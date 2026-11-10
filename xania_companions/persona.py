"""Personas: who a bot is. A TOML file per character (``personas/*.toml``):

    name = "Bram"
    cls = "cleric"
    race = "human"
    sex = "m"
    home = "Midgaard"
    summary = "a soft-spoken cleric who worries about everyone"

    [traits]            # each 0..1; missing ones are 0.5
    bravery = 0.3       # how long it stays in a bad fight (flee threshold), never past survival-first limits
    chattiness = 0.7    # how often it remarks on what happens
    humour = 0.4
    loyalty = 0.9       # how readily it follows and how much it fusses over its master's HP
    greed = 0.2

    catchphrases = ["Light keep you."]

    [voice]             # extra lines per intent (dialogue.INTENTS), added to the shared ones
    greet = ["Ah, {master}. Light keep you."]

Slots in lines are filled from the moment: {master}, {me}, {level}, {cls}, {area}, {mob}, {hp}, {max_hp}, ...
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PERSONAS_DIR = Path(__file__).resolve().parents[1] / "personas"
TRAITS = ("bravery", "chattiness", "humour", "loyalty", "greed")


@dataclass
class Persona:
    name: str
    cls: str = "knight"
    race: str = "human"
    sex: str = "o"
    home: str = "Midgaard"
    summary: str = ""
    traits: dict[str, float] = field(default_factory=dict)
    voice: dict[str, list[str]] = field(default_factory=dict)
    catchphrases: list[str] = field(default_factory=list)

    def trait(self, name: str) -> float:
        return min(1.0, max(0.0, float(self.traits.get(name, 0.5))))

    @property
    def flee_at(self) -> float:
        """Flee below this share of HP: 0.45 for the timid down to 0.3 for the bravest (survival first)."""
        return 0.45 - 0.15 * self.trait("bravery")

    @property
    def heal_below(self) -> float:
        """A loyal healer tops its group up sooner."""
        return 0.4 + 0.25 * self.trait("loyalty")


def load(path: Path | str) -> Persona:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    known = {k: data[k] for k in ("name", "cls", "race", "sex", "home", "summary", "catchphrases") if k in data}
    voice = {k: list(v) if isinstance(v, list) else [v] for k, v in data.get("voice", {}).items()}
    return Persona(traits=dict(data.get("traits", {})), voice=voice, **known)


def roster(directory: Path | str = PERSONAS_DIR) -> dict[str, Persona]:
    """Every persona in a directory, by lower-case name."""
    return {p.name.lower(): p for p in (load(f) for f in sorted(Path(directory).glob("*.toml")))}


def plain(name: str, cls: str = "knight", race: str = "human") -> Persona:
    """A persona with no file: middling traits, the shared voice only."""
    return Persona(name.capitalize(), cls, race)
