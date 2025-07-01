from django.shortcuts import render
from .models import Card
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse
from .forms import UserUpdateForm
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth import update_session_auth_hash

from .forms import UserUpdateForm

from .models import Rating
from django.shortcuts import get_object_or_404

from django.contrib import messages


from django.shortcuts import render
from .models import Card


def home(request):
    return render(request, 'shop/home.html')

def browse(request):
    return render(request, 'shop/browse.html')

def contact(request):
    return render(request, 'shop/contact.html')

def sell(request):
    return render(request, 'shop/sell.html')

def browse(request):
    query = request.GET.get('q')
    brand = request.GET.get('brand')

    cards = Card.objects.all()

    if query:
        cards = cards.filter(name__icontains=query)

    if brand:
        cards = cards.filter(brand=brand)

    return render(request, 'shop/browse.html', {'cards': cards})


def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'shop/register.html', {'form': form})

@login_required
def profile(request):
    return render(request, 'shop/profile.html')

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


def browse(request):
    cards = Card.objects.all()

    q = request.GET.get("q")
    brand = request.GET.get("brand")
    max_price = request.GET.get("max_price")

    if q:
        cards = cards.filter(name__icontains=q)

    if brand:
        cards = cards.filter(brand=brand)

    if max_price:
        try:
            cards = cards.filter(price__lte=float(max_price))
        except ValueError:
            pass

    # get unique brands for the filter dropdown
    brands = Card.objects.values_list('brand', flat=True).distinct()

    return render(request, "shop/browse.html", {
        "cards": cards,
        "brands": brands,
    })


def card_detail(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    return render(request, 'shop/card_detail.html', {'card': card})

def add_to_cart(request, card_id):
    card = get_object_or_404(Card, id=card_id)
    cart = request.session.get('cart', {})
    cart[str(card.id)] = cart.get(str(card.id), 0) + 1

    request.session['cart'] = cart

    messages.success(request, f"{card.name} added to your cart.")
    return redirect(request.META.get('HTTP_REFERER', 'browse'))


@login_required
def view_cart(request):
    cart = request.session.get('cart', {})
    cart_items = []
    total_price = 0

    for card_id, quantity in cart.items():
        card = Card.objects.get(id=card_id)
        item_total = card.price * quantity
        total_price += item_total
        cart_items.append({
            'card': card,
            'quantity': quantity,
            'item_total': item_total,
        })

    return render(request, 'shop/cart.html', {
        'cart_items': cart_items,
        'total_price': total_price,
    })

@login_required
def profile_view(request):
    user = request.user
    if request.method == 'POST':
        form = UserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            return redirect('profile')
    else:
        form = UserUpdateForm(instance=user)

    # example activity data (will customize the models later)
    ratings = Rating.objects.filter(user=user).select_related('card')[:5]  # last 5 ratings
    wishlist = user.profile.wishlist.all()[:5] if hasattr(user, 'profile') and hasattr(user.profile, 'wishlist') else []
    viewed_cards = user.profile.viewed_cards.all()[:5] if hasattr(user, 'profile') and hasattr(user.profile, 'viewed_cards') else []

    return render(request, 'shop/profile.html', {
        'form': form,
        'ratings': ratings,
        'wishlist': wishlist,
        'viewed_cards': viewed_cards,
    })


@login_required
def edit_profile(request):
    if request.method == 'POST':
        form = UserUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect('profile')
    else:
        form = UserUpdateForm(instance=request.user)

    return render(request, 'shop/edit_profile.html', {'form': form})


@login_required
def user_dashboard(request):
    user = request.user

    # fetch ratings the user has given
    user_ratings = Rating.objects.filter(user=user).select_related('card')

    # placeholder for future features
    recently_viewed = request.session.get('recently_viewed', [])[:5]
    recently_viewed_cards = Card.objects.filter(id__in=recently_viewed)

    # later i need to add purchases and wishlist
    context = {
        'user_ratings': user_ratings,
        'recently_viewed_cards': recently_viewed_cards,
    }
    return render(request, 'shop/dashboard.html', context)