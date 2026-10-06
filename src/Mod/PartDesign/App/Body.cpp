// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2010 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/


#include <algorithm>
#include <functional>
#include <map>

#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/VarSet.h>
#include <App/Origin.h>
#include <Base/Placement.h>

#include "Body.h"
#include "BodyPy.h"
#include "FeatureBase.h"
#include "FeatureSketchBased.h"
#include "FeatureSolid.h"
#include "FeatureTransformed.h"
#include "Retarget.h"
#include "ShapeBinder.h"

using namespace PartDesign;


PROPERTY_SOURCE(PartDesign::Body, Part::BodyBase)

Body::Body()
{
    BaseFeature.setScope(App::LinkScope::Global);
    ADD_PROPERTY_TYPE(AllowCompound, (true), "Base", App::Prop_None, "Allow multiple solids in Body");

    _GroupTouched.setStatus(App::Property::Output, true);
    // The roll-back bar is the Tip: moving it doesn't touch the Body (ops#127, R7); onChanged()
    // enforces a recompute only when the Body isn't rolled back and the Tip's shape is new
    Tip.setStatus(App::Property::Output, true);
}

/*
// Note: The following code will catch Python Document::removeObject() modifications. If the object
removed is
// a member of the Body::Group, then it will be automatically removed from the Group property which
triggers the
// following two methods
// But since we require the Python user to call both Document::addObject() and Body::addObject(), we
should
// also require calling both Document::removeObject and Body::removeFeature() in order to be
consistent void Body::onBeforeChange(const App::Property *prop)
{
    // Remember the feature before the current Tip. If the Tip is already at the first feature,
remember the next feature if (prop == &Group) { std::vector<App::DocumentObject*> features =
Group.getValues(); if (features.empty()) { rememberTip = NULL; } else {
            std::vector<App::DocumentObject*>::iterator it = std::find(features.begin(),
features.end(), Tip.getValue()); if (it == features.begin()) { it++; if (it == features.end())
rememberTip = NULL; else rememberTip = *it; } else { it--; rememberTip = *it;
            }
        }
    }

    return Part::Feature::onBeforeChange(prop);
}

void Body::onChanged(const App::Property *prop)
{
    if (prop == &Group) {
        std::vector<App::DocumentObject*> features = Group.getValues();
        if (features.empty()) {
            Tip.setValue(NULL);
        } else {
            std::vector<App::DocumentObject*>::iterator it = std::find(features.begin(),
features.end(), Tip.getValue()); if (it == features.end()) {
                // Tip feature was deleted
                Tip.setValue(rememberTip);
            }
        }
    }

    return Part::Feature::onChanged(prop);
}
*/

short Body::mustExecute() const
{
    // Not on a Tip change alone (ops#127, R7): see onChanged()
    return Part::BodyBase::mustExecute();
}

namespace
{
/// The shape a Body copied from its Tip is the Tip's current one: the same TopoDS shape (TShape,
/// location, orientation), tag and hasher (TopoShape::isSame), and an element map of the same size
/// (the map itself isn't public; a recompute that renames makes a new TShape anyway) (ops#127, R7)
bool sameTipShape(const Part::TopoShape& a, const Part::TopoShape& b)
{
    return a.isSame(b) && a.getElementMapSize(false) == b.getElementMapSize(false);
}

/// The Tip's current shape, before the Body's placement bake
Part::TopoShape tipShapeOf(const App::DocumentObject* tip)
{
    auto feature = freecad_cast<const Part::Feature*>(tip);
    return feature ? feature->Shape.getShape() : Part::TopoShape();
}
}  // namespace

// The roll-back bar (ops#127, notes/reorder-rollback-design.md section 1)

App::DocumentObject* Body::getEditRollPoint() const
{
    return editRollPoint && hasObject(editRollPoint) ? editRollPoint : nullptr;
}

void Body::setEditRollPoint(App::DocumentObject* obj)
{
    editRollPoint = obj;
}

