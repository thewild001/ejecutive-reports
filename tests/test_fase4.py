"""Tests de Fase 4: temas, i18n y plugins (sin red)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.i18n import t
from common.plugins import load_plugins, run_hook
from common.themes import THEMES, get_theme


# ── themes ───────────────────────────────────────────────────────────────

def test_themes_complete_palettes():
    for name, palette in THEMES.items():
        assert set(palette) == {"ink", "accent", "gray", "light", "white"}, name
        for key, rgb in palette.items():
            assert len(rgb) == 3 and all(0 <= c <= 255 for c in rgb)


def test_get_theme_default_and_unknown():
    assert get_theme(None) == THEMES["corporativo"]
    try:
        get_theme("psicodélico")
    except SystemExit as e:
        assert "tema desconocido" in str(e)
    else:
        raise AssertionError("debió lanzar SystemExit")


def test_pdf_with_theme_param():
    """ReportPDF acepta tema sin romper el constructor."""
    from common.pdfbase import ReportPDF
    pdf = ReportPDF({"name": "X", "unit": "Y"}, "Test", theme=get_theme("minimal"))
    assert pdf._theme["accent"] == (17, 17, 17)
    pdf_default = ReportPDF({"name": "X"}, "Test")
    assert pdf_default._theme["accent"] == THEMES["corporativo"]["accent"]


# ── i18n ─────────────────────────────────────────────────────────────────

def test_i18n_es_en_and_fallback():
    assert t("executive_summary", "es") == "Resumen ejecutivo"
    assert t("executive_summary", "en") == "Executive summary"
    # clave inexistente: fallback a la propia clave
    assert t("__no_existe__", "en") == "__no_existe__"
    # locale desconocido cae a español
    assert t("col_project", "fr") == "Proyecto"


# ── plugins ──────────────────────────────────────────────────────────────

def test_plugin_load_and_hooks(tmp_path: Path, monkeypatch):
    import common.plugins as pl
    mod_dir = tmp_path / "plugins"
    monkeypatch.setattr(pl, "PLUGINS_DIR", mod_dir)
    mod_dir.mkdir()
    (mod_dir / "eco.py").write_text(
        "def post_collect(report_type, rows, cfg):\n"
        "    return [r for r in rows if r != 'drop']\n"
        "def post_export(report_type, paths, cfg):\n"
        "    paths.append('touch')\n",
        encoding="utf-8",
    )
    (mod_dir / "roto.py").write_text("raise RuntimeError('boom')", encoding="utf-8")

    mods = load_plugins({"plugins": {"enabled": ["eco", "roto", "fantasma"]}})
    assert len(mods) == 1  # roto y fantasma se omiten sin romper

    rows = ["keep", "drop"]
    results = run_hook(mods, "post_collect", "gitlab", rows, {})
    assert results == [["keep"]]

    paths = ["a.pdf"]
    run_hook(mods, "post_export", "gitlab", paths, {})
    assert paths == ["a.pdf", "touch"]
