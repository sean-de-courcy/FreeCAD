#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-2.1-or-later

"""FreeCAD-CH release check (ops#460, ops#482): the compat corpus holds the previous release's generation.

After the beta, each release's generation is saved after its tag, from that release's own build
(notes/beta-compatibility.md 3.9): fork-0.7.0's build saved gen1. A release is therefore checked
against the release before it: the newest generation in
`src/Mod/PartDesign/PartDesignTests/Compat/gen<k>` must carry the `namingRevision` of the previous
`fork-*` release (`ForkNamingRevision` in that tag's `src/App/Document.cpp`; the tag is
`git describe --tags --abbrev=0 --match 'fork-*' HEAD` with HEAD's own `fork-*` tags excluded, so a
tag already on HEAD is not its own previous release, and a merge commit counts a release tagged on
its merged branch), in both of its halves: `gen<k>` saved on Windows and `gen<k>-macos` saved on
macOS (ops#538); a missing half is an error.
- Lower: the previous release's generation never landed, and TestCompatCorpus would read the files
  it promised to open as an older generation's. Refused.
- Higher than this source's `ForkNamingRevision`: no build of this source wrote it. Refused.
- Higher than the previous release's, up to this source's: saved by a later build than the
  release's, so it isn't the record of what that release wrote. Refused.

    check_release_gen0.py --source .                    refuse (exit 1) unless it holds
    check_release_gen0.py --source . --warn-only        report it, exit 0 (a dry run)

Exit codes: 0 current (or --warn-only), 1 refused, 2 can't read a revision, a MANIFEST or the
previous tag. To fix a refusal: save gen<k> with the previous release's own build (its Windows
package running `regen_gen0_drive.py`, the macOS half from a `CI_macos.yml` run on its tag with
`-f compat_generation=<k>`), land both halves as one PR, and release from the commit after it
(notes/beta-compatibility.md 3.9). The source must be a git checkout with the tags (the release
workflow fetches full history).
"""

import argparse
import json
import os
import re
import subprocess
import sys

COMPAT = os.path.join("src", "Mod", "PartDesign", "PartDesignTests", "Compat")
DOCUMENT = os.path.join("src", "App", "Document.cpp")
# A generation's halves, by folder suffix (make_generation.HALVES): Windows, macOS.
HALVES = ("", "-macos")
REVISION_LINE = re.compile(r"^constexpr int ForkNamingRevision = (\d+);", re.MULTILINE)


def how_to_fix(tag, k, names):
    """The refusal's remedy: generation `k`'s folders `names`, saved by `tag`'s own build."""
    return (
        f"Save {' and '.join(names)} with {tag}'s own build (its Windows package running "
        f"src/Mod/PartDesign/PartDesignTests/Compat/regen_gen0_drive.py for gen{k}, "
        f"`gh workflow run CI_macos.yml --ref {tag} -f compat_generation={k}` for gen{k}-macos), "
        f"land them as one PR, and release from the commit after it (notes/beta-compatibility.md 3.9)."
    )


class CheckError(Exception):
    """Something the check needs is missing or unreadable (exit 2)."""


def revision_in(text, where):
    """ForkNamingRevision in the text of a Document.cpp."""
    m = REVISION_LINE.search(text)
    if not m:
        raise CheckError(f"no `constexpr int ForkNamingRevision = N;` line in {where}")
    return int(m.group(1))


def build_revision(source):
    """ForkNamingRevision in the source's Document.cpp."""
    path = os.path.join(source, DOCUMENT)
    try:
        with open(path, encoding="utf-8") as document:
            text = document.read()
    except OSError as error:
        raise CheckError(f"can't read {path}: {error}")
    return revision_in(text, path)


def git(source, *args):
    """stdout of a git command in the source tree."""
    try:
        done = subprocess.run(
            ["git", "-C", source, *args], capture_output=True, text=True, encoding="utf-8"
        )
    except OSError as error:
        raise CheckError(f"can't run git: {error}")
    if done.returncode != 0:
        raise CheckError(f"git {' '.join(args)} failed in {source}: {done.stderr.strip()}")
    return done.stdout


def previous_release(source):
    """(tag, ForkNamingRevision) of the newest fork-* tag before HEAD.

    Not `HEAD^`: that is the first parent only, so a merge of a hotfix branch tagged fork-X would
    take the tag before fork-X (fork-0.6.1 reached integration that way)."""
    own = git(source, "tag", "--points-at", "HEAD", "--list", "fork-*").split()
    excluded = [arg for name in own for arg in ("--exclude", name)]
    tag = git(
        source, "describe", "--tags", "--abbrev=0", "--match", "fork-*", *excluded, "HEAD"
    ).strip()
    where = f"{tag}:{DOCUMENT.replace(os.sep, '/')}"
    return tag, revision_in(git(source, "show", where), where)


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
    tag, previous = previous_release(source)
    stale, wrong = [], []
    for name, generation, built in halves:
        if generation == previous and generation <= revision:
            continue
        built = f" (made by a build of {built[0][:10]})" if built else ""
        if generation > revision:
            why = f"newer than this source's ForkNamingRevision {revision}: no build of it wrote that"
        elif generation < previous:
            why = (
                f"older than {tag}'s ForkNamingRevision {previous}: {tag}'s generation never landed, "
                f"so TestCompatCorpus would read the files {tag} wrote as an older release's"
            )
        else:
            why = (
                f"newer than {tag}'s ForkNamingRevision {previous}: a later build saved it, so it "
                f"isn't the record of what {tag} wrote"
            )
        stale.append(f"{name} has naming revision {generation}{built}, {why}")
        wrong.append(name)
    if not stale:
        names = " and ".join(name for name, _, _ in halves)
        return True, (
            f"Compat corpus: {names} hold {tag}'s generation (naming revision {previous}; "
            f"this source's is {revision})."
        )
    k = int(re.match(r"gen(\d+)", halves[0][0]).group(1))
    if all(generation < previous for _, generation, _ in halves):
        # the release's generation never landed: it is the next number
        fix = f"{tag}'s generation is gen{k + 1}, not landed yet. " + how_to_fix(
            tag, k + 1, [f"gen{k + 1}", f"gen{k + 1}-macos"]
        )
    else:
        # a half that isn't the release's record is saved again
        fix = how_to_fix(tag, k, wrong)
    return False, f"Compat corpus: {'; '.join(stale)} (ops#482). {fix}"


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
        message = f"Release check (compat generation): {error}"
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
