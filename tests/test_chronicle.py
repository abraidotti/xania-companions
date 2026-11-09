"""Legends from an event log: highlights, journals, epithets, the fallen, cursed places and the digest."""

from xania_sim import chronicle as C
from xania_sim.persona import plain, roster

T0 = 1_700_000_000.0


def ev(kind, at, area="Sewer", bot="Wren", **data):
    return {"bot": bot, "at": T0 + at, "kind": kind, "room": None, "area": area, "data": data}


SATURDAY = [
    ev("kill", 10, victim="A gutter rat", target="a gutter rat"),
    ev("kill", 20, victim="A gutter rat", target="a gutter rat"),
    ev("close_call", 30, hp=3, max_hp=20, against="the small spider"),
    ev("died", 40, killer="the small spider"),
    ev("group", 50, area="Midgaard", who="you", leader="Sandro"),
    ev("kill", 60, victim="A gutter rat", target="a gutter rat"),
    ev("kill", 70, victim="The small spider", target="the small spider"),
    ev("level", 80, level=5),
    ev("loot", 90, item="a rusty dagger", of="the small spider"),
]


def test_highlights_know_firsts_revenge_and_milestones():
    kinds = [h.kind for h in C.highlights(SATURDAY)]
    assert kinds == ["first_kill", "kill", "close_call", "died", "companion", "kill", "revenge", "milestone", "loot"]
    later = C.highlights([ev("kill", 100, victim="A duckling")], history=SATURDAY)
    assert [h.kind for h in later] == ["kill"]  # not a first any more


def test_a_journal_reads_like_a_day():
    wren = roster()["wren"]
    entry = C.journal(wren, SATURDAY)
    text = " ".join(entry)
    assert len(entry) >= 5 and "{" not in text
    assert "small spider" in text and "level 5" in text.lower()
    assert C.journal(wren, SATURDAY) == entry  # the same day always reads the same
    assert "3 gutter rats" in text  # the tally


def test_tally_and_plurals():
    assert C.tally(SATURDAY) == (4, "3 gutter rats and the small spider")
    assert C._plural("a fox") == "foxes" and C._plural("the fairy") == "fairies" and C._plural("a wolf") == "wolves"
    assert C._plural("a captain of the guard") == "captains of the guard"


def test_epithets():
    rats = [ev("kill", i, victim="A gutter rat", target="a gutter rat") for i in range(12)]
    assert [e.title for e in C.epithets(rats)] == ["the Ratcatcher"]
    titles = [e.title for e in C.epithets(SATURDAY + [ev("died", 200, killer="a bear")])]
    assert titles[0] == "the Avenger" and "Twice-Dead" in titles
    assert C.styled("Wren", C.epithets(rats)[0]) == "Wren the Ratcatcher"


def test_the_fallen_cursed_places_and_the_digest():
    hilda = [ev("died", 5, bot="Hilda", killer="the small spider"), ev("kill", 6, bot="Hilda", victim="A rat")]
    everything = SATURDAY + hilda
    assert [d["bot"] for d in C.fallen(everything)] == ["Wren", "Hilda"]
    assert C.cursed_places(everything) == [("Sewer", 2, 5)]  # Hilda killed there too
    sections = C.digest({"Wren": SATURDAY, "Hilda": hilda}, roster(), period="this weekend",
                        info={"Wren": {"level": 5, "cls": "mage", "epithet": "the Avenger"}})
    narrators = [n for n, _ in sections]
    assert narrators[0] == "The Chronicler" and "Wren" in narrators and "Hilda" in narrators
    assert narrators.index("Wren") < narrators.index("Hilda")  # the more eventful story first
    text = " ".join(" ".join(lines) for _, lines in sections)
    assert "Sewer" in text and "{" not in text
    assert C.digest({}, {}) == [("The Chronicler", ["Nothing stirred in Xania this weekend."])]


def test_note_lines_wrap():
    assert C._wrap("one two three four", 9) == ["one two", "three", "four"]
    assert all(len(x) <= 72 for x in C._wrap(" ".join(["word"] * 60), 72))
    assert plain("x").name == "X"


def test_legends_reach_the_dispatch(tmp_path):
    import sqlite3

    from xania_sim import dispatch as D
    from xania_sim.events import Progress, Recorder
    from xania_sim.findings import Journal
    from xania_sim.legends import gather, text
    from xania_sim.parsers import Prompt

    class Bot:
        name, prompt, observers = "Wren", None, []

    db, clock = sqlite3.connect(":memory:"), [T0]
    rec = Recorder(db, Bot(), cls="mage", level=1, area_of=lambda v: "Sewer", room=lambda: 1, clock=lambda: clock[0])
    rec.target = "the small spider"
    p = Prompt(20, 20, 100, 100, 100, 100, 0, 0, 0)
    for line in ("A gutter rat is DEAD!!", "You have been KILLED!!", "The small spider is DEAD!!"):
        clock[0] += 60
        rec.feed(line + "\n", p)
    lg = gather(db, days=3, now=clock[0] + 10)
    assert lg.info["Wren"]["epithet"] == "the Avenger"
    assert "Wren the Avenger" in text(db, "wren", 3)
    site = D.build(Journal(db), tmp_path / "site", Progress(db), legends=lg)
    chron = (site / "chronicle.html").read_text(encoding="utf-8")
    assert "Hall of the fallen" in chron and "the small spider" in chron and "Wren" in chron
    page = (site / "bots" / "wren.html").read_text(encoding="utf-8")
    assert "the Avenger" in page and "Journal" in page and "journeyman of running away" in page
    assert "chronicle.html" in (site / "index.html").read_text(encoding="utf-8")
