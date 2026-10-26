// SPDX-License-Identifier: LGPL-2.1-or-later

#include <TColgp_Array2OfPnt.hxx>
#include <algorithm>
#include <cctype>
#include <functional>
#include <map>
#include <numbers>
#include <set>
#include <sstream>
#include <gtest/gtest.h>
#include "src/App/InitApplication.h"
#include <Base/Console.h>
#include <Mod/Part/App/TopoShape.h>
#include "Mod/Part/App/TopoShapeMapper.h"
#include "Mod/Part/App/modelRefine.h"
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "PartTestHelpers.h"

#include <boost/core/ignore_unused.hpp>
#include <BRepAdaptor_CompCurve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRep_Builder.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepFeat_SplitShape.hxx>
#include <BRepOffsetAPI_MakeEvolved.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <gp_Ax1.hxx>
#include <gp_Circ.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepGProp.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepPrimAPI_MakeHalfSpace.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopTools_DataMapOfShapeShape.hxx>
#include <TopTools_MapOfShape.hxx>
#include <GeomAPI_PointsToBSpline.hxx>
#include <Geom_BezierCurve.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_BSplineCurve.hxx>
#include <gp_Pln.hxx>
#include <ShapeFix_Wireframe.hxx>
#include <ShapeBuild_ReShape.hxx>
#include <ShapeUpgrade_ShapeDivideClosedEdges.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS_Edge.hxx>
#include <TColgp_Array1OfPnt.hxx>

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

using namespace Part;
using namespace PartTestHelpers;

class TopoShapeExpansionTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        Base::Interpreter().runString("import Part");
        _docName = App::GetApplication().getUniqueDocumentName("test");
        App::GetApplication().newDocument(_docName.c_str(), "testUser");
        _hasher = Base::Reference<App::StringHasher>(new App::StringHasher);
        ASSERT_EQ(_hasher.getRefCount(), 1);
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }


private:
    std::string _docName;
    Data::ElementIDRefs _sid;
    App::StringHasherRef _hasher;
};

TEST_F(TopoShapeExpansionTest, makeElementCompoundOneShapeReturnsShape)
{
    // Arrange
    auto edge = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    TopoShape topoShape {edge};
    std::vector<TopoShape> shapes {topoShape};

    // Act
    topoShape.makeElementCompound(shapes, "C", TopoShape::SingleShapeCompoundCreationPolicy::returnShape);

    // Assert
    EXPECT_EQ(edge.ShapeType(), topoShape.getShape().ShapeType());  // NOT a Compound
}

TEST_F(TopoShapeExpansionTest, makeElementCompoundOneShapeForceReturnsCompound)
{
    // Arrange
    auto edge = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    TopoShape topoShape {edge};
    std::vector<TopoShape> shapes {topoShape};

    // Act
    topoShape.makeElementCompound(
        shapes,
        "C",
        TopoShape::SingleShapeCompoundCreationPolicy::forceCompound
    );

    // Assert
    EXPECT_NE(edge.ShapeType(), topoShape.getShape().ShapeType());  // No longer the same thing
}

TEST_F(TopoShapeExpansionTest, makeElementCompoundTwoShapesReturnsCompound)
{
    // Arrange
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    auto edge2 = BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 0.0, 0.0), gp_Pnt(2.0, 0.0, 0.0)).Edge();
    TopoShape topoShape {edge1};
    std::vector<TopoShape> shapes {edge1, edge2};

    // Act
    topoShape.makeElementCompound(shapes);

    // Assert
    EXPECT_EQ(TopAbs_ShapeEnum::TopAbs_COMPOUND, topoShape.getShape().ShapeType());
}

TEST_F(TopoShapeExpansionTest, makeElementCompoundEmptyShapesReturnsEmptyCompound)
{
    // Arrange
    auto edge = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    TopoShape topoShape {edge};
    std::vector<TopoShape> shapes;

    // Act
    topoShape.makeElementCompound(shapes);

    // Assert
    EXPECT_EQ(TopAbs_ShapeEnum::TopAbs_COMPOUND, topoShape.getShape().ShapeType());
    EXPECT_TRUE(topoShape.getMappedChildElements().empty());
    EXPECT_EQ(0, topoShape.getShape().TShape()->NbChildren());
}

TEST_F(TopoShapeExpansionTest, makeElementCompoundTwoShapesGeneratesMapV1)
{
    // Arrange
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    auto edge2 = BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 0.0, 0.0), gp_Pnt(2.0, 0.0, 0.0)).Edge();
    TopoShape topoShape {App::HistoryAlgorithm::V1, 1L};
    std::vector<TopoShape> shapes {
        TopoShape(App::HistoryAlgorithm::V1, edge1, 2L),
        TopoShape(App::HistoryAlgorithm::V1, edge2, 3L)
    };
    // Act
    topoShape.makeElementCompound(shapes);
    auto elements = elementMap((topoShape));
    Base::BoundBox3d bb = topoShape.getBoundBox();
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getLength(topoShape.getShape()), 2);
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0, 0, 0, 2, 0, 0)));
    // Assert map is correct
    EXPECT_FALSE(topoShape.getMappedChildElements().empty());
    EXPECT_EQ(elements.size(), 6);
    EXPECT_EQ(elements[IndexedName("Edge", 1)], MappedName("Edge1;:H2,E"));
    EXPECT_EQ(elements[IndexedName("Edge", 2)], MappedName("Edge1;:H3,E"));
    EXPECT_EQ(elements[IndexedName("Vertex", 1)], MappedName("Vertex1;:H2,V"));
    EXPECT_EQ(elements[IndexedName("Vertex", 2)], MappedName("Vertex2;:H2,V"));
    EXPECT_EQ(elements[IndexedName("Vertex", 3)], MappedName("Vertex1;:H3,V"));
    EXPECT_EQ(elements[IndexedName("Vertex", 4)], MappedName("Vertex2;:H3,V"));
}

TEST_F(TopoShapeExpansionTest, makeElementCompoundTwoShapesGeneratesMapV2)
{
    // Arrange
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    auto edge2 = BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 0.0, 0.0), gp_Pnt(2.0, 0.0, 0.0)).Edge();
    TopoShape topoShape {1L};
    std::vector<TopoShape> shapes {TopoShape(edge1, 2L), TopoShape(edge2, 3L)};
    // Act
    topoShape.makeElementCompound(shapes);
    Base::BoundBox3d bb = topoShape.getBoundBox();
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getLength(topoShape.getShape()), 2);
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0, 0, 0, 2, 0, 0)));
    // Assert map is correct
    //   V2 keeps no child maps: the children's elements are named in the compound's own map. The
    //   edges have no names, so each element gets its unmapped name in its edge, under that
    //   edge's tag; the compound passes no op (MKR)
    EXPECT_TRUE(topoShape.getMappedChildElements().empty());
    EXPECT_EQ(topoShape.getElementMapSize(), 6);
    EXPECT_TRUE(elementHasNames(topoShape, "Edge1", {unmappedName("Edge1", 2)}));
    EXPECT_TRUE(elementHasNames(topoShape, "Edge2", {unmappedName("Edge1", 3)}));
    EXPECT_TRUE(elementHasNames(topoShape, "Vertex1", {unmappedName("Vertex1", 2)}));
    EXPECT_TRUE(elementHasNames(topoShape, "Vertex2", {unmappedName("Vertex2", 2)}));
    EXPECT_TRUE(elementHasNames(topoShape, "Vertex3", {unmappedName("Vertex1", 3)}));
    EXPECT_TRUE(elementHasNames(topoShape, "Vertex4", {unmappedName("Vertex2", 3)}));
    EXPECT_EQ(unmappedName("Vertex2", 3).toString(), "Vertex2;_;3;MKR;0;V;0;IDX,SRC;_");
}

namespace
{
// Collects the console's messages by level while it lives
class ConsoleCollector final: public Base::ILogger
{
public:
    ConsoleCollector()
    {
        Base::Console().attachObserver(this);
    }
    ~ConsoleCollector() override
    {
        Base::Console().detachObserver(this);
    }
    ConsoleCollector(const ConsoleCollector&) = delete;
    ConsoleCollector(ConsoleCollector&&) = delete;
    ConsoleCollector& operator=(const ConsoleCollector&) = delete;
    ConsoleCollector& operator=(ConsoleCollector&&) = delete;

    void sendLog(
        const std::string& /*notifiername*/,
        const std::string& msg,
        Base::LogStyle level,
        Base::IntendedRecipient /*recipient*/,
        Base::ContentType /*content*/
    ) override
    {
        messages.emplace_back(level, msg);
    }
    const char* name() override
    {
        return "ConsoleCollector";
    }

    size_t count(const std::string& text, Base::LogStyle level) const
    {
        return std::ranges::count_if(messages, [&](const auto& message) {
            return message.first == level && message.second.find(text) != std::string::npos;
        });
    }

    std::vector<std::pair<Base::LogStyle, std::string>> messages;
};

// Sets a log tag's level while it lives
class LogLevelScope
{
public:
    LogLevelScope(const char* tag, int level)
        : level(Base::Console().getLogLevel(tag))
        , oldLevel(*this->level)
    {
        *this->level = level;
    }
    ~LogLevelScope()
    {
        *level = oldLevel;
    }
    LogLevelScope(const LogLevelScope&) = delete;
    LogLevelScope(LogLevelScope&&) = delete;
    LogLevelScope& operator=(const LogLevelScope&) = delete;
    LogLevelScope& operator=(LogLevelScope&&) = delete;

private:
    int* level;
    int oldLevel;
};
}  // namespace

TEST_F(TopoShapeExpansionTest, mapSubElementOtherHasherOnlyLogs)
{
    // Arrange: the second input belongs to another document's string table (hasher). The user
    // can't act on that, so it goes to the log only, not to the Report view as an error or
    // warning (ops#151, upstream issue 24567)
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    auto edge2 = BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 0.0, 0.0), gp_Pnt(2.0, 0.0, 0.0)).Edge();
    App::StringHasherRef hasher1(new App::StringHasher);
    App::StringHasherRef hasher2(new App::StringHasher);
    TopoShape plain {1L};
    plain.makeElementCompound({TopoShape(edge1, 2L), TopoShape(edge2, 3L)});
    // The compound's shape alone, named from its inputs one by one below
    TopoShape topoShape(plain.getShape(), 1L, hasher1);
    topoShape.mapSubElement(TopoShape(edge1, 2L, hasher1));
    ASSERT_GT(topoShape.getElementMapSize(), 0);
    // Act: at the log level, restored however the test ends
    {
        LogLevelScope logLevel("TopoShape", FC_LOGLEVEL_LOG);
        ConsoleCollector collector;
        topoShape.mapSubElement(TopoShape(edge2, 3L, hasher2));
        // Assert: the mismatch was seen, and reported at the log level only
        EXPECT_GE(collector.count("hasher mismatch", Base::LogStyle::Log), 1);
        EXPECT_EQ(collector.count("hasher mismatch", Base::LogStyle::Error), 0);
        EXPECT_EQ(collector.count("hasher mismatch", Base::LogStyle::Warning), 0);
    }
    EXPECT_EQ(topoShape.getElementMapSize(), 6);
}

TEST_F(TopoShapeExpansionTest, makeElementCompoundTwoCubes)
{
    auto [cube1TS, cube2TS] = CreateTwoTopoShapeCubes();
    // Act
    TopoShape topoShape {3L};
    topoShape.makeElementCompound({cube1TS, cube2TS});
    Base::BoundBox3d bb = topoShape.getBoundBox();
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getVolume(topoShape.getShape()), 2);
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0, 0, 0, 2, 1, 1)));
    // Assert map is correct
    // Two cubes, each consisting of:
    // 8 Vertices
    // 12 Edges
    // 6 Faces
    // ----------
    // 26 subshapes each, all named. V2 keeps no child maps.
    EXPECT_TRUE(topoShape.getMappedChildElements().empty());
    EXPECT_EQ(topoShape.countSubElements("Vertex"), 16);
    EXPECT_EQ(topoShape.countSubElements("Edge"), 24);
    EXPECT_EQ(topoShape.countSubElements("Face"), 12);
    EXPECT_TRUE(allElementsNamed(topoShape));
    // Each cube is a compound of its six faces, tags 1 to 6 and 8 to 13, which have no names, so
    // every element is named after an element of one of these faces: the unmapped name of that
    // face's element, under the face's tag. That element must be the one named: the faces share
    // their edges and vertices, so a face's Edge2 is not the Edge2 after the previous faces' edges.
    std::map<long, TopoShape> faces;
    for (int index = 1; index <= 6; ++index) {
        faces[index] = TopoShape(cube1TS.getSubShape(TopAbs_FACE, index));
        faces[index + 7] = TopoShape(cube2TS.getSubShape(TopAbs_FACE, index));
    }
    EXPECT_TRUE(unmappedNamesNameTheirElements(topoShape, faces));
}

TEST_F(TopoShapeExpansionTest, MapperMakerModified)
{
    // Arrange
    // Definition of all the objects needed for a Transformation
    // (https://dev.opencascade.org/doc/refman/html/class_b_rep_builder_a_p_i___transform.html)
    auto translation {gp_Trsf()};
    auto transform {BRepBuilderAPI_Transform(translation)};
    auto transformMprMkr {MapperMaker(transform)};

    // Definition of all the objects needed for a Shape Splitting
    // (https://dev.opencascade.org/doc/refman/html/class_b_rep_feat___split_shape.html)
    auto splitMkr {BRepFeat_SplitShape()};
    auto splitMprMkr {MapperMaker(splitMkr)};

    // Creating a Wire, used later to create a Face
    auto wireMkr {BRepBuilderAPI_MakeWire(
        BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)),
        BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 0.0, 0.0), gp_Pnt(1.0, 1.0, 0.0)),
        BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 1.0, 0.0), gp_Pnt(0.0, 0.0, 0.0))
    )};
    auto wire = wireMkr.Wire();

    // Creating a Face using the Wire created before
    auto faceMkr {BRepBuilderAPI_MakeFace(wire)};
    const auto& face = faceMkr.Face();

    // Creating an Edge to split the Face and the Wire
    auto edgeMkr {BRepBuilderAPI_MakeEdge(gp_Pnt(0.5, 1.0, 0.0), gp_Pnt(0.5, -1.0, 0.0))};
    auto edge = edgeMkr.Edge();

    // Act
    // Performing the Transformation
    translation.SetTranslation(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0));
    transform.Perform(wire);

    // Initializing and performing the Split
    splitMkr.Init(face);
    splitMkr.Add(edge, face);
    splitMkr.Build();

    // Assert
    // Check that all the shapes and operations have been performed
    EXPECT_TRUE(wireMkr.IsDone());
    EXPECT_TRUE(faceMkr.IsDone());
    EXPECT_TRUE(edgeMkr.IsDone());
    EXPECT_TRUE(splitMkr.IsDone());
    EXPECT_TRUE(transform.IsDone());

    // Check the result of the operations
    EXPECT_EQ(transformMprMkr.modified(wire).size(), 1);  // The Transformation acts on the Wire...
    EXPECT_EQ(
        transformMprMkr.modified(face).size(),
        1
    );  // ... and therefore on the created Face...
    EXPECT_EQ(transformMprMkr.modified(edge).size(), 1);  // ... and on the Edge added to the Face

    EXPECT_EQ(splitMprMkr.modified(edge).size(), 0);  // The Split doesn't modify the Edge
    EXPECT_EQ(splitMprMkr.modified(wire).size(), 2);  // The Split modifies the Wire into 2 Wires
    EXPECT_EQ(splitMprMkr.modified(face).size(), 2);  // The Split modifies the Face into 2 Faces
}

TEST_F(TopoShapeExpansionTest, MapperMakerGenerated)
{
    // Arrange
    // Creating tree Edges, used later in the Fuse operations
    auto edge1 {BRepBuilderAPI_MakeEdge(gp_Pnt(-1.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge()};
    auto edge2 {BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, -1.0, 0.0), gp_Pnt(0.0, 1.0, 0.0)).Edge()};
    auto edge3 {BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, -1.0), gp_Pnt(0.0, 0.0, 1.0)).Edge()};

    // Definition of all the objects needed for the Fuses
    // (https://dev.opencascade.org/doc/refman/html/class_b_rep_algo_a_p_i___fuse.html)
    // The Fuse operation, like other Boolean operations derived from BRepAlgoAPI_BuilderAlgo,
    // supports the generation history
    // (https://dev.opencascade.org/doc/refman/html/class_b_rep_algo_a_p_i___builder_algo.html)
    auto fuse1Mkr {BRepAlgoAPI_Fuse(edge1, edge2)};
    auto fuse1MprMkr {MapperMaker(fuse1Mkr)};
    auto fuse2Mkr {BRepAlgoAPI_Fuse(edge1, edge3)};
    auto fuse2MprMkr {MapperMaker(fuse2Mkr)};

    // Act
    fuse1Mkr.Build();
    fuse2Mkr.Build();

    // Assert
    // Check that all the shapes and operations have been performed
    EXPECT_TRUE(fuse1Mkr.IsDone());
    EXPECT_TRUE(fuse2Mkr.IsDone());

    // Check the result of the operations
    EXPECT_EQ(fuse1MprMkr.generated(edge1).size(), 1);  // fuse1 has a new vertex generated by edge1
    EXPECT_EQ(fuse1MprMkr.generated(edge2).size(), 1);  // fuse1 has a new vertex generated by edge2
    EXPECT_EQ(
        fuse1MprMkr.generated(edge3).size(),
        0
    );  // fuse1 doesn't have a new vertex generated by edge3

    EXPECT_EQ(fuse2MprMkr.generated(edge1).size(), 1);  // fuse2 has a new vertex generated by edge1
    EXPECT_EQ(
        fuse2MprMkr.generated(edge2).size(),
        0
    );  // fuse2 doesn't have a new vertex generated by edge2
    EXPECT_EQ(fuse2MprMkr.generated(edge3).size(), 1);  // fuse2 has a new vertex generated by edge3
}

TEST_F(TopoShapeExpansionTest, MapperHistoryModified)
{
    // Arrange
    // Creating a all the shapes needed for the operations that have a history
    auto vertex1 {BRepBuilderAPI_MakeVertex(gp_Pnt(-1.0, -1.0, 0.0)).Vertex()};
    auto vertex2 {BRepBuilderAPI_MakeVertex(gp_Pnt(1.0, 0.0, 0.0)).Vertex()};
    auto edge1 {BRepBuilderAPI_MakeEdge(vertex1, vertex2).Edge()};
    auto edge2 {BRepBuilderAPI_MakeEdge(gp_Pnt(-1.0, 0.0, 0.0), gp_Pnt(0.0, 1.0, 0.0)).Edge()};
    auto edge3 {BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 1.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge()};
    auto wire {BRepBuilderAPI_MakeWire(edge1, edge2, edge3).Wire()};

    // Definition of a MapperHistory made with ShapeBuild_ReShape and of all the objects needed
    // (https://dev.opencascade.org/doc/refman/html/class_shape_build___re_shape.html)
    // (https://dev.opencascade.org/doc/overview/html/occt_user_guides__shape_healing.html#occt_shg_5_1)
    Handle(ShapeBuild_ReShape) reshape {new ShapeBuild_ReShape()};
    // Recording all the shapes that will be modified
    vertex1 = reshape->CopyVertex(vertex1);
    vertex2 = reshape->CopyVertex(vertex2);
    reshape->Apply(edge1);
    auto reshapeMprHst {MapperHistory(reshape)};

    // Definition a MapperHistory made with ShapeFix_Wireframe and of all the objects needed
    // (https://dev.opencascade.org/doc/refman/html/class_shape_fix___wireframe.html)
    // (https://dev.opencascade.org/doc/overview/html/occt_user_guides__shape_healing.html#occt_shg_2_1)
    Handle(ShapeFix_Wireframe) fix {new ShapeFix_Wireframe()};
    fix->SetContext(reshape);
    fix->SetPrecision(0.0);
    auto fixMprHst {MapperHistory(*fix)};

    // Definition of a MapperHistory made with the BRepTools_History of reshape
    // (https://dev.opencascade.org/doc/refman/html/class_b_rep_tools___history.html)
    auto historyMprHst {MapperHistory(reshape->History())};

    // Act
    // Closing the wire
    fix->Load(wire);
    fix->FixWireGaps();

    // Replacing the edge with the new one made with the modified Vertexes
    reshape->Replace(edge1, BRepBuilderAPI_MakeEdge(vertex1, vertex2).Edge());
    reshape->Apply(edge1);

    // Assert
    // Check that all the shapes and operations have been performed
    EXPECT_TRUE(reshape->Status(ShapeExtend_DONE1));
    EXPECT_TRUE(reshape->Status(ShapeExtend_DONE3));
    EXPECT_TRUE(fix->StatusWireGaps(ShapeExtend_DONE));

    // Check the results of the operations after the ShapeFix_Wireframe.
    // The history is in common so all the MapperHistory object defined previously will return the
    // same values
    EXPECT_EQ(historyMprHst.modified(edge1).size(), 1);
    EXPECT_EQ(reshapeMprHst.modified(edge1).size(), 1);
    EXPECT_EQ(fixMprHst.modified(edge1).size(), 1);
}

TEST_F(TopoShapeExpansionTest, MapperHistoryGenerated)
{
    // Arrange
    // Creating a all the shapes needed for the operations that have a history
    auto edge1 {BRepBuilderAPI_MakeEdge(gp_Pnt(-1.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge()};
    auto edge2 {BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, -1.0, 0.0), gp_Pnt(0.0, 1.0, 0.0)).Edge()};
    auto edge3 {BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, -1.0), gp_Pnt(0.0, 0.0, 1.0)).Edge()};

    // Definition of a MapperHistory made with a BRepTools_History containing the Generated() shapes
    // of the Fuse operations, added manually to workaround a CI failure
    // (https://github.com/FreeCAD/FreeCAD/pull/12402#issuecomment-1946234571)
    auto fuse1Mkr {BRepAlgoAPI_Fuse(edge1, edge2)};
    Handle(BRepTools_History) fuse1Hst {new BRepTools_History()};
    auto fuse1MprHst {MapperHistory(fuse1Hst)};
    auto fuse2Mkr {BRepAlgoAPI_Fuse(edge1, edge3)};
    Handle(BRepTools_History) fuse2Hst {new BRepTools_History()};
    auto fuse2MprHst {MapperHistory(fuse2Hst)};

    // Act
    fuse1Mkr.Build();
    fuse1Hst->AddGenerated(edge1, fuse1Mkr);
    fuse1Hst->AddGenerated(edge2, fuse1Mkr);
    fuse2Mkr.Build();
    fuse2Hst->AddGenerated(edge1, fuse2Mkr);
    fuse2Hst->AddGenerated(edge3, fuse2Mkr);

    // Assert
    // Check that all the shapes and operations have been performed
    EXPECT_TRUE(fuse1Mkr.IsDone());
    EXPECT_TRUE(fuse2Mkr.IsDone());

    // Check the result of the operations
    EXPECT_EQ(fuse1MprHst.generated(edge1).size(), 1);  // fuse1 has a new vertex generated by edge1
    EXPECT_EQ(fuse1MprHst.generated(edge2).size(), 1);  // fuse1 has a new vertex generated by edge2
    EXPECT_EQ(
        fuse1MprHst.generated(edge3).size(),
        0
    );  // fuse1 doesn't have a new vertex generated by edge3

    EXPECT_EQ(fuse2MprHst.generated(edge1).size(), 1);  // fuse2 has a new vertex generated by edge1
    EXPECT_EQ(
        fuse2MprHst.generated(edge2).size(),
        0
    );  // fuse2 doesn't have a new vertex generated by edge2
    EXPECT_EQ(fuse2MprHst.generated(edge3).size(), 1);  // fuse2 has a new vertex generated by edge3
}

TEST_F(TopoShapeExpansionTest, resetElementMapTest)
{
    // Arrange
    // Creating various TopoShapes to check different conditions

    // A TopoShape without a map
    auto shapeWithoutMap {
        TopoShape(BRepBuilderAPI_MakeEdge(gp_Pnt(-1.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge(), 1)
    };

    // A TopoShape without a map that will be replaced by another map
    auto shapeWithoutMapAfterReset {TopoShape(shapeWithoutMap)};

    // A TopoShape with a map
    auto shapeWithMap {
        TopoShape(BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, -1.0, 0.0), gp_Pnt(0.0, 1.0, 0.0)).Edge(), 3)
    };
    shapeWithMap.makeShapeWithElementMap(shapeWithMap.getShape(), TopoShape::Mapper(), {shapeWithMap});

    // A TopoShape with a map that will be replaced by another map
    auto shapeWithMapAfterReset {TopoShape(shapeWithMap)};
    shapeWithMapAfterReset.makeShapeWithElementMap(
        shapeWithMapAfterReset.getShape(),
        TopoShape::Mapper(),
        {shapeWithMapAfterReset}
    );

    // A TopoShape with a map that will be replaced by an empty map
    auto shapeWithMapAfterEmptyReset {TopoShape(shapeWithMap)};
    shapeWithMapAfterEmptyReset.makeShapeWithElementMap(
        shapeWithMapAfterEmptyReset.getShape(),
        TopoShape::Mapper(),
        {shapeWithMapAfterEmptyReset}
    );

    // A new map
    auto newElementMapPtr {std::make_shared<Data::ElementMap>()};
    newElementMapPtr->setElementName(IndexedName("Edge", 2), MappedName("Edge2;:H,E"), 3, nullptr, true);

    // Act
    shapeWithoutMapAfterReset.resetElementMap(newElementMapPtr);
    shapeWithMapAfterReset.resetElementMap(newElementMapPtr);
    shapeWithMapAfterEmptyReset.resetElementMap(nullptr);

    // Assert
    // Check that the original maps haven't been modified
    EXPECT_EQ(shapeWithoutMap.getElementMapSize(false), 0);
    EXPECT_EQ(shapeWithMap.getElementMapSize(false), 3);

    // Check that the two shapes have the same map
    EXPECT_EQ(shapeWithoutMapAfterReset.getElementMap(), shapeWithMapAfterReset.getElementMap());
    // Check that inside the shape's map there's the element of the new map (same result if
    // checking with the other shape)
    EXPECT_NE(shapeWithoutMapAfterReset.getElementMap()[0].name.find("Edge2"), -1);
    // Check that there aren't leftovers from the previous map
    EXPECT_EQ(shapeWithMapAfterReset.getElementMap()[0].name.find("Edge1"), -1);

    // Check that the map has been emptied
    EXPECT_EQ(shapeWithMapAfterEmptyReset.getElementMapSize(false), 0);
}

TEST_F(TopoShapeExpansionTest, flushElementMapTest)
{
    // Arrange
    // Creating various TopoShapes to check different conditions

    // A TopoShape with a map that won't be flushed
    auto shapeWithMapNotFlushed {
        TopoShape(BRepBuilderAPI_MakeEdge(gp_Pnt(-1.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge(), 1)
    };
    shapeWithMapNotFlushed.makeShapeWithElementMap(
        shapeWithMapNotFlushed.getShape(),
        TopoShape::Mapper(),
        {shapeWithMapNotFlushed}
    );

    // A TopoShape with a map that will be reset and then flushed
    auto shapeWithMapFlushed {
        TopoShape(BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, -1.0, 0.0), gp_Pnt(0.0, 1.0, 0.0)).Edge(), 2)
    };
    shapeWithMapFlushed.makeShapeWithElementMap(
        shapeWithMapFlushed.getShape(),
        TopoShape::Mapper(),
        {shapeWithMapFlushed}
    );

    // A child TopoShape that will be flushed
    auto childshapeWithMapFlushed {shapeWithMapFlushed.getSubTopoShape(TopAbs_VERTEX, 1)};
    childshapeWithMapFlushed.Tag = 3;

    // A new map
    auto newElementMapPtr {std::make_shared<Data::ElementMap>()};
    newElementMapPtr->setElementName(IndexedName("Edge", 2), MappedName("Edge2;:H,E"), 3, nullptr, true);

    // Setting a different element map and then resetting otherwise flush won't have effect
    shapeWithMapFlushed.resetElementMap(newElementMapPtr);
    shapeWithMapFlushed.resetElementMap(nullptr);

    // Act
    shapeWithMapNotFlushed.flushElementMap();
    shapeWithMapFlushed.flushElementMap();
    childshapeWithMapFlushed.flushElementMap();

    // Assert
    // Check that the original map haven't been modified
    EXPECT_EQ(shapeWithMapNotFlushed.getElementMapSize(false), 3);

    // Check that the two maps have been flushed
    EXPECT_NE(shapeWithMapFlushed.getElementMap()[0].name.find("Edge2"), -1);
    EXPECT_NE(childshapeWithMapFlushed.getElementMap()[0].name.find("Vertex1"), -1);
}

TEST_F(TopoShapeExpansionTest, cacheRelatedElements)
{
    // Arrange
    TopoShape topoShape {3L};
    QVector<MappedElement> names {
        {MappedName {"Test1"}, IndexedName {"Test", 1}},
        {MappedName {"Test2"}, IndexedName {"Test", 2}},
        {MappedName {"OtherTest1"}, IndexedName {"OtherTest", 1}},
    };
    QVector<MappedElement> names2 {
        {MappedName {"Test3"}, IndexedName {"Test", 3}},
    };
    HistoryTraceType traceType = HistoryTraceType::followTypeChange;
    MappedName keyName {"Key1"};
    MappedName keyName2 {"Key2"};
    QVector<MappedElement> returnedNames;
    QVector<MappedElement> returnedNames2;
    QVector<MappedElement> returnedNames3;
    // Act
    topoShape.cacheRelatedElements(keyName, traceType, names);
    topoShape.cacheRelatedElements(keyName2, HistoryTraceType::stopOnTypeChange, names2);
    topoShape.getRelatedElementsCached(keyName, traceType, returnedNames);
    topoShape.getRelatedElementsCached(keyName, HistoryTraceType::stopOnTypeChange, returnedNames3);
    topoShape.getRelatedElementsCached(keyName2, HistoryTraceType::stopOnTypeChange, returnedNames2);
    // Assert
    EXPECT_EQ(returnedNames.size(), 3);
    EXPECT_STREQ(returnedNames[0].name.toString().c_str(), "Test1");
    EXPECT_EQ(returnedNames2.size(), 1);
    EXPECT_STREQ(returnedNames2[0].name.toString().c_str(), "Test3");
    EXPECT_EQ(returnedNames3.size(), 0);  // No entries of this type.
}

TEST_F(TopoShapeExpansionTest, makeElementWiresCombinesAdjacent)
{
    // Arrange
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    auto edge2 = BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 0.0, 0.0), gp_Pnt(2.0, 0.0, 0.0)).Edge();
    TopoShape topoShape {3L};
    std::vector<TopoShape> shapes {TopoShape(edge1, 1L), TopoShape(edge2, 2L)};
    //    std::vector<TopoShape> shapes {edge1, edge2};
    // Act
    topoShape.makeElementWires(shapes);
    auto elementMap = topoShape.getElementMap();
    // Assert
    EXPECT_EQ(6, elementMap.size());
}

