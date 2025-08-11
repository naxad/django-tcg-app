from django.shortcuts import render, redirect, get_object_or_404
from .models import CartItem
from browse.models import Card
from cart.models import Purchase
from django.contrib.auth.decorators import login_required
from django.contrib import messages

import os, json, decimal
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.conf import settings
from .models import CartItem, Purchase
from orders.models import Order, OrderItem, Payment
from browse.models import Card
from datetime import timedelta, timezone
import stripe
import requests

Decimal = decimal.Decimal

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
PP_CLIENT = os.environ.get("PAYPAL_CLIENT_ID")
PP_SECRET = os.environ.get("PAYPAL_SECRET")
PP_BASE = "https://api-m.paypal.com"  # use https://api-m.sandbox.paypal.com for sandbox

@login_required
def add_to_cart(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    item, created = CartItem.objects.get_or_create(user=request.user, card=card)

    if not created:
        item.quantity += 1
        item.save()

    # Set session flag to show popup
    request.session['cart_added'] = card.name

    return redirect(request.META.get('HTTP_REFERER', 'browse:card_detail'))


@login_required
def view_cart(request):
    cart_items = CartItem.objects.filter(user=request.user)
    total_price = sum(item.card.price * item.quantity for item in cart_items)

    show_popup = request.session.pop('cart_added', False)

    return render(request, 'cart/cart.html', {
        'cart_items': cart_items,
        'total_price': total_price,
        'show_popup': show_popup
    })

@login_required
def remove_from_cart(request, card_id):
    item = CartItem.objects.filter(user=request.user, card_id=card_id).first()
    if item:
        item.delete()
        messages.success(request, "Item removed from cart.")
    else:
        messages.warning(request, "Item not found in your cart.")
    return redirect('cart:cart')

@login_required
def checkout(request):
    # Build/refresh a pending order snapshot from the cart (idempotent per click)
    order = _create_order_from_cart(request)
    if not order:
        messages.warning(request, "Your cart is empty.")
        return redirect('cart:cart')

    # show summary page with Pay buttons
    return render(request, 'cart/checkout.html', {"order": order})




@login_required
def update_cart_quantity(request, card_id):
    if request.method == 'POST':
        action = request.POST.get('action')
        item = CartItem.objects.filter(user=request.user, card_id=card_id).first()

        if item:
            if action == 'increase':
                item.quantity += 1
                item.save()
            elif action == 'decrease':
                item.quantity -= 1
                if item.quantity <= 0:
                    item.delete()
                else:
                    item.save()
    return redirect('cart:cart')



def _create_order_from_cart(request):
    cart_items = CartItem.objects.filter(user=request.user)
    if not cart_items.exists():
        return None

    email = request.user.email if request.user.is_authenticated else request.POST.get("email","")
    currency = "EUR"

    order = Order.objects.create(
        user=request.user if request.user.is_authenticated else None,
        email=email,
        currency=currency,
        status="pending",
        total=Decimal("0.00"),
    )

    total = Decimal("0.00")
    for ci in cart_items:
        OrderItem.objects.create(
            order=order,
            card=ci.card,
            name=ci.card.name,
            unit_price=ci.card.price,
            quantity=ci.quantity
        )
        total += (ci.card.price * ci.quantity)

    order.total = total
    order.save(update_fields=["total"])
    return order


@require_POST
@login_required
def stripe_checkout(request):
    order = _create_order_from_cart(request)
    if not order:
        return JsonResponse({"error": "empty"}, status=400)

    line_items = [{
        "price_data": {
            "currency": order.currency.lower(),
            "unit_amount": int(it.unit_price * 100),
            "product_data": {"name": it.name},
        },
        "quantity": it.quantity,
    } for it in order.items.all()]

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        success_url=request.build_absolute_uri("/cart/thank-you/"),
        cancel_url=request.build_absolute_uri("/cart/cart/"),
        customer_email=order.email or None,
        metadata={"order_id": str(order.id)},
    )
    order.gateway = "stripe"
    order.gateway_id = session.id
    order.save(update_fields=["gateway","gateway_id"])
    return JsonResponse({"url": session.url})




@login_required
def thank_you(request):
    return render(request, 'cart/thank_you.html')



def _finalize_order_to_purchases(order: Order):
    # create Purchase rows for history
    for it in order.items.all():
        for _ in range(it.quantity):
            Purchase.objects.create(user=order.user, card=it.card)
    # clear the user's cart
    if order.user:
        CartItem.objects.filter(user=order.user).delete()


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig = request.META.get("HTTP_STRIPE_SIGNATURE")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        sess = event["data"]["object"]
        order_id = sess["metadata"]["order_id"]
        order = Order.objects.get(id=order_id)
        order.status = "paid"
        order.paid_at = timezone.now()
        order.save(update_fields=["status","paid_at"])
        Payment.objects.create(
            order=order,
            gateway="stripe",
            gateway_ref=sess.get("payment_intent",""),
            amount=order.total,
            raw=event
        )
        # materialize Purchases, clear cart
        _finalize_order_to_purchases(order)
    return HttpResponse(status=200)


def _pp_token():
    r = requests.post(f"{PP_BASE}/v1/oauth2/token", auth=(PP_CLIENT, PP_SECRET), data={"grant_type":"client_credentials"})
    r.raise_for_status()
    return r.json()["access_token"]

@require_POST
@login_required
def paypal_create(request):
    order = _create_order_from_cart(request)
    if not order:
        return JsonResponse({"error":"empty"}, status=400)
    access = _pp_token()
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {"currency_code": order.currency, "value": str(order.total)},
            "custom_id": str(order.id)
        }]
    }
    r = requests.post(f"{PP_BASE}/v2/checkout/orders", headers={"Authorization": f"Bearer {access}", "Content-Type":"application/json"}, json=body)
    data = r.json()
    order.gateway = "paypal"
    order.gateway_id = data["id"]
    order.save(update_fields=["gateway","gateway_id"])
    return JsonResponse({"id": data["id"]})

@require_POST
@login_required
def paypal_capture(request, order_id):
    access = _pp_token()
    r = requests.post(f"{PP_BASE}/v2/checkout/orders/{order_id}/capture", headers={"Authorization": f"Bearer {access}"})
    data = r.json()
    # Verify
    if data.get("status") == "COMPLETED":
        # Pull our order id
        custom_id = None
        try:
            custom_id = data["purchase_units"][0]["payments"]["captures"][0]["custom_id"]
        except KeyError:
            # older field path; fall back to order.gateway_id
            pass
        order = Order.objects.get(id=int(custom_id)) if custom_id else Order.objects.get(gateway_id=order_id)
        order.status = "paid"
        order.paid_at = timezone.now()
        order.save(update_fields=["status","paid_at"])
        Payment.objects.create(
            order=order,
            gateway="paypal",
            gateway_ref=data["id"],
            amount=order.total,
            raw=data
        )
        _finalize_order_to_purchases(order)
        return JsonResponse({"ok": True})
    return HttpResponseBadRequest("Not completed")