"""The state schema shared by the LangGraph workflow.

Everything is kept JSON-serializable (``dict``s) so the graph state can be
written to the SQLite checkpointer and survives process restarts.
"""

from __future__ import annotations

from typing import TypedDict

from app.config import Settings


class PlanState(TypedDict):
    plan_id: str
    request: dict
    phase: str
    research: dict | None
    research_tools: dict | None
    draft_plan: dict | None
    final_plan: dict | None
    feedback: dict | None
    revisions: int
    error: str | None
    created_at: str
    updated_at: str


# Phases
PHASE_PROCESSING = "processing"
PHASE_PLANNING = "planning"
PHASE_REVIEW = "review"
PHASE_FINALIZED = "finalized"
PHASE_ERROR = "error"

PHASE_MESSAGES = {
    PHASE_PROCESSING: "Workflow is running…",
    PHASE_PLANNING: "Research complete; building the itinerary…",
    PHASE_REVIEW: "Draft itinerary is ready. Approve, revise, or modify.",
    PHASE_FINALIZED: "Plan approved and finalized.",
    PHASE_ERROR: "Workflow failed.",
}


def phase_message(phase: str) -> str:
    return PHASE_MESSAGES.get(phase, "")


def max_revisions(settings: Settings) -> int:
    return settings.max_revisions