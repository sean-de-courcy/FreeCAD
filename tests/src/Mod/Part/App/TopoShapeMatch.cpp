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
#include <BRepAlgoAPI_Cut.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <GProp_GProps.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
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

// Rung 2's direction term (CC1): a point moved across its neighbour is not the same point. Then
// R1 (ruling 10-28): the edge left at its place has no matched edge beside it, so nothing confirms
// it, and the wire is new
TEST(TopoShapeMatch, pointMovedAcrossItsNeighbourTakesAFreshId)
{
    const auto before = polyline({gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0), gp_Pnt(10, 10, 0)});
    const auto after = polyline({gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0), gp_Pnt(10, -10, 0)});
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_FALSE(matches.vertexes.count(vertexAt(after, gp_Pnt(10, -10, 0))));
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
}

// R1 in a wire: a moved end keeps the wire, each edge beside a matched one
TEST(TopoShapeMatch, wireWithAMovedEndKeepsItsOtherEdges)
{
    const auto before = polyline({gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0), gp_Pnt(10, 10, 0), gp_Pnt(0, 10, 0)});
    const auto after = polyline({gp_Pnt(0, 0, 0), gp_Pnt(10, 0, 0), gp_Pnt(10, 10, 0), gp_Pnt(0, 30, 0)});
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_EQ(matches.edges.at(edgeThrough(after, gp_Pnt(5, 0, 0))), edgeThrough(before, gp_Pnt(5, 0, 0)));
    EXPECT_EQ(matches.edges.at(edgeThrough(after, gp_Pnt(10, 5, 0))), edgeThrough(before, gp_Pnt(10, 5, 0)));
    EXPECT_EQ(matches.vertexes.at(vertexAt(after, gp_Pnt(10, 10, 0))), vertexAt(before, gp_Pnt(10, 10, 0)));
}

