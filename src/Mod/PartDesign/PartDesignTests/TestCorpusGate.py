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

"""The naming corpus's gate (FreeCAD-CH, ops#506; Scenarios/corpus.py, Scenarios/README.md).

`FreeCADCmd -t PartDesignTests.TestCorpusGate`, with FREECAD_SCENARIO_TIER=G (the default: CI's
step "Naming corpus gate") or F (the full set, before every push). Not part of `-t 0`.

One test class per case (`Case_<case>`), one test per reference and configuration,
`test_<ref>_<config>`: it fails when the verdict is REGRESSED against the case's ledger entry,
when the entry is missing (NEW) or the case's run failed (`error`). IMPROVED and CHANGED pass with
a line (and a CI warning): the merge guard refuses them until the ledger is updated. Then
`Module_<module>` (the module imports), in tier F `Random_Sequences` (`test_seed<NNNN>`) and
`test_<ref>_V2siOracle` (V2si gives what V2s gives), `Stale_Entries` (entries without their case,
variant or module),
and last, in tier F, `TierFSeeds` (every verdict the same under a second naming hash seed; one
that differs is `flaky`). The module's end prints the summary and, in tier F, the `Tier F:` line
for the PR description: `failed` where any test failed or errored other than by a ledger comparison
(Tracked). Tier F runs every configuration a case's ledger holds (corpus.Run.configsFor).

Environment: FREECAD_SCENARIO_UPDATE_LEDGER=1 writes the ledgers from the run (in place);
FREECAD_SCENARIO_LEDGER_OUT=<folder> writes them there instead (CI's would-be ledgers);
FREECAD_SCENARIO_MODULES=<folder>[;<folder>] runs the case modules of other folders (an attacker's
inbox); FREECAD_SCENARIO_CONFIGS, _SCALES, _SEEDS (`none` skips them), _STEPS,
_CHILD_SEED (`none` skips the second process) and FREECAD_SCENARIO_ORACLE=0 shape tier F.
"""

import os
import re
import unittest

from PartDesignTests.Scenarios import corpus, harness

RUN = corpus.Run()
FAILING = ("REGRESSED", "NEW", "STALE")


def setUpModule():
    RUN.startChild()


def tearDownModule():
    if RUN.child:
        corpus.writeChildVerdicts(RUN)
        return
    written = []
    out = os.environ.get("FREECAD_SCENARIO_LEDGER_OUT")
    if out:
        written += RUN.updateLedgers(out)
    if os.environ.get("FREECAD_SCENARIO_UPDATE_LEDGER") == "1":
        written += RUN.updateLedgers()
    for path in written:
        corpus.say(f"CORPUS ledger written: {path}")
    for line in RUN.summary():
        corpus.say(line)


def oracleOn():
    return RUN.tier == "F" and os.environ.get("FREECAD_SCENARIO_ORACLE", "1") != "0"


def testName(text):
    return re.sub(r"\W", "_", text)


class Tracked(unittest.TestCase):
    """Every test of the gate: one that fails or errors other than by a ledger comparison
    (REGRESSED, NEW, STALE: the ledger fingerprint covers those) makes the Tier F line say
    `failed` (fork PR 381 R3-5: a second hash seed's process that crashed)."""

    comparisonFailed = False

    def run(self, result=None):
        if result is None:
            return super().run(result)
        before = len(result.failures) + len(result.errors)
        self.comparisonFailed = False
        out = super().run(result)
        if len(result.failures) + len(result.errors) > before and not self.comparisonFailed:
            RUN.testFailures.append(self.id())
        return out


class CaseTest(Tracked):
    case = None
    module = None

    def check(self, ref, config):
        outcome = RUN.outcomes(self.case, config)[ref]
        k = corpus.key(self.case.__name__, ref, config)
        corpus.say(f"CORPUS VERDICT {k} {outcome.verdict}")
        status, line = RUN.judge(self.module, k, outcome)
        self.comparisonFailed = outcome.verdict != "error" and status in FAILING
        if outcome.verdict == "error" or status in FAILING:
            self.fail(f"{line}\n{outcome.message}")

    def checkOracle(self, ref):
        """V2si gives the reference what V2s gives it, after every step (ops#6)."""
        from PartDesignTests import TestNamingScenarios as scenarios

        plain, interned = RUN.results(self.case, "V2s")[1], RUN.results(self.case, "V2si")[1]
        if plain is None or interned is None:
            RUN.failures.append(f"{self.case.__name__}|{ref} oracle run")
            self.fail(f"{self.case.__name__}: a run failed (its V2s tests say why)")
        a = scenarios._stepRecords(plain[ref])
        b = scenarios._stepRecords(interned[ref])
        self.assertEqual([s for s, _ in b], [s for s, _ in a])
        for (step, x), (_, y) in zip(a, b):
            differ = [
                f
                for f in scenarios.ORACLE_FIELDS
                if scenarios._oracleValue(x, f) != scenarios._oracleValue(y, f)
            ]
            if differ:
                corpus.say(f"CORPUS ORACLE {corpus.key(self.case.__name__, ref, 'V2si')} {differ}")
                RUN.failures.append(f"{self.case.__name__}|{ref} oracle")
                self.fail(f"{ref} after {step}: V2si differs from V2s in {differ}")


