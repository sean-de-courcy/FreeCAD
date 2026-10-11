// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2010 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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
#include <cmath>
#include <cstring>
#include <numbers>
#include <optional>
#include <ranges>
#include <utility>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <Geom_ElementarySurface.hxx>
#include <gp.hxx>
#include <gp_Ax2.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <Precision.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>

#include <App/Document.h>
#include <Base/Console.h>
#include <Base/Converter.h>
#include <Base/Exception.h>
#include <Base/Tools.h>
#include <Base/Translation.h>
#include <Mod/Part/App/Tools.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "FeatureRevolved.h"

using namespace PartDesign;

namespace PartDesign
{

/* TRANSLATOR PartDesign::Revolved */

PROPERTY_SOURCE_ABSTRACT(PartDesign::Revolved, PartDesign::ProfileBased)  // NOLINT

const App::PropertyAngle::Constraints Revolved::floatAngle = {-360.0, 360.0, 1.0};
const char* Revolved::SideTypesEnums[] = {"One side", "Two sides", "Symmetric", nullptr};

namespace
{

bool usesBRepFeatRevolution(Revolved::RevolMethod method, Part::RevolMode revolMode)
{
    return method == Revolved::RevolMethod::ToFirst || method == Revolved::RevolMethod::ToFace
        || (method == Revolved::RevolMethod::ToLast && revolMode == Part::RevolMode::FuseWithBase);
}

bool isLegacyTwoAngles(const std::string& method)
{
    return method == "?TwoAngles" || method == "TwoAngles";
}

bool getProfileOrbit(const TopoShape& profileShape, const gp_Ax1& axis, gp_Pnt& center, gp_Vec& radial)
{
    Base::Vector3d profileCenter;
    if (!profileShape.getCenterOfGravity(profileCenter)) {
        return false;
    }

    const gp_Pnt profilePoint = Base::convertTo<gp_Pnt>(profileCenter);
    const gp_Vec axisVector(axis.Direction());
    const double parameter = gp_Vec(axis.Location(), profilePoint).Dot(axisVector);
    center = axis.Location();
    center.Translate(axisVector * parameter);
    radial = gp_Vec(center, profilePoint);
    return radial.Magnitude() > Precision::Confusion();
}

std::optional<double> getPlanarStartReferenceAngle(
    const TopoShape& profileShape,
    const TopoShape& referenceShape,
    const gp_Ax1& axis
)
{
    TopoShape referenceFace = referenceShape;
    if (referenceFace.shapeType(true) != TopAbs_FACE) {
        referenceFace = referenceFace.getSubTopoShape(TopAbs_FACE, 1);
    }

    BRepAdaptor_Surface surface(TopoDS::Face(referenceFace.getShape()));
    if (surface.GetType() != GeomAbs_Plane) {
        return std::nullopt;
    }

    gp_Pnt orbitCenter;
    gp_Vec radial;
    if (!getProfileOrbit(profileShape, axis, orbitCenter, radial)) {
        return std::nullopt;
    }

    const gp_Pln plane = surface.Plane();
    const gp_Vec normal(plane.Axis().Direction());
    const gp_Vec tangent = gp_Vec(axis.Direction()).Crossed(radial);
    const double cosineCoefficient = radial.Dot(normal);
    const double sineCoefficient = tangent.Dot(normal);
    const double constant = gp_Vec(plane.Location(), orbitCenter).Dot(normal);
    const double amplitude = std::hypot(cosineCoefficient, sineCoefficient);

    if (amplitude <= Precision::Confusion()) {
        if (std::fabs(constant) <= Precision::Confusion()) {
            return 0.0;
        }
        return std::nullopt;
    }

    const double solution = -constant / amplitude;
    if (solution < -1.0 - Precision::Confusion() || solution > 1.0 + Precision::Confusion()) {
        return std::nullopt;
    }

    const double phase = std::atan2(sineCoefficient, cosineCoefficient);
    const double delta = std::acos(std::clamp(solution, -1.0, 1.0));
    return std::min(normalizeAngleRadians(phase + delta), normalizeAngleRadians(phase - delta));
}

}  // namespace

Revolved::Revolved()
{
    ADD_PROPERTY_TYPE(StartType, (0L), "Start", App::Prop_None, "How to define the revolution start");
    StartType.setEnums(StartTypesEnums);
    ADD_PROPERTY_TYPE(
        StartOffset,
        (0.0),
        "Start",
        App::Prop_None,
        "Angular offset from the profile or selected start reference"
    );
    ADD_PROPERTY_TYPE(
        StartReference,
        (nullptr),
        "Start",
        App::Prop_None,
        "Face, plane or sketch used as the start reference"
    );
    Angle.setConstraints(&floatAngle);
    Angle2.setConstraints(&floatAngle);
    StartOffset.setConstraints(&floatAngle);
}

short Revolved::mustExecute() const
{
    if (Placement.isTouched() || SideType.isTouched() || Type.isTouched() || Type2.isTouched()
        || ReferenceAxis.isTouched() || Axis.isTouched() || Base.isTouched() || UpToFace.isTouched()
        || UpToFace2.isTouched() || Angle.isTouched() || Angle2.isTouched() || StartType.isTouched()
        || StartOffset.isTouched() || StartReference.isTouched()) {
        return 1;
    }
    return ProfileBased::mustExecute();
}

void Revolved::onChanged(const App::Property* prop)
{
    if (prop == &Midplane && !isRestoring() && !migratingDeprecatedProperties) {
        const char* impliedSideType = Midplane.getValue() ? "Symmetric" : "One side";

        // Scripts routinely assign every property, so only scream when the write actually
        // asks for something SideType is not already saying.
        if (SideType.getValueAsString() != std::string(impliedSideType)) {
            App::DocumentObject* obj = Profile.getValue();
            auto baseName = obj ? obj->getNameInDocument() : "";
            Base::Console().warning(
                "The 'Midplane' property being set for the revolution of %s is deprecated and has "
                "been replaced by the 'SideType' property in Revolved; assuming SideType='%s'."
                " Please update your script, this property will be removed in a future version.\n",
                baseName,
                impliedSideType
            );
            SideType.setValue(impliedSideType);
        }
    }

    ProfileBased::onChanged(prop);
}

App::DocumentObjectExecReturn* Revolved::executeRevolved(Part::RevolMode revolMode)
{
    try {
        return tryExecuteRevolved(revolMode);
    }
    catch (const Standard_Failure& e) {
        if (std::string(e.GetMessageString()) == "TopoDS::Face") {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Could not create face from sketch.\n"
                "Intersecting sketch entities in a sketch are not allowed."
            ));
        }

        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
}

