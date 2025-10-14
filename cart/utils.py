# cart/utils.py
from typing import Dict
from django.contrib import messages
from browse.models import Card

def get_cart(session) -> Dict[str, dict]:
    cart = session.get("cart")
    if not isinstance(cart, dict):
        cart = {}
        session["cart"] = cart
    return cart

def sync_cart_with_stock(request) -> None:
    """
    Ensure cart never contains qty > stock or OOS items.
    Mutates the session cart in-place and saves the session.
    """
    cart = get_cart(request.session)
    if not cart:
        return

    # Fetch all involved cards at once
    ids = [int(cid) for cid in cart.keys() if cid.isdigit()]
    if not ids:
        return

    stock_map = {c.id: c.quantity for c in Card.objects.filter(id__in=ids).only("id", "quantity")}
    removed = []
    reduced = []

    for cid_str, line in list(cart.items()):
        try:
            cid = int(cid_str)
        except ValueError:
            removed.append(cid_str)
            cart.pop(cid_str, None)
            continue

        wanted = int(line.get("qty", 0) or 0)
        available = int(stock_map.get(cid, 0))

        # Item missing or OOS → remove
        if available <= 0:
            removed.append(cid_str)
            cart.pop(cid_str, None)
            continue

        # Cap to available
        if wanted > available:
            reduced.append((cid_str, wanted, available))
            line["qty"] = available

        # If qty ended up 0, drop it
        if line["qty"] <= 0:
            removed.append(cid_str)
            cart.pop(cid_str, None)

    request.session.modified = True

    # Friendly messages
    if removed:
        messages.warning(request, "Some items in your cart are no longer available and were removed.")
    if reduced:
        messages.info(request, "We reduced some quantities to match current stock.")
