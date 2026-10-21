// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2010 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <functional>
#include <limits>
#include <memory>
#include <numbers>
#include <optional>
#include <ranges>
#include <string>
#include <utility>
#include <vector>
#include <Bnd_Box.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_NurbsConvert.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepLib.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepTools.hxx>
#include <BOPTools_AlgoTools3D.hxx>
#include <ElCLib.hxx>
#include <ElSLib.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_Circle.hxx>
#include <Geom_ConicalSurface.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_ElementarySurface.hxx>
#include <Geom_Plane.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <GeomAPI_ExtremaCurveSurface.hxx>
#include <GeomAPI_IntCS.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GeomAdaptor_Surface.hxx>
#include <GeomConvert.hxx>
#include <GeomConvert_BSplineSurfaceToBezierSurface.hxx>
#include <GProp_GProps.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GCPnts_UniformAbscissa.hxx>
#include <gp.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>
#include <gp_Cone.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Trsf.hxx>
#include <IntTools_Context.hxx>
#include <Precision.hxx>
#include <TColGeom_Array2OfBezierSurface.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopTools_DataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopTools_MapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>

#include <App/Document.h>
#include <Base/Console.h>
#include <Base/Converter.h>
#include <Base/Exception.h>
#include <Base/Tools.h>
#include <Base/Translation.h>
#include <Mod/Part/App/FilletFallback.h>
#include <Mod/Part/App/Tools.h>
#include <Mod/Part/App/TopoShapeMapper.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "FeatureRevolved.h"
#include "FirstContactConstruction.h"
#include "FirstContactJumps.h"

using namespace PartDesign;

namespace PartDesign
{

/* TRANSLATOR PartDesign::Revolved */

PROPERTY_SOURCE_ABSTRACT(PartDesign::Revolved, PartDesign::ProfileBased)  // NOLINT

const App::PropertyAngle::Constraints Revolved::floatAngle = {-360.0, 360.0, 1.0};
const char* Revolved::SideTypesEnums[] = {"One side", "Two sides", "Symmetric", nullptr};

namespace
{

// Whether a side revolves up to a face (up to the first, last or a chosen face): the sweep up to
// the face (sweepUpToFace())
bool revolvesUpToFace(Revolved::RevolMethod method, Part::RevolMode revolMode)
{
    return method == Revolved::RevolMethod::ToFirst || method == Revolved::RevolMethod::ToFace
        || (method == Revolved::RevolMethod::ToLast && revolMode == Part::RevolMode::FuseWithBase);
}

bool isLegacyTwoAngles(const std::string& method)
{
    return method == "?TwoAngles" || method == "TwoAngles";
}

bool getProfileOrbit(const TopoShape& profileShape, const gp_Ax1& axis, gp_Pnt& center, gp_Vec& radial)
{
    Base::Vector3d profileCenter;
    if (!profileShape.getCenterOfGravity(profileCenter)) {
        return false;
    }

    const gp_Pnt profilePoint = Base::convertTo<gp_Pnt>(profileCenter);
    const gp_Vec axisVector(axis.Direction());
    const double parameter = gp_Vec(axis.Location(), profilePoint).Dot(axisVector);
    center = axis.Location();
    center.Translate(axisVector * parameter);
    radial = gp_Vec(center, profilePoint);
    return radial.Magnitude() > Precision::Confusion();
}

std::optional<double> getPlanarStartReferenceAngle(
    const TopoShape& profileShape,
    const TopoShape& referenceShape,
    const gp_Ax1& axis
)
{
    TopoShape referenceFace = referenceShape;
    if (referenceFace.shapeType(true) != TopAbs_FACE) {
        referenceFace = referenceFace.getSubTopoShape(TopAbs_FACE, 1);
    }

    BRepAdaptor_Surface surface(TopoDS::Face(referenceFace.getShape()));
    if (surface.GetType() != GeomAbs_Plane) {
        return std::nullopt;
    }

    gp_Pnt orbitCenter;
    gp_Vec radial;
    if (!getProfileOrbit(profileShape, axis, orbitCenter, radial)) {
        return std::nullopt;
    }

    const gp_Pln plane = surface.Plane();
    const gp_Vec normal(plane.Axis().Direction());
    const gp_Vec tangent = gp_Vec(axis.Direction()).Crossed(radial);
    const double cosineCoefficient = radial.Dot(normal);
    const double sineCoefficient = tangent.Dot(normal);
    const double constant = gp_Vec(plane.Location(), orbitCenter).Dot(normal);
    const double amplitude = std::hypot(cosineCoefficient, sineCoefficient);

    if (amplitude <= Precision::Confusion()) {
        if (std::fabs(constant) <= Precision::Confusion()) {
            return 0.0;
        }
        return std::nullopt;
    }

    const double solution = -constant / amplitude;
    if (solution < -1.0 - Precision::Confusion() || solution > 1.0 + Precision::Confusion()) {
        return std::nullopt;
    }

    const double phase = std::atan2(sineCoefficient, cosineCoefficient);
    const double delta = std::acos(std::clamp(solution, -1.0, 1.0));
    return std::min(normalizeAngleRadians(phase + delta), normalizeAngleRadians(phase - delta));
}

// A face without a wire (a datum or origin plane) or with an infinite bounding box: BRepFeat
// trims it (BRepFeat::FaceUntil), and a boolean can't measure it.
bool isUnboundedFace(const TopoShape& face)
{
    if (face.isNull()) {
        return false;
    }
    if (!TopExp_Explorer(face.getShape(), TopAbs_WIRE).More()) {
        return true;
    }
    Base::BoundBox3d faceBox = face.getBoundBox();
    return !faceBox.IsValid() || Precision::IsInfinite(faceBox.CalcDiagonalLength());
}

double faceArea(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(shape, props);
    return props.Mass();
}

// Whether two faces lie on the same plane.
bool onSamePlane(const TopoDS_Face& face, const TopoDS_Face& other)
{
    BRepAdaptor_Surface surface(face);
    BRepAdaptor_Surface otherSurface(other);
    if (surface.GetType() != GeomAbs_Plane || otherSurface.GetType() != GeomAbs_Plane) {
        return false;
    }
    const gp_Pln plane = surface.Plane();
    const gp_Pln otherPlane = otherSurface.Plane();
    return plane.Axis().IsParallel(otherPlane.Axis(), Precision::Angular())
        && otherPlane.Distance(plane.Location()) <= Precision::Confusion();
}

// Whether two bounded faces cover the same points: the area they share is the area of each.
// Holes count, and so do curved faces and faces whose seams differ (a disk and its mirror image).
bool coversSamePoints(const TopoShape& face, const TopoShape& other)
{
    try {
        const double area = faceArea(face.getShape());
        const double otherArea = faceArea(other.getShape());
        BRepAlgoAPI_Common common(face.getShape(), other.getShape());
        if (!common.IsDone() || area <= Precision::Confusion()) {
            return false;
        }
        const double shared = faceArea(common.Shape());
        const double tolerance = area * 1e-6;
        return std::fabs(shared - area) <= tolerance && std::fabs(shared - otherArea) <= tolerance;
    }
    catch (const Standard_Failure&) {
        return false;
    }
}

// Whether a bounded face reaches a plane: it crosses the plane or touches it.
bool reachesPlane(const TopoShape& face, const gp_Pln& plane)
{
    const Base::BoundBox3d box = face.getBoundBox();
    const gp_Pnt center(box.GetCenter().x, box.GetCenter().y, box.GetCenter().z);
    Standard_Real u = 0.0;
    Standard_Real v = 0.0;
    ElSLib::Parameters(plane, center, u, v);
    // The face's points project within its diagonal of its centre's projection.
    const double reach = box.CalcDiagonalLength() + 1.0;
    const TopoDS_Face planeFace
        = BRepBuilderAPI_MakeFace(plane, u - reach, u + reach, v - reach, v + reach).Face();
    BRepExtrema_DistShapeShape distance(face.getShape(), planeFace);
    if (!distance.IsDone()) {
        throw Base::RuntimeError(
            "Symmetric: could not measure the up-to face's distance to the profile plane"
        );
    }
    return distance.Value() <= Precision::Confusion();
}

// The face the profile is checked against: the up-to face itself, or for an unbounded face (a
// datum plane, a whole cylinder) a face on its surface that holds every point the sweep of the
// profile about the axis can reach, since booleans and distances can't take an unbounded face.
// The sweep's points lie within reach of the surface's location, and an elementary surface's
// unbounded parameters are lengths (a cone's along its generatrix: within 2 reach + its radius),
// so a face trimmed to those holds them. An unbounded face on another kind of surface fails (the
// PR 273 review's M2: a whole cylinder went unchecked).
TopoDS_Face reachableUpToFace(
    const TopoShape& upToFace,
    const TopoShape& profile,
    const gp_Ax1& axis
)
{
    const TopoDS_Face& face = TopoDS::Face(upToFace.getShape());
    if (!isUnboundedFace(upToFace)) {
        return face;
    }
    Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    Handle(Geom_Surface) basis = surface;
    Handle(Geom_RectangularTrimmedSurface) trimmed
        = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface);
    if (!trimmed.IsNull()) {
        basis = trimmed->BasisSurface();
    }
    Standard_Real uMin = 0.0;
    Standard_Real uMax = 0.0;
    Standard_Real vMin = 0.0;
    Standard_Real vMax = 0.0;
    surface->Bounds(uMin, uMax, vMin, vMax);
    if (Precision::IsInfinite(uMin) || Precision::IsInfinite(uMax) || Precision::IsInfinite(vMin)
        || Precision::IsInfinite(vMax)) {
        Handle(Geom_ElementarySurface) elementary = Handle(Geom_ElementarySurface)::DownCast(basis);
        if (elementary.IsNull()) {
            throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                "Exception",
                "The up-to face is unbounded, and its kind of surface can't be checked against "
                "the profile. Use a bounded face."
            ));
        }
        double radius = 0.0;
        if (auto cylinder = Handle(Geom_CylindricalSurface)::DownCast(elementary);
            !cylinder.IsNull()) {
            radius = cylinder->Radius();
        }
        else if (auto cone = Handle(Geom_ConicalSurface)::DownCast(elementary); !cone.IsNull()) {
            radius = cone->RefRadius();
        }
        // A point of the profile within d of the axis location sweeps within 2 d of it.
        const Base::BoundBox3d bounds = profile.getBoundBox();
        const gp_Pnt center(bounds.GetCenter().x, bounds.GetCenter().y, bounds.GetCenter().z);
        const double reach = elementary->Location().Distance(axis.Location())
            + 2.0 * (axis.Location().Distance(center) + bounds.CalcDiagonalLength() / 2.0);
        const double limit = 2.0 * reach + radius + 1.0;
        // Only infinite bounds: a cylinder's or cone's periodic range, cut to the limit, lost
        // part of the surface when the limit was under 2 pi (the PR 273 verification's Low).
        auto clamp = [limit](Standard_Real& low, Standard_Real& high) {
            if (Precision::IsInfinite(low)) {
                low = Precision::IsInfinite(high) ? -limit : std::min(-limit, high - 1.0);
            }
            if (Precision::IsInfinite(high)) {
                high = std::max(limit, low + 1.0);
            }
        };
        clamp(uMin, uMax);
        clamp(vMin, vMax);
    }
    BRepBuilderAPI_MakeFace maker(surface, uMin, uMax, vMin, vMax, Precision::Confusion());
    if (!maker.IsDone()) {
        throw Base::RuntimeError(
            QT_TRANSLATE_NOOP("Exception", "Could not check the up-to face against the profile")
        );
    }
    return maker.Face();
}

// A copy of the up-to face with its seams' tolerance cut back to what their curves need, or a null
// face when that changes no seam's tolerance. A seam isn't a boundary: the face goes on across it,
// so its tolerance says nothing about where the face is. Raised with the rest of the face's
// (fixTolerance, a tolerant import), it let the splitter merge the seam with a face of the sweep
// that it runs nearly along: up to a torus turned so that its seam meridian dips 0.1 inside the
// profile's outer cylinder, with the base's tolerance 0.02 the sweep went on into the torus (39.04
// instead of 13.35), and with 0.03 it came out 1.25 short, with no error, whichever way the torus
// was parametrized (ops#293, q4). The face's other edges keep theirs: a face flush with the
// profile within its tolerance relies on it (ops#338).
TopoDS_Face withExactSeams(const TopoDS_Face& face)
{
    BRepBuilderAPI_Copy copy(face);
    const TopoDS_Face result = TopoDS::Face(copy.Shape());
    BRep_Builder builder;
    bool changed = false;
    for (TopExp_Explorer explorer(result, TopAbs_EDGE); explorer.More(); explorer.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(explorer.Current());
        if (BRep_Tool::Degenerated(edge) || !BRep_Tool::IsClosed(edge, result)) {
            continue;
        }
        const double before = BRep_Tool::Tolerance(edge);
        builder.UpdateEdge(edge, Precision::Confusion());
        builder.SameParameter(edge, Standard_False);
        BRepLib::SameParameter(edge, Precision::Confusion());
        changed = changed || BRep_Tool::Tolerance(edge) < before - Precision::Confusion();
    }
    return changed ? result : TopoDS_Face();
}

// The tolerance of the checks of the profile against the up-to face, ten times the largest of
// the shapes' own: section edges along a curved boundary are approximations (the PR 273 review's
// L2).
double profileCheckTolerance(const TopoDS_Shape& profile, const TopoDS_Face& face)
{
    double tolerance = std::max(Precision::Confusion(), BRep_Tool::Tolerance(face));
    for (TopExp_Explorer faces(profile, TopAbs_FACE); faces.More(); faces.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Face(faces.Current())));
    }
    for (TopExp_Explorer edges(profile, TopAbs_EDGE); edges.More(); edges.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Edge(edges.Current())));
    }
    return 10.0 * tolerance;
}

// The tolerance of the check whether the up-to face cuts through the profile: ten times the
// profile's, as profileCheckTolerance(), but only twice the face's. With ten times a face
// tolerance of 1e-3, a profile reaching 0.005 past the face passed as touching it, and the sweep
// then failed saying part of the profile goes all the way round (ops#338).
double cutThroughTolerance(const TopoDS_Shape& profile, const TopoDS_Face& face)
{
    double tolerance = Precision::Confusion();
    for (TopExp_Explorer faces(profile, TopAbs_FACE); faces.More(); faces.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Face(faces.Current())));
    }
    for (TopExp_Explorer edges(profile, TopAbs_EDGE); edges.More(); edges.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Edge(edges.Current())));
    }
    return std::max(10.0 * tolerance, 2.0 * BRep_Tool::Tolerance(face));
}

