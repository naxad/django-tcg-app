from django.shortcuts import render
from .models import Card
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse


from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth import update_session_auth_hash



from userprofile.models import Rating
from django.shortcuts import get_object_or_404



from django.shortcuts import render
from .models import Card
from wishlist.models import WishlistItem






@login_required
def browse(request):
    query = request.GET.get('q')
    brand = request.GET.get('brand')
    max_price = request.GET.get('max_price')
    sort = request.GET.get('sort')

    cards = Card.objects.all()

    if query:
        cards = cards.filter(name__icontains=query)
    if brand:
        cards = cards.filter(brand=brand)
    if max_price:
        try:
            cards = cards.filter(price__lte=float(max_price))
        except ValueError:
            pass

    # Sorting logic
    if sort == "price_asc":
        cards = cards.order_by("price")
    elif sort == "price_desc":
        cards = cards.order_by("-price")
    elif sort == "rating_desc":
        cards = sorted(cards, key=lambda c: c.average_rating() or 0, reverse=True)
    elif sort == "newest":
        cards = cards.order_by("-id")

    brands = Card.objects.values_list('brand', flat=True).distinct()

    wishlist_cards = []
    if request.user.is_authenticated:
        wishlist_cards = Card.objects.filter(wishlisted_by__user=request.user)

    show_popup = None
    if 'cart_added' in request.session:
        show_popup = request.session.pop('cart_added')  # Remove after showing once


    return render(request, 'browse/browse.html', {
        'cards': cards,
        'brands': brands,
        'wishlist_cards': wishlist_cards,
        'current_sort': sort,
        'show_popup': show_popup,
    })





@login_required
def rate_card(request):
    if request.method == 'POST':
        card_id = request.POST.get('card_id')
        score = request.POST.get('score')

        try:
            card = Card.objects.get(id=card_id)
            rating, created = Rating.objects.update_or_create(
                user=request.user,
                card=card,
                defaults={'score': score}
            )
            return JsonResponse({'success': True})
        except Card.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Card not found'})

    return JsonResponse({'success': False, 'error': 'Invalid request'})




def card_detail(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    is_in_wishlist = False

    # Check if the card is in the user's wishlist
    if request.user.is_authenticated:
        is_in_wishlist = WishlistItem.objects.filter(user=request.user, card=card).exists()

    # --- Track Recently Viewed Cards ---
    recently_viewed = request.session.get('recently_viewed', [])

    if card.id in recently_viewed:
        recently_viewed.remove(card.id)  # Move to front if already there
    recently_viewed.insert(0, card.id)   # Add current card to the front

    # Limit to last 5 viewed
    request.session['recently_viewed'] = recently_viewed[:5]
    # -----------------------------------

    show_popup = None
    if 'cart_added' in request.session:
        show_popup = request.session.pop('cart_added')

    return render(request, 'browse/card_detail.html', {
        'card': card,
        'is_in_wishlist': is_in_wishlist,
        'show_popup': show_popup,
    })





