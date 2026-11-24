from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("locations/<int:pk>/", views.location_analytics, name="location"),
    path("stations/<int:pk>/", views.station_analytics, name="station"),
]
