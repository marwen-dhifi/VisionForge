"""
Seven-Segment task widgets.

  SevenSegFeedWidget  — display-only feed; emits box_clicked(tracker_id)
  DetailPanel         — live crop preview + OCR reading + action buttons
  NamingDialog        — assign / rename a measurement to a tracker box
"""

from typing import List, Optional

import cv2
import numpy as np
from PySide6.QtCore  import Qt, Signal
from PySide6.QtGui   import QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from VisionForge.app.widgets.feed_widget import FeedWidget
from VisionForge.app.tasks.seven_segment.core import is_valid_numeric, point_in_quad

_C = {
    "bg":     "#060612",
    "bg2":    "#0C0C1E",
    "bg3":    "#111128",
    "border": "#1A1A38",
    "accent": "#00CFFF",
    "green":  "#00E676",
    "red":    "#FF4466",
    "orange": "#FFB300",
    "blue":   "#3B82F6",
    "text":   "#E8EAFF",
    "muted":  "#8890B8",
    "dim":    "#454878",
}


# ── Feed widget ───────────────────────────────────────────────────────────────

class SevenSegFeedWidget(FeedWidget):
    """
    Thin display widget. Receives annotated QImages from the panel and maps
    mouse clicks back to tracker IDs using the latest FramePacket.
    """

    box_clicked = Signal(int)   # tracker_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pkt   = None
        self._scale = 1.0
        self._ox    = 0
        self._oy    = 0

    def show_raw_frame(self, frame: np.ndarray, _meta=None):
        """Display a raw camera frame while the processor is still loading models.
        Once the processor takes over via update_frame(), this becomes a no-op.
        frame is RGB (as sent by the camera client) — no conversion needed.
        """
        if self._pkt is not None:
            return  # processor has taken over
        lw, lh = self.width(), self.height()
        if lw < 1 or lh < 1:
            return
        dpr    = self.devicePixelRatioF()
        pw, ph = int(lw * dpr), int(lh * dpr)
        fh, fw = frame.shape[:2]
        scale  = min(pw / fw, ph / fh)
        nw     = max(1, int(fw * scale))
        nh     = max(1, int(fh * scale))
        display = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        qimg = QImage(display.data, nw, nh, nw * 3,
                      QImage.Format.Format_RGB888).copy()
        qimg.setDevicePixelRatio(dpr)
        self._pixmap    = QPixmap.fromImage(qimg)
        self._connected = True
        self.update()

    def update_frame(self, qimg: QImage, pkt):
        """Called from the panel after annotation. pkt is kept for click mapping."""
        self._pkt    = pkt
        self._pixmap = QPixmap.fromImage(qimg)
        self._connected = True
        self.update()

        # Compute click-mapping: full-res obb_points → display coordinates
        if pkt is not None:
            fh, fw = pkt.frame.shape[:2]
            lw, lh = self.width(), self.height()
            s = min(lw / max(fw, 1), lh / max(fh, 1))
            self._ox    = (lw - fw * s) / 2
            self._oy    = (lh - fh * s) / 2
            self._scale = 1.0 / s if s > 0 else 1.0

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton or self._pkt is None:
            return
        fx = (ev.position().x() - self._ox) * self._scale
        fy = (ev.position().y() - self._oy) * self._scale
        for i, quad in enumerate(self._pkt.obb_points):
            if i >= len(self._pkt.tracker_ids):
                continue
            if point_in_quad(fx, fy, quad):
                self.box_clicked.emit(int(self._pkt.tracker_ids[i]))
                return


# ── Detail panel ─────────────────────────────────────────────────────────────

