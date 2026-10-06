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
 * Every link property counts except `ExpressionEngine`, `_Body` and a `BaseFeature` that links a
 * solid feature (a failed one passed its base through). An input in error is allowed only when it
 * is a solid feature of a Body referenced by element (a non-empty sub such as `Face6`): the
 * element is judged on its pass-through shape. Otherwise returns true with `why` naming the
 * property and the input.
 */
PartDesignExport bool inputInError(const App::DocumentObject* owner, std::string& why);

/// Install PartDesign's rule for failures inside a Body (App::setRecomputeContinuation): a failed
/// member doesn't stop the recompute, a failed solid feature passes its base shape through.
void registerFailureContinuation();

}  // namespace PartDesign