// Whether the up-to face cuts through the profile: the profile's points on the face are already
// there, those on one side of it meet it at once, and the others only later or never. BRepFeat
// then revolved nothing, with no error, on one side, two sides and Symmetric (ops#289). A face
// that only touches the profile's boundary doesn't cut through it. A section that fails throws:
// the revolution mustn't go on unchecked (the PR 273 review's M1).
// The face is sectioned with the profile's plane, not with the profile: where the face runs along
// a profile edge that leaves it tangentially, the section with the profile came back as one edge
// along the whole boundary, or empty (ops#293 round 1). The section is then classified against the
// profile at points every size / 1024 along it, within the profile's bounding box, the resolution
// of the certificate (tryToRevolveToFace): not exactly. A stretch inside the profile shorter than
// that can slip through. Three points per section edge, or one per piece of the section's common
// with the profile, missed a section that runs along the boundary and inside it where the edge
// bulges out; and that common came back as the profile's own edge, bulge and all, so its points
// were all on the boundary (testRevolutionUpToFaceAlongBulgingProfileEdge, ops#334).
bool cutsThroughProfile(const TopoShape& profile, const TopoDS_Face& face, double tolerance)
{
    auto checkFailed = []() {
        return Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Could not check whether the up-to face cuts through the profile"
        ));
    };
    const Base::BoundBox3d box = profile.getBoundBox();
    const double size = box.CalcDiagonalLength();
    TopoDS_Shape sectionShape;
    try {
        TopoDS_Shape carrier = profile.getShape();
        gp_Pln plane;
        if (profile.findPlane(plane)) {
            // A face on the profile's plane that holds the profile with a margin.
            const gp_Pnt center(box.GetCenter().x, box.GetCenter().y, box.GetCenter().z);
            Standard_Real u = 0.0;
            Standard_Real v = 0.0;
            ElSLib::Parameters(plane, center, u, v);
            const double reach = size + 1.0;
            carrier = BRepBuilderAPI_MakeFace(plane, u - reach, u + reach, v - reach, v + reach)
                          .Face();
        }
        BRepAlgoAPI_Section section(carrier, face);
        if (!section.IsDone()) {
            throw checkFailed();
        }
        sectionShape = section.Shape();
    }
    catch (const Standard_Failure&) {
        throw checkFailed();
    }
    // A point the classifier puts on the boundary counts as inside when it is farther than the
    // tolerance from the profile's edges: on a line that runs along a boundary edge, the
    // classifier's answer can't be relied on.
    Base::BoundBox3d reach = box;
    reach.Enlarge(tolerance);
    TopoDS_Compound boundary;
    BRep_Builder builder;
    builder.MakeCompound(boundary);
    for (TopExp_Explorer edges(profile.getShape(), TopAbs_EDGE); edges.More(); edges.Next()) {
        builder.Add(boundary, edges.Current());
    }
    const double step = std::max(size / 1024.0, 2.0 * tolerance);
    for (TopExp_Explorer edges(sectionShape, TopAbs_EDGE); edges.More(); edges.Next()) {
        // Within twice the section edge's own tolerance, a point may be on the boundary
        const double within
            = std::max(tolerance, 2.0 * BRep_Tool::Tolerance(TopoDS::Edge(edges.Current())));
        BRepAdaptor_Curve curve(TopoDS::Edge(edges.Current()));
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        const double length = GCPnts_AbscissaPoint::Length(curve);
        const int count = std::max(3, static_cast<int>(std::ceil(length / step)) + 1);
        GCPnts_UniformAbscissa points(curve, count, first, last);
        for (int i = 1; i <= count; ++i) {
            const double parameter = points.IsDone()
                ? points.Parameter(i)
                : first + (last - first) * (i - 1) / (count - 1);
            const gp_Pnt point = curve.Value(parameter);
            if (!reach.IsInBox(Base::Vector3d(point.X(), point.Y(), point.Z()))) {
                continue;
            }
            for (TopExp_Explorer faces(profile.getShape(), TopAbs_FACE); faces.More();
                 faces.Next()) {
                const TopoDS_Face& profileFace = TopoDS::Face(faces.Current());
                BRepClass_FaceClassifier classifier(profileFace, point, within);
                if (classifier.State() == TopAbs_IN) {
                    return true;
                }
                if (classifier.State() == TopAbs_ON) {
                    BRepExtrema_DistShapeShape distance(
                        BRepBuilderAPI_MakeVertex(point).Vertex(),
                        boundary
                    );
                    if (!distance.IsDone()) {
                        throw checkFailed();
                    }
                    if (distance.Value() > within) {
                        return true;
                    }
                }
            }
        }
    }
    return false;
}

// Whether the profile's circles about the axis come back to the profile's plane inside the profile
// before a whole turn. They meet the plane again at the mirror image of their start across the
// plane through the axis square to the profile's plane, so this is a common of the profile with
// its mirror image. The sweep then overlaps itself, and a turn up to a face isn't defined there
// (an axis off the profile's plane; ops#293 round 5). With the axis in the profile's plane the
// mirror image lies across the axis, and touches the profile at most along it.
bool returnsToProfile(const TopoShape& profile, const gp_Ax1& axis)
{
    gp_Pln plane;
    if (!profile.findPlane(plane)) {
        throw Base::RuntimeError(
            QT_TRANSLATE_NOOP("Exception", "Could not check the revolution up to the face")
        );
    }
    const gp_Vec across = gp_Vec(axis.Direction()).Crossed(gp_Vec(plane.Axis().Direction()));
    if (across.Magnitude() <= Precision::Angular()) {
        // An axis square to the profile's plane turns it within its plane
        return true;
    }
    gp_Trsf mirror;
    mirror.SetMirror(gp_Ax2(axis.Location(), gp_Dir(across)));
    try {
        const TopoDS_Shape image = BRepBuilderAPI_Transform(profile.getShape(), mirror, true).Shape();
        BRepAlgoAPI_Common common(profile.getShape(), image);
        if (!common.IsDone()) {
            throw Base::RuntimeError(
                QT_TRANSLATE_NOOP("Exception", "Could not check the revolution up to the face")
            );
        }
        return faceArea(common.Shape()) > 1e-9 * faceArea(profile.getShape());
    }
    catch (const Standard_Failure&) {
        throw Base::RuntimeError(
            QT_TRANSLATE_NOOP("Exception", "Could not check the revolution up to the face")
        );
    }
}

// Points of a profile or a face: its vertices, points along its edges (one per sixteenth of its
// bounding box's diagonal, from one up to seven per edge: a profile of many short edges cost 7
// distance checks per edge), and points inside its faces (a grid over each face's bounds, and the
// face classifier's own point).
std::vector<gp_Pnt> profileSamples(const TopoDS_Shape& profile)
{
    std::vector<gp_Pnt> points;
    Bnd_Box box;
    BRepBndLib::Add(profile, box);
    const double spacing = box.IsVoid() ? 0.0 : std::sqrt(box.SquareExtent()) / 16.0;
    for (TopExp_Explorer vertices(profile, TopAbs_VERTEX); vertices.More(); vertices.Next()) {
        points.push_back(BRep_Tool::Pnt(TopoDS::Vertex(vertices.Current())));
    }
    for (TopExp_Explorer edges(profile, TopAbs_EDGE); edges.More(); edges.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(edges.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        BRepAdaptor_Curve curve(edge);
        int samples = 7;
        if (spacing > Precision::Confusion()) {
            const double length = GCPnts_AbscissaPoint::Length(curve);
            samples = std::clamp(static_cast<int>(std::ceil(length / spacing)), 1, 7);
        }
        for (int i = 1; i <= samples; ++i) {
            points.push_back(curve.Value(
                curve.FirstParameter()
                + (curve.LastParameter() - curve.FirstParameter()) * i / (samples + 1)
            ));
        }
    }
    for (TopExp_Explorer faces(profile, TopAbs_FACE); faces.More(); faces.Next()) {
        const TopoDS_Face& face = TopoDS::Face(faces.Current());
        Standard_Real uMin = 0.0;
        Standard_Real uMax = 0.0;
        Standard_Real vMin = 0.0;
        Standard_Real vMax = 0.0;
        BRepTools::UVBounds(face, uMin, uMax, vMin, vMax);
        BRepAdaptor_Surface surface(face);
        constexpr int steps = 6;
        for (int i = 1; i < steps; ++i) {
            for (int j = 1; j < steps; ++j) {
                const gp_Pnt2d uv(
                    uMin + (uMax - uMin) * i / steps,
                    vMin + (vMax - vMin) * j / steps
                );
                BRepClass_FaceClassifier classifier(face, uv, Precision::Confusion());
                if (classifier.State() == TopAbs_IN) {
                    points.push_back(surface.Value(uv.X(), uv.Y()));
                }
            }
        }
        try {
            gp_Pnt point;
            gp_Pnt2d uv;
            if (BOPTools_AlgoTools3D::PointInFace(face, point, uv, new IntTools_Context) == 0) {
                points.push_back(point);
            }
        }
        catch (const Standard_Failure&) {
            // The grid's points stand.
        }
    }
    return points;
}

// Parameters on a face's surface moved into the face's own range where the surface is periodic:
// intersections give them in the surface's base period, and a face on [5.87, 6.48] of a cylinder
// then classified OUT where it held them (the PR 273 round 5 verification's B). Centred on the
// face's range, so a point on its boundary stays on it.
gp_Pnt2d intoFaceRange(const TopoDS_Face& face, const Handle(Geom_Surface)& surface, const gp_Pnt2d& uv)
{
    Standard_Real uMin = 0.0;
    Standard_Real uMax = 0.0;
    Standard_Real vMin = 0.0;
    Standard_Real vMax = 0.0;
    BRepTools::UVBounds(face, uMin, uMax, vMin, vMax);
    gp_Pnt2d moved = uv;
    if (surface->IsUPeriodic()) {
        const double half = 0.5 * surface->UPeriod();
        moved.SetX(ElCLib::InPeriod(uv.X(), 0.5 * (uMin + uMax) - half, 0.5 * (uMin + uMax) + half));
    }
    if (surface->IsVPeriodic()) {
        const double half = 0.5 * surface->VPeriod();
        moved.SetY(ElCLib::InPeriod(uv.Y(), 0.5 * (vMin + vMax) - half, 0.5 * (vMin + vMax) + half));
    }
    return moved;
}

// A face's surface trimmed to the face's parameter bounds, widened by a hundredth of them and
// kept within the surface's own bounds; a periodic direction the face nearly fills stays whole.
// GeomAPI_IntCS against a whole extruded surface, unbounded along the extrusion, found none or
// one of the five points where a circle crosses an open wavy wall, and all five against the
// trimmed one: a check that misses the first contact expects the tool to go on to a later one
// (the PR 279 round 2 verification's 4: a correct Revolution refused).
Handle(Geom_Surface) trimmedToFace(const TopoDS_Face& face, const Handle(Geom_Surface)& surface)
{
    Standard_Real uMin = 0.0;
    Standard_Real uMax = 0.0;
    Standard_Real vMin = 0.0;
    Standard_Real vMax = 0.0;
    BRepTools::UVBounds(face, uMin, uMax, vMin, vMax);
    Standard_Real uLow = 0.0;
    Standard_Real uHigh = 0.0;
    Standard_Real vLow = 0.0;
    Standard_Real vHigh = 0.0;
    surface->Bounds(uLow, uHigh, vLow, vHigh);
    // Whether to trim one direction, and to what
    auto widen = [](Standard_Real& low, Standard_Real& high, double boundLow, double boundHigh,
                    bool periodic, double period) {
        const double margin = 0.01 * (high - low);
        if (periodic) {
            if (high - low + 2.0 * margin >= period) {
                return false;
            }
            low -= margin;
            high += margin;
            return true;
        }
        low = std::max(low - margin, boundLow);
        high = std::min(high + margin, boundHigh);
        return high - low > Precision::PConfusion();
    };
    const bool trimU = widen(
        uMin,
        uMax,
        uLow,
        uHigh,
        surface->IsUPeriodic(),
        surface->IsUPeriodic() ? surface->UPeriod() : 0.0
    );
    const bool trimV = widen(
        vMin,
        vMax,
        vLow,
        vHigh,
        surface->IsVPeriodic(),
        surface->IsVPeriodic() ? surface->VPeriod() : 0.0
    );
    try {
        if (trimU && trimV) {
            return new Geom_RectangularTrimmedSurface(surface, uMin, uMax, vMin, vMax);
        }
        if (trimU) {
            return new Geom_RectangularTrimmedSurface(surface, uMin, uMax, Standard_True);
        }
        if (trimV) {
            return new Geom_RectangularTrimmedSurface(surface, vMin, vMax, Standard_False);
        }
    }
    catch (const Standard_Failure&) {
        // The whole surface
    }
    return surface;
}

// Where a circle surely meets a face: its parameters (angles from its X direction) at the points
// where it crosses or touches the face's surface on the face (the face classifier says in or on,
// within the tolerance). Quick, unlike the exact distance to a face of many edges (16 ms a circle
// against 84 edges); none found means only "not shown", for the exact distance to settle. With
// `firstOnly`, the first one found: whether the circle meets the face at all.
std::vector<double> circleContactsQuickly(
    const gp_Circ& circle,
    const TopoDS_Face& face,
    double tolerance,
    bool firstOnly = false
)
{
    std::vector<double> contacts;
    try {
        const Handle(Geom_Circle) curve = new Geom_Circle(circle);
        const Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
        std::vector<std::pair<double, gp_Pnt2d>> candidates;
        GeomAPI_IntCS crossing(curve, trimmedToFace(face, surface));
        if (crossing.IsDone()) {
            for (int i = 1; i <= crossing.NbPoints(); ++i) {
                Standard_Real u = 0.0;
                Standard_Real v = 0.0;
                Standard_Real w = 0.0;
                crossing.Parameters(i, u, v, w);
                candidates.emplace_back(w, gp_Pnt2d(u, v));
            }
        }
        GeomAPI_ExtremaCurveSurface touching(curve, surface);
        if (!touching.Extrema().IsParallel()) {
            for (int i = 1; i <= touching.NbExtrema(); ++i) {
                if (touching.Distance(i) > tolerance) {
                    continue;
                }
                Standard_Real w = 0.0;
                Standard_Real u = 0.0;
                Standard_Real v = 0.0;
                touching.Parameters(i, w, u, v);
                candidates.emplace_back(w, gp_Pnt2d(u, v));
            }
        }
        for (const auto& [angle, uv] : candidates) {
            BRepClass_FaceClassifier classifier(face, intoFaceRange(face, surface, uv), tolerance);
            if (classifier.State() == TopAbs_IN || classifier.State() == TopAbs_ON) {
                contacts.push_back(ElCLib::InPeriod(angle, 0.0, 2.0 * std::numbers::pi));
                if (firstOnly) {
                    break;
                }
            }
        }
    }
    catch (const Standard_Failure&) {
        // Not shown: the exact distance decides.
    }
    return contacts;
}

// The parameter rectangle on a face's surface that holds the face and every point of the sweep
// (whose bounding box is `sweep`) on that surface (the PR 273 verification's item 1: a profile
// edge poking past the face's outer edge between the samples slipped when the rectangle was only
// the face's bounds). A plane: the face's bounds and the sweep's box projected. A cylinder or
// cone: a whole turn, and along the axis the sweep's box (a cone stops at its apex, on the face's
// side). A sphere or torus: the whole surface. Another surface: one period where it is periodic,
// its bounds where they are finite, and where they aren't (a length along an extrusion or an
// offset) the face's bounds widened by the size of the face and the sweep together.
void sweepRectangle(
    const TopoDS_Face& face,
    const Bnd_Box& sweep,
    Standard_Real& uMin,
    Standard_Real& uMax,
    Standard_Real& vMin,
    Standard_Real& vMax
)
{
    constexpr double turn = 2.0 * std::numbers::pi;
    BRepTools::UVBounds(face, uMin, uMax, vMin, vMax);
    const Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    const GeomAdaptor_Surface adaptor(surface);
    std::vector<gp_Pnt> corners;
    if (!sweep.IsVoid()) {
        Standard_Real x[2];
        Standard_Real y[2];
        Standard_Real z[2];
        sweep.Get(x[0], y[0], z[0], x[1], y[1], z[1]);
        for (int i = 0; i < 8; ++i) {
            corners.emplace_back(x[i & 1], y[(i >> 1) & 1], z[(i >> 2) & 1]);
        }
    }
    auto widen = [](Standard_Real value, Standard_Real& low, Standard_Real& high) {
        low = std::min(low, value);
        high = std::max(high, value);
    };
    switch (adaptor.GetType()) {
        case GeomAbs_Plane:
            for (const gp_Pnt& corner : corners) {
                Standard_Real u = 0.0;
                Standard_Real v = 0.0;
                ElSLib::Parameters(adaptor.Plane(), corner, u, v);
                widen(u, uMin, uMax);
                widen(v, vMin, vMax);
            }
            return;
        case GeomAbs_Cylinder:
            uMax = uMin + turn;
            for (const gp_Pnt& corner : corners) {
                Standard_Real u = 0.0;
                Standard_Real v = 0.0;
                ElSLib::Parameters(adaptor.Cylinder(), corner, u, v);
                widen(v, vMin, vMax);
            }
            return;
        case GeomAbs_Cone: {
            uMax = uMin + turn;
            const gp_Cone cone = adaptor.Cone();
            const double faceVMin = vMin;
            const double faceVMax = vMax;
            // A point at height h along the axis has v = h / cos(semi-angle)
            for (const gp_Pnt& corner : corners) {
                const double height = gp_Vec(cone.Location(), corner)
                                          .Dot(gp_Vec(cone.Axis().Direction()));
                widen(height / std::cos(cone.SemiAngle()), vMin, vMax);
            }
            if (std::abs(std::sin(cone.SemiAngle())) > Precision::Angular()) {
                const double apex = -cone.RefRadius() / std::sin(cone.SemiAngle());
                if (faceVMin >= apex - Precision::Confusion()) {
                    vMin = std::max(vMin, apex);
                }
                else if (faceVMax <= apex + Precision::Confusion()) {
                    vMax = std::min(vMax, apex);
                }
            }
            return;
        }
        case GeomAbs_Sphere:
            uMax = uMin + turn;
            vMin = -std::numbers::pi / 2.0;
            vMax = std::numbers::pi / 2.0;
            return;
        case GeomAbs_Torus:
            uMax = uMin + turn;
            vMax = vMin + turn;
            return;
        default:
            break;
    }
    Standard_Real boundUMin = 0.0;
    Standard_Real boundUMax = 0.0;
    Standard_Real boundVMin = 0.0;
    Standard_Real boundVMax = 0.0;
    surface->Bounds(boundUMin, boundUMax, boundVMin, boundVMax);
    Bnd_Box both = sweep;
    BRepBndLib::Add(face, both);
    const double reach = both.IsVoid() ? 0.0 : std::sqrt(both.SquareExtent());
    auto cover = [reach](
                     bool periodic,
                     double period,
                     Standard_Real boundLow,
                     Standard_Real boundHigh,
                     Standard_Real& low,
                     Standard_Real& high
                 ) {
        if (periodic) {
            high = low + period;
            return;
        }
        low = Precision::IsInfinite(boundLow) ? low - reach : boundLow;
        high = Precision::IsInfinite(boundHigh) ? high + reach : boundHigh;
    };
    cover(
        surface->IsUPeriodic(),
        surface->IsUPeriodic() ? surface->UPeriod() : 0.0,
        boundUMin,
        boundUMax,
        uMin,
        uMax
    );
    cover(
        surface->IsVPeriodic(),
        surface->IsVPeriodic() ? surface->VPeriod() : 0.0,
        boundVMin,
        boundVMax,
        vMin,
        vMax
    );
}

// The gaps in the face's reach on its own surface: what sweepRectangle() holds beyond the face.
// Within the face's own parameter bounds, the rectangle less the face: its holes (inner wires),
// and notches or slots cut into its outer boundary. Beyond them, the strips up to the sweep's
// rectangle, which hold none of the face and need no boolean: a Cut of a whole turn of a
// cylinder came back empty. A null shape within when the face fills its bounds, which the areas
// tell at once, and no strips where the sweep stays within them. The rectangle is built on the surface as BRep_Tool gives it, already moved for a located face; a
// hole's own face built on that copy from the face's inner wire, whose curves are on the
// original surface, made the classifier refuse a valid case (the PR 273 verification's Low). The
// Cut fails closed: its area must be the rectangle's less the face's (the PR 273 verification's
// item 3).
struct FaceGaps
{
    TopoDS_Shape within;
    std::vector<TopoDS_Face> beyond;
};

FaceGaps faceGaps(const TopoDS_Face& face, const Bnd_Box& sweep)
{
    auto checkFailed = []() {
        return Base::RuntimeError(
            QT_TRANSLATE_NOOP("Exception", "Could not check whether the profile meets the up-to face")
        );
    };
    Standard_Real uMin = 0.0;
    Standard_Real uMax = 0.0;
    Standard_Real vMin = 0.0;
    Standard_Real vMax = 0.0;
    BRepTools::UVBounds(face, uMin, uMax, vMin, vMax);
    Standard_Real wideUMin = 0.0;
    Standard_Real wideUMax = 0.0;
    Standard_Real wideVMin = 0.0;
    Standard_Real wideVMax = 0.0;
    sweepRectangle(face, sweep, wideUMin, wideUMax, wideVMin, wideVMax);
    const Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    // An elementary surface's trim would refuse the strips beyond it
    Handle(Geom_Surface) wideSurface = surface;
    if (auto trimmed = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface);
        !trimmed.IsNull()
        && trimmed->BasisSurface()->IsKind(STANDARD_TYPE(Geom_ElementarySurface))) {
        wideSurface = trimmed->BasisSurface();
    }
    auto rectangle = [&](const Handle(Geom_Surface)& on,
                         Standard_Real u0,
                         Standard_Real u1,
                         Standard_Real v0,
                         Standard_Real v1) {
        BRepBuilderAPI_MakeFace maker(on, u0, u1, v0, v1, Precision::Confusion());
        if (!maker.IsDone()) {
            throw checkFailed();
        }
        return maker.Face();
    };
    FaceGaps gaps;
    const TopoDS_Face own = rectangle(surface, uMin, uMax, vMin, vMax);
    const double ownArea = faceArea(own);
    const double inside = ownArea - faceArea(face);
    if (inside > 1e-9 * ownArea) {
        BRepAlgoAPI_Cut cut(own, face);
        if (!cut.IsDone() || cut.Shape().IsNull()
            || std::abs(faceArea(cut.Shape()) - inside) > 1e-6 * ownArea) {
            throw checkFailed();
        }
        gaps.within = cut.Shape();
    }
    const std::array<std::array<Standard_Real, 4>, 4> strips {{
        {wideUMin, uMin, wideVMin, wideVMax},
        {uMax, wideUMax, wideVMin, wideVMax},
        {uMin, uMax, wideVMin, vMin},
        {uMin, uMax, vMax, wideVMax},
    }};
    for (const auto& [u0, u1, v0, v1] : strips) {
        if (u1 - u0 <= Precision::PConfusion() || v1 - v0 <= Precision::PConfusion()) {
            continue;
        }
        const TopoDS_Face strip = rectangle(wideSurface, u0, u1, v0, v1);
        if (faceArea(strip) <= 1e-9 * ownArea) {
            continue;
        }
        gaps.beyond.push_back(strip);
    }
    return gaps;
}

