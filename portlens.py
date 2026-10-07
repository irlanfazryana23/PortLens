"""
PortLens
Detects all printers connected to the system, shows which physical port
each printer is plugged into, and checks online/offline status dynamically.

Performance: uses win32print API for instant printer/port enumeration (2ms),
only uses PowerShell for PnP/USB physical port detection (~1.5s).
"""

import base64
import datetime
import io
import json
import re
import subprocess
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import messagebox, ttk

from PIL import Image

from app_info import get_version, resource_path
import print_page
import settings_store
import view_logic as vl

try:
    import win32print
    HAS_WIN32PRINT = True
except ImportError:
    HAS_WIN32PRINT = False

try:
    import win32con
    import win32ui
    HAS_PRINT_GDI = True
except ImportError:
    HAS_PRINT_GDI = False

_CF = subprocess.CREATE_NO_WINDOW

# win32print attribute/status flags
_ATTR_WORK_OFFLINE = 0x00000400
_ATTR_SHARED = 0x00000008
_ATTR_NETWORK = 0x00000010
_ATTR_LOCAL = 0x00000040
_STATUS_OFFLINE = 0x00000080
_STATUS_ERROR = 0x00000002
_STATUS_PAUSED = 0x00000001
_STATUS_PAPER_JAM = 0x00000008
_STATUS_PAPER_OUT = 0x00000010
_STATUS_PRINTING = 0x00000400
_STATUS_BUSY = 0x00000200


# ---------------------------------------------------------------------------
# Data collection — native Python APIs + minimal PowerShell for USB location
# ---------------------------------------------------------------------------

def _run_ps(cmd, timeout=15):
    """Run a PowerShell command and return parsed JSON or None."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_CF,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception:
        pass
    return None


def _ensure_list(data):
    if data is None:
        return []
    return [data] if isinstance(data, dict) else data


def collect_all_printer_data():
    """
    Collect all printer data.

    Uses win32print for instant printer/port enumeration (~2ms),
    and a single PowerShell call for PnP/USB physical port detection (~1.5s).

    Returns (printers, port_details, pnp_printers, usb_ports).
    """
    results = {}

    # --- INSTANT: Native win32print API (2ms) ---
    printers = []
    port_details = {}
    default_printer = ""

    if HAS_WIN32PRINT:
        try:
            default_printer = win32print.GetDefaultPrinter()
        except Exception:
            pass

        # Enumerate printers with full details
        try:
            raw_printers = win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
                None, 2
            )
            for p in raw_printers:
                attrs = p.get("Attributes", 0)
                status = p.get("Status", 0)
                printers.append({
                    "name": p.get("pPrinterName", "Unknown"),
                    "port": p.get("pPortName", "Unknown"),
                    "driver": p.get("pDriverName", "Unknown"),
                    "work_offline": bool(attrs & _ATTR_WORK_OFFLINE),
                    "status_flags": status,
                    "shared": "Yes" if (attrs & _ATTR_SHARED) else "No",
                    "type": "Connection" if (attrs & _ATTR_NETWORK) and not (attrs & _ATTR_LOCAL) else "Local",
                    "is_default": p.get("pPrinterName", "").casefold() == default_printer.casefold(),
                    "attrs": attrs,
                })
        except Exception:
            pass

        # Enumerate ports
        try:
            raw_ports = win32print.EnumPorts(None, 2)
            for p in raw_ports:
                port_details[p.get("Name", "")] = {
                    "description": p.get("Description", ""),
                    "monitor": p.get("MonitorName", ""),
                    "host_address": "",  # not available from EnumPorts
                    "port_number": "",
                }
        except Exception:
            pass

    # Fallback to PowerShell if win32print not available
    if not printers:
        printers, port_details = _fallback_ps_printers()

    # --- Determine which printers need USB port detection ---
    has_usb_printers = any("USB" in p["port"].upper() and not p["work_offline"]
                          for p in printers)
    # Also check offline USB printers — they might still be plugged in
    has_any_usb = any("USB" in p["port"].upper() for p in printers)

    # --- PARALLEL: PnP + USB location (only if USB printers exist) ---
    def _fetch_pnp_and_usb():
        """Single PS call for PnP printers + USB physical port data."""
        if not has_any_usb:
            # No USB printers at all — only get PnP for completeness
            cmd = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @{}
$out.pnp = @(Get-PnpDevice -PresentOnly -Class Printer -EA SilentlyContinue | Select-Object InstanceId,Status,FriendlyName)
$out.usb = @()
$out | ConvertTo-Json -Depth 4 -Compress
"""
        else:
            cmd = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @{}
$out.pnp = @(Get-PnpDevice -PresentOnly -Class Printer -EA SilentlyContinue | Select-Object InstanceId,Status,FriendlyName)

# Find VID/PIDs of connected USB printers
$pds = $out.pnp | Where-Object { $_.InstanceId -like 'USBPRINT\*' }
$vps = @()
foreach ($pd in $pds) {
    $par = (Get-PnpDeviceProperty -InstanceId $pd.InstanceId -KeyName 'DEVPKEY_Device_Parent' -EA SilentlyContinue).Data
    if ($par) { $m = [regex]::Match($par, 'VID_[0-9A-F]{4}&PID_[0-9A-F]{4}'); if ($m.Success) { $vps += $m.Value } }
}
$vps = $vps | Select-Object -Unique

$usbDevs = @()
if ($vps.Count -gt 0) {
    Get-PnpDevice -PresentOnly -EA SilentlyContinue | Where-Object { $_.InstanceId -like 'USB\VID_*' } | ForEach-Object {
        foreach ($vp in $vps) {
            if ($_.InstanceId -like "*$vp*") {
                $pp = Get-PnpDeviceProperty -InstanceId $_.InstanceId -EA SilentlyContinue
                $usbDevs += [PSCustomObject]@{
                    FriendlyName=$_.FriendlyName; Class=$_.Class; InstanceId=$_.InstanceId; Status=$_.Status
                    LocationInfo=($pp|Where-Object KeyName -eq 'DEVPKEY_Device_LocationInfo').Data
                    LocationPaths=($pp|Where-Object KeyName -eq 'DEVPKEY_Device_LocationPaths').Data -join '|'
                }
                break
            }
        }
    }
}
$out.usb = $usbDevs
$out | ConvertTo-Json -Depth 4 -Compress
"""
        data = _run_ps(cmd, timeout=15)
        if data:
            results["pnp_usb"] = data

    # Also fetch printer port host addresses (not available from win32print)
    def _fetch_port_hosts():
        """Get network port host addresses from PrinterPort cmdlet."""
        # Only needed if there are network ports without host info
        has_network = any(_is_network_port(p["port"].upper(), port_details.get(p["port"]))
                         for p in printers)
        if not has_network:
            results["port_hosts"] = {}
            return

        cmd = (
            "Get-PrinterPort -ErrorAction SilentlyContinue "
            "| Where-Object { $_.PrinterHostAddress } "
            "| Select-Object Name, PrinterHostAddress, PortNumber "
            "| ConvertTo-Json -Depth 3 -Compress"
        )
        data = _run_ps(cmd, timeout=10)
        hosts = {}
        for p in _ensure_list(data):
            hosts[p.get("Name", "")] = {
                "host_address": p.get("PrinterHostAddress", ""),
                "port_number": p.get("PortNumber", ""),
            }
        results["port_hosts"] = hosts

    # Run PnP/USB and port host queries in parallel
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_fetch_pnp_and_usb), pool.submit(_fetch_port_hosts)]
        for f in as_completed(futures):
            pass

    # Parse PnP/USB results
    pnp_usb = results.get("pnp_usb", {})

    pnp_printers = []
    for d in _ensure_list(pnp_usb.get("pnp")):
        pnp_printers.append({
            "instance_id": (d.get("InstanceId") or "").upper(),
            "status": (d.get("Status") or "").upper(),
            "friendly_name": d.get("FriendlyName", ""),
        })

    usb_ports = {}
    for d in _ensure_list(pnp_usb.get("usb")):
        iid = (d.get("InstanceId") or "").upper()
        usb_ports[iid] = {
            "friendly_name": d.get("FriendlyName", ""),
            "class": d.get("Class", ""),
            "status": (d.get("Status") or "").upper(),
            "location_info": d.get("LocationInfo") or "",
            "location_paths": d.get("LocationPaths") or "",
        }

    # Merge port host addresses into port_details
    for port_name, host_info in results.get("port_hosts", {}).items():
        if port_name in port_details:
            port_details[port_name]["host_address"] = host_info.get("host_address", "")
            port_details[port_name]["port_number"] = host_info.get("port_number", "")
        else:
            port_details[port_name] = {
                "description": "", "monitor": "",
                "host_address": host_info.get("host_address", ""),
                "port_number": host_info.get("port_number", ""),
            }

    return printers, port_details, pnp_printers, usb_ports


def _fallback_ps_printers():
    """Fallback if win32print is not available."""
    printers = []
    port_details = {}
    cmd = r"""
