// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <chrono>
#include <functional>
#include <cmath>
#include <numbers>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <boost/scope_exit.hpp>

#include <src/App/InitApplication.h>
#include <Base/Reader.h>
#include <Base/Writer.h>
#include <App/Application.h>
#include <App/Document.h>
#include <App/FeatureTest.h>
#include <App/Part.h>
#include <App/PropertyLinks.h>
#include <App/RecomputeThread.h>
#include <Mod/Part/App/FeaturePartBox.h>
#include <Mod/Part/App/PrimitiveFeature.h>


class TestablePlane: public Part::Plane
{
public:
    bool restoreLegacySupport(Base::XMLReader& reader, const char* typeName)
    {
        return extensionHandleChangedPropertyName(reader, typeName, "Support");
    }
};


template<typename PropertyT>
void restoreLegacySupport(TestablePlane& plane, PropertyT& property)
{
    const std::string typeName(property.getTypeId().getName());
    Base::StringWriter writer;
    property.Save(writer);

    std::stringstream data;
    data << "<?xml version='1.0' encoding='utf-8'?>\n"
         << "<Property name='Support' type='" << typeName << "'>\n"
         << writer.getString() << "</Property>\n";
    Base::XMLReader reader("Document.xml", data);

    EXPECT_TRUE(plane.restoreLegacySupport(reader, typeName.c_str()));
}


template<typename PropertyT>
void restoreEmptyLegacySupport(TestablePlane& plane)
{
    PropertyT property;
    restoreLegacySupport(plane, property);
}


class AttachExtensionTest: public ::testing::Test
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
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    App::Document* getDocument() const
    {
        return _doc;
    }

    TestablePlane* createTestablePlane(const char* name)
    {
        auto plane = new TestablePlane();
        getDocument()->addObject(plane, name);
        return plane;
    }

private:
    std::string _docName;
    App::Document* _doc = nullptr;
};

TEST_F(AttachExtensionTest, testPlanePlane)
{
    auto plane1 = getDocument()->addObject<Part::Plane>("Plane1");
    auto plane2 = getDocument()->addObject<Part::Plane>("Plane2");

    ASSERT_TRUE(plane1);
    ASSERT_TRUE(plane2);

    getDocument()->recompute();

    plane2->MapReversed.setValue(false);
    plane2->AttachmentSupport.setValue(plane1);
    plane2->MapPathParameter.setValue(0.0);
    plane2->MapMode.setValue("FlatFace");

    getDocument()->recompute();
    EXPECT_TRUE(true);
}

TEST_F(AttachExtensionTest, testMidPlane)
{
    auto firstPlane = getDocument()->addObject<Part::Plane>("FirstPlane");
    auto secondPlane = getDocument()->addObject<Part::Plane>("SecondPlane");
    auto midPlane = getDocument()->addObject<Part::Plane>("MidPlane");

    ASSERT_TRUE(firstPlane);
    ASSERT_TRUE(secondPlane);
    ASSERT_TRUE(midPlane);

    secondPlane->Placement.setValue(
        Base::Placement(
            Base::Vector3d(0, 100, 20),
            Base::Rotation(Base::Vector3d(1, 0, 0), std::numbers::pi)
        )
    );
    midPlane->AttachmentSupport.setValues({firstPlane, secondPlane}, {"", ""});
    midPlane->MapMode.setValue("MidPlane");
    EXPECT_STREQ(midPlane->MapMode.getValueAsString(), "MidPlane");

    getDocument()->recompute();

    const Base::Placement placement = midPlane->Placement.getValue();
    const Base::Vector3d position = placement.getPosition();
    EXPECT_NEAR(position.x, 50.0, 1e-7);
    EXPECT_NEAR(position.y, 50.0, 1e-7);
    EXPECT_NEAR(position.z, 10.0, 1e-7);

    Base::Vector3d normal;
    placement.getRotation().multVec(Base::Vector3d(0, 0, 1), normal);
    EXPECT_NEAR(normal.x, 0.0, 1e-7);
    EXPECT_NEAR(normal.y, 0.0, 1e-7);
    EXPECT_NEAR(normal.z, 1.0, 1e-7);
}

