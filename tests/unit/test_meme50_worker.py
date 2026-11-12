import os
import subprocess
import sys
import time

import httpx
import pytest

from services.retrieval.public_fetch import FetchError, request_public
from services.worker.app.meme_worker import ProtocolError, stream_events


def test_redirect_to_private_is_rejected_before_second_request(monkeypatch):
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    monkeypatch.setattr(
        "services.retrieval.public_fetch.PublicTransport", lambda *a: httpx.MockTransport(handle)
    )
    with pytest.raises(FetchError, match="url_policy") as error:
        request_public("https://new-public.example.org/image", 10000, 5)
    assert len(seen) == 1 and error.value.stats["redirects"] == 1


def test_runner_real_hard_timeout_reaps_process_group(monkeypatch, tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX process-group assertion")
    real_popen = subprocess.Popen
    processes = []
    pid_file = tmp_path / "child.pid"
    code = (
        "import os,time,pathlib; "
        "child=os.fork(); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child)) if child else None; "
        "time.sleep(60)"
    )

    def launch(*args, **kwargs):
        process = real_popen([sys.executable, "-c", code], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("services.worker.app.meme_worker.subprocess.Popen", launch)
    started = time.monotonic()
    with pytest.raises(ProtocolError, match="meme_search_timeout"):
        list(stream_events({"anything": "bounded-input"}, 0.3))
    assert time.monotonic() - started < 3
    assert processes[0].poll() is not None
    child = int(pid_file.read_text())
    monkeypatch.setattr("services.worker.app.meme_worker.subprocess.Popen", real_popen)
    # No running descendant survives the group kill (a reparented zombie may
    # briefly remain until init reaps it).
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True)
    assert not result.stdout.strip() or result.stdout.strip().startswith("Z")
