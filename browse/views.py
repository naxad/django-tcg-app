from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .models import Card
from wishlist.models import WishlistItem

from django.contrib.admin.views.decorators import staff_member_required

# Browse cards with filtering, sorting, and rating calculation
def browse(request):
    query = request.GET.get('q')
    brand = request.GET.get('brand')
    max_price = request.GET.get('max_price')
    sort = request.GET.get('sort')

    cards = Card.objects.all()

    if not request.user.is_staff:
        cards = cards.filter(quantity__gt=0)
    if query:
        cards = cards.filter(name__icontains=query)
    if brand:
        cards = cards.filter(brand=brand)
    if max_price:
        try:
            cards = cards.filter(price__lte=float(max_price))
        except ValueError:
            pass

    # Sorting
    if sort == "price_asc":
        cards = cards.order_by("price")
    elif sort == "price_desc":
        cards = cards.order_by("-price")
    elif sort == "newest":
        cards = cards.order_by("-id")

    # Get brands for filter
    brands = Card.objects.values_list('brand', flat=True).distinct()

    # Wishlist cards for the user
    wishlist_cards = []
    if request.user.is_authenticated:
        wishlist_cards = Card.objects.filter(wishlisted_by__user=request.user)

    # Toast message
    show_popup = None
    if 'cart_added' in request.session:
        show_popup = request.session.pop('cart_added')


    return render(request, 'browse/browse.html', {
        'cards': cards,
        'brands': brands,
        'wishlist_cards': wishlist_cards,
        'current_sort': sort,
        'show_popup': show_popup,
        'user_is_staff': request.user.is_staff,
        
    })




from django.contrib.auth.decorators import user_passes_test

@user_passes_test(lambda u: u.is_staff)
def add_card(request):
    if request.method == "POST":
        name = request.POST.get("name")
        brand = request.POST.get("brand")
        condition = request.POST.get("condition")
        release_date = request.POST.get("release_date")
        price = request.POST.get("price")
        image = request.FILES.get("image")
        quantity_raw = request.POST.get("quantity", "0")
        set_name = request.POST.get("set_name", "").strip()
        try:
            quantity = max(0, int(quantity_raw))
        except ValueError:
            quantity = 0

        Card.objects.create(
            name=name,
            brand=brand,
            condition=condition,
            
            price=price,
            image=image,
            quantity=quantity,
            set_name=set_name,
        )
    return redirect("browse:browse")







@staff_member_required
def delete_card(request, card_id):
    if request.method == "POST":
        card = get_object_or_404(Card, id=card_id)
        card.delete()
        return redirect('browse:browse')






# Card detail view with wishlist and recently viewed tracking
def card_detail(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    # Check if it's in the wishlist
    is_in_wishlist = False
    if request.user.is_authenticated:
        is_in_wishlist = WishlistItem.objects.filter(user=request.user, card=card).exists()

    # Track recently viewed
    recently_viewed = request.session.get('recently_viewed', [])
    if card.id in recently_viewed:
        recently_viewed.remove(card.id)
    recently_viewed.insert(0, card.id)
    request.session['recently_viewed'] = recently_viewed[:5]

    # Toast message
    show_popup = None
    if 'cart_added' in request.session:
        show_popup = request.session.pop('cart_added')



    return render(request, 'browse/card_detail.html', {
        'card': card,
        'is_in_wishlist': is_in_wishlist,
        'show_popup': show_popup,
    })
