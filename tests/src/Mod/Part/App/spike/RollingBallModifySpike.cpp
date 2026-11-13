// killtest2 (decision 425, kill test 2): a designed model (stadium prism under a twisted B-spline lid, OCCT's fillet
// round the top: plane/lid and cylinder/lid blends in one closed G1 chain). The blend faces' geometry is replaced by the
// Newton-ball surface and the seam vertices slide along their untouched edges (the plane/cylinder tangent lines), all
// through one BRepTools_Modification. Then: BRepCheck, tolerances, same-parameter deviation, ball residual.
// Standalone: pure OCCT, no FreeCAD, not in any CMake target. Build line: work/killtest2/build.sh on the Mac (one clang++
// call against the pixi environment's OCCT 8.0.1). Arguments: radius, twist, stations per face, K mode (1: the untouched
// tangent edge only answers NewParameter). Result 2026-11-13 (ops#640): PASS, see notes/rolling-ball-killtests.md.
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_ModifyShape.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepLib.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepTools.hxx>
#include <BRepTools_Modification.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GProp_GProps.hxx>
#include <Geom2dAPI_Interpolate.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_Line.hxx>
#include <Geom_Plane.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <ShapeAnalysis_Edge.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <TColStd_HArray1OfReal.hxx>
#include <TColgp_Array1OfPnt2d.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TColgp_HArray1OfPnt2d.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Pln.hxx>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <vector>

static double R = 1.5;       // the fillet radius
static double TWIST = 0.02;  // lid: z = 20 + TWIST x y
static int NST = 81;         // stations per blend face
static int KMODE = 0;        // 0: K is given back as a new curve (the same one); 1: K only answers NewParameter

static Handle(Geom_Surface) untrimmed(Handle(Geom_Surface) s)
{
    while (s->IsKind(STANDARD_TYPE(Geom_RectangularTrimmedSurface))) {
        s = Handle(Geom_RectangularTrimmedSurface)::DownCast(s)->BasisSurface();
    }
    return s;
}

struct Foot
{
    gp_Pnt q;
    double u = 0, v = 0, d = 0;
    gp_Vec g;  // unit, from the foot to the point
};

// The foot of c on the untrimmed surface: Newton on (u, v) with second derivatives
static Foot foot(const Handle(Geom_Surface)& S, const gp_Pnt& c, const double* hint = nullptr)
{
    Foot f;
    if (hint) {
        f.u = hint[0];
        f.v = hint[1];
    }
    else {
        GeomAPI_ProjectPointOnSurf pr(c, S);
        if (pr.NbPoints() < 1) {
            printf("FATAL no projection\n");
            exit(3);
        }
        pr.LowerDistanceParameters(f.u, f.v);
    }
    gp_Pnt p;
    gp_Vec su, sv, suu, svv, suv;
    for (int it = 0; it < 40; ++it) {
        S->D2(f.u, f.v, p, su, sv, suu, svv, suv);
        const gp_Vec r(c, p);
        const double f1 = r.Dot(su), f2 = r.Dot(sv);
        const double a = su.Dot(su) + r.Dot(suu), b = su.Dot(sv) + r.Dot(suv), d = sv.Dot(sv) + r.Dot(svv);
        const double det = a * d - b * b;
        const double du = (-f1 * d + f2 * b) / det, dv = (-f2 * a + f1 * b) / det;
        f.u += du;
        f.v += dv;
        if (std::fabs(du) * su.Magnitude() + std::fabs(dv) * sv.Magnitude() < 1e-14) {
            break;
        }
    }
    f.q = S->Value(f.u, f.v);
    f.g = gp_Vec(f.q, c);
    f.d = f.g.Magnitude();
    f.g /= f.d;
    return f;
}

struct Station
{
    gp_Pnt c;
    Foot a, b;  // a: on the side wall, b: on the lid
    int it = 0;
    double res = 0;
    double t = 0;
};

// Newton for the ball centre: |c - S1| = r, |c - S2| = r, (c - o) . n = 0
static Station solveStation(gp_Pnt c,
                            const Handle(Geom_Surface)& S1,
                            const Handle(Geom_Surface)& S2,
                            const gp_Pnt& o,
                            const gp_Vec& n,
                            const Station* warm = nullptr)
{
    Station s;
    double h1[2], h2[2];
    bool hasHint = warm != nullptr;
    if (warm) {
        h1[0] = warm->a.u, h1[1] = warm->a.v, h2[0] = warm->b.u, h2[1] = warm->b.v;
    }
    for (int it = 0; it <= 40; ++it) {
        s.a = foot(S1, c, hasHint ? h1 : nullptr);
        s.b = foot(S2, c, hasHint ? h2 : nullptr);
        h1[0] = s.a.u, h1[1] = s.a.v, h2[0] = s.b.u, h2[1] = s.b.v;
        hasHint = true;
        const double F[3] = {s.a.d - R, s.b.d - R, gp_Vec(o, c).Dot(n)};
        s.res = std::max({std::fabs(F[0]), std::fabs(F[1]), std::fabs(F[2])});
        s.it = it;
        if (s.res < 3e-13 || it == 40) {
            break;
        }
        gp_Mat J(s.a.g.X(), s.a.g.Y(), s.a.g.Z(), s.b.g.X(), s.b.g.Y(), s.b.g.Z(), n.X(), n.Y(), n.Z());
        const gp_XYZ dc = J.Inverted() * gp_XYZ(-F[0], -F[1], -F[2]);
        c.SetXYZ(c.XYZ() + dc);
    }
    s.c = c;
    return s;
}

