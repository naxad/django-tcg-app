from django.shortcuts import render
from django.utils import timezone

from .models import CarouselItem

from django.utils import timezone
from .models import CarouselItem

def home_view(request):
    carousel_items = CarouselItem.objects.filter(is_active=True).order_by('order')
    return render(request, 'home/home.html', {
        'now': timezone.now(),
        'carousel_items': carousel_items
    })
