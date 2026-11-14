import sqlite3

import pytest

from common import execution_ledger as ledger


def test_start_and_finish_persist_execution(tmp_path, monkeypatch):
    db_path = tmp_path / "state" / "ledger.sqlite3"
    monkeypatch.setenv("REPORTS_STATE_DB", str(db_path))

    run_id = ledger.start("gespro", "/tmp/gespro.log")
    ledger.finish(run_id, "SUCCEEDED", 0)

    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT report, status, exit_code, finished_at, duration_seconds "
            "FROM executions WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    assert row[0] == "gespro"
    assert row[1] == "SUCCEEDED"
    assert row[2] == 0
    assert row[3] is not None
    assert row[4] >= 0


def test_skipped_lock_is_a_terminal_non_success_state(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_STATE_DB", str(tmp_path / "ledger.sqlite3"))
    run_id = ledger.start("gitlab", None)

    ledger.finish(run_id, "SKIPPED_LOCKED", 75)

    with sqlite3.connect(ledger.database_path()) as db:
        status, code = db.execute(
            "SELECT status, exit_code FROM executions WHERE run_id = ?", (run_id,)
        ).fetchone()
    assert (status, code) == ("SKIPPED_LOCKED", 75)


def test_execution_cannot_be_finished_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_STATE_DB", str(tmp_path / "ledger.sqlite3"))
    run_id = ledger.start("trends", None)
    ledger.finish(run_id, "FAILED", 1)

    with pytest.raises(ValueError, match="ya terminó"):
        ledger.finish(run_id, "SUCCEEDED", 0)


def test_unknown_execution_cannot_be_finished(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTS_STATE_DB", str(tmp_path / "ledger.sqlite3"))

    with pytest.raises(ValueError, match="desconocido"):
        ledger.finish("missing-run-id", "FAILED", 1)
