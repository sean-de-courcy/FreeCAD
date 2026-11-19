// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2024 Eric Price (CorvusCorax)                           *
 *                      <eric.price[at]tuebingen.mpg.de>                   *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

/**
 * FCBRepAlgoAPI provides a wrapper for various OCCT functions.
 */

#include <algorithm>

#include <FCBRepAlgoAPI_BooleanOperation.h>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepBndLib.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <Bnd_Box.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepTools.hxx>
#include <GeomAdaptor_Surface.hxx>
#include <Message_ProgressScope.hxx>
#include <Geom_Surface.hxx>
#include <Standard_ConstructionError.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS_Face.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Iterator.hxx>
#include <Precision.hxx>
#include <FuzzyHelper.h>
#include <MassProperties.h>
#include <SignalException.h>
#include <Base/Console.h>
#include <Base/Exception.h>

#include <BOPAlgo_PaveFiller.hxx>
#include <BOPAlgo_Tools.hxx>
#include <BOPDS_DS.hxx>
#include <BOPDS_Interf.hxx>
#include <BOPDS_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <Extrema_GenLocateExtPS.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <IntSurf_PntOn2S.hxx>
#include <IntTools_Context.hxx>
#include <IntTools_FClass2d.hxx>
#include <IntTools_FaceFace.hxx>
#include <IntTools_Tools.hxx>
#include <NCollection_List.hxx>
#include <Standard_ErrorHandler.hxx>
#include <TopoDS_Edge.hxx>
#include <gp_Pnt2d.hxx>

#include <cmath>
#include <vector>

namespace
{

/* FreeCAD-CH ops#901: the face/face crossings OCCT 8.0.1 misses (notes/polar-pattern-901.md
 * section 9). Two near-tangent B-spline faces can cross along a short curve that OCCT's
 * surface/surface intersection never finds: its search for a start point lays a grid over the
 * whole of each surface (IntPatch_PrmPrmIntersection::PointDepart), as dense as the surface's
 * knots, and a crossing one or two grid cells wide falls between its points. The Boolean then
 * leaves an open shell, or a closed one with the wrong material.
 *
 * CrossingFiller runs OCCT's face/face step, then, for each face pair that got no curve and no
 * point, isn't marked tangent, has a freeform face and no periodic, closed or seamed one:
 * 1. restricts both faces to the parameter rectangles where they can meet (tiles of sampled
 *    boxes, a few levels), padded by their own size; nothing meets, or both still over half
 *    their face: left as OCCT found it;
 * 2. intersects the two rectangles of the same surfaces again (fuzzy 0), moved near the origin
 *    as OCCT moves a pair far from it;
 * 3. failing that, gives the intersector start points of its own: where the signed distance from
 *    a grid on the first rectangle to the second surface changes sign, bisected onto both
 *    surfaces, those on a rectangle's border first;
 * 4. keeps a curve only when a point of it lies strictly inside both faces (a curve along a
 *    boundary within tolerance is a graze, not a crossing);
 * and appends the curves kept to the pair the way PerformFF does. The rest of the Boolean
 * (MakeBlocks, the splits, the history) is OCCT's own.
 * Its numbers decide a saved result once a file holds a recovered feature (R3): they don't
 * change without a compat-change. */
constexpr int TileCount = 8;        // tiles per direction and level
constexpr int TileSamples = 4;      // sample intervals per tile edge
constexpr int TileLevels = 4;
constexpr double TilePad = 1.0;     // the rectangle grows by its own size on each side
constexpr int SeedGrid = 12;        // sign-change grid on the first rectangle
constexpr int MaxSeeds = 16;
constexpr int BisectSteps = 50;

struct Rect
{
    double u0, u1, v0, v1;
    double area() const
    {
        return (u1 - u0) * (v1 - v0);
    }
};

std::vector<Bnd_Box> tileBoxes(const Handle(Geom_Surface)& surface, const Rect& r)
{
    const int n = TileCount * TileSamples + 1;
    std::vector<gp_Pnt> points(static_cast<std::size_t>(n) * n);
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            points[static_cast<std::size_t>(i) * n + j] = surface->Value(
                r.u0 + (r.u1 - r.u0) * i / (n - 1),
                r.v0 + (r.v1 - r.v0) * j / (n - 1)
            );
        }
    }
    std::vector<Bnd_Box> boxes(static_cast<std::size_t>(TileCount) * TileCount);
    for (int a = 0; a < TileCount; ++a) {
        for (int b = 0; b < TileCount; ++b) {
            Bnd_Box box;
            for (int i = a * TileSamples; i <= (a + 1) * TileSamples; ++i) {
                for (int j = b * TileSamples; j <= (b + 1) * TileSamples; ++j) {
                    box.Add(points[static_cast<std::size_t>(i) * n + j]);
                }
            }
            box.Enlarge(0.1 * std::sqrt(box.SquareExtent()) + 1e-6);
            boxes[static_cast<std::size_t>(a) * TileCount + b] = box;
        }
    }
    return boxes;
}

