from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView



urlpatterns = [
    
    path('', views.contact_view, name='contact'),

    

]
