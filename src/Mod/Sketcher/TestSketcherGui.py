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
    else False
)
