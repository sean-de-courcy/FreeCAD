// SPDX-License-Identifier: LGPL-2.1-or-later

// The reorder's re-target record in the link properties (ops#127,
// notes/reorder-rollback-design.md 3.4 a and 7.3): carried by every solver write-back, by copy
// and paste (undo), and by a setter that passes the shadows on; ended by a setter that doesn't.

#include <gtest/gtest.h>
#include "src/App/InitApplication.h"

#include <App/Application.h>
#include <App/Document.h>
#include <App/ElementRetarget.h>
#include <App/ElementSolverBatch.h>
#include <App/FeatureTest.h>
#include <App/PropertyLinks.h>

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

namespace
{
App::RetargetRecord record(const std::string& index)
{
    return App::RetargetRecord::fromAttributes("Pad001", ";g3;SKT;:H1:7,E." + index, "fp" + index);
}
}  // namespace

TEST(RetargetRecord, attributesRoundTrip)
{
    // A mapped name may hold commas; the index after the last one is the original's
    auto r = App::RetargetRecord::fromAttributes("Pad001", ";g3;SKT;:H1:7,E,Face6", "abc");
    EXPECT_EQ(r.target, "Pad001");
    EXPECT_EQ(r.origName, ";g3;SKT;:H1:7,E");
    EXPECT_EQ(r.origIndex, "Face6");
    EXPECT_EQ(r.origFp, "abc");
    EXPECT_EQ(App::RetargetRecord::fromAttributes(r.target, r.origText(), r.origFp), r);
    EXPECT_TRUE(App::RetargetRecord::fromAttributes("", "x,Face1", "").empty());
}

TEST(RetargetRecord, rebuildSubListCarriesTheRecordThroughEveryResolution)
{
    using Status = App::SolverResolution::Status;
    std::vector<std::string> subs {"Edge1", "Edge2", "Edge3", "Edge4", "Edge5"};
    std::vector<App::PropertyLinkBase::ShadowSub> shadows(subs.size());
    std::vector<std::string> fingerprints(subs.size());
    std::vector<std::string> froms(subs.size());
    std::vector<App::RetargetRecord> records {record("A"),
                                              record("B"),
                                              record("C"),
                                              record("D"),
                                              record("E")};
    std::vector<App::SolverResolution> resolutions(4);
    resolutions[0].status = Status::Resolved;
    resolutions[0].index = 0;
    resolutions[0].sub = "Edge11";
    resolutions[1].status = Status::Expanded;
    resolutions[1].index = 1;
    resolutions[1].pieces = {{"Edge12", {}}, {"Edge13", {}}};
    resolutions[1].from = "Edge2";
    resolutions[2].status = Status::Broken;
    resolutions[2].index = 2;
    resolutions[2].sub = "?Edge3";
    resolutions[3].status = Status::Removed;
    resolutions[3].index = 3;
    std::vector<int> firstNew;
    std::vector<int> countNew;
    ASSERT_TRUE(App::rebuildSubList(
        resolutions, subs, shadows, fingerprints, froms, firstNew, countNew, &records));
    ASSERT_EQ(subs, (std::vector<std::string> {"Edge11", "Edge12", "Edge13", "?Edge3", "Edge5"}));
    ASSERT_EQ(records.size(), 5U);
    EXPECT_EQ(records[0], record("A"));
    EXPECT_EQ(records[1], record("B"));
    EXPECT_EQ(records[2], record("B"));
    EXPECT_EQ(records[3], record("C"));
    EXPECT_EQ(records[4], record("E"));
}

class RetargetRecordProperty: public ::testing::Test
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
        _owner = _doc->addObject<App::FeatureTest>("Owner");
        _target = _doc->addObject<App::FeatureTest>("Target");
        _other = _doc->addObject<App::FeatureTest>("Other");
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    static std::vector<App::PropertyLinkBase::ShadowSub> shadowsOf(std::size_t count)
    {
        std::vector<App::PropertyLinkBase::ShadowSub> shadows;
        for (std::size_t i = 0; i < count; ++i) {
            shadows.emplace_back(";mapped" + std::to_string(i) + ".Face1", "?Face1");
        }
        return shadows;
    }

    // NOLINTBEGIN(cppcoreguidelines-non-private-member-variables-in-classes)
    App::Document* _doc = nullptr;
    std::string _docName;
    App::FeatureTest* _owner = nullptr;
    App::FeatureTest* _target = nullptr;
    App::FeatureTest* _other = nullptr;
    // NOLINTEND(cppcoreguidelines-non-private-member-variables-in-classes)
};

TEST_F(RetargetRecordProperty, linkSubKeepsItWithShadowsAndEndsItOnARepick)
{
    auto& link = _owner->LinkSub;
    link.setValue(_target, {"?Face1", "?Face1"}, shadowsOf(2));
    link.setRetargets({record("A"), record("B")});
    ASSERT_EQ(link.getRetargets().size(), 2U);

    // Passed on with the shadows (the re-target, a restore): kept
    link.setValue(_other, {"?Face1", "?Face1"}, shadowsOf(2));
    EXPECT_EQ(link.getRetargets()[1], record("B"));

    // Copy and paste (undo) bring it back
    std::unique_ptr<App::Property> copy(link.Copy());
    link.setValue(_target, {"Face2"});
    EXPECT_TRUE(link.getRetargets()[0].empty());
    link.Paste(*copy);
    EXPECT_EQ(link.getRetargets()[0], record("A"));
    EXPECT_EQ(link.getValue(), _other);

    // A re-pick (no shadows) ends it
    link.setValue(_other, {"Face3", "Face4"});
    ASSERT_EQ(link.getRetargets().size(), 2U);
    EXPECT_TRUE(link.getRetargets()[0].empty());
    EXPECT_TRUE(link.getRetargets()[1].empty());
}

TEST_F(RetargetRecordProperty, linkSubListKeepsItWithShadowsAndEndsItOnARepick)
{
    auto& link = _owner->LinkSubList;
    link.setValues({_target, _other}, {"?Face1", "?Face1"}, shadowsOf(2));
    link.setRetargets({record("A"), {}});
    link.setElementFingerprint(0, "original");
    EXPECT_EQ(link.getElementFingerprints()[0], "original");

    std::unique_ptr<App::Property> copy(link.Copy());
    link.setValues({_other}, std::vector<std::string> {"Face2"});
    EXPECT_TRUE(link.getRetargets().empty() || link.getRetargets()[0].empty());
    link.Paste(*copy);
    ASSERT_EQ(link.getRetargets().size(), 2U);
    EXPECT_EQ(link.getRetargets()[0], record("A"));
    EXPECT_EQ(link.getElementFingerprints()[0], "original");

    link.setValue(_target, std::vector<std::string> {"Face5"});
    EXPECT_TRUE(link.getRetargets().empty() || link.getRetargets()[0].empty());
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
