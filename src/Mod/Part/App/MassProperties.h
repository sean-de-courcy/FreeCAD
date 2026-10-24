// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <GProp_GProps.hxx>

#include <Mod/Part/PartGlobal.h>

class TopoDS_Shape;
class TopoDS_Solid;
class gp_Pnt;

/** Volume and area that stay right on faces with many curved B-spline spans (FreeCAD-CH,
 * ops#414).
 *
 * OCCT's default BRepGProp integration takes a fixed number of Gauss points per face, whatever
 * the face's knot spans, so a face carrying a curved B-spline with more than about 80 to 200 spans
 * is under-sampled: a long pipe's volume was +26 % or -31 %, a Pad's -300 %, a planar face's area
 * -426 %, all on geometry that is right. Here a cheap screen of the faces picks the method: OCCT's
 * default when no face carries such a B-spline, so ordinary shapes get the same numbers bit for
 * bit, and adaptive methods at 1e-6 otherwise:
 * - volumes: Gauss-Kronrod with one integration per knot span, right on the prisms (extrusion
 *   faces included), pipes and revolutions of such B-splines in the tests;
 * - areas: each face on an extrusion (an offset of one included, through trimmed and offset
 *   wrappers) exactly, by a boundary integral along its pcurves with Gauss-Legendre per knot span
 *   of the basis curve; the other faces by OCCT's adaptive surface integration, which is off on
 *   extrusions (1.9 % at 41 spans, 4 to a wave) and right on B-spline surfaces, revolutions and
 *   planes (within 1e-5 in the tests).
 * The screen counts spans only: a strongly curved B-spline of 40 spans or fewer keeps the default,
 * which can be off there too (ops#427).
 *
 * For the code whose decisions depend on a volume, an area or a centre of mass (Refine's and the
 * solid makers' orientation, FilletFallback, TopoShapeRepair, the face makers, PartDesign's
 * up-to faces, Revolution's checks, Scaled; ops#428). A comparison of two shapes integrates both
 * the same way: the overloads taking forceAdaptive, with needsAdaptive() of either shape. The
 * reported Shape.Volume, Shape.Area and centres stay OCCT's default for now (PLAN decision 106).
 * Lengths need no screen: OCCT's linear integration follows the knot spans (1e-14 on a curved
 * B-spline of 1000 spans, ops#428). */
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

/// As volumeProperties(shape, props), adaptive also when \a forceAdaptive
PartExport void
volumeProperties(const TopoDS_Shape& shape, GProp_GProps& props, bool forceAdaptive);

/// The shape's surface properties into \a props, as BRepGProp::SurfaceProperties(shape, props)
/// does, adaptive when needsAdaptive(), with the faces on extrusions integrated exactly
PartExport void surfaceProperties(const TopoDS_Shape& shape, GProp_GProps& props);

/// The volume the shape bounds: negative for a shell oriented inwards. The adaptive method
/// computes the mass alone here, about a tenth of the cost of volumeProperties()
PartExport double volume(const TopoDS_Shape& shape);

/// The total area of the shape's faces
PartExport double area(const TopoDS_Shape& shape);

/// As volume(shape), adaptive also when \a forceAdaptive
PartExport double volume(const TopoDS_Shape& shape, bool forceAdaptive);

/// As area(shape), adaptive also when \a forceAdaptive
PartExport double area(const TopoDS_Shape& shape, bool forceAdaptive);

/// The centre of mass of the shape's solids, else of its faces, else of its edges, else the mean
/// of its vertices, as TopoShape::getCenterOfGravity() chooses; false for an empty or infinite
/// shape
PartExport bool centreOfMass(const TopoDS_Shape& shape, gp_Pnt& centre);

/// Orients a closed solid outwards, as BRepLib::OrientClosedSolid(solid) does, and returns what it
/// returns. When needsAdaptive(), by the sign of the adaptive volume instead: OCCT's classifier
/// turned a prism over a long steep wave inside out (ops#426). The classifier still decides when
/// the adaptive integration fails or gives no sign
PartExport bool orientClosedSolid(TopoDS_Solid& solid);

}  // namespace Part::MassProperties
