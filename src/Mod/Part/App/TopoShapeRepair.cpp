// SPDX-License-Identifier: LGPL-2.1-or-later

#include "TopoShapeRepair.h"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <exception>
#include <map>
#include <memory>
#include <numeric>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <Bnd_Box.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepBndLib.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <ChFi3d.hxx>
#include <Geom_Surface.hxx>
#include <GProp_GProps.hxx>
#include <gp.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>

#include <App/ElementMap.h>
#include <Base/Console.h>
#include <Base/Exception.h>

#include "Geometry.h"
#include "MassProperties.h"
#include "TopoShape.h"

FC_LOG_LEVEL_INIT("TopoShape", true, true)  // NOLINT

namespace Part
{

namespace
{

// The largest relative difference of two faces' areas that are the same face, and of their
// centres, relative to the face's size (the square root of its area)
constexpr double relativeTolerance = 1e-9;
// The least distance of the centres: findSubShapesWithSharedVertex()'s default tolerance
constexpr double tolerance = 1e-7;

// What tells a face apart when its vertices don't: its kind of surface, area and centre. The
// surface itself can't be compared: the repair builds new ones, which Geometry::isSame() tells
// apart by their parametrization (findSubShapesWithSharedVertex() skips it for planes too).
struct FaceKey
{
    Base::Type surface;
    double area = 0.0;
    gp_Pnt centre;

    explicit FaceKey(const TopoShape& face)
    {
        std::unique_ptr<Geometry> geometry(Geometry::fromShape(face.getShape(), true));
        if (geometry) {
            surface = geometry->getTypeId();
        }
        GProp_GProps props;
        MassProperties::surfaceProperties(face.getShape(), props);
        area = props.Mass();
        centre = props.CentreOfMass();
    }

    bool same(const FaceKey& other) const
    {
        return !surface.isBad() && surface == other.surface
            && std::abs(area - other.area) <= relativeTolerance * std::max(area, 1.0)
            && centre.Distance(other.centre)
            <= std::max(tolerance, relativeTolerance * std::sqrt(area));
    }
};

// The index of the one element of \a shape of \a type that has the type, geometry and vertices of
// \a element, or 0 when none or several have
int theOneLike(const TopoShape& shape, const TopoShape& element, TopAbs_ShapeEnum type)
{
    std::vector<std::string> names;
    shape.findSubShapesWithSharedVertex(element, &names);
    if (names.size() != 1) {
        return 0;
    }
    return std::stoi(names.front().substr(TopoShape::shapeName(type).size()));
}

// The elements of a type of a shape and their boundaries (the edges of a face, the vertices of an
// edge), by index
struct Bounds
{
    // the boundary of each element (from 1)
    std::vector<std::set<int>> of;
    // the elements at each element of a boundary
    std::map<int, std::vector<int>> at;

