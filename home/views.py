from django.shortcuts import render
from django.utils import timezone

def home_view(request):
    return render(request, 'home/home.html', {'now': timezone.now()})
