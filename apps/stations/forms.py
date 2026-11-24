from django import forms

from apps.accounts.forms import StyledFormMixin
from apps.locations.models import Location

from .models import ChargingStation


class StationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ChargingStation
        fields = ["location", "name", "address", "city", "state", "charger_type", "charger_capacity_kw", "status"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "city": "Defaults to the location's city when left blank.",
            "state": "Defaults to the location's state when left blank.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset = Location.objects.order_by("name")
        self.fields["location"].label_from_instance = lambda l: f"{l.name} – {l.city} ({l.location_id})"
        if self.instance.pk:
            # A station's location is fixed once created so lead history and analytics stay consistent.
            self.fields["location"].disabled = True
            self.fields["location"].help_text = "The location of an existing station cannot be changed."
        self.fields["city"].required = False
        self.fields["state"].required = False
        self.fields["charger_capacity_kw"].widget.attrs.update({"step": "0.01", "min": "0", "placeholder": "e.g. 60"})
        self.apply_styles()

    def clean_charger_capacity_kw(self):
        value = self.cleaned_data.get("charger_capacity_kw")
        if value is not None and (value <= 0 or value > 5000):
            raise forms.ValidationError("Enter a capacity between 0 and 5000 kW.")
        return value

    def clean(self):
        cleaned = super().clean()
        location = cleaned.get("location")
        name = " ".join((cleaned.get("name") or "").split())
        cleaned["name"] = name
        if location:
            cleaned["city"] = cleaned.get("city") or location.city
            cleaned["state"] = cleaned.get("state") or location.state
            if name and ChargingStation.objects.filter(location=location, name__iexact=name).exclude(pk=self.instance.pk).exists():
                self.add_error("name", "A station with this name already exists at this location.")
        return cleaned
