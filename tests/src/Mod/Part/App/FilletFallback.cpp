// SPDX-License-Identifier: LGPL-2.1-or-later

// The exact construction of the fillets and chamfers OCCT refuses (ops#300; design:
// notes/fillet-workarounds.md in the ops repository). Designed models only; every expectation is
// the analytic volume, or OCCT's own result where OCCT works.

#include <algorithm>
#include <cmath>
#include <functional>
#include <numbers>
#include <sstream>
#include <gtest/gtest.h>

#include "src/App/InitApplication.h"
#include <App/ElementNamingUtils.h>
#include <Mod/Part/App/FilletFallback.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRep_Tool.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GProp_GProps.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <StdFail_NotDone.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pln.hxx>

// NOLINTBEGIN(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)

using namespace Part;
namespace FF = Part::FilletFallback;

namespace
{

constexpr double pi = std::numbers::pi;

/// The section of a 90 degree fillet, and its centroid's distance from each face
double filletSection(double r)
{
    return r * r * (1 - pi / 4);
}

double filletCentroid(double r)
{
    return r * (10 - 3 * pi) / (12 - 3 * pi);
}

/// The fillet section at a dihedral angle alpha (between the faces, through the material)
double filletSection(double r, double alpha)
{
    return r * r * (1 / std::tan(alpha / 2) - (pi - alpha) / 2);
}

double volume(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape, props);
    return props.Mass();
}

int count(const TopoDS_Shape& shape, TopAbs_ShapeEnum type)
{
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, type, map);
    return map.Extent();
}

TopoDS_Shape box(double x, double y, double z, gp_Pnt at = gp_Pnt())
{
    return BRepPrimAPI_MakeBox(at, x, y, z).Shape();
}

/// A box filling the side of the plane the normal points to (within size of the point)
TopoDS_Shape beyondPlane(const gp_Pnt& point, const gp_Dir& normal, double size)
{
    gp_Ax2 frame(point, normal);
    gp_Vec diagonal = gp_Vec(frame.XDirection()) + gp_Vec(frame.YDirection());
    gp_Ax2 corner(point.Translated(diagonal * -size), normal, frame.XDirection());
    return BRepPrimAPI_MakeBox(corner, 2 * size, 2 * size, size).Shape();
}

/// A prism of the polygon (in the plane x = 0, points as (y, z)) along x
TopoDS_Shape profileAlongX(const std::vector<std::pair<double, double>>& yz, double length)
{
    BRepBuilderAPI_MakePolygon polygon;
    for (auto [y, z] : yz) {
        polygon.Add(gp_Pnt(0, y, z));
    }
    polygon.Close();
    TopoDS_Face face = BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
    return BRepPrimAPI_MakePrism(face, gp_Vec(length, 0, 0)).Shape();
}

/// A step: a block 30 x 20 x 10 with a block 30 x 10 x 4 on its back half; the riser at y = 10
/// has its concave edge at z = 10 and its convex edge at z = 14
TopoDS_Shape step()
{
    return profileAlongX({{0, 0}, {20, 0}, {20, 14}, {10, 14}, {10, 10}, {0, 10}}, 30);
}

/// A tube: radii 10 and 6, height 10
TopoDS_Shape tube()
{
    BRepAlgoAPI_Cut cut(
        BRepPrimAPI_MakeCylinder(10, 10).Shape(),
        BRepPrimAPI_MakeCylinder(6, 10).Shape()
    );
    return cut.Shape();
}

/// A stadium plate: straight sides 20 long, width 4, height 3, half circles of radius 2 at
/// x = 0 and x = 20
TopoDS_Shape stadium()
{
    gp_Pnt a(0, 0, 0), b(20, 0, 0), c(20, 4, 0), d(0, 4, 0);
    BRepBuilderAPI_MakeWire wire;
    wire.Add(BRepBuilderAPI_MakeEdge(a, b).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(b, gp_Pnt(22, 2, 0), c).Value()).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(c, d).Edge());
    wire.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(d, gp_Pnt(-2, 2, 0), a).Value()).Edge());
    TopoDS_Face face = BRepBuilderAPI_MakeFace(wire.Wire(), Standard_True).Face();
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, 3)).Shape();
}

/// A wall 30 x 10 x 20 (y from -10 to 0) with a rib 4 wide, 20 long and 4 high on its front,
/// x from 13 to 17
TopoDS_Shape ribAgainstWall()
{
    BRepAlgoAPI_Fuse fuse(box(30, 10, 20, gp_Pnt(0, -10, 0)), box(4, 20, 4, gp_Pnt(13, 0, 0)));
    ShapeUpgrade_UnifySameDomain unify(fuse.Shape());
    unify.Build();
    return unify.Shape();
}

/// The box 30 x 4 x 20 on a lower block x in [-5, 0], z up to 17: the end face of the top edges
/// at x = 0 covers z from 17 to 20 only
TopoDS_Shape boxOnALowerBlock()
{
    BRepAlgoAPI_Fuse fuse(box(30, 4, 20), box(5, 4, 17, gp_Pnt(-5, 0, 0)));
    ShapeUpgrade_UnifySameDomain unify(fuse.Shape());
    unify.Build();
    return unify.Shape();
}

/// A plate 20 high whose top is 4 wide at x = 0, the front y = 0 up to x = 30, then the front
/// bending by the angle towards the back, which it meets at x = 30 + 4 / tan(angle)
TopoDS_Shape bentFront(double angle)
{
    double tip = 30 + 4 / std::tan(angle);
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(0, 0, 0),
        gp_Pnt(30, 0, 0),
        gp_Pnt(tip, 4, 0),
        gp_Pnt(0, 4, 0),
        Standard_True
    );
    TopoDS_Face face = BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, 20)).Shape();
}

