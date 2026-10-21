// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
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
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <numbers>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include <Bnd_Box.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepTools.hxx>
#include <BRepTopAdaptor_FClass2d.hxx>
#include <ElCLib.hxx>
#include <GCE2d_MakeSegment.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_Curve.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <Geom_Surface.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Geom2dAPI_InterCurveCurve.hxx>
#include <Geom2dAPI_ProjectPointOnCurve.hxx>
#include <Geom2dConvert.hxx>
#include <Geom2dInt_GInter.hxx>
#include <GeomAPI.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GeomConvert.hxx>
#include <GProp_GProps.hxx>
#include <IntRes2d_IntersectionPoint.hxx>
#include <gp_Ax3.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <gp_Vec2d.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>

#include <fmt/format.h>

#include <Base/Exception.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeMapper.h>

#include "FirstContactConstruction.h"

namespace PartDesign::FirstContact
{

namespace
{

Base::RuntimeError refused(const std::string& why)
{
    return Base::RuntimeError("Could not build the revolution where first contact jumps: " + why);
}

// A cell's piece that didn't check: why, and where
struct CellRefusal
{
    std::size_t cell;
    std::string why;
};

// Where an edge of the face crosses its silhouette (section 15.10): the edge's image flips side
// there, tangent to the silhouette's image, whose wall ends there. The three walls meet in one
// junction: the arm pushed to the silhouette wall's side continues it, and the other arm, pushed
// the other way, is cut where it crosses the silhouette wall a little way on. Indices are into the
// construction's walls; `AtEnd` says which end of a wall's curve lies at the flip.
struct Junction
{
    std::size_t silhouette = 0;
    bool silhouetteAtEnd = false;
    std::size_t along = 0;
    bool alongAtEnd = false;
    std::size_t across = 0;
    bool acrossAtEnd = false;
    // The distance between the silhouette wall's end and the flip: the edge's curve and the
    // surface agree only within the edge's tolerance
    double gap = 0.0;
};

// The curve of a piece over its range, as a B-spline
Handle(Geom2d_BSplineCurve) asBSpline(const JumpPiece& piece)
{
    Handle(Geom2d_Curve) trimmed = new Geom2d_TrimmedCurve(piece.curve, piece.first, piece.last);
    Handle(Geom2d_BSplineCurve) spline = Geom2dConvert::CurveToBSplineCurve(trimmed);
    if (spline.IsNull()) {
        throw refused("a jump curve isn't a B-spline");
    }
    if (spline->IsPeriodic()) {
        spline->SetNotPeriodic();
    }
    return spline;
}

// The unit normal of a curve at t, towards `side` (+1: the left of its direction)
gp_Vec2d normalTowards(const Handle(Geom2d_Curve)& curve, double t, int side)
{
    gp_Pnt2d point;
    gp_Vec2d along;
    gp_Vec2d second;
    curve->D2(t, point, along, second);
    if (along.Magnitude() <= gp::Resolution()) {
        // A stationary point: the direction is the second derivative's
        along = second;
    }
    if (along.Magnitude() <= gp::Resolution()) {
        throw refused("a jump curve has no direction");
    }
    along.Normalize();
    return gp_Vec2d(-along.Y(), along.X()) * side;
}

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

double largestEdgeTolerance(const TopoDS_Shape& shape)
{
    double largest = 0.0;
    for (TopExp_Explorer edges(shape, TopAbs_EDGE); edges.More(); edges.Next()) {
        largest = std::max(largest, BRep_Tool::Tolerance(TopoDS::Edge(edges.Current())));
    }
    return largest;
}

double area(const TopoDS_Shape& shape)
{
    GProp_GProps properties;
    BRepGProp::SurfaceProperties(shape, properties);
    return properties.Mass();
}

double perimeter(const TopoDS_Shape& shape)
{
    GProp_GProps properties;
    BRepGProp::LinearProperties(shape, properties);
    return properties.Mass();
}

// A solid's volume by Gauss-Kronrod integration over the surfaces' spans, to 1e-7, and the error
// reached. The adaptive integration of VolumeProperties() at 1e-6 (solidVolume() in
// FeatureRevolved.cpp) was 3e-4 off on the folds' pieces (26.3629 for 26.3494) and gave the fuse
// 2.6e-4 less than its pieces; Gauss-Kronrod agreed with them to 1e-8 and with first contact
// integrated from the wall's curve to 4e-7.
std::pair<double, double> volume(const TopoDS_Shape& shape)
{
    GProp_GProps properties;
    const double relativeError
        = BRepGProp::VolumePropertiesGK(shape, properties, 1e-7, Standard_True, Standard_True);
    return {properties.Mass(), std::fabs(relativeError * properties.Mass())};
}

// The largest distance of a shape's bounding box's corners from the axis
double largestRadius(const TopoDS_Shape& shape, const gp_Ax1& axis)
{
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    if (box.IsVoid()) {
        return 0.0;
    }
    const gp_Lin line(axis);
    double largest = 0.0;
    const gp_Pnt low = box.CornerMin();
    const gp_Pnt high = box.CornerMax();
    for (const double x : {low.X(), high.X()}) {
        for (const double y : {low.Y(), high.Y()}) {
            for (const double z : {low.Z(), high.Z()}) {
                largest = std::max(largest, line.Distance(gp_Pnt(x, y, z)));
            }
        }
    }
    return largest;
}

// A B-spline's net in homogeneous coordinates (w x, w y, w z, w), with its flat knots
struct Net
{
    std::vector<std::array<double, 4>> poles;
    std::vector<double> knots;
    int degree = 0;
};

// The derivative's net: p (H[i+1] - H[i]) / (k[i+p+1] - k[i+1]), of degree p - 1
Net differenced(const Net& net)
{
    Net out;
    if (net.degree == 0) {
        return out;
    }
    out.degree = net.degree - 1;
    out.knots.assign(net.knots.begin() + 1, net.knots.end() - 1);
    for (std::size_t i = 0; i + 1 < net.poles.size(); ++i) {
        const double span = net.knots[i + net.degree + 1] - net.knots[i + 1];
        std::array<double, 4> pole {};
        if (span > 0.0) {
            for (int k = 0; k < 4; ++k) {
                pole[k] = net.degree * (net.poles[i + 1][k] - net.poles[i][k]) / span;
            }
        }
        out.poles.push_back(pole);
    }
    return out;
}

// Bounds of |S'| and |S''| over a B-spline with the given poles, weights and flat knots. The
// derivatives of N = w (S - O) and of w are B-splines whose values lie in their nets' hulls;
// S' = (N' - w' (S - O)) / w and S'' = (N'' - 2 w' S' - w'' (S - O)) / w, with O the poles' centre,
// |S - O| at most the farthest pole and w at least the smallest weight.
std::pair<double, double> derivativeBounds(
    const std::vector<std::array<double, 3>>& points,
    const std::vector<double>& weights,
    const std::vector<double>& knots,
    int degree
)
{
    std::array<double, 3> centre {};
    for (const auto& point : points) {
        for (int k = 0; k < 3; ++k) {
            centre[k] += point[k] / static_cast<double>(points.size());
        }
    }
    Net net;
    net.degree = degree;
    net.knots = knots;
    double reach = 0.0;
    double lightest = std::numeric_limits<double>::max();
    for (std::size_t i = 0; i < points.size(); ++i) {
        const double w = weights.empty() ? 1.0 : weights[i];
        const std::array<double, 3> d {points[i][0] - centre[0], points[i][1] - centre[1], points[i][2] - centre[2]};
        net.poles.push_back({w * d[0], w * d[1], w * d[2], w});
        reach = std::max(reach, std::sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]));
        lightest = std::min(lightest, w);
    }
    auto largest = [](const Net& of) {
        double space = 0.0;
        double weight = 0.0;
        for (const auto& pole : of.poles) {
            space = std::max(space, std::sqrt(pole[0] * pole[0] + pole[1] * pole[1] + pole[2] * pole[2]));
            weight = std::max(weight, std::fabs(pole[3]));
        }
        return std::make_pair(space, weight);
    };
    const Net first = differenced(net);
    const auto [n1, w1] = largest(first);
    const auto [n2, w2] = largest(differenced(first));
    const double speed = (n1 + w1 * reach) / lightest;
    return {speed, (n2 + 2.0 * w1 * speed + w2 * reach) / lightest};
}

