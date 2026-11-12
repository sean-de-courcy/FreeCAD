// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 Stefan Tröger <stefantroeger@gmx.net>              *
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

#include <array>

#include <BRepAdaptor_Curve.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <BRepTools_History.hxx>
#include <BRep_Tool.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GProp_GProps.hxx>
#include <GeomAPI_PointsToBSpline.hxx>
#include <GeomFill_Profiler.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Surface.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Pln.hxx>
#include <Precision.hxx>


#include <boost/core/ignore_unused.hpp>

#include <App/Document.h>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Mod/Part/App/FaceMakerCheese.h>

#include "Mod/Part/App/TopoShapeOpCode.h"

#include "FeatureLoft.h"
#include "ProfileRegions.h"
using namespace PartDesign;

namespace
{
// ops#655: Onshape's loft start and end condition "Normal to profile" (notes/loft-options.md)

/// k per unit magnitude, as a multiple of the distance between the profiles. Oracle fact GB12 (e)
/// fits k = 30.138 for profiles 30 apart; the rule behind it is asked of the oracle (ops#675), and
/// this is the one place to change when it answers.
constexpr double tangentPerDistance = 30.138 / 30.0;

gp_Pnt wireCentre(const TopoDS_Shape& wire)
{
    GProp_GProps props;
    BRepGProp::LinearProperties(wire, props);
    return props.CentreOfMass();
}

/// The point at each arc-length fraction of `edge`, walking from the end nearer `start` (an
/// open edge) or in the direction whose quarter point is nearer `quarter` (a closed edge).
std::vector<gp_Pnt> byArcLength(
    const TopoDS_Edge& edge,
    const gp_Pnt& start,
    const gp_Pnt& quarter,
    const std::vector<double>& fractions
)
{
    BRepAdaptor_Curve curve(edge);
    const double first = curve.FirstParameter();
    const double last = curve.LastParameter();
    const double length = GCPnts_AbscissaPoint::Length(curve);
    auto at = [&](double fraction, bool forward) {
        if (fraction <= 0) {
            return curve.Value(forward ? first : last);
        }
        if (fraction >= 1) {
            return curve.Value(forward ? last : first);
        }
        GCPnts_AbscissaPoint point(
            curve,
            forward ? fraction * length : -fraction * length,
            forward ? first : last
        );
        if (!point.IsDone()) {
            throw Base::CADKernelError("Loft: failed to walk a profile edge");
        }
        return curve.Value(point.Parameter());
    };
    bool forward = true;
    if (BRep_Tool::IsClosed(edge) || curve.Value(first).Distance(curve.Value(last)) < 1e-7) {
        forward = at(0.25, true).Distance(quarter) <= at(0.25, false).Distance(quarter);
    }
    else {
        forward = curve.Value(first).Distance(start) <= curve.Value(last).Distance(start);
    }
    std::vector<gp_Pnt> points;
    points.reserve(fractions.size());
    for (double fraction : fractions) {
        points.push_back(at(fraction, forward));
    }
    return points;
}

Handle(Geom_BSplineCurve) fit(const std::vector<gp_Pnt>& points, const std::vector<double>& fractions)
{
    TColgp_Array1OfPnt poles(1, static_cast<int>(points.size()));
    TColStd_Array1OfReal params(1, static_cast<int>(fractions.size()));
    for (size_t i = 0; i < points.size(); ++i) {
        poles(static_cast<int>(i) + 1) = points[i];
        params(static_cast<int>(i) + 1) = fractions[i];
    }
    GeomAPI_PointsToBSpline approx(poles, params, 3, 8, GeomAbs_C2, 1e-9);
    if (!approx.IsDone()) {
        throw Base::CADKernelError("Loft: failed to fit a profile edge");
    }
    return approx.Curve();
}

/// The ruled loft `ruled` between the planar profiles `first` and `last`, with each side face
/// replaced by Onshape's cubic in the loft direction: it leaves the first profile along its normal
/// (a start condition) and/or reaches the last one along its normal (an end condition), with a
/// natural (zero second derivative) end where no condition is set. Each matched pair of profile
/// edges is parameterised by arc length, as Onshape's plain loft pairs them. The faces keep the
/// ruled loft's names.
Part::TopoShape withProfileConditions(
    const Part::TopoShape& ruled,
    const TopoDS_Shape& first,
    const TopoDS_Shape& last,
    bool start,
    double startMagnitude,
    bool end,
    double endMagnitude
)
{
    gp_Pln plane0;
    gp_Pln plane1;
    if (!Part::TopoShape(first).findPlane(plane0) || !Part::TopoShape(last).findPlane(plane1)) {
        throw Base::CADKernelError(
            QT_TRANSLATE_NOOP("Exception", "Loft: Normal to profile needs planar profiles")
        );
    }
    const gp_Vec across(wireCentre(first), wireCentre(last));
    gp_Dir normal0 = plane0.Axis().Direction();
    gp_Dir normal1 = plane1.Axis().Direction();
    if (across.Dot(normal0) < 0) {
        normal0.Reverse();
    }
    if (across.Dot(normal1) < 0) {
        normal1.Reverse();
    }
    const double distance0 = across.Dot(normal0);
    const double distance1 = across.Dot(normal1);
    if (distance0 < Precision::Confusion() || distance1 < Precision::Confusion()) {
        throw Base::CADKernelError(QT_TRANSLATE_NOOP(
            "Exception",
            "Loft: Normal to profile needs each profile's centre off the other profile's plane"
        ));
    }
    const gp_Vec tangent0 = gp_Vec(normal0) * (startMagnitude * distance0 * tangentPerDistance);
    const gp_Vec tangent1 = gp_Vec(normal1) * (endMagnitude * distance1 * tangentPerDistance);

    constexpr int samples = 101;
    std::vector<double> fractions(samples);
    for (int i = 0; i < samples; ++i) {
        fractions[i] = double(i) / (samples - 1);
    }
    auto onPlane = [](const gp_Pln& plane, const gp_Pnt& point) {
        return plane.Distance(point) < 1e-6;
    };

    std::vector<TopoDS_Face> oldFaces;
    std::vector<TopoDS_Face> newFaces;
    for (TopExp_Explorer x(ruled.getShape(), TopAbs_FACE); x.More(); x.Next()) {
        const TopoDS_Face& face = TopoDS::Face(x.Current());
        TopoDS_Edge edge0;
        TopoDS_Edge edge1;
        for (TopExp_Explorer e(face, TopAbs_EDGE); e.More(); e.Next()) {
            const TopoDS_Edge& edge = TopoDS::Edge(e.Current());
            if (BRep_Tool::Degenerated(edge)) {
                continue;
            }
            BRepAdaptor_Curve curve(edge);
            const gp_Pnt a = curve.Value(curve.FirstParameter());
            const gp_Pnt b = curve.Value(curve.LastParameter());
            const gp_Pnt m = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
            if (onPlane(plane0, a) && onPlane(plane0, b) && onPlane(plane0, m)) {
                edge0 = edge;
            }
            else if (onPlane(plane1, a) && onPlane(plane1, b) && onPlane(plane1, m)) {
                edge1 = edge;
            }
        }
        if (edge0.IsNull() || edge1.IsNull()) {
            throw Base::CADKernelError("Loft: a side face doesn't join the two profiles");
        }
        // the ruled face's rows on the two profiles give the matched ends and the direction
        Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
        double u0 = 0;
        double u1 = 0;
        double v0 = 0;
        double v1 = 0;
        BRepTools::UVBounds(face, u0, u1, v0, v1);
        const double um = (u0 + u1) / 2;
        const double vm = (v0 + v1) / 2;
        // a quarter along each profile row, for a closed edge's direction
        const double uq = u0 + (u1 - u0) / 4;
        const double vq = v0 + (v1 - v0) / 4;
        gp_Pnt start0;
        gp_Pnt middle0;
        gp_Pnt start1;
        gp_Pnt middle1;
        if (onPlane(plane0, surface->Value(um, v0)) || onPlane(plane0, surface->Value(um, v1))) {
            const bool low = onPlane(plane0, surface->Value(um, v0));
            start0 = surface->Value(u0, low ? v0 : v1);
            middle0 = surface->Value(uq, low ? v0 : v1);
            start1 = surface->Value(u0, low ? v1 : v0);
            middle1 = surface->Value(uq, low ? v1 : v0);
        }
        else {
            const bool low = onPlane(plane0, surface->Value(u0, vm));
            start0 = surface->Value(low ? u0 : u1, v0);
            middle0 = surface->Value(low ? u0 : u1, vq);
            start1 = surface->Value(low ? u1 : u0, v0);
            middle1 = surface->Value(low ? u1 : u0, vq);
        }
        GeomFill_Profiler profiler;
        profiler.AddCurve(fit(byArcLength(edge0, start0, middle0, fractions), fractions));
        profiler.AddCurve(fit(byArcLength(edge1, start1, middle1, fractions), fractions));
        profiler.Perform(Precision::PConfusion());
        const int count = profiler.NbPoles();
        TColgp_Array1OfPnt row0(1, count);
        TColgp_Array1OfPnt row3(1, count);
        profiler.Poles(1, row0);
        profiler.Poles(2, row3);
        TColgp_Array2OfPnt poles(1, count, 1, 4);
        for (int j = 1; j <= count; ++j) {
            const gp_XYZ p0 = row0(j).XYZ();
            const gp_XYZ p3 = row3(j).XYZ();
            gp_XYZ p1;
            gp_XYZ p2;
            if (start && end) {
                p1 = p0 + tangent0.XYZ() / 3;
                p2 = p3 - tangent1.XYZ() / 3;
            }
            else if (start) {
                p1 = p0 + tangent0.XYZ() / 3;
                p2 = (p1 + p3) / 2;
            }
            else {
                p2 = p3 - tangent1.XYZ() / 3;
                p1 = (p0 + p2) / 2;
            }
            poles(j, 1) = gp_Pnt(p0);
            poles(j, 2) = gp_Pnt(p1);
            poles(j, 3) = gp_Pnt(p2);
            poles(j, 4) = gp_Pnt(p3);
        }
        TColStd_Array1OfReal uKnots(1, profiler.NbKnots());
        TColStd_Array1OfInteger uMults(1, profiler.NbKnots());
        profiler.KnotsAndMults(uKnots, uMults);
        TColStd_Array1OfReal vKnots(1, 2);
        TColStd_Array1OfInteger vMults(1, 2);
        vKnots(1) = 0;
        vKnots(2) = 1;
        vMults(1) = 4;
        vMults(2) = 4;
        Handle(Geom_BSplineSurface) side
            = new Geom_BSplineSurface(poles, uKnots, vKnots, uMults, vMults, profiler.Degree(), 3);
        BRepBuilderAPI_MakeFace maker(side, Precision::Confusion());
        if (!maker.IsDone()) {
            throw Base::CADKernelError("Loft: failed to make a side face");
        }
        oldFaces.push_back(face);
        newFaces.push_back(maker.Face());
    }

    BRepBuilderAPI_Sewing sewer(1e-6);
    for (const auto& face : newFaces) {
        sewer.Add(face);
    }
    sewer.Perform();
    const TopoDS_Shape sewn = sewer.SewedShape();

    // the names: each old face, edge and vertex is modified into its counterpart
    Handle(BRepTools_History) history = new BRepTools_History;
    for (size_t i = 0; i < oldFaces.size(); ++i) {
        TopoDS_Shape face = sewer.Modified(newFaces[i]);
        if (face.IsNull()) {
            face = newFaces[i];
        }
        history->AddModified(oldFaces[i], face);
    }
    auto ends = [](const TopoDS_Edge& edge) {
        BRepAdaptor_Curve curve(edge);
        return std::array<gp_Pnt, 3> {
            curve.Value(curve.FirstParameter()),
            curve.Value(curve.LastParameter()),
            curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2)
        };
    };
    TopTools_IndexedMapOfShape newEdges;
    TopExp::MapShapes(sewn, TopAbs_EDGE, newEdges);
    TopTools_IndexedMapOfShape oldEdges;
    TopExp::MapShapes(ruled.getShape(), TopAbs_EDGE, oldEdges);
    for (int i = 1; i <= oldEdges.Extent(); ++i) {
        const TopoDS_Edge& oldEdge = TopoDS::Edge(oldEdges(i));
        if (BRep_Tool::Degenerated(oldEdge)) {
            continue;
        }
        const auto o = ends(oldEdge);
        int best = 0;
        double bestMiddle = 0;
        for (int j = 1; j <= newEdges.Extent(); ++j) {
            const TopoDS_Edge& newEdge = TopoDS::Edge(newEdges(j));
            if (BRep_Tool::Degenerated(newEdge)) {
                continue;
            }
            const auto n = ends(newEdge);
            const bool same = (o[0].Distance(n[0]) < 1e-6 && o[1].Distance(n[1]) < 1e-6)
                || (o[0].Distance(n[1]) < 1e-6 && o[1].Distance(n[0]) < 1e-6);
            if (!same) {
                continue;
            }
            const double middle = o[2].Distance(n[2]);
            if (!best || middle < bestMiddle) {
                best = j;
                bestMiddle = middle;
            }
        }
        if (best) {
            history->AddModified(oldEdge, newEdges(best));
        }
    }
    TopTools_IndexedMapOfShape newVertices;
    TopExp::MapShapes(sewn, TopAbs_VERTEX, newVertices);
    TopTools_IndexedMapOfShape oldVertices;
    TopExp::MapShapes(ruled.getShape(), TopAbs_VERTEX, oldVertices);
    for (int i = 1; i <= oldVertices.Extent(); ++i) {
        const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(oldVertices(i)));
        for (int j = 1; j <= newVertices.Extent(); ++j) {
            if (BRep_Tool::Pnt(TopoDS::Vertex(newVertices(j))).Distance(point) < 1e-6) {
                history->AddModified(oldVertices(i), newVertices(j));
                break;
            }
        }
    }
    Part::TopoShape result(ruled.Tag, ruled.Hasher);
    result.makeShapeWithElementMap(sewn, Part::MapperHistory(history), {ruled});
    return result;
}
}  // namespace

