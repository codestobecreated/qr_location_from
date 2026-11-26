"""Admin pages for THE single RELUX QR code (served to customers at <site>/qr)."""
import io
import tempfile

from django.contrib import messages
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.audit import log_action
from apps.accounts.models import AuditLog
from apps.accounts.permissions import MANAGER, role_required

from .models import QRCodeMapping, QRScanEvent, get_main_qr
from .services import png_bytes, png_download_name, qr_matrix_image, safe_filename, write_qr_pdf


@role_required(MANAGER)
def qr_list(request):
    """There is exactly one RELUX QR code. This page shows it (creating it on the very first visit)."""
    return _qr_page(request, get_main_qr())


@role_required(MANAGER)
def qr_detail(request, pk):
    """Older QR codes (if any) can still be viewed; the main one lives at /qr-codes/."""
    mapping = get_object_or_404(QRCodeMapping.objects.select_related("station"), pk=pk)
    if mapping.is_main:
        return redirect("qrcodes:list")
    return _qr_page(request, mapping)


def _qr_page(request, mapping):
    scans = QRScanEvent.objects.filter(mapping=mapping)
    genuine = scans.filter(is_bot=False, is_repeat=False)
    leads = mapping.leads.all()
    return render(request, "qrcodes/detail.html", {
        "mapping": mapping,
        "qr": mapping.station,
        "stats": {
            "scans": genuine.count(),
            "form_views": genuine.filter(form_viewed=True).count(),
            "leads": leads.filter(is_duplicate=False).count(),
            "converted": leads.filter(is_duplicate=False, status="converted").count(),
        },
        "recent_scans": scans.order_by("-scanned_at")[:15],
        "recent_leads": leads.order_by("-submitted_at")[:10],
    })


@role_required(MANAGER)
def qr_png(request, pk):
    mapping = get_object_or_404(QRCodeMapping.objects.select_related("station"), pk=pk)
    response = HttpResponse(png_bytes(mapping), content_type="image/png")
    if request.GET.get("inline"):
        response["Cache-Control"] = "private, max-age=300"
    else:
        response["Content-Disposition"] = f'attachment; filename="{png_download_name(mapping)}"'
    return response


@role_required(MANAGER)
def qr_thumb(request, pk):
    """Small plain QR image."""
    mapping = get_object_or_404(QRCodeMapping, pk=pk)
    buf = io.BytesIO()
    qr_matrix_image(mapping.qr_url, box_size=3, border=2).save(buf, format="PNG", optimize=True)
    response = HttpResponse(buf.getvalue(), content_type="image/png")
    response["Cache-Control"] = "private, max-age=3600"
    return response


@role_required(MANAGER)
def qr_pdf(request, pk):
    mapping = get_object_or_404(QRCodeMapping.objects.select_related("station"), pk=pk)
    try:
        per_page = int(request.GET.get("per_page", 1))
    except ValueError:
        per_page = 1
    tmp = tempfile.TemporaryFile()
    write_qr_pdf([mapping] * max(1, min(per_page, 6)), tmp, per_page=per_page)
    tmp.seek(0)
    return FileResponse(tmp, as_attachment=True, filename=f"RELUX_{safe_filename(mapping.station.station_id)}.pdf",
                        content_type="application/pdf")


@role_required()
@require_POST
def qr_toggle(request, pk):
    mapping = get_object_or_404(QRCodeMapping.objects.select_related("station"), pk=pk)
    QRCodeMapping.objects.filter(pk=mapping.pk).update(is_active=not mapping.is_active)
    mapping.is_active = not mapping.is_active
    log_action(request, AuditLog.Action.QR_TOGGLE, mapping.station,
               f"QR {'switched on' if mapping.is_active else 'paused'} ({mapping.qr_url})", object_type="QR Code")
    messages.success(
        request,
        "QR code switched on – scanning opens the form." if mapping.is_active
        else "QR code paused – scanning now shows a 'not accepting enquiries' page. The QR and URL stay the same.",
    )
    return redirect(mapping.get_absolute_url())
