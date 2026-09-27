"""
VisionForge v1.0
Entry point — bootstraps the application, shows the splash screen,
then hands off to the connection dialog and main window.
"""

import os
import sys

# ── Make `import VisionForge.…` resolve when run as a plain script ──────────
# Almost every module in this project imports itself absolutely, as
# `from VisionForge.app.… import …`, which needs the PARENT of this folder on
# sys.path. An IDE that treats the parent as a content root provides that, so
# running from PyCharm works; `python main.py` in a terminal does not, and
# fails at the first such import inside splash.py. This is the same bootstrap
# app/plugin_sdk/dev_runner.py already performs for the same reason.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("VisionForge")
    app.setApplicationVersion("1.0")
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)

    # Apply global stylesheet
    from app.styles.theme import STYLESHEET
    app.setStyleSheet(STYLESHEET)

    # ── Offline mode ────────────────────────────────────────────────────────
    # `python main.py --offline` skips the connection dialog and opens the main
    # window with no camera and no arm. This uses an EXISTING code path rather
    # than a new one: ConnectionDialog._proceed already passes None for a device
    # that is unreachable, and TaskPanel already guards against self._cam and
    # self._arm being None. Intended for working on the interface, or capturing
    # it, without the equipment present.
    # ⚠ There is no live feed in this mode, so the task panels show their
    # controls but no frames and no detections.
    if "--offline" in sys.argv:
        from app.main_window import MainWindow
        app._window = MainWindow(None, None, cam_ip="", arm_ip="", opc_port=48050)
        app._window.showMaximized()
        sys.exit(app.exec())

    # ── Splash ──────────────────────────────────────────────────────────────
    # References are stored on `app` so Python doesn't garbage-collect them
    # the moment the enclosing function returns.
    from app.splash import SplashScreen
    app._splash = SplashScreen()

    def _on_splash_done():
        from app.connection_dialog import ConnectionDialog
        app._dlg = ConnectionDialog()

        def _on_connected(camera_client, arm_controller, cam_ip, arm_ip, opc_port):
            from app.main_window import MainWindow
            app._window = MainWindow(camera_client, arm_controller,
                                     cam_ip=cam_ip, arm_ip=arm_ip, opc_port=opc_port)
            app._window.showMaximized()

        app._dlg.connection_established.connect(_on_connected)
        app._dlg.show()

    app._splash.finished.connect(_on_splash_done)
    app._splash.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()