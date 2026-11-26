from django.db import models, transaction
from django.urls import reverse

from apps.core.models import TimeStampedModel
from apps.core.utils import generate_code


class ChargingStation(TimeStampedModel):
    """
    One named QR code (e.g. "Tambaram bunk"). The model keeps its historical name
    for database compatibility; in the app it is shown simply as a "QR code".
    Its permanent token/URL live in QRCodeMapping (one-to-one).
    """

    station_id = models.CharField("QR ID", max_length=30, unique=True, null=True, blank=True, editable=False)
    name = models.CharField("QR name", max_length=200, db_index=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "QR code"
        verbose_name_plural = "QR codes"

    def __str__(self):
        return f"{self.name} ({self.station_id})" if self.station_id else self.name

    def get_absolute_url(self):
        mapping = getattr(self, "qr_mapping", None)
        return reverse("qrcodes:detail", args=[mapping.pk]) if mapping else reverse("qrcodes:list")

    @property
    def accepts_enquiries(self):
        mapping = getattr(self, "qr_mapping", None)
        return bool(mapping and mapping.is_active)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.station_id:
                self.station_id = generate_code(ChargingStation, "station_id", "QR", self.pk)
                ChargingStation.objects.filter(pk=self.pk).update(station_id=self.station_id)
