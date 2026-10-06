// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <string>
#include <utility>
#include <vector>

#include <Base/Vector3D.h>

#include "ElementFingerprint.h"
#include "ElementGuess.h"
#include "PropertyLinks.h"

namespace App
{

class DocumentObject;
class GeoFeature;

/** One sub-element reference seen by pass 1 of the reference solver (ops#7, Task 2 PR 3).
 *
 * Pass 1 (PropertyLinkBase::collectElementReferences()) runs the exact lookup on every
 * reference of a property and records the outcome here: a reference whose element is missing
 * (just now, or already before), or one that resolved exactly. Pass 2 keeps only those whose
 * target is the feature being updated.
 */
struct AppExport SolverEntry
{
    enum class Kind
    {
        /// The reference's element doesn't exist: the sub is `?<index>`.
        Missing,
        /// The reference resolved exactly (tier 0).
        Exact,
    };

    Kind kind = Kind::Missing;
    /// The property holding the reference (a PropertyXLinkSubList's child for its references).
    PropertyLinkBase* prop = nullptr;
    /// The reference's position in the property's sub list.
    int index = 0;
    /// The linked object the sub is relative to, and the property's owner.
    DocumentObject* obj = nullptr;
    DocumentObject* owner = nullptr;
    /// The sub as pass 1 left it, and the sub-object path before the element, e.g.
    /// `Body.Pad.` (often empty).
    std::string sub;
    std::string prefix;
    /// Missing: the old bare mapped name (empty for an index-only reference).
    std::string oldName;
    /// Missing: the stored index name (`Face3` for `?Face3`). Exact: the resolved element.
    std::string oldIndex;
    /// The reference's saved fingerprint text; empty if none.
    std::string oldFingerprint;
    PropertyLinkBase::ElementPolicy policy = PropertyLinkBase::ElementPolicy::One;
    /// Exact: the bare mapped name the reference holds.
    std::string exactName;
    /// Exact: the index the reference was stored at before pass 1's lookup (which writes the
    /// resolved element's): a naming migration's choice among elements at its place (ops#103).
    std::string storedIndex;
    /// The bare mapped name the reference was expanded from (Task 2 PR 7); empty if none, and
    /// always in a property that keeps no `from` (only PropertyLinkSub does).
    std::string from;
    /// The reference's guess record (ops#127), if it holds one: the entry is the element the
    /// reference holds, and a resolution keeps the record. \a guessed: the original's name gives
    /// an element again, and the entry is exact on that one instead (the snap-back); then
    /// \a guessedIndex is the element the sub holds (empty if that is gone).
    bool guessed = false;
    std::string guessedIndex;
    GuessRecord guess;
};

/// What pass 1 gathers for one update of one feature.
struct AppExport SolverBatch
{
    DocumentObject* feature = nullptr;
    bool reverse = false;
    bool notify = false;
    std::vector<SolverEntry> entries;
    /// The properties pass 1 visited, in order, and whether it changed them already (the exact
    /// lookup rewrote a sub, after aboutToSetValue() when notifying).
    std::vector<std::pair<PropertyLinkBase*, bool>> properties;
};

/** A resolution written back by PropertyLinkBase::applyResolutions().
 *
 * Every call gets at least one item, so that a property changed in pass 1 completes its
 * notification; an item with status None carries only the context.
 */
struct AppExport SolverResolution
{
    enum class Status
    {
        None,
        /// The reference names one element: sub and shadow.
        Resolved,
        /// The reference becomes one per element (Expand, Task 2 PR 7): pieces, each with
        /// `from`. Only PropertyLinkSub receives it.
        Expanded,
        /// An exact reference breaks (a continuation under One or Equivalent, or a run-past):
        /// sub and shadow are its missing form, and it keeps its fingerprint.
        Broken,
        /// The reference goes (a collapsing group's other members). Only PropertyLinkSub
        /// receives it.
        Removed,
        /// The reference names one element provisionally (ops#127): sub and shadow as for
        /// Resolved, with \a guess, the record of the original. With \a pieces it becomes one
        /// per element, as for Expanded, each with the record.
        Guessed,
    };

    Status status = Status::None;
    PropertyLinkBase* prop = nullptr;
    int index = -1;
    /// Resolved and Broken: the new sub and its shadow.
    std::string sub;
    PropertyLinkBase::ShadowSub shadow;
    /// Expanded: the sub and shadow of each element, in order, and their `from`.
    std::vector<std::pair<std::string, PropertyLinkBase::ShadowSub>> pieces;
    std::string from;
    /// Resolved by a collapse: the reference's `from` is cleared.
    bool clearFrom = false;
    /// Broken: the reference's fingerprint is cleared too (a pick the user rejected: its
    /// fingerprint is the rejected element's, ops#127).
    bool clearFingerprint = false;
    /// Guessed: the record. Resolved and Broken always clear a reference's record (ops#127).
    GuessRecord guess;

