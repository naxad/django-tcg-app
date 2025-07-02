from django.db import models
from django.contrib.auth.models import User
from browse.models import Card

class CartItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    card = models.ForeignKey(Card, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.quantity} x {self.card.name} for {self.user.username}"
    


class Purchase(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    card = models.ForeignKey(Card, on_delete=models.CASCADE)
    purchased_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} bought {self.card.name}"
