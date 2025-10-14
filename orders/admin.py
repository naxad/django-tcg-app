from django.contrib import admin
from .models import ShippingMethod, ShippingRate
from .models import Order, OrderItem, Payment

class ShippingRateInline(admin.TabularInline):
    model = ShippingRate
    extra = 1

@admin.register(ShippingMethod)
class ShippingMethodAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "sort_order", "price", "free_over", "eta")
    list_filter  = ("is_active",)
    search_fields = ("code", "name")
    inlines = [ShippingRateInline]

@admin.register(ShippingRate)
class ShippingRateAdmin(admin.ModelAdmin):
    list_display = ("method", "country", "price")
    list_filter  = ("country", "method")
    search_fields = ("country", "method__code", "method__name")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id","user","email","status","total","gateway","created_at","paid_at")
    list_filter = ("status","gateway","created_at")
    inlines = [OrderItemInline]

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order","gateway","gateway_ref","amount","created_at")