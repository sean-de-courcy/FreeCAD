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
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <BRep_Builder.hxx>
#include <BRepAdaptor_Surface.hxx>
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

#include "FeatureExtrude.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesign;

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
    if (Part::findAllFacesCutBy(face, profile, dir).empty()) {
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

// The direction a Pad or Pocket swept its profile along, for the reference solver (PR 366 round
// 6): Direction holds the one computeDirection() last used, in the body's frame. Turned into the
// feature's own frame, without its placement, where its elements' fingerprints are measured.
bool sweepDirection(const App::GeoFeature* geo, Base::Vector3d& direction)
{
    const auto extrude = dynamic_cast<const FeatureExtrude*>(geo);
    if (!extrude) {
        return false;
    }
    direction = extrude->Placement.getValue().getRotation().inverse().multVec(
        extrude->Direction.getValue()
    );
    return direction.Length() > Precision::Confusion();
}

const bool sweepDirectionRegistered = (App::setElementSweepDirectionFunction(&sweepDirection), true);

// The up-to faces under a far piece's point, for the reference solver (ops#522, PLAN decision
// 168; App::ElementUpToFacesFunction): the faces of a one-sided Pad's or Pocket's UpToFace or
// UpToShape, as generateSingleExtrusionSide() takes them, that the line through the point along
// the sweep meets, inside them or on their boundary. The point comes in the feature's own frame
// and goes to the frame the up-to shapes are taken in (with their placements) by the feature's
// current placement, so it moves with a profile moved by placement; then into each face owner's
// own frame, where the face's box, area, normal and outer wire are measured, so a plate moved by
// its owner's placement is the same plate. With `all`, every up-to face too (its normal: none). A datum plane or another unbounded face, UpToFirst and UpToLast
// (the base's faces), an empty shape list (the base), two sides, and a face whose normal can't
// be taken at the point can't be told.
bool upToFaces(
    const App::GeoFeature* geo,
    const Base::Vector3d& point,
    std::vector<Data::ElementFingerprint::UpToFace>& faces,
    std::vector<Data::ElementFingerprint::UpToFace>* all
)
{
    faces.clear();
    if (all) {
        all->clear();
    }
    const auto extrude = dynamic_cast<const FeatureExtrude*>(geo);
    if (!extrude || std::strcmp(extrude->SideType.getValueAsString(), "One side") != 0) {
        return false;
    }
    // Each up-to object with the face it names, or none for all of its faces
    std::vector<std::pair<const App::DocumentObject*, std::string>> refs;
    const std::string method = extrude->Type.getValueAsString();
    if (method == "UpToFace") {
        const auto& subs = extrude->UpToFace.getSubValues();
        if (subs.size() > 1) {
            return false;
        }
        refs.emplace_back(extrude->UpToFace.getValue(), subs.empty() ? std::string() : subs[0]);
    }
    else if (method == "UpToShape") {
        for (const auto& [ref, subs] : extrude->UpToShape.getSubListValues()) {
            if (subs.empty() || (subs.size() == 1 && subs[0].empty())) {
                refs.emplace_back(ref, std::string());
            }
            for (const auto& sub : subs) {
                if (!sub.empty()) {
                    refs.emplace_back(ref, sub);
                }
            }
        }
    }
    const Base::Vector3d along = extrude->Direction.getValue();
    if (refs.empty() || along.Length() <= Precision::Confusion()) {
        return false;
    }
    const Base::Placement placement = extrude->Placement.getValue();
    Base::Vector3d at;
    placement.multVec(point, at);
    try {
        for (const auto& [ref, sub] : refs) {
            if (!ref || !ref->getNameInDocument() || ref->isDerivedFrom<App::Plane>()
                || ref->isDerivedFrom<Part::Datum>()) {
                return false;
            }
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
            inverse.getRotation().multVec(along, direction);
            const gp_Lin line(
                gp_Pnt(origin.x, origin.y, origin.z),
                gp_Dir(direction.x, direction.y, direction.z)
            );
            for (const auto& face : shape.getSubTopoShapes(TopAbs_FACE)) {
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
                BRepIntCurveSurface_Inter hits;
                hits.Init(topoFace, line, Precision::Confusion());
                std::optional<std::pair<double, double>> uv;
                double nearest = 0.0;
                for (; hits.More(); hits.Next()) {
                    if ((hits.State() == TopAbs_IN || hits.State() == TopAbs_ON)
                        && (!uv || std::abs(hits.W()) < nearest)) {
                        uv = std::make_pair(hits.U(), hits.V());
                        nearest = std::abs(hits.W());
                    }
                }
                if (!uv) {
                    continue;
                }
                BRepAdaptor_Surface surface(topoFace);
                gp_Pnt on;
                gp_Vec du;
                gp_Vec dv;
                surface.D1(uv->first, uv->second, on, du, dv);
                const gp_Vec normal = du.Crossed(dv);
                if (normal.Magnitude() <= gp::Resolution()) {
                    return false;
                }
                upTo.normal = Base::Vector3d(normal.X(), normal.Y(), normal.Z()).Normalize();
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
                    direction = addSubType == Type::Additive ? axis : -axis;
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
    (void)inverse;
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
            switch (addSubType) {
                case Type::Additive:
                    extrudeDirection = dir;
                    break;
                case Type::Subtractive:
                    extrudeDirection = -dir;
                    break;
            }
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
        else if (method == "UpToFace") {
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

App::DocumentObjectExecReturn* FeatureExtrude::buildExtrusion(ExtrudeOptions options)
{
    if (onlyHaveRefined()) {
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
        this->positionByPrevious();
        auto invObjLoc = getInverseLocation(base);

        auto invTrsf = invObjLoc.Transformation();

        base.move(invObjLoc);

        Base::Vector3d paddingDirection = computeDirection(SketchVector, inverseDirection);

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
        Direction.setValue(paddingDirection);

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

        const char* startType = StartType.getValueAsString();
        const double startOffset = std::strcmp(startType, "Profile plane") == 0 ? 0.0
            : std::strcmp(startType, "Offset") == 0
            ? StartOffset.getValue()
            : getStartReferenceOffset(sketchshape, StartReference, dir, StartOffset.getValue(), invObjLoc);
        TopoShape startSketch = moveProfileToStart(sketchshape, dir, startOffset);

        std::vector<TopoShape> prisms;  // Stores prisms, all in global CS
        double taper1 = TaperAngle.getValue();
        double offset1 = Offset.getValue();

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
            double taper2 = TaperAngle2.getValue();
            double offset2 = Offset2.getValue();
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

        // store shape before refinement
        this->rawShape = prism;
        prism = refineShapeIfActive(prism);
        // set the additive shape property for later usage in e.g. pattern
        this->AddSubShape.setValue(prism);

        if (base.shapeType(true) <= TopAbs_SOLID && fuse) {
            prism.Tag = -this->getID();

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
            // we have to get the solids (fuse sometimes creates compounds)
            auto solRes = this->getSolid(result);
            // lets check if the result is a solid
            if (solRes.isNull()) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Resulting shape is not a solid")
                );
            }

            // store shape before refinement
            this->rawShape = result;
            solRes = refineShapeIfActive(result);

            if (!isSingleSolidRuleSatisfied(solRes.getShape())) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Result has multiple solids: enable 'Allow Compound' in the active body."
                ));
            }
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
        }
        else if (method == "UpToShape") {
            faceCount = getUpToShapeFromLinkSubList(upToShape, upToShapePropHandle);
            upToShape.move(invObjLoc);
            if (faceCount == 0) {
                // No shape selected, use the base
                upToShape = base;
            }
        }

        if (faceCount == 1) {
            getUpToFace(upToShape, base, sketchshape, method, dir);
            addOffsetToFace(upToShape, dir, offsetVal);
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
            if (addSubType != FeatureAddSub::Type::Subtractive) {
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
}
