from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from .models import Order

@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return render(request, 'orders/order_detail.html', {'order': order})
