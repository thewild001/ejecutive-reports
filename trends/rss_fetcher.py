#!/usr/bin/env python3
"""
Trends — Genera un borrador de boletín desde feeds RSS/Atom (Fase 2).

Lee trends.rss_feeds de config.yaml, descarga cada feed con el cliente HTTP
robusto (retry + timeout) y escribe trends/trends_draft.json con la estructura
de trends_data.json, listo para edición humana. No genera ni entrega PDF.
"""
from __future__ import annotations

import datetime
import json
import logging
import sys
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.settings import load_config, REPORTS_ROOT
from common.http_client import build_client

log = logging.getLogger(__name__)

_ATOM = "{http://www.w3.org/2005/Atom}"
_MAX_ITEMS_PER_FEED = 8


def fetch_feed(client, url: str) -> bytes | None:
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content
    except Exception as e:  # httpx errors ya reintentados por el client
        log.warning("Feed no disponible %s: %s", url, e)
        return None


def parse_feed(raw: bytes, source_url: str) -> dict | None:
    """Parsea RSS 2.0 o Atom a {'titulo', 'items': [{nombre, detalle, fecha, enlace}]}.
    Items malformados se omiten con warning."""
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as e:
        log.warning("XML inválido en %s: %s", source_url, e)
        return None

    if root.tag == f"{_ATOM}feed":  # Atom
        title = (root.findtext(f"{_ATOM}title") or source_url).strip()
        items = []
        for entry in root.findall(f"{_ATOM}entry")[:_MAX_ITEMS_PER_FEED]:
            nombre = (entry.findtext(f"{_ATOM}title") or "").strip()
            if not nombre:
                log.warning("Item sin título omitido en %s", source_url)
                continue
            link_el = entry.find(f"{_ATOM}link")
            items.append({
                "nombre": nombre,
                "detalle": (entry.findtext(f"{_ATOM}summary")
                            or entry.findtext(f"{_ATOM}content") or "").strip()[:400],
                "fecha": (entry.findtext(f"{_ATOM}updated")
                          or entry.findtext(f"{_ATOM}published") or "")[:10],
                "enlace": link_el.get("href", "") if link_el is not None else "",
            })
        return {"titulo": title, "items": items}

    channel = root.find("channel")  # RSS 2.0
    if channel is None:
        log.warning("Formato no reconocido (ni RSS ni Atom) en %s", source_url)
        return None
    title = (channel.findtext("title") or source_url).strip()
    items = []
    for item in channel.findall("item")[:_MAX_ITEMS_PER_FEED]:
        nombre = (item.findtext("title") or "").strip()
        if not nombre:
            log.warning("Item sin título omitido en %s", source_url)
            continue
        items.append({
            "nombre": nombre,
            "detalle": (item.findtext("description") or "").strip()[:400],
            "fecha": (item.findtext("pubDate") or "")[:16],
            "enlace": (item.findtext("link") or "").strip(),
        })
    return {"titulo": title, "items": items}


def build_draft(feeds: list[dict], urls: list[str]) -> dict:
    """Estructura idéntica a trends_data.json, con impacto por definir."""
    hoy = datetime.date.today()
    return {
        "periodo": f"Borrador generado el {hoy.isoformat()}",
        "resumen_ejecutivo": "[Por redactar a partir de las secciones generadas]",
        "secciones": [
            {
                "titulo": f["titulo"],
                "items": [
                    {"nombre": it["nombre"],
                     "detalle": f"{it['detalle']} ({it['enlace']})".strip(),
                     "impacto": "",
                     "fecha": it["fecha"]}
                    for it in f["items"]
                ],
            }
            for f in feeds if f["items"]
        ],
        "fuentes": urls,
    }


def main() -> int:
    cfg = load_config()
    t = cfg.get("trends", {})
    urls = [u for u in (t.get("rss_feeds") or []) if u]
    if not urls:
        log.error("No hay feeds configurados: define trends.rss_feeds en config.yaml")
        return 1

    tcfg = cfg.get("gitlab", {})  # reutiliza verify_ssl/timeout de la instancia interna
    client = build_client(
        "",
        verify_ssl=t.get("verify_ssl", tcfg.get("verify_ssl", False)),
        timeout=float(t.get("timeout_seconds", 30)),
        follow_redirects=True,  # los feeds RSS suelen responder con redirecciones
    )

    feeds, ok_urls = [], []
    for url in urls:
        if (raw := fetch_feed(client, url)) and (parsed := parse_feed(raw, url)):
            feeds.append(parsed)
            ok_urls.append(url)

    if not feeds:
        log.error("Ningún feed se pudo procesar (%d intentados)", len(urls))
        return 1

    draft = build_draft(feeds, ok_urls)
    out_path = REPORTS_ROOT / "trends" / "trends_draft.json"
    out_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    log.info("Borrador generado en %s (%d secciones)", out_path,
             len(draft["secciones"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
