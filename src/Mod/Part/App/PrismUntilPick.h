// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                             *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 ****************************************************************************/

#pragma once

#include <Mod/Part/PartGlobal.h>

namespace Part
{

/** Whether the face TopoShape::makeElementPrismUntil() goes up to was picked (ops#1039, review rv540).
 *
 * Up to a picked face (Onshape's "up to face", a Pad's UpToFace or one-face UpToShape) Onshape
 * extends a cylinder, cone or sphere face to its whole surface and stops each point at its first
 * crossing (orc1125c, RB34). Up to first or last the face is the part's (O8, RB29): the prism
 * ends on the face itself, so the first-crossing rule must not move it to another part of the
 * surface. Set it, on the thread that calls makeElementPrismUntil(), for the one call:
 *
 *     Part::PrismUntilPick picked(method == "UpToFace");
 *     prism.makeElementPrismUntil(...);
 *
 * Nothing set means not picked: the first-crossing rule doesn't pre-empt BRepFeat. A header of
 * its own so that the flag doesn't change TopoShape.h, which most of the tree includes.
 */
class PartExport PrismUntilPick
{
public:
    explicit PrismUntilPick(bool picked);
    ~PrismUntilPick();
    PrismUntilPick(const PrismUntilPick&) = delete;
    PrismUntilPick& operator=(const PrismUntilPick&) = delete;

    /// The innermost guard's value on this thread, false without one
    static bool current();

private:
    bool previous;
};

}  // namespace Part
