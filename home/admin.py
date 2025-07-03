from django.contrib import admin
from .models import CarouselItem

@admin.register(CarouselItem)
class CarouselItemAdmin(admin.ModelAdmin):
    list_display = ['title', 'card', 'is_active', 'order']
    list_editable = ['is_active', 'order']
