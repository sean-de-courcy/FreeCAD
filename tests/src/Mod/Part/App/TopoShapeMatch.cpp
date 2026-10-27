// SPDX-License-Identifier: LGPL-2.1-or-later

// The names of a result without history, by a verified match against the result it replaces (MLN,
// ops#502): each rung of the matcher and each refusal, the ids and their counter, and the hook in
// PropertyPartShape. Designed shapes only; every expectation is geometric.

#include <gtest/gtest.h>

#include "src/App/InitApplication.h"
#include <App/Document.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/PrimitiveFeature.h>
#include <Mod/Part/App/PropertyTopoShape.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeMatch.h>

#include <cmath>
#include <memory>
#include <string>
#include <optional>
#include <vector>

#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <GProp_GProps.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

namespace
{

constexpr double tolerance = 1e-7;
constexpr double pi = 3.14159265358979323846;

TopoDS_Shape box(double x, double height = 10)
{
    return BRepPrimAPI_MakeBox(gp_Pnt(x, 0, 0), 10, 10, height).Shape();
}

TopoDS_Wire polyline(const std::vector<gp_Pnt>& points, bool closed = false)
{
    BRepBuilderAPI_MakePolygon polygon;
    for (const auto& point : points) {
        polygon.Add(point);
    }
    if (closed) {
        polygon.Close();
    }
    return polygon.Wire();
}

// A regular prism of \a sides sides, circumradius 10, a vertex at angle 0, height \a height
TopoDS_Shape prism(int sides, double height = 10)
{
    BRepBuilderAPI_MakePolygon polygon;
    for (int k = 0; k < sides; ++k) {
        const double angle = 2 * pi * k / sides;
        polygon.Add(gp_Pnt(10 * std::cos(angle), 10 * std::sin(angle), 0));
    }
    polygon.Close();
    const TopoDS_Face base = BRepBuilderAPI_MakeFace(polygon.Wire()).Face();
    return BRepPrimAPI_MakePrism(base, gp_Vec(0, 0, height)).Shape();
}

TopoDS_Face square(double x0, double x1)
{
    const TopoDS_Wire outline = polyline(
        {gp_Pnt(x0, 0, 0), gp_Pnt(x1, 0, 0), gp_Pnt(x1, 10, 0), gp_Pnt(x0, 10, 0)},
        true
    );
    return BRepBuilderAPI_MakeFace(outline).Face();
}

TopoDS_Compound compound(std::initializer_list<TopoDS_Shape> shapes)
{
    TopoDS_Compound res;
    BRep_Builder builder;
    builder.MakeCompound(res);
    for (const auto& shape : shapes) {
        builder.Add(res, shape);
    }
    return res;
}

TopTools_IndexedMapOfShape elements(const TopoDS_Shape& shape, TopAbs_ShapeEnum type)
{
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, type, map);
    return map;
}

gp_Pnt pointOf(const TopoDS_Shape& shape, int vertex)
{
    return BRep_Tool::Pnt(TopoDS::Vertex(elements(shape, TopAbs_VERTEX)(vertex)));
}

// The index (from 1) of the vertex of \a shape at \a point, 0 if none
int vertexAt(const TopoDS_Shape& shape, const gp_Pnt& point)
{
    const auto map = elements(shape, TopAbs_VERTEX);
    for (int i = 1; i <= map.Extent(); ++i) {
        if (BRep_Tool::Pnt(TopoDS::Vertex(map(i))).Distance(point) < tolerance) {
            return i;
        }
    }
    return 0;
}

// The oriented normal of a planar face
std::optional<gp_Dir> planeNormal(const TopoDS_Face& face)
{
    BRepAdaptor_Surface surface(face, false);
    if (surface.GetType() != GeomAbs_Plane) {
        return std::nullopt;
    }
    gp_Dir normal = surface.Plane().Axis().Direction();
    if (face.Orientation() == TopAbs_REVERSED) {
        normal.Reverse();
    }
    return normal;
}

gp_Pnt centreOf(const TopoDS_Shape& face)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(face, props);
    return props.CentreOfMass();
}