TEST_F(AttachExtensionTest, testMidPlaneBisectsFaceAngle)
{
    auto firstPlane = getDocument()->addObject<Part::Plane>("FirstPlane");
    auto secondPlane = getDocument()->addObject<Part::Plane>("SecondPlane");
    auto midPlane = getDocument()->addObject<Part::Plane>("MidPlane");

    ASSERT_TRUE(firstPlane);
    ASSERT_TRUE(secondPlane);
    ASSERT_TRUE(midPlane);

    const Base::Placement secondPlacement(
        Base::Vector3d(0, 0, 10),
        Base::Rotation(Base::Vector3d(1, 0, 0), std::numbers::pi / 2.0)
    );
    secondPlane->Placement.setValue(secondPlacement);
    midPlane->AttachmentSupport.setValues({firstPlane, secondPlane}, {"", ""});
    midPlane->MapMode.setValue("MidPlane");

    getDocument()->recompute();

    const Base::Vector3d position = midPlane->Placement.getValue().getPosition();
    EXPECT_NEAR(position.x, 50.0, 1e-7);
    EXPECT_NEAR(position.y, 27.5, 1e-7);
    EXPECT_NEAR(position.z, 27.5, 1e-7);

    Base::Vector3d secondNormal;
    secondPlacement.getRotation().multVec(Base::Vector3d(0, 0, 1), secondNormal);
    Base::Vector3d expectedNormal(0, 0, 1);
    expectedNormal += secondNormal;
    expectedNormal.Normalize();

    Base::Vector3d normal;
    midPlane->Placement.getValue().getRotation().multVec(Base::Vector3d(0, 0, 1), normal);
    EXPECT_NEAR(normal.x, expectedNormal.x, 1e-7);
    EXPECT_NEAR(normal.y, expectedNormal.y, 1e-7);
    EXPECT_NEAR(normal.z, expectedNormal.z, 1e-7);

    // The faces are z = 0 and y = 0, so they intersect on the X axis.
    EXPECT_NEAR(normal.Dot(Base::Vector3d(0, 0, 0) - position), 0.0, 1e-7);
    EXPECT_NEAR(normal.Dot(Base::Vector3d(10, 0, 0) - position), 0.0, 1e-7);
}

TEST_F(AttachExtensionTest, testMidPlaneBisectsConnectedFaces)
{
    auto box = getDocument()->addObject<Part::Box>("Box");
    auto midPlane = getDocument()->addObject<Part::Plane>("MidPlane");

    ASSERT_TRUE(box);
    ASSERT_TRUE(midPlane);

    box->Length.setValue(100.0);
    box->Width.setValue(60.0);
    box->Height.setValue(20.0);
    midPlane->AttachmentSupport.setValues({box, box}, {"Face6", "Face4"});
    midPlane->MapMode.setValue("MidPlane");

    getDocument()->recompute();

    const Base::Placement placement = midPlane->Placement.getValue();
    const Base::Vector3d position = placement.getPosition();
    EXPECT_NEAR(position.x, 50.0, 1e-7);
    EXPECT_NEAR(position.y, 50.0, 1e-7);
    EXPECT_NEAR(position.z, 10.0, 1e-7);

    Base::Vector3d normal;
    placement.getRotation().multVec(Base::Vector3d(0, 0, 1), normal);
    EXPECT_NEAR(normal.x, 0.0, 1e-7);
    EXPECT_NEAR(normal.y, -std::sqrt(0.5), 1e-7);
    EXPECT_NEAR(normal.z, std::sqrt(0.5), 1e-7);

    // Face6 (z = Height) and Face4 (y = Width) meet at the edge y = 60, z = 20.
    EXPECT_NEAR(normal.Dot(Base::Vector3d(0, 60, 20) - position), 0.0, 1e-7);
    EXPECT_NEAR(normal.Dot(Base::Vector3d(100, 60, 20) - position), 0.0, 1e-7);
}

