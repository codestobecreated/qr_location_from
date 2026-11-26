from datetime import date, datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.permissions import scope_leads, scope_scans, scope_stations
from apps.analytics import services as svc
from apps.leads.models import Lead, LeadNote, LeadStatus
from apps.qrcodes.models import QRCodeMapping, QRScanEvent
from apps.stations.models import ChargingStation


def _aware(d):
    return timezone.make_aware(datetime.combine(d, time.min), timezone.get_current_timezone())


def _chart(series):
    return {"labels": [r["label"] for r in series], "scans": [r["scans"] for r in series],
            "leads": [r["leads"] for r in series], "converted": [r["converted"] for r in series]}


@login_required
def home(request):
    user = request.user
    today = timezone.localdate()
    today_start = _aware(today)
    week_start = _aware(today - timedelta(days=today.weekday()))
    month_start = _aware(today.replace(day=1))
    year_start = _aware(date(today.year, 1, 1))

    leads = scope_leads(Lead.objects.all(), user)
    unique = leads.filter(is_duplicate=False)
    scans = scope_scans(QRScanEvent.objects.all(), user)
    qrs = scope_stations(ChargingStation.objects.all(), user)

    lead_stats = unique.aggregate(
        total=Count("id"),
        today=Count("id", filter=Q(submitted_at__gte=today_start)),
        week=Count("id", filter=Q(submitted_at__gte=week_start)),
        month=Count("id", filter=Q(submitted_at__gte=month_start)),
        year=Count("id", filter=Q(submitted_at__gte=year_start)),
        new=Count("id", filter=Q(status=LeadStatus.NEW)),
        contacted=Count("id", filter=Q(status=LeadStatus.CONTACTED)),
        converted=Count("id", filter=Q(status=LeadStatus.CONVERTED)),
    )
    stats = {
        **lead_stats,
        "qr_total": qrs.count(),
        "qr_active": QRCodeMapping.objects.filter(station__in=qrs, is_active=True).count(),
        "scans": scans.filter(svc.GENUINE_SCAN).count(),
        "scans_today": scans.filter(svc.GENUINE_SCAN, scanned_at__gte=today_start).count(),
        "conversion_rate": svc.pct(lead_stats["converted"], lead_stats["total"]),
    }

    daily = svc.time_series(leads, scans, "daily", svc.DateRange(today - timedelta(days=29), today))
    m = today.year * 12 + today.month - 1 - 11          # first day of the month, 11 months ago
    last_12_months = date(m // 12, m % 12 + 1, 1)
    monthly = svc.time_series(leads, scans, "monthly", svc.DateRange(last_12_months, today))
    yearly = svc.time_series(leads, scans, "yearly")
    categories = svc.category_distribution(leads, svc.DateRange(today - timedelta(days=29), today))

    follow_ups = (
        LeadNote.objects.filter(lead__in=leads, follow_up_at__isnull=False, follow_up_at__lt=today_start + timedelta(days=8))
        .exclude(lead__status__in=[LeadStatus.CONVERTED, LeadStatus.CLOSED, LeadStatus.NOT_INTERESTED])
        .select_related("lead").order_by("follow_up_at")[:8]
    )
    return render(request, "dashboard/home.html", {
        "stats": stats,
        "daily_chart": _chart(daily),
        "monthly_chart": _chart(monthly),
        "yearly_chart": _chart(yearly),
        "monthly_rows": list(reversed(monthly)),
        "yearly_rows": list(reversed(yearly)),
        "category_chart": {"labels": [c["label"] for c in categories], "values": [c["total"] for c in categories]},
        "recent_leads": leads.select_related("assigned_to", "station").order_by("-submitted_at")[:8],
        "follow_ups": follow_ups,
        "now": timezone.now(),
        "today": today,
        "week_start": today - timedelta(days=today.weekday()),
    })