// How the profile meets the up-to face as it turns about the axis (profileReach())
enum class ProfileReach
{
    MeetsFace,
    // Part of the profile never meets the face
    MissesFace,
    // Part of the profile turns through a gap in the face before it first meets the face
    CrossesGapFirst,
    // Part of a profile face turns past the face's outer edge before it meets the face, while
    // another part of it stops at the face
    PassesEdgeFirst,
};

// How the profile meets the up-to face as it turns about the axis, in the revolution's direction
// (positive about the axis, as BRepFeat turns). A point of the profile whose circle stays farther
// than the tolerance from the face has nowhere to stop, and BRepFeat revolved it all the way
// round or not at all, with no error: a face touching the profile's boundary where the profile's
// nearer points never reach it, or a face trimmed away from the profile plane (the PR 273
// review's M3). A point that turns through a gap within the face's bounds (faceGaps(): holes,
// notches, slots) before it first meets the face went on past where it should have stopped:
// BRepFeat keeps a hole, and gave 29.07 instead of 12.58 for a wall through the axis with a hole
// where the profile's points meet the wall's far half later (the PR 273 verification's item 2,
// ops#299). The points are samples of the profile, and samples of the gaps where the profile's
// points turn through them (the gaps within the profile revolved a whole turn): a gap narrower
// than the profile samples' spacing, or only partly in the profile's way, slipped between them
// (the PR 273 verifications), and so did a profile edge poking past the face's outer edge (item
// 1: the strips beyond the face's bounds). Each gap point checked is on a profile point's
// circle, and is refused only when its whole circle, or within the face's bounds the arc from
// the profile to it, stays clear of the face, so a refusal is never wrong. Both booleans fail
// closed (item 3).
ProfileReach profileReach(
    const TopoShape& profile,
    const TopoDS_Face& face,
    const gp_Ax1& axis,
    double tolerance
)
{
    constexpr double turn = 2.0 * std::numbers::pi;
    const gp_Lin line(axis);
    auto checkFailed = []() {
        return Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Could not check whether the profile meets the up-to face"
        ));
    };
    // Whether the circle through a point, about the axis, stays farther than the tolerance from
    // the face.
    auto circleMisses = [&](const gp_Pnt& point) {
        const double radius = line.Distance(point);
        const gp_Pnt center = ElCLib::Value(ElCLib::Parameter(line, point), line);
        TopoDS_Shape circle;
        if (radius <= Precision::Confusion()) {
            circle = BRepBuilderAPI_MakeVertex(point).Shape();
        }
        else {
            const gp_Circ curve(gp_Ax2(center, axis.Direction()), radius);
            if (!circleContactsQuickly(curve, face, tolerance, true).empty()) {
                return false;
            }
            circle = BRepBuilderAPI_MakeEdge(curve).Shape();
        }
        BRepExtrema_DistShapeShape distance(circle, face);
        if (!distance.IsDone()) {
            throw checkFailed();
        }
        return distance.Value() > tolerance;
    };
    gp_Pln plane;
    // Without the profile's plane, the start of a gap point's circle isn't found, and first
    // contact would go unchecked (the PR 273 verification's item 7).
    if (!profile.findPlane(plane)) {
        throw checkFailed();
    }
    // The profile's reach, from its bounding box's corners: a radius from the axis up to the
    // largest corner's, a position along the axis between theirs. A point beyond either isn't
    // swept, and needs no classifying against the profile (a profile of 100 edges made a wall
    // of 20 holes out of reach take three times as long).
    double reachRadius = 0.0;
    double reachLow = std::numeric_limits<double>::max();
    double reachHigh = std::numeric_limits<double>::lowest();
    {
        Bnd_Box box;
        BRepBndLib::AddOptimal(profile.getShape(), box, Standard_False, Standard_False);
        if (!box.IsVoid()) {
            Standard_Real x[2];
            Standard_Real y[2];
            Standard_Real z[2];
            box.Get(x[0], y[0], z[0], x[1], y[1], z[1]);
            for (int i = 0; i < 8; ++i) {
                const gp_Pnt corner(x[i & 1], y[(i >> 1) & 1], z[(i >> 2) & 1]);
                reachRadius = std::max(reachRadius, line.Distance(corner));
                const double along = ElCLib::Parameter(line, corner);
                reachLow = std::min(reachLow, along);
                reachHigh = std::max(reachHigh, along);
            }
        }
    }
    // The circle through a point, about the axis, that starts on the profile: its X direction
    // points at where it meets the profile, so a point's parameter on it is the angle the profile
    // turns through to reach the point. Whether that start is inside the profile, not on its
    // boundary. Nothing for a point the profile doesn't sweep through, or on the axis.
    struct Swept
    {
        gp_Circ circle;
        bool inside;
        TopoDS_Face profileFace;
    };
    auto sweptCircle = [&](const gp_Pnt& point) -> std::optional<Swept> {
        const double radius = line.Distance(point);
        const double along = ElCLib::Parameter(line, point);
        if (radius <= Precision::Confusion() || radius > reachRadius + tolerance
            || along < reachLow - tolerance || along > reachHigh + tolerance) {
            return std::nullopt;
        }
        const gp_Ax2 frame(ElCLib::Value(along, line), axis.Direction());
        // The circle meets the profile plane where a cos(t) + b sin(t) = -d / radius
        const gp_Vec normal(plane.Axis().Direction());
        const double a = gp_Vec(frame.XDirection()).Dot(normal);
        const double b = gp_Vec(frame.YDirection()).Dot(normal);
        const double d = gp_Vec(plane.Location(), frame.Location()).Dot(normal);
        const double amplitude = std::hypot(a, b);
        if (amplitude * radius <= Precision::Confusion()) {
            return std::nullopt;
        }
        const double ratio = -d / (amplitude * radius);
        if (std::abs(ratio) > 1.0 + tolerance / radius) {
            return std::nullopt;
        }
        const double phase = std::atan2(b, a);
        const double offset = std::acos(std::clamp(ratio, -1.0, 1.0));
        for (double angle : {phase + offset, phase - offset}) {
            const gp_Dir start(
                gp_Vec(frame.XDirection()) * std::cos(angle)
                + gp_Vec(frame.YDirection()) * std::sin(angle)
            );
            const gp_Pnt onPlane = frame.Location().Translated(gp_Vec(start) * radius);
            for (TopExp_Explorer faces(profile.getShape(), TopAbs_FACE); faces.More();
                 faces.Next()) {
                BRepClass_FaceClassifier classifier(
                    TopoDS::Face(faces.Current()),
                    onPlane,
                    tolerance
                );
                if (classifier.State() == TopAbs_IN || classifier.State() == TopAbs_ON) {
                    return Swept {
                        gp_Circ(gp_Ax2(frame.Location(), axis.Direction(), start), radius),
                        classifier.State() == TopAbs_IN,
                        TopoDS::Face(faces.Current())
                    };
                }
            }
        }
        return std::nullopt;
    };
    // How the profile point on a gap point's circle reaches the gap point: the face first, or the
    // gap. A gap point on the profile itself only checks that its circle meets the face.
    auto gapReach = [&](const gp_Pnt& point, const gp_Circ& circle) {
        const double angle = ElCLib::Parameter(circle, point);
        const double slack = 0.5 * tolerance / circle.Radius();
        if (angle <= slack) {
            return circleMisses(point) ? ProfileReach::MissesFace : ProfileReach::MeetsFace;
        }
        const std::vector<double> contacts = circleContactsQuickly(circle, face, tolerance);
        if (std::ranges::any_of(contacts, [&](double contact) {
                return contact <= angle + slack || contact >= turn - slack;
            })) {
            return ProfileReach::MeetsFace;
        }
        // Not shown: the exact distance from the arc up to the point
        BRepBuilderAPI_MakeEdge arc(circle, 0.0, angle - slack);
        if (!arc.IsDone()) {
            throw checkFailed();
        }
        BRepExtrema_DistShapeShape distance(arc.Edge(), face);
        if (!distance.IsDone()) {
            throw checkFailed();
        }
        if (distance.Value() <= tolerance) {
            return ProfileReach::MeetsFace;
        }
        if (!contacts.empty() || !circleMisses(point)) {
            return ProfileReach::CrossesGapFirst;
        }
        return ProfileReach::MissesFace;
    };
    // Whether every sample of a profile face first crosses the face's surface outside the face:
    // the whole profile face turns past the face's edge, and meets the face later, which BRepFeat
    // handles (testRevolutionTwoFacesAcrossTheAxis). When some of its samples stop at the face
    // first and others pass its edge, BRepFeat took them all past it: 12 pi instead of 9 pi,
    // silently (the PR 273 verification's item 6).
    std::vector<std::pair<TopoDS_Face, bool>> besideFaces;
    auto passesBeside = [&](const TopoDS_Face& profileFace) {
        for (const auto& [known, beside] : besideFaces) {
            if (known.IsSame(profileFace)) {
                return beside;
            }
        }
        // A trimmed surface ends where the face does: its basis holds the crossings beside it
        // (trimmedTubeWall()).
        Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
        if (const Handle(Geom_RectangularTrimmedSurface) trimmed
            = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface);
            !trimmed.IsNull()) {
            surface = trimmed->BasisSurface();
        }
        bool beside = true;
        for (const gp_Pnt& point : profileSamples(profileFace)) {
            const double radius = line.Distance(point);
            if (radius <= tolerance) {
                continue;
            }
            const gp_Pnt center = ElCLib::Value(ElCLib::Parameter(line, point), line);
            const Handle(Geom_Circle) circle = new Geom_Circle(
                gp_Ax2(center, axis.Direction(), gp_Dir(gp_Vec(center, point))),
                radius
            );
            const double slack = 0.5 * tolerance / radius;
            GeomAPI_IntCS crossing(circle, surface);
            if (!crossing.IsDone()) {
                throw checkFailed();
            }
            double first = turn;
            gp_Pnt2d firstUV;
            for (int i = 1; i <= crossing.NbPoints(); ++i) {
                Standard_Real u = 0.0;
                Standard_Real v = 0.0;
                Standard_Real w = 0.0;
                crossing.Parameters(i, u, v, w);
                w = ElCLib::InPeriod(w, 0.0, turn);
                if (w > slack && w < turn - slack && w < first) {
                    first = w;
                    firstUV.SetCoord(u, v);
                }
            }
            if (first == turn) {
                beside = false;
                break;
            }
            // A point crossing at the face's edge (on its boundary) doesn't stop inside it
            BRepClass_FaceClassifier classifier(
                face,
                intoFaceRange(face, surface, firstUV),
                tolerance
            );
            if (classifier.State() == TopAbs_IN) {
                beside = false;
                break;
            }
        }
        besideFaces.emplace_back(profileFace, beside);
        return beside;
    };
    try {
        for (const gp_Pnt& point : profileSamples(profile.getShape())) {
            if (circleMisses(point)) {
                return ProfileReach::MissesFace;
            }
        }
        BRepPrimAPI_MakeRevol sweep(profile.getShape(), axis, turn);
        if (!sweep.IsDone()) {
            throw checkFailed();
        }
        Bnd_Box sweepBox;
        BRepBndLib::AddOptimal(sweep.Shape(), sweepBox, Standard_False, Standard_False);
        const FaceGaps gaps = faceGaps(face, sweepBox);
        // Within the face's bounds, a gap point is refused when the profile reaches it before
        // the face. Beyond them, when its circle never meets the face, or when the profile
        // reaches it first and part of the same profile face stops at the face: a whole profile
        // face that turns past the face's outer edge and meets the face later is what BRepFeat
        // handles (testRevolutionTwoFacesAcrossTheAxis: the far face's profile passes the wall's
        // plane beside the wall, and meets the wall three quarters of a turn on).
        // Each strip on its own: strips touching along their edges in one argument made the
        // Common warn (an acquired self-intersection).
        std::vector<std::pair<TopoDS_Shape, bool>> regions;
        if (!gaps.within.IsNull()) {
            regions.emplace_back(gaps.within, true);
        }
        for (const TopoDS_Face& strip : gaps.beyond) {
            regions.emplace_back(strip, false);
        }
        for (const auto& [region, firstContact] : regions) {
            auto reach = [&](const gp_Pnt& point, const std::optional<Swept>& swept) {
                if (!swept) {
                    return circleMisses(point) ? ProfileReach::MissesFace
                                               : ProfileReach::MeetsFace;
                }
                const ProfileReach found = gapReach(point, swept->circle);
                if (firstContact || found != ProfileReach::CrossesGapFirst) {
                    return found;
                }
                return passesBeside(swept->profileFace) ? ProfileReach::MeetsFace
                                                        : ProfileReach::PassesEdgeFirst;
            };
            // The region's own samples that the profile turns through, and whether one is inside
            // the sweep: the Common below must then give a face.
            bool reachesRegion = false;
            for (const gp_Pnt& point : profileSamples(region)) {
                if (const std::optional<Swept> swept = sweptCircle(point)) {
                    reachesRegion = reachesRegion || swept->inside;
                    if (const ProfileReach found = reach(point, swept);
                        found != ProfileReach::MeetsFace) {
                        return found;
                    }
                }
            }
            BRepAlgoAPI_Common reached(region, sweep.Shape());
            if (!reached.IsDone() || reached.HasWarnings()) {
                throw checkFailed();
            }
            bool pieces = false;
            for (TopExp_Explorer piece(reached.Shape(), TopAbs_FACE); piece.More();
                 piece.Next()) {
                pieces = true;
                // A point of the Common is swept; one whose start isn't found (on the sweep's
                // boundary, within the tolerance) only checks that its circle meets the face.
                for (const gp_Pnt& point : profileSamples(piece.Current())) {
                    if (const ProfileReach found = reach(point, sweptCircle(point));
                        found != ProfileReach::MeetsFace) {
                        return found;
                    }
                }
            }
            if (reachesRegion && !pieces) {
                throw checkFailed();
            }
        }
    }
    catch (const Standard_Failure&) {
        throw checkFailed();
    }
    return ProfileReach::MeetsFace;
}

