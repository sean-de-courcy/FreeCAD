// SPDX-License-Identifier: LGPL-2.1-or-later

// The exact construction of the fillets and chamfers OCCT refuses (ops#300; design:
// notes/fillet-workarounds.md in the ops repository). Designed models only; every expectation is
// the analytic volume, or OCCT's own result where OCCT works.

#include <algorithm>
#include <array>
#include <cmath>
#include <functional>
#include <limits>
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
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GProp_GProps.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <StdFail_NotDone.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pln.hxx>
#include <gp_XY.hxx>

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

/// A prism of the polygon (in the plane y = 0, points as (x, z)) along y
TopoDS_Shape profileAlongY(const std::vector<std::pair<double, double>>& xz, double length)
{
    BRepBuilderAPI_MakePolygon polygon;
    for (auto [x, z] : xz) {
        polygon.Add(gp_Pnt(x, 0, z));
    }
    polygon.Close();
    TopoDS_Face face = BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, length, 0)).Shape();
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

/// The indices of the shape's elements of the type, without degenerated edges: OCCT's sphere
/// patches can carry one at a pole on their boundary (A5), where the construction's sphere has its
/// poles away from the patch. Such an edge has no length and nothing can refer to it usefully
std::vector<int> elementsOf(const TopoShape& shape, const char* type)
{
    std::vector<int> indices;
    auto n = static_cast<int>(shape.countSubElements(type));
    for (int i = 1; i <= n; ++i) {
        auto element = subShape(shape, type, i);
        if (element.ShapeType() == TopAbs_EDGE && BRep_Tool::Degenerated(TopoDS::Edge(element))) {
            continue;
        }
        indices.push_back(i);
    }
    return indices;
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
        auto ours = elementsOf(result, type);
        auto theirs = elementsOf(reference, type);
        auto list = [&](std::ostringstream& ss, const TopoShape& shape, const std::vector<int>& in) {
            for (int j : in) {
                double m = 0;
                gp_Pnt c = centreOf(subShape(shape, type, j), m);
                ss << "\n  " << type << j << " (" << c.X() << ", " << c.Y() << ", " << c.Z()
                   << "; " << m << ")";
            }
        };
        if (ours.size() != theirs.size()) {
            std::ostringstream ss;
            ss << type << " count " << ours.size() << " != " << theirs.size() << "\nthe result has";
            list(ss, result, ours);
            ss << "\nthe reference has";
            list(ss, reference, theirs);
            return testing::AssertionFailure() << ss.str();
        }
        for (int i : theirs) {
            Data::IndexedName element(type, i);
            double measure = 0;
            gp_Pnt centre = centreOf(subShape(reference, type, i), measure);
            int match = 0;
            for (int j : ours) {
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
                list(ss, result, ours);
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

// The rib's top edges chamfered just under the limit: the top strip left between the chamfers,
// 2 (2 - d) wide, is within the Booleans' fuzzy reach of the ridge, which absorbs it with a grown
// tolerance, and the result would lack the strip's volume. The construction refuses it (PR 286
// verification, finding 1); at the limit and further below it builds exactly
TEST_F(FilletFallbackTest, refusesAFaceMergedAwayJustUnderTheLimit)
{
    TopoShape base(box(30, 4, 20), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {0, 0, 20}, {30, 0, 20}),
        edgeBetween(base, {0, 4, 20}, {30, 4, 20})
    };
    for (double d : {2 - 1e-7, 2 - 2e-7}) {
        FF::Request request = chamfer(d);
        request.limitOnly = false;
        std::string reason;
        EXPECT_TRUE(forced(base, edges, request, &reason).isNull()) << d;
        EXPECT_NE(reason.find("tolerance grew"), std::string::npos) << d << ": " << reason;
    }
    EXPECT_TRUE(exact(forced(base, edges, chamfer(2)), 2400 - 4 * 30));
    double d = 2 - 3e-7;
    FF::Request below = chamfer(d);
    below.limitOnly = false;
    TopoShape built = forced(base, edges, below);
    EXPECT_TRUE(exact(built, 2400 - d * d * 30));
    EXPECT_EQ(built.countSubElements("Face"), 8);
}

// The same merge on a base with a larger tolerance away from the rib's top (an imported part's
// edge, an earlier rounded corner): the grown edge is compared with the faces next to it, not with
// the base's largest tolerance (ops#315; PR 288 review, finding 1)
TEST_F(FilletFallbackTest, refusesAFaceMergedAwayBesideALargerToleranceElsewhere)
{
    TopoShape base(box(30, 4, 20), 1L);
    TopoShape bottom = edgeBetween(base, {0, 0, 0}, {30, 0, 0});
    BRep_Builder builder;
    builder.UpdateEdge(TopoDS::Edge(bottom.getShape()), 1e-6);
    for (TopExp_Explorer it(bottom.getShape(), TopAbs_VERTEX); it.More(); it.Next()) {
        builder.UpdateVertex(TopoDS::Vertex(it.Current()), 1e-6);
    }
    std::vector<TopoShape> edges {
        edgeBetween(base, {0, 0, 20}, {30, 0, 20}),
        edgeBetween(base, {0, 4, 20}, {30, 4, 20})
    };
    for (double d : {2 - 1e-7, 2 - 2e-7}) {
        FF::Request request = chamfer(d);
        request.limitOnly = false;
        std::string reason;
        EXPECT_TRUE(forced(base, edges, request, &reason).isNull()) << d;
        EXPECT_NE(reason.find("tolerance grew"), std::string::npos) << d << ": " << reason;
    }
    double d = 2 - 3e-7;
    FF::Request below = chamfer(d);
    below.limitOnly = false;
    TopoShape built = forced(base, edges, below);
    EXPECT_TRUE(exact(built, 2400 - d * d * 30));
    EXPECT_EQ(built.countSubElements("Face"), 8);
}

// OCCT's maker raises the base's tolerances in place: chamfers of a rib's top edges ending
// against a wall as high as the rib leave the base's vertices there at 1e-4, and with them the
// rib's sides. The check for merged faces compares with the tolerances from before the maker
// (Request::faceTolerances, as makeElementChamfer takes them), so the strip that one edge's
// chamfer merges away into the far side just under the limit is still refused after OCCT ran
// (PR 314 review, item 2)
TEST_F(FilletFallbackTest, refusesAFaceMergedAwayAfterOcctRaisedTheTolerances)
{
    BRepAlgoAPI_Fuse fuse(box(30, 4, 20), box(5, 24, 20, gp_Pnt(-5, -10, 0)));
    ShapeUpgrade_UnifySameDomain unify(fuse.Shape());
    unify.Build();
    TopoShape base(unify.Shape(), 1L);
    std::vector<TopoShape> edges {edgeBetween(base, {0, 0, 20}, {30, 0, 20})};
    const auto largest = [&]() {
        double tolerance = 0;
        for (TopExp_Explorer it(base.getShape(), TopAbs_FACE); it.More(); it.Next()) {
            tolerance = std::max(tolerance, FF::faceTolerances(it.Current()).Find(it.Current()));
        }
        return tolerance;
    };
    const auto before = FF::faceTolerances(base.getShape());
    ASSERT_LT(largest(), 1e-6);
    std::vector<TopoShape> both {edges.front(), edgeBetween(base, {0, 4, 20}, {30, 4, 20})};
    EXPECT_FALSE(dressUp(base, both, chamfer(2 - 1e-5)).isNull());
    ASSERT_GT(largest(), 1e-5);
    FF::Request request = chamfer(4 - 2e-7);
    request.limitOnly = false;
    request.faceTolerances = before;
    std::string reason;
    EXPECT_TRUE(forced(base, edges, request, &reason).isNull());
    EXPECT_NE(reason.find("tolerance grew"), std::string::npos) << reason;
}

// The tube's top ring between its rims chamfered just under the limit, 2 (2 - d) wide, merges
// into the edge between the two cones: an exact section like a line between planes (ops#315; PR
// 288 review, finding 2). Further below the ring is a face
TEST_F(FilletFallbackTest, refusesARingMergedAwayBetweenCones)
{
    TopoShape ring(tube(), 1L);
    auto circles = edgesWhere(ring, atHeight(10), true);
    ASSERT_EQ(circles.size(), 2U);
    // Each rim's chamfer removes the triangle d x d / 2 about the axis (Pappus), its centroid at
    // 10 - d / 3 and 6 + d / 3
    const auto removed = [](double d) {
        return 16 * pi * d * d;
    };
    FF::Request request = chamfer(2 - 1e-7);
    request.limitOnly = false;
    std::string reason;
    EXPECT_TRUE(forced(ring, circles, request, &reason).isNull());
    EXPECT_NE(reason.find("tolerance grew"), std::string::npos) << reason;
    double d = 2 - 3e-7;
    FF::Request below = chamfer(d);
    below.limitOnly = false;
    TopoShape built = forced(ring, circles, below);
    EXPECT_TRUE(exact(built, pi * 64 * 10 - removed(d)));
    EXPECT_EQ(built.countSubElements("Face"), 6);
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

// Corners (section 5): miters where two selected edges meet, sphere patches and chamfer
// triangles where three do, at the limit with the analytic volumes of 5.4

namespace
{
constexpr double filletFraction = 1 - pi / 4;      // a 90 degree fillet's section over r^2
constexpr double miterOverlap = 5.0 / 3 - pi / 2;  // two mitered rounds' overlap over r^3
constexpr double sphereCell = 1 - pi / 6;          // a box corner's cell over r^3

/// A box a x b x c with all 12 edges at r (Steiner)
double roundedBox(double a, double b, double c, double r)
{
    double x = a - 2 * r;
    double y = b - 2 * r;
    double z = c - 2 * r;
    return x * y * z + 2 * r * (x * y + y * z + z * x) + pi * r * r * (x + y + z)
        + 4 * pi * r * r * r / 3;
}

std::vector<TopoShape> verticalEdges(const TopoShape& shape)
{
    std::vector<TopoShape> result;
    for (const auto& edge : shape.getSubTopoShapes(TopAbs_EDGE)) {
        TopoDS_Vertex v1, v2;
        TopExp::Vertices(TopoDS::Edge(edge.getShape()), v1, v2);
        gp_Pnt a = BRep_Tool::Pnt(v1);
        gp_Pnt b = BRep_Tool::Pnt(v2);
        if (std::abs(a.X() - b.X()) < 1e-7 && std::abs(a.Y() - b.Y()) < 1e-7) {
            result.push_back(edge);
        }
    }
    return result;
}

int sphereFaces(const TopoShape& shape)
{
    int n = 0;
    for (TopExp_Explorer it(shape.getShape(), TopAbs_FACE); it.More(); it.Next()) {
        n += surfaceType(it.Current()) == GeomAbs_Sphere ? 1 : 0;
    }
    return n;
}

/// A prism of the polygon (in the plane z = 0, points as (x, y)) up to the height
TopoDS_Shape prismOf(const std::vector<std::pair<double, double>>& xy, double height)
{
    BRepBuilderAPI_MakePolygon polygon;
    for (auto [x, y] : xy) {
        polygon.Add(gp_Pnt(x, y, 0));
    }
    polygon.Close();
    TopoDS_Face face = BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, height)).Shape();
}

/// The regular n-gon of circumradius 15, 4 high
TopoDS_Shape regularPlate(int n)
{
    std::vector<std::pair<double, double>> xy;
    for (int k = 0; k < n; ++k) {
        xy.emplace_back(15 * std::cos(2 * pi * k / n), 15 * std::sin(2 * pi * k / n));
    }
    return prismOf(xy, 4);
}

/// A rhombus 40 long, 4 high, with corners of 45 and 135 degrees
TopoDS_Shape rhombusPlate()
{
    double half = 20 * std::tan(pi / 8);
    return prismOf({{20, 0}, {0, half}, {-20, 0}, {0, -half}}, 4);
}

/// A convex prism with all its edges at r (Steiner, as in 5.4): the plan's area and perimeter, and
/// k, the sum of cot(theta / 2) over its plan angles
double roundedPrism(double area, double perimeter, double k, double height, double r)
{
    double innerArea = area - perimeter * r + k * r * r;
    double innerPerimeter = perimeter - 2 * k * r;
    double z = height - 2 * r;
    return innerArea * z + 2 * innerArea * r + innerPerimeter * z * r
        + pi * r * r * innerPerimeter / 2 + pi * r * r * z + 4 * pi * r * r * r / 3;
}

/// A block 40 x 20 x 10 with a slot 30 x 4, 6 deep, from x = 5, y = 8
TopoDS_Shape slotBlock()
{
    return BRepAlgoAPI_Cut(box(40, 20, 10), box(30, 4, 6, gp_Pnt(5, 8, 4))).Shape();
}

/// The slot's four floor edges, and with the vertical edges its four concave vertical edges
std::vector<TopoShape> slotEdges(const TopoShape& slot, bool vertical)
{
    std::vector<TopoShape> edges = edgesWhere(slot, atHeight(4));
    if (vertical) {
        for (const auto& e : verticalEdges(slot)) {
            gp_Pnt p = BRep_Tool::Pnt(TopExp::FirstVertex(TopoDS::Edge(e.getShape())));
            if (p.X() > 1 && p.X() < 39 && p.Y() > 1 && p.Y() < 19) {
                edges.push_back(e);
            }
        }
    }
    return edges;
}

/// A boss 10 x 10, 2 high, on a plate 40 x 40 x 4
TopoDS_Shape bossOnAPlate()
{
    BRepAlgoAPI_Fuse fuse(box(40, 40, 4), box(10, 10, 2, gp_Pnt(15, 15, 4)));
    ShapeUpgrade_UnifySameDomain unify(fuse.Shape());
    unify.Build();
    return unify.Shape();
}

/// An L block 4 high, its arms 30 x 10, the inner corner at (10, 10)
TopoDS_Shape lBlock()
{
    return prismOf({{0, 0}, {30, 0}, {30, 10}, {10, 10}, {10, 30}, {0, 30}}, 4);
}

/// The edges of the shape with a vertex at the point
std::vector<TopoShape> edgesAt(const TopoShape& shape, const gp_Pnt& point)
{
    std::vector<TopoShape> result;
    for (const auto& edge : shape.getSubTopoShapes(TopAbs_EDGE)) {
        for (TopExp_Explorer it(edge.getShape(), TopAbs_VERTEX); it.More(); it.Next()) {
            if (BRep_Tool::Pnt(TopoDS::Vertex(it.Current())).Distance(point) < 1e-7) {
                result.push_back(edge);
                break;
            }
        }
    }
    return result;
}

/// The plate 30 x 20 x 4 with its end x = 30 leaning in by the angle (out, if negative): the top
/// is (30 - 4 tan(angle)) x 20
TopoDS_Shape leaningPlate(double angle)
{
    double lean = 4 * std::tan(angle);
    return profileAlongY({{0, 0}, {30, 0}, {30 - lean, 4}, {0, 4}}, 20);
}

/// The plate 30 x 20 x 4 with all four walls leaning in by the angle from its bottom
TopoDS_Shape draftedPlate(double angle)
{
    double c = std::cos(angle);
    double s = std::sin(angle);
    TopoDS_Shape shape = box(30, 20, 4);
    for (auto [point, normal] : std::vector<std::pair<gp_Pnt, gp_Dir>> {
             {{30, 0, 0}, {c, 0, s}},
             {{0, 0, 0}, {-c, 0, s}},
             {{0, 20, 0}, {0, c, s}},
             {{0, 0, 0}, {0, -c, s}}
         }) {
        shape = BRepAlgoAPI_Cut(shape, beyondPlane(point, normal, 100)).Shape();
    }
    return shape;
}

/// The parallelogram 20 x 10 with a 60 degree corner at the origin, extruded along the vector
TopoDS_Shape parallelepiped(const gp_Vec& along)
{
    BRepBuilderAPI_MakePolygon polygon(
        gp_Pnt(0, 0, 0),
        gp_Pnt(20, 0, 0),
        gp_Pnt(20 + 10 * std::cos(pi / 3), 10 * std::sin(pi / 3), 0),
        gp_Pnt(10 * std::cos(pi / 3), 10 * std::sin(pi / 3), 0),
        Standard_True
    );
    TopoDS_Face face = BRepBuilderAPI_MakeFace(polygon.Wire(), Standard_True).Face();
    return BRepPrimAPI_MakePrism(face, along).Shape();
}

/// The boss of bossOnAPlate with its wall x = 25 leaning in by 10 degrees
TopoDS_Shape draftedBossOnAPlate()
{
    TopoDS_Shape boss = box(10, 10, 2, gp_Pnt(15, 15, 4));
    gp_Dir leaning(std::cos(pi / 18), 0, std::sin(pi / 18));
    boss = BRepAlgoAPI_Cut(boss, beyondPlane({25, 15, 4}, leaning, 100)).Shape();
    BRepAlgoAPI_Fuse fuse(box(40, 40, 4), boss);
    ShapeUpgrade_UnifySameDomain unify(fuse.Shape());
    unify.Build();
    return unify.Shape();
}

/// The integral of f over [a, b] by n-point Gauss-Legendre, its nodes by Newton's method
double gaussLegendre(const std::function<double(double)>& f, double a, double b, int n = 32)
{
    double sum = 0.0;
    for (int i = 1; i <= n; ++i) {
        double x = std::cos(pi * (i - 0.25) / (n + 0.5));
        double derivative = 0.0;
        for (int iteration = 0; iteration < 100; ++iteration) {
            double p0 = 1.0;
            double p1 = x;
            for (int k = 2; k <= n; ++k) {
                double p2 = ((2 * k - 1) * x * p1 - (k - 1) * p0) / k;
                p0 = p1;
                p1 = p2;
            }
            derivative = n * (x * p1 - p0) / (x * x - 1);
            double step = p1 / derivative;
            x -= step;
            if (std::abs(step) < 1e-16) {
                break;
            }
        }
        double weight = 2 / ((1 - x * x) * derivative * derivative);
        sum += weight * f((a + b) / 2 + (b - a) / 2 * x);
    }
    return sum * (b - a) / 2;
}

/** What a dress-up of the four top edges of a plate removes, by slices parallel to the top at
 * the depth z (Gauss-Legendre between the depths where a band ends). The top is the rectangle
 * a x b, and its sides (x = 0, x = a, y = 0, y = b) meet it at the dihedral angles alpha. A slice
 * of the plate is the rectangle with each side z cot alpha in from the top's, and it loses a band
 * w(z) wide along each side: the union of the four rounds (or chamfers), as OCCT builds them where
 * they meet at unequal angles, and its miter where they meet at equal ones.
 * - fillet r, z = r (1 - cos theta): w = r cot(alpha / 2) - r sin theta - z cot alpha, down to
 *   theta = pi - alpha (the tangent line on the side)
 * - chamfer d: w = d - z / sin alpha, down to z = d sin alpha
 */
double plateTopRemoved(
    bool isFillet,
    double a,
    double b,
    const std::array<double, 4>& alpha,
    double size,
    double depth
)
{
    auto removed = [&](double z, const std::array<double, 4>& width) {
        std::array<double, 4> outer {};
        std::array<double, 4> inner {};
        for (int i = 0; i < 4; ++i) {
            outer[i] = z / std::tan(alpha[i]);
            inner[i] = outer[i] + std::max(0.0, width[i]);
        }
        return (a - outer[0] - outer[1]) * (b - outer[2] - outer[3])
            - (a - inner[0] - inner[1]) * (b - inner[2] - inner[3]);
    };
    std::vector<double> ends;
    double last = 0.0;
    std::function<double(double)> slice;
    if (isFillet) {
        last = std::acos(1 - std::min(depth, 2 * size) / size);
        for (double angle : alpha) {
            ends.push_back(pi - angle);
        }
        slice = [&](double theta) {
            double z = size * (1 - std::cos(theta));
            std::array<double, 4> width {};
            for (int i = 0; i < 4; ++i) {
                width[i] = theta <= pi - alpha[i] ? size / std::tan(alpha[i] / 2)
                        - size * std::sin(theta) - z / std::tan(alpha[i])
                                                  : 0.0;
            }
            return removed(z, width) * size * std::sin(theta);
        };
    }
    else {
        last = depth;
        for (double angle : alpha) {
            ends.push_back(size * std::sin(angle));
        }
        slice = [&](double z) {
            std::array<double, 4> width {};
            for (int i = 0; i < 4; ++i) {
                width[i] = size - z / std::sin(alpha[i]);
            }
            return removed(z, width);
        };
    }
    ends.push_back(0.0);
    ends.push_back(last);
    std::sort(ends.begin(), ends.end());
    double total = 0.0;
    for (size_t i = 0; i + 1 < ends.size(); ++i) {
        double from = std::clamp(ends[i], 0.0, last);
        double to = std::clamp(ends[i + 1], 0.0, last);
        if (to > from) {
            total += gaussLegendre(slice, from, to);
        }
    }
    return total;
}
}  // namespace

TEST_F(FilletFallbackTest, twoEdgeCornersWithUnequalAngles)
{
    // The plate whose end leans in by 10 degrees: its top edge meets the long top edges at 100
    // degrees against their 90. The four top edges at r = t, and chamfered at d = t: the long
    // sides vanish; the rounds meet at the leaning end where the two tools cross (an ellipse on
    // the plane bisecting their axes, not the faces' bisector plane), the union of the two tools,
    // and in miters at the other
    for (double degrees : {10.0, 25.0}) {
        double angle = degrees * pi / 180;
        TopoShape plate(leaningPlate(angle), 1L);
        auto top = edgesWhere(plate, atHeight(4));
        ASSERT_EQ(top.size(), 4U);
        double a = 30 - 4 * std::tan(angle);
        double volume = 4 * 20 * (30 + a) / 2;
        std::array<double, 4> alpha {pi / 2, pi / 2 + angle, pi / 2, pi / 2};
        ASSERT_TRUE(occtFilletFails(plate, top, 4, 4)) << degrees;
        TopoShape rounded = dressUp(plate, top, fillet(4));
        EXPECT_TRUE(exact(rounded, volume - plateTopRemoved(true, a, 20, alpha, 4, 4))) << degrees;
        ASSERT_TRUE(occtFails(plate, top, chamfer(4))) << degrees;
        double chamfered = volume - plateTopRemoved(false, a, 20, alpha, 4, 4);
        EXPECT_TRUE(exact(dressUp(plate, top, chamfer(4)), chamfered)) << degrees;
    }
}

TEST_F(FilletFallbackTest, unequalCornersSameAsOcctBelowTheLimit)
{
    // OCCT's result where it works, with the names: the two edges at a leaning end, the four top
    // edges, an end leaning out (80 degrees), rounds and chamfers
    for (double degrees : {10.0, -10.0, 25.0}) {
        TopoShape plate(leaningPlate(degrees * pi / 180), 1L);
        auto top = edgesWhere(plate, atHeight(4));
        double a = 30 - 4 * std::tan(degrees * pi / 180);
        std::vector<TopoShape> two {
            edgeBetween(plate, {0, 0, 4}, {a, 0, 4}),
            edgeBetween(plate, {a, 0, 4}, {a, 20, 4})
        };
        EXPECT_TRUE(sameAsOcct(plate, two, fillet(2))) << degrees;
        EXPECT_TRUE(sameAsOcct(plate, two, chamfer(2))) << degrees;
        EXPECT_TRUE(sameAsOcct(plate, top, fillet(degrees < 0 ? 2 : 3.9))) << degrees;
        EXPECT_TRUE(sameAsOcct(plate, top, chamfer(degrees < 0 ? 2 : 3.9))) << degrees;
    }
}

TEST_F(FilletFallbackTest, threeEdgeCornersWithUnequalAngles)
{
    // The plate with all four walls leaning in by 10 degrees, all 12 edges at r = t / 2: the
    // walls vanish (top edges at 100 degrees, bottom ones at 80), the sphere patches are tangent
    // to three planes at unequal angles. The result is the rectangle at half height that the
    // offset walls bound, swept by the ball (Steiner): 2 A r + pi P r^2 / 2 + 4 pi r^3 / 3
    double angle = pi / 18;
    TopoShape plate(draftedPlate(angle), 1L);
    auto all = plate.getSubTopoShapes(TopAbs_EDGE);
    ASSERT_EQ(all.size(), 12U);
    double r = 2;
    ASSERT_TRUE(occtFilletFails(plate, all, r, r));
    double inset = r * (std::tan(angle) + 1 / std::cos(angle));
    double x = 30 - 2 * inset;
    double y = 20 - 2 * inset;
    TopoShape rounded = dressUp(plate, all, fillet(r));
    EXPECT_TRUE(exact(rounded, 2 * x * y * r + pi * (x + y) * r * r + 4 * pi * r * r * r / 3));
    EXPECT_EQ(sphereFaces(rounded), 8);
    // The acute triangle (30, 75 and 75 degrees) with all edges at r = t / 2
    double side = 30;
    TopoShape triangle(
        prismOf(
            {{0, 0},
             {side * std::cos(pi / 12), -side * std::sin(pi / 12)},
             {side * std::cos(pi / 12), side * std::sin(pi / 12)}},
            4
        ),
        1L
    );
    auto edges = triangle.getSubTopoShapes(TopAbs_EDGE);
    ASSERT_TRUE(occtFilletFails(triangle, edges, r, r));
    double area = side * side * std::sin(pi / 6) / 2;
    double perimeter = 2 * side + 2 * side * std::sin(pi / 12);
    double k = 1 / std::tan(pi / 12) + 2 / std::tan(5 * pi / 24);
    TopoShape acute = dressUp(triangle, edges, fillet(r));
    EXPECT_TRUE(exact(acute, roundedPrism(area, perimeter, k, 4, r)));
    EXPECT_EQ(sphereFaces(acute), 6);
    // An oblique parallelepiped, all edges at r = t / 2: its walls at half height, each moved in
    // by r over the horizontal part of its unit normal, bound the parallelogram the ball sweeps
    gp_Vec along(1, 0.5, 4);
    TopoShape oblique(parallelepiped(along), 1L);
    auto all12 = oblique.getSubTopoShapes(TopAbs_EDGE);
    ASSERT_TRUE(occtFilletFails(oblique, all12, r, r));
    auto moved = [&](const gp_Vec& side) {
        gp_Vec normal = side.Crossed(along);
        return r * normal.Magnitude() / std::hypot(normal.X(), normal.Y());
    };
    double sine = std::sin(pi / 3);
    double lu = 20 - 2 * moved({std::cos(pi / 3), sine, 0}) / sine;
    double lv = 10 - 2 * moved({1, 0, 0}) / sine;
    TopoShape swept = dressUp(oblique, all12, fillet(r));
    EXPECT_TRUE(exact(
        swept,
        2 * lu * lv * sine * r + pi * (lu + lv) * r * r + 4 * pi * r * r * r / 3
    ));
    EXPECT_EQ(sphereFaces(swept), 8);
}

TEST_F(FilletFallbackTest, twoEdgeCornersMiter)
{
    // A2: the plate's four top edges at r = t: the side faces vanish, the rounds meet in miters
    TopoShape plate(box(30, 20, 4), 1L);
    auto top = edgesWhere(plate, atHeight(4));
    ASSERT_TRUE(occtFilletFails(plate, top, 4, 4));
    double r = 4;
    EXPECT_TRUE(exact(
        dressUp(plate, top, fillet(r)),
        2400 - (100 * r * r * filletFraction - 4 * r * r * r * miterOverlap)
    ));
    // A4: the rib's four top edges at r = 2: a full round, mitered into the end rounds
    TopoShape rib(box(30, 4, 20), 1L);
    auto ribTop = edgesWhere(rib, atHeight(20));
    ASSERT_TRUE(occtFilletFails(rib, ribTop, 2, 2));
    r = 2;
    EXPECT_TRUE(exact(
        dressUp(rib, ribTop, fillet(r)),
        2400 - (68 * r * r * filletFraction - 4 * r * r * r * miterOverlap)
    ));
    // A8, A10: the same corners chamfered (P d^2 / 2 - k d^3 / 3)
    EXPECT_TRUE(exact(dressUp(plate, top, chamfer(4)), 2400 - (100 * 8 - 4 * 64.0 / 3)));
    EXPECT_TRUE(exact(dressUp(rib, ribTop, chamfer(2)), 2400 - (68 * 2 - 4 * 8.0 / 3)));
    // Two edges of a cube at one corner, r = 4: both side faces vanish
    TopoShape cube(box(4, 4, 4), 1L);
    std::vector<TopoShape> two {
        edgeBetween(cube, {0, 0, 4}, {4, 0, 4}),
        edgeBetween(cube, {0, 0, 4}, {0, 4, 4})
    };
    EXPECT_TRUE(
        exact(dressUp(cube, two, fillet(4)), 64 - (8 * 16 * filletFraction - 64 * miterOverlap))
    );
    EXPECT_TRUE(exact(dressUp(cube, two, chamfer(4)), 64 - (8 * 8 - 64.0 / 3)));
}

TEST_F(FilletFallbackTest, threeEdgeCornersSpherePatches)
{
    // A1: the plate's 12 edges at r = t / 2 (a rounded slab): the vertical rounds vanish
    TopoShape plate(box(30, 20, 4), 1L);
    auto all = plate.getSubTopoShapes(TopAbs_EDGE);
    ASSERT_TRUE(occtFilletFails(plate, all, 2, 2));
    TopoShape slab = dressUp(plate, all, fillet(2));
    EXPECT_TRUE(exact(slab, roundedBox(30, 20, 4, 2)));
    EXPECT_EQ(sphereFaces(slab), 8);
    // A5: the rib's top and vertical edges at r = 2: domed ends
    TopoShape rib(box(30, 4, 20), 1L);
    auto edges = edgesWhere(rib, atHeight(20));
    for (const auto& e : verticalEdges(rib)) {
        edges.push_back(e);
    }
    ASSERT_TRUE(occtFilletFails(rib, edges, 2, 2));
    double r = 2;
    TopoShape domed = dressUp(rib, edges, fillet(r));
    EXPECT_TRUE(exact(
        domed,
        2400
            - (4 * r * r * r * sphereCell + 2 * 26 * r * r * filletFraction
               + 4 * (20 - r) * r * r * filletFraction)
    ));
    EXPECT_EQ(sphereFaces(domed), 4);
    // The cube's 12 edges at r = 2: a ball of eight patches
    TopoShape cube(box(4, 4, 4), 1L);
    EXPECT_TRUE(exact(dressUp(cube, cube.getSubTopoShapes(TopAbs_EDGE), fillet(2)), 32 * pi / 3));
    // A3: the plate's top and vertical edges at r = t: the vertical rounds vanish, the sphere
    // patches reach the bottom face
    std::vector<TopoShape> topAndVertical = edgesWhere(plate, atHeight(4));
    for (const auto& e : verticalEdges(plate)) {
        topAndVertical.push_back(e);
    }
    ASSERT_TRUE(occtFilletFails(plate, topAndVertical, 4, 4));
    r = 4;
    TopoShape cornered = dressUp(plate, topAndVertical, fillet(r));
    EXPECT_TRUE(exact(
        cornered,
        2400 - (4 * r * r * r * sphereCell + 2 * (22 + 12) * r * r * filletFraction)
    ));
    EXPECT_EQ(sphereFaces(cornered), 4);
    // A6: the three edges at one corner of the rib at r = 4: the short top edge's two faces vanish
    std::vector<TopoShape> three = edgesAt(rib, {0, 0, 20});
    ASSERT_EQ(three.size(), 3U);
    ASSERT_TRUE(occtFilletFails(rib, three, 4, 4));
    TopoShape oneCorner = dressUp(rib, three, fillet(r));
    EXPECT_TRUE(exact(
        oneCorner,
        2400 - (r * r * r * sphereCell + (26 + 0 + 16) * r * r * filletFraction)
    ));
    EXPECT_EQ(sphereFaces(oneCorner), 1);
    // A11: a slot's floor and vertical edges, concave, r = 2: a ball-end slot
    r = 2;
    TopoShape slot(slotBlock(), 1L);
    std::vector<TopoShape> concave = slotEdges(slot, true);
    ASSERT_EQ(concave.size(), 8U);
    ASSERT_TRUE(occtFilletFails(slot, concave, 2, 2));
    EXPECT_TRUE(exact(
        dressUp(slot, concave, fillet(r)),
        8000 - 720
            + (4 * r * r * r * sphereCell + 2 * 26 * r * r * filletFraction
               + 4 * (6 - r) * r * r * filletFraction)
    ));
}

TEST_F(FilletFallbackTest, threeEdgeCornersChamfered)
{
    // A9: the plate's 12 edges chamfered at d = t / 2: each box corner removes 5 d^3 / 6, each
    // edge between corners (L - 2 d) d^2 / 2
    TopoShape plate(box(30, 20, 4), 1L);
    auto all = plate.getSubTopoShapes(TopAbs_EDGE);
    double d = 2;
    ASSERT_TRUE(occtFails(plate, all, chamfer(d)));
    EXPECT_TRUE(exact(
        dressUp(plate, all, chamfer(d)),
        2400 - (8 * 5 * d * d * d / 6 + 4 * (26 + 16) * d * d / 2)
    ));
}

TEST_F(FilletFallbackTest, twoEdgeCornersAtConcaveVertices)
{
    // A11b: the slot's floor edges, concave at a concave vertex, r = 2: the miter's overlap is
    // added material counted twice, so it comes off
    double r = 2;
    TopoShape slot(slotBlock(), 1L);
    auto floor = slotEdges(slot, false);
    ASSERT_EQ(floor.size(), 4U);
    ASSERT_TRUE(occtFilletFails(slot, floor, r, r));
    EXPECT_TRUE(exact(
        dressUp(slot, floor, fillet(r)),
        7280 + 68 * r * r * filletFraction - 4 * r * r * r * miterOverlap
    ));
    // A12: the boss's base edges, concave, at vertices whose unselected edge is convex: the
    // rounds run on past the boss's corners and add the miter term
    TopoShape boss(bossOnAPlate(), 1L);
    auto base = edgesWhere(boss, [](const gp_Pnt& p) {
        return std::abs(p.Z() - 4) < 1e-7 && p.X() > 14 && p.X() < 26 && p.Y() > 14 && p.Y() < 26;
    });
    ASSERT_EQ(base.size(), 4U);
    ASSERT_TRUE(occtFilletFails(boss, base, r, r));
    EXPECT_TRUE(exact(
        dressUp(boss, base, fillet(r)),
        6600 + 40 * r * r * filletFraction + 4 * r * r * r * miterOverlap
    ));
    // A13: the L block's two convex top edges at its inner corner, a concave vertex, r = t = 4
    r = 4;
    TopoShape l(lBlock(), 1L);
    std::vector<TopoShape> inner {
        edgeBetween(l, {10, 10, 4}, {30, 10, 4}),
        edgeBetween(l, {10, 10, 4}, {10, 30, 4})
    };
    ASSERT_TRUE(occtFilletFails(l, inner, r, r));
    EXPECT_TRUE(exact(
        dressUp(l, inner, fillet(r)),
        2000 - (40 * r * r * filletFraction + r * r * r * miterOverlap)
    ));
}

TEST_F(FilletFallbackTest, cornersAtOtherPlanAngles)
{
    // The triangle (60 degrees) and the hexagon (120): top edges at r = t, all edges at r = t / 2
    for (int n : {3, 6}) {
        TopoShape plate(regularPlate(n), 1L);
        double area = n * 15 * 15 * std::sin(2 * pi / n) / 2;
        double perimeter = n * 2 * 15 * std::sin(pi / n);
        double k = n / std::tan(pi * (n - 2) / n / 2);
        auto top = edgesWhere(plate, atHeight(4));
        ASSERT_TRUE(occtFilletFails(plate, top, 4, 4)) << n;
        EXPECT_TRUE(exact(
            dressUp(plate, top, fillet(4)),
            4 * area - (perimeter * 16 * filletFraction - k * 64 * miterOverlap)
        )) << n;
        auto all = plate.getSubTopoShapes(TopAbs_EDGE);
        ASSERT_TRUE(occtFilletFails(plate, all, 2, 2)) << n;
        TopoShape rounded = dressUp(plate, all, fillet(2));
        EXPECT_TRUE(exact(rounded, roundedPrism(area, perimeter, k, 4, 2))) << n;
        EXPECT_EQ(sphereFaces(rounded), 2 * n) << n;
    }
    // The rhombus (45 and 135 degrees): the same, and its top edges chamfered at d = t
    TopoShape rhombus(rhombusPlate(), 1L);
    double half = 20 * std::tan(pi / 8);
    double area = 2 * 20 * half;
    double perimeter = 4 * std::hypot(20, half);
    double k = 2 / std::tan(pi / 8) + 2 / std::tan(3 * pi / 8);
    auto top = edgesWhere(rhombus, atHeight(4));
    ASSERT_TRUE(occtFilletFails(rhombus, top, 4, 4));
    EXPECT_TRUE(exact(
        dressUp(rhombus, top, fillet(4)),
        4 * area - (perimeter * 16 * filletFraction - k * 64 * miterOverlap)
    ));
    auto all = rhombus.getSubTopoShapes(TopAbs_EDGE);
    ASSERT_TRUE(occtFilletFails(rhombus, all, 2, 2));
    EXPECT_TRUE(exact(dressUp(rhombus, all, fillet(2)), roundedPrism(area, perimeter, k, 4, 2)));
    ASSERT_TRUE(occtFails(rhombus, top, chamfer(4)));
    EXPECT_TRUE(
        exact(dressUp(rhombus, top, chamfer(4)), 4 * area - (perimeter * 8 - k * 64.0 / 3))
    );
}

TEST_F(FilletFallbackTest, fullRoundOfARibAgainstAWallWithItsEndEdge)
{
    // The rib's top edges end at the wall and meet its end edge in two miters at y = 20
    TopoShape base(ribAgainstWall(), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {13, 0, 4}, {13, 20, 4}),
        edgeBetween(base, {17, 0, 4}, {17, 20, 4}),
        edgeBetween(base, {13, 20, 4}, {17, 20, 4})
    };
    ASSERT_TRUE(occtFilletFails(base, edges, 2, 2));
    double r = 2;
    EXPECT_TRUE(exact(
        dressUp(base, edges, fillet(r)),
        6320 - (40 * r * r * filletFraction + 4 * r * r * filletFraction - 2 * r * r * r * miterOverlap)
    ));
}

