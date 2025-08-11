from django.shortcuts import render
from browse.models import Card
from cart.models import Purchase
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse

from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth import update_session_auth_hash

from .forms import UserUpdateForm

from userprofile.models import Rating
from django.shortcuts import get_object_or_404

from django.contrib import messages
from django.db.models import Avg

from django.shortcuts import render
from browse.models import Card
from wishlist.models import WishlistItem
from django.db.models import Sum
from decimal import Decimal

from orders.models import Order

# Create your views here.


@login_required
def profile(request):
    return render(request, 'userprofile/profile.html')


from .forms import UserUpdateForm, UserProfileForm

from userprofile.models import UserProfile

@login_required
def profile_view(request):
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        user_form = UserUpdateForm(request.POST, instance=user)
        profile_form = UserProfileForm(request.POST, instance=profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')  # make sure your URL name points to this view
    else:
        user_form = UserUpdateForm(instance=user)
        profile_form = UserProfileForm(instance=profile)

    # Existing sections
    ratings = Rating.objects.filter(user=user).select_related('card')
    wishlist_items = WishlistItem.objects.filter(user=user).select_related('card')
    wishlist_cards = [w.card for w in wishlist_items]

    viewed_ids = request.session.get('recently_viewed', [])
    viewed_qs = Card.objects.filter(id__in=viewed_ids)
    viewed_cards = sorted(viewed_qs, key=lambda c: viewed_ids.index(c.id)) if viewed_ids else []

    purchases = Purchase.objects.filter(user=user).order_by('-purchased_at')

    # NEW: orders + lifetime spend
    recent_orders = Order.objects.filter(user=user).order_by('-created_at')[:5]
    lifetime_spend = (
        Order.objects.filter(user=request.user, status='paid')
        .aggregate(total=Sum('total'))
        .get('total') or Decimal('0.00')
    )

    context = {
        'form': user_form,
        'profile_form': profile_form,
        'ratings': ratings,
        'wishlist': wishlist_cards,
        'viewed_cards': viewed_cards,
        'purchases': purchases,
        'recent_orders': recent_orders,
        'lifetime_spend': lifetime_spend,
    }
    return render(request, 'userprofile/profile.html', context)



@login_required
def edit_profile(request):
    if request.method == 'POST':
        form = UserUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect('profile')
    else:
        form = UserUpdateForm(instance=request.user)

    return render(request, 'userprofile/edit_profile.html', {'form': form})



@login_required
def profile_dashboard_view(request):
    user = request.user

    # Recently viewed logic (session-based for now)
    recently_viewed_ids = request.session.get('recently_viewed', [])[-5:]
    recently_viewed_cards = Card.objects.filter(id__in=recently_viewed_ids)

    user_ratings = Rating.objects.filter(user=user)

    context = {
        'user': user,
        'recently_viewed_cards': recently_viewed_cards,
        'user_ratings': user_ratings,
        # Add more context like purchases later
    }

    return render(request, 'userprofile/profile_dashboard.html', context)
