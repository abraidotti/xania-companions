"""Personas, memory and dialogue: no MUD needed."""

import random
import sqlite3

from xania_sim.dialogue import LINES, Speaker, classify
from xania_sim.memory import Keeper, Memory
from xania_sim.persona import PERSONAS_DIR, load, plain, roster


def test_shipped_personas_load_and_every_line_formats():
    people = roster()
    assert {"bram", "hilda", "wren"} <= set(people)
    for p in people.values():
        assert p.cls in ("mage", "cleric", "knight", "barbarian")
        assert 0.3 <= p.flee_at <= 0.45  # survival first, whatever the bravery
        sp = Speaker(p, random.Random(1))
        for intent in set(LINES) | set(p.voice):
            for _ in range(4):
                line = sp.line(intent, master="Sandro", level=3, hp=10, max_hp=20, mob="the small spider",
                               where="Town Square", commands="follow", areas="Mud School", nemesis="a rat",
                               times="twice", mood="fine")
                assert line and "{" not in line, (p.name, intent, line)


def test_intents():
    assert classify("Where should I level?") == "where_level"
    assert classify("any good place to hunt for xp around here") == "where_level"
    assert classify("who killed you last time") == "nemesis"
    assert classify("hey there") == "greet"
    assert classify("thanks!") == "thanks"
    assert classify("you're useless") == "insult"
    assert classify("how are you doing") == "how_are_you"
    assert classify("the quick brown fox") is None


def test_lines_are_not_repeated_back_to_back():
    sp = Speaker(load(PERSONAS_DIR / "wren.toml"), random.Random(3))
    said = [sp.line("greet", master="Sandro") for _ in range(12)]
    assert all(a != b for a, b in zip(said, said[1:]))
    assert len(set(said)) >= 3  # shared lines plus Wren's own


def test_answers_use_memory_and_the_world():
    sp = Speaker(plain("Bram", "cleric"), random.Random(0))
    assert "Mud School or Midgaard" in sp.answer("where should we hunt?", level=2, areas=["Mud School", "Midgaard"])
    assert "safe" in sp.answer("where can I level", level=2, areas=[])
    assert "Nothing has killed me" in sp.answer("who killed you?", nemesis_fact=None)
    foe = {"key": "the small spider", "count": 2, "data": {"kills_me": 2, "revenge": False}}
    assert "twice" in sp.answer("who's your nemesis", nemesis_fact=foe).lower()
    assert sp.answer("blah blah") is None
    sp.fallback = lambda text, persona, slots: f"({persona.name} shrugs)"
    assert sp.answer("blah blah") == "(Bram shrugs)"


class FakeBot:
    def __init__(self):
        self.name, self.observers = "Bram", []


def test_memory_builds_nemeses_places_people_and_firsts():
    db, clock = sqlite3.connect(":memory:"), [100.0]
    mem = Memory(db, "bram", clock=lambda: clock[0])
    facts = []
    bot = FakeBot()
    target = ["the small spider"]
    Keeper(mem, bot, area=lambda: "Sewer", target=lambda: target[0], on_fact=lambda k, f: facts.append(k))
    feed = bot.observers[0]
    feed("A gutter rat is DEAD!!\nYou receive 200 experience points.\n", None)
    feed("You have been KILLED!!\n", None)
    clock[0] += 10
    feed("You have been KILLED!!\n", None)
    feed("Sandro tells you 'hi'\nYou join Sandro's group.\n", None)
    feed("The small spider is DEAD!!\n", None)
    assert facts == ["first_kill", "killed_by", "killed_by", "grouped", "revenge"]
    spider = mem.get("nemesis", "The Small Spider")
    assert spider["data"]["kills_me"] == 2 and spider["data"]["revenge"] is True
    sewer = mem.get("place", "sewer")["data"]
    assert sewer == {"kills": 2, "deaths": 2, "xp": 200}
    assert mem.get("person", "sandro")["data"] == {"talks": 1, "groups": 1}
    assert mem.get("first", "kill")["data"]["victim"] == "A gutter rat"
    assert mem.nemesis()["key"] == "the small spider"
