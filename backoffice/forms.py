# backoffice/forms.py
from django import forms
from orders.models import Order
from decimal import Decimal

class OrderShippingForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["shipping_method", "shipping_amount"]
        widgets = {
            "shipping_method": forms.Select(attrs={"class": "form-select"}),
            "shipping_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


    def clean_shipping_amount(self):
            amt = self.cleaned_data.get("shipping_amount") or Decimal("0")
            if amt < 0:
                raise forms.ValidationError("Shipping cannot be negative.")
            return amt
    

    def save(self, commit=True):
        order = super().save(commit=False)
        # if method changed but amount not edited, suggest the method price
        if "shipping_method" in self.changed_data and "shipping_amount" not in self.changed_data:
            if order.shipping_method:
                order.shipping_amount = order.shipping_method.effective_price(order.items_subtotal)
        order.recompute_totals()
        return order
