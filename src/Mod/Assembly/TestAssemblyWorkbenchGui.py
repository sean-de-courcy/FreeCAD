# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: the Assembly workbench's GUI tests (run in FreeCAD, not FreeCADCmd)

import TestApp

from AssemblyTests.TestOnshapeJointsGui import TestOnshapeJointsGui  # ops#640, rank 60

# Use the modules so that code checkers don't complain (flake8)
True if TestOnshapeJointsGui else False

from AssemblyTests.TestOnshapeAssembliesGui import TestSeveralAssembliesGui  # ops#640, ops#651

True if TestSeveralAssembliesGui else False
