from django.db import models
from django.contrib.auth.models import User
from browse.models import Card

# Create your models here.


class RecentlyViewed(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    card = models.ForeignKey(Card, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} viewed {self.card.name}"
