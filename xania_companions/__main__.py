"""``python -m xania_companions``: companion bots for Xania, built on Xania Sim.

- ``companion NAME --master YOU``: one companion that follows you and takes orders by tell
- ``companions --roster roster.toml``: a roster living on your MUD on a schedule
- ``chronicle [bot]``: the legends: journals, the fallen, cursed places, epithets
"""

from __future__ import annotations

import argparse

from . import play


def main() -> None:
    ap = argparse.ArgumentParser(prog="xania_companions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    play.add_commands(sub)
    co = sub.add_parser("companions", help="a roster of bots living on your MUD (see roster.example.toml)")
    co.add_argument("--roster", default="roster.toml")
    co.add_argument("--hours", type=float, help="stop after this many hours (default: run until Ctrl+C)")
    ch = sub.add_parser("chronicle", help="the legends: a digest of every bot's journal, the fallen, cursed places")
    ch.add_argument("bot", nargs="?", help="just this bot: its journal day by day, epithets and nemeses")
    ch.add_argument("--days", type=float, default=3, help="how far back (default 3 days)")
    args = ap.parse_args()
    if args.cmd == "companion":
        play.run(args)
    elif args.cmd == "companions":
        from .companions import main as companions_main

        companions_main(args.roster, args.hours)
    elif args.cmd == "chronicle":
        from xania_sim.store import Lore

        from . import legends

        lore = Lore()
        try:
            print(legends.text(lore.db, args.bot, args.days))
        finally:
            lore.close()


if __name__ == "__main__":
    main()
