// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2013 Jan Rheinländer <jrheinlaender@users.sourceforge.net> *
 *                                                                            *
 *   This file is part of the FreeCAD CAx development system.                 *
 *                                                                            *
 *   This library is free software; you can redistribute it and/or            *
 *   modify it under the terms of the GNU Library General Public              *
 *   License as published by the Free Software Foundation; either             *
 *   version 2 of the License, or (at your option) any later version.         *
 *                                                                            *
 *   This library  is distributed in the hope that it will be useful,         *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of           *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            *
 *   GNU Library General Public License for more details.                     *
 *                                                                            *
 *   You should have received a copy of the GNU Library General Public        *
 *   License along with this library; see the file COPYING.LIB. If not,       *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,            *
 *   Suite 330, Boston, MA  02111-1307, USA                                   *
 *                                                                            *
 ******************************************************************************/


#include <Mod/Part/App/FCBRepAlgoAPI_Common.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Cut.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <Standard_Failure.hxx>

#include <algorithm>

#include <Precision.hxx>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/PropertyLinks.h>
#include <Base/Tools.h>
#include <Mod/Part/App/modelRefine.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "FeatureBoolean.h"
#include "Body.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true);

using namespace PartDesign;

namespace PartDesign
{
extern bool getPDRefineModelParameter();

PROPERTY_SOURCE_WITH_EXTENSIONS(PartDesign::Boolean, PartDesign::FeatureRefine)

const char* Boolean::TypeEnums[] = {"Fuse", "Cut", "Common", nullptr};

Boolean::Boolean()
{
    ADD_PROPERTY(Type, ((long)0));
    Type.setEnums(TypeEnums);
    ADD_PROPERTY_TYPE(
        UseLegacyBodyPlacement,
        (App::GetApplication().isRestoring()),
        "Compatibility",
        App::Prop_Hidden,
        "Use legacy PartDesign Boolean body placement handling"
    );

    App::GeoFeatureGroupExtension::initExtension(this);
    // Boolean tools are references, not owned coordinate-system children.
    Group.setScope(App::LinkScope::Global);
}

namespace
{
// A Merge's saved toolFrames() from its last compute (FreeCAD-CH ops#325, PR 305 round 1)
constexpr const char* mergeFrames = "MergeFrames";
}  // namespace

short Boolean::mustExecute() const
{
    if (Group.isTouched() || UseLegacyBodyPlacement.isTouched()) {
        return 1;
    }
    // A merged part moved: nothing it links changed, and the Body isn't linked (FreeCAD-CH
    // ops#325, M-t6)
    if (isMerge()) {
        const std::vector<Base::Placement> frames = toolFrames();
        if (frames.size() != lastToolFrames.size()
            || !std::ranges::equal(frames, lastToolFrames, [](const auto& one, const auto& other) {
                   return one.isSame(other, Precision::Confusion());
               })) {
            return 1;
        }
    }
    return PartDesign::Feature::mustExecute();
}

TopoShape Boolean::getBooleanTopoShape(const App::DocumentObject* object) const
{
    if (UseLegacyBodyPlacement.getValue()) {
        return getTopoShape(object, Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform);
    }
    return getTopoShapeInLocalCoordinates(object);
}

std::vector<App::DocumentObject*> Boolean::addObject(App::DocumentObject* object)
{
    return addObjects({object});
}

std::vector<App::DocumentObject*> Boolean::addObjects(std::vector<App::DocumentObject*> objects)
{
    auto tools = Group.getValues();
    std::vector<App::DocumentObject*> added;

    for (auto object : objects) {
        if (!object || std::ranges::find(tools, object) != tools.end()) {
            continue;
        }

        tools.push_back(object);
        added.push_back(object);
    }

    Base::ObjectStatusLocker<App::Property::Status, App::Property> guard(App::Property::User3, &Group);
    Group.setValues(tools);
    return added;
}

std::vector<App::DocumentObject*> Boolean::setObjects(std::vector<App::DocumentObject*> objects)
{
    std::vector<App::DocumentObject*> tools;
    std::vector<App::DocumentObject*> added;

    for (auto object : objects) {
        if (!object || std::ranges::find(tools, object) != tools.end()) {
            continue;
        }

        tools.push_back(object);
        added.push_back(object);
    }

    Base::ObjectStatusLocker<App::Property::Status, App::Property> guard(App::Property::User3, &Group);
    Group.setValues(tools);
    return added;
}

std::vector<App::DocumentObject*> Boolean::removeObject(App::DocumentObject* object)
{
    return removeObjects({object});
}

std::vector<App::DocumentObject*> Boolean::removeObjects(std::vector<App::DocumentObject*> objects)
{
    auto tools = Group.getValues();
    std::vector<App::DocumentObject*> removed;

    for (auto object : objects) {
        auto it = std::ranges::find(tools, object);
        if (it == tools.end()) {
            continue;
        }

        removed.push_back(object);
        tools.erase(it);
    }

    Base::ObjectStatusLocker<App::Property::Status, App::Property> guard(App::Property::User3, &Group);
    Group.setValues(tools);
    return removed;
}

bool Boolean::hasObject(const App::DocumentObject* /*object*/, bool /*recursive*/) const
{
    // Boolean tools are references, not owned children. Returning false keeps
    // GeoFeatureGroupExtension from using this object as their coordinate system.
    return false;
}

App::DocumentObjectExecReturn* Boolean::execute()
{
    // Get the operation type
    std::string type = Type.getValueAsString();

    // Check the parameters
    const Part::Feature* baseFeature = this->getBaseObject(/* silent = */ true);

    if (!baseFeature && type == "Cut") {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Cannot do boolean cut without BaseFeature")
        );
    }

