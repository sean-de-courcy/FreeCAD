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

#include <App/Application.h>
#include <App/Document.h>
#include <App/GroupExtension.h>
#include <App/Part.h>
#include <App/PropertyStandard.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Tools.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureAddSub.h"
#include "FeatureApply.h"
#include "FeatureBase.h"
#include "FeatureBoolean.h"
#include "FeatureMultiTransform.h"
#include "Retarget.h"
#include "Studio.h"
#include "StudioList.h"

namespace App
{
// App/DocumentObject.cpp (FreeCAD-CH ops#325): the readers of obj through a subname path, which
// aren't in obj's in-list (declared where used, as in Body.cpp)
AppExport std::vector<DocumentObject*> subnamePathReaders(const DocumentObject* obj,
                                                          std::vector<DocumentObject*>* links = nullptr);
}  // namespace App

using namespace PartDesign;

PROPERTY_SOURCE(PartDesign::StudioList, App::DocumentObject)

namespace PartDesign
{
// Below (slice 9)
PartDesignExport bool isStudioPartPattern(const App::DocumentObject* obj);
PartDesignExport bool studioPartMirrorConsumes(const App::DocumentObject* owner);
}  // namespace PartDesign

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

/// A hidden dynamic flag of obj (slice 9), written only when it changes; it touches nothing
void setFlag(App::DocumentObject* obj, const char* name, bool on)
{
    auto prop = freecad_cast<App::PropertyBool*>(obj->getPropertyByName(name));
    if (!prop) {
        if (!on || obj->getPropertyByName(name)) {
            return;
        }
        prop = static_cast<App::PropertyBool*>(obj->addDynamicProperty(
            "App::PropertyBool",
            name,
            "Studio",
            "Whether this part mirror's Add consumes its source part (ops#654 slice 9)",
            App::Prop_Hidden | App::Prop_Output | App::Prop_NoRecompute
        ));
    }
    if (prop->getValue() != on) {
        prop->setValue(on);
    }
}

bool flagOf(const App::DocumentObject* obj, const char* name)
{
    auto prop = freecad_cast<App::PropertyBool*>(obj->getPropertyByName(name));
    return prop && prop->getValue();
}

/// The Boolean operation an owner asks for: its Operation (an enumeration or a string), by
/// FreeCAD's or Onshape's word; Union without one
const char* operationOf(const App::DocumentObject* owner)
{
    std::string op;
    if (auto boolean = freecad_cast<const Boolean*>(owner)) {
        // A Boolean studio feature (P5): its Type, Fuse / Cut / Common
        const char* value = boolean->Type.getValueAsString();
        op = value ? value : "";
    }
    else if (auto prop = owner->getPropertyByName("Operation")) {
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

/// When a part is consumed (FreeCAD-CH ops#654 P5): part -> the list index of the Boolean owner
/// that consumes it. From that place on it is no part: no scope or tool resolves to it
using Consumed = std::map<const Body*, int>;

/// Whether body is a part at index of entries (positions: each entry's index): not absorbed into
/// another part (MergedInto, ops#325), not consumed by a Boolean before index, and not made by an
/// entry after index (StudioMadeBy). With before, the state just before the entry at index: a part
/// made by that entry isn't there yet either
bool liveAt(const Body* body,
            int index,
            const std::map<const App::DocumentObject*, int>& positions,
            const Consumed& consumed,
            bool before = false)
{
    auto merged = freecad_cast<App::PropertyLink*>(body->getPropertyByName("MergedInto"));
    if (merged && merged->getValue()) {
        return false;
    }
    if (auto it = consumed.find(body); it != consumed.end() && it->second < index) {
        return false;
    }
    if (auto madeBy = body->StudioMadeBy.getValue()) {
        auto it = positions.find(madeBy);
        if (it != positions.end() && (it->second > index || (before && it->second == index))) {
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
                           const std::map<const App::DocumentObject*, int>& positions,
                           const Consumed& consumed)
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
                && liveAt(body, index, positions, consumed)) {
                out.push_back(body);
            }
        }
    }
    return out;
}

