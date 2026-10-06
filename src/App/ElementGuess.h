// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <cmath>
#include <cstdio>
#include <limits>
#include <string>
#include <vector>

namespace App
{

/** The saved record of a reference the solver resolved provisionally (ops#127, ops#107; design
 * note N2 section 3): a guess, a resolution by geometry (tiers 2-3), a continuation or split
 * expanded, or a naming migration's index carry. Its owner computes with a warning while it is
 * set.
 *
 * The reference's sub and shadow name the element picked, and the reference follows that element
 * as any resolved one does (by name, with its own fingerprint); the record keeps the original
 * reference. When the original's name gives an element again, the reference snaps back to it and
 * the record goes. Accepting it, a repair, marking it broken or any setter clears it too. Saved
 * as the `guess`, `orig` and `alt` attributes of the reference, in solver documents only.
 */
struct GuessRecord
{
    /// One other element the reference could be: its index name, why it is one (`structural`,
    /// `geometric`, `piece`, `place`, ...) and its centre's distance from the saved centre (NaN
    /// where unknown).
    struct Alternative
    {
        std::string index;
        std::string role;
        double distance = std::numeric_limits<double>::quiet_NaN();

        bool operator==(const Alternative& other) const
        {
            return index == other.index && role == other.role
                && (distance == other.distance
                    || (std::isnan(distance) && std::isnan(other.distance)));
        }
    };

    /// `nearest`, `geometric`, `piece` (the guess rules), `tier2`, `tier3`, `continued`,
    /// `expanded`, `index`; empty: no record.
    std::string kind;
    /// The original reference: its bare mapped name as the shadow held it (empty if it had none)
    /// and its index name.
    std::string origName;
    std::string origIndex;
    /// The other elements, in rank order (the picked one is not among them).
    std::vector<Alternative> alternatives;

    bool empty() const
    {
        return kind.empty();
    }

    bool operator==(const GuessRecord& other) const
    {
        return kind == other.kind && origName == other.origName && origIndex == other.origIndex
            && alternatives == other.alternatives;
    }
    bool operator!=(const GuessRecord& other) const
    {
        return !(*this == other);
    }

    /// The `orig` attribute: the original in shadow form, `;<name>.<index>`, or the index alone.
    std::string origText() const
    {
        return origName.empty() ? origIndex : ";" + origName + "." + origIndex;
    }

    /// The `alt` attribute: `index|role|distance` per alternative, joined by `,` (the distance
    /// with 6 significant digits, empty when unknown).
    std::string altText() const
    {
        std::string text;
        for (const auto& alternative : alternatives) {
            if (!text.empty()) {
                text += ',';
            }
            text += alternative.index + '|' + alternative.role + '|';
            if (!std::isnan(alternative.distance)) {
                char buffer[32];
                std::snprintf(buffer, sizeof(buffer), "%.6g", alternative.distance);
                text += buffer;
            }
        }
        return text;
    }

    /// The record read back from the three attributes; empty if \a kind is.
    static GuessRecord fromAttributes(const std::string& kind,
                                      const std::string& orig,
                                      const std::string& alt)
    {
        GuessRecord record;
        if (kind.empty()) {
            return record;
        }
        record.kind = kind;
        if (!orig.empty() && orig.front() == ';') {
            auto dot = orig.rfind('.');
            if (dot != std::string::npos && dot > 0) {
                record.origName = orig.substr(1, dot - 1);
                record.origIndex = orig.substr(dot + 1);
            }
            else {
                record.origName = orig.substr(1);
            }
        }
        else {
            record.origIndex = orig;
        }
        std::size_t start = 0;
        while (start < alt.size()) {
            std::size_t end = alt.find(',', start);
            if (end == std::string::npos) {
                end = alt.size();
            }
            const std::string item = alt.substr(start, end - start);
            start = end + 1;
            if (item.empty()) {
                continue;
            }
            Alternative alternative;
            std::size_t bar = item.find('|');
            alternative.index = item.substr(0, bar);
            if (bar != std::string::npos) {
                std::size_t bar2 = item.find('|', bar + 1);
                alternative.role = bar2 == std::string::npos ? item.substr(bar + 1)
                                                             : item.substr(bar + 1, bar2 - bar - 1);
                if (bar2 != std::string::npos && bar2 + 1 < item.size()) {
                    try {
                        alternative.distance = std::stod(item.substr(bar2 + 1));
                    }
                    catch (...) {
                        alternative.distance = std::numeric_limits<double>::quiet_NaN();
                    }
                }
            }
            record.alternatives.push_back(std::move(alternative));
        }
        return record;
    }
};

}  // namespace App