    // A Merge's tools are its absorbed parts' merged features (FreeCAD-CH ops#325)
    if (isMerge()) {
        lastToolFrames = toolFrames();
        auto saved = freecad_cast<App::PropertyPlacementList*>(getPropertyByName(mergeFrames));
        if (saved && saved->getValues() != lastToolFrames) {
            saved->setValues(lastToolFrames);
        }
        if (std::string why = mergeProblem(); !why.empty()) {
            return new App::DocumentObjectExecReturn(why, this);
        }
    }

    std::vector<App::DocumentObject*> tools = Group.getValues();
    if (tools.empty()) {
        // Being set up: before its first tool (its command runs it once before the panel opens)
        // or in its panel. Otherwise its tools are gone (e.g. the tool Body was deleted), and
        // keeping the old result would show them silently (FreeCAD-CH ops#314); failing passes
        // the base shape through (ops#126)
        if (settingUp || Shape.getShape().isNull()) {
            return App::DocumentObject::StdReturn;
        }
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Boolean has no tools: add a Body to its list")
        );
    }

    // Get the base shape to operate on
    Part::TopoShape baseTopShape = makeTopoShape(false);
    if (baseFeature) {
        if (UseLegacyBodyPlacement.getValue()) {
            baseTopShape = baseFeature->Shape.getShape();
        }
        else {
            baseTopShape = getBooleanTopoShape(baseFeature);
        }
    }
    else {
        auto feature = tools.back();
        if (!feature->isDerivedFrom<Part::Feature>()) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Cannot do boolean with anything but Part::Feature and its derivatives"
            ));
        }

        if (UseLegacyBodyPlacement.getValue()) {
            baseTopShape = static_cast<Part::Feature*>(feature)->Shape.getShape();
        }
        else {
            baseTopShape = getBooleanTopoShape(feature);
        }
        tools.pop_back();
    }

    if (baseTopShape.getShape().IsNull()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Cannot do boolean operation with invalid base shape")
        );
    }

    std::vector<TopoShape> shapes;
    shapes.push_back(baseTopShape);
    for (auto it = tools.begin(); it < tools.end(); ++it) {
        auto shape = getBooleanTopoShape(*it);
        if (shape.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Tool shape is null")
            );
        }
        shapes.push_back(shape);
    }
    TopoShape result(baseTopShape);

    if (!tools.empty()) {
        const char* op = nullptr;

        if (type == "Fuse") {
            op = Part::OpCodes::Fuse;
        }
        else if (type == "Cut") {
            op = Part::OpCodes::Cut;
        }
        else if (type == "Common") {
            op = Part::OpCodes::Common;
        }
        // LinkStage3 defines these other types of Boolean operations.  Removed for now pending
        // decision to bring them in or not.
        // else if(type == "Compound")
        //     op = Part::OpCodes::Compound;
        // else if(type == "Section")
        //     op = Part::OpCodes::Section;
        else {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Unsupported boolean operation")
            );
        }

        try {
            result = makeResultShape(baseTopShape)
                         .makeElementBoolean(op, shapes, nullptr, FuzzyTolerance.getValue());
        }
        catch (Standard_Failure& e) {
            FC_ERR("Boolean operation failed: " << e.GetMessageString());
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Boolean operation failed")
            );
        }
    }

    result = refineShapeIfActive(result);

    if (!isSingleSolidRuleSatisfied(result.getShape())) {
        return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
            "Exception",
            "Result has multiple solids: enable 'Allow Compound' in the active body."
        ));
    }

    this->Shape.setValue(getSolid(result));
    warnMerged();

    return StdReturn;
}

