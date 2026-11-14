// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2020 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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
#include <limits>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Section.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <gp_Pnt2d.hxx>
#include <BRepBndLib.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepIntCurveSurface_Inter.hxx>
#include <BRepProj_Projection.hxx>
#include <BRepTools.hxx>
#include <BRepFeat_MakePrism.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <Bnd_Box.hxx>
#include <gp.hxx>
#include <gp_Dir.hxx>
#include <gp_Lin.hxx>
#include <GProp_GProps.hxx>
#include <TopoDS.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Pln.hxx>
#include <Precision.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Wire.hxx>

#include <App/Datums.h>
#include <App/Document.h>
#include <App/ElementNamingUtils.h>
#include <App/ElementSolver.h>
#include <App/ElementSolverBatch.h>
#include <App/ObjectIdentifier.h>
#include <Base/Converter.h>
#include <Base/Tools.h>
#include <Mod/Part/App/DatumFeature.h>
#include <Mod/Part/App/ExtrusionHelper.h>
#include <Mod/Part/App/MassProperties.h>
#include <Mod/Part/App/Tools.h>
#include "Mod/Part/App/TopoShapeOpCode.h"
#include <Mod/Part/App/PartFeature.h>

#include "Body.h"
#include "FeatureExtrude.h"
#include "FeaturePad.h"
#include "FeaturePocket.h"
#include "StudioList.h"
#include "StudioOwner.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesign;

namespace PartDesign
{
// FeatureSketchBased.cpp: whether an extrusion along `dir` up to `upToFace` goes the other way
bool upToFaceBehind(const TopoShape& upToFace, const TopoShape& profile, const gp_Dir& dir);
}  // namespace PartDesign

const char* FeatureExtrude::SideTypesEnums[] = {"One side", "Two sides", "Symmetric", nullptr};

PROPERTY_SOURCE(PartDesign::FeatureExtrude, PartDesign::ProfileBased)

App::PropertyQuantityConstraint::Constraints FeatureExtrude::signedLengthConstraint
    = {-std::numeric_limits<double>::max(), std::numeric_limits<double>::max(), 1.0};
double FeatureExtrude::maxAngle = 90 - Base::toDegrees<double>(Precision::Angular());
App::PropertyAngle::Constraints FeatureExtrude::floatAngle = {-maxAngle, maxAngle, 1.0};

