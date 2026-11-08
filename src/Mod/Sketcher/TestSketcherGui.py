# SPDX-License-Identifier: LGPL-2.1-or-later
from SketcherTests.TestConstraintPreselectionGui import SketcherGuiTestCases
from SketcherTests.TestPolylineFilletGui import TestPolylineFilletGui
from SketcherTests.TestOnViewParameterGui import TestOnViewParameterGui
from SketcherTests.TestPlacementUpdate import TestSketchPlacementUpdate
from SketcherTests.TestExternalFacePreselection import TestExternalFacePreselection
from SketcherTests.TestAutoScaleNamesGui import TestAutoScaleNamesGui
from SketcherTests.TestSketchMissingExternalGui import TestSketchMissingExternalGui
from SketcherTests.TestSketchBrokenExternalTreeGui import TestSketchBrokenExternalTreeGui
from SketcherTests.TestSketchEditCameraGui import TestSketchEditCameraGui
from SketcherTests.TestDimensionInPlaceGui import TestDimensionInPlaceGui
from SketcherTests.TestSketchCameraOnEditGui import TestSketchCameraOnEditGui
from SketcherTests.TestAutoConstraintsGui import TestAutoConstraintsGui
from SketcherTests.TestSketchCopyElementsGui import TestSketchCopyElementsGui
from SketcherTests.TestSketchCopyElementsGui import TestMergeExternalPairingGui
from SketcherTests.TestSketchExternalTypes import TestSketchExternalTypesGui
from SketcherTests.TestSketchCommandsGui import TestSketchCommandsGui
from SketcherTests.TestSketchToolbarGui import TestSketchToolbarGui  # FreeCAD-CH, ops#605
from SketcherTests.TestSketchModelPicksGui import TestSketchModelPicksGui  # FreeCAD-CH, ops#634
from SketcherTests.TestSketchOnshapeGui import (  # FreeCAD-CH, ops#640
    TestSketchEscapeGui,
    TestSketchMidpointGui,
    TestSketchOverdefiningDimensionGui,
    TestSketchDeleteGui,
    TestSketchShiftInferenceGui,
    TestSketchColoursGui,
    TestSketchClosestMatchGui,
)
from SketcherTests.TestSketchHelpersGui import TestSketchHelpersGui  # FreeCAD-CH, ops#634
from SketcherTests.TestSketchOnshapeToolsGui import (  # FreeCAD-CH, ops#640 (C-tools)
    TestSketchToggleDrivingGui,
    TestSketchSlopedLineDimensionGui,
    TestSketchTangentArcGui,
    TestSketchFilletFieldsGui,
)

# Use the module so that code checkers don't complain (flake8)
(
    True
    if SketcherGuiTestCases
    and TestPolylineFilletGui
    and TestSketchPlacementUpdate
    and TestOnViewParameterGui
    and TestExternalFacePreselection
    and TestAutoScaleNamesGui
    and TestSketchMissingExternalGui
    and TestSketchBrokenExternalTreeGui
    and TestSketchEditCameraGui
    and TestDimensionInPlaceGui
    and TestSketchCameraOnEditGui
    and TestAutoConstraintsGui
    and TestSketchCopyElementsGui
    and TestMergeExternalPairingGui
    and TestSketchCommandsGui
    and TestSketchToolbarGui
    and TestSketchModelPicksGui
    and TestSketchEscapeGui
    and TestSketchMidpointGui
    and TestSketchOverdefiningDimensionGui
    and TestSketchDeleteGui
    and TestSketchShiftInferenceGui
    and TestSketchColoursGui
    and TestSketchClosestMatchGui
    and TestSketchHelpersGui
    and TestSketchToggleDrivingGui
    and TestSketchSlopedLineDimensionGui
    and TestSketchTangentArcGui
    and TestSketchFilletFieldsGui
    else False
)
