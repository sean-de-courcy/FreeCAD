// SPDX-License-Identifier: LGPL-2.1-or-later

#include "TopoShapeMatch.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

#include <Bnd_Box.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepLProp_SLProps.hxx>
#include <BRepTools.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Surface.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GProp_GProps.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>
#include <Standard_Failure.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include <App/ElementMap.h>
#include <App/ElementNamingUtils.h>
#include <App/MappedName.h>
#include <Base/Console.h>

#include "MassProperties.h"
#include "TopoShape.h"

FC_LOG_LEVEL_INIT("TopoShape", true, true)  // NOLINT

namespace Part
{

namespace
{

// The tolerance of a place: 1e-7 of the shape's size, at least 1e-7 (part D's epsilon)
double placeTolerance(const TopoDS_Shape& shape)
{
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    if (box.IsVoid()) {
        return 1e-7;
    }
    box.SetGap(0.0);
    return 1e-7 * std::max(1.0, std::sqrt(box.SquareExtent()));
}

// The distance of a point to a shape, as Part's isInside() measures it for a face or an edge
double distanceTo(const TopoDS_Shape& shape, const gp_Pnt& point)
{
    try {
        BRepExtrema_DistShapeShape distance(BRepBuilderAPI_MakeVertex(point).Vertex(), shape);
        if (distance.IsDone()) {
            return distance.Value();
        }
    }
    catch (const Standard_Failure&) {
    }
    return HUGE_VAL;
}

gp_Pnt midpointOf(const TopoDS_Edge& edge)
{
    BRepAdaptor_Curve curve(edge);
    return curve.Value(0.5 * (curve.FirstParameter() + curve.LastParameter()));
}

// The kind of an edge's curve, -1 for a degenerated edge
int curveKind(const TopoDS_Edge& edge)
{
    if (BRep_Tool::Degenerated(edge)) {
        return -1;
    }
    try {
        return static_cast<int>(BRepAdaptor_Curve(edge).GetType());
    }
    catch (const Standard_Failure&) {
        return -1;
    }
}

std::vector<int> sorted(std::vector<int> items)
{
    std::sort(items.begin(), items.end());
    return items;
}

// The pairs of {new: candidates} whose candidate is the only one and is no other new element's
// candidate either
std::map<int, int> uniquePairs(const std::map<int, std::vector<int>>& candidates)
{
    std::map<int, int> back;
    for (const auto& [element, olds] : candidates) {
        for (const int old : olds) {
            ++back[old];
        }
    }
    std::map<int, int> pairs;
    for (const auto& [element, olds] : candidates) {
        if (olds.size() == 1 && back[olds.front()] == 1) {
            pairs[element] = olds.front();
        }
    }
    return pairs;
}

// A face's surface, as far as two faces at one place compare: its kind, and for the kinds that
// have them its placement and sizes
struct SurfaceKey
{
    int kind = -1;
    std::vector<double> lengths;  // compared within the place tolerance
    std::vector<double> directions;  // compared within 1e-6

    bool same(const SurfaceKey& other, double tolerance) const
    {
        if (kind != other.kind || lengths.size() != other.lengths.size()
            || directions.size() != other.directions.size()) {
            return false;
        }
        for (std::size_t i = 0; i < lengths.size(); ++i) {
            if (std::abs(lengths[i] - other.lengths[i]) > std::max(tolerance, 1e-6)) {
                return false;
            }
        }
        for (std::size_t i = 0; i < directions.size(); ++i) {
            if (std::abs(directions[i] - other.directions[i]) > 1e-6) {
                return false;
            }
        }
        return true;
    }
};

SurfaceKey surfaceKey(const TopoDS_Face& face)
{
    SurfaceKey key;
    try {
        BRepAdaptor_Surface surface(face, false);
        key.kind = static_cast<int>(surface.GetType());
        auto place = [&key](const gp_Pnt& point) {
            key.lengths.insert(key.lengths.end(), {point.X(), point.Y(), point.Z()});
        };
        switch (surface.GetType()) {
            case GeomAbs_Plane: {
                const gp_Pln plane = surface.Plane();
                gp_Dir normal = plane.Axis().Direction();
                const double offset = gp_Vec(plane.Location().XYZ()).Dot(gp_Vec(normal));
                if (face.Orientation() == TopAbs_REVERSED) {
                    normal.Reverse();
                }
                key.directions = {normal.X(), normal.Y(), normal.Z()};
                key.lengths = {offset};
                break;
            }
            case GeomAbs_Cylinder:
                place(surface.Cylinder().Location());
                key.lengths.push_back(surface.Cylinder().Radius());
                break;
            case GeomAbs_Cone:
                place(surface.Cone().Location());
                key.lengths.push_back(surface.Cone().RefRadius());
                break;
            case GeomAbs_Sphere:
                place(surface.Sphere().Location());
                key.lengths.push_back(surface.Sphere().Radius());
                break;
            case GeomAbs_Torus:
                place(surface.Torus().Location());
                key.lengths.push_back(surface.Torus().MajorRadius());
                key.lengths.push_back(surface.Torus().MinorRadius());
                break;
            case GeomAbs_BSplineSurface: {
                const auto bspline = surface.BSpline();
                const TColgp_Array2OfPnt& poles = bspline->Poles();
                for (int i = poles.LowerRow(); i <= poles.UpperRow(); ++i) {
                    for (int j = poles.LowerCol(); j <= poles.UpperCol(); ++j) {
                        place(poles(i, j));
                    }
                }
                break;
            }
            default:
                break;
        }
    }
    catch (const Standard_Failure&) {
        key.kind = -1;
    }
    return key;
}

// A grid of points for the lookup of those at a place
class PointGrid
{
public:
    PointGrid(const std::vector<gp_Pnt>& points, double tolerance)
        : points(points)
        , tolerance(tolerance)
    {
        for (int i = 0; i < static_cast<int>(points.size()); ++i) {
            cells[cellOf(points[i])].push_back(i);
        }
    }