TEST_F(FilletFallbackTest, cornersSameAsOcctBelowTheLimit)
{
    TopoShape rib(box(30, 4, 20), 1L);
    auto edges = edgesWhere(rib, atHeight(20));
    EXPECT_TRUE(sameAsOcct(rib, edges, fillet(1.9)));
    for (const auto& e : verticalEdges(rib)) {
        edges.push_back(e);
    }
    EXPECT_TRUE(sameAsOcct(rib, edges, fillet(1.9)));
    EXPECT_TRUE(sameAsOcct(rib, edgesAt(rib, {0, 0, 20}), fillet(3.9)));
    TopoShape plate(box(30, 20, 4), 1L);
    EXPECT_TRUE(sameAsOcct(plate, plate.getSubTopoShapes(TopAbs_EDGE), chamfer(1.9)));
    std::vector<TopoShape> topAndVertical = edgesWhere(plate, atHeight(4));
    for (const auto& e : verticalEdges(plate)) {
        topAndVertical.push_back(e);
    }
    EXPECT_TRUE(sameAsOcct(plate, topAndVertical, fillet(3.9)));
    TopoShape slot(slotBlock(), 1L);
    EXPECT_TRUE(sameAsOcct(slot, slotEdges(slot, true), fillet(1.9)));
    EXPECT_TRUE(sameAsOcct(slot, slotEdges(slot, false), fillet(1.9)));
    TopoShape l(lBlock(), 1L);
    std::vector<TopoShape> inner {
        edgeBetween(l, {10, 10, 4}, {30, 10, 4}),
        edgeBetween(l, {10, 10, 4}, {10, 30, 4})
    };
    EXPECT_TRUE(sameAsOcct(l, inner, fillet(3.9)));
    TopoShape hexagon(regularPlate(6), 1L);
    EXPECT_TRUE(sameAsOcct(hexagon, hexagon.getSubTopoShapes(TopAbs_EDGE), fillet(1.9)));
    TopoShape rhombus(rhombusPlate(), 1L);
    EXPECT_TRUE(sameAsOcct(rhombus, edgesWhere(rhombus, atHeight(4)), fillet(3.9)));
    EXPECT_TRUE(sameAsOcct(rhombus, edgesWhere(rhombus, atHeight(4)), chamfer(3.9)));
}