App::DocumentObjectExecReturn* Revolved::tryExecuteRevolved(Part::RevolMode revolMode)
{
    if (onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    constexpr double maxDegree = 360.0;
    std::string sideType = SideType.getValueAsString();
    auto method = static_cast<RevolMethod>(Type.getValue());
    auto method2 = static_cast<RevolMethod>(Type2.getValue());

    if (method == RevolMethod::TwoAngles) {
        sideType = "Two sides";
        method = RevolMethod::Angle;
        method2 = RevolMethod::Angle;
    }
    if (method2 == RevolMethod::TwoAngles) {
        method2 = RevolMethod::Angle;
    }

    // Validate parameters
    double angleDeg = Angle.getValue();
    if (std::fabs(angleDeg) > maxDegree) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Angle of revolution too large")
        );
    }

    auto angle = Base::toRadians<double>(angleDeg);
    if (sideType != "Two sides" && std::fabs(angle) < Precision::Angular()
        && method == RevolMethod::Angle) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Angle of revolution too small")
        );
    }

    double angle2Deg = Angle2.getValue();
    if (std::fabs(angle2Deg) > maxDegree) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Angle of revolution too large")
        );
    }

    double angle2 = Base::toRadians(angle2Deg);

    if (sideType == "Two sides" && method == RevolMethod::Angle && method2 == RevolMethod::Angle
        && std::fabs(angle) >= Precision::Angular() && std::fabs(angle2) >= Precision::Angular()
        && std::fabs(angle + angle2) < Precision::Angular()) {
        const std::string warning = Base::Translation::translate(
            "PartDesign",
            QT_TRANSLATE_NOOP(
                "PartDesign",
                "The two revolution angles cancel each other resulting in an empty operation."
            )
        );
        Base::Console().warning("%s\n", warning.c_str());
    }

    TopoShape sketchshape = getTopoShapeVerifiedFace();

    // if the Base property has a valid shape, fuse the AddShape into it
    TopoShape base = tryGetBaseShape();

    // update Axis from ReferenceAxis
    updateAxis();

    // get revolve axis
    const Base::Vector3d v = Axis.getValue();
    if (v.IsNull()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Reference axis is invalid")
        );
    }

    if (sketchshape.isNull()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Creating a face from sketch failed")
        );
    }

    gp_Dir dir = Base::convertTo<gp_Dir>(v);
    gp_Pnt pnt = Base::convertTo<gp_Pnt>(Base.getValue());
    positionByPrevious();
    auto invObjLoc = getLocation().Inverted();
    pnt.Transform(invObjLoc.Transformation());
    dir.Transform(invObjLoc.Transformation());
    base.move(invObjLoc);
    sketchshape.move(invObjLoc);
    if (Reversed.getValue()) {
        dir.Reverse();
    }

    const gp_Ax1 revolutionAxis(pnt, dir);
    const char* startType = StartType.getValueAsString();
    const double startAngle = std::strcmp(startType, "Profile plane") == 0 ? 0.0
        : std::strcmp(startType, "Offset") == 0 ? Base::toRadians(StartOffset.getValue())
                                                : getStartReferenceAngle(
                                                      sketchshape,
                                                      StartReference,
                                                      revolutionAxis,
                                                      Base::toRadians(StartOffset.getValue()),
                                                      invObjLoc
                                                  );
    sketchshape = rotateProfileToStart(sketchshape, revolutionAxis, startAngle);

    // Check distance between sketchshape and axis - to avoid failures and crashes
    TopExp_Explorer xp;
    xp.Init(sketchshape.getShape(), TopAbs_FACE);
    for (; xp.More(); xp.Next()) {
        if (checkLineCrossesFace(gp_Lin(pnt, dir), TopoDS::Face(xp.Current()))) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Revolve axis intersects the sketch")
            );
        }
    }

    // Generate the revolution tool first; PartDesign applies the final base operation below.
    TopoShape result = makeTopoShape(false);
    TopoShape supportface = tryGetSupportShape();

    supportface.move(invObjLoc);

    std::vector<TopoShape> revolutions;
    auto addRevolution = [&revolutions](TopoShape&& revolution) {
        if (!revolution.isNull() && !revolution.getShape().IsNull()) {
            revolutions.emplace_back(std::move(revolution));
        }
    };

    bool fuseSideResults = false;

    // Both sides are named from the same profile edges under the feature's tag, so in V2 the
    // second side revolves a copy whose names are marked (CPY): otherwise the two sides' elements
    // share names, told apart only by the duplicate counter in the order of the final fuse
    // (ops#240). V1 keeps upstream's names.
    auto secondSideProfile = [&]() {
        const bool marked = getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2;
        return sketchshape.makeElementCopy(marked ? Part::OpCodes::Copy : nullptr);
    };

    if (sideType == "Two sides") {
        constexpr double fullRevolution = 2.0 * std::numbers::pi;
        const double combinedAngle = angle + angle2;
        const bool isThroughAll = revolMode == Part::RevolMode::CutFromBase
            && (method == RevolMethod::ThroughAll || method2 == RevolMethod::ThroughAll);
        const bool coversFullRevolution = method == RevolMethod::Angle
            && method2 == RevolMethod::Angle
            && std::fabs(combinedAngle) >= fullRevolution - Precision::Angular();

        if (isThroughAll || coversFullRevolution) {
            // Through all is direction-independent, so either side makes the other one
            // irrelevant. Likewise, cap overlapping two-angle sweeps at one full turn.
            // Smaller signed totals are handled as one exact angular interval below.
            addRevolution(generateSingleRevolutionSide(
                isThroughAll ? RevolMethod::ThroughAll : RevolMethod::Angle,
                fullRevolution,
                UpToFace,
                sketchshape.makeElementCopy(),
                base,
                supportface,
                pnt,
                dir,
                invObjLoc,
                revolMode
            ));
        }
        else if (
            method == RevolMethod::Angle && method2 == RevolMethod::Angle
            && std::fabs(combinedAngle) >= Precision::Angular()
        ) {
            // Both limits are angular, so construct the exact interval between them as one
            // primitive. Besides avoiding a boolean seam for opposite-side angles, this is
            // equivalent to XOR for same-side signed angles: 50 + (-20) starts at 20 degrees
            // and sweeps 30 degrees to 50 degrees.
            generateRevolution(
                result,
                sketchshape,
                gp_Ax1(pnt, dir),
                angle,
                angle2,
                false,
                false,
                RevolMethod::TwoAngles
            );
            addRevolution(std::move(result));
        }
        else {
            fuseSideResults = usesBRepFeatRevolution(method, revolMode)
                || usesBRepFeatRevolution(method2, revolMode);

            addRevolution(generateSingleRevolutionSide(
                method,
                angle,
                UpToFace,
                sketchshape.makeElementCopy(),
                base,
                supportface,
                pnt,
                dir,
                invObjLoc,
                revolMode
            ));

            gp_Dir dir2 = dir;
            dir2.Reverse();
            addRevolution(generateSingleRevolutionSide(
                method2,
                angle2,
                UpToFace2,
                secondSideProfile(),
                base,
                supportface,
                pnt,
                dir2,
                invObjLoc,
                revolMode
            ));
        }
    }
    else if (sideType == "Symmetric") {
        const bool isThroughAll = method == RevolMethod::ThroughAll
            && revolMode == Part::RevolMode::CutFromBase;
        if (method == RevolMethod::Angle || isThroughAll) {
            generateRevolution(result, sketchshape, gp_Ax1(pnt, dir), angle, 0.0, true, false, method);
            addRevolution(std::move(result));
        }
        else {
            fuseSideResults = usesBRepFeatRevolution(method, revolMode);
            gp_Ax1 axis(pnt, dir);
            TopoShape upToFace
                = getRevolutionUpToFace(method, UpToFace, base, sketchshape, invObjLoc, axis);
            TopoShape side = tryToRevolveToFace(
                upToFace,
                axis,
                base,
                supportface,
                sketchshape.makeElementCopy(),
                revolMode
            );
            if (!side.isNull() && !side.getShape().IsNull()) {
                addRevolution(side.makeElementCopy());

                // Use the profile's actual plane. The center of its axis-aligned bounding box is
                // not necessarily on that plane for an asymmetric tilted profile; using it as
                // the mirror origin made the angles unequal and could make BRepFeat fail.
                gp_Pln sketchPlane;
                if (!sketchshape.findPlane(sketchPlane)) {
                    throw Base::RuntimeError("Could not determine the sketch plane!");
                }
                gp_Ax2 mirrorPlane(sketchPlane.Location(), sketchPlane.Axis().Direction());
                TopoShape mirroredUpToFace = upToFace.makeElementMirror(mirrorPlane);
                gp_Dir dir2 = dir;
                dir2.Reverse();
                addRevolution(tryToRevolveToFace(
                    mirroredUpToFace,
                    gp_Ax1(pnt, dir2),
                    base,
                    supportface,
                    secondSideProfile(),
                    revolMode
                ));
            }
        }
    }
    else {
        addRevolution(generateSingleRevolutionSide(
            method,
            angle,
            UpToFace,
            sketchshape,
            base,
            supportface,
            pnt,
            dir,
            invObjLoc,
            revolMode
        ));
    }

    if (revolutions.empty()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "No revolution geometry was generated")
        );
    }
    if (revolutions.size() == 1) {
        result = revolutions.front();
    }
    else if (fuseSideResults) {
        // Up-to-face revolutions go through BRepFeat. Fuse the generated tools so that the
        // preview stays continuous before PartDesign applies the final base operation.
        result.makeElementFuse(revolutions, Part::OpCodes::Revolve);
    }
    else {
        result.makeElementXor(revolutions, Part::OpCodes::Revolve);
    }

    setResult(base, result);

    // eventually disable some settings that are not valid for the current method
    updateProperties();

    return App::DocumentObject::StdReturn;
}

