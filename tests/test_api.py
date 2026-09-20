"""HTTP API tests via FastAPI TestClient (offline/mock providers)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def _client(settings, manager):
    return TestClient(create_app(settings=settings, manager=manager))


def test_health(settings, manager):
    client = _client(settings, manager)
    assert client.get("/health").json() == {"status": "ok"}


def test_full_cycle(settings, manager, request_payload):
    client = _client(settings, manager)

    resp = client.post("/plan", json=request_payload.model_dump(mode="json"))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    plan_id = body["plan_id"]
    assert body["phase"] in {"processing", "review"}

    status = client.get(f"/plan/{plan_id}")
    assert status.status_code == 200, status.text
    info = status.json()
    assert info["plan_id"] == plan_id
    assert info["draft_plan"] is not None

    # Final should be unavailable before approval
    final_before = client.get(f"/plan/{plan_id}/final")
    assert final_before.status_code == 409

    review = client.post(
        f"/plan/{plan_id}/review", json={"action": "approve"}
    )
    assert review.status_code == 200, review.text
    assert review.json()["phase"] == "finalized"

    final = client.get(f"/plan/{plan_id}/final")
    assert final.status_code == 200, final.text
    data = final.json()
    assert data["plan_id"] == plan_id
    assert len(data["final_plan"]["days"]) > 0


def test_validation_errors(settings, manager):
    client = _client(settings, manager)

    # Bad dates
    payload = {
        "destination": "Paris",
        "start_date": "2026-06-15",
        "end_date": "2026-06-10",
        "budget": {"min_amount": 100, "max_amount": 500, "currency": "USD"},
        "interests": ["art"],
        "travelers": 2,
    }
    assert client.post("/plan", json=payload).status_code == 422

    # Bad budget ordering
    payload["start_date"] = "2026-06-10"
    payload["end_date"] = "2026-06-15"
    payload["budget"] = {"min_amount": 900, "max_amount": 100, "currency": "USD"}
    assert client.post("/plan", json=payload).status_code == 422

    # Missing interests
    payload["budget"] = {"min_amount": 100, "max_amount": 500, "currency": "USD"}
    payload.pop("interests")
    assert client.post("/plan", json=payload).status_code == 422


def test_unknown_plan_returns_404(settings, manager):
    client = _client(settings, manager)
    assert client.get("/plan/nope").status_code == 404
    assert client.get("/plan/nope/final").status_code == 404
    assert client.post("/plan/nope/review", json={"action": "approve"}).status_code == 404


def test_review_conflict_when_not_paused(settings, manager, request_payload):
    client = _client(settings, manager)
    resp = client.post("/plan", json=request_payload.model_dump(mode="json"))
    plan_id = resp.json()["plan_id"]

    client.post(f"/plan/{plan_id}/review", json={"action": "approve"})
    # Second review on an already-finalized plan
    second = client.post(f"/plan/{plan_id}/review", json={"action": "approve"})
    assert second.status_code == 409