TEST_F(TopoShapeExpansionTest, makeElementWiresCombinesWiresV1)
{
    // Arrange
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    auto edge2 = BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 0.0, 0.0), gp_Pnt(2.0, 0.0, 0.0)).Edge();
    auto edge3 = BRepBuilderAPI_MakeEdge(gp_Pnt(3.0, 0.0, 0.0), gp_Pnt(2.0, 1.0, 0.0)).Edge();
    auto edge4 = BRepBuilderAPI_MakeEdge(gp_Pnt(2.0, 1.0, 0.0), gp_Pnt(2.0, 2.0, 0.0)).Edge();
    std::vector<TopoShape> shapes {
        TopoShape(App::HistoryAlgorithm::V1, edge1, 1L),
        TopoShape(App::HistoryAlgorithm::V1, edge2, 2L)
    };
    std::vector<TopoShape> shapes2 {
        TopoShape(App::HistoryAlgorithm::V1, edge3, 4L),
        TopoShape(App::HistoryAlgorithm::V1, edge4, 4L)
    };
    //    std::vector<TopoShape> shapes {edge1, edge2};
    // Act
    auto& wire1 = (new TopoShape {App::HistoryAlgorithm::V1})->makeElementWires(shapes);
    auto& wire2 = (new TopoShape {App::HistoryAlgorithm::V1})->makeElementWires(shapes2);
    auto& topoShape = (new TopoShape {App::HistoryAlgorithm::V1})->makeElementWires({wire1, wire2});
    auto elements = elementMap((topoShape));
    Base::BoundBox3d bb = topoShape.getBoundBox();
    // Assert shape is correct
    EXPECT_NEAR(getLength(topoShape.getShape()), 4.4142137, 1e-6);
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0, 0, 0, 3, 2, 0)));
    // Assert map is correct
    EXPECT_TRUE(allElementsMatch(
        topoShape,
        {
            "Edge1;WIR;:H1:4,E;WIR;:H1:4,E",
            "Edge1;WIR;:H2:4,E;WIR;:H2:4,E",
            "Edge1;WIR;:H4:4,E;D1;:H4:3,E;WIR;:H4:4,E",
            "Edge1;WIR;:H4:4,E;WIR;:H4:4,E",
            "Vertex1;WIR;:H1:4,V;WIR;:H1:4,V",
            "Vertex1;WIR;:H4:4,V;WIR;:H4:4,V",
            "Vertex2;WIR;:H1:4,V;WIR;:H1:4,V",
            "Vertex2;WIR;:H2:4,V;WIR;:H2:4,V",
            "Vertex2;WIR;:H4:4,V;D1;:H4:3,V;WIR;:H4:4,V",
            "Vertex2;WIR;:H4:4,V;WIR;:H4:4,V",
        }
    ));  // Changed with PR#12471. Probably will change again after
         // importing other TopoNaming logics
}

TEST_F(TopoShapeExpansionTest, makeElementFaceNull)
{
    // Arrange
    const float Len = 3, Wid = 2, Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    TopoShape topoShape {App::HistoryAlgorithm::V1, face1};
    double area = getArea(face1);
    double area1 = getArea(topoShape.getShape());
    // Act
    TopoShape newFace = topoShape.makeElementFace(nullptr);
    double area2 = getArea(newFace.getShape());
    double area3 = getArea(topoShape.getShape());
    // Assert
    EXPECT_FALSE(face1.IsEqual(newFace.getShape()));
    EXPECT_DOUBLE_EQ(area, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area1, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area2, Len * Wid - std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area3, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_STREQ(newFace.shapeName().c_str(), "Face");
}

TEST_F(TopoShapeExpansionTest, makeElementFaceSimple)
{
    // Arrange
    const float Len = 3;
    const float Wid = 2;
    const float Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    TopoShape topoShape {face1};
    double area = getArea(face1);
    double area1 = getArea(topoShape.getShape());
    // Act
    TopoShape newFace = topoShape.makeElementFace(wire1);
    double area2 = getArea(newFace.getShape());
    double area3 = getArea(topoShape.getShape());
    // Assert
    EXPECT_TRUE(newFace.getShape().IsEqual(topoShape.getShape()));  // topoShape was altered
    EXPECT_FALSE(face1.IsEqual(newFace.getShape()));
    EXPECT_DOUBLE_EQ(area, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area1, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area2, Len * Wid);
    EXPECT_DOUBLE_EQ(area3, Len * Wid);
    EXPECT_STREQ(newFace.shapeName().c_str(), "Face");
}

TEST_F(TopoShapeExpansionTest, makeElementFaceParams)
{
    // Arrange
    const float Len = 3;
    const float Wid = 2;
    const float Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    TopoShape topoShape {face1, 1L};
    double area = getArea(face1);
    double area1 = getArea(topoShape.getShape());
    // Act
    TopoShape newFace = topoShape.makeElementFace(wire1, "Cut", "Part::FaceMakerBullseye", nullptr);
    double area2 = getArea(newFace.getShape());
    double area3 = getArea(topoShape.getShape());
    // Assert
    EXPECT_TRUE(newFace.getShape().IsEqual(topoShape.getShape()));  // topoShape was altered
    EXPECT_FALSE(face1.IsEqual(newFace.getShape()));
    EXPECT_DOUBLE_EQ(area, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area1, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area2, Len * Wid);
    EXPECT_DOUBLE_EQ(area3, Len * Wid);
    EXPECT_STREQ(newFace.shapeName().c_str(), "Face");
}

TEST_F(TopoShapeExpansionTest, makeElementFaceFromFace)
{
    // Arrange
    const float Len = 3;
    const float Wid = 2;
    const float Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    TopoShape topoShape {face1, 1L};
    double area = getArea(face1);
    double area1 = getArea(topoShape.getShape());
    // Act
    TopoShape newFace = topoShape.makeElementFace(face1, "Cut", "Part::FaceMakerBullseye", nullptr);
    double area2 = getArea(newFace.getShape());
    double area3 = getArea(topoShape.getShape());
    // Assert
    EXPECT_TRUE(newFace.getShape().IsEqual(topoShape.getShape()));  // topoShape was altered
    EXPECT_FALSE(face1.IsEqual(newFace.getShape()));
    EXPECT_DOUBLE_EQ(area, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area1, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area2, Len * Wid - std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area3, Len * Wid - std::numbers::pi * Rad * Rad);
    EXPECT_STREQ(newFace.shapeName().c_str(), "Face");
}


TEST_F(TopoShapeExpansionTest, makeElementFaceOpenWire)
{
    // Arrange
    const float Len = 3;
    const float Wid = 2;
    const float Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    TopoShape topoShape {wire1, 1L};
    double area = getArea(face1);
    double area1 = getArea(topoShape.getShape());
    // Act
    TopoShape newFace = topoShape.makeElementFace(wire1, "Cut", nullptr, nullptr);
    double area2 = getArea(newFace.getShape());
    double area3 = getArea(topoShape.getShape());
    // Assert
    EXPECT_TRUE(newFace.getShape().IsEqual(topoShape.getShape()));  // topoShape was altered
    EXPECT_FALSE(face1.IsEqual(newFace.getShape()));
    EXPECT_DOUBLE_EQ(area, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area1, 0);  // Len * Wid - std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area2, Len * Wid);
    EXPECT_DOUBLE_EQ(area3, Len * Wid);
    EXPECT_STREQ(newFace.shapeName().c_str(), "Face");
}


TEST_F(TopoShapeExpansionTest, makeElementFaceClosedWire)
{
    // Arrange
    const float Len = 3;
    const float Wid = 2;
    const float Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    TopoShape topoShape {wire2, 1L};
    double area = getArea(face1);
    double area1 = getArea(topoShape.getShape());
    // Act
    TopoShape newFace = topoShape.makeElementFace(wire2, "Cut", "Part::FaceMakerBullseye", nullptr);
    double area2 = getArea(newFace.getShape());
    double area3 = getArea(topoShape.getShape());
    // Assert
    EXPECT_TRUE(newFace.getShape().IsEqual(topoShape.getShape()));  // topoShape was altered
    EXPECT_FALSE(face1.IsEqual(newFace.getShape()));
    EXPECT_DOUBLE_EQ(area, Len * Wid + std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area1, 0);  // Len * Wid - std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area2, std::numbers::pi * Rad * Rad);
    EXPECT_DOUBLE_EQ(area3, std::numbers::pi * Rad * Rad);
    EXPECT_STREQ(newFace.shapeName().c_str(), "Face");
}

// Possible future makeElementFace tests:
// Overlapping wire
// Compound of wires
// Compound of faces
// Compound of other shape types


TEST_F(TopoShapeExpansionTest, setElementComboNameNothing)
{
    // Arrange
    TopoShape topoShape {1L};
    // Act
    Data::MappedName result = topoShape.setElementComboName(Data::IndexedName(), {});
    // ASSERT
    EXPECT_STREQ(result.toString().c_str(), "");
}


TEST_F(TopoShapeExpansionTest, setElementComboNameSimpleV1)
{
    // Arrange
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    TopoShape topoShape {App::HistoryAlgorithm::V1, edge1, 1L};
    topoShape.setElementMap({});  // Initialize the map to avoid a segfault.
    // Also, maybe the end of TopoShape::mapSubElementTypeForShape should enforce that elementMap()
    // isn't nullptr to eliminate the segfault.
    Data::MappedName edgeName("testname");
    // Act
    Data::MappedName result
        = topoShape.setElementComboName(Data::IndexedName::fromConst("Edge", 1), {edgeName});
    // Assert
    EXPECT_STREQ(result.toString().c_str(), "testname;");
}


TEST_F(TopoShapeExpansionTest, setElementComboNameV1)
{
    // Arrange
    TopoShape topoShape {App::HistoryAlgorithm::V1, 2L};
    topoShape.setElementMap({});
    Data::MappedName edgeName = topoShape.getMappedName(Data::IndexedName::fromConst("Edge", 1), true);
    Data::MappedName faceName = topoShape.getMappedName(Data::IndexedName::fromConst("Face", 7), true);
    Data::MappedName faceName2 = topoShape.getMappedName(Data::IndexedName::fromConst("Face", 8), true);
    const char* op = "Copy";
    // Act
    Data::MappedName result = topoShape.setElementComboName(
        Data::IndexedName::fromConst("Edge", 1),
        {edgeName, faceName, faceName2},
        OpCodes::Common,
        op
    );
    // Assert
    EXPECT_STREQ(result.toString().c_str(), "Edge1;CMN(Face7|Face8);Copy");
    // The detailed forms of names are covered in encodeElementName tests
}

TEST_F(TopoShapeExpansionTest, setElementComboNameCompoundV1)
{
    // Arrange
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    auto wire1 = BRepBuilderAPI_MakeWire({edge1}).Wire();
    auto wire2 = BRepBuilderAPI_MakeWire({edge1}).Wire();
    TopoShape topoShape {App::HistoryAlgorithm::V1, 2L};
    topoShape.makeElementCompound({wire1, wire2});  // Quality of shape doesn't matter
    Data::MappedName edgeName = topoShape.getMappedName(Data::IndexedName::fromConst("Edge", 1), true);
    Data::MappedName faceName = topoShape.getMappedName(Data::IndexedName::fromConst("Face", 7), true);
    Data::MappedName faceName2 = topoShape.getMappedName(Data::IndexedName::fromConst("Face", 8), true);
    const char* op = "Copy";
    // Act
    Data::MappedName result = topoShape.setElementComboName(
        Data::IndexedName::fromConst("Edge", 1),
        {edgeName, faceName, faceName2},
        OpCodes::Common,
        op
    );
    // ASSERT
    EXPECT_STREQ(
        result.toString().c_str(),
        "Edge1;:H,E;CMN(Face7|Face8);Copy"
    );  // Changed with PR#12471. Probably will change again
        // after importing other TopoNaming logics
    // The detailed forms of names are covered in encodeElementName tests
}

TEST_F(TopoShapeExpansionTest, setElementComboNameCompoundV2)
{
    // Arrange
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)).Edge();
    auto wire1 = BRepBuilderAPI_MakeWire({edge1}).Wire();
    auto wire2 = BRepBuilderAPI_MakeWire({edge1}).Wire();
    TopoShape topoShape {2L};
    topoShape.makeElementCompound({wire1, wire2});  // Quality of shape doesn't matter
    Data::MappedName edgeName = topoShape.getMappedName(Data::IndexedName::fromConst("Edge", 1), true);
    Data::MappedName faceName = topoShape.getMappedName(Data::IndexedName::fromConst("Face", 7), true);
    Data::MappedName faceName2 = topoShape.getMappedName(Data::IndexedName::fromConst("Face", 8), true);
    const char* op = "Copy";
    // Act
    Data::MappedName result = topoShape.setElementComboName(
        Data::IndexedName::fromConst("Edge", 1),
        {edgeName, faceName, faceName2},
        OpCodes::Common,
        op
    );
    // Assert
    //   the wires' edge has no name and no tag: in the compound it gets its unmapped name under
    //   the compound's tag. V2 has no combo names (encodeElementName does nothing), so the element
    //   keeps the first name as it is.
    EXPECT_EQ(edgeName, unmappedName("Edge1", 2));
    EXPECT_EQ(result, edgeName);
    EXPECT_EQ(topoShape.getMappedName(Data::IndexedName::fromConst("Edge", 1)), edgeName);
}

TEST_F(TopoShapeExpansionTest, splitWires)
{
    // Arrange
    const float Len = 3;
    const float Wid = 2;
    const float Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    TopoShape topoShape {face1, 1L};
    std::vector<TopoShape> inner;
    // Act
    EXPECT_EQ(topoShape.getShape().Orientation(), TopAbs_FORWARD);
    TopoShape wire = topoShape.splitWires(&inner, TopoShape::SplitWireReorient::ReorientReversed);
    // Assert
    EXPECT_EQ(inner.size(), 1);
    EXPECT_DOUBLE_EQ(getLength(wire.getShape()), 2 + 2 + 3 + 3);
    EXPECT_DOUBLE_EQ(getLength(inner.front().getShape()), std::numbers::pi * Rad * 2);
    EXPECT_EQ(wire.getShape().Orientation(), TopAbs_REVERSED);
    for (TopoShape& shape : inner) {
        EXPECT_EQ(shape.getShape().Orientation(), TopAbs_FORWARD);
    }
}

// Possible future tests:
// splitWires without inner Wires
// splitWires with all four reorientation values NoReorient, ReOrient, ReorientForward,
// ReorientReversed

TEST_F(TopoShapeExpansionTest, getSubShapes)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoTopoShapeCubes();
    // Act
    auto subShapes = cube1.getSubShapes();
    auto subShapes2 = cube1.getSubShapes(TopAbs_FACE);
    auto subShapes3 = cube1.getSubShapes(TopAbs_SHAPE, TopAbs_EDGE);
    // Assert
    EXPECT_EQ(subShapes.size(), 6);
    EXPECT_EQ(subShapes2.size(), 6);
    EXPECT_EQ(subShapes3.size(), 0);  // TODO:  Why doesn't this match the next test?
}

TEST_F(TopoShapeExpansionTest, getSubTopoShapes)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoTopoShapeCubes();
    // Act
    auto subShapes = cube1.getSubTopoShapes();
    auto subShapes2 = cube1.getSubTopoShapes(TopAbs_FACE);
    auto subShapes3 = cube1.getSubTopoShapes(TopAbs_SHAPE, TopAbs_EDGE);
    // Assert
    EXPECT_EQ(subShapes.size(), 6);
    EXPECT_EQ(subShapes2.size(), 6);
    EXPECT_EQ(subShapes3.size(), 6);
}

TEST_F(TopoShapeExpansionTest, getOrderedEdges)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoTopoShapeCubes();
    // Act
    auto subShapes = cube1.getOrderedEdges(MapElement::noMap);
    // Assert
    EXPECT_EQ(subShapes.size(), 24);
    //    EXPECT_THROW(cube1.getOrderedEdges(), NullShapeException);  // No Map
    EXPECT_EQ(subShapes.front().getElementMap().size(), 0);
    //    EXPECT_EQ(subShapes2.front().getElementMap().size(),2);
}

TEST_F(TopoShapeExpansionTest, getOrderedVertexes)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoTopoShapeCubes();
    // Act
    auto subShapes = cube1.getOrderedVertexes(MapElement::noMap);
    // Assert
    EXPECT_EQ(subShapes.size(), 24);
    //    EXPECT_THROW(cube1.getOrderedEdges(), NullShapeException);  // No Map
}

TEST_F(TopoShapeExpansionTest, getSubTopoShapeByEnum)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};

    // Act
    auto subShape = cube1TS.getSubTopoShape(TopAbs_FACE, 1);
    auto subShape2 = cube1TS.getSubTopoShape(TopAbs_FACE, 2);
    auto subShape3 = cube1TS.getSubTopoShape(TopAbs_FACE, 6);
    auto noshape1 = cube1TS.getSubTopoShape(TopAbs_FACE, 7, true);
    // Assert
    EXPECT_EQ(subShape.getShape().ShapeType(), TopAbs_FACE);
    EXPECT_EQ(subShape2.getShape().ShapeType(), TopAbs_FACE);
    EXPECT_EQ(subShape2.getShape().ShapeType(), TopAbs_FACE);
    EXPECT_TRUE(noshape1.isNull());
    EXPECT_THROW(cube1TS.getSubTopoShape(TopAbs_FACE, 7), Base::IndexError);  // Out of range
}

TEST_F(TopoShapeExpansionTest, getSubTopoShapeByStringDefaults)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    Part::TopoShape cube1TS {cube1, 1L};
    const float Len = 3;
    const float Wid = 2;
    auto [face1, wire1, edge1, edge2, edge3, edge4] = CreateRectFace(Len, Wid);
    TopoDS_Compound compound1;
    TopoDS_Builder builder {};
    builder.MakeCompound(compound1);
    builder.Add(compound1, face1);
    TopoShape topoShape {compound1, 2L};
    // Act
    auto subShape = cube1TS.getSubTopoShape(nullptr);
    auto subShape1 = cube1TS.getSubTopoShape("");
    auto subShape2 = topoShape.getSubTopoShape(nullptr);
    // Assert
    EXPECT_TRUE(subShape.getShape().IsEqual(cube1TS.getShape()));
    EXPECT_EQ(subShape.getShape().ShapeType(), TopAbs_SOLID);
    EXPECT_TRUE(subShape1.getShape().IsEqual(cube1TS.getShape()));
    EXPECT_EQ(subShape1.getShape().ShapeType(), TopAbs_SOLID);
    EXPECT_TRUE(subShape2.getShape().IsEqual(face1));
    EXPECT_EQ(subShape2.getShape().ShapeType(), TopAbs_FACE);
}

TEST_F(TopoShapeExpansionTest, getSubTopoShapeByStringNames)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};

    // Act
    auto subShape = cube1TS.getSubTopoShape("Face1");
    auto subShape2 = cube1TS.getSubTopoShape("Face2");
    auto subShape3 = cube1TS.getSubTopoShape("Face3");
    auto noshape1 = cube1TS.getSubTopoShape("Face7", true);  // Out of range
    // Assert
    EXPECT_EQ(subShape.getShape().ShapeType(), TopAbs_FACE);
    EXPECT_EQ(subShape2.getShape().ShapeType(), TopAbs_FACE);
    EXPECT_EQ(subShape3.getShape().ShapeType(), TopAbs_FACE);
    EXPECT_TRUE(noshape1.isNull());
    EXPECT_THROW(cube1TS.getSubTopoShape("Face7"), Base::IndexError);          // Out of range
    EXPECT_THROW(cube1TS.getSubTopoShape("WOOHOO", false), Base::ValueError);  // Invalid
}

TEST_F(TopoShapeExpansionTest, mapSubElementInvalidParm)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};
    TopoShape cube2TS {cube2, 2L};
    // Act
    std::vector<TopoShape> subShapes = cube1TS.getSubTopoShapes(TopAbs_FACE);
    TopoShape face1 = subShapes.front();
    face1.Tag = 3;
    cube1TS.mapSubElement(face1);
    cube2TS.mapSubElement(face1);
    // Assert
    EXPECT_EQ(cube1TS.getElementMap().size(), 9);  // Valid, the face is in Cube1
    EXPECT_EQ(cube2TS.getElementMap().size(), 0);  // Invalid, the face is not in Cube2
}

TEST_F(TopoShapeExpansionTest, mapSubElementFindShapeByNames)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1};
    TopoShape cube2TS {cube2};
    cube1TS.Tag = 1;
    cube2TS.Tag = 2;
    TopoShape topoShape;
    TopoShape topoShape1;

    // Act
    int fs1 = topoShape1.findShape(cube1);
    topoShape.setShape(cube2TS);
    topoShape1.makeElementCompound({cube1TS, cube2TS});
    int fs2 = topoShape1.findShape(cube1);

    TopoDS_Shape tds1 = topoShape.findShape("SubShape1");
    TopoDS_Shape tds2 = topoShape.findShape("SubShape2");  // Nonexistent
    TopoDS_Shape tds3 = topoShape1.findShape("SubShape1");
    TopoDS_Shape tds4 = topoShape1.findShape("SubShape2");
    TopoDS_Shape tds5 = topoShape1.findShape("NonExistentName");  // Invalid Name

    // Assert
    EXPECT_EQ(fs1, 0);
    EXPECT_EQ(fs2, 1);
    EXPECT_FALSE(tds1.IsNull());
    EXPECT_TRUE(tds2.IsNull());
    EXPECT_FALSE(tds3.IsNull());
    EXPECT_FALSE(tds4.IsNull());
    EXPECT_TRUE(tds5.IsNull());
}

TEST_F(TopoShapeExpansionTest, mapSubElementFindShapeByType)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1};
    TopoShape cube2TS {cube2};
    cube1TS.Tag = 1;
    cube2TS.Tag = 2;
    TopoShape topoShape;
    topoShape.makeElementCompound({cube1TS, cube2TS});
    topoShape.mapSubElement(cube2TS, "Name", false);

    // Act, Assert
    for (int i = 1; i <= 12; i++) {
        TopoDS_Shape dshape1 = topoShape.findShape(TopAbs_FACE, i);
        EXPECT_FALSE(dshape1.IsNull()) << "Face num " << i;
    }
    TopoDS_Shape dshape1 = topoShape.findShape(TopAbs_FACE, 13);
    EXPECT_TRUE(dshape1.IsNull());
}


TEST_F(TopoShapeExpansionTest, mapSubElementFindAncestor)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1};
    TopoShape cube2TS {cube2};
    cube1TS.Tag = 1;
    cube2TS.Tag = 2;
    TopoShape topoShape;
    topoShape.makeElementCompound({cube1TS, cube2TS});
    topoShape.mapSubElement(cube2TS, "Name", false);

    // Act
    int fa1 = topoShape.findAncestor(cube2, TopAbs_COMPOUND);
    TopoDS_Shape tds1 = topoShape.findAncestorShape(cube1, TopAbs_COMPOUND);

    // Assert
    EXPECT_EQ(fa1, 1);
    EXPECT_TRUE(tds1.IsEqual(topoShape.getShape()));
}


TEST_F(TopoShapeExpansionTest, mapSubElementFindAncestors)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto [cube3, cube4] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(0, 1, 0)));
    cube3.Move(TopLoc_Location(tr));
    cube4.Move(TopLoc_Location(tr));
    TopoShape cube1TS {cube1};
    TopoShape cube2TS {cube2};
    TopoShape cube3TS {cube3};
    TopoShape cube4TS {cube4};
    cube1TS.Tag = 1;
    cube2TS.Tag = 2;
    cube3TS.Tag = 3;
    cube4TS.Tag = 4;
    TopoShape topoShape;
    TopoShape topoShape1;
    TopoShape topoShape2;
    TopoShape topoShape3;
    TopoShape topoShape4;
    TopoShape topoShape5;
    TopoShape topoShape6;
    topoShape.makeElementCompound({cube1TS, cube2TS});
    topoShape1.makeElementCompound({cube3TS, cube4TS});
    topoShape2.makeElementCompound({cube1TS, cube3TS});
    topoShape3.makeElementCompound({cube2TS, cube4TS});
    topoShape4.makeElementCompound({topoShape, topoShape1});
    topoShape5.makeElementCompound({topoShape2, topoShape3});
    topoShape6.makeElementCompound({topoShape4, topoShape5});
    topoShape6.mapSubElement(cube2TS, nullptr, false);

    // Act
    auto ancestorList = topoShape6.findAncestors(cube3, TopAbs_COMPOUND);
    auto ancestorShapeList = topoShape6.findAncestorsShapes(cube3, TopAbs_COMPOUND);

    // FIXME:  It seems very strange that both of these ancestors calls return lists of two items
    // that contain the same thing twice.  What I expect is that the ancestors of cube3 would be
    // topoShape6 topoShape5, topoShape3, topoShape2, and topoShape1.
    //
    // This is a very convoluted hierarchy, and the only way I could get more than one result from
    // findAncestors.  I guess it's possible that it's only intended to return a single result in
    // almost all cases; that would mean that what it returns is the shape at the top of the tree.
    // But that's exactly the shape we use to call it in the first place, so we already have it.
    //
    // Note that in the RT branch, findAncestorsShapes is called by GenericShapeMapper::init,
    // TopoShape::makEChamfer and MapperPrism
    //  findAncestors is used in a dozen places.
    //

    // Assert
    EXPECT_EQ(ancestorList.size(), 2);
    EXPECT_EQ(ancestorList.front(), 1);
    EXPECT_EQ(ancestorList.back(), 1);
    EXPECT_EQ(ancestorShapeList.size(), 2);
    EXPECT_TRUE(ancestorShapeList.front().IsEqual(topoShape6.getShape()));
    EXPECT_TRUE(ancestorShapeList.back().IsEqual(topoShape6.getShape()));
}

TEST_F(TopoShapeExpansionTest, findSubShapesWithSharedVertexEverything)
{
    // Arrange
    auto [box1, box2] = CreateTwoCubes();
    TopoShape box1TS {box1};
    std::vector<std::string> names;
    std::vector<std::string> names1;
    std::vector<std::string> names2;
    double tol {2};  // Silly big tolerance to get everything
    double atol {2};

    TopExp_Explorer exp(box1, TopAbs_FACE);
    auto face = exp.Current();
    exp.Init(box1, TopAbs_EDGE);
    auto edge = exp.Current();
    exp.Init(box1, TopAbs_VERTEX);
    auto vertex = exp.Current();
    // Act
    auto shapes = box1TS.findSubShapesWithSharedVertex(
        face,
        &names,
        Data::SearchOption::CheckGeometry,
        tol,
        atol
    );
    auto shapes1 = box1TS.findSubShapesWithSharedVertex(
        edge,
        &names1,
        Data::SearchOption::CheckGeometry,
        tol,
        atol
    );
    auto shapes2 = box1TS.findSubShapesWithSharedVertex(
        vertex,
        &names2,
        Data::SearchOption::CheckGeometry,
        tol,
        atol
    );
    //  Assert
    EXPECT_EQ(shapes.size(), 6);
    EXPECT_EQ(names.size(), 6);
    EXPECT_STREQ(names[0].c_str(), "Face1");
    EXPECT_STREQ(names[1].c_str(), "Face3");
    EXPECT_STREQ(names[2].c_str(), "Face6");
    EXPECT_STREQ(names[3].c_str(), "Face5");
    EXPECT_STREQ(names[4].c_str(), "Face4");
    EXPECT_STREQ(names[5].c_str(), "Face2");
    EXPECT_EQ(shapes1.size(), 12);
    EXPECT_EQ(names1.size(), 12);
    EXPECT_EQ(shapes2.size(), 8);
    EXPECT_EQ(names2.size(), 8);
}

TEST_F(TopoShapeExpansionTest, findSubShapesWithSharedVertexMid)
{
    // Arrange
    auto [box1, box2] = CreateTwoCubes();
    TopoShape box1TS {box1};
    std::vector<std::string> names;
    std::vector<std::string> names1;
    std::vector<std::string> names2;
    double tol {1e-0};
    double atol {1e-04};

    TopExp_Explorer exp(box1, TopAbs_FACE);
    auto face = exp.Current();
    exp.Init(box1, TopAbs_EDGE);
    auto edge = exp.Current();
    exp.Init(box1, TopAbs_VERTEX);
    auto vertex = exp.Current();
    // Act
    auto shapes = box1TS.findSubShapesWithSharedVertex(
        face,
        &names,
        Data::SearchOption::CheckGeometry,
        tol,
        atol
    );
    auto shapes1 = box1TS.findSubShapesWithSharedVertex(
        edge,
        &names1,
        Data::SearchOption::CheckGeometry,
        tol,
        atol
    );
    auto shapes2 = box1TS.findSubShapesWithSharedVertex(
        vertex,
        &names2,
        Data::SearchOption::CheckGeometry,
        tol,
        atol
    );
    //  Assert
    EXPECT_EQ(shapes.size(), 6);
    EXPECT_EQ(names.size(), 6);
    EXPECT_EQ(shapes1.size(), 7);
    EXPECT_EQ(names1.size(), 7);
    EXPECT_EQ(shapes2.size(), 4);
    EXPECT_EQ(names2.size(), 4);
}

TEST_F(TopoShapeExpansionTest, findSubShapesWithSharedVertexClose)
{
    // Arrange
    auto [box1, box2] = CreateTwoCubes();
    TopoShape box1TS {box1};
    std::vector<std::string> names;
    std::vector<std::string> names1;
    std::vector<std::string> names2;
    double tol {1e-02};
    double atol {1e-04};

    TopExp_Explorer exp(box1, TopAbs_FACE);
    auto face = exp.Current();
    exp.Init(box1, TopAbs_EDGE);
    auto edge = exp.Current();
    exp.Init(box1, TopAbs_VERTEX);
    auto vertex = exp.Current();
    // Act
    auto shapes = box1TS.findSubShapesWithSharedVertex(
        face,
        &names,
        Data::SearchOption::CheckGeometry,
        tol,
        atol
    );
    auto shapes1 = box1TS.findSubShapesWithSharedVertex(
        edge,
        &names1,
        Data::SearchOption::CheckGeometry,
        tol,
        atol
    );
    auto shapes2 = box1TS.findSubShapesWithSharedVertex(
        vertex,
        &names2,
        Data::SearchOption::CheckGeometry,
        tol,
        atol
    );
    //  Assert
    EXPECT_EQ(shapes.size(), 1);
    EXPECT_EQ(names.size(), 1);
    EXPECT_EQ(shapes1.size(), 1);
    EXPECT_EQ(names1.size(), 1);
    EXPECT_EQ(shapes2.size(), 1);
    EXPECT_EQ(names2.size(), 1);
}

TEST_F(TopoShapeExpansionTest, makeElementShellInvalid)
{
    // Arrange
    TopoShape topoShape {1L};
    // Act / Assert
    EXPECT_THROW(topoShape.makeElementShell(false, nullptr), Base::CADKernelError);
}