// OCCT's own result wherever OCCT works

TEST_F(FilletFallbackTest, occtsResultWhereOcctWorks)
{
    // The cube with all 12 edges at r = 1: OCCT builds it, with spherical corners; below the
    // limit the exact construction refuses, so the result can only be OCCT's
    TopoShape cube(box(4, 4, 4), 1L);
    auto all = cube.getSubTopoShapes(TopAbs_EDGE);
    ASSERT_FALSE(occtFilletFails(cube, all, 1, 1));
    std::string reason;
    EXPECT_TRUE(forced(cube, all, fillet(1), &reason).isNull());
    EXPECT_NE(reason.find("not at the limit"), std::string::npos) << reason;
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

TEST_F(FilletFallbackTest, refusesUnequalCornersThatAreNotConvex)
{
    // The boss with its wall x = 25 leaning in by 10 degrees: its base edge meets the base edges
    // of the walls y = 15 and y = 25 at unequal angles, concave edges at vertices whose vertical
    // edge is convex. OCCT's rounds don't meet as the union of the tools there
    TopoShape boss(draftedBossOnAPlate(), 1L);
    auto base = edgesWhere(boss, [](const gp_Pnt& p) {
        return std::abs(p.Z() - 4) < 1e-7 && p.X() > 14 && p.X() < 26 && p.Y() > 14 && p.Y() < 26;
    });
    ASSERT_EQ(base.size(), 4U);
    std::string reason;
    EXPECT_TRUE(forced(boss, base, fillet(2), &reason).isNull());
    EXPECT_NE(reason.find("unequal dihedral angles that is not convex"), std::string::npos)
        << reason;
}

TEST_F(FilletFallbackTest, refusesObliqueCornersWhoseRoundsRunPastTheirVertex)
{
    // The parallelepiped extruded along (3, 1, 4), all edges at r = t / 2: at its obtuse corners
    // the sphere centre's foot on an edge falls behind the vertex, so the edge's round would run
    // past it, out of the material, and its strip off its face (5.3, a known refusal)
    TopoShape oblique(parallelepiped({3, 1, 4}), 1L);
    EXPECT_TRUE(refusedFor(
        oblique,
        oblique.getSubTopoShapes(TopAbs_EDGE),
        fillet(2),
        "a tangent strip runs off its face"
    ));
}

TEST_F(FilletFallbackTest, refusesCornersOcctBuildsWithOtherPatches)
{
    // Section 5.3's refusals, where OCCT builds a torus or B-spline patch below the limit. A
    // boss corner of mixed convexity: its convex vertical edge and the two concave base edges
    TopoShape boss(bossOnAPlate(), 1L);
    auto mixed = edgesAt(boss, {15, 15, 4});
    ASSERT_EQ(mixed.size(), 3U);
    EXPECT_TRUE(refusedFor(boss, mixed, fillet(2), "mixed convexity"));
    // A15: the triangle and hexagon plates' edges chamfered: their corners aren't square
    for (int n : {3, 6}) {
        TopoShape plate(regularPlate(n), 1L);
        auto all = plate.getSubTopoShapes(TopAbs_EDGE);
        EXPECT_TRUE(refusedFor(plate, all, chamfer(2), "not square")) << n;
    }
    // The D plate: a line and a half circle meeting at an angle, top edges at r = t
    BRepBuilderAPI_MakeWire outline;
    outline.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, -10, 0), gp_Pnt(0, 10, 0)).Edge());
    outline.Add(
        BRepBuilderAPI_MakeEdge(
            GC_MakeArcOfCircle(gp_Pnt(0, 10, 0), gp_Pnt(10, 0, 0), gp_Pnt(0, -10, 0)).Value()
        )
            .Edge()
    );
    TopoDS_Face d = BRepBuilderAPI_MakeFace(outline.Wire(), Standard_True).Face();
    TopoShape dPlate(BRepPrimAPI_MakePrism(d, gp_Vec(0, 0, 4)).Shape(), 1L);
    auto dTop = edgesWhere(dPlate, atHeight(4));
    ASSERT_EQ(dTop.size(), 2U);
    EXPECT_TRUE(refusedFor(dPlate, dTop, fillet(4), "not straight"));
}

