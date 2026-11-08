"""Genericidad: el código reutilizable no debe llevar datos de una organización concreta.

La identidad (empresa, hosts, destinatarios, rutas) vive en config.yaml/.env. Esta
lista de archivos crece a medida que se migran los generadores heredados; los que
aún no están aquí (gitlab/ y gespro/ heredados) tienen literales pendientes.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Patrones que delatan una organización/host/ruta concretos dentro del código.
FORBIDDEN = re.compile(r"fortes|uci\.cu|sigies|akademos|xetid|/home/[a-z]|\.hermes", re.IGNORECASE)

CLEAN = [
    *sorted((ROOT / "common").glob("*.py")),
    ROOT / "trends" / "tech_trends_v2.py",
    ROOT / "trends" / "trends_report.py",
    ROOT / "trends" / "rss_fetcher.py",
    ROOT / "cli.py",
    ROOT / "run.sh",
    *sorted((ROOT / "scripts").glob("*.sh")),
]


def test_archivos_genericos_sin_literales_de_organizacion():
    offenders = []
    for path in CLEAN:
        if not path.is_file():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    assert not offenders, "Literales de organización en código genérico:\n" + "\n".join(offenders)


def test_no_hay_credenciales_en_el_codigo():
    secret = re.compile(r"""(PASS|PASSWORD|TOKEN|SECRET|API_KEY)\w*\s*=\s*["'][^"'\s]{6,}["']""")
    allowed = {"tests"}
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in allowed or ".venv" in rel.parts or ".git" in rel.parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().startswith("export ") or not secret.search(line):
                continue  # `export VAR="..."` en un docstring de uso es documentación
            offenders.append(f"{rel}:{n}")
    assert not offenders, "Posibles credenciales en el código: " + ", ".join(offenders)
