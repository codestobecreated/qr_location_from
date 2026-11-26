from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ChargingStation


@receiver(post_save, sender=ChargingStation)
def create_permanent_qr(sender, instance, created, **kwargs):
    """
    Every station gets exactly one permanent QR mapping the moment it is created.
    Later edits only refresh the printed card's text labels – the QR pattern, token and URL never change.
    """
    from apps.qrcodes.models import QRCodeMapping
    from apps.qrcodes.services import build_qr_image

    if kwargs.get("raw") or getattr(instance, "_main_qr", False):
        return
    # On first save the QR ID is assigned just after this signal runs, so the printed card
    # is rendered lazily (on first preview/download) once the ID exists.
    skip_image = getattr(instance, "_skip_qr_image", False) or not instance.station_id
    mapping = QRCodeMapping.objects.filter(station=instance).first()
    if mapping is None:
        QRCodeMapping.create_for_station(
            instance, user=getattr(instance, "_created_by", None), build_image=not skip_image
        )
    elif skip_image:
        QRCodeMapping.objects.filter(pk=mapping.pk).update(encoded_url="")
    else:
        mapping.station = instance
        build_qr_image(mapping)
