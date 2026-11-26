from django.shortcuts import render
from django.utils import timezone

from apps.accounts.audit import log_action
from apps.accounts.models import AuditLog
from apps.accounts.permissions import MANAGER, role_required, scope_stations
from apps.analytics import services as svc
from apps.analytics.views import _scoped
from apps.core.exports import export_response, xlsx_response
from apps.leads.models import EnquiryCategory, LeadStatus
from apps.leads.views import LEAD_EXPORT_HEADERS, lead_export_rows
from apps.stations.models import ChargingStation

PERF_HEADERS = ["QR Scans", "Form Visits", "Form Submissions", "Total Leads", "Converted Leads", "Conversion Rate (%)"]


def _perf(r):
    return [r.m_scans, r.m_form_views, r.m_submissions, r.m_leads, r.m_converted, round(r.m_rate, 2)]


def station_perf_rows(stations, dr):
    for s in svc.station_metrics(stations, dr).order_by("-m_leads", "name"):
        yield [s.station_id, s.name, "Active" if s.qr_mapping.is_active else "Inactive"] + _perf(s)


STATION_PERF_HEADERS = ["QR ID", "QR Name", "Status"] + PERF_HEADERS


@role_required(MANAGER)
def index(request):
    dr = svc.date_range_from_request(request, default="30d")
    report = request.GET.get("report")
    fmt = request.GET.get("format", "xlsx")
    if fmt not in ("xlsx", "csv"):
        fmt = "xlsx"
    if report:
        response = build_report(request, report, fmt, dr)
        if response is not None:
            log_action(request, AuditLog.Action.EXPORT, None, f"Report '{report}' ({fmt}), {dr.label}", object_type="Report")
            return response
    leads, scans, _ = _scoped(request)
    return render(request, "reports/index.html", {
        "dr": dr, "presets": svc.RANGE_PRESETS,
        "totals": svc.funnel_totals(leads, scans, dr),
        "stations": scope_stations(ChargingStation.objects.order_by("name"), request.user).only("pk", "name", "station_id"),
        "categories": EnquiryCategory.choices, "statuses": LeadStatus.choices,
    })


def build_report(request, report, fmt, dr):
    leads, scans, stations = _scoped(request)
    stamp = dr.label.replace(" ", "_").replace("–", "to")
    if report in ("daily", "weekly", "monthly", "yearly"):
        series = svc.time_series(leads, scans, report, dr)
        rows = ([r["period"], r["label"], r["scans"], r["leads"], r["converted"], svc.pct(r["converted"], r["leads"])]
                for r in series)
        return export_response(fmt, f"relux_{report}_report_{stamp}",
                               ["Period start", "Period", "QR Scans", "Leads", "Converted", "Conversion Rate (%)"],
                               rows, f"{report.title()} report")
    if report == "category":
        rows = ([r["label"], r["total"], r["converted"], r["rate"]] for r in svc.category_distribution(leads, dr))
        return export_response(fmt, f"relux_category_wise_{stamp}",
                               ["Category", "Leads", "Converted", "Conversion Rate (%)"], rows, "Category-wise")
    if report == "leads":
        qs = leads.filter(dr.lead_q()).order_by("-submitted_at")
        return export_response(fmt, f"relux_leads_{stamp}", LEAD_EXPORT_HEADERS, lead_export_rows(qs), "Leads")
    if report == "scans":
        qs = scans.filter(dr.scan_q()).select_related("station").order_by("-scanned_at")
        rows = (
            [timezone.localtime(s.scanned_at), s.station.station_id,
             s.station.name, s.token, s.device_type, s.os, s.browser, "Yes" if s.is_bot else "No",
             "Yes" if s.is_repeat else "No", "Yes" if s.form_viewed else "No", "Yes" if s.submitted else "No",
             s.utm_source, s.utm_medium, s.utm_campaign]
            for s in qs.iterator(chunk_size=1000)
        )
        return export_response(fmt, f"relux_qr_scans_{stamp}",
                               ["Scanned at", "QR ID", "QR Name", "QR Token", "Device",
                                "OS", "Browser", "Bot", "Repeat", "Form viewed", "Submitted", "UTM Source",
                                "UTM Medium", "UTM Campaign"], rows, "QR scans")
    if report == "full":
        totals = svc.funnel_totals(leads, scans, dr)
        summary = [
            ["Report period", dr.label], ["Generated", timezone.localtime()],
            ["QR scans (genuine)", totals["scans"]], ["Form visits", totals["form_views"]],
            ["Form submissions", totals["submissions"]], ["Total leads", totals["leads"]],
            ["Converted leads", totals["converted"]], ["Conversion rate (%)", totals["conversion_rate"]],
            ["Bot hits excluded", totals["bots"]],
        ]
        sheets = [
            ("Summary", ["Metric", "Value"], summary),
            ("Monthly", ["Period start", "Period", "QR Scans", "Leads", "Converted"],
             [[r["period"], r["label"], r["scans"], r["leads"], r["converted"]]
              for r in svc.time_series(leads, scans, "monthly", dr)]),
            ("Leads", LEAD_EXPORT_HEADERS, list(lead_export_rows(leads.filter(dr.lead_q()).order_by("-submitted_at")))),
        ]
        stamp_now = timezone.localtime().strftime("%Y%m%d_%H%M")
        return xlsx_response(f"relux_full_report_{stamp}_{stamp_now}", sheets)
    return None