// R1 in a wire: a closed square shifted by its own side leaves one edge at an old edge's place,
// with no matched edge beside it: every id is fresh
TEST(TopoShapeMatch, squareWireShiftedByItsSideTakesFreshIds)
{
    auto square = [](double x) {
        return polyline({gp_Pnt(x, 0, 0), gp_Pnt(x + 10, 0, 0), gp_Pnt(x + 10, 10, 0), gp_Pnt(x, 10, 0)}, true);
    };
    const auto matches = Part::matchElements(square(0), square(10), false);
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
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

// Every face rung's side term (CC2): a face at its place facing the other way is another face;
// then R1 (ruling 10-28): its corners and edges at their places have no matched face to confirm
// them, so they are new too
TEST(TopoShapeMatch, reversedFaceTakesAFreshId)
{
    const TopoDS_Face before = square(0, 10);
    const auto matches = Part::matchElements(before, before.Reversed(), false);
    EXPECT_TRUE(matches.faces.empty());
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
}

// The seam (ruling 10-28, R1): a box moved by its own width leaves the shared side's corners and
// edges at old places, but the side faces the other way (CC2) and the far corners would be the
// near ones turned (CC1): no face matches, so nothing confirms the seam, and every id is fresh
TEST(TopoShapeMatch, boxMovedByItsOwnWidthTakesFreshIds)
{
    const auto matches = Part::matchElements(box(0), box(10), false);
    EXPECT_TRUE(matches.faces.empty());
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
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

// P1 (ruling 10-28): twins traded in the producer's order are the same shapes as twins reordered;
// neither reading is verified, so the class takes fresh ids
TEST(TopoShapeMatch, tradedTwinsTakeFreshIds)
{
    const auto matches =
        Part::matchElements(compound({box(0), box(20)}), compound({box(20), box(0)}), false);
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
    EXPECT_TRUE(matches.faces.empty());
}

// P1: twins slid by their pitch: the first lands on the second's place
TEST(TopoShapeMatch, twinsSlidByTheirPitchTakeFreshIds)
{
    const auto matches =
        Part::matchElements(compound({box(0), box(20)}), compound({box(20), box(40)}), false);
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
    EXPECT_TRUE(matches.faces.empty());
}

// P1: touching twins are separate pieces, because the producer made them so
TEST(TopoShapeMatch, touchingTwinsTradedTakeFreshIds)
{
    const auto matches =
        Part::matchElements(compound({box(0), box(10)}), compound({box(10), box(0)}), false);
    EXPECT_TRUE(matches.faces.empty());
    EXPECT_TRUE(matches.edges.empty());
}

// P1 doesn't fire on a count change: a copy inserted first leaves the others at their places
TEST(TopoShapeMatch, copyInsertedFirstKeepsTheOthers)
{
    const TopoDS_Shape before = compound({box(0), box(20)});
    const TopoDS_Shape after = compound({box(40), box(0), box(20)});
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_EQ(matches.faces.size(), 12);
    EXPECT_EQ(matches.edges.size(), 24);
    EXPECT_EQ(matches.vertexes.size(), 16);
    EXPECT_FALSE(matches.vertexes.count(vertexAt(after, gp_Pnt(50, 10, 10))));
}

// P1 doesn't fire on pieces that aren't congruent: reordered, each keeps its ids by place
TEST(TopoShapeMatch, reorderedPiecesThatDifferKeepTheirIds)
{
    const TopoDS_Shape before = compound({box(0), box(20, 20)});
    const TopoDS_Shape after = compound({box(20, 20), box(0)});
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_EQ(matches.faces.size(), 12);
    EXPECT_EQ(matches.edges.size(), 24);
    EXPECT_EQ(matches.vertexes.size(), 16);
    EXPECT_EQ(matches.vertexes.at(vertexAt(after, gp_Pnt(30, 10, 20))), vertexAt(before, gp_Pnt(30, 10, 20)));
}

// P1 doesn't fire on a twin moved to a free place: the other keeps its ids
TEST(TopoShapeMatch, twinMovedToAFreePlaceLeavesTheOther)
{
    const TopoDS_Shape after = compound({box(0), box(50)});
    const auto matches = Part::matchElements(compound({box(0), box(20)}), after, false);
    EXPECT_EQ(matches.faces.size(), 6);
    EXPECT_EQ(matches.vertexes.at(vertexAt(after, gp_Pnt(10, 10, 10))), vertexAt(compound({box(0), box(20)}), gp_Pnt(10, 10, 10)));
}

// P1 (decision 188): a near-twin 0.5 µm taller is no twin. Twins traded with the near-twin deleted
// are a permutation of the twins' class; taken into it, the near-twin would unbalance its counts
TEST(TopoShapeMatch, twinsTradedNearTwinDroppedTakeFreshIds)
{
    const auto matches = Part::matchElements(
        compound({box(0), box(20), box(40, 10.0005)}),
        compound({box(20), box(0)}),
        false
    );
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
    EXPECT_TRUE(matches.faces.empty());
}

// P1's generous classes (the review's T3) test the places as generously: a near-pair 0.5 µm apart
// traded sits at no partner's place by the strict test (the fix review's T1)
TEST(TopoShapeMatch, nearPairTradedTakesFreshIds)
{
    const auto matches = Part::matchElements(
        compound({box(0), box(20, 10.0005)}),
        compound({box(20), box(0, 10.0005)}),
        false
    );
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
    EXPECT_TRUE(matches.faces.empty());
}

namespace
{

// A board 60 x 10 x 5 ripped along its diagonal: the wedge below the diagonal, or above it
TopoDS_Shape wedge(bool below)
{
    const TopoDS_Wire outline = below
        ? polyline({gp_Pnt(0, 0, 0), gp_Pnt(60, 0, 0), gp_Pnt(60, 10, 0)}, true)
        : polyline({gp_Pnt(0, 0, 0), gp_Pnt(60, 10, 0), gp_Pnt(0, 10, 0)}, true);
    return BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(outline).Face(), gp_Vec(0, 0, 5)).Shape();
}

// The shape turned half a turn about the board's vertical axis: each wedge onto the other's place
TopoDS_Shape halfTurned(const TopoDS_Shape& shape)
{
    gp_Trsf turn;
    turn.SetRotation(gp_Ax1(gp_Pnt(30, 5, 0), gp_Dir(0, 0, 1)), pi);
    return BRepBuilderAPI_Transform(shape, turn, true).Shape();
}

}  // namespace

// P1: twin wedges share the board's box, so by their boxes both sit at every old place; turned
// half a turn, each old wedge's matched elements went to the other (the fix review's T3)
TEST(TopoShapeMatch, wedgeTwinsTurnedTakeFreshIds)
{
    const auto matches = Part::matchElements(
        compound({wedge(true), wedge(false)}),
        compound({halfTurned(wedge(true)), halfTurned(wedge(false))}),
        false
    );
    EXPECT_TRUE(matches.vertexes.empty());
    EXPECT_TRUE(matches.edges.empty());
    EXPECT_TRUE(matches.faces.empty());
}

namespace
{

// A comb in the XY plane, 2 deep: a base 2 high (or  base) from  x to  x + 12 and three
// teeth 2 wide (or  width, from their left sides), up to y = 7, at a pitch of 4, their left
// sides 1 in from the base's left end
TopoDS_Shape comb(double x, double width = 2, double base = 2)
{
    std::vector<gp_Pnt> points {gp_Pnt(x, 0, 0), gp_Pnt(x + 12, 0, 0), gp_Pnt(x + 12, base, 0)};
    for (int tooth = 2; tooth >= 0; --tooth) {
        const double left = x + 1 + 4 * tooth;
        points.insert(
            points.end(),
            {gp_Pnt(left + width, base, 0),
             gp_Pnt(left + width, 7, 0),
             gp_Pnt(left, 7, 0),
             gp_Pnt(left, base, 0)}
        );
    }
    points.emplace_back(x, base, 0);
    const TopoDS_Face profile = BRepBuilderAPI_MakeFace(polyline(points, true)).Face();
    return BRepPrimAPI_MakePrism(profile, gp_Vec(0, 0, 2)).Shape();
}

// A square-wave wire of \a periods periods of 4 from \a x: up 2 at x + 2, down at x + 4, ...
TopoDS_Wire squareWave(double x, int periods)
{
    std::vector<gp_Pnt> points {gp_Pnt(x, 0, 0)};
    for (int p = 0; p < periods; ++p) {
        const double left = x + 4 * p;
        points.insert(
            points.end(),
            {gp_Pnt(left + 2, 0, 0), gp_Pnt(left + 2, 2, 0), gp_Pnt(left + 4, 2, 0), gp_Pnt(left + 4, 0, 0)}
        );
    }
    points.emplace_back(x + 4 * periods + 2, 0, 0);
    return polyline(points);
}

}  // namespace

// R2' (decision 169): a periodic piece slid by its pitch puts each tooth on the next tooth's old
// place, every match verified; the piece moved as a whole (congruent, its box elsewhere), so it
// takes fresh ids
TEST(TopoShapeMatch, combSlidByItsPitchTakesFreshIds)
{
    const auto matches = Part::matchElements(comb(0), comb(4), false);
    EXPECT_TRUE(matches.faces.empty());
    EXPECT_TRUE(matches.edges.empty());
    EXPECT_TRUE(matches.vertexes.empty());
}

// Decision 174's risk case: the comb slid by its pitch, its teeth narrowed from their left
// sides and its base thinned. Nothing is where it was but the teeth's top left corners, each at
// the next tooth's old corner (seams), and each tooth top overlaps the next tooth's old top
// alone (rung 4). The front and back faces (rung 4 too) confirm the seams: left out one at a
// time, the tops would anchor one another and keep the neighbouring tooth's ids. The tops have
// twins on their plane, so their anchor must hold without any rung-4 face: none keeps the id
// of the old top at its place
TEST(TopoShapeMatch, combTeethSlidAndNarrowedKeepNoNeighboursTop)
{
    const TopoDS_Shape before = comb(0);
    const TopoDS_Shape after = comb(4, 1.8, 1.5);
    auto faceCentredAt = [](const TopoDS_Shape& shape, const gp_Pnt& point) {
        const auto map = elements(shape, TopAbs_FACE);
        for (int i = 1; i <= map.Extent(); ++i) {
            if (centreOf(map(i)).Distance(point) < 1e-6) {
                return i;
            }
        }
        return 0;
    };
    const auto matches = Part::matchElements(before, after, false);
    for (const double left : {5.0, 9.0}) {
        const int top = faceCentredAt(after, gp_Pnt(left + 0.9, 7, 1));
        const int oldTop = faceCentredAt(before, gp_Pnt(left + 1, 7, 1));
        ASSERT_NE(top, 0);
        ASSERT_NE(oldTop, 0);
        const auto it = matches.faces.find(top);
        EXPECT_FALSE(it != matches.faces.end() && it->second == oldTop) << left;
    }
}

TEST(TopoShapeMatch, squareWaveSlidByItsPeriodTakesFreshIds)
{
    const auto matches = Part::matchElements(squareWave(0, 3), squareWave(4, 3), false);
    EXPECT_TRUE(matches.edges.empty());
    EXPECT_TRUE(matches.vertexes.empty());
}

// R2 against a split: a loose shell's second plate becomes two. The matcher reads the far piece as
// the plate with its near side moved (rung 2 on the corners, rung 3) and the near piece as new;
// R2 doesn't fire (the unmatched elements differ), so the first plate keeps its id
TEST(TopoShapeMatch, shellWithASplitPlateKeepsTheOtherPlates)
{
    const TopoDS_Shape before = compound({square(0, 10), square(10, 30)});
    const TopoDS_Shape after = compound({square(0, 10), square(10, 18), square(18, 30)});
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_EQ(matches.faces.size(), 2);
    EXPECT_EQ(matches.faces.at(1), 1);
}

// R2' leaves a piece that stayed alone: a hole moved in a script plate is a new hole, and the
// plate keeps its faces (the ruling's 2b retired the whole plate here)
TEST(TopoShapeMatch, plateWithAMovedHoleKeepsItsFaces)
{
    auto plate = [](double hole) {
        const TopoDS_Shape block = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 40, 20, 2).Shape();
        const TopoDS_Shape pin = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(hole, 10, -1), gp_Dir(0, 0, 1)), 3, 4).Shape();
        return BRepAlgoAPI_Cut(block, pin).Shape();
    };
    const TopoDS_Shape before = plate(10);
    const TopoDS_Shape after = plate(25);
    const auto matches = Part::matchElements(before, after, false);
    EXPECT_EQ(matches.faces.at(planarFace(after, gp_Dir(1, 0, 0), 40)), planarFace(before, gp_Dir(1, 0, 0), 40));
    EXPECT_EQ(matches.faces.at(planarFace(after, gp_Dir(0, 0, 1), 2)), planarFace(before, gp_Dir(0, 0, 1), 2));
    EXPECT_FALSE(matches.faces.count(faceOfKind(after, GeomAbs_Cylinder)));
}

