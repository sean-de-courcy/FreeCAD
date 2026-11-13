// SPDX-License-Identifier: LGPL-2.1-or-later

// Patterns as studio features (FreeCAD-CH ops#655, T1-T3). Scaffolding (B1); the copy rule of
// in-Body patterns of studio features (ops#654 slice 8).

#include <algorithm>
#include <cmath>
#include <optional>
#include <string>
#include <vector>

#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Pln.hxx>
#include <gp_Trsf.hxx>

#include <App/Datums.h>
#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <App/PropertyUnits.h>
#include <Base/Exception.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/Part2DObject.h>

#include "Body.h"
#include "FeatureAddSub.h"
#include "FeatureExtrude.h"
#include "FeatureHole.h"
#include "FeatureMirrored.h"
#include "StudioOwner.h"
#include "StudioPattern.h"

namespace PartDesign
{

std::vector<Body*> studioPatternScope(const App::DocumentObject* /*pattern*/)
{
    return {};  // T1
}

namespace
{

constexpr double lengthTolerance = 1e-6;
constexpr double angleTolerance = 1e-9;

std::string enumOf(const App::DocumentObject* obj, const char* name)
{
    auto prop = freecad_cast<App::PropertyEnumeration*>(obj->getPropertyByName(name));
    const char* value = prop ? prop->getValueAsString() : nullptr;
    return value ? value : "";
}

double floatOf(const App::DocumentObject* obj, const char* name)
{
    auto prop = freecad_cast<App::PropertyFloat*>(obj->getPropertyByName(name));
    return prop ? prop->getValue() : 0.0;
}

bool boolOf(const App::DocumentObject* obj, const char* name)
{
    auto prop = freecad_cast<App::PropertyBool*>(obj->getPropertyByName(name));
    return prop && prop->getValue();
}

const App::PropertyLinkSub* linkOf(const App::DocumentObject* obj, const char* name)
{
    return freecad_cast<App::PropertyLinkSub*>(obj->getPropertyByName(name));
}

gp_Trsf toTrsf(const Base::Placement& placement)
{
    return Part::TopoShape::convert(placement.toMatrix());
}

/// The geometry a reference names, in the document's frame (null when there is none)
TopoDS_Shape referenceShape(const App::PropertyLinkSub* link)
{
    App::DocumentObject* ref = link ? link->getValue() : nullptr;
    if (!ref) {
        return {};
    }
    const auto& subs = link->getSubValues();
    TopoDS_Shape shape = Part::Feature::getShape(
        ref,
        Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink,
        subs.empty() ? nullptr : subs[0].c_str()
    );
    if (shape.IsNull()) {
        return {};
    }
    // In the object's own frame (no Transform): placed where the document has it
    return BRepBuilderAPI_Transform(shape, toTrsf(App::GeoFeature::getGlobalPlacement(ref)), true)
        .Shape();
}

/// The plane a reference names, in the document's frame: an origin or datum plane, or a planar face
std::optional<gp_Pln> referencePlane(const App::PropertyLinkSub* link)
{
    App::DocumentObject* ref = link ? link->getValue() : nullptr;
    if (!ref) {
        return std::nullopt;
    }
    if (ref->isDerivedFrom<App::Plane>()) {
        const Base::Placement placement = App::GeoFeature::getGlobalPlacement(ref);
        Base::Vector3d normal = placement.getRotation().multVec(Base::Vector3d(0, 0, 1));
        const Base::Vector3d origin = placement.getPosition();
        return gp_Pln(gp_Pnt(origin.x, origin.y, origin.z), gp_Dir(normal.x, normal.y, normal.z));
    }
    const TopoDS_Shape shape = referenceShape(link);
    TopExp_Explorer faces(shape, TopAbs_FACE);
    if (!faces.More()) {
        return std::nullopt;
    }
    BRepAdaptor_Surface surface(TopoDS::Face(faces.Current()));
    if (surface.GetType() != GeomAbs_Plane) {
        return std::nullopt;
    }
    return surface.Plane();
}

/// Whether t maps pln onto itself
bool keepsPlane(const gp_Trsf& t, const gp_Pln& pln)
{
    const gp_Pln moved = pln.Transformed(t);
    return moved.Axis().Direction().IsParallel(pln.Axis().Direction(), angleTolerance)
        && pln.Distance(moved.Location()) < lengthTolerance;
}

/// The normal of a profile-based feature's profile plane, in the document's frame
std::optional<gp_Dir> profileNormal(const App::DocumentObject* owner)
{
    auto profile = linkOf(owner, "Profile");
    App::DocumentObject* obj = profile ? profile->getValue() : nullptr;
    if (!obj) {
        return std::nullopt;
    }
    if (obj->isDerivedFrom<Part::Part2DObject>()) {
        const Base::Vector3d normal = App::GeoFeature::getGlobalPlacement(obj).getRotation().multVec(
            Base::Vector3d(0, 0, 1)
        );
        return gp_Dir(normal.x, normal.y, normal.z);
    }
    if (auto plane = referencePlane(profile)) {
        return plane->Axis().Direction();
    }
    return std::nullopt;
}

/// The z range of shape in the frame whose z axis is along: [low, high]; false when empty
bool rangeAlong(const TopoDS_Shape& shape, const gp_Trsf& toLocal, Bnd_Box& box)
{
    if (shape.IsNull()) {
        return false;
    }
    BRepBndLib::AddOptimal(shape.Moved(TopLoc_Location(toLocal)), box, false, false);
    return !box.IsVoid();
}

/** The column over a straight copy's own footprint, in the frame where it runs along z: its end
 * faces at the low end z0 swept from low to high. Null when the copy has no planar end there (the
 * box around it is used instead) */
TopoDS_Shape footprintColumn(const TopoDS_Shape& copyLocal, double z0, double low, double high)
{
    const double tolerance = 1e-5;
    BRep_Builder builder;
    TopoDS_Compound column;
    builder.MakeCompound(column);
    bool any = false;
    gp_Trsf shift;
    shift.SetTranslation(gp_Vec(0, 0, low - z0));
    for (TopExp_Explorer it(copyLocal, TopAbs_FACE); it.More(); it.Next()) {
        const TopoDS_Face& face = TopoDS::Face(it.Current());
        BRepAdaptor_Surface surface(face);
        if (surface.GetType() != GeomAbs_Plane
            || !surface.Plane().Axis().Direction().IsParallel(gp::DZ(), Precision::Angular())) {
            continue;
        }
        Bnd_Box box;
        BRepBndLib::AddOptimal(face, box, false, false);
        double fx0, fy0, fz0, fx1, fy1, fz1;
        box.Get(fx0, fy0, fz0, fx1, fy1, fz1);
        if (std::fabs(fz0 - z0) > tolerance || std::fabs(fz1 - z0) > tolerance) {
            continue;
        }
        BRepPrimAPI_MakePrism prism(face.Moved(TopLoc_Location(shift)), gp_Vec(0, 0, high - low));
        if (!prism.IsDone()) {
            return {};
        }
        builder.Add(column, prism.Shape());
        any = true;
    }
    return any ? TopoDS_Shape(column) : TopoDS_Shape();
}

/** Whether every copy of a straight tool along normal (in the pattern's frame) spans the part:
 * within the copy's footprint (its own end faces swept across the part, ops#640 F2: its box
 * refused a hole beside a boss), the part lies between the copy's two ends. Then the copy removes what a Through all made at that place removes, as both are the
 * same profile swept from the same start, through all of the part's material ahead. */
bool everyCopySpans(
    const Part::TopoShape& tool,
    const Part::TopoShape& part,
    const gp_Dir& normal,
    const std::vector<gp_Trsf>& instances
)
{
    for (const gp_Trsf& t : instances) {
        const TopoDS_Shape copy = BRepBuilderAPI_Transform(tool.getShape(), t, true).Shape();
        const gp_Dir along = normal.Transformed(t);
        gp_Trsf toLocal;
        toLocal.SetTransformation(gp_Ax3(gp::Origin(), along));
        Bnd_Box toolBox;
        Bnd_Box partBox;
        if (!rangeAlong(copy, toLocal, toolBox)) {
            return false;
        }
        if (!rangeAlong(part.getShape(), toLocal, partBox)) {
            continue;  // no part: nothing to remove
        }
        double x0, y0, z0, x1, y1, z1;
        double px0, py0, pz0, px1, py1, pz1;
        toolBox.Get(x0, y0, z0, x1, y1, z1);
        partBox.Get(px0, py0, pz0, px1, py1, pz1);
        const double margin = 1.0;
        const double low = std::min(pz0, z0) - margin;
        const double high = std::max(pz1, z1) + margin;
        TopoDS_Shape column =
            footprintColumn(copy.Moved(TopLoc_Location(toLocal)), z0, low, high);
        if (column.IsNull()) {
            column = BRepPrimAPI_MakeBox(
                         gp_Pnt(x0 - lengthTolerance, y0 - lengthTolerance, low),
                         gp_Pnt(x1 + lengthTolerance, y1 + lengthTolerance, high)
            )
                         .Shape();
        }
        BRepAlgoAPI_Common common(part.getShape().Moved(TopLoc_Location(toLocal)), column);
        if (!common.IsDone()) {
            return false;
        }
        Bnd_Box inColumn;
        if (!rangeAlong(common.Shape(), gp_Trsf(), inColumn)) {
            continue;  // the copy misses the part
        }
        double cx0, cy0, cz0, cx1, cy1, cz1;
        inColumn.Get(cx0, cy0, cz0, cx1, cy1, cz1);
        const double tolerance = 1e-5;
        if (cz0 < z0 - tolerance || cz1 > z1 + tolerance) {
            return false;
        }
    }
    return true;
}

std::string quoted(const App::DocumentObject* obj)
{
    return std::string("'") + obj->Label.getValue() + "'";
}

}  // namespace

std::string studioCopyRefusal(
    FeatureAddSub* step,
    const Part::TopoShape& tool,
    const Part::TopoShape& part,
    const std::vector<gp_Trsf>& instances,
    const gp_Trsf& fromDocument
)
{
    const App::DocumentObject* owner = step ? step->StudioOwner.getValue() : nullptr;
    if (!owner || instances.empty()) {
        return {};
    }
    const std::string name = quoted(owner);
    // The T3 fix (Onshape oracle 9): an Up to next seed is re-run at each instance with Reapply
    // off too (R2), and an Up to face seed is copied (R3: Onshape copies it); the others stay
    // refused where the copy may differ (unverified on Onshape)
    const std::string later =
        ": a copy at each instance could differ from the instance computed there (turn Reapply "
        "on to compute each instance)";
    const bool hole = owner->isDerivedFrom<Hole>();

    // A face the feature starts or ends at: its plane must be every instance's own
    auto keepsFace = [&](const App::PropertyLinkSub* link) {
        auto pln = referencePlane(link);
        if (!pln) {
            return false;
        }
        const gp_Pln here = pln->Transformed(fromDocument);
        for (const gp_Trsf& t : instances) {
            if (!keepsPlane(t, here)) {
                return false;
            }
        }
        return true;
    };

    const std::string start = enumOf(owner, "StartType");
    if (start == "Reference" && !keepsFace(linkOf(owner, "StartReference"))) {
        return name + " starts at a reference face" + later;
    }
    if (start == "Part") {
        return name + " starts at the part's surface" + later;
    }

    struct End
    {
        std::string type;
        const char* face;
        const char* taper;
    };
    std::vector<End> ends;
    if (hole) {
        const std::string depth = enumOf(owner, "DepthType");
        if (depth != "Dimension") {
            return name + " is a hole whose depth type is " + depth + later;
        }
    }
    else {
        ends.push_back({enumOf(owner, "Type"), "UpToFace", "TaperAngle"});
        if (enumOf(owner, "SideType") == "Two sides") {
            ends.push_back({enumOf(owner, "Type2"), "UpToFace2", "TaperAngle2"});
        }
    }
    const bool extrude = owner->isDerivedFrom<FeatureExtrude>();
    for (const End& end : ends) {
        const std::string& type = end.type;
        if (type.empty() || type == "Length" || type == "TwoLengths" || type == "Angle"
            || type == "TwoAngles") {
            continue;
        }
        if (type == "UpToFirst") {
            return name + " ends Up to next" + later;
        }
        if (type == "UpToLast") {
            return name + " ends Up to last" + later;
        }
        if (type == "UpToShape") {
            return name + " ends Up to a shape" + later;
        }
        if (type == "UpToFace") {
            continue;  // Reapply off copies it, as Onshape does (oracle 9, R3)
        }
        if (type == "UpToVertex") {
            const TopoDS_Shape shape = referenceShape(linkOf(owner, end.face));
            TopExp_Explorer vertices(shape, TopAbs_VERTEX);
            const auto normal = profileNormal(owner);
            if (!vertices.More() || !normal) {
                return name + " ends Up to vertex" + later;
            }
            const gp_Pnt vertex =
                BRep_Tool::Pnt(TopoDS::Vertex(vertices.Current())).Transformed(fromDocument);
            const gp_Dir n = normal->Transformed(fromDocument);
            for (const gp_Trsf& t : instances) {
                const gp_Vec moved(vertex, vertex.Transformed(t));
                // An extrusion ends on the plane through the vertex parallel to its profile:
                // the instance's end plane is the copy's when the vertex stays on it. Any other
                // feature keeps its end only when the vertex stays where it is
                const double off = extrude ? std::fabs(moved.Dot(gp_Vec(n.Transformed(t))))
                                           : moved.Magnitude();
                if (off > lengthTolerance) {
                    return name
                        + " ends Up to vertex, and an instance moves the vertex off its end "
                          "plane"
                        + later;
                }
            }
            continue;
        }
        if (type == "ThroughAll") {
            const auto normal = profileNormal(owner);
            if (!extrude || step->getAddSubType() != FeatureAddSub::Type::Subtractive || !normal
                || boolOf(owner, "UseCustomVector")
                || std::fabs(floatOf(owner, end.taper)) > angleTolerance) {
                return name + " goes Through all" + later;
            }
            try {
                if (!everyCopySpans(tool, part, normal->Transformed(fromDocument), instances)) {
                    return name
                        + " goes Through all, and a copy doesn't span the part at its place"
                        + later;
                }
            }
            catch (const Standard_Failure&) {
                return name + " goes Through all" + later;
            }
            continue;
        }
        return name + " ends " + type + later;  // a type this rule doesn't know: not proved
    }
    return {};
}

// ------------------------------------------------------------------------------------------------
// Part patterns (FreeCAD-CH ops#654 slice 9, notes/patterns-design.md 3.1): the part mirror

// StudioList.cpp (declared where used)
PartDesignExport bool isStudioPartPattern(const App::DocumentObject* obj);
PartDesignExport std::vector<Body*> studioPartPatternSources(const App::DocumentObject* owner);

/// A part pattern's tool (the part mirror, slice 9): its source part as it is just before the
/// pattern (studioBaseAt), mirrored about MirrorPlane, in the document's frame, named with the
/// pattern's tag; null with why. Other part patterns, and feature patterns as owners, not yet
Part::TopoShape studioPatternTool(
    const App::DocumentObject* pattern,
    const Body* /*part*/,
    std::string* why
)
{
    auto fail = [why](const std::string& text) {
        if (why) {
            *why = text;
        }
        return Part::TopoShape();
    };
    if (!isStudioPartPattern(pattern)) {
        return fail("not yet (T1)");
    }
    if (!freecad_cast<const Mirrored*>(pattern)) {
        return fail(
            "A part pattern other than the part mirror is not done yet: pattern the part's "
            "features, or mirror it"
        );
    }
    const std::vector<Body*> sources = studioPartPatternSources(pattern);
    if (sources.empty()) {
        return fail(
            "No part to mirror: the source part is gone, merged or consumed at the mirror's place"
        );
    }
    if (sources.size() > 1) {
        return fail(
            "A part mirror takes one part, and " + std::to_string(sources.size())
            + " are picked: mirroring several parts at once is not done yet"
        );
    }
    const Body* source = sources.front();
    const std::optional<gp_Pln> plane = referencePlane(linkOf(pattern, "MirrorPlane"));
    if (!plane) {
        return fail("The mirror plane must be a plane or a planar face");
    }
    const Part::TopoShape base = studioBaseAt(pattern, source);
    if (base.isNull()) {
        return fail(std::string("'") + source->Label.getValue() + "' has no solid before the mirror");
    }
    gp_Trsf mirror;
    mirror.SetMirror(gp_Ax2(plane->Location(), plane->Axis().Direction()));
    // Left-handed: a copy (BRepBuilderAPI_Transform), as the Whole-shape engine makes
    Part::TopoShape out(pattern->getID(), pattern->getDocument()->getStringHasher());
    out.makeElementTransform(base, mirror, nullptr, Part::CopyType::copy);
    return out;
}

}  // namespace PartDesign
