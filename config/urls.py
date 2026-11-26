from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "RELUX ELECTRIC – System Admin"
admin.site.site_title = "RELUX Lead Management"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dashboard:home", permanent=False)),
    path("django-admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("qr-codes/", include("apps.qrcodes.urls")),
    path("leads/", include("apps.leads.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("reports/", include("apps.reports.urls")),
    # Public customer-facing routes (QR landing, enquiry, thank-you, privacy)
    path("", include("apps.leads.public_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
