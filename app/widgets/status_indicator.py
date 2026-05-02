"""
StatusIndicator — a live hardware connection badge.

Shows a pulsing coloured dot, a text label, and (when disconnected)
a small "Connect" button. The pulse animation is driven by a QTimer
that periodically calls update() to repaint the dot.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QTimer, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush

# Colour map for each state
STATE_COLORS = {
    "connected":    "#00E676",
    "disconnected": "#FF4466",
    "warning":      "#FFB300",
    "idle":         "#454878",
}


class _PulseDot(QWidget):
    """A custom-painted pulsing circle."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._base_color = QColor(color)
        self._pulse_r    = 0.0
        self._pulsing    = True

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)   # ~33 fps repaint

    def set_color(self, color: str):
        self._base_color = QColor(color)
        self.update()

    def set_pulsing(self, on: bool):
        self._pulsing = on
        if not on:
            self._pulse_r = 0.0
            self.update()

    def _tick(self):
        if self._pulsing:
            self._pulse_r = (self._pulse_r + 0.7) % 22
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = 7.0, 7.0

        # Expanding ring
        if self._pulsing and self._pulse_r > 0:
            fade   = max(0.0, 1.0 - self._pulse_r / 22)
            ring_c = QColor(self._base_color)
            ring_c.setAlpha(int(fade * 160))
            p.setPen(QPen(ring_c, 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = self._pulse_r * 0.45
            p.drawEllipse(QPointF(cx, cy), r, r)

        # Core dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._base_color))
        p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)


class StatusIndicator(QWidget):
    """
    Full status badge: dot + label + optional connect button.

    Signals:
        reconnect_requested — emitted when the user clicks the Connect button
    """

    reconnect_requested = Signal()

    def __init__(self, device_name: str, parent=None):
        super().__init__(parent)
        self._device = device_name
        self._connected = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self._dot   = _PulseDot(STATE_COLORS["disconnected"], self)
        self._label = QLabel(f"{self._device}  ·  Disconnected", self)
        self._label.setStyleSheet(f"color: #FF4466; font-size: 12px; font-weight: 600;")

        self._btn = QPushButton("Connect", self)
        self._btn.setProperty("class", "connect-btn")
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setFixedHeight(22)
        self._btn.clicked.connect(self.reconnect_requested.emit)

        layout.addWidget(self._dot)
        layout.addWidget(self._label)
        layout.addWidget(self._btn)

    # ── Public API ───────────────────────────────────────────────────────────

    def set_connected(self, connected: bool):
        self._connected = connected
        if connected:
            self._dot.set_color(STATE_COLORS["connected"])
            self._dot.set_pulsing(True)
            self._label.setText(f"{self._device}  ·  Connected")
            self._label.setStyleSheet("color: #00E676; font-size: 12px; font-weight: 600;")
            self._btn.setVisible(False)
        else:
            self._dot.set_color(STATE_COLORS["disconnected"])
            self._dot.set_pulsing(False)
            self._label.setText(f"{self._device}  ·  Disconnected")
            self._label.setStyleSheet("color: #FF4466; font-size: 12px; font-weight: 600;")
            self._btn.setVisible(True)

    def set_warning(self, message: str):
        self._dot.set_color(STATE_COLORS["warning"])
        self._dot.set_pulsing(True)
        self._label.setText(f"{self._device}  ·  {message}")
        self._label.setStyleSheet("color: #FFB300; font-size: 12px; font-weight: 600;")
        self._btn.setVisible(False)
