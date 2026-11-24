from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from apps.accounts.audit import log_action
from apps.accounts.models import AuditLog
from apps.accounts.permissions import MANAGER, role_required, scope_locations, scope_stations
from apps.core.exports import export_response, read_tabular_upload
from apps.core.pagination import paginate
from apps.core.utils import safe_next
from apps.locations.forms import ImportForm
from apps.locations.models import Location

from .forms import StationForm
from .importers import STATION_COLUMNS, import_stations
from .models import ChargingStation

SORT_FIELDS = {
    "station_id": "station_id", "name": "name", "location": "location__name", "city": "city", "state": "state",
    "status": "status", "capacity": "charger_capacity_kw", "leads": "lead_count", "created_at": "created_at",
}


def filtered_stations(request):
    qs = scope_stations(ChargingStation.objects.select_related("location", "qr_mapping"), request.user)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(station_id__icontains=q) | Q(location__name__icontains=q)
            | Q(location__location_id__icontains=q) | Q(address__icontains=q) | Q(city__icontains=q)
        )
    location = request.GET.get("location", "")
    if location.isdigit():
        qs = qs.filter(location_id=int(location))
    for field in ("city", "state"):
        value = request.GET.get(field, "").strip()
        if value:
            qs = qs.filter(**{f"{field}__iexact": value})
    for field in ("status", "charger_type"):
        value = request.GET.get(field, "")
        if value:
            qs = qs.filter(**{field: value})
    qr = request.GET.get("qr", "")
    if qr == "active":
        qs = qs.filter(qr_mapping__is_active=True)
    elif qr == "inactive":
        qs = qs.filter(qr_mapping__is_active=False)
    return qs


@role_required(MANAGER)
def station_list(request):
    qs = filtered_stations(request).annotate(lead_count=Count("leads", filter=Q(leads__is_duplicate=False)))
    sort = request.GET.get("sort", "name")
    key = SORT_FIELDS.get(sort.lstrip("-"), "name")
    qs = qs.order_by(f"-{key}" if sort.startswith("-") else key, "pk")
    page = paginate(request, qs)
    base = scope_stations(ChargingStation.objects.all(), request.user)
    selected_location = None
    if request.GET.get("location", "").isdigit():
        selected_location = scope_locations(Location.objects.all(), request.user).filter(pk=request.GET["location"]).first()
    return render(request, "stations/list.html", {
        "page": page,
        "states": base.order_by("state").values_list("state", flat=True).distinct(),
        "cities": base.order_by("city").values_list("city", flat=True).distinct(),
        "locations": scope_locations(Location.objects.order_by("name"), request.user).only("pk", "name", "location_id"),
        "selected_location": selected_location,
        "statuses": ChargingStation.StationStatus.choices,
        "charger_types": ChargingStation.ChargerType.choices,
        "totals": base.aggregate(
            total=Count("id"), active=Count("id", filter=Q(status=ChargingStation.StationStatus.ACTIVE))
        ),
        "filters": {k: request.GET.get(k, "") for k in ("q", "city", "state", "status", "charger_type", "location", "qr")},
    })


@role_required(MANAGER)
def station_detail(request, pk):
    station = get_object_or_404(scope_stations(ChargingStation.objects.select_related("location", "qr_mapping"), request.user), pk=pk)
    from apps.qrcodes.models import QRScanEvent

    leads = station.leads.all()
    scans = QRScanEvent.objects.filter(station=station, is_bot=False, is_repeat=False)
    return render(request, "stations/detail.html", {
        "station": station,
        "mapping": station.qr_mapping,
        "stats": {
            "scans": scans.count(),
            "form_views": scans.filter(form_viewed=True).count(),
            "leads": leads.filter(is_duplicate=False).count(),
            "converted": leads.filter(is_duplicate=False, status="converted").count(),
        },
        "recent_leads": leads.order_by("-submitted_at")[:10],
    })


@role_required()
def station_create(request):
    initial = {}
    loc = request.GET.get("location", "")
    if loc.isdigit():
        location = Location.objects.filter(pk=loc).first()
        if location:
            initial = {"location": location, "address": location.address, "city": location.city, "state": location.state}
    form = StationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        station = form.save(commit=False)
        station._created_by = request.user
        station.save()
        log_action(request, AuditLog.Action.CREATE, station, f"Station created with permanent QR token {station.qr_mapping.token}")
        messages.success(request, f"Station “{station.name}” created ({station.station_id}). A permanent QR code was generated.")
        return redirect(station)
    return render(request, "stations/form.html", {"form": form, "is_create": True})


