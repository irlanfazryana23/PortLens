import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import settings_store as ss  # noqa: E402


def test_round_trip(tmp_path):
    path = str(tmp_path / "sub" / "settings.json")
    data = {"sort_column": "driver", "sort_direction": "desc",
            "status_filter": "offline", "connection_filter": "USB"}
    assert ss.save_settings(data, path) is True
    assert ss.load_settings(path) == data
    assert not os.path.exists(path + ".tmp")


def test_missing_file_gives_defaults(tmp_path):
    assert ss.load_settings(str(tmp_path / "nope.json")) == ss.DEFAULTS


def test_corrupt_json_gives_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{not json", encoding="utf-8")
    assert ss.load_settings(str(p)) == ss.DEFAULTS


def test_non_dict_json_gives_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert ss.load_settings(str(p)) == ss.DEFAULTS


def test_invalid_values_replaced_individually(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "sort_column": "bogus", "sort_direction": "desc",
        "status_filter": "offline", "connection_filter": "Fax", "extra": 1,
    }), encoding="utf-8")
    loaded = ss.load_settings(str(p))
    assert loaded["sort_column"] is None
    assert loaded["sort_direction"] == "asc"      # reset with the column
    assert loaded["status_filter"] == "offline"   # valid value kept
    assert loaded["connection_filter"] == "all"
    assert "extra" not in loaded


def test_no_appdata(monkeypatch):
    monkeypatch.delenv("APPDATA", raising=False)
    assert ss.default_path() is None
    assert ss.load_settings() == ss.DEFAULTS
    assert ss.save_settings(dict(ss.DEFAULTS)) is False


def test_unwritable_location_returns_false(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    # Parent "directory" is actually a file, so makedirs/open must fail.
    assert ss.save_settings(dict(ss.DEFAULTS), str(blocker / "settings.json")) is False


def test_default_path_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert ss.default_path() == os.path.join(str(tmp_path), "PortLens", "settings.json")
    assert ss.save_settings({"sort_column": "printer", "sort_direction": "asc"}) is True
    assert ss.load_settings()["sort_column"] == "printer"


def test_old_settings_folder_is_used_until_new_file_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    old_dir = tmp_path / "PrinterPortDetector"
    old_dir.mkdir()
    (old_dir / "settings.json").write_text(
        json.dumps({"sort_column": "driver", "sort_direction": "desc",
                    "status_filter": "offline"}), encoding="utf-8")

    loaded = ss.load_settings()
    assert loaded["sort_column"] == "driver" and loaded["status_filter"] == "offline"

    # Saving writes to the new folder, which then takes priority.
    assert ss.save_settings(dict(loaded, status_filter="online")) is True
    assert (tmp_path / "PortLens" / "settings.json").exists()
    assert ss.load_settings()["status_filter"] == "online"
    # the old file is left alone
    assert json.loads((old_dir / "settings.json").read_text(encoding="utf-8"))["status_filter"] == "offline"