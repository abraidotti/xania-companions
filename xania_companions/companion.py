"""Companions: a bot that plays alongside a person, takes orders by tell, and says what it's doing.

The person (the "master") tells the bot a command, e.g. ``tell Bram follow``:

- ``follow`` / ``come``: follow the master (and turn autoassist on, so once the master groups the bot with
  ``group Bram`` it joins the master's fights: fight.cpp check_assist);
- ``stay`` / ``wait``: stop following and wait here;
- ``status``: level, HP, mana, where it is and what it's doing;
- ``home``: recall to the temple; ``rest``: sleep until healed;
- ``hunt``: level on its own (``level.Leveller``) until told anything else;
- ``heal`` / ``buff``: cast its best cure (or armor and bless) on the master, if its class knows them by now;
- ``help``; ``bye``: stop.

Healers also watch the group while following: when someone is below ``HEAL_BELOW`` of their HP and the bot has the
mana, it casts its best cure on them. When the master moves, "You follow X." and the room that follows keep the
navigator's belief up to date.

A companion has a persona (``persona.py``: traits and voice) and, given the lore database, a memory
(``memory.py``). Anything said to it that isn't an order is answered in its voice (``dialogue.py``: greetings,
thanks, "where should I level?", "who killed you?"...), and it remarks on what happens to it (levels, first kill,
close calls, deaths, revenge) as often as its chattiness says. Bravery sets its flee threshold and loyalty how soon
it heals.

Everything a companion does goes through ``Bot.do``, so a ``Recorder`` on the same bot logs it like any other play.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from xania_explorer import api

from .dialogue import Speaker, level_areas
from xania_sim.events import parse
from xania_sim.fight import recover
from .memory import Keeper, Memory
from .persona import Persona, plain
from xania_sim.nav import Navigator, NavError
from xania_sim.rooms import parse_view
from xania_sim.session import Bot

HEALS = ("heal", "cure critical", "cure serious", "cure light")  # best first
BUFFS = ("armor", "bless")
HEAL_BELOW = 0.5
GROUP_EVERY = 6.0  # seconds between group checks while following
ALIASES = {"come": "follow", "f": "follow", "wait": "stay", "unfollow": "stay", "st": "status", "how": "status",
           "recall": "home", "sleep": "rest", "level": "hunt", "fight": "hunt", "cure": "heal", "quit": "bye",
           "?": "help", "commands": "help"}
COMMANDS = ("follow", "stay", "status", "home", "rest", "hunt", "heal", "buff", "help", "bye")

FOLLOWED = re.compile(r"^You follow (?P<who>.+?)\.$", re.M)
FOLLOW_REPLY = (r"You now follow|They aren't here|You already follow|But you'd rather|doesn't seem to want|"
                r"No way! You are still fighting|can't follow someone")
CAST_REPLY = (r"^Ok\.|You feel|You don't know any spells|You don't have enough mana|You lost your concentration|"
              r"They aren't here|Cast which what where|You can't|is already|are already|not in the mood")
TELL_REPLY = r"^You tell |They aren't here|is not receiving tells|can't hear you|is AFK"
REMOVED = re.compile(r"removes you from (?:his|her|their|its) group|You stop following")
GROUP_LINE = re.compile(r"^\[\s*(?P<lvl>\d+) +[^\]]*\] (?P<name>\S+) +(?P<hp>-?\d+)/ *(?P<max>\d+) hp", re.M)
LEVEL = re.compile(r"Level:?\s+(\d+)")


@dataclass
class Member:
    name: str
    level: int
    hp: int
    max_hp: int

    @property
    def share(self) -> float:
        return self.hp / self.max_hp if self.max_hp else 1.0


def parse_group(text: str) -> list[Member]:
    """Members from ``group`` output (act_comm.cpp do_group: "[lvl Cls] Name  hp/max hp ...")."""
    return [Member(m["name"], int(m["lvl"]), int(m["hp"]), int(m["max"])) for m in GROUP_LINE.finditer(text)]


def command_of(text: str, bot_name: str = "") -> tuple[str, str]:
    """(command, rest) from a tell: the first word, lower-cased and de-punctuated, with aliases resolved; a leading
    bot name ("Bram, follow") is skipped."""
    words = re.sub(r"[^\w\s'?-]", " ", text).split()
    if words and bot_name and words[0].lower() == bot_name.lower():
        words = words[1:]
    if not words:
        return "", ""
    word = words[0].lower()
    return ALIASES.get(word, word), " ".join(words[1:])


CLOSE_CALL = 0.2  # below this share of HP (and alive) is worth a remark
REMARK_GAP = 45.0  # seconds between unprompted remarks


class Companion:
    def __init__(self, bot: Bot, world, cls: str, master: str, nav: Navigator | None = None, level: int = 1,
                 leveller=None, hunt_budget: float = 600, persona: Persona | None = None, db=None, log=None,
                 speaker: Speaker | None = None, autonomous: bool = False, idle_hunt: float = 180):
        self.bot, self.world, self.cls, self.master = bot, world, cls, master.capitalize()
        self.nav = nav or Navigator(bot, world)
        self.level, self.leveller, self.hunt_budget = level, leveller, hunt_budget
        self.persona = persona or plain(bot.name, cls)
        self.speaker = speaker or Speaker(self.persona)
        self.log = log  # fight.FightLog, for "where should I level?"
        if leveller is not None:
            leveller.flee_at = self.persona.flee_at
        self.memory = Memory(db, bot.name) if db is not None else None
        self.target: str | None = None
        if self.memory is not None:
            Keeper(self.memory, bot, area=self._area, target=lambda: self._target(), on_fact=self._fact)
        self.spells = {a.name: a.level for a in api.abilities(cls)}
        self.inbox: list[str] = []
        self.remarks: list[tuple[str, dict]] = []  # (intent, slots) waiting to be said
        self._last_remark = 0.0
        self._close_call_armed = True
        self._areas: dict[int, list[str]] = {}
        # autonomous: with no orders for ``idle_hunt`` seconds (or the master offline), go hunting on its own
        self.autonomous, self.idle_hunt = autonomous, idle_hunt
        self.master_online = True
        self._last_order = 0.0
        self.epithet: str | None = None
        if self.memory is not None:
            worn = self.memory.top("epithet", 1, by="worn_at")
            self.epithet = worn[0]["data"].get("title") if worn else None
        self.following = self.grouped = self.done = False
        self.mode = "idle"  # idle, follow, hunt
        self.doing = "waiting for orders"
        self._last_group_check = 0.0
        bot.observers.append(self._watch)

    # -- what the bot hears -------------------------------------------------------------------------
    def _watch(self, text: str, prompt) -> None:
        for e in parse(text):
            if e.kind == "tell" and e.data["from"].lower() == self.master.lower():
                self.inbox.append(e.data["text"])
                self.master_online = True
            elif e.kind == "group" and e.data.get("leader", "").lower() == self.master.lower():
                self.grouped = True
            elif e.kind == "level":
                self.level += 1
                self.remarks.append(("level_up", {"level": self.level}))
        if (m := REMOVED.search(text)) is not None:
            if "group" in m.group(0):
                self.grouped = False
            else:
                self.following = False
        if prompt is not None and prompt.max_hp:
            if 0 < prompt.hp < CLOSE_CALL * prompt.max_hp and self._close_call_armed:
                self._close_call_armed = False
                self.remarks.append(("close_call", {"hp": prompt.hp, "max_hp": prompt.max_hp}))
            elif prompt.hp >= 0.6 * prompt.max_hp:
                self._close_call_armed = True
        if (m := FOLLOWED.search(text)) is not None and m["who"].lower() == self.master.lower():
            view = parse_view(text[m.end():])
            if view is not None:
                self.nav._arrive(self.nav.recognise(view, None))

    def _area(self) -> str | None:
        a = self.world.room_area.get(self.nav.here) if self.nav.here is not None else None
        return a.name if a is not None else None

    def _target(self) -> str | None:
        rec = self.leveller.recorder if self.leveller is not None else None
        return (rec.target if rec is not None else None) or self.target

    def _fact(self, kind: str, fact: dict) -> None:
        mob = fact.get("data", {}).get("victim") or fact["key"]
        if kind in ("first_kill", "killed_by", "revenge"):
            self.remarks.append((kind, {"mob": mob}))
        elif kind == "grouped" and fact["count"] == 1:
            self.remarks.append(("grouped", {}))

    def slots(self) -> dict:
        p = self.bot.prompt
        return {"master": self.master, "level": self.level, "hp": p.hp if p else 0, "max_hp": p.max_hp if p else 0,
                "mana": p.mana if p else 0, "where": self.where(), "area": self._area() or "?",
                "commands": ", ".join(COMMANDS)}

    async def say(self, intent: str, **extra) -> None:
        line = self.speaker.line(intent, **self.slots() | extra)
        if line:
            await self.tell(line)

    def best(self, names) -> str | None:
        return next((n for n in names if self.spells.get(n, 999) <= self.level), None)

    # -- talking ---------------------------------------------------------------------------------
    async def tell(self, text: str) -> bool:
        """Tell the master; False if they aren't online (or can't hear), which an autonomous companion takes as
        leave to go hunting."""
        r = await self.bot.do(f"tell {self.master} {text}", expect=TELL_REPLY)
        delivered = r.has(r"^You tell ")
        self.master_online = delivered
        return delivered

    def where(self) -> str:
        here = self.nav.here
        if here is None or here not in self.world.rooms:
            return "somewhere I don't recognise"
        from xania_sim.rooms import plain

        area = self.world.room_area.get(here)
        return f"{plain(self.world.rooms[here].name).strip()}" + (f" in {area.name}" if area else "")

    # -- the loop --------------------------------------------------------------------------------
    async def run(self, seconds: float | None = None) -> None:
        loop = asyncio.get_running_loop()
        end = None if seconds is None else loop.time() + seconds
        self._last_order = loop.time()
        await self._read_level()
        await self.say("hello")
        while not self.done and (end is None or loop.time() < end):
            if self.inbox:
                self._last_order = loop.time()
                await self.handle(self.inbox.pop(0))
            elif self.remarks:
                await self._remark(loop.time())
            elif self._should_wander(loop.time()):
                self.mode, self.doing = "hunt", f"hunting while {self.master} is away"
            elif self.mode == "hunt":
                await self._hunt()
            else:
                await self._tend(loop.time())
                await self.bot.listen(2)

    def _should_wander(self, now: float) -> bool:
        if not self.autonomous or self.leveller is None or self.mode != "idle" or self.following:
            return False
        return not self.master_online or now - self._last_order >= self.idle_hunt

    async def _read_level(self) -> None:
        r = await self.bot.do("score", expect=LEVEL)
        if m := LEVEL.search(r.text):
            self.level = int(m.group(1))
        if self.nav.here is None:
            try:
                await self.nav.locate()
            except NavError:
                pass

    async def handle(self, text: str) -> None:
        cmd, rest = command_of(text, self.bot.name)
        action = getattr(self, f"cmd_{cmd}", None) if cmd in COMMANDS else None
        if action is not None:
            await action(rest)
            return
        slots = self.slots()
        if self.memory is not None:
            slots["nemesis_fact"] = self.memory.nemesis()
        if self.level not in self._areas:
            try:
                self._areas[self.level] = level_areas(self.world, self.cls, self.level, self.log)
            except Exception:  # pragma: no cover - a world without combat data
                self._areas[self.level] = []
        slots["areas"] = self._areas[self.level]
        reply = self.speaker.answer(text, **slots)
        await self.tell(reply or self.speaker.line("unknown", **slots))

    async def _remark(self, now: float) -> None:
        """Say one queued remark, if it's been a while and the persona feels like talking; drop the rest."""
        intent, extra = self.remarks.pop(0)
        important = intent in ("killed_by", "revenge", "level_up")
        if now - self._last_remark >= REMARK_GAP or important:
            if important or self.speaker.chatty():
                self._last_remark = now
                await self.say(intent, **extra)
        if intent in ("killed_by", "revenge", "level_up", "first_kill"):
            await self.check_epithet()

    async def check_epithet(self) -> None:
        """Wear the best title the record has earned (``title``, act_info.cpp do_title), and say so."""
        if self.memory is None:
            return
        from .chronicle import epithets
        from xania_sim.events import Progress

        earned = epithets(Progress(self.memory.db).timeline(self.bot.name))
        if not earned or earned[0].title == self.epithet:
            return
        best = earned[0]
        await self.bot.do(f"title {best.title}", expect=r"^Ok\.|Change your title")
        self.memory.note("epithet", best.title, title=best.title, reason=best.reason, worn_at=self.memory.clock())
        self.epithet = best.title
        await self.say("epithet", title=best.title, reason=best.reason)

    # -- commands --------------------------------------------------------------------------------
    async def cmd_help(self, rest: str) -> None:
        await self.tell("follow, stay, status, home, rest, hunt, heal, buff, bye. Group me once I follow you "
                        "and I'll fight beside you.")

    async def cmd_follow(self, rest: str) -> None:
        r = await self.bot.do(f"follow {self.master}", expect=FOLLOW_REPLY)
        if re.search(r"You now follow|You already follow|But you'd rather", r.text):
            self.following, self.mode, self.doing = True, "follow", f"following {self.master}"
            await self._autoassist(True)
            line = self.speaker.line("follow_ok", **self.slots())
            await self.tell(line + ("" if self.grouped else f" Type 'group {self.bot.name}' and I'll fight beside you."))
        elif "They aren't here" in r.text:
            await self.tell(f"I can't see you. I'm at {self.where()}.")
        else:
            await self.tell(f"I can't follow you right now ({r.lines[0] if r.lines else 'no answer'}).")

    async def cmd_stay(self, rest: str) -> None:
        await self.bot.do("follow self", expect=r"You stop following|You already follow yourself|Follow whom")
        self.following, self.mode, self.doing = False, "idle", f"waiting at {self.where()}"
        await self.say("stay_ok")

    async def cmd_status(self, rest: str) -> None:
        p = self.bot.prompt
        mana = f", {p.mana}/{p.max_mana} mana" if p.max_mana else ""
        await self.tell(f"Level {self.level}, {p.hp}/{p.max_hp} hp{mana}, {p.moves}/{p.max_moves} moves. "
                        f"I'm at {self.where()}, {self.doing}.")

    async def cmd_home(self, rest: str) -> None:
        if self.following:
            await self.bot.do("follow self", expect=r"You stop following|You already follow yourself")
            self.following = False
        try:
            await self.nav.recall()
            self.mode, self.doing = "idle", "waiting at the temple"
            await self.tell("I'm back at the temple.")
        except NavError as e:
            await self.tell(f"I couldn't recall: {e}")

    async def cmd_rest(self, rest: str) -> None:
        self.doing = "resting"
        await self.tell("Resting a while.")
        await recover(self.bot, timeout=300, on_attack=self.nav.escape)
        p = self.bot.prompt
        self.doing = f"following {self.master}" if self.following else "waiting for orders"
        await self.tell(f"Rested: {p.hp}/{p.max_hp} hp.")

    async def cmd_hunt(self, rest: str) -> None:
        if self.leveller is None:
            await self.tell("I don't know where to hunt yet.")
            return
        if self.following:
            await self.bot.do("follow self", expect=r"You stop following|You already follow yourself")
            self.following = False
        self.mode, self.doing = "hunt", "hunting for xp"
        await self.tell("Off to hunt. Tell me anything to stop.")

    async def cmd_heal(self, rest: str) -> None:
        spell = self.best(HEALS)
        if spell is None:
            await self.tell(f"I don't know any healing yet (a {self.cls} learns cure light at level "
                            f"{self.spells.get('cure light', '?')}).")
            return
        r = await self._cast(spell, rest.split()[0] if rest else self.master)
        await self.tell(f"Cast {spell}." if r else f"My {spell} didn't work.")

    async def cmd_buff(self, rest: str) -> None:
        cast = [s for s in BUFFS if self.best([s])]
        if not cast:
            await self.tell("I don't know armor or bless yet.")
            return
        done = [s for s in cast if await self._cast(s, self.master)]
        await self.tell(f"Cast {' and '.join(done)}." if done else "My spells didn't work.")

    async def cmd_bye(self, rest: str) -> None:
        await self.say("farewell")
        self.done = True

    # -- helpers ---------------------------------------------------------------------------------
    async def _cast(self, spell: str, target: str) -> bool:
        r = await self.bot.do(f"cast '{spell}' {target}", expect=CAST_REPLY)
        return bool(re.search(r"^Ok\.|You feel", r.text, re.M))

    async def _autoassist(self, on: bool) -> None:
        for _ in range(2):
            r = await self.bot.do("autoassist", expect=r"You will now assist when needed|Autoassist removed")
            if ("You will now assist" in r.text) == on:
                return

    async def _tend(self, now: float) -> None:
        """While following: a healer checks the group and heals whoever is low."""
        if not self.following or self.best(HEALS) is None or now - self._last_group_check < GROUP_EVERY:
            return
        self._last_group_check = now
        r = await self.bot.do("group", expect=r"group:|You have no group|isn't following")
        low = sorted((m for m in parse_group(r.text) if m.share < self.persona.heal_below), key=lambda m: m.share)
        if low and self.bot.prompt.mana >= 15:
            target = "self" if low[0].name.lower() == self.bot.name.lower() else low[0].name
            await self._cast(self.best(HEALS), target)

    async def _hunt(self) -> None:
        rep = await self.leveller.run(goal_level=self.level + 1, budget=self.hunt_budget, stop=lambda: bool(self.inbox))
        if rep.level > self.level:
            self.level = rep.level
        await self.check_epithet()
        if rep.reason.startswith("no safe targets"):  # (levels are announced by the level_up remark)
            self.mode, self.doing = "idle", "waiting for orders"
            await self.tell(f"Nothing safe left to fight at level {self.level}. Waiting for orders.")
        elif rep.deaths and not any(i == "killed_by" for i, _ in self.remarks):
            await self.tell("I died out there. Back at the temple.")
