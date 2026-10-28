"""Exercise the live API, independent worker, review and original animated download."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def verify():
    manifest = json.loads((ROOT / "data/reference/manifest.json").read_text())
    asset = next(asset for asset in manifest["assets"] if asset["title"] == "Mind blown")
    image = ROOT / "data/reference/examples" / (Path(asset["gif_path"]).stem + ".png")
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30, trust_env=False) as client:
        client.get("/health/ready").raise_for_status()
        key = str(uuid4())

        def upload():
            return client.post(
                "/search-requests",
                data={"client_submission_key": key},
                files={"image": (image.name, image.read_bytes(), "image/png")},
            )

        accepted = upload()
        assert accepted.status_code == 202, accepted.text
        ids = accepted.json()
        replay = upload().json()
        assert replay["request_id"] == ids["request_id"] and replay["job_id"] == ids["job_id"]
        states = []
        started = time.monotonic()
        while time.monotonic() - started < 120:
            result = client.get(f"/search-requests/{ids['request_id']}").json()
            if not states or states[-1] != result["status"]:
                states.append(result["status"])
            if result["status"] in {"completed", "failed"}:
                break
            time.sleep(0.3)
        assert result["status"] == "completed", result
        assert result["result_kind"] == "candidates", result
        candidate = result["candidates"][0]
        payload = {
            "decision": "accept",
            "candidate_id": candidate["candidate_id"],
            "client_review_key": str(uuid4()),
        }
        review = client.post(f"/search-jobs/{ids['job_id']}/reviews", json=payload)
        review.raise_for_status()
        replay = client.post(f"/search-jobs/{ids['job_id']}/reviews", json=payload)
        assert replay.json() == review.json()
        media = client.get(candidate["media_url"])
        media.raise_for_status()
        checksum = hashlib.sha256(media.content).hexdigest()
        assert checksum == asset["sha256"], "Top-ranked download must be the correct original GIF"
        with Image.open(io.BytesIO(media.content)) as gif:
            assert gif.format == "GIF" and gif.n_frames > 1
            frames = gif.n_frames
        target = ROOT / ".cache/live-download.gif"
        target.write_bytes(media.content)
        evidence = {
            "request_id": ids["request_id"],
            "job_id": ids["job_id"],
            "observed_states": states,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "query": asset["title"],
            "candidate_count": len(result["candidates"]),
            "top_score": candidate["score"],
            "download_sha256": checksum,
            "download_frames": frames,
            "review_id": review.json()["review_id"],
            "upload_and_review_replay": "passed",
            "retrieval": "real local CLIP",
            "database": "PostgreSQL 16",
            "worker": "independent process",
        }
        (ROOT / ".cache/live-verification.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    verify()
