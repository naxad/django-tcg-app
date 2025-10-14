# grading/ml/cv_inference.py
from __future__ import annotations
from pathlib import Path
import os, uuid
from typing import Union, Tuple

import numpy as np
import cv2 as cv
import torch
from PIL import Image

from grading.ml.preprocess.rectify import rectify_card
from grading.ml.preprocess.color import normalize_color
from grading.ml.preprocess.quality import basic_quality_checks

from .model import PairRegressor
from .transforms import PairTransform  # same transform used in training

# ---------- config ----------
DEBUG_DIR = os.environ.get("GRADING_DEBUG_DIR", "debug_runs")
TARGET_MIN_SIDE = 1000        # where we *want* the rectified crop to be
SOFT_MIN_SIDE   = 700         # accept anything this size and up, then upscale
MIN_BLUR        = 110.0       # softer than before (was 140)
MAX_GLARE       = 0.18        # softer than before (was 0.03)

os.makedirs(DEBUG_DIR, exist_ok=True)


# ---------- helpers ----------
def _to_bgr(img_like: Union[np.ndarray, bytes, bytearray, Path, str, Image.Image]) -> np.ndarray:
    if isinstance(img_like, np.ndarray):
        if img_like.ndim == 3 and img_like.shape[2] == 3:
            return img_like[..., ::-1].copy()  # assume RGB -> BGR
        raise ValueError("Unsupported ndarray image shape.")
    if isinstance(img_like, (bytes, bytearray)):
        data = np.frombuffer(img_like, np.uint8)
        bgr = cv.imdecode(data, cv.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("Could not decode image bytes.")
        return bgr
    p = Path(img_like) if isinstance(img_like, (str, Path)) else None
    if p is not None:
        bgr = cv.imread(str(p), cv.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"Could not read image at {p}.")
        return bgr
    if isinstance(img_like, Image.Image):
        rgb = np.array(img_like.convert("RGB"))
        return cv.cvtColor(rgb, cv.COLOR_RGB2BGR)
    raise ValueError("Unsupported image input type.")


def _fallback_rectify(bgr: np.ndarray, ratio: float = 88/63) -> np.ndarray | None:
    """
    Extremely simple 'largest rectangle' fallback if rectify_card() fails.
    Returns a perspective-warped BGR image with the Pokémon aspect (88x63).
    """
    h, w = bgr.shape[:2]
    gray = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
    gray = cv.GaussianBlur(gray, (5, 5), 0)
    edges = cv.Canny(gray, 60, 160)
    edges = cv.dilate(edges, np.ones((3,3), np.uint8), 1)

    cnts, _ = cv.findContours(edges, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None

    cnt = max(cnts, key=cv.contourArea)
    if cv.contourArea(cnt) < 0.05 * (w * h):
        # too small to be a full card
        return None

    rect = cv.minAreaRect(cnt)
    box = cv.boxPoints(rect).astype(np.float32)

    # order the box points TL, TR, BR, BL
    def _order(pts):
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1).reshape(-1)
        tl = pts[np.argmin(s)]
        br = pts[np.argmax(s)]
        tr = pts[np.argmin(diff)]
        bl = pts[np.argmax(diff)]
        return np.array([tl, tr, br, bl], dtype=np.float32)

    box = _order(box)

    # choose destination size honoring the card aspect
    # short side aligned with width (63) and long with height (88)
    # but allow rotation: figure out which is longer in source box
    w1 = np.linalg.norm(box[1] - box[0])
    w2 = np.linalg.norm(box[2] - box[3])
    h1 = np.linalg.norm(box[3] - box[0])
    h2 = np.linalg.norm(box[2] - box[1])
    src_w = max(w1, w2)
    src_h = max(h1, h2)

    if src_h >= src_w:
        dst_h = max(int(TARGET_MIN_SIDE), int(src_h))
        dst_w = int(dst_h / ratio)
    else:
        dst_w = max(int(TARGET_MIN_SIDE), int(src_w))
        dst_h = int(dst_w * ratio)

    dst = np.array([[0,0],[dst_w-1,0],[dst_w-1,dst_h-1],[0,dst_h-1]], dtype=np.float32)
    M = cv.getPerspectiveTransform(box, dst)
    warped = cv.warpPerspective(bgr, M, (dst_w, dst_h), flags=cv.INTER_CUBIC)
    return warped


def _maybe_upscale(img: np.ndarray, min_side_target: int = TARGET_MIN_SIDE) -> np.ndarray:
    h, w = img.shape[:2]
    m = min(h, w)
    if m >= min_side_target:
        return img
    scale = float(min_side_target) / float(m)
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    return cv.resize(img, (new_w, new_h), interpolation=cv.INTER_CUBIC)


def preprocess_one(bgr: np.ndarray, tag: str) -> Tuple[np.ndarray | None, dict]:
    """
    rectify → color normalize → quality (soft gate) → optional upscale
    Saves debug frames. Returns (image_or_None, report).
    """
    uid_tag = tag
    # 1) try main rectifier
    rect = rectify_card(bgr)
    if rect is None or rect.image is None:
        # 2) fallback rectifier
        rect_img = _fallback_rectify(bgr)
        if rect_img is None:
            print(f"[CVGrader] {uid_tag}: rectify failed (no card quadrilateral).")
            return None, {"ok": False, "reason": "Could not detect a reliable card quadrilateral."}
        image = rect_img
    else:
        image = rect.image

    h, w = image.shape[:2]
    print(f"[CVGrader] {uid_tag}: rectified size = {w}x{h}")
    cv.imwrite(os.path.join(DEBUG_DIR, f"{tag}_rect_raw.jpg"), image)

    # 3) color normalize
    norm = normalize_color(image)
    cv.imwrite(os.path.join(DEBUG_DIR, f"{tag}_rect_norm.jpg"), norm)

    # 4) quality (softer thresholds)
    qr = basic_quality_checks(norm, min_side=SOFT_MIN_SIDE, min_blur=MIN_BLUR, max_glare=MAX_GLARE)
    print(f"[CVGrader] {uid_tag}: quality ok={qr.ok} blur={qr.blur_var:.1f} glare={qr.glare_ratio:.4f} min_side={qr.min_side}")

    # 5) upscale if needed (even if quality said low min_side)
    norm = _maybe_upscale(norm, TARGET_MIN_SIDE)

    # We *continue* even if quality failed; caller decides whether to gate.
    report = {
        "ok": bool(qr.ok),
        "reason": qr.reason,
        "blur_var": float(qr.blur_var),
        "glare_ratio": float(qr.glare_ratio),
        "min_side": int(qr.min_side),
    }
    return norm, report


# ---------- main wrapper ----------
class CVGrader:
    """
    Unified inference wrapper with robust fallback + debug prints.
    """
    def __init__(self,
                 weights_path: Union[str, Path] = "grading/ml/models/cardgrader_v1.pt",
                 size: int = 384,
                 device: str | None = None) -> None:

        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model = PairRegressor().to(self.device)
        self.model.load_state_dict(torch.load(str(weights_path), map_location=self.device))
        self.model.eval()
        self.tf = PairTransform(train=False, size=size)

    @torch.inference_mode()
    def predict(self,
                front: Union[np.ndarray, bytes, bytearray, Path, str, Image.Image],
                back: Union[np.ndarray, bytes, bytearray, Path, str, Image.Image, None] = None
                ) -> dict:

        uid = uuid.uuid4().hex[:8]
        print(f"[CVGrader] predict uid={uid}")

        # --- load to BGR ---
        front_bgr = _to_bgr(front)
        back_bgr  = _to_bgr(back) if back is not None else None
        print(f"[CVGrader] {uid}: front_bgr shape={front_bgr.shape}; back={'yes' if back_bgr is not None else 'no'}")

        # --- preprocess (rectify + normalize + quality) ---
        front_proc, qf = preprocess_one(front_bgr, f"{uid}_front")
        if front_proc is None:
            return {
                "success": False, "stage": "preprocess_front",
                "message": qf.get("reason", "Unknown failure")
            }

        back_proc, qb = (None, {"ok": False, "reason": "No back image provided."})
        if back_bgr is not None:
            back_proc, qb = preprocess_one(back_bgr, f"{uid}_back")
            if back_proc is None:
                back_proc = front_proc  # keep shape/channel expectations

        # Gate only on *very* bad front; otherwise proceed and show warnings on the page
        if not qf.get("ok", True) and "min side" not in qf.get("reason","").lower():
            return {
                "success": False, "stage": "quality_front",
                "message": qf.get("reason", "Front failed quality checks")
            }

        if back_proc is None:
            back_proc = front_proc

        # --- to PIL RGB for PairTransform ---
        front_pil = Image.fromarray(cv.cvtColor(front_proc, cv.COLOR_BGR2RGB))
        back_pil  = Image.fromarray(cv.cvtColor(back_proc,  cv.COLOR_BGR2RGB))

        sample = {"front": front_pil, "back": back_pil}
        x = self.tf(sample)["pair"].unsqueeze(0).to(self.device)  # [1, 6, H, W]
        x_np = x.detach().cpu().numpy()
        print(f"[CVGrader] {uid}: tensor x shape={tuple(x.shape)} dtype={x.dtype} "
              f"min={x_np.min():.4f} max={x_np.max():.4f} mean={x_np.mean():.4f}")

        out = self.model(x)[0].detach().cpu().tolist()  # [6] -> [cent, surface, edges, corners, color, overall]
        keys = ["centering", "surface", "edges", "corners", "color", "overall"]

        # --- clamp & pack
        def clamp(v: float) -> float:
            return float(max(0.0, min(10.0, v)))
        scores = {k: clamp(v) for k, v in zip(keys, out)}

        # ========= Edge fallback (analytical) =========
        # Use the rectified FRONT image (better signal) to estimate chips along the border band.
        def edge_fallback_score(rect_bgr: np.ndarray, band: int = 3) -> tuple[float, float]:
            """
            Returns (score_0_10, chip_ratio).
            chip_ratio = fraction of border-band pixels that deviate strongly from local median
            """
            g = cv.cvtColor(rect_bgr, cv.COLOR_BGR2GRAY)
            h, w = g.shape
            band = max(2, min(6, band))

            # border mask (outer band px) and a just-inside band for local reference
            border = np.zeros_like(g, np.uint8)
            border[:band, :] = 1; border[-band:, :] = 1; border[:, :band] = 1; border[:, -band:] = 1

            inner = np.zeros_like(g, np.uint8)
            inner[band*2:h-band*2, band*2:w-band*2] = 1

            # local reference: robust central median
            ref = np.median(g[inner > 0]).astype(np.float32)
            diff = np.abs(g.astype(np.float32) - ref)
            chip_mask = (diff > 28) & (border > 0)  # 28 is a good first cut; tune on your photos

            chip_ratio = float(chip_mask.sum()) / float(border.sum() + 1e-6)

            # Map chip_ratio → score: 0.00 → 10, 0.5% → ~9, 1% → ~8, 2% → ~6, 5% → ~0
            # Adjust k to taste
            k = 180.0   # higher k makes it more forgiving
            score = 10.0 * max(0.0, 1.0 - k * chip_ratio)
            return float(score), float(chip_ratio)

        # Compute fallback on the *front* rectified image
        ef_score, ef_ratio = edge_fallback_score(front_proc, band=3)

        # Decide how to combine
        # ENV knobs:
        #   EDGES_FALLBACK_MODE = "override" | "average" | "off"
        #   EDGES_OVERRIDE_THRESHOLD = 0.5  (network edges below this triggers help)
        mode = os.environ.get("EDGES_FALLBACK_MODE", "override").lower()
        thr  = float(os.environ.get("EDGES_OVERRIDE_THRESHOLD", "0.5"))

        edges_before = scores["edges"]
        if mode != "off" and edges_before < thr:
            if mode == "average":
                scores["edges"] = clamp(0.5 * (edges_before + ef_score))
            else:  # override
                scores["edges"] = clamp(ef_score)

        # --- save useful debug tiles ---
        try:
            uid = uid  # from above
            dbg_base = os.path.join(DEBUG_DIR, f"{uid}_edges")
            os.makedirs(DEBUG_DIR, exist_ok=True)
            # full rect for visual inspection
            cv.imwrite(dbg_base + "_front_rect.jpg", front_proc)
            # visualize border band & chip mask
            g = cv.cvtColor(front_proc, cv.COLOR_BGR2GRAY)
            h, w = g.shape
            band = 3
            border = np.zeros_like(g, np.uint8)
            border[:band, :] = 255; border[-band:, :] = 255; border[:, :band] = 255; border[:, -band:] = 255
            ref = np.median(g[band*2:h-band*2, band*2:w-band*2]).astype(np.float32)
            chip = (np.abs(g.astype(np.float32) - ref) > 28).astype(np.uint8) * 255
            chip_border = cv.bitwise_and(chip, border)
            vis = front_proc.copy()
            vis[chip_border > 0] = (0, 0, 255)  # mark chips in red
            cv.imwrite(dbg_base + "_chip_overlay.jpg", vis)
        except Exception:
            pass

        # ========= Overall calculation guard =========
        # Keep your “zero-hard-fail” rule configurable so one bad head doesn’t auto-zero during debugging.
        zero_hard_fail = os.environ.get("OVERALL_ZERO_IF_ANY_ZERO", "true").lower() == "true"
        if zero_hard_fail and any(scores[k] <= 0.05 for k in ["centering","surface","edges","corners","color"]):
            scores["overall"] = 0.0
        else:
            # If your model's overall looks broken, use average as a temp fallback
            if scores["overall"] < 0.5:
                scores["overall"] = clamp(
                    (scores["centering"] + scores["surface"] + scores["edges"] +
                     scores["corners"] + scores["color"]) / 5.0
                )

        return {
            "success": True,
            "stage": "ok",
            "debug": {
                "front_blur": qf.get("blur_var", 0.0),
                "front_glare": qf.get("glare_ratio", 0.0),
                "net_edges": float(edges_before),
                "fallback_edges": float(ef_score),
                "chip_ratio": float(ef_ratio),
                "overall_zero_hard_fail": zero_hard_fail,
            },
            **{k: float(scores[k]) for k in keys},
        }
