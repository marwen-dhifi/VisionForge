from VisionForge.app.inspection.inspection_service import InspectionService


class DifferenceInspectionService(InspectionService):

    def __init__(self):
        super().__init__(
            tag_name='difference_inspection',
            tag_description='Frame-difference motion detection inspection',
        )
        self.add_parameter(
            'ana', 'motion_threshold',
            tag_description='Motion level above which an alert is raised (0.0 - 100.0)',
            v_scl_min=0.0, v_scl_max=100.0,
        )
        self.add_report_value(
            'ana', 'motion_level',
            tag_description='Current motion level as % of changed pixels (0.0 - 100.0)',
            v_scl_min=0.0, v_scl_max=100.0,
        )
        self.add_report_value(
            'bin', 'motion_alert',
            tag_description='True when motion_level exceeds motion_threshold',
        )
        self._threshold = 5.0

    def on_starting(self):
        self._threshold = float(self.get_param('motion_threshold') or 5.0)

    def on_result(self, result) -> None:
        if not isinstance(result, dict):
            return
        motion = float(result.get('motion', 0.0))
        self.set_report('motion_level', motion)
        self.set_report('motion_alert', motion > self._threshold)
