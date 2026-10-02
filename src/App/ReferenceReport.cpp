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
                        const std::vector<PropertyLinkBase::ShadowSub>& shadows) {
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
            for (auto& sub : link->getSubValues(false)) {
                add(name, link, index, i++, link->getValue(), sub, link->getShadowSubs());
            }
        }
        else if (auto list = freecad_cast<PropertyLinkSubList*>(prop)) {
            const auto& objs = list->getValues();
            auto subs = list->getSubValues(false);
            for (std::size_t i = 0; i < subs.size(); ++i) {
                add(name,
                    list,
                    index,
                    static_cast<int>(i),
                    i < objs.size() ? objs[i] : nullptr,
                    subs[i],
                    list->getShadowSubs());
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
                for (auto& sub : subs) {
                    add(name, &child, index, i++, target, sub, child.getShadowSubs());
                }
            }
        }
        else if (auto xlink = freecad_cast<PropertyXLink*>(prop)) {
            int i = 0;
            for (auto& sub : xlink->getSubValues(false)) {
                add(name, xlink, index, i++, xlink->getValue(), sub, xlink->getShadowSubs());
            }
        }
    }
    return slots;
}

bool ReferenceReport::describeBroken(const DocumentObject* obj, std::string& why)
{
    std::ostringstream ss;
    int count = 0;
    for (const auto& slot : slotsOf(obj)) {
        if (!Data::hasMissingElement(slot.sub.c_str())) {
            continue;
        }
        // In the consumers' words ("Missing face reference: Face3"), naming the element, then
        // where the reference is and what the user may repair it to.
        std::string element = Data::findElementName(slot.sub.c_str());
        if (!element.empty() && element.front() == '?') {
            element.erase(0, 1);
        }
        std::string type = element.substr(0, element.find_first_of("0123456789"));
        std::transform(type.begin(), type.end(), type.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        ss << (count++ ? "; " : "") << "Missing " << (type.empty() ? "element" : type)
           << " reference: " << element << " (" << slot.property << '[' << slot.index << "], ";
        auto entry = find(slot.prop, slot.localIndex);
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
    }
    if (!count) {
        return false;
    }
    why = ss.str();
    return true;
}

}  // namespace App
