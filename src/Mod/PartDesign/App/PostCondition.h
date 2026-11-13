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

#include <TopoDS_Compound.hxx>
#include <TopoDS_Shape.hxx>

/** Per-feature post-conditions, report-only (FreeCAD-CH, kernel layer, notes/kernel-layer.md
 * section 1; thresholds from notes/census.md "The checks as per-feature post-conditions"). After a
 * solid feature's result passed its check (ResultCheck.h), four conditions are measured and logged.
 * They never throw, never fail the feature and never change its result:
 * - tol:  the result's largest edge or vertex tolerance is over 1e-3 mm and over 10 times its base's;
 * - type: a face the feature made is a B-spline, Bezier, extrusion, revolution or offset surface that
 *         lies within 1e-7 mm of a plane, cylinder, cone, sphere or torus (a degraded form). A
 *         revolved circle (a torus by construction) is counted apart, not flagged;
 * - dv:   an additive or subtractive feature, a Boolean or a pattern changes the volume by no more
 *         than 1e-6 of it + 1e-6 mm^3;
 * - bop:  OCCT's argument analyzer (self-interference and curve-on-surface only) finds a fault among
 *         the faces the feature made and the faces next to them.
 * Off unless FREECAD_CH_POSTCOND_LOG names a file (an absolute path): one JSON line per feature is
 * appended to it, with each check's numbers, flag and time.
 */
namespace PartDesign
{
class Feature;
namespace PostCondition
{
/// What the result check saw, for the post-conditions to read (copies of nothing: the document's
/// own shapes, read on the feature's thread after its execute)
struct Observed
{
    /// Set where the result check read a new result (not the one it vouched for before)
    bool fresh {false};
    TopoDS_Shape base;
    /// The shape the faces were compared on: the result, or what its refine started from
    TopoDS_Shape checked;
    /// The faces of checked that base doesn't have
    TopoDS_Compound made;
    /// The volume's change, where the result check integrated it against a known base volume
    bool volumeKnown {false};
    double change {0.0};
    double after {0.0};
};

/// Whether the post-conditions run (FREECAD_CH_POSTCOND_LOG is set)
bool enabled();

/// Measures and logs the post-conditions of \a feature's result. Never throws
void report(Feature& feature, const Observed& observed) noexcept;
}  // namespace PostCondition
}  // namespace PartDesign