PROPERTY_SOURCE(PartDesign::Loft, PartDesign::ProfileBased)

Loft::Loft()
{
    ADD_PROPERTY_TYPE(Sections, (nullptr), "Loft", App::Prop_None, "List of sections");
    Sections.setValue(nullptr);
    ADD_PROPERTY_TYPE(Ruled, (false), "Loft", App::Prop_None, "Create ruled surface");
    ADD_PROPERTY_TYPE(Closed, (false), "Loft", App::Prop_None, "Close Last to First Profile");
    ADD_PROPERTY_TYPE(
        StartCondition,
        (0L),
        "Loft",
        App::Prop_None,
        "How the loft leaves the first profile: None, or Normal to profile (two planar profiles)"
    );
    StartCondition.setEnums(ConditionEnums);
    ADD_PROPERTY_TYPE(
        StartMagnitude,
        (1.0),
        "Loft",
        App::Prop_None,
        "Scale of the start condition's tangent"
    );
    ADD_PROPERTY_TYPE(
        EndCondition,
        (0L),
        "Loft",
        App::Prop_None,
        "How the loft reaches the last profile: None, or Normal to profile (two planar profiles)"
    );
    EndCondition.setEnums(ConditionEnums);
    ADD_PROPERTY_TYPE(EndMagnitude, (1.0), "Loft", App::Prop_None, "Scale of the end condition's tangent");
}

