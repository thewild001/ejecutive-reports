"""
GitLab Advanced Analytics MCP Server (copia integrada en REPORTS).

Servidor MCP que expone herramientas de análisis y métricas sobre proyectos GitLab.
Útil para equipos de ingeniería que quieren entender salud del repositorio,
eficiencia de CI/CD, patrones de colaboración, y dinámicas del equipo.

Uso (desde la raíz de REPORTS):
    export GITLAB_TOKEN="glpat-..."
    # o defínelo en .env — se carga automáticamente con common/settings.py

    # Modo SSE (default) — servidor HTTP, ideal para conexiones remotas:
    python mcp/gitlab_server.py
    # → http://localhost:8000/sse

    # Modo stdio — tubería local, para docker exec o clientes MCP:
    python mcp/gitlab_server.py --transport stdio

    # Vía CLI de la suite (requiere el extra `mcp`):
    python cli.py mcp serve gitlab

Modo desarrollo (puerto custom):
    python mcp/gitlab_server.py --port 8080
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gitlab
import pandas as pd
from dateutil.parser import parse as parse_date
from mcp.server.fastmcp import FastMCP

# Raíz de REPORTS en sys.path para reutilizar common/ (loader .env propio).
_REPORTS_ROOT = Path(__file__).resolve().parent.parent
if str(_REPORTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPORTS_ROOT))

# ── Redis (opcional) ─────────────────────────────────────────────────────────
# Si REDIS_URL no está configurado, opera sin caché.
try:
    import redis as redis_lib
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False

# ── Configuración de logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,  # stderr para no contaminar el protocolo MCP (stdout)
)
log = logging.getLogger("gitlab-analytics")

# ── Cargar variables de entorno desde .env (raíz de REPORTS) ────────────────
from common.settings import load_dotenv as _reports_load_dotenv

_reports_load_dotenv()
log.info("Variables de entorno cargadas desde .env (si existe)")

# ── Redis cache (opcional) ──────────────────────────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "")
REDIS_TTL = int(os.environ.get("REDIS_TTL", "300"))  # 5 minutos por defecto

_redis_client = None


def get_redis():
    """Retorna el cliente Redis o None si no está configurado o no responde."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client if _redis_client is not False else None
    if not REDIS_URL or not _HAS_REDIS:
        _redis_client = False
        return None
    try:
        _redis_client = redis_lib.Redis.from_url(
            REDIS_URL, socket_connect_timeout=2, decode_responses=True
        )
        _redis_client.ping()
        log.info("Redis conectado → %s (TTL=%ss)", REDIS_URL, REDIS_TTL)
        return _redis_client
    except Exception as e:
        log.warning("Redis no disponible: %s. Operando sin caché.", e)
        _redis_client = False
        return None


def _cache_key(prefix: str, *args, **kwargs) -> str:
    """Genera una clave única para el cache."""
    raw = f"{prefix}:{json.dumps(args, sort_keys=True)}:{json.dumps(kwargs, sort_keys=True)}"
    return f"gitlab-mcp:{hashlib.md5(raw.encode()).hexdigest()}"


def cache_get(prefix: str, *args, **kwargs) -> str | None:
    """Obtiene valor del cache. Retorna None si no hay cache o Redis no disponible."""
    r = get_redis()
    if not r:
        return None
    key = _cache_key(prefix, *args, **kwargs)
    try:
        val = r.get(key)
        if val is not None:
            log.info("Cache HIT  → %s", key[:72])
        return val
    except Exception:
        return None


def cache_set(prefix: str, value: str, *args, **kwargs) -> None:
    """Guarda valor en cache con TTL configurable."""
    r = get_redis()
    if not r:
        return
    key = _cache_key(prefix, *args, **kwargs)
    try:
        r.setex(key, REDIS_TTL, value)
        log.info("Cache SET  → %s (TTL=%ss)", key[:72], REDIS_TTL)
    except Exception:
        pass


# ── Inicializar servidor MCP ────────────────────────────────────────────────
mcp = FastMCP(
    "GitLab Advanced Analytics",
    instructions="Analítica avanzada para proyectos GitLab: pipelines, ramas, contribuciones, MRs, issues y más.",
    host="0.0.0.0",
    port=8000,
    sse_path="/sse",
)


def _safe_api_call(project_or_gl, resource_and_method: str, **kwargs):
    """
    Wrapper para llamadas de listado a la API de GitLab.
    Captura 403 Forbidden y retorna None.
    Así el llamante puede chequear::

        commits = _safe_api_call(project, "commits.list", per_page=20)
        if commits is None:
            return "Sin acceso a commits..."
        if not commits:
            return "No hay commits..."
        for c in commits:   # seguro
            ...

    Ejemplos:
        branches = _safe_api_call(project, "branches.list", all=True)
        commits  = _safe_api_call(project, "commits.list", per_page=20)
        issues   = _safe_api_call(project, "issues.list", state="opened", per_page=100)
    """
    try:
        parts = resource_and_method.split(".")
        obj = project_or_gl
        for part in parts:
            obj = getattr(obj, part)
        return obj(**kwargs)
    except Exception as exc:
        err_str = str(exc)
        if "403" in err_str or "Forbidden" in err_str:
            res_name = resource_and_method.split(".")[0]
            log.warning("API 403 en %s/%s (sin permisos)",
                        getattr(project_or_gl, "id", "?"), res_name)
            return None
        raise


# ── Cliente GitLab ──────────────────────────────────────────────────────────
def get_gitlab_client() -> gitlab.Gitlab:
    """Inicializa el cliente de GitLab.

    Prioridad: variables de entorno → config.yaml (sección ``gitlab``) →
    defaults. Los secretos siempre llegan vía entorno/.env (constitution §5).
    """
    # Fallback a config.yaml solo si faltan las variables de entorno.
    cfg_gitlab: dict = {}
    if not (os.environ.get("GITLAB_URL") and os.environ.get("GITLAB_TOKEN")):
        try:
            from common.settings import load_config
            cfg_gitlab = load_config().get("gitlab", {}) or {}
        except Exception:  # config ausente/inválido: se sigue con env puro
            cfg_gitlab = {}

    gitlab_url = os.environ.get("GITLAB_URL") or cfg_gitlab.get(
        "base_url", "https://gitlab.com")
    token_env = cfg_gitlab.get("token_env", "GITLAB_TOKEN")
    gitlab_token = os.environ.get("GITLAB_TOKEN") or os.environ.get(token_env, "")
    if not gitlab_token:
        raise ValueError(
            "El token de GitLab no está configurado. "
            "Define GITLAB_TOKEN en .env o expórtalo en el entorno."
        )
    env_ssl = os.environ.get("GITLAB_SSL_VERIFY")
    ssl_verify = (env_ssl.lower() != "false") if env_ssl else bool(
        cfg_gitlab.get("verify_ssl", True))
    gl = gitlab.Gitlab(gitlab_url, private_token=gitlab_token, ssl_verify=ssl_verify)
    log.info("Cliente GitLab conectado a %s (ssl_verify=%s)", gitlab_url, ssl_verify)
    return gl


