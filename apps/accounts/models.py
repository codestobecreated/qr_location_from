from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user with a business role used for role-based access control."""

    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        MANAGER = "manager", "Manager"
        STAFF = "staff", "Staff"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF, db_index=True)
    phone = models.CharField(max_length=20, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    # Charging stations a Manager is responsible for. Super Admins see everything regardless.
    assigned_stations = models.ManyToManyField(
        "stations.ChargingStation", blank=True, related_name="managers"
    )

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def __str__(self):
        return self.get_full_name() or self.username

    # Role helpers -----------------------------------------------------------
    @property
    def is_super_admin(self):
        return self.is_superuser or self.role == self.Role.SUPER_ADMIN

    @property
    def is_manager(self):
        return not self.is_super_admin and self.role == self.Role.MANAGER

    @property
    def is_staff_member(self):
        return not self.is_super_admin and self.role == self.Role.STAFF

    @property
    def role_label(self):
        if self.is_superuser:
            return "Super Admin"
        return self.get_role_display()

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        name = self.display_name.split()
        return ("".join(p[0] for p in name[:2]) or self.username[:2]).upper()

    def save(self, *args, **kwargs):
        # Superusers are always Super Admins; Super Admins may enter the Django admin.
        if self.is_superuser:
            self.role = self.Role.SUPER_ADMIN
        # Only Super Admins may enter the low-level Django admin site.
        self.is_staff = self.role == self.Role.SUPER_ADMIN
        super().save(*args, **kwargs)


class AuditLog(models.Model):
    """Immutable trail of important admin actions."""

    class Action(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        STATUS = "status", "Status change"
        IMPORT = "import", "Import"
        EXPORT = "export", "Export"
        QR_REGENERATE = "qr_regenerate", "QR regenerate"
        QR_TOGGLE = "qr_toggle", "QR activate/deactivate"
        ASSIGN = "assign", "Assign"
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        LOGIN_FAILED = "login_failed", "Login failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs"
    )
    action = models.CharField(max_length=30, choices=Action.choices, db_index=True)
    object_type = models.CharField(max_length=60, blank=True, db_index=True)
    object_id = models.CharField(max_length=60, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.get_action_display()} {self.object_repr}"