App::DocumentObject* Body::effectiveBar() const
{
    if (auto point = getEditRollPoint()) {
        return point;
    }
    return Tip.getValue();
}

App::DocumentObject* Body::lastSolidFeature() const
{
    const auto& features = Group.getValues();
    auto it = std::find_if(features.rbegin(), features.rend(), isSolidFeature);
    return it == features.rend() ? nullptr : *it;
}

bool Body::isRolledBack() const
{
    auto last = lastSolidFeature();
    return last && effectiveBar() != last;
}

namespace
{
/// The position in features of the first solid feature after the bar (features.size() if none);
/// the bar null means the top
std::size_t firstHeldSolid(const std::vector<App::DocumentObject*>& features,
                           const App::DocumentObject* bar)
{
    std::size_t start = 0;
    if (bar) {
        auto it = std::find(features.begin(), features.end(), bar);
        if (it == features.end()) {
            // A bar outside the Group (a stale Tip) holds nothing
            return features.size();
        }
        start = static_cast<std::size_t>(it - features.begin()) + 1;
    }
    for (std::size_t i = start; i < features.size(); ++i) {
        if (Body::isSolidFeature(features[i])) {
            return i;
        }
    }
    return features.size();
}
}  // namespace

bool Body::holds(const App::DocumentObject* obj) const
{
    if (!obj) {
        return false;
    }
    if (obj == this) {
        return isRolledBack();
    }
    if (!isRolledBack()) {
        return false;
    }
    const auto& features = Group.getValues();
    std::size_t firstHeld = firstHeldSolid(features, effectiveBar());
    if (firstHeld >= features.size()) {
        return false;
    }
    std::map<const App::DocumentObject*, std::size_t> position;
    for (std::size_t i = 0; i < features.size(); ++i) {
        position.emplace(features[i], i);
    }
    // Memo per call: 1 held, 0 not, absent unknown; the graph is acyclic
    std::map<const App::DocumentObject*, bool> memo;
    std::function<bool(const App::DocumentObject*)> held = [&](const App::DocumentObject* o) {
        auto known = memo.find(o);
        if (known != memo.end()) {
            return known->second;
        }
        auto pos = position.find(o);
        bool result = false;
        if (pos != position.end() && pos->second >= firstHeld) {
            if (isSolidFeature(o)) {
                result = true;
            }
            else {
                // B1: held only when every member that uses it is held
                memo[o] = true;  // a cycle (shouldn't exist) counts as held
                result = true;
                for (auto user : o->getInList()) {
                    if (user == this || !position.count(user)) {
                        continue;
                    }
                    if (!held(user)) {
                        result = false;
                        break;
                    }
                }
            }
        }
        memo[o] = result;
        return result;
    };
    return held(obj);
}

void Body::rollTo(App::DocumentObject* feature)
{
    if (feature && (!hasObject(feature) || !isSolidFeature(feature))) {
        throw Base::ValueError("Body: the roll-back bar goes after a solid feature of this body");
    }
    if (!feature) {
        // The top: after the base feature, if there is one (nothing goes before it)
        const auto& features = Group.getValues();
        if (!features.empty() && features.front()->isDerivedFrom<FeatureBase>()) {
            feature = features.front();
        }
    }
    if (Tip.getValue() != feature) {
        Tip.setValue(feature);
    }
}

void Body::rollToEnd()
{
    auto last = lastSolidFeature();
    if (Tip.getValue() != last) {
        Tip.setValue(last);
    }
}

void Body::rerouteBase(App::DocumentObject* feature, App::DocumentObject* newBase)
{
    auto pd = freecad_cast<PartDesign::Feature*>(feature);
    if (!pd) {
        return;
    }
    App::DocumentObject* oldBase = pd->BaseFeature.getValue();
    if (oldBase == newBase) {
        return;
    }
    pd->BaseFeature.setValue(newBase);
    pd->onBaseFeatureRerouted(oldBase, newBase);
}