/// Narrows \a r1 and \a r2 to where the two surfaces can meet; false: nowhere
bool restrictToMeeting(
    const Handle(Geom_Surface)& s1,
    Rect& r1,
    const Handle(Geom_Surface)& s2,
    Rect& r2
)
{
    const int k = TileCount;
    for (int level = 0; level < TileLevels; ++level) {
        const auto t1 = tileBoxes(s1, r1);
        const auto t2 = tileBoxes(s2, r2);
        int a0 = k, a1 = -1, b0 = k, b1 = -1, c0 = k, c1 = -1, d0 = k, d1 = -1;
        for (int i = 0; i < k * k; ++i) {
            for (int j = 0; j < k * k; ++j) {
                if (!t1[i].IsOut(t2[j])) {
                    a0 = std::min(a0, i / k);
                    a1 = std::max(a1, i / k);
                    b0 = std::min(b0, i % k);
                    b1 = std::max(b1, i % k);
                    c0 = std::min(c0, j / k);
                    c1 = std::max(c1, j / k);
                    d0 = std::min(d0, j % k);
                    d1 = std::max(d1, j % k);
                }
            }
        }
        if (a1 < 0) {
            return false;
        }
        const double du1 = (r1.u1 - r1.u0) / k;
        const double dv1 = (r1.v1 - r1.v0) / k;
        const double du2 = (r2.u1 - r2.u0) / k;
        const double dv2 = (r2.v1 - r2.v0) / k;
        r1 = {r1.u0 + a0 * du1, r1.u0 + (a1 + 1) * du1, r1.v0 + b0 * dv1, r1.v0 + (b1 + 1) * dv1};
        r2 = {r2.u0 + c0 * du2, r2.u0 + (c1 + 1) * du2, r2.v0 + d0 * dv2, r2.v0 + (d1 + 1) * dv2};
        const int kept = (a1 - a0 + 1) * (b1 - b0 + 1) + (c1 - c0 + 1) * (d1 - d0 + 1);
        if (kept > k * k) {
            break;  // little left to gain from another level
        }
    }
    return true;
}

void pad(Rect& r, const Rect& face)
{
    const double w = TilePad * (r.u1 - r.u0);
    const double h = TilePad * (r.v1 - r.v0);
    r = {std::max(face.u0, r.u0 - w),
         std::min(face.u1, r.u1 + w),
         std::max(face.v0, r.v0 - h),
         std::min(face.v1, r.v1 + h)};
}

bool analytic(GeomAbs_SurfaceType type)
{
    return type == GeomAbs_Plane || type == GeomAbs_Cylinder || type == GeomAbs_Cone
        || type == GeomAbs_Sphere || type == GeomAbs_Torus;
}

/// A face whose surface closes on itself, or that has a seam: not taken (the rectangle face and
/// the in-face test are not checked there)
bool closedOrSeamed(const TopoDS_Face& face, const BRepAdaptor_Surface& surface)
{
    if (surface.IsUClosed() || surface.IsVClosed() || surface.IsUPeriodic()
        || surface.IsVPeriodic()) {
        return true;
    }
    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
        if (BRep_Tool::IsClosed(TopoDS::Edge(it.Current()), face)) {
            return true;
        }
    }
    return false;
}

/// OCCT's ToleranceFF (BOPAlgo_PaveFiller_6.cxx): the pair's tolerance
double toleranceFF(const BRepAdaptor_Surface& a1, const BRepAdaptor_Surface& a2)
{
    double tol = std::max(a1.Tolerance(), a2.Tolerance());
    if (!analytic(a1.GetType()) || !analytic(a2.GetType())) {
        tol = std::max(tol, 5.e-6);
    }
    return tol;
}

