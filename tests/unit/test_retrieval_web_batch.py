import io
import json

import pytest
from PIL import Image

from scripts import meme50_acceptance as acceptance
from scripts import retrieval_web_batch as bridge
from services.common.media import inspect_media


def picture(index, animated):
    image = Image.new("RGB", (10, 10), (index, 60, 0))
    out = io.BytesIO()
    if animated:
        image.save(
            out,
            "GIF",
            save_all=True,
            append_images=[Image.new("RGB", image.size, "red")],
            duration=100,
            loop=0,
        )
    else:
        image.save(out, "PNG")
    return out.getvalue()


def test_plan_is_source_blind_and_scoring_checks_original_bytes(tmp_path):
    assets, cases = [], []
    for i in range(6):
        target, query = picture(i, True), picture(i, False)
        gif_path, image = f"{i}.gif", f"{i}.png"
        (tmp_path / gif_path).write_bytes(target)
        (tmp_path / image).write_bytes(query)
        sha = bridge.digest(target)
        split = "final" if i == 5 else "development"
        family = f"原始名称{max(1, i)}"
        assets.append(
            dict(
                id=str(i),
                family_id=family,
                gif_path=gif_path,
                sha256=sha,
                frame_count=2,
                split=split,
                source=f"{bridge.REPO}/blob/{bridge.REV}/public/meme/{i}.gif",
                license="Community source, unverified" if i == 4 else bridge.LICENSE,
            )
        )
        cases.append(
            dict(
                id=f"internal-{i}",
                split=split,
                cohort="animated_original",
                target_asset_id=str(i),
                target_sha256=sha,
                family_id=family,
                transform="crop",
                image=image,
                image_sha256=bridge.digest(query),
            )
        )
    source = tmp_path / "original.json"
    bridge.write_json(source, dict(assets=assets, cases=cases))
    batch = tmp_path / "batch"
    assert bridge.freeze(source, batch, 3) == 3
    manifest, public = acceptance.load_manifest(batch / "manifest.json", "development")
    key = json.loads((batch / "private/answers.json").read_bytes())
    assert len({c["family"] for c in public}) == 3
    assert {c["local_case_id"] for c in key["cases"].values()} == {
        "internal-0",
        "internal-2",
        "internal-3",
    }
    text = (batch / "manifest.json").read_text(encoding="ascii")
    for c in public:
        assert c.get("description", "") == ""
        assert key["cases"][c["case_id"]]["target_sha256"] not in text
    assert "github" not in text and "internal-" not in text
    assert bridge.score(batch)["statuses"] == {"missing": 3}
    with pytest.raises(ValueError, match="only 4 are eligible"):
        bridge.freeze(source, tmp_path / "excessive", 5)

    runs = tmp_path / "runs"
    attempts = []
    success = public[0]["case_id"]
    for i, c in enumerate(public[:2]):
        cid = c["case_id"]
        leaf = runs / cid
        leaf.mkdir(parents=True)
        query, _ = acceptance.input_bytes(c)
        (leaf / "input.png").write_bytes(query)
        items = []
        if i == 0:
            files = [picture(j + 10, False) for j in range(3)]
            files.append((batch / "private" / key["cases"][cid]["original"]).read_bytes())
            for rank, data in enumerate(files, 1):
                meta = inspect_media(data)
                name = f"{rank}.{meta.suffix}"
                (leaf / name).write_bytes(data)
                items.append(
                    dict(
                        candidate_id=str(rank),
                        rank=rank,
                        downloaded_file=name,
                        downloaded_sha256=meta.sha256,
                        sha256=meta.sha256,
                        media_format=meta.format,
                        frame_count=meta.frame_count,
                        mime_type=meta.mime_type,
                        media_kind=meta.media_kind,
                    )
                )
        evidence = dict(
            case_id=cid,
            input_sha256=c["sha256"],
            review_input_file="input.png",
            configuration_fingerprint="config",
            code_fingerprint="code",
            machine_status="failed" if i else "passed",
            results=items,
            job=dict(
                job_id=cid,
                result_count=len(items),
                result_revision="rev",
                status="failed" if i else "completed",
            ),
        )
        acceptance.write_json(leaf / "evidence.json", evidence)
        attempts.append(
            dict(
                case_id=cid,
                evidence=f"{cid}/evidence.json",
                elapsed_seconds=3,
                exit_code=2 if i else 0,
            )
        )
    acceptance.write_json(
        runs / "suite.json",
        dict(
            manifest_sha256=key["query_manifest_sha256"],
            manifest_version=manifest["version"],
            split="development",
            code_fingerprint="code",
            configuration_fingerprint="config",
            cases=attempts,
        ),
    )
    report = bridge.score(batch, runs)
    assert report["planned"] == 3
    assert report["statuses"] == {"completed": 1, "failed": 1, "missing": 1}
    assert report["exact_hits_among_all_planned"] == {
        "exact_rank": {"top1": 0, "top3": 0},
        "animation_rank": {"top1": 1, "top3": 1},
    }
    (runs / success / "4.gif").write_bytes(picture(30, True))
    with pytest.raises(ValueError, match="download SHA differs"):
        bridge.score(batch, runs)
