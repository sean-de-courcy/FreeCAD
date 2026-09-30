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

Configurations: V2 for every scenario, V2multi (the multi-match flags on) for the scenarios whose
consumers the flags touch. FREECAD_SCENARIO_CONFIGS=V1,V2,V2multi runs the listed ones for every
scenario instead (the scorecard's local run). Every verdict is printed as a `SCORE` line.
"""

import os
import traceback
import unittest

from PartDesignTests.Scenarios import harness
from PartDesignTests.Scenarios import attachment, booleans, dressups, patterns, sketch_edits
from PartDesignTests.Scenarios import uptoface

AREAS = (sketch_edits, dressups, attachment, uptoface, patterns, booleans)


def configsFor(scenario):
    listed = os.environ.get("FREECAD_SCENARIO_CONFIGS")
    if listed:
        return [c.strip() for c in listed.split(",") if c.strip()]
    return ["V2", "V2multi"] if scenario.MULTI else ["V2"]


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
        classes[scenario.__name__] = type(scenario.__name__, (ScenarioTestCase,), attributes)
    return classes


globals().update(_makeTests())
__all__ = [name for name, value in globals().items()
           if isinstance(value, type) and issubclass(value, ScenarioTestCase)
           and value is not ScenarioTestCase]
