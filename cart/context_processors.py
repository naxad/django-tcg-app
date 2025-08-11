# tcg_store/context_processors.py
import os

def payment_keys(request):
    return {
        "PAYPAL_CLIENT_ID": os.environ.get("PAYPAL_CLIENT_ID", ""),
        # You can also expose Stripe public key if you want:
        "STRIPE_PUBLIC_KEY": os.environ.get("STRIPE_PUBLIC_KEY", ""),
    }