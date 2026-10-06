// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <string>

#include "ElementGuess.h"

namespace App
{

/** The re-target record of one sub-element reference (ops#127, notes/reorder-rollback-design.md
 * 3.4 a): a reorder put the reference's owner above the solid it was on, so the reference was
 * moved to the owner's new base; the record keeps where it was and what it named, so that moving
 * the feature back below that solid puts it back. It lives with the reference in its link property
 * (parallel to the subs, as the fingerprints), is carried by every solver write-back and by
 * save, restore, copy, paste and undo, and is cleared by any setter that drops the reference's
 * shadow (a user's re-pick, a repair), and by the restore. Saved as `rt`, `rto` and `rtfp` on the
 * sub, with the guess record it carries as `rtguess`, `rtorig` and `rtalt`.
 */
struct RetargetRecord
{
    /// The name of the object the reference was on (in the owner's document)
    std::string target;
    /// The original element's mapped name in shadow form (empty if it had none) and its index
    /// name (`Face6`)
    std::string origName;
    std::string origIndex;
    /// The original's fingerprint text (the `fp` encoding), empty if none
    std::string origFp;
    /// The reference's guess record when it was moved (N1 3.2), the elements the user rejected
    /// included: the original above is that record's original, and the restore puts the record
    /// back with it
    GuessRecord guess;

    bool empty() const
    {
        return target.empty();
    }

    /// `rto`: "<origName>,<origIndex>" (a mapped name may hold commas; an index name doesn't)
    std::string origText() const
    {
        return origName + "," + origIndex;
    }

    /// The record of the saved attributes; empty if `rt` is
    static RetargetRecord fromAttributes(const std::string& rt,
                                         const std::string& rto,
                                         const std::string& rtfp)
    {
        RetargetRecord record;
        if (rt.empty()) {
            return record;
        }
        record.target = rt;
        auto comma = rto.rfind(',');
        if (comma == std::string::npos) {
            record.origIndex = rto;
        }
        else {
            record.origName = rto.substr(0, comma);
            record.origIndex = rto.substr(comma + 1);
        }
        record.origFp = rtfp;
        return record;
    }

    bool operator==(const RetargetRecord& other) const = default;
};

}  // namespace App
