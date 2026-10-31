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

"""Naming scenarios as tests (FreeCAD-CH, ops#5): one test class per scenario, one test per
reference and configuration, `<Scenario>.test_<ref>_<config>`. A test passes when its reference's
verdict is correct or equivalent (or broken, where the scenario expects the element to be gone).
Each scenario is built once per configuration, on its first test. See Scenarios/harness.py.
The naming corpus's cases (scenarios with CLASSES, Scenarios/cases/) aren't run here:
TestCorpusGate runs them against their ledgers (ops#506).

Configurations: V2s (the reference solver on, ops#7) for every scenario. The solver-off ones
(V1, V2, V2multi) don't run by default, in CI or locally (PLAN decision 179, ops#537: solver-off
and upstream files are deferred compatibility, decision 58); FREECAD_SCENARIO_CONFIGS=V1,V2,V2multi,V2s
runs the listed ones for every scenario instead (the scorecard's local run, or a change to the
solver-off path). MULTI marks the scenarios whose consumers V2multi's flags touch. Every verdict is
printed as a `SCORE` line.

The interning oracles (ops#6, Task 1): `test_<ref>_V2siOracle` runs the scenario in V2s and in V2si
(V2s with InternNames on) and requires the same verdict, stored subs, expanded names and solver tier
after every step. It asserts equality with V2s, not a correct verdict, so V2s's known failures need
no V2si entries. It runs by default, or when FREECAD_SCENARIO_CONFIGS lists V2si (the random
sequences then run V2si as a configuration of their own, below). `test_<ref>_V2iOracle` does the
same without the solver (V2i against V2); it runs only when FREECAD_SCENARIO_CONFIGS lists V2i.

The reference solver's determinism (ops#7): `SolverSeeded` runs the V2s scenarios and random
sequences in two child processes under two naming hash seeds, and their SCORE records must be equal.

Randomized edit sequences (Scenarios/randomized.py): `RandomSequences.test_seed<NNNN>_<config>`,
one test per seed and configuration, V2s; with FREECAD_SCENARIO_CONFIGS set, every
listed configuration, V1, V2i and V2si included (no oracle there: their verdicts must be correct;
the solver-off ones have no known-failure entries since decision 179, so a local run of V1, V2,
V2multi or V2i shows unlisted failures). It passes when every reference is as expected after
every step. By default seeds 1-4 with 8 steps each (CI); FREECAD_SCENARIO_SEEDS
("1-500", "3,7") and FREECAD_SCENARIO_STEPS change them, FREECAD_SCENARIO_REPLAY=<seed>:<steps>
runs one seed, and FREECAD_SCENARIO_GAP=1 plans the close-spaced series (ops#127, N3 6.2).
"""

import os
import re
import subprocess
import tempfile
import traceback
import unittest

from PartDesignTests.Scenarios import harness
from PartDesignTests.Scenarios import booleans, dressups, patterns, sketch_edits
from PartDesignTests.Scenarios import ambiguous, consumers, crossdoc, derived, external, internal
from PartDesignTests.Scenarios import issues
from PartDesignTests.Scenarios import fillet_limit, interning, moves, reorder
from PartDesignTests.Scenarios import pipe_legs
from PartDesignTests.Scenarios import rlist
from PartDesignTests.Scenarios import randomized, revolve_uptoface, splits, uptoface

AREAS = (
    sketch_edits,
    dressups,
    uptoface,
    revolve_uptoface,
    patterns,
    booleans,
    splits,
    external,
    internal,
    ambiguous,
    crossdoc,
    consumers,
    issues,
    rlist,
    interning,
    moves,
    reorder,
    fillet_limit,
    derived,
    pipe_legs,
)


def configsFor(scenario):
    listed = os.environ.get("FREECAD_SCENARIO_CONFIGS")
    if listed:
        return [c.strip() for c in listed.split(",") if c.strip() and c.strip() not in ORACLES]
    return ["V2s"]