    /// The update's context.
    DocumentObject* feature = nullptr;
    bool notify = false;
    /// Pass 1 changed the property already.
    bool touched = false;

    /// Set on the first item by a property that rebuilt its sub list (rebuildSubList()): per
    /// old index, the first new index and the count (0: removed). Empty otherwise.
    mutable std::vector<int> firstNew;
    mutable std::vector<int> countNew;
};

/** Rebuilds the parallel lists of a PropertyLinkSub from \a resolutions (Task 2 PR 7):
 * Resolved and Broken replace a reference, Expanded replaces it by its pieces (a piece whose
 * element another reference of the new list or an untouched one already holds is skipped),
 * Removed drops it. Fingerprints of written references are emptied (the caller refreshes them),
 * except a Broken one's, which it keeps unless clearFingerprint is set. Guessed (ops#127) replaces
 * a reference as Resolved does, or by its pieces as Expanded does, and sets its record in
 * \a guesses; Broken sets the resolution's record (empty, or the one it carries); every other
 * written reference loses its record. \a retargets, if given, are the reorder's re-target records
 * (ops#127): every resolution keeps its reference's record, and each piece of an expanded
 * reference carries it. Sets \a firstNew and \a countNew per old index. Returns true if anything
 * was written.
 */
AppExport bool rebuildSubList(const std::vector<SolverResolution>& resolutions,
                              std::vector<std::string>& subs,
                              std::vector<PropertyLinkBase::ShadowSub>& shadows,
                              std::vector<std::string>& fingerprints,
                              std::vector<std::string>& froms,
                              std::vector<int>& firstNew,
                              std::vector<int>& countNew,
                              std::vector<GuessRecord>* guesses = nullptr,
                              std::vector<RetargetRecord>* retargets = nullptr);

/// The indices \a mapped (of the old list) in a rebuilt list: each old index m becomes
/// firstNew[m] .. firstNew[m] + countNew[m] - 1, a removed one disappears.
AppExport std::vector<int> remapSubIndices(const std::vector<int>& mapped,
                                           const std::vector<int>& firstNew,
                                           const std::vector<int>& countNew);

/** The reference solver for \a props' references to \a feature's elements: pass 1 (collect, the
 * exact lookup), pass 2 (tiers 0-1 and forced matching per owner, Data::solveOwner()), the
 * write-back, the log and the ReferenceReport. For properties in solver documents only.
 *
 * Returns true if a property changed.
 */
AppExport bool solveElementReferences(DocumentObject* feature,
                                      const std::vector<PropertyLinkBase*>& props,
                                      bool reverse,
                                      bool notify);

/** The reverse update's check (an element-map version change): the element now at a
 * reference's old index is its old element if the fingerprints have the same type and kind, the
 * sizes and radii agree within 1e-9 relative, the directions within 1e-9, and the centres within
 * 1e-7 times \a diagonal (the target's bounding box diagonal), and so do circles' centres and
 * planes' extents when both have one.
 */
AppExport bool fingerprintsAgree(const Data::ElementFingerprint& saved,
                                 const Data::ElementFingerprint& now,
                                 double diagonal);

/** A cheap description of an element (ops#105), for the moved-element check's scan: its type,
 * kind, direction and radii (and a circle's centre) as its fingerprint has them, without the
 * size, centre or extent, and a point of a plane face's plane, a line edge's line or a vertex.
 */
struct AppExport ElementHint
{
    bool valid = false;
    Data::ElementFingerprint intrinsic;
    Base::Vector3d anchor;
    bool hasAnchor = false;
};

/** Fills \a hints with every element of \a type (`Face`, `Edge`, `Vertex`) of \a geo's shape:
 * hints[k - 1] for `<type>k`. Returns false when it gives none (another kind of feature, a
 * sketch's internal elements). Part sets it; without it every element is fingerprinted.
 */
using ElementHintsFunction = bool (*)(const GeoFeature* geo,
                                      const char* type,
                                      std::vector<ElementHint>& hints);
AppExport void setElementHintsFunction(ElementHintsFunction function);

/// The bare mapped name in a shadow's new-style name (`Body.;<name>.Face3` -> `<name>`), or an
/// empty string.
AppExport std::string bareMappedName(const std::string& newStyleName);

/// What a reverse update (an element map version change, e.g. a naming migration: ops#103) did
/// to one reference: kept on its name's element, moved to the element its old geometry gives,
/// or broken.
enum class MigrationOutcome
{
    Kept,
    Moved,
    Broken,
};

/// Counts \a outcome for \a owner's document, for reportReferenceMigration().
AppExport void countReferenceMigration(const DocumentObject* owner, MigrationOutcome outcome);

/// One warning per document with its counts since the last call, if any; clears them. Called at
/// the end of each recompute.
AppExport void reportReferenceMigration();

}  // namespace App
