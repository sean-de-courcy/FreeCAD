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
#include <set>
#include <sstream>
#include <gtest/gtest.h>

#include "src/App/InitApplication.h"
#include <App/ElementNamingUtils.h>
#include <Base/Exception.h>
#include <Mod/Part/App/FilletFallback.h>
#include <Mod/Part/App/MassProperties.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_GTransform.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <GProp_GProps.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <StdFail_NotDone.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopoDS.hxx>
#include <gp.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>
#include <gp_Elips.hxx>
#include <gp_GTrsf.hxx>
#include <gp_Mat.hxx>
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

/// A chamfer by equal distances w over a chain whose angles differ is OCCT's with the setbacks
/// (notes/chamfer-chain-setbacks.md): the same solid with the same faces as OCCT given the
/// expected setbacks directly. Where OCCT fails with them, the construction refuses the corner
/// between setbacks that differ and builds w on every edge instead (ruling A, section 7).
testing::AssertionResult sameAsOcctWithSetbacks(
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    double w,
    const std::vector<double>& expected
)
{
    auto setbacks = FF::chainSetbacks(base, edges, w);
    if (setbacks.size() != expected.size()) {
        return testing::AssertionFailure() << setbacks.size() << " setbacks";
    }
    for (std::size_t i = 0; i < expected.size(); ++i) {
        if (std::abs(setbacks[i] - expected[i]) > 1e-9) {
            return testing::AssertionFailure()
                << "setback " << i << " " << setbacks[i] << " != " << expected[i];
        }
    }
    TopoShape result = dressUp(base, edges, chamfer(w));
    BRepFilletAPI_MakeChamfer maker(base.getShape());
    for (std::size_t i = 0; i < edges.size(); ++i) {
        const auto& edge = TopoDS::Edge(edges[i].getShape());
        auto face = TopoDS::Face(base.findAncestorShape(edge, TopAbs_FACE));
        maker.Add(expected[i], expected[i], edge, face);
    }
    bool built = false;
    try {
        maker.Build();
        built = maker.IsDone() && BRepCheck_Analyzer(maker.Shape()).IsValid();
    }
    catch (const Standard_Failure&) {
        built = false;
    }
    if (!built) {
        FF::Request uniform = chamfer(w);
        uniform.limitOnly = false;
        return sameAs(forced(base, edges, uniform), result);
    }
    const auto& a = result.getShape();
    const TopoDS_Shape& b = maker.Shape();
    if (a.IsNull()) {
        return testing::AssertionFailure() << "null shape";
    }
    double difference
        = volume(BRepAlgoAPI_Cut(a, b).Shape()) + volume(BRepAlgoAPI_Cut(b, a).Shape());
    if (difference > 1e-7 * volume(b)) {
        return testing::AssertionFailure() << "symmetric difference " << difference;
    }
    if (count(a, TopAbs_FACE) != count(b, TopAbs_FACE)) {
        return testing::AssertionFailure()
            << count(a, TopAbs_FACE) << " faces != " << count(b, TopAbs_FACE);
    }
    return testing::AssertionSuccess();
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

// A concave straight edge between a wall and a boss fused to it, a cylinder along the edge: the
// ball of its round lies in the air, in front of the wall and outside the boss (ops#640, Case Base
// #47: the construction put it in the material, in the boss, and refused). Below the limit, forced,
// it is OCCT's round
TEST_F(FilletFallbackTest, concaveRoundOfAWallAndABoss)
{
    BRepAlgoAPI_Fuse fuse(
        box(20, 10, 10, gp_Pnt(0, -10, 0)),
        BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(10, 2, 0), gp::DZ()), 5, 10).Shape()
    );
    ShapeUpgrade_UnifySameDomain unify(fuse.Shape());
    unify.Build();
    TopoShape base(unify.Shape(), 1L);
    double x = 10 + std::sqrt(21.0);
    std::vector<TopoShape> edges {edgeBetween(base, {x, 0, 0}, {x, 0, 10})};
    EXPECT_TRUE(sameAsOcct(base, edges, fillet(2)));
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
    // OCCT's own maker, on the base: makeElementChamfer runs it on a copy (ops#345)
    BRepFilletAPI_MakeChamfer occt(base.getShape());
    occt.Add(2 - 1e-5, TopoDS::Edge(edges.front().getShape()));
    occt.Add(2 - 1e-5, TopoDS::Edge(edgeBetween(base, {0, 4, 20}, {30, 4, 20}).getShape()));
    occt.Build();
    ASSERT_TRUE(occt.IsDone());
    ASSERT_GT(largest(), 1e-5);
    FF::Request request = chamfer(4 - 2e-7);
    request.limitOnly = false;
    request.faceTolerances = before;
    std::string reason;
    EXPECT_TRUE(forced(base, edges, request, &reason).isNull());
    EXPECT_NE(reason.find("tolerance grew"), std::string::npos) << reason;
}

namespace
{
/// The rib 30 x 4 x 20 against a wall 5 x 24 x 20 as high as it, with its two top edges
TopoShape ribAgainstWall(std::vector<TopoShape>& topEdges)
{
    BRepAlgoAPI_Fuse fuse(box(30, 4, 20), box(5, 24, 20, gp_Pnt(-5, -10, 0)));
    ShapeUpgrade_UnifySameDomain unify(fuse.Shape());
    unify.Build();
    TopoShape rib(unify.Shape(), 1L);
    topEdges = {edgeBetween(rib, {0, 0, 20}, {30, 0, 20}), edgeBetween(rib, {0, 4, 20}, {30, 4, 20})};
    return rib;
}

/// The largest tolerance of the shape's faces, edges and vertices
double largestTolerance(const TopoDS_Shape& shape)
{
    double tolerance = 0;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Face(it.Current())));
    }
    for (TopExp_Explorer it(shape, TopAbs_EDGE); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Edge(it.Current())));
    }
    for (TopExp_Explorer it(shape, TopAbs_VERTEX); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Vertex(it.Current())));
    }
    return tolerance;
}

/// The shape's element map as (indexed name, mapped name) pairs
std::set<std::pair<std::string, std::string>> elementNames(const TopoShape& shape)
{
    std::set<std::pair<std::string, std::string>> names;
    for (const auto& element : shape.getElementMap()) {
        names.emplace(element.index.toString(), element.name.toString());
    }
    return names;
}

/// The rib against the wall named as a feature's shape is: the fuse's and refine's element map
TopoShape namedRibAgainstWall(std::vector<TopoShape>& topEdges)
{
    TopoShape rib(1L);
    rib.makeElementFuse(
        {TopoShape(box(30, 4, 20), 2L), TopoShape(box(5, 24, 20, gp_Pnt(-5, -10, 0)), 3L)}
    );
    rib = rib.makeElementRefine();
    topEdges = {edgeBetween(rib, {0, 0, 20}, {30, 0, 20}), edgeBetween(rib, {0, 4, 20}, {30, 4, 20})};
    return rib;
}

/// Each face's, edge's and vertex's tolerance, in the order of the shape's indexed names
std::vector<double> tolerancesByIndex(const TopoDS_Shape& shape)
{
    std::vector<double> tolerances;
    for (const TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        TopTools_IndexedMapOfShape map;
        TopExp::MapShapes(shape, type, map);
        for (int i = 1; i <= map.Extent(); ++i) {
            const TopoDS_Shape& sub = map(i);
            tolerances.push_back(
                type == TopAbs_FACE ? BRep_Tool::Tolerance(TopoDS::Face(sub))
                    : type == TopAbs_EDGE ? BRep_Tool::Tolerance(TopoDS::Edge(sub))
                                          : BRep_Tool::Tolerance(TopoDS::Vertex(sub))
            );
        }
    }
    return tolerances;
}

/// Whether any face, edge or vertex of the one shape is one of the other's (the same TShape)
bool sharesTopology(const TopoDS_Shape& shape, const TopoDS_Shape& other)
{
    for (const TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        TopTools_IndexedMapOfShape map;
        TopExp::MapShapes(other, type, map);
        for (TopExp_Explorer it(shape, type); it.More(); it.Next()) {
            for (int i = 1; i <= map.Extent(); ++i) {
                if (it.Current().IsPartner(map(i))) {
                    return true;
                }
            }
        }
    }
    return false;
}

/// The loft from the circle r 10 at z 0 to the ellipse 12 x 6 at z 15 (a B-spline side face)
TopoShape loftedSolid()
{
    BRepOffsetAPI_ThruSections loft(Standard_True);
    const gp_Ax2 bottom(gp_Pnt(0, 0, 0), gp::DZ(), gp::DX());
    const gp_Ax2 top(gp_Pnt(0, 0, 15), gp::DZ(), gp::DX());
    loft.AddWire(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(bottom, 10)).Edge()).Wire());
    loft.AddWire(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Elips(top, 12, 6)).Edge()).Wire());
    loft.Build();
    return TopoShape(loft.Shape(), 1L);
}

/// The loft's side face
TopoShape loftSide(const TopoShape& loft)
{
    for (const auto& face : loft.getSubTopoShapes(TopAbs_FACE)) {
        if (BRepAdaptor_Surface(TopoDS::Face(face.getShape())).GetType() != GeomAbs_Plane) {
            return face;
        }
    }
    ADD_FAILURE() << "no side face";
    return {};
}

