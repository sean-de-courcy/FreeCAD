// SPDX-License-Identifier: LGPL-2.1-or-later

#include "TopoShapeRepair.h"

#include <algorithm>
#include <cmath>
#include <exception>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <gp_Pnt.hxx>
#include <Standard_Failure.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>

#include <App/ElementMap.h>
#include <Base/Console.h>
#include <Base/Exception.h>

#include "Geometry.h"
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
        BRepGProp::SurfaceProperties(face.getShape(), props);
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

bool fixKeepingNames(TopoShape& shape)
{
    // The shape as it was, names included: a deep copy, because fix() changes sub-shapes in
    // place. A copy that fails costs the names, not the repair.
    TopoShape before(shape.Tag, shape.Hasher, shape.getHistoryAlgorithm());
    try {
        before.makeElementCopy(shape);
    }
    catch (const Standard_Failure& e) {
        warnKept(e.GetMessageString());
        return shape.fix();
    }
    catch (const Base::Exception& e) {
        warnKept(e.what());
        return shape.fix();
    }
    catch (const std::exception& e) {
        warnKept(e.what());
        return shape.fix();
    }
    return fixKeepingNames(shape, before);
}

}  // namespace Part
