"""The Destination Research Agent.

Uses two tools:
1. ``web_search`` (mandatory) — live web intelligence via Serper or Exa.
2. ``weather_forecast`` — trip-dates weather via free Open-Meteo.

Produces a schema-valid :class:`ResearchReport` dict.
"""

from __future__ import annotations

import json

from app.agents.agent import ReActAgent
from app.agents.tools.web_search import web_search
from app.agents.tools.weather import weather_forecast
from app.config import Settings
from app.core.llm import extract_json, get_llm
from app.core.prompts import RESEARCH_SYSTEM_PROMPT
from app.planning.builders import build_research_report


class ResearchAgent:
    def __init__(self, settings: Settings) -> None:
        model = get_llm(settings, behavior="research")
        self._runner = ReActAgent(
            name="research_agent",
            model=model,
            tools=[web_search, weather_forecast],
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            max_iterations=settings.max_agent_iterations,
        )

    def run(
        self,
        request: dict,
        feedback: dict | None = None,
    ) -> tuple[dict, dict[str, str]]:
        """Return ``(report, tool_outputs)``."""
        payload: dict = {"request": request}
        if feedback:
            payload["feedback"] = feedback
        result = self._runner.run(json.dumps(payload, default=str))

        report = extract_json(result.content)
        if report is None:
            web = result.tool_outputs.get("web_search", "{}")
            weather = result.tool_outputs.get("weather_forecast", "{}")
            report = build_research_report(web, weather, request.get("destination", ""))
        return report, result.tool_outputs