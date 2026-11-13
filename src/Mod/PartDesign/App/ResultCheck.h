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

class TopoDS_Shape;

/** The check of each solid feature's result (FreeCAD-CH, kernel safety S2), in
 * Feature::recompute(): OCCT can build an invalid solid, or a valid one of the wrong volume, without
 * an error (a fuse with a horn torus, a pocket on an inverted base), and the next features build on
 * it silently. After a feature succeeds:
 * - every solid it changed has a positive volume, and so does its base where nothing checked it;
 * - the volume follows the operation: an add doesn't shrink the part, a remove or intersect doesn't
 *   grow it (within 1e-5 of the volume);
 * - the faces it made or changed pass the shape check (BRepCheck), and the shells holding them are
 *   closed and oriented; all faces where an input of its boolean was repaired.
 * The volume's change is integrated over the changed faces only, and the base's volume is the one
 * its own check found, so the check costs what the feature changed, not the whole part. A violation
 * fails the feature with a message that says what was wrong; the recompute's continuation rule then
 * passes its base through. "User parameter:BaseApp/Preferences/Mod/PartDesign", bool
 * "CheckResults", default true, turns it off.
 */
namespace PartDesign
{
class Feature;

namespace ResultCheck
{
/// FeatureRefine notes what its refine started from (before) and gave (after): the faces that
/// refine rebuilds are compared on the shape before it
void noteRefine(const Feature* feature, const TopoDS_Shape& before, const TopoDS_Shape& after);

/// Before \a step, a check or a refine of the feature's result: when the feature's time limit has
/// passed (Part::KernelBudget::pastDeadline()), throws Base::CADKernelError, noted as a stop for
/// the feature (Part::KernelBudget::stopIfPastDeadline()), which then fails. Never skipped with a
/// warning (kernel layer step 2, notes/kernel-layer.md P4 and P5): an unchecked or unrefined
/// result would pass as "Valid", its face count differing from Onshape's silently
void stopIfPastTheLimit(const char* step);
}  // namespace ResultCheck
}  // namespace PartDesign