/// The square 4 x 4 in the plane x = 22, beside the loft's +x side, its top `gap` under z = 15
TopoShape squareBesideTheLoft(double gap)
{
    const double z1 = 15 - gap;
    BRepBuilderAPI_MakePolygon square(
        gp_Pnt(22, -2, z1 - 4),
        gp_Pnt(22, 2, z1 - 4),
        gp_Pnt(22, 2, z1),
        gp_Pnt(22, -2, z1),
        Standard_True
    );
    return TopoShape(BRepBuilderAPI_MakeFace(square.Wire(), Standard_True).Face(), 2L);
}
}  // namespace

// OCCT's maker raises its input's tolerances in place, to 1e-4 at the vertices where the rib's
// chamfers or rounds end against the wall, and a dress-up's base shares its TShapes with the
// base feature's stored Shape. The maker runs on a copy (makerInput()): the base keeps its
// tolerances, and the result keeps those the maker raised (ops#345)
TEST_F(FilletFallbackTest, leavesTheBaseTolerancesAlone)
{
    for (const auto& request : {chamfer(2 - 1e-5), chamfer(1.5), fillet(2 - 1e-5), fillet(1.5)}) {
        std::vector<TopoShape> edges;
        TopoShape base = ribAgainstWall(edges);
        const double before = largestTolerance(base.getShape());
        ASSERT_LT(before, 1e-6);
        TopoShape result = dressUp(base, edges, request);
        ASSERT_FALSE(result.isNull());
        EXPECT_TRUE(result.isValid());
        EXPECT_EQ(largestTolerance(base.getShape()), before) << request.size1;
        EXPECT_GT(largestTolerance(result.getShape()), 1e-5) << request.size1;
    }
}

// A second dress-up on the same base sees the base's own tolerances: the check for merged faces
// takes its thresholds (Request::faceTolerances) from them, not from what the first maker raised
// (ops#345; PR 314 review, item 2)
TEST_F(FilletFallbackTest, aSecondDressUpSeesTheBaseTolerances)
{
    std::vector<TopoShape> edges;
    TopoShape base = ribAgainstWall(edges);
    const auto before = FF::faceTolerances(base.getShape());
    TopoShape first = dressUp(base, edges, chamfer(2 - 1e-5));
    ASSERT_FALSE(first.isNull());
    const auto after = FF::faceTolerances(base.getShape());
    ASSERT_EQ(after.Extent(), before.Extent());
    for (TopTools_DataMapOfShapeReal::Iterator it(before); it.More(); it.Next()) {
        ASSERT_TRUE(after.IsBound(it.Key()));
        EXPECT_EQ(after.Find(it.Key()), it.Value());
    }
    TopoShape second = dressUp(base, edges, chamfer(2 - 1e-5));
    ASSERT_FALSE(second.isNull());
    EXPECT_EQ(largestTolerance(second.getShape()), largestTolerance(first.getShape()));
}

// The copy keeps the base's element map and Tag: the result is named as by OCCT's maker on the
// base itself
TEST_F(FilletFallbackTest, theCopyNamesAsTheBase)
{
    std::vector<TopoShape> edges;
    TopoShape base = ribAgainstWall(edges);
    TopoShape result(2L);
    result.makeElementChamfer(base, edges, ChamferType::equalDistance, 1.5, 1.5);

    std::vector<TopoShape> otherEdges;
    TopoShape other = ribAgainstWall(otherEdges);
    BRepFilletAPI_MakeChamfer occt(other.getShape());
    for (const auto& edge : otherEdges) {
        const auto& e = TopoDS::Edge(edge.getShape());
        occt.Add(1.5, 1.5, e, TopoDS::Face(other.findAncestorShape(e, TopAbs_FACE)));
    }
    occt.Build();
    ASSERT_TRUE(occt.IsDone());
    TopoShape expected(2L);
    expected.makeElementShape(occt, other, OpCodes::Chamfer);

    EXPECT_FALSE(elementNames(result).empty());
    EXPECT_EQ(elementNames(result), elementNames(expected));
}

// The same with a base named as a feature's shape is: the result's names come from the base's
// element map through the copy, as OCCT's maker on the base itself gives them (PR 318 review, low 1)
TEST_F(FilletFallbackTest, theCopyNamesAsTheBaseWithItsElementMap)
{
    std::vector<TopoShape> edges;
    TopoShape base = namedRibAgainstWall(edges);
    ASSERT_FALSE(base.getElementMap().empty());
    TopoShape result(4L);
    result.makeElementChamfer(base, edges, ChamferType::equalDistance, 1.5, 1.5);

    std::vector<TopoShape> otherEdges;
    TopoShape other = namedRibAgainstWall(otherEdges);
    BRepFilletAPI_MakeChamfer occt(other.getShape());
    for (const auto& edge : otherEdges) {
        const auto& e = TopoDS::Edge(edge.getShape());
        occt.Add(1.5, 1.5, e, TopoDS::Face(other.findAncestorShape(e, TopAbs_FACE)));
    }
    occt.Build();
    ASSERT_TRUE(occt.IsDone());
    TopoShape expected(4L);
    expected.makeElementShape(occt, other, OpCodes::Chamfer);
    EXPECT_EQ(elementNames(result), elementNames(expected));

    // Not the names an unnamed base gives: the base's own names reach the result
    std::vector<TopoShape> plainEdges;
    TopoShape plain = ribAgainstWall(plainEdges);
    TopoShape plainResult(4L);
    plainResult.makeElementChamfer(plain, plainEdges, ChamferType::equalDistance, 1.5, 1.5);
    EXPECT_NE(elementNames(result), elementNames(plainResult));
}

// The maker's copy has the base's tolerances, sub-shape by sub-shape, in new TShapes: the checks
// that read them (Request::faceTolerances) see the base's own (PR 318 review, low 2)
TEST_F(FilletFallbackTest, theCopyHasTheBaseTolerances)
{
    std::vector<TopoShape> edges;
    TopoShape base = ribAgainstWall(edges);
    // Tolerances that differ between the sub-shapes, as a base built by other features has them
    BRep_Builder builder;
    const auto& edge = TopoDS::Edge(edges[0].getShape());
    builder.UpdateEdge(edge, 3e-6);
    builder.UpdateVertex(TopExp::FirstVertex(edge), 5e-6);
    std::vector<TopoShape> inputEdges = edges;
    const TopoShape input = FF::makerInput(base, inputEdges);
    EXPECT_EQ(tolerancesByIndex(input.getShape()), tolerancesByIndex(base.getShape()));
    EXPECT_FALSE(sharesTopology(input.getShape(), base.getShape()));
    EXPECT_EQ(input.Tag, base.Tag);
    ASSERT_EQ(inputEdges.size(), edges.size());
    for (std::size_t i = 0; i < edges.size(); ++i) {
        EXPECT_EQ(input.findShape(inputEdges[i].getShape()), base.findShape(edges[i].getShape()));
    }
}

// makerInputs() copies several inputs together: an up-to face of the base is a face of the base's
// copy, a face of another shape gets its own copy, and each copy keeps its shape's tolerances,
// element map and Tag (ops#347)
TEST_F(FilletFallbackTest, theInputsAreCopiedTogether)
{
    std::vector<TopoShape> edges;
    TopoShape base = namedRibAgainstWall(edges);
    const TopoShape top = TopoShape(base.findAncestorShape(edges[0].getShape(), TopAbs_FACE), 5L);
    const TopoShape other(
        BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 40), gp::DZ()), 0, 1, 0, 1).Face(),
        6L
    );
    const auto copies = FF::makerInputs({base, TopoShape(), top, other});
    ASSERT_EQ(copies.size(), 4U);
    EXPECT_TRUE(copies[1].isNull());
    EXPECT_EQ(tolerancesByIndex(copies[0].getShape()), tolerancesByIndex(base.getShape()));
    EXPECT_EQ(elementNames(copies[0]), elementNames(base));
    EXPECT_EQ(copies[0].Tag, base.Tag);
    EXPECT_EQ(copies[2].Tag, 5L);
    EXPECT_EQ(copies[3].Tag, 6L);
    for (const auto& copy : {copies[0], copies[2], copies[3]}) {
        EXPECT_FALSE(sharesTopology(copy.getShape(), base.getShape()));
        EXPECT_FALSE(sharesTopology(copy.getShape(), other.getShape()));
    }
    // The base's face is the copy's face of the same index
    EXPECT_EQ(copies[0].findShape(copies[2].getShape()), base.findShape(top.getShape()));
    EXPECT_GT(copies[0].findShape(copies[2].getShape()), 0);
    EXPECT_EQ(copies[0].findShape(copies[3].getShape()), 0);
}

