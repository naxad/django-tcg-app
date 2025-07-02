from django.db import models
from django.contrib.auth.models import User
from browse.models import Card

# Create your models here.
class Rating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    card = models.ForeignKey(Card, on_delete=models.CASCADE)
    score = models.IntegerField()  # 1 to 5

    class Meta:
        unique_together = ('user', 'card')  # prevent duplicate ratings

    def __str__(self):
        return f'{self.user.username} rated {self.card.name} - {self.score}★'