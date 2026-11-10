// SPDX-License-Identifier: LGPL-2.1-or-later

// A sketch's profile as Onshape's regions (FreeCAD-CH, feat/profile-regions): see ProfileRegions.h

#include <algorithm>
#include <cmath>
#include <numeric>
#include <unordered_map>

#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepGProp.hxx>
#include <Precision.hxx>
#include <BRepTools.hxx>
#include <Geom_Curve.hxx>
#include <GProp_GProps.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <Base/Console.h>
#include <Mod/Part/App/FaceMaker.h>
#include <Mod/Sketcher/App/SketchImprint.h>
#include <Mod/Sketcher/App/SketchObject.h>

#include "ProfileRegions.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

using Part::TopoShape;

namespace
{

/// The bounded faces of a sketch's arrangement, judged by Onshape's whole-sketch rule
struct Analysis
{
    std::vector<bool> kept;
    /// for each face kept, the faces kept it shares a side with have the same group
    std::vector<std::size_t> group;
    bool simple = false;
};

std::size_t findRoot(std::vector<std::size_t>& parent, std::size_t i)
{
    while (parent[i] != i) {
        parent[i] = parent[parent[i]];
        i = parent[i];
    }
    return i;
}

Analysis analyse(const std::vector<TopoDS_Face>& cells)
{
    Analysis a;
    const std::size_t n = cells.size();
    a.kept.assign(n, true);
    a.group.resize(n);
    std::iota(a.group.begin(), a.group.end(), 0);

    TopTools_IndexedMapOfShape edges;
    std::vector<std::size_t> wireCount(n, 0);
    std::vector<std::vector<int>> cellEdges(n);
    for (std::size_t i = 0; i < n; ++i) {
        for (TopoDS_Iterator it(cells[i]); it.More(); it.Next()) {
            if (it.Value().ShapeType() == TopAbs_WIRE) {
                ++wireCount[i];
            }
        }
        TopTools_IndexedMapOfShape own;
        TopExp::MapShapes(cells[i], TopAbs_EDGE, own);
        for (int k = 1; k <= own.Extent(); ++k) {
            cellEdges[i].push_back(edges.Add(own(k)));  // orientation and location aside (IsSame)
        }
    }
    // The cells on each edge (one or two); an edge on the outer boundary of all the regions is a
    // side of one cell, once (a dangling edge kept inside a cell is a side twice, or internal)
    std::vector<std::vector<std::size_t>> edgeCells(edges.Extent() + 1);
    std::vector<int> sides(edges.Extent() + 1, 0);
    for (std::size_t i = 0; i < n; ++i) {
        for (int e : cellEdges[i]) {
            edgeCells[e].push_back(i);
        }
        for (TopExp_Explorer x(cells[i], TopAbs_EDGE); x.More(); x.Next()) {
            const int e = edges.FindIndex(x.Current());
            const auto o = x.Current().Orientation();
            sides[e] += (o == TopAbs_FORWARD || o == TopAbs_REVERSED) ? 1 : 2;
        }
    }
    auto onBoundary = [&](int e) {
        return sides[e] == 1;
    };

    // filterInnerLoops (Onshape, PR1-PR4, PRQ1, PRQ2): a curve of the sketch that touches the outer
    // boundary of all the regions (an edge of it on that boundary, or a point of it on one) bounds
    // no hole; the cells the other curves enclose are left out, whatever their own boundary. So a
    // line from side to side through a circle keeps the circle a hole (PRQ1), a circle tangent to
    // the outer side from inside is no hole (PR4), and a square across a hole's corner is left out
    // whole, its part in the material too (PRQ2). The cells' edges are pieces of the sketch's
    // curves, each keeping its curve (BOPAlgo trims it): the curve is the edge's Geom_Curve.
    std::vector<std::size_t> curveOf(edges.Extent() + 1, 0);
    {
        std::unordered_map<const Geom_Curve*, std::size_t> curves;
        std::size_t curveCount = 0;
        for (int e = 1; e <= edges.Extent(); ++e) {
            TopLoc_Location location;
            double first {}, last {};
            const Handle(Geom_Curve) c =
                BRep_Tool::Curve(TopoDS::Edge(edges(e)), location, first, last);
            if (c.IsNull()) {
                curveOf[e] = curveCount++;  // no curve: a curve of its own
                continue;
            }
            const auto [it, added] = curves.try_emplace(c.get(), curveCount);
            curveCount += added ? 1 : 0;
            curveOf[e] = it->second;
        }
        std::vector<bool> touching(curveCount, false);
        TopTools_IndexedMapOfShape boundaryVertices;
        for (int e = 1; e <= edges.Extent(); ++e) {
            if (onBoundary(e)) {
                touching[curveOf[e]] = true;
                TopExp::MapShapes(edges(e), TopAbs_VERTEX, boundaryVertices);
            }
        }
        for (int e = 1; e <= edges.Extent(); ++e) {
            for (TopExp_Explorer v(edges(e), TopAbs_VERTEX); v.More() && !touching[curveOf[e]];
                 v.Next()) {
                touching[curveOf[e]] = boundaryVertices.Contains(v.Current());
            }
        }
        // a flood from the outside (the cells on the outer boundary) across the touching curves
        std::vector<bool> reached(n, false);
        std::vector<std::size_t> queue;
        for (std::size_t i = 0; i < n; ++i) {
            for (int e : cellEdges[i]) {
                if (onBoundary(e) && !reached[i]) {
                    reached[i] = true;
                    queue.push_back(i);
                }
            }
        }
        while (!queue.empty()) {
            const auto c = queue.back();
            queue.pop_back();
            for (int e : cellEdges[c]) {
                if (!touching[curveOf[e]]) {
                    continue;
                }
                for (auto d : edgeCells[e]) {
                    if (!reached[d]) {
                        reached[d] = true;
                        queue.push_back(d);
                    }
                }
            }
        }
        for (std::size_t i = 0; i < n; ++i) {
            a.kept[i] = reached[i];
        }
    }
    bool islands = false;
    for (std::size_t i = 0; i < n; ++i) {
        islands = islands || (!a.kept[i] && wireCount[i] > 1);
    }

    // Disjoint simple loops: every vertex of the regions' sides is on exactly two of them (a
    // closed edge counts twice). Crossings, a shared side, a touching point and a line from a
    // loop all make a vertex on three or more.
    BRep_Builder builder;
    TopoDS_Compound all;
    builder.MakeCompound(all);
    for (const auto& cell : cells) {
        builder.Add(all, cell);
    }
    TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
    TopExp::MapShapesAndUniqueAncestors(all, TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
    bool twoEach = true;
    for (int v = 1; twoEach && v <= vertexEdges.Extent(); ++v) {
        int degree = 0;
        for (const auto& e : vertexEdges(v)) {
            const TopoDS_Edge& edge = TopoDS::Edge(e);
            degree += TopExp::FirstVertex(edge).IsSame(TopExp::LastVertex(edge)) ? 2 : 1;
        }
        twoEach = degree == 2;
    }
    a.simple = twoEach && !islands;

    // Regions kept that share a side make one face
    std::vector<std::size_t> parent(n);
    std::iota(parent.begin(), parent.end(), 0);
    std::vector<long> owner(edges.Extent() + 1, -1);
    for (std::size_t i = 0; i < n; ++i) {
        if (!a.kept[i]) {
            continue;
        }
        for (TopExp_Explorer x(cells[i], TopAbs_EDGE); x.More(); x.Next()) {
            const int e = edges.FindIndex(x.Current());
            if (e <= 0) {
                continue;
            }
            if (owner[e] < 0) {
                owner[e] = static_cast<long>(i);
            }
            else {
                parent[findRoot(parent, i)] = findRoot(parent, static_cast<std::size_t>(owner[e]));
            }
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        a.group[i] = findRoot(parent, i);
    }
    return a;
}

double area(const TopoDS_Shape& face)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(face, props);
    return props.Mass();
}

TopoShape prototype(const TopoShape& like)
{
    return TopoShape(0, like.Hasher, like.getHistoryAlgorithm());
}

/// Faces that share their sides (one face maker's), merged into one
std::vector<TopoShape> mergeShared(const std::vector<TopoShape>& group, const TopoShape& like)
{
    if (group.size() < 2) {
        return group;
    }
    TopoShape shell = prototype(like).makeElementCompound(group);
    shell.makeElementShell(false);
    return shell.makeElementRefine().getSubTopoShapes(TopAbs_FACE);
}

/// The arrangement of the wires' curves (as the sketch makes its regions); named: with element
/// names (the faces made), else topology only (the rule's decision: about a third of the cost on
/// 750 squares)
TopoShape arrangementOf(const TopoShape& wires, bool named)
{
    std::vector<TopoShape> shapes = wires.getSubTopoShapes(TopAbs_WIRE);
    for (auto& edge : wires.getSubTopoShapes(TopAbs_EDGE, TopAbs_WIRE)) {
        shapes.push_back(std::move(edge));
    }
    if (shapes.empty()) {
        return {};
    }
    try {
        return prototype(wires).makeElementFace(
            shapes,
            nullptr,
            "Part::FaceMakerBuildFace",
            nullptr,
            named ? Part::ElementMapPolicy::Propagate : Part::ElementMapPolicy::Drop
        );
    }
    catch (const Part::NullShapeException&) {
        return {};  // no bounded region
    }
}

std::vector<TopoDS_Face> facesOf(const TopoDS_Shape& shape)
{
    std::vector<TopoDS_Face> faces;
    if (shape.IsNull()) {
        return faces;
    }
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, TopAbs_FACE, map);
    for (int i = 1; i <= map.Extent(); ++i) {
        faces.push_back(TopoDS::Face(map(i)));
    }
    return faces;
}

const Sketcher::SketchObject* sketchOf(const App::DocumentObject* profile)
{
    if (!profile) {
        return nullptr;
    }
    return dynamic_cast<const Sketcher::SketchObject*>(profile->getLinkedObject(true));
}

/// The sketch's regions as it made them, when they are those of its own curves alone: the
/// arrangement of new sketches, without model edges
bool ownRegions(const Sketcher::SketchObject* sketch)
{
    return sketch && sketch->MakeInternals.getValue() && sketch->_InternalFaceVersion.getValue() >= 2
        && !Sketcher::hasImprint(*sketch);
}

}  // namespace