// The index (from 1) of the planar face of \a shape with the oriented normal \a normal whose centre
// is at \a level along it, 0 if none
int planarFace(const TopoDS_Shape& shape, const gp_Dir& normal, double level)
{
    const auto map = elements(shape, TopAbs_FACE);
    for (int i = 1; i <= map.Extent(); ++i) {
        const auto own = planeNormal(TopoDS::Face(map(i)));
        if (own && own->IsEqual(normal, 1e-9)
            && std::abs(gp_Vec(centreOf(map(i)).XYZ()).Dot(gp_Vec(normal)) - level) < 1e-6) {
            return i;
        }
    }
    return 0;
}

// The index (from 1) of the face of \a shape of surface kind \a kind, 0 if none or several
int faceOfKind(const TopoDS_Shape& shape, GeomAbs_SurfaceType kind)
{
    const auto map = elements(shape, TopAbs_FACE);
    int found = 0;
    for (int i = 1; i <= map.Extent(); ++i) {
        if (BRepAdaptor_Surface(TopoDS::Face(map(i)), false).GetType() == kind) {
            if (found) {
                return 0;
            }
            found = i;
        }
    }
    return found;
}

// The index (from 1) of the edge of \a shape whose midpoint (by parameter) is at \a point
int edgeThrough(const TopoDS_Shape& shape, const gp_Pnt& point)
{
    const auto map = elements(shape, TopAbs_EDGE);
    for (int i = 1; i <= map.Extent(); ++i) {
        double first = 0;
        double last = 0;
        const auto curve = BRep_Tool::Curve(TopoDS::Edge(map(i)), first, last);
        if (curve && curve->Value(0.5 * (first + last)).Distance(point) < 1e-6) {
            return i;
        }
    }
    return 0;
}

}  // namespace

// Rungs 1 and 3: the same shape built again keeps every element
TEST(TopoShapeMatch, identicalShapeKeepsEveryElement)
{
    const auto matches = Part::matchElements(box(0), box(0), false);
    EXPECT_FALSE(matches.byIndex);
    ASSERT_EQ(matches.vertexes.size(), 8);
    ASSERT_EQ(matches.edges.size(), 12);
    ASSERT_EQ(matches.faces.size(), 6);
    for (const auto& [now, old] : matches.faces) {
        EXPECT_EQ(now, old);
    }
}

// Rung 6: a fixed construction order with the same counts and incidences keeps every index
TEST(TopoShapeMatch, fixedOrderKeepsIndexesWhenTheConstructionIsTheSame)
{
    const auto matches = Part::matchElements(box(0), box(0, 20), true);
    EXPECT_TRUE(matches.byIndex);
    EXPECT_EQ(matches.vertexes.size(), 8);
    EXPECT_EQ(matches.edges.size(), 12);
    EXPECT_EQ(matches.faces.size(), 6);
}

// Rung 2 then 3, without a fixed order: the top's corners moved, each held by the corner below it
TEST(TopoShapeMatch, boxMadeTallerKeepsEveryElement)
{
    const TopoDS_Shape before = box(0);
    const TopoDS_Shape after = box(0, 20);
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_FALSE(matches.byIndex);
    EXPECT_EQ(matches.vertexes.size(), 8);
    EXPECT_EQ(matches.edges.size(), 12);
    ASSERT_EQ(matches.faces.size(), 6);
    EXPECT_EQ(matches.faces.at(planarFace(after, gp_Dir(0, 0, 1), 20)), planarFace(before, gp_Dir(0, 0, 1), 10));
    EXPECT_EQ(matches.faces.at(planarFace(after, gp_Dir(1, 0, 0), 10)), planarFace(before, gp_Dir(1, 0, 0), 10));
    const int top = vertexAt(after, gp_Pnt(10, 10, 20));
    ASSERT_TRUE(matches.vertexes.count(top));
    EXPECT_EQ(matches.vertexes.at(top), vertexAt(before, gp_Pnt(10, 10, 10)));
}

