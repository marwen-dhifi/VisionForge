"""
SevenSegInspectionService — MTP inspection service for the 7-segment OCR task.

Publishes via OPC UA:
  Parameters  : confidence_threshold (ana, 0.0–1.0)
  Report vals : ocr_value (str), ocr_confidence (ana), detection_count (dint)

on_result() receives FramePacket objects from SevenSegProcessor.
"""

from VisionForge.app.inspection.inspection_service import InspectionService


class SevenSegInspectionService(InspectionService):

    def __init__(self):
        super().__init__(
            tag_name='seven_segment_inspection',
            tag_description='Seven-segment OCR inspection via YOLO-OBB + PARSeq',
        )
        self.add_parameter(
            'ana', 'confidence_threshold',
            tag_description='Minimum OCR confidence to publish (0.0 - 1.0)',
            v_min=0.0, v_max=1.0, v_scl_min=0.0, v_scl_max=1.0,
        )
        self.add_report_value(
            'str', 'ocr_value',
            tag_description='Last OCR reading',
        )
        self.add_report_value(
            'ana', 'ocr_confidence',
            tag_description='OCR confidence 0–1',
            v_scl_min=0.0, v_scl_max=1.0,
        )
        self.add_report_value(
            'dint', 'detection_count',
            tag_description='Number of tracked displays in frame',
            v_scl_min=0, v_scl_max=100,
        )
        self._threshold = 0.5

    def on_starting(self):
        self._threshold = float(self.get_param('confidence_threshold') or 0.5)

    def on_result(self, result) -> None:
        if result is None:
            return

        # result is a FramePacket emitted by SevenSegProcessor
        n = len(result.tracker_ids) if hasattr(result, 'tracker_ids') else 0
        self.set_report('detection_count', n)

        best_text, best_conf = '', 0.0
        if hasattr(result, 'ocr_results'):
            for _tid, (text, conf) in result.ocr_results.items():
                if conf >= self._threshold and conf > best_conf:
                    best_text, best_conf = text, conf

        if best_text:
            self.set_report('ocr_value',      best_text)
            self.set_report('ocr_confidence', best_conf)
