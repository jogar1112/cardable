"""SQLite store: players, personal libraries, decks, saved game profiles,
per-player settings. Rooms are live state and stay in memory (app/room.py).
"""
import json
import os
import secrets
import sqlite3
import threading

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
DB_PATH = os.path.join(DATA_DIR, "cardable.db")
_lock = threading.Lock()


def _conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS players(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, token TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS library_cards(
                id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '',
                primary_number TEXT NOT NULL DEFAULT '',
                image_path TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE IF NOT EXISTS decks(
                id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL,
                name TEXT NOT NULL, card_ids TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS saved_profiles(
                id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL,
                name TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(
                player_id INTEGER PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}');
            """
        )
        cols = [r[1] for r in c.execute("PRAGMA table_info(library_cards)")]
        if "type_line" not in cols:
            c.execute("ALTER TABLE library_cards ADD COLUMN "
                      "type_line TEXT NOT NULL DEFAULT ''")


def create_player(name):
    token = secrets.token_urlsafe(24)
    with _lock, _conn() as c:
        cur = c.execute("INSERT INTO players(name, token) VALUES(?,?)", (name, token))
        return {"id": cur.lastrowid, "name": name, "token": token}


def player_by_token(token):
    if not token:
        return None
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM players WHERE token=?", (token,)).fetchone()
        return dict(row) if row else None


def add_library_card(owner_id, name, text, primary, image_path, type_line=""):
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO library_cards(owner_id,name,text,primary_number,image_path,type_line) VALUES(?,?,?,?,?,?)",
            (owner_id, name, text, primary, image_path, type_line))
        return cur.lastrowid


def list_library(owner_id):
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM library_cards WHERE owner_id=? ORDER BY id", (owner_id,)).fetchall()
        return [dict(r) for r in rows]


def get_library_card(owner_id, card_id):
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM library_cards WHERE owner_id=? AND id=?",
                        (owner_id, card_id)).fetchone()
        return dict(row) if row else None


def update_library_card(owner_id, card_id, name, text, primary, type_line=""):
    with _lock, _conn() as c:
        c.execute("UPDATE library_cards SET name=?, text=?, primary_number=?, type_line=? WHERE owner_id=? AND id=?",
                  (name, text, primary, type_line, owner_id, card_id))


def create_deck(owner_id, name, card_ids):
    with _lock, _conn() as c:
        cur = c.execute("INSERT INTO decks(owner_id,name,card_ids) VALUES(?,?,?)",
                        (owner_id, name, json.dumps(card_ids)))
        return cur.lastrowid


def list_decks(owner_id):
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM decks WHERE owner_id=? ORDER BY id", (owner_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["card_ids"] = json.loads(d["card_ids"])
            out.append(d)
        return out


def get_deck(owner_id, deck_id):
    for d in list_decks(owner_id):
        if d["id"] == deck_id:
            return d
    return None


def save_profile(owner_id, name, data):
    with _lock, _conn() as c:
        cur = c.execute("INSERT INTO saved_profiles(owner_id,name,data) VALUES(?,?,?)",
                        (owner_id, name, json.dumps(data)))
        return cur.lastrowid


def list_profiles(owner_id):
    with _lock, _conn() as c:
        rows = c.execute("SELECT * FROM saved_profiles WHERE owner_id=? ORDER BY id", (owner_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d["data"])
            out.append(d)
        return out


def get_settings(player_id):
    with _lock, _conn() as c:
        row = c.execute("SELECT data FROM settings WHERE player_id=?", (player_id,)).fetchone()
        data = json.loads(row["data"]) if row else {}
    data.setdefault("link_mode", "instant")  # instant | confirm
    return data


def set_settings(player_id, data):
    merged = get_settings(player_id)
    merged.update(data)
    with _lock, _conn() as c:
        c.execute("INSERT INTO settings(player_id,data) VALUES(?,?) "
                  "ON CONFLICT(player_id) DO UPDATE SET data=excluded.data",
                  (player_id, json.dumps(merged)))
    return merged
