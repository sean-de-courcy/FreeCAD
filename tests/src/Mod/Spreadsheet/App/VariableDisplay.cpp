// SPDX-License-Identifier: LGPL-2.1-or-later

// FreeCAD-CH (ops#152): the `#name` display mode (notes/variables-design.md section 8.7, X1-X8).
// Here rather than in App's tests because the cases need a Spreadsheet: its alias provider is
// registered when the module loads. Every model is built by the test; the expected texts are
// fixed up front.

#include <gtest/gtest.h>

#include <cstdio>
#include <fstream>
#include <regex>
#include <set>
#include <stdexcept>

#include <zipios++/zipinputstream.h>

#include <App/Application.h>
#include <App/Document.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <App/PropertyGeo.h>
#include <App/PropertyUnits.h>
#include <App/VarSet.h>
#include <App/VariableLookup.h>
#include <Base/FileInfo.h>
#include <Mod/Spreadsheet/App/Sheet.h>
#include <src/App/InitApplication.h>

// NOLINTBEGIN(readability-magic-numbers)

namespace
{

using Pairs = std::vector<std::pair<std::string, std::string>>;

class VariableDisplay: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("display");
        doc = App::GetApplication().newDocument(_docName.c_str(), "testUser");
        varSet = freecad_cast<App::VarSet*>(doc->addObject("App::VarSet", "VarSet"));
        width = static_cast<App::PropertyLength*>(
            varSet->addDynamicProperty("App::PropertyLength", "Width")
        );
        width->setValue(20.0);
        auto pos = static_cast<App::PropertyVector*>(
            varSet->addDynamicProperty("App::PropertyVector", "Pos")
        );
        pos->setValue(Base::Vector3d(1, 2, 3));
        // The "Box": a plain object holding a length, so no module but Spreadsheet is needed.
        box = doc->addObject("App::DocumentObjectGroup", "Box");
        length = static_cast<App::PropertyLength*>(
            box->addDynamicProperty("App::PropertyLength", "Length")
        );
        length->setValue(10.0);
        sheet = freecad_cast<Spreadsheet::Sheet*>(doc->addObject("Spreadsheet::Sheet", "Sheet"));
        sheet->setCell("B3", "30 mm");
        sheet->setAlias(App::CellAddress("B3"), "Depth");
        doc->recompute();
    }

    void TearDown() override
    {
        for (const auto& name : _otherDocs) {
            App::GetApplication().closeDocument(name.c_str());
        }
        App::GetApplication().closeDocument(_docName.c_str());
    }

    App::ExpressionPtr parse(const App::DocumentObject* owner, const std::string& text)
    {
        return App::ExpressionPtr(App::Expression::parse(owner, text));
    }

    std::string display(const App::DocumentObject* owner, const std::string& text)
    {
        auto expr = parse(owner, text);
        return App::toDisplayString(expr.get());
    }

    // The stored expression of Box.Length, as display text.
    std::string boxDisplay()
    {
        auto info = box->getExpression(App::ObjectIdentifier(*length));
        return info.expression ? App::toDisplayString(info.expression.get()) : std::string();
    }

    App::Document* otherDocument(const char* name)
    {
        auto docName = App::GetApplication().getUniqueDocumentName(name);
        _otherDocs.push_back(docName);
        return App::GetApplication().newDocument(docName.c_str(), "testUser");
    }

    static std::set<std::string> depNames(const App::Expression* expr)
    {
        std::set<std::string> result;
        for (const auto& [obj, props] : expr->getDeps()) {
            for (const auto& [prop, paths] : props) {
                result.insert(std::string(obj->getNameInDocument()) + "." + prop);
            }
        }
        return result;
    }

    App::Document* doc {};
    App::VarSet* varSet {};
    App::PropertyLength* width {};
    App::DocumentObject* box {};
    App::PropertyLength* length {};
    Spreadsheet::Sheet* sheet {};

private:
    std::string _docName;
    std::vector<std::string> _otherDocs;
};

// X1
TEST_F(VariableDisplay, shortWhenUnique)
{
    auto expr = parse(box, "VarSet.Width * 2");
    EXPECT_EQ(App::toDisplayString(expr.get()), "#Width * 2");
    EXPECT_EQ(expr->toString(), "VarSet.Width * 2");
    EXPECT_EQ(expr->toString(true), "VarSet.Width * 2");
}

