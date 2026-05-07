"""
Build script: produces visionforge-sdk-<version>.zip

Usage:
    python tools/build_sdk_zip.py [--version X.Y.Z]

Output:
    dist/visionforge-sdk-<version>.zip
"""
import argparse
import os
import sys
import zipfile

# Repo root is one level up from this file (tools/)
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _add(zf: zipfile.ZipFile, src: str, dest: str):
    """Add a single file to the zip at <dest>."""
    zf.write(src, dest)


def _add_dir(zf: zipfile.ZipFile, src_dir: str, dest_prefix: str):
    """Recursively add a directory to the zip under <dest_prefix>."""
    for dirpath, _dirs, files in os.walk(src_dir):
        for fname in files:
            full = os.path.join(dirpath, fname)
            rel  = os.path.relpath(full, src_dir)
            zf.write(full, os.path.join(dest_prefix, rel))


def _empty_init(zf: zipfile.ZipFile, dest: str):
    """Write an empty __init__.py at <dest>."""
    zf.writestr(dest, "")


def build(version: str):
    dist_dir = os.path.join(REPO, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    zip_name   = f"visionforge-sdk-{version}.zip"
    zip_path   = os.path.join(dist_dir, zip_name)
    top        = f"visionforge-sdk-{version}"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:

        # ── Package __init__.py files ────────────────────────────────────────
        _empty_init(zf, f"{top}/VisionForge/__init__.py")
        _empty_init(zf, f"{top}/VisionForge/app/__init__.py")
        _empty_init(zf, f"{top}/VisionForge/app/core/__init__.py")
        _empty_init(zf, f"{top}/VisionForge/app/styles/__init__.py")

        # ── Real hardware clients ────────────────────────────────────────────
        for fname in ("camera_client.py", "arm_controller.py"):
            src = os.path.join(REPO, "app", "core", fname)
            _add(zf, src, f"{top}/VisionForge/app/core/{fname}")

        # ── Theme stylesheet ─────────────────────────────────────────────────
        theme_src = os.path.join(REPO, "app", "styles", "theme.py")
        if os.path.isfile(theme_src):
            _add(zf, theme_src, f"{top}/VisionForge/app/styles/theme.py")

        # ── Plugin SDK (verbatim from repo) ───────────────────────────────────
        sdk_dir = os.path.join(REPO, "app", "plugin_sdk")
        for fname in (
            "__init__.py", "base.py", "manifest.py",
            "loader.py", "utils.py", "dev_runner.py",
        ):
            src = os.path.join(sdk_dir, fname)
            _add(zf, src, f"{top}/VisionForge/app/plugin_sdk/{fname}")

        # ── Example plugin ────────────────────────────────────────────────────
        example_src = os.path.join(REPO, "plugins", "example_difference")
        _add_dir(zf, example_src, f"{top}/plugins/example_difference")

        # ── requirements-sdk.txt ──────────────────────────────────────────────
        req_src = os.path.join(REPO, "requirements-sdk.txt")
        _add(zf, req_src, f"{top}/requirements-sdk.txt")

        # ── Convenience runner scripts ────────────────────────────────────────
        zf.writestr(
            f"{top}/run.bat",
            "@echo off\r\npython -m VisionForge.app.plugin_sdk.dev_runner %*\r\n",
        )
        zf.writestr(
            f"{top}/run.sh",
            "#!/bin/sh\npython3 -m VisionForge.app.plugin_sdk.dev_runner \"$@\"\n",
        )

    print(f"Built: {zip_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build VisionForge SDK zip.")
    parser.add_argument("--version", default=None, help="Override version string")
    args = parser.parse_args()

    version = args.version
    if version is None:
        # Read from SDK __init__
        sys.path.insert(0, REPO)
        from app.plugin_sdk import __version__ as _v
        version = _v

    build(version)