/// Start points: where the signed distance from a grid on \a r1 of \a s1 to \a s2 (on \a r2)
/// changes sign, bisected onto both surfaces; border points first
NCollection_List<IntSurf_PntOn2S> startPoints(
    const Handle(Geom_Surface)& s1,
    const Rect& r1,
    const Handle(Geom_Surface)& s2,
    const Rect& r2,
    const gp_Trsf& toOrigin
)
{
    GeomAdaptor_Surface adaptor2(s2, r2.u0, r2.u1, r2.v0, r2.v1);
    double guessU = (r2.u0 + r2.u1) / 2;
    double guessV = (r2.v0 + r2.v1) / 2;
    bool haveGuess = false;
    double gap = 0;
    auto signedDistance = [&](double u, double v, double& u2, double& v2, double& distance) {
        const gp_Pnt p = s1->Value(u, v);
        bool found = false;
        if (haveGuess) {
            Extrema_GenLocateExtPS locate(adaptor2, 1e-10, 1e-10);
            locate.Perform(p, guessU, guessV);
            if (locate.IsDone()) {
                locate.Point().Parameter(u2, v2);
                found = u2 >= r2.u0 - 1e-12 && u2 <= r2.u1 + 1e-12 && v2 >= r2.v0 - 1e-12
                    && v2 <= r2.v1 + 1e-12;
            }
        }
        if (!found) {
            GeomAPI_ProjectPointOnSurf projection(p, s2, r2.u0, r2.u1, r2.v0, r2.v1);
            if (projection.NbPoints() == 0) {
                return false;
            }
            projection.LowerDistanceParameters(u2, v2);
        }
        guessU = u2;
        guessV = v2;
        haveGuess = true;
        gp_Pnt q;
        gp_Vec du;
        gp_Vec dv;
        s2->D1(u2, v2, q, du, dv);
        const gp_Vec normal = du.Crossed(dv);
        if (normal.Magnitude() < 1e-12) {
            return false;
        }
        gap = gp_Vec(q, p).Magnitude();
        distance = gp_Vec(q, p).Dot(normal.Normalized());
        return true;
    };
    const int n = SeedGrid;
    const std::size_t count = static_cast<std::size_t>(n + 1) * (n + 1);
    std::vector<double> distances(count, 0.0);
    std::vector<double> pu(count);
    std::vector<double> pv(count);
    std::vector<char> ok(count, 0);
    auto at = [&](int i, int j) {
        return static_cast<std::size_t>(i) * (n + 1) + j;
    };
    for (int i = 0; i <= n; ++i) {
        for (int j = 0; j <= n; ++j) {
            const std::size_t k = at(i, j);
            ok[k] = signedDistance(
                r1.u0 + (r1.u1 - r1.u0) * i / n,
                r1.v0 + (r1.v1 - r1.v0) * j / n,
                pu[k],
                pv[k],
                distances[k]
            );
        }
    }
    NCollection_List<IntSurf_PntOn2S> border;
    NCollection_List<IntSurf_PntOn2S> inner;
    auto seed = [&](int ia, int ja, int ib, int jb) {
        const std::size_t ka = at(ia, ja);
        const std::size_t kb = at(ib, jb);
        if (!ok[ka] || !ok[kb] || distances[ka] * distances[kb] >= 0
            || border.Extent() + inner.Extent() >= 4 * MaxSeeds) {
            return;
        }
        double ua = r1.u0 + (r1.u1 - r1.u0) * ia / n;
        double va = r1.v0 + (r1.v1 - r1.v0) * ja / n;
        double ub = r1.u0 + (r1.u1 - r1.u0) * ib / n;
        double vb = r1.v0 + (r1.v1 - r1.v0) * jb / n;
        double da = distances[ka];
        double u2 = 0;
        double v2 = 0;
        double dm = 0;
        double um = ua;
        double vm = va;
        for (int step = 0; step < BisectSteps; ++step) {
            um = (ua + ub) / 2;
            vm = (va + vb) / 2;
            if (!signedDistance(um, vm, u2, v2, dm)) {
                return;
            }
            if (dm == 0) {
                break;
            }
            if (dm * da > 0) {
                ua = um;
                va = vm;
                da = dm;
            }
            else {
                ub = um;
                vb = vm;
            }
        }
        if (std::fabs(dm) > 1e-9 || gap > 1e-8) {
            return;
        }
        IntSurf_PntOn2S point;
        point.SetValue(s1->Value(um, vm).Transformed(toOrigin), um, vm, u2, v2);
        auto onEdge = [](double x, double lo, double hi) {
            return std::fabs(x - lo) < 1e-9 * (hi - lo) || std::fabs(x - hi) < 1e-9 * (hi - lo);
        };
        const bool onBorder = onEdge(um, r1.u0, r1.u1) || onEdge(vm, r1.v0, r1.v1)
            || onEdge(u2, r2.u0, r2.u1) || onEdge(v2, r2.v0, r2.v1);
        (onBorder ? border : inner).Append(point);
    };
    for (int i = 0; i <= n; ++i) {
        for (int j = 0; j <= n; ++j) {
            if (i < n) {
                seed(i, j, i + 1, j);
            }
            if (j < n) {
                seed(i, j, i, j + 1);
            }
        }
    }
    for (const auto& point : inner) {
        if (border.Extent() >= MaxSeeds) {
            break;
        }
        border.Append(point);
    }
    return border;
}

class CrossingFiller: public BOPAlgo_PaveFiller
{
public:
    explicit CrossingFiller(const Handle(NCollection_BaseAllocator)& allocator)
        : BOPAlgo_PaveFiller(allocator)
    {}

