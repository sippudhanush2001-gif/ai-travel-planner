"""The workflow manager: the single interaction point between the FastAPI layer
and the LangGraph orchestrator.

Responsibilities:
* Create a plan (thread id = plan_id) and execute the graph in a background
  thread. The graph pauses on the HITL ``interrupt`` and ``invoke`` returns the
  current state.
* Read plan status from the SQLite checkpointer (works across restarts because
  the graph state is the source of truth).
* Resume the graph with ``Command(resume=...)`` when the user reviews.
* Serialize access to the (not-thread-safe) SQLite saver with a per-plan lock.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command

from app.config import Settings
from app.models.schemas import ReviewFeedback, TravelRequest, now_iso
from app.orchestrator.graph import build_workflow_graph
from app.orchestrator.persistence import build_checkpointer
from app.orchestrator.state import phase_message


class ReviewNotAllowed(Exception):
    """Raised when review feedback is submitted for a plan that is not paused
    at the human-in-the-loop gate."""


class PlanNotFound(Exception):
    """Raised when the requested plan id does not exist."""


@dataclass
class PlanRecord:
    plan_id: str
    phase: str = "processing"
    message: str | None = None
    research: dict | None = None
    draft_plan: dict | None = None
    final_plan: dict | None = None
    feedback: dict | None = None
    revisions: int = 0
    can_review: bool = False
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    _running: bool = field(default=False)


class WorkflowManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.checkpointer = build_checkpointer(settings)
        self.graph = build_workflow_graph(settings, self.checkpointer)

        self._records: dict[str, PlanRecord] = {}
        self._records_lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def submit(self, request: TravelRequest) -> PlanRecord:
        plan_id = uuid.uuid4().hex
        now = now_iso()
        initial: dict[str, Any] = {
            "plan_id": plan_id,
            "request": request.model_dump(mode="json"),
            "phase": "processing",
            "research": None,
            "research_tools": None,
            "draft_plan": None,
            "final_plan": None,
            "feedback": None,
            "revisions": 0,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        thr = threading.Thread(
            target=self._execute, args=(plan_id, initial), daemon=True,
            name=f"plan-{plan_id[:8]}"
        )
        thr.start()
        timeout = self.settings.request_timeout_seconds
        thr.join(timeout=timeout)

        record = self.status(plan_id)
        if record is None:  # pragma: no cover - defensive
            record = PlanRecord(
                plan_id=plan_id,
                phase="processing",
                message="Workflow is still starting.",
                created_at=now,
                updated_at=now,
            )
            self._records[plan_id] = record
        if record._running:
            record.message = (
                "Workflow is still running (research & planning may take a while)."
            )
        return record

    def review(self, plan_id: str, feedback: ReviewFeedback) -> PlanRecord:
        record = self.status(plan_id)
        if record is None:
            raise PlanNotFound(plan_id)
        if not record.can_review:
            raise ReviewNotAllowed(
                f"Plan {plan_id} is not awaiting review (phase: {record.phase})."
            )
        thr = threading.Thread(
            target=self._resume, args=(plan_id, feedback.model_dump()), daemon=True,
            name=f"review-{plan_id[:8]}"
        )
        thr.start()
        thr.join(timeout=self.settings.request_timeout_seconds)
        return self.status(plan_id)  # type: ignore[return-value]

    def status(self, plan_id: str) -> PlanRecord | None:
        with self._records_lock:
            record = self._records.get(plan_id)
        if record is None:
            record = self._load_from_checkpoint(plan_id)
            if record is None:
                return None
            with self._records_lock:
                self._records.setdefault(plan_id, record)
        return record

    def has_plan(self, plan_id: str) -> bool:
        return self.status(plan_id) is not None

    # ------------------------------------------------------------------ #
    # Internal execution
    # ------------------------------------------------------------------ #
    def _execute(self, plan_id: str, initial: dict) -> None:
        config = self._config(plan_id)
        with self._lock(plan_id):
            record = self._ensure_record(plan_id)
            record._running = True
            try:
                self.graph.invoke(initial, config)
            except Exception as exc:  # noqa: BLE001 - record the failure in state
                self._record_error(plan_id, exc)
            finally:
                record._running = False
            self._refresh_record(plan_id)

    def _resume(self, plan_id: str, feedback: dict) -> None:
        config = self._config(plan_id)
        with self._lock(plan_id):
            record = self._ensure_record(plan_id)
            record._running = True
            try:
                self.graph.invoke(Command(resume=feedback), config)
            except Exception as exc:  # noqa: BLE001
                self._record_error(plan_id, exc)
            finally:
                record._running = False
            self._refresh_record(plan_id)

    def _record_error(self, plan_id: str, exc: Exception) -> None:
        try:
            self.graph.update_state(
                self._config(plan_id),
                {"phase": "error", "error": f"{type(exc).__name__}: {exc}",
                 "updated_at": now_iso()},
            )
        except Exception:  # noqa: BLE001 - never mask the original error
            record = self._ensure_record(plan_id)
            record.phase = "error"
            record.error = f"{type(exc).__name__}: {exc}"
            record.updated_at = now_iso()

    # ------------------------------------------------------------------ #
    # Record bookkeeping
    # ------------------------------------------------------------------ #
    def _config(self, plan_id: str) -> dict:
        return {"configurable": {"thread_id": plan_id}}

    def _ensure_record(self, plan_id: str) -> PlanRecord:
        with self._records_lock:
            record = self._records.get(plan_id)
            if record is None:
                record = PlanRecord(plan_id=plan_id)
                self._records[plan_id] = record
            return record

    def _lock(self, plan_id: str) -> threading.Lock:
        with self._records_lock:
            lock = self._locks.get(plan_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[plan_id] = lock
            return lock

    def _refresh_record(self, plan_id: str) -> None:
        snapshot = self.graph.get_state(self._config(plan_id))
        values = snapshot.values or {}
        record = self._ensure_record(plan_id)

        pending = bool(
            snapshot.tasks
            and any(getattr(t, "interrupts", None) for t in snapshot.tasks)
        )

        record.plan_id = values.get("plan_id", plan_id)
        record.phase = values.get("phase", record.phase)
        record.research = values.get("research")
        record.draft_plan = values.get("draft_plan")
        record.final_plan = values.get("final_plan")
        record.feedback = values.get("feedback")
        record.revisions = values.get("revisions", 0)
        record.error = values.get("error")
        record.created_at = values.get("created_at")
        record.updated_at = values.get("updated_at")
        record.can_review = pending or record.phase == "review"
        record.message = (
            record.error
            or phase_message(record.phase)
            or f"Phase: {record.phase}"
        )

    def _load_from_checkpoint(self, plan_id: str) -> PlanRecord | None:
        """Rebuild a record purely from persisted graph state (server restart)."""
        try:
            snapshot = self.graph.get_state(self._config(plan_id))
        except Exception:  # noqa: BLE001 - treat as missing
            return None
        values = snapshot.values
        if not values or values.get("plan_id") != plan_id:
            return None
        return self._plan_record_from(snapshot, plan_id)

    def _plan_record_from(self, snapshot, plan_id: str) -> PlanRecord:
        values = snapshot.values or {}
        pending = bool(
            snapshot.tasks
            and any(getattr(t, "interrupts", None) for t in snapshot.tasks)
        )
        error = values.get("error")
        phase = values.get("phase", "processing")
        return PlanRecord(
            plan_id=plan_id,
            phase=phase,
            message=error or phase_message(phase) or f"Phase: {phase}",
            research=values.get("research"),
            draft_plan=values.get("draft_plan"),
            final_plan=values.get("final_plan"),
            feedback=values.get("feedback"),
            revisions=values.get("revisions", 0),
            can_review=pending or phase == "review",
            error=error,
            created_at=values.get("created_at"),
            updated_at=values.get("updated_at"),
        )


__all__ = ["WorkflowManager", "PlanRecord", "ReviewNotAllowed", "PlanNotFound"]