from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Status(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


DEFAULT_PRIVACY_POLICY = """RELUX ELECTRIC collects the details you submit through this enquiry form (name, mobile number, email address, enquiry category and message) together with the charging station from which the enquiry was made.

We use this information only to respond to your enquiry, to contact you about RELUX ELECTRIC products and services you asked about, and to improve our service. We do not sell your personal information.

Basic technical information such as device type, browser and the time of your visit is recorded to protect the service from abuse and to measure how our QR codes are used.

You may ask us to update or delete your information at any time by contacting us using the details on this page."""


class SystemSetting(models.Model):
    """Singleton holding business settings editable from the Settings page."""

    company_name = models.CharField(max_length=120, default="RELUX ELECTRIC")
    support_email = models.EmailField(blank=True, default="")
    support_phone = models.CharField(max_length=30, blank=True, default="")
    website_url = models.URLField(blank=True, default="https://reluxelectric.com")
    enquiry_heading = models.CharField(
        max_length=150, default="Interested in EV charging? Talk to RELUX ELECTRIC."
    )
    enquiry_intro = models.TextField(
        blank=True,
        default="Share your details and our team will get in touch with you shortly.",
    )
    thank_you_message = models.TextField(
        default="Thank you! Your enquiry has been received. Our team will contact you shortly."
    )
    privacy_policy = models.TextField(default=DEFAULT_PRIVACY_POLICY)
    duplicate_window_minutes = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(1440)],
        help_text="Repeat enquiries from the same mobile number at the same station within this window are flagged as duplicates.",
    )
    max_submissions_per_hour = models.PositiveIntegerField(
        default=20,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        help_text="Maximum enquiries accepted per hour from one IP address.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    CACHE_KEY = "system-settings"

    class Meta:
        verbose_name = "System setting"
        verbose_name_plural = "System settings"

    def __str__(self):
        return "System settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    def delete(self, *args, **kwargs):  # pragma: no cover - singleton is never deleted
        pass

    @classmethod
    def load(cls):
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, obj, 300)
        return obj
