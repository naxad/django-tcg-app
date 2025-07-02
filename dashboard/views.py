
from django.shortcuts import render
from browse.models import Card
from userprofile.models import Rating

def dashboard_view(request):
    user = request.user
    recently_viewed_cards = []
    recently_viewed_ids = request.session.get('recently_viewed', [])

    if recently_viewed_ids:
        # fetch cards in the order they appear in the list
        cards = Card.objects.filter(id__in=recently_viewed_ids)
        recently_viewed_cards = sorted(cards, key=lambda c: recently_viewed_ids.index(c.id))

    user_ratings = Rating.objects.filter(user=user) #to see every rating a users has given

    context = {
        'recently_viewed_cards': recently_viewed_cards,
        'user_ratings': user_ratings,
    }

    return render(request, 'dashboard/dashboard.html', context)
