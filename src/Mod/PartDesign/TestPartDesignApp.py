# SPDX-License-Identifier: LGPL-2.1-or-later

# **************************************************************************
#   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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

# ---------------------------------------------------------------------------
# define the test cases to test the FreeCAD PartDesign module
# ---------------------------------------------------------------------------

# datum tools
from PartDesignTests.TestDatum import (
    TestDatumPoint,
    TestDatumLine,
    TestDatumPlane,
    TestAttachedToACoordinateSystem,
    TestAttachedToACoordinateSystemInAPlacedBody,
)
from PartDesignTests.TestShapeBinder import TestShapeBinder
from PartDesignTests.TestShapeBinder import TestSubShapeBinder
from PartDesignTests.TestShapeBinder import (
    TestShapeBinderOfACoordinateSystem,
    TestShapeBinderOfACoordinateSystemInAPlacedBody,
    TestTracedBinderAcrossBodies,
)

# additive/subtractive features & primitives
from PartDesignTests.TestPad import (
    TestPad,
    TestUpToPlanePlacement,
    TestUpToPlanePlacementInAPlacedBody,
)
from PartDesignTests.TestPocket import TestPocket
from PartDesignTests.TestPocket import TestRefineKeepsAValidResult  # FreeCAD-CH, ops#640
from PartDesignTests.TestHelix import TestHelix
from PartDesignTests.TestHole import TestHole
from PartDesignTests.TestRevolve import TestRevolve
from PartDesignTests.TestPipe import TestPipe
from PartDesignTests.TestPipe import TestPipeEndNames  # FreeCAD-CH, ops#351
from PartDesignTests.TestPipe import TestPipeCorners  # FreeCAD-CH, ops#370
from PartDesignTests.TestPipe import TestJointsWhenABendStraightens  # FreeCAD-CH, ops#446
from PartDesignTests.TestPipe import TestBaseAfterAnInvalidPipe  # FreeCAD-CH, ops#310
from PartDesignTests.TestPipe import TestBaseAfterAnInvalidBaseFeature  # FreeCAD-CH, ops#310
from PartDesignTests.TestPipe import TestPipeAlongTiltedWaves, TestLoosePipeWarns  # FreeCAD-CH, ops#448
from PartDesignTests.TestPipe import TestRoundCornerNames  # FreeCAD-CH, ops#455
from PartDesignTests.TestPipe import TestBinormalPipe  # FreeCAD-CH, ops#406
from PartDesignTests.TestPipe import TestPipeNamesUnderSpineEdits  # FreeCAD-CH, ops#469, ops#435
from PartDesignTests.TestPipeOnshape import (  # FreeCAD-CH, sweeps as Onshape's (ops#640)
    TestPipeToolCheck,
    TestPipeProfileControl,
    TestPipeExtendToFullPath,
    TestPipeProfilePlacement,
    TestPipePathFromSeveralObjects,
    TestPipeEndAfterThePathGrows,
    TestThreadCapFollowsEdits,
    TestHelixTurnNamesNeverPass,
    TestPipeHelixTurnsCountFromTheStart,
    TestThreadToothOnTheCylinder,
    TestPipeSelfOverlap,
    TestPipeSelfOverlapUnion,
    TestPipeTwist,
    TestPipeScale,
    TestPipeLock,
    TestPipeThin,
)
from PartDesignTests.TestLoft import TestLoft
from PartDesignTests.TestLoftOnshape import (  # FreeCAD-CH, ops#655
    TestLoftOnshapePlain,
    TestLoftOnshapeConditions,
    TestLoftOnshapeThreeSections,
)
from PartDesignTests.TestLoftConnections import (  # FreeCAD-CH, ops#640
    TestLoftConnectionsTwist,
    TestLoftConnectionsUnequal,
)
from PartDesignTests.TestPrimitive import TestPrimitive
from PartDesignTests.TestPrimitive import TestBaseAfterARefine  # FreeCAD-CH, ops#474
from PartDesignTests.TestLostTool import TestLostTool  # FreeCAD-CH, ops#472
from PartDesignTests.TestHelix import TestHelix

# transformations and boolean
from PartDesignTests.TestMirrored import TestMirrored
from PartDesignTests.TestLinearPattern import TestLinearPattern
from PartDesignTests.TestPolarPattern import TestPolarPattern
from PartDesignTests.TestCurvePattern import TestCurvePattern
from PartDesignTests.TestMultiTransform import TestMultiTransform
from PartDesignTests.TestPatternRules import TestPatternRules  # FreeCAD-CH, ops#640
from PartDesignTests.TestFacePattern import TestFacePattern  # FreeCAD-CH, ops#655 T8
from PartDesignTests.TestDraftRules import TestDraftNeedsNeutralPlane  # FreeCAD-CH, ops#640
from PartDesignTests.TestHoleDepth import TestHoleDepth  # FreeCAD-CH, ops#640
from PartDesignTests.TestBoolean import TestBoolean
from PartDesignTests.TestBaseFeature import TestBaseFeature
from PartDesignTests.TestCrossBody import TestCrossBody
from PartDesignTests.TestAttachAcrossContainers import TestAttachAcrossContainers

