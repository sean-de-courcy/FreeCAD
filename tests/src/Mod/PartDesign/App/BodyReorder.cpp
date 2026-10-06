// SPDX-License-Identifier: LGPL-2.1-or-later

// The reorder's re-target record in the link properties (ops#127,
// notes/reorder-rollback-design.md 3.4 a and 7.3): carried by every solver write-back, by copy
// and paste (undo), and by a setter that passes the shadows on; ended by a setter that doesn't.

#include <gtest/gtest.h>

#include <algorithm>
#include <limits>
#include <sstream>
#include "src/App/InitApplication.h"

#include <App/Application.h>
#include <App/Document.h>
#include <App/ElementRecords.h>
#include <App/ElementRetarget.h>
#include <App/ElementSolverBatch.h>
#include <App/FeatureTest.h>
#include <App/Origin.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <Base/Reader.h>
#include <Base/Writer.h>
#include <Mod/Part/App/Geometry.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureLinearPattern.h>
#include <Mod/PartDesign/App/FeaturePad.h>
#include <Mod/Sketcher/App/SketchObject.h>

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
    std::vector<App::ElementRecords> records(5);
    for (std::size_t i = 0; i < records.size(); ++i) {
        records[i].retarget = record(std::string(1, char('A' + i)));
    }
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
    EXPECT_EQ(records[0].retarget, record("A"));
    EXPECT_EQ(records[1].retarget, record("B"));
    EXPECT_EQ(records[2].retarget, record("B"));
    EXPECT_EQ(records[3].retarget, record("C"));
    EXPECT_EQ(records[4].retarget, record("E"));
}

TEST(RetargetRecord, aRepairEndsItAndEverythingElseKeepsIt)
{
    using Status = App::SolverResolution::Status;
    std::vector<std::string> subs {"Edge1", "Edge2"};
    std::vector<App::PropertyLinkBase::ShadowSub> shadows(subs.size());
    std::vector<std::string> fingerprints(subs.size());
    std::vector<std::string> froms(subs.size());
    std::vector<App::ElementRecords> records(2);
    records[0].retarget = record("A");
    records[1].retarget = record("B");
    std::vector<App::SolverResolution> resolutions(2);
    resolutions[0].status = Status::Resolved;
    resolutions[0].index = 0;
    resolutions[0].sub = "Edge11";
    resolutions[0].clearFrom = true;
    resolutions[0].clearRetarget = true;  // repairReference()
    resolutions[1].status = Status::Resolved;
    resolutions[1].index = 1;
    resolutions[1].sub = "Edge12";
    std::vector<int> firstNew;
    std::vector<int> countNew;
    ASSERT_TRUE(App::rebuildSubList(
        resolutions, subs, shadows, fingerprints, froms, firstNew, countNew, &records));
    ASSERT_EQ(records.size(), 2U);
    EXPECT_TRUE(records[0].retarget.empty());
    EXPECT_EQ(records[1].retarget, record("B"));
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

TEST_F(RetargetRecordProperty, theGuessRecordItCarriesIsSavedAndRestored)
{
    auto& link = _owner->LinkSub;
    link.setValue(_target, {"?Face1"}, shadowsOf(1));
    App::ElementRecords records;
    records.retarget = record("A");
    records.retarget.guess.kind = "rejected";
    records.retarget.guess.origName = "m";
    records.retarget.guess.origIndex = "Face3";
    records.retarget.guess.alternatives = {
        {"Face4", "rejected", std::numeric_limits<double>::quiet_NaN()}};
    link.setElementRecords({records});

    Base::StringWriter writer;
    link.Save(writer);
    EXPECT_NE(writer.getString().find("rtguess=\"rejected\""), std::string::npos);
    std::stringstream data("<?xml version='1.0' encoding='utf-8'?>\n<Property name='LinkSub'>\n"
                           + writer.getString() + "</Property>\n");
    link.setValue(_other, {"Face2"});
    ASSERT_TRUE(link.getRetargets()[0].empty());

    Base::XMLReader reader("Document.xml", data);
    link.Restore(reader);
    EXPECT_EQ(link.getValue(), _target);
    ASSERT_EQ(link.getRetargets().size(), 1U);
    EXPECT_EQ(link.getRetargets()[0], records.retarget);
}

// Body::reorderObject() on a chain of five pads (N1 7.3): P0 a 20 x 20 x 10 block, P1..P4 2 x 2 x 2
// bosses on its top, each pad on its own unattached sketch
class BodyReorderChain: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("reorder");
        _doc = App::GetApplication().newDocument(_docName.c_str(), "testUser");
        _body = _doc->addObject<PartDesign::Body>("Body");
        _pads.push_back(pad("P0", 0, 0, 20, 0, 10));
        for (int i = 1; i <= 4; ++i) {
            _pads.push_back(pad(("P" + std::to_string(i)).c_str(), 4.0 * i - 2, 2, 2, 10, 2));
        }
        _doc->recompute();
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    PartDesign::Pad* pad(const char* name, double x, double y, double size, double z, double height)
    {
        auto sketch =
            _doc->addObject<Sketcher::SketchObject>((std::string(name) + "Sketch").c_str());
        _body->addObject(sketch);
        sketch->Placement.setValue(Base::Placement(Base::Vector3d(0, 0, z), Base::Rotation()));
        const Base::Vector3d corners[] = {Base::Vector3d(x, y, 0),
                                          Base::Vector3d(x + size, y, 0),
                                          Base::Vector3d(x + size, y + size, 0),
                                          Base::Vector3d(x, y + size, 0)};
        for (int i = 0; i < 4; ++i) {
            Part::GeomLineSegment line;
            line.setPoints(corners[i], corners[(i + 1) % 4]);
            sketch->addGeometry(&line, false);
        }
        auto feature = _doc->addObject<PartDesign::Pad>(name);
        _body->addObject(feature);
        feature->Profile.setValue(sketch, {""});
        feature->Length.setValue(height);
        return feature;
    }

    /// The solids in Group order, each on the one before
    void expectChain(const std::vector<App::DocumentObject*>& solids) const
    {
        std::vector<App::DocumentObject*> found;
        for (auto obj : _body->Group.getValues()) {
            if (PartDesign::Body::isSolidFeature(obj)) {
                found.push_back(obj);
            }
        }
        ASSERT_EQ(found, solids);
        App::DocumentObject* previous = nullptr;
        for (auto solid : solids) {
            EXPECT_EQ(static_cast<PartDesign::Feature*>(solid)->BaseFeature.getValue(), previous)
                << solid->getNameInDocument();
            previous = solid;
        }
    }

    PartDesign::Feature* p(int i) const
    {
        return _pads[i];
    }

    static App::DocumentObject* sketchOf(PartDesign::Feature* feature)
    {
        return static_cast<PartDesign::Pad*>(feature)->Profile.getValue();
    }

    // NOLINTBEGIN(cppcoreguidelines-non-private-member-variables-in-classes)
    App::Document* _doc = nullptr;
    std::string _docName;
    PartDesign::Body* _body = nullptr;
    std::vector<PartDesign::Feature*> _pads;
    // NOLINTEND(cppcoreguidelines-non-private-member-variables-in-classes)
};

