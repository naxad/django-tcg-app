# grading/ml/vision_checks.py
from __future__ import annotations
import cv2
import numpy as np
from typing import Dict, Tuple

def _read_bgr(p: str):
    img = cv2.imread(p)
    if img is None:
        raise FileNotFoundError(p)
    return img

def variance_of_laplacian(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())

def detect_blur(bgr: np.ndarray, thresh: float = 120.0) -> Tuple[bool, float]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    v = variance_of_laplacian(gray)
    return (v < thresh, v)

def detect_glare(bgr: np.ndarray, frac_thresh: float = 0.010) -> Tuple[bool, float]:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)
    # very bright & low saturation → likely glare/reflect
    glare = (V > 245) & (S < 30)
    ratio = float(glare.sum()) / float(glare.size)
    return (ratio > frac_thresh, ratio)

def detect_scribble_or_marker(bgr: np.ndarray) -> Tuple[bool, float]:
    """
    Lightweight heuristic:
      - find highly saturated dark pixels (pen ink tends to be saturated & darker)
      - OR thin edge-like strokes from Canny
      - remove small components; look for elongated/curvy blobs
    If total stroke area is above ~0.4% of the card surface, flag as scribble.
    """
    h, w = bgr.shape[:2]
    area = float(h * w)

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)

    # Saturated & not bright → candidate ink
    cand1 = (S > 90) & (V < 200)

    # Edge strokes (captures pencil/pen even when saturation is low)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 160) > 0

    mask = (cand1 | edges).astype(np.uint8) * 255

    # Clean & keep stroke-like shapes
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)), iterations=1)

    # Remove tiny specks
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros_like(mask)
    stroke_area = 0.0

    for i in range(1, num_labels):
        x, y, w0, h0, a = stats[i]
        if a < 150:   # too small to be real scribble
            continue
        ar = max(w0, h0) / max(1, min(w0, h0))  # aspect ratio
        if ar < 2.2 and a < 800:
            # small & not elongated → likely printed texture/noise; skip
            continue
        keep[labels == i] = 255
        stroke_area += float(a)

    frac = stroke_area / area
    # tune threshold to your images; 0.004 (~0.4%) works well on phone photos
    return (frac > 0.004, frac)

# grading/ml/vision_checks.py  (or keep beside openai_client.py)
import cv2
import numpy as np

import cv2
import numpy as np

def run_vision_checks_img(img_bgr):
    """
    Input: BGR np.ndarray (already warped/cropped to the card).
    Output flags + confidences (0..1):
      scribble, scribble_conf, glare, glare_conf, blur, blur_conf
    """
    out = dict(scribble=False, scribble_conf=0.0,
               glare=False, glare_conf=0.0,
               blur=False,  blur_conf=0.0)

    if img_bgr is None:
        return out

    h, w = img_bgr.shape[:2]

    # --- BLUR (variance of Laplacian) ---
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    fm = cv2.Laplacian(gray, cv2.CV_64F).var()
    BLUR_T = 140.0
    if fm < BLUR_T:
        out["blur"] = True
        out["blur_conf"] = float(np.clip((BLUR_T - fm) / BLUR_T, 0, 1))

    # --- GLARE (bright + low saturation) ---
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)
    glare_mask = (V > 242) & (S < 40)
    glare_ratio = float(glare_mask.mean())
    out["glare"] = glare_ratio > 0.02
    out["glare_conf"] = float(np.clip((glare_ratio - 0.02) / 0.10, 0, 1))

    # --- SCRIBBLE (ink-colored long curvy strokes) ---
    # ROI: middle-lower portion where scribbles tend to be (reduce art/portrait edges)
    y0, y1 = int(0.40*h), int(0.92*h)
    x0, x1 = int(0.06*w), int(0.94*w)
    roi = img_bgr[y0:y1, x0:x1]

    roi_hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    Hr, Sr, Vr = cv2.split(roi_hsv)

    # Ink colors:
    #  - Blue pen: B channel stronger; H around 90–140 in OpenCV? (Actually OpenCV H=0..179)
    #  - Black marker: very low V and low S
    # Build two masks and OR them
    blue_mask = ((Hr > 90) & (Hr < 140) & (Sr > 60) & (Vr > 40))
    black_mask = ((Vr < 60) & (Sr < 80))

    ink_mask = (blue_mask | black_mask).astype(np.uint8) * 255

    # edges inside ink regions only (avoid printed borders)
    roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(roi_gray, 70, 160)
    edges = cv2.bitwise_and(edges, edges, mask=ink_mask)
    edges = cv2.dilate(edges, np.ones((3,3), np.uint8), 1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    total_len = 0.0
    curvy_count = 0
    area_acc = 0.0

    for cnt in contours:
        if len(cnt) < 30:
            continue
        area = cv2.contourArea(cnt)
        if area < 35 or area > 6000:
            continue

        x,y,wc,hc = cv2.boundingRect(cnt)
        ar = max(wc, 1) / max(hc, 1)
        if ar < 0.8:
            ar = 1.0/ar
        if ar < 2.2:                 # need long thin strokes
            continue

        perim = cv2.arcLength(cnt, False)
        approx = cv2.approxPolyDP(cnt, 0.02*perim, False)
        if len(approx) <= 6:         # require curvature (not straight text lines)
            continue

        total_len += perim
        curvy_count += 1
        area_acc += area

    diag = np.hypot(w, h)
    stroke_score = 0.0
    if diag > 0:
        stroke_score = (total_len / (0.25*diag)) + (0.12*curvy_count)

    ink_area_ratio = float(area_acc / max(1, roi.shape[0]*roi.shape[1]))

    # Very conservative trigger:
    conf = float(np.clip(0.5*stroke_score + 6.0*ink_area_ratio, 0, 1))
    out["scribble_conf"] = conf
    out["scribble"] = (stroke_score > 1.15 and curvy_count >= 3 and ink_area_ratio > 0.0025)

    return out


def run_vision_checks(path: str):
    img = cv2.imread(path)
    return run_vision_checks_img(img)