TEST_F(TopoShapeExpansionTest, makeElementShellSingle)
{
    // Arrange
    const float Len = 3;
    const float Wid = 2;
    auto [face1, wire1, edge1, edge2, edge3, _] = CreateRectFace(Len, Wid);
    TopoShape topoShape {face1, 1L};
    // Act
    TopoShape result = topoShape.makeElementShell(false, nullptr);
    // Assert
    EXPECT_EQ(result.getShape().NbChildren(), 1);
    EXPECT_EQ(result.countSubElements("Vertex"), 4);
    EXPECT_EQ(result.countSubElements("Edge"), 4);
    EXPECT_EQ(result.countSubElements("Face"), 1);
    EXPECT_STREQ(result.shapeName().c_str(), "Shell");
}

TEST_F(TopoShapeExpansionTest, makeElementShellOpen)
{
    // Arrange
    const float Len = 3;
    const float Wid = 2;
    auto [face1, wire1, edge1, edge2, edge3, edge4] = CreateRectFace(Len, Wid);
    auto transform {gp_Trsf()};
    transform.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), std::numbers::pi / 2);
    auto face2 = face1;  // Shallow copy
    face2.Move(TopLoc_Location(transform));
    TopoDS_Compound compound1;
    TopoDS_Builder builder {};
    builder.MakeCompound(compound1);
    builder.Add(compound1, face1);
    builder.Add(compound1, face2);
    TopoShape topoShape {compound1, 1L};
    // Act
    TopoShape result = topoShape.makeElementShell(true, nullptr);
    // Assert
    EXPECT_EQ(result.getShape().NbChildren(), 2);
    EXPECT_EQ(result.countSubElements("Vertex"), 6);
    EXPECT_EQ(result.countSubElements("Edge"), 7);
    EXPECT_EQ(result.countSubElements("Face"), 2);
    EXPECT_STREQ(result.shapeName().c_str(), "Shell");
}

TEST_F(TopoShapeExpansionTest, makeElementShellClosed)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape topoShape {cube1};
    std::vector<TopoShape> shapes;
    for (const auto& face : topoShape.getSubShapes(TopAbs_FACE)) {
        shapes.emplace_back(face);
    }
    // Act
    TopoShape topoShape1 {1L};
    topoShape1.makeElementCompound(shapes, "D");
    // Assert
    TopoShape result = topoShape1.makeElementShell(false, "SH1");
    EXPECT_EQ(result.getShape().NbChildren(), 6);
    EXPECT_EQ(result.countSubElements("Vertex"), 8);
    EXPECT_EQ(result.countSubElements("Edge"), 12);
    EXPECT_EQ(result.countSubElements("Face"), 6);
    EXPECT_STREQ(result.shapeName().c_str(), "Shell");
}

TEST_F(TopoShapeExpansionTest, makeElementShellIntersecting)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto transform {gp_Trsf()};
    transform.SetTranslation(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(0.5, 0.5, 0.0));
    cube2.Move(TopLoc_Location(transform));
    TopoShape topoShape {cube1};
    std::vector<TopoShape> shapes;
    for (const auto& face : topoShape.getSubShapes(TopAbs_FACE)) {
        shapes.emplace_back(face);
    }
    topoShape.setShape(cube2);
    for (const auto& face : topoShape.getSubShapes(TopAbs_FACE)) {
        shapes.emplace_back(face);
    }
    // Act
    TopoShape topoShape1 {1L};
    topoShape1.makeElementCompound(shapes, "D");
    // Assert
    EXPECT_THROW(topoShape1.makeElementShell(false, nullptr), Base::CADKernelError);
}

TEST_F(TopoShapeExpansionTest, makeElementShellFromWires)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape topoShape {cube1};
    std::vector<TopoShape> shapes;
    for (const auto& face : topoShape.getSubShapes(TopAbs_WIRE)) {
        shapes.emplace_back(face);
    }
    // Act
    TopoShape topoShape1 {1L};
    topoShape1.makeElementCompound(shapes, "D");
    // Assert
    TopoShape result = topoShape1.makeElementShellFromWires(shapes);
    EXPECT_EQ(result.getShape().NbChildren(), 20);  // Have a NbChildren method?
    EXPECT_EQ(result.countSubElements("Vertex"), 8);
    EXPECT_EQ(result.countSubElements("Edge"), 32);
    EXPECT_EQ(result.countSubElements("Face"), 20);
    EXPECT_STREQ(result.shapeName().c_str(), "Shell");
}

TEST_F(TopoShapeExpansionTest, makeElementBooleanImpossibleCommon)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape topoShape1 {cube1, 1L};
    TopoShape topoShape2 {cube2, 2L};
    // Act
    TopoShape& result = topoShape1.makeElementBoolean(Part::OpCodes::Common, {topoShape1, topoShape2});
    auto elements = elementMap(result);
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 0);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 0);
}

TEST_F(TopoShapeExpansionTest, makeElementBooleanCommon)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {cube1, 1L};
    TopoShape topoShape2 {cube2, 2L};
    // Act
    TopoShape& result = topoShape1.makeElementBoolean(Part::OpCodes::Common, {topoShape1, topoShape2});
    auto elements = elementMap(result);
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 0.25);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 26);
    //   the common is the box 0.5 < x < 1, 0 < y < 0.5, 0 < z < 1. Its face at y = 0 is cube1's
    //   Face3 (y min), trimmed: it keeps that face's unmapped name, with op CMN
    EXPECT_TRUE(elementHasNames(
        result,
        elementAt(result, "Face", Base::Vector3d(0.75, 0, 0.5)).c_str(),
        {unmappedName("Face3", 1, "CMN")}
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementBooleanCommonWithCompoundToolV1)
{
    // Arrange
    TopoShape base {BRepPrimAPI_MakeCylinder(1.0, 2.0).Shape(), 1L};
    auto toolMaker
        = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(1.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0)), 1.2, 1.0);
    TopoShape tool {toolMaker.Shape(), 2L};
    TopoShape overlap {3L};
    overlap.makeElementBoolean(Part::OpCodes::Common, {base, tool});
    TopoShape remainder {4L};
    remainder.makeElementBoolean(Part::OpCodes::Cut, {tool, base});
    TopoShape compound {5L};
    compound.makeElementCompound({overlap, remainder});

    // Act
    TopoShape result {6L};
    result.makeElementBoolean(Part::OpCodes::Common, {base, compound});

    // Assert
    EXPECT_FALSE(result.isEmpty());
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), getVolume(overlap.getShape()));
}

TEST_F(TopoShapeExpansionTest, makeElementBooleanCut)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {App::HistoryAlgorithm::V1, cube1, 1L};
    TopoShape topoShape2 {App::HistoryAlgorithm::V1, cube2, 2L};
    // Act
    TopoShape& result = topoShape1.makeElementBoolean(Part::OpCodes::Cut, {topoShape1, topoShape2});
    auto elements = elementMap(result);
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 0.75);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 38);
    EXPECT_EQ(elements.count(IndexedName("Face", 1)), 1);
    EXPECT_TRUE(allElementsMatch(
        result,
        {
            "Edge1",
            "Edge10;:G(Edge2;K-1;:H2:4,E);CUT;:H1:1a,V",
            "Edge10;:M;CUT;:H1:7,E",
            "Edge11",
            "Edge11;:M;CUT;:H2:7,E",
            "Edge12",
            "Edge12;:M;CUT;:H2:7,E",
            "Edge2",
            "Edge2;:M;CUT;:H2:7,E",
            "Edge3",
            "Edge3;:M;CUT;:H2:7,E",
            "Edge4",
            "Edge4;:M;CUT;:H2:7,E",
            "Edge6;:G(Edge12;K-1;:H2:4,E);CUT;:H1:1b,V",
            "Edge6;:M;CUT;:H1:7,E",
            "Edge7",
            "Edge8;:G(Edge11;K-1;:H2:4,E);CUT;:H1:1b,V",
            "Edge8;:M;CUT;:H1:7,E",
            "Edge9;:G(Edge4;K-1;:H2:4,E);CUT;:H1:1a,V",
            "Edge9;:M;CUT;:H1:7,E",
            "Face1",
            "Face1;:M;CUT;:H2:7,F",
            "Face2;:G(Face4;K-1;:H2:4,F);CUT;:H1:1a,E",
            "Face2;:M;CUT;:H1:7,F",
            "Face3;:G(Face1;K-1;:H2:4,F);CUT;:H1:1a,E",
            "Face3;:M;CUT;:H1:7,F",
            "Face4",
            "Face4;:M;CUT;:H2:7,F",
            "Face5;:M;CUT;:H1:7,F",
            "Face6;:M;CUT;:H1:7,F",
            "Vertex1",
            "Vertex2",
            "Vertex3",
            "Vertex3;:M;CUT;:H2:7,V",
            "Vertex4",
            "Vertex4;:M;CUT;:H2:7,V",
            "Vertex7",
            "Vertex8",
        }
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementBooleanFuseV1)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {App::HistoryAlgorithm::V1, cube1, 1L};
    TopoShape topoShape2 {App::HistoryAlgorithm::V1, cube2, 2L};
    // Act
    TopoShape& result = topoShape1.makeElementBoolean(Part::OpCodes::Fuse, {topoShape1, topoShape2});
    auto elements = elementMap(result);
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 1.75);
    // Assert element map is correct
    EXPECT_EQ(elements.size(), 66);
    EXPECT_EQ(elements.count(IndexedName("Face", 1)), 1);
    EXPECT_TRUE(allElementsMatch(
        result,
        {
            "Edge1",
            "Edge10;:G(Edge2;K-1;:H2:4,E);FUS;:H1:1a,V",
            "Edge10;:H2,E",
            "Edge10;:M2;FUS;:H1:8,E",
            "Edge10;:M;FUS;:H1:7,E",
            "Edge11",
            "Edge11;:M2;FUS;:H2:8,E",
            "Edge11;:M;FUS;:H2:7,E",
            "Edge12",
            "Edge12;:M2;FUS;:H2:8,E",
            "Edge12;:M;FUS;:H2:7,E",
            "Edge1;:H2,E",
            "Edge2",
            "Edge2;:M2;FUS;:H2:8,E",
            "Edge2;:M;FUS;:H2:7,E",
            "Edge3",
            "Edge4",
            "Edge4;:M2;FUS;:H2:8,E",
            "Edge4;:M;FUS;:H2:7,E",
            "Edge5;:H2,E",
            "Edge6;:G(Edge12;K-1;:H2:4,E);FUS;:H1:1b,V",
            "Edge6;:H2,E",
            "Edge6;:M2;FUS;:H1:8,E",
            "Edge6;:M;FUS;:H1:7,E",
            "Edge7",
            "Edge7;:H2,E",
            "Edge8;:G(Edge11;K-1;:H2:4,E);FUS;:H1:1b,V",
            "Edge8;:H2,E",
            "Edge8;:M2;FUS;:H1:8,E",
            "Edge8;:M;FUS;:H1:7,E",
            "Edge9;:G(Edge4;K-1;:H2:4,E);FUS;:H1:1a,V",
            "Edge9;:H2,E",
            "Edge9;:M2;FUS;:H1:8,E",
            "Edge9;:M;FUS;:H1:7,E",
            "Face1",
            "Face1;:M;FUS;:H2:7,F",
            "Face2;:G(Face4;K-1;:H2:4,F);FUS;:H1:1a,E",
            "Face2;:H2,F",
            "Face2;:M;FUS;:H1:7,F",
            "Face3;:G(Face1;K-1;:H2:4,F);FUS;:H1:1a,E",
            "Face3;:H2,F",
            "Face3;:M;FUS;:H1:7,F",
            "Face4",
            "Face4;:M;FUS;:H2:7,F",
            "Face5;:M2(Face5;K2;:H2:3,F);FUS;:H1:1a,F",
            "Face5;:M;FUS;:H1:7,F",
            "Face5;:M;FUS;:H2:7,F",
            "Face6;:M2(Face6;K2;:H2:3,F);FUS;:H1:1a,F",
            "Face6;:M;FUS;:H1:7,F",
            "Face6;:M;FUS;:H2:7,F",
            "Vertex1",
            "Vertex1;:H2,V",
            "Vertex2",
            "Vertex2;:H2,V",
            "Vertex3",
            "Vertex3;:M;FUS;:H2:7,V",
            "Vertex4",
            "Vertex4;:M;FUS;:H2:7,V",
            "Vertex5;:H2,V",
            "Vertex5;:M;FUS;:H1:7,V",
            "Vertex6;:H2,V",
            "Vertex6;:M;FUS;:H1:7,V",
            "Vertex7",
            "Vertex7;:H2,V",
            "Vertex8",
            "Vertex8;:H2,V",
        }
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementDraft)
{  // Draft as in Draft Angle or sloped sides for removing shapes from a mold.
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};
    std::vector<TopoShape> subShapes = cube1TS.getSubTopoShapes(TopAbs_FACE);
    std::vector<TopoShape> faces {subShapes[0], subShapes[1], subShapes[2], subShapes[3]};
    const gp_Dir pullDirection {0, 0, 1};
    double angle {std::numbers::pi * 10 / 8};  // Angle should be between Pi and Pi * 1.5 ( 180 and
                                               // 270 degrees )
    const gp_Pln plane {};
    // Act
    TopoShape& result = cube1TS.makeElementDraft(cube1TS, faces, pullDirection, angle, plane);
    auto elements = elementMap(result);
    // Assert
    EXPECT_NEAR(getVolume(result.getShape()), 4.3333333333, 1e-06);  // Truncated pyramid
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 26);  // Cubes have 6 Faces, 12 Edges, 8 Vertexes
    //   the cube has no names. Each drafted side face is generated from the cube face it replaces
    //   (whose unmapped name carries the op); the bottom and top faces are modified and keep
    //   their unmapped names. Box faces: Face1 x min, Face2 x max, Face3 y min, Face4 y max,
    //   Face5 z min, Face6 z max.
    auto face = [&](const std::function<bool(const Base::Vector3d&)>& isAt) {
        return elementWhere(result, "Face", isAt);
    };
    auto isNear = [](double value, double target) {
        return std::abs(value - target) < Base::Precision::Confusion();
    };
    std::map<std::string, std::string> sides {
        {"Face1", face([&](auto c) { return c.x < 0.4 && isNear(c.y, 0.5); })},
        {"Face2", face([&](auto c) { return c.x > 0.6 && isNear(c.y, 0.5); })},
        {"Face3", face([&](auto c) { return c.y < 0.4 && isNear(c.x, 0.5); })},
        {"Face4", face([&](auto c) { return c.y > 0.6 && isNear(c.x, 0.5); })},
    };
    for (const auto& [cubeFace, draftedFace] : sides) {
        EXPECT_TRUE(elementHasNames(
            result,
            draftedFace.c_str(),
            {linkingName({unmappedName(cubeFace, 1, "DFT")}, 1, "DFT", 'F', MAPPER_FLAG_GENERATED)}
        ));
    }
    EXPECT_TRUE(elementHasNames(
        result,
        elementAt(result, "Face", Base::Vector3d(0.5, 0.5, 0)).c_str(),
        {unmappedName("Face5", 1, "DFT")}
    ));
    EXPECT_TRUE(elementHasNames(
        result,
        elementAt(result, "Face", Base::Vector3d(0.5, 0.5, 1)).c_str(),
        {unmappedName("Face6", 1, "DFT")}
    ));
    //   the edges and vertices have no history: each is named after the faces it bounds (UPP)
    EXPECT_TRUE(upperNamed(result, "Edge", 1, "DFT"));
    EXPECT_TRUE(upperNamed(result, "Vertex", 1, "DFT"));
}

TEST_F(TopoShapeExpansionTest, makeElementDraftTopoShapes)
{
    // Arrange
    auto [cube1TS, cube2TS] = CreateTwoTopoShapeCubes();
    const gp_Dir pullDirection {0, 0, 1};
    double angle {std::numbers::pi * 10 / 8};  // Angle should be between Pi and Pi * 1.5 ( 180 and
                                               // 270 degrees )
    const gp_Pln plane {};
    // Act
    TopoShape result3 = cube1TS.makeElementDraft(
        cube1TS.getSubTopoShapes(TopAbs_FACE),
        pullDirection,
        angle,
        plane
    );  // Non Reference call type
    TopoShape result2 = cube1TS.makeElementDraft(
        cube1TS,
        cube1TS.getSubTopoShapes(TopAbs_FACE),
        pullDirection,
        angle,
        plane
    );  // Bad use of Reference call
    TopoShape& result = cube1TS.makeElementDraft(
        cube2TS,
        cube2TS.getSubTopoShapes(TopAbs_FACE),
        pullDirection,
        angle,
        plane
    );  // Correct usage
    // Assert
    EXPECT_TRUE(result.getMappedChildElements().empty());
    EXPECT_NEAR(getVolume(result.getShape()), 4.3333333333, 1e-06);  // Truncated pyramid
    EXPECT_TRUE(allElementsNamed(result));
    EXPECT_TRUE(allElementsNamed(result2));
    EXPECT_TRUE(allElementsNamed(result3));
    //   the cube (x from 1 to 2) has names. Each drafted side face is generated from the cube
    //   face it replaces, linking that face's name, with the result's tag (cube1TS's, 7); the
    //   bottom and top faces keep their names as they are
    EXPECT_EQ(result.Tag, 7);
    auto isNear = [](double value, double target) {
        return std::abs(value - target) < Base::Precision::Confusion();
    };
    std::map<int, std::function<bool(const Base::Vector3d&)>> sides {
        {1, [&](auto c) { return c.x < 1.4 && isNear(c.y, 0.5); }},
        {2, [&](auto c) { return c.x > 1.6 && isNear(c.y, 0.5); }},
        {3, [&](auto c) { return c.y < 0.4 && isNear(c.x, 1.5); }},
        {4, [&](auto c) { return c.y > 0.6 && isNear(c.x, 1.5); }},
    };
    for (const auto& [cubeFace, isAt] : sides) {
        auto cubeFaceName = cube2TS.getMappedName(IndexedName::fromConst("Face", cubeFace));
        EXPECT_TRUE(elementHasNames(
            result,
            elementWhere(result, "Face", isAt).c_str(),
            {linkingName({cubeFaceName}, 7, "DFT", 'F', MAPPER_FLAG_GENERATED)}
        ));
    }
    EXPECT_TRUE(elementHasNames(
        result,
        elementAt(result, "Face", Base::Vector3d(1.5, 0.5, 0)).c_str(),
        {cube2TS.getMappedName(IndexedName::fromConst("Face", 5))}
    ));
    EXPECT_TRUE(elementHasNames(
        result,
        elementAt(result, "Face", Base::Vector3d(1.5, 0.5, 1)).c_str(),
        {cube2TS.getMappedName(IndexedName::fromConst("Face", 6))}
    ));
    //   the edges and vertices have no history: each is named after the faces it bounds (UPP)
    EXPECT_TRUE(upperNamed(result, "Edge", 7, "DFT"));
    EXPECT_TRUE(upperNamed(result, "Vertex", 7, "DFT"));
}

TEST_F(TopoShapeExpansionTest, linearizeEdge)
{
    // Arrange
    TColgp_Array1OfPnt points {1, 2};
    points.SetValue(1, gp_Pnt(0.0, 0.0, 0.0));
    points.SetValue(2, gp_Pnt(1.0, 0.0, 0.0));
    auto line1 = new Geom_BezierCurve(points);
    auto edge1 = BRepBuilderAPI_MakeEdge(line1).Edge();
    TopoShape topoShape1 {edge1, 1L};
    // Act
    auto edges = topoShape1.getSubTopoShapes(TopAbs_EDGE);
    BRepAdaptor_Curve curve(TopoDS::Edge(edges.front().getShape()));
    topoShape1.linearize(LinearizeFace::noFaces, LinearizeEdge::linearizeEdges);
    auto edges2 = topoShape1.getSubTopoShapes(TopAbs_EDGE);
    BRepAdaptor_Curve curve2(TopoDS::Edge(edges2.front().getShape()));
    // Assert
    EXPECT_EQ(curve.GetType(), GeomAbs_BezierCurve);
    EXPECT_EQ(curve2.GetType(), GeomAbs_Line);
}

TEST_F(TopoShapeExpansionTest, linearizeFace)
{
    TColgp_Array2OfPnt points2 {1, 2, 1, 2};
    points2.SetValue(1, 1, gp_Pnt(0.0, 0.0, 0.0));
    points2.SetValue(2, 1, gp_Pnt(1.0, 0.0, 0.0));
    points2.SetValue(1, 2, gp_Pnt(0.0, 1.0, 0.0));
    points2.SetValue(2, 2, gp_Pnt(1.0, 1.0, 0.0));
    auto face1 = new Geom_BezierSurface(points2);
    auto surf1 = BRepBuilderAPI_MakeFace(face1, 0.1).Face();
    TopoShape topoShape2 {surf1, 2L};
    // Act
    auto faces = topoShape2.getSubTopoShapes(TopAbs_FACE);
    BRepAdaptor_Surface surface(TopoDS::Face(faces.front().getShape()));
    topoShape2.linearize(LinearizeFace::linearizeFaces, LinearizeEdge::noEdges);
    auto faces2 = topoShape2.getSubTopoShapes(TopAbs_FACE);
    BRepAdaptor_Surface surface2(TopoDS::Face(faces.front().getShape()));
    // Assert
    EXPECT_EQ(surface.GetType(), GeomAbs_BezierSurface);
    EXPECT_EQ(surface2.GetType(), GeomAbs_Plane);
}

TEST_F(TopoShapeExpansionTest, makeElementRuledSurfaceEdgesV1)
{
    // Arrange
    auto edge1 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(0.0, 0.0, 8.0)).Edge();
    auto edge2 = BRepBuilderAPI_MakeEdge(gp_Pnt(2.5, 0.0, 0.0), gp_Pnt(2.5, 0.0, 8.0)).Edge();
    TopoShape edge1ts {App::HistoryAlgorithm::V1, edge1, 2L};
    TopoShape edge2ts {App::HistoryAlgorithm::V1, edge2, 3L};
    TopoShape topoShape {App::HistoryAlgorithm::V1, 1L};
    // Act
    topoShape.makeElementRuledSurface({edge1ts, edge2ts}, 0);  // TODO: orientation as enum?
    auto elements = elementMap(topoShape);
    // Assert shape is correct
    EXPECT_EQ(topoShape.countSubElements("Wire"), 1);
    EXPECT_FLOAT_EQ(getArea(topoShape.getShape()), 20);
    // Assert that we're creating a correct element map
    EXPECT_TRUE(topoShape.getMappedChildElements().empty());
    EXPECT_EQ(elements.size(), 9);
    EXPECT_EQ(elements.count(IndexedName("Edge", 1)), 1);
    EXPECT_TRUE(allElementsMatch(
        topoShape,
        {
            "Edge1",
            "Edge1;:L(Edge1;D1|Vertex1;:L(Vertex1;D1);RSF|Vertex2;:L(Vertex2;D1);RSF);RSF",
            "Edge1;D1",
            "Vertex1",
            "Vertex1;:L(Vertex1;D1);RSF",
            "Vertex1;D1",
            "Vertex2",
            "Vertex2;:L(Vertex2;D1);RSF",
            "Vertex2;D1",
        }
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementRuledSurfaceWiresV1)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {App::HistoryAlgorithm::V1, cube1, 1L};
    std::vector<TopoShape> subWires = cube1TS.getSubTopoShapes(TopAbs_WIRE);
    // Act
    auto surface = cube1TS.makeElementRuledSurface(
        {subWires[0], subWires[1]},
        0
    );  // TODO: orientation as enum?
    auto elements = elementMap(surface);
    // Assert
    EXPECT_EQ(surface.countSubElements("Wire"), 4);
    EXPECT_NEAR(getArea(surface.getShape()), 4, 1e-7);
    // Assert that we're creating a correct element map
    EXPECT_TRUE(surface.getMappedChildElements().empty());
    EXPECT_EQ(elements.size(), 24);
    EXPECT_EQ(elements.count(IndexedName("Edge", 1)), 1);
    EXPECT_TRUE(elementsMatch(  // Depending on OCCT versions can get 24 or 28 entries here.
        surface,
        {
            "Edge1",
            "Edge1;:L(Edge1;D1|Vertex1;:L(Vertex1;D1);RSF|Vertex2;:L(Vertex2;D1);RSF);RSF",
            "Edge1;D1",
            "Edge2",
            "Edge2;:L(Edge2;D1|Vertex1;:L(Vertex1;D1);RSF|Vertex3;:L(Vertex3;D1);RSF);RSF",
            "Edge2;D1",
            "Edge3",
            "Edge3;:L(Edge3;D1|Vertex3;:L(Vertex3;D1);RSF|Vertex4;:L(Vertex4;D1);RSF);RSF",
            "Edge3;D1",
            "Edge4",
            "Edge4;:L(Edge4;D1|Vertex2;:L(Vertex2;D1);RSF|Vertex4;:L(Vertex4;D1);RSF);RSF",
            "Edge4;D1",
            "Vertex1",
            "Vertex1;:L(Vertex1;D1);RSF",
            "Vertex1;D1",
            "Vertex2",
            "Vertex2;:L(Vertex2;D1);RSF",
            "Vertex2;D1",
            "Vertex3",
            "Vertex3;:L(Vertex3;D1);RSF",
            "Vertex3;D1",
            "Vertex4",
            "Vertex4;:L(Vertex4;D1);RSF",
            "Vertex4;D1",
        }));
}

