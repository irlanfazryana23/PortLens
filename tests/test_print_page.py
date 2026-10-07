import datetime
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import print_page as pp  # noqa: E402

LOGO = os.path.join(ROOT, "assets", "portlens_logo.png")

INFO = {
    "is_online": True, "status_text": "Online", "is_default": True,
    "connection": "\U0001F50C USB", "physical_port": "USB Port 2", "port": "USB004",
    "driver": "EPSON L3110 Series", "type": "Local", "shared": "No",
    "vid_pid": "VID_04B8&PID_1142", "physical_raw": "Port_#0002.Hub_#0001",
    "usb_path": "PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(2)", "host": "",
}


def metrics(w_in, h_in, dpi, pad=0.17):
    return {"page_w": int((w_in - 2 * pad) * dpi), "page_h": int((h_in - 2 * pad) * dpi),
            "dpi_x": dpi, "dpi_y": dpi, "phys_w": int(w_in * dpi),
            "phys_h": int(h_in * dpi), "color": True}


# --- pure helpers ---

def test_colorref_is_bgr_integer():
    assert pp.colorref("#000000") == 0
    assert pp.colorref("#FF0000") == 0x0000FF
    assert pp.colorref("#00FF00") == 0x00FF00
    assert pp.colorref("#0000FF") == 0xFF0000
    assert pp.colorref("102AAF") == 0xAF2A10


def test_compute_scale_fits_and_clamps():
    assert pp.compute_scale(pp.DESIGN_W, pp.DESIGN_H) == pytest.approx(1.0)
    assert pp.compute_scale(100, 100) == 1.25          # never blow up
    assert pp.compute_scale(0.5, 0.5) == 0.3           # never vanish
    # limited by the tighter dimension
    assert pp.compute_scale(7.6 / 2, 50) == pytest.approx(0.5)


def test_gray_steps_cover_white_to_black():
    steps = pp.gray_steps()
    assert len(steps) == 11
    assert steps[0] == ("0%", 255)
    assert steps[-1] == ("100%", 0)
    levels = [lvl for _, lvl in steps]
    assert levels == sorted(levels, reverse=True)
    assert len(set(levels)) == 11


def test_paper_label():
    assert pp.paper_label(8.27, 11.69) == "A4 (210 \u00d7 297 mm)"
    assert pp.paper_label(8.5, 11.0) == "Letter (216 \u00d7 279 mm)"
    assert pp.paper_label(5.83, 8.27).startswith("A5")
    assert pp.paper_label(3.15, 10.0) == "80 \u00d7 254 mm"   # unknown size, no name


def test_line_px_minimum_one():
    assert pp.line_px(0.25, 72) == 1
    assert pp.line_px(2.0, 600) == 17
    assert pp.line_px(0.1, 96) == 1


def test_detail_rows_usb_and_network():
    left, right = pp.detail_rows("EPSON", INFO)
    assert [l for l, _ in left] == ["Printer", "Default printer", "Type", "Shared", "Driver"]
    assert dict(left)["Default printer"] == "Yes"
    labels = [l for l, _ in right]
    assert labels[:2] == ["Connection", "Windows port"]
    assert "USB device ID" in labels and len(right) == 5
    assert dict(right)["Connection"] == "USB"      # icon stripped

    net = dict(INFO, connection="\U0001F310 Network (10.0.0.5)", host="10.0.0.5",
               vid_pid="", physical_raw="", usb_path="", port="IP_10.0.0.5")
    _, right = pp.detail_rows("Canon", net)
    assert dict(right)["Host address"] == "10.0.0.5"
    assert "USB device ID" not in dict(right)
    assert right[-1][0] == "Computer"


def test_detail_rows_handle_missing_data():
    left, right = pp.detail_rows("", {})
    assert len(left) == 5 and len(right) <= 5
    assert dict(left)["Printer"] == pp.EMPTY
    assert dict(left)["Driver"] == pp.EMPTY


# --- rendering (bitmap, no printer or paper involved) ---

pytestmark_gdi = pytest.mark.skipif(not pp.HAS_GDI, reason="pywin32 / Pillow not available")


def _render(met, info=INFO, name="EPSON L3110 Series"):
    return pp.render_preview(name, info, met, LOGO, datetime.datetime(2026, 10, 7, 10, 42, 7))


def _count(img, box, predicate):
    """Count pixels in box whose (r, g, b) satisfy predicate."""
    region = img.crop(box)
    px = region.load()
    return sum(1 for x in range(region.width) for y in range(region.height)
               if predicate(*px[x, y]))


def _dark_pixels_in(img, box):
    return _count(img, box, lambda r, g, b: (r + g + b) / 3 < 90)


@pytestmark_gdi
@pytest.mark.parametrize("w,h,dpi", [(8.27, 11.69, 100), (8.5, 11.0, 100), (5.83, 8.27, 120)])
def test_page_renders_on_common_paper_sizes(w, h, dpi):
    met = metrics(w, h, dpi)
    img = _render(met)
    assert img.size == (met["page_w"], met["page_h"])
    # header band is the brand blue near the top-left of the canvas
    x = int(img.width * 0.5)
    r, g, b = img.getpixel((x, int(img.height * 0.09)))
    assert b > 120 and r < 60, "expected the blue header band"
    # page is not mostly empty
    assert _dark_pixels_in(img, (0, 0, img.width, img.height)) > 2000


@pytestmark_gdi
def test_corner_marks_touch_the_printable_edges():
    img = _render(metrics(8.5, 11.0, 100))
    w, h = img.size
    for corner in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)):
        assert sum(img.getpixel(corner)) < 300, f"missing corner mark at {corner}"


@pytestmark_gdi
def test_content_stays_inside_the_page_bottom():
    """Only the small edge tick may touch the last 8 pixel rows of the page."""
    img = _render(metrics(8.5, 11.0, 100))
    w, h = img.size
    dark = _count(img, (int(w * 0.1), h - 8, int(w * 0.9), h),
                  lambda r, g, b: (r + g + b) / 3 < 200)
    assert dark < 60  # bottom-centre tick is 15 x 2 px


@pytestmark_gdi
def test_unicode_and_long_names_do_not_break_rendering():
    info = dict(INFO, driver="Drücker Ünïcode \u65e5\u672c\u8a9e " + "x" * 200)
    img = _render(metrics(8.27, 11.69, 100), info, "Büro-Drucker \u65e5\u672c\u8a9e")
    assert img.size[0] > 0


@pytestmark_gdi
def test_offline_printer_uses_error_color_for_status():
    info = dict(INFO, is_online=False, status_text="Offline (USB Unplugged)")
    img = _render(metrics(8.5, 11.0, 100), info)
    reds = _count(img, (55, 190, 240, 225),   # status value inside the first tile
                  lambda r, g, b: r > 140 and g < 90 and b < 90)
    assert reds > 20


@pytestmark_gdi
def test_tiny_and_narrow_pages_do_not_raise():
    # e.g. a 4in label printer at low resolution
    img = _render(metrics(4.0, 6.0, 72, pad=0.1))
    assert img.size[0] > 0
