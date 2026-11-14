// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                             *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 ****************************************************************************/

// FreeCAD-CH kernel layer: per-feature post-conditions, report-only (PostCondition.h)

#include <BOPAlgo_CheckerSI.hxx>
#include <BOPDS_DS.hxx>
#include <BOPDS_Pair.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepBndLib.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_Circle.hxx>
#include <Geom_ConicalSurface.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_OffsetSurface.hxx>
#include <Geom_Plane.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom_SphericalSurface.hxx>
#include <Geom_SurfaceOfLinearExtrusion.hxx>
#include <Geom_SurfaceOfRevolution.hxx>
#include <Geom_ToroidalSurface.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <GeomConvert.hxx>
#include <GeomConvert_SurfToAnaSurf.hxx>
#include <Message_ProgressRange.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Iterator.hxx>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>

#include <App/Document.h>
#include <Mod/Part/App/KernelBudget.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureAddSub.h"
#include "FeatureBoolean.h"
#include "FeatureDressUp.h"
#include "FeatureTransformed.h"
#include "PostCondition.h"

using namespace PartDesign;

namespace
{
// Thresholds (notes/census.md, "The checks as per-feature post-conditions")
constexpr double tolAbsolute = 1e-3;   // mm
constexpr double tolGrowth = 10.0;     // times the base's
constexpr double typeTolerance = 1e-7; // mm, the fit of a free-form face to an analytic one
// 1e-9, not census's 1e-6: FSLC #037 removes a real 0.00026 mm^3 sliver of 15362 (Onshape: 0.000266)
constexpr double dvRelative = 1e-9;
constexpr double dvAbsolute = 1e-6;    // mm^3

using Clock = std::chrono::steady_clock;

double msSince(Clock::time_point start)
{
    return std::chrono::duration<double, std::milli>(Clock::now() - start).count();
}

/// An environment variable, or empty (_dupenv_s under MSVC: clang-cl's -Wdeprecated rejects
/// std::getenv there)
std::string environmentValue(const char* name)
{
#ifdef _MSC_VER
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, name) != 0 || !value) {
        return {};
    }
    std::string text(value);
    std::free(value);
    return text;
#else
    const char* value = std::getenv(name);
    return value ? std::string(value) : std::string();
#endif
}

/// Read at each feature, so that a script or a test can turn the log on and off (a getenv is
/// cheap next to a feature)
std::string logPath()
{
    return environmentValue("FREECAD_CH_POSTCOND_LOG");
}

std::string quoted(const std::string& text)
{
    std::string out = "\"";
    for (unsigned char c : text) {
        switch (c) {
            case '"':
                out += "\\\"";
                break;
            case '\\':
                out += "\\\\";
                break;
            case '\n':
                out += "\\n";
                break;
            case '\t':
                out += "\\t";
                break;
            default:
                if (c < 0x20) {
                    char buffer[8];
                    std::snprintf(buffer, sizeof(buffer), "\\u%04x", c);
                    out += buffer;
                }
                else {
                    out += static_cast<char>(c);
                }
        }
    }
    return out + "\"";
}

std::string number(double value)
{
    if (!std::isfinite(value)) {
        return "null";
    }
    std::ostringstream text;
    text.precision(9);
    text << value;
    return text.str();
}

double maxTolerance(const TopoDS_Shape& shape)
{
    double tolerance = 0.0;
    if (shape.IsNull()) {
        return tolerance;
    }
    for (TopExp_Explorer it(shape, TopAbs_EDGE); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Edge(it.Current())));
    }
    for (TopExp_Explorer it(shape, TopAbs_VERTEX); it.More(); it.Next()) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Vertex(it.Current())));
    }
    return tolerance;
}

const char* analyticName(const occ::handle<Geom_Surface>& surface)
{
    if (surface.IsNull()) {
        return nullptr;
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_Plane))) {
        return "Plane";
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_CylindricalSurface))) {
        return "Cylinder";
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_ConicalSurface))) {
        return "Cone";
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_SphericalSurface))) {
        return "Sphere";
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_ToroidalSurface))) {
        return "Torus";
    }
    return nullptr;
}

