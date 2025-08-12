from django.shortcuts import render

# Create your views here.
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.utils import timezone
from django.db.models import Q
import csv

from orders.models import Order

def _filtered_orders(request):
    qs = Order.objects.select_related("user").order_by("-created_at")
    q  = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    fulfill = request.GET.get("fulfillment", "")
    gateway = request.GET.get("gateway", "")
    paid = request.GET.get("paid", "")  # yes/no

    if q:
        qs = qs.filter(
            Q(id__icontains=q) |
            Q(email__icontains=q) |
            Q(user__username__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if fulfill:
        qs = qs.filter(fulfillment_status=fulfill)
    if gateway:
        qs = qs.filter(gateway=gateway)
    if paid == "yes":
        qs = qs.filter(status="paid")
    elif paid == "no":
        qs = qs.exclude(status="paid")

    return qs

@staff_member_required
def orders_list(request):
    qs = _filtered_orders(request)
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page"))

    ctx = {
        "page": page,
        "statuses": Order.STATUS_CHOICES,
        "fulfill_choices": getattr(Order, "FULFILL_CHOICES", []),
        "current": request.GET,
    }
    return render(request, "backoffice/orders_list.html", ctx)

@staff_member_required
def orders_export_csv(request):
    qs = _filtered_orders(request)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="orders.csv"'
    w = csv.writer(resp)
    w.writerow(["ID","Created","Email","Total","Currency","Status","Fulfillment","Gateway","Paid at","Shipped at","Tracking","Carrier"])
    for o in qs:
        w.writerow([
            o.id, o.created_at, o.email, o.total, o.currency, o.status,
            getattr(o, "fulfillment_status", ""), o.gateway, o.paid_at,
            getattr(o, "shipped_at", ""), getattr(o, "tracking_number", ""), getattr(o, "carrier", "")
        ])
    return resp

@staff_member_required
def order_detail(request, order_id):
    o = get_object_or_404(Order.objects.select_related("user"), id=order_id)

    if request.method == "POST":
        # update fulfillment data
        if "save_fulfillment" in request.POST:
            if hasattr(o, "fulfillment_status"):
                o.fulfillment_status = request.POST.get("fulfillment_status", o.fulfillment_status)
            if hasattr(o, "tracking_number"):
                o.tracking_number = request.POST.get("tracking_number", o.tracking_number)
            if hasattr(o, "carrier"):
                o.carrier = request.POST.get("carrier", o.carrier)
            if hasattr(o, "admin_note"):
                o.admin_note = request.POST.get("admin_note", o.admin_note)
            o.save()
            return redirect("backoffice:order_detail", order_id=o.id)

        if "mark_shipped" in request.POST and hasattr(o, "shipped_at"):
            o.fulfillment_status = "shipped" if hasattr(o, "fulfillment_status") else o.status
            o.shipped_at = timezone.now()
            o.save(update_fields=["fulfillment_status","shipped_at"] if hasattr(o, "fulfillment_status") else ["shipped_at"])
            return redirect("backoffice:order_detail", order_id=o.id)

    return render(request, "backoffice/order_detail.html", {"o": o})


# backoffice/views.py
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from orders.models import Order
from .forms import OrderShippingForm

@staff_member_required
def order_shipping_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == "POST":
        form = OrderShippingForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            # IMPORTANT: refresh items_subtotal, shipping_amount (if method computes it), and total
            order.recompute_totals()
            messages.success(request, "Shipping updated.")
            return redirect("backoffice:order_detail", order_id=order.pk)
    else:
        form = OrderShippingForm(instance=order)

    return render(request, "backoffice/order_shipping_edit.html", {"order": order, "form": form})