$ErrorActionPreference = 'SilentlyContinue'
$out = @{}
$out.printers = @(Get-CimInstance Win32_Printer | Select-Object Name,PortName,DriverName,PrinterStatus,Shared,Local,Default)
$out.ports = @(Get-PrinterPort | Select-Object Name,Description,PortMonitor,PrinterHostAddress,PortNumber)
$out | ConvertTo-Json -Depth 4 -Compress
"""
    data = _run_ps(cmd, timeout=15)
    if data:
        for p in _ensure_list(data.get("printers")):
            printers.append({
                "name": p.get("Name", "Unknown"),
                "port": p.get("PortName", "Unknown"),
                "driver": p.get("DriverName", "Unknown"),
                "work_offline": False,
                "status_flags": 0,
                "shared": "Yes" if p.get("Shared") else "No",
                "type": "Local" if p.get("Local") else "Connection",
                "is_default": bool(p.get("Default")),
                "attrs": 0,
            })
        for p in _ensure_list(data.get("ports")):
            port_details[p.get("Name", "")] = {
                "description": p.get("Description", ""),
                "monitor": p.get("PortMonitor", ""),
                "host_address": p.get("PrinterHostAddress", ""),
                "port_number": p.get("PortNumber", ""),
            }
    return printers, port_details


# ---------------------------------------------------------------------------
# Physical port & status helpers
# ---------------------------------------------------------------------------

def _extract_vid_pid(instance_id):
    m = re.search(r'VID_([0-9A-F]{4})\&PID_([0-9A-F]{4})', instance_id.upper())
    return f"VID_{m.group(1)}&PID_{m.group(2)}" if m else None


def find_physical_port_for_printer(printer_name, printer_port, pnp_printers, usb_ports):
    """Find the actual physical USB port for a printer."""
    if "USB" not in printer_port.upper():
        return None

    vid_pid = None
    for usb_iid, usb_info in usb_ports.items():
        if _fuzzy_match(printer_name, usb_info["friendly_name"]):
            vid_pid = _extract_vid_pid(usb_iid)
            if vid_pid:
                break

    candidates = []
    if vid_pid:
        for usb_iid, usb_info in usb_ports.items():
            if vid_pid in usb_iid:
                candidates.append(usb_info)
    if not candidates:
        for usb_iid, usb_info in usb_ports.items():
            if _fuzzy_match(printer_name, usb_info["friendly_name"]):
                vid_pid = vid_pid or _extract_vid_pid(usb_iid)
                candidates.append(usb_info)

    if not candidates:
        return None

    physical_info = None
    for c in candidates:
        if c.get("location_info", "").startswith("Port_"):
            physical_info = c
            break
    if not physical_info:
        for c in candidates:
            if c.get("location_info", ""):
                physical_info = c
                break

    if not physical_info:
        return {"physical_port": "USB (port unknown)", "location_raw": "", "usb_path": "", "vid_pid": vid_pid or ""}

    loc_raw = physical_info["location_info"]
    loc_paths = physical_info.get("location_paths", "")
    port_label = _format_physical_port(loc_raw)

    usb_path = ""
    if loc_paths:
        for p in loc_paths.split("|"):
            if "PCIROOT" in p and "USBMI" not in p:
                usb_path = p
                break
        if not usb_path:
            usb_path = loc_paths.split("|")[0] if loc_paths else ""

    return {"physical_port": port_label, "location_raw": loc_raw, "usb_path": usb_path, "vid_pid": vid_pid or ""}


def _format_physical_port(location_info):
    if not location_info:
        return "USB (unknown)"
    port_match = re.search(r'Port_#(\d+)', location_info)
    hub_match = re.search(r'Hub_#(\d+)', location_info)
    if port_match:
        port_num = int(port_match.group(1))
        hub_num = int(hub_match.group(1)) if hub_match else None
        if hub_num and hub_num > 1:
            return f"USB Port {port_num} (Hub {hub_num})"
        return f"USB Port {port_num}"
    raw_match = re.match(r'[\d]+\.[\d]+\.[\d]+\.(\d+)', location_info)
    if raw_match:
        port_num = int(raw_match.group(1))
        if port_num > 0:
            return f"USB Port {port_num}"
    return f"USB ({location_info})"


def determine_device_status(printer, port_details, pnp_printers):
    """Determine real online/offline status using win32print flags. Returns (status_text, is_online)."""
    name = printer["name"]
    port_name = printer["port"]
    port_upper = port_name.upper()
    port_info = port_details.get(port_name, {})

    work_offline = printer.get("work_offline", False)
    status_flags = printer.get("status_flags", 0)

    if _is_virtual_printer(port_name, printer["driver"]):
        return ("N/A (Virtual)", None)

    if "USB" in port_upper:
        pnp_found = False
        for pnp in pnp_printers:
            if _fuzzy_match(name, pnp["friendly_name"]):
                pnp_found = True
                if pnp["status"] == "OK":
                    if work_offline:
                        return ("Offline (Set Offline in Windows)", False)
                    return ("Online", True)
                else:
                    return (f"Error ({pnp['status']})", False)
        if work_offline:
            return ("Offline (Disconnected)", False)
        if not pnp_found:
            return ("Offline (USB Unplugged)", False)
        return ("Online", True)

    if _is_network_port(port_upper, port_info):
        host = extract_host_from_port(port_name, port_info)
        if work_offline:
            reachable = ping_host(host) if host else None
            if reachable:
                return ("Offline (Set Offline, Host Reachable)", False)
            elif reachable is False:
                return ("Offline (Host Unreachable)", False)
            return ("Offline", False)
        if host:
            reachable = ping_host(host)
            return ("Online (Reachable)", True) if reachable else ("Offline (Unreachable)", False)
        return ("Online", True)

    if port_upper.startswith("LPT") or port_upper.startswith("COM"):
        return ("Offline", False) if work_offline else ("Online", True)

    return ("Offline", False) if work_offline else ("Online", True)


def detect_port_type(port_name, port_details=None):
    pu = port_name.upper()
    if "USB" in pu:
        return "🔌 USB"
    if pu.startswith("IP_") or "TCPMON" in (port_details or {}).get("monitor", "").upper():
        host = (port_details or {}).get("host_address", "")
        return f"🌐 Network ({host})" if host else "🌐 Network (TCP/IP)"
    if "WSD" in pu:
        return "🌐 WSD (Network)"
    if pu.startswith("LPT"):
        return "🖨️ Parallel (LPT)"
    if pu.startswith("COM"):
        return "📟 Serial (COM)"
    if pu == "FILE:" or "FILE" in pu:
        return "📄 File"
    if "NUL" in pu:
        return "⛔ Null"
    if "PORTPROMPT" in pu:
        return "📝 Prompt"
    if port_name.startswith("\\\\"):
        return "🌐 Network (SMB)"
    if port_name.lower().startswith("http://") or port_name.lower().startswith("https://"):
        return "🌐 Network (IPP/HTTP)"
    return "❓ Other"


def _is_virtual_printer(port_name, driver_name):
    pu, du = port_name.upper(), (driver_name or "").upper()
    for vp in ["NUL:", "FILE:", "PORTPROMPT:"]:
        if vp in pu:
            return True
    for kw in ["PDF", "XPS", "ONENOTE", "FAX", "SEND TO",
                "MICROSOFT PRINT", "SNAGIT", "CUTEPDF", "FOXIT", "BULLZIP"]:
        if kw in pu or kw in du:
            return True
    return False


def _is_network_port(port_upper, port_info=None):
    if port_upper.startswith("IP_") or "WSD" in port_upper:
        return True
    if port_upper.startswith("\\\\") or port_upper.startswith("HTTP://") or port_upper.startswith("HTTPS://"):
        return True
    if port_info:
        m = (port_info.get("monitor") or "").upper()
        d = (port_info.get("description") or "").upper()
        if "TCPMON" in m or "INTERNET" in m or "INTERNET" in d:
            return True
    return False


def _fuzzy_match(name1, name2):
    def words(s):
        return set(re.findall(r'[a-z0-9]+', s.lower())) - {'printer', 'series', 'the', 'a'}
    w1, w2 = words(name1), words(name2)
    return bool(w1 and w2 and len(w1 & w2) >= min(2, min(len(w1), len(w2))))


def extract_host_from_port(port_name, port_details=None):
    if port_details and port_details.get("host_address"):
        return port_details["host_address"]
    if port_name.upper().startswith("IP_"):
        return port_name[3:]
    m = re.search(r'https?://([^/:]+)', port_name, re.IGNORECASE)
    if m:
        return m.group(1)
    if port_name.startswith("\\\\"):
        parts = port_name.strip("\\").split("\\")
        return parts[0] if parts else None
    return None


def ping_host(host, timeout_ms=1500):
    if not host:
        return None
    try:
        r = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), host],
            capture_output=True, text=True, timeout=5, creationflags=_CF,
        )
        return r.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class PortLensApp:
    AUTO_REFRESH_MS = 15_000

    def __init__(self, root):
        self.root = root
        self.root.title("PortLens")
        self.root.geometry("1280x780")
        self.root.minsize(980, 660)

        self.auto_refresh_enabled = tk.BooleanVar(value=False)
        self._auto_refresh_id = None
        self._scan_thread = None
        self.port_details = {}
        self.printer_data = []
        self._prev_physical_ports = {}
        self.brand_logo = None

        # View state: filter/sort settings are remembered between launches.
        saved = settings_store.load_settings()
        self.sort_column = saved["sort_column"]
        self.sort_direction = saved["sort_direction"]
        self.search_var = tk.StringVar()
        self.status_filter = tk.StringVar(value=saved["status_filter"])
        self.connection_filter = tk.StringVar(value=saved["connection_filter"])
        self._visible_rows = []
        self._row_by_iid = {}
        self._changed_ports = set()
        self._scanned_once = False
        self._rendering = False
        self._flash_after_id = None
        self._flash_prev_text = None
        self._flash_text = None

        self.colors = {
            "bg": "#F5F7FC", "surface": "#FFFFFF", "surface2": "#F8FAFD",
            "accent": "#102AAF", "accent_hover": "#1734BB", "accent_soft": "#EEF2FF",
            "text": "#172443", "text_dim": "#63718A", "detail": "#455471",
            "success": "#16835A", "success_soft": "#EAF7F1",
            "warning": "#C56A00", "warning_soft": "#FFF5E7",
            "error": "#B33E36", "error_soft": "#FCEFED",
            "border": "#E0E6F0", "header_bg": "#FFFFFF",
        }

        self.root.configure(bg=self.colors["bg"])
        self._setup_styles()
        self._build_header()
        self._build_toolbar()
        self._build_filter_bar()
        # Bottom panels are packed before the table so the table is the
        # part that shrinks when the window is small.
        self._build_statusbar()
        self._build_detail_panel()
        self._build_table()

        self.search_var.trace_add("write", lambda *_: self._on_filter_changed(save=False))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._apply_view()
        self.root.after(100, self.refresh_printers)

    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Custom.Treeview",
                    background=self.colors["surface"], foreground=self.colors["text"],
                    fieldbackground=self.colors["surface"], borderwidth=0,
                    rowheight=34, font=("Segoe UI", 10))
        s.configure("Custom.Treeview.Heading",
                    background="#F0F3F9", foreground="#31405C",
                    bordercolor=self.colors["border"], borderwidth=1, relief="flat",
                    padding=(8, 10), font=("Segoe UI Semibold", 10))
        s.map("Custom.Treeview.Heading", background=[("active", "#E7EBF5")])
        s.map("Custom.Treeview",
              background=[("selected", self.colors["accent_soft"])],
              foreground=[("selected", self.colors["accent"])])
        s.configure("Light.Vertical.TScrollbar", background="#C7D0E0",
                    troughcolor="#F3F5F9", borderwidth=0, arrowsize=12)
        s.configure("Scan.Horizontal.TProgressbar", troughcolor="#EBEFF7",
                    background=self.colors["accent"], borderwidth=0, thickness=3)

        # Filter chips (ttk Toolbutton-style radio buttons: keyboard accessible)
        for name, fg in (("Chip", self.colors["text"]), ("ChipBad", self.colors["error"])):
            style = f"{name}.Toolbutton"
            s.configure(style, background=self.colors["surface"], foreground=fg,
                        bordercolor=self.colors["border"], lightcolor=self.colors["surface"],
                        darkcolor=self.colors["surface"], relief="solid", borderwidth=1,
                        padding=(10, 5), font=("Segoe UI", 9))
            s.map(style,
                  background=[("selected", self.colors["accent"]),
                              ("active", self.colors["accent_soft"])],
                  foreground=[("selected", "#FFFFFF")],
                  bordercolor=[("selected", self.colors["accent"]),
                               ("focus", self.colors["accent"])],
                  lightcolor=[("selected", self.colors["accent"])],
                  darkcolor=[("selected", self.colors["accent"])],
                  relief=[("selected", "solid"), ("pressed", "solid")])

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=self.colors["header_bg"],
                       highlightbackground=self.colors["border"], highlightthickness=1)
        hdr.pack(fill=tk.X)
        content = tk.Frame(hdr, bg=self.colors["header_bg"], padx=24, pady=15)
        content.pack(fill=tk.X)

        try:
            self.brand_logo = self._load_header_logo(size=40)
            tk.Label(content, image=self.brand_logo, bg=self.colors["header_bg"],
                     borderwidth=0).pack(side=tk.LEFT, padx=(0, 12))
        except (tk.TclError, OSError):
            pass

        title_block = tk.Frame(content, bg=self.colors["header_bg"])
        title_block.pack(side=tk.LEFT)
        tk.Label(title_block, text="PortLens",
                 font=("Segoe UI Semibold", 18), fg=self.colors["text"],
                 bg=self.colors["header_bg"]).pack(anchor=tk.W)
        tk.Label(title_block, text="Printer connections and physical port status",
                 font=("Segoe UI", 9), fg=self.colors["text_dim"],
                 bg=self.colors["header_bg"]).pack(anchor=tk.W, pady=(2, 0))

    @staticmethod
    def _load_header_logo(size):
        """Load the brand logo as a smooth size x size square (Tk only
        subsamples by whole numbers, which looks jagged). The logo file keeps
        its built-in padding, the same way Network Resetter shows its logo."""
        image = Image.open(resource_path("portlens_logo.png")).convert("RGBA")
        image = image.resize((size, size), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return tk.PhotoImage(data=base64.b64encode(buffer.getvalue()))

    def _secondary_button(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command, font=("Segoe UI Semibold", 9),
            bg=self.colors["surface"], fg="#243451",
            activebackground="#F1F4F9", activeforeground="#243451",
            relief="solid", borderwidth=1, highlightthickness=0,
            padx=14, pady=8, cursor="hand2")

    def _build_toolbar(self):
        section = tk.Frame(self.root, bg=self.colors["bg"], padx=24, pady=16)
        section.pack(fill=tk.X)
        tb = tk.Frame(section, bg=self.colors["bg"])
        tb.pack(fill=tk.X)

        self.refresh_btn = tk.Button(
            tb, text="Refresh printers", font=("Segoe UI Semibold", 9),
            bg=self.colors["accent"], fg="#FFFFFF",
            activebackground=self.colors["accent_hover"], activeforeground="#FFFFFF",
            relief="flat", borderwidth=0, padx=18, pady=9, cursor="hand2",
            command=self.refresh_printers)
        self.refresh_btn.pack(side=tk.LEFT)

        self._secondary_button(tb, "Copy report", self.copy_to_clipboard).pack(
            side=tk.LEFT, padx=(8, 0))
        self.test_page_btn = self._secondary_button(tb, "Print test page", self.print_test_page)
        self.test_page_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.default_btn = self._secondary_button(
            tb, "Set as default", self.set_selected_as_default)
        self.default_btn.config(state=tk.DISABLED)
        self.default_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.auto_btn = tk.Checkbutton(
            tb, text="Auto-refresh every 15 seconds", font=("Segoe UI", 9),
            variable=self.auto_refresh_enabled, command=self._toggle_auto_refresh,
            bg=self.colors["bg"], fg=self.colors["text_dim"],
            activebackground=self.colors["bg"], activeforeground=self.colors["text"],
            selectcolor=self.colors["surface"], cursor="hand2")
        self.auto_btn.pack(side=tk.LEFT, padx=(16, 0))

        metrics = tk.Frame(tb, bg=self.colors["bg"])
        metrics.pack(side=tk.RIGHT)
        self.count_label = tk.Label(metrics, text="Waiting for scan", font=("Segoe UI", 9),
                                    fg=self.colors["text_dim"], bg=self.colors["bg"])
        self.count_label.pack(side=tk.LEFT, padx=(0, 10))
        self.scan_time_label = tk.Label(metrics, text="", font=("Segoe UI", 9),
                                        fg=self.colors["text_dim"], bg=self.colors["bg"])
        self.scan_time_label.pack(side=tk.LEFT)

    STATUS_CHIP_LABELS = {"all": "All", "online": "Online",
                          "offline": "Offline", "virtual": "Virtual"}
    CONNECTION_CHIP_LABELS = {"all": "Any type", "USB": "USB",
                              "Network": "Network", "Other": "Other"}

    def _build_filter_bar(self):
        bar = tk.Frame(self.root, bg=self.colors["bg"], padx=24)
        bar.pack(fill=tk.X, pady=(0, 12))

        # Search box with placeholder and clear button
        box = tk.Frame(bar, bg=self.colors["surface"],
                       highlightbackground=self.colors["border"],
                       highlightcolor=self.colors["accent"], highlightthickness=1)
        box.pack(side=tk.LEFT)
        self.search_entry = tk.Entry(
            box, textvariable=self.search_var, width=27, font=("Segoe UI", 10),
            relief="flat", borderwidth=0, bg=self.colors["surface"],
            fg=self.colors["text"], insertbackground=self.colors["text"])
        self.search_entry.pack(side=tk.LEFT, padx=(10, 4), pady=7)
        self.search_clear = tk.Label(
            box, text="\u2715", font=("Segoe UI", 9), fg=self.colors["text_dim"],
            bg=self.colors["surface"], cursor="hand2", padx=6)
        self.search_clear.bind("<Button-1>", lambda e: self._clear_search())
        self.search_placeholder = tk.Label(
            box, text="Search printers, ports, drivers", font=("Segoe UI", 10),
            fg=self.colors["text_dim"], bg=self.colors["surface"], cursor="xterm")
        self.search_placeholder.bind("<Button-1>", lambda e: self.search_entry.focus_set())
        self.search_entry.bind("<Escape>", lambda e: self._clear_search())
        self._sync_search_decorations()

        # Chip groups
        self.status_chips = {}
        self.connection_chips = {}
        self._build_chip_group(bar, self.STATUS_CHIP_LABELS, self.status_filter,
                               self.status_chips).pack(side=tk.LEFT, padx=(16, 0))
        tk.Frame(bar, bg=self.colors["border"], width=1).pack(
            side=tk.LEFT, fill=tk.Y, padx=12, pady=4)
        self._build_chip_group(bar, self.CONNECTION_CHIP_LABELS, self.connection_filter,
                               self.connection_chips).pack(side=tk.LEFT)

    def _build_chip_group(self, parent, labels, variable, registry):
        group = tk.Frame(parent, bg=self.colors["bg"])
        for value, label in labels.items():
            chip = ttk.Radiobutton(
                group, text=label, value=value, variable=variable,
                style="Chip.Toolbutton", takefocus=True,
                command=lambda: self._on_filter_changed(save=True))
            chip.pack(side=tk.LEFT, padx=(0, 4))
            registry[value] = chip
        return group

    def _sync_search_decorations(self):
        """Show the placeholder when empty and the clear button when not."""
        if self.search_var.get():
            self.search_placeholder.place_forget()
            if not self.search_clear.winfo_ismapped():
                self.search_clear.pack(side=tk.RIGHT, before=self.search_entry)
        else:
            self.search_clear.pack_forget()
            self.search_placeholder.place(in_=self.search_entry, x=0, rely=0.5, anchor="w")
            self.search_placeholder.lift()

    def _clear_search(self):
        self.search_var.set("")
        self.search_entry.focus_set()

    def _clear_filters(self):
        self.search_var.set("")
        self.status_filter.set("all")
        self.connection_filter.set("all")
        self._on_filter_changed(save=True)

    def _on_filter_changed(self, save=False):
        self._sync_search_decorations()
        self._apply_view()
        if save:
            self._save_settings()

    def _save_settings(self):
        settings_store.save_settings({
            "sort_column": self.sort_column,
            "sort_direction": self.sort_direction,
            "status_filter": self.status_filter.get(),
            "connection_filter": self.connection_filter.get(),
        })

    def _on_close(self):
        self._save_settings()
        self.root.destroy()

    def _build_table(self):
        section = tk.Frame(self.root, bg=self.colors["bg"], padx=24)
        section.pack(fill=tk.BOTH, expand=True)
        title_row = tk.Frame(section, bg=self.colors["bg"])
        title_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(title_row, text="Detected printers", font=("Segoe UI Semibold", 13),
                 fg=self.colors["text"], bg=self.colors["bg"]).pack(side=tk.LEFT)
        self.showing_label = tk.Label(title_row, text="", font=("Segoe UI", 9),
                                      fg=self.colors["text_dim"], bg=self.colors["bg"])
        self.showing_label.pack(side=tk.RIGHT)
        frame = tk.Frame(section, bg=self.colors["border"], padx=1, pady=1)
        frame.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(frame, bg=self.colors["surface"])
        inner.pack(fill=tk.BOTH, expand=True)

        cols = vl.SORT_COLUMNS
        self.tree = ttk.Treeview(inner, columns=cols, show="headings",
                                  style="Custom.Treeview", selectmode="browse")

        self._heading_text = {
            "status": "Status", "default": "Default", "printer": "Printer Name",
            "physical_port": "Physical Port", "win_port": "Windows Port",
            "connection": "Connection Type", "device_status": "Device Status",
            "driver": "Driver",
        }
        for col in cols:
            self.tree.heading(
                col, text=self._heading_text[col],
                anchor=tk.CENTER if col == "default" else tk.W,
                command=lambda c=col: self._on_heading_click(c))

        self.tree.column("status", width=96, minwidth=90, stretch=False, anchor=tk.W)
        self.tree.column("default", width=72, minwidth=72, stretch=False, anchor=tk.CENTER)
        self.tree.column("printer", width=190, minwidth=130)
        self.tree.column("physical_port", width=160, minwidth=100)
        self.tree.column("win_port", width=130, minwidth=80)
        self.tree.column("connection", width=170, minwidth=100)
        self.tree.column("device_status", width=230, minwidth=140)
        self.tree.column("driver", width=200, minwidth=100)

        sb = ttk.Scrollbar(inner, orient=tk.VERTICAL, command=self.tree.yview,
                           style="Light.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Configure>", self._fit_columns)

        # Empty-state overlay, placed over the table when there is nothing to show
        self.empty_frame = tk.Frame(inner, bg=self.colors["surface"])
        self.empty_title = tk.Label(self.empty_frame, text="", font=("Segoe UI Semibold", 12),
                                    fg=self.colors["text"], bg=self.colors["surface"])
        self.empty_title.pack()
        self.empty_message = tk.Label(self.empty_frame, text="", font=("Segoe UI", 9),
                                      fg=self.colors["text_dim"], bg=self.colors["surface"])
        self.empty_message.pack(pady=(4, 0))
        self.empty_clear_btn = self._secondary_button(
            self.empty_frame, "Clear filters", self._clear_filters)

        # Right-click context menu
        self.context_menu = tk.Menu(self.root, tearoff=0,
                                     bg=self.colors["surface"], fg=self.colors["text"],
                                     activebackground=self.colors["accent_soft"],
                                     activeforeground=self.colors["accent"],
                                     activeborderwidth=0, borderwidth=1,
                                     font=("Segoe UI", 10))
        self.context_menu.add_command(label="★  Set as Default", command=self.set_selected_as_default)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🖨  Print Test Page", command=self.print_test_page)
        self.context_menu.add_command(label="⚙  Printer Properties", command=self._open_printer_properties)
        self.context_menu.add_command(label="📂  Open Printer Queue", command=self._open_printer_queue)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📋  Copy to Clipboard", command=self.copy_to_clipboard)
        self.tree.bind("<Button-3>", self._show_context_menu)

        self.tree.tag_configure("online_even", background="#FFFFFF", foreground=self.colors["text"])
        self.tree.tag_configure("online_odd", background="#F8FAFD", foreground=self.colors["text"])
        self.tree.tag_configure("offline_even", background="#FFF8F7", foreground=self.colors["text"])
        self.tree.tag_configure("offline_odd", background="#FCEFED", foreground=self.colors["text"])
        self.tree.tag_configure("virtual_even", background="#FFFFFF", foreground=self.colors["text_dim"])
        self.tree.tag_configure("virtual_odd", background="#F8FAFD", foreground=self.colors["text_dim"])
        self.tree.tag_configure("port_changed_even", background="#FFF9ED", foreground=self.colors["warning"])
        self.tree.tag_configure("port_changed_odd", background="#FFF5E7", foreground=self.colors["warning"])

    def _build_detail_panel(self):
        section = tk.Frame(self.root, bg=self.colors["bg"], padx=24, pady=12)
        section.pack(fill=tk.X, side=tk.BOTTOM)
        title_row = tk.Frame(section, bg=self.colors["bg"])
        title_row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(title_row, text="Printer details", font=("Segoe UI Semibold", 11),
                 fg=self.colors["text"], bg=self.colors["bg"]).pack(side=tk.LEFT)
        self.detail_hint = tk.Label(title_row, text="", font=("Segoe UI", 9),
                                    fg=self.colors["text_dim"], bg=self.colors["bg"])
        self.detail_hint.pack(side=tk.RIGHT)

        self.detail_frame = tk.Frame(
            section, bg=self.colors["surface"], padx=14, pady=8,
            highlightbackground=self.colors["border"], highlightthickness=1)
        self.detail_frame.pack(fill=tk.X)

        # One fixed grid (3 columns, filled top-to-bottom) so the panel keeps
        # the same height whichever printer is selected.
        labels = [label for label, _ in vl.build_detail_fields({})]
        per_column = -(-len(labels) // 3)
        self._detail_values = {}
        self._detail_widgets = {}
        self._detail_cells = []
        for col in range(3):
            self.detail_frame.columnconfigure(col, weight=1, uniform="detail")
        for index, label in enumerate(labels):
            col, row = divmod(index, per_column)
            cell = tk.Frame(self.detail_frame, bg=self.colors["surface"])
            cell.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 10, 0))
            cell.columnconfigure(2, weight=1)  # spare space goes after the copy button
            tk.Label(cell, text=label, width=13, anchor=tk.W, font=("Segoe UI", 9),
                     fg=self.colors["text_dim"], bg=self.colors["surface"]
                     ).grid(row=0, column=0, sticky="nw", pady=1)
            value = tk.Label(cell, text=vl.EMPTY, anchor=tk.W, justify=tk.LEFT,
                             font=("Segoe UI", 9), fg=self.colors["text"],
                             bg=self.colors["surface"], cursor="hand2")
            value.grid(row=0, column=1, sticky="nw", pady=1)
            value.bind("<Button-1>", lambda e, l=label: self._copy_detail(l))
            copy_btn = tk.Button(
                cell, text="\u29c9", font=("Segoe UI Symbol", 9), relief="flat",
                borderwidth=0, padx=4, pady=0, cursor="hand2",
                fg=self.colors["text_dim"], bg=self.colors["surface"],
                activebackground=self.colors["accent_soft"],
                activeforeground=self.colors["accent"], takefocus=True,
                state=tk.DISABLED, command=lambda l=label: self._copy_detail(l))
            copy_btn.grid(row=0, column=2, sticky="nw", padx=(2, 0))
            self._detail_values[label] = vl.EMPTY
            self._detail_widgets[label] = (value, copy_btn)
            self._detail_cells.append(cell)
        self.detail_frame.bind("<Configure>", self._on_detail_resize)
        self._detail_wrap = 0

    def _on_detail_resize(self, event):
        """Wrap long values to the current column width instead of a fixed size."""
        column_width = max(120, event.width // 3 - 150)
        if column_width == self._detail_wrap:
            return
        self._detail_wrap = column_width
        for value, _ in self._detail_widgets.values():
            value.config(wraplength=column_width)

    def _copy_detail(self, label):
        value = self._detail_values.get(label, vl.EMPTY)
        if value == vl.EMPTY:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self._flash_status(f"Copied {label}: {value}")

    def _flash_status(self, text, ms=2500):
        """Show a short status message, then restore the previous text."""
        current = self.status_label.cget("text")
        if self._flash_after_id is not None:
            self.root.after_cancel(self._flash_after_id)
            # Keep the original text, unless something else replaced the flash.
            if current != self._flash_text:
                self._flash_prev_text = current
        else:
            self._flash_prev_text = current
        self._flash_text = text
        self.status_label.config(text=text)

        def restore():
            self._flash_after_id = None
            # Only restore if nothing else has replaced the message meanwhile.
            if self.status_label.cget("text") == text:
                self.status_label.config(text=self._flash_prev_text)

        self._flash_after_id = self.root.after(ms, restore)

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=self.colors["header_bg"],
                       highlightbackground=self.colors["border"], highlightthickness=1,
                       padx=24, pady=11)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_text = tk.Frame(bar, bg=self.colors["header_bg"])
        status_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.status_label = tk.Label(status_text, text="Ready", font=("Segoe UI Semibold", 9),
                                     fg=self.colors["text"], bg=self.colors["header_bg"], anchor=tk.W)
        self.status_label.pack(anchor=tk.W)
        self.time_label = tk.Label(status_text, text="Printers will be scanned automatically.",
                                   font=("Segoe UI", 8), fg=self.colors["text_dim"],
                                   bg=self.colors["header_bg"], anchor=tk.W)
        self.time_label.pack(anchor=tk.W, pady=(2, 0))
        self.scan_progress = ttk.Progressbar(
            bar, mode="indeterminate", length=150, style="Scan.Horizontal.TProgressbar")
        self.scan_progress.pack(side=tk.RIGHT, padx=(16, 0))

    # ----- Scanning -----

    def refresh_printers(self):
        if self._scan_thread and self._scan_thread.is_alive():
            return
        self.status_label.config(text="Scanning printers...")
        self.time_label.config(text="Reading Windows printer and port information.")
        self.scan_progress.start(12)
        self.refresh_btn.config(state=tk.DISABLED, text="Scanning...")
        self.default_btn.config(state=tk.DISABLED)
        self.root.update_idletasks()
        self._scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._scan_thread.start()

    def _scan_worker(self):
        import time
        t0 = time.time()
        try:
            printers, port_details, pnp_printers, usb_ports = collect_all_printer_data()

            # Pings for network printers (parallel)
            ping_results = {}
            network_printers = [(p["name"], extract_host_from_port(p["port"], port_details.get(p["port"])))
                                for p in printers
                                if _is_network_port(p["port"].upper(), port_details.get(p["port"]))]

            if network_printers:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futs = {pool.submit(ping_host, host): name
                            for name, host in network_printers if host}
                    for f in as_completed(futs):
                        ping_results[futs[f]] = f.result()

            # Build results
            results = []
            for printer in printers:
                port_info = port_details.get(printer["port"], {})
                conn_type = detect_port_type(printer["port"], port_info)

                # Network status from ping
                if printer["name"] in ping_results:
                    work_offline = printer.get("work_offline", False)
                    reachable = ping_results[printer["name"]]
                    if work_offline:
                        st = ("Offline (Set Offline, Host Reachable)", False) if reachable else ("Offline (Host Unreachable)", False)
                    else:
                        st = ("Online (Reachable)", True) if reachable else ("Offline (Unreachable)", False)
                    status_text, is_online = st
                else:
                    status_text, is_online = determine_device_status(printer, port_details, pnp_printers)

                phys = find_physical_port_for_printer(printer["name"], printer["port"], pnp_printers, usb_ports)

                if phys:
                    pp, pr, up, vp = phys["physical_port"], phys["location_raw"], phys["usb_path"], phys["vid_pid"]
                elif _is_network_port(printer["port"].upper(), port_info):
                    host = extract_host_from_port(printer["port"], port_info)
                    pp, pr, up, vp = host or "Network", "", "", ""
                elif _is_virtual_printer(printer["port"], printer["driver"]):
                    pp, pr, up, vp = "Virtual", "", "", ""
                else:
                    pp, pr, up, vp = printer["port"], "", "", ""

                results.append({
                    "name": printer["name"], "port": printer["port"],
                    "physical_port": pp, "physical_raw": pr,
                    "usb_path": up, "vid_pid": vp,
                    "connection": conn_type, "driver": printer["driver"],
                    "status_text": status_text, "is_online": is_online,
                    "shared": printer["shared"], "type": printer["type"],
                    "is_default": printer.get("is_default", False),
                })

            elapsed = time.time() - t0
            self.root.after(0, self._update_table, results, port_details, elapsed)
        except Exception as e:
            self.root.after(0, self._scan_error, str(e))

    def _update_table(self, results, port_details, elapsed):
        self.port_details = port_details
        self.printer_data = results
        self._scanned_once = True

        # Detect physical port changes since the previous scan
        port_changes = []
        self._changed_ports = set()
        for p in results:
            prev = self._prev_physical_ports.get(p["name"])
            if (prev is not None and prev != p["physical_port"]
                    and p["physical_port"] not in ("Virtual", "")):
                self._changed_ports.add(p["name"])
                port_changes.append(f"{p['name']}: {prev} → {p['physical_port']}")
        self._prev_physical_ports = {p["name"]: p["physical_port"] for p in results}

        self._apply_view()

        total = len(results)
        if not results:
            self.status_label.config(text="No printers detected")
            self.time_label.config(text="Windows did not return any installed printers.")
            self.count_label.config(text="No printers found")
            self.scan_time_label.config(text="")
        else:
            self.count_label.config(text=f"{total} printer{'s' if total != 1 else ''}")
            self.scan_time_label.config(text=f"{elapsed:.1f}s")
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.time_label.config(text=f"Last scanned {now}")
            msg = "Scan complete"
            if port_changes:
                msg = f"Port changed: {'; '.join(port_changes)}"
            self.status_label.config(text=msg)

        self.scan_progress.stop()
        self.refresh_btn.config(state=tk.NORMAL, text="Refresh printers")
        self._update_details()

    # ----- View pipeline: filter -> sort -> render -----

    def _apply_view(self):
        """Render self.printer_data through the current search, chips and sort."""
        all_rows = self.printer_data
        query = self.search_var.get()
        status = self.status_filter.get()
        connection = self.connection_filter.get()

        self._update_chips(all_rows, query, status, connection)

        rows = vl.sort_rows(vl.filter_rows(all_rows, query, status, connection),
                            self.sort_column, self.sort_direction)
        self._visible_rows = rows

        # Remember selection and scroll position so a re-render is invisible
        selected = self.tree.selection()
        selected_iid = selected[0] if selected else None
        top_fraction = self.tree.yview()[0]

        self._rendering = True
        try:
            self.tree.delete(*self.tree.get_children())
            self._row_by_iid = {}
            iid_by_name = {}
            for i, p in enumerate(rows):
                iid = p["name"]
                if iid in self._row_by_iid:  # names are unique in Windows; be safe anyway
                    iid = f"{p['name']}#{i}"
                self._row_by_iid[iid] = p
                iid_by_name.setdefault(p["name"], iid)

                kind = vl.classify_status(p)
                parity = "even" if i % 2 == 0 else "odd"
                changed = p["name"] in self._changed_ports
                tag = f"port_changed_{parity}" if changed else f"{kind}_{parity}"
                physical = f"⟳ {p['physical_port']}" if changed else p["physical_port"]
                self.tree.insert("", tk.END, iid=iid, values=(
                    vl.status_badge(kind), "Default" if p.get("is_default") else "—",
                    p["name"], physical, p["port"],
                    p["connection"], p["status_text"], p["driver"],
                ), tags=(tag,))

            if selected_iid in self._row_by_iid:
                self.tree.selection_set(selected_iid)
                self.tree.focus(selected_iid)
                self.tree.yview_moveto(top_fraction)
        finally:
            self._rendering = False

        self._update_heading_arrows()
        self._update_empty_state(len(rows), len(all_rows))
        filtered = len(rows) != len(all_rows)
        self.showing_label.config(
            text=f"Showing {len(rows)} of {len(all_rows)}" if filtered else "")
        self._update_details()

    # Relative widths of the resizable columns (status and default are fixed)
    _COLUMN_WEIGHTS = {"printer": 190, "physical_port": 150, "win_port": 160,
                       "connection": 170, "device_status": 220, "driver": 200}

    def _fit_columns(self, event):
        """Share the table width between data columns so none are clipped."""
        fixed = sum(int(self.tree.column(c, "width")) for c in ("status", "default"))
        available = event.width - fixed - 4
        total_weight = sum(self._COLUMN_WEIGHTS.values())
        for col, weight in self._COLUMN_WEIGHTS.items():
            minimum = int(self.tree.column(col, "minwidth"))
            self.tree.column(col, width=max(minimum, available * weight // total_weight))

    def _update_chips(self, rows, query, status, connection):
        counts = vl.chip_counts(rows, query, status, connection)
        for value, chip in self.status_chips.items():
            n = counts["status"][value]
            chip.config(text=f"{self.STATUS_CHIP_LABELS[value]}  {n}")
            if value == vl.STATUS_OFFLINE:
                chip.config(style="ChipBad.Toolbutton" if n else "Chip.Toolbutton")
        for value, chip in self.connection_chips.items():
            n = counts["connection"][value]
            chip.config(text=f"{self.CONNECTION_CHIP_LABELS[value]}  {n}")

    def _update_heading_arrows(self):
        for col, text in self._heading_text.items():
            if col == self.sort_column:
                arrow = "▲" if self.sort_direction == "asc" else "▼"
                text = f"{text} {arrow}"
            self.tree.heading(col, text=text)

    def _update_empty_state(self, visible, total):
        if visible:
            self.empty_frame.place_forget()
            return
        if not self._scanned_once:
            title, message, show_clear = "Scanning printers…", "", False
        elif total == 0:
            title = "No printers detected"
            message = "Windows did not return any installed printers."
            show_clear = False
        else:
            title = "No printers match your filters"
            message = "Try a different search, or clear the filters."
            show_clear = True
        self.empty_title.config(text=title)
        self.empty_message.config(text=message)
        if show_clear:
            self.empty_clear_btn.pack(pady=(12, 0))
        else:
            self.empty_clear_btn.pack_forget()
        self.empty_frame.place(relx=0.5, rely=0.55, anchor="center")
        self.empty_frame.lift()

    def _on_heading_click(self, column):
        self.sort_column, self.sort_direction = vl.next_sort_state(
            self.sort_column, self.sort_direction, column)
        self._apply_view()
        self._save_settings()

    def _scan_error(self, error_msg):
        self.status_label.config(text="Scan failed")
        self.time_label.config(text=error_msg)
        self.scan_progress.stop()
        self.refresh_btn.config(state=tk.NORMAL, text="Refresh printers")
        self.default_btn.config(state=tk.DISABLED)

    # ----- Selection & details -----

    def _selected_row(self):
        sel = self.tree.selection()
        return self._row_by_iid.get(sel[0]) if sel else None

    def _on_select(self, event=None):
        if self._rendering:
            return
        self._update_details()

    def _update_details(self):
        """Fill the details grid from the selected row (or blank it)."""
        row = self._selected_row()
        if row is None:
            fields = vl.build_detail_fields({})
            self.detail_hint.config(text="Select a printer to see its details")
            self.default_btn.config(state=tk.DISABLED)
        else:
            port_info = self.port_details.get(row["port"], {})
            host = extract_host_from_port(row["port"], port_info)
            fields = vl.build_detail_fields(row, port_info, host)
            self.detail_hint.config(text="Click a value or ⧉ to copy it")
            self.default_btn.config(
                state=tk.DISABLED if row.get("is_default") else tk.NORMAL)

        if row is None:
            fields = [(label, vl.EMPTY) for label, _ in fields]
        kind = vl.classify_status(row) if row else None
        status_color = {vl.STATUS_ONLINE: self.colors["success"],
                        vl.STATUS_OFFLINE: self.colors["error"]}.get(kind, self.colors["text_dim"])

        for label, value in fields:
            self._detail_values[label] = value
            value_widget, copy_btn = self._detail_widgets[label]
            shown = value
            color = self.colors["text"] if value != vl.EMPTY else self.colors["text_dim"]
            if label == "Status" and row is not None:
                shown = f"{vl.status_symbol(kind)} {value}"
                color = status_color
            value_widget.config(text=shown, fg=color)
            copy_btn.config(state=tk.DISABLED if value == vl.EMPTY else tk.NORMAL)

    def _toggle_auto_refresh(self):
        if self.auto_refresh_enabled.get():
            self._schedule_auto_refresh()
        else:
            if self._auto_refresh_id:
                self.root.after_cancel(self._auto_refresh_id)
                self._auto_refresh_id = None

    def _schedule_auto_refresh(self):
        if self.auto_refresh_enabled.get():
            self.refresh_printers()
            self._auto_refresh_id = self.root.after(self.AUTO_REFRESH_MS, self._schedule_auto_refresh)

    def copy_to_clipboard(self):
        """Copy a text report of the printers currently shown in the table."""
        rows = self._visible_rows
        if not rows:
            messagebox.showinfo("Info", "No printer data to copy.")
            return
        total = len(self.printer_data)
        lines = [
            f"PortLens {get_version()} Report",
            f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if len(rows) != total:
            lines.append(f"Showing {len(rows)} of {total} printers (filtered view)")
        lines += ["=" * 65, ""]
        for p in rows:
            lines += [f"  Printer:         {p['name']}",
                      f"  Default:         {'Yes' if p.get('is_default') else 'No'}",
                      f"  Physical Port:   {p['physical_port']}", f"  Windows Port:    {p['port']}",
                      f"  Connection:      {p['connection']}", f"  Device Status:   {p['status_text']}",
                      f"  Driver:          {p['driver']}", "-" * 55]
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self._flash_status(f"Copied report for {len(rows)} printer{'s' if len(rows) != 1 else ''}")

    # ----- Print Test Page & Printer Actions -----

    def _get_selected_printer_name(self):
        """Get the printer name from the current treeview selection."""
        row = self._selected_row()
        return row["name"] if row else None
    def set_selected_as_default(self):
        """Set the selected printer as the Windows default printer."""
        printer_name = self._get_selected_printer_name()
        if not printer_name:
            messagebox.showwarning("No Printer Selected",
                                   "Please select a printer from the list first.")
            return

        selected = next((p for p in self.printer_data
                         if p["name"] == printer_name), {})
        if selected.get("is_default"):
            self.status_label.config(text=f"{printer_name} is already the default printer")
            self.default_btn.config(state=tk.DISABLED)
            return

        self.default_btn.config(state=tk.DISABLED)
        self.status_label.config(text=f"Setting {printer_name} as default...")
        self.root.update_idletasks()
        try:
            if HAS_WIN32PRINT:
                win32print.SetDefaultPrinter(printer_name)
            else:
                result = subprocess.run(
                    ["rundll32", "printui.dll,PrintUIEntry", "/y", "/n", printer_name],
                    capture_output=True, text=True, timeout=15,
                    creationflags=_CF, check=False)
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or
                                       "Windows rejected the default printer change.")

            for printer in self.printer_data:
                printer["is_default"] = printer["name"] == printer_name
            self._apply_view()

            self.status_label.config(text="Default printer updated")
            self.time_label.config(text=f"{printer_name} is now the Windows default printer.")
        except Exception as exc:
            self.default_btn.config(state=tk.NORMAL)
            self.status_label.config(text="Could not change the default printer")
            messagebox.showerror(
                "Set Default Printer Failed",
                f'Could not set this printer as default:\n\n"{printer_name}"\n\n{exc}')

    def _show_context_menu(self, event):
        """Show context menu on right-click, selecting the row under cursor."""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.tree.focus(item)
            self._on_select(event)
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

    def print_test_page(self):
        """Print an app-generated diagnostic page to the selected printer."""
        printer_name = self._get_selected_printer_name()
        if not printer_name:
            messagebox.showwarning("No Printer Selected",
                                    "Please select a printer from the list first.")
            return

        # Check if it's a virtual printer
        full = next((p for p in self.printer_data if p["name"] == printer_name), {})
        if full.get("is_online") is None:  # virtual
            messagebox.showinfo("Virtual Printer",
                                f'"{printer_name}" is a virtual printer.\n'
                                "Test pages can only be sent to physical printers.")
            return

        # Confirm with the user
        confirm = messagebox.askyesno(
            "Print Custom Test Page",
            f'Send a PortLens test page to:\n\n"{printer_name}"?\n\n'
            "The page includes connection details, color and grayscale checks,\n"
            "fine-line and text samples, and alignment marks.",
            icon="question")
        if not confirm:
            return

        self.status_label.config(text=f"Sending test page to {printer_name}...")
        self.root.update_idletasks()

        # The page shows the network host, which is not part of the table row
        info = dict(full)
        port = full.get("port", "")
        info["host"] = extract_host_from_port(port, self.port_details.get(port)) or ""

        # Run in a thread to avoid freezing the GUI
        threading.Thread(target=self._do_print_test_page,
                         args=(printer_name, info), daemon=True).start()

    def _do_print_test_page(self, printer_name, printer_info):
        """Render and submit the app's diagnostic test page."""
        try:
            if not HAS_PRINT_GDI:
                raise RuntimeError("Custom printing requires the pywin32 package.")
            self._render_test_page(printer_name, printer_info)
            self.root.after(0, lambda: self.status_label.config(
                text=f"Test page sent to {printer_name}"))
        except Exception as exc:
            error = str(exc)
            self.root.after(
                0, lambda error=error: self._test_page_error(printer_name, error))

    def _render_test_page(self, printer_name, info):
        """Send the diagnostic page (drawn by print_page.py) to the printer."""
        dc = win32ui.CreateDC()
        document_started = False
        page_started = False
        try:
            dc.CreatePrinterDC(printer_name)
            metrics = print_page.collect_metrics(dc, printer_name)

            dc.StartDoc("PortLens - Test Page")
            document_started = True
            dc.StartPage()
            page_started = True

            print_page.draw_test_page(
                dc, printer_name, info, metrics,
                resource_path("portlens_logo.png"), version=get_version())

            dc.EndPage()
            page_started = False
            dc.EndDoc()
            document_started = False
        except Exception:
            if page_started or document_started:
                try:
                    dc.AbortDoc()
                except Exception:
                    pass
            raise
        finally:
            dc.DeleteDC()

    def _test_page_error(self, printer_name, error):
        self.status_label.config(text=f"❌ Test page failed: {error}")
        messagebox.showerror("Print Test Page Failed",
                              f'Could not print test page to:\n"{printer_name}"\n\n{error}')

    def _open_printer_properties(self):
        """Open the Windows printer properties dialog for the selected printer."""
        printer_name = self._get_selected_printer_name()
        if not printer_name:
            messagebox.showwarning("No Printer Selected",
                                    "Please select a printer from the list first.")
            return
        try:
            # /e = display properties, /n = printer name
            subprocess.Popen(
                ["rundll32", "printui.dll,PrintUIEntry", "/e", "/n", printer_name],
                creationflags=_CF,
            )
            self.status_label.config(text=f"Opening properties for {printer_name}...")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open properties:\n{e}")

    def _open_printer_queue(self):
        """Open the printer queue window for the selected printer."""
        printer_name = self._get_selected_printer_name()
        if not printer_name:
            messagebox.showwarning("No Printer Selected",
                                    "Please select a printer from the list first.")
            return
        try:
            # /o = open printer queue, /n = printer name
            subprocess.Popen(
                ["rundll32", "printui.dll,PrintUIEntry", "/o", "/n", printer_name],
                creationflags=_CF,
            )
            self.status_label.config(text=f"Opening queue for {printer_name}...")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open queue:\n{e}")


def main():
    root = tk.Tk()
    try:
        root.iconbitmap(resource_path("portlens.ico"))
    except tk.TclError:
        try:
            root.iconphoto(True, tk.PhotoImage(file=resource_path("portlens_logo.png")))
        except tk.TclError:
            pass
    PortLensApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
