"""No location details on stations: address, city and state are removed (a station is just a named QR)."""
from django.db import migrations


def redraw_printed_cards(apps, schema_editor):
    # The city/state line disappears from the printed card. Marking the image stale makes it re-render
    # once with the SAME permanent qr_url – the QR pattern and URL do not change.
    QRCodeMapping = apps.get_model("qrcodes", "QRCodeMapping")
    QRCodeMapping.objects.update(encoded_url="")


class Migration(migrations.Migration):
    dependencies = [
        ("stations", "0002_remove_location"),
        ("qrcodes", "0002_permanent_qr_url"),
    ]

    operations = [
        migrations.RemoveIndex(model_name="chargingstation", name="stations_ch_state_e7ff24_idx"),
        migrations.RemoveField(model_name="chargingstation", name="address"),
        migrations.RemoveField(model_name="chargingstation", name="city"),
        migrations.RemoveField(model_name="chargingstation", name="state"),
        migrations.RunPython(redraw_printed_cards, migrations.RunPython.noop),
    ]