# The interning oracles (ops#6): {interned configuration: the configuration it must equal}
ORACLES = {"V2i": "V2", "V2si": "V2s"}


def oracles():
    """The interned configurations whose oracle tests run: V2si by default; those listed in
    FREECAD_SCENARIO_CONFIGS when it is set."""
    listed = os.environ.get("FREECAD_SCENARIO_CONFIGS")
    if not listed:
        return ["V2si"]
    return [c.strip() for c in listed.split(",") if c.strip() in ORACLES]


# The fields of a SCORE record an interning oracle compares
ORACLE_FIELDS = (
    "verdict",
    "stored",
    "outcome",
    "subs",
    "names",
    "names_before",
    "subs_before",
    "tier",
    "guess",
)


GEOMETRY_ID = re.compile(r"\bg[0-9]+\b")
# The key of a Pipe's spine corner (`<key>;_;<tag>;PCV;...` and `PCR`, ops#415), at any escape
# level: a hash of the names of the lines at the corner, so of their geometry IDs too
CORNER_KEY = re.compile(r"\b[0-9a-f]{16}(?=\^*;_\^*;[^;]*;PC[VR]\^*;)")


def _oracleValue(record, field):
    """A record's field as the oracle compares it. Sketch geometry IDs in names are masked: a
    new geometry's ID comes from a process-wide counter, so it differs between two runs of a
    scenario (`models.notchDiscCircle`); `subs` still tells the elements apart. So are the keys
    of a Pipe's spine corners, which hash such IDs where a line was drawn anew (ops#551)."""
    value = record.get(field)
    if field in ("names", "names_before") and value:
        return [
            CORNER_KEY.sub("k#", GEOMETRY_ID.sub("g#", name)) if name else name for name in value
        ]
    return value


def _stepRecords(result):
    """[(step, record)] of a reference's Result or StepResults."""
    results = getattr(result, "results", [result])
    return [(r.step, r.record) for r in results]


class ScenarioTestCase(unittest.TestCase):
    scenario = None
    _runs = None  # {config: {ref: Result} or the traceback of a failed run}

    @classmethod
    def results(cls, config):
        if config not in cls._runs:
            try:
                cls._runs[config] = cls.scenario(config).run()
            except Exception:
                cls._runs[config] = traceback.format_exc()
        return cls._runs[config]

    def check(self, ref, config):
        results = self.results(config)
        if isinstance(results, str):
            raise harness.ScenarioError(f"{self.scenario.__name__} ({config}) failed:\n{results}")
        result = results[ref]
        if not result.passing:
            self.fail(f"{ref} is {result.verdict}: {result.message()}")

    def checkInterned(self, ref, config):
        """The interned configuration gives the reference what its plain one gives it, after
        every step (ops#6)."""
        base = ORACLES[config]
        runs = {c: self.results(c) for c in (base, config)}
        for c, results in runs.items():
            if isinstance(results, str):
                raise harness.ScenarioError(f"{self.scenario.__name__} ({c}) failed:\n{results}")
        plain = _stepRecords(runs[base][ref])
        interned = _stepRecords(runs[config][ref])
        self.assertEqual([step for step, _ in interned], [step for step, _ in plain])
        for (step, a), (_, b) in zip(plain, interned):
            differ = [f for f in ORACLE_FIELDS if _oracleValue(a, f) != _oracleValue(b, f)]
            if differ:
                lines = [f"  {f}: {base} {a.get(f)!r}\n    {config} {b.get(f)!r}" for f in differ]
                self.fail(
                    f"{ref} after {step}: {config} differs from {base} in {differ}:\n"
                    + "\n".join(lines)
                )