/// A Boolean studio feature (P5): a PartDesign::Boolean outside every Body, not a Merge
const Boolean* booleanOwner(const App::DocumentObject* entry)
{
    auto boolean = freecad_cast<const Boolean*>(entry);
    if (!boolean || Body::findBodyOf(entry) || boolean->isMerge()) {
        return nullptr;
    }
    return boolean;
}

/// What a Boolean owner at index acts on (FreeCAD-CH ops#654 P5, Onshape O3 and O9b): its steps'
/// parts, its tool parts and the parts it consumes, all resolved at its place.
/// - Subtract: a step in each target; the tools (targets left out) are cut from them.
/// - Union: the parts listed, targets then tools, merge into the first, which has the only step;
///   the others are its tools.
/// - Intersect: refused at compute (a new part: P6p); steps in the targets, nothing consumed.
/// Keep tools off, the tools are consumed; a suppressed Boolean consumes nothing. both: the parts
/// that are a target and a tool of a Subtract or an Intersect (the Boolean fails)
struct BooleanParts
{
    std::vector<Body*> steps;
    std::vector<Body*> tools;
    std::vector<Body*> consumed;
    std::vector<Body*> both;
};

BooleanParts booleanPartsAt(const Boolean* owner,
                            const std::vector<Body*>& bodies,
                            int index,
                            const std::map<const App::DocumentObject*, int>& positions,
                            const Consumed& consumed)
{
    BooleanParts out;
    const auto targets = resolveScope(studioScopeIds(owner), bodies, index, positions, consumed);
    const auto tools =
        resolveScope(owner->StudioTools.getValues(), bodies, index, positions, consumed);
    const char* value = owner->Type.getValueAsString();
    const std::string type = value ? value : "";
    if (type == "Fuse") {
        std::vector<Body*> listed = targets;
        for (auto tool : tools) {
            if (std::ranges::find(listed, tool) == listed.end()) {
                listed.push_back(tool);
            }
        }
        if (!listed.empty()) {
            out.steps.push_back(listed.front());
            out.tools.assign(listed.begin() + 1, listed.end());
        }
    }
    else {
        out.steps = targets;
        for (auto tool : tools) {
            if (std::ranges::find(targets, tool) == targets.end()) {
                out.tools.push_back(tool);
            }
            else {
                out.both.push_back(tool);
            }
        }
    }
    // A Boolean that fails for what it resolves to (no target, no tool, a part both, a Union of
    // one part) contributes nothing, as Onshape's failed feature: it consumes nothing either. One
    // that fails on the geometry (a Union of parts apart, a cut that splits) still consumes: the
    // projection doesn't compute shapes (unverified on Onshape)
    const bool resolves = type == "Fuse" ? !out.tools.empty()
                                         : !out.steps.empty() && !out.tools.empty() && out.both.empty();
    if (type != "Common" && resolves && !owner->KeepTools.getValue() && !suppressedOf(owner)) {
        out.consumed = out.tools;
    }
    return out;
}

std::vector<Body*> partPatternSourcesAt(const App::DocumentObject* owner,
                                        const std::vector<Body*>& bodies,
                                        int index,
                                        const std::map<const App::DocumentObject*, int>& positions,
                                        const Consumed& consumed);

/// The parts the Boolean owners of entries consume, each at its owner's place, in list order (a
/// part a Boolean consumed earlier is no tool of a later one); and the source of a part mirror's
/// Add that merges it (slice 9, Onshape oracle 9 R4: decided by the mirror's last compute,
/// StudioConsumesSource), unless suppressed
Consumed consumedBy(const std::vector<App::DocumentObject*>& entries,
                    const std::vector<Body*>& bodies,
                    const std::map<const App::DocumentObject*, int>& positions)
{
    Consumed out;
    for (std::size_t i = 0; i < entries.size(); ++i) {
        if (entries[i] && isStudioPartPattern(entries[i]) && !suppressedOf(entries[i])
            && studioPartMirrorConsumes(entries[i])) {
            auto at = positions.find(entries[i]);
            if (at != positions.end() && at->second == static_cast<int>(i)) {
                const auto sources =
                    partPatternSourcesAt(entries[i], bodies, static_cast<int>(i), positions, out);
                if (sources.size() == 1) {
                    out.emplace(sources.front(), static_cast<int>(i));
                }
            }
            continue;
        }
        const Boolean* owner = booleanOwner(entries[i]);
        if (!owner) {
            continue;
        }
        auto at = positions.find(owner);
        if (at == positions.end() || at->second != static_cast<int>(i)) {
            continue;
        }
        const auto parts = booleanPartsAt(owner, bodies, static_cast<int>(i), positions, out);
        for (auto body : parts.consumed) {
            out.emplace(body, static_cast<int>(i));
        }
    }
    return out;
}