namespace
{
// What an extrusion up to `face` reaches, as generateSingleExtrusionSide(), getUpToFace() and
// makeElementPrismUntil() decide it, for the reference solver's equivalence probe (ops#7,
// Task 2 PR 5; the plan's Q3 (a)). Two candidates are equivalent only if the extrusion decides
// the same with either: the direction after getUpToFace()'s test of the line from the
// profile's centre against the face, a plane, and the face's limits removed, so that the
// unlimited plane is what the prism reaches. Then the result is that plane (the point where
// the profile's centre line meets it, and its normal turned towards the direction). Any other
// case (a curved or concave face, limits kept, a face the extrusion refuses) gives nothing.
// All shapes in the feature's coordinates.
std::optional<Base::Placement> upToFaceReached(TopoShape face, const TopoShape& profile, gp_Dir dir)
{
    if (upToFaceBehind(face, profile, dir)) {
        dir.Reverse();
    }
    if (face.shapeType(true) != TopAbs_FACE) {
        if (!face.hasSubShape(TopAbs_FACE)) {
            return std::nullopt;
        }
        face = face.getSubTopoShape(TopAbs_FACE, 1);
    }
    const TopoDS_Face& topoFace = TopoDS::Face(face.getShape());
    BRepAdaptor_Surface adapt(topoFace);
    if (adapt.GetType() != GeomAbs_Plane) {
        return std::nullopt;
    }
    gp_Pln plane = adapt.Plane();
    gp_Dir normal = plane.Axis().Direction();
    if (dir.IsNormal(normal, Precision::Confusion())) {
        return std::nullopt;
    }
    BRepExtrema_DistShapeShape distance(profile.getShape(), topoFace);
    if (distance.Value() < Precision::Confusion()) {
        return std::nullopt;
    }
    // OCCT's default integration can put the centre far off on a profile bounded by a long
    // curved B-spline (ops#428)
    gp_Pnt pCog;
    Part::MassProperties::centreOfMass(profile.getShape(), pCog);
    if (Part::Tools::isConcave(topoFace, pCog, dir) || !face.hasSubShape(TopAbs_WIRE)) {
        return std::nullopt;
    }
    bool removeLimits = false;
    for (auto& sketchFace : profile.getSubTopoShapes(TopAbs_FACE)) {
        TopoShape outerWire = sketchFace.splitWires();
        BRepProj_Projection projection(TopoDS::Wire(outerWire.getShape()), topoFace, dir);
        if (!projection.More() || !projection.Current().Closed()) {
            removeLimits = true;
            break;
        }
    }
    if (!removeLimits) {
        std::vector<TopoShape> wires;
        face.splitWires(&wires);
        for (auto& wire : wires) {
            BRepProj_Projection projection(TopoDS::Wire(wire.getShape()), profile.getShape(), -dir);
            if (projection.More()) {
                removeLimits = true;
                break;
            }
        }
    }
    if (!removeLimits) {
        return std::nullopt;
    }
    if (normal.Dot(dir) < 0) {
        normal.Reverse();
    }
    double t = gp_Vec(pCog, plane.Location()).Dot(gp_Vec(normal)) / dir.Dot(normal);
    gp_Pnt reached = pCog.Translated(t * gp_Vec(dir));
    return Base::Placement(
        Base::Vector3d(reached.X(), reached.Y(), reached.Z()),
        Base::Rotation(Base::Vector3d(0, 0, 1), Base::Vector3d(normal.X(), normal.Y(), normal.Z()))
    );
}

// Whether a side extruded up to a face from `profile` (in a plane with normal `normal`) went the
// way `dir` points (ops#73). getUpToFace() reverses a side whose face it doesn't find ahead, and
// the prism then goes to the face on whichever side it lies. One side, that pads backwards to
// the face; but a reversed side of a two-sided extrusion lands on the other side, and the XOR of
// the sides cancels the overlap. The prism lies on one side of the profile's plane, so the
// position of its centre of mass decides.
bool sideGoesAlong(
    const TopoShape& prism,
    const TopoShape& profile,
    const gp_Dir& normal,
    const gp_Dir& dir
)
{
    gp_Pnt prismCog;
    gp_Pnt profileCog;
    if (prism.isNull() || !Part::MassProperties::centreOfMass(prism.getShape(), prismCog)
        || !Part::MassProperties::centreOfMass(profile.getShape(), profileCog)) {
        return true;
    }
    double along = gp_Vec(profileCog, prismCog).Dot(gp_Vec(normal));
    return along * normal.Dot(dir) > -Precision::Confusion();
}

// Whether `prism` reaches the side of the plane through `profile` (normal `normal`) that `dir`
// points to, or at least the plane itself (ops#73). The one-prism path of a two-sided extrusion
// starts the up-to side at the other side's end, so a face between the sketch plane and that end
// would otherwise give a cut-down result where the two-prism path reports the side as unable to
// reach its face.
bool sideReachesPlane(
    const TopoShape& prism,
    const TopoShape& profile,
    const gp_Dir& normal,
    const gp_Dir& dir
)
{
    gp_Pnt profileCog;
    if (prism.isNull() || !Part::MassProperties::centreOfMass(profile.getShape(), profileCog)) {
        return true;
    }
    gp_Dir sideNormal = normal.Dot(dir) < 0 ? normal.Reversed() : normal;
    // In a frame whose Z axis is the plane's normal on dir's side, the prism's highest Z is how far
    // it reaches past the plane.
    gp_Trsf toPlane;
    toPlane.SetTransformation(gp_Ax3(profileCog, sideNormal));
    Bnd_Box box;
    BRepBndLib::AddOptimal(prism.getShape().Moved(TopLoc_Location(toPlane)), box, false, false);
    if (box.IsVoid()) {
        return true;
    }
    return box.CornerMax().Z() > -Precision::Confusion();
}

// The extrusion that made the far piece or element named `name`, for the reference solver
// (ops#524, PLAN decision 182, N2): the feature its projection's tag names (Data::projectionTag()),
// when that is `geo` or a feature before it on its BaseFeature chain; `geo` itself without a name.
// A later feature (a Pocket, a dress-up, a primitive as the Tip) passes the Pad's pieces on with
// their names, and has no up-to faces or sweep of its own.
const FeatureExtrude* makerOf(const App::GeoFeature* geo, const char* name)
{
    if (!name || !name[0]) {
        return dynamic_cast<const FeatureExtrude*>(geo);
    }
    const long tag = Data::projectionTag(name);
    if (tag <= 0) {
        return nullptr;
    }
    // The chain is short; the bound only guards against a cycle
    const App::DocumentObject* feature = geo;
    for (int steps = 0; feature && steps < 10000; ++steps) {
        if (feature->getID() == tag) {
            return dynamic_cast<const FeatureExtrude*>(feature);
        }
        const auto partDesign = dynamic_cast<const PartDesign::Feature*>(feature);
        // FreeCAD-CH ops#654 S2: a studio step's pieces carry its naming tag, its owner's ID: the
        // owner made them
        if (partDesign && partDesign->StudioOwner.getValue() && partDesign->namingTag() == tag) {
            return dynamic_cast<const FeatureExtrude*>(partDesign->StudioOwner.getValue());
        }
        feature = partDesign ? partDesign->getBaseObject(true) : nullptr;
    }
    return nullptr;
}

// Whether `geo`'s shape may be read with its current placement for the piece made by `extrude`:
// each shape was made under the placement it has now (ops#522's window, review prA1b-r1, for the
// extrusion; ops#524 for a later feature).
bool madeUnderPlacements(const App::GeoFeature* geo, const FeatureExtrude* extrude)
{
    if (!extrude->shapeMadeUnderPlacement()) {
        return false;
    }
    if (geo == extrude) {
        return true;
    }
    const auto later = dynamic_cast<const PartDesign::Feature*>(geo);
    return later && !placedAheadOfShape(later);
}

// The direction a Pad or Pocket swept its profile along, for the reference solver (PR 366 round
// 6): Direction holds the one computeDirection() last used, in the body's frame. Turned into the
// target's own frame, without its placement, where its elements' fingerprints are measured. The
// target is the extrusion, or a later feature passing its pieces on (ops#524, N2).
bool sweepDirection(const App::GeoFeature* geo, const char* name, Base::Vector3d& direction)
{
    const auto extrude = makerOf(geo, name);
    if (!extrude || (extrude != geo && !madeUnderPlacements(geo, extrude))) {
        return false;
    }
    direction = geo->Placement.getValue().getRotation().inverse().multVec(
        extrude->Direction.getValue()
    );
    return direction.Length() > Precision::Confusion();
}

const bool sweepDirectionRegistered = (App::setElementSweepDirectionFunction(&sweepDirection), true);

// What the up-to hooks below read: the extrusion that made the piece, its up-to objects with the
// face each names (none: all of its faces), its direction and the target's placement (the point's
// frame). False when it can't be told (upToFaces()).
struct UpToContext
{
    const FeatureExtrude* extrude = nullptr;
    std::vector<std::pair<const App::DocumentObject*, std::string>> refs;
    Base::Vector3d along;
    Base::Placement placement;
};

bool upToContext(const App::GeoFeature* geo, const char* name, UpToContext& context)
{
    const auto extrude = makerOf(geo, name);
    if (!extrude || std::strcmp(extrude->SideType.getValueAsString(), "One side") != 0
        || !madeUnderPlacements(geo, extrude)) {
        return false;
    }
    context.extrude = extrude;
    const std::string method = extrude->Type.getValueAsString();
    if (method == "UpToFace") {
        const auto& subs = extrude->UpToFace.getSubValues();
        if (subs.size() > 1) {
            return false;
        }
        context.refs.emplace_back(extrude->UpToFace.getValue(), subs.empty() ? std::string() : subs[0]);
    }
    else if (method == "UpToShape") {
        for (const auto& [ref, subs] : extrude->UpToShape.getSubListValues()) {
            if (subs.empty() || (subs.size() == 1 && subs[0].empty())) {
                context.refs.emplace_back(ref, std::string());
            }
            for (const auto& sub : subs) {
                if (!sub.empty()) {
                    context.refs.emplace_back(ref, sub);
                }
            }
        }
    }
    context.along = extrude->Direction.getValue();
    context.placement = geo->Placement.getValue();
    if (context.refs.empty() || context.along.Length() <= Precision::Confusion()) {
        return false;
    }
    for (const auto& ref : context.refs) {
        if (!ref.first || !ref.first->getNameInDocument() || ref.first->isDerivedFrom<App::Plane>()
            || ref.first->isDerivedFrom<Part::Datum>()) {
            return false;
        }
    }
    return true;
}

// An up-to object's faces (the one it names, or all) in its own frame, and the line through `at`
// (the target's point carried to the body's frame) along the sweep, in that frame too
bool upToFacesOf(
    const UpToContext& context,
    const App::DocumentObject* ref,
    const std::string& sub,
    const Base::Vector3d& at,
    std::vector<TopoShape>& faces,
    gp_Lin& line
)
{
    // The owner's placement, as Part::Feature::getTopoShape() applies it (Transform)
    Base::Matrix4D matrix;
    ref->getSubObject(nullptr, nullptr, &matrix);
    const Base::Placement inverse = Base::Placement(matrix).inverse();
    const TopoShape shape = Part::Feature::getTopoShape(
        ref,
        Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink,
        sub.empty() ? nullptr : sub.c_str()
    );
    if (shape.isNull() || !shape.hasSubShape(TopAbs_FACE)) {
        return false;
    }
    Base::Vector3d origin;
    Base::Vector3d direction;
    inverse.multVec(at, origin);
    inverse.getRotation().multVec(context.along, direction);
    line = gp_Lin(gp_Pnt(origin.x, origin.y, origin.z), gp_Dir(direction.x, direction.y, direction.z));
    faces = shape.getSubTopoShapes(TopAbs_FACE);
    return true;
}

// Where `line` meets `face` nearest its origin, inside the face or on its boundary, with the
// state there; none when it doesn't
std::optional<std::pair<gp_Pnt2d, TopAbs_State>> meeting(const TopoDS_Face& face, const gp_Lin& line)
{
    BRepIntCurveSurface_Inter hits;
    hits.Init(face, line, Precision::Confusion());
    std::optional<std::pair<gp_Pnt2d, TopAbs_State>> nearest;
    double distance = 0.0;
    for (; hits.More(); hits.Next()) {
        if ((hits.State() == TopAbs_IN || hits.State() == TopAbs_ON)
            && (!nearest || std::abs(hits.W()) < distance)) {
            nearest = std::make_pair(gp_Pnt2d(hits.U(), hits.V()), hits.State());
            distance = std::abs(hits.W());
        }
    }
    return nearest;
}

// The up-to faces under a far piece's point, for the reference solver (ops#522, PLAN decision
// 168; App::ElementUpToFacesFunction): the faces of the one-sided Pad's or Pocket's UpToFace or
// UpToShape that made the piece (makerOf(): the target, or a feature before it, ops#524), as
// generateSingleExtrusionSide() takes them, that the line through the point along the sweep
// meets, inside them or on their boundary. The point comes in the target's own frame and goes to
// the frame the up-to shapes are taken in (with their placements) by the target's current
// placement, so it moves with a profile moved by placement; then into each face owner's own frame,
// where the face's box, area, normal, outer wire and the foot (where the line meets it, ops#524)
// are measured, so a plate moved by its owner's placement is the same plate. With `all`, every
// up-to face too (its normal and foot: none). A datum plane or another unbounded face, UpToFirst
// and UpToLast (the base's faces), an empty shape list (the base), two sides, a face whose normal
// can't be taken at the point, and a shape not made under the current Placement (between a
// recompute's positionByPrevious() and its new shape: review prA1b-r1; a later feature's too,
// ops#524) can't be told.
bool upToFaces(
    const App::GeoFeature* geo,
    const char* name,
    const Base::Vector3d& point,
    std::vector<Data::ElementFingerprint::UpToFace>& faces,
    std::vector<Data::ElementFingerprint::UpToFace>* all
)
{
    faces.clear();
    if (all) {
        all->clear();
    }
    UpToContext context;
    if (!upToContext(geo, name, context)) {
        return false;
    }
    Base::Vector3d at;
    context.placement.multVec(point, at);
    try {
        for (const auto& [ref, sub] : context.refs) {
            std::vector<TopoShape> shapeFaces;
            gp_Lin line;
            if (!upToFacesOf(context, ref, sub, at, shapeFaces, line)) {
                return false;
            }
            for (const auto& face : shapeFaces) {
                const TopoDS_Face& topoFace = TopoDS::Face(face.getShape());
                Bnd_Box box;
                BRepBndLib::AddOptimal(topoFace, box, false, false);
                if (box.IsVoid() || box.IsOpen()) {
                    return false;
                }
                box.SetGap(0.0);
                double x0 {}, y0 {}, z0 {}, x1 {}, y1 {}, z1 {};
                box.Get(x0, y0, z0, x1, y1, z1);
                const std::array<double, 6> corners {x0, y0, z0, x1, y1, z1};
                if (std::any_of(corners.begin(), corners.end(), [](double v) {
                        return Precision::IsInfinite(v);
                    })) {
                    return false;
                }
                GProp_GProps props;
                BRepGProp::SurfaceProperties(topoFace, props);
                const TopoDS_Wire outer = BRepTools::OuterWire(topoFace);
                GProp_GProps wireProps;
                if (outer.IsNull()) {
                    return false;
                }
                BRepGProp::LinearProperties(outer, wireProps);
                if (wireProps.Mass() <= Precision::Confusion()) {
                    return false;
                }
                const gp_Pnt wire = wireProps.CentreOfMass();
                Data::ElementFingerprint::UpToFace upTo;
                upTo.owner = ref->getNameInDocument();
                upTo.boxMin = Base::Vector3d(x0, y0, z0);
                upTo.boxMax = Base::Vector3d(x1, y1, z1);
                upTo.area = props.Mass();
                upTo.wireCentre = Base::Vector3d(wire.X(), wire.Y(), wire.Z());
                if (all) {
                    all->push_back(upTo);
                }
                // The meeting nearest to the point
                const auto met = meeting(topoFace, line);
                if (!met) {
                    continue;
                }
                BRepAdaptor_Surface surface(topoFace);
                gp_Pnt on;
                gp_Vec du;
                gp_Vec dv;
                surface.D1(met->first.X(), met->first.Y(), on, du, dv);
                const gp_Vec normal = du.Crossed(dv);
                if (normal.Magnitude() <= gp::Resolution()) {
                    return false;
                }
                upTo.normal = Base::Vector3d(normal.X(), normal.Y(), normal.Z()).Normalize();
                upTo.foot = Base::Vector3d(on.X(), on.Y(), on.Z());
                faces.push_back(std::move(upTo));
            }
        }
    }
    catch (const Standard_Failure&) {
        return false;
    }
    catch (const Base::Exception&) {
        return false;
    }
    return true;
}

const bool upToFacesRegistered = (App::setElementUpToFacesFunction(&upToFaces), true);

// Whether a lone far piece slid within its up-to face, for the reference solver (ops#524, PLAN
// decisions 182 and 199 (3); App::ElementUpToPathFunction). In the saved face's owner's own frame:
// the line along the sweep through the piece's point now (carried as upToFaces() carries it) meets
// exactly one of that owner's up-to faces, inside it and not on its boundary, and so does the line
// through the saved foot, on the same face; then the path stays on the face when no boundary edge
// of it (its holes' included) meets the strip that the segment between the two meetings spans
// along the sweep: an exact section, no sampling. A piece moved along the sweep alone stays at its
// place. A seam edge met, and nothing else, can't be told (the path may go round a periodic face
// through it); nor can the rest that isn't one meeting inside the face at each end.
std::optional<bool> upToPath(
    const App::GeoFeature* geo,
    const char* name,
    const Data::ElementFingerprint::UpToFace& saved,
    const Base::Vector3d& point
)
{
    UpToContext context;
    if (!saved.foot || !upToContext(geo, name, context)) {
        return std::nullopt;
    }
    Base::Vector3d at;
    context.placement.multVec(point, at);
    try {
        std::optional<TopoDS_Face> under;
        gp_Pnt now;
        gp_Dir along;
        for (const auto& [ref, sub] : context.refs) {
            if (saved.owner != ref->getNameInDocument()) {
                continue;
            }
            std::vector<TopoShape> shapeFaces;
            gp_Lin line;
            if (!upToFacesOf(context, ref, sub, at, shapeFaces, line)) {
                return std::nullopt;
            }
            along = line.Direction();
            for (const auto& face : shapeFaces) {
                const TopoDS_Face& topoFace = TopoDS::Face(face.getShape());
                const auto met = meeting(topoFace, line);
                if (!met) {
                    continue;
                }
                if (under || met->second != TopAbs_IN) {
                    return std::nullopt;  // two faces, or on the boundary
                }
                under = topoFace;
                now = BRepAdaptor_Surface(topoFace).Value(met->first.X(), met->first.Y());
            }
        }
        if (!under) {
            return std::nullopt;
        }
        const gp_Pnt foot(saved.foot->x, saved.foot->y, saved.foot->z);
        const auto old = meeting(*under, gp_Lin(foot, along));
        if (!old || old->second != TopAbs_IN) {
            return std::nullopt;
        }
        const gp_Pnt from = BRepAdaptor_Surface(*under).Value(old->first.X(), old->first.Y());
        // The segment's part across the sweep; none: the piece stayed where it was, seen along it
        gp_Vec across(from, now);
        across -= gp_Vec(along) * across.Dot(gp_Vec(along));
        const double length = across.Magnitude();
        if (length <= Precision::Confusion()) {
            return true;
        }
        // The strip: from `from` across to `now`, and far along the sweep both ways, past the face
        Bnd_Box box;
        BRepBndLib::AddOptimal(*under, box, false, false);
        if (box.IsVoid() || box.IsOpen()) {
            return std::nullopt;
        }
        const double reach = std::sqrt(box.SquareExtent())
            + from.Distance(box.CornerMin()) + from.Distance(box.CornerMax()) + 1.0;
        const gp_Dir x(across);
        const gp_Ax3 frame(from, x.Crossed(along), x);  // its Y axis is the sweep
        BRepBuilderAPI_MakeFace strip(gp_Pln(frame), 0.0, length, -reach, reach);
        if (!strip.IsDone()) {
            return std::nullopt;
        }
        // Whether the strip meets any of `edges`; empty when the section fails
        auto meets = [&](const TopoDS_Compound& edges) -> std::optional<bool> {
            BRepAlgoAPI_Section section(strip.Face(), edges, false);
            section.Build();
            if (!section.IsDone()) {
                return std::nullopt;
            }
            const TopoDS_Shape& met = section.Shape();
            return TopExp_Explorer(met, TopAbs_VERTEX).More()
                || TopExp_Explorer(met, TopAbs_EDGE).More();
        };
        TopoDS_Compound boundary;
        TopoDS_Compound seams;
        BRep_Builder builder;
        builder.MakeCompound(boundary);
        builder.MakeCompound(seams);
        bool anySeam = false;
        for (TopExp_Explorer edges(*under, TopAbs_EDGE); edges.More(); edges.Next()) {
            const TopoDS_Edge& edge = TopoDS::Edge(edges.Current());
            const bool seam = BRep_Tool::IsClosed(edge, *under);
            builder.Add(seam ? seams : boundary, edge);
            anySeam = anySeam || seam;
        }
        const auto crosses = meets(boundary);
        if (!crosses || *crosses) {
            return crosses ? std::optional<bool>(false) : std::nullopt;
        }
        if (anySeam) {
            const auto throughSeam = meets(seams);
            if (!throughSeam || *throughSeam) {
                return std::nullopt;
            }
        }
        return true;
    }
    catch (const Standard_Failure&) {
        return std::nullopt;
    }
    catch (const Base::Exception&) {
        return std::nullopt;
    }
}

const bool upToPathRegistered = (App::setElementUpToPathFunction(&upToPath), true);
}  // namespace

