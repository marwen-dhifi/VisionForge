"""
InspectionService — base class for per-task MTP services.

Task authors subclass this and override only 3 methods:
    on_result(result)    — called every result_ready; call set_report() here
    on_starting()        — optional setup before EXECUTE (read params here)
    on_completing()      — optional finalization before COMPLETED

Constructor: call add_parameter() and add_report_value() to declare the schema.
"""

import time

from PySide6.QtCore import QObject, Signal

from mtppy.service import Service
from mtppy.procedure import Procedure
from mtppy.operation_elements import AnaServParam, DIntServParam, BinServParam, StringServParam
from mtppy.indicator_elements import AnaView, DIntView, BinView, StringView


_PARAM_TYPES = {
    'ana':  AnaServParam,
    'dint': DIntServParam,
    'bin':  BinServParam,
    'str':  StringServParam,
}

_VIEW_TYPES = {
    'ana':  AnaView,
    'dint': DIntView,
    'bin':  BinView,
    'str':  StringView,
}


class InspectionService(Service, QObject):
    """
    Abstract base. Subclass this in service.py alongside any TaskProcessor.

    Thread model:
        - MTPPy state methods (idle, execute, …) run in plain daemon threads
          spawned by ThreadControl — never on the Qt main thread.
        - on_result() is called from the processor QThread.
        - Qt signals (state_changed, report_values_updated) use QueuedConnection
          automatically because InspectionTab lives in the main thread.
        - Service.__init__ and QObject.__init__ must both be called explicitly
          (MRO constraint — QObject is a C++ extension type).
    """

    state_changed         = Signal(str)   # new state name, e.g. "execute"
    report_values_updated = Signal()      # at least one report value changed

    def __init__(self, tag_name: str, tag_description: str = ''):
        Service.__init__(self, tag_name, tag_description)
        QObject.__init__(self)

        self._default_proc = Procedure(
            procedure_id=0,
            tag_name='default',
            is_self_completing=False,
            is_default=True,
        )
        self.add_procedure(self._default_proc)

    # ── Schema definition API (call in subclass __init__) ─────────────────────

    def add_parameter(self, kind: str, tag_name: str,
                      tag_description: str = '', **kwargs):
        """
        Add an input parameter locked at START.
        kind: 'ana' | 'dint' | 'bin' | 'str'
        kwargs: v_min, v_max, v_scl_min, v_scl_max, v_unit, v_state_0, v_state_1
        """
        cls = _PARAM_TYPES[kind]
        self._default_proc.add_procedure_parameter(
            cls(tag_name, tag_description, **kwargs)
        )

    def add_report_value(self, kind: str, tag_name: str,
                         tag_description: str = '', **kwargs):
        """
        Add a live output updated during EXECUTE.
        kind: 'ana' | 'dint' | 'bin' | 'str'
        """
        cls = _VIEW_TYPES[kind]
        self._default_proc.add_report_value(
            cls(tag_name, tag_description, **kwargs)
        )

    # ── Runtime helpers (call in on_result / on_starting) ─────────────────────

    def set_report(self, tag_name: str, value) -> None:
        """
        Update a report value and push to the OPC UA node.
        Thread-safe — may be called from the processor QThread inside on_result().
        """
        rv = self._default_proc.report_values.get(tag_name)
        if rv is not None:
            rv.set_v(value)
            self.report_values_updated.emit()

    def get_param(self, tag_name: str):
        """Read the VOut locked value of a procedure parameter."""
        param = self._default_proc.procedure_parameters.get(tag_name)
        if param is not None:
            return param.get_v_out()
        return None

    def get_report(self, tag_name: str):
        """Read the current V value of a report view."""
        rv = self._default_proc.report_values.get(tag_name)
        if rv is not None:
            return rv.attributes['V'].value
        return None

    # ── Override points (optional) ────────────────────────────────────────────

    def on_result(self, result) -> None:
        """
        Called every time the linked TaskProcessor emits result_ready.
        Update report values with set_report(). Do NOT block.
        Runs on the processor QThread.
        """

    def on_starting(self) -> None:
        """Optional setup before EXECUTE. Read locked parameters here."""

    def on_completing(self) -> None:
        """Optional finalization before COMPLETED."""

    # ── Concrete MTPPy state implementations (16 states) ─────────────────────

    def idle(self):
        self.state_changed.emit('idle')
        while self.is_state('idle'):
            time.sleep(0.1)

    def starting(self):
        self.state_changed.emit('starting')
        try:
            self.on_starting()
        except Exception as exc:
            print(f'[InspectionService:{self.tag_name}] on_starting error: {exc}', flush=True)
        self.state_change()

    def execute(self):
        self.state_changed.emit('execute')
        while self.is_state('execute'):
            time.sleep(0.05)

    def completing(self):
        self.state_changed.emit('completing')
        try:
            self.on_completing()
        except Exception as exc:
            print(f'[InspectionService:{self.tag_name}] on_completing error: {exc}', flush=True)
        self.state_change()

    def completed(self):
        self.state_changed.emit('completed')
        while self.is_state('completed'):
            time.sleep(0.1)

    def pausing(self):
        self.state_changed.emit('pausing')
        self.state_change()

    def paused(self):
        self.state_changed.emit('paused')
        while self.is_state('paused'):
            time.sleep(0.1)

    def resuming(self):
        self.state_changed.emit('resuming')
        self.state_change()

    def holding(self):
        self.state_changed.emit('holding')
        self.state_change()

    def held(self):
        self.state_changed.emit('held')
        while self.is_state('held'):
            time.sleep(0.1)

    def unholding(self):
        self.state_changed.emit('unholding')
        self.state_change()

    def stopping(self):
        self.state_changed.emit('stopping')
        self.state_change()

    def stopped(self):
        self.state_changed.emit('stopped')
        while self.is_state('stopped'):
            time.sleep(0.1)

    def aborting(self):
        self.state_changed.emit('aborting')
        self.state_change()

    def aborted(self):
        self.state_changed.emit('aborted')
        while self.is_state('aborted'):
            time.sleep(0.1)

    def resetting(self):
        self.state_changed.emit('resetting')
        self.state_change()