// BRepFeat up to a face raises the tolerances of what the prism meets in place: with the square's
// top 1e-6 under the loft's top edge, that edge and its vertex went from 1e-7 to 5e-6, and the
// loft is a Pad's base, shared with the base feature's stored shape. The prism is built from
// copies: the base and the up-to face keep their tolerances (ops#347)
TEST_F(FilletFallbackTest, prismUpToAFaceLeavesItsInputsAlone)
{
    // A Pad's call (the base given), a Pocket's (no base: the up-to face alone is the loft's), and
    // the fuse with the base done here
    for (const auto& [additive, mode] : std::vector<std::pair<bool, TopoShape::PrismMode>> {
             {true, TopoShape::PrismMode::None},
             {false, TopoShape::PrismMode::None},
             {true, TopoShape::PrismMode::FuseWithBase}
         }) {
        const TopoShape loft = loftedSolid();
        const TopoShape side = loftSide(loft);
        const TopoShape square = squareBesideTheLoft(1e-6);
        const auto loftBefore = tolerancesByIndex(loft.getShape());
        const auto squareBefore = tolerancesByIndex(square.getShape());
        TopoShape prism(3L);
        prism.makeElementPrismUntil(
            additive ? loft : TopoShape(),
            square,
            TopoShape(),
            side,
            gp_Dir(-1, 0, 0),
            mode,
            Standard_True
        );
        ASSERT_FALSE(prism.isNull());
        EXPECT_TRUE(prism.isValid());
        EXPECT_EQ(tolerancesByIndex(loft.getShape()), loftBefore) << additive << mode;
        EXPECT_EQ(tolerancesByIndex(square.getShape()), squareBefore) << additive << mode;
        // Nothing the prism holds is the inputs': a later maker can't reach them through it
        EXPECT_FALSE(sharesTopology(prism.getShape(), loft.getShape())) << additive << mode;
    }
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
        EXPECT_TRUE(sameAsOcct(plate, top, fillet(degrees < 0 ? 2 : 3.9))) << degrees;
        // Chamfers by equal distances: the chain's first edge gets w, every other edge
        // w tan(a1 / 2) / tan(a / 2), where the top meets the walls at 90 degrees and the
        // leaning end at 90 + degrees (notes/chamfer-chain-setbacks.md section 4)
        auto angleOf = [&](const TopoShape& edge) {
            TopoDS_Vertex v1;
            TopoDS_Vertex v2;
            TopExp::Vertices(TopoDS::Edge(edge.getShape()), v1, v2);
            bool leaning = std::abs(BRep_Tool::Pnt(v1).X() - a) < 1e-9
                && std::abs(BRep_Tool::Pnt(v2).X() - a) < 1e-9;
            return (leaning ? 90 + degrees : 90.0) * pi / 180;
        };
        auto setbacksOf = [&](const std::vector<TopoShape>& edges, double w) {
            std::vector<double> setbacks;
            for (const auto& edge : edges) {
                setbacks.push_back(
                    w * std::tan(angleOf(edges.front()) / 2) / std::tan(angleOf(edge) / 2)
                );
            }
            setbacks.front() = w;
            return setbacks;
        };
        double w = degrees < 0 ? 2 : 3.9;
        EXPECT_TRUE(sameAsOcctWithSetbacks(plate, two, 2, setbacksOf(two, 2))) << degrees;
        EXPECT_TRUE(sameAsOcctWithSetbacks(plate, top, w, setbacksOf(top, w))) << degrees;
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

/// The public function throws OCCT's StdFail_NotDone, with its message and why the exact
/// construction refused (ops#601): "BRep_API: command not done (exact construction refused:
/// <reason>)", the reason holding \a expected if given
testing::AssertionResult throwsOcctsError(
    const std::function<void()>& run,
    const char* expected = nullptr
)
{
    const std::string occts = "BRep_API: command not done";
    const std::string refused = " (exact construction refused: ";
    try {
        run();
    }
    catch (const StdFail_NotDone& e) {
        const std::string message = e.GetMessageString();
        if (message.rfind(occts + refused, 0) != 0 || message.back() != ')'
            || message.size() == occts.size() + refused.size() + 1) {
            return testing::AssertionFailure() << "message " << message;
        }
        if (expected && message.find(expected, occts.size()) == std::string::npos) {
            return testing::AssertionFailure() << "message without the reason: " << message;
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
    auto raised = throwsOcctsError([&] { dressUp(base, edges, request); }, expected);
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
        "runs past both its faces"
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
    // A15: the hexagon plate's edges chamfered: its corners aren't square. OCCT fails with the
    // setbacks too (vertical edges at 120 degrees, the others at 90), so the construction builds
    // w on every edge (ruling A, notes/chamfer-chain-setbacks.md section 7) and refuses that
    TopoShape hexagon(regularPlate(6), 1L);
    auto hexagonEdges = hexagon.getSubTopoShapes(TopAbs_EDGE);
    EXPECT_TRUE(refusedFor(hexagon, hexagonEdges, chamfer(2), "not square"));
    // The triangle plate's: OCCT fails with w, but builds with the setbacks (the chain's first
    // edge gets w, every other edge w tan(a1 / 2) / tan(a / 2); the vertical edges are at 60
    // degrees, the others at 90)
    TopoShape triangle(regularPlate(3), 1L);
    auto triangleEdges = triangle.getSubTopoShapes(TopAbs_EDGE);
    EXPECT_TRUE(occtFails(triangle, triangleEdges, chamfer(2)));
    auto angleOf = [](const TopoShape& edge) {
        TopoDS_Vertex v1;
        TopoDS_Vertex v2;
        TopExp::Vertices(TopoDS::Edge(edge.getShape()), v1, v2);
        bool vertical = std::abs(BRep_Tool::Pnt(v1).Z() - BRep_Tool::Pnt(v2).Z()) > 1;
        return (vertical ? 60.0 : 90.0) * pi / 180;
    };
    std::vector<double> setbacks;
    for (const auto& edge : triangleEdges) {
        setbacks.push_back(
            2 * std::tan(angleOf(triangleEdges.front()) / 2) / std::tan(angleOf(edge) / 2)
        );
    }
    setbacks.front() = 2;
    EXPECT_TRUE(sameAsOcctWithSetbacks(triangle, triangleEdges, 2, setbacks));
    EXPECT_TRUE(dressUp(triangle, triangleEdges, chamfer(2)).isValid());
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
    // Its corners are convex now (Corner2Union, ops#640). At r = t OCCT 8.0.1 fails, and its cut
    // of the first tool, which passes through the bottom vertex, measured 1e-3 off its common
    // part: the loops raised vertex tolerances open (ops#669), so the construction builds it
    // (batch 8 review). Four exact faces; the volume is the closed form's (the D's area times t,
    // less the integral over the D of max(distance to the line, distance to the arc)): 474.33880
    std::string why;
    TopoShape built = forced(dPlate, dTop, fillet(4), &why);
    ASSERT_FALSE(built.isNull()) << why;
    EXPECT_TRUE(built.isValid());
    EXPECT_EQ(count(built.getShape(), TopAbs_SOLID), 1);
    EXPECT_EQ(count(built.getShape(), TopAbs_FACE), 4);
    EXPECT_NEAR(volume(built.getShape()), 474.3388, 1e-3);
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

/** The area the rounds of radius r of count edges (1 or 2) remove from the section of a plate of
 * the width: at the depth r (1 - cos t) one round is r (1 - sin t) wide, the rounds together at
 * most the width. By Simpson's rule on each side of the kink, where the integrand is smooth */
double roundsSection(double r, double width, int count)
{
    auto f = [&](double t) {
        return std::min(width, count * r * (1 - std::sin(t))) * r * std::sin(t);
    };
    auto simpson = [&](double a, double b) {
        const int n = 2000;
        double h = (b - a) / n;
        double sum = f(a) + f(b);
        for (int i = 1; i < n; ++i) {
            sum += f(a + i * h) * (i % 2 ? 4 : 2);
        }
        return sum * h / 3;
    };
    double kink = std::asin(std::max(0.0, 1 - width / count / r));
    return simpson(0, kink) + simpson(kink, pi / 2);
}

TEST_F(FilletFallbackTest, overlappingToolsAsOnshape)
{
    // r = 2.1 on the rib 4 wide, 20 long: the two rounds overlap, and the result is the rib
    // without their union, as Onshape's (ops#640, S3; notes/onshape-facts.md K2E)
    TopoShape base(ribAgainstWall(), 1L);
    std::vector<TopoShape> edges {
        edgeBetween(base, {13, 0, 4}, {13, 20, 4}),
        edgeBetween(base, {17, 0, 4}, {17, 20, 4})
    };
    EXPECT_TRUE(exact(dressUp(base, edges, fillet(2.1)), 6000 + 320 - 20 * roundsSection(2.1, 4, 2)));
}

TEST_F(FilletFallbackTest, justOverTheLimitAsOnshape)
{
    // Past the limit the result is the plate without the tools' union (ops#640, S3; Onshape's
    // KP3, K2D, K2E). The plate's top is 4 wide
    TopoShape base(box(30, 4, 20), 1L);
    TopoShape front = edgeBetween(base, {0, 0, 20}, {30, 0, 20});
    TopoShape back = edgeBetween(base, {0, 4, 20}, {30, 4, 20});
    for (double r : {2.005, 2.01, 2.02}) {
        EXPECT_TRUE(exact(dressUp(base, {front, back}, fillet(r)), 2400 - 30 * roundsSection(r, 4, 2)))
            << r;
    }
    for (double r : {4.01, 4.02, 4.04}) {
        EXPECT_TRUE(exact(dressUp(base, {front}, fillet(r)), 2400 - 30 * roundsSection(r, 4, 1)))
            << r;
    }
    // Two chamfers meet in a ridge: d^2 less the overlap (2 d - 4)^2 / 4; one past the top: its
    // triangle less the part beyond the far side, (d - 4)^2 / 2
    for (double d : {2.001, 2.002}) {
        EXPECT_TRUE(exact(
            dressUp(base, {front, back}, chamfer(d)),
            2400 - 30 * (d * d - (2 * d - 4) * (2 * d - 4) / 4)
        )) << d;
    }
    double d = 4.002;
    EXPECT_TRUE(exact(dressUp(base, {front}, chamfer(d)), 2400 - 30 * (d * d - (d - 4) * (d - 4)) / 2));
    TopoShape sliver(box(0.01, 4, 20), 1L);
    TopoShape shortEdge = edgeBetween(sliver, {0, 0, 20}, {0.01, 0, 20});
    EXPECT_TRUE(exact(dressUp(sliver, {shortEdge}, chamfer(4)), 0.8 - 0.01 * 8));
    d = 4.0004;
    EXPECT_TRUE(exact(dressUp(sliver, {shortEdge}, chamfer(d)), 0.8 - 0.01 * (d * d - (d - 4) * (d - 4)) / 2));
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

TEST_F(FilletFallbackTest, trimsADressUpPastTheRisersFootByTheTread)
{
    // The step's convex edge (riser 4 high) with size 5: the strip on the riser runs 1 past its
    // foot, into the material under the tread. Onshape trims the dress-up by the tread's plane
    // run on under it: the tread grows, the riser is used up, no step is left (Q-LEDGE LD1-LD3,
    // notes/onshape-facts.md; S4 there is this case scaled: r 1 over a wall 0.5 high)
    TopoShape base(step(), 1L);
    TopoShape convex = edgeBetween(base, {0, 10, 14}, {30, 10, 14});
    // The round, centre (y 15, z 9): the material it keeps in y 10..15, z 10..14 is the quarter
    // disc above z = 10; it meets the tread at y = 15 - sqrt(24)
    double kept = 25 * pi / 4 - (std::sqrt(24.0) / 2 + 12.5 * std::asin(0.2));
    // The chamfer, from (15, 14) to (10, 9): its triangle less the part under the tread
    double chamfered = 12.5 - 0.5;
    struct Case
    {
        FF::Request request;
        double volume;
        double treadTo;
    };
    for (const auto& c : {Case {fillet(5), 7200 - (20 - kept) * 30, 15 - std::sqrt(24.0)},
                          Case {chamfer(5), 7200 - chamfered * 30, 11.0}}) {
        TopoShape result = forced(base, {convex}, c.request);
        EXPECT_TRUE(exact(result, c.volume));
        EXPECT_EQ(result.countSubElements("Face"), 8);
        // The tread: one plane face at z = 10, from y = 0 to where the dress-up meets it
        int treads = 0;
        for (const auto& face : result.getSubTopoShapes(TopAbs_FACE)) {
            Bnd_Box box;
            BRepBndLib::Add(face.getShape(), box);
            double xMin, yMin, zMin, xMax, yMax, zMax;
            box.Get(xMin, yMin, zMin, xMax, yMax, zMax);
            if (zMax - zMin < 1e-6 && std::abs(zMin - 10) < 1e-6) {
                ++treads;
                EXPECT_NEAR(yMin, 0.0, 1e-6);
                EXPECT_NEAR(yMax, c.treadTo, 1e-6);
            }
        }
        EXPECT_EQ(treads, 1);
    }
}

/// A closed B-spline through n points about the centre at height z: radius r + w cos(4 t), turned by
/// the angle
TopoDS_Wire wavyLoop(gp_Pnt centre, double r, double w, double turn)
{
    const int n = 16;
    Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, n);
    for (int i = 0; i < n; ++i) {
        double t = 2 * pi * i / n + turn;
        double rho = r + w * std::cos(4 * t);
        points->SetValue(i + 1, centre.Translated(gp_Vec(rho * std::cos(t), rho * std::sin(t), 0)));
    }
    GeomAPI_Interpolate curve(points, Standard_True, 1e-9);
    curve.Perform();
    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(curve.Curve()).Edge()).Wire();
}

/// Case Base #108's class, designed: a channel 2 deep (x < 10) beside a block 30 x 30 x 10, and a
/// finger notch, the cylinder r 4 about (10, 0) cut down to the channel's floor (z 8): its rim is a
/// half circle from (10, -4) to (10, 4), split at the cylinder's seam (14, 0). With freeForm, a
/// boss lofted between two wavy B-spline loops stands on the top, away from the notch: its side is
/// a B-spline surface, which OCCT's default volume integration doesn't get exactly
TopoDS_Shape fingerNotch(bool freeForm)
{
    TopoDS_Shape shape = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeBox(gp_Pnt(0, -15, 0), 30, 30, 10).Shape(),
        BRepPrimAPI_MakeBox(gp_Pnt(-1, -16, 8), 11, 32, 3).Shape()
    ).Shape();
    gp_Ax2 axis(gp_Pnt(10, 0, 8), gp::DZ(), gp::DX());
    shape = BRepAlgoAPI_Cut(shape, BRepPrimAPI_MakeCylinder(axis, 4, 3).Shape()).Shape();
    if (freeForm) {
        BRepOffsetAPI_ThruSections loft(Standard_True, Standard_False);
        loft.AddWire(wavyLoop(gp_Pnt(22, 6, 10), 4, 1.2, 0));
        loft.AddWire(wavyLoop(gp_Pnt(22, 6, 25), 2.5, 1.0, pi / 8));
        loft.Build();
        shape = BRepAlgoAPI_Fuse(shape, loft.Shape()).Shape();
    }
    ShapeUpgrade_UnifySameDomain unify(shape, Standard_False, Standard_True, Standard_False);
    unify.Build();
    return unify.Shape();
}

/// fingerNotch's block, channel and notch, on a block 2200 x 2200 x 10 with a boss of about 2e9 mm3
/// lofted between wavy B-spline loops (r 900 at z 10, r 600 at z 1010) at (1100, 0), clear of the notch
TopoDS_Shape fingerNotchOnALargeBody()
{
    TopoDS_Shape shape = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeBox(gp_Pnt(0, -1100, 0), 2200, 2200, 10).Shape(),
        BRepPrimAPI_MakeBox(gp_Pnt(-1, -1101, 8), 11, 2202, 3).Shape()
    ).Shape();
    gp_Ax2 axis(gp_Pnt(10, 0, 8), gp::DZ(), gp::DX());
    shape = BRepAlgoAPI_Cut(shape, BRepPrimAPI_MakeCylinder(axis, 4, 3).Shape()).Shape();
    BRepOffsetAPI_ThruSections loft(Standard_True, Standard_False);
    loft.AddWire(wavyLoop(gp_Pnt(1100, 0, 10), 900, 150, 0));
    loft.AddWire(wavyLoop(gp_Pnt(1100, 0, 1010), 600, 100, pi / 8));
    loft.Build();
    shape = BRepAlgoAPI_Fuse(shape, loft.Shape()).Shape();
    ShapeUpgrade_UnifySameDomain unify(shape, Standard_False, Standard_True, Standard_False);
    unify.Build();
    return unify.Shape();
}

TEST_F(FilletFallbackTest, chamfersASeamSplitRimBesideALargeFreeFormBody)
{
    // Case Base #108 on Onshape's own input: the body (191 000 mm3, free-form faces) measured the
    // cut 29.32171848 for 29.32153143 even adaptively, about 1e-9 of the body against a bound of
    // 1e-6 of the cut. Measured over the faces the stage changed, the change doesn't depend on the
    // body. The reference here is the removed piece measured alone, for the same reason
    TopoShape base(fingerNotchOnALargeBody(), 1L);
    auto rim = edgesWhere(base, atHeight(10), true);
    ASSERT_EQ(rim.size(), 2U);
    double whole = Part::MassProperties::volume(base.getShape(), true);
    std::string reason;
    TopoShape result = forced(base, rim, chamfer(2), &reason);
    ASSERT_FALSE(result.isNull()) << reason << " (body " << whole << ")";
    EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
    TopoDS_Shape removed = BRepAlgoAPI_Cut(base.getShape(), result.getShape()).Shape();
    double expected = pi * (4 + 2.0 / 3) * 2;
    EXPECT_NEAR(Part::MassProperties::volume(removed, true), expected, 1e-6 * expected);
}

/// Case Base #76, designed: a block x 0..30, |y| <= 15, z 0..20; a tunnel r 5 along x about
/// (y 0, z 10); a slot |y| <= 5 above the tunnel's axis (z 10..20) from x 15 on. The rim is the
/// tunnel's upper half circle on the slot's end wall x = 15, from (15, 5, 10) over (15, 0, 15) to
/// (15, -5, 10). At each end the slot's wall is tangent to the tunnel, and the wall's edge on the
/// end wall leaves the vertex upward as the arc does: a cusp. seam: the direction of the tunnel
/// cylinder's seam from its axis (+y puts it on the cusp at y 5, as in Case Base)
TopoDS_Shape cuspedSlot(const gp_Dir& seam)
{
    gp_Ax2 axis(gp_Pnt(-1, 0, 10), gp::DX(), seam);
    TopoDS_Shape shape = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeBox(gp_Pnt(0, -15, 0), 30, 30, 20).Shape(),
        BRepPrimAPI_MakeCylinder(axis, 5, 32).Shape()
    ).Shape();
    return BRepAlgoAPI_Cut(shape, BRepPrimAPI_MakeBox(gp_Pnt(15, -5, 10), 16, 10, 11).Shape())
        .Shape();
}

