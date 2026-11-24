import io
import tempfile
import zipfile

from django import forms
from django.contrib import messages
from django.db.models import Count, Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.audit import log_action
from apps.accounts.forms import StyledFormMixin
from apps.accounts.models import AuditLog
from apps.accounts.permissions import MANAGER, role_required, scope_locations, scope_stations
from apps.core.pagination import paginate
from apps.core.utils import safe_next
from apps.locations.models import Location
from apps.stations.models import ChargingStation

from .models import QRCodeMapping, QRScanEvent
from .services import ensure_image, png_bytes, png_download_name, qr_matrix_image, safe_filename, write_qr_pdf

MAX_BULK = 2000


def scoped_mappings(user):
    stations = scope_stations(ChargingStation.objects.all(), user)
    return QRCodeMapping.objects.filter(station__in=stations).select_related("station", "station__location")


def filtered_mappings(request, data=None):
    data = data if data is not None else request.GET
    qs = scoped_mappings(request.user)
    q = (data.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(station__name__icontains=q) | Q(station__station_id__icontains=q) | Q(token__icontains=q)
            | Q(station__location__name__icontains=q) | Q(station__location__location_id__icontains=q)
        )
    location = data.get("location") or ""
    if str(location).isdigit():
        qs = qs.filter(station__location_id=int(location))
    for field in ("city", "state"):
        value = (data.get(field) or "").strip()
        if value:
            qs = qs.filter(**{f"station__{field}__iexact": value})
    status = data.get("qr_status") or ""
    if status == "active":
        qs = qs.filter(is_active=True, station__status="active", station__location__status="active")
    elif status == "inactive":
        qs = qs.filter(Q(is_active=False) | ~Q(station__status="active") | ~Q(station__location__status="active"))
    return qs


@role_required(MANAGER)
def qr_list(request):
    qs = filtered_mappings(request).annotate(
        scan_count=Count("scans", filter=Q(scans__is_bot=False, scans__is_repeat=False), distinct=True),
    ).order_by("station__location__name", "station__name")
    page = paginate(request, qs, default=25)
    base = scoped_mappings(request.user)
    stations = scope_stations(ChargingStation.objects.all(), request.user)
    totals = base.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True, station__status="active", station__location__status="active")),
    )
    totals["inactive"] = totals["total"] - totals["active"]
    return render(request, "qrcodes/list.html", {
        "page": page,
        "locations": scope_locations(Location.objects.order_by("name"), request.user).only("pk", "name", "location_id"),
        "states": stations.order_by("state").values_list("state", flat=True).distinct(),
        "cities": stations.order_by("city").values_list("city", flat=True).distinct(),
        "totals": totals,
        "filters": {k: request.GET.get(k, "") for k in ("q", "location", "city", "state", "qr_status")},
        "max_bulk": MAX_BULK,
    })


@role_required(MANAGER)
def qr_detail(request, pk):
    mapping = get_object_or_404(scoped_mappings(request.user), pk=pk)
    scans = QRScanEvent.objects.filter(mapping=mapping)
    genuine = scans.filter(is_bot=False, is_repeat=False)
    return render(request, "qrcodes/detail.html", {
        "mapping": mapping,
        "station": mapping.station,
        "history": mapping.history.select_related("retired_by"),
        "stats": {
            "scans": genuine.count(),
            "bot_scans": scans.filter(is_bot=True).count(),
            "form_views": genuine.filter(form_viewed=True).count(),
            "submissions": genuine.filter(submitted=True).count(),
            "leads": mapping.leads.filter(is_duplicate=False).count(),
        },
        "recent_scans": scans.order_by("-scanned_at")[:15],
    })


@role_required(MANAGER)
def qr_png(request, pk):
    mapping = get_object_or_404(scoped_mappings(request.user), pk=pk)
    data = png_bytes(mapping)
    response = HttpResponse(data, content_type="image/png")
    if request.GET.get("inline"):
        response["Cache-Control"] = "private, max-age=300"
    else:
        response["Content-Disposition"] = f'attachment; filename="{png_download_name(mapping)}"'
    return response


