from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.home, name='home'),
    path('browse/', views.browse, name='browse'),
    path('contact/', views.contact, name='contact'),
    path('sell/', views.sell, name='sell'),
    path('card/<int:card_id>/', views.card_detail, name='card_detail'),

    # Auth
    path('register/', views.register, name='register'),
    path('login/', auth_views.LoginView.as_view(template_name='shop/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='home'), name='logout'),
    path('profile/', views.profile, name='profile'),

    # AJAX rating endpoint
    path('rate-card/', views.rate_card, name='rate_card'),
]
