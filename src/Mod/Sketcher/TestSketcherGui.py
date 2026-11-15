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
from SketcherTests.TestSketchDxfGui import TestSketchDxfGui  # FreeCAD-CH, the DXF lane
from SketcherTests.TestSketchModelPicksGui import TestSketchModelPicksGui  # FreeCAD-CH, ops#634
from SketcherTests.TestSketchMidpointPicksGui import (  # FreeCAD-CH, selection parity 10 (b)
    TestModelEdgeMidpointMarkerGui,
    TestSketchModelMidpointPickGui,
    TestSketchModelArcMidpointPickGui,
)
from SketcherTests.TestSketchModelFacesGui import TestSketchModelFacesGui  # FreeCAD-CH, ops#640
from SketcherTests.TestSketchConstraintToolsGui import TestSketchConstraintToolsGui  # FreeCAD-CH, ops#640
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
    TestSketchSplitCircleGui,  # FreeCAD-CH, ops#656 F3
    TestSketchSplitCirclePicksGui,  # FreeCAD-CH, sketcher 3 (hand-check 6)
    TestSketchSplitIntersectionGui,  # FreeCAD-CH, sketcher 3 (hand-check 6)
    TestSketchTrimCrossingGui,  # FreeCAD-CH, sketcher 4 (Onshape SK19-SK22, SK24)
    TestSketchTrimPointsGui,  # FreeCAD-CH, sketcher 4 (Onshape SK23-SK25)
    TestSketchExtendGui,  # FreeCAD-CH, sketch tools 2 (Onshape GA3-25)
    TestSketchTrimDragGui,  # FreeCAD-CH, sketch tools 2 (Onshape GA3-25)
)
from SketcherTests.TestSketchRound3Gui import (  # FreeCAD-CH, ops#640 (sketch round 3)
    TestSketchModelInferenceGui,
    TestSketchModelInferenceOnFaceGui,
    TestSketchModelArcMidpointGui,  # FreeCAD-CH, selection parity 10 (c)
    TestSketchModelArcMidpointOnFaceGui,
    TestSketchConflictKeptGui,
    TestSketchOverdefinedRedGui,
    TestSketchOnshapeConstraintsGui,
    TestSketchOnshapeShapesGui,
)
from SketcherTests.TestSketchPatternGui import TestSketchPatternToolsGui  # FreeCAD-CH, ops#725
from SketcherTests.TestSketchRound4Gui import (  # FreeCAD-CH, ops#640 (sketch round 4)
    TestSketchToolbarFeaturesGui,
    TestSketchMirrorToolFirstGui,
    TestSketchTransformToolFirstGui,
    TestSketchOtherPartSnapGui,
)
from SketcherTests.TestSketchCancelGui import TestSketchCancelGui  # FreeCAD-CH, ops#640 (round 5)

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
    and TestModelEdgeMidpointMarkerGui
    and TestSketchModelMidpointPickGui
    and TestSketchModelArcMidpointPickGui
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
    and TestSketchModelFacesGui
    and TestSketchConstraintToolsGui
    and TestSketchModelInferenceGui
    and TestSketchModelInferenceOnFaceGui
    and TestSketchConflictKeptGui
    and TestSketchOverdefinedRedGui
    and TestSketchOnshapeConstraintsGui
    and TestSketchOnshapeShapesGui
    and TestSketchToolbarFeaturesGui
    and TestSketchMirrorToolFirstGui
    and TestSketchTransformToolFirstGui
    and TestSketchPatternToolsGui
    and TestSketchOtherPartSnapGui
    and TestSketchCancelGui
    else False
)
