"""``python -m xania_companions companion``: one companion playing beside you for a while, with everything it does
recorded in Xania Sim's event log (so ``python -m xania_sim status`` shows it).

Both connect to a MUD that's already running (``--port``; 9000 is the usual one), or start an isolated test MUD
with ``--test-mud``. A bot's password is ``--password`` (default ``botpass1``); a new name creates the character.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

from xania_sim import world as W
from .companion import Companion
from xania_sim.events import Recorder
from xania_sim.fight import FightLog, MobIndex
from xania_sim.level import Leveller
from xania_sim.nav import Navigator
from .persona import Persona, plain, roster
from xania_sim.rooms import Fingerprints
from xania_sim.server import TestMud
from xania_sim.session import Bot, Profile
from xania_sim.store import Lore


async def _with_mud(test_mud: bool, port: int, play):
    if not test_mud:
        return await play("127.0.0.1", port)
    async with TestMud(port=port) as mud:
        return await play(mud.host, mud.port)


def _setup(bot: Bot, w, cls: str, race: str, lore: Lore, run_id: str):
    nav = Navigator(bot, w, Fingerprints(w))
    rec = Recorder(lore.db, bot, cls=cls, race=race, run_id=run_id, room=lambda: nav.here, area_of=W.area_namer(w))
    lev = Leveller(bot, w, cls, nav, FightLog(lore.db), MobIndex(w), recorder=rec)
    return nav, rec, lev


async def post_journal(bot: Bot, persona: Persona, lore: Lore, since: float, to: str) -> list[str]:
    """The session's journal entry, posted as a note to ``to`` (a name, "all", or "" for none). Returns it."""
    from .chronicle import journal, post_note
    from xania_sim.events import Progress

    pr = Progress(lore.db)
    entry = journal(persona, pr.timeline(bot.name, since=since), pr.timeline(bot.name, until=since))
    if entry and to and bot.conn and not bot.conn.closed:
        await post_note(bot, to, f"{bot.name}'s journal, {time.strftime('%d %b')}", entry)
    return entry


async def companion(persona: Persona, master: str, minutes: float, port: int, test_mud: bool, password: str,
                    notes: str = "master") -> None:
    name, cls, race = persona.name, persona.cls, persona.race
    w, lore = W.load(), Lore()
    runs = Path("runs") / f"companion-{time.strftime('%Y%m%d-%H%M%S')}"

    async def play(host, port):
        bot = Bot(name, password, host=host, port=port, transcript_dir=runs)  # autoloot off: it crashes debug builds (do_get)
        await bot.enter(Profile(race=race, cls=cls, sex=persona.sex))
        nav, rec, lev = _setup(bot, w, cls, race, lore, "companion")
        rec.level = await lev.level()
        rec.snapshot()
        comp = Companion(bot, w, cls, master, nav, rec.level, lev, persona=persona, db=lore.db, log=lev.log)
        print(f"{bot.name} ({race} {cls}, level {rec.level}) is in. Tell it 'help' from {master.capitalize()}. "
              f"Transcript: {bot.transcript}")
        start = time.time()
        try:
            await comp.run(seconds=minutes * 60)
            to = {"master": master, "none": ""}.get(notes, notes)
            entry = await post_journal(bot, persona, lore, start, to)
            if entry:
                print(f"\n{bot.name}'s journal" + (f" (posted as a note to {to})" if to else "") + ":\n  "
                      + "\n  ".join(entry))
        finally:
            rec.snapshot()
            with contextlib.suppress(Exception):
                await bot.quit()

    try:
        await _with_mud(test_mud, port, play)
    finally:
        lore.close()


def add_commands(sub) -> None:
    p = sub.add_parser("companion", help="a bot that follows you and takes orders by tell (tell it 'help')")
    p.add_argument("name", nargs="?", help="the bot's character name (created if new; default: the persona's)")
    p.add_argument("--persona", help="a persona from personas/ (e.g. bram, hilda, wren): name, class, voice, traits")
    p.add_argument("--master", required=True, help="your character's name: the one it takes orders from")
    p.add_argument("--notes", default="master",
                   help="post its journal as an in-game note at the end: master (default), all, none, or a name")
    p.add_argument("--cls", help="mage, cleric, knight or barbarian (default: the persona's, else cleric)")
    p.add_argument("--race", help="default: the persona's, else human")
    p.add_argument("--minutes", type=float, default=60)
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--test-mud", action="store_true", help="start an isolated test MUD on --port instead")
    p.add_argument("--password", default="botpass1")


def persona_for(args) -> Persona:
    """The persona from --persona (or one named like the bot), with --cls/--race overriding it."""
    people = roster()
    key = (args.persona or args.name or "").lower()
    if args.persona and key not in people:
        raise SystemExit(f"no persona {args.persona!r}; there are: {', '.join(sorted(people))}")
    if not key:
        raise SystemExit("give the bot a name, or --persona")
    p = people.get(key) or plain(args.name, "cleric")
    if args.name:
        p.name = args.name.capitalize()
    p.cls, p.race = args.cls or p.cls, args.race or p.race
    return p


def run(args) -> None:
    p = persona_for(args)
    asyncio.run(companion(p, args.master, args.minutes, args.port, args.test_mud, args.password, args.notes))
