"""
Import the legacy "Central Repository.xlsx" workbook into the ATS.

Usage:
    python manage.py import_central "Sample Data/Central Repository.xlsx"
    python manage.py import_central "..." --dry-run     # analyse only, write nothing
    python manage.py import_central "..." --flush        # wipe imported data first

Scope (agreed): vacancies (ROLE sheet) + one Candidate per application row across
the Central Sheet AND the Shortlisted sheet (deduped by email+name), with pipeline
status enriched from the Shortlisted sheet. Writes use batched bulk_create with
retry so a flaky serverless connection can't corrupt a huge single transaction.
"""
import re
import time
import uuid
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.utils import OperationalError
from django.utils import timezone

from candidates.models import (
    Candidate, CandidateStatusHistory, EmailRegistry, Note,
)
from jobs.models import Job

STATUS = Candidate.Status
GENERAL = 'General Application'
BATCH = 100


def norm_role(value):
    """Map a raw 'Role Selected' string to one of the 9 official role titles or
    the General Application bucket. Rules confirmed with the user:
      - data/business analyst & analytics titles -> Jr. Analytics Consultant
      - any HR / human-resource title            -> HRBP
    """
    if value in (None, ''):
        return GENERAL
    s = str(value).strip().lower().replace('�', '-')
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()

    if 'general application' in s:
        return GENERAL
    if 'sales' in s and 'marketing' in s:
        return 'Sales and Marketing Manager- UAE'
    if ('senior' in s or 'sr' in s.split()) and 'sales' in s:
        return 'Sr. Sales Manager'
    if 'sales associate' in s or s == 'sale associate':
        return 'Sales Associate'
    if 'marketing associate' in s:
        return 'Marketing Associate'
    if 'programme manager' in s or 'program manager' in s or \
       ('program' in s and 'project' in s and 'manager' in s):
        return 'Program Manager'
    if 'program associate' in s or 'programme associate' in s:
        return 'Program Associate'
    if 'admin' in s or 'office assistant' in s:
        return 'Administrative Assistant'
    if 'hr' in s.split() or 'hrbp' in s or 'human resource' in s or 'business partner' in s:
        return 'HRBP'
    if ('analyt' in s or 'analysis' in s or 'analyst' in s or
            'data scien' in s or 'business intelligence' in s):
        return 'Jr. Analytics Consultant'
    return GENERAL


def compute_status(central_status, short_stage, short_final):
    """Return (app_status, note_text). Shortlisted-sheet stage wins if present."""
    if short_stage or short_final:
        blob = f"{short_stage or ''} {short_final or ''}".lower()
        if 'hired' in blob:
            return STATUS.HIRED, None
        if 'rejected' in blob:
            return STATUS.REJECTED, None
        if 'decision pending' in blob:
            return STATUS.FINAL_SELECTION, None
        if 'interview' in blob:
            return STATUS.INTERVIEW, None
        if 'round 1' in blob or 'round1' in blob:
            return STATUS.ROUND1, None
        if 'non reachable' in blob:
            return STATUS.SHORTLISTED, 'Imported stage: Non Reachable'
        if 'hold' in blob:
            return STATUS.SHORTLISTED, 'Imported stage: On Hold'
        if 'call pending' in blob:
            return STATUS.SHORTLISTED, None
        return STATUS.SHORTLISTED, None

    cs = (central_status or '').strip().lower()
    if cs == 'shortlisted':
        return STATUS.SHORTLISTED, None
    if cs in ('not shortlisted', 'rejected'):
        return STATUS.REJECTED, None
    if cs == 'not applicable':
        return STATUS.REJECTED, 'Imported status: Not Applicable'
    return STATUS.OPEN, None


def _rows(ws, header_idx):
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(c).strip() if c is not None else '' for c in rows[header_idx]]
    out = []
    for r in rows[header_idx + 1:]:
        if all(c in (None, '') for c in r):
            continue
        out.append(dict(zip(hdr, r)))
    return out


def _norm_name(v):
    if v in (None, ''):
        return None
    s = re.sub(r'[^a-z0-9 ]', ' ', str(v).strip().lower())
    return re.sub(r'\s+', ' ', s).strip() or None


def _s(v, limit=None):
    if v in (None, ''):
        return None
    s = str(v).strip()
    return s[:limit] if limit else s


