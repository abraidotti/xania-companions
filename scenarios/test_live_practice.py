"""Practice on the real MUD: a new knight finds a practice mob near the temple and spends its sessions."""

from xania_sim.nav import Navigator
from xania_sim.rooms import Fingerprints
from xania_sim.session import Profile
from xania_sim.trainer import practise


async def test_new_knight_practises(new_bot, world):
    bot = await new_bot(Profile(cls="knight"))
    nav = Navigator(bot, world, Fingerprints(world))
    rep = await practise(bot, nav, world, "knight")
    assert rep.sessions_before > 0, rep
    assert rep.reason == "done" and rep.sessions_left == 0 and "sword" in rep.practised, rep
