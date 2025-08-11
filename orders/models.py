from django.db import models

# Create your models here.
from django.conf import settings
from django.db import models
from django.utils import timezone
from browse.models import Card

class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    email = models.EmailField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending")
    currency = models.CharField(max_length=10, default="EUR")
    total = models.DecimalField(max_digits=10, decimal_places=2)
    gateway = models.CharField(max_length=20, blank=True)      # 'stripe' or 'paypal'
    gateway_id = models.CharField(max_length=255, blank=True)  # session id / order id
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # --- NEW: shipping snapshot stored on the order ---
    shipping_name = models.CharField(max_length=120, blank=True)
    shipping_phone = models.CharField(max_length=30, blank=True)
    shipping_line1 = models.CharField(max_length=255, blank=True)
    shipping_line2 = models.CharField(max_length=255, blank=True)
    shipping_city = models.CharField(max_length=120, blank=True)
    shipping_state = models.CharField(max_length=120, blank=True)
    shipping_postal_code = models.CharField(max_length=20, blank=True)
    shipping_country = models.CharField(max_length=2, blank=True)
    # link back to a saved address for convenience (string ref avoids import cycle)
    shipping_address = models.ForeignKey(
        "userprofile.Address",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="orders"
    )

    def __str__(self):
        return f"Order #{self.id} - {self.status}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    card = models.ForeignKey(Card, on_delete=models.PROTECT)
    name = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)

    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.quantity} × {self.name} (Order #{self.order_id})"

class Payment(models.Model):
    order = models.OneToOneField(Order, related_name="payment", on_delete=models.CASCADE)
    gateway = models.CharField(max_length=20)                  # 'stripe' or 'paypal'
    gateway_ref = models.CharField(max_length=255)             # intent/capture id
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    raw = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.gateway} {self.amount} for Order #{self.order_id}"
