"""Talking without an LLM: what someone said is matched to an intent, and the bot answers with a line from its
voice (the shared lines below plus its persona's own), slots filled from the moment, avoiding lines it used
recently. Events get reactions the same way (``react``), gated by the persona's chattiness.

Answers that need facts get them from the game: ``where_level`` names the areas where this bot's safe targets
spawn (``fight.safe_targets``: Explorer's prediction, corrected by what bots have seen), ``nemesis`` comes from
memory.

There is one optional hook for an LLM (``Speaker.fallback``): called with (text, persona, slots) for lines that
match no intent; it is ``None`` (off) unless a caller sets it.
"""

from __future__ import annotations

import random
import re
from collections import deque

from .persona import Persona

# intent -> pattern over what was said (lower-cased). First match wins, so specific intents come first.
INTENTS: list[tuple[str, re.Pattern]] = [
    ("where_level", re.compile(r"where (?:should|can|do|could|would) (?:i|we|you)\b.*\b(?:level|hunt|fight|xp|exp)|"
                               r"where to (?:level|hunt)|good (?:place|area|spot) (?:to|for) (?:level|hunt|xp)")),
    ("nemesis", re.compile(r"who (?:killed|kills) you|nemesis|your (?:worst )?enemy|what killed you|grudge")),
    ("how_are_you", re.compile(r"how (?:are|r) (?:you|u)|how'?s it going|you ok|are you (?:ok|alright|hurt)")),
    ("who_are_you", re.compile(r"who are you|what are you|tell me about yourself|your name")),
    ("thanks", re.compile(r"\b(?:thanks|thank you|thx|ty|cheers|much obliged)\b")),
    ("praise", re.compile(r"\b(?:good job|well done|nice (?:one|work|job)|great|awesome|good (?:bot|work)|bravo)\b")),
    ("insult", re.compile(r"\b(?:stupid|idiot|useless|noob|dumb|suck|worthless|pathetic)\b")),
    ("joke", re.compile(r"\b(?:joke|funny|make me laugh)\b")),
    ("greet", re.compile(r"^(?:hi|hello|hey|hiya|greetings|good (?:morning|evening|day)|yo|howdy|hail)\b")),
]

# The shared voice. Each persona's [voice] lines are added to these.
LINES: dict[str, list[str]] = {
    "hello": ["Hello {master}! I'm {me}, a level {level} {cls}. Tell me 'help' to see what I can do.",
              "{me} reporting, {master}. Level {level} {cls}, at your service. Tell me 'help' for orders."],
    "greet": ["Hello, {master}.", "Hail, {master}!", "Good to see you, {master}."],
    "thanks": ["Any time.", "Glad to help, {master}.", "Don't mention it."],
    "praise": ["Thank you, {master}!", "I'm trying my best.", "That means a lot."],
    "insult": ["That's unkind, {master}.", "I'll remember that.", "Hmph."],
    "joke": ["Why did the {cls} cross the road? The other side had experience points.",
             "I asked the Mud School monster for directions. It just roared. Typical."],
    "how_are_you": ["{hp}/{max_hp} hp and {mood}.", "{mood_cap}, {hp}/{max_hp} hp. Thanks for asking."],
    "who_are_you": ["I'm {me}, a level {level} {race} {cls}. {summary}", "{me}, {cls}, level {level}. {summary}"],
    "where_level": ["At level {level}, try {areas}.", "For a level {level} {cls} like me: {areas}.",
                    "{areas}, I'd say. That's where the safe fights are at level {level}."],
    "where_level_none": ["I don't know anywhere safe at level {level}. Stay close to town."],
    "nemesis": ["{nemesis} killed me {times}. I haven't forgotten.", "{nemesis_cap}. {times_cap}. One day..."],
    "nemesis_avenged": ["{nemesis} killed me {times}, but I paid it back."],
    "nemesis_none": ["Nothing has killed me yet. Knock on wood."],
    "follow_ok": ["Right behind you.", "Lead on, {master}.", "With you, {master}."],
    "stay_ok": ["I'll wait here, at {where}.", "Waiting at {where}."],
    "farewell": ["Farewell!", "Until next time, {master}.", "Safe travels, {master}."],
    "unknown": ["Sorry, I don't follow. I can: {commands}.", "Hmm? Orders I know: {commands}."],
    # reactions to events (said only some of the time, by chattiness)
    "level_up": ["Level {level}! I can feel it.", "I'm level {level} now!", "Level {level}. Getting stronger."],
    "first_kill": ["My first kill: {mob}. I won't forget it.", "{mob_cap} is my first kill!"],
    "close_call": ["That was close. {hp}/{max_hp} hp.", "Too close. I need a rest."],
    "killed_by": ["{mob_cap} killed me. I'll be back for it.", "I died to {mob}. That's a grudge now."],
    "revenge": ["{mob_cap} is dead. That's for last time.", "Revenge on {mob}, at last."],
    "grouped": ["Together, then.", "Good to be in a party again."],
}

