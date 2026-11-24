from django.db import models, transaction
from django.urls import reverse

from apps.core.models import TimeStampedModel
from apps.locations.models import Location, generate_code


class ChargingStation(TimeStampedModel):
    class ChargerType(models.TextChoices):
        AC_TYPE2 = "ac_type2", "AC – Type 2"
        AC_BHARAT = "ac_bharat_001", "AC – Bharat AC-001"
        DC_CCS2 = "dc_ccs2", "DC – CCS2"
        DC_CHADEMO = "dc_chademo", "DC – CHAdeMO"
        DC_BHARAT = "dc_bharat_001", "DC – Bharat DC-001"
        DC_GBT = "dc_gbt", "DC – GB/T"
        LEV = "lev", "LEV (2W/3W) Charger"
        MIXED = "mixed", "Multi-standard (AC + DC)"
        OTHER = "other", "Other"

    class StationStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        MAINTENANCE = "maintenance", "Under maintenance"

    station_id = models.CharField(
        "Station ID", max_length=30, unique=True, null=True, blank=True, editable=False
    )
    # PROTECT: a location that still owns stations can never be deleted by accident.
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="stations")
    name = models.CharField("Station name", max_length=200, db_index=True)
    address = models.TextField("Station address")
    city = models.CharField(max_length=100, db_index=True)
    state = models.CharField(max_length=100, db_index=True)
    charger_type = models.CharField(max_length=20, choices=ChargerType.choices, default=ChargerType.DC_CCS2)
    charger_capacity_kw = models.DecimalField(
        "Charger capacity (kW)", max_digits=7, decimal_places=2, null=True, blank=True
    )
    status = models.CharField(
        max_length=12, choices=StationStatus.choices, default=StationStatus.ACTIVE, db_index=True
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["location", "status"]),
            models.Index(fields=["state", "city"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.station_id})" if self.station_id else self.name

    def get_absolute_url(self):
        return reverse("stations:detail", args=[self.pk])

    @property
    def is_active(self):
        return self.status == self.StationStatus.ACTIVE

    @property
    def accepts_enquiries(self):
        """A QR form is open only when station, its location and its QR mapping are all active."""
        mapping = getattr(self, "qr_mapping", None)
        return self.is_active and self.location.is_active and bool(mapping and mapping.is_active)

    @property
    def capacity_display(self):
        if self.charger_capacity_kw is None:
            return "—"
        value = self.charger_capacity_kw.normalize()
        return f"{value:f} kW"

    def save(self, *args, **kwargs):
        # Default city/state from the parent location when left blank.
        if self.location_id and (not self.city or not self.state):
            self.city = self.city or self.location.city
            self.state = self.state or self.location.state
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.station_id:
                self.station_id = generate_code(ChargingStation, "station_id", "STN", self.pk)
                ChargingStation.objects.filter(pk=self.pk).update(station_id=self.station_id)
