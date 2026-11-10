// SPDX-License-Identifier: LGPL-2.1-or-later

// The studio's ordered feature list (FreeCAD-CH ops#654, notes/parts-design.md 3.2, 10.1 and 10.8,
// notes/one-history-design.md 5 and 9): the list is the only truth of the history; each Body's
// chain is its projection, rebuilt by reconcile() in the edit's transaction. Ported from the
// bake-off's prototype (work/standby-a/reconcile.py), which passed 2,400 random edits.

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <App/Document.h>
#include <App/GroupExtension.h>
#include <App/Part.h>
#include <App/PropertyStandard.h>
#include <Base/Exception.h>
#include <Base/Tools.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureAddSub.h"
#include "FeatureApply.h"
#include "FeatureBase.h"
#include "FeatureMultiTransform.h"
#include "Studio.h"
#include "StudioList.h"

using namespace PartDesign;

PROPERTY_SOURCE(PartDesign::StudioList, App::DocumentObject)

namespace
{

std::string quoted(const App::DocumentObject* obj)
{
    return std::string("'") + (obj ? obj->Label.getValue() : "?") + "'";
}

/// A MultiTransform's step (Studio.cpp's rule): a member of the Body run as part of its
/// MultiTransform, not a feature of its own
bool isMultiTransformStep(const App::DocumentObject* obj)
{
    if (!freecad_cast<const Transformed*>(obj)) {
        return false;
    }
    return std::ranges::any_of(obj->getInList(), [obj](App::DocumentObject* in) {
        auto multi = freecad_cast<MultiTransform*>(in);
        return multi
            && std::ranges::find(multi->Transformations.getValues(), obj)
            != multi->Transformations.getValues().end();
    });
}

/// A Body member that is no entry and keeps its place in the Group: the Body's FeatureBase (nothing
/// goes before it) and a MultiTransform's step
bool isAnchor(const App::DocumentObject* obj)
{
    return obj->isDerivedFrom<FeatureBase>() || isMultiTransformStep(obj);
}

App::DocumentObject* ownerOfStep(const App::DocumentObject* obj)
{
    auto feature = freecad_cast<const Feature*>(obj);
    return feature ? feature->StudioOwner.getValue() : nullptr;
}

bool suppressedOf(const App::DocumentObject* entry)
{
    auto prop = freecad_cast<App::PropertyBool*>(entry->getPropertyByName("Suppressed"));
    return prop && prop->getValue();
}

/// The Boolean operation an owner asks for: its Operation (an enumeration or a string), by
/// FreeCAD's or Onshape's word; Union without one
const char* operationOf(const App::DocumentObject* owner)
{
    std::string op;
    if (auto prop = owner->getPropertyByName("Operation")) {
        if (auto enumeration = freecad_cast<const App::PropertyEnumeration*>(prop)) {
            const char* value = enumeration->getValueAsString();
            op = value ? value : "";
        }
        else if (auto text = freecad_cast<const App::PropertyString*>(prop)) {
            op = text->getValue();
        }
    }
    if (op == "Subtraction" || op == "Cut" || op == "Remove") {
        return "Subtraction";
    }
    if (op == "Common" || op == "Intersect" || op == "Intersection") {
        return "Common";
    }
    return "Union";
}

int positionOf(const std::vector<App::DocumentObject*>& entries, const App::DocumentObject* obj)
{
    auto it = std::ranges::find(entries, obj);
    return it == entries.end() ? -1 : static_cast<int>(it - entries.begin());
}

/// Inserts entry at index of entries; a bar (an index, -1: the end) at or after index moves with
/// the entries after it, so an entry inserted at the bar is active (Onshape inserts at the bar)
void insertAt(std::vector<App::DocumentObject*>& entries,
              int& bar,
              int index,
              App::DocumentObject* entry)
{
    const int size = static_cast<int>(entries.size());
    if (index < 0 || index > size) {
        index = size;
    }
    entries.insert(entries.begin() + index, entry);
    if (bar >= 0 && index <= bar) {
        ++bar;
    }
}

/// The entries of every other list of doc
std::set<const App::DocumentObject*> entriesElsewhere(const StudioList* list)
{
    std::set<const App::DocumentObject*> out;
    auto doc = list->getDocument();
    if (!doc) {
        return out;
    }
    for (auto obj : doc->getObjectsOfType(StudioList::getClassTypeId())) {
        if (obj == list) {
            continue;
        }
        for (auto entry : static_cast<StudioList*>(obj)->Entries.getValues()) {
            if (entry) {
                out.insert(entry);
            }
        }
    }
    return out;
}

/// Whether body is a part at index of entries (positions: each entry's index): not absorbed into
/// another part (MergedInto, ops#325), and not made by an entry after index (StudioMadeBy)
bool liveAt(const Body* body,
            int index,
            const std::map<const App::DocumentObject*, int>& positions)
{
    auto merged = freecad_cast<App::PropertyLink*>(body->getPropertyByName("MergedInto"));
    if (merged && merged->getValue()) {
        return false;
    }
    if (auto madeBy = body->StudioMadeBy.getValue()) {
        auto it = positions.find(madeBy);
        if (it != positions.end() && it->second > index) {
            return false;
        }
    }
    return true;
}

/// ids resolved against the studio's bodies at index: each id's Body and the pieces descended
/// from it (StudioParentId, up the chain of parts still present), in id order, without repeats
std::vector<Body*> resolveScope(const std::vector<std::string>& ids,
                           const std::vector<Body*>& bodies,
                           int index,
                           const std::map<const App::DocumentObject*, int>& positions)
{
    std::map<std::string, const Body*> byId;
    for (auto body : bodies) {
        byId.emplace(studioPartId(body), body);
    }
    // Whether body is id's part or descends from it
    auto descends = [&byId](const Body* body, const std::string& id) {
        std::set<std::string> seen;
        std::string current = studioPartId(body);
        std::string parent = body->StudioParentId.getValue();
        while (true) {
            if (current == id) {
                return true;
            }
            if (parent.empty() || !seen.insert(parent).second) {
                return false;
            }
            current = parent;
            auto it = byId.find(parent);
            parent = it == byId.end() ? std::string() : it->second->StudioParentId.getValue();
        }
    };
    std::vector<Body*> out;
    for (const auto& id : ids) {
        if (id.empty()) {
            continue;
        }
        for (auto body : bodies) {
            if (std::ranges::find(out, body) == out.end() && descends(body, id)
                && liveAt(body, index, positions)) {
                out.push_back(body);
            }
        }
    }
    return out;
}

std::map<const App::DocumentObject*, int>
positionsOf(const std::vector<App::DocumentObject*>& entries)
{
    std::map<const App::DocumentObject*, int> positions;
    for (std::size_t i = 0; i < entries.size(); ++i) {
        if (entries[i]) {
            positions.emplace(entries[i], static_cast<int>(i));
        }
    }
    return positions;
}

App::Part* studioOfObject(const App::DocumentObject* obj)
{
    if (auto body = Body::findBodyOf(obj)) {
        App::Part* studio = nullptr;
        Part::BodyBase::studioOf(body, studio);
        return studio;
    }
    return App::Part::getPartOfObject(obj, /*recursive=*/true);
}

}  // namespace

