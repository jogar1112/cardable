# Cardable — Build Notes

**Build label:** `Build 2026-11-13 · Cardable v0.2` (served at `GET /api/build`, shown in the page footer)
**Stack:** Python 3.12 + FastAPI + WebSockets + SQLite + vanilla JS. No frameworks, no build steps. Blockbustarr codebase patterns throughout.

## What v0.2 adds (2026-11-13)

1. **Keyword search — the deck pre-filter** (design file 02, built at Joey's word). SEARCH-family phrases now capture their filter blank (`search your library for a [filter] card …`), parse it into keyword groups (types / traits / colors / names / number comparisons like "mana value 3 or less" / qualifiers like basic, nonbasic, legendary; AND across groups, OR inside, unknown words fall back to substring), and the long-hold opens the **deck view**: the server flags matches in a direct reply only the searcher receives, matches render lit, non-matches dimmed but visible — the filter never hides a card. Tap a card to take it; a soft tally tracks "up to N" without enforcing it. A same-sentence "…, then shuffle" is owned by the search match and offered in the deck view as **Shuffle, then done**; a shuffle printed as its own sentence stays its own link. The Yu-Gi-Oh! "add 1 [X] from your Deck to your hand" shape maps to the same search.
2. **Top-N peek with the same filter** — "look at the top N cards … you may reveal a [filter] from among them … recycle the rest" (the Riftbound shape) opens the deck view over just the top N, with **Recycle the rest** as its tail (un-taken cards go to the bottom of the deck, order preserved). The Riftbound pack still has NO whole-deck search phrase — verified texts never produce one.
3. **Privacy holds**: search results travel in a WebSocket direct reply to the requester only (never the broadcast); opponents see a "🔍 searching <stack>…" flag on the searcher's seat; searching another seat's hidden stack is refused server-side. Deck-role stack tools also gained a manual **🔍 Search deck** button with a typed keyword box running the same engine (the plain-deck path).
4. **Type lines**: library cards gained a `type_line` field (SQLite migration, editable in the library, filled automatically by the Scryfall lane) — it's what type/trait/qualifier matching reads, alongside name and text.
5. **Touch fix (Joey's report: finger drags dragged the screen)**: `#felt`, `.stack`, `.tcard`, `.die` and phrase links now carry `touch-action:none`, drags capture the pointer, and the piece **follows the finger live** instead of teleporting on release; the stray click a drag produces on release is swallowed for cards and dice (a dragged die no longer rolls itself).

**Tests**: `tests/test_search.py` — **31 checks** (phrase shapes incl. the Riftbound no-search rule, filter parsing/matching, wire privacy of the search reply, take/recycle order, refusal for other seats' decks). `tests/test_flow.py` still **43/43**, `tests/test_boot.py` passes. A jsdom harness driving the real client against the real server (long-hold → deck view → take → tails, live drag-follow) passes 21/21; copy kept in the Retro Card Table goal's `hidden_files/harness-cardable-v02.js`.

## v0.1 (2026-11-06)

1. **Server-as-dealer multiplayer core** — WebSocket room (`/ws/table/{code}`), up to 4 seats, per-viewer state serialization in `app/room.py::view()`. A client never receives another player's hand, a hidden stack's contents, or a face-down card's identity (proven on the wire by the flow tests). Seats and hands survive disconnect; reconnecting with the same player token restores them. Sandbox actions only — no rules, no turn engine — plus a manual **turn indicator** the current player passes.
2. **The table** — mobile-first, seat-relative rendering; GBA/SNES-band pixel chrome; real card faces (uploaded images) inside the retro frame. Stacks are named areas with roles and visibility (hidden/top/open). Players drag stacks during the **setup** phase; positions **lock** when the host starts the game (locked attempts are logged, not silently dropped). Starter profiles: **Standard 52-Card**, **TCG (Library/Graveyard/Exile/Battlefield/Command)**, **Uno-Style (two piles)**. Saving a setup as a personal game works and a table can be created from a saved game.
3. **Built-in standard deck** — 52 cards + 2 jokers, zero intake. Faces are drawn programmatically as inline SVG (pips/ranks, classic pip layouts) in `app/static/app.js`. No copyrighted art anywhere.
4. **Physical dice on the table** — dice are objects resting on the felt: d4/d6/d8/d10/d%/d12/d20 + coin, custom side counts (2–1000), tap to roll in place, drag to move, drop on a card to park it as a counter. The **server generates every roll** and broadcasts one result to all clients (flow-tested identical).
5. **Glance layer** — each profile declares its primary number (`rank_suit` for playing cards, `primary` otherwise); it renders big from the data layer on table-sized cards and in hand. **Double-tap** (or double-click) opens the examine view: card big + clean confirmed text in a panel. Foregrounding is purely local — it cannot reveal a face the server didn't send.
6. **Custom card intake (basics)** — upload an image to your **personal** library; the image is the face and the card is playable immediately; name/text/primary-number are editable (the confirm/correct step). Decks are selections from your own library only (the server rejects building a deck from someone else's cards). Bring a deck to a table into a deck-role stack; contents stay hidden from opponents until drawn/played.
7. **Key-phrase action links (subset)** — data-driven exact matching (`app/phrases.py`, from the universal core in design file 02): `draw N` (digits or number-words, from your deck-role stack), `shuffle`, `flip a coin`, `roll a die` / `roll a dN`. Matched phrases in a card's confirmed text become links in the examine view. Long-hold shows a filling pixel progress bar; release cancels. Per-player setting chooses **instant-fire** vs **arm-then-confirm-tap** (persisted server-side). Links only offer actions — no legality checks, per the sandbox rule.

## Stubbed / seamed — honestly

- **OCR is a stub.** `app/ocr.py::extract_text()` is the clean interface; the v1 engine returns an empty draft plus a note saying so. Uploads are playable instantly regardless; a real engine (tesseract/cloud) drops in behind that one function.
- **Scryfall fast lane is implemented but live-dependent.** `POST /api/library/{id}/scryfall` looks the card's name up on the free keyless Scryfall API and fills text/primary from the record (image URL returned as `scryfall_image`). It needs internet access from the container; it was not exercised in the offline test suite.
- **Rooms are in-memory.** Live table state is not persisted across a server restart (libraries, decks, saved games, and settings ARE persisted in SQLite on the data volume). Room persistence is the natural next step.
- **No accounts/passwords.** Players are name + bearer token stored on the device (Blockbustarr-style profiles/PINs are a later layer). Table access is by 4-hex-char room code.
- **Camera/sheet scanning** (design file 03) is not in v1 — file upload only. The auto-snap/sheet-mode pipeline lands behind the same intake interface later.
- **Phrase library** covers the v1 subset above only; the full per-game packs from design file 02 are data additions, not code changes.
- Dice rolls use Python's `random` (server-side, single source) — fine for a friendly sandbox table; not a cryptographic audit trail.

## Tests

- `tests/test_flow.py` — **43 checks, all passing**: phrase parsing, per-player settings, two clients playing the built-in deck, wire-level privacy assertions (opponent payloads contain no hand or face-down identities), server dice identical for all clients, custom dice, die-as-counter, turn passing, reconnect seat/hand restore, setup arrange → start → lock holds, upload/edit/deck ownership, deck bring + draw privacy, saved-game roundtrip.
- `tests/test_boot.py` — subprocess boot against a fresh temp data dir: build label, status, index page, player creation.
- `python -m compileall` clean; `node --check` clean on all JS.
- Fixture note: the flow test deletes `tests/data_flow/` before running — re-running against residue causes false sqlite failures.

Run them with any venv that has fastapi/httpx/uvicorn/python-multipart:
`python tests/test_flow.py && python tests/test_boot.py`

## Run it (Portainer)

1. In Portainer: **Stacks → Add stack → Repository**, URL = this repo (`https://github.com/jogar1112/cardable`), compose path `docker-compose.yml`.
2. Deploy. The stack builds the image, publishes **host port 8901** → container 8000, and stores data (SQLite + uploaded card images) in the named volume `cardable-data`.
3. Open `http://<docker-host>:8901`, enter a name, create a table, share the 4-character code. A second player joins from their phone with the same code.
4. Updates: pull-and-redeploy the stack (Blockbustarr pattern; no `image:` line, so Portainer rebuilds from git).

Local run without Docker: `pip install -r requirements.txt && uvicorn app.main:app --port 8901` (set `DATA_DIR` to choose where data lives; default `./data`).
