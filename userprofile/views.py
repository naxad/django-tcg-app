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



# Create your views here.


@login_required
def profile(request):
    return render(request, 'userprofile/profile.html')


from .forms import UserUpdateForm, UserProfileForm

from userprofile.models import UserProfile

@login_required
def profile_view(request):
    user = request.user

    # ✅ Ensure user has a profile or create one if not
    profile, created = UserProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        user_form = UserUpdateForm(request.POST, instance=user)
        profile_form = UserProfileForm(request.POST, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')
    else:
        user_form = UserUpdateForm(instance=user)
        profile_form = UserProfileForm(instance=profile)

    ratings = Rating.objects.filter(user=user)
    wishlist_items = WishlistItem.objects.filter(user=user)
    wishlist_cards = [item.card for item in wishlist_items]
    viewed_ids = request.session.get('recently_viewed', [])
    viewed_cards = list(Card.objects.filter(id__in=viewed_ids))
    viewed_cards.sort(key=lambda card: viewed_ids.index(card.id))
    purchases = Purchase.objects.filter(user=user).order_by('-purchased_at')

    context = {
        'form': user_form,
        'profile_form': profile_form,
        'ratings': ratings,
        'wishlist': wishlist_cards,
        'viewed_cards': viewed_cards,
        'purchases': purchases,
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
