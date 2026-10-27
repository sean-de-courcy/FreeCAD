# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Scorecard of the naming scenarios and the naming corpus (ops#5, ops#506; copied from the ops
repo's scripts/scenarios/scorecard.py, which this replaces). Plain Python, no FreeCAD.

Reads the SCORE lines that PartDesignTests.TestNamingScenarios prints (one JSON record per
reference, configuration and platform) from any mix of:
- FreeCADCmd -t logs (local, `... 2>&1 | cat > log`);
- CI logs (`gh run view <id> --log --repo sean-de-courcy/FreeCAD > log`; the job prefix is skipped);
- score files (FREECAD_SCENARIO_SCORE_FILE).

`path=LABEL` relabels every record of that input's configuration (e.g. a run on official 1.1.3:
`score-113.jsonl=1.1.3`). The last record wins for the same platform, configuration, scenario and
reference.

Randomized sequences (area `randomized`, scenario `Random<seed>`, reference `<name>@<step>`) are
left out of the other tables and listed in a section of their own: per configuration, the seeds and steps
run, and every record that isn't as expected, with its edit and the replay setting.

Records of the corpus's cases (`classes` set) get a table by class, axis and set (right, loud+,
loud-, wrong, neither; notes/naming-system.md 2.2).

`--ledger <folder or file>...` tabulates ledgers alone (`Scenarios/cases/ledger/*.json`), no run
needed: the entries per module, and the same class, axis and set tables from each entry's expected
verdict on Windows (and macOS overrides apart). With `--base <folder or file>...` (another checkout's or commit's
ledgers), the entries that moved between sets: improvements, debt paid (wrong -> other) and debt
added.

Usage: python scorecard.py <input>[=LABEL]... [-o results/scorecard-<date>.md] [--title TEXT]
       python scorecard.py --ledger <folder>... [--base <folder>...] [-o FILE] [--title TEXT]
