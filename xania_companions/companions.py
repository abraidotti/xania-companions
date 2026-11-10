"""The companions runner: a roster of bots living on your MUD, all weekend.

    python -m xania_companions companions --roster roster.toml

The roster (see ``roster.example.toml``) names the master, the MUD and each bot: its persona, whether it's a
``companion`` (takes your orders; hunts on its own while you're away) or a ``leveller``, its daily window
(``hours = "09:00-23:30"``, may wrap past midnight), a cap on hours played per day, and how long one session lasts.

Each bot is its own task: logins are staggered, a session that fails (the MUD restarting, a dropped connection)
is retried with a growing backoff, a bot that's told ``bye`` takes a break before coming back, and on Ctrl+C every
bot quits cleanly (saving its character and posting its journal). On Windows, ``keep_wsl`` holds a ``wsl.exe``
session open for as long as the runner lives, because WSL stops the distro (and the MUD) when none is attached.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("xania_sim.companions")


@dataclass
class Entry:
    persona: str
    mode: str = "companion"  # companion or leveller
    name: str | None = None  # default: the persona's name
    hours: tuple[int, int] | None = None  # daily window in minutes after midnight, (start, end); None = all day
    daily_hours: float = 6.0
    session_minutes: float = 120.0
    goal: int = 91  # levellers stop at this level
    password: str = "botpass1"
    rest_after_bye: float = 60.0  # minutes off after the master says bye


@dataclass
class Roster:
    master: str
    host: str = "127.0.0.1"
    port: int = 9000
    notes: str = "master"
    stagger_seconds: float = 45.0
    keep_wsl: bool = True
    bots: list[Entry] = field(default_factory=list)


def _window(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    a, b = (t.strip() for t in text.split("-"))

    def mins(t: str) -> int:
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    return mins(a), mins(b)


def load_roster(path: Path | str) -> Roster:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    bots = []
    for b in data.get("bot", []):
        b = dict(b)
        b["hours"] = _window(b.get("hours"))
        bots.append(Entry(**b))
    top = {k: v for k, v in data.items() if k != "bot"}
    return Roster(bots=bots, **top)


def in_window(window: tuple[int, int] | None, t: float) -> bool:
    if window is None:
        return True
    lt = time.localtime(t)
    now = lt.tm_hour * 60 + lt.tm_min
    start, end = window
    return start <= now < end if start <= end else now >= start or now < end  # a window may wrap midnight


def minutes_left(window: tuple[int, int] | None, t: float) -> float:
    if window is None:
        return float("inf")
    lt = time.localtime(t)
    now = lt.tm_hour * 60 + lt.tm_min + lt.tm_sec / 60
    end = window[1]
    return (end - now) % (24 * 60) or 24 * 60


class Runner:
    """Runs every bot in a roster. ``session(entry, minutes)`` plays one session and returns why it ended ("bye",
    "time", "goal"); it's ``play_session`` unless a test passes another, as it may ``sleep`` and ``clock``."""

    def __init__(self, roster: Roster, session=None, clock=time.time, sleep=asyncio.sleep):
        self.roster, self.clock, self.sleep = roster, clock, sleep
        self.session = session or self.play_session
        self.played: dict[tuple[str, str], float] = {}  # (bot, day) -> seconds played
        self.stopping = False
        self.status: dict[str, str] = {}

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self.clock()))

    def _name(self, e: Entry) -> str:
        return (e.name or e.persona).capitalize()

    async def run(self, until: float | None = None) -> None:
        keeper = await self._keep_wsl() if self.roster.keep_wsl else None
        tasks = [asyncio.create_task(self.bot_loop(e, i * self.roster.stagger_seconds, until))
                 for i, e in enumerate(self.roster.bots)]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            # Ctrl+C: gather has cancelled each bot once; let them quit and post their journals, without cancelling
            # them again (that would cut their goodbyes short)
            self.stopping = True
            await asyncio.wait(tasks, timeout=60)
            raise
        finally:
            self.stopping = True
            for t in tasks:
                if not t.done():
                    t.cancel()
            if keeper is not None and keeper.returncode is None:
                keeper.terminate()

    async def bot_loop(self, e: Entry, delay: float, until: float | None = None) -> None:
        name, failures = self._name(e), 0
        await self.sleep(delay)
        while not self.stopping and (until is None or self.clock() < until):
            now, key = self.clock(), (name, self._day())
            cap_left = e.daily_hours * 3600 - self.played.get(key, 0.0)
            if not in_window(e.hours, now) or cap_left <= 60:
                self.status[name] = "off duty"
                await self.sleep(60)
                continue
            minutes = min(e.session_minutes, cap_left / 60, minutes_left(e.hours, now))
            if until is not None:
                minutes = min(minutes, (until - now) / 60)
            self.status[name] = f"playing for up to {minutes:.0f} min"
            t0 = self.clock()
            try:
                why = await self.session(e, minutes)
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as ex:  # the MUD went away, a login failed...: back off and try again
                failures += 1
                wait = min(900.0, 15.0 * 2 ** failures)
                log.warning("%s: session failed (%s: %s); retrying in %.0f s", name, type(ex).__name__, ex, wait)
                self.status[name] = f"retrying in {wait:.0f} s after {type(ex).__name__}"
                self.played[key] = self.played.get(key, 0.0) + (self.clock() - t0)
                await self.sleep(wait)
                continue
            self.played[key] = self.played.get(key, 0.0) + (self.clock() - t0)
            log.info("%s: session ended (%s)", name, why)
            if why == "goal":
                self.status[name] = "reached its goal"
                return
            if why == "bye":
                self.status[name] = f"resting for {e.rest_after_bye:.0f} min"
                await self.sleep(e.rest_after_bye * 60)
            else:
                await self.sleep(30)

    async def play_session(self, e: Entry, minutes: float) -> str:
        """One real session on the roster's MUD."""
        from xania_sim import world as W
        from .companion import Companion
        from .persona import plain, roster as personas
        from .play import _setup, post_journal
        from xania_sim.session import Bot, Profile
        from xania_sim.store import Lore

        p = personas().get(e.persona.lower()) or plain(e.persona)
        if e.name:
            p.name = e.name.capitalize()
        w, lore = W.load(), Lore()
        runs = Path("runs") / f"companions-{time.strftime('%Y%m%d')}"
        bot = Bot(p.name, e.password, host=self.roster.host, port=self.roster.port, transcript_dir=runs)
        start = time.time()
        why, posted = "time", False
        to = {"master": self.roster.master, "none": ""}.get(self.roster.notes, self.roster.notes)
        try:
            await bot.enter(Profile(race=p.race, cls=p.cls, sex=p.sex))
            nav, rec, lev = _setup(bot, w, p.cls, p.race, lore, "companions")
            rec.level = await lev.level()
            rec.snapshot()
            if e.mode == "leveller":
                rep = await lev.run(goal_level=e.goal, budget=minutes * 60)
                why = "goal" if rep.level >= e.goal else "time"
            else:
                comp = Companion(bot, w, p.cls, self.roster.master, nav, rec.level, lev, persona=p, db=lore.db,
                                 log=lev.log, autonomous=True)
                await comp.run(seconds=minutes * 60)
                why = "bye" if comp.done else "time"
            await post_journal(bot, p, lore, start, to)
            posted = True
        finally:
            if not posted:  # stopped mid-session (Ctrl+C): still write the day down
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(post_journal(bot, p, lore, start, to), 30)
            with contextlib.suppress(Exception):
                rec.snapshot()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(bot.quit(), 10)
            lore.close()
        return why

    async def _keep_wsl(self):
        from xania_sim.server import DISTRO, ON_WINDOWS

        if not ON_WINDOWS:
            return None
        try:
            return await asyncio.create_subprocess_exec("wsl.exe", "-d", DISTRO, "--", "sleep", "infinity",
                                                        stdin=asyncio.subprocess.DEVNULL,
                                                        stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.DEVNULL)
        except OSError as ex:  # pragma: no cover
            log.warning("couldn't keep WSL alive: %s", ex)
            return None


def main(path: str, hours: float | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    roster = load_roster(path)
    until = time.time() + hours * 3600 if hours else None
    names = ", ".join(f"{(b.name or b.persona).capitalize()} ({b.mode})" for b in roster.bots)
    print(f"companions for {roster.master} on {roster.host}:{roster.port}: {names}. Ctrl+C to stop them all.")
    try:
        asyncio.run(Runner(roster).run(until))
    except KeyboardInterrupt:
        print("stopped; every bot quit")
