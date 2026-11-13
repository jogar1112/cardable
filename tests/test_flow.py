"""Cardable flow tests: two clients, privacy on the wire, dice, setup lock,
reconnect, library/deck ownership, phrase matching, settings.

Run:  python tests/test_flow.py   (deletes its data dir first -- sqlite
residue from a previous run causes false failures.)
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data_flow")
shutil.rmtree(DATA, ignore_errors=True)
os.environ["DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(HERE, ".."))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

CHECKS = [0]


def ok(cond, label):
    CHECKS[0] += 1
    if not cond:
        raise AssertionError(f"check {CHECKS[0]} FAILED: {label}")
    print(f"  ok {CHECKS[0]:2d} - {label}")


client = TestClient(app)


def make_player(name):
    r = client.post("/api/players", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def hdr(p):
    return {"X-Player-Token": p["token"]}


class Seat:
    """A websocket client with a one-message-at-a-time sync helper."""

    def __init__(self, code, player):
        self.ws = client.websocket_connect(f"/ws/table/{code}?token={player['token']}")
        self.cm = self.ws.__enter__()

    def send(self, obj):
        self.cm.send_json(obj)

    def recv(self):
        msg = self.cm.receive_json()
        assert msg.get("type") == "state", msg
        return msg

    def close(self):
        self.ws.__exit__(None, None, None)


def stack_by_role(state, role, owner="any"):
    for s in state["stacks"]:
        if s["role"] == role and (owner == "any" or s["owner"] == owner):
            return s
    return None


def main():
    with client:
        a = make_player("Alice")
        b = make_player("Bob")
        ok(a["token"] != b["token"], "players get distinct tokens")

        # ---- phrase matching (unit level, via API)
        m = client.post("/api/phrases/match", json={
            "text": "Draw two cards, then shuffle your library. Flip a coin. Roll a d20. Draw 3 cards."}).json()["matches"]
        acts = [(x["action"], x.get("count"), x.get("sides")) for x in m]
        ok(("draw", 2, None) in acts, "phrase: 'Draw two cards' -> draw 2")
        ok(("shuffle", None, None) in acts, "phrase: shuffle matched")
        ok(("coin", None, None) in acts, "phrase: flip a coin matched")
        ok(("roll", None, 20) in acts, "phrase: roll a d20 -> sides 20")
        ok(("draw", 3, None) in acts, "phrase: 'Draw 3 cards' -> draw 3")

        # ---- settings roundtrip
        s = client.put("/api/settings", headers=hdr(a), json={"link_mode": "confirm"}).json()
        ok(s["link_mode"] == "confirm", "settings: link_mode saved per player")
        s = client.get("/api/settings", headers=hdr(b)).json()
        ok(s["link_mode"] == "instant", "settings: other player unaffected (default instant)")

        # ---- room 1: standard 52, two clients play the built-in deck
        code = client.post("/api/rooms", headers=hdr(a), json={"profile_id": "standard52"}).json()["code"]
        sa = Seat(code, a)
        sta = sa.recv()
        ok(sta["your_seat"] == 0 and sta["phase"] == "setup", "host seated at seat 0 in setup")
        sb = Seat(code, b)
        stb = sb.recv(); sta = sa.recv()
        ok(stb["your_seat"] == 1, "second client seated at seat 1")

        deck_stack = stack_by_role(sta, "deck", owner=None)
        sa.send({"type": "load_builtin", "stack_id": deck_stack["id"], "jokers": True})
        sta = sa.recv(); stb = sb.recv()
        ok(stack_by_role(sta, "deck", owner=None)["count"] == 54, "built-in deck loaded: 54 cards")
        ok("of ♠" not in json.dumps(stb) and "Joker" not in json.dumps(stb),
           "B's wire payload has NO hidden deck identities")

        sa.send({"type": "draw", "stack_id": deck_stack["id"], "count": 5})
        sta = sa.recv(); stb = sb.recv()
        ok(len(sta["hand"]) == 5, "A drew 5 cards")
        a_hand_names = {c["name"] for c in sta["hand"]}
        ok(all(c["name"] not in json.dumps(stb) for c in sta["hand"]),
           "B's payload NEVER contains A's hand identities")
        ok(stb["hand"] == [] and stb["seats"][0]["hand_count"] == 5,
           "B sees A's hand as a count of backs only")

        # face-down table card: identity must not leak
        victim = sta["hand"][0]
        sa.send({"type": "play_card", "uid": victim["uid"], "face_up": False, "x": 40, "y": 40})
        sta = sa.recv(); stb = sb.recv()
        btc = [t for t in stb["table_cards"] if t["uid"] == victim["uid"]][0]
        ok(btc["known_to_you"] is False and "name" not in btc, "face-down table card is a back to B")
        ok(victim["name"] not in json.dumps(stb), "face-down identity absent from B's whole payload")
        atc = [t for t in sta["table_cards"] if t["uid"] == victim["uid"]][0]
        ok(atc.get("name") == victim["name"], "the owner still knows their own face-down card")

        sa.send({"type": "flip_card", "uid": victim["uid"]})
        sta = sa.recv(); stb = sb.recv()
        btc = [t for t in stb["table_cards"] if t["uid"] == victim["uid"]][0]
        ok(btc.get("name") == victim["name"], "after flip, B sees the card face")

        # ---- dice: server-generated, identical for every client
        sa.send({"type": "spawn_die", "sides": 20})
        sta = sa.recv(); stb = sb.recv()
        die = sta["dice"][0]
        ok(die["sides"] == 20, "d20 spawned on the table")
        sa.send({"type": "roll_die", "die_id": die["id"]})
        sta = sa.recv(); stb = sb.recv()
        va = [d for d in sta["dice"] if d["id"] == die["id"]][0]["value"]
        vb = [d for d in stb["dice"] if d["id"] == die["id"]][0]["value"]
        ok(va == vb and 1 <= va <= 20, f"dice roll identical for all clients (={va})")
        sa.send({"type": "spawn_die", "sides": 7})
        sta = sa.recv(); stb = sb.recv()
        ok(any(d["sides"] == 7 for d in sta["dice"]), "custom-side die (d7) spawnable")

        # park a die on the face-up card (die-as-counter)
        sa.send({"type": "park_die", "die_id": die["id"], "uid": victim["uid"]})
        sta = sa.recv(); stb = sb.recv()
        ok([d for d in stb["dice"] if d["id"] == die["id"]][0]["on_card"] == victim["uid"],
           "die parked on a card as a counter, visible to all")

        # ---- turn indicator passes
        sa.send({"type": "pass_turn"})
        sta = sa.recv(); stb = sb.recv()
        ok(stb["turn_seat"] == 1, "turn indicator passed to seat 1")

        # ---- reconnect restores seat + hand
        sa.close()
        stb = sb.recv()  # disconnect broadcast
        ok(stb["seats"][0]["connected"] is False, "disconnect marks seat away, seat held")
        sa = Seat(code, a)
        sta = sa.recv(); stb = sb.recv()
        ok(sta["your_seat"] == 0 and len(sta["hand"]) == 4, "reconnect restores seat and hand")
        sa.close(); sb.close()

        # ---- room 2: TCG profile; setup arrange, then LOCK at start
        code2 = client.post("/api/rooms", headers=hdr(a), json={"profile_id": "tcg"}).json()["code"]
        ta = Seat(code2, a); sta = ta.recv()
        tb = Seat(code2, b); stb = tb.recv(); sta = ta.recv()
        lib = stack_by_role(sta, "deck", owner=0)
        ok(lib is not None, "TCG profile gives each seat a Library stack")
        ta.send({"type": "move_stack", "stack_id": lib["id"], "x": 11, "y": 12})
        sta = ta.recv(); stb = tb.recv()
        moved = stack_by_role(sta, "deck", owner=0)
        ok(moved["x"] == 11 and moved["y"] == 12, "setup phase: stack arrangement moves")
        ta.send({"type": "start_game"})
        sta = ta.recv(); stb = tb.recv()
        ok(sta["phase"] == "playing", "host starts the game")
        ta.send({"type": "move_stack", "stack_id": lib["id"], "x": 90, "y": 90})
        sta = ta.recv(); stb = tb.recv()
        still = stack_by_role(sta, "deck", owner=0)
        ok(still["x"] == 11 and still["y"] == 12, "setup-lock holds after game start")
        ok(any("locked" in line for line in sta["log"]), "lock attempt is logged, not silently dropped")

        # ---- library: upload is playable immediately; ownership is strict
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6360000000020001e221bc330000000049454e44ae426082")
        r = client.post("/api/library/upload", headers=hdr(a),
                        files={"file": ("pyropup.png", png, "image/png")})
        ok(r.status_code == 200, "image upload accepted")
        card = r.json()
        ok(card["image_path"].startswith("/uploads/") and card["ocr"]["engine"] == "stub",
           "uploaded card exists instantly; OCR honestly stubbed")
        r = client.put(f"/api/library/{card['id']}", headers=hdr(a), json={
            "name": "Pyropup", "text": "Draw two cards. Flip a coin.", "primary": "70"})
        ok(r.json()["name"] == "Pyropup", "confirm/correct step edits name/text/number")
        r = client.post("/api/decks", headers=hdr(b), json={"name": "Thief", "card_ids": [card["id"]]})
        ok(r.status_code == 400, "opponent CANNOT build a deck from your library")
        r = client.post("/api/decks", headers=hdr(a), json={"name": "Mine", "card_ids": [card["id"]]})
        deck = r.json()
        ok(deck["card_ids"] == [card["id"]], "owner builds a deck from their library")

        # bring the custom deck to the TCG table and draw it
        ta.send({"type": "bring_deck", "deck_id": deck["id"], "stack_id": lib["id"]})
        sta = ta.recv(); stb = tb.recv()
        ok(stack_by_role(sta, "deck", owner=0)["count"] == 1, "custom deck brought to table")
        ok("Pyropup" not in json.dumps(stb), "B never sees A's un-drawn custom deck contents")
        ta.send({"type": "draw", "stack_id": lib["id"], "count": 1})
        sta = ta.recv(); stb = tb.recv()
        ok(sta["hand"][0]["name"] == "Pyropup" and sta["hand"][0]["image"].startswith("/uploads/"),
           "custom card drawn with its uploaded image as the face")
        ta.close(); tb.close()

        # ---- saved game profile roundtrip
        prof = {"glance": "primary",
                "shared_stacks": [{"name": "Pot", "role": "play", "visibility": "open", "x": 50, "y": 40}],
                "seat_stacks": [{"name": "My Deck", "role": "deck", "visibility": "hidden", "x": 80, "y": 70}]}
        r = client.post("/api/my-profiles", headers=hdr(a), json={"name": "My Uno", "data": prof})
        ok(r.status_code == 200, "setup saved as a personal game")
        mine = client.get("/api/my-profiles", headers=hdr(a)).json()
        ok(any(p["name"] == "My Uno" for p in mine), "saved game listed for its owner")
        mine_b = client.get("/api/my-profiles", headers=hdr(b)).json()
        ok(not any(p["name"] == "My Uno" for p in mine_b), "saved games are personal too")
        code3 = client.post("/api/rooms", headers=hdr(a),
                            json={"profile_id": str(r.json()["id"])}).json()["code"]
        s3 = Seat(code3, a); st3 = s3.recv()
        ok(any(s["name"] == "Pot" for s in st3["stacks"]), "a table can be created from a saved game")
        s3.close()

    print(f"\nALL {CHECKS[0]} CHECKS PASSED")


if __name__ == "__main__":
    main()
