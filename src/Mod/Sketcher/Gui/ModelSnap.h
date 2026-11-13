// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                            *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#pragma once

#include <optional>
#include <string>

#include <Base/Tools2D.h>

namespace App
{
class DocumentObject;
}

namespace Sketcher
{
class SketchObject;
}

namespace SketcherGui
{

class ViewProviderSketch;

/** FreeCAD-CH (ops#640, rank 18, first slice): Onshape's inference onto the model while drawing.
 * Hovering a model vertex or edge with a drawing tool wakes it: the cursor snaps to it, and the
 * point placed there gets the model element as external geometry (an implicit link, which goes
 * with its last constraint) and a Coincident (a vertex) or Point on object (an edge) to it
 * (H/Sketch/automatic_inferencing.htm; gap S17).
 *
 * The first slice reads the shapes of the sketch's support (the feature whose face the sketch is
 * on) and, in a Body, of the solid feature before the sketch (both before the sketch, so a link
 * can't make a cycle), and takes the vertices and the line and circle edges that lie in the sketch
 * plane, where the cursor on the plane and the element meet. Not yet: elements off the plane (a
 * pick in 3D), other curve types, other parts' features, the hover highlight of the element, and a
 * Parallel inference to a model edge.
 */
struct ModelSnapHit
{
    App::DocumentObject* object = nullptr;
    /// "Vertex<n>" or "Edge<n>" of object's shape
    std::string subName;
    bool isVertex = false;
    /// the snapped position, in sketch coordinates
    Base::Vector2d position;
    /// SQ2: the position is the middle of the edge (Onshape's midpoint inference)
    bool isMidpoint = false;
    /// the edge is a circular arc (its middle is a Midpoint constraint, a line's a Symmetric)
    bool isArc = false;
};

/// an edge's middle wins within this many snap tolerances along the edge (about 8 px against 5)
constexpr double modelMidpointRadius = 1.6;

/** The model element nearest pos (vertices first) within tolerance (sketch units), if any. An edge
 * whose nearest point lies within modelMidpointRadius times tolerance of its middle gives the
 * middle (SQ2: Onshape's midpoint wins about 8 px along the edge, the edge about 5 px across it).
 * The test is on the edge's nearest point, so the snapped position finds the same hit again.
 */
std::optional<ModelSnapHit> findModelSnap(const Sketcher::SketchObject* sketch,
                                          const Base::Vector2d& pos,
                                          double tolerance);

/// the snap and inference distance onto the model: about the sketch's own pick radius on screen
double modelSnapTolerance(const ViewProviderSketch& viewProvider);

/** The GeoId of the external geometry for the model element: an existing link's, or a new implicit
 * link's. A new link joins the open transaction or, with none open, a temporary booking the next
 * command (the autoconstraints') takes over, so the link and its constraint are one undo step.
 * GeoUndef when the element can't be linked (the caller then adds no constraint to it).
 */
int linkModelSnap(Sketcher::SketchObject* sketch,
                  App::DocumentObject* object,
                  const std::string& subName);

}  // namespace SketcherGui
