"""Charging stations no longer belong to a location (name, address, city and state stay on the station)."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stations", "0001_initial"),
        # managers' station list is built from station.location first
        ("accounts", "0002_assigned_stations"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="chargingstation", name="stations_ch_locatio_9e962a_idx"),
        migrations.AddIndex(
            model_name="chargingstation",
            index=models.Index(fields=["status", "name"], name="stations_ch_status_6c1f2b_idx"),
        ),
        migrations.RemoveField(model_name="chargingstation", name="location"),
    ]
