"""Strict, append-only meme50 evidence: probe, run-suite, review, score, finalize.

No labels or member attestations are invented. Exit 0 passed, 1 measured failure,
2 pending authorization/human evidence, 3 invalid evidence or execution error.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import math
import json
import os
import re
import shutil
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import numpy as np

from services.common.media import inspect_media, png_bytes, representative_frames
from services.search_agent.meme_deepseek import DeepSeekQueryPlanner, DeepSeekWeb
from services.search_agent.meme_types import Ledger, MemeSettings, PipelineError
from services.search_agent.visual_analysis import analyze_image
from scripts import verify_meme50

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"clearly_related", "partially_related", "unrelated", "unreviewed"}
BINDING = ("case_id", "job_id", "revision", "candidate_id", "rank", "sha256")
LABEL_FIELDS = [
    *BINDING,
    "relevance",
    "duplicate_group",
    "duplicate_status",
    "media_valid",
    "low_quality",
    "notes",
    "reviewer",
]
PUBLIC_FIELDS = (
    "provider_policy",
    "deepseek_model",
    "reverse_image_provider",
    "vision_provider",
    "hkust_model",
    "vision_model",
    "keyword_provider",
    "verify_entities",
    "target_count",
    "timeout_seconds",
    "call_timeout_seconds",
    "max_search_calls",
    "max_model_calls",
    "max_queries",
    "max_sources",
    "max_previews",
    "max_originals",
    "max_pages",
    "max_bytes",
    "max_redirects",
    "max_disk_bytes",
    "concurrency",
    "dns_mode",
    "minimum_score",
    "scoring_version",
    "dedup_version",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def public_configuration(settings=None):
    s = settings or MemeSettings()
    return {name: getattr(s, name) for name in PUBLIC_FIELDS}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def new_directory(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir(exist_ok=False)
    return path


def snapshot(out):
    files = []
    for directory in ["services", "scripts", "web", "alembic", "tests", ".github"]:
        for path in (ROOT / directory).rglob("*"):
            if any(
                p in {"node_modules", "__pycache__", "test-results", "playwright-report"}
                for p in path.parts
            ):
                continue
            if (
                path.is_file()
                and not path.is_symlink()
                and path.suffix in {".py", ".js", ".mjs", ".html", ".css", ".json", ".yaml", ".yml"}
            ):
                files.append(path)
    files += [
        ROOT / name
        for name in ["pyproject.toml", "Dockerfile", "compose.yaml", "alembic.ini"]
        if (ROOT / name).is_file()
    ]
    records = [
        {
            "path": p.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(files)
    ]
    with tarfile.open(out / "code.tar.gz", "w:gz") as archive:
        for p in sorted(files):
            archive.add(p, arcname=p.relative_to(ROOT).as_posix(), recursive=False)
    runtime_files = {
        "pyproject.toml",
        "alembic.ini",
        "web/index.html",
        "web/styles.css",
        "web/app.js",
        "web/api.js",
        "web/store.js",
        "web/meme50.js",
    }
    runtime_records = [
        r
        for r in records
        if r["path"].startswith(("services/", "scripts/", "alembic/")) or r["path"] in runtime_files
    ]
    value = dict(
        code_fingerprint=digest(runtime_records),
        source_snapshot_fingerprint=digest(records),
        files=records,
        configuration=public_configuration(),
        configuration_fingerprint=digest(public_configuration()),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    write_json(out / "snapshot.json", value)
    return value


def load_manifest(path, split=None):
    manifest = json.loads(Path(path).read_text())
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases or not manifest.get("version"):
        raise ValueError("manifest requires a version and cases")
    ids = [c["case_id"] for c in cases]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", x) for x in ids):
        raise ValueError("duplicate or unsafe case ID")
    families = {
        s: {c["family"] for c in cases if c["split"] == s} for s in ["development", "heldout"]
    }
    if families["development"] & families["heldout"]:
        raise ValueError("development/heldout family leakage")
    selected = [c for c in cases if not split or c["split"] == split]
    if not selected:
        raise ValueError("empty split")
    return manifest, selected


def input_bytes(case):
    path = Path(case["input_path"])
    if not path.is_absolute():
        path = ROOT / path
    data = path.read_bytes()
    metadata = inspect_media(data)
    if (
        metadata.sha256 != case["sha256"]
        or metadata.format != case["format"]
        or metadata.media_kind != case["media_kind"]
    ):
        raise ValueError("frozen input SHA/format mismatch")
    return data, metadata


def probe(args):
    out = new_directory(args.out)
    frozen = snapshot(out)
    data = args.image.read_bytes()
    metadata = inspect_media(data)
    frames, records = representative_frames(data, count=4)
    for i, frame in enumerate(frames):
        (out / f"frame-{i:02}.png").write_bytes(png_bytes(frame))
    settings = MemeSettings()
    ledger = Ledger(settings)
    report = dict(
        kind="provider_probe",
        input_sha256=metadata.sha256,
        sampled_frames=records,
        configuration_fingerprint=frozen["configuration_fingerprint"],
        code_fingerprint=frozen["code_fingerprint"],
        runtime={
            "uid": os.getuid() if hasattr(os, "getuid") else None,
            "container": Path("/.dockerenv").exists(),
            "worker_environment_confirmed": False,
        },
        calls=[],
    )
    analysis = None

    def call(name, provider, endpoint, fn):
        started = time.monotonic()
        before = ledger.counts.copy()
        item = dict(
            name=name,
            provider=provider,
            endpoint_type=endpoint,
            configuration_fingerprint=frozen["configuration_fingerprint"],
        )
        try:
            output = fn()
            item.update(
                status="passed", output_count=len(output) if isinstance(output, list) else None
            )
            return output
        except PipelineError as exc:
            item.update(
                status="pending" if "unconfigured" in exc.code else "failed",
                error_code=exc.code,
                diagnostic=exc.diagnostic,
            )
        except Exception as exc:
            item.update(status="error", error_type=type(exc).__name__)
        finally:
            item["elapsed_seconds"] = round(time.monotonic() - started, 3)
            item["ledger_delta"] = {k: ledger.counts[k] - before[k] for k in before}
            report["calls"].append(item)

    analyzed = call(
        "visual",
        settings.vision_provider,
        "chat/completions" if settings.vision_provider == "hkust" else "generateContent",
        lambda: analyze_image(data, "", settings, ledger)[0],
    )
    if analyzed:
        analysis = analyzed
        report["analysis"] = analysis.model_dump(mode="json")
        report["calls"][-1]["output_count"] = len(analysis.queries)
        report["calls"][-1]["model"] = settings.effective_vision_model
    if analysis:
        planned = call(
            "query_planning",
            "deepseek",
            "chat/completions",
            lambda: DeepSeekQueryPlanner(settings, ledger).plan(analysis),
        )
        report["calls"][-1]["model"] = settings.deepseek_model
        if planned:
            analysis.queries = planned
            analysis.planner_version = (
                "deepseek/" + settings.deepseek_model + "/" + DeepSeekQueryPlanner.version
            )
            report["analysis"] = analysis.model_dump(mode="json")
    else:
        report["calls"].append(
            dict(
                name="query_planning",
                provider="deepseek",
                status="pending",
                error_code="automatic_query_unavailable",
            )
        )
    report["provider_policy"] = settings.provider_policy
    report["reverse_image"] = {
        "status": "disabled",
        "reason": "HKUST/DeepSeek-only; web retrieval is not pixel reverse-search",
    }
    for name, method in [("keyword_web", "search"), ("web_verification", "verify")]:
        if not analysis:
            report["calls"].append(
                dict(
                    name=name,
                    provider="deepseek",
                    endpoint_type="v1/tools/search",
                    status="pending",
                    error_code="automatic_query_unavailable",
                )
            )
            continue
        query = analysis.queries[0].text[:128]
        result = call(
            name,
            "deepseek",
            "v1/tools/search",
            lambda: getattr(DeepSeekWeb(settings, ledger), method)(query),
        )
        if result is not None:
            report[name] = [s.model_dump() if hasattr(s, "model_dump") else s for s in result]
    statuses = {c["status"] for c in report["calls"]}
    report["status"] = (
        "error"
        if "error" in statuses
        else "failed"
        if "failed" in statuses
        else "pending"
        if "pending" in statuses
        else "passed"
    )
    report["ledger"] = ledger.counts
    write_json(out / "probe.json", report)
    return {"passed": 0, "failed": 1, "pending": 2, "error": 3}[report["status"]]


def run_suite(args):
    manifest, cases = load_manifest(args.manifest, args.split)
    # Reject corrupt or missing frozen inputs before issuing any external job.
    for case in cases:
        input_bytes(case)
    out = new_directory(args.out)
    baseline = out / "baseline"
    baseline.mkdir()
    frozen = snapshot(baseline)
    if args.local_stack:
        from scripts.run_local_demo import local_environment

        os.environ.update(local_environment())
        from services.common.config import get_settings

        get_settings.cache_clear()
    suite = dict(
        kind="run_suite",
        manifest_version=manifest["version"],
        manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        split=args.split,
        code_fingerprint=frozen["code_fingerprint"],
        configuration_fingerprint=frozen["configuration_fingerprint"],
        cases=[],
    )
    for case in cases:
        leaf = out / case["case_id"]
        params = SimpleNamespace(
            out=leaf,
            image=ROOT / case["input_path"],
            description=case.get("description") or None,
            target_count=args.target_count,
            base_url=args.base_url,
            timeout=args.timeout,
            check_db=args.check_db,
        )
        started = time.monotonic()
        try:
            code = verify_meme50.run(params)
        except Exception as exc:
            leaf.mkdir(exist_ok=True)
            write_json(
                leaf / "evidence.json",
                dict(machine_status="error", error_type=type(exc).__name__, results=[]),
            )
            code = 3
        evidence = json.loads((leaf / "evidence.json").read_text())
        job_config = evidence.get("job", {}).get("configuration", {})
        if (
            job_config
            and digest({k: job_config.get(k) for k in PUBLIC_FIELDS})
            != frozen["configuration_fingerprint"]
        ):
            evidence["machine_status"] = "error"
            evidence["error_type"] = "WorkerConfigurationMismatch"
            code = 3
        original, metadata = input_bytes(case)
        (leaf / ("input." + metadata.suffix)).write_bytes(original)
        evidence["review_input_file"] = "input." + metadata.suffix
        evidence["review_instructions"] = case.get(
            "judgment_notes",
            "Judge visible subject, action, emotion or meme meaning, "
            "and honor the optional preference.",
        )
        evidence.update(
            case_id=case["case_id"],
            manifest_version=manifest["version"],
            code_fingerprint=frozen["code_fingerprint"],
            configuration_fingerprint=frozen["configuration_fingerprint"],
        )
        write_json(leaf / "evidence.json", evidence)
        suite["cases"].append(
            dict(
                case_id=case["case_id"],
                evidence=f"{case['case_id']}/evidence.json",
                exit_code=code,
                elapsed_seconds=round(time.monotonic() - started, 3),
            )
        )
        write_json(out / "suite.json", suite)
    # A successful suite execution does not imply quantity or quality acceptance.
    return (
        3
        if any(c["exit_code"] == 3 for c in suite["cases"])
        else 1
        if any(c["exit_code"] for c in suite["cases"])
        else 0
    )


def suite_records(runs):
    suite = json.loads((runs / "suite.json").read_text())
    entries = []
    for item in suite["cases"]:
        relative = Path(item["evidence"])
        target = (runs / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(runs.resolve()):
            raise ValueError("evidence path escapes suite")
        evidence = json.loads(target.read_text())
        if evidence.get("case_id") != item["case_id"]:
            raise ValueError("case ID differs")
        entries.append((item["case_id"], target.parent, evidence))
    if len({x[0] for x in entries}) != len(entries):
        raise ValueError("duplicate suite case")
    return suite, entries


def bound_rows(entries):
    rows = []
    for case_id, directory, evidence in entries:
        job = evidence.get("job", {})
        for item in evidence.get("results", []):
            relative = Path(item["downloaded_file"])
            target = (directory / relative).resolve()
            if relative.is_absolute() or not target.is_relative_to(directory.resolve()):
                raise ValueError("download path escapes case")
            metadata = inspect_media(target.read_bytes())
            if metadata.sha256 != item["sha256"] or item["downloaded_sha256"] != metadata.sha256:
                raise ValueError("download SHA differs")
            if (metadata.format, metadata.mime_type, metadata.frame_count, metadata.media_kind) != (
                item.get("media_format"),
                item.get("mime_type"),
                item.get("frame_count"),
                item.get("media_kind"),
            ):
                raise ValueError("download media contract differs")
            row = dict(
                case_id=case_id,
                job_id=job["job_id"],
                revision=job["result_revision"],
                candidate_id=item["candidate_id"],
                rank=str(item["rank"]),
                sha256=metadata.sha256,
            )
            rows.append((row, target, item))
    return rows


def review(args):
    suite, entries = suite_records(args.runs)
    rows = bound_rows(entries)
    out = new_directory(args.out)
    assets = out / "media"
    assets.mkdir()
    labels = []
    cards = []
    for case_id, directory, evidence in entries:
        relative = evidence.get("review_input_file")
        if relative:
            source = (directory / relative).resolve()
            if not source.is_relative_to(directory.resolve()):
                raise ValueError("review input escapes case")
            metadata = inspect_media(source.read_bytes())
            if metadata.sha256 != evidence["input_sha256"]:
                raise ValueError("review input SHA differs")
            name = f"input-{case_id}.{metadata.suffix}"
            shutil.copyfile(source, assets / name)
            context = html.escape(
                f"{case_id}: {evidence.get('description') or '(empty text)'} · "
                f"{evidence.get('review_instructions', '')} · "
                f"status={evidence.get('machine_status')}, "
                f"candidates={len(evidence.get('results', []))}"
            )
            cards.append(
                f"<article><h2>{context}</h2>"
                f'<img alt="Frozen input" data-src="media/{name}">'
                '<button type="button">Load / play</button></article>'
            )
    for i, (binding, source, item) in enumerate(rows):
        name = f"{i:04}{source.suffix}"
        shutil.copyfile(source, assets / name)
        labels.append(
            {
                **binding,
                "relevance": "unreviewed",
                "duplicate_group": "",
                "duplicate_status": "unreviewed",
                "media_valid": "unreviewed",
                "low_quality": "unreviewed",
                "notes": "",
                "reviewer": "",
            }
        )
        caption = html.escape(
            f"{binding['case_id']} #{binding['rank']} · {binding['candidate_id']} · "
            f"{binding['sha256']}"
        )
        source_url = str(item.get("source_url") or "")
        parsed_source = urlsplit(source_url)
        source_link = "Source unavailable"
        if (
            parsed_source.scheme in {"http", "https"}
            and parsed_source.hostname
            and not parsed_source.username
            and not any(c in source_url for c in "<>\"'\r\n")
        ):
            source_link = (
                '<a rel="noopener noreferrer" target="_blank" href="'
                + html.escape(source_url, quote=True)
                + '">Original source</a>'
            )
        # Load bytes only on explicit click, including animations; no remote fallbacks.
        cards.append(
            f'<article data-result="{i}">'
            f"<p>{caption}</p><p>{source_link}</p>"
            f'<img alt="Local verified result" data-src="media/{name}">'
            '<button type="button">Load / play</button>'
            "<p>Label in labels.csv: clearly_related / partially_related / unrelated;"
            " duplicate group;"
            " reviewer.</p>"
            "</article>"
        )
    failures = [
        dict(
            case_id=case_id,
            status=e.get("machine_status"),
            result_count=len(e.get("results", [])),
            error=e.get("job", {}).get("error"),
        )
        for case_id, _, e in entries
        if not e.get("results")
    ]
    with (out / "labels.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        writer.writerows(labels)
    with (out / "duplicate-groups.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[*BINDING, "duplicate_group", "reviewer"])
        writer.writeheader()
        writer.writerows(
            {**binding, "duplicate_group": "", "reviewer": ""} for binding, _, _ in rows
        )
    write_json(
        out / "cases.json",
        dict(
            suite=suite,
            cases=[
                dict(
                    case_id=c,
                    input_sha256=e.get("input_sha256"),
                    status=e.get("machine_status"),
                    result_count=len(e.get("results", [])),
                )
                for c, _, e in entries
            ],
            failures=failures,
        ),
    )
    write_json(
        out / "reproduction-template.json",
        dict(
            status="pending",
            human_attestation=False,
            independent_from_executor=False,
            operator="",
            date="",
            code_fingerprint=suite["code_fingerprint"],
            configuration_fingerprint=suite["configuration_fingerprint"],
            environment="",
            startup_command="",
            input_sha256="",
            job_id="",
            result_revision="",
            run_evidence="",
            result_count=None,
            pagination_checked=False,
            static_download_sha_checked=False,
            animated_download_sha_checked=False,
            animation_checked=False,
            problems="",
            conclusion="",
        ),
    )
    body = "\n".join(cards) or (
        "<p>No result files exist in this run. Human relevance review is pending; "
        "no old or remote media substituted.</p>"
    )
    shutil.copyfile(ROOT / "scripts/meme50_review_ui.js", out / "review-ui.js")
    bindings_json = json.dumps([row for row, _, _ in rows], ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    (out / "index.html").write_text(
        """<!doctype html>