TEST_F(TopoShapeExpansionTest, makeElementLoftV1)
{
    // Loft must have either all open or all closed sections to work, we'll do two closed.
    // Arrange
    const float Len = 5;
    const float Wid = 5;
    auto [face1, wire1, edge1, edge2, edge3, edge4] = CreateRectFace(Len, Wid);
    auto transform {gp_Trsf()};
    transform.SetTranslation(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(0.0, 0.0, 10.0));
    auto wire2 = wire1;  // Shallow copy
    wire2.Move(TopLoc_Location(transform));
    TopoShape wire1ts {App::HistoryAlgorithm::V1, wire1, 1L};  // One of these shapes should have a
                                                               // tag or else we won't get an
                                                               // Element Map
    TopoShape wire2ts {App::HistoryAlgorithm::V1, wire2, 2L};  // If you change either tag or
                                                               // eliminate one it changes the
                                                               // resulting name.
    std::vector<TopoShape> shapes = {wire1ts, wire2ts};
    // Act
    auto& topoShape = (new TopoShape(App::HistoryAlgorithm::V1))
                          ->makeElementLoft(shapes, IsSolid::notSolid, IsRuled::notRuled);
    auto& topoShape2 = (new TopoShape(App::HistoryAlgorithm::V1))
                           ->makeElementLoft(shapes, IsSolid::solid, IsRuled::notRuled);
    auto& topoShape3 = (new TopoShape(App::HistoryAlgorithm::V1))
                           ->makeElementLoft(shapes, IsSolid::notSolid, IsRuled::ruled);
    auto& topoShape4 = (new TopoShape(App::HistoryAlgorithm::V1))
                           ->makeElementLoft(shapes, IsSolid::solid, IsRuled::ruled);
    auto& topoShape5
        = (new TopoShape(App::HistoryAlgorithm::V1))
              ->makeElementLoft(shapes, IsSolid::notSolid, IsRuled::notRuled, IsClosed::closed);
    auto elements = elementMap((topoShape));
    // Assert that we haven't broken the basic Loft functionality
    EXPECT_EQ(topoShape.countSubElements("Wire"), 4);
    EXPECT_DOUBLE_EQ(getArea(topoShape.getShape()), 200);
    EXPECT_NEAR(getVolume(topoShape.getShape()), 166.66667, 1e-5);
    EXPECT_DOUBLE_EQ(getVolume(topoShape2.getShape()), 250);
    EXPECT_NEAR(getVolume(topoShape3.getShape()), 166.66667, 1e-5);
    EXPECT_DOUBLE_EQ(getVolume(topoShape4.getShape()), 250);
    EXPECT_NEAR(getVolume(topoShape5.getShape()), 0, 1e-07);
    // Assert that we're creating a correct element map
    EXPECT_TRUE(topoShape.getMappedChildElements().empty());
    EXPECT_EQ(elements.size(), 24);
    EXPECT_TRUE(allElementsMatch(
        topoShape,
        {
            "Edge1;:G(Edge1;K-1;:H2:4,E);LFT;:H1:1a,F",     "Edge1;:H1,E",   "Edge1;:H2,E",
            "Edge2;:G(Edge2;K-1;:H2:4,E);LFT;:H1:1a,F",     "Edge2;:H1,E",   "Edge2;:H2,E",
            "Edge3;:G(Edge3;K-1;:H2:4,E);LFT;:H1:1a,F",     "Edge3;:H1,E",   "Edge3;:H2,E",
            "Edge4;:G(Edge4;K-1;:H2:4,E);LFT;:H1:1a,F",     "Edge4;:H1,E",   "Edge4;:H2,E",
            "Vertex1;:G(Vertex1;K-1;:H2:4,V);LFT;:H1:1c,E", "Vertex1;:H1,V", "Vertex1;:H2,V",
            "Vertex2;:G(Vertex2;K-1;:H2:4,V);LFT;:H1:1c,E", "Vertex2;:H1,V", "Vertex2;:H2,V",
            "Vertex3;:G(Vertex3;K-1;:H2:4,V);LFT;:H1:1c,E", "Vertex3;:H1,V", "Vertex3;:H2,V",
            "Vertex4;:G(Vertex4;K-1;:H2:4,V);LFT;:H1:1c,E", "Vertex4;:H1,V", "Vertex4;:H2,V",
        }
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementLoftAllowsDistinctProfilesWithSameCenter)  // NOLINT
{
    // Regression test for PR #29982 / forum thread t=88234.  The fix for issue #5855 rejected any
    // two consecutive loft profiles that share a center of gravity, which is too strict: two
    // concentric, coplanar squares of different size share the center (2.5, 2.5, 0) but are clearly
    // distinct shapes, so the loft between them must still be created.
    //
    // See also test makeElementLoftRejectsCoincidentProfiles, below, to confirm that 5855 is still
    // fixed

    // Arrange
    auto [face1, wire1, edge1, edge2, edge3, edge4] = CreateRectFace(5, 5);  // 5x5, CoG (2.5,2.5,0)
    auto scale {gp_Trsf()};
    scale.SetScale(gp_Pnt(2.5, 2.5, 0.0), 2.0);  // 10x10 square, same CoG
    auto biggerWire = BRepBuilderAPI_Transform(wire1, scale, true).Shape();
    TopoShape smallerProfile {wire1, 1L};
    TopoShape biggerProfile {biggerWire, 2L};
    std::vector<TopoShape> shapes = {smallerProfile, biggerProfile};

    // Act: the previous code raised Base::CADKernelError here because the centers of gravity match.
    auto* loft = new TopoShape();
    ASSERT_NO_THROW(loft->makeElementLoft(shapes, IsSolid::notSolid, IsRuled::ruled));  // NOLINT

    // Assert: the result is the flat frame between the 5x5 and the 10x10 square.
    EXPECT_FALSE(loft->isNull());
    EXPECT_NEAR(getArea(loft->getShape()), 10.0 * 10.0 - 5.0 * 5.0, 1e-6);
}

TEST_F(TopoShapeExpansionTest, makeElementLoftRejectsCoincidentProfiles)  // NOLINT
{
    // The fix for issue #5855 must still hold: lofting through coincident profiles (for example the
    // same sketch used as more than one section) crashes OCCT, so makeElementLoft has to reject it.
    //
    // See also makeElementLoftAllowsDistinctProfilesWithSameCenter, above

    // Arrange
    auto [face1, wire1, edge1, edge2, edge3, edge4] = CreateRectFace(5, 5);
    TopoShape firstProfile {wire1, 1L};
    TopoShape secondProfile {wire1, 2L};
    std::vector<TopoShape> shapes = {firstProfile, secondProfile};

    // Act / Assert
    EXPECT_THROW(  // NOLINT
        (new TopoShape())->makeElementLoft(shapes, IsSolid::notSolid, IsRuled::notRuled),
        Base::CADKernelError
    );
}

TEST_F(TopoShapeExpansionTest, makeElementPipeShell)
{
    // Arrange
    const float Len = 5;
    const float Wid = 5;
    auto [face1, wire1, edge1, edge2, edge3, edge4] = CreateRectFace(Len, Wid);
    auto edge5 = BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(0.0, 0.0, -8.0)).Edge();
    auto wire2 = BRepBuilderAPI_MakeWire({edge5}).Wire();
    TopoShape face1ts {face1, 1L};
    TopoShape edge5ts {edge5, 2L};
    std::vector<TopoShape> shapes = {face1ts, edge5ts};
    // Act
    auto& topoShape = (new TopoShape())->makeElementPipeShell(shapes, MakeSolid::noSolid, false);
    auto elements = elementMap((topoShape));
    // Assert that we haven't broken the basic Loft functionality
    EXPECT_EQ(topoShape.countSubElements("Wire"), 4);
    EXPECT_DOUBLE_EQ(getArea(topoShape.getShape()), 160);
    EXPECT_NEAR(getVolume(topoShape.getShape()), 133.33334, 1e-5);
    // Assert that we're creating a correct element map
    EXPECT_TRUE(topoShape.getMappedChildElements().empty());
    EXPECT_EQ(elements.size(), 24);
    //   the first input is the spine, the rectangle's closed wire (tag 1), the second the profile,
    //   the line (tag 2). The result has no tag, so its sections take the first input tag (1).
    //   The inputs have no names: they are linked by their elements' unmapped names, with op PSH.
    //   Each side face is generated from a spine edge and the profile's edge
    for (int index = 1; index <= 4; ++index) {
        auto profileEdge = "Edge" + std::to_string(index);
        auto center = face1ts.getSubTopoShape(profileEdge.c_str()).getBoundBox().GetCenter();
        EXPECT_TRUE(elementHasNames(
            topoShape,
            elementAt(topoShape, "Face", Base::Vector3d(center.x, center.y, -4)).c_str(),
            {linkingName(
                {unmappedName(profileEdge, 1, "PSH"), unmappedName("Edge1", 2, "PSH")},
                1,
                "PSH",
                'F',
                MAPPER_FLAG_GENERATED
            )}
        ));
    }
    //   the profile placed at each spine vertex: OCCT reports it as generated from that vertex, but
    //   the spine's vertices name nothing (ops#375). The spine is closed, so the shell ends where it
    //   starts, and that edge is the profile's own; the others have no history: each is named
    //   after the side faces it bounds (UPP)
    for (int index = 1; index <= 4; ++index) {
        auto spineVertex = "Vertex" + std::to_string(index);
        auto point = face1ts.getSubTopoShape(spineVertex.c_str()).getBoundBox().GetCenter();
        auto edge = elementAt(topoShape, "Edge", Base::Vector3d(point.x, point.y, -4));
        EXPECT_TRUE(elementHasNames(
            topoShape,
            edge.c_str(),
            {index == 1 ? unmappedName("Edge1", 2, "PSH") : upperName(topoShape, edge, 1, "PSH")}
        ));
    }
    //   each profile vertex generates an edge along each spine edge, named after both, as a side
    //   face is after its spine edge and profile edge (fork PR 352 round 1; before, the four were
    //   told apart by an index in the result's edge order)
    for (auto [profileVertex, z] : {std::pair {"Vertex1", 0.0}, std::pair {"Vertex2", -8.0}}) {
        for (int index = 1; index <= 4; ++index) {
            auto spineEdge = "Edge" + std::to_string(index);
            auto center = face1ts.getSubTopoShape(spineEdge.c_str()).getBoundBox().GetCenter();
            EXPECT_TRUE(elementHasNames(
                topoShape,
                elementAt(topoShape, "Edge", Base::Vector3d(center.x, center.y, z)).c_str(),
                {linkingName(
                    {unmappedName(spineEdge, 1, "PSH"), unmappedName(profileVertex, 2, "PSH")},
                    1,
                    "PSH",
                    'E',
                    MAPPER_FLAG_GENERATED
                )}
            ));
        }
    }
    //   the vertices: the profile's own at the start (the line's ends), the others named after the
    //   faces they bound (UPP), those at z = 0 and z = -8 between the same faces told apart by the
    //   index
    auto vertices = static_cast<int>(topoShape.countSubElements("Vertex"));
    for (int index = 1; index <= vertices; ++index) {
        auto vertex = "Vertex" + std::to_string(index);
        auto point = topoShape.getSubTopoShape(vertex.c_str()).getBoundBox().GetCenter();
        if (std::abs(point.x) < 1e-7 && std::abs(point.y) < 1e-7) {
            auto profileVertex = std::abs(point.z) < 1e-7 ? "Vertex1" : "Vertex2";
            EXPECT_TRUE(elementHasNames(topoShape, vertex.c_str(), {unmappedName(profileVertex, 2, "PSH")}));
            continue;
        }
        bool upper = false;
        for (int rank = 0; rank < 4 && !upper; ++rank) {
            upper = elementHasNames(topoShape, vertex.c_str(), {upperName(topoShape, vertex, 1, "PSH", rank)});
        }
        EXPECT_TRUE(upper) << vertex;
    }
}

TEST_F(TopoShapeExpansionTest, makeElementThickSolid)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};
    std::vector<TopoShape> subFaces = cube1TS.getSubTopoShapes(TopAbs_FACE);
    subFaces[0].Tag = 2L;
    subFaces[1].Tag = 3L;
    std::vector<TopoShape> shapes = {subFaces[0], subFaces[1]};
    // Act
    TopoShape& result = cube1TS.makeElementThickSolid(cube1TS, shapes, 0.1, 1e-07);
    (void)result;
    auto elements = elementMap(cube1TS);
    // Assert
    EXPECT_EQ(cube1TS.countSubElements("Wire"), 16);
    EXPECT_NEAR(getArea(cube1TS.getShape()), 9.4911509, 1e-6);
    // Assert that we're creating a correct element map
    EXPECT_TRUE(cube1TS.getMappedChildElements().empty());
    EXPECT_EQ(elements.size(), 74);
    EXPECT_EQ(elements.count(IndexedName("Edge", 1)), 1);

    // Note:  Cannot do an elementsMatch here because the oldest OCCT treats ThickSolid a little
    // differently.  So, just mae sure the size is right, and something has a THK in it.
    for (auto& element : elements) {
        if (element.second.find("THK") > 0) {
            EXPECT_TRUE(1);
            break;
        };
    }
}

TEST_F(TopoShapeExpansionTest, makeElementGeneralFuse)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {App::HistoryAlgorithm::V1, cube1, 1L};
    TopoShape topoShape2 {App::HistoryAlgorithm::V1, cube2, 2L};
    // Act
    std::vector<std::vector<TopoShape>> modified {{}};
    TopoShape& result = topoShape1.makeElementGeneralFuse({topoShape1, topoShape2}, modified);

    auto elements = elementMap(result);
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 1.75);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 72);
    EXPECT_EQ(elements.count(IndexedName("Face", 1)), 1);
    EXPECT_TRUE(allElementsMatch(
        result,
        {
            "Edge1",
            "Edge10;:G(Edge2;K-1;:H2:4,E);GFS;:H1:1a,V",
            "Edge10;:H2,E",
            "Edge10;:M2;GFS;:H1:8,E",
            "Edge10;:M;GFS;:H1:7,E",
            "Edge11",
            "Edge11;:M2;GFS;:H2:8,E",
            "Edge11;:M;GFS;:H2:7,E",
            "Edge12",
            "Edge12;:M2;GFS;:H2:8,E",
            "Edge12;:M;GFS;:H2:7,E",
            "Edge1;:H2,E",
            "Edge2",
            "Edge2;:M2;GFS;:H2:8,E",
            "Edge2;:M;GFS;:H2:7,E",
            "Edge3",
            "Edge3;:M;GFS;:H2:7,E",
            "Edge4",
            "Edge4;:M2;GFS;:H2:8,E",
            "Edge4;:M;GFS;:H2:7,E",
            "Edge5;:H2,E",
            "Edge5;:M;GFS;:H1:7,E",
            "Edge6;:G(Edge12;K-1;:H2:4,E);GFS;:H1:1b,V",
            "Edge6;:H2,E",
            "Edge6;:M2;GFS;:H1:8,E",
            "Edge6;:M;GFS;:H1:7,E",
            "Edge7",
            "Edge7;:H2,E",
            "Edge8;:G(Edge11;K-1;:H2:4,E);GFS;:H1:1b,V",
            "Edge8;:H2,E",
            "Edge8;:M2;GFS;:H1:8,E",
            "Edge8;:M;GFS;:H1:7,E",
            "Edge9;:G(Edge4;K-1;:H2:4,E);GFS;:H1:1a,V",
            "Edge9;:H2,E",
            "Edge9;:M2;GFS;:H1:8,E",
            "Edge9;:M;GFS;:H1:7,E",
            "Face1",
            "Face1;:M2;GFS;:H2:8,F",
            "Face1;:M;GFS;:H2:7,F",
            "Face2;:G(Face4;K-1;:H2:4,F);GFS;:H1:1a,E",
            "Face2;:H2,F",
            "Face2;:M2;GFS;:H1:8,F",
            "Face2;:M;GFS;:H1:7,F",
            "Face3;:G(Face1;K-1;:H2:4,F);GFS;:H1:1a,E",
            "Face3;:H2,F",
            "Face3;:M2;GFS;:H1:8,F",
            "Face3;:M;GFS;:H1:7,F",
            "Face4",
            "Face4;:M2;GFS;:H2:8,F",
            "Face4;:M;GFS;:H2:7,F",
            "Face5;:M2(Face5;K2;:H2:3,F);GFS;:H1:1a,F",
            "Face5;:M;GFS;:H1:7,F",
            "Face5;:M;GFS;:H2:7,F",
            "Face6;:M2(Face6;K2;:H2:3,F);GFS;:H1:1a,F",
            "Face6;:M;GFS;:H1:7,F",
            "Face6;:M;GFS;:H2:7,F",
            "Vertex1",
            "Vertex1;:H2,V",
            "Vertex2",
            "Vertex2;:H2,V",
            "Vertex3",
            "Vertex3;:M;GFS;:H2:7,V",
            "Vertex4",
            "Vertex4;:M;GFS;:H2:7,V",
            "Vertex5;:H2,V",
            "Vertex5;:M;GFS;:H1:7,V",
            "Vertex6;:H2,V",
            "Vertex6;:M;GFS;:H1:7,V",
            "Vertex7",
            "Vertex7;:H2,V",
            "Vertex8",
            "Vertex8;:H2,V",
        }
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementFuse)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {cube1, 1L};
    TopoShape topoShape2 {cube2, 2L};
    // Act
    TopoShape& result = topoShape1.makeElementFuse({topoShape1, topoShape2});  // op, tolerance
    auto elements = elementMap(result);
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 1.75);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 66);
    //   neither cube has names. Every element of the fuse is one of theirs, kept (MKR), trimmed
    //   (FUS) or split: the cubes' tops and bottoms, and the edges crossing into the other cube,
    //   are split into pieces, which add a MOD section. The squares where the cubes' tops and
    //   bottoms overlap lie on a face of each cube and have no history of their own: they are
    //   named after their edges (LOW). The rest is made where elements of the two cubes meet:
    //   the edges at x = 0.5 and y = 0.5 (GEN from a face of each cube) and the vertices at
    //   their ends (GEN from an edge of each cube)
    EXPECT_EQ(result.countSubElements("Vertex"), 20);
    EXPECT_EQ(result.countSubElements("Edge"), 32);
    EXPECT_EQ(result.countSubElements("Face"), 14);
    EXPECT_TRUE(namedAsBoolean(result, {{1, TopoShape(cube1)}, {2, TopoShape(cube2)}}, "FUS"));
    EXPECT_TRUE(elementHasNames(
        result,
        elementAt(result, "Edge", Base::Vector3d(0.5, 0, 0.5)).c_str(),
        {linkingName(
            {unmappedName("Face3", 1, "FUS"), unmappedName("Face1", 2, "FUS")},
            1,
            "FUS",
            'E',
            MAPPER_FLAG_GENERATED
        )}
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementCut)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {cube1, 1L};
    TopoShape topoShape2 {cube2, 2L};
    // Act
    TopoShape& result = topoShape1.makeElementCut(
        {topoShape1, topoShape2}
    );  //, const char* op = nullptr, double tol = 0);
    auto elements = elementMap(result);
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 0.75);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 38);
    //   cube1 without the corner 0.5 < x < 1, 0 < y < 0.5 that cube2 takes. Neither cube has
    //   names: every element is one of theirs, kept (MKR), trimmed (CUT), or made where two of
    //   their elements meet: the edges at x = 0.5 and y = 0.5 (GEN from a face of each cube) and
    //   the vertices at their ends (GEN from an edge of each cube)
    EXPECT_EQ(result.countSubElements("Vertex"), 12);
    EXPECT_EQ(result.countSubElements("Edge"), 18);
    EXPECT_EQ(result.countSubElements("Face"), 8);
    EXPECT_TRUE(namedAsBoolean(result, {{1, TopoShape(cube1)}, {2, TopoShape(cube2)}}, "CUT"));
    EXPECT_TRUE(elementHasNames(
        result,
        elementAt(result, "Edge", Base::Vector3d(0.5, 0, 0.5)).c_str(),
        {linkingName(
            {unmappedName("Face3", 1, "CUT"), unmappedName("Face1", 2, "CUT")},
            1,
            "CUT",
            'E',
            MAPPER_FLAG_GENERATED
        )}
    ));
}

namespace
{
// The V2 names of a box without names whose every edge was rounded or chamfered (tag 1): each box
// face, trimmed, keeps its unmapped name with the op; the face along each box edge and the face at
// each box corner are generated from that edge or vertex; the edges and vertices have no history
// and are named after the faces they bound (UPP). Each face is found near what it replaces.
void expectDressedBoxNames(const TopoShape& result, const TopoShape& box, const char* op)
{
    auto faceNear = [&](const Base::Vector3d& point) {
        return elementWhere(result, "Face", [&](const Base::Vector3d& center) {
            return Base::Distance(center, point) < 0.1;  // twice the rounding or chamfer size
        });
    };
    auto centerOf = [&](const std::string& element) {
        return box.getSubTopoShape(element.c_str()).getBoundBox().GetCenter();
    };
    for (int index = 1; index <= 6; ++index) {
        auto face = "Face" + std::to_string(index);
        EXPECT_TRUE(elementHasNames(
            result,
            elementAt(result, "Face", centerOf(face)).c_str(),
            {unmappedName(face, 1, op)}
        ));
    }
    for (const auto& [type, count] : {std::pair {"Edge", 12}, std::pair {"Vertex", 8}}) {
        for (int index = 1; index <= count; ++index) {
            auto element = type + std::to_string(index);
            EXPECT_TRUE(elementHasNames(
                result,
                faceNear(centerOf(element)).c_str(),
                {linkingName({unmappedName(element, 1, op)}, 1, op, 'F', MAPPER_FLAG_GENERATED)}
            ));
        }
    }
    EXPECT_TRUE(upperNamed(result, "Edge", 1, op));
    EXPECT_TRUE(upperNamed(result, "Vertex", 1, op));
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeElementChamfer)
{
    // Arrange
    // Fillets / Chamfers do not work on compounds of faces, so use complete boxes ( Solids ) here.
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};
    auto edges = cube1TS.getSubTopoShapes(TopAbs_EDGE);
    // Act
    cube1TS.makeElementChamfer({cube1TS}, edges, Part::ChamferType::equalDistance, .05, .05);
    auto elements = elementMap(cube1TS);
    // Assert shape is correct
    EXPECT_EQ(cube1TS.countSubElements("Wire"), 26);
    EXPECT_NEAR(getArea(cube1TS.getShape()), 5.640996, 1e-6);
    // Assert that we're creating a correct element map
    EXPECT_TRUE(cube1TS.getMappedChildElements().empty());
    EXPECT_EQ(cube1TS.countSubElements("Face"), 26);
    EXPECT_TRUE(allElementsNamed(cube1TS));
    expectDressedBoxNames(cube1TS, TopoShape(cube1), "CHF");
}

TEST_F(TopoShapeExpansionTest, makeElementFillet)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};
    auto edges = cube1TS.getSubTopoShapes(TopAbs_EDGE);
    // Act
    cube1TS.makeElementFillet({cube1TS}, edges, .05, .05);
    auto elements = elementMap(cube1TS);
    // Assert shape is correct
    EXPECT_EQ(cube1TS.countSubElements("Wire"), 26);
    EXPECT_NEAR(getArea(cube1TS.getShape()), 5.739646, 1e-6);
    // Assert that we're creating a correct element map
    EXPECT_TRUE(cube1TS.getMappedChildElements().empty());
    EXPECT_EQ(cube1TS.countSubElements("Face"), 26);
    EXPECT_TRUE(allElementsNamed(cube1TS));
    expectDressedBoxNames(cube1TS, TopoShape(cube1), "FLT");
}

TEST_F(TopoShapeExpansionTest, makeElementSlice)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();  // TopoShape version works too
    TopoShape cube1TS {cube1};               // Adding a tag here only adds text in each mapped name
    auto faces = cube1TS.getSubShapes(TopAbs_FACE);
    TopoShape slicer {faces[0]};
    Base::Vector3d direction {1.0, 0.0, 0.0};
    // Act
    auto& result = slicer.makeElementSlice(cube1TS, direction, 0.5);
    // Assert shape is correct
    EXPECT_FLOAT_EQ(getLength(result.getShape()), 4);
    EXPECT_EQ(TopAbs_ShapeEnum::TopAbs_WIRE, result.getShape().ShapeType());
    // Assert that we're creating a correct element map
    EXPECT_TRUE(result.getMappedChildElements().empty());
    //   the cube has neither a tag nor names, so it can't be linked: the wire is named after the
    //   slicing plane only, a face made for the slice with the slice's number as its tag (1) and
    //   named without an op, and the result takes that tag. Its 4 edges and 4 vertices are all
    //   generated from that face. Each name has its element's type (ops#46), and within a type
    //   they are told apart by the index, 0 to 3. Which element gets which index is ops#19's
    auto planeName = unmappedName("Face1", 1);
    EXPECT_TRUE(allElementsNamed(result));
    EXPECT_TRUE(namesHaveTheirElementsType(result));
    std::set<std::string> names;
    std::map<char, std::set<std::string>> indexesByType;
    for (const auto& entry : result.getElementMap()) {
        auto section = lastSection(entry.name);
        EXPECT_EQ(section.linkedNames, std::vector<std::string> {planeName.toString()});
        EXPECT_EQ(section.iterationTag, "1");
        EXPECT_EQ(section.opCode, "SLC");
        EXPECT_EQ(section.mapperFlags, std::vector<std::string> {MAPPER_FLAG_GENERATED});
        names.insert(entry.name.toString());
        indexesByType[section.elementType].insert(section.index);
    }
    EXPECT_EQ(names.size(), 8);
    std::set<std::string> fourIndexes {"0", "1", "2", "3"};
    std::map<char, std::set<std::string>> expectedIndexes {{'E', fourIndexes}, {'V', fourIndexes}};
    EXPECT_EQ(indexesByType, expectedIndexes);
}

TEST_F(TopoShapeExpansionTest, makeElementSlices)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};
    auto faces = cube1TS.getSubShapes(TopAbs_FACE);
    TopoShape slicer {faces[0]};
    Base::Vector3d direction {1.0, 0.0, 0.0};
    // Act
    auto& result = slicer.makeElementSlices(cube1TS, direction, {0.25, 0.5, 0.75});
    auto subTopoShapes = result.getSubTopoShapes(TopAbs_WIRE);
    // Assert shape is correct
    EXPECT_EQ(result.countSubElements("Wire"), 3);
    EXPECT_FLOAT_EQ(getLength(result.getShape()), 12);
    EXPECT_FLOAT_EQ(getLength(subTopoShapes[0].getShape()), 4);
    EXPECT_EQ(TopAbs_ShapeEnum::TopAbs_COMPOUND, result.getShape().ShapeType());
    EXPECT_EQ(TopAbs_ShapeEnum::TopAbs_WIRE, subTopoShapes[0].getShape().ShapeType());
    EXPECT_EQ(TopAbs_ShapeEnum::TopAbs_WIRE, subTopoShapes[1].getShape().ShapeType());
    EXPECT_EQ(TopAbs_ShapeEnum::TopAbs_WIRE, subTopoShapes[2].getShape().ShapeType());
    // Assert that we're creating a correct element map
    EXPECT_TRUE(result.getMappedChildElements().empty());
    //   each slice i (x = 0.25, 0.5, 0.75) is a wire where a face made for the slice, with the
    //   slice's number as its tag and named without an op, cuts the cube (tag 1). Each edge is
    //   generated from the cube face it lies on and that face, each vertex from the cube edge it
    //   lies on and that face. The op is SLC for the first slice and SLC_<i> for the others; the
    //   result has no tag and takes the first input's (1)
    EXPECT_TRUE(allElementsNamed(result));
    TopoShape cube {cube1};
    auto expected = [&](const std::string& element) {
        auto shape = result.getSubShape(element.c_str());
        const char* above = element.starts_with("Vertex") ? "Edge" : "Face";
        auto slice = static_cast<int>(std::lround(result.getSubTopoShape(element.c_str())
                                                      .getBoundBox()
                                                      .GetCenter()
                                                      .x
                                                  / 0.25));
        std::string op = slice == 1 ? "SLC" : "SLC_" + std::to_string(slice);
        std::vector<MappedName> linked;
        for (int index = 1; index <= static_cast<int>(cube.countSubElements(above)); ++index) {
            auto cubeElement = above + std::to_string(index);
            if (liesOn(shape, cube.getSubShape(cubeElement.c_str()))) {
                linked.push_back(unmappedName(cubeElement, 1, op.c_str()));
            }
        }
        EXPECT_EQ(linked.size(), 1) << element;
        linked.push_back(unmappedName("Face1", slice));
        return linkingName(linked, 1, op.c_str(), element[0], MAPPER_FLAG_GENERATED);
    };
    for (const char* type : {"Vertex", "Edge"}) {
        for (int index = 1; index <= static_cast<int>(result.countSubElements(type)); ++index) {
            auto element = type + std::to_string(index);
            EXPECT_TRUE(elementHasNames(result, element.c_str(), {expected(element)}));
        }
    }
    EXPECT_FALSE(subTopoShapes[0].getElementMap().empty());  // Changed with PR#12471. Probably will
                                                             // change again after importing other
                                                             // TopoNaming logics
}

TEST_F(TopoShapeExpansionTest, makeElementMirror)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};
    auto edges = cube1TS.getSubTopoShapes(TopAbs_EDGE);
    gp_Ax2 axis {gp_Pnt {0, 0, 0}, gp_Dir {1, 0, 0}};
    // Act
    auto& result = cube1TS.makeElementMirror(cube1TS, axis);
    auto elements = elementMap(cube1TS);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(-1, 0, 0, 0, 1, 1)));
    EXPECT_EQ(result.countSubElements("Wire"), 6);
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 1);
    EXPECT_EQ(TopAbs_ShapeEnum::TopAbs_SOLID, result.getShape().ShapeType());
    // Assert that we're creating a correct element map
    EXPECT_TRUE(result.getMappedChildElements().empty());
    //   the cube has no names: each element of the mirror image keeps the unmapped name of the
    //   cube element it mirrors (the one at x -> -x), with op MIR. Mirroring adds no section.
    TopoShape cube {cube1};
    for (const char* type : {"Vertex", "Edge", "Face"}) {
        for (int index = 1; index <= static_cast<int>(cube.countSubElements(type)); ++index) {
            auto element = type + std::to_string(index);
            auto center = cube.getSubTopoShape(element.c_str()).getBoundBox().GetCenter();
            EXPECT_TRUE(elementHasNames(
                result,
                elementAt(result, type, Base::Vector3d(-center.x, center.y, center.z)).c_str(),
                {unmappedName(element, 1, "MIR")}
            ));
        }
    }
}

TEST_F(TopoShapeExpansionTest, makeElementTransformWithoutMap)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    TopoShape topoShape1 {cube1, 1L};
    // Act
    TopoShape& result = topoShape1.makeElementTransform(topoShape1, tr);
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(-0.5, -0.5, 0.0, 0.5, 0.5, 1.0)));
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 1);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 0);
}

TEST_F(TopoShapeExpansionTest, makeElementTransformWithMap)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {cube1, 1L};
    TopoShape topoShape2 {cube2, 2L};
    // Act
    TopoShape& result = topoShape1.makeElementFuse({topoShape1, topoShape2});  // op, tolerance
    topoShape1.makeElementTransform(result, tr);
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(-0.5, -1.0, 0.0, 1.0, 0.5, 1.0)));
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 1.75);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 66);
    //   moving the fused cubes adds no section: every element keeps the fused shape's names
    //   (makeElementFuse checks those)
    TopoShape fused {1L};
    fused.makeElementFuse({TopoShape(cube1, 1L), TopoShape(cube2, 2L)});
    EXPECT_TRUE(allElementsNamed(result));
    EXPECT_TRUE(sameNamesPerElement(result, fused));
}

TEST_F(TopoShapeExpansionTest, makeElementGTransformWithoutMap)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    TopoShape topoShape1 {cube1, 1L};
    // Act
    TopoShape& result = topoShape1.makeElementGTransform(topoShape1, TopoShape::convert(tr));
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(-0.5, -0.5, 0.0, 0.5, 0.5, 1.0)));
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 1);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 0);
}

TEST_F(TopoShapeExpansionTest, makeElementGTransformWithMap)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {cube1, 1L};
    TopoShape topoShape2 {cube2, 2L};
    // Act
    TopoShape& result = topoShape1.makeElementFuse({topoShape1, topoShape2});  // op, tolerance
    topoShape1.makeElementGTransform(result, TopoShape::convert(tr));
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(-0.5, -1.0, 0.0, 1.0, 0.5, 1.0)));
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 1.75);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 66);
    //   moving the fused cubes adds no section: every element keeps the fused shape's names
    //   (makeElementFuse checks those)
    TopoShape fused {1L};
    fused.makeElementFuse({TopoShape(cube1, 1L), TopoShape(cube2, 2L)});
    EXPECT_TRUE(allElementsNamed(result));
    EXPECT_TRUE(sameNamesPerElement(result, fused));
}

// Not testing _makeElementTransform as it is a thin wrapper that calls the same places as the four
// preceding tests.

TEST_F(TopoShapeExpansionTest, makeElementSolid)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {cube1, 1L};
    TopoShape topoShape2 {cube2, 2L};
    // Act
    TopExp_Explorer exp(topoShape1.getShape(), TopAbs_SHELL);
    auto shell1 = exp.Current();
    exp.Init(topoShape2.getShape(), TopAbs_SHELL);
    auto shell2 = exp.Current();
    TopoShape& topoShape3 = topoShape1.makeElementCompound({shell1, shell2});
    TopoShape& result = topoShape1.makeElementSolid(topoShape3);  // Need the single parm form
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0.0, -0.5, 0.0, 1.5, 1.0, 1.0)));
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 2);
    // Assert elementMap is correct
    EXPECT_EQ(elements.size(), 52);
    //   the shells have no tags and no names: in the compound, each element of a shell gets its
    //   unmapped name in that shell under the compound's tag (1). The second shell's names are
    //   the first one's, so they get duplicate count 1. The solid keeps them.
    EXPECT_EQ(unmappedName("Edge3", 1, "MKR", 1).toString(), "Edge3;_;1;MKR;0;E;1;IDX,SRC;_");
    for (const auto& [shell, duplicate] : {std::pair {shell1, 0}, std::pair {shell2, 1}}) {
        TopoShape shellShape {shell};
        for (const char* type : {"Vertex", "Edge", "Face"}) {
            auto count = static_cast<int>(shellShape.countSubElements(type));
            for (int index = 1; index <= count; ++index) {
                auto element = type + std::to_string(index);
                auto found = result.findShape(shellShape.getSubShape(element.c_str()));
                EXPECT_TRUE(elementHasNames(
                    result,
                    (type + std::to_string(found)).c_str(),
                    {unmappedName(element, 1, "MKR", duplicate)}
                ));
            }
        }
    }
}

