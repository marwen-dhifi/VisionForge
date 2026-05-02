"""
SplashScreen — the opening cinematic of VisionForge.

Sequence:
  1. Fade in (400 ms)
  2. ModelLoader runs in background — progress bar reflects real loading
  3. Brief pause (350 ms)
  4. Fade out (400 ms)
  5. Emit finished()
"""

import math
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from VisionForge.app.tasks.seven_segment.core import ModelLoader


W, H = 680, 400


class SplashScreen(QWidget):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self._progress_val = 0
        self._grid_offset  = 0

        self._setup_ui()
        self._center()
        self._start_sequence()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        inner = QWidget(self)
        inner.setStyleSheet(
            "background-color: #060612;"
            "border: 2px solid rgba(0,207,255,160);"
            "border-radius: 12px;"
        )
        inner.setFixedSize(W, H)

        lo = QVBoxLayout(inner)
        lo.setContentsMargins(60, 0, 60, 32)
        lo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lo.addStretch(2)

        # Tag line above title
        tag = QLabel("VISION & ROBOTICS INTEGRATION PLATFORM")
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tag.setStyleSheet(
            "color: rgba(0,207,255,180);"
            "font-size: 11px;"
            "font-weight: 600;"
            "letter-spacing: 4px;"
            "background: transparent;"
            "border: none;"
        )
        lo.addWidget(tag)
        lo.addSpacing(16)

        # Main title
        title_row = QWidget()
        title_row.setStyleSheet("background: transparent; border: none;")
        title_lo = QVBoxLayout(title_row)
        title_lo.setContentsMargins(0, 0, 0, 0)
        title_lo.setSpacing(0)

        vision_lbl = QLabel("Vision")
        vision_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vision_lbl.setFont(QFont("Segoe UI", 58, QFont.Weight.Light))
        vision_lbl.setStyleSheet("color: #E8EAFF; background: transparent; border: none; letter-spacing: 2px;")

        forge_lbl = QLabel("Forge")
        forge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        forge_lbl.setFont(QFont("Segoe UI", 58, QFont.Weight.Bold))
        forge_lbl.setStyleSheet("color: #00CFFF; background: transparent; border: none; letter-spacing: 2px;")

        # Put them side by side
        title_inner = QWidget()
        title_inner.setStyleSheet("background: transparent; border: none;")
        ti_lo = QVBoxLayout(title_inner)
        ti_lo.setContentsMargins(0, 0, 0, 0)
        ti_lo.setSpacing(0)
        ti_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)

        side_lo_w = QWidget()
        side_lo_w.setStyleSheet("background: transparent; border: none;")
        from PySide6.QtWidgets import QHBoxLayout
        side_lo = QHBoxLayout(side_lo_w)
        side_lo.setContentsMargins(0, 0, 0, 0)
        side_lo.setSpacing(0)
        side_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_lo.addWidget(vision_lbl)
        side_lo.addWidget(forge_lbl)

        lo.addWidget(side_lo_w)

        lo.addSpacing(8)

        # Version
        ver = QLabel("v 1.0")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(
            "color: rgba(0,207,255,200);"
            "font-size: 13px;"
            "letter-spacing: 6px;"
            "background: transparent;"
            "border: none;"
        )
        lo.addWidget(ver)

        lo.addStretch(2)

        # Progress bar
        self._bar = QProgressBar(inner)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(4)
        self._bar.setTextVisible(False)
        lo.addWidget(self._bar)

        # Status text
        self._status = QLabel("Initialising…")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(
            "color: #7a7eb8; font-size: 12px;"
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        lo.addSpacing(8)
        lo.addWidget(self._status)

        root.addWidget(inner)

        # Opacity effect for fade in/out
        self._opacity_fx = QGraphicsOpacityEffect(self)
        self._opacity_fx.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_fx)

        # Animated grid offset for the paintEvent (subtle movement)
        self._grid_timer = QTimer(self)
        self._grid_timer.timeout.connect(self._tick_grid)
        self._grid_timer.start(40)

    def _tick_grid(self):
        self._grid_offset = (self._grid_offset + 0.4) % 40
        self.update()

    # ── Sequence ─────────────────────────────────────────────────────────────

    def _start_sequence(self):
        # Fade in
        self._fade(0.0, 1.0, 400, callback=self._start_progress)

    def _start_progress(self):
        self._loader = ModelLoader(self)
        self._loader.progress.connect(self._on_loader_progress)
        self._loader.finished.connect(self._on_loader_finished)
        self._loader.start()

    def _on_loader_progress(self, pct: int, msg: str):
        self._bar.setValue(pct)
        self._status.setText(msg)

    def _on_loader_finished(self):
        self._bar.setValue(100)
        self._status.setText("Ready.")
        QTimer.singleShot(350, self._finish)

    def _finish(self):
        self._fade(1.0, 0.0, 400, callback=self._emit_done)

    def _emit_done(self):
        self._grid_timer.stop()
        self.finished.emit()
        self.close()

    def _fade(self, start: float, end: float, duration: int, callback=None):
        anim = QPropertyAnimation(self._opacity_fx, b"opacity", self)
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        if callback:
            anim.finished.connect(callback)
        anim.start()
        self._current_anim = anim   # keep reference

    # ── Center ───────────────────────────────────────────────────────────────

    def _center(self):
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - W) // 2,
            (screen.height() - H) // 2,
        )