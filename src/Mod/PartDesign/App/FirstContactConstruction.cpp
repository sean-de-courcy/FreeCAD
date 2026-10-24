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
#include <iterator>
#include <limits>
#include <numbers>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include <BOPTools_AlgoTools3D.hxx>
#include <Bnd_Box.hxx>
#include <Bnd_Box2d.hxx>
#include <BndLib_Add2dCurve.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
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
#include <Geom2d_BezierCurve.hxx>
#include <Geom2dConvert.hxx>
#include <Geom2dConvert_BSplineCurveToBezierCurve.hxx>
#include <Geom2dInt_GInter.hxx>
#include <GeomAPI.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GeomConvert.hxx>
#include <GeomConvert_BSplineSurfaceToBezierSurface.hxx>
#include <GProp_GProps.hxx>
#include <IntRes2d_IntersectionPoint.hxx>
#include <IntTools_Context.hxx>
#include <gp_Ax3.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <gp_Vec2d.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColGeom_Array2OfBezierSurface.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>

#include <fmt/format.h>

#include <Base/Exception.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeMapper.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

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

// The walls' edges, generated from the element of the face each wall is the image of (section
// 15.17): its edge, or the face itself for a silhouette. One element's walls in the order they are
// added.
class WallSources: public Part::TopoShape::Mapper
{
public:
    void add(const TopoDS_Shape& source, const std::vector<TopoDS_Edge>& edges)
    {
        for (auto& [element, generated] : sources) {
            if (element.IsSame(source)) {
                generated.insert(generated.end(), edges.begin(), edges.end());
                return;
            }
        }
        sources.emplace_back(source, std::vector<TopoDS_Shape>(edges.begin(), edges.end()));
    }

    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& element) const override
    {
        _res.clear();
        for (const auto& [source, edges] : sources) {
            if (source.IsSame(element)) {
                _res = edges;
            }
        }
        return _res;
    }

private:
    std::vector<std::pair<TopoDS_Shape, std::vector<TopoDS_Shape>>> sources;
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
// integrated from the wall's curve to 4e-7. A failed integration (a negative error) leaves no
// volume to check by, so it throws: read as a volume, its error passed every check (ops#428).
std::pair<double, double> volume(const TopoDS_Shape& shape)
{
    GProp_GProps properties;
    const double relativeError
        = BRepGProp::VolumePropertiesGK(shape, properties, 1e-7, Standard_True, Standard_True);
    if (relativeError < 0.0) {
        throw Standard_Failure("the volume's integration over knot spans failed");
    }
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

// A wall's line, for its name (section 15.19): the line through its unpushed curve's ends, as the
// doubled angle of its direction and the foot of the perpendicular from the frame's origin, rounded
// (to 1e-3 and 1e-4 mm). The same for a straight wall wherever the profile cuts it; a curved wall's
// changes with the profile, and a reference to it breaks.
std::string lineKey(const Handle(Geom2d_BSplineCurve)& curve)
{
    const gp_Pnt2d start = curve->StartPoint();
    gp_Vec2d along(start, curve->EndPoint());
    if (along.Magnitude() < Precision::Confusion()) {
        return "P";
    }
    along.Normalize();
    const gp_Vec2d normal(-along.Y(), along.X());
    const double offset = gp_Vec2d(start.XY()).Dot(normal);
    auto rounded = [](double value) {
        const long long k = std::llround(value);
        return k < 0 ? "N" + std::to_string(-k) : std::to_string(k);
    };
    return fmt::format(
        "{}_{}_{}_{}",
        rounded(1e3 * (along.X() * along.X() - along.Y() * along.Y())),
        rounded(1e3 * 2.0 * along.X() * along.Y()),
        rounded(offset * normal.X() / 1e-4),
        rounded(offset * normal.Y() / 1e-4)
    );
}

// A point inside the face: OCCT's, or the first of points along the middle of its parameters' box
// (across u, then across v) that lies inside
std::optional<gp_Pnt> pointInside(const TopoDS_Face& face, const Handle(IntTools_Context)& context)
{
    gp_Pnt point;
    gp_Pnt2d uv;
    if (BOPTools_AlgoTools3D::PointInFace(face, point, uv, context) == 0) {
        return point;
    }
    double u0 = 0.0;
    double u1 = 0.0;
    double v0 = 0.0;
    double v1 = 0.0;
    BRepTools::UVBounds(face, u0, u1, v0, v1);
    const BRepTopAdaptor_FClass2d classifier(face, Precision::PConfusion());
    for (const bool acrossU : {true, false}) {
        for (const int k : {4, 1, 2, 3, 5, 6, 7}) {
            const double share = k / 8.0;
            uv = acrossU ? gp_Pnt2d(u0 + share * (u1 - u0), (v0 + v1) / 2.0)
                         : gp_Pnt2d((u0 + u1) / 2.0, v0 + share * (v1 - v0));
            if (classifier.Perform(uv) == TopAbs_IN) {
                return BRep_Tool::Surface(face)->Value(uv.X(), uv.Y());
            }
        }
    }
    return std::nullopt;
}

}  // namespace