// The whole surface a face lies on: an unbounded plane, or a cylinder or cone unbounded along
// its axis, taken from the surface itself, not a trimmed surface's trim. Other surfaces fail.
// B-spline, Bezier, offset surfaces and extrusions or revolutions of a curve often end where the
// face ends (a loft, a sweep, a Pad of a spline), so their image lost the second side as before
// (the PR 268 review's High). A whole sphere as the second side's face gave less than the mirror
// of the first side, silently (probed).
TopoShape wholeSurface(const TopoDS_Face& face)
{
    Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    for (auto trimmed = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface);
         !trimmed.IsNull();
         trimmed = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface)) {
        surface = trimmed->BasisSurface();
    }
    if (auto plane = Handle(Geom_Plane)::DownCast(surface); !plane.IsNull()) {
        return TopoShape(BRepBuilderAPI_MakeFace(plane->Pln()).Face());
    }
    if (Handle(Geom_CylindricalSurface)::DownCast(surface).IsNull()
        && Handle(Geom_ConicalSurface)::DownCast(surface).IsNull()) {
        throw Base::RuntimeError(
            "Symmetric: the up-to face crosses the profile plane, and its surface can't stop the "
            "second side at the face's mirror image. Use Two sides."
        );
    }
    BRepBuilderAPI_MakeFace maker(surface, Precision::Confusion());
    if (!maker.IsDone()) {
        throw Base::RuntimeError("Symmetric: could not extend the up-to face to its whole surface");
    }
    return TopoShape(maker.Face());
}

// Whether two solids are the same: neither has volume outside the other, within 1e-6 of the
// larger volume.
bool sameSolid(const TopoShape& shape, const TopoShape& other)
{
    if (shape.isNull() || shape.getShape().IsNull() || other.isNull()
        || other.getShape().IsNull()) {
        return false;
    }
    try {
        GProp_GProps props;
        BRepGProp::VolumeProperties(shape.getShape(), props);
        GProp_GProps otherProps;
        BRepGProp::VolumeProperties(other.getShape(), otherProps);
        const double tolerance = std::max(
            std::max(std::fabs(props.Mass()), std::fabs(otherProps.Mass())) * 1e-6,
            Precision::Confusion()
        );
        for (const auto& [from, cut] : {std::pair {&shape, &other}, std::pair {&other, &shape}}) {
            BRepAlgoAPI_Cut difference(from->getShape(), cut->getShape());
            if (!difference.IsDone()) {
                return false;
            }
            GProp_GProps rest;
            BRepGProp::VolumeProperties(difference.Shape(), rest);
            if (std::fabs(rest.Mass()) > tolerance) {
                return false;
            }
        }
        return true;
    }
    catch (const Standard_Failure&) {
        return false;
    }
}

// Whether a face lies on a surface: its vertices, points along its edges, and points inside it
// (a grid over its bounds and a point the face classifier finds). A face whose inside yields no
// point (a thin ring or crescent can miss every grid point, the PR 268 round 2 verification's
// finding 1) is judged by its boundary alone, never skipped: its callers then check that it lies
// within the up-to face, by area, which a face off the surface fails.
bool liesOnSurface(const TopoDS_Face& face, const Handle(Geom_Surface)& surface)
{
    const double faceTolerance = BRep_Tool::Tolerance(face);
    auto onSurface = [&](const gp_Pnt& point, double shapeTolerance) {
        const double tolerance = std::max(
            10.0 * Precision::Confusion(),
            2.0 * std::max(faceTolerance, shapeTolerance)
        );
        GeomAPI_ProjectPointOnSurf projection(point, surface);
        return projection.NbPoints() > 0 && projection.LowerDistance() <= tolerance;
    };
    for (TopExp_Explorer vertices(face, TopAbs_VERTEX); vertices.More(); vertices.Next()) {
        const TopoDS_Vertex& vertex = TopoDS::Vertex(vertices.Current());
        if (!onSurface(BRep_Tool::Pnt(vertex), BRep_Tool::Tolerance(vertex))) {
            return false;
        }
    }
    for (TopExp_Explorer edges(face, TopAbs_EDGE); edges.More(); edges.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(edges.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        BRepAdaptor_Curve curve(edge);
        constexpr int samples = 8;
        for (int i = 1; i < samples; ++i) {
            const double parameter = curve.FirstParameter()
                + (curve.LastParameter() - curve.FirstParameter()) * i / samples;
            if (!onSurface(curve.Value(parameter), BRep_Tool::Tolerance(edge))) {
                return false;
            }
        }
    }
    Standard_Real uMin = 0.0;
    Standard_Real uMax = 0.0;
    Standard_Real vMin = 0.0;
    Standard_Real vMax = 0.0;
    BRepTools::UVBounds(face, uMin, uMax, vMin, vMax);
    BRepAdaptor_Surface faceSurface(face);
    constexpr int steps = 4;
    for (int i = 1; i < steps; ++i) {
        for (int j = 1; j < steps; ++j) {
            const gp_Pnt2d uv(uMin + (uMax - uMin) * i / steps, vMin + (vMax - vMin) * j / steps);
            BRepClass_FaceClassifier classifier(face, uv, Precision::Confusion());
            if (classifier.State() == TopAbs_IN
                && !onSurface(faceSurface.Value(uv.X(), uv.Y()), 0.0)) {
                return false;
            }
        }
    }
    try {
        gp_Pnt point;
        gp_Pnt2d uv;
        if (BOPTools_AlgoTools3D::PointInFace(face, point, uv, new IntTools_Context) == 0
            && !onSurface(point, 0.0)) {
            return false;
        }
    }
    catch (const Standard_Failure&) {
        // No point found inside: the boundary decides.
    }
    return true;
}

// Whether a face lies within another face on the same surface: their common area is its own.
bool liesWithin(const TopoDS_Face& face, const TopoDS_Face& other)
{
    try {
        const double area = faceArea(face);
        BRepAlgoAPI_Common common(face, other);
        if (!common.IsDone()) {
            return false;
        }
        return std::fabs(faceArea(common.Shape()) - area)
            <= std::max(area * 1e-6, Precision::Confusion());
    }
    catch (const Standard_Failure&) {
        return false;
    }
}

// Whether the first side meets the face's whole surface first on the face: the sweep of the
// first side's profile up to the whole surface ends only on the face, and is the first side's
// tool. Both are whole sweeps, not clipped by the base, since ops#293 round 5: BRepFeat's tools
// were, and a comparison of them alone passed when the first side ran through the base (a
// Revolution) or through empty space (a Groove) between the surface's first hit and the face:
// the second side then stopped at the mirror of that first hit, and where the base isn't
// symmetric, the result lost material silently (the PR 268 verification's High). A sweep that
// fails throws, for the caller to say so.
bool firstSideEndsOnFace(
    const TopoShape& upToFace,
    const TopoShape& whole,
    const TopoShape& firstSide,
    const std::function<TopoShape(const TopoShape&)>& sweepUpTo
)
{
    const TopoShape sweep = sweepUpTo(whole);
    if (sweep.isNull() || sweep.getShape().IsNull()) {
        return false;
    }
    const Handle(Geom_Surface) surface = BRep_Tool::Surface(TopoDS::Face(whole.getShape()));
    const TopoDS_Face& face = TopoDS::Face(upToFace.getShape());
    bool ends = false;
    for (TopExp_Explorer faces(sweep.getShape(), TopAbs_FACE); faces.More(); faces.Next()) {
        const TopoDS_Face& end = TopoDS::Face(faces.Current());
        if (!liesOnSurface(end, surface)) {
            continue;
        }
        if (!liesWithin(end, face)) {
            return false;
        }
        ends = true;
    }
    return ends && sameSolid(firstSide, sweep);
}

// The up-to face of Symmetric's second side, given the first side's face, its mirror image in the
// profile plane, the first side's tool, and a way to sweep the first side's profile up to another
// face. A face across the
// profile plane crosses its own image there, and BRepFeat then lost the second side or revolved
// it the long way round, silently, whenever the face was a face of the base: across the plane it
// isn't symmetric about (a wall turned by any angle, a pipe longer on one side), and earlier
// across the plane it is (ops#254, ops#272).
// - An image that covers the face's points (a wall or a disk across the plane, an unbounded
//   plane through it) gives way to the face itself, which Two sides passes for both sides.
// - The image of any other face that reaches the plane (touching it included), or that shares
//   the face's plane (a hole on one side of a wall across it), gives way to its whole
//   surface. The second side meets that first where the image lies if the first side meets the
//   face's whole surface first on the face (firstSideEndsOnFace). If it doesn't (the surface is
//   met first off the face, or through a hole in it), or the surface can't be extended, the
//   feature fails rather than stop the second side elsewhere.
// - Any other image stays: that of a face off the plane.
TopoShape secondSideUpToFace(
    const TopoShape& upToFace,
    const TopoShape& mirrored,
    const gp_Pln& profilePlane,
    const TopoShape& firstSide,
    const std::function<TopoShape(const TopoShape&)>& sweepUpTo
)
{
    if (upToFace.isNull() || mirrored.isNull() || upToFace.getShape().ShapeType() != TopAbs_FACE
        || mirrored.getShape().ShapeType() != TopAbs_FACE) {
        return mirrored;
    }
    const TopoDS_Face& face = TopoDS::Face(upToFace.getShape());
    const TopoDS_Face& image = TopoDS::Face(mirrored.getShape());
    const bool samePlane = onSamePlane(face, image);
    if (isUnboundedFace(upToFace) || isUnboundedFace(mirrored)) {
        return samePlane ? upToFace : mirrored;
    }
    if (coversSamePoints(upToFace, mirrored)) {
        return upToFace;
    }
    if (samePlane || reachesPlane(upToFace, profilePlane)) {
        const TopoShape whole = wholeSurface(face);
        bool endsOnFace = false;
        // The sweep up to the whole surface fails where the surface cuts through the profile or
        // can't be checked against it: that reason, not a first hit before the face (the PR 273
        // review's L1).
        try {
            endsOnFace = firstSideEndsOnFace(upToFace, whole, firstSide, sweepUpTo);
        }
        catch (const Base::Exception& error) {
            throw Base::RuntimeError(
                std::string("Symmetric: the second side's check revolves the first side up to the "
                            "whole surface of the up-to face, and that failed. Use Two sides. "
                            "The reason, said of that surface: ")
                + error.what()
            );
        }
        catch (const Standard_Failure&) {
            throw Base::RuntimeError(
                "Symmetric: the second side's check could not revolve the first side up to the "
                "up-to face's whole surface. Use Two sides."
            );
        }
        if (!endsOnFace) {
            throw Base::RuntimeError(
                "Symmetric: the profile meets the up-to face's surface before the face itself, "
                "so the second side can't mirror the first. Use Two sides."
            );
        }
        return wholeSurface(image);
    }
    return mirrored;
}

// The faces an up-to revolution revolves one at a time: a profile of several separate faces is
// revolved face by face, each up to its own face, and the tools are fused (ops#263). One
// BRepFeat call for the whole profile named only its last face's elements from the profile: its
// later per-face steps rebuild the earlier faces' edges, so references to those faces could move
// to other faces silently. A profile of one face (also in a compound) stays whole, as before.
std::vector<TopoShape> upToProfileFaces(const TopoShape& profile)
{
    if (profile.countSubShapes(TopAbs_FACE) > 1) {
        return profile.getSubTopoShapes(TopAbs_FACE);
    }
    return {profile};
}

// One face's tool of a profile of several, with only this feature's names on the elements that
// have one (ops#263). BRepFeat names the pieces of a base edge it splits from that edge, told
// apart by the duplicate counter alone, so the pieces in two faces' tools got the same name.
// Each piece also has a name from its face's profile edge, and the fusion with the base names it
// as the base edge's piece again. An element with no name of this feature's keeps its names.
TopoShape ownNamesWhereNamed(const TopoShape& tool, long featureTag)
{
    if (!tool.hasElementMap()) {
        return tool;
    }
    const std::string own = std::to_string(featureTag);
    auto isOwn = [&own](const Data::MappedName& name) {
        const auto& decoded = Data::MappedName::getDecodedMappedName(name.toString());
        return !decoded.empty() && decoded.front().iterationTag == own;
    };
    struct Named
    {
        Data::IndexedName element;
        Data::MappedName name;
        Data::ElementIDRefs sids;
    };
    std::vector<Named> kept;
    bool dropped = false;
    for (const char* type : {"Vertex", "Edge", "Face"}) {
        const int count = tool.countSubShapes(type);
        for (int i = 1; i <= count; ++i) {
            const auto element = Data::IndexedName::fromConst(type, i);
            const auto names = tool.getElementMappedNames(element);
            const bool hasOwn = std::ranges::any_of(names, [&](const auto& n) {
                return isOwn(n.first);
            });
            for (const auto& [name, sids] : names) {
                if (hasOwn && !isOwn(name)) {
                    dropped = true;
                    continue;
                }
                kept.push_back({element, name, sids});
            }
        }
    }
    if (!dropped) {
        return tool;
    }
    TopoShape result(tool);
    result.resetElementMap();
    for (const auto& named : kept) {
        result.setElementName(named.element, named.name, result.Tag, &named.sids);
    }
    return result;
}

// A shape's volume and a bound on its error. BRepGProp's default integration, a fixed number of
// points per face, was 7 % off on a surface of revolution of a B-spline edge (26.19 for 28.05,
// ops#338), so it integrates adaptively to 1e-6 and returns the error it reached.
struct SolidVolume
{
    double value;
    double error;
};

SolidVolume solidVolume(const TopoDS_Shape& shape)
{
    if (shape.IsNull()) {
        return {0.0, 0.0};
    }
    GProp_GProps props;
    const double relativeError = BRepGProp::VolumeProperties(shape, props, 1e-6);
    return {props.Mass(), std::fabs(relativeError * props.Mass())};
}

// solidVolume(), or for a tool built by constructFirstContact() and what it was combined into, the
// volume integrated over knot spans: the adaptive integration was 2e-4 off on the folded wall's tool
// and refused its correct cut from the base (ops#293 D2). Sweeps the certificate accepts keep
// solidVolume() (D2a).
SolidVolume checkedVolume(const TopoDS_Shape& shape, bool constructed)
{
    if (!constructed || shape.IsNull()) {
        return solidVolume(shape);
    }
    const auto [value, error] = FirstContact::spanVolume(shape);
    return {value, error};
}

// The largest distance of a shape's bounding box's corners from the axis
double largestRadius(const TopoDS_Shape& shape, const gp_Ax1& axis)
{
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    if (box.IsVoid()) {
        return 0.0;
    }
    double xMin = 0.0;
    double yMin = 0.0;
    double zMin = 0.0;
    double xMax = 0.0;
    double yMax = 0.0;
    double zMax = 0.0;
    box.Get(xMin, yMin, zMin, xMax, yMax, zMax);
    const gp_Lin line(axis);
    double largest = 0.0;
    for (const double x : {xMin, xMax}) {
        for (const double y : {yMin, yMax}) {
            for (const double z : {zMin, zMax}) {
                largest = std::max(largest, line.Distance(gp_Pnt(x, y, z)));
            }
        }
    }
    return largest;
}

// The sweep of one profile face about the axis up to the up-to face, built without BRepFeat:
// the face revolved a sliver short of a whole turn, split by the up-to face, and the pieces that
// start at the profile. Each point of the profile goes as far as the face, the first time it
// gets there, when first contact doesn't jump inside the profile (certifyFirstContact() checks
// that). BRepFeat kept another piece when a circle of the profile crosses the face more than once
// (a torus round the axis, a whole cylinder beside the profile): the part between the crossings,
// or a broken shape that lost the base in the fuse, with no error (ops#293). Named into `named`
// from the sweep, which is named from the profile, and the up-to face. `faceParts` gets the
// pieces of the up-to face. Fails when a piece that starts at the profile reaches the end of the
// turn: the face doesn't stop it. `tolerance` is that of the checks (profileCheckTolerance()).
TopoShape sweepUpToFace(
    TopoShape named,
    const TopoShape& profile,
    const TopoDS_Face& face,
    const gp_Ax1& axis,
    double tolerance,
    TopTools_IndexedMapOfShape& faceParts
)
{
    auto fail = []() {
        return Base::RuntimeError(
            QT_TRANSLATE_NOOP("Exception", "Could not revolve up to the face")
        );
    };
    // Empty, with the tag, hasher and history algorithm of `named`
    const TopoShape blank(named);
    // The sliver keeps the end of the turn apart from its start, by more than the inputs'
    // tolerance wherever the profile is at least a tenth of its largest radius from the axis. A
    // face flush with the profile, within its tolerance of the start, bridged a gap of 1e-4
    // radians, and the piece reached the end: up to a face of tolerance 1e-4 flush with a profile
    // at radius 3, every Revolution failed as going all the way round (ops#338).
    const double radius = largestRadius(profile.getShape(), axis);
    const double sliver = radius > 0.0 ? std::clamp(tolerance / radius, 1e-4, 1e-2) : 1e-4;
    BRepPrimAPI_MakeRevol turn(profile.getShape(), axis, 2.0 * std::numbers::pi - sliver);
    if (!turn.IsDone()) {
        throw fail();
    }
    TopoShape sweep(blank);
    sweep.makeElementShape(turn, profile, Part::OpCodes::Revolve);
    BRepAlgoAPI_Splitter splitter;
    TopTools_ListOfShape arguments;
    arguments.Append(sweep.getShape());
    TopTools_ListOfShape tools;
    tools.Append(face);
    splitter.SetArguments(arguments);
    splitter.SetTools(tools);
    splitter.Build();
    if (!splitter.IsDone()) {
        throw fail();
    }
    // The pieces of the start and end caps
    auto piecesOf = [&splitter](const TopoDS_Shape& shape) {
        return Part::UpToSplitMapper::piecesOf(splitter, shape);
    };
    const TopTools_IndexedMapOfShape start = piecesOf(turn.FirstShape());
    const TopTools_IndexedMapOfShape end = piecesOf(turn.LastShape());
    faceParts = piecesOf(face);
    std::vector<TopoDS_Shape> kept;
    for (TopExp_Explorer solids(splitter.Shape(), TopAbs_SOLID); solids.More(); solids.Next()) {
        bool atStart = false;
        bool atEnd = false;
        for (TopExp_Explorer faces(solids.Current(), TopAbs_FACE); faces.More(); faces.Next()) {
            atStart = atStart || start.Contains(faces.Current());
            atEnd = atEnd || end.Contains(faces.Current());
        }
        if (atStart && atEnd) {
            throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                "Exception",
                "Could not revolve up to the face: part of the profile goes all the way round "
                "without meeting it"
            ));
        }
        if (atStart) {
            kept.push_back(solids.Current());
        }
    }
    if (kept.empty()) {
        throw fail();
    }
    const TopoDS_Shape result = Part::UpToSplitMapper::keptShape(kept);
    auto firstShape = [&turn](const TopoDS_Shape& element) { return turn.FirstShape(element); };
    named.makeShapeWithElementMap(
        result,
        Part::UpToSplitMapper(splitter, turn, firstShape, profile.getShape(), result),
        {sweep, TopoShape(face)},
        Part::OpCodes::Revolve
    );
    return named;
}

