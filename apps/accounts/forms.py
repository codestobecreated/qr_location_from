from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password

from apps.core.models import SystemSetting

from .models import User


class StyledFormMixin:
    """Applies the shared Tailwind input classes to every widget."""

    def apply_styles(self):
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault("class", "h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500")
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                continue
            else:
                widget.attrs["class"] = "input"
                if isinstance(widget, forms.Textarea):
                    widget.attrs.setdefault("rows", 4)


class LoginForm(StyledFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"placeholder": "Username", "autofocus": True})
        self.fields["password"].widget.attrs.update({"placeholder": "Password"})
        self.apply_styles()


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class AdminSetPasswordForm(StyledFormMixin, SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class UserForm(StyledFormMixin, forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, required=False)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput, required=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone", "designation", "role",
                  "is_active"]

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop("request_user", None)
        super().__init__(*args, **kwargs)
        self.creating = self.instance.pk is None
        if self.creating:
            self.fields["password1"].required = True
            self.fields["password2"].required = True
        else:
            self.fields["password1"].help_text = "Leave blank to keep the current password."
        self.fields["email"].required = True
        self.fields["first_name"].required = True
        self.apply_styles()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another user already uses this email address.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "Passwords do not match.")
            else:
                try:
                    validate_password(p1, self.instance)
                except forms.ValidationError as exc:
                    self.add_error("password1", exc)
        if self.request_user and self.instance.pk == self.request_user.pk:
            if cleaned.get("role") != User.Role.SUPER_ADMIN and self.instance.is_super_admin:
                self.add_error("role", "You cannot remove your own Super Admin role.")
            if not cleaned.get("is_active"):
                self.add_error("is_active", "You cannot deactivate your own account.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "designation"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class SystemSettingForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = ["company_name", "support_email", "support_phone", "website_url", "enquiry_heading",
                  "enquiry_intro", "thank_you_message", "privacy_policy", "duplicate_window_minutes",
                  "max_submissions_per_hour"]
        widgets = {"privacy_policy": forms.Textarea(attrs={"rows": 10})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()
