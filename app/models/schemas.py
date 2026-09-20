"""Pydantic models for API input/output and the internal plan document.

These models are intentionally split into two groups:

* **API models** — validated against exactly what the client sends/receives.
* **Plan document** — the persisted itinerary object shared between the
  orchestration state, the deterministic builders and the API response.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

_STYLE = Literal["relaxed", "adventure", "cultural", "family", "business", "romantic"]


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
class BudgetRange(BaseModel):
    min_amount: float = Field(gt=0, description="Minimum total budget in `currency`.")
    max_amount: float = Field(gt=0, description="Maximum total budget in `currency`.")
    currency: str = Field(default="USD", min_length=3, max_length=3)

    @model_validator(mode="after")
    def _ordering(self) -> "BudgetRange":
        if self.max_amount < self.min_amount:
            raise ValueError("budget.max_amount must be >= budget.min_amount")
        return self


class TravelRequest(BaseModel):
    """What a user submits to start planning a trip."""

    destination: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date
    budget: BudgetRange
    interests: list[str] = Field(min_length=1, description="e.g. ['art', 'food', 'hiking']")
    travelers: int = Field(ge=1, le=20)
    travel_style: _STYLE = "cultural"
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _dates_ordered(self) -> "TravelRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self

    @property
    def nights(self) -> int:
        return max((self.end_date - self.start_date).days, 0)

    @property
    def days(self) -> int:
        return self.nights + 1


class ReviewFeedback(BaseModel):
    """Human-in-the-loop decision made by the user on a draft plan."""

    action: Literal["approve", "revise", "modify"]
    comments: str = Field(default="", max_length=2000)
    # Used when action == "revise": which agent(s) should incorporate the comments.
    target: Literal["research", "plan"] = "plan"
    # Used when action == "modify": structured overrides applied to the draft.
    modifications: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Plan document
# --------------------------------------------------------------------------- #
class Activity(BaseModel):
    title: str
    time: str | None = None
    area: str | None = None
    description: str | None = None
    tip: str | None = None


class DayPlan(BaseModel):
    day: int
    date: str | None = None
    title: str | None = None
    activities: list[Activity] = Field(default_factory=list)
    meals: list[str] = Field(default_factory=list)
    transport_note: str | None = None


class HotelOption(BaseModel):
    name: str
    area: str
    price_per_night: float = 0.0
    rating: float = 0.0
    notes: str | None = None


class RestaurantPick(BaseModel):
    name: str
    cuisine: str
    area: str | None = None
    budget_tier: str | None = None
    notes: str | None = None


class WeatherDay(BaseModel):
    date: str
    temp_min: float = 0.0
    temp_max: float = 0.0
    precipitation_chance: float = 0.0
    condition: str = "Unknown"


class ItineraryPlan(BaseModel):
    """The real itinerary document returned for the destination."""

    destination: str
    start_date: str
    end_date: str
    travelers: int = 1
    interests: list[str] = Field(default_factory=list)
    budget_min: float
    budget_max: float
    currency: str = "USD"
    overview: str = ""
    days: list[DayPlan] = Field(default_factory=list)
    hotels: list[HotelOption] = Field(default_factory=list)
    restaurants: list[RestaurantPick] = Field(default_factory=list)
    budget_allocation: dict[str, float] = Field(default_factory=dict)
    packing_list: list[str] = Field(default_factory=list)
    local_tips: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """Structured destination intelligence produced by the Research Agent."""

    destination: str
    overview: str = ""
    attractions: list[Activity] = Field(default_factory=list)
    weather: list[WeatherDay] = Field(default_factory=list)
    weather_notes: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    local_tips: list[str] = Field(default_factory=list)
    seasonal_notes: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# API responses
# --------------------------------------------------------------------------- #
class PlanCreated(BaseModel):
    plan_id: str
    phase: str
    message: str


class PlanStatus(BaseModel):
    plan_id: str
    phase: str = Field(
        description="processing | reviewing | revising | modified | finalized | error"
    )
    message: str | None = None
    draft_plan: ItineraryPlan | None = None
    research: ResearchReport | None = None
    revisions: int = 0
    can_review: bool = False
    feedback: dict[str, Any] | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class FinalPlanResponse(BaseModel):
    plan_id: str
    final_plan: ItineraryPlan


class ErrorResponse(BaseModel):
    detail: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso(date_val: date) -> str:
    return date_val.isoformat()


def time_to_str(t: time | None) -> str | None:
    return t.isoformat() if t else None