from django.contrib import messages
from django.db.models import Count, ProtectedError, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from apps.accounts.audit import log_action
from apps.accounts.models import AuditLog
from apps.accounts.permissions import MANAGER, role_required, scope_locations
from apps.core.exports import export_response, read_tabular_upload
from apps.core.models import Status
from apps.core.pagination import paginate
from apps.core.utils import safe_next

from .forms import ImportForm, LocationForm
from .importers import LOCATION_COLUMNS, import_locations
from .models import Location

SORT_FIELDS = {
    "location_id": "location_id", "name": "name", "city": "city", "state": "state", "status": "status",
    "created_at": "created_at", "stations": "station_count", "leads": "lead_count",
}


def filtered_locations(request):
    qs = scope_locations(Location.objects.all(), request.user)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(location_id__icontains=q) | Q(city__icontains=q) | Q(address__icontains=q)
            | Q(pincode__icontains=q) | Q(contact_person__icontains=q) | Q(district__icontains=q)
        )
    for field in ("city", "state", "status"):
        value = request.GET.get(field, "").strip()
        if value:
            qs = qs.filter(**{f"{field}__iexact": value})
    return qs


@role_required(MANAGER)
def location_list(request):
    qs = filtered_locations(request).annotate(
        station_count=Count("stations", distinct=True), lead_count=Count("leads", distinct=True)
    )
    sort = request.GET.get("sort", "name")
    key = SORT_FIELDS.get(sort.lstrip("-"), "name")
    qs = qs.order_by(f"-{key}" if sort.startswith("-") else key, "pk")
    page = paginate(request, qs)
    base = scope_locations(Location.objects.all(), request.user)
    return render(request, "locations/list.html", {
        "page": page,
        "states": base.order_by("state").values_list("state", flat=True).distinct(),
        "cities": base.filter(**({"state__iexact": request.GET["state"]} if request.GET.get("state") else {}))
                      .order_by("city").values_list("city", flat=True).distinct(),
        "statuses": Status.choices,
        "totals": base.aggregate(total=Count("id"), active=Count("id", filter=Q(status=Status.ACTIVE))),
        "filters": {k: request.GET.get(k, "") for k in ("q", "city", "state", "status")},
    })


@role_required(MANAGER)
def location_detail(request, pk):
    location = get_object_or_404(scope_locations(Location.objects.all(), request.user), pk=pk)
    stations = location.stations.select_related("qr_mapping").annotate(
        lead_count=Count("leads", distinct=True)
    ).order_by("name")
    return render(request, "locations/detail.html", {
        "location": location,
        "stations": stations,
        "lead_count": location.leads.filter(is_duplicate=False).count(),
        "recent_leads": location.leads.select_related("station").order_by("-submitted_at")[:10],
    })


@role_required()
def location_create(request):
    form = LocationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        location = form.save()
        log_action(request, AuditLog.Action.CREATE, location, "Location created")
        messages.success(request, f"Location “{location.name}” created with ID {location.location_id}.")
        if "add_station" in request.POST:
            return redirect(f"/stations/add/?location={location.pk}")
        return redirect(location)
    return render(request, "locations/form.html", {"form": form, "is_create": True})


@role_required()
def location_edit(request, pk):
    location = get_object_or_404(Location, pk=pk)
    form = LocationForm(request.POST or None, instance=location)
    if request.method == "POST" and form.is_valid():
        changed = ", ".join(form.changed_data) or "no fields"
        location = form.save()
        log_action(request, AuditLog.Action.UPDATE, location, f"Changed: {changed}")
        messages.success(request, "Location updated.")
        return redirect(location)
    return render(request, "locations/form.html", {"form": form, "is_create": False, "location": location})


