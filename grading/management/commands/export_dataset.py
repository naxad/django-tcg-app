# grading/management/commands/export_dataset.py
import csv
import json
import os
import shutil
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from grading.models import GradeRequest


class Command(BaseCommand):
    help = "Export graded card dataset (images + metadata) for ML training."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            default="dataset",
            help="Output folder (default: dataset)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max number of rows to export (default: all).",
        )
        parser.add_argument(
            "--since-days",
            type=int,
            default=None,
            help="Only export rows created within the last N days.",
        )
        parser.add_argument(
            "--no-copy",
            action="store_true",
            help="Do not copy images, only write metadata with absolute paths.",
        )

    def handle(self, *args, **opts):
        out_dir = opts["out"]
        no_copy = opts["no_copy"]
        limit = opts["limit"]
        since_days = opts["since_days"]

        images_dir = os.path.join(out_dir, "images")
        os.makedirs(out_dir, exist_ok=True)
        if not no_copy:
            os.makedirs(images_dir, exist_ok=True)

        qs = GradeRequest.objects.all().order_by("id")
        if since_days:
            cutoff = timezone.now() - timedelta(days=since_days)
            qs = qs.filter(created_at__gte=cutoff) if hasattr(GradeRequest, "created_at") else qs

        if limit:
            qs = qs[:limit]

        csv_path = os.path.join(out_dir, "metadata.csv")
        jsonl_path = os.path.join(out_dir, "metadata.jsonl")

        csv_fields = [
            "id",
            "front_path",
            "back_path",
            "centering",
            "surface",
            "edges",
            "corners",
            "color",
            "predicted_grade",
            "predicted_label",
            "needs_better_photos",
            "photo_feedback",
            "created_at",
        ]

        rows_written = 0
        with open(csv_path, "w", newline="", encoding="utf-8") as csvf, \
             open(jsonl_path, "w", encoding="utf-8") as jsonlf:

            writer = csv.DictWriter(csvf, fieldnames=csv_fields)
            writer.writeheader()

            for gr in qs:
                # Require at least a front image
                if not gr.front_image:
                    continue

                # Source absolute paths
                abs_front = gr.front_image.path
                abs_back = gr.back_image.path if getattr(gr, "back_image", None) else None

                # Dest relative paths (for training)
                rel_front = None
                rel_back = None

                if no_copy:
                    # Use absolute paths when not copying
                    rel_front = abs_front
                    rel_back = abs_back
                else:
                    # Copy into dataset/images as <id>_front.<ext>, <id>_back.<ext>
                    front_ext = os.path.splitext(abs_front)[1] or ".jpg"
                    front_name = f"{gr.pk}_front{front_ext}"
                    front_out = os.path.join(images_dir, front_name)
                    self._safe_copy(abs_front, front_out)
                    rel_front = os.path.join("images", front_name)

                    if abs_back:
                        back_ext = os.path.splitext(abs_back)[1] or ".jpg"
                        back_name = f"{gr.pk}_back{back_ext}"
                        back_out = os.path.join(images_dir, back_name)
                        self._safe_copy(abs_back, back_out)
                        rel_back = os.path.join("images", back_name)

                # Scores & metadata (handle missing fields safely)
                row = {
                    "id": gr.pk,
                    "front_path": rel_front or "",
                    "back_path": rel_back or "",
                    "centering": self._to_float(getattr(gr, "score_centering", 0)),
                    "surface": self._to_float(getattr(gr, "score_surface", 0)),
                    "edges": self._to_float(getattr(gr, "score_edges", 0)),
                    "corners": self._to_float(getattr(gr, "score_corners", 0)),
                    "color": self._to_float(getattr(gr, "score_color", 0)),
                    "predicted_grade": self._to_float(getattr(gr, "predicted_grade", 0)),
                    "predicted_label": getattr(gr, "predicted_label", "") or "",
                    "needs_better_photos": bool(getattr(gr, "needs_better_photos", False)),
                    "photo_feedback": getattr(gr, "photo_feedback", "") or "",
                    "created_at": (
                        getattr(gr, "created_at", None).isoformat()
                        if getattr(gr, "created_at", None) else ""
                    ),
                }

                writer.writerow(row)
                jsonlf.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows_written += 1

        self.stdout.write(self.style.SUCCESS(
            f"Export complete → {out_dir}  "
            f"[rows: {rows_written}, images: {'not copied' if no_copy else 'copied'}]"
        ))

    @staticmethod
    def _safe_copy(src, dst):
        try:
            shutil.copy2(src, dst)
        except Exception as e:
            # If a single file fails, skip but continue the export
            print(f"[warn] failed to copy {src} → {dst}: {e}")

    @staticmethod
    def _to_float(x):
        try:
            return float(x)
        except Exception:
            return 0.0