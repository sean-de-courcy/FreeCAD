// SPDX-License-Identifier: LGPL-2.1-or-later

// Owners outside every Body (FreeCAD-CH ops#654 S2, notes/parts-design.md 10.1 "(b) on the build"
// and 10.9): which features run as owners, and the in-scope parts' shapes at an owner's place.

#include <algorithm>
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
#include "Studio.h"
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

const Part::Feature* studioPartSolidBefore(const App::DocumentObject* owner, const Body* part)
{
    const StudioList* list = StudioList::holding(owner);
    if (!list || !part) {
        return nullptr;
    }
    const auto& entries = list->Entries.getValues();
    auto placeOf = [&entries](const App::DocumentObject* obj) {
        auto it = std::ranges::find(entries, obj);
        return it == entries.end() ? -1 : static_cast<int>(it - entries.begin());
    };
    const int at = placeOf(owner);
    if (at < 0) {
        return nullptr;
    }
    const Part::Feature* last = nullptr;
    int key = -1;
    for (App::DocumentObject* obj : part->Group.getValues()) {
        int here = placeOf(obj);
        if (here < 0) {
            if (auto feature = freecad_cast<Feature*>(obj)) {
                here = placeOf(feature->StudioOwner.getValue());
            }
        }
        if (here >= 0) {
            key = here;  // else the place of the member before it
        }
        if (key >= at || !Body::isSolidFeature(obj)) {
            continue;
        }
        auto feature = static_cast<const Part::Feature*>(obj);
        const Part::TopoShape& shape = feature->Shape.getShape();
        if (!shape.isNull() && shape.hasSubShape(TopAbs_SOLID)) {
            last = feature;  // a failed feature contributes nothing (parts-design 10.9)
        }
    }
    return last;
}

Part::TopoShape studioPartShapeAt(
    const App::DocumentObject* owner,
    const App::DocumentObject* linked,
    bool& isPart
)
{
    isPart = false;
    const StudioList* list = linked ? StudioList::holding(owner) : nullptr;
    if (!list || Body::findBodyOf(owner)) {
        return {};
    }
    auto body = freecad_cast<const Body*>(linked);
    if (!body && Body::isSolidFeature(linked)) {
        body = Body::findBodyOf(linked);
    }
    if (!body) {
        return {};
    }
    const auto bodies = studioBodies(owner->getDocument(), list->studio());
    if (std::ranges::find(bodies, body) == bodies.end()) {
        return {};
    }
    isPart = true;
    const Part::Feature* last = studioPartSolidBefore(owner, body);
    if (!last) {
        return {};
    }
    // With its Body's placement, as the Body's own shape has it, whichever of the two the link
    // names: reconcile writes the solid in place of the Body, and the result must not change
    Part::TopoShape shape = Part::Feature::getTopoShape(
        last,
        Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
    );
    shape.transformShape(body->Placement.getValue().toMatrix(), false, true);
    return shape;
}

bool studioWholePartLink(const App::Property* prop)
{
    const char* name = prop ? prop->getName() : nullptr;
    auto link = freecad_cast<const App::PropertyLinkBase*>(prop);
    // Of a reader outside every Body only (an owner): reconcile and the read at its place serve
    // no other
    auto reader = link ? freecad_cast<const App::DocumentObject*>(link->getContainer()) : nullptr;
    if (!name || !reader || Body::findBodyOf(reader)) {
        return false;
    }
    const std::string propName = name;
    if (propName != "UpToFace" && propName != "UpToFace2" && propName != "UpToShape"
        && propName != "UpToShape2") {
        return false;
    }
    std::vector<App::DocumentObject*> objs;
    std::vector<std::string> subs;
    link->getLinks(objs, /*all=*/true, &subs, /*newStyle=*/false);
    if (objs.empty() || !std::ranges::all_of(subs, &std::string::empty)) {
        return false;
    }
    return std::ranges::all_of(objs, [](const App::DocumentObject* obj) {
        return obj
            && (obj->isDerivedFrom<Body>() || (Body::isSolidFeature(obj) && Body::findBodyOf(obj)));
    });
}

void studioReleaseWholePartLinks(App::DocumentObject* step, Body* body)
{
    if (!step || !body) {
        return;
    }
    App::DocumentObject* before = body->getPrevSolidFeature(step);
    App::DocumentObject* target = before ? before : body;
    for (auto reader : step->getInList()) {
        if (!reader || Body::findBodyOf(reader)) {
            continue;
        }
        for (const char* name : {"UpToFace", "UpToFace2", "UpToShape", "UpToShape2"}) {
            App::Property* prop = reader->getPropertyByName(name);
            if (!studioWholePartLink(prop)) {
                continue;
            }
            if (auto one = freecad_cast<App::PropertyLinkSub*>(prop)) {
                if (one->getValue() == step) {
                    one->setValue(target, one->getSubValues());
                }
            }
            else if (auto many = freecad_cast<App::PropertyLinkSubList*>(prop)) {
                auto sets = many->getSubListValues();
                bool changed = false;
                for (auto& [obj, subs] : sets) {
                    if (obj == step) {
                        obj = target;
                        changed = true;
                    }
                }
                if (changed) {
                    many->setSubListValues(sets);
                }
            }
        }
    }
}

std::string studioLinkAhead(const Feature* owner)
{
    if (!runsAsStudioOwner(owner)) {
        return {};
    }
    std::vector<App::Property*> props;
    owner->getPropertyList(props);
    for (auto prop : props) {
        auto link = freecad_cast<App::PropertyLinkBase*>(prop);
        const char* name = prop->getName();
        if (!link || !name || link->getScope() == App::LinkScope::Hidden) {
            continue;
        }
        std::vector<App::DocumentObject*> linked;
        link->getLinks(linked, /*all=*/true);
        for (auto obj : linked) {
            if (!obj) {
                continue;
            }
            auto body = freecad_cast<const Body*>(obj);
            const bool whole = body != nullptr;
            if (!body && Body::isSolidFeature(obj)) {
                body = Body::findBodyOf(obj);
            }
            const Feature* step = body ? StudioList::stepOf(owner, body) : nullptr;
            if (!step) {
                continue;  // a part it doesn't change: no cycle through a step
            }
            const std::string head = std::string(name) + " links '" + obj->Label.getValue() + "', ";
            const std::string tail = ": link a feature of the part from before this one (the "
                                     "link is a dependency loop, and results would come one "
                                     "recompute late)";
            if (whole) {
                return head + "the part this feature changes" + tail;
            }
            if (obj == step) {
                return head + "this feature's own step in '" + body->Label.getValue() + "'" + tail;
            }
            const auto& group = body->Group.getValues();
            if (std::find(group.begin(), group.end(), obj)
                > std::find(group.begin(), group.end(), static_cast<const App::DocumentObject*>(step))) {
                return head + "a feature of '" + body->Label.getValue() + "' after this one" + tail;
            }
        }
    }
    return {};
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