FeatureExtrude::FeatureExtrude()
{
    // The reference solver (ops#7, Task 2 PR 5): the pieces of a split UpToFace are equivalent
    // when the extrusion reaches the same with each (upToFaceReached()). Only side 1 of a
    // one-sided or symmetric extrusion from the profile plane is probed; elsewhere, and for
    // UpToFace2, no candidates are equivalent.
    UpToFace.setElementPolicy(App::PropertyLinkBase::ElementPolicy::Equivalent);
    UpToFace.setEquivalenceProbe(
        [this](int index, const std::string& sub) -> std::optional<Base::Placement> {
            const std::string side = SideType.getValueAsString();
            if (index != 0 || std::strcmp(Type.getValueAsString(), "UpToFace") != 0
                || (side != "One side" && side != "Symmetric")
                || std::strcmp(StartType.getValueAsString(), "Profile plane") != 0) {
                return std::nullopt;
            }
            try {
                App::DocumentObject* ref = UpToFace.getValue();
                if (!ref || ref->isDerivedFrom<App::Plane>()) {
                    return std::nullopt;
                }
                TopoShape profile = getTopoShapeVerifiedFace();
                // buildExtrusion()'s direction, without computeDirection()'s property writes
                Base::Vector3d sketchVector = getProfileNormal();
                Base::Vector3d direction = sketchVector;
                if (UseCustomVector.getValue()) {
                    const Base::Vector3d& custom = Direction.getValue();
                    if (std::fabs(custom.x) >= Precision::Confusion()
                        || std::fabs(custom.y) >= Precision::Confusion()
                        || std::fabs(custom.z) >= Precision::Confusion()) {
                        direction = custom;
                    }
                }
                else if (ReferenceAxis.getValue()) {
                    Base::Vector3d base;
                    Base::Vector3d axis;
                    getAxis(
                        ReferenceAxis.getValue(),
                        ReferenceAxis.getSubValues(),
                        base,
                        axis,
                        ForbiddenAxis::NotPerpendicularWithNormal
                    );
                    direction = sweepsAgainstNormal() ? -axis : axis;
                }
                auto invObjLoc = getLocation().Inverted();
                gp_Dir dir(direction.x, direction.y, direction.z);
                dir.Transform(invObjLoc.Transformation());
                if (Reversed.getValue()) {
                    dir.Reverse();
                }
                profile.move(invObjLoc);
                TopoShape face = Part::Feature::getTopoShape(
                    ref,
                    Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                        | Part::ShapeOption::Transform,
                    sub.c_str()
                );
                face.move(invObjLoc);
                return upToFaceReached(face, profile, dir);
            }
            catch (Base::Exception&) {
            }
            catch (Standard_Failure&) {
            }
            return std::nullopt;
        }
    );
}

short FeatureExtrude::mustExecute() const
{
    if (Placement.isTouched() || SideType.isTouched() || Type.isTouched() || Type2.isTouched()
        || Length.isTouched() || Length2.isTouched() || TaperAngle.isTouched()
        || TaperAngle2.isTouched() || UseCustomVector.isTouched() || Direction.isTouched()
        || ReferenceAxis.isTouched() || AlongSketchNormal.isTouched() || Offset.isTouched()
        || Offset2.isTouched() || StartType.isTouched() || StartOffset.isTouched()
        || StartReference.isTouched() || UpToFace.isTouched() || UpToFace2.isTouched()
        || UpToShape.isTouched() || UpToShape2.isTouched()) {
        return 1;
    }
    return ProfileBased::mustExecute();
}

Base::Vector3d FeatureExtrude::computeDirection(const Base::Vector3d& sketchVector, bool inverse)
{
    Base::Vector3d extrudeDirection;

    if (!UseCustomVector.getValue()) {
        if (!ReferenceAxis.getValue()) {
            // use sketch's normal vector for direction
            extrudeDirection = sketchVector;
            AlongSketchNormal.setReadOnly(true);
        }
        else {
            // update Direction from ReferenceAxis
            App::DocumentObject* pcReferenceAxis = ReferenceAxis.getValue();
            const std::vector<std::string>& subReferenceAxis = ReferenceAxis.getSubValues();
            Base::Vector3d base;
            Base::Vector3d dir;
            getAxis(pcReferenceAxis, subReferenceAxis, base, dir, ForbiddenAxis::NotPerpendicularWithNormal);
            // The class's direction, not the Operation's: a Pad can cut and a Pocket can add
            // (FreeCAD-CH ops#640), and each keeps the side it sweeps to
            extrudeDirection = inverse ? -dir : dir;
        }
    }
    else {
        // use the given vector
        // if null vector, use sketchVector
        if ((fabs(Direction.getValue().x) < Precision::Confusion())
            && (fabs(Direction.getValue().y) < Precision::Confusion())
            && (fabs(Direction.getValue().z) < Precision::Confusion())) {
            Direction.setValue(sketchVector);
        }
        extrudeDirection = Direction.getValue();
    }

    // disable options of UseCustomVector
    Direction.setReadOnly(!UseCustomVector.getValue());
    ReferenceAxis.setReadOnly(UseCustomVector.getValue());
    // UseCustomVector allows AlongSketchNormal but !UseCustomVector does not forbid it
    if (UseCustomVector.getValue()) {
        AlongSketchNormal.setReadOnly(false);
    }

    // explicitly set the Direction so that the dialog shows also the used direction
    // if the sketch's normal vector was used
    Direction.setValue(extrudeDirection);
    return extrudeDirection;
}

bool FeatureExtrude::hasTaperedAngle() const
{
    return fabs(TaperAngle.getValue()) > Base::toRadians(Precision::Angular())
        || fabs(TaperAngle2.getValue()) > Base::toRadians(Precision::Angular());
}

void FeatureExtrude::onChanged(const App::Property* prop)
{
    if (prop == &Midplane && !isRestoring() && !migratingDeprecatedProperties) {
        // Deprecation notice: Midplane property is deprecated and has been replaced by SideType in
        // FreeCAD 1.1 when FeatureExtrude was refactored.
        const char* impliedSideType = Midplane.getValue() ? "Symmetric" : "One side";

        // Scripts routinely assign every property, so only scream when the write actually
        // asks for something SideType is not already saying.
        if (SideType.getValueAsString() != std::string(impliedSideType)) {
            App::DocumentObject* obj = Profile.getValue();
            auto baseName = obj ? obj->getNameInDocument() : "";
            Base::Console().warning(
                "The 'Midplane' property being set for the extrusion of %s is deprecated and has "
                "been replaced by the 'SideType' property in FeatureExtrude; assuming "
                "SideType='%s'. Please update your script, this property will be removed in a"
                " future version.\n",
                baseName,
                impliedSideType
            );
            SideType.setValue(impliedSideType);
        }
    }
    ProfileBased::onChanged(prop);
}

TopoShape FeatureExtrude::makeShellFromUpToShape(TopoShape shape, TopoShape sketchshape, gp_Dir& dir)
{

    // Find nearest/furthest face
    std::vector<Part::cutTopoShapeFaces> cfaces = Part::findAllFacesCutBy(shape, sketchshape, dir);
    if (cfaces.empty()) {
        dir = -dir;
        cfaces = Part::findAllFacesCutBy(shape, sketchshape, dir);
    }

    if (cfaces.empty()) {
        return shape;
    }

    struct Part::cutTopoShapeFaces* nearFace {};
    struct Part::cutTopoShapeFaces* farFace {};
    nearFace = farFace = &cfaces.front();
    for (auto& face : cfaces) {
        if (face.distsq > farFace->distsq) {
            farFace = &face;
        }
        else if (face.distsq < nearFace->distsq) {
            nearFace = &face;
        }
    }

    if (nearFace != farFace) {
        std::vector<TopoShape> faceList;
        for (auto& face : shape.getSubTopoShapes(TopAbs_FACE)) {
            if (!(face == farFace->face)) {
                // don't use the last face so the shell is open
                // and OCC works better
                faceList.push_back(face);
            }
        }
        return shape.makeElementCompound(faceList);
    }
    return shape;
}

void FeatureExtrude::updateProperties()
{
    std::string sideTypeVal = SideType.getValueAsString();
    std::string methodSide1 = Type.getValueAsString();
    std::string methodSide2 = Type2.getValueAsString();

    bool isLength1Enabled = false;
    bool isTaper1Visible = false;
    bool isUpToFace1Enabled = false;
    bool isUpToShape1Enabled = false;
    bool isOffset1Enabled = false;

    bool isType2Enabled = false;
    bool isLength2Enabled = false;
    bool isTaper2Visible = false;
    bool isUpToFace2Enabled = false;
    bool isUpToShape2Enabled = false;
    bool isOffset2Enabled = false;

    bool currentAlongSketchNormalEnabled = false;

    auto configureSideProperties = [&](const std::string& method,
                                       bool& lengthEnabled,
                                       bool& taperVisible,
                                       bool& upToFaceEnabled,
                                       bool& upToShapeEnabled,
                                       bool& localAlongSketchNormal,
                                       bool& localOffset) {
        if (method == "Length") {
            lengthEnabled = true;
            taperVisible = true;
            localAlongSketchNormal = true;
        }
        else if (method == "UpToFace" || method == "UpToVertex") {
            // up to a vertex: UpToFace holds the vertex (ops#640 rank 22)
            upToFaceEnabled = true;
            localOffset = true;
        }
        else if (method == "UpToShape") {
            upToShapeEnabled = true;
            localOffset = true;
        }
        else if (method == "UpToLast" || method == "UpToFirst") {
            localOffset = true;
        }
        else if (method == "ThroughAll") {
            taperVisible = true;
        }
    };

    if (sideTypeVal == "One side") {
        bool side1ASN = false;
        configureSideProperties(
            methodSide1,
            isLength1Enabled,
            isTaper1Visible,
            isUpToFace1Enabled,
            isUpToShape1Enabled,
            side1ASN,
            isOffset1Enabled
        );
        currentAlongSketchNormalEnabled = side1ASN;
    }
    else if (sideTypeVal == "Two sides") {
        isType2Enabled = true;

        bool side1ASN = false;
        configureSideProperties(
            methodSide1,
            isLength1Enabled,
            isTaper1Visible,
            isUpToFace1Enabled,
            isUpToShape1Enabled,
            side1ASN,
            isOffset1Enabled
        );

        bool side2ASN = false;
        configureSideProperties(
            methodSide2,
            isLength2Enabled,
            isTaper2Visible,
            isUpToFace2Enabled,
            isUpToShape2Enabled,
            side2ASN,
            isOffset2Enabled
        );

        currentAlongSketchNormalEnabled = side1ASN || side2ASN;  // Enable if either side needs it
    }
    else if (sideTypeVal == "Symmetric") {
        bool symASN = false;
        configureSideProperties(
            methodSide1,
            isLength1Enabled,
            isTaper1Visible,
            isUpToFace1Enabled,
            isUpToShape1Enabled,
            symASN,
            isOffset1Enabled
        );
        currentAlongSketchNormalEnabled = symASN;
    }

    Length.setReadOnly(!isLength1Enabled);
    TaperAngle.setReadOnly(!isTaper1Visible);
    UpToFace.setReadOnly(!isUpToFace1Enabled);
    UpToShape.setReadOnly(!isUpToShape1Enabled);
    Offset.setReadOnly(!isOffset1Enabled);

    Type2.setReadOnly(!isType2Enabled);
    Length2.setReadOnly(!isLength2Enabled);
    TaperAngle2.setReadOnly(!isTaper2Visible);
    UpToFace2.setReadOnly(!isUpToFace2Enabled);
    UpToShape2.setReadOnly(!isUpToShape2Enabled);
    Offset2.setReadOnly(!isOffset2Enabled);

    const bool isStartOffsetEnabled = std::strcmp(StartType.getValueAsString(), "Profile plane") != 0;
    StartOffset.setReadOnly(!isStartOffsetEnabled);
    StartReference.setReadOnly(std::strcmp(StartType.getValueAsString(), "Reference") != 0);

    AlongSketchNormal.setReadOnly(!currentAlongSketchNormalEnabled);
}

