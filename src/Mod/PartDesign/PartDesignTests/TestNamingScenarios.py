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

Configurations: V2 and V2s (the reference solver on, ops#7) for every scenario, V2multi (the
multi-match flags on) for the scenarios whose consumers the flags touch.
FREECAD_SCENARIO_CONFIGS=V1,V2,V2multi,V2s runs the listed ones for every scenario instead (the
scorecard's local run). Every verdict is printed as a `SCORE` line.

The interning oracle (ops#6, Task 1): `test_<ref>_V2iOracle` runs the scenario in V2 and in V2i
(V2 with InternNames on) and requires the same verdict, stored subs and expanded names after every
step. It asserts equality with V2, not a correct verdict, so V2's known failures need no V2i
entries. It runs by default, or when FREECAD_SCENARIO_CONFIGS lists V2i.
`test_<ref>_V2siOracle` does the same for the reference solver (V2s against V2si, the solver's
tiers included); it runs only when FREECAD_SCENARIO_CONFIGS lists V2si (local runs).

The reference solver's determinism (ops#7): `SolverSeeded` runs the V2s scenarios and random
sequences in two child processes under two naming hash seeds, and their SCORE records must be equal.

Randomized edit sequences (Scenarios/randomized.py): `RandomSequences.test_seed<NNNN>_<config>`,
one test per seed and configuration, V2, V2multi and V2s. It passes when every reference is as
expected after every step. By default seeds 1-4 with 8 steps each (CI); FREECAD_SCENARIO_SEEDS
("1-500", "3,7") and FREECAD_SCENARIO_STEPS change them, and FREECAD_SCENARIO_REPLAY=<seed>:<steps>
runs one seed.
"""

import os
import re
import subprocess
import tempfile
import traceback
import unittest

from PartDesignTests.Scenarios import harness
from PartDesignTests.Scenarios import attachment, booleans, dressups, patterns, sketch_edits
from PartDesignTests.Scenarios import ambiguous, consumers, crossdoc, external, internal, issues
from PartDesignTests.Scenarios import interning, moves, reorder
from PartDesignTests.Scenarios import rlist
from PartDesignTests.Scenarios import randomized, splits, uptoface

AREAS = (
    sketch_edits,
    dressups,
    attachment,
    uptoface,
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
)


def configsFor(scenario):
    listed = os.environ.get("FREECAD_SCENARIO_CONFIGS")
    if listed:
        return [c.strip() for c in listed.split(",") if c.strip() and c.strip() not in ORACLES]
    return ["V2", "V2s", "V2multi"] if scenario.MULTI else ["V2", "V2s"]


# The interning oracles (ops#6): {interned configuration: the configuration it must equal}
ORACLES = {"V2i": "V2", "V2si": "V2s"}


def oracles():
    """The interned configurations whose oracle tests run: V2i by default; those listed in
    FREECAD_SCENARIO_CONFIGS when it is set."""
    listed = os.environ.get("FREECAD_SCENARIO_CONFIGS")
    if not listed:
        return ["V2i"]
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


def _oracleValue(record, field):
    """A record's field as the oracle compares it. Sketch geometry IDs in names are masked: a
    new geometry's ID comes from a process-wide counter, so it differs between two runs of a
    scenario (`models.notchDiscCircle`); `subs` still tells the elements apart."""
    value = record.get(field)
    if field in ("names", "names_before") and value:
        return [GEOMETRY_ID.sub("g#", name) if name else name for name in value]
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


def randomRuns():
    """([seeds], steps) from the environment."""
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
        [c.strip() for c in listed.split(",") if c.strip()] if listed else ["V2", "V2multi", "V2s"]
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


__all__ = [
    name
    for name, value in globals().items()
    if isinstance(value, type)
    and issubclass(value, ScenarioTestCase)
    and value is not ScenarioTestCase
] + ["RandomSequences", "SolverSeeded", "HarnessSameSolid"]
