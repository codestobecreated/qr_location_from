from pathlib import Path

from django.conf import settings

from .models import SystemSetting

_TAILWIND_BUILD = Path(settings.BASE_DIR) / "static" / "css" / "tailwind.build.css"


def branding(request):
    return {
        "site_settings": SystemSetting.load(),
        "QR_BASE_URL": settings.QR_BASE_URL,
        # Use a compiled Tailwind stylesheet when present (see README), else the Tailwind CDN runtime.
        "TAILWIND_BUILD": _TAILWIND_BUILD.exists(),
    }
