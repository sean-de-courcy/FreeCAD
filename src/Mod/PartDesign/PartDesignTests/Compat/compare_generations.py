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

"""Compares two generations of the CI reopen corpus (FreeCAD-CH ops#418, notes/beta-compatibility.md
3.9). Plain Python, no FreeCAD: run it with any Python 3.

    python compare_generations.py <old gen folder> <new gen folder> [--strict]

Exit 0: no difference. Exit 1: a difference (or, with --strict, a known flake). Exit 2: a
generation can't be read (a missing or corrupt MANIFEST, oracle or FCStd: the message says which).

A regeneration changes by itself the MANIFEST's `build`, `date` and file hashes, every object `id`
and the assemblies' `Uid`s, and the saved files' timestamps, so those are ignored. What is compared:
the MANIFEST's format, generation, platform, fork release, naming revision, models (with their
documents in open order) and file list, every value of every oracle, and each FCStd's member names
and its objects (type and name, in order). Not each FCStd's whole Document.xml: it holds the object
ids inside the name tables, UUIDs and dates, which change in every regeneration.

KNOWN_FLAKES are differences seen between two runs of the same build; they are reported as such and
don't fail the comparison, unless --strict. A flake also has a guard on the two whole oracles: the
differences count as the flake only if the guard holds.
"""

import json
import os
import re
import sys
import zipfile

IGNORED_KEYS = {"id", "Uid", "date", "build"}
MANIFEST_FIELDS = ("format", "generation", "platform", "forkRelease", "namingRevision", "models")

_OBJECT = re.compile(r'<Object type="([^"]*)" name="([^"]*)"')


class ReadError(Exception):
    """A generation file can't be read, so the comparison can't say anything (exit 2)."""


def _twin_tops_permuted(old, new):
    """Binders' TwinTops binds both twin Pads and the flake swaps them: the Support targets of the
    new run are a permutation of the old run's, in the property and in the references. One side
    changing alone (both supports on one Pad, say) is a real change, not the flake."""
    try:
        a = old["records"]["Binders"]["objects"]["TwinTops"]
        b = new["records"]["Binders"]["objects"]["TwinTops"]

        def refs(o):
            return [
                o["refs"][f"Support[{i}]"]["target"] for i in range(len(o["props"]["Support"][1]))
            ]

        def prop(o):
            return list(o["props"]["Support"][1])

        # each run agrees with itself (the references follow the property), and the runs differ
        # only by the order of the same targets
        return refs(a) == prop(a) and refs(b) == prop(b) and sorted(prop(a)) == sorted(prop(b))
    except (KeyError, TypeError, IndexError):
        return False


# (oracle file, path pattern, the values both sides must be among, a guard on the two oracles, why).
# Binders' two twin Pads swap their names in some runs (ops#344's rebase, work\pr344-rebase2\gen).
KNOWN_FLAKES = [
    (
        "Binders.oracle.json",
        re.compile(
            r"^/records/Binders/objects/TwinTops/(props/Support\[\d\]\[\d\]|refs/Support\[\d\]/target)$"
        ),
        {"TwinPad", "Twin001Pad"},
        _twin_tops_permuted,
        "Binders: the twin Pads' names swap between runs",
    ),
]


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        raise ReadError(f"can't read {path}: {e}")


def _walk(x, y, path, out):
    """Appends (path, old, new) for each difference."""
    if isinstance(x, dict) and isinstance(y, dict):
        for key in sorted(set(x) | set(y)):
            if key in IGNORED_KEYS:
                continue
            if key not in x or key not in y:
                out.append(
                    (
                        f"{path}/{key}",
                        "(missing)" if key not in x else x[key],
                        "(missing)" if key not in y else y[key],
                    )
                )
            else:
                _walk(x[key], y[key], f"{path}/{key}", out)
    elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        for i, (p, q) in enumerate(zip(x, y)):
            _walk(p, q, f"{path}[{i}]", out)
    elif x != y:
        out.append((path, x, y))


