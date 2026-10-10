// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
 *   Copyright (c) 2024 Werner Mayer <wmayer[at]users.sourceforge.net>      *
 *   Copyright (c) 2025 Pieter Hijma <info@pieterhijma.net>                 *
 *                                                                          *
 *   This file is part of the FreeCAD CAx development system.               *
 *                                                                          *
 *   This library is free software; you can redistribute it and/or          *
 *   modify it under the terms of the GNU Library General Public            *
 *   License as published by the Free Software Foundation; either           *
 *   version 2 of the License, or (at your option) any later version.       *
 *                                                                          *
 *   This library  is distributed in the hope that it will be useful,       *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of         *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          *
 *   GNU Library General Public License for more details.                   *
 *                                                                          *
 *   You should have received a copy of the GNU Library General Public      *
 *   License along with this library; see the file COPYING.LIB. If not,     *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,          *
 *   Suite 330, Boston, MA  02111-1307, USA                                 *
 *                                                                          *
 ****************************************************************************/

#include <gtest/gtest.h>

#include <algorithm>

#include <FCConfig.h>

#include <Base/Console.h>
#include <Base/Writer.h>
#include <Base/Reader.h>
#include <Base/Interpreter.h>

#include <App/Application.h>
#include <App/Document.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <App/VarSet.h>

#include <src/App/InitApplication.h>

#include <xercesc/util/PlatformUtils.hpp>

#include "Property.h"

namespace
{
// Collects the errors sent to the console while it is attached (ops#235)
class ErrorCollector final: public Base::ILogger
{
public:
    ErrorCollector()
    {
        Base::Console().attachObserver(this);
    }
    ~ErrorCollector() override
    {
        Base::Console().detachObserver(this);
    }
    ErrorCollector(const ErrorCollector&) = delete;
    ErrorCollector(ErrorCollector&&) = delete;
    ErrorCollector& operator=(const ErrorCollector&) = delete;
    ErrorCollector& operator=(ErrorCollector&&) = delete;

    void sendLog(
        const std::string& /*notifiername*/,
        const std::string& msg,
        Base::LogStyle level,
        Base::IntendedRecipient /*recipient*/,
        Base::ContentType /*content*/
    ) override
    {
        if (level == Base::LogStyle::Error) {
            errors.push_back(msg);
        }
    }
    const char* name() override
    {
        return "ErrorCollector";
    }

    std::vector<std::string> errors;
};
}  // namespace

TEST(PropertyLink, TestSetValues)
{
    App::PropertyLinkSubList prop;
    std::vector<App::DocumentObject*> objs {nullptr, nullptr};
    std::vector<const char*> subs {"Sub1", "Sub2"};
    prop.setValues(objs, subs);
    const auto& sub = prop.getSubValues();
    EXPECT_EQ(sub.size(), 2);
    EXPECT_EQ(sub[0], "Sub1");
    EXPECT_EQ(sub[1], "Sub2");
}

class PropertyFloatTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        XERCES_CPP_NAMESPACE::XMLPlatformUtils::Initialize();
    }
};

TEST_F(PropertyFloatTest, testWriteRead)
{
#if defined(FC_OS_LINUX) || defined(FC_OS_BSD)
    setlocale(LC_ALL, "");
    setlocale(LC_NUMERIC, "C");  // avoid rounding of floating point numbers
#endif
    double value = 1.2345;
    App::PropertyFloat prop;
    prop.setValue(value);
    Base::StringWriter writer;
    prop.Save(writer);

    std::string str = "<?xml version='1.0' encoding='utf-8'?>\n";
    str.append("<Property name='Length' type='App::PropertyFloat'>\n");
    str.append(writer.getString());
    str.append("</Property>\n");

    std::stringstream data(str);
    Base::XMLReader reader("Document.xml", data);
    App::PropertyFloat prop2;
    prop2.Restore(reader);
    EXPECT_DOUBLE_EQ(prop2.getValue(), value);
}

App::Document* RenameProperty::doc {nullptr};

// Tests whether we can rename a property
TEST_F(RenameProperty, simple)
{
    // Act
    bool isRenamed = varSet->renameDynamicProperty(prop, "NewName");

    // Assert
    EXPECT_TRUE(isRenamed);
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), prop);
}

// Tests whether we can rename a property from Python
TEST_F(RenameProperty, fromPython)
{
    // Act
    Base::Interpreter().runString(
        "App.ActiveDocument.getObject('VarSet').renameProperty('Variable', 'NewName')"
    );

    // Assert
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), prop);
}

// Tests whether we can rename a property in a chain
TEST_F(RenameProperty, chain)
{
    // Act 1
    bool isRenamed = varSet->renameDynamicProperty(prop, "Name1");

    // Assert 1
    EXPECT_TRUE(isRenamed);
    EXPECT_STREQ(varSet->getPropertyName(prop), "Name1");
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Name1"), prop);

    // Act 2
    auto prop1 = freecad_cast<App::PropertyInteger*>(varSet->getDynamicPropertyByName("Name1"));
    isRenamed = varSet->renameDynamicProperty(prop1, "Name2");

    // Assert 2
    EXPECT_TRUE(isRenamed);
    EXPECT_EQ(prop, prop1);
    EXPECT_STREQ(varSet->getPropertyName(prop1), "Name2");
    EXPECT_EQ(varSet->getDynamicPropertyByName("Name1"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Name2"), prop1);
}

// Tests whether we can rename a static property
TEST_F(RenameProperty, staticProperty)
{
    // Arrange
    App::Property* prop = varSet->getPropertyByName("Label");

    // Act
    bool isRenamed = varSet->renameDynamicProperty(prop, "MyLabel");

    // Assert
    EXPECT_FALSE(isRenamed);
    EXPECT_STREQ(varSet->getPropertyName(prop), "Label");
    EXPECT_EQ(varSet->getDynamicPropertyByName("MyLabel"), nullptr);
}

// Tests whether we can rename a static property from Python
TEST_F(RenameProperty, staticPropertyFromPython)
{
    // Arrange
    App::Property* prop = varSet->getPropertyByName("Label");

    // Act / Assert
    EXPECT_THROW(
        Base::Interpreter().runString(
            "App.ActiveDocument.getObject('VarSet006').renameProperty('Label', 'NewName')"
        ),
        Base::Exception
    );

    // Assert
    EXPECT_STREQ(varSet->getPropertyName(prop), "Label");
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), nullptr);
}

// Tests whether we can rename a locked property
TEST_F(RenameProperty, lockedProperty)
{
    // Arrange
    prop->setStatus(App::Property::LockDynamic, true);

    // Act / Assert
    EXPECT_THROW(varSet->renameDynamicProperty(prop, "NewName"), Base::RuntimeError);

    // Assert
    EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), prop);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), nullptr);
}

// Tests whether we can rename to a property that already exists
TEST_F(RenameProperty, toExistingProperty)
{
    // Arrange
    App::Property* prop2 = varSet->addDynamicProperty("App::PropertyInteger", "Variable2", "Variables");

    // Act / Assert
    EXPECT_THROW(varSet->renameDynamicProperty(prop2, "Variable"), Base::NameError);

    // Assert
    EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
    EXPECT_STREQ(varSet->getPropertyName(prop2), "Variable2");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), prop);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable2"), prop2);
}

// Tests whether we can rename to a property that is invalid
TEST_F(RenameProperty, toInvalidProperty)
{
    // Act / Assert
    EXPECT_THROW(varSet->renameDynamicProperty(prop, "0Variable"), Base::NameError);

    // Assert
    EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), prop);
    EXPECT_EQ(varSet->getDynamicPropertyByName("0Variable"), nullptr);
}

