// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ReferenceReport.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <map>
#include <set>
#include <sstream>

#include "Document.h"
#include "DocumentObject.h"
#include "ElementNamingUtils.h"
#include "ElementSolverBatch.h"
#include "PropertyLinks.h"

namespace App
{

namespace
{

// By property: by target's full name, the entries for that target.
using TargetEntries = std::map<std::string, std::vector<ReferenceReport::Entry>>;

std::map<const PropertyLinkBase*, TargetEntries>& reports()
{
    static std::map<const PropertyLinkBase*, TargetEntries> map;
    return map;
}

// The reorder's re-target record of a reference (ops#127), empty if none
RetargetRecord retargetOf(const PropertyLinkBase* prop, int index)
{
    std::vector<RetargetRecord> records;
    if (auto link = freecad_cast<const PropertyLinkSub*>(prop)) {
        records = link->getRetargets();
    }
    else if (auto list = freecad_cast<const PropertyLinkSubList*>(prop)) {
        records = list->getRetargets();
    }
    else if (auto xlink = freecad_cast<const PropertyXLink*>(prop)) {
        records = xlink->getRetargets();
    }
    if (index < 0 || index >= static_cast<int>(records.size())) {
        return {};
    }
    return records[index];
}

}  // namespace

void ReferenceReport::replace(const PropertyLinkBase* prop,
                              const std::string& target,
                              std::vector<Entry> entries)
{
    auto& map = reports();
    if (entries.empty()) {
        auto it = map.find(prop);
        if (it != map.end()) {
            it->second.erase(target);
            if (it->second.empty()) {
                map.erase(it);
            }
        }
        return;
    }
    map[prop][target] = std::move(entries);
}

void ReferenceReport::clear(const PropertyLinkBase* prop)
{
    auto& map = reports();
    if (!map.empty()) {
        map.erase(prop);
    }
}

void ReferenceReport::remap(const PropertyLinkBase* prop,
                            const std::vector<int>& firstNew,
                            const std::vector<int>& countNew)
{
    auto& map = reports();
    auto it = map.find(prop);
    if (it == map.end()) {
        return;
    }
    for (auto& [target, entries] : it->second) {
        remapEntries(entries, firstNew, countNew);
    }
}

void ReferenceReport::remapEntries(std::vector<Entry>& entries,
                                   const std::vector<int>& firstNew,
                                   const std::vector<int>& countNew)
{
    const int size = static_cast<int>(std::min(firstNew.size(), countNew.size()));
    std::vector<Entry> kept;
    for (auto& entry : entries) {
        if (entry.index < 0 || entry.index >= size) {
            kept.push_back(std::move(entry));
        }
        else if (countNew[entry.index] > 0) {
            entry.index = firstNew[entry.index];
            kept.push_back(std::move(entry));
        }
    }
    entries = std::move(kept);
}

std::vector<ReferenceReport::Entry> ReferenceReport::get(const PropertyLinkBase* prop)
{
    std::vector<Entry> result;
    auto& map = reports();
    auto it = map.find(prop);
    if (it == map.end()) {
        return result;
    }
    for (const auto& [target, entries] : it->second) {
        result.insert(result.end(), entries.begin(), entries.end());
    }
    std::stable_sort(result.begin(), result.end(), [](const Entry& a, const Entry& b) {
        return a.index < b.index;
    });
    return result;
}

const ReferenceReport::Entry* ReferenceReport::find(const PropertyLinkBase* prop, int index)
{
    auto& map = reports();
    auto it = map.find(prop);
    if (it == map.end()) {
        return nullptr;
    }
    for (const auto& [target, entries] : it->second) {
        for (const auto& entry : entries) {
            if (entry.index == index) {
                return &entry;
            }
        }
    }
    return nullptr;
}

const char* ReferenceReport::statusName(Status status)
{
    switch (status) {
        case Status::Resolved:
            return "resolved";
        case Status::Index:
            return "index";
        case Status::Expanded:
            return "expanded";
        case Status::Guessed:
            return "guessed";
        case Status::Broken:
        default:
            return "broken";
    }
}

std::vector<ReferenceReport::Slot> ReferenceReport::slotsOf(const DocumentObject* obj)
{
    std::vector<Slot> slots;
    if (!obj) {
        return slots;
    }
    std::vector<Property*> props;
    obj->getPropertyList(props);
    std::sort(props.begin(), props.end(), [](const Property* a, const Property* b) {
        return std::string(a->getName()) < std::string(b->getName());
    });

    auto add = [&slots](const char* name,
                        const PropertyLinkBase* key,
                        int& index,
                        int localIndex,
                        DocumentObject* target,
                        std::string sub,
                        const std::vector<PropertyLinkBase::ShadowSub>& shadows,
                        const std::vector<GuessRecord>& guesses,
                        bool partial) {
        Slot slot;
        slot.property = name;
        slot.index = index++;
        slot.prop = key;
        slot.localIndex = localIndex;
        slot.obj = target;
        slot.sub = std::move(sub);
        if (localIndex < static_cast<int>(shadows.size())) {
            slot.mappedName = bareMappedName(shadows[localIndex].newName);
        }
        if (localIndex < static_cast<int>(guesses.size())) {
            slot.guess = guesses[localIndex];
        }
        slot.partial = partial;
        slots.push_back(std::move(slot));
    };

    for (auto prop : props) {
        const char* name = prop->getName();
        if (!name) {
            continue;
        }
        int index = 0;
        if (auto link = freecad_cast<PropertyLinkSub*>(prop)) {
            int i = 0;
            const auto guesses = link->getElementGuesses();
            const bool partial = link->isPartialAllowed();
            for (auto& sub : link->getSubValues(false)) {
                add(name,
                    link,
                    index,
                    i++,
                    link->getValue(),
                    sub,
                    link->getShadowSubs(),
                    guesses,
                    partial);
            }
        }
        else if (auto list = freecad_cast<PropertyLinkSubList*>(prop)) {
            const auto& objs = list->getValues();
            auto subs = list->getSubValues(false);
            const auto guesses = list->getElementGuesses();
            for (std::size_t i = 0; i < subs.size(); ++i) {
                add(name,
                    list,
                    index,
                    static_cast<int>(i),
                    i < objs.size() ? objs[i] : nullptr,
                    subs[i],
                    list->getShadowSubs(),
                    guesses,
                    list->isPartialAllowed());
            }
        }
        else if (auto xlist = freecad_cast<PropertyXLinkSubList*>(prop)) {
            // As PropertyXLinkSubList::getLinks() counts: attached links, at least one each.
            for (const auto& child : xlist->getSubListValues()) {
                auto target = child.getValue();
                if (!target || !target->isAttachedToDocument()) {
                    continue;
                }
                auto subs = child.getSubValues(false);
                if (subs.empty()) {
                    ++index;
                    continue;
                }
                int i = 0;
                const auto guesses = child.getElementGuesses();
                for (auto& sub : subs) {
                    add(name,
                        &child,
                        index,
                        i++,
                        target,
                        sub,
                        child.getShadowSubs(),
                        guesses,
                        xlist->isPartialAllowed());
                }
            }
        }
        else if (auto xlink = freecad_cast<PropertyXLink*>(prop)) {
            int i = 0;
            const auto guesses = xlink->getElementGuesses();
            for (auto& sub : xlink->getSubValues(false)) {
                add(name,
                    xlink,
                    index,
                    i++,
                    xlink->getValue(),
                    sub,
                    xlink->getShadowSubs(),
                    guesses,
                    xlink->isPartialAllowed());
            }
        }
    }
    return slots;
}

namespace
{

// The element a sub names, without its sub-object path and without a missing mark: `Edge3`.
std::string elementOfSub(const std::string& sub)
{
    const char* found = Data::findElementName(sub.c_str());
    std::string element = found ? found : "";
    if (!element.empty() && element.front() == '?') {
        element.erase(0, 1);
    }
    return element;
}

// The lower-case element type of an index name: `Edge3` -> `edge`.
std::string typeOf(const std::string& element)
{
    std::string type = element.substr(0, element.find_first_of("0123456789"));
    std::transform(type.begin(), type.end(), type.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return type;
}

std::string plural(const std::string& type)
{
    if (type.empty()) {
        return "elements";
    }
    if (type == "vertex") {
        return "vertices";
    }
    return type + "s";
}

std::string capitalized(std::string text)
{
    if (!text.empty()) {
        text.front() = static_cast<char>(std::toupper(static_cast<unsigned char>(text.front())));
    }
    return text;
}

// A missing reference, in the consumers' words ("Missing face reference: Face3"), naming the
// element, then where the reference is and what the user may repair it to.
std::string missingText(const ReferenceReport::Slot& slot, const ReferenceReport::Entry* entry)
{
    std::ostringstream ss;
    const std::string element = elementOfSub(slot.sub);
    const std::string type = typeOf(element);
    const GuessRecord& guess = slot.guess;
    if (entry && !entry->headline.empty()) {
        ss << entry->headline;
    }
    else if (guess.kind == "rejected" && guess.origIndex.empty() && guess.origName.empty()) {
        // Mark broken on a record that lost its original (ops#268): the missing link holds the
        // rejected pick, and "Missing edge reference: Edge3, rejected: Edge3" read as a
        // contradiction
        ss << "Missing " << (type.empty() ? "element" : type) << " reference (original unknown)";
    }
    else {
        ss << "Missing " << (type.empty() ? "element" : type) << " reference: " << element;
    }
    // A reference with a record (ops#127): the pick that broke, or the picks the user rejected
    if (guess.kind == "rejected") {
        std::string picks;
        for (const auto& alternative : guess.alternatives) {
            if (alternative.role == "rejected") {
                picks += (picks.empty() ? "" : ", ") + alternative.index;
            }
        }
        if (!picks.empty()) {
            ss << ", rejected: " << picks;
        }
    }
    else if (!guess.empty() && !guess.origIndex.empty() && guess.origIndex != element) {
        ss << ", picked for " << guess.origIndex;
    }
    ss << " (" << slot.property << '[' << slot.index << "], ";
    if (entry && !entry->candidates.empty()) {
        // with each one's distance from the saved centre when known (ops#127, N3 5.3)
        ss << "candidates: ";
        for (std::size_t i = 0; i < entry->candidates.size(); ++i) {
            ss << (i ? ", " : "") << entry->candidates[i].first;
            if (i < entry->candidateDistances.size() && !std::isnan(entry->candidateDistances[i])) {
                char distance[32];
                std::snprintf(distance, sizeof(distance), "%.3g", entry->candidateDistances[i]);
                ss << " (" << distance << " mm)";
            }
        }
    }
    else {
        ss << "no candidates";
    }
    ss << ')';
    // Moved off the object it was on by a reorder (ops#127): say where it came from
    auto record = retargetOf(slot.prop, slot.localIndex);
    if (!record.empty()) {
        auto owner = slot.prop ? freecad_cast<DocumentObject*>(slot.prop->getContainer()) : nullptr;
        auto doc = owner ? owner->getDocument() : nullptr;
        auto was = doc ? doc->getObject(record.target.c_str()) : nullptr;
        if (was && !record.isTarget(was->getID())) {
            was = nullptr;  // another object took its name (ops#165)
        }
        ss << "; it was on '" << (was ? was->Label.getValue() : record.target.c_str())
           << "', which a reorder put after the feature that uses it";
    }
    return ss.str();
}

// A reference with a guess record: what it holds and what it stands for, where it is, the
// evidence and the alternatives, all from the record (so the text reads the same after a
// reopen). \a elements lists the elements of an expanded reference's pieces.
std::string guessedText(const ReferenceReport::Slot& slot,
                        const std::string& elements,
                        const std::string& where)
{
    const GuessRecord& guess = slot.guess;
    const std::string original = guess.origIndex;
    const std::string type = typeOf(original.empty() ? elements : original);
    const std::string typeName = type.empty() ? "element" : type;
    // A record can lose its original: a Part Fillet/Chamfer whose Base was replaced by one with
    // no single edge where the original was (followBase, ops#265).
    const std::string forOriginal =
        original.empty() ? std::string(", original unknown") : " for " + original;
    std::ostringstream ss;
    if (guess.kind == "index") {
        ss << "Index reference: " << elements << " kept by its place after a naming migration";
    }
    else if (guess.kind == "tier2" || guess.kind == "tier3") {
        ss << capitalized(typeName) << " reference resolved by geometry: " << elements
           << forOriginal;
    }
    else if (guess.kind == "continued") {
        ss << capitalized(typeName) << " reference continued: " << elements << forOriginal;
    }
    else if (guess.kind == "expanded") {
        ss << capitalized(typeName) << " reference split: " << elements << forOriginal;
    }
    else if (guess.kind == "piece" && elements == original) {
        // The pick is the piece that kept the original's name (G3; the Fable review of fork
        // PR 117, finding 1)
        ss << "Guessed " << typeName << " reference: kept " << original;
    }
    else {
        ss << "Guessed " << typeName << " reference: " << elements << forOriginal;
    }
    ss << " (" << where;
    // From the record, which outlives the solver's report (a reopened file), so the text is the
    // same before and after.
    std::string evidence;
    if (guess.kind == "tier2") {
        evidence = "tier 2";
    }
    else if (guess.kind == "tier3") {
        evidence = "tier 3";
    }
    else if (guess.kind == "continued") {
        evidence = "tier 4";
    }
    else if (guess.kind == "nearest") {
        evidence = "tier 3 wide";
    }
    else if (guess.kind == "geometric") {
        evidence = "tier 3 wide, no structural candidate";
    }
    else if (guess.kind == "piece") {
        evidence = "the piece at the saved centre";
    }
    if (!evidence.empty()) {
        ss << ", " << evidence;
    }
    std::vector<std::string> alternatives;
    for (const auto& alternative : guess.alternatives) {
        alternatives.push_back(alternative.index);
    }
    if (!alternatives.empty()) {
        ss << "; alternatives: ";
        for (std::size_t i = 0; i < alternatives.size(); ++i) {
            ss << (i ? ", " : "") << alternatives[i];
        }
    }
    ss << ')';
    return ss.str();
}

// The records judged found again in the same place (ops#391), by property and reference
// position: the record's identity when judged. Its original fingerprint is a snapshot, so a later
// edit that moves the element (a dimension upstream) would undo the judgement at the next
// recompute; the judgement holds while the record does.
using SamePlaceKey = std::pair<const PropertyLinkBase*, int>;
std::map<SamePlaceKey, std::string>& samePlaceRecords()
{
    static std::map<SamePlaceKey, std::string> records;
    return records;
}

// The record and the element it picked: another solve, which may pick another element with the
// same record, judges again
std::string recordIdentity(const ReferenceReport::Slot& slot)
{
    const GuessRecord& guess = slot.guess;
    return guess.kind + '\n' + guess.origText() + '\n' + guess.origFingerprint + '\n'
        + guess.altText() + '\n' + (slot.mappedName.empty() ? slot.sub : slot.mappedName);
}

// Whether the slot's reference was found again in the same place: now (reboundInPlace()), or
// when its record was judged
bool foundInPlace(const ReferenceReport::Slot& slot)
{
    auto& records = samePlaceRecords();
    const SamePlaceKey key {slot.prop, slot.localIndex};
    if (reboundInPlace(slot.obj, slot.sub, slot.guess)) {
        records[key] = recordIdentity(slot);
        return true;
    }
    auto it = records.find(key);
    return it != records.end() && it->second == recordIdentity(slot);
}

// The references a warning text names as found again in the same place (samePlaceText()), as
// (property, position): `Base[1-3, 5]` gives Base 1, 2, 3 and 5.
std::set<std::pair<std::string, int>> samePlaceNamed(const std::string& text)
{
    std::set<std::pair<std::string, int>> named;
    const std::string marker = " found again in the same place (";
    for (auto at = text.find(marker); at != std::string::npos; at = text.find(marker, at + 1)) {
        const auto open = at + marker.size();
        const auto bracket = text.find('[', open);
        const auto close = text.find("])", open);
        if (bracket == std::string::npos || close == std::string::npos || bracket > close) {
            continue;
        }
        const std::string property = text.substr(open, bracket - open);
        std::istringstream list(text.substr(bracket + 1, close - bracket - 1));
        std::string item;
        while (std::getline(list, item, ',')) {
            std::istringstream range(item);
            int first = 0;
            if (!(range >> first)) {
                continue;
            }
            int last = first;
            char dash = 0;
            if (range >> dash && dash == '-') {
                range >> last;
            }
            for (int i = first; i <= last && i - first < 100000; ++i) {
                named.emplace(property, i);
            }
        }
    }
    return named;
}

// A property's references found again in the same place (ops#391), in one text:
// `Edge reference found again in the same place (Base[1])`, `3 edge references found again in the
// same place (Base[1-3, 5])`; \a type is empty when they are of mixed types.
std::string samePlaceText(
    const std::string& property,
    const std::vector<int>& indices,
    const std::string& type
)
{
    std::ostringstream ss;
    if (indices.size() == 1) {
        ss << capitalized(type.empty() ? "element" : type) << " reference";
    }
    else {
        ss << indices.size() << ' ' << (type.empty() ? std::string("element") : type)
           << " references";
    }
    ss << " found again in the same place (" << property << '[';
    // runs of consecutive positions as `a-b`
    for (std::size_t i = 0; i < indices.size();) {
        std::size_t j = i;
        while (j + 1 < indices.size() && indices[j + 1] == indices[j] + 1) {
            ++j;
        }
        ss << (i ? ", " : "") << indices[i];
        if (j > i) {
            ss << '-' << indices[j];
        }
        i = j + 1;
    }
    ss << "])";
    return ss.str();
}

}  // namespace

bool ReferenceReport::describeBroken(const DocumentObject* obj, std::string& why)
{
    std::ostringstream ss;
    int count = 0;
    for (const auto& slot : slotsOf(obj)) {
        if (!Data::hasMissingElement(slot.sub.c_str())) {
            continue;
        }
        ss << (count++ ? "; " : "") << missingText(slot, find(slot.prop, slot.localIndex));
    }
    if (!count) {
        return false;
    }
    why = ss.str();
    return true;
}

bool ReferenceReport::describe(const DocumentObject* obj, Outcome& outcome)
{
    outcome = Outcome();
    const auto slots = slotsOf(obj);
    // Per property: how many of its references resolve, of how many, and their type.
    struct Count
    {
        int resolving = 0;
        int total = 0;
        std::string type;
        bool mixed = false;
        int lastMissing = -1;  // the slot after which the property's partial note goes
    };
    std::map<std::string, Count> counts;
    for (std::size_t s = 0; s < slots.size(); ++s) {
        const auto& slot = slots[s];
        const std::string element = elementOfSub(slot.sub);
        if (element.empty()) {
            continue;  // a whole object, not an element
        }
        auto& count = counts[slot.property];
        ++count.total;
        if (Data::hasMissingElement(slot.sub.c_str())) {
            count.lastMissing = static_cast<int>(s);
        }
        else {
            ++count.resolving;
        }
        const std::string type = typeOf(element);
        if (count.type.empty() && !count.mixed) {
            count.type = type;
        }
        else if (count.type != type) {
            count.mixed = true;
            count.type.clear();
        }
    }
    auto append = [](std::string& text, const std::string& item) {
        text += (text.empty() ? "" : "; ") + item;
    };
    // The warning's texts in order; a property's references found again in the same place share
    // one text, at its first one's position (ops#391), filled in at the end
    std::vector<std::string> warnings;
    struct SamePlace
    {
        std::size_t position = 0;
        std::vector<int> indices;
        std::string type;
        bool mixed = false;
    };
    std::map<std::string, SamePlace> samePlace;  // by property
    bool othersWarned = false;
    for (std::size_t s = 0; s < slots.size(); ++s) {
        const auto& slot = slots[s];
        auto entry = find(slot.prop, slot.localIndex);
        if (Data::hasMissingElement(slot.sub.c_str())) {
            const auto& count = counts[slot.property];
            if (!slot.partial || count.resolving == 0) {
                append(outcome.fatal, missingText(slot, entry));
                continue;
            }
            warnings.push_back(missingText(slot, entry));
            othersWarned = true;
            if (count.lastMissing == static_cast<int>(s)) {
                warnings.push_back(
                    "computed on " + std::to_string(count.resolving) + " of "
                    + std::to_string(count.total) + " " + plural(count.type)
                );
            }
            continue;
        }
        if (slot.guess.empty()) {
            samePlaceRecords().erase({slot.prop, slot.localIndex});
            continue;
        }
        if (foundInPlace(slot)) {
            auto [it, first] = samePlace.try_emplace(slot.property);
            auto& same = it->second;
            const std::string type = typeOf(elementOfSub(slot.sub));
            if (first) {
                same.position = warnings.size();
                same.type = type;
                warnings.emplace_back();
            }
            else if (same.type != type) {
                same.mixed = true;
            }
            same.indices.push_back(slot.index);
            continue;
        }
        othersWarned = true;
        // The pieces of an expanded reference carry the same record: one text for them.
        std::size_t last = s;
        std::string elements = elementOfSub(slot.sub);
        while (last + 1 < slots.size() && slots[last + 1].property == slot.property
               && slots[last + 1].guess == slot.guess && !slot.guess.origIndex.empty()
               && (slot.guess.kind == "expanded" || slot.guess.kind == "continued")
               && !Data::hasMissingElement(slots[last + 1].sub.c_str())) {
            ++last;
            elements += ", " + elementOfSub(slots[last].sub);
        }
        std::string where = slot.property + "[" + std::to_string(slot.index)
            + (last > s ? ".." + std::to_string(slots[last].index) : std::string()) + "]";
        warnings.push_back(guessedText(slot, elements, where));
        s = last;
    }
    for (const auto& [property, same] : samePlace) {
        warnings[same.position] = samePlaceText(property, same.indices, same.mixed ? "" : same.type);
    }
    for (const auto& text : warnings) {
        append(outcome.warning, text);
    }
    outcome.samePlace = !samePlace.empty() && !othersWarned;
    return !outcome.fatal.empty() || !outcome.warning.empty();
}

namespace
{
// By object: the warnings of the quieter level (ops#391)
std::set<const DocumentObject*>& samePlaceWarnings()
{
    static std::set<const DocumentObject*> objects;
    return objects;
}
}  // namespace

bool ReferenceReport::isSamePlaceWarning(const DocumentObject* obj)
{
    return samePlaceWarnings().contains(obj);
}

void ReferenceReport::setSamePlaceWarning(const DocumentObject* obj, bool on)
{
    if (on) {
        samePlaceWarnings().insert(obj);
    }
    else {
        samePlaceWarnings().erase(obj);
    }
}

bool ReferenceReport::restoredSamePlaceWarning(const DocumentObject* obj, const std::string& text)
{
    // The saved text keeps the judgement of the session that saved it, which the shapes alone
    // can't give back once an edit moved the element since (foundInPlace())
    const auto named = samePlaceNamed(text);
    if (!named.empty()) {
        for (const auto& slot : slotsOf(obj)) {
            if ((slot.guess.kind == "tier2" || slot.guess.kind == "tier3")
                && !Data::hasMissingElement(slot.sub.c_str())
                && named.contains({slot.property, slot.index})) {
                samePlaceRecords()[{slot.prop, slot.localIndex}] = recordIdentity(slot);
            }
        }
    }
    Outcome outcome;
    return describe(obj, outcome) && outcome.fatal.empty() && outcome.samePlace
        && outcome.warning == text;
}

}  // namespace App
