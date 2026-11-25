// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <charconv>
#include <cstdlib>
#include <string_view>
#include <vector>

#include "ElementFingerprint.h"
#include "ElementNamingUtils.h"
#include "ImportedTags.h"
#include "MappedName.h"
#include "NameTable.h"

namespace
{

// Part::OpCodes::External, the boundary section a Link or binder from another document adds (App
// can't include Part)
constexpr std::string_view externalOpCode = "EXT";

// remapElementTags() of a full V2 name (no `~` references), depth the embedding level
std::optional<std::string> remapFull(const std::string& name, const std::map<long, long>& ids, int depth)
{
    if (depth > 64 || name.empty()) {
        return std::nullopt;
    }
    // A copy: the decoding is shared, and the recursion below decodes other strings
    Data::DecodedMappedName decoded = Data::MappedName::getDecodedMappedName(name);
    if (decoded.empty() || Data::MappedName::makeEncodedName(decoded) != name) {
        return std::nullopt;
    }
    std::size_t first = 0;
    for (std::size_t i = 0; i < decoded.size(); ++i) {
        if (decoded[i].opCode == externalOpCode) {
            first = i;
        }
    }
    bool changed = false;
    auto remapList = [&](std::vector<std::string>& names) {
        const bool sorted = std::ranges::is_sorted(names);
        bool listChanged = false;
        for (auto& embedded : names) {
            if (auto remapped = remapFull(embedded, ids, depth + 1)) {
                embedded = std::move(*remapped);
                listChanged = true;
            }
        }
        if (listChanged) {
            if (sorted) {
                std::ranges::sort(names);
            }
            changed = true;
        }
    };
    for (std::size_t i = first; i < decoded.size(); ++i) {
        auto& section = decoded[i];
        long tag = 0;
        const auto& text = section.iterationTag;
        const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), tag);
        if (error == std::errc() && end == text.data() + text.size() && tag != 0) {
            auto it = ids.find(std::abs(tag));
            if (it != ids.end() && it->second != std::abs(tag)) {
                section.iterationTag = std::to_string(tag < 0 ? -it->second : it->second);
                changed = true;
            }
        }
        remapList(section.linkedNames);
        remapList(section.connectedElements);
    }
    if (!changed) {
        return std::nullopt;
    }
    return Data::MappedName::makeEncodedName(decoded);
}

// The ID a source's key gives (`<ID>` or `<ID>.<property>`), if it is this document's
std::optional<long> sourceId(const std::string& key, std::size_t& digits)
{
    if (key.find('@') != std::string::npos) {
        return std::nullopt;
    }
    long id = 0;
    const auto [end, error] = std::from_chars(key.data(), key.data() + key.size(), id);
    if (error != std::errc() || end == key.data() || (end != key.data() + key.size() && *end != '.')) {
        return std::nullopt;
    }
    digits = static_cast<std::size_t>(end - key.data());
    return id;
}

}  // namespace

std::optional<std::string> Data::remapElementTags(const std::string& name,
                                                  const std::map<long, long>& ids)
{
    if (ids.empty() || name.empty()) {
        return std::nullopt;
    }
    auto& table = NameTable::instance();
    const bool interned = name.find(NameTable::Marker) != std::string::npos;
    const std::string full = interned ? table.toPlain(name) : name;
    auto remapped = remapFull(full, ids, 0);
    if (!remapped) {
        return std::nullopt;
    }
    if (interned) {
        return table.toInterned(*remapped);
    }
    return remapped;
}

std::optional<std::string> Data::remapNameTags(const std::string& text,
                                               const std::map<long, long>& ids)
{
    if (ids.empty() || text.empty()) {
        return std::nullopt;
    }
    const char* element = findElementName(text.c_str());
    const char* mapped = isMappedElement(element);
    if (!mapped) {
        // A bare mapped name (a guess record's original): its sections hold a `;`, an index name
        // (`Face6`) none
        if (text.find(';') == std::string::npos) {
            return std::nullopt;
        }
        return remapElementTags(text, ids);
    }
    const auto start = static_cast<std::size_t>(mapped - text.c_str());
    // A mapped name holds no dot: one after it starts the index name
    auto end = text.find('.', start);
    if (end == std::string::npos) {
        end = text.size();
    }
    auto remapped = remapElementTags(text.substr(start, end - start), ids);
    if (!remapped) {
        return std::nullopt;
    }
    return text.substr(0, start) + *remapped + text.substr(end);
}

std::optional<std::string> Data::remapFingerprintIds(const std::string& text,
                                                     const std::map<long, long>& ids)
{
    if (ids.empty() || text.empty()) {
        return std::nullopt;
    }
    auto fingerprint = ElementFingerprint::fromString(text);
    if (!fingerprint.isValid() || fingerprint.toString() != text) {
        return std::nullopt;
    }
    bool changed = false;
    for (auto& mark : fingerprint.marks) {
        auto it = ids.find(mark.tag);
        if (it != ids.end() && it->second != mark.tag) {
            mark.tag = it->second;
            changed = true;
        }
    }
    for (auto& source : fingerprint.sources) {
        std::size_t digits = 0;
        auto id = source.locus == 'D' ? std::nullopt : sourceId(source.key, digits);
        if (!id) {
            continue;
        }
        auto it = ids.find(*id);
        if (it != ids.end() && it->second != *id) {
            source.key = std::to_string(it->second) + source.key.substr(digits);
            changed = true;
        }
    }
    if (!changed) {
        return std::nullopt;
    }
    // As the writers order them: the marks by ID, world and highest mark (PropertyLinks.cpp
    // sortMarks()), the sources by locus and key (ElementSolverBatch.cpp)
    std::ranges::sort(fingerprint.marks, [](const auto& a, const auto& b) {
        return a.tag < b.tag || (a.tag == b.tag && a.world() < b.world())
            || (a.tag == b.tag && a.world() == b.world() && a.mark > b.mark);
    });
    std::ranges::stable_sort(fingerprint.sources, [](const auto& a, const auto& b) {
        return a.locus != b.locus ? a.locus < b.locus : a.key < b.key;
    });
    return fingerprint.toString();
}
