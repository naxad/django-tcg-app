from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('<int:order_id>/', views.order_detail, name='detail'),
    path("checkout/shipping/", views.checkout_shipping, name="checkout_shipping"),
]
