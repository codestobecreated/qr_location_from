"""
All analytics are computed live from the database.

Funnel definitions
  QR scans      – visits to a valid QR URL, excluding detected bots and repeat opens by the same browser within 30 min
  Form visits   – scans where a real browser rendered the enquiry form (JS beacon)
  Submissions   – every accepted enquiry submission (including duplicates)
  Leads         – unique enquiries (duplicates excluded)
  Converted     – leads whose status is Converted
  Conversion %  – converted / leads
"""
from datetime import date, datetime, time, timedelta

from django.db.models import Count, F, FloatField, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Cast, Coalesce, NullIf, TruncDate, TruncMonth, TruncWeek
from django.utils import timezone

from apps.leads.models import Lead, LeadStatus
from apps.qrcodes.models import QRScanEvent

GENUINE_SCAN = Q(is_bot=False, is_repeat=False)

RANGE_PRESETS = [
    ("7d", "Last 7 days", 7), ("30d", "Last 30 days", 30), ("90d", "Last 90 days", 90),
    ("365d", "Last 12 months", 365), ("all", "All time", None),
]


class DateRange:
    def __init__(self, start=None, end=None, key="30d", label="Last 30 days"):
        self.start, self.end, self.key, self.label = start, end, key, label

    @property
    def start_dt(self):
        return _aware(self.start) if self.start else None

    @property
    def end_dt(self):
        return _aware(self.end + timedelta(days=1)) if self.end else None

    def lead_q(self, prefix=""):
        q = Q()
        if self.start:
            q &= Q(**{f"{prefix}submitted_at__gte": self.start_dt})
        if self.end:
            q &= Q(**{f"{prefix}submitted_at__lt": self.end_dt})
        return q

    def scan_q(self, prefix=""):
        q = Q()
        if self.start:
            q &= Q(**{f"{prefix}scanned_at__gte": self.start_dt})
        if self.end:
            q &= Q(**{f"{prefix}scanned_at__lt": self.end_dt})
        return q

    def as_query(self):
        if self.key == "custom":
            return f"range=custom&start={self.start:%Y-%m-%d}&end={self.end:%Y-%m-%d}"
        return f"range={self.key}"


def _aware(d):
    return timezone.make_aware(datetime.combine(d, time.min), timezone.get_current_timezone())


