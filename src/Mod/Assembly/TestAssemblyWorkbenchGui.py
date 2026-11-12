# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: the Assembly workbench's GUI tests (run in FreeCAD, not FreeCADCmd)

import TestApp

from AssemblyTests.TestOnshapeJointsGui import TestOnshapeJointsGui  # ops#640, rank 60

# Use the modules so that code checkers don't complain (flake8)
True if TestOnshapeJointsGui else False

from AssemblyTests.TestMateOffsetsGui import TestMateOffsetsGui  # ops#640, design C1

True if TestMateOffsetsGui else False

from AssemblyTests.TestOnshapeAssembliesGui import (  # ops#640, ops#651
    TestSeveralAssembliesGui,
    TestJointErrorsGui,
    TestInsertStudioGui,
)

True if TestSeveralAssembliesGui else False
True if TestJointErrorsGui else False
True if TestInsertStudioGui else False

from AssemblyTests.TestOnshapeAssembliesGui import TestAssemblyListGui  # ops#640 round 10
from AssemblyTests.TestAssemblyPatternsGui import TestAssemblyPatternsGui  # FreeCAD-CH (asm-patterns)

True if TestAssemblyListGui else False
True if TestAssemblyPatternsGui else False
