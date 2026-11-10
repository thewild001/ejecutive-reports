"""Panel web: datasets del cron, API y descarga segura."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from common import dashboard_data
from web import app as web_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "_out_dir", lambda: tmp_path)
    return TestClient(web_app.app), tmp_path


def test_save_and_history(tmp_path):
    for open_ in (10, 8):
        dashboard_data.save_dataset(tmp_path, "gespro", {"open": open_, "label": "x"},
                                    [{"name": "A"}], {"k": 1})
    d = dashboard_data.load_dataset(tmp_path, "gespro")
    assert d["totals"]["open"] == 8 and d["projects"] == [{"name": "A"}]
    assert [h["open"] for h in d["history"]] == [10, 8]
    assert "label" not in d["history"][0]  # solo numéricos


def test_load_missing_returns_none(tmp_path):
    assert dashboard_data.load_dataset(tmp_path, "gitlab") == {}


def test_api_empty_state(client):
    c, _ = client
    body = c.get("/api/dashboard").json()
    assert body["sources"] == {} and body["bands"]["gitlab"] == [75, 60]


def test_api_with_data_and_reports(client):
    c, out = client
    dashboard_data.save_dataset(out, "gitlab", {"avg_health": 70}, [{"name": "r"}], {})
    (out / "gitlab_ejecutivo_2026-11-10.pdf").write_bytes(b"%PDF")
    body = c.get("/api/dashboard").json()
    assert body["sources"]["gitlab"]["totals"]["avg_health"] == 70
    assert [r["name"] for r in body["reports"]] == ["gitlab_ejecutivo_2026-11-10.pdf"]


def test_index_served(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200 and "Panel de proyectos" in r.text


def test_download_ok_and_traversal(client):
    c, out = client
    (out / "a.pdf").write_bytes(b"%PDF")
    (out.parent / "secreto.txt").write_text("x")
    assert c.get("/download/a.pdf").status_code == 200
    assert c.get("/download/..%2Fsecreto.txt").status_code in (400, 404)
    assert c.get("/download/.dashboard_gitlab.json").status_code == 400
    assert c.get("/download/nope.pdf").status_code == 404