/// The free-form kinds a degraded face comes as; null for any other surface
const char* freeFormName(const occ::handle<Geom_Surface>& surface)
{
    if (surface->IsKind(STANDARD_TYPE(Geom_BSplineSurface))) {
        return "BSplineSurface";
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_BezierSurface))) {
        return "BezierSurface";
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_SurfaceOfLinearExtrusion))) {
        return "SurfaceOfExtrusion";
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_SurfaceOfRevolution))) {
        return "SurfaceOfRevolution";
    }
    if (surface->IsKind(STANDARD_TYPE(Geom_OffsetSurface))) {
        return "OffsetSurface";
    }
    return nullptr;
}

/// A revolved circle: a torus (or a sphere) by construction, exact, counted apart
bool revolvedCircle(const occ::handle<Geom_Surface>& surface)
{
    auto revolution = occ::handle<Geom_SurfaceOfRevolution>::DownCast(surface);
    if (revolution.IsNull()) {
        return false;
    }
    occ::handle<Geom_Curve> curve = revolution->BasisCurve();
    while (auto trimmed = occ::handle<Geom_TrimmedCurve>::DownCast(curve)) {
        curve = trimmed->BasisCurve();
    }
    return curve->IsKind(STANDARD_TYPE(Geom_Circle));
}

struct Degraded
{
    std::string from;
    std::string to;
    double gap {0.0};
    double area {0.0};
    double centre[3] {0.0, 0.0, 0.0};
};

struct TypeResult
{
    int freeForm {0};
    int revolvedCircles {0};
    int offsetsUnchecked {0};
    int failures {0};
    int inherited {0};
    std::vector<Degraded> degraded;
};

/// The analytic surface within typeTolerance of the face's surface over the face's parameters
occ::handle<Geom_Surface> analyticOf(const TopoDS_Face& face, const occ::handle<Geom_Surface>& basis, double& gap)
{
    double u1 = 0;
    double u2 = 0;
    double v1 = 0;
    double v2 = 0;
    BRepTools::UVBounds(face, u1, u2, v1, v2);
    occ::handle<Geom_Surface> surface = basis;
    if (auto offset = occ::handle<Geom_OffsetSurface>::DownCast(basis)) {
        // Its equivalent surface, where OCCT knows one (an offset of an analytic surface)
        occ::handle<Geom_Surface> equivalent = offset->Surface();
        if (equivalent.IsNull()) {
            return {};
        }
        if (analyticName(equivalent)) {
            gap = 0.0;
            return equivalent;
        }
        surface = equivalent;
    }
    if (!surface->IsKind(STANDARD_TYPE(Geom_BSplineSurface))
        && !surface->IsKind(STANDARD_TYPE(Geom_BezierSurface))) {
        // An extrusion or a revolution: its exact B-spline over the face's parameters
        occ::handle<Geom_Surface> trimmed = new Geom_RectangularTrimmedSurface(surface, u1, u2, v1, v2);
        surface = GeomConvert::SurfaceToBSplineSurface(trimmed);
        double a1 = 0;
        double a2 = 0;
        double b1 = 0;
        double b2 = 0;
        surface->Bounds(a1, a2, b1, b2);
        u1 = a1;
        u2 = a2;
        v1 = b1;
        v2 = b2;
    }
    GeomConvert_SurfToAnaSurf converter(surface);
    occ::handle<Geom_Surface> analytic = converter.ConvertToAnalytical(typeTolerance, u1, u2, v1, v2);
    if (analytic.IsNull() || !analyticName(analytic) || converter.Gap() > typeTolerance) {
        return {};
    }
    gap = converter.Gap();
    return analytic;
}

/// The base's degraded faces, found once when a made face is degraded: a made face whose surface
/// is one of them (the same geometry, or the same analytic form) was re-trimmed or copied by the
/// feature, not made degraded by it (a pad that re-trims a revolve's faces; a dress-up's result,
/// built on copies, has every face new)
class Inherited
{
public:
    explicit Inherited(const TopoDS_Shape& base)
        : base(base)
    {}

