# grading/views.py
from pathlib import Path
from decimal import Decimal

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from .forms import GradingForm
from .models import GradeRequest
from .openai_client import grade_with_openai


def grade_card(request):
    """
    Public page to upload & grade a card.
    Uses openai_client.grade_with_openai() exclusively.
    """
    if request.method == "POST":
        form = GradingForm(request.POST, request.FILES)
        if form.is_valid():
            # Save first so images are written to disk and we have file paths
            gr: GradeRequest = form.save(commit=False)
            if request.user.is_authenticated:
                gr.user = request.user
            gr.save()

            try:
                data = grade_with_openai(
                    Path(gr.front_image.path),
                    Path(gr.back_image.path) if gr.back_image else None
                )
            except Exception as exc:
                messages.error(request, f"AI grading failed: {exc}")
                # optional: keep the request for audit; if you prefer to drop it:
                # gr.delete()
                return redirect("grading:grade")

            # Map JSON → model fields (matches your openai_client output)
            s = data.get("scores", {}) or {}
            gr.score_centering = Decimal(str(s.get("centering", 0)))
            gr.score_surface   = Decimal(str(s.get("surface", 0)))
            gr.score_edges     = Decimal(str(s.get("edges", 0)))
            gr.score_corners   = Decimal(str(s.get("corners", 0)))
            gr.score_color     = Decimal(str(s.get("color", 0)))

            gr.predicted_grade     = Decimal(str(data.get("predicted_grade", 0)))
            gr.predicted_label     = data.get("predicted_label", "")
            gr.explanation_md      = data.get("summary", "")
            gr.needs_better_photos = bool(data.get("needs_better_photos", False))
            gr.photo_feedback      = data.get("photo_feedback", "")
            gr.raw_json            = data

            gr.save(update_fields=[
                "score_centering","score_surface","score_edges","score_corners","score_color",
                "predicted_grade","predicted_label","explanation_md",
                "needs_better_photos","photo_feedback","raw_json"
            ])
            return redirect("grading:result", pk=gr.pk)
    else:
        form = GradingForm()

    return render(request, "grading/grade_form.html", {"form": form})


def grade_result(request, pk):
    gr = get_object_or_404(GradeRequest, pk=pk)
    return render(request, "grading/grade_result.html", {"gr": gr})