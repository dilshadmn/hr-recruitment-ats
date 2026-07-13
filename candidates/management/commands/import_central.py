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
    Candidate, CandidateEducation, CandidateStatusHistory, CommunicationLog,
    EmailRegistry, Note, Offer,
)
from interviews.models import Interview
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


def _norm_source(v):
    """Consolidate any referral-type source into a single 'Employee reference'."""
    s = _s(v, 255)
    if s and 'ref' in s.lower():
        return 'Employee reference'
    return s


def _call_outcome(raw):
    """Map an Excel 'Call Status' to a CommunicationLog.Outcome, or None."""
    from candidates.models import CommunicationLog as CL
    s = (raw or '').strip().lower()
    if s == 'nr' or 'non reachable' in s or 'unable' in s:
        return CL.Outcome.UNABLE
    if 'call back' in s or s == 'callback':
        return CL.Outcome.CALLBACK
    if 'not shortlist' in s:
        return CL.Outcome.NOT_SHORTLISTED
    if 'shortlist' in s:
        return CL.Outcome.SHORTLISTED
    return None


def _is_hold(sl):
    """True if the Shortlisted row indicates the candidate is on hold."""
    if not sl:
        return False
    blob = f"{sl.get('Final Status') or ''} {sl.get('Current Stage') or ''}".lower()
    return 'hold' in blob


def _as_datetime(v):
    if isinstance(v, datetime):
        return v if timezone.is_aware(v) else timezone.make_aware(v)
    return None


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _interview_outcome(raw):
    """Map a Round-1/Interview status string to (Interview.status, Interview.result).
    Returns None when no interview effectively happened (blank / N/A)."""
    s = (raw or '').strip().lower()
    if s in ('', 'na', 'n/a', 'nil', '-'):
        return None
    if s in ('cleared', 'selected', 'shortlisted', 'pass', 'passed'):
        return Interview.Status.COMPLETED, Interview.Result.PASS_
    if s in ('rejected', 'not cleared', 'fail', 'failed', 'not selected'):
        return Interview.Status.COMPLETED, Interview.Result.FAIL
    if s in ('not attended', 'no show', 'absent', 'did not attend'):
        return Interview.Status.CANCELLED, Interview.Result.PENDING
    return Interview.Status.COMPLETED, Interview.Result.PENDING


def _num(v):
    """Parse a numeric cell (int/float/'2.5'/'2 years') -> Decimal-friendly float or None."""
    if v in (None, ''):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r'\d+(\.\d+)?', str(v))
    return float(m.group()) if m else None


STAGE_ORDER = [STATUS.OPEN, STATUS.SHORTLISTED, STATUS.ROUND1, STATUS.INTERVIEW,
               STATUS.FINAL_SELECTION, STATUS.HIRED]