std::string certifyPiece(
    const TopoDS_Shape& piece,
    const TopoDS_Face& face,
    const TopTools_IndexedMapOfShape& faceParts,
    const Band& band,
    double tolerance
)
{
    auto refusal = [](const char* what, const gp_Pnt& point) {
        return fmt::format("{} (near ({:.4g}, {:.4g}, {:.4g}))", what, point.X(), point.Y(), point.Z());
    };
    // C3: seams aren't edges, the face goes on across them
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
        const double edgeTolerance = largestEdgeTolerance(face);
        // Non-destructive: the piece's edges are the face's, and the boolean would raise their
        // tolerances in place (the hook's flap edge from 5e-6 to 2.9e-5, past its band)
        BRepAlgoAPI_Common common;
        TopTools_ListOfShape arguments;
        arguments.Append(edges);
        TopTools_ListOfShape tools;
        tools.Append(piece);
        common.SetArguments(arguments);
        common.SetTools(tools);
        common.SetNonDestructive(Standard_True);
        common.Build();
        if (!common.IsDone()) {
            return "C3: the face's edges can't be checked against the cell's piece";
        }
        BRepClass3d_SolidClassifier inPiece(piece);
        for (TopExp_Explorer explorer(common.Shape(), TopAbs_EDGE); explorer.More(); explorer.Next()) {
            const TopoDS_Edge& inside = TopoDS::Edge(explorer.Current());
            BRepAdaptor_Curve curve(inside);
            const gp_Pnt middle = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2.0);
            inPiece.Perform(middle, tolerance);
            if (inPiece.State() != TopAbs_IN) {
                continue;
            }
            if (const auto out = band.outside(inside, edgeTolerance)) {
                return refusal("C3: the face's edge lies in the cell's turn", *out);
            }
        }
    }
    // C4 and C5: where the circles meet a part of the face on the piece's boundary from behind or
    // touch it, it lies in the band (Band::behind()). Internal parts are C2's.
    for (TopExp_Explorer faces(piece, TopAbs_FACE); faces.More(); faces.Next()) {
        const TopoDS_Face& part = TopoDS::Face(faces.Current());
        if (!faceParts.Contains(part) || part.Orientation() == TopAbs_INTERNAL
            || part.Orientation() == TopAbs_EXTERNAL) {
            continue;
        }
        if (const auto out = band.behind(part)) {
            return refusal("C4-C5: the cell's turn meets the face from behind, or touches it", *out);
        }
    }
    return {};
}

namespace
{

// One cell swept up to the face: the cell revolved a sliver short of a whole turn, split by the
// face, and the solid at its start cap (as sweepUpToFace() in FeatureRevolved.cpp). C1: exactly one
// such solid, keeping the whole cap. `band` is that of the walls on the cell's boundary; `step` is
// lostSheet()'s. C2's lost sheet and C3-C5 (certifyPiece()) on the solid. Returns the solid, named
// from `cell`'s names as sweepUpToFace() names its sweep, with `blank`'s tag; or why it refuses.
std::pair<Part::TopoShape, std::string> sweepCell(
    const Part::TopoShape& blank,
    const Part::TopoShape& cell,
    const TopoDS_Face& face,
    const gp_Ax1& axis,
    double sliver,
    const Band& band,
    double step,
    double tolerance
)
{
    const TopoDS_Face cellFace = TopoDS::Face(cell.getShape());
    try {
        BRepPrimAPI_MakeRevol turn(cellFace, axis, 2.0 * std::numbers::pi - sliver);
        if (!turn.IsDone()) {
            return {{}, "the cell's turn failed"};
        }
        // Non-destructive here and in every boolean of the construction: the face is the user's, and
        // the pieces share its edges
        BRepAlgoAPI_Splitter splitter;
        TopTools_ListOfShape arguments;
        arguments.Append(turn.Shape());
        TopTools_ListOfShape tools;
        tools.Append(face);
        splitter.SetArguments(arguments);
        splitter.SetTools(tools);
        splitter.SetNonDestructive(Standard_True);
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
        const double cellArea = area(cellFace);
        const double allowed = 1e-9 * cellArea + perimeter(cellFace) * std::max(largestTolerance(cellFace), Precision::Confusion());
        if (std::fabs(cap - cellArea) > allowed) {
            return {{}, fmt::format("C1: the piece's start cap is {:.9g} of the cell's {:.9g}", cap, cellArea)};
        }
        if (const std::string why = certifyPiece(kept.front(), face, faceParts, band, tolerance); !why.empty()) {
            return {{}, why};
        }
        Part::TopoShape turned(blank);
        turned.makeElementShape(turn, cell, Part::OpCodes::Revolve);
        auto firstShape = [&turn](const TopoDS_Shape& element) { return turn.FirstShape(element); };
        Part::TopoShape piece(blank);
        piece.makeShapeWithElementMap(
            kept.front(),
            Part::UpToSplitMapper(splitter, turn, firstShape, cellFace, kept.front()),
            {turned, Part::TopoShape(face)},
            Part::OpCodes::Revolve
        );
        return {piece, {}};
    }
    catch (const Standard_Failure& failure) {
        return {{}, std::string("the cell's sweep failed: ") + failure.GetMessageString()};
    }
}

}  // namespace

