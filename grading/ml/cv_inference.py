# grading/ml/cv_inference.py
from __future__ import annotations
from pathlib import Path
import torch
from PIL import Image

from .model import PairRegressor
from .transforms import PairTransform  # same transform used in training

class CVGrader:
    """
    Lightweight inference wrapper for the pair regressor.
    Uses the same eval transform as training (PairTransform(train=False)).
    """
    def __init__(self, weights_path: str | Path = "grading/ml/models/cardgrader_v1.pt",
                 size: int = 384, device: str | None = None) -> None:
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model = PairRegressor().to(self.device)
        self.model.load_state_dict(torch.load(str(weights_path), map_location=self.device))
        self.model.eval()
        self.tf = PairTransform(train=False, size=size)

    @torch.inference_mode()
    def predict(self, front_path: Path, back_path: Path | None) -> dict:
        # Fallback: if back missing, reuse front (keeps tensor shape)
        front = Image.open(front_path).convert("RGB")
        back  = Image.open(back_path).convert("RGB") if back_path else front

        # Match training preprocessing exactly
        sample = {"front": front, "back": back}
        x = self.tf(sample)["pair"].unsqueeze(0).to(self.device)  # [1,6,H,W]

        out = self.model(x)[0].detach().cpu().tolist()  # [6]
        keys = ["centering","surface","edges","corners","color","overall"]

        # Clamp to 0..10 just in case
        def clamp(v): return float(max(0.0, min(10.0, v)))
        return {k: clamp(v) for k, v in zip(keys, out)}
