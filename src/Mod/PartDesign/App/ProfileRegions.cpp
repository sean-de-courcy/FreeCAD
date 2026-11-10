// SPDX-License-Identifier: LGPL-2.1-or-later

// A sketch's profile as Onshape's regions (FreeCAD-CH, feat/profile-regions): see ProfileRegions.h

#include <algorithm>
#include <cmath>
#include <numeric>
#include <set>

#include <BRep_Builder.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
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

std::vector<int> edgeKey(const TopoDS_Shape& wire, TopTools_IndexedMapOfShape& edges)
{
    std::vector<int> key;
    for (TopExp_Explorer x(wire, TopAbs_EDGE); x.More(); x.Next()) {
        key.push_back(edges.Add(x.Current()));  // orientation and location aside (IsSame)
    }
    std::ranges::sort(key);
    key.erase(std::unique(key.begin(), key.end()), key.end());
    return key;
}

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
    // (cell, its holes' edge sets); a hole is an inner wire that shares no vertex with the cell's
    // outer wire: a loop touching the outer boundary is no hole (Onshape, PR4)
    std::vector<std::pair<std::size_t, std::vector<int>>> holes;
    for (std::size_t i = 0; i < n; ++i) {
        const TopoDS_Wire outerWire = BRepTools::OuterWire(cells[i]);
        TopTools_IndexedMapOfShape outerVertices;
        TopExp::MapShapes(outerWire, TopAbs_VERTEX, outerVertices);
        for (TopoDS_Iterator it(cells[i]); it.More(); it.Next()) {
            if (it.Value().ShapeType() != TopAbs_WIRE) {
                continue;
            }
            ++wireCount[i];
            if (it.Value().IsSame(outerWire)) {
                edgeKey(it.Value(), edges);
                continue;
            }
            bool touches = false;
            for (TopExp_Explorer v(it.Value(), TopAbs_VERTEX); v.More() && !touches; v.Next()) {
                touches = outerVertices.Contains(v.Current());
            }
            auto key = edgeKey(it.Value(), edges);
            if (!touches) {
                holes.emplace_back(i, std::move(key));
            }
        }
    }
    // The cells on each edge (one or two)
    std::vector<std::vector<std::size_t>> edgeCells(edges.Extent() + 1);
    std::vector<std::vector<int>> cellEdges(n);
    for (std::size_t i = 0; i < n; ++i) {
        TopTools_IndexedMapOfShape own;
        TopExp::MapShapes(cells[i], TopAbs_EDGE, own);
        for (int k = 1; k <= own.Extent(); ++k) {
            const int e = edges.FindIndex(own(k));
            if (e > 0) {
                edgeCells[e].push_back(i);
                cellEdges[i].push_back(e);
            }
        }
    }
    // filterInnerLoops: every region inside another region's hole is left out, whatever its own
    // boundary (Onshape, PR1 and PR3): a flood from the hole's sides inwards, across shared sides
    // other than the hole's
    std::vector<bool> inside(n, false);
    for (const auto& [owner, hole] : holes) {
        std::vector<std::size_t> queue;
        for (int e : hole) {
            for (auto c : edgeCells[e]) {
                if (c != owner && !inside[c]) {
                    inside[c] = true;
                    queue.push_back(c);
                }
            }
        }
        while (!queue.empty()) {
            const auto c = queue.back();
            queue.pop_back();
            for (int e : cellEdges[c]) {
                if (std::ranges::binary_search(hole, e)) {
                    continue;
                }
                for (auto d : edgeCells[e]) {
                    if (d != owner && !inside[d]) {
                        inside[d] = true;
                        queue.push_back(d);
                    }
                }
            }
        }
    }
    bool islands = false;
    for (std::size_t i = 0; i < n; ++i) {
        a.kept[i] = !inside[i];
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
        && Sketcher::imprintEdges(*sketch).isNull();
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
