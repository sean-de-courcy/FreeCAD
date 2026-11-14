// SPDX-License-Identifier: LGPL-2.1-or-later

// Owners outside every Body (FreeCAD-CH ops#654 S2, notes/parts-design.md 10.1 "(b) on the build"
// and 10.9): which features run as owners, and the in-scope parts' shapes at an owner's place.

#include <string>
#include <vector>

#include <BRepExtrema_DistShapeShape.hxx>
#include <Precision.hxx>
#include <TopAbs_ShapeEnum.hxx>

#include <App/Document.h>
#include <App/PropertyLinks.h>
#include <Mod/Part/App/PartFeature.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureApply.h"
#include "Pieces.h"
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
    if (bases) {
        for (auto base : bases->getValues()) {
            if (base && part->hasObject(base)) {
                return freecad_cast<const Part::Feature*>(base);
            }
        }
        return nullptr;
    }
    // A shape owner has no bases of its own: its Add's steps hold them (ops#654 10.13)
    for (auto user : owner->getInList()) {
        auto step = freecad_cast<const Feature*>(user);
        if (!step || step->StudioOwner.getValue() != owner) {
            continue;
        }
        for (auto base : step->StudioBases.getValues()) {
            if (base && part->hasObject(base)) {
                return freecad_cast<const Part::Feature*>(base);
            }
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

std::string studioAddLeftover(const App::DocumentObject* owner)
{
    // Onshape H1a: such a solid is a new part, made by the command (P6p); until then E fails
    return unclaimedLeftovers(owner);
}

// FreeCAD-CH ops#654 P5: StudioList.cpp (declared where used)
PartDesignExport void studioBooleanParts(const App::DocumentObject* owner,
                                         std::vector<Body*>& steps,
                                         std::vector<Body*>& tools,
                                         std::vector<Body*>& both);
PartDesignExport Part::TopoShape studioBooleanTool(const App::DocumentObject* owner, std::string* why);

/// A Boolean studio feature's tool (P5): its tool parts' shapes at its place (studioBaseAt), fused
/// when there are several, in the document's frame, named with the owner's tag; null with why
Part::TopoShape studioBooleanTool(const App::DocumentObject* owner, std::string* why)
{
    auto fail = [why](const std::string& text) {
        if (why) {
            *why = text;
        }
        return Part::TopoShape();
    };
    std::vector<Body*> steps;
    std::vector<Body*> tools;
    std::vector<Body*> both;
    studioBooleanParts(owner, steps, tools, both);
    if (tools.empty()) {
        return fail("No tool part: the Boolean's tools are gone or consumed at its place");
    }
    std::vector<Part::TopoShape> shapes;
    for (auto tool : tools) {
        Part::TopoShape shape = studioBaseAt(owner, tool);
        if (shape.isNull()) {
            return fail(std::string("'") + tool->Label.getValue()
                        + "' has no solid before the Boolean");
        }
        shapes.push_back(shape);
    }
    if (shapes.size() == 1) {
        return shapes.front();
    }
    Part::TopoShape fused(owner->getID(), owner->getDocument()->getStringHasher());
    fused.makeElementFuse(shapes);
    return fused;
}

bool runsAsStudioOwner(const Feature* feature)
{
    // An instance outside every Body that the studio's list holds: it computes only its tool
    return feature && feature->isAttachedToDocument() && !feature->getFeatureBody()
        && isStudioOwner(feature);
}

}  // namespace PartDesign
