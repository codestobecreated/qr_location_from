from django.contrib import admin

from .models import Lead, LeadAssignment, LeadNote, LeadStatusHistory


class HistoryInline(admin.TabularInline):
    model = LeadStatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "note", "changed_at")
    can_delete = False


class NoteInline(admin.TabularInline):
    model = LeadNote
    extra = 0
    readonly_fields = ("author", "created_at")


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("lead_id", "full_name", "mobile", "category", "station_name", "location_name", "status", "submitted_at", "is_duplicate")
    list_filter = ("status", "category", "is_duplicate", "source_state")
    search_fields = ("lead_id", "full_name", "mobile", "email", "station_code", "qr_token")
    date_hierarchy = "submitted_at"
    inlines = [HistoryInline, NoteInline]
    readonly_fields = [f.name for f in Lead._meta.fields if f.name not in ("status", "assigned_to")]

    def has_add_permission(self, request):
        return False  # leads are created only through the QR enquiry form


admin.site.register(LeadAssignment)