<meta charset="utf-8">
<title>Meme50 human review</title>
<style>body{font:16px system-ui;
max-width:1100px;
margin:auto}article{border:1px solid #bbb;
margin:1em;
padding:1em;
overflow-wrap:anywhere}img{max-width:360px;
max-height:300px}pre{white-space:pre-wrap}</style>
<h1>Human relevance and duplicate review</h1>
<label>Your actual reviewer identity <input id="reviewer"></label>
<button id="export-labels" type="button">Export labels.csv</button><p id="review-message"></p>
<p>Review every animation's action. Scores and algorithm group IDs are not human labels.
Enter your own identity; do not label failed or absent results as reviewed.</p>
<p>Source cases, failures and input hashes: cases.json. Labels: labels.csv.
Independent member: reproduction-template.json.</p>"""
        + body
        + '<script>document.querySelectorAll("article button").forEach(b=>b.onclick=()=>{'
        'let i=b.parentNode.querySelector("img");'
        'if(i.hasAttribute("src")){i.removeAttribute("src");'
        'b.textContent="Load / play"}else{i.src=i.dataset.src;'
        'b.textContent="Stop / unload"}})</script>'
        + '<script id="bindings" type="application/json">'
        + bindings_json
        + "</script>"
        '<script src="review-ui.js"></script>'
    )
    return 2


def score_data(manifest, cases, suite, entries, labels):
    if suite["manifest_version"] != manifest["version"]:
        raise ValueError("manifest version mismatch")
    expected = {tuple(row[k] for k in BINDING): (row, item) for row, _, item in bound_rows(entries)}
    indexed = {}
    for label in labels:
        key = tuple(str(label.get(k, "")) for k in BINDING)
        if key not in expected or key in indexed:
            raise ValueError("foreign, stale or duplicate label identity")
        if (
            label.get("relevance") not in LABELS
            or label.get("media_valid") not in {"yes", "no", "unreviewed"}
            or label.get("low_quality") not in {"yes", "no", "unreviewed"}
            or label.get("duplicate_status") not in {"unique", "duplicate", "unreviewed"}
        ):
            raise ValueError("invalid human label")
        if (
            label.get("duplicate_status") == "duplicate"
            and not label.get("duplicate_group", "").strip()
        ):
            raise ValueError("duplicate result requires a human group")
        if label["relevance"] != "unreviewed" and not label.get("reviewer", "").strip():
            raise ValueError("human reviewer required")
        indexed[key] = label
    by_case = {c: e for c, _, e in entries}
    if set(by_case) != {c["case_id"] for c in cases}:
        raise ValueError("suite omits or adds selected cases")
    pending = len(indexed) != len(expected) or any(
        label["relevance"] == "unreviewed"
        or label["media_valid"] == "unreviewed"
        or label["low_quality"] == "unreviewed"
        or label["duplicate_status"] == "unreviewed"
        or not label.get("reviewer", "").strip()
        for label in indexed.values()
    )
    reports = []
    all_final, success_final, previews = [], [], []
    for case in cases:
        evidence = by_case[case["case_id"]]
        if evidence.get("input_sha256") != case["sha256"]:
            raise ValueError("run input SHA differs from frozen case")
        items = evidence.get("results", [])
        ranks = [i["rank"] for i in items]
        if ranks != list(range(1, len(items) + 1)) or len(items) > 50:
            raise ValueError("invalid result ranks")
        selected = [
            indexed.get(
                tuple(
                    str(v)
                    for v in [
                        case["case_id"],
                        evidence.get("job", {}).get("job_id"),
                        evidence.get("job", {}).get("result_revision"),
                        item["candidate_id"],
                        item["rank"],
                        item["sha256"],
                    ]
                )
            )
            for item in items
        ]
        clear = sum(
            label is not None and label["relevance"] == "clearly_related" for label in selected
        )
        top10 = sum(
            label is not None and label["relevance"] == "clearly_related" for label in selected[:10]
        )
        groups = [
            label["duplicate_group"].strip()
            for label in selected
            if label and label["duplicate_group"].strip()
        ]
        sha_duplicate = len(items) != len({i["sha256"] for i in items})
        human_duplicate = len(groups) != len(set(groups))
        media_bad = any(label and label["media_valid"] == "no" for label in selected)
        machine_ok = evidence.get("machine_status") == "passed"
        if not machine_ok:
            clear = top10 = 0
        prescreen = case.get("resource_rich", {})
        quantity = (
            40 <= len(items) <= 50
            and machine_ok
            and not sha_duplicate
            and not human_duplicate
            and not media_bad
        )
        elapsed = evidence.get("elapsed_seconds")
        if isinstance(elapsed, (int, float)):
            all_final.append(elapsed)
            if machine_ok and items:
                success_final.append(elapsed)
        first = evidence.get("first_preview_seconds")
        if isinstance(first, (int, float)):
            previews.append(first)
        reports.append(
            dict(
                case_id=case["case_id"],
                machine_status=evidence.get("machine_status"),
                returned=len(items),
                clearly_related=clear if not pending else None,
                top10=top10 / 10 if not pending else None,
                returned_precision=clear / len(items)
                if items and not pending
                else 0.0
                if not items
                else None,
                fixed_p50=clear / 50 if not pending else None,
                sha_duplicate=sha_duplicate,
                human_duplicate=human_duplicate if not pending else None,
                invalid_media=media_bad if not pending else None,
                resource_prescreened=bool(
                    prescreen.get("prescreened") and prescreen.get("evidence")
                ),
                quantity_gate=quantity
                if prescreen.get("prescreened") and prescreen.get("evidence")
                else None,
                ledger=evidence.get("job", {}).get("progress", {}).get("ledger", {}),
                counts=evidence.get("job", {}).get("progress", {}).get("counts", {}),
                stop_reason=evidence.get("job", {}).get("stop_reason"),
                elapsed_seconds=elapsed,
                first_preview_seconds=first,
            )
        )

    def latency(values):
        return dict(
            measured=len(values),
            total_cases=len(cases),
            p50=float(np.percentile(values, 50)) if values else None,
            p95=float(np.percentile(values, 95)) if values else None,
        )

    zero_or_fail = sum(not r["returned"] or r["machine_status"] != "passed" for r in reports)
    macro10 = None if pending else sum(r["top10"] for r in reports) / len(reports)
    macror = None if pending else sum(r["returned_precision"] for r in reports) / len(reports)
    macrop50 = None if pending else sum(r["fixed_p50"] for r in reports) / len(reports)
    # A failed/zero-result suite with no rows cannot manufacture completed human review.
    quality_status = (
        "pending"
        if pending or not expected
        else "passed"
        if macro10 >= 0.9
        and macror >= 0.8
        and not any(
            r["sha_duplicate"] or r["human_duplicate"] or r["invalid_media"] for r in reports
        )
        else "failed"
    )
    return dict(
        kind="scores",
        status=quality_status,
        split=suite["split"],
        manifest_version=manifest["version"],
        code_fingerprint=suite["code_fingerprint"],
        configuration_fingerprint=suite["configuration_fingerprint"],
        labels_complete=not pending and bool(expected),
        cases=reports,
        case_count=len(reports),
        failure_rate=zero_or_fail / len(reports),
        macro_top10=macro10,
        macro_returned_precision=macror,
        macro_fixed_p50=macrop50,
        latency=dict(
            all_final=latency(all_final),
            successful_final=latency(success_final),
            first_preview=latency(previews),
        ),
        resource_quantity_passed=sum(r["quantity_gate"] is True for r in reports),
        resource_quantity_failures=sum(
            r["resource_prescreened"]
            and r["machine_status"] == "passed"
            and not 40 <= r["returned"] <= 50
            for r in reports
        ),
        human_labels="pending" if quality_status == "pending" else "complete",
    )


def score(args):
    manifest, cases = load_manifest(args.manifest)
    suite, entries = suite_records(args.runs)
    cases = [c for c in cases if c["split"] == suite["split"]]
    if hashlib.sha256(args.manifest.read_bytes()).hexdigest() != suite["manifest_sha256"]:
        raise ValueError("manifest changed since run")
    with args.labels.open(newline="") as f:
        labels = list(csv.DictReader(f))
    report = score_data(manifest, cases, suite, entries, labels)
    out = new_directory(args.out)
    shutil.copyfile(args.labels, out / "labels.csv")
    report.update(
        evidence_version="bound-labels-v2",
        manifest_sha256=suite["manifest_sha256"],
        labels_sha256=hashlib.sha256((out / "labels.csv").read_bytes()).hexdigest(),
    )
    write_json(out / "scores.json", report)
    return {"passed": 0, "failed": 1, "pending": 2}[report["status"]]


def verified_scores(path, manifest_path, manifest, entries, split):
    if path is None:
        return {}
    report = json.loads(path.read_text())
    labels_path = path.parent / "labels.csv"
    if labels_path.is_symlink() or not labels_path.is_file():
        raise ValueError("score requires its bound labels snapshot")
    if report.get("evidence_version") != "bound-labels-v2" or report.get("split") != split:
        raise ValueError("unsupported score evidence")
    if report.get("manifest_sha256") != hashlib.sha256(manifest_path.read_bytes()).hexdigest():
        raise ValueError("score manifest SHA differs")
    if report.get("labels_sha256") != hashlib.sha256(labels_path.read_bytes()).hexdigest():
        raise ValueError("score labels SHA differs")
    cases = [c for c in manifest["cases"] if c["split"] == split]
    ids = {c["case_id"] for c in cases}
    selected = [entry for entry in entries if entry[0] in ids]
    if len(selected) != len(cases):
        raise ValueError("score suite membership differs")
    for _, _, evidence in selected:
        for field in ["code_fingerprint", "configuration_fingerprint"]:
            if evidence.get(field) != report.get(field):
                raise ValueError("score run version differs")
    with labels_path.open(newline="") as f:
        labels = list(csv.DictReader(f))
    recomputed = score_data(manifest, cases, report, selected, labels)
    if any(report.get(k) != v for k, v in recomputed.items()):
        raise ValueError("score summary differs from actual labels/results")
    return report


def verified_reproduction(path):
    if path is None:
        return {}
    report = json.loads(path.read_text())
    report["run_evidence_verified"] = False
    if report.get("status") != "passed":
        return report
    if not report.get("run_evidence"):
        raise ValueError("member attestation requires actual run evidence")
    evidence_path = Path(report["run_evidence"])
    if not evidence_path.is_absolute():
        evidence_path = path.parent / evidence_path
    evidence = json.loads(evidence_path.read_text())
    job = evidence.get("job", {})
    if (
        evidence.get("machine_status") != "passed"
        or evidence.get("database_check") != "passed"
        or evidence.get("description") != ""
        or not evidence.get("results")
        or evidence.get("input_sha256") != report.get("input_sha256")
        or job.get("job_id") != report.get("job_id")
        or job.get("result_revision") != report.get("result_revision")
        or len(evidence["results"]) != report.get("result_count")
    ):
        raise ValueError("member run does not match attestation")
    bound_rows([("member-reproduction", evidence_path.parent, evidence)])
    report["run_evidence_verified"] = True
    return report


def verified_browser(path):
    report = json.loads(path.read_text())
    if report.get("status") != "passed":
        return report
    job = report.get("job", {})
    ids = report.get("api_candidate_ids", [])
    if (
        job.get("status") != "completed"
        or not report.get("revision")
        or report.get("job_id") != job.get("job_id")
        or report["revision"] != job.get("result_revision")
        or not 0 < len(ids) <= 50
        or len(ids) != job.get("result_count")
        or len(set(ids)) != len(ids)
        or [i for page in report.get("pages", []) for i in page] != ids
    ):
        raise ValueError("browser pagination proof differs")
    for item in report.get("downloads", []):
        name = Path(item["file"])
        target = (path.parent / name).resolve()
        if name.is_absolute() or not target.is_relative_to(path.parent.resolve()):
            raise ValueError("browser download escapes evidence directory")
        metadata = inspect_media(target.read_bytes())
        if metadata.sha256 != item.get("sha256") or metadata.media_kind != item.get("kind"):
            raise ValueError("browser download proof differs")
    if report.get("assertions", {}).get("animation_pixels_changed"):
        from PIL import Image

        fingerprints = set()
        for frame in report.get("animation_frames", []):
            name = Path(frame["file"])
            target = (path.parent / name).resolve()
            if name.is_absolute() or not target.is_relative_to(path.parent.resolve()):
                raise ValueError("animation proof escapes evidence directory")
            if hashlib.sha256(target.read_bytes()).hexdigest() != frame.get("sha256"):
                raise ValueError("animation screenshot SHA differs")
            with Image.open(target) as image:
                fingerprints.add(hashlib.sha256(image.convert("RGB").tobytes()).hexdigest())
        if len(fingerprints) < 2:
            raise ValueError("animation proof contains no rendered pixel change")
    return report


def quality_passed(report):
    return (
        report.get("status") == "passed"
        and report.get("labels_complete") is True
        and all(
            isinstance(report.get(k), (int, float))
            and not isinstance(report[k], bool)
            and math.isfinite(report[k])
            and 0 <= report[k] <= 1
            for k in ["macro_top10", "macro_returned_precision"]
        )
        and report["macro_top10"] >= 0.9
        and report["macro_returned_precision"] >= 0.8
    )


def finalize_data(
    probe_report, suite_entries, development, heldout, browsers, regression, reproduction, manifest
):
    jobs = [e.get("job", {}) for _, _, e in suite_entries]
    traces = [j.get("execution", {}).get("trace", []) if j.get("execution") else [] for j in jobs]
    successful = [
        e for _, _, e in suite_entries if e.get("machine_status") == "passed" and e.get("results")
    ]
    calls = probe_report.get("calls", [])
    expected = {
        "visual": ("hkust", "chat/completions", "model_calls"),
        "query_planning": ("deepseek", "chat/completions", "model_calls"),
        "keyword_web": ("deepseek", "v1/tools/search", "search_calls"),
        "web_verification": ("deepseek", "v1/tools/search", "search_calls"),
    }
    four = probe_report.get("provider_policy") == "hkust-deepseek-v1" and all(
        any(
            c.get("name") == name
            and c.get("provider") == provider
            and c.get("endpoint_type") == endpoint
            and c.get("status") == "passed"
            and c.get("ledger_delta", {}).get(counter, 0) > 0
            and (name != "query_planning" or c.get("model") == "deepseek-flash")
            for c in calls
        )
        for name, (provider, endpoint, counter) in expected.items()
    )
    binding = any(
        digest({k: j.get("configuration", {}).get(k) for k in PUBLIC_FIELDS})
        == probe_report.get("configuration_fingerprint")
        and j.get("execution", {}).get("model_calls", 0) > 0
        for j in jobs
        if j.get("execution")
    )
    distinct_analyses = {
        (e.get("input_sha256"), tuple(e.get("job", {}).get("analysis", {}).get("observations", [])))
        for e in successful
        if e.get("description", "") == "" and e.get("job", {}).get("analysis")
    }
    automatic = len(distinct_analyses) >= 2 and any(
        j.get("analysis", {}).get("user_text") == ""
        and len({q.get("angle") for q in j.get("analysis", {}).get("queries", [])}) >= 2
        and any(
            t.get("step") == "entity_verification"
            and t.get("details", {}).get("before")
            and t.get("details", {}).get("after")
            and t.get("details", {}).get("evidence")
            for t in trace
        )
        for j, trace in zip(jobs, traces)
        if j.get("analysis")
    )
    recall = any(
        any(
            t.get("step") == "query_planning"
            and t.get("details", {}).get("provider") == "deepseek"
            and t.get("details", {}).get("model") == "deepseek-flash"
            for t in trace
        )
        and any(
            t.get("step") == "keyword_web"
            and t.get("details", {}).get("provider") == "deepseek"
            and t.get("details", {}).get("sources", 0) > 0
            for t in trace
        )
        and job.get("progress", {}).get("counts", {}).get("valid_media", 0) > 0
        for job, trace in zip(jobs, traces)
    )
    hcases = [c for c in manifest["cases"] if c["split"] == "heldout"]
    coverage = (
        len(hcases) >= 12
        and sum(not c.get("description") for c in hcases) >= 8
        and sum(c.get("media_kind") == "animated" for c in hcases) >= 4
        and {c["format"] for c in hcases} >= {"PNG", "JPEG", "WEBP", "GIF"}
        and {"chinese_text", "human_reaction", "cartoon_or_animal", "crop"}
        <= set().union(*(set(c.get("categories", [])) for c in hcases))
    )
    reproduction_ok = (
        reproduction.get("status") == "passed"
        and all(
            reproduction.get(k)
            for k in [
                "operator",
                "date",
                "environment",
                "startup_command",
                "input_sha256",
                "job_id",
                "code_fingerprint",
                "configuration_fingerprint",
                "pagination_checked",
                "static_download_sha_checked",
                "animated_download_sha_checked",
                "animation_checked",
                "conclusion",
            ]
        )
        and reproduction.get("human_attestation") is True
        and reproduction.get("independent_from_executor") is True
        and reproduction.get("run_evidence_verified") is True
    )
    gates = dict(
        A0="passed" if four and binding else "pending",
        A1="passed" if automatic else "pending",
        A2="passed" if recall else "pending",
        A3="passed"
        if any(e.get("database_check") == "passed" for e in successful)
        and {"static", "animated"}
        <= {i.get("media_kind") for e in successful for i in e.get("results", [])}
        else "pending",
        A4="failed"
        if development.get("resource_quantity_failures", 0)
        else "passed"
        if development.get("resource_quantity_passed", 0) >= 3
        and development.get("labels_complete")
        else "pending"
        if not development.get("labels_complete")
        else "failed",
        A5=(
            "passed"
            if quality_passed(heldout)
            else "failed"
            if heldout.get("status") == "failed"
            else "pending"
        )
        if coverage
        and heldout.get("case_count") == len(hcases)
        and {c.get("case_id") for c in heldout.get("cases", [])} == {c["case_id"] for c in hcases}
        and heldout.get("code_fingerprint")
        else "pending",
        A6="passed"
        if browsers
        and all(
            b.get("status") == "passed"
            and all(
                b.get("assertions", {}).get(k) is True
                for k in [
                    "pagination_ids",
                    "refresh_position",
                    "filter_counts",
                    "mobile_scroll",
                    "no_unconditional_original_loading",
                ]
            )
            for b in browsers
        )
        and {"static", "animated"}
        <= {
            d.get("kind")
            for b in browsers
            for d in b.get("downloads", [])
            if d.get("verified") and d.get("database_check") == "passed"
        }
        and any(
            all(
                b.get("assertions", {}).get(k) is True
                for k in [
                    "animation_pixels_changed",
                    "animation_paused",
                    "offscreen_animation_paused",
                ]
            )
            for b in browsers
        )
        else "pending",
        A7="passed"
        if regression.get("status") == "passed"
        and regression.get("code_fingerprint") == probe_report.get("code_fingerprint")
        and all(
            regression.get(k)
            for k in [
                "python_postgres",
                "web",
                "ruff",
                "diff_check",
                "prettier",
                "deployment_checked",
            ]
        )
        else "pending",
        A8="passed"
        if reproduction_ok and heldout.get("labels_complete") and development.get("labels_complete")
        else "pending",
    )
    if any(b.get("status") == "error" for b in browsers):
        gates["A6"] = "error"
    elif any(b.get("status") == "failed" for b in browsers):
        gates["A6"] = "failed"
    if regression.get("status") in {"failed", "error"}:
        gates["A7"] = regression["status"]
    if any(
        e.get("machine_status") == "passed" and not e.get("results") for _, _, e in suite_entries
    ):
        gates["A3"] = "failed"
    if probe_report.get("status") in {"failed", "error"}:
        gates["A0"] = probe_report["status"]
    if any(
        e.get("machine_status") in {"error", "failed"}
        and e.get("job", {}).get("stop_reason")
        not in {
            "visual_provider_unconfigured",
            "image_search_unconfigured",
            "keyword_search_unconfigured",
        }
        for _, _, e in suite_entries
    ):
        gates["A3"] = "failed"
    # All supplied versions must refer to one frozen implementation/configuration.
    artifacts = [development, heldout, *browsers, regression, reproduction]
    mismatch = any(
        a.get("code_fingerprint") and a["code_fingerprint"] != probe_report.get("code_fingerprint")
        for a in artifacts
    )
    mismatch |= any(
        a.get("configuration_fingerprint")
        and a["configuration_fingerprint"] != probe_report.get("configuration_fingerprint")
        for a in [development, heldout, *browsers, reproduction]
    )
    status = (
        "error"
        if mismatch or "error" in gates.values()
        else "failed"
        if "failed" in gates.values()
        else "pending"
        if "pending" in gates.values()
        else "passed"
    )
    return dict(
        kind="final_acceptance",
        status=status,
        gates=gates,
        version_mismatch=mismatch,
        code_fingerprint=probe_report.get("code_fingerprint"),
        configuration_fingerprint=probe_report.get("configuration_fingerprint"),
        credentials_or_human_material_pending=status == "pending",
    )


def finalize(args):
    manifest, _ = load_manifest(args.manifest)
    records = []
    for runs in args.runs:
        _, entries = suite_records(runs)
        records.extend(entries)

    def read(p):
        return json.loads(p.read_text()) if p else {}

    report = finalize_data(
        read(args.probe),
        records,
        verified_scores(args.development_scores, args.manifest, manifest, records, "development"),
        verified_scores(args.heldout_scores, args.manifest, manifest, records, "heldout"),
        [verified_browser(p) for p in args.browser],
        read(args.regression),
        verified_reproduction(args.reproduction),
        manifest,
    )
    out = new_directory(args.out)
    write_json(out / "final.json", report)
    (out / "report.md").write_text(
        "# Meme50 acceptance\n\nStatus: **"
        + report["status"]
        + "**\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in report["gates"].items())
        + "\n\nNo pending authorization, human labels "
        "or member reproduction is treated as passed.\n"
    )
    return {"passed": 0, "failed": 1, "pending": 2, "error": 3}[report["status"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("probe")
    p.add_argument("--image", type=Path, required=True)
    p.set_defaults(handler=probe)
    p = commands.add_parser("run-suite")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--split", choices=["development", "heldout"], required=True)
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--target-count", type=int, choices=range(1, 51), default=50)
    p.add_argument("--timeout", type=float, default=330)
    p.add_argument("--check-db", action="store_true")
    p.add_argument("--local-stack", action="store_true")
    p.set_defaults(handler=run_suite)
    p = commands.add_parser("review")
    p.add_argument("--runs", type=Path, required=True)
    p.set_defaults(handler=review)
    p = commands.add_parser("score")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--labels", type=Path, required=True)
    p.set_defaults(handler=score)
    p = commands.add_parser("finalize")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--probe", type=Path, required=True)
    p.add_argument("--runs", type=Path, action="append", default=[])
    p.add_argument("--development-scores", type=Path)
    p.add_argument("--heldout-scores", type=Path)
    p.add_argument("--browser", type=Path, action="append", default=[])
    p.add_argument("--regression", type=Path)
    p.add_argument("--reproduction", type=Path)
    p.set_defaults(handler=finalize)
    for p in commands.choices.values():
        p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        status = args.handler(args)
    except Exception as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        raise SystemExit(3) from None
    print(json.dumps({"command": args.command, "exit_code": status, "out": str(args.out)}))
    raise SystemExit(status)


if __name__ == "__main__":
    main()