/// The edge of the shape between the two points
TopoShape edgeBetween(const TopoShape& shape, gp_Pnt p, gp_Pnt q)
{
    for (const auto& edge : shape.getSubTopoShapes(TopAbs_EDGE)) {
        TopoDS_Vertex v1, v2;
        TopExp::Vertices(TopoDS::Edge(edge.getShape()), v1, v2);
        gp_Pnt a = BRep_Tool::Pnt(v1);
        gp_Pnt b = BRep_Tool::Pnt(v2);
        if ((a.Distance(p) < 1e-7 && b.Distance(q) < 1e-7)
            || (a.Distance(q) < 1e-7 && b.Distance(p) < 1e-7)) {
            return edge;
        }
    }
    ADD_FAILURE() << "no edge between the points";
    return {};
}

/// The edges of the shape whose every vertex passes the test
std::vector<TopoShape> edgesWhere(
    const TopoShape& shape,
    const std::function<bool(const gp_Pnt&)>& test,
    bool circlesOnly = false
)
{
    std::vector<TopoShape> result;
    for (const auto& edge : shape.getSubTopoShapes(TopAbs_EDGE)) {
        BRepAdaptor_Curve curve(TopoDS::Edge(edge.getShape()));
        if (circlesOnly && curve.GetType() != GeomAbs_Circle) {
            continue;
        }
        bool all = true;
        for (TopExp_Explorer it(edge.getShape(), TopAbs_VERTEX); it.More(); it.Next()) {
            all = all && test(BRep_Tool::Pnt(TopoDS::Vertex(it.Current())));
        }
        if (all) {
            result.push_back(edge);
        }
    }
    return result;
}

/// The edges' test: the point at this height
std::function<bool(const gp_Pnt&)> atHeight(double z)
{
    return [z](const gp_Pnt& p) {
        return std::abs(p.Z() - z) < 1e-7;
    };
}

TopoDS_Shape subShape(const TopoShape& shape, const char* type, int index)
{
    return shape.getSubShape(Data::IndexedName(type, index).toString().c_str());
}

GeomAbs_SurfaceType surfaceType(const TopoDS_Shape& face)
{
    return BRepAdaptor_Surface(TopoDS::Face(face)).GetType();
}

bool hasZeroAreaFace(const TopoDS_Shape& shape)
{
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        GProp_GProps props;
        BRepGProp::SurfaceProperties(it.Current(), props);
        if (props.Mass() < 1e-7) {
            return true;
        }
    }
    return false;
}

/// A valid single solid with no zero-area face and the expected volume
testing::AssertionResult exact(const TopoShape& result, double expected)
{
    const auto& shape = result.getShape();
    if (shape.IsNull()) {
        return testing::AssertionFailure() << "null result";
    }
    if (!BRepCheck_Analyzer(shape).IsValid()) {
        return testing::AssertionFailure() << "invalid result";
    }
    if (count(shape, TopAbs_SOLID) != 1) {
        return testing::AssertionFailure() << count(shape, TopAbs_SOLID) << " solids";
    }
    if (hasZeroAreaFace(shape)) {
        return testing::AssertionFailure() << "a zero-area face";
    }
    double v = volume(shape);
    if (std::abs(v - expected) > 1e-6 * expected) {
        return testing::AssertionFailure() << "volume " << v << ", expected " << expected;
    }
    return testing::AssertionSuccess();
}

bool occtFilletFails(
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    double r1,
    double r2
)
{
    BRepFilletAPI_MakeFillet maker(base.getShape());
    for (const auto& e : edges) {
        maker.Add(r1, r2, TopoDS::Edge(e.getShape()));
    }
    try {
        maker.Build();
    }
    catch (const Standard_Failure&) {
        return true;
    }
    return !maker.IsDone();
}

FF::Request fillet(double r)
{
    FF::Request request;
    request.kind = FF::Kind::Fillet;
    request.size1 = request.size2 = r;
    return request;
}

FF::Request chamfer(
    double d1,
    double d2 = 0.0,
    ChamferType type = ChamferType::equalDistance,
    Flip flip = Flip::none
)
{
    FF::Request request;
    request.kind = FF::Kind::Chamfer;
    request.size1 = d1;
    request.size2 = type == ChamferType::equalDistance ? d1 : d2;
    request.chamferType = type;
    request.flipDirection = flip;
    return request;
}

/// OCCT's own dress-up fails (fillets, and chamfers by distances)
bool occtFails(
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const FF::Request& request
)
{
    if (request.kind == FF::Kind::Fillet) {
        return occtFilletFails(base, edges, request.size1, request.size2);
    }
    BRepFilletAPI_MakeChamfer maker(base.getShape());
    for (const auto& e : edges) {
        const auto& edge = TopoDS::Edge(e.getShape());
        auto face = TopoDS::Face(base.findAncestorShape(edge, TopAbs_FACE));
        maker.Add(request.size1, request.size2, edge, face);
    }
    try {
        maker.Build();
    }
    catch (const Standard_Failure&) {
        return true;
    }
    return !maker.IsDone();
}

/// The dress-up as the public functions build it: OCCT, or the exact construction after it
TopoShape dressUp(
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const FF::Request& request
)
{
    TopoShape result(2L);
    if (request.kind == FF::Kind::Fillet) {
        result.makeElementFillet(base, edges, request.size1, request.size2);
    }
    else {
        result.makeElementChamfer(
            base,
            edges,
            request.chamferType,
            request.size1,
            request.size2,
            nullptr,
            request.flipDirection
        );
    }
    return result;
}

