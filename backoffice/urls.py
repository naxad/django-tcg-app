from django.urls import path
from . import views

app_name = "backoffice"

urlpatterns = [
    path("orders/", views.orders_list, name="orders_list"),
    path("orders/export.csv", views.orders_export_csv, name="orders_export_csv"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/shipping/", views.order_shipping_edit, name="order_shipping_edit"),
]
