from django.contrib import admin
from .models import GradeRequest

@admin.register(GradeRequest)
class GradeRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "card_name", "predicted_grade", "needs_better_photos", "created_at")
    search_fields = ("card_name","user__username")
    list_filter = ("needs_better_photos", "created_at")
    readonly_fields = ("raw_json",)
