from __future__ import annotations

from pathlib import Path

import pytest

from services.common.storage import atomic_write


def test_atomic_write_preserves_replace_error_when_temp_cleanup_fails(tmp_path, monkeypatch):
    original_unlink = Path.unlink
    cleanup_errors = []

    def fail_replace(_path, _target):
        del _path, _target
        raise OSError("original replace failure")

    def fail_temp_cleanup(path, *args, **kwargs):
        if path.suffix == ".tmp":
            raise PermissionError("temporary cleanup failure")
        return original_unlink(path, *args, **kwargs)

    def log_cleanup_failure(message, **fields):
        cleanup_errors.append((message, fields))

    monkeypatch.setattr("services.common.storage.logger.exception", log_cleanup_failure)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_replace)
        patch.setattr(Path, "unlink", fail_temp_cleanup)
        with pytest.raises(OSError, match="original replace failure"):
            atomic_write(tmp_path, "inputs/test.image", b"test")

    assert len(cleanup_errors) == 1
    assert cleanup_errors[0][0] == "stored_file_cleanup_failed"
    assert cleanup_errors[0][1]["extra"]["storage_class"] == "temporary"
    assert cleanup_errors[0][1]["extra"]["file_name"].endswith(".tmp")
    temporary_files = list((tmp_path / "inputs").glob("*.tmp"))
    assert len(temporary_files) == 1
    assert temporary_files[0].read_bytes() == b"test"
    original_unlink(temporary_files[0])


def test_atomic_write_replaces_target_without_leaving_temp_files(tmp_path):
    target = atomic_write(tmp_path, "inputs/test.image", b"first")
    assert target.read_bytes() == b"first"
    target = atomic_write(tmp_path, "inputs/test.image", b"second")
    assert target.read_bytes() == b"second"
    assert list(target.parent.glob("*.tmp")) == []


def test_hashed_media_temporary_path_fits_when_original_fits(tmp_path, monkeypatch):
    media_name = "a" * 64 + ".gif"
    original_open = Path.open

    def open_with_limited_path(path, *args, **kwargs):
        if len(path.name) > len(media_name):
            raise FileNotFoundError("Temporary name exceeded the original path budget")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_with_limited_path)
    target = atomic_write(tmp_path, f"originals/{media_name}", b"original")
    assert target.read_bytes() == b"original"
