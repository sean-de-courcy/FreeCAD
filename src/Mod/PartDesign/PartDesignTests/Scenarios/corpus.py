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

"""The naming corpus (FreeCAD-CH, ops#506; notes/naming-system.md sections 2 and 3).

A case is a Scenario with CLASSES set (harness.py). Case modules live in a case folder: the
fork's `Scenarios/cases/`, or any folder named in FREECAD_SCENARIO_MODULES. Each module has a
ledger, `<folder>/ledger/<module>.json`: per (case, reference, configuration) the verdict
expected on Windows (`expected`, one verdict or an allowed set), an optional `macos` override,
the case's `tier`, `classes`, `axes`, `issue`, `found_by` and `accepted`, and a `run` header
(sha, platform, time, tier, cases). Ledgers are written by runs only
(FREECAD_SCENARIO_UPDATE_LEDGER=1), never by hand.

Each verdict is compared with its entry (`compare`): a worse one is REGRESSED (the gate fails),
a better one IMPROVED, another one of the same rank CHANGED (both warnings: the ledger needs the
full run), a key without an entry NEW (a failure, where the module has a ledger), an entry of
the tier without a run STALE (a failure). `TestCorpusGate` turns this into tests.

Tiers (FREECAD_SCENARIO_TIER): G, the cases with TIER "G" in V2s, one run each (the CI gate);
F, every case in V2s and its variants (`:thin` for THIN cases, `:s<mm>` for the sizes in
FREECAD_SCENARIO_SCALES), the V2si oracle, a second process under another naming hash seed
(a verdict that differs is `flaky`) and a range of random sequences.
"""

import datetime
import glob
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import traceback

import FreeCAD as App

from . import harness

LEDGER = "ledger"
# The in-tree case folder, relative to the source tree
CASES = "src/Mod/PartDesign/PartDesignTests/Scenarios/cases"
RANDOM_MODULE = "random"
# Seeds and steps of tier F's random sequences (FREECAD_SCENARIO_SEEDS, ..._STEPS)
RANDOM_SEEDS = "1-12"
RANDOM_STEPS = 8
# The hash seed of tier F's second process (FREECAD_SCENARIO_CHILD_SEED; "none" skips it)
CHILD_SEED = "2"
CHILD = "FREECAD_SCENARIO_CORPUS_CHILD"
# A case slower than this stays out of tier G (notes/naming-system.md 2.2)
TIER_G_SECONDS = 10


def tier():
    value = os.environ.get("FREECAD_SCENARIO_TIER", "G").strip().upper() or "G"
    if value not in ("G", "F"):
        raise harness.ScenarioError(f"FREECAD_SCENARIO_TIER={value!r}: G or F")
    return value


def platform():
    return "macos" if sys.platform == "darwin" else sys.platform


def say(line):
    """One line on stdout in one write, as harness.emit (the runner's output cuts lines)."""
    try:
        os.write(1, (line + "\n").encode("utf-8"))
    except OSError:
        App.Console.PrintMessage(line + "\n")


# ---------------------------------------------------------------------------------------------
# Case folders and modules
# ---------------------------------------------------------------------------------------------