TEST_F(BodyReorderChain, singleMovesUpDownToTheTopAndToTheEnd)
{
    _body->reorderObject({p(3)}, p(0), true);
    expectChain({p(0), p(3), p(1), p(2), p(4)});
    EXPECT_EQ(_body->Tip.getValue(), p(4));

    // Below the last solid with the bar at the end: the bar stays at the end
    _body->reorderObject({p(3)}, p(4), true);
    expectChain({p(0), p(1), p(2), p(4), p(3)});
    EXPECT_EQ(_body->Tip.getValue(), p(3));

    // To the top: no base
    _body->reorderObject({p(2)}, nullptr, true);
    expectChain({p(2), p(0), p(1), p(4), p(3)});

    // The moved solid carries its sketch
    const auto& group = _body->Group.getValues();
    auto at = [&](App::DocumentObject* obj) {
        return std::find(group.begin(), group.end(), obj) - group.begin();
    };
    EXPECT_EQ(at(sketchOf(p(2))) + 1, at(p(2)));
}

TEST_F(BodyReorderChain, aBlockOfTwo)
{
    _body->reorderObject({p(1), p(2)}, p(4), true);
    expectChain({p(0), p(3), p(4), p(1), p(2)});
    EXPECT_EQ(_body->Tip.getValue(), p(2));
}

