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
#include <limits>

#include <BRepFilletAPI_MakeChamfer.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <gp_Trsf.hxx>
#include <ShapeFix_Shape.hxx>
#include <Standard_Version.hxx>


#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Base/Tools.h>
#include <Mod/Part/App/FilletFallback.h>
#include <Mod/Part/App/SignalException.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeRepair.h>

#include "FeatureChamfer.h"
#include "ResultCheck.h"

#include <Base/ProgramVersion.h>


FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesign;

namespace PartDesign
{
// FeatureDressUp.cpp (ops#640 F2, Onshape's failure text; declared where used)
PartDesignExport std::string dressUpFailure(const char* verb, const std::string& what);
PartDesignExport bool isDressUpFailure(const std::string& what);
// FeatureDressUp.cpp (FreeCAD-CH ops#654 T3; declared where used)
PartDesignExport bool dressUpReapplying(Part::TopoShape& base, std::vector<Part::TopoShape>& edges);
// ops#942 (FeatureDressUp.cpp): a pattern instance's move from the seed's base
PartDesignExport bool dressUpReapplyMove(gp_Trsf& move);
PartDesignExport void dressUpReapplied(const Part::TopoShape& result);
// ops#796 (FeatureDressUp.cpp): a studio step takes what its owner's try built
PartDesignExport void dressUpReappliedFrom(const Part::TopoShape& raw,
                                           const Part::TopoShape& result,
                                           bool plain);
PartDesignExport bool studioDressUpTake(const DressUp* step,
                                        const Part::TopoShape& base,
                                        const std::vector<Part::TopoShape>& edges,
                                        Part::TopoShape& raw);
PartDesignExport const DressUp* dressUpTriedFor(const DressUp* step);
// FeatureDressUp.cpp (FreeCAD-CH ops#654 P8a; declared where used)
PartDesignExport App::DocumentObjectExecReturn* studioDressUpOwnerRun(DressUp* owner);
PartDesignExport bool studioDressUpStepPassesThrough(DressUp* step);
PartDesignExport bool runsAsStudioOwner(const Feature* feature);
// FeatureDressUp.cpp (ops#655, tangent propagation off)
PartDesignExport std::vector<Part::TopoShape> takeChainedEdges(
    const Part::TopoShape& base,
    std::vector<Part::TopoShape>& edges,
    double radius
);
PartDesignExport TopoDS_Shape runOutCut(
    const TopoDS_Shape& shape,
    const TopoDS_Shape& base,
    const TopoDS_Edge& edge,
    double radius,
    bool arc
);
}  // namespace PartDesign


PROPERTY_SOURCE(PartDesign::Chamfer, PartDesign::DressUp)

const char* ChamferTypeEnums[] = {"Equal distance", "Two distances", "Distance and Angle", nullptr};
// ops#942: Part::FilletFallback::WidthAt, by index; values are only ever appended
const char* WidthAtEnums[] = {"Narrowest angle", "Widest angle", "At a reference point", nullptr};
const App::PropertyQuantityConstraint::Constraints Chamfer::floatSize
    = {0.0, std::numeric_limits<float>::max(), 0.1};
const App::PropertyAngle::Constraints Chamfer::floatAngle = {0.0, 180.0, 1.0};

static App::DocumentObjectExecReturn* validateParameters(
    int chamferType,
    double size,
    double size2,
    double angle
);

