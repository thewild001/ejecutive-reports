"""Persistent execution history for scheduled report wrappers.

The ledger is intentionally local to a single host/filesystem. It is not a
distributed lock or a multi-host coordination mechanism.
"""
from __future__ import annotations

import argparse
import os
import socket
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "SKIPPED_LOCKED", "TIMED_OUT", "INTERRUPTED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def database_path() -> Path:
    configured = os.environ.get("REPORTS_STATE_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    root = Path(__file__).resolve().parent.parent
    return root / "output" / ".state" / "execution-ledger.sqlite3"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_meta (
               version INTEGER NOT NULL
           )"""
    )
    row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
    if row is None:
        connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
    elif row["version"] != SCHEMA_VERSION:
        connection.close()
        raise RuntimeError(
            f"Versión de ledger no soportada: {row['version']} (esperada {SCHEMA_VERSION})"
        )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS executions (
               run_id TEXT PRIMARY KEY,
               report TEXT NOT NULL,
               status TEXT NOT NULL,
               started_at TEXT NOT NULL,
               finished_at TEXT,
               exit_code INTEGER,
               duration_seconds REAL,
               host TEXT NOT NULL,
               pid INTEGER NOT NULL,
               log_path TEXT,
               metadata_json TEXT NOT NULL DEFAULT '{}'
           )"""
    )
    connection.commit()
    try:
        os.chmod(path, 0o600)
        wal = Path(str(path) + "-wal")
        if wal.exists():
            os.chmod(wal, 0o600)
    except OSError:
        pass
    return connection


def start(report: str, log_path: str | None, pid: int, host: str) -> str:
    run_id = str(uuid.uuid4())
    started = utc_now()
    with connect(database_path()) as db:
        db.execute(
            """INSERT INTO executions
               (run_id, report, status, started_at, host, pid, log_path)
               VALUES (?, ?, 'RUNNING', ?, ?, ?, ?)""",
            (run_id, report, started, host, pid, log_path),
        )
    return run_id


def finish(run_id: str, status: str, exit_code: int) -> None:
    if status not in TERMINAL_STATES:
        raise ValueError(f"Estado terminal inválido: {status}")
    with connect(database_path()) as db:
        row = db.execute(
            "SELECT started_at, status FROM executions WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"run_id desconocido: {run_id}")
        if row["status"] != "RUNNING":
            raise ValueError(f"La ejecución {run_id} ya terminó con estado {row['status']}")
        started = datetime.fromisoformat(row["started_at"])
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        db.execute(
            """UPDATE executions
               SET status = ?, finished_at = ?, exit_code = ?, duration_seconds = ?
               WHERE run_id = ? AND status = 'RUNNING'""",
            (status, utc_now(), exit_code, round(elapsed, 3), run_id),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Gestiona el ledger de ejecuciones programadas")
    sub = parser.add_subparsers(dest="command", required=True)
    begin = sub.add_parser("start")
    begin.add_argument("--report", required=True)
    begin.add_argument("--log-path")
    begin.add_argument("--pid", type=int, default=os.getpid())
    begin.add_argument("--host", default=socket.gethostname())
    end = sub.add_parser("finish")
    end.add_argument("--run-id", required=True)
    end.add_argument("--status", choices=sorted(TERMINAL_STATES), required=True)
    end.add_argument("--exit-code", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "start":
            print(start(args.report, args.log_path, args.pid, args.host))
        else:
            finish(args.run_id, args.status, args.exit_code)
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"execution-ledger: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
