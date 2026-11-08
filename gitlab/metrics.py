"""
GitLab — Métricas avanzadas de desarrollo (Fase 2).

Funciones de cálculo puras + recolector con degradación elegante:
si la API falla, se loggea y se devuelven campos None para que el
reporte omita la sección sin romper el PDF.
"""
from __future__ import annotations

import datetime
import logging

from common.http_client import ApiError

log = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def merge_request_metrics(api, pid: int, days: int = 90) -> dict | None:
    """MRs de la ventana: abiertos, mergeados, tasa de merge y tiempo medio
    de revisión (created_at → merged_at), en días."""
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=days)).date().isoformat()
    try:
        mrs = api.paginate(f"/projects/{pid}/merge_requests",
                           {"state": "all", "created_after": since})
    except ApiError:
        log.warning("Merge requests no disponibles para el proyecto %s", pid)
        return None

    opened = sum(1 for m in mrs if m.get("state") == "opened")
    merged = [m for m in mrs if m.get("state") == "merged"]
    closed = sum(1 for m in mrs if m.get("state") == "closed")
    decided = len(merged) + closed
    review_days = []
    for m in merged:
        created, merged_at = _parse_dt(m.get("created_at")), _parse_dt(m.get("merged_at"))
        if created and merged_at:
            review_days.append((merged_at - created).total_seconds() / 86400)
    return {
        "mr_open": opened,
        "mr_merged": len(merged),
        "mr_merge_rate": round(len(merged) / decided * 100, 1) if decided else None,
        "mr_avg_review_days": round(sum(review_days) / len(review_days), 1) if review_days else None,
    }


def activity_metrics(api, pid: int, days: int = 90) -> dict | None:
    """Contribuidores activos (commits en la ventana) vs. históricos."""
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=days)).date().isoformat()
    try:
        commits = api.paginate(f"/projects/{pid}/repository/commits", {"since": since})
    except ApiError:
        log.warning("Commits no disponibles para el proyecto %s", pid)
        return None
    try:
        contributors = api._get(f"/projects/{pid}/repository/contributors")
    except ApiError:
        log.warning("Contributors no disponibles para el proyecto %s", pid)
        contributors = []

    active = sorted({c.get("author_name", "") for c in commits if c.get("author_name")})
    historic = {c.get("name", "") for c in contributors if isinstance(c, dict)}
    inactive = sorted(historic - set(active))
    return {
        "commits": len(commits),
        "active_contributors": active,
        "inactive_contributors": inactive,
    }


def topics_from_project(p: dict) -> list[str]:
    """Topics/etiquetas del proyecto — sin llamada extra (vienen en /projects)."""
    topics = p.get("topics") or p.get("tag_list") or []
    return [str(t) for t in topics if t]


def collect_metrics(api, p: dict, cfg: dict) -> dict:
    """Recolecta las métricas Fase 2 de un proyecto GitLab.
    Nunca lanza: cada métrica degrada a None con warning."""
    g = cfg.get("gitlab", {})
    days = int(g.get("activity_days", 90))
    pid = p["id"]
    out: dict = {"topics": topics_from_project(p)}
    if g.get("include_merge_requests", True):
        out.update({
            "mrs": merge_request_metrics(api, pid, days),
            "activity": activity_metrics(api, pid, days),
        })
    return out