    bool contains(const occ::handle<Geom_Surface>& raw, const occ::handle<Geom_Surface>& analytic)
    {
        load();
        for (const auto& known : raws) {
            if (known == raw) {
                return true;
            }
        }
        for (const auto& known : analytics) {
            if (known->DynamicType() == analytic->DynamicType()
                && GeomConvert_SurfToAnaSurf::IsSame(known, analytic, typeTolerance)) {
                return true;
            }
        }
        return false;
    }

private:
    void load()
    {
        if (loaded) {
            return;
        }
        loaded = true;
        if (base.IsNull()) {
            return;
        }
        for (TopExp_Explorer it(base, TopAbs_FACE); it.More(); it.Next()) {
            const TopoDS_Face& face = TopoDS::Face(it.Current());
            TopLoc_Location location;
            occ::handle<Geom_Surface> raw = BRep_Tool::Surface(face, location);
            occ::handle<Geom_Surface> surface = raw;
            while (auto trimmed = occ::handle<Geom_RectangularTrimmedSurface>::DownCast(surface)) {
                surface = trimmed->BasisSurface();
            }
            if (surface.IsNull() || !freeFormName(surface)) {
                continue;
            }
            raws.push_back(raw);
            try {
                double gap = 0.0;
                occ::handle<Geom_Surface> analytic = analyticOf(face, surface, gap);
                if (!analytic.IsNull()) {
                    // In the frame the made faces are compared in (BRep_Tool::Surface(face))
                    if (!location.IsIdentity()) {
                        analytic = occ::down_cast<Geom_Surface>(
                            analytic->Transformed(location.Transformation()));
                    }
                    analytics.push_back(analytic);
                }
            }
            catch (const Standard_Failure&) {
            }
        }
    }

    TopoDS_Shape base;
    bool loaded {false};
    std::vector<occ::handle<Geom_Surface>> raws;
    std::vector<occ::handle<Geom_Surface>> analytics;
};

TypeResult checkTypes(const TopoDS_Shape& made, const TopoDS_Shape& base)
{
    TypeResult result;
    Inherited inherited(base);
    for (TopoDS_Iterator it(made); it.More(); it.Next()) {
        if (it.Value().ShapeType() != TopAbs_FACE) {
            continue;
        }
        const TopoDS_Face& face = TopoDS::Face(it.Value());
        occ::handle<Geom_Surface> surface = BRep_Tool::Surface(face);
        if (surface.IsNull()) {
            continue;
        }
        while (auto trimmed = occ::handle<Geom_RectangularTrimmedSurface>::DownCast(surface)) {
            surface = trimmed->BasisSurface();
        }
        const char* from = freeFormName(surface);
        if (!from) {
            continue;
        }
        ++result.freeForm;
        if (revolvedCircle(surface)) {
            ++result.revolvedCircles;
            continue;
        }
        try {
            double gap = 0.0;
            occ::handle<Geom_Surface> analytic = analyticOf(face, surface, gap);
            if (analytic.IsNull()) {
                if (surface->IsKind(STANDARD_TYPE(Geom_OffsetSurface))
                    && occ::handle<Geom_OffsetSurface>::DownCast(surface)->Surface().IsNull()) {
                    ++result.offsetsUnchecked;
                }
                continue;
            }
            // analytic is in the located frame already (BRep_Tool::Surface(face) applies the
            // face's location); raw is the TShape's own handle, for the identity test
            TopLoc_Location location;
            occ::handle<Geom_Surface> raw = BRep_Tool::Surface(face, location);
            if (inherited.contains(raw, analytic)) {
                ++result.inherited;
                continue;
            }
            Degraded found;
            found.from = from;
            found.to = analyticName(analytic);
            found.gap = gap;
            GProp_GProps props;
            BRepGProp::SurfaceProperties(face, props);
            found.area = props.Mass();
            Bnd_Box box;
            BRepBndLib::Add(face, box, Standard_False);
            if (!box.IsVoid()) {
                double x0 = 0;
                double y0 = 0;
                double z0 = 0;
                double x1 = 0;
                double y1 = 0;
                double z1 = 0;
                box.Get(x0, y0, z0, x1, y1, z1);
                found.centre[0] = (x0 + x1) / 2;
                found.centre[1] = (y0 + y1) / 2;
                found.centre[2] = (z0 + z1) / 2;
            }
            result.degraded.push_back(found);
        }
        catch (const Standard_Failure&) {
            ++result.failures;
        }
    }
    return result;
}

struct BopResult
{
    std::string status = "not run";  // "ok", "faulty", "limit", "error: ...", "no faces"
    int faces {0};
    int level {4};
    int selfIntersect {0};
};

