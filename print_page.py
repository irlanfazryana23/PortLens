"""
Printer test page renderer for PortLens.

draw_test_page() draws onto any Windows GDI device context, so the same code
prints to a real printer and renders to an in-memory bitmap (render_preview)
for checking the layout without using paper.

The page is designed on a fixed "design canvas" measured in inches and scaled
to fit the printer's printable area, so it works on Letter, A4, A5 and so on.
"""

import datetime
import os
import platform

from view_logic import EMPTY, plain_text

try:
    import win32con
    import win32gui
    import win32ui
    from PIL import Image, ImageWin
    HAS_GDI = True
except ImportError:  # pywin32 / Pillow missing: printing is unavailable
    HAS_GDI = False

try:
    import win32print
except ImportError:
    win32print = None

# --- Design constants (inches on the design canvas) -------------------------

DESIGN_W = 7.6
DESIGN_H = 10.3
MARGIN = 0.35
CONTENT_W = DESIGN_W - 2 * MARGIN

PALETTE = {
    "blue": "#102AAF", "orange": "#FF8900", "navy": "#172443", "muted": "#63718A",
    "border": "#DCE2EE", "light": "#F5F7FC", "white": "#FFFFFF",
    "success": "#16835A", "error": "#B33E36",
}

# (label, color) for the color check row
SWATCHES = [
    ("CYAN", "#00AEEF"), ("MAGENTA", "#EC008C"), ("YELLOW", "#FFF200"),
    ("BLACK", "#000000"), ("RED", "#ED1C24"), ("GREEN", "#00A651"),
    ("BLUE", "#2E3192"),
]

# Line weights (points) for the fine line test
LINE_WEIGHTS_PT = (0.25, 0.5, 1.0, 2.0)

CHECKLIST = (
    "Colors are solid, with no streaks or missing bands",
    "All grayscale steps look different from their neighbors",
    "Fine lines are sharp and unbroken",
    "The smallest text is readable",
    "All four corner marks are visible",
)

_KNOWN_PAPER = {
    (210, 297): "A4", (216, 279): "Letter", (148, 210): "A5",
    (216, 356): "Legal", (297, 420): "A3", (105, 148): "A6",
}


# --- Pure helpers (unit tested) ---------------------------------------------

def colorref(hex_color):
    """Convert #RRGGBB into the COLORREF integer used by Windows GDI."""
    value = hex_color.lstrip("#")
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return red | (green << 8) | (blue << 16)


def compute_scale(printable_w_in, printable_h_in):
    """Scale factor that fits the design canvas into the printable area."""
    k = min(printable_w_in / DESIGN_W, printable_h_in / DESIGN_H)
    return max(0.3, min(k, 1.25))


def gray_steps(count=11):
    """(label, gray level) pairs from 0% ink (white) to 100% ink (black)."""
    steps = []
    for i in range(count):
        coverage = i / (count - 1)
        steps.append((f"{round(coverage * 100)}%", round(255 * (1 - coverage))))
    return steps


def paper_label(width_in, height_in):
    """Human readable paper size, e.g. 'A4 (210 x 297 mm)'."""
    w_mm, h_mm = round(width_in * 25.4), round(height_in * 25.4)
    size = f"{w_mm} \u00d7 {h_mm} mm"
    for (kw, kh), name in _KNOWN_PAPER.items():
        if abs(w_mm - kw) <= 3 and abs(h_mm - kh) <= 3:
            return f"{name} ({size})"
    return size


def line_px(points, dpi):
    """Thickness in device pixels for a line of the given weight (min 1)."""
    return max(1, int(round(points * dpi / 72)))


def detail_rows(printer_name, info):
    """
    Left and right columns for the printer details card, 5 rows each.
    Returns (left_rows, right_rows) of (label, value) pairs.
    """
    def val(key):
        text = str(info.get(key) or "").strip()
        return text or EMPTY

    left = [
        ("Printer", printer_name or EMPTY),
        ("Default printer", "Yes" if info.get("is_default") else "No"),
        ("Type", val("type")),
        ("Shared", val("shared")),
        ("Driver", val("driver")),
    ]
    right = [
        ("Connection", plain_text(info.get("connection")) or EMPTY),
        ("Windows port", val("port")),
    ]
    for label, key in (("Host address", "host"), ("USB device ID", "vid_pid"),
                       ("Location", "physical_raw"), ("USB path", "usb_path")):
        if str(info.get(key) or "").strip():
            right.append((label, val(key)))
    right.append(("Computer", computer_name()))
    return left, right[:5]


