"""Controlled subprocess timeout; subprocess.run is not mocked."""

import os
import sys
import time

import pytest

from services.common.config import get_settings
from services.worker.app import search_worker


@pytest.mark.skipif(os.name != "posix", reason="POSIX controlled sleep process")
def test_parent_actually_kills_slow_runner(tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    wrapper = tmp_path / "slow-runner"
    wrapper.write_text(f'#!/bin/sh\nprintf "%s" "$$" > "{pidfile}"\nexec /bin/sleep 30\n')
    wrapper.chmod(0o700)
    monkeypatch.setattr(sys, "executable", str(wrapper))
    monkeypatch.setattr(get_settings(), "web_search_timeout_seconds", 0.1)
    started = time.monotonic()
    with pytest.raises(search_worker.RetrievalError) as exc:
        search_worker.invoke_web_search(
            tmp_path / "input.png", "slow controlled boundary", tmp_path
        )
    assert exc.value.code == "web_search_timeout"
    assert 4 < time.monotonic() - started < 15
    pid = int(pidfile.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
