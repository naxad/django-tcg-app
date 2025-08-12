from django.contrib import admin
from .models import ShippingMethod

@admin.register(ShippingMethod)
class ShippingMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "free_over", "is_active", "eta") #here i set the shipping details/prices
    list_filter = ("is_active",)
    search_fields = ("name",)