StudioList::StudioList()
{
    ADD_PROPERTY_TYPE(Entries, (nullptr), "Studio", App::Prop_None, "The history, in order");
    ADD_PROPERTY_TYPE(
        Bar,
        (-1),
        "Studio",
        App::Prop_None,
        "Entries before it are active (-1: the end)"
    );
}

App::DocumentObjectExecReturn* StudioList::execute()
{
    return App::DocumentObject::StdReturn;
}

short StudioList::mustExecute() const
{
    return 0;
}

void StudioList::onChanged(const App::Property* prop)
{
    App::DocumentObject::onChanged(prop);
}

StudioList* StudioList::of(App::Document* doc, App::Part* studio, bool create)
{
    if (!doc) {
        return nullptr;
    }
    for (auto obj : doc->getObjectsOfType(StudioList::getClassTypeId())) {
        auto list = static_cast<StudioList*>(obj);
        if (list->studio() == studio) {
            return list;
        }
    }
    if (!create) {
        return nullptr;
    }
    // Adopted from the derived order once (Studio.cpp): the Body members, without the anchors and
    // steps, and the bar where the studio's bar is
    const auto sequence = studioSequence(doc, studio);
    std::vector<App::DocumentObject*> entries;
    App::DocumentObject* barAfter = nullptr;
    const bool rolledBack = isStudioRolledBack(doc, studio);
    if (rolledBack) {
        barAfter = studioBarAfter(sequence);
    }
    int bar = rolledBack && !barAfter ? 0 : -1;
    for (auto obj : sequence) {
        if (obj && !isAnchor(obj) && !isStep(obj)) {
            entries.push_back(obj);
        }
        if (rolledBack && obj == barAfter) {
            bar = static_cast<int>(entries.size());
        }
    }
    if (bar >= static_cast<int>(entries.size())) {
        bar = -1;
    }
    auto list = static_cast<StudioList*>(doc->addObject("PartDesign::StudioList", "StudioList"));
    if (studio) {
        studio->getExtensionByType<App::GroupExtension>()->addObject(list);
    }
    list->Entries.setValues(entries);
    list->Bar.setValue(bar);
    return list;
}

