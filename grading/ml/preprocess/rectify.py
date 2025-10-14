# grading/ml/preprocess/rectify.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple
import cv2 as cv
import numpy as np
import os

DEBUG_DIR = os.environ.get("GRADING_DEBUG_DIR", "debug_runs")

@dataclass
class RectResult:
    image: np.ndarray  # warped BGR

def _order_pts(pts: np.ndarray) -> np.ndarray:
    # pts: (4,2)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype=np.float32)

def _warp(img: np.ndarray, quad: np.ndarray, out_h: int = 1100) -> np.ndarray:
    # Card aspect 63x88 (w:h). For a given out_h, compute out_w.
    aspect = 63.0 / 88.0
    out_w = int(round(out_h * aspect))
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype=np.float32)
    M = cv.getPerspectiveTransform(_order_pts(quad.astype(np.float32)), dst)
    return cv.warpPerspective(img, M, (out_w, out_h), flags=cv.INTER_CUBIC)

def _find_quad(img: np.ndarray) -> Optional[np.ndarray]:
    """
    Try to find a 4-point contour that looks like a Pokémon card.
    Two passes: (1) gentle thresholds, (2) aggressive.
    Returns quad as (4,2) float32 if found, else None.
    """
    H, W = img.shape[:2]
    min_area = 0.20 * (H * W)      # cards occupy ≥ ~20% in your UI photos
    max_area = 0.95 * (H * W)

    def pass_once(blur_ksize: int, canny_lo: int, canny_hi: int, close_ks: int, dil_iter: int):
        gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
        gray = cv.GaussianBlur(gray, (blur_ksize, blur_ksize), 0)
        edges = cv.Canny(gray, canny_lo, canny_hi)
        kernel = cv.getStructuringElement(cv.MORPH_RECT, (close_ks, close_ks))
        edges = cv.dilate(edges, kernel, iterations=dil_iter)
        edges = cv.morphologyEx(edges, cv.MORPH_CLOSE, kernel, iterations=1)

        contours, _ = cv.findContours(edges, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv.contourArea, reverse=True)

        overlay = cv.cvtColor(edges, cv.COLOR_GRAY2BGR)
        for i, c in enumerate(contours[:10]):
            area = cv.contourArea(c)
            if area < min_area or area > max_area:
                continue
            peri = cv.arcLength(c, True)
            approx = cv.approxPolyDP(c, 0.02 * peri, True)  # 2% approx, tweak if needed
            if len(approx) == 4 and cv.isContourConvex(approx):
                quad = approx.reshape(-1, 2).astype(np.float32)
                return quad, overlay
            # draw for debugging
            cv.drawContours(overlay, [c], -1, (0, 255, 255), 2)
        return None, overlay

    # Pass 1: normal
    quad, overlay = pass_once(5, 50, 140, 5, 1)
    if quad is not None:
        cv.imwrite(os.path.join(DEBUG_DIR, "rectify_pass1_overlay.jpg"), overlay)
        return quad

    # Pass 2: more aggressive
    quad, overlay = pass_once(7, 20, 200, 7, 2)
    cv.imwrite(os.path.join(DEBUG_DIR, "rectify_pass2_overlay.jpg"), overlay)
    return quad

def rectify_card(bgr: np.ndarray) -> Optional[RectResult]:
    """
    Detect the card quadrilateral and warp it to a canonical aspect.
    Returns None if no convincing quad found.
    """
    quad = _find_quad(bgr)
    if quad is None:
        return None
    warped = _warp(bgr, quad, out_h=1100)
    return RectResult(image=warped)
