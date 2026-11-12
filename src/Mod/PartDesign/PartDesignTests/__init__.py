# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD

if FreeCAD.GuiUp:
    # FreeCAD-CH (ops#602): PartDesign shows the Features list in the Model panel in place of the
    # tree. The GUI tests drive the tree, so they run with it; TestFeaturesViewGui switches to the
    # list and back (PartDesign_ToggleModelTree flips the preference and applies it)
    import FreeCADGui
    import PartDesignGui  # noqa: F401 (the command)

    if not FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign").GetBool(
        "ShowModelTree", False
    ):
        FreeCADGui.runCommand("PartDesign_ToggleModelTree")

from . import TestBoolean
from . import TestBaseFeature
from . import TestChamfer
from . import TestCrossBody
from . import TestDatum
from . import TestDraft
from . import TestFillet
from . import TestFilletFailureText
from . import TestFilletPropagation
from . import TestHelix
from . import TestHole
from . import TestInvoluteGear
from . import TestLinearPattern
from . import TestLoft
from . import TestLoftOnshape
from . import TestMirrored
from . import TestMultiTransform
from . import TestPad
from . import TestPipe
from . import TestPocket
from . import TestPolarPattern
from . import TestCurvePattern
from . import TestPrimitive
from . import TestRevolve
from . import TestShapeBinder
from . import TestSuppressed
from . import TestThickness
from . import TestTopologicalNamingProblem
