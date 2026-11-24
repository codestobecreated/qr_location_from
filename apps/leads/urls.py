from django.urls import path

from . import views

app_name = "leads"

urlpatterns = [
    path("", views.lead_list, name="list"),
    path("export/", views.lead_export, name="export"),
    path("bulk/", views.lead_bulk_action, name="bulk_action"),
    path("<int:pk>/", views.lead_detail, name="detail"),
    path("<int:pk>/status/", views.lead_update_status, name="update_status"),
    path("<int:pk>/note/", views.lead_add_note, name="add_note"),
    path("<int:pk>/assign/", views.lead_assign, name="assign"),
]