App::DocumentObject* Body::getPrevSolidFeature(App::DocumentObject* start)
{
    if (!start) {  // default to tip
        start = Tip.getValue();
    }

    if (!start) {  // No Tip
        return nullptr;
    }

    if (!hasObject(start)) {
        return nullptr;
    }

    const std::vector<App::DocumentObject*>& features = Group.getValues();

    auto startIt = std::find(features.rbegin(), features.rend(), start);
    if (startIt == features.rend()) {  // object not found
        return nullptr;
    }

    auto rvIt = std::find_if(startIt + 1, features.rend(), isSolidFeature);
    if (rvIt != features.rend()) {  // the solid found in model list
        return *rvIt;
    }
    return nullptr;
}

App::DocumentObject* Body::getNextSolidFeature(App::DocumentObject* start)
{
    if (!start) {  // default to tip
        start = Tip.getValue();
    }

    if (!start || !hasObject(start)) {  // no or faulty tip
        return nullptr;
    }

    const std::vector<App::DocumentObject*>& features = Group.getValues();
    std::vector<App::DocumentObject*>::const_iterator startIt;

    startIt = std::find(features.begin(), features.end(), start);
    if (startIt == features.end()) {  // object not found
        return nullptr;
    }

    startIt++;
    if (startIt == features.end()) {  // features list has only one element
        return nullptr;
    }

    auto rvIt = std::find_if(startIt, features.end(), isSolidFeature);
    if (rvIt != features.end()) {  // the solid found in model list
        return *rvIt;
    }
    return nullptr;
}

bool Body::isAfterInsertPoint(App::DocumentObject* feature)
{
    App::DocumentObject* nextSolid = getNextSolidFeature();
    assert(feature);
    if (!Tip.getValue()) {
        // The bar at the top (ops#127): every solid is after it
        const auto& features = Group.getValues();
        auto it = std::find_if(features.begin(), features.end(), isSolidFeature);
        nextSolid = it == features.end() ? nullptr : *it;
    }

    if (feature == nextSolid) {
        return true;
    }
    else if (!nextSolid) {  // the tip is last solid, we can't be placed after it
        return false;
    }
    else {
        return isAfter(feature, nextSolid);
    }
}

bool Body::isSolidFeature(const App::DocumentObject* obj)
{
    if (!obj) {
        return false;
    }

    if (obj->isDerivedFrom<PartDesign::Feature>()) {
        if (PartDesign::Feature::isDatum(obj)) {
            // Datum objects are not solid
            return false;
        }
        if (auto transFeature = freecad_cast<PartDesign::Transformed*>(obj)) {
            // Transformed Features inside a MultiTransform are not solid features
            return !transFeature->isMultiTransformChild();
        }
        return true;
    }
    return false;  // DeepSOIC: work-in-progress?
}

bool Body::isAllowed(const App::DocumentObject* obj)
{
    if (!obj) {
        return false;
    }

    // TODO: Should we introduce a PartDesign::FeaturePython class? This should then also return
    // true for isSolidFeature()
    return (
        obj->isDerivedFrom<PartDesign::Feature>() || obj->isDerivedFrom<Part::Datum>() ||
        // TODO Shouldn't we replace it with Sketcher::SketchObject? (2015-08-13, Fat-Zer)
        obj->isDerivedFrom<Part::Part2DObject>() || obj->isDerivedFrom<PartDesign::ShapeBinder>()
        || obj->isDerivedFrom<PartDesign::SubShapeBinder>() ||
        // TODO Why this lines was here? why should we allow anything of those? (2015-08-13,
        // Fat-Zer) obj->isDerivedFrom<Part::FeaturePython>() // trouble with this line on Windows!?
        // Linker fails to find getClassTypeId() of the Part::FeaturePython...
        // obj->isDerivedFrom<Part::Feature>()
        // allow VarSets for parameterization
        obj->isDerivedFrom<App::VarSet>() || obj->isDerivedFrom<App::DatumElement>()
        || obj->isDerivedFrom<App::LocalCoordinateSystem>()
    );
}


