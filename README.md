# HR Recruitment Portal (ATS)

Django + Bootstrap 5 Applicant Tracking System.

**Status:** Phase 1 — new relational schema (`jobs`, `candidates` + education/experience/status-history/blacklist/email_registry)
and the public-facing Careers portal (open vacancies, job detail popup, application form with duplicate/blacklist
detection). The HR admin side (dashboard, candidate repository, interview scheduler, RBAC) is the next phase; in the
meantime, manage Jobs and Candidates via `/admin/`.

The previous single-table "Central Repository" version of this app is preserved in git history
(commit "Snapshot: single-table Central Repository recruitment portal (pre-ATS redesign)") if you need to refer back to it.

## Setup

```
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

- Public site: `http://127.0.0.1:8000/` (redirects to `/careers/`)
- HR admin: `http://127.0.0.1:8000/admin/` — create/edit `Job` postings and review submitted `Candidate` applications here for now.

## Data model

- `jobs.Job` — vacancy postings (`job_code` auto-generated, `status` Open/Closed, `is_archived`).
- `candidates.Candidate` — the single master candidate table; status is a column (`Open, Shortlisted, Round1,
  Interview, FinalSelection, Hired, Rejected, Blacklisted`), never a separate table per stage.
- `candidates.CandidateEducation` / `CandidateExperience` — one-to-many detail rows per candidate.
- `candidates.CandidateStatusHistory` — full audit trail of every status change.
- `candidates.Blacklist` — reason/who/when for blacklisted candidates (in addition to the `is_blacklisted` flag).
- `candidates.EmailRegistry` — one row per applicant email, used for duplicate/reapply detection
  (`candidates/services.py::check_email`).

## Switching to PostgreSQL / Azure SQL

SQLite is used by default. Set `DB_ENGINE=postgres` plus `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
(env vars) to point at Postgres; swap the `ENGINE` in `HR_management/settings.py` for an Azure-SQL-compatible
backend (e.g. `mssql-django`) the same way. Resumes are stored locally under `media/cvs/<job_id>/<candidate_code>/`;
swapping `DEFAULT_FILE_STORAGE` to `django-storages`' Azure Blob backend later needs no model changes.