    // The points within the tolerance of \a point
    std::vector<int> at(const gp_Pnt& point) const
    {
        std::vector<int> found;
        const auto [x, y, z] = cellOf(point);
        for (std::int64_t dx = -1; dx <= 1; ++dx) {
            for (std::int64_t dy = -1; dy <= 1; ++dy) {
                for (std::int64_t dz = -1; dz <= 1; ++dz) {
                    const auto it = cells.find({x + dx, y + dy, z + dz});
                    if (it == cells.end()) {
                        continue;
                    }
                    for (const int i : it->second) {
                        if (points[i].Distance(point) <= tolerance) {
                            found.push_back(i);
                        }
                    }
                }
            }
        }
        std::sort(found.begin(), found.end());
        return found;
    }

private:
    using Cell = std::array<std::int64_t, 3>;
    struct CellHash
    {
        std::size_t operator()(const Cell& cell) const
        {
            std::size_t hash = 0;
            for (const auto c : cell) {
                hash = hash * 1000003u ^ std::hash<std::int64_t>()(c);
            }
            return hash;
        }
    };

    Cell cellOf(const gp_Pnt& point) const
    {
        auto index = [this](double c) {
            return static_cast<std::int64_t>(std::floor(c / tolerance));
        };
        return {index(point.X()), index(point.Y()), index(point.Z())};
    }

    const std::vector<gp_Pnt>& points;
    double tolerance;
    std::unordered_map<Cell, std::vector<int>, CellHash> cells;
};

// A shape's elements, from 0, and how they bound each other
struct Topology
{
    TopoDS_Shape shape;
    TopTools_IndexedMapOfShape vertexes;
    TopTools_IndexedMapOfShape edges;
    TopTools_IndexedMapOfShape faces;
    std::vector<gp_Pnt> points;
    // the vertices of each edge, the edges and the vertices (sorted) of each face, in the order
    // of their own maps
    std::vector<std::vector<int>> edgeVertexes;
    std::vector<std::vector<int>> faceEdges;
    std::vector<std::vector<int>> faceVertexes;
    // the vertices sharing an edge with each vertex, and the number of faces at each
    std::vector<std::set<int>> neighbours;
    std::vector<int> vertexFaces;
    // the piece of each face and vertex: the solid holding it, else the shell, else the face
    std::vector<int> facePiece;
    std::vector<int> vertexPiece;
    double tolerance;

    explicit Topology(const TopoDS_Shape& shape)
        : shape(shape)
        , tolerance(placeTolerance(shape))
    {
        TopExp::MapShapes(shape, TopAbs_VERTEX, vertexes);
        TopExp::MapShapes(shape, TopAbs_EDGE, edges);
        TopExp::MapShapes(shape, TopAbs_FACE, faces);
        for (int i = 1; i <= vertexes.Extent(); ++i) {
            points.push_back(BRep_Tool::Pnt(TopoDS::Vertex(vertexes(i))));
        }
        auto indexes = [](const TopoDS_Shape& element,
                          TopAbs_ShapeEnum type,
                          const TopTools_IndexedMapOfShape& all) {
            TopTools_IndexedMapOfShape own;
            TopExp::MapShapes(element, type, own);
            std::vector<int> found;
            for (int k = 1; k <= own.Extent(); ++k) {
                found.push_back(all.FindIndex(own(k)) - 1);
            }
            return found;
        };
        neighbours.resize(points.size());
        for (int i = 1; i <= edges.Extent(); ++i) {
            edgeVertexes.push_back(indexes(edges(i), TopAbs_VERTEX, vertexes));
            const auto& ends = edgeVertexes.back();
            if (ends.size() == 2 && ends[0] != ends[1] && ends[0] >= 0 && ends[1] >= 0) {
                neighbours[ends[0]].insert(ends[1]);
                neighbours[ends[1]].insert(ends[0]);
            }
        }
        vertexFaces.assign(points.size(), 0);
        for (int i = 1; i <= faces.Extent(); ++i) {
            faceEdges.push_back(indexes(faces(i), TopAbs_EDGE, edges));
            faceVertexes.push_back(sorted(indexes(faces(i), TopAbs_VERTEX, vertexes)));
            for (const int v : faceVertexes.back()) {
                if (v >= 0) {
                    ++vertexFaces[v];
                }
            }
        }
        facePiece.assign(faces.Extent(), -1);
        vertexPiece.assign(points.size(), -1);
        for (const auto type : {TopAbs_SOLID, TopAbs_SHELL, TopAbs_FACE}) {
            TopTools_IndexedMapOfShape groups;
            TopExp::MapShapes(shape, type, groups);
            if (groups.IsEmpty()) {
                continue;
            }
            for (int k = 1; k <= groups.Extent(); ++k) {
                for (const int f : indexes(groups(k), TopAbs_FACE, faces)) {
                    if (f >= 0 && facePiece[f] < 0) {
                        facePiece[f] = k - 1;
                    }
                }
                for (const int v : indexes(groups(k), TopAbs_VERTEX, vertexes)) {
                    if (v >= 0 && vertexPiece[v] < 0) {
                        vertexPiece[v] = k - 1;
                    }
                }
            }
            break;
        }
    }

    const TopoDS_Face& face(int i) const
    {
        return TopoDS::Face(faces(i + 1));
    }

    const TopoDS_Edge& edge(int i) const
    {
        return TopoDS::Edge(edges(i + 1));
    }

    // Whether \a point lies on the face (IN or ON within the tolerance)
    bool onFace(int i, const gp_Pnt& point) const
    {
        const Bnd_Box& box = faceBox(i);
        if (box.IsOut(point)) {
            return false;
        }
        return distanceTo(face(i), point) <= tolerance;
    }

    // A point inside the face: its centre of mass if that is on it, else the first of a 7 x 7
    // grid of its parameters that is
    const gp_Pnt& innerPoint(int i) const
    {
        auto& cached = innerPoints[i];
        if (cached) {
            return *cached;
        }
        const TopoDS_Face& f = face(i);
        GProp_GProps props;
        MassProperties::surfaceProperties(f, props);
        gp_Pnt found = props.CentreOfMass();
        if (!onFace(i, found)) {
            try {
                double u0 = 0.0;
                double u1 = 0.0;
                double v0 = 0.0;
                double v1 = 0.0;
                BRepTools::UVBounds(f, u0, u1, v0, v1);
                BRepAdaptor_Surface surface(f, false);
                bool inside = false;
                for (int a = 1; a < 8 && !inside; ++a) {
                    for (int b = 1; b < 8 && !inside; ++b) {
                        const gp_Pnt q = surface.Value(u0 + (u1 - u0) * a / 8, v0 + (v1 - v0) * b / 8);
                        if (onFace(i, q)) {
                            found = q;
                            inside = true;
                        }
                    }
                }
            }
            catch (const Standard_Failure&) {
            }
        }
        cached = found;
        return *cached;
    }

