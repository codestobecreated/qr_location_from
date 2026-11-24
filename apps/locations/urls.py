from django.urls import path

from . import views

app_name = "locations"

urlpatterns = [
    path("", views.location_list, name="list"),
    path("add/", views.location_create, name="create"),
    path("import/", views.location_import, name="import"),
    path("import/template/", views.location_import_template, name="import_template"),
    path("export/", views.location_export, name="export"),
    path("bulk-status/", views.location_bulk_status, name="bulk_status"),
    path("<int:pk>/", views.location_detail, name="detail"),
    path("<int:pk>/edit/", views.location_edit, name="edit"),
    path("<int:pk>/delete/", views.location_delete, name="delete"),
    path("<int:pk>/toggle/", views.location_toggle, name="toggle"),
]
