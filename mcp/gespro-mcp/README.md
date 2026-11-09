# gespro-mcp

Servidor MCP (Model Context Protocol) para consultar cualquier instancia Redmine compatible con GESPRO: proyectos, miembros, tareas y estados. Transporte `stdio` (default), `sse` o `streamable-http` vía flags CLI.

## Requisitos

- Python >= 3.10
- Una instancia Redmine accesible y una clave API de usuario

## Quickstart

```bash
cp .env.example .env
# editar .env con GESPRO_URL y GESPRO_API_KEY reales
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
./run-mcp.sh
```

Sin `uv`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, o `pip install -r requirements.txt` + `python3 main.py`.

## Configuración del cliente MCP (stdio)

Ejemplo para el archivo de configuración de tu cliente MCP:

```json
{
  "mcpServers": {
    "gespro-mcp": {
      "command": "python",
      "args": ["/ruta/absoluta/a/gespro-mcp/main.py"],
      "env": {
        "GESPRO_URL": "https://tu-redmine.example.com/",
        "GESPRO_API_KEY": "tu-clave-api"
      }
    }
  }
}
```

Ver también `mcp.json.example`.

## Herramientas MCP

Consulta básica: `list_projects`, `get_project`, `get_project_members`, `get_member_tasks`, `get_member_status`, `get_all_members_status`, `search_issues`, `get_users`, `get_user`.

### T1 Pulso (daily y riesgos)

| Tool | Uso |
|------|-----|
| `get_overdue_issues` | Tareas abiertas vencidas (`due_date` < hoy) para el daily |
| `get_recent_activity` | Pulso creado/cerrado/actualizado de los últimos N días |
| `get_stalled_issues` | Tareas abiertas sin actualizar hace N días (riesgo de estancamiento) |

### T2 Planificación (roadmap)

| Tool | Uso |
|------|-----|
| `get_versions` | Hitos/versiones del proyecto con estado y fecha |
| `get_issue_details` | Detalle con hijos, relaciones y n.º de comentarios |
| `get_upcoming_deadlines` | Vencimientos abiertos en los próximos N días, ordenados |

### T3 Carga (capacidad y esfuerzo)

| Tool | Uso |
|------|-----|
| `get_workload` | Carga por miembro: abiertas, vencidas, horas estimadas/invertidas |
| `get_time_entries` | Imputaciones de tiempo con filtros de proyecto/fecha/usuario |

### T4 Flujo y catálogos

| Tool | Uso |
|------|-----|
| `get_issues_by_status` | Conteo agregado por estado, tracker y prioridad |
| `get_tracker_stats` | Abiertas/cerradas por tracker más lead time medio (`avg_close_days`) |
| `get_trackers` | Catálogo de trackers `{id, name}` |
| `get_issue_statuses` | Catálogo de estados `{id, name}` |
| `get_priorities` | Catálogo de prioridades `{id, name}` |

### T5 Escritura básica

| Tool | Uso |
|------|-----|
| `create_issue` | Crea una tarea (valida proyecto, asunto y fecha) |
| `update_issue` | Actualiza estado, asignado, avance, fecha o asunto |
| `add_note` | Agrega un comentario a una tarea |
| `log_time` | Imputa horas a una tarea (fecha por defecto: hoy) |

## Variables de entorno

| Variable             | Defecto                       | Descripción                                            |
|----------------------|-------------------------------|--------------------------------------------------------|
| `GESPRO_URL`         | `https://redmine.example.com/`| URL base de la instancia Redmine                       |
| `GESPRO_API_KEY`     | (vacío, obligatoria)          | Clave API del usuario; sin ella el servidor no arranca |
| `GESPRO_VERIFY_SSL`  | `true`                        | Verificación TLS (`true`/`false`)                      |
| `GESPRO_TIMEOUT`     | `30.0`                        | Tiempo de espera HTTP en segundos                      |
| `GESPRO_DEFAULT_LIMIT` | `50`                        | Límite por defecto de resultados en búsquedas          |
| `GESPRO_PROJECT_FILTER` | (vacío, sin filtro)        | Allowlist de proyectos: ids o identifiers separados por coma |
| `MCP_TRANSPORT`      | `stdio`                       | Fallback de transporte si no se pasa `--transport`     |

## Transporte y CLI

`main.py` acepta flags estilo argparse (tienen precedencia sobre `MCP_TRANSPORT`):