def _safe_get(project, resource: str, item_id: int, **kwargs):
    """Wrapper con reintento básico para obtener recursos de GitLab."""
    try:
        return getattr(project, resource).get(item_id, **kwargs)
    except gitlab.exceptions.GitlabError as e:
        log.warning("Error al obtener %s/%s: %s", resource, item_id, e)
        raise


# ══════════════════════════════════════════════════════════════════════════════
#  RECURSOS MCP
# ══════════════════════════════════════════════════════════════════════════════

@mcp.resource("analytics://project/{project_id}/resumen")
def resource_resumen_proyecto(project_id: str) -> str:
    """
    Resumen rápido de salud del proyecto: pipelines recientes, cantidad de ramas,
    issues abiertos y últimos commits.
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)

        pipelines = project.pipelines.list(per_page=10, scope="running")
        branches = project.branches.list(all=True)
        issues = project.issues.list(state="opened", per_page=1)
        commits = project.commits.list(per_page=1)

        return (
            f"--- Resumen de {project.name} ---\n"
            f"Ramas activas: {len(branches)}\n"
            f"Pipelines en ejecución: {len(pipelines)}\n"
            f"Issues abiertos: {project.open_issues_count if hasattr(project, 'open_issues_count') else len(issues)}\n"
            f"Último commit: {commits[0].created_at[:10] if commits else 'N/A'}\n"
            f"URL: {project.web_url}\n"
        )
    except Exception as e:
        log.exception("Error en resource_resumen_proyecto")
        return f"Error al obtener resumen: {e}"


# ══════════════════════════════════════════════════════════════════════════════
#  1. MÉTRICAS DE CI/CD Y RENDIMIENTO DEL PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def analizar_rendimiento_pipelines(project_id: str, limit: int = 50) -> str:
    """
    Analiza la estabilidad y eficiencia de los pipelines de CI/CD del proyecto.
    Retorna tasa de éxito, tiempos promedio de ejecución y fallos comunes.

    Args:
        project_id: ID o ruta codificada del proyecto (ej: 'group/project' o '12345').
        limit: Cantidad de pipelines a analizar (default: 50).
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)
        pipelines = project.pipelines.list(per_page=limit)

        if not pipelines:
            return f"No se encontraron pipelines recientes en el proyecto {project.name}."

        data = []
        for p in pipelines:
            p_detail = project.pipelines.get(p.id)
            data.append({
                "id": p_detail.id,
                "status": p_detail.status,
                "duration": p_detail.duration,
                "ref": p_detail.ref,
                "source": p_detail.source,
                "created_at": str(p_detail.created_at)[:10] if p_detail.created_at else "N/A",
            })

        total = len(data)
        status_counts = {}
        for d in data:
            status_counts[d["status"]] = status_counts.get(d["status"], 0) + 1

        success_count = status_counts.get("success", 0)
        success_rate = (success_count / total) * 100 if total else 0

        durations = [d["duration"] for d in data if d["duration"] is not None and d["duration"] > 0 and d["status"] == "success"]
        avg_duration_min = (sum(durations) / len(durations) / 60) if durations else 0

        fail_count = status_counts.get("failed", 0)
        fail_rate = (fail_count / total) * 100 if total else 0

        # Fallos por rama
        fail_refs = {}
        for d in data:
            if d["status"] == "failed":
                fail_refs[d["ref"]] = fail_refs.get(d["ref"], 0) + 1
        top_fails = sorted(fail_refs.items(), key=lambda x: -x[1])[:5]

        # Pipelines por rama
        ref_counts = {}
        for d in data:
            ref_counts[d["ref"]] = ref_counts.get(d["ref"], 0) + 1
        top_refs = sorted(ref_counts.items(), key=lambda x: -x[1])[:5]

        result = (
            f"🔄 *Rendimiento de Pipelines* — {project.name}\n"
            f"{total} pipelines analizados\n\n"
            f"· ✅ Éxito: {success_rate:.0f}%\n"
            f"· ❌ Fallos: {fail_rate:.0f}%\n"
            f"· ⏱️ Duración promedio: {avg_duration_min:.0f} min\n\n"
        )

        result += "*Por rama*\n"
        for ref, count in top_refs:
            bar_len = max(1, int((count / total) * 20))
            bar = "▬" * bar_len
            result += f"`{bar:<8}` {ref}: {count}\n"

        if top_fails:
            result += "\n*Fallos por rama*\n"
            for ref, count in top_fails:
                result += f"· {ref}: {count} fallos\n"

        return result
    except Exception as e:
        log.exception("Error en analizar_rendimiento_pipelines")
        return f"Error al analizar pipelines: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  2. SALUD DEL REPOSITORIO (RAMAS OBSOLETAS / DESVIACIONES)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def detectar_ramas_stale(project_id: st º   º12*/0. ys_threshold: int = 60) -> str:
    """
    Identifica ramas inactivas (stale) que no han recibido commits recientemente.
    Ayuda a evaluar la acumulación de deuda técnica o código abandonado.

    Args:
        project_id: ID o ruta codificada del proyecto.
        days_threshold: Días sin actividad para considerar una rama como "stale" (default: 60).
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)
        branches = _safe_api_call(project, "branches.list", all=True)
        now = datetime.now(timezone.utc)

        if branches is None:
            return f"🔒 Sin acceso a ramas de *{project.name}* (permisos insuficientes)."

        stale_branches = []
        for b in branches:
            if b.protected:
                continue
            last_commit_date = parse_date(b.commit["committed_date"])
            age_days = (now - last_commit_date).days
            if age_days > days_threshold:
                stale_branches.append({
                    "name": b.name,
                    "last_author": b.commit["author_name"],
                    "age_days": age_days,
                    "date": b.commit["committed_date"][:10],
                })

        if not stale_branches:
            return (
                f"✅ *{project.name}* — No hay ramas inactivas "
                f"(> {days_threshold} días sin cambios)."
            )

        very_old = sum(1 for s in stale_branches if s["age_days"] > days_threshold * 2)

        result = (
            f"🌿 *Ramas Inactivas* — {project.name}\n"
            f"{len(stale_branches)} ramas sin cambios > {days_threshold} días "
            f"({very_old} muy viejas)\n\n"
        )
        for s in sorted(stale_branches, key=lambda x: -x["age_days"]):
            emoji = "⚠️" if s["age_days"] > days_threshold * 2 else "▸"
            result += (
                f"{emoji} *{s['name']}* — {s['age_days']} días "
                f"(último: {s['date']}, {s['last_author']})\n"
            )

        return result
    except Exception as e:
        log.exception("Error en detectar_ramas_stale")
        return f"Error al buscar ramas inactivas: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  3. PATRONES COMPORTAMENTALES Y HORARIOS DE USUARIOS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def obtener_patrones_horarios_commits(project_id: str, limit: int = 150) -> str:
    """
    Analiza las horas y días de los commits para identificar patrones de trabajo.
    Útil para comprender las dinámicas de entrega del equipo y detectar sobrecarga.

    Args:
        project_id: ID o ruta codificada del proyecto.
        limit: Cantidad de commits a analizar (default: 150).
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)
        commits = _safe_api_call(project, "commits.list", per_page=limit)

        if commits is None:
            return f"🔒 Sin acceso a commits de *{project.name}* (permisos insuficientes)."
        if not commits:
            return f"📭 *{project.name}* — No hay commits suficientes para analizar."

        times = []
        for c in commits:
            dt = parse_date(c.created_at)
            times.append({
                "hour": dt.hour,
                "day_name": dt.strftime("%A"),
                "day_num": dt.weekday(),
            })

        df = pd.DataFrame(times)

        def clasificar_bloque(hora):
            if 0 <= hora < 6:
                return "🌙 Madrugada"
            elif 6 <= hora < 12:
                return "☀️ Mañana"
            elif 12 <= hora < 18:
                return "🌤️ Tarde"
            else:
                return "🌆 Noche"

        df["bloque_horario"] = df["hour"].apply(clasificar_bloque)
        by_block = df["bloque_horario"].value_counts()
        peak_hour = df["hour"].mode().iloc[0] if not df.empty else "—"
        hours_map = {0: "00", 1: "01", 2: "02", 3: "03", 4: "04", 5: "05",
                     6: "06", 7: "07", 8: "08", 9: "09", 10: "10", 11: "11",
                     12: "12", 13: "13", 14: "14", 15: "15", 16: "16", 17: "17",
                     18: "18", 19: "19", 20: "20", 21: "21", 22: "22", 23: "23"}

        result = (
            f"🕐 *Patrón de Actividad* — {project.name}\n"
            f"({len(df)} commits analizados)\n\n"
        )

        # Bloques del día
        result += "*Por bloque horario*\n"
        for bloque in ["☀️ Mañana", "🌤️ Tarde", "🌆 Noche", "🌙 Madrugada"]:
            count = by_block.get(bloque, 0)
            pct = (count / len(df)) * 100
            result += f"· {bloque}: {count} ({pct:.0f}%)\n"

        result += f"\n⏰ Hora pico: ~{hours_map.get(peak_hour, str(peak_hour))}:00\n\n"

        # Días de la semana
        day_names_es = {
            "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
            "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado",
            "Sunday": "Domingo"
        }
        by_day = df.groupby(["day_num", "day_name"]).size()
        result += "*Por día*\n"
        for (_, day_en), count in sorted(by_day.items(), key=lambda x: x[0][0]):
            dia_es = day_names_es.get(day_en, day_en)
            pct = (count / len(df)) * 100
            result += f"· {dia_es}: {count} ({pct:.0f}%)\n"

        return result
    except Exception as e:
        log.exception("Error en obtener_patrones_horarios_commits")
        return f"Error al analizar patrones horarios: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  4. COLABORACIÓN Y RIESGO DE "FACTOR BUS" (Silos de Información)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def analizar_distribucion_codigo_y_silos(project_id: str, limit: int = 100) -> str:
    """
    Calcula la concentración de aportes para evaluar el 'Factor Bus' del repositorio.
    Identifica si el conocimiento está centralizado en pocos desarrolladores.

    Args:
        project_id: ID o ruta codificada del proyecto.
        limit: Cantidad de commits a analizar (default: 100).
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)
        commits = _safe_api_call(project, "commits.list", per_page=limit)

        if commits is None:
            return f"🔒 Sin acceso a commits de *{project.name}* (permisos insuficientes)."
        if not commits:
            return f"📭 *{project.name}* — Pocos commits para evaluar distribución."

        authors = [c.author_name for c in commits]
        counts = pd.Series(authors).value_counts()
        total = len(authors)

        cumulative = 0
        bus_factor = 0
        top_share = 0.0

        result = f"👥 *Distribución de Contribuciones* — {project.name}\n({total} commits)\n\n"

        for i, (author, count) in enumerate(counts.items(), 1):
            share = (count / total) * 100
            cumulative += share
            if cumulative <= 75:
                bus_factor += 1
            if i == 1:
                top_share = share
            bar_len = max(1, int(share / 5))
            bar = "▬" * bar_len
            result += f"`{bar:<8}` {author}: {count} ({share:.1f}%)\n"

        # HHI
        hhi = sum((c / total) ** 2 for c in counts.values())

        result += (
            f"\n*Concentración* HHI: {hhi:.3f} "
            f"{'🔴 Alto' if hhi > 0.5 else '🟡 Medio' if hhi > 0.3 else '🟢 Bajo'}\n"
        )
        result += f"*Factor Bus*: ~{max(1, bus_factor)} desarrolladores\n"
        result += f"*Top contribuidor*: {top_share:.0f}% del código\n"

        if hhi > 0.5:
            result += "\n⚠️ Alta concentración — conviene distribuir revisiones."
        elif hhi > 0.3:
            result += "\n👀 Concentración moderada — monitorear."

        return result
    except Exception as e:
        log.exception("Error en analizar_distribucion_codigo_y_silos")
        return f"Error al analizar distribución: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  5. TIEMPO DE RESPUESTA EN PROBLEMAS (ISSUES)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def analizar_ciclo_vida_issues(project_id: str, limit: int = 50) -> str:
    """
    Mide los tiempos de respuesta y resolución de los tickets (issues).
    Ofrece visibilidad sobre la velocidad de respuesta del equipo ante incidencias.

    Args:
        project_id: ID o ruta codificada del proyecto.
        limit: Cantidad de issues a analizar (default: 50).
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)
        issues = project.issues.list(state="all", per_page=limit)

        if not issues:
            return f"📭 *{project.name}* — No se encontraron issues."

        opened = sum(1 for i in issues if i.state == "opened")
        closed = sum(1 for i in issues if i.state == "closed")

        # Tiempos de resolución para issues cerrados
        res_days = []
        for i in issues:
            if i.state == "closed" and i.closed_at:
                created = parse_date(i.created_at)
                closed_dt = parse_date(i.closed_at)
                res_days.append((closed_dt - created).total_seconds() / 86400)

        unassigned = sum(1 for i in issues if len(i.assignees) == 0)

        result = (
            f"🎫 *Issues* — {project.name}\n"
            f"{len(issues)} analizados\n\n"
            f"· Abiertos: {opened}\n"
            f"· Cerrados: {closed}\n"
            f"· Sin asignar: {unassigned}\n\n"
        )

        if res_days:
            avg_d = sum(res_days) / len(res_days)
            result += (
                f"⏱️ *Tiempo de resolución*\n"
                f"· Promedio: {avg_d:.1f} días\n"
                f"· Mínimo: {min(res_days):.1f} días\n"
                f"· Máximo: {max(res_days):.1f} días\n"
            )
        else:
            result += "⏱️ Sin issues cerrados para medir resolución.\n"

        return result
    except Exception as e:
        log.exception("Error en analizar_ciclo_vida_issues")
        return f"Error al analizar issues: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  6. (NUEVO) ANALÍTICA DE MERGE REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def analizar_merge_requests(project_id: str, limit: int = 50) -> str:
    """
    Analiza métricas de Merge Requests: tiempo de revisión, tasa de aprobación,
    tamaño de los MRs, y eficiencia del proceso de code review.

    Args:
        project_id: ID o ruta codificada del proyecto.
        limit: Cantidad de MRs a analizar (default: 50).
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)

        # Traemos MRs mergeados y abiertos
        mrs_merged = _safe_api_call(project, "mergerequests.list", state="merged", per_page=limit)
        mrs_open = _safe_api_call(project, "mergerequests.list", state="opened", per_page=limit)

        if mrs_merged is None and mrs_open is None:
            return f"Sin acceso a Merge Requests del proyecto {project.name} (permisos insuficientes)."

        mrs_merged = mrs_merged or []
        mrs_open = mrs_open or []
        all_mrs = mrs_merged + mrs_open

        if not all_mrs:
            return f"No se encontraron Merge Requests en {project.name}."

        data = []
        for mr in all_mrs:
            created = parse_date(mr.created_at)
            merged = parse_date(mr.merged_at) if hasattr(mr, "merged_at") and mr.merged_at else None
            closed = parse_date(mr.closed_at) if hasattr(mr, "closed_at") and mr.merged_at is None and hasattr(mr, "closed_at") and mr.closed_at else None

            # Tiempo de vida del MR
            end = merged or closed or datetime.now(timezone.utc)
            lifetime_days = (end - created).total_seconds() / 86400
            # Tiempo hasta merge (solo mergeados)
            merge_time_days = (merged - created).total_seconds() / 86400 if merged else None

            data.append({
                "iid": mr.iid,
                "title": mr.title[:60],
                "state": mr.state,
                "author": mr.author["name"] if mr.author else "Desconocido",
                "created": str(mr.created_at)[:10],
                "merged": str(mr.merged_at)[:10] if merged else "—",
                "lifetime_days": round(lifetime_days, 1),
                "merge_time_days": round(merge_time_days, 1) if merge_time_days else None,
                "source_branch": mr.source_branch,
                "target_branch": mr.target_branch,
            })

        total = len(data)
        merged_count = sum(1 for d in data if d["state"] == "merged")
        open_count = sum(1 for d in data if d["state"] == "opened")

        # Tiempo promedio para merge
        merge_times = [d["merge_time_days"] for d in data if d["merge_time_days"]]
        avg_merge_time = sum(merge_times) / len(merge_times) if merge_times else 0

        # Autores más activos
        authors = {}
        for d in data:
            authors[d["author"]] = authors.get(d["author"], 0) + 1
        top_authors = sorted(authors.items(), key=lambda x: -x[1])[:5]

        # Ramas destino
        target_branches = {}
        for d in data:
            target_branches[d["target_branch"]] = target_branches.get(d["target_branch"], 0) + 1
        top_branches = sorted(target_branches.items(), key=lambda x: -x[1])[:5]

        result = (
            f"🔄 *Merge Requests* — {project.name}\n"
            f"{total} analizados\n\n"
            f"· Mergeados: {merged_count}\n"
            f"· Abiertos: {open_count}\n"
            f"· Tiempo promedio a merge: {avg_merge_time:.1f} días\n\n"
        )

        result += "*Top autores*\n"
        for author, count in top_authors:
            result += f"· {author}: {count} MRs\n"

        result += "\n*Ramas destino*\n"
        for branch, count in top_branches:
            result += f"· `{branch}`: {count} MRs\n"

        return result
    except Exception as e:
        log.exception("Error en analizar_merge_requests")
        return f"Error al analizar Merge Requests: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  7. (NUEVO) TENDENCIA DE CONTRIBUCIONES EN EL TIEMPO
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def analizar_tendencia_contribuciones(project_id: str, months: int = 6) -> str:
    """
    Analiza la tendencia de commits a lo largo del tiempo para detectar
    épocas de alta/baja actividad y estacionalidad del equipo.

    Args:
        project_id: ID o ruta codificada del proyecto.
        months: Cantidad de meses hacia atrás a analizar (default: 6).
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)
        since_date = datetime.now(timezone.utc) - timedelta(days=30 * months)

        # GitLab API permite filtrar por fecha desde
        commits = _safe_api_call(project, "commits.list", since=since_date.isoformat(), all=True)

        if commits is None:
            return f"Sin acceso a commits del proyecto {project.name} (permisos insuficientes)."
        elif not commits:
            return f"No hay commits en los últimos {months} meses en {project.name}."

        # Agrupar por mes
        monthly = defaultdict(int)
        author_monthly = defaultdict(lambda: defaultdict(int))

        for c in commits:
            dt = parse_date(c.created_at)
            key = dt.strftime("%Y-%m")
            monthly[key] += 1
            author_monthly[key][c.author_name] += 1

        # Ordenar meses
        meses_ordenados = sorted(monthly.keys())
        total_commits = len(commits)
        avg_monthly = total_commits / len(meses_ordenados) if meses_ordenados else 0

        # Mes más activo
        max_mes = max(monthly.items(), key=lambda x: x[1])

        # Top autores
        all_authors = defaultdict(int)
        for c in commits:
            all_authors[c.author_name] += 1
        top_authors = sorted(all_authors.items(), key=lambda x: -x[1])[:5]

        result = (
            f"📈 *Tendencia de Contribuciones* — {project.name}\n"
            f"Últimos {months} meses · {total_commits} commits\n\n"
            f"*Actividad mensual*\n"
        )
        for mes in meses_ordenados:
            count = monthly[mes]
            bar_len = max(1, int((count / max(avg_monthly, 1)) * 4))
            bar = "▬" * min(bar_len, 20)
            result += f"`{bar:<20}` {mes}: {count}\n"

        result += (
            f"\n📊 Promedio: {avg_monthly:.0f}/mes\n"
            f"🔥 Pico: {max_mes[0]} ({max_mes[1]} commits)\n\n"
            f"*Top contribuyentes*\n"
        )
        for i, (author, count) in enumerate(top_authors, 1):
            pct = (count / total_commits) * 100
            result += f"· {author}: {count} ({pct:.1f}%)\n"

        return result
    except Exception as e:
        log.exception("Error en analizar_tendencia_contribuciones")
        return f"Error al analizar tendencia: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  8. (NUEVO) REPORTE DE SALUD DEL PROYECTO (Dashboard Combinado)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def reporte_salud_proyecto(project_id: str) -> str:
    """
    Genera un dashboard rápido combinando múltiples métricas del proyecto:
    pipelines, ramas, issues, MRs y contribuciones recientes.
    Ideal para una visión general ejecutiva de la salud del repositorio.

    Args:
        project_id: ID o ruta codificada del proyecto.
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)

        # ── Pipelines recientes ──
        try:
            pipelines = project.pipelines.list(per_page=20, get_all=False)
            if pipelines:
                df_p = pd.DataFrame([{"status": p.status} for p in pipelines])
                success_pct = (df_p["status"].value_counts().get("success", 0) / len(df_p)) * 100
                last_pipeline_status = pipelines[0].status
            else:
                success_pct = 0
                last_pipeline_status = "Sin datos"
        except Exception as exc:
            log.warning("reporte_salud: no se pudieron obtener pipelines: %s", exc)
            success_pct = 0
            last_pipeline_status = "Sin acceso"

        # ── Ramas ──
        try:
            branches = project.branches.list(all=True)
            protected = sum(1 for b in branches if b.protected)
            stale_count = 0
            now = datetime.now(timezone.utc)
            for b in branches:
                if not b.protected:
                    age = (now - parse_date(b.commit["committed_date"])).days
                    if age > 60:
                        stale_count += 1
        except Exception as exc:
            log.warning("reporte_salud: no se pudieron obtener ramas: %s", exc)
            branches = []
            protected = 0
            stale_count = 0

        # ── Issues ──
        try:
            open_issues = project.issues.list(state="opened", per_page=100, get_all=False)
            unassigned = sum(1 for i in open_issues if len(i.assignees) == 0) if open_issues else 0
        except Exception as exc:
            log.warning("reporte_salud: no se pudieron obtener issues: %s", exc)
            open_issues = []
            unassigned = 0

        # ── MRs ──
        try:
            open_mrs = project.mergerequests.list(state="opened", per_page=100, get_all=False)
            merged_mrs = project.mergerequests.list(state="merged", per_page=20, get_all=False)
        except Exception as exc:
            log.warning("reporte_salud: no se pudieron obtener MRs: %s", exc)
            open_mrs = []
            merged_mrs = []

        # ── Commits recientes ──
        try:
            recent_commits = project.commits.list(per_page=5, get_all=False)
        except Exception as exc:
            log.warning("reporte_salud: no se pudieron obtener commits: %s", exc)
            recent_commits = []

        # Scoring simple de salud
        score = 0
        score += 25 if success_pct >= 80 else 15 if success_pct >= 50 else 5
        score += 15 if branches and stale_count <= 5 else 5
        score += 20 if open_issues and unassigned <= len(open_issues) * 0.3 else 5
        score += 20 if len(open_mrs) <= 10 else 10
        score += 20 if recent_commits else 0

        health = (
            "🟢 Excelente" if score >= 90 else
            "🟢 Buena" if score >= 70 else
            "🟡 Regular" if score >= 40 else
            "🔴 Precaria"
        )

        result = (
            f"📊 *{project.name}*\n"
            f"Salud: {health}  ({score}/100)\n\n"
            f"▸ *Pipelines* — Último: {last_pipeline_status}  ·  "
            f"Éxito: {success_pct:.0f}%\n"
        )

        if branches:
            result += (
                f"▸ *Ramas* — {len(branches)} total · {protected} protegidas · "
                f"{stale_count} stale\n"
            )
        else:
            result += "▸ *Ramas* — Sin acceso\n"

        if open_issues:
            pct_sin_asignar = (unassigned / len(open_issues)) * 100 if open_issues else 0
            result += (
                f"▸ *Issues* — {len(open_issues)} abiertos · "
                f"{unassigned} sin asignar ({pct_sin_asignar:.0f}%)\n"
            )
        else:
            result += "▸ *Issues* — Sin acceso\n"

        if open_mrs or merged_mrs:
            result += (
                f"▸ *MRs* — {len(open_mrs)} abiertos · "
                f"{len(merged_mrs)} mergeados (recientes)\n"
            )
        else:
            result += "▸ *MRs* — Sin acceso\n"

        if recent_commits:
            result += "▸ *Últimos commits*\n"
            for c in recent_commits[:5]:
                result += f"  · {c.created_at[:10]} — {c.author_name}: {c.title[:55]}\n"
        else:
            result += "▸ *Commits* — Sin acceso\n"

        return result
    except Exception as e:
        log.exception("Error en reporte_salud_proyecto")
        return f"Error al generar reporte de salud: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  9. (NUEVO) ANALIZADOR DE COLABORADORES ACTIVOS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def analizar_colaboradores_activos(project_id: str, limit: int = 100, days: int = 90) -> str:
    """
    Identifica quiénes están contribuyendo activamente al proyecto,
    frecuencia de commits, antigüedad y métricas individuales.

    Args:
        project_id: ID o ruta codificada del proyecto.
        limit: Cantidad de commits a analizar (default: 100).
        days: Ventana de tiempo para considerar actividad 'reciente' (default: 90).
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)
        since_date = datetime.now(timezone.utc) - timedelta(days=days)

        try:
            commits = project.commits.list(since=since_date.isoformat(), per_page=limit, get_all=False)
        except Exception as exc:
            log.warning("analizar_colaboradores: no se pudieron obtener commits: %s", exc)
            return f"No hay acceso a los commits del proyecto {project.name} en los últimos {days} días."

        if not commits:
            return f"No hay commits en los últimos {days} días en {project.name}."

        # Agrupar por autor
        author_stats = defaultdict(lambda: {"commits": 0, "first_seen": None, "last_seen": None, "lines_changed": 0})

        for c in commits:
            name = c.author_name
            dt = parse_date(c.created_at)
            author_stats[name]["commits"] += 1
            if author_stats[name]["first_seen"] is None or dt < author_stats[name]["first_seen"]:
                author_stats[name]["first_seen"] = dt
            if author_stats[name]["last_seen"] is None or dt > author_stats[name]["last_seen"]:
                author_stats[name]["last_seen"] = dt

        rows = []
        for author, stats in author_stats.items():
            days_active = (stats["last_seen"] - stats["first_seen"]).days + 1 if stats["first_seen"] else 1
            freq = round(stats["commits"] / days_active, 2) if days_active > 0 else 0
            rows.append({
                "author": author,
                "commits": stats["commits"],
                "first_seen": stats["first_seen"].strftime("%Y-%m-%d") if stats["first_seen"] else "—",
                "last_seen": stats["last_seen"].strftime("%Y-%m-%d") if stats["last_seen"] else "—",
                "freq": freq,
            })

        rows.sort(key=lambda r: -r["commits"])
        total_commits = sum(r["commits"] for r in rows)

        result = (
            f"👥 *Colaboradores Activos* — {project.name}\n"
            f"Últimos {days} días · {total_commits} commits\n"
            f"{len(rows)} contribuidores distintos\n\n"
        )
        for r in rows:
            pct = (r["commits"] / total_commits) * 100
            bar_len = max(1, int(pct / 5))
            bar = "▬" * bar_len
            result += (
                f"`{bar:<8}` *{r['author']}* — {r['commits']} ({pct:.0f}%)\n"
                f"        📅 {r['first_seen']} → {r['last_seen']}  "
                f"(frec: {r['freq']:.2f}/día)\n"
            )
    except Exception as e:
        log.exception("Error en analizar_colaboradores_activos")
        return f"Error al analizar colaboradores: {str(e)}"


