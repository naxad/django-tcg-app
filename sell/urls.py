from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView



urlpatterns = [
    
    
    path('', views.sell, name='sell'),
    path('submit', views.submit_card, name='submit_card'),
    path('thank_you/', views.thank_you, name='thank_you'),
    

]