// Tests whether we can rename a property that is used in an expression in the same container
TEST_F(RenameProperty, updateExpressionSameContainer)
{
    // Arrange
    const auto* prop2 = freecad_cast<App::PropertyInteger*>(
        varSet->addDynamicProperty("App::PropertyInteger", "Variable2", "Variables")
    );

    App::ObjectIdentifier path(*prop2);
    std::shared_ptr<App::Expression> expr(App::Expression::parse(varSet, "Variable"));
    varSet->setExpression(path, expr);
    varSet->ExpressionEngine.execute();

    // Assert before the rename
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(prop2->getValue(), value);

    // Act
    bool isRenamed = varSet->renameDynamicProperty(prop, "NewName");
    varSet->ExpressionEngine.execute();

    // Assert after the rename
    EXPECT_TRUE(isRenamed);
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), prop);
    EXPECT_EQ(prop2->getValue(), value);
}

// Tests whether we can rename a property that is used in an expression in a different container
TEST_F(RenameProperty, updateExpressionDifferentContainer)
{
    // Arrange
    auto* varSet2 = freecad_cast<App::VarSet*>(doc->addObject("App::VarSet", "VarSet2"));
    const auto* prop2 = freecad_cast<App::PropertyInteger*>(
        varSet2->addDynamicProperty("App::PropertyInteger", "Variable2", "Variables")
    );

    App::ObjectIdentifier path(*prop2);
    std::shared_ptr<App::Expression> expr(App::Expression::parse(varSet, "VarSet.Variable"));
    varSet2->setExpression(path, expr);
    varSet2->ExpressionEngine.execute();

    // Assert before the rename
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(prop2->getValue(), value);

    // Act
    bool isRenamed = varSet->renameDynamicProperty(prop, "NewName");
    varSet2->ExpressionEngine.execute();

    // Assert after the rename
    EXPECT_TRUE(isRenamed);
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), prop);
    EXPECT_EQ(prop2->getValue(), value);

    // Tear down
    doc->removeObject(varSet2->getNameInDocument());
}

// Tests whether we can rename a property that is used in an expression in a different document
TEST_F(RenameProperty, updateExpressionDifferentDocument)
{
    // Arrange
    std::string docName = App::GetApplication().getUniqueDocumentName("test2");
    App::Document* doc2 = App::GetApplication().newDocument(docName.c_str(), "testUser");

    auto* varSet2 = freecad_cast<App::VarSet*>(doc2->addObject("App::VarSet", "VarSet2"));
    const auto* prop2 = freecad_cast<App::PropertyInteger*>(
        varSet2->addDynamicProperty("App::PropertyInteger", "Variable2", "Variables")
    );

    App::ObjectIdentifier path(*prop2);
    std::shared_ptr<App::Expression> expr(App::Expression::parse(varSet, "test#VarSet.Variable"));
    doc->saveAs("test.FCStd");
    doc2->saveAs("test2.FCStd");
    varSet2->setExpression(path, expr);
    varSet2->ExpressionEngine.execute();

    // Assert before the rename
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(prop2->getValue(), value);

    // Act
    bool isRenamed = varSet->renameDynamicProperty(prop, "NewName");
    varSet2->ExpressionEngine.execute();

    // Assert after the rename
    EXPECT_TRUE(isRenamed);
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), prop);
    EXPECT_EQ(prop2->getValue(), value);

    // Tear down
    doc2->removeObject(varSet2->getNameInDocument());
    App::GetApplication().closeDocument(doc2->getName());
}

// Test if we can rename a property which value is the result of an expression
TEST_F(RenameProperty, withExpression)
{
    // Arrange
    auto* prop2 = freecad_cast<App::PropertyInteger*>(
        varSet->addDynamicProperty("App::PropertyInteger", "Variable2", "Variables")
    );
    prop2->setValue(value);

    App::ObjectIdentifier path(*prop);
    std::shared_ptr<App::Expression> expr(App::Expression::parse(varSet, "Variable2"));
    varSet->setExpression(path, expr);
    varSet->ExpressionEngine.execute();

    // Assert before the rename
    EXPECT_EQ(prop2->getValue(), value);
    EXPECT_EQ(prop->getValue(), value);

    // Act
    bool isRenamed = varSet->renameDynamicProperty(prop, "NewName");
    varSet->ExpressionEngine.execute();

    // Assert after the rename
    EXPECT_TRUE(isRenamed);
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), prop);

    // Act
    prop2->setValue(value + 1);
    varSet->ExpressionEngine.execute();

    // Assert
    EXPECT_EQ(prop2->getValue(), value + 1);
    EXPECT_EQ(prop->getValue(), value + 1);
}

// Tests whether we can rename a property and undo it
TEST_F(RenameProperty, undo)
{
    // Act
    bool isRenamed = false;
    {
        doc->openTransaction("Rename Property");
        isRenamed = varSet->renameDynamicProperty(prop, "NewName");
        doc->commitTransaction();
    }

    // Assert
    EXPECT_TRUE(isRenamed);
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), prop);

    // Act: Undo the rename
    bool undone = doc->undo();

    // Assert: The property should be back to its original name and value
    EXPECT_TRUE(undone);
    EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), prop);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), nullptr);
}

// Tests whether adding a property as the first change under a global (application) transaction,
// as Application::setActiveTransaction makes with no active document, or openGlobalTransaction,
// is undone and redone with it (ops#163)
TEST_F(RenameProperty, addUnderGlobalTransactionUndoes)
{
    // Arrange
    int undos = doc->getAvailableUndos();

    // Act
    int tid = App::GetApplication().openGlobalTransaction({.name = "Add property"});
    auto* added = freecad_cast<App::PropertyInteger*>(
        varSet->addDynamicProperty("App::PropertyInteger", "Added")
    );
    ASSERT_NE(added, nullptr);
    added->setValue(5);
    App::GetApplication().commitTransaction(tid);

    // Assert: nothing stays booked, one step undoes and redoes the add
    EXPECT_EQ(doc->getBookedTransactionID(), 0);
    EXPECT_EQ(App::GetApplication().getGlobalTransaction(), 0);
    ASSERT_EQ(doc->getAvailableUndos(), undos + 1);
    EXPECT_TRUE(doc->undo());
    EXPECT_EQ(varSet->getDynamicPropertyByName("Added"), nullptr);
    EXPECT_TRUE(doc->redo());
    auto* redone = freecad_cast<App::PropertyInteger*>(varSet->getDynamicPropertyByName("Added"));
    ASSERT_NE(redone, nullptr);
    EXPECT_EQ(redone->getValue(), 5);
}

// Tests whether a rename as the first change under a global transaction is undone and redone with
// it (ops#163)
TEST_F(RenameProperty, renameUnderGlobalTransactionUndoes)
{
    // Arrange
    int undos = doc->getAvailableUndos();

    // Act
    int tid = App::GetApplication().openGlobalTransaction({.name = "Rename property"});
    bool isRenamed = varSet->renameDynamicProperty(prop, "NewName");
    App::GetApplication().commitTransaction(tid);

    // Assert
    EXPECT_TRUE(isRenamed);
    EXPECT_EQ(doc->getBookedTransactionID(), 0);
    EXPECT_EQ(App::GetApplication().getGlobalTransaction(), 0);
    ASSERT_EQ(doc->getAvailableUndos(), undos + 1);
    EXPECT_TRUE(doc->undo());
    EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), prop);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), nullptr);
    EXPECT_TRUE(doc->redo());
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
}

// A VarSet's Variable = Variable2 + 1, a handler of signalRenameDynamicProperty that throws for
// Variable (once, or every time), and the expression of a property by name (ops#231)
class RenameHandlerThrows: public RenameProperty
{
protected:
    void arrange(bool always)
    {
        prop2 = freecad_cast<App::PropertyInteger*>(
            varSet->addDynamicProperty("App::PropertyInteger", "Variable2", "Variables")
        );
        prop2->setValue(value);
        varSet->setExpression(
            App::ObjectIdentifier(*prop),
            std::shared_ptr<App::Expression>(App::Expression::parse(varSet, "Variable2 + 1"))
        );
        varSet->ExpressionEngine.execute();
        throws = always ? -1 : 1;
        conn = App::GetApplication().signalRenameDynamicProperty.connect(
            [this](const App::Property& renamed, const char*) {
                if (&renamed == prop && throws != 0) {
                    if (throws > 0) {
                        --throws;
                    }
                    throw Base::RuntimeError("handler failed");
                }
            }
        );
    }

