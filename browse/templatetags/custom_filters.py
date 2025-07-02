from django import template

register = template.Library()

@register.filter
def average_rating(ratings):
    if not ratings:
        return 0
    total = sum([r.score for r in ratings])
    return round(total / len(ratings), 1)