TEST_F(FilletFallbackTest, refusesCornersJustOverTheLimit)
{
    // The domed rib over the limit: the planes through the two sphere centres at the ends of a
    // short top edge cross inside its round, from limit + 2e-7 on
    TopoShape rib(box(30, 4, 20), 1L);
    auto edges = edgesWhere(rib, atHeight(20));
    for (const auto& e : verticalEdges(rib)) {
        edges.push_back(e);
    }
    for (double r : {2.0000002, 2.00001, 2.01, 2.1}) {
        EXPECT_TRUE(refusedFor(rib, edges, fillet(r), "cross inside its tool")) << r;
    }
}

TEST_F(FilletFallbackTest, refusesAnApexOfFourEdges)
{
    // A pyramid on a 20 x 20 square, 10 high: OCCT returns an invalid result there without an
    // error (ops#297), which the exact construction doesn't take over
    TopoDS_Shape solid = box(20, 20, 10);
    gp_Pnt apex(10, 10, 10);
    for (const auto& normal : {gp_Dir(0, -1, 1), gp_Dir(1, 0, 1), gp_Dir(0, 1, 1), gp_Dir(-1, 0, 1)}
    ) {
        solid = BRepAlgoAPI_Cut(solid, beyondPlane(apex, normal, 200)).Shape();
    }
    TopoShape pyramid(solid, 1L);
    ASSERT_NEAR(volume(solid), 4000.0 / 3, 1e-9);
    auto four = edgesAt(pyramid, apex);
    ASSERT_EQ(four.size(), 4U);
    std::string reason;
    EXPECT_TRUE(forced(pyramid, four, fillet(1), &reason).isNull());
    EXPECT_NE(reason.find("4 edges meet"), std::string::npos) << reason;
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

// A plan angle other than 90 degrees at the unequal corners (PR 285 verification, F1): the two
// strips overlap in a parallelogram of area w_a w_b / sin(phi), and the tools' common volume
// carries the same factor.

namespace
{

/// A slab t thick over a convex footprint (counterclockwise), its wall i (from foot[i] to
/// foot[i + 1]) leaning in from its bottom edge by lean[i] degrees (out if negative)
TopoDS_Shape leaningSlab(const std::vector<gp_XY>& foot, double t, const std::vector<double>& lean)
{
    double xmin = foot[0].X();
    double xmax = xmin;
    double ymin = foot[0].Y();
    double ymax = ymin;
    for (const auto& p : foot) {
        xmin = std::min(xmin, p.X());
        xmax = std::max(xmax, p.X());
        ymin = std::min(ymin, p.Y());
        ymax = std::max(ymax, p.Y());
    }
    double margin = 3 * t + 10;
    TopoDS_Shape shape = box(
        xmax - xmin + 2 * margin,
        ymax - ymin + 2 * margin,
        t,
        gp_Pnt(xmin - margin, ymin - margin, 0)
    );
    for (size_t i = 0; i < foot.size(); ++i) {
        gp_XY along = (foot[(i + 1) % foot.size()] - foot[i]).Normalized();
        double beta = lean[i] * pi / 180;
        gp_Dir normal(along.Y() * std::cos(beta), -along.X() * std::cos(beta), std::sin(beta));
        gp_Pnt at(foot[i].X(), foot[i].Y(), 0);
        shape = BRepAlgoAPI_Cut(shape, beyondPlane(at, normal, 100)).Shape();
    }
    return shape;
}

/// The part of the convex polygon where normal . p <= c
std::vector<gp_XY> clipped(const std::vector<gp_XY>& polygon, const gp_XY& normal, double c)
{
    std::vector<gp_XY> result;
    for (size_t i = 0; i < polygon.size(); ++i) {
        const gp_XY& p = polygon[i];
        const gp_XY& q = polygon[(i + 1) % polygon.size()];
        double fp = normal.Dot(p) - c;
        double fq = normal.Dot(q) - c;
        if (fp <= 0) {
            result.push_back(p);
        }
        if ((fp < 0 && fq > 0) || (fq < 0 && fp > 0)) {
            result.push_back(p + (q - p) * (fp / (fp - fq)));
        }
    }
    return result;
}

double polygonArea(const std::vector<gp_XY>& polygon)
{
    double twice = 0.0;
    for (size_t i = 0; i < polygon.size(); ++i) {
        twice += polygon[i].Crossed(polygon[(i + 1) % polygon.size()]);
    }
    return std::abs(twice) / 2;
}

/** What a dress-up of all the top edges of leaningSlab() removes, by slices parallel to the top
 * at the depth z (plateTopRemoved() for any convex footprint; the verification's polygon slice
 * integral). A slice is the top polygon with each side z cot(alpha) further in, and it loses a
 * band w(z) along each side; the slices come from clipping a large square by the sides' lines.
 * Pure plane geometry: nothing of the construction's tools, overlaps or plan angles.
 */
double slabTopRemoved(
    bool isFillet,
    const std::vector<gp_XY>& foot,
    double t,
    const std::vector<double>& lean,
    double size
)
{
    struct Wall
    {
        gp_XY normal;  // outward, in the plane
        double top;    // normal . p of the top's side
        double beta;   // the lean
        double alpha;  // the dihedral angle at the top edge
    };
    std::vector<Wall> walls;
    for (size_t i = 0; i < foot.size(); ++i) {
        gp_XY along = (foot[(i + 1) % foot.size()] - foot[i]).Normalized();
        gp_XY normal(along.Y(), -along.X());
        double beta = lean[i] * pi / 180;
        walls.push_back({normal, normal.Dot(foot[i]) - t * std::tan(beta), beta, pi / 2 + beta});
    }
    auto sliceArea = [&](double z, const std::vector<double>& width) {
        std::vector<gp_XY> polygon {{-1e4, -1e4}, {1e4, -1e4}, {1e4, 1e4}, {-1e4, 1e4}};
        for (size_t i = 0; i < walls.size() && !polygon.empty(); ++i) {
            double c = walls[i].top + z * std::tan(walls[i].beta) - width[i];
            polygon = clipped(polygon, walls[i].normal, c);
        }
        return polygonArea(polygon);
    };
    std::vector<double> none(walls.size(), 0.0);
    std::vector<double> ends {0.0};
    double last = 0.0;
    std::function<double(double)> slice;
    if (isFillet) {
        last = std::acos(std::max(-1.0, 1 - t / size));
        for (const auto& wall : walls) {
            ends.push_back(std::clamp(pi - wall.alpha, 0.0, last));
        }
        slice = [&](double theta) {
            double z = size * (1 - std::cos(theta));
            std::vector<double> width;
            for (const auto& wall : walls) {
                width.push_back(
                    theta <= pi - wall.alpha ? size / std::tan(wall.alpha / 2)
                            - size * std::sin(theta) - z / std::tan(wall.alpha)
                                             : 0.0
                );
            }
            return (sliceArea(z, none) - sliceArea(z, width)) * size * std::sin(theta);
        };
    }
    else {
        last = t;
        for (const auto& wall : walls) {
            ends.push_back(std::min(size * std::sin(wall.alpha), t));
        }
        slice = [&](double z) {
            std::vector<double> width;
            for (const auto& wall : walls) {
                width.push_back(
                    z <= size * std::sin(wall.alpha) ? size - z / std::sin(wall.alpha) : 0.0
                );
            }
            return sliceArea(z, none) - sliceArea(z, width);
        };
    }
    ends.push_back(last);
    std::sort(ends.begin(), ends.end());
    // The slice area has kinks where a slice's polygon changes its corners: many short pieces
    constexpr int pieces = 200;
    double total = 0.0;
    for (size_t i = 0; i + 1 < ends.size(); ++i) {
        double step = (ends[i + 1] - ends[i]) / pieces;
        for (int k = 0; step > 0 && k < pieces; ++k) {
            total += gaussLegendre(slice, ends[i] + k * step, ends[i] + (k + 1) * step, 16);
        }
    }
    return total;
}

/// The limits where the thinnest wall vanishes: r = t / (1 + cos alpha), d = t / sin alpha
double filletLimit(double t, const std::vector<double>& lean)
{
    double limit = std::numeric_limits<double>::max();
    for (double degrees : lean) {
        limit = std::min(limit, t / (1 + std::cos(pi / 2 + degrees * pi / 180)));
    }
    return limit;
}

double chamferLimit(double t, const std::vector<double>& lean)
{
    double limit = std::numeric_limits<double>::max();
    for (double degrees : lean) {
        limit = std::min(limit, t / std::sin(pi / 2 + degrees * pi / 180));
    }
    return limit;
}

}  // namespace

TEST_F(FilletFallbackTest, unequalCornersAtOtherPlanAngles)
{
    // The 60 degree parallelogram 30 x 15 (walls leaning 0, 20 out, 25 in, 0), and the triangle
    // with corners of 60, 80 and 40 degrees on a 40 mm side (walls leaning 20 out, 10 in, 30 in),
    // 4 thick: all top edges at the limit, where the wall leaning out vanishes, against the slice
    // integral; and the forced construction equal to OCCT below it
    double c60 = std::cos(pi / 3);
    double s60 = std::sin(pi / 3);
    double side = 40 * std::sin(2 * pi / 9) / std::sin(4 * pi / 9);
    std::vector<std::pair<std::vector<gp_XY>, std::vector<double>>> slabs {
        {{{0, 0}, {30, 0}, {30 + 15 * c60, 15 * s60}, {15 * c60, 15 * s60}}, {0, -20, 25, 0}},
        {{{0, 0}, {40, 0}, {side * c60, side * s60}}, {-20, 10, 30}}
    };
    for (const auto& [foot, lean] : slabs) {
        TopoShape slab(leaningSlab(foot, 4, lean), 1L);
        auto top = edgesWhere(slab, atHeight(4));
        ASSERT_EQ(top.size(), foot.size());
        double plate = volume(slab.getShape());
        double r = filletLimit(4, lean);
        double d = chamferLimit(4, lean);
        ASSERT_TRUE(occtFails(slab, top, fillet(r))) << foot.size();
        EXPECT_TRUE(exact(dressUp(slab, top, fillet(r)), plate - slabTopRemoved(true, foot, 4, lean, r)))
            << foot.size();
        ASSERT_TRUE(occtFails(slab, top, chamfer(d))) << foot.size();
        EXPECT_TRUE(
            exact(dressUp(slab, top, chamfer(d)), plate - slabTopRemoved(false, foot, 4, lean, d))
        ) << foot.size();
        EXPECT_TRUE(sameAsOcct(slab, top, fillet(0.9 * r))) << foot.size();
        EXPECT_TRUE(sameAsOcct(slab, top, chamfer(0.9 * d))) << foot.size();
    }
}

// A face of zero width in OCCT's result (ops#298): OCCT succeeds where the dress-up consumes a
// face whole if the face shrinks to a line that the dress-up doesn't run along (the stadium's
// top), and keeps the face with area 0. Near the limit it leaves slivers narrower than their own
// tolerance. makeElementFillet / makeElementChamfer send both to the exact construction.

namespace
{

/// OCCT's fillet as makeElementFillet builds it (start and end radius), without the exact
/// construction
TopoDS_Shape occtFillet(const TopoShape& base, const std::vector<TopoShape>& edges, double r)
{
    BRepFilletAPI_MakeFillet maker(base.getShape());
    for (const auto& e : edges) {
        maker.Add(r, r, TopoDS::Edge(e.getShape()));
    }
    maker.Build();
    return maker.IsDone() ? maker.Shape() : TopoDS_Shape();
}

double faceArea(const TopoDS_Shape& face)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(face, props);
    return props.Mass();
}

/// stadium() as a box fused with two cylinders, unified: the half circle at x = 20 is split in
/// two at its cylinder's seam (22, 2), a vertex of two edges on two faces
TopoDS_Shape fusedStadium()
{
    // As Python's box.fuse([cylinder, cylinder]).removeSplitter()
    TopoShape fused;
    fused.makeElementBoolean(
        OpCodes::Fuse,
        {TopoShape(box(20, 4, 3)),
         TopoShape(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 2, 0), gp::DZ()), 2, 3).Shape()),
         TopoShape(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(20, 2, 0), gp::DZ()), 2, 3).Shape())}
    );
    return fused.removeSplitter();
}

}  // namespace

