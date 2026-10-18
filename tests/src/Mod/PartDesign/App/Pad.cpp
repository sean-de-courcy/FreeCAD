// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>
#include "src/App/InitApplication.h"

#include <chrono>
#include <functional>
#include <string>
#include <thread>

#include <boost/scope_exit.hpp>

#include <App/Application.h>
#include <App/Document.h>
#include <App/FeatureTest.h>
#include <App/RecomputeThread.h>
#include <Mod/Part/App/Geometry.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeaturePad.h>
#include <Mod/Sketcher/App/SketchObject.h>

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

class PadTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _doc = App::GetApplication().newDocument("Pad_test", "testUser");
        _body = _doc->addObject<PartDesign::Body>();
        _sketch = _doc->addObject<Sketcher::SketchObject>("Sketch");
        _body->addObject(_sketch);

        _sketch->AttachmentSupport.setValue(_doc->getObject("XY_Plane"), "");
        _sketch->MapMode.setValue("FlatFace");
        Part::GeomCircle circle;
        circle.setRadius(10.0);
        _sketch->addGeometry(&circle, false);
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_doc->getName());
    }

    App::Document* getDocument() const
    {
        return _doc;
    }

    PartDesign::Body* getBody() const
    {
        return _body;
    }

    Sketcher::SketchObject* getSketch() const
    {
        return _sketch;
    }

private:
    App::Document* _doc = nullptr;
    PartDesign::Body* _body = nullptr;
    Sketcher::SketchObject* _sketch = nullptr;
};

TEST_F(PadTest, TestMidPlaneTwoLength)
{
    auto doc = getDocument();
    auto body = getBody();
    auto sketch = getSketch();

    doc->recompute();

    auto pad = doc->addObject<PartDesign::Pad>("Pad");
    body->addObject(pad);
    pad->Profile.setValue(sketch, {""});
    pad->Direction.setValue(0.0, 0.0, 1.0);
    pad->Midplane.setValue(true);
    pad->Length.setValue(10.0);
    pad->Length2.setValue(20.0);

    pad->SideType.setValue("Two sides");

    doc->recompute();

    auto bbox = pad->Shape.getBoundingBox();

    EXPECT_DOUBLE_EQ(bbox.MaxX, 10.0);
    EXPECT_DOUBLE_EQ(bbox.MinX, -10.0);
    EXPECT_DOUBLE_EQ(bbox.MaxY, 10.0);
    EXPECT_DOUBLE_EQ(bbox.MinY, -10.0);
    EXPECT_DOUBLE_EQ(bbox.MaxZ, 10.0);
    EXPECT_DOUBLE_EQ(bbox.MinZ, -20.0);
}

// The GUI's Refresh poll beside an async recompute (FreeCAD-CH ops#352) -------------------------

namespace
{

/// Runs `whileHeld` while the async recompute worker is inside a request for a blocking feature in
/// a second document, then lets the worker finish and waits until it is idle. A single-object
/// request sets no document's Recomputing status; a document request sets only the other
/// document's (as ops#337's attachment poll tests)
void besideTheWorker(bool singleObject, const std::function<void()>& whileHeld)
{
    auto& app = App::GetApplication();
    const std::string otherName = app.getUniqueDocumentName("other");
    auto other = app.newDocument(otherName.c_str(), "testUser");
    BOOST_SCOPE_EXIT_ALL(&)
    {
        app.closeDocument(otherName.c_str());
    };
    auto blocker = other->addObject("App::FeatureTestAsyncBlocker", "Blocker");
    ASSERT_TRUE(blocker);
    const auto request = singleObject ? App::RecomputeRequest::fromDocumentObject(*blocker)
                                      : App::RecomputeRequest::fromDocument(*other, true);
    App::FeatureTestAsyncBlocker::resetBlocker();
    BOOST_SCOPE_EXIT_ALL(&)
    {
        App::FeatureTestAsyncBlocker::releaseBlocker();
        const auto until = std::chrono::steady_clock::now() + std::chrono::seconds(10);
        while (!App::runWhileRecomputeWorkerIdle([] {})
               && std::chrono::steady_clock::now() < until) {
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    };
    blocker->touch();
    ASSERT_TRUE(app.canRecomputeRequestOnWorker(request));
    app.queueRecomputeRequest(request);
    ASSERT_TRUE(App::FeatureTestAsyncBlocker::waitUntilStarted(std::chrono::seconds(10)));
    ASSERT_FALSE(App::runWhileRecomputeWorkerIdle([] {}));
    whileHeld();
}

}  // namespace

class PadPollTest: public PadTest, public ::testing::WithParamInterface<bool>
{
protected:
    /// The fixture's sketch in Body A, a pad of it in Body B, recomputed at one origin; then A
    /// moved: the pad's profile is placed elsewhere than its Body (ops#308, ops#325)
    PartDesign::Pad* padOfAMovedBodysSketch()
    {
        auto doc = getDocument();
        auto bodyB = doc->addObject<PartDesign::Body>("B");
        auto pad = doc->addObject<PartDesign::Pad>("Across");
        bodyB->addObject(pad);
        pad->Profile.setValue(getSketch(), {""});
        pad->Length.setValue(5.0);
        doc->recompute();
        EXPECT_FALSE(pad->mustExecute());
        getBody()->Placement.setValue(
            Base::Placement(Base::Vector3d(0, 0, 10), Base::Rotation())
        );
        EXPECT_TRUE(pad->mustExecute());
        return pad;
    }
};

TEST_P(PadPollTest, placerElsewhereWalksOnlyWithTheWorkerIdle)
{
    // Feature::mustExecute's placerElsewhere() walks Bodies, containers and placements: from the
    // GUI's poll (this thread, no recompute here) not while the worker is inside any request
    auto pad = padOfAMovedBodysSketch();
    besideTheWorker(GetParam(), [&] { EXPECT_FALSE(pad->mustExecute()); });
    EXPECT_TRUE(pad->mustExecute());
    getDocument()->recompute();
    EXPECT_FALSE(pad->isValid());
    EXPECT_FALSE(pad->mustExecute());
}

INSTANTIATE_TEST_SUITE_P(
    WorkerRequest,
    PadPollTest,
    ::testing::Values(true, false),
    [](const ::testing::TestParamInfo<bool>& info) {
        return info.param ? "OneObject" : "AnotherDocument";
    }
);

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
