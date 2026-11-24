from datetime import datetime, time, timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.audit import log_action
from apps.accounts.models import AuditLog, User
from apps.accounts.permissions import (
    MANAGER, STAFF, assignable_users, can_assign_leads, role_required, scope_leads, scope_locations, scope_stations,
)
from apps.core.exports import export_response
from apps.core.pagination import paginate
from apps.core.utils import safe_next
from apps.locations.models import Location
from apps.stations.models import ChargingStation

from .forms import LeadAssignForm, LeadNoteForm, LeadStatusForm
from .models import EnquiryCategory, Lead, LeadAssignment, LeadStatus, LeadStatusHistory

SORT_FIELDS = {
    "lead_id": "pk", "name": "full_name", "category": "category", "location": "location_name",
    "station": "station_name", "city": "source_city", "state": "source_state", "date": "submitted_at",
    "status": "status",
}


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def filter_leads(request, qs=None, data=None):
    data = data if data is not None else request.GET
    qs = scope_leads(qs if qs is not None else Lead.objects.all(), request.user)
    q = (data.get("q") or "").strip()
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        cond = Q(full_name__icontains=q) | Q(email__icontains=q) | Q(lead_id__iexact=q) | Q(qr_token=q) | Q(station_code__iexact=q)
        if len(digits) >= 4:
            cond |= Q(mobile__contains=digits[-10:])
        qs = qs.filter(cond)
    for param, field in (("location", "location_id"), ("station", "station_id")):
        value = data.get(param) or ""
        if str(value).isdigit():
            qs = qs.filter(**{field: int(value)})
    for param, field in (("city", "source_city__iexact"), ("state", "source_state__iexact")):
        value = (data.get(param) or "").strip()
        if value:
            qs = qs.filter(**{field: value})
    category = data.get("category") or ""
    if category in EnquiryCategory.values:
        qs = qs.filter(category=category)
    status = data.get("status") or ""
    if status in LeadStatus.values:
        qs = qs.filter(status=status)
    assigned = data.get("assigned") or ""
    if assigned == "me":
        qs = qs.filter(assigned_to=request.user)
    elif assigned == "none":
        qs = qs.filter(assigned_to__isnull=True)
    elif str(assigned).isdigit():
        qs = qs.filter(assigned_to_id=int(assigned))
    tz = timezone.get_current_timezone()
    date_from, date_to = parse_date(data.get("date_from")), parse_date(data.get("date_to"))
    if date_from:
        qs = qs.filter(submitted_at__gte=timezone.make_aware(datetime.combine(date_from, time.min), tz))
    if date_to:
        qs = qs.filter(submitted_at__lt=timezone.make_aware(datetime.combine(date_to + timedelta(days=1), time.min), tz))
    duplicates = data.get("duplicates") or ""
    if duplicates == "only":
        qs = qs.filter(is_duplicate=True)
    elif duplicates != "include":
        qs = qs.filter(is_duplicate=False)
    return qs


FILTER_KEYS = ("q", "location", "station", "city", "state", "category", "status", "assigned",
               "date_from", "date_to", "duplicates")


def _filter_options(request):
    leads = scope_leads(Lead.objects.all(), request.user)
    location_id = request.GET.get("location", "")
    stations = scope_stations(ChargingStation.objects.order_by("name"), request.user)
    if location_id.isdigit():
        stations = stations.filter(location_id=int(location_id))
    return {
        "locations": scope_locations(Location.objects.order_by("name"), request.user).only("pk", "name", "location_id")
        if not request.user.is_staff_member else Location.objects.filter(pk__in=leads.values("location_id")).order_by("name"),
        "stations": stations.only("pk", "name", "station_id")
        if not request.user.is_staff_member else ChargingStation.objects.filter(pk__in=leads.values("station_id")).order_by("name"),
        "cities": leads.order_by("source_city").values_list("source_city", flat=True).distinct(),
        "states": leads.order_by("source_state").values_list("source_state", flat=True).distinct(),
        "categories": EnquiryCategory.choices,
        "statuses": LeadStatus.choices,
        "assignees": assignable_users(request.user) if can_assign_leads(request.user) else User.objects.none(),
    }


@role_required(MANAGER, STAFF)
def lead_list(request):
    qs = filter_leads(request).select_related("assigned_to")
    sort = request.GET.get("sort", "-date")
    key = SORT_FIELDS.get(sort.lstrip("-"), "submitted_at")
    qs = qs.order_by(f"-{key}" if sort.startswith("-") else key, "-pk")
    page = paginate(request, qs)
    ctx = {"page": page, "filters": {k: request.GET.get(k, "") for k in FILTER_KEYS},
           "can_assign": can_assign_leads(request.user)}
    ctx.update(_filter_options(request))
    ctx["has_filters"] = any(ctx["filters"].values())
    return render(request, "leads/list.html", ctx)


def _get_lead(request, pk):
    return get_object_or_404(
        scope_leads(Lead.objects.select_related("location", "station", "qr_mapping", "assigned_to", "scan_event"), request.user),
        pk=pk,
    )


@role_required(MANAGER, STAFF)
def lead_detail(request, pk):
    lead = _get_lead(request, pk)
    can_assign = can_assign_leads(request.user)
    return render(request, "leads/detail.html", {
        "lead": lead,
        "status_form": LeadStatusForm(initial={"status": lead.status}),
        "note_form": LeadNoteForm(),
        "assign_form": LeadAssignForm(users=assignable_users(request.user), initial={"assigned_to": lead.assigned_to}) if can_assign else None,
        "history": lead.status_history.select_related("changed_by"),
        "notes": lead.notes.select_related("author"),
        "assignments": lead.assignments.select_related("assigned_to", "assigned_by"),
        "duplicates": scope_leads(lead.duplicates.all(), request.user),
        "previous_leads": scope_leads(Lead.objects.filter(mobile=lead.mobile).exclude(pk=lead.pk), request.user)
        .order_by("-submitted_at")[:10],
    })