    int retried = 0;    ///< pairs intersected again
    int recovered = 0;  ///< pairs that got a curve
    int curves = 0;     ///< curves added

protected:
    void PerformFF(const Message_ProgressRange& range) override
    {
        Message_ProgressScope scope(range, nullptr, 10);
        BOPAlgo_PaveFiller::PerformFF(scope.Next(9));
        if (HasErrors()) {
            return;
        }
        auto& pairs = myDS->InterfFF();
        Message_ProgressScope retries(scope.Next(), nullptr, std::max(pairs.Length(), 1));
        for (int k = 0; k < pairs.Length(); ++k, retries.Next()) {
            if (UserBreak(retries)) {
                return;
            }
            BOPDS_InterfFF& pair = pairs.ChangeValue(k);
            if (pair.Curves().Length() > 0 || pair.Points().Length() > 0 || pair.TangentFaces()) {
                continue;
            }
            int n1 = 0;
            int n2 = 0;
            pair.Indices(n1, n2);
            try {
                OCC_CATCH_SIGNALS
                recover(pair, n1, n2);
            }
            catch (const Standard_Failure&) {
                // left as OCCT found it
            }
        }
    }

private:
    void recover(BOPDS_InterfFF& pair, int n1, int n2)
    {
        const TopoDS_Face f1 = TopoDS::Face(myDS->Shape(n1));
        const TopoDS_Face f2 = TopoDS::Face(myDS->Shape(n2));
        BRepAdaptor_Surface a1(f1, false);
        BRepAdaptor_Surface a2(f2, false);
        if (analytic(a1.GetType()) && analytic(a2.GetType())) {
            return;
        }
        if (closedOrSeamed(f1, a1) || closedOrSeamed(f2, a2)) {
            return;
        }
        Rect face1 {};
        Rect face2 {};
        BRepTools::UVBounds(f1, face1.u0, face1.u1, face1.v0, face1.v1);
        BRepTools::UVBounds(f2, face2.u0, face2.u1, face2.v0, face2.v1);
        if (face1.area() <= 0 || face2.area() <= 0) {
            return;
        }
        // BRep_Tool::Surface(face): the surface with the face's location applied
        const Handle(Geom_Surface) s1 = BRep_Tool::Surface(f1);
        const Handle(Geom_Surface) s2 = BRep_Tool::Surface(f2);
        Rect r1 = face1;
        Rect r2 = face2;
        if (!restrictToMeeting(s1, r1, s2, r2)) {
            return;
        }
        if (r1.area() / face1.area() > 0.5 && r2.area() / face2.area() > 0.5) {
            return;  // the same question OCCT answered
        }
        ++retried;
        pad(r1, face1);
        pad(r2, face2);
        // Far from the origin, intersect near it, as PerformFF does (BOPAlgo_FaceFace::Perform)
        gp_Trsf toOrigin;
        const bool moved = BOPAlgo_Tools::TrsfToPoint(
            myDS->ShapeInfo(n1).Box(),
            myDS->ShapeInfo(n2).Box(),
            toOrigin
        );
        TopoDS_Face g1 = BRepBuilderAPI_MakeFace(s1, r1.u0, r1.u1, r1.v0, r1.v1, Precision::Confusion());
        TopoDS_Face g2 = BRepBuilderAPI_MakeFace(s2, r2.u0, r2.u1, r2.v0, r2.v1, Precision::Confusion());
        if (moved) {
            g1.Move(TopLoc_Location(toOrigin));
            g2.Move(TopLoc_Location(toOrigin));
        }
        const double tolFF = toleranceFF(a1, a2);
        const double boxExpand = tolFF
            + std::max(BRep_Tool::MaxTolerance(f1, TopAbs_VERTEX),
                       BRep_Tool::MaxTolerance(f2, TopAbs_VERTEX));
        int added = 0;
        for (int attempt = 0; attempt < 2 && added == 0; ++attempt) {
            IntTools_FaceFace intersector;
            intersector.SetParameters(true, true, true, 1.e-7);
            intersector.SetFuzzyValue(0.0);
            if (attempt == 1) {
                NCollection_List<IntSurf_PntOn2S> seeds =
                    startPoints(s1, r1, s2, r2, moved ? toOrigin : gp_Trsf());
                if (seeds.IsEmpty()) {
                    break;
                }
                intersector.SetList(seeds);
            }
            intersector.Perform(g1, g2, false);
            if (!intersector.IsDone()) {
                continue;
            }
            intersector.PrepareLines3D(false);
            const auto& lines = intersector.Lines();
            for (int i = 1; i <= lines.Length(); ++i) {
                IntTools_Curve curve = lines(i);
                if (moved) {
                    curve.Curve()->Transform(toOrigin.Inverted());
                }
                Bnd_Box box;
                if (!IntTools_Tools::CheckCurve(curve, box)) {
                    continue;
                }
                if (!crossesBoth(curve, f1, f2)) {
                    continue;
                }
                BOPDS_Curve& kept = pair.ChangeCurves().Appended();
                kept.SetCurve(curve);
                box.Enlarge(boxExpand);
                kept.SetBox(box);
                kept.SetTolerance(std::max(curve.Tolerance(), tolFF));
                ++added;
            }
        }
        if (added > 0) {
            myDS->AddInterf(n1, n2);
            ++recovered;
            curves += added;
        }
    }

