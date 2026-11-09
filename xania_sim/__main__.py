"""``python -m xania_sim smoke``: start a test MUD, create a bot, look around, quit."""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from . import world
from .names import bot_names, mob_words
from .server import TestMud
from .session import Bot, Profile


async def smoke(port: int, existing: bool) -> None:
    runs = Path("runs") / time.strftime("%Y%m%d-%H%M%S")
    if existing:
        await _visit(port, runs)
        return
    async with TestMud(port=port) as mud:
        await _visit(mud.port, runs)


async def _visit(port: int, runs: Path) -> None:
    [name] = bot_names("smoke", 1, mob_words(world.load()))
    bot = Bot(name, "botpass1", port=port, transcript_dir=runs)
    r = await bot.enter(Profile(race="human", cls="knight"))
    print(f"{bot.name} is in ({'created' if bot.created else 'logged in'}): {r.prompt}")
    look = await bot.do("look")
    print("\n".join(look.lines[:6]))
    print((await bot.quit()).strip().splitlines()[:1])
    print(f"transcript: {bot.transcript}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="xania_sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("smoke", help="start a test MUD, create a bot, look, quit")
    s.add_argument("--port", type=int, default=9100)
    s.add_argument("--existing", action="store_true", help="use a MUD already running on --port")
    lo = sub.add_parser("lore", help="scan the game repo's skills and spells into the shared lore and show status")
    lo.add_argument("--db", default=None, help="lore database (default state/lore.db)")
    lo.add_argument("--level", type=int, default=1, help="show status for this level's band")
    lo.add_argument("names", nargs="*", help="abilities to show in detail")
    h = sub.add_parser("hunt", help="bots fight a mob on a test MUD under gdb until xania crashes; save the backtrace")
    h.add_argument("--mob", default="angry cave beast", help="mob to fight, matched in its short description")
    h.add_argument("--bots", type=int, default=4)
    h.add_argument("--minutes", type=float, default=10)
    h.add_argument("--port", type=int, default=9100)
    args = ap.parse_args()
    if args.cmd == "smoke":
        asyncio.run(smoke(args.port, args.existing))
    elif args.cmd == "lore":
        lore_cmd(args.db, args.level, args.names)
    elif args.cmd == "hunt":
        from .hunt import hunt

        r = asyncio.run(hunt(args.mob, args.bots, args.minutes, args.port))
        print(f"{r.fights} fights in {r.seconds:.0f} s, {r.errors} bot errors")
        if r.crashed:
            print(f"XANIA CRASHED. Report with backtrace: {r.report_path}\n")
            print("\n".join(r.report.splitlines()[:40]))
        else:
            print("no crash")
        for e in r.last_errors:
            print("  bot error:", e)


def lore_cmd(db: str | None, level: int, names: list[str]) -> None:
    from collections import Counter

    from .repo import GameRepo
    from .scan import scan_source
    from .store import DEFAULT_PATH, Lore, band_label, band_of

    repo = GameRepo()
    v = repo.version()
    print(f"game repo {repo.linux_path} at {v.label}")
    b = repo.build_check()
    if b.stale:
        print(f"WARNING: {b.reason}. Bots would learn from source the running game doesn't have.")
    lore = Lore(db or DEFAULT_PATH)
    diff = lore.apply_scan(v.commit, v.dirty, scan_source(repo.src_dir))
    for kind in ("new", "changed", "removed"):
        items = getattr(diff, kind)
        if items:
            print(f"{kind}: {len(items)}" + (f" ({', '.join(items[:12])}{', ...' if len(items) > 12 else ''})"))
    statuses = Counter(lore.summary(n, level).status for n in lore.abilities())
    print(f"{len(lore.abilities())} abilities; at levels {band_label(band_of(level))}: "
          + ", ".join(f"{k} {statuses[k]}" for k in ("known", "testing", "stale", "unknown") if statuses[k]))
    for n in names:
        f, s = lore.facts(n), lore.summary(n, level)
        if f is None:
            print(f"{n}: not in the source")
            continue
        learn = ", ".join(f"{c} {lv}" for c, lv in f.levels.items() if lv is not None) or "no class"
        print(f"{n}: {'spell' if f.is_spell else 'skill'}, target {f.target or '-'}, position {f.position or '-'}, "
              f"mana {f.min_mana}, lag {f.beats}; learned by {learn}; fingerprint {f.fingerprint}")
        print(f"  {band_label(s.band)}: {s.status}, {s.observations} observations"
              + (f", success {s.success_rate:.0%}" if s.success_rate is not None else "")
              + (f", mean damage {s.mean_damage:.1f}" if s.mean_damage is not None else "")
              + (f", claimed by {s.claimed_by}" if s.claimed_by else ""))
    lore.close()


if __name__ == "__main__":
    main()
