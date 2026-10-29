#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-2.1-or-later

"""FreeCAD-CH release check (ops#460): the compat corpus is current for the build's naming revision.

TestCompatCorpus reads a generation whose MANIFEST `namingRevision` is below the build's as a
user's older file, and then does not compare element names. Naming PRs no longer regenerate gen0
(PLAN decision 120 (1)); the coordinator does it once per merge batch. A release built from a batch
whose gen0 is still older would ship with the name check off, so it is refused here, before the
draft release exists. The newest generation in `src/Mod/PartDesign/PartDesignTests/Compat/gen<k>`
must carry the same `namingRevision` as `ForkNamingRevision` in `src/App/Document.cpp`, in both of
its halves: `gen<k>` saved on Windows and `gen<k>-macos` saved on macOS (ops#538); a missing half
is an error.

    check_release_gen0.py --source .                    refuse (exit 1) when gen0 is older
    check_release_gen0.py --source . --warn-only        report it, exit 0 (a dry run)

Exit codes: 0 current (or --warn-only), 1 refused, 2 can't read the revision or a MANIFEST.
To fix a refusal: merge the batch into integration, build it, run
`src/Mod/PartDesign/PartDesignTests/Compat/regen_gen0.sh --install` from that checkout (the macOS
half: `--install --from` the compat-gen0-macos artifact of integration's macOS run), land the
result as a PR, and cut the release from the commit after it (notes/beta-compatibility.md 3.9).
"""

import argparse
import json
import os
import re
import sys

COMPAT = os.path.join("src", "Mod", "PartDesign", "PartDesignTests", "Compat")
DOCUMENT = os.path.join("src", "App", "Document.cpp")
# A generation's halves, by folder suffix (make_generation.HALVES): Windows, macOS.
HALVES = ("", "-macos")

HOW_TO_FIX = (
    "Merge the batch into integration, build it, run "
    "src/Mod/PartDesign/PartDesignTests/Compat/regen_gen0.sh --install from that checkout "
    "(the macOS half: --install --from the compat-gen0-macos artifact of integration's macOS "
    "run), land both halves as one PR, and release from the commit after it "
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
    """[(name, namingRevision, build)] of both halves of the highest-numbered generation: gen<k>,
    then gen<k>-macos.

    The newest number counts even when a half has no folder or no MANIFEST: that is an error (exit
    2), never a fall back to an older generation."""
    compat = os.path.join(source, COMPAT)
    try:
        entries = os.listdir(compat)
    except OSError as error:
        raise CheckError(f"can't list {compat}: {error}")
    folder = re.compile(r"^gen(\d+)(?:-macos)?$")
    numbers = sorted({int(m.group(1)) for m in map(folder.match, entries) if m})
    if not numbers:
        raise CheckError(f"no gen<k> folder in {compat}")
    halves = []
    for suffix in HALVES:
        name = f"gen{numbers[-1]}{suffix}"
        if not os.path.isdir(os.path.join(compat, name)):
            raise CheckError(
                f"no {name} folder in {compat}: each generation has a Windows half (gen<k>) and a "
                f"macOS half (gen<k>-macos), ops#538"
            )
        path = os.path.join(compat, name, "MANIFEST")
        try:
            with open(path, encoding="utf-8") as manifest:
                data = json.load(manifest)
            naming = data["namingRevision"]
            # TestCompatCorpus compares an exact int: "6", 6.0 and true are not a revision
            if type(naming) is not int:
                raise ValueError(f"namingRevision is {naming!r}, not an integer")
            halves.append((name, naming, str(data.get("build", "")).split()[-1:]))
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CheckError(f"can't read namingRevision from {path}: {error!r}")
    return halves


def check(source):
    """(ok, message) for a source tree."""
    revision = build_revision(source)
    halves = newest_generation(source)
    stale = []
    for name, generation, built in halves:
        if generation == revision:
            continue
        built = f" (made by a build of {built[0][:10]})" if built else ""
        relation = "older than" if generation < revision else "newer than"
        stale.append(
            f"{name} has naming revision {generation}{built}, {relation} this source's "
            f"ForkNamingRevision {revision}"
        )
    names = " and ".join(name for name, _, _ in halves)
    if not stale:
        return True, f"Compat corpus: {names} are current (naming revision {revision})."
    return False, (
        f"Compat corpus: {'; '.join(stale)}. TestCompatCorpus reads such a generation as an older file and does not compare element "
        f"names, so a release from this commit would ship with the name check off (ops#460). "
        f"{HOW_TO_FIX}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=".", help="the source tree (default: the current folder)")
    parser.add_argument("--warn-only", action="store_true", help="report a refusal, exit 0 (dry runs)")
    parser.add_argument("--summary", help="append the result to this Markdown file")
    args = parser.parse_args()

    def summarize(text):
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as summary:
                summary.write(text + "\n\n")

    try:
        ok, message = check(args.source)
    except CheckError as error:
        message = f"Release check (gen0): {error}"
        summarize("**Refused:** " + message)
        print(message, file=sys.stderr)
        sys.exit(2)
    summarize(("" if ok else "**Refused:** ") + message)
    if ok:
        print(message)
    elif args.warn_only:
        print(f"::warning::{message} (dry run: not refused)")
    else:
        sys.exit(message + " Refusing to build the release.")


if __name__ == "__main__":
    main()