Chamfer::Chamfer()
{
    ADD_PROPERTY_TYPE(ChamferType, (0L), "Chamfer", App::Prop_None, "Type of chamfer");
    ChamferType.setEnums(ChamferTypeEnums);

    ADD_PROPERTY_TYPE(Size, (1.0), "Chamfer", App::Prop_None, "Size of chamfer");
    Size.setUnit(Base::Unit::Length);
    Size.setConstraints(&floatSize);

    ADD_PROPERTY_TYPE(Size2, (1.0), "Chamfer", App::Prop_None, "Second size of chamfer");
    Size2.setUnit(Base::Unit::Length);
    Size2.setConstraints(&floatSize);

    ADD_PROPERTY_TYPE(Angle, (45.0), "Chamfer", App::Prop_None, "Angle of chamfer");
    Angle.setUnit(Base::Unit::Angle);
    Angle.setConstraints(&floatAngle);

    ADD_PROPERTY_TYPE(FlipDirection, (false), "Chamfer", App::Prop_None, "Flip direction");
    ADD_PROPERTY_TYPE(
        UseAllEdges,
        (false),
        "Chamfer",
        App::Prop_None,
        "Chamfer all edges if true, else use only those edges in Base property.\n"
        "If true, then this overrides any edge changes made to the Base property or in the "
        "dialog.\n"
    );
    ADD_PROPERTY_TYPE(
        TangentPropagation,
        (true),
        "Chamfer",
        App::Prop_None,
        "Chamfer the whole tangent chain of each picked edge (Onshape's 'Tangent propagation').\n"
        "Off: only the picked edges; where a picked straight edge continues tangentially, the\n"
        "chamfer (equal distance only) runs straight on until it leaves the body, as Onshape's does."
    );
    ADD_PROPERTY_TYPE(
        WidthAt,
        (0L),
        "Chamfer",
        App::Prop_None,
        "Equal distance, along a closed edge whose faces meet at an angle that varies round it:\n"
        "where the chamfer has the width typed. It keeps one distance to both faces all round.\n"
        "Narrowest angle: the width is the chamfer's longest leg. Widest angle: its shortest.\n"
        "At a reference point: at the station of each edge's point in WidthPoints."
    );
    WidthAt.setEnums(WidthAtEnums);
    ADD_PROPERTY_TYPE(
        WidthPoints,
        (),
        "Chamfer",
        App::Prop_None,
        "For each picked edge, a point at the station whose angle sets the chamfer's distance;\n"
        "set by the transfer, or typed. Used with WidthAt 'At a reference point' only."
    );

    updateProperties();
}

short Chamfer::mustExecute() const
{
    bool touched = false;

    auto chamferType = ChamferType.getValue();

    switch (chamferType) {
        case 0:  // "Equal distance"
            touched = Size.isTouched() || ChamferType.isTouched() || WidthAt.isTouched()
                || WidthPoints.isTouched();
            break;
        case 1:  // "Two distances"
            touched = Size.isTouched() || ChamferType.isTouched() || Size2.isTouched();
            break;
        case 2:  // "Distance and Angle"
            touched = Size.isTouched() || ChamferType.isTouched() || Angle.isTouched();
            break;
    }

    if (Placement.isTouched() || TangentPropagation.isTouched() || touched) {
        return 1;
    }
    return DressUp::mustExecute();
}

App::DocumentObjectExecReturn* Chamfer::execute()
{
    // FreeCAD-CH ops#701 (F2b): over several parts, this part failing while the first part's
    // builds is a warning, as Onshape's CHAMFER_PARTIAL_FAIL
    return partialFailure(build(), "chamfer", "Size");
}