StudioList* StudioList::holding(const App::DocumentObject* entry)
{
    if (!entry || !entry->getDocument()) {
        return nullptr;
    }
    for (auto obj : entry->getDocument()->getObjectsOfType(StudioList::getClassTypeId())) {
        auto list = static_cast<StudioList*>(obj);
        const auto& entries = list->Entries.getValues();
        if (std::ranges::find(entries, entry) != entries.end()) {
            return list;
        }
    }
    return nullptr;
}

App::Part* StudioList::studio() const
{
    return App::Part::getPartOfObject(this, /*recursive=*/true);
}

void StudioList::insertEntry(App::DocumentObject* entry, int index)
{
    if (!entry) {
        throw Base::ValueError("Studio list: no entry to insert");
    }
    if (auto list = holding(entry)) {
        throw Base::ValueError(quoted(entry) + " is in the history already, at "
                               + std::to_string(positionOf(list->Entries.getValues(), entry) + 1));
    }
    auto entries = Entries.getValues();
    int bar = Bar.getValue();
    insertAt(entries, bar, index, entry);
    Entries.setValues(entries);
    setBarIndex(bar);
}

void StudioList::removeEntry(App::DocumentObject* entry)
{
    auto entries = Entries.getValues();
    const int pos = positionOf(entries, entry);
    if (pos < 0) {
        throw Base::ValueError(quoted(entry) + " is not in this history");
    }
    entries.erase(entries.begin() + pos);
    int bar = Bar.getValue();
    if (bar >= 0 && pos < bar) {
        --bar;
    }
    Entries.setValues(entries);
    setBarIndex(bar);
}

void StudioList::moveEntry(App::DocumentObject* entry, int index)
{
    auto entries = Entries.getValues();
    const int pos = positionOf(entries, entry);
    if (pos < 0) {
        throw Base::ValueError(quoted(entry) + " is not in this history");
    }
    entries.erase(entries.begin() + pos);
    const int size = static_cast<int>(entries.size());
    if (index < 0 || index > size) {
        index = size;
    }
    entries.insert(entries.begin() + index, entry);
    if (entries != Entries.getValues()) {
        Entries.setValues(entries);
    }
}

void StudioList::setBarIndex(int index)
{
    const int size = static_cast<int>(Entries.getSize());
    if (index < 0 || index >= size) {
        index = -1;
    }
    if (Bar.getValue() != index) {
        Bar.setValue(index);
    }
}

int StudioList::barIndex() const
{
    const int size = static_cast<int>(Entries.getSize());
    const int bar = Bar.getValue();
    return bar < 0 || bar > size ? size : bar;
}

StudioList::Projection StudioList::project() const
{
    return projectEntries(Entries.getValues(), Bar.getValue());
}

