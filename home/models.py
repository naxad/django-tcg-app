from django.db import models
from django.urls import reverse

class CarouselItem(models.Model):
    title = models.CharField(max_length=100)
    subtitle = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to='carousel/')
    card = models.ForeignKey('browse.Card', on_delete=models.CASCADE, related_name='carousel_items')  # Link to your Card model
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('card_detail', args=[self.card.pk])


class HomepageBanner(models.Model):
    title = models.CharField(max_length=100)
    subtitle = models.CharField(max_length=200, blank=True)
    image = models.ImageField(upload_to='homepage_banners/')
    button_text = models.CharField(max_length=30, default="Shop Now")
    button_link = models.URLField(blank=True, help_text="Link for the call-to-action button")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return self.title
