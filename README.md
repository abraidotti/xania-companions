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

## Reading and sharing what runs found: the dispatch

Hunts and live test sessions record themselves (runs and findings) in the lore database. A finding is one problem
however often it's seen: a crash is identified by its signal and the first function in Xania's own source, so the
`get all` and autoloot triggers above are one finding with two kinds of occurrence. xania's own `[*****] BUG:` log
lines become findings too. Each keeps every occurrence (when, which game commit, backtrace, the bots' last
transcript lines), a way to reproduce it, a status and an optional issue link.

```
python -m xania_sim report                          # latest runs and findings in the terminal
python -m xania_sim findings do_get --link https://github.com/abraidotti/xania/issues/1
python -m xania_sim findings do_get --status known  # new | known | ignored (new ones lead the headlines)
python -m xania_sim dispatch                        # build the website locally (build/dispatch/index.html)
python -m xania_sim publish                         # push it to the dispatch branch and deploy to GitHub Pages
```

The published dispatch is at **https://abraidotti.github.io/xania-sim/**: headlines, a card per finding (each
with its own page, a stable link to share), and the run log. `publish` commits the site to the `dispatch` branch
(never to `main`) and runs the [Dispatch workflow](.github/workflows/dispatch.yml), which deploys it. Only test
MUD runs are recorded, and home directories in backtraces are shortened to `~/`.

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

## Companions and levelling bots

```
python -m xania_sim companion --persona bram --master Sandro    # Bram, a cleric, joins your MUD (port 9000) for an hour
python -m xania_sim companion --persona wren --master Sandro --minutes 180
python -m xania_sim companion Zed --cls knight --master Sandro  # no persona file: middling traits, the shared voice
python -m xania_sim level Hilda --goal 5                     # a knight that levels on its own, survival first
python -m xania_sim level Hilda --test-mud --port 9100       # the same on an isolated test MUD
```

A companion greets you by tell and takes orders the same way (`tell Bram follow`): `follow`, `stay`, `status`,
`home`, `rest`, `hunt`, `heal`, `buff`, `help`, `bye`. Once it follows you, `group Bram` and it fights beside you
(autoassist); a healer checks the group and casts its best cure on whoever drops below half their HP. `hunt` sends
it levelling on its own until you tell it anything else. Bots log in with the password `botpass1` unless you pass
`--password`; a new name creates the character.

Anything else you tell it is answered in its own voice: greetings, thanks, insults, "how are you?", "who are
you?", "tell me a joke", "where should I level?" (an accurate answer: the areas where its safe targets spawn at
its level) and "who killed you?" (from its memory). It also remarks on what happens to it, as often as its
chattiness says: levels, its first kill, close calls, deaths, and revenge on whatever killed it.

Personas live in [personas/](personas/) as TOML: name, class, race, a one-line summary, catchphrases, traits
(bravery sets its flee threshold, between 45% and 30% of HP; loyalty how soon it heals the group; chattiness how
often it talks) and extra lines per intent. Three ship: Bram (a worried cleric), Hilda (a terse knight) and Wren
(a chatty, cowardly mage). What a bot remembers (people, places, nemeses, firsts) stays in the lore database
between sessions.

Levelling is survival first: a bot only starts fights predicted (by Explorer, then by the shared fight log once bots
have seen enough) to cost well under half its HP, skips rooms where others could join in, flees early (standing up
first if it's been tripped or bashed), rests at the temple, and never goes back to a room it fled from.

## Progress: what each bot has done

```
python -m xania_sim status                # every bot: level, xp, gold, kills, deaths, flees, hours played
python -m xania_sim status lvlknia        # one bot's areas and recent events too
```

Everything a bot reads is parsed into events (kills, deaths with their killer, xp, levels, skill gains, loot, gold,
tells, says, channels, follows, groups; the messages are Xania's own, with file:line in `events.py`) and stored
with the room and area it happened in, next to prompt snapshots (HP, mana, moves, xp, gold) taken as they change.
The dispatch gets a bots table and a page per bot: level over time, where it fought, what it did lately, and its
fights beside Explorer's predictions (`fight.compare`). The tables (`bots`, `events`, `snapshots`, `fights`) are
plain SQLite in `state/lore.db`, for other tools to read.

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
| `fight.py` | Recognising mobs in a room, `safe_targets`, `fight()` round by round, `recover()`, the shared `FightLog`, `compare` |
| `level.py` | `Leveller`: go where the safe fights are, fight one at a time, rest, flee and never go back |
| `companion.py` | `Companion`: orders by tell, follow/group/autoassist, healing the group, status reports, hunting |
| `persona.py` | Personas from TOML: traits, voice lines, catchphrases; the flee and heal thresholds they imply |
| `memory.py` | `Memory` (facts per bot: people, places, nemeses, firsts) and `Keeper`, which builds them from events |
| `dialogue.py` | Intents from what's said, voiced lines without repeats, event reactions, levelling advice; an off-by-default LLM hook |
| `play.py` | The `companion` and `level` commands: one bot playing for a while, recorded in the event log |
| `events.py` | `parse(text)` into events, `Recorder` (watches a bot, stores events + snapshots), `Progress` (reads them) |
| `nav.py` | `Navigator`: where am I, safe routes (`danger_rooms` from aggressive spawns + `predict_fight`), walking, exploring |

On Windows the MUD runs in WSL. WSL stops a distro once no `wsl.exe` session is attached, so `TestMud` keeps
its start script in the foreground for as long as the server should live.

## Roadmap

The goal: companion bots with agency in the world, who play alongside you, are tracked over time, and write
their own legend (journals, nemeses, epithets). No LLM needed; there's an optional hook for one later.

- **M1 (done)**: telnet, lobby, prompt, isolated test MUD, smoke scenarios (now the regression suite).
- **M2 (done)**: navigation with Explorer's map (`locate`, `walk_to`, `explore(area)`), danger-aware.
- **M3a (done)**: the game repo (version, build check), skill/spell scan with fingerprints, shared lore (SQLite).
- **M3 (done)**: survival and levelling: pick safe fights with `api.predict_fight`, rest, flee, recall.
- **M4 (done)**: event log (SQLite), `xania_sim status`, progress pages on the dispatch beside Explorer's predictions.
- **M5 (done)**: companionship: follow, group, assist, heal, party commands by `tell`.
- **M6 (done)**: personas, memory and dialogue (intent templates in each persona's voice, event-driven remarks).
- **M7**: legends: journals posted as in-game notes, nemeses, epithets, cursed places, a weekend digest.
- **M8**: the companions runner (a roster all weekend on your MUD), then the Raspberry Pi.
