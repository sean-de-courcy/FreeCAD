// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <App/Application.h>
#include <App/ElementMap.h>
#include <src/App/InitApplication.h>

// NOLINTBEGIN(readability-magic-numbers)


class ElementNamingUtilsTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("test");
        App::GetApplication().newDocument(_docName.c_str(), "testUser");
        _sids = &_sid;
        _hasher = Base::Reference<App::StringHasher>(new App::StringHasher);
        ASSERT_EQ(_hasher.getRefCount(), 1);
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    std::string _docName;
    Data::ElementIDRefs _sid;
    QVector<App::StringIDRef>* _sids;
    App::StringHasherRef _hasher;
};

TEST_F(ElementNamingUtilsTest, findElementName)
{
    // Act
    Data::ElementMap elementMap = Data::ElementMap();
    auto name1 = Data::findElementName("Edge1");
    auto name2 = Data::findElementName(
        ";g5v2;SKT;:Had6,V;:G;OFS;:Had6:7,V;:G;OFS;:Had6:7,V;WIR;:"
        "Had6:4,V;:G;XTR;:Had6:7,E;:H,E.Face1.Edge2"
    );
    auto name3 = Data::findElementName("An.Example.Assembly.Edge3");
    auto name4 = Data::findElementName(".Edge4");

    // Assert
    EXPECT_STREQ(name1, "Edge1");
    EXPECT_STREQ(
        name2,
        ";g5v2;SKT;:Had6,V;:G;OFS;:Had6:7,V;:G;OFS;:Had6:7,V;WIR;:"
        "Had6:4,V;:G;XTR;:Had6:7,E;:H,E.Face1.Edge2"
    );
    EXPECT_STREQ(name3, "Edge3");
    EXPECT_STREQ(name4, "Edge4");
}

TEST_F(ElementNamingUtilsTest, isRoleValue)
{
    // The roles are the named set (ops#468, naming-class-A.md 4.1), tested by value
    EXPECT_TRUE(Data::isRoleValue(Data::ROLE_CROSSING_IN));
    EXPECT_TRUE(Data::isRoleValue(Data::ROLE_CROSSING_OUT));
    EXPECT_TRUE(Data::isRoleValue("in"));
    EXPECT_TRUE(Data::isRoleValue("out"));

    // Never a counter, a twin place, a pattern instance's number, or another word
    EXPECT_FALSE(Data::isRoleValue("0"));
    EXPECT_FALSE(Data::isRoleValue("1"));
    EXPECT_FALSE(Data::isRoleValue("0of2"));
    EXPECT_FALSE(Data::isRoleValue("in0of2"));
    EXPECT_FALSE(Data::isRoleValue("_"));
    EXPECT_FALSE(Data::isRoleValue(""));
    EXPECT_FALSE(Data::isRoleValue("IN"));
    EXPECT_FALSE(Data::isRoleValue("inside"));
}

TEST_F(ElementNamingUtilsTest, indexOfElement)
{
    // Valid cases
    EXPECT_EQ(Data::indexOfElement("Edge1", "Edge"), 1);
    EXPECT_EQ(Data::indexOfElement("Edge12", "Edge"), 12);
    EXPECT_EQ(Data::indexOfElement("Edge999", "Edge"), 999);

    // Prefix mismatch
    EXPECT_EQ(Data::indexOfElement("Node5", "Edge"), 0);

    // Missing numeric suffix
    EXPECT_EQ(Data::indexOfElement("Edge", "Edge"), 0);

    // Non-numeric suffix
    EXPECT_EQ(Data::indexOfElement("EdgeX", "Edge"), 0);
    EXPECT_EQ(Data::indexOfElement("Edge12X", "Edge"), 0);

    // Zero or invalid index
    EXPECT_EQ(Data::indexOfElement("Edge0", "Edge"), 0);

    // Degenerate inputs
    EXPECT_EQ(Data::indexOfElement("", "Edge"), 0);
    EXPECT_EQ(Data::indexOfElement("123", ""), 0);
}
// NOLINTEND(readability-magic-numbers)
