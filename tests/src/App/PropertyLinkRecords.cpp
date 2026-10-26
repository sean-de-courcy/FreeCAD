// SPDX-License-Identifier: LGPL-2.1-or-later

// A rewrite keeps the records and fingerprints of the references it keeps, paired by value
// (FreeCAD-CH, ops#504 E2, invariant I-S10): the C++-only setters (addValue(), removeValue()).
// The Python setters, the element forms (mapped, index, missing) and the solver's records are
// tested in PartDesignTests/TestNamingRewrite.py.

#include <gtest/gtest.h>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ElementRecords.h>
#include <App/PropertyLinks.h>

#include <src/App/InitApplication.h>

class PropertyLinkRecords: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("test");
        _doc = App::GetApplication().newDocument(_docName.c_str(), "testUser");
        _a = _doc->addObject("App::FeatureTest", "A");
        _b = _doc->addObject("App::FeatureTest", "B");
        _owner = _doc->addObject("App::FeatureTest", "Owner");
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    template<class T>
    T* addLinks(const char* name)
    {
        return freecad_cast<T*>(_owner->addDynamicProperty(T::getClassTypeId().getName(), name));
    }

    // A guess record that names its original
    static App::ElementRecords guessed(const char* original)
    {
        App::ElementRecords records;
        records.guess.kind = "tier3";
        records.guess.origIndex = original;
        return records;
    }

    std::string _docName;
    App::Document* _doc {};
    App::DocumentObject* _a {};
    App::DocumentObject* _b {};
    App::DocumentObject* _owner {};
};

TEST_F(PropertyLinkRecords, linkSubListAddValueKeepsTheRecords)
{
    // Arrange
    auto prop = addLinks<App::PropertyLinkSubList>("Links");
    prop->setValue(_a, std::vector<std::string> {"Sub."});
    prop->setElementRecords({guessed("A")});
    prop->setElementFingerprint(0, "fp-a");

    // Act
    prop->addValue(_b, {"Sub."});

    // Assert
    auto records = prop->getElementRecords();
    ASSERT_EQ(records.size(), 2);
    EXPECT_EQ(records[0], guessed("A"));
    EXPECT_TRUE(records[1].empty());
    auto fingerprints = prop->getElementFingerprints();
    EXPECT_EQ(fingerprints[0], "fp-a");
    EXPECT_EQ(fingerprints[1], "");
}

TEST_F(PropertyLinkRecords, linkSubListAddValueWithResetKeepsTheOthers)
{
    // Arrange
    auto prop = addLinks<App::PropertyLinkSubList>("Links");
    prop->setValues(std::vector<App::DocumentObject*> {_a, _b},
                    std::vector<std::string> {"Sub.", "Sub."});
    prop->setElementRecords({guessed("A"), guessed("B")});

    // Act: a's entries chosen anew, b's kept
    prop->addValue(_a, {"Other."}, true);

    // Assert
    ASSERT_EQ(prop->getValues(), (std::vector<App::DocumentObject*> {_b, _a}));
    auto records = prop->getElementRecords();
    EXPECT_EQ(records[0], guessed("B"));
    EXPECT_TRUE(records[1].empty());
}

TEST_F(PropertyLinkRecords, linkSubListRemoveValueKeepsTheOthers)
{
    // Arrange
    auto prop = addLinks<App::PropertyLinkSubList>("Links");
    prop->setValues(std::vector<App::DocumentObject*> {_a, _b},
                    std::vector<std::string> {"Sub.", "Sub."});
    prop->setElementRecords({guessed("A"), guessed("B")});
    prop->setElementFingerprint(1, "fp-b");

    // Act
    prop->removeValue(_a);

    // Assert
    auto records = prop->getElementRecords();
    ASSERT_EQ(records.size(), 1);
    EXPECT_EQ(records[0], guessed("B"));
    EXPECT_EQ(prop->getElementFingerprints()[0], "fp-b");
}

