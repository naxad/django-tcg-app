# wishlist/views.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import WishlistItem
from browse.models import Card

@login_required
def wishlist_view(request):
    wishlist = WishlistItem.objects.filter(user=request.user)
    return render(request, 'wishlist/wishlist.html', {'wishlist': wishlist})

@login_required
def add_to_wishlist(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    WishlistItem.objects.get_or_create(user=request.user, card=card)
    return redirect('wishlist')

@login_required
def remove_from_wishlist(request, card_id):
    WishlistItem.objects.filter(user=request.user, card__id=card_id).delete()
    return redirect('wishlist')


from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from browse.models import Card
from .models import WishlistItem

@login_required
def toggle_wishlist(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    wishlist_item, created = WishlistItem.objects.get_or_create(user=request.user, card=card)

    if not created:
        # It already exists, so remove it
        wishlist_item.delete()

    return redirect('browse')  # Adjust if needed to redirect to current page
