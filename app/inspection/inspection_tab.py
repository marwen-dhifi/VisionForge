"""
InspectionTab — the "Inspection" sub-tab widget added to task panels.

Contents:
  - POL warning banner (shown when external POL is controlling)
  - State indicator (colored label showing current MTP state)
  - Manual control buttons (START / STOP / RESET / ABORT)
  - Report values table (live-updated every result_ready frame)
"""

from PySide6.QtCore    import Qt, Slot
from PySide6.QtGui     import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


_STATE_COLORS = {
    'idle':       '#8890B8',
    'starting':   '#FFB300',
    'execute':    '#00E676',
    'completing': '#FFB300',
    'completed':  '#00CFFF',
    'pausing':    '#FFB300',
    'paused':     '#FFB300',
    'resuming':   '#FFB300',
    'holding':    '#FFB300',
    'held':       '#FF4466',
    'unholding':  '#FFB300',
    'stopping':   '#FF4466',
    'stopped':    '#FF4466',
    'aborting':   '#FF4466',
    'aborted':    '#FF4466',
    'resetting':  '#FFB300',
}

# MTPPy command codes
_CMD_START    = 4
_CMD_STOP     = 8
_CMD_RESET    = 2
_CMD_ABORT    = 256
_CMD_COMPLETE = 1024


