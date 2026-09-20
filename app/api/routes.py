"""HTTP routes for the travel planner."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_manager
from app.models.schemas import (
    FinalPlanResponse,
    ItineraryPlan,
    PlanCreated,
    PlanStatus,
    ResearchReport,
    ReviewFeedback,
    TravelRequest,
)
from app.runtime.manager import (
    PlanNotFound,
    ReviewNotAllowed,
    WorkflowManager,
)

router = APIRouter(tags=["plans"])


def _to_plan_status(record) -> PlanStatus:
    draft = None
    if isinstance(record.draft_plan, dict):
        try:
            draft = ItineraryPlan.model_validate(record.draft_plan)
        except Exception:  # noqa: BLE001 - tolerate a malformed draft
            draft = None

    research = None
    if isinstance(record.research, dict):
        try:
            research = ResearchReport.model_validate(record.research)
        except Exception:  # noqa: BLE001
            research = None

    return PlanStatus(
        plan_id=record.plan_id,
        phase=record.phase,
        message=record.message,
        draft_plan=draft,
        research=research,
        revisions=record.revisions or 0,
        can_review=record.can_review,
        feedback=record.feedback,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post(
    "/plan",
    response_model=PlanCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new travel request",
)
def create_plan(
    payload: TravelRequest,
    manager: WorkflowManager = Depends(get_manager),
) -> PlanCreated:
    """Validate the request, kick off the orchestrator, and return the plan id.

    The workflow runs in the background; submit returns as soon as the plan has
    either paused at review, finalized, or timed out (still processing).
    """
    record = manager.submit(payload)
    message = "Plan created."
    if record.phase == "review":
        message = "Draft itinerary ready for review."
    elif record.phase == "processing":
        message = "Plan created; workflow still running."
    elif record.phase == "error":
        message = "Plan created but workflow failed."
    return PlanCreated(
        plan_id=record.plan_id,
        phase=record.phase,
        message=message or "",
    )


@router.get(
    "/plan/{plan_id}",
    response_model=PlanStatus,
    summary="Get current plan status and draft",
)
def get_plan(
    plan_id: str,
    manager: WorkflowManager = Depends(get_manager),
) -> PlanStatus:
    try:
        record = manager.status(plan_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown plan '{plan_id}'.",
        )
    return _to_plan_status(record)


@router.post(
    "/plan/{plan_id}/review",
    response_model=PlanStatus,
    summary="Submit human-in-the-loop feedback (approve / revise / modify)",
)
def review_plan(
    plan_id: str,
    feedback: ReviewFeedback,
    manager: WorkflowManager = Depends(get_manager),
) -> PlanStatus:
    try:
        record = manager.review(plan_id, feedback)
    except PlanNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ReviewNotAllowed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown plan '{plan_id}'.")
    return _to_plan_status(record)


@router.get(
    "/plan/{plan_id}/final",
    response_model=FinalPlanResponse,
    summary="Retrieve the finalized plan (only after approval)",
)
def get_final_plan(
    plan_id: str,
    manager: WorkflowManager = Depends(get_manager),
) -> FinalPlanResponse:
    record = manager.status(plan_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown plan '{plan_id}'.")
    if record.phase != "finalized" or record.final_plan is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Plan '{plan_id}' is not finalized yet "
                f"(phase: {record.phase}). Final output is only available after "
                "review approval."
            ),
        )
    try:
        final = ItineraryPlan.model_validate(record.final_plan)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Final plan could not be parsed: {exc}"
        ) from exc
    return FinalPlanResponse(plan_id=plan_id, final_plan=final)


__all__ = ["router"]