// Rung 2: an end point moved, held by its matched neighbour
TEST(TopoShapeMatch, movedEndPointKeepsItsId)
{
    const auto before = polyline({gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0), gp_Pnt(10, 10, 0), gp_Pnt(0, 10, 0)});
    const auto after = polyline({gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0), gp_Pnt(10, 10, 0), gp_Pnt(0, 12, 0)});
    const auto matches = Part::matchElements(before, after, false);
    ASSERT_EQ(matches.vertexes.size(), 4);
    EXPECT_EQ(matches.vertexes.at(vertexAt(after, gp_Pnt(0, 12, 0))), vertexAt(before, gp_Pnt(0, 10, 0)));
    ASSERT_EQ(matches.edges.size(), 3);
    EXPECT_EQ(
        matches.edges.at(edgeThrough(after, gp_Pnt(5, 11, 0))),
        edgeThrough(before, gp_Pnt(5, 10, 0))
    );
}

// Rung 2's direction term (CC1): a point moved across its neighbour is not the same point
TEST(TopoShapeMatch, pointMovedAcrossItsNeighbourTakesAFreshId)
{
    const auto before = polyline({gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0), gp_Pnt(10, 10, 0)});
    const auto after = polyline({gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0), gp_Pnt(10, -10, 0)});
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_EQ(matches.vertexes.size(), 2);
    EXPECT_FALSE(matches.vertexes.count(vertexAt(after, gp_Pnt(10, -10, 0))));
    EXPECT_EQ(matches.edges.size(), 1);
}

// Rung 1: a wire drawn the other way keeps every element, each at its place
TEST(TopoShapeMatch, reversedWireKeepsEveryElement)
{
    const std::vector<gp_Pnt> points {gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0), gp_Pnt(10, 10, 0), gp_Pnt(0, 10, 0)};
    const auto before = polyline(points);
    const auto after = polyline(std::vector<gp_Pnt>(points.rbegin(), points.rend()));
    const auto matches = Part::matchElements(before, after, false);
    ASSERT_EQ(matches.vertexes.size(), 4);
    for (const auto& [now, old] : matches.vertexes) {
        EXPECT_LT(pointOf(after, now).Distance(pointOf(before, old)), tolerance);
    }
    EXPECT_EQ(matches.edges.size(), 3);
}

// Every face rung's side term (CC2): a face at its place facing the other way is another face
TEST(TopoShapeMatch, reversedFaceTakesAFreshId)
{
    const TopoDS_Face before = square(0, 10);
    const auto matches = Part::matchElements(before, before.Reversed(), false);
    EXPECT_EQ(matches.vertexes.size(), 4);
    EXPECT_EQ(matches.edges.size(), 4);
    EXPECT_TRUE(matches.faces.empty());
}

// CC1 and CC2 together: a box moved by its own width keeps only what stays at its place (the
// shared side's corners and edges); the shared side faces the other way, and the far corners
// would be the near ones turned
TEST(TopoShapeMatch, boxMovedByItsOwnWidthKeepsOnlyTheSharedPlaces)
{
    const TopoDS_Shape after = box(10);
    const auto matches = Part::matchElements(box(0), after, false);
    EXPECT_TRUE(matches.faces.empty());
    ASSERT_EQ(matches.vertexes.size(), 4);
    for (const auto& [now, old] : matches.vertexes) {
        EXPECT_NEAR(pointOf(after, now).X(), 10, tolerance);
    }
    EXPECT_EQ(matches.edges.size(), 4);
}

// Rung 4: an end face of a prism given more sides overlaps the old one at both inner points;
// the sides are new
TEST(TopoShapeMatch, prismWithMoreSidesKeepsItsEndFaces)
{
    const TopoDS_Shape before = prism(6);
    const TopoDS_Shape after = prism(8);
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_FALSE(matches.byIndex);
    ASSERT_EQ(matches.faces.size(), 2);
    EXPECT_EQ(matches.faces.at(planarFace(after, gp_Dir(0, 0, 1), 10)), planarFace(before, gp_Dir(0, 0, 1), 10));
    EXPECT_EQ(matches.faces.at(planarFace(after, gp_Dir(0, 0, -1), 0)), planarFace(before, gp_Dir(0, 0, -1), 0));
    // the corners at 0 and 180 degrees, and the side edges between them
    EXPECT_EQ(matches.vertexes.size(), 4);
    EXPECT_EQ(matches.edges.size(), 2);
}