/// The exact construction, forced
TopoShape forced(
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const FF::Request& request,
    std::string* reason = nullptr
)
{
    TopoShape result(2L);
    std::string why;
    bool built = FF::build(
        result,
        base,
        edges,
        request,
        request.kind == FF::Kind::Fillet ? OpCodes::Fillet : OpCodes::Chamfer,
        &why
    );
    if (reason) {
        *reason = why;
    }
    else {
        EXPECT_TRUE(built) << why;
    }
    return built ? result : TopoShape();
}

gp_Pnt centreOf(const TopoDS_Shape& shape, double& measure)
{
    if (shape.ShapeType() == TopAbs_VERTEX) {
        measure = 0;
        return BRep_Tool::Pnt(TopoDS::Vertex(shape));
    }
    GProp_GProps props;
    if (shape.ShapeType() == TopAbs_EDGE) {
        BRepGProp::LinearProperties(shape, props);
    }
    else {
        BRepGProp::SurfaceProperties(shape, props);
    }
    measure = props.Mass();
    return props.CentreOfMass();
}

std::vector<std::string> sortedNames(const TopoShape& shape, const Data::IndexedName& element)
{
    std::vector<std::string> names;
    for (const auto& name : shape.getElementMappedNames(element)) {
        names.push_back(name.first.toString());
    }
    std::sort(names.begin(), names.end());
    return names;
}

/// The two results are the same solid with the same elements, named the same, element for element
/// (matched by position, to the precision of the integrated centres: the indices may differ)
testing::AssertionResult sameAs(const TopoShape& result, const TopoShape& reference)
{
    const auto& a = result.getShape();
    const auto& b = reference.getShape();
    if (a.IsNull() || b.IsNull()) {
        return testing::AssertionFailure() << "null shape";
    }
    double difference
        = volume(BRepAlgoAPI_Cut(a, b).Shape()) + volume(BRepAlgoAPI_Cut(b, a).Shape());
    if (difference > 1e-7 * volume(b)) {
        return testing::AssertionFailure() << "symmetric difference " << difference;
    }
    for (const char* type : {"Vertex", "Edge", "Face"}) {
        auto n = static_cast<int>(reference.countSubElements(type));
        if (static_cast<int>(result.countSubElements(type)) != n) {
            return testing::AssertionFailure() << type << " count " << result.countSubElements(type)
                                               << " != " << n;
        }
        for (int i = 1; i <= n; ++i) {
            Data::IndexedName element(type, i);
            double measure = 0;
            gp_Pnt centre = centreOf(subShape(reference, type, i), measure);
            int match = 0;
            for (int j = 1; j <= n; ++j) {
                double m = 0;
                gp_Pnt c = centreOf(subShape(result, type, j), m);
                double tolerance = 1e-5 * std::max(1.0, measure);
                if (c.Distance(centre) < 1e-5 && std::abs(m - measure) < tolerance) {
                    if (match != 0) {
                        return testing::AssertionFailure() << element.toString() << " is ambiguous";
                    }
                    match = j;
                }
            }
            if (match == 0) {
                std::ostringstream ss;
                ss << "no element at " << element.toString() << " (" << centre.X() << ", "
                   << centre.Y() << ", " << centre.Z() << "; " << measure << "); the other has";
                for (int j = 1; j <= n; ++j) {
                    double m = 0;
                    gp_Pnt c = centreOf(subShape(result, type, j), m);
                    ss << "\n  " << type << j << " (" << c.X() << ", " << c.Y() << ", " << c.Z()
                       << "; " << m << ")";
                }
                return testing::AssertionFailure() << ss.str();
            }
            if (std::string(type) == "Face") {
                auto t1 = surfaceType(subShape(reference, type, i));
                auto t2 = surfaceType(subShape(result, type, match));
                if (t1 != t2) {
                    return testing::AssertionFailure()
                        << element.toString() << " surface type " << t2 << " != " << t1;
                }
            }
            auto expected = sortedNames(reference, element);
            auto names = sortedNames(result, Data::IndexedName(type, match));
            if (expected.empty()) {
                return testing::AssertionFailure() << element.toString() << " (OCCT) has no name";
            }
            if (names != expected) {
                std::ostringstream ss;
                ss << element.toString() << " (OCCT) is named";
                for (const auto& n : expected) {
                    ss << "\n  " << n;
                }
                ss << "\nits counterpart " << type << match << " is named";
                for (const auto& n : names) {
                    ss << "\n  " << n;
                }
                return testing::AssertionFailure() << ss.str();
            }
        }
    }
    return testing::AssertionSuccess();
}

/// Below the limit, where OCCT works: the exact construction, forced, gives OCCT's result
testing::AssertionResult sameAsOcct(
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const FF::Request& request
)
{
    TopoShape occt = dressUp(base, edges, request);
    FF::Request belowTheLimit = request;
    belowTheLimit.limitOnly = false;
    TopoShape exactRoute = forced(base, edges, belowTheLimit);
    return sameAs(exactRoute, occt);
}

/// The last section of each of the element's names: the op and flag the dress-up gave it
bool namedBy(const TopoShape& shape, const char* element, const char* op, const char* flag)
{
    auto names = shape.getElementMappedNames(Data::IndexedName(element));
    if (names.empty()) {
        return false;
    }
    for (const auto& name : names) {
        const auto& sections = name.first.getDecodedMappedName();
        if (sections.empty()) {
            return false;
        }
        const auto& last = sections.back();
        if (last.opCode != op || !last.hasMapperFlag(flag)) {
            return false;
        }
    }
    return true;
}

}  // namespace

class FilletFallbackTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }
};

// Section 1's table: each row fails in OCCT 8.0.1 and succeeds by the exact construction with
// the analytic volume, through makeElementFillet / makeElementChamfer.