TEST_F(TopoShapeExpansionTest, makeElementRevolve)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape topoShape1 {cube1, 1L};
    gp_Ax1 axis {gp_Pnt {0, 0, 0}, gp_Dir {0, 1, 0}};
    double angle = 45;
    auto subTopoFaces = topoShape1.getSubTopoShapes(TopAbs_FACE);
    subTopoFaces[0].Tag = 2L;
    // Act
    TopoShape result = subTopoFaces[0].makeElementRevolve(axis, angle);
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(
        PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0.0, 0.0, 0.0, 0.85090352453411933, 1.0, 1.0))
    );
    EXPECT_NEAR(getVolume(result.getShape()), 0.50885141, 1e-6);
    // Assert elementMap is correct
    //   the face (the cube's x = 0 face, tag 2) has names, which the result links; the result
    //   has the face's tag. The face itself is kept as the start face. Its edge on the axis
    //   (z = 0) is kept and sweeps nothing; the others sweep a face each (GEN), and its vertices
    //   off the axis sweep an edge each (GEN).
    const auto& face = subTopoFaces[0];
    auto nameOf = [&](const std::string& element) {
        return face.getMappedName(IndexedName(element.c_str()));
    };
    auto rotated = [&](const Base::Vector3d& point) {
        gp_Trsf rotation;
        rotation.SetRotation(axis, angle);
        gp_Pnt moved = gp_Pnt(point.x, point.y, point.z).Transformed(rotation);
        return Base::Vector3d(moved.X(), moved.Y(), moved.Z());
    };
    auto centerOf = [&](const TopoShape& shape, const std::string& element) {
        return shape.getSubTopoShape(element.c_str()).getBoundBox().GetCenter();
    };
    EXPECT_EQ(result.countSubElements("Face"), 5);
    EXPECT_TRUE(allElementsNamed(result));
    EXPECT_TRUE(namesHaveTheirElementsType(result));
    EXPECT_TRUE(elementHasNames(
        result,
        ("Face" + std::to_string(result.findShape(face.getShape()))).c_str(),
        {nameOf("Face1")}
    ));
    std::string axisEdge;
    for (int index = 1; index <= 4; ++index) {
        auto edge = "Edge" + std::to_string(index);
        auto center = centerOf(face, edge);
        if (std::abs(center.z) < 1e-7) {
            axisEdge = edge;
            continue;
        }
        //   the swept face contains the edge and its rotated copy: its center is off both
        std::string sweptFace;
        for (int faceIndex = 1; faceIndex <= 5; ++faceIndex) {
            auto candidate = "Face" + std::to_string(faceIndex);
            if (liesOn(face.getSubShape(edge.c_str()), result.getSubShape(candidate.c_str()))
                && result.getMappedName(IndexedName(candidate.c_str())) != nameOf("Face1")) {
                sweptFace = candidate;
            }
        }
        EXPECT_TRUE(elementHasNames(
            result,
            sweptFace.c_str(),
            {linkingName({nameOf(edge)}, 2, "RVL", 'F', MAPPER_FLAG_GENERATED)}
        ));
    }
    EXPECT_EQ(axisEdge, "Edge4");
    for (int index = 1; index <= 4; ++index) {
        auto vertex = "Vertex" + std::to_string(index);
        auto point = centerOf(face, vertex);
        if (std::abs(point.z) < 1e-7) {
            continue;
        }
        auto arcEnd = rotated(point);
        std::string arc;
        auto end = BRepBuilderAPI_MakeVertex(gp_Pnt(arcEnd.x, arcEnd.y, arcEnd.z)).Vertex();
        auto edges = static_cast<int>(result.countSubElements("Edge"));
        for (int edgeIndex = 1; edgeIndex <= edges; ++edgeIndex) {
            auto candidate = "Edge" + std::to_string(edgeIndex);
            auto shape = result.getSubShape(candidate.c_str());
            if (liesOn(face.getSubShape(vertex.c_str()), shape) && liesOn(end, shape)
                && !liesOn(shape, face.getShape())) {
                arc = candidate;
            }
        }
        EXPECT_TRUE(elementHasNames(
            result,
            arc.c_str(),
            {linkingName({nameOf(vertex)}, 2, "RVL", 'E', MAPPER_FLAG_GENERATED)}
        ));
    }
    //   the end face has no history of its own, so it is named after its edges (LOW). The
    //   fallback names faces before edges in one pass, so the only edge of it named by then is
    //   the kept axis edge.
    auto endFace = elementWhere(result, "Face", [&](const Base::Vector3d& center) {
        return Base::Distance(center, rotated(centerOf(face, "Face1"))) < 1e-7;
    });
    EXPECT_TRUE(elementHasNames(
        result,
        endFace.c_str(),
        {linkingName({nameOf(axisEdge)}, 2, "RVL", 'F', MAPPER_FLAG_LOWER)}
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementPrism)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape topoShape1 {cube1, 1L};
    auto subTopoFaces = topoShape1.getSubTopoShapes(TopAbs_FACE);
    subTopoFaces[0].Tag = 2L;
    // Act
    TopoShape& result = topoShape1.makeElementPrism(subTopoFaces[0], {0.75, 0, 0});
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0.0, 0.0, 0.0, 0.75, 1.0, 1.0)));
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 0.75);
    // Assert elementMap is correct
    //   the face (the cube's x = 0 face, tag 2) has names, which the prism links under its own
    //   tag (1): the face and its edges and vertices are kept as the start; the face's copy at
    //   x = 0.75 and its edges and vertices are projected from them (PRJ); each edge of the face
    //   sweeps a side face and each vertex an edge (GEN)
    const auto& face = subTopoFaces[0];
    EXPECT_TRUE(allElementsNamed(result));
    for (const char* type : {"Vertex", "Edge", "Face"}) {
        for (int index = 1; index <= static_cast<int>(face.countSubElements(type)); ++index) {
            auto element = type + std::to_string(index);
            auto name = face.getMappedName(IndexedName(element.c_str()));
            auto center = face.getSubTopoShape(element.c_str()).getBoundBox().GetCenter();
            auto kept = type + std::to_string(result.findShape(face.getSubShape(element.c_str())));
            EXPECT_TRUE(elementHasNames(result, kept.c_str(), {name}));
            EXPECT_TRUE(elementHasNames(
                result,
                elementAt(result, type, center + Base::Vector3d(0.75, 0, 0)).c_str(),
                {linkingName({name}, 1, "XTR", type[0], MAPPER_FLAG_PROJECTION)}
            ));
            if (std::string(type) != "Face") {
                const char* swept = std::string(type) == "Vertex" ? "Edge" : "Face";
                EXPECT_TRUE(elementHasNames(
                    result,
                    elementAt(result, swept, center + Base::Vector3d(0.375, 0, 0)).c_str(),
                    {linkingName({name}, 1, "XTR", swept[0], MAPPER_FLAG_GENERATED)}
                ));
            }
        }
    }
}

TEST_F(TopoShapeExpansionTest, makeElementPrismUntil)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape cube1TS {cube1, 1L};
    auto subTopoFaces = cube1TS.getSubTopoShapes(TopAbs_FACE);
    auto direction = gp_Vec(gp_XYZ(0.0, 0.0, 1));
    // Act
    TopoShape result = cube1TS.makeElementPrismUntil(
        subTopoFaces[4],
        subTopoFaces[4],
        subTopoFaces[5],
        direction,
        TopoShape::PrismMode::FuseWithBase
    );
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)));
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 1);
    // Assert elementMap is correct
    //    EXPECT_EQ(result.getElementMapSize(),26); // Todo: Sometimes too big in TNP code.  Why?
    EXPECT_EQ(result.countSubElements("Edge"), 12);
    EXPECT_EQ(result.countSubElements("Face"), 6);
    EXPECT_EQ(result.countSubElements("Vertex"), 8);
}

// BRepFeat up to a shell that stops only part of the profile extruded all of it far past the
// shell, and said it was done (ops#356). BRepFeat chooses its own sense, so the maker refuses a
// prism that reaches past both the shell and the profile either way. FeatureExtrude turns the
// direction toward the up-to shape first, so no Pad or Pocket reaches the backwards half: here the
// direction points away from the box. BRepFeat turns round, and the overhanging square's prism
// reaches z = 163, past the box, the other way (ops#357)
TEST_F(TopoShapeExpansionTest, makeElementPrismUntilRefusesReachingPastBackwards)
{
    // The box x 10..35, y -5..5, z 0..10 without its top: a Pad's shell up to the whole base
    BRepPrimAPI_MakeBox box(gp_Pnt(10, -5, 0), 25, 10, 10);
    const TopoDS_Face top = box.TopFace();
    TopoDS_Shell shell;
    BRep_Builder builder;
    builder.MakeShell(shell);
    for (TopExp_Explorer faces(box.Shape(), TopAbs_FACE); faces.More(); faces.Next()) {
        if (!faces.Current().IsSame(top)) {
            builder.Add(shell, faces.Current());
        }
    }
    const TopoShape upTo(shell, 3L);
    const TopoShape base(box.Shape(), 4L);
    // The 4 x 4 square x x0..x0 + 4, y -2..2 at z = -5
    auto square = [](double x0) {
        BRepBuilderAPI_MakePolygon outline(
            gp_Pnt(x0, -2, -5),
            gp_Pnt(x0 + 4, -2, -5),
            gp_Pnt(x0 + 4, 2, -5),
            gp_Pnt(x0, 2, -5),
            Standard_True
        );
        return TopoShape(BRepBuilderAPI_MakeFace(outline.Wire()).Face(), 2L);
    };
    // With the box as the base and the square as its own support, as FeatureExtrude passes them:
    // without a base BRepFeat fails either way
    auto prism = [&](double x0) {
        const TopoShape profile = square(x0);
        TopoShape result(1L);
        result.makeElementPrismUntil(
            base,
            profile,
            profile,
            upTo,
            gp_Dir(0, 0, -1),
            TopoShape::PrismMode::None,
            Standard_True
        );
        return result;
    };
    // All of the square under the box: up to its bottom, 4 x 4 x 5
    const TopoShape under = prism(25);
    EXPECT_NEAR(getVolume(under.getShape()), 80, 1e-6);
    Base::BoundBox3d bounds = under.getBoundBox();
    EXPECT_NEAR(bounds.MinZ, -5, 1e-6);
    EXPECT_NEAR(bounds.MaxZ, 0, 1e-6);
    // Half of it beside the box
    try {
        const TopoShape past = prism(33);
        ADD_FAILURE() << "a prism of volume " << getVolume(past.getShape());
    }
    catch (const Base::RuntimeError& error) {
        EXPECT_NE(std::string(error.what()).find("doesn't meet"), std::string::npos)
            << error.what();
    }
}

namespace
{
// The profile of the makeElementRevolution tests: the rectangle x 1..2, z 0.25..0.75 in the XZ
// plane
TopoDS_Face revolutionProfile()
{
    BRepBuilderAPI_MakePolygon outline(
        gp_Pnt(1, 0, 0.25),
        gp_Pnt(2, 0, 0.25),
        gp_Pnt(2, 0, 0.75),
        gp_Pnt(1, 0, 0.75),
        Standard_True
    );
    return BRepBuilderAPI_MakeFace(outline.Wire()).Face();
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeElementRevolution)
{
    // Arrange
    //   a wall x -3..0, y 0..3, z 0..1 (tag 1), and a profile face x 1..2, z 0.25..0.75 in the XZ
    //   plane (tag 2), revolved about the Z axis up to the wall's face x = 0: a quarter ring
    TopoShape wall {BRepPrimAPI_MakeBox(gp_Pnt(-3, 0, 0), 3, 3, 1).Shape(), 1L};
    TopoShape profile {revolutionProfile(), 2L};
    auto upTo = wall.getSubTopoShape(elementAt(wall, "Face", Base::Vector3d(0, 1.5, 0.5)).c_str());
    gp_Ax1 axis {gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)};
    TopoShape result {3L};
    // Act
    result.makeElementRevolution(
        wall,
        profile,
        axis,
        TopoShape(),
        TopoDS::Face(upTo.getShape()),
        nullptr,
        Part::RevolMode::None,
        Standard_False
    );
    // Assert shape is correct: the quarter ring alone (in RevolMode::None BRepFeat returns the
    // revolved solid; PartDesign fuses it with the base afterwards)
    EXPECT_NEAR(getVolume(result.getShape()), 3 * std::numbers::pi / 8, 1e-6);
    // Assert elementMap is correct (ops#240)
    //   as a Pad up to a face: named from the profile (tag 2), which has no element map here, so
    //   its elements' names are their indexes. The profile face is kept as the start face; each of
    //   its edges sweeps a face, and each of its vertices an arc edge, which the result names under
    //   its own tag (3) as generated (GEN)
    auto nameOf = [](const std::string& element) {
        return unmappedName(element, 2, "RVL");
    };
    auto startFace = "Face" + std::to_string(result.findShape(profile.getShape()));
    EXPECT_TRUE(elementHasNames(result, startFace.c_str(), {unmappedName("Face1", 2, "MKR")}));
    auto sweptBy = [&](const char* type, const std::string& element) {
        auto shape = profile.getSubShape(element.c_str());
        std::string swept;
        for (int index = 1; index <= static_cast<int>(result.countSubElements(type)); ++index) {
            auto candidate = type + std::to_string(index);
            if (candidate != startFace && liesOn(shape, result.getSubShape(candidate.c_str()))
                && !liesOn(result.getSubShape(candidate.c_str()), profile.getShape())) {
                EXPECT_TRUE(swept.empty()) << element << " on " << swept << " and " << candidate;
                swept = candidate;
            }
        }
        return swept;
    };
    for (int index = 1; index <= 4; ++index) {
        auto edge = "Edge" + std::to_string(index);
        EXPECT_TRUE(elementHasNames(
            result,
            sweptBy("Face", edge).c_str(),
            {linkingName({nameOf(edge)}, 3, "RVL", 'F', MAPPER_FLAG_GENERATED)}
        ));
        auto vertex = "Vertex" + std::to_string(index);
        EXPECT_TRUE(elementHasNames(
            result,
            sweptBy("Edge", vertex).c_str(),
            {linkingName({nameOf(vertex)}, 3, "RVL", 'E', MAPPER_FLAG_GENERATED)}
        ));
    }
    //   no element is named by its index in BRepFeat's result: the only unmapped names are the
    //   profile's, on the profile's own elements (the wall's faces, not sources here, get their
    //   names in the boolean that follows in PartDesign)
    EXPECT_TRUE(unmappedNamesNameTheirElements(result, {{2L, profile}}));
}

TEST_F(TopoShapeExpansionTest, makeElementRevolutionV1)
{
    // Arrange: makeElementRevolution's model in V1
    auto box = BRepPrimAPI_MakeBox(gp_Pnt(-3, 0, 0), 3, 3, 1).Shape();
    TopoShape wall {App::HistoryAlgorithm::V1, box, 1L};
    TopoShape profile {App::HistoryAlgorithm::V1, revolutionProfile(), 2L};
    auto upTo = wall.getSubTopoShape(elementAt(wall, "Face", Base::Vector3d(0, 1.5, 0.5)).c_str());
    TopoShape result {App::HistoryAlgorithm::V1, 3L};
    // Act
    result.makeElementRevolution(
        wall,
        profile,
        gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)),
        TopoShape(),
        TopoDS::Face(upTo.getShape()),
        nullptr,
        Part::RevolMode::None,
        Standard_False
    );
    // Assert: the same shape, and upstream's names, which ops#240 leaves alone: BRepFeat's result,
    // without a tag, is the only source, so the result has no element map
    EXPECT_NEAR(getVolume(result.getShape()), 3 * std::numbers::pi / 8, 1e-6);
    EXPECT_EQ(result.getElementMapSize(), 0);
}

TEST_F(TopoShapeExpansionTest, makeElementFilledFace)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    TopoShape topoShape1 {cube1, 1L};
    auto wires = topoShape1.getSubShapes(TopAbs_WIRE);
    TopoShape topoShape2 {wires[0], 2L};
    // Act
    auto params = TopoShape::BRepFillingParams();
    TopoShape& result = topoShape1.makeElementFilledFace({topoShape2}, params);
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0.0, -0.6, -0.6, 0, 1.6, 1.6)));
    EXPECT_FLOAT_EQ(getArea(result.getShape()), 1);
    // Assert elementMap is correct
    //   the wire (the cube's Face1's, tag 2) has no names. The face's boundary edges and vertices
    //   are generated from the wire's edges and vertices they lie on; the face itself has no
    //   history and is named after its edges (LOW). The result has cube1's tag (1).
    TopoShape wire {wires[0]};
    EXPECT_TRUE(allElementsNamed(result));
    for (const char* type : {"Vertex", "Edge"}) {
        for (int index = 1; index <= static_cast<int>(result.countSubElements(type)); ++index) {
            auto element = type + std::to_string(index);
            std::vector<MappedName> sources;
            auto inputs = static_cast<int>(wire.countSubElements(type));
            for (int inputIndex = 1; inputIndex <= inputs; ++inputIndex) {
                auto inputElement = type + std::to_string(inputIndex);
                auto shape = result.getSubShape(element.c_str());
                if (liesOn(shape, wire.getSubShape(inputElement.c_str()))) {
                    sources.push_back(unmappedName(inputElement, 2, "FFC"));
                }
            }
            EXPECT_EQ(sources.size(), 1) << element;
            EXPECT_TRUE(elementHasNames(
                result,
                element.c_str(),
                {linkingName(sources, 1, "FFC", type[0], MAPPER_FLAG_GENERATED)}
            ));
        }
    }
    EXPECT_TRUE(elementHasNames(result, "Face1", {lowerName(result, "Face1", 1, "FFC")}));
}

TEST_F(TopoShapeExpansionTest, makeElementFilledFaceFromLooseEdges)
{
    // Arrange: four independently-built edges whose endpoints are coincident but are *not* the same
    // shared vertices. See issue #31080 and PR #31141.
    auto [face, wire, edge1, edge2, edge3, edge4] = CreateRectFace(2.0, 3.0);
    boost::ignore_unused(face, wire);
    std::vector<TopoShape> edges {
        TopoShape {edge1, 1L},
        TopoShape {edge2, 2L},
        TopoShape {edge3, 3L},
        TopoShape {edge4, 4L},
    };
    TopoShape result;

    // Act: default params force boundary detection from the loose edges
    auto params = TopoShape::BRepFillingParams();
    result.makeElementFilledFace(edges, params);

    // Assert: the four disconnected edges were merged into a single closed four-sided boundary and
    // filled. Under the old requireSharedVertex policy the edges could not be chained and no
    // boundary face was produced. The filled surface bulges beyond the boundary, so its bounding
    // box and area are not asserted exactly.
    EXPECT_FALSE(result.isNull());
    EXPECT_EQ(result.countSubShapes(TopAbs_FACE), 1);
    EXPECT_EQ(result.countSubShapes(TopAbs_EDGE), 4);
    EXPECT_GT(getArea(result.getShape()), 0.0);
    // Topological naming survived the tolerance-based wire construction.
    EXPECT_FALSE(elementMap(result).empty());
}

TEST_F(TopoShapeExpansionTest, makeElementFilledFaceExplicitBoundaryRange)
{
    // Arrange: same disconnected edges as test above, but designate them explicitly as the boundary
    // range. See issue #31080 and PR #31141.
    auto [face, wire, edge1, edge2, edge3, edge4] = CreateRectFace(2.0, 3.0);
    boost::ignore_unused(face, wire);
    std::vector<TopoShape> edges {
        TopoShape {edge1, 1L},
        TopoShape {edge2, 2L},
        TopoShape {edge3, 3L},
        TopoShape {edge4, 4L},
    };
    TopoShape result;

    // Act
    auto params = TopoShape::BRepFillingParams();
    params.boundary_begin = 0;
    params.boundary_end = 4;
    result.makeElementFilledFace(edges, params);

    // Assert
    EXPECT_FALSE(result.isNull());
    EXPECT_EQ(result.countSubShapes(TopAbs_FACE), 1);
    EXPECT_EQ(result.countSubShapes(TopAbs_EDGE), 4);
    EXPECT_GT(getArea(result.getShape()), 0.0);
    EXPECT_FALSE(elementMap(result).empty());
}

TEST_F(TopoShapeExpansionTest, makeElementBSplineFace)
{
    // Arrange
    TColgp_Array1OfPnt array1(1, 3);  // sizing array
    array1.SetValue(1, gp_Pnt(-4, 0, 2));
    array1.SetValue(2, gp_Pnt(-7, 2, 2));
    array1.SetValue(3, gp_Pnt(-10, 0, 2));
    Handle(Geom_BSplineCurve) curve1 = GeomAPI_PointsToBSpline(array1).Curve();

    TColgp_Array1OfPnt array2(1, 3);  // sizing array
    array2.SetValue(1, gp_Pnt(-4, 0, 2));
    array2.SetValue(2, gp_Pnt(-7, -2, 2));
    array2.SetValue(3, gp_Pnt(-9, 0, 2));
    Handle(Geom_BSplineCurve) curve2 = GeomAPI_PointsToBSpline(array2).Curve();

    auto edge = BRepBuilderAPI_MakeEdge(curve1);
    auto edge1 = BRepBuilderAPI_MakeEdge(curve2);
    TopoShape topoShape {1L};
    TopoShape topoShape2 {edge, 2L};
    TopoShape topoShape3 {edge1, 3L};
    // Act
    TopoShape& result = topoShape.makeElementBSplineFace({topoShape2, topoShape3});
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(
        PartTestHelpers::boxesMatch(
            bb,
            Base::BoundBox3d(-10, -2.0597998470594132, 2, -4, 2.1254369627132599, 2)
        )
    );
    EXPECT_NEAR(getArea(result.getShape()), 14.677052, 1e-6);
    // Assert elementMap is correct
    //   the curves (tags 2 and 3) have no names. The face is generated from both; each of its
    //   edges and vertices on a curve is that curve's element, modified: the corner the curves
    //   share is both curves' Vertex1, so it has both names. The other two edges (the one between
    //   the curves' far ends, and a degenerated one at the shared corner) bound only the face: UPP.
    //   Before ops#47, V2 gave every edge tag 0, and the face its first edge's name. The two UPP
    //   edges are told apart by their index, in the order of their parameters on the face
    //   (ops#378): the degenerated one is 0, the far edge 1.
    EXPECT_TRUE(allElementsNamed(result));
    EXPECT_TRUE(namesHaveTheirElementsType(result));
    EXPECT_TRUE(elementHasNames(
        result,
        "Face1",
        {linkingName(
            {unmappedName("Edge1", 2, "BSF"), unmappedName("Edge1", 3, "BSF")},
            1,
            "BSF",
            'F',
            MAPPER_FLAG_GENERATED
        )}
    ));
    int upperNames = 0;
    for (int index = 1; index <= static_cast<int>(result.countSubElements("Edge")); ++index) {
        auto element = "Edge" + std::to_string(index);
        auto shape = result.getSubShape(element.c_str());
        if (BRep_Tool::Degenerated(TopoDS::Edge(shape))) {
            EXPECT_TRUE(liesOn(shape, BRepBuilderAPI_MakeVertex(gp_Pnt(-4, 0, 2)).Vertex()));
            EXPECT_TRUE(
                elementHasNames(result, element.c_str(), {upperName(result, element, 1, "BSF", 0)})
            );
            ++upperNames;
        }
        else if (liesOn(shape, edge.Edge())) {
            EXPECT_TRUE(
                elementHasNames(result, element.c_str(), {unmappedName("Edge1", 2, "BSF")})
            );
        }
        else if (liesOn(shape, edge1.Edge())) {
            EXPECT_TRUE(
                elementHasNames(result, element.c_str(), {unmappedName("Edge1", 3, "BSF")})
            );
        }
        else {
            EXPECT_TRUE(
                elementHasNames(result, element.c_str(), {upperName(result, element, 1, "BSF", 1)})
            );
            ++upperNames;
        }
    }
    EXPECT_EQ(upperNames, 2);
    auto end1 = elementAt(result, "Vertex", Base::Vector3d(-10, 0, 2));
    auto end2 = elementAt(result, "Vertex", Base::Vector3d(-9, 0, 2));
    auto shared = elementAt(result, "Vertex", Base::Vector3d(-4, 0, 2));
    EXPECT_TRUE(elementHasNames(result, end1.c_str(), {unmappedName("Vertex2", 2, "BSF")}));
    EXPECT_TRUE(elementHasNames(result, end2.c_str(), {unmappedName("Vertex2", 3, "BSF")}));
    EXPECT_TRUE(elementHasNames(
        result,
        shared.c_str(),
        {unmappedName("Vertex1", 2, "BSF"), unmappedName("Vertex1", 3, "BSF")}
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementBSplineFaceClosedEdgeWithOp)
{
    // Arrange: a single closed edge is split into 4, and the face is filled between them
    auto circle = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 2));
    TopoShape topoShape {1L};
    TopoShape topoShape2 {circle.Edge(), 2L};
    // Act
    TopoShape& result
        = topoShape.makeElementBSplineFace(topoShape2, FillingStyle::stretch, false, "SEW");
    // Assert shape is correct
    EXPECT_EQ(result.countSubElements("Face"), 1);
    EXPECT_EQ(result.countSubElements("Edge"), 4);
    // Assert elementMap is correct
    //   the face's own section has the op passed (before ops#47 it was dropped in this case), and
    //   links the four pieces of the circle; each edge is a piece of the circle, so its name has
    //   the circle's unmapped name.
    EXPECT_TRUE(allElementsNamed(result));
    EXPECT_TRUE(namesHaveTheirElementsType(result));
    auto face = lastSection(result.getMappedName(IndexedName("Face1")));
    EXPECT_EQ(face.opCode, "SEW");
    EXPECT_EQ(face.iterationTag, "1");
    EXPECT_EQ(face.mapperFlags, (std::vector<std::string> {MAPPER_FLAG_GENERATED}));
    EXPECT_EQ(face.linkedNames.size(), 4U);
    auto circleName = unmappedName("Edge1", 2, "SPT").toString();
    for (int index = 1; index <= 4; ++index) {
        auto element = "Edge" + std::to_string(index);
        auto name = result.getMappedName(IndexedName(element.c_str())).toString();
        EXPECT_EQ(name.rfind(circleName, 0), 0) << element << " = " << name;
    }
}

TEST_F(TopoShapeExpansionTest, replaceElementShape)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoTopoShapeCubes();
    // We can't use a compound in replaceElementShape, so we'll make a replacement wire and a shell
    auto wire {BRepBuilderAPI_MakeWire(
                   BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(1.0, 0.0, 0.0)),
                   BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 0.0, 0.0), gp_Pnt(1.0, 1.0, 0.0)),
                   BRepBuilderAPI_MakeEdge(gp_Pnt(1.0, 1.0, 0.0), gp_Pnt(0.0, 0.0, 0.0))
    )
                   .Wire()};
    auto shell = cube1.makeElementShell();
    auto wires = shell.getSubTopoShapes(TopAbs_WIRE);
    // Act
    TopoShape& result = shell.replaceElementShape(shell, {{wires[0], wire}});
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)));
    EXPECT_FLOAT_EQ(getArea(result.getShape()), 5);
    EXPECT_EQ(result.countSubElements("Wire"), 6);
    // Assert that we're creating a correct element map
    EXPECT_TRUE(result.getMappedChildElements().empty());
    //   no history: the elements that are the shell's keep the shell's names; the triangle has no
    //   tag and no names, so its edges and vertices, and the face rebuilt on it, have none
    const TopoShape& before = cube1;  // made a shell in place
    for (const char* type : {"Vertex", "Edge", "Face"}) {
        for (int index = 1; index <= static_cast<int>(result.countSubElements(type)); ++index) {
            auto element = type + std::to_string(index);
            auto found = before.findShape(result.getSubShape(element.c_str()));
            std::vector<MappedName> names;
            if (found > 0) {
                auto element = IndexedName::fromConst(type, found);
                for (const auto& name : before.getElementMappedNames(element)) {
                    names.push_back(name.first);
                }
                EXPECT_FALSE(names.empty()) << element;
            }
            EXPECT_TRUE(elementHasNames(result, element.c_str(), names));
        }
    }
}

TEST_F(TopoShapeExpansionTest, removeElementShape)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoTopoShapeCubes();
    auto faces = cube1.getSubTopoShapes(TopAbs_FACE);
    // Act
    TopoShape result = cube1.removeElementShape({faces[0]});
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)));
    EXPECT_FLOAT_EQ(getArea(result.getShape()), 5);
    EXPECT_EQ(result.countSubShapes("Compound"), 1);
    EXPECT_EQ(result.countSubShapes("Face"), 5);
    // Assert that we're creating a correct element map
    EXPECT_TRUE(result.getMappedChildElements().empty());
    //   every element left is one of the cube's, and keeps the cube's names for it
    EXPECT_TRUE(allElementsNamed(result));
    for (const char* type : {"Vertex", "Edge", "Face"}) {
        for (int index = 1; index <= static_cast<int>(result.countSubElements(type)); ++index) {
            auto element = type + std::to_string(index);
            auto found = cube1.findShape(result.getSubShape(element.c_str()));
            ASSERT_GT(found, 0) << element;
            std::vector<MappedName> names;
            auto cubeElement = IndexedName::fromConst(type, found);
            for (const auto& name : cube1.getElementMappedNames(cubeElement)) {
                names.push_back(name.first);
            }
            EXPECT_TRUE(elementHasNames(result, element.c_str(), names));
        }
    }
}

TEST_F(TopoShapeExpansionTest, makeElementEvolve)
{
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(0.0, 0.0, 0.0),
        gp_Pnt(200.0, 0.0, 0.0),
        gp_Pnt(200.0, 200.0, 0.0),
        gp_Pnt(0.0, 200.0, 0.0)
    );
    polygon.Close();
    TopoShape spine {polygon.Wire(), 1L};
    // Alternative:
    //    auto face {BRepBuilderAPI_MakeFace(polygon.Wire()).Face()};
    //    TopoShape spine {face, 11L};
    BRepBuilderAPI_MakePolygon polygon2(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(-60.0, -60.0, -200.0));
    TopoShape profile {polygon2.Wire(), 2L};
    // Alternative:
    //    TopoShape profile {
    //        BRepBuilderAPI_MakeEdge(gp_Pnt(0.0, 0.0, 0.0), gp_Pnt(-60.0, -60.0, -200.0)).Edge(),
    //        10L};
    // Act
    TopoShape topoShape {3L};
    auto& result = topoShape.makeElementEvolve(spine, profile);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(
        PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(-60.0, -60.0, -200.0, 260.0, 260.0, 0))
    );
    EXPECT_FLOAT_EQ(getVolume(result.getShape()), 8910324);
    // Assert elementMap is correct
    EXPECT_EQ(topoShape.getElementMap().size(), 0);
    // Neither the Spine nor the Profile have an elementMap, because they are simple wires or faces.
    // The resulting Evolved also does not populate the elementMap, but that might be a bug in
    // underutilized code.
    EXPECT_EQ(spine.getElementMap().size(), 0);
}

