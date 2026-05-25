"""
SevenSegInspectionService — MTP inspection service for the 7-segment OCR task.

Publishes via OPC UA:
  Parameters  : confidence_threshold (ana, 0.0–1.0)
  Report vals : detections (str)

detections format: "N|name1:text1:conf1|name2:text2:conf2|..."
  - N    : number of named (green) displays published
  - name : user-assigned measurement name
  - text : OCR reading (empty string if below confidence threshold)
  - conf : confidence rounded to 2 decimal places
  - only tracker IDs with an assigned name are included
  - example: "2|Tank1:1234:0.95|Pump2:5678:0.88"

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
            tag_description='Minimum OCR confidence to publish text (0.0 - 1.0)',
            v_min=0.0, v_max=1.0, v_scl_min=0.0, v_scl_max=1.0,
        )
        self.add_report_value(
            'str', 'detections',
            tag_description=(
                'Named displays encoded as '
                '"N|name1:text1:conf1|name2:text2:conf2|...". '
                'Only assigned (green) displays are included.'
            ),
        )
        self._threshold = 0.5
        self._name_map: dict = {}   # shared reference to panel.tid_to_measurement

    def set_name_map(self, name_map: dict) -> None:
        """Share the panel's tid_to_measurement dict. Call once from MainWindow after service creation."""
        self._name_map = name_map

    def on_starting(self):
        self._threshold = float(self.get_param('confidence_threshold') or 0.5)

    def on_result(self, result) -> None:
        if result is None:
            return
        if not hasattr(result, 'tracker_ids'):
            return

        ocr = getattr(result, 'ocr_results', {})
        parts = []

        for tid in sorted(int(t) for t in result.tracker_ids):
            name = self._name_map.get(tid)
            if not name:
                continue
            text, conf = ocr.get(tid, ('', 0.0))
            published_text = text if conf >= self._threshold else ''
            parts.append(f'{name}:{published_text}:{conf:.2f}')

        self.set_report('detections', f'{len(parts)}|' + '|'.join(parts))
