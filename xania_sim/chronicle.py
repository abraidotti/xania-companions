"""Legends: what was worth telling, told in each bot's own voice.

Everything here is derived from the event log (``events``), so a chronicle can be rebuilt at any time and never
disagrees with the record:

- ``highlights`` scores each event (``SCORES``) in the context of what came before: a bot's first kill, a level
  that's a milestone, revenge (killing something that once killed it), a close call, a death, a new companion;
- ``journal`` writes one bot's entry for a period: an opening, the best highlights in order, a tally of the rest,
  and a closing line that depends on how it went; lines come from the persona's voice, then the shared ``JOURNAL``
  lines, chosen with a seed per bot and day so the same day always reads the same;
- ``epithets`` awards titles by rules (Ratcatcher, Spiderbane, Twice-Dead, the Avenger...), best first;
- ``cursed_places`` and ``fallen`` (the hall of the fallen) look across all bots;
- ``digest`` stitches several narrators together for a period: a chronicler's frame around each bot's journal.

``post_note`` posts a journal as an in-game note (Note.cpp: ``note to``, ``note subject``, ``note +``, ``note post``).
"""

from __future__ import annotations

import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from .dialogue import LINES, Speaker, _cap
from .persona import Persona, plain

SCORES = {"died": 10, "revenge": 9, "milestone": 8, "close_call": 6, "level": 5, "first_kill": 5, "companion": 4,
          "loot": 3, "fled": 2, "kill": 1}
MILESTONES = (5, 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 91)
DAY = 86400

JOURNAL: dict[str, list[str]] = {
    "j_open": ["{day}. {area_cap} again.", "{day}, in {area}.", "Journal, {day}.", "{day}. Mostly {area}."],
    "j_open_quiet": ["{day}. A quiet one.", "{day}. Not much to tell."],
    "j_died": ["{mob_cap} killed me in {area}.", "I died. {mob_cap}, in {area}. I won't forget it.",
               "Killed by {mob} in {area}. Woke up at the temple, sore."],
    "j_revenge": ["I paid {mob} back for killing me.", "{mob_cap} is dead. Revenge, at last."],
    "j_milestone": ["Level {level}! A milestone.", "I reached level {level}. Someone should write this down. (I did.)"],
    "j_level": ["Reached level {level}.", "Level {level} now."],
    "j_close_call": ["{mob_cap} had me down to {hp} hp. Too close.", "Nearly died to {mob}: {hp}/{max_hp} hp."],
    "j_close_call_anon": ["I was down to {hp} hp at one point. Too close."],
    "j_first_kill": ["My first kill: {mob}.", "{mob_cap}: my first kill. I suppose I'm a proper adventurer now."],
    "j_companion": ["Fell in with {who}.", "{who} and I travelled together."],
    "j_loot": ["Took {item} from {mob}.", "Found {item} on {mob}."],
    "j_fled": ["Ran from a fight. No shame in it.", "Fled one fight. Live to fight another day."],
    "j_fled_many": ["Ran from {n} fights. No shame in it.", "Fled {n} times. Live to fight another day."],
    "j_tally": ["{kills} kills in all: {list}.", "All told, {list}."],
    "j_close_bad": ["Tomorrow will be better.", "I need to be more careful.", "Sore, but alive. Ish."],
    "j_close_good": ["A good day.", "Stronger than yesterday.", "Not bad at all."],
    "j_close": ["That's all.", "Bed.", "More tomorrow."],
    # the chronicler, who frames the digest
    "c_open": ["The chronicle of {period}.", "Here is what befell the companions, {period}."],
    "c_none": ["Nothing stirred in Xania {period}."],
    "c_bot": ["{who}, {epithet_part}level {level} {cls}, writes:", "From the journal of {who}{epithet_comma}:"],
    "c_fallen": ["The fallen: {list}.", "Deaths this time: {list}."],
    "c_cursed": ["Beware {list}.", "Cursed ground: {list}."],
    "c_close": ["So ends the chronicle, for now.", "More will be written."],
}


