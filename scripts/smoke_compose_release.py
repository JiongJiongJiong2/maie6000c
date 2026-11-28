"""Test prebuilt release images in an isolated pgvector Compose project without CLIP weights."""

from __future__ import annotations

import argparse
from contextlib import suppress
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("api", "worker", "media-fetch")
CLIENT_ENV = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "XDG_CONFIG_HOME",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)",
    "SYSTEMDRIVE",
    "HOMEDRIVE",
    "HOMEPATH",
    "DOCKER_CONFIG",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "DOCKER_API_VERSION",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
}

VECTOR_FIXTURE = r"""
import io
import sys

import numpy as np
from sqlalchemy import select

from services.common.accounts import accounts
from services.common.config import get_settings, use_workspace
from services.common.db import get_session_factory
from services.common.search_models import SavedAsset
from services.common.storage import atomic_write, validate_image
from services.retrieval.saved_index import (
    frame_numbers, identity, index_location, read_saved_gif, validate_vectors,
)

mode, username, asset_id = sys.argv[1:]
with get_session_factory()() as db:
    workspace = db.scalar(select(accounts.c.workspace).where(accounts.c.username == username))
if not workspace or workspace == "public":
    raise RuntimeError("Expected an isolated smoke account")
with use_workspace(workspace):
    with get_session_factory()() as db:
        asset = db.get(SavedAsset, asset_id)
        if asset is None or validate_image(read_saved_gif(asset), animated_gif=True) != 2:
            raise RuntimeError("The imported original GIF is invalid")
        metadata, version = identity(asset)
        frames = frame_numbers(asset.frame_count)
        vectors = np.zeros((len(frames), 512), dtype=np.float32)
        vectors[:, 0] = 1.0
        validate_vectors(vectors, len(frames))
        if mode == "seed":
            if asset.index_status != "pending":
                raise RuntimeError("Fixture must be prepared before starting the worker")
            output = io.BytesIO()
            np.savez_compressed(output, metadata=metadata, frames=frames, embeddings=vectors)
            atomic_write(
                get_settings().media_root, index_location(asset, version), output.getvalue()
            )
        elif mode == "rank":
            from services.retrieval.vector_store import rank_saved_vectors

            if asset.index_status != "ready" or asset.index_version != version:
                raise RuntimeError("Worker did not publish the trusted fixture generation")
            if rank_saved_vectors(vectors[0], 3, 0.82) != [
                {"reference_asset_id": asset.id, "score": 1.0}
            ]:
                raise RuntimeError("Saved pgvector rankings did not match the fixture")
        else:
            raise RuntimeError("Invalid fixture action")
"""


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Stack:
    def __init__(self, directory, images, timeout):
        self.timeout = timeout
        self.project = "meme-smoke-" + secrets.token_hex(8)
        self.env = {key: value for key, value in os.environ.items() if key.upper() in CLIENT_ENV}
        reference = directory / "reference"
        reference.mkdir()
        settings = {
            "POSTGRES_PASSWORD": secrets.token_hex(24),
            "POSTGRES_HOST_PORT": "0",
            "API_HOST_PORT": "0",
            "API_BIND_HOST": "127.0.0.1",
            "REFERENCE_HOST_PATH": reference.as_posix(),
            "ACCOUNT_LOGIN_ENABLED": "true",
            "PRIVATE_LIBRARY_ENABLED": "true",
            "ENABLE_DEMO_LIBRARY": "false",
            "VECTOR_BACKEND": "pgvector",
            "WORKER_POLL_SECONDS": "0.5",
            "SAVED_INDEX_TIMEOUT_SECONDS": "60",
            "SEARCH_WORKER_STOP_GRACE_PERIOD": "10s",
        }
        env_file = directory / "smoke.env"
        env_file.write_text(
            "".join(
                f"{key}={json.dumps(value, ensure_ascii=False)}\n"
                for key, value in settings.items()
            ),
            encoding="utf-8",
        )
        override = directory / "images.json"
        override.write_text(
            json.dumps(
                {
                    "services": {
                        service: {"image": image, "pull_policy": "never"}
                        for service, image in images.items()
                    }
                }
            ),
            encoding="utf-8",
        )
        self.base = [
            "docker",
            "compose",
            "--ansi",
            "never",
            "--project-name",
            self.project,
            "--env-file",
            str(env_file),
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            str(ROOT / "compose.pgvector.yaml"),
            "-f",
            str(override),
        ]

    def compose(self, *args, capture=False, check=True):
        return subprocess.run(
            [*self.base, *args],
            cwd=ROOT,
            env=self.env,
            timeout=self.timeout + 30,
            check=check,
            capture_output=capture,
            encoding="utf-8",
        ).stdout

    def up(self, *services):
        self.compose("up", "--no-build", "--wait", "--wait-timeout", str(self.timeout), *services)

    def sql(self, statement):
        return self.compose(
            "exec",
            "-T",
            "db",
            "psql",
            "-XAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "maie6000c",
            "-c",
            statement,
            capture=True,
        ).strip()


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )

    def request(self, path, status=200, method="GET", body=None, headers=None):
        headers = dict(headers or {})
        if method != "GET":
            headers["Origin"] = self.base
        request = urllib.request.Request(self.base + path, body, headers, method=method)
        try:
            response = self.opener.open(request, timeout=15)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            require(
                response.code == status,
                f"{method} {path}: HTTP {response.code}, expected {status}",
            )
            return response.headers, response.read()

    def send_json(self, path, value, status=200):
        return json.loads(
            self.request(
                path,
                status,
                "POST",
                json.dumps(value).encode(),
                {"Content-Type": "application/json"},
            )[1]
        )

    def get_json(self, path):
        return json.loads(self.request(path)[1])


