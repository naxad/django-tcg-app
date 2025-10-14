# backoffice/views.py
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
import csv

from orders.models import Order
from orders.emails import send_shipment_email
from .forms import OrderShippingForm


# ---------- shared filtering ----------
def _filtered_orders(request):
    qs = Order.objects.select_related("user").order_by("-created_at")
    q       = request.GET.get("q", "").strip()
    status  = request.GET.get("status", "")
    fulfill = request.GET.get("fulfillment", "")
    gateway = request.GET.get("gateway", "")
    paid    = request.GET.get("paid", "")  # yes/no

    if q:
        qs = qs.filter(
            Q(id__icontains=q) |
            Q(email__icontains=q) |
            Q(user_username_icontains=q)
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


# ---------- list ----------
@staff_member_required
def orders_list(request):
    qs = _filtered_orders(request)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    ctx = {
        "page": page,
        "statuses": Order.STATUS_CHOICES,
        "fulfill_choices": getattr(Order, "FULFILL_CHOICES", []),
        "current": request.GET,
    }
    return render(request, "backoffice/orders_list.html", ctx)


# ---------- export ----------
@staff_member_required
def orders_export_csv(request):
    qs = _filtered_orders(request)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="orders.csv"'
    w = csv.writer(resp)
    w.writerow(["ID","Created","Email","Total","Currency","Status","Fulfillment",
                "Gateway","Paid at","Shipped at","Tracking","Carrier"])
    for o in qs:
        w.writerow([
            o.id, o.created_at, o.email, o.total, o.currency, o.status,
            getattr(o, "fulfillment_status", ""), o.gateway, o.paid_at,
            getattr(o, "shipped_at", ""), getattr(o, "tracking_number", ""),
            getattr(o, "carrier", "")
        ])
    return resp


# ---------- edit shipping snapshot ----------
@staff_member_required
def order_shipping_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == "POST":
        form = OrderShippingForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            # keep totals coherent with any admin edits
            order.recompute_totals()
            messages.success(request, "Shipping updated.")
            return redirect("backoffice:order_detail", order_id=order.pk)
    else:
        form = OrderShippingForm(instance=order)

    return render(request, "backoffice/order_shipping_edit.html",
                  {"order": order, "form": form})


# ---------- detail + fulfillment actions ----------
@staff_member_required
def order_detail(request, order_id):
    o = get_object_or_404(Order.objects.select_related("user"), id=order_id)

    if request.method == "POST":
        # keep previous values to decide on emailing
        prev_status   = getattr(o, "fulfillment_status", "")
        prev_tracking = (getattr(o, "tracking_number", "") or "").strip()

        # --- form 1: save fulfillment (status/tracking/carrier/note) ---
        if "save_fulfillment" in request.POST:
            if hasattr(o, "fulfillment_status"):
                o.fulfillment_status = request.POST.get("fulfillment_status", o.fulfillment_status)
            if hasattr(o, "tracking_number"):
                o.tracking_number = (request.POST.get("tracking_number") or "").strip()
            if hasattr(o, "carrier"):
                o.carrier = (request.POST.get("carrier") or "").strip()
            if hasattr(o, "admin_note"):
                o.admin_note = request.POST.get("admin_note", o.admin_note)

            # if moving to shipped here, stamp shipped_at
            if prev_status != "shipped" and o.fulfillment_status == "shipped":
                o.mark_shipped()  # sets status + shipped_at and saves
            else:
                o.save()

            # decide whether to email
            should_email = False
            if prev_status != "shipped" and o.fulfillment_status == "shipped":
                should_email = True
            elif o.fulfillment_status == "shipped" and (o.tracking_number or "") != prev_tracking:
                should_email = True

            if should_email:
                try:
                    send_shipment_email(o)
                    messages.success(request, "Shipment email sent to customer.")
                except Exception as e:
                    messages.warning(request, f"Saved, but email failed: {e}")

            messages.success(request, "Order updated.")
            return redirect("backoffice:order_detail", order_id=o.id)

        # --- form 2: mark as shipped button ---
        if "mark_shipped" in request.POST:
            if hasattr(o, "fulfillment_status"):
                o.fulfillment_status = "shipped"
            o.shipped_at = timezone.now()
            o.save(update_fields=["fulfillment_status", "shipped_at"] if hasattr(o, "fulfillment_status") else ["shipped_at"])

            # send email when we switch to shipped via button
            try:
                send_shipment_email(o)
                messages.success(request, "Order marked as shipped and customer notified.")
            except Exception as e:
                messages.warning(request, f"Marked as shipped, but email failed: {e}")

            return redirect("backoffice:order_detail", order_id=o.id)

    # GET
    return render(request, "backoffice/order_detail.html", {"o": o})