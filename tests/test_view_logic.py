import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import view_logic as vl  # noqa: E402


def row(name="P", port="USB001", physical="USB Port 1", connection="\U0001F50C USB",
        driver="Drv", status="Online", online=True, default=False, **extra):
    r = {
        "name": name, "port": port, "physical_port": physical,
        "connection": connection, "driver": driver, "status_text": status,
        "is_online": online, "is_default": default, "type": "Local",
        "shared": "No", "vid_pid": "", "physical_raw": "", "usb_path": "",
    }
    r.update(extra)
    return r


# --- status ---

def test_classify_status():
    assert vl.classify_status({"is_online": True}) == "online"
    assert vl.classify_status({"is_online": False}) == "offline"
    assert vl.classify_status({"is_online": None}) == "virtual"
    assert vl.classify_status({}) == "virtual"


def test_status_badge_text():
    assert vl.status_badge("online") == "\u25cf Online"
    assert vl.status_badge("offline") == "\u25cf Offline"
    assert vl.status_badge("virtual") == "\u2013 Virtual"


# --- connection ---

def test_connection_category():
    assert vl.connection_category(row(connection="\U0001F50C USB")) == "USB"
    assert vl.connection_category(row(connection="\U0001F310 Network (10.0.0.5)")) == "Network"
    assert vl.connection_category(row(connection="\U0001F310 WSD (Network)")) == "Network"
    assert vl.connection_category(row(connection="\u2753 Other")) == "Other"
    assert vl.connection_category(row(connection="\U0001F4C4 File")) == "Other"
    # A network host containing "usb" must not be classed as USB.
    assert vl.connection_category(row(connection="\U0001F310 Network (usb-host)")) == "Network"


# --- sorting ---

def names(rows):
    return [r["name"] for r in rows]


def test_natural_order():
    rows = [row("a", physical="USB Port 10"), row("b", physical="USB Port 2"),
            row("c", physical="usb port 1")]
    out = vl.sort_rows(rows, "physical_port", "asc")
    assert names(out) == ["c", "b", "a"]
    assert names(vl.sort_rows(rows, "physical_port", "desc")) == ["a", "b", "c"]


def test_sort_printer_case_insensitive():
    rows = [row("beta"), row("Alpha"), row("gamma")]
    assert names(vl.sort_rows(rows, "printer", "asc")) == ["Alpha", "beta", "gamma"]


def test_status_order_problems_first():
    rows = [row("v", online=None), row("on", online=True), row("off", online=False)]
    assert names(vl.sort_rows(rows, "status", "asc")) == ["off", "on", "v"]
    assert names(vl.sort_rows(rows, "status", "desc")) == ["v", "on", "off"]


def test_default_sorts_first():
    rows = [row("a"), row("b", default=True)]
    assert names(vl.sort_rows(rows, "default", "asc")) == ["b", "a"]


def test_connection_sort_ignores_emoji():
    rows = [row("n", connection="\U0001F310 Network (x)"), row("u", connection="\U0001F50C USB")]
    assert names(vl.sort_rows(rows, "connection", "asc")) == ["n", "u"]


def test_no_direction_returns_scan_order_copy():
    rows = [row("b"), row("a")]
    out = vl.sort_rows(rows, "printer", None)
    assert names(out) == ["b", "a"]
    assert out is not rows
    assert names(vl.sort_rows(rows, "nope", "asc")) == ["b", "a"]


def test_sort_is_stable_on_ties_both_directions():
    rows = [row("first", driver="X"), row("second", driver="X"), row("third", driver="X")]
    assert names(vl.sort_rows(rows, "driver", "asc")) == ["first", "second", "third"]
    assert names(vl.sort_rows(rows, "driver", "desc")) == ["first", "second", "third"]


def test_next_sort_state_cycle():
    assert vl.next_sort_state(None, "asc", "driver") == ("driver", "asc")
    assert vl.next_sort_state("driver", "asc", "driver") == ("driver", "desc")
    assert vl.next_sort_state("driver", "desc", "driver") == (None, "asc")
    assert vl.next_sort_state("driver", "desc", "printer") == ("printer", "asc")


# --- filtering ---

def sample():
    return [
        row("HP LaserJet", port="USB001", physical="USB Port 2", driver="HP Universal",
            status="Online", online=True),
        row("Canon Net", port="IP_10.0.0.5", physical="10.0.0.5",
            connection="\U0001F310 Network (10.0.0.5)", driver="Canon UFR",
            status="Offline (Unreachable)", online=False),
        row("PDF Writer", port="PORTPROMPT:", physical="Virtual",
            connection="\U0001F4DD Prompt", driver="Microsoft Print To PDF",
            status="N/A (Virtual)", online=None),
    ]