def computer_name():
    return os.environ.get("COMPUTERNAME") or platform.node() or EMPTY


# --- Device metrics ---------------------------------------------------------

def printer_is_color(printer_name):
    """True / False from the printer's default DEVMODE, or None if unknown."""
    if win32print is None or not printer_name:
        return None
    handle = None
    try:
        handle = win32print.OpenPrinter(printer_name)
        devmode = win32print.GetPrinter(handle, 2).get("pDevMode")
        color = getattr(devmode, "Color", 0)
        return True if color == 2 else False if color == 1 else None
    except Exception:
        return None
    finally:
        if handle is not None:
            try:
                win32print.ClosePrinter(handle)
            except Exception:
                pass


def collect_metrics(dc, printer_name=None):
    """Read the printable area, physical paper size and resolution from a printer DC."""
    page_w = dc.GetDeviceCaps(win32con.HORZRES)
    page_h = dc.GetDeviceCaps(win32con.VERTRES)
    return {
        "page_w": page_w, "page_h": page_h,
        "dpi_x": dc.GetDeviceCaps(win32con.LOGPIXELSX),
        "dpi_y": dc.GetDeviceCaps(win32con.LOGPIXELSY),
        "phys_w": dc.GetDeviceCaps(win32con.PHYSICALWIDTH) or page_w,
        "phys_h": dc.GetDeviceCaps(win32con.PHYSICALHEIGHT) or page_h,
        "color": printer_is_color(printer_name),
    }


# --- Drawing ----------------------------------------------------------------

