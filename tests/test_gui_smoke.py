"""Smoke tests that drive the real Tk UI with fake scan results (no printers needed)."""
import os
import sys
import time
import tkinter as tk

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portlens as pd  # noqa: E402


def make_row(name, port="USB001", physical="USB Port 1", connection="\U0001F50C USB",
             driver="Driver", status="Online", online=True, default=False, **extra):
    row = {
        "name": name, "port": port, "physical_port": physical, "physical_raw": "",
        "usb_path": "", "vid_pid": "", "connection": connection, "driver": driver,
        "status_text": status, "is_online": online, "shared": "No", "type": "Local",
        "is_default": default,
    }
    row.update(extra)
    return row


def scan_results():
    return [
        make_row("HP {LaserJet} 400", physical="USB Port 2", driver="HP Universal",
                 default=True, vid_pid="VID_03F0&PID_1234"),
        make_row("Canon Net", port="IP_10.0.0.5", physical="10.0.0.5",
                 connection="\U0001F310 Network (10.0.0.5)", driver="Canon UFR",
                 status="Offline (Unreachable)", online=False),
        make_row("PDF Writer", port="PORTPROMPT:", physical="Virtual",
                 connection="\U0001F4DD Prompt", driver="Microsoft Print To PDF",
                 status="N/A (Virtual)", online=None),
    ]