StudioList::Projection StudioList::projectEntries(const std::vector<App::DocumentObject*>& entries,
                                                  int bar) const
{
    Projection out;
    auto doc = getDocument();
    if (!doc) {
        out.errors.emplace_back("The studio list is in no document");
        return out;
    }
    const auto bodies = studioBodies(doc, studio());
    const std::set<const Body*> inStudio(bodies.begin(), bodies.end());
    for (auto body : bodies) {
        out.chains[body];
    }
    const auto elsewhere = entriesElsewhere(this);
    const int size = static_cast<int>(entries.size());
    const int barAt = bar < 0 || bar > size ? size : bar;
    std::map<const App::DocumentObject*, int> positions;
    for (int i = 0; i < size; ++i) {
        App::DocumentObject* entry = entries[i];
        if (!entry) {
            continue;
        }
        if (!positions.emplace(entry, i).second) {
            out.errors.push_back(quoted(entry) + " is in the history twice");
            continue;
        }
        if (elsewhere.count(entry)) {
            out.errors.push_back(quoted(entry) + " is in the history of another studio too");
        }
    }
    for (int i = 0; i < size; ++i) {
        App::DocumentObject* entry = entries[i];
        if (!entry || positions[entry] != i) {
            continue;
        }
        if (entry == this || entry->isDerivedFrom<Part::BodyBase>()
            || entry->isDerivedFrom<App::Part>()) {
            out.errors.push_back(quoted(entry) + " is a part or a studio, not a feature");
            continue;
        }
        if (isStep(entry)) {
            out.errors.push_back(quoted(entry) + " is a step: its studio feature is the entry");
            continue;
        }
        Slot slot;
        slot.entry = entry;
        slot.suppressed = suppressedOf(entry);
        slot.held = i >= barAt;
        if (Body* body = Body::findBodyOf(entry)) {
            if (!inStudio.count(body)) {
                out.errors.push_back(quoted(entry) + " is in " + quoted(body)
                                     + ", a part outside the studio");
                continue;
            }
            out.chains[body].push_back(slot);
            continue;
        }
        // An owner: a step in each part its scope resolves to at its place
        slot.isStep = true;
        const auto ids = studioScopeIds(entry);
        const auto scope = resolveScope(ids, bodies, i, positions);
        if (!ids.empty() && scope.empty()) {
            out.unresolved.push_back(entry);
        }
        for (auto body : scope) {
            out.chains[body].push_back(slot);
        }
        for (auto user : entry->getInList()) {
            if (isStep(user) && ownerOfStep(user) == entry) {
                Body* body = Body::findBodyOf(user);
                if (body && !inStudio.count(body)) {
                    out.errors.push_back(quoted(entry) + " has a step in " + quoted(body)
                                         + ", a part outside the studio");
                }
            }
        }
    }
    return out;
}

