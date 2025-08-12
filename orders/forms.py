# orders/forms.py
from django import forms
from .models import ShippingMethod

class ShippingChoiceForm(forms.Form):
    method = forms.ModelChoiceField(
        queryset=ShippingMethod.objects.filter(is_active=True),
        widget=forms.RadioSelect,
        empty_label=None,
        label="Shipping"
    )
