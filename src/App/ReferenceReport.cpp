// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ReferenceReport.h"

#include <algorithm>
#include <cctype>
#include <map>
#include <sstream>

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
    if (entry && !entry->headline.empty()) {
        ss << entry->headline;
    }
    else {
        ss << "Missing " << (type.empty() ? "element" : type) << " reference: " << element;
    }
    // A reference with a record (ops#127): the pick that broke, or the picks the user rejected
    const GuessRecord& guess = slot.guess;
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
        ss << "candidates: ";
        for (std::size_t i = 0; i < entry->candidates.size(); ++i) {
            ss << (i ? ", " : "") << entry->candidates[i].first;
        }
    }
    else {
        ss << "no candidates";
    }
    ss << ')';
    return ss.str();
}

// A reference with a guess record: what it holds and what it stands for, where it is, the
// evidence and the alternatives (the report entry's when the solver ran since, the record's
// otherwise: after a reopen). \a elements lists the elements of an expanded reference's pieces.
std::string guessedText(const ReferenceReport::Slot& slot,
                        const ReferenceReport::Entry* entry,
                        const std::string& elements,
                        const std::string& where)
{
    const GuessRecord& guess = slot.guess;
    const std::string original = guess.origIndex;
    const std::string type = typeOf(original.empty() ? elements : original);
    const std::string typeName = type.empty() ? "element" : type;
    std::ostringstream ss;
    if (guess.kind == "index") {
        ss << "Index reference: " << elements << " kept by its place after a naming migration";
    }
    else if (guess.kind == "tier2" || guess.kind == "tier3") {
        ss << capitalized(typeName) << " reference resolved by geometry: " << elements << " for "
           << original;
    }
    else if (guess.kind == "continued") {
        ss << capitalized(typeName) << " reference continued: " << elements << " for " << original;
    }
    else if (guess.kind == "expanded") {
        ss << capitalized(typeName) << " reference split: " << elements << " for " << original;
    }
    else {
        ss << "Guessed " << typeName << " reference: " << elements << " for " << original;
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
    else if (guess.kind != "index" && guess.kind != "expanded") {
        evidence = entry && entry->status == ReferenceReport::Status::Guessed ? entry->evidence
                                                                            : guess.kind;
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
    for (std::size_t s = 0; s < slots.size(); ++s) {
        const auto& slot = slots[s];
        auto entry = find(slot.prop, slot.localIndex);
        if (Data::hasMissingElement(slot.sub.c_str())) {
            const auto& count = counts[slot.property];
            if (!slot.partial || count.resolving == 0) {
                append(outcome.fatal, missingText(slot, entry));
                continue;
            }
            append(outcome.warning, missingText(slot, entry));
            if (count.lastMissing == static_cast<int>(s)) {
                outcome.warning += "; computed on " + std::to_string(count.resolving) + " of "
                    + std::to_string(count.total) + " " + plural(count.type);
            }
            continue;
        }
        if (slot.guess.empty()) {
            continue;
        }
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
        append(outcome.warning, guessedText(slot, entry, elements, where));
        s = last;
    }
    return !outcome.fatal.empty() || !outcome.warning.empty();
}

}  // namespace App
