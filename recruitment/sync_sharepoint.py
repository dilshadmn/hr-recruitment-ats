"""
SharePoint sync utility for the HR Recruitment Portal.

Downloads the Central Repository workbook straight from its SharePoint
document library and imports it using the same duplicate-safe routine as
`manage.py import_candidates` (recruitment.services.import_workbook).

Usage:
    python manage.py shell -c "from recruitment.sync_sharepoint import sync; sync()"

Credentials/URL are read from settings (SHAREPOINT_SITE_URL, SHAREPOINT_USERNAME,
SHAREPOINT_PASSWORD, SHAREPOINT_FILE_URL) unless passed explicitly.
"""
import io
import os
import tempfile

from django.conf import settings

from . import services


def _get_client_context(site_url, username, password):
    from office365.runtime.auth.user_credential import UserCredential
    from office365.sharepoint.client_context import ClientContext

    return ClientContext(site_url).with_credentials(UserCredential(username, password))


def download_excel(site_url=None, username=None, password=None, file_url=None):
    """Read the Excel workbook from SharePoint and return a local temp file path."""
    site_url = site_url or settings.SHAREPOINT_SITE_URL
    username = username or settings.SHAREPOINT_USERNAME
    password = password or settings.SHAREPOINT_PASSWORD
    file_url = file_url or settings.SHAREPOINT_FILE_URL

    if not all([site_url, username, password, file_url]):
        raise ValueError(
            "SharePoint credentials are missing. Set SHAREPOINT_SITE_URL, "
            "SHAREPOINT_USERNAME, SHAREPOINT_PASSWORD and SHAREPOINT_FILE_URL "
            "(env vars or Django settings)."
        )

    ctx = _get_client_context(site_url, username, password)
    buffer = io.BytesIO()
    ctx.web.get_file_by_server_relative_url(file_url).download(buffer).execute_query()
    buffer.seek(0)

    tmp = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
    tmp.write(buffer.read())
    tmp.close()
    return tmp.name


def parse_sheets(local_path):
    """Parse every sheet with pandas and return {sheet_name: DataFrame}.

    Used for previewing/validating a downloaded workbook before syncing it
    into the database (the actual DB sync uses openpyxl via
    recruitment.services.import_workbook, which streams rows instead of
    loading the whole sheet into memory).
    """
    import pandas as pd

    return pd.read_excel(local_path, sheet_name=None, engine='openpyxl')


def sync(site_url=None, username=None, password=None, file_url=None, user=None):
    """Download the workbook from SharePoint and sync it into the database.

    Duplicate insertions are avoided because `services.import_workbook`
    skips any candidate row already matched on (email, full name, source),
    so this function is safe to run repeatedly (e.g. on a schedule).
    """
    local_path = download_excel(site_url, username, password, file_url)
    try:
        return services.import_workbook(local_path, user=user)
    finally:
        os.unlink(local_path)