// The names nameByMatch() gives need the application's types (a filtered run starts here)
class TopoShapeMatchNames: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
};

// The first result of an object takes ids in index order: vertices, edges, faces
TEST_F(TopoShapeMatchNames, firstResultTakesIdsInIndexOrder)
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
    const auto names =
        shape.getElementMappedNames(Data::IndexedName("Face1", shape.getElementTypes()));
    ASSERT_EQ(names.size(), 1);
    const std::string name = names.front().first.toString();
    EXPECT_NE(name.find(";MLN;"), std::string::npos) << name;
    EXPECT_EQ(name.find("IDX"), std::string::npos) << name;
}

// A matched element keeps its id, and the counter gives none
TEST_F(TopoShapeMatchNames, matchedElementsKeepTheirIds)
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
TEST_F(TopoShapeMatchNames, freshIdsAreNeverReused)
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
TEST_F(TopoShapeMatchNames, counterRisesPastThePreviousIds)
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

// A result with no elements (a Common of shapes that don't touch: an empty compound) has nothing
// to name: it is set as it is (the hook once called itself on it until the stack ran out)
TEST_F(TopoShapeMatchDocument, emptyResultIsSetWithoutNames)
{
    auto feature = _doc->addObject<Part::Feature>("Thing");
    feature->Shape.setValue(Part::TopoShape(box(0)));
    BRep_Builder builder;
    TopoDS_Compound empty;
    builder.MakeCompound(empty);
    feature->Shape.setValue(Part::TopoShape(empty));
    EXPECT_FALSE(feature->Shape.getShape().isNull());
    EXPECT_EQ(feature->Shape.getShape().getElementMapSize(), 0U);
    EXPECT_EQ(feature->Shape.getNextElementId(), 27);
    // and a later result is still named past the earlier ids
    feature->Shape.setValue(Part::TopoShape(box(0)));
    EXPECT_EQ(Part::matchedId(feature->Shape.getShape(), "Vertex1"), 27);
}

