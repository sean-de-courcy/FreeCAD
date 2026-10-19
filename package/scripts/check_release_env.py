#!/usr/bin/env python
# SPDX-License-Identifier: LGPL-2.1-or-later

"""FreeCAD-CH release check (ops#388): a packaged build runs the tested environment.

The release bundles copy the pixi environment that CI and every test use (pixi.lock,
environment "default"). This check runs the packaged FreeCADCmd, asks it for the OCCT,
Python and Qt versions it actually loads, and fails when any of them differs from the
version pixi.lock pins for the platform. Without --freecadcmd it only prints the locked
versions (the release notes job).

    check_release_env.py --lock pixi.lock --platform win-64 --freecadcmd <bundle>/bin/FreeCAD-CHCmd.exe
    check_release_env.py --lock pixi.lock --platform osx-arm64 --notes-line
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

# The package in pixi.lock, and the name the release notes use, for each checked library
PACKAGES = (("occt", "OCCT"), ("python", "Python"), ("qt6-main", "Qt"))

PROBE = (
    "import sys, Part; from PySide6 import QtCore; "
    "print('RELEASE-ENV occt=%s python=%d.%d.%d qt=%s' % "
    "((Part.OCC_VERSION,) + tuple(sys.version_info[:3]) + (QtCore.qVersion(),)))"
)


def locked_versions(lock_path, platform):
    """Versions of PACKAGES in pixi.lock's default environment for a platform.

    A lock platform is named after its subdir, with a suffix when it sets a minimum
    system version (osx-arm64-macos-14-0)."""
    found = {}
    section = None
    in_default = False
    with open(lock_path, encoding="utf-8") as lock:
        for line in lock:
            if not line.startswith(" "):
                in_default = False
                section = None
                continue
            if line.startswith("  ") and not line.startswith("   "):
                in_default = line.strip() == "default:"
                section = None
                continue
            if not in_default:
                continue
            m = re.match(r"^      ([A-Za-z0-9_-]+):\s*$", line)
            if m:
                name = m.group(1)
                section = name if name == platform or name.startswith(platform + "-") else None
                continue
            if section is None:
                continue
            m = re.match(r"^      - conda: \S+/([^/\s]+)\.(?:conda|tar\.bz2)\s*$", line)
            if not m:
                continue
            # <name>-<version>-<build>; names contain '-', versions and builds don't
            name, version, _build = m.group(1).rsplit("-", 2)
            if name in dict(PACKAGES):
                found[name] = version
    missing = [p for p, _ in PACKAGES if p not in found]
    if missing:
        sys.exit(f"pixi.lock has no {', '.join(missing)} for {platform} in the default environment")
    return found


def packaged_versions(freecadcmd):
    """Versions the packaged FreeCADCmd loads: Part.OCC_VERSION, sys.version_info, qVersion()."""
    env = dict(os.environ)
    # Never the runner's (or a developer's) own FreeCAD settings
    home = tempfile.mkdtemp(prefix="fc-release-check-")
    env["FREECAD_USER_HOME"] = home
    try:
        run = subprocess.run(
            [freecadcmd, "--safe-mode", "-c", PROBE],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    finally:
        shutil.rmtree(home, ignore_errors=True)
    output = run.stdout + run.stderr
    m = re.search(r"RELEASE-ENV occt=(\S+) python=(\S+) qt=(\S+)", output)
    if not m:
        print(output)
        sys.exit(f"{freecadcmd} did not report its versions (exit code {run.returncode})")
    return dict(zip((p for p, _ in PACKAGES), m.groups()))


def same(locked, reported):
    # A conda version can carry more parts than the library reports (occt 8.0.1.1 is OCCT 8.0.1)
    lparts = locked.split(".")
    rparts = reported.split(".")
    return len(rparts) >= 3 and lparts[: len(rparts)] == rparts


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lock", required=True, help="the workspace's pixi.lock")
    parser.add_argument("--platform", required=True, help="conda subdir, e.g. win-64, osx-arm64")
    parser.add_argument("--freecadcmd", help="the packaged FreeCADCmd to check")
    parser.add_argument("--notes-line", action="store_true", help="print one release-notes line")
    parser.add_argument("--summary", help="append the result to this Markdown file")
    args = parser.parse_args()

    locked = locked_versions(args.lock, args.platform)
    reported = packaged_versions(args.freecadcmd) if args.freecadcmd else None

    lines = []
    failed = False
    for package, label in PACKAGES:
        line = f"{label} {locked[package]}"
        if reported is not None:
            ok = same(locked[package], reported[package])
            failed |= not ok
            line = f"{label}: pixi.lock {locked[package]}, packaged build {reported[package]}" + (
                "" if ok else "  <-- MISMATCH"
            )
        lines.append(line)

    if args.notes_line:
        text = f"- {args.platform}: " + ", ".join(lines)
    else:
        text = f"Release environment, {args.platform}:\n" + "\n".join("  " + l for l in lines)
    print(text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as summary:
            summary.write(text.replace("  <-- MISMATCH", " **(mismatch)**") + "\n\n")
    if failed:
        sys.exit(
            "The packaged build does not run the tested environment (pixi.lock): "
            "refusing to package it (ops#388)."
        )


if __name__ == "__main__":
    main()
