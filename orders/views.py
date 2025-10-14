# orders/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from decimal import Decimal

from .models import Order, ShippingMethod
from .forms import ShippingChoiceForm

@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return render(request, 'orders/order_detail.html', {'order': order})

@login_required
def checkout_shipping(request):
    order = get_object_or_404(Order, user=request.user, status="pending")

    if request.method == "POST":
        form = ShippingChoiceForm(request.POST)
        if form.is_valid():
            method = form.cleaned_data["method"]
            order.shipping_method = method
            order.recompute_totals()
            messages.success(request, "Shipping method saved.")
            # NOTE: Adjust the redirect to your real payment-step URL name if needed.
            return redirect("checkout:payment")
    else:
        form = ShippingChoiceForm(
            initial={"method": order.shipping_method_id} if order.shipping_method_id else None
        )

    items_subtotal = order._calc_items_subtotal()
    methods = [
        {"obj": m, "effective": m.effective_price(items_subtotal)}
        for m in ShippingMethod.objects.filter(is_active=True)
    ]

    return render(request, "orders/checkout_shipping.html", {
        "order": order,
        "form": form,
        "methods": methods,
        "items_subtotal": items_subtotal,
    })
