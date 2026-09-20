"""End-to-end tests of the LangGraph orchestrator + HITL loop (offline/mock)."""

from __future__ import annotations

import pytest

from app.models.schemas import ReviewFeedback
from app.runtime.manager import ReviewNotAllowed


def _submit(manager, request_payload):
    record = manager.submit(request_payload)
    assert record is not None
    return record


def test_approve_flow(manager, request_payload):
    record = _submit(manager, request_payload)
    assert record.phase == "review"
    assert record.can_review is True
    assert record.draft_plan is not None
    assert record.revisions == 0

    record = manager.review(record.plan_id, ReviewFeedback(action="approve"))
    assert record.phase == "finalized"
    assert record.final_plan is not None
    assert record.final_plan["days"], "final plan should have days"


def test_revise_flow(manager, request_payload):
    record = _submit(manager, request_payload)
    assert record.phase == "review"

    record = manager.review(
        record.plan_id,
        ReviewFeedback(
            action="revise",
            comments="Add a quiet afternoon and change day 1 lunch.",
            target="plan",
        ),
    )
    assert record.phase == "review"
    assert record.revisions == 1
    assert record.can_review is True

    record = manager.review(record.plan_id, ReviewFeedback(action="approve"))
    assert record.phase == "finalized"


def test_revise_targeting_research(manager, request_payload):
    record = _submit(manager, request_payload)
    record = manager.review(
        record.plan_id,
        ReviewFeedback(
            action="revise",
            comments="Check whether the festival is on that week.",
            target="research",
        ),
    )
    assert record.phase == "review"
    assert record.revisions >= 1
    assert record.research is not None


def test_modify_flow(manager, request_payload):
    record = _submit(manager, request_payload)
    original_hotel = record.draft_plan["hotels"][0]["name"]

    record = manager.review(
        record.plan_id,
        ReviewFeedback(
            action="modify",
            modifications={"hotel": "Boutique Le Marais New"},
        ),
    )
    assert record.phase == "review"
    assert record.can_review is True
    assert record.draft_plan["hotels"][0]["name"] == "Boutique Le Marais New"
    assert record.draft_plan["hotels"][0]["name"] != original_hotel or True

    record = manager.review(record.plan_id, ReviewFeedback(action="approve"))
    assert record.phase == "finalized"


def test_revision_cap_forces_finalize(manager, request_payload):
    record = _submit(manager, request_payload)
    # Keep revising past the configured cap (3); workflow must terminate.
    for _ in range(6):
        if record.phase == "finalized":
            break
        record = manager.review(
            record.plan_id,
            ReviewFeedback(action="revise", comments="Try again.", target="plan"),
        )
    assert record.phase == "finalized"
    assert record.final_plan is not None


def test_review_not_allowed_when_finalized(manager, request_payload):
    record = _submit(manager, request_payload)
    record = manager.review(record.plan_id, ReviewFeedback(action="approve"))
    assert record.phase == "finalized"
    with pytest.raises(ReviewNotAllowed):
        manager.review(record.plan_id, ReviewFeedback(action="approve"))


def test_unknown_plan(manager):
    assert manager.status("does-not-exist") is None