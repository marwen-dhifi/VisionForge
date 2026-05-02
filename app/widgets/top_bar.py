"""
TopBar — the permanent header strip of VisionForge.

Left:  animated logo + version badge
Right: StatusIndicator per hardware device
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPainter, QColor, QPen

from VisionForge.app.widgets.status_indicator import StatusIndicator


class _LogoWidget(QWidget):
    """'VisionForge' text logo with subtle animated accent dot."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)

        lo = QHBoxLayout(self)
        lo.setContentsMargins(20, 0, 20, 0)
        lo.setSpacing(10)

        # "VisionForge" — two-tone text using two QLabels
        vision = QLabel("Vision")
        vision.setFont(QFont("Segoe UI", 17, QFont.Weight.Light))
        vision.setStyleSheet("color: #E8EAFF; letter-spacing: 1px;")

        forge = QLabel("Forge")
        forge.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        forge.setStyleSheet("color: #00CFFF; letter-spacing: 1px;")

        version = QLabel("v1.0")
        version.setFont(QFont("Segoe UI", 9))
        version.setStyleSheet(
            "color: #00CFFF; background-color: rgba(0,207,255,18);"
            "border: 1px solid rgba(0,207,255,60);"
            "border-radius: 4px; padding: 1px 6px; letter-spacing: 1px;"
        )

        lo.addWidget(vision)
        lo.addWidget(forge)
        lo.addSpacing(6)
        lo.addWidget(version)
        lo.addStretch()


class _Separator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.VLine)
        self.setFixedWidth(1)
        self.setStyleSheet("background-color: #1A1A38;")


class TopBar(QWidget):
    """
    Permanent top bar. Exposes `cam_indicator` and `arm_indicator`
    so the main window can wire them to core thread signals.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setStyleSheet(
            "background-color: #0C0C1E;"
            "border-bottom: 1px solid #1A1A38;"
        )
        self._setup_ui()

    def _setup_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 16, 0)
        lo.setSpacing(0)

        lo.addWidget(_LogoWidget())
        lo.addStretch()

        lo.addWidget(_Separator())
        lo.addSpacing(8)

        self.cam_indicator = StatusIndicator("Camera", self)
        lo.addWidget(self.cam_indicator)

        lo.addSpacing(4)
        lo.addWidget(_Separator())
        lo.addSpacing(8)

        self.arm_indicator = StatusIndicator("xArm 5", self)
        lo.addWidget(self.arm_indicator)

    def paintEvent(self, event):
        """Draw a thin cyan accent line at the very bottom."""
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QPen(QColor(0, 207, 255, 60), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()