"""

import argparse
import collections
import datetime
import glob
import json
import os
import sys

VERDICTS = (
    "correct",
    "equivalent",
    "broken",
    "partial",
    "wrong",
    "partial-warned",
    "guessed",
    "guessed-wrong",
    "quiet",
    "broken-",
    "error",
    "flaky",
)
# The corpus's sets, as Scenarios/harness.py's SETS
SETS = {
    "correct": "right",
    "equivalent": "right",
    "guessed": "right",
    "quiet": "right",
    "broken": "loud+",
    "broken-": "loud-",
    "wrong": "wrong",
    "guessed-wrong": "wrong",
    "partial": "wrong",
    "partial-warned": "wrong",
    "error": "neither",
    "flaky": "neither",
}
# The verdicts that are right under an expectation kind (the ledger's `expect`), as harness.py's
# EXPECT_RIGHT
EXPECT_RIGHT = {
    "BROKEN": {"broken": 0},
    "PARTIAL": {"partial-warned": 0},
    "OWN-OR-BROKEN": {"broken": 1},
}
SET_ORDER = ("right", "loud+", "loud-", "wrong", "neither")
PLATFORMS = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}
CONFIG_ORDER = ("V2s", "V2", "V2multi", "V1", "1.1.3")


def read(path, label=None):
    records = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            at = line.find("SCORE {")
            if at < 0:
                continue
            try:
                record, _ = json.JSONDecoder().raw_decode(line[at + 6 :].strip())
            except json.JSONDecodeError:
                continue
            if label:
                record["config"] = label
            # A multi-step scenario (steps, ops#7) judges a reference after each step: keep
            # each step's verdict apart (randomized references carry their step already).
            step = record.get("step")
            if record.get("area") != RANDOM and step not in (None, "edit"):
                record["ref"] = f"{record['ref']}@{step}"
            records.append(record)
    return records


def column(record):
    return (record["config"], PLATFORMS.get(record.get("platform"), record.get("platform")))


def columnOrder(key):
    config, platform = key
    rank = CONFIG_ORDER.index(config) if config in CONFIG_ORDER else len(CONFIG_ORDER)
    return (rank, config, platform)


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def tally(records):
    """The count of each verdict, then of the records whose owner carries the solver's warning
    (ops#127: a guessed, partial or warned-tier resolution)."""
    counts = collections.Counter(r["verdict"] for r in records)
    return [counts.get(v, 0) for v in VERDICTS] + [sum(bool(r.get("warning")) for r in records)]


TALLY = list(VERDICTS) + ["warned"]


RANDOM = "randomized"


def asExpected(record):
    """As the harness's `Result.passing` (ops#127): an expected break also passes as a guess
    among its candidates, an expected partial only as partial-warned, an expected guess only
    as guessed; a plain expectation passes as correct, equivalent or guessed."""
    expect = str(record.get("expect", ""))
    verdict = {"quiet": "correct", "broken-": "broken"}.get(record["verdict"], record["verdict"])
    if expect.startswith("BROKEN"):
        return verdict in ("broken", "guessed")
    if expect.startswith("PARTIAL"):
        return verdict == "partial-warned"
    if expect.startswith("GUESSED"):
        return verdict == "guessed"
    return verdict in ("correct", "equivalent", "guessed")


def randomSection(records, columns):
    out = ["## Randomized sequences", ""]
    rows = []
    for key in columns:
        rs = [r for r in records if column(r) == key]
        if not rs:
            continue
        seeds = {r.get("seed") for r in rs}
        steps = {(r.get("seed"), r["step"]) for r in rs if r["step"] != "0"}
        failing = {r.get("seed") for r in rs if not asExpected(r)}
        rows.append([key[0], key[1], len(seeds), len(steps), len(rs)] + tally(rs)
                    + [sum(not asExpected(r) for r in rs), len(failing)])
    out += table(["Config", "Platform", "Seeds", "Steps", "Records"] + TALLY
                 + ["Not as expected", "Seeds with one"], rows) + [""]
    bad = [r for r in records if not asExpected(r)]
    out += ["Records not as expected (a sequence stops after its first step with one; "
            "replay with `FREECAD_SCENARIO_REPLAY=<seed>:<steps>`):", ""]
    if not bad:
        return out + ["None.", ""]
    bad.sort(key=lambda r: (r.get("seed") or 0, r["config"], r.get("platform") or "", r["ref"]))
    rows = []
    for r in bad[:200]:
        platform = PLATFORMS.get(r.get("platform"), r.get("platform"))
        link = f"{r.get('consumer')} -> {r.get('target')} {', '.join(r.get('subs') or []) or '-'}"
        rows.append([r.get("seed"), r["step"], f"{r['config']} {platform}",
                     (r.get("edit") or "").replace("|", "/"), r["ref"].split("@")[0],
                     r["verdict"], r.get("stored"), r.get("outcome"), link,
                     (r.get("expect") or "")[:80], (r.get("detail") or "")[:120]])
    out += table(["Seed", "Step", "Column", "Edit", "Reference", "Verdict", "Stored", "Outcome",
                  "Link", "Expected", "Detail"], rows) + [""]
    if len(bad) > 200:
        out += [f"... {len(bad) - 200} more.", ""]
    return out


def setOf(verdict, kind=None):
    if verdict in EXPECT_RIGHT.get(kind, {}):
        return "right"
    return SETS.get(verdict, "neither")


def entrySet(entry, field="expected"):
    """An entry's set under its expectation kind: an allowed set counts as its worst member."""
    value = entry.get(field, entry.get("expected"))
    values = value if isinstance(value, list) else [value]
    return max((setOf(v, entry.get("expect")) for v in values), key=SET_ORDER.index)


def setTables(items, what):
    """Tables by class and by axis of [(classes, axes, set)] items, counted by set."""
    byClass = collections.defaultdict(collections.Counter)
    byAxis = collections.defaultdict(collections.Counter)
    total = collections.Counter()
    for classes, axes, kind in items:
        for c in classes or ["-"]:
            byClass[c][kind] += 1
        for a in axes or ["-"]:
            byAxis[a][kind] += 1
        total[kind] += 1

    def rows(counts):
        return [[k, sum(n.values())] + [n.get(s, 0) for s in SET_ORDER] for k, n in sorted(counts.items())]

    out = [f"## {what} by class", ""]
    out += table(["Class", "Entries"] + list(SET_ORDER), rows(byClass) + rows({"all": total}))
    out += ["", f"## {what} by axis", ""]
    out += table(["Axis", "Entries"] + list(SET_ORDER), rows(byAxis)) + [""]
    return out


def short(names):
    if not names:
        return "-"
    return "<br>".join(f"`{n}`" for n in names)


def render(records, title, sources):
    latest = {}
    for r in records:
        latest[column(r) + (r["scenario"], r["ref"])] = r
    records = list(latest.values())
    columns = sorted({column(r) for r in records}, key=columnOrder)
    randomRecords = [r for r in records if r["area"] == RANDOM]
    records = [r for r in records if r["area"] != RANDOM]
    out = [f"# {title}", ""]
    out.append("Generated by `scripts/scenarios/scorecard.py` from:")
    out += [f"- `{s}`" for s in sources]
    out += ["", "Verdicts (`notes/scenarios.md` section 3): correct; equivalent (a different element "
            "that gives the consumer the same result); broken; partial (a split reference that kept "
            "some pieces); wrong; partial-warned (some pieces kept, with the solver's warning); "
            "guessed (a guess rule's pick, warned, that is the expected element or one of an "
            "expected break's candidates); guessed-wrong (any other guess). `warned` counts the "
            "records whose owner carries the warning.", ""]

    cases = [r for r in records if r.get("classes")]
    if cases:
        out += setTables([(r["classes"], r.get("axes"), r["verdict"]) for r in cases], "Corpus cases")

    out += ["## By configuration and platform", ""]
    rows = []
    for key in columns:
        rs = [r for r in records if column(r) == key]
        rows.append([key[0], key[1], len(rs)] + tally(rs))
    out += table(["Config", "Platform", "References"] + TALLY, rows) + [""]

    out += ["## By area", ""]
    areas = sorted({r["area"] for r in records})
    rows = []
    for area in areas:
        for key in columns:
            rs = [r for r in records if r["area"] == area and column(r) == key]
            if rs:
                rows.append([area, key[0], key[1], len(rs)] + tally(rs))
    out += table(["Area", "Config", "Platform", "References"] + TALLY, rows) + [""]

    refs = sorted({(r["area"], r["scenario"], r["ref"]) for r in records})
    byRef = collections.defaultdict(dict)
    for r in records:
        byRef[(r["area"], r["scenario"], r["ref"])][column(r)] = r

    out += ["## Every reference", ""]
    header = ["Area", "Scenario", "Reference"] + [f"{c} {p}" for c, p in columns]
    rows = []
    for key in refs:
        cells = []
        for col in columns:
            r = byRef[key].get(col)
            cells.append(r["verdict"] if r else "")
        rows.append(list(key) + cells)
    out += table(header, rows) + [""]

    differing = [k for k in refs if len({r["verdict"] for r in byRef[k].values()}) > 1]
    notCorrect = [
        k for k in refs if any(r["verdict"] not in ("correct", "equivalent") for r in byRef[k].values())
    ]
    out += ["## References whose verdict differs between configurations or platforms", ""]
    if not differing:
        out += ["None.", ""]
    for key in differing:
        out += [f"### {key[1]}.{key[2]} ({key[0]})", ""]
        rows = []
        for col in columns:
            r = byRef[key].get(col)
            if not r:
                continue
            rows.append([
                f"{col[0]} {col[1]}", r["verdict"], r.get("stored"), r.get("outcome"),
                ", ".join(r.get("subs") or []) or "-", short(r.get("names_before")),
                short(r.get("names")), short(r.get("expected_names")), r.get("detail") or "",
            ])
        out += table(["Column", "Verdict", "Stored", "Outcome", "Subs", "Name before the edit",
                      "Name after", "Expected element's name", "Detail"], rows) + [""]

    out += ["## Not correct, by configuration", ""]
    if not notCorrect:
        out += ["None.", ""]
    for key in notCorrect:
        for col, r in sorted(byRef[key].items(), key=lambda kv: columnOrder(kv[0])):
            if r["verdict"] not in ("correct", "equivalent"):
                out.append(f"- {col[0]} {col[1]}: `{key[1]}.{key[2]}` {r['verdict']} "
                           f"(stored {r.get('stored')}, outcome {r.get('outcome')}; "
                           f"{r.get('consumer')} -> {r.get('target')} {r.get('subs')}) {r.get('detail') or ''}")
    out.append("")
    if randomRecords:
        out += randomSection(randomRecords, columns)
    return "\n".join(out)


def readLedgers(paths):
    """{module: ledger} from ledger files and folders of them."""
    ledgers = {}
    for path in paths:
        files = sorted(glob.glob(os.path.join(path, "*.json"))) if os.path.isdir(path) else [path]
        for name in files:
            with open(name, encoding="utf-8") as fh:
                ledgers[os.path.splitext(os.path.basename(name))[0]] = json.load(fh)
    return ledgers


def expectedVerdict(entry, field="expected"):
    """An entry's verdict for the tables: an allowed set counts as its worst member."""
    value = entry.get(field, entry.get("expected"))
    if isinstance(value, list):
        return max(value, key=lambda v: SET_ORDER.index(setOf(v, entry.get("expect"))))
    return value


def moveKind(a, b):
    """How an entry moved from set a to set b (None: no entry)."""
    if a is None:
        return "debt added (new)" if b == "wrong" else "new"
    if b is None:
        return "removed"
    if b == "wrong":
        return "debt added"
    if a == "wrong":
        return "debt paid"
    return "improved" if SET_ORDER.index(b) < SET_ORDER.index(a) else "worse"


def renderLedger(ledgers, title, sources, base=None):
    out = [f"# {title}", "", "Generated by `scorecard.py --ledger` from:"]
    out += [f"- `{s}`" for s in sources] + [""]
    # No run header (ops decision 150): the run that wrote them is the PR's `Tier F:` line
    rows = [[module, len(ledger.get("entries", {}))] for module, ledger in sorted(ledgers.items())]
    out += ["## Ledgers", ""] + table(["Module", "Entries"], rows)
    out.append("")
    entries = {k: e for ledger in ledgers.values() for k, e in ledger.get("entries", {}).items()}
    out += setTables([(e.get("classes"), e.get("axes"), entrySet(e)) for e in entries.values()],
                     "Windows")
    mac = {k: e for k, e in entries.items() if "macos" in e}
    out += ["## macOS overrides", ""]
    out += [f"- `{k}`: {e['expected']} on Windows, {e['macos']} on macOS" for k, e in sorted(mac.items())]
    out += ([] if mac else ["None."]) + [""]
    wrong = sorted(k for k, e in entries.items() if entrySet(e) == "wrong")
    out += ["## Debt (the wrong set)", ""]
    for k in wrong:
        e = entries[k]
        accepted = f", accepted {e['accepted']}" if e.get("accepted") else ""
        out.append(f"- `{k}` {expectedVerdict(e)} ({e.get('issue') or 'no issue'}{accepted})")
    out += ([] if wrong else ["None."]) + [""]
    if base is not None:
        old = {k: e for ledger in base.values() for k, e in ledger.get("entries", {}).items()}
        moves = collections.defaultdict(list)
        for k in sorted(set(old) | set(entries)):
            a = entrySet(old[k]) if k in old else None
            b = entrySet(entries[k]) if k in entries else None
            if a != b:
                moves[moveKind(a, b)].append(f"`{k}`: {a or '-'} -> {b or '-'}")
        out += ["## Against the base", ""]
        for kind in ("debt added", "debt added (new)", "worse", "removed", "debt paid", "improved", "new"):
            out += [f"- {kind}: {len(moves[kind])}"] + [f"  - {m}" for m in moves[kind]]
        out.append("")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*")
    parser.add_argument("--ledger", nargs="+", help="tabulate ledger files or folders alone")
    parser.add_argument("--base", nargs="+", help="with --ledger: the ledgers to compare with")
    parser.add_argument("-o", "--output")
    parser.add_argument("--title")
    args = parser.parse_args()
    if args.ledger:
        title = args.title or f"Naming corpus ledger, {datetime.date.today()}"
        base = readLedgers(args.base) if args.base else None
        write(renderLedger(readLedgers(args.ledger), title, args.ledger, base), args.output)
        return
    if not args.inputs:
        parser.error("no inputs (SCORE logs or score files), and no --ledger")
    args.title = args.title or f"Naming scenarios scorecard, {datetime.date.today()}"
    records = []
    for spec in args.inputs:
        path, _, label = spec.partition("=")
        found = read(path, label or None)
        if not found:
            print(f"warning: no SCORE lines in {path}", file=sys.stderr)
        records += found
    if not records:
        sys.exit("no SCORE lines found")
    write(render(records, args.title, args.inputs), args.output)


def write(text, output):
    if output:
        with open(output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
