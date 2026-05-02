"""
CameraPanel — the "Camera" page of VisionForge.

Layout (QSplitter):
  Left  (~65%)  FeedWidget
  Right (~35%)  Toggle: [Configuration] [Media]
                  → CameraConfigPanel  or  MediaPanel
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QPushButton, QStackedWidget
)
from PySide6.QtCore import Qt

from VisionForge.app.widgets.feed_widget    import FeedWidget
from VisionForge.app.widgets.camera_config  import CameraConfigPanel
from VisionForge.app.widgets.media_panel    import MediaPanel
from VisionForge.app.core.media_manager     import MediaManager


class CameraPanel(QWidget):

    def __init__(self, camera_client=None, parent=None):
        super().__init__(parent)
        self._client  = camera_client
        self._manager = MediaManager(self)
        self._setup_ui()
        if camera_client:
            self._wire(camera_client)

    def _setup_ui(self):
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #1A1A38; }")

        # ── Left: live feed ───────────────────────────────────────────
        self._feed = FeedWidget()

        # ── Right: toggled panel ──────────────────────────────────────
        right = QWidget()
        right.setStyleSheet("background-color: #0C0C1E; border-left: 1px solid #1A1A38;")
        right_lo = QVBoxLayout(right)
        right_lo.setContentsMargins(0, 0, 0, 0)
        right_lo.setSpacing(0)

        # Toggle buttons
        tog = QWidget()
        tog.setStyleSheet("background-color: #080814; border-bottom: 1px solid #1A1A38;")
        tog.setFixedHeight(38)
        tog_lo = QHBoxLayout(tog)
        tog_lo.setContentsMargins(0, 0, 0, 0)
        tog_lo.setSpacing(0)

        self._btn_config = QPushButton("Configuration")
        self._btn_media  = QPushButton("Media")
        for btn in (self._btn_config, self._btn_media):
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_config.setStyleSheet(self._tab_style(True))
        self._btn_media.setStyleSheet(self._tab_style(False))
        self._btn_config.clicked.connect(lambda: self._switch(0))
        self._btn_media.clicked.connect(lambda: self._switch(1))
        tog_lo.addWidget(self._btn_config)
        tog_lo.addWidget(self._btn_media)

        # Stacked widget
        self._stack  = QStackedWidget()
        self._config = CameraConfigPanel(camera_client=self._client)
        self._media  = MediaPanel(self._manager)
        self._stack.addWidget(self._config)   # index 0
        self._stack.addWidget(self._media)    # index 1

        right_lo.addWidget(tog)
        right_lo.addWidget(self._stack, 1)

        splitter.addWidget(self._feed)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 65)
        splitter.setStretchFactor(1, 35)
        self._splitter = splitter

        self._feed.resolution_changed.connect(self._fit_splitter_to_camera)

        lo.addWidget(splitter)

    def _fit_splitter_to_camera(self, cam_w: int, cam_h: int):
        """Resize the splitter so the feed widget is exactly the camera's aspect ratio.
        This eliminates both dark bars and any cropping."""
        feed_h = self._feed.height()
        if feed_h < 1:
            return
        ideal_feed_w = int(feed_h * cam_w / cam_h)
        total_w = self._splitter.width()
        right_w = max(280, total_w - ideal_feed_w)
        self._splitter.setSizes([total_w - right_w, right_w])

    def _switch(self, idx: int):
        self._stack.setCurrentIndex(idx)
        self._btn_config.setStyleSheet(self._tab_style(idx == 0))
        self._btn_media.setStyleSheet(self._tab_style(idx == 1))

    def _wire(self, camera_client):
        # raw_frame_received for the feed is managed by showEvent/hideEvent.
        # Media always needs frames (for recording); feed only when visible.
        camera_client.raw_frame_received.connect(self._media.on_frame)
        camera_client.connection_changed.connect(self._feed.set_camera_connected)
        camera_client.fps_updated.connect(self._feed.set_fps)
        self._config.set_client(camera_client)

    def showEvent(self, event):
        super().showEvent(event)
        if self._client:
            self._client.raw_frame_received.connect(self._feed.on_frame)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._client:
            try:
                self._client.raw_frame_received.disconnect(self._feed.on_frame)
            except RuntimeError:
                pass

    def attach_camera(self, camera_client):
        self._client = camera_client
        self._wire(camera_client)
        if self.isVisible():
            camera_client.raw_frame_received.connect(self._feed.on_frame)

    @staticmethod
    def _tab_style(active: bool) -> str:
        if active:
            return (
                "QPushButton { background:#111128; color:#00CFFF;"
                " border:none; border-bottom: 2px solid #00CFFF;"
                " font-size:12px; font-weight:700; }"
            )
        return (
            "QPushButton { background:#080814; color:#454878;"
            " border:none; border-bottom: 1px solid #1A1A38;"
            " font-size:12px; }"
            "QPushButton:hover { color:#8890B8; background:#0E0E22; }"
        )