"""Tests de validación de configuración (spec 001, REQ-1.2)."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config_models import ReportsConfig, validate_config

VALID_CONFIG = {
    "company": {"name": "ACME", "unit": "Dev", "issued_by": "BI", "locale": "es"},
    "output": {"dir": "./output", "keep_last": 10},
    "gespro": {
        "enabled": True,
        "base_url": "https://gespro.example.com",
        "api_key_env": "REDMINE_API_KEY",
        "verify_ssl": True,
        "project_ids": [1, 304],
        "closed_status_names": ["cerrada"],
    },
    "gitlab": {
        "enabled": True,
        "base_url": "https://gitlab.example.com",
        "token_env": "GITLAB_TOKEN",
        "group": "equipo",
        "max_projects": 25,
        "stale_branch_days": 60,
    },
    "trends": {"enabled": True, "data_file": "trends/trends_data.json"},
    "delivery": {
        "email": {"enabled": False, "smtp_port": 587},
        "telegram": {"enabled": False},
    },
}


def test_config_valida_pasa():
    cfg = validate_config(copy.deepcopy(VALID_CONFIG))
    assert isinstance(cfg, ReportsConfig)
    assert cfg.company.name == "ACME"
    assert cfg.gitlab.max_projects == 25


def test_url_malformada_falla():
    bad = copy.deepcopy(VALID_CONFIG)
    bad["gitlab"]["base_url"] = "no-es-url"
    with pytest.raises(SystemExit) as exc:
        validate_config(bad)
    assert "gitlab.base_url" in str(exc.value)


def test_entero_negativo_falla():
    bad = copy.deepcopy(VALID_CONFIG)
    bad["output"]["keep_last"] = -1
    with pytest.raises(SystemExit) as exc:
        validate_config(bad)
    assert "output.keep_last" in str(exc.value)


def test_tipo_incorrecto_falla():
    bad = copy.deepcopy(VALID_CONFIG)
    bad["gitlab"]["max_projects"] = "veinticinco"
    with pytest.raises(SystemExit) as exc:
        validate_config(bad)
    assert "gitlab.max_projects" in str(exc.value)


def test_puerto_fuera_de_rango_falla():
    bad = copy.deepcopy(VALID_CONFIG)
    bad["delivery"]["email"]["smtp_port"] = 99999
    with pytest.raises(SystemExit) as exc:
        validate_config(bad)
    assert "smtp_port" in str(exc.value)


def test_logging_level_invalido_falla():
    bad = copy.deepcopy(VALID_CONFIG)
    bad["logging"] = {"level": "TRAZA"}
    with pytest.raises(SystemExit) as exc:
        validate_config(bad)
    assert "logging.level" in str(exc.value)


def test_errores_multiples_se_reportan_juntos():
    bad = copy.deepcopy(VALID_CONFIG)
    bad["gitlab"]["base_url"] = "ftp://x"
    bad["output"]["keep_last"] = 0
    with pytest.raises(SystemExit) as exc:
        validate_config(bad)
    msg = str(exc.value)
    assert "gitlab.base_url" in msg and "output.keep_last" in msg


def test_campos_opcionales_tienen_defaults():
    cfg = validate_config({"company": {"name": "ACME"}})
    assert cfg.output.keep_last == 10
    assert cfg.gitlab.enabled is True
    assert cfg.logging.level == "INFO"
