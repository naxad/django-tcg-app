# grading/ml/dataset.py
from pathlib import Path
import pandas as pd
from PIL import Image
from torch.utils.data import Dataset

class CardPairDataset(Dataset):
    """
    Reads metadata.csv with columns:
      front_path, back_path, centering, surface, edges, corners, color, overall_grade
    """
    def __init__(self, csv_path, transform=None):
        self.df = pd.read_csv(csv_path)
        self.transform = transform
        # normalize paths if they’re absolute in CSV
        self.df["front_path"] = self.df["front_path"].apply(lambda p: str(Path(p)))
        self.df["back_path"]  = self.df["back_path"].apply(lambda p: str(Path(p)))

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        front = Image.open(row["front_path"]).convert("RGB")
        back  = Image.open(row["back_path"]).convert("RGB")
        sample = {"front": front, "back": back}
        if self.transform:
            sample = self.transform(sample)

        y = {
            "centering": float(row.get("centering", 0) or 0),
            "surface":   float(row.get("surface", 0) or 0),
            "edges":     float(row.get("edges", 0) or 0),
            "corners":   float(row.get("corners", 0) or 0),
            "color":     float(row.get("color", 0) or 0),
            "overall":   float(row.get("overall_grade", row.get("predicted_grade", 0)) or 0),
        }
        return sample, y
