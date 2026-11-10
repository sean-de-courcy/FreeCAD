// SPDX-License-Identifier: LGPL-2.1-or-later

// Owners outside every Body (FreeCAD-CH ops#654 S2, notes/parts-design.md 10.1 "(b) on the build"
// and 10.9): which features run as owners, and the in-scope parts' shapes at an owner's place.

#include <vector>

#include <TopAbs_ShapeEnum.hxx>

#include <App/PropertyLinks.h>
#include <Mod/Part/App/PartFeature.h>

#include "Body.h"
#include "Feature.h"
#include "StudioList.h"
#include "StudioOwner.h"

namespace PartDesign
{

namespace
{

/// The solid feature of part just before owner's step: the step's previous solid in its Body's
/// chain, else (no step yet) the one reconcile wrote into owner's StudioBases
const Part::Feature* baseOf(const App::DocumentObject* owner, const Body* part)
{
    if (auto step = StudioList::stepOf(owner, part)) {
        auto previous = const_cast<Body*>(part)->getPrevSolidFeature(step);
        return freecad_cast<const Part::Feature*>(previous);
    }
    auto bases = freecad_cast<const App::PropertyLinkList*>(owner->getPropertyByName("StudioBases"));
    if (!bases) {
        return nullptr;
    }
    for (auto base : bases->getValues()) {
        if (base && part->hasObject(base)) {
            return freecad_cast<const Part::Feature*>(base);
        }
    }
    return nullptr;
}

}  // namespace

Part::TopoShape studioBaseAt(const App::DocumentObject* owner, const Body* part)
{
    if (!owner || !part) {
        return {};
    }
    const Part::Feature* base = baseOf(owner, part);
    if (!base) {
        return {};
    }
    // In its Body's frame (its own placement on it), as a Body member's base is
    Part::TopoShape shape = base->Shape.getShape();
    if (shape.isNull() || !shape.hasSubShape(TopAbs_SOLID)) {
        return {};
    }
    shape.transformShape(part->globalPlacement().toMatrix(), false, true);
    return shape;
}

Part::TopoShape studioScopeBaseAt(const App::DocumentObject* owner)
{
    std::vector<Part::TopoShape> shapes;
    for (auto part : studioScopeOf(owner)) {
        Part::TopoShape shape = studioBaseAt(owner, part);
        if (!shape.isNull()) {
            shapes.push_back(shape);
        }
    }
    if (shapes.empty()) {
        return {};
    }
    // One child per part, in scope order, not fused: parts that touch stay two (Up to next tells
    // them apart, Onshape O8e)
    Part::TopoShape out;
    out.makeElementCompound(
        shapes,
        nullptr,
        Part::TopoShape::SingleShapeCompoundCreationPolicy::forceCompound
    );
    return out;
}

bool runsAsStudioOwner(const Feature* feature)
{
    // An instance outside every Body that the studio's list holds: it computes only its tool
    return feature && feature->isAttachedToDocument() && !feature->getFeatureBody()
        && isStudioOwner(feature);
}

}  // namespace PartDesign
