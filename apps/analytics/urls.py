from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("qr/<int:pk>/", views.station_analytics, name="station"),
]
