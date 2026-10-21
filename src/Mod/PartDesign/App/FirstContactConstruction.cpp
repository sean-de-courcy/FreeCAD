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
#include <cmath>
#include <functional>
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
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <ElCLib.hxx>
#include <Geom_Curve.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Geom2dConvert.hxx>
#include <GeomAPI.hxx>
#include <GProp_GProps.hxx>
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

// One cell swept up to the face: the cell revolved a sliver short of a whole turn, split by the
// face, and the solid at its start cap (as sweepUpToFace() in FeatureRevolved.cpp). C1: exactly one
// such solid, keeping the whole cap. `inBand` says whether a point lies within the band of a wall on
// the cell's boundary. Returns the solid, or why it refuses.
std::pair<TopoDS_Shape, std::string> sweepCell(
    const TopoDS_Face& cell,
    const TopoDS_Face& face,
    const gp_Ax1& axis,
    double sliver,
    const std::function<bool(const gp_Pnt&)>& inBand
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
        // C2, a sheet of the face lost in the split: every edge of the piece where the face cuts the
        // turn bounds a piece of the face there (the end, or a flap), unless it lies in the band of a
        // wall, where the split may drop a flap that bounds nothing (the hook at the first push). On
        // q18's fold trimmed by a slanted plane (TrimmedFold), the split cut the turn's faces along
        // the face's middle leg but merged the leg's own piece with the face outside the turn, near a
        // vertex of tolerance 2e-5 at the wall junction: the piece ran on to the next leg, +0.03 in
        // volume, with every other check passing (ops#293 D2 session 5). PROVISIONAL like the flap's
        // check below: a lost sheet whose edges all lie on walls isn't seen.
        const TopTools_IndexedMapOfShape faceParts = Part::UpToSplitMapper::piecesOf(splitter, face);
        TopTools_IndexedMapOfShape sections;
        for (const TopoDS_Shape& edge : splitter.SectionEdges()) {
            sections.Add(edge);
        }
        TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
        TopExp::MapShapesAndAncestors(kept.front(), TopAbs_EDGE, TopAbs_FACE, edgeFaces);
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
            BRepAdaptor_Curve along(edge);
            for (int s = 0; s <= 32; ++s) {
                const gp_Pnt point
                    = along.Value(along.FirstParameter() + (along.LastParameter() - along.FirstParameter()) * s / 32);
                if (inBand(point)) {
                    continue;
                }
                return {{},
                        fmt::format(
                            "C2: the face crosses the cell's piece without splitting it (near ({:.4g}, {:.4g}, {:.4g}))",
                            point.X(),
                            point.Y(),
                            point.Z()
                        )};
            }
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

    std::vector<double> pushes(needed.size(), firstPush);
    std::vector<int> raised(needed.size(), 0);
    // The largest edge tolerance of the face's section with the unpushed wall turned about the axis
    auto sectionTolerance = [&](std::size_t w) {
        try {
            const Handle(Geom2d_BSplineCurve) curve = asBSpline(trace.pieces[needed[w]]);
            const TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(GeomAPI::To3d(curve, wallPlane)).Edge();
            BRepPrimAPI_MakeRevol turn(edge, axis, 2.0 * std::numbers::pi);
            BRepAlgoAPI_Section section(face, turn.Shape());
            return section.IsDone() ? largestEdgeTolerance(section.Shape()) : 0.0;
        }
        catch (const Standard_Failure&) {
            return 0.0;
        }
    };
    auto raise = [&](std::size_t w) {
        if (raised[w] == 0) {
            pushes[w] = std::max(10.0 * firstPush, 4.0 * sectionTolerance(w));
        }
        else {
            pushes[w] *= 10.0;
        }
        ++raised[w];
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
        // Each wall's edges: its curve, a connector to the next piece of its curve where that is
        // a wall too (the two lie 2 pushes apart across the flip), and its free ends carried out
        std::vector<std::vector<TopoDS_Edge>> wallEdges(needed.size());
        for (std::size_t w = 0; w < needed.size(); ++w) {
            solid.walls.push_back(pushedWall(trace, needed[w], pushes[w]));
        }
        for (std::size_t w = 0; w < needed.size(); ++w) {
            const Handle(Geom2d_BSplineCurve)& curve = solid.walls[w].curve;
            wallEdges[w].push_back(BRepBuilderAPI_MakeEdge(GeomAPI::To3d(curve, wallPlane)).Edge());
            const bool joinsPrevious = w > 0 && needed[w - 1] + 1 == needed[w]
                && trace.pieces[needed[w]].continuesPrevious;
            const bool joinsNext = w + 1 < needed.size() && needed[w] + 1 == needed[w + 1]
                && trace.pieces[needed[w + 1]].continuesPrevious;
            auto at = [&](const gp_Pnt2d& point) {
                return ElCLib::To3d(wallPlane.Position().Ax2(), point);
            };
            gp_Pnt2d point;
            gp_Vec2d along;
            if (!joinsPrevious) {
                curve->D1(curve->FirstParameter(), point, along);
                const gp_Pnt2d out = point.Translated(along.Normalized() * -extension);
                wallEdges[w].push_back(BRepBuilderAPI_MakeEdge(at(point), at(out)).Edge());
            }
            if (joinsNext) {
                const gp_Pnt2d to = solid.walls[w + 1].curve->StartPoint();
                if (curve->EndPoint().Distance(to) > Precision::Confusion()) {
                    wallEdges[w].push_back(BRepBuilderAPI_MakeEdge(at(curve->EndPoint()), at(to)).Edge());
                }
            }
            else {
                curve->D1(curve->LastParameter(), point, along);
                const gp_Pnt2d out = point.Translated(along.Normalized() * extension);
                wallEdges[w].push_back(BRepBuilderAPI_MakeEdge(at(point), at(out)).Edge());
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
            // the flap along a wall on the cell's boundary: its image within 2 pushes of the wall.
            // PROVISIONAL (ops#293 D2 session 4): the image is checked at points along the
            // face's edges; section 15.8's certified band bound (the edges by the curve bound, the
            // silhouette in the face by the patch bound) replaces it.
            std::vector<std::size_t> bounding;
            for (TopExp_Explorer edges(solid.cells[c], TopAbs_EDGE); edges.More(); edges.Next()) {
                for (std::size_t w = 0; w < needed.size(); ++w) {
                    if (onWall[w].Contains(edges.Current())
                        && std::ranges::find(bounding, w) == bounding.end()) {
                        bounding.push_back(w);
                    }
                }
            }
            auto inBand = [&](const gp_Pnt& point) {
                const gp_Vec offset(axis.Location(), point);
                const double height = offset.Dot(gp_Vec(axis.Direction()));
                const double out = (offset - gp_Vec(axis.Direction()) * height).Magnitude();
                const TopoDS_Vertex image
                    = BRepBuilderAPI_MakeVertex(ElCLib::To3d(wallPlane.Position().Ax2(), gp_Pnt2d(out, height)));
                return std::ranges::any_of(bounding, [&](std::size_t w) {
                    for (const TopoDS_Edge& edge : wallEdges[w]) {
                        BRepExtrema_DistShapeShape distance(image, edge);
                        if (distance.IsDone() && distance.Value() <= 2.0 * pushes[w]) {
                            return true;
                        }
                    }
                    return false;
                });
            };
            auto [piece, why] = sweepCell(solid.cells[c], face, axis, sliver, inBand);
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
                    BRepAdaptor_Curve along(TopoDS::Edge(edges.Current()));
                    for (int k = 0; k <= 32 && !away; ++k) {
                        const gp_Pnt point = along.Value(
                            along.FirstParameter() + (along.LastParameter() - along.FirstParameter()) * k / 32
                        );
                        if (!inBand(point)) {
                            away = point;
                        }
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
        if (build == 3) {
            throw refused(why);
        }
        for (std::size_t w = 0; w < needed.size(); ++w) {
            if (raising[w]) {
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