static Handle(Geom2d_BSplineCurve) segment2d(const gp_Pnt2d& p0, const gp_Pnt2d& p1, double a, double b)
{
    TColgp_Array1OfPnt2d poles(1, 2);
    poles(1) = p0;
    poles(2) = p1;
    TColStd_Array1OfReal knots(1, 2);
    knots(1) = a;
    knots(2) = b;
    TColStd_Array1OfInteger mults(1, 2);
    mults(1) = 2;
    mults(2) = 2;
    return new Geom2d_BSplineCurve(poles, knots, mults, 1);
}

struct EdgeNew
{
    Handle(Geom_Curve) c;
    TopoDS_Vertex vf;  // the edge's FORWARD vertex
    double pf = 0, pl = 0;
};

struct Blend
{
    TopoDS_Face f, wall;
    Handle(Geom_Surface) sWall, sOld;
    bool isCyl = false;
    TopoDS_Edge eWall, eLid;
    int seam[2] = {-1, -1};  // at v = 0 and at v = length
    std::vector<Station> st;
    std::vector<gp_Pnt> centres;  // of OCCT's own sections, the Newton starts
    Handle(Geom_BSplineSurface) S;
    double length = 0;
};

struct Seam
{
    TopoDS_Edge e, K;
    TopoDS_Vertex vK, vL;
    int bPlane = -1, bCyl = -1;
    gp_Pnt o;  // on K
    gp_Vec n;  // the split plane's normal
    Station st;
};

class BallModification: public BRepTools_Modification
{
public:
    std::map<const TopoDS_TShape*, Handle(Geom_Surface)> surfaces;
    std::map<const TopoDS_TShape*, EdgeNew> curves;
    std::map<const TopoDS_TShape*, EdgeNew> slides;  // untouched edges whose vertex slides
    std::map<std::pair<const TopoDS_TShape*, const TopoDS_TShape*>, Handle(Geom2d_Curve)> pcurves;
    std::map<const TopoDS_TShape*, gp_Pnt> points;
    double tol = 1e-7;

    bool NewSurface(const TopoDS_Face& F, Handle(Geom_Surface)& S, TopLoc_Location& L, double& Tol, bool& RevWires, bool& RevFace) override
    {
        const auto it = surfaces.find(F.TShape().get());
        if (it == surfaces.end()) {
            return false;
        }
        S = it->second;
        L = TopLoc_Location();
        Tol = tol;
        RevWires = false;
        RevFace = false;
        return true;
    }
    bool NewCurve(const TopoDS_Edge& E, Handle(Geom_Curve)& C, TopLoc_Location& L, double& Tol) override
    {
        const auto it = curves.find(E.TShape().get());
        if (it == curves.end()) {
            return false;
        }
        C = it->second.c;
        L = TopLoc_Location();
        Tol = tol;
        return true;
    }
    bool NewPoint(const TopoDS_Vertex& V, gp_Pnt& P, double& Tol) override
    {
        const auto it = points.find(V.TShape().get());
        if (it == points.end()) {
            return false;
        }
        P = it->second;
        Tol = tol;
        return true;
    }
    bool NewCurve2d(const TopoDS_Edge& E, const TopoDS_Face& F, const TopoDS_Edge&, const TopoDS_Face&, Handle(Geom2d_Curve)& C, double& Tol) override
    {
        const auto it = pcurves.find({E.TShape().get(), F.TShape().get()});
        if (it == pcurves.end()) {
            if (curves.count(E.TShape().get())) {
                printf("WARN NewCurve2d: a new edge without a pcurve on one of its faces\n");
            }
            return false;
        }
        C = it->second;
        Tol = tol;
        return true;
    }
    bool NewParameter(const TopoDS_Vertex& V, const TopoDS_Edge& E, double& P, double& Tol) override
    {
        auto it = curves.find(E.TShape().get());
        if (it == curves.end()) {
            it = slides.find(E.TShape().get());
            if (it == slides.end()) {
                return false;
            }
        }
        P = V.IsSame(it->second.vf) ? it->second.pf : it->second.pl;
        Tol = tol;
        return true;
    }
    GeomAbs_Shape Continuity(const TopoDS_Edge& E, const TopoDS_Face& F1, const TopoDS_Face& F2, const TopoDS_Edge&, const TopoDS_Face&, const TopoDS_Face&) override
    {
        return BRep_Tool::Continuity(E, F1, F2);
    }
};

class Maker: public BRepBuilderAPI_ModifyShape
{
public:
    Maker(const TopoDS_Shape& shape, const Handle(BRepTools_Modification)& modification)
    {
        myModification = modification;
        DoModif(shape);
    }
};

struct Tols
{
    double v = 0, e = 0, f = 0;
};
static Tols maxTol(const TopoDS_Shape& s)
{
    Tols t;
    for (TopExp_Explorer x(s, TopAbs_VERTEX); x.More(); x.Next()) t.v = std::max(t.v, BRep_Tool::Tolerance(TopoDS::Vertex(x.Current())));
    for (TopExp_Explorer x(s, TopAbs_EDGE); x.More(); x.Next()) t.e = std::max(t.e, BRep_Tool::Tolerance(TopoDS::Edge(x.Current())));
    for (TopExp_Explorer x(s, TopAbs_FACE); x.More(); x.Next()) t.f = std::max(t.f, BRep_Tool::Tolerance(TopoDS::Face(x.Current())));
    return t;
}
static double volume(const TopoDS_Shape& s)
{
    GProp_GProps g;
    BRepGProp::VolumeProperties(s, g);
    return g.Mass();
}
static double area(const TopoDS_Shape& s)
{
    GProp_GProps g;
    BRepGProp::SurfaceProperties(s, g);
    return g.Mass();
}

