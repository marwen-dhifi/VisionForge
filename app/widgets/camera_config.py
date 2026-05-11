"""
CameraConfigPanel — scrollable panel for all Baumer camera parameters.

Each control is wired to immediately send a parameter update via
CameraClient.send_params(). Controls are enabled/disabled based on Auto modes.
"""

from PySide6.QtWidgets import (
    QWidget, QScrollArea, QVBoxLayout, QHBoxLayout,
    QLabel, QGroupBox, QSlider, QSpinBox, QDoubleSpinBox,
    QComboBox, QPushButton
)
from PySide6.QtCore import Qt, QTimer


class _Row(QWidget):
    """A label + control row inside a group."""
    def __init__(self, label: str, control: QWidget, parent=None):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(10)

        lbl = QLabel(label, self)
        lbl.setFixedWidth(130)
        lbl.setStyleSheet("color: #8890B8; font-size: 12px;")

        lo.addWidget(lbl)
        lo.addWidget(control, 1)


class _SliderSpinRow(QWidget):
    """Horizontal slider + spinbox pair."""
    def __init__(self, min_v, max_v, default, decimals=0, parent=None):
        super().__init__(parent)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(8)

        if decimals > 0:
            self._spin = QDoubleSpinBox()
            self._spin.setDecimals(decimals)
            self._spin.setSingleStep(0.1)
        else:
            self._spin = QSpinBox()

        self._spin.setRange(min_v, max_v)
        self._spin.setValue(default)
        self._spin.setFixedWidth(78)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        # Slider works in integer space; multiply by 10 for float params
        factor = 10 if decimals > 0 else 1
        self._factor = factor
        self._slider.setRange(int(min_v * factor), int(max_v * factor))
        self._slider.setValue(int(default * factor))

        self._slider.valueChanged.connect(
            lambda v: self._spin.setValue(v / factor)
        )
        self._spin.valueChanged.connect(
            lambda v: self._slider.setValue(int(v * factor))
        )

        lo.addWidget(self._slider, 1)
        lo.addWidget(self._spin)

    @property
    def value(self):
        return self._spin.value()

    def set_enabled(self, on: bool):
        self._slider.setEnabled(on)
        self._spin.setEnabled(on)

    def connect_changed(self, slot):
        self._spin.valueChanged.connect(slot)