std::pair<double, double> spanVolume(const TopoDS_Shape& shape)
{
    return volume(shape);
}

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
    Part part {spline, width, derivativeBounds(spline).second, {}, {}};
    // The spans' boxes, from the Bezier arcs' poles: a rational arc lies in its poles' convex hull
    // when its weights are positive. Otherwise one span, which every point may be near.
    Geom2dConvert_BSplineCurveToBezierCurve arcs(spline);
    TColStd_Array1OfReal knots(1, arcs.NbArcs() + 1);
    arcs.Knots(knots);
    bool bounded = true;
    for (int k = 1; k <= arcs.NbArcs() && bounded; ++k) {
        const Handle(Geom2d_BezierCurve) arc = arcs.Arc(k);
        Span span {knots(k), knots(k + 1)};
        span.xLow = span.yLow = std::numeric_limits<double>::max();
        span.xHigh = span.yHigh = std::numeric_limits<double>::lowest();
        for (int i = 1; i <= arc->NbPoles(); ++i) {
            bounded = bounded && arc->Weight(i) > 0.0;
            const gp_Pnt2d pole = arc->Pole(i);
            span.xLow = std::min(span.xLow, pole.X());
            span.xHigh = std::max(span.xHigh, pole.X());
            span.yLow = std::min(span.yLow, pole.Y());
            span.yHigh = std::max(span.yHigh, pole.Y());
        }
        part.spans.push_back(span);
    }
    if (!bounded) {
        constexpr double huge = std::numeric_limits<double>::max();
        part.spans = {{spline->FirstParameter(), spline->LastParameter(), -huge, huge, -huge, huge}};
    }
    part.box = part.spans.front();
    for (const Span& span : part.spans) {
        part.box.xLow = std::min(part.box.xLow, span.xLow);
        part.box.xHigh = std::max(part.box.xHigh, span.xHigh);
        part.box.yLow = std::min(part.box.yLow, span.yLow);
        part.box.yHigh = std::max(part.box.yHigh, span.yHigh);
    }
    parts.push_back(std::move(part));
}


std::pair<double, double> Band::nearest(const Part& part, const gp_Pnt2d& point)
{
    const Handle(Geom2d_BSplineCurve)& curve = part.curve;
    std::pair<double, double> best {curve->FirstParameter(), point.Distance(curve->StartPoint())};
    if (const double last = point.Distance(curve->EndPoint()); last < best.second) {
        best = {curve->LastParameter(), last};
    }
    // The distance to a span's box (squared), a lower bound of the distance to its points: a span
    // whose box is farther than the nearest point found so far can't hold a nearer one. The box of
    // all of them first.
    auto squared = [&](const Span& span) {
        const double dx = std::max({span.xLow - point.X(), 0.0, point.X() - span.xHigh});
        const double dy = std::max({span.yLow - point.Y(), 0.0, point.Y() - span.yHigh});
        return dx * dx + dy * dy;
    };
    // Out of the part's band whatever its nearest point: no parameter, and the lower bound
    const double width = part.width * part.width;
    if (const double all = squared(part.box); all > width) {
        return {std::numeric_limits<double>::quiet_NaN(), std::sqrt(all)};
    }
    std::vector<double> low(part.spans.size());
    std::size_t closest = 0;
    for (std::size_t k = 0; k < part.spans.size(); ++k) {
        low[k] = squared(part.spans[k]);
        if (low[k] < low[closest]) {
            closest = k;
        }
    }
    if (low[closest] > width) {
        return {std::numeric_limits<double>::quiet_NaN(), std::sqrt(low[closest])};
    }
    auto search = [&](const Span& span) {
        // The span's ends, where the nearest point may lie without being an extremum of the span
        for (const double t : {span.first, span.last}) {
            if (const double d = point.Distance(curve->Value(t)); d < best.second) {
                best = {t, d};
            }
        }
        Geom2dAPI_ProjectPointOnCurve projection(point, curve, span.first, span.last);
        if (projection.NbPoints() > 0 && projection.LowerDistance() < best.second) {
            best = {projection.LowerDistanceParameter(), projection.LowerDistance()};
        }
    };
    // The closest box first, which usually leaves no other below the distance found
    search(part.spans[closest]);
    for (std::size_t k = 0; k < part.spans.size(); ++k) {
        if (k != closest && low[k] < best.second * best.second) {
            search(part.spans[k]);
        }
    }
    return best;
}

bool Band::contains(const gp_Pnt& point) const
{
    const gp_Pnt2d at = image(point);
    return std::ranges::any_of(parts, [&](const Part& part) {
        return nearest(part, at).second <= part.width;
    });
}

std::optional<gp_Pnt> Band::outside(const TopoDS_Edge& edge) const
{
    return outside(edge, BRep_Tool::Tolerance(edge));
}

