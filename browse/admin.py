from django.contrib import admin
from .models import Card

@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ('name', 'brand', 'price')
    search_fields = ('name', 'brand')
    list_filter = ('brand', 'is_featured')
