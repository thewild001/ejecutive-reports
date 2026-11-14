# gitlab-mcp

Servidor MCP (Model Context Protocol) para analizar y consultar cualquier instancia GitLab (SaaS o self-managed): proyectos, pipelines, ramas, merge requests, issues, colaboradores y salud de grupos. Transporte `stdio` (default), `sse` o `streamable-http` vía flags CLI. Misma estructura que `gespro-mcp`.

## Requisitos

- Python >= 3.10
- Una instancia GitLab accesible y un access token con scope `read_api`

## Quickstart

```bash
cp .env.example .env
# editar .env con GITLAB_URL y GITLAB_TOKEN reales
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
./run-mcp.sh
```

Sin `uv`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, o `pip install -r requirements.txt` + `python3 main.py`.

## Configuración del cliente MCP (stdio)

```json
{
  "mcpServers": {
    "gitlab-mcp": {
      "command": "python",
      "args": ["/ruta/absoluta/a/gitlab-mcp/main.py"],
      "env": {
        "GITLAB_URL": "https://gitlab.example.com",
        "GITLAB_TOKEN": "tu-token"
      }
    }
  }
}
```

Ver también `mcp.json.example`.

## Variables de entorno

| Variable | Defecto | Uso |
|----------|---------|-----|
| `GITLAB_URL` | `https://gitlab.com` | URL base de la instancia |
| `GITLAB_TOKEN` | — (obligatoria) | Token con scope `read_api` |
| `GITLAB_VERIFY_SSL` | `true` | `false` solo con certificados autofirmados |
| `GITLAB_TIMEOUT` | `30.0` | Timeout HTTP en segundos |
| `GITLAB_DEFAULT_LIMIT` | `50` | Límite por defecto en listados/búsquedas |
| `GITLAB_PROJECT_FILTER` | vacío | ids, rutas de proyecto o de grupo permitidos (coma) |
| `REDIS_URL` / `REDIS_TTL` | vacío / `300` | Caché opcional |

## Herramientas MCP

### Consulta básica

`list_projects`, `get_project`, `get_project_members`, `search_issues`.

### Analítica

| Tool | Uso |
|------|-----|
| `reporte_salud_proyecto` | Puntuación de salud: ramas, issues, MRs, últimos commits |
| `analizar_rendimiento_pipelines` | Éxito/fallos y duración de pipelines |
| `analizar_merge_requests` | Mergeados/abiertos, tiempo a merge, autores |
| `analizar_tiempo_revision_mr` | Tiempos de revisión de MRs |
| `analizar_colaboradores_activos` | Commits por colaborador en una ventana de `days` |
| `analizar_distribucion_codigo_y_silos` | Factor bus, HHI, concentración por autor |
| `analizar_tendencia_contribuciones` | Serie mensual de commits |
| `obtener_patrones_horarios_commits` | Franjas horarias y días de la semana |
| `ranking_contribuciones_proyecto` | Ranking de contribuidores |
| `analizar_ciclo_vida_issues` | Ciclo de vida de issues |
| `detectar_ramas_stale` | Ramas sin actividad > `days_threshold` |
| `analizar_grupo_salud` | Panorama de un grupo y sus subgrupos |
| `analizar_vision_general` | Visión general de proyectos accesibles |

## Docker

```bash
docker compose up -d --build
docker exec -i gitlab-mcp python3 main.py
```

## Uso desde la suite de reportes

`gitlab/gitlab_report.py` lanza este servidor por stdio (`mcp/gitlab-mcp/main.py`) y parsea la salida de las tools de analítica. Si cambias el formato de texto de esas tools, ajusta los parsers de `gitlab/portfolio_report.py`.

## Seguridad

- `.env` y `.venv/` están en `.gitignore`: no los subas al repositorio.
- El token nunca se registra en logs (stderr).
