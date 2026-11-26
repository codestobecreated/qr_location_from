"""
"Charging stations" become plain named QR codes.

- charger type / capacity removed
- station status merged into the QR's own Active switch (inactive or under-maintenance stations -> QR inactive)
- IDs STN-000001 -> QR-000001 (also on existing leads' snapshot)
- printed card labels redrawn once; the QR token and permanent URL are NOT touched
"""
from django.db import migrations, models


def to_qr_only(apps, schema_editor):
    Station = apps.get_model("stations", "ChargingStation")
    Mapping = apps.get_model("qrcodes", "QRCodeMapping")
    Lead = apps.get_model("leads", "Lead")

    inactive_ids = list(Station.objects.exclude(status="active").values_list("pk", flat=True))
    Mapping.objects.filter(station_id__in=inactive_ids).update(is_active=False)

    for st in Station.objects.filter(station_id__startswith="STN-"):
        new_code = "QR-" + st.station_id[len("STN-"):]
        if Station.objects.filter(station_id=new_code).exclude(pk=st.pk).exists():
            continue
        Lead.objects.filter(station_id=st.pk, station_code=st.station_id).update(station_code=new_code)
        Station.objects.filter(pk=st.pk).update(station_id=new_code)

    Mapping.objects.update(encoded_url="")  # re-render card labels; qr_url is unchanged


class Migration(migrations.Migration):
    dependencies = [
        ("stations", "0003_remove_address_city_state"),
        ("qrcodes", "0002_permanent_qr_url"),
        ("leads", "0003_remove_source_city_state"),
    ]

    operations = [
        migrations.RunPython(to_qr_only, migrations.RunPython.noop),
        migrations.RemoveIndex(model_name="chargingstation", name="stations_ch_status_6c1f2b_idx"),
        migrations.RemoveField(model_name="chargingstation", name="charger_type"),
        migrations.RemoveField(model_name="chargingstation", name="charger_capacity_kw"),
        migrations.RemoveField(model_name="chargingstation", name="status"),
        migrations.AlterModelOptions(
            name="chargingstation",
            options={"ordering": ["name"], "verbose_name": "QR code", "verbose_name_plural": "QR codes"},
        ),
        migrations.AlterField(
            model_name="chargingstation", name="name",
            field=models.CharField(db_index=True, max_length=200, verbose_name="QR name"),
        ),
        migrations.AlterField(
            model_name="chargingstation", name="station_id",
            field=models.CharField(
                blank=True, editable=False, max_length=30, null=True, unique=True, verbose_name="QR ID"),
        ),
    ]
