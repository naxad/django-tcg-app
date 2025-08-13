# grading/ml/transforms.py
import random
import torchvision.transforms as T
import torch

class PairTransform:
    """
    Apply identical spatial transforms to front & back, then convert to tensors.
    Output: {"pair": Tensor shape [6,H,W]} by channel-concat (front[3]+back[3]).
    """
    def __init__(self, train=True, size=384):
        augs = []
        if train:
            augs += [
                T.RandomResizedCrop(size, scale=(0.9, 1.0), ratio=(0.95, 1.05)),
                T.RandomHorizontalFlip(p=0.1),
            ]
        else:
            augs += [T.Resize(size), T.CenterCrop(size)]
        self.aug = T.Compose(augs)
        self.to_tensor = T.Compose([
            T.ToTensor(),
            T.Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]),
        ])

    def __call__(self, sample):
        f = self.aug(sample["front"])
        b = self.aug(sample["back"])
        f = self.to_tensor(f)
        b = self.to_tensor(b)
        # channel-concat → [6,H,W]
        pair = torch.cat([f, b], dim=0)
        return {"pair": pair}
