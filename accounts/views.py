from django.shortcuts import render
from django.shortcuts import render

from django.contrib.auth.forms import UserCreationForm

from django.shortcuts import render, redirect





from django.shortcuts import render, redirect
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse_lazy
from django.shortcuts import render
from django.contrib.auth import login


# Create your views here.
def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request,user)
            return redirect('home:home')
    else:
        form = UserCreationForm()
    return render(request, 'accounts/register.html', {'form': form})