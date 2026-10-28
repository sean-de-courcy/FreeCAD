// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <functional>
#include <numbers>
#include <set>

#include <boost/core/ignore_unused.hpp>
#include "Mod/Part/App/FeaturePartCommon.h"
#include "Mod/Part/App/FeatureExtrusion.h"
#include "Mod/Part/App/FeaturePartFuse.h"
#include "Mod/Part/App/PrimitiveFeature.h"
#include "Mod/Part/App/TopoShapeOpCode.h"
#include <App/Link.h>
#include <src/App/InitApplication.h>
#include <BRep_Builder.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <TopoDS_Compound.hxx>
#include <gp.hxx>
#include <gp_Ax1.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <TopLoc_Location.hxx>
#include "PartTestHelpers.h"
#include "App/ElementFingerprint.h"
#include "App/ElementSolver.h"
#include "App/MappedElement.h"
#include "App/NameTable.h"
#include <Base/Interpreter.h>
#include <Base/Console.h>
#include <Base/FileInfo.h>
#include <App/PropertyLinks.h>
#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>

using namespace Part;
using namespace PartTestHelpers;

class FeaturePartTest: public ::testing::Test, public PartTestHelperClass
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }


    void SetUp() override
    {
        createTestDoc();
        _common = _doc->addObject<Common>();
    }

    void TearDown() override
    {}

    Common* _common = nullptr;  // NOLINT Can't be private in a test framework
};

TEST_F(FeaturePartTest, testGetElementName)
{
    // Arrange
    _common->Base.setValue(_boxes[0]);
    _common->Tool.setValue(_boxes[1]);

    // Act
    _common->execute();
    const TopoShape& ts = _common->Shape.getShape();

    auto namePair = _common->getElementName("test");
    auto namePairExport = _common->getElementName("test", App::GeoFeature::Export);
    auto namePairSelf = _common->getElementName(nullptr);
    // Assert
    EXPECT_STREQ(namePair.newName.c_str(), "");
    EXPECT_STREQ(namePair.oldName.c_str(), "test");
    EXPECT_STREQ(namePairExport.newName.c_str(), "");
    EXPECT_STREQ(namePairExport.oldName.c_str(), "test");
    EXPECT_STREQ(namePairSelf.newName.c_str(), "");
    EXPECT_STREQ(namePairSelf.oldName.c_str(), "");
    //   the common is a box: every one of its 26 elements is named (which names:
    //   FeaturePartCommonTest.testMapping)
    EXPECT_EQ(
        ts.countSubElements("Vertex") + ts.countSubElements("Edge") + ts.countSubElements("Face"),
        26
    );
    EXPECT_TRUE(allElementsNamed(ts));
    // TBD
}

TEST_F(FeaturePartTest, create)
{
    // Arrange

    // A shape that will be passed to the various calls of Feature::create
    auto shape {TopoShape(BRepBuilderAPI_MakeVertex(gp_Pnt(1.0, 1.0, 1.0)).Vertex(), 1)};

    auto otherDocName {App::GetApplication().getUniqueDocumentName("otherDoc")};
    // Another document where it will be created a shape
    auto otherDoc {App::GetApplication().newDocument(otherDocName.c_str(), "otherDocUser")};

    // _doc is populated by PartTestHelperClass::createTestDoc. Making it an empty document
    _doc->clearDocument();

    // Setting the active document back to _doc otherwise the first 3 calls to Feature::create will
    // act on otherDoc
    App::GetApplication().setActiveDocument(_doc);

    // Act

    // A feature with an empty TopoShape
    auto featureNoShape {Feature::create(TopoShape())};

    // A feature with a TopoShape
    auto featureNoName {Feature::create(shape)};

    // A feature with a TopoShape and a name
    auto featureNoDoc {Feature::create(shape, "Vertex")};

    // A feature with a TopoShape and a name in the document otherDoc
    auto feature {Feature::create(shape, "Vertex", otherDoc)};

    // Assert

    // Check that the shapes have been added. Only featureNoShape should return an empty shape, the
    // others should have it as TopoShape shape is passed as argument
    EXPECT_TRUE(featureNoShape->Shape.getValue().IsNull());
    EXPECT_FALSE(featureNoName->Shape.getValue().IsNull());
    EXPECT_FALSE(featureNoDoc->Shape.getValue().IsNull());
    EXPECT_FALSE(feature->Shape.getValue().IsNull());

    // Check the features names

    // Without a name the feature's name will be set to "Shape"
    EXPECT_STREQ(_doc->getObjectName(featureNoShape), "Shape");

    // In _doc there's already a shape with name "Shape" and, as there can't be duplicated names in
    // the same document, the other feature will get an unique name that will still contain "Shape"
    EXPECT_STREQ(_doc->getObjectName(featureNoName), "Shape001");

    // There aren't other features with name "Vertex" in _doc, therefore that name will be assigned
    // without modifications
    EXPECT_STREQ(_doc->getObjectName(featureNoDoc), "Vertex");

    // The feature is created in otherDoc, which doesn't have other features and thertherefore the
    // feature's name will be assigned without modifications
    EXPECT_STREQ(otherDoc->getObjectName(feature), "Vertex");

    // Check that the features have been created in the correct document

    // The first 3 calls to Feature::create acts on _doc, which is empty, and therefore the number
    // of features in that document is the same of the features created with Feature::create
    EXPECT_EQ(_doc->getObjects().size(), 3);

    // The last call to Feature::create acts on otherDoc, which is empty, and therefore that
    // document will have only 1 feature
    EXPECT_EQ(otherDoc->getObjects().size(), 1);
}

TEST_F(FeaturePartTest, getElementHistory)
{
    // Arrange
    const char* name2 = "Edge2";  // Edge, Vertex, or Face. will work here.
    // Act
    auto result = Feature::getElementHistory(_boxes[0], name2, true, false);
    Data::HistoryItem histItem = result.front();
    // Assert
    EXPECT_EQ(result.size(), 1);
    EXPECT_NE(histItem.tag, 0);  // Make sure we have one.  It will vary.
    EXPECT_EQ(histItem.index.getIndex(), 2);
    EXPECT_STREQ(histItem.index.getType(), "Edge");
    EXPECT_STREQ(histItem.element.toString().c_str(), name2);
    EXPECT_EQ(histItem.obj, _boxes[0]);
}

TEST_F(FeaturePartTest, getRelatedElements)
{
    // Arrange
    _common->Base.setValue(_boxes[0]);
    _common->Tool.setValue(_boxes[1]);
    // Act
    _common->execute();
    auto label1 = _common->Label.getValue();
    auto label2 = _boxes[1]->Label.getValue();
    const TopoShape& ts = _common->Shape.getShape();
    boost::ignore_unused(ts);
    auto result = Feature::getRelatedElements(
        _doc->getObject(label1),
        "Edge2",
        HistoryTraceType::followTypeChange,
        true
    );
    auto result2 = Feature::getRelatedElements(
        _doc->getObject(label2),
        "Edge1",
        HistoryTraceType::followTypeChange,
        true
    );
    // Assert
    EXPECT_EQ(result.size(), 1);   // Found the one.
    EXPECT_EQ(result2.size(), 0);  // No element map, so no related elements
    // The results are always going to vary, so we can't test for specific values:
    // EXPECT_STREQ(result.front().name.toString().c_str(),"Edge3;:M;CMN;:H38d:7,E");
}

TEST_F(FeaturePartTest, getRelatedElementsOfAMissingNameV2)
{
    // Arrange
    //   a 10 mm cube with a ridge across its top face, fused: the top face is split in two. Then
    //   the ridge moves into the cube, and the pieces' names are gone.
    ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V2);
    auto cube = _doc->addObject<Part::Box>("Cube");
    cube->Length.setValue(10);
    cube->Width.setValue(10);
    cube->Height.setValue(10);
    auto ridge = _doc->addObject<Part::Box>("Ridge");
    ridge->Length.setValue(2);
    ridge->Width.setValue(12);
    ridge->Height.setValue(2);
    ridge->Placement.setValue(Base::Placement(Base::Vector3d(4, -1, 9), Base::Rotation()));
    auto fuse = _doc->addObject<Part::Fuse>("Fuse");
    fuse->Base.setValue(cube);
    fuse->Tool.setValue(ridge);
    fuse->Refine.setValue(false);
    _doc->recompute();
    //   the faces in the plane z = 10
    auto topFaces = [&]() {
        std::vector<Data::MappedElement> result;
        const TopoShape& shape = fuse->Shape.getShape();
        for (int i = 1; i <= shape.countSubShapes(TopAbs_FACE); ++i) {
            Data::IndexedName index("Face", i);
            auto box = TopoShape(shape.getSubShape(TopAbs_FACE, i)).getBoundBox();
            if (std::abs(box.MinZ - 10) < 1e-7 && std::abs(box.MaxZ - 10) < 1e-7) {
                result.emplace_back(shape.getMappedName(index), index);
            }
        }
        return result;
    };
    auto pieces = topFaces();
    ASSERT_EQ(pieces.size(), 2);
    Data::MappedName oldName = pieces.front().name.copy();
    ridge->Width.setValue(2);
    ridge->Placement.setValue(Base::Placement(Base::Vector3d(4, 4, 4), Base::Rotation()));
    _doc->recompute();
    ASSERT_EQ(topFaces().size(), 1);
    const TopoShape& shape = fuse->Shape.getShape();
    ASSERT_FALSE(shape.getIndexedName(oldName));
    std::string oldReference = Data::ComplexGeoData::elementMapPrefix() + oldName.toString();

    // Act
    Data::MappedName original;
    long tag = shape.getElementHistory(oldName, &original);
    auto related = Feature::getRelatedElements(
        fuse,
        oldReference.c_str(),
        HistoryTraceType::followTypeChange,
        false
    );

    // Assert
    //   the old piece's history leads to the cube's top face (ops#27)
    EXPECT_EQ(tag, cube->getID());
    EXPECT_EQ(original.toString(), "Face6");
    //   but getRelatedElements() can't read a missing V2 name's element type
    //   (ComplexGeoData::elementType() reads V1 postfixes and index names), so it finds nothing
    //   before it looks at the history. Its callers (Attacher, the Sketcher's
    //   fixExternalGeometry, the fillet dialog, the dress-up panel's guessNewLink) keep their V2
    //   behaviour.
    EXPECT_TRUE(related.empty());
}

// Note that this test is pretty trivial and useless .. but the method in question is never
// called in the codebase.
TEST_F(FeaturePartTest, getElementFromSource)
{
    // Arrange
    _common->Base.setValue(_boxes[0]);
    _common->Tool.setValue(_boxes[1]);
    App::DocumentObject sourceObject;
    //    const char *sourceSubElement;
    // Act
    _common->execute();
    auto label1 = _common->Label.getValue();
    auto label2 = _boxes[1]->Label.getValue();
    const TopoShape& ts = _common->Shape.getShape();
    boost::ignore_unused(label1);
    boost::ignore_unused(label2);
    boost::ignore_unused(ts);
    auto element = Feature::getElementFromSource(
        _common,
        "Part__Box001",  // "Edge1",
        _boxes[0],
        "Face1",  // "Edge1",
        false
    );
    // Assert
    EXPECT_EQ(element.size(), 0);
}

