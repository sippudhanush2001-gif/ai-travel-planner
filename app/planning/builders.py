"""Deterministic document builders.

These functions convert raw tool output into schema-valid documents. They are
used in two places:

1. As the **answer generator** for the offline ``MockChatModel``.
2. As a **repair fallback** when a real LLM returns non-parseable JSON, so a
   plan is always produced even if the model misbehaves.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from app.models.schemas import ItineraryPlan, ResearchReport

# --------------------------------------------------------------------------- #
# JSON helpers
# --------------------------------------------------------------------------- #
def _load_json(text) -> dict:
    if isinstance(text, dict):
        return text
    if text is None:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


# --------------------------------------------------------------------------- #
# Research report
# --------------------------------------------------------------------------- #
def build_research_report(
    web_output: str, weather_output: str, fallback_destination: str = "destination"
) -> dict:
    web = _load_json(web_output)
    weather = _load_json(weather_output)

    dest = web.get("destination") or fallback_destination
    attractions = web.get("attractions") or []
    report = {
        "destination": dest,
        "overview": web.get(
            "overview",
            f"{dest} offers a rich mix of culture, food and sightseeing.",
        ),
        "attractions": [
            {
                "title": a.get("name") or a.get("title", "Unnamed"),
                "time": a.get("time"),
                "area": a.get("area"),
                "description": a.get("description") or a.get("why_visit"),
                "tip": a.get("tip") or a.get("why_visit"),
            }
            for a in attractions
        ],
        "weather": weather.get("forecast", []),
        "weather_notes": list(weather.get("notes", [])),
        "safety_notes": list(web.get("safety_notes", [])),
        "local_tips": list(web.get("local_tips", [])),
        "seasonal_notes": list(web.get("seasonal_notes", [])),
        "sources": list(web.get("sources", [])),
    }
    if web.get("fallback_reason"):
        report["sources"].append(f"web-search-fallback: {web['fallback_reason']}")
    if weather.get("fallback_reason"):
        report["sources"].append(f"weather-fallback: {weather['fallback_reason']}")

    # Validate / repair against the schema.
    return ResearchReport.model_validate(report).model_dump()


# --------------------------------------------------------------------------- #
# Itinerary plan
# --------------------------------------------------------------------------- #
def _date_range(start: str, end: str) -> list[str]:
    try:
        s = date.fromisoformat(start[:10])
        e = date.fromisoformat(end[:10])
    except ValueError:
        return [start, end] if start else []
    days = []
    cur = s
    while cur <= e:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def _clean_attractions(research: dict, places: dict) -> list[dict]:
    """Merge research + curated places, deduplicated by name, prefer curated."""
    merged: dict[str, dict] = {}
    for a in places.get("attractions", []):
        if isinstance(a, dict) and a.get("name"):
            merged[a["name"]] = _pad_activity(a)
    for a in (research or {}).get("attractions", []):
        if isinstance(a, dict) and a.get("name") and a["name"] not in merged:
            merged[a["name"]] = _pad_activity(a)
    return list(merged.values())


def _pad_activity(a: dict) -> dict:
    return {
        "time": a.get("time"),
        "title": a.get("title") or a.get("name", "Sightseeing"),
        "area": a.get("area"),
        "description": a.get("description"),
        "tip": a.get("tip") or a.get("why_visit"),
    }


_MEDIALS = ["morning", "late morning", "early afternoon", "afternoon"]


def _group_by_days(activities: list[dict], n_days: int, interests: list[str]) -> list[list[dict]]:
    """Spread activities across days evenly (round-robin, max 3/day).

    Even distribution avoids empty days when there are more travel days than
    curated attractions; empty days are filled by the plan builder.
    """
    if not activities:
        return [[] for _ in range(n_days)]
    buckets: list[list[dict]] = [[] for _ in range(n_days)]
    cursor = 0
    for item in activities:
        buckets[cursor % n_days].append(item)
        cursor += 1
    # Respect a sensible per-day cap of 3, keeping ordering by interest rank.
    for bucket in buckets:
        if len(bucket) > 3:
            spill = bucket[3:]
            del bucket[3:]
            for extra in spill:
                # push to the first bucket that has room
                for candidate in buckets:
                    if len(candidate) < 3:
                        candidate.append(extra)
                        break
    return buckets


def _budget_split(budget_min: float, budget_max: float, nights: int) -> dict:
    mid = (budget_min + budget_max) / 2
    housing = round(0.42 * mid, 2)
    food = round(0.24 * mid, 2)
    transport = round(0.18 * mid, 2)
    activities = round(0.12 * mid, 2)
    misc = round(mid - (housing + food + transport + activities), 2)
    return {
        "housing": housing,
        "food": food,
        "transport": transport,
        "activities": activities,
        "misc": misc,
        "total": round(housing + food + transport + activities + misc, 2),
    }


def build_plan(
    request: dict,
    research: dict | None,
    places_output: str,
    guides_output: str,
    feedback: dict | None = None,
    modifications: dict | None = None,
) -> dict:
    """Build a complete itinerary document from the available inputs."""
    places = _load_json(places_output)
    guides = _load_json(guides_output)

    budget_min = float(request.get("budget", {}).get("min_amount", 1000))
    budget_max = float(request.get("budget", {}).get("max_amount", 3000))
    currency = request.get("budget", {}).get("currency", "USD")
    start = request.get("start_date") or ""
    end = request.get("end_date") or ""
    travelers = int(request.get("travelers", 1))
    interests = list(request.get("interests", []) or [])

    dates = _date_range(start, end)
    n_days = len(dates) or 1
    nights = n_days - 1

    attractions = _clean_attractions(research or {}, places)
    by_day = _group_by_days(attractions, n_days, interests)

    days = []
    day_themes = ["Arrival & Orientation", "Sightseeing", "Hidden Gems"]
    for i in range(n_days):
        acts = []
        for k, act in enumerate(by_day[i]):
            acts.append(
                {
                    "time": _MEDIALS[k % len(_MEDIALS)],
                    "title": act.get("title"),
                    "area": act.get("area"),
                    "description": act.get("description"),
                    "tip": act.get("tip"),
                }
            )
        if not acts:
            acts = [
                {
                    "time": "morning",
                    "title": "Free time & exploration",
                    "area": "City centre",
                    "description": "Unstructured time to explore at your own pace.",
                    "tip": "Walk the main streets and people-watch.",
                }
            ]
        days.append(
            {
                "day": i + 1,
                "date": dates[i] if i < len(dates) else None,
                "title": day_themes[i % len(day_themes)],
                "activities": acts,
                "meals": [
                    "Breakfast at the hotel",
                    "Lunch near the morning sightseeing area",
                    "Dinner at a recommended local restaurant",
                ],
                "transport_note": "Public transit / walkathon day",
            }
        )

    # --- hotels -----------------------------------------------------------
    split = _budget_split(budget_min, budget_max, nights or 1)
    per_night = round(split["housing"] / (nights or 1), 2)
    area = attractions[0].get("area", "City centre") if attractions else "City centre"
    hotels = [
        {
            "name": f"Comfort Central {area}",
            "area": area,
            "price_per_night": round(per_night * 0.9, 2),
            "rating": 4.2,
            "notes": "Value pick near major sights.",
        },
        {
            "name": "Grand Plaza Hotel",
            "area": area,
            "price_per_night": round(per_night * 1.25, 2),
            "rating": 4.6,
            "notes": "Upscale choice with better amenities.",
        },
    ]

    # --- restaurants ------------------------------------------------------
    restaurants = guides.get("restaurants", [])
    restaurants = [
        {
            "name": r.get("name", "Local Bistro"),
            "cuisine": r.get("cuisine", "Local"),
            "area": r.get("area"),
            "budget_tier": r.get("budget_tier"),
            "notes": r.get("notes"),
        }
        for r in restaurants
    ][:4]

    # --- packing & tips ----------------------------------------------------
    packing = list(guides.get("packing_list", []))
    if not packing:
        packing = ["Comfortable shoes", "Travel documents", "Water bottle"]
    tips = list((research or {}).get("local_tips", []))
    tips += list(guides.get("local_tips", []))
    tips = _dedupe(tips)

    overview = str((research or {}).get("overview", "")) or (
        f"{request.get('destination', 'This destination')} — a balanced itinerary "
        "matching your interests."
    )
    weather_notes = list((research or {}).get("weather_notes", []))
    if weather_notes:
        overview += " Weather: " + " ".join(weather_notes[:2])
    if feedback:
        overview += ' Feedback applied: "%s"' % (
            str(feedback.get("comments", "")).strip() or "revised per your comments."
        )

    plan = {
        "destination": request.get("destination", ""),
        "start_date": start,
        "end_date": end,
        "travelers": travelers,
        "interests": interests,
        "budget_min": budget_min,
        "budget_max": budget_max,
        "currency": currency,
        "overview": overview,
        "days": days,
        "hotels": hotels,
        "restaurants": restaurants,
        "budget_allocation": split,
        "packing_list": packing,
        "local_tips": tips,
    }

    plan = _apply_modifications(plan, modifications)

    return ItineraryPlan.model_validate(plan).model_dump(mode="json")


def _apply_modifications(plan: dict, modifications: dict | None) -> dict:
    if not modifications:
        return plan
    mods = _load_json(json.dumps(modifications)) if modifications else {}

    hotel = mods.get("hotel")
    if isinstance(hotel, str):
        plan["hotels"] = plan.get("hotels", []) or [
            {"name": hotel, "notes": "Chosen by user.", "rating": 4.0}
        ]
        plan["hotels"][0]["name"] = hotel

    budget = mods.get("budget")
    if isinstance(budget, dict):
        if isinstance(budget.get("min"), (int, float)):
            plan["budget_min"] = float(budget["min"])
        if isinstance(budget.get("max"), (int, float)):
            plan["budget_max"] = float(budget["max"])

    days_override = mods.get("days")
    if isinstance(days_override, dict):
        for day_key, value in days_override.items():
            target = plan.get("days", [])
            try:
                idx = int(day_key) - 1
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(target):
                if isinstance(value, dict) and value.get("activities") is not None:
                    target[idx]["activities"] = value["activities"]
                if isinstance(value, dict) and value.get("title"):
                    target[idx]["title"] = value["title"]

    return plan


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


__all__ = ["build_research_report", "build_plan"]