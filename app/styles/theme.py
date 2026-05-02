"""
VisionForge Theme
Deep-space industrial aesthetic: near-black navy base, electric cyan accents,
sharp typographic hierarchy. Every color is purposeful.
"""

# ── Palette ─────────────────────────────────────────────────────────────────
C = {
    "bg_deep":      "#060612",   # deepest background
    "bg_panel":     "#0C0C1E",   # sidebar / panels
    "bg_card":      "#111128",   # card surfaces
    "bg_input":     "#181830",   # inputs / combos
    "bg_hover":     "#1C1C38",   # hover state
    "bg_selected":  "#1A1A40",   # selected nav item

    "accent":       "#00CFFF",   # primary cyan
    "accent_dim":   "#0099CC",   # pressed / dimmed cyan
    "accent_glow":  "rgba(0, 207, 255, 30)",  # soft glow fill

    "purple":       "#7C3AED",   # secondary accent

    "success":      "#00E676",   # connected / ok
    "warning":      "#FFB300",   # partial / warning
    "error":        "#FF4466",   # disconnected / error

    "text_primary":   "#E8EAFF",
    "text_secondary": "#8890B8",
    "text_muted":     "#454878",
    "text_accent":    "#00CFFF",

    "border":        "#1A1A38",
    "border_bright": "#282858",
    "border_accent": "rgba(0, 207, 255, 60)",
    "separator":     "#141430",
}

