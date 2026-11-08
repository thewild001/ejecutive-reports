# Spec — Fase 2: Enriquecimiento de Métricas

> Delta spec derivado del Plan de Implementación por Fases (Fase 2, Semana 3-4).
> Constitution de referencia: `openspec/memory/constitution.md`.
> Sin nuevas dependencias: RSS vía stdlib (`httpx` + `xml.etree.ElementTree`).

## ADDED Requirements

### R2.1 — GitLab: métricas de merge requests y actividad

**ADDED** El reporte GitLab DEBE incluir, por proyecto, métricas de Merge Requests
cuando `gitlab.include_merge_requests` sea true (default):

- MRs abiertos y mergeados en la ventana `gitlab.activity_days` (default 90 días).
- Tasa de merge (`merged / (merged + closed)` en la ventana, %).
- Tiempo promedio de revisión en días (`merged_at - created_at` de MRs mergeados).
- Actividad de contribuidores en la ventana: commits y autores activos vs.
  contribuidores históricos totales.
- Topics/etiquetas del proyecto (sin llamada extra: vienen en el objeto proyecto).

Escenario: si la API deniega o falla cualquiera de estas llamadas, el reporte
DEBE registrar `log.warning` y omitir la sección sin fallar el PDF completo.

### R2.2 — GESPRO: comparativa con período anterior

**ADDED** El reporte GESPRO DEBE mostrar, por proyecto, una comparativa entre
la ventana actual y la ventana anterior de `gespro.previous_period_days`
(default 30 días), computada desde los campos `created_on`/`closed_on` de las
tareas ya recolectadas (sin llamadas extra):

- Tareas creadas y cerradas en la ventana actual vs. la anterior, con delta (↑↓).
- Velocidad del equipo: tareas cerradas por semana en la ventana actual.
- Cuellos de botella: estados abiertos que concentran ≥ 40 % de las tareas
  abiertas del proyecto.
- Miembros con carga creciente: abiertas actuales > cerradas en la ventana.

Escenario: si las tareas no incluyen `created_on`/`closed_on` parseables,
la sección DEBE indicar "Datos no disponibles" en lugar de fallar.

### R2.3 — Trends: borrador automatizado desde RSS

**ADDED** Un nuevo script `trends/rss_fetcher.py` DEBE:

- Leer `trends.rss_feeds` (lista de URLs RSS 2.0 / Atom) desde config.yaml.
- Descargar cada feed con el cliente HTTP robusto de Fase 1 (retry + timeouts).
- Parsear items (título, enlace, resumen, fecha) con `xml.etree.ElementTree`,
  tolerando items malformados (se omiten con `log.warning`).
- Generar `trends/trends_draft.json` con la estructura exacta de
  `trends_data.json` (una sección por feed, items como pendientes de redacción,
  `impacto` vacío) para edición humana posterior.
- Ejecutarse como script independiente (`python trends/rss_fetcher.py`) sin
  modificar ni generar el PDF.

Escenario: feeds vacíos o todos fallidos → exit code 1 con mensaje claro.

### R2.4 — Métricas cruzadas GESPRO↔GitLab (opcional)

**ADDED (condicional)** Si existe una correlación de nombres derivable de
config.yaml entre proyectos GESPRO y repositorios GitLab, DEBE generarse al
menos un insight cruzado (mucho código/pocas tareas o viceversa).
[NEEDS CLARIFICATION]: no existe hoy convención de matching entre sistemas;
si no es derivable de config, este requisito queda pospuesto a una fase futura
y el gap queda documentado aquí.

## Fuera de scope (Fase 2)

- Caché de API, paralelismo, exporters (Fase 3).
- CLI Typer, plugins, i18n, templates (Fase 4).