std::vector<TopoShape> cuspedRim(const TopoShape& base)
{
    return edgesWhere(
        base,
        [](const gp_Pnt& p) { return std::abs(p.X() - 15) < 1e-7 && p.Z() > 10 - 1e-7; },
        true
    );
}

/// The volume of the triangle (a on the top, b down the bore) swept round the half circle r about
/// its axis and cut by the planes y = +-r: the integral over rho in [r, r + a] of
/// 2 rho asin(r / rho) b (r + a - rho) / a
double cuspedChamferVolume(double r, double a, double b)
{
    auto s = [r](double rho) { return std::sqrt(rho * rho - r * r); };
    auto f1 = [&](double rho) { return rho * rho / 2 * std::asin(r / rho) + r / 2 * s(rho); };
    auto f2 = [&](double rho) {
        return rho * rho * rho / 3 * std::asin(r / rho)
            + r / 6 * (rho * s(rho) + r * r * std::log(rho + s(rho)));
    };
    auto g = [&](double rho) { return 2 * (r + a) * f1(rho) - 2 * f2(rho); };
    return b / a * (g(r + a) - g(r));
}

TEST_F(FilletFallbackTest, chamfersARimEndingInCuspsAsOnshape)
{
    // Case Base #76 (oracle 17, Q-CUSP, facts CU1-CU5): Onshape chamfers the half circle and ends
    // the chamfer face on the slot's wall planes y = +-5, adding one face. OCCT leaves a face of zero
    // width; the construction refused "an end face parallel to the edge", or "a vertex where 4 edges
    // meet" with the tunnel's seam on the cusp (as in Case Base). Removed: the triangle swept round
    // the half circle and cut by the wall planes, in closed form (Onshape's volumes are within 2.4e-4
    // of it, OCCT's own on a rib bounding the same region within 1e-6)
    struct Case
    {
        double wall, tunnel, removed;
    };
    const Case cases[] = {
        {1, 3, cuspedChamferVolume(5, 1, 3)},  // C1: 19.826838
        {1, 1, cuspedChamferVolume(5, 1, 1)},  // C3: 6.608946
        {3, 1, cuspedChamferVolume(5, 3, 1)},  // C4: 18.290831
    };
    // The seam below the rim, on its top (the rim in two pieces), and on the cusp
    for (const gp_Dir& seam : {gp_Dir(0, 0, -1), gp_Dir(0, 0, 1), gp_Dir(0, 1, 0)}) {
        TopoShape base(cuspedSlot(seam), 1L);
        auto rim = cuspedRim(base);
        ASSERT_FALSE(rim.empty());
        auto face = base.findAncestorShape(rim[0].getShape(), TopAbs_FACE);
        bool onWall = BRepAdaptor_Surface(TopoDS::Face(face)).GetType() == GeomAbs_Plane;
        int faces = base.countSubShapes(TopAbs_FACE);
        for (const auto& c : cases) {
            auto request = onWall ? chamfer(c.wall, c.tunnel, ChamferType::twoDistances)
                                  : chamfer(c.tunnel, c.wall, ChamferType::twoDistances);
            if (c.wall == c.tunnel) {
                request = chamfer(c.wall);
            }
            TopoShape result = dressUp(base, rim, request);
            ASSERT_FALSE(result.isNull()) << seam.Z() << " " << c.wall << "/" << c.tunnel;
            EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
            EXPECT_NEAR(
                volume(base.getShape()) - volume(result.getShape()),
                c.removed,
                1e-6 * c.removed
            ) << seam.Z() << " " << c.wall << "/" << c.tunnel;
            // One chamfer face per piece of the rim
            EXPECT_EQ(result.countSubShapes(TopAbs_FACE), faces + static_cast<int>(rim.size()))
                << seam.Z() << " " << c.wall << "/" << c.tunnel;
        }
    }
}

