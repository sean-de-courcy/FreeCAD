// SPDX-License-Identifier: LGPL-2.1-or-later

#include "RecomputeContinuation.h"

#include <Base/Console.h>

FC_LOG_LEVEL_INIT("App", true, true)

namespace App
{

namespace
{
// Set at module load and not changed afterwards, so the async recompute's worker thread reads it
// without a lock
std::shared_ptr<const RecomputeContinuation>& continuationRule()
{
    static std::shared_ptr<const RecomputeContinuation> rule;
    return rule;
}
}  // namespace

void setRecomputeContinuation(std::shared_ptr<const RecomputeContinuation> rule)
{
    auto& current = continuationRule();
    if (current && rule && current != rule) {
        FC_WARN("Replacing the recompute continuation rule");
    }
    current = std::move(rule);
}

std::shared_ptr<const RecomputeContinuation> recomputeContinuation()
{
    return continuationRule();
}

}  // namespace App