Body* Body::findBodyOf(const App::DocumentObject* feature)
{
    if (!feature) {
        return nullptr;
    }

    return static_cast<Body*>(BodyBase::findBodyOf(feature));
}


std::vector<App::DocumentObject*> Body::addObject(App::DocumentObject* feature)
{
    if (!isAllowed(feature)) {
        throw Base::ValueError("Body: object is not allowed");
    }

    // TODO: features should not add all links

    // only one group per object. If it is in a body the single feature will be removed
    auto* group = App::GroupExtension::getGroupOfObject(feature);
    if (group && group != getExtendedObject()) {
        group->getExtensionByType<GroupExtension>()->removeObject(feature);
    }


    App::DocumentObject* next = nullptr;
    if (Tip.getValue()) {
        next = getNextSolidFeature();
    }
    else {
        // The bar at the top (ops#127): before the first solid feature
        const auto& features = Group.getValues();
        auto it = std::find_if(features.begin(), features.end(), isSolidFeature);
        next = it == features.end() ? nullptr : *it;
    }
    insertObject(feature, next, /*after = */ false);
    // Move the Tip if we added a solid
    if (isSolidFeature(feature)) {
        Tip.setValue(feature);
    }

    if (feature->Visibility.getValue() && feature->isDerivedFrom<PartDesign::Feature>()) {
        for (auto obj : Group.getValues()) {
            if (obj->Visibility.getValue() && obj != feature
                && obj->isDerivedFrom<PartDesign::Feature>()) {
                obj->Visibility.setValue(false);
            }
        }
    }

    std::vector<App::DocumentObject*> result = {feature};
    return result;
}

std::vector<App::DocumentObject*> Body::addObjects(std::vector<App::DocumentObject*> objs)
{

    for (auto obj : objs) {
        addObject(obj);
    }

    return objs;
}


void Body::insertObject(App::DocumentObject* feature, App::DocumentObject* target, bool after)
{
    if (target && !hasObject(target)) {
        throw Base::ValueError(
            "Body: the feature we should insert relative to is not part of that body"
        );
    }

    // ensure that all origin links are ok
    relinkToOrigin(feature);

    std::vector<App::DocumentObject*> model = Group.getValues();
    std::vector<App::DocumentObject*>::iterator insertInto;

    // Find out the position there to insert the feature
    if (!target) {
        if (after) {
            insertInto = model.begin();
        }
        else {
            insertInto = model.end();
        }
    }
    else {
        std::vector<App::DocumentObject*>::iterator targetIt
            = std::find(model.begin(), model.end(), target);
        assert(targetIt != model.end());
        if (after) {
            insertInto = targetIt + 1;
        }
        else {
            insertInto = targetIt;
        }
    }

    // Insert the new feature after the given
    model.insert(insertInto, feature);

    Group.setValues(model);

    if (feature->isDerivedFrom<PartDesign::Feature>()) {
        static_cast<PartDesign::Feature*>(feature)->_Body.setValue(this);
    }

    // Set the BaseFeature property
    setBaseProperty(feature);
}

void Body::setBaseProperty(App::DocumentObject* feature)
{
    if (Body::isSolidFeature(feature)) {
        // Set BaseFeature property to previous feature (this might be the Tip feature)
        App::DocumentObject* prevSolidFeature = getPrevSolidFeature(feature);
        // NULL is ok here, it just means we made the current one fiature the base solid
        rerouteBase(feature, prevSolidFeature);

        // Reroute the next solid feature's BaseFeature property to this feature, with the
        // references that follow its base (ops#127: insert at the bar)
        App::DocumentObject* nextSolidFeature = getNextSolidFeature(feature);
        if (nextSolidFeature) {
            assert(nextSolidFeature->isDerivedFrom(PartDesign::Feature::getClassTypeId()));
            rerouteBase(nextSolidFeature, feature);
        }
    }
}

