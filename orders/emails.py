# orders/emails.py
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

def send_order_emails(order):
    to = [order.email] if getattr(order, "email", "") else []
    if not to:
        print("[EMAIL] Skipping: order.email is empty")
        return

    ctx = {
        "order": order,
        "items": order.items.all(),
        "items_subtotal": order.items_subtotal,
        "shipping_price": order.shipping_price or 0,
        "grand_total": (order.items_subtotal or 0) + (order.shipping_price or 0),
    }

    # ⬇ Make sure these paths match your files on disk:
    subject = render_to_string("orders/order_confirmation_subject.txt", ctx).strip()
    text_body = render_to_string("orders/order_confirmation.txt", ctx)
    html_body = render_to_string("orders/order_confirmation.html", ctx)

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_HOST_USER)

    msg = EmailMultiAlternatives(subject, text_body, from_email, to)
    msg.attach_alternative(html_body, "text/html")
    print(f"[EMAIL] Sending customer email to {to} …")
    msg.send(fail_silently=False)   # ⬅ show errors
    print("[EMAIL] Customer email sent")

    rcpts = list(getattr(settings, "ORDER_ALERT_RECIPIENTS", []))
    if rcpts:
        admin_body = render_to_string("orders/order_alert.txt", ctx)
        EmailMultiAlternatives(
            subject=f"[Order #{order.id}] Paid – {order.email}",
            body=admin_body,
            from_email=from_email,
            to=rcpts,
        ).send(fail_silently=False)
        print("[EMAIL] Admin alert sent to", rcpts)




def send_shipment_email(order):
    """
    Notify the customer that the order shipped.
    Sends both text and HTML versions.
    """
    if not order.email:
        return

    ctx = {
        "order": order,
        "tracking_number": order.tracking_number or "",
        "carrier": order.carrier or "",
        "shipping_name": order.shipping_name,
        "shipping_line1": order.shipping_line1,
        "shipping_line2": order.shipping_line2,
        "shipping_city": order.shipping_city,
        "shipping_postal_code": order.shipping_postal_code,
        "shipping_country": order.shipping_country,
    }

    subject = render_to_string("orders/shipment_subject.txt", ctx).strip()
    text_body = render_to_string("orders/shipment.txt", ctx)
    html_body = render_to_string("orders/shipment.html", ctx)

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_HOST_USER)
    to = [order.email]

    msg = EmailMultiAlternatives(subject, text_body, from_email, to)
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=False)
