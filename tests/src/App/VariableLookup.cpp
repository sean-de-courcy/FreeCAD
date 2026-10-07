// SPDX-License-Identifier: LGPL-2.1-or-later

// FreeCAD-CH (ops#152): `#name` resolution at its edges, and the VarSet provider
// (notes/variables-design.md section 3.1). Sheet aliases are tested in Spreadsheet_tests_run.

#include <gtest/gtest.h>

#include <algorithm>

#include <App/Application.h>
#include <App/Document.h>
#include <App/Expression.h>
#include <App/PropertyUnits.h>
#include <App/VarSet.h>
#include <App/VariableLookup.h>
#include <Base/Exception.h>
#include <src/App/InitApplication.h>

// NOLINTBEGIN(readability-magic-numbers)

namespace
{

class VariableLookupTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("variables");
        doc = App::GetApplication().newDocument(_docName.c_str(), "testUser");
        varSet = doc->addObject("App::VarSet", "VarSet");
        auto width = static_cast<App::PropertyLength*>(
            varSet->addDynamicProperty("App::PropertyLength", "Width")
        );
        width->setValue(20.0);
        varSet->addDynamicProperty("App::PropertyLength", "Depth");
        owner = doc->addObject("App::DocumentObjectGroup", "Owner");
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    // The message of the ParserError that parsing @a text raises, or "" if it parses.
    std::string parseError(const App::DocumentObject* by, const std::string& text)
    {
        try {
            App::ExpressionPtr expr(App::Expression::parse(by, text));
        }
        catch (const Base::ParserError& e) {
            return e.what();
        }
        return {};
    }

    App::Document* doc {};
    App::DocumentObject* varSet {};
    App::DocumentObject* owner {};

private:
    std::string _docName;
};

TEST_F(VariableLookupTest, resolvesWithAnOwner)
{
    App::ExpressionPtr expr(App::Expression::parse(owner, "#Width * 2"));
    EXPECT_EQ(expr->toString(), "VarSet.Width * 2");
}

TEST_F(VariableLookupTest, noOwnerLeavesTheTextAlone)
{
    // No owner, no document to search: `#Width` is the syntax error it is in stock FreeCAD.
    EXPECT_EQ(parseError(nullptr, "#Width"), "Failed to parse expression '#Width'");
}

TEST_F(VariableLookupTest, unterminatedStringIsNoString)
{
    // `<<` without its `>>` is not a string to the lexer, so the scanner doesn't skip over it.
    EXPECT_EQ(parseError(owner, "#Width + <<x"), "Failed to parse expression '#Width + <<x'");
    EXPECT_EQ(parseError(owner, "<<x #Width"), "Failed to parse expression '<<x #Width'");
    EXPECT_EQ(parseError(owner, R"(<<x\>> #Width)"), R"(Failed to parse expression '<<x\>> #Width')");
}

TEST_F(VariableLookupTest, stringThenSpaceThenHashIsADocumentPath)
{
    // `<<Doc>> #Obj.Prop` names a document: nothing here is named Obj, so a rewrite would raise.
    auto otherName = App::GetApplication().getUniqueDocumentName("other");
    auto other = App::GetApplication().newDocument(otherName.c_str(), "testUser");
    other->addObject("App::VarSet", "Obj")->addDynamicProperty("App::PropertyLength", "Prop");
    std::string text = "<<" + otherName + ">> #Obj.Prop";
    EXPECT_EQ(parseError(owner, text), "");
    App::ExpressionPtr expr(App::Expression::parse(owner, text));
    EXPECT_NE(expr->toString().find("#Obj.Prop"), std::string::npos);
    App::GetApplication().closeDocument(otherName.c_str());
}

TEST_F(VariableLookupTest, unknownAndAmbiguous)
{
    EXPECT_EQ(
        parseError(owner, "#Nope"),
        "no variable named Nope in this document (in expression '#Nope')"
    );
    doc->addObject("App::VarSet", "VarSet001")->addDynamicProperty("App::PropertyLength", "Width");
    EXPECT_EQ(
        parseError(owner, "#Width"),
        "#Width is ambiguous: VarSet.Width, VarSet001.Width; write the full path "
        "(in expression '#Width')"
    );
}

TEST_F(VariableLookupTest, listVariablesOfVarSets)
{
    std::vector<std::string> paths;
    for (const auto& ref : App::VariableLookup::listVariables(doc)) {
        paths.push_back(ref.path());
    }
    std::sort(paths.begin(), paths.end());
    EXPECT_EQ(paths, (std::vector<std::string> {"VarSet.Depth", "VarSet.Width"}));
    EXPECT_TRUE(App::VariableLookup::isVariable(varSet, "Width"));
    EXPECT_FALSE(App::VariableLookup::isVariable(varSet, "Label"));  // static, not a variable
    EXPECT_FALSE(App::VariableLookup::isVariable(owner, "Label"));
}

}  // namespace

// NOLINTEND(readability-magic-numbers)