bool StudioList::reconcile(std::string* why)
{
    auto fail = [why](const std::string& text) {
        if (why) {
            *why = text;
        }
        return false;
    };
    App::Document* doc = getDocument();
    if (!doc) {
        return fail("The studio list is in no document");
    }
    const auto bodies = studioBodies(doc, studio());

    // 1. Adopt the Body members the list doesn't hold (made by old commands), each after the entry
    // before it in its Body's Group; planned on a copy, so a refusal changes nothing
    std::vector<App::DocumentObject*> entries;
    for (auto entry : Entries.getValues()) {
        if (entry) {
            entries.push_back(entry);
        }
    }
    int bar = Bar.getValue();
    if (bar >= static_cast<int>(entries.size())) {
        bar = -1;
    }
    const auto elsewhere = entriesElsewhere(this);
    std::set<const App::DocumentObject*> held(entries.begin(), entries.end());
    for (auto body : bodies) {
        const std::string id = studioPartId(body);
        // Where a member with nothing before it in its Body goes: before the Body's first entry,
        // else at the bar
        auto firstOfBody = [&]() {
            for (std::size_t i = 0; i < entries.size(); ++i) {
                auto entry = entries[i];
                if (body->hasObject(entry)) {
                    return static_cast<int>(i);
                }
                const auto ids = studioScopeIds(entry);
                if (!Body::findBodyOf(entry) && std::ranges::find(ids, id) != ids.end()) {
                    return static_cast<int>(i);
                }
            }
            return bar < 0 ? static_cast<int>(entries.size()) : bar;
        };
        App::DocumentObject* before = nullptr;
        for (auto member : body->Group.getValues()) {
            if (!member || isAnchor(member)) {
                continue;
            }
            if (isStep(member)) {
                auto owner = ownerOfStep(member);
                if (owner && held.count(owner)) {
                    before = owner;
                }
                continue;
            }
            if (held.count(member)) {
                before = member;
                continue;
            }
            if (elsewhere.count(member)) {
                continue;  // a projection error below
            }
            const int index = before ? positionOf(entries, before) + 1 : firstOfBody();
            insertAt(entries, bar, index, member);
            held.insert(member);
            before = member;
        }
    }

    // 2. Project; refuse before writing anything
    const Projection projection = projectEntries(entries, bar);
    if (!projection.errors.empty()) {
        std::string text;
        for (const auto& error : projection.errors) {
            text += (text.empty() ? "" : "\n") + error;
        }
        return fail(text);
    }
    if (entries != Entries.getValues()) {
        Entries.setValues(entries);
    }
    setBarIndex(bar);
    for (auto body : bodies) {
        if (std::string(body->StudioPartId.getValue()).empty()) {
            body->StudioPartId.setValue(body->getNameInDocument());
        }
    }

    // 3. Remove the steps whose owner is gone, out of the list, or no longer acts on the part (a
    // part dropped from a scope loses its step: names come from the owner's tool, so a step made
    // again later makes the same names, work/standby-f/tags.log); a second step of one key too.
    // All first, so the names of the steps made below are free
    for (auto body : bodies) {
        const auto& chain = projection.chains.at(body);
        std::set<const App::DocumentObject*> wanted;
        for (const auto& slot : chain) {
            if (slot.isStep) {
                wanted.insert(slot.entry);
            }
        }
        std::set<const App::DocumentObject*> seen;
        const auto members = body->Group.getValues();
        for (auto member : members) {
            if (!member || !isStep(member)) {
                continue;
            }
            auto owner = ownerOfStep(member);
            if (owner && wanted.count(owner) && seen.insert(owner).second) {
                continue;
            }
            const std::string name = member->getNameInDocument();
            body->removeObject(member);
            doc->removeObject(name.c_str());
        }
    }

    // 4. Make the missing steps and put every Body's chain in the projected order. A member that
    // isn't in the chain (an anchor) keeps its place; a slot already right after the one before
    // it isn't touched. Steps move by removeObject() and insertObject(), which keep the
    // BaseFeature links; native members by reorderObject(), which also re-targets their references
    std::map<const App::DocumentObject*, std::vector<std::pair<Body*, Feature*>>> stepsByOwner;
    for (auto body : bodies) {
        const auto& chain = projection.chains.at(body);
        std::vector<App::DocumentObject*> wanted;
        for (const auto& slot : chain) {
            if (!slot.isStep) {
                wanted.push_back(slot.entry);
                continue;
            }
            Feature* step = stepOf(slot.entry, body);
            if (!step) {
                const std::string type = studioStepType(slot.entry);
                auto obj = doc->addObject(type.c_str(), stepName(slot.entry, body).c_str());
                step = freecad_cast<Feature*>(obj);
                if (!step) {
                    if (obj) {
                        doc->removeObject(obj->getNameInDocument());
                    }
                    return fail(type + " is not a PartDesign feature: no step for "
                                + quoted(slot.entry));
                }
                step->StudioOwner.setValue(slot.entry);
                step->Visibility.setValue(false);
            }
            stepsByOwner[slot.entry].emplace_back(body, step);
            wanted.push_back(step);
        }
        const std::set<const App::DocumentObject*> inChain(wanted.begin(), wanted.end());
        App::DocumentObject* previous = nullptr;
        for (auto obj : wanted) {
            const auto group = body->Group.getValues();
            auto from = group.begin();
            if (previous) {
                from = std::ranges::find(group, previous);
                if (from != group.end()) {
                    ++from;
                }
            }
            auto next = std::find_if(from, group.end(), [&inChain](App::DocumentObject* member) {
                return inChain.count(member) > 0;
            });
            if (next != group.end() && *next == obj) {
                previous = obj;
                continue;
            }
            const bool present = std::ranges::find(group, obj) != group.end();
            if (present && !isStep(obj)) {
                try {
                    body->reorderObject({obj}, previous, true);
                }
                catch (const Base::Exception& e) {
                    return fail(e.what());
                }
            }
            else {
                if (present) {
                    body->removeObject(obj);
                }
                App::DocumentObject* target = previous;
                const auto& now = body->Group.getValues();
                if (!target && !now.empty() && now.front()->isDerivedFrom<FeatureBase>()) {
                    target = now.front();  // nothing goes before the base feature
                }
                body->insertObject(obj, target, /*after=*/true);
            }
            previous = obj;
        }
    }

    // 5. The steps' values from their owners; the owners' bases at their place
    for (const auto& [owner, steps] : stepsByOwner) {
        std::vector<App::DocumentObject*> bases;
        for (const auto& [body, step] : steps) {
            if (step->StudioOwner.getValue() != owner) {
                step->StudioOwner.setValue(const_cast<App::DocumentObject*>(owner));
            }
            if (auto addSub = freecad_cast<FeatureAddSub*>(step)) {
                const char* op = operationOf(owner);
                const char* current = addSub->Operation.getValueAsString();
                if (addSub->Operation.isPartOf(op) && (!current || std::string(current) != op)) {
                    addSub->Operation.setValue(op);
                }
                auto refine = freecad_cast<App::PropertyBool*>(owner->getPropertyByName("Refine"));
                if (refine) {
                    if (addSub->Refine.getValue() != refine->getValue()) {
                        addSub->Refine.setValue(refine->getValue());
                    }
                }
            }
            const bool suppressed = suppressedOf(owner);
            if (step->Suppressed.getValue() != suppressed) {
                step->Suppressed.setValue(suppressed);
            }
            if (auto base = body->getPrevSolidFeature(step)) {
                bases.push_back(base);
            }
        }
        auto prop = freecad_cast<App::PropertyLinkList*>(owner->getPropertyByName("StudioBases"));
        if (prop && prop->getValues() != bases) {
            prop->setValues(bases);
        }
    }
    // An owner whose steps are all gone has no bases
    for (auto entry : entries) {
        if (!Body::findBodyOf(entry) && !stepsByOwner.count(entry)) {
            auto prop =
                freecad_cast<App::PropertyLinkList*>(entry->getPropertyByName("StudioBases"));
            if (prop && prop->getSize() > 0) {
                prop->setValues(std::vector<App::DocumentObject*>());
            }
        }
    }

    // 6. Each Body's Tip from the bar: its last active solid, else its base feature (or none)
    for (auto body : bodies) {
        App::DocumentObject* tip = nullptr;
        const auto& chain = projection.chains.at(body);
        for (auto it = chain.rbegin(); it != chain.rend() && !tip; ++it) {
            if (it->held) {
                continue;
            }
            App::DocumentObject* obj = it->isStep ? stepOf(it->entry, body) : it->entry;
            if (Body::isSolidFeature(obj)) {
                tip = obj;
            }
        }
        if (!tip) {
            const auto& group = body->Group.getValues();
            if (!group.empty() && group.front()->isDerivedFrom<FeatureBase>()) {
                tip = group.front();
            }
        }
        if (body->Tip.getValue() != tip) {
            body->Tip.setValue(tip);
        }
    }
    return true;
}