@role_required()
def station_edit(request, pk):
    station = get_object_or_404(ChargingStation, pk=pk)
    form = StationForm(request.POST or None, instance=station)
    if request.method == "POST" and form.is_valid():
        changed = ", ".join(form.changed_data) or "no fields"
        station = form.save()
        log_action(request, AuditLog.Action.UPDATE, station, f"Changed: {changed}. QR token unchanged.")
        messages.success(request, "Station updated. Its QR code URL is unchanged.")
        return redirect(station)
    return render(request, "stations/form.html", {"form": form, "is_create": False, "station": station})


@role_required()
@require_POST
def station_set_status(request, pk):
    station = get_object_or_404(ChargingStation, pk=pk)
    status = request.POST.get("status")
    if status not in ChargingStation.StationStatus.values:
        messages.error(request, "Invalid status.")
        return redirect(station)
    ChargingStation.objects.filter(pk=station.pk).update(status=status, updated_at=timezone.now())
    station.status = status
    log_action(request, AuditLog.Action.STATUS, station, f"Station set to {station.get_status_display()}")
    msg = f"{station.name} is now {station.get_status_display().lower()}."
    if status != ChargingStation.StationStatus.ACTIVE:
        msg += " Its QR code now shows a 'not accepting enquiries' page – it is never redirected to another station."
    messages.success(request, msg)
    return redirect(safe_next(request, station.get_absolute_url()))


@role_required()
@require_POST
def station_bulk_status(request):
    ids = request.POST.getlist("ids")
    status = request.POST.get("status")
    if status not in ChargingStation.StationStatus.values or not ids:
        messages.error(request, "Select at least one station and a valid status.")
        return redirect("stations:list")
    count = ChargingStation.objects.filter(pk__in=ids).update(status=status, updated_at=timezone.now())
    log_action(request, AuditLog.Action.STATUS, None, f"Bulk set {count} stations to {status}", object_type="Charging Station")
    messages.success(request, f"{count} station(s) updated.")
    return redirect(safe_next(request, "stations:list"))


@role_required()
def station_import(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == "POST" and form.is_valid():
        try:
            _, rows = read_tabular_upload(form.cleaned_data["file"])
        except Exception as exc:
            form.add_error("file", f"Could not read file: {exc}")
        else:
            if len(rows) > 20000:
                form.add_error("file", "Maximum 20,000 rows per import.")
            else:
                result = import_stations(rows, update_existing=form.cleaned_data["update_existing"], user=request.user)
                log_action(
                    request, AuditLog.Action.IMPORT, None,
                    f"Stations import: {result['created']} created, {result['updated']} updated, "
                    f"{result['skipped']} skipped, {len(result['errors'])} errors",
                    object_type="Charging Station",
                )
                if result["created"] or result["updated"]:
                    messages.success(
                        request,
                        f"Import complete: {result['created']} created (each with a new permanent QR), {result['updated']} updated.",
                    )
    return render(request, "stations/import.html", {"form": form, "result": result, "columns": STATION_COLUMNS})


@role_required()
def station_import_template(request):
    wb = Workbook()
    ws = wb.active
    ws.title = "Stations"
    ws.append([label for _, label in STATION_COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1B8042")
    sample_loc = Location.objects.order_by("pk").values_list("location_id", flat=True).first() or "LOC-000001"
    ws.append(["", sample_loc, "RELUX Tambaram Station", "12 GST Road, Tambaram", "Chennai", "Tamil Nadu",
               "DC – CCS2", 60, "Active"])
    types = wb.create_sheet("Charger types")
    types.append(["Accepted charger type values"])
    for value, label in ChargingStation.ChargerType.choices:
        types.append([label])
    for col in "ABCDEFGHI":
        ws.column_dimensions[col].width = 26
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="relux_station_import_template.xlsx"'
    wb.save(response)
    return response


@role_required(MANAGER)
def station_export(request):
    fmt = request.GET.get("format", "xlsx")
    qs = filtered_stations(request).annotate(lead_count=Count("leads", filter=Q(leads__is_duplicate=False))).order_by("location__name", "name")
    headers = ["Station ID", "Station Name", "Location ID", "Location Name", "Station Address", "City", "State",
               "Charger Type", "Capacity (kW)", "Status", "QR Status", "QR URL", "Leads", "Created", "Updated"]
    rows = (
        [s.station_id, s.name, s.location.location_id, s.location.name, s.address, s.city, s.state,
         s.get_charger_type_display(), s.charger_capacity_kw, s.get_status_display(),
         "Active" if s.qr_mapping.is_active else "Inactive", s.qr_mapping.public_url, s.lead_count,
         s.created_at, s.updated_at]
        for s in qs.iterator(chunk_size=500)
    )
    log_action(request, AuditLog.Action.EXPORT, None, f"Stations exported ({fmt})", object_type="Charging Station")
    return export_response(fmt, "relux_stations", headers, rows, "Stations")
