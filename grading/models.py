

# Create your models here.
from __future__ import annotations
from django.conf import settings
from django.db import models

class GradeRequest(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    card_name = models.CharField(max_length=120, blank=True)

    front_image = models.ImageField(upload_to="grading/%Y/%m/%d/")
    back_image  = models.ImageField(upload_to="grading/%Y/%m/%d/", blank=True, null=True)

    # Per-category 0–10 (one decimal place) + overall predicted PSA 1–10
    score_centering = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    score_surface   = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    score_edges     = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    score_corners   = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    score_color     = models.DecimalField(max_digits=4, decimal_places=1, default=0)

    predicted_grade = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    predicted_label = models.CharField(max_length=20, blank=True)  # e.g. "PSA 9 (Mint)"

    explanation_md  = models.TextField(blank=True)  # nice human summary (markdown OK)
    needs_better_photos = models.BooleanField(default=False)
    photo_feedback  = models.CharField(max_length=300, blank=True)

    raw_json = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        who = self.user.username if self.user else "guest"
        return f"GradeRequest #{self.pk} by {who} – PSA~{self.predicted_grade}"
