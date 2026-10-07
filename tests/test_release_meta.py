import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import app_info  # noqa: E402
import make_version_info as mvi  # noqa: E402


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def test_version_file_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", read("VERSION").strip())


def test_get_version_reads_version_file():
    assert app_info.get_version() == read("VERSION").strip()


def test_get_version_falls_back_to_dev(monkeypatch):
    monkeypatch.setattr(app_info, "resource_path", lambda name: os.path.join(ROOT, "no-such-file"))
    assert app_info.get_version() == "dev"


def test_get_version_rejects_malformed(monkeypatch, tmp_path):
    bad = tmp_path / "VERSION"
    bad.write_text("v1.0", encoding="utf-8")
    monkeypatch.setattr(app_info, "resource_path", lambda name: str(bad))
    assert app_info.get_version() == "dev"


def test_resource_path_finds_assets_and_version():
    for name in ("portlens.ico", "portlens_logo.png", "VERSION"):
        assert os.path.exists(app_info.resource_path(name)), name


def test_resource_path_uses_bundle_root_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", r"C:\bundle", raising=False)
    assert app_info.resource_path("portlens.ico") == os.path.join(r"C:\bundle", "portlens.ico")


def test_version_tuple():
    assert mvi.version_tuple("1.2.3") == (1, 2, 3, 0)
    for bad in ("1.2", "1.2.3.4", "v1.2.3", "", None, "1.2.x"):
        with pytest.raises(ValueError):
            mvi.version_tuple(bad)


def test_version_info_renders_a_valid_pyinstaller_resource():
    text = mvi.render("2.5.1", "PortLens-2.5.1.exe")
    assert "filevers=(2, 5, 1, 0)" in text
    assert "StringStruct('FileVersion', '2.5.1.0')" in text
    assert "StringStruct('OriginalFilename', 'PortLens-2.5.1.exe')" in text
    # It must evaluate with PyInstaller's own classes (what the spec hands over).
    versioninfo = pytest.importorskip("PyInstaller.utils.win32.versioninfo")
    namespace = {name: getattr(versioninfo, name) for name in (
        "VSVersionInfo", "FixedFileInfo", "StringFileInfo", "StringTable",
        "StringStruct", "VarFileInfo", "VarStruct")}
    assert eval(text, namespace) is not None


def test_changelog_has_an_entry_for_the_current_version():
    version = read("VERSION").strip()
    headings = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", read("CHANGELOG.md"), re.MULTILINE)
    assert version in headings, f"CHANGELOG.md needs a '## [{version}] - date' section"
    assert headings[0] == version, "the newest changelog entry must match VERSION"


def test_spec_uses_version_and_bundles_assets():
    spec = read("PortLens.spec")
    assert "VERSION" in spec and "portlens.ico" in spec and "portlens_logo.png" in spec