class DetailPanel(QFrame):
    """
    Shows the crop, OCR reading, confidence and action buttons for the
    currently selected tracker box.
    """

    flip_changed     = Signal(int, bool)
    assign_request   = Signal(int)
    unassign_request = Signal(int)
    reassign_request = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.selected_tid: Optional[int] = None
        self._is_flipped = False
        self._is_green   = False
        self._meas_name  = ""
        self._build_ui()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Placeholder (no selection) ────────────────────────────────────────
        self.placeholder = QWidget()
        ph_lo  = QVBoxLayout(self.placeholder)
        ph_lbl = QLabel("Select a box\nto inspect")
        ph_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lbl.setStyleSheet(
            f"color: {_C['dim']}; font-size: 11px; padding: 20px 0;"
        )
        ph_lo.addWidget(ph_lbl)
        root.addWidget(self.placeholder)

        # ── Content (box selected) ────────────────────────────────────────────
        self.content = QWidget()
        c = QVBoxLayout(self.content)
        c.setContentsMargins(0, 0, 0, 0)
        c.setSpacing(5)

        # status badge
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFixedHeight(22)
        c.addWidget(self.status_label)

        # header: name / ID
        self.header_label = QLabel()
        self.header_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.header_label.setStyleSheet(f"color: {_C['text']};")
        self.header_label.setWordWrap(True)
        c.addWidget(self.header_label)

        # crop preview
        crop_frame = QFrame()
        crop_frame.setStyleSheet(
            f"background: {_C['bg']}; border: 1px solid {_C['border']}; border-radius: 7px;"
        )
        crop_frame.setFixedHeight(76)
        cf = QVBoxLayout(crop_frame)
        cf.setContentsMargins(4, 4, 4, 4)
        self.crop_label = QLabel()
        self.crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.crop_label.setStyleSheet("background: transparent; border: none;")
        cf.addWidget(self.crop_label)
        c.addWidget(crop_frame)

        # big OCR reading
        self.reading_label = QLabel("---")
        self.reading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reading_label.setFont(QFont("Consolas", 22, QFont.Weight.Bold))
        self.reading_label.setStyleSheet(f"color: {_C['text']};")
        c.addWidget(self.reading_label)

        # confidence
        self.conf_label = QLabel("confidence —")
        self.conf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.conf_label.setStyleSheet(f"color: {_C['dim']}; font-size: 10px;")
        c.addWidget(self.conf_label)

        # validity indicator
        self.validity_label = QLabel()
        self.validity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.validity_label.setFixedHeight(19)
        c.addWidget(self.validity_label)

        c.addSpacing(3)

        # action buttons
        self.flip_btn = self._btn(
            "Flip 180°", _C['bg3'], _C['accent'], _C['bg2']
        )
        self.flip_btn.clicked.connect(self._on_flip)
        c.addWidget(self.flip_btn)

        self.assign_btn = self._btn("Assign Measurement", _C['blue'], "#FFFFFF", "#2563EB")
        self.assign_btn.clicked.connect(
            lambda: self.assign_request.emit(self.selected_tid)
        )
        c.addWidget(self.assign_btn)

        self.reassign_btn = self._btn(
            "Rename / Reassign", _C['bg3'], _C['accent'], _C['bg2']
        )
        self.reassign_btn.clicked.connect(
            lambda: self.reassign_request.emit(self.selected_tid)
        )
        c.addWidget(self.reassign_btn)

        self.stop_btn = self._btn("Stop Storing", "#2D0A0A", _C['red'], "#450A0A")
        self.stop_btn.clicked.connect(
            lambda: self.unassign_request.emit(self.selected_tid)
        )
        c.addWidget(self.stop_btn)

        c.addSpacing(2)
        close_btn = QPushButton("✕  Close")
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {_C['dim']};"
            f" border: 1px solid {_C['border']}; border-radius: 5px; padding: 5px; }}"
            f"QPushButton:hover {{ color: {_C['muted']}; border-color: {_C['dim']}; }}"
        )
        close_btn.clicked.connect(self.deselect)
        c.addWidget(close_btn)
        c.addStretch()

        self.content.setVisible(False)
        root.addWidget(self.content)

    @staticmethod
    def _btn(text: str, bg: str, fg: str, hover: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; font-weight: 600;"
            f" border-radius: 5px; padding: 7px; border: none; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
        )
        return btn

    # ── Public API ────────────────────────────────────────────────────────────

    def select(self, tid: int, is_green: bool, meas_name: str, is_flipped: bool):
        self.selected_tid = tid
        self._is_green    = is_green
        self._meas_name   = meas_name
        self._is_flipped  = is_flipped
        self.placeholder.setVisible(False)
        self.content.setVisible(True)

    def deselect(self):
        self.selected_tid = None
        self.placeholder.setVisible(True)
        self.content.setVisible(False)

    def refresh(self, crop_bgr, text: str, conf: float,
                is_green: bool, meas_name: str, is_verif: bool):
        if self.selected_tid is None:
            return

        self._is_green  = is_green
        self._meas_name = meas_name

        # header
        if meas_name:
            self.header_label.setText(f"{meas_name}   ·   ID {self.selected_tid}")
        else:
            self.header_label.setText(f"Tracker ID {self.selected_tid}")

        # status badge
        if is_verif:
            self._badge("VERIFICATION", "#1E3A5F", "#60A5FA")
        elif is_green:
            self._badge("● STORING", "#052E16", _C['green'])
        else:
            self._badge("○ NOT ASSIGNED", "#2D0A0A", _C['red'])

        # crop preview
        if crop_bgr is not None:
            disp = crop_bgr.copy()
            if self._is_flipped:
                disp = cv2.rotate(disp, cv2.ROTATE_180)
            rgb  = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(
                rgb.data, w, h, w * ch,
                QImage.Format.Format_RGB888,
            ).copy()
            pm = QPixmap.fromImage(qimg).scaled(
                256, 66,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.crop_label.setPixmap(pm)
        else:
            self.crop_label.setText("—")

        # reading + confidence
        self.reading_label.setText(text if text else "---")
        self.conf_label.setText(f"confidence  {conf:.3f}")

        # validity
        numeric = is_valid_numeric(text) if text else False
        if not text or text == "---":
            self.reading_label.setStyleSheet(f"color: {_C['text']};")
            self.validity_label.setVisible(False)
        elif numeric:
            self.reading_label.setStyleSheet(f"color: {_C['text']};")
            if is_green and not is_verif:
                self.validity_label.setText("✓  STORED")
                self.validity_label.setStyleSheet(
                    f"color: {_C['green']}; background: #052E16;"
                    " border-radius: 9px; font-size: 9px; font-weight: 700;"
                )
                self.validity_label.setVisible(True)
            else:
                self.validity_label.setVisible(False)
        else:
            self.reading_label.setStyleSheet(f"color: {_C['orange']};")
            self.validity_label.setText("⚠  NOT NUMERIC — SKIPPED")
            self.validity_label.setStyleSheet(
                f"color: {_C['orange']}; background: #431407;"
                " border-radius: 9px; font-size: 9px; font-weight: 700;"
            )
            self.validity_label.setVisible(True)

        # button visibility
        self.flip_btn.setVisible(True)
        self.assign_btn.setVisible(not is_verif and not is_green)
        self.reassign_btn.setVisible(not is_verif and is_green)
        self.stop_btn.setVisible(not is_verif and is_green)

    def _badge(self, text: str, bg: str, fg: str):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 11px;"
            " font-size: 9px; font-weight: 700; letter-spacing: 1px;"
        )

    def _on_flip(self):
        self._is_flipped = not self._is_flipped
        if self.selected_tid is not None:
            self.flip_changed.emit(self.selected_tid, self._is_flipped)