# dressup features
from PartDesignTests.TestFillet import TestFillet
from PartDesignTests.TestFilletPropagation import TestFilletPropagation  # FreeCAD-CH, ops#655
from PartDesignTests.TestFilletFailureText import (  # FreeCAD-CH, ops#640 F2, ops#701
    TestFilletFailureText,
    TestMultiPartWarning,
    TestMultiPartLink,  # ops#701 F2c
)
from PartDesignTests.TestChamfer import TestChamfer
from PartDesignTests.TestDraft import (
    TestDraft,
    TestDressUpFaces,
    TestNeutralPlanePlacement,
    TestNeutralPlanePlacementInAPlacedBody,
)
from PartDesignTests.TestThickness import TestThickness
from PartDesignTests.TestMissingElements import TestMissingElements  # FreeCAD-CH, ops#69-71

# extras
from PartDesignTests.TestInvoluteGear import TestInvoluteGear
from PartDesignTests.TestSketch import TestSketch
from PartDesignTests.TestSuppressed import TestSuppressed

# Topological naming problem
from PartDesignTests.TestTopologicalNamingProblem import TestTopologicalNamingProblem
from PartDesignTests.TestNamingDump import TestNamingGolden, TestNamingSeeded
from PartDesignTests.TestNamingDump import TestNamingRepeated, TestNamingTagCollision
from PartDesignTests.TestNamingDump import TestNamingRevision  # FreeCAD-CH, ops#103
from PartDesignTests.TestNamingDump import TestNamingInterning  # FreeCAD-CH, ops#6
from PartDesignTests.TestNamingSave import *  # FreeCAD-CH, ops#6
from PartDesignTests.TestNamingLoad import *  # FreeCAD-CH, ops#6
from PartDesignTests.TestNamingScenarios import *  # one class per scenario (FreeCAD-CH, ops#5)
from PartDesignTests.TestNamingRList import TestNamingRList  # FreeCAD-CH, ops#5
from PartDesignTests.TestNamingSolver import TestNamingSolver  # FreeCAD-CH, ops#7
from PartDesignTests.TestNameGrowth import TestNameGrowth  # FreeCAD-CH, ops#640
from PartDesignTests.TestNamingRewrite import TestNamingRewrite  # FreeCAD-CH, ops#504
from PartDesignTests.TestMaplessNames import (  # FreeCAD-CH, ops#502, ops#633
    TestMaplessNames,
    TestDatumNamesAfterReopen,
)
from PartDesignTests.TestBetaMapless import TestBetaMapless  # FreeCAD-CH, ops#502
from PartDesignTests.TestNamingGate import TestNamingGate, TestNamingGateFile  # FreeCAD-CH, ops#103
from PartDesignTests.TestNamingConsumerPass import (  # FreeCAD-CH, ops#116
    TestNamingConsumerPass,
    TestNamingConsumerPassSolver,
)
from PartDesignTests.TestFailurePassThrough import (  # FreeCAD-CH, ops#126
    TestFailurePassThroughV2,
    TestFailurePassThroughV2s,
)
from PartDesignTests.TestBodyReorder import (  # FreeCAD-CH, ops#127
    TestBodyReorderV2,
    TestBodyReorderV2s,
)
from PartDesignTests.TestStudio import TestStudio  # FreeCAD-CH, ops#325
from PartDesignTests.TestStudioSequence import TestStudioSequence  # FreeCAD-CH, ops#602
from PartDesignTests.TestStudioSequence import TestHistoryOrder  # FreeCAD-CH, ops#632
from PartDesignTests.TestBarPlace import TestBarPlace  # FreeCAD-CH, ops#640 rank 34
from PartDesignTests.TestDeletePart import TestDeletePart  # FreeCAD-CH, ops#635
from PartDesignTests.TestRegenerate import (  # FreeCAD-CH, ops#640
    TestRegenerate,
    TestPatternWithoutOriginals,
    TestStoppedBody,
)
from PartDesignTests.TestNewPart import TestMapOrigin, TestNewPart  # FreeCAD-CH, ops#311
from PartDesignTests.TestNewPart import TestOperations  # FreeCAD-CH, ops#640
from PartDesignTests.TestRevolveOperations import TestRevolveOperations  # FreeCAD-CH, ops#640 rank 20
from PartDesignTests.TestRevolveFaceProfile import TestRevolveFaceProfile  # FreeCAD-CH, ops#640 #113
from PartDesignTests.TestSiblings import TestSiblings  # FreeCAD-CH, ops#325
from PartDesignTests.TestMerge import TestMerge  # FreeCAD-CH, ops#325
from PartDesignTests.TestSplit import TestSplit  # FreeCAD-CH, ops#325
from PartDesignTests.TestMergeScope import TestMergeScope  # FreeCAD-CH, ops#640
from PartDesignTests.TestResultRules import TestResultRules  # FreeCAD-CH, ops#640
from PartDesignTests.TestDatumPlanePoint import TestDatumPlanePoint  # FreeCAD-CH, ops#640
from PartDesignTests.TestPlaneEdgePoint import TestPlaneEdgePoint  # FreeCAD-CH, ops#673
from PartDesignTests.TestFlipKeepsTheSketch import TestFlipKeepsTheSketch  # FreeCAD-CH, ops#640
from PartDesignTests.TestFilletDeleteKeepsTheSketch import (  # FreeCAD-CH, ops#640
    TestFilletDeleteKeepsTheSketch,
)
from PartDesignTests.TestBooleanRules import TestBooleanRules  # FreeCAD-CH, ops#640
from PartDesignTests.TestSplitParts import TestSplitParts  # FreeCAD-CH, ops#640
from PartDesignTests.TestOnshapeEndTypes import TestOnshapeEndTypes  # FreeCAD-CH, ops#640
from PartDesignTests.TestProfileRegions import TestProfileRegions  # FreeCAD-CH, feat/profile-regions
from PartDesignTests.TestDerived import TestDerived  # FreeCAD-CH, ops#640 round 6
from PartDesignTests.TestDerivedFiles import TestDerivedFiles  # FreeCAD-CH, derived-design.md
from PartDesignTests.TestDerivedFollowUps import TestDerivedFollowUps  # FreeCAD-CH, derived-design.md
from PartDesignTests.TestPartStudioVariables import TestPartStudioVariables  # FreeCAD-CH, derived-design.md
from PartDesignTests.TestMeasuredVariables import TestMeasuredVariables  # FreeCAD-CH, ops#640
from PartDesignTests.TestSolidOps import TestThicken, TestThickenOnshapeOptions, TestScale, TestOffsetSurface, TestSolidOpsExpressions, TestThickenBend, TestThickenPipe  # FreeCAD-CH, lane solid-ops
# TestThickenObliqueLeg fails on Windows at its fixture (5 tests, known: tests/known-failures, ops#753)
from PartDesignTests.TestSolidOps import TestThickenObliqueLeg, TestThickenSeamLeg, TestThickenPlanarCaps  # FreeCAD-CH (ops#640)

