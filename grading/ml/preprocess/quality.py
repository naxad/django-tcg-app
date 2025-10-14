# grading/ml/preprocess/quality.py
from __future__ import annotations
from dataclasses import dataclass
import cv2 as cv
import numpy as np

__all__ = ["QualityReport", "basic_quality_checks"]

@dataclass
class QualityReport:
    ok: bool
    reason: str = ""
    blur_var: float = 0.0
    glare_ratio: float = 0.0
    min_side: int = 0

def _variance_of_laplacian(gray: np.ndarray) -> float:
    return float(cv.Laplacian(gray, cv.CV_64F).var())

def _glare_fraction(bgr: np.ndarray, thr: int = 245) -> float:
    gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
    return float((gray >= thr).sum()) / float(gray.size)

def basic_quality_checks(
    rectified: np.ndarray,
    min_side: int = 1000,
    min_blur: float = 140.0,
    max_glare: float = 0.03,
) -> QualityReport:
    h, w = rectified.shape[:2]
    gray = cv.cvtColor(rectified, cv.COLOR_BGR2GRAY)
    blur = _variance_of_laplacian(gray)
    glare = _glare_fraction(rectified)

    ms = min(h, w)
    if ms < min_side:
        return QualityReport(
            ok=False,
            reason=f"Low resolution (min side {ms} < {min_side})",
            blur_var=blur,
            glare_ratio=glare,
            min_side=ms,
        )
    if blur < min_blur:
        return QualityReport(
            ok=False,
            reason=f"Image is blurry (Laplacian var {blur:.1f} < {min_blur})",
            blur_var=blur,
            glare_ratio=glare,
            min_side=ms,
        )
    if glare > max_glare:
        return QualityReport(
            ok=False,
            reason=f"Glare too high ({glare*100:.1f}% > {max_glare*100:.1f}%)",
            blur_var=blur,
            glare_ratio=glare,
            min_side=ms,
        )
    return QualityReport(True, blur_var=blur, glare_ratio=glare, min_side=ms)
