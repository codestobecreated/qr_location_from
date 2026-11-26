from django.shortcuts import get_object_or_404, render

from apps.accounts.permissions import MANAGER, role_required, scope_leads, scope_scans, scope_stations
from apps.leads.models import Lead
from apps.qrcodes.models import QRScanEvent
from apps.stations.models import ChargingStation

from . import services as svc

METRIC_COLS = [("scans", "QR scans"), ("form_views", "Form visits"), ("submissions", "Submissions"),
               ("leads", "Leads"), ("converted", "Converted"), ("rate", "Conv. %")]


def _scoped(request):
    user = request.user
    return (
        scope_leads(Lead.objects.all(), user),
        scope_scans(QRScanEvent.objects.all(), user),
        scope_stations(ChargingStation.objects.all(), user),
    )


def _chart(series):
    return {
        "labels": [r["label"] for r in series],
        "scans": [r["scans"] for r in series],
        "leads": [r["leads"] for r in series],
        "converted": [r["converted"] for r in series],
    }


@role_required(MANAGER)
def overview(request):
    dr = svc.date_range_from_request(request)
    leads, scans, stations = _scoped(request)
    period = request.GET.get("period", "daily")
    if period not in svc.TRUNC:
        period = "daily"
    series = svc.time_series(leads, scans, period, dr)

    categories = svc.category_distribution(leads, dr)
    return render(request, "analytics/overview.html", {
        "dr": dr, "presets": svc.RANGE_PRESETS, "metric_cols": METRIC_COLS, "period": period,
        "totals": svc.funnel_totals(leads, scans, dr),
        "chart": _chart(series),
        "series": series,
        "categories": categories,
        "category_chart": {"labels": [c["label"] for c in categories], "values": [c["total"] for c in categories]},
        "devices": svc.device_breakdown(scans, dr),
    })


@role_required(MANAGER)
def station_analytics(request, pk):
    dr = svc.date_range_from_request(request)
    leads, scans, stations = _scoped(request)
    station = get_object_or_404(stations, pk=pk)
    st_leads = leads.filter(station=station)
    st_scans = scans.filter(station=station)
    series = svc.time_series(st_leads, st_scans, "daily", dr)
    categories = svc.category_distribution(st_leads, dr)
    return render(request, "analytics/station.html", {
        "dr": dr, "presets": svc.RANGE_PRESETS, "metric_cols": METRIC_COLS, "station": station,
        "totals": svc.funnel_totals(st_leads, st_scans, dr),
        "chart": _chart(series), "categories": categories,
        "category_chart": {"labels": [c["label"] for c in categories], "values": [c["total"] for c in categories]},
        "devices": svc.device_breakdown(st_scans, dr),
        "recent_leads": st_leads.filter(dr.lead_q()).order_by("-submitted_at")[:25],
    })
