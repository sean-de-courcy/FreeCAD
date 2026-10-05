# SPDX-License-Identifier: LGPL-2.1-or-later

disable_occt8_deprecation_warnings()

add_subdirectory(App)
if(BUILD_GUI)
    add_subdirectory(Gui)
endif(BUILD_GUI)

set(PartDesign_Scripts
    __init__.py
    Init.py
    TestPartDesignApp.py
)

if(BUILD_GUI)
    list (APPEND PartDesign_Scripts
          InitGui.py
          TestPartDesignGui.py
          InvoluteGearFeature.py
          InvoluteGearFeature.ui
          SprocketFeature.py
          SprocketFeature.ui
    )
endif(BUILD_GUI)

set(PartDesign_OtherScripts
    Scripts/__init__.py
    Scripts/DistanceBolt.py
    Scripts/Epitrochoid.py
    Scripts/FilletArc.py
    Scripts/Gear.py
    Scripts/Parallelepiped.py
    Scripts/RadialCopy.py
    Scripts/Spring.py
)

set(PartDesign_TestScripts
    PartDesignTests/__init__.py
    PartDesignTests/TestActiveObject.py
    PartDesignTests/TestDatum.py
    PartDesignTests/TestShapeBinder.py
    PartDesignTests/TestPad.py
    PartDesignTests/TestPocket.py
    PartDesignTests/TestHelix.py
    PartDesignTests/TestHole.py
    PartDesignTests/TestRevolve.py
    PartDesignTests/TestLoft.py
    PartDesignTests/TestPipe.py
    PartDesignTests/TestPrimitive.py
    PartDesignTests/TestMirrored.py
    PartDesignTests/TestLinearPattern.py
    PartDesignTests/TestPolarPattern.py
    PartDesignTests/TestMultiTransform.py
    PartDesignTests/TestBoolean.py
    PartDesignTests/TestBaseFeature.py
    PartDesignTests/TestFillet.py
    PartDesignTests/TestChamfer.py
    PartDesignTests/TestDraft.py
    PartDesignTests/TestThickness.py
    PartDesignTests/TestMissingElements.py
    PartDesignTests/TestTopologicalNamingProblem.py
    PartDesignTests/TestNamingDump.py
    PartDesignTests/TestNamingLoad.py
    PartDesignTests/TestNamingSave.py
    PartDesignTests/TestNamingRList.py
    PartDesignTests/TestNamingScenarios.py
    PartDesignTests/TestNamingSolver.py
    PartDesignTests/TestNamingGate.py
    PartDesignTests/TestNamingConsumerPass.py
    PartDesignTests/TestInvoluteGear.py
    PartDesignTests/TestSketch.py
)

if(BUILD_GUI)
    list(APPEND PartDesign_TestScripts
        PartDesignTests/TestMaterial.py
        PartDesignTests/TestSuppressed.py
        PartDesignTests/TestPreviewPython.py
    )
endif(BUILD_GUI)

set(PartDesign_TestFixtures
    PartDesignTests/Fixtures/InvoluteGear_v0-20.FCStd
    PartDesignTests/Fixtures/InternalInvoluteGear_v0-20.FCStd
)

# The naming scenarios (TestNamingScenarios; the model helpers are shared with TestNamingDump)
set(PartDesign_TestScenarios
    PartDesignTests/Scenarios/__init__.py
    PartDesignTests/Scenarios/ambiguous.py
    PartDesignTests/Scenarios/attachment.py
    PartDesignTests/Scenarios/booleans.py
    PartDesignTests/Scenarios/consumers.py
    PartDesignTests/Scenarios/crossdoc.py
    PartDesignTests/Scenarios/dressups.py
    PartDesignTests/Scenarios/external.py
    PartDesignTests/Scenarios/harness.py
    PartDesignTests/Scenarios/internal.py
    PartDesignTests/Scenarios/interning.py
    PartDesignTests/Scenarios/issues.py
    PartDesignTests/Scenarios/models.py
    PartDesignTests/Scenarios/moves.py
    PartDesignTests/Scenarios/patterns.py
    PartDesignTests/Scenarios/randomized.py
    PartDesignTests/Scenarios/rlist.py
    PartDesignTests/Scenarios/sketch_edits.py
    PartDesignTests/Scenarios/splits.py
    PartDesignTests/Scenarios/uptoface.py
)