// Rung 6 refuses a change of counts: the fixed order falls back to the other rungs
TEST(TopoShapeMatch, fixedOrderFallsBackWhenTheCountsChange)
{
    const auto matches = Part::matchElements(prism(6), prism(8), true);
    EXPECT_FALSE(matches.byIndex);
    EXPECT_EQ(matches.faces.size(), 2);
}

// Rung 6's side term: a cone whose apex changes end has the same counts and incidences, but its
// base faces the other way; nothing else holds, so nothing keeps its id
TEST(TopoShapeMatch, fixedOrderRefusesAConeWhoseApexChangesEnd)
{
    const TopoDS_Shape before = BRepPrimAPI_MakeCone(5, 0, 10).Shape();
    const TopoDS_Shape after = BRepPrimAPI_MakeCone(0, 5, 10).Shape();
    const auto matches = Part::matchElements(before, after, true);
    EXPECT_FALSE(matches.byIndex);
    EXPECT_TRUE(matches.faces.empty());
    EXPECT_TRUE(matches.edges.empty());
}

// Rungs 4 and 5: a cylinder made partial keeps its ends, its side and its rims (an arc of the old
// circle)
TEST(TopoShapeMatch, cylinderMadePartialKeepsItsEndsAndRims)
{
    const TopoDS_Shape before = BRepPrimAPI_MakeCylinder(5, 10).Shape();
    const TopoDS_Shape after = BRepPrimAPI_MakeCylinder(5, 10, 1.5 * pi).Shape();
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_EQ(matches.faces.at(planarFace(after, gp_Dir(0, 0, 1), 10)), planarFace(before, gp_Dir(0, 0, 1), 10));
    EXPECT_EQ(matches.faces.at(planarFace(after, gp_Dir(0, 0, -1), 0)), planarFace(before, gp_Dir(0, 0, -1), 0));
    EXPECT_EQ(
        matches.faces.at(faceOfKind(after, GeomAbs_Cylinder)),
        faceOfKind(before, GeomAbs_Cylinder)
    );
    // the rims: the arcs' midpoints at 135 degrees, the old circles' at 180
    const double c = 5 * std::cos(0.75 * pi);
    const double s = 5 * std::sin(0.75 * pi);
    EXPECT_EQ(matches.edges.at(edgeThrough(after, gp_Pnt(c, s, 10))), edgeThrough(before, gp_Pnt(-5, 0, 10)));
    EXPECT_EQ(matches.edges.at(edgeThrough(after, gp_Pnt(c, s, 0))), edgeThrough(before, gp_Pnt(-5, 0, 0)));
}

// One to one: a face split in two keeps neither piece
TEST(TopoShapeMatch, splitFaceKeepsNeitherPiece)
{
    const auto matches = Part::matchElements(square(0, 10), compound({square(0, 5), square(5, 10)}), false);
    EXPECT_TRUE(matches.faces.empty());
}

// Rung 4's anchor: congruent copies slid along a row overlap one another, but nothing links the
// old pieces to the new
TEST(TopoShapeMatch, slidCopiesWithoutAnAnchorTakeFreshIds)
{
    const auto matches = Part::matchElements(compound({box(0), box(20)}), compound({box(5), box(25)}), false);
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
    EXPECT_TRUE(matches.faces.empty());
}

// The first result of an object takes ids in index order: vertices, edges, faces
TEST(TopoShapeMatch, firstResultTakesIdsInIndexOrder)
{
    Part::TopoShape shape(box(0));
    long counter = 0;
    Part::nameByMatch(shape, Part::TopoShape(), 7, counter, false);
    EXPECT_EQ(shape.Tag, 7);
    EXPECT_EQ(Part::matchedId(shape, "Vertex1"), 1);
    EXPECT_EQ(Part::matchedId(shape, "Vertex8"), 8);
    EXPECT_EQ(Part::matchedId(shape, "Edge1"), 9);
    EXPECT_EQ(Part::matchedId(shape, "Face1"), 21);
    EXPECT_EQ(Part::matchedId(shape, "Face6"), 26);
    EXPECT_EQ(counter, 27);
    // one section, the MLN op code, no IDX flag: identity evidence like any other name
    const std::string name =
        shape.getMappedName(Data::IndexedName::fromConst("Face", 1)).toString();
    EXPECT_NE(name.find(";MLN;"), std::string::npos) << name;
    EXPECT_EQ(name.find("IDX"), std::string::npos) << name;
}

