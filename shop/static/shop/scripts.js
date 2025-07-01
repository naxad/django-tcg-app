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
                csrfmiddlewaretoken: csrfToken  // declared in base.html
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
