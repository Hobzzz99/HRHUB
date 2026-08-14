"""Readiness has to be able to fail.

DEPLOYMENT.md gates a deploy on the health check. Until now that check was a
static dict — it returned 200 with Postgres down, with Redis down, and with
migrations unapplied, which are the exact three failures it was being run to
rule out.

Liveness stays dependency-free on purpose: a database blip should not make an
orchestrator kill a process that is only waiting for the database to come back.
"""

from __future__ import annotations

from app.api.routes import health


def test_liveness_needs_no_dependencies(client, monkeypatch):
    """It must answer even when everything it talks to is down."""
    monkeypatch.setattr(health, "_check_database", lambda: "connection refused")
    monkeypatch.setattr(health, "_check_redis", lambda: "connection refused")

    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readiness_is_ok_when_dependencies_answer(client, monkeypatch):
    monkeypatch.setattr(health, "_check_database", lambda: None)
    monkeypatch.setattr(health, "_check_redis", lambda: None)

    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


def test_readiness_fails_when_the_database_is_down(client, monkeypatch):
    monkeypatch.setattr(health, "_check_database", lambda: "could not connect")
    monkeypatch.setattr(health, "_check_redis", lambda: None)

    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["database"] == "could not connect"


def test_readiness_fails_when_redis_is_down(client, monkeypatch):
    """Redis carries the job queue, so the API can look healthy while no
    search a recruiter starts will ever reach a worker."""
    monkeypatch.setattr(health, "_check_database", lambda: None)
    monkeypatch.setattr(health, "_check_redis", lambda: "connection refused")

    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
