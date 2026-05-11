"""
HandPointerProcessor — detects right-hand gestures via MediaPipe Tasks API.

Compatible with mediapipe >= 0.10.14 (the new Tasks API).
The hand_landmarker.task model file is downloaded automatically on first run
to the plugin directory.

Emits:
    display_ready(QImage)  — annotated frame with landmarks + gesture label
    result_ready(dict)     — {"gesture": str, "direction": (dx, dy)}

Gestures:
    "pointing"  — index finger extended, other three fingers curled
    "fist"      — all four fingers curled
    "open"      — any other configuration
    "none"      — no hand detected
    "error"     — mediapipe not installed / model missing
"""

import os
import urllib.request
import cv2
import numpy as np
from PySide6.QtGui import QImage
from VisionForge.app.plugin_sdk import TaskProcessor

# ── Model file ────────────────────────────────────────────────────────────────

_MODEL_URL  = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")

# ── Hand skeleton connections for manual drawing ──────────────────────────────

_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),
    (0,5),(5,6),(6,7),(7,8),
    (0,9),(9,10),(10,11),(11,12),
    (0,13),(13,14),(14,15),(15,16),
    (0,17),(17,18),(18,19),(19,20),
    (5,9),(9,13),(13,17),(0,17),
]

# (fingertip id, pip id) for index / middle / ring / pinky
_FINGER_PAIRS = [(8, 6), (12, 10), (16, 14), (20, 18)]

# ── Import mediapipe ──────────────────────────────────────────────────────────

_MP_OK    = False
_MP_ERROR = ""

try:
    import mediapipe as mp
    from mediapipe.tasks import python as _mp_python
    from mediapipe.tasks.python import vision as _mp_vision
    _MP_OK = True
except (ImportError, AttributeError) as _e:
    _MP_ERROR = str(_e)


def _ensure_model() -> str:
    """Return _MODEL_PATH if model exists/downloaded, else raise RuntimeError."""
    if os.path.isfile(_MODEL_PATH):
        return _MODEL_PATH
    print("[HandPointer] Downloading hand_landmarker.task …", flush=True)
    try:
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
        print(f"[HandPointer] Model saved to {_MODEL_PATH}", flush=True)
        return _MODEL_PATH
    except Exception as exc:
        raise RuntimeError(
            f"Could not download model: {exc}\n"
            f"Download manually from:\n  {_MODEL_URL}\n"
            f"and place it at:\n  {_MODEL_PATH}"
        ) from exc


# ── Processor ─────────────────────────────────────────────────────────────────

class HandPointerProcessor(TaskProcessor):

    def __init__(self):
        super().__init__()
        self._detector = None
        self._init_error = ""

        if not _MP_OK:
            self._init_error = _MP_ERROR or "mediapipe not installed — pip install mediapipe"
            return

        try:
            model_path = _ensure_model()
            options = _mp_vision.HandLandmarkerOptions(
                base_options=_mp_python.BaseOptions(model_asset_path=model_path),
                running_mode=_mp_vision.RunningMode.IMAGE,
                num_hands=2,
                min_hand_detection_confidence=0.7,
                min_hand_presence_confidence=0.7,
                min_tracking_confidence=0.5,
            )
            self._detector = _mp_vision.HandLandmarker.create_from_options(options)
        except Exception as exc:
            self._init_error = str(exc)

    def process_frame(self, frame_rgb, meta):
        h, w = frame_rgb.shape[:2]
        canvas = frame_rgb.copy()

        if self._detector is None:
            _put_text(canvas, self._init_error or "init error", (255, 80, 80))
            self.display_ready.emit(_to_qimg(canvas))
            self.result_ready.emit({"gesture": "error", "direction": (0.0, 0.0)})
            return

        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        detection = self._detector.detect(mp_img)

        result = {"gesture": "none", "direction": (0.0, 0.0)}

        if detection.hand_landmarks:
            idx = _pick_right_hand(detection)
            lm  = detection.hand_landmarks[idx]

            _draw_hand(canvas, lm, w, h)

            gesture   = _classify(lm)
            direction = _finger_direction(lm) if gesture == "pointing" else (0.0, 0.0)
            result    = {"gesture": gesture, "direction": direction}

            if gesture == "pointing":
                base_px = (int(lm[5].x * w), int(lm[5].y * h))
                tip_px  = (int(lm[8].x * w), int(lm[8].y * h))
                cv2.arrowedLine(canvas, base_px, tip_px, (0, 230, 100), 3, tipLength=0.4)

        color = {
            "pointing": (0, 230, 100),
            "fist":     (255, 80,  80),
            "open":     (255, 179, 0),
            "none":     (120, 120, 180),
            "error":    (255, 80,  80),
        }.get(result["gesture"], (180, 180, 180))
        _put_text(canvas, result["gesture"].upper(), color)

        self.display_ready.emit(_to_qimg(canvas))
        self.result_ready.emit(result)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pick_right_hand(detection) -> int:
    """
    Return index of the user's right hand.

    The new Tasks API (mediapipe >= 0.10.14) assumes a non-mirrored image,
    so 'Right' == user's right hand (opposite of the legacy solutions API).
    Fall back to index 0 if handedness is unavailable.
    """
    if detection.handedness:
        for i, cat_list in enumerate(detection.handedness):
            if cat_list and cat_list[0].category_name == "Right":
                return i
    return 0


def _dist(a, b):
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5


def _classify(lm) -> str:
    """Classify gesture using wrist-to-tip distances (works in any orientation)."""
    wrist = lm[0]
    extended = [
        _dist(lm[tip], wrist) > _dist(lm[pip], wrist)
        for tip, pip in _FINGER_PAIRS
    ]
    idx, mid, rng, pnk = extended
    if idx and not mid and not rng and not pnk:
        return "pointing"
    if not any(extended):
        return "fist"
    return "open"


def _finger_direction(lm):
    """Normalised 2-D screen direction of the index finger (MCP → tip)."""
    tip  = lm[8]
    base = lm[5]
    dx, dy = tip.x - base.x, tip.y - base.y
    length = (dx ** 2 + dy ** 2) ** 0.5
    if length < 1e-6:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _draw_hand(canvas, lm, w, h):
    pts = [(int(p.x * w), int(p.y * h)) for p in lm]
    for a, b in _CONNECTIONS:
        cv2.line(canvas, pts[a], pts[b], (100, 180, 255), 2)
    for pt in pts:
        cv2.circle(canvas, pt, 4, (255, 255, 255), -1)
        cv2.circle(canvas, pt, 4, (60, 120, 220),  1)


def _put_text(canvas, text, color):
    cv2.putText(canvas, text, (16, 44),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 2)


def _to_qimg(frame_rgb) -> QImage:
    h, w = frame_rgb.shape[:2]
    return QImage(frame_rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
