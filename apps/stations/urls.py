from django.urls import path

from . import views

app_name = "stations"

urlpatterns = [
    path("", views.station_list, name="list"),
    path("add/", views.station_create, name="create"),
    path("import/", views.station_import, name="import"),
    path("import/template/", views.station_import_template, name="import_template"),
    path("export/", views.station_export, name="export"),
    path("bulk-status/", views.station_bulk_status, name="bulk_status"),
    path("<int:pk>/", views.station_detail, name="detail"),
    path("<int:pk>/edit/", views.station_edit, name="edit"),
    path("<int:pk>/status/", views.station_set_status, name="set_status"),
]
