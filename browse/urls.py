from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView

app_name = 'browse'

urlpatterns = [
    path('', views.browse, name='browse'),
    path('card/<int:card_id>/', views.card_detail, name='card_detail'),
   
    path('card/<int:pk>/', views.card_detail, name='card_detail'),

    # for ajax star rating
    path('rate/', views.rate_card, name='rate_card'),
]
