# grading/ml/cv_inference.py
from pathlib import Path
from PIL import Image
import torch
import torchvision.transforms as T
from .model import PairRegressor

class CVGrader:
    def __init__(self, weights_path="models/cardgrader_v1.pt", size=384, device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = PairRegressor()
        self.model.load_state_dict(torch.load(weights_path, map_location=self.device))
        self.model.to(self.device).eval()
        self.tf = T.Compose([
            T.Resize(size),
            T.CenterCrop(size),
            T.ToTensor(),
            T.Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]),
        ])

    def predict(self, front_path: Path, back_path: Path):
        f = self.tf(Image.open(front_path).convert("RGB"))
        b = self.tf(Image.open(back_path).convert("RGB"))
        x = torch.cat([f,b], dim=0).unsqueeze(0).to(self.device)  # [1,6,H,W]
        with torch.no_grad():
            out = self.model(x).cpu().squeeze(0).tolist()  # [6]
        keys = ["centering","surface","edges","corners","color","overall"]
        return dict(zip(keys, out))
