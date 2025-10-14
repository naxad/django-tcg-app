# cart/forms.py
from django import forms
from userprofile.models import Address
from orders.models import ShippingRate

class ShippingAddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ["full_name","phone","line1","line2","city","state","postal_code","country"]
        widgets = {
            "full_name":   forms.TextInput(attrs={"class":"form-control"}),
            "phone":       forms.TextInput(attrs={"class":"form-control"}),
            "line1":       forms.TextInput(attrs={"class":"form-control"}),
            "line2":       forms.TextInput(attrs={"class":"form-control"}),
            "city":        forms.TextInput(attrs={"class":"form-control"}),
            "state":       forms.TextInput(attrs={"class":"form-control"}),
            "postal_code": forms.TextInput(attrs={"class":"form-control"}),
            "country":     forms.TextInput(attrs={"class":"form-control", "placeholder":"2-letter code e.g. DE"}),
        }

class ShippingOptionForm(forms.Form):
    shipping_method = forms.ChoiceField(widget=forms.RadioSelect)

    def __init__(self, *args, country_code: str = "", currency: str = "EUR", **kwargs):
        super().__init__(*args, **kwargs)
        qs = (ShippingRate.objects
              .select_related("method")
              .filter(method__is_active=True, country=(country_code or "").upper())
              .order_by("method__name"))
        choices = [
            (str(rate.method.id), f"{rate.method.name} — {currency} {rate.price}")
            for rate in qs
        ]
        self.fields["shipping_method"].choices = choices
