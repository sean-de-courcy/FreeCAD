# SPDX-License-Identifier: LGPL-2.1-or-later
"""Writes a generation's delta files (beta-compatibility 3.5) from a gate run's report: the
intended changes of a `compat-change` or `compat-neutral` PR, one `<gen>/<model>.delta.json` per
model that changed, each float the gate found changed with the record's old value and this
build's new one.

    1. Run the gate on the PR's build with FREECAD_COMPAT_REPORT=<report>: every pass that
       differs dumps `<label>.<pass>.<stem>.expected.json` and `.actual.json` there.
    2. python make_delta.py <report> <corpus> --issue ops#n --label compat-change
           --approved "<who, when>" --why "<the change>" [--rel 1e-9]
       (<corpus> is the folder holding gen<k>/; CompatRecord.py must be importable: run it with
       src/Mod/Part on PYTHONPATH, or from the build's Mod/Part folder.)
    3. Rerun the gate: it must pass. Review every entry: a delta is a result change the user sees.

A change that isn't a float (a name, a count, a type) can't be a delta: it is printed and the
script exits 1. An entry found in several passes must agree within its tolerance; the recompute
pass's (against the saved record) is kept. Windows and macOS halves: each half's delta takes its
own old values from its own report, so run the gate over both halves (the corpus holds them) and
the new values, one build's, hold on the other platform within --rel (CompatRecord.DELTA_TOLERANCE).
"""

import argparse
import json
import os
import re
import sys

import CompatRecord

REPORT = re.compile(
    r"(?P<gen>gen\d+(?:-macos)?)-(?P<model>.+)-(?P<order>ordered|alone)"
    r"\.(?P<pass>open|recompute|roundtrip)\.(?P<stem>[^.]+)\.expected\.json"
)
PREFERRED = {"recompute": 0, "roundtrip": 1, "open": 2}


def collect(report, rel):
    """{gen: {model: {stem: {where: entry}}}} and the lines that can't be deltas."""
    found, problems = {}, []
    for fileName in sorted(os.listdir(report)):
        m = REPORT.fullmatch(fileName)
        if not m:
            continue
        expected = CompatRecord.load(os.path.join(report, fileName))
        actual = CompatRecord.load(
            os.path.join(report, fileName.replace(".expected.json", ".actual.json"))
        )
        stage = "recompute" if m["pass"] != "open" else "open"
        entries, others = CompatRecord.deltaEntries(expected, actual, stage, rel)
        problems += [f"{fileName}: {line}" for line in others]
        stems = found.setdefault(m["gen"], {}).setdefault(m["model"], {})
        held = stems.setdefault(m["stem"], {})
        for where, entry in entries.items():
            entry["pass"] = m["pass"]
            entry["seen"] = {m["pass"]}
            known = held.get(where)
            if known is None:
                held[where] = entry
                continue
            entry["seen"] |= known["seen"]
            known["seen"] |= entry["seen"]
            for key in ("old", "new"):
                a, b = known[key], entry[key]
                # FreeCAD-CH (ops#683, c768): an absolute floor beside the relative tolerance, so
                # a quaternion's 0 and 6e-17 agree
                floor = max(entry.get("abs", 0.0), CompatRecord.DELTA_TOLERANCE[1])
                if abs(a - b) > max(floor, rel * max(abs(a), abs(b))):
                    problems.append(f"{fileName}: {where}'s {key} {b} differs from {known['pass']}'s {a}")
            if PREFERRED[entry["pass"]] < PREFERRED[known["pass"]]:
                held[where] = entry
    return found, problems


def entryOf(e):
    """A delta file's entry. A change the open pass didn't see (a recompute changes what the file
    holds, as C2's frames do: ops#683) holds only in the passes that saw it (`deltasFor`)."""
    out = {k: e[k] for k in ("old", "new", "rel", "abs") if k in e}
    if "open" not in e["seen"]:
        out["passes"] = sorted(e["seen"])
    return out


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("report")
    parser.add_argument("corpus")
    parser.add_argument("--issue", required=True)
    parser.add_argument("--label", required=True, choices=("compat-change", "compat-neutral"))
    parser.add_argument("--approved", required=True)
    parser.add_argument("--why", required=True)
    parser.add_argument("--rel", type=float, default=CompatRecord.DELTA_TOLERANCE[0])
    args = parser.parse_args(argv)
    found, problems = collect(args.report, args.rel)
    for line in problems:
        print("not a delta:", line)
    if problems:
        return 1
    for gen, models in sorted(found.items()):
        for model, stems in sorted(models.items()):
            changes = {
                stem: {where: entryOf(e) for where, e in sorted(held.items())}
                for stem, held in sorted(stems.items())
                if held
            }
            if not changes:
                continue
            path = os.path.join(args.corpus, gen, model + ".delta.json")
            if os.path.exists(path):
                print(f"{path} exists: merge by hand")
                return 1
            body = {
                "format": 1,
                "issue": args.issue,
                "label": args.label,
                "approved": args.approved,
                "why": args.why,
                "changes": changes,
            }
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(body, fh, indent=1, sort_keys=True)
                fh.write("\n")
            print(path, sum(len(v) for v in changes.values()), "entries")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
