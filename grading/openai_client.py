# grading/openai_client.py
from __future__ import annotations
import base64, json, mimetypes, os
from pathlib import Path
from typing import Optional, Dict, Any
from openai import OpenAI

# You can swap to "gpt-4o" for even better accuracy
OPENAI_MODEL_GRADE = os.getenv("OPENAI_GRADING_MODEL", "gpt-4o")
OPENAI_MODEL_CLASS = os.getenv("OPENAI_CLASSIFIER_MODEL", "gpt-4o-mini")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------- helpers ----------
def _file_to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "image/jpeg"
    b64 = base64.b64encode(Path(path).read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def _img_part(path: Path) -> Dict[str, Any]:
    return {"type": "image_url", "image_url": {"url": _file_to_data_url(path)}}

def _safe_float(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d

# ---------- Stage 1: classification/gating (FRONT/BACK only, no “same card” test) ----------
CLASSIFY_PROMPT = (
    "You are a strict intake checker for TCG card photos.\n"
    "You will receive two images. For each image, decide if it shows a card FRONT or card BACK.\n"
    "Rules of thumb (Pokémon): backs are the blue design with the Poké Ball and 'Pokémon' logo; "
    "fronts show the card artwork, text boxes, set symbol/number, etc.\n"
    "Also rate overall photo quality as 'low'|'medium'|'high'.\n"
    "Return STRICT JSON ONLY:\n"
    "{\n"
    '  "detected_sides": {"image_1":"front|back|unknown", "image_2":"front|back|unknown"},\n'
    '  "image_quality": "low|medium|high"\n'
    "}\n"
)

def _classify_images(img1: Path, img2: Optional[Path]) -> Dict[str, Any]:
    content = [{"type": "text", "text": "Classify these two images (order matters)."}]
    content.append(_img_part(img1))
    if img2:
        content.append(_img_part(img2))
    else:
        content.append({"type": "text", "text": "Second image is missing."})

    resp = client.chat.completions.create(
        model=OPENAI_MODEL_CLASS,
        temperature=0.0,
        messages=[
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user", "content": content},
        ],
    )
    raw = (resp.choices[0].message.content or "{}").strip()
    try:
        data = json.loads(raw)
    except Exception:
        s, e = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[s:e+1]) if s != -1 and e != -1 and e > s else {}

    ds = data.get("detected_sides") or {}
    data["detected_sides"] = {
        "image_1": str(ds.get("image_1", "unknown")),
        "image_2": str(ds.get("image_2", "unknown")),
    }
    data["image_quality"] = (data.get("image_quality") or "low").lower()
    return data

# ---------- Stage 2: meticulous grading ----------
GRADE_PROMPT = (
    "You are a meticulous pre-grader for TCG cards (PSA-like 1..10; 10=Gem Mint).\n"
    "You will receive FRONT then BACK images of the same card. Do not deduct unless you can name at least one concrete, "
    "visible observation.\n"
    "PROCESS (mandatory):\n"
    "• Split each image into a 5×5 grid; scan top→bottom, left→right.\n"
    "• Centering: estimate border thickness on all four sides—front weighted more, back too; report off-center directions.\n"
    "• Surface: look for print lines, scratches, stains, dents/dimples, specks—distinguish true defects from glare/noise.\n"
    "• Edges: zoom along all edges for whitening/chips; avoid confusing holo sparkles/noise with wear.\n"
    "• Corners: zoom on all four corners for rounding, fray, whitening.\n"
    "• Color: check fading/yellowing/oversaturation/uneven tones.\n"
    "• If anything prevents accurate grading (blurry, glare, crop, two fronts/two backs), set needs_better_photos=true and "
    "  return zeroes for scores with clear photo_feedback.\n"
    "• If pristine (no valid observations of wear) and borders are excellent, Gem Mint (10) is allowed.\n\n"
    "OUTPUT STRICT JSON ONLY:\n"
    "{\n"
    '  "scores": {"centering": number, "surface": number, "edges": number, "corners": number, "color": number},\n'
    '  "predicted_grade": number,\n'
    '  "predicted_label": string,\n'
    '  "needs_better_photos": boolean,\n'
    '  "photo_feedback": string,\n'
    '  "observations": [\n'
    '    {"category":"centering|surface|edges|corners|color","side":"front|back","note":"short detail","box":[x0,y0,x1,y1]}\n'
    "  ],\n"
    '  "summary": string\n'
    "}\n"
)

def _normalize_grade_json(data: Dict[str, Any]) -> Dict[str, Any]:
    s = data.get("scores", {}) or {}
    return {
        "scores": {
            "centering": _safe_float(s.get("centering"), 0.0),
            "surface":   _safe_float(s.get("surface"), 0.0),
            "edges":     _safe_float(s.get("edges"), 0.0),
            "corners":   _safe_float(s.get("corners"), 0.0),
            "color":     _safe_float(s.get("color"), 0.0),
        },
        "predicted_grade": _safe_float(data.get("predicted_grade"), 0.0),
        "predicted_label": str(data.get("predicted_label") or "").strip(),
        "needs_better_photos": bool(data.get("needs_better_photos", False)),
        "photo_feedback": str(data.get("photo_feedback") or "").strip(),
        "observations": data.get("observations") or [],
        "summary": str(data.get("summary") or "").strip(),
    }

def _enforce_observation_guard(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    If there are deductions but zero concrete observations, snap to 10.0 everywhere
    (prevents phantom 'minor scratch' claims).
    """
    if result.get("needs_better_photos"):
        return result
    obs = result.get("observations") or []
    has_concrete = any(isinstance(o, dict) and "category" in o for o in obs)
    if not has_concrete:
        result["scores"] = {k: 10.0 for k in ["centering","surface","edges","corners","color"]}
        result["predicted_grade"] = 10.0
        if not result.get("predicted_label"):
            result["predicted_label"] = "PSA 10 (Gem Mint)"
    return result

def grade_with_openai(front_path: Path, back_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Classify sides (must be one FRONT + one BACK, any order). If OK and quality
    is medium/high, grade; otherwise return a photo issue (no scores).
    """
    gate = _classify_images(front_path, back_path)
    sides = gate["detected_sides"]
    q = gate["image_quality"]

    # Must have exactly one front and one back (order doesn’t matter)
    pair = {sides["image_1"], sides["image_2"]}
    has_front = "front" in pair
    has_back  = "back"  in pair

    if not (has_front and has_back):
        return {
            "scores": {"centering":0.0,"surface":0.0,"edges":0.0,"corners":0.0,"color":0.0},
            "predicted_grade": 0.0,
            "predicted_label": "—",
            "needs_better_photos": True,
            "photo_feedback": "Please upload exactly one FRONT and one BACK image.",
            "summary": "",
        }

    if q not in {"medium","high"}:
        return {
            "scores": {"centering":0.0,"surface":0.0,"edges":0.0,"corners":0.0,"color":0.0},
            "predicted_grade": 0.0,
            "predicted_label": "—",
            "needs_better_photos": True,
            "photo_feedback": "Photo quality is too low (blur, glare or cropping).",
            "summary": "",
        }

    # Normalize order to FRONT then BACK
    if sides["image_1"] == "back" and sides["image_2"] == "front":
        front_path, back_path = back_path, front_path

    # Grade
    content = [{"type": "text", "text": "FRONT then BACK of the same card — grade per instructions."}]
    content.append(_img_part(front_path))
    if back_path:
        content.append(_img_part(back_path))

    resp = client.chat.completions.create(
        model=OPENAI_MODEL_GRADE,
        temperature=0.2,
        messages=[
            {"role": "system", "content": GRADE_PROMPT},
            {"role": "user", "content": content},
        ],
    )

    raw = (resp.choices[0].message.content or "{}").strip()
    try:
        data = json.loads(raw)
    except Exception:
        s, e = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[s:e+1]) if s != -1 and e != -1 and e > s else {}

    result = _normalize_grade_json(data)
    result = _enforce_observation_guard(result)
    return result