std::pair<double, double> derivativeBounds(Handle(Geom_BSplineCurve) curve)
{
    curve = Handle(Geom_BSplineCurve)::DownCast(curve->Copy());
    curve->SetNotPeriodic();
    std::vector<std::array<double, 3>> points;
    std::vector<double> weights;
    for (int i = 1; i <= curve->NbPoles(); ++i) {
        const gp_Pnt pole = curve->Pole(i);
        points.push_back({pole.X(), pole.Y(), pole.Z()});
        if (curve->IsRational()) {
            weights.push_back(curve->Weight(i));
        }
    }
    const TColStd_Array1OfReal& sequence = curve->KnotSequence();
    return derivativeBounds(points, weights, {sequence.begin(), sequence.end()}, curve->Degree());
}

std::pair<double, double> derivativeBounds(Handle(Geom2d_BSplineCurve) curve)
{
    curve = Handle(Geom2d_BSplineCurve)::DownCast(curve->Copy());
    curve->SetNotPeriodic();
    std::vector<std::array<double, 3>> points;
    std::vector<double> weights;
    for (int i = 1; i <= curve->NbPoles(); ++i) {
        const gp_Pnt2d pole = curve->Pole(i);
        points.push_back({pole.X(), pole.Y(), 0.0});
        if (curve->IsRational()) {
            weights.push_back(curve->Weight(i));
        }
    }
    const TColStd_Array1OfReal& sequence = curve->KnotSequence();
    return derivativeBounds(points, weights, {sequence.begin(), sequence.end()}, curve->Degree());
}

