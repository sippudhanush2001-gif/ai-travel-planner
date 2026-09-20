"""LangGraph orchestrator.

Workflow (StateGraph):

    START -> validate -> research -> plan -> review --+--> finalize -> END
                                         (interrupt)  +--> research   (revise target: research)
                                                      +--> plan       (revise target: plan | modify)

* ``validate``   — revalidates the request (defense in depth; the API already validates).
* ``research``   — Research Agent gathers destination intelligence + weather.
* ``plan``       — Itinerary Agent turns research into a draft plan.
* ``review``     — **interrupt()** pauses the graph and surfaces the draft for
                   human-in-the-loop review. Resumed with ``approve`` | ``revise`` |
                   ``modify`` via ``Command(resume=...)``.
* ``finalize``   — writes the approved plan as the final output.

The loop between ``review`` and ``research``/``plan`` supports revisions; a
revision cap (``MAX_REVISIONS``) forces the workflow forward so it can't spin
forever.
"""

from __future__ import annotations

from datetime import datetime, timezone

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agents.itinerary import ItineraryAgent
from app.agents.research import ResearchAgent
from app.config import Settings
from app.models.schemas import ItineraryPlan, TravelRequest
from app.orchestrator.state import PlanState, max_revisions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def validate_node(state: PlanState) -> dict:
    try:
        request = TravelRequest.model_validate(state["request"])
        return {
            "request": request.model_dump(mode="json"),
            "phase": "processing",
            "error": None,
            "updated_at": _now(),
        }
    except Exception as exc:  # noqa: BLE001 - normalize to a state error
        return {
            "phase": "error",
            "error": f"Invalid travel request: {exc}",
            "updated_at": _now(),
        }


def research_node(state: PlanState, research_agent: ResearchAgent) -> dict:
    feedback = state.get("feedback")
    report, tools = research_agent.run(state["request"], feedback)
    return {
        "research": report,
        "research_tools": tools,
        "phase": "planning",
        "revisions": _bump_revisions(state),
        "updated_at": _now(),
    }


def plan_node(state: PlanState, itinerary_agent: ItineraryAgent) -> dict:
    feedback = state.get("feedback") or {}
    modifications = (
        feedback.get("modifications") if feedback.get("action") == "modify" else None
    )
    draft, tools = itinerary_agent.run(
        state["request"], state.get("research"), feedback, modifications
    )
    return {
        "draft_plan": draft,
        "phase": "review",
        "revisions": _bump_revisions(state),
        "updated_at": _now(),
    }


def review_node(state: PlanState) -> dict:
    """Human-in-the-loop gate. Pauses the graph until the user reviews."""
    decision = interrupt(
        {
            "message": "The draft itinerary is ready for your review.",
            "draft_plan": state.get("draft_plan"),
            "instructions": {
                "approve": "Send {\"action\": \"approve\"} to accept this plan.",
                "revise": (
                    "Send {\"action\": \"revise\", \"comments\": \"...\", "
                    "\"target\": \"plan\" | \"research\"} to request changes."
                ),
                "modify": (
                    "Send {\"action\": \"modify\", \"modifications\": {"
                    "\"hotel\": \"...\", \"days\": {\"1\": {\"title\": \"...\", "
                    "\"activities\": [...]}}, \"budget\": {\"max\": 4000}}} to "
                    "adjust specific parts of the plan."
                ),
            },
        }
    )
    return {"feedback": decision or {}, "updated_at": _now()}


def _bump_revisions(state: PlanState) -> int:
    feedback = state.get("feedback")
    # A revision only counts when human feedback was already given.
    return (state.get("revisions", 0) + 1) if feedback else state.get("revisions", 0)


def route_after_validate(state: PlanState) -> str:
    return "research" if not state.get("error") else END


def route_after_review(state: PlanState, settings: Settings) -> str:
    feedback = state.get("feedback") or {}
    action = feedback.get("action")
    if action == "approve":
        return "finalize"
    if state.get("revisions", 0) >= max_revisions(settings):
        # Cap reached -> stop iterating and finalize the latest draft.
        return "finalize"
    if action == "revise":
        return "research" if feedback.get("target") == "research" else "plan"
    return "plan"  # modify (or unknown action) -> re-plan with modifications


def finalize_node(state: PlanState, settings: Settings) -> dict:
    draft = state.get("draft_plan")
    value = dict(draft) if isinstance(draft, dict) else {}
    feedback = state.get("feedback") or {}

    forced = feedback.get("action") != "approve"
    if forced:
        overview = value.get("overview", "")
        value["overview"] = (
            f"{overview} [Plan finalized after reaching the revision limit "
            f"({max_revisions(settings)}); latest changes applied.]".strip()
        )

    validated = ItineraryPlan.model_validate(value)
    return {
        "final_plan": validated.model_dump(mode="json"),
        "phase": "finalized",
        "updated_at": _now(),
    }


# --------------------------------------------------------------------------- #
# Graph construction
# --------------------------------------------------------------------------- #
def build_workflow_graph(settings: Settings, checkpointer):
    research_agent = ResearchAgent(settings)
    itinerary_agent = ItineraryAgent(settings)

    builder = StateGraph(PlanState)

    builder.add_node("validate", validate_node)
    builder.add_node("research", lambda s: research_node(s, research_agent))
    builder.add_node("plan", lambda s: plan_node(s, itinerary_agent))
    builder.add_node("review", review_node)
    builder.add_node("finalize", lambda s: finalize_node(s, settings))

    builder.set_entry_point("validate")
    builder.add_conditional_edges(
        "validate",
        route_after_validate,
        {"research": "research", END: END},
    )
    builder.add_edge("research", "plan")
    builder.add_edge("plan", "review")
    builder.add_conditional_edges(
        "review",
        lambda s: route_after_review(s, settings),
        {"research": "research", "plan": "plan", "finalize": "finalize"},
    )
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)


__all__ = ["build_workflow_graph"]