Feature* StudioList::stepOf(const App::DocumentObject* owner, const Body* body)
{
    if (!owner || !body) {
        return nullptr;
    }
    for (auto member : body->Group.getValues()) {
        if (member && isStep(member) && ownerOfStep(member) == owner) {
            return static_cast<Feature*>(member);
        }
    }
    return nullptr;
}

std::vector<Feature*> StudioList::stepsOf(const App::DocumentObject* owner)
{
    std::vector<Feature*> out;
    if (!owner) {
        return out;
    }
    for (auto body : studioScopeOf(owner)) {
        if (auto step = stepOf(owner, body)) {
            out.push_back(step);
        }
    }
    // Steps not (yet, or no longer) in its scope's parts, until the next reconcile
    for (auto user : owner->getInList()) {
        if (!isStep(user) || ownerOfStep(user) != owner || !Body::findBodyOf(user)) {
            continue;
        }
        auto step = static_cast<Feature*>(user);
        if (std::ranges::find(out, step) == out.end()) {
            out.push_back(step);
        }
    }
    return out;
}

std::string StudioList::stepName(const App::DocumentObject* owner, const Body* body)
{
    return std::string(owner->getNameInDocument()) + "_" + body->getNameInDocument();
}

bool StudioList::isStep(const App::DocumentObject* obj)
{
    auto feature = freecad_cast<const Feature*>(obj);
    return feature && (feature->StudioOwner.getValue() || feature->isDerivedFrom<FeatureApply>());
}

