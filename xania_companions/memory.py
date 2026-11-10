"""What a bot remembers: facts about people, places and enemies, built up from its events and kept in the lore
database (table ``memories``), so a bot that logs in next weekend still knows who healed it and what killed it.

Each fact is (bot, kind, key) with a count, first and last time, and a small JSON payload. Kinds:

- ``person``: someone it has talked or grouped with (``talks``, ``groups``);
- ``place``: an area, with ``kills``, ``deaths`` and ``xp`` there;
- ``nemesis``: a mob that killed it (``kills_me``), and ``revenge`` once it has killed one back;
- ``debt``: someone who healed or rescued it;
- ``first``: firsts (first kill, first level, first death), one row each, for the chronicle.

``Keeper`` is a ``Bot`` observer that turns events into memories as they happen; ``Memory`` reads and writes them.
"""

from __future__ import annotations

import json
import time

from xania_sim.events import attacker, parse

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    bot TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
    first REAL NOT NULL, last REAL NOT NULL, data TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (bot, kind, key));
"""


def _key(text: str) -> str:
    return " ".join(text.lower().split())


class Memory:
    def __init__(self, db, bot: str, clock=time.time):
        self.db, self.bot, self.clock = db, bot.capitalize(), clock
        db.executescript(SCHEMA)

    def note(self, kind: str, key: str, count: int = 1, **data) -> dict:
        """Add to a fact (creating it): its count goes up by ``count``, numeric data fields are summed, others set.
        Returns the fact after the change."""
        now, k = self.clock(), _key(key)
        old = self.get(kind, k)
        merged = dict(old["data"]) if old else {}
        for name, v in data.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and isinstance(merged.get(name), (int, float)):
                merged[name] += v
            else:
                merged[name] = v
        with self.db:
            self.db.execute(
                "INSERT INTO memories (bot, kind, key, count, first, last, data) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(bot, kind, key) DO UPDATE SET count = count + excluded.count, last = excluded.last, "
                "data = excluded.data", (self.bot, kind, k, count, now, now, json.dumps(merged)))
        return self.get(kind, k)

    def first(self, what: str, **data) -> bool:
        """Record a first (e.g. "kill"); True only the first time."""
        if self.get("first", what):
            return False
        self.note("first", what, **data)
        return True

    def get(self, kind: str, key: str) -> dict | None:
        row = self.db.execute("SELECT key, count, first, last, data FROM memories WHERE bot = ? AND kind = ? AND key = ?",
                              (self.bot, kind, _key(key))).fetchone()
        return None if row is None else {"key": row[0], "count": row[1], "first": row[2], "last": row[3],
                                         "data": json.loads(row[4])}

    def top(self, kind: str, n: int = 5, by: str = "count") -> list[dict]:
        rows = self.db.execute("SELECT key, count, first, last, data FROM memories WHERE bot = ? AND kind = ?",
                               (self.bot, kind)).fetchall()
        facts = [{"key": k, "count": c, "first": f, "last": la, "data": json.loads(d)} for k, c, f, la, d in rows]
        key = (lambda m: m["count"]) if by == "count" else (lambda m: m["data"].get(by, 0))
        return sorted(facts, key=lambda m: (-key(m), -m["last"]))[:n]

    def nemesis(self) -> dict | None:
        """The mob that has killed this bot most often and not yet been avenged (or the deadliest, if all were)."""
        foes = self.top("nemesis", 20)
        open_ = [f for f in foes if not f["data"].get("revenge")]
        return (open_ or foes or [None])[0]


class Keeper:
    """Watches a bot and remembers. ``area()`` gives the current area's name; ``target()`` what it's fighting."""

    def __init__(self, memory: Memory, bot, area=None, target=None, on_fact=None):
        self.memory, self.bot = memory, bot
        self.area = area or (lambda: None)
        self.target = target or (lambda: None)
        self.on_fact = on_fact  # called with (kind, fact) for notable changes: lets a companion react
        self.last_attacker: str | None = None
        bot.observers.append(self.feed)

    def _tell(self, kind: str, fact) -> None:
        if self.on_fact is not None and fact is not None:
            self.on_fact(kind, fact)

    def feed(self, text: str, prompt) -> None:
        m, area = self.memory, self.area()
        if (hit_by := attacker(text)) is not None:
            self.last_attacker = hit_by
        for e in parse(text):
            d = e.data
            if e.kind == "kill":
                victim = d.get("victim", "?")
                if area:
                    m.note("place", area, kills=1)
                if m.first("kill", victim=victim, area=area):
                    self._tell("first_kill", m.get("first", "kill"))
                foe = m.get("nemesis", victim)
                if foe is not None and not foe["data"].get("revenge"):
                    self._tell("revenge", m.note("nemesis", victim, count=0, revenge=True, avenged_at=m.clock()))
            elif e.kind == "died":
                killer = d.get("killer") or self.last_attacker or self.target() or "something unseen"
                self.last_attacker = None
                if area:
                    m.note("place", area, deaths=1)
                self._tell("killed_by", m.note("nemesis", killer, kills_me=1, revenge=False, area=area or ""))
                m.first("death", killer=killer, area=area)
            elif e.kind == "xp" and area:
                m.note("place", area, count=0, xp=d.get("amount", 0))
            elif e.kind == "level":
                m.first("level")
            elif e.kind in ("tell", "say") and d.get("from") and d["from"].lower() != self.bot.name.lower():
                m.note("person", d["from"], talks=1)
            elif e.kind == "group":
                who = d.get("leader") if d.get("who") == "you" else d.get("who")
                if who and who != "you":
                    self._tell("grouped", m.note("person", who, groups=1))