def test_search_each_field():
    rows = sample()
    assert names(vl.filter_rows(rows, "laserjet")) == ["HP LaserJet"]        # name
    assert names(vl.filter_rows(rows, "port 2")) == ["HP LaserJet"]          # physical
    assert names(vl.filter_rows(rows, "IP_10")) == ["Canon Net"]             # windows port
    assert names(vl.filter_rows(rows, "prompt")) == ["PDF Writer"]           # connection
    assert names(vl.filter_rows(rows, "unreachable")) == ["Canon Net"]       # status text
    assert names(vl.filter_rows(rows, "ufr")) == ["Canon Net"]               # driver


def test_search_case_insensitive_and_multiword_and():
    rows = sample()
    assert names(vl.filter_rows(rows, "HP UNIVERSAL")) == ["HP LaserJet"]
    assert vl.filter_rows(rows, "hp canon") == []
    assert len(vl.filter_rows(rows, "   ")) == 3


def test_search_is_plain_text_not_regex():
    rows = sample() + [row("Odd (Printer", port="X")]
    assert names(vl.filter_rows(rows, "(printer")) == ["Odd (Printer"]
    assert len(vl.filter_rows(rows, "(")) == 3  # literal "(" in three status/name fields
    assert vl.filter_rows(rows, "[") == []
    assert vl.filter_rows(rows, ".*") == []


def test_chip_combinations():
    rows = sample()
    assert names(vl.filter_rows(rows, status="offline")) == ["Canon Net"]
    assert names(vl.filter_rows(rows, status="virtual")) == ["PDF Writer"]
    assert names(vl.filter_rows(rows, connection="USB")) == ["HP LaserJet"]
    assert vl.filter_rows(rows, status="offline", connection="USB") == []
    assert names(vl.filter_rows(rows, "canon", "offline", "Network")) == ["Canon Net"]


def test_chip_counts():
    rows = sample()
    c = vl.chip_counts(rows)
    assert c["status"] == {"all": 3, "online": 1, "offline": 1, "virtual": 1}
    assert c["connection"] == {"all": 3, "USB": 1, "Network": 1, "Other": 1}

    # Status counts respect search and the connection chip
    c = vl.chip_counts(rows, query="canon", connection="Network")
    assert c["status"] == {"all": 1, "online": 0, "offline": 1, "virtual": 0}
    # Connection counts respect search and the status chip
    c = vl.chip_counts(rows, status="online")
    assert c["connection"] == {"all": 1, "USB": 1, "Network": 0, "Other": 0}


def test_empty_results():
    assert vl.filter_rows([], "x") == []
    assert vl.filter_rows(sample(), "zzz-no-match") == []
    assert vl.chip_counts([])["status"]["all"] == 0


# --- details ---

def test_detail_fields_usb():
    r = row("HP", vid_pid="VID_03F0&PID_1234", physical_raw="Port_#0002.Hub_#0001",
            usb_path="PCIROOT(0)#PCI(1400)", default=True)
    fields = dict(vl.build_detail_fields(r, {"description": "USB Printing", "monitor": "USBMON"}))
    assert fields["Default"] == "Yes"
    assert fields["Connection"] == "USB"
    assert fields["USB device ID"] == "VID_03F0&PID_1234"
    assert fields["Location"] == "Port_#0002.Hub_#0001"
    assert fields["Port description"] == "USB Printing"
    assert fields["Host address"] == vl.EMPTY


def test_detail_fields_network_and_virtual():
    net = dict(vl.build_detail_fields(sample()[1], {"monitor": "Standard TCP/IP Port"}, host="10.0.0.5"))
    assert net["Host address"] == "10.0.0.5"
    assert net["USB device ID"] == vl.EMPTY
    virt = dict(vl.build_detail_fields(sample()[2]))
    assert virt["USB path"] == vl.EMPTY
    assert virt["Port monitor"] == vl.EMPTY


def test_detail_fields_fixed_set_and_missing_data():
    labels_full = [l for l, _ in vl.build_detail_fields(sample()[0])]
    labels_empty = [l for l, _ in vl.build_detail_fields({})]
    assert labels_full == labels_empty
    assert len(labels_full) == 15
    assert all(v == vl.EMPTY or v in ("No",) for l, v in vl.build_detail_fields({}))
