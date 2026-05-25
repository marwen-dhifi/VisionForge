"""
InspectionModule — owns the single OPCUAServerPEA for the VisionForge PEA.

Responsibilities:
  - Accept service registrations with their panel stack index
  - Start the OPC UA server after all services are registered
  - Enforce one-active-service constraint
  - Emit Qt signals to MainWindow for auto-switch and POL banner
  - Stop the server on app close

Created once by MainWindow.
"""

import threading

from PySide6.QtCore import QObject, Qt, Signal


class InspectionModule(QObject):
    """
    Signals:
        auto_switch_requested(int)      — MainWindow should switch to this stack index
        pol_control_changed(bool)       — True = external POL is driving a service
        service_state_changed(str, str) — (tag_name, state_str) forwarded to InspectionTab
    """

    auto_switch_requested = Signal(int)
    pol_control_changed   = Signal(str, bool)  # (tag_name, is_pol_active)
    service_state_changed = Signal(str, str)

    def __init__(self, opc_port: int = 48050, parent=None):
        super().__init__(parent)
        self._port   = opc_port
        self._pea    = None

        self._services:            dict = {}   # {tag_name: InspectionService}
        self._service_stack_index: dict = {}   # {tag_name: int}
        self._active_service_tag:  "str | None" = None
        self._pol_control:         bool = False
        self._server_started:      bool = False

    # ── Registration ─────────────────────────────────────────────────────────

    def register_service(self, service, stack_index: int) -> None:
        """
        Register an InspectionService with its owning panel's stack index.
        Must be called before start_server().
        """
        self._services[service.tag_name] = service
        self._service_stack_index[service.tag_name] = stack_index

        service.state_changed.connect(
            lambda state, tag=service.tag_name: self._on_service_state_changed(tag, state),
            Qt.ConnectionType.QueuedConnection,
        )

    # ── Server lifecycle ──────────────────────────────────────────────────────

    def start_server(self) -> None:
        """
        Build OPC UA node tree and start server. Call AFTER all register_service().
        Runs the heavy node-building in a background thread to avoid blocking Qt.
        """
        if self._server_started or not self._services:
            return
        self._server_started = True
        threading.Thread(target=self._run_server, daemon=True, name='opc-ua-server').start()

    def _run_server(self) -> None:
        try:
            from mtppy.opcua_server_pea import OPCUAServerPEA
            endpoint = f'opc.tcp://0.0.0.0:{self._port}/'
            self._pea = OPCUAServerPEA(mtp_generator=None, endpoint=endpoint)
            for service in self._services.values():
                self._pea.add_service(service)
            self._pea.run_opcua_server()
            self._pea.set_services_in_idle()
            print(f'[InspectionModule] OPC UA server started at {endpoint}', flush=True)
        except Exception as exc:
            import traceback
            print(f'[InspectionModule] Server start failed:\n{traceback.format_exc()}', flush=True)

    def stop_server(self) -> None:
        """Called by MainWindow.closeEvent()."""
        if self._pea and self._server_started:
            try:
                self._pea.opcua_server.stop()
                print('[InspectionModule] OPC UA server stopped.', flush=True)
            except Exception:
                pass

    # ── Public queries ────────────────────────────────────────────────────────

    def get_active_service_tag(self) -> "str | None":
        return self._active_service_tag

    def is_pol_active(self) -> bool:
        return self._pol_control

    def get_service(self, tag_name: str):
        return self._services.get(tag_name)

    # ── Internal state dispatcher ─────────────────────────────────────────────

    def _on_service_state_changed(self, tag_name: str, state_str: str) -> None:
        """
        Called whenever any registered service emits state_changed.
        Executed on the Qt main thread via QueuedConnection.
        """
        self.service_state_changed.emit(tag_name, state_str)

        if state_str == 'execute':
            if self._active_service_tag and self._active_service_tag != tag_name:
                print(
                    f'[InspectionModule] WARNING: service "{tag_name}" entered execute '
                    f'while "{self._active_service_tag}" was already active.',
                    flush=True,
                )
            self._active_service_tag = tag_name

            idx = self._service_stack_index.get(tag_name)
            if idx is not None:
                self.auto_switch_requested.emit(idx)

        elif state_str in ('stopped', 'aborted', 'idle', 'completed'):
            if self._active_service_tag == tag_name:
                self._active_service_tag = None

        pol_driven = self._is_pol_driven(tag_name)
        if pol_driven != self._pol_control:
            self._pol_control = pol_driven
            self.pol_control_changed.emit(tag_name, pol_driven)

    def _is_pol_driven(self, tag_name: str) -> bool:
        """Return True if the service is being controlled by an external source (POL)."""
        svc = self._services.get(tag_name)
        if svc is None:
            return False
        try:
            return bool(svc.op_src_mode.attributes['SrcExtAct'].value)
        except Exception:
            return False