TEST_F(TopoShapeExpansionTest, traceElementV1)
{
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {App::HistoryAlgorithm::V1, cube1, 1L};
    TopoShape topoShape2 {App::HistoryAlgorithm::V1, cube2, 2L};
    // Act
    TopoShape& result = topoShape1.makeElementCut(
        {topoShape1, topoShape2}
    );  //, const char* op = nullptr, double tol = 0);
    std::string name {"Face2;:M;CUT;:H1:7,F"};
    //    auto faces = result.getSubTopoShapes(TopAbs_FACE);
    Data::MappedName mappedName(name);
    // Arrange
    Data::TraceCallback cb =
        [name](const Data::MappedName& elementname, int offset, long encodedTag, long tag) {
            boost::ignore_unused(offset);
            boost::ignore_unused(tag);
            // TODO:  This is likely a flawed way to address testing a callback.
            // Also, it isn't clear exactly what the correct results are, although as soon as
            // we start addressing History, we will quickly discover that, and likely the right
            // things to test.
            if (encodedTag == 1) {
                EXPECT_STREQ(elementname.toString().c_str(), name.c_str());
            }
            else {
                EXPECT_STREQ(elementname.toString().c_str(), name.substr(0, 5).c_str());
            }
            return false;
        };
    // Act
    result.traceElement(mappedName, cb);
    // Assert we have the element map we think we do.
    EXPECT_TRUE(allElementsMatch(
        result,
        {
            "Edge1",
            "Edge10;:G(Edge2;K-1;:H2:4,E);CUT;:H1:1a,V",
            "Edge10;:M;CUT;:H1:7,E",
            "Edge11",
            "Edge11;:M;CUT;:H2:7,E",
            "Edge12",
            "Edge12;:M;CUT;:H2:7,E",
            "Edge2",
            "Edge2;:M;CUT;:H2:7,E",
            "Edge3",
            "Edge3;:M;CUT;:H2:7,E",
            "Edge4",
            "Edge4;:M;CUT;:H2:7,E",
            "Edge6;:G(Edge12;K-1;:H2:4,E);CUT;:H1:1b,V",
            "Edge6;:M;CUT;:H1:7,E",
            "Edge7",
            "Edge8;:G(Edge11;K-1;:H2:4,E);CUT;:H1:1b,V",
            "Edge8;:M;CUT;:H1:7,E",
            "Edge9;:G(Edge4;K-1;:H2:4,E);CUT;:H1:1a,V",
            "Edge9;:M;CUT;:H1:7,E",
            "Face1",
            "Face1;:M;CUT;:H2:7,F",
            "Face2;:G(Face4;K-1;:H2:4,F);CUT;:H1:1a,E",
            "Face2;:M;CUT;:H1:7,F",
            "Face3;:G(Face1;K-1;:H2:4,F);CUT;:H1:1a,E",
            "Face3;:M;CUT;:H1:7,F",
            "Face4",
            "Face4;:M;CUT;:H2:7,F",
            "Face5;:M;CUT;:H1:7,F",
            "Face6;:M;CUT;:H1:7,F",
            "Vertex1",
            "Vertex2",
            "Vertex3",
            "Vertex3;:M;CUT;:H2:7,V",
            "Vertex4",
            "Vertex4;:M;CUT;:H2:7,V",
            "Vertex7",
            "Vertex8",
        }
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementOffset)
{
    // Arrange
    // Arrange
    auto [cube1, cube2] = CreateTwoCubes();
    auto tr {gp_Trsf()};
    tr.SetTranslation(gp_Vec(gp_XYZ(-0.5, -0.5, 0)));
    cube2.Move(TopLoc_Location(tr));
    TopoShape topoShape1 {App::HistoryAlgorithm::V1, cube1, 1L};
    TopoShape topoShape2 {App::HistoryAlgorithm::V1, cube2, 2L};
    // Act
    //    TopoShape topoShape3 {6L};
    TopoShape result {App::HistoryAlgorithm::V1, 3L};
    //    topoShape1.makeElementFuse({topoShape2,topoShape2});  // op, tolerance
    result.makeElementOffset(topoShape1, 0.25, 1e-07);
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(
        PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(-0.25, -0.25, -0.25, 1.25, 1.25, 1.25))
    );
    EXPECT_NEAR(getVolume(result.getShape()), 3.1544986, 1e-6);
    // Assert elementMap is correct
    //    EXPECT_EQ(elements.size(), 98);
    //    EXPECT_EQ(elements.count(IndexedName("Face", 1)), 1);
    //    EXPECT_EQ(
    //        elements[IndexedName("Face", 1)],
    //        MappedName("Face2;:G;OFS;:H1:7,F"));
    EXPECT_TRUE(elementsMatch(
        result,
        {
            "Edge10;:G;OFS;:H1:7,F",
            "Edge10;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge10;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge10;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge10;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge11;:G;OFS;:H1:7,F",
            "Edge11;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge11;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge11;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge11;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge12;:G;OFS;:H1:7,F",
            "Edge12;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge12;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge12;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge12;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge1;:G;OFS;:H1:7,F",
            "Edge1;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge1;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U2;OFS;:H1:8,V",
            "Edge1;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge1;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge1;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge1;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge1;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge1;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge2;:G;OFS;:H1:7,F",
            "Edge2;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge2;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U2;OFS;:H1:8,V",
            "Edge2;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge2;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge2;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge2;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge2;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge3;:G;OFS;:H1:7,F",
            "Edge3;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge3;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U2;OFS;:H1:8,V",
            "Edge3;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge3;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge3;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge3;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge3;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge4;:G;OFS;:H1:7,F",
            "Edge4;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge4;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U2;OFS;:H1:8,V",
            "Edge4;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge4;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge4;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge4;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge5;:G;OFS;:H1:7,F",
            "Edge5;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge5;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U2;OFS;:H1:8,V",
            "Edge5;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge5;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge5;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge5;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge5;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge5;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge6;:G;OFS;:H1:7,F",
            "Edge6;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge6;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U2;OFS;:H1:8,V",
            "Edge6;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge6;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge6;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge6;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge6;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge7;:G;OFS;:H1:7,F",
            "Edge7;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge7;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U2;OFS;:H1:8,V",
            "Edge7;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge7;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge7;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge7;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge7;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge8;:G;OFS;:H1:7,F",
            "Edge8;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge8;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U2;OFS;:H1:8,V",
            "Edge8;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E;:U;OFS;:H1:7,V",
            "Edge8;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge8;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge8;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Edge9;:G;OFS;:H1:7,F",
            "Edge9;:G;OFS;:H1:7,F;:U2;OFS;:H1:8,E",
            "Edge9;:G;OFS;:H1:7,F;:U3;OFS;:H1:8,E",
            "Edge9;:G;OFS;:H1:7,F;:U4;OFS;:H1:8,E",
            "Edge9;:G;OFS;:H1:7,F;:U;OFS;:H1:7,E",
            "Face1;:G;OFS;:H1:7,F",
            "Face2;:G;OFS;:H1:7,F",
            "Face3;:G;OFS;:H1:7,F",
            "Face4;:G;OFS;:H1:7,F",
            "Face5;:G;OFS;:H1:7,F",
            "Face6;:G;OFS;:H1:7,F",
            "Vertex1;:G;OFS;:H1:7,F",
            "Vertex2;:G;OFS;:H1:7,F",
            "Vertex3;:G;OFS;:H1:7,F",
            "Vertex4;:G;OFS;:H1:7,F",
            "Vertex5;:G;OFS;:H1:7,F",
            "Vertex6;:G;OFS;:H1:7,F",
            "Vertex7;:G;OFS;:H1:7,F",
            "Vertex8;:G;OFS;:H1:7,F",
        }
    ));
}

namespace
{
// A cylinder (radius 5, height 10) whose side is two half-cylinder faces. They meet at two tangent
// lines, which an offset with arc joins keeps, so the two lines are named after the same two faces
// and told apart only by their index; the circles get arc faces (ops#49).
TopoDS_Shape splitCylinder()
{
    gp_Circ circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 5);
    auto arc1 = BRepBuilderAPI_MakeEdge(circle, 0, std::numbers::pi).Edge();
    auto arc2 = BRepBuilderAPI_MakeEdge(circle, std::numbers::pi, 2 * std::numbers::pi).Edge();
    auto face = BRepBuilderAPI_MakeFace(BRepBuilderAPI_MakeWire(arc1, arc2).Wire()).Face();
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, 10)).Shape();
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeElementOffsetAndThickSolidRepeat)
{
    // OCCT lists the faces of an offset with arc faces in an order that changes from run to run.
    // Built again in this process, the result must have the same element names at the same
    // indexes, in V1 and V2 (ops#49).
    for (auto algorithm : {App::HistoryAlgorithm::V1, App::HistoryAlgorithm::V2}) {
        // OCCT's order follows the addresses of the source's sub-shapes: each build gets a new
        // cylinder, and every shape is kept, so that no build reuses the memory of the one before.
        std::vector<TopoShape> kept;
        auto cylinder = [&]() {
            kept.emplace_back(algorithm, splitCylinder(), 1L);
            return kept.back();
        };
        auto offset = [&]() {
            TopoShape result {algorithm, 2L};
            result.makeElementOffset(cylinder(), 1, 1e-07);
            kept.push_back(result);
            return elementMap(result);
        };
        auto thickSolid = [&]() {
            TopoShape source = cylinder();
            TopoShape top;
            for (const auto& face : source.getSubTopoShapes(TopAbs_FACE)) {
                if (face.getBoundBox().MinZ > 9.9) {
                    top = face;
                }
            }
            TopoShape result {algorithm, 3L};
            result.makeElementThickSolid(source, {top}, 1, 1e-07);
            kept.push_back(result);
            return elementMap(result);
        };
        const auto firstOffset = offset();
        const auto firstThickSolid = thickSolid();
        EXPECT_EQ(firstOffset.size(), 30);  // 8 faces, 14 edges, 8 vertexes, all named
        EXPECT_EQ(firstThickSolid.size(), 35);
        for (int run = 2; run <= 5; ++run) {
            EXPECT_EQ(offset(), firstOffset) << "offset, run " << run;
            EXPECT_EQ(thickSolid(), firstThickSolid) << "thick solid, run " << run;
        }
    }
}

TEST_F(TopoShapeExpansionTest, makeElementOffsetFace)
{
    // Arrange
    const float Len = 3, Wid = 2, Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    // Act
    TopoShape result {App::HistoryAlgorithm::V1, face1, 1L};
    result.makeElementOffsetFace(result, 0.25, 0);
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(-0.25, -0.25, 0.0, 3.25, 2.25, 0.0)));
    // Assert elementMap is correct
    //    EXPECT_EQ(elements.size(), 19);
    //        EXPECT_EQ(elements.count(IndexedName("Face", 1)), 1);
    //        EXPECT_EQ(
    //            elements[IndexedName("Face", 1)],
    //            MappedName("Edge1;:G;OFF;:H1:7,E;FAC;:H1:4,F"));
    EXPECT_TRUE(elementsMatch(
        result,
        {
            "Edge1;:G;OFF;:H1:7,E",
            "Edge1;:G;OFF;:H1:7,E;:U2;OFF;:H1:8,V",
            "Edge1;:G;OFF;:H1:7,E;:U;OFF;:H1:7,V",
            "Edge1;:G;OFF;:H1:7,E;FAC;:H1:4,F",
            "Edge2;:G;OFF;:H1:7,E",
            "Edge2;:G;OFF;:H1:7,E;:U2;OFF;:H1:8,V",
            "Edge2;:G;OFF;:H1:7,E;:U;OFF;:H1:7,V",
            "Edge3;:G;OFF;:H1:7,E",
            "Edge3;:G;OFF;:H1:7,E;:U2;OFF;:H1:8,V",
            "Edge3;:G;OFF;:H1:7,E;:U;OFF;:H1:7,V",
            "Edge4;:G;OFF;:H1:7,E",
            "Edge4;:G;OFF;:H1:7,E;:U2;OFF;:H1:8,V",
            "Edge4;:G;OFF;:H1:7,E;:U;OFF;:H1:7,V",
            "Edge5;:H1,E",
            "Vertex1;:G;OFF;:H1:7,E",
            "Vertex2;:G;OFF;:H1:7,E",
            "Vertex3;:G;OFF;:H1:7,E",
            "Vertex4;:G;OFF;:H1:7,E",
            "Vertex5;:H1,V",
        }
    ));
}

TEST_F(TopoShapeExpansionTest, makeElementOffset2D)
{
    // Arrange
    const float Len = 3, Wid = 2, Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    // Act
    TopoShape result {wire1, 1L};
    result.makeElementOffset2D(result, 0.25);
    auto elements = elementMap(result);
    Base::BoundBox3d bb = result.getBoundBox();
    // Assert shape is correct
    EXPECT_TRUE(PartTestHelpers::boxesMatch(bb, Base::BoundBox3d(-0.25, -0.25, 0.0, 3.25, 2.25, 0.0)));
    // Assert elementMap is correct
    //   OCCT gives two open pieces here: the offsets of the rectangle's Edge1 (y = 0) and Edge2
    //   (x = 3), and the arcs around its Vertex1 (0, 0) and Vertex3 (3, 2). The rectangle has no
    //   names: each offset line is generated from the edge it offsets, each arc from the vertex
    //   it goes around, with the result's tag (1) and op OFF
    EXPECT_EQ(result.countSubElements("Edge"), 4);
    auto generated = [](const char* element) {
        return linkingName({unmappedName(element, 1, "OFF")}, 1, "OFF", 'E', MAPPER_FLAG_GENERATED);
    };
    auto edgeAt = [&](double x, double y) {
        return elementAt(result, "Edge", Base::Vector3d(x, y, 0));
    };
    auto arcAround = [&](double x, double y) {
        return elementWhere(result, "Edge", [&](const Base::Vector3d& center) {
            return Base::Distance(center, Base::Vector3d(x, y, 0)) < 0.25;
        });
    };
    EXPECT_TRUE(elementHasNames(result, edgeAt(1.5, -0.25).c_str(), {generated("Edge1")}));
    EXPECT_TRUE(elementHasNames(result, edgeAt(3.25, 1).c_str(), {generated("Edge2")}));
    EXPECT_TRUE(elementHasNames(result, arcAround(0, 0).c_str(), {generated("Vertex1")}));
    EXPECT_TRUE(elementHasNames(result, arcAround(3, 2).c_str(), {generated("Vertex3")}));
}

TEST_F(TopoShapeExpansionTest, makeElementOffset2DVertices)
{
    // Arrange
    const float Len = 3, Wid = 2, Rad = 1;
    auto [face1, wire1, wire2] = CreateFaceWithRoundHole(Len, Wid, Rad);
    // Act
    TopoShape result {wire1, 1L};
    result.makeElementOffset2D(result, 0.25);
    // Assert
    //   the offset's vertices are all new, and have no history of their own. The result has no
    //   faces, so each is named UPP from the edges it bounds, as V1 does (ops#21). Before, the
    //   compound of the two pieces named them by their own index (Vertex5;_;1;MKR;..;IDX,SRC), as
    //   if they were elements of an input
    EXPECT_TRUE(allElementsNamed(result));
    EXPECT_TRUE(upperNamed(result, "Vertex", 1, "OFF"));
    for (int index = 1; index <= static_cast<int>(result.countSubElements("Vertex")); ++index) {
        auto name = result.getMappedName(IndexedName::fromConst("Vertex", index));
        EXPECT_FALSE(lastSection(name).hasMapperFlag(MAPPER_FLAG_INDEX)) << name.toString();
    }
}

TEST_F(TopoShapeExpansionTest, makeElementOffset2DOneWireVertices)
{
    // Arrange
    //   a 3 x 2 rectangle wire (tag 1, no names), offset into a result with tag 2. Offset
    //   outwards with arc joins and no open result, it gives one closed wire of 8 edges: 4 lines
    //   and 4 arcs, with 8 new vertices
    TopoShape rectangle {
        BRepBuilderAPI_MakePolygon(
            gp_Pnt(0.0, 0.0, 0.0),
            gp_Pnt(3.0, 0.0, 0.0),
            gp_Pnt(3.0, 2.0, 0.0),
            gp_Pnt(0.0, 2.0, 0.0),
            true
        )
            .Wire(),
        1L
    };
    // Act
    TopoShape result {2L};
    result.makeElementOffset2D(
        rectangle,
        0.25,
        JoinType::arc,
        FillType::noFill,
        OpenResult::noOpenResult
    );
    // Assert
    //   a result without faces: each vertex is named UPP from the two edges it joins (ops#21),
    //   e.g. the one at (3, -0.25) from the offset of the bottom side and the arc around (3, 0)
    EXPECT_EQ(result.countSubElements("Edge"), 8);
    EXPECT_EQ(result.countSubElements("Vertex"), 8);
    EXPECT_TRUE(allElementsNamed(result));
    EXPECT_TRUE(upperNamed(result, "Vertex", 2, "OFF"));
    auto bottom = elementAt(result, "Edge", Base::Vector3d(1.5, -0.25, 0.0));
    auto corner = elementWhere(result, "Edge", [](const Base::Vector3d& center) {
        return Base::Distance(center, Base::Vector3d(3.0, 0.0, 0.0)) < 0.25;
    });
    auto vertex = elementAt(result, "Vertex", Base::Vector3d(3.0, -0.25, 0.0));
    ASSERT_FALSE(bottom.empty() || corner.empty() || vertex.empty());
    EXPECT_TRUE(elementHasNames(
        result,
        vertex.c_str(),
        {linkingName(
            {result.getMappedName(IndexedName(bottom.c_str())),
             result.getMappedName(IndexedName(corner.c_str()))},
            2,
            "OFF",
            'V',
            MAPPER_FLAG_UPPER
        )}
    ));
}

TEST_F(TopoShapeExpansionTest, appendElementSectionV2)
{
    // Arrange
    //   pattern: a pattern instance, a copy of its original's shape that shares the original's
    //   element map (ops#55). Face1 has two names, Edge1 one, the other elements none.
    TopoShape original(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    IndexedName face1("Face", 1);
    IndexedName edge1("Edge", 1);
    auto faceName = MappedName::makeUnmappedName({"Face1"}, 7, "MKR", 'F');
    auto secondFaceName = MappedName::makeUnmappedName({"Face1"}, 7, "XTR", 'F');
    auto edgeName = MappedName::makeUnmappedName({"Edge1"}, 7, "MKR", 'E');
    original.setElementName(face1, faceName, 7L);
    original.setElementName(face1, secondFaceName, 7L);
    original.setElementName(edge1, edgeName, 7L);
    ASSERT_EQ(original.getElementMapSize(), 3);
    TopoShape instance(original);

    // Act
    //   instance 3 of the pattern with ID 5
    instance.appendElementSection(5L, OpCodes::Transformed, "3");

    // Assert
    //   every name ends in '|_;_;5;TRF;3;<type>;0;MOD;_', and an element's names keep their order
    auto faceNames = instance.getElementMappedNames(face1);
    ASSERT_EQ(faceNames.size(), 2);
    EXPECT_EQ(faceNames[0].first.toString(), faceName.toString() + "|_;_;5;TRF;3;F;0;MOD;_");
    EXPECT_EQ(faceNames[1].first.toString(), secondFaceName.toString() + "|_;_;5;TRF;3;F;0;MOD;_");
    EXPECT_EQ(
        instance.getMappedName(edge1).toString(),
        edgeName.toString() + "|_;_;5;TRF;3;E;0;MOD;_"
    );
    EXPECT_EQ(instance.getElementMapSize(), 3);
    EXPECT_FALSE(instance.getMappedName(IndexedName("Face", 2)));
    //   the original keeps its names
    auto originalFaceNames = original.getElementMappedNames(face1);
    ASSERT_EQ(originalFaceNames.size(), 2);
    EXPECT_EQ(originalFaceNames[0].first, faceName);
    EXPECT_EQ(originalFaceNames[1].first, secondFaceName);
    EXPECT_EQ(original.getMappedName(edge1), edgeName);
    EXPECT_EQ(original.getElementMapSize(), 3);
    //   a multi-step pattern's instance has one number per step (ops#6): the name takes it as
    //   it is, and it decodes as the section's one index field
    TopoShape stepInstance(original);
    stepInstance.appendElementSection(5L, OpCodes::Transformed, "2:2");
    auto stepName = stepInstance.getMappedName(edge1);
    EXPECT_EQ(stepName.toString(), edgeName.toString() + "|_;_;5;TRF;2:2;E;0;MOD;_");
    const auto& decoded = MappedName::getDecodedMappedName(stepName.toString());
    ASSERT_EQ(decoded.size(), 2);
    EXPECT_EQ(decoded.back().opCode, OpCodes::Transformed);
    EXPECT_EQ(decoded.back().index, "2:2");
}

TEST_F(TopoShapeExpansionTest, appendElementSectionLeavesV1AndUnnamedShapes)
{
    // Arrange
    //   a V1 shape with a name, and a V2 shape without a map
    IndexedName face1("Face", 1);
    TopoShape v1(App::HistoryAlgorithm::V1, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);
    v1.setElementName(face1, MappedName("Face1;:H7,F"), 7L);
    auto v1Names = v1.getElementMap();
    TopoShape unnamed(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 3.0).Shape(), 7L);

    // Act
    v1.appendElementSection(5L, OpCodes::Transformed, "3");
    unnamed.appendElementSection(5L, OpCodes::Transformed, "3");

    // Assert
    //   both are left as they were
    auto names = v1.getElementMap();
    ASSERT_EQ(names.size(), v1Names.size());
    for (size_t i = 0; i < names.size(); ++i) {
        EXPECT_EQ(names[i].name, v1Names[i].name);
        EXPECT_EQ(names[i].index, v1Names[i].index);
    }
    EXPECT_FALSE(unnamed.hasElementMap());
}

TEST_F(TopoShapeExpansionTest, makeElementCutNamesBothCoincidentPiecesV2)
{
    // Arrange
    //   a compound of two overlapping boxes, and a cylinder standing on their shared corner. The
    //   cut leaves a quarter of the cylinder's side in each box's piece, at the same place: two
    //   faces, of which OCCT's history reports one. The other has no history, and its edges get
    //   their names only in the fallback (UPP), after the faces (ops#25).
    TopoShape box1(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 2.0).Shape(), 1L);
    TopoShape box2(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(2.0, 1.0, 2.0).Shape(), 2L);
    TopoShape cylinder(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeCylinder(0.5, 2.0).Shape(), 3L);
    TopoShape compound(4L);
    compound.makeElementCompound({box1, box2});
    TopoShape result(5L);

    // Act
    result.makeElementCut({compound, cylinder});

    // Assert
    //   each box loses the quarter of the cylinder inside it
    EXPECT_NEAR(getVolume(result.getShape()), 8.0 - 2 * (std::numbers::pi * 0.25 * 2.0 / 4), 1e-6);
    EXPECT_TRUE(allElementsNamed(result));
    std::vector<MappedName> pieces;
    int index = 0;
    for (const auto& face : result.getSubTopoShapes(TopAbs_FACE)) {
        ++index;
        if (BRepAdaptor_Surface(TopoDS::Face(face.getShape())).GetType() == GeomAbs_Cylinder) {
            pieces.push_back(result.getMappedName(IndexedName::fromConst("Face", index)));
        }
    }
    ASSERT_EQ(pieces.size(), 2);
    EXPECT_TRUE(pieces[0]);
    EXPECT_TRUE(pieces[1]);
    EXPECT_NE(pieces[0], pieces[1]);
}

namespace
{
// ops#378: OCCT can store sub-shapes in another order on another platform (the bend arcs of a
// pipe with a round hole come out of the wire in opposite orders on Windows and macOS) or in
// another OCCT version. A result is named, and then a copy that stores the same sub-shapes in
// reverse order; an element told apart from others only by its index must keep its name.

/// The shape at the identity and forward: the same TShape compares equal whatever its place.
TopoDS_Shape bareShape(const TopoDS_Shape& shape)
{
    return shape.Located(TopLoc_Location()).Oriented(TopAbs_FORWARD);
}

/// Which containers store their children in reverse order in the copy.
enum class Reversed
{
    Wires,  ///< each wire's edges: the order that differs in the Pipe's bend
    All,    ///< every container's children: wires, faces' wires, shells, solids, compounds
};

/// The shape with its children stored in reverse order (`reversed`). Every container above the
/// edges is rebuilt once (`copies` maps the original, bare, to its copy), except those the result
/// took from its sources as they are (`kept`, bare): OCCT built only the others. Edges and
/// vertexes stay the same shapes.
TopoDS_Shape reverseChildOrder(
    const TopoDS_Shape& shape,
    Reversed reversed,
    const TopTools_MapOfShape& kept,
    TopTools_DataMapOfShapeShape& copies
)
{
    const TopoDS_Shape bare = bareShape(shape);
    if (shape.ShapeType() >= TopAbs_EDGE || kept.Contains(bare)) {
        return shape;
    }
    if (!copies.IsBound(bare)) {
        std::vector<TopoDS_Shape> children;
        for (TopoDS_Iterator it(bare, Standard_False, Standard_False); it.More(); it.Next()) {
            children.push_back(reverseChildOrder(it.Value(), reversed, kept, copies));
        }
        if (reversed == Reversed::All || bare.ShapeType() == TopAbs_WIRE) {
            std::reverse(children.begin(), children.end());
        }
        TopoDS_Shape copy = bare.EmptyCopied();
        BRep_Builder builder;
        for (const auto& child : children) {
            builder.Add(copy, child);
        }
        copy.Closed(bare.Closed());
        copy.Orientable(bare.Orientable());
        copy.Infinite(bare.Infinite());
        copy.Convex(bare.Convex());
        copies.Bind(bare, copy);
    }
    return copies(bare).Located(shape.Location()).Oriented(shape.Orientation());
}

/// A mapper's history, with the rebuilt containers in place of the original ones.
struct ReorderedMapper: TopoShape::Mapper
{
    ReorderedMapper(const TopoShape::Mapper& mapper, const TopTools_DataMapOfShapeShape& copies)
        : mapper(mapper)
        , copies(copies)
    {}
    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& shape) const override
    {
        return translate(mapper.generated(shape));
    }
    const std::vector<TopoDS_Shape>& modified(const TopoDS_Shape& shape) const override
    {
        return translate(mapper.modified(shape));
    }
    const std::vector<TopoDS_Shape>& projected(const TopoDS_Shape& shape) const override
    {
        return translate(mapper.projected(shape));
    }

private:
    const std::vector<TopoDS_Shape>& translate(const std::vector<TopoDS_Shape>& shapes) const
    {
        _res.clear();
        for (const auto& shape : shapes) {
            if (const TopoDS_Shape* copy = copies.Seek(bareShape(shape))) {
                _res.push_back(copy->Located(shape.Location()).Oriented(shape.Orientation()));
            }
            else {
                _res.push_back(shape);
            }
        }
        return _res;
    }

    const TopoShape::Mapper& mapper;
    const TopTools_DataMapOfShapeShape& copies;
};

/// An element's place: its centre of mass and its length or area (a vertex: its point), moved by
/// `trsf`, in micrometres.
std::array<long long, 4> placeOf(const TopoDS_Shape& element, const gp_Trsf& trsf = gp_Trsf())
{
    gp_Pnt center;
    double mass = 0;
    if (element.ShapeType() == TopAbs_VERTEX) {
        center = BRep_Tool::Pnt(TopoDS::Vertex(element));
    }
    else {
        GProp_GProps props;
        if (element.ShapeType() == TopAbs_FACE) {
            BRepGProp::SurfaceProperties(element, props);
        }
        else {
            BRepGProp::LinearProperties(element, props);
        }
        center = props.CentreOfMass();
        mass = props.Mass();
    }
    center.Transform(trsf);
    const double grid = 1e-6;
    return {
        std::llround(center.X() / grid),
        std::llround(center.Y() / grid),
        std::llround(center.Z() / grid),
        std::llround(mass / grid)
    };
}

using NamesByPlace
    = std::map<std::pair<std::string, std::array<long long, 4>>, std::vector<std::vector<std::string>>>;

/// Each face's, edge's and vertex's names, sorted, by type and place (moved by `trsf`). Coincident
/// elements share a place; their name lists are sorted too.
NamesByPlace namesByPlace(const TopoShape& shape, const gp_Trsf& trsf = gp_Trsf())
{
    NamesByPlace result;
    for (auto type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        const std::string typeName = TopoShape::shapeName(type);
        int index = 0;
        for (const auto& element : shape.getSubShapes(type)) {
            ++index;
            std::vector<std::string> names;
            for (const auto& name :
                 shape.getElementMappedNames(Data::IndexedName::fromConst(typeName.c_str(), index))) {
                names.push_back(name.first.toString());
            }
            std::sort(names.begin(), names.end());
            result[{typeName, placeOf(element, trsf)}].push_back(names);
        }
    }
    for (auto& entry : result) {
        std::sort(entry.second.begin(), entry.second.end());
    }
    return result;
}

/// The places whose names differ between `copy` and `original`, one line each; empty when none.
/// `originalToCopy` moves the original's places onto the copy's (a copy built from moved inputs).
std::string namesDiffer(
    const TopoShape& copy,
    const TopoShape& original,
    const gp_Trsf& originalToCopy = gp_Trsf()
)
{
    const NamesByPlace copyNames = namesByPlace(copy);
    const NamesByPlace originalNames = namesByPlace(original, originalToCopy);
    std::set<NamesByPlace::key_type> places;
    for (const auto* names : {&copyNames, &originalNames}) {
        for (const auto& entry : *names) {
            places.insert(entry.first);
        }
    }
    auto text = [](const NamesByPlace& names, const NamesByPlace::key_type& place) {
        auto found = names.find(place);
        std::string result;
        if (found == names.end()) {
            return std::string("(none)");
        }
        for (const auto& elementNames : found->second) {
            for (const auto& name : elementNames) {
                result += " " + name;
            }
            result += " /";
        }
        return result;
    };
    std::ostringstream out;
    for (const auto& place : places) {
        const std::string copyText = text(copyNames, place);
        const std::string originalText = text(originalNames, place);
        if (copyText != originalText) {
            out << place.first << " at (" << place.second[0] << ", " << place.second[1] << ", "
                << place.second[2] << "): copy" << copyText << " original" << originalText << "\n";
        }
    }
    return out.str();
}

/// The number of faces, edges and vertexes at another index in `copy` than at the same place in
/// `original`.
int movedElements(const TopoShape& original, const TopoShape& copy)
{
    int moved = 0;
    for (auto type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        const auto originalElements = original.getSubShapes(type);
        const auto copyElements = copy.getSubShapes(type);
        for (size_t i = 0; i < originalElements.size() && i < copyElements.size(); ++i) {
            moved += placeOf(originalElements[i]) != placeOf(copyElements[i]) ? 1 : 0;
        }
    }
    return moved;
}

/// `built` named from `mapper` and `sources`, and a copy of it with children in reverse order
/// (`reversed`), named from the same history.
std::pair<TopoShape, TopoShape> nameWithReversedChildren(
    const TopoDS_Shape& built,
    const TopoShape::Mapper& mapper,
    const std::vector<TopoShape>& sources,
    const char* op,
    Reversed reversed
)
{
    TopoShape original(App::HistoryAlgorithm::V2, 10L);
    original.makeShapeWithElementMap(built, mapper, sources, op);
    TopTools_MapOfShape kept;
    for (const auto& source : sources) {
        for (auto type : {TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE, TopAbs_WIRE}) {
            for (TopExp_Explorer xp(source.getShape(), type); xp.More(); xp.Next()) {
                kept.Add(bareShape(xp.Current()));
            }
        }
    }
    TopTools_DataMapOfShapeShape copies;
    const TopoDS_Shape reordered = reverseChildOrder(built, reversed, kept, copies);
    TopoShape copy(App::HistoryAlgorithm::V2, 10L);
    copy.makeShapeWithElementMap(reordered, ReorderedMapper(mapper, copies), sources, op);
    return {original, copy};
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeShapeWithElementMapBendArcsIgnoreChildOrderV2)
{
    // Arrange
    //   a round hole's wire (radius 1) swept along an L path (up 30, then 20 along X) with right
    //   corners, as PartDesign's Pipe sweeps each wire of its profile: at the bend the two legs'
    //   side faces meet in four quarter arcs, which with the four vertexes between them are named
    //   from the same two faces and told apart only by their index (UPP). OCCT stores the arcs in
    //   the first leg's wire in opposite orders on Windows and macOS (ops#378); the copy also
    //   swaps the two faces, which are generated from the same profile edge (S4)
    const gp_Circ circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 1);
    const TopoDS_Wire hole = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire();
    BRepBuilderAPI_MakePolygon path(gp_Pnt(0, 0, 0), gp_Pnt(0, 0, 30), gp_Pnt(20, 0, 30));
    BRepOffsetAPI_MakePipeShell pipe(path.Wire());
    pipe.SetTransitionMode(BRepBuilderAPI_RightCorner);
    pipe.Add(hole);
    pipe.Build();
    ASSERT_TRUE(pipe.IsDone());
    const TopoShape profile(App::HistoryAlgorithm::V2, hole, 1L);

    // Act
    auto [original, copy] = nameWithReversedChildren(
        pipe.Shape(),
        MapperMaker(pipe),
        {profile},
        OpCodes::PipeShell,
        Reversed::All
    );

    // Assert
    //   the four arcs at the bend (centres within the hole's radius of the path's corner), named
    //   four ways
    std::set<std::string> arcNames;
    int arcs = 0;
    int index = 0;
    for (const auto& edge : original.getSubShapes(TopAbs_EDGE)) {
        ++index;
        GProp_GProps props;
        BRepGProp::LinearProperties(edge, props);
        const gp_Pnt center = props.CentreOfMass();
        if (std::abs(center.X()) < 1 && std::abs(center.Z() - 30) < 1) {
            ++arcs;
            arcNames.insert(original.getMappedName(IndexedName::fromConst("Edge", index)).toString());
        }
    }
    EXPECT_EQ(arcs, 4);
    EXPECT_EQ(arcNames.size(), 4);
    EXPECT_EQ(arcNames.count(""), 0);
    //   the copy's arcs are at other indexes, and every element has the same names as the
    //   original's at the same place
    EXPECT_GT(movedElements(original, copy), 0);
    EXPECT_EQ(namesDiffer(copy, original), "");
}