std::vector<App::DocumentObject*> Body::removeObject(App::DocumentObject* feature)
{
    // This method must be called BEFORE the feature is removed from the Document!

    App::DocumentObject* nextSolidFeature = getNextSolidFeature(feature);
    App::DocumentObject* prevSolidFeature = getPrevSolidFeature(feature);

    // It's ok to remove the first solid feature, that just mean the next feature become the base one

    if (nextSolidFeature && nextSolidFeature->isDerivedFrom(PartDesign::Feature::getClassTypeId())) {
        auto* nextPD = static_cast<PartDesign::Feature*>(nextSolidFeature);
        // Check if the next feature is pointing to the one being deleted
        if (nextPD->BaseFeature.getValue() == feature) {
            rerouteBase(nextPD, prevSolidFeature);
        }
    }

    std::vector<App::DocumentObject*> model = Group.getValues();
    const auto it = std::ranges::find(model, feature);

    if (editRollPoint == feature) {
        editRollPoint = nullptr;
    }

    // Adjust Tip feature if it is pointing to the deleted object
    if (Tip.getValue() == feature) {
        if (prevSolidFeature) {
            Tip.setValue(prevSolidFeature);
        }
        else {
            Tip.setValue(nextSolidFeature);
        }
    }

    // Erase feature from Group
    if (it != model.end()) {
        model.erase(it);
        Group.setValues(model);
    }
    std::vector<App::DocumentObject*> result = {feature};
    return result;
}

std::vector<App::DocumentObject*> Body::removeObjects(std::vector<App::DocumentObject*> objs)
{
    // One at a time, so each keeps the chain and the Tip valid (ops#127); the group's own
    // removeObjects() rewrites Group only
    std::vector<App::DocumentObject*> removed;
    for (auto obj : objs) {
        if (obj && hasObject(obj)) {
            auto result = removeObject(obj);
            removed.insert(removed.end(), result.begin(), result.end());
        }
    }
    return removed;
}

void Body::reorderObject(const std::vector<App::DocumentObject*>& objs,
                         App::DocumentObject* target,
                         bool after)
{
    reorderBody(*this, objs, target, after, [this](App::DocumentObject* f, App::DocumentObject* b) {
        rerouteBase(f, b);
    });
}


App::DocumentObjectExecReturn* Body::execute()
{
    Part::BodyBase::execute();
    /*
    Base::Console().error("Body '%s':\n", getNameInDocument());
    App::DocumentObject* tip = Tip.getValue();
    Base::Console().error("   Tip: %s\n", (tip == NULL) ? "None" : tip->getNameInDocument());
    std::vector<App::DocumentObject*> model = Group.getValues();
    Base::Console().error("   Group:\n");
    for (std::vector<App::DocumentObject*>::const_iterator m = model.begin(); m != model.end(); m++)
    { if (*m == NULL) continue; Base::Console().error("      %s", (*m)->getNameInDocument()); if
    (Body::isSolidFeature(*m)) { App::DocumentObject* baseFeature =
    static_cast<PartDesign::Feature*>(*m)->BaseFeature.getValue(); Base::Console().error(", Base:
    %s\n", baseFeature == NULL ? "None" : baseFeature->getNameInDocument()); } else {
            Base::Console().error("\n");
        }
    }
    */

    App::DocumentObject* tip = Tip.getValue();

    Part::TopoShape tipShape = makeTopoShape();
    if (tip) {
        if (!tip->isDerivedFrom<PartDesign::Feature>()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Linked object is not a PartDesign feature")
            );
        }

        // get the shape of the tip
        tipShape = static_cast<Part::Feature*>(tip)->Shape.getShape();

        if (tipShape.getShape().IsNull()) {
            if (tip->isError()) {
                // A failed first feature passed an empty base through: the Body is empty and
                // valid (ops#126)
                lastTipShape = Part::TopoShape();
                Shape.setValue(Part::TopoShape());
                return App::DocumentObject::StdReturn;
            }
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Tip shape is empty")
            );
        }

        // The Tip's shape copied last time: Shape stays as it is, so nothing outside the Body
        // re-solves a reference into it (ops#127, R7: a roll back and forward with nothing edited)
        if (!lastTipShape.isNull() && sameTipShape(tipShape, lastTipShape)
            && !Shape.getShape().isNull()) {
            return App::DocumentObject::StdReturn;
        }
        lastTipShape = tipShape;

        // We should hide here the transformation of the baseFeature
        tipShape.transformShape(tipShape.getTransform(), true);
    }
    else {
        lastTipShape = Part::TopoShape();
    }

    Shape.setValue(tipShape);
    return App::DocumentObject::StdReturn;
}

