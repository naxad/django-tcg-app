from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path("verification-sent/", views.verification_sent, name="verification_sent"),
    path("activate/<uidb64>/<token>/", views.activate, name="activate"),

]