    std::string expressionOf(const char* name) const
    {
        auto expressions = varSet->ExpressionEngine.getExpressions();
        auto it = expressions.find(App::ObjectIdentifier(varSet, std::string(name)));
        return it == expressions.end() ? std::string() : it->second->toString();
    }

    App::PropertyInteger* prop2 = nullptr;
    int throws = 0;
    fastsignals::scoped_connection conn;
};

// Tests whether a rename that a handler throws from once is taken back, as a refused rename:
// the old name with its expression, and nothing to abort
TEST_F(RenameHandlerThrows, takenBack)
{
    arrange(false);

    doc->openTransaction("Rename Property");
    EXPECT_THROW(varSet->renameDynamicProperty(prop, "NewName"), Base::RuntimeError);

    EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
    EXPECT_EQ(expressionOf("Variable"), "Variable2 + 1");
    EXPECT_EQ(expressionOf("NewName"), "");
    doc->abortTransaction();
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), prop);
    EXPECT_EQ(expressionOf("Variable"), "Variable2 + 1");
    prop2->setValue(value + 1);
    varSet->ExpressionEngine.execute();
    EXPECT_EQ(prop->getValue(), value + 2);
}

// Tests whether a rename whose handler throws every time, also when the rename is taken back, is
// still taken back: the name changes before the handlers run
TEST_F(RenameHandlerThrows, takenBackWhenHandlerAlwaysThrows)
{
    arrange(true);

    doc->openTransaction("Rename Property");
    EXPECT_THROW(varSet->renameDynamicProperty(prop, "NewName"), Base::RuntimeError);
    throws = 0;
    EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
    EXPECT_EQ(expressionOf("Variable"), "Variable2 + 1");
    EXPECT_EQ(expressionOf("NewName"), "");

    doc->abortTransaction();
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), prop);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), nullptr);
    EXPECT_EQ(expressionOf("Variable"), "Variable2 + 1");
    prop2->setValue(value + 1);
    varSet->ExpressionEngine.execute();
    EXPECT_EQ(prop->getValue(), value + 2);
}

// Tests whether a rename taken back after a handler threw, committed, leaves at most one undo
// step (the expressions renamed and renamed back) that changes nothing on undo and redo (review of
// fork PR 213)
TEST_F(RenameHandlerThrows, takenBackCommitted)
{
    arrange(false);
    int undos = doc->getAvailableUndos();

    doc->openTransaction("Rename Property");
    EXPECT_THROW(varSet->renameDynamicProperty(prop, "NewName"), Base::RuntimeError);
    doc->commitTransaction();

    int steps = doc->getAvailableUndos() - undos;
    EXPECT_LE(steps, 1);
    for (int round = 0; round < 2 * steps; ++round) {
        EXPECT_TRUE(round % 2 == 0 ? doc->undo() : doc->redo());
        EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
        EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), nullptr);
        EXPECT_EQ(expressionOf("Variable"), "Variable2 + 1");
    }
    EXPECT_EQ(doc->getAvailableUndos(), undos + steps);
}

// Tests the same when the handler throws again as the rename is taken back
TEST_F(RenameHandlerThrows, takenBackCommittedWhenHandlerAlwaysThrows)
{
    arrange(true);
    int undos = doc->getAvailableUndos();

    doc->openTransaction("Rename Property");
    EXPECT_THROW(varSet->renameDynamicProperty(prop, "NewName"), Base::RuntimeError);
    throws = 0;
    doc->commitTransaction();

    int steps = doc->getAvailableUndos() - undos;
    EXPECT_LE(steps, 1);
    for (int round = 0; round < 2 * steps; ++round) {
        EXPECT_TRUE(round % 2 == 0 ? doc->undo() : doc->redo());
        EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
        EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), nullptr);
        EXPECT_EQ(expressionOf("Variable"), "Variable2 + 1");
    }
    EXPECT_EQ(doc->getAvailableUndos(), undos + steps);
}

// Tests whether undo goes on when a handler refuses the rename back (ops#231: a rename whose
// handler throws is taken back): the property keeps its new name, the rest of the transaction (a
// value) is undone, an error is logged, and redo and a second undo restore the value without the
// handler throwing (review of fork PR 216). The expression engine is restored as it was before the
// transaction, under the old name, which no property has then (ops#238).
TEST_F(RenameHandlerThrows, failingRenameBack)
{
    arrange(false);
    throws = 0;

    doc->openTransaction("Rename Property");
    EXPECT_TRUE(varSet->renameDynamicProperty(prop, "NewName"));
    prop2->setValue(value + 5);
    doc->commitTransaction();
    EXPECT_EQ(expressionOf("NewName"), "Variable2 + 1");
    auto assertState = [this](long value2) {
        EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
        EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
        EXPECT_EQ(prop2->getValue(), value2);
    };

    ErrorCollector errors;
    throws = 1;
    EXPECT_NO_THROW(doc->undo());
    EXPECT_EQ(throws, 0);
    EXPECT_EQ(errors.errors.size(), 1);
    assertState(value);
    EXPECT_EQ(expressionOf("Variable"), "Variable2 + 1");
    EXPECT_EQ(expressionOf("NewName"), "");
    EXPECT_NO_THROW(doc->redo());
    assertState(value + 5);
    EXPECT_NO_THROW(doc->undo());
    assertState(value);
}

// Tests whether we can rename a property, undo, and redo it
TEST_F(RenameProperty, redo)
{
    // Act
    bool isRenamed = false;
    {
        doc->openTransaction("Rename Property");
        isRenamed = varSet->renameDynamicProperty(prop, "NewName");
        doc->commitTransaction();
    }

    // Assert
    EXPECT_TRUE(isRenamed);
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), prop);

    // Act: Undo the rename
    bool undone = doc->undo();

    // Assert: The property should be back to its original name and value
    EXPECT_TRUE(undone);
    EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), prop);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), nullptr);

    // Act: Redo the rename
    bool redone = doc->redo();
    EXPECT_TRUE(redone);
    EXPECT_STREQ(varSet->getPropertyName(prop), "NewName");
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(varSet->getDynamicPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet->getDynamicPropertyByName("NewName"), prop);
}

