"""Key-phrase action links: data-driven matching over a card's CONFIRMED text.

Universal core (from 02-universal-functions-library.md):
  draw N / shuffle / flip a coin / roll a die (or roll a dN), plus the
  keyword-search family: SEARCH DECK phrases carry a FILTER blank
  ("search your library for a [filter] card ... then shuffle") and the
  top-N PEEK family ("look at the top N cards ... reveal a [filter]
  from among them ... recycle the rest" -- the Riftbound shape; the
  Riftbound pack deliberately has NO whole-deck search phrase).

The filter blank is parsed into keyword groups (types / traits /
colors / names / number comparisons / qualifiers). Matching is AND
across groups, OR inside a group; a word the vocabularies don't know
falls back to a name/text substring, never a silent drop. The filter
is a flashlight, not a gate: the deck view shows non-matches dimmed,
and an empty filter lights everything (Demonic Tutor).

Links only OFFER actions; the player runs them (sandbox).
"""
import re

NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUM = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|a|an)"

# ---------------------------------------------------------------- filter vocab
TYPES = {
    "creature", "artifact", "enchantment", "instant", "sorcery", "land",
    "planeswalker", "battle", "unit", "gear", "spell", "trap", "monster",
    "trainer", "item", "supporter", "stadium", "energy", "rune", "vehicle",
    "saga", "aura", "equipment", "character", "event", "stage", "leader",
    "option", "tamer", "action", "song", "pokemon", "pokémon",
}
TRAITS = {
    "elf", "goblin", "dragon", "zombie", "vampire", "spirit", "soldier",
    "wizard", "warrior", "angel", "demon", "beast", "cat", "dog", "bird",
    "fish", "insect", "plant", "elemental", "construct", "golem", "human",
    "dwarf", "orc", "troll", "giant", "merfolk", "faerie", "knight",
    "cleric", "rogue", "shaman", "druid", "monk", "pirate", "dinosaur",
    "unicorn", "hydra", "sphinx", "phoenix", "skeleton", "werewolf",
    "mech", "slime", "devil", "god", "avatar", "assassin", "scout",
    "archer", "samurai", "ninja", "minion", "illusion", "horror",
    "serpent", "spider", "rat", "bat", "wolf", "bear", "boar", "horse",
    "ox", "ape", "crab", "octopus", "whale", "shark", "snake", "frog",
    "lizard", "turtle", "mouse", "rabbit", "fox", "deer", "elk",
}
COLORS = {
    "white", "blue", "black", "red", "green", "colorless",
    "fury", "calm", "body", "mind", "chaos", "order",          # Riftbound domains
    "fire", "water", "lightning", "grass", "fighting", "psychic",
    "darkness", "metal", "fairy", "electric", "ice", "ground",
    "rock", "poison", "flying", "bug", "ghost", "steel", "dark",
}
QUALIFIERS = {"basic", "nonbasic", "legendary", "nonlegendary", "another"}
STOPWORDS = {
    "a", "an", "the", "card", "cards", "from", "your", "deck", "library",
    "main", "with", "of", "and", "or", "among", "them", "into", "hand",
    "reveal", "reveals", "revealed", "put", "may", "you", "top", "look",
    "search", "for", "up", "to", "that", "this", "those", "these", "is",
    "are", "on", "in", "it", "its", "any", "all", "other", "own",
} | set(NUMBER_WORDS)

_NUMCON = re.compile(
    r"(mana\s+value|converted\s+mana\s+cost|cmc|total\s+cost|cost|hp|"
    r"hit\s+points|power|toughness)\s+(?:of\s+)?(\d+)\s+or\s+"
    r"(less|fewer|more|greater)", re.I)
_COSTCON = re.compile(r"costs?\s+(\d+)\s+or\s+(less|fewer|more|greater)", re.I)
_FIELD_MAP = {
    "mana value": "mana_value", "converted mana cost": "mana_value",
    "cmc": "mana_value", "total cost": "cost", "cost": "cost",
    "hp": "hp", "hit points": "hp", "power": "power", "toughness": "toughness",
}


def _norm(tok):
    """Singular form for vocab lookup: 'creatures' -> 'creature'."""
    if tok.endswith("ies") and len(tok) > 3:
        cand = tok[:-3] + "y"
        if cand in TYPES or cand in TRAITS or cand in COLORS:
            return cand
    for suf in ("es", "s"):
        if tok.endswith(suf) and len(tok) > len(suf):
            cand = tok[:-len(suf)]
            if cand in TYPES or cand in TRAITS or cand in COLORS or cand in QUALIFIERS:
                return cand
    return tok