TEST_F(FilletFallbackTest, fullRoundOfTheTopFace)
{
    TopoShape base(box(30, 4, 20), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {0, 0, 20}, {30, 0, 20}),
        edgeBetween(base, {0, 4, 20}, {30, 4, 20})
    };
    ASSERT_TRUE(occtFilletFails(base, edges, 2, 2));
    TopoShape result = dressUp(base, edges, fillet(2));
    EXPECT_TRUE(exact(result, 2400 - 2 * filletSection(2) * 30));
    // Without refine: one quarter cylinder per edge, as OCCT builds them below the limit
    EXPECT_EQ(result.countSubElements("Face"), 7);
}

TEST_F(FilletFallbackTest, filletAsWideAsItsFace)
{
    TopoShape base(box(30, 4, 20), 1L);
    std::vector<TopoShape> edges {edgeBetween(base, {0, 0, 20}, {30, 0, 20})};
    ASSERT_TRUE(occtFilletFails(base, edges, 4, 4));
    EXPECT_TRUE(exact(dressUp(base, edges, fillet(4)), 2400 - filletSection(4) * 30));
}

TEST_F(FilletFallbackTest, filletAsHighAsThePlate)
{
    TopoShape base(box(30, 20, 4), 1L);
    std::vector<TopoShape> edges {edgeBetween(base, {0, 0, 4}, {30, 0, 4})};
    ASSERT_TRUE(occtFilletFails(base, edges, 4, 4));
    EXPECT_TRUE(exact(dressUp(base, edges, fillet(4)), 2400 - filletSection(4) * 30));
}

TEST_F(FilletFallbackTest, filletConsumingBothFacesOfASquareBar)
{
    TopoShape base(box(30, 4, 4), 1L);
    std::vector<TopoShape> edges {edgeBetween(base, {0, 0, 4}, {30, 0, 4})};
    ASSERT_TRUE(occtFilletFails(base, edges, 4, 4));
    EXPECT_TRUE(exact(dressUp(base, edges, fillet(4)), 480 - filletSection(4) * 30));
}

TEST_F(FilletFallbackTest, columnRoundedIntoACylinder)
{
    TopoShape base(box(4, 4, 10), 1L);
    auto edges = edgesWhere(base, [](const gp_Pnt&) { return true; });
    edges.erase(
        std::remove_if(
            edges.begin(),
            edges.end(),
            [](const TopoShape& e) {
                TopoDS_Vertex a, b;
                TopExp::Vertices(TopoDS::Edge(e.getShape()), a, b);
                return std::abs(BRep_Tool::Pnt(a).Z() - BRep_Tool::Pnt(b).Z()) < 1;
            }
        ),
        edges.end()
    );
    ASSERT_EQ(edges.size(), 4U);
    ASSERT_TRUE(occtFilletFails(base, edges, 2, 2));
    TopoShape result = dressUp(base, edges, fillet(2));
    EXPECT_TRUE(exact(result, pi * 4 * 10));
    EXPECT_EQ(result.countSubElements("Face"), 6);
}

TEST_F(FilletFallbackTest, stepConcaveConvexAndOgee)
{
    TopoShape base(step(), 1L);
    TopoShape concave = edgeBetween(base, {0, 10, 10}, {30, 10, 10});
    TopoShape convex = edgeBetween(base, {0, 10, 14}, {30, 10, 14});
    ASSERT_TRUE(occtFilletFails(base, {concave}, 4, 4));
    ASSERT_TRUE(occtFilletFails(base, {convex}, 4, 4));
    ASSERT_TRUE(occtFilletFails(base, {concave, convex}, 2, 2));
    EXPECT_TRUE(exact(dressUp(base, {concave}, fillet(4)), 7200 + filletSection(4) * 30));
    EXPECT_TRUE(exact(dressUp(base, {convex}, fillet(4)), 7200 - filletSection(4) * 30));
    EXPECT_TRUE(exact(dressUp(base, {concave, convex}, fillet(2)), 7200));
}

TEST_F(FilletFallbackTest, tubeFullRound)
{
    TopoShape base(tube(), 1L);
    auto edges = edgesWhere(base, atHeight(10), true);
    ASSERT_EQ(edges.size(), 2U);
    ASSERT_TRUE(occtFilletFails(base, edges, 2, 2));
    double c = filletCentroid(2);
    double removed = 2 * pi * (10 - c) * filletSection(2) + 2 * pi * (6 + c) * filletSection(2);
    TopoShape result = dressUp(base, edges, fillet(2));
    EXPECT_TRUE(exact(result, pi * 64 * 10 - removed));
    // The round faces are tori, as OCCT makes them
    int tori = 0;
    for (const auto& face : result.getSubTopoShapes(TopAbs_FACE)) {
        tori += surfaceType(face.getShape()) == GeomAbs_Torus ? 1 : 0;
    }
    EXPECT_EQ(tori, 2);
}

TEST_F(FilletFallbackTest, discRoundedOverItsWholeHeight)
{
    // A circular edge whose fillet consumes the cylinder face
    TopoShape base(BRepPrimAPI_MakeCylinder(10, 2).Shape(), 1L);
    auto edges = edgesWhere(base, atHeight(2), true);
    ASSERT_EQ(edges.size(), 1U);
    ASSERT_TRUE(occtFilletFails(base, edges, 2, 2));
    double removed = 2 * pi * (10 - filletCentroid(2)) * filletSection(2);
    EXPECT_TRUE(exact(dressUp(base, edges, fillet(2)), pi * 100 * 2 - removed));
}