std::optional<gp_Pnt> Band::outside(const TopoDS_Edge& edge, double tolerance) const
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
    struct Sample
    {
        double t = 0.0;
        gp_Pnt point;
        double radius = 0.0;
        // Per part: the nearest point's parameter and the distance
        std::vector<std::pair<double, double>> closest;
    };
    // A sample whose image, widened by the tolerance, is in no part's band can't be certified
    auto sample = [&](double t) -> std::optional<Sample> {
        Sample here {t, curve->Value(t), 0.0, {}};
        const gp_Pnt2d at = image(here.point);
        here.radius = at.X();
        bool held = false;
        for (const Part& part : parts) {
            here.closest.push_back(nearest(part, at));
            held = held || here.closest.back().second + tolerance < part.width;
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
                // A sample out of the part's band
                if (std::isnan(low.closest[p].first) || std::isnan(high.closest[p].first)) {
                    continue;
                }
                const double du = high.closest[p].first - low.closest[p].first;
                held = std::max(low.closest[p].second, high.closest[p].second)
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

namespace
{

// The largest norm of a vector polynomial's coefficients, a bound of its values (the convex hull
// property)
double largestNorm(const std::array<Bernstein, 3>& net)
{
    double largest = 0.0;
    for (std::size_t k = 0; k < net[0].value.size(); ++k) {
        largest = std::max(largest, std::hypot(net[0].value[k], net[1].value[k], net[2].value[k]));
    }
    return largest;
}

// The same across `axis` only: Phi's second derivative sees only that part of a tangent
double largestNormAcross(const std::array<Bernstein, 3>& net, const gp_XYZ& axis)
{
    double largest = 0.0;
    for (std::size_t k = 0; k < net[0].value.size(); ++k) {
        const gp_XYZ value(net[0].value[k], net[1].value[k], net[2].value[k]);
        largest = std::max(largest, (value - axis * value.Dot(axis)).Modulus());
    }
    return largest;
}

double largestValue(const Bernstein& polynomial)
{
    double largest = 0.0;
    for (const double value : polynomial.value) {
        largest = std::max(largest, std::abs(value));
    }
    return largest;
}

std::array<Bernstein, 3> derivatives(const std::array<Bernstein, 3>& net, bool alongU)
{
    return {derivative(net[0], alongU), derivative(net[1], alongU), derivative(net[2], alongU)};
}

// A point of the face, for a refusal that has no better one
gp_Pnt somewhere(const TopoDS_Face& face)
{
    TopExp_Explorer vertices(face, TopAbs_VERTEX);
    if (vertices.More()) {
        return BRep_Tool::Pnt(TopoDS::Vertex(vertices.Current()));
    }
    double uLow = 0.0;
    double uHigh = 0.0;
    double vLow = 0.0;
    double vHigh = 0.0;
    BRepTools::UVBounds(face, uLow, uHigh, vLow, vHigh);
    return BRep_Tool::Surface(face)->Value((uLow + uHigh) / 2.0, (vLow + vHigh) / 2.0);
}

}  // namespace

std::optional<gp_Pnt> Band::outside(const TopoDS_Face& face) const
{
    for (TopExp_Explorer edges(face, TopAbs_EDGE); edges.More(); edges.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(edges.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        if (auto out = outside(edge)) {
            return out;
        }
    }
    return leavesOutside(face, true);
}

std::optional<gp_Pnt> Band::behind(const TopoDS_Face& face) const
{
    return leavesOutside(face, false);
}

std::optional<gp_Pnt> Band::leavesOutside(const TopoDS_Face& face, bool whole) const
{
    SilhouetteSurface silhouette;
    try {
        silhouette = silhouetteSurface(face);
    }
    catch (const Base::Exception&) {
        return somewhere(face);
    }
    catch (const Standard_Failure&) {
        return somewhere(face);
    }
    const Handle(Geom_BSplineSurface)& surface = silhouette.surface;
    const TopoDS_Face& carrier = silhouette.carrier;
    const gp_Ax1 axis(frame.Location(), frame.YDirection());
    const gp_XYZ direction = axis.Direction().XYZ();
    const double tolerance = BRep_Tool::Tolerance(face);
    // g's sign against the face's outward normal: the converted surface's normal against the
    // face's own at the surface's middle
    double orientation = 1.0;
    if (!whole) {
        double uFirst = 0.0;
        double uLast = 0.0;
        double vFirst = 0.0;
        double vLast = 0.0;
        surface->Bounds(uFirst, uLast, vFirst, vLast);
        gp_Pnt middle;
        gp_Vec alongU;
        gp_Vec alongV;
        surface->D1((uFirst + uLast) / 2.0, (vFirst + vLast) / 2.0, middle, alongU, alongV);
        const gp_Vec converted = alongU.Crossed(alongV);
        const Handle(Geom_Surface) own = BRep_Tool::Surface(face);
        GeomAPI_ProjectPointOnSurf onOwn(middle, own);
        if (!onOwn.IsDone() || onOwn.NbPoints() < 1 || converted.Magnitude() <= gp::Resolution()) {
            return somewhere(face);
        }
        double u = 0.0;
        double v = 0.0;
        onOwn.LowerDistanceParameters(u, v);
        gp_Pnt at;
        own->D1(u, v, at, alongU, alongV);
        gp_Vec outward = alongU.Crossed(alongV);
        if (face.Orientation() == TopAbs_REVERSED) {
            outward.Reverse();
        }
        const double agreement = converted.Dot(outward);
        if (std::abs(agreement) <= 0.5 * converted.Magnitude() * outward.Magnitude()) {
            return somewhere(face);
        }
        orientation = agreement > 0.0 ? 1.0 : -1.0;
    }

    // Where the face's boundary can lie in its parameters: a rectangle that meets none of these
    // boxes holds no point of the boundary, so it lies in the face or out of it whole. Each pcurve
    // in 32 spans: one box for a slanted trim covers much of the face. Where the surface's
    // parameters aren't the face's, every leaf counts as reaching the face.
    std::vector<Bnd_Box2d> boundary;
    for (TopExp_Explorer edges(carrier, TopAbs_EDGE); edges.More(); edges.Next()) {
        double first = 0.0;
        double last = 0.0;
        const Handle(Geom2d_Curve) pcurve
            = BRep_Tool::CurveOnSurface(TopoDS::Edge(edges.Current()), carrier, first, last);
        if (pcurve.IsNull()) {
            return somewhere(face);
        }
        constexpr int spans = 32;
        for (int k = 0; k < spans; ++k) {
            Bnd_Box2d box;
            BndLib_Add2dCurve::Add(
                pcurve,
                first + (last - first) * k / spans,
                first + (last - first) * (k + 1) / spans,
                Precision::PConfusion(),
                box
            );
            boundary.push_back(box);
        }
    }
    BRepTopAdaptor_FClass2d inCarrier(carrier, Precision::PConfusion());
    auto inFace = [&](double u, double v) {
        return !silhouette.sameParameters || inCarrier.Perform(gp_Pnt2d(u, v)) != TopAbs_OUT;
    };
    auto reaches = [&](double u0, double u1, double v0, double v1) {
        if (!silhouette.sameParameters) {
            return true;
        }
        Bnd_Box2d rectangle;
        rectangle.Update(u0, v0, u1, v1);
        return std::ranges::any_of(boundary, [&](const Bnd_Box2d& box) { return !box.IsOut(rectangle); })
            || inFace((u0 + u1) / 2.0, (v0 + v1) / 2.0);
    };

    struct Corner
    {
        gp_Pnt point;
        double radius = 0.0;
        // Per part: the nearest point's parameter and the distance
        std::vector<std::pair<double, double>> closest;
    };
    // Corners in the order (u0, v0), (u1, v0), (u0, v1), (u1, v1)
    struct Leaf
    {
        SilhouettePatch patch;
        double u0 = 0.0;
        double u1 = 0.0;
        double v0 = 0.0;
        double v1 = 0.0;
        std::array<Corner, 4> corners;
    };
    auto corner = [&](const SilhouettePatch& patch, bool uHigh, bool vHigh) {
        const int k = patch.weights.index(uHigh ? patch.weights.m : 0, vHigh ? patch.weights.n : 0);
        Corner here;
        here.point = gp_Pnt(
            gp_XYZ(patch.net[0].value[k], patch.net[1].value[k], patch.net[2].value[k]) / patch.weights.value[k]
            + axis.Location().XYZ()
        );
        const gp_Pnt2d at = image(here.point);
        here.radius = at.X();
        for (const Part& part : parts) {
            here.closest.push_back(nearest(part, at));
        }
        return here;
    };
    // A corner of the face whose image, widened by the tolerance, is in no part's band: any, for
    // the whole face; for behind(), one where g <= 0
    auto away = [&](const Corner& here, double u, double v, double g) {
        if (!whole && g * orientation > 0.0) {
            return false;
        }
        for (std::size_t p = 0; p < parts.size(); ++p) {
            if (here.closest[p].second + tolerance < parts[p].width) {
                return false;
            }
        }
        return inFace(u, v);
    };
    // Whether the leaf's image is certified within one part's band; otherwise which way to halve it
    auto holds = [&](const Leaf& leaf, bool& alongU) {
        const SilhouettePatch& patch = leaf.patch;
        const std::size_t count = patch.weights.value.size();
        double lightest = std::numeric_limits<double>::max();
        gp_XYZ centre;
        for (std::size_t k = 0; k < count; ++k) {
            const double weight = patch.weights.value[k];
            lightest = std::min(lightest, weight);
            centre += gp_XYZ(patch.net[0].value[k], patch.net[1].value[k], patch.net[2].value[k]) / weight;
        }
        alongU = leaf.u1 - leaf.u0 >= leaf.v1 - leaf.v0;
        if (lightest <= 0.0) {
            return false;
        }
        centre /= static_cast<double>(count);
        double farthest = 0.0;
        for (std::size_t k = 0; k < count; ++k) {
            const gp_XYZ pole
                = gp_XYZ(patch.net[0].value[k], patch.net[1].value[k], patch.net[2].value[k]) / patch.weights.value[k];
            farthest = std::max(farthest, (pole - centre).Modulus());
        }
        // N = w (S - O) about the poles' centre O: S' = (N' - w' (S - O)) / w and
        // S'' = (N'' - 2 w' S' - w'' (S - O)) / w, with |S - O| at most the farthest pole. Across
        // the axis, the same with N' and S - O across it.
        std::array<Bernstein, 3> about;
        for (int c = 0; c < 3; ++c) {
            about[c] = sum(patch.net[c], scaled(patch.weights, centre.Coord(c + 1)), -1.0);
        }
        auto bounds = [&](bool u) {
            const std::array<Bernstein, 3> once = derivatives(about, u);
            const Bernstein weightOnce = derivative(patch.weights, u);
            const std::array<Bernstein, 3> twice = derivatives(once, u);
            const Bernstein weightTwice = derivative(weightOnce, u);
            const double speed = (largestNorm(once) + largestValue(weightOnce) * farthest) / lightest;
            const double across
                = (largestNormAcross(once, direction) + largestValue(weightOnce) * farthest) / lightest;
            const double bend = (largestNorm(twice) + 2.0 * largestValue(weightOnce) * speed
                                 + largestValue(weightTwice) * farthest)
                / lightest;
            return std::array<double, 3> {speed, across, bend};
        };
        const auto [speedU, acrossU, bendU] = bounds(true);
        const auto [speedV, acrossV, bendV] = bounds(false);
        alongU = speedU >= speedV;
        // The radius is 1-Lipschitz, and every point of the leaf lies within half its sides of a
        // corner
        double radius = std::numeric_limits<double>::max();
        for (const Corner& here : leaf.corners) {
            radius = std::min(radius, here.radius);
        }
        radius -= (speedU + speedV) / 2.0;
        if (radius <= 0.0) {
            return false;
        }
        const double turnU = bendU + acrossU * acrossU / radius;
        const double turnV = bendV + acrossV * acrossV / radius;
        const auto& c = leaf.corners;
        double least = std::numeric_limits<double>::max();
        for (std::size_t p = 0; p < parts.size(); ++p) {
            // A corner out of the part's band: the part can't hold the leaf
            if (std::ranges::any_of(c, [&](const Corner& here) { return std::isnan(here.closest[p].first); })) {
                continue;
            }
            const double duU = std::max(
                std::abs(c[1].closest[p].first - c[0].closest[p].first),
                std::abs(c[3].closest[p].first - c[2].closest[p].first)
            );
            const double duV = std::max(
                std::abs(c[2].closest[p].first - c[0].closest[p].first),
                std::abs(c[3].closest[p].first - c[1].closest[p].first)
            );
            const double termU = turnU + parts[p].bend * duU * duU;
            const double termV = turnV + parts[p].bend * duV * duV;
            double reach = 0.0;
            for (const Corner& here : c) {
                reach = std::max(reach, here.closest[p].second);
            }
            const double bound = reach + (termU + termV) / 8.0 + tolerance;
            if (bound <= parts[p].width) {
                return true;
            }
            if (bound < least) {
                least = bound;
                alongU = termU >= termV;
            }
        }
        return false;
    };

    GeomConvert_BSplineSurfaceToBezierSurface pieces(surface);
    TColGeom_Array2OfBezierSurface patches(1, pieces.NbUPatches(), 1, pieces.NbVPatches());
    pieces.Patches(patches);
    if (pieces.NbUPatches() != surface->NbUKnots() - 1 || pieces.NbVPatches() != surface->NbVKnots() - 1) {
        return somewhere(face);
    }
    std::vector<Leaf> stack;
    for (int i = patches.LowerRow(); i <= patches.UpperRow(); ++i) {
        for (int j = patches.LowerCol(); j <= patches.UpperCol(); ++j) {
            Leaf leaf {
                silhouettePatch(patches(i, j), axis),
                surface->UKnot(i),
                surface->UKnot(i + 1),
                surface->VKnot(j),
                surface->VKnot(j + 1),
                {}
            };
            leaf.corners = {
                corner(leaf.patch, false, false),
                corner(leaf.patch, true, false),
                corner(leaf.patch, false, true),
                corner(leaf.patch, true, true)
            };
            stack.push_back(std::move(leaf));
        }
    }
    // Halving stops at a floor, and the count at a budget (section 15.8: 1,000,000 nodes)
    const double floorU = (surface->UKnot(surface->NbUKnots()) - surface->UKnot(1)) * 1e-9;
    const double floorV = (surface->VKnot(surface->NbVKnots()) - surface->VKnot(1)) * 1e-9;
    constexpr int budget = 1000000;
    int count = 0;
    while (!stack.empty()) {
        Leaf leaf = std::move(stack.back());
        stack.pop_back();
        if (++count > budget) {
            return leaf.corners[0].point;
        }
        // None of the face, or no silhouette in the leaf (for behind(), none and g > 0)
        const Bernstein& g = leaf.patch.g;
        if (!reaches(leaf.u0, leaf.u1, leaf.v0, leaf.v1)
            || (oneSign(g) && (whole || g.value.front() * orientation > 0.0))) {
            continue;
        }
        const std::array<std::pair<double, double>, 4> at {
            std::make_pair(leaf.u0, leaf.v0),
            std::make_pair(leaf.u1, leaf.v0),
            std::make_pair(leaf.u0, leaf.v1),
            std::make_pair(leaf.u1, leaf.v1)
        };
        for (std::size_t k = 0; k < 4; ++k) {
            const double gCorner = g.value[g.index(k % 2 == 1 ? g.m : 0, k >= 2 ? g.n : 0)];
            if (away(leaf.corners[k], at[k].first, at[k].second, gCorner)) {
                return leaf.corners[k].point;
            }
        }
        bool alongU = true;
        if (holds(leaf, alongU)) {
            continue;
        }
        const bool uSmall = leaf.u1 - leaf.u0 <= floorU;
        const bool vSmall = leaf.v1 - leaf.v0 <= floorV;
        if (uSmall && vSmall) {
            return leaf.corners[0].point;
        }
        alongU = vSmall || (alongU && !uSmall);
        auto [first, second] = halves(leaf.patch, alongU);
        Leaf low {std::move(first), leaf.u0, leaf.u1, leaf.v0, leaf.v1, leaf.corners};
        Leaf high {std::move(second), leaf.u0, leaf.u1, leaf.v0, leaf.v1, leaf.corners};
        if (alongU) {
            low.u1 = high.u0 = (leaf.u0 + leaf.u1) / 2.0;
            low.corners[1] = high.corners[0] = corner(low.patch, true, false);
            low.corners[3] = high.corners[2] = corner(low.patch, true, true);
        }
        else {
            low.v1 = high.v0 = (leaf.v0 + leaf.v1) / 2.0;
            low.corners[2] = high.corners[0] = corner(low.patch, false, true);
            low.corners[3] = high.corners[1] = corner(low.patch, true, true);
        }
        stack.push_back(std::move(high));
        stack.push_back(std::move(low));
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
    return constructFirstContact(
        Part::TopoShape(),
        Part::TopoShape(face),
        Part::TopoShape(profile),
        axis,
        tolerance
    );
}

FirstContactSolid constructFirstContact(
    Part::TopoShape named,
    const Part::TopoShape& namedFace,
    const Part::TopoShape& namedProfile,
    const gp_Ax1& axis,
    double tolerance
)
{
    // Empty, with the tag, hasher and history algorithm of `named`
    const Part::TopoShape blank(named);
    const TopoDS_Face face = TopoDS::Face(namedFace.getShape());
    const TopoDS_Face profile
        = TopoDS::Face(TopExp_Explorer(namedProfile.getShape(), TopAbs_FACE).Current());
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
            BRepAlgoAPI_Section section(face, turn.Shape(), Standard_False);
            section.SetNonDestructive(Standard_True);
            section.Build();
            return section.IsDone() ? largestEdgeTolerance(section.Shape()) : 0.0;
        }
        catch (const Standard_Failure&) {
            return 0.0;
        }
    };
    // A wall's group pushed a level farther: the first level is max(10 x the first push, 4 x the
    // group's section tolerance), the next ten times more; always above where the group stands (a
    // junction's group starts at twice its gap, which may be above the first level)
    auto raise = [&](std::size_t w) {
        double push = 0.0;
        double current = 0.0;
        for (std::size_t v = 0; v < needed.size(); ++v) {
            if (group[v] != group[w]) {
                continue;
            }
            current = std::max(current, pushes[v]);
            push = std::max(
                push,
                raised[v] == 0 ? std::max(10.0 * firstPush, 4.0 * sectionTolerance(v)) : 10.0 * pushes[v]
            );
        }
        if (push <= current) {
            push = 10.0 * current;
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
        splitter.SetNonDestructive(Standard_True);
        splitter.Build();
        if (!splitter.IsDone()) {
            throw refused("the profile's split along the walls failed");
        }
        // The cells named through the split from the profile and the walls. A wall's name holds
        // its line (lineKey()), which the profile doesn't move: the walls of one element of F that
        // lie in the profile change with an edit of the profile, so a rank among them would move a
        // reference to another wall. Walls of one element on one line are ranked by their place,
        // and their count goes into the name: an edit that removes one renames the others.
        TopTools_IndexedMapOfShape faceEdges;
        TopExp::MapShapes(face, TopAbs_EDGE, faceEdges);
        struct WallGroup
        {
            TopoDS_Shape element;
            std::string line;
            std::vector<std::size_t> members;
        };
        std::vector<WallGroup> bySource;
        for (std::size_t w = 0; w < needed.size(); ++w) {
            const JumpPiece& source = trace.pieces[needed[w]];
            const TopoDS_Shape element
                = source.source == JumpSource::Edge ? faceEdges(source.edge) : TopoDS_Shape(face);
            const std::string line = lineKey(unpushed[w]);
            auto found = std::ranges::find_if(bySource, [&](const WallGroup& entry) {
                return entry.element.IsSame(element) && entry.line == line;
            });
            if (found == bySource.end()) {
                bySource.push_back({element, line, {}});
                found = std::prev(bySource.end());
            }
            found->members.push_back(w);
        }
        // A wall's place: its unpushed curve's middle, by the distance from the axis, then the
        // height along it
        auto place = [&](std::size_t w) {
            const Handle(Geom2d_BSplineCurve)& curve = unpushed[w];
            const gp_Pnt2d middle = curve->Value((curve->FirstParameter() + curve->LastParameter()) / 2.0);
            return std::pair(middle.X(), middle.Y());
        };
        std::vector<Part::TopoShape> namedSources {namedProfile};
        for (auto& [element, line, members] : bySource) {
            std::ranges::sort(members, [&](std::size_t a, std::size_t b) { return place(a) < place(b); });
            WallSources sources;
            TopoDS_Compound wallCompound;
            BRep_Builder builder;
            builder.MakeCompound(wallCompound);
            for (const std::size_t w : members) {
                sources.add(element, wallEdges[w]);
                for (const TopoDS_Edge& edge : wallEdges[w]) {
                    builder.Add(wallCompound, edge);
                }
            }
            const std::string op = fmt::format("FCW{}_{}", members.size(), line);
            Part::TopoShape walls(blank);
            walls.makeShapeWithElementMap(wallCompound, sources, {namedFace}, op.c_str());
            namedSources.push_back(walls);
        }
        Part::TopoShape namedCells(blank);
        namedCells.makeElementShape(splitter, namedSources, Part::OpCodes::Split);
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
        if (solid.cells.empty()) {
            throw refused("the profile's split along the walls left no face");
        }
        constexpr std::size_t largestCells = 32;
        if (solid.cells.size() > largestCells) {
            throw refused(fmt::format("the walls split the profile into {} cells, over 32", solid.cells.size()));
        }

        // Each cell up to the face, checked
        std::vector<TopoDS_Shape> pieces;
        std::vector<Part::TopoShape> namedPieces;
        std::vector<CellRefusal> refusals;
        for (std::size_t c = 0; c < solid.cells.size(); ++c) {
            // C2: a face of the piece left INTERNAL is the face failing to split it, unless it is
            // the flap along a wall on the cell's boundary: its image within 2 pushes of the wall,
            // certified by its edges and its silhouette (section 15.8, 2b)
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
            const Part::TopoShape cell
                = namedCells.getSubTopoShape(TopAbs_FACE, namedCells.findShape(solid.cells[c]));
            auto [namedPiece, why]
                = sweepCell(blank, cell, face, axis, sliver, band, resolution, tolerance);
            const TopoDS_Shape piece = namedPiece.getShape();
            if (piece.IsNull()) {
                refusals.push_back({c, why});
                continue;
            }
            std::string flap;
            const Handle(IntTools_Context) context = new IntTools_Context;
            for (TopExp_Explorer faces(piece, TopAbs_FACE); faces.More() && flap.empty(); faces.Next()) {
                if (faces.Current().Orientation() != TopAbs_INTERNAL) {
                    continue;
                }
                const TopoDS_Face internal = TopoDS::Face(faces.Current());
                std::optional<gp_Pnt> away = band.outside(internal);
                // The bands of all the walls on the cell's boundary may enclose the cell: then the
                // face's edges and silhouette in the band don't hold its interior there (a sheet
                // across the cell has neither; section 15.18). A flap's interior maps into the band
                // too. A flap too thin for OCCT to find a point inside (the hook's, 2 pushes wide)
                // lies within its width of its edges.
                if (!away) {
                    if (const auto point = pointInside(internal, context); point && !band.contains(*point)) {
                        away = point;
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
            namedPieces.push_back(namedPiece);
        }

        // The pieces fused (C6: their volumes add up, within the walls' area times the
        // tolerance)
        std::string fuseRefusal;
        if (refusals.empty()) {
            try {
                Part::TopoShape fused = namedPieces.front();
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
                    fuse.SetNonDestructive(Standard_True);
                    fuse.Build();
                    if (!fuse.IsDone()) {
                        throw refused("the pieces' fuse failed");
                    }
                    fused = Part::TopoShape(blank).makeElementShape(fuse, namedPieces, Part::OpCodes::Fuse);
                }
                // The walls' faces lie between two pieces: counted twice in the pieces, not at
                // all in the fuse
                const double wallArea = std::max(0.0, (piecesArea - area(fused.getShape())) / 2.0);
                const Part::TopoShape namedRefined
                    = fused.makeElementRefine(nullptr, Part::RefineFail::shapeUntouched);
                const TopoDS_Shape refined = namedRefined.getShape();
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
                    solid.named = namedRefined;
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
        if (build == 3) {
            throw refused(why);
        }
        // Once per group, whichever of its walls bounds a cell that refused
        std::vector<std::size_t> groups;
        for (std::size_t w = 0; w < needed.size(); ++w) {
            if (raising[w] && std::ranges::find(groups, group[w]) == groups.end()) {
                groups.push_back(group[w]);
            }
        }
        for (const std::size_t w : groups) {
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

}  // namespace PartDesign::FirstContact
