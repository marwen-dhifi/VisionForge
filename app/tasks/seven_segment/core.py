"""
Seven-Segment task — shared constants, paths, utilities, data classes,
and model loading with a caching layer so models are only loaded once
(during the splash screen) and reused instantly by the processor.
"""

import os
import re
import sys
import traceback
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
from dataclasses import dataclass, field
from PySide6.QtCore import QThread, Signal

# ── Paths (resolved relative to this file) ───────────────────────────────────

_DIR        = os.path.dirname(os.path.abspath(__file__))
PARSEQ_ROOT = os.path.join(_DIR, "parseq")
PARSEQ_CKPT = os.path.join(_DIR, "weights", "parseq", "parseq_7seg.ckpt")
MODEL_PATH  = os.path.join(_DIR, "weights", "yolo",   "best.pt")

# ── InfluxDB connection settings ──────────────────────────────────────────────

INFLUX_URL    = "http://localhost:8086"
INFLUX_TOKEN  = "0FvQ4oKTsdke0QZz6uiEMiMTTuXDJFaBnfrLpCfiODt4eoQHRPPd-71Enhk6kklxNsbHhdXJ2D7QMzod56a6NQ=="
INFLUX_ORG    = "ESDperformance"
INFLUX_BUCKET = "7Segments_Measurments"


# ── Model cache (populated once at startup, reused by the processor) ─────────

_yolo_model   = None
_parseq_model = None
_parseq_transform = None
_parseq_device    = "cpu"


def load_yolo(progress_cb: Optional[Callable] = None):
    """Load YOLO-OBB model (cached). progress_cb(pct, msg) is optional."""
    global _yolo_model
    if _yolo_model is not None:
        return _yolo_model
    from ultralytics import YOLO
    if progress_cb:
        progress_cb(5, "Loading YOLO detector…")
    _yolo_model = YOLO(MODEL_PATH)
    if progress_cb:
        progress_cb(35, "YOLO detector ready.")
    return _yolo_model


def load_parseq(progress_cb: Optional[Callable] = None):
    """Load PARSeq OCR model (cached). progress_cb(pct, msg) is optional."""
    global _parseq_model, _parseq_transform, _parseq_device
    if _parseq_model is not None:
        return _parseq_model, _parseq_transform, _parseq_device

    if PARSEQ_ROOT not in sys.path:
        sys.path.insert(0, PARSEQ_ROOT)

    if progress_cb:
        progress_cb(40, "Importing PARSeq library…")
    from strhub.models.utils import load_from_checkpoint
    from strhub.data.module  import SceneTextDataModule

    if progress_cb:
        progress_cb(55, "Loading PARSeq checkpoint…")
    _parseq_device = "cuda" if torch.cuda.is_available() else "cpu"
    _parseq_model  = load_from_checkpoint(PARSEQ_CKPT).eval().to(_parseq_device)

    if progress_cb:
        progress_cb(92, "Building image transform…")
    _parseq_transform = SceneTextDataModule.get_transform(_parseq_model.hparams.img_size)

    if progress_cb:
        progress_cb(100, "All models ready.")
    return _parseq_model, _parseq_transform, _parseq_device


# ── Startup model loader (runs during the splash screen) ─────────────────────

class ModelLoader(QThread):
    """
    Background thread that loads YOLO + PARSeq during the splash screen.
    Emits progress(int 0-100, str message) as loading advances.
    The models are cached in this module; SevenSegProcessor reuses them instantly.
    """

    progress = Signal(int, str)

    def run(self):
        try:
            load_yolo(progress_cb=lambda p, m: self.progress.emit(p, m))
            load_parseq(progress_cb=lambda p, m: self.progress.emit(p, m))
        except Exception:
            print("[ModelLoader] Failed to load models:")
            traceback.print_exc()
            self.progress.emit(100, "Model load failed — check console.")


# ── Utility functions ─────────────────────────────────────────────────────────