// The ruling's A4: after an empty result (a bad input), a rebuilt one takes ids from the saved
// counter, never from 1, across a save and a reopen too
TEST_F(TopoShapeMatchDocument, idsAfterAnEmptyResultComeFromTheSavedCounter)
{
    auto feature = _doc->addObject<Part::Feature>("Thing");
    feature->Shape.setValue(Part::TopoShape(box(0)));
    BRep_Builder builder;
    TopoDS_Compound empty;
    builder.MakeCompound(empty);
    feature->Shape.setValue(Part::TopoShape(empty));
    const std::string path = App::Application::getTempFileName("counter") + ".FCStd";
    ASSERT_TRUE(_doc->saveAs(path.c_str()));
    App::GetApplication().closeDocument(_docName.c_str());
    _doc = App::GetApplication().openDocument(path.c_str());
    ASSERT_NE(_doc, nullptr);
    _docName = _doc->getName();
    auto restored = freecad_cast<Part::Feature*>(_doc->getObject("Thing"));
    ASSERT_NE(restored, nullptr);
    EXPECT_EQ(restored->Shape.getNextElementId(), 27);
    restored->Shape.setValue(Part::TopoShape(box(0)));
    EXPECT_EQ(Part::matchedId(restored->Shape.getShape(), "Vertex1"), 27);
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
