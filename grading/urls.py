from django.urls import path
from . import views

app_name = "grading"

urlpatterns = [
    path("grade/", views.grade_card, name="grade"),
    path("result/<int:pk>/", views.grade_result, name="result"),
]