TEST_F(FilletFallbackTest, chamfers)
{
    TopoShape base(box(30, 4, 20), 1L);
    TopoShape front = edgeBetween(base, {0, 0, 20}, {30, 0, 20});
    TopoShape back = edgeBetween(base, {0, 4, 20}, {30, 4, 20});
    EXPECT_TRUE(exact(dressUp(base, {front}, chamfer(4)), 2400 - 8 * 30));
    EXPECT_TRUE(exact(dressUp(base, {front, back}, chamfer(2)), 2400 - 4 * 30));
    // Two distances and distance-angle, with 4 on the 4 mm top face: the reference face is
    // the one makeElementChamfer picks, flipped when that is the side face
    TopoDS_Shape reference = base.findAncestorShape(front.getShape(), TopAbs_FACE);
    gp_Pln referencePlane = BRepAdaptor_Surface(TopoDS::Face(reference)).Plane();
    gp_Dir referenceNormal = referencePlane.Axis().Direction();
    bool topIsReference = referenceNormal.IsParallel(gp_Dir(0, 0, 1), 1e-9);
    Flip flip = topIsReference ? Flip::none : Flip::flip;
    auto twoDistances = chamfer(4, 2, ChamferType::twoDistances, flip);
    EXPECT_TRUE(exact(dressUp(base, {front}, twoDistances), 2400 - 4 * 30));
    double b = 4 * std::sin(pi / 6) / std::sin(pi / 3);
    EXPECT_TRUE(exact(
        dressUp(base, {front}, chamfer(4, 30, ChamferType::distanceAngle, flip)),
        2400 - 4 * b / 2 * 30
    ));
    // The column chamfered into a square turned by 45 degrees
    TopoShape column(box(4, 4, 10), 1L);
    std::vector<TopoShape> vertical;
    for (double x : {0.0, 4.0}) {
        for (double y : {0.0, 4.0}) {
            vertical.push_back(edgeBetween(column, {x, y, 0}, {x, y, 10}));
        }
    }
    EXPECT_TRUE(exact(dressUp(column, vertical, chamfer(2)), 160 - 4 * 2 * 10));
    // The tube's top ring chamfered away: cones
    TopoShape ring(tube(), 1L);
    auto circles = edgesWhere(ring, atHeight(10), true);
    double removed = 2 * pi * (10 - 2.0 / 3) * 2 + 2 * pi * (6 + 2.0 / 3) * 2;
    EXPECT_TRUE(exact(dressUp(ring, circles, chamfer(2)), pi * 64 * 10 - removed));
}

TEST_F(FilletFallbackTest, slantedFreeEnds)
{
    // A plate 4 thick whose end x = 30 .. 41.5 is slanted 30 degrees from the vertical: the tools
    // are bounded by the end planes
    double a = 30 + 20 * std::tan(pi / 6);
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(0, 0, 0),
        gp_Pnt(a, 0, 0),
        gp_Pnt(30, 0, 20),
        gp_Pnt(0, 0, 20),
        Standard_True
    );
    TopoDS_Face face = BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
    TopoShape base(BRepPrimAPI_MakePrism(face, gp_Vec(0, 4, 0)).Shape(), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {0, 0, 20}, {30, 0, 20}),
        edgeBetween(base, {0, 4, 20}, {30, 4, 20})
    };
    EXPECT_TRUE(sameAsOcct(base, edges, fillet(1.9)));
    ASSERT_TRUE(occtFilletFails(base, edges, 2, 2));
    double length = 30 + (a - 30) * filletCentroid(2) / 20;  // along the centroid's line
    double expected = volume(base.getShape()) - 2 * filletSection(2) * length;
    EXPECT_TRUE(exact(dressUp(base, edges, fillet(2)), expected));
}

TEST_F(FilletFallbackTest, concaveSlantedFreeEnd)
{
    // The step with its end x = 30 + z / 2 slanted: the concave tool is trimmed at the end plane,
    // not extended into the air beyond it (5.6)
    TopoDS_Shape longStep
        = profileAlongX({{0, 0}, {20, 0}, {20, 14}, {10, 14}, {10, 10}, {0, 10}}, 60);
    TopoDS_Shape beyond = beyondPlane(gp_Pnt(30, 0, 0), gp_Dir(1, 0, -0.5), 200);
    TopoShape base(BRepAlgoAPI_Cut(longStep, beyond).Shape(), 1L);
    ASSERT_EQ(count(base.getShape(), TopAbs_SOLID), 1);
    TopoShape concave = edgeBetween(base, {0, 10, 10}, {35, 10, 10});
    EXPECT_TRUE(sameAsOcct(base, {concave}, fillet(3)));
    double length = 35 + 0.5 * filletCentroid(4);
    double expected = volume(base.getShape()) + filletSection(4) * length;
    EXPECT_TRUE(exact(dressUp(base, {concave}, fillet(4)), expected));
}

TEST_F(FilletFallbackTest, fullRoundOfARibAgainstAWall)
{
    // The rib's top edges end at the wall: the tools are bounded by its plane, and what they
    // leave in it joins the wall's face
    TopoShape base(ribAgainstWall(), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {13, 0, 4}, {13, 20, 4}),
        edgeBetween(base, {17, 0, 4}, {17, 20, 4})
    };
    EXPECT_TRUE(sameAsOcct(base, edges, fillet(1.9)));
    ASSERT_TRUE(occtFilletFails(base, edges, 2, 2));
    double expected = volume(base.getShape()) - 2 * filletSection(2) * 20;
    EXPECT_TRUE(exact(dressUp(base, edges, fillet(2)), expected));
}