void Revolved::setResult(const TopoShape& base, const TopoShape& revolved)
{
    if (revolved.isNull()) {
        throw Base::RuntimeError(QT_TRANSLATE_NOOP("Exception", "Could not revolve the sketch!"));
    }
    // store shape before refinement
    this->rawShape = revolved;
    TopoShape result = refineShapeIfActive(revolved);
    // set the additive shape property for later usage in e.g. pattern
    this->AddSubShape.setValue(result);

    if (!base.isNull()) {
        result = makeShape(base, result);
        // store shape before refinement
        this->rawShape = result;
        result = refineShapeIfActive(result);
    }
    if (!isSingleSolidRuleSatisfied(result.getShape())) {
        throw Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Result has multiple solids: enable 'Allow Compound' in the active body."
        ));
    }
    result = getSolid(result);
    this->Shape.setValue(result);
}

TopoShape Revolved::tryToRevolveToFace(
    const TopoShape& upToFace,
    const gp_Ax1& axis,
    const TopoShape& base,
    TopoShape supportface,
    const TopoShape& sketchshape,
    Part::RevolMode revolMode
) const
{
    TopExp_Explorer Ex(supportface.getShape(), TopAbs_WIRE);
    if (!Ex.More()) {
        supportface = TopoDS_Face();
    }

    // BRepFeat_MakeRevol needs a solid base, and its result holds the base besides the revolved
    // tool. Without a solid before this feature, give it a box on the axis, and cut it out again
    // below. The profile itself as the base, as makeElementPrismUntil() does for Pad, gives a null
    // shape (ops#191).
    // The box can't touch the tool or the base: a rotation about the axis keeps each point's
    // position along the axis, so the whole sweep lies within |location - center| + diagonal / 2
    // of the axis location along it (center and diagonal of the bounding box of the profile and
    // the base), and the box starts more than half a diagonal beyond that.
    // The box is also what BRepFeat trims an unbounded up-to face to (BRepFeat::FaceUntil: a
    // square sized from 10 times the base's largest bounding box coordinate).
    // A small box near the axis made that square miss part of the sweep: a loud failure, or a
    // nearly full ring instead of a quarter (ops#239). So the box is centred radially on the
    // axis, and its side is twice the distance from the global origin to anything involved:
    // its largest coordinate then exceeds that distance in any direction.
    // With an unbounded up-to face (no wire, as a datum or origin plane, or an infinite bounding
    // box), which is what FaceUntil trims, a base gets the box too, beside it in a compound: a
    // small base made the square just as small, with the same wrong ring (ops#242). The box then
    // clears the base as well. A bounded up-to face isn't trimmed and keeps the base alone.
    // A Groove without a base gets the same box: makeRemovedVolume() then fails and the tool
    // itself becomes the result, as for a Groove by angle or a Pocket as the first feature.
    auto isUnbounded = [](const TopoShape& face) {
        if (face.isNull()) {
            return false;
        }
        if (!TopExp_Explorer(face.getShape(), TopAbs_WIRE).More()) {
            return true;
        }
        Base::BoundBox3d faceBox = face.getBoundBox();
        return !faceBox.IsValid() || Precision::IsInfinite(faceBox.CalcDiagonalLength());
    };
    TopoShape featureBase = base;
    if (base.isNull() || isUnbounded(upToFace)) {
        Base::BoundBox3d bounds = sketchshape.getBoundBox();
        if (!base.isNull()) {
            bounds.Add(base.getBoundBox());
        }
        gp_Pnt center(bounds.GetCenter().x, bounds.GetCenter().y, bounds.GetCenter().z);
        const gp_Pnt& location = axis.Location();
        double clearance = location.Distance(center) + bounds.CalcDiagonalLength() + 1.0;
        // The up-to face's reach is a margin: a datum plane's origin far from the profile made no
        // difference in probes (ops#239). An infinite face's bounding box (about 1e100) would
        // make the cube lose the clearance to rounding, so only a finite box counts, and an
        // elementary surface adds its location.
        double faceReach = 0.0;
        if (!upToFace.isNull() && upToFace.getShape().ShapeType() == TopAbs_FACE) {
            Handle(Geom_ElementarySurface) surface = Handle(Geom_ElementarySurface)::DownCast(
                BRep_Tool::Surface(TopoDS::Face(upToFace.getShape()))
            );
            if (!surface.IsNull()) {
                faceReach = surface->Location().Distance(gp::Origin());
            }
            Base::BoundBox3d faceBox = upToFace.getBoundBox();
            if (faceBox.IsValid() && !Precision::IsInfinite(faceBox.CalcDiagonalLength())) {
                faceReach = std::max(
                    faceReach,
                    faceBox.GetCenter().Length() + faceBox.CalcDiagonalLength() / 2.0
                );
            }
        }
        double side = 2.0 * (location.Distance(gp::Origin()) + clearance + faceReach) + 2.0;
        gp_Ax2 frame(location.Translated(gp_Vec(axis.Direction()) * clearance), axis.Direction());
        gp_Pnt corner = frame.Location().Translated(
            (gp_Vec(frame.XDirection()) + gp_Vec(frame.YDirection())) * (-side / 2.0)
        );
        gp_Ax2 boxFrame(corner, axis.Direction(), frame.XDirection());
        TopoShape box(BRepPrimAPI_MakeBox(boxFrame, side, side, side).Shape());
        featureBase = base.isNull() ? box : TopoShape().makeElementCompound({base, box});
    }

    auto makeRevolution = [&](Part::RevolMode mode, Standard_Boolean modify) {
        TopoShape revolution = makeTopoShape();
        revolution.makeElementRevolution(
            featureBase,
            sketchshape,
            axis,
            supportface,
            TopoDS::Face(upToFace.getShape()),
            nullptr,
            mode,
            modify
        );
        if (revolution.isNull() || revolution.getShape().IsNull()) {
            throw Base::RuntimeError("Could not revolve the sketch!");
        }
        return revolution;
    };

    auto makeGeneratedTool = [&](const TopoShape& baseResult) {
        TopoShape tool = makeTopoShape();
        tool.makeElementCut({baseResult, featureBase}, Part::OpCodes::Revolve);
        if (tool.isNull() || tool.getShape().IsNull()) {
            throw Base::RuntimeError("Could not extract generated revolution tool!");
        }
        return tool;
    };

    auto makeRemovedVolume = [&](const TopoShape& baseResult) {
        TopoShape tool = makeTopoShape();
        tool.makeElementCut({base, baseResult}, Part::OpCodes::Revolve);
        if (tool.isNull() || tool.getShape().IsNull()) {
            throw Base::RuntimeError("Could not extract generated groove tool!");
        }
        return tool;
    };

    if (revolMode == Part::RevolMode::CutFromBase) {
        try {
            return makeRemovedVolume(makeRevolution(revolMode, Standard_True));
        }
        catch (const Base::Exception&) {
            // If the groove side removes no material, keep trying to return the cutter tool
            // itself so a no-op side behaves like an angle-based groove.
        }
        catch (const Standard_Failure&) {
            // Fall through to cutter generation below.
        }
    }

    try {
        return makeGeneratedTool(makeRevolution(Part::RevolMode::None, Standard_False));
    }
    catch (const Base::Exception&) {
        // Some OCCT cases require a feature mode. Falling back keeps up-to-face usable.
    }
    catch (const Standard_Failure&) {
        // Fall through to the feature mode below.
    }

    try {
        return makeGeneratedTool(makeRevolution(Part::RevolMode::FuseWithBase, Standard_True));
    }
    catch (const Base::Exception&) {
        throw Base::RuntimeError("Could not revolve the sketch!");
    }
    catch (const Standard_Failure&) {
        throw Base::RuntimeError("Could not revolve the sketch!");
    }
}

