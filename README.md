# Xania Companions

Rule-based companion bots for the [Xania](https://github.com/mattgodbolt/xania) MUD. They live in the world while
you play: they follow you, take orders by `tell`, heal and fight beside you, level when you're away, and write their
own legend (journals posted as in-game notes, nemeses, epithets, cursed places). No LLM needed.

Built on [Xania Sim](https://github.com/abraidotti/xania-sim), which provides the telnet session, navigation,
survival-first fighting and levelling, the event log and the test MUD. This code was split out of Xania Sim so that
Sim stays a testing tool; the history before the split is Sim's.

## Setup

Python 3.12+, with sibling checkouts of xania-explorer and xania-sim:

```
pip install -e ../xania-explorer -e ../xania-sim -e .[dev]
```

## Commands

| Command | What it does |
|---|---|
| `python -m xania_companions companion NAME --master YOU [--persona bram]` | One companion that follows you; tell it `help` |
| `python -m xania_companions companions --roster roster.toml [--hours N]` | A roster living on your MUD on a schedule (copy `roster.example.toml`) |
| `python -m xania_companions chronicle [bot] [--days 3]` | The legends: journals, the fallen, cursed places, epithets |

They connect to your MUD on port 9000 by default; `--test-mud` starts an isolated test MUD instead. Progress goes
into Xania Sim's event log, so `python -m xania_sim status` shows the companions too.

## Personas

Each companion is a TOML file in `personas/` (Bram, Hilda and Wren to start): class, race, a summary, traits
(bravery, chattiness, humour, loyalty, greed) and extra lines per intent in its own voice. Bravery sets how long it
stays in a bad fight, within survival-first limits; loyalty sets how readily it heals you.

## Modules

| Module | What it does |
|---|---|
| `companion.py` | Orders by tell, following, autoassist, healing the group, remarks |
| `companions.py` | The roster runner (play windows, journals posted at the end) |
| `persona.py`, `personas/` | Who each bot is |
| `memory.py` | What a bot remembers (firsts, nemeses) |
| `dialogue.py` | Intent templates in each persona's voice |
| `chronicle.py`, `legends.py` | Journals, epithets, the fallen, cursed places, the digest |
| `play.py` | The `companion` command |

## Licence

MIT.