    // The face's normal at \a point, oriented as the face
    std::optional<gp_Dir> normalAt(int i, const gp_Pnt& point) const
    {
        try {
            const TopoDS_Face& f = face(i);
            GeomAPI_ProjectPointOnSurf projection(point, BRep_Tool::Surface(f));
            if (projection.NbPoints() == 0) {
                return std::nullopt;
            }
            double u = 0.0;
            double v = 0.0;
            projection.LowerDistanceParameters(u, v);
            BRepAdaptor_Surface surface(f, false);
            BRepLProp_SLProps props(surface, u, v, 1, tolerance);
            if (!props.IsNormalDefined()) {
                return std::nullopt;
            }
            gp_Dir normal = props.Normal();
            if (f.Orientation() == TopAbs_REVERSED) {
                normal.Reverse();
            }
            return normal;
        }
        catch (const Standard_Failure&) {
            return std::nullopt;
        }
    }

    const SurfaceKey& surface(int i) const
    {
        auto& cached = surfaces[i];
        if (!cached) {
            cached = surfaceKey(face(i));
        }
        return *cached;
    }

    const Bnd_Box& faceBox(int i) const
    {
        auto& cached = faceBoxes[i];
        if (!cached) {
            Bnd_Box box;
            BRepBndLib::Add(face(i), box);
            box.Enlarge(tolerance);
            cached = box;
        }
        return *cached;
    }

    void prepare()
    {
        innerPoints.resize(faces.Extent());
        surfaces.resize(faces.Extent());
        faceBoxes.resize(faces.Extent());
    }

private:
    mutable std::vector<std::optional<gp_Pnt>> innerPoints;
    mutable std::vector<std::optional<SurfaceKey>> surfaces;
    mutable std::vector<std::optional<Bnd_Box>> faceBoxes;
};

// Faces on the same side: the same kind of surface, and the oriented normals at their inner
// points agree (the design's CC2)
bool sameSide(const Topology& before, int j, const Topology& after, int i)
{
    if (before.surface(j).kind != after.surface(i).kind) {
        return false;
    }
    const auto old = before.normalAt(j, before.innerPoint(j));
    const auto now = after.normalAt(i, after.innerPoint(i));
    return old && now && old->Dot(*now) > 0;
}

// Rung 6: the same counts and incidences under the index map, each face of the same kind and side
bool sameConstruction(const Topology& before, const Topology& after)
{
    if (before.points.size() != after.points.size()
        || before.edgeVertexes.size() != after.edgeVertexes.size()
        || before.faceEdges.size() != after.faceEdges.size()) {
        return false;
    }
    for (std::size_t i = 0; i < before.edgeVertexes.size(); ++i) {
        if (sorted(before.edgeVertexes[i]) != sorted(after.edgeVertexes[i])) {
            return false;
        }
    }
    if (before.faceEdges != after.faceEdges) {
        return false;
    }
    for (int i = 0; i < static_cast<int>(before.faceEdges.size()); ++i) {
        if (!sameSide(before, i, after, i)) {
            return false;
        }
    }
    return true;
}

// The run of unmatched vertices holding \a start, and its anchors (its matched neighbours)
std::pair<std::set<int>, std::set<int>> runOf(
    int start,
    const std::vector<std::set<int>>& neighbours,
    const std::vector<bool>& matched
)
{
    std::set<int> run {start};
    std::set<int> anchors;
    std::vector<int> todo {start};
    while (!todo.empty()) {
        const int x = todo.back();
        todo.pop_back();
        for (const int y : neighbours[x]) {
            if (matched[y]) {
                anchors.insert(y);
            }
            else if (run.insert(y).second) {
                todo.push_back(y);
            }
        }
    }
    return {run, anchors};
}

class Matcher
{
public:
    Matcher(const Topology& before, const Topology& after)
        : before(before)
        , after(after)
        , tolerance(std::max(before.tolerance, after.tolerance))
        , vmap(after.points.size(), -1)
        , vback(before.points.size(), -1)
    {}

    ElementMatches run()
    {
        matchPlaces();
        matchMovedPoints();
        matchFaces();
        matchFaceVertexes();
        matchEdges();
        ElementMatches result;
        for (int i = 0; i < static_cast<int>(vmap.size()); ++i) {
            if (vmap[i] >= 0) {
                result.vertexes[i + 1] = vmap[i] + 1;
            }
        }
        for (const auto& [i, j] : emap) {
            result.edges[i + 1] = j + 1;
        }
        for (const auto& [i, j] : fmap) {
            result.faces[i + 1] = j + 1;
        }
        return result;
    }

private:
    void link(int i, int j)
    {
        vmap[i] = j;
        vback[j] = i;
    }

    void unlink(int i)
    {
        vback[vmap[i]] = -1;
        vmap[i] = -1;
    }

    // Rung 1 for vertices: at the identical place, one to one. A vertex no edge joins to another
    // such vertex as before is weak: a point that moved onto another's old place, which rung 2
    // doesn't build on.
    void matchPlaces()
    {
        PointGrid grid(before.points, tolerance);
        std::map<int, std::vector<int>> candidates;
        for (int i = 0; i < static_cast<int>(after.points.size()); ++i) {
            candidates[i] = grid.at(after.points[i]);
        }
        for (const auto& [i, j] : uniquePairs(candidates)) {
            link(i, j);
        }
        weak.assign(vmap.size(), false);
        for (int n = 0; n < static_cast<int>(vmap.size()); ++n) {
            if (vmap[n] < 0) {
                continue;
            }
            const auto& oldNeighbours = before.neighbours[vmap[n]];
            weak[n] = std::none_of(
                after.neighbours[n].begin(),
                after.neighbours[n].end(),
                [&](int k) { return vmap[k] >= 0 && oldNeighbours.count(vmap[k]); }
            );
        }
    }

