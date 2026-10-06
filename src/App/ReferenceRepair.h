// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <string>

namespace App
{

class PropertyLinkBase;

/** The picker's calls on one element reference (ops#127, design note N2 section 6.1).
 *
 * \a prop is the property holding the reference (a PropertyXLinkSubList's link for its
 * references, as ReferenceReport::Slot::prop), \a localIndex its position there. Each writes as
 * the solver writes a resolution (applyResolutions(), recorded for undo inside the caller's
 * transaction), drops the property's report, clears the owner's warning and touches the owner,
 * whose next recompute derives its state from what is left. They throw Base::ValueError for a
 * reference that doesn't exist or a candidate they can't take.
 */

/// The guessed element becomes the reference: its record goes, and its fingerprint is measured
/// from the element it holds now.
AppExport void acceptReference(PropertyLinkBase* prop, int localIndex);

/** The reference takes \a candidate (an index name, e.g. `Edge9`): one of the report's candidates
 * or alternatives, or the record's original; with \a force any element of the target (a re-pick).
 * Its record and `from` go, and its fingerprint is measured from the new element.
 */
AppExport void repairReference(PropertyLinkBase* prop,
                               int localIndex,
                               const std::string& candidate,
                               bool force = false);

/// The guess is wrong and nothing else is right: the reference goes back to its original, missing
/// (`?Edge5`), and its owner fails at the next recompute. Its record becomes a rejection (kind
/// `rejected`, the rejected elements as alternatives with role `rejected`): the solver never
/// offers them for it again, its fingerprint (the rejected element's) goes, and it still snaps
/// back when the original's name gives an element again.
AppExport void markReferenceBroken(PropertyLinkBase* prop, int localIndex);

}  // namespace App
