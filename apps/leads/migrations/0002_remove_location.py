"""Leads keep their station, QR token, city and state; only the location link is removed."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0001_initial"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="lead", name="leads_lead_locatio_aed3b3_idx"),
        migrations.RemoveField(model_name="lead", name="location"),
        migrations.RemoveField(model_name="lead", name="location_code"),
        migrations.RemoveField(model_name="lead", name="location_name"),
    ]
