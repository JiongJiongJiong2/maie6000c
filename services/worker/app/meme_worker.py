"""Validate bounded JSONL events, publish verified drafts, commit immutable results."""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from datetime import timedelta, timezone
from pathlib import Path
from uuid import uuid4

from services.common.config import get_settings
from services.common.db import get_session_factory
from services.common.media import inspect_media, safe_file
from services.common.models import utcnow
from services.common.search_models import (
    Candidate,
    MemeCandidateDraft,
    MemeProgressEvent,
    SearchExecution,
    SearchJob,
    SearchRequest,
)
from services.common.storage import atomic_write, contained_path, sha256
from services.search_agent.meme_types import MemeSettings, PreparedMedia, RunnerEvent

STAGES = {
    "preprocessing",
    "understanding",
    "verifying",
    "recalling",
    "fetching",
    "reranking",
    "finalizing",
}


class ProtocolError(ValueError):
    pass


def stop_process(process):
    if process.poll() is None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
    process.wait()


def stream_events(payload, timeout):
    process = subprocess.Popen(
        [sys.executable, "-m", "services.worker.app.meme_search_runner"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name == "posix",
    )
    messages = queue.Queue(maxsize=16)
    stopped = threading.Event()

    def read():
        try:
            while True:
                line = process.stdout.readline(256 * 1024 + 1)
                while not stopped.is_set():
                    try:
                        messages.put(line, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                if stopped.is_set():
                    break
                if not line or len(line) > 256 * 1024:
                    break
        finally:
            process.stdout.close()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    total = 0
    try:
        process.stdin.write(json.dumps(payload).encode())
        process.stdin.close()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProtocolError("meme_search_timeout")
            try:
                line = messages.get(timeout=remaining)
            except queue.Empty:
                raise ProtocolError("meme_search_timeout") from None
            if not line:
                break
            total += len(line)
            if len(line) > 256 * 1024 or total > 4 * 1024 * 1024:
                raise ProtocolError("runner_output_limit")
            try:
                yield RunnerEvent.model_validate_json(line)
            except ValueError:
                raise ProtocolError("invalid_meme_event") from None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProtocolError("meme_search_timeout")
        try:
            code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise ProtocolError("meme_search_timeout") from None
        if code:
            raise ProtocolError("meme_runner_exit")
    finally:
        stopped.set()
        stop_process(process)
        reader.join(timeout=1)


def publish_event(db, job_id, event, work):
    job = db.get(SearchJob, job_id)
    if not job or job.status != "running":
        raise ProtocolError("job_not_running")
    data = event.payload
    if event.type == "stage":
        if data.get("stage") not in STAGES:
            raise ProtocolError("invalid_stage")
        job.stage = data["stage"]
    elif event.type == "analysis_ready":
        from services.search_agent.meme_types import VisualAnalysis

        job.analysis = VisualAnalysis.model_validate(data["analysis"]).model_dump(mode="json")
    elif event.type == "progress":
        count = data.get("verified_count")
        if type(count) is not int or not 0 <= count <= 120:
            raise ProtocolError("invalid_progress")
        job.progress = data
    elif event.type == "candidate_ready":
        prepared = PreparedMedia.model_validate(data["candidate"]).validate_paths()
        source = safe_file(work, prepared.relative_path)
        content = source.read_bytes()
        metadata = inspect_media(content)
        if metadata != prepared.metadata:
            raise ProtocolError("candidate_metadata_mismatch")
        preview = safe_file(work, prepared.preview_relative_path).read_bytes()
        pm = inspect_media(preview)
        if pm.format != "PNG" or pm.frame_count != 1 or max(pm.width, pm.height) > 384:
            raise ProtocolError("invalid_preview")
        root = get_settings().media_root
        relative = f"meme50-drafts/{job_id}/{prepared.key}.{metadata.suffix}"
        poster = f"meme50-drafts/{job_id}/{prepared.key}.preview.png"
        from sqlalchemy import select

        drafts = list(
            db.scalars(select(MemeCandidateDraft).where(MemeCandidateDraft.job_id == job_id))
        )
        if any(d.draft_key == prepared.key for d in drafts):
            raise ProtocolError("duplicate_draft_key")
        if len(drafts) >= 120:
            raise ProtocolError("draft_count_limit")
        reserved = sum(
            d.data["metadata"]["byte_size"] + contained_path(root, d.preview_path).stat().st_size
            for d in drafts
        )
        if 3 * (reserved + len(content) + len(preview)) > job.configuration.get(
            "max_disk_bytes", 512 * 1024 * 1024
        ):
            raise ProtocolError("draft_disk_limit")
        atomic_write(root, relative, content)
        atomic_write(root, poster, preview)
        db.add(
            MemeCandidateDraft(
                job_id=job_id,
                draft_key=prepared.key,
                local_path=relative,
                preview_path=poster,
                data=prepared.model_dump(mode="json"),
                expires_at=utcnow() + timedelta(days=1),
            )
        )
    db.add(MemeProgressEvent(job_id=job_id, seq=event.seq, event_type=event.type, data=data))
    db.commit()


def finalize(db, job_id, payload):
    from sqlalchemy import select

    job = db.get(SearchJob, job_id)
    if job.status != "running":
        raise ProtocolError("job_not_running")
    keys = payload.get("candidate_keys")
    if (
        not isinstance(keys, list)
        or len(keys) > min(50, job.target_count)
        or len(set(keys)) != len(keys)
    ):
        raise ProtocolError("invalid_final_candidates")
    rows = {
        d.draft_key: d
        for d in db.scalars(select(MemeCandidateDraft).where(MemeCandidateDraft.job_id == job_id))
    }
    if any(k not in rows for k in keys):
        raise ProtocolError("unknown_final_draft")
    items = [PreparedMedia.model_validate(rows[k].data).validate_paths() for k in keys]
    if len({x.content_group_id for x in items}) != len(items):
        raise ProtocolError("duplicate_content_group")
    if [x.score for x in items] != sorted([x.score for x in items], reverse=True):
        raise ProtocolError("unsorted_final")
    status = payload.get("status")
    if status not in {"completed", "failed"} or (status == "failed" and items):
        raise ProtocolError("invalid_final_status")
    if status == "completed" and job.analysis is None:
        raise ProtocolError("analysis_missing")
    ledger = payload.get("ledger", {})
    limits = {
        "search_calls": 16,
        "model_calls": 3,
        "queries": 6,
        "media_attempts": 120,
        "page_attempts": 40,
        "preview_attempts": 250,
        "response_bytes": 512 * 1024 * 1024,
        "redirects": 120,
        "disk_bytes": 512 * 1024 * 1024,
    }
    if any(
        type(ledger.get(k, 0)) is not int or not 0 <= ledger.get(k, 0) <= v
        for k, v in limits.items()
    ):
        raise ProtocolError("invalid_final_budget")
    root = get_settings().media_root
    revision = uuid4().hex
    written = []
    try:
        for rank, item in enumerate(items, 1):
            draft = rows[item.key]
            content = contained_path(root, draft.local_path).read_bytes()
            if inspect_media(content) != item.metadata:
                raise ProtocolError("draft_corrupted")
            candidate_id = str(uuid4())
            relative = f"candidates/{job_id}/{candidate_id}.{item.metadata.suffix}"
            poster = f"candidates/{job_id}/{candidate_id}.preview.png"
            written.append(atomic_write(root, relative, content))
            written.append(
                atomic_write(root, poster, contained_path(root, draft.preview_path).read_bytes())
            )
            m = item.metadata
            db.add(
                Candidate(
                    id=candidate_id,
                    job_id=job_id,
                    rank=rank,
                    similarity_score=item.score,
                    media_sha256=m.sha256,
                    source_url=item.source_url,
                    image_url=item.media_url,
                    provider=item.provider,
                    local_cache_path=relative,
                    preview_path=poster,
                    frame_count=m.frame_count,
                    media_format=m.format,
                    mime_type=m.mime_type,
                    media_kind=m.media_kind,
                    width=m.width,
                    height=m.height,
                    byte_size=m.byte_size,
                    duration_ms=m.duration_ms,
                    content_group_id=item.content_group_id,
                    cache_expires_at=utcnow() + timedelta(days=get_settings().media_retention_days),
                )
            )
        job.status = status
        job.stage = "completed" if status == "completed" else "failed"
        job.result_kind = (
            ("candidates" if items else "no_candidates") if status == "completed" else None
        )
        job.result_count = len(items)
        job.result_revision = revision if status == "completed" else None
        job.partial = bool(payload.get("partial"))
        job.progress = {
            "verified_count": len(items),
            "ledger": ledger,
            "counts": payload.get("counts", {}),
        }
        job.finished_at = utcnow()
        if status == "failed":
            job.error_code = str(payload.get("stop_reason", "meme_search_failed"))[:50]
            job.error_detail = "图片检索服务暂不可用，请稍后重试。"
        db.add(
            SearchExecution(
                job_id=job_id,
                agent_version="meme50-v2",
                model_version=payload.get("model_version"),
                stop_reason=str(payload.get("stop_reason", "unknown"))[:100],
                search_calls=ledger.get("search_calls", 0),
                planner_calls=ledger.get("model_calls", 0),
                downloads_used=ledger.get("media_attempts", 0),
                duration_ms=int(
                    (job.finished_at - job.started_at.replace(tzinfo=timezone.utc)).total_seconds()
                    * 1000
                ),
                trace=payload.get("trace", []),
                warnings=payload.get("warnings", []),
            )
        )
        db.commit()
    except BaseException:
        db.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        raise


def process_meme_job(job_id, *, factory=None, event_stream=None):
    factory = factory or get_session_factory()
    settings = get_settings()
    config = MemeSettings()
    public_config = config.model_dump(
        exclude={
            "gemini_api_key",
            "hkust_api_key",
            "deepseek_api_key",
            "google_vision_api_key",
            "brave_api_key",
        }
    )
    with factory() as db:
        job = db.get(SearchJob, job_id)
        request = db.get(SearchRequest, job.request_id)
        if job.status != "running" or job.search_profile != "meme50-v2":
            raise ProtocolError("invalid_meme_job")
        job.configuration = {**job.configuration, **public_config}
        db.commit()
        path = contained_path(settings.media_root, request.input_path)
        if sha256(path.read_bytes()) != request.input_sha256:
            raise ProtocolError("input_corrupted")
        payload = dict(
            image_path=str(path.resolve()),
            description=job.description or "",
            work_dir=str((settings.media_root / "web-search" / job_id).resolve()),
            target_count=job.target_count,
            settings=public_config,
        )
    work = Path(payload["work_dir"])
    work.mkdir(parents=True, exist_ok=True)
    final = None
    seq = 0
    analysis = False
    try:
        stream = (
            event_stream(payload, config.timeout_seconds + 10)
            if event_stream
            else stream_events(payload, config.timeout_seconds + 10)
        )
        for event in stream:
            if final is not None or event.seq != seq + 1:
                raise ProtocolError("invalid_event_order")
            seq = event.seq
            if event.type == "candidate_ready" and not analysis:
                raise ProtocolError("candidate_before_analysis")
            if event.type == "analysis_ready":
                analysis = True
            if event.type == "final":
                final = event.payload
            with factory() as db:
                publish_event(db, job_id, event, work)
        if final is None:
            raise ProtocolError("runner_missing_final")
        with factory() as db:
            finalize(db, job_id, final)
    except (ProtocolError, ValueError, OSError) as exc:
        from .search_worker import fail_job

        code = str(exc) if isinstance(exc, ProtocolError) else "invalid_meme_output"
        with factory() as db:
            fail_job(db, job_id, code[:50], "图片检索中断或结果未通过验证，请重试。")
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