    /// A point of \a curve lies strictly inside both faces
    bool crossesBoth(const IntTools_Curve& curve, const TopoDS_Face& f1, const TopoDS_Face& f2)
    {
        const Handle(Geom_Curve)& c = curve.Curve();
        const double first = c->FirstParameter();
        const double last = c->LastParameter();
        for (double t : {0.5, 0.25, 0.75}) {
            const gp_Pnt p = c->Value(first + (last - first) * t);
            bool inside = true;
            for (const TopoDS_Face* face : {&f1, &f2}) {
                GeomAPI_ProjectPointOnSurf projection(p, BRep_Tool::Surface(*face));
                if (projection.NbPoints() == 0) {
                    inside = false;
                    break;
                }
                double u = 0;
                double v = 0;
                projection.LowerDistanceParameters(u, v);
                if (myContext->FClass2d(*face).Perform(gp_Pnt2d(u, v)) != TopAbs_IN) {
                    inside = false;
                    break;
                }
            }
            if (inside) {
                return true;
            }
        }
        return false;
    }
};

}  // namespace

FCBRepAlgoAPI_BooleanOperation::FCBRepAlgoAPI_BooleanOperation()
{
    SetRunParallel(Standard_True);
    SetNonDestructive(Standard_True);
}


FCBRepAlgoAPI_BooleanOperation::FCBRepAlgoAPI_BooleanOperation(
    const TopoDS_Shape& theS1,
    const TopoDS_Shape& theS2,
    const BOPAlgo_Operation theOperation
)
    : BRepAlgoAPI_BooleanOperation(theS1, theS2, theOperation)
{
    if (!BRepCheck_Analyzer(theS1).IsValid()) {
        Base::Console().warning("Base shape is not valid for boolean operation");
    }

    if (!BRepCheck_Analyzer(theS2).IsValid()) {
        Base::Console().warning("Tool shape is not valid for boolean operation");
    }

    setAutoFuzzy();
    SetRunParallel(Standard_True);
    SetNonDestructive(Standard_True);
}

void FCBRepAlgoAPI_BooleanOperation::setAutoFuzzy()
{
    FCBRepAlgoAPIHelper::setAutoFuzzy(this);
}


void FCBRepAlgoAPIHelper::setAutoFuzzy(BRepAlgoAPI_BooleanOperation* op)
{
    Bnd_Box bounds;
    for (TopTools_ListOfShape::Iterator it(op->Arguments()); it.More(); it.Next()) {
        BRepBndLib::Add(it.Value(), bounds);
    }
    for (TopTools_ListOfShape::Iterator it(op->Tools()); it.More(); it.Next()) {
        BRepBndLib::Add(it.Value(), bounds);
    }
    op->SetFuzzyValue(
        Part::FuzzyHelper::getBooleanFuzzy() * sqrt(bounds.SquareExtent()) * Precision::Confusion()
    );
}

void FCBRepAlgoAPIHelper::setAutoFuzzy(BRepAlgoAPI_BuilderAlgo* op)
{
    Bnd_Box bounds;
    for (TopTools_ListOfShape::Iterator it(op->Arguments()); it.More(); it.Next()) {
        BRepBndLib::Add(it.Value(), bounds);
    }
    op->SetFuzzyValue(
        Part::FuzzyHelper::getBooleanFuzzy() * sqrt(bounds.SquareExtent()) * Precision::Confusion()
    );
}

void FCBRepAlgoAPIHelper::refuseFacesWithoutWidth(const TopTools_ListOfShape& shapes)
{
    TopTools_IndexedMapOfShape faces;
    for (TopTools_ListOfShape::Iterator it(shapes); it.More(); it.Next()) {
        TopExp::MapShapes(it.Value(), TopAbs_FACE, faces);
    }
    for (int i = 1; i <= faces.Extent(); ++i) {
        const TopoDS_Face& face = TopoDS::Face(faces(i));
        TopLoc_Location location;
        const Handle(Geom_Surface)& surface = BRep_Tool::Surface(face, location);
        if (surface.IsNull()) {
            continue;
        }
        const GeomAbs_SurfaceType type = GeomAdaptor_Surface(surface).GetType();
        if (type == GeomAbs_Plane || type == GeomAbs_Cylinder) {
            continue;
        }
        double u0 = 0.0, u1 = 0.0, v0 = 0.0, v1 = 0.0;
        BRepTools::UVBounds(face, u0, u1, v0, v1);
        // Also a range that is NaN or reversed
        if (!(u1 - u0 >= Precision::PConfusion()) || !(v1 - v0 >= Precision::PConfusion())) {
            throw Standard_ConstructionError(
                "an input has a face of no width (no area), on which OCCT's intersection would "
                "not end"
            );
        }
    }
}