TEST_F(PropertyLinkRecords, linkSubListReorderPairsByValueNotPosition)
{
    // Arrange
    auto prop = addLinks<App::PropertyLinkSubList>("Links");
    prop->setValues(std::vector<App::DocumentObject*> {_a, _b},
                    std::vector<std::string> {"Sub.", "Sub."});
    prop->setElementRecords({guessed("A"), guessed("B")});

    // Act
    prop->setValues(std::vector<App::DocumentObject*> {_b, _a},
                    std::vector<std::string> {"Sub.", "Sub."});

    // Assert
    auto records = prop->getElementRecords();
    EXPECT_EQ(records[0], guessed("B"));
    EXPECT_EQ(records[1], guessed("A"));
}

TEST_F(PropertyLinkRecords, linkSubSetValueKeepsTheRecords)
{
    // Arrange
    auto prop = addLinks<App::PropertyLinkSub>("Link");
    prop->setValue(_a, std::vector<std::string> {"Sub."});
    prop->setElementRecords({guessed("A")});
    prop->setElementFingerprint(0, "fp-a");

    // Act
    prop->setValue(_a, std::vector<std::string> {"Other.", "Sub."});

    // Assert
    auto records = prop->getElementRecords();
    EXPECT_TRUE(records[0].empty());
    EXPECT_EQ(records[1], guessed("A"));
    EXPECT_EQ(prop->getElementFingerprints()[1], "fp-a");
}

TEST_F(PropertyLinkRecords, linkSubAnotherObjectKeepsNoRecord)
{
    // Arrange
    auto prop = addLinks<App::PropertyLinkSub>("Link");
    prop->setValue(_a, std::vector<std::string> {"Sub."});
    prop->setElementRecords({guessed("A")});

    // Act
    prop->setValue(_b, std::vector<std::string> {"Sub."});

    // Assert
    EXPECT_TRUE(prop->getElementRecords()[0].empty());
}

TEST_F(PropertyLinkRecords, xLinkSubListAddValueKeepsTheRecords)
{
    // Arrange
    auto prop = addLinks<App::PropertyXLinkSubList>("XLinks");
    prop->addValue(_a, std::vector<std::string> {"Sub."});
    prop->editLink(0, [](App::PropertyXLinkSub& link) {
        link.setElementRecords({guessed("A")});
        link.setElementFingerprint(0, "fp-a");
    });

    // Act: another sub of the same object, then another object
    prop->addValue(_a, std::vector<std::string> {"Other."});
    prop->addValue(_b, std::vector<std::string> {"Sub."});

    // Assert
    const auto& links = prop->getSubListValues();
    ASSERT_EQ(links.size(), 2);
    const auto& link = links.front();
    ASSERT_EQ(link.getSubValues(), (std::vector<std::string> {"Sub.", "Other."}));
    auto records = link.getElementRecords();
    EXPECT_EQ(records[0], guessed("A"));
    EXPECT_TRUE(records[1].empty());
    EXPECT_EQ(link.getElementFingerprints()[0], "fp-a");
    EXPECT_TRUE(links.back().getElementRecords()[0].empty());
}

TEST_F(PropertyLinkRecords, xLinkSetValueToAnotherObjectKeepsNoRecord)
{
    // Arrange
    auto prop = addLinks<App::PropertyXLinkSub>("XLink");
    prop->setValue(_a, std::vector<std::string> {"Sub."});
    prop->setElementRecords({guessed("A")});

    // Act
    prop->setValue(_b, std::vector<std::string> {"Sub."});

    // Assert
    EXPECT_TRUE(prop->getElementRecords()[0].empty());
}

TEST_F(PropertyLinkRecords, shadowsPassedOnKeepTheirReferencesRecords)
{
    // Arrange: a's entry passed on with its shadow (as the Sketcher's setExternalLinks() does),
    // with an entry added before it
    auto prop = addLinks<App::PropertyLinkSubList>("Links");
    prop->setValue(_a, std::vector<std::string> {"Sub."});
    prop->setElementRecords({guessed("A")});
    auto shadow = prop->getShadowSubs()[0];

    // Act
    prop->setValues(std::vector<App::DocumentObject*> {_b, _a},
                    std::vector<std::string> {"Sub.", "Sub."},
                    std::vector<App::PropertyLinkBase::ShadowSub> {{}, shadow});

    // Assert
    auto records = prop->getElementRecords();
    EXPECT_TRUE(records[0].empty());
    EXPECT_EQ(records[1], guessed("A"));
}
