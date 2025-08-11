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




class AddressForm(forms.ModelForm):
    set_as_default = forms.BooleanField(required=False, initial=True, label="Make default")

    class Meta:
        model = Address
        fields = ["full_name", "phone", "line1", "line2", "city", "state", "postal_code", "country", "set_as_default"]