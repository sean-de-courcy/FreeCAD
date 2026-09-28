# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run FreeCAD's tests and compare their failures with the known-failure list.

The list lives in tests/known-failures/*.txt (format: tests/known-failures/README.md).
A run fails only on failures that aren't listed, or when it didn't complete. Listed
tests that didn't fail are reported so their entries can be removed.

    python known_failures.py gtest --build-dir build/release --out-dir logs/gtest
    python known_failures.py cli --log logs/TestCLIBuild.log [--exit-code N]
    python known_failures.py list

Common options: --platform windows|macos|linux (default: this machine),
--list-dir (default: tests/known-failures next to this checkout), --report FILE
(markdown appended; $GITHUB_STEP_SUMMARY gets it too when set).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PLATFORMS = ("windows", "macos", "linux")
KINDS = ("gtest", "exe", "cli")
REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_ANNOTATIONS = 20


def this_platform():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


# ---------------------------------------------------------------------------
# The list


class Entry:
    def __init__(self, kind, test_id, platforms, issue, reason, where):
        self.kind = kind
        self.test_id = test_id
        self.platforms = platforms
        self.issue = issue
        self.reason = reason
        self.where = where

    @property
    def key(self):
        return (self.kind, self.test_id)

    def applies_to(self, platform):
        return not self.platforms or platform in self.platforms


class ListError(Exception):
    pass


def load_list(list_dir):
    """Parse every *.txt in list_dir. Raises ListError listing every problem found."""
    entries = []
    problems = []
    files = sorted(Path(list_dir).glob("*.txt"))
    if not files:
        raise ListError(f"no *.txt files in {list_dir}")
    for path in files:
        issue = None
        reason = None
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            where = f"{path.name}:{lineno}"
            line = re.sub(
                r"(^|\s)#.*$", "", raw
            ).strip()  # '#' after a space starts a comment; ops#N doesn't
            if not line:
                continue
            if line.startswith("issue:"):
                issue = line[len("issue:") :].strip()
                if not re.fullmatch(r"ops#\d+", issue):
                    problems.append(f"{where}: issue must look like ops#<n>, got '{issue}'")
                continue
            if line.startswith("reason:"):
                reason = line[len("reason:") :].strip()
                if not reason:
                    problems.append(f"{where}: empty reason")
                continue
            fields = line.split()
            kind, rest = fields[0], fields[1:]
            if kind not in KINDS:
                problems.append(
                    f"{where}: unknown kind '{kind}' (expected one of {', '.join(KINDS)})"
                )
                continue
            if not rest:
                problems.append(f"{where}: '{kind}' without a test ID")
                continue
            test_id, platforms = rest[0], rest[1:]
            bad = [p for p in platforms if p not in PLATFORMS]
            if bad:
                problems.append(f"{where}: unknown platform(s) {' '.join(bad)}")
            if kind == "gtest" and "/" not in test_id:
                problems.append(
                    f"{where}: gtest IDs are <executable>/<Suite.Case>, got '{test_id}'"
                )
            if issue is None:
                problems.append(f"{where}: entry before the file's 'issue:' line")
            if reason is None:
                problems.append(f"{where}: entry without a 'reason:' above it")
            entries.append(Entry(kind, test_id, frozenset(platforms), issue, reason, where))
    # An ID may appear more than once only for disjoint platform sets.
    seen = {}
    for e in entries:
        for other in seen.get(e.key, []):
            if not e.platforms or not other.platforms or e.platforms & other.platforms:
                problems.append(
                    f"{e.where}: '{e.kind} {e.test_id}' is already listed at {other.where}"
                )
        seen.setdefault(e.key, []).append(e)
    if problems:
        raise ListError("\n".join(problems))
    return entries


# ---------------------------------------------------------------------------
# Results: every test that ran, as {(kind, id): status}, status one of
# "pass", "fail", "skip"; plus "problems": failures without a test ID of their own.


class Results:
    def __init__(self, what):
        self.what = what
        self.status = {}
        self.details = {}
        self.incomplete = []  # human-readable reasons the run is incomplete; each fails the check

    def set(self, key, status, detail=""):
        # A failure wins over anything else reported for the same test (subtests, reruns).
        if self.status.get(key) == "fail":
            return
        self.status[key] = status
        if detail:
            self.details[key] = detail


def compare(results, entries, platform):
    listed = {e.key: e for e in entries if e.applies_to(platform) and e.key[0] in results.kinds}
    failed = [k for k, s in results.status.items() if s == "fail"]
    unlisted = sorted(k for k in failed if k not in listed)
    known = sorted(k for k in failed if k in listed)
    not_failing = []
    for key, entry in sorted(listed.items()):
        status = results.status.get(key)
        if key[0] == "gtest" and results.status.get(("exe", key[1].split("/", 1)[0])) == "fail":
            continue  # its executable failed as a whole; that is reported already
        if status != "fail":
            not_failing.append(
                (
                    key,
                    entry,
                    {"pass": "passed", "skip": "skipped"}.get(status, "not seen in the run"),
                )
            )
    return unlisted, known, not_failing


def report(results, entries, platform, report_file):
    unlisted, known, not_failing = compare(results, entries, platform)
    if results.incomplete:
        not_failing = []  # meaningless when tests are missing from the run
    ok = not unlisted and not results.incomplete
    passed = sum(1 for s in results.status.values() if s == "pass")

    out = []
    icon = ":heavy_check_mark:" if ok else ":fire:"
    out.append(
        f"<details><summary>{icon} {results.what}, known-failure check ({platform}): "
        f"{len(unlisted)} new failures, {len(known)} known, {len(not_failing)} listed but not failing"
        f"{', run incomplete' if results.incomplete else ''}</summary>\n"
    )
    out.append(
        f"{passed} passed, {len(known) + len(unlisted)} failed "
        f"(IDs as in `tests/known-failures`).\n"
    )
    if results.incomplete:
        out.append("**The run is incomplete:**\n")
        out.extend(f"- {r}" for r in results.incomplete)
        out.append("")
    if unlisted:
        out.append("**New failures (not in the list): these fail the step.**\n\n```")
        out.extend(f"{k} {i}" for k, i in unlisted)
        out.append("```\n")
    if not_failing:
        out.append("**Listed but not failing: remove these entries if they now pass.**\n\n```")
        out.extend(f"{k} {i}  # {why}; {e.where}" for (k, i), e, why in not_failing)
        out.append("```\n")
    if known:
        by_issue = {}
        for key in known:
            e = next(e for e in entries if e.key == key and e.applies_to(platform))
            by_issue.setdefault(e.issue, []).append(key)
        out.append(
            "Known failures by issue: "
            + ", ".join(f"{issue} ({len(keys)})" for issue, keys in sorted(by_issue.items()))
            + "\n"
        )
    out.append("</details>\n")
    text = "\n".join(out)

    print(text)
    for path in filter(None, [report_file, os.environ.get("GITHUB_STEP_SUMMARY")]):
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    if os.environ.get("GITHUB_ACTIONS"):
        for reason in results.incomplete:
            print(f"::error title={results.what}: run incomplete::{reason}")
        for k, i in unlisted[:MAX_ANNOTATIONS]:
            print(f"::error title={results.what}: new failure::{k} {i}")
        for (k, i), e, why in not_failing[:MAX_ANNOTATIONS]:
            print(f"::warning title={results.what}: listed but {why}::{k} {i} ({e.where})")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# C++ tests: every gtest and QtTest executable in the build, one after another.

EXE_RE = re.compile(r"^[A-Za-z0-9]+_(tests|Tests)_run(\.exe)?$")


def find_test_executables(build_dir):
    found = {}
    for sub in ("tests", "bin"):  # tests/ on macOS and Linux, bin/ on Windows
        d = build_dir / sub
        if d.is_dir():
            for p in d.iterdir():
                if p.is_file() and EXE_RE.match(p.name) and os.access(p, os.X_OK):
                    found.setdefault(p.name.removesuffix(".exe"), p)
    return dict(sorted(found.items()))


def test_environment(build_dir):
    env = dict(os.environ)
    if sys.platform.startswith("win"):
        # What tests/CMakeLists.txt gives ctest (without its configure-time glob, ops#14):
        # FreeCAD's DLLs in bin/, module .pyd files in Mod/*/, third-party DLLs in the env.
        dirs = [build_dir / "bin"] + sorted(p for p in (build_dir / "Mod").glob("*") if p.is_dir())
        prefix = os.environ.get("CONDA_PREFIX")
        if prefix:
            dirs.append(Path(prefix) / "Library" / "bin")
            plugins = Path(prefix) / "Library" / "lib" / "qt6" / "plugins"
            if plugins.is_dir():
                env.setdefault("QT_PLUGIN_PATH", str(plugins))
        env["PATH"] = os.pathsep.join([str(d) for d in dirs] + [env.get("PATH", "")])
    if "FREECAD_USER_HOME" not in env:
        env["FREECAD_USER_HOME"] = tempfile.mkdtemp(prefix="fc-test-home-")
    return env


