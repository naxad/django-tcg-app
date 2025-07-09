from django.db import models
from django.contrib.auth.models import User
from browse.models import Card
from django.dispatch import receiver
from django.db.models.signals import post_save


# Create your models here.
class Rating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE,  related_name='ratings')
    card = models.ForeignKey(Card, on_delete=models.CASCADE,  related_name='ratings')
    score = models.IntegerField()  # 1 to 5
    address = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ('user', 'card')  # prevent duplicate ratings

    def __str__(self):
        return f'{self.user.username} rated {self.card.name} - {self.score}★'
    

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    address = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"
    

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()