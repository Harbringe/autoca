from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    #: The heading Users and Profiles sit under in the admin sidebar.
    verbose_name = "Accounts"

    def ready(self):
        from core import (
            checks,  # noqa: F401  (registers system checks)
            signals,  # noqa: F401  (one profile per account)
        )
