import os
import shutil
from pathlib import Path

import pytest

from review import legacy_convert
from review.legacy_convert import convert_legacy_to_modern


def test_non_legacy_returns_none(tmp_path):
    assert convert_legacy_to_modern(tmp_path / "modern.xlsx") is None


def test_disabled_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBREOFFICE_CONVERT_TIMEOUT", "0")
    assert convert_legacy_to_modern(tmp_path / "old.xls") is None


def test_soffice_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert convert_legacy_to_modern(tmp_path / "old.xls") is None


def test_subprocess_timeout_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/soffice")
    import subprocess as sp
    def _fake_run(*args, **kwargs):
        raise sp.TimeoutExpired(cmd="soffice", timeout=30)
    monkeypatch.setattr(sp, "run", _fake_run)
    assert convert_legacy_to_modern(tmp_path / "old.xls") is None


def test_nonzero_returncode_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/soffice")
    class _R:
        returncode = 1
        stderr = "boom"
    import subprocess as sp
    monkeypatch.setattr(sp, "run", lambda *a, **k: _R())
    assert convert_legacy_to_modern(tmp_path / "old.xls") is None