def _makeTests():
    classes = {}
    for scenario in harness.scenarioClasses(AREAS):
        attributes = {
            "scenario": scenario,
            "_runs": {},
            "__module__": __name__,
            "__doc__": scenario.__doc__,
        }
        for ref in scenario.REFS:
            for config in configsFor(scenario):

                def test(self, ref=ref, config=config):
                    self.check(ref, config)

                test.__name__ = f"test_{ref}_{config}"
                test.__doc__ = f"{scenario.__name__}: {ref} ({config})"
                attributes[test.__name__] = test
            for config in oracles():

                def oracle(self, ref=ref, config=config):
                    self.checkInterned(ref, config)

                oracle.__name__ = f"test_{ref}_{config}Oracle"
                oracle.__doc__ = f"{scenario.__name__}: {ref} ({config} equals {ORACLES[config]})"
                attributes[oracle.__name__] = oracle
        classes[scenario.__name__] = type(scenario.__name__, (ScenarioTestCase,), attributes)
    return classes


globals().update(_makeTests())


class CasesOnlyInCases(unittest.TestCase):
    """A scenario with CLASSES is a corpus case, which only TestCorpusGate runs, and only from
    Scenarios/cases/: one tagged in an area module would run nowhere."""

    def testNoCasesInAreaModules(self):
        misplaced = [f"{c.__module__}.{c.__name__}" for c in harness.scenarioClasses(AREAS, cases=True)]
        self.assertEqual(misplaced, [], "cases outside Scenarios/cases/: move them there")


class CorpusSetsAgree(unittest.TestCase):
    """scorecard.py's copies of the corpus's sets agree with the harness's (fork PR 381, L8; the
    ops repo's corpus_guard.py keeps a third copy)."""

    def testScorecardSets(self):
        from PartDesignTests.Scenarios import scorecard

        self.assertEqual(scorecard.SETS, harness.SETS)
        self.assertEqual(scorecard.EXPECT_RIGHT, harness.EXPECT_RIGHT)
        self.assertEqual(sorted(scorecard.VERDICTS), sorted(harness.VERDICTS))


class CorpusRules(unittest.TestCase):
    """The corpus's ledger rules without a run (Scenarios/corpus.py; fork PR 381's reviews)."""

    def testKindJudgesTheVerdict(self):
        """H1: under PARTIAL, partial-warned is right and its dropped warning REGRESSED; under
        BROKEN a break is right; inside the wrong set a silent wrong is worse than a warned one."""
        from PartDesignTests.Scenarios import corpus

        partial = {"expected": "partial-warned", "expect": "PARTIAL"}
        self.assertEqual(corpus.compare(partial, "partial-warned", "PARTIAL"), "OK")
        self.assertEqual(corpus.compare(partial, "wrong", "PARTIAL"), "REGRESSED")
        self.assertEqual(corpus.compare({"expected": "guessed-wrong"}, "wrong"), "REGRESSED")
        self.assertEqual(corpus.compare({"expected": "wrong"}, "guessed-wrong"), "IMPROVED")
        self.assertEqual(corpus.compare({"expected": "broken", "expect": "BROKEN"}, "broken", "CORRECT"),
                         "REGRESSED")
        self.assertEqual(harness.verdictSet("broken", "BROKEN"), "right")
        self.assertEqual(harness.verdictSet("partial-warned", "PARTIAL"), "right")
        self.assertEqual(harness.verdictSet("partial-warned", "CORRECT"), "wrong")
        for text, kind in (("BROKEN", "BROKEN"), ("BROKEN[pieces(x)]", "BROKEN"), ("PARTIAL[x]", "PARTIAL"),
                           ("OWN-OR-BROKEN[x]", "OWN-OR-BROKEN"), ("pieces(x)", "CORRECT"), (None, "CORRECT")):
            self.assertEqual(harness.expectKind(text), kind)

    def testAllowedAndAcceptedPerConfiguration(self):
        """R3-2 and H2: an allowed set comes from the case's ALLOWED now, not an old entry; ALLOWED
        and ACCEPTED are keyed by reference and configuration."""
        from PartDesignTests.Scenarios import corpus

        class Case(harness.Scenario):
            CLASSES, AXES, TIER, REFS = ("A",), ("M1",), "G", ("r",)
            ACCEPTED = {"r|V2": "decision 58"}
            ALLOWED = {"r|V2s": ["correct", "broken"]}

        old = {"expected": ["correct", "broken"]}
        outcome = corpus.Outcome("broken", {"expect": "face"})
        self.assertEqual(corpus.entryFor(Case, "r", "V2s", outcome, old)["expected"], ["correct", "broken"])
        self.assertNotIn("accepted", corpus.entryFor(Case, "r", "V2s", outcome, old))
        self.assertEqual(corpus.entryFor(Case, "r", "V2", outcome, None)["accepted"], "decision 58")
        self.assertEqual(corpus.entryFor(Case, "r", "V2", outcome, None)["tier"], "F")
        Case.ALLOWED = {}
        self.assertEqual(corpus.entryFor(Case, "r", "V2s", outcome, old)["expected"], "broken")
        self.assertEqual(corpus.tagProblems(Case), [])
        Case.ACCEPTED = {"r": "decision 58", "r|V2s": "yes"}
        self.assertEqual(len(corpus.tagProblems(Case)), 2)

    def testHashSeeds(self):
        """R3-3: seeds read as NamingHash.h reads them (strtoull, base 0, 0 = off)."""
        from PartDesignTests.Scenarios import corpus

        for text, value in (("2", 2), ("0x2", 2), (" 2", 2), ("010", 8), ("0", 0), ("", 0), (None, 0),
                            ("abc", 0), ("2 ", 0), ("08", 0), ("-1", 2**64 - 1)):
            self.assertEqual(corpus.hashSeed(text), value, text)