    Bounds(const TopoShape& shape, TopAbs_ShapeEnum type, TopAbs_ShapeEnum boundary)
        : of(shape.countSubShapes(type) + 1)
    {
        for (int index = 1; index < static_cast<int>(of.size()); ++index) {
            for (TopExp_Explorer it(shape.getSubShape(type, index), boundary); it.More();
                 it.Next()) {
                of[index].insert(shape.findShape(it.Current()));
            }
            for (const int element : of[index]) {
                at[element].push_back(index);
            }
        }
    }
};

// theOneLike() for the element \a index of \a shape whose boundary all has a match in \a other
// (\a matches, by index): the one element of \a other bounded by exactly the elements they match
// that has the element's geometry and vertices too, or 0. theOneLike() compares the element with
// every element at its first vertex, looking for that vertex among all of them, and splits a
// face's wires for each face it compares: on a solid with many holes most faces touch one with
// hundreds of edges, and the cost grows with the square of the holes (ops#190: 100 pockets, 408
// faces, 15 s).
int theOneBoundedAlike(
    const TopoShape& other,
    const Bounds& otherBounds,
    const TopoShape& shape,
    const Bounds& shapeBounds,
    TopAbs_ShapeEnum type,
    int index,
    const std::map<int, int>& matches
)
{
    std::set<int> bounding;
    for (const int element : shapeBounds.of[index]) {
        const auto match = matches.find(element);
        if (match == matches.end()) {
            return 0;
        }
        bounding.insert(match->second);
    }
    if (bounding.empty()) {
        return 0;
    }
    const auto candidates = otherBounds.at.find(*bounding.begin());
    if (candidates == otherBounds.at.end()) {
        return 0;
    }
    const auto element = shape.getSubTopoShape(type, index);
    int found = 0;
    for (const int j : candidates->second) {
        if (otherBounds.of[j] == bounding
            && other.getSubTopoShape(type, j).findSubShapesWithSharedVertex(element).size() == 1) {
            if (found) {
                return 0;
            }
            found = j;
        }
    }
    return found;
}

// The element of \a before that each element of \a after of \a type is, by index: one-to-one
// matches only, checked from both sides (an element of \a before that two elements of \a after
// match is neither's, and an element of \a after that matches one of \a before which matches
// another of \a after too is not that one's). \a bounds are the matches of the type below
// (vertices for edges, edges for faces): an element whose boundary all matched is compared only
// with the elements that boundary bounds.
std::map<int, int> matchesOf(
    const TopoShape& before,
    const TopoShape& after,
    TopAbs_ShapeEnum type,
    const std::map<int, int>& bounds
)
{
    const auto count = static_cast<int>(after.countSubShapes(type));
    std::map<int, int> found;
    std::optional<Bounds> boundsBefore;
    std::optional<Bounds> boundsAfter;
    std::map<int, int> boundsBack;
    if (type != TopAbs_VERTEX) {
        const auto boundary = type == TopAbs_FACE ? TopAbs_EDGE : TopAbs_VERTEX;
        boundsBefore.emplace(before, type, boundary);
        boundsAfter.emplace(after, type, boundary);
        for (const auto& [i, j] : bounds) {
            boundsBack[j] = i;
        }
    }
    for (int i = 1; i <= count; ++i) {
        if (boundsBefore) {
            const Bounds& inBefore = *boundsBefore;
            const Bounds& inAfter = *boundsAfter;
            const int j = theOneBoundedAlike(before, inBefore, after, inAfter, type, i, bounds);
            if (j > 0
                && theOneBoundedAlike(after, inAfter, before, inBefore, type, j, boundsBack) == i) {
                found[i] = j;
                continue;
            }
        }
        const int j = theOneLike(before, after.getSubTopoShape(type, i), type);
        if (j > 0 && theOneLike(after, before.getSubTopoShape(type, j), type) == i) {
            found[i] = j;
        }
    }
    if (type == TopAbs_FACE) {
        // A face the repair split an edge of has another vertex: the same kind of surface, area
        // and centre, again one to one among the faces left over on both sides
        std::set<int> matched;
        for (const auto& [i, j] : found) {
            matched.insert(j);
        }
        std::map<int, FaceKey> leftBefore;
        for (int j = 1; j <= static_cast<int>(before.countSubShapes(type)); ++j) {
            if (!matched.count(j)) {
                leftBefore.emplace(j, FaceKey(before.getSubTopoShape(type, j)));
            }
        }
        std::map<int, FaceKey> leftAfter;
        for (int i = 1; i <= count; ++i) {
            if (!found.count(i)) {
                leftAfter.emplace(i, FaceKey(after.getSubTopoShape(type, i)));
            }
        }
        auto sameAs = [](const FaceKey& key, const std::map<int, FaceKey>& keys) {
            std::vector<int> same;
            for (const auto& [index, other] : keys) {
                if (key.same(other)) {
                    same.push_back(index);
                }
            }
            return same;
        };
        for (const auto& [i, key] : leftAfter) {
            const auto same = sameAs(key, leftBefore);
            if (same.size() == 1 && sameAs(leftBefore.at(same.front()), leftAfter).size() == 1) {
                found[i] = same.front();
            }
        }
    }
    std::map<int, int> uses;
    for (const auto& [i, j] : found) {
        ++uses[j];
    }
    for (auto it = found.begin(); it != found.end();) {
        it = uses[it->second] > 1 ? found.erase(it) : std::next(it);
    }
    return found;
}

using Names = std::vector<std::pair<Data::MappedName, Data::ElementIDRefs>>;

// An element of the repaired shape: its own names and, if it matched, those of \a before's
// element it is
struct Renamed
{
    Data::IndexedName element;
    Names own;
    Names moved;
    bool keep = false;
};

// Gives the elements of \a shape (repaired by fix()) the names of the elements of \a before they
// are. A matched element whose names fix() already gave an element left unmatched keeps fix()'s
// names: a name on two elements would rename the second one silently (PR 157's review).
void renameAsBefore(TopoShape& shape, const TopoShape& before)
{
    std::vector<Renamed> elements;
    std::map<int, int> below;
    for (const auto type : {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE}) {
        const auto& typeName = TopoShape::shapeName(type);
        const auto matches = matchesOf(before, shape, type, below);
        below = matches;
        const auto count = static_cast<int>(shape.countSubShapes(type));
        for (int i = 1; i <= count; ++i) {
            Renamed renamed;
            renamed.element = Data::IndexedName::fromConst(typeName.c_str(), i);
            renamed.own = shape.getElementMappedNames(renamed.element);
            const auto match = matches.find(i);
            if (match != matches.end()) {
                renamed.moved = before.getElementMappedNames(
                    Data::IndexedName::fromConst(typeName.c_str(), match->second));
                // an element of before without names gives none: the element keeps its own
                renamed.keep = !renamed.moved.empty();
            }
            elements.push_back(std::move(renamed));
        }
    }
    // Which elements keep their own names, until no moved name clashes with one of them
    std::set<Data::IndexedName> ownNames;
    for (const auto& renamed : elements) {
        if (!renamed.keep) {
            ownNames.insert(renamed.element);
        }
    }
    for (bool changed = true; changed;) {
        changed = false;
        for (auto& renamed : elements) {
            if (!renamed.keep) {
                continue;
            }
            const bool clash =
                std::any_of(renamed.moved.begin(), renamed.moved.end(), [&](const auto& name) {
                    const auto holder = shape.getIndexedName(name.first);
                    return holder && holder != renamed.element && ownNames.count(holder);
                });
            if (clash) {
                renamed.keep = false;
                ownNames.insert(renamed.element);
                changed = true;
            }
        }
    }
    // A new map: the old one may be shared, e.g. with the shape this one is a copy of. In the
    // element's order, so its first name stays first.
    const auto fixed = shape.resetElementMap(std::make_shared<Data::ElementMap>());
    try {
        for (const auto& renamed : elements) {
            for (const auto& [name, sids] : renamed.keep ? renamed.moved : renamed.own) {
                shape.setElementName(renamed.element, name, shape.Tag, &sids);
            }
        }
    }
    catch (...) {
        shape.resetElementMap(fixed);
        throw;
    }
}

void warnKept(const char* why)
{
    FC_WARN("Repaired shape: keeping the repair's names, renaming failed: " << why);
}

}  // namespace

bool fixKeepingNames(TopoShape& shape, const TopoShape& before)
{
    assert(&shape != &before);
    if (!shape.fix()) {
        return false;
    }
    if (shape.getHistoryAlgorithm() != App::HistoryAlgorithm::V2 || !shape.hasElementMap()
        || !before.hasElementMap()) {
        return true;
    }
    // The repair succeeded: a failure to rename keeps the names fix() gave, never fails it
    try {
        renameAsBefore(shape, before);
    }
    catch (const Standard_Failure& e) {
        warnKept(e.GetMessageString());
    }
    catch (const Base::Exception& e) {
        warnKept(e.what());
    }
    catch (const std::exception& e) {
        warnKept(e.what());
    }
    catch (...) {
        warnKept("unknown exception");
    }
    return true;
}

namespace
{

// The largest relative change of a face's area that checkDressUp() accepts from a repair
constexpr double repairAreaTolerance = 1e-6;

// The areas of the shape's faces, smallest first
std::vector<double> faceAreas(const TopoShape& shape)
{
    std::vector<double> areas;
    for (TopExp_Explorer it(shape.getShape(), TopAbs_FACE); it.More(); it.Next()) {
        areas.push_back(MassProperties::area(it.Current()));
    }
    std::sort(areas.begin(), areas.end());
    return areas;
}

bool sameArea(double a, double b)
{
    return std::abs(a - b) <= repairAreaTolerance * std::max(a, b);
}

/* Why the repair of a dress-up's result changes its surface, or null. Each face is compared,
 * not the total: a wrong repair adds two small faces (ShapeFix splitting the self-intersecting
 * face of two overlapping rounds), which a tolerance on a large part's total area let through. An
 * invalid base passes its defects on, and their repair may remove faces and area (a fin, ops#12),
 * never add them. */
const char* repairChangesSurface(const TopoShape& before, const TopoShape& after, bool validBase)
{
    const auto areasBefore = faceAreas(before);
    const auto areasAfter = faceAreas(after);
    if (!validBase) {
        const auto sum = [](const std::vector<double>& areas) {
            return std::accumulate(areas.begin(), areas.end(), 0.0);
        };
        if (areasAfter.size() > areasBefore.size()) {
            return "adds faces";
        }
        if (sum(areasAfter) > (1 + repairAreaTolerance) * sum(areasBefore)) {
            return "adds area";
        }
        return nullptr;
    }
    if (areasAfter.size() != areasBefore.size()) {
        return "changes the number of faces";
    }
    for (size_t i = 0; i < areasBefore.size(); ++i) {
        if (!sameArea(areasBefore[i], areasAfter[i])) {
            return "changes the area of a face";
        }
    }
    return nullptr;
}

// Whether the shape is solids only: a solid, or compounds of solids
bool onlySolids(const TopoDS_Shape& shape)
{
    if (shape.IsNull()) {
        return false;
    }
    switch (shape.ShapeType()) {
        case TopAbs_SOLID:
            return true;
        case TopAbs_COMPOUND:
        case TopAbs_COMPSOLID:
            for (TopoDS_Iterator it(shape); it.More(); it.Next()) {
                if (!onlySolids(it.Value())) {
                    return false;
                }
            }
            return true;
        default:
            return false;
    }
}

// The faces outside the shape's solids, in loose shells or on their own
TopoDS_Compound facesOutsideSolids(const TopoDS_Shape& shape)
{
    TopoDS_Compound faces;
    BRep_Builder builder;
    builder.MakeCompound(faces);
    for (TopExp_Explorer it(shape, TopAbs_FACE, TopAbs_SOLID); it.More(); it.Next()) {
        builder.Add(faces, it.Current());
    }
    return faces;
}

int faceCount(const TopoDS_Shape& shape)
{
    int count = 0;
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        ++count;
    }
    return count;
}

// Whether the faces close up, enclosing a volume: every edge of theirs (but degenerate ones)
// bounds two of them. A seam counts twice, so a lone closed face counts as closed.
bool closesUp(const TopoDS_Shape& faces)
{
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(faces, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    if (edgeFaces.IsEmpty()) {
        return false;
    }
    for (int i = 1; i <= edgeFaces.Extent(); ++i) {
        if (!BRep_Tool::Degenerated(TopoDS::Edge(edgeFaces.FindKey(i)))
            && edgeFaces(i).Extent() < 2) {
            return false;
        }
    }
    return true;
}

// The faces in sets connected through shared edges
std::vector<TopoDS_Compound> connectedFaces(const TopoDS_Shape& faces)
{
    TopTools_IndexedMapOfShape all;
    TopExp::MapShapes(faces, TopAbs_FACE, all);
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(faces, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    std::vector<TopoDS_Compound> sets;
    std::vector<bool> seen(all.Extent() + 1, false);
    BRep_Builder builder;
    for (int start = 1; start <= all.Extent(); ++start) {
        if (seen[start]) {
            continue;
        }
        TopoDS_Compound set;
        builder.MakeCompound(set);
        std::vector<int> todo {start};
        seen[start] = true;
        while (!todo.empty()) {
            const auto& face = all(todo.back());
            todo.pop_back();
            builder.Add(set, face);
            for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
                for (const auto& other : edgeFaces.FindFromKey(it.Current())) {
                    const int index = all.FindIndex(other);
                    if (index > 0 && !seen[index]) {
                        seen[index] = true;
                        todo.push_back(index);
                    }
                }
            }
        }
        sets.push_back(set);
    }
    return sets;
}

// The shape's solids, with their names: the solid itself if there is one
TopoShape solidsOf(const TopoShape& shape)
{
    auto solids = shape.getSubTopoShapes(TopAbs_SOLID);
    if (solids.size() == 1) {
        return solids.front();
    }
    TopoShape res(shape.Tag, shape.Hasher, shape.getHistoryAlgorithm());
    res.makeElementCompound(solids);
    return res;
}

}  // namespace

bool enclosesOutsideSolids(const TopoDS_Shape& shape)
{
    // Each shell on its own and each set of connected faces: a closed shell beside an open fin
    // must not pass as open with it
    for (TopExp_Explorer it(shape, TopAbs_SHELL, TopAbs_SOLID); it.More(); it.Next()) {
        if (closesUp(it.Current())) {
            return true;
        }
    }
    const auto sets = connectedFaces(facesOutsideSolids(shape));
    return std::any_of(sets.begin(), sets.end(), [](const auto& faces) {
        return closesUp(faces);
    });
}

namespace
{

// Whether a solid of the shape has a shell that doesn't close up. BRepCheck accepts such a solid:
// a dress-up at the limit on the fin cube (ops#12) keeps the fin as a second shell of its solid,
// and a later Boolean then gives a wrong volume (ops#303). A shell oriented INTERNAL holds faces
// inside the solid on purpose, and is no defect
bool hasOpenShellInASolid(const TopoDS_Shape& shape)
{
    for (TopExp_Explorer solid(shape, TopAbs_SOLID); solid.More(); solid.Next()) {
        for (TopoDS_Iterator it(solid.Current()); it.More(); it.Next()) {
            const TopoDS_Shape& shell = it.Value();
            if (shell.ShapeType() == TopAbs_SHELL && shell.Orientation() != TopAbs_INTERNAL
                && !closesUp(shell)) {
                return true;
            }
        }
    }
    return false;
}

// Each closed shell of the shape's solids, with the volume it bounds: negative for a void
std::vector<std::pair<TopoDS_Shape, double>> closedShells(const TopoDS_Shape& shape)
{
    std::vector<std::pair<TopoDS_Shape, double>> shells;
    for (TopExp_Explorer solid(shape, TopAbs_SOLID); solid.More(); solid.Next()) {
        for (TopoDS_Iterator it(solid.Current()); it.More(); it.Next()) {
            const TopoDS_Shape& shell = it.Value();
            if (shell.ShapeType() == TopAbs_SHELL
                && (shell.Orientation() == TopAbs_FORWARD || shell.Orientation() == TopAbs_REVERSED)
                && closesUp(shell)) {
                shells.emplace_back(shell, MassProperties::volume(shell));
            }
        }
    }
    return shells;
}

// The space a void's shell encloses, as a solid of positive volume
TopoDS_Solid voidSpace(const TopoDS_Shape& shell)
{
    BRep_Builder builder;
    TopoDS_Solid solid;
    builder.MakeSolid(solid);
    builder.Add(solid, shell.Reversed());
    return solid;
}

// A solid, or a void's space, with its bounding box
struct Space
{
    TopoDS_Shape solid;
    Bnd_Box box;
};

Space spaceOf(const TopoDS_Shape& solid)
{
    Space space {solid, {}};
    BRepBndLib::Add(solid, space.box);
    return space;
}

// The volume two solids share, or nothing if the Boolean fails. Not on warnings: a void's space
// and the solid around it share their faces, which warns on a sphere's
std::optional<double> sharedVolume(const Space& a, const Space& b)
{
    if (a.box.IsOut(b.box)) {
        return 0.0;
    }
    try {
        BRepAlgoAPI_Common common(a.solid, b.solid);
        if (!common.IsDone() || common.HasErrors()) {
            return std::nullopt;
        }
        return MassProperties::volume(common.Shape());
    }
    catch (const Standard_Failure&) {
        return std::nullopt;
    }
}

// The volume a space shares with the solids, or nothing if a Boolean fails
std::optional<double> sharedVolume(const Space& space, const std::vector<Space>& solids)
{
    double total = 0.0;
    for (const auto& solid : solids) {
        const auto shared = sharedVolume(space, solid);
        if (!shared) {
            return std::nullopt;
        }
        total += *shared;
    }
    return total;
}

std::vector<Space> solidSpaces(const TopoDS_Shape& shape)
{
    std::vector<Space> spaces;
    for (TopExp_Explorer solid(shape, TopAbs_SOLID); solid.More(); solid.Next()) {
        spaces.push_back(spaceOf(solid.Current()));
    }
    return spaces;
}

/* Why the dress-up's result lost a closed shell of the base's solids, or null. OCCT's fillet and
 * chamfer rebuild a solid they change from its outer shell, and keep its other shells only where
 * they bound the rebuilt solid (ops#303): a second outer shell goes, and its material with it; a
 * void goes also where the material around it stays (a chamfer cutting into it), which fills it.
 * A void that goes with the material around it, or one outside it (an invalid base), rightly
 * goes. */
const char* droppedShell(const TopoDS_Shape& shape, const TopoDS_Shape& base)
{
    // Only a solid with more shells than its outer one has one to lose
    int most = 0;
    for (TopExp_Explorer solid(base, TopAbs_SOLID); solid.More(); solid.Next()) {
        int shells = 0;
        for (TopoDS_Iterator it(solid.Current()); it.More(); it.Next()) {
            ++shells;
        }
        most = std::max(most, shells);
    }
    if (most < 2) {
        return nullptr;
    }
    const auto before = closedShells(base);
    const auto after = closedShells(shape);
    const auto count = [](const auto& shells, bool material) {
        return std::count_if(shells.begin(), shells.end(), [&](const auto& shell) {
            return material ? shell.second > 0 : shell.second < 0;
        });
    };
    if (count(after, true) < count(before, true)) {
        return "drops a shell of the base's solids that bounds material";
    }
    if (count(after, false) >= count(before, false)) {
        return nullptr;
    }
    // A void the result lost is one no void of the result overlaps: a void the dress-up changes
    // (an edge of it rounded) stays one. A lost void's space must hold no more material of the
    // result than of the base (another solid of a compound may lie in it), which a sample of points
    // on a sphere or a cylinder misses (PR 341 reviews). Bounding boxes spare most Booleans
    std::vector<Space> keptVoids;
    for (const auto& [shell, volume] : after) {
        if (volume < 0) {
            keptVoids.push_back(spaceOf(voidSpace(shell)));
        }
    }
    std::optional<std::vector<Space>> resultSolids;
    std::optional<std::vector<Space>> baseSolids;
    for (const auto& [shell, volume] : before) {
        if (volume >= 0) {
            continue;
        }
        const double threshold = 1e-6 * -volume;
        const Space space = spaceOf(voidSpace(shell));
        const bool kept = std::any_of(keptVoids.begin(), keptVoids.end(), [&](const auto& other) {
            const auto shared = sharedVolume(space, other);
            return shared && *shared > threshold;
        });
        if (kept) {
            continue;
        }
        if (!resultSolids) {
            resultSolids = solidSpaces(shape);
            baseSolids = solidSpaces(base);
        }
        const auto filled = sharedVolume(space, *resultSolids);
        const auto had = sharedVolume(space, *baseSolids);
        if (!filled || !had) {
            return "loses a void of the base whose space can't be checked";
        }
        if (*filled - *had > threshold) {
            return "fills a void of the base";
        }
    }
    return nullptr;
}

// The members of the shape's compounds that are faces, wires, edges or vertices, outside every
// shell
void collectLooseParts(const TopoShape& shape, std::vector<TopoShape>& parts)
{
    if (shape.getShape().ShapeType() != TopAbs_COMPOUND) {
        return;
    }
    for (const auto& member : shape.getSubTopoShapes()) {
        switch (member.getShape().ShapeType()) {
            case TopAbs_COMPOUND:
                collectLooseParts(member, parts);
                break;
            case TopAbs_FACE:
            case TopAbs_WIRE:
            case TopAbs_EDGE:
            case TopAbs_VERTEX:
                parts.push_back(member);
                break;
            default:
                break;
        }
    }
}

/* Puts the base's loose parts into the dress-up's result: OCCT's fillet and chamfer keep only the
 * solids and shells of their input, and drop its loose faces, wires, edges and vertices, which
 * they leave alone (ops#303). False if the result has loose parts of its own: they would come
 * from the maker's copy of the base, so which of the base's they are can't be told. */
bool keepLooseParts(TopoShape& shape, const TopoShape& base)
{
    std::vector<TopoShape> parts;
    collectLooseParts(base, parts);
    if (parts.empty()) {
        return true;
    }
    std::vector<TopoShape> kept;
    collectLooseParts(shape, kept);
    if (!kept.empty()) {
        FC_WARN("Dress-up result with " << kept.size() << " shapes outside its shells, beside the "
                                        << "base's " << parts.size());
        return false;
    }
    std::vector<TopoShape> members;
    if (shape.getShape().ShapeType() == TopAbs_COMPOUND) {
        members = shape.getSubTopoShapes();
    }
    else {
        members.push_back(shape);
    }
    members.insert(members.end(), parts.begin(), parts.end());
    TopoShape res(shape.Tag, shape.Hasher, shape.getHistoryAlgorithm());
    res.makeElementCompound(members);
    shape = res;
    return true;
}

// checkDressUp() for what OCCT kept of the base: its solids and shells
bool checkResult(TopoShape& shape, const TopoShape& base)
{
    // An invalid base passes its defects on, also into a result BRepCheck accepts: there it is
    // repaired as an invalid one. A valid base keeps the check as before, since a solid may hold an
    // open shell on purpose (internal faces). The base's check is a full BRepCheck, so it runs
    // only for a result that has such a shell
    if (shape.isValid() && (!hasOpenShellInASolid(shape.getShape()) || base.isValid())) {
        return true;
    }
    const auto solids = base.countSubShapes(TopAbs_SOLID);
    const auto found = shape.countSubShapes(TopAbs_SOLID);
    if (found != solids) {
        FC_WARN("Invalid dress-up result with " << found << " solids from " << solids);
        return false;
    }
    TopoShape repaired(shape.Tag, shape.Hasher, shape.getHistoryAlgorithm());
    repaired.makeElementCopy(shape);
    if (!fixKeepingNames(repaired, shape)) {
        FC_WARN("Invalid dress-up result that the repair can't make valid");
        return false;
    }
    if (repaired.countSubShapes(TopAbs_SOLID) != solids) {
        FC_WARN("Invalid dress-up result whose repair loses solids");
        return false;
    }
    // ShapeFix may move faces out of the solid into an open shell beside it (the fin of an
    // invalid base, ops#12): a valid compound whose volume counts the loose faces, wrong
    // downstream. Judged on the result, not the base: OCCT drops a base's loose faces. The solids
    // of a solids-only result are the repair if the base is invalid, unless the faces dropped
    // enclose a volume; on a valid base nothing may move out. A result with faces outside its
    // solids (a shell's) keeps them, and the repair may move no more out.
    const auto outside = facesOutsideSolids(repaired.getShape());
    if (onlySolids(shape.getShape())) {
        if (!onlySolids(repaired.getShape())) {
            if (base.isValid()) {
                FC_WARN("Invalid dress-up result whose repair leaves shapes outside its solids");
                return false;
            }
            if (enclosesOutsideSolids(repaired.getShape())) {
                FC_WARN("Invalid dress-up result whose repair leaves a closed shell outside its solids");
                return false;
            }
            repaired = solidsOf(repaired);
        }
    }
    else if (faceCount(outside) > faceCount(facesOutsideSolids(shape.getShape()))) {
        FC_WARN("Invalid dress-up result whose repair moves faces out of its solids");
        return false;
    }
    if (const char* why = repairChangesSurface(shape, repaired, base.isValid())) {
        FC_WARN("Invalid dress-up result whose repair " << why);
        return false;
    }
    shape = repaired;
    return true;
}

// The angle within which an edge continues another at a vertex: OCCT's fillet and chamfer carry
// on along such an edge
constexpr double chainAngle = 0.01;
// The least thickness of a piece of material the result has that the base didn't, its volume
// over its area: below it the piece is the Boolean's numerical noise
constexpr double leastThickness = 1e-6;
// How far the Boolean's region reaches beyond the changed faces, relative to its least extent and
// least: its sides stay clear of the faces in it
constexpr double regionMargin = 0.05;
constexpr double leastMargin = 0.01;
// How near a concave edge, beyond its tolerance, a piece of the material the result adds must come
// to be that edge's: the material a concave edge's dress-up adds lies in its corner and holds it
constexpr double edgeReach = 1e-4;

gp_Vec tangentAt(const TopoDS_Edge& edge, const TopoDS_Vertex& vertex)
{
    BRepAdaptor_Curve curve(edge);
    gp_Pnt point;
    gp_Vec tangent;
    curve.D1(BRep_Tool::Parameter(vertex, edge), point, tangent);
    return tangent;
}

// The edges OCCT dresses up for the given ones: those, and every edge that continues one of them
// tangentially at a vertex, which OCCT carries the fillet or chamfer on along
TopTools_IndexedMapOfShape chainOf(const TopoDS_Shape& base, const std::vector<TopoShape>& edges)
{
    TopTools_IndexedDataMapOfShapeListOfShape edgesAt;
    TopExp::MapShapesAndAncestors(base, TopAbs_VERTEX, TopAbs_EDGE, edgesAt);
    TopTools_IndexedMapOfShape chain;
    for (const auto& edge : edges) {
        if (!edge.isNull() && edge.getShape().ShapeType() == TopAbs_EDGE) {
            chain.Add(edge.getShape());
        }
    }
    for (int i = 1; i <= chain.Extent(); ++i) {
        const TopoDS_Edge edge = TopoDS::Edge(chain(i));
        for (TopExp_Explorer it(edge, TopAbs_VERTEX); it.More(); it.Next()) {
            const TopoDS_Vertex& vertex = TopoDS::Vertex(it.Current());
            const int index = edgesAt.FindIndex(vertex);
            if (index == 0 || BRep_Tool::Degenerated(edge)) {
                continue;
            }
            const gp_Vec tangent = tangentAt(edge, vertex);
            for (const auto& other : edgesAt(index)) {
                const TopoDS_Edge& next = TopoDS::Edge(other);
                if (chain.Contains(next) || BRep_Tool::Degenerated(next)) {
                    continue;
                }
                const gp_Vec along = tangentAt(next, vertex);
                if (tangent.Magnitude() > gp::Resolution() && along.Magnitude() > gp::Resolution()
                    && tangent.IsParallel(along, chainAngle)) {
                    chain.Add(next);
                }
            }
        }
    }
    return chain;
}

// The faces of the base that hold a vertex of the edges
TopTools_IndexedMapOfShape facesAt(
    const TopTools_IndexedDataMapOfShapeListOfShape& facesAtVertices,
    const TopTools_IndexedMapOfShape& edges
)
{
    TopTools_IndexedMapOfShape faces;
    for (int i = 1; i <= edges.Extent(); ++i) {
        for (TopExp_Explorer it(edges(i), TopAbs_VERTEX); it.More(); it.Next()) {
            const int index = facesAtVertices.FindIndex(it.Current());
            if (index == 0) {
                continue;
            }
            for (const auto& face : facesAtVertices(index)) {
                faces.Add(face);
            }
        }
    }
    return faces;
}

std::vector<gp_Pnt> vertexPoints(const TopoDS_Shape& face)
{
    TopTools_IndexedMapOfShape vertices;
    TopExp::MapShapes(face, TopAbs_VERTEX, vertices);
    std::vector<gp_Pnt> points;
    points.reserve(vertices.Extent());
    for (int i = 1; i <= vertices.Extent(); ++i) {
        points.push_back(BRep_Tool::Pnt(TopoDS::Vertex(vertices(i))));
    }
    return points;
}

bool samePoints(const std::vector<gp_Pnt>& a, const std::vector<gp_Pnt>& b)
{
    return a.size() == b.size() && std::all_of(a.begin(), a.end(), [&](const gp_Pnt& p) {
               return std::any_of(b.begin(), b.end(), [&](const gp_Pnt& q) {
                   return p.Distance(q) <= Precision::Confusion();
               });
           });
}

const Geom_Surface* surfaceOf(const TopoDS_Shape& face)
{
    TopLoc_Location location;
    return BRep_Tool::Surface(TopoDS::Face(face), location).get();
}

// The faces that don't come through the dress-up unchanged, of the base and of the result
struct Changes
{
    // A face of the base other than the given ones changed: the check runs
    bool away = false;
    // Where those, and the result's faces that aren't on the surface of a given one, lie: every
    // recess the result fills has a changed face there (its walls, its floor)
    Bnd_Box region;
    // The base's faces the result changed, the given ones included
    TopTools_IndexedMapOfShape changed;
};

/* The faces of the base the result changed: the result has no face on its surface with its
 * vertices. OCCT's maker runs on a copy of the base that shares its geometry (ops#345) and keeps
 * the faces it leaves alone, and so do the exact construction's Booleans; a repaired result,
 * whose geometry is copied, changes all of them. The given faces, those at the dressed edges,
 * change in an ordinary dress-up: they don't count, nor do the result's faces on their surfaces,
 * which may span the whole base (a plate's top face) while they change only at the edges. */
Changes changesOf(
    const TopoDS_Shape& shape,
    const TopoDS_Shape& base,
    const TopTools_IndexedMapOfShape& changing
)
{
    std::unordered_map<const Geom_Surface*, std::vector<int>> onSurface;
    TopTools_IndexedMapOfShape resultFaces;
    TopExp::MapShapes(shape, TopAbs_FACE, resultFaces);
    for (int i = 1; i <= resultFaces.Extent(); ++i) {
        onSurface[surfaceOf(resultFaces(i))].push_back(i);
    }
    std::vector<bool> kept(resultFaces.Extent() + 1, false);
    std::unordered_set<const Geom_Surface*> changingSurfaces;
    Changes changes;
    TopTools_IndexedMapOfShape baseFaces;
    TopExp::MapShapes(base, TopAbs_FACE, baseFaces);
    for (int i = 1; i <= baseFaces.Extent(); ++i) {
        const TopoDS_Shape& face = baseFaces(i);
        const Geom_Surface* surface = surfaceOf(face);
        if (changing.Contains(face)) {
            changingSurfaces.insert(surface);
        }
        const auto candidates = onSurface.find(surface);
        if (candidates != onSurface.end()) {
            const auto points = vertexPoints(face);
            const auto match = std::find_if(
                candidates->second.begin(),
                candidates->second.end(),
                [&](int index) { return samePoints(points, vertexPoints(resultFaces(index))); }
            );
            if (match != candidates->second.end()) {
                kept[*match] = true;
                continue;
            }
        }
        changes.changed.Add(face);
        if (!changing.Contains(face)) {
            changes.away = true;
            BRepBndLib::Add(face, changes.region, false);
        }
    }
    for (int i = 1; i <= resultFaces.Extent(); ++i) {
        if (!kept[i] && changingSurfaces.count(surfaceOf(resultFaces(i))) == 0) {
            BRepBndLib::Add(resultFaces(i), changes.region, false);
        }
    }
    return changes;
}

TopoDS_Compound solidsIn(const TopoDS_Shape& shape)
{
    BRep_Builder builder;
    TopoDS_Compound solids;
    builder.MakeCompound(solids);
    for (TopExp_Explorer it(shape, TopAbs_SOLID); it.More(); it.Next()) {
        builder.Add(solids, it.Current());
    }
    return solids;
}

// The edges of the chain between two faces that aren't convex: a concave edge's dress-up adds
// material in its corner (ChFi3d's own test, which the fillet uses). An edge without exactly two
// faces (a seam, a free or a non-manifold edge) counts as concave too: the lenient side, where
// material on the faces at it passes
TopTools_IndexedMapOfShape concaveEdges(const TopoDS_Shape& base, const TopTools_IndexedMapOfShape& chain)
{
    TopTools_IndexedDataMapOfShapeListOfShape facesOfEdges;
    TopExp::MapShapesAndAncestors(base, TopAbs_EDGE, TopAbs_FACE, facesOfEdges);
    TopTools_IndexedMapOfShape concave;
    for (int i = 1; i <= chain.Extent(); ++i) {
        const TopoDS_Edge& edge = TopoDS::Edge(chain(i));
        const int index = facesOfEdges.FindIndex(edge);
        TopTools_IndexedMapOfShape faces;
        if (index != 0) {
            for (const auto& face : facesOfEdges(index)) {
                faces.Add(face);
            }
        }
        if (faces.Extent() != 2
            || ChFi3d::DefineConnectType(
                   edge,
                   TopoDS::Face(faces(1)),
                   TopoDS::Face(faces(2)),
                   std::sin(Precision::Angular()),
                   false
               ) != ChFiDS_Convex) {
            concave.Add(edge);
        }
    }
    return concave;
}

// The selected edge nearest to the piece, by its name in the base
std::string nearestEdge(
    const TopoShape& base,
    const std::vector<TopoShape>& edges,
    const TopoDS_Shape& piece
)
{
    std::string name;
    double least = 0.0;
    for (const auto& edge : edges) {
        BRepExtrema_DistShapeShape distance(piece, edge.getShape());
        if (!distance.IsDone()) {
            continue;
        }
        const int index = base.findShape(edge.getShape());
        if (index != 0 && (name.empty() || distance.Value() < least)) {
            least = distance.Value();
            name = TopoShape::shapeName(TopAbs_EDGE) + std::to_string(index);
        }
    }
    return name.empty() ? std::string("an edge") : name;
}

/* Adds the faces of the base that the result changed and that meet one of the faces across a
 * smooth edge, and so on. A concave edge's band runs on onto a face tangent to one at the edge (a
 * floor that ends in a round) and trims it, and the material it adds lies on that face too (PR 346
 * review, H1). A face the dress-up leaves alone holds none of it, and the growth stops there: else
 * it would run on over the base, through a round the band doesn't reach, to a smooth recess another
 * edge's band fills (PR 346 round 2). A recess's walls meet its floor and the face it opens on at
 * sharp edges, so they stay out. A filled recess's faces change too, so the growth still reaches a
 * smooth one in a face it holds; the material filling it lies apart from the concave edges, which
 * whatItAdds() checks (PR 346 round 3). */
void addSmoothNeighbours(
    const TopoDS_Shape& base,
    const TopTools_IndexedMapOfShape& changed,
    TopTools_IndexedMapOfShape& faces
)
{
    TopTools_IndexedDataMapOfShapeListOfShape facesOfEdges;
    TopExp::MapShapesAndAncestors(base, TopAbs_EDGE, TopAbs_FACE, facesOfEdges);
    for (int i = 1; i <= faces.Extent(); ++i) {
        const TopoDS_Face face = TopoDS::Face(faces(i));
        for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
            const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
            const int index = facesOfEdges.FindIndex(edge);
            if (index == 0 || BRep_Tool::Degenerated(edge)) {
                continue;
            }
            for (const auto& other : facesOfEdges(index)) {
                if (!other.IsSame(face) && !faces.Contains(other) && changed.Contains(other)
                    && ChFi3d::IsTangentFaces(edge, face, TopoDS::Face(other))) {
                    faces.Add(other);
                }
            }
        }
    }
}

Bnd_Box boundsOf(const TopoDS_Shape& shape)
{
    Bnd_Box bounds;
    BRepBndLib::Add(shape, bounds, false);
    return bounds;
}

bool holds(const Bnd_Box& outer, const Bnd_Box& inner)
{
    if (inner.IsVoid()) {
        return true;
    }
    double a[6];
    double b[6];
    outer.Get(a[0], a[1], a[2], a[3], a[4], a[5]);
    inner.Get(b[0], b[1], b[2], b[3], b[4], b[5]);
    return a[0] <= b[0] && a[1] <= b[1] && a[2] <= b[2] && b[3] <= a[3] && b[4] <= a[4]
        && b[5] <= a[5];
}

// Whether the piece reaches one of the edges. If the distance can't be computed, it counts as
// reaching it: the faces the piece lies on still decide
bool reachesAny(const TopoDS_Shape& piece, const TopTools_IndexedMapOfShape& edges)
{
    const Bnd_Box bounds = boundsOf(piece);
    for (int i = 1; i <= edges.Extent(); ++i) {
        const TopoDS_Edge& edge = TopoDS::Edge(edges(i));
        const double reach = edgeReach + BRep_Tool::Tolerance(edge);
        Bnd_Box around = boundsOf(edge);
        around.Enlarge(reach);
        if (around.IsOut(bounds)) {
            continue;
        }
        BRepExtrema_DistShapeShape distance(piece, edge);
        if (!distance.IsDone() || distance.Value() <= reach) {
            return true;
        }
    }
    return false;
}

// The solids of the shape whose bounds meet the box
TopoDS_Compound solidsMeeting(const TopoDS_Shape& shape, const Bnd_Box& box)
{
    BRep_Builder builder;
    TopoDS_Compound solids;
    builder.MakeCompound(solids);
    for (TopExp_Explorer it(shape, TopAbs_SOLID); it.More(); it.Next()) {
        if (!box.IsOut(boundsOf(it.Current()))) {
            builder.Add(solids, it.Current());
        }
    }
    return solids;
}

// The solids of the base that hold a dressed edge: OCCT changes no other
TopoDS_Compound dressedSolids(const TopoDS_Shape& base, const TopTools_IndexedMapOfShape& chain)
{
    BRep_Builder builder;
    TopoDS_Compound solids;
    builder.MakeCompound(solids);
    for (TopExp_Explorer it(base, TopAbs_SOLID); it.More(); it.Next()) {
        TopTools_IndexedMapOfShape edges;
        TopExp::MapShapes(it.Current(), TopAbs_EDGE, edges);
        for (int i = 1; i <= chain.Extent(); ++i) {
            if (edges.Contains(chain(i))) {
                builder.Add(solids, it.Current());
                break;
            }
        }
    }
    return solids;
}

// Sets up a non-destructive Boolean: one with the default would raise the shapes' tolerances in
// place
template<class Boolean>
bool runBoolean(Boolean& boolean, const TopoDS_Shape& object, const TopoDS_Shape& tool)
{
    TopTools_ListOfShape objects;
    TopTools_ListOfShape tools;
    objects.Append(object);
    tools.Append(tool);
    boolean.SetArguments(objects);
    boolean.SetTools(tools);
    boolean.SetNonDestructive(Standard_True);
    boolean.Build();
    return boolean.IsDone() && !boolean.HasErrors();
}

// The images of a shape in a Boolean's result: none if it was deleted, the shape itself if it
// came through unchanged
void addImages(
    BRepAlgoAPI_BooleanOperation& boolean,
    const TopoDS_Shape& shape,
    TopTools_ListOfShape& images
)
{
    if (boolean.IsDeleted(shape)) {
        return;
    }
    const TopTools_ListOfShape& modified = boolean.Modified(shape);
    if (modified.IsEmpty()) {
        images.Append(shape);
    }
    for (const auto& image : modified) {
        images.Append(image);
    }
}

// What the dress-up changed, found before the Boolean
struct Prepared
{
    // The result's solids to check, and the base's solids they're compared with
    TopoDS_Compound checked;
    TopoDS_Compound against;
    // Where the result can have material the base didn't
    Bnd_Box region;
    TopTools_IndexedMapOfShape concave;
    // The base's faces the material a concave edge adds may lie on
    TopTools_IndexedMapOfShape allowed;
};

// Whether the result changed the base away from its edges (the gate), and where
std::optional<Prepared> prepare(
    const TopoDS_Compound& result,
    const TopoDS_Compound& before,
    const std::vector<TopoShape>& edges
)
{
    const auto chain = chainOf(before, edges);
    const TopoDS_Compound dressed = dressedSolids(before, chain);
    if (!TopoDS_Iterator(dressed).More()) {
        // None of the edges is a solid's: they are those of a shell or a face of the base beside
        // its solids (a compound of a solid and an open shell), which the check doesn't cover
        FC_WARN(
            "Dress-up result not checked for a filled recess: no solid of the base holds its edges"
        );
        return std::nullopt;
    }
    // The result's solids where the dressed ones were: OCCT keeps the others as they were
    Bnd_Box dressedBounds = boundsOf(dressed);
    dressedBounds.Enlarge(Precision::Confusion());
    const TopoDS_Compound images = solidsMeeting(result, dressedBounds);
    TopTools_IndexedDataMapOfShapeListOfShape facesAtVertices;
    TopExp::MapShapesAndAncestors(dressed, TopAbs_VERTEX, TopAbs_FACE, facesAtVertices);
    const Changes changes = changesOf(images, dressed, facesAt(facesAtVertices, chain));
    if (!changes.away) {
        return std::nullopt;
    }
    Prepared prepared;
    // A concave edge adds material in its corner, on the faces at it and on the changed ones
    // joining them smoothly
    prepared.concave = concaveEdges(dressed, chain);
    if (prepared.concave.Extent() > 0) {
        prepared.allowed = facesAt(facesAtVertices, prepared.concave);
        addSmoothNeighbours(dressed, changes.changed, prepared.allowed);
    }
    // Every recess the result fills has a changed face in the region, so the Boolean runs on what
    // lies there (PR 346 review, M1). Its sides keep clear of the faces in it. It holds the concave
    // edges too, so the material their dress-up adds still reaches them once cut down to it
    prepared.region = changes.region;
    for (int i = 1; i <= prepared.concave.Extent(); ++i) {
        BRepBndLib::Add(prepared.concave(i), prepared.region, false);
    }
    double x0 = 0.0;
    double y0 = 0.0;
    double z0 = 0.0;
    double x1 = 0.0;
    double y1 = 0.0;
    double z1 = 0.0;
    prepared.region.Get(x0, y0, z0, x1, y1, z1);
    prepared.region.Enlarge(regionMargin * std::min({x1 - x0, y1 - y0, z1 - z0}) + leastMargin);
    prepared.checked = solidsMeeting(images, prepared.region);
    prepared.against = solidsMeeting(before, prepared.region);
    if (!TopoDS_Iterator(prepared.checked).More()) {
        return std::nullopt;
    }
    return prepared;
}

// The material the result has that the base didn't, and why it is wrong, or an empty string
std::string whatItAdds(const Prepared& prepared, const TopoShape& base, const std::vector<TopoShape>& edges)
{
    const auto& [checked, against, region, concave, allowed] = prepared;
    // Both cut down to the region, unless it holds them whole. If that fails, the Boolean runs
    // on the whole solids
    TopoDS_Shape object = checked;
    TopoDS_Shape tool = against;
    std::unique_ptr<BRepAlgoAPI_Common> toolInRegion;
    if (!holds(region, boundsOf(checked)) || !holds(region, boundsOf(against))) {
        double x0 = 0.0;
        double y0 = 0.0;
        double z0 = 0.0;
        double x1 = 0.0;
        double y1 = 0.0;
        double z1 = 0.0;
        region.Get(x0, y0, z0, x1, y1, z1);
        const TopoDS_Shape box = BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape();
        BRepAlgoAPI_Common objectInRegion;
        toolInRegion = std::make_unique<BRepAlgoAPI_Common>();
        if (runBoolean(objectInRegion, checked, box) && runBoolean(*toolInRegion, against, box)) {
            object = objectInRegion.Shape();
            tool = toolInRegion->Shape();
        }
        else {
            toolInRegion.reset();
        }
    }
    BRepAlgoAPI_Cut cut;
    if (!runBoolean(cut, object, tool)) {
        return "changes faces away from its edges in a way that can't be checked";
    }
    // A concave edge adds material in its corner, on the allowed faces: a piece of it that lies on
    // any other face of the base fills what that face bounded, and so does one that doesn't reach a
    // concave edge, whatever faces it lies on (a smooth recess whose faces the growth allowed, PR 346
    // round 3; a repaired result, all of whose faces changed)
    TopTools_IndexedMapOfShape walls;
    if (concave.Extent() > 0) {
        TopTools_IndexedMapOfShape baseFaces;
        TopExp::MapShapes(against, TopAbs_FACE, baseFaces);
        for (int i = 1; i <= baseFaces.Extent(); ++i) {
            const TopoDS_Shape& face = baseFaces(i);
            if (allowed.Contains(face)) {
                continue;
            }
            TopTools_ListOfShape parts;
            if (toolInRegion) {
                addImages(*toolInRegion, face, parts);
            }
            else {
                parts.Append(face);
            }
            TopTools_ListOfShape images;
            for (const auto& part : parts) {
                addImages(cut, part, images);
            }
            for (const auto& image : images) {
                walls.Add(image);
            }
        }
    }
    for (TopExp_Explorer it(cut.Shape(), TopAbs_SOLID); it.More(); it.Next()) {
        const TopoDS_Shape& piece = it.Current();
        if (std::abs(MassProperties::volume(piece))
            <= leastThickness * MassProperties::area(piece)) {
            continue;
        }
        bool wrong = concave.Extent() == 0 || !reachesAny(piece, concave);
        for (TopExp_Explorer face(piece, TopAbs_FACE); !wrong && face.More(); face.Next()) {
            wrong = walls.Contains(face.Current());
        }
        if (wrong) {
            return "fills a recess of the base next to " + nearestEdge(base, edges, piece)
                + ": its new face covers the recess's opening";
        }
    }
    return {};
}

}  // namespace