TEST_F(FeaturePartTest, getSubObject)
{
    // Arrange
    _common->Base.setValue(_boxes[0]);
    _common->Tool.setValue(_boxes[1]);
    App::DocumentObject sourceObject;
    PyObject* pyObj;
    Base::PyGILStateLocker lock;  // getSubObject builds a Python wrapper for the shape
    // Act
    _common->execute();
    auto result = _boxes[1]->getSubObject("Face5", &pyObj, nullptr, false, 10);
    // Assert
    ASSERT_NE(result, nullptr);
    EXPECT_STREQ(result->getNameInDocument(), "Part__Box001");
}

TEST_F(FeaturePartTest, getElementTypes)
{
    Part::Feature pf;
    std::vector<const char*> types = pf.getElementTypes();

    EXPECT_EQ(types.size(), 3);
    EXPECT_STREQ(types[0], "Face");
    EXPECT_STREQ(types[1], "Edge");
    EXPECT_STREQ(types[2], "Vertex");
}

TEST_F(FeaturePartTest, getComplexElementTypes)
{
    Part::TopoShape shape;
    std::vector<const char*> types = shape.getElementTypes();

    EXPECT_EQ(types.size(), 3);
    EXPECT_STREQ(types[0], "Face");
    EXPECT_STREQ(types[1], "Edge");
    EXPECT_STREQ(types[2], "Vertex");
}

namespace
{
// A pad's vertical side edge, generated from the sketch vertex where two lines meet. The vertex's
// name lists the two lines' vertex IDs, e.g. {"g1v2", "g2v1"}: the front line's end and the right
// line's start (ops#79).
Data::MappedName sideEdgeName(const std::vector<std::string>& vertexIDs)
{
    Data::MappedName vertex(Data::MappedName::makeEncodedSection(
        vertexIDs,
        std::vector<Data::MappedName> {},
        5,
        "SKT",
        0,
        'V',
        0,
        {Data::MAPPER_FLAG_SOURCE},
        std::vector<Data::MappedName> {}
    ));
    return Data::MappedName(Data::MappedName::makeEncodedSection(
        std::vector<std::string> {},
        std::vector<Data::MappedName> {vertex},
        6,
        "XTR",
        0,
        'E',
        0,
        {Data::MAPPER_FLAG_GENERATED},
        std::vector<Data::MappedName> {}
    ));
}

std::vector<std::string> indexesOf(const std::vector<Data::MappedElement>& elements)
{
    std::vector<std::string> indexes;
    for (const auto& element : elements) {
        indexes.push_back(element.index.toString());
    }
    return indexes;
}
}  // namespace

TEST_F(FeaturePartTest, doNamesMatchStrictRejectsOneSharedVertexID)
{
    // Arrange
    //   pattern: a rectangle's corner at (20, 0) is the vertex g1v2,g2v1. A notch in the front
    //   line g1 moves g1's end to the notch's first corner, g1v2,g5v1, and the corner becomes
    //   g2v1,g8v2: each shares one ID with the old corner (ops#79).
    auto corner = sideEdgeName({"g1v2", "g2v1"});
    auto notchCorner = sideEdgeName({"g1v2", "g5v1"});
    auto movedCorner = sideEdgeName({"g2v1", "g8v2"});
    auto sameCorner = sideEdgeName({"g2v1", "g1v2"});
    auto otherCorner = sideEdgeName({"g3v2", "g4v1"});

    // Act and assert
    //   loose: one shared vertex ID is enough
    EXPECT_TRUE(Feature::doNamesMatch(corner, notchCorner));
    EXPECT_TRUE(Feature::doNamesMatch(corner, movedCorner));
    //   strict: it isn't
    EXPECT_FALSE(Feature::doNamesMatch(corner, notchCorner, false, true));
    EXPECT_FALSE(Feature::doNamesMatch(corner, movedCorner, false, true));
    //   both IDs shared, in either order, still match strictly
    EXPECT_TRUE(Feature::doNamesMatch(corner, sameCorner, false, true));
    //   no shared ID matches in neither mode
    EXPECT_FALSE(Feature::doNamesMatch(corner, otherCorner));
    EXPECT_FALSE(Feature::doNamesMatch(corner, otherCorner, false, true));
}

TEST_F(FeaturePartTest, doNamesMatchKeepsPatternInstancesApart)
{
    // Arrange
    //   pattern: a pattern's instances are copies of the support's face that end in a TRF section
    //   with the pattern's ID and the instance number (ops#55); a fusion splits a face by
    //   appending a MOD section of its own
    auto section = [](long tag, const char* op, int index) {
        return std::string("|")
            + Data::MappedName::makeEncodedSection(
                   std::vector<std::string> {},
                   std::vector<Data::MappedName> {},
                   tag,
                   op,
                   index,
                   'F',
                   0,
                   {Data::MAPPER_FLAG_MODIFIED},
                   std::vector<Data::MappedName> {}
            );
    };
    auto withSection = [&](const Data::MappedName& name, long tag, const char* op, int index) {
        return Data::MappedName(name.toString() + section(tag, op, index));
    };
    auto support = Data::MappedName::makeUnmappedName({"Face6"}, 5, "MKR", 'F');
    auto instance2 = withSection(support, 9, OpCodes::Transformed, 2);
    auto instance3 = withSection(support, 9, OpCodes::Transformed, 3);
    auto sameInstance3 = withSection(support, 9, OpCodes::Transformed, 3);
    auto otherPatternsInstance3 = withSection(support, 8, OpCodes::Transformed, 3);
    auto pieceOfInstance3 = withSection(instance3, 10, OpCodes::Fuse, 0);
    auto pieceOfSupport = withSection(support, 10, OpCodes::Fuse, 0);

    // Act and assert
    //   an instance is neither the support nor another instance, of this pattern or another
    EXPECT_FALSE(Feature::doNamesMatch(instance3, support));
    EXPECT_FALSE(Feature::doNamesMatch(support, instance3));
    EXPECT_FALSE(Feature::doNamesMatch(instance3, instance2));
    EXPECT_FALSE(Feature::doNamesMatch(instance3, otherPatternsInstance3));
    EXPECT_TRUE(Feature::doNamesMatch(instance3, sameInstance3));
    //   a piece still matches the face it was split from, in an instance as in the support
    EXPECT_TRUE(Feature::doNamesMatch(pieceOfInstance3, instance3));
    EXPECT_TRUE(Feature::doNamesMatch(pieceOfSupport, support));
    EXPECT_FALSE(Feature::doNamesMatch(pieceOfInstance3, support));
    //   a multi-step pattern's numbers (ops#6) compare as text: instance (2, 2) is neither (2, 1)
    //   nor (1, 2), and its pieces match it
    auto stepped = [&](const char* number) {
        return Data::MappedName(support.toString() + "|_;_;9;TRF;" + number + ";F;0;MOD;_");
    };
    auto x2y2 = stepped("2:2");
    auto sameX2y2 = stepped("2:2");
    auto x2 = stepped("2");
    auto x1y2 = stepped("1:2");
    auto pieceOfX2y2 = withSection(x2y2, 10, OpCodes::Fuse, 0);
    EXPECT_TRUE(Feature::doNamesMatch(x2y2, sameX2y2));
    EXPECT_FALSE(Feature::doNamesMatch(x2y2, x2));
    EXPECT_FALSE(Feature::doNamesMatch(x2y2, x1y2));
    EXPECT_TRUE(Feature::doNamesMatch(pieceOfX2y2, x2y2));
}

TEST_F(FeaturePartTest, doNamesMatchKeepsLinkInstancesApart)
{
    // Arrange
    //   pattern: a face of a box in another document, brought in by Links 7 and 8 (two
    //   instances of the box), ends in a boundary section with the Link's ID (ops#56); a fusion
    //   here splits a face by appending a MOD section of its own
    auto section = [](long tag, const char* op, const std::vector<std::string>& flags) {
        return std::string("|")
            + Data::MappedName::makeEncodedSection(
                   std::vector<std::string> {},
                   std::vector<Data::MappedName> {},
                   tag,
                   op,
                   0,
                   'F',
                   0,
                   flags,
                   std::vector<Data::MappedName> {}
            );
    };
    auto through = [&](const Data::MappedName& name, long link) {
        return Data::MappedName(name.toString() + section(link, OpCodes::External, {}));
    };
    auto boxFace = Data::MappedName::makeUnmappedName({"Face6"}, 1, "MKR", 'F');
    auto inLink7 = through(boxFace, 7);
    auto inLink8 = through(boxFace, 8);
    auto sameInLink7 = through(boxFace, 7);
    auto pieceInLink7
        = Data::MappedName(inLink7.toString() + section(10, OpCodes::Fuse, {"MOD"}));
    //   the box's face reached through Link 9, which links to Link 7 in a third document
    auto throughTwo = through(inLink7, 9);

    // Act and assert
    //   a copy is neither the box's own face nor the copy through another Link
    EXPECT_FALSE(Feature::doNamesMatch(inLink7, boxFace));
    EXPECT_FALSE(Feature::doNamesMatch(boxFace, inLink7));
    EXPECT_FALSE(Feature::doNamesMatch(inLink7, inLink8));
    EXPECT_FALSE(Feature::doNamesMatch(inLink7, inLink8, false, true));
    EXPECT_TRUE(Feature::doNamesMatch(inLink7, sameInLink7));
    //   a piece still matches the face it was split from, in its own copy only
    EXPECT_TRUE(Feature::doNamesMatch(pieceInLink7, inLink7));
    EXPECT_FALSE(Feature::doNamesMatch(pieceInLink7, inLink8));
    EXPECT_FALSE(Feature::doNamesMatch(pieceInLink7, boxFace));
    //   two boundaries are another path than either one
    auto inLink9 = through(boxFace, 9);
    auto sameThroughTwo = through(sameInLink7, 9);
    EXPECT_FALSE(Feature::doNamesMatch(throughTwo, inLink7));
    EXPECT_FALSE(Feature::doNamesMatch(throughTwo, inLink9));
    EXPECT_TRUE(Feature::doNamesMatch(throughTwo, sameThroughTwo));
}

