"""
ConnectionDialog — hardware IP entry and connection testing.

Handles all four cases:
  • Both OK        → emits connection_established and closes
  • Camera only OK → warning, user may proceed
  • Arm only OK    → warning, user may proceed
  • Both fail      → error, retry option only
"""

import zmq

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QFont


# ── Button stylesheets ────────────────────────────────────────────────────────

_BTN_VIOLET = """
    QPushButton {
        background-color: #7C3AED;
        color: #FFFFFF;
        border: none;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 600;
        padding: 0 24px;
    }
    QPushButton:hover {
        background-color: #9333EA;
    }
    QPushButton:pressed {
        background-color: #6D28D9;
    }
    QPushButton:disabled {
        background-color: #3B2A6B;
        color: #7C6B9E;
    }
"""

_BTN_GHOST = """
    QPushButton {
        background-color: transparent;
        color: #8890B8;
        border: 1px solid #282848;
        border-radius: 6px;
        font-size: 13px;
        padding: 0 18px;
    }
    QPushButton:hover {
        color: #E8EAFF;
        border-color: #454878;
    }
"""


# ── Connection test worker ────────────────────────────────────────────────────

class _ConnectionWorker(QThread):
    finished = Signal(bool, bool)   # cam_ok, arm_ok

    def __init__(self, cam_ip: str, arm_ip: str):
        super().__init__()
        self._cam_ip = cam_ip
        self._arm_ip = arm_ip

    def run(self):
        cam_ok = self._test_camera(self._cam_ip)
        arm_ok = self._test_arm(self._arm_ip)
        self.finished.emit(cam_ok, arm_ok)

    def _test_camera(self, ip: str) -> bool:
        try:
            ctx = zmq.Context()
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.RCVTIMEO, 3000)
            sock.setsockopt(zmq.SNDTIMEO, 3000)
            sock.setsockopt(zmq.LINGER, 0)
            sock.connect(f"tcp://{ip}:5556")
            sock.send_json({"fps": 30})
            reply = sock.recv_json()
            sock.close()
            ctx.term()
            return reply.get("status") == "ok"
        except Exception as e:
            print(f"[Connection] Camera test failed: {e}")
            return False

    def _test_arm(self, ip: str) -> bool:
        try:
            from xarm.wrapper import XArmAPI
            arm = XArmAPI(ip)
            connected = arm.connected
            arm.disconnect()
            return connected
        except Exception as e:
            print(f"[Connection] Arm test failed: {e}")
            return False


# ── Dialog ────────────────────────────────────────────────────────────────────

