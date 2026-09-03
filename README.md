# REPORTS — Suite de reportes ejecutivos automatizados

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
- **GitLab**: última actividad, ramas totales y *stale* (umbral configurable), issues
  abiertos, tasa de éxito de pipelines, alertas y recomendaciones (limpieza de ramas,
  CI deteriorado, proyectos inactivos).
- **Tendencias**: boletín editable desde `trends/trends_data.json` con resumen ejecutivo,
  secciones temáticas, etiquetas de impacto (alto/medio/bajo) y fuentes.

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

## Configuración (config.yaml)

- `company.*` — nombre, unidad y autoría que aparecen en portadas y pies de página.
- `gespro.project_ids` — lista de IDs de proyectos; **vacío = todos los visibles** con la API key.
- `gitlab.group` — grupo a analizar (ej. `fortes`); vacío = proyectos del token.
- `delivery.email` / `delivery.telegram` — entrega opcional por SMTP y/o bot de Telegram.
  Los secretos **nunca** van en config.yaml: solo el nombre de la variable de entorno.

## Seguridad

- `.env` nunca se versiona (ver `.gitignore` si incorporas a git).
- GitLab: token con scope `read_api` solamente.
- Redmine/GESPRO: clave API de una cuenta de solo lectura recomendada.

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
