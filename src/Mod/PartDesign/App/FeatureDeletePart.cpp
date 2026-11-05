// SPDX-License-Identifier: LGPL-2.1-or-later

#include "FeatureDeletePart.h"

#include <algorithm>
#include <vector>

#include <App/Document.h>
#include <App/Part.h>
#include <Base/Exception.h>

#include "Body.h"
#include "Studio.h"

using namespace PartDesign;

PROPERTY_SOURCE(PartDesign::DeletePart, PartDesign::Feature)

namespace
{
std::string quoted(const App::DocumentObject* obj)
{
    return std::string("'") + (obj ? obj->Label.getValue() : "?") + "'";
}
}  // namespace

DeletePart::DeletePart() = default;

App::DocumentObjectExecReturn* DeletePart::execute()
{
    // The part is gone from here on: the Body is empty (Body::execute)
    Shape.setValue(Part::TopoShape());
    return App::DocumentObject::StdReturn;
}

DeletePart* DeletePart::deleterOf(const Body* body)
{
    return body ? freecad_cast<DeletePart*>(body->Tip.getValue()) : nullptr;
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
    auto feature = static_cast<DeletePart*>(
        body->getDocument()->addObject("PartDesign::DeletePart", "DeletePart")
    );
    feature->Label.setValue(std::string("Delete ") + body->Label.getValue());
    // At the bar, as the Tip, its base the solid before it (Body::insertObject)
    body->addObject(feature);
    return feature;
}

std::string DeletePart::deleteLock(const App::DocumentObject* feature)
{
    auto doc = feature ? feature->getDocument() : nullptr;
    if (!doc || doc->countObjectsOfType<DeletePart>() == 0) {
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
            if (obj && obj->isDerivedFrom<DeletePart>()) {
                return quoted(body) + " was deleted by " + quoted(obj)
                    + "; this feature comes after it. Move it before " + quoted(obj)
                    + ", or delete " + quoted(obj);
            }
        }
    }
    // A part deleted before this feature in history (Onshape: the reference breaks)
    std::vector<App::DocumentObject*> sequence;
    bool sequenced = false;
    for (auto read : readsOfOtherBodies(feature)) {
        auto other = freecad_cast<Body*>(read);
        if (!other) {
            other = Body::findBodyOf(read);
        }
        DeletePart* deleter = deleterOf(other);
        if (!deleter) {
            continue;
        }
        if (!sequenced) {
            App::Part* studio = nullptr;
            Part::BodyBase::studioOf(body, studio);
            sequence = studioSequence(doc, studio);
            sequenced = true;
        }
        auto here = std::ranges::find(sequence, feature);
        auto there = std::ranges::find(sequence, deleter);
        if (here != sequence.end() && there != sequence.end() && there < here) {
            std::string what = read == other ? quoted(other) : quoted(read) + " of " + quoted(other);
            return "This feature uses " + what + ", which " + quoted(deleter)
                + " deleted before it. Repoint it, or move it before " + quoted(deleter);
        }
    }
    return {};
}