bool PartDesign::isStudioOwner(const App::DocumentObject* obj)
{
    return obj && !Body::findBodyOf(obj) && StudioList::holding(obj);
}

std::string PartDesign::studioPartId(const Body* body)
{
    if (!body) {
        return {};
    }
    std::string id = body->StudioPartId.getValue();
    if (id.empty() && body->isAttachedToDocument()) {
        id = body->getNameInDocument();
    }
    return id;
}

std::vector<std::string> PartDesign::studioScopeIds(const App::DocumentObject* owner)
{
    if (!owner) {
        return {};
    }
    auto prop = freecad_cast<App::PropertyStringList*>(owner->getPropertyByName("StudioScope"));
    return prop ? prop->getValues() : std::vector<std::string>();
}

void PartDesign::setStudioScopeIds(App::DocumentObject* owner, const std::vector<std::string>& ids)
{
    if (!owner) {
        return;
    }
    auto prop = freecad_cast<App::PropertyStringList*>(owner->getPropertyByName("StudioScope"));
    if (!prop) {
        if (owner->getPropertyByName("StudioScope")) {
            throw Base::TypeError(quoted(owner) + "'s StudioScope is not a list of part ids");
        }
        prop = static_cast<App::PropertyStringList*>(owner->addDynamicProperty(
            "App::PropertyStringList",
            "StudioScope",
            "Studio",
            "The part ids this studio feature acts on, in order (ops#654)",
            App::Prop_Hidden
        ));
    }
    if (prop->getValues() != ids) {
        prop->setValues(ids);
    }
}

std::vector<Body*> PartDesign::studioScopeOf(const App::DocumentObject* owner)
{
    if (!owner || !owner->getDocument()) {
        return {};
    }
    const StudioList* list = StudioList::holding(owner);
    App::Part* studio = list ? list->studio() : studioOfObject(owner);
    const auto bodies = studioBodies(owner->getDocument(), studio);
    std::vector<App::DocumentObject*> entries;
    if (list) {
        entries = list->Entries.getValues();
    }
    const auto positions = positionsOf(entries);
    auto it = positions.find(owner);
    const int index = it == positions.end() ? static_cast<int>(entries.size()) : it->second;
    return resolveScope(studioScopeIds(owner), bodies, index, positions);
}

void PartDesign::setStudioScope(App::DocumentObject* owner, const std::vector<Body*>& parts)
{
    std::vector<std::string> ids;
    for (auto body : parts) {
        if (!body) {
            continue;
        }
        if (std::string(body->StudioPartId.getValue()).empty()) {
            body->StudioPartId.setValue(body->getNameInDocument());  // adopted
        }
        ids.push_back(studioPartId(body));
    }
    setStudioScopeIds(owner, ids);
}

long PartDesign::studioTagFor(const App::DocumentObject* owner, const Body* body)
{
    if (!owner) {
        return 0;
    }
    if (auto tags = freecad_cast<App::PropertyMap*>(owner->getPropertyByName("StudioTags"))) {
        const auto& values = tags->getValues();
        auto it = values.find(studioPartId(body));
        if (it != values.end()) {
            try {
                const long tag = std::stol(it->second);
                if (tag != 0) {
                    return tag;
                }
            }
            catch (const std::exception&) {
                // not a number: the owner's own tag
            }
        }
    }
    return owner->getID();
}

std::string PartDesign::studioStepType(const App::DocumentObject* /*owner*/)
{
    // Every tool-making owner, and S1's shape owners; dress-ups get their own type in P8a
    return "PartDesign::FeatureApply";
}
