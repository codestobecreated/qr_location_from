from django.apps import AppConfig


class LocationsConfig(AppConfig):
    """Kept only for migration history – the Location feature has been removed."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.locations"
    label = "locations"
