from django.contrib import admin
from .models import CardSubmission

@admin.register(CardSubmission)
class CardSubmissionAdmin(admin.ModelAdmin):
    list_display = ['card_name', 'seller_name', 'condition', 'submitted_at']
    readonly_fields = ['submitted_at']
