from django import forms
from .models import CardSubmission

class CardSubmissionForm(forms.ModelForm):
    class Meta:
        model = CardSubmission
        fields = ['seller_name', 'email', 'card_name', 'condition', 'comment', 'image_front', 'image_back']
        widgets = {
            'comment': forms.Textarea(attrs={'rows': 4}),
        }