COOLDOWN = 3  # a line isn't reused until this many others of the same intent have been said


def classify(text: str) -> str | None:
    t = " ".join(text.lower().split())
    for intent, pattern in INTENTS:
        if pattern.search(t):
            return intent
    return None


class _Slots(dict):
    def __missing__(self, key):
        return "{" + key + "}"  # visible, so a missing slot shows up in tests rather than as a silent "?"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


class Speaker:
    def __init__(self, persona: Persona, rng: random.Random | None = None):
        self.persona = persona
        self.rng = rng or random.Random()
        self.recent: dict[str, deque] = {}
        self.fallback = None  # optional (text, persona, slots) -> str | None, e.g. an LLM; off by default

    def lines(self, intent: str) -> list[str]:
        return LINES.get(intent, []) + self.persona.voice.get(intent, [])

    def line(self, intent: str, **slots) -> str:
        options = self.lines(intent)
        if not options:
            return ""
        recent = self.recent.setdefault(intent, deque(maxlen=min(COOLDOWN, len(options) - 1) or 1))
        fresh = [o for o in options if o not in recent] or options
        choice = self.rng.choice(fresh)
        if len(options) > 1:
            recent.append(choice)
        s = _Slots(me=self.persona.name, cls=self.persona.cls, race=self.persona.race, summary=self.persona.summary,
                   **slots)
        for k in ("mob", "nemesis", "times", "mood"):
            if k in s:
                s[f"{k}_cap"] = _cap(str(s[k]))
        text = choice.format_map(s).strip()
        if self.persona.catchphrases and intent in ("farewell", "greet", "hello") and self.rng.random() < 0.3:
            text += " " + self.rng.choice(self.persona.catchphrases)
        return text

    def chatty(self) -> bool:
        """Whether to remark on something right now (by chattiness: 15% for the quietest, 85% for the chattiest)."""
        return self.rng.random() < 0.15 + 0.7 * self.persona.trait("chattiness")

    def answer(self, text: str, **slots) -> str | None:
        """A reply to free text, or None if it matches no intent (and the fallback, if any, has nothing)."""
        intent = classify(text)
        if intent is None:
            return self.fallback(text, self.persona, slots) if self.fallback else None
        if intent == "nemesis":
            foe = slots.get("nemesis_fact")
            if foe is None:
                return self.line("nemesis_none", **slots)
            n = foe["data"].get("kills_me", foe["count"])
            which = "nemesis_avenged" if foe["data"].get("revenge") else "nemesis"
            return self.line(which, **slots | {"nemesis": foe["key"], "times": _times(n)})
        if intent == "where_level":
            areas = slots.get("areas") or []
            if not areas:
                return self.line("where_level_none", **slots)
            return self.line("where_level", **slots | {"areas": _join(areas)})
        if intent == "how_are_you":
            share = slots.get("hp", 1) / max(1, slots.get("max_hp", 1))
            mood = "feeling strong" if share > 0.8 else "a bit battered" if share > 0.4 else "badly hurt"
            return self.line(intent, **slots | {"mood": mood})
        return self.line(intent, **slots)


def _join(items: list[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def level_areas(world, cls: str, level: int, log=None, limit: int = 3) -> list[str]:
    """Areas worth levelling in for this class and level: where its safe targets spawn, by expected xp per round
    summed over spawns, nearer to the temple breaking ties."""
    from xania_explorer import api
    from xania_explorer.assess import mobs as M

    from .fight import safe_targets

    targets = safe_targets(world, cls, level, log)
    dist = api.distances(world, api.RECALL_ROOM)
    value: dict[str, float] = {}
    near: dict[str, int] = {}
    for info in M.collect(world):
        v = targets.get(info.mob.vnum)
        if v is None:
            continue
        for s in info.spawns:
            if s.room_vnum not in dist:
                continue
            area = world.room_area[s.room_vnum].name
            value[area] = value.get(area, 0.0) + v
            near[area] = min(near.get(area, 10 ** 6), dist[s.room_vnum])
    return sorted(value, key=lambda a: (-value[a], near[a]))[:limit]
