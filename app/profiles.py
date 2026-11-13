"""Starter game profiles: a saved setup bundles the stack set (names +
roles + visibility), positions, zone vocabulary and the glance field."""

# visibility: hidden = contents server-secret (count only)
#             top    = only the top card is public
#             open   = all cards public
STARTER_PROFILES = {
    "standard52": {
        "id": "standard52",
        "name": "Standard 52-Card",
        "glance": "rank_suit",
        "shared_stacks": [
            {"key": "deck", "name": "Deck", "role": "deck", "visibility": "hidden", "x": 8, "y": 30},
            {"key": "discard", "name": "Discard", "role": "discard", "visibility": "top", "x": 82, "y": 30},
            {"key": "play", "name": "Play Area", "role": "play", "visibility": "open", "x": 45, "y": 30},
        ],
        "seat_stacks": [],
    },
    "tcg": {
        "id": "tcg",
        "name": "TCG (Library / Graveyard / Exile)",
        "glance": "primary",
        "shared_stacks": [],
        "seat_stacks": [
            {"key": "library", "name": "Library", "role": "deck", "visibility": "hidden", "x": 82, "y": 62},
            {"key": "battlefield", "name": "Battlefield", "role": "play", "visibility": "open", "x": 45, "y": 55},
            {"key": "graveyard", "name": "Graveyard", "role": "discard", "visibility": "top", "x": 8, "y": 62},
            {"key": "exile", "name": "Exile", "role": "exile", "visibility": "open", "x": 82, "y": 88},
            {"key": "command", "name": "Command", "role": "command", "visibility": "open", "x": 8, "y": 88},
        ],
    },
    "uno": {
        "id": "uno",
        "name": "Uno-Style (Two Piles)",
        "glance": "primary",
        "shared_stacks": [
            {"key": "draw", "name": "Draw Pile", "role": "deck", "visibility": "hidden", "x": 30, "y": 35},
            {"key": "discard", "name": "Discard Pile", "role": "discard", "visibility": "top", "x": 60, "y": 35},
        ],
        "seat_stacks": [],
    },
}