def randomRuns():
    """([seeds], steps) from the environment; FREECAD_SCENARIO_GAP sets the plans' spacing."""
    gap = os.environ.get("FREECAD_SCENARIO_GAP")
    if gap:
        randomized.setSpacing(gap)
    replay = os.environ.get("FREECAD_SCENARIO_REPLAY")
    if replay:
        seed, _, steps = replay.partition(":")
        return [int(seed)], int(steps or 8)
    seeds = []
    for part in os.environ.get("FREECAD_SCENARIO_SEEDS", "1-4").split(","):
        first, _, last = part.strip().partition("-")
        seeds += range(int(first), int(last or first) + 1)
    return seeds, int(os.environ.get("FREECAD_SCENARIO_STEPS", "8"))


class RandomSequences(unittest.TestCase):
    """Randomized edit sequences: a seed's model and edits are planned once (in V2, each state
    checked by a fresh build) and replayed in each configuration."""

    _plans = {}  # {seed: Plan or the traceback of a failed plan}

    def check(self, seed, steps, config):
        plans = type(self)._plans
        if seed not in plans:
            try:
                plans[seed] = randomized.makePlan(seed, steps)
            except Exception:
                plans[seed] = traceback.format_exc()
        plan = plans[seed]
        if isinstance(plan, str):
            raise harness.ScenarioError(f"seed {seed}: no plan:\n{plan}")
        results = randomized.RandomSequence(config, plan).run()
        bad = [r for r in results if not r.passing]
        if bad:
            self.fail(
                f"{len(bad)} references not as expected (replay with "
                f"FREECAD_SCENARIO_REPLAY={seed}:{steps}):\n{randomized.replayText(plan)}\n"
                + "\n".join(r.message() for r in bad[:5])
            )


def _makeRandomTests():
    seeds, steps = randomRuns()
    listed = os.environ.get("FREECAD_SCENARIO_CONFIGS")
    configs = (
        [c.strip() for c in listed.split(",") if c.strip()] if listed else ["V2s"]
    )
    for seed in seeds:
        for config in configs:

            def test(self, seed=seed, config=config):
                self.check(seed, steps, config)

            test.__name__ = f"test_seed{seed:04d}_{config}"
            test.__doc__ = f"Random sequence, seed {seed}, {steps} steps ({config})"
            setattr(RandomSequences, test.__name__, test)


_makeRandomTests()


# Set in the children of SolverSeeded, which run the scenarios only.
SEEDED_CHILD = "FREECAD_SCENARIO_SEEDED_CHILD"