void Boolean::updatePreviewShape()
{
    if (strcmp(Type.getValueAsString(), "Cut") == 0) {
        TopoShape base;
        if (UseLegacyBodyPlacement.getValue()) {
            base = getBaseTopoShape(true);
            base.move(getInverseLocation(base));
        }
        else {
            base = getBooleanTopoShape(BaseFeature.getValue());
        }
        TopoShape result = Shape.getShape();

        try {
            PreviewShape.setValue(base.makeElementCut(result.getShape()));
        }
        catch (Standard_Failure& e) {
            FC_ERR("Boolean preview failed: " << e.GetMessageString());
            PreviewShape.setValue(base);
        }
        catch (Base::Exception& e) {
            FC_ERR("Boolean preview failed: " << e.what());
            PreviewShape.setValue(base);
        }
        return;
    }

    if (strcmp(Type.getValueAsString(), "Fuse") == 0) {
        // if there are no other shapes to fuse just return itself
        if (Group.getValues().empty()) {
            PreviewShape.setValue(Shape.getShape());
            return;
        }

        std::vector<TopoShape> shapes;

        for (auto& obj : Group.getValues()) {
            shapes.push_back(getBooleanTopoShape(obj));
        }

        TopoShape result = makeTopoShape(false);
        result.makeCompound(shapes);

        PreviewShape.setValue(result.getShape());
        return;
    }

    PreviewShape.setValue(Shape.getShape());
}

void Boolean::onChanged(const App::Property* prop)
{

    if (strcmp(prop->getName(), "Group") == 0) {
        touch();
    }
    // The merge warning goes, or comes back, with the next compute (FreeCAD-CH ops#325)
    else if (strcmp(prop->getName(), "MergeAccepted") == 0 && !isRestoring()) {
        touch();
    }

    Feature::onChanged(prop);
}

void Boolean::handleChangedPropertyName(Base::XMLReader& reader, const char* TypeName, const char* PropName)
{
    // The App::PropertyLinkList property was Bodies in the past
    Base::Type type = Base::Type::fromName(TypeName);

    if (Group.getClassTypeId() == type && strcmp(PropName, "Bodies") == 0) {
        Group.Restore(reader);
    }
}

// ------------------------------------------------------------------------------------------------
// Merge (FreeCAD-CH ops#325, B+ Stage 1 3b)

namespace
{
constexpr const char* mergedInto = "MergedInto";
constexpr const char* mergeAccepted = "MergeAccepted";

std::string label(const App::DocumentObject* obj)
{
    return obj ? obj->Label.getValue() : "None";
}

// The last solid feature of `body` up to its Tip, or null
App::DocumentObject* lastSolid(Body* body)
{
    const std::vector<App::DocumentObject*> group = body->Group.getValues();
    auto end = std::ranges::find(group, body->Tip.getValue());
    if (end == group.end()) {
        return nullptr;
    }
    for (auto it = std::make_reverse_iterator(end + 1); it != group.rend(); ++it) {
        if (Body::isSolidFeature(*it)) {
            return *it;
        }
    }
    return nullptr;
}

std::string labels(const std::vector<App::DocumentObject*>& objects)
{
    std::string text;
    for (auto obj : objects) {
        text += (text.empty() ? "" : ", ") + label(obj);
    }
    return text;
}
}  // namespace

bool Boolean::isMerge() const
{
    return getPropertyByName(mergeAccepted) != nullptr;
}

Boolean* Boolean::mergeOf(const App::DocumentObject* body)
{
    auto link = body ? freecad_cast<App::PropertyLinkHidden*>(body->getPropertyByName(mergedInto))
                     : nullptr;
    auto merge = link ? freecad_cast<Boolean*>(link->getValue()) : nullptr;
    // A Merge left in no part (its Body deleted alone) merges nothing (PR 305 round 1)
    return merge && merge->isMerge() && Body::findBodyOf(merge) ? merge : nullptr;
}

