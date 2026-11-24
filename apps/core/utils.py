"""Shared helpers: request metadata, user-agent parsing and bot detection."""
import re

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")

BOT_PATTERN = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|whatsapp|telegram|slack|discord|"
    r"skypeuripreview|linkedinbot|embedly|quora link|pinterest|vkshare|w3c_validator|"
    r"curl|wget|python-requests|python-urllib|httpx|aiohttp|go-http-client|java/|okhttp|"
    r"libwww|httpclient|headlesschrome|phantomjs|selenium|puppeteer|lighthouse|pingdom|"
    r"uptime|monitor|scanner|axios|node-fetch|postman",
    re.IGNORECASE,
)


def get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "")
    return ip or None


def is_bot_user_agent(user_agent):
    ua = (user_agent or "").strip()
    if len(ua) < 10:
        return True
    return bool(BOT_PATTERN.search(ua))


def parse_user_agent(user_agent):
    """Very small, dependency-free UA parser returning device type, OS and browser."""
    ua = user_agent or ""
    low = ua.lower()

    if is_bot_user_agent(ua):
        device = "Bot"
    elif "ipad" in low or ("tablet" in low) or ("android" in low and "mobile" not in low):
        device = "Tablet"
    elif any(k in low for k in ("mobi", "iphone", "ipod", "android", "windows phone")):
        device = "Mobile"
    else:
        device = "Desktop"

    if "windows phone" in low:
        os_name = "Windows Phone"
    elif "android" in low:
        m = re.search(r"android\s([\d.]+)", low)
        os_name = f"Android {m.group(1)}" if m else "Android"
    elif "iphone" in low or "ipad" in low or "ipod" in low:
        m = re.search(r"os (\d+)[_.](\d+)", low)
        os_name = f"iOS {m.group(1)}.{m.group(2)}" if m else "iOS"
    elif "windows nt" in low:
        os_name = "Windows"
    elif "mac os x" in low or "macintosh" in low:
        os_name = "macOS"
    elif "cros" in low:
        os_name = "ChromeOS"
    elif "linux" in low:
        os_name = "Linux"
    else:
        os_name = "Other"

    browser_rules = (
        (r"gsa/([\d.]+)", "Google App"),
        (r"samsungbrowser/([\d.]+)", "Samsung Internet"),
        (r"edg(?:a|ios|e)?/([\d.]+)", "Edge"),
        (r"opr/([\d.]+)|opera", "Opera"),
        (r"ucbrowser/([\d.]+)", "UC Browser"),
        (r"miuibrowser/([\d.]+)", "MIUI Browser"),
        (r"fxios/([\d.]+)|firefox/([\d.]+)", "Firefox"),
        (r"crios/([\d.]+)|chrome/([\d.]+)", "Chrome"),
        (r"version/([\d.]+).*safari", "Safari"),
    )
    browser = "Other"
    for pattern, name in browser_rules:
        m = re.search(pattern, low)
        if m:
            version = next((g for g in m.groups() if g), "") if m.groups() else ""
            major = version.split(".")[0] if version else ""
            browser = f"{name} {major}".strip()
            break
    if browser == "Other" and "; wv)" in low:
        browser = "Android WebView"
    return {"device_type": device, "os": os_name, "browser": browser}


def request_metadata(request):
    """Collect server-side metadata for scans and leads (never trusts form input)."""
    ua = request.META.get("HTTP_USER_AGENT", "")[:500]
    meta = parse_user_agent(ua)
    meta.update(
        {
            "user_agent": ua,
            "ip_address": get_client_ip(request),
            "referer": request.META.get("HTTP_REFERER", "")[:500],
        }
    )
    for key in UTM_KEYS:
        meta[key] = (request.GET.get(key) or "")[:150]
    return meta


def safe_next(request, default):
    """Return the POSTed/GET 'next' URL only if it is a safe local URL, else the default."""
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return default
