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
#include <cstring>
#include <functional>
#include <map>
#include <optional>
#include <set>
#include <utility>

#include <BRepAlgoAPI_Cut.hxx>

#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/VarSet.h>
#include <App/Origin.h>
#include <Base/Placement.h>
#include <Base/Tools.h>

#include "Body.h"
#include "BodyPy.h"
#include "FeatureBase.h"
#include "FeatureBoolean.h"
#include "FeatureDeletePart.h"
#include "FeatureDressUp.h"
#include "FeatureSketchBased.h"
#include "FeatureSolid.h"
#include "FeatureTransformed.h"
#include "Retarget.h"
#include "ShapeBinder.h"
#include "Studio.h"

namespace App
{
// App/DocumentObject.cpp (FreeCAD-CH ops#325): the readers of obj through a subname path of a
// container holding it or of a link showing one, which aren't in obj's in-list
AppExport std::vector<DocumentObject*> subnamePathReaders(const DocumentObject* obj,
                                                          std::vector<DocumentObject*>* links = nullptr);
}  // namespace App

using namespace PartDesign;


PROPERTY_SOURCE(PartDesign::Body, Part::BodyBase)

Body::Body()
{
    BaseFeature.setScope(App::LinkScope::Global);
    ADD_PROPERTY_TYPE(AllowCompound, (true), "Base", App::Prop_None, "Allow multiple solids in Body");
    // FreeCAD-CH ops#654: the part's identity in its studio (StudioList.h)
    ADD_PROPERTY_TYPE(StudioPartId, (""), "Studio", App::Prop_Hidden, "The part's id in its studio");
    ADD_PROPERTY_TYPE(StudioParentId,
                      (""),
                      "Studio",
                      App::Prop_Hidden,
                      "The id of the part this one is a piece of");
    ADD_PROPERTY_TYPE(StudioMadeBy,
                      (nullptr),
                      "Studio",
                      App::Prop_Hidden,
                      "The studio feature or piece record that made this part");
    ADD_PROPERTY_TYPE(StudioPieceWitness,
                      (),
                      "Studio",
                      App::Prop_Hidden,
                      "Element names of the parent part that lie on this piece: '<tier> <name>', "
                      "the name interned (ops#640 C2)");

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

bool Body::isRolledBack() const
{
    // Rolled back when a solid feature follows the bar. A bar outside the Group (a Tip set from
    // Python, or a stale file) or a non-solid after the last solid is the end: it holds nothing,
    // so the Body itself mustn't be held either (ops#127, M1)
    const auto& features = Group.getValues();
    return firstHeldSolid(features, effectiveBar()) < features.size();
}

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
    // The questions open on this thread, across Bodies: B1x asks another Body, which may ask this
    // one back. A cycle of links (possible from Python or an expression) would recurse without
    // end; a question already open counts as held, as a cycle within one Body does (ops#325)
    thread_local std::set<std::pair<const Body*, const App::DocumentObject*>> open;
    const auto question = std::make_pair(this, obj);
    if (!open.insert(question).second) {
        return true;
    }
    struct Close
    {
        std::pair<const Body*, const App::DocumentObject*> question;
        ~Close()
        {
            open.erase(question);
        }
    } close {question};
    const auto& features = Group.getValues();
    std::size_t firstHeld = firstHeldSolid(features, effectiveBar());
    if (firstHeld >= features.size()) {
        return false;
    }
    std::map<const App::DocumentObject*, std::size_t> position;
    for (std::size_t i = 0; i < features.size(); ++i) {
        position.emplace(features[i], i);
    }
    // A user outside this Body: held only by its own Body's bar (the in-list holds a member's
    // Body, as in FailureContinuation's bodyOf())
    auto heldElsewhere = [this](const App::DocumentObject* user) {
        const Body* other = nullptr;
        if (auto feature = freecad_cast<const PartDesign::Feature*>(user)) {
            other = feature->getFeatureBody();
        }
        for (auto in : user->getInList()) {
            if (other) {
                break;
            }
            if (auto body = freecad_cast<const Body*>(in); body && body->hasObject(user)) {
                other = body;
            }
        }
        return other && other != this && other->holds(user);
    };
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
                // B1: held only when every member that uses it is held. B1x (FreeCAD-CH ops#325):
                // a user outside this Body (another Body's feature, a Part feature, a link) reads
                // it too, so it isn't held unless that user's own Body holds the user
                // A reader through a subname path (Support = (Studio, "A.Shared.")) is a user too
                memo[o] = true;  // a cycle (shouldn't exist) counts as held
                result = true;
                auto users = o->getInList();
                auto pathReaders = App::subnamePathReaders(o);
                users.insert(users.end(), pathReaders.begin(), pathReaders.end());
                for (auto user : users) {
                    if (user == this) {
                        continue;
                    }
                    if (position.count(user) ? !held(user) : !heldElsewhere(user)) {
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

bool Body::waitsBelowBar(const App::DocumentObject* obj) const
{
    if (!obj || isSolidFeature(obj) || !isRolledBack() || holds(obj)) {
        return false;
    }
    const auto& features = Group.getValues();
    auto pos = std::find(features.begin(), features.end(), obj);
    if (pos == features.end()) {
        return false;
    }
    if (App::DocumentObject* bar = effectiveBar()) {
        auto barPos = std::find(features.begin(), features.end(), bar);
        if (barPos == features.end() || pos <= barPos) {
            return false;
        }
    }
    // A cycle of links (possible from Python) counts as live
    thread_local std::set<const App::DocumentObject*> open;
    if (!open.insert(obj).second) {
        return false;
    }
    struct Close
    {
        const App::DocumentObject* item;
        ~Close()
        {
            open.erase(item);
        }
    } close {obj};
    // Every user is held by its own Body's bar, or waits below it (a datum under a waiting sketch)
    bool used = false;
    for (auto user : obj->getInList()) {
        if (user == this) {
            continue;
        }
        Body* body = findBodyOf(user);
        if (!body || !(body->holds(user) || body->waitsBelowBar(user))) {
            return false;
        }
        used = true;
    }
    return used;
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

void Body::rerouteBase(App::DocumentObject* feature, App::DocumentObject* newBase, bool reorder)
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
    pd->onBaseFeatureRerouted(oldBase, newBase, reorder);
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
            // Transformed Features inside a MultiTransform are not solid features, nor is a new
            // pattern with nothing picked; a pattern whose Originals a reorder parked still is
            // (ops#127), and so is one in the chain whose original was deleted (ops#640, F3)
            return !transFeature->isOutOfChain() || hasParkedOriginals(obj);
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

namespace
{
// Defined with New part's rules, below
std::vector<App::DocumentObject*> linksOf(const App::DocumentObject* obj);
std::vector<App::DocumentObject*> usersOf(const App::DocumentObject* obj);

std::string quotedLabel(const App::DocumentObject* obj)
{
    return std::string("'") + (obj ? obj->Label.getValue() : "?") + "'";
}

// The first user of the Body `body` (or of its origin) that the Body's removal would break: not a
// container holding it, not its origin, not one of `moved` (relinked to the target's origin by
// insertObject), or null. `viaOrigin` says whether the user links the origin. A container is a
// group that holds the Body and is not a PartDesign feature: a Boolean's Group is its tool list
// (FeatureBoolean.cpp setObjects), so a Boolean holding the Body uses it. A reader through a
// subname path of the Body breaks whatever it is (its path names the Body)
const App::DocumentObject* bodyUser(
    const Body* body,
    const std::vector<App::DocumentObject*>& moved,
    bool& viaOrigin
)
{
    viaOrigin = false;
    auto harmless = [&](const App::DocumentObject* user) {
        if (!user || user == body || std::ranges::find(moved, user) != moved.end()) {
            return true;
        }
        if (user->isDerivedFrom<PartDesign::Feature>()) {
            return false;
        }
        auto group = user->getExtensionByType<App::GroupExtension>(true);
        return group && group->hasObject(body);
    };
    for (const App::DocumentObject* user : App::subnamePathReaders(body)) {
        if (user && user != body) {
            return user;
        }
    }
    for (const App::DocumentObject* user : body->getInList()) {
        if (!harmless(user)) {
            return user;
        }
    }
    // Its origin goes with it: a link into it from elsewhere would dangle
    auto origin = freecad_cast<App::Origin*>(body->Origin.getValue());
    if (!origin) {
        return nullptr;
    }
    const std::vector<App::DocumentObject*> datums = origin->OriginFeatures.getValues();
    auto own = [&](const App::DocumentObject* user) {
        return user == origin || std::ranges::find(datums, user) != datums.end();
    };
    std::vector<App::DocumentObject*> originUsers = origin->getInList();
    for (const App::DocumentObject* datum : datums) {
        const std::vector<App::DocumentObject*> datumUsers = datum->getInList();
        originUsers.insert(originUsers.end(), datumUsers.begin(), datumUsers.end());
    }
    for (const App::DocumentObject* user : originUsers) {
        if (!harmless(user) && !own(user)) {
            viaOrigin = true;
            return user;
        }
    }
    return nullptr;
}

/* FreeCAD-CH (ops#640 round 9, journeys J8 and J17): Add to part, a new part's feature switched
 * back to Add as Onshape's Extrude from New, takes its whole Body into the target and removes it:
 * what builds on the feature in its part follows it (a Mirror of it, a fillet on its edges, a
 * sketch on its face, a datum), as newPartFrom moved them the other way. The Body's members go in
 * their order, at the feature's place in the studio's history (the target's last member before
 * it): those before the feature (its sketch) right before it, the rest after it. Refused, naming
 * why, when the feature isn't the Body's first solid, when something outside the Body uses a
 * member (a link, a Derived, another part's binder or Boolean) or reads through the Body, when a
 * member combines other parts with it, or when a member of the target comes between the feature
 * and a later member in the history (the move would put them before it). */
struct AddToPartPlan
{
    /// The Body's members, in its order: all of them go
    std::vector<App::DocumentObject*> moved;
    /// The target's member they go after (null: its top)
    App::DocumentObject* after = nullptr;
    /// The studio's sequence before the move, saved again after it
    std::vector<App::DocumentObject*> sequence;
    std::string refusal;
};

AddToPartPlan planAddToPart(const App::DocumentObject* feature, const Body* body, const Body* target)
{
    AddToPartPlan plan;
    auto refuse = [&plan](std::string why) {
        plan.refusal = std::move(why);
        return plan;
    };
    if (const_cast<Body*>(body)->getPrevSolidFeature(const_cast<App::DocumentObject*>(feature))) {
        return refuse(quotedLabel(body) + " holds more than this feature; merge it instead");
    }
    if (body->isRolledBack()) {
        return refuse("roll " + quotedLabel(body) + " to the end first");
    }
    // The Body it leaves is removed: nothing else may use it (a Merge in another part consuming
    // it, as Delete part refuses; a Boolean's tool, a binder, a link, an expression)
    if (auto merge = Boolean::mergeOf(body)) {
        return refuse(
            quotedLabel(body) + " is merged by " + quotedLabel(merge) + "; delete the Merge first"
        );
    }
    plan.moved = body->Group.getValues();
    auto moves = [&plan](const App::DocumentObject* obj) {
        return std::ranges::find(plan.moved, obj) != plan.moved.end();
    };
    std::vector<App::DocumentObject*> origin;
    if (auto own = freecad_cast<App::Origin*>(body->Origin.getValue())) {
        origin = own->OriginFeatures.getValues();
        origin.push_back(own);
    }
    for (App::DocumentObject* obj : plan.moved) {
        if (obj->isDerivedFrom<Boolean>()) {
            return refuse(
                quotedLabel(obj) + " combines other parts with " + quotedLabel(body)
                + "; merge the part instead"
            );
        }
        // What would act on the target's material once merged, where it acted on the part's own
        // (review R9-2, R9-3): a pattern of the whole shape would copy the target too, a cut after
        // the feature would cut it too. Onshape's scope for them would differ: refused
        if (auto pattern = freecad_cast<Transformed*>(obj);
            pattern
            && static_cast<Transformed::Mode>(pattern->TransformMode.getValue())
                == Transformed::Mode::WholeShape) {
            return refuse(
                quotedLabel(obj) + " copies the whole of " + quotedLabel(body) + ", so it would copy "
                + quotedLabel(target) + " too"
            );
        }
        if (auto cut = freecad_cast<FeatureAddSub*>(obj); cut && obj != feature
            && cut->getBooleanOperation() != FeatureAddSub::BooleanOperation::Union) {
            return refuse(quotedLabel(obj) + " would cut " + quotedLabel(target) + " too");
        }
        for (App::DocumentObject* user : usersOf(obj)) {
            if (user == body || moves(user)) {
                continue;
            }
            auto merge = freecad_cast<const Boolean*>(user);
            if (merge && merge->isMerge()) {
                return refuse(
                    quotedLabel(body) + " is merged by " + quotedLabel(merge)
                    + "; delete the Merge first"
                );
            }
            return refuse(quotedLabel(user) + " uses " + quotedLabel(obj));
        }
        // insertObject relinks a link to the origin, not a binder's that traces its support
        // (ops#244) or a sub-shape binder's (its links aren't the ones relinkToOrigin rewrites)
        auto binder = freecad_cast<ShapeBinder*>(obj);
        const bool relinked = !(binder && binder->TraceSupport.getValue())
            && !obj->isDerivedFrom<SubShapeBinder>();
        for (App::DocumentObject* link : linksOf(obj)) {
            const bool ownOrigin = std::ranges::find(origin, link) != origin.end();
            if (link == body || (ownOrigin && !relinked)) {
                return refuse(
                    quotedLabel(obj) + (link == body ? " uses " : " uses the origin of ")
                    + quotedLabel(body) + ", which Add to part would remove"
                );
            }
        }
    }
    bool viaOrigin = false;
    if (auto user = bodyUser(body, plan.moved, viaOrigin)) {
        return refuse(
            quotedLabel(user) + (viaOrigin ? " uses the origin of " : " uses ") + quotedLabel(body)
            + ", which Add to part would remove"
        );
    }

    // Where the history has it: after the target's last member that comes before the feature in
    // the studio's sequence. The feature's place, not its sketch's: a sketch drawn before the
    // target's rows would put the feature before them (review MISS)
    App::Part* studio = nullptr;
    Body::studioOf(target, studio);
    plan.sequence = studioSequence(body->getDocument(), studio);
    const std::vector<App::DocumentObject*>& group = target->Group.getValues();
    auto inTarget = [&group](const App::DocumentObject* obj) {
        return std::ranges::find(group, obj) != group.end();
    };
    const auto here = std::ranges::find(plan.sequence, feature);
    for (auto it = plan.sequence.begin(); it != here; ++it) {
        if (inTarget(*it)) {
            plan.after = *it;
        }
    }
    if (here == plan.sequence.end()) {
        return plan;
    }
    // What follows the feature in its Body goes right after it: no member of the target may come
    // between them in the history
    auto lastMoved = here;
    for (auto it = here + 1; it != plan.sequence.end(); ++it) {
        if (moves(*it)) {
            lastMoved = it;
        }
    }
    for (auto it = here + 1; it < lastMoved; ++it) {
        if (inTarget(*it)) {
            App::DocumentObject* later = *std::find_if(it + 1, lastMoved + 1, moves);
            return refuse(
                quotedLabel(later) + " comes after " + quotedLabel(*it) + " of "
                + quotedLabel(target) + " in the history; Add to part would put it before"
            );
        }
    }
    return plan;
}
}  // namespace

std::string Body::addToPartRefusal(const App::DocumentObject* feature, const Body* target)
{
    const Body* body = findBodyOf(feature);
    if (!body || !isSolidFeature(feature)) {
        return "the object isn't a solid feature of a body";
    }
    if (!target || target == body) {
        return "no other part to add it to";
    }
    App::Part* bodyStudio = nullptr;
    App::Part* targetStudio = nullptr;
    if (body->getDocument() != target->getDocument() || !studioOf(body, bodyStudio)
        || !studioOf(target, targetStudio) || bodyStudio != targetStudio) {
        return quotedLabel(target) + " isn't a part of the feature's studio";
    }
    if (!areStudioSiblings(body, target)) {
        return quotedLabel(target) + " is placed apart from " + quotedLabel(body)
            + " (not one origin), or shown through a link";
    }
    if (target->isRolledBack()) {
        return "roll " + quotedLabel(target) + " to the end first";
    }
    // The rest is planAddToPart's: round 9 takes what builds on the feature in its part along
    return planAddToPart(feature, body, target).refusal;
}

/* FreeCAD-CH (ops#640 round 5, hands-on B5-3 and B5-4): New part for a feature that later
 * features build on, as Onshape's Extrude switched from Add to New. Onshape's later features act on
 * parts: a fillet on the boss's edges follows the boss to its new part, a later Extrude keeps its
 * merge scope (the part the boss leaves). Here a Body's features are one chain, so New part moves
 * the feature, its Profile sketch, and the later features that work on its own material, in order,
 * into the new Body; the others stay and the chain closes over the gap (Body::removeObject). What
 * can't be told apart, or would change what a feature does without a word, is refused, naming the
 * feature:
 * - a dress-up goes when its edges or faces are on the feature's own material (they touch the
 *   feature's tool and not the solid before it), and stays when none touches the tool;
 * - a pattern goes when it copies only features that go, and stays when it copies none and its
 *   result's change doesn't reach the tool; a pattern of the whole shape is refused;
 * - another solid feature stays when its tool (an Extrude's, a Boolean's parts) doesn't reach the
 *   feature's tool: a later Extrude on the boss would, as Onshape's would then act on the part the
 *   boss left;
 * - a feature that goes may link only what goes (and the Body's origin, which insertObject relinks);
 *   one that stays may link nothing that goes, besides its chain (BaseFeature);
 * - nothing outside the Body may use what goes.
 * The feature's Merge (its merge scope) goes first, when nothing builds on it. */
namespace
{
// The shape of `obj` where it is in the document
Part::TopoShape placedShape(const App::DocumentObject* obj, Part::TopoShape shape)
{
    if (!shape.isNull()) {
        if (auto geo = freecad_cast<const App::GeoFeature*>(obj)) {
            shape.setPlacement(geo->globalPlacement());
        }
    }
    return shape;
}

Part::TopoShape placedShape(const App::DocumentObject* obj)
{
    auto feature = freecad_cast<const Part::Feature*>(obj);
    return feature ? placedShape(obj, feature->Shape.getShape()) : Part::TopoShape();
}

bool touches(const TopoDS_Shape& shape, const TopoDS_Shape& region)
{
    return !shape.IsNull() && !region.IsNull() && FeatureAddSub::shapesTouch(shape, region);
}

// The objects `obj` links to through its properties: not by expression, not its chain
// (BaseFeature) or its Body (_Body), not a hidden link
std::vector<App::DocumentObject*> linksOf(const App::DocumentObject* obj)
{
    std::vector<App::DocumentObject*> targets;
    std::vector<App::Property*> props;
    obj->getPropertyList(props);
    auto pd = freecad_cast<const PartDesign::Feature*>(obj);
    for (App::Property* prop : props) {
        auto link = freecad_cast<App::PropertyLinkBase*>(prop);
        if (!link || prop == &obj->ExpressionEngine
            || (pd && (prop == &pd->BaseFeature || prop == &pd->_Body))) {
            continue;
        }
        link->getLinks(targets, false);
    }
    return targets;
}

// The users of `obj` (its in-list, and the readers through a subname path), not `obj` itself
std::vector<App::DocumentObject*> usersOf(const App::DocumentObject* obj)
{
    std::vector<App::DocumentObject*> users = obj->getInList();
    const std::vector<App::DocumentObject*> pathReaders = App::subnamePathReaders(obj);
    users.insert(users.end(), pathReaders.begin(), pathReaders.end());
    std::erase(users, obj);
    std::erase(users, nullptr);
    return users;
}

std::string quotedLabels(const std::vector<App::DocumentObject*>& objects)
{
    std::string text;
    for (const App::DocumentObject* obj : objects) {
        text += (text.empty() ? "" : ", ") + quotedLabel(obj);
    }
    return text;
}

/** FreeCAD-CH (ops#640, review R5-2 and its fix review F1/F2): a dress-up's Base, when it is the
 * dress-up's own BaseFeature and the move's reroute can carry it (DressUp::onBaseFeatureRerouted
 * relinks Base by its mapped names): nothing else of the dress-up links that object (a Draft's
 * NeutralPlane or PullDirection on it would stay behind, the reroute relinks Base only), and every
 * reference has a mapped name (one without would fall back to its index on the other shape: a
 * silent wrong edge). Otherwise nullptr: the link check refuses as before. */
App::DocumentObject* chainBaseOf(App::DocumentObject* obj)
{
    auto dressUp = freecad_cast<DressUp*>(obj);
    App::DocumentObject* base = dressUp ? dressUp->Base.getValue() : nullptr;
    if (!base || base != dressUp->BaseFeature.getValue()) {
        return nullptr;
    }
    const auto& shadows = dressUp->Base.getShadowSubs();
    if (shadows.size() != dressUp->Base.getSubValues().size()
        || std::ranges::any_of(shadows, [](const auto& shadow) { return shadow.newName.empty(); })) {
        return nullptr;
    }
    std::vector<App::Property*> props;
    obj->getPropertyList(props);
    for (App::Property* prop : props) {
        auto link = freecad_cast<App::PropertyLinkBase*>(prop);
        if (!link || prop == &dressUp->Base || prop == &dressUp->BaseFeature
            || prop == &dressUp->_Body || prop == &dressUp->ExpressionEngine) {
            continue;
        }
        std::vector<App::DocumentObject*> targets;
        link->getLinks(targets, false);
        if (std::ranges::find(targets, base) != targets.end()) {
            return nullptr;
        }
    }
    return base;
}

struct NewPartPlan
{
    /// What goes to the new part, in the Body's order: the sketch, the feature, what follows
    std::vector<App::DocumentObject*> moved;
    /// The feature's Merge, which goes first
    Boolean* merge = nullptr;
    std::string refusal;
};

// Why the Merge after `feature` can't go: something besides its Body builds on it, or empty
std::string mergeUserRefusal(const Boolean* merge, const Body* body)
{
    const std::vector<App::DocumentObject*> merged = merge->mergedBodies();
    for (App::DocumentObject* user : usersOf(merge)) {
        if (user != body && std::ranges::find(merged, user) == merged.end()) {
            return quotedLabel(user) + " builds on " + quotedLabel(merge) + ", the merge with "
                + quotedLabels(merged);
        }
    }
    return {};
}

// What New part moves for `feature` (planNewPart's rules, above), or why it is refused. With
// `ignoreMerge`, the feature's Merge counts as gone already (the user unticked its whole scope):
// what builds on it builds on the feature
NewPartPlan planNewPart(App::DocumentObject* feature, bool ignoreMerge)
{
    NewPartPlan plan;
    Body* body = Body::findBodyOf(feature);
    if (!body || !Body::isSolidFeature(feature)) {
        plan.refusal = "the object isn't a solid feature of a body";
        return plan;
    }
    const std::vector<App::DocumentObject*> group = body->Group.getValues();
    const auto here = std::ranges::find(group, feature);
    if (here == group.end()) {
        plan.refusal = "the object isn't a solid feature of a body";
        return plan;
    }
    plan.merge = Boolean::mergeAfter(feature);
    if (plan.merge && !ignoreMerge) {
        if (std::string why = mergeUserRefusal(plan.merge, body); !why.empty()) {
            plan.refusal = why;
            return plan;
        }
    }
    std::vector<App::DocumentObject*> later;
    for (auto it = here + 1; it != group.end(); ++it) {
        if (*it != plan.merge) {
            later.push_back(*it);
        }
    }
    const auto laterSolid = std::ranges::find_if(later, Body::isSolidFeature);
    if (laterSolid == later.end()) {
        // Nothing builds on it in its chain: the Tip, or its Merge the Tip
        App::DocumentObject* tip = body->Tip.getValue();
        if (tip != feature && !(plan.merge && tip == plan.merge)) {
            plan.refusal = "roll " + quotedLabel(body) + " to the end first";
            return plan;
        }
    }
    else {
        auto addSub = freecad_cast<FeatureAddSub*>(feature);
        if (!body->getPrevSolidFeature(feature)) {
            plan.refusal = quotedLabel(feature) + " is the first solid of " + quotedLabel(body)
                + ": " + quotedLabel(*laterSolid) + " builds on it";
            return plan;
        }
        if (body->Tip.getValue() != body->lastSolidFeature()) {
            plan.refusal = "roll " + quotedLabel(body) + " to the end first";
            return plan;
        }
        if (!addSub || addSub->getAddSubType() != FeatureAddSub::Type::Additive
            || addSub->AddSubShape.getShape().isNull()) {
            plan.refusal = quotedLabel(*laterSolid) + " comes after " + quotedLabel(feature)
                + ", which adds no material of its own";
            return plan;
        }
    }

    // Its Profile sketch, which goes along when only what goes uses it
    auto profileBased = freecad_cast<ProfileBased*>(feature);
    App::DocumentObject* profile = profileBased ? profileBased->Profile.getValue() : nullptr;
    if (!profile || !profile->isDerivedFrom<Part::Part2DObject>() || !body->hasObject(profile)) {
        profile = nullptr;
    }
    std::vector<App::DocumentObject*> moved = {feature};
    auto goes = [&](const App::DocumentObject* obj) {
        return std::ranges::find(moved, obj) != moved.end()
            || (ignoreMerge && plan.merge && obj == plan.merge);
    };
    auto isLater = [&](const App::DocumentObject* obj) {
        return std::ranges::find(later, obj) != later.end();
    };
    // The origin, which insertObject relinks to the new part's
    std::vector<App::DocumentObject*> origin;
    if (auto own = freecad_cast<App::Origin*>(body->Origin.getValue())) {
        origin = own->OriginFeatures.getValues();
        origin.push_back(own);
    }
    auto isOrigin = [&](const App::DocumentObject* obj) {
        return std::ranges::find(origin, obj) != origin.end();
    };

    // The feature's own material: its tool, and the solid before it
    TopoDS_Shape tool;
    TopoDS_Shape before;
    if (laterSolid != later.end()) {
        auto addSub = static_cast<FeatureAddSub*>(feature);
        tool = placedShape(feature, addSub->AddSubShape.getShape()).getShape();
        before = placedShape(body->getPrevSolidFeature(feature)).getShape();
    }
    auto reachesTool = [&](const TopoDS_Shape& shape) {
        return touches(shape, tool);
    };

    // FreeCAD-CH (ops#640 round 9, J17): a datum plane, line or point of the Body, before the
    // feature or after it, that only what goes uses goes along, when its attachment links nothing
    // but the origin (insertObject relinks it) or another datum that goes. Not one on a feature's
    // elements, even one that goes (review R9-1: a face of the moving feature's result may be the
    // rest of the part's material, gone from the new part). Onshape's plane is the studio's, so it
    // never holds the switch; here it moves with its users. Taken tentatively, in order: one that
    // something staying uses stays after all, and what follows the feature may then not use it
    // (the refusal as before; the feature and its sketch keep it across parts, as before)
    std::vector<App::DocumentObject*> tentative;
    auto isTentative = [&](const App::DocumentObject* obj) {
        return std::ranges::find(tentative, obj) != tentative.end();
    };
    auto datumMayGo = [&](App::DocumentObject* obj) {
        if (!PartDesign::Feature::isDatum(obj)) {
            return false;
        }
        const std::vector<App::DocumentObject*> users = usersOf(obj);
        const bool usedInside = std::ranges::any_of(users, [&](const App::DocumentObject* user) {
            return user != body;
        }) && std::ranges::all_of(users, [&](const App::DocumentObject* user) {
            return user == body || body->hasObject(user);
        });
        const std::vector<App::DocumentObject*> links = linksOf(obj);
        return usedInside && std::ranges::all_of(links, [&](const App::DocumentObject* link) {
            return isOrigin(link) || isTentative(link);
        });
    };
    // Those before the feature (review R9-4: the plane made first, then the Mirror)
    for (auto it = group.begin(); it != here; ++it) {
        if (datumMayGo(*it)) {
            moved.push_back(*it);
            tentative.push_back(*it);
        }
    }
    std::function<std::string(App::DocumentObject*)> keepDatum;
    keepDatum = [&](App::DocumentObject* datum) -> std::string {
        std::erase(moved, datum);
        std::erase(tentative, datum);
        // a tentative datum attached to it stays too
        const std::vector<App::DocumentObject*> others = tentative;
        for (App::DocumentObject* other : others) {
            const std::vector<App::DocumentObject*> links = linksOf(other);
            if (isTentative(other) && std::ranges::find(links, datum) != links.end()) {
                if (std::string why = keepDatum(other); !why.empty()) {
                    return why;
                }
            }
        }
        for (App::DocumentObject* obj : moved) {
            const std::vector<App::DocumentObject*> links = linksOf(obj);
            if (obj != feature && obj != profile && !isTentative(obj)
                && std::ranges::find(links, datum) != links.end()) {
                return quotedLabel(obj) + " uses " + quotedLabel(datum) + ", which stays in "
                    + quotedLabel(body);
            }
        }
        return {};
    };

    for (App::DocumentObject* obj : later) {
        bool go = false;
        if (datumMayGo(obj)) {
            moved.push_back(obj);
            tentative.push_back(obj);
            continue;
        }
        if (Body::isSolidFeature(obj)) {
            if (auto dressUp = freecad_cast<DressUp*>(obj)) {
                App::DocumentObject* base = dressUp->Base.getValue();
                const std::vector<std::string> subs = dressUp->Base.getSubValues(false);
                const Part::TopoShape baseShape = placedShape(base);
                bool own = !subs.empty();
                bool apart = true;
                for (const std::string& sub : subs) {
                    const TopoDS_Shape element =
                        baseShape.isNull() ? TopoDS_Shape() : baseShape.getSubShape(sub.c_str(), true);
                    if (element.IsNull()) {
                        own = false;
                        apart = false;
                        break;
                    }
                    const bool onTool = reachesTool(element);
                    own = own && onTool && !touches(element, before);
                    apart = apart && !onTool;
                }
                // Review R5-2: by its elements, whatever its Base is (a feature in between, or
                // the moved feature itself): the reroute carries the Base link's names (Feature::
                // relinkToMatchingSubelements), or the dress-up fails naming the reference
                if (own) {
                    go = true;
                }
                else if (apart) {
                    go = false;
                }
                else {
                    plan.refusal = quotedLabel(obj) + " works on both " + quotedLabel(feature)
                        + "'s material and the rest of " + quotedLabel(body)
                        + ", or on what can't be told apart";
                    return plan;
                }
            }
            else if (auto pattern = freecad_cast<Transformed*>(obj)) {
                const std::vector<App::DocumentObject*> originals = pattern->Originals.getValues();
                const bool whole =
                    static_cast<Transformed::Mode>(pattern->TransformMode.getValue())
                    == Transformed::Mode::WholeShape;
                const bool all = !originals.empty() && std::ranges::all_of(originals, goes);
                const bool none = std::ranges::none_of(originals, goes);
                if (!whole && all) {
                    go = true;
                }
                else if (!whole && none) {
                    // Its change: what it adds and what it takes away from its base
                    const TopoDS_Shape result = placedShape(obj).getShape();
                    const TopoDS_Shape previous = placedShape(pattern->BaseFeature.getValue()).getShape();
                    bool reaches = true;
                    if (!result.IsNull() && !previous.IsNull()) {
                        BRepAlgoAPI_Cut added(result, previous);
                        BRepAlgoAPI_Cut removed(previous, result);
                        if (added.IsDone() && removed.IsDone()) {
                            reaches = reachesTool(added.Shape()) || reachesTool(removed.Shape());
                        }
                    }
                    if (reaches) {
                        plan.refusal = quotedLabel(obj) + " copies features of "
                            + quotedLabel(body) + " onto " + quotedLabel(feature)
                            + "'s material, or can't be told apart";
                        return plan;
                    }
                }
                else {
                    plan.refusal = quotedLabel(obj) + " copies "
                        + (whole ? "the whole of " + quotedLabel(body)
                                 : "features of both parts");
                    return plan;
                }
            }
            else if (auto boolean = freecad_cast<Boolean*>(obj)) {
                // Another feature's Merge stays with it; a Boolean's parts mustn't reach the tool
                if (!boolean->isMerge()) {
                    for (App::DocumentObject* part : boolean->Group.getValues()) {
                        if (reachesTool(placedShape(part).getShape())) {
                            plan.refusal = quotedLabel(obj) + " reaches " + quotedLabel(feature)
                                + "'s material with " + quotedLabel(part);
                            return plan;
                        }
                    }
                }
            }
            else if (auto addSub = freecad_cast<FeatureAddSub*>(obj)) {
                const Part::TopoShape own = addSub->AddSubShape.getShape();
                if (own.isNull() || reachesTool(placedShape(obj, own).getShape())) {
                    plan.refusal = quotedLabel(obj) + (own.isNull() ? " has no tool to tell " : " reaches ")
                        + quotedLabel(feature) + "'s material"
                        + (own.isNull() ? " apart from" : ", and would stay in ")
                        + quotedLabel(body);
                    return plan;
                }
            }
            else {
                plan.refusal = "can't tell whether " + quotedLabel(obj) + " works on "
                    + quotedLabel(feature) + "'s material";
                return plan;
            }
        }
        // Its links: what goes links only what goes (the feature's sketch: below); what stays
        // links nothing that goes. A dress-up's Base on its own BaseFeature is the chain's link:
        // the move reroutes it with its references (Body::rerouteBase, review R5-2)
        App::DocumentObject* chainBase = chainBaseOf(obj);
        for (App::DocumentObject* target : linksOf(obj)) {
            if (chainBase && target == chainBase) {
                continue;
            }
            if (go && !goes(target) && !isOrigin(target) && target != profile
                && (isLater(target) || body->hasObject(target)) && target != body) {
                plan.refusal = quotedLabel(obj) + " uses " + quotedLabel(target) + ", which stays in "
                    + quotedLabel(body);
                return plan;
            }
            if (!go && goes(target)) {
                if (isTentative(target)) {
                    // a datum that something staying uses stays
                    if (std::string why = keepDatum(target); !why.empty()) {
                        plan.refusal = why;
                        return plan;
                    }
                    continue;
                }
                plan.refusal = quotedLabel(obj) + " uses " + quotedLabel(target)
                    + ", which would go to the new part";
                return plan;
            }
        }
        if (go) {
            moved.push_back(obj);
        }
    }
    // Nothing outside the Body uses what goes: the feature's siblings (a cut through other parts,
    // dropped by the switch) aside
    for (App::DocumentObject* obj : moved) {
        for (App::DocumentObject* user : usersOf(obj)) {
            if (user == body || body->hasObject(user)) {
                continue;
            }
            auto sibling = freecad_cast<FeatureAddSub*>(user);
            if (sibling && sibling->SiblingOf.getValue() == feature) {
                continue;
            }
            plan.refusal = quotedLabel(user) + " uses " + quotedLabel(obj);
            return plan;
        }
    }

    if (profile) {
        const std::vector<App::DocumentObject*> users = usersOf(profile);
        if (std::ranges::all_of(users, [&](const App::DocumentObject* user) {
                return user == body || goes(user);
            })) {
            moved.insert(moved.begin(), profile);
        }
        else {
            // It stays: the feature keeps it across parts (as before), a feature that follows
            // mustn't
            for (App::DocumentObject* obj : moved) {
                const std::vector<App::DocumentObject*> links = linksOf(obj);
                if (obj != feature && std::ranges::find(links, profile) != links.end()) {
                    plan.refusal = quotedLabel(obj) + " uses " + quotedLabel(profile)
                        + ", which stays in " + quotedLabel(body);
                    return plan;
                }
            }
        }
    }
    // A datum goes only when everything that uses it goes (again after each: one that only a
    // datum taken back used is taken back too)
    for (bool kept = true; kept;) {
        kept = false;
        for (App::DocumentObject* datum : tentative) {
            const std::vector<App::DocumentObject*> users = usersOf(datum);
            if (!std::ranges::all_of(users, [&](const App::DocumentObject* user) {
                    return user == body || goes(user);
                })) {
                if (std::string why = keepDatum(datum); !why.empty()) {
                    plan.refusal = why;
                    return plan;
                }
                kept = true;
                break;
            }
        }
    }
    // In the Body's order: a datum before the feature keeps its place before it
    auto place = [&group](const App::DocumentObject* obj) {
        return std::ranges::find(group, obj) - group.begin();
    };
    std::ranges::stable_sort(moved, [&](const App::DocumentObject* one, const App::DocumentObject* two) {
        return place(one) < place(two);
    });
    plan.moved = moved;
    return plan;
}
}  // namespace

namespace PartDesign
{
// FreeCAD-CH (ops#640 round 5): New part's rule, for the dialog's rows and the tests (no header
// names these: AppPartDesignPy.cpp and the Gui declare them)
PartDesignExport std::string newPartRefusal(const App::DocumentObject* feature, bool ignoreMerge);
std::string newPartRefusal(const App::DocumentObject* feature, bool ignoreMerge)
{
    return planNewPart(const_cast<App::DocumentObject*>(feature), ignoreMerge).refusal;
}

// Why the feature's Merge can't go for a Remove or an Intersect: something builds on it. Empty
// when it may, or when it has none
PartDesignExport std::string mergeGoesRefusal(const App::DocumentObject* feature);
std::string mergeGoesRefusal(const App::DocumentObject* feature)
{
    Body* body = Body::findBodyOf(feature);
    Boolean* merge = Boolean::mergeAfter(feature);
    return body && merge ? mergeUserRefusal(merge, body) : std::string();
}
}  // namespace PartDesign

Body* Body::newPartFrom(App::DocumentObject* feature)
{
    Body* body = findBodyOf(feature);
    if (!body || !isSolidFeature(feature)) {
        throw Base::ValueError("New part: the object isn't a solid feature of a body");
    }
    // What builds on it goes along, or the move is refused, naming why (planNewPart: a feature
    // that something uses would otherwise reroute the next solid, or make the links into it
    // cross-part without a word, the design's critic, point 9)
    const NewPartPlan plan = planNewPart(feature, /*ignoreMerge=*/false);
    if (!plan.refusal.empty()) {
        throw Base::ValueError("New part: " + plan.refusal);
    }
    App::Document* doc = feature->getDocument();
    auto part = static_cast<Body*>(doc->addObject("PartDesign::Body", "Body"));
    // Where the old Body is (identity in a studio, by the one-origin rule): a sketch on the old
    // Body's origin plane is relinked to the new one's, and at identity a placed old Body's lid
    // moved with no error (PR 302 review)
    part->Placement.setValue(body->Placement.getValue());
    // in the studio: the old Body's App::Part (SketchWorkflow.cpp does the same for a new Body)
    if (auto container = App::GeoFeatureGroupExtension::getGroupOfObject(body)) {
        if (auto group = container->getExtensionByType<App::GroupExtension>(true)) {
            group->addObject(part);
        }
    }
    // Out of the old Body first (Body::removeObject: the Tip goes back), then the sketch into
    // the new one before the feature, so the feature lands after it as the first solid. A sketch
    // on the old Body's origin is relinked to the new one's (insertObject); one on a face of the
    // old part keeps it, a direct reference
    // The feature's Merge first: its parts are parts again (Body::onChanged shows them)
    if (plan.merge) {
        const std::string name = plan.merge->getNameInDocument();
        body->removeObject(plan.merge);
        doc->removeObject(name.c_str());
    }
    // The last first, so the chain closes over each without rerouting what goes; then in order,
    // each solid after the one before it (Body::addObject)
    for (auto it = plan.moved.rbegin(); it != plan.moved.rend(); ++it) {
        body->removeObject(*it);
    }
    for (App::DocumentObject* obj : plan.moved) {
        part->addObject(obj);
    }
    // A dress-up whose Base the reroute couldn't carry keeps it in the other part, while it
    // computes on its new BaseFeature: cleared, so it fails until it is re-picked, never on the
    // other shape's element of the same index (fix review F2)
    for (Body* each : {body, part}) {
        for (App::DocumentObject* member : each->Group.getValues()) {
            auto dressUp = freecad_cast<DressUp*>(member);
            App::DocumentObject* base = dressUp ? dressUp->Base.getValue() : nullptr;
            if (base && base != dressUp->BaseFeature.getValue() && findBodyOf(base) != each) {
                Base::Console().warning("%s: New part couldn't carry its references to %s; "
                                        "re-pick them\n",
                                        dressUp->Label.getValue(),
                                        base->Label.getValue());
                dressUp->Base.setValue(nullptr);
                if (!dressUp->BaseFeature.getValue()) {
                    each->setBaseProperty(dressUp);
                }
            }
        }
    }
    // Onshape's New has no merge scope (ops#640 rank 1): the feature is its new part's first solid
    if (auto addSub = freecad_cast<FeatureAddSub*>(feature)) {
        if (addSub->EmptyMergeScope.getValue()) {
            addSub->EmptyMergeScope.setValue(false);
        }
        if (addSub->MergeWithAll.getValue()) {
            addSub->MergeWithAll.setValue(false);
        }
    }
    return part;
}

Body* Body::addToPart(App::DocumentObject* feature, Body* target)
{
    // Every refusal before anything is written (addToPartRefusal, which the dialog's rows read)
    const std::string why = addToPartRefusal(feature, target);
    if (!why.empty()) {
        throw Base::ValueError("Add to part: " + why);
    }
    Body* body = findBodyOf(feature);
    // Every member of its Body, after the target's last member before the feature in the
    // studio's history (planAddToPart)
    const AddToPartPlan plan = planAddToPart(feature, body, target);
    App::Document* doc = feature->getDocument();
    const std::vector<App::DocumentObject*>& group = target->Group.getValues();
    App::DocumentObject* after = plan.after;
    // The target's last solid comes before it: the last moved solid is the new Tip, else they go
    // in mid-history
    auto afterIt = after ? std::ranges::find(group, after) : group.begin();
    if (after) {
        ++afterIt;
    }
    const bool last = std::none_of(afterIt, group.end(), isSolidFeature);

    // Out of the Body, the last first, so its chain closes over nothing that goes; then in order,
    // each after the one before it: each solid on the solid before it (Body::insertObject), the
    // feature on the target's, the target's next solid on the last one. A link to the Body's
    // origin is relinked to the target's, as moveBack's insert does
    for (auto it = plan.moved.rbegin(); it != plan.moved.rend(); ++it) {
        body->removeObject(*it);
    }
    App::DocumentObject* lastSolid = nullptr;
    for (App::DocumentObject* obj : plan.moved) {
        target->insertObject(obj, after, /*after = */ true);
        after = obj;
        if (isSolidFeature(obj)) {
            lastSolid = obj;
        }
    }
    if (last && lastSolid) {
        target->Tip.setValue(lastSolid);
        // the part shows its new Tip alone, as Body::addObject() does
        for (App::DocumentObject* obj : target->Group.getValues()) {
            if (obj != lastSolid && obj->isDerivedFrom<PartDesign::Feature>()
                && obj->Visibility.getValue()) {
                obj->Visibility.setValue(false);
            }
        }
        lastSolid->Visibility.setValue(true);
    }
    else {
        for (App::DocumentObject* obj : plan.moved) {
            if (isSolidFeature(obj)) {
                obj->Visibility.setValue(false);
            }
        }
    }
    // The history as the target now holds them (review R9-5): the moved members together at the
    // feature's place, so a member before it (its sketch, drawn before the target's rows) isn't
    // ranked before the rows it now follows
    std::vector<App::DocumentObject*> order;
    std::vector<App::DocumentObject*> block;
    std::size_t at = 0;
    bool seen = false;
    for (App::DocumentObject* obj : plan.sequence) {
        if (obj == feature) {
            at = order.size();
            seen = true;
        }
        if (std::ranges::find(plan.moved, obj) == plan.moved.end()) {
            order.push_back(obj);
        }
    }
    for (App::DocumentObject* obj : plan.moved) {
        if (std::ranges::find(plan.sequence, obj) != plan.sequence.end()) {
            block.push_back(obj);
        }
    }
    if (!seen) {
        at = order.size();
    }
    order.insert(order.begin() + static_cast<std::ptrdiff_t>(at), block.begin(), block.end());
    saveHistoryOrder(order);
    // The Body it left is empty now: it goes, with its origin
    doc->removeObject(body->getNameInDocument());
    return target;
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


    // An insert at the studio's rolled-back bar is listed right after the bar, above what it holds
    // (FreeCAD-CH ops#632, notes/part-history-design.md 3.3): the order before it, and its bar
    App::Part* studio = nullptr;
    auto doc = getDocument();
    bool atStudioBar = doc && !doc->isPerformingTransaction() && !isRestoring()
        && studioOf(this, studio) && isStudioRolledBack(doc, studio);
    std::vector<App::DocumentObject*> history;
    App::DocumentObject* studioBar = nullptr;
    if (atStudioBar) {
        history = studioSequence(doc, studio);
        studioBar = studioBarAfter(history);
    }

    // Rolled back: a member that waits with the held features (waitsBelowBar()), listed after the
    // studio's bar when there is one: the insert goes before it, as Onshape inserts a new feature
    // at the bar, above the held rows' sketches (FreeCAD-CH ops#640 rank 34, blind test F42). One
    // listed above the studio's bar is live there, and the insert goes after it, as before
    auto waits = [&](App::DocumentObject* obj) {
        if (obj == feature || !waitsBelowBar(obj)) {
            return false;
        }
        if (!atStudioBar || !studioBar) {
            return true;
        }
        auto barPos = std::ranges::find(history, studioBar);
        auto pos = std::ranges::find(history, obj);
        return barPos != history.end() && pos != history.end() && pos > barPos;
    };
    const auto& features = Group.getValues();
    App::DocumentObject* next = nullptr;
    auto from = features.begin();
    if (Tip.getValue()) {
        next = getNextSolidFeature();
        from = std::ranges::find(features, Tip.getValue());
        if (from != features.end()) {
            ++from;
        }
    }
    else {
        // The bar at the top (ops#127): before the first solid feature
        auto it = std::find_if(features.begin(), features.end(), isSolidFeature);
        next = it == features.end() ? nullptr : *it;
    }
    if (next) {
        for (auto it = from; it != features.end() && *it != next; ++it) {
            if (waits(*it)) {
                next = *it;
                break;
            }
        }
    }
    insertObject(feature, next, /*after = */ false);
    if (atStudioBar) {
        saveInsertAtBar(doc, studio, history, studioBar, feature);
    }
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
    // In the Group: hasObject() also counts the Origin and its features, which have no place in
    // it, so an insert next to them went past its end (FreeCAD-CH ops#597)
    if (target && std::ranges::find(Group.getValues(), target) == Group.getValues().end()) {
        throw Base::ValueError(
            "Body: the feature we should insert relative to is not part of that body"
        );
    }

    // ensure that all origin links are ok. Not a shape binder's that traces its support
    // (FreeCAD-CH ops#244): it binds another container's origin feature where that one is, so
    // the relink to this body's own made it bind another plane or axis, silently. Also one of its
    // own body's plane moved to another body (PR 246 review L2): it keeps binding that plane, where
    // it is (PartDesign_MoveFeature takes it out of its body first, so the body it leaves isn't
    // known here)
    auto* binder = freecad_cast<ShapeBinder*>(feature);
    if (!binder || !binder->TraceSupport.getValue()) {
        relinkToOrigin(feature);
    }

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

    // The Merge that is the feature's merge scope goes with it, so its parts are parts again, as
    // when an Onshape Extrude is deleted (ops#640 rank 1; Boolean::scopeMerge). First, so the
    // chain below is rerouted past both. A move out of the Body (newPartFrom, addToPart) is
    // refused before it gets here while the Merge uses the feature
    if (hasObject(feature)) {
        if (Boolean* merge = Boolean::scopeMerge(feature); merge && hasObject(merge)) {
            if (App::Document* doc = merge->getDocument()) {
                const std::string name = merge->getNameInDocument();
                removeObject(merge);
                doc->removeObject(name.c_str());
            }
        }
    }

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
    // a reorder's reroute: without the solver, a link that finds no match on its new base goes
    // to it with its references missing (ops#291)
    reorderBody(*this, objs, target, after, [this](App::DocumentObject* f, App::DocumentObject* b) {
        rerouteBase(f, b, true);
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
            if (tip->isError() || tip->isDerivedFrom<DeletePart>() || DeletePart::deleterOf(this)) {
                // A failed first feature passed an empty base through, or the part is deleted
                // (ops#635): the Body is empty and valid (ops#126)
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

void Body::writeStoppedShape()
{
    // The next run copies its Tip again (execute() compares with the last copy)
    lastTipShape = Part::TopoShape();
    if (Shape.getShape().isNull()) {
        // Stopped already: nothing is written, so nothing re-solves a reference into it
        return;
    }
    // Inside the Recompute status, as execute() writes it: Part::Feature::onChanged doesn't take
    // the empty shape's identity location for the Placement
    Base::ObjectStatusLocker<App::ObjectStatus, App::DocumentObject> exe(App::Recompute, this);
    Shape.setValue(Part::TopoShape());
}

void Body::onSettingDocument()
{

    if (connection.connected()) {
        connection.disconnect();
    }

    Part::BodyBase::onSettingDocument();
}

namespace
{
// A reader of a solid the bar holds (in another Body, or a member B1x lets go) gets a warning when
// it recomputes (DocumentObject::recompute, FreeCAD-CH ops#325): it reads the solid's last result.
// A bar move changes what is held, so rerun the readers whose warning no longer matches: those in
// its in-list and those reading it through a subname path
void touchHeldSolidReaders(const Body& body)
{
    auto doc = body.getDocument();
    for (auto feature : body.Group.getValues()) {
        if (!Body::isSolidFeature(feature)) {
            continue;
        }
        std::optional<bool> held;
        auto readers = feature->getInList();
        auto pathReaders = App::subnamePathReaders(feature);
        readers.insert(readers.end(), pathReaders.begin(), pathReaders.end());
        for (auto reader : readers) {
            if (!reader || reader == &body) {
                continue;
            }
            if (!held) {
                held = body.holds(feature);
            }
            auto warning = doc ? doc->getWarningDescription(reader) : nullptr;
            bool warned = warning && std::strstr(warning, "which a roll-back bar holds");
            // A member the bar holds doesn't run (a member B1x lets go does, as a reader outside)
            if (*held != warned && !(body.hasObject(reader) && body.holds(reader))) {
                reader->enforceRecompute();
            }
        }
    }
}
}  // namespace

void Body::onChanged(const App::Property* prop)
{
    if (prop == &Tip && !isRestoring() && getDocument()) {
        touchHeldSolidReaders(*this);
    }
    if (prop->getName() && std::strcmp(prop->getName(), "MergedInto") == 0 && !isRestoring()
        && getDocument()) {
        // Merged into another part, or unmerged by deleting the Merge, by undo and redo too
        // (FreeCAD-CH ops#325, design 2.6, PR 305 round 1): its solids after the merged feature
        // fail, or compute again, and nothing else runs them. Unmerged, it shows again (undo
        // and redo put Visibility back themselves)
        for (auto feature : Group.getValues()) {
            if (isSolidFeature(feature)) {
                feature->touch();
            }
        }
        if (!getDocument()->isPerformingTransaction()
            && !static_cast<const App::PropertyLinkHidden*>(prop)->getValue()) {
            Visibility.setValue(true);
        }
    }
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
                // The copy starts where its source is, and follows it from there (FreeCAD-CH
                // ops#322). Set the Body placement before assigning BaseFeature to keep the
                // source's global position. For a feature of a Body only that Body's placement
                // applies (ops#308 T5: a box at (5, 5, 5) was copied to (10, 10, 10))
                if (auto frame = bf->sourceFrame()) {
                    bf->Placement.setValue(*frame);
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
