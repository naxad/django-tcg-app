# grading/ml/model.py
import torch
import torch.nn as nn
from torchvision.models import resnet18

class PairRegressor(nn.Module):
    """
    Simple baseline:
      - Two separate ResNet18 branches (shared weights=False) OR
      - One branch that accepts 6 channels (simpler)
    We’ll do the 6-channel trick for speed.
    """
    def __init__(self):
        super().__init__()
        base = resnet18(weights=None)
        # adapt first conv to 6 channels
        w = base.conv1.weight
        base.conv1 = nn.Conv2d(6, 64, kernel_size=7, stride=2, padding=3, bias=False)
        # init new conv by repeating original weights
        base.conv1.weight = nn.Parameter(torch.cat([w, w], dim=1))
        self.backbone = base
        self.head = nn.Sequential(
            nn.Linear(1000, 512),
            nn.ReLU(inplace=True),
            nn.Dropout(0.2),
            nn.Linear(512, 6)  # five subscores + overall
        )

    def forward(self, x):  # x: [B,6,H,W]
        feat = self.backbone(x)
        out  = self.head(feat)  # [B,6]
        # clamp to [0,10]
        return torch.clamp(out, 0.0, 10.0)