void FeatureExtrude::setupObject()
{
    ProfileBased::setupObject();
}

double FeatureExtrude::getStartOffset() const
{
    const char* startType = StartType.getValueAsString();
    if (std::strcmp(startType, "Profile plane") == 0) {
        return 0.0;
    }

    gp_Dir dir = Base::convertTo<gp_Dir>(Direction.getValue());
    if (Reversed.getValue()) {
        dir.Reverse();
    }
    if (std::strcmp(startType, "Offset") == 0) {
        return StartOffset.getValue();
    }

    TopLoc_Location identity;
    return getStartReferenceOffset(
        getTopoShapeVerifiedFace(),
        StartReference,
        dir,
        StartOffset.getValue(),
        identity
    );
}

void FeatureExtrude::noteReachesNothing()
{
    // Onshape's words (hands-on check R7, ops#640): an info, the feature stays valid
    static const std::string text = "Selected tools and targets do not intersect";
    // A sibling says it in its own words: "doesn't touch <part>" (warnIfMissing, ops#325)
    if (SiblingOf.getValue()) {
        return;
    }
    if (auto doc = getDocument()) {
        const char* previous = doc->getWarningDescription(this);
        doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + text : text);
    }
}

namespace
{
// Whether the boxes of a Remove's or an Intersect's tool and of its base are apart (ops#640 H3)
bool boxesApart(const TopoShape& tool, const TopoShape& base)
{
    Bnd_Box toolBox;
    Bnd_Box baseBox;
    BRepBndLib::Add(tool.getShape(), toolBox, /*useTriangulation=*/false);
    BRepBndLib::Add(base.getShape(), baseBox, /*useTriangulation=*/false);
    toolBox.Enlarge(Precision::Confusion());
    return toolBox.IsOut(baseBox);
}

double volumeOf(const TopoShape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape.getShape(), props);
    return props.Mass();
}

// Whether a Remove's tool missed its base (ops#640 H3), the cut done: judged by volume, not by
// contact, so a tool that only shares a face with the base (a sketch on the top face, the cut
// pointing out of the part: hands-on check R5) counts as a miss. The tolerance scales with the
// tool (a real cut removes a fair part of it) plus the base's own rounding
bool cutMissed(const TopoShape& tool, const TopoShape& base, const TopoShape& result)
{
    if (result.isNull() || !result.hasSubShape(TopAbs_SOLID)) {
        return false;
    }
    const double baseVolume = volumeOf(base);
    const double removed = baseVolume - volumeOf(result);
    const double tolerance = 1e-6 * std::fabs(volumeOf(tool)) + 1e-9 * std::fabs(baseVolume);
    return std::fabs(removed) <= tolerance;
}

// The point an end up to a vertex goes to (FreeCAD-CH ops#640 rank 22), in global coordinates:
// the linked vertex (of a part, a sketch or a datum point), or a coordinate system's point
gp_Pnt upToVertexPoint(const App::PropertyLinkSub& link)
{
    App::DocumentObject* ref = link.getValue();
    if (!ref) {
        throw Base::ValueError(QT_TRANSLATE_NOOP("Exception", "Select the vertex to extrude up to"));
    }
    const auto& subs = link.getSubValues();
    if (subs.size() > 1) {
        throw Base::ValueError(
            QT_TRANSLATE_NOOP("Exception", "The vertex link names several elements; select one vertex")
        );
    }
    const std::string sub = subs.empty() ? std::string() : subs.front();
    // A coordinate system's or an origin's point, linked through the system (the field's pick)
    App::DocumentObject* element = ref;
    if (!sub.empty() && ref->getDocument()) {
        if (auto named = ref->getDocument()->getObject(sub.c_str())) {
            element = named;
        }
    }
    if (auto point = freecad_cast<App::Point*>(element)) {
        return Base::convertTo<gp_Pnt>(point->getBasePoint());
    }
    const TopoShape shape = Part::Feature::getTopoShape(
        ref,
        Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
            | Part::ShapeOption::Transform,
        sub.empty() ? nullptr : sub.c_str()
    );
    if (shape.isNull() || shape.hasSubShape(TopAbs_EDGE)
        || shape.countSubShapes(TopAbs_VERTEX) != 1) {
        throw Base::ValueError(
            QT_TRANSLATE_NOOP("Exception", "Up to vertex: the reference isn't a vertex or a point")
        );
    }
    return BRep_Tool::Pnt(TopoDS::Vertex(shape.getSubShape(TopAbs_VERTEX, 1)));
}

