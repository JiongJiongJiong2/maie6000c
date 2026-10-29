"""Run the persistent local PostgreSQL, API and independent search worker."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".cache/local-demo.env"


def local_environment() -> dict[str, str]:
    ENV_FILE.parent.mkdir(exist_ok=True)
    if not ENV_FILE.exists():
        ENV_FILE.write_text(
            "POSTGRES_PASSWORD=" + secrets.token_hex(24) + "\nPOSTGRES_HOST_PORT=55432\n"
        )
        ENV_FILE.chmod(0o600)
    values = dotenv_values(ENV_FILE)
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": "postgresql+psycopg://postgres:"
            + values["POSTGRES_PASSWORD"]
            + "@127.0.0.1:"
            + values["POSTGRES_HOST_PORT"]
            + "/maie6000c",
            "MEDIA_ROOT": str(ROOT / "data/media"),
            "REFERENCE_ROOT": str(ROOT / "data/reference"),
            "MODEL_CACHE_ROOT": str(ROOT / "data/models"),
            "ENABLE_DEMO_LIBRARY": "true",
            "DEVICE_TOKEN": "",
            "WORKER_POLL_SECONDS": "0.5",
            "RETRIEVAL_TIMEOUT_SECONDS": "120",
            "HF_HUB_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    return env


def main():
    os.chdir(ROOT)
    env = local_environment()
    if not (ROOT / "data/models/gif-frames.npz").exists():
        raise SystemExit(
            "Prepare the GIF library and run python -m services.retrieval.engine index."
        )
    subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "memeretrieve-local",
            "--env-file",
            str(ENV_FILE),
            "up",
            "-d",
            "--wait",
            "db",
        ],
        check=True,
        env=env,
    )
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)
    subprocess.run(
        [sys.executable, "-m", "services.common.reference_assets", "data/reference/manifest.json"],
        check=True,
        env=env,
    )
    children = []
    logs = []
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    commands = {
        "api": [
            "-m",
            "uvicorn",
            "services.api.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        "worker": ["-m", "services.worker.app.search_worker"],
    }
    try:
        for name, command in commands.items():
            log = (ROOT / f".cache/local-{name}.log").open("a")
            logs.append(log)
            children.append(
                subprocess.Popen(
                    [sys.executable, *command], env=env, stdout=log, stderr=subprocess.STDOUT
                )
            )
        print("MemeRetrieve: http://127.0.0.1:8000/web/", flush=True)
        print("API and worker logs: .cache/local-api.log and .cache/local-worker.log", flush=True)
        while not stop.wait(1):
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A service stopped. Check the local API and worker logs.")
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 130
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for log in logs:
            log.close()
        print("API and worker stopped. PostgreSQL data is retained.", flush=True)


if __name__ == "__main__":
    main()
