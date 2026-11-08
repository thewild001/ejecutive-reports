#!/usr/bin/env python3
"""
Boletín de tendencias tecnológicas — genérico y data-driven.
El contenido vive en trends/trends_data.json (editable por cualquier equipo);
este script solo lo maqueta en PDF (fpdf2 + DejaVu) y lo entrega.

Estructura del JSON:
{
  "periodo": "Quincena 1-15 septiembre 2026",
  "resumen_ejecutivo": "texto...",
  "secciones": [
    {"titulo": "Inteligencia Artificial",
     "items": [{"nombre": "...", "detalle": "...", "impacto": "alto|medio|bajo"}]}
  ]
}
"""
from __future__ import annotations

import datetime
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.settings import load_config, rotate_outputs, REPORTS_ROOT
from common.pdfbase import ReportPDF
from common.delivery import deliver, delivery_exit_code
from common.i18n import t as _t
from common.plugins import load_plugins, run_hook
from common.themes import get_theme

log = logging.getLogger(__name__)

EXIT_STALE_DATA = 5  # el JSON de datos supera trends.max_age_days

IMPACT_LABEL = {"alto": "ALTO", "medio": "MEDIO", "bajo": "BAJO"}


def build_pdf(data: dict, cfg: dict, out_path: Path) -> None:
    from trends.tech_trends_v2 import branding_from_config, build_report, is_v2_data

    if is_v2_data(data):
        build_report(data, out_path, branding_from_config(cfg))
        return

    loc = cfg["company"].get("locale", "es")
    pdf = ReportPDF(cfg["company"], cfg["trends"].get("header_title", "Vigilancia Tecnológica"),
                    theme=get_theme(cfg.get("ui", {}).get("theme")))
    pdf.cover(data.get("periodo", datetime.datetime.now().strftime("%B %Y")))

    pdf.add_page()
    pdf.section(_t("executive_summary", loc))
    resumen = (data.get("resumen_ejecutivo") or "").strip()
    pdf.para(resumen if resumen else "Datos no disponibles para el resumen de este período.")

    for sec in data.get("secciones", []):
        pdf.section(sec.get("titulo", "Sección"))
        for item in sec.get("items", []):
            impacto = IMPACT_LABEL.get((item.get("impacto") or "").lower(), "")
            titulo = item.get("nombre", "Sin título")
            pdf.card(titulo + (f"  [{impacto}]" if impacto else ""), item.get("detalle", ""))

    fuentes = data.get("fuentes") or []
    if fuentes:
        pdf.section(_t("sources", loc))
        for f in fuentes:
            pdf.bullet(str(f))

    pdf.output(str(out_path))


def main() -> int:
    cfg = load_config()
    t = cfg.get("trends", {})
    if not t.get("enabled"):
        log.info("Tendencias deshabilitado en config.yaml"); return 0

    data_path = Path(t.get("data_file", "trends/trends_data.json"))
    if not data_path.is_absolute():
        data_path = REPORTS_ROOT / data_path
    if not data_path.is_file():
        log.error("No existe el archivo de datos %s", data_path)
        log.error("Copia trends/trends_data.example.json a trends/trends_data.json y edítalo.")
        return 1

    max_age = int(t.get("max_age_days") or 0)
    if max_age:
        age_days = (datetime.datetime.now().timestamp() - data_path.stat().st_mtime) / 86400
        if age_days > max_age:
            log.error("Los datos de tendencias están desactualizados: %s tiene %.1f días "
                      "(máximo trends.max_age_days=%d). No se genera ni envía el boletín.",
                      data_path.name, age_days, max_age)
            return EXIT_STALE_DATA

    data = json.loads(data_path.read_text(encoding="utf-8"))

    out_dir = cfg["output"]["dir"]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    prefix = t.get("filename_prefix", "informe_tendencias")
    out_path = out_dir / f"{prefix}_{stamp}.pdf"
    build_pdf(data, cfg, out_path)
    log.info("PDF generado: %s", out_path)

    from common.exporters import export_rows
    rows = [[sec.get("titulo", ""), it.get("nombre", ""), it.get("impacto", "")]
            for sec in data.get("secciones", []) for it in sec.get("items", [])]
    created = export_rows(["Sección", "Tendencia", "Impacto"], rows, out_path,
                          cfg.get("export", {}).get("formats", ["pdf"]))
    plugins = load_plugins(cfg)
    run_hook(plugins, "post_export", "trends", [out_path, *created], cfg)
    exts = tuple(f".{f}" for f in cfg.get("export", {}).get("formats", ["pdf"]))
    rotate_outputs(out_dir, prefix, cfg["output"].get("keep_last", 10), exts=exts)

    results = deliver(out_path, cfg,
                      f"{t.get('header_title', 'Boletín de Tendencias')} — {data.get('periodo', '')}",
                      report_key="trends")
    return delivery_exit_code(results)


if __name__ == "__main__":
    raise SystemExit(main())