    // Rung 2: a vertex whose matched neighbours are exactly an old vertex's, iterated; then a run
    // of such vertices is kept all or nothing
    void matchMovedPoints()
    {
        const std::vector<int>& oldFaces = before.vertexFaces;
        const std::vector<int>& newFaces = after.vertexFaces;
        std::vector<bool> placed(vmap.size());
        for (std::size_t i = 0; i < vmap.size(); ++i) {
            placed[i] = vmap[i] >= 0;
        }
        // the anchors: matched and not weak (new side), and their old vertices (old side)
        std::vector<int> inv(before.points.size(), -1);
        for (int n = 0; n < static_cast<int>(vmap.size()); ++n) {
            if (vmap[n] >= 0 && !weak[n]) {
                inv[vmap[n]] = n;
            }
        }
        using Signature = std::tuple<std::vector<int>, int, int>;
        for (int pass = 0; pass < maxVertexPasses; ++pass) {
            std::map<Signature, std::vector<int>> oldSignatures;
            for (int j = 0; j < static_cast<int>(before.points.size()); ++j) {
                const auto& around = before.neighbours[j];
                if (vback[j] >= 0 || around.empty()) {
                    continue;
                }
                std::vector<int> anchors;
                int unmatched = 0;
                for (const int k : around) {
                    if (inv[k] >= 0) {
                        anchors.push_back(inv[k]);
                    }
                    else {
                        ++unmatched;
                    }
                }
                if (!anchors.empty()) {
                    oldSignatures[{sorted(anchors), static_cast<int>(around.size()), unmatched}]
                        .push_back(j);
                }
            }
            std::vector<Signature> order;
            std::map<Signature, std::vector<int>> newSignatures;
            for (int i = 0; i < static_cast<int>(vmap.size()); ++i) {
                const auto& around = after.neighbours[i];
                if (vmap[i] >= 0 || around.empty()) {
                    continue;
                }
                std::vector<int> anchors;
                int unmatched = 0;
                for (const int k : around) {
                    if (vmap[k] >= 0 && !weak[k]) {
                        anchors.push_back(k);
                    }
                    else {
                        ++unmatched;
                    }
                }
                if (!anchors.empty()) {
                    Signature signature {anchors, static_cast<int>(around.size()), unmatched};
                    auto& holders = newSignatures[signature];
                    if (holders.empty()) {
                        order.push_back(signature);
                    }
                    holders.push_back(i);
                }
            }
            int added = 0;
            for (const auto& signature : order) {
                const auto& news = newSignatures[signature];
                const auto old = oldSignatures.find(signature);
                if (news.size() != 1 || old == oldSignatures.end() || old->second.size() != 1) {
                    continue;
                }
                const int i = news.front();
                const int j = old->second.front();
                if (oldFaces[j] != newFaces[i]) {
                    continue;
                }
                // CC1: the vertex stays on the same side of each matched neighbour (a shape
                // moved by one of its own edge vectors otherwise hands its ends over)
                const bool turned = std::any_of(
                    before.neighbours[j].begin(),
                    before.neighbours[j].end(),
                    [&](int k) {
                        return inv[k] >= 0
                            && gp_Vec(before.points[k], before.points[j])
                                    .Dot(gp_Vec(after.points[inv[k]], after.points[i]))
                            <= 0;
                    }
                );
                if (turned) {
                    continue;
                }
                if (std::get<2>(signature) > 0) {
                    // a partial neighbourhood: the run of unmatched points around it must be the
                    // same size, held by the same anchors, before and after
                    std::vector<bool> anchoredNew(vmap.size());
                    for (std::size_t k = 0; k < vmap.size(); ++k) {
                        anchoredNew[k] = vmap[k] >= 0 && !weak[k];
                    }
                    std::vector<bool> anchoredOld(inv.size());
                    for (std::size_t k = 0; k < inv.size(); ++k) {
                        anchoredOld[k] = inv[k] >= 0;
                    }
                    const auto [runNew, anchorsNew] = runOf(i, after.neighbours, anchoredNew);
                    const auto [runOld, anchorsOld] = runOf(j, before.neighbours, anchoredOld);
                    std::set<int> anchorsMapped;
                    for (const int k : anchorsOld) {
                        anchorsMapped.insert(inv[k]);
                    }
                    if (runNew.size() != runOld.size() || anchorsNew != anchorsMapped) {
                        continue;
                    }
                }
                link(i, j);
                inv[j] = i;
                ++added;
            }
            if (!added) {
                break;
            }
        }
        // A run of moved points is matched all or nothing: a run left half matched has a reading
        // the direction terms refuse further on (a square shifted by its side, mirrored onto
        // itself)
        std::vector<bool> seen(vmap.size(), false);
        for (int i = 0; i < static_cast<int>(vmap.size()); ++i) {
            if (placed[i] || vmap[i] < 0 || seen[i]) {
                continue;
            }
            std::vector<int> run {i};
            std::vector<int> todo {i};
            seen[i] = true;
            while (!todo.empty()) {
                const int x = todo.back();
                todo.pop_back();
                for (const int y : after.neighbours[x]) {
                    if (!placed[y] && !seen[y]) {
                        seen[y] = true;
                        run.push_back(y);
                        todo.push_back(y);
                    }
                }
            }
            if (std::any_of(run.begin(), run.end(), [this](int y) { return vmap[y] < 0; })) {
                for (const int y : run) {
                    if (vmap[y] >= 0) {
                        unlink(y);
                    }
                }
            }
        }
    }

