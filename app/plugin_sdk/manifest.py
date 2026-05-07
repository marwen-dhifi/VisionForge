"""
PluginManifest — reads and validates plugin.json.
"""
import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PluginManifest:
    name:         str
    label:        str
    icon:         str
    version:      str
    panel_module: str
    panel_class:  str
    description:  str = ""
    plugin_dir:   str = field(default="", compare=False)

    @staticmethod
    def required_keys():
        return ("name", "label", "icon", "version", "panel_module", "panel_class")


def load_manifest(plugin_dir: str) -> PluginManifest:
    """
    Read <plugin_dir>/plugin.json, validate required keys, return PluginManifest.

    Raises:
        FileNotFoundError  — plugin.json is absent
        ValueError         — required key missing or JSON invalid
    """
    path = os.path.join(plugin_dir, "plugin.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"plugin.json not found in: {plugin_dir}")

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    missing = [k for k in PluginManifest.required_keys() if k not in data]
    if missing:
        raise ValueError(f"{path}: missing required keys: {', '.join(missing)}")

    return PluginManifest(
        name         = data["name"],
        label        = data["label"],
        icon         = data["icon"],
        version      = data["version"],
        panel_module = data["panel_module"],
        panel_class  = data["panel_class"],
        description  = data.get("description", ""),
        plugin_dir   = os.path.abspath(plugin_dir),
    )
