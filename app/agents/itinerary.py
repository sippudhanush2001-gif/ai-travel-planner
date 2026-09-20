"""The Itinerary Planner Agent.

Uses two tools:
1. ``places_database`` — curated attractions matched to interests/days.
2. ``local_guides`` — restaurants, packing list, local tips.

Produces a schema-valid :class:`ItineraryPlan` dict. Can incorporate human
feedback (revise) and structured modifications (modify) passed by the
orchestrator.
"""

from __future__ import annotations

import json

from app.agents.agent import ReActAgent
from app.agents.tools.local_guides import local_guides
from app.agents.tools.places_db import places_database
from app.config import Settings
from app.core.llm import extract_json, get_llm
from app.core.prompts import PLANNER_SYSTEM_PROMPT
from app.planning.builders import build_plan


class ItineraryAgent:
    def __init__(self, settings: Settings) -> None:
        model = get_llm(settings, behavior="itinerary")
        self._runner = ReActAgent(
            name="itinerary_agent",
            model=model,
            tools=[places_database, local_guides],
            system_prompt=PLANNER_SYSTEM_PROMPT,
            max_iterations=settings.max_agent_iterations,
        )

    def run(
        self,
        request: dict,
        research: dict | None,
        feedback: dict | None = None,
        modifications: dict | None = None,
    ) -> tuple[dict, dict[str, str]]:
        """Return ``(plan, tool_outputs)``."""
        payload: dict = {"request": request, "research": research or {}}
        if feedback:
            payload["feedback"] = feedback
        if modifications:
            payload["modifications"] = modifications

        result = self._runner.run(json.dumps(payload, default=str))

        plan = extract_json(result.content)
        if plan is None:
            plan = build_plan(
                request=request,
                research=research,
                places_output=result.tool_outputs.get("places_database", "{}"),
                guides_output=result.tool_outputs.get("local_guides", "{}"),
                feedback=feedback,
                modifications=modifications,
            )
        else:
            # Even when the model returns JSON, guarantee schema compliance.
            from app.models.schemas import ItineraryPlan

            try:
                plan = ItineraryPlan.model_validate(plan).model_dump(mode="json")
            except Exception:  # noqa: BLE001 - fall back to the builder
                plan = build_plan(
                    request=request,
                    research=research,
                    places_output=result.tool_outputs.get("places_database", "{}"),
                    guides_output=result.tool_outputs.get("local_guides", "{}"),
                    feedback=feedback,
                    modifications=modifications,
                )
        return plan, result.tool_outputs