class InspectionTab(QWidget):
    """
    Constructed by MainWindow for each panel with a registered InspectionService.

    Parameters:
        service — the InspectionService instance
    """

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self._build_ui()
        self._wire_signals()

    def _build_ui(self):
        self.setStyleSheet('background-color: #060612;')
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── POL warning banner ────────────────────────────────────────────────
        self._pol_banner = QLabel('  ⚠  Under POL Control — manual operation is disabled  ')
        self._pol_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pol_banner.setStyleSheet(
            'background: #2A1500; color: #FFB300;'
            ' border: 1px solid #FFB300; border-radius: 4px;'
            ' padding: 6px; font-weight: 700; font-size: 12px;'
        )
        self._pol_banner.setVisible(False)
        root.addWidget(self._pol_banner)

        # ── State indicator ───────────────────────────────────────────────────
        state_row = QHBoxLayout()
        state_lbl = QLabel('State:')
        state_lbl.setStyleSheet('color: #8890B8; font-size: 12px;')
        state_row.addWidget(state_lbl)

        self._state_display = QLabel('IDLE')
        self._state_display.setFont(QFont('Consolas', 14, QFont.Weight.Bold))
        self._state_display.setStyleSheet(f'color: {_STATE_COLORS["idle"]};')
        state_row.addWidget(self._state_display)
        state_row.addStretch()

        svc_lbl = QLabel(f'service: {self._service.tag_name}')
        svc_lbl.setStyleSheet('color: #454878; font-size: 10px;')
        state_row.addWidget(svc_lbl)
        root.addLayout(state_row)

        root.addWidget(self._separator())

        # ── Manual control buttons ────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._btn_start    = self._make_btn('START',    '#00E676', self._cmd_start)
        self._btn_complete = self._make_btn('COMPLETE', '#00CFFF', self._cmd_complete)
        self._btn_stop     = self._make_btn('STOP',     '#FF4466', self._cmd_stop)
        self._btn_reset    = self._make_btn('RESET',    '#FFB300', self._cmd_reset)
        self._btn_abort    = self._make_btn('ABORT',    '#FF4466', self._cmd_abort)
        for btn in (self._btn_start, self._btn_complete, self._btn_stop,
                    self._btn_reset, self._btn_abort):
            btn_row.addWidget(btn)
        root.addLayout(btn_row)

        root.addWidget(self._separator())

        # ── Parameters section ────────────────────────────────────────────────
        params = self._service._default_proc.procedure_parameters
        if params:
            root.addWidget(self._section_label('PROCEDURE PARAMETERS  (set before START)'))
            self._param_table = QTableWidget(len(params), 3)
            self._param_table.setHorizontalHeaderLabels(['Tag', 'VOut (locked)', 'VOp (write)'])
            self._param_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Stretch
            )
            self._param_table.setMaximumHeight(120)
            self._param_table.setStyleSheet(self._table_style())
            self._param_table.verticalHeader().setVisible(False)
            for row, (tag, param) in enumerate(params.items()):
                self._param_table.setItem(row, 0, QTableWidgetItem(tag))
                self._param_table.setItem(row, 1, QTableWidgetItem(
                    str(param.attributes['VOut'].value)
                ))
                self._param_table.setItem(row, 2, QTableWidgetItem(''))
            root.addWidget(self._param_table)

        # ── Report values section ─────────────────────────────────────────────
        root.addWidget(self._section_label('REPORT VALUES  (live during EXECUTE)'))
        rvs = self._service._default_proc.report_values
        self._report_table = QTableWidget(len(rvs), 2)
        self._report_table.setHorizontalHeaderLabels(['Tag', 'Value'])
        self._report_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._report_table.setMaximumHeight(200)
        self._report_table.setStyleSheet(self._table_style())
        self._report_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._report_table.verticalHeader().setVisible(False)
        for row, tag in enumerate(rvs):
            self._report_table.setItem(row, 0, QTableWidgetItem(tag))
            self._report_table.setItem(row, 1, QTableWidgetItem('—'))
        root.addWidget(self._report_table)

        root.addStretch()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_btn(self, text: str, color: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(34)
        btn.setStyleSheet(
            f'QPushButton {{ background: transparent; color: {color};'
            f' border: 1px solid {color}; border-radius: 5px;'
            f' font-size: 11px; font-weight: 700; padding: 0 14px; }}'
            f'QPushButton:hover {{ background: {color}22; }}'
            f'QPushButton:disabled {{ color: #454878; border-color: #1A1A38; }}'
        )
        btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            'color: #454878; font-size: 9px; letter-spacing: 1px; font-weight: 700;'
        )
        return lbl

    @staticmethod
    def _separator() -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color: #1A1A38;')
        return sep

    @staticmethod
    def _table_style() -> str:
        return (
            'QTableWidget { background: #0C0C1E; color: #E8EAFF;'
            ' border: 1px solid #1A1A38; gridline-color: #1A1A38; }'
            'QHeaderView::section { background: #111128; color: #8890B8;'
            ' border: none; padding: 4px; font-size: 10px; font-weight: 700; }'
        )

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _wire_signals(self):
        self._service.state_changed.connect(self._on_state_changed)
        self._service.report_values_updated.connect(self._refresh_report_table)

    # ── Slots ─────────────────────────────────────────────────────────────────

    @Slot(str)
    def _on_state_changed(self, state_str: str):
        color = _STATE_COLORS.get(state_str, '#8890B8')
        self._state_display.setText(state_str.upper())
        self._state_display.setStyleSheet(f'color: {color};')

    @Slot()
    def _refresh_report_table(self):
        rvs = self._service._default_proc.report_values
        for row, (tag, rv) in enumerate(rvs.items()):
            val = rv.attributes['V'].value
            item = self._report_table.item(row, 1)
            if item is None:
                self._report_table.setItem(row, 1, QTableWidgetItem(str(val)))
            else:
                item.setText(str(val))

    @Slot(bool)
    def set_pol_banner(self, visible: bool):
        self._pol_banner.setVisible(visible)

    # ── Manual control (operator mode) ───────────────────────────────────────

    def _send_op_command(self, code: int) -> None:
        try:
            osm = self._service.op_src_mode
            sm  = self._service.state_machine
            osm.attributes['StateOpOp'].set_value(True)
            sm.set_command_op(code)
        except Exception as exc:
            print(f'[InspectionTab] command {code} failed: {exc}', flush=True)

    def _cmd_start(self):    self._send_op_command(_CMD_START)
    def _cmd_complete(self): self._send_op_command(_CMD_COMPLETE)
    def _cmd_stop(self):     self._send_op_command(_CMD_STOP)
    def _cmd_reset(self):    self._send_op_command(_CMD_RESET)
    def _cmd_abort(self):    self._send_op_command(_CMD_ABORT)
