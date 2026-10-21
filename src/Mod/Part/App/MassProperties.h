// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <GProp_GProps.hxx>

#include <Mod/Part/PartGlobal.h>

class TopoDS_Shape;

/** Volume and area that stay right on faces with many curved B-spline spans (FreeCAD-CH,
 * ops#414).
 *
 * OCCT's default BRepGProp integration takes a fixed number of Gauss points per face, whatever
 * the face's knot spans, so a face carrying a curved B-spline with more than about 80 to 200 spans
 * is under-sampled: a long pipe's volume was +26 % or -31 %, a Pad's -300 %, a planar face's area
 * -426 %, all on geometry that is right. The adaptive Gauss-Kronrod method at 1e-6 is right on all
 * of them. Here a cheap screen of the faces picks the method: OCCT's default when no face carries
 * such a B-spline, so ordinary shapes get the same numbers bit for bit, and the adaptive method
 * otherwise.
 *
 * For the code whose decisions depend on a volume or an area (Refine's orientation, FilletFallback,
 * TopoShapeRepair). The reported Shape.Volume and Shape.Area stay OCCT's default for now (PLAN
 * decision 106). */
namespace Part::MassProperties
{

/// A face's B-spline needs the adaptive method when it has more knot spans than this and isn't
/// straight. The default was right at 60 spans and -0.23 % at 80 on an extrusion (ops#414 note)
constexpr int spanThreshold = 40;
/// The adaptive method's relative error per face: 1e-3 was still -5.8 % to +8.8 % on cornered pipes
constexpr double adaptiveTolerance = 1e-6;

/// Whether a face of the shape carries, as its surface, the basis of its surface, or a 3D curve or
/// pcurve of its edges, a curved B-spline of more than spanThreshold spans
PartExport bool needsAdaptive(const TopoDS_Shape& shape);

/// The shape's volume properties (mass, centre of mass, inertia) into \a props, as
/// BRepGProp::VolumeProperties(shape, props) does, adaptive when needsAdaptive()
PartExport void volumeProperties(const TopoDS_Shape& shape, GProp_GProps& props);

/// The shape's surface properties into \a props, as BRepGProp::SurfaceProperties(shape, props)
/// does, adaptive when needsAdaptive()
PartExport void surfaceProperties(const TopoDS_Shape& shape, GProp_GProps& props);

/// The volume the shape bounds: negative for a shell oriented inwards. The adaptive method
/// computes the mass alone here, about a tenth of the cost of volumeProperties()
PartExport double volume(const TopoDS_Shape& shape);

/// The total area of the shape's faces
PartExport double area(const TopoDS_Shape& shape);

}  // namespace Part::MassProperties
