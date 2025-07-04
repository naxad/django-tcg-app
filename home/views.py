from django.shortcuts import render
from django.utils import timezone

from .models import CarouselItem
from browse.models import Card

from django.utils import timezone
from .models import CarouselItem
from .models import HomepageBanner


def home_view(request):
    carousel_items = CarouselItem.objects.filter(is_active=True).order_by('order')
    featured_items = Card.objects.filter(is_featured=True)[:5]
    banners = HomepageBanner.objects.filter(is_active=True).order_by('order')
    return render(request, 'home/home.html', {
        'now': timezone.now(),
        'carousel_items': carousel_items,
        'featured_items': featured_items,
        'banners': banners,
    })
