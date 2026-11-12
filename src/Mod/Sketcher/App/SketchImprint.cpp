// SPDX-License-Identifier: LGPL-2.1-or-later

// Onshape's imprint for a sketch's regions (FreeCAD-CH, feat/profile-regions): see SketchImprint.h

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepTools.hxx>
#include <Geom_Curve.hxx>
#include <ShapeAnalysis_Curve.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>

#include <App/Datums.h>
#include <Base/Console.h>
#include <Base/Placement.h>
#include <Mod/Part/App/DatumFeature.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/PartFeature.h>

#include "SketchImprint.h"
#include "SketchObject.h"

FC_LOG_LEVEL_INIT("Sketch", true, true)

namespace
{

// An edge lies in the plane when it does within OCCT's confusion: the support's own planar faces
// are that exact, and an edge only near the plane would make faces off their surface
constexpr double inPlane = Precision::Confusion();

bool liesInPlane(const TopoDS_Edge& edge, const gp_Trsf& toLocal)
{
    if (BRep_Tool::Degenerated(edge)) {
        return false;
    }
    TopoDS_Vertex first;
    TopoDS_Vertex last;
    TopExp::Vertices(edge, first, last);
    for (const auto& v : {first, last}) {
        if (v.IsNull()) {
            return false;
        }
        if (std::abs(BRep_Tool::Pnt(v).Transformed(toLocal).Z()) > inPlane) {
            return false;
        }
    }
    Bnd_Box box;
    BRepBndLib::AddOptimal(edge.Moved(TopLoc_Location(toLocal)), box, false, false);
    if (box.IsVoid()) {
        return false;
    }
    double x0 {}, y0 {}, z0 {}, x1 {}, y1 {}, z1 {};
    box.Get(x0, y0, z0, x1, y1, z1);
    return std::abs(z0) <= inPlane && std::abs(z1) <= inPlane;
}

bool imprints(const App::DocumentObject* obj)
{
    // Model geometry only: a datum's or an origin's face is a construction plane, and another
    // sketch is no model (Onshape imprints parts and surfaces)
    return obj && obj->isDerivedFrom<Part::Feature>() && !obj->isDerivedFrom<Part::Datum>()
        && !obj->isDerivedFrom<Part::Part2DObject>() && !obj->isDerivedFrom<App::DatumElement>();
}

}  // namespace

namespace
{

/// The imprint edges (imprintEdges()); firstOnly: stop at the first one, without copying it
std::vector<Part::TopoShape> collectImprint(const Sketcher::SketchObject& sketch, bool firstOnly)
{
    using Sketcher::SketchObject;
    if (sketch._InternalFaceVersion.getValue() < Sketcher::ImprintInternalFaceVersion
        || !sketch.MakeInternals.getValue() || sketch.DisableImprinting.getValue()) {
        return {};
    }
    std::vector<Part::TopoShape> edges;
    const Base::Placement invPlm = sketch.Placement.getValue().inverse();
    // Only the face the sketch lies on: another face's or another part's coplanar edges don't
    // split its regions, nor does a face under a sketch on a plane (Onshape, R4)
    for (const auto& [obj, subs] : sketch.AttachmentSupport.getSubListValues()) {
        if (!imprints(obj)) {
            continue;
        }
        try {
            auto shape = Part::Feature::getTopoShape(
                obj,
                Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
            );
            if (shape.isNull()) {
                continue;
            }
            // The support's shape is in its own container; the sketch's coordinates are its
            // placement in its container (as external geometry, ops#331)
            const Base::Matrix4D toLocal = (invPlm * sketch.externalFrame(obj, "")).toMatrix();
            const gp_Trsf trsf = Part::TopoShape::convert(toLocal);
            for (const auto& sub : subs) {
                auto face = shape.getSubTopoShape(sub.c_str(), /*silent*/ true);
                if (face.isNull() || face.shapeType(true) != TopAbs_FACE) {
                    continue;
                }
                for (const auto& edge : face.getSubTopoShapes(TopAbs_EDGE)) {
                    if (!liesInPlane(TopoDS::Edge(edge.getShape()), trsf)) {
                        continue;  // a face not in the sketch's plane (an offset sketch)
                    }
                    if (firstOnly) {
                        edges.push_back(edge);
                        return edges;
                    }
                    // A copy: the regions' face maker adds curves to its edges, which must not
                    // touch the model's (ops#316)
                    edges.push_back(Part::TopoShape(edge.Tag, edge.Hasher, edge.getHistoryAlgorithm())
                                        .makeElementTransform(
                                            edge,
                                            toLocal,
                        nullptr,
                        Part::CheckScale::noScaleCheck,
                        Part::CopyType::copy
                    ));
                }
            }
        }
        catch (const Base::Exception& e) {
            FC_WARN(sketch.getFullName() << ": no imprint from " << obj->getFullName() << ": "
                                         << e.what());
        }
        catch (const Standard_Failure& e) {
            FC_WARN(sketch.getFullName() << ": no imprint from " << obj->getFullName() << ": "
                                         << e.GetMessageString());
        }
    }
    return edges;
}

}  // namespace