// X2
TEST_F(VariableDisplay, fullPathWhenAmbiguous)
{
    sheet->setCell("C1", "5 mm");
    sheet->setAlias(App::CellAddress("C1"), "Width");
    EXPECT_EQ(display(box, "VarSet.Width * 2"), "VarSet.Width * 2");
    sheet->setAlias(App::CellAddress("C1"), "");
    EXPECT_EQ(display(box, "VarSet.Width * 2"), "#Width * 2");

    auto second = doc->addObject("App::VarSet", "VarSet001");
    second->addDynamicProperty("App::PropertyLength", "Width");
    EXPECT_EQ(display(box, "VarSet.Width * 2"), "VarSet.Width * 2");
    doc->removeObject("VarSet001");
    EXPECT_EQ(display(box, "VarSet.Width * 2"), "#Width * 2");
}

// X3: parse(owner, display(e)) has e's dependencies and value, and its stored text.
TEST_F(VariableDisplay, roundTrip)
{
    varSet->Label.setValue("Variables");
    struct Case
    {
        const App::DocumentObject* owner;
        std::string text;
        std::string shown;
    };
    const std::vector<Case> corpus {
        {box, "VarSet.Width", "#Width"},
        {box, "<<Variables>>.Width", "#Width"},
        {varSet, ".Width", "#Width"},
        {varSet, "Width + 5 mm", "#Width + 5 mm"},
        {box, "VarSet.Pos.x", "#Pos.x"},
        {box, "max(VarSet.Width; 3 mm)", "max(#Width; 3 mm)"},
        {box, "VarSet.Width > 1 mm ? 1 : 2", "#Width > 1 mm ? 1 : 2"},
        {box, "Sheet.Depth", "#Depth"},
        {box, "Sheet.Depth * VarSet.Width", "#Depth * #Width"},
    };
    for (const auto& c : corpus) {
        SCOPED_TRACE(c.text);
        auto expr = parse(c.owner, c.text);
        std::string shown = App::toDisplayString(expr.get());
        EXPECT_EQ(shown, c.shown);
        auto back = parse(c.owner, shown);
        EXPECT_EQ(depNames(back.get()), depNames(expr.get()));
        EXPECT_EQ(back->eval()->toString(), expr->eval()->toString());
        if (c.text == "<<Variables>>.Width") {
            EXPECT_EQ(back->toString(true), "VarSet.Width");  // by label comes back by name
        }
        else if (c.text == ".Width") {
            EXPECT_EQ(back->toString(true), "Width");  // `#Width` in the VarSet is stored bare
        }
        else {
            EXPECT_EQ(back->toString(true), expr->toString(true));
        }
    }
}

// X4
TEST_F(VariableDisplay, keptAsWritten)
{
    auto doc2 = otherDocument("display2");
    auto other = doc2->addObject("App::VarSet", "VarSet");
    other->addDynamicProperty("App::PropertyLength", "Width");
    auto boxWidth = static_cast<App::PropertyLength*>(
        box->addDynamicProperty("App::PropertyLength", "Width")
    );
    boxWidth->setValue(3.0);
    sheet->setCell("A5", "4 mm");
    doc->recompute();

    const std::string otherDoc = std::string(doc2->getName()) + "#VarSet.Width";
    struct Case
    {
        const App::DocumentObject* owner;
        std::string text;
    };
    const std::vector<Case> cases {
        {box, otherDoc},
        {box, "Sheet.A5"},
        {box, "Sheet.B3"},
        {box, "Box.Length"},
        {box, "Box.Width"},
        {sheet, "Depth"},
        {box, "VarSet.<<Sub.>>.Width"},
    };
    for (const auto& c : cases) {
        SCOPED_TRACE(c.text);
        auto expr = parse(c.owner, c.text);
        std::string shown = App::toDisplayString(expr.get());
        EXPECT_EQ(shown, expr->toString());
        if (c.text != otherDoc) {
            EXPECT_EQ(shown.find('#'), std::string::npos) << shown;
        }
    }
}

// X5
TEST_F(VariableDisplay, renameDeleteUndo)
{
    box->setExpression(
        App::ObjectIdentifier(*length),
        std::shared_ptr<App::Expression>(App::Expression::parse(box, "#Width * 2"))
    );
    EXPECT_EQ(boxDisplay(), "#Width * 2");

    ASSERT_TRUE(varSet->renameDynamicProperty(width, "BoxWidth"));
    EXPECT_EQ(boxDisplay(), "#BoxWidth * 2");

    doc->setTransactionMode(1);
    doc->openTransaction("Remove");
    varSet->removeDynamicProperty("BoxWidth");
    doc->commitTransaction();
    EXPECT_EQ(boxDisplay(), "VarSet.BoxWidth * 2");

    doc->undo();
    EXPECT_NE(varSet->getDynamicPropertyByName("BoxWidth"), nullptr);
    EXPECT_EQ(boxDisplay(), "#BoxWidth * 2");
}

