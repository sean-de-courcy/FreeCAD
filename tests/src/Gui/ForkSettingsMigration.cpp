// SPDX-License-Identifier: LGPL-2.1-or-later
// ops#882: the one-time reset of toolbars left by earlier FreeCAD-CH builds.

#include <gtest/gtest.h>

#include <Base/Parameter.h>
#include "Gui/StartupProcess.h"

#include <src/App/InitApplication.h>

namespace
{
const char* stock[] = {
    "Part Design Helper Features",
    "Part Design Modeling Features",
    "Part Design Dress-Up Features",
    "Part Design Transformation Features",
};

ParameterGrp::handle toolbars(ParameterGrp& root)
{
    return root.GetGroup("BaseApp")->GetGroup("MainWindow")->GetGroup("Toolbars");
}

ParameterGrp::handle customToolbars(ParameterGrp& root)
{
    return root.GetGroup("BaseApp")
        ->GetGroup("Workbench")
        ->GetGroup("PartDesignWorkbench")
        ->GetGroup("Toolbar");
}

// The settings an earlier fork build plus fork-1.0.0 leave: the four stock toolbars saved shown,
// a Tier 0 custom "Features" toolbar, and a custom toolbar of the user's own.
void writeUpgradedSettings(ParameterGrp& root)
{
    for (const char* name : stock) {
        toolbars(root)->SetBool(name, true);
    }
    toolbars(root)->SetBool("Features", true);
    toolbars(root)->SetBool("Sketcher", true);
    auto tier0 = customToolbars(root)->GetGroup("Custom_1");
    tier0->SetASCII("Name", "Features");
    tier0->SetASCII("PartDesign_Pad", "PartDesign");
    tier0->SetASCII("PartDesign_Pocket", "PartDesign");
    auto mine = customToolbars(root)->GetGroup("Custom_2");
    mine->SetASCII("Name", "My tools");
    mine->SetASCII("PartDesign_Pad", "PartDesign");
}
}  // namespace

class ForkSettingsMigration: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
    Base::Reference<ParameterManager> root {ParameterManager::Create()};
    void SetUp() override
    {
        root->CreateDocument();
    }
};

TEST_F(ForkSettingsMigration, resetsStockToolbarsAndTier0Copy)
{
    writeUpgradedSettings(*root);

    EXPECT_TRUE(Gui::StartupProcess::migrateForkSettings(*root));

    for (const char* name : stock) {
        EXPECT_FALSE(toolbars(*root)->GetBool(name, true)) << name;
    }
    // Only the duplicates go: the built-in Features toolbar, other toolbars and the user's own
    // custom toolbar stay as they were.
    EXPECT_TRUE(toolbars(*root)->GetBool("Features", false));
    EXPECT_TRUE(toolbars(*root)->GetBool("Sketcher", false));
    EXPECT_FALSE(customToolbars(*root)->HasGroup("Custom_1"));
    ASSERT_TRUE(customToolbars(*root)->HasGroup("Custom_2"));
    EXPECT_EQ(customToolbars(*root)->GetGroup("Custom_2")->GetASCII("Name"), "My tools");
    EXPECT_EQ(
        root->GetGroup("BaseApp")->GetGroup("Preferences")->GetGroup("General")->GetInt(
            "ForkSettingsVersion",
            0
        ),
        Gui::StartupProcess::forkSettingsVersion
    );
}

TEST_F(ForkSettingsMigration, runsOnce)
{
    writeUpgradedSettings(*root);
    ASSERT_TRUE(Gui::StartupProcess::migrateForkSettings(*root));

    // The user shows a stock toolbar again: the next start keeps it.
    toolbars(*root)->SetBool(stock[2], true);
    EXPECT_FALSE(Gui::StartupProcess::migrateForkSettings(*root));
    EXPECT_TRUE(toolbars(*root)->GetBool(stock[2], false));
}

TEST_F(ForkSettingsMigration, cleanSettingsOnlyGetTheVersion)
{
    EXPECT_FALSE(Gui::StartupProcess::migrateForkSettings(*root));
    EXPECT_FALSE(root->GetGroup("BaseApp")
                     ->GetGroup("Workbench")
                     ->GetGroup("PartDesignWorkbench")
                     ->HasGroup("Toolbar"));
    EXPECT_EQ(
        root->GetGroup("BaseApp")->GetGroup("Preferences")->GetGroup("General")->GetInt(
            "ForkSettingsVersion",
            0
        ),
        Gui::StartupProcess::forkSettingsVersion
    );
}

TEST_F(ForkSettingsMigration, keepsAUsersOwnFeaturesToolbar)
{
    writeUpgradedSettings(*root);
    auto own = customToolbars(*root)->GetGroup("Custom_3");
    own->SetASCII("Name", "Features");
    own->SetASCII("PartDesign_Pad", "PartDesign");
    own->SetASCII("Part_Box", "Part");

    ASSERT_TRUE(Gui::StartupProcess::migrateForkSettings(*root));
    EXPECT_FALSE(customToolbars(*root)->HasGroup("Custom_1"));
    EXPECT_TRUE(customToolbars(*root)->HasGroup("Custom_3"));
}

TEST_F(ForkSettingsMigration, alreadyMigratedSettingsStayAsTheyAre)
{
    writeUpgradedSettings(*root);
    root->GetGroup("BaseApp")->GetGroup("Preferences")->GetGroup("General")->SetInt(
        "ForkSettingsVersion",
        Gui::StartupProcess::forkSettingsVersion
    );

    EXPECT_FALSE(Gui::StartupProcess::migrateForkSettings(*root));
    for (const char* name : stock) {
        EXPECT_TRUE(toolbars(*root)->GetBool(name, false)) << name;
    }
    EXPECT_TRUE(customToolbars(*root)->HasGroup("Custom_1"));
}