    // Rungs 3 and 4 for faces
    void matchFaces()
    {
        // Rung 3: the same matched vertices
        std::map<std::vector<int>, std::vector<int>> oldByVertexes;
        for (int j = 0; j < static_cast<int>(before.faceVertexes.size()); ++j) {
            oldByVertexes[before.faceVertexes[j]].push_back(j);
        }
        std::map<int, std::vector<int>> candidates;
        for (int i = 0; i < static_cast<int>(after.faceVertexes.size()); ++i) {
            const auto& own = after.faceVertexes[i];
            if (own.empty()
                || std::any_of(own.begin(), own.end(), [this](int k) { return k < 0 || vmap[k] < 0; })) {
                continue;
            }
            std::vector<int> key;
            for (const int k : own) {
                key.push_back(vmap[k]);
            }
            const auto found = oldByVertexes.find(sorted(key));
            candidates[i] = found == oldByVertexes.end() ? std::vector<int> {} : found->second;
        }
        for (const auto& [i, j] : uniquePairs(candidates)) {
            if (sameSide(before, j, after, i)) {
                fmap[i] = j;
            }
        }
        // The anchors so far: pairs of (old piece, new piece) a matched vertex or face links.
        // Rung 4 matches a face only where its old and new pieces are so linked (else two
        // congruent pieces, a script compound's copies, could trade places by an overlap).
        std::set<std::pair<int, int>> links;
        for (int n = 0; n < static_cast<int>(vmap.size()); ++n) {
            if (vmap[n] >= 0) {
                links.emplace(before.vertexPiece[vmap[n]], after.vertexPiece[n]);
            }
        }
        for (const auto& [n, o] : fmap) {
            links.emplace(before.facePiece[o], after.facePiece[n]);
        }
        std::set<int> used;
        for (const auto& [n, o] : fmap) {
            used.insert(o);
        }
        const int oldCount = static_cast<int>(before.faceVertexes.size());
        const int newCount = static_cast<int>(after.faceVertexes.size());
        candidates.clear();
        for (int i = 0; i < newCount; ++i) {
            if (fmap.count(i)) {
                continue;
            }
            std::vector<int> found;
            // Rung 1: the same surface, side and vertex places
            for (int j = 0; j < oldCount; ++j) {
                if (used.count(j) || !samePlaces(j, i)) {
                    continue;
                }
                if (before.surface(j).same(after.surface(i), tolerance)
                    && sameSide(before, j, after, i)) {
                    found.push_back(j);
                }
            }
            if (found.empty()) {
                // Rung 4: mutual inner points, uncontested and anchored
                // (a face's inner point lies in its box: faces whose boxes don't meet are skipped
                // before their inner points are computed)
                std::vector<int> held;
                for (int j = 0; j < oldCount; ++j) {
                    if (!after.faceBox(i).IsOut(before.faceBox(j))
                        && after.onFace(i, before.innerPoint(j))) {
                        held.push_back(j);
                    }
                }
                for (const int j : held) {
                    if (used.count(j)) {
                        continue;
                    }
                    std::vector<int> holds;
                    for (int k = 0; k < newCount; ++k) {
                        if (!before.faceBox(j).IsOut(after.faceBox(k))
                            && before.onFace(j, after.innerPoint(k))) {
                            holds.push_back(k);
                        }
                    }
                    if (held.size() == 1 && holds == std::vector<int> {i}
                        && sameSide(before, j, after, i)
                        && links.count({before.facePiece[j], after.facePiece[i]})) {
                        found.push_back(j);
                    }
                }
            }
            candidates[i] = found;
        }
        for (const auto& [i, j] : uniquePairs(candidates)) {
            fmap[i] = j;
        }
    }

    // Whether the new face \a i has as many vertices as the old face \a j, each at a place of one
    // of its vertices
    bool samePlaces(int j, int i) const
    {
        const auto& olds = before.faceVertexes[j];
        const auto& news = after.faceVertexes[i];
        if (olds.size() != news.size()) {
            return false;
        }
        return std::all_of(news.begin(), news.end(), [&](int a) {
            return a >= 0 && std::any_of(olds.begin(), olds.end(), [&](int b) {
                       return b >= 0
                           && after.points[a].Distance(before.points[b]) <= tolerance;
                   });
        });
    }

    // A vertex of a matched face at the place of a vertex of its old face (owner-scoped: the
    // coincident vertices of a loose shell)
    void matchFaceVertexes()
    {
        for (const auto& [i, j] : fmap) {
            for (const int a : after.faceVertexes[i]) {
                if (a < 0 || vmap[a] >= 0) {
                    continue;
                }
                std::vector<int> hits;
                for (const int b : before.faceVertexes[j]) {
                    if (b >= 0 && after.points[a].Distance(before.points[b]) <= tolerance) {
                        hits.push_back(b);
                    }
                }
                if (hits.size() == 1 && vback[hits.front()] < 0) {
                    link(a, hits.front());
                }
            }
        }
    }

    // Rung 3 for edges, then rung 5
    void matchEdges()
    {
        std::map<std::pair<std::vector<int>, int>, std::vector<int>> oldByVertexes;
        for (int j = 0; j < static_cast<int>(before.edgeVertexes.size()); ++j) {
            oldByVertexes[{sorted(before.edgeVertexes[j]), curveKind(before.edge(j))}].push_back(j);
        }
        std::map<int, std::vector<int>> candidates;
        for (int i = 0; i < static_cast<int>(after.edgeVertexes.size()); ++i) {
            const auto& ends = after.edgeVertexes[i];
            if (ends.empty()
                || std::any_of(ends.begin(), ends.end(), [this](int k) { return k < 0 || vmap[k] < 0; })) {
                continue;
            }
            std::vector<int> key;
            for (const int k : ends) {
                key.push_back(vmap[k]);
            }
            const auto found = oldByVertexes.find({sorted(key), curveKind(after.edge(i))});
            std::vector<int> found2;
            if (found != oldByVertexes.end()) {
                found2 = found->second;
            }
            if (found2.size() > 1) {
                const gp_Pnt middle = midpointOf(after.edge(i));
                std::vector<int> near2;
                for (const int j : found2) {
                    if (distanceTo(before.edge(j), middle) <= tolerance) {
                        near2.push_back(j);
                    }
                }
                found2 = near2;
            }
            candidates[i] = found2;
        }
        emap = uniquePairs(candidates);
        std::set<int> taken;
        for (const auto& [i, j] : emap) {
            taken.insert(j);
        }
        // Rung 5: an edge of a matched face within one edge of the old face, which holds no other
        // edge of the face (a split edge keeps neither piece)
        for (const auto& [i, j] : fmap) {
            const auto& own = after.faceEdges[i];
            for (const int a : own) {
                if (a < 0 || emap.count(a)) {
                    continue;
                }
                const TopoDS_Edge& edge = after.edge(a);
                const int kind = curveKind(edge);
                const gp_Pnt middle = midpointOf(edge);
                std::vector<int> hits;
                for (const int b : before.faceEdges[j]) {
                    if (b < 0 || curveKind(before.edge(b)) != kind
                        || distanceTo(before.edge(b), middle) > tolerance) {
                        continue;
                    }
                    const auto& ends = after.edgeVertexes[a];
                    const bool within = std::all_of(ends.begin(), ends.end(), [&](int v) {
                        return v >= 0 && distanceTo(before.edge(b), after.points[v]) <= tolerance;
                    });
                    if (within) {
                        hits.push_back(b);
                    }
                }
                if (hits.size() == 1) {
                    const TopoDS_Edge& old = before.edge(hits.front());
                    const bool others = std::any_of(own.begin(), own.end(), [&](int z) {
                        return z >= 0 && z != a && curveKind(after.edge(z)) == kind
                            && distanceTo(old, midpointOf(after.edge(z))) <= tolerance;
                    });
                    if (others) {
                        hits.clear();
                    }
                }
                if (hits.size() == 1 && !taken.count(hits.front())) {
                    emap[a] = hits.front();
                    taken.insert(hits.front());
                }
            }
        }
    }

