"""LLM provider factory.

Returns any ``BaseChatModel`` — real (OpenAI / Anthropic) or the built-in
deterministic ``MockChatModel``. Using a common abstraction means the ReAct
agent loop and every downstream component are provider-agnostic.

The ``MockChatModel`` is a scripted, deterministic "LLM" that exercises the
tools in a fixed order and then composes a valid answer from the tool outputs
(via the deterministic builders in ``app.planning.builders``). It makes the
whole workflow runnable without any API keys, which doubles as a hermetic test
double and as a JSON-repair fallback path in production.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import date
from typing import Any, Literal

from pydantic import Field

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.config import Settings
from app.planning.builders import build_plan, build_research_report

RESEARCH_JSON_SCHEMA_HINT = (
    'Reply with ONLY a JSON object matching: '
    '{"destination": str, "overview": str, "attractions": [{"name", "area", '
    '"category", "description", "why_visit", "tip"}], "weather_notes": [str], '
    '"safety_notes": [str], "local_tips": [str], "seasonal_notes": [str], "sources": [str]}'
)

PLAN_JSON_SCHEMA_HINT = (
    "Reply with ONLY a JSON object. It must be a complete travel itinerary with keys: "
    "destination, start_date, end_date, travelers, interests, budget_min, budget_max, "
    "currency, overview, days (array of {day, date, title, activities: [{title, time, "
    "area, description, tip}], meals, transport_note}), hotels (array of {name, area, "
    "price_per_night, rating, notes}), restaurants (array of {name, cuisine, area, "
    "budget_tier, notes}), budget_allocation (object of category->amount), packing_list "
    "(array of str), local_tips (array of str). Return only the JSON, no prose."
)


class MockChatModel(BaseChatModel):
    """A deterministic stand-in LLM used when no API keys are configured.

    ``behavior`` selects the scripted tool-use sequence:
    * ``"research"``    ->  web_search, then weather_forecast, then a report.
    * ``"itinerary"``   ->  places_database, then local_guides, then a plan.

    The final answers are produced by the deterministic builders so the
    returned JSON is always schema-valid.
    """

    _llm_type = "mock-chat"

    @property
    def _llm_type(self) -> str:  # satisfies BaseChatModel's abstract property
        return "mock-chat"

    behavior: Literal["research", "itinerary"] = "research"
    tool_names: list[str] = Field(default_factory=list, exclude=True)

    def bind_tools(self, tools: list, **kwargs: Any) -> BaseChatModel:
        """Record bound tool names so `_generate` knows what is available."""
        names = [getattr(t, "name", str(t)) for t in tools]
        bound = self.model_copy(update={"tool_names": names})
        return bound  # type: ignore[return-value]

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        msg = self._next_message(messages)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def _next_message(self, messages: list[BaseMessage]) -> AIMessage:
        """Script the next action based on how many turns have happened."""
        ai_turns = [m for m in messages if isinstance(m, AIMessage)]
        step = len(ai_turns)

        payload = _last_human_dict(messages)
        request = (payload.get("request") or {}) if isinstance(payload, dict) else {}

        if self.behavior == "research":
            return self._research_turn(messages, step, request)
        return self._itinerary_turn(messages, step, request, payload)

    # --- research ------------------------------------------------------ #
    def _research_turn(
        self, messages: list[BaseMessage], step: int, request: dict
    ) -> AIMessage:
        destination = request.get("destination") or "Paris"
        if step == 0 and "web_search" in self.tool_names:
            return _tool_call(
                "web_search",
                {"query": self._search_query(request), "location": destination},
            )
        if step == 1 and "weather_forecast" in self.tool_names:
            return _tool_call(
                "weather_forecast",
                {
                    "location": destination,
                    "start_date": request.get("start_date", ""),
                    "end_date": request.get("end_date", ""),
                },
            )
        # Compose the final report from whatever the tools returned.
        results = _tool_results(messages)
        web = results.get("web_search", "{}")
        weather = results.get("weather_forecast", "{}")
        if not web.strip() or web == "{}":
            web = _fallback_web_json(destination)
        report = build_research_report(web, weather, destination)
        return AIMessage(content=json.dumps(report, ensure_ascii=False))

    @staticmethod
    def _search_query(request: dict) -> str:
        dest = request.get("destination", "")
        interests = ", ".join(request.get("interests", []) or [])
        parts = [
            f"{dest} travel guide",
            "top attractions",
            "safety",
            "best time to visit",
            "local tips",
        ]
        if interests:
            parts.insert(1, interests)
        return " ".join(p for p in parts if p)

    # --- itinerary ------------------------------------------------------ #
    def _itinerary_turn(
        self,
        messages: list[BaseMessage],
        step: int,
        request: dict,
        payload: dict,
    ) -> AIMessage:
        destination = request.get("destination") or "Paris"
        interests = request.get("interests") or []
        days = _days_in(request)

        if step == 0 and "places_database" in self.tool_names:
            return _tool_call(
                "places_database",
                {"destination": destination, "interests": interests, "days": days},
            )
        if step == 1 and "local_guides" in self.tool_names:
            season = _season_from(request)
            return _tool_call(
                "local_guides",
                {
                    "destination": destination,
                    "travelers": request.get("travelers", 1),
                    "season": season,
                },
            )

        results = _tool_results(messages)
        places = results.get("places_database", "{}")
        guides = results.get("local_guides", "{}")
        if places == "{}":
            places = _fallback_places_json(destination)
        if guides == "{}":
            guides = _fallback_guides_json(destination)
        plan = build_plan(
            request=request,
            research=payload.get("research"),
            places_output=places,
            guides_output=guides,
            feedback=payload.get("feedback"),
            modifications=payload.get("modifications"),
        )
        return AIMessage(content=json.dumps(plan, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": uuid.uuid4().hex[:12]}],
    )


def _tool_results(messages: list[BaseMessage]) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in messages:
        if isinstance(m, ToolMessage) and m.name:
            out[m.name] = m.content
    return out


def _last_human_dict(messages: list[BaseMessage]) -> dict:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            text = m.content
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except (ValueError, TypeError):
                    return {"request": {}}
            return {"request": {}}
    return {"request": {}}


def _days_in(request: dict) -> int:
    try:
        s = date.fromisoformat(request.get("start_date", ""))
        e = date.fromisoformat(request.get("end_date", ""))
        return max((e - s).days + 1, 1)
    except (ValueError, TypeError):
        return 3


def _season_from(request: dict) -> str:
    try:
        month = date.fromisoformat(request.get("start_date", "")).month
    except (ValueError, TypeError):
        return "spring"
    return {
        12: "winter", 1: "winter", 2: "winter",
        3: "spring", 4: "spring", 5: "spring",
        6: "summer", 7: "summer", 8: "summer",
        9: "fall", 10: "fall", 11: "fall",
    }[month]


def _fallback_web_json(destination: str) -> str:
    return json.dumps(
        {
            "destination": destination,
            "overview": f"{destination} is a popular travel destination.",
            "attractions": [],
            "safety_notes": ["Exercise standard tourist caution."],
            "local_tips": ["Check opening hours in advance."],
            "seasonal_notes": ["Peak season can be busy; book ahead."],
            "sources": [],
        }
    )


def _fallback_places_json(destination: str) -> str:
    from app.agents.tools.places_db import PLACES_DB

    entry = PLACES_DB.get(destination.title(), {})
    return json.dumps({"attractions": entry.get("attractions", [])})


def _fallback_guides_json(destination: str) -> str:
    from app.agents.tools.local_guides import GUIDES_DB

    entry = GUIDES_DB.get(destination.title(), {})
    return json.dumps(entry)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def get_llm(
    settings: Settings, behavior: Literal["research", "itinerary"] = "research"
) -> BaseChatModel:
    """Build the configured chat model for the given agent role.

    ``behavior`` only matters for the deterministic mock model in which it
    selects the scripted tool-use sequence. Real providers ignore it.
    """
    provider = settings.llm_provider
    if provider == "mock":
        return MockChatModel(behavior=behavior).with_config({"tags": ["mock"]})
    if provider == "openai":
        _require(settings.openai_api_key, "OPENAI_API_KEY", "openai provider")
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "langchain-openai is not installed. Run: pip install langchain-openai"
            ) from exc
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=settings.llm_temperature,
        )
    if provider == "anthropic":
        _require(settings.anthropic_api_key, "ANTHROPIC_API_KEY", "anthropic provider")
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "langchain-anthropic is not installed. Run: pip install langchain-anthropic"
            ) from exc
        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            temperature=settings.llm_temperature,
        )
    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. Expected one of: mock, openai, anthropic."
    )


def _require(value: str | None, env_name: str, for_what: str) -> None:
    if not value:
        raise RuntimeError(
            f"{env_name} is required to use the {for_what}. Set it in your .env file "
            "or switch LLM_PROVIDER=mock."
        )


def extract_json(text: str) -> dict | None:
    """Best-effort parse of a JSON object from an LLM response."""
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except ValueError:
            return None
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except ValueError:
            return None
    return None