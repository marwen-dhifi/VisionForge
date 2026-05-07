"""
VisionForge Plugin SDK — public API.

Import from here in plugin code:
    from VisionForge.app.plugin_sdk import TaskPanel, TaskProcessor
    from VisionForge.app.plugin_sdk import save_frame, resolve_path
"""
from VisionForge.app.plugin_sdk.base     import TaskPanel, TaskProcessor
from VisionForge.app.plugin_sdk.manifest import PluginManifest, load_manifest
from VisionForge.app.plugin_sdk.loader   import PluginLoader, get_plugin_loader
from VisionForge.app.plugin_sdk.utils    import save_frame, resolve_path

__version__ = "1.0.0"

__all__ = [
    "TaskPanel", "TaskProcessor",
    "PluginManifest", "load_manifest",
    "PluginLoader", "get_plugin_loader",
    "save_frame", "resolve_path",
    "__version__",
]
