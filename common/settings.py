"""Common helpers: configuration loading, environment variables."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

REPORTS_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE, # comments). Does not override existing env."""
    env_path = path or REPORTS_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(config_path: str | None = None) -> dict:
    load_dotenv()
    cfg_path = Path(config_path) if config_path else REPORTS_ROOT / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = REPORTS_ROOT
    out_dir = Path(cfg.get("output", {}).get("dir", "./output"))
    if not out_dir.is_absolute():
        out_dir = REPORTS_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg["output"]["dir"] = out_dir
    return cfg


def require_env(name: str, purpose: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"ERROR: falta la variable de entorno {name} ({purpose}). "
            f"Defínela en REPORTS/.env o expórtala antes de ejecutar."
        )
    return value


def rotate_outputs(out_dir: Path, prefix: str, keep: int = 10) -> None:
    files = sorted(out_dir.glob(f"{prefix}_*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep - 1:]:
        old.unlink(missing_ok=True)
