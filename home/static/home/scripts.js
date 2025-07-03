// Initialize AOS (Animate On Scroll)
AOS.init({
    duration: 600,
    easing: 'ease-out',
    once: true
});

// AJAX rating system
$(document).ready(function () {
    $('.rating-stars .star').on('click', function () {
        const score = $(this).data('value');
        const cardId = $(this).parent().data('card');

        $.ajax({
            type: 'POST',
            url: '/rate-card/',
            data: {
                card_id: cardId,
                score: score,
                csrfmiddlewaretoken: csrfToken
            },
            success: function (response) {
                if (response.success) {
                    alert('Rating submitted!');
                    location.reload();
                } else {
                    alert('Error: ' + response.error);
                }
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
    const speed = 0.5; // Adjust speed here
    let manualScroll = false;
    let manualTimeout;

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