/// The faces made and every face that shares an edge with one, in one compound
TopoDS_Compound madeAndNeighbours(const TopoDS_Shape& checked, const TopoDS_Shape& made, int& count)
{
    TopTools_IndexedMapOfShape madeFaces;
    for (TopoDS_Iterator it(made); it.More(); it.Next()) {
        madeFaces.Add(it.Value());
    }
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(checked, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    TopTools_IndexedMapOfShape faces;
    for (int i = 1; i <= madeFaces.Extent(); ++i) {
        faces.Add(madeFaces(i));
        for (TopExp_Explorer edge(madeFaces(i), TopAbs_EDGE); edge.More(); edge.Next()) {
            const int index = edgeFaces.FindIndex(edge.Current());
            if (index == 0) {
                continue;
            }
            for (const TopoDS_Shape& face : edgeFaces(index)) {
                faces.Add(face);
            }
        }
    }
    BRep_Builder builder;
    TopoDS_Compound compound;
    builder.MakeCompound(compound);
    for (int i = 1; i <= faces.Extent(); ++i) {
        builder.Add(compound, faces(i));
    }
    count = faces.Extent();
    return compound;
}

/// The self-interference check's level (BOPAlgo_CheckerSI::SetLevelOfCheck: 0 vertex/vertex .. 4
/// edge/face, 5 also face/face): FREECAD_CH_POSTCOND_BOP_LEVEL, default 4. Face/face intersections of
/// free-form faces cost seconds a feature (thread flanks, the replica studios) and found nothing
/// the edge/face level doesn't
int bopLevel()
{
    const std::string value = environmentValue("FREECAD_CH_POSTCOND_BOP_LEVEL");
    if (value.size() == 1 && value[0] >= '0' && value[0] <= '5') {
        return value[0] - '0';
    }
    return 4;
}

/// The most faces the check reads (FREECAD_CH_POSTCOND_BOP_MAX, default 1000): a feature that makes
/// more (a pattern of thousands of faces) is not checked ("size")
int bopMaxFaces()
{
    const std::string value = environmentValue("FREECAD_CH_POSTCOND_BOP_MAX");
    if (!value.empty()) {
        const int n = std::atoi(value.c_str());
        if (n > 0) {
            return n;
        }
    }
    return 1000;
}

BopResult checkBop(const TopoDS_Shape& checked, const TopoDS_Shape& made)
{
    BopResult result;
    result.level = bopLevel();
    TopoDS_Compound faces = madeAndNeighbours(checked, made, result.faces);
    if (result.faces == 0) {
        result.status = "no faces";
        return result;
    }
    if (result.faces > bopMaxFaces()) {
        result.status = "size";
        return result;
    }
    if (Part::KernelBudget::pastDeadline()) {
        result.status = "limit";
        return result;
    }
    struct Work
    {
        TopoDS_Shape shape;
        int level {4};
        int pairs {0};
        bool errors {false};
    };
    auto work = std::make_shared<Work>();
    work->shape = Part::KernelBudget::exactCopy(faces);
    work->level = result.level;
    const bool finished = Part::KernelBudget::runOptional(
        "A post-condition check",
        [work](const Message_ProgressRange& range) {
            // As BOPAlgo_ArgumentAnalyzer's self-interference test, at a chosen level
            BOPAlgo_CheckerSI checker;
            NCollection_List<TopoDS_Shape> arguments;
            arguments.Append(work->shape);
            checker.SetArguments(arguments);
            checker.SetNonDestructive(true);
            checker.SetRunParallel(false);
            checker.SetLevelOfCheck(work->level);
            checker.Perform(range);
            work->errors = checker.HasErrors();
            const BOPDS_DS& ds = *checker.PDS();
            for (const BOPDS_Pair& pair : ds.Interferences()) {
                int i1 = 0;
                int i2 = 0;
                pair.Indices(i1, i2);
                if (!ds.IsNewShape(i1) && !ds.IsNewShape(i2)) {
                    ++work->pairs;
                }
            }
        }
    );
    if (!finished) {
        result.status = "limit";
        return result;
    }
    result.selfIntersect = work->pairs;
    if (work->errors && work->pairs == 0) {
        result.status = "error";
        return result;
    }
    result.status = work->pairs == 0 ? "ok" : "faulty";
    return result;
}

/// Whether the operation is meant to change the volume: an add or remove, a Boolean, a pattern
bool changesVolume(Feature& feature)
{
    if (feature.isDerivedFrom<DressUp>()) {
        return false;
    }
    return feature.isDerivedFrom<FeatureAddSub>() || feature.isDerivedFrom<Boolean>()
        || feature.isDerivedFrom<Transformed>();
}

std::mutex logMutex;
}  // namespace

bool PostCondition::enabled()
{
    return !logPath().empty();
}