TEST_F(FilletFallbackTest, thinFacesOfOcctsResult)
{
    // The fused stadium's whole top outline at r = 2: OCCT keeps the top face with area 0
    TopoShape stadiumPlate(fusedStadium(), 1L);
    auto outline = edgesWhere(stadiumPlate, atHeight(3));
    TopoDS_Shape occt = occtFillet(stadiumPlate, outline, 2);
    ASSERT_FALSE(occt.IsNull());
    EXPECT_TRUE(BRepCheck_Analyzer(occt).IsValid());
    TopoDS_Face thin = FF::thinFace(occt, stadiumPlate.getShape());
    ASSERT_FALSE(thin.IsNull());
    EXPECT_LT(faceArea(thin), 1e-12);
    // The base's own faces aren't looked at
    EXPECT_TRUE(FF::thinFace(stadiumPlate.getShape(), stadiumPlate.getShape()).IsNull());

    // The full round of the 4 mm top: just below r = 2 OCCT leaves a sliver 2 (2 - r) wide, as
    // wide as it should be. Narrower than its edges' tolerance (1e-7) it is thin; from 2e-7 on
    // it is a face OCCT built correctly
    TopoShape rib(box(30, 4, 20), 1L);
    std::vector<TopoShape> pair {
        edgeBetween(rib, {0, 0, 20}, {30, 0, 20}),
        edgeBetween(rib, {0, 4, 20}, {30, 4, 20})
    };
    for (double gap : {1e-9, 1e-8}) {
        occt = occtFillet(rib, pair, 2 - gap);
        ASSERT_FALSE(occt.IsNull()) << gap;
        EXPECT_FALSE(FF::thinFace(occt, rib.getShape()).IsNull()) << gap;
    }
    for (double gap : {1e-7, 1e-5, 1e-3}) {
        occt = occtFillet(rib, pair, 2 - gap);
        ASSERT_FALSE(occt.IsNull()) << gap;
        EXPECT_TRUE(FF::thinFace(occt, rib.getShape()).IsNull()) << gap;
        EXPECT_EQ(count(occt, TopAbs_FACE), 8) << gap;
    }
}

