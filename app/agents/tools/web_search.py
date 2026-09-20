"""The mandatory web-search tool.

Backends (selected by ``WEB_SEARCH_PROVIDER`` in the environment):
* ``serper`` — calls the Serper API (serper.dev).
* ``exa``    — calls the Exa API (exa.ai).
* ``mock``   — deterministic curated content, so the system runs offline.

The tool always returns a **JSON string** with a consistent schema. Real
backends degrade gracefully to curated fallback content (marked in
``sources``) so a transient failure never breaks a plan.
"""

from __future__ import annotations

import json
from functools import lru_cache

import requests
from langchain_core.tools import tool

from app.config import Settings

# --------------------------------------------------------------------------- #
# Curated fallback content (used by the mock backend and as a safety net)
# --------------------------------------------------------------------------- #
_MOCK_SEARCH: dict[str, dict] = {
    "Paris": {
        "overview": "Paris is France's capital — iconic monuments, world-class "
        "museums, café culture and grand boulevards make it ideal for a cultural trip.",
        "attractions": [
            {
                "name": "Eiffel Tower",
                "area": "7th arrondissement",
                "category": ["architecture", "culture"],
                "description": "The iconic 1889 lattice tower with panoramic views.",
                "why_visit": "Best views of the skyline, especially at sunset.",
                "tip": "Book entry slots online well in advance.",
            },
            {
                "name": "Louvre Museum",
                "area": "1st arrondissement",
                "category": ["art", "history", "culture"],
                "description": "The world's largest art museum, home of the Mona Lisa.",
                "why_visit": "Unmatched art collection across every era.",
                "tip": "Pre-book timed tickets; mornings are quieter.",
            },
            {
                "name": "Musée d'Orsay",
                "area": "7th arrondissement",
                "category": ["art", "culture"],
                "description": "Impressionist masterpieces in a former railway station.",
                "why_visit": "Monet, Van Gogh and Renoir in one elegant setting.",
                "tip": "Combine with the nearby Tuileries Garden walk.",
            },
            {
                "name": "Notre-Dame Cathedral",
                "area": "Île de la Cité",
                "category": ["architecture", "history", "culture"],
                "description": "Gothic masterpiece and heart of medieval Paris.",
                "why_visit": "Free to view the exterior and riverside setting.",
                "tip": "Check re-opening status before your visit.",
            },
            {
                "name": "Montmartre & Sacré-Cœur",
                "area": "18th arrondissement",
                "category": ["culture", "art"],
                "description": "Village-like hilltop quarter with basilica views.",
                "why_visit": "Artists, cafés and the best panorama over Paris.",
                "tip": "Climb the dome for a full 360° view.",
            },
            {
                "name": "Seine River cruise",
                "area": "City centre",
                "category": ["relaxed", "culture"],
                "description": "See the riverside monuments from the water.",
                "why_visit": "Low-effort way to take in many landmarks.",
                "tip": "Take a dusk cruise for the sparkling Eiffel Tower.",
            },
            {
                "name": "Le Marais & Place des Vosges",
                "area": "3rd/4th arrondissements",
                "category": ["food", "shopping", "history"],
                "description": "Historic Jewish quarter with boutiques and galleries.",
                "why_visit": "Great for food, vintage shopping and cafés.",
                "tip": "Pick up falafel and pastries from the street markets.",
            },
            {
                "name": "Palace of Versailles",
                "area": "Versailles, ~20 km west",
                "category": ["history", "architecture", "culture"],
                "description": "The opulent royal palace and its vast gardens.",
                "why_visit": "A day-trip into French royal history.",
                "tip": "Big crowds: arrive before opening.",
            },
        ],
        "safety_notes": [
            "Paris is generally safe; watch for pickpockets in Métro and tourist spots.",
            "Be aware of common scam attempts around Eiffel Tower and Montmartre.",
        ],
        "local_tips": [
            "The Métro is fast and frequent; buy a multi-day Navigo pass.",
            "Many museums are free on the first Sunday of the month.",
            "Dinner is typically eaten 19:30–21:30; reserve popular places.",
        ],
        "seasonal_notes": [
            "Summer is warm with long evenings; spring (Apr–Jun) is pleasant and light.",
            "Winter is chilly but quiet; the city lights are magical in December.",
        ],
    },
    "Tokyo": {
        "overview": "Tokyo is a hyper-modern metropolis with neon districts, "
        "quiet temples and food culture that rewards slow exploration.",
        "attractions": [
            {
                "name": "Shibuya Crossing",
                "area": "Shibuya",
                "category": ["culture", "food"],
                "description": "The world-famous scramble crossing and Hachikō statue.",
                "why_visit": "The quintessential Tokyo energy shot.",
                "tip": "View from the Starbucks over the scramble for the classic photo.",
            },
            {
                "name": "Senso-ji Temple",
                "area": "Asakusa",
                "category": ["history", "culture"],
                "description": "Tokyo's oldest temple via the Kaminarimon gate.",
                "why_visit": "Classic shrine-town atmosphere and street food.",
                "tip": "Go early or late to avoid crowds; try ningyo-yaki on Nakamise.",
            },
            {
                "name": "Meiji Shrine",
                "area": "Shibuya/Harajuku",
                "category": ["history", "nature", "culture"],
                "description": "Serene Shinto shrine in a forested park.",
                "why_visit": "Moments of calm right by Harajuku's bustle.",
                "tip": "Sunday weddings of ceremonial kimono are common.",
            },
            {
                "name": "teamLab Planets",
                "area": "Toyosu",
                "category": ["culture", "family", "art"],
                "description": "Immersive digital-art installation museum.",
                "why_visit": "Stunning sensory art; shoes-off walk through water.",
                "tip": "Book timed tickets, usually weeks ahead.",
            },
            {
                "name": "Ueno Park & Museums",
                "area": "Ueno",
                "category": ["art", "nature", "history"],
                "description": "Parks, cherry blossoms and major museums.",
                "why_visit": "Tokyo National Museum and zoo in one green space.",
                "tip": "Combine with Ameya-Yokochō market street.",
            },
            {
                "name": "Tsukiji Outer Market",
                "area": "Tsukiji",
                "category": ["food"],
                "description": "Fresh seafood stalls, knife shops and street eats.",
                "why_visit": "Tuna, tamago and fresh sushi at street stalls.",
                "tip": "Go early; bring cash.",
            },
            {
                "name": "Odaiba Waterfront",
                "area": "Odaiba",
                "category": ["family", "relaxed"],
                "description": "Rainbow Bridge views and toy/shopping districts.",
                "why_visit": "Evening Rainbow Bridge and ferris wheel.",
                "tip": "Pairs well with teamLab Planets the same day.",
            },
            {
                "name": "Shinjuku Gyoen Garden",
                "area": "Shinjuku",
                "category": ["nature", "relaxed"],
                "description": "City oasis mixing Japanese, French and English gardens.",
                "why_visit": "Cherry blossoms in spring, quiet green in summer.",
                "tip": "Great picnic spot between sightseeing blocks.",
            },
        ],
        "safety_notes": [
            "Tokyo is extremely safe, even at night.",
            "Mind etiquette: no eating while walking, quiet in trains.",
        ],
        "local_tips": [
            "An IC card (Suica/Pasmo) makes trains and konbini effortless.",
            "Reserve top sushi/skewer spots; many have long queues.",
            "Taxis are pricey; transit is the way.",
        ],
        "seasonal_notes": [
            "Cherry blossom peaks late March–early April.",
            "Summer is hot and humid; autumn (Nov) is crisp and clear.",
        ],
    },
}