TopoShape Revolved::generateSingleRevolutionSide(
    RevolMethod method,
    double angle,
    App::PropertyLinkSub& upToFaceProp,
    const TopoShape& sketchshape,
    const TopoShape& base,
    TopoShape supportface,
    const gp_Pnt& pnt,
    const gp_Dir& dir,
    const TopLoc_Location& invObjLoc,
    Part::RevolMode revolMode
)
{
    TopoShape revolution = makeTopoShape();
    const bool isThroughAll = method == RevolMethod::ThroughAll
        && revolMode == Part::RevolMode::CutFromBase;

    if (method == RevolMethod::Angle || isThroughAll) {
        if (method == RevolMethod::Angle && std::fabs(angle) < Precision::Angular()) {
            return revolution;
        }
        generateRevolution(revolution, sketchshape, gp_Ax1(pnt, dir), angle, 0.0, false, false, method);
    }
    else if (
        method == RevolMethod::ToFirst
        || (method == RevolMethod::ToLast && revolMode == Part::RevolMode::FuseWithBase)
        || method == RevolMethod::ToFace
    ) {
        gp_Ax1 axis(pnt, dir);
        TopoShape upToFace
            = getRevolutionUpToFace(method, upToFaceProp, base, sketchshape, invObjLoc, axis);

        revolution = tryToRevolveToFace(upToFace, axis, base, supportface, sketchshape, revolMode);
    }
    else {
        throw Base::RuntimeError(
            "ProfileBased: Internal error: Unknown method for generateSingleRevolutionSide()"
        );
    }

    return revolution;
}

