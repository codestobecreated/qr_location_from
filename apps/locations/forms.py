from django import forms

from apps.accounts.forms import StyledFormMixin

from .models import Location


class LocationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "address", "city", "district", "state", "pincode", "latitude", "longitude",
                  "contact_person", "contact_number", "status"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["latitude"].widget.attrs.update({"step": "0.000001", "placeholder": "e.g. 12.924500"})
        self.fields["longitude"].widget.attrs.update({"step": "0.000001", "placeholder": "e.g. 80.127800"})
        self.fields["pincode"].widget.attrs.update({"inputmode": "numeric", "maxlength": "6", "pattern": r"\d{6}"})
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        for f in ("name", "city", "district", "state", "contact_person"):
            if cleaned.get(f):
                cleaned[f] = " ".join(cleaned[f].split())
        lat, lng = cleaned.get("latitude"), cleaned.get("longitude")
        if (lat is None) != (lng is None):
            raise forms.ValidationError("Enter both latitude and longitude, or leave both empty.")
        name, pincode = cleaned.get("name"), cleaned.get("pincode")
        if name and pincode:
            dup = Location.objects.filter(name__iexact=name, pincode=pincode).exclude(pk=self.instance.pk)
            if dup.exists():
                raise forms.ValidationError(
                    f"A location named “{name}” with PIN {pincode} already exists ({dup.first().location_id})."
                )
        return cleaned


class ImportForm(StyledFormMixin, forms.Form):
    file = forms.FileField(help_text="Excel (.xlsx) or CSV file, max 10 MB.")
    update_existing = forms.BooleanField(
        required=False, initial=True,
        label="Update existing records when the ID (or name + PIN code) already exists",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].widget.attrs["accept"] = ".xlsx,.csv"
        self.apply_styles()

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith((".xlsx", ".csv")):
            raise forms.ValidationError("Upload an .xlsx or .csv file.")
        if f.size > 10 * 1024 * 1024:
            raise forms.ValidationError("File is larger than 10 MB.")
        return f
