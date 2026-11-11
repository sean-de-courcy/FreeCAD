// SPDX-License-Identifier: LGPL-2.1-or-later

// Onshape's Derived feature inside one document (FreeCAD-CH ops#640 round 6): Derived.h

#include <algorithm>
#include <cmath>
#include <set>
#include <string>
#include <vector>

#include <Precision.hxx>

#include <App/Datums.h>
#include <App/Document.h>
#include <App/DocumentTabs.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/GroupExtension.h>
#include <App/Part.h>
#include <App/PropertyStandard.h>
#include <Base/Exception.h>
#include <Base/Placement.h>
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

/// What a member copies: its binder, or its copy of another document's part
App::DocumentObject* sourceHolderOf(const FeatureBase* member)
{
    if (auto binder = binderOf(member)) {
        return binder;
    }
    auto base = member ? member->BaseFeature.getValue() : nullptr;
    return isDerivedCopy(base) ? base : nullptr;
}

/// A dynamic string property of a derived copy, empty when it has none
std::string copyString(const App::DocumentObject* copy, const char* name)
{
    auto prop = copy ? freecad_cast<App::PropertyString*>(copy->getPropertyByName(name)) : nullptr;
    return prop ? std::string(prop->getValue()) : std::string();
}

/// Where a derived copy came from: its file and studio, the key that one Derived feature shares
std::string copyOrigin(const App::DocumentObject* copy)
{
    return copyString(copy, "DerivedSourcePath") + "|" + copyString(copy, "DerivedSourceStudio");
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

/// Whether obj is of studio's geometry: one of its Bodies, a Body's feature or origin, or, in an
/// App::Part studio, a shape it holds outside its Bodies (a Derived feature's binder). Containers,
/// origins and what isn't a shape (a VarSet, a sheet: usable from every studio) are of none
bool ofStudio(const App::DocumentObject* obj, const App::Part* studio)
{
    if (auto body = Part::BodyBase::bodyOfObject(obj)) {
        App::Part* part = nullptr;
        return Part::BodyBase::studioOf(body, part) && part == studio;
    }
    return studio && obj->isDerivedFrom<App::GeoFeature>()
        && !obj->hasExtension(App::GroupExtension::getExtensionClassTypeId())
        && !obj->isDerivedFrom<App::DatumElement>() && studio->hasObject(obj, true);
}

/// Where studio lies in the document: its Placement and its containers' (the top level: none)
Base::Placement studioPlacement(const App::Part* studio)
{
    Base::Placement placement;
    std::vector<const App::DocumentObject*> seen;
    for (const App::DocumentObject* frame = studio;
         frame && seen.size() < 100 && std::ranges::find(seen, frame) == seen.end();
         frame = App::GeoFeatureGroupExtension::getGroupOfObject(frame)) {
        seen.push_back(frame);
        if (auto geo = freecad_cast<const App::GeoFeature*>(frame)) {
            placement = geo->Placement.getValue() * placement;
        }
    }
    return placement;
}

/// Whether two placements are the same: positions within Precision::Confusion(), rotations by
/// their quaternions within 1e-12, either sign (as FeatureBase compares a source's frame)
bool samePlacement(const Base::Placement& a, const Base::Placement& b)
{
    if ((a.getPosition() - b.getPosition()).Length() > Precision::Confusion()) {
        return false;
    }
    double p[4];
    double q[4];
    a.getRotation().getValue(p[0], p[1], p[2], p[3]);
    b.getRotation().getValue(q[0], q[1], q[2], q[3]);
    auto within = [&](double sign) {
        for (int i = 0; i < 4; ++i) {
            if (std::abs(p[i] - sign * q[i]) > 1e-12) {
                return false;
            }
        }
        return true;
    };
    return within(1.0) || within(-1.0);
}

constexpr const char* historyRankName = "HistoryRank";

/// A member's history key, as studioSequence() reads it (Studio.cpp): its saved HistoryRank, else
/// its object id
double historyKey(const App::DocumentObject* obj)
{
    if (auto rank = freecad_cast<App::PropertyFloat*>(obj->getPropertyByName(historyRankName))) {
        return rank->getValue();
    }
    return static_cast<double>(obj->getID());
}

/// Gives obj the history key key, as saveHistoryOrder() saves one (Studio.cpp)
void setHistoryKey(App::DocumentObject* obj, double key)
{
    auto rank = freecad_cast<App::PropertyFloat*>(obj->getPropertyByName(historyRankName));
    if (!rank) {
        rank = static_cast<App::PropertyFloat*>(obj->addDynamicProperty(
            "App::PropertyFloat",
            historyRankName,
            "Base",
            "The place in its part studio's history, saved by a drag in the Features list or "
            "an insert at the bar (ops#632)",
            App::Prop_Output | App::Prop_Hidden
        ));
    }
    if (rank->getValue() != key) {
        rank->setValue(key);
    }
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
    const std::string problem = derivedPlacementProblem(doc, from, studio);
    if (!problem.empty()) {
        throw Base::ValueError(problem);
    }
    // A source that reads this studio would make the two studios read each other (review R6-1;
    // Onshape refuses a circular reference [guess])
    for (Body* source : sources) {
        for (App::DocumentObject* dep : source->getOutListRecursive()) {
            if (dep && dep != source && ofStudio(dep, studio)) {
                throw Base::ValueError(
                    "Derived: " + derivedDescription(source) + " depends on "
                    + dep->Label.getValue() + " of " + studioLabel(doc, studio)
                    + ": deriving it here would make a circular reference"
                );
            }
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

/// A new member labelled label in studio built on copy, a derived copy of another document's part
/// held in studio (derived-design.md 3): its Body labelled as the source part, the copy its base
FeatureBase* addCopyMember(App::Document* doc, App::Part* studio, Part::Feature* copy, const std::string& label)
{
    auto body = doc->addObject<Body>("Body");
    if (studio) {
        studio->addObject(body);
    }
    body->Label.setValue(derivedCopyLabel(copy));
    auto member = doc->addObject<FeatureBase>("Derived");
    member->Label.setValue(label);
    member->DerivedFrom.setValue(derivedDescription(copy));
    body->addObject(member);
    body->BaseFeature.setValue(copy);
    if (auto frame = member->sourceFrame()) {
        member->Placement.setValue(*frame);
    }
    return member;
}

/// The refusals of makeDerivedCopies() and editDerivedCopies(), before anything is written
void checkCopies(App::Document* doc, App::Part* studio, const std::vector<Part::Feature*>& copies)
{
    if (copies.empty()) {
        throw Base::ValueError("Derived: choose the parts to derive");
    }
    for (std::size_t i = 0; i < copies.size(); ++i) {
        Part::Feature* copy = copies[i];
        if (!copy || !copy->isAttachedToDocument() || copy->getDocument() != doc
            || !isDerivedCopy(copy)) {
            throw Base::ValueError("Derived: the copies must be derived copies of this document");
        }
        if (App::GeoFeatureGroupExtension::getGroupOfObject(copy) != studio) {
            throw Base::ValueError("Derived: a copy must be held by the studio it is derived into");
        }
        if (i > 0 && copyOrigin(copy) != copyOrigin(copies.front())) {
            throw Base::ValueError("Derived: the parts must come from one part studio");
        }
        if (std::count(copies.begin(), copies.end(), copy) > 1) {
            throw Base::ValueError("Derived: a part is chosen twice");
        }
    }
}

/// Removes a member, its binder and its Body when nothing else is left in it
void removeMember(FeatureBase* member)
{
    App::Document* doc = member->getDocument();
    App::DocumentObject* binder = sourceHolderOf(member);
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

std::string studioLabel(const App::Document* doc, const App::Part* studio)
{
    return studio ? std::string(studio->Label.getValue()) : App::DocumentTabs::implicitLabel(doc);
}

std::string derivedPlacementProblem(const App::Document* doc, const App::Part* from, const App::Part* to)
{
    if (from == to || samePlacement(studioPlacement(from), studioPlacement(to))) {
        return {};
    }
    return "Derived: " + studioLabel(doc, from) + " and " + studioLabel(doc, to)
        + " are placed differently (their Placement): a derived part would not keep its place in "
          "its part studio. Give both the same Placement";
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
    if (isDerivedCopy(source)) {
        std::string file = copyString(source, "DerivedSourceFile");
        if (file.empty()) {
            file = copyString(source, "DerivedSourcePath");
        }
        const auto slash = file.find_last_of("/\\");
        if (slash != std::string::npos) {
            file = file.substr(slash + 1);
        }
        return derivedCopyLabel(source) + " (" + copyString(source, "DerivedSourceStudioLabel")
            + ") in " + file;
    }
    App::Part* studio = nullptr;
    Part::BodyBase::studioOf(Part::BodyBase::bodyOfObject(source), studio);
    return std::string(source->Label.getValue()) + " ("
        + studioLabel(source->getDocument(), studio) + ")";
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
        // A copy of another document's part stands for its source (derived-design.md 3)
        App::DocumentObject* copy = sourceHolderOf(member);
        return copy && copy->isAttachedToDocument() ? copy : nullptr;
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
    const std::size_t keptCount = kept.size();
    for (Body* source : sources) {
        if (std::ranges::find(covered, source) == covered.end()) {
            kept.push_back(addMember(doc, studio, source, label + " (" + source->Label.getValue() + ")"));
        }
    }
    // The lead stays the lead while it keeps its part; else the last member kept takes over (the
    // last one made when none is), after the old one is gone (its label is free then), at the old
    // one's place in the studio's history, so the feature's row doesn't move (review R6-4). The
    // key is read after the members are made: one made at a rolled-back bar saves the order
    FeatureBase* newLead = lead;
    if (std::ranges::find(kept, lead) == kept.end()) {
        newLead = keptCount > 0 ? kept[keptCount - 1] : kept.back();
        setHistoryKey(newLead, historyKey(lead));
    }
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

bool isDerivedCopy(const App::DocumentObject* obj)
{
    return obj && obj->isDerivedFrom<Part::Feature>() && !obj->isDerivedFrom<PartDesign::Feature>()
        && freecad_cast<App::PropertyString*>(obj->getPropertyByName("DerivedSourcePart"));
}

std::string derivedCopyLabel(const App::DocumentObject* copy)
{
    std::string label = copyString(copy, "DerivedSourceLabel");
    return label.empty() ? copyString(copy, "DerivedSourcePart") : label;
}

FeatureBase* makeDerivedCopies(App::Document* doc, App::Part* studio, const std::vector<Part::Feature*>& copies)
{
    if (!doc) {
        throw Base::ValueError("Derived: no document");
    }
    checkCopies(doc, studio, copies);
    const std::string label = freeLabel(doc);
    std::vector<FeatureBase*> members;
    for (std::size_t i = 0; i < copies.size(); ++i) {
        const bool last = i + 1 == copies.size();
        members.push_back(addCopyMember(
            doc,
            studio,
            copies[i],
            last ? label : label + " (" + derivedCopyLabel(copies[i]) + ")"
        ));
    }
    FeatureBase* lead = members.back();
    members.pop_back();
    lead->DerivedParts.setValues(std::vector<App::DocumentObject*>(members.begin(), members.end()));
    return lead;
}

FeatureBase* editDerivedCopies(FeatureBase* lead, const std::vector<Part::Feature*>& copies)
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
    checkCopies(doc, studio, copies);
    const std::string label = lead->Label.getValue();
    std::vector<FeatureBase*> kept;
    std::vector<FeatureBase*> dropped;
    std::vector<App::DocumentObject*> covered;
    for (FeatureBase* member : derivedMembers(lead)) {
        App::DocumentObject* source = derivedSource(member);
        bool stays = source && std::ranges::find(copies, source) != copies.end()
            && std::ranges::find(covered, source) == covered.end();
        if (stays) {
            kept.push_back(member);
            covered.push_back(source);
        }
        else {
            dropped.push_back(member);
        }
    }
    if (dropped.empty() && kept.size() == copies.size()) {
        return lead;
    }
    const std::size_t keptCount = kept.size();
    for (Part::Feature* copy : copies) {
        if (std::ranges::find(covered, copy) == covered.end()) {
            kept.push_back(addCopyMember(doc, studio, copy, label + " (" + derivedCopyLabel(copy) + ")"));
        }
    }
    // As editDerived(): the lead keeps its row, or the last member kept takes it over
    FeatureBase* newLead = lead;
    if (std::ranges::find(kept, lead) == kept.end()) {
        newLead = keptCount > 0 ? kept[keptCount - 1] : kept.back();
        setHistoryKey(newLead, historyKey(lead));
    }
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
    App::DocumentObject* binder = sourceHolderOf(lead);
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
