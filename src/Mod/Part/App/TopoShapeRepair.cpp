// SPDX-License-Identifier: LGPL-2.1-or-later

#include "TopoShapeRepair.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <memory>
#include <string>
#include <tuple>
#include <vector>

#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <gp_Pnt.hxx>
#include <TopAbs_ShapeEnum.hxx>

#include <App/ElementMap.h>

#include "Geometry.h"
#include "TopoShape.h"

namespace Part
{

namespace
{

// findSubShapesWithSharedVertex()'s default tolerance, for the faces' centres
constexpr double tolerance = 1e-7;
// The largest relative difference of two faces' areas that are the same face
constexpr double areaTolerance = 1e-9;

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
            && std::abs(area - other.area) <= areaTolerance * std::max(area, 1.0)
            && centre.Distance(other.centre) <= tolerance;
    }
};

// The element of \a before that each element of \a after of \a type is, by index: one-to-one
// matches only (an element of \a before that two elements of \a after match is neither's).
std::map<int, int> matchesOf(const TopoShape& before, const TopoShape& after, TopAbs_ShapeEnum type)
{
    const std::string& typeName = TopoShape::shapeName(type);
    const auto count = static_cast<int>(after.countSubShapes(type));
    std::map<int, int> found;
    for (int i = 1; i <= count; ++i) {
        std::vector<std::string> names;
        before.findSubShapesWithSharedVertex(after.getSubTopoShape(type, i), &names);
        if (names.size() == 1) {
            found[i] = std::stoi(names.front().substr(typeName.size()));
        }
    }
    if (type == TopAbs_FACE) {
        // A face the repair split an edge of has another vertex: the same kind of surface, area
        // and centre
        std::map<int, FaceKey> unmatched;
        for (int j = 1; j <= static_cast<int>(before.countSubShapes(type)); ++j) {
            unmatched.emplace(j, FaceKey(before.getSubTopoShape(type, j)));
        }
        for (const auto& [i, j] : found) {
            unmatched.erase(j);
        }
        for (int i = 1; i <= count; ++i) {
            if (found.count(i)) {
                continue;
            }
            const FaceKey key(after.getSubTopoShape(type, i));
            std::vector<int> same;
            for (const auto& [j, other] : unmatched) {
                if (key.same(other)) {
                    same.push_back(j);
                }
            }
            if (same.size() == 1) {
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

}  // namespace

bool fixKeepingNames(TopoShape& shape)
{
    // The shape as it was, names included: a deep copy, because fix() changes sub-shapes in place
    TopoShape before(shape.Tag, shape.Hasher, shape.getHistoryAlgorithm());
    before.makeElementCopy(shape);
    if (!shape.fix()) {
        return false;
    }
    if (shape.getHistoryAlgorithm() != App::HistoryAlgorithm::V2 || !shape.hasElementMap()
        || !before.hasElementMap()) {
        return true;
    }
    std::vector<std::tuple<Data::IndexedName, Data::MappedName, Data::ElementIDRefs>> names;
    for (const auto type : {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE}) {
        const auto& typeName = TopoShape::shapeName(type);
        const auto matches = matchesOf(before, shape, type);
        const auto count = static_cast<int>(shape.countSubShapes(type));
        for (int i = 1; i <= count; ++i) {
            const auto element = Data::IndexedName::fromConst(typeName.c_str(), i);
            const auto match = matches.find(i);
            const bool kept = match != matches.end();
            const auto source = kept
                ? Data::IndexedName::fromConst(typeName.c_str(), match->second)
                : element;
            // In the element's order, so its first name stays first
            for (auto& [name, sids] : (kept ? before : shape).getElementMappedNames(source)) {
                names.emplace_back(element, name, sids);
            }
        }
    }
    // A new map: the old one may be shared, e.g. with the shape this one is a copy of
    shape.resetElementMap(std::make_shared<Data::ElementMap>());
    for (const auto& [element, name, sids] : names) {
        shape.setElementName(element, name, shape.Tag, &sids);
    }
    return true;
}

}  // namespace Part
