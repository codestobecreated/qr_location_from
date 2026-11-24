from django.contrib import admin

from .models import QRCodeMapping, QRScanEvent, QRTokenHistory


@admin.register(QRCodeMapping)
class QRCodeMappingAdmin(admin.ModelAdmin):
    list_display = ("station", "token", "is_active", "created_at", "regeneration_count")
    list_filter = ("is_active",)
    search_fields = ("token", "station__name", "station__station_id")
    readonly_fields = ("station", "token", "encoded_url", "image", "created_at", "created_by", "regenerated_at", "regeneration_count")

    def has_add_permission(self, request):
        return False  # created automatically with each station

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(QRTokenHistory)
class QRTokenHistoryAdmin(admin.ModelAdmin):
    list_display = ("token", "station", "issued_at", "retired_at", "retired_by")
    search_fields = ("token", "station__name")
    readonly_fields = [f.name for f in QRTokenHistory._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(QRScanEvent)
class QRScanEventAdmin(admin.ModelAdmin):
    list_display = ("scanned_at", "station", "device_type", "browser", "is_bot", "is_repeat", "form_viewed", "submitted")
    list_filter = ("is_bot", "is_repeat", "form_viewed", "submitted", "device_type")
    search_fields = ("token", "station__name", "station__station_id")
    readonly_fields = [f.name for f in QRScanEvent._meta.fields]
    date_hierarchy = "scanned_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
