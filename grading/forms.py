from django import forms
from .models import GradeRequest
import re

_PTCD_RE = re.compile(r"^[A-Z0-9]{2,6}$")          # e.g. SVI, PAR, EVS, SM12
_NUM_RE  = re.compile(r"^[0-9]{1,3}(/\d{1,3})?$")  # e.g. 45 or 161/236

class GradingForm(forms.ModelForm):
    # NEW (not stored on the model, just used/validated here)
    ptcgo_code = forms.CharField(
        required=True, max_length=10,
        widget=forms.TextInput(attrs={"class":"form-control", "placeholder":"Set code (e.g. SVI, PAR, EVS, SM12)"}))
    collector_number = forms.CharField(
        required=True, max_length=20,
        widget=forms.TextInput(attrs={"class":"form-control", "placeholder":"Collector no. (e.g. 161/236 or 045)"}))

    class Meta:
        model = GradeRequest
        fields = ["card_name", "front_image", "back_image"]  # model-backed fields only
        widgets = {
            "card_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Card name (optional)"}),
        }

    def clean_ptcgo_code(self):
        code = (self.cleaned_data["ptcgo_code"] or "").strip().upper()
        if not _PTCD_RE.match(code):
            raise forms.ValidationError("Use a short set code like SVI, PAR, EVS, SM12.")
        return code

    def clean_collector_number(self):
        num = (self.cleaned_data["collector_number"] or "").strip()
        if not _NUM_RE.match(num):
            raise forms.ValidationError("Use formats like 45 or 161/236.")
        return num

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
    if f.size > 12 * 1024 * 1024:
        raise forms.ValidationError("Image too large (max 12MB).")
    if getattr(f, "content_type", "").lower() not in {"image/jpeg","image/jpg","image/png","image/webp"}:
        raise forms.ValidationError("Please upload JPEG/PNG/WEBP images.")