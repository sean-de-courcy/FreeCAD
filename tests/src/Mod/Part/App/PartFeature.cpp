// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <boost/core/ignore_unused.hpp>
#include "Mod/Part/App/FeaturePartCommon.h"
#include <App/Link.h>
#include <src/App/InitApplication.h>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include "PartTestHelpers.h"
#include "App/MappedElement.h"
#include <Base/Interpreter.h>

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

TEST_F(FeaturePartTest, linksKeepTheSourcesNamesV2)
{
    // Arrange
    //   pattern: an object holds a shape whose face is new and untagged (last section's tag 0),
    //   built from a wire (tag 7). setValue() keeps the names of a shape that has a tag, so C++
    //   code can store such a shape. Link arrays and their elements take copies of the object's
    //   shape, which share its element map, and retag them (ops#34).
    ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V2);
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
    auto hiddenArrayShape =
        Feature::getTopoShape(hiddenArray, ShapeOption::ResolveLink | ShapeOption::Transform);

    // Assert
    //   the source's names are its own: no link's tag reaches them
    const TopoShape& sourceShape = source->Shape.getShape();
    EXPECT_EQ(sourceShape.getMappedName(face1).toString(), faceNameWithTag(0));
    EXPECT_EQ(sourceShape.getMappedName(edge1), edgeName);
    //   a plain link returns the source's shape as it is (through getSubObject(), no retag)
    EXPECT_FALSE(linkShape.isNull());
    //   an array's elements have their own tags (the box has 6 faces: the second element's
    //   first face is Face7)
    auto elements = array->ElementList.getValues();
    ASSERT_EQ(elements.size(), 2);
    Data::IndexedName face7("Face", 7);
    EXPECT_EQ(arrayShape.getMappedName(face1).toString(), faceNameWithTag(elements[0]->getID()));
    EXPECT_EQ(arrayShape.getMappedName(face7).toString(), faceNameWithTag(elements[1]->getID()));
    //   an array that hides its elements gives both copies its own tag
    EXPECT_EQ(hiddenArrayShape.getMappedName(face1).toString(), faceNameWithTag(hiddenArray->getID()));
    EXPECT_EQ(hiddenArrayShape.getMappedName(face7).toString(),
              faceNameWithTag(hiddenArray->getID(), 1));
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
            EXPECT_EQ(result.getMappedName(element),
                      Data::MappedName::makeUnmappedName({element.toString()}, 7, "MKR", type[0]));
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
            EXPECT_EQ(result.getMappedName(element).toString(),
                      element.toString() + ";:H7," + type[0]);
        }
    }
    EXPECT_EQ(result.getElementMapSize(), 26);
    //   the shape it was given keeps its algorithm
    EXPECT_EQ(shape.getHistoryAlgorithm(), App::HistoryAlgorithm::V2);
}