TEST_F(AttachExtensionTest, testMidPlaneBisectsObliqueFaceAngle)
{
    auto firstPlane = getDocument()->addObject<Part::Plane>("FirstPlane");
    auto secondPlane = getDocument()->addObject<Part::Plane>("SecondPlane");
    auto midPlane = getDocument()->addObject<Part::Plane>("MidPlane");

    ASSERT_TRUE(firstPlane);
    ASSERT_TRUE(secondPlane);
    ASSERT_TRUE(midPlane);

    // Rotating the second plane about the Y axis through the origin keeps both planes on the
    // Y axis, so the faces intersect there at a 50 degree dihedral angle. The differing sizes
    // put the face centers off the bisector, so the base point has to be corrected onto it.
    const double angle = 50.0 * std::numbers::pi / 180.0;
    secondPlane->Length.setValue(60.0);
    secondPlane->Width.setValue(60.0);
    secondPlane->Placement.setValue(
        Base::Placement(Base::Vector3d(0, 0, 0), Base::Rotation(Base::Vector3d(0, 1, 0), angle))
    );
    midPlane->AttachmentSupport.setValues({firstPlane, secondPlane}, {"", ""});
    midPlane->MapMode.setValue("MidPlane");

    getDocument()->recompute();

    const Base::Placement placement = midPlane->Placement.getValue();
    const Base::Vector3d position = placement.getPosition();
    Base::Vector3d normal;
    placement.getRotation().multVec(Base::Vector3d(0, 0, 1), normal);

    EXPECT_NEAR(normal.x, std::sin(angle / 2.0), 1e-7);
    EXPECT_NEAR(normal.y, 0.0, 1e-7);
    EXPECT_NEAR(normal.z, std::cos(angle / 2.0), 1e-7);

    EXPECT_NEAR(normal.Dot(Base::Vector3d(0, 0, 0) - position), 0.0, 1e-7);
    EXPECT_NEAR(normal.Dot(Base::Vector3d(0, 10, 0) - position), 0.0, 1e-7);
}

TEST_F(AttachExtensionTest, testAttacherEngineType)
{
    auto plane = getDocument()->addObject<Part::Plane>("Plane");
    EXPECT_STREQ(plane->AttacherType.getValue(), "Attacher::AttachEngine3D");
    EXPECT_STREQ(plane->AttacherEngine.getValueAsString(), "Engine 3D");

    plane->AttacherEngine.setValue(1L);
    EXPECT_STREQ(plane->AttacherType.getValue(), "Attacher::AttachEnginePlane");
    EXPECT_STREQ(plane->AttacherEngine.getValueAsString(), "Engine Plane");

    plane->AttacherEngine.setValue(2L);
    EXPECT_STREQ(plane->AttacherType.getValue(), "Attacher::AttachEngineLine");
    EXPECT_STREQ(plane->AttacherEngine.getValueAsString(), "Engine Line");

    plane->AttacherEngine.setValue(3L);
    EXPECT_STREQ(plane->AttacherType.getValue(), "Attacher::AttachEnginePoint");
    EXPECT_STREQ(plane->AttacherEngine.getValueAsString(), "Engine Point");
}

TEST_F(AttachExtensionTest, testAttacherTypeEngine)
{
    auto plane = getDocument()->addObject<Part::Plane>("Plane");
    EXPECT_STREQ(plane->AttacherType.getValue(), "Attacher::AttachEngine3D");
    EXPECT_STREQ(plane->AttacherEngine.getValueAsString(), "Engine 3D");

    plane->AttacherType.setValue("Attacher::AttachEnginePlane");
    plane->onExtendedDocumentRestored();
    EXPECT_STREQ(plane->AttacherEngine.getValueAsString(), "Engine Plane");

    plane->AttacherType.setValue("Attacher::AttachEngineLine");
    plane->onExtendedDocumentRestored();
    EXPECT_STREQ(plane->AttacherEngine.getValueAsString(), "Engine Line");

    plane->AttacherType.setValue("Attacher::AttachEnginePoint");
    plane->onExtendedDocumentRestored();
    EXPECT_STREQ(plane->AttacherEngine.getValueAsString(), "Engine Point");

    plane->AttacherType.setValue("Attacher::AttachEngine3D");
    plane->onExtendedDocumentRestored();
    EXPECT_STREQ(plane->AttacherEngine.getValueAsString(), "Engine 3D");
}