@mcp.tool()
def ranking_contribuciones_proyecto(project_id: str, limit: int = 100) -> str:
    """
    Ranking de miembros del proyecto ordenados por cantidad de commits
    (de mayor a menor). Ideal para ver quién contribuye más.

    Args:
        project_id: ID o ruta codificada del proyecto.
        limit: Cantidad de commits a analizar (default: 100).
               Usá 3 para top 3, o un número grande para ranking completo.
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)

        commits = _safe_api_call(project, "commits.list", per_page=limit, get_all=False)
        if commits is None:
            return f"❌ Sin acceso a commits del proyecto {project.name}."
        if not commits:
            return f"📭 No hay commits en {project.name}."

        # Agrupar por autor
        from collections import Counter
        autor_commits: Counter = Counter()
        for c in commits:
            autor_commits[c.author_name] += 1

        # Ordenar de mayor a menor
        ranking = autor_commits.most_common()  # ya ordena descendente
        total = sum(c for _, c in ranking)
        n = len(ranking)

        # Emojis para top 3
        medallas = ["🥇", "🥈", "🥉"]

        result = f"🏆 *Ranking de Contribuciones* — {project.name}\n"
        result += f"{total} commits · {n} contribuidores\n\n"

        for i, (autor, count) in enumerate(ranking):
            pct = (count / total) * 100
            bar_len = max(1, int(pct / 5))
            bar = "▬" * bar_len
            linea = f"{'    ' if i >= 3 else ''}"
            if i < 3:
                linea += f"{medallas[i]} "
            linea += f"*{autor}* — {count} commits ({pct:.0f}%)\n"
            linea += f"       `{bar:<8}`\n"
            result += linea

        top3 = " · ".join(r[0] for r in ranking[:3])
        result += f"\n📊 *Top 3:* {top3}"
        return result

    except Exception as e:
        log.exception("Error en ranking_contribuciones_proyecto")
        return f"Error al generar ranking: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
# 10. (NUEVO) TIEMPO DE REVISIÓN DE MERGE REQUESTS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def analizar_tiempo_revision_mr(project_id: str, limit: int = 30) -> str:
    """
    Analiza en detalle el tiempo que toma el proceso de code review:
    desde que se abre un MR hasta el primer comentario, aprobación o merge.

    Args:
        project_id: ID o ruta codificada del proyecto.
        limit: Cantidad de MRs mergeados a analizar (default: 30).
    """
    try:
        gl = get_gitlab_client()
        project = gl.projects.get(project_id)
        mrs = _safe_api_call(project, "mergerequests.list", state="merged", per_page=limit)

        if mrs is None:
            return f"🔒 Sin acceso a Merge Requests de *{project.name}* (permisos insuficientes)."
        if not mrs:
            return f"📭 *{project.name}* — No hay MRs mergeados para analizar."

        data = []
        for mr in mrs:
            created = parse_date(mr.created_at)
            merged = parse_date(mr.merged_at) if mr.merged_at else None

            if not merged:
                continue

            total_hours = (merged - created).total_seconds() / 3600

            # Obtener discusión para calcular tiempo hasta primer comentario
            try:
                mr_detail = project.mergerequests.get(mr.iid)
                notes = mr_detail.notes.list(all=True, sort="asc")
                first_response = None
                for note in notes:
                    if note.system is False and note.author["name"] != mr.author["name"]:
                        first_response = parse_date(note.created_at)
                        break
            except Exception:
                first_response = None

            response_time_hours = None
            if first_response and first_response > created:
                response_time_hours = (first_response - created).total_seconds() / 3600

            data.append({
                "iid": mr.iid,
                "title": mr.title[:55],
                "author": mr.author["name"] if mr.author else "?",
                "total_hours": round(total_hours, 1),
                "response_hours": round(response_time_hours, 1) if response_time_hours else None,
            })

        if not data:
            return "📭 No se pudieron procesar MRs mergeados."

        avg_total = sum(d["total_hours"] for d in data) / len(data)
        resp_hours = [d["response_hours"] for d in data if d["response_hours"]]
        avg_response = sum(resp_hours) / len(resp_hours) if resp_hours else None

        if avg_total < 4:
            speed = "⚡ Muy rápida"
        elif avg_total < 24:
            speed = "✅ Normal"
        elif avg_total < 72:
            speed = "⏳ Lenta"
        else:
            speed = "🐢 Muy lenta"

        result = (
            f"⏱️ *Tiempo de Revisión* — {project.name}\n"
            f"{len(data)} MRs mergeados\n\n"
            f"*Promedio*: {avg_total:.0f}h ({avg_total/24:.1f} días)\n"
            f"*Velocidad*: {speed}\n"
        )
        if avg_response:
            result += f"*1er comentario*: ~{avg_response:.0f}h\n"
        else:
            result += "*1er comentario*: sin datos\n"

        result += "\n*Detalle*\n"
        for d in sorted(data, key=lambda x: -x["total_hours"])[:10]:
            resp = f"↩️ {d['response_hours']:.0f}h" if d["response_hours"] else "—"
            result += f"· !{d['iid']} {d['total_hours']:.0f}h total ({resp}) — {d['title'][:40]}\n"

        return result
    except Exception as e:
        log.exception("Error en analizar_tiempo_revision_mr")
        return f"Error al analizar tiempos de revisión: {str(e)}"


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL: ANALIZAR GRUPO DE PROYECTOS (NUEVA)
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def analizar_grupo_salud(
    group_id: str,
    max_proyectos: int = 20,
    min_actividad_dias: int = 30,
) -> str:
    """Analiza la salud consolidada de un grupo de GitLab.

    Examina pipelines, ramas, issues y MRs de todos los proyectos activos del
    grupo (incluye subgrupos). Usa Redis cache (REDIS_TTL segundos) para evitar
    consultas repetitivas.

    Args:
        group_id: ID o ruta (URL-encoded) del grupo GitLab (ej: "mi-org" o "42").
        max_proyectos: Máximo de proyectos a analizar (default: 20).
        min_actividad_dias: Proyectos sin actividad en este período se excluyen
                            (default: 30 días).

    Returns:
        Reporte tabular con nombre, última actividad, éxito de pipelines,
        total/stale de ramas e issues abiertos.
    """
    cached = cache_get("grupo_salud", group_id, max_proyectos, min_actividad_dias)
    if cached:
        return cached

    gl = get_gitlab_client()
    grupo = gl.groups.get(group_id)

    # ── Listar proyectos del grupo ──────────────────────────────────────────
    proyectos = grupo.projects.list(
        all=True,
        per_page=max_proyectos,
        sort="desc",
        order_by="last_activity_at",
        include_subgroups=True,
        simple=True,
    )

    if not proyectos:
        return f"## Grupo `{group_id}`\n\n_No se encontraron proyectos en este grupo._"

    # ── Filtro por actividad ────────────────────────────────────────────────
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_actividad_dias)
    activos = []
    for p in proyectos:
        if p.last_activity_at:
            last = parse_date(p.last_activity_at)
            if last >= cutoff:
                activos.append(p)

    activos = activos[:max_proyectos]
    log.info("Grupo %s: %d proyectos (filtrados de %d)", group_id, len(activos), len(proyectos))

    if not activos:
        return (
            f"## Grupo `{group_id}`\n\n"
            f"Ningún proyecto del grupo tuvo actividad en los últimos "
            f"{min_actividad_dias} días."
        )

    # ── Colectar métricas por proyecto ──────────────────────────────────────
    rows = []
    for p in activos:
        try:
            project = gl.projects.get(p.id, statistics=False)

            # Últimos pipelines
            pipelines = project.pipelines.list(
                per_page=5, order_by="id", sort="desc"
            )
            if pipelines:
                last_status = pipelines[0].status
                success_count = sum(1 for pp in pipelines if pp.status == "success")
                pipeline_rate = f"{success_count}/{len(pipelines)}"
            else:
                last_status = "—"
                pipeline_rate = "—"

            # Ramas (stale = sin commit >60 días, no protegidas)
            try:
                branches = project.branches.list(all=True)
                total_ramas = len(branches)
                stale = 0
                now = datetime.now(timezone.utc)
                for b in branches:
                    if not getattr(b, "protected", False):
                        committed = parse_date(b.commit["committed_date"])
                        if (now - committed).days > 60:
                            stale += 1
            except Exception:
                total_ramas = 0
                stale = 0

            for issue_attr in ("open_issues_count", "issues_count"):
                issues_abiertos = getattr(p, issue_attr, None)
                if issues_abiertos is not None:
                    break
            else:
                issues_abiertos = 0

            rows.append(
                {
                    "proyecto": project.name,
                    "última_actividad": (
                        str(project.last_activity_at)[:10]
                        if project.last_activity_at
                        else "—"
                    ),
                    "pipelines_ok": pipeline_rate,
                    "último_status": last_status,
                    "ramas": total_ramas,
                    "stale": stale,
                    "issues": issues_abiertos,
                }
            )
        except Exception as e:
            log.warning("Error al leer proyecto %s: %s", getattr(p, "name", "?"), e)

    if not rows:
        return (
            f"📭 No se pudieron obtener métricas del grupo *{group_id}*."
        )

    # Resumen
    total_pipelines_ok = sum(1 for r in rows if r["pipelines_ok"] != "—" and int(r["pipelines_ok"].split("/")[0]) > 0)
    total_stale = sum(r["stale"] for r in rows)
    total_issues = sum(r["issues"] for r in rows)

    result = (
        f"🏢 *Grupo* {group_id}\n"
        f"{len(rows)} proyectos activos (de {len(proyectos)} totales)\n\n"
        f"*Resumen*\n"
        f"· Proyectos con pipelines ok: {total_pipelines_ok}/{len(rows)}\n"
        f"· Ramas stale totales: {total_stale}\n"
        f"· Issues abiertos totales: {total_issues}\n\n"
        f"*Proyectos*\n"
    )
    for r in sorted(rows, key=lambda x: x["proyecto"]):
        result += (
            f"▸ *{r['proyecto']}* — "
            f"pipelines: {r['pipelines_ok']} · "
            f"ramas: {r['ramas']} ({r['stale']} stale) · "
            f"issues: {r['issues']}\n"
        )

    cache_set("grupo_salud", result, group_id, max_proyectos, min_actividad_dias)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  TOOL: VISIÓN GENERAL (NUEVA)
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def analizar_vision_general(
    max_proyectos: int = 20,
    min_actividad_dias: int = 30,
) -> str:
    """Panorama general de los proyectos más activos en todo el GitLab.

    Examina los proyectos que tuvieron actividad reciente en toda la instancia
    y devuelve un tablero comparativo con métricas básicas de cada uno.
    Útil para líderes técnicos que quieren entender el pulso del equipo/org.

    Args:
        max_proyectos: Máximo de proyectos a incluir (default: 20).
        min_actividad_dias: Solo proyectos con actividad en este período
                            (default: 30 días).

    Returns:
        Reporte con nombre, namespace, última actividad, última vez que se
        ejecutaron pipelines, ramas totales y stale, issues abiertos.
    """
    cached = cache_get("vision_general", max_proyectos, min_actividad_dias)
    if cached:
        return cached

    gl = get_gitlab_client()

    # ── Obtener proyectos ordenados por última actividad ────────────────────
    proyectos = gl.projects.list(
        all=True,
        per_page=max_proyectos,
        sort="desc",
        order_by="last_activity_at",
        simple=True,
    )

    if not proyectos:
        return "_No se encontraron proyectos accesibles._"

    # ── Filtro por actividad ────────────────────────────────────────────────
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_actividad_dias)
    activos = []
    for p in proyectos:
        if p.last_activity_at:
            last = parse_date(p.last_activity_at)
            if last >= cutoff:
                activos.append(p)

    activos = activos[:max_proyectos]
    log.info("Visión general: %d proyectos activos de %d totales", len(activos), len(proyectos))

    if not activos:
        return (
            f"No se encontraron proyectos con actividad en los últimos "
            f"{min_actividad_dias} días."
        )

    # ── Métricas livianas por proyecto ──────────────────────────────────────
    rows = []
    for p in activos:
        try:
            project = gl.projects.get(p.id, statistics=False)

            pipelines = project.pipelines.list(
                per_page=3, order_by="id", sort="desc"
            )
            ultimo_pipeline = pipelines[0].created_at[:10] if pipelines else "—"

            try:
                branches = project.branches.list(all=True)
                total_ramas = len(branches)
                stale = 0
                now = datetime.now(timezone.utc)
                for b in branches:
                    if not getattr(b, "protected", False):
                        committed = parse_date(b.commit["committed_date"])
                        if (now - committed).days > 60:
                            stale += 1
            except Exception:
                total_ramas = 0
                stale = 0

            for issue_attr in ("open_issues_count", "issues_count"):
                issues_val = getattr(p, issue_attr, None)
                if issues_val is not None:
                    break
            else:
                issues_val = 0

            rows.append(
                {
                    "namespace": p.namespace.get("full_path", "?"),
                    "proyecto": project.name,
                    "última_actividad": (
                        str(project.last_activity_at)[:10]
                        if project.last_activity_at
                        else "—"
                    ),
                    "último_pipeline": ultimo_pipeline,
                    "ramas": total_ramas,
                    "stale": stale,
                    "issues": issues_val,
                }
            )
        except Exception as e:
            log.warning("Error al leer proyecto %s: %s", getattr(p, "name", "?"), e)

    if not rows:
        return "📭 No se pudieron obtener métricas de los proyectos."

    total_stale = sum(r["stale"] for r in rows)
    total_issues = sum(r["issues"] for r in rows)

    result = (
        f"📊 *Visión General*\n"
        f"{len(rows)} proyectos activos (de {len(proyectos)})\n\n"
        f"*Resumen*\n"
        f"· Ramas stale: {total_stale}\n"
        f"· Issues abiertos: {total_issues}\n\n"
        f"*Proyectos*\n"
    )
    for r in sorted(rows, key=lambda x: x["última_actividad"], reverse=True):
        result += (
            f"▸ *{r['proyecto']}* ({r['namespace']})\n"
            f"  📅 {r['última_actividad']} · "
            f"🔄 {r['último_pipeline']} · "
            f"🌿 {r['ramas']} ({r['stale']} stale) · "
            f"🎫 {r['issues']} issues\n"
        )

    cache_set("vision_general", result, max_proyectos, min_actividad_dias)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  PUNTO DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="GitLab Advanced Analytics MCP Server"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="sse",
        help="Transporte MCP (default: sse — http://0.0.0.0:8000/sse; usar stdio para docker exec)",
    )
    # host y port se configuran en el constructor de FastMCP arriba.
    # En docker-compose se usan los defaults (0.0.0.0:8000).
    args = parser.parse_args()

    log.info("Iniciando GitLab Analytics MCP Server (transporte=%s)", args.transport)
    try:
        mcp.run(transport=args.transport)
    except KeyboardInterrupt:
        log.info("Servidor detenido por el usuario.")
    except Exception as e:
        log.exception("Error fatal en el servidor MCP")
        sys.exit(1)
