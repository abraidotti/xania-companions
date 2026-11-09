"""Gathering the legends from the lore database, for the ``chronicle`` command and the dispatch.

``gather`` reads the event log once: every bot's events in the period and before it, who they are (persona,
level, class) and the epithets their whole record has earned. ``text`` prints the digest (or one bot's story);
the dispatch renders the same ``Legends`` as HTML.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from . import chronicle as C
from .events import Progress
from .memory import Memory
from .persona import Persona, plain, roster

DAY = C.DAY


@dataclass
class Legends:
    since: float
    period: str
    recent: dict[str, list[dict]] = field(default_factory=dict)  # bot -> events in the period
    history: dict[str, list[dict]] = field(default_factory=dict)  # bot -> events before it
    personas: dict[str, Persona] = field(default_factory=dict)  # lower-case name -> persona
    info: dict[str, dict] = field(default_factory=dict)  # bot -> level, cls, epithet, epithets
    everything: list[dict] = field(default_factory=list)

    def persona(self, bot: str) -> Persona:
        return self.personas.get(bot.lower()) or plain(bot, self.info.get(bot, {}).get("cls", "knight"))

    def digest(self) -> list[tuple[str, list[str]]]:
        return C.digest(self.recent, {b.lower(): self.persona(b) for b in self.recent}, self.history, self.period,
                        self.info)

    def days(self, bot: str) -> list[tuple[float, list[str]]]:
        """(day start, journal entry) for each day the bot did anything, newest first."""
        by_day: dict[int, list[dict]] = defaultdict(list)
        for e in self.history.get(bot, []) + self.recent.get(bot, []):
            by_day[int(_local_day(e["at"]))].append(e)
        out, before = [], []
        for d in sorted(by_day):
            out.append((float(d), C.journal(self.persona(bot), by_day[d], before)))
            before = before + by_day[d]
        return out[::-1]


def _local_day(t: float) -> float:
    lt = time.localtime(t)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _period(days: float) -> str:
    if days <= 1:
        return "today"
    return "this weekend" if days <= 3 else f"these {days:.0f} days"


def gather(db, bot: str | None = None, days: float = 3, now: float | None = None) -> Legends:
    now = time.time() if now is None else now
    since = now - days * DAY
    pr = Progress(db)
    lg = Legends(since, _period(days), personas=roster())
    statuses = {s.name: s for s in pr.bots()}
    names = [bot.capitalize()] if bot else list(statuses)
    for name in names:
        evs = pr.timeline(name)
        lg.everything += evs
        lg.history[name] = [e for e in evs if e["at"] < since]
        lg.recent[name] = [e for e in evs if e["at"] >= since]
        earned = C.epithets(evs)
        s = statuses.get(name)
        nemeses = Memory(db, name).top("nemesis", 3, by="kills_me")
        lg.info[name] = {"level": s.level if s else "?", "cls": s.cls if s else "", "race": s.race if s else "",
                         "epithet": earned[0].title if earned else None, "epithets": earned, "nemeses": nemeses}
    return lg


def text(db, bot: str | None = None, days: float = 3) -> str:
    lg = gather(db, bot, days)
    if bot:
        name = bot.capitalize()
        info = lg.info.get(name, {})
        out = [C.styled(name, info["epithets"][0] if info.get("epithets") else None)
               + f", level {info.get('level', '?')} {info.get('cls', '')}", ""]
        for e in info.get("epithets", []):
            out.append(f"  {e.title}: {e.reason}")
        for n in info.get("nemeses", []):
            out.append(f"  nemesis: {n['key']} (killed {name} {n['data'].get('kills_me', n['count'])}x"
                       + (", avenged)" if n["data"].get("revenge") else ")"))
        for day, entry in lg.days(name):
            out += [""] + [f"  {ln}" for ln in entry]  # each entry opens with its day
        return "\n".join(out)
    out = []
    for narrator, lines in lg.digest():
        out.append(f"[{narrator}]")
        out += [f"  {ln}" for ln in lines]
    return "\n".join(out)
