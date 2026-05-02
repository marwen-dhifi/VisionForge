"""
FeedWidget — renders live camera frames.
Scales with cv2.resize + draws overlay with cv2.putText,
exactly matching the reference implementation.
"""

import cv2
import numpy as np

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore    import Qt, Signal
from PySide6.QtGui     import QPainter, QPixmap, QColor, QImage, QPen, QFont


class FeedWidget(QWidget):

    # Emitted once per unique camera resolution so the parent can resize the splitter
    resolution_changed = Signal(int, int)   # cam_w, cam_h

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap    = None
        self._connected = False
        self._is_recording = False
        self._fps       = 0.0
        self._cam_w     = 0
        self._cam_h     = 0
        self.setMinimumSize(320, 240)
        self.setStyleSheet("background-color: #080814;")

    # ── Public API ───────────────────────────────────────────────────────────

    def on_frame(self, frame: np.ndarray, meta: dict):
        lw = self.width()
        lh = self.height()
        if lw < 1 or lh < 1:
            return

        # Scale to physical pixels to avoid upscaling artifacts on HiDPI displays
        dpr = self.devicePixelRatioF()
        pw  = int(lw * dpr)
        ph  = int(lh * dpr)

        h, w   = frame.shape[:2]
        if w != self._cam_w or h != self._cam_h:
            self._cam_w, self._cam_h = w, h
            self.resolution_changed.emit(w, h)
        scale  = min(pw / w, ph / h)
        nw     = int(w * scale)
        nh     = int(h * scale)
        display = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)

        # Overlay
        rec_indicator = "  ⬤ REC" if self._is_recording else ""
        overlay = "{}x{}  |  {:.1f} fps{}".format(
            meta["width"], meta["height"], self._fps, rec_indicator
        )
        color = (220, 50, 50) if self._is_recording else (80, 200, 80)
        cv2.putText(display, overlay, (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        # Build QImage at physical resolution, set DPR so Qt shows it crisp
        qimg = QImage(
            display.data, nw, nh, nw * 3,
            QImage.Format.Format_RGB888
        ).copy()
        qimg.setDevicePixelRatio(dpr)

        self._pixmap    = QPixmap.fromImage(qimg)
        self._connected = True
        self.update()

    def set_camera_connected(self, connected: bool):
        self._connected = connected
        if not connected:
            self._pixmap = None
        self.update()

    def set_fps(self, fps: float):
        self._fps = fps

    def set_recording(self, recording: bool):
        self._is_recording = recording

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.fillRect(self.rect(), QColor("#080814"))

        if self._connected and self._pixmap:
            # pixmap has devicePixelRatio set — Qt draws at correct logical size
            pw = self._pixmap.width()  / self._pixmap.devicePixelRatioF()
            ph = self._pixmap.height() / self._pixmap.devicePixelRatioF()
            x  = int((w - pw) / 2)
            y  = int((h - ph) / 2)
            painter.drawPixmap(x, y, self._pixmap)
        else:
            self._draw_disconnected(painter, w, h)

        painter.end()

    def _draw_disconnected(self, painter, w, h):
        cx, cy = w // 2, h // 2
        pen = QPen(QColor("#282848"), 1.5)
        painter.setPen(pen)
        painter.setBrush(QColor("#111128"))
        bw, bh = 90, 60
        painter.drawRoundedRect(cx - bw//2, cy - bh//2 - 10, bw, bh, 8, 8)
        painter.setPen(QPen(QColor("#282848"), 1.5))
        painter.setBrush(QColor("#0C0C1E"))
        painter.drawEllipse(cx - 18, cy - 18 - 10, 36, 36)
        painter.setPen(QPen(QColor("#1A1A38"), 1))
        painter.setBrush(QColor("#080814"))
        painter.drawEllipse(cx - 10, cy - 10 - 10, 20, 20)
        painter.setPen(QPen(QColor("#282848"), 1.5))
        painter.setBrush(QColor("#111128"))
        painter.drawRoundedRect(cx + bw//2 - 18, cy - bh//2 - 20, 18, 12, 3, 3)
        painter.setPen(QColor("#454878"))
        painter.setFont(QFont("Segoe UI", 13))
        painter.drawText(0, cy + 50, w, 24,
                         Qt.AlignmentFlag.AlignHCenter, "Camera not connected")
        painter.setPen(QColor("#282848"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(0, cy + 74, w, 20,
                         Qt.AlignmentFlag.AlignHCenter, "Check connection status above")