TEST_F(FilletFallbackTest, stadiumByTangentContinuation)
{
    // OCCT "succeeds" at r = 2 but keeps a zero-area face (ops#298); the exact construction,
    // forced, gives the clean full round
    TopoShape base(stadium(), 1L);
    auto top = edgesWhere(base, atHeight(3));
    ASSERT_EQ(top.size(), 4);
    double c = filletCentroid(2);
    double plate = 20 * 4 * 3 + pi * 4 * 3;
    double expected = plate - 2 * filletSection(2) * 20 - 2 * pi * (2 - c) * filletSection(2);
    EXPECT_TRUE(exact(forced(base, top, fillet(2)), expected));
    // Below the limit, with the arcs' rounds on tori that don't cross the axis
    EXPECT_TRUE(sameAsOcct(base, top, fillet(0.9)));
}

// Below the limit the forced construction equals OCCT: the same solid, the same faces and the
// same names, element for element.

TEST_F(FilletFallbackTest, sameAsOcctBelowTheLimit)
{
    TopoShape base(box(30, 4, 20), 1L);
    TopoShape front = edgeBetween(base, {0, 0, 20}, {30, 0, 20});
    TopoShape back = edgeBetween(base, {0, 4, 20}, {30, 4, 20});
    EXPECT_TRUE(sameAsOcct(base, {front, back}, fillet(1.9)));
    EXPECT_TRUE(sameAsOcct(base, {front}, fillet(3)));
    EXPECT_TRUE(sameAsOcct(base, {front}, chamfer(2, 3.9, ChamferType::twoDistances)));
    EXPECT_TRUE(sameAsOcct(base, {front}, chamfer(2, 3.9, ChamferType::twoDistances, Flip::flip)));
    EXPECT_TRUE(sameAsOcct(base, {front}, chamfer(2, 30, ChamferType::distanceAngle)));
    EXPECT_TRUE(sameAsOcct(base, {front, back}, chamfer(1.5)));
    TopoShape stepped(step(), 1L);
    EXPECT_TRUE(sameAsOcct(stepped, {edgeBetween(stepped, {0, 10, 10}, {30, 10, 10})}, fillet(3)));
    EXPECT_TRUE(sameAsOcct(stepped, {edgeBetween(stepped, {0, 10, 14}, {30, 10, 14})}, fillet(3)));
    TopoShape column(box(4, 4, 10), 1L);
    std::vector<TopoShape> vertical;
    for (double x : {0.0, 4.0}) {
        for (double y : {0.0, 4.0}) {
            vertical.push_back(edgeBetween(column, {x, y, 0}, {x, y, 10}));
        }
    }
    EXPECT_TRUE(sameAsOcct(column, vertical, fillet(1.5)));
    TopoShape ring(tube(), 1L);
    auto circles = edgesWhere(ring, atHeight(10), true);
    EXPECT_TRUE(sameAsOcct(ring, circles, fillet(1.9)));
    EXPECT_TRUE(sameAsOcct(ring, circles, chamfer(1.5)));
    // A cylinder's top edge with r = R: a sphere. With the caller's base kept as it is
    // (non-destructive Booleans), OCCT 8.0.1's cut leaves a face with misoriented wires here, and
    // the construction refuses; OCCT builds this one itself. Built or refused, never different
    TopoShape cylinder(BRepPrimAPI_MakeCylinder(5, 10).Shape(), 1L);
    auto rim = edgesWhere(cylinder, atHeight(10), true);
    FF::Request sphere = fillet(5);
    sphere.limitOnly = false;
    std::string reason;
    TopoShape exactRoute = forced(cylinder, rim, sphere, &reason);
    if (exactRoute.isNull()) {
        EXPECT_NE(reason.find("not valid"), std::string::npos) << reason;
    }
    else {
        EXPECT_TRUE(sameAs(exactRoute, dressUp(cylinder, rim, fillet(5))));
    }
}

TEST_F(FilletFallbackTest, sameAsOcctAtOtherAngles)
{
    // A plate whose side is slanted: edges of 60 and 120 degrees
    double top = 10 - 4 / std::tan(pi / 3);
    TopoShape base(profileAlongX({{0, 0}, {10, 0}, {top, 4}, {0, 4}}, 30), 1L);
    EXPECT_TRUE(sameAsOcct(base, {edgeBetween(base, {0, 10, 0}, {30, 10, 0})}, fillet(1)));
    EXPECT_TRUE(sameAsOcct(base, {edgeBetween(base, {0, top, 4}, {30, top, 4})}, fillet(2)));
    EXPECT_TRUE(sameAsOcct(base, {edgeBetween(base, {0, top, 4}, {30, top, 4})}, chamfer(1)));
}

TEST_F(FilletFallbackTest, sectionVolumeAtAnAngle)
{
    // At the limit on the 120 degree edge
    double top = 10 - 4 / std::tan(pi / 3);
    TopoShape base(profileAlongX({{0, 0}, {10, 0}, {top, 4}, {0, 4}}, 30), 1L);
    double alpha = 2 * pi / 3;
    // The tangent length equals the slanted face's width: that face is consumed
    double r = 4 / std::sin(pi / 3) * std::tan(alpha / 2);
    std::vector<TopoShape> edges {edgeBetween(base, {0, top, 4}, {30, top, 4})};
    ASSERT_TRUE(occtFilletFails(base, edges, r, r));
    double expected = volume(base.getShape()) - filletSection(r, alpha) * 30;
    EXPECT_TRUE(exact(dressUp(base, edges, fillet(r)), expected));
}