// A matched element keeps its id, and the counter gives none
TEST(TopoShapeMatch, matchedElementsKeepTheirIds)
{
    Part::TopoShape before(box(0));
    long counter = 0;
    Part::nameByMatch(before, Part::TopoShape(), 7, counter, false);
    const TopoDS_Shape taller = box(0, 20);
    Part::TopoShape after(taller);
    Part::nameByMatch(after, before, 7, counter, false);
    EXPECT_EQ(counter, 27);
    const std::string top = "Face" + std::to_string(planarFace(taller, gp_Dir(0, 0, 1), 20));
    const std::string oldTop = "Face" + std::to_string(planarFace(box(0), gp_Dir(0, 0, 1), 10));
    EXPECT_EQ(Part::matchedId(after, top.c_str()), Part::matchedId(before, oldTop.c_str()));
}

// An element that matches nothing takes a fresh id; an id is never given twice
TEST(TopoShapeMatch, freshIdsAreNeverReused)
{
    Part::TopoShape before(box(0));
    long counter = 0;
    Part::nameByMatch(before, Part::TopoShape(), 7, counter, false);
    Part::TopoShape after(box(100));
    Part::nameByMatch(after, before, 7, counter, false);
    EXPECT_EQ(Part::matchedId(after, "Vertex1"), 27);
    EXPECT_EQ(Part::matchedId(after, "Face6"), 52);
    EXPECT_EQ(counter, 53);
}

// The counter rises past every id of the previous result, whatever counter it is given
TEST(TopoShapeMatch, counterRisesPastThePreviousIds)
{
    Part::TopoShape before(box(0));
    long counter = 100;
    Part::nameByMatch(before, Part::TopoShape(), 7, counter, false);
    EXPECT_EQ(Part::matchedId(before, "Vertex1"), 100);
    long other = 0;
    Part::TopoShape after(box(100));
    Part::nameByMatch(after, before, 7, other, false);
    EXPECT_EQ(Part::matchedId(after, "Vertex1"), 126);
    EXPECT_EQ(other, 152);
}

class TopoShapeMatchDocument: public ::testing::Test
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
        ASSERT_EQ(_doc->getSelectedHistoryAlgorithm(), App::HistoryAlgorithm::V2);
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    App::Document* _doc = nullptr;
    std::string _docName;
};

// The hook: a feature's shape without a map is named by a match against the value it replaces
TEST_F(TopoShapeMatchDocument, featureShapeIsNamedByMatch)
{
    auto feature = _doc->addObject<Part::Feature>("Thing");
    feature->Shape.setValue(Part::TopoShape(box(0)));
    const Part::TopoShape first = feature->Shape.getShape();
    EXPECT_EQ(first.Tag, feature->getID());
    EXPECT_EQ(Part::matchedId(first, "Face1"), 21);
    // the TopoDS_Shape overload reaches the hook too
    const TopoDS_Shape taller = box(0, 20);
    feature->Shape.setValue(taller);
    const std::string top = "Face" + std::to_string(planarFace(taller, gp_Dir(0, 0, 1), 20));
    const std::string oldTop = "Face" + std::to_string(planarFace(box(0), gp_Dir(0, 0, 1), 10));
    const long topId = Part::matchedId(first, oldTop.c_str());
    EXPECT_GT(topId, 0);
    EXPECT_EQ(Part::matchedId(feature->Shape.getShape(), top.c_str()), topId);
    EXPECT_EQ(feature->Shape.getNextElementId(), 27);
}

