# REPORTS — Suite de reportería ejecutiva automatizada

Tres reportes PDF profesionales, genéricos y configurables, para cualquier empresa
de desarrollo de software que use **GESPRO/Redmine** y **GitLab**:

| # | Reporte | Fuente de datos | Script |
|---|---------|-----------------|--------|
| 1 | Estado de proyectos | GESPRO / Redmine REST API | `gespro/gespro_report.py` |
| 2 | Salud de repositorios | GitLab REST API v4 | `gitlab/gitlab_report.py` |
| 3 | Tendencias tecnológicas | JSON editable (data-driven) | `trends/trends_report.py` |

## Qué incluye cada reporte

- **GESPRO/Redmine**: indicadores consolidados, tasa de cierre por proyecto, distribución
  de estados, carga de trabajo por miembro, detección de tareas vencidas, miembros sin
  asignación y sobrecargados, recomendaciones accionables automáticas.
  **Fase 2**: comparativa vs período anterior (creadas/cerradas con delta), velocidad
  del equipo (cerradas/semana), cuellos de botella por estado y miembros con carga
  creciente — todo computado desde las tareas ya recolectadas, sin llamadas extra.
- **GitLab**: última actividad, ramas totales y *stale* (umbral configurable), issues
  abiertos, tasa de éxito de pipelines, alertas y recomendaciones.
  **Fase 2**: Merge Requests (abiertos/mergeados, tasa de merge, tiempo medio de
  revisión), contribuidores activos vs inactivos y topics por proyecto
  (`gitlab.include_merge_requests`, ventana `gitlab.activity_days`).
- **Tendencias**: boletín editable desde `trends/trends_data.json` con resumen ejecutivo,
  secciones temáticas, etiquetas de impacto (alto/medio/bajo) y fuentes.
  **Fase 2**: `trends/rss_fetcher.py` genera un borrador (`trends/trends_draft.json`)
  desde los feeds de `trends.rss_feeds` para acelerar la redacción.

## Instalación

### Opción A — Local con uv (recomendada)

```bash
./install.sh          # crea .venv con uv y copia .env / trends_data.json de ejemplo
nano .env             # credenciales (REDMINE_API_KEY, GITLAB_TOKEN, SMTP, Telegram)
nano config.yaml      # empresa, URLs, proyectos, entrega
./run.sh gespro       # o: gitlab | trends | all
```

Requisito: Python ≥ 3.10 y fuentes DejaVu (`fonts-dejavu-core` en Debian/Ubuntu).
Si están en otra ruta, exporta `REPORTS_FONTS_DIR=/ruta/a/fonts`.

### Opción B — Docker / docker-compose

```bash
cp .env.example .env && $EDITOR .env
$EDITOR config.yaml
docker compose build
docker compose run --rm gespro     # o gitlab / trends
```

Los PDFs quedan en `./output/` (montado como volumen) con rotación automática
(`output.keep_last` en config.yaml).

## Programación

Ver `crontab.example` con variantes local y Docker.

Para el plan de endurecimiento de las ejecuciones programadas (observabilidad,
control de concurrencia, recuperación, verificación de artefactos y pruebas),
consulta [Plan de confiabilidad de ejecuciones programadas](docs/implementation/scheduled-execution-reliability-plan.md).
El documento define tareas y criterios de aceptación. En esta rama ya se implementó el registro inicial descrito a continuación.

### Registro de ejecuciones programadas (fase inicial)

Los wrappers de `scripts/` registran cada intento en un ledger SQLite local:
`output/.state/execution-ledger.sqlite3`. El directorio y la base se crean con
permisos restrictivos; el estado se conserva entre ejecuciones. Cada intento
recibe un `run_id`, y el wrapper lo exporta como `REPORTS_RUN_ID` para que los
generadores o futuras integraciones puedan correlacionar sus eventos.

Estados persistidos actualmente:

- `RUNNING`: intento registrado y todavía en ejecución.
- `SUCCEEDED`: el generador terminó con código 0.
- `FAILED`: el generador terminó con código distinto de 0.
- `SKIPPED_LOCKED`: otra instancia tenía el lock; el wrapper termina con código 75.
- `INTERRUPTED`: el wrapper recibió INT, TERM o HUP.

El ledger almacena inicio/fin UTC, duración, reporte, PID, host, ruta del log y
código de salida. Los errores de ejecución se resumen también en stderr para
que cron pueda notificarlos mediante `MAILTO`. El log detallado permanece en
`logs/<reporte>.log`.

Variables adicionales:

- `REPORTS_STATE_DB`: ruta opcional para cambiar la ubicación del SQLite.
- `REPORTS_RUN_ID`: identificador generado por el wrapper y exportado al proceso
  Python del reporte (no debe establecerse manualmente).

**Límites actuales:** no existe todavía una interfaz de consulta/health, recuperación
automática de registros `RUNNING` abandonados, timeout, política de reintentos,
verificación de PDF ni garantía de coordinación multi-host. El ledger y `flock`
son locales; no se debe ubicar la base en NFS ni compartirla entre hosts.

## Configuración (config.yaml)

- `company.*` — nombre, unidad y autoría que aparecen en portadas y pies de página.
- `gespro.project_ids` — lista de IDs de proyectos; **vacío = todos los visibles** con la API key.
- `gitlab.group` — grupo a analizar (ej. `fortes`); vacío = proyectos del token.
- `delivery.email` / `delivery.telegram` — entrega opcional por SMTP y/o bot de Telegram.
  Los secretos **nunca** van en config.yaml: solo el nombre de la variable de entorno.

## Seguridad

