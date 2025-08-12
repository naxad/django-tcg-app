from django.shortcuts import render
from browse.models import Card
from cart.models import Purchase
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse

from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth import update_session_auth_hash
from django.views.decorators.http import require_POST
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
from .forms import UserUpdateForm, UserProfileForm, AddressForm   # NEW
from .models import UserProfile, Address 
from orders.models import Order
from django.urls import reverse

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

    if request.method == "POST":
        # Save basic user/profile fields
        if "profile_submit" in request.POST:
            user_form = UserUpdateForm(request.POST, instance=user)
            profile_form = UserProfileForm(request.POST, instance=profile)
            addr_form = AddressForm()  # blank for re-render

            if user_form.is_valid() and profile_form.is_valid():
                user_form.save()
                profile_form.save()
                messages.success(request, "Profile updated successfully!")
                return redirect(reverse("profile") + "#tab-profile")

        # Add address
        elif request.method == "POST" and request.POST.get("address_submit"):
            user_form = UserUpdateForm(instance=user)
            profile_form = UserProfileForm(instance=profile)
            addr_form = AddressForm(request.POST)
            if addr_form.is_valid():
                addr_form.save(user=request.user)  # <- pass owner to form's save() test change 
                messages.success(request, "Address saved.")
                return redirect("profile")

    else:
        user_form = UserUpdateForm(instance=user)
        profile_form = UserProfileForm(instance=profile)
        addr_form = AddressForm()

    # ----- Read-only dashboard data -----
    ratings = Rating.objects.filter(user=user).select_related("card")

    wishlist_items = (
        WishlistItem.objects.filter(user=user)
        .select_related("card")
    )
    wishlist_cards = [w.card for w in wishlist_items]

    viewed_ids = request.session.get("recently_viewed", [])
    viewed_qs = Card.objects.filter(id__in=viewed_ids)
    viewed_cards = sorted(viewed_qs, key=lambda c: viewed_ids.index(c.id)) if viewed_ids else []

    purchases = Purchase.objects.filter(user=user).order_by("-purchased_at")
    recent_orders = Order.objects.filter(user=user).order_by("-created_at")[:5]
    lifetime_spend = (
        Order.objects.filter(user=user, status="paid").aggregate(total=Sum("total")).get("total")
        or Decimal("0.00")
    )

    addresses = Address.objects.filter(user=user).order_by("-is_default", "-id")

    context = {
        "form": user_form,
        "profile_form": profile_form,
        "addr_form": addr_form,
        "addresses": addresses,
        "ratings": ratings,
        "wishlist": wishlist_cards,
        "viewed_cards": viewed_cards,
        "purchases": purchases,
        "recent_orders": recent_orders,
        "lifetime_spend": lifetime_spend,
    }
    return render(request, "userprofile/profile.html", context)



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



@require_POST
@login_required
def address_set_default(request, pk):
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    Address.objects.filter(user=request.user).update(is_default=False)
    addr.is_default = True
    addr.save(update_fields=["is_default"])
    messages.success(request, "Default address updated.")
    return redirect('profile')  # profile tab shows addresses

@require_POST
@login_required
def address_delete(request, pk):
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    addr.delete()
    messages.success(request, "Address deleted.")
    return redirect('profile')


@require_POST
@login_required
def address_set_default(request, pk):
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    Address.objects.filter(user=request.user).update(is_default=False)
    addr.is_default = True
    addr.save(update_fields=["is_default"])
    messages.success(request, "Default address updated.")
    return redirect(reverse("profile") + "#tab-profile")





@require_POST
@login_required
def address_delete(request, pk):
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    addr.delete()
    messages.success(request, "Address deleted.")
    return redirect(reverse("profile") + "#tab-profile")