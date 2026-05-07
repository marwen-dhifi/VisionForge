"""
VisionForge Plugin Dev Runner.

Run a plugin standalone against real hardware for development and testing.

Usage:
    python -m VisionForge.app.plugin_sdk.dev_runner <plugin_dir> --camera IP --arm IP

Both --camera and --arm are REQUIRED. Plugins always run against real hardware.

Example:
    python -m VisionForge.app.plugin_sdk.dev_runner plugins/example_difference \\
        --camera 192.168.1.100 --arm 192.168.1.200
"""
import argparse
import importlib.util
import os
import sys


def _ensure_visionforge_on_path():
    """Add repo root to sys.path so VisionForge.app.* imports resolve."""
    # This file is at VisionForge/app/plugin_sdk/dev_runner.py
    # Three parents up → repo root (the directory containing VisionForge/)
    this_file = os.path.abspath(__file__)
    sdk_dir   = os.path.dirname(this_file)          # app/plugin_sdk
    app_dir   = os.path.dirname(sdk_dir)             # app
    vf_dir    = os.path.dirname(app_dir)             # VisionForge
    repo_root = os.path.dirname(vf_dir)              # repo root
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def main():
    _ensure_visionforge_on_path()

    parser = argparse.ArgumentParser(
        prog="python -m VisionForge.app.plugin_sdk.dev_runner",
        description="Run a VisionForge plugin standalone against real hardware.",
    )
    parser.add_argument(
        "plugin_dir",
        help="Path to the plugin folder (must contain plugin.json)",
    )
    parser.add_argument(
        "--camera",
        required=True,
        metavar="IP",
        help="IP address of the camera ZMQ server (port 5555/5556)",
    )
    parser.add_argument(
        "--arm",
        required=True,
        metavar="IP",
        help="IP address of the xArm controller",
    )
    args = parser.parse_args()

    # ── Validate plugin directory ─────────────────────────────────────────────
    plugin_dir = os.path.abspath(args.plugin_dir)
    if not os.path.isdir(plugin_dir):
        print(f"ERROR: plugin directory not found: {plugin_dir}", file=sys.stderr)
        sys.exit(1)

    # ── Load manifest ─────────────────────────────────────────────────────────
    from VisionForge.app.plugin_sdk.manifest import load_manifest
    try:
        manifest = load_manifest(plugin_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Qt application ────────────────────────────────────────────────────────
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtCore    import Qt

    app = QApplication.instance() or QApplication(sys.argv)

    try:
        from VisionForge.app.styles.theme import STYLESHEET
        app.setStyleSheet(STYLESHEET)
    except Exception:
        pass

    # ── Real hardware ─────────────────────────────────────────────────────────
    from VisionForge.app.core.camera_client  import CameraClient
    from VisionForge.app.core.arm_controller import ArmController

    camera = CameraClient(args.camera)
    arm    = ArmController(args.arm)
    camera.start()
    arm.start()

    # ── Load plugin panel class ───────────────────────────────────────────────
    entry_path = os.path.join(plugin_dir, manifest.panel_module + ".py")
    if not os.path.isfile(entry_path):
        print(f"ERROR: panel module not found: {entry_path}", file=sys.stderr)
        camera.cleanup()
        arm.cleanup()
        sys.exit(1)

    module_key = f"_vf_devrun_{manifest.name}_{manifest.panel_module}"
    try:
        spec   = importlib.util.spec_from_file_location(module_key, entry_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        print(f"ERROR: failed to import {entry_path}: {exc}", file=sys.stderr)
        camera.cleanup()
        arm.cleanup()
        sys.exit(1)

    PanelClass = getattr(module, manifest.panel_class, None)
    if PanelClass is None:
        print(f"ERROR: class '{manifest.panel_class}' not found in {entry_path}", file=sys.stderr)
        camera.cleanup()
        arm.cleanup()
        sys.exit(1)

    # ── Instantiate panel ─────────────────────────────────────────────────────
    try:
        panel = PanelClass(camera_client=camera, arm_controller=arm)
        panel.on_attach()
    except Exception as exc:
        import traceback
        print(f"ERROR: failed to instantiate panel: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        camera.cleanup()
        arm.cleanup()
        sys.exit(1)

    # ── Main window ───────────────────────────────────────────────────────────
    class _DevWindow(QMainWindow):
        def closeEvent(self, event):
            try: panel.cleanup()
            except Exception: pass
            try: camera.cleanup()
            except Exception: pass
            try: arm.cleanup()
            except Exception: pass
            event.accept()

    win = _DevWindow()
    win.setWindowTitle(f"[dev] {manifest.label}  —  VisionForge Plugin Runner")
    win.setCentralWidget(panel)
    win.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