TEST_F(FilletFallbackTest, chamfersASeamSplitRimBesideAFreeFormFace)
{
    // Case Base #108: the chamfer 2 of the notch's rim (both pieces), down to the floor: the
    // triangle 2 x 2 revolved half way at the centroid radius 4 + 2 / 3. The construction measured
    // its stages by OCCT's default integration, whose error on a free-form face moves with the
    // shape integrated (the point it integrates about is the shape's): the boss's side, which the
    // cut leaves alone, then made the cut measure short. On the replica: 2.45e-4, eight times the
    // bound (ops#640). The volumes here are adaptive: the default can't be the test's reference
    for (bool freeForm : {false, true}) {
        TopoShape base(fingerNotch(freeForm), 1L);
        auto rim = edgesWhere(base, atHeight(10), true);
        ASSERT_EQ(rim.size(), 2U) << freeForm;
        GProp_GProps before;
        BRepGProp::VolumeProperties(base.getShape(), before);
        double defaultError = before.Mass() - Part::MassProperties::volume(base.getShape(), true);
        std::string reason;
        TopoShape result = forced(base, rim, chamfer(2), &reason);
        ASSERT_FALSE(result.isNull()) << freeForm << ": " << reason << " (default error "
                                      << defaultError << ")";
        EXPECT_TRUE(BRepCheck_Analyzer(result.getShape()).IsValid());
        EXPECT_NEAR(
            Part::MassProperties::volume(base.getShape(), true)
                - Part::MassProperties::volume(result.getShape(), true),
            pi * (4 + 2.0 / 3) * 2,
            1e-6 * pi * (4 + 2.0 / 3) * 2
        ) << freeForm << " (default error " << defaultError << ")";
    }
}

TEST_F(FilletFallbackTest, refusesATrimByAFinInFrontOfTheWall)
{
    // Review r1's case: a step (top z 10 over y 4..10, wall y 4 down to the ledge z 9.037) with a
    // fin 0.5 thick standing on the ledge 0.02 in front of the wall, its top 0.5 above the ledge.
    // The top's edge dressed up 1.0 runs past the wall's foot: the fin's section, closer to the
    // wall than both offsets, would have trimmed the dress-up at the fin's top. Refused
    const double h = 0.963;
    TopoDS_Shape shape = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 20, 10, 10).Shape(),
        BRepPrimAPI_MakeBox(gp_Pnt(-1, -1, 10 - h), 22, 5, h + 1).Shape()
    ).Shape();
    shape = BRepAlgoAPI_Fuse(shape, BRepPrimAPI_MakeBox(gp_Pnt(0, 3.48, 10 - h), 20, 0.5, 0.5).Shape())
                .Shape();
    ShapeUpgrade_UnifySameDomain unify(shape, Standard_False, Standard_True, Standard_False);
    unify.Build();
    TopoShape base(unify.Shape(), 1L);
    TopoShape top = edgeBetween(base, {0, 4, 10}, {20, 4, 10});
    for (const auto& request : {chamfer(1), fillet(1)}) {
        std::string reason;
        EXPECT_TRUE(forced(base, {top}, request, &reason).isNull());
        EXPECT_NE(reason.find("not the wall"), std::string::npos) << reason;
    }
}

TEST_F(FilletFallbackTest, refusesATrimByAFinInAnotherLedgesPlane)
{
    // Review r2's case: a front ledge (riser y 4, floor z 9.037) and a back ledge (riser y 16,
    // floor z 9.537), both top edges dressed up 1.0 in one feature, and a fin 0.02 in front of the
    // front riser whose top lies in the back ledge's plane. The front riser's own wall is its
    // floor at 9.037: the fin's top isn't, so the trim is refused (it was taken for the back wall)
    TopoDS_Shape shape = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 20, 20, 10).Shape(),
        BRepPrimAPI_MakeBox(gp_Pnt(-1, -1, 9.037), 22, 5, 2).Shape()
    ).Shape();
    shape = BRepAlgoAPI_Cut(shape, BRepPrimAPI_MakeBox(gp_Pnt(-1, 16, 9.537), 22, 5, 2).Shape())
                .Shape();
    shape = BRepAlgoAPI_Fuse(shape, BRepPrimAPI_MakeBox(gp_Pnt(0, 3.48, 9.037), 20, 0.5, 0.5).Shape())
                .Shape();
    ShapeUpgrade_UnifySameDomain unify(shape, Standard_False, Standard_True, Standard_False);
    unify.Build();
    TopoShape base(unify.Shape(), 1L);
    TopoShape front = edgeBetween(base, {0, 4, 10}, {20, 4, 10});
    TopoShape back = edgeBetween(base, {0, 16, 10}, {20, 16, 10});
    for (const auto& request : {chamfer(1), fillet(1)}) {
        std::string reason;
        EXPECT_TRUE(forced(base, {front, back}, request, &reason).isNull());
        EXPECT_NE(reason.find("not the wall"), std::string::npos) << reason;
    }
}

TEST_F(FilletFallbackTest, trimsARiserOverTwoLedgeHeightsByEachLedge)
{
    // Review r2's T2 without its fin: one riser (y 4) whose foot meets the ledge at z 9.037 for
    // x 0..10 and at z 9.537 for x 10..20. The strip runs into walls on two planes; each part of
    // the tool is trimmed by the ledge behind it. Closed forms: the base 2000 - 40 (0.963 + 0.463)
    // less, per 10 of length, the section above its ledge (chamfer 1/2 - d^2/2, fillet
    // (1 - pi/4) - (d - (d sqrt(1 - d^2) + asin d) / 2)), d = 0.037 and 0.537 past the foot
    TopoDS_Shape shape = BRepAlgoAPI_Cut(
        BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 20, 10, 10).Shape(),
        BRepPrimAPI_MakeBox(gp_Pnt(-1, -1, 9.037), 11, 5, 2).Shape()
    ).Shape();
    shape = BRepAlgoAPI_Cut(shape, BRepPrimAPI_MakeBox(gp_Pnt(10, -1, 9.537), 11, 5, 2).Shape())
                .Shape();
    ShapeUpgrade_UnifySameDomain unify(shape, Standard_False, Standard_True, Standard_False);
    unify.Build();
    TopoShape base(unify.Shape(), 1L);
    // The top edge is split where the two ledges meet (x 10): both halves are dressed up
    TopoShape left = edgeBetween(base, {0, 4, 10}, {10, 4, 10});
    TopoShape right = edgeBetween(base, {10, 4, 10}, {20, 4, 10});
    const double baseVolume = 2000 - 40 * (0.963 + 0.463);
    auto filletPast = [](double d) {
        return d - (d * std::sqrt(1 - d * d) + std::asin(d)) / 2;
    };
    const double chamfered = baseVolume - 10 * (0.5 - 0.037 * 0.037 / 2)
        - 10 * (0.5 - 0.537 * 0.537 / 2);
    const double rounded = baseVolume - 10 * ((1 - M_PI / 4) - filletPast(0.037))
        - 10 * ((1 - M_PI / 4) - filletPast(0.537));
    std::string reason;
    TopoShape result = forced(base, {left, right}, chamfer(1), &reason);
    EXPECT_TRUE(exact(result, chamfered)) << reason;
    EXPECT_EQ(count(result.getShape(), TopAbs_FACE), 11);
    result = forced(base, {left, right}, fillet(1), &reason);
    EXPECT_TRUE(exact(result, rounded)) << reason;
    EXPECT_EQ(count(result.getShape(), TopAbs_FACE), 11);
}

