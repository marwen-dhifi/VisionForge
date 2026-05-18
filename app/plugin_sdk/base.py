"""
TaskPanel and TaskProcessor — abstract base classes for VisionForge plugins.
"""
import queue
import sys
import traceback

import numpy as np
from PySide6.QtCore    import QThread, Signal
from PySide6.QtGui     import QImage
from PySide6.QtWidgets import QWidget


# ── Background CV worker ──────────────────────────────────────────────────────

class TaskProcessor(QThread):
    """
    Base class for background CV workers.

    The default run() loop maintains a bounded 1-frame queue so the processor
    always works on the most recent frame and never falls behind the camera.

    Signals:
        display_ready(QImage)  — rendered frame for the panel's feed widget
        result_ready(object)   — per-frame result (any Python object)

    Subclasses MUST override:
        process_frame(frame_rgb, meta) — do CV work, emit display_ready / result_ready

    Subclasses MAY override:
        run() — only if the default loop is unsuitable
    """

    display_ready = Signal(QImage)
    result_ready  = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue:   queue.Queue = queue.Queue(maxsize=1)
        self._running: bool        = False

    # ── Public (UI-thread safe) ───────────────────────────────────────────────

    def submit_frame(self, frame: np.ndarray, meta: dict = None):
        """
        Drop any previously queued frame, enqueue the latest one.
        Non-blocking. Safe to call from any thread.
        """
        try:    self._queue.get_nowait()
        except  queue.Empty: pass
        try:    self._queue.put_nowait((frame, meta or {}))
        except  queue.Full:  pass

    def stop(self, timeout_ms: int = 3000):
        """Signal the run loop to exit and wait for the thread to finish."""
        self._running = False
        self.wait(timeout_ms)

    # ── Override in subclass ──────────────────────────────────────────────────

    def process_frame(self, frame_rgb: np.ndarray, meta: dict) -> None:
        """
        Perform CV work on <frame_rgb> (HxWx3 uint8 RGB numpy array).
        Emit display_ready(QImage) and/or result_ready(object) as needed.
        Runs in this QThread — never touch Qt widgets here.
        """
        raise NotImplementedError

    # ── Default run loop ──────────────────────────────────────────────────────

    def run(self):
        self._running = True
        while self._running:
            try:
                frame, meta = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.process_frame(frame, meta)
            except Exception:
                traceback.print_exc(file=sys.stderr)


# ── Plugin panel ──────────────────────────────────────────────────────────────

class TaskPanel(QWidget):
    """
    Base class for all plugin panels.

    self._cam  → CameraClient | None   (the real ZMQ camera client)
    self._arm  → ArmController | None  (the real xArm SDK wrapper)

    Both are the REAL hardware objects used by VisionForge — plugins connect
    to their signals and call their methods directly.

    Guards: self._cam and self._arm may be None if hardware was not connected
    at startup. Always check before connecting signals:
        if self._cam:
            self._cam.raw_frame_received.connect(...)

    In dev_runner both are guaranteed non-None (--camera and --arm are required).

    Lifecycle (called by platform / dev_runner):
        __init__(camera_client, arm_controller, parent)
        on_attach()       ← REQUIRED: build UI, create processor, wire signals
        showEvent(event)  ← default: connect raw_frame_received → submit_frame, start processor
        hideEvent(event)  ← default: disconnect raw_frame_received → submit_frame
        cleanup()         ← REQUIRED: stop processor, release resources

    Subclasses MUST implement:
        on_attach(self)
        cleanup(self)     ← call super().cleanup() first

    Subclasses MAY override:
        showEvent / hideEvent
    """

    def __init__(
        self,
        camera_client  = None,
        arm_controller = None,
        parent         = None,
    ):
        super().__init__(parent)
        self._cam:       object = camera_client
        self._arm:       object = arm_controller
        self._processor: "TaskProcessor | None" = None

    # ── Mandatory hooks ───────────────────────────────────────────────────────

    def on_attach(self) -> None:
        """Build UI, create self._processor, connect processor signals. Called once."""
        raise NotImplementedError

    # ── Reconnection hooks (called by MainWindow) ─────────────────────────────

    def attach_camera(self, cam) -> None:
        """Called by MainWindow when the camera reconnects."""
        self._cam = cam

    def attach_arm(self, arm) -> None:
        """Called by MainWindow when the arm reconnects."""
        self._arm = arm

    # ── Default lifecycle ─────────────────────────────────────────────────────

    def showEvent(self, event):
        """Connect camera → processor and start processor when panel becomes visible."""
        super().showEvent(event)
        if self._cam is not None and self._processor is not None:
            try:
                self._cam.raw_frame_received.connect(self._processor.submit_frame)
            except (RuntimeError, TypeError):
                pass
        if self._processor is not None and not self._processor.isRunning():
            self._processor.start()

    def hideEvent(self, event):
        """Disconnect camera → processor when panel is hidden."""
        super().hideEvent(event)
        if self._cam is not None and self._processor is not None:
            try:
                self._cam.raw_frame_received.disconnect(self._processor.submit_frame)
            except (RuntimeError, TypeError):
                pass

    def _start_processor_persistent(self) -> None:
        """
        Connect camera → processor and start it once from on_attach().
        The processor runs until cleanup() regardless of panel visibility —
        required for MTP services that may be in EXECUTE when the panel is hidden.
        Safe to call multiple times; guards against double-connect with a flag.
        """
        if not hasattr(self, '_persistent_connected'):
            self._persistent_connected = False
        if self._cam is not None and self._processor is not None:
            if not self._persistent_connected:
                try:
                    self._cam.raw_frame_received.connect(self._processor.submit_frame)
                    self._persistent_connected = True
                except (RuntimeError, TypeError):
                    pass
        if self._processor is not None and not self._processor.isRunning():
            self._processor.start()

    def cleanup(self) -> None:
        """Stop processor and disconnect signals. Subclasses call super().cleanup() first."""
        if self._cam is not None and self._processor is not None:
            try:
                self._cam.raw_frame_received.disconnect(self._processor.submit_frame)
            except (RuntimeError, TypeError):
                pass
        if self._processor is not None:
            self._processor.stop()
