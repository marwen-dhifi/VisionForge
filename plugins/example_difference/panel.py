"""
DifferencePanel — UI for the frame-difference plugin.

Demonstrates:
  - Subclassing TaskPanel
  - on_attach(): build UI, create processor, wire signals
  - Using self._cam signals (real CameraClient)
  - Using self._arm signals (real ArmController)
  - cleanup(): call super().cleanup()
  - save_frame() + resolve_path() utilities
"""
import os
from datetime import datetime

from PySide6.QtCore    import Qt
from PySide6.QtGui     import QFont, QPixmap
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from VisionForge.app.plugin_sdk import TaskPanel, save_frame, resolve_path
from processor import DifferenceProcessor   # local import — plugin folder is on sys.path


class DifferencePanel(TaskPanel):
    """
    Frame-difference motion detector panel.

    Left side  : live annotated camera feed (click to save a capture)
    Right side : motion level readout + arm TCP position (when arm connected)
    """

    def on_attach(self):
        # ── Processor ────────────────────────────────────────────────────────
        self._processor = DifferenceProcessor()
        self._processor.display_ready.connect(self._on_display)
        self._processor.result_ready.connect(self._on_result)

        # ── Layout ────────────────────────────────────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title
        title = QLabel("Frame Difference")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #00CFFF;")
        root.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        # Feed label (click to save)
        self._feed = QLabel("Waiting for camera…")
        self._feed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._feed.setStyleSheet(
            "background-color: #0C0C1E; border: 1px solid #1A1A38; color: #8890B8;"
        )
        self._feed.setMinimumSize(320, 240)
        self._feed.setCursor(Qt.CursorShape.PointingHandCursor)
        self._feed.mousePressEvent = self._save_capture
        body.addWidget(self._feed, 3)

        # Info panel
        info = QWidget()
        info.setStyleSheet("background-color: #0C0C1E; border: 1px solid #1A1A38;")
        info.setMinimumWidth(180)
        info_lo = QVBoxLayout(info)
        info_lo.setContentsMargins(12, 12, 12, 12)
        info_lo.setSpacing(8)

        info_lo.addWidget(self._section_label("Motion"))
        self._motion_lbl = QLabel("— %")
        self._motion_lbl.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self._motion_lbl.setStyleSheet("color: #00E676;")
        info_lo.addWidget(self._motion_lbl)

        info_lo.addSpacing(16)
        info_lo.addWidget(self._section_label("Arm TCP"))
        self._arm_lbl = QLabel("not connected")
        self._arm_lbl.setStyleSheet("color: #8890B8; font-size: 11px;")
        self._arm_lbl.setWordWrap(True)
        info_lo.addWidget(self._arm_lbl)

        info_lo.addStretch()

        self._save_btn = QPushButton("Save frame")
        self._save_btn.setStyleSheet(
            "background: #111128; color: #00CFFF; border: 1px solid #00CFFF;"
            "border-radius: 4px; padding: 6px 12px;"
        )
        self._save_btn.clicked.connect(lambda: self._save_capture(None))
        info_lo.addWidget(self._save_btn)

        body.addWidget(info, 1)

        # ── Arm signals ───────────────────────────────────────────────────────
        if self._arm:
            self._arm.position_updated.connect(self._on_arm_position)
            self._arm.connection_changed.connect(self._on_arm_connection)

        # Track latest frame for click-to-save
        self._latest_frame = None
        self._processor.result_ready.connect(
            lambda _: None  # result_ready already connected above; no-op slot placeholder
        )

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_display(self, qimg):
        pix = QPixmap.fromImage(qimg)
        self._feed.setPixmap(
            pix.scaled(self._feed.size(),
                       Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        )

    def _on_result(self, result: dict):
        motion = result.get("motion", 0.0)
        self._motion_lbl.setText(f"{motion:.1f} %")
        color = "#FF4466" if motion > 5.0 else "#00E676"
        self._motion_lbl.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold;")

    def _on_arm_position(self, x, y, z, roll, pitch, yaw):
        self._arm_lbl.setText(
            f"X  {x:+.1f}\nY  {y:+.1f}\nZ  {z:+.1f}\n"
            f"R  {roll:+.1f}\nP  {pitch:+.1f}\nW  {yaw:+.1f}"
        )
        self._arm_lbl.setStyleSheet("color: #E8EAFF; font-size: 11px;")

    def _on_arm_connection(self, connected: bool):
        if not connected:
            self._arm_lbl.setText("disconnected")
            self._arm_lbl.setStyleSheet("color: #8890B8; font-size: 11px;")

    def _save_capture(self, _event):
        """Save the current frame to plugin_dir/captures/<timestamp>.png."""
        if self._processor is None:
            return
        # Grab latest frame from the queue if available
        captures_dir = resolve_path(__file__, "captures")
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        dst = os.path.join(captures_dir, f"diff_{ts}.png")
        # We save whatever the feed currently shows via QPixmap
        pix = self._feed.pixmap()
        if pix and not pix.isNull():
            pix.save(dst)
            print(f"[DifferencePanel] Saved capture: {dst}", flush=True)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self):
        if self._arm:
            try:
                self._arm.position_updated.disconnect(self._on_arm_position)
                self._arm.connection_changed.disconnect(self._on_arm_connection)
            except (RuntimeError, TypeError):
                pass
        super().cleanup()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            "color: #454878; font-size: 10px; font-weight: 600; letter-spacing: 2px;"
            "background: transparent; border: none;"
        )
        return lbl