@pytest.fixture(scope="session")
def tk_root():
    """One hidden Tk root for the whole run; each test gets its own Toplevel.

    Creating many Tk interpreters back-to-back can intermittently fail to read
    init.tcl on some machines, so the interpreter is created once (with retries).
    """
    last_error = None
    for _ in range(5):
        try:
            root = tk.Tk()
            break
        except tk.TclError as exc:
            last_error = exc
            time.sleep(0.3)
    else:
        pytest.skip(f"Tk is not available in this environment: {last_error}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def make_app(monkeypatch, tmp_path, tk_root):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(pd.PortLensApp, "refresh_printers", lambda self: None)
    windows = []

    def factory():
        window = tk.Toplevel(tk_root)
        window.withdraw()
        windows.append(window)
        return pd.PortLensApp(window)

    yield factory
    for window in windows:
        window.destroy()


@pytest.fixture
def app(make_app):
    return make_app()

def select(app, iid):
    app.tree.selection_set(iid)
    app.root.update()  # deliver <<TreeviewSelect>>


def shown_names(app):
    return [app.tree.set(i, "printer") for i in app.tree.get_children()]


def test_rows_use_text_badges_and_counts(app):
    app._update_table(scan_results(), {}, 0.1)
    assert len(app.tree.get_children()) == 3
    badges = {app.tree.set(i, "printer"): app.tree.set(i, "status") for i in app.tree.get_children()}
    assert badges["HP {LaserJet} 400"] == "\u25cf Online"
    assert badges["Canon Net"] == "\u25cf Offline"
    assert badges["PDF Writer"] == "\u2013 Virtual"
    assert "Offline  1" in str(app.status_chips["offline"].cget("text"))
    assert app.showing_label.cget("text") == ""


def test_search_and_chips_filter_rows(app):
    app._update_table(scan_results(), {}, 0.1)
    app.search_var.set("canon")
    assert shown_names(app) == ["Canon Net"]
    assert app.showing_label.cget("text") == "Showing 1 of 3"

    app.search_var.set("zzz")
    assert shown_names(app) == []
    assert app.empty_frame.winfo_manager() == "place"
    assert app.empty_title.cget("text") == "No printers match your filters"

    app._clear_filters()
    assert len(shown_names(app)) == 3
    assert app.empty_frame.winfo_manager() == ""

    app.status_filter.set("offline")
    app.connection_filter.set("Network")
    app._on_filter_changed(save=True)
    assert shown_names(app) == ["Canon Net"]
    app.connection_filter.set("USB")
    app._on_filter_changed(save=True)
    assert shown_names(app) == []


def test_sort_by_heading_cycles_and_shows_arrow(app):
    app._update_table(scan_results(), {}, 0.1)
    app._on_heading_click("printer")
    assert shown_names(app) == ["Canon Net", "HP {LaserJet} 400", "PDF Writer"]
    assert "\u25b2" in app.tree.heading("printer", "text")
    app._on_heading_click("printer")
    assert shown_names(app) == ["PDF Writer", "HP {LaserJet} 400", "Canon Net"]
    assert "\u25bc" in app.tree.heading("printer", "text")
    app._on_heading_click("printer")
    assert shown_names(app) == ["HP {LaserJet} 400", "Canon Net", "PDF Writer"]  # scan order
    assert app.tree.heading("printer", "text") == "Printer Name"


def test_selection_survives_refresh_and_filter(app):
    app._update_table(scan_results(), {}, 0.1)
    name = "HP {LaserJet} 400"  # braces/spaces must work as item ids
    select(app, name)
    assert app._selected_row()["name"] == name

    app._update_table(scan_results(), {}, 0.1)          # refresh
    assert app._selected_row()["name"] == name

    app._on_heading_click("driver")                       # re-sort
    assert app._selected_row()["name"] == name

    app.search_var.set("canon")                           # hidden by filter
    assert app._selected_row() is None
    assert app._detail_values["Printer"] == pd.vl.EMPTY

    app.search_var.set("")
    select(app, name)
    app._update_table(scan_results()[1:], {}, 0.1)       # printer removed
    assert app._selected_row() is None


def test_details_grid_and_copy(app):
    app._update_table(scan_results(), {}, 0.1)
    assert app._detail_values["Printer"] == pd.vl.EMPTY
    select(app, "HP {LaserJet} 400")
    assert app._detail_values["Driver"] == "HP Universal"
    assert app._detail_values["USB device ID"] == "VID_03F0&PID_1234"
    assert app._detail_values["Host address"] == pd.vl.EMPTY
    assert str(app._detail_widgets["Driver"][1].cget("state")) == "normal"
    assert str(app._detail_widgets["Host address"][1].cget("state")) == "disabled"
    assert str(app.default_btn.cget("state")) == "disabled"   # already default

    app._copy_detail("Driver")
    assert app.root.clipboard_get() == "HP Universal"
    assert app.status_label.cget("text").startswith("Copied Driver")

    select(app, "Canon Net")
    assert app._detail_values["Host address"] == "10.0.0.5"
    assert str(app.default_btn.cget("state")) == "normal"


def test_copy_report_uses_visible_rows(app):
    app._update_table(scan_results(), {}, 0.1)
    app.search_var.set("canon")
    app.copy_to_clipboard()
    text = app.root.clipboard_get()
    assert "Canon Net" in text and "PDF Writer" not in text
    assert "Showing 1 of 3" in text


def test_port_change_marker_and_counts(app):
    first = scan_results()
    app._update_table(first, {}, 0.1)
    moved = scan_results()
    moved[0]["physical_port"] = "USB Port 4"
    app._update_table(moved, {}, 0.1)
    assert app.tree.set("HP {LaserJet} 400", "physical_port") == "\u27f3 USB Port 4"
    assert "Port changed" in app.status_label.cget("text")
    # a changed-port printer is still counted as online
    assert "Online  1" in str(app.status_chips["online"].cget("text"))


def test_settings_persist_between_launches(app, make_app):
    app._update_table(scan_results(), {}, 0.1)
    app._on_heading_click("driver")
    app._on_heading_click("driver")   # descending
    app.status_filter.set("offline")
    app._on_filter_changed(save=True)
    app.search_var.set("not saved")

    second = make_app()
    assert second.sort_column == "driver"
    assert second.sort_direction == "desc"
    assert second.status_filter.get() == "offline"
    assert second.search_var.get() == ""

def test_flash_status_restores_previous_text(app):
    app.status_label.config(text="Scan complete")
    app._flash_status("Copied X", ms=20)
    assert app.status_label.cget("text") == "Copied X"
    time.sleep(0.1)
    app.root.update()
    assert app.status_label.cget("text") == "Scan complete"


def test_flash_does_not_overwrite_newer_status(app):
    app.status_label.config(text="Scan complete")
    app._flash_status("Copied X", ms=20)
    app.status_label.config(text="Scanning printers...")
    time.sleep(0.1)
    app.root.update()
    assert app.status_label.cget("text") == "Scanning printers..."