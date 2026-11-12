# SPDX-License-Identifier: LGPL-2.1-or-later

disable_occt8_deprecation_warnings()

add_subdirectory(App)
if(BUILD_GUI)
    add_subdirectory(Gui)
endif(BUILD_GUI)

set(Sketcher_Scripts
    Init.py
    SketcherExample.py
    TestSketcherApp.py
    Profiles.py
)

set(Sketcher_TestScripts
    SketcherTests/__init__.py
    SketcherTests/TestSketchFillet.py
    SketcherTests/TestSketcherSolver.py
    SketcherTests/TestSketchExpression.py
    SketcherTests/TestSketchValidateCoincidents.py
    SketcherTests/TestSketchCarbonCopyReverseMapping.py
    SketcherTests/TestSketchCarbonCopyReverseMapping.FCStd
    SketcherTests/TestSketchInternalFaces.py
    SketcherTests/TestSketchNamesV1.py
    SketcherTests/TestSketcherEllipse.py
    SketcherTests/TestSketchMissingExternal.py
    SketcherTests/TestSketchD4Solve.py
    SketcherTests/TestSketchExternalTypes.py
    SketcherTests/TestSketchCarbonCopyElements.py
    SketcherTests/TestSketchCornerSteps.py
    SketcherTests/TestSketchTrimSplit.py
    SketcherTests/TestSketchConflicts.py
    SketcherTests/TestSketchLadder.py
    SketcherTests/TestSketchTrimSplitAttacks.py
    SketcherTests/TestSketchPierce.py
    SketcherTests/TestSketchExtend.py
    SketcherTests/TestSketchPattern.py
    SketcherTests/TestSketchDxf.py
)

if(BUILD_GUI)
    list (APPEND Sketcher_Scripts
          InitGui.py
          TestSketcherGui.py
          SketcherDxfGui.py
    )
    list (APPEND Sketcher_TestScripts
          SketcherTests/TestConstraintPreselectionGui.py
          SketcherTests/TestPolylineFilletGui.py
          SketcherTests/GuiTestCase.py
          SketcherTests/TestPlacementUpdate.py
          SketcherTests/TestOnViewParameterGui.py
          SketcherTests/TestExternalFacePreselection.py
          SketcherTests/TestAutoScaleNamesGui.py
          SketcherTests/TestSketchMissingExternalGui.py
          SketcherTests/TestSketchBrokenExternalTreeGui.py
          SketcherTests/TestSketchEditCameraGui.py
          SketcherTests/TestDimensionInPlaceGui.py
          SketcherTests/TestSketchCameraOnEditGui.py
          SketcherTests/TestAutoConstraintsGui.py
          SketcherTests/TestSketchCopyElementsGui.py
          SketcherTests/TestSketchCommandsGui.py
          SketcherTests/TestSketchToolbarGui.py
          SketcherTests/TestSketchModelPicksGui.py
          SketcherTests/TestSketchMidpointPicksGui.py
          SketcherTests/TestSketchModelFacesGui.py
          SketcherTests/TestSketchConstraintToolsGui.py
          SketcherTests/TestSketchOnshapeGui.py
          SketcherTests/TestSketchHelpersGui.py
          SketcherTests/TestSketchOnshapeToolsGui.py
          SketcherTests/TestSketchRound3Gui.py
          SketcherTests/TestSketchRound4Gui.py
          SketcherTests/TestSketchCancelGui.py
          SketcherTests/TestSketchDxfGui.py
    )
endif(BUILD_GUI)

set(Sketcher_Dxf
    SketcherDxf/__init__.py
    SketcherDxf/reader.py
    SketcherDxf/fitting.py
    SketcherDxf/importer.py
    SketcherDxf/exporter.py
)

set(Sketcher_Profiles
    ProfileLib/Hexagon.py
    ProfileLib/RegularPolygon.py
    ProfileLib/__init__.py
)

add_custom_target(SketcherScripts ALL
    SOURCES ${Sketcher_Scripts} ${Sketcher_Profiles} ${Sketcher_TestScripts} ${Sketcher_Dxf}
)

fc_target_copy_resource(SketcherScripts
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_BINARY_DIR}/Mod/Sketcher
    ${Sketcher_Scripts}
    ${Sketcher_Profiles}
    ${Sketcher_TestScripts}
    ${Sketcher_Dxf}
)

INSTALL(
    FILES
        ${Sketcher_Scripts}
    DESTINATION
        Mod/Sketcher
)

INSTALL(
    FILES
        ${Sketcher_Dxf}
    DESTINATION
        Mod/Sketcher/SketcherDxf
)

INSTALL(
    FILES
        ${Sketcher_Profiles}
    DESTINATION
        Mod/Sketcher/ProfileLib
)

INSTALL(
    FILES
        ${Sketcher_TestScripts}
    DESTINATION
        Mod/Sketcher/SketcherTests
       )
