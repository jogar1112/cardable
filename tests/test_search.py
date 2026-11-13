"""Cardable keyword-search tests (v0.2): the filter parser, SEARCH/PEEK
phrase shapes, the direct-reply deck view (privacy on the wire), the
'searching...' activity flag, take-from-stack, and recycle-to-bottom.

Run:  python tests/test_search.py   (deletes its data dir first.)
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data_search")
shutil.rmtree(DATA, ignore_errors=True)
os.environ["DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(HERE, ".."))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.phrases import match_filter, parse_filter  # noqa: E402

CHECKS = [0]


def ok(cond, label):
    CHECKS[0] += 1
    if not cond:
        raise AssertionError(f"check {CHECKS[0]} FAILED: {label}")
    print(f"  ok {CHECKS[0]:2d} - {label}")


client = TestClient(app)
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000000020001e221bc330000000049454e44ae426082")


def make_player(name):
    r = client.post("/api/players", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def hdr(p):
    return {"X-Player-Token": p["token"]}


class Seat:
    def __init__(self, code, player):
        self.ws = client.websocket_connect(f"/ws/table/{code}?token={player['token']}")
        self.cm = self.ws.__enter__()

    def send(self, obj):
        self.cm.send_json(obj)

    def recv_any(self):
        return self.cm.receive_json()

    def recv(self):
        msg = self.recv_any()
        assert msg.get("type") == "state", msg
        return msg

    def close(self):
        self.ws.__exit__(None, None, None)


def stack_by_role(state, role, owner="any"):
    for s in state["stacks"]:
        if s["role"] == role and (owner == "any" or s["owner"] == owner):
            return s
    return None


def matches(text):
    return client.post("/api/phrases/match", json={"text": text}).json()["matches"]


def main():
    with client:
        # ---------------- phrase shapes ----------------
        m = matches("Search your library for a basic land card, reveal it, "
                    "put it into your hand, then shuffle.")
        ok(len(m) == 1 and m[0]["action"] == "search", "MTG tutor -> one SEARCH link (tail owned, no double shuffle link)")
        ok(m[0]["groups"]["types"] == ["land"] and m[0]["groups"]["qualifiers"] == ["basic"],
           "tutor blank parsed: type land + qualifier basic")
        ok(m[0]["tail"] == "shuffle" and m[0]["count"] is None, "tutor tail = shuffle, no up-to cap")

        m = matches("Search your deck for up to 2 Basic Pokémon cards, reveal them, "
                    "and put them into your hand. Then, shuffle your deck.")
        s = [x for x in m if x["action"] == "search"]
        ok(len(s) == 1 and s[0]["count"] == 2, "Pokémon tutor -> SEARCH with up-to 2")
        ok("pokémon" in s[0]["groups"]["types"] and "basic" in s[0]["groups"]["qualifiers"],
           "Pokémon blank parsed: type pokémon + basic")

        m = matches("Search your library for a card, reveal it, put it into your hand, then shuffle.")
        ok(m and m[0]["action"] == "search" and all(not v for v in m[0]["groups"].values()),
           "open tutor (Demonic shape) -> SEARCH with an empty filter (everything lights)")

        m = matches("Search your library for a creature card with mana value 3 or less, "
                    "reveal it, put it into your hand, then shuffle.")
        ok(m[0]["groups"]["types"] == ["creature"] and
           m[0]["groups"]["numbers"] == [{"field": "mana_value", "op": "<=", "value": 3}],
           "typed tutor blank: creature + mana value <= 3")

        m = matches("Look at the top 4 cards of your Main Deck. You may reveal a gear "
                    "from among them and draw it. Then recycle the rest.")
        ok(len(m) == 1 and m[0]["action"] == "peek" and m[0]["count"] == 4,
           "Riftbound Ornn shape -> PEEK top 4, nothing else links")
        ok(m[0]["groups"]["types"] == ["gear"] and m[0]["tail"] == "recycle",
           "peek blank parsed: type gear, tail = recycle the rest")
        ok(not any(x["action"] == "search" for x in m), "Riftbound text NEVER yields a whole-deck SEARCH")

        m = matches("Look at the top 3 cards of your Main Deck. Put 1 into your hand and recycle the rest.")
        ok(m[0]["action"] == "peek" and m[0]["count"] == 3 and m[0]["tail"] == "recycle"
           and all(not v for v in m[0]["groups"].values()),
           "Stacked Deck shape -> PEEK top 3, empty filter, recycle tail")

        m = matches("Add 1 Infernoble Knight card from your Deck to your hand.")
        ok(m and m[0]["action"] == "search" and m[0]["count"] == 1
           and "infernoble" in m[0]["groups"]["traits"],
           "YGO add-from-deck shape -> SEARCH 1 with trait terms")

        # ---------------- filter matching (unit level) ----------------
        elf = {"name": "Elven Archer", "type_line": "Creature — Elf Archer",
               "text": "", "primary": "2 G"}
        ok(match_filter(parse_filter("Elf creature with mana value 3 or less"), elf),
           "match: elf creature, mana value 3 (2 G) <= 3")
        ok(not match_filter(parse_filter("Dragon creature"), elf),
           "no match: dragon filter on an elf")
        ok(not match_filter(parse_filter("creature with mana value 2 or less"), elf),
           "no match: mana value cap excludes")
        forest = {"name": "Forest", "type_line": "Basic Land — Forest", "text": "", "primary": ""}
        ok(match_filter(parse_filter("basic land"), forest), "match: basic land")
        ok(not match_filter(parse_filter("nonbasic land"), forest), "no match: nonbasic excludes basics")
        ok(match_filter(parse_filter(""), elf), "empty filter lights everything")
        ok(match_filter(parse_filter("some unknownword"), elf) is False
           and match_filter(parse_filter("archer"), elf),
           "unknown words fall back to substring (archer hits the type line)")

        # ---------------- room flow: TCG, two seats ----------------
        a = make_player("Alice")
        b = make_player("Bob")

        def upload(name, type_line, primary):
            r = client.post("/api/library/upload", headers=hdr(a),
                            files={"file": ("c.png", PNG, "image/png")})
            cid = r.json()["id"]
            r = client.put(f"/api/library/{cid}", headers=hdr(a), json={
                "name": name, "text": "", "primary": primary, "type_line": type_line})
            assert r.json()["type_line"] == type_line, r.text
            return cid

        ids = [upload("Forest", "Basic Land — Forest", ""),
               upload("Elf Ranger", "Creature — Elf Ranger", "1 G"),
               upload("Ancient Dragon", "Creature — Dragon", "5 R")]
        deck = client.post("/api/decks", headers=hdr(a),
                           json={"name": "Searchables", "card_ids": ids}).json()

        code = client.post("/api/rooms", headers=hdr(a), json={"profile_id": "tcg"}).json()["code"]
        sa = Seat(code, a); sta = sa.recv()
        sb = Seat(code, b); stb = sb.recv(); sta = sa.recv()
        lib = stack_by_role(sta, "deck", owner=0)
        sa.send({"type": "bring_deck", "deck_id": deck["id"], "stack_id": lib["id"]})
        sta = sa.recv(); stb = sb.recv()
        ok(stack_by_role(sta, "deck", owner=0)["count"] == 3, "3-card deck at the table")
        ok("Elf Ranger" not in json.dumps(stb), "B's payload has no hidden deck identities")

        # activity flag: opponents see searching, never contents
        sa.send({"type": "searching", "stack_id": lib["id"], "mode": "search"})
        sta = sa.recv(); stb = sb.recv()
        ok(stb["seats"][0]["searching"] == "Library", "B sees 'searching Library...' on A's seat")

        # the filtered deck view: direct reply to A only
        sa.send({"type": "search_query", "stack_id": lib["id"], "mode": "search",
                 "filter": "basic land"})
        rep = sa.recv_any()
        ok(rep["type"] == "search_result" and rep["denied"] is False, "A gets a search_result reply")
        by_name = {c["name"]: c for c in rep["cards"]}
        ok(len(rep["cards"]) == 3 and by_name["Forest"]["match"] is True
           and by_name["Elf Ranger"]["match"] is False
           and by_name["Ancient Dragon"]["match"] is False,
           "basic land filter lights only the Forest")
        sta = sa.recv()  # the broadcast that follows the reply
        stb = sb.recv()
        ok(stb["type"] == "state" and "Elf Ranger" not in json.dumps(stb),
           "B receives only state after A's query -- no reply, no identities")

        # take the lit card
        sa.send({"type": "take_from_stack", "stack_id": lib["id"], "uid": by_name["Forest"]["uid"]})
        sta = sa.recv(); stb = sb.recv()
        ok(any(c["name"] == "Forest" for c in sta["hand"])
           and stack_by_role(sta, "deck", owner=0)["count"] == 2,
           "take_from_stack moves the picked card to A's hand")

        # creature filter lights both remaining cards
        sa.send({"type": "search_query", "stack_id": lib["id"], "mode": "search",
                 "filter": "creature"})
        rep = sa.recv_any(); sta = sa.recv(); stb = sb.recv()
        ok(len(rep["cards"]) == 2 and all(c["match"] for c in rep["cards"]),
           "creature filter lights both remaining cards")

        # peek the top 1, recycle it, confirm it lands on the bottom
        sa.send({"type": "search_query", "stack_id": lib["id"], "mode": "peek",
                 "top_n": 1, "filter": ""})
        rep = sa.recv_any(); sta = sa.recv(); stb = sb.recv()
        ok(len(rep["cards"]) == 1, "peek returns only the top card")
        top_uid = rep["cards"][0]["uid"]
        sa.send({"type": "recycle_rest", "stack_id": lib["id"], "uids": [top_uid]})
        sta = sa.recv(); stb = sb.recv()
        sa.send({"type": "search_query", "stack_id": lib["id"], "mode": "search", "filter": ""})
        rep = sa.recv_any(); sta = sa.recv(); stb = sb.recv()
        ok(rep["cards"][-1]["uid"] == top_uid and rep["cards"][0]["uid"] != top_uid,
           "recycled card is now on the bottom of the deck")

        # privacy: B cannot search A's hidden Library
        sb.send({"type": "search_query", "stack_id": lib["id"], "mode": "search", "filter": ""})
        repb = sb.recv_any()
        ok(repb["type"] == "search_result" and repb["denied"] is True and repb["cards"] == [],
           "B searching A's hidden Library is refused, empty-handed")
        stb = sb.recv(); sta = sa.recv()

        # closing the view clears the activity flag
        sa.send({"type": "searching", "stack_id": None})
        sta = sa.recv(); stb = sb.recv()
        ok(stb["seats"][0]["searching"] is None, "closing the deck view clears 'searching' for B")
        sa.close(); sb.close()

    print(f"\nALL {CHECKS[0]} CHECKS PASSED")


if __name__ == "__main__":
    main()
