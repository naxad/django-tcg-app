# grading/openai_client.py
from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
from pathlib import Path
from typing import Dict, Optional, Any

import cv2
import numpy as np
from PIL import Image
from openai import OpenAI

# ---------------------------
# Config
# ---------------------------
OPENAI_MODEL_GRADE = os.getenv("OPENAI_GRADING_MODEL", "gpt-4o")
OPENAI_MODEL_CLASS = os.getenv("OPENAI_CLASSIFIER_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Enforce upload order (front first, back second)
REQUIRE_FRONT_FIRST = True

# CV blending (keep OFF until you train on more data)
BLEND_CV_ALPHA = float(os.getenv("CV_BLEND_ALPHA", "0.0"))  # 0.0 = disabled
CV_WEIGHTS = os.getenv("CARDGRADER_WEIGHTS", "grading/ml/models/cardgrader_v1.pt")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------------------------
# Helpers
# ---------------------------
def _file_to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "image/jpeg"
    b64 = base64.b64encode(Path(path).read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def _img_part(path: Path) -> Dict[str, Any]:
    """Build an image part from a file path (no preprocessing)."""
    return {"type": "image_url", "image_url": {"url": _file_to_data_url(path)}}

def _img_part_from_data_url(data_url: str) -> Dict[str, Any]:
    """Build an image part from a data URL (used after preprocessing)."""
    return {"type": "image_url", "image_url": {"url": data_url}}

def _safe_float(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d

# ---------------------------
# Stage 1: gating / classification
# ---------------------------
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

# ---------------------------
# Stage 2: grading prompt
# ---------------------------
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

# ---------------------------
# Preprocess: crop/deskew card
# ---------------------------
def _to_data_url_from_pil(img: Image.Image, mime="image/jpeg") -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def _order_points(pts):
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]            # top-left
    rect[2] = pts[np.argmax(s)]            # bottom-right
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]         # top-right
    rect[3] = pts[np.argmax(diff)]         # bottom-left
    return rect

def _warp_card(img_bgr, target_h=896, target_w=640):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5,5), 0)
    edges = cv2.Canny(gray, 40, 120)
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    cnt = max(cnts, key=cv2.contourArea)
    peri = cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
    if len(approx) != 4:
        return None
    pts = approx.reshape(4,2).astype("float32")
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect
    wA = np.linalg.norm(br - bl)
    wB = np.linalg.norm(tr - tl)
    hA = np.linalg.norm(tr - br)
    hB = np.linalg.norm(tl - bl)
    maxW = int(max(wA, wB))
    maxH = int(max(hA, hB))
    dst = np.array([[0,0],[maxW-1,0],[maxW-1,maxH-1],[0,maxH-1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    warp = cv2.warpPerspective(img_bgr, M, (maxW, maxH))
    warp = cv2.resize(warp, (target_w, target_h), interpolation=cv2.INTER_CUBIC)
    return warp

def _preprocess_card_to_data_url(path: Path) -> str:
    img_bgr = cv2.imread(str(path))
    if img_bgr is None:
        return _file_to_data_url(path)
    warped = _warp_card(img_bgr)
    if warped is None:
        return _file_to_data_url(path)
    # simple upside-down heuristic (optional)
    top = warped[:80,:,:].mean(); bot = warped[-80:,:,:].mean()
    if bot + 10 < top:
        warped = cv2.rotate(warped, cv2.ROTATE_180)
    pil = Image.fromarray(cv2.cvtColor(warped, cv2.COLOR_BGR2RGB))
    return _to_data_url_from_pil(pil)

# ---------------------------
# Main entry
# ---------------------------
def grade_with_openai(front_path: Path, back_path: Optional[Path] = None) -> Dict[str, Any]:
    """Gate + crop + LLM grade (+ optional CV blend)."""

    # 1) Gate: sides & quality
    gate = _classify_images(front_path, back_path)
    sides = gate.get("detected_sides", {})
    q = (gate.get("image_quality") or "low").lower()

    # Enforce order
    if REQUIRE_FRONT_FIRST:
        if sides.get("image_1") != "front" or sides.get("image_2") != "back":
            return {
                "scores": {"centering":0.0,"surface":0.0,"edges":0.0,"corners":0.0,"color":0.0},
                "predicted_grade": 0.0,
                "predicted_label": "—",
                "needs_better_photos": True,
                "photo_feedback": "Upload the FRONT image first and the BACK image second.",
                "summary": "",
            }
    else:
        pair = {sides.get("image_1"), sides.get("image_2")}
        if not ("front" in pair and "back" in pair):
            return {
                "scores": {"centering":0.0,"surface":0.0,"edges":0.0,"corners":0.0,"color":0.0},
                "predicted_grade": 0.0,
                "predicted_label": "—",
                "needs_better_photos": True,
                "photo_feedback": "Please upload exactly one FRONT and one BACK image.",
                "summary": "",
            }
        if sides.get("image_1") == "back" and sides.get("image_2") == "front":
            front_path, back_path = back_path, front_path

    if q not in {"medium","high"}:
        return {
            "scores": {"centering":0.0,"surface":0.0,"edges":0.0,"corners":0.0,"color":0.0},
            "predicted_grade": 0.0,
            "predicted_label": "—",
            "needs_better_photos": True,
            "photo_feedback": "Photo quality is too low (blur, glare or cropping).",
            "summary": "",
        }

    # 2) Preprocess → data URLs
    f_url = _preprocess_card_to_data_url(front_path)
    b_url = _preprocess_card_to_data_url(back_path) if back_path else None

    # 3) LLM grade
    content = [{"type": "text", "text": "FRONT then BACK of the same card — grade per instructions."}]
    content.append(_img_part_from_data_url(f_url))
    if b_url:
        content.append(_img_part_from_data_url(b_url))

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

    # 4) Optional CV blend (OFF by default)
    if BLEND_CV_ALPHA > 0.0 and os.path.exists(CV_WEIGHTS) and back_path:
        try:
            from grading.ml.cv_inference import CVGrader
            cv = CVGrader(weights_path=CV_WEIGHTS)
            cv_pred = cv.predict(front_path, back_path)  # dict with keys: centering,...,overall
            a = float(BLEND_CV_ALPHA)
            for k in ["centering","surface","edges","corners","color"]:
                result["scores"][k] = (1-a)*result["scores"][k] + a*cv_pred[k]
            result["predicted_grade"] = (1-a)*result["predicted_grade"] + a*cv_pred["overall"]
        except Exception as e:
            # fail open: keep LLM-only if CV load/infer fails
            pass

    return result