TEST_F(TopoShapeExpansionTest, makeShapeWithElementMapCutCornersIgnoreChildOrderV2)
{
    // Arrange
    //   a compound of two overlapping boxes cut by a cylinder standing on their shared corner
    //   (TestNamingDump's CompoundCut): the cut corners' vertexes are named from the same faces
    //   and told apart only by their place (UPP, ops#378). Every container is reversed: two
    //   modified edges of the top face took another Connected Name when the faces were, the
    //   first named ancestor face in the result's face order; they take the smallest by name
    //   (ops#431)
    TopoShape box1(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(1.0, 2.0, 2.0).Shape(), 1L);
    TopoShape box2(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(2.0, 1.0, 2.0).Shape(), 2L);
    TopoShape cylinder(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeCylinder(0.5, 2.0).Shape(), 3L);
    TopoShape compound(4L);
    compound.makeElementCompound({box1, box2});
    BRepAlgoAPI_Cut cut(compound.getShape(), cylinder.getShape());
    ASSERT_TRUE(cut.IsDone());

    // Act
    auto [original, copy] = nameWithReversedChildren(
        cut.Shape(),
        MapperMaker(cut),
        {compound, cylinder},
        OpCodes::Cut,
        Reversed::All
    );

    // Assert
    EXPECT_TRUE(allElementsNamed(original));
    EXPECT_GT(movedElements(original, copy), 0);
    EXPECT_EQ(namesDiffer(copy, original), "");
}

TEST_F(TopoShapeExpansionTest, makeShapeWithElementMapPipeShellEndsIgnoreChildOrderV2)
{
    // Arrange
    //   a 4 x 2 rectangle swept 20 along Z, as a solid (TestNamingDump's PipeShell Sweep): each
    //   end section's four edges are generated from the same end vertex of the spine and told
    //   apart only by their index (S4, ops#378)
    const TopoDS_Wire rectangle = BRepBuilderAPI_MakePolygon(
                                      gp_Pnt(0, 0, 0),
                                      gp_Pnt(4, 0, 0),
                                      gp_Pnt(4, 2, 0),
                                      gp_Pnt(0, 2, 0),
                                      Standard_True
    )
                                      .Wire();
    const TopoDS_Wire line = BRepBuilderAPI_MakeWire(
                                 BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(0, 0, 20)).Edge()
    )
                                 .Wire();
    BRepOffsetAPI_MakePipeShell pipe(line);
    pipe.Add(rectangle);
    pipe.Build();
    ASSERT_TRUE(pipe.MakeSolid());
    const TopoShape spine(App::HistoryAlgorithm::V2, line, 1L);
    const TopoShape profile(App::HistoryAlgorithm::V2, rectangle, 2L);

    // Act
    auto [original, copy] = nameWithReversedChildren(
        pipe.Shape(),
        MapperMaker(pipe),
        {spine, profile},
        OpCodes::PipeShell,
        Reversed::All
    );

    // Assert
    EXPECT_TRUE(allElementsNamed(original));
    EXPECT_GT(movedElements(original, copy), 0);
    EXPECT_EQ(namesDiffer(copy, original), "");
}

TEST_F(TopoShapeExpansionTest, makeShapeWithElementMapSliceIgnoresChildOrderV2)
{
    // Arrange
    //   a 10 mm cube cut by the half space above z = 5, as TopoCrossSection slices a solid
    //   (TestNamingDump's Slice): the slice face's edges and vertexes are generated from the
    //   plane and the cube's sides (S2, S4, ops#378)
    const TopoShape cube(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(10, 10, 10).Shape(), 1L);
    const TopoDS_Face plane = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 5), gp_Dir(0, 0, 1))).Face();
    const TopoShape halfSpace(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeHalfSpace(plane, gp_Pnt(0, 0, 6)).Solid(),
        2L
    );
    BRepAlgoAPI_Cut cut(cube.getShape(), halfSpace.getShape());
    ASSERT_TRUE(cut.IsDone());

    // Act
    auto [original, copy] = nameWithReversedChildren(
        cut.Shape(),
        MapperMaker(cut),
        {cube, halfSpace},
        OpCodes::Slice,
        Reversed::All
    );

    // Assert
    //   the lower half is left
    EXPECT_NEAR(getVolume(original.getShape()), 500, 1e-6);
    EXPECT_TRUE(allElementsNamed(original));
    EXPECT_GT(movedElements(original, copy), 0);
    EXPECT_EQ(namesDiffer(copy, original), "");
}

namespace
{
// ops#378 round 2: an index that tells members of a group apart must survive the edits that
// leave the group's structure alone: a dimension edit, a rigid motion of the inputs, a tilt
// through an axis-aligned position. Round 1's key (the centre of mass, X first) swapped a loft's
// start and end edges when its top radius passed its bottom radius, and renumbered a Hole's
// coaxial faces when its axis tilted through vertical (fork PR 355 round 1's review).

/// The hole's wire (radius 1) swept along an L path with right corners, as the bend-arcs order
/// test builds it, from inputs moved by `trsf`, named V2.
TopoShape namedHoledPipe(const gp_Trsf& trsf)
{
    const gp_Circ circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 1);
    const TopoDS_Shape hole
        = BRepBuilderAPI_Transform(
              BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire(),
              trsf,
              Standard_True
        )
              .Shape();
    const TopoDS_Shape path
        = BRepBuilderAPI_Transform(
              BRepBuilderAPI_MakePolygon(gp_Pnt(0, 0, 0), gp_Pnt(0, 0, 30), gp_Pnt(20, 0, 30)).Wire(),
              trsf,
              Standard_True
        )
              .Shape();
    BRepOffsetAPI_MakePipeShell pipe(TopoDS::Wire(path));
    pipe.SetTransitionMode(BRepBuilderAPI_RightCorner);
    pipe.Add(TopoDS::Wire(hole));
    pipe.Build();
    EXPECT_TRUE(pipe.IsDone());
    const TopoShape profile(App::HistoryAlgorithm::V2, hole, 1L);
    TopoShape result(App::HistoryAlgorithm::V2, 10L);
    result.makeShapeWithElementMap(pipe.Shape(), MapperMaker(pipe), {profile}, OpCodes::PipeShell);
    return result;
}

/// A 4 x 2 rectangle centred on the Z axis, its edges E1 .. E4 from (-2, -1) counterclockwise,
/// swept 20 along Z as a solid, from inputs moved by `trsf`, named V2 with the spine and the
/// profile as inputs (without the spine the end edges have no shared source).
TopoShape namedSweptRectangle(const gp_Trsf& trsf)
{
    const TopoDS_Shape rectangle = BRepBuilderAPI_Transform(
                                       BRepBuilderAPI_MakePolygon(
                                           gp_Pnt(-2, -1, 0),
                                           gp_Pnt(2, -1, 0),
                                           gp_Pnt(2, 1, 0),
                                           gp_Pnt(-2, 1, 0),
                                           Standard_True
                                       )
                                           .Wire(),
                                       trsf,
                                       Standard_True
    )
                                       .Shape();
    const TopoDS_Shape line = BRepBuilderAPI_Transform(
                                  BRepBuilderAPI_MakeWire(
                                      BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(0, 0, 20)).Edge()
                                  )
                                      .Wire(),
                                  trsf,
                                  Standard_True
    )
                                  .Shape();
    BRepOffsetAPI_MakePipeShell pipe(TopoDS::Wire(line));
    pipe.Add(TopoDS::Wire(rectangle));
    pipe.Build();
    EXPECT_TRUE(pipe.MakeSolid());
    const TopoShape spine(App::HistoryAlgorithm::V2, line, 1L);
    const TopoShape profile(App::HistoryAlgorithm::V2, rectangle, 2L);
    TopoShape result(App::HistoryAlgorithm::V2, 10L);
    result.makeShapeWithElementMap(pipe.Shape(), MapperMaker(pipe), {spine, profile}, OpCodes::PipeShell);
    return result;
}

/// A rotation of 127 degrees about Z, then a move by (5, -3, 2): an ordinary placement, with no
/// axis of the inputs left along X, Y or Z.
gp_Trsf ordinaryMotion()
{
    gp_Trsf rotation;
    rotation.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 127.0 * std::numbers::pi / 180);
    gp_Trsf move;
    move.SetTranslation(gp_Vec(5, -3, 2));
    return move * rotation;
}

/// A rotation about Z by `degrees`.
gp_Trsf rotationAboutZ(double degrees)
{
    gp_Trsf rotation;
    rotation.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), degrees * std::numbers::pi / 180);
    return rotation;
}

/// A circle, radius 2, swept with right corners along a U path: up 30, across 20 along X, down
/// `downLength`; from inputs moved by `trsf`, named V2 with the circle as the only input, as
/// FeaturePipe names its result (with the spine as an input too, each leg's face has a source
/// of its own, the spine's edge, and no index).
TopoShape namedPipeLegs(double downLength, const gp_Trsf& trsf)
{
    const gp_Circ circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 2);
    const TopoDS_Shape profile
        = BRepBuilderAPI_Transform(
              BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire(),
              trsf,
              Standard_True
        )
              .Shape();
    const TopoDS_Shape path = BRepBuilderAPI_Transform(
                                  BRepBuilderAPI_MakePolygon(
                                      gp_Pnt(0, 0, 0),
                                      gp_Pnt(0, 0, 30),
                                      gp_Pnt(20, 0, 30),
                                      gp_Pnt(20, 0, 30 - downLength)
                                  )
                                      .Wire(),
                                  trsf,
                                  Standard_True
    )
                                  .Shape();
    BRepOffsetAPI_MakePipeShell pipe(TopoDS::Wire(path));
    pipe.SetTransitionMode(BRepBuilderAPI_RightCorner);
    pipe.Add(TopoDS::Wire(profile));
    pipe.Build();
    EXPECT_TRUE(pipe.IsDone());
    const TopoShape input(App::HistoryAlgorithm::V2, profile, 1L);
    TopoShape result(App::HistoryAlgorithm::V2, 10L);
    result.makeShapeWithElementMap(pipe.Shape(), MapperMaker(pipe), {input}, OpCodes::PipeShell);
    return result;
}

/// A history in which one source face generates one result face, and nothing else has any.
struct OneFaceMapper: TopoShape::Mapper
{
    OneFaceMapper(TopoDS_Shape source, TopoDS_Shape face)
        : source(std::move(source))
        , face(std::move(face))
    {}
    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& shape) const override
    {
        _res.clear();
        if (shape.IsSame(source)) {
            _res.push_back(face);
        }
        return _res;
    }

private:
    TopoDS_Shape source;
    TopoDS_Shape face;
};

/// The UPP index of each element of `shape` that is named from other elements by `op`, by the
/// names it is named from and its end: `end(centre)` says which end of the shape an element is
/// at (0 or 1), or -1 for one to skip.
std::map<std::vector<std::string>, std::map<int, int>> upperIndexesByEnd(
    const TopoShape& shape,
    const char* op,
    const std::function<int(const gp_Pnt&)>& end
)
{
    std::map<std::vector<std::string>, std::map<int, int>> indexes;
    for (auto type : {TopAbs_EDGE, TopAbs_VERTEX}) {
        const std::string typeName = TopoShape::shapeName(type);
        int index = 0;
        for (const auto& element : shape.getSubShapes(type)) {
            ++index;
            gp_Pnt center;
            if (type == TopAbs_VERTEX) {
                center = BRep_Tool::Pnt(TopoDS::Vertex(element));
            }
            else {
                GProp_GProps props;
                BRepGProp::LinearProperties(element, props);
                center = props.CentreOfMass();
            }
            const int atEnd = end(center);
            if (atEnd < 0) {
                continue;
            }
            const MappedName name = shape.getMappedName(
                Data::IndexedName::fromConst(typeName.c_str(), index)
            );
            const DecodedMappedSection section = lastSection(name);
            if (section.opCode != op || !section.hasMapperFlag(Data::MAPPER_FLAG_UPPER)) {
                continue;
            }
            std::vector<std::string> list = section.linkedNames;
            list.insert(list.begin(), typeName);
            indexes[list][atEnd] = std::stoi(section.index);
        }
    }
    return indexes;
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeElementLoftEndsKeepIndexesAcrossRadiusV2)
{
    // Arrange
    //   a smooth solid loft through a circle, radius 5, at z = 0, a square, side 8, at z = 10,
    //   and a circle, radius r_top, at z = 20 (gen0 LoftPipe's SmoothLoft). Each side face's
    //   start edge (z = 0) and end edge (z = 20) are named from that face alone, since the caps
    //   are named after the edges, so the pair is told apart only by its index; the vertexes
    //   between the side faces pair up the same way. The start comes first (v = 0 on the face),
    //   whatever the radii: an edit of r_top across 5 must not swap the pair (fork PR 355
    //   round 1's finding 1)
    auto circleAt = [](double z, double radius) {
        const gp_Circ circle(gp_Ax2(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)), radius);
        return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(circle).Edge()).Wire();
    };
    const TopoDS_Wire square = BRepBuilderAPI_MakePolygon(
                                   gp_Pnt(-4, -4, 10),
                                   gp_Pnt(4, -4, 10),
                                   gp_Pnt(4, 4, 10),
                                   gp_Pnt(-4, 4, 10),
                                   Standard_True
    )
                                   .Wire();
    auto whichEnd = [](const gp_Pnt& center) {
        if (std::abs(center.Z()) < 1e-6) {
            return 0;
        }
        if (std::abs(center.Z() - 20) < 1e-6) {
            return 1;
        }
        return -1;
    };

    for (double topRadius : {3.0, 4.9, 5.1, 6.0}) {
        // Act
        const TopoShape bottom(App::HistoryAlgorithm::V2, circleAt(0, 5), 1L);
        const TopoShape middle(App::HistoryAlgorithm::V2, square, 2L);
        const TopoShape top(App::HistoryAlgorithm::V2, circleAt(20, topRadius), 3L);
        TopoShape loft(App::HistoryAlgorithm::V2, 10L);
        loft.makeElementLoft({bottom, middle, top}, IsSolid::solid, IsRuled::notRuled);

        // Assert
        //   every index-told pair: the z = 0 member at index 0, the z = 20 member at index 1
        const auto pairs = upperIndexesByEnd(loft, OpCodes::Loft, whichEnd);
        EXPECT_GE(pairs.size(), 6) << "r_top " << topRadius;
        for (const auto& [list, byEnd] : pairs) {
            ASSERT_EQ(byEnd.size(), 2) << "r_top " << topRadius << ", " << list.front();
            EXPECT_EQ(byEnd.at(0), 0) << "r_top " << topRadius << ", " << list.front();
            EXPECT_EQ(byEnd.at(1), 1) << "r_top " << topRadius << ", " << list.front();
        }
    }
}

TEST_F(TopoShapeExpansionTest, makeShapeWithElementMapBendArcsKeepNamesUnderRigidMotionV2)
{
    // Arrange
    //   the holed pipe of the bend-arcs order test, and the same built from the path and the
    //   hole moved as one by an ordinary placement. The arcs' and vertexes' UPP indexes come from
    //   where they lie on the face they are named from, and the two legs' faces' S4 indexes from
    //   OCCT's history list, so the motion changes no name; a key in the shape's coordinates
    //   would renumber them (fork PR 355 round 1's finding 2, the Hole's tilt, is the same defect)
    const gp_Trsf motion = ordinaryMotion();

    // Act
    const TopoShape original = namedHoledPipe(gp_Trsf());
    const TopoShape moved = namedHoledPipe(motion);

    // Assert
    //   the original's four arcs are named four ways, and every element of the moved pipe has
    //   the original's names at the moved place
    std::set<std::string> arcNames;
    int index = 0;
    for (const auto& edge : original.getSubShapes(TopAbs_EDGE)) {
        ++index;
        GProp_GProps props;
        BRepGProp::LinearProperties(edge, props);
        const gp_Pnt center = props.CentreOfMass();
        if (std::abs(center.X()) < 1 && std::abs(center.Z() - 30) < 1) {
            arcNames.insert(original.getMappedName(IndexedName::fromConst("Edge", index)).toString());
        }
    }
    EXPECT_EQ(arcNames.size(), 4);
    EXPECT_EQ(arcNames.count(""), 0);
    EXPECT_NE(namesDiffer(moved, original), "");  // the places did move
    EXPECT_EQ(namesDiffer(moved, original, motion), "");
}

TEST_F(TopoShapeExpansionTest, makeShapeWithElementMapPipeShellEndsFollowProfileOrderV2)
{
    // Arrange
    //   the centred rectangle swept 20 along Z, turned with its spine about Z by 0, 90 and 127
    //   degrees. Each end's four edges are generated from the spine's end vertex and told apart
    //   only by their index (S4). OCCT lists them in the profile's edge order at every rotation,
    //   and the index follows that list. Round 1's key (the centre of mass, X first) permuted
    //   them with the rotation; a key on the distance from the spine's vertex ties for a centred
    //   profile and leaves them to the shape's coordinates too
    const std::array<gp_Pnt, 4> profileEdgeCentres {
        gp_Pnt(0, -1, 0),
        gp_Pnt(2, 0, 0),
        gp_Pnt(0, 1, 0),
        gp_Pnt(-2, 0, 0)
    };
    const TopoShape unturned = namedSweptRectangle(gp_Trsf());

    for (double degrees : {0.0, 90.0, 127.0}) {
        // Act
        const gp_Trsf turn = rotationAboutZ(degrees);
        const TopoShape swept = namedSweptRectangle(turn);

        // Assert
        //   each end edge has the index of its profile edge's place in the profile, E1 .. E4
        EXPECT_TRUE(allElementsNamed(swept)) << degrees << " degrees";
        int endEdges = 0;
        int index = 0;
        for (const auto& edge : swept.getSubShapes(TopAbs_EDGE)) {
            ++index;
            GProp_GProps props;
            BRepGProp::LinearProperties(edge, props);
            const gp_Pnt center = props.CentreOfMass();
            for (double z : {0.0, 20.0}) {
                for (std::size_t place = 0; place < profileEdgeCentres.size(); ++place) {
                    const gp_Pnt expected
                        = profileEdgeCentres[place].Translated(gp_Vec(0, 0, z)).Transformed(turn);
                    if (center.Distance(expected) > 1e-6) {
                        continue;
                    }
                    ++endEdges;
                    const DecodedMappedSection section = lastSection(
                        swept.getMappedName(IndexedName::fromConst("Edge", index))
                    );
                    EXPECT_EQ(section.opCode, OpCodes::PipeShell);
                    EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_GENERATED));
                    EXPECT_EQ(section.index, std::to_string(place))
                        << degrees << " degrees, z " << z << ", E" << place + 1;
                }
            }
        }
        EXPECT_EQ(endEdges, 8) << degrees << " degrees";
        //   and every element has the unturned sweep's names at the turned place
        EXPECT_EQ(namesDiffer(swept, unturned, turn), "") << degrees << " degrees";
    }
}

TEST_F(TopoShapeExpansionTest, makeShapeWithElementMapPipeLegsFollowSpineOrderV2)
{
    // Arrange
    //   a circle swept along a U path: up 30, across 20, down 10, 30 or 60; then the same turned
    //   127 degrees about Z. With the circle as the only input every leg's face is generated
    //   from the circle's edge, and the legs are told apart only by their index (S4). OCCT lists
    //   them in the spine's order, so the up leg is 0, the across leg 1 and the down leg 2 in
    //   every state. Round 1's key (X first) put the down leg before the across leg once turned;
    //   a key on the place along the circle's axis did at every length (ops#378 section 9,
    //   probe B)
    for (double degrees : {0.0, 127.0}) {
        const gp_Trsf turn = rotationAboutZ(degrees);
        for (double downLength : {10.0, 30.0, 60.0}) {
            // Act
            const TopoShape pipe = namedPipeLegs(downLength, turn);

            // Assert
            //   the legs' faces, by their centres in the unturned path (within the radius of the
            //   leg's axis: the corners trim each leg's inner side shorter)
            std::map<std::string, DecodedMappedSection> legs;
            int index = 0;
            for (const auto& face : pipe.getSubShapes(TopAbs_FACE)) {
                ++index;
                GProp_GProps props;
                BRepGProp::SurfaceProperties(face, props);
                const gp_Pnt center = props.CentreOfMass().Transformed(turn.Inverted());
                std::string leg;
                if (std::abs(center.X()) < 2 && center.Z() > 3 && center.Z() < 27) {
                    leg = "up";
                }
                else if (std::abs(center.Z() - 30) < 2 && center.X() > 5 && center.X() < 15) {
                    leg = "across";
                }
                else if (std::abs(center.X() - 20) < 2 && center.Z() < 27) {
                    leg = "down";
                }
                else {
                    continue;
                }
                legs[leg] = lastSection(pipe.getMappedName(IndexedName::fromConst("Face", index)));
            }
            ASSERT_EQ(legs.size(), 3) << degrees << " degrees, down " << downLength;
            for (const auto& [leg, section] : legs) {
                EXPECT_EQ(section.opCode, OpCodes::PipeShell) << leg;
                EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_GENERATED)) << leg;
                EXPECT_EQ(section.linkedNames, legs["up"].linkedNames) << leg;
            }
            EXPECT_EQ(legs["up"].index, "0") << degrees << " degrees, down " << downLength;
            EXPECT_EQ(legs["across"].index, "1") << degrees << " degrees, down " << downLength;
            EXPECT_EQ(legs["down"].index, "2") << degrees << " degrees, down " << downLength;
        }
    }
}

TEST_F(TopoShapeExpansionTest, makeShapeWithElementMapSeamKeepsIndexUnderWireOrderV2)
{
    // Arrange
    //   a cone's side face with a history of its own (generated from a face of another shape)
    //   and nothing else with one: its seam, its degenerate tip edge and its base circle are
    //   named from that face alone and told apart only by their index (UPP), ordered by their
    //   parameters on the face. The seam has two pcurves on it, u = 0 and u = 2 pi; which one
    //   BRep_Tool::CurveOnSurface reads follows the orientation the result stores the seam with
    //   first, which a copy with its wires' edges in reverse order flips. The seam's place is the
    //   smaller of the two, so its index doesn't depend on that
    const TopoDS_Shape cone = BRepPrimAPI_MakeCone(2, 0, 4).Shape();
    TopoDS_Shape side;
    for (TopExp_Explorer faces(cone, TopAbs_FACE); faces.More(); faces.Next()) {
        if (BRepAdaptor_Surface(TopoDS::Face(faces.Current())).GetType() == GeomAbs_Cone) {
            side = faces.Current();
        }
    }
    ASSERT_FALSE(side.IsNull());
    int degenerated = 0;
    for (TopExp_Explorer edges(side, TopAbs_EDGE); edges.More(); edges.Next()) {
        degenerated += BRep_Tool::Degenerated(TopoDS::Edge(edges.Current())) ? 1 : 0;
    }
    ASSERT_GT(degenerated, 0);
    const TopoDS_Shape plate
        = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, -5), gp_Dir(0, 0, 1)), 0, 1, 0, 1).Face();
    const TopoShape source(App::HistoryAlgorithm::V2, plate, 1L);

    // Act
    auto [original, copy] = nameWithReversedChildren(
        cone,
        OneFaceMapper(plate, side),
        {source},
        OpCodes::Maker,
        Reversed::Wires
    );

    // Assert
    //   the side face's edges are UPP, named from the side face alone, and every element has the
    //   same names in the copy as in the original at the same place
    EXPECT_TRUE(allElementsNamed(original));
    int upperEdges = 0;
    for (int index = 1; index <= static_cast<int>(original.countSubElements("Edge")); ++index) {
        const DecodedMappedSection section = lastSection(
            original.getMappedName(IndexedName::fromConst("Edge", index))
        );
        upperEdges += section.hasMapperFlag(MAPPER_FLAG_UPPER) && section.linkedNames.size() == 1;
    }
    EXPECT_EQ(upperEdges, 3);
    EXPECT_GT(movedElements(original, copy), 0);
    EXPECT_EQ(namesDiffer(copy, original), "");
}

namespace
{
/// A cylinder (radius 5, height 10) whose profile is a circle drawn as two half arcs, the
/// profile turned about Z by `degrees`, extruded and offset by 1, named V2 (TestNamingDump's
/// OffsetSplitCylinder). The offset's caps are planes, which OCCT builds with `u` along world X
/// whatever the profile's turn. The profile's face and arcs carry given names: with `capFirst`,
/// the names of the caps' descendants sort before those of the half-cylinders' (as interned
/// names can), else after.
TopoShape namedSplitCylinderOffset(double degrees, bool capFirst)
{
    const gp_Circ circle(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 5);
    const TopoDS_Wire wire
        = BRepBuilderAPI_MakeWire(
              BRepBuilderAPI_MakeEdge(circle, 0, std::numbers::pi).Edge(),
              BRepBuilderAPI_MakeEdge(circle, std::numbers::pi, 2 * std::numbers::pi).Edge()
        )
              .Wire();
    // The face is made from the turned wire, so OCCT chooses its plane's axes, as for a sketch
    const TopoDS_Face face
        = BRepBuilderAPI_MakeFace(
              TopoDS::Wire(
                  BRepBuilderAPI_Transform(wire, rotationAboutZ(degrees), Standard_True).Shape()
              ),
              Standard_True
        )
              .Face();
    TopoShape profile(App::HistoryAlgorithm::V2, face, 1L);
    profile.setElementName(IndexedName::fromConst("Face", 1), MappedName(capFirst ? "A" : "Z"), 1L);
    for (int arc = 1; arc <= 2; ++arc) {
        profile.setElementName(
            IndexedName::fromConst("Edge", arc),
            MappedName((capFirst ? "Z" : "A") + std::to_string(arc)),
            1L
        );
    }
    TopoShape cylinder(App::HistoryAlgorithm::V2, 2L);
    cylinder.makeElementPrism(profile, gp_Vec(0, 0, 10));
    TopoShape offset(App::HistoryAlgorithm::V2, 3L);
    offset.makeElementOffset(cylinder, 1.0, 1e-7);
    return offset;
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeElementOffsetSplitCylinderNamesUpperListsWithTheirCountV2)
{
    // Arrange
    //   the offset split cylinder: the cap vertexes over the split are named from a cap and the
    //   two half-cylinders (UPP), a list of two
    for (bool capFirst : {true, false}) {
        SCOPED_TRACE(capFirst);

        // Act
        const TopoShape offset = namedSplitCylinderOffset(0, capFirst);

        // Assert
        //   the members of a list of two carry 0of2 and 1of2 in DuplicateCount, Index 0 (the size
        //   rule, I-A2); and no ORD: their order is their place on a half-cylinder, a face that
        //   is a proper part of its period, which a rigid motion or a turn of the profile keeps
        //   (`naming-class-A.md` M2 (b), CC3 measured right in its section 6)
        int listed = 0;
        for (const char* type : {"Face", "Edge", "Vertex"}) {
            for (int index = 1; index <= static_cast<int>(offset.countSubElements(type)); ++index) {
                const DecodedMappedSection section
                    = lastSection(offset.getMappedName(IndexedName::fromConst(type, index)));
                if (!section.hasMapperFlag(MAPPER_FLAG_UPPER)) {
                    continue;
                }
                EXPECT_EQ(section.index, "0") << type << index;
                EXPECT_FALSE(section.hasMapperFlag(MAPPER_FLAG_ORDERED)) << type << index;
                if (section.duplicateCount != "0") {
                    EXPECT_TRUE(
                        section.duplicateCount == "0of2" || section.duplicateCount == "1of2"
                    ) << type
                      << index << " " << section.duplicateCount;
                    ++listed;
                }
            }
        }
        EXPECT_GE(listed, 2);
        EXPECT_EQ(listed % 2, 0);
    }
}

TEST_F(TopoShapeExpansionTest, makeElementOffsetDividedCylinderMarksPeriodicListsOrderedV2)
{
    // Arrange
    //   a cylinder (radius 5, height 10) whose cap circles are each divided into two half arcs at
    //   u = 0 and u = pi, its side one whole cylindrical face, offset by 1. Each cap's two offset
    //   vertexes (and arcs) are named from that cap and the cylinder (UPP), a list of two whose
    //   order is their `u` on the cylinder: a whole period, where `u` can jump by 2 pi with the
    //   members unmoved (`naming-class-A.md` M2 (b) (ii))
    ShapeUpgrade_ShapeDivideClosedEdges divide(BRepPrimAPI_MakeCylinder(5, 10).Shape());
    divide.SetNbSplitPoints(1);
    ASSERT_TRUE(divide.Perform());
    const TopoShape cylinder(App::HistoryAlgorithm::V2, divide.Result(), 1L);
    ASSERT_EQ(cylinder.countSubElements("Face"), 3);
    ASSERT_EQ(cylinder.countSubElements("Edge"), 5);

    // Act
    TopoShape offset(App::HistoryAlgorithm::V2, 2L);
    offset.makeElementOffset(cylinder, 1.0, 1e-7);

    // Assert
    //   every member of a list of two carries its place (0of2, 1of2) and ORD, Index 0; the
    //   members of one list differ by their place only
    std::map<std::string, std::vector<std::string>> lists;
    for (const char* type : {"Edge", "Vertex"}) {
        for (int index = 1; index <= static_cast<int>(offset.countSubElements(type)); ++index) {
            const MappedName name = offset.getMappedName(IndexedName::fromConst(type, index));
            const DecodedMappedSection section = lastSection(name);
            if (!section.hasMapperFlag(MAPPER_FLAG_UPPER) || section.duplicateCount == "0") {
                continue;
            }
            EXPECT_EQ(section.index, "0") << type << index;
            EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_ORDERED)) << type << index;
            std::string key = name.toString();
            key.replace(key.rfind(section.duplicateCount), section.duplicateCount.size(), "*");
            lists[key].push_back(section.duplicateCount);
        }
    }
    EXPECT_FALSE(lists.empty());
    for (auto& [key, places] : lists) {
        std::sort(places.begin(), places.end());
        EXPECT_EQ(places, (std::vector<std::string> {"0of2", "1of2"})) << key;
    }
}

