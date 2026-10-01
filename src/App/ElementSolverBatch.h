// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <string>
#include <utility>
#include <vector>

#include "PropertyLinks.h"

namespace Data
{
struct ElementFingerprint;
}

namespace App
{

class DocumentObject;

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
        Resolved,
    };

    Status status = Status::None;
    PropertyLinkBase* prop = nullptr;
    int index = -1;
    /// Resolved: the new sub and its shadow.
    std::string sub;
    PropertyLinkBase::ShadowSub shadow;

    /// The update's context.
    DocumentObject* feature = nullptr;
    bool notify = false;
    /// Pass 1 changed the property already.
    bool touched = false;
};

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
 * 1e-7 times \a diagonal (the target's bounding box diagonal).
 */
AppExport bool fingerprintsAgree(const Data::ElementFingerprint& saved,
                                 const Data::ElementFingerprint& now,
                                 double diagonal);

/// The bare mapped name in a shadow's new-style name (`Body.;<name>.Face3` -> `<name>`), or an
/// empty string.
AppExport std::string bareMappedName(const std::string& newStyleName);

}  // namespace App