def sourceTree():
    """The source tree of this build (its CMakeCache.txt), or None (an install)."""
    cache = os.path.join(App.getHomePath(), "CMakeCache.txt")
    try:
        with open(cache, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("CMAKE_HOME_DIRECTORY:"):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


class CaseModule:
    """One module of cases: its name (the ledger's file name), the module (None if it failed to
    import, with `error`), its folder and the folder's ledger."""

    def __init__(self, name, folder, module=None, error=None):
        self.name, self.folder, self.module, self.error = name, folder, module, error
        self.cases = harness.scenarioClasses([module], cases=True) if module else []

    @property
    def ledgerPath(self):
        return os.path.join(self.folder, LEDGER, self.name + ".json")


def folders():
    """The case folders: FREECAD_SCENARIO_MODULES (separated by os.pathsep), else the source
    tree's `Scenarios/cases/` (so a run reads the checkout's cases and ledgers, not the build's
    copies), else the build's or install's copy."""
    listed = os.environ.get("FREECAD_SCENARIO_MODULES")
    if listed:
        return [os.path.abspath(d) for d in listed.split(os.pathsep) if d.strip()], False
    source = sourceTree()
    if source and os.path.isdir(os.path.join(source, CASES)):
        return [os.path.normpath(os.path.join(source, CASES))], True
    from . import cases

    return [os.path.dirname(os.path.abspath(cases.__file__))], True


def loadModules():
    """([CaseModule], in-tree): every `*.py` of the case folders not starting with `_`, imported
    by path. Cases import the harness absolutely (`from PartDesignTests.Scenarios import
    harness`), so a module runs the same from any folder."""
    found = []
    dirs, inTree = folders()
    for folder in dirs:
        for path in sorted(glob.glob(os.path.join(folder, "*.py"))):
            name = os.path.splitext(os.path.basename(path))[0]
            if name.startswith("_"):
                continue
            if name == RANDOM_MODULE:
                raise harness.ScenarioError(f"{path}: the module name {name!r} is the ledger's")
            unique = f"corpus_{abs(hash(folder)) % 10**8}_{name}"
            try:
                spec = importlib.util.spec_from_file_location(unique, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[unique] = module
                spec.loader.exec_module(module)
                found.append(CaseModule(name, folder, module))
            except Exception:
                found.append(CaseModule(name, folder, error=traceback.format_exc()))
    names = [m.name for m in found]
    if len(names) != len(set(names)):
        raise harness.ScenarioError(f"two case modules share a name: {sorted(names)}")
    return found, inTree


# ---------------------------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------------------------


def key(case, ref, config):
    return f"{case}|{ref}|{config}"


def configsFor(case, which):
    """The configurations a case runs in, in the tier."""
    if which == "G":
        return ["V2s"] if case.TIER == "G" else []
    listed = os.environ.get("FREECAD_SCENARIO_CONFIGS")
    bases = [c.strip() for c in listed.split(",") if c.strip()] if listed else ["V2s"]
    configs = list(bases)
    for base in bases:
        if case.THIN:
            configs.append(base + ":thin")
        if case.SIZE:
            for size in os.environ.get("FREECAD_SCENARIO_SCALES", "").split(","):
                if size.strip():
                    configs.append(f"{base}:s{size.strip()}")
    return configs


def worst(results):
    """The worst of a reference's step Results by harness.RANKS (the first on a tie)."""
    return max(results, key=lambda r: harness.RANKS.get(r.verdict, 0))


class Outcome:
    """A reference's verdict in a configuration, its record (the worst step's) and its message."""

    def __init__(self, verdict, record=None, message=""):
        self.verdict, self.record, self.message = verdict, record or {}, message


def runCase(case, config):
    """({ref: Outcome}, {ref: Result or StepResults} or None, seconds) of one case in one
    configuration. A run that fails gives every reference `error`."""
    started = time.monotonic()
    try:
        results = case(config).run()
    except Exception:
        text = traceback.format_exc()
        outcomes = {ref: Outcome("error", message=text) for ref in case.REFS}
        return outcomes, None, time.monotonic() - started
    outcomes = {}
    for ref, result in results.items():
        steps = getattr(result, "results", [result])
        bad = worst(steps)
        outcomes[ref] = Outcome(bad.verdict, bad.record, bad.message())
    return outcomes, results, time.monotonic() - started


def randomSeeds():
    text = os.environ.get("FREECAD_SCENARIO_SEEDS", RANDOM_SEEDS).strip()
    if text.lower() == "none":
        return []
    seeds = []
    for part in text.split(","):
        first, _, last = part.strip().partition("-")
        seeds += range(int(first), int(last or first) + 1)
    return seeds


def runRandom(seed):
    """The Outcome of one random sequence in V2s: its first reference not as expected, else
    `correct`."""
    from . import randomized

    steps = int(os.environ.get("FREECAD_SCENARIO_STEPS", RANDOM_STEPS))
    try:
        plan = randomized.makePlan(seed, steps)
        results = randomized.RandomSequence("V2s", plan).run()
    except Exception:
        return Outcome("error", message=traceback.format_exc())
    for r in results:
        if not r.passing:
            return Outcome(r.verdict, r.record, r.message())
    return Outcome("correct", {}, "")


# ---------------------------------------------------------------------------------------------
# Ledgers
# ---------------------------------------------------------------------------------------------


def readLedger(path):
    """The ledger's {"run": header, "entries": {key: entry}}, or None if there is none."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def writeLedger(path, run, entries):
    """Sorted, one entry per line, so that a ledger's diff reads entry by entry."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ["{", f'"run": {json.dumps(run, sort_keys=True)},', '"entries": {']
    items = sorted(entries.items())
    for i, (k, entry) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        lines.append(f"{json.dumps(k)}: {json.dumps(entry, sort_keys=True)}{comma}")
    lines += ["}", "}"]
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def expectedOn(entry, where=None):
    """The entry's allowed verdicts on the platform: its `macos` override on macOS."""
    where = where or platform()
    value = entry.get("macos") if where == "macos" and "macos" in entry else entry["expected"]
    return list(value) if isinstance(value, list) else [value]


def compare(entry, verdict):
    """OK, REGRESSED, IMPROVED or CHANGED: the verdict against the entry's allowed verdicts. An
    error or a flake that isn't allowed is always REGRESSED."""
    allowed = expectedOn(entry)
    if verdict in allowed:
        return "OK"
    if verdict in ("error", "flaky"):
        return "REGRESSED"
    rank = harness.RANKS.get(verdict, 0)
    ranks = [harness.RANKS.get(v, 0) for v in allowed]
    if rank > max(ranks):
        return "REGRESSED"
    if rank < min(ranks):
        return "IMPROVED"
    return "CHANGED"


def entryFor(case, ref, verdict, old):
    """The ledger entry a run writes for a case's reference: the verdict expected on this
    platform (macOS writes its override only where it differs), the case's tags, and an
    allowed set kept (or given by the case's ALLOWED) when the verdict is in it."""
    entry = {"tier": case.TIER, "classes": list(case.CLASSES), "axes": list(case.AXES)}
    for field, value in (
        ("issue", case.ISSUE),
        ("found_by", case.FOUND_BY),
        ("accepted", case.ACCEPTED.get(ref)),
    ):
        if value:
            entry[field] = value
    allowed = case.ALLOWED.get(ref)
    value = list(allowed) if allowed and verdict in allowed else verdict
    return entry | expectation(value, verdict, old)


def expectation(value, verdict, old):
    """The `expected` and `macos` fields a run writes: on macOS the override only, where it
    differs from the Windows verdict; elsewhere the verdict, or the old allowed set if the
    verdict is in it, with the old override kept."""
    old = old or {}
    if platform() == "macos":
        base = old.get("expected", value)
        fields = {"expected": base}
        if verdict not in (base if isinstance(base, list) else [base]):
            fields["macos"] = value
        return fields
    previous = old.get("expected")
    if isinstance(previous, list) and not isinstance(value, list) and verdict in previous:
        value = previous
    fields = {"expected": value}
    if "macos" in old:
        fields["macos"] = old["macos"]
    return fields


def randomEntry(verdict, old):
    return {"tier": "F", "classes": [], "axes": []} | expectation(verdict, verdict, old)


def gitState(folder):
    """(sha, dirty) of the checkout holding the folder: dirty when anything but the ledgers
    differs from HEAD. FREECAD_SCENARIO_SHA overrides the sha (a CI run)."""
    sha = os.environ.get("FREECAD_SCENARIO_SHA")
    if sha:
        return sha, False
    try:
        sha = subprocess.run(
            ["git", "-C", folder, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=60
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", folder, "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return "unknown", False
    dirty = [line for line in status if f"/{LEDGER}/" not in line.replace("\\", "/")]
    return sha or "unknown", bool(dirty)


# ---------------------------------------------------------------------------------------------
# The run as a whole (TestCorpusGate holds one)
# ---------------------------------------------------------------------------------------------


class Run:
    """One tier's run of the case folders: what runs, the verdicts so far, and the end."""

    def __init__(self):
        self.tier = tier()
        self.started = time.monotonic()
        self.time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.modules, self.inTree = loadModules()
        self.child = os.environ.get(CHILD)  # the score file of tier F's second process
        self.verdicts = {}  # {key: Outcome}
        self.caseRuns = {}  # {(case, config): ({ref: Outcome}, seconds)}
        self.timings = {}  # {case: seconds}
        self.lines = []  # the comparison lines (REGRESSED, ...), for the summary
        self.ledgers = {m.name: readLedger(m.ledgerPath) for m in self.modules}
        if self.tier == "F" and self.inTree:
            self.ledgers[RANDOM_MODULE] = readLedger(self.randomLedgerPath)
        self.seeds = randomSeeds() if self.tier == "F" and self.inTree else []
        self.childProcess = None
        # {key: (module, case, ref, config)} of what this tier runs
        self.planned = {}
        for module in self.modules:
            for case in module.cases:
                for config in configsFor(case, self.tier):
                    for ref in case.REFS:
                        self.planned[key(case.__name__, ref, config)] = (module.name, case, ref, config)
        for seed in self.seeds:
            k = key(f"Random{seed:04d}", "sequence", "V2s")
            self.planned[k] = (RANDOM_MODULE, None, "sequence", "V2s")

    @property
    def randomLedgerPath(self):
        return os.path.join(self.modules[0].folder if self.modules else ".", LEDGER, RANDOM_MODULE + ".json")

    def moduleOf(self, case):
        return next(m for m in self.modules if case in m.cases)

    def outcomes(self, case, config):
        """{ref: Outcome} of the case in the configuration, run once."""
        return self.results(case, config)[0]

    def results(self, case, config):
        """({ref: Outcome}, the harness's results or None), run once."""
        if (case, config) not in self.caseRuns:
            outcomes, results, seconds = runCase(case, config)
            self.caseRuns[(case, config)] = (outcomes, results)
            self.timings[case.__name__] = self.timings.get(case.__name__, 0.0) + seconds
            if not config.startswith("V2si"):  # the oracle's runs aren't ledger entries
                for ref, outcome in outcomes.items():
                    self.verdicts[key(case.__name__, ref, config)] = outcome
        return self.caseRuns[(case, config)]

    def randomOutcome(self, seed):
        k = key(f"Random{seed:04d}", "sequence", "V2s")
        if k not in self.verdicts:
            started = time.monotonic()
            self.verdicts[k] = runRandom(seed)
            self.timings[f"Random{seed:04d}"] = time.monotonic() - started
        return k, self.verdicts[k]

    def entry(self, module, k):
        ledger = self.ledgers.get(module)
        return ledger["entries"].get(k) if ledger else None

    def judge(self, module, k, outcome):
        """The comparison of a key's outcome with its ledger entry: (status, line)."""
        ledger = self.ledgers.get(module)
        entry = ledger["entries"].get(k) if ledger else None
        if entry is None:
            status = "NEW" if ledger else "UNLEDGERED"
            line = f"CORPUS {status} {k} {outcome.verdict}"
        else:
            status = compare(entry, outcome.verdict)
            line = f"CORPUS {status} {k} {'/'.join(expectedOn(entry))} -> {outcome.verdict}"
        if status != "OK":
            self.lines.append((status, line))
            say(line)
            if status in ("IMPROVED", "CHANGED") and os.environ.get("GITHUB_ACTIONS"):
                say(f"::warning title=Corpus {status}::{line}")
        return status, line

    # Tier F's second process

    def startChild(self):
        """Tier F: the same run in another process under another naming hash seed, started at
        once so the two run side by side. Off in the child itself and with
        FREECAD_SCENARIO_CHILD_SEED=none."""
        seed = os.environ.get("FREECAD_SCENARIO_CHILD_SEED", CHILD_SEED)
        if self.tier != "F" or self.child or seed.lower() == "none":
            return
        if os.environ.get("FREECAD_NAMING_HASH_SEED") == seed:
            seed = "1"
        from PartDesignTests.TestNamingDump import _freecadCmd
        import tempfile

        work = tempfile.mkdtemp(prefix="corpus-seed-")
        script = os.path.join(work, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(CHILD_SCRIPT)
        env = dict(os.environ)
        out = os.path.join(work, "verdicts.jsonl")
        env.update({CHILD: out, "FREECAD_NAMING_HASH_SEED": seed, "FREECAD_SCENARIO_ORACLE": "0"})
        env.pop("FREECAD_SCENARIO_UPDATE_LEDGER", None)
        log = open(os.path.join(work, "child.log"), "w", encoding="utf-8")
        self.childProcess = (
            subprocess.Popen(
                [_freecadCmd(), script], env=env, cwd=work, stdout=log, stderr=subprocess.STDOUT
            ),
            out,
            seed,
            work,
        )

    def childVerdicts(self):
        """{key: verdict} of the second process, after it ends (None without one)."""
        if not self.childProcess:
            return None
        proc, out, seed, work = self.childProcess
        try:
            proc.wait(timeout=7200)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise harness.ScenarioError(f"the hash seed {seed} run didn't end ({work})")
        if not os.path.isfile(out):
            raise harness.ScenarioError(f"the hash seed {seed} run wrote no verdicts ({work})")
        with open(out, encoding="utf-8") as fh:
            return {k: v for line in fh if line.strip() for k, v in json.loads(line).items()}

    def markFlaky(self, other):
        """Keys whose verdict differs in the second process become `flaky`."""
        differ = []
        for k, outcome in self.verdicts.items():
            if k in other and other[k] != outcome.verdict:
                differ.append(f"{k}: {outcome.verdict} / {other[k]}")
                outcome.message = f"flaky: {outcome.verdict} here, {other[k]} under the other seed"
                outcome.verdict = "flaky"
        return differ

    # The end

    def existing(self, module):
        """The (case, ref) pairs of a module's cases."""
        return {
            (case.__name__, ref) for m in self.modules if m.name == module for case in m.cases
            for ref in case.REFS
        }

    def stale(self):
        """Entries without their case: a case or reference removed or renamed, and in tier G a
        tier G entry that didn't run (its case moved to tier F). Tier F keeps the entries of
        configurations it didn't run (the report columns, other sizes)."""
        found = []
        for module, ledger in self.ledgers.items():
            if not ledger or (module == RANDOM_MODULE and not self.seeds):
                continue
            if any(m.name == module and m.module is None for m in self.modules):
                continue  # the module didn't import: its own test fails
            pairs = self.existing(module)
            for k, entry in ledger["entries"].items():
                case, ref, config = k.split("|")
                if module == RANDOM_MODULE:
                    gone = k not in self.planned
                elif self.tier == "G":
                    gone = entry.get("tier") == "G" and config == "V2s" and k not in self.planned
                else:
                    gone = (case, ref) not in pairs
                if gone:
                    found.append(k)
        return sorted(found)

    def updateLedgers(self, where=None):
        """Writes each module's ledger from the run (FREECAD_SCENARIO_UPDATE_LEDGER=1, in place;
        or into the folder `where`, FREECAD_SCENARIO_LEDGER_OUT, for CI's artifact). Tier G
        updates its own entries only; tier F rewrites the module (stale entries go)."""
        written = []
        for module in self.modules:
            if module.module is None:
                continue
            old = (self.ledgers.get(module.name) or {}).get("entries", {})
            if self.tier == "F":
                pairs = self.existing(module.name)
                entries = {k: e for k, e in old.items() if tuple(k.split("|")[:2]) in pairs}
            else:
                entries = dict(old)
            for case in module.cases:
                for config in configsFor(case, self.tier):
                    for ref in case.REFS:
                        k = key(case.__name__, ref, config)
                        if k in self.verdicts:
                            entries[k] = entryFor(case, ref, self.verdicts[k].verdict, old.get(k))
            sha, dirty = gitState(module.folder)
            run = {
                "sha": sha,
                "dirty": dirty,
                "platform": platform(),
                "time": self.time,
                "tier": self.tier,
                "cases": len(module.cases),
            }
            path = os.path.join(where, module.name + ".json") if where else module.ledgerPath
            writeLedger(path, run, entries)
            written.append(path)
        if self.seeds:
            old = (self.ledgers.get(RANDOM_MODULE) or {}).get("entries", {})
            entries = {}
            for seed in self.seeds:
                k = key(f"Random{seed:04d}", "sequence", "V2s")
                if k in self.verdicts:
                    entries[k] = randomEntry(self.verdicts[k].verdict, old.get(k))
            sha, dirty = gitState(self.modules[0].folder if self.modules else ".")
            run = {"sha": sha, "dirty": dirty, "platform": platform(), "time": self.time,
                   "tier": self.tier, "cases": len(self.seeds)}
            path = os.path.join(where, RANDOM_MODULE + ".json") if where else self.randomLedgerPath
            writeLedger(path, run, entries)
            written.append(path)
        return written

    def counts(self):
        sets = {"wrong": 0, "loud": 0, "right": 0, "neither": 0}
        for outcome in self.verdicts.values():
            s = harness.SETS.get(outcome.verdict, "neither")
            sets["loud" if s.startswith("loud") else s] += 1
        return sets

    def summary(self):
        """The run's last lines: the counts, the comparisons, the slow cases and, for tier F,
        the header line the merge guard looks for in the PR description."""
        sets = self.counts()
        cases = sum(len(m.cases) for m in self.modules)
        seconds = time.monotonic() - self.started
        statuses = [s for s, _ in self.lines]
        lines = [
            f"CORPUS tier {self.tier}: {cases} cases, {len(self.verdicts)} verdicts, "
            f"{sets['wrong']} wrong / {sets['loud']} loud / {sets['right']} right"
            + (f" / {sets['neither']} neither" if sets["neither"] else "")
            + f"; {statuses.count('REGRESSED')} regressed, {statuses.count('IMPROVED')} improved, "
            f"{statuses.count('CHANGED')} changed, {statuses.count('NEW')} new, "
            f"{statuses.count('STALE')} stale; {seconds:.0f} s"
        ]
        slow = sorted(self.timings.items(), key=lambda kv: -kv[1])
        for name, secs in slow[:5]:
            lines.append(f"CORPUS time {name} {secs:.1f} s")
        if self.tier == "G":
            for name, secs in slow:
                if secs > TIER_G_SECONDS:
                    lines.append(f"CORPUS slow {name} {secs:.1f} s: over {TIER_G_SECONDS} s, move it to tier F")
        if self.tier == "F" and not self.child:
            sha, dirty = gitState(self.modules[0].folder if self.modules else ".")
            neither = f" {sets['neither']} neither" if sets["neither"] else ""
            lines.append(
                f"Tier F: {sha[:10]}{' dirty' if dirty else ''} {platform()} {self.time} {cases} "
                f"{sets['wrong']}/{sets['loud']}/{sets['right']}{neither}"
            )
        return lines


CHILD_SCRIPT = """import os, traceback, unittest
try:
    suite = unittest.defaultTestLoader.loadTestsFromName("PartDesignTests.TestCorpusGate")
    with open(os.environ["FREECAD_SCENARIO_CORPUS_CHILD"] + ".log", "w") as log:
        unittest.TextTestRunner(stream=log, verbosity=1).run(suite)
except Exception:
    with open(os.environ["FREECAD_SCENARIO_CORPUS_CHILD"] + ".error", "w") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
"""


def writeChildVerdicts(run):
    with open(run.child, "w", encoding="utf-8") as fh:
        for k, outcome in sorted(run.verdicts.items()):
            fh.write(json.dumps({k: outcome.verdict}) + "\n")