TEST_F(FilletFallbackTest, namedAsAFillet)
{
    // At the limit: the round faces are generated by their edges, the trimmed faces modified,
    // with the fillet's op code
    TopoShape base(box(30, 4, 20), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {0, 0, 20}, {30, 0, 20}),
        edgeBetween(base, {0, 4, 20}, {30, 4, 20})
    };
    TopoShape result = dressUp(base, edges, fillet(2));
    int rounds = 0;
    for (int i = 1; i <= static_cast<int>(result.countSubElements("Face")); ++i) {
        std::string face = "Face" + std::to_string(i);
        if (surfaceType(result.getSubShape(face.c_str())) == GeomAbs_Cylinder) {
            ++rounds;
            EXPECT_TRUE(namedBy(result, face.c_str(), OpCodes::Fillet, Data::MAPPER_FLAG_GENERATED))
                << face;
        }
    }
    EXPECT_EQ(rounds, 2);
    // A chamfer's faces carry the chamfer's op
    TopoShape chamfered = dressUp(base, {edges[0]}, chamfer(4));
    bool found = false;
    for (int i = 1; i <= static_cast<int>(chamfered.countSubElements("Face")); ++i) {
        std::string face = "Face" + std::to_string(i);
        found = found
            || namedBy(chamfered, face.c_str(), OpCodes::Chamfer, Data::MAPPER_FLAG_GENERATED);
    }
    EXPECT_TRUE(found);
}

// OCCT's own result wherever OCCT works

TEST_F(FilletFallbackTest, occtsResultWhereOcctWorks)
{
    // The cube with all 12 edges at r = 1: OCCT builds it, with spherical corners; the exact
    // construction refuses corners, so the result can only be OCCT's
    TopoShape cube(box(4, 4, 4), 1L);
    auto all = cube.getSubTopoShapes(TopAbs_EDGE);
    ASSERT_FALSE(occtFilletFails(cube, all, 1, 1));
    std::string reason;
    EXPECT_TRUE(forced(cube, all, fillet(1), &reason).isNull());
    EXPECT_NE(reason.find("corner"), std::string::npos) << reason;
    TopoShape result = dressUp(cube, all, fillet(1));
    EXPECT_TRUE(exact(result, 8 + 6 * 4 + 6 * pi + 4 * pi / 3));
    int spheres = 0;
    for (TopExp_Explorer it(result.getShape(), TopAbs_FACE); it.More(); it.Next()) {
        spheres += surfaceType(it.Current()) == GeomAbs_Sphere ? 1 : 0;
    }
    EXPECT_EQ(spheres, 8);
}

// Refusals: the original OCCT error stands.

/// The public function throws OCCT's StdFail_NotDone, with its message
testing::AssertionResult throwsOcctsError(const std::function<void()>& run)
{
    try {
        run();
    }
    catch (const StdFail_NotDone& e) {
        if (std::string(e.GetMessageString()) != "BRep_API: command not done") {
            return testing::AssertionFailure() << "message " << e.GetMessageString();
        }
        return testing::AssertionSuccess();
    }
    catch (const Standard_Failure& e) {
        return testing::AssertionFailure() << "another OCCT error: " << e.GetMessageString();
    }
    return testing::AssertionFailure() << "no error";
}

/// OCCT fails, the public function raises OCCT's error, and the exact construction, forced,
/// refuses for the reason
testing::AssertionResult refusedFor(
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const FF::Request& request,
    const char* expected
)
{
    if (!occtFails(base, edges, request)) {
        return testing::AssertionFailure() << "OCCT builds it";
    }
    auto raised = throwsOcctsError([&] { dressUp(base, edges, request); });
    if (!raised) {
        return raised;
    }
    std::string reason;
    if (!forced(base, edges, request, &reason).isNull()) {
        return testing::AssertionFailure() << "built when forced";
    }
    if (reason.find(expected) == std::string::npos) {
        return testing::AssertionFailure() << "refused for: " << reason;
    }
    return testing::AssertionSuccess();
}

TEST_F(FilletFallbackTest, refusesCorners)
{
    // Corners come with S1c: the cube rounded into a sphere fails as before
    TopoShape cube(box(4, 4, 4), 1L);
    auto all = cube.getSubTopoShapes(TopAbs_EDGE);
    EXPECT_TRUE(refusedFor(cube, all, fillet(2), "corner"));
    // Two top edges meeting at a corner, exactly at the limit
    std::vector<TopoShape> two {
        edgeBetween(cube, {0, 0, 4}, {4, 0, 4}),
        edgeBetween(cube, {0, 0, 4}, {0, 4, 4})
    };
    EXPECT_TRUE(refusedFor(cube, two, fillet(4), "corner"));
    EXPECT_TRUE(refusedFor(cube, two, chamfer(4), "corner"));
}

TEST_F(FilletFallbackTest, refusesVariableRadius)
{
    TopoShape base(box(30, 4, 20), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {0, 0, 20}, {30, 0, 20}),
        edgeBetween(base, {0, 4, 20}, {30, 4, 20})
    };
    TopoShape result(2L);
    EXPECT_TRUE(throwsOcctsError([&] { result.makeElementFillet(base, edges, 1, 2); }));
}

TEST_F(FilletFallbackTest, refusesOverlappingTools)
{
    // r = 2.1 on the rib 4 wide: the two rounds overlap
    TopoShape base(ribAgainstWall(), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {13, 0, 4}, {13, 20, 4}),
        edgeBetween(base, {17, 0, 4}, {17, 20, 4})
    };
    EXPECT_TRUE(refusedFor(base, edges, fillet(2.1), "overlap"));
}

