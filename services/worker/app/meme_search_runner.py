"""JSONL-only runner; model/library logs go to stderr, never the protocol."""

import contextlib
import json
import sys
from pathlib import Path
from threading import Lock

from services.search_agent.meme_types import (
    MemeSettings,
    PipelineError,
    RunnerEvent,
    VisualAnalysis,
)

EVENT_BYTES = 256 * 1024


class EventWriter:
    def __init__(self, stream):
        self.stream = stream
        self.seq = 0
        self.final = False
        self.lock = Lock()

    def emit(self, kind, data):
        with self.lock:
            if self.final:
                raise ValueError("Event after final")
            event = RunnerEvent(seq=self.seq + 1, type=kind, payload=data)
            line = event.model_dump_json().encode("utf-8") + b"\n"
            if len(line) > EVENT_BYTES:
                raise PipelineError("runner_event_too_large")
            self.stream.write(line)
            self.stream.flush()
            self.seq = event.seq
            self.final = kind == "final"


def main():
    payload = json.load(sys.stdin.buffer)
    writer = EventWriter(sys.stdout.buffer)

    with contextlib.redirect_stdout(sys.stderr):
        try:
            from services.search_agent.meme_pipeline import search_memes

            settings = MemeSettings.for_online_search(**payload.get("settings", {}))
            description = payload.get("description") or ""
            saved = (
                VisualAnalysis.model_validate(payload["saved_analysis"])
                if "saved_analysis" in payload
                else None
            )
            search_memes(
                Path(payload["image_path"]),
                description,
                Path(payload["work_dir"]),
                payload["target_count"],
                settings=settings,
                saved_analysis=saved
                if saved and saved.can_reuse_for_online_search(settings, description)
                else None,
                emit=writer.emit,
            )
        except Exception as exc:
            if not writer.final:
                code = exc.code if isinstance(exc, PipelineError) else "meme_pipeline_failed"
                writer.emit("error", {"code": code})
                writer.emit(
                    "final",
                    {
                        "status": "failed",
                        "stop_reason": code,
                        "candidate_keys": [],
                        "warnings": [],
                        "ledger": {},
                        "trace": [],
                        "counts": {},
                        "partial": False,
                        "model_version": None,
                        "scoring_version": "unavailable",
                    },
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
