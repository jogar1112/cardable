"""Server-as-dealer room state.

The server holds every card. A client's view is built per-viewer and NEVER
contains: another player's hand, the contents of a hidden stack, or the
identity of a face-down card the viewer doesn't own. Sandbox in actions,
strict in information.
"""
import copy
import random
import secrets

SUITS = [("S", "♠"), ("H", "♥"), ("D", "♦"), ("C", "♣")]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
STANDARD_DICE = [4, 6, 8, 10, 100, 12, 20]


def builtin_deck(include_jokers=True):
    cards = []
    for skey, glyph in SUITS:
        for rank in RANKS:
            name = f"{rank} of {glyph}"
            cards.append({
                "name": name, "text": "", "primary": f"{rank}{glyph}",
                "rank": rank, "suit": glyph, "image": "", "kind": "playing",
            })
    if include_jokers:
        for color in ("Red", "Black"):
            cards.append({
                "name": f"{color} Joker", "text": "", "primary": "JOKER",
                "rank": "JOKER", "suit": "★", "image": "", "kind": "playing",
            })
    return cards


class Room:
    def __init__(self, code, profile, host_player_id):
        self.code = code
        self.profile = copy.deepcopy(profile)
        self.phase = "setup"  # setup -> playing (stack positions lock)
        self.seats = [None] * 4  # {player_id, name, connected}
        self.hands = {i: [] for i in range(4)}
        self.stacks = []
        self.table_cards = []
        self.dice = []
        self.turn_seat = 0
        self.log = []
        self.searching = {}  # seat -> name of the stack being searched/peeked
        self._uid = 0
        for spec in self.profile.get("shared_stacks", []):
            self._add_stack(None, spec)
        self.host_player_id = host_player_id

    # -- internals ------------------------------------------------------
    def _next_uid(self):
        self._uid += 1
        return f"c{self._uid}-{secrets.token_hex(3)}"

    def _add_stack(self, owner, spec):
        stack = {
            "id": f"s{len(self.stacks)}-{secrets.token_hex(2)}",
            "owner": owner, "name": spec["name"], "role": spec["role"],
            "visibility": spec.get("visibility", "open"),
            "x": spec.get("x", 50), "y": spec.get("y", 50), "cards": [],
        }
        self.stacks.append(stack)
        return stack

    def seat_stacks_for(self, seat):
        made = []
        for spec in self.profile.get("seat_stacks", []):
            made.append(self._add_stack(seat, spec))
        return made

    def find_stack(self, stack_id):
        for s in self.stacks:
            if s["id"] == stack_id:
                return s
        return None

    def seat_of(self, player_id):
        for i, s in enumerate(self.seats):
            if s and s["player_id"] == player_id:
                return i
        return None

    def join(self, player):
        seat = self.seat_of(player["id"])
        if seat is not None:
            self.seats[seat]["connected"] = True
            return seat
        for i, s in enumerate(self.seats):
            if s is None:
                self.seats[i] = {"player_id": player["id"], "name": player["name"],
                                 "connected": True}
                self.seat_stacks_for(i)
                self._log(f"{player['name']} took seat {i + 1}")
                return i
        return None

    def disconnect(self, player_id):
        seat = self.seat_of(player_id)
        if seat is not None:
            self.seats[seat]["connected"] = False  # seat + hand are held
            self.searching.pop(seat, None)

    def _log(self, msg):
        self.log.append(msg)
        self.log = self.log[-50:]

    def _wrap(self, card_def):
        return {"uid": self._next_uid(), "def": card_def}

    # -- actions --------------------------------------------------------
    def load_cards_into(self, stack, card_defs):
        for d in card_defs:
            stack["cards"].append(self._wrap(d))
        return len(card_defs)

    def shuffle_stack(self, stack):
        random.shuffle(stack["cards"])

    def draw(self, seat, stack, count):
        drawn = []
        for _ in range(min(count, len(stack["cards"]))):
            card = stack["cards"].pop()
            self.hands[seat].append(card)
            drawn.append(card)
        return drawn

    def take_from_stack(self, seat, stack, uid):
        """Search flow: move ONE named card out of a stack into the
        searcher's hand. The pick is the player's; the table owns legality."""
        for i, c in enumerate(stack["cards"]):
            if c["uid"] == uid:
                self.hands[seat].append(stack["cards"].pop(i))
                return True
        return False

    def recycle_to_bottom(self, stack, uids):
        """Peek tail ('recycle the rest'): move the named cards to the
        bottom of the stack, preserving their relative order. The top
        of a stack is the END of its card list, so bottom = front."""
        wanted = set(uids)
        moved = [c for c in stack["cards"] if c["uid"] in wanted]
        kept = [c for c in stack["cards"] if c["uid"] not in wanted]
        stack["cards"] = moved + kept
        return len(moved)

    def play_from_hand(self, seat, uid, face_up, x=50, y=50, to_stack=None):
        hand = self.hands[seat]
        for i, c in enumerate(hand):
            if c["uid"] == uid:
                card = hand.pop(i)
                if to_stack is not None:
                    to_stack["cards"].append(card)
                else:
                    self.table_cards.append({
                        "card": card, "x": x, "y": y,
                        "face_up": bool(face_up), "owner_seat": seat,
                        "tapped": False,
                    })
                return True
        return False

    def take_table_card(self, seat, uid):
        for i, tc in enumerate(self.table_cards):
            if tc["card"]["uid"] == uid:
                self.table_cards.pop(i)
                self.hands[seat].append(tc["card"])
                return True
        return False

    def flip_table_card(self, uid):
        for tc in self.table_cards:
            if tc["card"]["uid"] == uid:
                tc["face_up"] = not tc["face_up"]
                return True
        return False

    def move_table_card(self, uid, x, y):
        for tc in self.table_cards:
            if tc["card"]["uid"] == uid:
                tc["x"], tc["y"] = x, y
                return True
        return False

    def table_card_to_stack(self, uid, stack):
        for i, tc in enumerate(self.table_cards):
            if tc["card"]["uid"] == uid:
                self.table_cards.pop(i)
                stack["cards"].append(tc["card"])
                return True
        return False

    def spawn_die(self, sides, x=50, y=45):
        die = {"id": f"d{len(self.dice)}-{secrets.token_hex(2)}",
               "sides": int(sides), "value": int(sides), "x": x, "y": y,
               "on_card": None, "label": "coin" if int(sides) == 2 else f"d{int(sides)}"}
        self.dice.append(die)
        return die

    def roll_die(self, die_id):
        for d in self.dice:
            if d["id"] == die_id:
                d["value"] = random.randint(1, d["sides"])  # server-generated
                return d
        return None

    # -- per-viewer serialization (THE privacy boundary) -----------------
    @staticmethod
    def _public_def(card):
        return dict(card["def"])

    def view(self, viewer_seat):
        seats = []
        for i, s in enumerate(self.seats):
            seats.append({
                "seat": i, "name": s["name"] if s else None,
                "connected": bool(s and s["connected"]),
                "hand_count": len(self.hands[i]),
                "is_you": i == viewer_seat,
                "searching": self.searching.get(i),
            })
        stacks = []
        for st in self.stacks:
            entry = {
                "id": st["id"], "owner": st["owner"], "name": st["name"],
                "role": st["role"], "visibility": st["visibility"],
                "x": st["x"], "y": st["y"], "count": len(st["cards"]),
                "cards": [], "top": None,
            }
            mine = st["owner"] is not None and st["owner"] == viewer_seat
            if st["visibility"] == "open":
                entry["cards"] = [{"uid": c["uid"], **self._public_def(c)} for c in st["cards"]]
            elif st["visibility"] == "top" and st["cards"]:
                top = st["cards"][-1]
                entry["top"] = {"uid": top["uid"], **self._public_def(top)}
            elif st["visibility"] == "hidden" and mine:
                # The owner may search/see their own deck-role stack.
                entry["cards"] = [{"uid": c["uid"], **self._public_def(c)} for c in st["cards"]]
            stacks.append(entry)
        table = []
        for tc in self.table_cards:
            base = {"uid": tc["card"]["uid"], "x": tc["x"], "y": tc["y"],
                    "face_up": tc["face_up"], "owner_seat": tc["owner_seat"],
                    "tapped": tc.get("tapped", False)}
            if tc["face_up"] or tc["owner_seat"] == viewer_seat:
                base.update(self._public_def(tc["card"]))
                base["known_to_you"] = True
            else:
                base["known_to_you"] = False  # back only -- no identity leaks
            table.append(base)
        hand = []
        if viewer_seat is not None:
            hand = [{"uid": c["uid"], **self._public_def(c)} for c in self.hands[viewer_seat]]
        return {
            "type": "state", "code": self.code, "phase": self.phase,
            "profile_name": self.profile.get("name", ""),
            "glance": self.profile.get("glance", "primary"),
            "your_seat": viewer_seat, "turn_seat": self.turn_seat,
            "seats": seats, "stacks": stacks, "table_cards": table,
            "dice": [dict(d) for d in self.dice],
            "hand": hand, "log": list(self.log),
        }
