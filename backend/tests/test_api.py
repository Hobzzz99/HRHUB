"""End-to-end API tests over the mock provider (auth disabled in test env)."""

from __future__ import annotations


def _create_search(client, **overrides):
    payload = {
        "job_title": "Backend Engineer",
        "skills": ["Python", "FastAPI", "Docker", "AWS"],
        "location": "Berlin",
        "min_experience": 5,
        "max_results": 10,
        "min_match_score": 40,
    }
    payload.update(overrides)
    return client.post("/search", json=payload)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_full_search_flow(client):
    # Create → runs eagerly → completes.
    resp = _create_search(client)
    assert resp.status_code == 202
    search = resp.json()
    assert search["status"] in {"queued", "running", "completed"}
    search_id = search["id"]

    # Status should be completed after the eager job.
    status_resp = client.get(f"/search/{search_id}")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == "completed"
    assert body["progress"]["found"] >= 10
    assert body["result_count"] >= 1

    # Results are ranked and above threshold.
    results = client.get(f"/search/{search_id}/results").json()
    assert len(results) >= 1
    scores = [r["match_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(s >= 40 for s in scores)
    assert results[0]["rank"] == 1
    # Strong Python/FastAPI candidates should surface at the top.
    assert results[0]["candidate"]["total_experience_years"] > 0


def test_min_experience_filters_juniors(client):
    resp = _create_search(client, min_experience=8, min_match_score=0)
    search_id = resp.json()["id"]
    results = client.get(f"/search/{search_id}/results").json()
    for r in results:
        assert r["candidate"]["total_experience_years"] >= 8


def test_save_and_list_saved(client):
    search_id = _create_search(client).json()["id"]
    results = client.get(f"/search/{search_id}/results").json()
    candidate_id = results[0]["candidate"]["id"]

    save = client.post("/candidate/save", json={"candidate_id": candidate_id, "notes": "great"})
    assert save.status_code == 201

    saved = client.get("/saved").json()
    assert len(saved) == 1
    assert saved[0]["candidate"]["id"] == candidate_id
    assert saved[0]["notes"] == "great"

    # Unsave.
    assert client.delete(f"/candidate/save/{candidate_id}").status_code == 204
    assert client.get("/saved").json() == []


def test_candidate_detail(client):
    search_id = _create_search(client).json()["id"]
    candidate_id = client.get(f"/search/{search_id}/results").json()[0]["candidate"]["id"]
    detail = client.get(f"/candidate/{candidate_id}").json()
    assert detail["id"] == candidate_id
    assert "experience" in detail
    assert isinstance(detail["skills"], list)


def test_dashboard(client):
    _create_search(client)
    dash = client.get("/dashboard").json()
    assert dash["total_searches"] >= 1
    assert dash["completed_searches"] >= 1
    assert dash["average_match_score"] >= 0
    assert isinstance(dash["top_skills"], list)


def test_export_csv(client):
    search_id = _create_search(client).json()["id"]
    resp = client.get(f"/search/{search_id}/export?fmt=csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "match_score" in resp.text


def test_second_user_cannot_see_first_users_search(client, monkeypatch):
    """Auth scoping: results are per-user."""
    search_id = _create_search(client).json()["id"]

    # Simulate a different authenticated user.
    from app.core import security

    other = security.CurrentUser(id="00000000-0000-0000-0000-0000000000ff", email="b@x")
    monkeypatch.setattr(security, "_dev_user", lambda: other)

    resp = client.get(f"/search/{search_id}")
    assert resp.status_code == 404