```bash
python main.py                          # stdio (default, para clientes MCP)
python main.py --transport sse --host 0.0.0.0 --port 8000   # http://localhost:8000/sse
python main.py --transport streamable-http --port 8000
python main.py --help
```

El logging va siempre a **stderr**, por lo que stdout queda puro para el protocolo MCP.

## Filtro de proyectos (GESPRO_PROJECT_FILTER)

Con ~57 proyectos en una instancia UCI puede interesar restringir el alcance de las herramientas a una lista propia. Define `GESPRO_PROJECT_FILTER` con ids numéricos o identifiers separados por coma (se recortan espacios; vacío = sin filtro, comportamiento original):

```bash
# .env — por ids
GESPRO_PROJECT_FILTER=16,58
# o por identifiers
GESPRO_PROJECT_FILTER=noticias-proyectos-uci,otro-proyecto
```

Efectos cuando el filtro está activo:

- `list_projects()` devuelve solo la intersección con la lista (por id o identifier).
- Todas las tools que reciben `project_id` rechazan proyectos fuera de la lista con un error claro: `Proyecto <id> no esta permitido por GESPRO_PROJECT_FILTER`.
- `search_issues()` sin `project_id` restringe la búsqueda a la lista (filtro server-side) en lugar de abarcar toda la instancia.
- Al arrancar se registra en stderr cuántos tokens/proyectos componen el allowlist (sin secretos).

## Integración con OpenCode

Tres estrategias, de más aislada a más simple. Todas usan `"type": "local"` y un array `command` en la config del proyecto (`opencode.json` o `~/.config/opencode/opencode.json`):

### A. Docker + `docker exec` (recomendada: dependencias congeladas en la imagen)

```bash
docker compose up -d --build   # el contenedor queda dormido (sleep infinity)
```

```json
{
  "mcp": {
    "gespro": {
      "type": "local",
      "command": ["docker", "exec", "-i", "gespro-mcp", "python3", "main.py"]
    }
  }
}
```

### B. `uv run` (gestiona deps automáticamente desde el repo)

```json
{
  "mcp": {
    "gespro": {
      "type": "local",
      "command": ["uv", "run", "python", "/ruta/absoluta/a/gespro-mcp/main.py"]
    }
  }
}
```

### C. `python` directo (requiere `make install` previo)

```json
{
  "mcp": {
    "gespro": {
      "type": "local",
      "command": ["python", "/ruta/absoluta/a/gespro-mcp/main.py"],
      "environment": {
        "GESPRO_URL": "https://tu-redmine.example.com/",
        "GESPRO_PROJECT_FILTER": "16,58"
      }
    }
  }
}
```

Sin `environment`, el servidor carga `.env` desde el directorio del script. Nunca pongas `GESPRO_API_KEY` en el JSON: usa `.env` (está en `.gitignore`).

## Estructura del proyecto

```
gespro-mcp/
├── server.py            # Monolito: 26 tools MCP + helpers REST crudos y filtros
├── main.py              # Entry point: argparse --transport/--host/--port
├── requirements.txt     # Única fuente de dependencias
├── Dockerfile           # Imagen: user no privilegiado, ENTRYPOINT python3 main.py
├── docker-compose.yml   # Servicio stdio activo + ejemplo SSE comentado
├── run-mcp.sh           # Wrapper: uv si existe, si no python3; pasa args ($@)
├── Makefile             # install/run/run-sse/build/up/down/logs/rebuild/test
├── .env.example         # Plantilla de configuración (copiar a .env)
├── mcp.json.example     # Ejemplo de config de cliente MCP (stdio vía python)
└── odd/                 # Documentación de features (ODD)
```

## Uso con Docker

```bash
cp .env.example .env
# editar .env con valores reales
docker compose up --build
```

Las variables se inyectan con `${GESPRO_URL}` / `${GESPRO_API_KEY}`; no hay secretos en el repositorio.

## Nota sobre SSL autofirmado

Si tu Redmine usa un certificado autofirmado, define `GESPRO_VERIFY_SSL=false` en `.env`. Úsalo solo en redes de confianza: desactiva la verificación TLS. El servidor registra un aviso en ese modo.

## Troubleshooting

- `GESPRO_API_KEY no esta configurada`: copia `.env.example` a `.env` y define la clave.
- `GESPRO_URL no esta configurada`: define la URL base de tu Redmine en `.env`.
- Errores TLS con certificados autofirmados: usa `GESPRO_VERIFY_SSL=false`.
- Dependencias: la única fuente es `requirements.txt` (`pip install -r requirements.txt`).