TEST_F(FeaturePartTest, doNamesMatchKeepsSecondSidesApart)
{
    // Arrange
    //   PR 243 round 3: a two-sided Pad's second side is built from the profile again, and its
    //   names are the first side's followed by `_;_;<pad>;CPY;2;<type>;0;MOD;_`; a Revolution's
    //   second side carries that section on the profile's edge inside its face's name
    auto section = [](long tag,
                      const char* op,
                      int index,
                      char type,
                      const std::vector<std::string>& flags,
                      const std::vector<Data::MappedName>& linked = {}) {
        return Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            linked,
            tag,
            op,
            index,
            type,
            0,
            flags,
            std::vector<Data::MappedName> {}
        );
    };
    auto withSection = [&](const Data::MappedName& name, long tag, const char* op, int index) {
        return Data::MappedName(
            name.toString() + "|" + section(tag, op, index, 'E', {Data::MAPPER_FLAG_MODIFIED})
        );
    };
    auto profileEdge = Data::MappedName::makeUnmappedName({"g1"}, 5, "SKT", 'E');
    auto sideOne = Data::MappedName(section(7, "XTR", 0, 'E', {"GEN"}, {profileEdge}));
    auto sideTwo = withSection(sideOne, 7, OpCodes::Copy, 2);
    auto sameSideTwo = withSection(sideOne, 7, OpCodes::Copy, 2);
    //   a through-all Pocket clipping both sides' corners: the top section is its MOD on both
    auto clippedOne = withSection(sideOne, 9, OpCodes::Cut, 0);
    auto clippedTwo = withSection(sideTwo, 9, OpCodes::Cut, 0);
    //   a Revolution's faces from the profile edge and from its second-side copy
    auto profileCopy = withSection(profileEdge, 7, OpCodes::Copy, 2);
    auto revolvedOne = Data::MappedName(section(7, "RVL", 0, 'F', {"GEN"}, {profileEdge}));
    auto revolvedTwo = Data::MappedName(section(7, "RVL", 0, 'F', {"GEN"}, {profileCopy}));
    auto sameRevolvedTwo = Data::MappedName(section(7, "RVL", 0, 'F', {"GEN"}, {profileCopy}));

    // Act and assert
    //   a second side's element is not the first side's, either way, nor after a later split
    EXPECT_FALSE(Feature::doNamesMatch(sideTwo, sideOne));
    EXPECT_FALSE(Feature::doNamesMatch(sideOne, sideTwo));
    EXPECT_TRUE(Feature::doNamesMatch(sideTwo, sameSideTwo));
    EXPECT_FALSE(Feature::doNamesMatch(clippedTwo, clippedOne));
    EXPECT_FALSE(Feature::doNamesMatch(clippedOne, clippedTwo));
    EXPECT_TRUE(Feature::doNamesMatch(clippedTwo, sideTwo));
    EXPECT_TRUE(Feature::doNamesMatch(clippedOne, sideOne));
    //   nor through a linked name
    EXPECT_FALSE(Feature::doNamesMatch(revolvedTwo, revolvedOne));
    EXPECT_FALSE(Feature::doNamesMatch(revolvedOne, revolvedTwo));
    EXPECT_TRUE(Feature::doNamesMatch(revolvedTwo, sameRevolvedTwo));
}

TEST_F(FeaturePartTest, doNamesMatchKeepsBinderSupportsApart)
{
    // Arrange
    //   ops#112: a face of a box in each of two copies of one file (equal IDs, equal names),
    //   both bound by binder 7: the boundary sections carry the key of each support's file in
    //   the index
    auto through = [](const Data::MappedName& name, long binder, int key) {
        return Data::MappedName(
            name.toString() + "|"
            + Data::MappedName::makeEncodedSection(
                std::vector<std::string> {},
                std::vector<Data::MappedName> {},
                binder,
                OpCodes::External,
                key,
                'F',
                0,
                std::vector<std::string> {},
                std::vector<Data::MappedName> {}
            )
        );
    };
    auto boxFace = Data::MappedName::makeUnmappedName({"Face6"}, 1, "MKR", 'F');
    auto fromP1 = through(boxFace, 7, 111);
    auto fromP2 = through(boxFace, 7, 222);
    auto sameFromP1 = through(boxFace, 7, 111);

    // Act and assert
    EXPECT_FALSE(Feature::doNamesMatch(fromP1, fromP2));
    EXPECT_FALSE(Feature::doNamesMatch(fromP1, fromP2, false, true));
    EXPECT_TRUE(Feature::doNamesMatch(fromP1, sameFromP1));
    //   nor is either the copy through a Link with the binder's tag (index 0)
    auto throughLink = through(boxFace, 7, 0);
    EXPECT_FALSE(Feature::doNamesMatch(fromP1, throughLink));
}

TEST_F(FeaturePartTest, boundaryIndexOfDocuments)
{
    // ops#112 review: the key of a support's document as SubShapeBinder takes it
    // Arrange
    namespace fs = std::filesystem;
    const fs::path base = fs::temp_directory_path() / "BoundaryIndexDocuments";
    std::error_code error;
    fs::remove_all(base, error);
    fs::create_directories(base / "p1");
    auto& app = App::GetApplication();
    const std::string sourceName = app.getUniqueDocumentName("BoundarySource");
    auto source = app.newDocument(sourceName.c_str(), "testUser");
    const std::string otherName = app.getUniqueDocumentName("BoundaryOwner");
    auto otherOwner = app.newDocument(otherName.c_str(), "testUser");
    const auto sourceFile = Base::FileInfo::pathToString(base / "p1" / "Part.FCStd");
    const auto ownerFile = Base::FileInfo::pathToString(base / "Asm.FCStd");

    // Act and assert
    //   the binder's own document (a copy-on-change support): 0, as for a Link
    EXPECT_EQ(Part::boundaryIndex(*_doc, *_doc), "0");
    //   a source without a file: by its name, a number other than 0, whatever the owner
    const auto unsaved = Part::boundaryIndex(*_doc, *source);
    EXPECT_NE(unsaved, "0");
    EXPECT_EQ(unsaved, Part::boundaryIndex(*otherOwner, *source));
    //   a saved source and an owner without a file: by the source's absolute path, whatever
    //   the owner, and another key than its name gave
    ASSERT_TRUE(source->saveAs(sourceFile.c_str()));
    const auto absolute = Part::boundaryIndex(*_doc, *source);
    EXPECT_NE(absolute, unsaved);
    EXPECT_EQ(absolute, Part::boundaryIndex(*otherOwner, *source));
    //   both saved: the relative path, as the file-name form gives it
    ASSERT_TRUE(otherOwner->saveAs(ownerFile.c_str()));
    const auto relative = Part::boundaryIndex(*otherOwner, *source);
    EXPECT_EQ(relative, Part::boundaryIndex(ownerFile, sourceFile));
    EXPECT_NE(relative, absolute);

    app.closeDocument(sourceName.c_str());
    app.closeDocument(otherName.c_str());
    fs::remove_all(base, error);
}

TEST(BoundaryIndex, oneFileOneKey)
{
    // ops#112: Part::boundaryIndex() keys a binder's support by its file's path relative to the
    // owner's folder: one key for one file however its path is written, another for another
    // file, the same for the same layout anywhere. Files that don't exist are made canonical as
    // far as their folders exist.
    using Part::boundaryIndex;
#ifdef _WIN32
    const std::string root = "C:";
#else
    const std::string root;
#endif
    auto at = [&](const std::string& path) {
        return root + path;
    };
    const auto key = boundaryIndex(at("/a/Asm.FCStd"), at("/a/p1/Part.FCStd"));
    //   a decimal number
    ASSERT_FALSE(key.empty());
    EXPECT_TRUE(std::all_of(key.begin(), key.end(), [](char c) { return c >= '0' && c <= '9'; }));
    //   twins: one file name in two folders
    EXPECT_NE(key, boundaryIndex(at("/a/Asm.FCStd"), at("/a/p2/Part.FCStd")));
    //   the same layout elsewhere (the whole tree moved), up and down too
    EXPECT_EQ(key, boundaryIndex(at("/b/c/Asm.FCStd"), at("/b/c/p1/Part.FCStd")));
    EXPECT_EQ(
        boundaryIndex(at("/a/x/Asm.FCStd"), at("/a/p1/Part.FCStd")),
        boundaryIndex(at("/b/x/Asm.FCStd"), at("/b/p1/Part.FCStd"))
    );
    EXPECT_NE(key, boundaryIndex(at("/a/x/Asm.FCStd"), at("/a/p1/Part.FCStd")));
    //   the same file written another way
    EXPECT_EQ(key, boundaryIndex(at("/a/Asm.FCStd"), at("/a/x/../p1/./Part.FCStd")));
    EXPECT_EQ(key, boundaryIndex(at("/a/./Asm.FCStd"), at("/a//p1/Part.FCStd")));
    //   any case, on every platform: the same tree gives the same key on Windows and on macOS
    EXPECT_EQ(key, boundaryIndex(at("/A/asm.fcstd"), at("/a/P1/PART.FCStd")));
#ifdef _WIN32
    //   Windows: `\` separators, and the drive in either case
    EXPECT_EQ(key, boundaryIndex("C:\\a\\Asm.FCStd", "C:\\a\\p1\\Part.FCStd"));
    EXPECT_EQ(key, boundaryIndex("c:/a/Asm.FCStd", "C:/a/p1/Part.FCStd"));
    //   a source on another drive has no relative path: its absolute one, whatever the owner
    const auto other = boundaryIndex("C:/a/Asm.FCStd", "E:/x/Part.FCStd");
    EXPECT_EQ(other, boundaryIndex("C:/b/c/Asm.FCStd", "e:\\X\\part.FCStd"));
    EXPECT_NE(other, boundaryIndex("C:/a/Asm.FCStd", "C:/x/Part.FCStd"));
#endif

    //   links resolved: the owner's folder reached through a link to it (as macOS's /var is a
    //   link to /private/var), the source through the real folder
    namespace fs = std::filesystem;
    const fs::path base = fs::temp_directory_path() / "BoundaryIndexTest";
    std::error_code error;
    fs::remove_all(base, error);
    fs::create_directories(base / "real" / "p1");
    for (const auto& file : {base / "real" / "Asm.FCStd", base / "real" / "p1" / "Part.FCStd"}) {
        std::ofstream(file) << "x";
    }
    fs::create_directory_symlink(base / "real", base / "alias", error);
    const bool linked = !error;
    if (linked) {
        const auto real = boundaryIndex(
            Base::FileInfo::pathToString(base / "real" / "Asm.FCStd"),
            Base::FileInfo::pathToString(base / "real" / "p1" / "Part.FCStd")
        );
        EXPECT_EQ(
            real,
            boundaryIndex(
                Base::FileInfo::pathToString(base / "alias" / "Asm.FCStd"),
                Base::FileInfo::pathToString(base / "real" / "p1" / "Part.FCStd")
            )
        );
        EXPECT_EQ(
            real,
            boundaryIndex(
                Base::FileInfo::pathToString(base / "real" / "Asm.FCStd"),
                Base::FileInfo::pathToString(base / "alias" / "p1" / "Part.FCStd")
            )
        );
        //   a file not there yet, in a folder reached through the link
        EXPECT_EQ(
            boundaryIndex(
                Base::FileInfo::pathToString(base / "alias" / "New.FCStd"),
                Base::FileInfo::pathToString(base / "real" / "p1" / "Part.FCStd")
            ),
            real
        );
    }
    fs::remove_all(base, error);
    if (!linked) {
        GTEST_SKIP() << "no folder link here (Windows without the right to make one)";
    }
}