TEST_F(FilletFallbackTest, wholeOutlineOfAStadium)
{
    // The stadium's whole top outline at r = w / 2 and d = w / 2. On the fused stadium OCCT
    // "succeeds", keeping the top face with area 0 (11 faces), down to r = 2 - 1e-8; on the
    // extruded one its result is invalid. makeElementFillet / makeElementChamfer build the full
    // round and the ridge exactly instead: the straight edges' tools meet the half circles' (a
    // sphere for the fillet, a cone for the chamfer) by tangent continuation, also across the
    // fused stadium's seam vertex: 9 faces, 10 with the half circle in two
    double plate = 20 * 4 * 3 + pi * 4 * 3;
    auto rounded = [&](double r) {
        double c = filletCentroid(r);
        return plate - 2 * filletSection(r) * 20 - 2 * pi * (2 - c) * filletSection(r);
    };
    for (const auto& [shape, faces] :
         std::vector<std::pair<TopoDS_Shape, int>> {{stadium(), 9}, {fusedStadium(), 10}}) {
        TopoShape base(shape, 1L);
        auto top = edgesWhere(base, atHeight(3));
        ASSERT_EQ(top.size(), faces - 5);
        TopoShape round = dressUp(base, top, fillet(2));
        EXPECT_TRUE(exact(round, rounded(2))) << faces;
        EXPECT_TRUE(FF::thinFace(round.getShape(), base.getShape()).IsNull()) << faces;
        EXPECT_EQ(round.countSubElements("Face"), faces);
        TopoShape ridge = dressUp(base, top, chamfer(2));
        EXPECT_TRUE(exact(ridge, plate - 2 * 2 * 20 - 2 * pi * (2 - 2.0 / 3) * 2)) << faces;
        EXPECT_TRUE(FF::thinFace(ridge.getShape(), base.getShape()).IsNull()) << faces;
        EXPECT_EQ(ridge.countSubElements("Face"), faces);
    }
    // Just below: OCCT's face of area 0 at 2 - 1e-8 is built exactly; its sliver 2e-7 wide at
    // 2 - 1e-7 is a face OCCT built correctly, and stays
    TopoShape base(fusedStadium(), 1L);
    auto top = edgesWhere(base, atHeight(3));
    TopoShape round = dressUp(base, top, fillet(2 - 1e-8));
    EXPECT_TRUE(exact(round, rounded(2 - 1e-8)));
    EXPECT_EQ(round.countSubElements("Face"), 10);
    round = dressUp(base, top, fillet(2 - 1e-7));
    EXPECT_TRUE(exact(round, rounded(2 - 1e-7)));
    EXPECT_EQ(round.countSubElements("Face"), 11);
    EXPECT_TRUE(FF::thinFace(round.getShape(), base.getShape()).IsNull());
}

