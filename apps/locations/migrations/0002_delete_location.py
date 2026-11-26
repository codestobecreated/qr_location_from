"""The Location module is removed. Runs after every link to it is gone."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("locations", "0001_initial"),
        ("accounts", "0002_assigned_stations"),
        ("stations", "0002_remove_location"),
        ("leads", "0002_remove_location"),
        ("qrcodes", "0002_permanent_qr_url"),
    ]

    operations = [
        migrations.DeleteModel(name="Location"),
    ]
