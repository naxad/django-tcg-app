from django.db import models
from django.contrib.auth.models import User

class CardSubmission(models.Model):
    CONDITION_CHOICES = [
        ('mint', 'Mint'),
        ('nm', 'Near Mint'),
        ('lp', 'Lightly Played'),
        ('mp', 'Moderately Played'),
        ('hp', 'Heavily Played'),
        ('damaged', 'Damaged'),
    ]

    seller_name = models.CharField(max_length=100)
    email = models.EmailField()
    card_name = models.CharField(max_length=200)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES)
    comment = models.TextField(blank=True)
    image_front = models.ImageField(upload_to='card_submissions/')
    image_back = models.ImageField(upload_to='card_submissions/', blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.card_name} by {self.seller_name}"