namespace PartDesign
{

WholeSketchRegions::WholeSketchRegions(const App::DocumentObject* profile, const TopoShape& wires)
    : wires(wires)
{
    std::vector<TopoDS_Face> cells;
    if (const auto* sketch = sketchOf(profile); ownRegions(sketch)) {
        // Topology only: the sketch's own coordinates do
        cells = facesOf(sketch->InternalShape.getShape().getShape());
    }
    if (cells.empty()) {
        cells = facesOf(arrangementOf(wires, false).getShape());
    }
    const Analysis a = analyse(cells);
    simple = a.simple;
    for (std::size_t i = 0; i < cells.size(); ++i) {
        if (a.kept[i]) {
            ++keptCount;
            keptArea += area(cells[i]);
        }
    }
}

bool WholeSketchRegions::matches(const TopoShape& faces) const
{
    if (faces.isNull() || faces.countSubShapes(TopAbs_FACE) != keptCount) {
        return false;
    }
    return std::abs(area(faces.getShape()) - keptArea) <= 1e-7 * std::max(1.0, keptArea);
}

TopoShape WholeSketchRegions::faces() const
{
    const TopoShape arrangement = arrangementOf(wires, true);
    const auto cells = arrangement.isNull() ? std::vector<TopoShape>()
                                            : arrangement.getSubTopoShapes(TopAbs_FACE);
    std::vector<TopoDS_Face> plain;
    plain.reserve(cells.size());
    for (const auto& cell : cells) {
        plain.push_back(TopoDS::Face(cell.getShape()));
    }
    const Analysis a = analyse(plain);
    std::vector<std::size_t> roots;
    for (std::size_t i = 0; i < cells.size(); ++i) {
        if (a.kept[i] && std::ranges::find(roots, a.group[i]) == roots.end()) {
            roots.push_back(a.group[i]);
        }
    }
    std::vector<TopoShape> result;
    for (auto root : roots) {
        std::vector<TopoShape> group;
        for (std::size_t i = 0; i < cells.size(); ++i) {
            if (a.kept[i] && a.group[i] == root) {
                group.push_back(cells[i]);
            }
        }
        for (auto& face : mergeShared(group, wires)) {
            result.push_back(std::move(face));
        }
    }
    if (result.empty()) {
        return {};
    }
    return prototype(wires).makeElementCompound(
        result,
        nullptr,
        TopoShape::SingleShapeCompoundCreationPolicy::returnShape
    );
}

bool picksRegions(const std::vector<std::string>& subs)
{
    const std::string prefix = Sketcher::SketchObject::internalPrefix() + "Face";
    return std::ranges::any_of(subs, [&prefix](const std::string& sub) {
        const std::string element = Data::oldElementName(Data::findElementName(sub.c_str()));
        return element.compare(0, prefix.size(), prefix) == 0;
    });
}

TopoShape wiresOfFaces(const TopoShape& faces)
{
    std::vector<TopoShape> wires;
    for (const auto& face : faces.getSubTopoShapes(TopAbs_FACE)) {
        // the outer wire first, then the holes'
        const TopoDS_Wire outer = BRepTools::OuterWire(TopoDS::Face(face.getShape()));
        auto own = face.getSubTopoShapes(TopAbs_WIRE);
        std::stable_partition(own.begin(), own.end(), [&outer](const TopoShape& wire) {
            return wire.getShape().IsSame(outer);
        });
        for (auto& wire : own) {
            wires.push_back(std::move(wire));
        }
    }
    if (wires.empty()) {
        return {};
    }
    return prototype(faces).makeElementCompound(wires);
}

std::vector<TopoShape> outerLoopsFirst(const std::vector<TopoShape>& wires, std::size_t* holes)
{
    const std::size_t n = wires.size();
    std::vector<bool> hole(n, false);
    if (n > 1) {
        std::vector<TopoDS_Face> faces(n);
        for (std::size_t j = 0; j < n; ++j) {
            BRepBuilderAPI_MakeFace mk(TopoDS::Wire(wires[j].getShape()), /*OnlyPlane*/ true);
            if (mk.IsDone()) {
                faces[j] = mk.Face();
            }
        }
        for (std::size_t i = 0; i < n; ++i) {
            TopExp_Explorer x(wires[i].getShape(), TopAbs_EDGE);
            if (!x.More()) {
                continue;
            }
            BRepAdaptor_Curve curve(TopoDS::Edge(x.Current()));
            const gp_Pnt middle
                = curve.Value(0.5 * (curve.FirstParameter() + curve.LastParameter()));
            int around = 0;
            for (std::size_t j = 0; j < n; ++j) {
                if (j == i || faces[j].IsNull()) {
                    continue;
                }
                BRepClass_FaceClassifier inside(faces[j], middle, Precision::Confusion());
                around += inside.State() == TopAbs_IN ? 1 : 0;
            }
            hole[i] = around % 2 == 1;
        }
    }
    std::vector<TopoShape> ordered;
    ordered.reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        if (!hole[i]) {
            ordered.push_back(wires[i]);
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        if (hole[i]) {
            ordered.push_back(wires[i]);
        }
    }
    if (holes) {
        *holes = static_cast<std::size_t>(std::ranges::count(hole, true));
    }
    return ordered;
}

TopoShape mergeAdjacentRegions(
    const App::DocumentObject* profile,
    const std::vector<std::string>& subs,
    const TopoShape& faces
)
{
    const auto* sketch = sketchOf(profile);
    if (!sketch || subs.size() < 2) {
        return faces;
    }
    const auto picked = faces.getSubTopoShapes(TopAbs_FACE);
    if (picked.size() != subs.size()) {
        return faces;  // an element left out (a reference solver document) or not a face
    }
    // Which of the sketch's regions each pick is: their sides are shared in its InternalShape
    const std::string prefix = Sketcher::SketchObject::internalPrefix() + "Face";
    std::vector<int> index;
    for (const auto& sub : subs) {
        const std::string element = Data::oldElementName(Data::findElementName(sub.c_str()));
        if (element.compare(0, prefix.size(), prefix) != 0) {
            return faces;
        }
        try {
            index.push_back(std::stoi(element.substr(prefix.size())));
        }
        catch (const std::exception&) {
            return faces;
        }
    }
    const auto cells = facesOf(sketch->InternalShape.getShape().getShape());
    std::vector<TopoDS_Face> chosen;
    for (int i : index) {
        if (i < 1 || i > static_cast<int>(cells.size())) {
            return faces;
        }
        chosen.push_back(cells[i - 1]);
    }
    // Picks that share a side, in the sketch's regions, make one face
    std::vector<std::size_t> group(chosen.size());
    std::iota(group.begin(), group.end(), 0);
    {
        TopTools_IndexedMapOfShape edges;
        std::vector<long> owner;
        for (std::size_t i = 0; i < chosen.size(); ++i) {
            for (TopExp_Explorer x(chosen[i], TopAbs_EDGE); x.More(); x.Next()) {
                const int e = edges.Add(x.Current());
                if (static_cast<int>(owner.size()) <= e) {
                    owner.resize(e + 1, -1);
                }
                if (owner[e] < 0) {
                    owner[e] = static_cast<long>(i);
                }
                else if (owner[e] != static_cast<long>(i)) {
                    group[findRoot(group, i)] = findRoot(group, static_cast<std::size_t>(owner[e]));
                }
            }
        }
        for (std::size_t i = 0; i < chosen.size(); ++i) {
            group[i] = findRoot(group, i);
        }
    }
    bool adjacent = false;
    for (std::size_t i = 0; i < chosen.size() && !adjacent; ++i) {
        adjacent = group[i] != i;
    }
    if (!adjacent) {
        return faces;
    }
    // The picks were read one by one, so they don't share their sides: fused first
    std::vector<TopoShape> result;
    std::vector<std::size_t> roots;
    for (std::size_t i = 0; i < chosen.size(); ++i) {
        if (std::ranges::find(roots, group[i]) != roots.end()) {
            continue;
        }
        roots.push_back(group[i]);
        std::vector<TopoShape> members;
        for (std::size_t j = 0; j < chosen.size(); ++j) {
            if (group[j] == group[i]) {
                members.push_back(picked[j]);
            }
        }
        if (members.size() == 1) {
            result.push_back(members.front());
            continue;
        }
        TopoShape fused = prototype(faces);
        fused.makeElementFuse(members);
        for (auto& face : mergeShared(fused.getSubTopoShapes(TopAbs_FACE), faces)) {
            result.push_back(std::move(face));
        }
    }
    return prototype(faces).makeElementCompound(
        result,
        nullptr,
        TopoShape::SingleShapeCompoundCreationPolicy::returnShape
    );
}

}  // namespace PartDesign
