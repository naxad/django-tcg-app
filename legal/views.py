from django.shortcuts import render

# legal/views.py
from django.shortcuts import render

def privacy(request):
    return render(request, "legal/privacy.html")

def terms(request):
    return render(request, "legal/terms.html")

def about(request):
    return render(request, "legal/about.html")