// Tests whether an expression in another object, changed in a transaction that swaps the names of
// the properties it refers to, comes back referring to the same properties (ops#238 probe: undo's
// temporary names rename the expressions in every container, the undo entries' copies included)
TEST_F(RenameProperty, swapWithExpressionChangedInOtherObject)
{
    auto* other = freecad_cast<App::PropertyInteger*>(
        varSet->addDynamicProperty("App::PropertyInteger", "Other", "Variables")
    );
    other->setValue(7);
    auto* varSet2 = freecad_cast<App::VarSet*>(doc->addObject("App::VarSet", "VarSet2"));
    auto* result = freecad_cast<App::PropertyInteger*>(
        varSet2->addDynamicProperty("App::PropertyInteger", "Result", "Variables")
    );
    const App::ObjectIdentifier path(*result);
    auto setExpression = [&](const char* text) {
        varSet2->setExpression(
            path,
            std::shared_ptr<App::Expression>(App::Expression::parse(varSet2, text))
        );
    };
    auto expression = [&] {
        auto expressions = varSet2->ExpressionEngine.getExpressions();
        auto it = expressions.find(path);
        return it == expressions.end() ? std::string() : it->second->toString();
    };
    auto evaluate = [&] {
        varSet2->ExpressionEngine.execute();
        return result->getValue();
    };
    setExpression("VarSet.Variable + 1");
    EXPECT_EQ(evaluate(), value + 1);
    const std::string before = expression();
    ErrorCollector errors;

    for (const bool commit : {false, true}) {
        doc->openTransaction("Swap");
        EXPECT_TRUE(varSet->renameDynamicProperty(prop, "Tmp"));
        EXPECT_TRUE(varSet->renameDynamicProperty(other, "Variable"));
        EXPECT_TRUE(varSet->renameDynamicProperty(prop, "Other"));
        EXPECT_EQ(evaluate(), value + 1);
        setExpression("VarSet.Variable * 2");
        EXPECT_EQ(evaluate(), 14);
        const std::string changed = expression();
        if (commit) {
            doc->commitTransaction();
            EXPECT_TRUE(doc->undo());
        }
        else {
            doc->abortTransaction();
        }
        EXPECT_STREQ(varSet->getPropertyName(prop), "Variable");
        EXPECT_STREQ(varSet->getPropertyName(other), "Other");
        EXPECT_EQ(expression(), before) << (commit ? "undo" : "abort");
        EXPECT_EQ(evaluate(), value + 1);
        if (commit) {
            EXPECT_TRUE(doc->redo());
            EXPECT_STREQ(varSet->getPropertyName(prop), "Other");
            EXPECT_EQ(expression(), changed);
            EXPECT_EQ(evaluate(), 14);
            EXPECT_TRUE(doc->undo());
            EXPECT_EQ(expression(), before);
            EXPECT_EQ(evaluate(), value + 1);
        }
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
    doc->clearUndos();
    doc->removeObject(varSet2->getNameInDocument());
}

/*
 * For these tests we have the following variables that correspond to the
 * following names:
 *
 * The documents:
 * - doc1: "test"
 * - doc2: "test1"
 *
 * The VarSet objects in doc1 are:
 * - varSet1Doc1: "VarSet"
 * - varSet2Doc1: "VarSet001"
 *
 * The VarSet object in doc2 is:
 * - varSetDoc2: "VarSet"
 *
 * The property to move:
 * - prop: "Variable" and is an integer with value 123 and is initially in varSet1Doc1.
 */

void MoveProperty::assertMovedProperty(App::Property* property, App::DocumentObject* target)

{
    ASSERT_TRUE(property != nullptr);
    EXPECT_EQ(property->getContainer(), target);
    EXPECT_EQ(varSet1Doc1->getDynamicPropertyByName("Variable"), nullptr);

    auto* movedPropWithType = freecad_cast<App::PropertyInteger*>(
        target->getDynamicPropertyByName("Variable")
    );
    ASSERT_TRUE(movedPropWithType != nullptr);
    EXPECT_EQ(movedPropWithType->getValue(), value);
}

// Helper function to test moving a property
void MoveProperty::testMoveProperty(App::DocumentObject* target)
{
    // Act
    App::Property* movedProp = varSet1Doc1->moveDynamicProperty(prop, target);

    assertMovedProperty(movedProp, target);
    // Assert
}

// Tests whether we can move a property to a different container
// test#VarSet.Variable -> test#VarSet001.Variable
TEST_F(MoveProperty, simple)
{
    testMoveProperty(varSet2Doc1);
}

// Tests whether we can move a property to a container in a different document
// test#VarSet.Variable -> test1#VarSet.Variable
TEST_F(MoveProperty, otherDoc)
{
    testMoveProperty(varSetDoc2);
}

// Tests whether we can move a static property
// test#Cube.Length -> FAIL
TEST_F(MoveProperty, staticProperty)
{
    // Arrange
    App::DocumentObject* cube = doc1->addObject("Part::Box", "Cube");
    App::Property* prop = cube->getPropertyByName("Length");

    // Act
    EXPECT_THROW(varSet1Doc1->moveDynamicProperty(prop, varSet2Doc1), Base::RuntimeError);

    // Assert
    EXPECT_EQ(cube->getPropertyByName("Length"), prop);
    EXPECT_EQ(varSet2Doc1->getDynamicPropertyByName("Length"), nullptr);

    // Tear down
    doc1->removeObject(cube->getNameInDocument());
}

// Tests whether we can move a static property
// test#VarSet.Variable (locked) -> FAIL
TEST_F(MoveProperty, lockedProperty)
{
    // Arrange
    prop->setStatus(App::Property::LockDynamic, true);

    // Act / Assert
    EXPECT_THROW(varSet1Doc1->moveDynamicProperty(prop, varSet2Doc1), Base::RuntimeError);
    EXPECT_EQ(varSet1Doc1->getPropertyByName("Variable"), prop);
}

// Tests whether we can move to a property that already exists
// test#VarSet.Variable -> test#VarSet001.Variable (already existing): FAIL
TEST_F(MoveProperty, toExistingProperty)
{
    // Arrange
    App::Property* prop2
        = varSet2Doc1->addDynamicProperty("App::PropertyInteger", "Variable", "Variables");

    // Act / Assert
    EXPECT_THROW(varSet1Doc1->moveDynamicProperty(prop, varSet2Doc1), Base::NameError);

    EXPECT_EQ(varSet1Doc1->getPropertyByName("Variable"), prop);
    EXPECT_EQ(varSet2Doc1->getPropertyByName("Variable"), prop2);
}

void MoveProperty::testMovePropertyExpressionWithAct(
    App::DocumentObject* sourceProp2,
    App::DocumentObject* target,
    const char* exprString,
    const std::function<App::Property*()>& act
)
{
    // Arrange
    const auto* prop2 = freecad_cast<App::PropertyInteger*>(
        sourceProp2->addDynamicProperty("App::PropertyInteger", "Variable2", "Variables")
    );

    App::ObjectIdentifier path(*prop2);
    std::shared_ptr<App::Expression> expr(App::Expression::parse(varSet1Doc1, "Variable"));
    doc1->saveAs("test.FCStd");
    doc2->saveAs("test1.FCStd");

    sourceProp2->setExpression(path, expr);
    sourceProp2->ExpressionEngine.execute();

    // Assert before the move
    EXPECT_EQ(prop->getValue(), value);
    EXPECT_EQ(prop2->getValue(), value);

    // Act
    App::Property* movedProp = act();
    sourceProp2->ExpressionEngine.execute();

    // Assert after the move
    ASSERT_TRUE(movedProp != nullptr);
    EXPECT_EQ(varSet1Doc1->getPropertyByName("Variable"), nullptr);

    auto* movedPropWithType = freecad_cast<App::PropertyInteger*>(
        target->getDynamicPropertyByName("Variable")
    );
    ASSERT_TRUE(movedPropWithType != nullptr);
    EXPECT_EQ(movedPropWithType->getValue(), value);
    EXPECT_STREQ(
        sourceProp2->ExpressionEngine.getExpressions().begin()->second->toString().c_str(),
        exprString
    );
}

void MoveProperty::testMovePropertyExpression(
    App::DocumentObject* sourceProp2,
    App::DocumentObject* target,
    const char* exprString
)
{
    auto act = [this, target]() -> App::Property* {
        return varSet1Doc1->moveDynamicProperty(prop, target);
    };
    testMovePropertyExpressionWithAct(sourceProp2, target, exprString, act);
}

// Tests whether we can move a property that is used in an expression in the
// originating container
// test#VarSet.Variable -> test#VarSet001.Variable where
// test#VarSet.Variable2 = Variable -> test#VarSet.Variable2 = VarSet001.Variable
TEST_F(MoveProperty, updateExpressionOriginatingContainer)
{
    testMovePropertyExpression(varSet1Doc1, varSet2Doc1, "VarSet001.Variable");
}

// Tests whether we can move a property that is used in an expression in the
// target container
// test#VarSet.Variable -> test#VarSet001.Variable where
// test#VarSet001.Variable2 = VarSet.Variable -> test#VarSet001.Variable2 = Variable
TEST_F(MoveProperty, updateExpressionTargetContainer)
{
    testMovePropertyExpression(varSet2Doc1, varSet2Doc1, "Variable");
}

// Tests whether we can move a property to another document that is used in an
// expression in the originating container
// test#VarSet.Variable -> test1#VarSet.Variable where
// test#VarSet.Variable2 = Variable -> test#VarSet.Variable2 = test1#VarSet.Variable
TEST_F(MoveProperty, updateExpressionOriginatingContainerOtherDoc)
{
    testMovePropertyExpression(varSet1Doc1, varSetDoc2, "test1#VarSet.Variable");
}

// Tests whether we can move a property to another document that is used in an
// expression in the target container
// test#VarSet.Variable -> test1#VarSet.Variable where
// test1#VarSet.Variable2 = test#VarSet.Variable -> test1#VarSet.Variable2 = Variable
TEST_F(MoveProperty, updateExpressionTargetContainerOtherDoc)
{
    testMovePropertyExpression(varSetDoc2, varSetDoc2, "Variable");
}

// Tests whether we can move a property that obtains its value from an expression.
// test#VarSet.Variable -> test#VarSet001.Variable where
// test#VarSet.Variable = Variable2 -> test#VarSet001.Variable = VarSet.Variable2
TEST_F(MoveProperty, updateExpressionMovedProp)
{
    // Arrange
    auto* prop2 = freecad_cast<App::PropertyInteger*>(
        varSet1Doc1->addDynamicProperty("App::PropertyInteger", "Variable2", "Variables")
    );
    int valueVar2 = 10;
    prop2->setValue(valueVar2);

    App::ObjectIdentifier path(*prop);
    std::shared_ptr<App::Expression> expr(App::Expression::parse(varSet1Doc1, "Variable2"));
    varSet1Doc1->setExpression(path, expr);
    varSet1Doc1->ExpressionEngine.execute();

    // Assert before the move
    EXPECT_EQ(prop->getValue(), valueVar2);
    EXPECT_EQ(prop2->getValue(), valueVar2);

    // Act
    App::Property* movedProp = nullptr;
    movedProp = varSet1Doc1->moveDynamicProperty(prop, varSet2Doc1);
    varSet1Doc1->ExpressionEngine.execute();
    varSet2Doc1->ExpressionEngine.execute();

    // Assert after the move
    ASSERT_TRUE(movedProp != nullptr);
    EXPECT_EQ(varSet1Doc1->getPropertyByName("Variable"), nullptr);
    EXPECT_EQ(varSet1Doc1->ExpressionEngine.getExpressions().size(), 0);

    auto* movedPropWithType = freecad_cast<App::PropertyInteger*>(
        varSet2Doc1->getDynamicPropertyByName("Variable")
    );
    ASSERT_TRUE(movedPropWithType != nullptr);
    EXPECT_EQ(movedPropWithType->getValue(), valueVar2);

    std::map<App::ObjectIdentifier, const App::Expression*> expressions
        = varSet2Doc1->ExpressionEngine.getExpressions();
    ASSERT_EQ(expressions.size(), 1);
    EXPECT_STREQ(expressions.begin()->first.getPropertyName().c_str(), "Variable");
    EXPECT_STREQ(expressions.begin()->second->toString().c_str(), "VarSet.Variable2");
}

void MoveProperty::testUndoProperty(App::DocumentObject* target)
{
    // Act
    App::Property* movedProp = nullptr;
    {
        doc1->openTransaction("Move Property");
        movedProp = varSet1Doc1->moveDynamicProperty(prop, target);
        doc1->commitTransaction();
    }

    // Assert
    assertMovedProperty(movedProp, target);

    // Act: Undo the move
    bool undone = doc1->undo();

    // Assert: The property should be back to its original container and value
    EXPECT_TRUE(undone);
    auto* originalProp = freecad_cast<App::PropertyInteger*>(
        varSet1Doc1->getDynamicPropertyByName("Variable")
    );
    ASSERT_TRUE(originalProp != nullptr);
    EXPECT_EQ(originalProp->getValue(), value);
    EXPECT_EQ(target->getPropertyByName("Variable"), nullptr);
}

// Tests whether we can move a property and undo it
// test#VarSet.Variable -> test#VarSet001.Variable and back
TEST_F(MoveProperty, undo)
{
    testUndoProperty(varSet2Doc1);
}

// Tests whether we can move a property to a container in a different document
// test#VarSet.Variable -> test1#VarSet.Variable and back
TEST_F(MoveProperty, undoOtherDoc)
{
    testUndoProperty(varSetDoc2);
}

void MoveProperty::testUndoMovePropertyExpression(
    App::DocumentObject* sourceProp2,
    App::DocumentObject* target,
    const char* exprString,
    const char* exprStringAfterUndo
)
{
    // Arrange
    auto act = [this, target] {
        App::Property* movedProp = nullptr;
        {
            doc1->openTransaction("Move Property");
            movedProp = varSet1Doc1->moveDynamicProperty(prop, target);
            doc1->commitTransaction();
        }
        return movedProp;
    };


    testMovePropertyExpressionWithAct(sourceProp2, target, exprString, act);

    // Act: Undo the move
    bool undone = doc1->undo();

    doc1->recompute();
    doc2->recompute();
    sourceProp2->ExpressionEngine.execute();

    // Assert
    EXPECT_TRUE(undone);
    auto* originalProp = freecad_cast<App::PropertyInteger*>(
        varSet1Doc1->getDynamicPropertyByName("Variable")
    );
    ASSERT_TRUE(originalProp != nullptr);
    EXPECT_EQ(originalProp->getValue(), value);
    EXPECT_STREQ(
        sourceProp2->ExpressionEngine.getExpressions().begin()->second->toString().c_str(),
        exprStringAfterUndo
    );

    EXPECT_EQ(target->getPropertyByName("Variable"), nullptr);
}

// Tests whether we can undo a move of a property that is used in an expression
// in the originating container.
//
// test#VarSet.Variable -> test#VarSet001.Variable where
// test#VarSet.Variable2 = Variable -> test#VarSet.Variable2 = VarSet001.Variable
// and back
TEST_F(MoveProperty, undoExpressionOriginatingContainer)
{
    testUndoMovePropertyExpression(varSet1Doc1, varSet2Doc1, "VarSet001.Variable", "Variable");
}

// Tests whether we can undo a move of a property that is used in an expression
// in the target container.
//
// test#VarSet.Variable -> test#VarSet001.Variable where
// test#VarSet001.Variable2 = VarSet.Variable -> test#VarSet001.Variable2 = Variable
// and back
TEST_F(MoveProperty, undoExpressionTargetContainer)
{
    testUndoMovePropertyExpression(varSet2Doc1, varSet2Doc1, "Variable", "VarSet.Variable");
}

// Tests whether we can undo a move of a property that is used in an expression
// in the originating container.
//
// test#VarSet.Variable -> test1#VarSet.Variable where
// test#VarSet.Variable2 = Variable -> test#VarSet.Variable2 = test1#VarSet.Variable
// and back
TEST_F(MoveProperty, undoExpressionOriginatingContainerOtherDoc)
{
    testUndoMovePropertyExpression(varSet1Doc1, varSetDoc2, "test1#VarSet.Variable", "Variable");
}

// Tests whether we can undo a move of a property that is used in an expression
// in the target container.
//
// test#VarSet.Variable -> test1#VarSet.Variable where
// test1#VarSet.Variable2 = test#VarSet.Variable -> test1#VarSet.Variable2 = Variable
// and back
TEST_F(MoveProperty, undoExpressionTargetContainerOtherDoc)
{
    testUndoMovePropertyExpression(varSetDoc2, varSetDoc2, "Variable", "test#VarSet.Variable");
}

// Tests whether we can undo and redo a property move
//
// test#VarSet.Variable -> test#VarSet001.Variable and back and back again.
TEST_F(MoveProperty, redoSimple)
{
    testUndoProperty(varSet2Doc1);
    // Act: Redo the move
    bool redone = doc1->redo();

    // Assert: The property should be moved to the new container again
    EXPECT_TRUE(redone);
    App::Property* movedPropWithType = freecad_cast<App::PropertyInteger*>(
        varSet2Doc1->getDynamicPropertyByName("Variable")
    );
    assertMovedProperty(movedPropWithType, varSet2Doc1);
}

// Tests whether we can undo and redo a property move to a different document
//
// test#VarSet.Variable -> test1#VarSet001.Variable and back and back again.
TEST_F(MoveProperty, redoOtherDoc)
{
    testUndoProperty(varSetDoc2);

    // Act: Redo the move
    bool redone = doc1->redo();
    doc1->recompute();
    doc2->recompute();

    // Assert: The property should be moved to the new container again
    EXPECT_TRUE(redone);
    App::Property* movedPropWithType = freecad_cast<App::PropertyInteger*>(
        varSetDoc2->getDynamicPropertyByName("Variable")
    );
    assertMovedProperty(movedPropWithType, varSetDoc2);
}

void MoveProperty::testRedoMovePropertyExpression(
    App::DocumentObject* sourceProp2,
    App::DocumentObject* target,
    const char* exprString,
    const char* exprStringAfterUndo
)
{
    testUndoMovePropertyExpression(sourceProp2, target, exprString, exprStringAfterUndo);

    bool redone = doc1->redo();
    doc1->recompute();
    doc2->recompute();
    sourceProp2->ExpressionEngine.execute();

    // Assert: The property should be moved to the target container again
    EXPECT_TRUE(redone);
    auto* movedPropWithType = freecad_cast<App::PropertyInteger*>(
        target->getDynamicPropertyByName("Variable")
    );
    ASSERT_TRUE(movedPropWithType != nullptr);
    EXPECT_EQ(movedPropWithType->getValue(), value);
    EXPECT_STREQ(
        sourceProp2->ExpressionEngine.getExpressions().begin()->second->toString().c_str(),
        exprString
    );
}

// Tests whether we can undo and redo a move of a property that is used in an
// expression in the originating container.
//
// test#VarSet.Variable -> test#VarSet001.Variable where
// test#VarSet.Variable2 = Variable -> test#VarSet.Variable2 = VarSet001.Variable
// and back and back again.
TEST_F(MoveProperty, redoExpressionOriginatingContainer)
{
    testRedoMovePropertyExpression(varSet1Doc1, varSet2Doc1, "VarSet001.Variable", "Variable");
}

// Tests whether we can undo and redo a move of a property that is used in an expression
// in the target container.
//
// test#VarSet.Variable -> test#VarSet001.Variable where
// test#VarSet001.Variable2 = VarSet.Variable -> test#VarSet001.Variable2 = Variable
// and back and back again.
TEST_F(MoveProperty, redoExpressionTargetContainer)
{
    testRedoMovePropertyExpression(varSet2Doc1, varSet2Doc1, "Variable", "VarSet.Variable");
}

// Tests whether we can undo and redo a move of a property that is used in an
// expression in the originating container.
//
// test#VarSet.Variable -> test1#VarSet.Variable where
// test#VarSet.Variable2 = Variable -> test#VarSet.Variable2 = test1#VarSet.Variable
// and back and back again.
TEST_F(MoveProperty, redoExpressionOriginatingContainerOtherDoc)
{
    testRedoMovePropertyExpression(varSet1Doc1, varSetDoc2, "test1#VarSet.Variable", "Variable");
}

// Tests whether we can undo and redo a move of a property that is used in an
// expression in the target container.
//
// test#VarSet.Variable -> test1#VarSet.Variable where
// test1#VarSet.Variable2 = test#VarSet.Variable -> test1#VarSet.Variable2 = Variable
// and back and back again
TEST_F(MoveProperty, redoExpressionTargetContainerOtherDoc)
{
    testRedoMovePropertyExpression(varSetDoc2, varSetDoc2, "Variable", "test#VarSet.Variable");
}

// Tests whether a property moved to another object and back in one transaction is undone, aborted
// and redone without an error (it used to be renamed to its own name), its value restored and the
// expression that uses it unchanged (review of fork PR 216)
TEST_F(MoveProperty, moveBack)
{
    auto* prop2 = freecad_cast<App::PropertyInteger*>(
        varSet1Doc1->addDynamicProperty("App::PropertyInteger", "Variable2", "Variables")
    );
    varSet1Doc1->setExpression(
        App::ObjectIdentifier(*prop2),
        std::shared_ptr<App::Expression>(App::Expression::parse(varSet1Doc1, "Variable + 1"))
    );
    auto expressions = [this] {
        std::vector<std::string> result;
        for (const auto& [path, expr] : varSet1Doc1->ExpressionEngine.getExpressions()) {
            result.push_back(path.toString() + " = " + expr->toString());
        }
        return result;
    };
    const auto expressionsBefore = expressions();
    auto variable = [this] {
        return freecad_cast<App::PropertyInteger*>(varSet1Doc1->getDynamicPropertyByName("Variable"));
    };
    // (a move taken back moves a new property back: prop is gone after the first abort)
    auto moveThereAndBack = [this, &variable] {
        App::Property* moved = varSet1Doc1->moveDynamicProperty(variable(), varSet2Doc1);
        App::Property* back = varSet2Doc1->moveDynamicProperty(moved, varSet1Doc1);
        freecad_cast<App::PropertyInteger*>(back)->setValue(value + 1);
    };
    auto assertState = [&](long expected) {
        ASSERT_NE(variable(), nullptr);
        EXPECT_EQ(variable()->getValue(), expected);
        EXPECT_EQ(varSet2Doc1->getPropertyByName("Variable"), nullptr);
        EXPECT_EQ(expressions(), expressionsBefore);
    };
    ErrorCollector errors;

    doc1->openTransaction("Move Property");
    moveThereAndBack();
    doc1->abortTransaction();
    assertState(value);

    doc1->openTransaction("Move Property");
    moveThereAndBack();
    doc1->commitTransaction();
    for (int round = 0; round < 2; ++round) {
        EXPECT_TRUE(doc1->undo());
        assertState(value);
        EXPECT_TRUE(doc1->redo());
        assertState(value + 1);
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
}

// Tests whether a property moved out of an object created and then removed in the same
// transaction can still be changed, renamed and moved: the removed object's move entry went with
// it (review of fork PR 216: it was read after it was freed). Since ops#238 the property counts
// as added to its target, so undo removes it and redo brings it back.
TEST_F(MoveProperty, sourceRemovedInTransaction)
{
    ErrorCollector errors;
    for (const bool commit : {false, true}) {
        doc1->openTransaction("Move Property");
        auto* source = doc1->addObject("App::VarSet", "Source");
        App::Property* added =
            source->addDynamicProperty("App::PropertyInteger", "Moved", "Variables");
        App::Property* moved = source->moveDynamicProperty(added, varSet2Doc1);
        ASSERT_NE(moved, nullptr);
        doc1->removeObject(source->getNameInDocument());
        freecad_cast<App::PropertyInteger*>(moved)->setValue(5);
        EXPECT_TRUE(varSet2Doc1->renameDynamicProperty(moved, "Renamed"));
        moved = varSet2Doc1->moveDynamicProperty(moved, varSet1Doc1);
        ASSERT_NE(moved, nullptr);
        freecad_cast<App::PropertyInteger*>(moved)->setValue(6);
        if (commit) {
            doc1->commitTransaction();
            EXPECT_TRUE(doc1->undo());
        }
        else {
            doc1->abortTransaction();
        }

        EXPECT_EQ(doc1->getObject("Source"), nullptr);
        EXPECT_EQ(varSet1Doc1->getPropertyByName("Renamed"), nullptr);
        ASSERT_EQ(varSet1Doc1->getDynamicPropertyByName("Variable"), prop);
        EXPECT_EQ(prop->getValue(), value);
        std::vector<std::string> names;
        for (auto* obj : {varSet1Doc1, varSet2Doc1}) {
            for (const char* name : {"Moved", "Renamed"}) {
                if (obj->getDynamicPropertyByName(name)) {
                    names.push_back(std::string(obj->getNameInDocument()) + "." + name);
                    obj->removeDynamicProperty(name);
                }
            }
        }
        // ops#238: it used to stay on the first target, under its name at the move
        EXPECT_EQ(names, std::vector<std::string>()) << (commit ? "undo" : "abort");
        if (commit) {
            EXPECT_TRUE(doc1->redo());
            auto* renamed = freecad_cast<App::PropertyInteger*>(
                varSet1Doc1->getDynamicPropertyByName("Renamed")
            );
            ASSERT_NE(renamed, nullptr);
            EXPECT_EQ(renamed->getValue(), 6);
            EXPECT_EQ(varSet2Doc1->getPropertyByName("Moved"), nullptr);
            EXPECT_TRUE(doc1->undo());
            EXPECT_EQ(varSet1Doc1->getPropertyByName("Renamed"), nullptr);
        }
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
}

namespace
{
std::vector<std::string> dynamicNames(const App::DocumentObject* obj)
{
    auto names = obj->getDynamicPropertyNames();
    std::ranges::sort(names);
    return names;
}

long intValue(const App::DocumentObject* obj, const char* name)
{
    auto* prop = freecad_cast<App::PropertyInteger*>(obj->getDynamicPropertyByName(name));
    return prop ? prop->getValue() : -1;
}
}  // namespace

// Tests whether a property moved into an object that is created and then removed in the same
// transaction comes back on undo: the move becomes a removal (ops#238; the move entry pointed at
// the freed object, read on undo and abort, and a later property at the same address was taken
// for the moved one)
TEST_F(MoveProperty, targetRemovedInTransaction)
{
    ErrorCollector errors;
    for (const bool commit : {false, true}) {
        doc1->openTransaction("Move Property");
        auto* target = doc1->addObject("App::VarSet", "Target");
        auto* moved = freecad_cast<App::PropertyInteger*>(
            varSet1Doc1->moveDynamicProperty(varSet1Doc1->getDynamicPropertyByName("Variable"),
                                             target)
        );
        ASSERT_NE(moved, nullptr);
        moved->setValue(5);
        doc1->removeObject(target->getNameInDocument());
        // a property allocated now may take the moved one's address
        varSet2Doc1->addDynamicProperty("App::PropertyInteger", "Other", "Variables");
        if (commit) {
            doc1->commitTransaction();
            EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>());
            EXPECT_TRUE(doc1->undo());
        }
        else {
            doc1->abortTransaction();
        }
        EXPECT_EQ(doc1->getObject("Target"), nullptr);
        EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>({"Variable"}))
            << (commit ? "undo" : "abort");
        EXPECT_EQ(intValue(varSet1Doc1, "Variable"), value);
        EXPECT_EQ(dynamicNames(varSet2Doc1), std::vector<std::string>());
        if (commit) {
            EXPECT_TRUE(doc1->redo());
            EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>());
            EXPECT_EQ(dynamicNames(varSet2Doc1), std::vector<std::string>({"Other"}));
            EXPECT_TRUE(doc1->undo());
            EXPECT_EQ(intValue(varSet1Doc1, "Variable"), value);
        }
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
}

// Tests whether a property moved into an object created in the same transaction moves back on
// undo and abort (ops#238: undo removed the target first, and its move was skipped, so the
// property went with it; abort destroyed the target before the move entry read it)
TEST_F(MoveProperty, intoObjectCreatedInTransaction)
{
    ErrorCollector errors;
    for (const bool commit : {false, true}) {
        doc1->openTransaction("Move Property");
        auto* target = doc1->addObject("App::VarSet", "Target");
        auto* moved = freecad_cast<App::PropertyInteger*>(
            varSet1Doc1->moveDynamicProperty(varSet1Doc1->getDynamicPropertyByName("Variable"),
                                             target)
        );
        ASSERT_NE(moved, nullptr);
        moved->setValue(5);
        EXPECT_TRUE(target->renameDynamicProperty(moved, "Renamed"));
        if (commit) {
            doc1->commitTransaction();
            EXPECT_TRUE(doc1->undo());
        }
        else {
            doc1->abortTransaction();
        }
        EXPECT_EQ(doc1->getObject("Target"), nullptr);
        EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>({"Variable"}))
            << (commit ? "undo" : "abort");
        EXPECT_EQ(intValue(varSet1Doc1, "Variable"), value);
        if (commit) {
            EXPECT_TRUE(doc1->redo());
            auto* redone = doc1->getObject("Target");
            ASSERT_NE(redone, nullptr);
            EXPECT_EQ(dynamicNames(redone), std::vector<std::string>({"Renamed"}));
            EXPECT_EQ(intValue(redone, "Renamed"), 5);
            EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>());
            EXPECT_TRUE(doc1->undo());
            EXPECT_EQ(doc1->getObject("Target"), nullptr);
            EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>({"Variable"}));
            EXPECT_EQ(intValue(varSet1Doc1, "Variable"), value);
        }
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
}

