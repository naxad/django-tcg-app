# accounts/views.py
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from .forms import RegistrationForm, EmailAuthenticationForm


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()  # saved with is_active=False
            _send_activation_email(request, user)
            return redirect("accounts:verification_sent")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})

# add at top if not present
from django.urls import reverse

from django.urls import reverse

from django.urls import reverse  # keep or remove; not used after this change


def _send_activation_email(request, user):
    uid   = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    # Build the link (hard path avoids the earlier reverse issues)
    path = f"/accounts/activate/{uid}/{token}/"
    activate_url = request.build_absolute_uri(path)

    subject = "Activate your account"
    context = {"user": user, "activate_url": activate_url}
    text_body = render_to_string("accounts/email_activation.txt", context)
    html_body = render_to_string("accounts/email_activation.html", context)

    # Send using the same mechanism your other emails likely use
    sent = send_mail(
        subject,
        text_body,
        settings.DEFAULT_FROM_EMAIL,  # e.g., your Gmail address
        [user.email],
        fail_silently=False,          # surface errors immediately
        html_message=html_body,
    )

def verification_sent(request):
    return render(request, "accounts/verification_sent.html")


def activate(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except Exception:
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        messages.success(request, "Your email has been verified. You can now log in.")
        return redirect("accounts:login")
    else:
        messages.error(request, "Activation link is invalid or has expired.")
        return render(request, "accounts/activation_invalid.html")


def login_view(request):
    # use our email-based login form; inactive users will be blocked by Django
    if request.method == "POST":
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not user.is_active:
                messages.error(request, "Please verify your email before logging in.")
                return redirect("accounts:verification_sent")
            login(request, user)
            return redirect("home:home")
        else:
            # AuthenticationForm already adds non_field_errors; we add a generic message too
            messages.error(request, "Incorrect email or password.")
    else:
        form = EmailAuthenticationForm()
    return render(request, "accounts/login.html", {"form": form})