std::vector<App::DocumentObject*> Boolean::mergedBodies() const
{
    std::vector<App::DocumentObject*> bodies;
    if (App::Document* doc = getDocument()) {
        for (auto obj : doc->getObjectsOfType(Body::getClassTypeId())) {
            if (mergeOf(obj) == this) {
                bodies.push_back(obj);
            }
        }
    }
    return bodies;
}

Boolean* Boolean::makeMerge(App::DocumentObject* at, const std::vector<App::DocumentObject*>& bodies)
{
    auto survivor = freecad_cast<Body*>(at);
    App::DocumentObject* after = nullptr;
    if (survivor) {
        after = lastSolid(survivor);
    }
    else if ((survivor = Body::findBodyOf(at)) && Body::isSolidFeature(at)) {
        after = at;
    }
    if (!survivor || !after) {
        throw Base::ValueError(
            "Merge: " + label(at) + " is neither a solid feature in a part nor a part with a solid"
        );
    }
    if (Boolean* merge = mergeOf(survivor)) {
        throw Base::ValueError(
            "Merge: " + label(survivor) + " is merged into " + label(Body::findBodyOf(merge))
            + "; merge into that part"
        );
    }
    std::vector<Body*> absorbed;
    std::vector<App::DocumentObject*> tools;
    for (auto obj : bodies) {
        auto body = freecad_cast<Body*>(obj);
        if (!body) {
            throw Base::ValueError("Merge: " + label(obj) + " isn't a part");
        }
        if (std::ranges::find(absorbed, body) != absorbed.end()) {
            continue;
        }
        if (body == survivor) {
            throw Base::ValueError("Merge: " + label(body) + " can't merge into itself");
        }
        if (!Part::BodyBase::areStudioSiblings(survivor, body)) {
            throw Base::ValueError(
                "Merge: " + label(body) + " isn't a part of " + label(survivor)
                + "'s studio (one container, placed alike)"
            );
        }
        if (Boolean* merge = mergeOf(body)) {
            throw Base::ValueError(
                "Merge: " + label(body) + " is merged into "
                + label(Body::findBodyOf(merge)) + " already"
            );
        }
        // A held feature would merge a frozen shape (design 2.6)
        if (body->isRolledBack()) {
            throw Base::ValueError("Merge: Roll " + label(body) + " to the end first");
        }
        App::DocumentObject* merged = lastSolid(body);
        if (!merged) {
            throw Base::ValueError("Merge: " + label(body) + " has no solid to merge");
        }
        absorbed.push_back(body);
        tools.push_back(merged);
    }
    if (absorbed.empty()) {
        throw Base::ValueError("Merge: no part to merge");
    }
    // A merged feature that depends on a feature the Merge will feed would be a cycle (the
    // design's critic, point 11): refused, naming the dependency
    const std::vector<App::DocumentObject*> group = survivor->Group.getValues();
    std::vector<App::DocumentObject*> later(std::ranges::find(group, after) + 1, group.end());
    for (auto merged : tools) {
        const std::vector<App::DocumentObject*> closure = merged->getOutListRecursive();
        std::vector<App::DocumentObject*> found;
        std::ranges::copy_if(later, std::back_inserter(found), [&closure](auto obj) {
            return std::ranges::find(closure, obj) != closure.end();
        });
        if (found.empty()) {
            continue;
        }
        // The first solid it depends on names it best (its sketch comes before it)
        auto solid = std::ranges::find_if(found, [](auto obj) { return Body::isSolidFeature(obj); });
        App::DocumentObject* dependency = solid != found.end() ? *solid : found.front();
        throw Base::ValueError(
            "Merge: " + label(merged) + " depends on " + label(dependency)
            + ", which comes after the Merge in " + label(survivor) + "; merge after "
            + label(dependency) + ", or change " + label(merged)
        );
    }

    App::Document* doc = survivor->getDocument();
    const bool atTip = survivor->Tip.getValue() == after;
    auto merge = static_cast<Boolean*>(doc->addObject("PartDesign::Boolean", "Merge"));
    merge->Label.setValue("Merge");
    survivor->insertObject(merge, after, /*after=*/true);
    if (atTip) {
        survivor->Tip.setValue(merge);
    }
    merge->Type.setValue("Fuse");
    auto accepted = static_cast<App::PropertyBool*>(merge->addDynamicProperty(
        "App::PropertyBool",
        mergeAccepted,
        "Merge",
        "Whether the merge was accepted: until then it warns",
        App::Prop_Hidden
    ));
    accepted->setValue(false);
    merge->addDynamicProperty(
        "App::PropertyPlacementList",
        mergeFrames,
        "Merge",
        "Where the merged parts were, in this part's frame, when the Merge last computed",
        App::Prop_Output | App::Prop_Hidden
    );
    merge->setObjects(tools);
    for (Body* body : absorbed) {
        auto link = freecad_cast<App::PropertyLinkHidden*>(body->getPropertyByName(mergedInto));
        if (!link) {
            link = static_cast<App::PropertyLinkHidden*>(body->addDynamicProperty(
                "App::PropertyLinkHidden",
                mergedInto,
                "Merge",
                "The Merge this part is merged into",
                App::Prop_Hidden
            ));
        }
        link->setValue(merge);
        body->Visibility.setValue(false);
    }
    return merge;
}

