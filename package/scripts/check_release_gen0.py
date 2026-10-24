#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-2.1-or-later

"""FreeCAD-CH release check (ops#460): the compat corpus is current for the build's naming revision.

TestCompatCorpus reads a generation whose MANIFEST `namingRevision` is below the build's as a
user's older file, and then does not compare element names. Naming PRs no longer regenerate gen0
(PLAN decision 120 (1)); the coordinator does it once per merge batch. A release built from a batch
whose gen0 is still older would ship with the name check off, so it is refused here, before the
draft release exists. The newest generation in `src/Mod/PartDesign/PartDesignTests/Compat/gen<k>`
must carry the same `namingRevision` as `ForkNamingRevision` in `src/App/Document.cpp`.

    check_release_gen0.py --source .                    refuse (exit 1) when gen0 is older
    check_release_gen0.py --source . --warn-only        report it, exit 0 (a dry run)

Exit codes: 0 current (or --warn-only), 1 refused, 2 can't read the revision or a MANIFEST.
To fix a refusal: merge the batch into integration, build it, run
`src/Mod/PartDesign/PartDesignTests/Compat/regen_gen0.sh --install` from that checkout, land the
result as a PR, and cut the release from the commit after it (notes/beta-compatibility.md 3.9).
"""

import argparse
import json
import os
import re
import sys

COMPAT = os.path.join("src", "Mod", "PartDesign", "PartDesignTests", "Compat")
DOCUMENT = os.path.join("src", "App", "Document.cpp")

HOW_TO_FIX = (
    "Merge the batch into integration, build it, run "
    "src/Mod/PartDesign/PartDesignTests/Compat/regen_gen0.sh --install from that checkout, "
    "land the result as a PR, and release from the commit after it "
    "(notes/beta-compatibility.md 3.9)."
)


class CheckError(Exception):
    """Something the check needs is missing or unreadable (exit 2)."""


def build_revision(source):
    """ForkNamingRevision in the source's Document.cpp."""
    path = os.path.join(source, DOCUMENT)
    try:
        with open(path, encoding="utf-8") as document:
            text = document.read()
    except OSError as error:
        raise CheckError(f"can't read {path}: {error}")
    m = re.search(r"^constexpr int ForkNamingRevision = (\d+);", text, re.MULTILINE)
    if not m:
        raise CheckError(f"no `constexpr int ForkNamingRevision = N;` line in {path}")
    return int(m.group(1))


def newest_generation(source):
    """(name, namingRevision, build) of the highest-numbered gen<k> folder with a MANIFEST."""
    compat = os.path.join(source, COMPAT)
    try:
        entries = os.listdir(compat)
    except OSError as error:
        raise CheckError(f"can't list {compat}: {error}")
    numbers = sorted(int(m.group(1)) for m in map(re.compile(r"^gen(\d+)$").match, entries) if m)
    if not numbers:
        raise CheckError(f"no gen<k> folder in {compat}")
    name = f"gen{numbers[-1]}"
    path = os.path.join(compat, name, "MANIFEST")
    try:
        with open(path, encoding="utf-8") as manifest:
            data = json.load(manifest)
        return name, int(data["namingRevision"]), str(data.get("build", "")).split()[-1:]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CheckError(f"can't read namingRevision from {path}: {error!r}")


def check(source):
    """(ok, message) for a source tree."""
    revision = build_revision(source)
    name, generation, built = newest_generation(source)
    built = f" (made by a build of {built[0][:10]})" if built else ""
    if generation == revision:
        return True, f"Compat corpus: {name} is current (naming revision {revision})."
    relation = "older than" if generation < revision else "newer than"
    return False, (
        f"Compat corpus: {name} has naming revision {generation}{built}, {relation} this "
        f"source's ForkNamingRevision {revision}. TestCompatCorpus reads such a generation as an "
        f"older file and does not compare element names, so a release from this commit would "
        f"ship with the name check off (ops#460). {HOW_TO_FIX}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=".", help="the source tree (default: the current folder)")
    parser.add_argument("--warn-only", action="store_true", help="report a refusal, exit 0 (dry runs)")
    parser.add_argument("--summary", help="append the result to this Markdown file")
    args = parser.parse_args()

    try:
        ok, message = check(args.source)
    except CheckError as error:
        sys.exit(f"Release check (gen0): {error}")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as summary:
            summary.write(("" if ok else "**Refused:** ") + message + "\n\n")
    if ok:
        print(message)
    elif args.warn_only:
        print(f"::warning::{message} (dry run: not refused)")
    else:
        sys.exit(message + " Refusing to build the release.")


if __name__ == "__main__":
    main()
