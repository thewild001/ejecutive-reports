"""Tests de Fase 3: caché SQLite, exporters y snapshots (sin red)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.cache import ApiCache
from common.exporters import export_rows
from common import snapshots


def _cache(tmp: Path, ttl=3600, enabled=True) -> ApiCache:
    return ApiCache(tmp / ".cache.db", ttl_seconds=ttl, enabled=enabled)


# ── cache ────────────────────────────────────────────────────────────────

def test_cache_roundtrip_and_expiry(tmp_path: Path):
    c = _cache(tmp_path, ttl=1)
    c.set("k1", '{"a": 1}')
    assert c.get("k1") == '{"a": 1}'
    c.set("k2", "x", ttl_seconds=0)  # expiración inmediata
    time.sleep(0.01)
    assert c.get("k2") is None
    c.close()


def test_cache_disabled_is_noop(tmp_path: Path):
    c = _cache(tmp_path, enabled=False)
    c.set("k", "v")
    assert c.get("k") is None
    assert c.clear() == 0


def test_cache_clear(tmp_path: Path):
    c = _cache(tmp_path)
    c.set("a", "1"); c.set("b", "2")
    assert c.clear() == 2
    assert c.get("a") is None


def test_cache_from_config(tmp_path: Path):
    cfg = {"output": {"dir": tmp_path}, "cache": {"enabled": True, "ttl_seconds": 60}}
    c = ApiCache.from_config(cfg)
    assert c.enabled and c.ttl == 60
    c.close()


# ── exporters ────────────────────────────────────────────────────────────

def test_export_csv_and_json(tmp_path: Path):
    base = tmp_path / "informe_x_20260913.pdf"
    created = export_rows(["A", "B"], [["1", "2"], ["3", "4"]], base,
                          ["csv", "json"])
    csv_path = tmp_path / "informe_x_20260913.csv"
    json_path = tmp_path / "informe_x_20260913.json"
    assert csv_path in created and json_path in created
    assert '"A","B"' not in csv_path.read_text()  # csv sin comillas forzadas
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data[1] == {"A": "3", "B": "4"}


def test_export_xlsx_degrades_without_openpyxl(tmp_path: Path):
    created = export_rows(["A"], [["1"]], tmp_path / "f.pdf", ["xlsx"])
    try:
        import openpyxl  # noqa: F401
        assert created  # instalado → sí se crea
    except ImportError:
        assert created == []  # degradación: warning + omisión


def test_export_ignores_pdf_and_unknown(tmp_path: Path):
    assert export_rows(["A"], [["1"]], tmp_path / "f.pdf", ["pdf", "docx"]) == []


# ── snapshots ────────────────────────────────────────────────────────────

def test_snapshot_roundtrip(tmp_path: Path):
    payload = {"proj": {"open": 5, "health": 80.0}}
    snapshots.save(tmp_path, "informe_x", payload)
    assert snapshots.load(tmp_path, "informe_x") == payload


def test_snapshot_load_missing(tmp_path: Path):
    assert snapshots.load(tmp_path, "nada") == {}


def test_snapshot_diff_only_changes():
    prev = {"p1": {"open": 5, "closed": 10}, "p2": {"open": 1}}
    curr = {"p1": {"open": 8, "closed": 10}, "p2": {"open": 1}}
    deltas = snapshots.diff(prev, curr, {"open": "abiertas", "closed": "cerradas"})
    assert len(deltas) == 1
    assert "p1" in deltas[0] and "abiertas" in deltas[0] and "↑3" in deltas[0]
