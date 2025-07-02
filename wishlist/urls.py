# wishlist/urls.py

from django.urls import path
from . import views



urlpatterns = [
    path('', views.wishlist_view, name='wishlist'),
    path('add/<int:card_id>/', views.add_to_wishlist, name='add_to_wishlist'),
    path('remove/<int:card_id>/', views.remove_from_wishlist, name='remove_from_wishlist'),
    path('toggle/<int:card_id>/', views.toggle_wishlist, name='toggle_wishlist'),
    path('wishlist/add/<int:card_id>/', views.add_to_wishlist, name='add_to_wishlist'),
    path('wishlist/remove/<int:card_id>/', views.remove_from_wishlist, name='remove_from_wishlist'),
    
]
