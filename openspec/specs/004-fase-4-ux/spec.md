# Spec — Fase 4: UX y Extensibilidad

> Delta spec derivado del Plan de Implementación por Fases (Fase 4, Semana 7-8).
> Constitution: `openspec/memory/constitution.md`. Dependencias pre-aprobadas:
> Typer (CLI), Jinja2 (web), gettext/YAML (i18n).
>
> **Desviación documentada**: el plan maestro proponía "templates Jinja2 para
> la estructura del PDF". El render PDF es imperativo (fpdf2); portarlo a
> plantillas sería un refactor profundo sin beneficio proporcional. En su
> lugar se implementan **temas** (paleta/fuentes por config) y Jinja2 se usa
> donde encaja naturalmente: el dashboard web.

## ADDED Requirements

### R4.1 — CLI con Typer

**ADDED** Un `cli.py` en la raíz DEBE exponer:

- `python cli.py run gespro|gitlab|trends|all [--verbose] [--force] [--workers N] [--format csv,json]`
- `python cli.py validate` — valida config.yaml y variables de entorno sin ejecutar
- `python cli.py cache clear` — vacía la caché de API
- `python cli.py rss-draft` — alias de trends/rss_fetcher
- `python cli.py init` — asistente mínimo: copia .env.example y muestra qué falta
- Entry point `reports` en pyproject (`[project.scripts]`).
- `--force` desactiva la caché para esa ejecución; `--verbose` sube el log a DEBUG.

Escenario: los scripts del crontab (`run.sh`) siguen funcionando sin cambios.

### R4.2 — Temas del PDF

**ADDED** `common/themes.py` DEBE definir al menos 3 temas:
`corporativo` (paleta actual INK/GOLD, default — pixel-idéntico a hoy),
`minimal` (monocromo) y `ejecutivo` (tinta oscura + acento azul).

`ReportPDF` acepta `theme: dict | None`; con None usa el tema corporativo,
sin cambio visual respecto a la versión anterior. Selección vía `ui.theme`
en config.yaml. Tema desconocido → error claro en validación.

### R4.3 — Internacionalización (i18n)

**ADDED** `common/i18n.py` DEBE ofrecer `t(key, locale)` con:

- Catálogos YAML en `locales/es.yaml` y `locales/en.yaml`.
- Fallback: clave ausente en el locale pedido → español; ausente en ambos →
  la propia clave (con warning).
- Cubre títulos de sección y cabeceras de tabla de los 3 reportes.
  El contenido dinámico (nombres de proyectos, fuentes) NO se traduce.
- `company.locale` (ya existe: es|en) selecciona el idioma.

### R4.4 — Sistema de plugins

**ADDED** `common/plugins.py` DEBE cargar módulos Python desde `plugins/`
cuando estén listados en `plugins.enabled` (config.yaml) y DEBE invocar dos
hooks si existen:

- `post_collect(report_type: str, rows: list, cfg: dict) -> list | None`
  — puede transformar/filtrar las filas antes del render.
- `post_export(report_type: str, paths: list[Path], cfg: dict) -> None`
  — se ejecuta tras generar todos los formatos.

Un plugin con error DEBE loggear el fallo y NO romper el reporte.
Debe existir al menos un plugin de ejemplo funcional (`plugins/logfile.py`).

### R4.5 — Dashboard web mínimo

**ADDED** `web/app.py` (FastAPI + Jinja2) DEBE:

- Listar los últimos archivos por tipo de reporte (PDF + exports) con enlace
  de descarga.
- Mostrar las métricas del último snapshot de cada reporte.
- Servirse manualmente (`uvicorn web.app:app --port …`); no forma parte del
  crontab ni es obligatorio para la suite.

## Fuera de scope

- Auto-completado de shell de Typer (documentado como posibilidad).
- Autenticación en el dashboard (red interna, herramienta opcional).