# Golden files of TestNamingDump (regenerate with FREECAD_NAMING_GOLDEN_UPDATE)
set(PartDesign_NamingGolden
    PartDesignTests/NamingGolden/CompoundCopies.V1.txt
    PartDesignTests/NamingGolden/CompoundCopies.V2.txt
    PartDesignTests/NamingGolden/CompoundCopies.V2i-ids.txt
    PartDesignTests/NamingGolden/CompoundCut.V1.txt
    PartDesignTests/NamingGolden/CompoundCut.V2.txt
    PartDesignTests/NamingGolden/CompoundCut.V2i-ids.txt
    PartDesignTests/NamingGolden/CutSplit.V1.txt
    PartDesignTests/NamingGolden/CutSplit.V2.txt
    PartDesignTests/NamingGolden/CutSplit.V2i-ids.txt
    PartDesignTests/NamingGolden/FilletChamfer.V1.txt
    PartDesignTests/NamingGolden/FilletChamfer.V2.txt
    PartDesignTests/NamingGolden/FilletChamfer.V2i-ids.txt
    PartDesignTests/NamingGolden/FuseCommon.V1.txt
    PartDesignTests/NamingGolden/FuseCommon.V2.txt
    PartDesignTests/NamingGolden/FuseCommon.V2i-ids.txt
    PartDesignTests/NamingGolden/HelixBinderFace.V1.txt
    PartDesignTests/NamingGolden/HelixBinderFace.V2.txt
    PartDesignTests/NamingGolden/HelixBinderFace.V2i-ids.txt
    PartDesignTests/NamingGolden/LinearPattern.V1.txt
    PartDesignTests/NamingGolden/LinearPattern.V2.txt
    PartDesignTests/NamingGolden/LinearPattern.V2i-ids.txt
    PartDesignTests/NamingGolden/LoftRevolve.V1.txt
    PartDesignTests/NamingGolden/LoftRevolve.V2.txt
    PartDesignTests/NamingGolden/LoftRevolve.V2i-ids.txt
    PartDesignTests/NamingGolden/OffsetSplitCylinder.V1.txt
    PartDesignTests/NamingGolden/OffsetSplitCylinder.V2.txt
    PartDesignTests/NamingGolden/OffsetSplitCylinder.V2i-ids.txt
    PartDesignTests/NamingGolden/OffsetThickness.V1.txt
    PartDesignTests/NamingGolden/OffsetThickness.V2.txt
    PartDesignTests/NamingGolden/OffsetThickness.V2i-ids.txt
    PartDesignTests/NamingGolden/PadCollinear.V1.txt
    PartDesignTests/NamingGolden/PadCollinear.V2.txt
    PartDesignTests/NamingGolden/PadCollinear.V2i-ids.txt
    PartDesignTests/NamingGolden/PadPocket.V1.txt
    PartDesignTests/NamingGolden/PadPocket.V2.txt
    PartDesignTests/NamingGolden/PadPocket.V2i-ids.txt
    PartDesignTests/NamingGolden/PatternSteps.V1.txt
    PartDesignTests/NamingGolden/PatternSteps.V2.txt
    PartDesignTests/NamingGolden/PatternSteps.V2i-ids.txt
    PartDesignTests/NamingGolden/PipeShell.V1.txt
    PartDesignTests/NamingGolden/PipeShell.V2.txt
    PartDesignTests/NamingGolden/PipeShell.V2i-ids.txt
    PartDesignTests/NamingGolden/REVISION
    PartDesignTests/NamingGolden/Refine.V1.txt
    PartDesignTests/NamingGolden/Refine.V2.txt
    PartDesignTests/NamingGolden/Refine.V2i-ids.txt
    PartDesignTests/NamingGolden/Sketch.V1.txt
    PartDesignTests/NamingGolden/Sketch.V2.txt
    PartDesignTests/NamingGolden/Sketch.V2i-ids.txt
    PartDesignTests/NamingGolden/Slice.V1.txt
    PartDesignTests/NamingGolden/Slice.V2.txt
    PartDesignTests/NamingGolden/Slice.V2i-ids.txt
)

set(PartDesign_GearScripts
    fcgear/__init__.py
    fcgear/fcgear.py
    fcgear/involute.py
    fcgear/svggear.py
)

