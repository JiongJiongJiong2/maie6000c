"""JSONL-only runner; model/library logs go to stderr, never the protocol."""

import contextlib
import json
import sys
from pathlib import Path

from services.search_agent.meme_types import MemeSettings, RunnerEvent


def main():
    payload = json.load(sys.stdin)
    stream = sys.stdout
    seq = 0
    final = False

    def emit(kind, data):
        nonlocal seq, final
        if final:
            raise ValueError("Event after final")
        seq += 1
        event = RunnerEvent(seq=seq, type=kind, payload=data)
        line = event.model_dump_json()
        if len(line.encode()) > 256 * 1024:
            raise ValueError("Event limit")
        stream.write(line + "\n")
        stream.flush()
        final = kind == "final"

    with contextlib.redirect_stdout(sys.stderr):
        try:
            from services.search_agent.meme_pipeline import search_memes

            search_memes(
                Path(payload["image_path"]),
                payload.get("description") or "",
                Path(payload["work_dir"]),
                payload["target_count"],
                settings=MemeSettings(**payload.get("settings", {})),
                emit=emit,
            )
        except Exception:
            if not final:
                emit("error", {"code": "meme_pipeline_failed"})
                emit(
                    "final",
                    {
                        "status": "failed",
                        "stop_reason": "meme_pipeline_failed",
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
