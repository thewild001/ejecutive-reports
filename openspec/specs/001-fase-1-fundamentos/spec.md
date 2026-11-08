# Spec 001 — Fase 1: Fundamentos de Producción

**Estado**: READY
**Fuente**: Plan de Implementación por Fases (Fase 1, Semana 1–2)
**Constitution**: `openspec/memory/constitution.md` §2 (deps F1), §4 (logging/errors), §5 (seguridad)

## Objetivo

Hacer el sistema robusto, debuggable y seguro para producción: logging
estructurado, validación de configuración con Pydantic, manejo de errores de
API con retry, y endurecimiento de seguridad en defaults y documentación.

## Alcance

### IN
1. `common/logging_config.py` — logging stdlib configurado, niveles, contexto
   (reporte/proyecto), archivo rotativo en producción.
2. `common/config_models.py` — modelos Pydantic v2 que validan `config.yaml`
   completo (tipos, required, URLs, enteros positivos) con mensajes claros.
3. `common/http_client.py` — cliente HTTP compartido con retry + exponential
   backoff, distinción 4xx/5xx, timeout configurable, sin exponer secretos.
4. Refactor de llamadas: gespro/gitlab adoptan el cliente compartido.
   delivery.py migra de print() a logging.
5. Seguridad: `verify_ssl` default `true` en ejemplos docs; `requirements.txt`
   y `pyproject.toml` añaden `pydantic>=2.0`.
6. Tests pytest en `tests/`: validación de config (válida/inválida/campos
   faltantes) y helpers puros.

### OUT (fases posteriores)
- Métricas avanzadas (F2), caché/paralelismo/exports (F3), CLI Typer (F4).

## Requisitos (delta)

### ADDED Requirements

#### REQ-1.1 Logging estructurado
- Todo módulo en `common/` y scripts de reporte usan `logging.getLogger(__name__)`.
- `setup_logging(cfg)` configura nivel desde config (`logging.level`, default INFO)
  y archivo rotativo opcional (`logging.file`, RotatingFileHandler).
- Los `print()` existentes se reemplazan por logs (INFO/WARNING/ERROR), salvo
  salida final de CLI orientada al usuario.
- Nunca se loggean tokens, API keys ni passwords.

#### REQ-1.2 Validación de configuración
- Modelos Pydantic v2 cubren: `company`, `output`, `gespro`, `gitlab`,
  `trends`, `delivery.email`, `delivery.telegram`.
- Validaciones: URLs con scheme http(s), enteros positivos (keep_last,
  max_projects, stale_branch_days, puertos), booleans, listas de strings.
- Config inválida → `SystemExit` con lista clara de todos los errores antes de
  cualquier llamada de red.
- `load_config()` pasa a devolver el modelo validado (o dict derivado) sin
  romper la interfaz actual de los reportes (acceso por claves).

#### REQ-1.3 Cliente HTTP robusto
- Retry con exponential backoff (3 intentos) para errores 5xx y timeouts/red.
- Errores 4xx no se reintentan; se reportan con status y path (sin headers).
- Timeout configurable por sección (`*_timeout` o `timeout_seconds`, default 30).
- API compatible con los wrappers actuales (`RedmineAPI`, GitLab client) —
  refactor interno, sin cambio de comportamiento observable salvo resiliencia.

#### REQ-1.4 Hardening de seguridad
- `config.yaml` de ejemplo y README documentan `verify_ssl: true` como default
  recomendado (con nota para entornos con CA interna).
- `require_env` ya falla si vacío — se mantiene; los wrappers validan antes de usar.
- README añade sección de permisos mínimos por token (ya parcial: se amplía).

#### REQ-1.5 Tests
- pytest configurado (dev-dependency).
- `tests/test_config_models.py`: config válida pasa; campos faltantes, tipos
  erróneos y URLs malformadas producen errores identificables.
- `tests/test_settings.py`: `rotate_outputs`, `require_env`, `load_dotenv`.

## Criterios de Aceptación (del plan)

- [ ] Todos los prints reemplazados con logging apropiado
- [ ] Config inválida produce error claro antes de ejecutar
- [ ] Errores de API 5xx/red se reintentan 3 veces con backoff
- [ ] Tests de validación pasan (`pytest tests/` verde)

## Riesgos

- Bajo: cambios internos; el comportamiento de salida (PDFs, delivery) no cambia.
- Pydantic es la primera dependencia nueva — aprobada en constitution §2.
