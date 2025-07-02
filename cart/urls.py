from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView



urlpatterns = [
    
    path('add-to-cart/<int:card_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/', views.view_cart, name='cart'),
    path('remove-from-cart/<int:card_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('checkout/', views.checkout, name='checkout'),
    path('cart/update/<int:card_id>/', views.update_cart_quantity, name='update_cart_quantity'),
    

]
