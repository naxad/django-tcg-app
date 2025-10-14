from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = "legal"

urlpatterns = [
    path("privacy/",  TemplateView.as_view(template_name="legal/privacy.html"),  name="privacy"),
    path("terms/",    TemplateView.as_view(template_name="legal/terms.html"),    name="terms"),
    path("cookies/",  TemplateView.as_view(template_name="legal/cookies.html"),  name="cookies"),
    path("returns/",  TemplateView.as_view(template_name="legal/returns.html"),  name="returns"),
    path("shipping/", TemplateView.as_view(template_name="legal/shipping.html"), name="shipping"),
    path("imprint/",  TemplateView.as_view(template_name="legal/imprint.html"),  name="imprint"),
    path("about/", views.about, name="about"),
]