TEST_F(FeaturePartTest, matchSimilarNamesSeveralLooseMatchesAreAmbiguous)
{
    // Arrange
    //   pattern: ops#79's notch: two edges share one vertex ID with the old corner's edge
    auto corner = sideEdgeName({"g1v2", "g2v1"});
    std::vector<Data::MappedElement> elements {
        {sideEdgeName({"g1v2", "g5v1"}), Data::IndexedName("Edge", 2)},
        {sideEdgeName({"g2v1", "g8v2"}), Data::IndexedName("Edge", 14)},
        {sideEdgeName({"g3v2", "g4v1"}), Data::IndexedName("Edge", 5)},
    };
    bool ambiguous = false;

    // Act
    auto matches = Feature::matchSimilarNames(corner, elements, ambiguous);

    // Assert
    //   neither is taken: picking the first by bytes was the silent wrong pick
    EXPECT_TRUE(matches.empty());
    EXPECT_TRUE(ambiguous);
}

TEST_F(FeaturePartTest, matchSimilarNamesTakesTheOnlyLooseMatch)
{
    // Arrange
    //   pattern: a corner whose front line was deleted and redrawn: only the right line's ID
    //   survives, in one vertex
    auto corner = sideEdgeName({"g1v2", "g2v1"});
    std::vector<Data::MappedElement> elements {
        {sideEdgeName({"g2v1", "g8v2"}), Data::IndexedName("Edge", 14)},
        {sideEdgeName({"g3v2", "g4v1"}), Data::IndexedName("Edge", 5)},
    };
    bool ambiguous = true;

    // Act
    auto matches = Feature::matchSimilarNames(corner, elements, ambiguous);

    // Assert
    EXPECT_EQ(indexesOf(matches), std::vector<std::string> {"Edge14"});
    EXPECT_FALSE(ambiguous);
}

TEST_F(FeaturePartTest, matchSimilarNamesStrictMatchesHideLooseOnes)
{
    // Arrange
    //   pattern: the corner's vertex is still there (both IDs, listed in the other order), next
    //   to an edge that shares one ID with it
    auto corner = sideEdgeName({"g1v2", "g2v1"});
    std::vector<Data::MappedElement> elements {
        {sideEdgeName({"g1v2", "g5v1"}), Data::IndexedName("Edge", 2)},
        {sideEdgeName({"g2v1", "g1v2"}), Data::IndexedName("Edge", 9)},
    };
    bool ambiguous = true;

    // Act
    auto matches = Feature::matchSimilarNames(corner, elements, ambiguous);

    // Assert
    EXPECT_EQ(indexesOf(matches), std::vector<std::string> {"Edge9"});
    EXPECT_FALSE(ambiguous);
}

namespace
{
// Collects the warnings sent to the console while it is attached.
class WarningCollector final: public Base::ILogger
{
public:
    WarningCollector()
    {
        Base::Console().attachObserver(this);
    }
    ~WarningCollector() override
    {
        Base::Console().detachObserver(this);
    }
    WarningCollector(const WarningCollector&) = delete;
    WarningCollector(WarningCollector&&) = delete;
    WarningCollector& operator=(const WarningCollector&) = delete;
    WarningCollector& operator=(WarningCollector&&) = delete;

    void sendLog(
        const std::string& /*notifiername*/,
        const std::string& msg,
        Base::LogStyle level,
        Base::IntendedRecipient /*recipient*/,
        Base::ContentType /*content*/
    ) override
    {
        if (level == Base::LogStyle::Warning) {
            warnings.push_back(msg);
        }
    }
    const char* name() override
    {
        return "WarningCollector";
    }

    size_t count(const std::string& text) const
    {
        size_t found = 0;
        for (const auto& msg : warnings) {
            if (msg.find(text) != std::string::npos) {
                ++found;
            }
        }
        return found;
    }

    std::vector<std::string> warnings;
};

// A sketch face's name, and a piece of it: the name followed by a MOD section (ops#7).
Data::MappedName faceName(const std::string& geometryID)
{
    return Data::MappedName(Data::MappedName::makeEncodedSection(
        std::vector<std::string> {geometryID},
        std::vector<Data::MappedName> {},
        5,
        "SKT",
        0,
        'F',
        0,
        {Data::MAPPER_FLAG_SOURCE},
        std::vector<Data::MappedName> {}
    ));
}

Data::MappedName pieceName(const Data::MappedName& face, int index)
{
    return Data::MappedName(
        face.toString() + Data::NAME_SECTION_DELIMINATOR
        + Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            std::vector<Data::MappedName> {},
            6,
            "CUT",
            index,
            'F',
            0,
            {Data::MAPPER_FLAG_MODIFIED},
            std::vector<Data::MappedName> {}
        )
    );
}
}  // namespace

TEST_F(FeaturePartTest, referenceResolvedByOneOfSeveralNameMatchesWarnsV2)
{
    // Arrange
    //   pattern: a link to a named face of a box; the box is replaced by a moved one where two
    //   faces are pieces of that face, as when a cut splits it. Both names match strictly, the
    //   old face's shape is gone, so the reference takes the first piece: a guess (ops#20).
    ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V2);
    // The solver-off matcher, as in a file saved before the solver became the default for
    // new documents (ops#7 Q7): with the solver on, references skip it.
    _doc->ReferenceSolver.setValue(false);
    auto top = faceName("g1");
    TopoShape before(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    before.setElementName(Data::IndexedName("Face", 1), top, 7L);
    TopoShape after(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeBox(gp_Pnt(10.0, 0.0, 0.0), 1.0, 2.0, 3.0).Shape(),
        7L
    );
    after.setElementName(Data::IndexedName("Face", 2), pieceName(top, 1), 7L);
    after.setElementName(Data::IndexedName("Face", 3), pieceName(top, 2), 7L);
    auto source = _doc->addObject<Part::Feature>("Source");
    source->Shape.setValue(before);
    auto user = _doc->addObject<Part::Feature>("User");
    auto ref = freecad_cast<App::PropertyLinkSub*>(
        user->addDynamicProperty("App::PropertyLinkSub", "Ref")
    );
    ASSERT_NE(ref, nullptr);
    ref->setValue(source, std::vector<std::string> {"Face1"});
    ASSERT_EQ(ref->getSubValues(false), std::vector<std::string> {"Face1"});
    WarningCollector collector;

    // Act
    source->Shape.setValue(after);

    // Assert
    auto subs = ref->getSubValues(false);
    ASSERT_EQ(subs.size(), 1);
    EXPECT_TRUE(subs[0] == "Face2" || subs[0] == "Face3") << subs[0];
    EXPECT_EQ(collector.count("guessed element reference"), 1);
    EXPECT_EQ(collector.count("2 names match, the first was taken"), 1);
    EXPECT_EQ(collector.count("overrode the name match"), 0);
}

TEST_F(FeaturePartTest, referenceResolvedByGeometryOverAnotherNameMatchWarnsV2)
{
    // Arrange
    //   pattern: as above, but the box stays where it is: the old face is still Face1 under
    //   another name, and Face2's name matches the old one. The geometric search finds the old
    //   face's shape at Face1 and overrides the name match: a guess (ops#20).
    ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V2);
    // The solver-off matcher, as in a file saved before the solver became the default for
    // new documents (ops#7 Q7): with the solver on, references skip it.
    _doc->ReferenceSolver.setValue(false);
    auto top = faceName("g1");
    TopoShape before(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    before.setElementName(Data::IndexedName("Face", 1), top, 7L);
    TopoShape after(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    after.setElementName(Data::IndexedName("Face", 1), faceName("g9"), 7L);
    after.setElementName(Data::IndexedName("Face", 2), pieceName(top, 1), 7L);
    auto source = _doc->addObject<Part::Feature>("Source");
    source->Shape.setValue(before);
    auto user = _doc->addObject<Part::Feature>("User");
    auto ref = freecad_cast<App::PropertyLinkSub*>(
        user->addDynamicProperty("App::PropertyLinkSub", "Ref")
    );
    ASSERT_NE(ref, nullptr);
    ref->setValue(source, std::vector<std::string> {"Face1"});
    WarningCollector collector;

    // Act
    source->Shape.setValue(after);

    // Assert
    EXPECT_EQ(ref->getSubValues(false), std::vector<std::string> {"Face1"});
    EXPECT_EQ(collector.count("overrode the name match"), 1);
    EXPECT_EQ(collector.count("names match, the first was taken"), 0);
}

TEST_F(FeaturePartTest, referenceWithOneNameMatchDoesNotWarnV2)
{
    // Arrange
    //   control: the moved box has one piece of the old face, so the name match is the only
    //   candidate and nothing overrides it
    ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V2);
    // The solver-off matcher, as in a file saved before the solver became the default for
    // new documents (ops#7 Q7): with the solver on, references skip it.
    _doc->ReferenceSolver.setValue(false);
    auto top = faceName("g1");
    TopoShape before(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    before.setElementName(Data::IndexedName("Face", 1), top, 7L);
    TopoShape after(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeBox(gp_Pnt(10.0, 0.0, 0.0), 1.0, 2.0, 3.0).Shape(),
        7L
    );
    after.setElementName(Data::IndexedName("Face", 3), pieceName(top, 1), 7L);
    auto source = _doc->addObject<Part::Feature>("Source");
    source->Shape.setValue(before);
    auto user = _doc->addObject<Part::Feature>("User");
    auto ref = freecad_cast<App::PropertyLinkSub*>(
        user->addDynamicProperty("App::PropertyLinkSub", "Ref")
    );
    ASSERT_NE(ref, nullptr);
    ref->setValue(source, std::vector<std::string> {"Face1"});
    WarningCollector collector;

    // Act
    source->Shape.setValue(after);

    // Assert
    EXPECT_EQ(ref->getSubValues(false), std::vector<std::string> {"Face3"});
    EXPECT_EQ(collector.count("guessed element reference"), 0);
}

TEST_F(FeaturePartTest, referenceResolvedByOneOfSeveralGeometricMatchesWarnsV2)
{
    // Arrange
    //   pattern: a link to a named face of a box; the box is replaced by a compound of two copies
    //   of it, with no name like the old one. The geometric search finds the old face's shape
    //   twice and takes the first: a guess (ops#20)
    ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V2);
    // The solver-off matcher, as in a file saved before the solver became the default for
    // new documents (ops#7 Q7): with the solver on, references skip it.
    _doc->ReferenceSolver.setValue(false);
    auto top = faceName("g1");
    TopoDS_Shape box = BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape();
    TopoShape before(App::HistoryAlgorithm::V2, box, 7L);
    before.setElementName(Data::IndexedName("Face", 1), top, 7L);
    BRep_Builder builder;
    TopoDS_Compound twice;
    builder.MakeCompound(twice);
    builder.Add(twice, box);
    builder.Add(twice, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape());
    TopoShape after(App::HistoryAlgorithm::V2, twice, 7L);
    after.setElementName(Data::IndexedName("Face", 2), faceName("g9"), 7L);
    auto source = _doc->addObject<Part::Feature>("Source");
    source->Shape.setValue(before);
    auto user = _doc->addObject<Part::Feature>("User");
    auto ref = freecad_cast<App::PropertyLinkSub*>(
        user->addDynamicProperty("App::PropertyLinkSub", "Ref")
    );
    ASSERT_NE(ref, nullptr);
    ref->setValue(source, std::vector<std::string> {"Face1"});
    WarningCollector collector;

    // Act
    source->Shape.setValue(after);

    // Assert
    auto subs = ref->getSubValues(false);
    ASSERT_EQ(subs.size(), 1);
    EXPECT_TRUE(subs[0] == "Face1" || subs[0] == "Face7") << subs[0];
    EXPECT_EQ(collector.count("2 elements match the old geometry, the first was taken"), 1);
}

