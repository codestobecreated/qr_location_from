import re

from django import forms

from apps.accounts.forms import StyledFormMixin

from .models import EnquiryCategory, LeadNote, LeadStatus


class EnquiryForm(StyledFormMixin, forms.Form):
    """Public enquiry form. Contains ONLY customer fields – the station comes from the QR token."""

    full_name = forms.CharField(label="Full name", max_length=120, min_length=2)
    mobile = forms.CharField(label="Mobile number", max_length=16)
    email = forms.EmailField(label="Email address", required=False)
    category = forms.ChoiceField(label="Enquiry category", choices=[("", "Select a category")] + list(EnquiryCategory.choices))
    message = forms.CharField(label="Message / enquiry details", required=False, max_length=2000,
                              widget=forms.Textarea(attrs={"rows": 4}))
    consent = forms.BooleanField(label="I agree to the Privacy Policy and consent to RELUX ELECTRIC contacting me about my enquiry.")
    submission_key = forms.CharField(widget=forms.HiddenInput, max_length=64, required=False)
    # Honeypot: real users never see or fill this field.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()
        self.fields["full_name"].widget.attrs.update({"autocomplete": "name", "placeholder": "Your full name"})
        self.fields["mobile"].widget.attrs.update({
            "autocomplete": "tel-national", "inputmode": "numeric", "placeholder": "10-digit mobile number",
            "pattern": r"[0-9+\s\-]{10,16}",
        })
        self.fields["email"].widget.attrs.update({"autocomplete": "email", "placeholder": "you@example.com (optional)"})
        self.fields["message"].widget.attrs.update({"placeholder": "Tell us about your requirement (optional)"})
        self.fields["consent"].widget.attrs["class"] = "mt-0.5 h-5 w-5 shrink-0 rounded border-slate-300 text-brand-600 focus:ring-brand-500"

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if not re.match(r"^[A-Za-zऀ-෿][A-Za-zऀ-෿ .'\-]{1,119}$", name):
            raise forms.ValidationError("Please enter a valid name (letters only).")
        return name

    def clean_mobile(self):
        digits = re.sub(r"\D", "", self.cleaned_data["mobile"])
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if not re.fullmatch(r"[6-9]\d{9}", digits):
            raise forms.ValidationError("Enter a valid 10-digit Indian mobile number.")
        if len(set(digits)) == 1:
            raise forms.ValidationError("Enter a valid mobile number.")
        return digits

    def clean_email(self):
        return self.cleaned_data.get("email", "").strip().lower()

    def clean_message(self):
        return self.cleaned_data.get("message", "").strip()


class LeadStatusForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(choices=LeadStatus.choices)
    note = forms.CharField(required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 2}),
                           label="Comment (optional)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class LeadNoteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LeadNote
        fields = ["note", "follow_up_at"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 3, "placeholder": "Call summary, next steps…"}),
            "follow_up_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["follow_up_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.apply_styles()


class LeadAssignForm(StyledFormMixin, forms.Form):
    assigned_to = forms.ModelChoiceField(queryset=None, required=False, empty_label="— Unassigned —")
    note = forms.CharField(required=False, max_length=255, label="Note (optional)")

    def __init__(self, *args, users=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = users
        self.fields["assigned_to"].label_from_instance = lambda u: f"{u.display_name} ({u.role_label})"
        self.apply_styles()
