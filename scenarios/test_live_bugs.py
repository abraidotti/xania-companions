"""Known Xania bugs, kept as live checks: each test passes while the bug is still there and fails (telling you to
retire it) once a fix makes the crash go away. Bot defaults that work around them (autoloot off) are checked too."""

import asyncio

from xania_sim.session import Bot, Profile


async def _crashes_after(mud, bot, command) -> bool:
    try:
        await bot.do(command, timeout=5)
    except Exception:  # noqa: BLE001 - the connection may hang or close as xania dies
        pass
    for _ in range(40):
        if not mud.alive():
            return True
        await asyncio.sleep(0.25)
    return False


async def test_bots_turn_autoloot_off(new_bot):
    bot = await new_bot()
    r = await bot.do("autoloot", expect=r"Autolooting removed|Automatic corpse looting set")
    assert "Automatic corpse looting set" in r.text  # it was off: toggling turned it back on
    await bot.set_autoloot(False)


async def test_get_all_in_an_empty_room_crashes_debug_builds(mud, names):
    """act_obj.cpp do_get: 'get all' reads arg1[3] where arg1 is "all" (3 chars) when nothing is found (line 648)."""
    bot = Bot(names(), "simpass1", host=mud.host, port=mud.port)
    await bot.enter(Profile())
    crashed = await _crashes_after(mud, bot, "get all")
    report = mud.crash_report() if crashed else ""
    await bot.close()
    if crashed:
        await mud.restart()
    assert crashed, "'get all' no longer crashes xania: the bug looks fixed, retire this test"
    assert "do_get" in report and "act_obj.cpp" in report