const char* Loft::ConditionEnums[] = {"None", "Normal to profile", nullptr};

short Loft::mustExecute() const
{
    if (Sections.isTouched()) {
        return 1;
    }
    if (Ruled.isTouched()) {
        return 1;
    }
    if (Closed.isTouched() || StartCondition.isTouched() || StartMagnitude.isTouched()
        || EndCondition.isTouched() || EndMagnitude.isTouched()) {
        return 1;
    }

    return ProfileBased::mustExecute();
}

std::vector<Part::TopoShape> Loft::getSectionShape(
    const char* name,
    App::DocumentObject* obj,
    const std::vector<std::string>& subs,
    size_t expected_size
)
{
    auto useSketch = [](App::DocumentObject* obj, const std::vector<std::string>& subs) {
        // Be smart. If part of a sketch is selected, use the entire sketch unless it is a single
        // vertex - backward compatibility (#16630)
        if (!obj) {
            return false;
        }

        auto subName = subs.empty() ? "" : subs.front();
        return obj->isDerivedFrom<Part::Part2DObject>() && subName.find("Vertex") != 0;
    };

    // A sketch vertex that no longer exists ("?Vertex1") fails the vertex test above, so the
    // whole sketch would be used in its place (ops#71)
    if (auto missing = missingElements(obj, {subs.empty() ? std::string() : subs.front()}, true);
        !missing.empty()) {
        FC_THROWM(Part::NullShapeException, "Missing element in " << name << ": " << missing);
    }

    std::vector<TopoShape> shapes;
    auto useEntireSketch = useSketch(obj, subs);
    if (subs.empty() || std::ranges::find(subs, std::string()) != subs.end() || useEntireSketch) {
        shapes.push_back(
            Part::Feature::getTopoShape(obj, Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform)
        );
        if (shapes.back().isNull()) {
            std::stringstream str;
            str << "Failed to get shape of " << name;
            if (obj) {
                auto doc = obj->getDocument();
                str << " " << App::SubObjectT(obj, "").getSubObjectFullName(doc->getName());
            }
            THROWM(Part::NullShapeException, str.str());
        }
    }
    else {
        for (const auto& sub : subs) {
            shapes.push_back(
                Part::Feature::getTopoShape(
                    obj,
                    Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                        | Part::ShapeOption::Transform,
                    sub.c_str()
                )
            );
            if (shapes.back().isNull()) {
                std::stringstream str;
                str << "Failed to get shape of " << name;
                if (obj) {
                    auto doc = obj->getDocument();
                    App::SubObjectT subObj(obj, sub.c_str());
                    str << " " << subObj.getSubObjectFullName(doc->getName());
                }
                THROWM(Part::NullShapeException, str.str());
            }
        }
    }
    auto compound = Feature::makeTopoShape(obj, TopoDS_Shape(), 0, false)
                        .makeElementCompound(
                            shapes,
                            "",
                            TopoShape::SingleShapeCompoundCreationPolicy::returnShape
                        );
    // A whole sketch gives its closed loops; open curves are ignored, as in Onshape (ops#631).
    // With no loop left, the open wires stay, and the loft refuses them as before.
    // Loops from regions come outer wire first; the loft pairs every section's loops by role
    // (outerLoopsFirst below), and stops where regions leave more than one hole to pair
    bool fromRegions = false;
    if (useEntireSketch && picksRegions(subs)) {
        fromRegions = true;
        // Picked regions (they were left for the whole sketch before): their faces' wires,
        // adjacent regions merged, in the picks' order (feat/profile-regions)
        std::vector<TopoShape> faces;
        for (const auto& sub : subs) {
            auto face = Part::Feature::getTopoShape(
                obj,
                Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                    | Part::ShapeOption::Transform,
                sub.c_str()
            );
            if (face.isNull() || !face.hasSubShape(TopAbs_FACE)) {
                FC_THROWM(Part::NullShapeException, "Failed to get the region " << sub << " of " << name);
            }
            faces.push_back(face);
        }
        auto picked = Feature::makeTopoShape(obj, TopoDS_Shape(), 0, false).makeElementCompound(faces);
        auto merged = mergeAdjacentRegions(obj, subs, picked);
        // Several regions would pair in the picks' order with another section's sketch order:
        // a second silent find of the pairing (review r2), so the literal rule: one region
        if (merged.countSubShapes(TopAbs_FACE) > 1) {
            FC_THROWM(Base::CADKernelError, name << ": " << SectionRegionsMessage);
        }
        compound = wiresOfFaces(merged);
    }
    else if (useEntireSketch) {
        WholeSketchRegions rule(obj, compound);
        bool loopsDone = false;
        if (rule.sameAsLoops()) {
            try {
                if (auto loops = withoutOpenCurves(compound); !loops.isNull()) {
                    compound = loops;
                }
                loopsDone = true;
            }
            catch (const Base::Exception&) {
                // Onshape's regions below
            }
        }
        if (!loopsDone) {
            // Loops that overlap, touch or nest deeper: Onshape's regions, which pair with
            // another section's only as one loop
            if (auto faces = rule.faces(); !faces.isNull()) {
                fromRegions = true;
                compound = wiresOfFaces(faces);
                // One region with at most one hole pairs as the old loops do (outer to outer,
                // hole to hole); more, and the face maker's order isn't the sketch's
                if (faces.countSubShapes(TopAbs_FACE) > 1
                    || compound.countSubShapes(TopAbs_WIRE) > 2) {
                    FC_THROWM(Base::CADKernelError, name << ": " << SectionRegionsMessage);
                }
            }
        }
    }
    auto wires = compound.getSubTopoShapes(TopAbs_WIRE);
    auto edges = compound.getSubTopoShapes(TopAbs_EDGE, TopAbs_WIRE);  // get free edges and make
                                                                       // wires from it
    if (!edges.empty()) {
        auto extra = Feature::makeTopoShape(obj, TopoDS_Shape(), 0, false)
                         .makeElementWires(edges)
                         .getSubTopoShapes(TopAbs_WIRE);
        wires.insert(wires.end(), extra.begin(), extra.end());
    }
    const char* msg
        = "Sections need to have the same amount of wires or vertices as the base section";
    if (!wires.empty()) {
        if (expected_size && expected_size != wires.size()) {
            FC_THROWM(Base::CADKernelError, msg);
        }
        // Outer loops first, then holes, in every section: a section of regions (outer wire
        // first) pairs with one in the sketch's own order (feat/profile-regions review r1)
        std::size_t holes = 0;
        wires = outerLoopsFirst(wires, &holes);
        if (fromRegions && holes > 1) {
            FC_THROWM(Base::CADKernelError, name << ": " << SectionRegionsMessage);
        }
        return wires;
    }
    auto vertices = compound.getSubTopoShapes(TopAbs_VERTEX);
    if (vertices.empty()) {
        FC_THROWM(
            Base::CADKernelError,
            "Invalid " << name << " shape, expecting either wires or vertices"
        );
    }
    if (expected_size && expected_size != vertices.size()) {
        FC_THROWM(Base::CADKernelError, msg);
    }
    return vertices;
}