@dataclass
class Highlight:
    bot: str
    at: float
    kind: str
    score: int
    slots: dict = field(default_factory=dict)


def _norm(name: str | None) -> str:
    return " ".join((name or "").lower().split())


def _article(name: str) -> str:
    """Lower-case a mob's leading article: "The small spider" -> "the small spider"."""
    return re.sub(r"^(The|A|An) ", lambda m: m.group(1).lower() + " ", name or "something")


def highlights(events: list[dict], history: list[dict] = ()) -> list[Highlight]:
    """Scored highlights from one bot's events (oldest first); ``history`` is what came before (for firsts and
    revenge)."""
    killers = {_norm(e["data"].get("killer")) for e in history if e["kind"] == "died"} - {""}
    killed_before = any(e["kind"] == "kill" for e in history)
    companions = {_norm(_who(e)) for e in history if e["kind"] == "group"}
    out = []
    for e in events:
        d, kind, slots = e["data"], e["kind"], {"area": e.get("area") or "the wilds"}
        if kind == "kill":
            mob = _article(d.get("victim") or d.get("target"))
            slots["mob"] = mob
            if _norm(mob) in killers or _norm(d.get("victim")) in killers:
                killers.discard(_norm(mob))
                killers.discard(_norm(d.get("victim")))
                kind = "revenge"
            elif not killed_before:
                kind = "first_kill"
            killed_before = True
        elif kind == "died":
            slots["mob"] = _article(d.get("killer") or "something unseen")
            killers.add(_norm(d.get("killer")))
        elif kind == "level":
            slots["level"] = d.get("level", "?")
            if d.get("level") in MILESTONES:
                kind = "milestone"
        elif kind == "close_call":
            slots |= {"hp": d.get("hp", "?"), "max_hp": d.get("max_hp", "?")}
            if d.get("against"):
                slots["mob"] = _article(d["against"])
        elif kind == "group":
            who = _who(e)
            if not who or _norm(who) in companions:
                continue
            companions.add(_norm(who))
            kind, slots["who"] = "companion", who
        elif kind == "loot":
            slots |= {"item": d.get("item", "something"), "mob": _article(d.get("of"))}
        elif kind == "fled":
            slots["mob"] = "a fight"
        if kind in SCORES:
            out.append(Highlight(e["bot"], e["at"], kind, SCORES[kind], slots))
    return out


def _who(e: dict) -> str | None:
    d = e["data"]
    who = d.get("leader") if d.get("who") == "you" else d.get("who")
    return None if who in (None, "you") else who


def _speaker(persona: Persona, seed: str) -> Speaker:
    return Speaker(persona, random.Random(seed), base=LINES | JOURNAL)


def _day(t: float) -> str:
    return time.strftime("%A %d %B", time.localtime(t)).replace(" 0", " ")


def _list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def tally(events: list[dict], skip: int = 0) -> tuple[int, str]:
    """(kills, "9 gutter rats, 3 ducklings and 2 others") for a period's kills."""
    names = Counter(_article(e["data"].get("victim") or e["data"].get("target")) for e in events if e["kind"] == "kill")
    total = sum(names.values())
    if not total:
        return 0, ""
    top = names.most_common(3)
    parts = [f"{n} {_plural(m)}" if n > 1 else m for m, n in top]
    rest = total - sum(n for _, n in top)
    if rest:
        parts.append(f"{rest} other{'s' if rest > 1 else ''}")
    return total, _list(parts)


def _plural(mob: str) -> str:
    """ "a gutter rat" -> "gutter rats" (the article goes; the last word takes an s)."""
    m = re.sub(r"^(the|a|an) ", "", mob)
    if " of " in m:
        head, tail = m.split(" of ", 1)
        return _plural(head) + " of " + tail
    if m.endswith(("s", "x", "ch", "sh")):
        return m + "es"
    if m.endswith("y") and m[-2:-1] not in "aeiou":
        return m[:-1] + "ies"
    if m.endswith("f"):
        return m[:-1] + "ves"
    return m + "s"