class ConnectionDialog(QDialog):
    connection_established = Signal(object, object, str, str)   # cam, arm, cam_ip, arm_ip

    CAM_DEFAULT = "10.6.51.140"
    ARM_DEFAULT  = "10.6.51.141"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VisionForge — Connect")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint
        )
        self.setModal(True)
        self.setFixedWidth(480)

        self._worker = None
        self._cam_ok = False
        self._arm_ok = False

        self._setup_ui()
        self._center()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setStyleSheet(
            "background-color: #0C0C1E;"
            "border: 1px solid rgba(124,58,237,120);"
            "border-radius: 12px;"
        )

        lo = QVBoxLayout(self)
        lo.setContentsMargins(40, 36, 40, 36)
        lo.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        hdr_label = QLabel("Initialize Connection")
        hdr_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Light))
        hdr_label.setStyleSheet("color: #E8EAFF; border: none;")
        lo.addWidget(hdr_label)

        sub_label = QLabel("Enter IP addresses for your hardware devices.")
        sub_label.setStyleSheet("color: #8890B8; font-size: 12px; border: none;")
        lo.addWidget(sub_label)
        lo.addSpacing(28)

        # ── Camera field ─────────────────────────────────────────────────────
        lo.addWidget(self._field_label("◉  CAMERA", "#00CFFF"))
        lo.addSpacing(6)
        self._cam_ip = QLineEdit(self.CAM_DEFAULT)
        self._cam_ip.setPlaceholderText("e.g. 10.6.51.140")
        self._cam_ip.setFixedHeight(42)
        self._cam_ip.setStyleSheet(self._input_style())
        lo.addWidget(self._cam_ip)
        lo.addSpacing(18)

        # ── Arm field ────────────────────────────────────────────────────────
        lo.addWidget(self._field_label("⬡  XARM 5", "#7C3AED"))
        lo.addSpacing(6)
        self._arm_ip = QLineEdit(self.ARM_DEFAULT)
        self._arm_ip.setPlaceholderText("e.g. 10.6.51.141")
        self._arm_ip.setFixedHeight(42)
        self._arm_ip.setStyleSheet(self._input_style())
        lo.addWidget(self._arm_ip)
        lo.addSpacing(24)

        # ── Connect button ───────────────────────────────────────────────────
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setFixedHeight(44)
        self._connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._connect_btn.setStyleSheet(_BTN_VIOLET)
        self._connect_btn.clicked.connect(self._start_connect)
        lo.addWidget(self._connect_btn)
        lo.addSpacing(16)

        # ── Status / message area ─────────────────────────────────────────────
        self._msg_label = QLabel("")
        self._msg_label.setWordWrap(True)
        self._msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_label.setStyleSheet("color: #8890B8; font-size: 12px; border: none;")
        lo.addWidget(self._msg_label)

        # ── Warning action row (hidden until needed) ──────────────────────────
        self._warn_row = QWidget()
        self._warn_row.setStyleSheet("background: transparent;")
        warn_lo = QHBoxLayout(self._warn_row)
        warn_lo.setContentsMargins(0, 8, 0, 0)
        warn_lo.setSpacing(10)

        self._proceed_btn = QPushButton("Proceed anyway")
        self._proceed_btn.setFixedHeight(38)
        self._proceed_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._proceed_btn.setStyleSheet(_BTN_VIOLET)
        self._proceed_btn.clicked.connect(self._proceed)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(38)
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setStyleSheet(_BTN_GHOST)
        self._cancel_btn.clicked.connect(self.reject)

        warn_lo.addWidget(self._proceed_btn, 1)
        warn_lo.addWidget(self._cancel_btn)
        self._warn_row.setVisible(False)
        lo.addWidget(self._warn_row)

        self.adjustSize()

    def _field_label(self, text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: 700;"
            f"letter-spacing: 2px; border: none;"
        )
        return lbl

    def _input_style(self) -> str:
        return """
            QLineEdit {
                background-color: #181830;
                color: #E8EAFF;
                border: 1px solid #282858;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #7C3AED;
                background-color: #1C1C38;
            }
        """

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _start_connect(self):
        cam_ip = self._cam_ip.text().strip()
        arm_ip = self._arm_ip.text().strip()

        if not cam_ip or not arm_ip:
            self._set_message("Please enter both IP addresses.", "#FF4466")
            return

        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Connecting…")
        self._warn_row.setVisible(False)
        self._set_message("Testing connections, please wait…", "#8890B8")

        self._worker = _ConnectionWorker(cam_ip, arm_ip)
        self._worker.finished.connect(self._on_result)
        self._worker.start()

    def _on_result(self, cam_ok: bool, arm_ok: bool):
        self._cam_ok = cam_ok
        self._arm_ok = arm_ok

        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Connect")

        if cam_ok and arm_ok:
            self._set_message("Both devices connected successfully.", "#00E676")
            QTimer.singleShot(600, self._proceed)

        elif not cam_ok and not arm_ok:
            self._set_message(
                "Neither device is reachable.\n"
                "Check IPs and network connectivity, then retry.",
                "#FF4466"
            )
            self._warn_row.setVisible(False)

        else:
            missing = "Camera" if not cam_ok else "xArm 5"
            ok      = "xArm 5" if not cam_ok else "Camera"
            self._set_message(
                f"{missing} is not reachable.\n"
                f"Only {ok} could be reached — you may proceed in limited mode.",
                "#FFB300"
            )
            self._warn_row.setVisible(True)
            self.adjustSize()

    def _proceed(self):
        cam_ip = self._cam_ip.text().strip()
        arm_ip = self._arm_ip.text().strip()

        from VisionForge.app.core.camera_client  import CameraClient
        from VisionForge.app.core.arm_controller import ArmController

        camera_client  = CameraClient(cam_ip)  if self._cam_ok else None
        arm_controller = ArmController(arm_ip) if self._arm_ok else None

        if camera_client:
            camera_client.start()
        if arm_controller:
            arm_controller.start()

        self.connection_established.emit(camera_client, arm_controller, cam_ip, arm_ip)
        self.accept()

    def _set_message(self, text: str, color: str):
        self._msg_label.setText(text)
        self._msg_label.setStyleSheet(
            f"color: {color}; font-size: 12px; border: none;"
        )
        self.adjustSize()

    def _center(self):
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - self.width())  // 2,
            (screen.height() - self.height()) // 2,
        )