TEST_F(FilletFallbackTest, refusesADressUpPastAConcaveEdgeIntoASlopedWall)
{
    // The same strip past the riser's foot, but the tread slopes: its plane isn't square to the
    // riser, so the trim by its surface run on behind the riser isn't the base's section swept
    // back. That stays refused
    TopoShape base(profileAlongX({{0, 0}, {20, 0}, {20, 14}, {10, 14}, {10, 10}, {0, 11}}, 30),
                   1L);
    std::string reason;
    TopoShape convex = edgeBetween(base, {0, 10, 14}, {30, 10, 14});
    EXPECT_TRUE(forced(base, {convex}, chamfer(5), &reason).isNull());
    EXPECT_NE(reason.find("runs off its face into a wall"), std::string::npos) << reason;
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

TEST_F(FilletFallbackTest, materialInFindsWhatACutLeftInARegion)
{
    // ops#669: the check that a cut removed the lens two tools share, by points, not by volumes
    const TopoDS_Shape block = box(10, 10, 10);
    const TopoDS_Shape region = box(2, 3, 4, gp_Pnt(4, 3, 2));
    EXPECT_FALSE(FF::materialIn(BRepAlgoAPI_Cut(block, region).Shape(), region));
    auto left = FF::materialIn(block, region);
    ASSERT_TRUE(left);
    EXPECT_GT(left->X(), 4);
    EXPECT_LT(left->X(), 6);
    EXPECT_GT(left->Z(), 2);
    EXPECT_LT(left->Z(), 6);
    // Half of it removed: the point is in the half left
    const TopoDS_Shape half = BRepAlgoAPI_Cut(block, box(2, 3, 2, gp_Pnt(4, 3, 4))).Shape();
    left = FF::materialIn(half, region);
    ASSERT_TRUE(left);
    EXPECT_LT(left->Z(), 4);
    // A lens 1e-3 thin is found; one thinner than 20 tolerances (1e-7) is not looked into
    const TopoDS_Shape sheet = box(6, 6, 1e-3, gp_Pnt(2, 2, 5));
    EXPECT_TRUE(FF::materialIn(block, sheet));
    EXPECT_FALSE(FF::materialIn(BRepAlgoAPI_Cut(block, sheet).Shape(), sheet));
    EXPECT_FALSE(FF::materialIn(block, box(6, 6, 1e-6, gp_Pnt(2, 2, 5))));
}

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

// C4 shape A (ops#640, notes/fillet-tight-arc.md): the top rim's round of 1.5 on a 30 x 20 x 5
// plate whose corner at (30, 0) is rounded rho < 1.5, the others 4. OCCT's result is valid but
// wrong; the construction runs first. Onshape's volumes (oracle 17, TA1 and TA2) and face count
TEST_F(FilletFallbackTest, roundAlongAWallArcTighterThanTheRound)
{
    for (auto [rho, onshape] : {std::pair {1.0, 2902.820914}, std::pair {0.5, 2903.543273}}) {
        TopoShape plate(box(30, 20, 5), 1L);
        std::vector<TopoShape> corners {
            edgeBetween(plate, {0, 0, 0}, {0, 0, 5}),
            edgeBetween(plate, {30, 20, 0}, {30, 20, 5}),
            edgeBetween(plate, {0, 20, 0}, {0, 20, 5})
        };
        TopoShape rounded = dressUp(plate, corners, fillet(4));
        TopoShape base = dressUp(rounded, {edgeBetween(rounded, {30, 0, 0}, {30, 0, 5})}, fillet(rho));
        auto top = edgesWhere(base, atHeight(5));
        ASSERT_EQ(top.size(), 8U);
        TopoShape result = dressUp(base, top, fillet(1.5));
        const auto& shape = result.getShape();
        ASSERT_FALSE(shape.IsNull());
        EXPECT_TRUE(BRepCheck_Analyzer(shape).IsValid());
        EXPECT_EQ(count(shape, TopAbs_SOLID), 1);
        EXPECT_FALSE(hasZeroAreaFace(shape));
        EXPECT_NEAR(volume(shape), onshape, 1e-3) << "rho " << rho;
        EXPECT_EQ(count(shape, TopAbs_FACE), 18) << "rho " << rho;
        // The wall arc stays whole at depth r, a circle
        auto arcs = edgesWhere(result, atHeight(3.5), true);
        EXPECT_TRUE(std::any_of(arcs.begin(), arcs.end(), [rho = rho](const TopoShape& edge) {
            return std::abs(BRepAdaptor_Curve(TopoDS::Edge(edge.getShape())).Circle().Radius() - rho)
                < 1e-9;
        })) << "rho "
            << rho;
    }
}

namespace
{
double area(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(shape, props);
    return props.Mass();
}

/// The concave fillet section r at the corner, filling towards +along and +up (a spandrel), in
/// the plane those two directions span
TopoDS_Face spandrel(const gp_Pnt& corner, const gp_Dir& along, const gp_Dir& up, double r)
{
    gp_Pnt onFloor = corner.Translated(gp_Vec(along) * r);
    gp_Pnt onWall = corner.Translated(gp_Vec(up) * r);
    gp_Pnt centre = onFloor.Translated(gp_Vec(up) * r);
    gp_Pnt middle = centre.Translated((gp_Vec(along) + gp_Vec(up)).Normalized() * -r);
    BRepBuilderAPI_MakeWire wire(
        BRepBuilderAPI_MakeEdge(corner, onFloor).Edge(),
        BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(onFloor, middle, onWall).Value()).Edge(),
        BRepBuilderAPI_MakeEdge(onWall, corner).Edge()
    );
    return BRepBuilderAPI_MakeFace(wire.Wire(), Standard_True).Face();
}

TopoDS_Shape fuseAll(const std::vector<TopoDS_Shape>& shapes)
{
    TopoDS_Shape result = shapes.front();
    for (size_t i = 1; i < shapes.size(); ++i) {
        result = BRepAlgoAPI_Fuse(result, shapes[i]).Shape();
    }
    return result;
}

/// The run's edges on the floor z = h: the concave foot edges whose midpoint passes the test
std::vector<TopoShape> footRun(const TopoShape& base, double h, const std::function<bool(const gp_Pnt&)>& test)
{
    std::vector<TopoShape> result;
    for (const auto& edge : edgesWhere(base, atHeight(h))) {
        BRepAdaptor_Curve curve(TopoDS::Edge(edge.getShape()));
        if (test(curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2))) {
            result.push_back(edge);
        }
    }
    return result;
}

int facesOn(const TopoDS_Shape& shape, GeomAbs_SurfaceType type)
{
    int n = 0;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        n += surfaceType(it.Current()) == type ? 1 : 0;
    }
    return n;
}
}  // namespace

