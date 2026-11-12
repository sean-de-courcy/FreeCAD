# SPDX-License-Identifier: LGPL-2.1-or-later

# **************************************************************************
#   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
#   Copyright (c) 2021 Emmanuel O'Brien                                   *
#                                                                         *
#   This file is part of the FreeCAD CAx development system.              *
#                                                                         *
#   This program is free software; you can redistribute it and/or modify  *
#   it under the terms of the GNU Lesser General Public License (LGPL)    *
#   as published by the Free Software Foundation; either version 2 of     *
#   the License, or (at your option) any later version.                   *
#   for detail see the LICENCE text file.                                 *
#                                                                         *
#   FreeCAD is distributed in the hope that it will be useful,            *
#   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
#   GNU Library General Public License for more details.                  *
#                                                                         *
#   You should have received a copy of the GNU Library General Public     *
#   License along with FreeCAD; if not, write to the Free Software        *
#   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
#   USA                                                                   *
# **************************************************************************

# Broken-out test modules
from SketcherTests.TestSketcherSolver import TestSketcherSolver
from SketcherTests.TestSketchFillet import TestSketchFillet
from SketcherTests.TestSketchExpression import TestSketchExpression
from SketcherTests.TestSketchValidateCoincidents import TestSketchValidateCoincidents
from SketcherTests.TestSketchCarbonCopyReverseMapping import TestSketchCarbonCopyReverseMapping
from SketcherTests.TestSketchInternalFaces import TestSketchInternalFaces
from SketcherTests.TestSketchNamesV1 import TestSketchNamesV1
from SketcherTests.TestSketcherEllipse import TestSketcherEllipse
from SketcherTests.TestSketchMissingExternal import (
    TestSketchMissingExternal,
    TestSketchMissingExternalSolver,
    TestSketchMissingExternalReturns,
    TestSketchMissingExternalReturnsSolver,
    TestSketchFaceLinkPairing,
    TestSketchFaceLinkPairingNoSolver,
    TestSketchFaceLinkPairing4m,
)
from SketcherTests.TestSketchExternalTypes import TestSketchExternalTypes
from SketcherTests.TestSketchExternalTypes import TestSketchImplicitExternals  # ops#634
from SketcherTests.TestSketchCarbonCopyElements import TestSketchCarbonCopyElements
from SketcherTests.TestSketchCarbonCopyElements import TestCarbonCopySelfReference
from SketcherTests.TestSketchCarbonCopyElements import TestCarbonCopyFlipped
from SketcherTests.TestSketchCarbonCopyElements import TestCarbonCopyFlippedInAMovedSketch
from SketcherTests.TestSketchCarbonCopyElements import TestCarbonCopyFlippedInATiltedSketch
from SketcherTests.TestSketchCornerSteps import TestSketchCornerSteps  # FreeCAD-CH, ops#640
from SketcherTests.TestSketchTrimSplit import TestSketchTrimSplit  # FreeCAD-CH, ops#656
from SketcherTests.TestSketchTrimSplitAttacks import TestSketchTrimSplitAttacks  # FreeCAD-CH, ops#656
from SketcherTests.TestSketchDxf import TestDxfReader, TestDxfFitting, TestDxfExport  # FreeCAD-CH, DXF lane
from SketcherTests.TestSketchDxf import TestDxfSkepticCases, TestDxfReviewCases  # FreeCAD-CH, DXF lane
from SketcherTests.TestSketchTrimSplit import TestSketchRepeatedConstraints  # FreeCAD-CH, ops#656
from SketcherTests.TestSketchTrimSplit import TestSketchArcMidpoint  # FreeCAD-CH, ops#656
from SketcherTests.TestSketchPierce import TestSketchPierce  # FreeCAD-CH, Onshape's Pierce
from SketcherTests.TestSketchExtend import (  # FreeCAD-CH, Onshape's Extend, Trim, Mirror
    TestSketchExtend,
    TestSketchTrimBounds,
    TestSketchMirrorLinked,
)
from SketcherTests.TestSketchConflicts import TestSketchConflicts  # FreeCAD-CH, ops#640
from SketcherTests.TestSketchPattern import (  # FreeCAD-CH, Onshape's sketch patterns
    TestSketchCircularPattern,
    TestSketchLinearPattern,
)

# Path and PartDesign tests use these functions that used to live here
# but moved to SketcherTests/TestSketcherSolver.py
from SketcherTests.TestSketcherSolver import CreateCircleSketch
from SketcherTests.TestSketcherSolver import CreateRectangleSketch
from SketcherTests.TestSketcherSolver import CreateSlotPlateSet
