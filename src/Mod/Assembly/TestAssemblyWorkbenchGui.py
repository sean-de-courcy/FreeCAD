# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: the Assembly workbench's GUI tests (run in FreeCAD, not FreeCADCmd)

import TestApp

from AssemblyTests.TestOnshapeJointsGui import TestOnshapeJointsGui  # ops#640, rank 60

# Use the modules so that code checkers don't complain (flake8)
True if TestOnshapeJointsGui else False

from AssemblyTests.TestMateOffsetsGui import TestMateOffsetsGui  # ops#640, design C1

True if TestMateOffsetsGui else False

from AssemblyTests.TestConnectorPointsGui import TestConnectorPointsGui  # ops#640, design C3

True if TestConnectorPointsGui else False

from AssemblyTests.TestSnapModeGui import TestSnapModeGui  # ops#640, design C9

True if TestSnapModeGui else False

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

from AssemblyTests.TestTriadGui import (  # ops#640, C8 and C10
    TestTriadGui,
    TestTriadMouseGui,
    TestTriadOriginGui,
)

True if TestTriadGui else False
True if TestTriadMouseGui else False
True if TestTriadOriginGui else False