class CameraConfigPanel(QWidget):
    """
    Full parameter panel for the Baumer VAX-50C camera.
    Pass a camera_client to enable live sending; pass None to render read-only.
    """

    def __init__(self, camera_client=None, parent=None):
        super().__init__(parent)
        self._client = camera_client
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._flush_params)
        self._pending: dict = {}

        self._setup_ui()

    def set_client(self, client):
        self._client = client

    # ── UI Build ─────────────────────────────────────────────────────────────

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        lo = QVBoxLayout(container)
        lo.setContentsMargins(12, 12, 12, 20)
        lo.setSpacing(14)

        # Header
        hdr = QLabel("CAMERA PARAMETERS")
        hdr.setProperty("class", "section-header")
        lo.addWidget(hdr)

        lo.addWidget(self._build_acquisition_group())
        lo.addWidget(self._build_exposure_group())
        lo.addWidget(self._build_gain_group())
        lo.addWidget(self._build_wb_group())
        lo.addWidget(self._build_brightness_group())
        lo.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ── Groups ────────────────────────────────────────────────────────────────

    def _build_acquisition_group(self) -> QGroupBox:
        grp = QGroupBox("ACQUISITION")
        lo  = QVBoxLayout(grp)
        lo.setSpacing(8)

        # FPS
        self._fps = _SliderSpinRow(1, 30, 30)
        self._fps.connect_changed(lambda v: self._schedule("fps", int(v)))
        lo.addWidget(_Row("Frame rate (fps)", self._fps))

        # Resolution (read-only)
        res_label = QLabel("2448 × 2048  (fixed)")
        res_label.setStyleSheet("color: #454878; font-size: 12px; font-family: Consolas;")
        lo.addWidget(_Row("Resolution", res_label))

        # Pixel format (read-only)
        fmt_label = QLabel("BayerRG8")
        fmt_label.setStyleSheet("color: #454878; font-size: 12px; font-family: Consolas;")
        lo.addWidget(_Row("Pixel format", fmt_label))

        return grp

    def _build_exposure_group(self) -> QGroupBox:
        grp = QGroupBox("EXPOSURE")
        lo  = QVBoxLayout(grp)
        lo.setSpacing(8)

        self._exp_auto = QComboBox()
        self._exp_auto.addItems(["Off", "Continuous", "Once"])
        self._exp_auto.setCurrentText("Off")
        self._exp_auto.currentTextChanged.connect(self._on_exp_auto_changed)
        lo.addWidget(_Row("Auto mode", self._exp_auto))

        self._exp_time = _SliderSpinRow(100, 100_000, 60_000)
        self._exp_time.connect_changed(
            lambda v: self._schedule("ExposureTime", int(v))
        )
        lo.addWidget(_Row("Exposure (µs)", self._exp_time))

        return grp

    def _build_gain_group(self) -> QGroupBox:
        grp = QGroupBox("GAIN")
        lo  = QVBoxLayout(grp)
        lo.setSpacing(8)

        self._gain_auto = QComboBox()
        self._gain_auto.addItems(["Off", "Continuous", "Once"])
        self._gain_auto.setCurrentText("Off")
        self._gain_auto.currentTextChanged.connect(self._on_gain_auto_changed)
        lo.addWidget(_Row("Auto mode", self._gain_auto))

        self._gain = _SliderSpinRow(0.0, 24.0, 9.0, decimals=1)
        self._gain.connect_changed(
            lambda v: self._schedule("Gain", round(float(v), 1))
        )
        lo.addWidget(_Row("Gain (dB)", self._gain))

        return grp

    def _build_wb_group(self) -> QGroupBox:
        grp = QGroupBox("WHITE BALANCE")
        lo  = QVBoxLayout(grp)
        lo.setSpacing(8)

        self._wb_auto = QComboBox()
        self._wb_auto.addItems(["Off", "Continuous", "Once"])
        self._wb_auto.setCurrentText("Once")
        self._wb_auto.currentTextChanged.connect(
            lambda v: self._schedule("BalanceWhiteAuto", v)
        )
        lo.addWidget(_Row("Auto mode", self._wb_auto))

        wb_now_btn = QPushButton("Apply Once Now")
        wb_now_btn.setProperty("class", "ghost")
        wb_now_btn.clicked.connect(
            lambda: self._send_now({"BalanceWhiteAuto": "Once"})
        )
        lo.addWidget(wb_now_btn)

        return grp

    def _build_brightness_group(self) -> QGroupBox:
        grp = QGroupBox("AUTO-BRIGHTNESS TARGET")
        lo  = QVBoxLayout(grp)
        lo.setSpacing(8)

        self._brightness = _SliderSpinRow(0, 255, 128)
        self._brightness.connect_changed(
            lambda v: self._schedule("BrightnessAutoNominalValue", int(v))
        )
        lo.addWidget(_Row("Target (0–255)", self._brightness))

        tip = QLabel("Active when ExposureAuto or GainAuto is on.")
        tip.setStyleSheet("color: #454878; font-size: 11px; padding-left: 140px;")
        lo.addWidget(tip)

        return grp

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_exp_auto_changed(self, mode: str):
        self._exp_time.set_enabled(mode == "Off")
        self._schedule("ExposureAuto", mode)

    def _on_gain_auto_changed(self, mode: str):
        self._gain.set_enabled(mode == "Off")
        self._schedule("GainAuto", mode)

    # ── Debounced send ────────────────────────────────────────────────────────

    def _schedule(self, key: str, value):
        """Buffer rapid slider moves and send once after 300 ms quiet."""
        self._pending[key] = value
        self._debounce.start()

    def _flush_params(self):
        if self._client and self._pending:
            self._client.send_params(dict(self._pending))
            self._pending.clear()

    def _send_now(self, params: dict):
        if self._client:
            self._client.send_params(params)