// Where points are in a shape's solids: in one of them, on one's boundary, or outside them all.
// Each solid is loaded once: a classifier built per point made the check slow with many holes
// (PR 279 review: 2.8 s for 40).
class SolidStates
{
public:
    explicit SolidStates(const TopoDS_Shape& shape)
    {
        for (TopExp_Explorer solids(shape, TopAbs_SOLID); solids.More(); solids.Next()) {
            classifiers.push_back(std::make_unique<BRepClass3d_SolidClassifier>(solids.Current()));
        }
    }

    TopAbs_State operator()(const gp_Pnt& point, double tolerance) const
    {
        bool on = false;
        for (const auto& classifier : classifiers) {
            classifier->Perform(point, tolerance);
            if (classifier->State() == TopAbs_IN) {
                return TopAbs_IN;
            }
            on = on || classifier->State() == TopAbs_ON;
        }
        return on ? TopAbs_ON : TopAbs_OUT;
    }

private:
    std::vector<std::unique_ptr<BRepClass3d_SolidClassifier>> classifiers;
};

// The largest tolerance of a shape's vertices and edges
double largestTolerance(const TopoDS_Shape& shape)
{
    double largest = 0.0;
    for (TopExp_Explorer vertices(shape, TopAbs_VERTEX); vertices.More(); vertices.Next()) {
        largest = std::max(largest, BRep_Tool::Tolerance(TopoDS::Vertex(vertices.Current())));
    }
    for (TopExp_Explorer edges(shape, TopAbs_EDGE); edges.More(); edges.Next()) {
        largest = std::max(largest, BRep_Tool::Tolerance(TopoDS::Edge(edges.Current())));
    }
    return largest;
}

// Whether a tool up to a face is built to the precision of its inputs: no vertex or edge
// tolerance above 1e-3 of its size, or ten times its inputs' largest. Correct tools up to
// B-spline walls reach 1.7e-4 of their size (an intersection curve's approximation: 5.5e-4 on a
// diagonal of 3.3, the PR 279 round 1 verification), so 1e-4 refused them. Up to PartDesign's torus
// face Reversed, BRepFeat's tool and the sweep both had a vertex of tolerance 0.995 on a 2 x 2
// profile, covering edges that don't meet: its points classify right, but its caps measure 10.82
// and 5.86 where both are 7.05, and its volume 14.20 instead of 13.35, which no check of points
// sees (ops#293, PR 279 review). Good tools there stay below 5e-6.
bool toleranceHolds(const TopoDS_Shape& tool, std::initializer_list<TopoDS_Shape> inputs)
{
    Bnd_Box box;
    BRepBndLib::Add(tool, box);
    if (box.IsVoid()) {
        return false;
    }
    double limit = 1e-3 * std::sqrt(box.SquareExtent());
    for (const TopoDS_Shape& input : inputs) {
        limit = std::max(limit, 10.0 * largestTolerance(input));
    }
    return largestTolerance(tool) <= limit;
}

double largestEdgeTolerance(const TopoDS_Shape& shape)
{
    double largest = 0.0;
    for (TopExp_Explorer edges(shape, TopAbs_EDGE); edges.More(); edges.Next()) {
        largest = std::max(largest, BRep_Tool::Tolerance(TopoDS::Edge(edges.Current())));
    }
    return largest;
}

// Whether a fuse or cut of a tool up to a face with the base is built to the precision of the
// two: no edge tolerance above 1e-3 of the tool's size, or 1.5 times the largest edge tolerance
// of the base and the tool. Up to a torus whose seam meridian, loosened to 0.3, runs nearly along
// the tool's outer cylinder, the fuse made that meridian the edge between them, at tolerance 0.916
// (0.676 at 0.2), and the result held 0.06 to 0.09 more than base and tool, with a right tool and
// no other error (ops#293, PR 307 review). Over 235 accepted cases (turns 320 to 334 and 0, base
// tolerance 0.02 to 0.3) the right results' edges kept the inputs' largest tolerance, and the four
// wrong ones rose 3.05 to 3.38 times. Vertices are left out: the fuse widens them to cover the
// edges ending there, up to 4.1 times in right results (0.0821 on a base of 0.02).
bool combinedWithinTolerance(
    const TopoDS_Shape& result,
    const TopoDS_Shape& base,
    const TopoDS_Shape& tool
)
{
    Bnd_Box box;
    BRepBndLib::Add(tool, box);
    if (box.IsVoid()) {
        return false;
    }
    const double limit = std::max(
        1e-3 * std::sqrt(box.SquareExtent()),
        1.5 * std::max(largestEdgeTolerance(base), largestEdgeTolerance(tool))
    );
    return largestEdgeTolerance(result) <= limit;
}

// The certificate that the sweep up to the face is what first contact gives (ops#293 round 5;
// notes\revolution-upto-first-contact.md, sections 2 and 3). The sweep U is right exactly when
// first contact doesn't jump inside the profile, and then (i) no edge of the up-to face lies inside
// U, (ii) every part of the face on U's boundary is one the circles leave U through, and (iii) the
// face's silhouette under the rotation (where circles about the axis touch it) misses those parts.
// (i) and (ii) are a boolean and classifications on U's own faces; (iii) is the silhouette tree
// below. Nothing samples circles.

using namespace FirstContact;

