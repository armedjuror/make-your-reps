from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from fitness.library import import_file

DEFAULT = Path(__file__).resolve().parents[2] / 'fixtures' / 'exercises.json'


class Command(BaseCommand):
    help = ('Validate exercises.json against fitness/schemas/exercise.schema.json and its assets, '
            'then upsert by id. Ids missing from the file are retired, never deleted.')

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default=str(DEFAULT))
        parser.add_argument('--dry-run', action='store_true', help='Validate and print the diff; change nothing')
        parser.add_argument('--keep-missing', action='store_true',
                            help='Do not retire exercises that are absent from the file (partial batches)')

    def handle(self, path, dry_run, keep_missing, **opts):
        if not Path(path).exists():
            raise CommandError(f'{path} not found')
        report = import_file(path, dry_run=dry_run, retire_missing=not keep_missing)
        for line in report.lines():
            self.stdout.write(line)
        if not report.ok:
            raise CommandError(f'{len(report.errors)} error(s); nothing imported')
        self.stdout.write(self.style.SUCCESS('Dry run: nothing written' if dry_run else 'Imported'))
