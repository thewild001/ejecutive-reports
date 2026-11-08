# Spec — Fase 3: Performance y Escalabilidad

> Delta spec derivado del Plan de Implementación por Fases (Fase 3, Semana 5-6).
> Constitution: `openspec/memory/constitution.md`. Dependencias aprobadas:
> `sqlite3` (stdlib), `concurrent.futures` (stdlib), `openpyxl` (opcional).

## ADDED Requirements

### R3.1 — Caché de respuestas de API

**ADDED** Un módulo `common/cache.py` DEBE ofrecer caché persistente en
SQLite (archivo `output/.cache.db`) con:

- `get(key) -> str | None` — devuelve el valor solo si no expiró su TTL.
- `set(key, value, ttl_seconds)` — upsert con timestamp.
- TTL configurable por `cache.ttl_seconds` en config.yaml (default 3600).
- `cache.enabled: false` (o ausente) DEBE desactivar la caché por completo
  (comportamiento actual, sin lecturas ni escrituras).
- `clear()` para invalidación completa (foreground CLI futuro).

Escenario: `checked_json` cachea respuestas GET exitosas por
`sha1(path + params)`. Los errores NUNCA se cachean. Cada hit se loggea
en nivel DEBUG.

### R3.2 — Ejecución paralela de proyectos

**ADDED** Los reportes GESPRO y GitLab DEBEN procesar proyectos en paralelo
con `concurrent.futures.ThreadPoolExecutor`:

- `execution.max_workers` en config.yaml (default 4, rango 1-16).
- `max_workers: 1` → ejecución secuencial idéntica a la actual.
- El orden de los proyectos en el PDF DEBE preservarse respecto al orden
  de entrada (se usa `executor.map`).
- Un fallo en un proyecto NO cancela los demás: se loggea y se omite
  ese proyecto (mismo criterio de degradación de Fases 1-2).

### R3.3 — Export a formatos alternativos

**ADDED** Un módulo `common/exporters.py` DEBE soportar:

- `export_rows(rows, out_path_base, formats) -> list[Path]` — genera los
  formatos pedidos en `export.formats` (default `["pdf"]`).
- **CSV**: stdlib `csv`, UTF-8, cabeceras incluidas.
- **JSON**: `json.dumps` con `ensure_ascii=False, indent=2`.
- **Excel (.xlsx)**: solo si `openpyxl` está instalado; si se pide y falta,
  `log.warning` y se omite sin fallar (dependencia opcional).
- Rotación: `rotate_outputs` aplica también a exports con el mismo prefijo.

### R3.4 — Snapshot de métricas (incremental ligero)

**ADDED** Cada reporte DEBE guardar `output/.snapshot_<prefix>.json` con las
métricas clave de la ejecución (totales por proyecto) y, si existe snapshot
previo, el resumen ejecutivo DEBE mencionar los deltas principales
(ej. issues abiertos, MRs, salud media).

**Nota de scope**: el plan maestro pedía "incremental reports" completos
(PDF delta). Esta spec implementa el detector de cambios ligero; el PDF-delta
completo queda como trabajo futuro si resulta necesario.

## Fuera de scope (Fase 3)

- CLI Typer, plugins, dashboard, i18n, templates (Fase 4).
