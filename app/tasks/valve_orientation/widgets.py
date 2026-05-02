"""
Valve-specific widgets.
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QImage, QPixmap

from VisionForge.app.widgets.feed_widget import FeedWidget
from VisionForge.app.tasks.valve_orientation.core import SAMPLE_WINDOW


# ── Valve feed (display only — all CV work is in ValveProcessor) ──────────────

class ValveFeedWidget(FeedWidget):
    """
    Thin display widget.  ValveProcessor does all resize/overlay/detect work in
    its own thread and emits ready QImages via display_ready — the UI thread only
    calls set_display() which is essentially free.
    """

    size_changed = Signal(int, int, float)   # lw, lh, dpr — for processor resize target

    def __init__(self, parent=None):
        super().__init__(parent)

    def set_display(self, qimg: QImage):
        """Slot — receives a fully-composed QImage from ValveProcessor."""
        self._pixmap    = QPixmap.fromImage(qimg)
        self._connected = True
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.size_changed.emit(self.width(), self.height(), self.devicePixelRatioF())


# ── Valve status card ──────────────────────────────────────────────────────────

class ValveCard(QFrame):
    """Compact status card for a single valve. Clickable."""

    clicked = Signal(int)   # emits marker_id on left-click

    def __init__(self, marker_id: int, name: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("valveCard")
        self.marker_id = marker_id
        self.setFixedHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        self.status_dot = QLabel("●")
        self.status_dot.setFixedWidth(20)
        self.status_dot.setFont(QFont("Arial", 16))
        self.status_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_dot)

        info = QVBoxLayout()
        info.setSpacing(2)

        self.name_label = QLabel(name or f"Valve {marker_id}")
        self.name_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.name_label.setStyleSheet("color: #E8EAFF;")
        info.addWidget(self.name_label)

        self.detail_label = QLabel(f"ID: {marker_id}")
        self.detail_label.setFont(QFont("Segoe UI", 9))
        self.detail_label.setStyleSheet("color: #8890B8;")
        info.addWidget(self.detail_label)

        layout.addLayout(info, 1)

        self.state_label = QLabel("—")
        self.state_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.state_label.setFixedWidth(90)
        layout.addWidget(self.state_label)

        self.set_config_status("none", False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.marker_id)
        super().mousePressEvent(event)

    def set_config_status(self, status: str, selected: bool):
        """
        Render the card for Overview / Calibration modes.
        status: 'full' | 'partial_open' | 'partial_closed' | 'none'
        selected: True → cyan highlight border
        """
        if selected:
            border, bg, thickness = "#00CFFF", "#060618", 2
        elif status == "full":
            border, bg, thickness = "#00E676", "#0A1F12", 1
        elif status in ("partial_open", "partial_closed"):
            border, bg, thickness = "#FFB300", "#1A1200", 1
        else:
            border, bg, thickness = "#FF4466", "#1F0A10", 1

        dot_color, badge, badge_color = {
            "full":           ("#00E676", "FULL",    "#00E676"),
            "partial_open":   ("#FFB300", "PARTIAL", "#FFB300"),
            "partial_closed": ("#FFB300", "PARTIAL", "#FFB300"),
        }.get(status, ("#FF4466", "NONE", "#FF4466"))

        detail = {
            "full":           "Open + Closed configured",
            "partial_open":   "Open only",
            "partial_closed": "Closed only",
        }.get(status, "Not configured")

        self.status_dot.setStyleSheet(f"color: {dot_color};")
        self.detail_label.setText(f"ID: {self.marker_id}  •  {detail}")
        self.state_label.setText(badge)
        self.state_label.setStyleSheet(f"color: {badge_color};")
        self.setStyleSheet(
            f"QFrame#valveCard {{ background-color: {bg}; "
            f"border: {thickness}px solid {border}; border-radius: 8px; }}"
        )

    def set_tracking_state(self, state: str, visible: bool,
                           confidence: float = 0.0, samples: int = 0):
        """Render the card for Tracking mode. Skips redundant repaints."""
        key = (state, visible, round(confidence * 100), samples)
        if getattr(self, "_tracking_key", None) == key:
            return
        self._tracking_key = key

        if not visible:
            self.status_dot.setStyleSheet("color: #454878;")
            self.state_label.setText("NOT SEEN")
            self.state_label.setStyleSheet("color: #454878;")
            self.detail_label.setText(f"ID: {self.marker_id}")
            self.setStyleSheet(
                "QFrame#valveCard { background-color: #0C0C1E; border: 1px solid #1A1A38; border-radius: 8px; }"
            )
        elif state == "open":
            self.status_dot.setStyleSheet("color: #00E676;")
            self.state_label.setText("OPEN")
            self.state_label.setStyleSheet("color: #00E676;")
            self.detail_label.setText(f"ID: {self.marker_id}  •  {confidence:.0%}  •  {samples}/{SAMPLE_WINDOW}")
            self.setStyleSheet(
                "QFrame#valveCard { background-color: #0A1F12; border: 1px solid #00E676; border-radius: 8px; }"
            )
        elif state == "closed":
            self.status_dot.setStyleSheet("color: #FF4466;")
            self.state_label.setText("CLOSED")
            self.state_label.setStyleSheet("color: #FF4466;")
            self.detail_label.setText(f"ID: {self.marker_id}  •  {confidence:.0%}  •  {samples}/{SAMPLE_WINDOW}")
            self.setStyleSheet(
                "QFrame#valveCard { background-color: #1F0A10; border: 1px solid #FF4466; border-radius: 8px; }"
            )
        else:
            self.status_dot.setStyleSheet("color: #FFB300;")
            self.state_label.setText("?")
            self.state_label.setStyleSheet("color: #FFB300;")
            self.detail_label.setText(f"ID: {self.marker_id}  •  configured")
            self.setStyleSheet(
                "QFrame#valveCard { background-color: #1A1200; border: 1px solid #FFB300; border-radius: 8px; }"
            )

    def set_name(self, name: str):
        self.name_label.setText(name)