def parse_filter(blank):
    """Parse a search blank into keyword groups. Unknown words fall back
    to name substrings -- nothing is silently dropped."""
    groups = {"types": [], "traits": [], "colors": [], "names": [],
              "numbers": [], "qualifiers": [], "not_types": []}
    if not blank:
        return groups
    raw = blank.strip()
    low = raw.lower()

    def _numcon_sub(m):
        f = _FIELD_MAP[re.sub(r"\s+", " ", m.group(1).lower())]
        op = "<=" if m.group(3).lower() in ("less", "fewer") else ">="
        groups["numbers"].append({"field": f, "op": op, "value": int(m.group(2))})
        return " "

    def _costcon_sub(m):
        op = "<=" if m.group(2).lower() in ("less", "fewer") else ">="
        groups["numbers"].append({"field": "cost", "op": op, "value": int(m.group(1))})
        return " "

    low = _NUMCON.sub(_numcon_sub, low)
    low = _COSTCON.sub(_costcon_sub, low)
    caps = {w.lower() for w in re.findall(r"[A-Z][a-zA-ZÀ-ÿ]+", raw)}

    def add(key, val):
        if val not in groups[key]:
            groups[key].append(val)

    for tok in re.findall(r"[a-zà-ÿ0-9']+", low):
        if not tok or tok in STOPWORDS or tok.isdigit():
            continue
        base = _norm(tok)
        neg = tok[3:] if tok.startswith("non") and len(tok) > 3 else None
        negbase = _norm(neg.lstrip("-")) if neg else None
        if base in QUALIFIERS:
            add("qualifiers", base)
        elif negbase in TYPES:
            add("not_types", negbase)
        elif neg and negbase in QUALIFIERS:
            add("qualifiers", "non" + negbase)
        elif base in TYPES:
            add("types", base)
        elif base in COLORS:
            add("colors", base)
        elif base in TRAITS or tok in caps:
            add("traits", tok)
        else:
            add("names", tok)
    return groups


def _mana_value(cost):
    """Best-effort mana value from a cost string: '2 G', '{2}{G}', '3'."""
    if not cost:
        return None
    total, seen = 0, False
    for tok in str(cost).replace("{", " ").replace("}", " ").split():
        if tok.isdigit():
            total += int(tok)
            seen = True
        elif re.fullmatch(r"[A-Za-z]", tok):
            if tok.upper() != "X":
                total += 1
            seen = True
        else:
            return None
    return total if seen else None


def _card_number(card, field):
    """The numeric value a constraint compares against, or None when the
    card carries no evaluable number (the constraint then doesn't
    exclude -- never a dead end)."""
    if isinstance(card.get(field), (int, float)):
        return card[field]
    primary = str(card.get("primary") or "")
    if field in ("mana_value", "cost"):
        return _mana_value(primary)
    if field == "hp":
        m = re.fullmatch(r"\s*(\d+)\s*(?:hp)?\s*", primary, re.I)
        return int(m.group(1)) if m else None
    return None


def _word_in(word, src):
    return re.search(r"\b" + re.escape(word) + r"s?\b", src) is not None


def match_filter(groups, card):
    """True when the card lights up under the filter. AND across groups,
    OR inside a group; an empty filter lights everything."""
    name = (card.get("name") or "").lower()
    tl = (card.get("type_line") or "").lower()
    hay = " ".join([name, tl, (card.get("text") or "").lower()])
    type_src = tl if tl else hay
    if groups.get("types") and not any(_word_in(t, type_src) for t in groups["types"]):
        return False
    if groups.get("not_types") and any(_word_in(t, type_src) for t in groups["not_types"]):
        return False
    if groups.get("traits") and not any(t in hay for t in groups["traits"]):
        return False
    if groups.get("colors") and not any(_word_in(c, hay) for c in groups["colors"]):
        return False
    if groups.get("names") and not any(n in name or n in hay for n in groups["names"]):
        return False
    for q in groups.get("qualifiers", []):
        if q == "basic" and "basic" not in type_src:
            return False
        if q == "nonbasic" and "basic" in type_src:
            return False
        if q == "legendary" and "legendary" not in hay:
            return False
        if q == "nonlegendary" and "legendary" in hay:
            return False
    for nc in groups.get("numbers", []):
        val = _card_number(card, nc["field"])
        if val is None:
            continue
        if nc["op"] == "<=" and val > nc["value"]:
            return False
        if nc["op"] == ">=" and val < nc["value"]:
            return False
    return True


# ---------------------------------------------------------------- phrase patterns
PATTERNS = [
    ("draw", re.compile(r"\bdraw\s+" + _NUM + r"\s+cards?\b", re.I)),
    ("draw", re.compile(r"\bdraw\s+" + _NUM + r"\b(?!\s*(?:damage|power))", re.I)),
    ("shuffle", re.compile(r"\bshuffle\b(?:\s+your\s+(?:deck|library))?", re.I)),
    ("coin", re.compile(r"\bflip\s+a\s+coin\b", re.I)),
    ("roll", re.compile(r"\broll\s+a\s+d(\d+)\b", re.I)),
    ("roll", re.compile(r"\broll\s+a\s+die\b", re.I)),
]

