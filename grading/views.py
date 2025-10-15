# grading/views.py
from __future__ import annotations
from pathlib import Path
from decimal import Decimal
from functools import lru_cache
import os

from django.contrib import messages
from django.conf import settings
from django.http import HttpRequest, HttpResponseNotFound
from django.shortcuts import render, redirect, get_object_or_404

from .forms import GradingForm
from .models import GradeRequest


def grading_enabled() -> bool:
    """Gate to show the grading UI at all."""
    return bool(getattr(settings, "GRADING_ENABLED", False))


# Feature flags (set these in Render → Environment)
AI_ENABLED = os.getenv("ENABLE_GRADING_AI", "0") == "1"
CV_ENABLED = os.getenv("ENABLE_CV_GRADER", "0") == "1"


def _label_from_score(x: float) -> str:
    if x >= 9.5: return "Gem Mint 10"
    if x >= 9.0: return "Mint 9"
    if x >= 8.0: return "NM-MT 8"
    if x >= 7.0: return "NM 7"
    if x >= 6.0: return "EX-MT 6"
    if x >= 5.0: return "EX 5"
    return f"{x:.1f}"


# ---- Lazy loaders (avoid importing heavy deps unless enabled & needed) ----
@lru_cache(maxsize=1)
def _get_cv_model():
    from grading.ml.cv_inference import CVGrader  # lazy import
    return CVGrader(weights_path="grading/ml/models/cardgrader_v1.pt", size=384)


def _grade_with_openai(*args, **kwargs):
    from .openai_client import grade_with_openai  # lazy import
    return grade_with_openai(*args, **kwargs)


# ----------------------------- Views ----------------------------------------
def grade_card(request: HttpRequest):
    """
    Upload & grade a card.
    Toggle engine with ?engine=cv or ?engine=ai (default=cv).
    """
    engine = (request.GET.get("engine") or "cv").lower()

    # Allow the UI to load even if grading is disabled.
    # When disabled, show the form but block POST.
    ui_allowed = grading_enabled()

    if request.method == "POST":
        if not ui_allowed:
            return redirect("grading:coming_soon")

        form = GradingForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, "grading/grade_form.html", {"form": form, "ui_allowed": ui_allowed})

        gr: GradeRequest = form.save(commit=False)

        game = (request.POST.get("game") or "").strip().lower()
        if hasattr(gr, "game"):
            gr.game = game
        if request.user.is_authenticated:
            gr.user = request.user
        gr.save()  # save early so images exist on disk

        try:
            if engine == "ai":
                if not AI_ENABLED:
                    messages.warning(request, "AI grading is disabled on this deployment.")
                    return redirect("grading:grade")

                ptcgo_code = form.cleaned_data.get("ptcgo_code")
                collector_number = form.cleaned_data.get("collector_number")

                data = _grade_with_openai(
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

            else:  # engine == "cv"
                if not CV_ENABLED:
                    messages.warning(request, "Computer-vision grading is disabled on this deployment.")
                    return redirect("grading:grade")

                front_p = Path(gr.front_image.path)
                back_p  = Path(gr.back_image.path) if gr.back_image else None

                cv_model = _get_cv_model()
                cv_out = cv_model.predict(front_p, back_p)

                if not cv_out.get("success", True):
                    reason = cv_out.get("message", "Photo quality too low for grading.")
                    stage  = cv_out.get("stage", "quality")
                    messages.warning(
                        request,
                        f"Couldn’t grade this photo ({stage}): {reason}. "
                        "Try with more light, less glare, and keep the card square to the camera."
                    )
                    gr.needs_better_photos = True
                    gr.photo_feedback = reason
                    gr.explanation_md = (
                        "Grading skipped due to photo quality gate."
                    )
                    gr.raw_json = {"engine": "cv", **cv_out}
                    gr.save(update_fields=["needs_better_photos", "photo_feedback", "explanation_md", "raw_json"])
                    return redirect("grading:grade")

                gr.score_centering = Decimal(str(cv_out.get("centering", 0)))
                gr.score_surface   = Decimal(str(cv_out.get("surface",   0)))
                gr.score_edges     = Decimal(str(cv_out.get("edges",     0)))
                gr.score_corners   = Decimal(str(cv_out.get("corners",   0)))
                gr.score_color     = Decimal(str(cv_out.get("color",     0)))
                overall = Decimal(str(cv_out.get("overall", 0)))
                gr.predicted_grade = overall
                gr.predicted_label = _label_from_score(float(overall))
                gr.explanation_md  = "Graded by CV model (pair-regressor v1)."
                gr.needs_better_photos = False
                gr.photo_feedback = ""
                gr.raw_json = {"engine": "cv", **cv_out}

        except Exception as exc:
            messages.error(request, f"Grading failed: {exc}")
            return redirect("grading:grade")

        gr.save(update_fields=[
            "score_centering", "score_surface", "score_edges", "score_corners", "score_color",
            "predicted_grade", "predicted_label", "explanation_md",
            "needs_better_photos", "photo_feedback", "raw_json",
            *(["game"] if hasattr(gr, "game") else []),
        ])
        return redirect("grading:result", pk=gr.pk)

    # GET → show form (even if disabled; the template can show a banner)
    form = GradingForm()
    return render(request, "grading/grade_form.html", {"form": form, "ui_allowed": ui_allowed})


def grade_result(request, pk: int):
    gr = get_object_or_404(GradeRequest, pk=pk)
    if not grading_enabled():
        return HttpResponseNotFound("Grading is currently unavailable.")
    return render(request, "grading/grade_result.html", {"gr": gr})


def coming_soon(request):
    return render(request, "grading/coming_soon.html")