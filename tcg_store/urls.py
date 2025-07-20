"""
URL configuration for tcg_store project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
  
    path('accounts/', include('accounts.urls')),
    path('userprofile/', include('userprofile.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('wishlist/', include('wishlist.urls', namespace='wishlist')),

    path('cart/', include('cart.urls', namespace='cart')),
    path('dashboard/', include('dashboard.urls')),
    path('', include('home.urls', namespace='home')), # all views are routed to the home app
    path('browse/', include('browse.urls')),
    path('contact/', include('contact.urls', namespace='contact')),
    path('sell/', include('sell.urls', namespace='sell')),

    path('password_change/', auth_views.PasswordChangeView.as_view(template_name='shop/password_change.html'), name='password_change'),
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='shop/password_change_done.html'), name='password_change_done'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)