TopoShape Revolved::getRevolutionUpToFace(
    RevolMethod method,
    const App::PropertyLinkSub& upToFaceProp,
    const TopoShape& base,
    const TopoShape& sketchshape,
    const TopLoc_Location& invObjLoc,
    const gp_Ax1& axis
) const
{
    TopoShape upToFace;
    if (method == RevolMethod::ToFace) {
        getUpToFaceFromLinkSub(upToFace, upToFaceProp);
        upToFace.move(invObjLoc);
    }
    else {
        getUpToFace(
            upToFace,
            base,
            sketchshape,
            method == RevolMethod::ToFirst ? "UpToFirst" : "UpToLast",
            axis
        );
    }
    return upToFace;
}

TopoShape Revolved::tryGetBaseShape() const
{
    TopoShape base = makeTopoShape(false);
    try {
        base = getBaseTopoShape();
    }
    catch (const Base::Exception&) {
        // fall back to support (for legacy features)
    }

    return base;
}

TopoShape Revolved::tryGetSupportShape() const
{
    TopoShape supportface = makeTopoShape(false);
    try {
        supportface = getSupportFace();
    }
    catch (...) {
        // do nothing, null shape is handled later
    }

    return supportface;
}

bool Revolved::suggestReversed()
{
    try {
        updateAxis();
    }
    catch (const Base::Exception&) {
        return false;
    }

    double angle = ProfileBased::getReversedAngle(Base.getValue(), Axis.getValue());
    return suggestReversedAngle(angle);
}

