"""Companions against the fake MUD: orders arrive as tells (pushed unprompted), replies go out as tells."""

import asyncio

import pytest

from fake_mud import FakeMud
from test_nav import AREA, Town
from xania_explorer.areafile.world import load_world
from xania_sim.companion import Companion, command_of, parse_group
from xania_sim.nav import Navigator
from xania_sim.session import Bot, Profile


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    d = tmp_path_factory.mktemp("town") / "area"
    d.mkdir()
    (d / "area.lst").write_text("Town.are\n$\n")
    (d / "Town.are").write_text(AREA)
    return load_world(d)


def test_orders_are_read_from_tells():
    assert command_of("follow") == ("follow", "")
    assert command_of("Bram, come here!", "Bram") == ("follow", "here")
    assert command_of("HEAL hassan") == ("heal", "hassan")
    assert command_of("...") == ("", "")


def test_group_output_is_parsed():
    text = ("Hassan's group:\n[ 5 Kni] Hassan            12/  60 hp  100/ 100 mana  100/ 100 mv     0 xp\n"
            "[ 3 Cle] Bram              30/  30 hp   80/ 100 mana  100/ 100 mv   900 xp\n")
    a, b = parse_group(text)
    assert (a.name, a.level, a.hp, a.max_hp) == ("Hassan", 5, 12, 60) and a.share == 0.2
    assert b.name == "Bram" and b.share == 1.0


class Party(Town):
    """The town, plus the commands a companion uses. Hassan (the master) is standing in the temple, at low HP."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.told: list[str] = []
        self.assist = False

    def __call__(self, cmd: str):
        low = cmd.lower()
        if low.startswith("tell hassan "):
            self.commands.append(cmd)
            self.told.append(cmd[len("tell hassan "):])
            return f"You tell Hassan '{self.told[-1]}'\n\r"
        if cmd == "score":
            return "You are Bram, level 3.\n\rLevel: 3  Age: 17\n\r"
        if low == "follow hassan":
            self.commands.append(cmd)
            return "You now follow Hassan.\n\r"
        if cmd == "follow self":
            self.commands.append(cmd)
            return "You stop following Hassan.\n\r"
        if cmd == "autoassist":
            self.assist = not self.assist
            return "You will now assist when needed.\n\r" if self.assist else "Autoassist removed.\n\r"
        if cmd == "group":
            self.commands.append(cmd)
            return ("Hassan's group:\n\r[ 5 Kni] Hassan            12/  60 hp  100/ 100 mana  100/ 100 mv     0 xp\n\r"
                    "[ 3 Cle] Bram              30/  30 hp   80/ 100 mana  100/ 100 mv   900 xp\n\r")
        if cmd.startswith("cast "):
            self.commands.append(cmd)
            return "Ok.\n\r"
        return super().__call__(cmd)


async def test_a_companion_follows_heals_and_reports(world):
    async with FakeMud() as mud:
        party = mud.play = Party(mud, world)
        bot = Bot("bram", "pass123", port=mud.port)
        await bot.enter(Profile(cls="cleric"))
        comp = Companion(bot, world, "cleric", "hassan", Navigator(bot, world))
        task = asyncio.create_task(comp.run(seconds=20))

        async def until(pred):
            for _ in range(100):
                if pred():
                    return
                await asyncio.sleep(0.05)
            raise AssertionError(f"timed out; told {party.told}, commands {party.commands}")

        await until(lambda: party.told)
        assert "level 3 cleric" in party.told[0]
        mud.push("Hassan tells you 'follow'\n\r")
        await until(lambda: "follow Hassan" in party.commands and len(party.told) >= 2)
        assert party.assist and "group Bram" in party.told[1]
        mud.push("You join Hassan's group.\n\r")
        await until(lambda: any(c.startswith("cast 'cure light' Hassan") for c in party.commands))  # Hassan's at 20%
        # the master walks north: the companion follows and knows where it is
        mud.push("You follow Hassan.\n\rTown Square\n\r\n\r  A busy square.\n\r\n\r[Exits: east south west]\n\r")
        mud.push("Hassan tells you 'status'\n\r")
        await until(lambda: any("Town Square" in t for t in party.told))
        assert comp.nav.here == 3002 and comp.grouped
        mud.push("Hassan tells you 'dance'\n\r")
        await until(lambda: any("don't know 'dance'" in t for t in party.told))
        mud.push("Hassan tells you 'bye'\n\r")
        await asyncio.wait_for(task, 10)
        assert party.told[-1] == "Farewell!"
        await bot.quit()
