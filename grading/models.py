

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



# grading/models.py
from django.db import models
from django.conf import settings

class GradedCard(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    card_name = models.CharField(max_length=255, blank=True)

    # Image paths
    front_image = models.ImageField(upload_to="graded_cards/front/")
    back_image = models.ImageField(upload_to="graded_cards/back/")

    # AI-predicted scores
    score_centering = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    score_surface   = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    score_edges     = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    score_corners   = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    score_color     = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)

    predicted_grade = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    predicted_label = models.CharField(max_length=100, blank=True)
    issues          = models.JSONField(default=list, blank=True)
    needs_better_photos = models.BooleanField(default=False)
    photo_feedback  = models.TextField(blank=True)
    summary         = models.TextField(blank=True)

    # Manual override
    human_verified_grade = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.card_name or 'Unnamed Card'} - {self.predicted_label or 'Ungraded'}"
