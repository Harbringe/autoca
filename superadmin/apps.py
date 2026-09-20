from django.apps import AppConfig


class SuperadminConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "superadmin"
    #: The heading these sections sit under in the admin sidebar.
    verbose_name = "Platform"

    def ready(self):
        from superadmin import checks  # noqa: F401  (registers system checks)
