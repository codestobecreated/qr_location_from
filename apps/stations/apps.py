from django.apps import AppConfig


class StationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.stations"
    label = "stations"
    verbose_name = "Charging Stations"

    def ready(self):
        from . import signals  # noqa: F401