TEST_F(FilletFallbackTest, refusesJustOverTheLimit)
{
    // The volume error grows with the square or cube of the excess, so the volume checks pass
    // these; the strips' areas grow linearly with it. The plate's top is 4 wide
    TopoShape base(box(30, 4, 20), 1L);
    TopoShape front = edgeBetween(base, {0, 0, 20}, {30, 0, 20});
    TopoShape back = edgeBetween(base, {0, 4, 20}, {30, 4, 20});
    for (double r : {2.005, 2.01, 2.02}) {
        EXPECT_TRUE(refusedFor(base, {front, back}, fillet(r), "overlap")) << r;
    }
    for (double r : {4.01, 4.02, 4.04}) {
        EXPECT_TRUE(refusedFor(base, {front}, fillet(r), "runs off its face")) << r;
    }
    for (double d : {2.001, 2.002}) {
        EXPECT_TRUE(refusedFor(base, {front, back}, chamfer(d), "overlap")) << d;
    }
    EXPECT_TRUE(refusedFor(base, {front}, chamfer(4.002), "runs off its face"));
    // On a short edge the overhang's area is small next to the strip's perimeter: the tolerance
    // goes with the strip's length along the edge
    TopoShape sliver(box(0.01, 4, 20), 1L);
    TopoShape shortEdge = edgeBetween(sliver, {0, 0, 20}, {0.01, 0, 20});
    EXPECT_TRUE(exact(dressUp(sliver, {shortEdge}, chamfer(4)), 0.8 - 0.01 * 8));
    EXPECT_TRUE(refusedFor(sliver, {shortEdge}, chamfer(4.0004), "runs off its face"));
}

TEST_F(FilletFallbackTest, refusesBelowTheLimit)
{
    // Where OCCT works the construction isn't needed, and isn't for: forced, it refuses
    TopoShape base(box(30, 4, 20), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {0, 0, 20}, {30, 0, 20}),
        edgeBetween(base, {0, 4, 20}, {30, 4, 20})
    };
    std::string reason;
    EXPECT_TRUE(forced(base, edges, fillet(1.9), &reason).isNull());
    EXPECT_NE(reason.find("not at the limit"), std::string::npos) << reason;
}

TEST_F(FilletFallbackTest, refusesAnEndFaceThatDoesNotCoverTheTool)
{
    // The front top edge at r = 4: its end face at x = 0 reaches down to z = 17 only, so the
    // round's end, down to z = 16, would leave a notch in the lower block. OCCT, below the
    // limit, runs the round on over the block instead
    TopoShape base(boxOnALowerBlock(), 1L);
    TopoShape front = edgeBetween(base, {0, 0, 20}, {30, 0, 20});
    EXPECT_TRUE(refusedFor(base, {front}, fillet(4), "does not cover"));
    // The full round of both top edges ends within the end face
    TopoShape back = edgeBetween(base, {0, 4, 20}, {30, 4, 20});
    EXPECT_TRUE(exact(dressUp(base, {front, back}, fillet(2)), 2740 - 2 * filletSection(2) * 30));
}

TEST_F(FilletFallbackTest, refusesANearlyStraightContinuation)
{
    // The front bends by a small angle at x = 30: OCCT's contour runs on along the bent edge,
    // and builds a second round there below the limit. The construction stops at the selected
    // edge, so it must not build the dress-up at the limit
    for (double angle : {0.005, 0.05, 0.1}) {
        TopoShape base(bentFront(angle), 1L);
        TopoShape front = edgeBetween(base, {0, 0, 20}, {30, 0, 20});
        ASSERT_TRUE(occtFilletFails(base, {front}, 4, 4));
        EXPECT_TRUE(throwsOcctsError([&] { dressUp(base, {front}, fillet(4)); })) << angle;
        // The reason: the contour, as the hook reads it after Add()
        BRepFilletAPI_MakeFillet maker(base.getShape());
        maker.Add(4, TopoDS::Edge(front.getShape()));
        FF::Request request = fillet(4);
        for (int i = 1; i <= maker.NbContours(); ++i) {
            for (int j = 1; j <= maker.NbEdges(i); ++j) {
                request.contour.push_back(maker.Edge(i, j));
            }
        }
        std::string reason;
        EXPECT_TRUE(forced(base, {front}, request, &reason).isNull()) << angle;
        EXPECT_NE(reason.find("OCCT's contour"), std::string::npos) << reason;
    }
}

TEST_F(FilletFallbackTest, refusesARoundUnderAnOverhang)
{
    // The step's convex edge with r = 5: the round's tangent line on the riser lies 1 below
    // the riser's foot, inside the material. The volume is right, but the result would cut
    // under the tread: its strip runs off the riser (the contact check after the cut is the
    // second line of defence)
    TopoShape base(step(), 1L);
    std::string reason;
    TopoShape convex = edgeBetween(base, {0, 10, 14}, {30, 10, 14});
    EXPECT_TRUE(forced(base, {convex}, fillet(5), &reason).isNull());
    EXPECT_NE(reason.find("runs off its face"), std::string::npos) << reason;
}

TEST_F(FilletFallbackTest, refusesATangentChainOntoUnselectedEdges)
{
    TopoShape base(stadium(), 1L);
    std::string reason;
    TopoShape side = edgeBetween(base, {0, 0, 3}, {20, 0, 3});
    EXPECT_TRUE(forced(base, {side}, fillet(2), &reason).isNull());
    EXPECT_NE(reason.find("tangent chain"), std::string::npos) << reason;
}

TEST_F(FilletFallbackTest, refusesAConeFace)
{
    TopoShape base(BRepPrimAPI_MakeCone(5, 3, 10).Shape(), 1L);
    std::string reason;
    auto edges = edgesWhere(base, atHeight(10), true);
    ASSERT_EQ(edges.size(), 1U);
    EXPECT_TRUE(forced(base, edges, fillet(1), &reason).isNull());
    EXPECT_FALSE(reason.empty());
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
