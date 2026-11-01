// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <Base/Vector3D.h>

#include "ElementFingerprint.h"
#include "ElementRecords.h"
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
    /// another element again, and this entry is a probe, exact on that one, beside the entry of
    /// the element held (if the reference has one); \a guessedIndex is the element the sub holds
    /// (empty if that is gone). The probe is never solved: the reference snaps back to its
    /// element only if that agrees with the record's original fingerprint (ops#133); otherwise
    /// the probe is dropped and the reference is solved as the element it holds.
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
    /// Resolved by a repair (the user picked the element): the reorder's re-target record ends
    /// too (ops#127). Every other resolution keeps it.
    bool clearRetarget = false;

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
 * except a Broken one's, which it keeps unless clearFingerprint is set. \a records, if given, are
 * the references' records (ops#127). Their guess record: Guessed (ops#127) replaces a reference as
 * Resolved does, or by its pieces as Expanded does, and sets it (skipped, as a piece is, when
 * another reference holds its element: ops#138); Broken sets the resolution's
 * (empty, or the one it carries); every other written reference loses it. Their re-target record:
 * every resolution keeps it (each piece of an expanded reference carries it), unless
 * clearRetarget is set. Sets \a firstNew and \a countNew per old index. Returns true if anything
 * was written.
 */
AppExport bool rebuildSubList(const std::vector<SolverResolution>& resolutions,
                              std::vector<std::string>& subs,
                              std::vector<PropertyLinkBase::ShadowSub>& shadows,
                              std::vector<std::string>& fingerprints,
                              std::vector<std::string>& froms,
                              std::vector<int>& firstNew,
                              std::vector<int>& countNew,
                              std::vector<ElementRecords>* records = nullptr);

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

/** Whether \a point lies over the face \a element (`Face7`) of \a geo's shape, within
 * \a distance: its nearest point on the face is inside the face, not on its boundary (ops#360,
 * PR 340 round 4). False for another element type, or when it can't be told. Part sets it;
 * without it no point lies over any face.
 */
using ElementHoldsPointFunction
    = bool (*)(const GeoFeature* geo, const char* element, const Base::Vector3d& point, double distance);
AppExport void setElementHoldsPointFunction(ElementHoldsPointFunction function);

/** Whether the line through \a point along the unit \a along meets the face \a element of
 * \a geo's shape inside it, not on its boundary, within \a distance of the point (PR 366 round 8):
 * the point seen along a Pad's sweep lies over the face. False for another element type, or when
 * it can't be told. Part sets it; without it ElementHoldsPointFunction stands for it.
 */
using ElementHoldsPointAlongFunction = bool (*)(const GeoFeature* geo,
                                                const char* element,
                                                const Base::Vector3d& point,
                                                const Base::Vector3d& along,
                                                double distance);
AppExport void setElementHoldsPointAlongFunction(ElementHoldsPointAlongFunction function);

/** The direction the element named \a name (a mapped name; null: \a geo itself) was swept along,
 * in the frame \a geo's fingerprints are measured in, either sense (PR 366 round 6): a Pad's or
 * Pocket's. ops#524 (PLAN decision 182, N2): a far piece's name names the extrusion that made it
 * (its projection's tag), which may be an earlier feature of \a geo's BaseFeature chain; its
 * direction is turned into \a geo's frame. False for another feature. PartDesign sets it; without
 * it no feature has one.
 */
using ElementSweepDirectionFunction
    = bool (*)(const GeoFeature* geo, const char* name, Base::Vector3d& direction);
AppExport void setElementSweepDirectionFunction(ElementSweepDirectionFunction function);

/** The up-to faces that the line through \a point along the sweep of the far piece named \a name
 * meets, inside them or on their boundary (ops#522, PLAN decision 168), each as
 * Data::ElementFingerprint::UpToFace has it: its owner, and its box, area and normal at the point,
 * its outer wire's centre and the foot (where the line meets it) in the owner's own frame. The up-to
 * faces are those of the extrusion that made the piece (ElementSweepDirectionFunction), on \a geo
 * or before it (ops#524, N2). \a point is in the frame \a geo's fingerprints are measured in,
 * carried by \a geo's current placement, so a point saved before a profile moved by placement
 * moves with it. With \a all, every up-to face too, under the point or not. False when it can't
 * be told: no such extrusion, not a one-sided extrusion up to a face or a shape, an up-to face that
 * is unbounded (a datum plane), or \a geo's shape not made under its current placement. True with
 * no face when the line meets none. PartDesign sets it; without it no point has an up-to face.
 */
using ElementUpToFacesFunction
    = bool (*)(const GeoFeature* geo,
               const char* name,
               const Base::Vector3d& point,
               std::vector<Data::ElementFingerprint::UpToFace>& faces,
               std::vector<Data::ElementFingerprint::UpToFace>* all);
AppExport void setElementUpToFacesFunction(ElementUpToFacesFunction function);

/** Whether a lone far piece named \a name moved within its up-to face (ops#524, PLAN decisions 182
 * and 199 (3)): the line through \a point (as ElementUpToFacesFunction's) meets one face of
 * \a saved's owner inside it, not on its boundary, and so does the line through \a saved's foot;
 * then true when no boundary edge of that face meets the strip the segment between the two
 * meetings spans along the sweep, seen in the owner's own frame, and false when one does. Empty
 * when it can't be told: no foot, no such meeting or two, an end on the boundary, only a seam
 * edge met, a failed section. PartDesign sets it; without it nothing can be told.
 */
using ElementUpToPathFunction
    = std::optional<bool> (*)(const GeoFeature* geo,
                              const char* name,
                              const Data::ElementFingerprint::UpToFace& saved,
                              const Base::Vector3d& point);
AppExport void setElementUpToPathFunction(ElementUpToPathFunction function);

/** ElementUpToFacesFunction's answer for the far piece \a element (`Face7`) of \a geo's shape,
 * whose fingerprint is \a fingerprint, at its inside point or else its centre: false when the
 * element isn't a far piece (none of its names is a marked projection, PRJ and MOD), has no
 * such point, or no function is set.
 */
AppExport bool elementUpToFaces(
    const GeoFeature* geo,
    const char* element,
    const Data::ElementFingerprint& fingerprint,
    std::vector<Data::ElementFingerprint::UpToFace>& faces
);

/** The mean of the centres of \a element (`Face7`) of \a geo's shape and of its twins, and their
 * number (ops#360, PR 340 round 5): the elements of its type with a name that is one of its
 * names up to an order key (Data::isTwinName(), ops#503 D1). Each centre as the element's
 * fingerprint measures it. Without twins, \a count 1 and \a centroid untouched if one of its
 * names is keyed by its order (Data::isOrderKeyedName()): a lone member. False otherwise, and
 * when the twins can't be measured.
 */
AppExport bool elementTwinCentroid(
    const GeoFeature* geo,
    const char* element,
    Base::Vector3d& centroid,
    int& count
);

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

/** Whether a reference resolved by geometry was found again in the same place (ops#391,
 * decision 97 D): \a guess is a `tier2` or `tier3` record with the original's fingerprint, the
 * element \a sub gives in \a obj sits where the original was (Data::atSamePlace(), with the
 * solver's tolerances and the target's diagonal) and none of the record's alternatives sits
 * there too. From the saved record and the current shape alone, so it reads the same after a
 * reopen. False for any other record, and when anything can't be measured.
 */
AppExport bool reboundInPlace(DocumentObject* obj, const std::string& sub, const GuessRecord& guess);

}  // namespace App