/// The parts owner (at index) has a step in: a Boolean's step parts, else its scope resolved
std::vector<Body*> stepPartsAt(const App::DocumentObject* owner,
                               const std::vector<Body*>& bodies,
                               int index,
                               const std::map<const App::DocumentObject*, int>& positions,
                               const Consumed& consumed)
{
    if (const Boolean* boolean = booleanOwner(owner)) {
        return booleanPartsAt(boolean, bodies, index, positions, consumed).steps;
    }
    return resolveScope(studioScopeIds(owner), bodies, index, positions, consumed);
}

/// A part pattern's source parts (StudioEntities) resolved at its place (index), without the
/// parts it makes itself (FreeCAD-CH ops#654 slice 9)
std::vector<Body*> partPatternSourcesAt(const App::DocumentObject* owner,
                                        const std::vector<Body*>& bodies,
                                        int index,
                                        const std::map<const App::DocumentObject*, int>& positions,
                                        const Consumed& consumed)
{
    auto pattern = freecad_cast<const Transformed*>(owner);
    if (!pattern) {
        return {};
    }
    std::vector<Body*> out;
    for (auto body :
         resolveScope(pattern->StudioEntities.getValues(), bodies, index, positions, consumed)) {
        if (body->StudioMadeBy.getValue() != owner) {
            out.push_back(body);
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

/// text as a piece of an object name, one to one: letters and digits stay, '_' becomes "__" and
/// every other byte "_HH" (two upper-case hex digits). So '_' is always followed by '_' or a hex
/// digit, and "_at_" (a lower-case letter after '_') can separate two pieces unambiguously
std::string namePiece(const std::string& text)
{
    static const char* hex = "0123456789ABCDEF";
    std::string out;
    for (unsigned char c : text) {
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) {
            out += static_cast<char>(c);
        }
        else if (c == '_') {
            out += "__";
        }
        else {
            out += '_';
            out += hex[c >> 4];
            out += hex[c & 0xF];
        }
    }
    return out;
}

/// The objects that read step (in body) beyond the chain: an in-list object linking it by any
/// property but a Body member's BaseFeature (the next feature of the chain) and an owner's
/// StudioBases (written by reconcile), and the readers through a subname path. Not the Body, the
/// step's owner or a list (FreeCAD-CH ops#654, notes/stored-tags.md 3 item 5)
std::vector<App::DocumentObject*> readersOf(const App::DocumentObject* step, const Body* body)
{
    std::vector<App::DocumentObject*> out;
    const App::DocumentObject* owner = ownerOfStep(step);
    auto add = [&out](App::DocumentObject* obj) {
        if (std::ranges::find(out, obj) == out.end()) {
            out.push_back(obj);
        }
    };
    for (auto in : step->getInList()) {
        if (!in || in == body || in == owner || in == step || in->isDerivedFrom<StudioList>()) {
            continue;
        }
        const bool member = body && body->hasObject(in);
        std::vector<App::Property*> props;
        in->getPropertyList(props);
        for (auto prop : props) {
            auto link = freecad_cast<App::PropertyLinkBase*>(prop);
            if (!link) {
                continue;
            }
            const char* name = prop->getName();
            const std::string propName = name ? name : "";
            if ((member && propName == "BaseFeature") || propName == "StudioBases") {
                continue;
            }
            std::vector<App::DocumentObject*> linked;
            link->getLinks(linked, /*all=*/true);
            if (std::ranges::find(linked, step) != linked.end()) {
                add(in);
                break;
            }
        }
    }
    for (auto reader : App::subnamePathReaders(step)) {
        if (reader && reader != body && reader != owner && !reader->isDerivedFrom<StudioList>()) {
            add(reader);
        }
    }
    return out;
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
    std::map<std::string, const Body*> byId;
    for (auto body : bodies) {
        out.chains[body];
        // A Body copied alone keeps the original's part id (and its steps the original's owners):
        // refused loudly until P7a decides what a copy is (parts-design.md 10.6)
        const std::string id = studioPartId(body);
        auto [it, added] = byId.emplace(id, body);
        if (!added) {
            out.errors.push_back("part id '" + id + "' is held by two parts, " + quoted(it->second)
                                 + " and " + quoted(body));
        }
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
    const Consumed consumed = consumedBy(entries, bodies, positions);
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
        const auto scope = stepPartsAt(entry, bodies, i, positions, consumed);
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

    // 2. Project, and plan every write; refuse before writing anything
    Projection projection = projectEntries(entries, bar);
    const auto positions = positionsOf(entries);
    const Consumed consumed = consumedBy(entries, bodies, positions);
    const int size = static_cast<int>(entries.size());
    const int barAt = bar < 0 || bar > size ? size : bar;

    // Each existing step is reused (its key, (owner, part), is in the projection; the first one
    // of a key), or unwanted: its owner is gone, out of the list, or no longer acts on the part.
    // An unwanted step that something reads is kept, suppressed, at its place (a reader of a step
    // deleted and made again would lose its link, notes/stored-tags.md "In short"); one without
    // readers is deleted. A step whose part isn't in its owner's scope and whose name isn't the one
    // made for that part (a Body copied with its steps) is refused, not deleted
    std::vector<App::DocumentObject*> doomed;
    std::map<const Body*, std::vector<Feature*>> kept;
    for (auto body : bodies) {
        const auto& chain = projection.chains.at(body);
        std::set<const App::DocumentObject*> wanted;
        for (const auto& slot : chain) {
            if (slot.isStep) {
                wanted.insert(slot.entry);
            }
        }
        std::set<const App::DocumentObject*> seen;
        for (auto member : body->Group.getValues()) {
            if (!member || !isStep(member)) {
                continue;
            }
            auto owner = ownerOfStep(member);
            if (owner && wanted.count(owner) && seen.insert(owner).second) {
                continue;
            }
            if (owner && positions.count(owner) && !wanted.count(owner) && owner->isAttachedToDocument()
                && stepName(owner, body) != member->getNameInDocument()) {
                projection.errors.push_back(
                    quoted(member) + ", a step of " + quoted(owner) + ", is in " + quoted(body)
                    + " (part id '" + studioPartId(body) + "'), a part its scope doesn't hold, and "
                    + "wasn't made there (a part copied with its steps?)"
                );
                continue;
            }
            // A step whose owner is deleted goes even when read, as the tree's delete takes it
            // (forgetDeletedEntry): nothing can bring it back but undo, and it would hold its
            // name against a new owner given the freed name (S1 skeptic, 2026-11-10). Its readers
            // fail, as Onshape's dependants of a deleted feature do
            const bool ownerGone = !owner || !owner->isAttachedToDocument();
            if (ownerGone || readersOf(member, body).empty()) {
                doomed.push_back(member);
            }
            else {
                kept[body].push_back(static_cast<Feature*>(member));
            }
        }
    }
    // The steps to make, under their names; a name another object has is an error, never a
    // suffix (step names are link anchors, parts-design.md 10.6)
    std::set<std::string> planned;
    for (auto body : bodies) {
        for (const auto& slot : projection.chains.at(body)) {
            if (!slot.isStep || stepOf(slot.entry, body)) {
                continue;
            }
            const std::string name = stepName(slot.entry, body);
            auto other = doc->getObject(name.c_str());
            if ((other && std::ranges::find(doomed, other) == doomed.end())
                || !planned.insert(name).second) {
                projection.errors.push_back(
                    "The step of " + quoted(slot.entry) + " in " + quoted(body) + " must be named '"
                    + name + "', which " + (other ? quoted(other) : std::string("another step"))
                    + " has"
                );
            }
        }
    }
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

    // 3. Remove the unwanted steps without readers, first, so the names of the steps made below
    // are free; suppress the kept ones
    for (auto member : doomed) {
        const std::string name = member->getNameInDocument();
        if (Body* body = Body::findBodyOf(member)) {
            body->removeObject(member);
        }
        doc->removeObject(name.c_str());
    }
    for (const auto& [body, steps] : kept) {
        for (auto step : steps) {
            if (!step->Suppressed.getValue()) {
                step->Suppressed.setValue(true);
            }
        }
    }

    // 4. Make the missing steps and put every Body's chain in the projected order: the projected
    // slots by their entries' places in the list, a kept step at its owner's place (or, its owner
    // gone from the list, after the member before it). A member that isn't in the chain (an anchor)
    // keeps its place; a slot already right after the one before it isn't touched. Steps move by
    // removeObject() and insertObject(), which keep the BaseFeature links; native members by
    // reorderObject(), which also re-targets their references
    struct Item
    {
        App::DocumentObject* obj;
        double key;
        bool held;
    };
    std::map<const App::DocumentObject*, std::vector<std::pair<Body*, Feature*>>> stepsByOwner;
    std::map<const Body*, std::vector<Item>> orders;
    for (auto body : bodies) {
        const auto& chain = projection.chains.at(body);
        std::vector<Item> items;
        for (const auto& slot : chain) {
            const auto at = positions.find(slot.entry);
            const double key = at == positions.end() ? size : at->second;
            if (!slot.isStep) {
                items.push_back({slot.entry, key, slot.held});
                continue;
            }
            Feature* step = stepOf(slot.entry, body);
            if (!step) {
                const std::string type = studioStepType(slot.entry);
                const std::string name = stepName(slot.entry, body);
                auto obj = doc->addObject(type.c_str(), name.c_str());
                step = freecad_cast<Feature*>(obj);
                if (!step || name != obj->getNameInDocument()) {
                    if (obj) {
                        doc->removeObject(obj->getNameInDocument());
                    }
                    return fail(type + " is not a PartDesign feature, or its name isn't '" + name
                                + "': no step for " + quoted(slot.entry));
                }
                step->StudioOwner.setValue(slot.entry);
                step->Visibility.setValue(false);
            }
            stepsByOwner[slot.entry].emplace_back(body, step);
            items.push_back({step, key, slot.held});
        }
        if (auto found = kept.find(body); found != kept.end()) {
            const auto group = body->Group.getValues();
            for (auto step : found->second) {
                Item item {step, -1.0, false};
                const auto at = positions.find(ownerOfStep(step));
                if (at != positions.end()) {
                    item.key = at->second;
                    item.held = at->second >= barAt;
                }
                else {
                    // After the projected member before it in the Group
                    auto here = std::ranges::find(group, step);
                    while (here != group.begin()) {
                        --here;
                        auto before = std::ranges::find_if(items, [here](const Item& i) {
                            return i.obj == *here;
                        });
                        if (before != items.end()) {
                            item.key = before->key + 0.5;
                            item.held = before->held;
                            break;
                        }
                    }
                }
                items.push_back(item);
            }
        }
        std::ranges::stable_sort(items, {}, &Item::key);
        orders[body] = items;

        std::vector<App::DocumentObject*> wanted;
        for (const auto& item : items) {
            wanted.push_back(item.obj);
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
                    // FreeCAD-CH ops#654 S3: the list places every member, so only obj moves (no
                    // input carried with it, as the Features list's drag, Retarget.h)
                    OnlyGivenObjects onlyObj;
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

    // 5. The steps' values from their owners; the owners' bases at their place, in scope order
    std::map<const App::DocumentObject*, std::vector<App::DocumentObject*>> basesByOwner;
    for (auto& [owner, steps] : stepsByOwner) {
        const auto at = positions.find(owner);
        const auto scope = stepPartsAt(owner,
                                       bodies,
                                       at == positions.end() ? size : at->second,
                                       positions,
                                       consumed);
        std::ranges::stable_sort(steps, {}, [&scope](const std::pair<Body*, Feature*>& step) {
            return std::ranges::find(scope, step.first) - scope.begin();
        });
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
        basesByOwner[owner] = bases;
    }
    // Each owner's bases (none when its steps are all gone); a Boolean's also hold its tool parts'
    // last solids before it (P5): its tool is their shapes at its place, and it runs again when
    // one of them changes
    for (int i = 0; i < size; ++i) {
        App::DocumentObject* entry = entries[i];
        if (Body::findBodyOf(entry)) {
            continue;
        }
        std::vector<App::DocumentObject*> bases = basesByOwner[entry];
        // A part pattern's source parts too (the part mirror, slice 9): its tool is their shapes
        // at its place
        std::vector<Body*> read;
        if (const Boolean* boolean = booleanOwner(entry)) {
            read = booleanPartsAt(boolean, bodies, i, positions, consumed).tools;
        }
        else if (isStudioPartPattern(entry)) {
            read = partPatternSourcesAt(entry, bodies, i, positions, consumed);
        }
        if (!read.empty()) {
            for (auto tool : read) {
                App::DocumentObject* last = nullptr;
                for (const auto& item : orders.at(tool)) {
                    if (item.key < i && Body::isSolidFeature(item.obj)) {
                        last = item.obj;
                    }
                }
                if (last && std::ranges::find(bases, last) == bases.end()) {
                    bases.push_back(last);
                }
            }
        }
        auto prop = freecad_cast<App::PropertyLinkList*>(entry->getPropertyByName("StudioBases"));
        if (prop && prop->getValues() != bases) {
            prop->setValues(bases);
        }
        if (isStudioPartPattern(entry)) {
            // What this projection took of its Add's consumption (resync after a recompute)
            setFlag(entry, "StudioConsumesSourceSeen", studioPartMirrorConsumes(entry));
        }
    }

    // 5b. A part consumed at the bar is hidden, as Onshape deletes it; live again (the bar above
    // its Boolean, the Boolean suppressed or deleted), it shows again. Only a Body hidden so is
    // shown again (its StudioConsumedHidden), never one the user hid (P5)
    for (auto body : bodies) {
        auto it = consumed.find(body);
        const bool gone = it != consumed.end() && it->second < barAt;
        auto marker =
            freecad_cast<App::PropertyBool*>(body->getPropertyByName("StudioConsumedHidden"));
        if (gone) {
            if (body->Visibility.getValue()) {
                if (!marker) {
                    marker = static_cast<App::PropertyBool*>(body->addDynamicProperty(
                        "App::PropertyBool",
                        "StudioConsumedHidden",
                        "Studio",
                        "Hidden because a Boolean consumes this part at the bar (ops#654)",
                        App::Prop_Hidden
                    ));
                }
                body->Visibility.setValue(false);
                marker->setValue(true);
            }
        }
        else if (marker && marker->getValue()) {
            marker->setValue(false);
            if (!body->Visibility.getValue()) {
                body->Visibility.setValue(true);
            }
        }
    }

    // 6. Each Body's Tip from the bar: its last active solid (a kept step included, so a part
    // dropped from the last feature's scope isn't rolled back by it), else its base feature
    for (auto body : bodies) {
        App::DocumentObject* tip = nullptr;
        const auto& items = orders.at(body);
        for (auto it = items.rbegin(); it != items.rend() && !tip; ++it) {
            if (!it->held && Body::isSolidFeature(it->obj)) {
                tip = it->obj;
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
    // A function of (owner name, part id), one to one (namePiece() and the "_at_" between them):
    // names are link anchors (sketch attachments, external geometry, Up to faces) and part of the
    // file format, so a step made again gets the same one (parts-design.md 10.6)
    return namePiece(owner->getNameInDocument()) + "_at_" + namePiece(studioPartId(body));
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
    return stepPartsAt(owner, bodies, index, positions, consumedBy(entries, bodies, positions));
}

// ------------------------------------------------------------------------------------------------
// Live parts and Boolean studio features (FreeCAD-CH ops#654 P5, P6a). Declared where they are
// used (no header names them: an App header change rebuilds the module)

namespace PartDesign
{
PartDesignExport std::vector<Body*> studioLivePartsAt(const StudioList* list, int index);
PartDesignExport void studioBooleanParts(const App::DocumentObject* owner,
                                         std::vector<Body*>& steps,
                                         std::vector<Body*>& tools,
                                         std::vector<Body*>& both);
PartDesignExport const App::DocumentObject* studioConsumerOf(const Body* body, int index);
}  // namespace PartDesign

/// The parts of list's studio live just before the entry at index (-1: at the bar): made by an
/// entry before it, not merged away, not consumed by a Boolean before it. The one query every
/// list of parts and every target or tool pick uses (P6a, report 26)
std::vector<Body*> PartDesign::studioLivePartsAt(const StudioList* list, int index)
{
    std::vector<Body*> out;
    if (!list || !list->getDocument()) {
        return out;
    }
    const auto bodies = studioBodies(list->getDocument(), list->studio());
    std::vector<App::DocumentObject*> entries;
    for (auto entry : list->Entries.getValues()) {
        if (entry) {
            entries.push_back(entry);
        }
    }
    const int size = static_cast<int>(entries.size());
    if (index < 0 || index > size) {
        index = std::min(list->barIndex(), size);
    }
    const auto positions = positionsOf(entries);
    const Consumed consumed = consumedBy(entries, bodies, positions);
    for (auto body : bodies) {
        if (liveAt(body, index, positions, consumed, /*before=*/true)) {
            out.push_back(body);
        }
    }
    return out;
}

/// A Boolean studio feature's parts at its place: its steps' parts, its tool parts, and the parts
/// that are a target and a tool. Empty for anything else
void PartDesign::studioBooleanParts(const App::DocumentObject* owner,
                                    std::vector<Body*>& steps,
                                    std::vector<Body*>& tools,
                                    std::vector<Body*>& both)
{
    steps.clear();
    tools.clear();
    both.clear();
    const Boolean* boolean = booleanOwner(owner);
    const StudioList* list = StudioList::holding(owner);
    if (!boolean || !list) {
        return;
    }
    const auto bodies = studioBodies(owner->getDocument(), list->studio());
    const auto& entries = list->Entries.getValues();
    const auto positions = positionsOf(entries);
    auto it = positions.find(owner);
    const int index = it == positions.end() ? static_cast<int>(entries.size()) : it->second;
    auto parts =
        booleanPartsAt(boolean, bodies, index, positions, consumedBy(entries, bodies, positions));
    steps = parts.steps;
    tools = parts.tools;
    both = parts.both;
}

/// The Boolean studio feature that consumes body before the entry at index of its list (-1: at
/// the bar), or null
const App::DocumentObject* PartDesign::studioConsumerOf(const Body* body, int index)
{
    App::Part* studio = nullptr;
    if (!body || !Part::BodyBase::studioOf(body, studio)) {
        return nullptr;
    }
    const StudioList* list = StudioList::of(body->getDocument(), studio);
    if (!list) {
        return nullptr;
    }
    const auto& entries = list->Entries.getValues();
    const int size = static_cast<int>(entries.size());
    if (index < 0 || index > size) {
        index = std::min(list->barIndex(), size);
    }
    const auto positions = positionsOf(entries);
    const Consumed consumed =
        consumedBy(entries, studioBodies(body->getDocument(), studio), positions);
    auto it = consumed.find(body);
    return it != consumed.end() && it->second < index ? entries[it->second] : nullptr;
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

// The part mirror (FreeCAD-CH ops#654 slice 9). Declared where used
namespace PartDesign
{
PartDesignExport bool isStudioPartPattern(const App::DocumentObject* obj);
PartDesignExport std::vector<Body*> studioPartPatternSources(const App::DocumentObject* owner);
}  // namespace PartDesign

/// A part pattern (PatternType Part) outside every Body: a studio feature whose tool is other
/// parts' shapes at its place
bool PartDesign::isStudioPartPattern(const App::DocumentObject* obj)
{
    auto pattern = freecad_cast<const Transformed*>(obj);
    return pattern && pattern->isAttachedToDocument() && !Body::findBodyOf(obj)
        && pattern->PatternType.getValue() == 1;
}

/// A part pattern's source parts live at its place in its list, in StudioEntities' order
std::vector<Body*> PartDesign::studioPartPatternSources(const App::DocumentObject* owner)
{
    const StudioList* list = StudioList::holding(owner);
    if (!isStudioPartPattern(owner) || !list) {
        return {};
    }
    const auto bodies = studioBodies(owner->getDocument(), list->studio());
    const auto& entries = list->Entries.getValues();
    const auto positions = positionsOf(entries);
    auto it = positions.find(owner);
    const int index = it == positions.end() ? static_cast<int>(entries.size()) : it->second;
    return partPatternSourcesAt(owner,
                                bodies,
                                index,
                                positions,
                                consumedBy(entries, bodies, positions));
}

namespace PartDesign
{
PartDesignExport void studioSetPartMirrorConsumes(App::DocumentObject* owner, bool consumes);
void registerPartMirrorResync();
}  // namespace PartDesign

bool PartDesign::studioPartMirrorConsumes(const App::DocumentObject* owner)
{
    return owner && flagOf(owner, "StudioConsumesSource");
}

void PartDesign::studioSetPartMirrorConsumes(App::DocumentObject* owner, bool consumes)
{
    if (owner) {
        setFlag(owner, "StudioConsumesSource", consumes);
    }
}

namespace
{
/// After a recompute: a part mirror whose Add decided to consume its source (or no longer) since
/// the list was last projected changes which parts live after it, so the list is reconciled and
/// the document computed again (slice 9). Not while undoing, restoring or closing
void resyncPartMirrors(const App::Document& constDoc)
{
    static bool busy = false;
    auto& doc = const_cast<App::Document&>(constDoc);
    if (busy || doc.isPerformingTransaction() || doc.testStatus(App::Document::Restoring)
        || App::GetApplication().isClosingAll()) {
        return;
    }
    std::vector<StudioList*> stale;
    for (auto obj : doc.getObjectsOfType(StudioList::getClassTypeId())) {
        auto list = static_cast<StudioList*>(obj);
        for (auto entry : list->Entries.getValues()) {
            if (entry && isStudioPartPattern(entry)
                && flagOf(entry, "StudioConsumesSource")
                    != flagOf(entry, "StudioConsumesSourceSeen")) {
                stale.push_back(list);
                break;
            }
        }
    }
    if (stale.empty()) {
        return;
    }
    Base::StateLocker lock(busy, true);
    for (auto list : stale) {
        std::string why;
        if (!list->reconcile(&why)) {
            Base::Console().warning("%s\n", why.c_str());
        }
    }
    doc.recompute();
}
}  // namespace

void PartDesign::registerPartMirrorResync()
{
    static bool registered = false;
    if (registered) {
        return;
    }
    registered = true;
    auto watch = [](const App::Document& doc) {
        const_cast<App::Document&>(doc).signalBecameStable.connect(&resyncPartMirrors);
    };
    App::GetApplication().signalNewDocument.connect(
        [watch](const App::Document& doc, bool) { watch(doc); }
    );
    for (auto doc : App::GetApplication().getDocuments()) {
        watch(*doc);
    }
}

long PartDesign::studioTagFor(const App::DocumentObject* owner, const Body* /*body*/)
{
    // The owner's ID, in every part: no stored tags (format rule, parts-design.md 10.6 and 10.10)
    return owner ? owner->getID() : 0;
}

std::string PartDesign::studioStepType(const App::DocumentObject* /*owner*/)
{
    // Every tool-making owner, and S1's shape owners; dress-ups get their own type in P8a
    return "PartDesign::FeatureApply";
}