double Revolved::getStartOffset() const
{
    const char* startType = StartType.getValueAsString();
    if (std::strcmp(startType, "Profile plane") == 0) {
        return 0.0;
    }
    if (std::strcmp(startType, "Offset") == 0) {
        return StartOffset.getValue();
    }

    const Base::Vector3d axisBase = Base.getValue();
    const Base::Vector3d axisDirection = Axis.getValue();
    gp_Ax1 axis(Base::convertTo<gp_Pnt>(axisBase), Base::convertTo<gp_Dir>(axisDirection));
    if (Reversed.getValue()) {
        axis.Reverse();
    }

    TopLoc_Location identity;
    return Base::toDegrees(getStartReferenceAngle(
        getTopoShapeVerifiedFace(),
        StartReference,
        axis,
        Base::toRadians(StartOffset.getValue()),
        identity
    ));
}

double Revolved::getStartReferenceAngle(
    const TopoShape& profileShape,
    const App::PropertyLinkSub& reference,
    const gp_Ax1& axis,
    double offset,
    const TopLoc_Location& invObjLoc
) const
{
    if (!reference.getValue()) {
        return 0.0;
    }

    TopoShape referenceShape;
    const auto& subValues = reference.getSubValues();
    if (reference.getValue()->isDerivedFrom<Part::Part2DObject>()) {
        if (!subValues.empty()) {
            const Part::ShapeOptions options = Part::ShapeOption::NeedSubElement
                | Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform;
            referenceShape = Part::Feature::getTopoShape(
                reference.getValue(),
                options,
                subValues.front().c_str()
            );
        }
        if (!referenceShape.hasSubShape(TopAbs_FACE)) {
            referenceShape = getTopoShapeVerifiedFace(false, false, reference.getValue(), subValues);
        }
    }
    else {
        getUpToFaceFromLinkSub(referenceShape, reference);
    }
    referenceShape.move(invObjLoc);

    if (const auto angle = getPlanarStartReferenceAngle(profileShape, referenceShape, axis)) {
        return *angle + offset;
    }

    gp_Pnt orbitCenter;
    gp_Vec radial;
    if (!getProfileOrbit(profileShape, axis, orbitCenter, radial)) {
        throw Base::ValueError("Revolved: Cannot determine the profile path around the axis");
    }

    const auto faces = Part::findAllFacesCutBy(referenceShape, profileShape, axis);
    if (faces.empty()) {
        throw Base::ValueError("Revolved: Start reference does not intersect the profile path");
    }

    const auto nearest = std::ranges::min_element(faces, {}, &Part::cutTopoShapeFaces::distsq);
    return nearest->distsq / radial.Magnitude() + offset;
}

