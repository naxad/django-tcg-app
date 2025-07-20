from django.shortcuts import render, redirect
from .forms import CardSubmissionForm
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required




# Create your views here.
def sell(request):
    return redirect('sell:submit_card')  # previously: render(request, 'sell/sell.html')




def submit_card(request):
    if request.method == 'POST':
        form = CardSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "🎉 Your card has been submitted! Our team will review it shortly.")
            form = CardSubmissionForm()  # Clear the form after successful submission
    else:
        form = CardSubmissionForm()
    return render(request, 'sell/submit_card.html', {'form': form})

