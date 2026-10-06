// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <string>
#include <utility>
#include <vector>

#include "ElementGuess.h"

namespace App
{

class DocumentObject;
class PropertyLinkBase;

/** What the reference solver did with the references it didn't resolve exactly (ops#7).
 *
 * Process-wide, keyed by property: rebuilt per property and target on every update of the
 * target, and dropped when the property unregisters its references (a setter, a restore, its
 * destruction). Read through the owner (DocumentObject::recompute()'s check, the Python query).
 *
 * The property's state decides whether a reference is broken (a `?` sub); the report only adds
 * the candidates and the evidence.
 */
class AppExport ReferenceReport
{
public:
    enum class Status
    {
        /// Resolved by the solver (tier 1).
        Resolved,
        /// Not resolved; the reference stays missing.
        Broken,
        /// Resolved by index after an element-map version change, verified by its fingerprint.
        Index,
        /// Resolved to several elements, one reference each (Expand, Task 2 PR 7).
        Expanded,
        /// Resolved provisionally, with a saved record of the original (ops#127): by geometry
        /// (tiers 2-3), a continuation or split expanded, a naming migration's index carry, a
        /// guess. The owner computes with a warning.
        Guessed,
    };

    struct Entry
    {
        /// The reference's position in its property's sub list.
        int index = 0;
        /// The old bare mapped name and the stored index name.
        std::string oldName;
        std::string oldIndex;
        Status status = Status::Broken;
        /// The tier for Resolved (0-3), Expanded (1, or 4 for a continuation) and Guessed, -1 for
        /// Broken; Index entries have none (-1).
        int tier = -1;
        /// Guessed: the record's kind (GuessRecord::kind).
        std::string kind;
        /// The element it resolved to (Expanded: the first); empty for Broken.
        std::string newIndex;
        /// Expanded: every element, (index name, mapped name), in order.
        std::vector<std::pair<std::string, std::string>> pieces;
        /// The candidates: (index name, mapped name).
        std::vector<std::pair<std::string, std::string>> candidates;
        /// Parallel to candidates, or empty: each one's role (`place`, `name`, `piece`,
        /// `structural`, `geometric`, `index`; Data::SolveOutcome) and its centre's distance
        /// from the saved centre (NaN where unknown) (ops#105).
        std::vector<std::string> candidateRoles;
        std::vector<double> candidateDistances;
        std::string evidence;
        /// The recompute check's words for a broken reference, if not the default
        /// `Missing <type> reference: <element>` (ops#105: `Ambiguous edge reference: Edge7
        /// moved and Edge9 sits where it was`).
        std::string headline;
        /// The target's full name.
        std::string target;
    };

    /// Replaces \a prop's entries for \a target by \a entries.
    static void replace(const PropertyLinkBase* prop,
                        const std::string& target,
                        std::vector<Entry> entries);
    /// Drops all of \a prop's entries.
    static void clear(const PropertyLinkBase* prop);
    /// Moves \a prop's entries to their indices in its rebuilt sub list (remapSubIndices()): an
    /// entry follows its reference's first new index, and goes with a removed one.
    static void remap(const PropertyLinkBase* prop,
                      const std::vector<int>& firstNew,
                      const std::vector<int>& countNew);
    /// The same for \a entries, not yet in the report.
    static void remapEntries(std::vector<Entry>& entries,
                             const std::vector<int>& firstNew,
                             const std::vector<int>& countNew);
    /// \a prop's entries, sorted by index.
    static std::vector<Entry> get(const PropertyLinkBase* prop);
    /// \a prop's entry for reference \a index, or null.
    static const Entry* find(const PropertyLinkBase* prop, int index);

    static const char* statusName(Status status);

    /// One sub-element reference of an object's link-sub properties, as the user sees it.
    struct Slot
    {
        /// The property's name, and the reference's position in it (a PropertyXLinkSubList
        /// counts its links' references in order, as its getLinks() does).
        std::string property;
        int index = 0;
        /// The property the report keys the reference by, and the position there.
        const PropertyLinkBase* prop = nullptr;
        int localIndex = 0;
        /// The linked object, the old-style sub (`?Face3` when missing) and the bare mapped name
        /// its shadow holds (empty if none).
        DocumentObject* obj = nullptr;
        std::string sub;
        std::string mappedName;
        /// The reference's guess record (ops#127); empty if none.
        GuessRecord guess;
        /// Whether the property lets its owner compute on the references that resolve.
        bool partial = false;
    };
    /// Every reference of \a obj's link-sub properties (PropertyLinkSub, PropertyLinkSubList,
    /// PropertyXLink, PropertyXLinkSubList), properties by name.
    static std::vector<Slot> slotsOf(const DocumentObject* obj);

    /** True if a link property of \a obj holds a missing sub-element reference; \a why then lists
     * them, with their candidates from the report:
     * `Missing edge reference: Edge3 (Base[0], candidates: Edge7, Edge12)`, as consumers word it,
     * or with the report entry's headline (Entry::headline) in place of `Missing ...: Edge3`.
     */
    static bool describeBroken(const DocumentObject* obj, std::string& why);

    /// What the recompute check says about an object's references (ops#127).
    struct Outcome
    {
        /// The owner fails: a missing reference that its property can't do without, or a
        /// property whose every reference is missing.
        std::string fatal;
        /// The owner computes with a warning: guessed references, references resolved by
        /// geometry, and missing ones of a property that computes on the rest.
        std::string warning;
    };
    /** Describes \a obj's missing, guessed and warned references, one text per reference, joined
     * by `; `: a missing reference as describeBroken() does, in \a outcome.fatal unless its
     * property allows partial computation and one of its references resolves (then in
     * \a outcome.warning, with `computed on <n> of <m> <type>s`); a guessed one in
     * \a outcome.warning (`Guessed edge reference: Edge7 for Edge5 (Base[0], tier 3;
     * alternatives: Edge9)`). Returns true if either text is set.
     */
    static bool describe(const DocumentObject* obj, Outcome& outcome);
};

}  // namespace App
