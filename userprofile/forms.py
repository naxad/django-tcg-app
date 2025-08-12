from django import forms
from django.contrib.auth.models import User
from .models import UserProfile
from .models import Address


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['address']
        widgets = {
            'address': forms.TextInput(attrs={'class': 'form-control'}),
        }



# forms.py
from django import forms
from .models import Address


class AddressForm(forms.ModelForm):
    set_as_default = forms.BooleanField(required=False, initial=True, label="Make default")

    class Meta:
        model = Address
        fields = ["full_name", "phone", "line1", "line2", "city", "state", "postal_code", "country", "set_as_default"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # placeholders
        placeholders = {
            "full_name": "Full name",
            "phone": "+1 555 123 4567",
            "line1": "Street, number",
            "line2": "Apt, suite, etc.",
            "city": "City",
            "state": "State",
            "postal_code": "Postal code",
            "country": "Country",
        }

        for name, field in self.fields.items():
            if name == "set_as_default":
                field.widget.attrs.setdefault("class", "form-check-input")
            elif name == "country":
                field.widget.attrs.setdefault("class", "form-select")
                field.widget.attrs.setdefault("placeholder", placeholders.get(name, ""))
            else:
                field.widget.attrs.setdefault("class", "form-control")
                field.widget.attrs.setdefault("placeholder", placeholders.get(name, ""))

    def save(self, user=None, commit=True):
        """Keep the 'default address' logic here."""
        addr = super().save(commit=False)
        if user is not None:
            addr.user = user
        if commit:
            addr.save()
            if self.cleaned_data.get("set_as_default"):
                Address.objects.filter(user=addr.user).exclude(id=addr.id).update(is_default=False)
                addr.is_default = True
                addr.save(update_fields=["is_default"])
        return addr