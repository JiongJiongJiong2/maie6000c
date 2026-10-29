from __future__ import annotations

import io
import os
import time
from uuid import uuid4

import httpx
import pytest
from PIL import Image

pytestmark = pytest.mark.smoke


def test_smoke_search_submission_and_terminal_state():
    base_url = os.getenv("SMOKE_BASE_URL")
    if not base_url:
        pytest.skip("SMOKE_BASE_URL not set")
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(output, "PNG")
    token = os.getenv("DEVICE_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=base_url, headers=headers, timeout=10) as client:
        key = str(uuid4())
        arguments = {
            "data": {"client_submission_key": key},
            "files": {"image": ("crop.png", output.getvalue(), "image/png")},
        }
        first = client.post("/search-requests", **arguments)
        assert first.status_code == 202
        replay = client.post("/search-requests", **arguments)
        assert replay.json()["job_id"] == first.json()["job_id"]
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            response = client.get(f"/search-requests/{first.json()['request_id']}")
            assert response.status_code == 200
            state = response.json()
            if state["status"] in {"completed", "failed"}:
                break
            time.sleep(0.5)
        else:
            pytest.fail("Search worker did not persist a terminal state")
        if state["status"] == "failed":
            expected = os.getenv("SMOKE_EXPECTED_SEARCH_ERROR")
            assert expected, f"Unexpected search failure: {state['error']}"
            assert state["error"]["code"] == expected
            assert state["result_kind"] is None
        else:
            assert state["error"] is None
            assert state["result_kind"] in {"candidates", "no_candidates"}
            assert len(state["candidates"]) <= 3
            for candidate in state["candidates"]:
                media = client.get(candidate["media_url"])
                assert media.status_code == 200
                with Image.open(io.BytesIO(media.content)) as gif:
                    assert gif.format == "GIF"
                    assert getattr(gif, "n_frames", 1) > 1
