# grading/views.py
from __future__ import annotations
from pathlib import Path
from decimal import Decimal

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpRequest
from django.http import HttpResponseNotFound
from .forms import GradingForm
from .models import GradeRequest

from django.conf import settings
def grading_enabled() -> bool:
    return getattr(settings, "GRADING_ENABLED", False)

# --- engines ---
from .openai_client import grade_with_openai            # existing AI path
from grading.ml.cv_inference import CVGrader            # new CV model

# Load CV model once (fast subsequent requests)
CV_MODEL = CVGrader(weights_path="grading/ml/models/cardgrader_v1.pt", size=384)


def _label_from_score(x: float) -> str:
    """Very simple labeler; tweak as you like."""
    if x >= 9.5:
        return "Gem Mint 10"
    if x >= 9.0:
        return "Mint 9"
    if x >= 8.0:
        return "NM-MT 8"
    if x >= 7.0:
        return "NM 7"
    if x >= 6.0:
        return "EX-MT 6"
    if x >= 5.0:
        return "EX 5"
    return f"{x:.1f}"


def grade_card(request: HttpRequest):
    """
    Public page to upload & grade a card.

    Toggle engine with ?engine=cv (new computer-vision model)
    or ?engine=ai (your OpenAI grader). Default = cv.
    """
    engine = (request.GET.get("engine") or "cv").lower()
    if not grading_enabled():
        return redirect("grading:coming_soon")
    
    if request.method == "POST":
        form = GradingForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, "grading/grade_form.html", {"form": form})

        gr: GradeRequest = form.save(commit=False)

        # Optional "game" if your model has the field
        game = (request.POST.get("game") or "").strip().lower()
        if hasattr(gr, "game"):
            gr.game = game

        if request.user.is_authenticated:
            gr.user = request.user

        # Save first so images exist on disk
        gr.save()

        try:
            if engine == "ai":
                # ---------- Existing OpenAI engine ----------
                ptcgo_code = form.cleaned_data.get("ptcgo_code")
                collector_number = form.cleaned_data.get("collector_number")

                data = grade_with_openai(
                    Path(gr.front_image.path),
                    Path(gr.back_image.path) if gr.back_image else None,
                    game_hint=game,
                    ptcgo_code=ptcgo_code,
                    collector_number=collector_number,
                )

                s = data.get("scores", {})
                gr.score_centering = Decimal(str(s.get("centering", 0)))
                gr.score_surface   = Decimal(str(s.get("surface",   0)))
                gr.score_edges     = Decimal(str(s.get("edges",     0)))
                gr.score_corners   = Decimal(str(s.get("corners",   0)))
                gr.score_color     = Decimal(str(s.get("color",     0)))
                overall            = Decimal(str(data.get("predicted_grade", 0)))
                gr.predicted_grade = overall
                gr.predicted_label = data.get("predicted_label", _label_from_score(float(overall)))
                gr.explanation_md  = data.get("summary", "")
                gr.needs_better_photos = bool(data.get("needs_better_photos", False))
                gr.photo_feedback  = data.get("photo_feedback", "")
                gr.raw_json        = data

            else:
                # ---------- New CV engine ----------
                front_p = Path(gr.front_image.path)
                back_p  = Path(gr.back_image.path) if gr.back_image else None

                cv_out = CV_MODEL.predict(front_p, back_p)

                # If the CV pipeline gated on quality, show a helpful message and stop
                if not cv_out.get("success", True):
                    reason = cv_out.get("message", "Photo quality too low for grading.")
                    stage  = cv_out.get("stage", "quality")
                    messages.warning(
                        request,
                        f"Couldn’t grade this photo ({stage}): {reason} — "
                        f"try retaking with more light, less glare, the card filling the frame, "
                        f"and keep it squared to the camera."
                    )

                    # Keep the record for your audit/debug (optional)
                    gr.needs_better_photos = True
                    gr.photo_feedback = reason
                    gr.explanation_md = (
                        "Grading skipped due to photo quality gate. "
                        "Please retake with the card squared up, high resolution, minimal glare, "
                        "and the full card visible."
                    )
                    gr.raw_json = {"engine": "cv", **cv_out}
                    gr.save(update_fields=["needs_better_photos", "photo_feedback", "explanation_md", "raw_json"])

                    return redirect("grading:grade")

                # Otherwise, fill in scores from CV
                gr.score_centering = Decimal(str(cv_out.get("centering", 0)))
                gr.score_surface   = Decimal(str(cv_out.get("surface",   0)))
                gr.score_edges     = Decimal(str(cv_out.get("edges",     0)))
                gr.score_corners   = Decimal(str(cv_out.get("corners",   0)))
                gr.score_color     = Decimal(str(cv_out.get("color",     0)))
                overall = Decimal(str(cv_out.get("overall", 0)))
                gr.predicted_grade = overall
                gr.predicted_label = _label_from_score(float(overall))
                gr.explanation_md  = (
                    "Graded by CV model (pair-regressor v1). "
                    "Scores reflect centering/surface/edges/corners/color; "
                    "overall is the model’s direct prediction."
                )
                gr.needs_better_photos = False
                gr.photo_feedback = ""
                gr.raw_json = {"engine": "cv", **cv_out}

        except Exception as exc:
            messages.error(request, f"Grading failed: {exc}")
            # optional: keep the record for debugging; or remove it:
            # gr.delete()
            return redirect("grading:grade")

        # Persist results
        gr.save(update_fields=[
            "score_centering", "score_surface", "score_edges", "score_corners", "score_color",
            "predicted_grade", "predicted_label", "explanation_md",
            "needs_better_photos", "photo_feedback", "raw_json",
            *(["game"] if hasattr(gr, "game") else []),
        ])
        return redirect("grading:result", pk=gr.pk)

    # GET -> show form
    form = GradingForm()
    return render(request, "grading/grade_form.html", {"form": form})


def grade_result(request, pk: int):
    gr = get_object_or_404(GradeRequest, pk=pk)
    if not grading_enabled():
        return HttpResponseNotFound("Grading is currently unavailable.")
    return render(request, "grading/grade_result.html", {"gr": gr})

def coming_soon(request):
    return render(request, "grading/coming_soon.html")