def build_stage_history(spec):
    """Reconstruct a candidate's dated stage timeline from the Excel signals:
    Applied -> Shortlist -> Round 1 -> Interview -> Final Selection -> Hire
    (or -> Rejected). Missing dates carry forward the last known date so the
    ordering stays correct. Returns [(old_status, new_status, when, remark)]."""
    sl = spec.get('sl') or {}
    applied = spec.get('appdate')
    screened = spec.get('screened_on') or _as_datetime(sl.get('Screened On'))
    call = _as_datetime(sl.get('Call made date'))
    r1 = _as_datetime(sl.get('Round 1 Date'))
    iv = _as_datetime(sl.get('Interview Date'))
    current = spec['status']

    reached = 0
    if sl or screened or call or current in STAGE_ORDER[1:]:
        reached = 1
    # a real Round-1/Interview outcome (not blank/N/A) counts as reaching that stage
    if r1 or _interview_outcome(_s(sl.get('Round 1 Status'))):
        reached = max(reached, 2)
    if iv or _interview_outcome(_s(sl.get('Interview Status'))):
        reached = max(reached, 3)
    if current in STAGE_ORDER:
        reached = max(reached, STAGE_ORDER.index(current))

    date_for = {0: applied, 1: screened or call, 2: r1, 3: iv, 4: None, 5: None}
    out, last, prev = [], applied or timezone.now(), ''
    for idx in range(reached + 1):
        when = date_for.get(idx) or last
        if when < last:
            when = last
        out.append((prev, STAGE_ORDER[idx], when, 'Applied (imported)' if idx == 0 else 'Imported'))
        prev, last = STAGE_ORDER[idx], when

    if current in (STATUS.REJECTED, STATUS.BLACKLISTED):
        label = 'Rejected' if current == STATUS.REJECTED else 'Blacklisted'
        out.append((prev, current, last, f'{label} (imported)'))
    return out


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
            em = _s(d.get('Mail ID'))
            if em:
                short_by_email[em.lower()] = d
            nm = _norm_name(d.get('Name'))
            if nm:
                short_by_name.setdefault(nm, d)

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

        pstats = None
        if not dry:
            obj_by_code = self._write(specs, jobs)
            pstats = self._import_pipeline(shortlisted, list(obj_by_code.values()))

        self.stdout.write(self.style.SUCCESS(
            f"\n{'DRY RUN - ' if dry else ''}Done. Candidates: {len(specs)} | "
            f"with real email: {n_email} | placeholder: {len(specs) - n_email} | "
            f"duplicates flagged: {n_dup} | shortlisted-only: {n_short}"))
        self.stdout.write('Status: ' + ', '.join(f'{k}={v}' for k, v in sorted(by_status.items())))
        self.stdout.write('Role: ' + ', '.join(f'{k}={v}' for k, v in sorted(by_role.items())))
        if pstats:
            self.stdout.write('Pipeline: ' + ', '.join(f'{k}={v}' for k, v in pstats.items()))

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
            openings = int(req) if isinstance(req, (int, float)) else 1
            job, _ = Job.objects.get_or_create(
                title=title,
                defaults={'job_code': code, 'status': status, 'closing_date': closing,
                          'openings': openings,
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

            sl = short_by_email.get(raw_email.lower()) if raw_email else None
            if not sl:
                sl = short_by_name.get(_norm_name(name))
            status, note_text = compute_status(
                _s(d.get('Status')),
                _s(sl.get('Current Stage')) if sl else None,
                _s(sl.get('Final Status')) if sl else None)

            notes = [t for t in (_s(d.get('Remarks')), note_text) if t]
            specs.append(dict(
                full_name=name or '(no name)', email=email, real_email=real, is_dup=is_dup,
                phone=_s(d.get('Mobile Number'), 20), role=norm_role(d.get('Role Selected')),
                qual=_s(d.get('Education'), 255),
                resume_url=_s(d.get('CV Link') or d.get('Hyper Link'), 1000),
                source=_norm_source(d.get('Source')), status=status,
                appdate=_as_datetime(d.get('Mail Date')),
                screened_on=_as_datetime(d.get('Screened On')), sl=sl, notes=notes,
                on_hold=_is_hold(sl),
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
                source=_norm_source(d.get('Source')), status=status,
                appdate=_as_datetime(d.get('Resume Received')),
                screened_on=_as_datetime(d.get('Screened On')), sl=d,
                notes=[t for t in (note_text,) if t], on_hold=_is_hold(d),
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
                status=sp['status'], is_duplicate=sp['is_dup'],
                is_on_hold=sp.get('on_hold', False))
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

        # 3) status history — reconstructed dated stage timeline per candidate
        hist = []
        for c in cands:
            obj = obj_by_code[c.candidate_code]
            for old, new, when, remark in build_stage_history(c._sp):
                hist.append(CandidateStatusHistory(
                    candidate=obj, old_status=old, new_status=new,
                    changed_at=when, remarks=remark))
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
        return obj_by_code

    # ------------------------------------------------------- pipeline detail
    def _import_pipeline(self, shortlisted, candidates):
        """Third pass: attach Round-1/Interview records, screening calls, offers,
        education and experience/CTC from the Shortlisted sheet to the matching
        candidate (by email, else normalized name; prefer the role-matched one)."""
        by_email, by_name = {}, {}
        for c in candidates:
            if c.email and not c.email.endswith('@import.local'):
                by_email.setdefault(c.email.lower(), []).append(c)
            nm = _norm_name(c.full_name)
            if nm:
                by_name.setdefault(nm, []).append(c)

        def resolve(row):
            em = _s(row.get('Mail ID'))
            nm = _norm_name(row.get('Name'))
            cands = (by_email.get(em.lower()) if em else None) or (by_name.get(nm) if nm else None)
            if not cands:
                return None
            role = norm_role(row.get('Role Selected'))
            for c in cands:
                if c.job and c.job.title == role:
                    return c
            return cands[0]

        interviews, comms, offers, notes, edus = [], [], [], [], []
        cand_updates = {}

        for d in shortlisted:
            c = resolve(d)
            if c is None:
                continue

            # screening call -> CommunicationLog (date embedded in subject since
            # logged_at is auto-set; keeps the historical date visible)
            call_date = _as_datetime(d.get('Call made date'))
            call_status = _s(d.get('Call Status'))
            if call_date or call_status:
                comms.append(CommunicationLog(
                    candidate=c, channel=CommunicationLog.Channel.PHONE,
                    subject=f"Screening call: {call_status or 'made'}"[:255],
                    message=_s(d.get('Call Remarks ')),
                    outcome=_call_outcome(call_status),
                    logged_at=call_date or c.created_at or timezone.now()))

            # Round 1 + Interview -> Interview records
            for date_col, status_col, rtype in (
                    ('Round 1 Date', 'Round 1 Status', Interview.RoundType.ROUND1),
                    ('Interview Date', 'Interview Status', Interview.RoundType.FINAL)):
                idate = _as_datetime(d.get(date_col))
                outcome = _interview_outcome(_s(d.get(status_col)))
                if not idate and not outcome:
                    continue
                status, result = outcome or (Interview.Status.SCHEDULED, Interview.Result.PENDING)
                sched = idate or c.created_at or timezone.now()
                fb = f"Imported. {status_col}: {_s(d.get(status_col)) or '-'}"
                sby = _s(d.get('Screened By'))
                if sby:
                    fb += f" (screened by {sby})"
                if not idate:
                    fb += " [date approximate]"
                interviews.append(Interview(
                    candidate=c, round_type=rtype, scheduled_date=sched,
                    mode=Interview.Mode.VIDEO, status=status, result=result, feedback=fb))

            # Offer
            if str(d.get('Offer Rolled Out') or '').strip().lower() == 'yes':
                accepted = str(d.get('Offer Accepted') or '').strip().lower() == 'yes'
                offers.append(Offer(
                    candidate=c,
                    status=Offer.Status.ACCEPTED if accepted else Offer.Status.SENT,
                    sent_at=_as_datetime(d.get('Interview Date'))))
                if str(d.get('Joined') or '').strip().lower() == 'yes':
                    notes.append(Note(candidate=c, text='Candidate joined (imported).'))

            # Education (College / Qualification)
            college = _s(d.get('College'), 255)
            qual = _s(d.get('Qualification') or d.get('Education'), 255)
            if college or qual:
                edus.append(CandidateEducation(
                    candidate=c, qualification=qual or 'N/A', institution=college))

            # Experience / CTC -> candidate fields
            exp = _num(d.get('Relevent Experience'))
            ctc = d.get('Current CTC')
            if exp is not None or ctc not in (None, ''):
                if exp is not None:
                    c.total_experience_years = round(exp, 1)
                if ctc not in (None, ''):
                    c.current_salary = (f"{ctc} LPA" if isinstance(ctc, (int, float))
                                        else _s(ctc, 100))
                cand_updates[c.pk] = c

        # write everything in batches
        for model, rows, label in (
                (Interview, interviews, 'interviews'), (CommunicationLog, comms, 'calls'),
                (Offer, offers, 'offers'), (Note, notes, 'join-notes'),
                (CandidateEducation, edus, 'education')):
            for batch in _chunks(rows, BATCH):
                self._retry(lambda m=model, b=batch: m.objects.bulk_create(b, batch_size=BATCH),
                            what=label)

        upd = list(cand_updates.values())
        for batch in _chunks(upd, BATCH):
            self._retry(lambda b=batch: Candidate.objects.bulk_update(
                b, ['total_experience_years', 'current_salary'], batch_size=BATCH), what='exp/ctc')

        return {'interviews': len(interviews), 'calls': len(comms), 'offers': len(offers),
                'education': len(edus), 'exp/ctc': len(upd)}
