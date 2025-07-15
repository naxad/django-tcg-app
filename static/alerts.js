document.addEventListener('DOMContentLoaded', function () {
    const alertBox = document.getElementById('cart-alert');

    if (alertBox) {
        setTimeout(() => {
            alertBox.classList.add('fade-out');  // fade out using opacity
        }, 2500);

        setTimeout(() => {
            alertBox.remove();  // fully remove from DOM
        }, 3500);
    }
});


document.addEventListener('DOMContentLoaded', function () {
    const toastEl = document.getElementById('cartToast');
    if (toastEl) {
        const toast = new bootstrap.Toast(toastEl, { delay: 3000 });  // 3 seconds
        toast.show();
    }
});

