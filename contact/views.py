from django.shortcuts import render, redirect
from .forms import ContactForm
from django.contrib import messages

# Create your views here.
def contact(request):
    return render(request, 'contact/contact.html')





def contact_view(request):
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your message has been sent!')
            return redirect('contact:contact')  # or wherever you want
    else:
        form = ContactForm()

    return render(request, 'contact/contact.html', {'form': form})