# Studio features (FreeCAD-CH, ops#654, ops#655)
from PartDesignTests.TestStudioList import (
    TestStudioList,
    TestStudioListProperty,
)
from PartDesignTests.TestApply import TestApply
from PartDesignTests.TestStudioOwner import TestStudioOwner
from PartDesignTests.TestStudioHistory import TestStudioHistory
from PartDesignTests.TestPieces import TestPieces, TestStudioUndo
from PartDesignTests.TestBooleanScope import TestBooleanScope
from PartDesignTests.TestStudioPatterns import TestStudioPatterns
from PartDesignTests.TestResultCheck import TestResultCheck  # FreeCAD-CH, kernel safety S2
from PartDesignTests.TestStudioPartMirror import TestStudioPartMirror
from PartDesignTests.TestStudioTransform import TestStudioTransform  # FreeCAD-CH, ops#655
from PartDesignTests.TestResultCheck import TestManyHoles  # FreeCAD-CH, kernel-9
from PartDesignTests.TestResultCheck import TestThreadEndRevolve  # FreeCAD-CH, kernel safety 10 (FSLC #30)
from PartDesignTests.TestStudioMerge import TestStudioMerge
from PartDesignTests.TestStudioDressUp import TestStudioDressUp
from PartDesignTests.TestConfigurations import TestConfigurations  # ops#671

# The CI reopen gate (FreeCAD-CH, ops#323)
from PartDesignTests.Compat.TestCompatCorpus import TestCompatCorpus
from PartDesignTests.Compat.TestCompatRecord import TestCompatRecord  # ops#343
from PartDesignTests.Compat.TestCompatRecord import TestCompatDeltas, TestCompatNamesMeasure  # ops#640
