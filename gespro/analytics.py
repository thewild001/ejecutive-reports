"""
GESPRO/Redmine — Análisis de tendencias (Fase 2).

Todo se computa sobre la lista de issues ya recolectada (created_on /
closed_on), sin llamadas extra a la API. Funciones puras: sin red, sin I/O.
"""
from __future__ import annotations

import datetime
from collections import Counter


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _status_of(issue: dict) -> str:
    st = issue.get("status")
    return st.get("name", "") if isinstance(st, dict) else str(st or "")


def period_windows(issues: list[dict], days: int = 30) -> dict:
    """Creadas/cerradas en la ventana actual vs. la ventana anterior."""
    today = datetime.date.today()
    start_curr = today - datetime.timedelta(days=days)
    start_prev = today - datetime.timedelta(days=2 * days)

    def _count(field: str, low: datetime.date, high: datetime.date) -> int:
        return sum(1 for i in issues
                   if (d := _parse_date(i.get(field))) and low <= d < high)

    mid_prev_end = start_curr  # ventana anterior: [start_prev, start_curr)
    return {
        "days": days,
        "created_current": _count("created_on", start_curr, today + datetime.timedelta(days=1)),
        "created_previous": _count("created_on", start_prev, mid_prev_end),
        "closed_current": _count("closed_on", start_curr, today + datetime.timedelta(days=1)),
        "closed_previous": _count("closed_on", start_prev, mid_prev_end),
    }


def weekly_velocity(issues: list[dict], days: int = 30) -> float | None:
    """Tareas cerradas por semana en la ventana actual."""
    w = period_windows(issues, days)
    if days <= 0:
        return None
    return round(w["closed_current"] / (days / 7), 1)


def status_bottlenecks(issues: list[dict], closed_names: set[str],
                       min_share: float = 0.40) -> list[dict]:
    """Estados abiertos que concentran una proporción relevante de las
    tareas abiertas — candidatos a cuello de botella del flujo."""
    open_issues = [i for i in issues
                   if _status_of(i).lower() not in closed_names]
    if not open_issues:
        return []
    counts = Counter(_status_of(i) for i in open_issues)
    total = len(open_issues)
    return [
        {"status": name, "count": n, "share": round(n / total * 100, 1)}
        for name, n in counts.most_common()
        if n / total >= min_share
    ]


def member_load_trend(member_issues: list[dict], closed_names: set[str],
                      days: int = 30) -> str:
    """'creciente' si abiertas > cerradas en la ventana; 'decreciente' si al
    contrario; 'estable' en otro caso."""
    open_n = sum(1 for i in member_issues
                 if _status_of(i).lower() not in closed_names)
    start_curr = datetime.date.today() - datetime.timedelta(days=days)
    closed_n = sum(1 for i in member_issues
                   if (d := _parse_date(i.get("closed_on"))) and d >= start_curr)
    if open_n > closed_n:
        return "creciente"
    if open_n < closed_n:
        return "decreciente"
    return "estable"


def analyze_trends(issues: list[dict], members: list[dict],
                   closed_names: set[str], days: int = 30) -> dict:
    """Paquete completo de analítica de un proyecto GESPRO."""
    trends_by_member = {}
    for m in members:
        mine = [i for i in issues
                if (i.get("assigned_to") or {}).get("id") == m.get("id")]
        trends_by_member[m.get("name", "?")] = member_load_trend(
            mine, closed_names, days)
    return {
        "windows": period_windows(issues, days),
        "velocity": weekly_velocity(issues, days),
        "bottlenecks": status_bottlenecks(issues, closed_names),
        "member_trends": trends_by_member,
    }