TEST_F(TopoShapeExpansionTest, makeElementOffsetSplitCylinderKeepsNamesWhenTurnedV2)
{
    // Arrange
    //   the offset split cylinder, and the same from a profile turned by 100 degrees about Z. The
    //   offset's cap vertexes over the split are named from a cap and the two half-cylinders
    //   (UPP) and told apart only by their index. Their places are read on the first named face
    //   that isn't a plane: a cap's `u` runs along world X at every turn, so on the cap the pair
    //   swapped between 90 and 100 degrees (fork PR 355 round 2's review, finding 1). Whether a
    //   cap is the list's first name depends on how the names sort; both orders are checked
    for (bool capFirst : {true, false}) {
        const TopoShape unturned = namedSplitCylinderOffset(0, capFirst);
        for (double degrees : {-100.0, 100.0}) {
            // Act
            const TopoShape turned = namedSplitCylinderOffset(degrees, capFirst);

            // Assert
            //   every element has the unturned offset's names at the turned place
            EXPECT_TRUE(allElementsNamed(turned)) << degrees << " degrees";
            EXPECT_EQ(namesDiffer(turned, unturned, rotationAboutZ(degrees)), "")
                << degrees << " degrees, cap first: " << capFirst;
        }
    }
}

TEST_F(TopoShapeExpansionTest, makeElementSectionVertexesKeepNamesAcrossTheSeamV2)
{
    // Arrange
    //   a cylinder (radius 5, height 10, its seam at x = 5, y = 0) cut by a vertical plane 1 from
    //   its axis, turned about Z. Each circle's two section vertexes are generated from that
    //   circle (S4) and told apart only by their index. OCCT lists them along the circle from its
    //   seam, so the list's order flips when a chord end passes the seam (between turns of 78 and
    //   80 degrees either way); the vertexes of a group generated from a closed edge keep the
    //   result's order instead (fork PR 355 round 2's review, finding 2)
    const TopoShape cylinder(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeCylinder(5, 10).Shape(), 1L);
    const double halfChord = std::acos(0.2) * 180 / std::numbers::pi;  // 78.46 degrees
    auto sectionNames = [&](double degrees) {
        const TopoDS_Shape plane
            = BRepBuilderAPI_Transform(
                  BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(1, 0, 0), gp_Dir(1, 0, 0)), -15, 15, -15, 15)
                      .Face(),
                  rotationAboutZ(degrees),
                  Standard_True
            )
                  .Shape();
        TopoShape section(App::HistoryAlgorithm::V2, 3L);
        section.makeElementBoolean(
            OpCodes::Section,
            {cylinder, TopoShape(App::HistoryAlgorithm::V2, plane, 2L)}
        );
        //   each vertex's name by the end of the chord it is at (+ or -) and its circle (z)
        std::map<std::string, std::string> names;
        const auto vertexes = section.getSubShapes(TopAbs_VERTEX);
        for (int index = 1; index <= static_cast<int>(vertexes.size()); ++index) {
            const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(vertexes[index - 1]));
            for (double side : {1.0, -1.0}) {
                const double angle = (degrees + side * halfChord) * std::numbers::pi / 180;
                for (double z : {0.0, 10.0}) {
                    if (point.Distance(gp_Pnt(5 * std::cos(angle), 5 * std::sin(angle), z)) < 1e-6) {
                        names[(side > 0 ? "+" : "-") + std::to_string(static_cast<int>(z))]
                            = section.getMappedName(IndexedName::fromConst("Vertex", index)).toString();
                    }
                }
            }
        }
        return names;
    };

    for (auto [before, after] : {std::pair {-80.0, -78.0}, std::pair {78.0, 80.0}}) {
        // Act
        const auto namesBefore = sectionNames(before);
        const auto namesAfter = sectionNames(after);

        // Assert
        //   the four vertexes are found and keep their names as the chord end passes the seam
        EXPECT_EQ(namesBefore.size(), 4) << before;
        EXPECT_EQ(namesBefore, namesAfter) << before << " to " << after << " degrees";
    }
}

namespace
{
/// Six 8 x 4 rectangles in a 3 x 2 grid, 5 apart in X and 3 in Y, so that neighbours overlap
/// (PatternSteps' copies), each extruded 4 along Z, the grid turned about Z by `degrees`, and
/// fused, named V2. Each profile face is made from the turned wire, so OCCT chooses its plane's
/// axes, as for a sketch: `u` runs along world X at every turn.
TopoShape namedFusedRectangleGrid(double degrees)
{
    const gp_Trsf turn = rotationAboutZ(degrees);
    std::vector<TopoShape> blocks;
    long tag = 1;
    for (double y : {0.0, 3.0}) {
        for (double x : {0.0, 5.0, 10.0}) {
            BRepBuilderAPI_MakePolygon polygon(
                gp_Pnt(x, y, 0).Transformed(turn),
                gp_Pnt(x + 8, y, 0).Transformed(turn),
                gp_Pnt(x + 8, y + 4, 0).Transformed(turn),
                gp_Pnt(x, y + 4, 0).Transformed(turn),
                Standard_True
            );
            const TopoShape profile(
                App::HistoryAlgorithm::V2,
                BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face(),
                tag++
            );
            TopoShape block(App::HistoryAlgorithm::V2, tag++);
            block.makeElementPrism(profile, gp_Vec(0, 0, 4));
            blocks.push_back(block);
        }
    }
    TopoShape fused(App::HistoryAlgorithm::V2, tag);
    fused.makeElementFuse(blocks);
    return fused;
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeElementFuseOfRectangleGridKeepsNamesWhenTurnedV2)
{
    // Arrange
    //   the fused grid, and the same turned by 100 degrees about Z. Where the copies overlap, the
    //   fuse leaves pairs of edges on a cap (the bottom or the top face of the result) that have no
    //   history and are named from that cap alone (UPP), told apart only by their index. Their
    //   places can't be read on the cap: its `u` runs along world X at every turn, so a key on it
    //   swapped the pairs between turns of 89 and 91 degrees (fork PR 355 round 3's review,
    //   finding 1). A list named only from planes keeps the result's order instead
    const TopoShape unturned = namedFusedRectangleGrid(0);
    int upperFromOneFace = 0;
    for (int index = 1; index <= static_cast<int>(unturned.countSubElements("Edge")); ++index) {
        const DecodedMappedSection section = lastSection(
            unturned.getMappedName(IndexedName::fromConst("Edge", index))
        );
        upperFromOneFace += section.hasMapperFlag(MAPPER_FLAG_UPPER)
            && section.linkedNames.size() == 1 && section.index == "1";
    }
    EXPECT_GT(upperFromOneFace, 0);  // the case is there

    // Act
    const TopoShape turned = namedFusedRectangleGrid(100);

    // Assert
    //   every element has the unturned fuse's names at the turned place
    EXPECT_TRUE(allElementsNamed(turned));
    EXPECT_EQ(namesDiffer(turned, unturned, rotationAboutZ(100)), "");
}

namespace
{
/// The last sections of the names of `shape`'s vertexes where `where` holds, by place along X
/// then Y.
std::vector<DecodedMappedSection> vertexSectionsWhere(
    const TopoShape& shape,
    const std::function<bool(const gp_Pnt&)>& where
)
{
    std::vector<std::pair<std::pair<double, double>, DecodedMappedSection>> found;
    int index = 0;
    for (const auto& vertex : shape.getSubShapes(TopAbs_VERTEX)) {
        ++index;
        const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(vertex));
        if (where(point)) {
            found.push_back(
                {{point.X(), point.Y()},
                 lastSection(shape.getMappedName(IndexedName::fromConst("Vertex", index)))}
            );
        }
    }
    std::sort(found.begin(), found.end(), [](const auto& left, const auto& right) {
        return left.first < right.first;
    });
    std::vector<DecodedMappedSection> sections;
    for (const auto& entry : found) {
        sections.push_back(entry.second);
    }
    return sections;
}

/// A 10 mm box at the origin cut by a cylinder of radius 1 along Z through it, centred at
/// (`x`, 0.3): it breaks out of the box's front face (y = 0) and crosses the face's bottom and
/// top edges, named V2.
TopoShape boxCutByCylinderAt(double x)
{
    TopoShape box(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), 1L);
    TopoShape cylinder(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, 0.3, -1.0), gp_Dir(0, 0, 1)), 1.0, 12.0).Shape(),
        2L
    );
    TopoShape result(App::HistoryAlgorithm::V2, 3L);
    result.makeElementCut({box, cylinder});
    return result;
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeElementCutNamesTwinVertexesByTheirSideV2)
{
    // Arrange
    //   the cylinder crosses the box's front bottom edge twice, at x = 5 -+ 0.954: both vertexes
    //   are generated from that edge and the cylinder's face. They are told apart by the side of
    //   the face the edge goes to there, not by a counter alone (ops#468): when an edit takes one
    //   of them away, or adds one to a lone one (a hole's seam leaving the edge), the other keeps
    //   its name. The cylinder at the box's corner crosses the edge once, where it leaves the
    //   cylinder going along +X, as the twins' second crossing does
    auto onBottomEdge = [](const gp_Pnt& p) {
        return std::abs(p.Y()) < 1e-6 && std::abs(p.Z()) < 1e-6 && p.X() > 1e-6 && p.X() < 10 - 1e-6;
    };

    // Act
    const TopoShape twins = boxCutByCylinderAt(5.0);
    const TopoShape lone = boxCutByCylinderAt(0.5);

    // Assert
    //   the twins' names differ only in the side, `in` / `out`, a role in Index (no place among
    //   twins in DuplicateCount), and carry ORD, so that the solver re-checks an exact hit that
    //   moved (the role-sibling clause, naming-class-A.md 4.1); the lone crossing has the side of
    //   the twin at the larger x, with ORD too
    EXPECT_TRUE(allElementsNamed(twins));
    const auto twinSections = vertexSectionsWhere(twins, onBottomEdge);
    ASSERT_EQ(twinSections.size(), 2);
    std::set<std::string> indexes;
    for (const auto& section : twinSections) {
        EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_GENERATED));
        EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_ORDERED));
        EXPECT_EQ(section.duplicateCount, "0");
        EXPECT_EQ(section.linkedNames, twinSections.front().linkedNames);
        indexes.insert(section.index);
    }
    EXPECT_EQ(indexes, (std::set<std::string> {ROLE_CROSSING_IN, ROLE_CROSSING_OUT}));
    const auto loneSections = vertexSectionsWhere(lone, onBottomEdge);
    ASSERT_EQ(loneSections.size(), 1);
    EXPECT_TRUE(loneSections.front().hasMapperFlag(MAPPER_FLAG_GENERATED));
    EXPECT_TRUE(loneSections.front().hasMapperFlag(MAPPER_FLAG_ORDERED));
    EXPECT_EQ(loneSections.front().index, twinSections.back().index);
    EXPECT_EQ(loneSections.front().duplicateCount, "0");
    //   only vertexes are named by a side: the lines and arcs the cut makes are named as before
    for (const TopoShape* shape : {&twins, &lone}) {
        for (const char* type : {"Edge", "Face"}) {
            for (int index = 1; index <= static_cast<int>(shape->countSubElements(type)); ++index) {
                const std::string sectionIndex
                    = lastSection(shape->getMappedName(IndexedName::fromConst(type, index))).index;
                EXPECT_TRUE(std::all_of(sectionIndex.begin(), sectionIndex.end(), [](char c) {
                    return std::isdigit(static_cast<unsigned char>(c)) || c == '_';
                })) << type
                    << index << " " << sectionIndex;
            }
        }
    }
}

TEST_F(TopoShapeExpansionTest, makeElementCutNamesRepeatedSidesByTheirOrderV2)
{
    // Arrange
    //   a torus (radii 3 and 1, its seams turned 45 degrees off the X axis) cut out of a box whose
    //   front bottom edge runs along X at z = 0.3 through the tube: the edge crosses the torus's
    //   one face four times, entering it twice and leaving it twice. A side seen more than once is
    //   counted along it (ops#468)
    TopoShape box(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeBox(gp_Pnt(-10.0, 0.0, 0.3), 20.0, 5.0, 5.0).Shape(),
        1L
    );
    const double half = std::sqrt(0.5);
    const gp_Ax2 axes(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1), gp_Dir(half, half, 0));
    TopoShape torus(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeTorus(axes, 3.0, 1.0).Shape(), 2L);
    TopoShape result(App::HistoryAlgorithm::V2, 3L);

    // Act
    result.makeElementCut({box, torus});

    // Assert
    //   the four crossings are `in` 0of2 and 1of2 and `out` 0of2 and 1of2 (the role in Index, the
    //   place among the crossings on the same side in DuplicateCount, with ORD), the sides
    //   alternating along X
    EXPECT_TRUE(allElementsNamed(result));
    const auto sections = vertexSectionsWhere(result, [](const gp_Pnt& p) {
        return std::abs(p.Y()) < 1e-6 && std::abs(p.Z() - 0.3) < 1e-6 && std::abs(p.X()) < 10 - 1e-6;
    });
    ASSERT_EQ(sections.size(), 4);
    std::set<std::string> places;
    for (const auto& section : sections) {
        EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_GENERATED));
        EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_ORDERED));
        places.insert(section.index + " " + section.duplicateCount);
    }
    EXPECT_EQ(
        places,
        (std::set<std::string> {"in 0of2", "in 1of2", "out 0of2", "out 1of2"})
    );
    for (std::size_t k = 1; k < sections.size(); ++k) {
        EXPECT_NE(sections[k].index, sections[k - 1].index);
    }
}

TEST_F(TopoShapeExpansionTest, makeElementCutNamesTwinVertexesOnAClosedEdgeByTheirSideV2)
{
    // Arrange
    //   a cylinder (radius 2, height 10) cut by a box whose face at x = 1 crosses the top circle
    //   twice, at y = -+1.732: the vertexes are generated from the circle and that face. The
    //   circle enters the box's side at one and leaves it at the other, wherever its seam lies
    TopoShape cylinder(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeCylinder(2.0, 10.0).Shape(), 1L);
    TopoShape box(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeBox(gp_Pnt(1.0, -5.0, 8.0), 5.0, 10.0, 4.0).Shape(),
        2L
    );
    TopoShape result(App::HistoryAlgorithm::V2, 3L);

    // Act
    result.makeElementCut({cylinder, box});

    // Assert
    EXPECT_TRUE(allElementsNamed(result));
    const auto sections = vertexSectionsWhere(result, [](const gp_Pnt& p) {
        return std::abs(p.X() - 1) < 1e-6 && std::abs(p.Z() - 10) < 1e-6;
    });
    ASSERT_EQ(sections.size(), 2);
    std::set<std::string> indexes;
    for (const auto& section : sections) {
        EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_GENERATED));
        EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_ORDERED));
        EXPECT_EQ(section.duplicateCount, "0");
        indexes.insert(section.index);
    }
    EXPECT_EQ(indexes, (std::set<std::string> {ROLE_CROSSING_IN, ROLE_CROSSING_OUT}));
}

namespace
{
/// The model B of `naming-class-A.md` 4.1 (CC1): box A, 10 mm at the origin, and box B, 10 mm at
/// (5, -5, 2), fused in the order A, B or (`reordered`) B, A, then cut by a cylinder of radius 1
/// along Z through (5, 0.3). The fuse's section edge y = 0, z = 2 (A's front face meets B's
/// bottom face) is crossed twice, at x = 5 -+ 0.954. The crossings' names, by x.
std::vector<std::string> sectionCrossingNames(bool reordered)
{
    TopoShape a(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), 1L);
    TopoShape b(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeBox(gp_Pnt(5.0, -5.0, 2.0), 10.0, 10.0, 10.0).Shape(),
        2L
    );
    TopoShape fused(App::HistoryAlgorithm::V2, 3L);
    fused.makeElementFuse(reordered ? std::vector<TopoShape> {b, a} : std::vector<TopoShape> {a, b});
    TopoShape cylinder(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(5.0, 0.3, -3.0), gp_Dir(0, 0, 1)), 1.0, 20.0).Shape(),
        4L
    );
    TopoShape result(App::HistoryAlgorithm::V2, 5L);
    result.makeElementCut({fused, cylinder});
    std::vector<std::pair<double, std::string>> found;
    int index = 0;
    for (const auto& vertex : result.getSubShapes(TopAbs_VERTEX)) {
        ++index;
        const gp_Pnt p = BRep_Tool::Pnt(TopoDS::Vertex(vertex));
        if (std::abs(p.Y()) < 1e-6 && std::abs(p.Z() - 2) < 1e-6 && std::abs(p.X() - 5) < 1.5) {
            found.emplace_back(
                p.X(),
                result.getMappedName(IndexedName::fromConst("Vertex", index)).toString()
            );
        }
    }
    std::sort(found.begin(), found.end());
    std::vector<std::string> names;
    for (const auto& entry : found) {
        names.push_back(entry.second);
    }
    return names;
}

DecodedMappedSection lastSectionOf(const std::string& name)
{
    return lastSection(MappedName(name));
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeElementCutNamesFlippedCrossingsByTheirSideV2)
{
    // Arrange
    //   the fuse's inputs reordered reverse its section edge's curve with the geometry unchanged:
    //   the side of the cylinder's face the edge goes to flips at both crossings (a switch point
    //   of the role, `naming-class-A.md` 4.1 item 5, measured in `flip2.txt`)

    // Act
    const auto names = sectionCrossingNames(false);
    const auto reorderedNames = sectionCrossingNames(true);

    // Assert
    //   each order names the crossings `in` and `out`, with ORD, which sends a moved exact hit to
    //   the solver's twin check
    ASSERT_EQ(names.size(), 2);
    ASSERT_EQ(reorderedNames.size(), 2);
    for (const auto* list : {&names, &reorderedNames}) {
        std::set<std::string> roles;
        for (const auto& name : *list) {
            const DecodedMappedSection section = lastSectionOf(name);
            EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_ORDERED)) << name;
            EXPECT_EQ(section.duplicateCount, "0") << name;
            roles.insert(section.index);
        }
        EXPECT_EQ(roles, (std::set<std::string> {ROLE_CROSSING_IN, ROLE_CROSSING_OUT}));
    }
    //   after the reorder, the two names sit on the swapped crossings: equal up to the role,
    //   each name reaches the other crossing exactly (role siblings, which the solver takes for
    //   twins: D1's half of the case)
    EXPECT_NE(lastSectionOf(names[0]).index, lastSectionOf(reorderedNames[0]).index);
    EXPECT_EQ(names[0], reorderedNames[1]);
    EXPECT_EQ(names[1], reorderedNames[0]);
}

namespace
{
/// ops#431's model (`notes\ops431-connected-name.md` 1): box A, 10 mm at the origin, and boxes B
/// and C, [3, 5] x [-3, 3] x [-1, 1] turned +30 and -30 degrees about the vertical axis through
/// V = (5, 0, 0). A's edge y = 0, z = 0 leaves B and C's union at V, where B's and C's turned
/// x = 5 faces meet it: the piece [5, 10] of the edge has two faces from other inputs at V.
std::array<TopoShape, 3> splitEdgeInputs()
{
    auto turned = [](double degrees, long tag) {
        gp_Trsf turn;
        turn.SetRotation(gp_Ax1(gp_Pnt(5, 0, 0), gp_Dir(0, 0, 1)), degrees * std::numbers::pi / 180);
        const TopoDS_Shape box = BRepPrimAPI_MakeBox(gp_Pnt(3, -3, -1), 2.0, 6.0, 2.0).Shape();
        return TopoShape(
            App::HistoryAlgorithm::V2,
            BRepBuilderAPI_Transform(box, turn, Standard_True).Shape(),
            tag
        );
    };
    return {
        TopoShape(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), 1L),
        turned(30, 2L),
        turned(-30, 3L)
    };
}

/// The names of the pieces of A's edge y = 0, z = 0 in `shape`, by their centre's x.
std::vector<std::string> splitEdgePieceNames(const TopoShape& shape)
{
    std::vector<std::pair<double, std::string>> found;
    int index = 0;
    for (const auto& edge : shape.getSubShapes(TopAbs_EDGE)) {
        ++index;
        GProp_GProps props;
        BRepGProp::LinearProperties(edge, props);
        const gp_Pnt center = props.CentreOfMass();
        if (std::abs(center.Y()) < 1e-6 && std::abs(center.Z()) < 1e-6) {
            found.emplace_back(
                center.X(),
                shape.getMappedName(IndexedName::fromConst("Edge", index)).toString()
            );
        }
    }
    std::sort(found.begin(), found.end());
    std::vector<std::string> names;
    for (const auto& entry : found) {
        names.push_back(entry.second);
    }
    return names;
}
}  // namespace

TEST_F(TopoShapeExpansionTest, makeShapeWithElementMapSplitEdgeIgnoresFaceOrderV2)
{
    // Arrange
    //   A fused with B and C, then named again with every container's children reversed (the
    //   result's faces in another order)
    const auto [a, b, c] = splitEdgeInputs();
    BRepAlgoAPI_Fuse fuse;
    TopTools_ListOfShape arguments;
    arguments.Append(a.getShape());
    TopTools_ListOfShape tools;
    tools.Append(b.getShape());
    tools.Append(c.getShape());
    fuse.SetArguments(arguments);
    fuse.SetTools(tools);
    fuse.Build();
    ASSERT_TRUE(fuse.IsDone());

    // Act
    auto [original, copy] = nameWithReversedChildren(
        fuse.Shape(),
        MapperMaker(fuse),
        {a, b, c},
        OpCodes::Fuse,
        Reversed::All
    );

    // Assert
    //   the edge's two pieces are told apart by Connected Names, and each takes the smallest of
    //   the faces from other inputs at its end by name, whatever the result's face order (ops#431)
    EXPECT_TRUE(allElementsNamed(original));
    EXPECT_GT(movedElements(original, copy), 0);
    EXPECT_EQ(namesDiffer(copy, original), "");
    const auto pieces = splitEdgePieceNames(original);
    ASSERT_EQ(pieces.size(), 2);
    for (const auto& name : pieces) {
        const DecodedMappedSection section = lastSectionOf(name);
        EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_MODIFIED)) << name;
        EXPECT_FALSE(section.connectedElements.empty()) << name;
        EXPECT_FALSE(section.hasMapperFlag(MAPPER_FLAG_ORDERED)) << name;
    }
}

TEST_F(TopoShapeExpansionTest, makeElementFuseSplitEdgeIgnoresInputOrderV2)
{
    // Arrange
    //   ops#431's model fused as A, B, C and as A, C, B (a MultiFuse's Shapes reordered)
    const auto [a, b, c] = splitEdgeInputs();
    TopoShape fused(App::HistoryAlgorithm::V2, 4L);
    TopoShape reordered(App::HistoryAlgorithm::V2, 4L);

    // Act
    fused.makeElementFuse({a, b, c});
    reordered.makeElementFuse({a, c, b});

    // Assert
    //   the edge's pieces keep their names: each piece's Connected Name at V is the smaller of
    //   B's and C's faces by name, not the one the result lists first
    const auto pieces = splitEdgePieceNames(fused);
    ASSERT_EQ(pieces.size(), 2);
    EXPECT_EQ(splitEdgePieceNames(reordered), pieces);
}

TEST_F(TopoShapeExpansionTest, genericShapeMapperFallbackFollowsFaceOrderV2)
{
    // Arrange
    //   two 10 mm boxes side by side, fused, and refined: the block's top face merges the boxes'
    //   top faces, and shares no two edges with one of them (its long edges are merged too), so
    //   the mapper falls back on geometry: both top faces lie in its plane. It took the first in
    //   an unordered_map's order, which follows hashes (H1, `naming-class-A.md` M2 (f)); it takes
    //   the first in the source's order of its faces. The source is also stored with its
    //   children in reverse order, which reverses its faces' order
    TopoShape a(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), 1L);
    TopoShape b(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeBox(gp_Pnt(10.0, 0.0, 0.0), 10.0, 10.0, 10.0).Shape(),
        2L
    );
    TopoShape fused(App::HistoryAlgorithm::V2, 3L);
    fused.makeElementFuse({a, b});
    auto onTop = [](const TopoDS_Shape& face) {
        GProp_GProps props;
        BRepGProp::SurfaceProperties(face, props);
        return std::abs(props.CentreOfMass().Z() - 10) < 1e-6;
    };

    for (const bool reversed : {false, true}) {
        SCOPED_TRACE(reversed);
        TopTools_DataMapOfShapeShape copies;
        const TopoDS_Shape source = reversed
            ? reverseChildOrder(fused.getShape(), Reversed::All, TopTools_MapOfShape(), copies)
            : fused.getShape();
        const TopoShape src(source);
        BRepBuilderAPI_RefineModel refine(source);
        ASSERT_TRUE(refine.IsDone());

        // Act
        GenericShapeMapper mapper;
        mapper.init(src, refine.Shape());

        // Assert
        //   the merged top face is generated from the source's first top face, not the other
        TopoDS_Shape merged;
        for (const auto& face : TopoShape(refine.Shape()).getSubShapes(TopAbs_FACE)) {
            if (onTop(face)) {
                merged = face;
            }
        }
        ASSERT_FALSE(merged.IsNull());
        std::vector<TopoDS_Shape> tops;
        for (const auto& face : src.getSubShapes(TopAbs_FACE)) {
            if (onTop(face)) {
                tops.push_back(face);
            }
        }
        ASSERT_EQ(tops.size(), 2);
        auto generates = [&mapper, &merged](const TopoDS_Shape& face) {
            const auto& generated = mapper.generated(face);
            return std::any_of(generated.begin(), generated.end(), [&merged](const TopoDS_Shape& g) {
                return g.IsSame(merged);
            });
        };
        EXPECT_TRUE(generates(tops[0]));
        EXPECT_FALSE(generates(tops[1]));
    }
}

TEST_F(TopoShapeExpansionTest, makeElementCutNamesTwinLinesByTheirPlaceV2)
{
    // Arrange
    //   a 10 mm box cut by a cylinder of radius 1 along Z from z = 2 to 8, centred at (5, 0.3): it
    //   breaks out of the box's front face (y = 0) in two vertical lines at x = 5 -+ 0.954, both
    //   generated from the front face and the cylinder's face, and ending at vertexes generated
    //   from the front face and the cylinder's circles. With the face first among their sources,
    //   the vertexes have no side (a crossing's side is told on the edge first: the class note's
    //   asymmetry), so the lines are told apart by nothing of their own: twins
    TopoShape box(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), 1L);
    TopoShape cylinder(
        App::HistoryAlgorithm::V2,
        BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(5.0, 0.3, 2.0), gp_Dir(0, 0, 1)), 1.0, 6.0).Shape(),
        2L
    );
    BRepAlgoAPI_Cut cut(box.getShape(), cylinder.getShape());
    ASSERT_TRUE(cut.IsDone());

    // Act
    auto [original, copy] = nameWithReversedChildren(
        cut.Shape(),
        MapperMaker(cut),
        {box, cylinder},
        OpCodes::Cut,
        Reversed::All
    );

    // Assert
    //   the lines are 0of2 and 1of2 in DuplicateCount (the size rule), Index 0, with ORD; and so
    //   are the vertexes at each end
    EXPECT_TRUE(allElementsNamed(original));
    std::set<std::string> places;
    int index = 0;
    for (const auto& edge : original.getSubShapes(TopAbs_EDGE)) {
        ++index;
        GProp_GProps props;
        BRepGProp::LinearProperties(edge, props);
        const gp_Pnt center = props.CentreOfMass();
        if (std::abs(center.Y()) < 1e-6 && std::abs(center.Z() - 5) < 1e-6) {
            const DecodedMappedSection section
                = lastSection(original.getMappedName(IndexedName::fromConst("Edge", index)));
            EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_GENERATED));
            EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_ORDERED));
            EXPECT_EQ(section.index, "0");
            places.insert(section.duplicateCount);
        }
    }
    EXPECT_EQ(places, (std::set<std::string> {"0of2", "1of2"}));
    for (const double z : {2.0, 8.0}) {
        const auto sections = vertexSectionsWhere(original, [z](const gp_Pnt& p) {
            return std::abs(p.Y()) < 1e-6 && std::abs(p.Z() - z) < 1e-6;
        });
        ASSERT_EQ(sections.size(), 2);
        std::set<std::string> vertexPlaces;
        for (const auto& section : sections) {
            EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_ORDERED));
            EXPECT_EQ(section.index, "0");
            vertexPlaces.insert(section.duplicateCount);
        }
        EXPECT_EQ(vertexPlaces, (std::set<std::string> {"0of2", "1of2"}));
    }
    //   the places follow the twins' canonical order, not the result's: the same names at the
    //   same places when the result stores its children in reverse order
    EXPECT_GT(movedElements(original, copy), 0);
    EXPECT_EQ(namesDiffer(copy, original), "");
}

TEST_F(TopoShapeExpansionTest, makeElementCutNamesTwinPiecesOfASplitFaceByTheirPlaceV2)
{
    // Arrange
    //   a cylinder (radius 5, height 10, its seam at +X) cut by two slots through its wall along
    //   its axis, at +X (taking the seam) and at -X: the side face falls into two halves, and each
    //   rim circle into two arcs. A half's edges are the arcs, whose names both halves share, and
    //   the slots' lines, which the cut generates: no Connected Name tells the halves apart. The
    //   modified stage tells them apart by their place on the side face (twinOrder), with the
    //   count
    TopoShape cylinder(App::HistoryAlgorithm::V2, BRepPrimAPI_MakeCylinder(5.0, 10.0).Shape(), 1L);
    TopoDS_Compound slots;
    BRep_Builder builder;
    builder.MakeCompound(slots);
    builder.Add(slots, BRepPrimAPI_MakeBox(gp_Pnt(4.0, -0.5, -1.0), 2.0, 1.0, 12.0).Shape());
    builder.Add(slots, BRepPrimAPI_MakeBox(gp_Pnt(-6.0, -0.5, -1.0), 2.0, 1.0, 12.0).Shape());
    TopoShape tool(App::HistoryAlgorithm::V2, slots, 2L);
    BRepAlgoAPI_Cut cut(cylinder.getShape(), tool.getShape());
    ASSERT_TRUE(cut.IsDone());

    // Act
    auto [original, copy] = nameWithReversedChildren(
        cut.Shape(),
        MapperMaker(cut),
        {cylinder, tool},
        OpCodes::Cut,
        Reversed::All
    );

    // Assert
    //   the halves are MOD, Index 0, 0of2 and 1of2 in DuplicateCount, with ORD
    EXPECT_TRUE(allElementsNamed(original));
    std::set<std::string> places;
    int index = 0;
    for (const auto& face : original.getSubShapes(TopAbs_FACE)) {
        ++index;
        if (BRepAdaptor_Surface(TopoDS::Face(face)).GetType() != GeomAbs_Cylinder) {
            continue;
        }
        const DecodedMappedSection section
            = lastSection(original.getMappedName(IndexedName::fromConst("Face", index)));
        EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_MODIFIED));
        EXPECT_TRUE(section.hasMapperFlag(MAPPER_FLAG_ORDERED));
        EXPECT_EQ(section.index, "0");
        EXPECT_TRUE(section.connectedElements.empty());
        places.insert(section.duplicateCount);
    }
    EXPECT_EQ(places, (std::set<std::string> {"0of2", "1of2"}));
    EXPECT_GT(movedElements(original, copy), 0);
    EXPECT_EQ(namesDiffer(copy, original), "");
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
