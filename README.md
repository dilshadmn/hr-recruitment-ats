# HR Recruitment Portal

Django + Bootstrap 5 replacement for the SharePoint "Central Repository" Excel workflow.

## Setup

```
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` (redirects to login, then `/dashboard/`).

## Sample data

Either load the bundled fixture:

```
python manage.py loaddata sample_data
```

or import the real workbook (defaults to `../Central Repository.xlsx` next to this project):

```
python manage.py import_candidates
python manage.py import_candidates --file "C:\path\to\Central Repository.xlsx"
```

Re-running `import_candidates` is safe — rows already imported (matched on name + email + source) are skipped.

## SharePoint sync

`recruitment/sync_sharepoint.py` downloads the workbook straight from SharePoint (via
`Office365-REST-Python-Client`) and reuses the same import routine. Configure
`SHAREPOINT_SITE_URL`, `SHAREPOINT_USERNAME`, `SHAREPOINT_PASSWORD`, `SHAREPOINT_FILE_URL`
(see `.env.example`), then:

```
python manage.py shell -c "from recruitment.sync_sharepoint import sync; sync()"
```

## Switching to PostgreSQL / Azure SQL

The project runs on SQLite out of the box. Set `DB_ENGINE=postgres` plus `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` (env vars or a `.env` loader of your
choice) to point at Postgres; swap the `ENGINE` in `HR_management/settings.py` for an
Azure-SQL-compatible backend (e.g. `mssql-django`) the same way.

## Roles & auth

Two Django groups (`Admin`, `HR User`) are created automatically after migration.
Assign users to them from `/admin/`.