    const Topology& before;
    const Topology& after;
    double tolerance;
    std::vector<int> vmap;  // new vertex -> old vertex, or -1
    std::vector<int> vback;  // old vertex -> new vertex, or -1
    std::vector<bool> weak;
    std::map<int, int> emap;
    std::map<int, int> fmap;
};

// The class C ruling of 10-28 (the ops repo's `notes/naming-class-C.md` section 9.2): rules that
// only withdraw matches, run on the matcher's result.

// The producer's top-level units (P1): a compound's children, compounds flattened; any other
// shape is one piece
void collectUnits(const TopoDS_Shape& shape, std::vector<TopoDS_Shape>& units)
{
    if (shape.ShapeType() != TopAbs_COMPOUND) {
        units.push_back(shape);
        return;
    }
    for (TopoDS_Iterator it(shape); it.More(); it.Next()) {
        collectUnits(it.Value(), units);
    }
}

// A piece: its elements' indexes in the shape's maps (from 0) and its bounding box
struct Piece
{
    std::array<std::vector<int>, 3> elements;  // vertices, edges, faces
    Bnd_Box box;
};

std::vector<Piece> piecesOf(const Topology& topology)
{
    std::vector<TopoDS_Shape> units;
    if (!topology.shape.IsNull()) {
        collectUnits(topology.shape, units);
    }
    const std::array<std::pair<TopAbs_ShapeEnum, const TopTools_IndexedMapOfShape*>, 3> types {
        {{TopAbs_VERTEX, &topology.vertexes},
         {TopAbs_EDGE, &topology.edges},
         {TopAbs_FACE, &topology.faces}}
    };
    std::vector<Piece> pieces;
    for (const auto& unit : units) {
        Piece piece;
        for (std::size_t t = 0; t < types.size(); ++t) {
            TopTools_IndexedMapOfShape own;
            TopExp::MapShapes(unit, types[t].first, own);
            for (int k = 1; k <= own.Extent(); ++k) {
                const int index = types[t].second->FindIndex(own(k)) - 1;
                if (index >= 0) {
                    piece.elements[t].push_back(index);
                }
            }
        }
        try {
            BRepBndLib::AddOptimal(unit, piece.box, false, false);
        }
        catch (const Standard_Failure&) {
            BRepBndLib::Add(unit, piece.box);
        }
        pieces.push_back(std::move(piece));
    }
    return pieces;
}

// Two sizes alike, generously: congruence over-approximated only adds loud
bool sizesAlike(double a, double b)
{
    return std::abs(a - b) <= std::max(1e-4, 1e-6 * std::max(std::abs(a), std::abs(b)));
}

// What congruence compares of a set of elements: the vertex count, and the edges' and faces'
// kinds and sizes (lengths, areas), sorted
struct Congruence
{
    std::size_t vertexes = 0;
    std::vector<std::pair<int, double>> edges;
    std::vector<std::pair<int, double>> faces;

    Congruence(const Topology& topology, const std::array<std::vector<int>, 3>& elements)
        : vertexes(elements[0].size())
    {
        for (const int e : elements[1]) {
            GProp_GProps props;
            BRepGProp::LinearProperties(topology.edge(e), props);
            edges.emplace_back(curveKind(topology.edge(e)), props.Mass());
        }
        for (const int f : elements[2]) {
            GProp_GProps props;
            MassProperties::surfaceProperties(topology.face(f), props);
            faces.emplace_back(topology.surface(f).kind, props.Mass());
        }
        std::sort(edges.begin(), edges.end());
        std::sort(faces.begin(), faces.end());
    }

    bool same(const Congruence& other) const
    {
        auto alike = [](const auto& a, const auto& b) {
            return a.size() == b.size()
                && std::equal(a.begin(), a.end(), b.begin(), [](const auto& x, const auto& y) {
                       return x.first == y.first && sizesAlike(x.second, y.second);
                   });
        };
        return vertexes == other.vertexes && alike(edges, other.edges) && alike(faces, other.faces);
    }

    bool empty() const
    {
        return edges.empty() && faces.empty();
    }
};

// Whether two pieces' boxes have the same centre and size
bool samePlace(const Bnd_Box& a, const Bnd_Box& b, double tolerance)
{
    if (a.IsVoid() || b.IsVoid()) {
        return false;
    }
    const double diagonal = std::sqrt(std::max(a.SquareExtent(), b.SquareExtent()));
    const double allowed = std::max(tolerance, 1e-6 * diagonal);
    auto centre = [](const Bnd_Box& box) {
        return gp_Pnt((box.CornerMin().XYZ() + box.CornerMax().XYZ()) / 2);
    };
    return centre(a).Distance(centre(b)) <= allowed
        && std::abs(std::sqrt(a.SquareExtent()) - std::sqrt(b.SquareExtent())) <= allowed;
}

class Ruling
{
public:
    Ruling(const Topology& before, const Topology& after, ElementMatches& result)
        : before(before)
        , after(after)
        , result(result)
        , tolerance(std::max(before.tolerance, after.tolerance))
        , oldPieces(piecesOf(before))
        , newPieces(piecesOf(after))
    {}

    void run()
    {
        retirePermutedTwins();
        confirmByFaces();
        retirePeriodSlides();
    }

private:
    std::map<int, int>& matchesOf(std::size_t type)
    {
        return type == 0 ? result.vertexes : type == 1 ? result.edges : result.faces;
    }

    // Every element of a new piece takes a fresh id
    void retire(const Piece& piece)
    {
        for (std::size_t t = 0; t < 3; ++t) {
            for (const int i : piece.elements[t]) {
                matchesOf(t).erase(i + 1);
            }
        }
    }

