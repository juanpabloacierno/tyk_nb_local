"""
Django management command to import notebooks.
"""
from django.core.management.base import BaseCommand, CommandError
from tyk_notebook_app.importer import import_notebook, import_tyk_demo


class Command(BaseCommand):
    help = 'Import a notebook file (.py or .ipynb) into the database'

    def add_arguments(self, parser):
        parser.add_argument(
            'filepath',
            nargs='?',
            help='Path to the notebook file to import'
        )
        parser.add_argument(
            '--name',
            help='Name for the notebook (defaults to filename)'
        )
        parser.add_argument(
            '--description',
            default='',
            help='Description for the notebook'
        )
        parser.add_argument(
            '--demo',
            action='store_true',
            help='Import the TyK demo notebook'
        )

    def handle(self, *args, **options):
        if options['demo']:
            try:
                notebook = import_tyk_demo()
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Successfully imported demo notebook: {notebook.name}'
                    )
                )
                self.stdout.write(f'  - {notebook.cells.count()} cells imported')
                params_count = sum(c.parameters.count() for c in notebook.cells.all())
                self.stdout.write(f'  - {params_count} parameters extracted')
            except Exception as e:
                raise CommandError(f'Failed to import demo notebook: {e}')
            return

        filepath = options['filepath']
        if not filepath:
            raise CommandError('Please provide a filepath or use --demo')

        try:
            notebook = import_notebook(
                filepath=filepath,
                name=options['name'],
                description=options['description']
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully imported notebook: {notebook.name}'
                )
            )
            self.stdout.write(f'  - {notebook.cells.count()} cells imported')
            params_count = sum(c.parameters.count() for c in notebook.cells.all())
            self.stdout.write(f'  - {params_count} parameters extracted')
            self.stdout.write(f'  - Slug: {notebook.slug}')

        except FileNotFoundError as e:
            raise CommandError(str(e))
        except Exception as e:
            raise CommandError(f'Failed to import notebook: {e}')