App::DocumentObjectExecReturn* Chamfer::build()
{
    // FreeCAD-CH ops#654 T3: re-run at a pattern's instance, on its base and edges
    Part::TopoShape reapplyBase;
    std::vector<Part::TopoShape> reapplyEdges;
    const bool reapplying = dressUpReapplying(reapplyBase, reapplyEdges);
    // FreeCAD-CH ops#654 P8a: a studio feature over several parts computes no shape of its own;
    // its steps read its parameters, and one whose part failed passes its base through (O2)
    if (!reapplying && runsAsStudioOwner(this)) {
        return studioDressUpOwnerRun(this);
    }
    if (!reapplying && StudioOwner.getValue() && studioDressUpStepPassesThrough(this)) {
        this->positionByBaseFeature();
        Shape.setValue(getBaseTopoShape(/*silent=*/true));
        return App::DocumentObject::StdReturn;
    }
    if (!reapplying && onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }

    // NOTE: Normally the Base property and the BaseFeature property should point to the same object.
    // The only difference is that the Base property also stores the edges that are to be chamfered
    Part::TopoShape TopShape;
    try {
        TopShape = reapplying ? reapplyBase : getBaseTopoShape();
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }

    TopShape.locate(TopLoc_Location());

    auto edges = reapplying            ? reapplyEdges
        : UseAllEdges.getValue() ? TopShape.getSubTopoShapes(TopAbs_EDGE)
                                 : getContinuousEdges(TopShape);

    if (edges.empty()) {
        return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP("Exception", "No edges specified"));
    }
    const int chamferType = ChamferType.getValue();
    const double size = Size.getValue();
    double size2 = Size2.getValue();
    const double angle = Angle.getValue();
    const bool flipDirection = FlipDirection.getValue();

    auto res = validateParameters(chamferType, size, size2, angle);
    if (res != App::DocumentObject::StdReturn) {
        return res;
    }

    if (!reapplying) {
        this->positionByBaseFeature();
    }
    // The chamfer's largest distance along a face, for the check of what it drops (ops#603). By
    // distance and angle, the distance on the other face grows without bound as the angle and the
    // edge's opening near 180 degrees: unknown, so that check doesn't run (PR review r1, T2)
    double reach = std::max(size, size2);
    bool setbacksDiffer = false;
    // ops#942: where the chamfer takes its width along an edge whose faces' angle varies
    Part::FilletFallback::ChamferWidth width;
    width.at = static_cast<Part::FilletFallback::WidthAt>(WidthAt.getValue());
    for (const auto& point : WidthPoints.getValues()) {
        width.points.emplace_back(point.x, point.y, point.z);
    }
    if (width.at == Part::FilletFallback::WidthAt::atPoint
        && static_cast<Part::ChamferType>(chamferType) == Part::ChamferType::equalDistance) {
        // The points are the Body's; the base shape is computed in its own feature's frame
        // (notes/chamfer-varying-angle-942.md section 4 point 8)
        const Part::TopoShape own = getBaseTopoShape(/*silent=*/true);
        if (!own.isNull()) {
            const gp_Trsf toOwn = own.getShape().Location().Transformation().Inverted();
            for (auto& point : width.points) {
                point.Transform(toOwn);
            }
        }
    }
    if (reapplying && width.at == Part::FilletFallback::WidthAt::atPoint
        && static_cast<Part::ChamferType>(chamferType) == Part::ChamferType::equalDistance) {
        // At a pattern's instance the points move with the edges (section 4 point 10); a studio
        // step's part has a frame of its own, not measured, so the value fails there
        gp_Trsf move;
        if (!dressUpReapplyMove(move)) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Chamfer: 'At a reference point' is not available on a chamfer over several "
                "parts; choose Narrowest angle or Widest angle"
            ));
        }
        for (auto& point : width.points) {
            point.Transform(move);
        }
    }
    bool varying = false;
    if (static_cast<Part::ChamferType>(chamferType) == Part::ChamferType::equalDistance) {
        // A chain of edges at different angles gets Onshape's setbacks, which can exceed the
        // size (0.714 of it beside a 110-degree first edge): the largest, as makeElementChamfer's
        reach = size;
        try {
            std::vector<TopoShape> copies = edges;
            const TopoShape input = Part::FilletFallback::makerInput(TopShape, copies);
            for (double setback : Part::FilletFallback::chainSetbacks(input, copies, size)) {
                reach = std::max(reach, setback);
                setbacksDiffer = setbacksDiffer || setback != size;
            }
            // One ball rolled round each edge (ops#942): its longest leg is the width at the
            // narrowest angle, and more with the width elsewhere
            Part::FilletFallback::Request request;
            request.kind = Part::FilletFallback::Kind::Chamfer;
            request.size1 = size;
            request.size2 = size;
            request.flipDirection = flipDirection ? Part::Flip::flip : Part::Flip::none;
            request.widthAt = width.at;
            request.widthPoints = width.points;
            std::vector<TopoDS_Shape> plain;
            for (const auto& edge : copies) {
                plain.push_back(edge.getShape());
            }
            if (!setbacksDiffer
                && Part::FilletFallback::variesAlongLoneEdge(input.getShape(), plain, request)) {
                varying = true;
                reach = std::max(
                    reach,
                    Part::FilletFallback::longestLeg(input.getShape(), plain, request)
                );
            }
        }
        catch (const Base::Exception&) {
            // makeElementChamfer reports it
        }
    }
    if (static_cast<Part::ChamferType>(chamferType) == Part::ChamferType::distanceAngle) {
        // The other face's distance, bounded by the edges' opening (ops#622); unbounded near an
        // opening + angle of 180 degrees, where the checks don't run
        reach = std::max(
            0.0,
            Part::distanceAngleReach(TopShape, edges, size, Base::toRadians(angle))
        );
        size2 = angle;
    }
    // One pass: the chamfer from scratch, its checks, and the feature's result if they pass. Each
    // pass starts from the picked edges (the run-out split below takes edges out of its own copy)
    auto chamferWith = [&](Part::ChamferType type,
                           double distance2,
                           double passReach) -> App::DocumentObjectExecReturn* {
        try {
            TopoShape shape = makeTopoShape();
            Part::SignalException sig;

            Part::FilletFallback::Recorder recorder;
            // ops#796: a studio step's owner built it already, on this base and these edges,
            // with these parameters, and checked it: the step goes on from the shape before the
            // refine
            if (Part::TopoShape raw;
                !reapplying && StudioOwner.getValue() && studioDressUpTake(this, TopShape, edges, raw)) {
                this->rawShape = raw;
                shape = refineShapeIfActive(raw);
                if (!isSingleSolidRuleSatisfied(shape.getShape())) {
                    return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Result has multiple solids: enable 'Allow Compound' in the active body."
                    ));
                }
                this->Shape.setValue(getSolid(shape));
                return App::DocumentObject::StdReturn;
            }
            std::vector<Part::TopoShape> passEdges = edges;
            // ops#655: with tangent propagation off, an edge whose tangent chain goes on is cut
            // Onshape's way after the others are chamfered (GB13); by equal distance only, since
            // which face takes which distance is OCCT's choice otherwise (the type asked for: the
            // retry with w on every edge is an equal distance chamfer too)
            const std::vector<Part::TopoShape> runOut = TangentPropagation.getValue()
                ? std::vector<Part::TopoShape>()
                : takeChainedEdges(TopShape, passEdges, size);
            if (!runOut.empty()
                && static_cast<Part::ChamferType>(chamferType) != Part::ChamferType::equalDistance) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Tangent propagation off: a picked edge continues tangentially into an edge that "
                    "isn't picked, and only an equal distance chamfer can stop there. Pick the whole "
                    "tangent chain, or turn tangent propagation on."
                ));
            }
            if (passEdges.empty()) {
                shape = TopShape;
            }
            else {
                // The retry with w on both faces (below) is by two distances: the rule is read
                // only by equal distances
                Part::FilletFallback::ChamferWidthScope scope(width);
                shape.makeElementChamfer(
                    TopShape,
                    passEdges,
                    type,
                    size,
                    distance2,
                    nullptr,
                    flipDirection ? Part::Flip::flip : Part::Flip::none
                );
            }
            if (shape.isNull()) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Failed to create chamfer")
                );
            }

            // Repair an invalid result on a copy, keeping names, or fail (see Fillet::execute(),
            // ops#12, ops#168, ops#297). Solids and shells only, as OCCT returns them: a later
            // feature fails on a BaseFeature's loose faces (ops#303)
            if (!Part::checkDressUp(shape, TopShape, Part::LooseParts::drop)) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Resulting shape is invalid")
                );
            }
            // OCCT fills a recess its band crosses, in a valid solid (ops#393)
            if (!passEdges.empty()) {
                ResultCheck::stopIfPastTheLimit("The chamfer's check for a filled recess");
            }
            const std::string filled = passEdges.empty()
                ? std::string()
                : Part::filledPocket(shape, TopShape, passEdges, passReach);
            if (!filled.empty()) {
                return new App::DocumentObjectExecReturn("The chamfer " + filled);
            }
            // OCCT stopping a hair short of a step drops the step's upper part, in a valid solid
            // (ops#603). Not for the wedge the exact construction ran on through the part: it
            // cuts faces beyond the band this check allows, and the construction checked what it
            // removed against the wedge (ops#936)
            if (!passEdges.empty()) {
                ResultCheck::stopIfPastTheLimit("The chamfer's check for lost material");
            }
            const std::string lost = passEdges.empty() || recorder.ranThrough()
                ? std::string()
                : Part::lostMaterial(shape, TopShape, passEdges, passReach);
            if (!lost.empty()) {
                return new App::DocumentObjectExecReturn("The chamfer " + lost);
            }
            // ops#655: each chained edge's chamfer runs straight on until it leaves the body (GB13)
            for (const auto& edge : runOut) {
                const TopoDS_Shape tool = runOutCut(
                    shape.getShape(),
                    TopShape.getShape(),
                    TopoDS::Edge(edge.getShape()),
                    size,
                    false
                );
                if (tool.IsNull()) {
                    continue;
                }
                TopoShape cut = makeTopoShape();
                cut.makeElementCut({shape, makeTopoShape(tool)});
                shape = cut;
            }
            if (!runOut.empty() && !Part::checkDressUp(shape, TopShape, Part::LooseParts::drop)) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Resulting shape is invalid")
                );
            }
            if (reapplying) {
                auto owner = freecad_cast<Chamfer*>(const_cast<DressUp*>(dressUpTriedFor(this)));
                dressUpReappliedFrom(
                    shape,
                    owner ? owner->refineShapeIfActive(shape) : refineShapeIfActive(shape),
                    !recorder.built()
                );
                return App::DocumentObject::StdReturn;
            }
            // store shape before refinement
            this->rawShape = shape;
            shape = refineShapeIfActive(shape);
            if (!isSingleSolidRuleSatisfied(shape.getShape())) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Result has multiple solids: enable 'Allow Compound' in the active body."
                ));
            }

            shape = getSolid(shape);
            // Where OCCT failed, the exact construction built it (ops#300, decision 54), once
            // the feature has its result
            recorder.report(Label.getValue());
            this->Shape.setValue(shape);
            return App::DocumentObject::StdReturn;
        }
        // ops#640 F2: Onshape's "Failed to chamfer selections" with the exact construction's
        // reason, never OCCT's raw text; the fork's other errors (a time limit, Esc) go on as
        // before, and are never retried
        catch (Base::Exception& e) {
            if (!isDressUpFailure(e.what())) {
                throw;
            }
            return new App::DocumentObjectExecReturn(dressUpFailure("chamfer", e.what()));
        }
        catch (Standard_Failure& e) {
            const char* what = e.GetMessageString();
            return new App::DocumentObjectExecReturn(dressUpFailure("chamfer", what ? what : ""));
        }
        catch (...) {
            return new App::DocumentObjectExecReturn(dressUpFailure("chamfer", ""));
        }
    };
    App::DocumentObjectExecReturn* result
        = chamferWith(static_cast<Part::ChamferType>(chamferType), size2, reach);
    // Where the chain's setbacks build but fail a check, the chamfer is built again with w on
    // every edge, today's result (Add(w, w) as makeElementChamfer's own retry), reaching w: a
    // chamfer that built with w never starts failing (ruling A, review r1 T1). Its error, if it
    // fails too, is the one reported
    // Along an edge of varying angle (ops#942) the same, with the width at the narrowest angle
    // only: with the width elsewhere, the result with w on both faces is far from the one asked
    // for, and the chamfer fails instead (notes/chamfer-varying-angle-942.md 4, point 10)
    const bool retry = setbacksDiffer
        || (varying && width.at == Part::FilletFallback::WidthAt::narrowest);
    if (result != App::DocumentObject::StdReturn && retry) {
        FC_LOG(
            getFullName() << ": the chain's setbacks or the rolling ball failed (" << result->Why
                          << "), building the chamfer again with " << size << " on every edge"
        );
        // Along an edge of varying angle the rolling ball's refusal says more than OCCT's failure
        // with w (the cause the user can act on: notes/chamfer-varying-angle-942.md T6)
        App::DocumentObjectExecReturn* again
            = chamferWith(Part::ChamferType::twoDistances, size, size);
        if (again != App::DocumentObject::StdReturn && varying && !setbacksDiffer) {
            delete again;
            return result;
        }
        delete result;
        result = again;
    }
    return result;
}