bool checkDressUp(TopoShape& shape, const TopoShape& base, LooseParts looseParts)
{
    if (!checkResult(shape, base)) {
        return false;
    }
    // After the repair, which may close a shell that closesUp() would not count
    if (const char* why = droppedShell(shape.getShape(), base.getShape())) {
        FC_WARN("Dress-up result that " << why);
        return false;
    }
    return looseParts == LooseParts::drop || keepLooseParts(shape, base);
}

std::string filledPocket(const TopoShape& shape, const TopoShape& base, const std::vector<TopoShape>& edges)
{
    const TopoDS_Compound result = solidsIn(shape.getShape());
    const TopoDS_Compound before = solidsIn(base.getShape());
    if (edges.empty() || !TopoDS_Iterator(result).More() || !TopoDS_Iterator(before).More()) {
        return {};
    }
    // If the analysis before the Boolean throws, the check is skipped with a warning: it decides
    // only whether the Boolean runs (PR 346 review, L1)
    std::optional<Prepared> prepared;
    try {
        prepared = prepare(result, before, edges);
    }
    catch (const Standard_Failure& e) {
        FC_WARN("Dress-up result not checked for a filled recess: " << e.GetMessageString());
        return {};
    }
    if (!prepared) {
        return {};
    }
    std::string why;
    try {
        FC_LOG("Dress-up result that changes faces away from its edges: checking what it adds");
        why = whatItAdds(*prepared, base, edges);
    }
    catch (const Standard_Failure&) {
        why = "changes faces away from its edges in a way that can't be checked";
    }
    if (why.empty()) {
        return {};
    }
    // A Boolean with an invalid base finds material that isn't there (the fin cube's inner face,
    // ops#12): such a base's defects pass on, as in checkDressUp(). Checked only for a result
    // that would fail: on a large base it costs more than the Boolean in the region
    try {
        if (!BRepCheck_Analyzer(prepared->against).IsValid()) {
            return {};
        }
    }
    catch (const Standard_Failure& e) {
        FC_WARN("Dress-up result not checked for a filled recess: " << e.GetMessageString());
        return {};
    }
    return why;
}

}  // namespace Part
