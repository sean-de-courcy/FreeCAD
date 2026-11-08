// SPDX-License-Identifier: LGPL-2.1-or-later

// Onshape's Derived feature inside one document (FreeCAD-CH ops#640 round 6): Derived.h

#include <algorithm>
#include <set>
#include <string>
#include <vector>

#include <App/Document.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/GroupExtension.h>
#include <App/Part.h>
#include <Base/Exception.h>
#include <Mod/Part/App/BodyBase.h>
#include <Mod/Part/App/PartFeature.h>

#include "Body.h"
#include "Derived.h"
#include "FeatureBase.h"
#include "FeatureDeletePart.h"
#include "ShapeBinder.h"
#include "Studio.h"

namespace PartDesign
{

namespace
{

/// The binder a member copies
SubShapeBinder* binderOf(const FeatureBase* member)
{
    return member ? freecad_cast<SubShapeBinder*>(member->BaseFeature.getValue()) : nullptr;
}

/// "Derived N", the lowest N no object of doc has as its label
std::string freeLabel(App::Document* doc)
{
    std::set<std::string> labels;
    for (auto obj : doc->getObjects()) {
        labels.insert(obj->Label.getValue());
    }
    for (int n = 1;; ++n) {
        std::string label = "Derived " + std::to_string(n);
        if (!labels.count(label)) {
            return label;
        }
    }
}

/// The studio of a Body, or throws for one in no studio (an Assembly's)
App::Part* studioOfBody(const Body* body)
{
    App::Part* studio = nullptr;
    if (!Part::BodyBase::studioOf(body, studio)) {
        throw Base::ValueError("Derived: the part isn't in a part studio");
    }
    return studio;
}

/// The refusals of makeDerived() and editDerived(), before anything is written
void checkSources(App::Document* doc, App::Part* studio, const std::vector<Body*>& sources)
{
    if (sources.empty()) {
        throw Base::ValueError("Derived: choose the parts to derive");
    }
    App::Part* from = nullptr;
    for (std::size_t i = 0; i < sources.size(); ++i) {
        Body* source = sources[i];
        if (!source || !source->isAttachedToDocument() || source->getDocument() != doc) {
            throw Base::ValueError("Derived: the parts must be parts of this document");
        }
        App::Part* sourceStudio = studioOfBody(source);
        if (sourceStudio == studio) {
            throw Base::ValueError("Derived: the parts must come from another part studio");
        }
        if (i > 0 && sourceStudio != from) {
            throw Base::ValueError("Derived: the parts must come from one part studio");
        }
        from = sourceStudio;
        if (std::count(sources.begin(), sources.end(), source) > 1) {
            throw Base::ValueError("Derived: a part is chosen twice");
        }
    }
}

/// A new member labelled label in studio copying source: its binder, and its Body labelled as the
/// source
FeatureBase* addMember(App::Document* doc, App::Part* studio, Body* source, const std::string& label)
{
    auto binder = doc->addObject<SubShapeBinder>("DerivedSource");
    if (studio) {
        studio->addObject(binder);
    }
    binder->Label.setValue(label + " source");
    binder->Support.setValue(source);
    binder->Visibility.setValue(false);
    binder->recomputeFeature();

    auto body = doc->addObject<Body>("Body");
    if (studio) {
        studio->addObject(body);
    }
    body->Label.setValue(source->Label.getValue());

    auto member = doc->addObject<FeatureBase>("Derived");
    member->Label.setValue(label);
    member->DerivedFrom.setValue(derivedDescription(source));
    // Body::addObject puts it at the studio's bar when the studio is rolled back (Onshape inserts
    // a feature at the bar); then the Body takes it as its base feature (Body::onChanged)
    body->addObject(member);
    body->BaseFeature.setValue(binder);
    // The copy starts where its source is, as Body::onChanged places a base feature it makes
    if (auto frame = member->sourceFrame()) {
        member->Placement.setValue(*frame);
    }
    return member;
}

/// Removes a member, its binder and its Body when nothing else is left in it
void removeMember(FeatureBase* member)
{
    App::Document* doc = member->getDocument();
    SubShapeBinder* binder = binderOf(member);
    Body* body = Body::findBodyOf(member);
    if (body) {
        body->removeObject(member);
    }
    doc->removeObject(member->getNameInDocument());
    if (body && body->Group.getValues().empty()) {
        doc->removeObject(body->getNameInDocument());
    }
    // The binder, when nothing but its container reads it any more
    if (binder && binder->isAttachedToDocument()) {
        bool used = std::ranges::any_of(binder->getInList(), [](App::DocumentObject* in) {
            return in && !in->hasExtension(App::GroupExtension::getExtensionClassTypeId());
        });
        if (!used) {
            doc->removeObject(binder->getNameInDocument());
        }
    }
}

}  // namespace

std::vector<App::Part*> derivedStudios(App::Document* doc)
{
    std::vector<App::Part*> studios;
    if (!doc) {
        return studios;
    }
    if (!derivableParts(doc, nullptr).empty()) {
        studios.push_back(nullptr);
    }
    for (auto obj : doc->getObjectsOfType(App::Part::getClassTypeId())) {
        auto part = static_cast<App::Part*>(obj);
        if (!derivableParts(doc, part).empty()) {
            studios.push_back(part);
        }
    }
    return studios;
}

std::string studioLabel(const App::Part* studio)
{
    return studio ? std::string(studio->Label.getValue()) : std::string("Part Studio 1");
}

std::vector<Body*> derivableParts(App::Document* doc, App::Part* studio)
{
    std::vector<Body*> parts;
    for (auto body : studioBodies(doc, studio)) {
        if (!body->Shape.getShape().isNull() && !DeletePart::deleterOf(body)) {
            parts.push_back(body);
        }
    }
    return parts;
}

std::string derivedDescription(const App::DocumentObject* source)
{
    if (!source) {
        return {};
    }
    App::Part* studio = nullptr;
    Part::BodyBase::studioOf(Part::BodyBase::bodyOfObject(source), studio);
    return std::string(source->Label.getValue()) + " (" + studioLabel(studio) + ")";
}

bool isDerived(const App::DocumentObject* obj)
{
    auto base = freecad_cast<const FeatureBase*>(obj);
    return base && !base->DerivedFrom.getStrValue().empty();
}

FeatureBase* derivedLead(const App::DocumentObject* obj)
{
    if (!isDerived(obj)) {
        return nullptr;
    }
    auto member = const_cast<FeatureBase*>(static_cast<const FeatureBase*>(obj));
    for (auto in : member->getInList()) {
        auto lead = freecad_cast<FeatureBase*>(in);
        if (lead && isDerived(lead)) {
            const auto& parts = lead->DerivedParts.getValues();
            if (std::ranges::find(parts, member) != parts.end()) {
                return lead;
            }
        }
    }
    return member;
}

std::vector<FeatureBase*> derivedMembers(FeatureBase* lead)
{
    std::vector<FeatureBase*> members;
    if (!lead) {
        return members;
    }
    for (auto obj : lead->DerivedParts.getValues()) {
        auto member = freecad_cast<FeatureBase*>(obj);
        if (member && member != lead && std::ranges::find(members, member) == members.end()) {
            members.push_back(member);
        }
    }
    members.push_back(lead);
    return members;
}

App::DocumentObject* derivedSource(const FeatureBase* member)
{
    SubShapeBinder* binder = binderOf(member);
    if (!binder) {
        return nullptr;
    }
    for (auto obj : binder->Support.getValues()) {
        if (obj && obj->isAttachedToDocument()) {
            return obj;
        }
    }
    return nullptr;
}

FeatureBase* makeDerived(App::Document* doc, App::Part* studio, const std::vector<Body*>& sources)
{
    if (!doc) {
        throw Base::ValueError("Derived: no document");
    }
    checkSources(doc, studio, sources);
    const std::string label = freeLabel(doc);
    // The others are labelled by their source; the last one made is the lead
    std::vector<FeatureBase*> members;
    for (std::size_t i = 0; i < sources.size(); ++i) {
        Body* source = sources[i];
        const bool last = i + 1 == sources.size();
        members.push_back(
            addMember(doc, studio, source, last ? label : label + " (" + source->Label.getValue() + ")")
        );
    }
    FeatureBase* lead = members.back();
    members.pop_back();
    lead->DerivedParts.setValues(std::vector<App::DocumentObject*>(members.begin(), members.end()));
    return lead;
}

FeatureBase* editDerived(FeatureBase* lead, const std::vector<Body*>& sources)
{
    if (!lead || !isDerived(lead) || derivedLead(lead) != lead) {
        throw Base::ValueError("Derived: not a Derived feature");
    }
    Body* leadBody = Body::findBodyOf(lead);
    App::Part* studio = nullptr;
    if (!leadBody || !Part::BodyBase::studioOf(leadBody, studio)) {
        throw Base::ValueError("Derived: the feature isn't in a part studio");
    }
    App::Document* doc = lead->getDocument();
    checkSources(doc, studio, sources);
    const std::string label = lead->Label.getValue();

    std::vector<FeatureBase*> kept;
    std::vector<FeatureBase*> dropped;
    std::vector<App::DocumentObject*> covered;
    for (FeatureBase* member : derivedMembers(lead)) {
        App::DocumentObject* source = derivedSource(member);
        bool stays = source && std::ranges::find(sources, source) != sources.end()
            && std::ranges::find(covered, source) == covered.end();
        if (stays) {
            kept.push_back(member);
            covered.push_back(source);
        }
        else {
            dropped.push_back(member);
        }
    }
    if (dropped.empty() && kept.size() == sources.size()) {
        return lead;
    }
    for (Body* source : sources) {
        if (std::ranges::find(covered, source) == covered.end()) {
            kept.push_back(addMember(doc, studio, source, label + " (" + source->Label.getValue() + ")"));
        }
    }
    // The lead stays the lead while it keeps its part; else the last member left takes over, after
    // the old one is gone (its label is free then)
    FeatureBase* newLead = std::ranges::find(kept, lead) != kept.end() ? lead : kept.back();
    std::vector<App::DocumentObject*> others;
    for (FeatureBase* member : kept) {
        if (member != newLead) {
            others.push_back(member);
        }
    }
    if (newLead != lead) {
        lead->DerivedParts.setValues(std::vector<App::DocumentObject*>());
    }
    newLead->DerivedParts.setValues(others);
    for (FeatureBase* member : dropped) {
        removeMember(member);
    }
    if (newLead != lead) {
        newLead->Label.setValue(label);
    }
    return newLead;
}

void deleteDerivedParts(FeatureBase* lead)
{
    if (!lead || !isDerived(lead)) {
        return;
    }
    App::Document* doc = lead->getDocument();
    std::vector<FeatureBase*> others = derivedMembers(lead);
    others.pop_back();
    lead->DerivedParts.setValues(std::vector<App::DocumentObject*>());
    for (FeatureBase* member : others) {
        if (member->isAttachedToDocument()) {
            removeMember(member);
        }
    }
    // Lead's binder goes with lead (Std_Delete removes lead after this): taken out of the Body
    // first when lead is all it holds, so the Body can go too
    SubShapeBinder* binder = binderOf(lead);
    if (Body* body = Body::findBodyOf(lead)) {
        const auto& group = body->Group.getValues();
        if (group.size() == 1 && group.front() == lead) {
            body->removeObject(lead);
            doc->removeObject(body->getNameInDocument());
        }
    }
    if (binder && binder->isAttachedToDocument()) {
        bool used = std::ranges::any_of(binder->getInList(), [lead](App::DocumentObject* in) {
            return in && in != lead && !in->hasExtension(App::GroupExtension::getExtensionClassTypeId());
        });
        if (!used) {
            doc->removeObject(binder->getNameInDocument());
        }
    }
}

}  // namespace PartDesign