App::DocumentObjectExecReturn* Loft::execute()
{
    if (onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    std::vector<TopoShape> wires;
    try {
        wires = getSectionShape("Profile", Profile.getValue(), Profile.getSubValues());
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }

    // if the Base property has a valid shape, fuse the pipe into it
    TopoShape base;
    try {
        base = getBaseTopoShape();
    }
    catch (const Base::Exception&) {
    }

    auto hasher = getDocument()->getStringHasher();

    try {
        // setup the location
        this->positionByPrevious();
        auto invObjLoc = getInverseLocation(base);
        if (!base.isNull()) {
            base.move(invObjLoc);
        }

        // build up multisections
        auto multisections = Sections.getSubListValues();
        if (multisections.empty()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Loft: At least one section is needed")
            );
        }

        std::vector<std::vector<TopoShape>> wiresections;
        wiresections.reserve(wires.size());
        for (auto& wire : wires) {
            wiresections.emplace_back(1, wire);
        }

        for (const auto& subSet : multisections) {
            int i = 0;
            for (const auto& s :
                 getSectionShape("Section", subSet.first, subSet.second, wiresections.size())) {
                wiresections[i++].push_back(s);
            }
        }

        bool closed = Closed.getValue();
        // invalid for less then 3 sections
        if (multisections.size() < 2) {
            closed = false;
        }

        TopoShape result = makeTopoShape();
        std::vector<TopoShape> shapes;

        // build all shells
        std::vector<TopoShape> shells;
        for (auto& sectionWires : wiresections) {
            for (auto& wire : sectionWires) {
                wire.move(invObjLoc);
            }
            // ops#655: a profile condition rebuilds the ruled loft's side faces
            const bool conditioned = StartCondition.getValue() != 0 || EndCondition.getValue() != 0;
            if (conditioned) {
                if (sectionWires.size() != 2 || closed) {
                    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Loft: Normal to profile needs exactly two profiles"
                    ));
                }
                if (sectionWires.front().shapeType() == TopAbs_VERTEX
                    || sectionWires.back().shapeType() == TopAbs_VERTEX) {
                    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Loft: Normal to profile needs two planar profiles, not a point profile"
                    ));
                }
            }
            auto shell = makeTopoShape().makeElementLoft(
                sectionWires,
                Part::IsSolid::notSolid,
                Ruled.getValue() || conditioned ? Part::IsRuled::ruled : Part::IsRuled::notRuled,
                closed ? Part::IsClosed::closed : Part::IsClosed::notClosed
            );
            if (conditioned) {
                shell = withProfileConditions(
                    shell,
                    sectionWires.front().getShape(),
                    sectionWires.back().getShape(),
                    StartCondition.getValue() != 0,
                    StartMagnitude.getValue(),
                    EndCondition.getValue() != 0,
                    EndMagnitude.getValue()
                );
            }
            shells.push_back(shell);
        }

        // build the top and bottom face, sew the shell and build the final solid
        TopoShape front;
        if (wiresections[0].front().shapeType() != TopAbs_VERTEX) {
            front = getTopoShapeVerifiedFace();
            if (front.isNull()) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Loft: Creating a face from sketch failed")
                );
            }
            front.move(invObjLoc);
        }

        TopoShape back;
        if (wiresections[0].back().shapeType() != TopAbs_VERTEX) {
            std::vector<TopoShape> backwires;
            for (auto& sectionWires : wiresections) {
                backwires.push_back(sectionWires.back());
            }
            const char* faceMaker[] = {
                "Part::FaceMakerBullseye",
                "Part::FaceMakerCheese",
                "Part::FaceMakerSimple",
                "Part::FaceMakerUnified",
            };
            for (size_t i = 0; i < std::size(faceMaker); i++) {
                try {
                    back = makeTopoShape(false).makeElementFace(backwires, nullptr, faceMaker[i]);
                    break;
                }
                catch (...) {
                    if (i == std::size(faceMaker) - 1) {
                        throw;
                    }
                    continue;
                }
            }
        }

        if (!front.isNull() || !back.isNull()) {
            BRepBuilderAPI_Sewing sewer;
            sewer.SetTolerance(Precision::Confusion());
            if (!front.isNull()) {
                sewer.Add(front.getShape());
            }
            if (!back.isNull()) {
                sewer.Add(back.getShape());
            }
            for (auto& s : shells) {
                sewer.Add(s.getShape());
            }

            sewer.Perform();

            if (!front.isNull()) {
                shells.push_back(front);
            }
            if (!back.isNull()) {
                shells.push_back(back);
            }
            // equivalent of the removed: result = result.makeElementShape(sewer,shells);
            result = result.makeShapeWithElementMap(
                sewer.SewedShape(),
                Part::MapperSewing(sewer),
                shells,
                Part::OpCodes::Sewing
            );
        }

        if (!result.countSubShapes(TopAbs_SHELL)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Loft: Failed to create shell")
            );
        }
        shapes = result.getSubTopoShapes(TopAbs_SHELL);

        for (auto& s : shapes) {
            // build the solid
            s = s.makeElementSolid();
            BRepClass3d_SolidClassifier SC(s.getShape());
            SC.PerformInfinitePoint(Precision::Confusion());
            if (SC.State() == TopAbs_IN) {
                s.setShape(s.getShape().Reversed(), false);
            }
        }

        AddSubShape.setValue(result.makeElementCompound(
            shapes,
            nullptr,
            Part::TopoShape::SingleShapeCompoundCreationPolicy::returnShape
        ));

        if (shapes.size() > 1) {
            result.makeElementFuse(shapes);
        }
        else {
            result = shapes.front();
        }

        if (base.isNull()) {
            // A Remove or an Intersect with nothing before it makes nothing, never its tool as
            // material, as an Extrude's (ops#640 rank 20, H3): FeatureAddSub::recompute fails it,
            // "Nothing to cut"
            if (getAddSubType() == FeatureAddSub::Type::Subtractive) {
                this->rawShape = TopoShape();  // a Refine-only change recomputes fully
                Shape.setValue(TopoShape());
                return App::DocumentObject::StdReturn;
            }
            if (!isSingleSolidRuleSatisfied(result.getShape())) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Result has multiple solids: enable 'Allow Compound' in the active body."
                ));
            }
            Shape.setValue(getSolid(result));
            return App::DocumentObject::StdReturn;
        }

        result.Tag = -getID();

        TopoShape boolOp = makeTopoShape();
        try {
            boolOp.makeElementBoolean(
                getBooleanMaker(),
                {base, result},
                nullptr,
                FuzzyTolerance.getValue(),
                Part::ElementMapPolicy::Propagate,
                booleanInputCheck(),
                &booleanInputsValid
            );
        }
        catch (Standard_Failure&) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Failed to perform boolean operation")
            );
        }
        // An Intersect that shares no volume with its base leaves the base as it was, healthy, with
        // Onshape's info, as a Revolve's and an Extrude's (hands-on R7, ops#640 rank 20, H3)
        if (getBooleanOperation() == BooleanOperation::Common
            && (boolOp.isNull() || !boolOp.hasSubShape(TopAbs_SOLID))) {
            if (auto doc = getDocument(); doc && !SiblingOf.getValue()) {
                static const std::string text = "Selected tools and targets do not intersect";
                const char* previous = doc->getWarningDescription(this);
                doc->setWarning(
                    this,
                    previous && *previous ? std::string(previous) + "\n" + text : text
                );
            }
            this->rawShape = TopoShape();
            Shape.setValue(base);
            return App::DocumentObject::StdReturn;
        }
        TopoShape solid = getSolid(boolOp);
        // lets check if the result is a solid
        if (solid.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is not a solid")
            );
        }
        // store shape before refinement
        this->rawShape = boolOp;
        boolOp = refineShapeIfActive(boolOp);
        if (!isSingleSolidRuleSatisfied(boolOp.getShape())) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Result has multiple solids: enable 'Allow Compound' in the active body."
            ));
        }
        boolOp = getSolid(boolOp);
        Shape.setValue(boolOp);
        return App::DocumentObject::StdReturn;
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (...) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Loft: A fatal error occurred when making the loft")
        );
    }
}

PROPERTY_SOURCE(PartDesign::AdditiveLoft, PartDesign::Loft)
AdditiveLoft::AdditiveLoft()
{
    defineAdditive();
    // New / Add / Remove / Intersect on one Loft (FreeCAD-CH ops#640 rank 20)
    allowAllOperations();
}

PROPERTY_SOURCE(PartDesign::SubtractiveLoft, PartDesign::Loft)
SubtractiveLoft::SubtractiveLoft()
{
    defineSubtractive();
    allowAllOperations();
}

void Loft::handleChangedPropertyType(Base::XMLReader& reader, const char* TypeName, App::Property* prop)
{
    // property Sections had the App::PropertyLinkList and was changed to App::PropertyXLinkSubList
    if (prop == &Sections && strcmp(TypeName, "App::PropertyLinkList") == 0) {
        Sections.upgrade(reader, TypeName);
    }
    else {
        ProfileBased::handleChangedPropertyType(reader, TypeName, prop);
    }
}