void Body::onSettingDocument()
{

    if (connection.connected()) {
        connection.disconnect();
    }

    Part::BodyBase::onSettingDocument();
}

void Body::onChanged(const App::Property* prop)
{
    if (prop == &Tip && !isRestoring() && getDocument() && !isRolledBack()) {
        // Tip has Output status (ops#127, R7): a bar move touches the Body only when rolling to
        // the end gives a shape the Body hasn't copied (also on undo)
        auto shape = tipShapeOf(Tip.getValue());
        if (lastTipShape.isNull() || !sameTipShape(shape, lastTipShape)) {
            enforceRecompute();
        }
    }
    // we neither load a project nor perform undo/redo
    if (!this->isRestoring() && this->getDocument()
        && !this->getDocument()->isPerformingTransaction()) {
        if (prop == &BaseFeature) {
            FeatureBase* bf = nullptr;
            bool createdBaseFeature = false;
            auto first = Group.getValues().empty() ? nullptr : Group.getValues().front();

            if (BaseFeature.getValue()) {
                // setup the FeatureBase if needed
                if (!first || !first->isDerivedFrom<FeatureBase>()) {
                    bf = getDocument()->addObject<FeatureBase>("BaseFeature");
                    insertObject(bf, first, false);
                    createdBaseFeature = true;

                    if (!Tip.getValue()) {
                        Tip.setValue(bf);
                    }
                }
                else {
                    bf = static_cast<FeatureBase*>(first);
                }
            }

            if (bf && (bf->BaseFeature.getValue() != BaseFeature.getValue())) {
                bf->BaseFeature.setValue(BaseFeature.getValue());
                bf->recomputeFeature();
            }
            if (bf && createdBaseFeature) {
                if (auto* base = freecad_cast<App::GeoFeature*>(BaseFeature.getValue())) {
                    // Initial placement is derived from the current global placements. Set the
                    // Body placement before assigning BaseFeature to keep the source feature's
                    // global position when the internal FeatureBase is created.
                    bf->Placement.setValue(this->globalPlacement().inverse() * base->globalPlacement());
                }
            }
        }
        else if (prop == &Group) {
            // if the FeatureBase was deleted we set the BaseFeature link to nullptr
            if (BaseFeature.getValue()
                && (Group.getValues().empty()
                    || !Group.getValues().front()->isDerivedFrom<FeatureBase>())) {
                BaseFeature.setValue(nullptr);
            }
        }
        else if (prop == &AllowCompound) {
            // As disallowing compounds can break the model we need to recompute the whole tree.
            // This will inform user about first place where there is more than one solid.
            // On allowing compounds we must also recompute the entire feature tree
            for (auto feature : getFullModel()) {
                feature->enforceRecompute();
            }
        }
        else if (prop == &ShapeMaterial) {
            std::vector<App::DocumentObject*> features = Group.getValues();
            if (!features.empty()) {
                for (auto it : features) {
                    auto feature = dynamic_cast<Part::Feature*>(it);
                    if (feature) {
                        if (feature->ShapeMaterial.getValue().getUUID()
                            != ShapeMaterial.getValue().getUUID()) {
                            feature->ShapeMaterial.setValue(ShapeMaterial.getValue());
                        }
                    }
                }
            }
        }
    }

    Part::BodyBase::onChanged(prop);
}

