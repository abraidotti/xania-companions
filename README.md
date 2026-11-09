# Xania Sim

Bots that play [Xania](https://github.com/mattgodbolt/xania) over telnet. They're for three things:

- **Company**: characters who live in the world while you play (in progress; see the roadmap).
- **Finding bugs**: bots play the real game and do what players do, so they run into crashes and oddities that
  nobody would find by reading code. A crash comes back as a report with a source-level backtrace.
- **Testing features**: scripted scenarios that check new skills, spells, areas and systems on the real game.

Bots never touch your real game: tests and hunts run on their own isolated MUD, with its own players.

It works alongside [Xania Explorer](../xania-explorer): Explorer reads the area files and C++ tables and predicts
what should happen; the bots check what does happen. xania-sim imports Explorer's API (`xania_explorer.api`) for the
map, names and predictions. Explorer never imports xania-sim.

## Setup

1. Xania built in WSL (Windows) or Linux: a checkout at `~/xania` with `make` run in it. See Xania's README.
2. Install this package and Explorer from the sibling checkout:

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (source .venv/bin/activate elsewhere)
python -m pip install -e ".[dev]" -e ../xania-explorer    # with Explorer checked out next to this repo
python -m pip install -e ".[dev,explorer]"                # or: Explorer straight from GitHub
```

Settings (environment variables): `XANIA_SIM_DISTRO` (the WSL distro, default `Ubuntu-26.04`) and `XANIA_SIM_XANIA`
(the checkout as a Linux path, default `$HOME/xania`).

## Try it

```
python -m xania_sim smoke                 # starts a test MUD on port 9100, creates a bot, looks, quits
python -m xania_sim smoke --port 9000 --existing   # the same against a MUD you already have running
python -m pytest                          # unit tests + live scenarios (1-3 min; the MUD takes ~12 s to boot)
python -m pytest -m "not live"            # unit tests only (a fake MUD, no Xania needed)
python -m pytest -m "not slow"            # skip scenarios that wait for regen ticks
```

Every bot writes a full transcript (`<` received, `>` sent) to `runs/<timestamp>/<Name>.log`.

## Finding bugs

The test MUD runs xania under gdb when gdb is installed in WSL (`sudo apt install gdb`), so if xania crashes, the
report shows the signal, the last lines xania logged, and a backtrace with source files and line numbers. gdb only
watches: no breakpoints, signals pass straight through. `XANIA_SIM_GDB=0` turns it off.

- **During tests**: a crash fails the test that caused it, with the backtrace, and the MUD restarts (players kept)
  so the rest of the run carries on.
- **On purpose**: `hunt` has bots repeat one risky activity until xania crashes or time runs out, then saves the
  report:

```
python -m xania_sim hunt --mob "angry cave beast" --bots 4 --minutes 10
# 4 fights in 75 s ... XANIA CRASHED. Report with backtrace: runs/hunt-.../xania-crash.txt
```

What the first hunt found: any character with autoloot (on for new players) who kills a mob with something on it
crashes debug builds of xania. Autoloot runs `get all corpse` (`loot_and_sacrifice_corpse`, src/fight.cpp:565),
and `do_get` (src/act_obj.cpp:707) passes `arg1[3]` where `arg1` is the 3-character `"all"`: C-era code reading a
string terminator that a `std::string_view` doesn't have. Typing `get all` in an empty room does the same (line
648). Release builds don't crash, but read the next character instead, so the guard against looting undroppable
items with `get all` never applies. Filed as [abraidotti/xania#1](https://github.com/abraidotti/xania/issues/1);
bots turn autoloot off until it's fixed, and `scenarios/test_live_bugs.py` keeps checking it (it fails, telling you
to retire it, once the crash is gone).

## Shared lore

```
python -m xania_sim lore                  # scan the game repo's skills/spells into the shared lore; show what changed
python -m xania_sim lore fireball --level 25   # one ability's facts, fingerprint and status for a level band
```

The lore is shared by all bots: what the source says about each skill and spell, plus what bots observe when they
use them. Each ability is fingerprinted (its skill-table entry and spell function, comments and spacing ignored),
so a new or rebalanced spell shows up as new or changed and only its observations start over. Bots claim an
ability and level band before experimenting, so the work isn't duplicated.

## Writing a scenario

Scenarios are pytest tests in `scenarios/`. The fixtures start one test MUD per session and make bots on it:

```python
from xania_sim import Profile

async def test_mage_starts_with_magic_missile(new_bot):
    bot = await new_bot(Profile(race="elf", cls="mage"))
    r = await bot.do("spells")
    assert r.has("magic missile")
```

- `bot.do(command)` sends one command and returns a `Response` with `text`, `lines`, `has(regex)` and the
  `prompt` that ended it (hp, mana, moves with maxima, xp, gold and wait state). Long output is paged through.
- The rule behind it: one command at a time, then wait for the prompt. Bots set the prompt `<bot ...>` when they
  log in, so the end of each command's output is unambiguous. Sending faster would trip Xania's input-flood kick.
  The MUD also prompts on its own (regen ticks, combat rounds, other players), so pass `expect=` (a regex the
  reply must contain) when it matters: `bot.do("north", expect=r"^\[Exits:|Alas")` reads past stray prompts
  until the real reply arrives, and returns `complete=False` if it never does.
- Getting around: `Navigator(bot, world, avoid=danger_rooms(world, level))` gives `locate()`, `walk_to(vnum)` and
  `explore(area)`. Routes come from Explorer's map; rooms are recognised as the bot arrives (name, first line of
  description, exits, plus where the move should have led, since about 600 room names are shared); locked doors and
  other refusals are routed around; tiredness means a rest; a lost bot recalls to the temple.
- Names: the MUD refuses names that match a mob keyword. The `names` fixture (and `xania_sim.names.bot_names`)
  hands out acceptable ones.

## How it fits together

| Module | What it does |
|---|---|
| `telnet.py` | Connection to doorman: refuses telnet options, strips ANSI, `expect(pattern)` / `send(line)`, transcript |
| `session.py` | `Bot`: the lobby (create or log in, as in `nanny`, xania/src/MudImpl.cpp), then `do(command)` |
| `parsers.py` | Pure parsing (the bot prompt, lines); tested against captured output |
| `server.py` | `TestMud`: its own doorman + xania on its own port with a throwaway data dir (`/tmp/xania-sim/<port>`) |
| `names.py` | Names the MUD accepts (`validate_player_name`) |
| `world.py` | Explorer's world, loaded from the checkout the test MUD runs (in WSL, via `\\wsl.localhost\...`) |
| `rooms.py` | Parsing room views (`room_look`, act_info.cpp) and recognising rooms by fingerprint |
| `repo.py` | `GameRepo`: the game's git repo (`XANIA_SIM_XANIA`): commit, dirty state, is the build older than the source |
| `scan.py` | Skills/spells from the repo's source (levels via Explorer; entry text, target, position read here) + fingerprints |
| `store.py` | `Lore`: shared SQLite (`state/lore.db`): abilities and their changes, raw observations, claims, status per band |
| `nav.py` | `Navigator`: where am I, safe routes (`danger_rooms` from aggressive spawns + `predict_fight`), walking, exploring |

On Windows the MUD runs in WSL. WSL stops a distro once no `wsl.exe` session is attached, so `TestMud` keeps
its start script in the foreground for as long as the server should live.

## Roadmap

The goal: companion bots with agency in the world, who play alongside you, are tracked over time, and write
their own legend (journals, nemeses, epithets). No LLM needed; there's an optional hook for one later.

- **M1 (done)**: telnet, lobby, prompt, isolated test MUD, smoke scenarios (now the regression suite).
- **M2 (done)**: navigation with Explorer's map (`locate`, `walk_to`, `explore(area)`), danger-aware.
- **M3a (done)**: the game repo (version, build check), skill/spell scan with fingerprints, shared lore (SQLite).
- **M3**: survival and levelling: pick safe fights with `api.predict_fight`, rest, flee, recall, train.
- **M4**: event log (SQLite), `xania_sim status` and an HTML progress report beside Explorer's predictions.
- **M5**: companionship: follow, group, assist, heal, party commands by `tell`.
- **M6**: personalities, memory and dialogue (utility AI, intent templates, event-driven chatter).
- **M7**: legends: journals posted as in-game notes, nemeses, epithets, cursed places, a weekend digest.
- **M8**: the companions runner (a roster all weekend on your MUD), then the Raspberry Pi.
