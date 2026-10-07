"""App identity and bundled-file lookup for PortLens."""

import os
import re
import sys

APP_NAME = "PortLens"

_ROOT = os.path.dirname(os.path.abspath(__file__))
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def resource_path(filename):
    """
    Path to a bundled file. Works from a PyInstaller bundle (files are at the
    bundle root) and from source (icons and logos live in assets/).
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return os.path.join(bundled, filename)
    for folder in ("assets", ""):
        candidate = os.path.join(_ROOT, folder, filename)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(_ROOT, filename)


def get_version():
    """Release version from the VERSION file, or 'dev' if it is missing or invalid."""
    try:
        with open(resource_path("VERSION"), "r", encoding="utf-8") as fh:
            value = fh.read().strip()
    except OSError:
        return "dev"
    return value if _VERSION_PATTERN.match(value) else "dev"
