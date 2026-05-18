"""
PluginLoader — discovers and loads plugins from the plugins/ directory.
"""
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from VisionForge.app.plugin_sdk.manifest import PluginManifest, load_manifest


@dataclass
class PluginDescriptor:
    manifest:     PluginManifest
    PanelClass:   type
    ServiceClass: "type | None" = None


class PluginLoader:
    """
    Scans a directory for plugin subfolders. For each valid plugin:
      1. Reads plugin.json
      2. Imports the entry module via importlib
      3. Resolves and validates the panel class (must subclass TaskPanel)
      4. Stores a PluginDescriptor in self.plugins

    Failures NEVER raise — broken plugins are skipped and logged to stderr.
    Platform startup is never affected by a bad plugin.
    """

    def __init__(self, plugins_root: str = None):
        if plugins_root is None:
            # loader.py is at VisionForge/app/plugin_sdk/loader.py
            # parents[2] → VisionForge/ → VisionForge/plugins
            plugins_root = str(Path(__file__).resolve().parents[2] / "plugins")
        self._root    = os.path.abspath(plugins_root)
        self.plugins: list[PluginDescriptor] = []
        self._scanned = False

    def scan(self) -> None:
        """Idempotent discovery pass. Safe to call multiple times."""
        if self._scanned:
            return
        self._scanned = True

        if not os.path.isdir(self._root):
            print(f"[PluginLoader] plugins directory not found: {self._root}", flush=True)
            return

        for entry in sorted(os.listdir(self._root)):
            sub = os.path.join(self._root, entry)
            if not os.path.isdir(sub):
                continue
            if entry.startswith(".") or entry.startswith("_"):
                continue
            if not os.path.isfile(os.path.join(sub, "plugin.json")):
                continue
            self._load_one(sub)

    def _load_one(self, plugin_dir: str) -> None:
        try:
            manifest = load_manifest(plugin_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[PluginLoader] Skipping {plugin_dir}: {exc}", file=sys.stderr, flush=True)
            return

        # Add plugin folder to sys.path so bare local imports work
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        # Flush any bare-named modules cached by a previous plugin (e.g. 'processor',
        # 'panel') so this plugin's local files are imported fresh.
        for _name in list(sys.modules.keys()):
            _mod = sys.modules[_name]
            _file = getattr(_mod, "__file__", None) or ""
            if _file and plugin_dir not in _file and os.path.dirname(_file) != plugin_dir:
                # only evict short unqualified names that look like local plugin modules
                if "." not in _name and not _name.startswith("_vf_plugin_"):
                    if os.path.isfile(os.path.join(plugin_dir, _name + ".py")):
                        sys.modules.pop(_name, None)

        entry_path = os.path.join(plugin_dir, manifest.panel_module + ".py")
        if not os.path.isfile(entry_path):
            print(
                f"[PluginLoader] Skipping '{manifest.name}': "
                f"panel module not found: {entry_path}",
                file=sys.stderr, flush=True,
            )
            return

        module_key = f"_vf_plugin_{manifest.name}_{manifest.panel_module}"
        try:
            spec   = importlib.util.spec_from_file_location(module_key, entry_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_key] = module
            spec.loader.exec_module(module)
        except Exception as exc:
            import traceback
            print(
                f"[PluginLoader] Skipping '{manifest.name}': import failed:\n"
                f"{traceback.format_exc()}",
                file=sys.stderr, flush=True,
            )
            return

        PanelClass = getattr(module, manifest.panel_class, None)
        if PanelClass is None:
            print(
                f"[PluginLoader] Skipping '{manifest.name}': "
                f"class '{manifest.panel_class}' not found in {entry_path}",
                file=sys.stderr, flush=True,
            )
            return

        from VisionForge.app.plugin_sdk.base import TaskPanel
        if not (isinstance(PanelClass, type) and issubclass(PanelClass, TaskPanel)):
            print(
                f"[PluginLoader] Skipping '{manifest.name}': "
                f"'{manifest.panel_class}' must subclass TaskPanel",
                file=sys.stderr, flush=True,
            )
            return

        descriptor = PluginDescriptor(manifest=manifest, PanelClass=PanelClass)

        # ── Optional: load service.py ─────────────────────────────────────────
        if manifest.service_module and manifest.service_class:
            svc_entry = os.path.join(plugin_dir, manifest.service_module + ".py")
            if os.path.isfile(svc_entry):
                svc_key = f"_vf_plugin_{manifest.name}_{manifest.service_module}"
                try:
                    svc_spec   = importlib.util.spec_from_file_location(svc_key, svc_entry)
                    svc_module = importlib.util.module_from_spec(svc_spec)
                    sys.modules[svc_key] = svc_module
                    svc_spec.loader.exec_module(svc_module)
                    ServiceClass = getattr(svc_module, manifest.service_class, None)
                    if ServiceClass is not None:
                        from VisionForge.app.inspection.inspection_service import InspectionService
                        if isinstance(ServiceClass, type) and issubclass(ServiceClass, InspectionService):
                            descriptor.ServiceClass = ServiceClass
                        else:
                            print(
                                f"[PluginLoader] '{manifest.name}': service class "
                                f"'{manifest.service_class}' must subclass InspectionService",
                                file=sys.stderr, flush=True,
                            )
                except Exception:
                    import traceback
                    print(
                        f"[PluginLoader] '{manifest.name}': service load failed:\n"
                        f"{traceback.format_exc()}",
                        file=sys.stderr, flush=True,
                    )

        self.plugins.append(descriptor)
        print(f"[PluginLoader] Loaded '{manifest.name}' v{manifest.version}", flush=True)


# ── Module-level singleton ────────────────────────────────────────────────────

_LOADER: "PluginLoader | None" = None


def get_plugin_loader() -> PluginLoader:
    """Return the process-wide PluginLoader singleton."""
    global _LOADER
    if _LOADER is None:
        _LOADER = PluginLoader()
    return _LOADER