void Chamfer::Restore(Base::XMLReader& reader)
{
    DressUp::Restore(reader);

    migrateFlippedProperties(reader);
}

void Chamfer::handleChangedPropertyType(Base::XMLReader& reader, const char* TypeName, App::Property* prop)
{
    if (prop && strcmp(TypeName, "App::PropertyFloatConstraint") == 0
        && prop->getTypeId().getName() == "App::PropertyQuantityConstraint") {
        App::PropertyFloatConstraint p;
        p.Restore(reader);
        static_cast<App::PropertyQuantityConstraint*>(prop)->setValue(p.getValue());
    }
    else {
        DressUp::handleChangedPropertyType(reader, TypeName, prop);
    }
}

bool Chamfer::requiresSizeSwapping(const Base::XMLReader& reader) const
{
    return Base::getVersion(reader.ProgramVersion) < Base::Version::v1_0
        && (ChamferType.getValue() == 1 || ChamferType.getValue() == 2);
}

void Chamfer::migrateFlippedProperties(const Base::XMLReader& reader)
{
    if (!requiresSizeSwapping(reader)) {
        return;
    }

    Base::Console().warning(
        "The 'FlipDirection' property of the chamfer of %s is being adjusted to maintain"
        "the same geometry in this FreeCAD version. If the re-saved file is later opened "
        "in FreeCAD 0.21.x the chamfer result may differ due to the changed parameter "
        "interpretation.\n",
        getFullName()
    );

    FlipDirection.setValue(!FlipDirection.getValue());
}