def _makeTests():
    classes = {}
    for module in RUN.modules:
        if module.module is None:

            def imports(self, module=module):
                self.fail(f"the case module {module.name} doesn't import:\n{module.error}")

            classes[f"Module_{testName(module.name)}"] = type(
                f"Module_{testName(module.name)}", (Tracked,), {"test_imports": imports}
            )
            continue
        for case in module.cases:
            attributes = {"case": case, "module": module.name, "__doc__": case.__doc__}
            configs = RUN.configsFor(case, module.name)
            for ref in case.REFS:
                for config in configs:

                    def test(self, ref=ref, config=config):
                        self.check(ref, config)

                    test.__name__ = f"test_{ref}_{testName(config)}"
                    attributes[test.__name__] = test
                if oracleOn() and "V2s" in configs:

                    def oracle(self, ref=ref):
                        self.checkOracle(ref)

                    oracle.__name__ = f"test_{ref}_V2siOracle"
                    attributes[oracle.__name__] = oracle
            if len(attributes) > 3:
                name = f"Case_{case.__name__}"
                classes[name] = type(name, (CaseTest,), attributes)
    return classes


globals().update(_makeTests())


class Random_Sequences(Tracked):
    """Tier F: random edit sequences in V2s (Scenarios/randomized.py), one ledger entry each."""


def _makeRandomTests():
    for seed in RUN.seeds:

        def test(self, seed=seed):
            k, outcome = RUN.randomOutcome(seed)
            corpus.say(f"CORPUS VERDICT {k} {outcome.verdict}")
            status, line = RUN.judge(corpus.RANDOM_MODULE, k, outcome)
            self.comparisonFailed = outcome.verdict != "error" and status in FAILING
            if outcome.verdict == "error" or status in FAILING:
                self.fail(f"{line} (replay with FREECAD_SCENARIO_REPLAY={seed}:"
                          f"{os.environ.get('FREECAD_SCENARIO_STEPS', corpus.RANDOM_STEPS)})\n"
                          f"{outcome.message}")

        test.__name__ = f"test_seed{seed:04d}"
        setattr(Random_Sequences, test.__name__, test)


_makeRandomTests()


class Stale_Entries(Tracked):
    """No ledger entry has lost its case (a removed or renamed case or reference)."""

    def testNoStaleEntries(self):
        stale = RUN.stale()
        self.comparisonFailed = bool(stale)
        for k in stale:
            RUN.lines.append(("STALE", f"CORPUS STALE {k}"))
            corpus.say(f"CORPUS STALE {k}")
        self.assertEqual(stale, [], "ledger entries without their case")


class TierFSeeds(Tracked):
    """Tier F: the run under a second naming hash seed gives every verdict this run gives.
    Sorted after the other classes, so this run's verdicts are all in."""

    def testVerdictsUnderAnotherHashSeed(self):
        if RUN.tier != "F" or RUN.child or not RUN.childProcess:
            self.skipTest("tier F's second process only")
        other = RUN.childVerdicts()
        differ = RUN.markFlaky(other)
        for line in differ:
            RUN.lines.append(("FLAKY", f"CORPUS FLAKY {line}"))
            corpus.say(f"CORPUS FLAKY {line}")
        missing = sorted(set(RUN.verdicts) - set(other))
        self.assertEqual(differ, [], "verdicts that differ under another naming hash seed")
        self.assertEqual(missing, [], "verdicts the other process didn't give")


__all__ = [
    name
    for name, value in globals().items()
    if isinstance(value, type) and issubclass(value, unittest.TestCase)
    and value not in (CaseTest, Tracked) and not name.startswith("_")
]
