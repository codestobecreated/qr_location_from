import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.stations.models import ChargingStation

TOKEN_BYTES = 16  # 128 bits of entropy -> 22 URL-safe characters
QR_PATH = "/q/{token}/"  # NEVER change: older QR codes point to this path
MAIN_QR_PATH = "/qr"      # NEVER change: THE printed RELUX QR code points to <QR_BASE_URL>/qr
MAIN_QR_NAME = "RELUX Enquiry QR"


def token_in_use(token):
    return (
        QRCodeMapping.objects.filter(token=token).exists()
        or QRTokenHistory.objects.filter(token=token).exists()
    )


def new_unique_token():
    """Cryptographically secure token that has never been used by any station."""
    for _ in range(20):
        token = secrets.token_urlsafe(TOKEN_BYTES)
        if not token_in_use(token):
            return token
    raise RuntimeError("Could not generate a unique QR token.")  # pragma: no cover


def build_permanent_url(token):
    return f"{settings.QR_BASE_URL}{QR_PATH.format(token=token)}"


def get_main_qr():
    """The one RELUX QR code (URL <QR_BASE_URL>/qr). Created once, then never changed."""
    mapping = QRCodeMapping.objects.select_related("station").filter(is_main=True).first()
    if mapping is None:
        from apps.stations.models import ChargingStation

        try:
            with transaction.atomic():
                station = ChargingStation(name=MAIN_QR_NAME)
                station._skip_qr_image = True
                station._main_qr = True  # the signal must not create a /q/<token>/ mapping for it
                station.save()
                mapping = QRCodeMapping.objects.create(
                    station=station, token=new_unique_token(), qr_url=f"{settings.QR_BASE_URL}{MAIN_QR_PATH}",
                    is_main=True,
                )
        except IntegrityError:  # created at the same moment by another request
            mapping = QRCodeMapping.objects.select_related("station").get(is_main=True)
    return mapping


# Fields that are written once, when the QR is created, and can never change afterwards.
PERMANENT_FIELDS = ("token", "qr_url", "station_id", "is_main")


class QRCodeMapping(models.Model):
    """
    The single, permanent link between a QR code and one charging station.

    The token AND the full URL printed in the QR code are stored at creation and never change:
    not when the station is edited, not when the code is updated/deployed, not when settings change.
    There is no "regenerate" – a station keeps the same QR code for its whole life.
    """

    station = models.OneToOneField(ChargingStation, on_delete=models.PROTECT, related_name="qr_mapping")
    token = models.CharField(max_length=64, unique=True, editable=False)
    qr_url = models.URLField(
        "Permanent QR URL", max_length=300, unique=True, editable=False,
        help_text="The exact URL encoded in the printed QR code. Fixed forever at creation.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_main = models.BooleanField(default=False, editable=False,
                                  help_text="The single RELUX QR code served at /qr.")
    image = models.ImageField(upload_to="qrcodes/", blank=True)
    encoded_url = models.URLField(max_length=300, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "QR code mapping"
        ordering = ["station__name"]
        constraints = [
            models.UniqueConstraint(fields=["is_main"], condition=models.Q(is_main=True), name="only_one_main_qr"),
        ]

    def __str__(self):
        return f"{self.station} → {self.qr_url}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("qrcodes:list") if self.is_main else reverse("qrcodes:detail", args=[self.pk])

    # -- Integrity guards ----------------------------------------------------
    def save(self, *args, **kwargs):
        if not self.token:
            raise ValidationError("A QR mapping needs a token.")
        if not self.qr_url:
            self.qr_url = build_permanent_url(self.token)
        if self.pk:
            original = QRCodeMapping.objects.filter(pk=self.pk).values(*PERMANENT_FIELDS).first()
            if original:
                changed = [f for f in PERMANENT_FIELDS if original[f] != getattr(self, f)]
                if changed:
                    raise ValidationError(
                        f"QR codes are permanent – {', '.join(changed)} can never be changed."
                    )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("QR mappings are permanent and cannot be deleted. Deactivate instead.")

    # -- Business helpers -----------------------------------------------------
    @property
    def public_url(self):
        """The permanent URL stored at creation (never recalculated from settings)."""
        return self.qr_url

    @property
    def effective_status(self):
        return "active" if self.is_active else "inactive"

    @property
    def image_is_stale(self):
        return not self.image or self.encoded_url != self.qr_url

    @classmethod
    def create_for_station(cls, station, user=None, build_image=True):
        for _ in range(5):
            try:
                with transaction.atomic():
                    token = new_unique_token()
                    mapping = cls.objects.create(
                        station=station, token=token, qr_url=build_permanent_url(token), created_by=user
                    )
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
            models.Index(fields=["is_bot", "scanned_at"]),
        ]

    def __str__(self):
        return f"Scan {self.pk} – {self.station_id} @ {self.scanned_at:%Y-%m-%d %H:%M}"
