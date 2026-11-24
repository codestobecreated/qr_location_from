from django.urls import path

from . import public_views

app_name = "public"

urlpatterns = [
    path("q/<str:token>/", public_views.qr_landing, name="qr_landing"),
    path("q/<str:token>/thank-you/", public_views.thank_you, name="thank_you"),
    path("q/<str:token>/viewed/", public_views.form_view_beacon, name="form_viewed"),
    path("privacy-policy/", public_views.privacy_policy, name="privacy"),
]
