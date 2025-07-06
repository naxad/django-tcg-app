// Initialize AOS (Animate On Scroll)
AOS.init({
    duration: 600,
    easing: 'ease-out',
    once: true
});

// Get CSRF token from cookie
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Use window.csrfToken if set; otherwise get from cookie
var csrfToken = window.csrfToken || getCookie('csrftoken');

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".rating-stars .star").forEach(star => {
        star.addEventListener("click", function () {
            const score = this.getAttribute("data-score");
            const cardId = this.getAttribute("data-card-id");

            fetch("/browse/rate/", {
                method: "POST",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                body: `card_id=${cardId}&score=${score}`
            })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        alert("Thanks for your rating!");
                        location.reload(); // Optionally reload to update stars
                    } else {
                        alert("Error: " + (data.error || "Something went wrong."));
                    }
                });
        });
    });
});

// Utility to get CSRF token
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let cookie of cookies) {
            cookie = cookie.trim();
            if (cookie.startsWith(name + "=")) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}


// Modal image view
document.addEventListener('DOMContentLoaded', function () {
    const imageElements = document.querySelectorAll('.card-img-clickable');
    const modal = new bootstrap.Modal(document.getElementById('imageModal'));
    const modalImage = document.getElementById('modalImage');

    imageElements.forEach(img => {
        img.addEventListener('click', () => {
            const imageUrl = img.dataset.img;
            if (modalImage && imageUrl) {
                modalImage.src = imageUrl;
                modal.show();
            }
        });
    });
});

// Infinite card carousel with manual arrows
document.addEventListener("DOMContentLoaded", function () {
    const track = document.querySelector(".card-track");
    if (!track) return;

    const originalItems = Array.from(track.children);
    const cardWidth = originalItems[0].offsetWidth;
    const gap = 24;
    const fullCardWidth = cardWidth + gap;

    // Clone 50 sets of the cards
    for (let i = 0; i < 50; i++) {
        originalItems.forEach(item => {
            const clone = item.cloneNode(true);
            clone.classList.add("clone");
            track.appendChild(clone);
        });
    }

    let scrollPos = 0;
    const speed = 0.5;
    let manualScroll = false;

    function loopScroll() {
        if (!manualScroll) {
            scrollPos += speed;
            track.style.transform = `translateX(-${scrollPos}px)`;
        }

        const totalItems = track.children.length;
        const totalTrackWidth = fullCardWidth * totalItems;

        if (scrollPos >= totalTrackWidth - (fullCardWidth * originalItems.length)) {
            scrollPos = 0;
            track.style.transform = `translateX(0)`;
        }

        requestAnimationFrame(loopScroll);
    }

    requestAnimationFrame(loopScroll);
});