TEST_F(FilletFallbackTest, recorderReportsWhatTheConstructionBuilt)
{
    // The feature's Report-view line (decision 54): nothing where OCCT built the dress-up; the
    // edges and the corners where the exact construction did, in the innermost recorder
    TopoShape cube(box(4, 4, 4), 1L);
    auto all = cube.getSubTopoShapes(TopAbs_EDGE);
    ASSERT_EQ(all.size(), 12);
    FF::Recorder outer;
    {
        FF::Recorder recorder;
        dressUp(cube, all, fillet(1.9));
        EXPECT_FALSE(recorder.built());
        EXPECT_EQ(recorder.report("Fillet"), "");
    }
    {
        FF::Recorder recorder;
        dressUp(cube, all, fillet(2));
        EXPECT_TRUE(recorder.built());
        EXPECT_EQ(
            recorder.report("Fillet"),
            "Fillet: built by the exact construction where OCCT failed: 12 edges, 8 corners"
        );
    }
    EXPECT_FALSE(outer.built());
    TopoShape rib(box(30, 4, 20), 1L);
    std::vector<TopoShape> pair {
        edgeBetween(rib, {0, 0, 20}, {30, 0, 20}),
        edgeBetween(rib, {0, 4, 20}, {30, 4, 20})
    };
    dressUp(rib, pair, chamfer(2));
    EXPECT_EQ(
        outer.report("Chamfer"),
        "Chamfer: built by the exact construction where OCCT failed: 2 edges, 0 corners"
    );
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
