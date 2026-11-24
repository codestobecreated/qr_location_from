from django.contrib import admin

from .models import Location


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("location_id", "name", "city", "state", "pincode", "status", "created_at")
    list_filter = ("status", "state")
    search_fields = ("location_id", "name", "city", "pincode")
    readonly_fields = ("location_id", "created_at", "updated_at")
