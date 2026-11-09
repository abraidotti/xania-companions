"""The dispatch: a static website of what runs found, to read and share.

``build(journal, out_dir)`` writes:
- ``index.html``: headlines, finding cards (new first, then by severity), and the run log;
- ``findings/<id>.html``: one page per finding (a stable link to share): what happened, how to reproduce it, a
  link to its issue, and every occurrence with its backtrace and the bots' transcript excerpts;
- ``dispatch.json``: the same data, for other tools.

Pages are plain HTML with inline CSS (light and dark), no scripts. Stories and progress charts join as those
milestones land. ``publish`` pushes the site to the repo's ``dispatch`` branch and asks GitHub to deploy it to Pages.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .findings import Journal

TITLE = "Xania Sim dispatch"
WORKFLOW = "dispatch.yml"
CSS = """
:root { --bg: #fbfaf7; --fg: #1d1d1b; --muted: #6b6a66; --card: #ffffff; --line: #e4e1da; --accent: #8a3b12;
        --high: #b42318; --medium: #b54708; --low: #475467; --code: #f3f1ec; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #161513; --fg: #ecebe7; --muted: #a3a19b; --card: #1f1e1b; --line: #34322d; --accent: #f0a46b;
          --high: #f97066; --medium: #fdb022; --low: #98a2b3; --code: #26241f; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 32px 16px 64px; }
a { color: var(--accent); }
h1 { font-size: 1.9rem; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 1.15rem; margin: 36px 0 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.sub { color: var(--muted); margin: 0 0 8px; }
.headlines li { margin: 4px 0; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; margin: 12px 0; }
.card h3 { margin: 0 0 6px; font-size: 1.05rem; }
.meta { color: var(--muted); font-size: 0.88rem; }
.badge { display: inline-block; font-size: 0.75rem; font-weight: 600; padding: 1px 8px; border-radius: 999px;
         border: 1px solid currentColor; margin-right: 6px; text-transform: uppercase; letter-spacing: 0.04em; }
.high { color: var(--high); } .medium { color: var(--medium); } .low { color: var(--low); }
.status-new { color: var(--accent); }
pre { background: var(--code); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px;
      overflow-x: auto; font-size: 0.8rem; line-height: 1.45; }
code { background: var(--code); padding: 1px 5px; border-radius: 4px; font-size: 0.9em; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
.scroll { overflow-x: auto; }
details { margin: 8px 0; } summary { cursor: pointer; color: var(--muted); }
footer { margin-top: 48px; color: var(--muted); font-size: 0.85rem; }
"""


def slug(signature: str) -> str:
    return hashlib.sha1(signature.encode()).hexdigest()[:10]


def _when(t: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""


_HOME = re.compile(r"/home/[^/\s]+/")


def _e(text) -> str:
    """HTML-escaped, with home directories shortened to ~/ (backtraces carry the builder's username)."""
    return html.escape(_HOME.sub("~/", str(text)))


def _page(title: str, body: str, root: str = "") -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{_e(title)}</title><style>{CSS}</style></head><body><main>{body}"
            f'<footer>Made by <a href="https://github.com/abraidotti/xania-sim">xania-sim</a>: bots playing '
            f'<a href="https://github.com/mattgodbolt/xania">Xania</a>. <a href="{root}index.html">Dispatch home</a>.'
            f"</footer></main></body></html>\n")


def _commit(c: str) -> str:
    return f"<code>{_e(c[:10])}</code>" if c else "unknown version"


def _card(f: dict, root: str = "") -> str:
    link = f' · <a href="{_e(f["link"])}">issue</a>' if f["link"] else ""
    seen = f'seen {f["count"]}×, first {_when(f["first_seen"])}, last {_when(f["last_seen"])} on {_commit(f["last_commit"])}'
    return (f'<div class="card"><h3><a href="{root}findings/{slug(f["signature"])}.html">{_e(f["title"])}</a></h3>'
            f'<div class="meta"><span class="badge {f["severity"]}">{f["severity"]}</span>'
            f'<span class="badge status-{f["status"]}">{f["status"]}</span>{seen}{link}</div>'
            + (f'<p>{_e(f["summary"].splitlines()[0])}</p>' if f["summary"] else "") + "</div>")


def _headlines(findings: list[dict], runs: list[dict]) -> list[str]:
    out = []
    fresh = [f for f in findings if f["status"] == "new"]
    for f in fresh[:5]:
        out.append(f'<a href="findings/{slug(f["signature"])}.html">{_e(f["title"])}</a>'
                   + (f' (seen {f["count"]}×)' if f["count"] > 1 else ""))
    if runs:
        last = runs[0]
        out.append(f'Latest run: {_e(last["title"])}, {_when(last["started"])}'
                   + (f' — {_e(_summary_text(last["summary"]))}' if last["summary"] else ""))
    if not fresh:
        out.append("No new findings.")
    return out


def _summary_text(s: dict) -> str:
    return ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in s.items() if not isinstance(v, (dict, list)))


def _index(findings: list[dict], runs: list[dict], generated: float) -> str:
    rows = "".join(
        f"<tr><td>{_when(r['started'])}</td><td>{_e(r['kind'])}</td><td>{_e(r['title'])}</td>"
        f"<td>{_commit(r['commit'])}{' (dirty)' if r['dirty'] else ''}</td><td>{_e(_summary_text(r['summary']))}</td>"
        f"<td>{''.join(f'<a href=\"findings/{slug(s)}.html\">●</a> ' for s in r['findings'])}</td></tr>"
        for r in runs)
    body = (f"<h1>{TITLE}</h1><p class='sub'>What bots found playing Xania. Updated {_when(generated)}.</p>"
            "<h2>Headlines</h2><ul class='headlines'>" + "".join(f"<li>{h}</li>" for h in _headlines(findings, runs))
            + "</ul><h2>Findings</h2>" + ("".join(_card(f) for f in findings) or "<p>None yet.</p>")
            + "<h2>Runs</h2><div class='scroll'><table><tr><th>When</th><th>Kind</th><th>Run</th><th>Game version</th>"
            f"<th>Summary</th><th>Findings</th></tr>{rows}</table></div>")
    return _page(TITLE, body)


def _finding_page(f: dict, occurrences: list[dict]) -> str:
    parts = [f"<p class='sub'><a href='../index.html'>{TITLE}</a></p><h1>{_e(f['title'])}</h1>", _card(f, "../")]
    if f["summary"]:
        parts.append(f"<h2>What happened</h2><pre>{_e(f['summary'])}</pre>")
    if f["repro"]:
        parts.append(f"<h2>Reproduce</h2><pre>{_e(f['repro'])}</pre>")
    parts.append(f"<h2>Occurrences ({f['count']})</h2>")
    for o in occurrences:
        ev = o["evidence"]
        block = [f"<div class='card'><div class='meta'>{_when(o['at'])} · run {_e(o['run'])} · {_commit(o['commit'])}</div>"]
        if ev.get("context"):
            block.append(f"<p>{_e(ev['context'])}</p>")
        if ev.get("frames"):
            block.append("<p>" + " ← ".join(f"<code>{_e(fr['func'])}</code> {_e(fr['file'])}:{fr['line']}"
                                            for fr in ev["frames"][:6]) + "</p>")
        if ev.get("backtrace"):
            block.append(f"<details><summary>Backtrace and xania's last log lines</summary><pre>{_e(ev['backtrace'])}</pre></details>")
        for name, text in (ev.get("transcripts") or {}).items():
            block.append(f"<details><summary>{_e(name)}'s transcript (last lines)</summary><pre>{_e(text)}</pre></details>")
        for line in ev.get("lines", [])[:20]:
            block.append(f"<pre>{_e(line)}</pre>")
        parts.append("".join(block) + "</div>")
    return _page(f["title"], "".join(parts), "../")


def build(journal: Journal, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "findings").mkdir(parents=True)
    findings, runs, now = journal.findings(), journal.runs(), time.time()
    (out_dir / "index.html").write_text(_index(findings, runs, now), encoding="utf-8")
    data = {"generated": now, "findings": [], "runs": runs}
    for f in findings:
        occ = journal.occurrences(f["signature"])
        (out_dir / "findings" / f"{slug(f['signature'])}.html").write_text(_finding_page(f, occ), encoding="utf-8")
        data["findings"].append(f | {"id": slug(f["signature"]), "occurrences": occ})
    (out_dir / "dispatch.json").write_text(_HOME.sub("~/", json.dumps(data, indent=1)), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("")
    return out_dir


def _git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def publish(journal: Journal, repo: Path, branch: str = "dispatch", deploy: bool = True) -> str:
    """Build the site, commit it as the only content of ``branch`` (history kept, one commit per publish), push,
    and run the Pages workflow. Returns the pushed commit."""
    repo = Path(repo)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "site"
        _git(repo, "fetch", "-q", "origin", branch, check=False)
        exists = bool(_git(repo, "ls-remote", "--heads", "origin", branch, check=False))
        _git(repo, "worktree", "add", "-q", "--detach", str(work))
        try:
            if exists:
                _git(work, "checkout", "-q", "-B", branch, f"origin/{branch}")
            else:
                _git(work, "checkout", "-q", "--orphan", branch)
            _git(work, "rm", "-rq", "--ignore-unmatch", ".")
            site = build(journal, Path(tmp) / "build")
            for p in site.iterdir():
                dest = work / p.name
                shutil.copytree(p, dest) if p.is_dir() else shutil.copy2(p, dest)
            _git(work, "add", "-A")
            if _git(work, "status", "--porcelain"):
                _git(work, "commit", "-q", "-m", f"Dispatch {time.strftime('%Y-%m-%d %H:%M')}")
            commit = _git(work, "rev-parse", "HEAD")
            _git(work, "push", "-q", "origin", f"HEAD:{branch}")
        finally:
            _git(repo, "worktree", "remove", "--force", str(work), check=False)
    if deploy:
        subprocess.run(["gh", "workflow", "run", WORKFLOW, "--repo", _origin_slug(repo)], check=True,
                       capture_output=True)
    return commit


def _origin_slug(repo: Path) -> str:
    url = _git(repo, "remote", "get-url", "origin")
    tail = url.split("github.com", 1)[1].lstrip(":/")
    return tail[:-4] if tail.endswith(".git") else tail