def crop_obb_local(frame: np.ndarray, cx, cy, w, h, angle_rad, pad: float = 1.5):
    """Extract an axis-aligned crop from an oriented bounding box."""
    fh, fw = frame.shape[:2]
    angle_deg = np.degrees(angle_rad)
    diag  = int(np.sqrt(w ** 2 + h ** 2) * pad)
    half  = diag // 2
    px1   = max(0, int(cx) - half)
    py1   = max(0, int(cy) - half)
    px2   = min(fw, px1 + diag)
    py2   = min(fh, py1 + diag)
    patch = frame[py1:py2, px1:px2]
    if patch.size == 0:
        return None
    local_cx = float(cx - px1)
    local_cy = float(cy - py1)
    M       = cv2.getRotationMatrix2D((local_cx, local_cy), angle_deg, 1.0)
    rotated = cv2.warpAffine(patch, M, (patch.shape[1], patch.shape[0]),
                             flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
    x1   = max(0, int(local_cx - w / 2))
    y1   = max(0, int(local_cy - h / 2))
    x2   = min(rotated.shape[1], int(local_cx + w / 2))
    y2   = min(rotated.shape[0], int(local_cy + h / 2))
    crop = rotated[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    if crop.shape[0] > crop.shape[1]:
        crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
    return crop


def batch_read_displays(crops_bgr: list, parseq, img_transform, device: str,
                        flip_flags: Optional[list] = None) -> list:
    """Run PARSeq OCR on a batch of BGR crops. Returns [(label, conf), ...]."""
    if not crops_bgr:
        return []

    from PIL import Image as PILImage

    tensors = []
    for i, crop in enumerate(crops_bgr):
        c = crop.copy()
        if flip_flags and i < len(flip_flags) and flip_flags[i]:
            c = cv2.rotate(c, cv2.ROTATE_180)
        pil = PILImage.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB))
        tensors.append(img_transform(pil))

    batch = torch.stack(tensors).to(device)
    with torch.no_grad():
        logits = parseq(batch)
        preds  = logits.softmax(-1)
        labels, confs = parseq.tokenizer.decode(preds)

    return [(labels[i], confs[i].mean().item()) for i in range(len(crops_bgr))]


def is_valid_numeric(text: str) -> bool:
    """Return True if text represents a valid integer or decimal number."""
    text = text.strip()
    if not text:
        return False
    return bool(re.match(r'^[+-]?(\d+\.?\d*|\.\d+)$', text))


def point_in_quad(px: float, py: float, quad: np.ndarray) -> bool:
    """Return True if the point (px, py) is inside the quadrilateral."""
    return cv2.pointPolygonTest(
        quad.astype(np.float32), (float(px), float(py)), False
    ) >= 0


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class FramePacket:
    frame:       np.ndarray                          # original BGR frame
    obb_points:  np.ndarray                          # (N, 4, 2) corners, full-res
    obb_xywhr:   np.ndarray                          # (N, 5)
    tracker_ids: np.ndarray                          # (N,) int
    crops:       Dict[int, np.ndarray] = field(default_factory=dict)
    ocr_results: Dict[int, Tuple[str, float]] = field(default_factory=dict)
    fps:         float = 0.0
    ran_ocr:     bool  = False


# ── InfluxDB manager ──────────────────────────────────────────────────────────

class InfluxDBManager:

    def __init__(self):
        from influxdb_client import InfluxDBClient, Point
        from influxdb_client.client.write_api import SYNCHRONOUS

        self._Point    = Point
        self.client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()
        self.delete_api = self.client.delete_api()

    def write_value(self, measurement_name: str, value: float):
        point = self._Point(measurement_name).field("value", value)
        self.write_api.write(bucket=INFLUX_BUCKET, record=point)

    def get_measurements(self) -> List[str]:
        query = (
            f'import "influxdata/influxdb/schema"\n'
            f'schema.measurements(bucket: "{INFLUX_BUCKET}")'
        )
        try:
            tables = self.query_api.query(query)
            return sorted(
                record.get_value()
                for table  in tables
                for record in table.records
            )
        except Exception as e:
            print(f"[InfluxDB] Error listing measurements: {e}")
            return []

    def delete_measurement(self, name: str):
        try:
            self.delete_api.delete(
                start     = "1970-01-01T00:00:00Z",
                stop      = "2099-12-31T23:59:59Z",
                predicate = f'_measurement="{name}"',
                bucket    = INFLUX_BUCKET,
                org       = INFLUX_ORG,
            )
        except Exception as e:
            print(f"[InfluxDB] Error deleting '{name}': {e}")

    def close(self):
        self.client.close()