std::string Boolean::mergeProblem() const
{
    const std::vector<App::DocumentObject*> bodies = mergedBodies();
    const std::vector<App::DocumentObject*> tools = Group.getValues();
    const std::string fix = "; re-pick the part, or delete the Merge";
    // No tools while the part is still here (its merged feature deleted) is said below: nothing
    // of it is merged (PR 305 round 1)
    if (bodies.empty()) {
        return label(this) + ": the merged part is gone" + fix;
    }
    for (auto tool : tools) {
        if (mergeOf(Body::findBodyOf(tool)) != this) {
            return label(this) + ": the merged part changed, " + label(tool)
                + " isn't in a part merged here" + fix;
        }
    }
    for (auto body : bodies) {
        if (std::ranges::none_of(tools, [body](auto tool) {
                return Body::findBodyOf(tool) == body;
            })) {
            return label(this) + ": the merged part changed, nothing of " + label(body)
                + " is merged" + fix;
        }
    }
    return {};
}

std::vector<Base::Placement> Boolean::toolFrames() const
{
    std::vector<Base::Placement> frames;
    Body* own = Body::findBodyOf(this);
    const Base::Placement here = own ? own->globalPlacement() : Base::Placement();
    for (auto tool : Group.getValues()) {
        Body* body = Body::findBodyOf(tool);
        frames.push_back(here.inverse() * (body ? body->globalPlacement() : Base::Placement()));
    }
    return frames;
}

void Boolean::onDocumentRestored()
{
    // The frames it last computed with, as saved: a Merge saved stale (its part moved after it
    // ran) runs on the next recompute. One saved without them runs once (PR 305 round 1)
    if (auto saved = freecad_cast<App::PropertyPlacementList*>(getPropertyByName(mergeFrames))) {
        lastToolFrames = saved->getValues();
    }
    FeatureRefine::onDocumentRestored();
}

void Boolean::warnMerged()
{
    auto accepted = freecad_cast<App::PropertyBool*>(getPropertyByName(mergeAccepted));
    App::Document* doc = getDocument();
    if (!accepted || accepted->getValue() || !doc) {
        return;
    }
    const std::string text = "Merged " + labels(mergedBodies()) + " into "
        + label(Body::findBodyOf(this));
    const char* previous = doc->getWarningDescription(this);
    doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + text : text);
}

std::string Boolean::mergeLock(const App::DocumentObject* feature)
{
    Body* body = Body::findBodyOf(feature);
    Boolean* merge = body && Body::isSolidFeature(feature) ? mergeOf(body) : nullptr;
    if (!merge) {
        return {};
    }
    const std::vector<App::DocumentObject*> group = body->Group.getValues();
    const auto here = std::ranges::find(group, feature);
    for (auto merged : merge->Group.getValues()) {
        const auto there = std::ranges::find(group, merged);
        if (there != group.end() && here != group.end() && here > there) {
            return label(body) + " is merged into " + label(Body::findBodyOf(merge)) + " at "
                + label(merged) + "; this feature doesn't reach the merge. Move it before "
                + label(merged) + ", or delete the Merge";
        }
    }
    return {};
}

}  // namespace PartDesign
