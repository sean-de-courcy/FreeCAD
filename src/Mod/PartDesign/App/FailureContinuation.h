// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <string>

#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class DocumentObject;
}

namespace PartDesign
{

/** Is one of `owner`'s inputs in error, so that `owner` must fail without running (ops#126)?
 *
 * Every link property counts except a hidden one, `ExpressionEngine`, `_Body` and a `BaseFeature`
 * that links a solid feature (a failed one passed its base through, or its failure stopped this
 * one already). An input in error is allowed only when it
 * is a solid feature of a Body referenced by element (a non-empty sub such as `Face6`): the
 * element is judged on its pass-through shape. Otherwise returns true with `why` naming the
 * property and the input.
 */
PartDesignExport bool inputInError(const App::DocumentObject* owner, std::string& why);

/// Install PartDesign's rule for failures inside a Body (App::setRecomputeContinuation): a failed
/// member whose result would be real and current is claimed, and a claimed solid feature passes its
/// base shape through, so the Body continues past it. A solid feature is claimed when its base holds
/// a solid and is Valid or a claimed failure, up its BaseFeature chain. A subtractive feature,
/// dress-up or pattern, or a feature whose failure is the park's (a reorder set a reference of it
/// aside), first naming no base or on a current base without a solid, passes the empty shape
/// (ops#591, ops#596); any other member when none of its inputs is an unclaimed failure (ops#579,
/// decision 262).
void registerFailureContinuation();

}  // namespace PartDesign
