// static/js/scripts.js
console.log("🟢 scripts.js loaded");

// -----------------------------
// AOS (Animate On Scroll)
// -----------------------------
if (window.AOS) {
    AOS.init({ duration: 600, easing: "ease-out", once: true });
}

// -----------------------------
// CSRF helper (Django)
// -----------------------------
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return decodeURIComponent(parts.pop().split(";").shift());
    return null;
}
const CSRFTOKEN = window.csrfToken || getCookie("csrftoken") || "";

// -----------------------------
// Ratings (stars)
// -----------------------------
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".rating-stars .star").forEach((star) => {
        star.addEventListener("click", function () {
            const score = this.getAttribute("data-score");
            const cardId = this.getAttribute("data-card-id");

            fetch("/browse/rate/", {
                method: "POST",
                headers: {
                    "X-CSRFToken": CSRFTOKEN,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body: `card_id=${encodeURIComponent(cardId)}&score=${encodeURIComponent(score)}`,
            })
                .then((res) => {
                    if (res.status === 401) {
                        alert("Please log in to rate cards!");
                        return null;
                    }
                    return res.json();
                })
                .then((data) => {
                    if (!data) return;
                    if (data.success) {
                        alert("Thanks for your rating!");
                        location.reload();
                    } else {
                        alert("Error: " + (data.error || "Something went wrong."));
                    }
                })
                .catch(() => alert("Network error. Please try again."));
        });
    });
});

// -----------------------------
// Modal image view
// -----------------------------
document.addEventListener("DOMContentLoaded", function () {
    const imageElements = document.querySelectorAll(".card-img-clickable");
    const modalEl = document.getElementById("imageModal");
    const modalImage = document.getElementById("modalImage");
    if (!modalEl || !modalImage) return;

    const modal = new bootstrap.Modal(modalEl);
    imageElements.forEach((img) => {
        img.addEventListener("click", () => {
            const imageUrl = img.dataset.img;
            if (imageUrl) {
                modalImage.src = imageUrl;
                modal.show();
            }
        });
    });
});

// -----------------------------
// Infinite card carousel (clone items)
// -----------------------------
window.addEventListener("load", function () {
    setTimeout(() => {
        const track = document.querySelector(".card-track");
        if (!track) return;

        const originalItems = Array.from(track.children);
        const cloneCount = 50;
        if (originalItems.length === 0) return;

        for (let i = 0; i < cloneCount; i++) {
            originalItems.forEach((item) => {
                const clone = item.cloneNode(true);
                clone.classList.add("clone");
                track.appendChild(clone);
            });
        }
        console.log(`✅ Cloned ${originalItems.length}×${cloneCount} = ${originalItems.length * cloneCount} cards.`);
    }, 100);
});

// -----------------------------
// Add-card modal trigger
// -----------------------------
document.addEventListener("DOMContentLoaded", function () {
    const addCardBtn = document.getElementById("addCardBtn");
    const addCardModalEl = document.getElementById("addCardModal");
    if (addCardBtn && addCardModalEl) {
        const addCardModal = new bootstrap.Modal(addCardModalEl);
        addCardBtn.addEventListener("click", () => addCardModal.show());
    }
});

// -----------------------------
// Profile tab: open from hash (#tab-profile etc.)
// -----------------------------
document.addEventListener("DOMContentLoaded", function () {
    const hash = window.location.hash;
    if (!hash) return;
    const btn = document.querySelector(`button[data-bs-target="${hash}"]`);
    if (btn && window.bootstrap) new bootstrap.Tab(btn).show();
});

// -----------------------------
// Checkout: Stripe + PayPal
// -----------------------------
(function () {
    async function postJSON(url, body) {
        const opts = {
            method: "POST",
            headers: {
                "X-CSRFToken": CSRFTOKEN,
                "Content-Type": "application/json",
            },
        };
        if (body !== undefined) opts.body = JSON.stringify(body);
        const res = await fetch(url, opts);
        let data = null;
        try {
            data = await res.json();
        } catch (_) { }
        return { res, data };
    }

    // Stripe redirect Checkout
    async function handleStripeClick(cfg) {
        const { res, data } = await postJSON(cfg.stripeUrl);
        if (!res.ok) {
            alert((data && data.message) || "Please select a shipping address first.");
            return;
        }
        if (data && data.url) {
            window.location = data.url;
        } else {
            alert("Could not start Stripe Checkout.");
        }
    }

    // PayPal Buttons (server-created order)
    async function initPayPal(cfg) {
        const container = document.getElementById("paypal-button-container");
        if (!container) return;
        if (!window.paypal) {
            console.warn("PayPal SDK not loaded.");
            return;
        }

        try {
            // Create the PayPal order on our server first (validates shipping)
            const r = await fetch(cfg.paypalCreateUrl, {
                method: "POST",
                headers: { "X-CSRFToken": CSRFTOKEN },
            });
            if (!r.ok) {
                let d = null;
                try {
                    d = await r.json();
                } catch (_e) { }
                container.innerHTML =
                    '<div class="alert alert-warning mb-0">' +
                    (d && d.message ? d.message : "Please select a shipping address first.") +
                    "</div>";
                return;
            }
            const { id } = await r.json();

            paypal
                .Buttons({
                    createOrder: () => id, // server-created id
                    onApprove: async () => {
                        const capUrl = cfg.paypalCaptureUrl.replace("__ORDER_ID__", id);
                        const resp = await fetch(capUrl, {
                            method: "POST",
                            headers: { "X-CSRFToken": CSRFTOKEN },
                        });
                        if (!resp.ok) {
                            alert("PayPal capture failed. If funds were taken, contact support.");
                            return;
                        }
                        window.location = cfg.thankYouUrl;
                    },
                    onError: (err) => {
                        console.error(err);
                        alert("PayPal error: " + (err && err.message ? err.message : "Something went wrong."));
                    },
                })
                .render("#paypal-button-container");
        } catch (e) {
            console.error(e);
            container.innerHTML = '<div class="alert alert-danger mb-0">Unable to initialize PayPal.</div>';
        }
    }

    // Public initializer for checkout page
    window.initCheckout = function initCheckout(cfg) {
        const root = document.getElementById("checkout-root");
        const shippingReady = root ? root.getAttribute("data-shipping-ready") === "1" : true;

        // Stripe button
        const stripeBtn = document.getElementById("pay-stripe");
        if (stripeBtn) {
            stripeBtn.addEventListener("click", () => handleStripeClick(cfg));
            if (!shippingReady) {
                stripeBtn.disabled = true;
                stripeBtn.title = "Please select a shipping address first.";
            }
        }

        // PayPal buttons
        if (shippingReady) {
            initPayPal(cfg);
        } else {
            const cont = document.getElementById("paypal-button-container");
            if (cont) cont.innerHTML = '<div class="alert alert-warning mb-0">Please select a shipping address first.</div>';
        }
    };
})();



// Cart: block checkout below €0.50 with a red toast
document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('btn-checkout');
    if (!btn) return;

    btn.addEventListener('click', function (e) {
        const raw = btn.getAttribute('data-total');
        const total = parseFloat((raw || '0').replace(',', '.'));
        if (isNaN(total) || total < 0.50) {
            e.preventDefault();
            const toastEl = document.getElementById('minOrderToast');
            if (toastEl && window.bootstrap) {
                const toast = bootstrap.Toast.getOrCreateInstance(toastEl);
                toast.show();
            } else {
                alert('Minimum order is €0.50. Please add more items to continue.');
            }
        }
    });
});