STYLESHEET = f"""

/* ── Base ──────────────────────────────────────────────────────────────── */
QMainWindow, QDialog {{
    background-color: {C["bg_deep"]};
    color: {C["text_primary"]};
}}

QWidget {{
    background-color: transparent;
    color: {C["text_primary"]};
    font-family: "Segoe UI", "SF Pro Display", "Ubuntu", Arial, sans-serif;
    font-size: 13px;
}}

/* ── Scroll bars ────────────────────────────────────────────────────────── */
QScrollArea {{
    border: none;
    background-color: transparent;
}}

QScrollBar:vertical {{
    background: {C["bg_panel"]};
    width: 6px;
    border-radius: 3px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C["border_bright"]};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C["accent_dim"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    background: {C["bg_panel"]};
    height: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {C["border_bright"]};
    border-radius: 3px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {C["accent_dim"]};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Labels ─────────────────────────────────────────────────────────────── */
QLabel {{
    background-color: transparent;
    color: {C["text_primary"]};
}}
QLabel[class="title"] {{
    font-size: 22px;
    font-weight: 700;
    color: {C["accent"]};
    letter-spacing: 2px;
}}
QLabel[class="subtitle"] {{
    font-size: 11px;
    color: {C["text_secondary"]};
    letter-spacing: 1px;
}}
QLabel[class="section-header"] {{
    font-size: 11px;
    font-weight: 600;
    color: {C["text_muted"]};
    letter-spacing: 2px;
    padding: 0 4px;
}}
QLabel[class="value"] {{
    font-family: "Consolas", "Courier New", monospace;
    font-size: 13px;
    color: {C["accent"]};
}}
QLabel[class="disconnected-label"] {{
    font-size: 15px;
    color: {C["text_muted"]};
}}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {C["bg_card"]};
    color: {C["text_primary"]};
    border: 1px solid {C["border_bright"]};
    border-radius: 6px;
    padding: 7px 18px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {C["bg_hover"]};
    border-color: {C["accent_dim"]};
    color: {C["accent"]};
}}
QPushButton:pressed {{
    background-color: {C["bg_selected"]};
    border-color: {C["accent"]};
}}
QPushButton:disabled {{
    background-color: {C["bg_panel"]};
    color: {C["text_muted"]};
    border-color: {C["border"]};
}}

QPushButton[class="primary"] {{
    background-color: {C["accent"]};
    color: #000010;
    border: none;
    font-weight: 600;
    font-size: 13px;
    padding: 9px 28px;
    border-radius: 6px;
}}
QPushButton[class="primary"]:hover {{
    background-color: #33D9FF;
    color: #000010;
}}
QPushButton[class="primary"]:pressed {{
    background-color: {C["accent_dim"]};
}}
QPushButton[class="primary"]:disabled {{
    background-color: {C["text_muted"]};
    color: {C["bg_panel"]};
}}

QPushButton[class="danger"] {{
    background-color: transparent;
    color: {C["error"]};
    border: 1px solid {C["error"]};
    border-radius: 6px;
    padding: 6px 16px;
}}
QPushButton[class="danger"]:hover {{
    background-color: rgba(255, 68, 102, 15);
}}

QPushButton[class="ghost"] {{
    background-color: transparent;
    color: {C["text_secondary"]};
    border: none;
    padding: 4px 10px;
    font-size: 12px;
}}
QPushButton[class="ghost"]:hover {{
    color: {C["accent"]};
    background-color: {C["accent_glow"]};
    border-radius: 4px;
}}

QPushButton[class="connect-btn"] {{
    background-color: transparent;
    color: {C["accent"]};
    border: 1px solid {C["border_accent"]};
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton[class="connect-btn"]:hover {{
    background-color: {C["accent_glow"]};
}}

/* ── Inputs ──────────────────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {C["bg_input"]};
    color: {C["text_primary"]};
    border: 1px solid {C["border_bright"]};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: {C["accent_dim"]};
}}
QLineEdit:focus {{
    border-color: {C["accent"]};
    background-color: {C["bg_hover"]};
}}
QLineEdit:disabled {{
    color: {C["text_muted"]};
    border-color: {C["border"]};
}}

/* ── ComboBox ────────────────────────────────────────────────────────────── */
QComboBox {{
    background-color: {C["bg_input"]};
    color: {C["text_primary"]};
    border: 1px solid {C["border_bright"]};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    min-width: 100px;
}}
QComboBox:hover {{
    border-color: {C["accent_dim"]};
}}
QComboBox:focus {{
    border-color: {C["accent"]};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C["text_secondary"]};
    width: 0;
    height: 0;
}}
QComboBox QAbstractItemView {{
    background-color: {C["bg_card"]};
    color: {C["text_primary"]};
    border: 1px solid {C["border_bright"]};
    selection-background-color: {C["bg_selected"]};
    selection-color: {C["accent"]};
    outline: none;
    padding: 4px;
}}
QComboBox:disabled {{
    color: {C["text_muted"]};
    border-color: {C["border"]};
}}

/* ── SpinBox ─────────────────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background-color: {C["bg_input"]};
    color: {C["text_primary"]};
    border: 1px solid {C["border_bright"]};
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 13px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {C["accent"]};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: {C["bg_hover"]};
    border: none;
    width: 18px;
    border-radius: 3px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {C["border_bright"]};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {C["text_muted"]};
    border-color: {C["border"]};
}}

/* ── Slider ──────────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    background: {C["bg_input"]};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {C["accent"]};
    border: 2px solid {C["bg_deep"]};
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover {{
    background: #33D9FF;
}}
QSlider::sub-page:horizontal {{
    background: {C["accent"]};
    border-radius: 2px;
}}
QSlider:disabled::groove:horizontal {{
    background: {C["border"]};
}}
QSlider:disabled::handle:horizontal {{
    background: {C["text_muted"]};
}}
QSlider:disabled::sub-page:horizontal {{
    background: {C["text_muted"]};
}}

/* ── ProgressBar ─────────────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {C["bg_input"]};
    border: none;
    border-radius: 2px;
    height: 3px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {C["accent"]};
    border-radius: 2px;
}}

/* ── GroupBox ────────────────────────────────────────────────────────────── */
QGroupBox {{
    background-color: {C["bg_card"]};
    border: 1px solid {C["border"]};
    border-radius: 8px;
    margin-top: 20px;
    padding: 12px 10px 10px 10px;
    font-size: 11px;
    font-weight: 600;
    color: {C["text_muted"]};
    letter-spacing: 1.5px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -1px;
    background-color: {C["bg_card"]};
    padding: 0 6px;
    color: {C["text_muted"]};
    letter-spacing: 1.5px;
    font-size: 10px;
    font-weight: 700;
}}

/* ── Splitter ────────────────────────────────────────────────────────────── */
QSplitter::handle {{
    background-color: {C["border"]};
    width: 1px;
    height: 1px;
}}
QSplitter::handle:hover {{
    background-color: {C["accent_dim"]};
}}

/* ── Tooltips ────────────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {C["bg_card"]};
    color: {C["text_primary"]};
    border: 1px solid {C["border_bright"]};
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 12px;
}}

"""