// A primitive whose face count changes keeps its end faces (ops#502's find: a sketch on a Prism's
// top moved to a side)
TEST_F(TopoShapeMatchDocument, prismGivenMoreSidesKeepsItsEndFaces)
{
    auto prism = _doc->addObject<Part::Prism>("Prism");
    prism->Polygon.setValue(6);
    prism->Circumradius.setValue(10);
    prism->Height.setValue(10);
    _doc->recompute();
    const Part::TopoShape before = prism->Shape.getShape();
    const std::string top = "Face" + std::to_string(planarFace(before.getShape(), gp_Dir(0, 0, 1), 10));
    const std::string bottom = "Face" + std::to_string(planarFace(before.getShape(), gp_Dir(0, 0, -1), 0));
    const long topId = Part::matchedId(before, top.c_str());
    const long bottomId = Part::matchedId(before, bottom.c_str());
    ASSERT_GT(topId, 0);
    ASSERT_GT(bottomId, 0);
    prism->Polygon.setValue(8);
    _doc->recompute();
    const Part::TopoShape after = prism->Shape.getShape();
    const std::string newTop = "Face" + std::to_string(planarFace(after.getShape(), gp_Dir(0, 0, 1), 10));
    const std::string newBottom =
        "Face" + std::to_string(planarFace(after.getShape(), gp_Dir(0, 0, -1), 0));
    EXPECT_EQ(Part::matchedId(after, newTop.c_str()), topId);
    EXPECT_EQ(Part::matchedId(after, newBottom.c_str()), bottomId);
    // the sides are new: none has an id the six sides had
    const long before6 = before.countSubShapes(TopAbs_FACE);
    for (int i = 1; i <= static_cast<int>(after.countSubShapes(TopAbs_FACE)); ++i) {
        const std::string face = "Face" + std::to_string(i);
        if (face == newTop || face == newBottom) {
            continue;
        }
        const long id = Part::matchedId(after, face.c_str());
        for (int j = 1; j <= before6; ++j) {
            EXPECT_NE(id, Part::matchedId(before, ("Face" + std::to_string(j)).c_str()));
        }
    }
}

// The counter only grows, across undo too (CC3): an id given in an undone step is never given
// again
TEST_F(TopoShapeMatchDocument, counterGrowsAcrossUndo)
{
    auto feature = _doc->addObject<Part::Feature>("Thing");
    _doc->openTransaction("first");
    feature->Shape.setValue(Part::TopoShape(box(0)));
    _doc->commitTransaction();
    _doc->openTransaction("second");
    feature->Shape.setValue(Part::TopoShape(box(100)));
    _doc->commitTransaction();
    EXPECT_EQ(Part::matchedId(feature->Shape.getShape(), "Face6"), 52);
    ASSERT_TRUE(_doc->undo());
    EXPECT_EQ(Part::matchedId(feature->Shape.getShape(), "Face6"), 26);
    EXPECT_EQ(feature->Shape.getNextElementId(), 53);
    _doc->openTransaction("third");
    feature->Shape.setValue(Part::TopoShape(box(200)));
    _doc->commitTransaction();
    EXPECT_EQ(Part::matchedId(feature->Shape.getShape(), "Vertex1"), 53);
}

// Copy and Paste carry the counter, and Paste keeps the larger one
TEST_F(TopoShapeMatchDocument, pasteKeepsTheLargerCounter)
{
    auto first = _doc->addObject<Part::Feature>("First");
    auto second = _doc->addObject<Part::Feature>("Second");
    first->Shape.setValue(Part::TopoShape(box(0)));
    second->Shape.setValue(Part::TopoShape(box(0)));
    second->Shape.setValue(Part::TopoShape(box(100)));
    ASSERT_EQ(first->Shape.getNextElementId(), 27);
    ASSERT_EQ(second->Shape.getNextElementId(), 53);
    std::unique_ptr<App::Property> copy(second->Shape.Copy());
    first->Shape.Paste(*copy);
    EXPECT_EQ(first->Shape.getNextElementId(), 53);
    std::unique_ptr<App::Property> older(first->Shape.Copy());
    second->Shape.Paste(*older);
    EXPECT_EQ(second->Shape.getNextElementId(), 53);
}
