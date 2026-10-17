// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// A container moved in the middle of a recompute (ops#342): its readers' polls run again

namespace PartDesign
{

/** A container (a Body, an App::Part) placed by an expression moves in the middle of the
 * recompute, after objects that read its contents may have polled its frame and not run: a
 * Merge (ops#325) and PartDesign's placed-elsewhere check (1b-1) kept the old result until the
 * next recompute. Once registered, every document reports each container that recomputes with
 * another Placement than it had; the objects in it and the objects outside it that link into it
 * are touched when their own mustExecute() then asks to run, and the recompute's second pass
 * runs them. A move outside a recompute needs none of this: the polls see it when they run.
 */
void registerContainerMoves();

}  // namespace PartDesign
