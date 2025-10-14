from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal

from browse.models import Card


# -------------------------------
# Shipping setup
# -------------------------------
class ShippingMethod(models.Model):
    code = models.SlugField(max_length=32, unique=True)          # e.g. "standard", "express"
    name = models.CharField(max_length=80)                       # e.g. "Standard (Tracked)"
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=10)

    # (optional global fallback)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    free_over = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    eta = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def effective_price(self, items_subtotal: Decimal) -> Decimal:
        if self.free_over is not None and items_subtotal >= self.free_over:
            return Decimal("0.00")
        return self.price

    def __str__(self):
        return self.name


class ShippingRate(models.Model):
    method  = models.ForeignKey(ShippingMethod, on_delete=models.CASCADE, related_name="rates")
    country = models.CharField(max_length=2)  # ISO alpha-2, e.g. "DE", "FR", "US"
    price   = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = ("method", "country")

    def __str__(self):
        return f"{self.method.name} → {self.country}: {self.price}"


# -------------------------------
# Orders / Items / Payments
# -------------------------------
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

    # --- pricing pieces ---
    shipping_method = models.ForeignKey(ShippingMethod, null=True, blank=True, on_delete=models.SET_NULL)
    shipping_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    items_subtotal  = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    shipping_method_code = models.SlugField(max_length=32, blank=True)      # "standard", "express"
    shipping_method_name = models.CharField(max_length=64, blank=True)      # human label snapshot
    shipping_price = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))

    # --- stock accounting guard ---
    stock_debited = models.BooleanField(default=False)  # NEW: prevents double-decrement

    def __str__(self):
        return f"Order #{self.id} - {self.status}"

    def mark_paid(self):
        self.status = "paid"
        self.paid_at = timezone.now()
        self.save(update_fields=["status", "paid_at"])

    def mark_shipped(self):
        self.fulfillment_status = "shipped"
        self.shipped_at = timezone.now()
        self.save(update_fields=["fulfillment_status", "shipped_at"])

    # ------ items subtotal helpers ------
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
            line_total = getattr(li, "total", None)
            if line_total is not None:
                total += Decimal(line_total)
                continue
            qty = Decimal(getattr(li, "quantity", 1))
            unit_price = getattr(li, "unit_price", None)
            if unit_price is None:
                unit_price = getattr(li, "price", "0")
            total += qty * Decimal(unit_price)
        return total

    def recompute_totals(self):
        self.items_subtotal = self._calc_items_subtotal()
        if self.shipping_method:
            self.shipping_amount = self._effective_shipping_amount()
        self.total = self.items_subtotal + self.shipping_amount
        self.save(update_fields=["items_subtotal", "shipping_amount", "total"])

    def _shipping_base_for_country(self) -> Decimal:
        if not self.shipping_method or not self.shipping_country:
            return Decimal("0.00")
        rate = self.shipping_method.rates.filter(country=(self.shipping_country or "").upper()).first()
        return Decimal(rate.price) if rate else Decimal(self.shipping_method.price)

    def _effective_shipping_amount(self) -> Decimal:
        base = self._shipping_base_for_country()
        free_over = self.shipping_method.free_over if self.shipping_method else None
        if free_over is not None and self.items_subtotal >= free_over:
            return Decimal("0.00")
        return base

    @property
    def grand_total(self):
        return (self.total or Decimal("0.00")) + (self.shipping_price or Decimal("0.00"))


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
    """
    Creating a Payment row is treated as a successful charge/capture.
    The stock decrement logic is hooked on post_save(created=True).
    """
    order = models.OneToOneField(Order, related_name="payment", on_delete=models.CASCADE)
    gateway = models.CharField(max_length=20)                  # 'stripe' or 'paypal'
    gateway_ref = models.CharField(max_length=255)             # intent/capture id
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    raw = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.gateway} {self.amount} for Order #{self.order_id}"


# -------------------------------
# Stock decrement on successful payment
# -------------------------------
@receiver(post_save, sender=Payment)
def reduce_stock_on_success(sender, instance: Payment, created, **kwargs):
    """
    When a Payment is created, decrement stock for each OrderItem.
    Guards with order.stock_debited to avoid double-debit.
    Uses select_for_update + F() for atomicity.
    """
    if not created:
        return

    order = instance.order

    # Already debited? bail out (prevents double decrement if duplicate signals)
    if order.stock_debited:
        return

    with transaction.atomic():
        items = order.items.select_related("card").select_for_update()
        for it in items:
            # Ensure Card has a 'quantity' field
            if not hasattr(it.card, "quantity"):
                raise AttributeError("Card model must have a 'quantity' field for stock control.")

            # Atomic decrement only if enough stock
            updated = Card.objects.filter(
                id=it.card_id,
                quantity__gte=it.quantity
            ).update(quantity=F("quantity") - it.quantity)

            if not updated:
                # Not enough stock; raise to signal a serious issue
                # (You could alternatively set order.status='failed' and alert staff)
                raise ValueError(f"Insufficient stock for '{it.card.name}' (requested {it.quantity}).")

        # Mark debited & paid if not already paid
        order.stock_debited = True
        if order.status != "paid":
            order.status = "paid"
            order.paid_at = timezone.now()
            order.save(update_fields=["stock_debited", "status", "paid_at"])
        else:
            order.save(update_fields=["stock_debited"])