// X6
TEST_F(VariableDisplay, scopeHygiene)
{
    auto expr = parse(box, "VarSet.Width * 2");
    EXPECT_EQ(App::VariableDisplayScope::current(), nullptr);
    {
        App::VariableDisplayScope outer;
        EXPECT_EQ(expr->toString(), "#Width * 2");
        EXPECT_EQ(expr->toString(true), "VarSet.Width * 2");
        {
            App::VariableDisplayScope inner;
            EXPECT_EQ(App::VariableDisplayScope::current(), &inner);
        }
        EXPECT_EQ(App::VariableDisplayScope::current(), &outer);
        try {
            App::VariableDisplayScope thrown;
            throw std::runtime_error("leave the scope");
        }
        catch (const std::runtime_error&) {
        }
        EXPECT_EQ(App::VariableDisplayScope::current(), &outer);
    }
    EXPECT_EQ(App::VariableDisplayScope::current(), nullptr);
    EXPECT_EQ(expr->toString(), "VarSet.Width * 2");
}

// X7
TEST_F(VariableDisplay, tooltipList)
{
    auto expr = parse(box, "Sheet.Depth * VarSet.Width + VarSet.Width");
    Pairs shortened;
    EXPECT_EQ(App::toDisplayString(expr.get(), &shortened), "#Depth * #Width + #Width");
    EXPECT_EQ(shortened, (Pairs {{"#Depth", "Sheet.Depth"}, {"#Width", "VarSet.Width"}}));
}

// X8
TEST_F(VariableDisplay, saveInsideScope)
{
    box->setExpression(
        App::ObjectIdentifier(*length),
        std::shared_ptr<App::Expression>(App::Expression::parse(box, "#Width * 2"))
    );
    sheet->setCell("B1", "=#Width");
    doc->recompute();
    std::string path = Base::FileInfo::getTempFileName("variables") + ".FCStd";
    {
        App::VariableDisplayScope scope;
        ASSERT_TRUE(doc->saveAs(path.c_str()));
    }
    std::ifstream file(path, std::ios::binary);
    zipios::ZipInputStream entry(file);
    std::string xml {std::istreambuf_iterator<char>(entry), std::istreambuf_iterator<char>()};
    file.close();
    std::remove(path.c_str());

    EXPECT_NE(xml.find("expression=\"VarSet.Width * 2\""), std::string::npos);
    EXPECT_NE(xml.find("content=\"=VarSet.Width\""), std::string::npos);
    const std::regex attribute(R"re((expression|content)="([^"]*)")re");
    for (auto it = std::sregex_iterator(xml.begin(), xml.end(), attribute);
         it != std::sregex_iterator();
         ++it) {
        EXPECT_EQ((*it)[2].str().find('#'), std::string::npos) << (*it)[0].str();
    }
}

// listVariables reads the alias map: an alias counts before its sheet's first recompute.
TEST_F(VariableDisplay, listVariablesWithAliases)
{
    auto fresh = freecad_cast<Spreadsheet::Sheet*>(doc->addObject("Spreadsheet::Sheet", "Fresh"));
    fresh->setCell("A2", "7 mm");
    fresh->setAlias(App::CellAddress("A2"), "Gap");
    fresh->setCell("A1", "8 mm");
    fresh->setAlias(App::CellAddress("A1"), "Gap0");
    ASSERT_EQ(fresh->getPropertyByName("A2"), nullptr);  // not recomputed yet

    std::vector<std::string> paths;
    for (const auto& ref : App::VariableLookup::listVariables(doc)) {
        paths.push_back(ref.path());
    }
    // Objects in document order; a sheet's aliases in cell order.
    EXPECT_EQ(
        paths,
        (std::vector<std::string> {"VarSet.Width", "VarSet.Pos", "Sheet.Depth", "Fresh.Gap0", "Fresh.Gap"})
    );
    EXPECT_TRUE(App::VariableLookup::isVariable(fresh, "Gap"));
    EXPECT_FALSE(App::VariableLookup::isVariable(fresh, "A2"));
}

}  // namespace

// NOLINTEND(readability-magic-numbers)