// One cell swept up to the face: the cell revolved a sliver short of a whole turn, split by the
// face, and the solid at its start cap (as sweepUpToFace() in FeatureRevolved.cpp). C1: exactly one
// such solid, keeping the whole cap. `band` is that of the walls on the cell's boundary; `step` is
// lostSheet()'s. Returns the solid, or why it refuses.
std::pair<TopoDS_Shape, std::string> sweepCell(
    const TopoDS_Face& cell,
    const TopoDS_Face& face,
    const gp_Ax1& axis,
    double sliver,
    const Band& band,
    double step,
    double tolerance
)
{
    try {
        BRepPrimAPI_MakeRevol turn(cell, axis, 2.0 * std::numbers::pi - sliver);
        if (!turn.IsDone()) {
            return {{}, "the cell's turn failed"};
        }
        BRepAlgoAPI_Splitter splitter;
        TopTools_ListOfShape arguments;
        arguments.Append(turn.Shape());
        TopTools_ListOfShape tools;
        tools.Append(face);
        splitter.SetArguments(arguments);
        splitter.SetTools(tools);
        splitter.Build();
        if (!splitter.IsDone()) {
            return {{}, "the face's split of the cell's turn failed"};
        }
        const TopTools_IndexedMapOfShape start = Part::UpToSplitMapper::piecesOf(splitter, turn.FirstShape());
        const TopTools_IndexedMapOfShape end = Part::UpToSplitMapper::piecesOf(splitter, turn.LastShape());
        std::vector<TopoDS_Shape> kept;
        double cap = 0.0;
        for (TopExp_Explorer solids(splitter.Shape(), TopAbs_SOLID); solids.More(); solids.Next()) {
            bool atStart = false;
            bool atEnd = false;
            double here = 0.0;
            for (TopExp_Explorer faces(solids.Current(), TopAbs_FACE); faces.More(); faces.Next()) {
                if (start.Contains(faces.Current())) {
                    atStart = true;
                    here += area(faces.Current());
                }
                atEnd = atEnd || end.Contains(faces.Current());
            }
            if (atStart && atEnd) {
                return {{}, "part of the cell goes all the way round"};
            }
            if (atStart) {
                kept.push_back(solids.Current());
                cap += here;
            }
        }
        if (kept.size() != 1) {
            return {{}, fmt::format("C1: {} solids at the cell's start", kept.size())};
        }
        // C2, a sheet of the face lost in the split
        const TopTools_IndexedMapOfShape faceParts = Part::UpToSplitMapper::piecesOf(splitter, face);
        TopTools_IndexedMapOfShape sections;
        for (const TopoDS_Shape& edge : splitter.SectionEdges()) {
            sections.Add(edge);
        }
        if (const std::string lost = lostSheet(kept.front(), face, sections, faceParts, band, step, tolerance);
            !lost.empty()) {
            return {{}, lost};
        }
        const double cellArea = area(cell);
        const double allowed = 1e-9 * cellArea + perimeter(cell) * std::max(largestTolerance(cell), Precision::Confusion());
        if (std::fabs(cap - cellArea) > allowed) {
            return {{}, fmt::format("C1: the piece's start cap is {:.9g} of the cell's {:.9g}", cap, cellArea)};
        }
        return {kept.front(), {}};
    }
    catch (const Standard_Failure& failure) {
        return {{}, std::string("the cell's sweep failed: ") + failure.GetMessageString()};
    }
}

}  // namespace

