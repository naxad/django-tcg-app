from django.conf import settings
from django.db import models
from django.utils import timezone
from browse.models import Card
from decimal import Decimal





class ShippingMethod(models.Model):
    name = models.CharField(max_length=80)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    free_over = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="If items subtotal ≥ this number, shipping becomes €0"
    )
    eta = models.CharField(max_length=60, blank=True)  # e.g. "2–4 business days"

    def effective_price(self, items_subtotal: Decimal) -> Decimal:
        if self.free_over is not None and items_subtotal >= self.free_over:
            return Decimal("0.00")
        return self.price

    def __str__(self):
        return self.name




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

    gateway = models.CharField(max_length=20, blank=True)
    gateway_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # --- shipping address snapshot ---
    shipping_name = models.CharField(max_length=120, blank=True)
    shipping_phone = models.CharField(max_length=30, blank=True)
    shipping_line1 = models.CharField(max_length=255, blank=True)
    shipping_line2 = models.CharField(max_length=255, blank=True)
    shipping_city = models.CharField(max_length=120, blank=True)
    shipping_state = models.CharField(max_length=120, blank=True)
    shipping_postal_code = models.CharField(max_length=20, blank=True)
    shipping_country = models.CharField(max_length=2, blank=True)
    shipping_address = models.ForeignKey(
        "userprofile.Address", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )

    # --- fulfillment/admin (yours) ---
    FULFILL_CHOICES = [
        ("new", "New"),
        ("processing", "Processing"),
        ("packed", "Packed"),
        ("shipped", "Shipped"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    ]
    fulfillment_status = models.CharField(max_length=20, choices=FULFILL_CHOICES, default="new")
    tracking_number   = models.CharField(max_length=100, blank=True)
    carrier           = models.CharField(max_length=100, blank=True)
    shipped_at        = models.DateTimeField(null=True, blank=True)
    admin_note        = models.TextField(blank=True)

    # --- PRICING pieces you asked about ---
    shipping_method = models.ForeignKey(ShippingMethod, null=True, blank=True, on_delete=models.SET_NULL)
    shipping_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    items_subtotal  = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    def __str__(self):
        return f"Order #{self.id} - {self.status}"

    def mark_shipped(self):
        self.fulfillment_status = "shipped"
        self.shipped_at = timezone.now()
        self.save(update_fields=["fulfillment_status", "shipped_at"])

    # ------ WHERE items_subtotal comes from ------
    def _line_items_qs(self):
        """
        Tries common related names. If your OrderItem has related_name='items',
        this returns self.items.all(). Otherwise, it tries Django’s default
        orderitem_set. Adjust if your related name is different.
        """
        if hasattr(self, "items"):
            return self.items.all()
        if hasattr(self, "orderitem_set"):
            return self.orderitem_set.all()
        return []

    def _calc_items_subtotal(self) -> Decimal:
        """
        Sums each line's total. If your line model stores 'unit_price' and 'quantity',
        it multiplies those. If it already has a 'total' field, that is used.
        """
        total = Decimal("0.00")
        for li in self._line_items_qs():
            # Preferred: a stored field called 'total'
            line_total = getattr(li, "total", None)
            if line_total is not None:
                total += Decimal(line_total)
                continue

            qty = Decimal(getattr(li, "quantity", 1))
            # try 'unit_price' first, fallback to 'price'
            unit_price = getattr(li, "unit_price", None)
            if unit_price is None:
                unit_price = getattr(li, "price", "0")
            total += qty * Decimal(unit_price)
        return total

    def recompute_totals(self):
        """
        Refresh items_subtotal, shipping_amount (optional logic from method),
        and grand total.
        """
        self.items_subtotal = self._calc_items_subtotal()
        if self.shipping_method:
            # comment this out if you want the manually-entered shipping_amount to stay as-is
            self.shipping_amount = self.shipping_method.effective_price(self.items_subtotal)
        self.total = self.items_subtotal + self.shipping_amount
        self.save(update_fields=["items_subtotal", "shipping_amount", "total"])


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



