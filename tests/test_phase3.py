"""Phase 3 reads: account search, cited sections, demo-mode health, and the UI mount."""

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from billpilot.cli import ledger_customer_count
from billpilot.config import get_settings, normalize_database_url
from billpilot.main import create_app
from billpilot.ui import mount_ui


@pytest.fixture
def client(seeded):
    del seeded
    app = create_app(get_settings())
    with TestClient(app) as test_client:
        yield test_client


def test_database_url_accepts_a_hosted_postgres_scheme():
    neon = "postgresql://billpilot:secret@ep-example.aws.neon.tech/billpilot?sslmode=require"
    assert normalize_database_url(neon) == (
        "postgresql+psycopg://billpilot:secret@ep-example.aws.neon.tech/billpilot?sslmode=require"
    )
    assert normalize_database_url("postgres://billpilot:secret@localhost/billpilot").startswith("postgresql+psycopg://")
    already = "postgresql+psycopg://billpilot:billpilot@localhost:5432/billpilot"
    assert normalize_database_url(already) == already


def test_health_reports_demo_mode_without_a_model_key(client: TestClient):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["demoMode"] is True
    assert body["llmBackend"] == "fake"
    assert body["tracing"] is False


def test_csr_can_search_accounts_by_customer_number(client: TestClient):
    found = client.get(
        "/tmf-api/accountManagement/v4/billingAccount",
        headers={"X-API-Key": "test-csr"},
        params={"q": "CUST-000001"},
    )
    assert found.status_code == 200
    rows = found.json()
    assert len(rows) == 1
    assert rows[0]["customerNumber"] == "CUST-000001"
    assert rows[0]["name"]
    missed = client.get(
        "/tmf-api/accountManagement/v4/billingAccount",
        headers={"X-API-Key": "test-csr"},
        params={"q": "no-such-customer"},
    )
    assert missed.status_code == 200
    assert missed.json() == []


def test_cited_policy_section_is_readable(client: TestClient):
    found = client.get(
        "/knowledge/section",
        headers={"X-API-Key": "test-customer"},
        params={"doc": "roaming.md", "section": "When roaming charges apply"},
    )
    assert found.status_code == 200
    body = found.json()
    assert body["doc"] == "roaming.md"
    assert "roaming" in body["body"].lower()
    missing = client.get(
        "/knowledge/section",
        headers={"X-API-Key": "test-customer"},
        params={"doc": "roaming.md", "section": "Not a section"},
    )
    assert missing.status_code == 404
    anonymous = client.get(
        "/knowledge/section",
        params={"doc": "roaming.md", "section": "When roaming charges apply"},
    )
    assert anonymous.status_code == 401


def test_ui_mount_serves_the_spa_and_leaves_the_api_alone(tmp_path: Path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>BillPilot</title><p>copilot</p>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('billpilot')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    assert mount_ui(app, dist) is True
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "BillPilot" in root.text
        assert client.get("/assets/app.js").text.startswith("console.log")
        assert client.get("/favicon.svg").status_code == 200
        assert client.get("/customer").text == root.text
        assert client.get("/tmf-api/customerBillManagement/v4/customerBill").status_code == 404
        assert client.get("/health").json()["status"] == "ok"
        outside = client.get("/../pyproject.toml")
        assert "[project]" not in outside.text


def test_installed_package_reads_corpus_and_ui_from_the_working_directory(tmp_path: Path, monkeypatch):
    corpus = tmp_path / "docs" / "knowledge"
    corpus.mkdir(parents=True)
    (corpus / "roaming.md").write_text("# Roaming\n", encoding="utf-8")
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("ok", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    import billpilot.agent.knowledge as knowledge
    import billpilot.ui as ui

    real_resolve = Path.resolve

    def installed_layout(self: Path) -> Path:
        resolved = real_resolve(self)
        if resolved.name == "knowledge.py":
            return Path("/opt/site-packages/billpilot/agent/knowledge.py")
        if resolved.name == "ui.py":
            return Path("/opt/site-packages/billpilot/ui.py")
        return resolved

    monkeypatch.setattr(Path, "resolve", installed_layout)
    assert knowledge.knowledge_root() == corpus
    assert ui.ui_dist() == dist


def test_ledger_count_matches_the_test_seed(seeded):
    del seeded
    assert ledger_customer_count(os.environ["DATABASE_URL"]) == 48


def test_create_app_without_a_build_keeps_the_json_root(client: TestClient):
    # The packaged tests do not build web/dist. The JSON root remains for /docs discovery.
    if (Path(__file__).resolve().parents[1] / "web" / "dist" / "index.html").is_file():
        body = client.get("/")
        assert body.status_code == 200
        assert "text/html" in body.headers["content-type"]
        return
    body = client.get("/").json()
    assert body["service"] == "billpilot-mock-bss"
    app = create_app(get_settings())
    assert app.title == "BillPilot mock BSS"