// The plane (a point and its normal, in global coordinates) of the face a side goes up to, where
// that side is better built blind when the plane is parallel to the profile plane (FreeCAD-CH
// ops#751; the caller tests that in the frame it builds in): the face is planar, and the profile
// holds an edge that is neither a line nor a circle (an ellipse, a spline). A straight extrusion
// ends on a plane parallel to its profile whatever the face's extent (the up-to prism takes the
// whole plane of a face smaller than the profile too), so the blind side reaching it is the same
// solid. BRepFeat's prism returns such an edge's end on the face as an approximated intersection
// curve, in pieces (the replica's #161: two B-splines where Onshape has one ellipse, so a later
// feature finds two edges, and two faces, for one). Nothing for any other reference (a datum, a
// curved face) or profile (lines and circles end exact either way, and keep their names)
std::optional<gp_Ax1> upToPlaneForBlindSide(
    const App::PropertyLinkSub& link,
    const TopoShape& profile
)
{
    App::DocumentObject* ref = link.getValue();
    const auto& subs = link.getSubValues();
    if (!ref || subs.size() != 1 || subs.front().empty() || profile.isNull()) {
        return std::nullopt;
    }
    bool approximated = false;
    for (TopExp_Explorer it(profile.getShape(), TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        const GeomAbs_CurveType type = BRepAdaptor_Curve(edge).GetType();
        if (type != GeomAbs_Line && type != GeomAbs_Circle) {
            approximated = true;
            break;
        }
    }
    if (!approximated) {
        return std::nullopt;
    }
    TopoShape shape;
    try {
        shape = Part::Feature::getTopoShape(
            ref,
            Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                | Part::ShapeOption::Transform,
            subs.front().c_str()
        );
    }
    catch (const Base::Exception&) {
        return std::nullopt;
    }
    catch (const Standard_Failure&) {
        return std::nullopt;
    }
    if (shape.isNull() || shape.countSubShapes(TopAbs_FACE) != 1) {
        return std::nullopt;
    }
    const BRepAdaptor_Surface surface(TopoDS::Face(shape.getSubShape(TopAbs_FACE, 1)));
    if (surface.GetType() != GeomAbs_Plane) {
        return std::nullopt;
    }
    return surface.Plane().Axis();
}

// Set while a studio owner builds one region of its profile (ops#654 S2), so that the region's
// own side is built as today's, against the one part it meets
thread_local bool ownerRegionRunning = false;

/* FreeCAD-CH ops#654 T3 (notes/patterns-design.md 3.3, Reapply): set while a pattern with Reapply
 * on re-runs this extrusion at one of its instances. The run is the seed's own, in the feature's
 * frame, against the instance's surroundings carried back onto the seed by the inverse instance
 * transform: the base at that instance and the fixed references (the up-to face, shape or vertex:
 * Onshape re-intersects the same face per instance, O6). The profile, its support face and the
 * direction stay. The tool the run makes, moved by the instance transform, is the instance
 * re-solved where it is (a rigid motion or a mirror carries the whole construction). The run
 * writes nothing of the feature: its tool goes here */
struct ReapplyRun
{
    gp_Trsf toSeed;         ///< the instance's surroundings onto the seed's, in the feature's frame
    TopoShape base;         ///< the base at the instance, carried onto the seed (feature's frame)
    std::string partLabel;  ///< the pattern's part, for messages
    TopoShape tool;         ///< the tool made (out)
};
thread_local ReapplyRun* reapplyRun = nullptr;

/** A studio owner's "Up to next" for one region against the one part it meets (FreeCAD-CH ops#654
 * S2, notes/onshape-facts.md O8h): the region's sweep ahead (reach long) split by the part, keeping
 * the pieces that start on the region. Starting outside the part they are the gap up to where the
 * part begins, so a stepped bottom gives a stepped tool; starting inside it, the material up to
 * where it ends. A region that starts partly inside and partly outside, or part of which meets
 * nothing ahead, fails the whole feature (the loud choice; unverified on Onshape) */
TopoShape ownerUpToNext(
    const FeatureExtrude& owner,
    const TopoShape& region,
    const TopoShape& part,
    const gp_Dir& dir,
    double reach,
    const std::string& which
)
{
    const double tol = Precision::Confusion() * 10;
    TopoDS_Face start = TopoDS::Face(region.getShape());
    BRepAdaptor_Surface startSurface(start);
    if (startSurface.GetType() != GeomAbs_Plane) {
        throw Base::ValueError(which + " is not planar");
    }
    const gp_Pln plane = startSurface.Plane();
    GProp_GProps startProps;
    BRepGProp::SurfaceProperties(start, startProps);
    const double startArea = startProps.Mass();
    auto alongMax = [&](const TopoDS_Shape& shape, double sign = 1.0) {
        double most = -std::numeric_limits<double>::max();
        for (TopExp_Explorer it(shape, TopAbs_VERTEX); it.More(); it.Next()) {
            gp_Pnt p = BRep_Tool::Pnt(TopoDS::Vertex(it.Current()));
            most = std::max(most, sign * gp_Vec(p.XYZ()).Dot(gp_Vec(dir)));
        }
        return sign * most;
    };
    // The nearest the start comes along dir: the sweep's far end lies reach beyond it
    const double s0 = alongMax(start, -1.0);
    // The area of solid's faces lying on the region's plane: its share of the start
    auto areaOnStart = [&](const TopoDS_Shape& solid) {
        double area = 0.0;
        for (TopExp_Explorer it(solid, TopAbs_FACE); it.More(); it.Next()) {
            const TopoDS_Face& face = TopoDS::Face(it.Current());
            BRepAdaptor_Surface surface(face);
            if (surface.GetType() != GeomAbs_Plane) {
                continue;
            }
            const gp_Pln facePlane = surface.Plane();
            if (!facePlane.Axis().IsParallel(plane.Axis(), Precision::Angular())
                || plane.Distance(facePlane.Location()) > tol) {
                continue;
            }
            GProp_GProps props;
            BRepGProp::SurfaceProperties(face, props);
            area += props.Mass();
        }
        return area;
    };

    TopoShape probe = owner.makeTopoShape();
    probe.makeElementPrism(region, reach * gp_Vec(dir));
    TopoShape outside = owner.makeTopoShape();
    outside.makeElementCut({probe, part});
    TopoShape inside = owner.makeTopoShape();
    inside.makeElementBoolean(Part::OpCodes::Common, {probe, part});

    auto startingPieces = [&](const TopoShape& shape, double& area) {
        std::vector<TopoShape> pieces;
        area = 0.0;
        if (shape.isNull()) {
            return pieces;
        }
        for (const TopoShape& solid : shape.getSubTopoShapes(TopAbs_SOLID)) {
            const double share = areaOnStart(solid.getShape());
            if (share > tol) {
                area += share;
                pieces.push_back(solid);
            }
        }
        return pieces;
    };
    double outsideArea = 0.0;
    double insideArea = 0.0;
    std::vector<TopoShape> gap = startingPieces(outside, outsideArea);
    std::vector<TopoShape> material = startingPieces(inside, insideArea);
    const double areaTol = std::max(1e-6, startArea * 1e-6);
    std::vector<TopoShape> pieces;
    if (std::abs(outsideArea - startArea) <= areaTol && insideArea <= areaTol) {
        pieces = std::move(gap);
    }
    else if (std::abs(insideArea - startArea) <= areaTol && outsideArea <= areaTol) {
        pieces = std::move(material);
    }
    else {
        throw Base::ValueError(which + " starts partly inside the part and partly outside it");
    }
    for (const TopoShape& piece : pieces) {
        if (alongMax(piece.getShape()) >= s0 + reach - tol * 100) {
            throw Base::ValueError(which + ": part of it meets nothing ahead");
        }
    }
    if (pieces.size() == 1) {
        return pieces.front();
    }
    TopoShape tool = owner.makeTopoShape();
    tool.makeElementFuse(pieces, Part::OpCodes::Extrude);
    return tool;
}

/** A studio owner's "Up to next" (UpToFirst) or "Up to last", Onshape's rule (FreeCAD-CH ops#654
 * S2, notes/onshape-facts.md O8): each region (face) of the profile goes against the one in-scope
 * part its sweep ahead meets, by side(region, that part's shape); the tool is the regions' prisms
 * fused. A region that meets no part ahead, or two (touching ones too, O8e), fails the whole
 * feature: no partial result, one error naming the region. Shapes are in the owner's own frame
 * (invObjLoc applied), as its profile is */
template<typename Side>
TopoShape ownerUpToPerRegion(
    const FeatureExtrude& owner,
    const TopoShape& profile,
    const std::string& method,
    const gp_Dir& dir,
    const TopLoc_Location& invObjLoc,
    Side side
)
{
    const std::string mode = method == "UpToFirst" ? "Up to next" : "Up to last";
    // The in-scope parts at the owner's place: the document's frame to its container's, then
    // its own
    const Base::Placement container =
        owner.globalPlacement() * owner.Placement.getValue().inverse();
    std::vector<std::pair<std::string, TopoShape>> parts;
    Bnd_Box all;
    BRepBndLib::Add(profile.getShape(), all);
    auto label = [](const Body* part) {
        return std::string("'") + part->Label.getValue() + "'";
    };
    if (reapplyRun) {
        // A pattern's instance (ops#654 T3): the pattern's part at the instance, in this frame
        if (!reapplyRun->base.isNull()) {
            BRepBndLib::Add(reapplyRun->base.getShape(), all);
            parts.emplace_back(reapplyRun->partLabel, reapplyRun->base);
        }
    }
    else {
        for (auto part : studioScopeOf(&owner)) {
            TopoShape shape = studioBaseAt(&owner, part);
            if (shape.isNull()) {
                continue;
            }
            shape.transformShape(container.inverse().toMatrix(), false, true);
            shape.move(invObjLoc);
            BRepBndLib::Add(shape.getShape(), all);
            parts.emplace_back(label(part), shape);
        }
    }
    all.SetGap(0.0);
    const double reach = 2.02 * std::sqrt(all.SquareExtent());

    std::vector<TopoShape> prisms;
    int index = 0;
    for (const TopoShape& region : profile.getSubTopoShapes(TopAbs_FACE)) {
        ++index;
        // The region's sweep ahead, through all
        TopoShape probe;
        probe.makeElementPrism(region, reach * gp_Vec(dir));
        Bnd_Box probeBox;
        BRepBndLib::Add(probe.getShape(), probeBox);
        std::vector<std::size_t> met;
        for (std::size_t i = 0; i < parts.size(); ++i) {
            Bnd_Box partBox;
            BRepBndLib::Add(parts[i].second.getShape(), partBox);
            if (probeBox.IsOut(partBox)) {
                continue;
            }
            BRepAlgoAPI_Common common(probe.getShape(), parts[i].second.getShape());
            if (!common.IsDone()) {
                continue;
            }
            GProp_GProps props;
            BRepGProp::VolumeProperties(common.Shape(), props);
            if (props.Mass() > Precision::Confusion()) {
                met.push_back(i);
            }
        }
        const std::string which = mode + ": region " + std::to_string(index) + " of the profile";
        if (met.empty()) {
            throw Base::ValueError(which + " meets no part ahead");
        }
        if (met.size() > 1) {
            throw Base::ValueError(
                which + " meets " + parts[met[0]].first + " and " + parts[met[1]].first
                + ": a region goes up to one part"
            );
        }
        prisms.push_back(side(region, parts[met.front()].second, reach, which));
    }
    if (prisms.empty()) {
        throw Base::ValueError(mode + ": the profile has no region");
    }
    if (prisms.size() == 1) {
        return prisms.front();
    }
    TopoShape tool = owner.makeTopoShape();
    tool.makeElementFuse(prisms, Part::OpCodes::Extrude);
    return tool;
}
}  // namespace