def _as_datetime(v):
    if isinstance(v, datetime):
        return v if timezone.is_aware(v) else timezone.make_aware(v)
    return None


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class Command(BaseCommand):
    help = 'Import the legacy Central Repository.xlsx workbook.'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--flush', action='store_true',
                            help='Delete previously imported candidates/jobs first.')

    def handle(self, *args, **opts):
        try:
            import openpyxl
        except ImportError:
            raise CommandError('openpyxl is required: pip install openpyxl')

        path, dry = opts['path'], opts['dry_run']
        self.stdout.write(f'Loading {path} ...')
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except FileNotFoundError:
            raise CommandError(f'File not found: {path}')

        role_rows = _rows(wb['ROLE'], 0)
        central = _rows(wb['Central Sheet'], 0)
        shortlisted = _rows(wb['Shortlisted'], 4)

        short_by_email, short_by_name = {}, {}
        for d in shortlisted:
            stage = (_s(d.get('Current Stage')), _s(d.get('Final Status')))
            em = _s(d.get('Mail ID'))
            if em:
                short_by_email[em.lower()] = stage
            nm = _norm_name(d.get('Name'))
            if nm:
                short_by_name.setdefault(nm, stage)

        if opts['flush'] and not dry:
            self.stdout.write('Flushing previously imported data...')
            CandidateStatusHistory.objects.all().delete()
            Note.objects.all().delete()
            EmailRegistry.objects.all().delete()
            Candidate.objects.all().delete()
            Job.objects.all().delete()

        jobs = self._create_jobs(role_rows, dry)

        # --- Collect specs (no DB writes) from both sheets ---
        specs, seen_emails, seen_names = [], set(), set()
        self._collect_central(central, short_by_email, short_by_name, jobs,
                              specs, seen_emails, seen_names)
        self._collect_shortlisted_only(shortlisted, jobs, specs, seen_emails, seen_names)

        # --- Report ---
        from collections import Counter
        by_status = Counter(sp['status'] for sp in specs)
        by_role = Counter(sp['role'] for sp in specs)
        n_email = sum(1 for sp in specs if sp['real_email'])
        n_dup = sum(1 for sp in specs if sp['is_dup'])
        n_short = sum(1 for sp in specs if sp['from_shortlisted'])

        if not dry:
            self._write(specs, jobs)

        self.stdout.write(self.style.SUCCESS(
            f"\n{'DRY RUN - ' if dry else ''}Done. Candidates: {len(specs)} | "
            f"with real email: {n_email} | placeholder: {len(specs) - n_email} | "
            f"duplicates flagged: {n_dup} | shortlisted-only: {n_short}"))
        self.stdout.write('Status: ' + ', '.join(f'{k}={v}' for k, v in sorted(by_status.items())))
        self.stdout.write('Role: ' + ', '.join(f'{k}={v}' for k, v in sorted(by_role.items())))

    # ------------------------------------------------------------------ jobs
    def _create_jobs(self, role_rows, dry):
        jobs = {}
        for d in role_rows:
            title = _s(d.get('ROLE'))
            if not title:
                continue
            code = _s(d.get('ID')) or ''
            active = (_s(d.get('ACTIVE')) or '').lower()
            status = Job.Status.OPEN if active == 'yes' else Job.Status.CLOSED
            req = d.get('REQUIREMENT')
            closing = d.get('CLOSING DATE')
            closing = closing.date() if isinstance(closing, datetime) else None
            if dry:
                jobs[title] = title
                continue
            job, _ = Job.objects.get_or_create(
                title=title,
                defaults={'job_code': code, 'status': status, 'closing_date': closing,
                          'requirements': f'Openings: {req}' if req else None})
            jobs[title] = job
        if dry:
            jobs[GENERAL] = GENERAL
        else:
            jobs[GENERAL] = Job.objects.get_or_create(
                title=GENERAL, defaults={'job_code': 'GENERAL', 'status': Job.Status.OPEN})[0]
        self.stdout.write(f'Vacancies ready: {len(jobs)}')
        return jobs

    # -------------------------------------------------------------- collect
    def _collect_central(self, central, short_by_email, short_by_name, jobs,
                        specs, seen_emails, seen_names):
        for i, d in enumerate(central, start=1):
            name = _s(d.get('Name'), 255)
            raw_email = _s(d.get('Mail ID'), 254)
            if not name and not raw_email:
                continue
            if raw_email:
                email, real = raw_email, True
                is_dup = raw_email.lower() in seen_emails
                seen_emails.add(raw_email.lower())
            else:
                email, real, is_dup = f'noemail-{i}@import.local', False, False
            if name:
                seen_names.add(_norm_name(name))

            short = short_by_email.get(raw_email.lower()) if raw_email else None
            if not short:
                short = short_by_name.get(_norm_name(name))
            status, note_text = compute_status(
                _s(d.get('Status')), short[0] if short else None, short[1] if short else None)

            notes = [t for t in (_s(d.get('Remarks')), note_text) if t]
            specs.append(dict(
                full_name=name or '(no name)', email=email, real_email=real, is_dup=is_dup,
                phone=_s(d.get('Mobile Number'), 20), role=norm_role(d.get('Role Selected')),
                qual=_s(d.get('Education'), 255),
                resume_url=_s(d.get('CV Link') or d.get('Hyper Link'), 1000),
                source=_s(d.get('Source'), 255), status=status,
                appdate=_as_datetime(d.get('Mail Date')), notes=notes,
                hist_remark='Imported from Central Repository.xlsx', from_shortlisted=False))

    def _collect_shortlisted_only(self, shortlisted, jobs, specs, seen_emails, seen_names):
        for j, d in enumerate(shortlisted, start=1):
            name = _s(d.get('Name'), 255)
            raw_email = _s(d.get('Mail ID'), 254)
            if not name and not raw_email:
                continue
            key_name = _norm_name(name)
            if (raw_email and raw_email.lower() in seen_emails) or \
               (key_name and key_name in seen_names):
                continue
            if raw_email:
                email, real = raw_email, True
                seen_emails.add(raw_email.lower())
            else:
                email, real = f'noemail-sl-{j}@import.local', False
            if key_name:
                seen_names.add(key_name)

            status, note_text = compute_status(
                None, _s(d.get('Current Stage')), _s(d.get('Final Status')))
            specs.append(dict(
                full_name=name or '(no name)', email=email, real_email=real, is_dup=False,
                phone=_s(d.get('Mobile Number'), 20), role=norm_role(d.get('Role Selected')),
                qual=_s(d.get('Qualification') or d.get('Education'), 255),
                resume_url=_s(d.get('CV Link') or d.get('Hyper Link'), 1000),
                source=_s(d.get('Source'), 255), status=status,
                appdate=_as_datetime(d.get('Resume Received')),
                notes=[t for t in (note_text,) if t],
                hist_remark='Imported from Central Repository.xlsx (Shortlisted sheet)',
                from_shortlisted=True))

    # ---------------------------------------------------------------- write
    def _retry(self, fn, what='batch', attempts=4):
        for a in range(attempts):
            try:
                with transaction.atomic():
                    return fn()
            except OperationalError as e:
                connection.close()  # force a fresh connection / wake the DB
                if a == attempts - 1:
                    raise
                self.stdout.write(self.style.WARNING(
                    f'  {what}: connection issue, retrying ({a + 1}/{attempts})...'))
                time.sleep(5)

    def _write(self, specs, jobs):
        # 1) candidates (unique candidate_code lets us re-fetch PKs afterwards,
        #    because SQL Server bulk_create does NOT populate object PKs)
        cands = []
        for sp in specs:
            c = Candidate(
                candidate_code=f'CAND-{uuid.uuid4().hex[:10].upper()}',
                full_name=sp['full_name'], email=sp['email'], phone=sp['phone'],
                job=jobs.get(sp['role']), qualification=sp['qual'],
                resume_url=sp['resume_url'], source=sp['source'],
                status=sp['status'], is_duplicate=sp['is_dup'])
            c._sp = sp
            cands.append(c)

        total = len(cands)
        for n, batch in enumerate(_chunks(cands, BATCH), 1):
            done = min(n * BATCH, total)
            self._retry(lambda b=batch: Candidate.objects.bulk_create(b, batch_size=BATCH),
                        what=f'candidates {done}/{total}')
        self.stdout.write(f'  inserted {total} candidates')

        # re-fetch persisted rows (with PKs) keyed by candidate_code
        obj_by_code = {}
        codes = [c.candidate_code for c in cands]
        for cbatch in _chunks(codes, 500):
            for obj in Candidate.objects.filter(candidate_code__in=cbatch):
                obj_by_code[obj.candidate_code] = obj

        # 2) preserve original application dates
        dated = []
        for c in cands:
            obj = obj_by_code[c.candidate_code]
            if c._sp['appdate']:
                obj.created_at = c._sp['appdate']
                dated.append(obj)
        for batch in _chunks(dated, BATCH):
            self._retry(lambda b=batch: Candidate.objects.bulk_update(b, ['created_at'], batch_size=BATCH),
                        what='dates')

        # 3) status history
        hist = [CandidateStatusHistory(candidate=obj_by_code[c.candidate_code], old_status='',
                                       new_status=c.status, remarks=c._sp['hist_remark'])
                for c in cands]
        for batch in _chunks(hist, BATCH):
            self._retry(lambda b=batch: CandidateStatusHistory.objects.bulk_create(b, batch_size=BATCH),
                        what='history')

        # 4) notes
        notes = [Note(candidate=obj_by_code[c.candidate_code], text=t)
                 for c in cands for t in c._sp['notes']]
        for batch in _chunks(notes, BATCH):
            self._retry(lambda b=batch: Note.objects.bulk_create(b, batch_size=BATCH), what='notes')

        # 5) email registry (one row per unique real email)
        reg = {}
        for c in cands:
            if not c._sp['real_email']:
                continue
            key = c.email.lower()
            if key in reg:
                reg[key].application_count += 1
            else:
                reg[key] = EmailRegistry(email=c.email,
                                         first_candidate=obj_by_code[c.candidate_code],
                                         application_count=1)
        regs = list(reg.values())
        for batch in _chunks(regs, BATCH):
            self._retry(lambda b=batch: EmailRegistry.objects.bulk_create(b, batch_size=BATCH),
                        what='registry')
        self.stdout.write(f'  history={len(hist)} notes={len(notes)} registry={len(regs)}')