_GENERIC = {
    "overview": "{d} is a well-loved travel destination with rich culture, "
    "food and sightseeing options.",
    "attractions": [],
    "safety_notes": ["Keep standard tourist precautions in mind."],
    "local_tips": ["Reserve popular venues ahead."],
    "seasonal_notes": ["Check the seasonal forecast for your exact dates."],
}


def _mock_search(query: str, location: str) -> dict:
    key = (location or "").strip().title()
    entry = _MOCK_SEARCH.get(key)
    if entry is None:
        entry = dict(_GENERIC)
        entry["overview"] = entry["overview"].format(d=key)
    content = dict(entry)
    content["sources"] = [f"mock-curated:{key.lower()}"]
    return content


# --------------------------------------------------------------------------- #
# Real backends
# --------------------------------------------------------------------------- #
def _serper_search(query: str, api_key: str) -> dict:
    resp = requests.post(
        "https://google.serper.dev/search",
        json={"q": query, "gl": "us", "hl": "en", "num": 10},
        headers={"X-API-KEY": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    organic = data.get("organic", [])[:8]
    result = {
        "sources": [item.get("link", "") for item in organic],
        "articles": [
            {
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": item.get("link", ""),
            }
            for item in organic
        ],
    }
    return result


def _exa_search(query: str, api_key: str) -> dict:
    resp = requests.post(
        "https://api.exa.ai/search",
        json={
            "query": query,
            "numResults": 6,
            "contents": {"title": True, "highlights": True, "summary": True},
        },
        headers={"x-api-key": api_key},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])[:6]
    return {
        "sources": [item.get("url", "") for item in results],
        "articles": [
            {
                "title": item.get("title", ""),
                "snippet": item.get("text") or item.get("summary") or "",
                "link": item.get("url", ""),
            }
            for item in results
        ],
    }


# --------------------------------------------------------------------------- #
# Public tool
# --------------------------------------------------------------------------- #
@tool
def web_search(query: str, location: str = "") -> str:
    """Search the web for travel intelligence (attractions, safety, weather,
    seasonal notes, local tips) for the given destination. Returns a JSON string.

    Args:
        query: The search query to run against the provider.
        location: The destination name, used for fallback content.
    """
    settings = _settings_cache()
    provider = _effective_provider(settings)

    try:
        if provider == "serper":
            payload = _serper_search(query, settings.serper_api_key or "")
        elif provider == "exa":
            payload = _exa_search(query, settings.exa_api_key or "")
        elif provider == "mock":
            payload = _mock_search(query, location)
        else:
            payload = _mock_search(query, location)
    except Exception as exc:  # noqa: BLE001 - graceful degradation
        payload = _mock_search(query, location)
        payload["fallback_reason"] = f"{type(exc).__name__}: {exc}"

    return json.dumps(payload, ensure_ascii=False)


@lru_cache
def _settings_cache() -> Settings:
    from app.config import get_settings

    return get_settings()


def _effective_provider(settings: Settings) -> str:
    return settings.effective_web_search_provider


__all__ = ["web_search"]