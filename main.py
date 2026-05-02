"""
VisionForge v1.0
Entry point — bootstraps the application, shows the splash screen,
then hands off to the connection dialog and main window.
"""

import sys
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

    # ── Splash ──────────────────────────────────────────────────────────────
    # References are stored on `app` so Python doesn't garbage-collect them
    # the moment the enclosing function returns.
    from app.splash import SplashScreen
    app._splash = SplashScreen()

    def _on_splash_done():
        from app.connection_dialog import ConnectionDialog
        app._dlg = ConnectionDialog()

        def _on_connected(camera_client, arm_controller, cam_ip, arm_ip):
            from app.main_window import MainWindow
            app._window = MainWindow(camera_client, arm_controller,
                                     cam_ip=cam_ip, arm_ip=arm_ip)
            app._window.showMaximized()

        app._dlg.connection_established.connect(_on_connected)
        app._dlg.show()

    app._splash.finished.connect(_on_splash_done)
    app._splash.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()