void PostCondition::report(Feature& feature, const Observed& observed) noexcept
{
    std::string path;
    try {
        path = logPath();
    }
    catch (...) {
        return;
    }
    if (path.empty() || !observed.fresh) {
        return;
    }
    try {
        const auto start = Clock::now();
        std::ostringstream line;
        std::string document;
        if (auto doc = feature.getDocument()) {
            document = doc->getName();
        }
        std::string body;
        if (auto owner = feature.getFeatureBody()) {
            body = owner->getNameInDocument() ? owner->getNameInDocument() : "";
        }
        int madeCount = 0;
        for (TopoDS_Iterator it(observed.made); it.More(); it.Next()) {
            ++madeCount;
        }
        line << "{\"doc\":" << quoted(document) << ",\"body\":" << quoted(body)
             << ",\"name\":" << quoted(feature.getNameInDocument() ? feature.getNameInDocument() : "")
             << ",\"label\":" << quoted(feature.Label.getValue())
             << ",\"type\":" << quoted(feature.getTypeId().getName()) << ",\"made\":" << madeCount;

        // tol
        auto clock = Clock::now();
        const TopoDS_Shape result = feature.Shape.getShape().getShape();
        const double resultTol = maxTolerance(result);
        const double baseTol = maxTolerance(observed.base);
        const bool tolFlag = resultTol > tolAbsolute && resultTol > tolGrowth * baseTol;
        line << ",\"tol\":{\"result\":" << number(resultTol) << ",\"base\":" << number(baseTol)
             << ",\"flag\":" << (tolFlag ? "true" : "false") << ",\"ms\":" << number(msSince(clock))
             << "}";

        // type
        clock = Clock::now();
        const TypeResult types = checkTypes(observed.made, observed.base);
        line << ",\"deg\":{\"freeForm\":" << types.freeForm
             << ",\"revolvedCircles\":" << types.revolvedCircles
             << ",\"offsetsUnchecked\":" << types.offsetsUnchecked
             << ",\"failures\":" << types.failures << ",\"inherited\":" << types.inherited
             << ",\"faces\":[";
        for (std::size_t i = 0; i < types.degraded.size(); ++i) {
            const Degraded& d = types.degraded[i];
            line << (i ? "," : "") << "{\"from\":" << quoted(d.from) << ",\"to\":" << quoted(d.to)
                 << ",\"gap\":" << number(d.gap) << ",\"area\":" << number(d.area) << ",\"c\":["
                 << number(d.centre[0]) << "," << number(d.centre[1]) << ","
                 << number(d.centre[2]) << "]}";
        }
        line << "],\"flag\":" << (types.degraded.empty() ? "false" : "true")
             << ",\"ms\":" << number(msSince(clock)) << "}";

        // dv
        const bool dvApplies = changesVolume(feature) && observed.volumeKnown;
        const bool dvFlag = dvApplies
            && std::abs(observed.change) <= dvRelative * std::abs(observed.after) + dvAbsolute;
        line << ",\"dv\":{\"applies\":" << (dvApplies ? "true" : "false");
        if (observed.volumeKnown) {
            line << ",\"change\":" << number(observed.change) << ",\"after\":"
                 << number(observed.after);
        }
        line << ",\"flag\":" << (dvFlag ? "true" : "false") << "}";

        // bop
        clock = Clock::now();
        BopResult bop;
        if (madeCount == 0) {
            bop.status = "no faces";
        }
        else {
            try {
                bop = checkBop(observed.checked, observed.made);
            }
            catch (const Standard_Failure& e) {
                bop.status = std::string("error: ") + e.GetMessageString();
            }
            catch (const std::exception& e) {
                bop.status = std::string("error: ") + e.what();
            }
        }
        line << ",\"bop\":{\"status\":" << quoted(bop.status) << ",\"faces\":" << bop.faces
             << ",\"level\":" << bop.level << ",\"selfIntersect\":" << bop.selfIntersect
             << ",\"flag\":" << (bop.status == "faulty" ? "true" : "false")
             << ",\"ms\":" << number(msSince(clock)) << "}";

        line << ",\"ms\":" << number(msSince(start)) << "}\n";
        std::lock_guard<std::mutex> lock(logMutex);
        std::ofstream out(path, std::ios::app);
        out << line.str();
    }
    catch (...) {
        // Report-only: nothing here may change the feature's outcome
    }
}