- `.env` nunca se versiona (ver `.gitignore` si incorporas a git).
- **Permisos mínimos por token:**
  - GitLab: token con scope `read_api` solamente.
  - Redmine/GESPRO: clave API de una cuenta de solo lectura recomendada.
  - SMTP: cuenta dedicada de envío, sin buzón de usuario.
  - Telegram: bot dedicado, chat_id de canal/grupo de reportes.
- `verify_ssl: true` es el default recomendado. Solo desactívalo si tu CA
  interna no está en el trust store del sistema — en ese caso evalúa añadir
  el certificado CA al sistema en lugar de deshabilitar la verificación.
- Los errores de API reportan método, ruta y código HTTP, nunca headers
  (donde viajan los tokens).
- Los logs (sección `logging` en config.yaml) nunca registran claves,
  tokens ni contraseñas.

## Robustez (Fase 1)

- La configuración se valida al arrancar (Pydantic): errores de tipo, URLs
  malformadas o valores fuera de rango abortan con un listado claro **antes**
  de cualquier llamada de red.
- Las llamadas HTTP reintentan automáticamente errores transitorios
  (5xx, red, timeout) con backoff exponencial (3 intentos). Los errores 4xx
  fallan de inmediato.
- Timeout configurable por fuente: `gespro.timeout_seconds` /
  `gitlab.timeout_seconds` (default 30).
- Logging estructurado a consola y, opcionalmente, a archivo rotativo:
  `logging.file: "output/reports.log"`.
- Tests: `pytest` (instala deps de desarrollo con `uv sync` o
  `pip install pytest`).

## Métricas enriquecidas (Fase 2)

- **GESPRO**: `gespro.previous_period_days` (default 30) define la ventana de la
  comparativa creadas/cerradas vs período anterior, la velocidad del equipo y la
  detección de carga creciente por miembro. Los cuellos de botella se detectan
  cuando un estado abierto concentra ≥ 40 % de las tareas abiertas del proyecto.
- **GitLab**: `gitlab.include_merge_requests: false` desactiva las llamadas de
  métricas Fase 2 (MRs, contribuidores) si la instancia es muy grande o el token
  tiene acceso limitado. `gitlab.activity_days` (default 90) fija la ventana.
- **Tendencias RSS**: define `trends.rss_feeds` (lista de URLs RSS/Atom) y ejecuta:

  ```bash
  python trends/rss_fetcher.py
  ```

  Genera `trends/trends_draft.json` con la estructura de `trends_data.json`
  (una sección por feed, `impacto` por definir) para edición humana. Los feeds
  se descargan con el cliente HTTP con retry/timeout y se parsean con la stdlib
  (`xml.etree.ElementTree`) — sin dependencias nuevas.

## Performance y exports (Fase 3)

- **Caché de API** (`cache.enabled: true`): las respuestas GET exitosas se
  guardan en `output/.cache.db` (SQLite; si el intérprete no trae `_sqlite3`,
  degrada automáticamente a JSON) con TTL de `cache.ttl_seconds` (def. 1 h).
  La segunda ejecución reutiliza respuestas — los hits se ven con
  `logging.level: DEBUG`. Los errores nunca se cachean.
- **Paralelismo** (`execution.max_workers`, def. 4): los proyectos de GESPRO y
  GitLab se analizan en paralelo con `concurrent.futures` preservando el orden
  en el PDF. `max_workers: 1` = comportamiento secuencial clásico.
- **Exports** (`export.formats`): además del PDF puedes generar `csv`, `json`
  y `xlsx` (requiere `openpyxl`; si falta, se omite con warning) con las tablas
  de resumen. La rotación `output.keep_last` aplica a todos los formatos.
- **Snapshot incremental ligero**: cada reporte guarda
  `output/.snapshot_<prefijo>.json` con sus métricas clave y el resumen
  ejecutivo muestra los deltas vs la ejecución anterior (↑/↓ por proyecto).

## UX y extensibilidad (Fase 4)

- **CLI** (Typer): `./run.sh` sigue funcionando, pero ahora también puedes usar

  ```bash
  python cli.py run all --force --workers 8 --format csv,json
  python cli.py validate      # verifica config + variables de entorno
  python cli.py cache clear   # vacía la caché de API
  python cli.py rss-draft     # borrador de tendencias desde RSS
  ```

- **Temas del PDF** (`ui.theme`): `corporativo` (default, paleta actual),
  `minimal` (monocromo) y `ejecutivo` (azul marino/acer). Sin cambio visual
  con el default.
- **i18n**: `company.locale: "es" | "en"` traduce títulos de sección y
  cabeceras de tabla (catálogos en `locales/*.yaml`; el contenido dinámico
  no se traduce).
- **Plugins**: módulos Python en `plugins/` habilitados en
  `plugins.enabled`. Hooks: `post_collect(report, rows, cfg)` (puede
  transformar filas) y `post_export(report, paths, cfg)`. Ejemplo incluido:
  `plugins/logfile.py`. Un plugin que falla solo deja warning en el log.
- **Dashboard web opcional** (FastAPI, fuera del crontab; requiere `pip install .[web]`):
  
  ```bash
  uvicorn web.app:app --port 8080
  ```

  KPI de tareas (Redmine) y repositorios (GitLab) con filtros, mapa de salud,
  tendencias y descarga de informes. Lee los datos que deja cada ejecución del cron.

## Estructura

```
REPORTS/
├── config.yaml / .env / pyproject.toml / requirements.txt
├── Dockerfile / docker-compose.yml / install.sh / run.sh / crontab.example
├── common/            # settings, base PDF (fpdf2+DejaVu), delivery (SMTP/Telegram)
├── gespro/            # reporte Redmine/GESPRO
├── gitlab/            # reporte GitLab
├── trends/            # boletín de tendencias + trends_data.json
└── output/            # PDFs generados
```

Generado por el Grupo de Inteligencia Empresarial — FORTES/UCI.
