// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCConfig.h>

#include <limits>
#include <string>
#include <vector>

#include "ElementGuess.h"

namespace App
{

class DocumentObject;
class PropertyLinkBase;

/** One reference the picker lists (ops#127, design note N2 sections 6.1-6.2): a reference with a
 * report entry, a guess record, or a missing element. `App.getReferenceReport` returns these as
 * dicts, and the Gui's References panel shows them.
 */
struct AppExport ReferenceRow
{
    /// The property's name, and the reference's position in it, as the user sees them.
    std::string property;
    int index = 0;
    /// Where the calls below find it: the property the report keys it by, and the position there.
    PropertyLinkBase* prop = nullptr;
    int localIndex = 0;
    /// The linked object and the stored sub (`?Edge5` when missing).
    DocumentObject* obj = nullptr;
    std::string sub;
    /// `resolved`, `broken`, `index`, `expanded` or `guessed` (ReferenceReport::statusName()).
    std::string status;
    int tier = -1;
    /// The old bare mapped name, the element it holds now (empty when broken), the evidence, and
    /// the target's full name (empty without a report entry).
    std::string oldName;
    std::string newIndex;
    std::string evidence;
    std::string target;
    /// The report entry's candidates, in rank order.
    struct Candidate
    {
        std::string index;
        std::string name;
        std::string role;
        double distance = std::numeric_limits<double>::quiet_NaN();
    };
    std::vector<Candidate> candidates;
    /// An expansion's elements (index names).
    std::vector<std::string> pieces;
    /// The guess record: its kind (empty if none), the original and the alternatives. Without a
    /// record, the original is the report entry's old element, if there is an entry.
    std::string guessKind;
    bool hasOriginal = false;
    std::string originalIndex;
    std::string originalName;
    std::vector<GuessRecord::Alternative> alternatives;
    /// The recompute check's words for it, if not the default.
    std::string headline;
};

/// The references of \a obj's link-sub properties that the picker lists, properties by name.
AppExport std::vector<ReferenceRow> referenceRows(const DocumentObject* obj);

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
