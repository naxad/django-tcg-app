from django.db import models
from django.contrib.auth.models import User


class Card(models.Model):
    BRAND_CHOICES = [
        ('Pokemon', 'Pokémon'),
        ('OnePiece', 'One Piece'),
        ('MTG', 'Magic: The Gathering'),
    ]

    name = models.CharField(max_length=100)
    brand = models.CharField(max_length=20, choices=BRAND_CHOICES)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='cards/', blank=True, null=True)
    rarity = models.CharField(max_length=50, blank=True)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    release_date = models.DateField(blank=True, null=True)
    condition = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"{self.name} ({self.brand})"
    

    


    



