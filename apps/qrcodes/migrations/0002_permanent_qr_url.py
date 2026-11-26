"""
Store each QR code's full URL permanently (it is never recalculated again), remove the
regenerate feature's fields, and drop the location link from scan events.
"""
from django.conf import settings
from django.db import migrations, models


def fill_permanent_urls(apps, schema_editor):
    QRCodeMapping = apps.get_model("qrcodes", "QRCodeMapping")
    for m in QRCodeMapping.objects.all():
        # Prefer the URL already printed in the QR image; otherwise the current base URL.
        m.qr_url = m.encoded_url or f"{settings.QR_BASE_URL}/q/{m.token}/"
        # Redraw the printed card once (the location line is gone). The QR pattern/URL stay identical.
        m.encoded_url = ""
        m.save(update_fields=["qr_url", "encoded_url"])


class Migration(migrations.Migration):
    dependencies = [
        ("qrcodes", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="qrcodemapping",
            name="qr_url",
            field=models.URLField(max_length=300, null=True, editable=False),
        ),
        migrations.RunPython(fill_permanent_urls, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="qrcodemapping",
            name="qr_url",
            field=models.URLField(
                editable=False, max_length=300, unique=True, verbose_name="Permanent QR URL",
                help_text="The exact URL encoded in the printed QR code. Fixed forever at creation.",
            ),
        ),
        migrations.RemoveField(model_name="qrcodemapping", name="regenerated_at"),
        migrations.RemoveField(model_name="qrcodemapping", name="regeneration_count"),
        migrations.RemoveIndex(model_name="qrscanevent", name="qrcodes_qrs_locatio_1ef254_idx"),
        migrations.RemoveField(model_name="qrscanevent", name="location"),
    ]