def change_status(lead, new_status, user, note=""):
    if new_status == lead.status:
        return False
    with transaction.atomic():
        LeadStatusHistory.objects.create(lead=lead, from_status=lead.status, to_status=new_status, changed_by=user, note=note)
        lead.status = new_status
        lead.status_changed_at = timezone.now()
        lead.save(update_fields=["status", "status_changed_at", "updated_at"])
    return True


@role_required(MANAGER, STAFF)
@require_POST
def lead_update_status(request, pk):
    lead = _get_lead(request, pk)
    form = LeadStatusForm(request.POST)
    if form.is_valid():
        old = lead.get_status_display()
        if change_status(lead, form.cleaned_data["status"], request.user, form.cleaned_data["note"]):
            log_action(request, AuditLog.Action.STATUS, lead, f"Status {old} → {lead.get_status_display()}")
            messages.success(request, f"Lead status changed to {lead.get_status_display()}.")
        else:
            messages.info(request, "Status unchanged.")
    else:
        messages.error(request, "Invalid status.")
    return redirect(safe_next(request, lead.get_absolute_url()))


@role_required(MANAGER, STAFF)
@require_POST
def lead_add_note(request, pk):
    lead = _get_lead(request, pk)
    form = LeadNoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.lead = lead
        note.author = request.user
        note.save()
        messages.success(request, "Note added.")
    else:
        messages.error(request, "Note could not be saved: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(lead.get_absolute_url() + "#notes")


def assign_lead(lead, user_to, by, note=""):
    if lead.assigned_to_id == (user_to.pk if user_to else None):
        return False
    with transaction.atomic():
        LeadAssignment.objects.create(lead=lead, assigned_to=user_to, assigned_by=by, note=note)
        lead.assigned_to = user_to
        lead.save(update_fields=["assigned_to", "updated_at"])
    return True


@role_required(MANAGER)
@require_POST
def lead_assign(request, pk):
    lead = _get_lead(request, pk)
    form = LeadAssignForm(request.POST, users=assignable_users(request.user))
    if form.is_valid():
        user_to = form.cleaned_data["assigned_to"]
        if assign_lead(lead, user_to, request.user, form.cleaned_data["note"]):
            log_action(request, AuditLog.Action.ASSIGN, lead, f"Assigned to {user_to or 'nobody'}")
            messages.success(request, f"Lead assigned to {user_to.display_name if user_to else 'nobody'}.")
        else:
            messages.info(request, "Assignment unchanged.")
    else:
        messages.error(request, "Choose a valid user.")
    return redirect(lead.get_absolute_url())


@role_required(MANAGER)
@require_POST
def lead_bulk_action(request):
    ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
    leads = list(scope_leads(Lead.objects.filter(pk__in=ids), request.user))
    action = request.POST.get("action")
    if not leads:
        messages.error(request, "Select at least one lead.")
    elif action == "status" and request.POST.get("status") in LeadStatus.values:
        new = request.POST["status"]
        changed = sum(change_status(l, new, request.user, "Bulk update") for l in leads)
        log_action(request, AuditLog.Action.STATUS, None, f"Bulk status → {new} for {changed} leads", object_type="Lead")
        messages.success(request, f"{changed} lead(s) updated.")
    elif action == "assign":
        target = request.POST.get("assigned_to", "")
        user_to = assignable_users(request.user).filter(pk=target).first() if target.isdigit() else None
        if target and target != "none" and user_to is None:
            messages.error(request, "Choose a valid user.")
        else:
            changed = sum(assign_lead(l, user_to, request.user, "Bulk assignment") for l in leads)
            log_action(request, AuditLog.Action.ASSIGN, None, f"Bulk assigned {changed} leads to {user_to or 'nobody'}", object_type="Lead")
            messages.success(request, f"{changed} lead(s) assigned.")
    else:
        messages.error(request, "Choose an action.")
    return redirect(safe_next(request, "leads:list"))


LEAD_EXPORT_HEADERS = [
    "Lead ID", "Customer Name", "Mobile", "Email", "Enquiry Category", "Message", "Location ID", "Location Name",
    "Station ID", "Station Name", "City", "State", "QR Token", "Submission Date", "Submission Time", "Status",
    "Assigned To", "Duplicate", "Device", "Browser", "OS", "UTM Source", "UTM Medium", "UTM Campaign",
]


def lead_export_rows(qs):
    for l in qs.select_related("assigned_to").iterator(chunk_size=500):
        local = timezone.localtime(l.submitted_at)
        yield [
            l.lead_id, l.full_name, l.mobile, l.email, l.get_category_display(), l.message, l.location_code,
            l.location_name, l.station_code, l.station_name, l.source_city, l.source_state, l.qr_token,
            local.strftime("%Y-%m-%d"), local.strftime("%H:%M:%S"), l.get_status_display(),
            l.assigned_to.display_name if l.assigned_to else "", "Yes" if l.is_duplicate else "No",
            l.device_type, l.browser, l.os, l.utm_source, l.utm_medium, l.utm_campaign,
        ]


@role_required(MANAGER)
def lead_export(request):
    fmt = request.GET.get("format", "xlsx")
    qs = filter_leads(request).order_by("-submitted_at")
    log_action(request, AuditLog.Action.EXPORT, None, f"Leads exported ({fmt}), filters: {request.GET.urlencode()}", object_type="Lead")
    return export_response(fmt, "relux_leads", LEAD_EXPORT_HEADERS, lead_export_rows(qs), "Leads")
