"""Curated places/activities knowledge base (Itinerary Agent's first tool).

This is the "choose your own" tool for itinerary construction: a small,
offline database of candidate attractions per destination, tagged with the
interest categories they satisfy. The agent selects a subset that matches the
traveler's interests and trip length. Unknown destinations degrade gracefully
to whatever the research report surfaced (with a note).
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

# --------------------------------------------------------------------------- #
# Curated database  (name -> attractions with category tags)
# --------------------------------------------------------------------------- #
PLACES_DB: dict[str, dict] = {
    "Paris": {
        "attractions": [
            {
                "name": "Eiffel Tower",
                "area": "Champ de Mars",
                "category": ["culture", "architecture"],
                "description": "Iconic iron lattice tower with summit views.",
                "why_visit": "The symbol of Paris; best at sunset.",
                "tip": "Pre-book elevator tickets.",
            },
            {
                "name": "Louvre Museum",
                "area": "Rue de Rivoli",
                "category": ["art", "history"],
                "description": "World's largest art museum (Mona Lisa).",
                "why_visit": "Unmissable collection; give it a half-day.",
                "tip": "Book timed entry in advance.",
            },
            {
                "name": "Musée d'Orsay",
                "area": "Rive Gauche",
                "category": ["art"],
                "description": "Impressionist collection in a former rail station.",
                "why_visit": "Monet, Van Gogh, Renoir.",
                "tip": "Pair with Tuileries Garden.",
            },
            {
                "name": "Montmartre & Sacré-Cœur",
                "area": "18th arrondissement",
                "category": ["culture", "art"],
                "description": "Hilltop art district with basilica.",
                "why_visit": "Panoramas + lively streets.",
                "tip": "Expect street crowds on weekends.",
            },
            {
                "name": "Seine Cruise",
                "area": "City centre",
                "category": ["relaxed", "romantic"],
                "description": "Boat tour past the riverside monuments.",
                "why_visit": "Low-effort landmark tour.",
                "tip": "Dusk cruise for lights.",
            },
            {
                "name": "Le Marais & Place des Vosges",
                "area": "3rd/4th arr.",
                "category": ["food", "shopping", "history"],
                "description": "Historic quarter of boutiques and cafés.",
                "why_visit": "Food, vintage shops, galleries.",
                "tip": "Best for food tours.",
            },
            {
                "name": "Palace of Versailles",
                "area": "Versailles",
                "category": ["history", "architecture"],
                "description": "Royal palace and gardens, ~40 min from centre.",
                "why_visit": "Full-day royal history.",
                "tip": "Go at opening time.",
            },
            {
                "name": "Luxembourg Gardens",
                "area": "6th arrondissement",
                "category": ["relaxed", "nature", "family"],
                "description": "Formal gardens with statues and ponds.",
                "why_visit": "Slow city afternoon.",
                "tip": "Free entrance.",
            },
        ]
    },
    "Tokyo": {
        "attractions": [
            {
                "name": "Senso-ji Temple",
                "area": "Asakusa",
                "category": ["history", "culture"],
                "description": "Tokyo's oldest temple, via Kaminarimon gate.",
                "why_visit": "Classic shrine-town streets.",
                "tip": "Go early to beat crowds.",
            },
            {
                "name": "Shibuya Crossing & Hachikō",
                "area": "Shibuya",
                "category": ["culture", "food"],
                "description": "The famous scramble crossing.",
                "why_visit": "Tokyo energy in one shot.",
                "tip": "Best photo from a first-floor café.",
            },
            {
                "name": "teamLab Planets",
                "area": "Toyosu",
                "category": ["art", "family"],
                "description": "Immersive digital-art museum.",
                "why_visit": "Sensory installations.",
                "tip": "Book timed tickets ahead.",
            },
            {
                "name": "Meiji Shrine",
                "area": "Shibuya",
                "category": ["nature", "culture"],
                "description": "Shinto shrine in a forested park.",
                "why_visit": "Calm by Harajuku.",
                "tip": "Watch ceremonial weddings.",
            },
            {
                "name": "Ueno Park & Tokyo National Museum",
                "area": "Ueno",
                "category": ["art", "history", "nature"],
                "description": "Museums and park in one area.",
                "why_visit": "Culture in a green setting.",
                "tip": "Close by Ameya-Yokochō market.",
            },
            {
                "name": "Tsukiji Outer Market",
                "area": "Tsukiji",
                "category": ["food"],
                "description": "Street food and knife stalls.",
                "why_visit": "Fresh seafood breakfast.",
                "tip": "Bring cash, arrive early.",
            },
            {
                "name": "Shinjuku Gyoen",
                "area": "Shinjuku",
                "category": ["nature", "relaxed"],
                "description": "Large city garden.",
                "why_visit": "Seasonal blossoms.",
                "tip": "Great picnic spot.",
            },
            {
                "name": "Harajuku & Takeshita Street",
                "area": "Harajuku",
                "category": ["shopping", "food"],
                "description": "Youth culture and quirky cafés.",
                "why_visit": "Pop culture shopping.",
                "tip": "Best on weekdays.",
            },
        ]
    },
    "New York": {
        "attractions": [
            {
                "name": "Statue of Liberty & Ellis Island",
                "area": "Liberty Island",
                "category": ["history", "culture"],
                "description": "Harbor icons of American immigration.",
                "why_visit": "Essential NYC history.",
                "tip": "Book ferry tickets in advance.",
            },
            {
                "name": "Central Park",
                "area": "Manhattan",
                "category": ["nature", "relaxed", "family"],
                "description": "843-acre green heart of the city.",
                "why_visit": "Bikes, lakes, monuments.",
                "tip": "Rent a bike for the loop.",
            },
            {
                "name": "The Met",
                "area": "Upper East Side",
                "category": ["art", "history"],
                "description": "Encyclopedic art museum.",
                "why_visit": "200+ galleries of art.",
                "tip": "Arrive at opening.",
            },
            {
                "name": "Brooklyn Bridge & DUMBO",
                "area": "Brooklyn",
                "category": ["architecture", "relaxed"],
                "description": "Iconic cable bridge with skyline views.",
                "why_visit": "Sunset skyline photos.",
                "tip": "Walk it early morning.",
            },
            {
                "name": "Top of the Rock",
                "area": "Midtown",
                "category": ["culture", "relaxed"],
                "description": "Observation deck over the skyline.",
                "why_visit": "Best Empire State view.",
                "tip": "Sunset slot sells out.",
            },
            {
                "name": "Broadway Theatre",
                "area": "Theatre District",
                "category": ["culture"],
                "description": "World-class stage shows.",
                "why_visit": "Top musicals and plays.",
                "tip": "Same-day TKTS for discounts.",
            },
            {
                "name": "Chelsea Market & High Line",
                "area": "Chelsea",
                "category": ["food", "shopping"],
                "description": "Market halls and elevated park.",
                "why_visit": "Food halls + garden walk.",
                "tip": "Churros at the market.",
            },
            {
                "name": "Museum of Modern Art",
                "area": "Midtown",
                "category": ["art"],
                "description": "Modern masterpieces (Van Gogh, Picasso).",
                "why_visit": "Crown jewels of modern art.",
                "tip": "Free Friday evenings.",
            },
        ]
    },
    "London": {
        "attractions": [
            {
                "name": "British Museum",
                "area": "Bloomsbury",
                "category": ["art", "history"],
                "description": "Collections from every civilization.",
                "why_visit": "Free and world-class.",
                "tip": "Arrive before opening.",
            },
            {
                "name": "Tower of London",
                "area": "Tower Hill",
                "category": ["history"],
                "description": "900-year-old royal fortress and Crown Jewels.",
                "why_visit": "Deep history in one fortress.",
                "tip": "Book timeslots in advance.",
            },
            {
                "name": "Tower Bridge",
                "area": "Tower Hill",
                "category": ["architecture", "culture"],
                "description": "Victorian bascule bridge and walkway.",
                "why_visit": "Glass-floor high walkway.",
                "tip": "Combine with the Tower.",
            },
            {
                "name": "Westminster & Big Ben",
                "area": "Westminster",
                "category": ["history", "culture"],
                "description": "Parliament, Abbey and the famous clock.",
                "why_visit": "Iconic photo stops.",
                "tip": "Best morning light on the river.",
            },
            {
                "name": "Camden Market",
                "area": "Camden",
                "category": ["food", "shopping"],
                "description": "Alternative fashion and food stalls.",
                "why_visit": "Eclectic street food.",
                "tip": "Go early for the good stalls.",
            },
            {
                "name": "Hyde Park & Kensington",
                "area": "Hyde Park",
                "category": ["nature", "relaxed"],
                "description": "Royal parks, Serpentine lake.",
                "why_visit": "Green calm + museums nearby.",
                "tip": "Boat rental on the Serpentine.",
            },
            {
                "name": "Borough Market",
                "area": "Southwark",
                "category": ["food"],
                "description": "900-year-old food market.",
                "why_visit": "Cheese, bread, street eats.",
                "tip": "Avoid midday weekends.",
            },
            {
                "name": "National Gallery",
                "area": "Trafalgar Square",
                "category": ["art"],
                "description": "European paintings from 13th–19th century.",
                "why_visit": "Free masterpieces.",
                "tip": "Focus on one wing per visit.",
            },
        ]
    },
    "Bangkok": {
        "attractions": [
            {
                "name": "Grand Palace",
                "area": "Rattanakosin",
                "category": ["history", "culture"],
                "description": "Resplendent royal complex and Wat Phra Kaew.",
                "why_visit": "Bangkok's most iconic site.",
                "tip": "Long trousers/skirts required.",
            },
            {
                "name": "Wat Arun",
                "area": "Thonburi",
                "category": ["culture", "architecture"],
                "description": "Riverside 'Temple of Dawn'.",
                "why_visit": "Best at sunset, riverside.",
                "tip": "Take the cross-river ferry.",
            },
            {
                "name": "Chatuchak Weekend Market",
                "area": "Chatuchak",
                "category": ["shopping", "food"],
                "description": "15,000+ stalls of everything.",
                "why_visit": "The world's great weekend market.",
                "tip": "Weekends only; go early.",
            },
            {
                "name": "Chinatown Food Walk",
                "area": "Yaowarat",
                "category": ["food"],
                "description": "Street-food paradise after dark.",
                "why_visit": "Some of the best food in Asia.",
                "tip": "Hawk stall scooters; move carefully.",
            },
            {
                "name": "Khlong Bangkok canals",
                "area": "Old City",
                "category": ["culture", "nature"],
                "description": "Longtail-boat rides through canal life.",
                "why_visit": "See the 'Venice of the East' side.",
                "tip": "Take a boat from Maharaj pier.",
            },
            {
                "name": "Jim Thompson House",
                "area": "Siam",
                "category": ["history", "culture"],
                "description": "Traditional Thai teak home and silk museum.",
                "why_visit": "Calm and beautifully preserved.",
                "tip": "Guided tours every 30 min.",
            },
            {
                "name": "Lumphini Park",
                "area": "Sathorn",
                "category": ["nature", "relaxed"],
                "description": "City green with lakes and monitor lizards.",
                "why_visit": "Morning joggers and calm.",
                "tip": "Great sunrise walk.",
            },
        ]
    },
}

_GENERIC_PLACE = {
    "name": "Old Town & Central Landmarks",
    "area": "City centre",
    "category": ["culture", "history"],
    "description": "A guided walk through the central historic district.",
    "why_visit": "Introduction to the city on foot.",
    "tip": "Start with a walking-tour map.",
}


def _rank(attractions: list[dict], interests: list[str]) -> list[dict]:
    """Score attractions by how many traveler interests they satisfy."""
    interests_lower = [i.strip().lower() for i in (interests or [])]

    def score(a: dict) -> int:
        cats = [c.lower() for c in a.get("category", [])]
        matched = sum(1 for i in interests_lower if any(i in c for c in cats))
        if matched == 0 and any(c in cats for c in ("culture", "food", "history")):
            matched = 1  # safe default affinity
        return matched

    ranked = sorted(attractions, key=score, reverse=True)
    top_score = ranked[0].get("_match", 0) if ranked else 0
    for a in ranked:
        a["_match"] = score(a)
    return ranked


@tool
def places_database(destination: str, interests: list[str], days: int = 1) -> str:
    """Look up curated candidate places/activities for a destination, matched
    to the traveler's interests. Returns a JSON string.

    Args:
        destination: The city/destination name.
        interests: The traveler's interest tags (e.g. art, food, hiking).
        days: Trip length in days (controls how many suggestions to return).
    """
    key = destination.strip().title()
    entry = PLACES_DB.get(key)
    if entry is None:
        # No curated data -> return a generic walk suggestion plus a hint that
        # the destination wasn't in our database.
        return json.dumps(
            {
                "destination": key,
                "note": f"No curated data for {key}; lean on research report.",
                "attractions": [_GENERIC_PLACE],
            },
            ensure_ascii=False,
        )

    ranked = _rank(entry["attractions"], interests or [])
    limit = max(2, min(8, int(days) * 2))
    ranked = ranked[:limit]
    for a in ranked:
        a.pop("_match", None)

    payload = {
        "destination": key,
        "note": "Top picks matched to interests.",
        "attractions": ranked,
    }
    return json.dumps(payload, ensure_ascii=False)


__all__ = ["places_database", "PLACES_DB"]