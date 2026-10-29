"""Run the W07 demo using a workspace-local PostgreSQL on Windows.

Download/extract EDB's PostgreSQL 16 binary archive first. This alternative
does not require Docker and does not install a Windows service.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

from dotenv import dotenv_values

from run_local_demo import ENV_FILE, ROOT, local_environment

PGDATA = ROOT / ".cache/w07-postgres"


def pg_command(bin_dir: Path, name: str, *args: str, **kwargs):
    return subprocess.run(
        [str(bin_dir / f"{name}.exe"), *args],
        creationflags=subprocess.CREATE_NO_WINDOW,
        **kwargs,
    )


def prepare_database(bin_dir: Path) -> dict[str, str]:
    env = local_environment()
    values = dotenv_values(ENV_FILE)
    port = values["POSTGRES_HOST_PORT"]
    if not (bin_dir / "postgres.exe").is_file():
        raise SystemExit(f"PostgreSQL binaries not found: {bin_dir}")
    if not (PGDATA / "PG_VERSION").exists():
        password_file = ROOT / ".cache/w07-pg-password.tmp"
        try:
            password_file.write_text(values["POSTGRES_PASSWORD"] + "\n", encoding="ascii")
            pg_command(
                bin_dir, "initdb", "-D", str(PGDATA), "-U", "postgres",
                "--encoding=UTF8", "--locale=C", "--auth=scram-sha-256",
                f"--pwfile={password_file}", check=True,
            )
        finally:
            password_file.unlink(missing_ok=True)
    status = pg_command(bin_dir, "pg_ctl", "-D", str(PGDATA), "status", capture_output=True)
    if status.returncode != 0:
        pg_command(
            bin_dir, "pg_ctl", "-D", str(PGDATA), "-l",
            str(ROOT / ".cache/local-postgres.log"), "-o",
            f"-h 127.0.0.1 -p {port}", "-w", "start", check=True,
        )
    import psycopg

    with psycopg.connect(
        host="127.0.0.1", port=int(port), user="postgres",
        password=values["POSTGRES_PASSWORD"], dbname="postgres", autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", ("maie6000c",)
        ).fetchone()
        if not exists:
            connection.execute("CREATE DATABASE maie6000c")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   cwd=ROOT, env=env, check=True)
    subprocess.run(
        [sys.executable, "-m", "services.common.reference_assets", "data/reference/manifest.json"],
        cwd=ROOT, env=env, check=True,
    )
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", type=Path,
                        default=ROOT / ".cache/pg16/pgsql/bin")
    parser.add_argument("--database-only", action="store_true")
    parser.add_argument("--stop-database", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This launcher is for Windows. Use run_local_demo.py on other hosts.")
    bin_dir = args.postgres_bin.resolve()
    if args.stop_database:
        pg_command(bin_dir, "pg_ctl", "-D", str(PGDATA), "-m", "fast", "-w", "stop",
                   check=True)
        return
    env = prepare_database(bin_dir)
    if args.database_only:
        print("PostgreSQL prepared. Database records are retained in .cache/w07-postgres.")
        return
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    children, logs = [], []
    commands = {
        "api": ["-m", "uvicorn", "services.api.app.main:app", "--host", "127.0.0.1",
                "--port", "8000"],
        "worker": ["-m", "services.worker.app.search_worker"],
    }
    try:
        for name, command in commands.items():
            log = (ROOT / f".cache/local-{name}.log").open("a", encoding="utf-8")
            logs.append(log)
            children.append(subprocess.Popen(
                [sys.executable, *command], cwd=ROOT, env=env, stdout=log,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
            ))
        print("MemeRetrieve: http://127.0.0.1:8000/web/ (native PostgreSQL)", flush=True)
        while not stop.wait(1):
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A service stopped. Inspect .cache/local-api.log and worker log")
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=15)
        for log in logs:
            log.close()
        print("API and worker stopped. PostgreSQL and records remain available.")


if __name__ == "__main__":
    main()