// The ball residual of a blend face: centre = p -/+ r n at distance r from both untrimmed walls
static void ballResidual(const TopoDS_Face& face, const Handle(Geom_Surface)& w1, const Handle(Geom_Surface)& w2, double& worst, double& mean)
{
    const Handle(Geom_Surface) S = BRep_Tool::Surface(face);
    double u0, u1, v0, v1;
    BRepTools::UVBounds(face, u0, u1, v0, v1);
    worst = 0;
    mean = 0;
    int n = 0;
    for (int i = 0; i <= 8; ++i) {
        for (int j = 0; j <= 160; ++j) {
            const double u = u0 + (u1 - u0) * (i + 0.5) / 9.5 * 0.999 + (u1 - u0) * 0.0005, v = v0 + (v1 - v0) * (j + 0.25) / 160.5;
            gp_Pnt p;
            gp_Vec du, dv;
            S->D1(u, v, p, du, dv);
            gp_Vec nn = du.Crossed(dv);
            nn.Normalize();
            double best = 1e9;
            for (double sg : {-1.0, 1.0}) {
                const gp_Pnt c = p.Translated(nn * (sg * R));
                const double r = std::max(std::fabs(foot(w1, c).d - R), std::fabs(foot(w2, c).d - R));
                best = std::min(best, r);
            }
            worst = std::max(worst, best);
            mean += best;
            ++n;
        }
    }
    mean /= n;
}