def run_gtests(args):
    build_dir = Path(args.build_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    exes = find_test_executables(build_dir)
    results = Results("C++ tests")
    results.kinds = ("gtest", "exe")
    if not exes:
        results.incomplete.append(
            f"no test executables found in {build_dir}/tests or {build_dir}/bin"
        )
        return results
    env = test_environment(build_dir)
    cwd = build_dir / "tests" if (build_dir / "tests").is_dir() else build_dir
    for name, path in exes.items():
        qt = name.endswith("_Tests_run")
        json_file = out_dir / f"{name}.json"
        log_file = out_dir / f"{name}.log"
        json_file.unlink(missing_ok=True)
        run_env = dict(env)
        if qt:
            run_env.setdefault("QT_QPA_PLATFORM", "offscreen")  # as ctest does for them
        else:
            run_env["GTEST_OUTPUT"] = f"json:{json_file}"
        start = time.monotonic()
        with open(log_file, "w", encoding="utf-8", errors="replace") as log:
            try:
                proc = subprocess.run(
                    [str(path)],
                    cwd=cwd,
                    env=run_env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=args.timeout,
                )
                code = proc.returncode
            except subprocess.TimeoutExpired:
                code = None
        took = time.monotonic() - start
        failing_cases = 0
        if not qt and json_file.is_file():
            data = json.loads(json_file.read_text(encoding="utf-8"))
            for suite in data.get("testsuites", []):
                for case in suite.get("testsuite", []):
                    key = ("gtest", f"{name}/{suite['name']}.{case['name']}")
                    if case.get("status") == "NOTRUN" or case.get("result") in (
                        "SKIPPED",
                        "SUPPRESSED",
                    ):
                        results.set(key, "skip")
                    elif case.get("failures"):
                        results.set(key, "fail", case["failures"][0].get("failure", ""))
                        failing_cases += 1
                    else:
                        results.set(key, "pass")
        # The executable as a whole: a failure its cases don't account for (a crash, a
        # timeout, missing DLLs, a failing QtTest executable) is a failure of 'exe <name>'.
        if code is None:
            state = f"timed out after {args.timeout} s"
        elif code != 0 and failing_cases == 0:
            state = f"exit code {code}" + (
                "" if qt or json_file.is_file() else ", no gtest results"
            )
        else:
            state = None
        results.set(("exe", name), "fail" if state else "pass", state or "")
        print(
            f"{name}: exit {code}, {failing_cases} failing cases, {took:.1f} s"
            + (f"  <- {state}" if state else ""),
            flush=True,
        )
    return results


# ---------------------------------------------------------------------------
# Python tests: the log of FreeCADCmd -t 0 / FreeCAD -t 0 (unittest, verbosity 2).

# Failures come from the error list after the run ("FAIL: name (id)"), which is reliable.
# Passes and skips come from the verbose lines, which aren't: a docstring moves the outcome
# to the next line ("name (id)" / "Docstring ... ok"), and test output can come between
# "..." and the outcome. They only label listed tests that didn't fail.
HEADER_RE = re.compile(r"^(FAIL|ERROR|UNEXPECTED SUCCESS): (\S+) \(([^()\s]+)\)")
START_RE = re.compile(r"^(\S+) \(([^()\s]+)\)")
OUTCOME_RE = re.compile(
    r"(?:^|\.\.\. )(ok|skipped\b.*|expected failure|unexpected success|FAIL|ERROR)$"
)
RAN_RE = re.compile(r"^Ran (\d+) tests? in ")
SUMMARY_RE = re.compile(r"^(OK|FAILED)\b(.*)$")


def unittest_id(name, qualified):
    # "test_x (pkg.mod.Class.test_x)" -> pkg.mod.Class.test_x; class-level errors
    # ("setUpClass (pkg.mod.Class)") -> pkg.mod.Class.setUpClass.
    return (
        qualified if qualified.endswith("." + name) or qualified == name else f"{qualified}.{name}"
    )


def parse_cli(args):
    results = Results(args.what)
    results.kinds = ("cli",)
    path = Path(args.log)
    if not path.is_file():
        results.incomplete.append(f"no log at {path}")
        return results
    ran = None
    summary = None
    header_failures = 0
    pending = None  # the test whose verbose outcome hasn't been seen yet
    for line in path.read_text(encoding="utf-8", errors="replace").replace("\r", "").split("\n"):
        m = HEADER_RE.match(line)
        if m:
            results.set(("cli", unittest_id(m.group(2), m.group(3))), "fail", m.group(1))
            header_failures += 1
            pending = None
            continue
        m = START_RE.match(line)
        if m and ran is None:
            pending = ("cli", unittest_id(m.group(1), m.group(2)))
        m = OUTCOME_RE.search(line)
        if m and pending:
            outcome = m.group(1)
            if outcome in ("ok", "expected failure"):
                results.set(pending, "pass")
            elif outcome.startswith("skipped"):
                results.set(pending, "skip")
            elif outcome == "unexpected success":
                results.set(pending, "fail", outcome)
            pending = None
            continue
        m = RAN_RE.match(line)
        if m:
            ran = int(m.group(1))
            continue
        m = SUMMARY_RE.match(line)
        if m and ran is not None:
            summary = line
    if ran is None or summary is None:
        results.incomplete.append(
            "the log has no unittest summary ('Ran N tests' / 'OK' / 'FAILED'): "
            "the run crashed, hung or was cut off"
        )
    elif summary.startswith("FAILED") and header_failures == 0:
        results.incomplete.append(f"'{summary}' but no FAIL/ERROR lines could be parsed")
    if args.exit_code is not None and args.exit_code not in (0, 1):
        results.incomplete.append(
            f"the test process exited with code {args.exit_code} "
            "(the runner only returns 0 or 1)"
        )
    elif args.exit_code == 1 and summary and summary.startswith("OK"):
        results.incomplete.append("the tests report OK but the process exited with code 1")
    return results


# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--platform",
        default=this_platform(),
        type=str.lower,
        help="platform whose entries apply (a runner.os value works: Windows, macOS)",
    )
    common.add_argument("--list-dir", default=str(REPO_ROOT / "tests" / "known-failures"))
    common.add_argument("--report", help="markdown file to append the result to")
    sub = parser.add_subparsers(dest="mode", required=True)

    g = sub.add_parser(
        "gtest", parents=[common], help="run the C++ test executables and check them"
    )
    g.add_argument("--build-dir", required=True)
    g.add_argument("--out-dir", required=True, help="where each executable's log and gtest JSON go")
    g.add_argument("--timeout", type=int, default=300, help="seconds per executable")

    c = sub.add_parser("cli", parents=[common], help="check the log of a Python test run")
    c.add_argument("--log", required=True)
    c.add_argument("--exit-code", type=int, help="the test process's exit code, if known")
    c.add_argument("--what", default="Python tests", help="name of the run, for the report")

    sub.add_parser("list", parents=[common], help="validate the list and print a summary")

    args = parser.parse_args()
    if args.platform not in PLATFORMS:
        parser.error(f"--platform must be one of {', '.join(PLATFORMS)}")
    try:
        entries = load_list(args.list_dir)
    except ListError as e:
        print(f"The known-failure list has errors:\n{e}", file=sys.stderr)
        if os.environ.get("GITHUB_ACTIONS"):
            for line in str(e).splitlines()[:MAX_ANNOTATIONS]:
                print(f"::error title=Known-failure list::{line}")
        return 2

    if args.mode == "list":
        counts = {}
        for e in entries:
            counts.setdefault((e.issue, e.where.split(":")[0]), {}).setdefault(e.kind, 0)
            counts[(e.issue, e.where.split(":")[0])][e.kind] += 1
        for (issue, name), kinds in sorted(counts.items()):
            print(f"{name}: {issue}: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
        return 0

    results = run_gtests(args) if args.mode == "gtest" else parse_cli(args)
    return report(results, entries, args.platform, args.report)


if __name__ == "__main__":
    sys.exit(main())
