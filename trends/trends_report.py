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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.settings import load_config, rotate_outputs, REPORTS_ROOT
from common.pdfbase import ReportPDF
from common.delivery import deliver

IMPACT_LABEL = {"alto": "ALTO", "medio": "MEDIO", "bajo": "BAJO"}


def build_pdf(data: dict, cfg: dict, out_path: Path) -> None:
    pdf = ReportPDF(cfg["company"], cfg["trends"].get("header_title", "Vigilancia Tecnológica"))
    pdf.cover(data.get("periodo", datetime.datetime.now().strftime("%B %Y")))

    pdf.add_page()
    pdf.section("Resumen ejecutivo")
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
        pdf.section("Fuentes consultadas")
        for f in fuentes:
            pdf.bullet(str(f))

    pdf.output(str(out_path))


def main() -> int:
    cfg = load_config()
    t = cfg.get("trends", {})
    if not t.get("enabled"):
        print("Tendencias deshabilitado en config.yaml"); return 0

    data_path = Path(t.get("data_file", "trends/trends_data.json"))
    if not data_path.is_absolute():
        data_path = REPORTS_ROOT / data_path
    if not data_path.is_file():
        print(f"ERROR: no existe el archivo de datos {data_path}")
        print("Copia trends/trends_data.example.json a trends/trends_data.json y edítalo.")
        return 1

    data = json.loads(data_path.read_text(encoding="utf-8"))

    out_dir = cfg["output"]["dir"]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    prefix = t.get("filename_prefix", "informe_tendencias")
    out_path = out_dir / f"{prefix}_{stamp}.pdf"
    build_pdf(data, cfg, out_path)
    rotate_outputs(out_dir, prefix, cfg["output"].get("keep_last", 10))
    print(f"PDF generado: {out_path}")

    deliver(out_path, cfg, f"{t.get('header_title', 'Boletín de Tendencias')} — {data.get('periodo', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