namespace
{
/// The solids of the shapes in \a list, also inside compounds and compsolids
std::vector<TopoDS_Shape> solidsOf(const TopTools_ListOfShape& list)
{
    std::vector<TopoDS_Shape> solids;
    for (TopTools_ListOfShape::Iterator it(list); it.More(); it.Next()) {
        for (TopExp_Explorer xp(it.Value(), TopAbs_SOLID); xp.More(); xp.Next()) {
            solids.push_back(xp.Current());
        }
    }
    return solids;
}

/// The shapes that aren't compounds in \a shape's compound tree, as Build's piecewise paths count
/// them (RecursiveCutCompound, RecursiveAddTools)
int leafCount(const TopoDS_Shape& shape)
{
    if (shape.ShapeType() != TopAbs_COMPOUND) {
        return 1;
    }
    int count = 0;
    for (TopoDS_Iterator it(shape); it.More(); it.Next()) {
        count += leafCount(it.Value());
    }
    return count;
}

/// Whether the boolean left no trace of \a tool: every face deleted, as a cut that removed nothing
/// leaves them (a void's faces stay, reversed), or every face kept unchanged, as a fuse that
/// merged nothing leaves them
bool leftNoTrace(BRepAlgoAPI_BooleanOperation* op, const TopoDS_Shape& tool, bool deleted)
{
    TopExp_Explorer xp(tool, TopAbs_FACE);
    if (!xp.More()) {
        return false;
    }
    for (; xp.More(); xp.Next()) {
        if (!op->Modified(xp.Current()).IsEmpty() || op->IsDeleted(xp.Current()) != deleted) {
            return false;
        }
    }
    return true;
}

/// Whether \a tool, which left no trace, overlaps the material of \a solid, by two independent
/// witnesses: a vertex of the tool classifies IN the solid, and the screened volume of their
/// common part is more than a millionth of the tool's (OCCT's Common is right where the solid
/// builder fails, ops#472). The first vertex not ON the solid's boundary decides, as such a tool
/// lies wholly in the material or wholly outside it (a vertex may touch the boundary), and each
/// classification costs about 0.1 s on a 1000-span face. The boxes are the caller's, each made once
/// (perf profile 4, ops#640: made per pair, a fuse of 200 separate solids made 40,000 of them)
bool overlaps(
    const TopoDS_Shape& solid,
    const Bnd_Box& solidBounds,
    const TopoDS_Shape& tool,
    const Bnd_Box& toolBounds,
    double fuzzy
)
{
    if (solidBounds.IsOut(toolBounds)) {
        return false;
    }
    TopTools_IndexedMapOfShape vertices;
    TopExp::MapShapes(tool, TopAbs_VERTEX, vertices);
    BRepClass3d_SolidClassifier classifier(solid);
    TopAbs_State state = TopAbs_ON;
    for (int i = 1; i <= vertices.Extent() && state == TopAbs_ON; ++i) {
        classifier.Perform(BRep_Tool::Pnt(TopoDS::Vertex(vertices(i))), Precision::Confusion());
        state = classifier.State();
    }
    if (state != TopAbs_IN) {
        return false;
    }
    BRepAlgoAPI_Common common;
    TopTools_ListOfShape arguments, tools;
    arguments.Append(solid);
    tools.Append(tool);
    common.SetArguments(arguments);
    common.SetTools(tools);
    common.SetFuzzyValue(fuzzy);
    common.Build();
    if (!common.IsDone()) {
        return false;
    }
    return Part::MassProperties::volume(common.Shape())
        > 1e-6 * std::abs(Part::MassProperties::volume(tool));
}
}  // namespace