TEST_F(BodyReorderChain, theTipKeepsItsPlaceWhenRolledBack)
{
    _body->rollTo(p(2));
    // The Tip moved down: the last unmoved solid before it is the bar
    _body->reorderObject({p(2)}, p(3), true);
    expectChain({p(0), p(1), p(3), p(2), p(4)});
    EXPECT_EQ(_body->Tip.getValue(), p(1));
    EXPECT_TRUE(_body->holds(p(2)));
    // A solid dropped above the bar is active
    _body->reorderObject({p(4)}, p(0), true);
    EXPECT_EQ(_body->Tip.getValue(), p(1));
    EXPECT_FALSE(_body->holds(p(4)));
    EXPECT_TRUE(_body->holds(p(3)));
}

TEST_F(BodyReorderChain, refusedChecksChangeNothing)
{
    auto group = _body->Group.getValues();
    auto stray = _doc->addObject<PartDesign::Pad>("Stray");
    EXPECT_THROW(_body->reorderObject({stray}, p(1), true), Base::ValueError);
    EXPECT_THROW(_body->reorderObject({p(1)}, stray, true), Base::ValueError);
    EXPECT_THROW(_body->reorderObject({p(1)}, p(1), true), Base::ValueError);
    EXPECT_EQ(_body->Group.getValues(), group);
    expectChain({p(0), p(1), p(2), p(3), p(4)});
}

TEST_F(BodyReorderChain, removeObjectsKeepsTheChain)
{
    _body->removeObjects({p(1), p(3)});
    expectChain({p(0), p(2), p(4)});
    EXPECT_EQ(_body->Tip.getValue(), p(4));
}

TEST_F(BodyReorderChain, holdsByTheBar)
{
    _body->rollTo(p(1));
    EXPECT_TRUE(_body->holds(_body));
    EXPECT_FALSE(_body->holds(p(1)));
    EXPECT_TRUE(_body->holds(p(2)));
    // P2's sketch is before the next solid after the bar: live (R2)
    EXPECT_FALSE(_body->holds(sketchOf(p(2))));
    // P3's sketch is after it and only P3 (held) uses it
    EXPECT_TRUE(_body->holds(sketchOf(p(3))));
    // The edit roll-back point is the bar while set
    _body->setEditRollPoint(p(3));
    EXPECT_FALSE(_body->holds(p(2)));
    EXPECT_TRUE(_body->holds(p(4)));
    _body->setEditRollPoint(nullptr);
    _body->rollToEnd();
    EXPECT_FALSE(_body->holds(_body));
}

TEST_F(BodyReorderChain, aBarMoveAloneDoesntTouchTheBody)
{
    ASSERT_FALSE(_body->isTouched());
    _body->rollTo(p(2));
    EXPECT_FALSE(_body->isTouched());
    _body->rollToEnd();
    // The Tip's shape is the one the Body copied: nothing to do (R7)
    EXPECT_FALSE(_body->isTouched());
    EXPECT_FALSE(_doc->mustExecute());
}

TEST_F(BodyReorderChain, parkedOriginalsComeBackByContent)
{
    auto pattern = _doc->addObject<PartDesign::LinearPattern>("Pattern");
    _body->addObject(pattern);
    pattern->Originals.setValues({p(3), p(4)});
    pattern->Direction.setValue(_body->getOrigin()->getY(), {""});
    pattern->Length.setValue(6.0);
    pattern->Occurrences.setValue(2);
    _body->Tip.setValue(pattern);
    _doc->recompute();
    ASSERT_TRUE(pattern->isValid());

    // Above both originals: both parked on the pattern, which is still a solid of the chain
    _body->reorderObject({pattern}, p(2), true);
    EXPECT_TRUE(pattern->Originals.getValues().empty());
    auto parked =
        dynamic_cast<App::PropertyStringList*>(pattern->getPropertyByName("ParkedReferences"));
    ASSERT_NE(parked, nullptr);
    EXPECT_EQ(parked->getValues().size(), 2U);
    expectChain({p(0), p(1), p(2), pattern, p(3), p(4)});
    _doc->recompute();
    EXPECT_TRUE(pattern->isError());

    // A third original added meanwhile; moved back, all three are there, each once
    pattern->Originals.setValues({p(1)});
    _body->reorderObject({pattern}, p(4), true);
    auto originals = pattern->Originals.getValues();
    std::sort(originals.begin(), originals.end());
    std::vector<App::DocumentObject*> expected {p(1), p(3), p(4)};
    std::sort(expected.begin(), expected.end());
    EXPECT_EQ(originals, expected);
    EXPECT_EQ(pattern->getPropertyByName("ParkedReferences"), nullptr);
    expectChain({p(0), p(1), p(2), p(3), p(4), pattern});
    _doc->recompute();
    EXPECT_TRUE(pattern->isValid());
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
