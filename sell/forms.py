from django import forms
from .models import CardSubmission
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

class CardSubmissionForm(forms.ModelForm):
    class Meta:
        model = CardSubmission
        fields = ['seller_name', 'email', 'card_name', 'condition', 'comment', 'image_front', 'image_back']
        widgets = {
            'seller_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Maria'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'example@email.com'}),
            'card_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Charizard'}),
            'condition': forms.Select(attrs={'class': 'form-select'}),
            'comment': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Any additional info…'}),
            'image_front': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'image_back': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        try:
            validate_email(email)
        except ValidationError:
            raise forms.ValidationError("Please enter a valid email address.")
        return email