TEST_F(AttachExtensionTest, testEmptyLegacySupportDoesNotClearAttachmentSupport)
{
    auto object = createTestablePlane("Object");
    auto support = getDocument()->addObject<Part::Plane>("Support");
    ASSERT_TRUE(object);
    ASSERT_TRUE(support);

    object->AttachmentSupport.setValue(support, "Face1");
    object->MapMode.setValue("Deactivated");

    restoreEmptyLegacySupport<App::PropertyLinkSub>(*object);
    restoreEmptyLegacySupport<App::PropertyLinkSubList>(*object);

    ASSERT_EQ(object->AttachmentSupport.getValues().size(), 1);
    EXPECT_EQ(object->AttachmentSupport.getValues().front(), support);
    ASSERT_EQ(object->AttachmentSupport.getSubValues().size(), 1);
    EXPECT_EQ(object->AttachmentSupport.getSubValues().front(), "Face1");
    EXPECT_STREQ(object->MapMode.getValueAsString(), "Deactivated");
}

TEST_F(AttachExtensionTest, testNonEmptyLegacySupportReplacesAttachmentSupport)
{
    auto object = createTestablePlane("Object");
    auto currentSupport = getDocument()->addObject<Part::Plane>("CurrentSupport");
    auto legacySupport = getDocument()->addObject<Part::Plane>("LegacySupport");
    ASSERT_TRUE(object);
    ASSERT_TRUE(currentSupport);
    ASSERT_TRUE(legacySupport);

    object->AttachmentSupport.setValue(currentSupport, "Face1");
    object->MapMode.setValue("Deactivated");

    App::PropertyLinkSub oldLinkSub;
    oldLinkSub.setContainer(object);
    oldLinkSub.setValue(legacySupport, std::vector<std::string> {"Face2"});
    restoreLegacySupport(*object, oldLinkSub);

    ASSERT_EQ(object->AttachmentSupport.getValues().size(), 1);
    EXPECT_EQ(object->AttachmentSupport.getValues().front(), legacySupport);
    EXPECT_STREQ(object->MapMode.getValueAsString(), "FlatFace");

    object->AttachmentSupport.setValue(currentSupport, "Face1");
    object->MapMode.setValue("Deactivated");

    App::PropertyLinkSubList oldLinkSubList;
    oldLinkSubList.setContainer(object);
    oldLinkSubList.setValues(
        std::vector<App::DocumentObject*> {legacySupport},
        std::vector<std::string> {"Face2"}
    );
    restoreLegacySupport(*object, oldLinkSubList);

    ASSERT_EQ(object->AttachmentSupport.getValues().size(), 1);
    EXPECT_EQ(object->AttachmentSupport.getValues().front(), legacySupport);
    ASSERT_EQ(object->AttachmentSupport.getSubValues().size(), 1);
    EXPECT_EQ(object->AttachmentSupport.getSubValues().front(), "Face2");
    EXPECT_STREQ(object->MapMode.getValueAsString(), "Deactivated");
}

// The GUI's Refresh poll beside an async recompute (FreeCAD-CH ops#337) ------------------------

