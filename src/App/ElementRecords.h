// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include "ElementGuess.h"
#include "ElementRetarget.h"

namespace App
{

/** The records of one sub-element reference besides its sub, shadow, fingerprint and `from`
 * (ops#127): the solver's guess record and the reorder's re-target record. A link property keeps
 * one per reference, parallel to the subs, and keeps, copies, saves and clears them together; a
 * setter keeps them only for a reference passed on with its shadow. The solver's write-back sets
 * the guess record by its own rules (SolverResolution) and keeps the re-target record, which only
 * a re-pick, a repair or the restore ends.
 */
struct ElementRecords
{
    GuessRecord guess;
    RetargetRecord retarget;

    bool empty() const
    {
        return guess.empty() && retarget.empty();
    }

    bool operator==(const ElementRecords& other) const = default;
};

}  // namespace App
