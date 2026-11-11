<a id="readme-top"></a>

```text
  /    \    /    \
  \     \  /     /
   \     \/     /
    \          /  A N I A Companions
    /    /\    \
   /    /  \    \
  /    /    \    \
  \   /      \   /
```

[![Status][status-shield]][status-url]
[![License][license-shield]][license-url]
[![Python][python-shield]][python-url]

<br />
<div align="center">
  <h3 align="center">Xania Companions</h3>

  <p align="center">
    Bots that live in Xania beside you: they follow you, fight and heal with you, and write their own legends.
    <br />
    <strong>A work in progress.</strong>
    <br />
    <br />
    <a href="https://github.com/abraidotti/xania-sim">Xania Sim</a>
    &middot;
    <a href="https://github.com/abraidotti/xania-explorer">Xania Explorer</a>
  </p>
</div>

<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

## About The Project

> **Work in progress.** Xania Companions runs, but it's early: it's pinned to an older Xania Sim (v0.1) until it
> moves to Sim's current layout, the personas are a first three, and the legends are rough. Expect changes.

Running a MUD on your own is quiet. Xania Companions fills [Xania](https://github.com/mattgodbolt/xania) with a
few characters who play beside you. They:

* **follow you** and take orders by `tell`;
* **fight and heal** beside you, and level on their own while you're away, carefully;
* **remember**: their firsts, the mobs that nearly killed them, the places they won't go back to;
* **write their legends**: a journal posted as an in-game note at the end of each session, and epithets, nemeses
  and cursed places gathered over time.

Each companion has a persona with its own class, voice and temperament: Bram the worried cleric ("I keep people
standing. Someone has to."), Hilda the knight ("Shield first, questions later.") and Wren the mage ("Apprentice of
the arcane, journeyman of running away."). Their traits (bravery, chattiness, humour, loyalty, greed) shape how
long they stay in a bad fight and how readily they heal you.

They're rule-based: no language model is needed.

### Built With

* Python 3.12, standard library only
* [Xania Sim](https://github.com/abraidotti/xania-sim) for playing the game: the session, getting around, careful
  fighting and levelling, the event log
* [Xania Explorer](https://github.com/abraidotti/xania-explorer), through Sim, for the map and predictions

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Getting Started

### Prerequisites

* Python 3.12 or later
* A Xania MUD to play on: your own, on port 9000 by default, or an isolated test MUD started from a Xania build

### Installation

1. Clone this repo:
   ```sh
   git clone https://github.com/abraidotti/xania-companions.git
   cd xania-companions
   ```
2. Install it with Xania Explorer, and Xania Sim at v0.1:
   ```sh
   python -m venv .venv
   source .venv/bin/activate          # .venv\Scripts\activate on Windows
   python -m pip install "xania-explorer @ git+https://github.com/abraidotti/xania-explorer"
   python -m pip install -e ".[dev,sim]"
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Usage

One companion that follows your character (tell it `help` in the game):

```sh
python -m xania_companions companion --persona bram --master YourName
```

A roster living on your MUD on a schedule (copy `roster.example.toml` to `roster.toml` first):

```sh
python -m xania_companions companions --roster roster.toml
```

Their legends: journals, the fallen, cursed places and epithets:

```sh
python -m xania_companions chronicle
python -m xania_companions chronicle Bram --days 7
```

They connect to port 9000 unless told otherwise; `--test-mud` starts an isolated test MUD instead. Personas are
TOML files in `personas/`, so a new one is a new file.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Roadmap

- [x] Companions that follow, take orders, fight, heal and level
- [x] Personas, memory and dialogue in each one's voice
- [x] Journals as in-game notes; epithets, nemeses and cursed places
- [x] A roster that plays on a daily schedule
- [ ] Move to Xania Sim's current layout (it's pinned to v0.1)
- [ ] More personas, and companions who talk to each other
- [ ] Better legends: longer arcs across sessions

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## License

Distributed under the MIT License. See [`LICENSE`](LICENSE).

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## Acknowledgments

* [Xania](https://github.com/mattgodbolt/xania) and its developers
* [Best-README-Template](https://github.com/othneildrew/Best-README-Template), which this README follows

<p align="right">(<a href="#readme-top">back to top</a>)</p>

[status-shield]: https://img.shields.io/badge/status-work%20in%20progress-orange?style=for-the-badge
[status-url]: #about-the-project
[license-shield]: https://img.shields.io/github/license/abraidotti/xania-companions?style=for-the-badge
[license-url]: LICENSE
[python-shield]: https://img.shields.io/badge/python-3.12%2B-blue?style=for-the-badge
[python-url]: https://www.python.org/
