"""Local guides tool (Itinerary Agent's second tool).

Generates restaurant picks, a season-aware packing list and practical local
tips for the destination. Curated per-city restaurant data with sensible
fallbacks for unknown cities.
"""

from __future__ import annotations

import json
from datetime import date

from langchain_core.tools import tool

GUIDES_DB: dict[str, dict] = {
    "Paris": {
        "restaurants": [
            {
                "name": "Le Comptoir du Relais",
                "cuisine": "French bistro",
                "area": "Saint-Germain",
                "budget_tier": "mid",
                "notes": "Classic bistro classics; book ahead.",
            },
            {
                "name": "Bouillon Chartier",
                "cuisine": "French",
                "area": "Opéra",
                "budget_tier": "value",
                "notes": "Iconic, affordable, lively.",
            },
            {
                "name": "Breizh Café",
                "cuisine": "Crêperie",
                "area": "Le Marais",
                "budget_tier": "value",
                "notes": "Excellent savory galettes at lunch.",
            },
            {
                "name": "Septime",
                "cuisine": "Contemporary French",
                "area": "11th arrondissement",
                "budget_tier": "premium",
                "notes": "Michelin-listed tasting menu.",
            },
        ],
        "tips": [
            "Reserve dinner 3–7 days ahead via online booking.",
            "Lunch set menus ('formule') are the best value.",
        ],
    },
    "Tokyo": {
        "restaurants": [
            {
                "name": "Ichiran Shibuya",
                "cuisine": "Ramen",
                "area": "Shibuya",
                "budget_tier": "value",
                "notes": "Self-serve tonkotsu ramen booths.",
            },
            {
                "name": "Sushi Dai (Toyosu)",
                "cuisine": "Sushi",
                "area": "Toyosu",
                "budget_tier": "mid",
                "notes": "Famous market sushi; queue very early.",
            },
            {
                "name": "Tsukiji Sushisay",
                "cuisine": "Sushi",
                "area": "Tsukiji",
                "budget_tier": "mid",
                "notes": "Kinmedai and nigiri sets.",
            },
            {
                "name": "Gonpachi Nishi-Azabu",
                "cuisine": "Izakaya",
                "area": "Roppongi",
                "budget_tier": "mid",
                "notes": "The 'Kill Bill' izakaya.",
            },
        ],
        "tips": [
            "Buy a Suica/Pasmo IC card for all transit.",
            "Some izakaya charge a small deposit entrance fee.",
        ],
    },
    "New York": {
        "restaurants": [
            {
                "name": "Katz's Delicatessen",
                "cuisine": "Deli",
                "area": "Lower East Side",
                "budget_tier": "mid",
                "notes": "Historic pastrami sandwiches.",
            },
            {
                "name": "Xi'an Famous Foods",
                "cuisine": "Chinese",
                "area": "East Village",
                "budget_tier": "value",
                "notes": "Hand-pulled noodles.",
            },
            {
                "name": "Joe's Pizza",
                "cuisine": "Pizza",
                "area": "Greenwich Village",
                "budget_tier": "value",
                "notes": "Classic NYC slice.",
            },
            {
                "name": "Dame",
                "cuisine": "Seafood",
                "area": "Greenwich Village",
                "budget_tier": "premium",
                "notes": "British-New England seafood plates.",
            },
        ],
        "tips": [
            "Reservations open 30 days ahead on OpenTable.",
            "Subway MetroCard works for the whole system.",
        ],
    },
    "London": {
        "restaurants": [
            {
                "name": "Dishoom Covent Garden",
                "cuisine": "Indian",
                "area": "Covent Garden",
                "budget_tier": "mid",
                "notes": "Bombay café-style all-day dining.",
            },
            {
                "name": "Borough Market Stalls",
                "cuisine": "Street food",
                "area": "Southwark",
                "budget_tier": "value",
                "notes": "Greatest hits at one stop.",
            },
            {
                "name": "Brick Lane Beigel Bake",
                "cuisine": "Bakery",
                "area": "Shoreditch",
                "budget_tier": "value",
                "notes": "24-hour salt-beef bagels.",
            },
        ],
        "tips": [
            "Tap-in/tap-out with contactless for all transport.",
            "The Underground gets busy at peak (8–9 AM, 5–6 PM).",
        ],
    },
    "Bangkok": {
        "restaurants": [
            {
                "name": "Jay Fai",
                "cuisine": "Thai street",
                "area": "Old Town",
                "budget_tier": "premium",
                "notes": "Michelin-starred crab omelette; arrive early.",
            },
            {
                "name": "Thip Samai",
                "cuisine": "Thai",
                "area": "Old Town",
                "budget_tier": "value",
                "notes": "Legendary pad thai.",
            },
            {
                "name": "Err Urban Rustic Thai",
                "cuisine": "Modern Thai",
                "area": "Sathorn",
                "budget_tier": "mid",
                "notes": "Creative Isaan dishes.",
            },
        ],
        "tips": [
            "Use the BTS/MRT rather than rush-hour taxis.",
            "Stay hydrated; carry hand sanitiser for market stops.",
        ],
    },
}

_GENERIC_RESTAURANTS = [
    {
        "name": "Central Market Table",
        "cuisine": "Local",
        "area": "Old town",
        "budget_tier": "value",
        "notes": "Reliable spot near the main square.",
    },
    {
        "name": "The Old Tavern",
        "cuisine": "Regional",
        "area": "Old town",
        "budget_tier": "mid",
        "notes": "Cozy setting, traditional menu.",
    },
]


def _season_from(start_date: str) -> str:
    try:
        month = date.fromisoformat(start_date).month
    except (ValueError, TypeError):
        return "spring"
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "fall"


@tool
def local_guides(destination: str, travelers: int = 1, season: str = "spring") -> str:
    """Get restaurant picks, a packing list and local tips for the destination.
    Returns a JSON string.

    Args:
        destination: The destination name.
        travelers: Number of travelers (adjusts packing suggestions).
        season: spring | summer | fall | winter (for packing).
    """
    key = destination.strip().title()
    entry = GUIDES_DB.get(key, {})
    restaurants = entry.get("restaurants") or _GENERIC_RESTAURANTS
    city_tips = entry.get("tips") or [
        "Check opening hours ahead; many venues close Mondays.",
    ]

    packing = [
        "Comfortable walking shoes",
        "Power adapter + portable charger",
        "Reusable water bottle",
        "Travel documents (passport, booking confirmations)",
        "Daypack for cameras and purchases",
    ]
    if season == "winter":
        packing += ["Warm layers, scarf, gloves", "Umbrella"]
    elif season == "summer":
        packing += ["Sun hat, sunscreen, sunglasses", "Light breathable clothing", "Insect repellent"]
    elif season == "spring":
        packing += ["Light rain jacket", "Light layers"]
    else:  # fall
        packing += ["Light layers", "Compact umbrella"]

    if travelers and travelers > 1:
        packing += ["Shared chargers/multi-outlet adapter"]

    return json.dumps(
        {
            "destination": key,
            "restaurants": restaurants[: max(2, min(4, travelers + 1))],
            "packing_list": packing,
            "local_tips": city_tips,
        },
        ensure_ascii=False,
    )


__all__ = ["local_guides", "GUIDES_DB"]