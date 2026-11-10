"""The roster runner with a fake clock and fake sessions: windows, daily caps, backoff, byes and goals."""

import asyncio
import time
from pathlib import Path

from xania_companions.companions import Entry, Roster, Runner, in_window, load_roster, minutes_left

MIDNIGHT = time.mktime((2026, 11, 7, 0, 0, 0, 0, 0, -1))  # a Saturday, local time


def at(h, m=0):
    return MIDNIGHT + h * 3600 + m * 60


def test_the_example_roster_loads():
    r = load_roster(Path(__file__).resolve().parents[1] / "roster.example.toml")
    assert r.master == "Sandro" and r.port == 9000 and [b.persona for b in r.bots] == ["bram", "hilda", "wren"]
    assert r.bots[0].hours == (8 * 60, 23 * 60 + 30) and r.bots[1].hours == (600, 120) and r.bots[2].hours is None


def test_windows_wrap_midnight():
    w = (22 * 60, 2 * 60)
    assert in_window(w, at(23)) and in_window(w, at(1)) and not in_window(w, at(12))
    assert minutes_left(w, at(23)) == 180 and minutes_left((600, 720), at(11, 30)) == 30
    assert in_window(None, at(4))


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s
        await asyncio.sleep(0)


def runner(entries, outcomes, clock):
    """Sessions take their allotted minutes (or fail) per ``outcomes``: a list of "time", "bye", "goal" or "fail"."""
    calls = []

    async def session(e, minutes):
        calls.append((e.persona, round(minutes), time.strftime("%H:%M", time.localtime(clock()))))
        what = outcomes.pop(0) if outcomes else "time"
        if what == "fail":
            clock.t += 5
            raise ConnectionError("the MUD went away")
        clock.t += minutes * 60
        return what

    r = Runner(Roster("Sandro", keep_wsl=False, stagger_seconds=0, bots=entries), session, clock, clock.sleep)
    return r, calls


def test_sessions_respect_the_window_and_the_daily_cap():
    clock = Clock(at(7, 30))
    e = Entry("bram", hours=(8 * 60, 12 * 60), daily_hours=3, session_minutes=120)
    r, calls = runner([e], [], clock)
    asyncio.run(r.bot_loop(e, 0, until=at(13)))
    assert [c[0] for c in calls] == ["bram", "bram"]
    assert calls[0][2] == "08:00" and calls[0][1] == 120  # waited for the window to open
    assert calls[1][1] <= 60  # the last hour of the cap
    assert sum(c[1] for c in calls) <= 180


def test_failures_back_off_and_bye_rests_and_goal_stops():
    clock = Clock(at(9))
    e = Entry("wren", session_minutes=30, rest_after_bye=60)
    r, calls = runner([e], ["fail", "fail", "bye", "goal"], clock)
    asyncio.run(r.bot_loop(e, 0, until=at(20)))
    times = [c[2] for c in calls]
    assert len(calls) == 4 and r.status["Wren"] == "reached its goal"
    # 30 s then 60 s of backoff after the failures; an hour off after the bye
    assert times[:3] == ["09:00", "09:00", "09:01"] and times[3] == "10:31"  # 09:01:40 + 30 min + 60 min


def test_stopping_lets_every_bot_finish_its_goodbye():
    cleaned = []

    async def session(e, minutes):
        try:
            await asyncio.sleep(3600)
        finally:
            await asyncio.sleep(0.05)  # quitting and posting the journal take a moment
            cleaned.append(e.persona)

    async def main():
        r = Runner(Roster("Sandro", keep_wsl=False, stagger_seconds=0, bots=[Entry("bram"), Entry("hilda")]), session)
        task = asyncio.create_task(r.run())
        await asyncio.sleep(0.05)
        task.cancel()  # Ctrl+C
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(main())
    assert sorted(cleaned) == ["bram", "hilda"]
