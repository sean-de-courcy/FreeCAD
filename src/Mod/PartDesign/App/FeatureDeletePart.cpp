// SPDX-License-Identifier: LGPL-2.1-or-later

#include "FeatureDeletePart.h"

#include <algorithm>
#include <atomic>
#include <cstring>
#include <mutex>
#include <unordered_set>
#include <vector>

#include <App/Document.h>
#include <App/Part.h>
#include <Base/Exception.h>

#include "Body.h"
#include "FeatureBase.h"
#include "FeatureBoolean.h"
#include "Studio.h"

using namespace PartDesign;

PROPERTY_SOURCE(PartDesign::DeletePart, PartDesign::Feature)

namespace
{
std::string quoted(const App::DocumentObject* obj)
{
    return std::string("'") + (obj ? obj->Label.getValue() : "?") + "'";
}

// The words that mark deleteLock()'s failures (isDeleteLock())
constexpr const char* deletedBy = "' was deleted by '";
constexpr const char* deletedBefore = " deleted before it";
constexpr const char* deletedWhole = " deletes; point it at a feature";

// DeletePart objects alive in any document (an undone one too): none, and deleteLock() costs
// nothing in the recomputes and polls of files that have none
std::atomic<int> alive {0};

// The features whose last recompute failed on deleteLock(); compared by address only, never
// dereferenced (an object deleted while in it costs at most one extra recompute of a new one)
std::mutex lockedMutex;
std::unordered_set<const App::DocumentObject*> locked;
}  // namespace

void DeletePart::setLocked(const App::DocumentObject* feature, bool on)
{
    std::scoped_lock guard(lockedMutex);
    if (on) {
        locked.insert(feature);
    }
    else {
        locked.erase(feature);
    }
}

bool DeletePart::wasLocked(const App::DocumentObject* feature)
{
    std::scoped_lock guard(lockedMutex);
    return locked.count(feature) != 0;
}

DeletePart::DeletePart()
{
    ++alive;
}

DeletePart::~DeletePart()
{
    --alive;
}

App::DocumentObjectExecReturn* DeletePart::execute()
{
    // The part is gone from here on: the Body is empty (Body::execute)
    Shape.setValue(Part::TopoShape());
    return App::DocumentObject::StdReturn;
}

DeletePart* DeletePart::deleterOf(const Body* body)
{
    // Up to the bar: a feature added after it (which fails) doesn't bring the part back, and the
    // bar rolled above it does. A suppressed one deletes nothing, as in Onshape
    App::DocumentObject* tip = body ? body->Tip.getValue() : nullptr;
    if (!tip) {
        return nullptr;
    }
    for (auto obj : body->Group.getValues()) {
        auto deleter = freecad_cast<DeletePart*>(obj);
        if (deleter && !deleter->Suppressed.getValue()) {
            return deleter;
        }
        if (obj == tip) {
            break;
        }
    }
    return nullptr;
}

bool DeletePart::isDeleteLock(const char* why)
{
    return why
        && (std::strstr(why, deletedBy) || std::strstr(why, deletedBefore)
            || std::strstr(why, deletedWhole));
}

DeletePart* DeletePart::deletePart(Body* body)
{
    if (!body || !body->getDocument()) {
        throw Base::ValueError("Delete part: the object isn't a body");
    }
    if (deleterOf(body)) {
        throw Base::ValueError(
            "Delete part: " + quoted(body) + " is deleted already, by " + quoted(body->Tip.getValue())
        );
    }
    if (!body->Tip.getValue()) {
        throw Base::ValueError(
            "Delete part: " + quoted(body) + " has no solid feature above its bar, so it is no part"
        );
    }
    // Its shape is the surviving part's now (Onshape: a part a boolean consumed is gone)
    if (auto merge = Boolean::mergeOf(body)) {
        throw Base::ValueError(
            "Delete part: " + quoted(body) + " is merged by " + quoted(merge)
            + "; delete the Merge first, or delete the part it is merged into"
        );
    }
    auto feature = static_cast<DeletePart*>(
        body->getDocument()->addObject("PartDesign::DeletePart", "DeletePart")
    );
    feature->Label.setValue(std::string("Delete ") + body->Label.getValue());
    // At the bar, as the Tip, its base the solid before it (Body::insertObject)
    body->addObject(feature);
    return feature;
}