# ── Naming dialog ─────────────────────────────────────────────────────────────

class NamingDialog(QDialog):
    """Assign or rename a measurement for a tracker box."""

    def __init__(self, existing: List[str], active: set, parent=None):
        super().__init__(parent)
        self.active       = active
        self.chosen_name: Optional[str] = None
        self.setWindowTitle("Assign Measurement")
        self.setMinimumWidth(360)
        self.setStyleSheet(
            f"QDialog   {{ background: {_C['bg2']}; }}"
            f"QLabel    {{ color: {_C['text']}; }}"
            f"QLineEdit {{ background: {_C['bg']}; color: {_C['text']};"
            f"  border: 1px solid {_C['border']}; border-radius: 5px; padding: 7px; }}"
            f"QLineEdit:focus {{ border-color: {_C['accent']}; }}"
            f"QComboBox {{ background: {_C['bg']}; color: {_C['text']};"
            f"  border: 1px solid {_C['border']}; border-radius: 5px; padding: 7px; }}"
            f"QComboBox QAbstractItemView {{ background: {_C['bg2']};"
            f"  color: {_C['text']}; selection-background-color: {_C['bg3']}; }}"
        )
        self._build(existing)

    def _build(self, existing: List[str]):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(18, 18, 18, 18)

        title = QLabel("Assign Measurement")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        lay.addWidget(title)

        sub = QLabel("Give this display a name, or pick an existing idle measurement.")
        sub.setStyleSheet(f"color: {_C['muted']}; font-size: 11px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        lay.addWidget(self._section("NEW NAME"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g.  Pressure_Gauge_1")
        lay.addWidget(self.name_input)

        available = [m for m in existing if m not in self.active]
        if available:
            lay.addWidget(self._section("OR EXISTING IDLE MEASUREMENT"))
            self.combo = QComboBox()
            self.combo.addItem("— select —")
            self.combo.addItems(available)
            lay.addWidget(self.combo)
        else:
            self.combo = None

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(
            f"QPushButton {{ background: {_C['bg3']}; color: {_C['muted']};"
            f" border: 1px solid {_C['border']}; border-radius: 5px; padding: 7px 14px; }}"
            f"QPushButton:hover {{ color: {_C['text']}; }}"
        )
        cancel.clicked.connect(self.reject)

        ok = QPushButton("Confirm")
        ok.setStyleSheet(
            f"QPushButton {{ background: {_C['blue']}; color: #FFFFFF;"
            f" font-weight: 700; border-radius: 5px; padding: 7px 14px; border: none; }}"
            f"QPushButton:hover {{ background: #2563EB; }}"
        )
        ok.clicked.connect(self._on_confirm)

        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)

    @staticmethod
    def _section(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {_C['dim']}; font-size: 9px; letter-spacing: 1px; font-weight: 700;"
        )
        return lbl

    def _on_confirm(self):
        typed    = self.name_input.text().strip()
        selected = None
        if self.combo and self.combo.currentIndex() > 0:
            selected = self.combo.currentText()

        if typed and selected:
            QMessageBox.warning(self, "Ambiguous",
                                "Enter a new name OR choose from the list — not both.")
            return
        if not typed and not selected:
            QMessageBox.warning(self, "Empty", "Please provide a measurement name.")
            return

        name = typed or selected
        if typed and typed in self.active:
            QMessageBox.warning(self, "In Use",
                                f"'{typed}' is already being stored by another box.")
            return

        self.chosen_name = name
        self.accept()
