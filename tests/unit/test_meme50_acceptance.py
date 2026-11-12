import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from scripts import meme50_acceptance as acceptance
from scripts.verify_meme50 import run
from services.common.media import inspect_media
from services.search_agent.meme_providers import provider_diagnostic


def record(tmp_path, case_id="one", count=1, status="passed"):
    folder = tmp_path / case_id
    folder.mkdir()
    items = []
    for rank in range(1, count + 1):
        out = io.BytesIO()
        Image.new("RGB", (20, 20), (rank, rank * 3, rank * 5)).save(out, "PNG")
        data = out.getvalue()
        m = inspect_media(data)
        filename = f"{rank}.png"
        (folder / filename).write_bytes(data)
        items.append(
            dict(
                candidate_id=f"candidate-{rank}",
                rank=rank,
                sha256=m.sha256,
                downloaded_sha256=m.sha256,
                downloaded_file=filename,
                media_kind="static",
                media_format=m.format,
                mime_type=m.mime_type,
                frame_count=m.frame_count,
            )
        )
    evidence = dict(
        case_id=case_id,
        input_sha256="a" * 64,
        machine_status=status,
        job=dict(job_id=f"job-{case_id}", result_revision="rev"),
        results=items,
        elapsed_seconds=10,
    )
    case = dict(case_id=case_id, sha256="a" * 64, split="heldout", family=case_id)
    return case, (case_id, folder, evidence)


def suite():
    return dict(
        manifest_version="test-v1",
        split="heldout",
        code_fingerprint="code",
        configuration_fingerprint="configuration",
    )


def labels_for(entry, relevance="clearly_related"):
    rows = []
    for binding, _, _ in acceptance.bound_rows([entry]):
        rows.append(
            dict(
                **binding,
                relevance=relevance,
                duplicate_group="",
                duplicate_status="unique",
                media_valid="yes",
                low_quality="no",
                reviewer="TEST FIXTURE (not a real acceptance label)",
            )
        )
    return rows


def test_fixed_denominators_include_failed_case_and_short_lists(tmp_path):
    c1, e1 = record(tmp_path, count=2)
    c2, e2 = record(tmp_path, "failed", count=0, status="failed")
    result = acceptance.score_data(
        {"version": "test-v1"}, [c1, c2], suite(), [e1, e2], labels_for(e1)
    )
    assert result["macro_top10"] == 0.1  # 2/10, then failure=0, macro of both.
    assert result["macro_returned_precision"] == 0.5
    assert result["macro_fixed_p50"] == 0.02
    assert result["failure_rate"] == 0.5 and result["status"] == "failed"


def test_unreviewed_missing_and_stale_labels_cannot_pass(tmp_path):
    case, entry = record(tmp_path)
    manifest = {"version": "test-v1"}
    assert acceptance.score_data(manifest, [case], suite(), [entry], [])["status"] == "pending"
    labels = labels_for(entry, "unreviewed")
    assert acceptance.score_data(manifest, [case], suite(), [entry], labels)["status"] == "pending"
    labels = labels_for(entry)
    labels[0]["job_id"] = "another-attempt"
    with pytest.raises(ValueError, match="identity"):
        acceptance.score_data(manifest, [case], suite(), [entry], labels)
    labels = labels_for(entry)
    labels[0]["reviewer"] = ""
    with pytest.raises(ValueError, match="reviewer"):
        acceptance.score_data(manifest, [case], suite(), [entry], labels)


def test_duplicate_groups_not_only_sha_are_quality_failures(tmp_path):
    case, entry = record(tmp_path, count=10)
    labels = labels_for(entry)
    labels[0]["duplicate_group"] = labels[1]["duplicate_group"] = "same-visual-content"
    labels[0]["duplicate_status"] = labels[1]["duplicate_status"] = "duplicate"
    result = acceptance.score_data({"version": "test-v1"}, [case], suite(), [entry], labels)
    assert result["macro_top10"] == 1 and result["status"] == "failed"
    assert result["cases"][0]["human_duplicate"]


