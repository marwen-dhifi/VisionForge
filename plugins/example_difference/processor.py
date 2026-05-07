"""
DifferenceProcessor — computes per-pixel difference between consecutive frames.

Demonstrates:
  - Subclassing TaskProcessor
  - Emitting display_ready(QImage) and result_ready(object)
  - Keeping state across frames (self._prev_gray)
"""
import cv2
import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtGui  import QImage

from VisionForge.app.plugin_sdk import TaskProcessor


class DifferenceProcessor(TaskProcessor):
    """
    Compares each incoming frame against the previous one.
    Emits:
        display_ready(QImage)  — frame with changed pixels highlighted in red
        result_ready(dict)     — {"motion": float}  motion level 0.0–100.0
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prev_gray: np.ndarray | None = None

    def process_frame(self, frame_rgb: np.ndarray, meta: dict) -> None:
        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)

        if self._prev_gray is None or self._prev_gray.shape != gray.shape:
            self._prev_gray = gray
            # Emit the plain frame on the first call so the feed isn't blank
            h, w = frame_rgb.shape[:2]
            qimg = QImage(frame_rgb.data, w, h, 3 * w,
                          QImage.Format.Format_RGB888).copy()
            self.display_ready.emit(qimg)
            self.result_ready.emit({"motion": 0.0})
            return

        # Absolute difference + threshold
        diff  = cv2.absdiff(gray, self._prev_gray)
        _, mask = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        self._prev_gray = gray

        # Motion level: percentage of pixels that changed
        motion = float(mask.mean())

        # Overlay changed pixels in red
        out = frame_rgb.copy()
        out[mask > 0] = [220, 50, 50]

        h, w = out.shape[:2]
        qimg = QImage(out.data, w, h, 3 * w,
                      QImage.Format.Format_RGB888).copy()

        self.display_ready.emit(qimg)
        self.result_ready.emit({"motion": motion})
