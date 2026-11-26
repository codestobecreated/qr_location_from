from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AuditLog, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "is_active", "last_login")
    list_filter = ("role", "is_active", "is_superuser")
    filter_horizontal = ("assigned_stations", "groups", "user_permissions")
    fieldsets = BaseUserAdmin.fieldsets + (("RELUX role", {"fields": ("role", "phone", "designation", "assigned_stations")}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("RELUX role", {"fields": ("email", "role")}),)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "object_type", "object_repr", "ip_address")
    list_filter = ("action", "object_type")
    search_fields = ("object_repr", "description", "user__username")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
