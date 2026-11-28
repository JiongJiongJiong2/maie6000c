import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.search_agent import meme_pipeline
from services.search_agent.meme_types import PipelineError, RunnerEvent
from services.worker.app import meme_search_runner as runner


def read_events(data):
    return [RunnerEvent.model_validate_json(line) for line in data.splitlines()]


def test_runner_uses_utf8_on_pipes_even_with_legacy_strict_stdout(monkeypatch):
    raw_input = io.BytesIO(
        json.dumps(
            {
                "image_path": "demo.png",
                "work_dir": "work",
                "description": "测试🍀",
                "target_count": 3,
            },
            ensure_ascii=False,
        ).encode("utf-8")
    )
    raw_output = io.BytesIO()
    stdin = io.TextIOWrapper(raw_input, encoding="ascii", errors="strict")
    stdout = io.TextIOWrapper(raw_output, encoding="ascii", errors="strict")
    monkeypatch.setattr(runner.sys, "stdin", stdin)
    monkeypatch.setattr(runner.sys, "stdout", stdout)

    def search(path, description, *args, emit, **kwargs):
        assert description == "测试🍀"
        emit("stage", {"stage": "verifying"})
        emit("analysis_ready", {"analysis": {"observations": ["哈吉米接电话🤳"]}})
        emit("final", {"status": "completed"})

    monkeypatch.setattr(meme_pipeline, "search_memes", search)
    assert runner.main() == 0
    records = read_events(raw_output.getvalue())
    assert [r.seq for r in records] == [1, 2, 3]
    assert records[1].payload["analysis"]["observations"] == ["哈吉米接电话🤳"]
    assert records[2].payload["status"] == "completed"


def test_rejected_event_leaves_next_sequence_available_and_final_is_terminal():
    stream = io.BytesIO()
    writer = runner.EventWriter(stream)
    overhead = len(RunnerEvent(seq=1, type="error", payload={"note": ""}).model_dump_json()) + 1
    payload_size = runner.EVENT_BYTES - overhead
    writer.emit("error", {"note": "x" * payload_size})
    assert len(stream.getvalue()) == runner.EVENT_BYTES
    with pytest.raises(PipelineError, match="runner_event_too_large"):
        writer.emit("final", {"note": "x" * (payload_size + 1)})
    with pytest.raises(ValueError):
        writer.emit("invalid", {})
    writer.emit("final", {"status": "failed", "stop_reason": "runner_event_too_large"})
    assert [(e.seq, e.type) for e in read_events(stream.getvalue())] == [(1, "error"), (2, "final")]
    with pytest.raises(ValueError, match="after final"):
        writer.emit("progress", {})


def test_concurrent_writes_are_complete_and_have_gapless_wire_sequence():
    stream = io.BytesIO()
    writer = runner.EventWriter(stream)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda index: writer.emit("progress", {"index": index}), range(100)))
    writer.emit("final", {"status": "completed"})
    records = read_events(stream.getvalue())
    assert [r.seq for r in records] == list(range(1, 102))
    assert {r.payload["index"] for r in records[:-1]} == set(range(100))


def test_oversize_final_trace_returns_a_bounded_failed_final(monkeypatch):
    request = b'{"image_path":"demo.png","work_dir":"work","target_count":3}'
    output = io.BytesIO()
    monkeypatch.setattr(runner.sys, "stdin", io.TextIOWrapper(io.BytesIO(request)))
    monkeypatch.setattr(runner.sys, "stdout", io.TextIOWrapper(output))

    def search(*args, emit, **kwargs):
        emit("stage", {"stage": "finalizing"})
        emit("final", {"status": "completed", "trace": ["x" * runner.EVENT_BYTES]})

    monkeypatch.setattr(meme_pipeline, "search_memes", search)
    assert runner.main() == 0
    events = read_events(output.getvalue())
    assert [(e.seq, e.type) for e in events] == [(1, "stage"), (2, "error"), (3, "final")]
    assert events[-1].payload["status"] == "failed"
    assert events[-1].payload["stop_reason"] == "runner_event_too_large"