@role_required(MANAGER)
def qr_thumb(request, pk):
    """Small plain QR matrix used for table thumbnails."""
    mapping = get_object_or_404(scoped_mappings(request.user), pk=pk)
    img = qr_matrix_image(mapping.public_url, box_size=3, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    response = HttpResponse(buf.getvalue(), content_type="image/png")
    response["Cache-Control"] = "private, max-age=3600"
    return response


def _pdf_response(mappings, per_page, filename):
    tmp = tempfile.TemporaryFile()
    write_qr_pdf(mappings, tmp, per_page=per_page)
    tmp.seek(0)
    return FileResponse(tmp, as_attachment=True, filename=filename, content_type="application/pdf")


@role_required(MANAGER)
def qr_pdf(request, pk):
    mapping = get_object_or_404(scoped_mappings(request.user), pk=pk)
    return _pdf_response([mapping], 1, f"RELUX_QR_{safe_filename(mapping.station.station_id)}.pdf")


def _bulk_selection(request):
    """Mappings chosen via checkboxes (ids) or 'all matching current filters'."""
    if request.POST.get("scope") == "filtered":
        qs = filtered_mappings(request, data=request.POST)
    else:
        ids = [i for i in request.POST.getlist("ids") if i.isdigit()]
        qs = scoped_mappings(request.user).filter(pk__in=ids)
    return qs.order_by("station__location__name", "station__name")


@role_required(MANAGER)
@require_POST
def qr_bulk_download(request):
    qs = _bulk_selection(request)
    count = qs.count()
    if not count:
        messages.error(request, "Select at least one QR code (or choose 'all matching filters').")
        return redirect(safe_next(request, "qrcodes:list"))
    if count > MAX_BULK:
        messages.error(request, f"{count} QR codes selected. Please narrow your filters to at most {MAX_BULK} per download.")
        return redirect(safe_next(request, "qrcodes:list"))
    fmt = request.POST.get("format", "zip")
    stamp = timezone.localtime().strftime("%Y%m%d_%H%M")
    log_action(request, AuditLog.Action.EXPORT, None, f"Bulk QR download ({fmt}) of {count} codes", object_type="QR Code")
    if fmt == "pdf":
        try:
            per_page = int(request.POST.get("per_page", 4))
        except ValueError:
            per_page = 4
        return _pdf_response(qs.iterator(chunk_size=100), per_page, f"RELUX_QR_codes_{stamp}.pdf")

    tmp = tempfile.TemporaryFile()
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = ["Station ID,Station Name,Location ID,Location Name,City,State,QR Status,QR URL,File"]
        used = set()
        for mapping in qs.iterator(chunk_size=100):
            s = mapping.station
            folder = safe_filename(f"{s.location.location_id}_{s.location.name}")
            name = f"{folder}/{png_download_name(mapping)}"
            if name in used:
                name = name.replace(".png", f"_{mapping.pk}.png")
            used.add(name)
            zf.writestr(name, png_bytes(mapping))
            status = "Active" if mapping.effective_status == "active" else "Inactive"
            cells = [s.station_id, s.name, s.location.location_id, s.location.name, s.city, s.state, status,
                     mapping.public_url, name]
            manifest.append(",".join('"' + str(c).replace('"', '""') + '"' for c in cells))
        zf.writestr("manifest.csv", "﻿" + "\n".join(manifest))
    tmp.seek(0)
    return FileResponse(tmp, as_attachment=True, filename=f"RELUX_QR_codes_{stamp}.zip", content_type="application/zip")


@role_required()
@require_POST
def qr_toggle(request, pk):
    mapping = get_object_or_404(QRCodeMapping.objects.select_related("station"), pk=pk)
    QRCodeMapping.objects.filter(pk=mapping.pk).update(is_active=not mapping.is_active)
    mapping.is_active = not mapping.is_active
    log_action(request, AuditLog.Action.QR_TOGGLE, mapping.station,
               f"QR {'activated' if mapping.is_active else 'deactivated'} (token {mapping.token})", object_type="QR Code")
    messages.success(
        request,
        f"QR code for {mapping.station.name} {'activated' if mapping.is_active else 'deactivated'}."
        + ("" if mapping.is_active else " Scans will show a 'not accepting enquiries' page – no redirect to any other station."),
    )
    return redirect(safe_next(request, mapping.get_absolute_url()))


class RegenerateForm(StyledFormMixin, forms.Form):
    confirm_station_id = forms.CharField(label="Type the Station ID to confirm")
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), min_length=10,
                             help_text="Required. Recorded in the QR history and audit log.")
    acknowledge = forms.BooleanField(
        label="I understand that every printed copy of the current QR code will stop accepting enquiries immediately.",
    )

    def __init__(self, *args, station=None, **kwargs):
        self.station = station
        super().__init__(*args, **kwargs)
        self.apply_styles()

    def clean_confirm_station_id(self):
        value = self.cleaned_data["confirm_station_id"].strip()
        if value != self.station.station_id:
            raise forms.ValidationError("Station ID does not match.")
        return value


@role_required()
def qr_regenerate(request, pk):
    mapping = get_object_or_404(QRCodeMapping.objects.select_related("station", "station__location"), pk=pk)
    form = RegenerateForm(request.POST or None, station=mapping.station)
    if request.method == "POST" and form.is_valid():
        old = mapping.token
        mapping = mapping.regenerate(request.user, form.cleaned_data["reason"])
        log_action(request, AuditLog.Action.QR_REGENERATE, mapping.station,
                   f"Token {old} retired and replaced by {mapping.token}. Reason: {form.cleaned_data['reason']}",
                   object_type="QR Code")
        messages.success(request, "A new QR code was issued. The old token is kept in history and no longer accepts enquiries. Print and replace the station's QR sticker.")
        return redirect("qrcodes:detail", pk=mapping.pk)
    return render(request, "qrcodes/regenerate.html", {"form": form, "mapping": mapping})


@role_required()
@require_POST
def qr_refresh_images(request):
    """Re-render printed cards for stale images (e.g. after renaming or changing QR_BASE_URL)."""
    stale = [m for m in QRCodeMapping.objects.select_related("station", "station__location") if m.image_is_stale]
    for m in stale:
        ensure_image(m)
    messages.success(request, f"Refreshed {len(stale)} QR image(s). Tokens were not changed.")
    return redirect("qrcodes:list")