// Tests whether a property added to an object created in the transaction and moved out of it is
// removed from its target on undo and abort, and moved there again on redo (ops#238: the created
// object's entries were skipped, so the property stayed on the target)
TEST_F(MoveProperty, outOfObjectCreatedInTransaction)
{
    ErrorCollector errors;
    for (const bool commit : {false, true}) {
        doc1->openTransaction("Move Property");
        auto* source = doc1->addObject("App::VarSet", "Source");
        auto* added = freecad_cast<App::PropertyInteger*>(
            source->addDynamicProperty("App::PropertyInteger", "Moved", "Variables")
        );
        added->setValue(7);
        ASSERT_NE(source->moveDynamicProperty(added, varSet2Doc1), nullptr);
        if (commit) {
            doc1->commitTransaction();
            EXPECT_TRUE(doc1->undo());
        }
        else {
            doc1->abortTransaction();
        }
        EXPECT_EQ(doc1->getObject("Source"), nullptr);
        EXPECT_EQ(dynamicNames(varSet2Doc1), std::vector<std::string>())
            << (commit ? "undo" : "abort");
        if (commit) {
            EXPECT_TRUE(doc1->redo());
            auto* redone = doc1->getObject("Source");
            ASSERT_NE(redone, nullptr);
            EXPECT_EQ(dynamicNames(redone), std::vector<std::string>());
            EXPECT_EQ(intValue(varSet2Doc1, "Moved"), 7);
            EXPECT_TRUE(doc1->undo());
            EXPECT_EQ(dynamicNames(varSet2Doc1), std::vector<std::string>());
        }
        for (const auto& name : dynamicNames(varSet2Doc1)) {
            varSet2Doc1->removeDynamicProperty(name.c_str());
        }
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
}

// Tests whether an object changed and then removed in a transaction comes back with its values
// from before the transaction, through undo, redo and undo again (ops#238 probe: "a Del object
// ignores its earlier Chn entries")
TEST_F(MoveProperty, changedThenRemovedObject)
{
    ErrorCollector errors;
    for (const bool commit : {false, true}) {
        doc1->openTransaction("Change and Remove");
        freecad_cast<App::PropertyInteger*>(varSet1Doc1->getDynamicPropertyByName("Variable"))
            ->setValue(5);
        EXPECT_TRUE(varSet1Doc1->renameDynamicProperty(
            varSet1Doc1->getDynamicPropertyByName("Variable"),
            "Renamed"
        ));
        doc1->removeObject(varSet1Doc1->getNameInDocument());
        if (commit) {
            doc1->commitTransaction();
            EXPECT_TRUE(doc1->undo());
            EXPECT_TRUE(doc1->redo());
            EXPECT_EQ(doc1->getObject("VarSet"), nullptr);
            EXPECT_TRUE(doc1->undo());
        }
        else {
            doc1->abortTransaction();
        }
        ASSERT_EQ(doc1->getObject("VarSet"), varSet1Doc1);
        EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>({"Variable"}));
        EXPECT_EQ(intValue(varSet1Doc1, "Variable"), value);
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
}

// Tests whether a move whose signalMoveDynamicProperty handler throws leaves the property on one
// object only, the target, with its value, as the transaction recorded, and whether abort, undo
// and redo take it back and forth, also when the handler throws while they move it (ops#238: it
// was left on both objects; review of fork PR 222: a move back whose handler threw stayed on the
// source under its temporary name)
TEST_F(MoveProperty, moveHandlerThrows)
{
    int throws = 0;
    fastsignals::scoped_connection conn = App::GetApplication().signalMoveDynamicProperty.connect(
        [&throws](const App::Property&, const App::DocumentObject&) {
            if (throws > 0) {
                --throws;
                throw Base::RuntimeError("handler failed");
            }
        }
    );
    auto assertOn = [this](App::DocumentObject* on, App::DocumentObject* off) {
        EXPECT_EQ(dynamicNames(on), std::vector<std::string>({"Variable"}));
        EXPECT_EQ(intValue(on, "Variable"), value);
        EXPECT_EQ(dynamicNames(off), std::vector<std::string>());
    };
    for (const bool commit : {false, true}) {
        ErrorCollector errors;
        doc1->openTransaction("Move Property");
        throws = 1;
        EXPECT_THROW(
            varSet1Doc1->moveDynamicProperty(varSet1Doc1->getDynamicPropertyByName("Variable"),
                                             varSet2Doc1),
            Base::RuntimeError
        );
        assertOn(varSet2Doc1, varSet1Doc1);
        if (!commit) {
            doc1->abortTransaction();
            assertOn(varSet1Doc1, varSet2Doc1);
            EXPECT_EQ(errors.errors, std::vector<std::string>());
            continue;
        }
        doc1->commitTransaction();
        // the handler throws while undo and redo move the property
        throws = 1;
        EXPECT_TRUE(doc1->undo());
        assertOn(varSet1Doc1, varSet2Doc1);
        throws = 1;
        EXPECT_TRUE(doc1->redo());
        assertOn(varSet2Doc1, varSet1Doc1);
        EXPECT_TRUE(doc1->undo());
        assertOn(varSet1Doc1, varSet2Doc1);
        ASSERT_EQ(errors.errors.size(), 2U);
        for (const auto& error : errors.errors) {
            EXPECT_NE(error.find("handler failed"), std::string::npos) << error;
        }
    }
}

// Tests whether a property added to an object created in the transaction, moved out and back
// and then removed with that object leaves nothing behind (review of fork PR 222: the removed
// object got a transaction entry again, which undo and abort read after it was freed)
TEST_F(MoveProperty, movedBackIntoRemovedCreatedObject)
{
    ErrorCollector errors;
    for (const bool commit : {false, true}) {
        doc1->openTransaction("Move Property");
        auto* source = doc1->addObject("App::VarSet", "Source");
        auto* added = freecad_cast<App::PropertyInteger*>(
            source->addDynamicProperty("App::PropertyInteger", "Extra", "Variables")
        );
        added->setValue(7);
        App::Property* moved = source->moveDynamicProperty(added, varSet2Doc1);
        ASSERT_NE(moved, nullptr);
        ASSERT_NE(varSet2Doc1->moveDynamicProperty(moved, source), nullptr);
        doc1->removeObject(source->getNameInDocument());
        if (commit) {
            doc1->commitTransaction();
            EXPECT_TRUE(doc1->undo());
        }
        else {
            doc1->abortTransaction();
        }
        EXPECT_EQ(doc1->getObject("Source"), nullptr);
        EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>({"Variable"}));
        EXPECT_EQ(dynamicNames(varSet2Doc1), std::vector<std::string>());
        if (commit) {
            EXPECT_TRUE(doc1->redo());
            EXPECT_EQ(doc1->getObject("Source"), nullptr);
            EXPECT_EQ(dynamicNames(varSet2Doc1), std::vector<std::string>());
            EXPECT_TRUE(doc1->undo());
        }
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
}

// Tests whether a property moved into an object created in the transaction, out of an object
// then removed in it, comes back on its object when both are undone (review of fork PR 222: it
// was moved into the source while that was still removed, and ended up there under a temporary
// name with the default value)
TEST_F(MoveProperty, intoCreatedObjectFromRemovedSource)
{
    ErrorCollector errors;
    for (const bool commit : {false, true}) {
        doc1->openTransaction("Move Property");
        auto* target = doc1->addObject("App::VarSet", "Target");
        auto* moved = freecad_cast<App::PropertyInteger*>(
            varSet1Doc1->moveDynamicProperty(varSet1Doc1->getDynamicPropertyByName("Variable"),
                                             target)
        );
        ASSERT_NE(moved, nullptr);
        moved->setValue(9);
        doc1->removeObject(varSet1Doc1->getNameInDocument());
        if (commit) {
            doc1->commitTransaction();
            EXPECT_TRUE(doc1->undo());
        }
        else {
            doc1->abortTransaction();
        }
        EXPECT_EQ(doc1->getObject("Target"), nullptr);
        ASSERT_EQ(doc1->getObject("VarSet"), varSet1Doc1);
        EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>({"Variable"}))
            << (commit ? "undo" : "abort");
        EXPECT_EQ(intValue(varSet1Doc1, "Variable"), value);
        if (commit) {
            EXPECT_TRUE(doc1->redo());
            EXPECT_EQ(doc1->getObject("VarSet"), nullptr);
            auto* redone = doc1->getObject("Target");
            ASSERT_NE(redone, nullptr);
            EXPECT_EQ(dynamicNames(redone), std::vector<std::string>({"Variable"}));
            EXPECT_EQ(intValue(redone, "Variable"), 9);
            EXPECT_TRUE(doc1->undo());
            EXPECT_EQ(doc1->getObject("Target"), nullptr);
            EXPECT_EQ(dynamicNames(varSet1Doc1), std::vector<std::string>({"Variable"}));
            EXPECT_EQ(intValue(varSet1Doc1, "Variable"), value);
        }
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
}

// Tests whether a property added to an object created in the transaction and moved into an
// object then removed in it is gone from that object when both are undone (review of fork PR
// 222: the target came back with it)
TEST_F(MoveProperty, outOfCreatedObjectIntoRemovedTarget)
{
    ErrorCollector errors;
    for (const bool commit : {false, true}) {
        doc1->openTransaction("Move Property");
        auto* source = doc1->addObject("App::VarSet", "Source");
        auto* added = freecad_cast<App::PropertyInteger*>(
            source->addDynamicProperty("App::PropertyInteger", "Extra", "Variables")
        );
        added->setValue(7);
        ASSERT_NE(source->moveDynamicProperty(added, varSet2Doc1), nullptr);
        doc1->removeObject(varSet2Doc1->getNameInDocument());
        if (commit) {
            doc1->commitTransaction();
            EXPECT_TRUE(doc1->undo());
        }
        else {
            doc1->abortTransaction();
        }
        EXPECT_EQ(doc1->getObject("Source"), nullptr);
        ASSERT_EQ(doc1->getObject("VarSet001"), varSet2Doc1);
        EXPECT_EQ(dynamicNames(varSet2Doc1), std::vector<std::string>())
            << (commit ? "undo" : "abort");
        if (commit) {
            EXPECT_TRUE(doc1->redo());
            EXPECT_EQ(doc1->getObject("VarSet001"), nullptr);
            auto* redone = doc1->getObject("Source");
            ASSERT_NE(redone, nullptr);
            EXPECT_EQ(dynamicNames(redone), std::vector<std::string>());
            EXPECT_TRUE(doc1->undo());
            EXPECT_EQ(dynamicNames(varSet2Doc1), std::vector<std::string>());
        }
        for (const auto& name : dynamicNames(varSet2Doc1)) {
            varSet2Doc1->removeDynamicProperty(name.c_str());
        }
    }
    EXPECT_EQ(errors.errors, std::vector<std::string>());
}
