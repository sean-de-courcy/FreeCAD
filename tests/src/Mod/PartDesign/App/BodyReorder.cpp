// SPDX-License-Identifier: LGPL-2.1-or-later

// The reorder's re-target record in the link properties (ops#127,
// notes/reorder-rollback-design.md 3.4 a and 7.3): carried by every solver write-back, by copy
// and paste (undo), and by a setter that passes the shadows on; ended by a setter that doesn't.

#include <gtest/gtest.h>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <limits>
#include <sstream>
#include "src/App/InitApplication.h"

#include <App/Application.h>
#include <App/Document.h>
#include <App/ElementFingerprint.h>
#include <App/ElementRecords.h>
#include <App/ElementRetarget.h>
#include <App/ElementSolverBatch.h>
#include <App/FeatureTest.h>
#include <App/Origin.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <Base/FileInfo.h>
#include <Base/Reader.h>
#include <Base/Writer.h>
#include <Mod/Part/App/Geometry.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureLinearPattern.h>
#include <Mod/PartDesign/App/FeaturePad.h>
#include <Mod/PartDesign/App/ShapeBinder.h>
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
    records.retarget.guess.origFingerprint = "ofp3";  // the snap-back's (ops#133)
    link.setElementRecords({records});

    Base::StringWriter writer;
    link.Save(writer);
    EXPECT_NE(writer.getString().find("rtguess=\"rejected\""), std::string::npos);
    EXPECT_NE(writer.getString().find("rtofp=\"ofp3\""), std::string::npos);
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

    PartDesign::Pad* pad(const char* name,
                         double x,
                         double y,
                         double size,
                         double z,
                         double height,
                         PartDesign::Body* body = nullptr)
    {
        body = body ? body : _body;
        auto sketch =
            _doc->addObject<Sketcher::SketchObject>((std::string(name) + "Sketch").c_str());
        body->addObject(sketch);
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
        body->addObject(feature);
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

TEST_F(BodyReorderChain, aParkedGuessRecordKeepsItsOriginalFingerprint)
{
    auto pattern = _doc->addObject<PartDesign::LinearPattern>("Pattern");
    _body->addObject(pattern);
    pattern->Originals.setValues({p(3)});
    // Along the block's front bottom edge (x): the copy sits on the top face. Along Edge1, the
    // block's vertical edge, it floated above the part, and a copy that touches nothing of the
    // part is dropped since Onshape's pattern rules (7756c9901e), the pattern failing (ops#652)
    std::string alongX;
    const auto& shape = p(4)->Shape.getShape();
    for (unsigned long i = 1; i <= shape.countSubShapes(TopAbs_EDGE) && alongX.empty(); ++i) {
        const auto name = "Edge" + std::to_string(i);
        const auto box = shape.getSubTopoShape(name.c_str()).getBoundBox();
        if (box.MaxX - box.MinX > 1 && std::abs(box.MaxY - box.MinY) < 1e-6
            && std::abs(box.MaxZ - box.MinZ) < 1e-6 && std::abs(box.MinY) < 1e-6
            && std::abs(box.MinZ) < 1e-6) {
            alongX = name;
        }
    }
    ASSERT_FALSE(alongX.empty());
    pattern->Direction.setValue(p(4), {alongX});
    pattern->Length.setValue(6.0);
    pattern->Occurrences.setValue(2);
    _body->Tip.setValue(pattern);
    _doc->recompute();
    ASSERT_TRUE(pattern->isValid());
    // A provisional pick's record on the direction, with the original's fingerprint (ops#133)
    App::ElementRecords records;
    records.guess.kind = "piece";
    records.guess.origName = "m";
    records.guess.origIndex = "Edge3";
    records.guess.origFingerprint = "ofp3";
    pattern->Direction.setElementRecords({records});

    auto directionLine = [&]() -> std::string {
        auto parked =
            dynamic_cast<App::PropertyStringList*>(pattern->getPropertyByName("ParkedReferences"));
        if (!parked) {
            return {};
        }
        for (const auto& line : parked->getValues()) {
            if (line.rfind("link|Direction|", 0) == 0) {
                return line;
            }
        }
        return {};
    };
    auto parkedGuess = [&]() {
        auto held = pattern->Direction.getElementRecords();
        return held.empty() ? App::GuessRecord() : held.front().guess;
    };

    // To the top, no base: the direction is parked, the fingerprint in a twelfth field
    _body->reorderObject({pattern}, nullptr, true);
    auto line = directionLine();
    EXPECT_EQ(std::count(line.begin(), line.end(), '|'), 11) << line;
    EXPECT_EQ(line.substr(line.rfind('|') + 1), "ofp3");

    // Back to the end: put back with the record whole
    _body->reorderObject({pattern}, p(4), true);
    EXPECT_EQ(pattern->getPropertyByName("ParkedReferences"), nullptr);
    EXPECT_EQ(pattern->Direction.getValue(), p(4));
    EXPECT_EQ(parkedGuess(), records.guess);

    // A line parked before ops#133 has eleven fields: put back without the fingerprint
    _body->reorderObject({pattern}, nullptr, true);
    line = directionLine();
    ASSERT_EQ(std::count(line.begin(), line.end(), '|'), 11) << line;
    auto parked =
        static_cast<App::PropertyStringList*>(pattern->getPropertyByName("ParkedReferences"));
    auto lines = parked->getValues();
    std::replace(lines.begin(), lines.end(), line, line.substr(0, line.rfind('|')));
    parked->setValues(lines);
    _body->reorderObject({pattern}, p(4), true);
    EXPECT_EQ(pattern->Direction.getValue(), p(4));
    auto old = records.guess;
    old.origFingerprint.clear();
    EXPECT_EQ(parkedGuess(), old);
}

// A reference's record while its target is still to be recomputed (ops#564): on the chain of
// BodyReorderChain, a holder outside the Body on the Body's own edge, (Body, "EdgeN"), the form a
// joint or an outside datum uses. The edge is P0's front bottom edge, which no boss touches.
class RecordRefreshChain: public BodyReorderChain
{
protected:
    /// The holder of (Body, the front bottom edge), its record taken by a recompute
    App::FeatureTest* holder()
    {
        auto holder = _doc->addObject<App::FeatureTest>("Holder");
        holder->LinkSub.setValue(_body, {frontBottomEdge()});
        _doc->recompute();
        return holder;
    }

    std::string frontBottomEdge(const Part::Feature* feature = nullptr) const
    {
        const auto& shape = (feature ? feature : _body)->Shape.getShape();
        for (unsigned long i = 1; i <= shape.countSubShapes(TopAbs_EDGE); ++i) {
            const auto name = "Edge" + std::to_string(i);
            const auto box = shape.getSubTopoShape(name.c_str()).getBoundBox();
            if (std::abs(box.MinX) < 1e-6 && std::abs(box.MaxX - 20) < 1e-6
                && std::abs(box.MaxY - box.MinY) < 1e-6 && std::abs(box.MinY) < 1e-6
                && std::abs(box.MaxZ - box.MinZ) < 1e-6 && std::abs(box.MinZ) < 1e-6) {
                return name;
            }
        }
        return {};
    }

    static std::string record(App::FeatureTest* holder)
    {
        const auto& records = holder->LinkSub.getElementFingerprints();
        return records.empty() ? std::string() : records[0];
    }

    /// The mark the record holds for \a obj; -2 if none
    static long markOf(const std::string& record, const App::DocumentObject* obj)
    {
        for (const auto& mark : Data::ElementFingerprint::fromString(record).marks) {
            if (mark.tag == obj->getID()) {
                return mark.mark;
            }
        }
        return -2;
    }

    /// Pi's square deleted and drawn again the other way round at the same place: new geometry
    /// IDs, the sketch touched
    void redrawBoss(int i)
    {
        auto sketch = static_cast<Sketcher::SketchObject*>(sketchOf(p(i)));
        const double x = 4.0 * i - 2;
        const double y = 2;
        const double size = 2;
        const Base::Vector3d corners[] = {Base::Vector3d(x, y + size, 0),
                                          Base::Vector3d(x + size, y + size, 0),
                                          Base::Vector3d(x + size, y, 0),
                                          Base::Vector3d(x, y, 0)};
        sketch->deleteAllGeometry();
        for (int k = 0; k < 4; ++k) {
            Part::GeomLineSegment line;
            line.setPoints(corners[k], corners[(k + 1) % 4]);
            sketch->addGeometry(&line, false);
        }
    }
};

TEST_F(RecordRefreshChain, aSetterBeforeTheRecomputeKeepsTheRecord)
{
    // Arrange
    auto link = holder();
    const auto before = record(link);
    ASSERT_FALSE(before.empty());
    const auto mark = markOf(before, sketchOf(p(4)));
    ASSERT_GE(mark, 0);

    // Act: the redraw, and the reference set again before the recompute (a dialog's OK)
    redrawBoss(4);
    link->LinkSub.setValue(_body, link->LinkSub.getSubValues());

    // Assert: the Body isn't made again yet, so its record stays as the solve will need it
    EXPECT_EQ(record(link), before);
    //   and the recompute takes it again, the redraw included
    _doc->recompute();
    EXPECT_GT(markOf(record(link), sketchOf(p(4))), mark);
}

TEST_F(RecordRefreshChain, theTargetsRecomputeTakesTheRecordOnlyAtItsEnd)
{
    // Arrange
    auto link = holder();
    const auto before = record(link);
    std::string afterTheBody;
    fastsignals::scoped_connection connection =
        _doc->signalRecomputedObject.connect([&](const App::DocumentObject& obj) {
            if (&obj == _body) {
                afterTheBody = record(link);
            }
        });

    // Act
    redrawBoss(4);
    _doc->recompute();

    // Assert: while the Body was made again (still touched) the record was held, and the end of
    // the recompute took it
    EXPECT_EQ(afterTheBody, before);
    EXPECT_GT(markOf(record(link), sketchOf(p(4))), markOf(before, sketchOf(p(4))));
}

TEST_F(RecordRefreshChain, aReferenceIntoAnObjectLeftUnmadeTakesItsRecordAtTheEnd)
{
    // Arrange
    auto link = holder();
    const auto before = record(link);
    const auto mark = markOf(before, sketchOf(p(4)));
    ASSERT_GE(mark, 0);

    // Act: P4's square drawn again, and P0, the Body's first solid feature, failing in the same
    // edit (length zero)
    redrawBoss(4);
    static_cast<PartDesign::Pad*>(p(0))->Length.setValue(0.0);
    _doc->recompute();

    // Assert: the Body isn't made (it doesn't continue past its failed base), and the record of
    // the reference into it is taken at the end all the same, the redraw included (ops#579,
    // decision 256): a line slid later onto a place one was removed from breaks, as it does
    // without the failure
    EXPECT_TRUE(p(0)->isError());
    EXPECT_TRUE(_body->isError());
    EXPECT_GT(markOf(record(link), sketchOf(p(4))), mark);
}

TEST_F(RecordRefreshChain, aFeatureFailingAloneTakesTheRecordsIntoIt)
{
    // Arrange: a holder of P0's own front bottom edge
    auto link = _doc->addObject<App::FeatureTest>("Holder");
    link->LinkSub.setValue(p(0), {frontBottomEdge(p(0))});
    _doc->recompute();
    const auto before = record(link);
    auto sketch = static_cast<Sketcher::SketchObject*>(sketchOf(p(0)));
    const auto mark = markOf(before, sketch);
    ASSERT_GE(mark, 0);

    // Act: a line drawn in P0's sketch, P0 failing (length zero), and P0 recomputed alone
    Part::GeomLineSegment line;
    line.setPoints(Base::Vector3d(30, 30, 0), Base::Vector3d(35, 30, 0));
    sketch->addGeometry(&line, false);
    static_cast<PartDesign::Pad*>(p(0))->Length.setValue(0.0);
    _doc->recomputeFeature(p(0));

    // Assert: P0 didn't make its shape, and the record into it is taken (decision 256)
    EXPECT_TRUE(p(0)->isError());
    EXPECT_GT(markOf(record(link), sketch), mark);
}

TEST_F(RecordRefreshChain, anObjectLeftTouchedDoesntHoldTheRecordPastTheRecompute)
{
    // Arrange: a second Body, rolled back after Q0, its Q1 changed and held by the bar (left
    // touched), and a binder of it in the chain's Body: in the closure of every record into it
    auto other = _doc->addObject<PartDesign::Body>("Other");
    auto q0 = pad("Q0", 40, 0, 10, 0, 10, other);
    auto q1 = pad("Q1", 42, 2, 2, 10, 2, other);
    _doc->recompute();
    other->rollTo(q0);
    auto binder = _doc->addObject<PartDesign::ShapeBinder>("Binder");
    _body->addObject(binder);
    binder->Support.setValue(other);
    _doc->recompute();
    auto link = holder();
    const auto before = record(link);
    ASSERT_GE(markOf(before, q1), -1);
    q1->Length.setValue(3.0);

    // Act: P4's boss redrawn and the document recomputed
    redrawBoss(4);
    _doc->recompute();

    // Assert: Q1 is still touched, but the chain's Body was made again: its record is taken
    // again, the redraw in it (a record kept would date what is drawn since as drawn again,
    // review prd2dopus-r3 R3-1)
    EXPECT_TRUE(other->holds(q1));
    EXPECT_TRUE(q1->isTouched());
    EXPECT_FALSE(_body->isTouched());
    EXPECT_GT(markOf(record(link), sketchOf(p(4))), markOf(before, sketchOf(p(4))));
}

TEST_F(RecordRefreshChain, aPartialRecomputeWithoutTheTargetKeepsTheRecordHeld)
{
    // Arrange: the redraw and the reference set again, held (review pr564opus-r1 T3)
    auto link = holder();
    const auto before = record(link);
    auto spare = _doc->addObject<App::FeatureTest>("Spare");
    redrawBoss(4);
    link->LinkSub.setValue(_body, link->LinkSub.getSubValues());

    // Act: a recompute of another object only
    _doc->recompute({spare});

    // Assert: P4's sketch wasn't in it and is still to be recomputed, so the record is still held
    EXPECT_TRUE(sketchOf(p(4))->isTouched());
    EXPECT_EQ(record(link), before);
    //   and the document's recompute takes it, the redraw included
    _doc->recompute();
    EXPECT_GT(markOf(record(link), sketchOf(p(4))), markOf(before, sketchOf(p(4))));
}

TEST_F(RecordRefreshChain, aFeatureRecomputedAloneTakesTheHeldRecord)
{
    // Arrange: the redraw and the reference set again, held
    auto link = holder();
    const auto before = record(link);
    redrawBoss(4);
    link->LinkSub.setValue(_body, link->LinkSub.getSubValues());
    ASSERT_EQ(record(link), before);

    // Act: the sketch recomputed alone (obj.recompute(), a task dialog's preview), which leaves
    // it touched
    _doc->recomputeFeature(sketchOf(p(4)), false);

    // Assert: the gating can't tell what is still to come there, so the record is taken (review
    // pr564opus-r1 T2: a record held past it would date a sibling dragged onto the place as drawn
    // again)
    EXPECT_TRUE(sketchOf(p(4))->isTouched());
    EXPECT_GT(markOf(record(link), sketchOf(p(4))), markOf(before, sketchOf(p(4))));
}

TEST_F(RecordRefreshChain, aFeatureRecomputedOutsideTheClosureKeepsTheRecordHeld)
{
    // Arrange: the redraw and the reference set again, held
    auto link = holder();
    const auto before = record(link);
    auto spare = _doc->addObject<App::FeatureTest>("Spare");
    redrawBoss(4);
    link->LinkSub.setValue(_body, link->LinkSub.getSubValues());
    ASSERT_EQ(record(link), before);

    // Act: another object recomputed alone (a task dialog's preview of an unrelated feature)
    _doc->recomputeFeature(spare, false);

    // Assert: the Body isn't made yet, so the record is still held (review pr564opus-r2 R2-1)
    EXPECT_EQ(record(link), before);
    //   and the document's recompute takes it, the redraw included
    _doc->recompute();
    EXPECT_GT(markOf(record(link), sketchOf(p(4))), markOf(before, sketchOf(p(4))));
}

TEST_F(RecordRefreshChain, aTargetLeftTouchedByTheRecomputeDoesntHoldTheRecordPastIt)
{
    // Arrange: a holder of P4's front bottom edge, the Body rolled back to P3
    auto link = _doc->addObject<App::FeatureTest>("Holder");
    link->LinkSub.setValue(p(4), {frontBottomEdge(p(4))});
    _doc->recompute();
    _body->rollTo(p(3));
    _doc->recompute();
    const auto before = record(link);
    ASSERT_GE(markOf(before, sketchOf(p(4))), 0);

    // Act: P4's boss redrawn, the reference set again, the document recomputed
    redrawBoss(4);
    link->LinkSub.setValue(p(4), link->LinkSub.getSubValues());
    _doc->recompute();

    // Assert: P4 is held by the bar, not made, but the run included it and left it touched, as
    // one that made its shape and then failed: the record is taken, the redraw included (the
    // loud side: held, a target made then failed dated what was drawn since as drawn again,
    // review pr564opus-r3 T-R3-1)
    EXPECT_TRUE(_body->holds(p(4)));
    EXPECT_TRUE(p(4)->isTouched());
    EXPECT_GT(markOf(record(link), sketchOf(p(4))), markOf(before, sketchOf(p(4))));
}

TEST_F(RecordRefreshChain, anObjectOfAnotherDocumentLeftTouchedDoesntHoldTheRecordPastTheRecompute)
{
    // Arrange: as anObjectLeftTouchedDoesntHoldTheRecordPastTheRecompute, the holder in a second
    // document (both saved: a link into another document needs its file)
    auto otherBody = _doc->addObject<PartDesign::Body>("Other");
    auto q0 = pad("Q0", 40, 0, 10, 0, 10, otherBody);
    auto q1 = pad("Q1", 42, 2, 2, 10, 2, otherBody);
    _doc->recompute();
    otherBody->rollTo(q0);
    auto binder = _doc->addObject<PartDesign::ShapeBinder>("Binder");
    _body->addObject(binder);
    binder->Support.setValue(otherBody);
    _doc->recompute();
    namespace fs = std::filesystem;
    const fs::path base = fs::temp_directory_path() / "RecordRefreshChainOtherDocument";
    std::error_code error;
    fs::remove_all(base, error);
    fs::create_directories(base);
    auto& app = App::GetApplication();
    const std::string holdersName = app.getUniqueDocumentName("holders");
    auto holders = app.newDocument(holdersName.c_str(), "testUser");
    ASSERT_TRUE(_doc->saveAs(Base::FileInfo::pathToString(base / "Target.FCStd").c_str()));
    ASSERT_TRUE(holders->saveAs(Base::FileInfo::pathToString(base / "Holders.FCStd").c_str()));
    auto holder = holders->addObject<App::FeatureTest>("Holder");
    auto link = freecad_cast<App::PropertyXLinkSub*>(
        holder->addDynamicProperty(App::PropertyXLinkSub::getClassTypeId().getName(), "XLink"));
    ASSERT_NE(link, nullptr);
    link->setValue(_body, std::vector<std::string> {frontBottomEdge()});
    holders->recompute();
    auto record = [&]() {
        const auto records = link->getElementFingerprints();
        return records.empty() ? std::string() : records[0];
    };
    const auto before = record();
    ASSERT_GE(markOf(before, q1), -1);
    q1->Length.setValue(3.0);

    // Act: P4's boss redrawn, and only the holder's document recomputed
    redrawBoss(4);
    holders->recompute();

    // Assert: the holder's recompute made the chain's Body again (its dependency list crosses into
    // the target's document) and included Q1, held by its bar and left touched: the record is
    // taken, the redraw in it (review pr564son-r4 T-R4-1: an object of another document left
    // touched held it past the recompute)
    EXPECT_TRUE(otherBody->holds(q1));
    EXPECT_TRUE(q1->isTouched());
    EXPECT_FALSE(_body->isTouched());
    EXPECT_GT(markOf(record(), sketchOf(p(4))), markOf(before, sketchOf(p(4))));

    app.closeDocument(holdersName.c_str());
    fs::remove_all(base, error);
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
