from django.apps import AppConfig


class SquadsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'squads'

    def ready(self):
        from squads import signals  # noqa: F401  (ledger, personal boards, deletion)