int main(int argc, char** argv)
{
    if (argc > 1) R = atof(argv[1]);
    if (argc > 2) TWIST = atof(argv[2]);
    if (argc > 3) NST = atoi(argv[3]);
    if (argc > 4) KMODE = atoi(argv[4]);
    printf("KT2 r %.4f twist %.4f stations %d kmode %d\n", R, TWIST, NST, KMODE);

    // ---- the designed model
    const gp_Pnt a1(-20, -10, 0), a2(20, -10, 0), a3(20, 10, 0), a4(-20, 10, 0);
    BRepBuilderAPI_MakeWire mw;
    mw.Add(BRepBuilderAPI_MakeEdge(a1, a2).Edge());
    mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(a2, gp_Pnt(30, 0, 0), a3).Value()).Edge());
    mw.Add(BRepBuilderAPI_MakeEdge(a3, a4).Edge());
    mw.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(a4, gp_Pnt(-30, 0, 0), a1).Value()).Edge());
    const TopoDS_Shape prism = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(mw.Wire()).Face(), gp_Vec(0, 0, 40)).Shape();
    TColgp_Array2OfPnt lp(1, 2, 1, 2);
    const double X = 45, Y = 25;
    lp(1, 1) = gp_Pnt(-X, -Y, 20 + TWIST * X * Y);
    lp(2, 1) = gp_Pnt(X, -Y, 20 - TWIST * X * Y);
    lp(1, 2) = gp_Pnt(-X, Y, 20 - TWIST * X * Y);
    lp(2, 2) = gp_Pnt(X, Y, 20 + TWIST * X * Y);
    TColStd_Array1OfReal k2(1, 2);
    k2(1) = 0;
    k2(2) = 1;
    TColStd_Array1OfInteger m2(1, 2);
    m2(1) = 2;
    m2(2) = 2;
    Handle(Geom_BSplineSurface) lidSurface = new Geom_BSplineSurface(lp, k2, k2, m2, m2, 1, 1);
    lidSurface->IncreaseDegree(3, 3);
    const TopoDS_Face lidFace0 = BRepBuilderAPI_MakeFace(lidSurface, 1e-7).Face();
    const TopoDS_Shape tool = BRepPrimAPI_MakePrism(lidFace0, gp_Vec(0, 0, 60)).Shape();
    BRepAlgoAPI_Cut cut(prism, tool);
    const TopoDS_Shape base = cut.Shape();
    TopoDS_Face lidBase;
    for (TopExp_Explorer x(base, TopAbs_FACE); x.More(); x.Next()) {
        if (untrimmed(BRep_Tool::Surface(TopoDS::Face(x.Current())))->IsKind(STANDARD_TYPE(Geom_BSplineSurface))) {
            lidBase = TopoDS::Face(x.Current());
        }
    }
    if (lidBase.IsNull()) {
        printf("FATAL no lid\n");
        return 3;
    }
    BRepFilletAPI_MakeFillet mk(base);
    TopTools_IndexedMapOfShape lidEdges;
    TopExp::MapShapes(lidBase, TopAbs_EDGE, lidEdges);
    for (int i = 1; i <= lidEdges.Extent(); ++i) mk.Add(R, TopoDS::Edge(lidEdges(i)));
    mk.Build();
    if (!mk.IsDone()) {
        printf("FATAL fillet failed\n");
        return 3;
    }
    const TopoDS_Shape shape = mk.Shape();
    printf("KT2 base valid %d, fillet valid %d, lid edges %d\n", BRepCheck_Analyzer(base).IsValid(), BRepCheck_Analyzer(shape).IsValid(), lidEdges.Extent());

    // ---- recognise: lid, blend faces, their walls, seams, K edges
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces, vertexEdges;
    TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    TopExp::MapShapesAndAncestors(shape, TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
    TopoDS_Face lid = TopoDS::Face(mk.Modified(lidBase).First());
    const Handle(Geom_Surface) sLid = untrimmed(BRep_Tool::Surface(lid));
    std::vector<Blend> blends;
    for (int i = 1; i <= lidEdges.Extent(); ++i) {
        const TopTools_ListOfShape& gen = mk.Generated(lidEdges(i));
        for (TopTools_ListOfShape::Iterator it(gen); it.More(); it.Next()) {
            if (it.Value().ShapeType() != TopAbs_FACE) continue;
            bool known = false;
            for (const Blend& o : blends) known = known || o.f.IsSame(it.Value());
            if (known) continue;
            Blend b;
            b.f = TopoDS::Face(it.Value());
            b.sOld = BRep_Tool::Surface(b.f);
            blends.push_back(b);
        }
    }
    auto blendOf = [&](const TopoDS_Shape& f) {
        for (size_t i = 0; i < blends.size(); ++i)
            if (blends[i].f.IsSame(f)) return int(i);
        return -1;
    };
    auto other = [&](const TopoDS_Edge& e, const TopoDS_Face& f) {
        const TopTools_ListOfShape& l = edgeFaces.FindFromKey(e);
        for (TopTools_ListOfShape::Iterator it(l); it.More(); it.Next())
            if (!it.Value().IsSame(f)) return TopoDS::Face(it.Value());
        return TopoDS_Face();
    };
    std::vector<Seam> seams;
    for (size_t i = 0; i < blends.size(); ++i) {
        Blend& b = blends[i];
        for (TopExp_Explorer x(b.f, TopAbs_EDGE); x.More(); x.Next()) {
            const TopoDS_Edge e = TopoDS::Edge(x.Current());
            const TopoDS_Face o = other(e, b.f);
            const int j = blendOf(o);
            if (o.IsSame(lid)) b.eLid = e;
            else if (j < 0) {
                b.eWall = e;
                b.wall = o;
                b.sWall = untrimmed(BRep_Tool::Surface(o));
                b.isCyl = b.sWall->IsKind(STANDARD_TYPE(Geom_CylindricalSurface));
            }
            else {
                bool known = false;
                for (Seam& s : seams) known = known || s.e.IsSame(e);
                if (!known) {
                    Seam s;
                    s.e = e;
                    seams.push_back(s);
                }
            }
        }
    }
    printf("KT2 faces %d, blend faces %zu, seams %zu\n", faces.Extent(), blends.size(), seams.size());
    for (size_t k = 0; k < seams.size(); ++k) {
        Seam& s = seams[k];
        const TopTools_ListOfShape& l = edgeFaces.FindFromKey(s.e);
        for (TopTools_ListOfShape::Iterator it(l); it.More(); it.Next()) {
            const int j = blendOf(it.Value());
            (blends[j].isCyl ? s.bCyl : s.bPlane) = j;
            Blend& b = blends[j];
            (b.seam[0] < 0 ? b.seam[0] : b.seam[1]) = int(k);
        }
        // K: the edge at one of the seam's vertices that lies between the two side walls
        TopoDS_Vertex v[2];
        TopExp::Vertices(s.e, v[0], v[1]);
        for (int q = 0; q < 2; ++q) {
            const TopTools_ListOfShape& le = vertexEdges.FindFromKey(v[q]);
            for (TopTools_ListOfShape::Iterator it(le); it.More(); it.Next()) {
                const TopoDS_Edge e = TopoDS::Edge(it.Value());
                const TopTools_ListOfShape& lf = edgeFaces.FindFromKey(e);
                bool w1 = false, w2 = false;
                for (TopTools_ListOfShape::Iterator jt(lf); jt.More(); jt.Next()) {
                    w1 = w1 || jt.Value().IsSame(blends[s.bPlane].wall);
                    w2 = w2 || jt.Value().IsSame(blends[s.bCyl].wall);
                }
                if (w1 && w2) {
                    s.K = e;
                    s.vK = v[q];
                    s.vL = v[1 - q];
                }
            }
        }
        if (s.K.IsNull()) {
            printf("FATAL seam %zu has no K edge\n", k);
            return 3;
        }
        double f, l2;
        const Handle(Geom_Curve) kc = BRep_Tool::Curve(s.K, f, l2);
        gp_Pnt kp;
        gp_Vec kd;
        kc->D1(f, kp, kd);
        const gp_Pln pl = Handle(Geom_Plane)::DownCast(blends[s.bPlane].sWall)->Pln();
        s.o = BRep_Tool::Pnt(s.vK);
        s.n = gp_Vec(pl.Axis().Direction()).Crossed(kd).Normalized();
    }

    // ---- OCCT's own section centres: the Newton starts, and OCCT's ball residual
    for (Blend& b : blends) {
        double u0, u1, v0, v1;
        BRepTools::UVBounds(b.f, u0, u1, v0, v1);
        double sign = 0;
        for (int i = 0; i <= 2; ++i) {
            for (int j = 0; j <= 200; ++j) {
                gp_Pnt p;
                gp_Vec du, dv;
                b.sOld->D1(u0 + (u1 - u0) * (i + 1) / 4.0, v0 + (v1 - v0) * j / 200.0, p, du, dv);
                gp_Vec nn = du.Crossed(dv).Normalized();
                if (sign == 0) {
                    double best = 1e9;
                    for (double sg : {-1.0, 1.0}) {
                        const gp_Pnt c = p.Translated(nn * (sg * R));
                        const double r = std::fabs(foot(b.sWall, c).d - R) + std::fabs(foot(sLid, c).d - R);
                        if (r < best) {
                            best = r;
                            sign = sg;
                        }
                    }
                }
                b.centres.push_back(p.Translated(nn * (sign * R)));
            }
        }
    }
    auto start = [&](const Blend& b, const gp_Pnt& o, const gp_Vec& n, const gp_Vec* side) {
        double best = 1e9;
        gp_Pnt c;
        for (const gp_Pnt& p : b.centres) {
            if (side && gp_Vec(o, p).Dot(*side) < 0) continue;
            const double d = std::fabs(gp_Vec(o, p).Dot(n));
            if (d < best) {
                best = d;
                c = p;
            }
        }
        return c;
    };

    // ---- split stations (the seams), then the stations of each face
    int itMax = 0;
    double resMax = 0;
    for (Seam& s : seams) {
        const Blend& b = blends[s.bPlane];
        s.st = solveStation(start(b, s.o, s.n, nullptr), b.sWall, sLid, s.o, s.n);
        itMax = std::max(itMax, s.st.it);
        resMax = std::max(resMax, s.st.res);
        const double onCyl = std::fabs(foot(blends[s.bCyl].sWall, s.st.c).d - R);
        const gp_Pnt oldK = BRep_Tool::Pnt(s.vK), oldL = BRep_Tool::Pnt(s.vL);
        printf("KT2 seam: split station it %d res %.1e, cylinder residual %.1e | vertex on K moves %.5f, vertex on the lid moves %.5f\n",
               s.st.it, s.st.res, onCyl, oldK.Distance(s.st.a.q), oldL.Distance(s.st.b.q));
    }
    for (Blend& b : blends) {
        const Seam& sa = seams[b.seam[0]];
        const Seam& sb = seams[b.seam[1]];
        b.st.assign(NST, Station());
        if (!b.isCyl) {
            const gp_Vec ab(sa.o, sb.o);
            const double len = ab.Dot(sa.n);  // signed along n
            b.length = std::fabs(len);
            for (int k = 0; k < NST; ++k) {
                const gp_Pnt o = sa.o.Translated(sa.n * (len * k / (NST - 1)));
                if (k == 0) b.st[k] = sa.st;
                else if (k == NST - 1) b.st[k] = sb.st;
                else b.st[k] = solveStation(start(b, o, sa.n, nullptr), b.sWall, sLid, o, sa.n, &b.st[k - 1]);
                b.st[k].t = b.length * k / (NST - 1);
            }
        }
        else {
            const gp_Cylinder cy = Handle(Geom_CylindricalSurface)::DownCast(b.sWall)->Cylinder();
            const gp_Ax1 axis = cy.Axis();
            const gp_Vec A(axis.Direction());
            auto radial = [&](const gp_Pnt& p) {
                gp_Vec r(axis.Location(), p);
                r -= A * r.Dot(A);
                return r.Normalized();
            };
            const gp_Vec ra = radial(sa.o), rb = radial(sb.o);
            // the sense of rotation: towards the face's own middle
            const gp_Vec mid = radial(b.centres[b.centres.size() / 2]);
            const double sense = ra.Crossed(mid).Dot(A) > 0 ? 1.0 : -1.0;
            double total = std::atan2(ra.Crossed(rb).Dot(A) * sense, ra.Dot(rb));
            if (total <= 1e-9) total += 2 * M_PI;
            b.length = total * cy.Radius();
            for (int k = 0; k < NST; ++k) {
                const double th = sense * total * k / (NST - 1);
                const gp_Vec rk = ra.Rotated(gp_Ax1(gp_Pnt(0, 0, 0), axis.Direction()), th);
                const gp_Vec n = A.Crossed(rk);
                if (k == 0) b.st[k] = sa.st;
                else if (k == NST - 1) b.st[k] = sb.st;
                else b.st[k] = solveStation(start(b, axis.Location(), n, &rk), b.sWall, sLid, axis.Location(), n, nullptr);
                b.st[k].t = b.length * k / (NST - 1);
            }
            // the seam stations' feet on the cylinder (they were solved on the plane)
            b.st[0].a = foot(b.sWall, b.st[0].c);
            b.st[NST - 1].a = foot(b.sWall, b.st[NST - 1].c);
            // one branch of the cylinder's u along the face
            for (int k = 1; k < NST; ++k) {
                while (b.st[k].a.u - b.st[k - 1].a.u > M_PI) b.st[k].a.u -= 2 * M_PI;
                while (b.st[k].a.u - b.st[k - 1].a.u < -M_PI) b.st[k].a.u += 2 * M_PI;
            }
        }
        for (const Station& s : b.st) {
            itMax = std::max(itMax, s.it);
            resMax = std::max(resMax, s.res);
        }
    }
    printf("KT2 stations: Newton it max %d, residual max %.1e\n", itMax, resMax);

    // ---- the surfaces: section arcs as rational quadratics, a cubic through the stations lengthwise (homogeneous)
    auto build = [&](Blend& b) {
        Handle(TColStd_HArray1OfReal) par = new TColStd_HArray1OfReal(1, NST);
        Handle(TColgp_HArray1OfPnt) row[4];
        for (auto& r : row) r = new TColgp_HArray1OfPnt(1, NST);
        for (int k = 0; k < NST; ++k) {
            const Station& s = b.st[k];
            par->SetValue(k + 1, s.t);
            const gp_Vec e1(s.c, s.a.q), e2(s.c, s.b.q);
            const double half = 0.5 * e1.Angle(e2), w = std::cos(half);
            const gp_Pnt pm = s.c.Translated((e1 + e2).Normalized() * (R / w));
            row[0]->SetValue(k + 1, s.a.q);
            row[1]->SetValue(k + 1, gp_Pnt(pm.XYZ() * w));
            row[2]->SetValue(k + 1, s.b.q);
            row[3]->SetValue(k + 1, gp_Pnt(w, 0, 0));
        }
        Handle(Geom_BSplineCurve) c[4];
        for (int i = 0; i < 4; ++i) {
            GeomAPI_Interpolate in(row[i], par, false, 1e-12);
            in.Perform();
            if (!in.IsDone()) {
                printf("FATAL interpolation\n");
                exit(3);
            }
            c[i] = in.Curve();
        }
        const int np = c[0]->NbPoles();
        TColgp_Array2OfPnt poles(1, 3, 1, np);
        TColStd_Array2OfReal weights(1, 3, 1, np);
        for (int j = 1; j <= np; ++j) {
            const double w = c[3]->Pole(j).X();
            poles(1, j) = c[0]->Pole(j);
            poles(2, j) = gp_Pnt(c[1]->Pole(j).XYZ() / w);
            poles(3, j) = c[2]->Pole(j);
            weights(1, j) = 1;
            weights(2, j) = w;
            weights(3, j) = 1;
        }
        TColStd_Array1OfReal uk(1, 2);
        uk(1) = 0;
        uk(2) = 1;
        TColStd_Array1OfInteger um(1, 2);
        um(1) = 3;
        um(2) = 3;
        TColStd_Array1OfReal vk(1, c[0]->NbKnots());
        TColStd_Array1OfInteger vm(1, c[0]->NbKnots());
        c[0]->Knots(vk);
        c[0]->Multiplicities(vm);
        b.S = new Geom_BSplineSurface(poles, weights, uk, vk, um, vm, 2, c[0]->Degree());
    };
    for (Blend& b : blends) {
        build(b);
        // the new surface's normal must point as the old surface's does (the face keeps its orientation)
        const Station& sm = b.st[NST / 2];
        gp_Pnt p;
        gp_Vec du, dv;
        b.S->D1(0.5, sm.t, p, du, dv);
        const gp_Vec nNew = du.Crossed(dv);
        GeomAPI_ProjectPointOnSurf pr(p, b.sOld);
        double u, v;
        pr.LowerDistanceParameters(u, v);
        gp_Pnt p2;
        b.sOld->D1(u, v, p2, du, dv);
        if (nNew.Dot(du.Crossed(dv)) < 0) {
            std::reverse(b.st.begin(), b.st.end());
            std::swap(b.seam[0], b.seam[1]);
            for (Station& s : b.st) s.t = b.length - s.t;
            build(b);
        }
    }

    // ---- the modification
    Handle(BallModification) mod = new BallModification;
    auto addEdge = [&](const TopoDS_Edge& e, Handle(Geom_Curve) c, std::vector<std::pair<TopoDS_Face, Handle(Geom2d_Curve)>> pcs) {
        const double a = c->FirstParameter(), b = c->LastParameter();
        TopoDS_Vertex vf, vl;
        TopExp::Vertices(TopoDS::Edge(e.Oriented(TopAbs_FORWARD)), vf, vl);
        const gp_Pnt pf = BRep_Tool::Pnt(vf);
        const bool flip = pf.Distance(c->Value(a)) > pf.Distance(c->Value(b));
        if (flip) c = c->Reversed();
        EdgeNew en;
        en.c = c;
        en.vf = vf;
        en.pf = a;
        en.pl = b;
        mod->curves[e.TShape().get()] = en;
        for (auto& pc : pcs) {
            mod->pcurves[{e.TShape().get(), pc.first.TShape().get()}] = flip ? pc.second->Reversed() : pc.second;
        }
    };
    auto interp2d = [&](const Blend& b, bool onLid, const Handle(Geom2d_Curve)& old, double of, double ol) {
        Handle(TColStd_HArray1OfReal) par = new TColStd_HArray1OfReal(1, NST);
        Handle(TColgp_HArray1OfPnt2d) pts = new TColgp_HArray1OfPnt2d(1, NST);
        // the same branch as the old pcurve (a periodic wall)
        const gp_Pnt2d om = old->Value(0.5 * (of + ol));
        const Foot& fm = onLid ? b.st[NST / 2].b : b.st[NST / 2].a;
        const double shift = (!onLid && b.isCyl) ? 2 * M_PI * std::round((om.X() - fm.u) / (2 * M_PI)) : 0.0;
        for (int k = 0; k < NST; ++k) {
            const Foot& f = onLid ? b.st[k].b : b.st[k].a;
            par->SetValue(k + 1, b.st[k].t);
            pts->SetValue(k + 1, gp_Pnt2d(f.u + shift, f.v));
        }
        Geom2dAPI_Interpolate in(pts, par, false, 1e-12);
        in.Perform();
        return Handle(Geom2d_Curve)(in.Curve());
    };
    for (Blend& b : blends) {
        mod->surfaces[b.f.TShape().get()] = b.S;
        double f, l;
        Handle(Geom2d_Curve) old = BRep_Tool::CurveOnSurface(b.eWall, b.wall, f, l);
        addEdge(b.eWall, b.S->UIso(0.0), {{b.f, segment2d(gp_Pnt2d(0, 0), gp_Pnt2d(0, b.length), 0, b.length)}, {b.wall, interp2d(b, false, old, f, l)}});
        old = BRep_Tool::CurveOnSurface(b.eLid, lid, f, l);
        addEdge(b.eLid, b.S->UIso(1.0), {{b.f, segment2d(gp_Pnt2d(1, 0), gp_Pnt2d(1, b.length), 0, b.length)}, {lid, interp2d(b, true, old, f, l)}});
    }
    for (size_t k = 0; k < seams.size(); ++k) {
        Seam& s = seams[k];
        std::vector<std::pair<TopoDS_Face, Handle(Geom2d_Curve)>> pcs;
        Handle(Geom_Curve) c;
        for (int j : {s.bPlane, s.bCyl}) {
            const Blend& b = blends[j];
            const double v = b.seam[0] == int(k) ? 0.0 : b.length;
            if (c.IsNull()) c = b.S->VIso(v);
            pcs.push_back({b.f, segment2d(gp_Pnt2d(0, v), gp_Pnt2d(1, v), 0, 1)});
        }
        addEdge(s.e, c, pcs);
        mod->points[s.vK.TShape().get()] = s.st.a.q;
        mod->points[s.vL.TShape().get()] = s.st.b.q;
        // K keeps its curve; its vertex slides along it
        double f, l;
        const Handle(Geom_Curve) kc = BRep_Tool::Curve(s.K, f, l);
        EdgeNew en;
        en.c = kc;
        TopoDS_Vertex vf, vl;
        TopExp::Vertices(TopoDS::Edge(s.K.Oriented(TopAbs_FORWARD)), vf, vl);
        en.vf = vf;
        en.pf = f;
        en.pl = l;
        GeomAPI_ProjectPointOnCurve pk(s.st.a.q, kc);
        const double np = pk.LowerDistanceParameter();
        printf("KT2 K edge: range [%.6f, %.6f], the moved vertex's parameter %.6f (was %.6f), the new point is %.1e off K\n", f, l, np,
               vf.IsSame(s.vK) ? f : l, pk.LowerDistance());
        (vf.IsSame(s.vK) ? en.pf : en.pl) = np;
        if (KMODE == 1) {
            mod->slides[s.K.TShape().get()] = en;
        }
        else {
            mod->curves[s.K.TShape().get()] = en;
            for (const TopoDS_Face& w : {blends[s.bPlane].wall, blends[s.bCyl].wall}) {
                double f2, l2;
                mod->pcurves[{s.K.TShape().get(), w.TShape().get()}] = BRep_Tool::CurveOnSurface(s.K, w, f2, l2);
            }
        }
    }

    const Tols t0 = maxTol(shape);
    Maker maker(shape, mod);
    if (!maker.IsDone()) {
        printf("KT2 FAIL: the modifier is not done\n");
        return 1;
    }
    TopoDS_Shape result = maker.Shape();
    const Tols t1 = maxTol(result);
    const bool validRaw = BRepCheck_Analyzer(result).IsValid();
    BRepLib::SameParameter(result, 1e-7, true);
    const Tols t2 = maxTol(result);
    const bool valid = BRepCheck_Analyzer(result).IsValid();
    printf("KT2 modifier done | valid before SameParameter %d, after %d\n", validRaw, valid);
    printf("KT2 max tolerance (vertex / edge / face): OCCT's fillet %.2e / %.2e / %.2e | modified %.2e / %.2e / %.2e | after SameParameter %.2e / %.2e / %.2e\n",
           t0.v, t0.e, t0.f, t1.v, t1.e, t1.f, t2.v, t2.e, t2.f);
    if (!valid) {
        BRepCheck_Analyzer an(result);
        int bad = 0;
        for (TopAbs_ShapeEnum kind : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX, TopAbs_WIRE, TopAbs_SHELL}) {
            for (TopExp_Explorer x(result, kind); x.More(); x.Next()) {
                const Handle(BRepCheck_Result)& r = an.Result(x.Current());
                if (r.IsNull()) continue;
                for (const BRepCheck_Status status : r->Status()) {
                    if (status != BRepCheck_NoError && bad++ < 30) printf("   bad: kind %d status %d\n", int(kind), int(status));
                }
            }
        }
    }

    // ---- the same topology in the same order
    bool sameOrder = true;
    int counts[3][2];
    int q = 0;
    for (TopAbs_ShapeEnum kind : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
        TopTools_IndexedMapOfShape before, after;
        TopExp::MapShapes(shape, kind, before);
        TopExp::MapShapes(result, kind, after);
        counts[q][0] = before.Extent();
        counts[q][1] = after.Extent();
        ++q;
        if (before.Extent() != after.Extent()) {
            sameOrder = false;
            continue;
        }
        for (int i = 1; i <= before.Extent(); ++i) sameOrder = sameOrder && maker.ModifiedShape(before(i)).IsSame(after(i));
    }
    printf("KT2 faces %d -> %d, edges %d -> %d, vertices %d -> %d, same order through the modifier's map: %d\n", counts[0][0], counts[0][1],
           counts[1][0], counts[1][1], counts[2][0], counts[2][1], sameOrder);

    // ---- same-parameter deviation, measured here: every edge of every face, 3D curve against pcurve on surface
    double devNew = 0, devAll = 0, vtxDev = 0;
    for (TopExp_Explorer xf(result, TopAbs_FACE); xf.More(); xf.Next()) {
        const TopoDS_Face f = TopoDS::Face(xf.Current());
        const Handle(Geom_Surface) S = BRep_Tool::Surface(f);
        for (TopExp_Explorer xe(f, TopAbs_EDGE); xe.More(); xe.Next()) {
            const TopoDS_Edge e = TopoDS::Edge(xe.Current());
            double a, b, a2, b2;
            const Handle(Geom_Curve) c = BRep_Tool::Curve(e, a, b);
            const Handle(Geom2d_Curve) pc = BRep_Tool::CurveOnSurface(e, f, a2, b2);
            if (c.IsNull() || pc.IsNull()) {
                printf("   an edge without a curve or a pcurve\n");
                devAll = 1e9;
                continue;
            }
            double d = std::max(std::fabs(a - a2), std::fabs(b - b2));
            for (int k = 0; k <= 200; ++k) {
                const double t = a + (b - a) * k / 200.0;
                const gp_Pnt2d uv = pc->Value(t);
                d = std::max(d, c->Value(t).Distance(S->Value(uv.X(), uv.Y())));
            }
            devAll = std::max(devAll, d);
            TopoDS_Vertex vf, vl;
            TopExp::Vertices(TopoDS::Edge(e.Oriented(TopAbs_FORWARD)), vf, vl);
            vtxDev = std::max({vtxDev, BRep_Tool::Pnt(vf).Distance(c->Value(a)), BRep_Tool::Pnt(vl).Distance(c->Value(b))});
        }
    }
    for (const Blend& b : blends) {
        const TopoDS_Face f = TopoDS::Face(maker.ModifiedShape(b.f));
        const Handle(Geom_Surface) S = BRep_Tool::Surface(f);
        for (TopExp_Explorer xe(f, TopAbs_EDGE); xe.More(); xe.Next()) {
            const TopoDS_Edge e = TopoDS::Edge(xe.Current());
            double a, bb;
            const Handle(Geom_Curve) c = BRep_Tool::Curve(e, a, bb);
            for (TopExp_Explorer xf(result, TopAbs_FACE); xf.More(); xf.Next()) {
                const TopoDS_Face g = TopoDS::Face(xf.Current());
                bool has = false;
                for (TopExp_Explorer xg(g, TopAbs_EDGE); xg.More() && !has; xg.Next()) has = xg.Current().IsSame(e);
                if (!has) continue;
                double a2, b2;
                const Handle(Geom2d_Curve) pc = BRep_Tool::CurveOnSurface(e, g, a2, b2);
                const Handle(Geom_Surface) Sg = BRep_Tool::Surface(g);
                for (int k = 0; k <= 400; ++k) {
                    const double t = a + (bb - a) * k / 400.0;
                    const gp_Pnt2d uv = pc->Value(t);
                    devNew = std::max(devNew, c->Value(t).Distance(Sg->Value(uv.X(), uv.Y())));
                }
            }
        }
    }
    printf("KT2 3D curve against pcurve on surface, max: the blend faces' edges on all their faces %.2e | every edge of the body %.2e | vertex against its edges' ends %.2e\n",
           devNew, devAll, vtxDev);

    // ---- the ball residual, before and after
    double worstOld = 0, worstNew = 0;
    for (const Blend& b : blends) {
        double w0, m0, w1, m1;
        ballResidual(b.f, b.sWall, sLid, w0, m0);
        ballResidual(TopoDS::Face(maker.ModifiedShape(b.f)), b.sWall, sLid, w1, m1);
        worstOld = std::max(worstOld, w0);
        worstNew = std::max(worstNew, w1);
        printf("KT2 blend face on a %s: ball residual OCCT max %.2e mean %.2e | corrected max %.2e mean %.2e | area %.6f -> %.6f\n",
               b.isCyl ? "cylinder" : "plane   ", w0, m0, w1, m1, area(b.f), area(maker.ModifiedShape(b.f)));
    }
    printf("KT2 volume %.6f -> %.6f (d %.2e), area %.6f -> %.6f\n", volume(shape), volume(result), volume(result) - volume(shape), area(shape), area(result));

    // ---- a later feature: a box cut through one seam
    bool laterValid = false;
    try {
        const gp_Pnt c = seams[0].st.c;
        const TopoDS_Shape box = BRepPrimAPI_MakeBox(gp_Pnt(c.X() - 3, c.Y() - 3, c.Z() - 3), 6, 6, 12).Shape();
        BRepAlgoAPI_Cut later(result, box);
        laterValid = later.IsDone() && !later.HasErrors() && BRepCheck_Analyzer(later.Shape()).IsValid();
        printf("KT2 a box cut through a corrected seam: done %d, errors %d, valid %d, volume removed %.4f\n", later.IsDone(), later.HasErrors(),
               laterValid, volume(result) - volume(later.Shape()));
    }
    catch (const Standard_Failure& e) {
        printf("KT2 later cut threw: %s\n", e.what());
    }
    BRepTools::Write(shape, "occt_fillet.brep");
    BRepTools::Write(result, "corrected.brep");

    const double tolMax = std::max({t2.v, t2.e, t2.f});
    const bool pass = valid && sameOrder && tolMax <= 1e-6 && worstNew <= 1e-6 && devNew <= 1e-6 && laterValid;
    printf("KT2 %s: valid %d, same topology %d, max tolerance %.2e (bound 1e-6), ball residual %.2e (bound 1e-6; OCCT's %.2e), same-parameter %.2e, later cut valid %d\n",
           pass ? "PASS" : "FAIL", valid, sameOrder, tolMax, worstNew, worstOld, devNew, laterValid);
    return pass ? 0 : 1;
}
