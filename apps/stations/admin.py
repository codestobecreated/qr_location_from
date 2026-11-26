from django.contrib import admin

from .models import ChargingStation


@admin.register(ChargingStation)
class QRNameAdmin(admin.ModelAdmin):
    list_display = ("station_id", "name", "created_at")
    search_fields = ("station_id", "name")
    readonly_fields = ("station_id", "created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False  # a QR code is permanent – deactivate it instead