Part::TopoShape Sketcher::imprintEdges(const SketchObject& sketch)
{
    auto edges = collectImprint(sketch, false);
    if (edges.empty()) {
        return {};
    }
    return sketch.makeTopoShape().makeElementCompound(edges);
}

bool Sketcher::hasImprint(const SketchObject& sketch)
{
    return !collectImprint(sketch, true).empty();
}

std::string Sketcher::imprintNearMode()
{
#ifdef _MSC_VER
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, "FREECAD_CH_IMPRINT_NEAR") != 0 || !value) {
        return {};
    }
    std::string text(value);
    std::free(value);
    return text;
#else
    const char* value = std::getenv("FREECAD_CH_IMPRINT_NEAR");
    return value ? std::string(value) : std::string();
#endif
}

std::vector<Part::TopoShape> Sketcher::nearImprintEdges(
    const Part::TopoShape& imprint,
    const Part::TopoShape& sketchEdges,
    bool& leftOutLoop
)
{
    leftOutLoop = false;
    std::vector<Part::TopoShape> all = imprint.getSubTopoShapes(TopAbs_EDGE);
    Bnd_Box own;
    for (TopExp_Explorer x(sketchEdges.getShape(), TopAbs_EDGE); x.More(); x.Next()) {
        BRepBndLib::Add(x.Current(), own);
    }
    if (own.IsVoid() || all.size() < 2 || imprintNearMode() == "off") {
        return all;
    }
    // Generous: a box too big keeps more edges, never fewer
    constexpr double margin = 1e-3;
    own.Enlarge(margin);
    const std::size_t n = all.size();
    std::vector<Bnd_Box> boxes(n);
    for (std::size_t i = 0; i < n; ++i) {
        BRepBndLib::Add(all[i].getShape(), boxes[i]);
        if (boxes[i].IsVoid()) {
            return all;  // an edge without a box: nothing is left out
        }
        boxes[i].Enlarge(margin);
    }
    // The groups: edges whose boxes overlap, by a sweep along x
    std::vector<std::size_t> parent(n);
    for (std::size_t i = 0; i < n; ++i) {
        parent[i] = i;
    }
    auto root = [&parent](std::size_t i) {
        while (parent[i] != i) {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        return i;
    };
    std::vector<std::size_t> order(n);
    std::vector<double> xmin(n), xmax(n);
    for (std::size_t i = 0; i < n; ++i) {
        order[i] = i;
        double y0 {}, z0 {}, y1 {}, z1 {};
        boxes[i].Get(xmin[i], y0, z0, xmax[i], y1, z1);
    }
    std::sort(order.begin(), order.end(), [&xmin](std::size_t a, std::size_t b) {
        return xmin[a] < xmin[b];
    });
    std::vector<std::size_t> active;
    for (std::size_t i : order) {
        std::erase_if(active, [&](std::size_t a) { return xmax[a] < xmin[i]; });
        for (std::size_t a : active) {
            if (!boxes[a].IsOut(boxes[i])) {
                parent[root(a)] = root(i);
            }
        }
        active.push_back(i);
    }
    std::vector<char> reaches(n, 0);
    for (std::size_t i = 0; i < n; ++i) {
        if (!boxes[i].IsOut(own)) {
            reaches[root(i)] = 1;
        }
    }
    // A group left out with a closed loop (as many edges as distinct vertices, or more) would have
    // made a cell of model edges alone
    std::map<std::size_t, std::pair<std::size_t, TopTools_IndexedMapOfShape>> leftOut;
    std::vector<Part::TopoShape> kept;
    for (std::size_t i = 0; i < n; ++i) {
        const std::size_t group = root(i);
        if (reaches[group]) {
            kept.push_back(all[i]);
            continue;
        }
        auto& [edgeCount, vertices] = leftOut[group];
        ++edgeCount;
        TopExp::MapShapes(all[i].getShape(), TopAbs_VERTEX, vertices);
    }
    for (const auto& [group, counts] : leftOut) {
        // Vertices of separately copied edges aren't shared: the same point counts once
        std::vector<gp_Pnt> points;
        for (int k = 1; k <= counts.second.Extent(); ++k) {
            const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(counts.second(k)));
            const double tolerance =
                std::max(margin, 2.0 * BRep_Tool::Tolerance(TopoDS::Vertex(counts.second(k))));
            if (std::none_of(points.begin(), points.end(), [&](const gp_Pnt& other) {
                    return other.Distance(point) <= tolerance;
                })) {
                points.push_back(point);
            }
        }
        if (counts.first >= points.size()) {
            leftOutLoop = true;
            break;
        }
    }
    return kept;
}

