from django.contrib import admin

from .models import ChargingStation


@admin.register(ChargingStation)
class ChargingStationAdmin(admin.ModelAdmin):
    list_display = ("station_id", "name", "location", "city", "state", "charger_type", "status")
    list_filter = ("status", "charger_type", "state")
    search_fields = ("station_id", "name", "location__name", "location__location_id")
    readonly_fields = ("station_id", "created_at", "updated_at")
    autocomplete_fields = ("location",)

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("location",) if obj else ())

    def has_delete_permission(self, request, obj=None):
        return False