void FCBRepAlgoAPIHelper::checkLostTools(BRepAlgoAPI_BooleanOperation* op)
{
    const bool cut = op->Operation() == BOPAlgo_CUT;
    if ((!cut && op->Operation() != BOPAlgo_FUSE) || !op->IsDone() || !op->HasHistory()) {
        return;
    }
    // FCBRepAlgoAPI_BooleanOperation::Build cuts a lone compound argument one leaf at a time, and
    // fuses the leaves of a lone compound tool before the cut: the history then covers only the
    // last build, so those cuts aren't checked yet (ops#472). A compound of one leaf, which every
    // boolean and PartDesign feature returns, takes one build and is checked
    if (cut && op->Arguments().Size() == 1
        && (leafCount(op->Arguments().First()) > 1
            || (op->Tools().Size() == 1 && leafCount(op->Tools().First()) > 1))) {
        return;
    }
    const std::vector<TopoDS_Shape> bases = solidsOf(op->Arguments());
    const std::vector<TopoDS_Shape> tools = solidsOf(op->Tools());
    if (bases.empty() || tools.empty()) {
        return;
    }
    std::vector<TopoDS_Shape> results;
    for (TopExp_Explorer xp(op->Shape(), TopAbs_SOLID); xp.More(); xp.Next()) {
        results.push_back(xp.Current());
    }
    // A fuse that kept a tool whole has more solids than its base, else it merged nothing
    if (!cut && results.size() <= bases.size()) {
        return;
    }
    // Each solid's box, made when first needed
    struct Boxed
    {
        TopoDS_Shape shape;
        Bnd_Box box;
        bool made = false;
        const Bnd_Box& bounds()
        {
            if (!made) {
                BRepBndLib::Add(shape, box);
                made = true;
            }
            return box;
        }
    };
    auto boxed = [](const std::vector<TopoDS_Shape>& shapes) {
        std::vector<Boxed> out;
        out.reserve(shapes.size());
        for (const auto& shape : shapes) {
            out.push_back({shape, Bnd_Box(), false});
        }
        return out;
    };
    std::vector<Boxed> boxedTools = boxed(tools);
    std::vector<Boxed> boxedOthers = boxed(cut ? results : bases);
    for (auto& tool : boxedTools) {
        if (!leftNoTrace(op, tool.shape, cut)) {
            continue;
        }
        // A cut that removed nothing lost the tool if the result still has material where the
        // tool is (a tool outside the base, or inside another tool, has none). A fuse that merged
        // nothing lost it if the tool lies in the material of the base or of another tool
        std::vector<Boxed*> others;
        for (auto& other : boxedOthers) {
            others.push_back(&other);
        }
        if (!cut) {
            for (auto& other : boxedTools) {
                if (!other.shape.IsSame(tool.shape)) {
                    others.push_back(&other);
                }
            }
        }
        for (Boxed* other : others) {
            if (overlaps(
                    other->shape,
                    other->bounds(),
                    tool.shape,
                    tool.bounds(),
                    op->FuzzyValue()
                )) {
                throw Base::CADKernelError(
                    cut ? "Cut failed: a tool solid lies inside the base, but the result lost its "
                          "cavity (OCCT solid builder fault, ops#472)"
                        : "Fuse failed: a tool solid lies inside the base, but the result kept it "
                          "as a separate overlapping solid (OCCT solid builder fault, ops#472)"
                );
            }
        }
    }
}

namespace
{
/// The protected state of the base Boolean, reached through a derived class
struct BooleanAccess: FCBRepAlgoAPI_BooleanOperation
{
    /** FreeCAD-CH ops#901: \a op built with a CrossingFiller in place of OCCT's own intersection.
     * The filler takes the options OCCT's IntersectShapes gives its own; the base Build then
     * skips the intersection (myIsIntersectionNeeded false) and builds from it. Owned by the
     * operation afterwards: with the flag set back, the next Build's Clear() or the destructor
     * deletes it, as it deletes OCCT's own. A filler that fails falls back to OCCT's path. */
    static void build(FCBRepAlgoAPI_BooleanOperation* op, const Message_ProgressRange& range)
    {
        auto* self = static_cast<BooleanAccess*>(op);
        self->Clear();
        TopTools_ListOfShape all = self->myArguments;
        for (TopTools_ListOfShape::Iterator it(self->myTools); it.More(); it.Next()) {
            all.Append(it.Value());
        }
        Message_ProgressScope scope(range, nullptr, 10);
        auto* filler = new CrossingFiller(self->myAllocator);
        filler->SetArguments(all);
        filler->SetRunParallel(self->myRunParallel);
        filler->SetFuzzyValue(self->myFuzzyValue);
        filler->SetNonDestructive(self->myNonDestructive);
        filler->SetGlue(self->myGlue);
        filler->SetUseOBB(self->myUseOBB);
        filler->Perform(scope.Next(7));
        if (filler->HasErrors()) {
            delete filler;
            self->myDSFiller = nullptr;
            self->myIsIntersectionNeeded = true;
            self->BRepAlgoAPI_BooleanOperation::Build(scope.Next(3));
            return;
        }
        if (filler->retried > 0) {
            Base::Console().log(
                "Boolean: %d face pairs intersected again, %d with crossings, %d curves (ops#901)\n",
                filler->retried,
                filler->recovered,
                filler->curves
            );
        }
        self->myDSFiller = filler;
        self->myIsIntersectionNeeded = false;
        self->BRepAlgoAPI_BooleanOperation::Build(scope.Next(3));
        self->myIsIntersectionNeeded = true;
        self->GetReport()->Merge(filler->GetReport());
    }
};

void buildRecoveringCrossings(FCBRepAlgoAPI_BooleanOperation* op, const Message_ProgressRange& range)
{
    BooleanAccess::build(op, range);
}
}  // namespace

