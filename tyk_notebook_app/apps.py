"""
Django app configuration for TyK Notebook Application.
"""
from django.apps import AppConfig


class TykNotebookConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tyk_notebook_app'
    verbose_name = 'TyK Notebook'

    def ready(self):
        # Import signal handlers if needed
        pass