TEST_F(FeaturePartTest, referenceWhoseNameMatchGeometryConfirmsDoesNotWarnV2)
{
    // Arrange
    //   control: the box stays where it is and its Face1 is now a piece of the old face, so the
    //   name match and the geometric search agree
    ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V2);
    // The solver-off matcher, as in a file saved before the solver became the default for
    // new documents (ops#7 Q7): with the solver on, references skip it.
    _doc->ReferenceSolver.setValue(false);
    auto top = faceName("g1");
    TopoShape before(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    before.setElementName(Data::IndexedName("Face", 1), top, 7L);
    TopoShape after(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    after.setElementName(Data::IndexedName("Face", 1), pieceName(top, 1), 7L);
    auto source = _doc->addObject<Part::Feature>("Source");
    source->Shape.setValue(before);
    auto user = _doc->addObject<Part::Feature>("User");
    auto ref = freecad_cast<App::PropertyLinkSub*>(
        user->addDynamicProperty("App::PropertyLinkSub", "Ref")
    );
    ASSERT_NE(ref, nullptr);
    ref->setValue(source, std::vector<std::string> {"Face1"});
    WarningCollector collector;

    // Act
    source->Shape.setValue(after);

    // Assert
    EXPECT_EQ(ref->getSubValues(false), std::vector<std::string> {"Face1"});
    EXPECT_EQ(collector.count("guessed element reference"), 0);
}

TEST_F(FeaturePartTest, linksKeepTheSourcesNamesV2)
{
    // Arrange
    //   pattern: an object holds a shape whose face is new and untagged (last section's tag 0),
    //   built from a wire (tag 7). setValue() keeps the names of a shape that has a tag, so C++
    //   code can store such a shape. Link arrays and their elements take copies of the object's
    //   shape, which share its element map, and retag them (ops#34).
    ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V2);
    //   plain names, compared as text: new documents are interned since ops#6's Q6
    _doc->InternNames.setValue(false);
    Data::IndexedName edge1("Edge", 1);
    Data::IndexedName face1("Face", 1);
    auto edgeName = Data::MappedName::makeUnmappedName({"Edge1"}, 7, "RTG", 'E');
    //   the second of two equal names gets duplicate count 1
    auto faceNameWithTag = [&](long tag, int duplicate = 0) {
        return Data::MappedName::makeEncodedSection(
            std::vector<std::string> {},
            std::vector<Data::MappedName> {edgeName},
            tag,
            "RTG",
            0,
            'F',
            duplicate,
            {Data::MAPPER_FLAG_GENERATED},
            std::vector<Data::MappedName> {}
        );
    };
    TopoShape shape(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    shape.setElementName(edge1, edgeName, 0);
    shape.setElementName(face1, Data::MappedName(faceNameWithTag(0)), 0);
    auto source = _doc->addObject<Part::Feature>("Source");
    source->Shape.setValue(shape);
    ASSERT_EQ(source->Shape.getShape().getMappedName(face1).toString(), faceNameWithTag(0));
    auto link = _doc->addObject<App::Link>("Link");
    link->setLink(-1, source);
    auto array = _doc->addObject<App::Link>("Array");
    array->setLink(-1, source);
    array->ElementCount.setValue(2);
    auto hiddenArray = _doc->addObject<App::Link>("HiddenArray");
    hiddenArray->setLink(-1, source);
    hiddenArray->ShowElement.setValue(false);
    hiddenArray->ElementCount.setValue(2);
    _doc->recompute();

    // Act
    auto linkShape = Feature::getTopoShape(link, ShapeOption::ResolveLink | ShapeOption::Transform);
    auto arrayShape = Feature::getTopoShape(array, ShapeOption::ResolveLink | ShapeOption::Transform);
    auto hiddenArrayShape
        = Feature::getTopoShape(hiddenArray, ShapeOption::ResolveLink | ShapeOption::Transform);

    // Assert
    //   the source's names are its own: no link's tag reaches them
    const TopoShape& sourceShape = source->Shape.getShape();
    EXPECT_EQ(sourceShape.getMappedName(face1).toString(), faceNameWithTag(0));
    EXPECT_EQ(sourceShape.getMappedName(edge1), edgeName);
    //   a plain link keys its copy by its ID: a link copy section (ops#523)
    auto copy = [](long tag, const std::string& index) {
        return std::string(Data::NAME_SECTION_DELIMINATOR) + "_;_;" + std::to_string(tag)
            + ";CPY;" + index + ";F;0;MOD;_";
    };
    EXPECT_EQ(
        linkShape.getMappedName(face1).toString(),
        faceNameWithTag(link->getID()) + copy(link->getID(), "L")
    );
    //   an array's elements are keyed by the array and their numbers, whether it shows them as
    //   objects or not (the box has 6 faces: the second element's first face is Face7)
    auto elements = array->ElementList.getValues();
    ASSERT_EQ(elements.size(), 2);
    Data::IndexedName face7("Face", 7);
    EXPECT_EQ(
        arrayShape.getMappedName(face1).toString(),
        faceNameWithTag(array->getID()) + copy(array->getID(), "L0")
    );
    EXPECT_EQ(
        arrayShape.getMappedName(face7).toString(),
        faceNameWithTag(array->getID()) + copy(array->getID(), "L1")
    );
    EXPECT_EQ(
        hiddenArrayShape.getMappedName(face1).toString(),
        faceNameWithTag(hiddenArray->getID()) + copy(hiddenArray->getID(), "L0")
    );
    EXPECT_EQ(
        hiddenArrayShape.getMappedName(face7).toString(),
        faceNameWithTag(hiddenArray->getID()) + copy(hiddenArray->getID(), "L1")
    );
    //   an element taken as an object (its LinkElement) has the array's names for it
    auto elementShape
        = Feature::getTopoShape(elements[1], ShapeOption::ResolveLink | ShapeOption::Transform);
    EXPECT_EQ(
        elementShape.getMappedName(face1).toString(),
        faceNameWithTag(array->getID()) + copy(array->getID(), "L1")
    );
}

TEST_F(FeaturePartTest, linkArrayElementsKeepTheirNamesV2)
{
    // ops#523 (Fable review finding 2): toggling ShowElement, a hidden element, or the count
    // going down and up again renames no element of a link array
    // Arrange
    _doc->InternNames.setValue(false);
    auto box = _doc->addObject<Part::Box>("Box");
    auto array = _doc->addObject<App::Link>("Array");
    array->setLink(-1, box);
    array->ElementCount.setValue(3);
    _doc->recompute();
    auto names = [&]() {
        auto shape = Feature::getTopoShape(array, ShapeOption::ResolveLink | ShapeOption::Transform);
        std::vector<std::string> result;
        for (int i = 1; i <= static_cast<int>(shape.countSubElements("Face")); ++i) {
            result.push_back(shape.getMappedName(Data::IndexedName("Face", i)).toString());
        }
        return result;
    };
    const auto shown = names();
    ASSERT_EQ(shown.size(), 18);
    const std::string arrayKey = std::string(Data::NAME_SECTION_DELIMINATOR) + "_;_;"
        + std::to_string(array->getID()) + ";CPY;";
    EXPECT_NE(shown[0].find(arrayKey + "L0;"), std::string::npos) << shown[0];
    EXPECT_NE(shown[6].find(arrayKey + "L1;"), std::string::npos) << shown[6];
    EXPECT_NE(shown[12].find(arrayKey + "L2;"), std::string::npos) << shown[12];

    // Act and assert
    //   ShowElement off and on again
    array->ShowElement.setValue(false);
    _doc->recompute();
    EXPECT_EQ(names(), shown);
    array->ShowElement.setValue(true);
    _doc->recompute();
    EXPECT_EQ(names(), shown);
    //   element 0 hidden: elements 1 and 2 keep their names
    array->setElementVisible("0", false);
    _doc->recompute();
    const auto withoutFirst = names();
    EXPECT_EQ(withoutFirst, std::vector<std::string>(shown.begin() + 6, shown.end()));
    array->setElementVisible("0", true);
    _doc->recompute();
    //   the count down and up again (new LinkElements)
    array->ElementCount.setValue(1);
    _doc->recompute();
    array->ElementCount.setValue(3);
    _doc->recompute();
    EXPECT_EQ(names(), shown);
}

TEST_F(FeaturePartTest, linkCopiesOfOneObjectHaveTheirOwnNamesV2)
{
    // ops#523: two links to one object in a fuse give its elements names that differ only by
    // their link copy sections, for a source without an element map (a primitive) and one with
    // (an extrusion). The source's own names don't change.
    // Arrange
    _doc->InternNames.setValue(false);
    auto cylinder = _doc->addObject<Part::Cylinder>("Cylinder");
    auto plane = _doc->addObject<Part::Plane>("Plane");
    plane->Length.setValue(10.0);  // the copies 20 apart don't touch
    plane->Width.setValue(10.0);
    auto extrusion = _doc->addObject<Part::Extrusion>("Extrusion");
    extrusion->Base.setValue(plane);
    extrusion->DirMode.setValue("Custom");
    extrusion->Dir.setValue(Base::Vector3d(0, 0, 1));
    extrusion->LengthFwd.setValue(2.0);
    _doc->recompute();
    for (App::DocumentObject* source : std::vector<App::DocumentObject*> {cylinder, extrusion}) {
        auto copy0 = _doc->addObject<App::Link>("Copy0");
        copy0->setLink(-1, source);
        auto copy1 = _doc->addObject<App::Link>("Copy1");
        copy1->setLink(-1, source);
        copy1->Placement.setValue(Base::Placement(Base::Vector3d(20, 0, 0), Base::Rotation()));
        _doc->recompute();
        const auto sourceShape = Feature::getTopoShape(source, ShapeOption::ResolveLink);
        const auto shape0 = Feature::getTopoShape(copy0, ShapeOption::ResolveLink | ShapeOption::Transform);
        const auto shape1 = Feature::getTopoShape(copy1, ShapeOption::ResolveLink | ShapeOption::Transform);
        ASSERT_EQ(shape0.countSubElements("Edge"), shape1.countSubElements("Edge"));

        // Act and assert
        auto copyOf = [](long tag) {
            return std::string(Data::NAME_SECTION_DELIMINATOR) + "_;_;" + std::to_string(tag)
                + ";CPY;L;";
        };
        for (int i = 1; i <= static_cast<int>(shape0.countSubElements("Edge")); ++i) {
            Data::IndexedName edge("Edge", i);
            const auto name0 = shape0.getMappedName(edge).toString();
            const auto name1 = shape1.getMappedName(edge).toString();
            const auto at0 = name0.rfind(copyOf(copy0->getID()));
            const auto at1 = name1.rfind(copyOf(copy1->getID()));
            ASSERT_NE(at0, std::string::npos) << name0;
            ASSERT_NE(at1, std::string::npos) << name1;
            //   the same name before the section: the source's, retagged by the link
            EXPECT_EQ(name0.substr(0, at0), name1.substr(0, at1));
            EXPECT_TRUE(Data::isCounterSiblingName(name0, name1));
        }
        //   the source's own names keep no link's section
        for (int i = 1; i <= static_cast<int>(sourceShape.countSubElements("Edge")); ++i) {
            const auto name = sourceShape.getMappedName(Data::IndexedName("Edge", i)).toString();
            EXPECT_EQ(name.find(";CPY;L"), std::string::npos) << name;
        }

        //   in a fuse, each copy's elements keep their link's key: no name told apart only by
        //   the collision counter
        auto fuse = _doc->addObject<Part::MultiFuse>("Fuse");
        fuse->Shapes.setValues({copy0, copy1});
        _doc->recompute();
        const auto fused = fuse->Shape.getShape();
        int keyed0 = 0;
        int keyed1 = 0;
        for (int i = 1; i <= static_cast<int>(fused.countSubElements("Edge")); ++i) {
            const auto name = fused.getMappedName(Data::IndexedName("Edge", i)).toString();
            keyed0 += name.find(copyOf(copy0->getID())) != std::string::npos ? 1 : 0;
            keyed1 += name.find(copyOf(copy1->getID())) != std::string::npos ? 1 : 0;
        }
        EXPECT_EQ(keyed0, static_cast<int>(shape0.countSubElements("Edge")));
        EXPECT_EQ(keyed1, static_cast<int>(shape1.countSubElements("Edge")));
    }
}

TEST_F(FeaturePartTest, linkCopyPostfix)
{
    // ops#523: the retag postfix of a shape a link hands over
    // Arrange
    auto& app = App::GetApplication();
    const std::string otherName = app.getUniqueDocumentName("LinkCopyOther");
    auto other = app.newDocument(otherName.c_str(), "testUser");
    auto box = _doc->addObject<Part::Box>("Box");
    auto link = _doc->addObject<App::Link>("Link");
    auto array = _doc->addObject<App::Link>("Array");
    array->setLink(-1, box);
    array->ElementCount.setValue(2);
    auto there = other->addObject<App::Link>("There");
    _doc->recompute();
    const std::string linkCopy(Data::POSTFIX_LINK_COPY);
    const std::string index(Data::POSTFIX_INDEX);

    // Act and assert
    //   within one document: the link copy postfix, the element's number after it
    const App::DocumentObject* obj = link;
    EXPECT_EQ(App::LinkBaseExtension::copyPostfix(obj, box, nullptr), linkCopy);
    EXPECT_EQ(obj, link);
    EXPECT_EQ(App::LinkBaseExtension::copyPostfix(obj, box, (index + "3").c_str()), linkCopy + index + "3");
    //   across documents: the external postfix, as before, with an element's number
    obj = there;
    EXPECT_EQ(App::LinkBaseExtension::copyPostfix(obj, box, nullptr), Data::POSTFIX_EXTERNAL_TAG);
    EXPECT_EQ(
        App::LinkBaseExtension::copyPostfix(obj, box, (index + "1").c_str()),
        std::string(Data::POSTFIX_EXTERNAL_TAG) + index + "1"
    );
    //   an array's element shown as an object: the array and the element's number
    auto elements = array->ElementList.getValues();
    ASSERT_EQ(elements.size(), 2);
    obj = elements[1];
    EXPECT_EQ(App::LinkBaseExtension::copyPostfix(obj, box, nullptr), linkCopy + index + "1");
    EXPECT_EQ(obj, array);

    app.closeDocument(otherName.c_str());
}

TEST_F(FeaturePartTest, setValueNamesAnotherObjectsShapeWithoutMapV2)
{
    // Arrange
    //   pattern: an object takes another object's shape (tag 7) that has no element map, as a
    //   Body takes its tip's (ops#35)
    TopoShape shape(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    ASSERT_EQ(shape.getElementMapSize(), 0);
    auto feature = _doc->addObject<Part::Feature>("Feature");

    // Act
    feature->Shape.setValue(shape);

    // Assert
    //   every element has the name mapSubElement() gives an element of a shape without a map:
    //   '<element>;_;7;MKR;0;<type>;0;IDX,SRC;_'
    const TopoShape& result = feature->Shape.getShape();
    EXPECT_EQ(result.Tag, feature->getID());
    for (const char* type : {"Face", "Edge", "Vertex"}) {
        const auto count = static_cast<int>(result.countSubElements(type));
        for (int index = 1; index <= count; ++index) {
            Data::IndexedName element(type, index);
            EXPECT_EQ(
                result.getMappedName(element),
                Data::MappedName::makeUnmappedName({element.toString()}, 7, "MKR", type[0])
            );
        }
    }
    EXPECT_EQ(result.getElementMapSize(), 26);
    //   the shape it was given still has no names
    EXPECT_EQ(shape.getElementMapSize(), 0);
}

TEST_F(FeaturePartTest, setValueNamesAShapeWithoutMapInTheDocumentsAlgorithmV1)
{
    // Arrange
    //   pattern: in a V1 document, an object takes another object's shape (tag 7) that has no
    //   element map and the V2 algorithm, as a Body takes a helix's result (ops#35)
    _doc->HistoryAlgorithm.setValue("V1");
    ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V1);
    TopoShape shape(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    auto feature = _doc->addObject<Part::Feature>("Feature");

    // Act
    feature->Shape.setValue(shape);

    // Assert
    //   the result is V1, and every element has a V1 name under the other object's tag:
    //   '<element>;:H7,<type>'
    const TopoShape& result = feature->Shape.getShape();
    EXPECT_EQ(result.getHistoryAlgorithm(), App::HistoryAlgorithm::V1);
    for (const char* type : {"Face", "Edge", "Vertex"}) {
        const auto count = static_cast<int>(result.countSubElements(type));
        for (int index = 1; index <= count; ++index) {
            Data::IndexedName element(type, index);
            EXPECT_EQ(result.getMappedName(element).toString(), element.toString() + ";:H7," + type[0]);
        }
    }
    EXPECT_EQ(result.getElementMapSize(), 26);
    //   the shape it was given keeps its algorithm
    EXPECT_EQ(shape.getHistoryAlgorithm(), App::HistoryAlgorithm::V2);
}

// Fingerprints for the reference solver (ops#7): the geometry of an element in the shape's own
// coordinates, without its placement.

TEST_F(FeaturePartTest, fingerprintsOfABox)
{
    // Arrange
    //   a 1 x 2 x 3 box at the origin
    TopoShape box(BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape());
    const Base::Vector3d middle(0.5, 1.0, 1.5);

    // Act and assert
    for (int index = 1; index <= 6; ++index) {
        Data::ElementFingerprint fp;
        ASSERT_TRUE(Feature::getElementFingerprint(box, ("Face" + std::to_string(index)).c_str(), fp));
        EXPECT_EQ(fp.type, 'F');
        EXPECT_EQ(fp.kind, "Plane");
        ASSERT_TRUE(fp.direction && fp.center && fp.size);
        //   the normal points out of the box: the face's orientation is taken into account
        EXPECT_GT((*fp.center - middle) * *fp.direction, 0.4) << index;
        EXPECT_NEAR(fp.direction->Length(), 1.0, 1e-12);
        //   the area is the product of the two dimensions the normal doesn't cross
        const auto& n = *fp.direction;
        double area = std::abs(n.x) > 0.5 ? 6.0 : std::abs(n.y) > 0.5 ? 3.0 : 2.0;
        EXPECT_NEAR(*fp.size, area, 1e-9) << index;
        EXPECT_TRUE(fp.radii.empty());
    }
    for (int index = 1; index <= 12; ++index) {
        Data::ElementFingerprint fp;
        ASSERT_TRUE(Feature::getElementFingerprint(box, ("Edge" + std::to_string(index)).c_str(), fp));
        EXPECT_EQ(fp.type, 'E');
        EXPECT_EQ(fp.kind, "Line");
        ASSERT_TRUE(fp.direction && fp.size && fp.center);
        //   an axis direction, sign-normalized: one component is 1, the others 0
        const auto& d = *fp.direction;
        EXPECT_NEAR(std::max({d.x, d.y, d.z}), 1.0, 1e-12) << index;
        double length = d.x > 0.5 ? 1.0 : d.y > 0.5 ? 2.0 : 3.0;
        EXPECT_NEAR(*fp.size, length, 1e-9) << index;
    }
    //   the vertices are the eight corners
    std::set<std::string> corners;
    for (int index = 1; index <= 8; ++index) {
        Data::ElementFingerprint vertex;
        ASSERT_TRUE(
            Feature::getElementFingerprint(box, ("Vertex" + std::to_string(index)).c_str(), vertex)
        );
        corners.insert(vertex.toString());
    }
    std::set<std::string> expectedCorners;
    for (int x : {0, 1}) {
        for (int y : {0, 2}) {
            for (int z : {0, 3}) {
                expectedCorners.insert(
                    "1|V|Point|_|" + std::to_string(x) + "," + std::to_string(y) + ","
                    + std::to_string(z) + "|_|_"
                );
            }
        }
    }
    EXPECT_EQ(corners, expectedCorners);
    //   unknown elements
    Data::ElementFingerprint none;
    EXPECT_FALSE(Feature::getElementFingerprint(box, "Face7", none));
    EXPECT_FALSE(Feature::getElementFingerprint(box, "Bogus1", none));
    EXPECT_FALSE(Feature::getElementFingerprint(TopoShape(), "Face1", none));
    EXPECT_FALSE(none.isValid());
}

namespace
{

// A fingerprint's bounding box, within 1e-7 of the given corners
void expectExtent(
    const Data::ElementFingerprint& fp,
    const Base::Vector3d& low,
    const Base::Vector3d& high
)
{
    ASSERT_TRUE(fp.extentMin && fp.extentMax) << fp.toString();
    EXPECT_LT(Base::Distance(*fp.extentMin, low), 1e-7) << fp.toString();
    EXPECT_LT(Base::Distance(*fp.extentMax, high), 1e-7) << fp.toString();
}

// Every point at radius 2 from the z axis, at height z (PR 366 round 5)
void expectOnCircle(const std::vector<Base::Vector3d>& points, double z)
{
    ASSERT_FALSE(points.empty());
    for (const auto& point : points) {
        EXPECT_NEAR(std::hypot(point.x, point.y), 2.0, 1e-9);
        EXPECT_NEAR(point.z, z, 1e-9);
    }
}

}  // namespace

TEST_F(FeaturePartTest, fingerprintsOfACylinder)
{
    // Arrange
    //   radius 2, height 5, on the z axis
    TopoShape cylinder(BRepPrimAPI_MakeCylinder(2.0, 5.0).Shape());
    int lateral = 0;
    int planes = 0;
    int circles = 0;
    int seams = 0;

    // Act and assert
    for (int index = 1; index <= static_cast<int>(cylinder.countSubShapes(TopAbs_FACE)); ++index) {
        Data::ElementFingerprint fp;
        ASSERT_TRUE(
            Feature::getElementFingerprint(cylinder, ("Face" + std::to_string(index)).c_str(), fp)
        );
        if (fp.kind == "Cylinder") {
            ++lateral;
            //   with its bounding box, in version 5 (PR 366 round 4)
            EXPECT_EQ(fp.toString().substr(0, 45), "5|F|Cylinder|62.8318530718|0,0,2.5|0,0,1|2|_|");
            expectExtent(fp, Base::Vector3d(-2, -2, 0), Base::Vector3d(2, 2, 5));
        }
        else {
            ++planes;
            EXPECT_EQ(fp.kind, "Plane");
            ASSERT_TRUE(fp.center && fp.direction);
            //   top faces up, bottom faces down
            EXPECT_DOUBLE_EQ(fp.direction->z, fp.center->z > 2.5 ? 1.0 : -1.0);
            EXPECT_NEAR(*fp.size, 4.0 * std::numbers::pi, 1e-9);
            const double z = fp.center->z;
            expectExtent(fp, Base::Vector3d(-2, -2, z), Base::Vector3d(2, 2, z));
            //   its outline (PR 366 round 5): points of its circle, convex round it
            expectOnCircle(fp.outline, z);
            EXPECT_GE(fp.outline.size(), 8u);
        }
    }
    for (int index = 1; index <= static_cast<int>(cylinder.countSubShapes(TopAbs_EDGE)); ++index) {
        Data::ElementFingerprint fp;
        ASSERT_TRUE(
            Feature::getElementFingerprint(cylinder, ("Edge" + std::to_string(index)).c_str(), fp)
        );
        if (fp.kind == "Circle") {
            ++circles;
            ASSERT_TRUE(fp.center);
            EXPECT_EQ(fp.radii, std::vector<double> {2.0});
            EXPECT_EQ(*fp.direction, Base::Vector3d(0, 0, 1));
            EXPECT_NEAR(*fp.size, 4.0 * std::numbers::pi, 1e-9);
            //   a full circle's centre of mass is its centre
            EXPECT_NEAR(fp.center->x, 0.0, 1e-9);
            EXPECT_NEAR(fp.center->y, 0.0, 1e-9);
            //   a circle carries its centre (Task 2 PR 7b), and its box, in version 5
            ASSERT_TRUE(fp.location);
            EXPECT_NEAR(Base::Distance(*fp.location, *fp.center), 0.0, 1e-9);
            EXPECT_EQ(fp.toString().substr(0, 11), "5|E|Circle|");
            const double z = fp.center->z;
            expectExtent(fp, Base::Vector3d(-2, -2, z), Base::Vector3d(2, 2, z));
            //   its outline: 17 points along it, its ends on its vertex
            expectOnCircle(fp.outline, z);
            ASSERT_EQ(fp.outline.size(), 17u);
            EXPECT_LT(Base::Distance(fp.outline.front(), fp.outline.back()), 1e-9);
        }
        else {
            ++seams;
            EXPECT_EQ(fp.toString().substr(0, 29), "5|E|Line|5|2,0,2.5|0,0,1|_|_|");
            expectExtent(fp, Base::Vector3d(2, 0, 0), Base::Vector3d(2, 0, 5));
            //   a line's outline: its two ends
            ASSERT_EQ(fp.outline.size(), 2u);
            EXPECT_NEAR(std::abs(fp.outline[0].z - fp.outline[1].z), 5.0, 1e-9);
            for (const auto& point : fp.outline) {
                EXPECT_LT(Base::Distance(Base::Vector3d(2, 0, point.z), point), 1e-9);
            }
        }
    }
    EXPECT_EQ(lateral, 1);
    EXPECT_EQ(planes, 2);
    EXPECT_EQ(circles, 2);
    EXPECT_EQ(seams, 1);
}

TEST_F(FeaturePartTest, fingerprintOfAnArcLocatesItsCircle)
{
    // Arrange
    //   a quarter cylinder, radius 2, height 5: its arcs run from 0 to 90 degrees
    TopoShape quarter(BRepPrimAPI_MakeCylinder(2.0, 5.0, std::numbers::pi / 2).Shape());
    int arcs = 0;

    // Act and assert
    for (int index = 1; index <= static_cast<int>(quarter.countSubShapes(TopAbs_EDGE)); ++index) {
        Data::ElementFingerprint fp;
        ASSERT_TRUE(
            Feature::getElementFingerprint(quarter, ("Edge" + std::to_string(index)).c_str(), fp)
        );
        if (fp.kind != "Circle") {
            EXPECT_FALSE(fp.location) << fp.toString();
            continue;
        }
        ++arcs;
        ASSERT_TRUE(fp.location && fp.center);
        //   the location is the circle's centre; the centre of mass lies off it, on the bisector
        EXPECT_NEAR(fp.location->x, 0.0, 1e-9);
        EXPECT_NEAR(fp.location->y, 0.0, 1e-9);
        EXPECT_NEAR(fp.location->z, fp.center->z, 1e-9);
        const double half = std::numbers::pi / 4;
        const double offset = 2.0 * std::sin(half) / half;
        EXPECT_NEAR(fp.center->x, offset * std::cos(half), 1e-9);
        EXPECT_NEAR(fp.center->y, offset * std::sin(half), 1e-9);
        auto parsed = Data::ElementFingerprint::fromString(fp.toString());
        EXPECT_EQ(parsed.location.has_value(), true);
    }
    EXPECT_EQ(arcs, 2);
}

TEST_F(FeaturePartTest, fingerprintsOfAnLHaveAPointInside)
{
    // Arrange
    //   the L x 0.5..2.5, y 0.5..2.5 without x 1..2.5, y 1..2.5 at z = 10 (PR 366 round 6): its
    //   centre (1.18, 1.18) lies outside it; and the square x 0..2, y 0..2
    auto face = [](const std::vector<gp_Pnt>& corners) {
        BRepBuilderAPI_MakePolygon polygon;
        for (const auto& corner : corners) {
            polygon.Add(corner);
        }
        polygon.Close();
        return TopoShape(BRepBuilderAPI_MakeFace(polygon.Wire()).Face());
    };
    const TopoShape lFace = face(
        {gp_Pnt(0.5, 0.5, 10),
         gp_Pnt(2.5, 0.5, 10),
         gp_Pnt(2.5, 1, 10),
         gp_Pnt(1, 1, 10),
         gp_Pnt(1, 2.5, 10),
         gp_Pnt(0.5, 2.5, 10)}
    );
    const TopoShape square = face(
        {gp_Pnt(0, 0, 10), gp_Pnt(2, 0, 10), gp_Pnt(2, 2, 10), gp_Pnt(0, 2, 10)}
    );

    // Act
    Data::ElementFingerprint lPrint;
    Data::ElementFingerprint squarePrint;
    ASSERT_TRUE(Feature::getElementFingerprint(lFace, "Face1", lPrint));
    ASSERT_TRUE(Feature::getElementFingerprint(square, "Face1", squarePrint));

    // Assert
    //   the L's point lies in the L, half its arm's width from its sides at most; its text keeps it
    ASSERT_TRUE(lPrint.inside) << lPrint.toString();
    const Base::Vector3d& point = *lPrint.inside;
    EXPECT_NEAR(point.z, 10.0, 1e-9);
    EXPECT_TRUE(point.x >= 0.5 && point.y >= 0.5 && (point.x <= 1 || point.y <= 1))
        << point.x << "," << point.y;
    EXPECT_GT(std::min({point.x - 0.5, point.y - 0.5}), 0.1) << point.x << "," << point.y;
    const auto parsed = Data::ElementFingerprint::fromString(lPrint.toString());
    ASSERT_TRUE(parsed.inside) << lPrint.toString();
    EXPECT_LT(Base::Distance(*parsed.inside, point), 1e-9);
    //   a square's centre is inside it: no point, and no twelfth field
    EXPECT_FALSE(squarePrint.inside);
    const std::string squareText = squarePrint.toString();
    EXPECT_EQ(std::count(squareText.begin(), squareText.end(), '|'), 10) << squareText;

    // Round 7: the L x 0.9..2.9, y 0.9..2.9 without x 0.9 + w..2.9, y 0.9 + w..2.9, its arms w
    // wide: 0.1 and 0.03 have no centre of the 9 x 9 grid in them (the first sits 0.11 in), 0.1
    // has one of the 27 x 27 grid's (0.037 in), 0.03 one of the 81 x 81 grid's (0.012 in). Its
    // point lies in an arm. Arms 0.005 wide have none even then: no point, and no twelfth field
    for (const double w : {0.1, 0.03, 0.005}) {
        const double a = 0.9 + w;
        const TopoShape thin = face(
            {gp_Pnt(0.9, 0.9, 10),
             gp_Pnt(2.9, 0.9, 10),
             gp_Pnt(2.9, a, 10),
             gp_Pnt(a, a, 10),
             gp_Pnt(a, 2.9, 10),
             gp_Pnt(0.9, 2.9, 10)}
        );
        Data::ElementFingerprint thinPrint;
        ASSERT_TRUE(Feature::getElementFingerprint(thin, "Face1", thinPrint));
        const std::string text = thinPrint.toString();
        if (w < 0.01) {
            EXPECT_FALSE(thinPrint.inside) << w << ": " << text;
            EXPECT_EQ(std::count(text.begin(), text.end(), '|'), 10) << text;
            continue;
        }
        ASSERT_TRUE(thinPrint.inside) << w << ": " << text;
        const Base::Vector3d& in = *thinPrint.inside;
        EXPECT_NEAR(in.z, 10.0, 1e-9);
        EXPECT_TRUE(in.x > 0.9 && in.y > 0.9 && (in.x < a || in.y < a))
            << w << ": " << in.x << "," << in.y;
    }
}

TEST_F(FeaturePartTest, fingerprintsIgnoreThePlacement)
{
    // Arrange
    //   the same box, at the origin and moved and turned
    _boxes[0]->recomputeFeature();
    std::vector<std::string> before;
    for (const char* element : {"Face1", "Face6", "Edge3", "Edge12", "Vertex5"}) {
        Data::ElementFingerprint fp;
        ASSERT_TRUE(_boxes[0]->getElementFingerprint(element, fp));
        before.push_back(fp.toString());
    }

    // Act
    _boxes[0]->Placement.setValue(
        Base::Placement(Base::Vector3d(10, -4, 7), Base::Rotation(Base::Vector3d(1, 1, 0), 0.7))
    );
    _boxes[0]->recomputeFeature();

    // Assert
    std::size_t i = 0;
    for (const char* element : {"Face1", "Face6", "Edge3", "Edge12", "Vertex5"}) {
        Data::ElementFingerprint fp;
        ASSERT_TRUE(_boxes[0]->getElementFingerprint(element, fp));
        EXPECT_EQ(fp.toString(), before[i++]) << element;
    }
    //   the shape itself did move
    EXPECT_FALSE(_boxes[0]->Shape.getShape().getPlacement().isIdentity());
}

namespace
{

// Every face, edge and vertex fingerprint of \a shape, as text, in index order.
std::vector<std::string> allFingerprints(const TopoShape& shape)
{
    std::vector<std::string> result;
    for (const char* type : {"Face", "Edge", "Vertex"}) {
        const auto count = static_cast<int>(shape.countSubElements(type));
        for (int index = 1; index <= count; ++index) {
            Data::ElementFingerprint fp;
            const std::string element = type + std::to_string(index);
            EXPECT_TRUE(Feature::getElementFingerprint(shape, element.c_str(), fp)) << element;
            result.push_back(element + " " + fp.toString());
        }
    }
    return result;
}

}  // namespace

TEST_F(FeaturePartTest, fingerprintsThroughTheCachedShapeEqualAFreshCopy)
{
    // Arrange
    //   a box and a cylinder in a compound, the cylinder placed inside it, so its sub-shapes carry
    //   a location of their own; then the compound itself moved and turned
    gp_Trsf inner;
    inner.SetTranslation(gp_Vec(5, 1, 0));
    TopoDS_Shape cylinder = BRepPrimAPI_MakeCylinder(1.0, 2.0).Shape().Moved(TopLoc_Location(inner));
    TopoDS_Compound compound;
    BRep_Builder builder;
    builder.MakeCompound(compound);
    builder.Add(compound, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape());
    builder.Add(compound, cylinder);
    gp_Trsf outer;
    outer.SetRotation(gp_Ax1(gp_Pnt(1, 2, 3), gp_Dir(1, 1, 0)), 0.7);
    outer.SetTranslationPart(gp_Vec(10, -4, 7));
    TopoShape shape(compound.Moved(TopLoc_Location(outer)));
    ASSERT_FALSE(shape.getShape().Location().IsIdentity());
    //   the shape's cache is built while it is placed
    ASSERT_EQ(shape.countSubElements("Face"), 9);
    ASSERT_FALSE(shape.getSubShape("Edge4").IsNull());

    // Act
    //   through the cached shape, twice (the second time from the filled cache)
    auto cached = allFingerprints(shape);
    auto again = allFingerprints(shape);
    //   from fresh copies without a cache, placed and at the origin (the path before ops#90)
    auto fresh = allFingerprints(TopoShape(shape.getShape()));
    auto atOrigin = allFingerprints(TopoShape(shape.getShape().Located(TopLoc_Location())));

    // Assert
    ASSERT_EQ(cached.size(), 9u + 15u + 10u);
    EXPECT_EQ(cached, again);
    EXPECT_EQ(cached, fresh);
    EXPECT_EQ(cached, atOrigin);
}

TEST_F(FeaturePartTest, fingerprintsThroughThePropertyEqualAFreshCopy)
{
    // Arrange
    //   a placed box: the property's shape has an element map and a cache
    _boxes[0]->Placement.setValue(
        Base::Placement(Base::Vector3d(10, -4, 7), Base::Rotation(Base::Vector3d(1, 1, 0), 0.7))
    );
    _boxes[0]->recomputeFeature();
    const TopoShape& shape = _boxes[0]->Shape.getShape();
    ASSERT_FALSE(shape.getShape().Location().IsIdentity());

    // Act and assert
    auto cached = allFingerprints(shape);
    EXPECT_EQ(cached.size(), 6u + 12u + 8u);
    EXPECT_EQ(cached, allFingerprints(TopoShape(shape.getShape())));
    for (int index = 1; index <= 6; ++index) {
        const std::string element = "Face" + std::to_string(index);
        Data::ElementFingerprint fp;
        ASSERT_TRUE(_boxes[0]->getElementFingerprint(element.c_str(), fp));
        EXPECT_EQ(element + " " + fp.toString(), cached[index - 1]);
    }
}

// The reference solver's tiers 2 and 3 (ops#7, Task 2 PR 4) on measured fingerprints, read back
// from their saved text as a reference holds them.

namespace
{

Data::ElementFingerprint savedFingerprint(const TopoShape& shape, const std::string& element)
{
    Data::ElementFingerprint fp;
    EXPECT_TRUE(Feature::getElementFingerprint(shape, element.c_str(), fp)) << element;
    return Data::ElementFingerprint::fromString(fp.toString());
}

// The fingerprints of the faces of \a shape that \a keep accepts, in index order.
std::vector<Data::ElementFingerprint> facesOf(
    const TopoShape& shape,
    const std::function<bool(const Data::ElementFingerprint&)>& keep
)
{
    std::vector<Data::ElementFingerprint> faces;
    for (int index = 1; index <= static_cast<int>(shape.countSubShapes(TopAbs_FACE)); ++index) {
        auto fp = savedFingerprint(shape, "Face" + std::to_string(index));
        if (keep(fp)) {
            faces.push_back(fp);
        }
    }
    return faces;
}

bool facesUp(const Data::ElementFingerprint& fp)
{
    return fp.kind == "Plane" && fp.direction && fp.direction->z > 0.5;
}

}  // namespace

TEST_F(FeaturePartTest, tier2AtTheToleranceBoundaries)
{
    Data::GeometryTolerances tol;  // 1e-6 rad, radii 1e-6 relative

    //   a cylinder's radius, just inside and just outside
    auto lateral = [](double radius) {
        TopoShape cylinder(BRepPrimAPI_MakeCylinder(radius, 5.0).Shape());
        auto faces = facesOf(cylinder, [](const auto& fp) { return fp.kind == "Cylinder"; });
        EXPECT_EQ(faces.size(), 1U);
        return faces.empty() ? Data::ElementFingerprint() : faces.front();
    };
    const auto cylinder = lateral(2.0);
    EXPECT_TRUE(Data::intrinsicAgrees(cylinder, lateral(2.0 * (1 + 0.5e-6)), tol));
    EXPECT_FALSE(Data::intrinsicAgrees(cylinder, lateral(2.0 * (1 + 2e-6)), tol));

    //   a box's top face turned about X, just inside and just outside
    auto top = [](double angle) {
        gp_Trsf turn;
        turn.SetRotation(gp::OX(), angle);
        TopoShape box(
            BRepBuilderAPI_Transform(BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), turn, true).Shape()
        );
        auto faces = facesOf(box, facesUp);
        EXPECT_EQ(faces.size(), 1U);
        return faces.empty() ? Data::ElementFingerprint() : faces.front();
    };
    const auto level = top(0.0);
    EXPECT_TRUE(Data::intrinsicAgrees(level, top(0.5e-6), tol));
    EXPECT_FALSE(Data::intrinsicAgrees(level, top(2e-6), tol));
    //   the bottom face is parallel, but faces the other way
    TopoShape box(BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape());
    auto bottom = facesOf(box, [](const auto& fp) {
        return fp.kind == "Plane" && fp.direction && fp.direction->z < -0.5;
    });
    ASSERT_EQ(bottom.size(), 1U);
    EXPECT_FALSE(Data::intrinsicAgrees(level, bottom.front(), tol));
}

TEST_F(FeaturePartTest, tier3NearestWithAGapOnSixBoxes)
{
    // Arrange
    //   the fixture's six boxes in one shape: at y = 0, 1, 3, 2, just past 2 (touching box 0
    //   within the confusion) and just short of 2
    _doc->recompute();
    BRep_Builder builder;
    TopoDS_Compound compound;
    builder.MakeCompound(compound);
    for (auto box : _boxes) {
        builder.Add(compound, box->Shape.getShape().getShape());
    }
    TopoShape shape(compound);
    auto tops = facesOf(shape, facesUp);
    ASSERT_EQ(tops.size(), 6U);
    const double diagonal = shape.getBoundBox().CalcDiagonalLength();
    Data::GeometryTolerances tol;

    // Act and assert
    //   boxes 0, 1 and 2 are a whole unit from any other: each top face is found in place
    for (int i : {0, 1, 2}) {
        EXPECT_EQ(Data::extrinsicNearest(tops[i], tops, diagonal, tol), i) << i;
    }
    //   boxes 3, 4 and 5 lie within d_max of each other: none is found
    for (int i : {3, 4, 5}) {
        EXPECT_EQ(Data::extrinsicNearest(tops[i], tops, diagonal, tol), -1) << i;
    }
    //   without boxes 4 and 5, box 3's top is found again
    std::vector<Data::ElementFingerprint> four(tops.begin(), tops.begin() + 4);
    EXPECT_EQ(Data::extrinsicNearest(tops[3], four, diagonal, tol), 3);
    //   a top face 1 % larger than the saved one isn't the same face
    auto larger = tops[0];
    larger.size = *tops[0].size * 1.011;
    EXPECT_EQ(Data::extrinsicNearest(larger, tops, diagonal, tol), -1);
}

TEST_F(FeaturePartTest, matchSimilarNamesTakesTheSameNameInTheOtherForm)
{
    // ops#97: the strict pass took the exact element by comparing bytes, else through
    // doNamesMatch, which isn't reflexive for every name: here a face's two linked edges match
    // each other (they're equal), so the face doesn't match itself. The same name in the other
    // form (interned) was then missed.
    // Arrange
    auto edge = Data::MappedName::makeUnmappedName({"Edge1"}, 5, "MKR", 'E');
    auto face = Data::MappedName(
        Data::MappedName::makeEncodedSection({}, {edge, edge}, 7, "FLT", 0, 'F', 0, {"GEN"})
    );
    auto interned = Data::MappedName(Data::NameTable::instance().toInterned(face.toString()));
    auto other = Data::MappedName::makeUnmappedName({"Face2"}, 5, "MKR", 'F');
    std::vector<Data::MappedElement> elements {
        {other, Data::IndexedName("Face", 2)},
        {interned, Data::IndexedName("Face", 1)},
    };
    bool ambiguous = false;

    // Act
    auto found = Feature::matchSimilarNames(face, elements, ambiguous);

    // Assert
    ASSERT_NE(interned, face);
    EXPECT_FALSE(Feature::doNamesMatch(face, face, false, true));  // the premise
    ASSERT_EQ(found.size(), 1U);
    EXPECT_EQ(found.front().index, Data::IndexedName("Face", 1));
    EXPECT_FALSE(ambiguous);
}