def _short(value, limit=100):
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _around(a, b):
    """Two long strings shown around their first difference."""
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return f"...{a[max(0, i - 30):i + 40]} -> ...{b[max(0, i - 30):i + 40]}"


def _describe(path, old, new):
    if isinstance(old, str) and isinstance(new, str) and max(len(old), len(new)) > 100:
        return f"{path}: {_around(old, new)}"
    return f"{path}: {_short(old)} -> {_short(new)}"


def _flake(name, path, old, new, oldDoc, newDoc):
    for file, pattern, values, guard, why in KNOWN_FLAKES:
        if (
            name == file
            and pattern.match(path)
            and old in values
            and new in values
            and guard(oldDoc, newDoc)
        ):
            return why
    return None


def _document(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(z.namelist())
            xml = (
                z.read("Document.xml").decode("utf-8", errors="replace")
                if "Document.xml" in names
                else ""
            )
    except (OSError, zipfile.BadZipFile) as e:
        raise ReadError(f"can't read {path}: {e}")
    return names, _OBJECT.findall(xml)


def compare(old, new):
    """(differences, flakes): lists of lines."""
    differences, flakes = [], []
    mold, mnew = _load(os.path.join(old, "MANIFEST")), _load(os.path.join(new, "MANIFEST"))
    for field in MANIFEST_FIELDS:
        if mold.get(field) != mnew.get(field):
            if field == "models":
                for model in sorted(set(mold[field]) | set(mnew[field])):
                    if mold[field].get(model) != mnew[field].get(model):
                        differences.append(
                            f"MANIFEST models/{model}: {mold[field].get(model)} -> {mnew[field].get(model)}"
                        )
            else:
                differences.append(f"MANIFEST {field}: {mold.get(field)} -> {mnew.get(field)}")
    oldFiles, newFiles = set(mold.get("files", {})), set(mnew.get("files", {}))
    for name in sorted(oldFiles - newFiles):
        differences.append(f"{name}: only in the old generation")
    for name in sorted(newFiles - oldFiles):
        differences.append(f"{name}: only in the new generation")
    for name in sorted(oldFiles & newFiles):
        a, b = os.path.join(old, name), os.path.join(new, name)
        if name.endswith(".oracle.json"):
            found = []
            docA, docB = _load(a), _load(b)
            _walk(docA, docB, "", found)
            for path, x, y in found:
                why = _flake(name, path, x, y, docA, docB)
                if why:
                    flakes.append(f"{name} {_describe(path, x, y)} (known flake: {why})")
                else:
                    differences.append(f"{name} {_describe(path, x, y)}")
        elif name.endswith(".FCStd"):
            (namesA, objectsA), (namesB, objectsB) = _document(a), _document(b)
            if namesA != namesB:
                differences.append(f"{name}: members {sorted(set(namesA) ^ set(namesB))} differ")
            if objectsA != objectsB:
                differences.append(
                    f"{name}: objects differ: {sorted(set(objectsA) ^ set(objectsB)) or 'order'}"
                )
    return differences, flakes


def main(argv):
    strict = "--strict" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        sys.stderr.write(__doc__.split("\n\n")[1] + "\n")
        return 2
    try:
        differences, flakes = compare(args[0], args[1])
    except ReadError as e:
        sys.stderr.write(f"compare_generations: {e}\n")
        return 2
    except (KeyError, TypeError, AttributeError) as e:
        sys.stderr.write(f"compare_generations: a MANIFEST is malformed: {type(e).__name__} {e}\n")
        return 2
    for line in differences:
        print("DIFFERENCE", line)
    for line in flakes:
        print("FLAKE", line)
    if differences or (strict and flakes):
        print(f"{len(differences)} difference(s), {len(flakes)} known flake(s)")
        return 1
    print("no difference" + (f" ({len(flakes)} known flake(s))" if flakes else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