App::DocumentObjectExecReturn* FeatureExtrude::buildExtrusion(ExtrudeOptions options)
{
    if (!reapplyRun && onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    // const App::HistoryAlgorithm& selectedHistoryVersion = getSelectedHistoryAlgorithm();

    bool makeface = options.testFlag(ExtrudeOption::MakeFace);
    bool fuse = options.testFlag(ExtrudeOption::MakeFuse);
    bool inverseDirection = options.testFlag(ExtrudeOption::InverseDirection);

    std::string Sidemethod(SideType.getValueAsString());
    std::string method(Type.getValueAsString());
    std::string method2(Type2.getValueAsString());

    // Validate parameters
    double L = method == "ThroughAll" ? getThroughAllLength()
        : method == "Length"          ? Length.getValue()
                                      : 0.0;
    double L2 = Sidemethod == "Two sides" ? method2 == "ThroughAll" ? getThroughAllLength()
            : method2 == "Length"                                   ? Length2.getValue()
                                                                    : 0.0
                                          : 0.0;

    if ((Sidemethod == "One side" && method == "Length")
        || (Sidemethod == "Two sides" && method == "Length" && method2 == "Length")) {

        if (std::abs(L + L2) < Precision::Confusion()) {
            if (addSubType == Type::Additive) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Cannot create a pad with a total length of zero.")
                );
            }
            else {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Cannot create a pocket with a total length of zero.")
                );
            }
        }
    }

    Part::Feature* obj = nullptr;
    TopoShape sketchshape;
    try {
        obj = getVerifiedObject();
        if (makeface) {
            sketchshape = getTopoShapeVerifiedFace();
            // A solid extrude takes planar faces only: Onshape refuses a curved face at pick
            // (hands-on check B3-4, ops#640). A feature that holds one anyway (an older file, a
            // script) fails, and the part stays as it was (the failure's pass-through, ops#126)
            if (!obj->isDerivedFrom<Part::Part2DObject>()) {
                for (const auto& face : sketchshape.getSubTopoShapes(TopAbs_FACE)) {
                    if (!face.isPlanarFace()) {
                        return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                            "Exception",
                            "The face to extrude isn't planar: select a planar face or a sketch "
                            "region"
                        ));
                    }
                }
            }
        }
        else {
            std::vector<TopoShape> shapes;
            bool hasEdges = false;
            auto subs = Profile.getSubValues(false);
            if (subs.empty()) {
                subs.emplace_back("");
            }
            bool failed = false;
            for (auto& sub : subs) {
                if (sub.empty() && subs.size() > 1) {
                    continue;
                }
                TopoShape shape = Part::Feature::getTopoShape(
                    obj,
                    Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                        | Part::ShapeOption::Transform,
                    sub.c_str()
                );

                if (shape.isNull()) {
                    FC_ERR(
                        getFullName()
                        << ": failed to get profile shape " << obj->getFullName() << "." << sub
                    );
                    failed = true;
                }
                hasEdges = hasEdges || shape.hasSubShape(TopAbs_EDGE);
                shapes.push_back(shape);
            }
            if (failed) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Failed to obtain profile shape")
                );
            }
            if (hasEdges) {
                sketchshape.makeElementWires(shapes);
            }
            else {
                sketchshape.makeElementCompound(
                    shapes,
                    nullptr,
                    TopoShape::SingleShapeCompoundCreationPolicy::returnShape
                );
            }
        }
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (const Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }

    // if the Base property has a valid shape, fuse the prism into it
    TopoShape base = getBaseTopoShape(true);

    // get the normal vector of the sketch
    Base::Vector3d SketchVector = getProfileNormal();

    try {
        if (!reapplyRun) {
            this->positionByPrevious();
        }
        auto invObjLoc = getInverseLocation(base);

        auto invTrsf = invObjLoc.Transformation();

        base.move(invObjLoc);
        if (reapplyRun) {
            // A pattern's instance (ops#654 T3): its base, carried onto the seed, and the
            // direction the seed's own run computed (no property writes)
            base = reapplyRun->base;
        }

        Base::Vector3d paddingDirection = reapplyRun
            ? Direction.getValue()
            : computeDirection(SketchVector, inverseDirection);

        // create vector in padding direction with length 1
        gp_Dir dir(paddingDirection.x, paddingDirection.y, paddingDirection.z);

        // The length of a gp_Dir is 1 so the resulting pad would have
        // the length L in the direction of dir. But we want to have its height in the
        // direction of the normal vector.
        // Therefore we must multiply L by the factor that is necessary
        // to make dir as long that its projection to the SketchVector
        // equals the SketchVector.
        // This is the scalar product of both vectors.
        // Since the pad length cannot be negative, the factor must not be negative.

        double factor = fabs(dir * gp_Dir(SketchVector.x, SketchVector.y, SketchVector.z));

        // factor would be zero if vectors are orthogonal
        if (factor < Precision::Confusion()) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Creation failed because direction is orthogonal to sketch's normal vector"
            ));
        }

        // perform the length correction if not along custom vector
        if (AlongSketchNormal.getValue()) {
            L = L / factor;
            L2 = L2 / factor;
        }

        // explicitly set the Direction so that the dialog shows also the used direction
        // if the sketch's normal vector was used
        if (!reapplyRun) {
            Direction.setValue(paddingDirection);
        }

        dir.Transform(invTrsf);
        if (Reversed.getValue()) {
            dir.Reverse();
        }

        if (sketchshape.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Creating a face from sketch failed")
            );
        }
        sketchshape.move(invObjLoc);

        if (reapplyRun && (method == "ThroughAll" || method2 == "ThroughAll")) {
            // Through all at a pattern's instance (ops#654 T3): through the base there
            Bnd_Box box;
            if (!base.isNull()) {
                BRepBndLib::Add(base.getShape(), box);
            }
            BRepBndLib::Add(sketchshape.getShape(), box);
            box.SetGap(0.0);
            const double all = 2.02 * std::sqrt(box.SquareExtent()) / factor;
            if (method == "ThroughAll") {
                L = all;
            }
            if (Sidemethod == "Two sides" && method2 == "ThroughAll") {
                L2 = all;
            }
        }

        const char* startType = StartType.getValueAsString();
        const double startOffset = std::strcmp(startType, "Profile plane") == 0 ? 0.0
            : std::strcmp(startType, "Offset") == 0
            ? StartOffset.getValue()
            : getStartReferenceOffset(sketchshape, StartReference, dir, StartOffset.getValue(), invObjLoc);
        TopoShape startSketch = moveProfileToStart(sketchshape, dir, startOffset);

        std::vector<TopoShape> prisms;  // Stores prisms, all in global CS
        double taper1 = TaperAngle.getValue();
        double offset1 = Offset.getValue();

        // Side 2 made blind from its vertex: untapered, its offset in its length
        bool upToVertex2 = false;
        // Up to vertex (FreeCAD-CH ops#640 rank 22, Onshape's): the end lies on the plane
        // through the vertex, parallel to the profile plane, moved by the offset (Onshape's sign:
        // positive short of the vertex, as for a face; verified in Onshape, oracle 7c, UV1). A straight
        // extrusion of a planar profile ends on such a plane whatever its direction, so the side
        // is the blind one whose length reaches that plane, untapered as a side up to a face is.
        // One side goes towards the vertex; a side of two, or of a symmetric pair, that can't
        // reach it fails, as a side up to a face behind it does
        // One side up to a face in a plane parallel to the profile plane ends the same way
        // (FreeCAD-CH ops#751): where its profile holds an ellipse or a spline, it is built blind
        // to that plane, so its far edges are the profile's own curves, as Onshape's are
        // (upToPlaneForBlindSide()). Parallel is tested where the side is built: in the feature's
        // frame, and at a pattern's instance (Reapply) on the face carried onto the seed, which a
        // rotation may tilt. A face in the profile plane, or an offset that leaves nothing, stays
        // with the up-to prism and its messages
        std::optional<gp_Pnt> planeEnd;
        if (method == "UpToFace" && Sidemethod == "One side") {
            if (const auto plane = upToPlaneForBlindSide(UpToFace, sketchshape)) {
                gp_Dir faceNormal = plane->Direction();
                faceNormal.Transform(invTrsf);
                if (reapplyRun) {
                    faceNormal.Transform(reapplyRun->toSeed);
                }
                gp_Dir sketchNormal(SketchVector.x, SketchVector.y, SketchVector.z);
                sketchNormal.Transform(invTrsf);
                if (faceNormal.IsParallel(sketchNormal, Precision::Angular())) {
                    planeEnd = plane->Location();
                }
            }
        }
        if (method == "UpToVertex" || planeEnd
            || (Sidemethod == "Two sides" && method2 == "UpToVertex")) {
            gp_Dir profileNormal(SketchVector.x, SketchVector.y, SketchVector.z);
            profileNormal.Transform(invTrsf);
            const TopoShape profileVertex = startSketch.getSubTopoShape(TopAbs_VERTEX, 1);
            const gp_Pnt onProfile = BRep_Tool::Pnt(TopoDS::Vertex(profileVertex.getShape()));
            // The signed length along `along` from the profile to the plane through `target`
            // (global) parallel to the profile plane
            auto distanceTo = [&](gp_Pnt target, const gp_Dir& along) {
                target.Transform(invTrsf);
                if (reapplyRun) {
                    target.Transform(reapplyRun->toSeed);
                }
                const double cosine = gp_Vec(along).Dot(gp_Vec(profileNormal));
                return gp_Vec(onProfile, target).Dot(gp_Vec(profileNormal)) / cosine;
            };
            if (planeEnd) {
                const double length = distanceTo(*planeEnd, dir);
                if (std::fabs(length) < Precision::Confusion()
                    || std::fabs(length) - offset1 < Precision::Confusion()) {
                    planeEnd.reset();
                }
                else {
                    if (length < 0.0) {
                        dir.Reverse();
                    }
                    L = std::fabs(length) - offset1;
                    method = "Length";
                    taper1 = 0.0;
                    offset1 = 0.0;
                }
            }
            // The signed length along `along` from the profile to the vertex's plane
            auto lengthTo = [&](const App::PropertyLinkSub& link, const gp_Dir& along, double offset) {
                const double length = distanceTo(upToVertexPoint(link), along);
                if (std::fabs(length) < Precision::Confusion()) {
                    throw Base::ValueError(QT_TRANSLATE_NOOP(
                        "Exception",
                        "The vertex lies on the profile plane: there is nothing to extrude"
                    ));
                }
                // Onshape's sign, as for a face: a positive offset ends short of the vertex's plane,
                // towards the profile, a negative one past it. An offset that reaches or crosses
                // the profile leaves no extrusion towards the vertex
                const double reach = std::fabs(length) - offset;
                if (reach < Precision::Confusion()) {
                    throw Base::ValueError(QT_TRANSLATE_NOOP(
                        "Exception",
                        "The offset ends the extrusion at or before the profile plane: there is "
                        "nothing to extrude"
                    ));
                }
                return length < 0.0 ? -reach : reach;
            };
            auto behindSide = [](int side) {
                return new App::DocumentObjectExecReturn(
                    side == 1 ? QT_TRANSLATE_NOOP(
                                    "Exception",
                                    "Side 1 can't reach its vertex: the vertex lies behind side 1."
                                )
                              : QT_TRANSLATE_NOOP(
                                    "Exception",
                                    "Side 2 can't reach its vertex: the vertex lies behind side 2."
                                )
                );
            };
            if (method == "UpToVertex") {
                const double length = lengthTo(UpToFace, dir, offset1);
                if (Sidemethod == "One side") {
                    if (length < 0.0) {
                        dir.Reverse();
                    }
                    L = std::fabs(length);
                }
                else if (Sidemethod == "Symmetric") {
                    // each half reaches the vertex's plane (Length is the total)
                    L = 2.0 * std::fabs(length);
                }
                else if (length < 0.0) {
                    return behindSide(1);
                }
                else {
                    L = length;
                }
                method = "Length";
                taper1 = 0.0;
                offset1 = 0.0;
            }
            if (Sidemethod == "Two sides" && method2 == "UpToVertex") {
                const double length = lengthTo(UpToFace2, dir.Reversed(), Offset2.getValue());
                if (length < 0.0) {
                    return behindSide(2);
                }
                L2 = length;
                method2 = "Length";
                upToVertex2 = true;
            }
        }

        // A second side is built from the same sketch edges as the first, so the two sides'
        // names would differ only by the duplicate counter, which follows the order of the XOR
        // below (ops#255). In V2 the second side's prism is marked as a copy, as a Revolution's
        // second side is (ops#240): the prism, not its profile, since a tapered side's caps are
        // named by the draft, not from the profile's names.
        auto markSecondSide = [&](TopoShape shape) {
            if (getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2) {
                shape.appendElementSection(getID(), Part::OpCodes::Copy, "2");
            }
            return shape;
        };
        // Side 1's start cap, when the sides are built apart, is the seam at the profile plane,
        // and has the profile's names, as the start cap of one side or of two sides built as one
        // prism has. In V2 it is marked (CPY;1), so that a reference to that cap doesn't move to
        // the seam, or the other way, when an edit switches between the builds (PR 243 round 5).
        auto markSeam = [&](TopoShape shape) {
            const bool untapered = std::fabs(taper1) < Precision::Angular();
            markStartCap(shape, startSketch, "1", false, untapered);
            return shape;
        };

        if (Sidemethod == "One side") {
            TopoShape prism1 = generateSingleExtrusionSide(
                startSketch,
                method,
                L,
                taper1,
                UpToFace,
                UpToShape,
                dir,
                offset1,
                makeface,
                base,
                invObjLoc
            );
            prisms.push_back(prism1);
        }
        else if (Sidemethod == "Symmetric") {
            // For Length mode, we are not doing a mirror, but we extrude along the same axis
            // in both directions as it is what users expect.
            if (method == "Length") {
                if (std::fabs(taper1) > Precision::Angular()) {
                    // TAPERED case: We must create two separate prisms and fuse them
                    // to ensure the taper originates correctly from the sketch plane in both
                    // directions.
                    L /= 2.0;
                    TopoShape prism1 = markSeam(generateSingleExtrusionSide(
                        startSketch.makeElementCopy(),
                        method,
                        L,
                        taper1,
                        UpToFace,
                        UpToShape,
                        dir,
                        offset1,
                        makeface,
                        base,
                        invObjLoc
                    ));
                    if (!prism1.isNull() && !prism1.getShape().IsNull()) {
                        prisms.push_back(prism1);
                    }

                    gp_Dir dir2 = dir;
                    dir2.Reverse();
                    TopoShape prism2 = markSecondSide(generateSingleExtrusionSide(
                        startSketch.makeElementCopy(),
                        method,
                        L,
                        taper1,
                        UpToFace,
                        UpToShape,
                        dir2,
                        offset1,
                        makeface,
                        base,
                        invObjLoc
                    ));
                    if (!prism2.isNull() && !prism2.getShape().IsNull()) {
                        prisms.push_back(prism2);
                    }
                }
                else {
                    // NON-TAPERED case: We can optimize by creating a single prism.
                    // Translate the sketch to the start position (-L/2) and extrude by the full
                    // length L.
                    gp_Trsf start_transform;
                    start_transform.SetTranslation(gp_Vec(dir).Reversed() * (L / 2.0));

                    TopoShape moved_sketch = startSketch.makeElementCopy();
                    moved_sketch.move(start_transform);

                    TopoShape prism1 = generateSingleExtrusionSide(
                        moved_sketch,
                        method,
                        L,
                        taper1,
                        UpToFace,
                        UpToShape,
                        dir,
                        offset1,
                        makeface,
                        base,
                        invObjLoc
                    );
                    if (!prism1.isNull() && !prism1.getShape().IsNull()) {
                        prisms.push_back(prism1);
                    }
                }
            }
            else {
                // For "UpToFace", "UpToShape", etc., mirror the result.
                TopoShape prism1 = generateSingleExtrusionSide(
                    startSketch,
                    method,
                    L,
                    taper1,
                    UpToFace,
                    UpToShape,
                    dir,
                    offset1,
                    makeface,
                    base,
                    invObjLoc
                );

                // Prism 2: Mirror prism1 across the sketch plane.
                // The mirror plane's normal must be the sketch normal, not the extrusion direction.
                gp_Dir sketchNormalDir(SketchVector.x, SketchVector.y, SketchVector.z);
                sketchNormalDir.Transform(invTrsf);  // Transform to global CS, like 'dir' was.

                Base::Vector3d sketchCenter = startSketch.getBoundBox().GetCenter();
                gp_Ax2 mirrorPlane(
                    gp_Pnt(sketchCenter.x, sketchCenter.y, sketchCenter.z),
                    sketchNormalDir
                );
                TopoShape prism2 = markSecondSide(prism1.makeElementMirror(mirrorPlane));
                // Side 1's seam marked after the mirror: side 2's names stay side 1's with CPY;2
                prisms.push_back(markSeam(prism1));
                prisms.push_back(prism2);
            }
        }
        else if (Sidemethod == "Two sides") {
            double taper2 = upToVertex2 ? 0.0 : TaperAngle2.getValue();
            double offset2 = upToVertex2 ? 0.0 : Offset2.getValue();
            gp_Dir dir2 = dir;
            dir2.Reverse();
            bool noTaper = std::fabs(taper1) < Precision::Angular()
                && std::fabs(taper2) < Precision::Angular();
            bool method1LengthBased = method == "Length" || method == "ThroughAll";
            bool method2LengthBased = method2 == "Length" || method2 == "ThroughAll";
            bool hasStartOffset = std::fabs(startOffset) > Precision::Confusion();
            gp_Dir sketchNormal(SketchVector.x, SketchVector.y, SketchVector.z);
            sketchNormal.Transform(invTrsf);
            // An up-to side that had to go the other way overlaps the other side (ops#73).
            auto reversed = [&](const TopoShape& prism, const TopoShape& profile, const gp_Dir& d) {
                return !sideGoesAlong(prism, profile, sketchNormal, d);
            };
            const char* side1Reversed = QT_TRANSLATE_NOOP(
                "Exception",
                "Side 1 can't reach its face: the face lies behind side 1."
            );
            const char* side2Reversed = QT_TRANSLATE_NOOP(
                "Exception",
                "Side 2 can't reach its face: the face lies behind side 2."
            );

            // Untapered from the profile plane, the two sides are one prism, from one side's end
            // to the other's. In V2 it starts from side 2's end whenever side 2 has a length, so
            // that its start cap has the profile's names, as one side's has, and its far cap is
            // side 1's end, named as side 1's far cap is when the sides are built apart (side 2's
            // has the copy section). Built apart, side 1's start cap, the seam, is marked (PR 243
            // rounds 4 and 5).
            const bool fromSide1End = !hasStartOffset && method1LengthBased
                && method2 != "UpToFirst" && noTaper;
            const bool fromSide2End = !hasStartOffset && method2LengthBased && method != "UpToFirst"
                && noTaper;
            const bool v2 = getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2;
            if (fromSide1End && !(v2 && fromSide2End)) {
                gp_Trsf start_transform;
                start_transform.SetTranslation(gp_Vec(dir) * L);

                TopoShape moved_sketch = sketchshape.makeElementCopy();
                moved_sketch.move(start_transform);
                TopoShape prism = generateSingleExtrusionSide(
                    moved_sketch,
                    method2,
                    L + L2,
                    0.0,
                    UpToFace2,
                    UpToShape2,
                    dir2,
                    offset2,
                    makeface,
                    base,
                    invObjLoc
                );
                if (!method2LengthBased
                    && !sideReachesPlane(prism, sketchshape, sketchNormal, dir2)) {
                    return new App::DocumentObjectExecReturn(side2Reversed);
                }
                if (!prism.isNull() && !prism.getShape().IsNull()) {
                    // From side 1's end (in V2, side 2 up to a face): the start cap is side
                    // 1's end, and the far cap is side 2's
                    markStartCap(prism, sketchshape, "0", true);
                    prisms.push_back(prism);
                }
            }
            else if (fromSide2End) {
                gp_Trsf start_transform;
                start_transform.SetTranslation(gp_Vec(dir).Reversed() * L2);

                TopoShape moved_sketch = sketchshape.makeElementCopy();
                moved_sketch.move(start_transform);
                TopoShape prism = generateSingleExtrusionSide(
                    moved_sketch,
                    method,
                    L + L2,
                    0.0,
                    UpToFace,
                    UpToShape,
                    dir,
                    offset1,
                    makeface,
                    base,
                    invObjLoc
                );
                if (!method1LengthBased
                    && !sideReachesPlane(prism, sketchshape, sketchNormal, dir)) {
                    return new App::DocumentObjectExecReturn(side1Reversed);
                }
                if (!prism.isNull() && !prism.getShape().IsNull()) {
                    prisms.push_back(prism);
                }
            }
            else {
                TopoShape prism1 = markSeam(generateSingleExtrusionSide(
                    startSketch.makeElementCopy(),
                    method,
                    L,
                    taper1,
                    UpToFace,
                    UpToShape,
                    dir,
                    offset1,
                    makeface,
                    base,
                    invObjLoc
                ));
                if (!method1LengthBased && reversed(prism1, startSketch, dir)) {
                    return new App::DocumentObjectExecReturn(side1Reversed);
                }
                if (!prism1.isNull() && !prism1.getShape().IsNull()) {
                    prisms.push_back(prism1);
                }

                // Side 2
                TopoShape prism2 = markSecondSide(generateSingleExtrusionSide(
                    startSketch.makeElementCopy(),
                    method2,
                    L2,
                    taper2,
                    UpToFace2,
                    UpToShape2,
                    dir2,
                    offset2,
                    makeface,
                    base,
                    invObjLoc
                ));
                if (!method2LengthBased && reversed(prism2, startSketch, dir2)) {
                    return new App::DocumentObjectExecReturn(side2Reversed);
                }
                if (!prism2.isNull() && !prism2.getShape().IsNull()) {
                    prisms.push_back(prism2);
                }
            }
        }

        // --- Combine generated prisms (all in global CS) ---
        TopoShape prism = makeTopoShape();
        if (prisms.empty()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "No extrusion geometry was generated.")
            );
        }
        else if (prisms.size() == 1) {
            prism = prisms[0];
        }
        else {
            try {
                prism.makeElementXor(prisms, Part::OpCodes::Extrude);
            }
            catch (const Standard_Failure& e) {
                return new App::DocumentObjectExecReturn(
                    std::string("Failed to xor extrusion sides (OCC): ") + e.GetMessageString()
                );
            }
            catch (const Base::Exception& e) {
                return new App::DocumentObjectExecReturn(
                    std::string("Failed to xor extrusion sides: ") + e.what()
                );
            }
        }

        if (prism.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting fused extrusion is null.")
            );
        }

        if (reapplyRun) {
            // A pattern's instance (ops#654 T3): its tool only, refined as the seed's
            reapplyRun->tool = refineShapeIfActive(prism);
            return App::DocumentObject::StdReturn;
        }

        // store shape before refinement
        this->rawShape = prism;
        prism = refineShapeIfActive(prism);
        // set the additive shape property for later usage in e.g. pattern
        this->AddSubShape.setValue(prism);

        // FreeCAD-CH ops#654 S2: a studio owner computes only its tool, which its steps apply;
        // its own shape stays empty, so nothing (a Body, the BOM, an assembly) sees it as a part
        if (runsAsStudioOwner(this)) {
            madeUnder = Placement.getValue();
            this->rawShape = TopoShape();
            this->Shape.setValue(TopoShape());
            updateProperties();
            return App::DocumentObject::StdReturn;
        }

        // Remove or Intersect (FreeCAD-CH ops#640 H3): one that misses its base changes no
        // geometry and stays healthy, with Onshape's info "Selected tools and targets do not
        // intersect" (below). With no solid before it, it makes nothing, never its tool as
        // material (the last branch below), and FeatureAddSub::recompute fails it: "Nothing to
        // cut" (ops#308 F8), its empty base passed through. A base of no solid that isn't empty
        // (a BaseFeature's face) goes on as before
        const bool cuts = fuse && booleanOperation != BooleanOperation::Union;
        if (cuts && base.isNull()) {
            madeUnder = Placement.getValue();
            // no raw result: a Refine-only change recomputes fully (FeatureRefine::onlyHaveRefined)
            this->rawShape = TopoShape();
            this->Shape.setValue(TopoShape());
            updateProperties();
            return App::DocumentObject::StdReturn;
        }

        if (base.shapeType(true) <= TopAbs_SOLID && fuse) {
            prism.Tag = -this->getID();

            const bool apart = cuts && boxesApart(prism, base);
            if (apart && booleanOperation == BooleanOperation::Common) {
                // they share nothing: the base as it was, not an empty common (ops#640 H3). No
                // raw result is kept: onlyHaveRefined would otherwise refine the prism into Shape
                // on a Refine-only change (a positive solid), and a full recompute keeps the note
                noteReachesNothing();
                madeUnder = Placement.getValue();
                this->rawShape = TopoShape();
                this->Shape.setValue(base);
                updateProperties();
                return App::DocumentObject::StdReturn;
            }

            // Let's call algorithm computing a fuse operation:
            TopoShape result = makeTopoShape();
            try {
                result.makeElementBoolean(
                    getBooleanMaker(),
                    {base, prism},
                    nullptr,
                    FuzzyTolerance.getValue(),
                    Part::ElementMapPolicy::Propagate,
                    booleanInputCheck(),
                    &booleanInputsValid
                );
            }
            catch (Standard_Failure&) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Fusion with base feature failed")
                );
            }
            if (cuts && booleanOperation == BooleanOperation::Common
                && (result.isNull() || !result.hasSubShape(TopAbs_SOLID))) {
                // boxes that overlap with solids that don't: the base as it was (ops#640 H3), no
                // raw result kept (as above)
                noteReachesNothing();
                madeUnder = Placement.getValue();
                this->rawShape = TopoShape();
                this->Shape.setValue(base);
                updateProperties();
                return App::DocumentObject::StdReturn;
            }
            const bool cutMisses = cuts && booleanOperation == BooleanOperation::Subtraction
                && (apart || cutMissed(prism, base, result));
            if (cutMisses) {
                // a cut that misses computes its base unchanged: kept as computed, with the note
                noteReachesNothing();
            }
            // we have to get the solids (fuse sometimes creates compounds)
            auto solRes = this->getSolid(result);
            // lets check if the result is a solid
            if (solRes.isNull()) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Resulting shape is not a solid")
                );
            }

            // store shape before refinement; none for a cut that missed, so that a Refine-only
            // change recomputes fully and keeps the note (DocumentObject::recompute clears it)
            this->rawShape = cutMisses ? TopoShape() : result;
            solRes = refineShapeIfActive(result);

            if (!isSingleSolidRuleSatisfied(solRes.getShape())) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Result has multiple solids: enable 'Allow Compound' in the active body."
                ));
            }
            madeUnder = Placement.getValue();
            this->Shape.setValue(getSolid(solRes));
        }
        else if (prism.hasSubShape(TopAbs_SOLID)) {
            if (prism.countSubShapes(TopAbs_SOLID) > 1) {
                prism.makeElementFuse(prism.getSubTopoShapes(TopAbs_SOLID));
            }

            // store shape before refinement
            this->rawShape = prism;
            prism = refineShapeIfActive(prism);
            if (!isSingleSolidRuleSatisfied(prism.getShape())) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Result has multiple solids: enable 'Allow Compound' in the active body."
                ));
            }
            prism = getSolid(prism);
            madeUnder = Placement.getValue();
            this->Shape.setValue(prism);
        }
        else {
            // store shape before refinement
            this->rawShape = prism;
            prism = refineShapeIfActive(prism);
            if (!isSingleSolidRuleSatisfied(prism.getShape())) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Result has multiple solids: enable 'Allow Compound' in the active body."
                ));
            }
            madeUnder = Placement.getValue();
            this->Shape.setValue(prism);
        }

        // eventually disable some settings that are not valid for the current method
        updateProperties();

        return App::DocumentObject::StdReturn;
    }
    catch (Standard_Failure& e) {
        if (std::string(e.GetMessageString()) == "TopoDS::Face") {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Could not create face from sketch.\n"
                "Intersecting sketch entities or multiple faces in a sketch are not allowed."
            ));
        }
        else {
            return new App::DocumentObjectExecReturn(e.GetMessageString());
        }
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
}