_SEARCH_RE = re.compile(
    r"\bsearch\s+your\s+(?:main\s+deck|library|deck)\s+for\s+"
    r"(?:up\s+to\s+" + _NUM + r"\s+)?"
    r"(?:(?:a|an|one)\s+)?"
    r"(?P<filter>.*?)"
    r"(?=,|\.|;|\bthen\s+shuffle\b|\band\s+put\b|\bfrom\s+your\b|$)",
    re.I | re.S)
_ADD_RE = re.compile(
    r"\badd\s+" + _NUM + r"\s+(?P<filter>.+?)\s+from\s+your\s+deck\s+to\s+your\s+hand\b",
    re.I | re.S)
_PEEK_RE = re.compile(
    r"\b(?:look\s+at|reveal)\s+the\s+top\s+(?:(" + _NUM + r")\s+)?cards?\s+of\s+your\s+"
    r"(?:main\s+deck|library|deck)\b", re.I)
_PEEK_FILTER_RE = re.compile(
    r"reveal\s+(?:a|an|one)\s+(.+?)\s+from\s+among\s+them", re.I | re.S)


def _num(tok):
    tok = tok.lower()
    return int(tok) if tok.isdigit() else NUMBER_WORDS.get(tok, 1)


def _clean_filter(text):
    text = (text or "").strip().strip(",").strip()
    text = re.sub(r"\s+cards?$", "", text, flags=re.I)
    text = text.strip()
    return "" if text.lower() in ("card", "cards") else text


def match_phrases(text):
    """Return [{start, end, phrase, action, ...}] sorted by start,
    non-overlapping. SEARCH/PEEK matches are claimed first: they own
    their tails, so a search's 'then shuffle' never double-links."""
    if not text:
        return []
    found = []
    taken = []

    def claim(s, e, item):
        if any(s < te and e > ts for ts, te in taken):
            return False
        taken.append((s, e))
        found.append(item)
        return True

    for m in _SEARCH_RE.finditer(text):
        filt = _clean_filter(m.group("filter"))
        # A same-sentence ", then shuffle" is this search's tail: the match
        # owns it (no separate shuffle link) and the deck view offers it
        # after the pick. A shuffle in a LATER sentence stays its own link.
        end = m.end()
        tail = None
        sentence_rest = text[m.end():]
        dot = sentence_rest.find(".")
        window = sentence_rest[:dot] if dot >= 0 else sentence_rest[:90]
        tm = re.search(r"\bthen\s+shuffle(?:\s+your\s+(?:deck|library))?\b", window, re.I)
        if tm:
            tail = "shuffle"
            end = m.end() + tm.end()
        claim(m.start(), end, {
            "start": m.start(), "end": end, "phrase": text[m.start():end],
            "action": "search",
            "count": _num(m.group(1)) if m.group(1) else None,
            "filter": filt, "groups": parse_filter(filt), "tail": tail,
        })
    for m in _ADD_RE.finditer(text):
        filt = _clean_filter(m.group("filter"))
        claim(m.start(), m.end(), {
            "start": m.start(), "end": m.end(), "phrase": m.group(0),
            "action": "search", "count": _num(m.group(1)),
            "filter": filt, "groups": parse_filter(filt), "tail": None,
        })
    for m in _PEEK_RE.finditer(text):
        window = text[m.end():m.end() + 220]
        fm = _PEEK_FILTER_RE.search(window)
        filt = _clean_filter(fm.group(1)) if fm else ""
        end = m.end()
        tail = None
        ri = window.lower().find("recycle the rest")
        if ri >= 0:
            tail = "recycle"
            end = max(end, m.end() + ri + len("recycle the rest"))
        if fm:
            end = max(end, m.end() + fm.end())
        claim(m.start(), end, {
            "start": m.start(), "end": end, "phrase": text[m.start():end],
            "action": "peek",
            "count": _num(m.group(1)) if m.group(1) else 1,
            "filter": filt, "groups": parse_filter(filt), "tail": tail,
        })
    for action, pat in PATTERNS:
        for m in pat.finditer(text):
            s, e = m.span()
            if any(s < te and e > ts for ts, te in taken):
                continue
            taken.append((s, e))
            item = {"start": s, "end": e, "phrase": m.group(0), "action": action}
            if action == "draw":
                item["count"] = _num(m.group(1))
            if action == "roll" and m.lastindex and m.group(1):
                item["sides"] = int(m.group(1))
            found.append(item)
    return sorted(found, key=lambda x: x["start"])