// Where the up-to face's silhouette under the rotation may lie on `parts`, the parts of the face
// on the sweep's boundary: a point within the profile's size / 1024 of both, or none. The face is
// converted to NURBS exactly (BRepBuilderAPI_NurbsConvert: planes, quadrics, tori, B-splines,
// extrusions and revolutions of such curves) and cut into Bezier patches. A patch whose silhouette
// polynomial has one sign holds no silhouette point; another is split in two along its longer
// side, until its control net, which holds it, is within the profile's size / 128; then, if the
// net is within reach of a part, down to the size / 1024. Patches whose net can't reach the
// profile's turn or a part are dropped: z along the axis is linear in the poles, the radius from
// it is at most a pole's, and at least the net's centre's less half its diagonal. So no silhouette
// point on a part is missed, however narrow or tall the fold; a silhouette that only runs within
// the size / 1024 of a part is refused too (a false refusal). The round 4 grid missed a fold on a
// face much taller than the profile and a fold narrower than its step (the PR 279 round 4
// verification).
std::optional<gp_Pnt> silhouetteOn(
    const TopoDS_Face& face,
    const std::vector<TopoDS_Face>& parts,
    const TopoDS_Shape& profile,
    const gp_Ax1& axis,
    double tolerance
)
{
    auto tooComplex = []() {
        return Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Could not revolve up to the face: it is too complex to check within the profile's turn"
        ));
    };
    auto checkFailed = []() {
        return Base::RuntimeError(
            QT_TRANSLATE_NOOP("Exception", "Could not check the revolution up to the face")
        );
    };
    const Handle(Geom_BSplineSurface) surface = silhouetteSurface(face).surface;

    const gp_Lin line(axis);
    const gp_XYZ center = axis.Location().XYZ();
    const gp_XYZ direction = axis.Direction().XYZ();
    auto height = [&](const gp_XYZ& offset) {
        return offset.Dot(direction);
    };
    auto radius = [&](const gp_XYZ& offset) {
        return (offset - direction * offset.Dot(direction)).Modulus();
    };
    // The profile's turn: its radii and heights, from its bounding box's corners
    Bnd_Box profileBox;
    BRepBndLib::AddOptimal(profile, profileBox, Standard_False, Standard_False);
    if (profileBox.IsVoid()) {
        throw checkFailed();
    }
    const double size = std::sqrt(profileBox.SquareExtent());
    const double coarse = size / 128.0;
    const double fine = std::max(size / 1024.0, 2.0 * tolerance);
    double profileLow = std::numeric_limits<double>::max();
    double profileHigh = std::numeric_limits<double>::lowest();
    double profileFarthest = 0.0;
    {
        Standard_Real x[2];
        Standard_Real y[2];
        Standard_Real z[2];
        profileBox.Get(x[0], y[0], z[0], x[1], y[1], z[1]);
        for (int corner = 0; corner < 8; ++corner) {
            const gp_XYZ offset
                = gp_XYZ(x[corner & 1], y[(corner >> 1) & 1], z[(corner >> 2) & 1]) - center;
            profileLow = std::min(profileLow, height(offset));
            profileHigh = std::max(profileHigh, height(offset));
            profileFarthest = std::max(profileFarthest, radius(offset));
        }
    }
    const gp_XYZ profileMiddle
        = (profileBox.CornerMin().XYZ() + profileBox.CornerMax().XYZ()) / 2.0 - center;
    const double profileNearest = std::max(0.0, radius(profileMiddle) - size / 2.0);

    std::vector<Bnd_Box> partBoxes;
    std::vector<std::unique_ptr<BRepExtrema_DistShapeShape>> partDistances;
    std::vector<std::unique_ptr<BRepExtrema_DistShapeShape>> edgeDistances;
    // A silhouette point farther than this from a part's boundary lies inside the part. A
    // silhouette along the boundary (a face touching the profile's edge, a plane through the axis
    // that the profile touches) changes nothing inside it.
    double clearance = tolerance + 1e-6 * size;
    for (const TopoDS_Face& part : parts) {
        Bnd_Box box;
        BRepBndLib::AddOptimal(part, box, Standard_False, Standard_False);
        box.Enlarge(tolerance);
        partBoxes.push_back(box);
        auto distance = std::make_unique<BRepExtrema_DistShapeShape>();
        distance->LoadS2(part);
        partDistances.push_back(std::move(distance));
        TopoDS_Compound edges;
        BRep_Builder builder;
        builder.MakeCompound(edges);
        for (TopExp_Explorer explorer(part, TopAbs_EDGE); explorer.More(); explorer.Next()) {
            builder.Add(edges, explorer.Current());
        }
        auto edgeDistance = std::make_unique<BRepExtrema_DistShapeShape>();
        edgeDistance->LoadS2(edges);
        edgeDistances.push_back(std::move(edgeDistance));
        clearance = std::max(clearance, tolerance + 2.0 * largestTolerance(part));
    }
    auto distance = [&](BRepExtrema_DistShapeShape& to, const gp_Pnt& point) {
        to.LoadS1(BRepBuilderAPI_MakeVertex(point).Vertex());
        if (!to.Perform()) {
            throw checkFailed();
        }
        return to.Value();
    };
    // The last point whose distance from each part's boundary was computed, and that distance. The
    // distance changes no faster than the point moves, so a point nearer to it than `away` less
    // the distance is within `away` of the boundary too. Along a silhouette that runs on a part's
    // boundary (a plane flush with a profile edge) the roots on a leaf's side come every 1e-7 of
    // it, where the polynomial is zero within its rounding, and their distances cost seconds to
    // minutes (ops#338: 10 million for a profile of size 0.1 at radius 100, 66 s).
    std::vector<std::optional<std::pair<gp_Pnt, double>>> lastEdgeDistance(parts.size());
    // The same for the distance from each part, which decides both ways
    std::vector<std::optional<std::pair<gp_Pnt, double>>> lastPartDistance(parts.size());
    auto withinPart = [&](std::size_t k, const gp_Pnt& point, double reach) {
        if (const auto& last = lastPartDistance[k]) {
            const double moved = point.Distance(last->first);
            if (last->second + moved <= reach) {
                return true;
            }
            if (last->second - moved > reach) {
                return false;
            }
        }
        const double fromPart = distance(*partDistances[k], point);
        lastPartDistance[k] = std::pair {point, fromPart};
        return fromPart <= reach;
    };
    // Whether a point lies within `reach` of a part and farther than `away` from its boundary
    auto inside = [&](const gp_Pnt& point, double reach, double away) {
        for (std::size_t k = 0; k < parts.size(); ++k) {
            if (partBoxes[k].IsOut(point)) {
                continue;
            }
            const auto& last = lastEdgeDistance[k];
            if (last && last->second + point.Distance(last->first) <= away) {
                continue;
            }
            const double fromEdge = distance(*edgeDistances[k], point);
            lastEdgeDistance[k] = std::pair {point, fromEdge};
            if (fromEdge > away && withinPart(k, point, reach)) {
                return true;
            }
        }
        return false;
    };
    // Whether a point is within `reach` of a part whose box meets `box`
    auto reaches = [&](const gp_Pnt& point, const Bnd_Box& box, double reach) {
        for (std::size_t k = 0; k < parts.size(); ++k) {
            if (partBoxes[k].IsOut(box)) {
                continue;
            }
            if (withinPart(k, point, reach)) {
                return true;
            }
        }
        return false;
    };

    GeomConvert_BSplineSurfaceToBezierSurface pieces(surface);
    TColGeom_Array2OfBezierSurface patches(1, pieces.NbUPatches(), 1, pieces.NbVPatches());
    pieces.Patches(patches);
    std::vector<SilhouettePatch> stack;
    for (int i = patches.LowerRow(); i <= patches.UpperRow(); ++i) {
        for (int j = patches.LowerCol(); j <= patches.UpperCol(); ++j) {
            stack.push_back(silhouettePatch(patches(i, j), axis));
        }
    }
    // Leaves along a silhouette across a face many times the profile's size, before pruning
    constexpr int budget = 200000;
    int nodes = 0;
    while (!stack.empty()) {
        SilhouettePatch patch = std::move(stack.back());
        stack.pop_back();
        if (++nodes > budget) {
            throw tooComplex();
        }
        if (oneSign(patch.g)) {
            continue;
        }
        const int m = patch.weights.m;
        const int n = patch.weights.n;
        auto pole = [&](int i, int j) {
            const int k = patch.weights.index(i, j);
            const double weight = patch.weights.value[k];
            return gp_XYZ(patch.net[0].value[k], patch.net[1].value[k], patch.net[2].value[k])
                / weight;
        };
        Bnd_Box box;
        double low = std::numeric_limits<double>::max();
        double high = std::numeric_limits<double>::lowest();
        double farthest = 0.0;
        double lengthU = 0.0;
        double lengthV = 0.0;
        for (int i = 0; i <= m; ++i) {
            double along = 0.0;
            for (int j = 0; j <= n; ++j) {
                const gp_XYZ offset = pole(i, j);
                box.Add(gp_Pnt(offset + center));
                low = std::min(low, height(offset));
                high = std::max(high, height(offset));
                farthest = std::max(farthest, radius(offset));
                if (j > 0) {
                    along += (offset - pole(i, j - 1)).Modulus();
                }
            }
            lengthV = std::max(lengthV, along);
        }
        for (int j = 0; j <= n; ++j) {
            double along = 0.0;
            for (int i = 1; i <= m; ++i) {
                along += (pole(i, j) - pole(i - 1, j)).Modulus();
            }
            lengthU = std::max(lengthU, along);
        }
        const double diagonal = std::sqrt(box.SquareExtent());
        const gp_Pnt middle((box.CornerMin().XYZ() + box.CornerMax().XYZ()) / 2.0);
        const double nearest = std::max(0.0, radius(middle.XYZ() - center) - diagonal / 2.0);
        // Out of the profile's turn
        if (high < profileLow - tolerance || low > profileHigh + tolerance
            || farthest < profileNearest - tolerance || nearest > profileFarthest + tolerance) {
            continue;
        }
        if (std::ranges::all_of(partBoxes, [&](const Bnd_Box& part) { return part.IsOut(box); })) {
            continue;
        }
        if (diagonal <= coarse) {
            if (!reaches(middle, box, diagonal / 2.0 + tolerance)) {
                continue;
            }
            if (diagonal <= fine) {
                // The silhouette's points on the leaf's sides, or a loop or a near tangency
                // within it, inside a part: refused
                const Bernstein& g = patch.g;
                bool found = false;
                for (int side = 0; side < 4; ++side) {
                    const bool alongV = side < 2;
                    const int fixed = side % 2 == 0 ? 0 : (alongV ? g.m : g.n);
                    const int count = alongV ? g.n + 1 : g.m + 1;
                    std::vector<double> value(count);
                    std::vector<double> bound(count);
                    for (int k = 0; k < count; ++k) {
                        const int index = alongV ? g.index(fixed, k) : g.index(k, fixed);
                        value[k] = g.value[index];
                        bound[k] = g.bound[index];
                    }
                    const double at = side % 2 == 0 ? 0.0 : 1.0;
                    for (double root : bernsteinRoots(value, bound)) {
                        found = true;
                        const double s = alongV ? at : root;
                        const double t = alongV ? root : at;
                        const gp_XYZ offset(
                            valueAt(patch.net[0], s, t),
                            valueAt(patch.net[1], s, t),
                            valueAt(patch.net[2], s, t)
                        );
                        const gp_Pnt point(offset / valueAt(patch.weights, s, t) + center);
                        if (inside(point, tolerance, clearance)) {
                            return point;
                        }
                    }
                }
                if (!found
                    && inside(middle, diagonal / 2.0 + tolerance, diagonal / 2.0 + clearance)) {
                    return middle;
                }
                continue;
            }
        }
        const bool splitU = lengthU >= lengthV;
        auto [gLow, gHigh] = halves(patch.g, splitU);
        auto [wLow, wHigh] = halves(patch.weights, splitU);
        SilhouettePatch first {std::move(gLow), {}, std::move(wLow)};
        SilhouettePatch second {std::move(gHigh), {}, std::move(wHigh)};
        for (int k = 0; k < 3; ++k) {
            auto [netLow, netHigh] = halves(patch.net[k], splitU);
            first.net[k] = std::move(netLow);
            second.net[k] = std::move(netHigh);
        }
        stack.push_back(std::move(second));
        stack.push_back(std::move(first));
    }
    return std::nullopt;
}

// Refuses, loudly and naming the place, a sweep up to the face (sweepUpToFace()) that isn't what
// first contact gives: where first contact jumps inside the profile, the sweep holds part of a turn
// past the first contact (the jump's strip has no face of the sweep's to stop at), or misses one.
// `faceParts` are the pieces of the up-to face from the sweep's split.
//
// A refusal where first contact jumps is a JumpRefused: the revolution then builds the solid
// between walls along the jumps instead (tryToRevolveToFace(), ops#293 D2).
class JumpRefused: public Base::RuntimeError
{
public:
    using Base::RuntimeError::RuntimeError;
};

void certifyFirstContact(
    const TopoDS_Shape& sweep,
    const TopTools_IndexedMapOfShape& faceParts,
    const TopoDS_Face& face,
    const TopoDS_Shape& profile,
    const gp_Ax1& axis,
    double tolerance
)
{
    const gp_Lin line(axis);
    auto refusal = [&](const char* reason, const gp_Pnt& point) {
        const double along = gp_Vec(axis.Location(), point).Dot(gp_Vec(axis.Direction()));
        return JumpRefused(
            std::string(reason)
            + fmt::format(
                " (near radius {:.4g} from the axis, {:.4g} along it)",
                line.Distance(point),
                along
            )
        );
    };
    auto checkFailed = []() {
        return Base::RuntimeError(
            QT_TRANSLATE_NOOP("Exception", "Could not check the revolution up to the face")
        );
    };
    // (i) No edge of the face inside the sweep: seams aren't edges, the face goes on across them
    TopoDS_Compound edges;
    BRep_Builder builder;
    builder.MakeCompound(edges);
    bool anyEdge = false;
    for (TopExp_Explorer explorer(face, TopAbs_EDGE); explorer.More(); explorer.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(explorer.Current());
        if (!BRep_Tool::Degenerated(edge) && !BRep_Tool::IsClosed(edge, face)) {
            builder.Add(edges, edge);
            anyEdge = true;
        }
    }
    if (anyEdge) {
        TopoDS_Shape inside;
        try {
            BRepAlgoAPI_Common common(edges, sweep);
            if (!common.IsDone()) {
                throw checkFailed();
            }
            inside = common.Shape();
        }
        catch (const Standard_Failure&) {
            throw checkFailed();
        }
        const SolidStates states(sweep);
        for (TopExp_Explorer explorer(inside, TopAbs_EDGE); explorer.More(); explorer.Next()) {
            BRepAdaptor_Curve curve(TopoDS::Edge(explorer.Current()));
            const gp_Pnt middle
                = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2.0);
            if (states(middle, tolerance) == TopAbs_IN) {
                throw refusal(
                    QT_TRANSLATE_NOOP(
                        "Exception",
                        "Could not revolve up to the face: the face's edge lies in the profile's "
                        "way, so where the profile first meets the face jumps within the profile"
                    ),
                    middle
                );
            }
        }
    }
    // (ii) The circles leave the sweep through each part of the face on its boundary. The sign
    // of the face's normal against the circles changes only across the silhouette, which (iii)
    // keeps off these parts, so one point per part decides.
    std::vector<TopoDS_Face> parts;
    Handle(IntTools_Context) context = new IntTools_Context;
    for (TopExp_Explorer solids(sweep, TopAbs_SOLID); solids.More(); solids.Next()) {
        if (solidVolume(solids.Current()).value <= 0.0) {
            throw checkFailed();
        }
        for (TopExp_Explorer faces(solids.Current(), TopAbs_FACE); faces.More(); faces.Next()) {
            if (!faceParts.Contains(faces.Current())) {
                continue;
            }
            const TopoDS_Face& part = TopoDS::Face(faces.Current());
            const bool internal = part.Orientation() == TopAbs_INTERNAL
                || part.Orientation() == TopAbs_EXTERNAL;
            parts.push_back(part);
            gp_Pnt point;
            gp_Pnt2d uv;
            try {
                if (BOPTools_AlgoTools3D::PointInFace(part, point, uv, context) != 0) {
                    throw checkFailed();
                }
            }
            catch (const Standard_Failure&) {
                throw checkFailed();
            }
            // The sweep on both sides of a part: the circles pass the face's edge and come back
            // round behind it, and the face doesn't split the sweep (a half tube whose end lies
            // in the profile's turn)
            if (internal) {
                throw refusal(
                    QT_TRANSLATE_NOOP(
                        "Exception",
                        "Could not revolve up to the face: the face's edge lies in the profile's "
                        "way, so where the profile first meets the face jumps within the profile"
                    ),
                    point
                );
            }
            BRepAdaptor_Surface surface(part);
            gp_Vec alongU;
            gp_Vec alongV;
            surface.D1(uv.X(), uv.Y(), point, alongU, alongV);
            gp_Vec outward = alongU.Crossed(alongV);
            if (part.Orientation() == TopAbs_REVERSED) {
                outward.Reverse();
            }
            const gp_Vec turning
                = gp_Vec(axis.Direction()).Crossed(gp_Vec(axis.Location(), point));
            const double scale = outward.Magnitude() * turning.Magnitude();
            if (scale <= gp::Resolution() || outward.Dot(turning) <= 1e-9 * scale) {
                throw refusal(
                    QT_TRANSLATE_NOOP(
                        "Exception",
                        "Could not revolve up to the face: the profile's turn meets the face from "
                        "behind, so where the profile first meets the face jumps within the profile"
                    ),
                    point
                );
            }
        }
    }
    if (parts.empty()) {
        throw checkFailed();
    }
    // (iii) No silhouette on those parts
    if (const std::optional<gp_Pnt> place = silhouetteOn(face, parts, profile, axis, tolerance)) {
        throw refusal(
            QT_TRANSLATE_NOOP(
                "Exception",
                "Could not revolve up to the face: the face folds over in the profile's way "
                "(circles about the axis touch it), so where the profile first meets the face "
                "jumps within the profile"
            ),
            *place
        );
    }
}

}  // namespace

Revolved::Revolved()
{
    ADD_PROPERTY_TYPE(StartType, (0L), "Start", App::Prop_None, "How to define the revolution start");
    StartType.setEnums(StartTypesEnums);
    ADD_PROPERTY_TYPE(
        StartOffset,
        (0.0),
        "Start",
        App::Prop_None,
        "Angular offset from the profile or selected start reference"
    );
    ADD_PROPERTY_TYPE(
        StartReference,
        (nullptr),
        "Start",
        App::Prop_None,
        "Face, plane or sketch used as the start reference"
    );
    Angle.setConstraints(&floatAngle);
    Angle2.setConstraints(&floatAngle);
    StartOffset.setConstraints(&floatAngle);
}

short Revolved::mustExecute() const
{
    if (Placement.isTouched() || SideType.isTouched() || Type.isTouched() || Type2.isTouched()
        || ReferenceAxis.isTouched() || Axis.isTouched() || Base.isTouched() || UpToFace.isTouched()
        || UpToFace2.isTouched() || Angle.isTouched() || Angle2.isTouched() || StartType.isTouched()
        || StartOffset.isTouched() || StartReference.isTouched()) {
        return 1;
    }
    return ProfileBased::mustExecute();
}

void Revolved::onChanged(const App::Property* prop)
{
    if (prop == &Midplane && !isRestoring() && !migratingDeprecatedProperties) {
        const char* impliedSideType = Midplane.getValue() ? "Symmetric" : "One side";

        // Scripts routinely assign every property, so only scream when the write actually
        // asks for something SideType is not already saying.
        if (SideType.getValueAsString() != std::string(impliedSideType)) {
            App::DocumentObject* obj = Profile.getValue();
            auto baseName = obj ? obj->getNameInDocument() : "";
            Base::Console().warning(
                "The 'Midplane' property being set for the revolution of %s is deprecated and has "
                "been replaced by the 'SideType' property in Revolved; assuming SideType='%s'."
                " Please update your script, this property will be removed in a future version.\n",
                baseName,
                impliedSideType
            );
            SideType.setValue(impliedSideType);
        }
    }

    ProfileBased::onChanged(prop);
}

App::DocumentObjectExecReturn* Revolved::executeRevolved(Part::RevolMode revolMode)
{
    constructedTool = false;
    try {
        return tryExecuteRevolved(revolMode);
    }
    catch (const Standard_Failure& e) {
        if (std::string(e.GetMessageString()) == "TopoDS::Face") {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Could not create face from sketch.\n"
                "Intersecting sketch entities in a sketch are not allowed."
            ));
        }

        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
}

