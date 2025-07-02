from django.urls import path
from . import views



urlpatterns = [
    # Combined profile + dashboard view
    path('', views.profile_view, name='profile'),
    
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/dashboard/view/', views.profile_dashboard_view, name='dashboard_view')
   
]
