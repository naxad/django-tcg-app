from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView

urlpatterns = [
    path('', views.home, name='home'),
    path('browse/', views.browse, name='browse'),
    path('contact/', views.contact, name='contact'),
    path('sell/', views.sell, name='sell'),
    path('card/<int:card_id>/', views.card_detail, name='card_detail'),
    path('add-to-cart/<int:card_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/', views.view_cart, name='cart'),
    path('remove-from-cart/<int:card_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('checkout/', views.checkout, name='checkout'),

    path('remove-from-cart/<int:card_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('cart/update/<int:card_id>/', views.update_cart_quantity, name='update_cart_quantity'),
    path('wishlist/add/<int:card_id>/', views.add_to_wishlist, name='add_to_wishlist'),
    path('wishlist/remove/<int:card_id>/', views.remove_from_wishlist, name='remove_from_wishlist'),
    path('wishlist/toggle/<int:card_id>/', views.toggle_wishlist, name='toggle_wishlist'),



    # Combined profile + dashboard view
    path('profile/', views.profile_view, name='profile'),

    path('profile/edit/', views.edit_profile, name='edit_profile'),

    # auth
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='shop/login.html'), name='login'),
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),

    # AJAX rating
    path('rate-card/', views.rate_card, name='rate_card'),
]