// Every section edge in the piece must bound a piece of the face there, unless it lies in a
// wall's band, where the split may drop a flap that bounds nothing (the hook at the first push).
// On q18's fold trimmed by a slanted plane (TrimmedFold), the split cut the turn's faces along
// the face's middle leg but merged the leg's own piece with the face outside the turn, near a
// vertex of tolerance 2e-5 at the wall junction: the piece ran on to the next leg, +0.03 in
// volume, with every other check passing (ops#293 D2 session 5). The lost sheet crossed the
// profile's own edge there, out of any band. In a cell bounded only by walls every section edge
// is in a band, so the face's material through an unexplained edge is followed: a dropped flap
// leaves the piece before its image leaves the band (the fold turns the face back, or the edge
// ends it), a lost sheet runs on into the piece.
std::string lostSheet(
    const TopoDS_Shape& piece,
    const TopoDS_Face& face,
    const TopTools_IndexedMapOfShape& sections,
    const TopTools_IndexedMapOfShape& faceParts,
    const Band& band,
    double step,
    double tolerance
)
{
    auto refusal = [](const char* what, const gp_Pnt& point) {
        return fmt::format("C2: {} (near ({:.4g}, {:.4g}, {:.4g}))", what, point.X(), point.Y(), point.Z());
    };
    // The nearest point of the face, with the face's normal there; nothing when the point is off
    // the face by more than half a step, or beyond its boundary
    const Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    double uLow = 0.0;
    double uHigh = 0.0;
    double vLow = 0.0;
    double vHigh = 0.0;
    BRepTools::UVBounds(face, uLow, uHigh, vLow, vHigh);
    GeomAPI_ProjectPointOnSurf projection;
    projection.Init(surface, uLow, uHigh, vLow, vHigh, Precision::Confusion());
    BRepTopAdaptor_FClass2d inFace(face, Precision::PConfusion());
    auto onFace = [&](const gp_Pnt& point) -> std::optional<std::pair<gp_Pnt, gp_Dir>> {
        projection.Perform(point);
        if (!projection.IsDone() || projection.NbPoints() < 1 || projection.LowerDistance() > step / 2.0) {
            return std::nullopt;
        }
        double u = 0.0;
        double v = 0.0;
        projection.LowerDistanceParameters(u, v);
        if (inFace.Perform(gp_Pnt2d(u, v)) == TopAbs_OUT) {
            return std::nullopt;
        }
        gp_Pnt at;
        gp_Vec du;
        gp_Vec dv;
        surface->D1(u, v, at, du, dv);
        const gp_Vec normal = du.Crossed(dv);
        if (normal.Magnitude() <= gp::Resolution()) {
            return std::nullopt;
        }
        return std::make_pair(at, gp_Dir(normal));
    };
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(piece, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    BRepClass3d_SolidClassifier inPiece(piece);
    for (int k = 1; k <= edgeFaces.Extent(); ++k) {
        const TopoDS_Edge& edge = TopoDS::Edge(edgeFaces.FindKey(k));
        if (!sections.Contains(edge) || BRep_Tool::Degenerated(edge)) {
            continue;
        }
        bool bounded = false;
        for (const TopoDS_Shape& next : edgeFaces.FindFromIndex(k)) {
            bounded = bounded || faceParts.Contains(next);
        }
        if (bounded) {
            continue;
        }
        if (const auto out = band.outside(edge)) {
            return refusal("the face crosses the cell's piece without splitting it", *out);
        }
        BRepAdaptor_Curve along(edge);
        // The face's material across the edge, both ways from its middle
        gp_Pnt middle;
        gp_Vec tangent;
        along.D1((along.FirstParameter() + along.LastParameter()) / 2.0, middle, tangent);
        const auto start = onFace(middle);
        if (!start || tangent.Magnitude() <= gp::Resolution()) {
            return refusal("the face can't be followed across the cell's piece", middle);
        }
        const gp_Vec across = gp_Vec(start->second).Crossed(tangent).Normalized();
        for (const double sign : {1.0, -1.0}) {
            gp_Pnt at = start->first;
            gp_Vec direction = across * sign;
            constexpr int farthest = 256;
            int count = 0;
            for (; count < farthest; ++count) {
                const auto next = onFace(at.Translated(direction * step));
                if (!next) {
                    // The face ends: the material through the edge stays in the band
                    break;
                }
                direction = gp_Vec(at, next->first);
                if (direction.Magnitude() <= step / 4.0) {
                    break;
                }
                direction.Normalize();
                at = next->first;
                if (band.contains(at)) {
                    continue;
                }
                inPiece.Perform(at, tolerance);
                if (inPiece.State() == TopAbs_IN) {
                    return refusal("a sheet of the face runs through the cell's piece unsplit", at);
                }
                break;
            }
            if (count == farthest) {
                return refusal("the face stays in a wall's band too far to check", at);
            }
        }
    }
    return {};
}

Band::Band(const gp_Ax2& frame)
    : frame(frame)
{}

gp_Pnt2d Band::image(const gp_Pnt& point) const
{
    const gp_Vec offset(frame.Location(), point);
    const gp_Vec along(frame.YDirection());
    const double height = offset.Dot(along);
    return {(offset - along * height).Magnitude(), height};
}

void Band::add(const Handle(Geom2d_Curve)& curve, double width)
{
    const Handle(Geom2d_BSplineCurve) spline = Geom2dConvert::CurveToBSplineCurve(curve);
    if (spline.IsNull()) {
        throw refused("a wall's curve can't be bounded");
    }
    parts.push_back({spline, width, derivativeBounds(spline).second});
}

namespace
{

// The parameter of the part's nearest point to `point`, and the distance
std::pair<double, double> nearest(const Handle(Geom2d_BSplineCurve)& curve, const gp_Pnt2d& point)
{
    std::pair<double, double> best {curve->FirstParameter(), point.Distance(curve->StartPoint())};
    if (const double last = point.Distance(curve->EndPoint()); last < best.second) {
        best = {curve->LastParameter(), last};
    }
    Geom2dAPI_ProjectPointOnCurve projection(point, curve);
    if (projection.NbPoints() > 0 && projection.LowerDistance() < best.second) {
        best = {projection.LowerDistanceParameter(), projection.LowerDistance()};
    }
    return best;
}

}  // namespace

bool Band::contains(const gp_Pnt& point) const
{
    const gp_Pnt2d at = image(point);
    return std::ranges::any_of(parts, [&](const Part& part) {
        return nearest(part.curve, at).second <= part.width;
    });
}

std::optional<gp_Pnt> Band::outside(const TopoDS_Edge& edge) const
{
    const gp_Pnt start = BRep_Tool::Pnt(TopExp::FirstVertex(edge));
    Handle(Geom_BSplineCurve) curve;
    try {
        double first = 0.0;
        double last = 0.0;
        const Handle(Geom_Curve) carrier = BRep_Tool::Curve(edge, first, last);
        if (carrier.IsNull() || last - first <= Precision::PConfusion()) {
            return start;
        }
        curve = GeomConvert::CurveToBSplineCurve(new Geom_TrimmedCurve(carrier, first, last));
    }
    catch (const Standard_Failure&) {
        return start;
    }
    if (curve.IsNull()) {
        return start;
    }
    const auto [speed, bend] = derivativeBounds(curve);
    const double tolerance = BRep_Tool::Tolerance(edge);
    struct Sample
    {
        double t = 0.0;
        gp_Pnt point;
        double radius = 0.0;
        // Per part: the nearest point's parameter and the distance
        std::vector<std::pair<double, double>> near;
    };
    // A sample whose image, widened by the tolerance, is in no part's band can't be certified
    auto sample = [&](double t) -> std::optional<Sample> {
        Sample here {t, curve->Value(t)};
        const gp_Pnt2d at = image(here.point);
        here.radius = at.X();
        bool held = false;
        for (const Part& part : parts) {
            here.near.push_back(nearest(part.curve, at));
            held = held || here.near.back().second + tolerance < part.width;
        }
        if (!held) {
            return std::nullopt;
        }
        return here;
    };
    const double first = curve->FirstParameter();
    const double last = curve->LastParameter();
    constexpr int initial = 8;
    std::vector<Sample> samples;
    for (int k = 0; k <= initial; ++k) {
        const double t = first + (last - first) * k / initial;
        auto here = sample(t);
        if (!here) {
            return curve->Value(t);
        }
        samples.push_back(std::move(*here));
    }
    std::vector<std::pair<Sample, Sample>> open;
    for (int k = initial; k > 0; --k) {
        open.emplace_back(samples[k - 1], samples[k]);
    }
    // Halving stops at a floor, and the count at a budget: past either, the edge isn't certified
    const double floor = (last - first) * 1e-9;
    constexpr int budget = 100000;
    int count = 0;
    while (!open.empty()) {
        auto [low, high] = std::move(open.back());
        open.pop_back();
        const double dt = high.t - low.t;
        // The radius is 1-Lipschitz along the curve
        const double radius = std::min(low.radius, high.radius) - speed * dt / 2.0;
        if (radius > 0.0) {
            const double turn = bend + speed * speed / radius;
            bool held = false;
            for (std::size_t p = 0; p < parts.size() && !held; ++p) {
                const double du = high.near[p].first - low.near[p].first;
                held = std::max(low.near[p].second, high.near[p].second)
                        + (turn * dt * dt + parts[p].bend * du * du) / 8.0 + tolerance
                    <= parts[p].width;
            }
            if (held) {
                continue;
            }
        }
        if (dt <= floor || ++count > budget) {
            return low.point;
        }
        auto middle = sample(low.t + dt / 2.0);
        if (!middle) {
            return curve->Value(low.t + dt / 2.0);
        }
        open.emplace_back(*middle, std::move(high));
        open.emplace_back(std::move(low), std::move(*middle));
    }
    return std::nullopt;
}

Wall pushedWall(const JumpTrace& trace, std::size_t index, double push)
{
    const JumpPiece& piece = trace.pieces.at(index);
    if (piece.curve.IsNull() || piece.side == 0) {
        throw refused("a jump curve has no side");
    }
    const Handle(Geom2d_BSplineCurve) original = asBSpline(piece);
    // Each pole moved along the normal at its Greville abscissa: within O(push x the normal's turn
    // over the pole's span) of the offset curve, so the spans are halved until that is within a
    // tenth of the push at every span's samples
    for (int refinement = 0; refinement < 6; ++refinement) {
        Handle(Geom2d_BSplineCurve) moved = Handle(Geom2d_BSplineCurve)::DownCast(original->Copy());
        const int degree = original->Degree();
        const int poles = original->NbPoles();
        TColStd_Array1OfReal knots(1, poles + degree + 1);
        original->KnotSequence(knots);
        for (int i = 1; i <= poles; ++i) {
            double greville = 0.0;
            for (int k = i + 1; k <= i + degree; ++k) {
                greville += knots(k);
            }
            greville /= degree;
            moved->SetPole(i, original->Pole(i).Translated(normalTowards(original, greville, piece.side) * push));
        }
        bool holds = true;
        for (int k = 1; k < original->NbKnots() && holds; ++k) {
            const double low = original->Knot(k);
            const double high = original->Knot(k + 1);
            for (int s = 0; s <= 8 && holds; ++s) {
                const double t = low + (high - low) * s / 8;
                const gp_Pnt2d expected
                    = original->Value(t).Translated(normalTowards(original, t, piece.side) * push);
                holds = moved->Value(t).Distance(expected) <= 0.1 * push;
            }
        }
        if (holds) {
            return {index, push, moved};
        }
        if (original->NbKnots() > 4096) {
            break;
        }
        TColStd_Array1OfReal middles(1, original->NbKnots() - 1);
        TColStd_Array1OfInteger once(1, original->NbKnots() - 1);
        for (int k = 1; k < original->NbKnots(); ++k) {
            middles(k) = (original->Knot(k) + original->Knot(k + 1)) / 2.0;
            once(k) = 1;
        }
        original->InsertKnots(middles, once);
    }
    throw refused("a jump curve can't be pushed within a tenth of its push");
}

FirstContactSolid constructFirstContact(
    const TopoDS_Face& face,
    const TopoDS_Face& profile,
    const gp_Ax1& axis,
    double tolerance
)
{
    // The tracer's fit stays within half the first push, so the pushed wall lies on the side of
    // the earlier first contact by at least half of it
    const JumpTrace trace = traceJumps(face, profile, axis, tolerance, firstPush / 2.0);
    std::vector<std::size_t> needed;
    for (std::size_t k = 0; k < trace.pieces.size(); ++k) {
        if (trace.pieces[k].meetsProfile && trace.pieces[k].jumps) {
            needed.push_back(k);
        }
    }
    if (needed.empty()) {
        throw refused("no jump was traced in the profile");
    }

    // The walls go in the profile's own plane, with the frame's axes: x away from the axis, y
    // along it
    const gp_Pln profilePlane = BRepAdaptor_Surface(profile).Plane();
    gp_Dir normal = profilePlane.Axis().Direction();
    if (normal.Dot(trace.frame.Direction()) < 0.0) {
        normal.Reverse();
    }
    const gp_Pnt location = trace.frame.Location();
    const double off = gp_Vec(profilePlane.Location(), location).Dot(gp_Vec(normal));
    const gp_Pln wallPlane(gp_Ax3(location.Translated(gp_Vec(normal) * -off), normal, trace.frame.XDirection()));

    Bnd_Box profileBox;
    BRepBndLib::Add(profile, profileBox);
    const double size = std::sqrt(profileBox.SquareExtent());
    // A wall's free end is carried this far along its tangent, out of the profile: the tracer
    // follows curves up to size / 8 past the profile's image box
    const double extension = 4.0 * size;
    const double cap = 1e-4 * size;
    const double radius = largestRadius(profile, axis);
    const double sliver = radius > 0.0 ? std::clamp(tolerance / radius, 1e-4, 1e-2) : 1e-4;

    // A wall whose next piece continues its curve across a flip of the side
    auto flipsToNext = [&](std::size_t w) {
        return w + 1 < needed.size() && needed[w] + 1 == needed[w + 1]
            && trace.pieces[needed[w + 1]].continuesPrevious;
    };

    // The junctions: a flip of an edge's image at the end of a silhouette wall. Found on the
    // unpushed curves, so they hold at every push. The silhouette wall's end is the chain's
    // crossing of the face's boundary, the flip the edge's own: within the tracer's resolution
    // of each other when they are the same point.
    std::vector<Handle(Geom2d_BSplineCurve)> unpushed;
    for (std::size_t w = 0; w < needed.size(); ++w) {
        unpushed.push_back(asBSpline(trace.pieces[needed[w]]));
    }
    auto normalAt = [&](std::size_t w, bool atEnd) {
        const Handle(Geom2d_BSplineCurve)& curve = unpushed[w];
        return normalTowards(
            curve,
            atEnd ? curve->LastParameter() : curve->FirstParameter(),
            trace.pieces[needed[w]].side
        );
    };
    std::vector<Junction> junctions;
    // Which ends of each wall lie in a junction: [at its start, at its end]
    std::vector<std::array<bool, 2>> joined(needed.size(), {false, false});
    const double resolution = size / 1024.0;
    for (std::size_t w = 0; w < needed.size(); ++w) {
        if (!flipsToNext(w) || trace.pieces[needed[w]].source != JumpSource::Edge) {
            // A cusp of the silhouette's image keeps its connector
            continue;
        }
        const gp_Pnt2d flip = unpushed[w]->EndPoint();
        Junction junction;
        junction.gap = resolution;
        bool found = false;
        for (std::size_t s = 0; s < needed.size(); ++s) {
            if (trace.pieces[needed[s]].source != JumpSource::Silhouette) {
                continue;
            }
            for (const bool atEnd : {false, true}) {
                const double gap = (atEnd ? unpushed[s]->EndPoint() : unpushed[s]->StartPoint()).Distance(flip);
                if (gap < junction.gap) {
                    junction.gap = gap;
                    junction.silhouette = s;
                    junction.silhouetteAtEnd = atEnd;
                    found = true;
                }
            }
        }
        if (!found) {
            continue;
        }
        // The arm pushed the silhouette wall's way continues it; the flip turns the other arm's
        // push the other way
        const gp_Vec2d normal = normalAt(junction.silhouette, junction.silhouetteAtEnd);
        const bool firstAlong = normal.Dot(normalAt(w, true)) > 0.0;
        if (firstAlong == (normal.Dot(normalAt(w + 1, false)) > 0.0)) {
            continue;
        }
        junction.along = firstAlong ? w : w + 1;
        junction.alongAtEnd = firstAlong;
        junction.across = firstAlong ? w + 1 : w;
        junction.acrossAtEnd = !firstAlong;
        joined[junction.silhouette][junction.silhouetteAtEnd ? 1 : 0] = true;
        joined[junction.along][junction.alongAtEnd ? 1 : 0] = true;
        joined[junction.across][junction.acrossAtEnd ? 1 : 0] = true;
        junctions.push_back(junction);
    }

    // Walls meeting in a junction share one push, raised together. The first push covers the
    // junction's gap twice over: the silhouette wall's end is moved onto the arm's, so its band
    // (2 pushes) must hold the flap along it, up to the push plus the gap wide.
    std::vector<std::size_t> group(needed.size());
    for (std::size_t w = 0; w < needed.size(); ++w) {
        group[w] = w;
    }
    auto merge = [&](std::size_t a, std::size_t b) {
        const std::size_t from = std::max(group[a], group[b]);
        const std::size_t to = std::min(group[a], group[b]);
        for (std::size_t& g : group) {
            g = g == from ? to : g;
        }
    };
    std::vector<double> pushes(needed.size(), firstPush);
    for (const Junction& junction : junctions) {
        merge(junction.silhouette, junction.along);
        merge(junction.silhouette, junction.across);
        for (const std::size_t w : {junction.silhouette, junction.along, junction.across}) {
            pushes[w] = std::max(pushes[w], 2.0 * junction.gap);
        }
    }
    for (std::size_t w = 0; w < needed.size(); ++w) {
        for (std::size_t v = 0; v < needed.size(); ++v) {
            if (group[v] == group[w]) {
                pushes[w] = std::max(pushes[w], pushes[v]);
            }
        }
    }
    std::vector<int> raised(needed.size(), 0);
    // The largest edge tolerance of the face's section with the unpushed wall turned about the axis
    auto sectionTolerance = [&](std::size_t w) {
        try {
            const TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(GeomAPI::To3d(unpushed[w], wallPlane)).Edge();
            BRepPrimAPI_MakeRevol turn(edge, axis, 2.0 * std::numbers::pi);
            BRepAlgoAPI_Section section(face, turn.Shape());
            return section.IsDone() ? largestEdgeTolerance(section.Shape()) : 0.0;
        }
        catch (const Standard_Failure&) {
            return 0.0;
        }
    };
    // A wall's group pushed a level farther: the first level is max(10 x the first push, 4 x the
    // group's section tolerance), the next ten times more; never below where the group stands
    auto raise = [&](std::size_t w) {
        double push = 0.0;
        for (std::size_t v = 0; v < needed.size(); ++v) {
            if (group[v] != group[w]) {
                continue;
            }
            push = std::max(
                push,
                raised[v] == 0 ? std::max(10.0 * firstPush, 4.0 * sectionTolerance(v)) : 10.0 * pushes[v]
            );
        }
        for (std::size_t v = 0; v < needed.size(); ++v) {
            if (group[v] == group[w]) {
                pushes[v] = std::max(pushes[v], push);
                ++raised[v];
            }
        }
    };

    FirstContactSolid solid;
    for (int build = 1;; ++build) {
        for (std::size_t w = 0; w < needed.size(); ++w) {
            if (pushes[w] > cap) {
                throw refused(fmt::format("a wall would be pushed {:.3g}, over 1e-4 of the profile's size", pushes[w]));
            }
        }
        solid = FirstContactSolid();
        solid.builds = build;
        for (std::size_t w = 0; w < needed.size(); ++w) {
            solid.walls.push_back(pushedWall(trace, needed[w], pushes[w]));
        }
        // The junctions: the silhouette wall's end moved onto the arm's that continues it (the
        // two are tangent there, pushed the same way: within the gap of each other), the other
        // arm cut where it crosses the silhouette wall, its new end on the wall
        for (const Junction& junction : junctions) {
            Handle(Geom2d_BSplineCurve)& silhouette = solid.walls[junction.silhouette].curve;
            const Handle(Geom2d_BSplineCurve)& along = solid.walls[junction.along].curve;
            Handle(Geom2d_BSplineCurve)& across = solid.walls[junction.across].curve;
            silhouette->SetPole(
                junction.silhouetteAtEnd ? silhouette->NbPoles() : 1,
                junction.alongAtEnd ? along->EndPoint() : along->StartPoint()
            );
            const double flip = junction.acrossAtEnd ? across->LastParameter() : across->FirstParameter();
            Geom2dAPI_InterCurveCurve crossings(across, silhouette, Precision::PConfusion());
            std::optional<double> nearest;
            gp_Pnt2d onWall;
            for (int k = 1; k <= crossings.NbPoints(); ++k) {
                const IntRes2d_IntersectionPoint& crossing = crossings.Intersector().Point(k);
                if (!nearest || std::fabs(crossing.ParamOnFirst() - flip) < std::fabs(*nearest - flip)) {
                    nearest = crossing.ParamOnFirst();
                    onWall = silhouette->Value(crossing.ParamOnSecond());
                }
            }
            if (!nearest) {
                throw refused("an edge's image flips side on the silhouette without crossing its wall");
            }
            Handle(Geom2d_Curve) kept = new Geom2d_TrimmedCurve(
                across,
                junction.acrossAtEnd ? across->FirstParameter() : *nearest,
                junction.acrossAtEnd ? *nearest : across->LastParameter()
            );
            across = Geom2dConvert::CurveToBSplineCurve(kept);
            across->SetPole(junction.acrossAtEnd ? across->NbPoles() : 1, onWall);
        }
        // Each wall's edges: its curve; at a flip outside a junction, a connector to the next
        // piece of its curve (the two lie 2 pushes apart there); its free ends carried out
        std::vector<std::vector<TopoDS_Edge>> wallEdges(needed.size());
        // The same in the frame's coordinates, for the bands
        std::vector<std::vector<Handle(Geom2d_Curve)>> wallParts(needed.size());
        for (std::size_t w = 0; w < needed.size(); ++w) {
            const Handle(Geom2d_BSplineCurve)& curve = solid.walls[w].curve;
            wallEdges[w].push_back(BRepBuilderAPI_MakeEdge(GeomAPI::To3d(curve, wallPlane)).Edge());
            wallParts[w].push_back(curve);
            const bool joinsPrevious = w > 0 && flipsToNext(w - 1);
            auto at = [&](const gp_Pnt2d& point) {
                return ElCLib::To3d(wallPlane.Position().Ax2(), point);
            };
            gp_Pnt2d point;
            gp_Vec2d along;
            if (!joinsPrevious && !joined[w][0]) {
                curve->D1(curve->FirstParameter(), point, along);
                const gp_Pnt2d out = point.Translated(along.Normalized() * -extension);
                wallEdges[w].push_back(BRepBuilderAPI_MakeEdge(at(point), at(out)).Edge());
                wallParts[w].push_back(GCE2d_MakeSegment(out, point).Value());
            }
            if (joined[w][1]) {
                continue;
            }
            if (flipsToNext(w)) {
                const gp_Pnt2d to = solid.walls[w + 1].curve->StartPoint();
                if (curve->EndPoint().Distance(to) > Precision::Confusion()) {
                    wallEdges[w].push_back(BRepBuilderAPI_MakeEdge(at(curve->EndPoint()), at(to)).Edge());
                    wallParts[w].push_back(GCE2d_MakeSegment(curve->EndPoint(), to).Value());
                }
            }
            else {
                curve->D1(curve->LastParameter(), point, along);
                const gp_Pnt2d out = point.Translated(along.Normalized() * extension);
                wallEdges[w].push_back(BRepBuilderAPI_MakeEdge(at(point), at(out)).Edge());
                wallParts[w].push_back(GCE2d_MakeSegment(point, out).Value());
            }
        }

        // The cells, and the walls on each one's boundary (from the split's history)
        BRepAlgoAPI_Splitter splitter;
        TopTools_ListOfShape arguments;
        arguments.Append(profile);
        TopTools_ListOfShape tools;
        for (const auto& edges : wallEdges) {
            for (const TopoDS_Edge& edge : edges) {
                tools.Append(edge);
            }
        }
        splitter.SetArguments(arguments);
        splitter.SetTools(tools);
        splitter.Build();
        if (!splitter.IsDone()) {
            throw refused("the profile's split along the walls failed");
        }
        std::vector<TopTools_IndexedMapOfShape> onWall(needed.size());
        for (std::size_t w = 0; w < needed.size(); ++w) {
            for (const TopoDS_Edge& edge : wallEdges[w]) {
                const TopTools_ListOfShape& split = splitter.Modified(edge);
                if (split.IsEmpty()) {
                    onWall[w].Add(edge);
                }
                for (const TopoDS_Shape& part : split) {
                    onWall[w].Add(part);
                }
            }
        }
        for (TopExp_Explorer faces(splitter.Shape(), TopAbs_FACE); faces.More(); faces.Next()) {
            solid.cells.push_back(TopoDS::Face(faces.Current()));
        }
        constexpr std::size_t largestCells = 32;
        if (solid.cells.size() > largestCells) {
            throw refused(fmt::format("the walls split the profile into {} cells, over 32", solid.cells.size()));
        }

        // Each cell up to the face, checked
        std::vector<TopoDS_Shape> pieces;
        std::vector<CellRefusal> refusals;
        for (std::size_t c = 0; c < solid.cells.size(); ++c) {
            // C2: a face of the piece left INTERNAL is the face failing to split it, unless it is
            // the flap along a wall on the cell's boundary: its image within 2 pushes of the wall,
            // its edges certified by the band's curve bound. Section 15.8 2b: the face's image lies
            // in the band when its boundary's and its silhouette's do; NOT YET the silhouette.
            std::vector<std::size_t> bounding;
            for (TopExp_Explorer edges(solid.cells[c], TopAbs_EDGE); edges.More(); edges.Next()) {
                for (std::size_t w = 0; w < needed.size(); ++w) {
                    if (onWall[w].Contains(edges.Current())
                        && std::ranges::find(bounding, w) == bounding.end()) {
                        bounding.push_back(w);
                    }
                }
            }
            Band band(trace.frame);
            for (const std::size_t w : bounding) {
                for (const Handle(Geom2d_Curve)& part : wallParts[w]) {
                    band.add(part, 2.0 * pushes[w]);
                }
            }
            auto [piece, why] = sweepCell(solid.cells[c], face, axis, sliver, band, resolution, tolerance);
            if (piece.IsNull()) {
                refusals.push_back({c, why});
                continue;
            }
            std::string flap;
            for (TopExp_Explorer faces(piece, TopAbs_FACE); faces.More() && flap.empty(); faces.Next()) {
                if (faces.Current().Orientation() != TopAbs_INTERNAL) {
                    continue;
                }
                std::optional<gp_Pnt> away;
                for (TopExp_Explorer edges(faces.Current(), TopAbs_EDGE); edges.More() && !away; edges.Next()) {
                    if (!BRep_Tool::Degenerated(TopoDS::Edge(edges.Current()))) {
                        away = band.outside(TopoDS::Edge(edges.Current()));
                    }
                }
                if (away) {
                    flap = fmt::format(
                        "C2: the face doesn't split the cell's piece (near ({:.4g}, {:.4g}, {:.4g}))",
                        away->X(),
                        away->Y(),
                        away->Z()
                    );
                }
            }
            if (!flap.empty()) {
                refusals.push_back({c, flap});
                continue;
            }
            pieces.push_back(piece);
        }

        // The pieces fused (C6: their volumes add up, within the walls' area times the
        // tolerance)
        std::string fuseRefusal;
        if (refusals.empty()) {
            try {
                TopoDS_Shape fused = pieces.front();
                double piecesArea = 0.0;
                double piecesVolume = 0.0;
                double piecesError = 0.0;
                double piecesTolerance = 0.0;
                for (const TopoDS_Shape& piece : pieces) {
                    piecesArea += area(piece);
                    const auto [value, error] = volume(piece);
                    piecesVolume += value;
                    piecesError += error;
                    piecesTolerance = std::max(piecesTolerance, largestTolerance(piece));
                }
                if (pieces.size() > 1) {
                    BRepAlgoAPI_Fuse fuse;
                    TopTools_ListOfShape first;
                    first.Append(pieces.front());
                    TopTools_ListOfShape rest;
                    for (std::size_t k = 1; k < pieces.size(); ++k) {
                        rest.Append(pieces[k]);
                    }
                    fuse.SetArguments(first);
                    fuse.SetTools(rest);
                    fuse.Build();
                    if (!fuse.IsDone()) {
                        throw refused("the pieces' fuse failed");
                    }
                    fused = fuse.Shape();
                }
                // The walls' faces lie between two pieces: counted twice in the pieces, not at
                // all in the fuse
                const double wallArea = std::max(0.0, (piecesArea - area(fused)) / 2.0);
                const TopoDS_Shape refined
                    = Part::TopoShape(fused).makeElementRefine(nullptr, Part::RefineFail::shapeUntouched).getShape();
                int count = 0;
                for (TopExp_Explorer solids(refined, TopAbs_SOLID); solids.More(); solids.Next()) {
                    ++count;
                }
                const auto [fusedVolume, fusedError] = volume(refined);
                if (count != 1 || !BRepCheck_Analyzer(refined).IsValid()) {
                    fuseRefusal = fmt::format("C6: the fuse is {} solids, or invalid", count);
                }
                else if (std::fabs(fusedVolume - piecesVolume)
                         > 1e-7 * piecesVolume + wallArea * piecesTolerance + piecesError + fusedError) {
                    fuseRefusal = fmt::format(
                        "C6: the fuse holds {:.9g}, the pieces {:.9g}",
                        fusedVolume,
                        piecesVolume
                    );
                }
                else {
                    solid.shape = refined;
                    solid.trace = trace;
                    solid.pieces = pieces;
                    return solid;
                }
            }
            catch (const Standard_Failure& failure) {
                fuseRefusal = std::string("the pieces' fuse failed: ") + failure.GetMessageString();
            }
        }

        // The walls of the cells that refused, or all of them when the fuse did, pushed farther
        std::string why = fuseRefusal;
        std::vector<bool> raising(needed.size(), !fuseRefusal.empty());
        for (const CellRefusal& refusal : refusals) {
            why += (why.empty() ? "" : "; ") + fmt::format("cell {}: {}", refusal.cell + 1, refusal.why);
            bool bounded = false;
            for (TopExp_Explorer edges(solid.cells[refusal.cell], TopAbs_EDGE); edges.More(); edges.Next()) {
                for (std::size_t w = 0; w < needed.size(); ++w) {
                    if (onWall[w].Contains(edges.Current())) {
                        raising[w] = true;
                        bounded = true;
                    }
                }
            }
            if (!bounded) {
                std::ranges::fill(raising, true);
            }
        }
        if (std::getenv("FC_D2_WHY")) { std::fprintf(stderr, "D2WHY build %d: %s\n", build, why.c_str()); }  // TEMP s7
        if (build == 3) {
            throw refused(why);
        }
        // Once per group
        for (std::size_t w = 0; w < needed.size(); ++w) {
            if (raising[w] && group[w] == w) {
                raise(w);
                if (pushes[w] > cap) {
                    // The reason stays with the refusal: the cap alone doesn't say what failed
                    throw refused(fmt::format(
                        "{}; a wall would then be pushed {:.3g}, over 1e-4 of the profile's size",
                        why,
                        pushes[w]
                    ));
                }
            }
        }
    }
}

}  // namespace PartDesign::FirstContact
