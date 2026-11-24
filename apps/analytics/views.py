from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from apps.accounts.permissions import MANAGER, role_required, scope_leads, scope_locations, scope_scans, scope_stations
from apps.core.pagination import paginate
from apps.leads.models import Lead
from apps.locations.models import Location
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
        scope_locations(Location.objects.all(), user),
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
    leads, scans, stations, locations = _scoped(request)
    period = request.GET.get("period", "daily")
    if period not in svc.TRUNC:
        period = "daily"
    series = svc.time_series(leads, scans, period, dr)
    top, bottom = svc.top_and_bottom_stations(stations, dr)

    tab = request.GET.get("tab", "locations")
    loc_sort = request.GET.get("lsort", "-leads")
    st_sort = request.GET.get("ssort", "-leads")
    location_rows = svc.sort_metrics(svc.location_metrics(locations, dr), loc_sort)
    station_rows = svc.sort_metrics(svc.station_metrics(stations, dr), st_sort)
    q = request.GET.get("q", "").strip()
    if q:
        location_rows = location_rows.filter(Q(name__icontains=q) | Q(city__icontains=q) | Q(location_id__icontains=q))
        station_rows = station_rows.filter(Q(name__icontains=q) | Q(city__icontains=q) | Q(station_id__icontains=q))

    categories = svc.category_distribution(leads, dr)
    return render(request, "analytics/overview.html", {
        "dr": dr, "presets": svc.RANGE_PRESETS, "metric_cols": METRIC_COLS, "period": period, "tab": tab, "q": q,
        "totals": svc.funnel_totals(leads, scans, dr),
        "chart": _chart(series),
        "series": series,
        "categories": categories,
        "category_chart": {"labels": [c["label"] for c in categories], "values": [c["total"] for c in categories]},
        "states": svc.leads_by(leads, "source_state", dr),
        "cities": svc.leads_by(leads, "source_city", dr, limit=25),
        "top": top, "bottom": bottom,
        "location_page": paginate(request, location_rows, default=25) if tab == "locations" else None,
        "station_page": paginate(request, station_rows, default=25) if tab == "stations" else None,
        "devices": svc.device_breakdown(scans, dr),
    })


@role_required(MANAGER)
def location_analytics(request, pk):
    dr = svc.date_range_from_request(request)
    leads, scans, stations, locations = _scoped(request)
    location = get_object_or_404(locations, pk=pk)
    loc_leads = leads.filter(location=location)
    loc_scans = scans.filter(location=location)
    station_rows = svc.sort_metrics(svc.station_metrics(stations.filter(location=location), dr), request.GET.get("ssort", "-leads"))
    series = svc.time_series(loc_leads, loc_scans, "daily", dr)
    categories = svc.category_distribution(loc_leads, dr)
    recent = loc_leads.filter(dr.lead_q()).order_by("-submitted_at")[:25]
    return render(request, "analytics/location.html", {
        "dr": dr, "presets": svc.RANGE_PRESETS, "metric_cols": METRIC_COLS, "location": location,
        "totals": svc.funnel_totals(loc_leads, loc_scans, dr),
        "stations": station_rows, "chart": _chart(series), "categories": categories,
        "category_chart": {"labels": [c["label"] for c in categories], "values": [c["total"] for c in categories]},
        "recent_leads": recent,
    })


@role_required(MANAGER)
def station_analytics(request, pk):
    dr = svc.date_range_from_request(request)
    leads, scans, stations, _ = _scoped(request)
    station = get_object_or_404(stations.select_related("location"), pk=pk)
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