set(PartDesign_SprocketScripts
    fcsprocket/__init__.py
    fcsprocket/fcsprocket.py
    fcsprocket/fcsprocketdialog.py
    fcsprocket/sprocket.py
)

set(PartDesign_WizardShaft
    WizardShaft/__init__.py
    WizardShaft/WizardShaft.svg
    WizardShaft/WizardShaft.py
    WizardShaft/WizardShaftTable.py
    WizardShaft/Shaft.py
    WizardShaft/ShaftFeature.py
    WizardShaft/ShaftDiagram.py
    WizardShaft/SegmentFunction.py
)

add_custom_target(PartDesignScripts ALL SOURCES
    ${PartDesign_Scripts}
    ${PartDesign_OtherScripts}
    ${PartDesign_TestScripts}
    ${PartDesign_TestFixtures}
    ${PartDesign_TestScenarios}
    ${PartDesign_NamingGolden}
    ${PartDesign_GearScripts}
    ${PartDesign_SprocketScripts}
)

fc_target_copy_resource(PartDesignScripts
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_BINARY_DIR}/Mod/PartDesign
    ${PartDesign_Scripts}
    ${PartDesign_OtherScripts}
    ${PartDesign_TestScripts}
    ${PartDesign_TestFixtures}
    ${PartDesign_TestScenarios}
    ${PartDesign_NamingGolden}
    ${PartDesign_GearScripts}
    ${PartDesign_SprocketScripts}
)

INSTALL(
    FILES
        ${PartDesign_Scripts}
    DESTINATION
        Mod/PartDesign
)

INSTALL(
    FILES
        ${PartDesign_OtherScripts}
    DESTINATION
        Mod/PartDesign/Scripts
       )

INSTALL(
    FILES
        ${PartDesign_TestScripts}
    DESTINATION
        Mod/PartDesign/PartDesignTests
       )

INSTALL(
    FILES
        ${PartDesign_TestFixtures}
    DESTINATION
        Mod/PartDesign/PartDesignTests/Fixtures
       )

INSTALL(
    FILES
        ${PartDesign_TestScenarios}
    DESTINATION
        Mod/PartDesign/PartDesignTests/Scenarios
       )

INSTALL(
    FILES
        ${PartDesign_NamingGolden}
    DESTINATION
        Mod/PartDesign/PartDesignTests/NamingGolden
       )

INSTALL(
    FILES
        ${PartDesign_GearScripts}
    DESTINATION
        Mod/PartDesign/fcgear
)

INSTALL(
    FILES
        ${PartDesign_SprocketScripts}
    DESTINATION
        Mod/PartDesign/fcsprocket
)

set(PartDesignHoleDefines
    Resources/Hole/din7984.json
    Resources/Hole/iso10642.json
    Resources/Hole/iso10642-fine.json
    Resources/Hole/iso12474-fine.json
    Resources/Hole/iso14583.json
    Resources/Hole/iso14583part.json
    Resources/Hole/iso2009.json
    Resources/Hole/iso4762_7089.json
    Resources/Hole/iso4762.json
    Resources/Hole/iso4762-fine.json
    Resources/Hole/iso7046.json
)

add_custom_target(PartDesignHole ALL SOURCES
    ${PartDesignHoleDefines}
)

fc_target_copy_resource(PartDesignHole
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_BINARY_DIR}/${CMAKE_INSTALL_DATADIR}/Mod/PartDesign
    ${PartDesignHoleDefines}
)

INSTALL(
    FILES
        ${PartDesignHoleDefines}
    DESTINATION
        ${CMAKE_INSTALL_DATADIR}/Mod/PartDesign/Resources/Hole
)

if(BUILD_FEM)
    SET(WizardShaft_SRCS
        ${PartDesign_WizardShaft}
    )
    SOURCE_GROUP("wizardshaft" FILES ${WizardShaft_SRCS})

    SET(all_wizardshaft_files ${WizardShaft_SRCS})

    ADD_CUSTOM_TARGET(WizardShaft ALL
        SOURCES ${all_wizardshaft_files}
    )

    SET(all_files ${all_wizardshaft_files})

    fc_copy_sources(WizardShaft "${CMAKE_BINARY_DIR}/Mod/PartDesign" ${all_files})

    INSTALL(
        FILES
            ${WizardShaft_SRCS}
        DESTINATION
            Mod/PartDesign/WizardShaft
    )
endif(BUILD_FEM)
