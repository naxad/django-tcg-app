# accounts/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string

class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=True, label="First name")
    last_name  = forms.CharField(max_length=30, required=True, label="Last name")
    email      = forms.EmailField(max_length=254, required=True, label="Email")

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data.get("email").lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        # Auto-generate a unique username from email (since default User requires it)
        email = self.cleaned_data["email"].lower()
        base = email.split("@")[0][:20] or "user"
        candidate = base
        # ensure uniqueness
        i = 0
        while User.objects.filter(username=candidate).exists():
            i += 1
            candidate = f"{base}{i}"
        user.username = candidate
        user.email = email
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        # block login until email is confirmed
        user.is_active = False
        if commit:
            user.save()
        return user


class EmailAuthenticationForm(AuthenticationForm):
    """
    Login with email + password, but still authenticates against the user's username internally.
    """
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True}))

    def clean(self):
        # Map email to the real username before AuthenticationForm does its checks
        email = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if email and password:
            try:
                user = User.objects.get(email__iexact=email)
                self.cleaned_data["username"] = user.username  # swap in username
            except User.DoesNotExist:
                # keep username as email so default error flows
                pass
        return super().clean()
