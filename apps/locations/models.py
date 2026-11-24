from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.urls import reverse

from apps.core.models import Status, TimeStampedModel

pincode_validator = RegexValidator(r"^\d{6}$", "Enter a valid 6-digit PIN code.")
phone_validator = RegexValidator(r"^\+?[\d\s-]{8,15}$", "Enter a valid contact number.")


def generate_code(model, field, prefix, pk):
    """Return a unique human-friendly code such as LOC-000123 for the given pk."""
    base = f"{prefix}-{pk:06d}"
    code, n = base, 1
    while model.objects.filter(**{field: code}).exclude(pk=pk).exists():
        n += 1
        code = f"{base}-{n}"
    return code


class Location(TimeStampedModel):
    location_id = models.CharField(
        "Location ID", max_length=30, unique=True, null=True, blank=True, editable=False,
        help_text="Generated automatically.",
    )
    name = models.CharField("Location name", max_length=200, db_index=True)
    address = models.TextField()
    city = models.CharField(max_length=100, db_index=True)
    district = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, db_index=True)
    pincode = models.CharField("PIN code", max_length=6, validators=[pincode_validator])
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    contact_person = models.CharField(max_length=120, blank=True)
    contact_number = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["state", "city"]),
            models.Index(fields=["status", "name"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.location_id})" if self.location_id else self.name

    def get_absolute_url(self):
        return reverse("locations:detail", args=[self.pk])

    @property
    def is_active(self):
        return self.status == Status.ACTIVE

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.location_id:
                self.location_id = generate_code(Location, "location_id", "LOC", self.pk)
                Location.objects.filter(pk=self.pk).update(location_id=self.location_id)
