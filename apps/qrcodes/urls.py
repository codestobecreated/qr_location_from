from django.urls import path

from . import views

app_name = "qrcodes"

urlpatterns = [
    path("", views.qr_list, name="list"),
    path("<int:pk>/", views.qr_detail, name="detail"),
    path("<int:pk>/png/", views.qr_png, name="png"),
    path("<int:pk>/thumb/", views.qr_thumb, name="thumb"),
    path("<int:pk>/pdf/", views.qr_pdf, name="pdf"),
    path("<int:pk>/toggle/", views.qr_toggle, name="toggle"),
]
