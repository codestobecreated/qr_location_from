"""
Public customer flow: QR scan -> enquiry form -> thank-you.

SECURITY: the station is resolved ONLY from the QR token in the URL, looked up in the database.
No station/location identifier is ever accepted from the customer.
"""
import secrets
import time
from datetime import timedelta

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.core.models import SystemSetting
from apps.core.utils import UTM_KEYS, get_client_ip, request_metadata
from apps.qrcodes.models import QRCodeMapping, QRScanEvent, QRTokenHistory

from .forms import EnquiryForm
from .models import Lead, LeadStatus, LeadStatusHistory

REPEAT_WINDOW_SECONDS = 30 * 60
MAX_NONCES = 5


def _resolve(token):
    """Return (mapping, retired_history) for a token. Exactly one lookup, by token only."""
    if not token or len(token) > 64:
        return None, None
    mapping = (
        QRCodeMapping.objects.select_related("station", "station__location").filter(token=token).first()
    )
    if mapping:
        return mapping, None
    return None, QRTokenHistory.objects.select_related("station").filter(token=token).first()


def _accepting(mapping):
    station = mapping.station
    return mapping.is_active and station.is_active and station.location.is_active


def _session_ready(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def _record_scan(request, mapping, accepting):
    meta = request_metadata(request)
    is_bot = meta["device_type"] == "Bot"
    session_key = ""
    is_repeat = False
    if not is_bot:
        session_key = _session_ready(request)
        last = request.session.get(f"scan_ts:{mapping.token}")
        now = time.time()
        is_repeat = bool(last and now - last < REPEAT_WINDOW_SECONDS)
        request.session[f"scan_ts:{mapping.token}"] = now
    event = QRScanEvent.objects.create(
        mapping=mapping, station=mapping.station, location=mapping.station.location, token=mapping.token,
        session_key=session_key or "", ip_address=meta["ip_address"], user_agent=meta["user_agent"],
        device_type=meta["device_type"], browser=meta["browser"], os=meta["os"], referer=meta["referer"],
        is_bot=is_bot, is_repeat=is_repeat, station_accepting=accepting,
        **{k: meta[k] for k in UTM_KEYS},
    )
    if not is_bot:
        request.session[f"scan_id:{mapping.token}"] = event.pk
    return event


def _issue_nonce(request, token):
    nonce = secrets.token_urlsafe(24)
    key = f"nonces:{token}"
    nonces = (request.session.get(key) or [])[-(MAX_NONCES - 1):]
    nonces.append(nonce)
    request.session[key] = nonces
    return nonce


def _context(mapping, form, **extra):
    station = mapping.station
    ctx = {"mapping": mapping, "station": station, "location": station.location, "form": form,
           "settings_obj": SystemSetting.load()}
    ctx.update(extra)
    return ctx


def _rate_limited(request):
    limit = SystemSetting.load().max_submissions_per_hour
    key = f"enquiry-rate:{get_client_ip(request)}"
    count = cache.get(key, 0)
    if count >= limit:
        return True
    cache.set(key, count + 1, 3600)
    return False


@never_cache
def qr_landing(request, token):
    if request.method not in ("GET", "POST", "HEAD"):
        return HttpResponseNotAllowed(["GET", "POST"])
    mapping, retired = _resolve(token)
    if mapping is None:
        if retired is not None:
            return render(request, "customer/retired.html", {"retired": retired}, status=410)
        return render(request, "customer/invalid.html", status=404)

    accepting = _accepting(mapping)
    if request.method == "HEAD":
        return render(request, "customer/enquiry.html", _context(mapping, EnquiryForm()))

    if request.method == "GET":
        _record_scan(request, mapping, accepting)
        if not accepting:
            return render(request, "customer/unavailable.html", _context(mapping, None), status=200)
        form = EnquiryForm(initial={"submission_key": _issue_nonce(request, token)})
        return render(request, "customer/enquiry.html", _context(mapping, form))

    # POST – submit enquiry
    if not accepting:
        return render(request, "customer/unavailable.html", _context(mapping, None))

    form = EnquiryForm(request.POST)
    if not form.is_valid():
        # Re-render with errors and a fresh nonce.
        data = request.POST.copy()
        data["submission_key"] = _issue_nonce(request, token)
        form = EnquiryForm(data)
        form.is_valid()
        return render(request, "customer/enquiry.html", _context(mapping, form), status=400)

    if form.cleaned_data.get("website"):
        # Honeypot filled -> silently drop the bot submission.
        return redirect("public:thank_you", token=token)

    submitted_key = form.cleaned_data.get("submission_key") or ""
    nonces = request.session.get(f"nonces:{token}") or []

    # Same form submitted twice (double tap / back + resubmit): show the original thank-you.
    existing = Lead.objects.filter(submission_key=submitted_key).first() if submitted_key else None
    if existing and existing.qr_mapping_id == mapping.pk:
        request.session[f"thanks:{token}"] = existing.pk
        return redirect("public:thank_you", token=token)

    if _rate_limited(request):
        return render(request, "customer/enquiry.html",
                      _context(mapping, form, rate_limited=True), status=429)

    key = submitted_key if submitted_key in nonces else secrets.token_urlsafe(24)
    lead = _create_lead(request, mapping, form.cleaned_data, key)
    if lead is None:  # raced with an identical submission
        lead = Lead.objects.filter(submission_key=key).first()
    if submitted_key in nonces:
        request.session[f"nonces:{token}"] = [n for n in nonces if n != submitted_key]
    request.session[f"thanks:{token}"] = lead.pk
    return redirect("public:thank_you", token=token)


def _create_lead(request, mapping, data, key):
    station = mapping.station
    location = station.location
    settings_obj = SystemSetting.load()
    meta = request_metadata(request)
    scan_event = None
    scan_id = request.session.get(f"scan_id:{mapping.token}")
    if scan_id:
        scan_event = QRScanEvent.objects.filter(pk=scan_id, mapping=mapping).first()
    utm = {k: (getattr(scan_event, k, "") if scan_event else "") or meta[k] for k in UTM_KEYS}

    now = timezone.now()
    original = (
        Lead.objects.filter(
            mobile=data["mobile"], station=station, is_duplicate=False,
            submitted_at__gte=now - timedelta(minutes=settings_obj.duplicate_window_minutes),
        ).order_by("submitted_at").first()
    )
    try:
        with transaction.atomic():
            lead = Lead.objects.create(
                full_name=data["full_name"], mobile=data["mobile"], email=data.get("email", ""),
                category=data["category"], message=data.get("message", ""), consent=True, consent_at=now,
                location=location, station=station, qr_mapping=mapping, qr_token=mapping.token,
                scan_event=scan_event, location_code=location.location_id, location_name=location.name,
                station_code=station.station_id, station_name=station.name,
                source_city=station.city, source_state=station.state, submitted_at=now,
                ip_address=meta["ip_address"], user_agent=meta["user_agent"], device_type=meta["device_type"],
                browser=meta["browser"], os=meta["os"], referer=meta["referer"],
                submission_key=key, is_duplicate=original is not None, duplicate_of=original,
                **utm,
            )
            LeadStatusHistory.objects.create(lead=lead, from_status="", to_status=LeadStatus.NEW,
                                             note="Enquiry submitted via QR code")
            if scan_event:
                QRScanEvent.objects.filter(pk=scan_event.pk).update(
                    submitted=True, submitted_at=now, form_viewed=True,
                    form_viewed_at=scan_event.form_viewed_at or now,
                )
    except IntegrityError:
        return None
    return lead


@never_cache
def thank_you(request, token):
    mapping, _ = _resolve(token)
    if mapping is None:
        return render(request, "customer/invalid.html", status=404)
    lead_id = request.session.get(f"thanks:{token}")
    lead = Lead.objects.filter(pk=lead_id, qr_mapping=mapping).first() if lead_id else None
    return render(request, "customer/thank_you.html", _context(mapping, None, lead=lead))


@require_POST
def form_view_beacon(request, token):
    """Called by the enquiry page's JS once it renders: proves a real browser displayed the form."""
    mapping, _ = _resolve(token)
    scan_id = request.session.get(f"scan_id:{token}")
    if mapping and scan_id:
        QRScanEvent.objects.filter(pk=scan_id, mapping=mapping, form_viewed=False).update(
            form_viewed=True, form_viewed_at=timezone.now()
        )
    return JsonResponse({"ok": True})


def privacy_policy(request):
    return render(request, "customer/privacy.html", {"settings_obj": SystemSetting.load()})