SEEDED_CHILD_SCRIPT = """import os, traceback, unittest
try:
    suite = unittest.defaultTestLoader.loadTestsFromName("PartDesignTests.TestNamingScenarios")
    with open(os.environ["FREECAD_SCENARIO_SCORE_FILE"] + ".log", "w") as log:
        unittest.TextTestRunner(stream=log, verbosity=1).run(suite)
except Exception:
    with open(os.environ["FREECAD_SCENARIO_SCORE_FILE"] + ".error", "w") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
"""


class SolverSeeded(unittest.TestCase):
    """The reference solver doesn't depend on the order of the naming code's hash containers
    (ops#7, Task 2 PR 8): the V2s scenarios and random sequences run in two child processes,
    under FREECAD_NAMING_HASH_SEED 1 and 2, and every SCORE record is the same in both."""

    SEEDS = ("1", "2")

    def testScoresAreTheSameUnderTwoHashSeeds(self):
        if os.environ.get(SEEDED_CHILD):
            self.skipTest("a child process of SolverSeeded")
        from PartDesignTests.TestNamingDump import _freecadCmd

        workDir = tempfile.mkdtemp(prefix="solver-seeded-")
        script = os.path.join(workDir, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(SEEDED_CHILD_SCRIPT)
        runs = {}
        for seed in self.SEEDS:
            env = dict(os.environ)
            env[SEEDED_CHILD] = "1"
            env["FREECAD_NAMING_HASH_SEED"] = seed
            env["FREECAD_SCENARIO_CONFIGS"] = "V2s"
            out = os.path.join(workDir, f"seed{seed}.jsonl")
            env["FREECAD_SCENARIO_SCORE_FILE"] = out
            proc = subprocess.Popen(
                [_freecadCmd(), script],
                env=env,
                cwd=workDir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            runs[seed] = (proc, out)
        records = {}
        for seed, (proc, out) in runs.items():
            try:
                proc.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                proc.kill()
            error = out + ".error"
            if os.path.isfile(error):
                with open(error, encoding="utf-8") as fh:
                    self.fail(f"seed {seed}: the child failed:\n{fh.read()}")
            self.assertTrue(os.path.isfile(out), f"seed {seed}: no SCORE records ({workDir})")
            with open(out, encoding="utf-8") as fh:
                records[seed] = sorted(line.strip() for line in fh if line.strip())
        first, second = (records[seed] for seed in self.SEEDS)
        self.assertGreater(len(first), 0, f"no SCORE records ({workDir})")
        only = sorted(set(first) ^ set(second))
        self.assertEqual(
            first,
            second,
            f"{len(only)} SCORE records differ between FREECAD_NAMING_HASH_SEED "
            f"{' and '.join(self.SEEDS)} ({workDir}); the first:\n" + "\n".join(only[:4]),
        )


class HarnessSameSolid(unittest.TestCase):
    """The outcome checks' shape comparison doesn't depend on whether a shape carries a
    triangulation (ops#108). In the GUI a consumer's view provider meshes its shape and the
    oracle's shape isn't, and BoundBox uses a triangulation when there is one: a 10 mm block,
    fillet 1 on its front top edge, then fillet 0.25 on the arc that leaves at x = 0, is bounded
    to the block with one and 0.08 mm wider without."""

    def testTriangulationDoesNotMatter(self):
        import Part

        block = Part.makeBox(10, 10, 10)
        frontTop = [
            e
            for e in block.Edges
            if all(abs(v.Point.y) < 1e-9 and abs(v.Point.z - 10) < 1e-9 for v in e.Vertexes)
        ]
        filletA = block.makeFillet(1, frontTop)
        arc = [
            e
            for e in filletA.Edges
            if isinstance(e.Curve, Part.Circle) and abs(e.Curve.Center.x) < 1e-9
        ]
        self.assertEqual(len(arc), 1)
        meshed = filletA.makeFillet(0.25, arc)
        meshed.tessellate(0.1)
        fresh = filletA.makeFillet(0.25, arc)
        # The trap itself: equal solids, different BoundBox.
        self.assertGreater(abs(meshed.BoundBox.YMin - fresh.BoundBox.YMin), 0.01)
        self.assertEqual(harness.sameSolid(meshed, fresh), (True, ""))
        self.assertEqual(harness.sameSolid(fresh, meshed), (True, ""))


class HarnessGuessVerdicts(unittest.TestCase):
    """N2 7.2's verdicts for a guess rule's pick (ops#127), on report rows as
    App.getReferenceReport gives them: the `guessed-wrong` branch runs in no scenario yet."""

    EDGE = harness.edge("line", direction=harness.Z, through=(20, 0, 0))

    @staticmethod
    def rows(status="guessed", kind="piece"):
        return [{"property": "Base", "index": 0, "status": status, "guess_kind": kind}]

    def verdict(self, expectation, stored, verdict, rows):
        return harness.guessVerdict(expectation, stored, verdict, rows)

    def passing(self, expectation, verdict):
        result = harness.Result(None, None, "V2s", 0)
        result.record["expect"] = repr(expectation)
        result.verdict = verdict
        return result.passing

    def testExpectedBreakResolvedByAGuessIsWrong(self):
        verdict = self.verdict(harness.BROKEN, "wrong", "wrong", self.rows())
        self.assertEqual(verdict, "guessed-wrong")
        self.assertFalse(self.passing(harness.BROKEN, verdict))

    def testGuessAmongAnExpectedBreaksCandidatesPasses(self):
        expectation = harness.Broken(self.EDGE)
        verdict = self.verdict(expectation, "partial", "partial", self.rows())
        self.assertEqual(verdict, "guessed")
        self.assertTrue(self.passing(expectation, verdict))

    def testGuessOfTheExpectedElementPasses(self):
        verdict = self.verdict(self.EDGE, "correct", "correct", self.rows(kind="nearest"))
        self.assertEqual(verdict, "guessed")
        self.assertTrue(self.passing(self.EDGE, verdict))

    def testGuessOfAnotherElementIsWrong(self):
        verdict = self.verdict(self.EDGE, "wrong", "wrong", self.rows(kind="geometric"))
        self.assertEqual(verdict, "guessed-wrong")
        self.assertFalse(self.passing(self.EDGE, verdict))

    def testExpectedGuessResolvedPlainlyDoesNotPass(self):
        expectation = harness.Guessed(self.EDGE)
        verdict = self.verdict(expectation, "correct", "correct", [])
        self.assertEqual(verdict, "correct")
        self.assertFalse(self.passing(expectation, verdict))
        #   a warned resolution's record is no guess
        verdict = self.verdict(expectation, "correct", "correct", self.rows("resolved", "tier3"))
        self.assertEqual(verdict, "correct")

    def testBreakThatKeptItsRecordStaysBroken(self):
        """A1: a record survives a break; a correct break isn't turned into a wrong guess."""
        verdict = self.verdict(harness.BROKEN, "broken", "broken", self.rows("broken", "piece"))
        self.assertEqual(verdict, "broken")
        self.assertTrue(self.passing(harness.BROKEN, verdict))

    def testLoudBreakUnderALiveGuessPassesOwnOrBroken(self):
        """The consumer fails loudly after a guess rule's pick of the right element: right
        under `OwnOrBroken`, whose broken answer the guess doesn't turn into `guessed-wrong`;
        a wrong stored set still is."""
        expectation = harness.OwnOrBroken(self.EDGE)
        verdict = harness.guessVerdict(expectation.expected, "correct", "broken", self.rows(), True)
        self.assertEqual(verdict, "broken")
        self.assertTrue(self.passing(expectation, verdict))
        #   a plain expectation still takes the loud break for a wrong guess
        verdict = self.verdict(self.EDGE, "correct", "broken", self.rows())
        self.assertEqual(verdict, "guessed-wrong")
        #   a wrong stored set is `wrong` from `combine`, and a guess of it is guessed-wrong
        verdict = harness.guessVerdict(self.EDGE, "wrong", "wrong", self.rows(), True)
        self.assertEqual(verdict, "guessed-wrong")
        self.assertFalse(self.passing(expectation, verdict))

    def testContinuationOntoAnExtraElementIsWrong(self):
        """ops#286: a pick whose stored set is wrong is guessed-wrong even when the consumer's
        result is the same (ops#284: a chamfer continued onto an extra edge it leaves unchanged)."""
        verdict = self.verdict(self.EDGE, "wrong", "equivalent", self.rows(kind="continued"))
        self.assertEqual(verdict, "guessed-wrong")
        self.assertFalse(self.passing(self.EDGE, verdict))

    def testGeometryPickOfAWrongSetIsWrong(self):
        """A tier-3 pick (not a guess kind) of a wrong set with the same result (the
        verification of fork PR 256, M1)."""
        rows = self.rows("resolved", "tier3")
        verdict = self.verdict(self.EDGE, "wrong", "equivalent", rows)
        self.assertEqual(verdict, "equivalent")  # guessVerdict alone doesn't see it
        verdict = harness.pickedWrongSet("wrong", verdict, rows)
        self.assertEqual(verdict, "guessed-wrong")
        self.assertFalse(self.passing(self.EDGE, verdict))
        #   the expected element picked by geometry stays correct
        self.assertEqual(harness.pickedWrongSet("correct", "correct", rows), "correct")
        #   a record a break kept is no pick
        self.assertEqual(
            harness.pickedWrongSet("wrong", "equivalent", self.rows("broken", "tier3")),
            "equivalent",
        )
        #   nor is a guess the policy rejected
        self.assertEqual(
            harness.pickedWrongSet("wrong", "equivalent", self.rows("resolved", "rejected")),
            "equivalent",
        )

    def testExpansionToTheExpectedPiecesPasses(self):
        verdict = self.verdict(self.EDGE, "correct", "correct", self.rows(kind="expanded"))
        self.assertEqual(verdict, "guessed")
        self.assertTrue(self.passing(self.EDGE, verdict))


class HarnessSplitVerdicts(unittest.TestCase):
    """The corpus's `quiet` and `broken-` (ops#506), on report rows as App.getReferenceReport
    gives them: no scenario of the seed corpus reaches them yet."""

    EDGE = harness.edge("line", direction=harness.Z, through=(20, 0, 0))

    def split(self, verdict, stored, rows, warned=False, expectation=None):
        expectation = expectation or self.EDGE
        return harness.splitVerdict(verdict, stored, expectation, ["Edge3"], rows, warned)

    def testSamePlaceLevelIsQuiet(self):
        rows = [{"status": "resolved", "warning_level": "same-place", "evidence": ""}]
        self.assertEqual(self.split("correct", "correct", rows, warned=True), "quiet")
        #   a normal warning keeps it correct
        rows = [{"status": "resolved", "warning_level": "normal", "evidence": ""}]
        self.assertEqual(self.split("correct", "correct", rows, warned=True), "correct")

    def testTwinTradeIsQuiet(self):
        rows = [{"status": "resolved", "warning_level": "", "evidence": "moved by 2; its own twin"}]
        self.assertEqual(self.split("equivalent", "wrong", rows), "quiet")

    def testBreakWithoutTheElementIsBrokenMinus(self):
        rows = [{"status": "broken", "candidates": ["Edge1", "Edge2"]}]
        self.assertEqual(self.split("broken", "broken", rows), "broken-")
        rows = [{"status": "broken", "candidates": ["Edge3", "Edge2"]}]
        self.assertEqual(self.split("broken", "broken", rows), "broken")

    def testExpectedBreakAndFailedConsumerStayBroken(self):
        self.assertEqual(self.split("broken", "broken", [], expectation=harness.BROKEN), "broken")
        #   the reference holds its element, the consumer fails: no candidates to judge
        self.assertEqual(self.split("broken", "correct", []), "broken")

    def testSplitVerdictsPassWhereTheirsDo(self):
        for verdict, expectation, passing in (
            ("quiet", self.EDGE, True),
            ("broken-", harness.BROKEN, True),
            ("broken-", self.EDGE, False),
        ):
            result = harness.Result(None, None, "V2s", 0)
            result.record["expect"] = repr(expectation)
            result.verdict = verdict
            self.assertEqual(result.passing, passing, verdict)


class HarnessOracleMask(unittest.TestCase):
    """The interning oracle compares names with sketch geometry IDs and spine corner keys masked
    (ops#551), and nothing else."""

    PIPE = "_;g1^;_^;{Spine}^;SKT^;0^;E^;0^;SRC^;_;{Pipe};PSH;0;F;0;GEN;_"

    def masked(self, *names):
        return _oracleValue({"names": list(names)}, "names")

    def testCornerKeysAreMasked(self):
        for opCode in ("PCV", "PCR"):
            for name in (
                f"455f11a62c460362;_;{{Spine}};{opCode};0;V;0;SRC;_",
                f"_;_;{{Pipe}};FUS;0;F;0;MOD;_^;455f11a62c460362^^;_^^;{{Spine}}^^;{opCode}^^;0",
            ):
                other = name.replace("455f11a62c460362", "f86b35e64b0e82ca")
                self.assertEqual(self.masked(name), self.masked(other), name)
                self.assertNotIn("455f11a62c460362", self.masked(name)[0])

    def testOtherKeysAndNamesStay(self):
        for name in (
            "455f11a62c460362;_;{Spine};PLM;0;E;0;SRC;_",
            "455f11a62c460362;_;{Spine};PCX;0;V;0;SRC;_",
            "455f11a62c460362",
            self.PIPE + ";455f11a62c460362",
        ):
            self.assertIn("455f11a62c460362", self.masked(name)[0], name)
        self.assertNotEqual(self.masked(self.PIPE), self.masked(self.PIPE.replace("E^;0", "F^;0")))
        self.assertEqual(self.masked(self.PIPE), self.masked(self.PIPE.replace("g1", "g580675")))
        self.assertEqual(_oracleValue({"subs": ["Face6"]}, "subs"), ["Face6"])


class HarnessPinnedObject(unittest.TestCase):
    """A reference that must be on another object (Ref.on) is wrong there even when its element
    and its consumer's result are right (the review of fork PR 256, High 1)."""

    def judge(self, on):
        scenario = harness.Scenario("V2")
        scenario.doc = doc = scenario.newDocument("Pinned")
        try:
            box = doc.addObject("Part::Box", "Box")
            other = doc.addObject("Part::Box", "Other")
            other.Placement.Base = harness.V(50, 0, 0)
            doc.recompute()
            top = harness.face("plane", normal=harness.Z, through=(0, 0, 10))
            sketch = doc.addObject("Sketcher::SketchObject", "Sketch")
            sketch.AttachmentSupport = [(box, scenario.names(box, top)[0])]
            sketch.MapMode = "FlatFace"
            doc.recompute()
            ref = harness.Ref(
                "support", "Sketch", "AttachmentSupport", lambda: top, harness.Attached(),
                lambda: on,
            )
            return scenario.judge(ref, "edit")
        finally:
            scenario.cleanup()

    def testOnItsObjectIsCorrect(self):
        self.assertEqual(self.judge("Box").verdict, "correct")

    def testOnAnotherObjectIsWrong(self):
        result = self.judge("Other")
        self.assertEqual(result.verdict, "wrong")
        self.assertEqual(result.record["outcome"], "correct")
        self.assertFalse(result.passing)


__all__ = [
    name
    for name, value in globals().items()
    if isinstance(value, type)
    and issubclass(value, ScenarioTestCase)
    and value is not ScenarioTestCase
] + [
    "RandomSequences",
    "SolverSeeded",
    "HarnessSameSolid",
    "HarnessGuessVerdicts",
    "HarnessSplitVerdicts",
    "HarnessPinnedObject",
]
