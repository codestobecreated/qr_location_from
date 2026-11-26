"""Leads no longer copy the station's city/state (no location details anywhere)."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0002_remove_location"),
    ]

    operations = [
        migrations.RemoveField(model_name="lead", name="source_city"),
        migrations.RemoveField(model_name="lead", name="source_state"),
    ]