TEST_F(FilletFallbackTest, concaveRunEndingWhereItsChainTurnsConvex)
{
    // Nest Cover #151's topology with straight edges (oracle 17 Q-OVF v2, onshape-facts OV3): a plate
    // 40 x 20 with its outer edge bevelled down and in, 45 deg through the whole thickness C; a stadium
    // wall (x 10..30, y 0..T, round ends r T/2, 4 high) flush with the bevel; a fillet r T/2 on the
    // wall's inner foot line and the round ends' feet. At (10, 0, 10) and (30, 0, 10) four edges meet,
    // and the floor/bevel edge carries the run on tangentially but convex. OCCT's fillet runs on along
    // it and returns a valid solid with 2 faces too many, 29 mm3 short. Onshape stops the chain there,
    // and each end torus rolls on past the vertex, trimmed by the bevel (and the wall's outer face):
    // V 1358.018700 (evVolume, ~1e-3), A 1923.543821, 14 faces, 34 edges, 22 vertices; 3 new faces,
    // the tori 3.883267 each; the outer face starts at z 10.79375 at x 10 (79.246377)
    const double c = 1.5875;
    const double t = 1.5875;
    const double h = 10;
    const double r = t / 2;
    BRepBuilderAPI_MakePolygon outline(
        gp_Pnt(0, 0, h),
        gp_Pnt(0, c, h - c),
        gp_Pnt(0, 20, h - c),
        gp_Pnt(0, 20, h),
        Standard_True
    );
    TopoDS_Shape plate = BRepPrimAPI_MakePrism(
                             BRepBuilderAPI_MakeFace(outline.Wire(), Standard_True).Face(),
                             gp_Vec(40, 0, 0)
    )
                             .Shape();
    BRepBuilderAPI_MakeWire stadium;
    stadium.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(10, 0, h), gp_Pnt(30, 0, h)).Edge());
    stadium.Add(BRepBuilderAPI_MakeEdge(
                    GC_MakeArcOfCircle(gp_Pnt(30, 0, h), gp_Pnt(30 + r, r, h), gp_Pnt(30, t, h)).Value()
    )
                    .Edge());
    stadium.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(30, t, h), gp_Pnt(10, t, h)).Edge());
    stadium.Add(BRepBuilderAPI_MakeEdge(
                    GC_MakeArcOfCircle(gp_Pnt(10, t, h), gp_Pnt(10 - r, r, h), gp_Pnt(10, 0, h)).Value()
    )
                    .Edge());
    TopoDS_Shape wall
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(stadium.Wire(), Standard_True).Face(), gp_Vec(0, 0, 4))
              .Shape();
    TopoShape fused;
    fused.makeElementBoolean(OpCodes::Fuse, {TopoShape(plate), TopoShape(wall)});
    TopoShape base(fused.removeSplitter(), 1L);
    ASSERT_EQ(base.countSubElements("Face"), 11);
    auto run = footRun(base, h, [&](const gp_Pnt& p) {
        return p.Y() > 1e-7 && p.Y() < t + 1e-7;
    });
    ASSERT_EQ(run.size(), 3);
    // Onshape's shape by other Booleans: the line's spandrel, and each end's spandrel turned a whole
    // turn about its axis, kept where the bevel's plane (y + z >= h) has the material
    TopoDS_Shape fill = BRepPrimAPI_MakePrism(spandrel(gp_Pnt(10, t, h), gp::DY(), gp::DZ(), r), gp_Vec(20, 0, 0))
                            .Shape();
    BRepBuilderAPI_MakePolygon side(
        gp_Pnt(-10, h / 2, h / 2),
        gp_Pnt(-10, -25, h + 25),
        gp_Pnt(-10, 40, h + 25),
        gp_Pnt(-10, 40, h / 2),
        Standard_True
    );
    TopoDS_Shape bevelSide
        = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(side.Wire(), Standard_True).Face(), gp_Vec(60, 0, 0))
              .Shape();
    for (double x : {10.0, 30.0}) {
        gp_Ax1 axis(gp_Pnt(x, r, h), gp::DZ());
        TopoDS_Shape ring = BRepPrimAPI_MakeRevol(
                                spandrel(gp_Pnt(x - r, r, h), gp::DX().Reversed(), gp::DZ(), r),
                                axis,
                                2 * pi
        )
                                .Shape();
        fill = BRepAlgoAPI_Fuse(fill, BRepAlgoAPI_Common(ring, bevelSide).Shape()).Shape();
    }
    double expected = volume(BRepAlgoAPI_Fuse(base.getShape(), fill).Shape());
    EXPECT_NEAR(expected, 1358.018700, 2e-3);  // Onshape's evVolume
    TopoShape result = dressUp(base, run, fillet(r));
    EXPECT_TRUE(exact(result, expected));
    EXPECT_NEAR(result.getShape().IsNull() ? 0.0 : area(result.getShape()), 1923.543821, 1e-5);
    EXPECT_EQ(result.countSubElements("Face"), 14);
    EXPECT_EQ(result.countSubElements("Edge"), 34);
    EXPECT_EQ(result.countSubElements("Vertex"), 22);
    EXPECT_EQ(facesOn(result.getShape(), GeomAbs_Torus), 2);
    for (TopExp_Explorer it(result.getShape(), TopAbs_FACE); it.More(); it.Next()) {
        if (surfaceType(it.Current()) == GeomAbs_Torus) {
            EXPECT_NEAR(area(it.Current()), 3.883267, 1e-5);
        }
    }
    // The inner line alone: OCCT's contour runs on the same way (tangent propagation), and the
    // selection stops short of Onshape's chain at the round ends: never OCCT's result silently
    std::vector<TopoShape> line;
    for (const auto& edge : run) {
        if (BRepAdaptor_Curve(TopoDS::Edge(edge.getShape())).GetType() == GeomAbs_Line) {
            line.push_back(edge);
        }
    }
    ASSERT_EQ(line.size(), 1);
    EXPECT_THROW(dressUp(base, line, fillet(r)), Base::Exception);
}

TEST_F(FilletFallbackTest, concaveArcRunEndingAtAChamferCone)
{
    // The same on half a round plate, as Nest Cover's (#151): the plate r 20 with its rim bevelled down
    // and in (a cone, 45 deg, C deep); on it a wall along the rim (r 20 - T .. 20, -30..30 deg, 4
    // high) with round ends r T/2; the fillet r T/2 on its inner foot arc and the ends' feet. At each
    // end the floor/cone rim carries the run on tangentially but convex: each end torus rolls on
    // past the vertex, trimmed by the cone, which grows there by the tool's faces on it (3 new
    // faces, as Onshape's 17 -> 20 on Nest Cover)
    const double c = 1.5875;
    const double t = 1.5875;
    const double h = 10;
    const double r = t / 2;
    const double rim = 20;
    const double half = pi / 6;
    BRepBuilderAPI_MakePolygon outline(
        gp_Pnt(0, 0, h),
        gp_Pnt(rim, 0, h),
        gp_Pnt(rim - c, 0, h - c),
        gp_Pnt(0, 0, h - c),
        Standard_True
    );
    // Half the plate (x >= 0), so the bevel is a band with ends. Debt: on the whole plate's closed
    // band OCCT's face unifier joins the two patches the tools leave on the cone to each other and
    // not to the band (one face with two outer wires), and the construction refuses "the result is
    // not valid"
    gp_Trsf toQuarter;
    toQuarter.SetRotation(gp_Ax1(gp::Origin(), gp::DZ()), -pi / 2);
    TopoDS_Shape plate = BRepPrimAPI_MakeRevol(
                             BRepBuilderAPI_MakeFace(outline.Wire(), Standard_True)
                                 .Face()
                                 .Moved(TopLoc_Location(toQuarter)),
                             gp_Ax1(gp::Origin(), gp::DZ()),
                             pi
    )
                             .Shape();
    BRepBuilderAPI_MakePolygon band(
        gp_Pnt(rim - t, 0, h),
        gp_Pnt(rim, 0, h),
        gp_Pnt(rim, 0, h + 4),
        gp_Pnt(rim - t, 0, h + 4),
        Standard_True
    );
    gp_Trsf toStart;
    toStart.SetRotation(gp_Ax1(gp::Origin(), gp::DZ()), -half);
    TopoDS_Shape arc = BRepPrimAPI_MakeRevol(
                           BRepBuilderAPI_MakeFace(band.Wire(), Standard_True).Face().Moved(TopLoc_Location(toStart)),
                           gp_Ax1(gp::Origin(), gp::DZ()),
                           2 * half
    )
                           .Shape();
    std::vector<TopoDS_Shape> parts {plate, arc};
    std::vector<gp_Pnt> ends;
    for (double a : {-half, half}) {
        gp_Pnt centre((rim - r) * std::cos(a), (rim - r) * std::sin(a), h);
        ends.push_back(centre);
        parts.push_back(BRepPrimAPI_MakeCylinder(gp_Ax2(centre, gp::DZ()), r, 4).Shape());
    }
    TopoShape fused;
    fused.makeElementBoolean(
        OpCodes::Fuse,
        {TopoShape(parts[0]), TopoShape(parts[1]), TopoShape(parts[2]), TopoShape(parts[3])}
    );
    TopoShape base(fused.removeSplitter(), 1L);
    int baseFaces = base.countSubElements("Face");
    auto run = footRun(base, h, [&](const gp_Pnt& p) {
        double radial = std::hypot(p.X(), p.Y());
        return radial < rim - 1e-7 && radial > rim - t - 1e-7 && p.X() > 0;
    });
    ASSERT_EQ(run.size(), 3);
    // Onshape's shape by other Booleans: the arc's spandrel turned about the plate's axis, and each
    // end's a whole turn about its own, kept inside the cone (r <= rim + (z - h))
    TopoDS_Shape fill = BRepPrimAPI_MakeRevol(
                            spandrel(gp_Pnt(rim - t, 0, h), gp::DX().Reversed(), gp::DZ(), r)
                                .Moved(TopLoc_Location(toStart)),
                            gp_Ax1(gp::Origin(), gp::DZ()),
                            2 * half
    )
                            .Shape();
    TopoDS_Shape cone
        = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(0, 0, h - 5), gp::DZ()), rim - 5, rim + 10, 15).Shape();
    for (const auto& centre : ends) {
        gp_Vec out(gp::Origin(), gp_Pnt(centre.X(), centre.Y(), 0));
        out.Normalize();
        TopoDS_Shape ring = BRepPrimAPI_MakeRevol(
                                spandrel(centre.Translated(out * r), gp_Dir(out), gp::DZ(), r),
                                gp_Ax1(centre, gp::DZ()),
                                2 * pi
        )
                                .Shape();
        fill = BRepAlgoAPI_Fuse(fill, BRepAlgoAPI_Common(ring, cone).Shape()).Shape();
    }
    double expected = volume(BRepAlgoAPI_Fuse(base.getShape(), fill).Shape());
    TopoShape result = dressUp(base, run, fillet(r));
    EXPECT_TRUE(exact(result, expected));
    EXPECT_EQ(result.countSubElements("Face"), baseFaces + 3);
    EXPECT_EQ(facesOn(result.getShape(), GeomAbs_Torus), 3);
}

