// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>
#include "src/App/InitApplication.h"

#include <App/Application.h>
#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/IndexedName.h>
#include "Mod/Part/App/FeaturePartBox.h"
#include "Mod/Part/App/FeaturePartCut.h"
#include "Mod/Part/App/PrimitiveFeature.h"
#include "Mod/PartDesign/App/Body.h"
#include "Mod/PartDesign/App/ShapeBinder.h"

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

class ShapeBinderTest: public ::testing::Test
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
        _body = _doc->addObject<PartDesign::Body>();
        _box = _doc->addObject<Part::Box>();
        _box->Length.setValue(1);
        _box->Width.setValue(2);
        _box->Height.setValue(3);
        _box->Placement.setValue(
            Base::Placement(Base::Vector3d(), Base::Rotation(), Base::Vector3d())
        );  // NOLINT
        //        _body->addObject(_box); // Invalid, Part::Features can't go in a PartDesign::Body,
        //        but we can bind them.
        _binder = _doc->addObject<PartDesign::ShapeBinder>("ShapeBinderFoo");
        _subbinder = _doc->addObject<PartDesign::SubShapeBinder>("SubShapeBinderBar");
        _binder->Shape.setValue(_box->Shape.getShape());
        _subbinder->setLinks({{_box, {"Face1", "Face2"}}}, false);
        _body->addObject(_binder);
        _body->addObject(_subbinder);
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    // NOLINTBEGIN(cppcoreguidelines-non-private-member-variables-in-classes)

    App::Document* _doc = nullptr;
    std::string _docName = "";
    Part::Box* _box = nullptr;
    PartDesign::Body* _body = nullptr;
    PartDesign::ShapeBinder* _binder = nullptr;
    PartDesign::SubShapeBinder* _subbinder = nullptr;

    // NOLINTEND(cppcoreguidelines-non-private-member-variables-in-classes)
};

TEST_F(ShapeBinderTest, shapeBinderExists)
{
    // Arrange
    // Act
    auto binder = _doc->getObject("ShapeBinderFoo");
    // Assert the object is correct
    EXPECT_NE(binder, nullptr);
    // Assert the elementMap is correct
}

TEST_F(ShapeBinderTest, subShapeBinderExists)
{
    // Arrange
    // Act
    auto subbinder = _doc->getObject("SubShapeBinderBar");
    // Assert the object is correct
    EXPECT_NE(subbinder, nullptr);
    // Assert the elementMap is correct
}

namespace
{

/* The centres of the faces of a SubShapeBinder that binds every face of a box cut by a cylinder
 * (names with embedded names), in a V2 document with InternNames on or off. The subs are given
 * in new style, `;<mapped name>.FaceN`, as a selection in the GUI gives them; the link stores
 * them as index names (`Face3`), so the binder's order doesn't depend on the names' form.
 */
std::vector<Base::Vector3d> binderFaceCentres(bool interned)
{
    auto name = App::GetApplication().getUniqueDocumentName("binderOrder");
    auto doc = App::GetApplication().newDocument(name.c_str(), "testUser");
    doc->clearDocument();  // object IDs from 0: the same tags, so the same IDs, in both
    doc->InternNames.setValue(interned);
    auto box = doc->addObject<Part::Box>();
    box->Length.setValue(10);
    box->Width.setValue(10);
    box->Height.setValue(10);
    auto cylinder = doc->addObject<Part::Cylinder>();
    cylinder->Radius.setValue(3);
    cylinder->Height.setValue(20);
    cylinder->Placement.setValue(
        Base::Placement(Base::Vector3d(10, 5, -5), Base::Rotation())
    );
    auto cut = doc->addObject<Part::Cut>();
    cut->Base.setValue(box);
    cut->Tool.setValue(cylinder);
    doc->recompute();
    const auto& shape = cut->Shape.getShape();
    std::vector<std::string> subs;
    int withReference = 0;
    for (int i = 1; i <= static_cast<int>(shape.countSubShapes(TopAbs_FACE)); ++i) {
        auto face = Data::IndexedName::fromConst("Face", i);
        App::ElementNamePair elementName;  // as a selection in the GUI resolves it
        App::GeoFeature::resolveElement(cut, face.toString().c_str(), elementName);
        // The premise: the subs are given in new style, so the stored index names below come
        // from the link's normalization, not from the input
        EXPECT_NE(elementName.newName.find(';'), std::string::npos) << elementName.newName;
        withReference += elementName.newName.find('~') != std::string::npos ? 1 : 0;
        subs.push_back(elementName.newName);
    }
    // ... and in the interned document some of them hold references, whose bytes would sort
    // by ID
    EXPECT_EQ(withReference > 0, interned);
    auto binder = doc->addObject<PartDesign::SubShapeBinder>("Binder");
    binder->setLinks({{cut, subs}}, false);
    for (const auto& link : binder->Support.getSubListValues()) {
        for (const auto& sub : link.getSubValues()) {
            EXPECT_EQ(sub.find(';'), std::string::npos) << sub;  // stored as an index name
        }
    }
    doc->recompute();
    std::vector<Base::Vector3d> centres;
    const auto& bound = binder->Shape.getShape();
    for (int i = 1; i <= static_cast<int>(bound.countSubShapes(TopAbs_FACE)); ++i) {
        Base::Vector3d centre;
        bound.getSubTopoShape(TopAbs_FACE, i).getCenterOfGravity(centre);
        centres.push_back(centre);
    }
    App::GetApplication().closeDocument(name.c_str());
    return centres;
}

}  // namespace

TEST_F(ShapeBinderTest, subShapeBinderNumbersFacesAsInAPlainDocument)
{
    // ops#96: the binder takes its subs in the bytes' order of the stored sub names. Were they
    // mapped names, an interned one (`~<ID>`) would sort by its ID and the faces would come out
    // in another order with InternNames on. The link stores them as index names on every path
    // (its normalization resolves them when they're set), so the order is the same. Not covered:
    // a sub that can't be resolved when it's set (a target in an unloaded document) keeps the
    // form it was given.
    auto plain = binderFaceCentres(false);
    auto interned = binderFaceCentres(true);
    ASSERT_EQ(plain.size(), 8U);
    ASSERT_EQ(interned.size(), plain.size());
    for (std::size_t i = 0; i < plain.size(); ++i) {
        EXPECT_LT((interned[i] - plain[i]).Length(), 1e-7) << "Face" << i + 1;
    }
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
