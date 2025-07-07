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



    #this is for staff members to be able to add and delete cards from the browser section
    path('delete/<int:card_id>/', views.delete_card, name='delete_card'),
    path("add/", views.add_card, name="add_card"),
]
