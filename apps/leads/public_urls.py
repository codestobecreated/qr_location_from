from django.urls import path

from . import public_views

app_name = "public"

urlpatterns = [
    # THE RELUX QR code points here. NEVER change these paths – the printed QR depends on them.
    path("qr", public_views.main_qr, name="main_qr"),
    path("qr/", public_views.main_qr),
    path("qr/thank-you/", public_views.main_thank_you, name="main_thank_you"),
    path("qr/viewed/", public_views.main_viewed, name="main_viewed"),
    # Older per-QR links keep working.
    path("q/<str:token>/", public_views.qr_landing, name="qr_landing"),
    path("q/<str:token>/thank-you/", public_views.thank_you, name="thank_you"),
    path("q/<str:token>/viewed/", public_views.form_view_beacon, name="form_viewed"),
    path("privacy-policy/", public_views.privacy_policy, name="privacy"),
]
