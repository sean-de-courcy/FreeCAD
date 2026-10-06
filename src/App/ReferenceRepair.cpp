// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ReferenceRepair.h"

#include <algorithm>
#include <vector>

#include <Base/Exception.h>

#include "ComplexGeoData.h"
#include "Document.h"
#include "DocumentObject.h"
#include "ElementNamingUtils.h"
#include "ElementSolverBatch.h"
#include "GeoFeature.h"
#include "PropertyLinks.h"
#include "ReferenceReport.h"

namespace App
{

namespace
{

// One reference of a property as the picker's calls need it.
struct Reference
{
    DocumentObject* obj = nullptr;
    std::vector<std::string> subs;
    std::vector<PropertyLinkBase::ShadowSub> shadows;
    std::vector<GuessRecord> guesses;
    /// The sub-object path before the element, e.g. `Body.Pad.` (often empty).
    std::string prefix;
};

Reference referenceOf(PropertyLinkBase* prop, int index)
{
    Reference reference;
    if (auto link = freecad_cast<PropertyLinkSub*>(prop)) {
        reference.obj = link->getValue();
        reference.subs = link->getSubValues();
        reference.shadows = link->getShadowSubs();
    }
    else if (auto list = freecad_cast<PropertyLinkSubList*>(prop)) {
        const auto& objs = list->getValues();
        reference.obj = index >= 0 && index < static_cast<int>(objs.size()) ? objs[index] : nullptr;
        reference.subs = list->getSubValues();
        reference.shadows = list->getShadowSubs();
    }
    else if (auto xlink = freecad_cast<PropertyXLink*>(prop)) {
        reference.obj = xlink->getValue();
        reference.subs = xlink->getSubValues();
        reference.shadows = xlink->getShadowSubs();
    }
    if (!prop || !reference.obj || index < 0 || index >= static_cast<int>(reference.subs.size())) {
        throw Base::ValueError("No such element reference");
    }
    reference.shadows.resize(reference.subs.size());
    reference.guesses = prop->getElementGuesses();
    reference.guesses.resize(reference.subs.size());
    const std::string& sub = reference.subs[index];
    const char* element = Data::findElementName(sub.c_str());
    reference.prefix = element ? sub.substr(0, element - sub.c_str()) : std::string();
    return reference;
}

// The owner of a property (a PropertyXLinkSubList's link has its list's).
DocumentObject* ownerOf(const PropertyLinkBase* prop)
{
    if (auto xlink = freecad_cast<const PropertyXLink*>(prop)) {
        if (!xlink->getContainer() && xlink->parent()) {
            prop = xlink->parent();
        }
    }
    return prop ? freecad_cast<DocumentObject*>(prop->getContainer()) : nullptr;
}

// Writes \a resolutions as the solver does, then drops the report, clears the owner's warning and
// touches the owner, whose next recompute derives its state anew.
void apply(PropertyLinkBase* prop, const Reference& reference, std::vector<SolverResolution> list)
{
    DocumentObject* feature = reference.prefix.empty()
        ? reference.obj
        : reference.obj->getSubObject(reference.prefix.c_str());
    if (!feature) {
        throw Base::RuntimeError("Cannot find " + reference.prefix + " in "
                                 + reference.obj->getFullName());
    }
    for (auto& resolution : list) {
        resolution.prop = prop;
        resolution.feature = feature;
        resolution.notify = true;
    }
    prop->applyResolutions(list);
    // As a setter does: the report on the property is stale now.
    ReferenceReport::clear(prop);
    if (auto owner = ownerOf(prop)) {
        if (auto doc = owner->getDocument()) {
            doc->clearWarning(owner);
        }
        owner->touch();
    }
}

// The references of \a prop that hold the same record as reference \a index (the pieces of an
// expanded one), \a index first; just \a index when it has none.
std::vector<int> sameRecord(const Reference& reference, int index)
{
    std::vector<int> indices {index};
    const GuessRecord& guess = reference.guesses[index];
    if (guess.empty()) {
        return indices;
    }
    for (int i = 0; i < static_cast<int>(reference.guesses.size()); ++i) {
        if (i != index && reference.guesses[i] == guess) {
            indices.push_back(i);
        }
    }
    return indices;
}

}  // namespace

void acceptReference(PropertyLinkBase* prop, int localIndex)
{
    Reference reference = referenceOf(prop, localIndex);
    if (reference.guesses[localIndex].empty()) {
        throw Base::ValueError("The element reference holds no guess to accept");
    }
    std::vector<SolverResolution> list;
    for (int i : sameRecord(reference, localIndex)) {
        if (Data::hasMissingElement(reference.subs[i].c_str())) {
            continue;  // nothing to take
        }
        // The reference as it is, without the record: its fingerprint is measured anew.
        SolverResolution resolution;
        resolution.status = SolverResolution::Status::Resolved;
        resolution.index = i;
        resolution.sub = reference.subs[i];
        resolution.shadow = reference.shadows[i];
        list.push_back(std::move(resolution));
    }
    if (list.empty()) {
        throw Base::ValueError("The guessed element is missing");
    }
    apply(prop, reference, std::move(list));
}

void repairReference(PropertyLinkBase* prop,
                     int localIndex,
                     const std::string& candidate,
                     bool force)
{
    Reference reference = referenceOf(prop, localIndex);
    const GuessRecord& guess = reference.guesses[localIndex];
    bool listed = force;
    std::string mappedName;
    if (auto entry = ReferenceReport::find(prop, localIndex)) {
        for (const auto& c : entry->candidates) {
            if (c.first == candidate) {
                listed = true;
                mappedName = c.second;
                break;
            }
        }
    }
    listed = listed || candidate == guess.origIndex
        || std::any_of(guess.alternatives.begin(),
                       guess.alternatives.end(),
                       [&](const GuessRecord::Alternative& a) { return a.index == candidate; });
    if (!listed) {
        throw Base::ValueError(candidate + " is not a candidate of the element reference");
    }
    // The candidate's current mapped name, from the target (a candidate the report doesn't list).
    ElementNamePair found;
    const char* element = nullptr;
    GeoFeature* geo = nullptr;
    const std::string path = reference.prefix + candidate;
    if (!GeoFeature::resolveElement(reference.obj,
                                    path.c_str(),
                                    found,
                                    true,
                                    GeoFeature::ElementNameType::Export,
                                    nullptr,
                                    &element,
                                    &geo)
        || !geo || !element || !element[0] || Data::hasMissingElement(found.oldName.c_str())) {
        throw Base::ValueError(candidate + " is not an element of "
                               + reference.obj->getFullName());
    }
    if (mappedName.empty()) {
        mappedName = bareMappedName(found.newName);
    }
    std::vector<SolverResolution> list;
    SolverResolution resolution;
    resolution.status = SolverResolution::Status::Resolved;
    resolution.index = localIndex;
    resolution.shadow.oldName = reference.prefix + candidate;
    if (!mappedName.empty()) {
        resolution.shadow.newName = reference.prefix + Data::ComplexGeoData::elementMapPrefix()
            + mappedName + "." + candidate;
    }
    resolution.sub = !resolution.shadow.newName.empty()
            && Data::hasMappedElementName(reference.subs[localIndex].c_str())
        ? resolution.shadow.newName
        : resolution.shadow.oldName;
    // The repaired reference loses its `from` and its record (and the other pieces of the same
    // record go: one element replaces them, in a PropertyLinkSub, the only one with pieces). A
    // repair is the user's pick, so a reorder's re-target record ends too: a later move back
    // mustn't overwrite it (ops#127).
    resolution.clearFrom = true;
    resolution.clearRetarget = true;
    list.push_back(resolution);
    if (freecad_cast<PropertyLinkSub*>(prop)) {
        auto indices = sameRecord(reference, localIndex);
        for (std::size_t k = 1; k < indices.size(); ++k) {
            SolverResolution removed;
            removed.status = SolverResolution::Status::Removed;
            removed.index = indices[k];
            list.push_back(removed);
        }
    }
    apply(prop, reference, std::move(list));
}

void markReferenceBroken(PropertyLinkBase* prop, int localIndex)
{
    Reference reference = referenceOf(prop, localIndex);
    const GuessRecord guess = reference.guesses[localIndex];
    if (guess.empty()) {
        throw Base::ValueError("The element reference holds no guess to mark broken");
    }
    std::vector<SolverResolution> list;
    // The original, missing, as the solver breaks a guess: the owner fails with it. The record
    // becomes a rejection: the solver never offers the rejected elements for it again, and the
    // fingerprint (the rejected element's) goes, so geometry can't find it either. The original's
    // name coming back still snaps it back.
    GuessRecord rejected;
    rejected.kind = "rejected";
    rejected.origName = guess.origName;
    rejected.origIndex = guess.origIndex;
    if (guess.kind == "rejected") {
        rejected.alternatives = guess.alternatives;
    }
    for (int i : sameRecord(reference, localIndex)) {
        const char* element = Data::findElementName(reference.subs[i].c_str());
        if (element && element[0] && !Data::hasMissingElement(element)) {
            GuessRecord::Alternative alternative;
            alternative.index = element;
            alternative.role = "rejected";
            rejected.alternatives.push_back(std::move(alternative));
        }
    }
    SolverResolution resolution;
    resolution.status = SolverResolution::Status::Broken;
    resolution.index = localIndex;
    resolution.guess = std::move(rejected);
    resolution.clearFingerprint = true;
    if (!guess.origName.empty()) {
        resolution.shadow.newName = reference.prefix + Data::ComplexGeoData::elementMapPrefix()
            + guess.origName + "." + guess.origIndex;
    }
    resolution.shadow.oldName = reference.prefix + Data::MISSING_PREFIX + guess.origIndex;
    resolution.sub = !resolution.shadow.newName.empty()
            && Data::hasMappedElementName(reference.subs[localIndex].c_str())
        ? resolution.shadow.newName
        : resolution.shadow.oldName;
    list.push_back(resolution);
    if (freecad_cast<PropertyLinkSub*>(prop)) {
        auto indices = sameRecord(reference, localIndex);
        for (std::size_t k = 1; k < indices.size(); ++k) {
            SolverResolution removed;
            removed.status = SolverResolution::Status::Removed;
            removed.index = indices[k];
            list.push_back(removed);
        }
    }
    apply(prop, reference, std::move(list));
}

}  // namespace App
