"""A companion on the real MUD: one bot plays the person, ordering a cleric companion (Bram's persona) around by
tell and chatting with it."""

import asyncio
import sqlite3

from xania_companions.companion import Companion
from xania_sim.events import parse
from xania_sim.nav import Navigator
from xania_companions.persona import roster
from xania_sim.rooms import Fingerprints
from xania_sim.session import Profile


async def test_companion_follows_groups_and_reports(new_bot, world):
    fp = Fingerprints(world)
    player = await new_bot(Profile(cls="knight"))
    heard: list[str] = []
    player.observers.append(lambda text, prompt: heard.extend(
        e.data["text"] for e in parse(text) if e.kind == "tell"))
    friend = await new_bot(Profile(cls="cleric"))
    bram = roster()["bram"]
    bram.name = friend.name
    comp = Companion(friend, world, "cleric", player.name, Navigator(friend, world, fp), persona=bram,
                     db=sqlite3.connect(":memory:"))
    task = asyncio.create_task(comp.run(seconds=120))

    async def until(pred, what, seconds=20):
        for _ in range(int(seconds / 0.5)):
            if pred():
                return
            await player.listen(0.5)  # reading the player's connection delivers the companion's tells
        raise AssertionError(f"no {what}; the player heard {heard}")

    try:
        await until(lambda: any("Tell me 'help'" in t for t in heard), "greeting")
        await player.do(f"tell {friend.name} follow", expect="You tell")
        await until(lambda: any(f"group {friend.name}" in t for t in heard), "follow reply")
        r = await player.do(f"group {friend.name}", expect="joins your group|isn't following")
        assert "joins your group" in r.text
        nav = Navigator(player, world, fp)
        start = await nav.locate()
        step = nav.plan(3001)[0]  # the first step from the Mud School entrance towards the temple
        walked = await nav.walk_to(step.to_vnum)
        assert walked.reached
        await player.do(f"tell {friend.name} status", expect="You tell")
        await until(lambda: any("Level " in t and "following" in t for t in heard), "status")
        assert comp.nav.here == nav.here != start and comp.following and comp.grouped
        n = len(heard)
        await player.do(f"tell {friend.name} where should I level?", expect="You tell")
        await until(lambda: any(a in t for t in heard[n:] for a in ("Mud School", "Midgaard", "Sewer")), "advice")
        n = len(heard)
        await player.do(f"tell {friend.name} who killed you?", expect="You tell")
        await until(lambda: any("killed me" in t.lower() or "wood" in t for t in heard[n:]), "nemesis answer")
        await player.do(f"tell {friend.name} bye", expect="You tell")
        await asyncio.wait_for(task, 20)
    finally:
        if not task.done():
            task.cancel()