App::DocumentObjectExecReturn* Revolved::tryExecuteRevolved(Part::RevolMode revolMode)
{
    if (onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    constexpr double maxDegree = 360.0;
    std::string sideType = SideType.getValueAsString();
    auto method = static_cast<RevolMethod>(Type.getValue());
    auto method2 = static_cast<RevolMethod>(Type2.getValue());

    if (method == RevolMethod::TwoAngles) {
        sideType = "Two sides";
        method = RevolMethod::Angle;
        method2 = RevolMethod::Angle;
    }
    if (method2 == RevolMethod::TwoAngles) {
        method2 = RevolMethod::Angle;
    }

    // Validate parameters
    double angleDeg = Angle.getValue();
    if (std::fabs(angleDeg) > maxDegree) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Angle of revolution too large")
        );
    }

    auto angle = Base::toRadians<double>(angleDeg);
    if (sideType != "Two sides" && std::fabs(angle) < Precision::Angular()
        && method == RevolMethod::Angle) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Angle of revolution too small")
        );
    }

    double angle2Deg = Angle2.getValue();
    if (std::fabs(angle2Deg) > maxDegree) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Angle of revolution too large")
        );
    }

    double angle2 = Base::toRadians(angle2Deg);

    if (sideType == "Two sides" && method == RevolMethod::Angle && method2 == RevolMethod::Angle
        && std::fabs(angle) >= Precision::Angular() && std::fabs(angle2) >= Precision::Angular()
        && std::fabs(angle + angle2) < Precision::Angular()) {
        const std::string warning = Base::Translation::translate(
            "PartDesign",
            QT_TRANSLATE_NOOP(
                "PartDesign",
                "The two revolution angles cancel each other resulting in an empty operation."
            )
        );
        Base::Console().warning("%s\n", warning.c_str());
    }

    TopoShape sketchshape = getTopoShapeVerifiedFace();

    // if the Base property has a valid shape, fuse the AddShape into it
    TopoShape base = tryGetBaseShape();

    // update Axis from ReferenceAxis
    updateAxis();

    // get revolve axis
    const Base::Vector3d v = Axis.getValue();
    if (v.IsNull()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Reference axis is invalid")
        );
    }

    if (sketchshape.isNull()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Creating a face from sketch failed")
        );
    }

    gp_Dir dir = Base::convertTo<gp_Dir>(v);
    gp_Pnt pnt = Base::convertTo<gp_Pnt>(Base.getValue());
    positionByPrevious();
    auto invObjLoc = getInverseLocation(base);
    pnt.Transform(invObjLoc.Transformation());
    dir.Transform(invObjLoc.Transformation());
    base.move(invObjLoc);
    sketchshape.move(invObjLoc);
    if (Reversed.getValue()) {
        dir.Reverse();
    }

    // The faces chosen to revolve up to (ToFace), when set; one not set fails where it is used
    const bool twoSides = sideType == "Two sides";
    TopoShape chosenFace = makeTopoShape(false);
    TopoShape chosenFace2 = makeTopoShape(false);
    if (method == RevolMethod::ToFace && UpToFace.getValue()) {
        getUpToFaceFromLinkSub(chosenFace, UpToFace);
        chosenFace.move(invObjLoc);
    }
    if (twoSides && method2 == RevolMethod::ToFace && UpToFace2.getValue()) {
        getUpToFaceFromLinkSub(chosenFace2, UpToFace2);
        chosenFace2.move(invObjLoc);
    }
    // The sweep up to a face is split by the face (sweepUpToFace()), and OCCT raises in place the
    // tolerances of what it splits: the face's edges and vertices, the base feature's stored
    // shape's when the face is the base's. Up to a face, the revolution runs on copies of the
    // base and the chosen faces, made together, so that the tool's face parts are still the
    // base's for the fuse or cut with it (ops#347). The sweep adds curves on surfaces to the
    // profile's edges too, which are the sketch's stored shape's: the profile is copied as well
    if (revolvesUpToFace(method, revolMode) || (twoSides && revolvesUpToFace(method2, revolMode))) {
        const std::vector<TopoShape> copies =
            Part::FilletFallback::makerInputs({base, chosenFace, chosenFace2, sketchshape});
        base = copies[0];
        chosenFace = copies[1];
        chosenFace2 = copies[2];
        sketchshape = copies[3];
    }

    const gp_Ax1 revolutionAxis(pnt, dir);
    const char* startType = StartType.getValueAsString();
    const double startAngle = std::strcmp(startType, "Profile plane") == 0 ? 0.0
        : std::strcmp(startType, "Offset") == 0 ? Base::toRadians(StartOffset.getValue())
                                                : getStartReferenceAngle(
                                                      sketchshape,
                                                      StartReference,
                                                      revolutionAxis,
                                                      Base::toRadians(StartOffset.getValue()),
                                                      invObjLoc
                                                  );
    sketchshape = rotateProfileToStart(sketchshape, revolutionAxis, startAngle);

    // Check distance between sketchshape and axis - to avoid failures and crashes
    TopExp_Explorer xp;
    xp.Init(sketchshape.getShape(), TopAbs_FACE);
    for (; xp.More(); xp.Next()) {
        if (checkLineCrossesFace(gp_Lin(pnt, dir), TopoDS::Face(xp.Current()))) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Revolve axis intersects the sketch")
            );
        }
    }

    // Generate the revolution tool first; PartDesign applies the final base operation below.
    TopoShape result = makeTopoShape(false);

    std::vector<TopoShape> revolutions;
    auto addRevolution = [&revolutions](TopoShape&& revolution) {
        if (!revolution.isNull() && !revolution.getShape().IsNull()) {
            revolutions.emplace_back(std::move(revolution));
        }
    };

    bool fuseSideResults = false;

    // Both sides are named from the same profile edges under the feature's tag, so in V2 the
    // second side revolves a copy whose names are marked: a section with this feature's ID, CPY
    // and side 2 appended to every name. Otherwise the two sides' elements share names, told apart
    // only by the duplicate counter in the order of the final fuse (ops#240). The copy's op alone
    // doesn't mark them: V2 copies a child's names as they are. V1 keeps upstream's names.
    auto secondSideProfile = [&]() {
        TopoShape copy = sketchshape.makeElementCopy();
        if (getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2) {
            copy.appendElementSection(getID(), Part::OpCodes::Copy, "2");
        }
        return copy;
    };
    // Side 1's start face, when the sides are built apart, is the seam at the profile, and has
    // the profile's names, as the start face of one side or of two sides built as one solid
    // has. In V2 it is marked (CPY;1), so that a reference to that face doesn't move to the
    // seam, or the other way, when an edit switches between the builds (PR 243 round 5).
    // Unlike a Pad's, no far cap is marked here (farCapIsSide2 is false): a revolution's PRJ
    // sections take the revolved shape's tag, possibly the sketch's, not this feature's ID, and
    // markStartCap's partner test requires this feature's ID. Reusing it for a revolution would
    // reject every partner; check where the tag comes from first (PR 243 follow-up F3).
    auto markSeam = [&](TopoShape side) {
        markStartCap(side, sketchshape, "1", false, true);
        return side;
    };

    if (sideType == "Two sides") {
        constexpr double fullRevolution = 2.0 * std::numbers::pi;
        const double combinedAngle = angle + angle2;
        const bool isThroughAll = revolMode == Part::RevolMode::CutFromBase
            && (method == RevolMethod::ThroughAll || method2 == RevolMethod::ThroughAll);
        const bool coversFullRevolution = method == RevolMethod::Angle
            && method2 == RevolMethod::Angle
            && std::fabs(combinedAngle) >= fullRevolution - Precision::Angular();

        if (isThroughAll || coversFullRevolution) {
            // Through all is direction-independent, so either side makes the other one
            // irrelevant. Likewise, cap overlapping two-angle sweeps at one full turn.
            // Smaller signed totals are handled as one exact angular interval below.
            addRevolution(generateSingleRevolutionSide(
                isThroughAll ? RevolMethod::ThroughAll : RevolMethod::Angle,
                fullRevolution,
                chosenFace,
                sketchshape.makeElementCopy(),
                base,
                pnt,
                dir,
                revolMode
            ));
        }
        else if (
            method == RevolMethod::Angle && method2 == RevolMethod::Angle
            && std::fabs(combinedAngle) >= Precision::Angular()
        ) {
            // Both limits are angular, so construct the exact interval between them as one
            // primitive. Besides avoiding a boolean seam for opposite-side angles, this is
            // equivalent to XOR for same-side signed angles: 50 + (-20) starts at 20 degrees
            // and sweeps 30 degrees to 50 degrees.
            generateRevolution(
                result,
                sketchshape,
                gp_Ax1(pnt, dir),
                angle,
                angle2,
                false,
                false,
                RevolMethod::TwoAngles
            );
            // Its start face, side 2's end, has the profile's names, as one side's has
            addRevolution(std::move(result));
        }
        else {
            fuseSideResults = revolvesUpToFace(method, revolMode)
                || revolvesUpToFace(method2, revolMode);

            // Side 1's seam is marked on each face's tool, before the tools are fused: the
            // fusion renames a start face piece that another face's tool crosses, and the mark
            // then missed it, silently (PR 259 round 1)
            addRevolution(generateSingleRevolutionSide(
                method,
                angle,
                chosenFace,
                sketchshape.makeElementCopy(),
                base,
                pnt,
                dir,
                revolMode,
                true
            ));

            gp_Dir dir2 = dir;
            dir2.Reverse();
            addRevolution(generateSingleRevolutionSide(
                method2,
                angle2,
                chosenFace2,
                secondSideProfile(),
                base,
                pnt,
                dir2,
                revolMode
            ));
        }
    }
    else if (sideType == "Symmetric") {
        const bool isThroughAll = method == RevolMethod::ThroughAll
            && revolMode == Part::RevolMode::CutFromBase;
        if (method == RevolMethod::Angle || isThroughAll) {
            generateRevolution(result, sketchshape, gp_Ax1(pnt, dir), angle, 0.0, true, false, method);
            // One solid, as Two sides by two angles
            addRevolution(std::move(result));
        }
        else {
            // Each face of the profile on its own, both sides (ops#263); the sides and faces are
            // fused, since two faces' tools may overlap.
            const std::vector<TopoShape> faces = upToProfileFaces(sketchshape);
            const std::vector<TopoShape> secondFaces = upToProfileFaces(secondSideProfile());
            fuseSideResults = revolvesUpToFace(method, revolMode) || faces.size() > 1;
            gp_Ax1 axis(pnt, dir);
            // Use the profile's actual plane. The center of its axis-aligned bounding box is not
            // necessarily on that plane for an asymmetric tilted profile; using it as the mirror
            // origin made the angles unequal and could make BRepFeat fail.
            gp_Pln sketchPlane;
            if (!sketchshape.findPlane(sketchPlane)) {
                throw Base::RuntimeError("Could not determine the sketch plane!");
            }
            gp_Ax2 mirrorPlane(sketchPlane.Location(), sketchPlane.Axis().Direction());
            gp_Dir dir2 = dir;
            dir2.Reverse();
            const bool ownNamesPerFace = faces.size() > 1
                && getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2;
            auto perFace = [&](TopoShape tool) {
                return ownNamesPerFace ? ownNamesWhereNamed(tool, getID()) : tool;
            };
            for (std::size_t i = 0; i < faces.size(); ++i) {
                TopoShape upToFace
                    = getRevolutionUpToFace(method, chosenFace, base, faces[i], axis);
                TopoShape side = tryToRevolveToFace(upToFace, axis, faces[i].makeElementCopy());
                if (side.isNull() || side.getShape().IsNull()) {
                    continue;
                }
                addRevolution(perFace(markSeam(side.makeElementCopy())));
                TopoShape mirroredUpToFace = secondSideUpToFace(
                    upToFace,
                    upToFace.makeElementMirror(mirrorPlane),
                    sketchPlane,
                    side,
                    [&](const TopoShape& face) {
                        return tryToRevolveToFace(face, axis, faces[i].makeElementCopy());
                    }
                );
                addRevolution(perFace(
                    tryToRevolveToFace(mirroredUpToFace, gp_Ax1(pnt, dir2), secondFaces[i])
                ));
            }
        }
    }
    else {
        addRevolution(generateSingleRevolutionSide(
            method,
            angle,
            chosenFace,
            sketchshape,
            base,
            pnt,
            dir,
            revolMode
        ));
    }

    if (revolutions.empty()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "No revolution geometry was generated")
        );
    }
    if (revolutions.size() == 1) {
        result = revolutions.front();
    }
    else if (fuseSideResults) {
        // Up-to-face tools may overlap. Fuse them so that the preview stays continuous before
        // PartDesign applies the final base operation.
        result.makeElementFuse(revolutions, Part::OpCodes::Revolve);
    }
    else {
        result.makeElementXor(revolutions, Part::OpCodes::Revolve);
    }

    // An up-to-face tool's fuse or cut with the base gave a wrong volume where a torus's seam
    // runs (ops#293: 487.95 for 487.09)
    setResult(
        base,
        result,
        revolvesUpToFace(method, revolMode)
            || (sideType == "Two sides" && revolvesUpToFace(method2, revolMode))
    );

    // eventually disable some settings that are not valid for the current method
    updateProperties();

    return App::DocumentObject::StdReturn;
}

void Revolved::setResult(const TopoShape& base, const TopoShape& revolved, bool checkVolume)
{
    if (revolved.isNull()) {
        throw Base::RuntimeError(QT_TRANSLATE_NOOP("Exception", "Could not revolve the sketch!"));
    }
    // store shape before refinement
    this->rawShape = revolved;
    TopoShape result = refineShapeIfActive(revolved);
    // set the additive shape property for later usage in e.g. pattern
    this->AddSubShape.setValue(result);

    if (!base.isNull()) {
        const TopoShape tool = result;
        result = makeShape(base, result);
        // A correct fuse holds at least the larger of the two and at most both; a correct cut at
        // least the base less the tool and at most the base
        if (checkVolume) {
            const auto [baseVolume, baseError] = checkedVolume(base.getShape(), constructedTool);
            const auto [toolVolume, toolError] = checkedVolume(tool.getShape(), constructedTool);
            const auto [volume, error] = checkedVolume(result.getShape(), constructedTool);
            const double slack = 1e-6 * (baseVolume + toolVolume) + baseError + toolError + error
                + Precision::Confusion();
            const bool fuse = volume >= std::max(baseVolume, toolVolume) - slack
                && volume <= baseVolume + toolVolume + slack;
            const bool cut = volume >= baseVolume - toolVolume - slack
                && volume <= baseVolume + slack;
            if (!(getAddSubType() == FeatureAddSub::Type::Additive ? fuse : cut)) {
                throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Could not combine the revolution with the base: the result's volume is wrong"
                ));
            }
            if (!combinedWithinTolerance(result.getShape(), base.getShape(), tool.getShape())) {
                throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Could not combine the revolution with the base: the result's edges don't meet "
                    "within the precision of the base and the revolution"
                ));
            }
        }
        // store shape before refinement
        this->rawShape = result;
        result = refineShapeIfActive(result);
    }
    if (!isSingleSolidRuleSatisfied(result.getShape())) {
        throw Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Result has multiple solids: enable 'Allow Compound' in the active body."
        ));
    }
    result = getSolid(result);
    this->Shape.setValue(result);
}

