"""Tests de Fase 2: métricas GitLab/GESPRO y parser RSS (sin red)."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gespro.analytics import (
    member_load_trend, period_windows, status_bottlenecks, weekly_velocity,
)
from trends.rss_fetcher import build_draft, parse_feed

CLOSED = {"cerrada", "resuelta", "closed", "resolved"}

TODAY = datetime.date.today()


def _d(days_ago: int) -> str:
    return (TODAY - datetime.timedelta(days=days_ago)).isoformat()


def _issue(status="Abierta", created=None, closed=None, assignee=None):
    return {
        "status": {"name": status},
        "created_on": created,
        "closed_on": closed,
        "assigned_to": {"id": assignee} if assignee else None,
    }


# ── period_windows / velocity ────────────────────────────────────────────

def test_period_windows_counts_current_and_previous():
    issues = [
        _issue(created=_d(5)),            # creada en ventana actual
        _issue(created=_d(40)),           # creada en ventana anterior
        _issue(status="Cerrada", created=_d(50), closed=_d(3)),   # cerrada actual
        _issue(status="Cerrada", created=_d(90), closed=_d(45)),  # cerrada anterior
        _issue(created=None, closed=None),                      # sin fechas
    ]
    w = period_windows(issues, days=30)
    assert w["created_current"] == 1
    assert w["created_previous"] == 2  # _d(40) + la cerrada-actual creada _d(50)
    assert w["closed_current"] == 1
    assert w["closed_previous"] == 1


def test_weekly_velocity():
    issues = [_issue(status="Cerrada", created=_d(60), closed=_d(i + 1))
              for i in range(4)]
    # 4 cierres en 28 días → 1 por semana
    assert weekly_velocity(issues, days=28) == 1.0
    assert weekly_velocity([], days=30) == 0.0


# ── bottlenecks ──────────────────────────────────────────────────────────

def test_bottlenecks_detects_dominant_status():
    issues = ([_issue(status="En revisión")] * 6
              + [_issue(status="Nueva")] * 2
              + [_issue(status="Cerrada", closed=_d(1))] * 10)
    out = status_bottlenecks(issues, CLOSED, min_share=0.40)
    assert [b["status"] for b in out] == ["En revisión"]
    assert out[0]["share"] == 75.0


def test_bottlenecks_empty_when_no_open():
    assert status_bottlenecks([_issue(status="Cerrada", closed=_d(1))], CLOSED) == []


# ── member_load_trend ────────────────────────────────────────────────────

def test_member_load_trend():
    growing = [_issue(assignee=7)] * 3
    assert member_load_trend(growing, CLOSED) == "creciente"
    shrinking = [_issue(status="Cerrada", closed=_d(2), assignee=7)] * 3
    assert member_load_trend(shrinking, CLOSED) == "decreciente"
    assert member_load_trend([], CLOSED) == "estable"


# ── RSS parsing ──────────────────────────────────────────────────────────

RSS_SAMPLE = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Tech News</title>
  <item><title>Item Uno</title><link>https://x/1</link>
    <description>Detalle uno</description><pubDate>Mon, 01 Sep 2026</pubDate></item>
  <item><title></title></item>
</channel></rss>"""

ATOM_SAMPLE = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry><title>Entrada A</title><link href="https://x/a"/>
    <summary>Resumen A</summary><updated>2026-09-10T00:00:00Z</updated></entry>
</feed>"""


def test_parse_rss_skips_malformed_items():
    feed = parse_feed(RSS_SAMPLE, "https://x")
    assert feed["titulo"] == "Tech News"
    assert len(feed["items"]) == 1
    assert feed["items"][0]["nombre"] == "Item Uno"


def test_parse_atom():
    feed = parse_feed(ATOM_SAMPLE, "https://x")
    assert feed["titulo"] == "Atom Feed"
    assert feed["items"][0]["enlace"] == "https://x/a"
    assert feed["items"][0]["fecha"] == "2026-09-10"


def test_parse_invalid_xml_returns_none():
    assert parse_feed(b"not xml", "https://x") is None


def test_build_draft_structure():
    draft = build_draft([parse_feed(RSS_SAMPLE, "https://x")], ["https://x"])
    assert draft["secciones"][0]["titulo"] == "Tech News"
    assert draft["secciones"][0]["items"][0]["impacto"] == ""
    assert draft["fuentes"] == ["https://x"]
    assert "resumen_ejecutivo" in draft
