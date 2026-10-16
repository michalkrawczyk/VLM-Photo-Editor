from __future__ import annotations

import os
import time

import pytest

from vlm_photo_editor.app import tmp_layout


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "vlm_photo_editor"
    r.mkdir()
    monkeypatch.setattr(tmp_layout, "_ROOT", r)
    return r


def test_sweep_stale_removes_only_old_dirs(root):
    fresh = root / "recent_abc123"
    stale = root / "old_def456"
    fresh.mkdir()
    stale.mkdir()
    (stale / "original.jpg").write_bytes(b"x")

    old = time.time() - 48 * 3600
    os.utime(stale, (old, old))

    tmp_layout.sweep_stale()

    assert fresh.exists()
    assert not stale.exists()


def test_sweep_stale_noop_when_root_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(tmp_layout, "_ROOT", tmp_path / "does_not_exist")
    tmp_layout.sweep_stale()  # must not raise


def test_sweep_stale_respects_custom_age(root):
    d = root / "img_xyz"
    d.mkdir()
    stamp = time.time() - 120
    os.utime(d, (stamp, stamp))

    tmp_layout.sweep_stale(max_age_seconds=60)
    assert not d.exists()