Body* DeletePart::removeEmptyPart(Body* body)
{
    App::Document* doc = body ? body->getDocument() : nullptr;
    App::Part* studio = nullptr;
    if (!doc || !Part::BodyBase::studioOf(body, studio)) {
        return nullptr;
    }
    const std::vector<App::DocumentObject*> members = body->Group.getValues();
    if (std::ranges::any_of(members, [](const App::DocumentObject* obj) {
            return Body::isSolidFeature(obj);
        })) {
        return nullptr;
    }
    std::vector<Body*> others = studioBodies(doc, studio);
    std::erase(others, body);
    // Only a Body placed as this one: relinked to another frame, its sketches would move in the
    // world without a word (review R7W-1); with none, the empty Body stays, as before
    std::erase_if(others, [body](const Body* other) {
        return !other->Placement.getValue().isSame(body->Placement.getValue(), 1e-9);
    });
    if (others.empty()) {
        return nullptr;
    }
    auto readOwner = [&]() -> Body* {
        for (App::DocumentObject* member : members) {
            for (App::DocumentObject* read : member->getOutList()) {
                Body* owner = Body::findBodyOf(read);
                if (owner && std::ranges::find(others, owner) != others.end()) {
                    return owner;
                }
            }
        }
        return others.front();
    };
    Body* target = readOwner();
    // Each after the target's last member listed before it (the base feature stays first)
    const std::vector<App::DocumentObject*> sequence = studioSequence(doc, studio);
    for (App::DocumentObject* member : members) {
        const std::vector<App::DocumentObject*>& group = target->Group.getValues();
        App::DocumentObject* after = nullptr;
        for (App::DocumentObject* obj : sequence) {
            if (obj == member) {
                break;
            }
            if (std::ranges::find(group, obj) != group.end()) {
                after = obj;
            }
        }
        if (!after && !group.empty() && group.front()->isDerivedFrom<FeatureBase>()) {
            after = group.front();
        }
        body->removeObject(member);
        // relinked to the target's origin, as addToPart's insert does
        target->insertObject(member, after, /*after = */ true);
    }
    saveHistoryOrder(sequence);
    doc->removeObject(body->getNameInDocument());
    return target;
}

std::string DeletePart::deleteLock(const App::DocumentObject* feature)
{
    auto doc = feature ? feature->getDocument() : nullptr;
    if (alive.load() == 0 || !doc || doc->countObjectsOfType<DeletePart>() == 0) {
        return {};
    }
    Body* body = Body::findBodyOf(feature);
    if (!body) {
        return {};
    }
    // After a DeletePart in its own Body: an Add to a part that no longer exists (Onshape errors;
    // computing on the empty shape would bring the part back without a word)
    if (Body::isSolidFeature(feature) && !feature->isDerivedFrom<DeletePart>()) {
        for (auto obj : body->Group.getValues()) {
            if (obj == feature) {
                break;
            }
            auto deleter = freecad_cast<DeletePart*>(obj);
            if (deleter && !deleter->Suppressed.getValue()) {
                return quoted(body) + " was deleted by " + quoted(obj)
                    + "; this feature comes after it. Move it before " + quoted(obj)
                    + ", or delete " + quoted(obj);
            }
        }
    }
    // A part deleted before this feature in history (Onshape: the reference breaks)
    std::vector<App::DocumentObject*> sequence;
    bool sequenced = false;
    std::vector<const App::DocumentObject*> via;
    const auto reads = readsOfOtherBodies(feature, &via);
    for (std::size_t i = 0; i < reads.size(); ++i) {
        auto read = reads[i];
        auto other = freecad_cast<Body*>(read);
        if (!other) {
            other = Body::findBodyOf(read);
        }
        DeletePart* deleter = deleterOf(other);
        if (!deleter) {
            continue;
        }
        // The whole Body (a Boolean's tool, a binder, a link) is read at its end, which is empty
        // now, whenever the reader was made: loud, as there is no part to read (Onshape keeps a
        // reader made before the delete valid: a known difference)
        if (read == other) {
            return "This feature uses the whole of " + quoted(other) + ", which " + quoted(deleter)
                + deletedWhole + " of " + quoted(other) + ", or delete " + quoted(deleter);
        }
        if (!sequenced) {
            App::Part* studio = nullptr;
            Part::BodyBase::studioOf(body, studio);
            sequence = studioSequence(doc, studio);
            sequenced = true;
        }
        // Where the read is made: the feature, or its sketch, datum or binder made before the
        // delete (Onshape: a sketch before the delete keeps its reference, and so does what uses it)
        auto here = std::ranges::find(sequence, via[i]);
        if (here == sequence.end()) {
            here = std::ranges::find(sequence, feature);
        }
        auto there = std::ranges::find(sequence, deleter);
        if (here != sequence.end() && there != sequence.end() && there < here) {
            return "This feature uses " + quoted(read) + " of " + quoted(other) + ", which "
                + quoted(deleter) + deletedBefore + ". Repoint it, or move it before "
                + quoted(deleter);
        }
    }
    return {};
}
