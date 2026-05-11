import cv2
from PySide6.QtGui import QImage
from VisionForge.app.plugin_sdk import TaskProcessor


class RotateProcessor(TaskProcessor):
    def process_frame(self, frame_rgb, meta):
        rotated = cv2.rotate(frame_rgb, cv2.ROTATE_90_CLOCKWISE)
        h, w = rotated.shape[:2]
        qimg = QImage(rotated.data, w, h, 3 * w,
                      QImage.Format.Format_RGB888).copy()
        self.display_ready.emit(qimg)