TopoShape FeatureExtrude::generateSingleExtrusionSide(
    const TopoShape& sketchshape,
    const std::string& method,
    double length,
    double taperAngleDeg,
    App::PropertyLinkSub& upToFacePropHandle,
    App::PropertyLinkSubList& upToShapePropHandle,
    gp_Dir dir,
    double offsetVal,
    bool makeFace,
    const TopoShape& base,
    TopLoc_Location& invObjLoc
)
{
    TopoShape prism = makeTopoShape();

    if ((method == "UpToFirst" || method == "UpToLast") && !ownerRegionRunning
        && runsAsStudioOwner(this)) {
        Base::StateLocker perRegion(ownerRegionRunning);
        return ownerUpToPerRegion(*this, sketchshape, method, dir, invObjLoc, [&](
            const TopoShape& region, const TopoShape& part, double reach, const std::string& which) {
            auto asToday = [&](double taper, double offset) {
                return generateSingleExtrusionSide(
                    region,
                    method,
                    length,
                    taper,
                    upToFacePropHandle,
                    upToShapePropHandle,
                    dir,
                    offset,
                    makeFace,
                    part,
                    invObjLoc
                );
            };
            if (method != "UpToFirst") {
                return asToday(taperAngleDeg, offsetVal);
            }
            // Onshape's up to next (O8h): every point of the region stops at the part's next face
            TopoShape tool = ownerUpToNext(*this, region, part, dir, reach, which);
            if (std::abs(taperAngleDeg) < Precision::Angular()
                && std::abs(offsetVal) < Precision::Confusion()) {
                return tool;
            }
            // A taper or an offset is today's single face: right only when the next faces are
            // one, which the plain flat tool's volume tells
            if (std::abs(volumeOf(asToday(0.0, 0.0)) - volumeOf(tool))
                > std::max(1e-6, volumeOf(tool) * 1e-7)) {
                throw Base::ValueError(
                    which + ": a taper or an offset over next faces at different depths is not "
                            "supported yet"
                );
            }
            return asToday(taperAngleDeg, offsetVal);
        });
    }

    if (method == "UpToFirst" || method == "UpToLast" || method == "UpToFace"
        || method == "UpToShape") {
        // Note: This will return an unlimited planar face if support is a datum plane
        TopoShape supportface = getTopoShapeSupportFace();
        supportface.move(invObjLoc);

        if (!supportface.hasSubShape(TopAbs_WIRE)) {
            supportface = makeTopoShape();
        }

        TopoShape upToShape = makeTopoShape();
        int faceCount = 1;
        // Find a valid shape, face or datum plane to extrude up to
        if (method == "UpToFace") {
            getUpToFaceFromLinkSub(upToShape, upToFacePropHandle);
            upToShape.move(invObjLoc);
            if (reapplyRun) {
                upToShape = upToShape.makeElementTransform(reapplyRun->toSeed);
            }
        }
        else if (method == "UpToShape") {
            faceCount = getUpToShapeFromLinkSubList(upToShape, upToShapePropHandle);
            upToShape.move(invObjLoc);
            if (reapplyRun) {
                upToShape = upToShape.makeElementTransform(reapplyRun->toSeed);
            }
            if (faceCount == 0) {
                // No shape selected, use the base
                upToShape = base;
            }
        }

        if (faceCount == 1) {
            getUpToFace(upToShape, base, sketchshape, method, dir);
            // Onshape's sign (FreeCAD-CH P3, the Onshape fact U1; coordinator c720): a positive
            // offset ends short of the face, back towards the profile, a negative one past it
            // (Onshape's "opposite direction"). Up to a face, a shape's face, first and last.
            addOffsetToFace(upToShape, dir, -offsetVal);
        }
        else {
            if (fabs(offsetVal) > Precision::Confusion()) {
                throw Base::RuntimeError("Extrude: Can only offset one face");
            }
            // open the shell by removing the furthest face
            upToShape = makeShellFromUpToShape(upToShape, sketchshape, dir);
        }

        try {
            TopoShape _base = makeTopoShape();
            // An owner's base is its in-scope parts (ops#654 S2): its tool is the prism alone
            if (addSubType != FeatureAddSub::Type::Subtractive && !runsAsStudioOwner(this)) {
                _base = base;  // avoid issue #16690
            }
            prism.makeElementPrismUntil(
                _base,
                sketchshape,
                supportface,
                upToShape,
                dir,
                TopoShape::PrismMode::None,
                true /*CheckUpToFaceLimits.getValue()*/
            );
        }
        catch (Base::RuntimeError&) {
            // The prism up to a freeform face refuses with what is wrong: the profile passes the
            // shape, or meets it first in a jump (ops#353)
            throw;
        }
        catch (Base::Exception&) {
            if (method == "UpToShape" && faceCount > 1) {
                throw Base::RuntimeError(
                    "Extrude: Unable to reach the selected shape, please select faces"
                );
            }
            // Not an empty prism: one side gave a null result, and a side of two was left out
            // with no error (ops#353)
            throw;
        }
    }
    else if (method == "Length" || method == "ThroughAll") {
        using std::numbers::pi;

        Part::ExtrusionParameters params;
        params.taperAngleFwd = Base::toRadians(taperAngleDeg);
        params.innerWireTaper = Part::InnerWireTaper::SameAsOuter;

        if (std::fabs(params.taperAngleFwd) >= Precision::Angular()
            || std::fabs(params.taperAngleRev) >= Precision::Angular()) {
            if (fabs(params.taperAngleFwd) > pi * 0.5 - Precision::Angular()
                || fabs(params.taperAngleRev) > pi * 0.5 - Precision::Angular()) {
                return prism;
            }
            params.dir = dir;
            params.solid = makeFace;
            params.lengthFwd = length;

            std::vector<TopoShape> drafts;
            Part::ExtrusionHelper::makeElementDraft(
                params,
                sketchshape,
                drafts,
                getDocument()->getStringHasher()
            );
            if (drafts.empty()) {
                return prism;
            }
            prism.makeElementCompound(
                drafts,
                nullptr,
                TopoShape::SingleShapeCompoundCreationPolicy::returnShape
            );
        }
        else {
            // Without taper angle we create a prism because its shells are in every case no
            // B-splines and can therefore be use as support for further features like Pads,
            // Lofts etc. B-spline shells can break certain features, see e.g.
            // https://forum.freecad.org/viewtopic.php?p=560785#p560785 It is better not to use
            // BRepFeat_MakePrism here even if we have a support because the resulting shape
            // creates problems with Pocket
            try {
                prism.makeElementPrism(sketchshape, length * gp_Vec(dir));
            }
            catch (Standard_Failure&) {
                throw Base::RuntimeError("FeatureExtrusion: Length: Could not extrude the sketch!");
            }
        }
    }

    return prism;
}

