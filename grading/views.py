from pathlib import Path
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from .forms import GradingForm
from .models import GradeRequest
from .openai_client import grade_with_openai

def grade_card(request):
    """Public page to upload & grade a card."""
    if request.method == "POST":
        form = GradingForm(request.POST, request.FILES)
        if form.is_valid():
            gr: GradeRequest = form.save(commit=False)
            if request.user.is_authenticated:
                gr.user = request.user
            gr.save()  # save first so images are written to disk

            try:
                data = grade_with_openai(
                    Path(gr.front_image.path),
                    Path(gr.back_image.path) if gr.back_image else None
                )
            except Exception as exc:
                messages.error(request, f"AI grading failed: {exc}")
                gr.delete()
                return redirect("grading:grade")

            # Map JSON → model fields
            s = data.get("scores", {})
            gr.score_centering = Decimal(str(s.get("centering", 0)))
            gr.score_surface   = Decimal(str(s.get("surface", 0)))
            gr.score_edges     = Decimal(str(s.get("edges", 0)))
            gr.score_corners   = Decimal(str(s.get("corners", 0)))
            gr.score_color     = Decimal(str(s.get("color", 0)))

            gr.predicted_grade = Decimal(str(data.get("predicted_grade", 0)))
            gr.predicted_label = data.get("predicted_label","")
            gr.explanation_md  = data.get("summary","")
            gr.needs_better_photos = bool(data.get("needs_better_photos", False))
            gr.photo_feedback  = data.get("photo_feedback","")
            gr.raw_json        = data

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



# grading/views.py
import base64, json
from django.conf import settings
from django.shortcuts import render
from django.contrib import messages
from openai import OpenAI

client = OpenAI(api_key=getattr(settings, "OPENAI_API_KEY", None))

def _b64_data_uri(uploaded_file):
    """
    Convert a Django UploadedFile to a data: URI string suitable for GPT-4o image input.
    """
    content = uploaded_file.read()
    mime = uploaded_file.content_type or "image/jpeg"
    b64 = base64.b64encode(content).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def grade_card_view(request):
    """
    GET: show form
    POST: call OpenAI to grade the card from images
    """
    result = None

    if request.method == "POST":
        card_name = request.POST.get("card_name", "").strip()
        front = request.FILES.get("front")
        back  = request.FILES.get("back")

        if not front:
            messages.error(request, "Please upload the front image.")
        else:
            try:
                front_uri = _b64_data_uri(front)
                back_uri  = _b64_data_uri(back) if back else None

                # Build the multimodal user content
                user_content = [
                    {"type": "text", "text": f"Card: {card_name or 'Unknown'}"},
                    {"type": "input_image", "image_url": {"url": front_uri}},
                ]
                if back_uri:
                    user_content.append({"type": "input_image", "image_url": {"url": back_uri}})

                system_prompt = (
                    "You are a professional TCG card grading assistant. "
                    "Grade the card on the following PSA-like categories: centering, surface, edges, corners, color. "
                    "Scores must be 1–10 (decimals allowed), and provide a single predicted overall_grade (1–10). "
                    "If the image quality is poor (blurry, glare, cropped), explain that and lower confidence. "
                    "Return STRICT JSON with this schema:\n"
                    "{\n"
                    '  "centering": number,\n'
                    '  "surface": number,\n'
                    '  "edges": number,\n'
                    '  "corners": number,\n'
                    '  "color": number,\n'
                    '  "overall_grade": number,\n'
                    '  "confidence": "low|medium|high",\n'
                    '  "summary": "short explanation"\n'
                    "}"
                )

                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    temperature=0.3,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                )

                raw = resp.choices[0].message.content or "{}"
                # try parse as JSON; if the model returns text with JSON inside, extract it
                try:
                    result = json.loads(raw)
                except json.JSONDecodeError:
                    # attempt to find a JSON block
                    start = raw.find("{")
                    end   = raw.rfind("}")
                    if start != -1 and end != -1 and end > start:
                        result = json.loads(raw[start:end+1])
                    else:
                        raise

            except Exception as e:
                messages.error(request, f"AI grading failed: {e}")

    return render(request, "grading/grade.html", {"result": result})
