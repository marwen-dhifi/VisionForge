"""
ServiceAwareWrapper — wraps an existing task panel in a QTabWidget,
adding an "Inspection" tab as the last tab.

Applied by MainWindow when a service.py is discovered alongside a task.
Proxies attach_camera(), attach_arm(), cleanup(), set_arm() to the inner panel
so all existing MainWindow wiring continues to work unchanged.
"""

from PySide6.QtWidgets import QTabWidget, QWidget, QVBoxLayout


_TAB_STYLE = """
    QTabWidget::pane { border: none; }
    QTabBar::tab {
        background: #0C0C1E;
        color: #8890B8;
        border: 1px solid #1A1A38;
        border-bottom: none;
        padding: 6px 16px;
        font-size: 11px;
        font-weight: 600;
    }
    QTabBar::tab:selected {
        background: #111128;
        color: #00CFFF;
    }
    QTabBar::tab:hover:!selected {
        background: #0E0E22;
        color: #E8EAFF;
    }
"""


class ServiceAwareWrapper(QWidget):
    """
    Container with a QTabWidget:
      Tab 0  — original task panel
      Tab 1  — InspectionTab ("Inspection")

    All proxy methods forward to the inner panel so MainWindow never needs
    to know whether a panel is wrapped or not.
    """

    def __init__(self, task_panel: QWidget, inspection_tab: QWidget,
                 task_label: str = 'Task', parent=None):
        super().__init__(parent)
        self._panel          = task_panel
        self._inspection_tab = inspection_tab

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(_TAB_STYLE)
        self._tabs.addTab(task_panel,     task_label)
        self._tabs.addTab(inspection_tab, 'Inspection')
        lo.addWidget(self._tabs)

    # ── Proxy methods used by MainWindow ──────────────────────────────────────

    def attach_camera(self, cam) -> None:
        if hasattr(self._panel, 'attach_camera'):
            self._panel.attach_camera(cam)

    def attach_arm(self, arm) -> None:
        if hasattr(self._panel, 'attach_arm'):
            self._panel.attach_arm(arm)

    def set_arm(self, arm) -> None:
        if hasattr(self._panel, 'set_arm'):
            self._panel.set_arm(arm)

    def cleanup(self) -> None:
        if hasattr(self._panel, 'cleanup'):
            self._panel.cleanup()

    # ── Property proxies used by MainWindow._attach_camera ───────────────────

    @property
    def _cam(self):
        return getattr(self._panel, '_cam', None)

    @_cam.setter
    def _cam(self, value):
        self._panel._cam = value

    @property
    def _processor(self):
        return getattr(self._panel, '_processor', None)

    # ── Forward panel-specific attributes accessed by MainWindow ─────────────

    def __getattr__(self, name: str):
        # Only called when normal lookup fails.
        # Guard against recursion during __init__ before _panel is set.
        if '_panel' not in self.__dict__:
            raise AttributeError(name)
        return getattr(self._panel, name)