void FeatureExtrude::onDocumentRestored()
{
    Base::StateLocker migrating(migratingDeprecatedProperties);

    // property Type no longer has TwoLengths.
    if (strcmp(Type.getValueAsString(), "?TwoLengths") == 0) {
        Type.setValue("Length");
        Type2.setValue("Length");
        SideType.setValue("Two sides");

        // The old TwoLengths code path (generatePrism) always extruded in +dir:
        //   offset = -L2 * dir  (Reversed=false) or -L * dir (Reversed=true)
        //   extrude = (L+L2) * dir
        // The new "Two sides" code extrudes Side 1 in dir, Side 2 in -dir,
        // with Reversed toggling the sign of dir. To preserve the same OCC
        // topology (face/edge ordering) in V1, we toggle Reversed so the effective
        // extrusion direction matches the old +dir, and swap Length/Length2
        // to keep the correct offset for each side. (V2 builds the prism from
        // side 2's end, the other way, and names its elements by their history,
        // not their order: PR 243 round 4.)
        Reversed.setValue(!Reversed.getValue());
        double origL = Length.getValue();
        double origL2 = Length2.getValue();
        Length.setValue(origL2);
        Length2.setValue(origL);

        App::ObjectIdentifier lengthPath(Length);
        App::ObjectIdentifier length2Path(Length2);

        // Rename Length <-> Length2 in all expressions before swapping which expression lives on
        // which property. This avoids cyclic dependencies and fixes cross-object references.
        std::map<App::ObjectIdentifier, App::ObjectIdentifier> renames;
        renames[lengthPath] = length2Path;
        renames[length2Path] = lengthPath;
        getDocument()->renameObjectIdentifiers(renames);

        auto exprL = getExpression(lengthPath);
        auto exprL2 = getExpression(length2Path);
        if (exprL.expression || exprL2.expression) {
            clearExpression(lengthPath);
            clearExpression(length2Path);
            if (exprL.expression) {
                setExpression(length2Path, exprL.expression);
            }
            if (exprL2.expression) {
                setExpression(lengthPath, exprL2.expression);
            }
        }
    }
    else if (Midplane.getValue()) {
        Midplane.setValue(false);
        SideType.setValue("Symmetric");
    }

    ProfileBased::onDocumentRestored();
    // The restored shape was saved with its placement (ops#522)
    madeUnder = Placement.getValue();
}

bool FeatureExtrude::shapeMadeUnderPlacement() const
{
    return madeUnder && madeUnder->isSame(Placement.getValue(), Precision::Confusion());
}

namespace PartDesign
{

/** FreeCAD-CH ops#654 T3: feature's tool re-solved at a pattern's instance (ReapplyRun above), in
 * the feature's own frame; null with why when it can't be made there. Declared where used
 * (FeatureTransformed.cpp) */
PartDesignExport TopoShape reapplyExtrusion(
    FeatureExtrude* feature,
    const gp_Trsf& toSeed,
    const TopoShape& base,
    const std::string& partLabel,
    std::string& why
)
{
    ReapplyRun run {toSeed, base, partLabel, TopoShape()};
    ReapplyRun* outer = reapplyRun;
    reapplyRun = &run;
    App::DocumentObjectExecReturn* ret = nullptr;
    try {
        if (auto pad = freecad_cast<Pad*>(feature)) {
            ret = pad->execute();
        }
        else if (auto pocket = freecad_cast<Pocket*>(feature)) {
            ret = pocket->execute();
        }
        else {
            why = "it isn't a Pad or a Pocket";
        }
    }
    catch (const Base::Exception& e) {
        why = e.what();
    }
    catch (const Standard_Failure& e) {
        why = e.GetMessageString();
    }
    reapplyRun = outer;
    if (ret) {
        why = ret->Why;
        delete ret;
        return {};
    }
    if (run.tool.isNull() && why.empty()) {
        why = "it made no tool there";
    }
    return why.empty() ? run.tool : TopoShape();
}

}  // namespace PartDesign