    // P1: congruent pieces whose places pair them otherwise than the producer's order are
    // retired as a class. The pieces of a class (the old pieces congruent with its first, and
    // the new pieces congruent with it) are paired by their order in the class; when the counts
    // are equal and some old piece's place holds a new piece of the class other than its partner,
    // no reading is verified: a trade, a reorder and a slide by the pitch are the same shapes.
    // Added or removed pieces, and a twin moved to a free place, are no permutation.
    void retirePermutedTwins()
    {
        if (oldPieces.size() < 2 || newPieces.empty()) {
            return;
        }
        struct Class
        {
            Congruence shape;
            std::vector<int> olds;
            std::vector<int> news;
        };
        std::vector<Class> classes;
        for (int k = 0; k < static_cast<int>(oldPieces.size()); ++k) {
            Congruence congruence(before, oldPieces[k].elements);
            auto found = std::find_if(classes.begin(), classes.end(), [&](const Class& c) {
                return c.shape.same(congruence);
            });
            if (found == classes.end()) {
                classes.push_back({std::move(congruence), {k}, {}});
            }
            else {
                found->olds.push_back(k);
            }
        }
        for (int n = 0; n < static_cast<int>(newPieces.size()); ++n) {
            Congruence congruence(after, newPieces[n].elements);
            auto found = std::find_if(classes.begin(), classes.end(), [&](const Class& c) {
                return c.shape.same(congruence);
            });
            if (found != classes.end()) {
                found->news.push_back(n);
            }
        }
        for (const auto& c : classes) {
            if (c.olds.size() < 2 || c.olds.size() != c.news.size()) {
                continue;
            }
            bool permuted = false;
            for (std::size_t p = 0; p < c.olds.size() && !permuted; ++p) {
                std::vector<int> there;
                for (const int n : c.news) {
                    if (samePlace(oldPieces[c.olds[p]].box, newPieces[n].box, tolerance)) {
                        there.push_back(n);
                    }
                }
                permuted = there.size() == 1 && there.front() != c.news[p];
            }
            if (permuted) {
                for (const int n : c.news) {
                    retire(newPieces[n]);
                }
            }
        }
    }

    // R1: identity flows down from faces. A matched vertex counts only where a face at it
    // matched; a matched edge where a face at it matched or both its vertices are so confirmed
    // (a prism's vertical edge between its matched caps). An element at no face, in a wire: an
    // edge counts where an adjacent edge matched (an edge with no adjacent edge stands alone), a
    // vertex where an edge at it counts. A place match nothing confirms is a seam: elements at
    // the old places of other faces' elements (a shape moved by its own width).
    void confirmByFaces()
    {
        std::set<int> faces;
        for (const auto& [i, j] : result.faces) {
            faces.insert(i - 1);
        }
        std::vector<std::vector<int>> facesAtVertex(after.points.size());
        for (int f = 0; f < static_cast<int>(after.faceVertexes.size()); ++f) {
            for (const int v : after.faceVertexes[f]) {
                if (v >= 0) {
                    facesAtVertex[v].push_back(f);
                }
            }
        }
        std::vector<std::vector<int>> facesAtEdge(after.edgeVertexes.size());
        for (int f = 0; f < static_cast<int>(after.faceEdges.size()); ++f) {
            for (const int e : after.faceEdges[f]) {
                if (e >= 0) {
                    facesAtEdge[e].push_back(f);
                }
            }
        }
        std::vector<std::vector<int>> edgesAtVertex(after.points.size());
        for (int e = 0; e < static_cast<int>(after.edgeVertexes.size()); ++e) {
            for (const int v : after.edgeVertexes[e]) {
                if (v >= 0) {
                    edgesAtVertex[v].push_back(e);
                }
            }
        }
        auto anyMatchedFace = [&](const std::vector<int>& at) {
            return std::any_of(at.begin(), at.end(), [&](int f) { return faces.count(f) > 0; });
        };
        std::set<int> vertexes;  // confirmed through a face
        for (const auto& [i, j] : result.vertexes) {
            if (anyMatchedFace(facesAtVertex[i - 1])) {
                vertexes.insert(i - 1);
            }
        }
        std::set<int> edges;
        for (const auto& [i, j] : result.edges) {
            const int e = i - 1;
            if (!facesAtEdge[e].empty()) {
                const auto& ends = after.edgeVertexes[e];
                if (anyMatchedFace(facesAtEdge[e])
                    || (!ends.empty() && std::all_of(ends.begin(), ends.end(), [&](int v) {
                           return vertexes.count(v) > 0;
                       }))) {
                    edges.insert(e);
                }
                continue;
            }
            bool adjacent = false;
            bool matched = false;
            for (const int v : after.edgeVertexes[e]) {
                if (v < 0) {
                    continue;
                }
                for (const int other : edgesAtVertex[v]) {
                    if (other != e) {
                        adjacent = true;
                        matched = matched || result.edges.count(other + 1) > 0;
                    }
                }
            }
            if (!adjacent || matched) {
                edges.insert(e);
            }
        }
        for (const auto& [i, j] : result.vertexes) {
            const int v = i - 1;
            if (facesAtVertex[v].empty()
                && std::any_of(edgesAtVertex[v].begin(), edgesAtVertex[v].end(), [&](int e) {
                       return edges.count(e) > 0;
                   })) {
                vertexes.insert(v);
            }
        }
        std::erase_if(result.vertexes, [&](const auto& match) {
            return !vertexes.count(match.first - 1);
        });
        std::erase_if(result.edges, [&](const auto& match) {
            return !edges.count(match.first - 1);
        });
    }