void Chamfer::onChanged(const App::Property* prop)
{
    if (prop == &ChamferType || prop == &WidthAt) {
        updateProperties();
    }

    DressUp::onChanged(prop);
}

void Chamfer::updateProperties()
{
    auto chamferType = ChamferType.getValue();

    auto disableproperty = [](App::Property* prop, bool on) {
        prop->setStatus(App::Property::ReadOnly, on);
    };

    // ops#942: the width rule by equal distances only; its points with "At a reference point"
    disableproperty(&this->WidthAt, chamferType != 0);
    disableproperty(&this->WidthPoints, chamferType != 0 || WidthAt.getValue() != 2);
    switch (chamferType) {
        case 0:  // "Equal distance"
            disableproperty(&this->Angle, true);
            disableproperty(&this->Size2, true);
            break;
        case 1:  // "Two distances"
            disableproperty(&this->Angle, true);
            disableproperty(&this->Size2, false);
            break;
        case 2:  // "Distance and Angle"
            disableproperty(&this->Angle, false);
            disableproperty(&this->Size2, true);
            break;
    }
}

static App::DocumentObjectExecReturn* validateParameters(
    int chamferType,
    double size,
    double size2,
    double angle
)
{
    // Size is common to all chamfer types.
    if (size <= 0) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Size must be greater than zero")
        );
    }

    switch (chamferType) {
        case 0:  // Equal distance
            // Nothing to do.
            break;
        case 1:  // Two distances
            if (size2 <= 0) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Size2 must be greater than zero")
                );
            }
            break;
        case 2:  // Distance and angle
            if (angle <= 0 || angle >= 180.0) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Angle must be greater than 0 and less than 180")
                );
            }
            break;
    }

    return App::DocumentObject::StdReturn;
}
