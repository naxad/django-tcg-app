from django.shortcuts import render, redirect
from .forms import CardSubmissionForm
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required




# Create your views here.
def sell(request):
    return redirect('submit_card')  # Previously: render(request, 'sell/sell.html')




def submit_card(request):
    if request.method == 'POST':
        form = CardSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Your card has been submitted! Our team will review it shortly.")
            return redirect('sell:thank_you')
    else:
        form = CardSubmissionForm()
    return render(request, 'sell/submit_card.html', {'form': form})

def thank_you(request):
    return render(request, 'sell/thank_you.html')