std::string Sketcher::regionsDifference(const Part::TopoShape& a, const Part::TopoShape& b)
{
    if (a.isNull() || b.isNull()) {
        return a.isNull() == b.isNull() ? std::string() : std::string("one is null");
    }
    if (a.getShape().ShapeType() != b.getShape().ShapeType()) {
        return "the shape types";
    }
    std::ostringstream ta;
    std::ostringstream tb;
    BRepTools::Write(a.getShape(), ta);
    BRepTools::Write(b.getShape(), tb);
    if (ta.str() != tb.str()) {
        return "the BRep text";
    }
    for (const char* type : {"Face", "Edge", "Vertex"}) {
        const int count = static_cast<int>(a.countSubShapes(type));
        if (count != static_cast<int>(b.countSubShapes(type))) {
            return std::string("the count of ") + type;
        }
        for (int i = 1; i <= count; ++i) {
            const Data::IndexedName name(type, i);
            const std::string na = a.getMappedName(name).toString();
            const std::string nb = b.getMappedName(name).toString();
            if (na != nb) {
                return std::string(type) + std::to_string(i) + ": " + na + " / " + nb;
            }
        }
    }
    return {};
}

Part::TopoShape Sketcher::withinSketchRegions(
    const Part::TopoShape& arrangement,
    const Part::TopoShape& sketchEdges,
    bool rebuild
)
{
    if (arrangement.isNull()) {
        return arrangement;
    }
    const auto cells = arrangement.getSubTopoShapes(TopAbs_FACE);
    const std::size_t n = cells.size();

    // The sketch's own edges, with their boxes
    std::vector<TopoDS_Edge> own;
    std::vector<Bnd_Box> ownBoxes;
    for (TopExp_Explorer x(sketchEdges.getShape(), TopAbs_EDGE); x.More(); x.Next()) {
        own.push_back(TopoDS::Edge(x.Current()));
        Bnd_Box box;
        BRepBndLib::Add(x.Current(), box);
        box.Enlarge(10 * Precision::Confusion());
        ownBoxes.push_back(box);
    }
    // An arrangement edge is the sketch's when it is one of the sketch's edges (the face maker keeps
    // the edges it doesn't split), or when its middle lies on one (a piece of it, or a model edge
    // drawn over it)
    TopTools_IndexedMapOfShape ownMap;
    for (const auto& edge : own) {
        ownMap.Add(edge);
    }
    // A piece of a sketch edge the face maker split keeps the edge's curve (BOPAlgo trims it): exact.
    // Else (a model edge over a sketch edge, a common block's representative), the piece lies on a
    // sketch edge at its middle and both quarter points: a model curve only tangent to a sketch
    // edge meets it at one point (review r1, T3)
    std::vector<Handle(Geom_Curve)> ownCurves;
    for (const auto& edge : own) {
        TopLoc_Location location;
        double first {}, last {};
        ownCurves.push_back(BRep_Tool::Curve(edge, location, first, last));
    }
    auto isSketchEdge = [&](const TopoDS_Edge& edge) {
        if (ownMap.Contains(edge)) {
            return true;
        }
        {
            TopLoc_Location location;
            double first {}, last {};
            Handle(Geom_Curve) c = BRep_Tool::Curve(edge, location, first, last);
            if (!c.IsNull() && std::ranges::find(ownCurves, c) != ownCurves.end()) {
                return true;
            }
        }
        BRepAdaptor_Curve curve(edge);
        const double f = curve.FirstParameter();
        const double l = curve.LastParameter();
        const std::array<gp_Pnt, 3> points {
            curve.Value(0.5 * (f + l)),
            curve.Value(0.75 * f + 0.25 * l),
            curve.Value(0.25 * f + 0.75 * l)
        };
        auto onSketchEdge = [&](std::size_t k, const gp_Pnt& point) {
            double first {}, last {};
            Handle(Geom_Curve) c = BRep_Tool::Curve(own[k], first, last);
            if (c.IsNull()) {
                return false;
            }
            gp_Pnt projected;
            double param {};
            return ShapeAnalysis_Curve().Project(
                       c,  // with the edge's location (BRep_Tool::Curve)
                       point,
                       Precision::Confusion(),
                       projected,
                       param,
                       first,
                       last,
                       false
                   )
                <= 10 * Precision::Confusion();
        };
        const gp_Pnt& middle = points[0];
        for (std::size_t k = 0; k < own.size(); ++k) {
            if (ownBoxes[k].IsOut(middle)) {
                continue;
            }
            if (onSketchEdge(k, points[0]) && onSketchEdge(k, points[1])
                && onSketchEdge(k, points[2])) {
                return true;
            }
        }
        return false;
    };

    TopTools_IndexedMapOfShape edges;
    std::vector<std::vector<int>> cellEdges(n);
    for (std::size_t i = 0; i < n; ++i) {
        TopTools_IndexedMapOfShape mine;
        TopExp::MapShapes(cells[i].getShape(), TopAbs_EDGE, mine);
        for (int k = 1; k <= mine.Extent(); ++k) {
            cellEdges[i].push_back(edges.Add(mine(k)));
        }
    }
    std::vector<std::vector<std::size_t>> edgeCells(edges.Extent() + 1);
    for (std::size_t i = 0; i < n; ++i) {
        for (int e : cellEdges[i]) {
            edgeCells[e].push_back(i);
        }
    }
    std::vector<char> sketchSide(edges.Extent() + 1, 0);
    for (int e = 1; e <= edges.Extent(); ++e) {
        sketchSide[e] = isSketchEdge(TopoDS::Edge(edges(e))) ? 1 : 0;
    }

    // Cells joined across model edges are one region of the sketch's curves alone; it is the
    // outside of the sketch's curves when a model edge of it borders no other cell
    std::vector<long> component(n, -1);
    std::vector<bool> outside;
    for (std::size_t start = 0; start < n; ++start) {
        if (component[start] >= 0) {
            continue;
        }
        const long id = static_cast<long>(outside.size());
        outside.push_back(false);
        std::vector<std::size_t> queue {start};
        component[start] = id;
        while (!queue.empty()) {
            const auto c = queue.back();
            queue.pop_back();
            for (int e : cellEdges[c]) {
                if (sketchSide[e]) {
                    continue;
                }
                if (edgeCells[e].size() < 2) {
                    outside[id] = true;
                }
                for (auto d : edgeCells[e]) {
                    if (component[d] < 0) {
                        component[d] = id;
                        queue.push_back(d);
                    }
                }
            }
        }
    }
    std::vector<Part::TopoShape> kept;
    for (std::size_t i = 0; i < n; ++i) {
        if (!outside[component[i]]) {
            kept.push_back(cells[i]);
        }
    }
    if (kept.size() == n && !rebuild) {
        return arrangement;
    }
    if (kept.empty()) {
        return {};
    }
    Part::TopoShape result(arrangement.Tag, arrangement.Hasher, arrangement.getHistoryAlgorithm());
    result.makeElementCompound(kept);
    return result;
}
