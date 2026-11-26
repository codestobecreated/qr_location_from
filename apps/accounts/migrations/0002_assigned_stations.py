"""Managers: 'assigned locations' become 'assigned stations' (every station of each old location)."""
from django.db import migrations, models


def copy_locations_to_stations(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    ChargingStation = apps.get_model("stations", "ChargingStation")
    for user in User.objects.all():
        location_ids = list(user.assigned_locations.values_list("pk", flat=True))
        if location_ids:
            user.assigned_stations.set(ChargingStation.objects.filter(location_id__in=location_ids))


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("stations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="assigned_stations",
            field=models.ManyToManyField(blank=True, related_name="managers", to="stations.chargingstation"),
        ),
        migrations.RunPython(copy_locations_to_stations, migrations.RunPython.noop),
        migrations.RemoveField(model_name="user", name="assigned_locations"),
    ]
