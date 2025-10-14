# cart/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.db.models import F

import os
import json
import decimal
import stripe
import requests

from browse.models import Card
from userprofile.models import Address
from .models import CartItem, Purchase
from .forms import ShippingAddressForm, ShippingOptionForm
from orders.models import Order, OrderItem, Payment, ShippingMethod, ShippingRate
from orders.emails import send_order_emails
from decimal import Decimal, ROUND_HALF_UP

# ----- VAT (Greece 24%) -----
VAT_RATE = Decimal("0.24")

def _money(x: Decimal) -> Decimal:
    """Round to 2dp, HALF_UP."""
    return (x or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _calc_vat(items_subtotal: Decimal, shipping_price: Decimal) -> Decimal:
    """VAT on items + shipping."""
    taxable = (items_subtotal or Decimal("0.00")) + (shipping_price or Decimal("0.00"))
    return _money(taxable * VAT_RATE)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
PP_CLIENT = os.environ.get("PAYPAL_CLIENT_ID")
PP_SECRET = os.environ.get("PAYPAL_SECRET")
PP_ENV  = os.environ.get("PAYPAL_ENV", "sandbox")
PP_BASE = "https://api-m.sandbox.paypal.com" if PP_ENV == "sandbox" else "https://api-m.paypal.com"

MIN_ORDER_TOTAL = Decimal("15")  # items-only minimum


# -----------------------
# Cart <-> Stock sync helpers (DB-backed cart)
# -----------------------
def _sync_db_cart(request):
    items = list(CartItem.objects.select_related("card").filter(user=request.user))
    if not items:
        return

    removed = 0
    reduced = 0

    for it in items:
        card = it.card
        if not card or card.quantity <= 0:
            it.delete()
            removed += 1
            continue

        if it.quantity > card.quantity:
            it.quantity = card.quantity
            it.save(update_fields=["quantity"])
            reduced += 1

        if it.quantity <= 0:
            it.delete()
            removed += 1

    if removed:
        messages.warning(request, "Some items were removed from your cart because they are out of stock.")
    if reduced:
        messages.info(request, "We reduced some quantities in your cart to match current stock.")


def _decrement_stock_and_clear_cart(order: Order):
    for li in order.items.select_related("card").all():
        updated = Card.objects.filter(
            id=li.card_id,
            quantity__gte=li.quantity
        ).update(quantity=F("quantity") - li.quantity)

        if updated == 0:
            card = Card.objects.filter(id=li.card_id).first()
            if card and card.quantity < 0:
                card.quantity = 0
                card.save(update_fields=["quantity"])

    if order.user_id:
        CartItem.objects.filter(user=order.user).delete()


# -----------------------
# Cart basics
# -----------------------
@login_required
def add_to_cart(request, card_id):
    _sync_db_cart(request)

    card = get_object_or_404(Card, id=card_id)
    if card.quantity <= 0:
        messages.error(request, "This item is out of stock.")
        return redirect(request.META.get('HTTP_REFERER', 'browse:card_detail'))

    item, created = CartItem.objects.get_or_create(user=request.user, card=card, defaults={"quantity": 0})
    desired = (item.quantity or 0) + 1
    new_qty = min(desired, card.quantity)
    if new_qty <= 0:
        messages.error(request, "This item is out of stock.")
        return redirect(request.META.get('HTTP_REFERER', 'browse:card_detail'))

    item.quantity = new_qty
    item.save(update_fields=["quantity"])

    request.session['cart_added'] = card.name
    return redirect(request.META.get('HTTP_REFERER', 'browse:card_detail'))


@login_required
def view_cart(request):
    _sync_db_cart(request)
    cart_items = CartItem.objects.select_related("card").filter(user=request.user)
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
def update_cart_quantity(request, card_id):
    if request.method == 'POST':
        _sync_db_cart(request)

        action = request.POST.get('action')
        item = CartItem.objects.select_related("card").filter(user=request.user, card_id=card_id).first()
        if not item:
            return redirect('cart:cart')

        card = item.card
        if not card or card.quantity <= 0:
            item.delete()
            messages.warning(request, "This item is out of stock and was removed.")
            return redirect('cart:cart')

        if action == 'increase':
            item.quantity = min(item.quantity + 1, card.quantity)
            item.save(update_fields=["quantity"])
            if item.quantity == card.quantity:
                messages.info(request, "You’ve reached the maximum available stock for this item.")
        elif action == 'decrease':
            item.quantity -= 1
            if item.quantity <= 0:
                item.delete()
            else:
                item.save(update_fields=["quantity"])
    return redirect('cart:cart')


# -----------------------
# Order building helpers
# -----------------------
def _calc_items_subtotal_for(request_user):
    cart_items = CartItem.objects.select_related("card").filter(user=request_user)
    return sum(ci.card.price * ci.quantity for ci in cart_items) or Decimal("0.00")


def _create_or_refresh_order_from_cart(request):
    _sync_db_cart(request)

    cart_items = CartItem.objects.select_related("card").filter(user=request.user)
    if not cart_items.exists():
        return None

    email = request.user.email
    order = (
        Order.objects
        .filter(user=request.user, status="pending")
        .order_by("-created_at")
        .first()
    )
    if not order:
        order = Order.objects.create(
            user=request.user,
            email=email,
            currency="EUR",
            status="pending",
            total=Decimal("0.00"),
        )

    order.items.all().delete()
    for ci in cart_items:
        OrderItem.objects.create(
            order=order,
            card=ci.card,
            name=ci.card.name,
            unit_price=_money(ci.card.price),
            quantity=ci.quantity,
        )

    order.items_subtotal = order._calc_items_subtotal()
    order.total = order.items_subtotal  # items only (shipping separate)
    order.save(update_fields=["items_subtotal", "total"])
    return order


# -----------------------
# Shipping helpers
# -----------------------
def _available_shipping_choices(order):
    if not order.shipping_country:
        return []
    rates = (
        ShippingRate.objects
        .select_related("method")
        .filter(method__is_active=True, country=(order.shipping_country or "").upper())
        .order_by("method__name")
    )
    return [(str(r.method.id), f"{r.method.name} — {order.currency} {r.price}") for r in rates]


def _apply_shipping_selection(order, method_id: str) -> bool:
    if not (order and order.shipping_country and method_id):
        return False

    rate = (
        ShippingRate.objects
        .select_related("method")
        .filter(
            method__is_active=True,
            method__id=int(method_id),
            country=(order.shipping_country or "").upper()
        )
        .first()
    )
    if not rate:
        return False

    order.shipping_method = rate.method
    order.shipping_method_code = str(rate.method.id)
    order.shipping_method_name = rate.method.name
    order.shipping_price = _money(rate.price)

    order.items_subtotal = order._calc_items_subtotal()
    order.total = order.items_subtotal
    order.save(update_fields=[
        "shipping_method", "shipping_method_code", "shipping_method_name",
        "shipping_price", "items_subtotal", "total"
    ])
    return True


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
    if not order.email and order.user and order.user.email:
        order.email = order.user.email
        order.save(update_fields=["email"])


# -----------------------
# Checkout
# -----------------------
@login_required
@require_http_methods(["GET", "POST"])
def checkout(request):
    _sync_db_cart(request)

    cart_items = CartItem.objects.select_related("card").filter(user=request.user)
    if not cart_items.exists():
        messages.warning(request, "Your cart is empty.")
        return redirect('cart:cart')

    items_subtotal = _calc_items_subtotal_for(request.user)
    if items_subtotal < MIN_ORDER_TOTAL:
        messages.error(request, "Minimum order is €15.")
        return redirect('cart:cart')

    order = _create_or_refresh_order_from_cart(request)
    if not order:
        messages.warning(request, "Your cart is empty.")
        return redirect('cart:cart')

    request.session['current_order_id'] = order.id
    addresses = Address.objects.filter(user=request.user)
    addr_form = None
    ship_form = None

    has_address = bool(order.shipping_line1)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "use_saved_address":
            addr_id = request.POST.get("address_id")
            if addr_id:
                addr = get_object_or_404(Address, id=addr_id, user=request.user)
                _apply_address_to_order(order, addr)
                has_address = True
                order.shipping_method = None
                order.shipping_method_code = ""
                order.shipping_method_name = ""
                order.shipping_price = Decimal("0.00")
                order.save(update_fields=["shipping_method","shipping_method_code","shipping_method_name","shipping_price"])
                messages.success(request, "Shipping address selected.")
            else:
                messages.error(request, "Please select an address.")

        elif action == "new_address":
            addr_form = ShippingAddressForm(request.POST)
            save_to_profile = bool(request.POST.get("save_address") == "1")
            if addr_form.is_valid():
                addr_obj = addr_form.save(commit=False)
                addr_obj.user = request.user
                if save_to_profile:
                    addr_obj.save()
                _apply_address_to_order(order, addr_obj)
                has_address = True
                order.shipping_method = None
                order.shipping_method_code = ""
                order.shipping_method_name = ""
                order.shipping_price = Decimal("0.00")
                order.save(update_fields=["shipping_method","shipping_method_code","shipping_method_name","shipping_price"])
                messages.success(request, "Shipping address added.")
            else:
                messages.error(request, "Please fix the address errors below.")

        elif action == "choose_shipping":
            if not has_address:
                messages.error(request, "Select an address first.")
            else:
                ship_form = ShippingOptionForm(
                    request.POST,
                    country_code=order.shipping_country,
                    currency=order.currency
                )
                if ship_form.is_valid():
                    chosen = ship_form.cleaned_data["shipping_method"]
                    if _apply_shipping_selection(order, chosen):
                        messages.success(request, "Shipping method selected.")
                    else:
                        messages.error(request, "That shipping option isn’t available for your country.")
                else:
                    messages.error(request, "Invalid shipping selection.")

    if not addr_form and not addresses.exists():
        addr_form = ShippingAddressForm()

    shipping_ready = has_address
    shipping_choices = _available_shipping_choices(order) if has_address else []
    if has_address and shipping_choices:
        ship_form = ShippingOptionForm(
            initial={"shipping_method": order.shipping_method_code or (shipping_choices[0][0] if shipping_choices else "")},
            country_code=order.shipping_country,
            currency=order.currency
        )

    # Keep monetary snapshots up to date
    order.items_subtotal = order._calc_items_subtotal()
    order.total = order.items_subtotal
    order.save(update_fields=["items_subtotal", "total"])

    vat_amount = _calc_vat(order.items_subtotal, order.shipping_price or Decimal("0.00"))
    grand_total = _money(order.items_subtotal + (order.shipping_price or Decimal("0.00")) + vat_amount)

    return render(request, 'cart/checkout.html', {
        "order": order,
        "addresses": addresses,
        "addr_form": addr_form,
        "ship_form": ship_form,
        "shipping_choices": shipping_choices,
        "shipping_ready": shipping_ready,
        "PAYPAL_CLIENT_ID": os.environ.get("PAYPAL_CLIENT_ID",""),
        "grand_total": grand_total,
        "vat_amount": vat_amount,
        "vat_rate_pct": int(VAT_RATE * 100),
    })


# -----------------------
# Stripe / PayPal
# -----------------------
@require_POST
@login_required
def stripe_checkout(request):
    order_id = request.session.get("current_order_id")
    if not order_id:
        return JsonResponse({"error": "no_order"}, status=400)
    order = get_object_or_404(Order, id=order_id, user=request.user, status="pending")

    if not order.email:
        if request.user and request.user.email:
            order.email = request.user.email
            order.save(update_fields=["email"])
        else:
            return JsonResponse(
                {"error": "email_missing", "message": "Please add an email address in your profile before paying."},
                status=400
            )

    if not all([order.shipping_name, order.shipping_line1, order.shipping_city, order.shipping_postal_code, order.shipping_country]):
        return JsonResponse({"error": "shipping_missing", "message": "Please select a shipping address first."}, status=400)

    if not order.shipping_method_code:
        return JsonResponse({"error":"shipping_option_missing","message":"Please choose a shipping method."}, status=400)

    if order.items_subtotal < MIN_ORDER_TOTAL:
        return JsonResponse({"error":"min_total","message":"Minimum order is €15."}, status=400)

    if not order.items.exists() or order.items_subtotal <= 0:
        return JsonResponse({"error":"empty_order"}, status=400)

    # Line items (items)
    line_items = [{
        "price_data": {
            "currency": order.currency.lower(),
            "unit_amount": int(_money(it.unit_price) * 100),
            "product_data": {"name": it.name},
        },
        "quantity": it.quantity,
    } for it in order.items.all()]

    # Shipping
    if order.shipping_price and order.shipping_price > 0:
        line_items.append({
            "price_data": {
                "currency": order.currency.lower(),
                "unit_amount": int(_money(order.shipping_price) * 100),
                "product_data": {"name": f"Shipping — {order.shipping_method_name or order.shipping_method_code}"},
            },
            "quantity": 1,
        })

    # VAT (items + shipping)
    vat_amount = _calc_vat(order.items_subtotal, order.shipping_price or Decimal("0.00"))
    if vat_amount > 0:
        line_items.append({
            "price_data": {
                "currency": order.currency.lower(),
                "unit_amount": int(vat_amount * 100),
                "product_data": {"name": f"VAT ({int(VAT_RATE*100)}%)"},
            },
            "quantity": 1,
        })

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
    order.save(update_fields=["gateway","gateway_id"])
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

                # Backfill email from Stripe if missing
                cust_email = None
                try:
                    cust_email = (sess.get("customer_details") or {}).get("email")
                except Exception:
                    pass
                if cust_email and not order.email:
                    order.email = cust_email
                    order.save(update_fields=["email"])

                if sess.get("payment_status") == "paid":
                    order.status = "paid"
                    order.paid_at = timezone.now()
                    order.gateway = "stripe"
                    order.gateway_id = sess["id"]
                    order.save(update_fields=["status","paid_at","gateway","gateway_id"])

                    total_with_vat = _money(
                        order.items_subtotal + (order.shipping_price or Decimal("0.00")) +
                        _calc_vat(order.items_subtotal, order.shipping_price or Decimal("0.00"))
                    )

                    Payment.objects.create(
                        order=order,
                        gateway="stripe",
                        gateway_ref=sess.get("payment_intent",""),
                        amount=total_with_vat,
                        raw=sess
                    )
                    # decrement stock & clear cart
                    _decrement_stock_and_clear_cart(order)
        except Exception:
            pass
    return render(request, 'cart/thank_you.html')


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

        cust_email = None
        try:
            cust_email = (sess.get("customer_details") or {}).get("email")
        except Exception:
            pass
        if cust_email and not order.email:
            order.email = cust_email
            order.save(update_fields=["email"])

        order.status = "paid"
        order.paid_at = timezone.now()
        order.save(update_fields=["status","paid_at"])

        total_with_vat = _money(
            order.items_subtotal + (order.shipping_price or Decimal("0.00")) +
            _calc_vat(order.items_subtotal, order.shipping_price or Decimal("0.00"))
        )

        Payment.objects.create(
            order=order,
            gateway="stripe",
            gateway_ref=sess.get("payment_intent",""),
            amount=total_with_vat,
            raw=event
        )
        _decrement_stock_and_clear_cart(order)
        if order.email:
            send_order_emails(order)
    return HttpResponse(status=200)


def _pp_token():
    r = requests.post(
        f"{PP_BASE}/v1/oauth2/token",
        auth=(PP_CLIENT, PP_SECRET),
        data={"grant_type":"client_credentials"}
    )
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

    if not order.email:
        if request.user and request.user.email:
            order.email = request.user.email
            order.save(update_fields=["email"])
        else:
            return JsonResponse(
                {"error": "email_missing", "message": "Please add an email address in your profile before paying."},
                status=400
            )

    if not all([order.shipping_name, order.shipping_line1, order.shipping_city, order.shipping_postal_code, order.shipping_country]):
        return JsonResponse({"error":"shipping_missing","message":"Please select a shipping address first."}, status=400)
    if not order.shipping_method_code:
        return JsonResponse({"error":"shipping_option_missing","message":"Please choose a shipping method."}, status=400)

    if order.items_subtotal < MIN_ORDER_TOTAL:
        return JsonResponse({"error":"min_total","message":"Minimum order is €15."}, status=400)

    access = _pp_token()

    vat_amount = _calc_vat(order.items_subtotal, order.shipping_price or Decimal("0.00"))
    grand_total = _money(order.items_subtotal + (order.shipping_price or Decimal("0.00")) + vat_amount)

    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {
                "currency_code": order.currency,
                "value": str(grand_total),
                "breakdown": {
                    "item_total": {"currency_code": order.currency, "value": str(_money(order.items_subtotal))},
                    "shipping":   {"currency_code": order.currency, "value": str(_money(order.shipping_price or Decimal('0.00')))},
                    "tax_total":  {"currency_code": order.currency, "value": str(vat_amount)},
                }
            },
            "custom_id": str(order.id),
            "items": [
                *[
                    {"name": it.name,
                     "quantity": str(it.quantity),
                     "unit_amount": {"currency_code": order.currency, "value": str(_money(it.unit_price))}}
                    for it in order.items.all()
                ]
            ]
        }]
    }
    r = requests.post(
        f"{PP_BASE}/v2/checkout/orders",
        headers={"Authorization": f"Bearer {access}", "Content-Type":"application/json"},
        json=body
    )
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
    r = requests.post(f"{PP_BASE}/v2/checkout/orders/{order_id}/capture",
                      headers={"Authorization": f"Bearer {access}"})
    data = r.json()
    if data.get("status") == "COMPLETED":
        custom_id = None
        try:
            custom_id = data["purchase_units"][0]["payments"]["captures"][0]["custom_id"]
        except KeyError:
            pass
        order = Order.objects.get(id=int(custom_id)) if custom_id else Order.objects.get(gateway_id=order_id)

        pp_email = None
        try:
            pp_email = (data.get("payer") or {}).get("email_address")
        except Exception:
            pass
        if pp_email and not order.email:
            order.email = pp_email
            order.save(update_fields=["email"])

        order.status = "paid"
        order.paid_at = timezone.now()
        order.save(update_fields=["status","paid_at"])

        total_with_vat = _money(
            order.items_subtotal + (order.shipping_price or Decimal("0.00")) +
            _calc_vat(order.items_subtotal, order.shipping_price or Decimal("0.00"))
        )

        Payment.objects.create(
            order=order,
            gateway="paypal",
            gateway_ref=data["id"],
            amount=total_with_vat,
            raw=data
        )
        _decrement_stock_and_clear_cart(order)
        if order.email:
            send_order_emails(order)
        return JsonResponse({"ok": True})
    return HttpResponseBadRequest("Not completed")


# -----------------------
# Finalization (kept, now ONLY creates Purchase records)
# -----------------------
def _finalize_order_to_purchases(order: Order):
    for it in order.items.all():
        for _ in range(it.quantity):
            Purchase.objects.create(user=order.user, card=it.card)
    # Cart clearing is handled in _decrement_stock_and_clear_cart after payment