TopoShape Revolved::rotateProfileToStart(const TopoShape& profileShape, const gp_Ax1& axis, double angle)
{
    if (std::fabs(angle) < Precision::Angular()) {
        return profileShape;
    }

    TopoShape result = profileShape.makeElementCopy();
    gp_Trsf transform;
    transform.SetRotation(axis, angle);
    result.move(transform);
    return result;
}

void Revolved::updateAxis()
{
    App::DocumentObject* pcReferenceAxis = ReferenceAxis.getValue();
    const std::vector<std::string>& subReferenceAxis = ReferenceAxis.getSubValues();
    Base::Vector3d base;
    Base::Vector3d dir;
    getAxis(pcReferenceAxis, subReferenceAxis, base, dir, ForbiddenAxis::NotParallelWithNormal);

    Base.setValue(base);
    Axis.setValue(dir);
}

void Revolved::generateRevolution(
    TopoShape& revol,
    const TopoShape& sketchshape,
    const gp_Ax1& axis,
    double angle,
    double angle2,
    bool midplane,
    bool reversed,
    RevolMethod method
)
{
    if (method == RevolMethod::Angle || method == RevolMethod::TwoAngles
        || method == RevolMethod::ThroughAll) {
        double angleTotal = angle;
        double angleOffset = 0.;

        if (method == RevolMethod::TwoAngles) {
            // Rotate the face by `angle2`/`angle` to get "second" angle
            angleTotal += angle2;
            angleOffset = angle2 * -1.0;
        }
        else if (method == RevolMethod::ThroughAll) {
            angleTotal = 2 * std::numbers::pi;
        }
        else if (midplane) {
            // Rotate the face by half the angle to get Revolution symmetric to sketch plane
            angleOffset = -angle / 2;
        }

        if (std::fabs(angleTotal) < Precision::Angular()) {
            throw Base::ValueError("Cannot create a revolution with zero angle.");
        }

        gp_Ax1 revolAx(axis);
        if (reversed) {
            revolAx.Reverse();
        }

        TopoShape from = sketchshape;
        if (method == RevolMethod::TwoAngles || midplane) {
            gp_Trsf mov;
            mov.SetRotation(revolAx, angleOffset);
            TopLoc_Location loc(mov);
            from.move(loc);
        }

        // revolve the face to a solid
        // BRepPrimAPI is the only option that allows use of this shape for patterns.
        // See https://forum.freecad.org/viewtopic.php?f=8&t=70185&p=611673#p611673.
        revol = from;
        revol = revol.makeElementRevolve(revolAx, angleTotal);
        revol.Tag = -getID();
    }
    else {
        throw Base::RuntimeError(
            "ProfileBased: Internal error: Unknown method for generateRevolution()"
        );
    }
}