def test_files_rechecked_and_review_does_not_load_remote_media(tmp_path):
    case, entry = record(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    folder = runs / case["case_id"]
    entry[1].rename(folder)
    evidence = entry[2]
    evidence["results"][0]["source_url"] = 'https://example.org/"><script>alert(1)</script>'
    acceptance.write_json(folder / "evidence.json", evidence)
    acceptance.write_json(
        runs / "suite.json",
        dict(
            **suite(),
            cases=[dict(case_id=case["case_id"], evidence=f"{case['case_id']}/evidence.json")],
        ),
    )
    out = tmp_path / "review"
    assert acceptance.review(SimpleNamespace(runs=runs, out=out)) == 2
    content = (out / "index.html").read_text()
    assert 'data-src="media/0000.png"' in content and 'src="https:' not in content
    assert "alert(1)" not in content
    with (out / "labels.csv").open() as f:
        row = list(csv.DictReader(f))[0]
    assert row["relevance"] == "unreviewed" and row["reviewer"] == ""
    (folder / "1.png").write_bytes(b"broken")
    with pytest.raises(ValueError):
        acceptance.bound_rows([(case["case_id"], folder, evidence)])


def test_existing_attempt_refused_without_overwrite(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep").write_text("original")
    with pytest.raises(FileExistsError):
        run(SimpleNamespace(out=target, image=Path("not-used")))
    assert (target / "keep").read_text() == "original"


def test_manifest_family_leak_and_input_sha(tmp_path):
    manifest = dict(
        version="v2",
        cases=[
            dict(case_id="a", split="development", family="same"),
            dict(case_id="b", split="heldout", family="same"),
        ],
    )
    file = tmp_path / "manifest.json"
    file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="leakage"):
        acceptance.load_manifest(file)
    out = io.BytesIO()
    Image.new("RGB", (10, 10)).save(out, "PNG")
    path = tmp_path / "input.png"
    path.write_bytes(out.getvalue())
    with pytest.raises(ValueError, match="SHA"):
        acceptance.input_bytes(
            dict(input_path=str(path), sha256="wrong", format="PNG", media_kind="static")
        )


def test_finalizer_empty_artifacts_and_fake_provider_success_are_pending():
    probe = dict(status="pending", calls=[], code_fingerprint="c", configuration_fingerprint="s")
    result = acceptance.finalize_data(probe, [], {}, {}, [], {}, {}, dict(cases=[]))
    assert result["status"] == "pending" and all(v == "pending" for v in result["gates"].values())
    probe.update(
        status="passed",
        calls=[
            dict(name=n, status="passed")
            for n in ["visual", "reverse_image", "keyword_images", "web_verification"]
        ],
    )
    result = acceptance.finalize_data(probe, [], {}, {}, [], {}, {}, dict(cases=[]))
    assert result["gates"]["A0"] == "pending"  # No actual calls / runtime binding.


def test_hkust_deepseek_policy_gates_require_real_calls_and_downloaded_media(tmp_path):
    configuration = acceptance.public_configuration()
    calls = [
        dict(
            name=name,
            provider=provider,
            endpoint_type=endpoint,
            status="passed",
            model="deepseek-flash" if name == "query_planning" else "gemini-2.5-flash-lite",
            ledger_delta={counter: 1},
        )
        for name, provider, endpoint, counter in [
            ("visual", "hkust", "chat/completions", "model_calls"),
            ("query_planning", "deepseek", "chat/completions", "model_calls"),
            ("keyword_web", "deepseek", "v1/tools/search", "search_calls"),
            ("web_verification", "deepseek", "v1/tools/search", "search_calls"),
        ]
    ]
    probe = dict(
        status="passed",
        provider_policy="hkust-deepseek-v1",
        calls=calls,
        configuration_fingerprint=acceptance.digest(configuration),
        code_fingerprint="controlled-code",
    )
    job = dict(
        configuration=configuration,
        execution=dict(
            model_calls=3,
            trace=[
                dict(
                    step="query_planning", details=dict(provider="deepseek", model="deepseek-flash")
                ),
                dict(step="keyword_web", details=dict(provider="deepseek", sources=12)),
            ],
        ),
        progress=dict(counts=dict(valid_media=1)),
    )
    entries = [(dict(case_id="controlled"), tmp_path, dict(job=job))]
    result = acceptance.finalize_data(probe, entries, {}, {}, [], {}, {}, dict(cases=[]))
    assert result["gates"]["A0"] == result["gates"]["A2"] == "passed"
    job["progress"]["counts"]["valid_media"] = 0
    assert (
        acceptance.finalize_data(probe, entries, {}, {}, [], {}, {}, dict(cases=[]))["gates"]["A2"]
        == "pending"
    )
    calls[2]["provider"] = "brave"
    assert (
        acceptance.finalize_data(probe, entries, {}, {}, [], {}, {}, dict(cases=[]))["gates"]["A0"]
        == "pending"
    )


def test_error_diagnostics_drop_messages_and_unknown_reason():
    diagnostic = provider_diagnostic(
        403,
        dict(
            message="SECRET MUST NOT BE LOGGED",
            status="PERMISSION_DENIED",
            details=[dict(reason="SERVICE_DISABLED"), dict(reason="SECRET_TOKEN")],
        ),
    )
    assert diagnostic["classification"] == "service_not_enabled"
    assert "SECRET" not in json.dumps(diagnostic)
    assert provider_diagnostic(404)["classification"] == "model_or_endpoint_not_found"
    assert provider_diagnostic(429)["classification"] == "quota_or_rate_limit"


def test_google_http200_business_error_is_not_provider_pass(monkeypatch):
    from services.search_agent.meme_providers import GoogleImageSearch
    from services.search_agent.meme_types import Ledger, MemeSettings, PipelineError

    monkeypatch.setattr(
        "services.search_agent.meme_providers.bounded_json",
        lambda *a, **k: {"responses": [{"error": {"code": 7, "message": "untrusted vendor text"}}]},
    )
    settings = MemeSettings(google_vision_api_key="controlled-test")
    with pytest.raises(PipelineError, match="image_search_failed") as error:
        GoogleImageSearch(settings, Ledger(settings)).search(Image.new("RGB", (10, 10)))
    assert error.value.diagnostic["http_status"] == 200
    assert error.value.diagnostic["business_code"] == 7
    assert "message" not in error.value.diagnostic


def test_missing_duplicate_judgment_keeps_all_quality_pending(tmp_path):
    case, entry = record(tmp_path, count=10)
    labels = labels_for(entry)
    labels[0]["duplicate_status"] = "unreviewed"
    result = acceptance.score_data({"version": "test-v1"}, [case], suite(), [entry], labels)
    assert result["status"] == "pending" and result["macro_top10"] is None


def test_runtime_fingerprint_is_same_without_test_tree_or_dockerfile(tmp_path, monkeypatch):
    root = tmp_path / "source"
    (root / "services").mkdir(parents=True)
    (root / "services" / "code.py").write_text("value = 1\n")
    monkeypatch.setattr(acceptance, "ROOT", root)
    first = tmp_path / "one"
    first.mkdir()
    a = acceptance.snapshot(first)
    (root / "tests").mkdir()
    (root / "tests" / "test.py").write_text("assert True\n")
    (root / "Dockerfile").write_text("FROM example\n")
    second = tmp_path / "two"
    second.mkdir()
    b = acceptance.snapshot(second)
    assert a["code_fingerprint"] == b["code_fingerprint"]
    assert a["source_snapshot_fingerprint"] != b["source_snapshot_fingerprint"]


def test_idempotent_replay_can_advance_status_while_upload_decodes(tmp_path, monkeypatch):
    import httpx
    from scripts import verify_meme50

    real_client = httpx.Client
    accepted = dict(
        request_id="same-request",
        job_id="same-job",
        search_profile="meme50-v2",
        contract_version=2,
        target_count=50,
        status="pending",
    )
    posts = []

    def handle(request):
        if request.method == "POST":
            posts.append(True)
            return httpx.Response(
                202, json={**accepted, "status": "pending" if len(posts) == 1 else "failed"}
            )
        return httpx.Response(
            200,
            json=dict(
                job_id="same-job", status="failed", stop_reason="visual_provider_unconfigured"
            ),
        )

    monkeypatch.setattr(
        verify_meme50.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    image = tmp_path / "random.png"
    out = io.BytesIO()
    Image.new("RGB", (12, 12)).save(out, "PNG")
    image.write_bytes(out.getvalue())
    args = SimpleNamespace(
        image=image,
        out=tmp_path / "attempt",
        description=None,
        target_count=50,
        base_url="https://controlled.example.org",
        timeout=3,
        check_db=False,
    )
    assert verify_meme50.run(args) == 2
    evidence = json.loads((args.out / "evidence.json").read_text())
    assert evidence["machine_status"] == "failed" and evidence["replay"]["status"] == "failed"
    assert "error_type" not in evidence


def scored_fixture(tmp_path, count=10):
    import hashlib

    case, entry = record(tmp_path, count=count)
    entry[2].update(code_fingerprint="code", configuration_fingerprint="configuration")
    manifest = dict(version="test-v1", cases=[case])
    manifest_path = tmp_path / "manifest.json"
    acceptance.write_json(manifest_path, manifest)
    run_folder = tmp_path / "runs"
    run_folder.mkdir()
    entry[1].rename(run_folder / case["case_id"])
    entry = (entry[0], run_folder / case["case_id"], entry[2])
    acceptance.write_json(entry[1] / "evidence.json", entry[2])
    suite_data = dict(
        **suite(),
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        cases=[dict(case_id=case["case_id"], evidence=f"{case['case_id']}/evidence.json")],
    )
    acceptance.write_json(run_folder / "suite.json", suite_data)
    labels_path = tmp_path / "labels.csv"
    with labels_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=acceptance.LABEL_FIELDS)
        writer.writeheader()
        writer.writerows(labels_for(entry))
    args = SimpleNamespace(
        manifest=manifest_path, runs=run_folder, labels=labels_path, out=tmp_path / "scores"
    )
    assert acceptance.score(args) == 0
    return args, manifest, entry


def test_final_scores_are_recomputed_not_trusted_summary_flags(tmp_path):
    args, manifest, entry = scored_fixture(tmp_path)
    path = args.out / "scores.json"
    assert (
        acceptance.verified_scores(path, args.manifest, manifest, [entry], "heldout")["status"]
        == "passed"
    )
    report = json.loads(path.read_text())
    report["macro_top10"] = 0.95
    acceptance.write_json(path, report)
    with pytest.raises(ValueError, match="summary differs"):
        acceptance.verified_scores(path, args.manifest, manifest, [entry], "heldout")


def test_final_scores_reject_changed_label_snapshot_and_other_attempt(tmp_path):
    args, manifest, entry = scored_fixture(tmp_path)
    path = args.out / "scores.json"
    entry[2]["job"]["job_id"] = "other-attempt"
    with pytest.raises(ValueError, match="identity"):
        acceptance.verified_scores(path, args.manifest, manifest, [entry], "heldout")
    (args.out / "labels.csv").write_text("changed labels")
    with pytest.raises(ValueError, match="labels SHA"):
        acceptance.verified_scores(path, args.manifest, manifest, [entry], "heldout")


def test_member_pass_flags_without_run_proof_are_rejected(tmp_path):
    path = tmp_path / "member.json"
    acceptance.write_json(
        path,
        dict(
            status="passed",
            human_attestation=True,
            independent_from_executor=True,
            run_evidence_verified=True,
        ),
    )
    with pytest.raises(ValueError, match="actual run"):
        acceptance.verified_reproduction(path)


def test_browser_pass_with_wrong_pagination_is_rejected(tmp_path):
    path = tmp_path / "browser.json"
    acceptance.write_json(
        path,
        dict(
            status="passed",
            job_id="job",
            revision="rev",
            job=dict(status="completed", job_id="job", result_revision="rev", result_count=2),
            api_candidate_ids=["first", "second"],
            pages=[["first", "first"]],
        ),
    )
    with pytest.raises(ValueError, match="pagination proof"):
        acceptance.verified_browser(path)


def test_different_png_bytes_without_pixel_motion_cannot_prove_animation(tmp_path):
    import hashlib
    from PIL.PngImagePlugin import PngInfo

    frames = []
    for i in range(2):
        info = PngInfo()
        info.add_text("encoding-note", str(i))
        out = io.BytesIO()
        Image.new("RGB", (20, 20), "red").save(out, "PNG", pnginfo=info)
        name = f"capture-{i}.png"
        (tmp_path / name).write_bytes(out.getvalue())
        frames.append(dict(file=name, sha256=hashlib.sha256(out.getvalue()).hexdigest()))
    assert frames[0]["sha256"] != frames[1]["sha256"]
    path = tmp_path / "browser.json"
    acceptance.write_json(
        path,
        dict(
            status="passed",
            job_id="job",
            revision="rev",
            job=dict(status="completed", job_id="job", result_revision="rev", result_count=1),
            api_candidate_ids=["first"],
            pages=[["first"]],
            downloads=[],
            assertions=dict(animation_pixels_changed=True),
            animation_frames=frames,
        ),
    )
    with pytest.raises(ValueError, match="pixel change"):
        acceptance.verified_browser(path)


def test_quality_gate_requires_complete_finite_threshold_measurements():
    assert not acceptance.quality_passed(dict(status="passed", labels_complete=True))
    assert not acceptance.quality_passed(
        dict(
            status="passed",
            labels_complete=True,
            macro_top10=float("nan"),
            macro_returned_precision=1,
        )
    )
    assert not acceptance.quality_passed(
        dict(status="passed", labels_complete=False, macro_top10=1, macro_returned_precision=1)
    )
    assert acceptance.quality_passed(
        dict(status="passed", labels_complete=True, macro_top10=0.9, macro_returned_precision=0.8)
    )


def test_media_contract_cannot_claim_gif_for_valid_png_sha(tmp_path):
    _, entry = record(tmp_path)
    entry[2]["results"][0]["media_format"] = "GIF"
    with pytest.raises(ValueError, match="media contract"):
        acceptance.bound_rows([entry])