def enroll(client):
    credentials = {
        "username": "smoke-" + secrets.token_hex(8),
        "password": secrets.token_urlsafe(24),
    }
    account = client.send_json("/auth/register", credentials, 201)
    require(account.get("username") == credentials["username"], "Registration response mismatch")
    page = client.request("/web/search")[1]
    account_marker = f'data-account="{account["username"]}"'.encode()
    require(account_marker in page, "Session did not open the app")
    return credentials


def import_fixture(client):
    fixture = (ROOT / "web/tests/fixtures/two-frames.gif").read_bytes()
    digest = hashlib.sha256(fixture).hexdigest()
    batch = client.send_json(
        "/library/imports",
        {
            "client_batch_key": secrets.token_hex(16),
            "items": [
                {
                    "client_item_id": "smoke-fixture",
                    "filename": "smoke-fixture.gif",
                    "byte_size": len(fixture),
                    "sha256": digest,
                }
            ],
        },
    )
    boundary = "meme-smoke-" + secrets.token_hex(12)
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="smoke-fixture.gif"\r\n'
            "Content-Type: image/gif\r\n\r\n"
        ).encode()
        + fixture
        + f"\r\n--{boundary}--\r\n".encode()
    )
    path = f"/library/imports/{batch['batch_id']}/items/smoke-fixture"
    item = json.loads(
        client.request(
            path, 200, "PUT", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )[1]
    )
    require(item.get("status") == "imported" and item.get("asset_id"), "Fixture import failed")
    asset_id = item["asset_id"]
    media_headers, original = client.request(f"/saved-assets/{asset_id}/media")
    require(media_headers.get_content_type() == "image/gif" and original == fixture, "GIF altered")
    return asset_id, digest


def wait_for_saved_index(client, asset_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get_json(f"/saved-assets/{asset_id}")["index_status"]
        if state == "ready":
            return
        if state == "failed":
            raise RuntimeError("Worker could not publish the model-free GIF fixture")
        time.sleep(1)
    raise RuntimeError("Timed out waiting for the worker to index the smoke GIF")


def smoke(stack):
    stack.up("db", "api", "media-fetch")
    stack.compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "worker",
        "python",
        "-m",
        "services.retrieval.vector_store",
        "provision",
    )
    extension = stack.sql("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    require(bool(extension), "pgvector extension is missing")
    require(
        stack.sql(
            "SELECT to_regclass('public.reference_frame_vectors') IS NOT NULL "
            "AND to_regclass('public.saved_frame_vectors') IS NOT NULL"
        )
        == "t",
        "Public pgvector relations are missing",
    )

    address = stack.compose("port", "api", "8000", capture=True).strip()
    api = "http://127.0.0.1:" + str(int(address.rsplit(":", 1)[1]))
    first, second = Client(api), Client(api)
    require(first.get_json("/health/ready").get("status") == "ok", "API is not ready")
    first.request("/library/assets", 401)
    require(b"account.js" in first.request("/web/search")[1], "Account page is missing")
    for name in ("app.js", "share.js", "meme50.js"):
        headers, body = first.request("/web/" + name)
        require(
            headers.get_content_type() in {"application/javascript", "text/javascript"}
            and bool(body),
            f"Invalid module response for {name}",
        )

    one = enroll(first)
    enroll(second)
    asset_id, digest = import_fixture(first)
    require(not second.get_json("/library/assets").get("assets"), "Account libraries overlap")
    second.request(f"/saved-assets/{asset_id}/media", 404)
    stack.compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "worker",
        "python",
        "-c",
        VECTOR_FIXTURE,
        "seed",
        one["username"],
        asset_id,
    )
    stack.up("worker")
    wait_for_saved_index(first, asset_id, stack.timeout)
    stack.compose(
        "exec", "-T", "worker", "python", "-c", VECTOR_FIXTURE, "rank", one["username"], asset_id
    )
    stack.compose(
        "exec",
        "-T",
        "worker",
        "python",
        "-c",
        "import urllib.request; "
        "urllib.request.urlopen('http://media-fetch:8120/health/live', timeout=5)",
    )
    first.send_json("/auth/logout", {})
    first.request("/library/assets", 401)
    first.send_json("/auth/login", one)
    first.request(f"/saved-assets/{asset_id}/media")
    return {
        "status": "passed",
        "pgvector_version": extension,
        "gif_sha256": digest,
        "rank_mode": "deterministic fixture embeddings; no CLIP inference",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--worker-image", required=True)
    parser.add_argument("--fetch-image", required=True)
    parser.add_argument("--timeout", type=int, default=150, metavar="SECONDS")
    args = parser.parse_args()
    if not 15 <= args.timeout <= 600:
        parser.error("--timeout must be between 15 and 600 seconds")
    images = dict(zip(SERVICES, (args.api_image, args.worker_image, args.fetch_image), strict=True))
    with tempfile.TemporaryDirectory(prefix="meme-compose-smoke-") as name:
        stack = Stack(Path(name), images, args.timeout)
        report = None
        try:
            report = smoke(stack)
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            print(f"Compose smoke failed: {exc}", file=sys.stderr, flush=True)
            with suppress(OSError, subprocess.SubprocessError):
                stack.compose("ps", "-a", check=False)
                stack.compose("logs", "--no-color", "--tail", "50", check=False)
        finally:
            try:
                stack.compose("down", "--volumes", "--remove-orphans")
            except (OSError, subprocess.SubprocessError):
                print(f"Cleanup failed for smoke project {stack.project}", file=sys.stderr)
                report = None
        if report is None:
            return 1
        print(json.dumps({**report, "images": images}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
