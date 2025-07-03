from django.shortcuts import render, redirect, get_object_or_404
from .models import CartItem
from browse.models import Card
from cart.models import Purchase
from django.contrib.auth.decorators import login_required
from django.contrib import messages

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
    cart_items = CartItem.objects.filter(user=request.user)

    if not cart_items:
        messages.warning(request, "Your cart is empty.")
        return redirect('cart:cart')

    for item in cart_items:
        for _ in range(item.quantity):
            Purchase.objects.create(user=request.user, card=item.card)

    cart_items.delete()  # Clear the cart after checkout

    return render(request, 'cart/thank_you.html')



def remove_from_cart(request, card_id):
    cart = request.session.get('cart', [])
    if card_id in cart:
        cart.remove(card_id)
        request.session['cart'] = cart
    return redirect('cart:cart')

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
    return redirect('cart')