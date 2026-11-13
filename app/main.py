"""Cardable v0.1 -- a retro multiplayer sandbox card table.

Server-as-dealer: the server holds every deck and hand; clients only ever
receive what their seat is allowed to see (see app/room.py view()).
"""
import os
import secrets

import httpx
from fastapi import (FastAPI, File, Header, HTTPException, Request,
                     UploadFile, WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .ocr import extract_text
from .phrases import match_filter, match_phrases, parse_filter
from .profiles import STARTER_PROFILES
from .room import Room, builtin_deck

BUILD_LABEL = "Build 2026-11-13 · Cardable v0.2"
BASE = os.path.dirname(__file__)
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE, "..", "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

app = FastAPI(title="Cardable")
ROOMS = {}


@app.on_event("startup")
def _startup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db.init_db()


def _player(x_player_token: str = Header(default="")):
    p = db.player_by_token(x_player_token)
    if not p:
        raise HTTPException(401, "unknown player token")
    return p


# ---------------------------------------------------------------- basics
@app.get("/api/build")
def build():
    return {"build": BUILD_LABEL}


@app.get("/api/status")
def status():
    return {"ok": True, "build": BUILD_LABEL, "rooms": len(ROOMS)}


@app.post("/api/players")
async def create_player(req: Request):
    body = await req.json()
    name = (body.get("name") or "Player").strip()[:24] or "Player"
    return db.create_player(name)


@app.get("/api/settings")
def get_settings(x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    return db.get_settings(player["id"])


@app.put("/api/settings")
async def put_settings(req: Request, x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    body = await req.json()
    if body.get("link_mode") not in (None, "instant", "confirm"):
        raise HTTPException(400, "link_mode must be instant|confirm")
    return db.set_settings(player["id"], body)


# ---------------------------------------------------------------- library
@app.get("/api/library")
def library(x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    return db.list_library(player["id"])


@app.post("/api/library/upload")
async def upload_card(file: UploadFile = File(...), x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        raise HTTPException(400, "image files only")
    fname = f"{player['id']}-{secrets.token_hex(6)}{ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    with open(path, "wb") as f:
        f.write(await file.read())
    draft = extract_text(path)  # stub OCR seam; image is playable NOW
    card_id = db.add_library_card(player["id"], draft["name"], draft["text"],
                                  draft["primary"], f"/uploads/{fname}")
    card = db.get_library_card(player["id"], card_id)
    card["ocr"] = draft
    return card


@app.put("/api/library/{card_id}")
async def edit_card(card_id: int, req: Request, x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    body = await req.json()
    card = db.get_library_card(player["id"], card_id)
    if not card:
        raise HTTPException(404, "card not in your library")
    db.update_library_card(player["id"], card_id,
                           body.get("name", ""), body.get("text", ""),
                           body.get("primary", ""),
                           body.get("type_line", card.get("type_line", "")))
    return db.get_library_card(player["id"], card_id)


@app.post("/api/library/{card_id}/scryfall")
async def scryfall_upgrade(card_id: int, x_player_token: str = Header(default="")):
    """MTG fast lane: replace a library card's data with Scryfall's record
    matched by its current name. Free, keyless API."""
    player = _player(x_player_token)
    card = db.get_library_card(player["id"], card_id)
    if not card:
        raise HTTPException(404, "card not in your library")
    if not card["name"]:
        raise HTTPException(400, "name the card first (OCR draft or typing)")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://api.scryfall.com/cards/named",
                             params={"fuzzy": card["name"]})
    if r.status_code != 200:
        raise HTTPException(404, "no Scryfall match for that name")
    data = r.json()
    image = (data.get("image_uris") or {}).get("normal", "")
    text = data.get("oracle_text", "")
    primary = str(data.get("mana_cost", "")).strip("{}").replace("}{", " ")
    db.update_library_card(player["id"], card_id, data.get("name", card["name"]),
                           text, primary or card["primary_number"],
                           data.get("type_line", ""))
    out = db.get_library_card(player["id"], card_id)
    out["scryfall_image"] = image
    return out


# ---------------------------------------------------------------- decks
@app.get("/api/decks")
def decks(x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    return db.list_decks(player["id"])


@app.post("/api/decks")
async def create_deck(req: Request, x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    body = await req.json()
    card_ids = [int(c) for c in body.get("card_ids", [])]
    for cid in card_ids:
        if not db.get_library_card(player["id"], cid):
            raise HTTPException(400, f"card {cid} is not in YOUR library")
    deck_id = db.create_deck(player["id"], body.get("name", "Deck"), card_ids)
    return db.get_deck(player["id"], deck_id)


# ---------------------------------------------------------------- profiles
@app.get("/api/profiles")
def profiles():
    return list(STARTER_PROFILES.values())


@app.get("/api/my-profiles")
def my_profiles(x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    return db.list_profiles(player["id"])


@app.post("/api/my-profiles")
async def save_my_profile(req: Request, x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    body = await req.json()
    data = body.get("data") or {}
    for key in ("shared_stacks", "seat_stacks"):
        for st in data.get(key, []):
            for field in ("name", "role", "visibility"):
                if field not in st:
                    raise HTTPException(400, f"stack missing {field}")
    pid = db.save_profile(player["id"], body.get("name", "My Game"), data)
    return {"id": pid, "name": body.get("name", "My Game"), "data": data}


@app.post("/api/phrases/match")
async def phrase_match(req: Request):
    body = await req.json()
    return {"matches": match_phrases(body.get("text", ""))}


# ---------------------------------------------------------------- rooms (REST helpers)
@app.post("/api/rooms")
async def create_room(req: Request, x_player_token: str = Header(default="")):
    player = _player(x_player_token)
    body = await req.json()
    profile_id = body.get("profile_id", "standard52")
    if profile_id in STARTER_PROFILES:
        profile = STARTER_PROFILES[profile_id]
    else:
        profile = None
        for saved in db.list_profiles(player["id"]):
            if str(saved["id"]) == str(profile_id):
                profile = dict(saved["data"])
                profile.setdefault("name", saved["name"])
                profile.setdefault("glance", "primary")
                break
        if profile is None:
            raise HTTPException(404, "unknown profile")
    code = secrets.token_hex(2).upper()
    room = Room(code, profile, player["id"])
    ROOMS[code] = room
    return {"code": code}


# ---------------------------------------------------------------- websocket table
@app.websocket("/ws/table/{code}")
async def table_ws(ws: WebSocket, code: str):
    await ws.accept()
    token = ws.query_params.get("token", "")
    player = db.player_by_token(token)
    room = ROOMS.get(code.upper())
    if not player or not room:
        await ws.send_json({"type": "error", "message": "bad token or room code"})
        await ws.close()
        return
    seat = room.join(player)
    if seat is None:
        await ws.send_json({"type": "error", "message": "table is full (4 seats)"})
        await ws.close()
        return
    peers = PEERS.setdefault(code.upper(), set())
    peers.add(ws)

    async def broadcast():
        for peer in list(peers):
            try:
                # Each peer gets ITS OWN view -- privacy is per-viewer.
                pseat = room.seat_of(_ws_player[peer]["id"])
                await peer.send_json(room.view(pseat))
            except Exception:
                pass

    _ws_player[ws] = player
    await broadcast()
    try:
        while True:
            msg = await ws.receive_json()
            reply = await _handle(room, player, seat, msg)
            seat = room.seat_of(player["id"])
            if reply is not None:
                # Direct replies (e.g. search results) go ONLY to the
                # requester -- never into the broadcast.
                await ws.send_json(reply)
            await broadcast()
    except WebSocketDisconnect:
        pass
    finally:
        peers.discard(ws)
        _ws_player.pop(ws, None)
        room.disconnect(player["id"])
        for peer in list(peers):
            try:
                pseat = room.seat_of(_ws_player[peer]["id"])
                await peer.send_json(room.view(pseat))
            except Exception:
                pass


_ws_player = {}
PEERS = {}


async def _handle(room: Room, player, seat, msg):
    kind = msg.get("type")
    if kind == "move_stack":
        if room.phase != "setup":
            room._log("Stacks are locked -- the game has started.")
            return
        stack = room.find_stack(msg.get("stack_id", ""))
        if stack and (stack["owner"] == seat or stack["owner"] is None):
            stack["x"] = max(0, min(100, float(msg.get("x", stack["x"]))))
            stack["y"] = max(0, min(100, float(msg.get("y", stack["y"]))))
    elif kind == "start_game":
        if player["id"] == room.host_player_id:
            room.phase = "playing"
            room._log("Game started -- stacks locked.")
    elif kind == "load_builtin":
        stack = room.find_stack(msg.get("stack_id", ""))
        if stack:
            n = room.load_cards_into(stack, builtin_deck(msg.get("jokers", True)))
            if msg.get("shuffle", True):
                room.shuffle_stack(stack)
            room._log(f"{player['name']} loaded the built-in deck ({n} cards).")
    elif kind == "bring_deck":
        deck = db.get_deck(player["id"], int(msg.get("deck_id", 0)))
        stack = room.find_stack(msg.get("stack_id", ""))
        if deck and stack and (stack["owner"] == seat or stack["owner"] is None):
            defs = []
            for cid in deck["card_ids"]:
                c = db.get_library_card(player["id"], cid)
                if c:
                    defs.append({"name": c["name"], "text": c["text"],
                                 "primary": c["primary_number"], "rank": "",
                                 "suit": "", "image": c["image_path"], "kind": "custom",
                                 "type_line": c.get("type_line", "")})
            room.load_cards_into(stack, defs)
            room.shuffle_stack(stack)
            room._log(f"{player['name']} brought deck '{deck['name']}' ({len(defs)} cards).")
    elif kind == "draw":
        stack = room.find_stack(msg.get("stack_id", ""))
        if stack:
            room.draw(seat, stack, int(msg.get("count", 1)))
    elif kind == "shuffle":
        stack = room.find_stack(msg.get("stack_id", ""))
        if stack:
            room.shuffle_stack(stack)
            room._log(f"{player['name']} shuffled {stack['name']}.")
    elif kind == "play_card":
        stack = room.find_stack(msg["to_stack"]) if msg.get("to_stack") else None
        room.play_from_hand(seat, msg.get("uid", ""), msg.get("face_up", True),
                            float(msg.get("x", 50)), float(msg.get("y", 50)), stack)
    elif kind == "take_card":
        room.take_table_card(seat, msg.get("uid", ""))
    elif kind == "flip_card":
        room.flip_table_card(msg.get("uid", ""))
    elif kind == "move_card":
        room.move_table_card(msg.get("uid", ""), float(msg.get("x", 50)), float(msg.get("y", 50)))
    elif kind == "card_to_stack":
        stack = room.find_stack(msg.get("stack_id", ""))
        if stack:
            room.table_card_to_stack(msg.get("uid", ""), stack)
    elif kind == "pass_turn":
        room.turn_seat = (seat + 1) % 4 if msg.get("next") is None else int(msg["next"]) % 4
        room._log(f"Turn passed to seat {room.turn_seat + 1}.")
    elif kind == "spawn_die":
        sides = int(msg.get("sides", 6))
        if 2 <= sides <= 1000:
            room.spawn_die(sides, float(msg.get("x", 50)), float(msg.get("y", 45)))
    elif kind == "roll_die":
        die = room.roll_die(msg.get("die_id", ""))
        if die:
            face = ("HEADS" if die["value"] == 1 else "TAILS") if die["label"] == "coin" else str(die["value"])
            room._log(f"{player['name']} rolled {die['label']}: {face}")
    elif kind == "move_die":
        for d in room.dice:
            if d["id"] == msg.get("die_id"):
                d["x"], d["y"] = float(msg.get("x", d["x"])), float(msg.get("y", d["y"]))
                d["on_card"] = msg.get("on_card", d["on_card"])
    elif kind == "park_die":
        for d in room.dice:
            if d["id"] == msg.get("die_id"):
                d["on_card"] = msg.get("uid")  # die parked on a card = counter
    elif kind == "searching":
        # Activity flag only: opponents see "searching <stack>...", never
        # contents. stack_id null clears it (deck view closed).
        stack = room.find_stack(msg.get("stack_id", ""))
        if stack:
            room.searching[seat] = stack["name"]
            room._log(f"{player['name']} is searching {stack['name']}...")
        else:
            room.searching.pop(seat, None)
    elif kind == "search_query":
        return _search_reply(room, seat, msg)
    elif kind == "take_from_stack":
        stack = room.find_stack(msg.get("stack_id", ""))
        if stack and _can_search(stack, seat):
            if room.take_from_stack(seat, stack, msg.get("uid", "")):
                room._log(f"{player['name']} took a card from {stack['name']}.")
    elif kind == "recycle_rest":
        stack = room.find_stack(msg.get("stack_id", ""))
        if stack and _can_search(stack, seat):
            n = room.recycle_to_bottom(stack, msg.get("uids", []))
            if n:
                room._log(f"{player['name']} recycled {n} card(s) to the bottom of {stack['name']}.")


def _can_search(stack, seat):
    """Who may look through a stack: its owner, anyone for a shared
    (ownerless) stack, and anyone for an open/top stack (already public).
    A hidden stack belonging to another seat is refused."""
    return (stack["owner"] == seat or stack["owner"] is None
            or stack["visibility"] in ("open", "top"))


def _search_reply(room, seat, msg):
    """Direct reply, requester only: the cards of one stack with a
    keyword filter's matches flagged. Peek mode returns only the top N.
    Order is top-first, the way a player fans a deck."""
    stack = room.find_stack(msg.get("stack_id", ""))
    base = {"type": "search_result", "stack_id": msg.get("stack_id", ""),
            "mode": msg.get("mode", "search"), "groups": parse_filter(""),
            "cards": [], "denied": True}
    if not stack or not _can_search(stack, seat):
        return base
    groups = parse_filter(msg.get("filter") or "")
    cards = list(reversed(stack["cards"]))  # top of stack = end of list
    if msg.get("mode") == "peek":
        n = max(0, int(msg.get("top_n") or 0))
        cards = cards[:n]
    out = []
    for c in cards:
        d = dict(c["def"])
        out.append({
            "uid": c["uid"], "name": d.get("name", ""),
            "primary": d.get("primary", ""), "image": d.get("image", ""),
            "kind": d.get("kind", ""), "type_line": d.get("type_line", ""),
            "rank": d.get("rank", ""), "suit": d.get("suit", ""),
            "match": match_filter(groups, d),
        })
    base.update({"groups": groups, "cards": out, "denied": False})
    return base


@app.get("/uploads/{fname}")
def upload_file(fname: str):
    path = os.path.join(UPLOAD_DIR, os.path.basename(fname))
    if not os.path.exists(path):
        raise HTTPException(404, "no such upload")
    return FileResponse(path)


app.mount("/", StaticFiles(directory=os.path.join(BASE, "static"), html=True), name="static")
