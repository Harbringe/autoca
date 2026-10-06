from django.apps import AppConfig


class UsageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "usage"
    #: The heading these sections sit under in the admin sidebar.
    verbose_name = "Usage and cost"