@role_required()
def location_delete(request, pk):
    location = get_object_or_404(Location, pk=pk)
    station_count = location.stations.count()
    lead_count = location.leads.count()
    blocked = station_count > 0 or lead_count > 0
    if request.method == "POST":
        if blocked:
            messages.error(request, "This location still has stations or leads. Deactivate it instead.")
            return redirect(location)
        try:
            name = str(location)
            log_action(request, AuditLog.Action.DELETE, location, "Location deleted")
            location.delete()
        except ProtectedError:
            messages.error(request, "This location is referenced by other records and cannot be deleted. Deactivate it instead.")
            return redirect(location)
        messages.success(request, f"Location {name} deleted.")
        return redirect("locations:list")
    return render(request, "locations/delete.html", {
        "location": location, "station_count": station_count, "lead_count": lead_count, "blocked": blocked,
    })


@role_required()
@require_POST
def location_toggle(request, pk):
    location = get_object_or_404(Location, pk=pk)
    location.status = Status.INACTIVE if location.is_active else Status.ACTIVE
    location.save(update_fields=["status", "updated_at"])
    log_action(request, AuditLog.Action.STATUS, location, f"Location set to {location.get_status_display()}")
    messages.success(
        request,
        f"{location.name} is now {location.get_status_display().lower()}."
        + ("" if location.is_active else " QR codes at this location will stop accepting enquiries."),
    )
    return redirect(safe_next(request, location.get_absolute_url()))


@role_required()
@require_POST
def location_bulk_status(request):
    ids = request.POST.getlist("ids")
    status = request.POST.get("status")
    if status not in Status.values or not ids:
        messages.error(request, "Select at least one location and a valid status.")
        return redirect("locations:list")
    count = Location.objects.filter(pk__in=ids).update(status=status)
    log_action(request, AuditLog.Action.STATUS, None, f"Bulk set {count} locations to {status}", object_type="Location")
    messages.success(request, f"{count} location(s) set to {status}.")
    return redirect(safe_next(request, "locations:list"))


@role_required()
def location_import(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == "POST" and form.is_valid():
        try:
            _, rows = read_tabular_upload(form.cleaned_data["file"])
        except Exception as exc:  # malformed file
            form.add_error("file", f"Could not read file: {exc}")
        else:
            if len(rows) > 20000:
                form.add_error("file", "Maximum 20,000 rows per import.")
            else:
                result = import_locations(rows, update_existing=form.cleaned_data["update_existing"])
                log_action(
                    request, AuditLog.Action.IMPORT, None,
                    f"Locations import: {result['created']} created, {result['updated']} updated, "
                    f"{result['skipped']} skipped, {len(result['errors'])} errors",
                    object_type="Location",
                )
                if result["created"] or result["updated"]:
                    messages.success(request, f"Import complete: {result['created']} created, {result['updated']} updated.")
    return render(request, "locations/import.html", {"form": form, "result": result, "columns": LOCATION_COLUMNS})


@role_required()
def location_import_template(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "Locations"
    ws.append([label for _, label in LOCATION_COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1B8042")
    ws.append(["", "RELUX Tambaram Hub", "12 GST Road, Tambaram", "Chennai", "Chengalpattu", "Tamil Nadu",
               "600045", 12.9249, 80.1, "Ravi Kumar", "9876543210", "Active"])
    for col in "ABCDEFGHIJKL":
        ws.column_dimensions[col].width = 24
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="relux_location_import_template.xlsx"'
    wb.save(response)
    return response


@role_required(MANAGER)
def location_export(request):
    fmt = request.GET.get("format", "xlsx")
    qs = filtered_locations(request).annotate(
        station_count=Count("stations", distinct=True), lead_count=Count("leads", distinct=True)
    ).order_by("name")
    headers = ["Location ID", "Location Name", "Address", "City", "District", "State", "PIN Code", "Latitude",
               "Longitude", "Contact Person", "Contact Number", "Status", "Stations", "Leads", "Created", "Updated"]
    rows = (
        [l.location_id, l.name, l.address, l.city, l.district, l.state, l.pincode, l.latitude, l.longitude,
         l.contact_person, l.contact_number, l.get_status_display(), l.station_count, l.lead_count,
         l.created_at, l.updated_at]
        for l in qs.iterator(chunk_size=500)
    )
    log_action(request, AuditLog.Action.EXPORT, None, f"Locations exported ({fmt})", object_type="Location")
    return export_response(fmt, "relux_locations", headers, rows, "Locations")
