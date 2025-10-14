# grading/ml/preprocess/color.py
from __future__ import annotations
import numpy as np
import cv2 as cv

def gray_world_awb(bgr: np.ndarray) -> np.ndarray:
    # simple, robust AWB for TCG shots
    eps = 1e-6
    mean = bgr.reshape(-1,3).mean(axis=0) + eps
    scale = mean.mean() / mean
    awb = np.clip(bgr * scale, 0, 255).astype(np.uint8)
    return awb

def gentle_tonemap(bgr: np.ndarray, gamma=1.05) -> np.ndarray:
    # very light gamma + clip
    x = bgr.astype(np.float32) / 255.0
    x = np.power(x, 1.0/gamma)
    x = np.clip(x, 0, 1)
    return (x * 255.0 + 0.5).astype(np.uint8)

def normalize_color(bgr: np.ndarray) -> np.ndarray:
    out = gray_world_awb(bgr)
    out = gentle_tonemap(out)
    return out
