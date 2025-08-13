from django import forms
from .models import GradeRequest

class GradingForm(forms.ModelForm):
    class Meta:
        model = GradeRequest
        fields = ["card_name", "front_image", "back_image"]
        widgets = {
            "card_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Card name (optional)"}),
        }

    def clean_front_image(self):
        img = self.cleaned_data["front_image"]
        _validate_image(img)
        return img

    def clean_back_image(self):
        img = self.cleaned_data.get("back_image")
        if img:
            _validate_image(img)
        return img

def _validate_image(f):
    # 12 MB size guard and basic content type check
    if f.size > 12 * 1024 * 1024:
        raise forms.ValidationError("Image too large (max 12MB).")
    if getattr(f, "content_type", "").lower() not in {"image/jpeg","image/jpg","image/png","image/webp"}:
        raise forms.ValidationError("Please upload JPEG/PNG/WEBP images.")