void FCBRepAlgoAPI_BooleanOperation::Build()
{
    Message_ProgressRange progressRange;
    Build(progressRange);
}

void FCBRepAlgoAPI_BooleanOperation::Build(const Message_ProgressRange& progressRange)
{
    Part::SignalException sig;
    if (progressRange.UserBreak()) {
        throw Standard_ConstructionError("User aborted");
    }
    if (myOperation == BOPAlgo_CUT && myArguments.Size() == 1 && myTools.Size() == 1
        && myTools.First().ShapeType() == TopAbs_COMPOUND) {
        // cut argument and compound tool
        TopTools_ListOfShape myOriginalArguments = myArguments;
        TopTools_ListOfShape myOriginalTools = myTools;
        RecursiveCutFusedTools(myOriginalArguments, myOriginalTools.First(), progressRange);
        myArguments = myOriginalArguments;
        myTools = myOriginalTools;
    }
    else if (
        myOperation == BOPAlgo_CUT && myArguments.Size() == 1
        && myArguments.First().ShapeType() == TopAbs_COMPOUND
    ) {
        // cut compound argument
        TopTools_ListOfShape myOriginalArguments = myArguments;
        RecursiveCutCompound(myOriginalArguments.First(), progressRange);
        myArguments = myOriginalArguments;
    }
    else {
        // The pieces of the two paths above come here one by one
        FCBRepAlgoAPIHelper::refuseFacesWithoutWidth(myArguments);
        FCBRepAlgoAPIHelper::refuseFacesWithoutWidth(myTools);
        if (Part::FuzzyHelper::getCrossingRecovery() && myOperation != BOPAlgo_SECTION) {
            buildRecoveringCrossings(this, progressRange);
        }
        else
#if OCC_VERSION_HEX >= 0x070600
        {
            BRepAlgoAPI_BooleanOperation::Build(progressRange);
        }
#else
        BRepAlgoAPI_BooleanOperation::Build();
#endif
    }
    if (progressRange.UserBreak()) {
        throw Standard_ConstructionError("User aborted");
    }
}

void FCBRepAlgoAPI_BooleanOperation::RecursiveAddTools(const TopoDS_Shape& theTool)
{
    TopoDS_Iterator it(theTool);
    for (; it.More(); it.Next()) {
        if (it.Value().ShapeType() == TopAbs_COMPOUND) {
            RecursiveAddTools(it.Value());
        }
        else {
            myTools.Append(it.Value());
        }
    }
}

void FCBRepAlgoAPI_BooleanOperation::RecursiveCutFusedTools(
    const TopTools_ListOfShape& theOriginalArguments,
    const TopoDS_Shape& theTool,
    const Message_ProgressRange& progressRange
)
{
    // The fuse and the cut each get a part of the caller's range, so that a cancel (the kernel
    // budget's time limit, Esc) stops them too (ops#773): a Build() without one never reads it
    Message_ProgressScope scope(progressRange, "Cut by fused tools", 2);
    // get a list of shapes in the tool compound
    myTools.Clear();
    RecursiveAddTools(theTool);

    // if tool consists of two or more shapes, fuse them together
    if (myTools.Size() >= 2) {
        myArguments.Clear();
        myArguments.Append(myTools.First());
        myTools.RemoveFirst();
        myOperation = BOPAlgo_FUSE;
        Build(scope.Next());

        // restore original state
        myOperation = BOPAlgo_CUT;
        myArguments = theOriginalArguments;

        if (!IsDone()) {
            myShape = {};
            return;
        }

        // use fused shape as new tool
        // if the original tools didn't all touch, the fused shape will be a compound
        // which we convert into a list of shapes so we don't attempt to fuse them again
        myTools.Clear();
        RecursiveAddTools(myShape);
    }

    // do the cut
    Build(scope.Next());
}

void FCBRepAlgoAPI_BooleanOperation::RecursiveCutCompound(
    const TopoDS_Shape& theArgument,
    const Message_ProgressRange& progressRange
)
{
    BRep_Builder builder;
    TopoDS_Compound comp;
    builder.MakeCompound(comp);

    // Each piece's cut gets a part of the caller's range, as in RecursiveCutFusedTools (ops#773)
    int pieces = 0;
    for (TopoDS_Iterator count(theArgument); count.More(); count.Next()) {
        ++pieces;
    }
    Message_ProgressScope scope(progressRange, "Cut of a compound", std::max(pieces, 1));
    // iterate through shapes in argument compound and cut each one with the tool
    TopoDS_Iterator it(theArgument);
    for (; it.More(); it.Next()) {
        myArguments.Clear();
        myArguments.Append(it.Value());
        Build(scope.Next());

        if (!IsDone()) {
            myShape = {};
            return;
        }

        builder.Add(comp, myShape);
    }

    // result is a compound of individual cuts
    myShape = comp;
}