def _parse(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def date_range_from_request(request, default="30d"):
    key = request.GET.get("range", default)
    today = timezone.localdate()
    if key == "custom":
        start, end = _parse(request.GET.get("start")), _parse(request.GET.get("end"))
        if start and end and start <= end:
            return DateRange(start, end, "custom", f"{start:%d %b %Y} – {end:%d %b %Y}")
        key = default
    for k, label, days in RANGE_PRESETS:
        if k == key:
            if days is None:
                return DateRange(None, None, k, label)
            return DateRange(today - timedelta(days=days - 1), today, k, label)
    return DateRange(today - timedelta(days=29), today, "30d", "Last 30 days")


# ---------------------------------------------------------------------------
# Funnel totals
# ---------------------------------------------------------------------------
def funnel_totals(leads_qs, scans_qs, dr=None):
    if dr:
        leads_qs = leads_qs.filter(dr.lead_q())
        scans_qs = scans_qs.filter(dr.scan_q())
    s = scans_qs.aggregate(
        scans=Count("id", filter=GENUINE_SCAN),
        form_views=Count("id", filter=GENUINE_SCAN & Q(form_viewed=True)),
        bots=Count("id", filter=Q(is_bot=True)),
        raw=Count("id"),
    )
    l = leads_qs.aggregate(
        submissions=Count("id"),
        leads=Count("id", filter=Q(is_duplicate=False)),
        converted=Count("id", filter=Q(is_duplicate=False, status=LeadStatus.CONVERTED)),
    )
    data = {**s, **l}
    data["conversion_rate"] = pct(data["converted"], data["leads"])
    data["scan_to_lead_rate"] = pct(data["leads"], data["scans"])
    data["form_rate"] = pct(data["form_views"], data["scans"])
    data["submit_rate"] = pct(data["submissions"], data["form_views"])
    return data


def pct(num, den):
    return round(num * 100.0 / den, 2) if den else 0.0


# ---------------------------------------------------------------------------
# Per-station / per-location metrics via correlated sub-queries (no join explosion)
# ---------------------------------------------------------------------------
def _sub_count(model, fk, condition):
    sq = (
        model.objects.filter(condition, **{fk: OuterRef("pk")})
        .order_by().values(fk).annotate(c=Count("pk")).values("c")
    )
    return Coalesce(Subquery(sq, output_field=IntegerField()), Value(0))


def _annotate_metrics(qs, fk, dr=None):
    lead_q = dr.lead_q() if dr else Q()
    scan_q = dr.scan_q() if dr else Q()
    return qs.annotate(
        m_scans=_sub_count(QRScanEvent, fk, scan_q & GENUINE_SCAN),
        m_form_views=_sub_count(QRScanEvent, fk, scan_q & GENUINE_SCAN & Q(form_viewed=True)),
        m_submissions=_sub_count(Lead, fk, lead_q),
        m_leads=_sub_count(Lead, fk, lead_q & Q(is_duplicate=False)),
        m_converted=_sub_count(Lead, fk, lead_q & Q(is_duplicate=False, status=LeadStatus.CONVERTED)),
    ).annotate(
        m_rate=Coalesce(
            Cast(F("m_converted"), FloatField()) * 100.0 / NullIf(Cast(F("m_leads"), FloatField()), 0.0),
            Value(0.0),
        )
    )


def station_metrics(stations_qs, dr=None):
    return _annotate_metrics(stations_qs.select_related("location"), "station", dr)


def location_metrics(locations_qs, dr=None):
    return _annotate_metrics(locations_qs, "location", dr)


METRIC_SORTS = {
    "scans": "m_scans", "form_views": "m_form_views", "submissions": "m_submissions", "leads": "m_leads",
    "converted": "m_converted", "rate": "m_rate", "name": "name",
}


def sort_metrics(qs, sort, default="-leads"):
    sort = sort or default
    key = METRIC_SORTS.get(sort.lstrip("-"), "m_leads")
    order = f"-{key}" if sort.startswith("-") else key
    return qs.order_by(order, "name")


def top_and_bottom_stations(stations_qs, dr=None, n=10):
    qs = station_metrics(stations_qs.filter(status="active"), dr)
    top = list(qs.order_by("-m_leads", "-m_rate", "-m_scans", "name")[:n])
    bottom = list(qs.order_by("m_leads", "m_scans", "name")[:n])
    return top, bottom


# ---------------------------------------------------------------------------
# Group-by breakdowns and time series
# ---------------------------------------------------------------------------
def leads_by(leads_qs, field, dr=None, limit=None):
    qs = leads_qs.filter(is_duplicate=False)
    if dr:
        qs = qs.filter(dr.lead_q())
    rows = (
        qs.values(field).annotate(
            total=Count("id"),
            converted=Count("id", filter=Q(status=LeadStatus.CONVERTED)),
        ).order_by("-total", field)
    )
    rows = list(rows[:limit] if limit else rows)
    for r in rows:
        r["rate"] = pct(r["converted"], r["total"])
    return rows


def category_distribution(leads_qs, dr=None):
    from apps.leads.models import EnquiryCategory

    labels = dict(EnquiryCategory.choices)
    rows = leads_by(leads_qs, "category", dr)
    for r in rows:
        r["label"] = labels.get(r["category"], r["category"])
    return rows


TRUNC = {"daily": TruncDate, "weekly": TruncWeek, "monthly": TruncMonth}


def time_series(leads_qs, scans_qs, period="daily", dr=None, default_points=None):
    """Return list of {period, label, scans, leads, converted} with gaps filled."""
    trunc = TRUNC[period]
    tz = timezone.get_current_timezone()
    leads = leads_qs.filter(is_duplicate=False)
    scans = scans_qs.filter(GENUINE_SCAN)
    today = timezone.localdate()
    if dr and dr.start:
        start, end = dr.start, dr.end or today
    else:
        span = {"daily": 30, "weekly": 7 * 12, "monthly": 365}[period] if default_points is None else default_points
        first = leads.order_by("submitted_at").values_list("submitted_at", flat=True).first()
        start = timezone.localtime(first).date() if first else today - timedelta(days=span)
        start = max(start, today - timedelta(days=365 * 3))
        end = today
    leads = leads.filter(submitted_at__gte=_aware(start), submitted_at__lt=_aware(end + timedelta(days=1)))
    scans = scans.filter(scanned_at__gte=_aware(start), scanned_at__lt=_aware(end + timedelta(days=1)))

    def bucket_key(value):
        if isinstance(value, datetime):
            value = timezone.localtime(value, tz).date() if timezone.is_aware(value) else value.date()
        return value

    lead_rows = leads.annotate(p=trunc("submitted_at", tzinfo=tz)).values("p").annotate(
        total=Count("id"), converted=Count("id", filter=Q(status=LeadStatus.CONVERTED))
    )
    scan_rows = scans.annotate(p=trunc("scanned_at", tzinfo=tz)).values("p").annotate(total=Count("id"))
    lead_map = {bucket_key(r["p"]): r for r in lead_rows}
    scan_map = {bucket_key(r["p"]): r["total"] for r in scan_rows}

    buckets = []
    if period == "daily":
        d = start
        while d <= end:
            buckets.append((d, d.strftime("%d %b")))
            d += timedelta(days=1)
    elif period == "weekly":
        d = start - timedelta(days=start.weekday())
        while d <= end:
            buckets.append((d, f"Wk {d:%d %b}"))
            d += timedelta(days=7)
    else:
        d = date(start.year, start.month, 1)
        while d <= end:
            buckets.append((d, d.strftime("%b %Y")))
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    out = []
    for key, label in buckets:
        lr = lead_map.get(key, {})
        out.append({"period": key, "label": label, "scans": scan_map.get(key, 0),
                    "leads": lr.get("total", 0), "converted": lr.get("converted", 0)})
    return out


def device_breakdown(scans_qs, dr=None):
    qs = scans_qs.filter(GENUINE_SCAN)
    if dr:
        qs = qs.filter(dr.scan_q())
    return list(qs.values("device_type").annotate(total=Count("id")).order_by("-total"))