def draw_test_page(dc, printer_name, info, metrics, logo_path, now=None, version=None):
    """Draw the complete test page on dc (printer DC or memory DC)."""
    now = now or datetime.datetime.now()
    pw, ph = metrics["page_w"], metrics["page_h"]
    dpx, dpy = float(metrics["dpi_x"]), float(metrics["dpi_y"])
    k = compute_scale(pw / dpx, ph / dpy)
    ox = max(0, int((pw - DESIGN_W * dpx * k) / 2))  # centre the canvas

    def sx(v):
        return int(round(v * dpx * k))

    def sy(v):
        return int(round(v * dpy * k))

    def X(v):
        return ox + sx(v)

    def Y(v):
        return sy(v)

    colors = {name: colorref(value) for name, value in PALETTE.items()}
    navy, muted, border, light = (colors[n] for n in ("navy", "muted", "border", "light"))
    white, blue, orange = colors["white"], colors["blue"], colors["orange"]

    fonts = {}

    def font_for(points, weight):
        key = (points, weight)
        if key not in fonts:
            fonts[key] = win32ui.CreateFont({
                "name": "Segoe UI", "weight": weight,
                "height": -max(1, int(points * k * dpy / 72)),
            })
        return fonts[key]

    def fill(x0, y0, x1, y1, color):
        if x1 > x0 and y1 > y0:
            dc.FillSolidRect((int(x0), int(y0), int(x1), int(y1)), color)

    def outline(x0, y0, x1, y1, color, t=1):
        fill(x0, y0, x1, y0 + t, color)
        fill(x0, y1 - t, x1, y1, color)
        fill(x0, y0, x0 + t, y1, color)
        fill(x1 - t, y0, x1, y1, color)

    def text(value, x, y, points=9, color=navy, weight=400, width=None,
             align="left", wrap=False):
        dc.SelectObject(font_for(points, weight))
        dc.SetTextColor(color)
        dc.SetBkMode(win32con.TRANSPARENT)
        width = width if width is not None else sx(CONTENT_W)
        flags = win32con.DT_NOPREFIX | {"left": win32con.DT_LEFT,
                                        "right": win32con.DT_RIGHT,
                                        "center": win32con.DT_CENTER}[align]
        flags |= win32con.DT_WORDBREAK if wrap else (win32con.DT_SINGLELINE |
                                                     win32con.DT_END_ELLIPSIS)
        # win32gui.DrawText is the wide-char (Unicode) API, so printer names with
        # accents or non-Latin characters print correctly.
        win32gui.DrawText(dc.GetHandleOutput(), str(value), -1,
                          (int(x), int(y), int(x + width), int(y + sy(1.5))), flags)

    original_font = dc.SelectObject(font_for(9, 400))
    try:
        # ---- Header band -------------------------------------------------
        band_top, band_bottom = Y(0.35), Y(1.30)
        fill(X(MARGIN), band_top, X(DESIGN_W - MARGIN), band_bottom, blue)
        fill(X(MARGIN), band_bottom, X(DESIGN_W - MARGIN), Y(1.35), orange)

        logo_size = sx(0.62)
        logo_x = X(MARGIN + 0.2)
        logo_y = band_top + (band_bottom - band_top - logo_size) // 2
        try:
            source = Image.open(logo_path).convert("RGBA")
            box = source.getbbox()  # trim transparent padding
            if box:
                source = source.crop(box)
            tile_px = 384  # high enough to stay sharp on 600 dpi printers
            scale = (tile_px * 0.8) / max(source.size)
            source = source.resize((max(1, round(source.width * scale)),
                                    max(1, round(source.height * scale))),
                                   Image.Resampling.LANCZOS)
            tile = Image.new("RGB", (tile_px, tile_px), "white")
            tile.paste(source, ((tile_px - source.width) // 2,
                                (tile_px - source.height) // 2), source)
            ImageWin.Dib(tile).draw(dc.GetHandleOutput(),
                                    (logo_x, logo_y, logo_x + logo_size, logo_y + logo_size))
        except Exception:
            pass  # a missing logo must never block a test page

        title_x = logo_x + logo_size + sx(0.2)
        text("PortLens", title_x, Y(0.52), 21, white, 700, sx(4.0))
        text("PRINTER TEST PAGE", title_x, Y(1.0), 9, white, 600, sx(4.0))
        right_x = X(DESIGN_W - MARGIN - 0.2 - 2.4)
        text(f"{now:%B %d, %Y}", right_x, Y(0.55), 9.5, white, 600, sx(2.4), "right")
        text(f"{now:%H:%M:%S}", right_x, Y(0.78), 9.5, white, 400, sx(2.4), "right")
        text(computer_name(), right_x, Y(1.0), 8, white, 400, sx(2.4), "right")

        # ---- Summary tiles -----------------------------------------------
        online = info.get("is_online") is True
        status_color = colors["success"] if online else colors["error"]
        connection = plain_text(info.get("connection")) or "Unknown"
        physical = str(info.get("physical_port") or EMPTY)
        status_text = str(info.get("status_text") or "").strip()
        value_text = "Online" if online else "Offline"
        # Avoid repeating "Online / Online"; show extra detail or the check time.
        status_sub = (status_text if status_text and status_text.lower() != value_text.lower()
                      else f"Checked {now:%H:%M:%S}")
        tile_gap = 0.15
        tile_w = (CONTENT_W - 2 * tile_gap) / 3
        tiles = [
            ("STATUS", "Online" if online else "Offline",
             status_sub, status_color, status_color),
            ("CONNECTION", connection, f"Windows port {info.get('port') or EMPTY}",
             navy, blue),
            ("PHYSICAL PORT", physical,
             str(info.get("vid_pid") or info.get("host") or ""), navy, orange),
        ]
        for i, (label, value, sub, value_color, accent) in enumerate(tiles):
            tx = MARGIN + i * (tile_w + tile_gap)
            fill(X(tx), Y(1.6), X(tx + tile_w), Y(2.35), light)
            fill(X(tx), Y(1.6), X(tx) + sx(0.06), Y(2.35), accent)
            inner = sx(tile_w - 0.3)
            text(label, X(tx + 0.18), Y(1.68), 7, muted, 700, inner)
            text(value, X(tx + 0.18), Y(1.86), 13, value_color, 700, inner)
            text(sub, X(tx + 0.18), Y(2.1), 8, muted, 400, inner)

        # ---- Printer details card ----------------------------------------
        def section(title, y):
            text(title, X(MARGIN), Y(y), 12, navy, 700)
            fill(X(MARGIN), Y(y + 0.35), X(DESIGN_W - MARGIN), Y(y + 0.35) + 2, border)

        section("Printer details", 2.6)
        left_rows, right_rows = detail_rows(printer_name, info)
        col_gap = 0.2
        col_w = (CONTENT_W - col_gap) / 2
        row_h = 0.3
        label_w = 1.1
        for col, rows in enumerate((left_rows, right_rows)):
            cx = MARGIN + col * (col_w + col_gap)
            for i, (label, value) in enumerate(rows):
                top = 3.05 + i * row_h
                if i % 2 == 0:
                    fill(X(cx), Y(top), X(cx + col_w), Y(top + row_h), light)
                text(label, X(cx + 0.08), Y(top + 0.07), 8.5, muted, 600, sx(label_w))
                text(value, X(cx + label_w + 0.1), Y(top + 0.07), 9, navy, 400,
                     sx(col_w - label_w - 0.18))

        # Page and system strip
        paper = paper_label(metrics.get("phys_w", pw) / dpx, metrics.get("phys_h", ph) / dpy)
        printable = paper_label(pw / dpx, ph / dpy).split("(")[-1].rstrip(")")
        color_mode = {True: "Color", False: "Monochrome", None: None}[metrics.get("color")]
        parts = [f"Paper  {paper}", f"Printable  {printable}",
                 f"Resolution  {int(dpx)} \u00d7 {int(dpy)} dpi"]
        if color_mode:
            parts.append(color_mode)
        fill(X(MARGIN), Y(4.7), X(DESIGN_W - MARGIN), Y(5.15), light)
        text("   \u00b7   ".join(parts), X(MARGIN + 0.1), Y(4.76), 8, navy, 400,
             sx(CONTENT_W - 0.2))
        text(f"Windows {platform.version()}   \u00b7   Computer  {computer_name()}",
             X(MARGIN + 0.1), Y(4.95), 8, muted, 400, sx(CONTENT_W - 0.2))

        # ---- Print quality checks ----------------------------------------
        section("Print quality checks", 5.35)

        def caption(label, y, x=MARGIN):
            text(label, X(x), Y(y), 7, muted, 700, sx(3.0))

        # Color swatches
        caption("COLOR", 5.78)
        gap = 0.08
        sw_w = (CONTENT_W - gap * (len(SWATCHES) - 1)) / len(SWATCHES)
        for i, (label, hex_color) in enumerate(SWATCHES):
            sxl = MARGIN + i * (sw_w + gap)
            fill(X(sxl), Y(5.95), X(sxl + sw_w), Y(6.42), colorref(hex_color))
            outline(X(sxl), Y(5.95), X(sxl + sw_w), Y(6.42), border)
            text(label, X(sxl), Y(6.46), 7, muted, 600, sx(sw_w), "center")

        # Grayscale ramp
        caption("GRAYSCALE (INK COVERAGE)", 6.68)
        steps = gray_steps()
        step_w = CONTENT_W / len(steps)
        for i, (label, level) in enumerate(steps):
            gx = MARGIN + i * step_w
            fill(X(gx), Y(6.85), X(gx + step_w), Y(7.2), colorref(f"#{level:02X}{level:02X}{level:02X}"))
            text(label, X(gx), Y(7.24), 7, muted, 600, sx(step_w), "center")
        outline(X(MARGIN), Y(6.85), X(DESIGN_W - MARGIN), Y(7.2), border)

        # Fine lines
        caption("FINE LINES", 7.5)
        for i, pts in enumerate(LINE_WEIGHTS_PT):
            t = line_px(pts, dpy)
            ly = Y(7.75 + i * 0.2)
            fill(X(MARGIN), ly, X(MARGIN + 1.5), ly + t, navy)
            text(f"{pts:g} pt", X(MARGIN + 1.6), Y(7.75 + i * 0.2) - sy(0.06), 7, muted, 400, sx(0.6))
        for i, pts in enumerate(LINE_WEIGHTS_PT):
            t = line_px(pts, dpx)
            lx = X(2.9 + i * 0.3)
            fill(lx, Y(7.67), lx + t, Y(8.47), navy)
            text(f"{pts:g}", lx - sx(0.15), Y(8.5), 7, muted, 400, sx(0.3), "center")

        # Text samples
        caption("TEXT SAMPLES", 7.5, x=4.05)
        sample = "Quick brown fox jumps over the lazy dog"
        text_w = sx(DESIGN_W - MARGIN - 4.05)
        for size, ty in ((7, 7.7), (9, 7.86), (11, 8.06)):
            text(f"{sample}", X(4.05), Y(ty), size, navy, 400, text_w)
        fill(X(4.05), Y(8.42), X(DESIGN_W - MARGIN), Y(8.68), navy)
        text("REVERSED TEXT   0123456789", X(4.15), Y(8.46), 9, white, 700, text_w - sx(0.2))

        # ---- Checklist ---------------------------------------------------
        caption("CHECKLIST", 8.85)
        col_x = (MARGIN, MARGIN + CONTENT_W / 2 + 0.1)
        for i, item in enumerate(CHECKLIST):
            cx = col_x[i % 2]
            cy = 9.07 + (i // 2) * 0.24
            box = sx(0.13)
            outline(X(cx), Y(cy), X(cx) + box, Y(cy) + box, navy, max(1, line_px(0.75, dpy)))
            text(item, X(cx + 0.22), Y(cy) - sy(0.025), 8, navy, 400, sx(CONTENT_W / 2 - 0.3))

        # ---- Footer ------------------------------------------------------
        fill(X(MARGIN), Y(9.8), X(DESIGN_W - MARGIN), Y(9.8) + 2, border)
        text("If this page is clear and complete, the print path is working.",
             X(MARGIN), Y(9.86), 9, navy, 700)
        suffix = f" {version}" if version else ""
        text(f"Generated by PortLens{suffix}. This page is drawn by the app, "
             "not by the Windows test page service.",
             X(MARGIN), Y(10.07), 7, muted, 400)

        # ---- Corner and edge marks at the real printable edges -----------
        arm = int(dpx * 0.25)
        t = max(2, int(dpx / 150))
        for x0, x1 in ((0, arm), (pw - arm, pw)):
            for y0, y1 in ((0, t), (ph - t, ph)):
                fill(x0, y0, x1, y1, navy)
        for x0, x1 in ((0, t), (pw - t, pw)):
            for y0, y1 in ((0, arm), (ph - arm, ph)):
                fill(x0, y0, x1, y1, navy)
        tick = int(dpx * 0.15)
        fill(pw // 2 - tick // 2, 0, pw // 2 + tick // 2, t, navy)
        fill(pw // 2 - tick // 2, ph - t, pw // 2 + tick // 2, ph, navy)
        fill(0, ph // 2 - tick // 2, t, ph // 2 + tick // 2, navy)
        fill(pw - t, ph // 2 - tick // 2, pw, ph // 2 + tick // 2, navy)
    finally:
        dc.SelectObject(original_font)


def render_preview(printer_name, info, metrics, logo_path, now=None, version=None):
    """Render the page to a PIL image (no printer needed) for checking the layout."""
    width, height = metrics["page_w"], metrics["page_h"]
    screen_hdc = win32gui.GetDC(0)
    screen = win32ui.CreateDCFromHandle(screen_hdc)
    memory = screen.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(screen, width, height)
    previous = memory.SelectObject(bitmap)
    try:
        memory.FillSolidRect((0, 0, width, height), colorref("#FFFFFF"))
        draw_test_page(memory, printer_name, info, metrics, logo_path, now, version)
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer("RGB", (width, height), bits, "raw", "BGRX", 0, 1)
    finally:
        memory.SelectObject(previous)
        memory.DeleteDC()
        screen.DeleteDC()
        win32gui.ReleaseDC(0, screen_hdc)
