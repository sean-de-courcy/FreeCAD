// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                               *
 *                                                                            *
 *   This file is part of the FreeCAD CAx development system.                 *
 *                                                                            *
 *   This library is free software; you can redistribute it and/or            *
 *   modify it under the terms of the GNU Library General Public              *
 *   License as published by the Free Software Foundation; either             *
 *   version 2 of the License, or (at your option) any later version.         *
 *                                                                            *
 *   This library  is distributed in the hope that it will be useful,         *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of           *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            *
 *   GNU Library General Public License for more details.                     *
 *                                                                            *
 *   You should have received a copy of the GNU Library General Public        *
 *   License along with this library; see the file COPYING.LIB. If not,       *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,            *
 *   Suite 330, Boston, MA  02111-1307, USA                                   *
 *                                                                            *
 ******************************************************************************/

#pragma once

#include <vector>

#include <TopoDS_Wire.hxx>
#include <gp_Ax3.hxx>

#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <App/PropertyUnits.h>
#include "FeatureTransformed.h"

namespace PartDesign
{

/** Onshape's Curve pattern (FreeCAD-CH ops#655, T6): the originals repeated along a path, a
 * connected chain of edges (sketch curves or model edges), the instances spaced equally by arc
 * length (Equal) or a given distance apart (Distance). The first instance is the original. The
 * path starts at its end nearest the original (a closed path: at its point nearest the original),
 * as Onshape's does (oracle 9d, CP2 and CP4); there is no flip. Each instance is the original moved
 * by the motion that takes the path's frame at its start to the frame at the instance's place:
 * with Default, the frame turns with the path's tangent (a rotation-minimizing frame, so a planar
 * path keeps its plane's normal); with Keep orientation, the original is only translated. A
 * closed path spreads Equal instances over its whole length, none on the original.
 */
class PartDesignExport CurvePattern: public PartDesign::Transformed
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::CurvePattern);

public:
    CurvePattern();

    /// The path: edges of one sketch or feature, a connected chain in any pick order. A sketch
    /// picked whole (no sub-element) gives all its edges
    App::PropertyLinkSub Path;
    /// "Equal": the instances share the path's length; "Distance": they are Distance apart
    App::PropertyEnumeration SpacingType;
    /// The arc length between two instances next to each other, with Distance spacing
    App::PropertyLength Distance;
    /// The number of instances, the original included
    App::PropertyIntegerConstraint Occurrences;
    /// How the instances turn: "Default" (with the path's tangent) or "Keep orientation"
    App::PropertyEnumeration Orientation;
    /// Skip instances: indexes from 0 at the original, as Onshape lists them. The original is
    /// never skipped; an index out of range is ignored
    App::PropertyIntegerList SkippedInstances;

    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderCurvePattern";
    }

    short mustExecute() const override;
    const std::list<gp_Trsf> getTransformations(const std::vector<App::DocumentObject*>) override;
    std::vector<std::size_t> getSkippedPositions() const override;

    /// The path is read in this feature's Body (ops#325)
    std::vector<const char*> placerProperties() const override
    {
        return {"Path"};
    }

    /** The path as one wire in this feature's coordinates, its edges ordered and oriented along
     * the chain (from its first picked edge's start). Throws Base::ValueError with the user's message when the
     * edges are missing, not edges, or don't form one connected chain
     */
    TopoDS_Wire getPathWire() const;

    /// A frame on a path: the point, the tangent (X), and the transported normal (Y)
    struct Frame
    {
        gp_Pnt point;
        gp_Dir tangent;
        gp_Dir normal;
    };
    /** The frames at the arc lengths `lengths` (ascending, each in 0..length of the wire) along
     * `wire`, the normal carried by a rotation-minimizing frame from the start (exact on lines,
     * arcs and any planar path, where it stays the plane's normal). At a corner of the chain the
     * frame turns by the smallest rotation taking one tangent to the next
     */
    static std::vector<Frame> framesAlong(const TopoDS_Wire& wire, const std::vector<double>& lengths);
    /// The motion taking frame `from` to frame `to` (Keep orientation: the translation only)
    static gp_Trsf motion(const Frame& from, const Frame& to, bool keepOrientation);

private:
    static const App::PropertyIntegerConstraint::Constraints intOccurrences;
    static const char* OrientationEnums[];
    static const char* SpacingTypeEnums[];
    /// The centre of the originals' bounding box in this feature's coordinates (with no
    /// originals, the base's): where the path's start is chosen from. False: nothing to measure
    bool seedCentre(const std::vector<App::DocumentObject*>& originals, gp_Pnt& centre);
};

}  // namespace PartDesign
