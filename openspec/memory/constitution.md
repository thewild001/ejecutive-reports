# REPORTS — Project Constitution

> Principios inmutables del proyecto. Derivada del análisis del codebase
> (v1.0.0) y del Plan de Implementación por Fases (4 fases, Semana 1–8).
> Todo cambio de código se evalúa contra estos principios antes de implementarse.

---

## 1. Propósito y Identidad

REPORTS es una suite de **reportería ejecutiva automatizada** en Python que genera
PDFs desde tres fuentes: GESPRO/Redmine, GitLab REST API v4 y un JSON editable de
tendencias tecnológicas. Entrega vía SMTP y/o Telegram. Corre local, en Docker
y por cron.

**No es**: un servicio web, una API, ni una app interactiva. Es un paquete de
scripts ejecutables (`run.sh gespro|gitlab|trends|all`).

---

## 2. Tech Stack Aprobado

### Core (fijo)
| Componente | Elección | Estado |
|---|---|---|
| Lenguaje | Python **≥ 3.10** | ✅ En uso |
| HTTP client | `httpx` | ✅ En uso |
| PDF | `fpdf2` (+ fuentes DejaVu) | ✅ En uso |
| Config files | `PyYAML` (`yaml.safe_load` únicamente) | ✅ En uso |
| Entorno | `uv` + `.venv` (install.sh) · Docker como alternativa | ✅ En uso |

### Aprobadas por el Plan de Fases (adopción conforme avanzan las fases)
| Componente | Elección | Fase |
|---|---|---|
| Validación de config | **Pydantic ≥ 2.0** | Fase 1 |
| Logging estructurado | `logging` stdlib (`structlog` opcional) | Fase 1 |
| CLI | **Typer ≥ 0.9** | Fase 4 |
| Caché | `sqlite3` (stdlib) | Fase 3 |
| Paralelismo | `asyncio` / `concurrent.futures` (stdlib) | Fase 3 |
| Export Excel | `openpyxl` o `xlsxwriter` | Fase 3 |
| Web dashboard (opcional) | **FastAPI + Jinja2** | Fase 4 |
| i18n | `gettext` o YAML | Fase 4 |
| Templates PDF | Jinja2 | Fase 4 |

**Prohibido** introducir dependencias fuera de estas tablas sin confirmación
explícita del usuario. Preferencia permanente: **stdlib antes que librería nueva**
(precedente: `urllib.request` en delivery, loader `.env` propio en settings).

---

## 3. Arquitectura

```
REPORTS/
├── common/      ← código compartido: settings, pdfbase, delivery (+ nuevos módulos de fases)
├── gespro/      ← reporte Redmine/GESPRO (entry: gespro_report.py)
├── gitlab/      ← reporte GitLab (entry: gitlab_report.py)
├── trends/      ← boletín tendencias (entry: trends_report.py + trends_data.json)
├── output/      ← PDFs generados (rotación automática)
└── openspec/    ← constitution, specs y changes (único store canónico)
```

### Reglas arquitectónicas invariantes
1. **Toda lógica compartida vive en `common/`**. Los módulos de reporte nunca
   duplican acceso HTTP, config, PDF ni delivery.
2. **Cada reporte es un script ejecutable independiente** con `if __name__ ==
   "__main__"` y docstring de cabecera explicando propósito y salida.
3. **`ReportPDF` (common/pdfbase.py)** es la única base PDF. Paleta fija:
   `INK (33,37,41)`, `GOLD (176,141,66)`, `GRAY (110,118,129)`, `LIGHT`, `WHITE`.
4. **Config centralizada**: `config.yaml` (no secreto) + `.env` (secretos).
   Los secretos **nunca** aparecen en config.yaml — solo el *nombre* de la
   variable de entorno (`*_env` keys), resuelto con `require_env()`.
5. Los paths se resuelven relativos a `REPORTS_ROOT` (settings.py), nunca al CWD.

---

## 4. Convenciones de Código (observadas, obligatorias)

### Estilo Python
- `from __future__ import annotations` en **todo** módulo.
- Type hints modernos: `str | None`, `list[str]`, `dict` — sin `Optional`/`List` de typing.
- `pathlib.Path` para rutas (nunca concatenación de strings para paths).
- f-strings para todo formato de texto.
- Imports: stdlib → terceros → locales, separados por línea en blanco.
- Docstring de módulo en la primera línea describiendo propósito.

### Idioma
- **Texto de usuario, comentarios y mensajes de error: español.**
- Identifiers, nombres de módulos y funciones: inglés.
- Excepción: markers de specs/scaffolding en inglés (`[NEEDS CLARIFICATION]`).

### Manejo de errores
- Errores de configuración/entorno: `SystemExit` con mensaje claro y accionable
  (precedente: `require_env`).
- Errores de API: migrando hacia retry con backoff y distinción 4xx/5xx (Fase 1).
  Mientras tanto: `httpx.raise_for_status()` + except específico, nunca
  `except Exception` silencioso sin log.
- **Fase 1 en adelante: `logging` reemplaza `print()`** en código común.
  Los `print()` informativos de CLI permanecen solo como salida final al usuario.

### Configuración
- Defaults vía `.get(key, default)` o modelos Pydantic (Fase 1+).
- `verify_ssl` default seguro hacia **`true` en ejemplos/docs** (Fase 1 lo endurece).
- Rotación de outputs con `output.keep_last` (default 10).

### Testing (nuevo, desde Fase 1)
- Framework: **pytest**.
- Tests en directorio `tests/` separado (no co-ubicados con el código).
- Mínimo: validación de configuración y helpers puros. HTTP se mockea.

---

## 5. Seguridad (innegociable)

1. Secrets solo vía variables de entorno; `.env` nunca se versiona.
2. Tokens con mínimo privilegio: GitLab `read_api`, Redmine cuenta read-only.
3. Nunca loggear secretos, tokens ni bodies de auth en errores.
4. Validar config antes de ejecutar (Fase 1: Pydantic con errores claros).
5. Sanitizar inputs externos (paths, URLs, IDs de proyecto).
6. Timeouts explícitos en toda llamada de red (default 30s, configurable por Fase 1).

## 6. Git y Entrega

- Commits atómicos, conventional commits: `feat|fix|test|refactor|chore|docs`.
- Nunca mezclar feature + tests en el mismo commit.
- Specs y artefactos de openspec/ van en commits `docs` separados.
- `.env`, `output/*.pdf` y `__pycache__/` nunca se versionan.

## 7. Flujo de Trabajo (MentorKit)

1. Todo desarrollo pasa por: fingerprinting → plan → gates → confirmación → implementación.
2. Features nuevas → spec en `openspec/specs/[NNN]-[slug]/spec.md` antes de código.
3. Implementación sigue el **Plan de Fases aprobado**; cada fase tiene sus
   criterios de aceptación verificables.
4. Decisiones de alto riesgo (patrón nuevo, zona sensible) escalan a llm-council.
5. El plan puede enriquecer el código, **pero nunca contradice esta constitution**.
   Si un cambio futuro la contradice, se actualiza la constitution primero
   (commit explícito), luego el código.
