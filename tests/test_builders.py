"""Unit tests for the deterministic document builders."""

from __future__ import annotations

import json

from app.planning.builders import build_plan, build_research_report

REQ = {
    "destination": "Paris",
    "start_date": "2026-06-10",
    "end_date": "2026-06-13",
    "travelers": 2,
    "interests": ["art", "food"],
    "budget": {"min_amount": 1500, "max_amount": 3200, "currency": "USD"},
}


def test_build_research_report_parses_tool_outputs():
    web = json.dumps(
        {
            "destination": "Paris",
            "overview": "Paris is great.",
            "attractions": [
                {"name": "Louvre", "area": "Rive Droite",
                 "description": "Museum", "tip": "Book ahead"}
            ],
            "safety_notes": ["Beware pickpockets."],
            "local_tips": ["Use the Metro."],
            "seasonal_notes": ["Summer is warm."],
            "sources": ["mock"],
        }
    )
    weather = json.dumps(
        {
            "forecast": [
                {"date": "2026-06-10", "temp_min": 15, "temp_max": 24,
                 "precipitation_chance": 20, "condition": "Partly cloudy"}
            ]
        }
    )
    report = build_research_report(web, weather, "Paris")
    assert report["destination"] == "Paris"
    assert report["attractions"][0]["title"] == "Louvre"
    assert report["weather"][0]["date"] == "2026-06-10"
    assert "Beware pickpockets." in report["safety_notes"]


def test_build_plan_produces_valid_schema():
    research = build_research_report(
        json.dumps(
            {
                "destination": "Paris",
                "overview": "City of light.",
                "attractions": [
                    {
                        "name": "Eiffel Tower",
                        "description": "The tower.",
                        "tip": "Go at sunset.",
                    },
                    {
                        "name": "Louvre",
                        "description": "The museum.",
                        "tip": "Pre-book.",
                    },
                    {"name": "Orsay"},
                ],
                "weather_notes": ["Mild weather."],
                "local_tips": ["Metro is best."],
            }
        ),
        json.dumps({"forecast": []}),
        "Paris",
    )
    places = json.dumps(
        {"attractions": [
            {"name": "Eiffel Tower", "area": "7e",
             "description": "Icon.", "tip": "Go sunset."},
            {"name": "Seine Cruise", "description": "Boat."},
        ]}
    )
    guides = json.dumps(
        {
            "restaurants": [
                {"name": "Bouillon", "cuisine": "French",
                 "area": "Opéra", "budget_tier": "value"}
            ],
            "packing_list": ["Shoes"],
            "local_tips": ["Book dinners."],
        }
    )

    plan = build_plan(REQ, research, places, guides)
    assert plan["destination"] == "Paris"
    assert len(plan["days"]) == 4  # 10..13 June inclusive
    assert plan["travelers"] == 2
    assert 1500 <= plan["budget_allocation"]["total"] <= 3200
    assert plan["restaurants"][0]["name"] == "Bouillon"
    assert "Shoes" in plan["packing_list"]
    for day in plan["days"]:
        assert day["day"] >= 1
        assert len(day["activities"]) >= 1


def test_build_plan_applies_modifications():
    research = build_research_report(
        json.dumps({"destination": "Paris"}), json.dumps({"forecast": []}), "Paris"
    )
    plan = build_plan(
        REQ,
        research,
        json.dumps({"attractions": []}),
        json.dumps({"restaurants": [], "packing_list": [], "local_tips": []}),
        modifications={
            "hotel": "Custom Hotel X",
            "budget": {"max": 5000},
            "days": {"1": {"title": "River Day"}},
        },
    )
    assert plan["hotels"][0]["name"] == "Custom Hotel X"
    assert plan["budget_max"] == 5000
    assert plan["days"][0]["title"] == "River Day"