// A round that ends under an overhang (ops#640, the replica's Case Base #103). Designed model: a
// block with its vertical corner rounded (a cylinder R tangent to both side planes), scooped by an
// ellipsoid below z 21.225, with an opening r 7.658 above it: a 1 mm lip hangs over the scoop. The
// scoop's edge with the corner cylinder ends under the lip, 0.024 from each tangent line.
namespace
{
constexpr double lipCorner = 11.3125;
constexpr double lipUnderside = 21.225;
constexpr double lipRound = 0.79375;

/// The block with its corner rounded, to the height given
TopoDS_Shape roundedCornerBlock(double height)
{
    TopoDS_Shape block = box(40 + lipCorner, 40 + lipCorner, height, gp_Pnt(-40, -lipCorner, 0));
    BRepAlgoAPI_Cut corner(
        box(lipCorner, lipCorner, height, gp_Pnt(0, -lipCorner, 0)),
        BRepPrimAPI_MakeCylinder(lipCorner, height).Shape()
    );
    return BRepAlgoAPI_Cut(block, corner.Shape()).Shape();
}

/// The ellipsoid: centre (6, -6, 21.667), semi-axes 8, 8, 14
TopoDS_Shape scoopEllipsoid()
{
    gp_GTrsf scale;
    scale.SetVectorialPart(gp_Mat(8, 0, 0, 0, 8, 0, 0, 0, 14));
    scale.SetTranslationPart(gp_XYZ(6, -6, 21.667));
    return BRepBuilderAPI_GTransform(BRepPrimAPI_MakeSphere(1.0).Shape(), scale, true).Shape();
}

/// The scooped block: with the lip (height 22.225), or cut off at the lip's underside
TopoDS_Shape scoopedBlock(bool lip)
{
    if (!lip) {
        return BRepAlgoAPI_Cut(roundedCornerBlock(lipUnderside), scoopEllipsoid()).Shape();
    }
    BRepAlgoAPI_Common below(scoopEllipsoid(), box(200, 200, lipUnderside + 50, gp_Pnt(-100, -100, -50)));
    BRepAlgoAPI_Cut scooped(roundedCornerBlock(lipUnderside + 1), below.Shape());
    BRepAlgoAPI_Cut opened(
        scooped.Shape(),
        BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(6, -6, lipUnderside), gp::DZ()), 7.658, 2).Shape()
    );
    ShapeUpgrade_UnifySameDomain unify(opened.Shape());
    unify.Build();
    return unify.Shape();
}

/// The edges between the scoop's free-form face and the corner's cylinder
std::vector<TopoShape> scoopEdges(const TopoShape& shape)
{
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(shape.getShape(), TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    std::vector<TopoShape> edges;
    for (int i = 1; i <= edgeFaces.Extent(); ++i) {
        bool corner = false;
        bool scoop = false;
        for (const auto& face : edgeFaces(i)) {
            BRepAdaptor_Surface surface(TopoDS::Face(face));
            if (surface.GetType() == GeomAbs_Cylinder) {
                corner = corner || std::abs(surface.Cylinder().Radius() - lipCorner) < 1e-9;
            }
            else if (surface.GetType() != GeomAbs_Plane) {
                scoop = true;
            }
        }
        if (corner && scoop) {
            edges.push_back(shape.getSubTopoShape(TopAbs_EDGE, shape.findShape(edgeFaces.FindKey(i))));
        }
    }
    return edges;
}
}  // namespace

TEST_F(FilletFallbackTest, roundEndingUnderALipIsTheRoundBelowItCutOffByItsUnderside)
{
    // OCCT alone: the blend faces, and the two side planes left with open boundaries
    TopoShape base(scoopedBlock(true), 1L);
    ASSERT_TRUE(BRepCheck_Analyzer(base.getShape()).IsValid());
    auto edges = scoopEdges(base);
    ASSERT_EQ(edges.size(), 2);  // the corner cylinder's seam splits the edge
    BRepFilletAPI_MakeFillet occt(base.getShape());
    for (const auto& edge : edges) {
        occt.Add(lipRound, TopoDS::Edge(edge.getShape()));
    }
    occt.Build();
    ASSERT_TRUE(occt.IsDone());
    EXPECT_FALSE(BRepCheck_Analyzer(occt.Shape()).IsValid());
    // The control: without the lip (the block cut off at the underside's height) OCCT's round is
    // valid, and what it removes is what the round under the lip must remove
    TopoShape control(scoopedBlock(false), 3L);
    TopoShape below = dressUp(control, scoopEdges(control), fillet(lipRound));
    ASSERT_TRUE(BRepCheck_Analyzer(below.getShape()).IsValid());
    double removed = Part::MassProperties::volume(control.getShape(), true)
        - Part::MassProperties::volume(below.getShape(), true);
    EXPECT_GT(removed, 16.0);
    EXPECT_LT(removed, 17.5);
    // Under the lip: one valid solid, the same volume gone, the lip's underside grown over it
    {
        // The construction's own verdict: its reason where it refuses
        std::vector<TopoDS_Shape> shapes;
        for (const auto& edge : edges) {
            shapes.push_back(edge.getShape());
        }
        FF::Construction construction;
        std::string reason;
        EXPECT_TRUE(FF::construct(base.getShape(), shapes, fillet(lipRound), construction, &reason))
            << reason;
    }
    TopoShape round = dressUp(base, edges, fillet(lipRound));
    EXPECT_TRUE(BRepCheck_Analyzer(round.getShape()).IsValid());
    EXPECT_EQ(count(round.getShape(), TopAbs_SOLID), 1);
    double gone = Part::MassProperties::volume(base.getShape(), true)
        - Part::MassProperties::volume(round.getShape(), true);
    // Both are differences of whole-body volumes (56 500 mm3, good to about 1e-8 of it)
    EXPECT_NEAR(gone, removed, 2e-3);
    // Onshape's own result on this model (oracle 17, Q-LIP, facts LP0-LP1): its round under the lip
    // is the round without the lip cut off at z 21.225; the lip's underside grows from 8.100316
    // to 9.120288, and two slivers of the corner cylinder, 0.474914 each, are split off in the
    // lip's band. (Its dV is -16.72 +- 0.01; OCCT's own blend, with or without the lip, removes
    // 16.665: the round's shape is OCCT's, not this construction's)
    int slivers = 0;
    bool underside = false;
    for (TopExp_Explorer it(round.getShape(), TopAbs_FACE); it.More(); it.Next()) {
        BRepAdaptor_Surface surface(TopoDS::Face(it.Current()));
        GProp_GProps props;
        BRepGProp::SurfaceProperties(it.Current(), props);
        if (surface.GetType() == GeomAbs_Cylinder
            && std::abs(surface.Cylinder().Radius() - lipCorner) < 1e-9
            && std::abs(props.Mass() - 0.474914) < 1e-3) {
            ++slivers;
        }
        if (surface.GetType() == GeomAbs_Plane && std::abs(props.Mass() - 9.120288) < 2e-3
            && std::abs(props.CentreOfMass().Z() - lipUnderside) < 1e-7) {
            underside = true;
        }
    }
    EXPECT_EQ(slivers, 2);
    EXPECT_TRUE(underside);
    // Four blend faces (the seam splits the middle one) and the corner cylinder's two slivers
    // above them, split off; no step under the lip (the cap merges into the underside)
    EXPECT_EQ(count(round.getShape(), TopAbs_FACE), count(base.getShape(), TopAbs_FACE) + 6);
    EXPECT_TRUE(FF::thinFace(round.getShape(), base.getShape()).IsNull());
    // The result is named
    EXPECT_FALSE(elementNames(round).empty());
}

// A round on the rim that ends in cusps, CU5's own figures (oracle 17 Q-CUSP, notes/onshape-facts.md
// "Case Base #76 designed check"). The construction refused it ("an end face parallel to the edge")
// until the line's later picks built it (batch 14c, b14f)
TEST_F(FilletFallbackTest, roundsARimEndingInCuspsAsOnshape)
{
    // CU5: r 1 on the rim: dV -2.922055 (evVolume, ~1.5e-4), dA -5.057250, 10 -> 11 faces, one torus
    // face 20.915168, cut off by the slot's wall planes y = +-5
    for (const gp_Dir& seam : {gp_Dir(0, 0, -1), gp_Dir(0, 1, 0)}) {
        TopoShape base(cuspedSlot(seam), 1L);
        auto rim = cuspedRim(base);
        std::string reason;
        TopoShape result = forced(base, rim, fillet(1), &reason);
        ASSERT_FALSE(result.isNull()) << reason;
        EXPECT_NEAR(volume(base.getShape()) - volume(result.getShape()), 2.922055, 3e-4);
        EXPECT_NEAR(area(base.getShape()) - area(result.getShape()), 5.057250, 1e-5);
        EXPECT_EQ(result.countSubElements("Face"), base.countSubElements("Face") + 1);
        int tori = 0;
        for (TopExp_Explorer it(result.getShape(), TopAbs_FACE); it.More(); it.Next()) {
            if (surfaceType(it.Current()) == GeomAbs_Torus) {
                ++tori;
                EXPECT_NEAR(area(it.Current()), 20.915168, 1e-5);
            }
        }
        EXPECT_EQ(tori, 1);
    }
}

// NOLINTEND(readability-magic-numbers,cppcoreguidelines-avoid-magic-numbers)
