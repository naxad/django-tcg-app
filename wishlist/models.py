from django.db import models
from django.contrib.auth.models import User

from browse.models import Card

# Create your models here.
class WishlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="wishlist_items")
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="wishlisted_by")
    added_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} wishlisted {self.card.name}"