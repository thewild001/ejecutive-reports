"""Tests de helpers puros de common/settings.py (spec 001, REQ-1.5)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.settings import load_dotenv, require_env, rotate_outputs


def test_require_env_devuelve_valor(monkeypatch):
    monkeypatch.setenv("REPORTS_TEST_KEY", "secreto")
    assert require_env("REPORTS_TEST_KEY", "prueba") == "secreto"


def test_require_env_falla_si_vacia(monkeypatch):
    monkeypatch.delenv("REPORTS_TEST_MISSING", raising=False)
    with pytest.raises(SystemExit) as exc:
        require_env("REPORTS_TEST_MISSING", "prueba")
    assert "REPORTS_TEST_MISSING" in str(exc.value)


def test_load_dotenv_no_sobrescribe_existente(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CLAVE_A=de_archivo\nCLAVE_B=de_archivo\n")
    monkeypatch.setenv("CLAVE_A", "de_entorno")
    monkeypatch.delenv("CLAVE_B", raising=False)
    load_dotenv(env_file)
    import os

    assert os.environ["CLAVE_A"] == "de_entorno"
    assert os.environ["CLAVE_B"] == "de_archivo"


def test_rotate_outputs_conserva_keep_ultimos(tmp_path):
    for i in range(15):
        (tmp_path / f"informe_2024010{i:02d}.pdf").write_bytes(b"%PDF")
    rotate_outputs(tmp_path, "informe", keep=10)
    restantes = list(tmp_path.glob("informe_*.pdf"))
    assert len(restantes) == 9  # keep-1 vigentes + el recién generado fuera del test = 9 aquí


def test_rotate_outputs_ignora_otros_prefijos(tmp_path):
    (tmp_path / "otro_2024.pdf").write_bytes(b"%PDF")
    rotate_outputs(tmp_path, "informe", keep=10)
    assert (tmp_path / "otro_2024.pdf").exists()
