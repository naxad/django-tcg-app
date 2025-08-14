# grading/ml/train.py
from __future__ import annotations
import argparse, json, math, os, random
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split
from tqdm import tqdm

# Run this from your project root:
#   python grading/ml/train.py --csv dataset/metadata.csv
# Import using package paths so it works from project root.
from grading.ml.dataset import CardPairDataset
from grading.ml.transforms import PairTransform
from grading.ml.model import PairRegressor
import torch

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Using device: ", device)


# -----------------------------
# utils
# -----------------------------
def set_seed(seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def stack_targets(y_dict: dict) -> torch.Tensor:
    """
    y_dict has plain Python lists or tensors for each head.
    Return [B, 6] in the fixed order below.
    """
    return torch.stack(
        [
            torch.as_tensor(y_dict["centering"]),
            torch.as_tensor(y_dict["surface"]),
            torch.as_tensor(y_dict["edges"]),
            torch.as_tensor(y_dict["corners"]),
            torch.as_tensor(y_dict["color"]),
            torch.as_tensor(y_dict["overall"]),
        ],
        dim=1,
    ).float()


def mae_per_head(pred: torch.Tensor, tgt: torch.Tensor) -> dict:
    """
    pred, tgt: [B,6]
    """
    heads = ["centering", "surface", "edges", "corners", "color", "overall"]
    out = {}
    with torch.no_grad():
        for i, k in enumerate(heads):
            out[k] = torch.mean(torch.abs(pred[:, i] - tgt[:, i])).item()
    return out


# -----------------------------
# training loop
# -----------------------------
def train_one_epoch(model, loader, device, optimizer, loss_fn, grad_clip=None):
    model.train()
    total_loss = 0.0
    total_batches = 0
    total_mae = {k: 0.0 for k in ["centering","surface","edges","corners","color","overall"]}

    pbar = tqdm(loader, desc="train", leave=False)
    for batch in pbar:
        x = batch[0]["pair"].to(device)  # [B,6,H,W]
        y = stack_targets(batch[1]).to(device)  # [B,6]

        optimizer.zero_grad()
        pred = model(x)  # [B,6]
        loss = loss_fn(pred, y)
        loss.backward()

        if grad_clip:
            torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)

        optimizer.step()

        total_loss += loss.item() * x.size(0)
        total_batches += x.size(0)

        maes = mae_per_head(pred.detach(), y)
        for k, v in maes.items():
            total_mae[k] += v * x.size(0)

        pbar.set_postfix(loss=f"{loss.item():.4f}")

    avg_loss = total_loss / max(1, total_batches)
    avg_mae = {k: v / max(1, total_batches) for k, v in total_mae.items()}
    return avg_loss, avg_mae


@torch.inference_mode()
def validate(model, loader, device, loss_fn):
    model.eval()
    total_loss = 0.0
    total_batches = 0
    total_mae = {k: 0.0 for k in ["centering","surface","edges","corners","color","overall"]}

    pbar = tqdm(loader, desc="valid", leave=False)
    for batch in pbar:
        x = batch[0]["pair"].to(device)
        y = stack_targets(batch[1]).to(device)

        pred = model(x)
        loss = loss_fn(pred, y)

        total_loss += loss.item() * x.size(0)
        total_batches += x.size(0)

        maes = mae_per_head(pred, y)
        for k, v in maes.items():
            total_mae[k] += v * x.size(0)

        pbar.set_postfix(loss=f"{loss.item():.4f}")

    avg_loss = total_loss / max(1, total_batches)
    avg_mae = {k: v / max(1, total_batches) for k, v in total_mae.items()}
    return avg_loss, avg_mae


# -----------------------------
# main
# -----------------------------
def main(args):
    set_seed(args.seed)
    device = torch.device(args.device if torch.cuda.is_available() or args.device == "cpu" else "cpu")
    print(f"Using device: {device}")

    # dataset & split
    full = CardPairDataset(args.csv, transform=PairTransform(train=True, size=args.size))
    n = len(full)
    if n < 8:
        raise SystemExit("Not enough rows to train. Collect more samples first. (have: %d)" % n)

    val_size = max(2, int(n * args.val_split))
    train_size = n - val_size
    train_ds, val_ds = random_split(full, [train_size, val_size], generator=torch.Generator().manual_seed(args.seed))

    # distinct train/val transforms
    train_ds.dataset.transform = PairTransform(train=True,  size=args.size)
    val_ds.dataset.transform   = PairTransform(train=False, size=args.size)

    train_loader = DataLoader(train_ds, batch_size=args.batch, shuffle=True,
                              num_workers=args.workers, pin_memory=True)
    val_loader   = DataLoader(val_ds,   batch_size=args.batch, shuffle=False,
                              num_workers=args.workers, pin_memory=True)

    # model / opt
    model = PairRegressor().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, args.epochs))
    loss_fn = nn.SmoothL1Loss(beta=0.5)

    # saving
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "cardgrader_v1.pt"
    info_path = out_dir / "model_info.json"

    best_val = float("inf")
    patience_left = args.patience

    for epoch in range(1, args.epochs + 1):
        print(f"\nEpoch {epoch}/{args.epochs}")

        tr_loss, tr_mae = train_one_epoch(model, train_loader, device, optimizer, loss_fn, grad_clip=args.grad_clip)
        va_loss, va_mae = validate(model, val_loader, device, loss_fn)
        scheduler.step()

        print(f"  train: loss={tr_loss:.4f}  MAE={ {k: round(v,3) for k,v in tr_mae.items()} }")
        print(f"  valid: loss={va_loss:.4f}  MAE={ {k: round(v,3) for k,v in va_mae.items()} }")

        improved = va_loss < best_val
        if improved:
            best_val = va_loss
            patience_left = args.patience
            torch.save(model.state_dict(), ckpt_path)
            with open(info_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "image_size": args.size,
                        "val_loss": best_val,
                        "mean": [0.485, 0.456, 0.406],
                        "std":  [0.229, 0.224, 0.225],
                        "heads": ["centering","surface","edges","corners","color","overall"],
                        "arch": "PairRegressor",
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            print(f"  ✅ saved best -> {ckpt_path}")
        else:
            patience_left -= 1
            if patience_left <= 0:
                print("  Early stopping (patience exhausted).")
                break

    print("\nTraining complete.")
    if ckpt_path.exists():
        print(f"Best weights: {ckpt_path}")
        print(f"Info file   : {info_path}")
    else:
        print("No weights saved.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="dataset/metadata.csv")
    ap.add_argument("--out", default="grading/ml/models")
    ap.add_argument("--size", type=int, default=384)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--weight-decay", type=float, default=1e-4)
    ap.add_argument("--val-split", type=float, default=0.15)
    ap.add_argument("--device", default="cuda")      # "cuda", "mps", or "cpu"
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--grad-clip", type=float, default=1.0)
    args = ap.parse_args()
    main(args)