namespace
{

/// A plane at the document's root on the top face of a box in an App::Part at z = 50, recomputed,
/// then the App::Part moved to z = 80: the plane's link frame differs from the one it was placed in
Part::Plane* planeOnAMovedPart(App::Document* doc)
{
    auto part = doc->addObject<App::Part>("PA");
    part->Placement.setValue(Base::Placement(Base::Vector3d(0, 0, 50), Base::Rotation()));
    auto box = doc->addObject<Part::Box>("Inside");
    part->addObject(box);
    auto plane = doc->addObject<Part::Plane>("Attached");
    plane->AttachmentSupport.setValue(box, std::vector<std::string> {"Face6"});
    plane->MapMode.setValue("FlatFace");
    doc->recompute();
    EXPECT_NEAR(plane->Placement.getValue().getPosition().z, 60, 1e-9);
    part->Placement.setValue(Base::Placement(Base::Vector3d(0, 0, 80), Base::Rotation()));
    return plane;
}

bool polledFramesChanged(Part::Plane* plane)
{
    return plane->getExtensionByType<Part::AttachExtension>()->linkFramesChanged();
}

/// Queues `request` with a blocking feature in it, and checks the poll while the worker holds it:
/// no walk, so no; after the worker is done, yes; after a recompute, placed anew and no
void checkPollBesideTheWorker(
    Part::Plane* plane,
    App::DocumentObject* blocker,
    const App::RecomputeRequest& request
)
{
    auto& app = App::GetApplication();
    EXPECT_TRUE(polledFramesChanged(plane));

    App::FeatureTestAsyncBlocker::resetBlocker();
    BOOST_SCOPE_EXIT_ALL(&)
    {
        App::FeatureTestAsyncBlocker::releaseBlocker();
    };
    blocker->touch();
    ASSERT_TRUE(app.canRecomputeRequestOnWorker(request));
    app.queueRecomputeRequest(request);
    ASSERT_TRUE(App::FeatureTestAsyncBlocker::waitUntilStarted(std::chrono::seconds(2)));

    // The worker is inside the request: the poll from this thread doesn't walk
    EXPECT_FALSE(polledFramesChanged(plane));
    EXPECT_FALSE(App::runWhileRecomputeWorkerIdle([] {}));

    App::FeatureTestAsyncBlocker::releaseBlocker();
    // Until the worker has finished the request
    const auto until = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (!App::runWhileRecomputeWorkerIdle([] {}) && std::chrono::steady_clock::now() < until) {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    ASSERT_TRUE(App::runWhileRecomputeWorkerIdle([] {}));
    EXPECT_TRUE(polledFramesChanged(plane));

    plane->getDocument()->recompute();
    EXPECT_NEAR(plane->Placement.getValue().getPosition().z, 90, 1e-9);
    EXPECT_FALSE(polledFramesChanged(plane));
}

}  // namespace

// The blocking feature in a second document: a request in the plane's own document recomputes
// the plane first, on the worker, so the poll beside it would find no difference either way
void checkPollBesideAnotherDocument(
    Part::Plane* plane,
    const std::function<App::RecomputeRequest(App::Document&, App::DocumentObject&)>& request
)
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
    checkPollBesideTheWorker(plane, blocker, request(*other, *blocker));
}

TEST_F(AttachExtensionTest, testPollBesideAWorkerRecomputeOfOneObject)
{
    // A single-object request (recomputeFeature) sets neither a document's Recomputing status
    // nor the recompute's thread marker: the old guard let the poll walk beside it
    checkPollBesideAnotherDocument(
        planeOnAMovedPart(getDocument()),
        [](App::Document&, App::DocumentObject& blocker) {
            return App::RecomputeRequest::fromDocumentObject(blocker);
        }
    );
}

TEST_F(AttachExtensionTest, testPollBesideAWorkerRecomputeOfAnotherDocument)
{
    // The walk reads objects of other documents too, but the old guard tested only the plane's
    checkPollBesideAnotherDocument(
        planeOnAMovedPart(getDocument()),
        [](App::Document& other, App::DocumentObject&) {
            return App::RecomputeRequest::fromDocument(other, true);
        }
    );
}

TEST_F(AttachExtensionTest, testPollWithTheWorkerIdleComparesFrames)
{
    auto plane = planeOnAMovedPart(getDocument());
    EXPECT_TRUE(polledFramesChanged(plane));
    getDocument()->recompute();
    EXPECT_NEAR(plane->Placement.getValue().getPosition().z, 90, 1e-9);
    EXPECT_FALSE(polledFramesChanged(plane));
}