void Revolved::updateProperties()
{
    const std::string sideType = SideType.getValueAsString();
    const std::string method = Type.getValueAsString();
    const std::string method2 = Type2.getValueAsString();

    bool isAngleEnabled = method == "Angle";
    bool isUpToFaceEnabled = method == "UpToFace";
    bool isType2Enabled = sideType == "Two sides";
    bool isAngle2Enabled = isType2Enabled && (method2 == "Angle" || isLegacyTwoAngles(method2));
    bool isUpToFace2Enabled = isType2Enabled && method2 == "UpToFace";

    if (isLegacyTwoAngles(method)) {
        isAngleEnabled = true;
        isType2Enabled = true;
        isAngle2Enabled = true;
    }

    const bool isSymmetricAngleLike = sideType == "Symmetric"
        && (method == "Angle" || method == "ThroughAll");

    Angle.setReadOnly(!isAngleEnabled);
    Type2.setReadOnly(!isType2Enabled);
    Angle2.setReadOnly(!isAngle2Enabled);
    Midplane.setReadOnly(true);
    Reversed.setReadOnly(isSymmetricAngleLike);
    UpToFace.setReadOnly(!isUpToFaceEnabled);
    UpToFace2.setReadOnly(!isUpToFace2Enabled);

    const bool isStartOffsetEnabled = std::strcmp(StartType.getValueAsString(), "Profile plane") != 0;
    StartOffset.setReadOnly(!isStartOffsetEnabled);
    StartReference.setReadOnly(std::strcmp(StartType.getValueAsString(), "Reference") != 0);
}

void Revolved::onDocumentRestored()
{
    Base::StateLocker migrating(migratingDeprecatedProperties);

    if (isLegacyTwoAngles(Type.getValueAsString())) {
        Type.setValue("Angle");
        Type2.setValue("Angle");
        SideType.setValue("Two sides");
    }
    else {
        if (isLegacyTwoAngles(Type2.getValueAsString())) {
            Type2.setValue("Angle");
        }
        if (Midplane.getValue()) {
            Midplane.setValue(false);
            SideType.setValue("Symmetric");
        }
    }

    ProfileBased::onDocumentRestored();
}

}  // namespace PartDesign