void Body::setupObject()
{
    Part::BodyBase::setupObject();
}

void Body::unsetupObject()
{
    Part::BodyBase::unsetupObject();
}

PyObject* Body::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new BodyPy(this), true);
    }
    return Py::new_reference_to(PythonObject);
}

std::vector<std::string> Body::getSubObjects(int reason) const
{
    if (reason == GS_SELECT && !showTip) {
        return Part::BodyBase::getSubObjects(reason);
    }
    return {};
}

App::DocumentObject* Body::getSubObject(
    const char* subname,
    PyObject** pyObj,
    Base::Matrix4D* pmat,
    bool transform,
    int depth
) const
{
    while (subname && *subname == '.') {
        ++subname;  // skip leading .
    }

    // PartDesign::Feature now support grouping sibling features, and the user
    // is free to expand/collapse at any time. To not disrupt subname path
    // because of this, the body will peek the next two sub-objects reference,
    // and skip the first sub-object if possible.
    if (subname) {
        const char* firstDot = strchr(subname, '.');
        if (firstDot) {
            const char* secondDot = strchr(firstDot + 1, '.');
            if (secondDot) {
                auto firstObj = Group.find(std::string(subname, firstDot).c_str());
                if (!firstObj || firstObj->isDerivedFrom<PartDesign::Feature>()) {
                    auto secondObj = Group.find(std::string(firstDot + 1, secondDot).c_str());
                    if (secondObj) {
                        // we support only one level of sibling grouping, so no
                        // recursive call to our own getSubObject()
                        return Part::BodyBase::getSubObject(
                            firstDot + 1,
                            pyObj,
                            pmat,
                            transform,
                            depth + 1
                        );
                    }
                }
            }
        }
    }
#if 1
    return Part::BodyBase::getSubObject(subname, pyObj, pmat, transform, depth);
#else
    // The following code returns Body shape only if there is at least one
    // child visible in the body (when show through, not show tip). The
    // original intention is to sync visual to shape returned by
    // Part.getShape() when the body is included in some other group. But this
    // interfere with direct modeling using body shape. Therefore it is
    // disabled here.

    if (!pyObj || showTip
        || (subname && !Data::ComplexGeoData::isMappedElement(subname) && strchr(subname, '.'))) {
        return Part::BodyBase::getSubObject(subname, pyObj, pmat, transform, depth);
    }

    // We return the shape only if there are feature visible inside
    for (auto obj : Group.getValues()) {
        if (obj->Visibility.getValue() && obj->isDerivedFrom<PartDesign::Feature>()) {
            return Part::BodyBase::getSubObject(subname, pyObj, pmat, transform, depth);
        }
    }
    if (pmat && transform) {
        *pmat *= Placement.getValue().toMatrix();
    }
    return const_cast<Body*>(this);
#endif
}

void Body::onDocumentRestored()
{
    for (auto obj : Group.getValues()) {
        if (obj->isDerivedFrom<PartDesign::Feature>()) {
            static_cast<PartDesign::Feature*>(obj)->_Body.setValue(this);
        }
    }
    _GroupTouched.setStatus(App::Property::Output, true);
    Tip.setStatus(App::Property::Output, true);

    // trigger ViewProviderBody::copyColorsfromTip
    if (Tip.getValue()) {
        Tip.touch();
    }

    DocumentObject::onDocumentRestored();
}

// a body is solid if it has features that are solid
bool Body::isSolid()
{
    std::vector<App::DocumentObject*> features = getFullModel();
    for (auto feature : features) {
        if (isSolidFeature(feature)) {
            return true;
        }
    }
    return false;
}