    // R2 (to be measured, the ruling's 2b): a piece with an internal period slid by its pitch
    // (a comb of teeth, a square-wave wire) puts each tooth's elements on the next tooth's old
    // places, every match verified. Its signature: the old piece's unmatched elements and the
    // new piece's are congruent, the first tooth's left and the last tooth's arrived. Such a
    // piece is retired. A split (one old element, two new) and a count change don't fit it.
    void retirePeriodSlides()
    {
        auto pieceOf = [](const std::vector<Piece>& pieces, std::size_t type, std::size_t count) {
            std::vector<int> owner(count, -1);
            for (int k = 0; k < static_cast<int>(pieces.size()); ++k) {
                for (const int i : pieces[k].elements[type]) {
                    if (owner[i] < 0) {
                        owner[i] = k;
                    }
                }
            }
            return owner;
        };
        const std::array<std::size_t, 3> oldCounts {
            before.points.size(),
            before.edgeVertexes.size(),
            before.faceVertexes.size()
        };
        const std::array<std::size_t, 3> newCounts {
            after.points.size(),
            after.edgeVertexes.size(),
            after.faceVertexes.size()
        };
        // The pieces the matches link: a new piece with the one old piece its matches reach, and
        // no other new piece's matches reach that one
        std::map<int, std::set<int>> reached;  // new piece -> old pieces
        std::map<int, std::set<int>> reachedBy;  // old piece -> new pieces
        std::array<std::set<int>, 3> held;  // old elements matched
        for (std::size_t t = 0; t < 3; ++t) {
            const auto oldOwner = pieceOf(oldPieces, t, oldCounts[t]);
            const auto newOwner = pieceOf(newPieces, t, newCounts[t]);
            for (const auto& [i, j] : matchesOf(t)) {
                held[t].insert(j - 1);
                const int n = newOwner[i - 1];
                const int k = oldOwner[j - 1];
                if (n >= 0 && k >= 0) {
                    reached[n].insert(k);
                    reachedBy[k].insert(n);
                }
            }
        }
        for (const auto& [n, olds] : reached) {
            if (olds.size() != 1 || reachedBy[*olds.begin()].size() != 1) {
                continue;
            }
            const Piece& oldPiece = oldPieces[*olds.begin()];
            const Piece& newPiece = newPieces[n];
            std::array<std::vector<int>, 3> left;
            std::array<std::vector<int>, 3> arrived;
            for (std::size_t t = 0; t < 3; ++t) {
                for (const int j : oldPiece.elements[t]) {
                    if (!held[t].count(j)) {
                        left[t].push_back(j);
                    }
                }
                for (const int i : newPiece.elements[t]) {
                    if (!matchesOf(t).count(i + 1)) {
                        arrived[t].push_back(i);
                    }
                }
            }
            const Congruence gone(before, left);
            const Congruence come(after, arrived);
            if (!gone.empty() && gone.same(come)) {
                retire(newPiece);
            }
        }
    }

    const Topology& before;
    const Topology& after;
    ElementMatches& result;
    double tolerance;
    std::vector<Piece> oldPieces;
    std::vector<Piece> newPieces;
};

long idOf(const TopoShape& shape, const Data::IndexedName& element)
{
    for (const auto& [name, sids] : shape.getElementMappedNames(element)) {
        const auto& sections = name.getDecodedMappedName();
        if (sections.size() == 1 && sections.front().opCode == matchOpCode) {
            try {
                return std::stol(sections.front().index);
            }
            catch (const std::exception&) {
                return 0;
            }
        }
    }
    return 0;
}

// The ids nameByMatch() gave the elements of a type of \a shape, by index from 1 (0: none)
std::vector<long> idsOf(const TopoShape& shape, TopAbs_ShapeEnum type)
{
    const auto& typeName = TopoShape::shapeName(type);
    const auto count = static_cast<int>(shape.countSubShapes(type));
    std::vector<long> ids(count + 1, 0);
    for (int i = 1; i <= count; ++i) {
        ids[i] = idOf(shape, Data::IndexedName::fromConst(typeName.c_str(), i));
    }
    return ids;
}

}  // namespace

ElementMatches matchElements(const TopoDS_Shape& before, const TopoDS_Shape& after, bool fixedOrder)
{
    Topology old(before.Located(TopLoc_Location()));
    Topology now(after.Located(TopLoc_Location()));
    old.prepare();
    now.prepare();
    if (fixedOrder && sameConstruction(old, now)) {
        // A producer whose construction order is fixed for a given topology (a primitive): the
        // same counts and incidences under the index map are the same elements
        ElementMatches result;
        for (int i = 1; i <= now.vertexes.Extent(); ++i) {
            result.vertexes[i] = i;
        }
        for (int i = 1; i <= now.edges.Extent(); ++i) {
            result.edges[i] = i;
        }
        for (int i = 1; i <= now.faces.Extent(); ++i) {
            result.faces[i] = i;
        }
        result.byIndex = true;
        return result;
    }
    ElementMatches result = Matcher(old, now).run();
    Ruling(old, now, result).run();
    return result;
}

long matchedId(const TopoShape& shape, const char* element)
{
    return idOf(shape, Data::IndexedName(element, shape.getElementTypes()));
}

void nameByMatch(TopoShape& shape, const TopoShape& previous, long tag, long& counter, bool fixedOrder)
{
    const std::array<TopAbs_ShapeEnum, 3> types {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE};
    std::array<std::vector<long>, 3> oldIds;
    bool named = false;
    if (!previous.isNull() && previous.getElementMapSize() > 0) {
        for (std::size_t t = 0; t < types.size(); ++t) {
            oldIds[t] = idsOf(previous, types[t]);
            for (const long id : oldIds[t]) {
                counter = std::max(counter, id + 1);
                named = named || id > 0;
            }
        }
    }
    counter = std::max(counter, 1L);
    ElementMatches matches;
    if (named) {
        // A match that fails leaves every element a fresh id: loud, never a guess
        try {
            matches = matchElements(previous.getShape(), shape.getShape(), fixedOrder);
        }
        catch (const Standard_Failure& e) {
            FC_WARN("Naming by match failed, fresh names: " << e.GetMessageString());
        }
        catch (const std::exception& e) {
            FC_WARN("Naming by match failed, fresh names: " << e.what());
        }
    }
    const std::array<const std::map<int, int>*, 3> byType {
        &matches.vertexes,
        &matches.edges,
        &matches.faces
    };
    shape.setHistoryAlgorithm(App::HistoryAlgorithm::V2);
    shape.initCache(1);
    shape.resetElementMap(std::make_shared<Data::ElementMap>());
    shape.Tag = tag;
    const std::vector<Data::MappedName> noNames;
    for (std::size_t t = 0; t < types.size(); ++t) {
        const auto& typeName = TopoShape::shapeName(types[t]);
        const auto count = static_cast<int>(shape.countSubShapes(types[t]));
        for (int i = 1; i <= count; ++i) {
            long id = 0;
            const auto match = byType[t]->find(i);
            if (match != byType[t]->end() && match->second < static_cast<int>(oldIds[t].size())) {
                id = oldIds[t][match->second];
            }
            if (id <= 0) {
                id = counter++;
            }
            const std::string section = Data::MappedName::makeEncodedSection(
                {},
                noNames,
                std::to_string(tag),
                matchOpCode,
                std::to_string(id),
                typeName[0],
                std::string("0"),
                {},
                noNames
            );
            shape.setElementName(
                Data::IndexedName::fromConst(typeName.c_str(), i),
                Data::MappedName(section),
                tag
            );
        }
    }
}

}  // namespace Part