def journal(persona: Persona, events: list[dict], history: list[dict] = (), day: float | None = None,
            limit: int = 5) -> list[str]:
    """One journal entry (a list of sentences) in ``persona``'s voice for ``events`` (one bot, oldest first)."""
    if not events:
        return []
    t0 = day if day is not None else events[0]["at"]
    sp = _speaker(persona, f"{persona.name}:{int(t0 // DAY)}")
    areas = Counter(e["area"] for e in events if e.get("area"))
    area = areas.most_common(1)[0][0] if areas else "the wilds"
    hs = highlights(events, history)
    flees = sum(h.kind == "fled" for h in hs)
    told = [h for h in hs if h.kind not in ("kill", "fled")]
    if flees:  # one line for all of the day's flights
        first = next(h for h in hs if h.kind == "fled")
        told.append(Highlight(first.bot, first.at, "fled_many" if flees > 1 else "fled", first.score, {"n": flees}))
    best = sorted(sorted(told, key=lambda h: (-h.score, h.at))[:limit], key=lambda h: h.at)
    common = {"day": _day(t0), "area": area, "area_cap": _cap(area)}
    kills, listed = tally(events)
    lines = [sp.line("j_open" if best or kills >= 3 else "j_open_quiet", **common)]
    for h in best:
        key = f"j_{h.kind}"
        if h.kind == "close_call" and "mob" not in h.slots:
            key = "j_close_call_anon"
        lines.append(sp.line(key, **common | h.slots))
    if kills >= 3:
        lines.append(sp.line("j_tally", kills=kills, list=listed))
    died = any(h.kind == "died" for h in hs)
    rose = any(h.kind in ("level", "milestone") for h in hs)
    lines.append(sp.line("j_close_bad" if died else "j_close_good" if rose else "j_close", **common))
    return [ln for ln in lines if ln]


# -- epithets -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Epithet:
    title: str  # as worn: "the Ratcatcher", "Spiderbane"
    reason: str
    rank: int  # higher is more prestigious


def epithets(events: list[dict]) -> list[Epithet]:
    """Titles a bot has earned from its whole record, most prestigious first."""
    kills = Counter(_norm(_article(e["data"].get("victim") or e["data"].get("target")))
                    for e in events if e["kind"] == "kill")
    deaths = sum(e["kind"] == "died" for e in events)
    flees = sum(e["kind"] == "fled" for e in events)
    areas = {e["area"] for e in events if e["kind"] == "kill" and e.get("area")}
    total = sum(kills.values())
    revenge = any(h.kind == "revenge" for h in highlights(events))
    out = []
    by_word = Counter()
    for mob, n in kills.items():
        word = re.sub(r"^(the|a|an) ", "", mob).split()[-1] if mob else ""
        if word:
            by_word[word] += n
    for word, n in by_word.most_common():
        if word == "rat" and n >= 10:
            out.append(Epithet("the Ratcatcher", f"{n} rats", 30 + n))
        elif n >= 15:
            out.append(Epithet(f"{word.capitalize()}bane", f"{n} {_plural(word)}", 30 + n))
    if total >= 50 and deaths == 0:
        out.append(Epithet("the Unbroken", f"{total} kills without dying", 80))
    if revenge:
        out.append(Epithet("the Avenger", "killed what killed them", 60))
    if deaths >= 5:
        out.append(Epithet("the Undying", f"{deaths} deaths and still going", 50))
    elif deaths in (2, 3):
        out.append(Epithet({2: "Twice-Dead", 3: "Thrice-Dead"}[deaths], f"{deaths} deaths", 20 + deaths))
    if len(areas) >= 6:
        out.append(Epithet("the Wanderer", f"fought in {len(areas)} areas", 40))
    if flees >= 10:
        out.append(Epithet("the Swift", f"fled {flees} fights and lived", 25))
    return sorted(out, key=lambda e: -e.rank)


