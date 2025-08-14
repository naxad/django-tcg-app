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





document.addEventListener("DOMContentLoaded", function () {
    const root = document.querySelector(".grade-carousel");
    if (!root) return;

    const slides = root.querySelectorAll(".gc-img");
    const prev = root.querySelector(".gc-prev");
    const next = root.querySelector(".gc-next");
    const dots = root.querySelectorAll(".gc-dot");
    let idx = 0;

    function show(i) {
        idx = (i + slides.length) % slides.length;
        slides.forEach((el, j) => el.classList.toggle("gc-active", j === idx));
        dots.forEach((d, j) => d.classList.toggle("gc-dot-active", j === idx));
    }

    if (next) next.addEventListener("click", () => show(idx + 1));
    if (prev) prev.addEventListener("click", () => show(idx - 1));
    dots.forEach((d, j) => d.addEventListener("click", () => show(j)));
});
