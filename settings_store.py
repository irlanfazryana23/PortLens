"""
Remembered view settings for PortLens.

Stored as JSON in %APPDATA%\\PortLens\\settings.json (settings saved by the app's
earlier name, in %APPDATA%\\PrinterPortDetector, are still read). Loading never
raises: a missing, unreadable or corrupt file falls back to defaults, and
unknown values are replaced one key at a time. Saving returns False on
failure instead of raising, so the UI is never interrupted.
"""

import json
import os

from view_logic import CONNECTION_FILTERS, SORT_COLUMNS, STATUS_FILTERS

APP_DIR_NAME = "PortLens"
LEGACY_APP_DIR_NAME = "PrinterPortDetector"  # folder used before the rename
FILE_NAME = "settings.json"

DEFAULTS = {
    "sort_column": None,
    "sort_direction": "asc",
    "status_filter": "all",
    "connection_filter": "all",
}


def default_path():
    """Return the settings file path, or None when %APPDATA% is unavailable."""
    base = os.environ.get("APPDATA")
    if not base:
        return None
    return os.path.join(base, APP_DIR_NAME, FILE_NAME)


def legacy_path():
    """Settings path from before the rename, or None when %APPDATA% is unavailable."""
    base = os.environ.get("APPDATA")
    if not base:
        return None
    return os.path.join(base, LEGACY_APP_DIR_NAME, FILE_NAME)


def sanitize(data):
    """Return a complete settings dict, replacing any invalid value by its default."""
    result = dict(DEFAULTS)
    if not isinstance(data, dict):
        return result
    column = data.get("sort_column")
    if column in SORT_COLUMNS:
        result["sort_column"] = column
    if data.get("sort_direction") in ("asc", "desc"):
        result["sort_direction"] = data["sort_direction"]
    if data.get("status_filter") in STATUS_FILTERS:
        result["status_filter"] = data["status_filter"]
    if data.get("connection_filter") in CONNECTION_FILTERS:
        result["connection_filter"] = data["connection_filter"]
    if result["sort_column"] is None:
        result["sort_direction"] = "asc"
    return result


def load_settings(path=None):
    explicit = path is not None
    path = path or default_path()
    if not path:
        return dict(DEFAULTS)
    if not explicit and not os.path.exists(path):
        # First launch after the rename: keep the user's old sort and filters.
        old = legacy_path()
        if old and os.path.exists(old):
            path = old
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return sanitize(json.load(fh))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(data, path=None):
    """Write settings atomically. Returns True on success, False otherwise."""
    path = path or default_path()
    if not path:
        return False
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(sanitize(data), fh, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