def styled(name: str, epithet: Epithet | None) -> str:
    """ "Bram the Ratcatcher", "Hilda Spiderbane", or just the name."""
    return f"{name} {epithet.title}" if epithet else name


# -- across bots ----------------------------------------------------------------------------------
def fallen(events: list[dict]) -> list[dict]:
    """Every death, newest first: bot, when, killer, where."""
    return [{"bot": e["bot"], "at": e["at"], "killer": _article(e["data"].get("killer") or "something unseen"),
             "area": e.get("area") or "?"} for e in sorted(events, key=lambda e: -e["at"]) if e["kind"] == "died"]


def cursed_places(events: list[dict], min_deaths: int = 2) -> list[tuple[str, int, int]]:
    """(area, deaths, kills) where bots keep dying: at least ``min_deaths``, worst ratio first."""
    deaths, kills = Counter(), Counter()
    for e in events:
        if e.get("area"):
            if e["kind"] == "died":
                deaths[e["area"]] += 1
            elif e["kind"] == "kill":
                kills[e["area"]] += 1
    bad = [(a, d, kills[a]) for a, d in deaths.items() if d >= min_deaths]
    return sorted(bad, key=lambda r: (-r[1] / (r[2] + 1), -r[1]))


def digest(by_bot: dict[str, list[dict]], personas: dict[str, Persona], history: dict[str, list[dict]] | None = None,
           period: str = "this weekend", info: dict[str, dict] | None = None) -> list[tuple[str, list[str]]]:
    """Sections of (narrator, lines): the chronicler's opening, each bot's journal under the chronicler's
    introduction, then the fallen and the cursed places. ``info`` per bot: level, cls, epithet."""
    history, info = history or {}, info or {}
    chron = _speaker(plain("The Chronicler"), f"chronicle:{period}")
    everything = [e for evs in by_bot.values() for e in evs]
    if not everything:
        return [("The Chronicler", [chron.line("c_none", period=period)])]
    out = [("The Chronicler", [chron.line("c_open", period=period)])]
    order = sorted(by_bot, key=lambda b: -sum(h.score for h in highlights(by_bot[b], history.get(b, []))))
    for bot in order:
        evs = by_bot[bot]
        if not evs:
            continue
        p = personas.get(bot.lower()) or plain(bot)
        i = info.get(bot, {})
        ep = i.get("epithet")
        intro = chron.line("c_bot", who=bot, level=i.get("level", "?"), cls=i.get("cls", p.cls),
                           epithet_part=f"{ep}, " if ep else "", epithet_comma=f" {ep}" if ep else "")
        out.append(("The Chronicler", [intro]))
        out.append((bot, journal(p, evs, history.get(bot, []))))
    end = []
    dead = fallen(everything)
    if dead:
        end.append(chron.line("c_fallen", list=_list([f"{d['bot']} to {d['killer']} in {d['area']}" for d in dead[:6]])))
    cursed = cursed_places(everything)
    if cursed:
        end.append(chron.line("c_cursed", list=_list([a for a, *_ in cursed[:3]])))
    end.append(chron.line("c_close"))
    out.append(("The Chronicler", end))
    return out


async def post_note(bot, to: str, subject: str, lines: list[str]) -> bool:
    """Post ``lines`` as an in-game note. True if the MUD said Ok to the post."""
    ok = r"^Ok\.|You need to|You have no note|Huh\?"
    await bot.do("note clear", expect=ok)
    await bot.do(f"note to {to}", expect=ok)
    await bot.do(f"note subject {subject.replace('~', '-')}", expect=ok)
    for line in lines:
        for chunk in _wrap(line.replace("~", "-"), 72):
            await bot.do(f"note + {chunk}", expect=ok)
    r = await bot.do("note post", expect=ok)
    return r.has(r"^Ok\.")


def _wrap(text: str, width: int) -> list[str]:
    words, out, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    return out + ([cur] if cur else [])
