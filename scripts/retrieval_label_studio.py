"""Prepare private MemeRetrieve blind review tasks for Label Studio Community Edition."""

import argparse
import hashlib
import json
import os
import random
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import ProxyHandler, build_opener, Request

HERE = Path(__file__).resolve().parent
DEFAULT_STATE = HERE.parent / ".cache" / "label-studio"
HOST = "127.0.0.1"
SUPPORTED_MEDIA = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def credentials(state):
    path = state / "login.local.json"
    state.mkdir(parents=True, exist_ok=True)
    try:
        data = {
            "email": "gif-review@localhost.local",
            "password": secrets.token_urlsafe(24),
            "token": secrets.token_hex(20),
        }
        with path.open("x", encoding="utf-8") as file:
            json.dump(data, file)
    except FileExistsError:
        pass
    return json.loads(path.read_text(encoding="utf-8"))


class ReviewMedia(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(404)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *_args):
        pass


def start(state, port, media_port):
    account = credentials(state)
    app_data = state / "app"
    app_data.mkdir(exist_ok=True)
    media = state / "review-media"
    media.mkdir(exist_ok=True)
    env = os.environ | {
        "LABEL_STUDIO_BASE_DATA_DIR": str(app_data),
        "LABEL_STUDIO_USERNAME": account["email"],
        "LABEL_STUDIO_PASSWORD": account["password"],
        "LABEL_STUDIO_USER_TOKEN": account["token"],
        "LABEL_STUDIO_DISABLE_SIGNUP_WITHOUT_LINK": "true",
        "LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED": "false",
        "LABEL_STUDIO_LATEST_VERSION_CHECK": "false",
        "LABEL_STUDIO_COLLECT_ANALYTICS": "false",
        "LABEL_STUDIO_SENTRY_DSN": "",
        "LABEL_STUDIO_FRONTEND_SENTRY_DSN": "",
    }
    command = [
        sys.executable,
        "-m",
        "label_studio.server",
        "start",
        "--enable-legacy-api-token",
        "--internal-host",
        HOST,
        "--port",
        str(port),
        "--host",
        f"http://{HOST}:{port}",
        "--data-dir",
        str(app_data),
        "--no-browser",
    ]
    handler = partial(ReviewMedia, directory=str(media))
    with ThreadingHTTPServer((HOST, media_port), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(
            f"Label Studio http://{HOST}:{port}/ | Login file {state / 'login.local.json'}",
            flush=True,
        )
        try:
            return subprocess.call(command, env=env, cwd=app_data)
        finally:
            server.shutdown()
            thread.join()


def local_media_url(relative, manifest_dir, destination, media_port):
    url = urlsplit(relative)
    if url.scheme or url.netloc or url.query or url.fragment:
        raise ValueError("Review media must be a relative path without URL parameters.")
    source = (manifest_dir / unquote(url.path)).resolve(strict=True)
    source_root = (manifest_dir / "media").resolve(strict=True)
    if (
        not source.is_file()
        or not source.is_relative_to(source_root)
        or source.suffix.lower() not in SUPPORTED_MEDIA
    ):
        raise ValueError(
            "Review media must be a supported image inside the manifest's media folder."
        )
    content = source.read_bytes()
    name = hashlib.sha256(content).hexdigest() + source.suffix.lower()
    copy = destination / name
    if not copy.exists():
        temporary = copy.with_name(f".{copy.name}.{secrets.token_hex(6)}")
        temporary.write_bytes(content)
        temporary.replace(copy)
    return f"http://{HOST}:{media_port}/{name}"


def blind_tasks(manifest, state, media_port):
    manifest = manifest.resolve(strict=True)
    document = json.loads(manifest.read_text(encoding="utf-8-sig"))
    dataset_id = document["dataset_id"]
    destination = state / "review-media"
    destination.mkdir(parents=True, exist_ok=True)
    resolved = {}
    tasks = []
    seen_pairs = set()

    def figure(heading, relative):
        if relative not in resolved:
            resolved[relative] = local_media_url(relative, manifest.parent, destination, media_port)
        return (
            '<div style="flex:1 1 15rem; min-width:0; text-align:center;">'
            f'<p><strong>{heading}</strong></p><img alt="{heading}" src="{resolved[relative]}" '
            'style="max-width:100%; max-height:300px; object-fit:contain;" /></div>'
        )

    for case in document["cases"]:
        case_id = case["case_id"]
        if not case["candidates"]:
            continue
        query = figure("查询截图", case["query_url"])
        reference = figure("原版参照", case["reference_url"]) if case.get("reference_url") else ""
        for item in case["candidates"]:
            candidate_id = item["candidate_id"]
            key = (case_id, candidate_id)
            if key in seen_pairs:
                raise ValueError(f"Duplicate review pair {key!r}.")
            seen_pairs.add(key)
            candidate = figure("匿名候选", item["media_url"])
            preview = (
                '<div style="display:flex; flex-wrap:wrap; gap:16px;">'
                + query
                + reference
                + candidate
                + "</div>"
            )
            tasks.append(
                {
                    "data": {
                        "dataset_id": dataset_id,
                        "case_id": case_id,
                        "candidate_id": candidate_id,
                        "preview": preview,
                    }
                }
            )
    if not tasks:
        raise ValueError("No review candidates in this manifest.")
    return dataset_id, tasks


def task_key(data):
    return data["dataset_id"], data["case_id"], data["candidate_id"]


def sync_tasks(api, project_id, shuffled):
    expected = {task_key(t["data"]): t["data"] for t in shuffled}

    def existing():
        if not api(f"projects/{project_id}/")["task_number"]:
            return set()
        path = f"projects/{project_id}/export?exportType=JSON&download_all_tasks=true"
        present = set()
        for task in api(path):
            key = task_key(task["data"])
            if key in present or expected.get(key) != task["data"]:
                raise ValueError(f"Project {project_id} contains duplicate or unexpected task data")
            present.add(key)
        return present

    # SQLite imports can briefly contend with Label Studio's project setup.
    # A response may fail after commit. Reconcile the actual pair keys before retrying.
    for attempt in range(4):
        present = existing()
        remaining = [t for t in shuffled if task_key(t["data"]) not in present]
        try:
            for start in range(0, len(remaining), 20):
                batch = remaining[start : start + 20]
                result = api(f"projects/{project_id}/import", batch)
                if result["task_count"] != len(batch):
                    raise RuntimeError(f"Unexpected task count from project {project_id} import")
            break
        except (HTTPError, TimeoutError) as exc:
            if attempt == 3 or (
                isinstance(exc, HTTPError) and exc.code not in {500, 502, 503, 504}
            ):
                raise
            time.sleep(2**attempt)
    if existing() != set(expected):
        raise RuntimeError(f"Project {project_id} is missing frozen review pairs after import")


def import_projects(state, port, media_port, manifest, aliases):
    account = credentials(state)
    opener = build_opener(ProxyHandler({}))
    dataset_id, tasks = blind_tasks(manifest, state, media_port)
    content_id = hashlib.sha256(json.dumps(tasks, sort_keys=True).encode()).hexdigest()[:12]
    compact_id = re.sub(r"[^\w.-]", "-", dataset_id)[:10]
    label_config = (HERE / "label_studio_gif_review.xml").read_text(encoding="utf-8")

    def api(path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Authorization": f"Token {account['token']}", "Content-Type": "application/json"}
        with opener.open(
            Request(f"http://{HOST}:{port}/api/{path}", data=body, headers=headers), timeout=40
        ) as response:
            return json.load(response)

    page = 1
    projects = {}
    while True:
        result = api(f"projects/?page_size=100&page={page}")
        projects.update((p["title"], p) for p in result["results"])
        if not result.get("next"):
            break
        page += 1
    imported = []
    for alias in aliases:
        review_id = hashlib.sha256(f"{content_id}:{alias}".encode()).hexdigest()[:12]
        title = f"GIF · {compact_id} · {alias[:17]} · {review_id}"
        project = projects.get(title)
        if project is None:
            project = api(
                "projects/",
                {"title": title, "label_config": label_config, "maximum_annotations": 1},
            )
        project_id = project["id"]
        shuffled = list(tasks)
        random.Random(f"{content_id}:{alias}").shuffle(shuffled)
        sync_tasks(api, project_id, shuffled)
        imported.append(
            {
                "reviewer": alias,
                "project_id": project_id,
                "tasks": len(tasks),
                "url": f"http://{HOST}:{port}/projects/{project_id}/data",
            }
        )
    print(
        json.dumps({"dataset_id": dataset_id, "projects": imported}, ensure_ascii=False, indent=2)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "import"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--port", type=int, default=58631)
    parser.add_argument("--media-port", type=int, default=58632)
    parser.add_argument(
        "--reviewer",
        action="append",
        help="One project per reviewer. Default reviewer-01 and reviewer-02.",
    )
    args = parser.parse_args()
    state = args.state.resolve()
    if args.action == "start":
        return start(state, args.port, args.media_port)
    if args.manifest is None:
        parser.error("import requires --manifest")
    aliases = args.reviewer or ["reviewer-01", "reviewer-02"]
    if len(set(aliases)) != len(aliases) or any(
        not re.fullmatch(r"[\w.-]{1,40}", alias) for alias in aliases
    ):
        parser.error(
            "reviewer aliases must be unique and use 1–40 letters, digits, underscores, "
            "periods or hyphens"
        )
    state.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(state / "import-lock.sqlite3", timeout=60)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        import_projects(state, args.port, args.media_port, args.manifest, aliases)
    return 0


if __name__ == "__main__":
    sys.exit(main())
