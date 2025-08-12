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
from django.utils import timezone
import stripe
import requests
from userprofile.models import Address
from django.views.decorators.http import require_http_methods

Decimal = decimal.Decimal

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
PP_CLIENT = os.environ.get("PAYPAL_CLIENT_ID")
PP_SECRET = os.environ.get("PAYPAL_SECRET")
PP_ENV  = os.environ.get("PAYPAL_ENV", "sandbox")
PP_BASE = "https://api-m.sandbox.paypal.com" if PP_ENV == "sandbox" else "https://api-m.paypal.com"

MIN_ORDER_TOTAL = Decimal("0.50")  # Stripe minimum in EUR

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
@require_http_methods(["GET", "POST"])
def checkout(request):
    # --- Guard: empty cart / minimum total ---
    cart_items = CartItem.objects.filter(user=request.user)
    if not cart_items.exists():
        messages.warning(request, "Your cart is empty.")
        return redirect('cart:cart')

    cart_total = sum(ci.card.price * ci.quantity for ci in cart_items)
    if cart_total < MIN_ORDER_TOTAL:
        messages.error(request, "Minimum order is €0.50.")
        return redirect('cart:cart')
    # ----------------------------------------

    order = _create_or_refresh_order_from_cart(request)
    if not order:
        messages.warning(request, "Your cart is empty.")
        return redirect('cart:cart')

    request.session['current_order_id'] = order.id
    addresses = Address.objects.filter(user=request.user)

    shipping_ready = bool(order.shipping_line1)

    if request.method == "POST":
        # case 1: use a saved address
        addr_id = request.POST.get("address_id")
        if addr_id:
            addr = get_object_or_404(Address, id=addr_id, user=request.user)
            _apply_address_to_order(order, addr)
            shipping_ready = True
            messages.success(request, "Shipping address selected.")
        else:
            messages.error(request, "Please select an address.")

    return render(request, 'cart/checkout.html', {
        "order": order,
        "addresses": addresses,
        "shipping_ready": shipping_ready,
        "PAYPAL_CLIENT_ID": os.environ.get("PAYPAL_CLIENT_ID","")
    })


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


def _create_or_refresh_order_from_cart(request):
    cart_items = CartItem.objects.filter(user=request.user)
    if not cart_items.exists():
        return None

    email = request.user.email
    order = (Order.objects
             .filter(user=request.user, status="pending")
             .order_by("-created_at")
             .first())
    if not order:
        order = Order.objects.create(user=request.user, email=email, currency="EUR",
                                     status="pending", total=Decimal("0.00"))

    # rebuild items to exactly mirror cart
    order.items.all().delete()
    total = Decimal("0.00")
    for ci in cart_items:
        OrderItem.objects.create(order=order, card=ci.card, name=ci.card.name,
                                 unit_price=ci.card.price, quantity=ci.quantity)
        total += ci.card.price * ci.quantity
    order.total = total
    order.save(update_fields=["total"])
    return order


@require_POST
@login_required
def stripe_checkout(request):
    order_id = request.session.get("current_order_id")
    if not order_id:
        return JsonResponse({"error": "no_order"}, status=400)

    order = get_object_or_404(Order, id=order_id, user=request.user, status="pending")

    # Guard: require shipping snapshot
    if not all([
        order.shipping_name,
        order.shipping_line1,
        order.shipping_city,
        order.shipping_postal_code,
        order.shipping_country,
    ]):
        return JsonResponse({"error": "shipping_missing", "message": "Please select a shipping address first."}, status=400)

    # Guard: minimum total
    if order.total < MIN_ORDER_TOTAL:
        return JsonResponse({"error": "min_total", "message": "Minimum order is €0.50."}, status=400)

    if not order.items.exists() or order.total <= 0:
        return JsonResponse({"error": "empty_order"}, status=400)

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
        success_url=request.build_absolute_uri("/cart/thank-you/?session_id={CHECKOUT_SESSION_ID}"),
        cancel_url=request.build_absolute_uri("/cart/cart/"),
        customer_email=order.email or None,
        metadata={"order_id": str(order.id)},
    )
    order.gateway = "stripe"
    order.gateway_id = session.id
    order.save(update_fields=["gateway", "gateway_id"])
    return JsonResponse({"url": session.url})


@login_required
def thank_you(request):
    order_id   = request.session.get("current_order_id")
    session_id = request.GET.get("session_id")
    if order_id and session_id:
        try:
            order = Order.objects.get(id=order_id, user=request.user)
            if order.status != "paid":
                sess = stripe.checkout.Session.retrieve(session_id)
                if sess.get("payment_status") == "paid":
                    order.status = "paid"
                    order.paid_at = timezone.now()
                    order.gateway = "stripe"
                    order.gateway_id = sess["id"]
                    order.save(update_fields=["status","paid_at","gateway","gateway_id"])
                    Payment.objects.create(
                        order=order,
                        gateway="stripe",
                        gateway_ref=sess.get("payment_intent",""),
                        amount=order.total,
                        raw=sess
                    )
                    _finalize_order_to_purchases(order)
        except Exception:
            pass
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
        _finalize_order_to_purchases(order)
    return HttpResponse(status=200)


def _pp_token():
    r = requests.post(f"{PP_BASE}/v1/oauth2/token", auth=(PP_CLIENT, PP_SECRET), data={"grant_type":"client_credentials"})
    r.raise_for_status()
    return r.json()["access_token"]

@require_POST
@login_required
def paypal_create(request):
    order_id = request.session.get("current_order_id")
    if not order_id:
        order = _create_or_refresh_order_from_cart(request)
        if not order:
            return JsonResponse({"error":"empty"}, status=400)
        request.session['current_order_id'] = order.id
    else:
        order = get_object_or_404(Order, id=order_id, user=request.user, status="pending")

    # Guard: require shipping snapshot
    if not all([
        order.shipping_name,
        order.shipping_line1,
        order.shipping_city,
        order.shipping_postal_code,
        order.shipping_country,
    ]):
        return JsonResponse(
            {"error": "shipping_missing", "message": "Please select a shipping address first."},
            status=400
        )

    # Guard: minimum total
    if order.total < MIN_ORDER_TOTAL:
        return JsonResponse({"error":"min_total", "message":"Minimum order is €0.50."}, status=400)

    access = _pp_token()
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {"currency_code": order.currency, "value": str(order.total)},
            "custom_id": str(order.id)
        }]
    }
    r = requests.post(f"{PP_BASE}/v2/checkout/orders",
                      headers={"Authorization": f"Bearer {access}", "Content-Type":"application/json"},
                      json=body)
    r.raise_for_status()
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
    if data.get("status") == "COMPLETED":
        custom_id = None
        try:
            custom_id = data["purchase_units"][0]["payments"]["captures"][0]["custom_id"]
        except KeyError:
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


def _apply_address_to_order(order, addr: Address):
    order.shipping_address = addr
    order.shipping_name = addr.full_name
    order.shipping_phone = addr.phone
    order.shipping_line1 = addr.line1
    order.shipping_line2 = addr.line2
    order.shipping_city = addr.city
    order.shipping_state = addr.state
    order.shipping_postal_code = addr.postal_code
    order.shipping_country = addr.country
    order.save(update_fields=[
        "shipping_address","shipping_name","shipping_phone","shipping_line1","shipping_line2",
        "shipping_city","shipping_state","shipping_postal_code","shipping_country"
    ])
