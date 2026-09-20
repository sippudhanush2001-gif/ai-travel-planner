"""Interactive CLI demo of the workflow (no API server required).

Usage:
    travel-planner
    python -m app.cli

Runs a hard-coded trip through the full approximate/revise/approve cycle.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from app.config import get_settings
from app.models.schemas import ReviewFeedback, TravelRequest
from app.runtime.manager import WorkflowManager


def _sample_request() -> TravelRequest:
    start = date.today() + timedelta(days=21)
    return TravelRequest(
        destination="Paris",
        start_date=start,
        end_date=start + timedelta(days=4),
        budget={"min_amount": 1800, "max_amount": 3500, "currency": "USD"},
        interests=["art", "food", "culture", "architecture"],
        travelers=2,
        travel_style="cultural",
        notes="Prefer walking over taxis; love museums.",
    )


def main() -> None:
    settings = get_settings()
    print(f"Provider: LLM={settings.llm_provider!r} "
          f"web_search={settings.web_search_provider!r} "
          f"weather={settings.weather_provider!r}\n")

    manager = WorkflowManager(settings)
    request = _sample_request()
    print("Submitting:", json.dumps(request.model_dump(), default=str)[:140], "...")

    record = manager.submit(request)
    print(f"plan_id={record.plan_id}  phase={record.phase!r}")
    print("-" * 60)

    if record.can_review and record.draft_plan:
        days = record.draft_plan.get("days", [])
        print(f"Draft has {len(days)} day(s); first day activities: "
              f"{[a.get('title') for a in days[0].get('activities', []) if a]}")

    # Round 1: revise with feedback
    record = manager.review(
        record.plan_id,
        ReviewFeedback(
            action="revise",
            comments="Add one quiet morning and swap day 2 lunch to seafood.",
            target="plan",
        ),
    )
    print(f"After revise: phase={record.phase!r} revisions={record.revisions}")

    # Round 2: modify a specific part
    record = manager.review(
        record.plan_id,
        ReviewFeedback(
            action="modify",
            modifications={"hotel": "Boutique Saint-Antoine", "budget": {"max": 4000}},
        ),
    )
    print(f"After modify: phase={record.phase!r} hotel="
          f"{record.draft_plan.get('hotels', [{}])[0].get('name') if record.draft_plan else None}")

    # Round 3: approve
    record = manager.review(record.plan_id, ReviewFeedback(action="approve"))
    print(f"After approve: phase={record.phase!r}")

    final = record.final_plan or {}
    print("-" * 60)
    print("FINAL PLAN")
    print(f"  {final.get('destination')}  {final.get('start_date')} -> {final.get('end_date')}")
    print(f"  Budget: {final.get('budget_min')}-{final.get('budget_max')} {final.get('currency')}")
    print(f"  Overview: {str(final.get('overview'))[:120]}...")
    for day in final.get("days", []):
        titles = [a.get("title") for a in day.get("activities", [])]
        print(f"  Day {day.get('day')}: {day.get('title')} -> {titles}")


if __name__ == "__main__":
    main()