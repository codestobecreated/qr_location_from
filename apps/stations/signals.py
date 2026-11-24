from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.locations.models import Location

from .models import ChargingStation


@receiver(post_save, sender=ChargingStation)
def create_permanent_qr(sender, instance, created, **kwargs):
    """Every station gets exactly one permanent QR mapping the moment it is created."""
    from apps.qrcodes.models import QRCodeMapping
    from apps.qrcodes.services import build_qr_image

    if kwargs.get("raw"):
        return
    # On first save the Station ID is assigned just after this signal runs, so the printed card
    # is rendered lazily (on first preview/download) once the ID exists.
    skip_image = getattr(instance, "_skip_qr_image", False) or not instance.station_id
    mapping = QRCodeMapping.objects.filter(station=instance).first()
    if mapping is None:
        QRCodeMapping.create_for_station(
            instance, user=getattr(instance, "_created_by", None), build_image=not skip_image
        )
    elif skip_image:
        # Mark the printed card stale; it is re-rendered on next preview/download.
        QRCodeMapping.objects.filter(pk=mapping.pk).update(encoded_url="")
    else:
        # Station label changed – refresh the printed card. Token / URL are untouched.
        mapping.station = instance
        build_qr_image(mapping)


@receiver(post_save, sender=Location)
def refresh_location_qr_labels(sender, instance, created, **kwargs):
    from apps.qrcodes.models import QRCodeMapping

    if created or kwargs.get("raw"):
        return
    # Location name appears on printed cards: mark them stale, re-rendered lazily.
    QRCodeMapping.objects.filter(station__location=instance).update(encoded_url="")
