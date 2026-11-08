"""Caché persistente de respuestas de API (Fase 3).

SQLite stdlib en ``output/.cache.db``; si el intérprete no trae ``_sqlite3``
compilado, degrada a un archivo JSON (``output/.cache.db.json``) con la misma
semántica. Cada entrada tiene TTL; los valores expirados se tratan como
ausentes. Desactivado por completo si ``cache.enabled`` es falso en config.yaml.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

try:
    import sqlite3
except ImportError:  # entornos mínimos sin _sqlite3 compilado
    sqlite3 = None

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


class _JsonStore:
    """Fallback sin sqlite3: mismo comportamiento sobre un archivo JSON."""

    def __init__(self, path: Path):
        self._path = path
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data), encoding="utf-8")

    def get(self, key: str) -> tuple[str, float] | None:
        entry = self._data.get(key)
        return (entry["value"], entry["expires_at"]) if entry else None

    def set(self, key: str, value: str, expires_at: float) -> None:
        self._data[key] = {"value": value, "expires_at": expires_at}
        self._flush()

    def delete(self, key: str) -> None:
        if self._data.pop(key, None) is not None:
            self._flush()

    def clear(self) -> int:
        n = len(self._data)
        self._data = {}
        self._flush()
        return n

    def close(self) -> None:
        pass


class _SqliteStore:
    def __init__(self, path: Path):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(_SCHEMA)

    def get(self, key: str) -> tuple[str, float] | None:
        return self._conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,),
        ).fetchone()

    def set(self, key: str, value: str, expires_at: float) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, value, expires_at),
        )
        self._conn.commit()

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        self._conn.commit()

    def clear(self) -> int:
        cur = self._conn.execute("DELETE FROM cache")
        self._conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()


class ApiCache:
    """Caché key→JSON con TTL. Instanciar una vez por proceso."""

    def __init__(self, db_path: Path, ttl_seconds: int = 3600, enabled: bool = True):
        self.ttl = ttl_seconds
        self.enabled = enabled and bool(db_path)
        self._store = None
        if self.enabled:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            if sqlite3 is not None:
                self._store = _SqliteStore(db_path)
            else:  # fallback: archivo JSON junto al .db previsto
                log.warning("sqlite3 no disponible: caché en JSON (%s.json)", db_path)
                self._store = _JsonStore(db_path.with_suffix(db_path.suffix + ".json"))

    @classmethod
    def from_config(cls, cfg: dict) -> "ApiCache":
        c = cfg.get("cache", {}) or {}
        return cls(
            db_path=Path(cfg["output"]["dir"]) / ".cache.db",
            ttl_seconds=int(c.get("ttl_seconds", 3600)),
            enabled=bool(c.get("enabled", False)),
        )

    def get(self, key: str) -> str | None:
        if not self.enabled or self._store is None:
            return None
        row = self._store.get(key)
        if not row:
            return None
        value, expires_at = row
        if time.time() > expires_at:
            self._store.delete(key)
            return None
        log.debug("cache hit: %s", key[:80])
        return value

    def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        if not self.enabled or self._store is None:
            return
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl
        self._store.set(key, value, time.time() + ttl)

    def clear(self) -> int:
        """Elimina todas las entradas. Devuelve cuántas había."""
        if not self.enabled or self._store is None:
            return 0
        return self._store.clear()

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None
