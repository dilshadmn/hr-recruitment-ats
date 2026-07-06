from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from recruitment import services


class Command(BaseCommand):
    help = (
        "Import Roles and Candidates from a SharePoint-exported Central Repository "
        "Excel workbook (sheets: 'ROLE' and 'Central Sheet'). Safe to re-run — "
        "already-imported rows are skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            dest='file',
            default=None,
            help='Path to the .xlsx workbook (defaults to settings.CENTRAL_REPOSITORY_XLSX)',
        )

    def handle(self, *args, **options):
        filepath = options['file'] or settings.CENTRAL_REPOSITORY_XLSX
        self.stdout.write(f"Importing from: {filepath}")
        try:
            result = services.import_workbook(filepath)
        except FileNotFoundError as exc:
            raise CommandError(f"Workbook not found: {filepath}") from exc

        self.stdout.write(self.style.SUCCESS(
            f"Roles: {result['roles_created']} created, {result['roles_updated']} updated. "
            f"Candidates: {result['candidates_created']} created, {result['candidates_skipped']} skipped (already imported)."
        ))
