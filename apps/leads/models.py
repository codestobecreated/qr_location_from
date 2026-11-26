from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.utils import generate_code
from apps.qrcodes.models import QRCodeMapping, QRScanEvent
from apps.stations.models import ChargingStation

mobile_validator = RegexValidator(r"^[6-9]\d{9}$", "Enter a valid 10-digit Indian mobile number.")


class EnquiryCategory(models.TextChoices):
    FRANCHISE = "franchise", "EV Charging Franchise"
    CAAS = "caas", "CaaS (Charging as a Service)"
    ZERO_INVESTMENT = "zero_investment", "Zero Investment Model"
    INSTALLATION = "installation", "EV Charging Station Installation"
    PARTNERSHIP = "partnership", "Business Partnership"
    GENERAL = "general", "General Enquiry"
    OTHER = "other", "Other"


class LeadStatus(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    FOLLOW_UP = "follow_up", "Follow-up"
    INTERESTED = "interested", "Interested"
    CONVERTED = "converted", "Converted"
    NOT_INTERESTED = "not_interested", "Not Interested"
    CLOSED = "closed", "Closed"


# Fields captured from the QR token at submission time. They can never change afterwards.
IMMUTABLE_SOURCE_FIELDS = (
    "station_id", "qr_mapping_id", "qr_token", "station_code", "station_name",
    "submitted_at",
    "full_name", "mobile", "email", "category", "message",
)


class Lead(models.Model):
    lead_id = models.CharField("Lead ID", max_length=30, unique=True, null=True, blank=True, editable=False)

    # Customer-entered fields
    full_name = models.CharField(max_length=120)
    mobile = models.CharField(max_length=10, validators=[mobile_validator], db_index=True)
    email = models.EmailField(blank=True)
    category = models.CharField("Enquiry category", max_length=20, choices=EnquiryCategory.choices, db_index=True)
    message = models.TextField("Message / enquiry details", blank=True)
    consent = models.BooleanField(default=False)
    consent_at = models.DateTimeField(null=True, blank=True)

    # Source – resolved server-side from the QR token, never from user input
    station = models.ForeignKey(ChargingStation, on_delete=models.PROTECT, related_name="leads", editable=False,
                                verbose_name="QR code")
    qr_mapping = models.ForeignKey(QRCodeMapping, on_delete=models.PROTECT, related_name="leads", editable=False)
    qr_token = models.CharField(max_length=64, editable=False)
    scan_event = models.ForeignKey(
        QRScanEvent, null=True, blank=True, on_delete=models.SET_NULL, related_name="leads", editable=False
    )
    # Snapshots so the lead keeps its original context even if names are edited later
    station_code = models.CharField("QR ID", max_length=30, editable=False)
    station_name = models.CharField("QR name", max_length=200, editable=False)

    submitted_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    # Request metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True, editable=False)
    user_agent = models.CharField(max_length=500, blank=True, editable=False)
    device_type = models.CharField(max_length=20, blank=True, editable=False)
    browser = models.CharField(max_length=60, blank=True, editable=False)
    os = models.CharField(max_length=60, blank=True, editable=False)
    referer = models.CharField(max_length=500, blank=True, editable=False)
    utm_source = models.CharField(max_length=150, blank=True, editable=False)
    utm_medium = models.CharField(max_length=150, blank=True, editable=False)
    utm_campaign = models.CharField(max_length=150, blank=True, editable=False)
    utm_term = models.CharField(max_length=150, blank=True, editable=False)
    utm_content = models.CharField(max_length=150, blank=True, editable=False)

    # Duplicate handling
    submission_key = models.CharField(max_length=64, unique=True, editable=False)
    is_duplicate = models.BooleanField(default=False, db_index=True, editable=False)
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates", editable=False
    )

    # Workflow
    status = models.CharField(max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_leads"
    )
    status_changed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["station", "submitted_at"]),
            models.Index(fields=["status", "submitted_at"]),
            models.Index(fields=["mobile", "station", "submitted_at"]),
            models.Index(fields=["is_duplicate", "submitted_at"]),
        ]

    def __str__(self):
        return f"{self.lead_id} – {self.full_name}"

    def get_absolute_url(self):
        return reverse("leads:detail", args=[self.pk])

    def clean(self):
        if self.qr_mapping_id and self.station_id and self.qr_mapping.station_id != self.station_id:
            raise ValidationError("QR mapping does not belong to this station.")

    def save(self, *args, **kwargs):
        if self.pk:
            original = Lead.objects.filter(pk=self.pk).values(*IMMUTABLE_SOURCE_FIELDS).first()
            if original:
                changed = [f for f in IMMUTABLE_SOURCE_FIELDS if original[f] != getattr(self, f)]
                if changed:
                    raise ValidationError(
                        f"Original enquiry/source fields cannot be modified: {', '.join(changed)}"
                    )
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.lead_id:
                self.lead_id = generate_code(Lead, "lead_id", "LD", self.pk)
                Lead.objects.filter(pk=self.pk).update(lead_id=self.lead_id)

    @property
    def status_badge(self):
        return {
            LeadStatus.NEW: "blue",
            LeadStatus.CONTACTED: "indigo",
            LeadStatus.FOLLOW_UP: "amber",
            LeadStatus.INTERESTED: "cyan",
            LeadStatus.CONVERTED: "green",
            LeadStatus.NOT_INTERESTED: "rose",
            LeadStatus.CLOSED: "slate",
        }.get(self.status, "slate")


class LeadStatusHistory(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20, choices=LeadStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=LeadStatus.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-changed_at"]
        verbose_name_plural = "Lead status history"

    def __str__(self):
        return f"{self.lead.lead_id}: {self.from_status or '—'} → {self.to_status}"


class LeadNote(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="lead_notes"
    )
    note = models.TextField()
    follow_up_at = models.DateTimeField("Follow-up date", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Note on {self.lead.lead_id}"


class LeadAssignment(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="assignments")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="lead_assignments"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=255, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"{self.lead.lead_id} → {self.assigned_to or 'Unassigned'}"
