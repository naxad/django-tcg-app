from django.shortcuts import render
from .models import Card
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Rating, Card

# Create your views here.
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

    # Get unique brands for the filter dropdown
    brands = Card.objects.values_list('brand', flat=True).distinct()

    return render(request, "shop/browse.html", {
        "cards": cards,
        "brands": brands,
    })