// The tool up to a face is the sweep up to it (sweepUpToFace()), certified to be what first contact
// gives (certifyFirstContact()); otherwise the revolution fails, naming where first contact jumps:
// never a wrong solid without an error (ops#293). Not BRepFeat's tool: up to a face it kept a piece
// past a second crossing, swept 357 degrees, cut by an extended surface, or lost the base's thin
// ribs (notes\revolution-upto-first-contact.md, sections 4 and 9). Up to planar and cylindrical
// faces of the base, Revolution and Groove, One side and Reversed, the sweep's fuse and cut with
// the base gave BRepFeat's volumes exactly, and valid solids (ops#293 round 5, the coincident-face
// probe).
TopoShape Revolved::tryToRevolveToFace(
    const TopoShape& upToFace,
    const gp_Ax1& axis,
    const TopoShape& sketchshape
) const
{
    // The callers pass one face at a time (upToProfileFaces, ops#263)
    if (sketchshape.countSubShapes(TopAbs_FACE) > 1) {
        throw Base::RuntimeError(
            "Revolution: Internal error: several profile faces passed to tryToRevolveToFace()"
        );
    }
    if (upToFace.isNull() || upToFace.getShape().ShapeType() != TopAbs_FACE) {
        throw Base::RuntimeError("Could not revolve the sketch!");
    }
    const TopoDS_Face reachable = reachableUpToFace(upToFace, sketchshape, axis);
    const double tolerance = profileCheckTolerance(sketchshape.getShape(), reachable);
    if (cutsThroughProfile(
            sketchshape,
            reachable,
            cutThroughTolerance(sketchshape.getShape(), reachable)
        )) {
        throw Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "The up-to face cuts through the profile, so part of the profile can't revolve "
            "up to it"
        ));
    }
    if (returnsToProfile(sketchshape, axis)) {
        throw Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Could not revolve up to the face: the profile's circles about the axis come back to "
            "the profile's plane inside the profile, so its turn overlaps itself"
        ));
    }
    switch (profileReach(sketchshape, reachable, axis, tolerance)) {
        case ProfileReach::MeetsFace:
            break;
        case ProfileReach::MissesFace:
            throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                "Exception",
                "Part of the profile never meets the up-to face as it revolves about the axis"
            ));
        case ProfileReach::CrossesGapFirst:
            throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                "Exception",
                "Part of the profile passes through a gap in the up-to face before it meets "
                "the face as it revolves about the axis"
            ));
        case ProfileReach::PassesEdgeFirst:
            throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                "Exception",
                "Part of the profile passes the edge of the up-to face before it meets the "
                "face as it revolves about the axis, while the rest of it stops at the face"
            ));
    }
    // The boolean of the sweep with the face is tried again with both turned about the axis, which
    // changes neither the sweep nor where it meets the face, only the coordinates the boolean works
    // in. Where a profile edge lies on the face and leaves it tangentially, the same sweep came out
    // with an edge of tolerance 0.54 in the sketch's frame and 1.5e-4 in the body's (ops#338); a
    // turn of 1 or 2 radians gave 8e-5 to 1.5e-4 in every case. Each try faces the same checks.
    //
    // Where the certificate refuses because first contact jumps inside the profile, the solid is
    // built between walls along the jumps instead (constructFirstContact(), ops#293 D2), and only
    // there: every sweep the certificate accepts stays the tool (decision 90, D2a). The same three
    // frames are tried on a boolean failure (a throw, an invalid solid, a tolerance that doesn't
    // hold); the construction's own refusal, after its walls were pushed farther, refuses at once.
    // Either way the refusal names the jump. The construction is named from the profile and the
    // face, its walls from the face's elements (section 15.17).
    const auto constructToFirstContact = [&](const TopoShape& upTo, const JumpRefused& jump) {
        for (const double turn : {0.0, 1.0, 2.0}) {
            gp_Trsf rotation;
            rotation.SetRotation(axis, turn);
            const TopLoc_Location there(rotation);
            const TopoShape profile = sketchshape.moved(there);
            const TopoShape face = upTo.moved(there);
            TopoShape solid;
            try {
                solid = constructFirstContact(makeTopoShape(), face, profile, axis, tolerance).named;
            }
            catch (const Standard_Failure&) {
                continue;
            }
            catch (const Base::Exception& refusal) {
                throw JumpRefused(std::string(jump.what()) + ". " + refusal.what());
            }
            if (!solid.isValid()
                || !toleranceHolds(solid.getShape(), {profile.getShape(), face.getShape()})) {
                continue;
            }
            constructedTool = true;
            return solid.moved(there.Inverted());
        }
        throw jump;
    };
    const auto sweepToFirstContact = [&](const TopoShape& upTo) {
        bool built = false;
        for (const double turn : {0.0, 1.0, 2.0}) {
            gp_Trsf rotation;
            rotation.SetRotation(axis, turn);
            const TopLoc_Location there(rotation);
            const TopoShape profile = sketchshape.moved(there);
            const TopoDS_Face face = TopoDS::Face(upTo.getShape().Moved(there));
            TopTools_IndexedMapOfShape faceParts;
            TopoShape sweep;
            try {
                sweep = sweepUpToFace(makeTopoShape(), profile, face, axis, tolerance, faceParts);
            }
            catch (const Standard_Failure&) {
                continue;
            }
            built = true;
            if (!sweep.isValid()
                || !toleranceHolds(sweep.getShape(), {profile.getShape(), face})) {
                continue;
            }
            try {
                certifyFirstContact(
                    sweep.getShape(),
                    faceParts,
                    face,
                    profile.getShape(),
                    axis,
                    tolerance
                );
            }
            catch (const JumpRefused& jump) {
                return constructToFirstContact(upTo, jump);
            }
            return sweep.moved(there.Inverted());
        }
        if (!built) {
            throw Base::RuntimeError(
                QT_TRANSLATE_NOOP("Exception", "Could not revolve up to the face")
            );
        }
        throw Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Could not revolve up to the face: the result's edges don't meet within the precision "
            "of the profile and the face"
        ));
    };
    // The sweep is split by the face as it is, so that its face parts are the base's. When the
    // face's seams are looser than their curves need (withExactSeams()), the split is made again
    // with the seams exact, and the two sweeps must agree. A seam merged with a sweep face it runs
    // nearly along passes the certificate, which takes a seam for no boundary (ops#293, q4: 39.04
    // instead of 13.35, or 0.036 short). Split by the exact copy alone, the tool's face parts no
    // longer matched the base's face, and the fuse with the base gave the base's volume alone.
    // The up-to face keeps its names where it is the face checked (a bounded face), for the walls'
    TopoShape sweep = sweepToFirstContact(
        reachable.IsSame(upToFace.getShape()) ? upToFace : TopoShape(reachable)
    );
    const TopoDS_Face exactSeams = withExactSeams(reachable);
    if (!exactSeams.IsNull()) {
        bool agree = false;
        try {
            const TopoShape exactSweep = sweepToFirstContact(TopoShape(exactSeams));
            const auto [volume, error] = checkedVolume(sweep.getShape(), constructedTool);
            const auto [exactVolume, exactError] =
                checkedVolume(exactSweep.getShape(), constructedTool);
            agree = std::fabs(volume - exactVolume)
                <= 1e-6 * (volume + exactVolume) + error + exactError + Precision::Confusion();
        }
        catch (const Base::Exception&) {
        }
        catch (const Standard_Failure&) {
        }
        if (!agree) {
            throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                "Exception",
                "Could not revolve up to the face: the result's edges don't meet within the "
                "precision of the profile and the face"
            ));
        }
    }
    return sweep;
}

TopoShape Revolved::generateSingleRevolutionSide(
    RevolMethod method,
    double angle,
    const TopoShape& chosenFace,
    const TopoShape& sketchshape,
    const TopoShape& base,
    const gp_Pnt& pnt,
    const gp_Dir& dir,
    Part::RevolMode revolMode,
    bool markSeam
)
{
    TopoShape revolution = makeTopoShape();
    const bool isThroughAll = method == RevolMethod::ThroughAll
        && revolMode == Part::RevolMode::CutFromBase;

    if (method == RevolMethod::Angle || isThroughAll) {
        if (method == RevolMethod::Angle && std::fabs(angle) < Precision::Angular()) {
            return revolution;
        }
        generateRevolution(revolution, sketchshape, gp_Ax1(pnt, dir), angle, 0.0, false, false, method);
        if (markSeam) {
            markStartCap(revolution, sketchshape, "1");
        }
    }
    else if (
        method == RevolMethod::ToFirst
        || (method == RevolMethod::ToLast && revolMode == Part::RevolMode::FuseWithBase)
        || method == RevolMethod::ToFace
    ) {
        gp_Ax1 axis(pnt, dir);
        // Each face of the profile up to its own face (its own first or last one), fused (ops#263)
        const std::vector<TopoShape> faces = upToProfileFaces(sketchshape);
        // The own-names pass reads V2's sections only (PR 259 round 1)
        const bool ownNamesPerFace = faces.size() > 1
            && getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2;
        std::vector<TopoShape> tools;
        for (const TopoShape& face : faces) {
            TopoShape upToFace = getRevolutionUpToFace(method, chosenFace, base, face, axis);
            TopoShape tool = tryToRevolveToFace(upToFace, axis, face);
            if (tool.isNull() || tool.getShape().IsNull()) {
                continue;
            }
            // Side 1's seam before the own-names pass, as Symmetric's
            if (markSeam) {
                markStartCap(tool, sketchshape, "1");
            }
            tools.push_back(ownNamesPerFace ? ownNamesWhereNamed(tool, getID()) : tool);
        }
        if (tools.size() == 1) {
            revolution = tools.front();
        }
        else if (tools.size() > 1) {
            revolution.makeElementFuse(tools, Part::OpCodes::Revolve);
        }
    }
    else {
        throw Base::RuntimeError(
            "ProfileBased: Internal error: Unknown method for generateSingleRevolutionSide()"
        );
    }

    return revolution;
}

TopoShape Revolved::getRevolutionUpToFace(
    RevolMethod method,
    const TopoShape& chosenFace,
    const TopoShape& base,
    const TopoShape& sketchshape,
    const gp_Ax1& axis
) const
{
    TopoShape upToFace;
    if (method == RevolMethod::ToFace) {
        if (chosenFace.isNull()) {
            throw Base::ValueError("SketchBased: No face selected");
        }
        upToFace = chosenFace;
    }
    else {
        getUpToFace(
            upToFace,
            base,
            sketchshape,
            method == RevolMethod::ToFirst ? "UpToFirst" : "UpToLast",
            axis
        );
    }
    return upToFace;
}

TopoShape Revolved::tryGetBaseShape() const
{
    TopoShape base = makeTopoShape(false);
    try {
        base = getBaseTopoShape();
    }
    catch (const Base::Exception&) {
        // fall back to support (for legacy features)
    }

    return base;
}

bool Revolved::suggestReversed()
{
    try {
        updateAxis();
    }
    catch (const Base::Exception&) {
        return false;
    }

    double angle = ProfileBased::getReversedAngle(Base.getValue(), Axis.getValue());
    return suggestReversedAngle(angle);
}

std::optional<bool> Revolved::suggestedReversed()
{
    // without an axis, getAxis leaves a null direction, and the angle reads 0: no suggestion
    if (!ReferenceAxis.getValue()) {
        return std::nullopt;
    }
    try {
        updateAxis();
    }
    catch (const Base::Exception&) {
        return std::nullopt;
    }

    bool computed = false;
    double angle = ProfileBased::getReversedAngle(Base.getValue(), Axis.getValue(), &computed);
    // an angle of 0 (the profile's centre on the axis, or the axis along its normal) suggests
    // neither way
    if (!computed || std::fabs(angle) < Precision::Confusion()) {
        return std::nullopt;
    }
    return suggestReversedAngle(angle);
}

double Revolved::getStartOffset() const
{
    const char* startType = StartType.getValueAsString();
    if (std::strcmp(startType, "Profile plane") == 0) {
        return 0.0;
    }
    if (std::strcmp(startType, "Offset") == 0) {
        return StartOffset.getValue();
    }

    const Base::Vector3d axisBase = Base.getValue();
    const Base::Vector3d axisDirection = Axis.getValue();
    gp_Ax1 axis(Base::convertTo<gp_Pnt>(axisBase), Base::convertTo<gp_Dir>(axisDirection));
    if (Reversed.getValue()) {
        axis.Reverse();
    }

    TopLoc_Location identity;
    return Base::toDegrees(getStartReferenceAngle(
        getTopoShapeVerifiedFace(),
        StartReference,
        axis,
        Base::toRadians(StartOffset.getValue()),
        identity
    ));
}

double Revolved::getStartReferenceAngle(
    const TopoShape& profileShape,
    const App::PropertyLinkSub& reference,
    const gp_Ax1& axis,
    double offset,
    const TopLoc_Location& invObjLoc
) const
{
    if (!reference.getValue()) {
        return 0.0;
    }

    TopoShape referenceShape;
    const auto& subValues = reference.getSubValues();
    if (reference.getValue()->isDerivedFrom<Part::Part2DObject>()) {
        if (!subValues.empty()) {
            const Part::ShapeOptions options = Part::ShapeOption::NeedSubElement
                | Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform;
            referenceShape = Part::Feature::getTopoShape(
                reference.getValue(),
                options,
                subValues.front().c_str()
            );
        }
        if (!referenceShape.hasSubShape(TopAbs_FACE)) {
            referenceShape = getTopoShapeVerifiedFace(false, false, reference.getValue(), subValues);
        }
    }
    else {
        getUpToFaceFromLinkSub(referenceShape, reference);
    }
    referenceShape.move(invObjLoc);

    if (const auto angle = getPlanarStartReferenceAngle(profileShape, referenceShape, axis)) {
        return *angle + offset;
    }

    gp_Pnt orbitCenter;
    gp_Vec radial;
    if (!getProfileOrbit(profileShape, axis, orbitCenter, radial)) {
        throw Base::ValueError("Revolved: Cannot determine the profile path around the axis");
    }

    const auto faces = Part::findAllFacesCutBy(referenceShape, profileShape, axis);
    if (faces.empty()) {
        throw Base::ValueError("Revolved: Start reference does not intersect the profile path");
    }

    const auto nearest = std::ranges::min_element(faces, {}, &Part::cutTopoShapeFaces::distsq);
    return nearest->distsq / radial.Magnitude() + offset;
}

TopoShape Revolved::rotateProfileToStart(const TopoShape& profileShape, const gp_Ax1& axis, double angle)
{
    if (std::fabs(angle) < Precision::Angular()) {
        return profileShape;
    }

    TopoShape result = profileShape.makeElementCopy();
    gp_Trsf transform;
    transform.SetRotation(axis, angle);
    result.move(transform);
    return result;
}

void Revolved::updateAxis()
{
    App::DocumentObject* pcReferenceAxis = ReferenceAxis.getValue();
    const std::vector<std::string>& subReferenceAxis = ReferenceAxis.getSubValues();
    Base::Vector3d base;
    Base::Vector3d dir;
    getAxis(pcReferenceAxis, subReferenceAxis, base, dir, ForbiddenAxis::NotParallelWithNormal);

    Base.setValue(base);
    Axis.setValue(dir);
}

void Revolved::generateRevolution(
    TopoShape& revol,
    const TopoShape& sketchshape,
    const gp_Ax1& axis,
    double angle,
    double angle2,
    bool midplane,
    bool reversed,
    RevolMethod method
)
{
    if (method == RevolMethod::Angle || method == RevolMethod::TwoAngles
        || method == RevolMethod::ThroughAll) {
        double angleTotal = angle;
        double angleOffset = 0.;

        if (method == RevolMethod::TwoAngles) {
            // Rotate the face by `angle2`/`angle` to get "second" angle
            angleTotal += angle2;
            angleOffset = angle2 * -1.0;
        }
        else if (method == RevolMethod::ThroughAll) {
            angleTotal = 2 * std::numbers::pi;
        }
        else if (midplane) {
            // Rotate the face by half the angle to get Revolution symmetric to sketch plane
            angleOffset = -angle / 2;
        }

        if (std::fabs(angleTotal) < Precision::Angular()) {
            throw Base::ValueError("Cannot create a revolution with zero angle.");
        }

        gp_Ax1 revolAx(axis);
        if (reversed) {
            revolAx.Reverse();
        }

        TopoShape from = sketchshape;
        if (method == RevolMethod::TwoAngles || midplane) {
            gp_Trsf mov;
            mov.SetRotation(revolAx, angleOffset);
            TopLoc_Location loc(mov);
            from.move(loc);
        }

        // revolve the face to a solid
        // BRepPrimAPI is the only option that allows use of this shape for patterns.
        // See https://forum.freecad.org/viewtopic.php?f=8&t=70185&p=611673#p611673.
        revol = from;
        revol = revol.makeElementRevolve(revolAx, angleTotal);
        revol.Tag = -getID();
    }
    else {
        throw Base::RuntimeError(
            "ProfileBased: Internal error: Unknown method for generateRevolution()"
        );
    }
}

void Revolved::updateProperties()
{
    const std::string sideType = SideType.getValueAsString();
    const std::string method = Type.getValueAsString();
    const std::string method2 = Type2.getValueAsString();

    bool isAngleEnabled = method == "Angle";
    bool isUpToFaceEnabled = method == "UpToFace";
    bool isType2Enabled = sideType == "Two sides";
    bool isAngle2Enabled = isType2Enabled && (method2 == "Angle" || isLegacyTwoAngles(method2));
    bool isUpToFace2Enabled = isType2Enabled && method2 == "UpToFace";

    if (isLegacyTwoAngles(method)) {
        isAngleEnabled = true;
        isType2Enabled = true;
        isAngle2Enabled = true;
    }

    const bool isSymmetricAngleLike = sideType == "Symmetric"
        && (method == "Angle" || method == "ThroughAll");

    Angle.setReadOnly(!isAngleEnabled);
    Type2.setReadOnly(!isType2Enabled);
    Angle2.setReadOnly(!isAngle2Enabled);
    Midplane.setReadOnly(true);
    Reversed.setReadOnly(isSymmetricAngleLike);
    UpToFace.setReadOnly(!isUpToFaceEnabled);
    UpToFace2.setReadOnly(!isUpToFace2Enabled);

    const bool isStartOffsetEnabled = std::strcmp(StartType.getValueAsString(), "Profile plane") != 0;
    StartOffset.setReadOnly(!isStartOffsetEnabled);
    StartReference.setReadOnly(std::strcmp(StartType.getValueAsString(), "Reference") != 0);
}

void Revolved::onDocumentRestored()
{
    Base::StateLocker migrating(migratingDeprecatedProperties);

    if (isLegacyTwoAngles(Type.getValueAsString())) {
        Type.setValue("Angle");
        Type2.setValue("Angle");
        SideType.setValue("Two sides");
    }
    else {
        if (isLegacyTwoAngles(Type2.getValueAsString())) {
            Type2.setValue("Angle");
        }
        if (Midplane.getValue()) {
            Midplane.setValue(false);
            SideType.setValue("Symmetric");
        }
    }

    ProfileBased::onDocumentRestored();
}

}  // namespace PartDesign
