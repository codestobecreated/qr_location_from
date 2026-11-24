from datetime import datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.permissions import scope_leads, scope_locations, scope_scans, scope_stations
from apps.analytics import services as svc
from apps.leads.models import Lead, LeadNote, LeadStatus
from apps.locations.models import Location
from apps.qrcodes.models import QRCodeMapping, QRScanEvent
from apps.stations.models import ChargingStation


@login_required
def home(request):
    user = request.user
    tz = timezone.get_current_timezone()
    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, time.min), tz)
    month_start = timezone.make_aware(datetime.combine(today.replace(day=1), time.min), tz)

    leads = scope_leads(Lead.objects.all(), user)
    unique = leads.filter(is_duplicate=False)
    scans = scope_scans(QRScanEvent.objects.all(), user)
    stations = scope_stations(ChargingStation.objects.all(), user)
    locations = scope_locations(Location.objects.all(), user)

    lead_stats = unique.aggregate(
        total=Count("id"),
        today=Count("id", filter=Q(submitted_at__gte=today_start)),
        month=Count("id", filter=Q(submitted_at__gte=month_start)),
        new=Count("id", filter=Q(status=LeadStatus.NEW)),
        contacted=Count("id", filter=Q(status=LeadStatus.CONTACTED)),
        follow_up=Count("id", filter=Q(status=LeadStatus.FOLLOW_UP)),
        interested=Count("id", filter=Q(status=LeadStatus.INTERESTED)),
        converted=Count("id", filter=Q(status=LeadStatus.CONVERTED)),
        unassigned=Count("id", filter=Q(assigned_to__isnull=True)),
    )
    stats = {
        **lead_stats,
        "locations": locations.count(),
        "stations": stations.count(),
        "active_qr": QRCodeMapping.objects.filter(
            station__in=stations, is_active=True, station__status="active", station__location__status="active"
        ).count(),
        "scans": scans.filter(svc.GENUINE_SCAN).count(),
        "scans_today": scans.filter(svc.GENUINE_SCAN, scanned_at__gte=today_start).count(),
        "conversion_rate": svc.pct(lead_stats["converted"], lead_stats["total"]),
    }

    dr = svc.DateRange(today - timedelta(days=13), today, "14d", "Last 14 days")
    series = svc.time_series(leads, scans, "daily", dr)
    categories = svc.category_distribution(leads, svc.DateRange(today - timedelta(days=29), today))

    top_stations = []
    if not user.is_staff_member:
        top_stations = list(
            svc.station_metrics(stations, svc.DateRange(today - timedelta(days=29), today)).order_by("-m_leads", "-m_scans")[:5]
        )

    follow_ups = (
        LeadNote.objects.filter(lead__in=leads, follow_up_at__isnull=False,
                                follow_up_at__lt=today_start + timedelta(days=8))
        .exclude(lead__status__in=[LeadStatus.CONVERTED, LeadStatus.CLOSED, LeadStatus.NOT_INTERESTED])
        .select_related("lead").order_by("follow_up_at")[:8]
    )
    return render(request, "dashboard/home.html", {
        "stats": stats,
        "chart": {
            "labels": [r["label"] for r in series], "scans": [r["scans"] for r in series],
            "leads": [r["leads"] for r in series], "converted": [r["converted"] for r in series],
        },
        "category_chart": {"labels": [c["label"] for c in categories], "values": [c["total"] for c in categories]},
        "recent_leads": leads.select_related("assigned_to").order_by("-submitted_at")[:8],
        "top_stations": top_stations,
        "follow_ups": follow_ups,
        "now": timezone.now(),
    })
