"""
MediaPanel — capture images and video, manage media directories.
"""

import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFrame, QInputDialog,
    QMessageBox, QDoubleSpinBox, QSpinBox, QScrollArea, QAbstractSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QLocale
from PySide6.QtGui  import QColor, QFont

from VisionForge.app.core.media_manager import MediaManager, IMAGES_ROOT, VIDEOS_ROOT


def _btn(label: str, color: str, fixed_h: int = 34) -> QPushButton:
    b = QPushButton(label)
    b.setFixedHeight(fixed_h)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton {{
            background: #181830; color: {color};
            border: 1px solid {color}55; border-radius: 5px;
            font-size: 12px; font-weight: 600; padding: 0 10px;
        }}
        QPushButton:hover   {{ background: #22224A; border-color: {color}AA; }}
        QPushButton:pressed {{ background: #111128; }}
        QPushButton:disabled {{ color: #454878; border-color: #2A2A48; }}
    """)
    return b


def _hdr(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color: #454878; font-size: 10px; font-weight: 700; letter-spacing: 2px;"
    )
    return lbl


def _sep() -> QFrame:
    f = QFrame(); f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color: #1A1A38;")
    return f


def _count_files(path: str) -> int:
    """Count files (not subdirs) directly in path."""
    try:
        return sum(
            1 for e in os.scandir(path)
            if e.is_file() and not e.name.startswith(".")
        )
    except Exception:
        return 0


class _DirList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QListWidget {
                background: #0C0C1E; border: 1px solid #1A1A38;
                border-radius: 6px; color: #C0C4E8;
                font-size: 12px; outline: none;
            }
            QListWidget::item { padding: 6px 10px; }
            QListWidget::item:selected {
                background: #1E1E3C; color: #00CFFF;
                border-left: 2px solid #00CFFF;
            }
            QListWidget::item:hover { background: #14142A; }
        """)

    def add_root_entry(self, root: str):
        count = _count_files(root)
        item = QListWidgetItem(f"  /  (root)   [{count}]")
        item.setData(Qt.ItemDataRole.UserRole, "")
        item.setForeground(QColor("#7C3AED"))
        self.addItem(item)

    def add_dir(self, root: str, name: str):
        count = _count_files(os.path.join(root, name))
        item = QListWidgetItem(f"  📁  {name}   [{count}]")
        item.setData(Qt.ItemDataRole.UserRole, name)
        self.addItem(item)

    def selected_subdir(self) -> str:
        items = self.selectedItems()
        if not items:
            return ""
        return items[0].data(Qt.ItemDataRole.UserRole) or ""


class MediaPanel(QWidget):

    def __init__(self, media_manager: MediaManager, parent=None):
        super().__init__(parent)
        self._mgr         = media_manager
        self._last_frame  = None
        self._mode        = "images"

        # Auto-capture state
        self._auto_timer      = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_tick)
        self._auto_remaining  = 0
        self._auto_running    = False

        self.setStyleSheet("background-color: #0C0C1E;")

        # Wrap in scroll area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: #0C0C1E; }"
            "QScrollBar:vertical { background: #0C0C1E; width: 6px; }"
            "QScrollBar::handle:vertical { background: #1A1A38; border-radius: 3px; }"
        )

        inner = QWidget(); inner.setStyleSheet("background: #0C0C1E;")
        self._lo = QVBoxLayout(inner)
        self._lo.setContentsMargins(16, 14, 16, 16)
        self._lo.setSpacing(10)

        self._build()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

        self._mgr.directories_changed.connect(self._refresh)
        self._mgr.image_saved.connect(self._on_image_saved)
        self._mgr.recording_started.connect(self._on_rec_started)
        self._mgr.recording_stopped.connect(self._on_rec_stopped)
        self._mgr.error_occurred.connect(self._on_error)
        self._refresh()

    # ── Build ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _setup_spin(spin):
        """Apply PlusMinus buttons (always visible) and English locale (decimal point)."""
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        spin.setLocale(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
        spin.setStyleSheet(MediaPanel._spin_style())

    def _build(self):
        lo = self._lo

        # Tab toggle
        tog = QHBoxLayout(); tog.setSpacing(0)
        self._tab_img = QPushButton("Images")
        self._tab_vid = QPushButton("Videos")
        for b in (self._tab_img, self._tab_vid):
            b.setFixedHeight(30); b.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_img.setStyleSheet(self._tab_style(True))
        self._tab_vid.setStyleSheet(self._tab_style(False))
        self._tab_img.clicked.connect(lambda: self._set_mode("images"))
        self._tab_vid.clicked.connect(lambda: self._set_mode("videos"))
        tog.addWidget(self._tab_img); tog.addWidget(self._tab_vid)
        lo.addLayout(tog)

        # Directory section
        lo.addWidget(_hdr("SAVE DIRECTORY"))

        self._dir_list = _DirList()
        self._dir_list.setMaximumHeight(160)
        lo.addWidget(self._dir_list)

        dir_btns = QHBoxLayout(); dir_btns.setSpacing(6)
        self._btn_new    = _btn("+ New",  "#00CFFF")
        self._btn_rename = _btn("Rename", "#FFB300")
        self._btn_delete = _btn("Delete", "#FF4466")
        self._btn_rename.setEnabled(False)
        self._btn_delete.setEnabled(False)
        self._btn_new.clicked.connect(self._new_dir)
        self._btn_rename.clicked.connect(self._rename_dir)
        self._btn_delete.clicked.connect(self._delete_dir)
        dir_btns.addWidget(self._btn_new)
        dir_btns.addWidget(self._btn_rename)
        dir_btns.addWidget(self._btn_delete)
        lo.addLayout(dir_btns)
        self._dir_list.itemSelectionChanged.connect(self._on_dir_select)

        lo.addWidget(_sep())

        # ── IMAGE CONTROLS ────────────────────────────────────────────
        self._img_widget = QWidget(); self._img_widget.setStyleSheet("background:transparent;")
        img_lo = QVBoxLayout(self._img_widget); img_lo.setContentsMargins(0,0,0,0); img_lo.setSpacing(8)

        img_lo.addWidget(_hdr("CAPTURE"))

        self._btn_capture = _btn("📷  Capture Image", "#00E676", fixed_h=42)
        self._btn_capture.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self._btn_capture.clicked.connect(self._capture_image)
        img_lo.addWidget(self._btn_capture)

        img_lo.addWidget(_sep())

        # Auto-capture section
        img_lo.addWidget(_hdr("AUTO CAPTURE"))

        # Interval row
        int_row = QHBoxLayout(); int_row.setSpacing(8)
        int_row.addWidget(QLabel("Every"))
        self._interval_spin = QDoubleSpinBox()
        self._interval_spin.setMinimum(0.5); self._interval_spin.setMaximum(3600)
        self._interval_spin.setValue(2.0); self._interval_spin.setSingleStep(0.5)
        self._interval_spin.setSuffix("  s")
        self._interval_spin.setFixedWidth(90)
        self._setup_spin(self._interval_spin)
        int_row.addWidget(self._interval_spin)
        int_row.addWidget(QLabel("for"))
        self._count_spin = QSpinBox()
        self._count_spin.setMinimum(1); self._count_spin.setMaximum(9999)
        self._count_spin.setValue(10)
        self._count_spin.setFixedWidth(70)
        self._setup_spin(self._count_spin)
        int_row.addWidget(self._count_spin)
        int_row.addWidget(QLabel("shots"))
        int_row.addStretch()
        for lbl in self._img_widget.findChildren(QLabel):
            lbl.setStyleSheet("color: #8890B8; font-size: 12px; background: transparent;")
        img_lo.addLayout(int_row)

        self._btn_auto = _btn("▶  Start Auto Capture", "#7C3AED", fixed_h=42)
        self._btn_auto.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self._btn_auto.clicked.connect(self._toggle_auto)
        img_lo.addWidget(self._btn_auto)

        self._auto_status = QLabel("")
        self._auto_status.setStyleSheet("color: #7C3AED; font-size: 11px; background: transparent;")
        self._auto_status.setWordWrap(True)
        img_lo.addWidget(self._auto_status)

        lo.addWidget(self._img_widget)

        # ── VIDEO CONTROLS ────────────────────────────────────────────
        self._vid_widget = QWidget(); self._vid_widget.setStyleSheet("background:transparent;")
        vid_lo = QVBoxLayout(self._vid_widget); vid_lo.setContentsMargins(0,0,0,0); vid_lo.setSpacing(8)

        vid_lo.addWidget(_hdr("RECORDING"))

        fps_row = QHBoxLayout(); fps_row.setSpacing(8)
        fps_lbl = QLabel("FPS"); fps_lbl.setStyleSheet("color: #8890B8; font-size: 12px; background:transparent;")
        self._fps_spin = QDoubleSpinBox()
        self._fps_spin.setMinimum(1.0); self._fps_spin.setMaximum(60.0)
        self._fps_spin.setValue(10.0); self._fps_spin.setSingleStep(1.0)
        self._setup_spin(self._fps_spin)
        fps_row.addWidget(fps_lbl); fps_row.addStretch(); fps_row.addWidget(self._fps_spin)
        vid_lo.addLayout(fps_row)

        self._btn_record = _btn("⏺  Start Recording", "#FF4466", fixed_h=42)
        self._btn_record.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self._btn_record.clicked.connect(self._toggle_record)
        vid_lo.addWidget(self._btn_record)

        lo.addWidget(self._vid_widget)
        self._vid_widget.setVisible(False)

        # Status
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #8890B8; font-size: 11px; background: transparent;")
        self._status_lbl.setWordWrap(True)
        lo.addWidget(self._status_lbl)

        lo.addStretch()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def on_frame(self, frame, meta):
        self._last_frame = frame
        if self._mgr.is_recording:
            self._mgr.write_frame(frame)

    def _set_mode(self, mode: str):
        self._mode = mode
        self._tab_img.setStyleSheet(self._tab_style(mode == "images"))
        self._tab_vid.setStyleSheet(self._tab_style(mode == "videos"))
        self._img_widget.setVisible(mode == "images")
        self._vid_widget.setVisible(mode == "videos")
        self._refresh()

    def _refresh(self):
        root = IMAGES_ROOT if self._mode == "images" else VIDEOS_ROOT
        prev = self._dir_list.selected_subdir()
        self._dir_list.clear()
        self._dir_list.add_root_entry(root)
        for d in self._mgr.list_dirs(root):
            self._dir_list.add_dir(root, d)
        # Restore selection
        for i in range(self._dir_list.count()):
            item = self._dir_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == prev:
                self._dir_list.setCurrentItem(item)
                return
        self._dir_list.setCurrentRow(0)

    def _on_dir_select(self):
        items = self._dir_list.selectedItems()
        is_root = not items or items[0].data(Qt.ItemDataRole.UserRole) == ""
        self._btn_rename.setEnabled(not is_root)
        self._btn_delete.setEnabled(not is_root)

    def _current_root(self):
        return IMAGES_ROOT if self._mode == "images" else VIDEOS_ROOT

    def _new_dir(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name.strip():
            self._mgr.create_dir(self._current_root(), name.strip())

    def _rename_dir(self):
        old = self._dir_list.selected_subdir()
        if not old: return
        new, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        if ok and new.strip():
            self._mgr.rename_dir(self._current_root(), old, new.strip())

    def _delete_dir(self):
        name = self._dir_list.selected_subdir()
        if not name: return
        reply = QMessageBox.question(
            self, "Delete Folder",
            f"Delete '{name}' and all its contents?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._mgr.delete_dir(self._current_root(), name)

    def _capture_image(self):
        if self._last_frame is None:
            self._status_lbl.setText("No frame yet."); return
        self._mgr.capture_image(self._last_frame, self._dir_list.selected_subdir())

    # ── Auto capture ──────────────────────────────────────────────────────────

    def _toggle_auto(self):
        if self._auto_running:
            self._stop_auto()
        else:
            self._start_auto()

    def _start_auto(self):
        if self._last_frame is None:
            self._auto_status.setText("No frame yet."); return
        self._auto_remaining = self._count_spin.value()
        self._auto_running   = True
        interval_ms = int(self._interval_spin.value() * 1000)
        self._auto_timer.start(interval_ms)
        self._btn_auto.setText("⏹  Stop Auto Capture")
        self._btn_auto.setStyleSheet(
            self._btn_auto.styleSheet().replace("#7C3AED", "#FFB300")
        )
        self._interval_spin.setEnabled(False)
        self._count_spin.setEnabled(False)
        self._update_auto_status()

    def _stop_auto(self):
        self._auto_timer.stop()
        self._auto_running = False
        self._btn_auto.setText("▶  Start Auto Capture")
        self._btn_auto.setStyleSheet(
            self._btn_auto.styleSheet().replace("#FFB300", "#7C3AED")
        )
        self._interval_spin.setEnabled(True)
        self._count_spin.setEnabled(True)
        self._auto_status.setText("")
        self._refresh()  # update counts once after all captures done

    def _auto_tick(self):
        if self._last_frame is None:
            return
        self._mgr.capture_image(self._last_frame, self._dir_list.selected_subdir())
        self._auto_remaining -= 1
        if self._auto_remaining <= 0:
            self._stop_auto()
            self._auto_status.setText("✔  Auto capture complete.")
        else:
            self._update_auto_status()

    def _update_auto_status(self):
        total = self._count_spin.value()
        done  = total - self._auto_remaining
        self._auto_status.setText(
            f"Capturing…  {done} / {total}  "
            f"({self._interval_spin.value():.1f}s interval)"
        )

    # ── Recording ─────────────────────────────────────────────────────────────

    def _toggle_record(self):
        if self._mgr.is_recording:
            self._mgr.stop_recording()
        else:
            if self._last_frame is None:
                self._status_lbl.setText("No frame yet."); return
            self._mgr.start_recording(
                self._last_frame,
                self._dir_list.selected_subdir(),
                fps=self._fps_spin.value()
            )

    # ── Manager callbacks ─────────────────────────────────────────────────────

    def _on_image_saved(self, path: str):
        self._status_lbl.setText(f"✔  {os.path.basename(path)}")
        # Only refresh dir counts when NOT auto-capturing (to avoid
        # clearing the selection mid-sequence which drops captures)
        if not self._auto_running:
            self._refresh()
        QTimer.singleShot(3000, lambda: self._status_lbl.setText(""))

    def _on_rec_started(self, path: str):
        self._btn_record.setText("⏹  Stop Recording")
        self._btn_record.setStyleSheet(
            self._btn_record.styleSheet().replace("#FF4466", "#FFB300")
        )
        self._status_lbl.setText(f"⏺  {os.path.basename(path)}")

    def _on_rec_stopped(self, path: str):
        self._btn_record.setText("⏺  Start Recording")
        self._btn_record.setStyleSheet(
            self._btn_record.styleSheet().replace("#FFB300", "#FF4466")
        )
        self._status_lbl.setText(f"✔  Saved: {os.path.basename(path)}")
        self._refresh()
        QTimer.singleShot(4000, lambda: self._status_lbl.setText(""))

    def _on_error(self, msg: str):
        self._status_lbl.setText(f"✖  {msg}")

    # ── Style helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _tab_style(active: bool) -> str:
        if active:
            return (
                "QPushButton { background:#1A1A38; color:#00CFFF;"
                " border:1px solid #00CFFF55; border-radius:0px;"
                " font-size:12px; font-weight:700; padding:0 12px; }"
            )
        return (
            "QPushButton { background:#111128; color:#454878;"
            " border:1px solid #1A1A38; border-radius:0px;"
            " font-size:12px; padding:0 12px; }"
            "QPushButton:hover { color:#8890B8; background:#14142A; }"
        )

    @staticmethod
    def _spin_style() -> str:
        # No button sub-control styling — let PlusMinus symbols render as text
        return (
            "QDoubleSpinBox, QSpinBox {"
            " background:#111128; color:#C0C4E8;"
            " border:1px solid #1A1A38; border-radius:4px;"
            " padding:3px 6px; font-size:12px; }"
            "QDoubleSpinBox::up-button, QSpinBox::up-button {"
            " background:#1A1A38; border:none; width:18px;"
            " border-top-right-radius:4px; }"
            "QDoubleSpinBox::down-button, QSpinBox::down-button {"
            " background:#1A1A38; border:none; width:18px;"
            " border-bottom-right-radius:4px; border-top:1px solid #0C0C1E; }"
            "QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,"
            "QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {"
            " background:#2A2A48; }"
        )