"""
Pure view logic for PortLens.

No Tk, win32 or PIL imports here, so everything in this module can be unit
tested without a display. A "row" is one dict from the scan results with the
keys name, port, physical_port, connection, driver, status_text, is_online,
is_default, type, shared, vid_pid, physical_raw and usb_path.
"""

import re

EMPTY = "\u2014"  # shown for fields that do not apply

# --- Status ----------------------------------------------------------------

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
STATUS_VIRTUAL = "virtual"

STATUS_FILTERS = ("all", STATUS_ONLINE, STATUS_OFFLINE, STATUS_VIRTUAL)

_STATUS_SYMBOL = {STATUS_ONLINE: "\u25cf", STATUS_OFFLINE: "\u25cf", STATUS_VIRTUAL: "\u2013"}
_STATUS_LABEL = {STATUS_ONLINE: "Online", STATUS_OFFLINE: "Offline", STATUS_VIRTUAL: "Virtual"}
# Problems first when sorting ascending.
_STATUS_ORDER = {STATUS_OFFLINE: 0, STATUS_ONLINE: 1, STATUS_VIRTUAL: 2}


def classify_status(row):
    """Return online / offline / virtual from the row's is_online value."""
    is_online = row.get("is_online")
    if is_online is True:
        return STATUS_ONLINE
    if is_online is False:
        return STATUS_OFFLINE
    return STATUS_VIRTUAL


def status_symbol(kind):
    return _STATUS_SYMBOL.get(kind, "")


def status_badge(kind):
    """Text badge for a status kind, e.g. '● Online'."""
    return f"{_STATUS_SYMBOL[kind]} {_STATUS_LABEL[kind]}"


# --- Connection ------------------------------------------------------------

CONNECTION_FILTERS = ("all", "USB", "Network", "Other")


def plain_text(value):
    """Strip leading emoji/symbols the UI puts in front of connection names."""
    return re.sub(r"^[^A-Za-z0-9]+", "", str(value or "")).strip()


def connection_category(row):
    """Return USB, Network or Other for a row."""
    text = plain_text(row.get("connection", "")).upper()
    if text.startswith("USB"):
        return "USB"
    if text.startswith("NETWORK") or text.startswith("WSD"):
        return "Network"
    return "Other"


# --- Sorting ---------------------------------------------------------------

SORT_COLUMNS = ("status", "default", "printer", "physical_port",
                "win_port", "connection", "device_status", "driver")


def natural_key(value):
    """Sort key so 'USB Port 2' comes before 'USB Port 10' (case-insensitive)."""
    parts = re.split(r"(\d+)", str(value or "").casefold())
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p != "")


def _sort_key(column, row):
    if column == "status":
        return (_STATUS_ORDER[classify_status(row)], natural_key(row.get("name")))
    if column == "default":
        return (0 if row.get("is_default") else 1, natural_key(row.get("name")))
    if column == "printer":
        return natural_key(row.get("name"))
    if column == "physical_port":
        return natural_key(row.get("physical_port"))
    if column == "win_port":
        return natural_key(row.get("port"))
    if column == "connection":
        return natural_key(plain_text(row.get("connection")))
    if column == "device_status":
        return natural_key(row.get("status_text"))
    if column == "driver":
        return natural_key(row.get("driver"))
    return ()


def sort_rows(rows, column, direction):
    """
    Return a new list sorted by column. direction is 'asc' or 'desc'.
    Any other direction (or an unknown column) returns scan order.
    The sort is stable, so ties keep scan order in both directions.
    """
    if column not in SORT_COLUMNS or direction not in ("asc", "desc"):
        return list(rows)
    return sorted(rows, key=lambda r: _sort_key(column, r), reverse=(direction == "desc"))


def next_sort_state(current_column, current_direction, clicked_column):
    """Cycle asc -> desc -> scan order for repeated clicks on one column."""
    if clicked_column != current_column or current_direction not in ("asc", "desc"):
        return clicked_column, "asc"
    if current_direction == "asc":
        return clicked_column, "desc"
    return None, "asc"


# --- Filtering -------------------------------------------------------------

def _haystack(row):
    fields = (
        row.get("name"), row.get("physical_port"), row.get("port"),
        plain_text(row.get("connection")), row.get("status_text"), row.get("driver"),
    )
    return " ".join(str(f) for f in fields if f).casefold()


def filter_rows(rows, query="", status="all", connection="all"):
    """
    Keep rows matching the search text and both chip selections.
    The query is plain text; every whitespace-separated word must match
    somewhere in the row (AND). No regex is applied.
    """
    terms = str(query or "").casefold().split()
    result = []
    for row in rows:
        if status != "all" and classify_status(row) != status:
            continue
        if connection != "all" and connection_category(row) != connection:
            continue
        if terms:
            hay = _haystack(row)
            if not all(t in hay for t in terms):
                continue
        result.append(row)
    return result


def chip_counts(rows, query="", status="all", connection="all"):
    """
    Counts for each chip given the search and the *other* chip group.
    Returns {"status": {...}, "connection": {...}}.
    """
    status_counts = {}
    for s in STATUS_FILTERS:
        status_counts[s] = len(filter_rows(rows, query, s, connection))
    connection_counts = {}
    for c in CONNECTION_FILTERS:
        connection_counts[c] = len(filter_rows(rows, query, status, c))
    return {"status": status_counts, "connection": connection_counts}


# --- Details ---------------------------------------------------------------

def _or_empty(value):
    text = "" if value is None else str(value).strip()
    return text if text else EMPTY


def build_detail_fields(row, port_info=None, host=None):
    """
    Ordered (label, value) pairs for the details grid. The field set is fixed
    so the panel never changes height; fields that do not apply show '—'.
    """
    port_info = port_info or {}
    return [
        ("Status", _or_empty(row.get("status_text"))),
        ("Printer", _or_empty(row.get("name"))),
        ("Default", "Yes" if row.get("is_default") else "No"),
        ("Type", _or_empty(row.get("type"))),
        ("Shared", _or_empty(row.get("shared"))),
        ("Connection", _or_empty(plain_text(row.get("connection")))),
        ("Physical port", _or_empty(row.get("physical_port"))),
        ("Windows port", _or_empty(row.get("port"))),
        ("Driver", _or_empty(row.get("driver"))),
        ("USB device ID", _or_empty(row.get("vid_pid"))),
        ("Location", _or_empty(row.get("physical_raw"))),
        ("USB path", _or_empty(row.get("usb_path"))),
        ("Port description", _or_empty(port_info.get("description"))),
        ("Port monitor", _or_empty(port_info.get("monitor"))),
        ("Host address", _or_empty(host)),
    ]
