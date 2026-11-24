import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.locations.models import Location
from apps.stations.models import ChargingStation

TOKEN_BYTES = 16  # 128 bits of entropy -> 22 URL-safe characters


def token_in_use(token):
    return (
        QRCodeMapping.objects.filter(token=token).exists()
        or QRTokenHistory.objects.filter(token=token).exists()
    )


def new_unique_token():
    """Cryptographically secure token that has never been used by any station (current or retired)."""
    for _ in range(20):
        token = secrets.token_urlsafe(TOKEN_BYTES)
        if not token_in_use(token):
            return token
    raise RuntimeError("Could not generate a unique QR token.")  # pragma: no cover


class QRCodeMapping(models.Model):
    """The single, permanent link between a QR token and one charging station."""

    station = models.OneToOneField(ChargingStation, on_delete=models.PROTECT, related_name="qr_mapping")
    token = models.CharField(max_length=64, unique=True, editable=False)
    is_active = models.BooleanField(default=True, db_index=True)
    image = models.ImageField(upload_to="qrcodes/", blank=True)
    encoded_url = models.URLField(max_length=300, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    regenerated_at = models.DateTimeField(null=True, blank=True)
    regeneration_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "QR code mapping"
        ordering = ["station__name"]

    def __str__(self):
        return f"{self.station} → {self.token}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("qrcodes:detail", args=[self.pk])

    # -- Integrity guards ----------------------------------------------------
    def save(self, *args, **kwargs):
        if self.pk:
            original = QRCodeMapping.objects.filter(pk=self.pk).values("token", "station_id").first()
            if original and not getattr(self, "_allow_token_change", False):
                if original["token"] != self.token:
                    raise ValidationError("QR tokens are permanent. Use the regenerate workflow.")
                if original["station_id"] != self.station_id:
                    raise ValidationError("A QR code can never be moved to a different station.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("QR mappings are permanent and cannot be deleted. Deactivate instead.")

    # -- Business helpers -----------------------------------------------------
    @property
    def public_url(self):
        return f"{settings.QR_BASE_URL}/q/{self.token}/"

    @property
    def effective_status(self):
        """Active only if the QR, its station and its location are all active."""
        if not self.is_active:
            return "inactive"
        if not self.station.is_active or not self.station.location.is_active:
            return "station_inactive"
        return "active"

    @property
    def image_is_stale(self):
        return not self.image or self.encoded_url != self.public_url

    @classmethod
    def create_for_station(cls, station, user=None, build_image=True):
        for _ in range(5):
            try:
                with transaction.atomic():
                    mapping = cls.objects.create(station=station, token=new_unique_token(), created_by=user)
                break
            except IntegrityError:
                existing = cls.objects.filter(station=station).first()
                if existing:
                    return existing
        else:  # pragma: no cover
            raise RuntimeError("Unable to create QR mapping.")
        if build_image:
            from .services import build_qr_image

            build_qr_image(mapping)
        return mapping

    def regenerate(self, user, reason):
        """Retire the current token (kept in history, never reused) and issue a new one."""
        with transaction.atomic():
            locked = QRCodeMapping.objects.select_for_update().get(pk=self.pk)
            QRTokenHistory.objects.create(
                mapping=locked,
                station=locked.station,
                token=locked.token,
                issued_at=locked.regenerated_at or locked.created_at,
                retired_by=user,
                reason=reason,
            )
            locked.token = new_unique_token()
            locked.regenerated_at = timezone.now()
            locked.regeneration_count += 1
            locked._allow_token_change = True
            locked.save()
        from .services import build_qr_image

        build_qr_image(locked)
        return locked


class QRTokenHistory(models.Model):
    """Retired tokens. They keep pointing at their original station for audit, but no longer accept enquiries."""

    mapping = models.ForeignKey(QRCodeMapping, on_delete=models.PROTECT, related_name="history")
    station = models.ForeignKey(ChargingStation, on_delete=models.PROTECT, related_name="retired_tokens")
    token = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField()
    retired_at = models.DateTimeField(auto_now_add=True)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reason = models.TextField()

    class Meta:
        ordering = ["-retired_at"]
        verbose_name_plural = "QR token history"

    def __str__(self):
        return f"{self.token} (retired {self.retired_at:%Y-%m-%d})"


class QRScanEvent(models.Model):
    """One visit to a QR landing URL. Form views and submissions are tracked on the same record."""

    mapping = models.ForeignKey(QRCodeMapping, on_delete=models.PROTECT, related_name="scans")
    station = models.ForeignKey(ChargingStation, on_delete=models.PROTECT, related_name="scans")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="scans")
    token = models.CharField(max_length=64)
    scanned_at = models.DateTimeField(default=timezone.now, db_index=True)
    session_key = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    device_type = models.CharField(max_length=20, blank=True)
    browser = models.CharField(max_length=60, blank=True)
    os = models.CharField(max_length=60, blank=True)
    referer = models.CharField(max_length=500, blank=True)
    utm_source = models.CharField(max_length=150, blank=True)
    utm_medium = models.CharField(max_length=150, blank=True)
    utm_campaign = models.CharField(max_length=150, blank=True)
    utm_term = models.CharField(max_length=150, blank=True)
    utm_content = models.CharField(max_length=150, blank=True)
    is_bot = models.BooleanField(default=False, db_index=True)
    is_repeat = models.BooleanField(
        default=False, help_text="Same browser session re-opened the QR within 30 minutes."
    )
    # Funnel: scan -> form visit (page rendered in a real browser) -> submission
    form_viewed = models.BooleanField(default=False, db_index=True)
    form_viewed_at = models.DateTimeField(null=True, blank=True)
    submitted = models.BooleanField(default=False, db_index=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    station_accepting = models.BooleanField(default=True)

    class Meta:
        ordering = ["-scanned_at"]
        indexes = [
            models.Index(fields=["station", "scanned_at"]),
            models.Index(fields=["location", "scanned_at"]),
            models.Index(fields=["is_bot", "scanned_at"]),
        ]

    def __str__(self):
        return f"Scan {self.pk} – {self.station_id} @ {self.scanned_at:%Y-%m-%d %H:%M}"
