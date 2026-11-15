// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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

#include <limits>

#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRep_Tool.hxx>
#include <Geom_Circle.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopExp_Explorer.hxx>
#include <ShapeFix_Shape.hxx>

#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Mod/Part/App/FilletFallback.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeRepair.h>

#include "FeatureFillet.h"
#include "ResultCheck.h"


using namespace PartDesign;

namespace PartDesign
{
// FeatureDressUp.cpp (ops#640 F2, Onshape's failure text; declared where used)
PartDesignExport std::string dressUpFailure(const char* verb, const std::string& what);
PartDesignExport bool isDressUpFailure(const std::string& what);
// FeatureDressUp.cpp (FreeCAD-CH ops#654 T3; declared where used)
PartDesignExport bool dressUpReapplying(Part::TopoShape& base, std::vector<Part::TopoShape>& edges);
PartDesignExport void dressUpReapplied(const Part::TopoShape& result);
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


PROPERTY_SOURCE(PartDesign::Fillet, PartDesign::DressUp)

const App::PropertyQuantityConstraint::Constraints floatRadius
    = {0.0, std::numeric_limits<float>::max(), 0.1};

Fillet::Fillet()
{
    ADD_PROPERTY_TYPE(Radius, (1.0), "Fillet", App::Prop_None, "Fillet radius.");
    Radius.setUnit(Base::Unit::Length);
    Radius.setConstraints(&floatRadius);
    ADD_PROPERTY_TYPE(
        UseAllEdges,
        (false),
        "Fillet",
        App::Prop_None,
        "Fillet all edges if true, else use only those edges in Base property.\n"
        "If true, then this overrides any edge changes made to the Base property or in the "
        "dialog.\n"
    );
    ADD_PROPERTY_TYPE(
        TangentPropagation,
        (true),
        "Fillet",
        App::Prop_None,
        "Fillet the whole tangent chain of each picked edge (Onshape's 'Tangent propagation').\n"
        "Off: only the picked edges; where a picked straight edge continues tangentially, the\n"
        "fillet runs straight on until it leaves the body, as Onshape's does."
    );
}

short Fillet::mustExecute() const
{
    if (Placement.isTouched() || Radius.isTouched() || TangentPropagation.isTouched()) {
        return 1;
    }
    return DressUp::mustExecute();
}

App::DocumentObjectExecReturn* Fillet::execute()
{
    // FreeCAD-CH ops#701 (F2b): over several parts, this part failing while the first part's
    // builds is a warning, as Onshape's FILLET_PARTIAL_FAIL
    return partialFailure(build(), "fillet", "Radius");
}

App::DocumentObjectExecReturn* Fillet::build()
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


    Part::TopoShape baseShape;
    try {
        baseShape = reapplying ? reapplyBase : getBaseTopoShape();
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    baseShape.locate(TopLoc_Location());

    auto edges = reapplying            ? reapplyEdges
        : UseAllEdges.getValue() ? baseShape.getSubTopoShapes(TopAbs_EDGE)
                                 : getContinuousEdges(baseShape);
    if (edges.empty()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Fillet not possible on selected shapes")
        );
    }

    double radius = Radius.getValue();

    if (radius <= 0) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Fillet radius must be greater than zero")
        );
    }

    if (!reapplying) {
        this->positionByBaseFeature();
    }

    try {
        TopoShape shape = makeTopoShape();
        // Add signal handler for segfault protection
#if defined(__GNUC__) && defined(FC_OS_LINUX)
        Base::SignalException se;
#endif

        Part::FilletFallback::Recorder recorder;
        // ops#655: with tangent propagation off, an edge whose tangent chain goes on is cut
        // Onshape's way after the others are filleted
        const std::vector<Part::TopoShape> runOut = TangentPropagation.getValue()
            ? std::vector<Part::TopoShape>()
            : takeChainedEdges(baseShape, edges, radius);
        if (edges.empty()) {
            shape = baseShape;
        }
        else {
            shape.makeElementFillet(baseShape, edges, Radius.getValue(), Radius.getValue());
        }
        if (shape.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is null")
            );
        }

        // Limiting every tolerance to Precision::Confusion() used to be the repair: it opened the
        // gaps a fillet closes with larger tolerances, turning valid fillets into invalid solids,
        // and edited sub-shapes shared with the base shape in place (ops#12). The repair works on
        // a copy and keeps the names of the elements it doesn't change (ops#168). A result that is
        // invalid and can't be repaired without changing its solids or its surface fails the
        // feature, as it did up to 0.21, instead of breaking the features after it. The check is
        // the full one: BRepAlgo::IsValid on the new faces passed OCCT's two-solid result of an
        // overlong full round (ops#297).
        // Solids and shells only, as OCCT returns them: a later feature fails on a BaseFeature's
        // loose faces (ops#303)
        if (!Part::checkDressUp(shape, baseShape, Part::LooseParts::drop)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is invalid")
            );
        }
        // OCCT fills a recess its band crosses, in a valid solid (ops#393)
        if (!edges.empty()) {
            ResultCheck::stopIfPastTheLimit("The fillet's check for a filled recess");
        }
        const std::string filled
            = edges.empty() ? std::string() : Part::filledPocket(shape, baseShape, edges, radius);
        if (!filled.empty()) {
            return new App::DocumentObjectExecReturn("The fillet " + filled);
        }
        // OCCT stopping a hair short of a step drops the step's upper part, in a valid solid
        // (ops#603). Not for a round the exact construction rolled on over a tangent edge: it
        // covers its face beyond the band this check allows a direct round, and the construction
        // measured what it cut or fused against the tool's closed form (ops#640, #47 at R1 7, r 4)
        const bool checkLost = !edges.empty() && !recorder.rolledOn();
        if (checkLost) {
            ResultCheck::stopIfPastTheLimit("The fillet's check for lost material");
        }
        const std::string lost
            = checkLost ? Part::lostMaterial(shape, baseShape, edges, radius) : std::string();
        if (!lost.empty()) {
            return new App::DocumentObjectExecReturn("The fillet " + lost);
        }
        // OCCT bridges a hole or pocket the band crosses with a B-spline (ops#604 gap 3a)
        if (!edges.empty()) {
            ResultCheck::stopIfPastTheLimit("The fillet's check for a bridged recess");
        }
        const std::string bridged
            = edges.empty() ? std::string() : Part::bridgedRecess(shape, baseShape, edges, radius);
        if (!bridged.empty()) {
            return new App::DocumentObjectExecReturn("The fillet" + bridged);
        }
        // ops#655: each chained edge's fillet runs straight on until it leaves the body (GB13)
        for (const auto& edge : runOut) {
            const TopoDS_Shape tool = runOutCut(
                shape.getShape(),
                baseShape.getShape(),
                TopoDS::Edge(edge.getShape()),
                radius,
                true
            );
            if (tool.IsNull()) {
                continue;
            }
            TopoShape cut = makeTopoShape();
            cut.makeElementCut({shape, makeTopoShape(tool)});
            shape = cut;
        }
        if (!runOut.empty() && !Part::checkDressUp(shape, baseShape, Part::LooseParts::drop)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is invalid")
            );
        }
        // store shape before refinement
        if (reapplying) {
            dressUpReapplied(refineShapeIfActive(shape));
            return App::DocumentObject::StdReturn;
        }
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
    // ops#640 F2: Onshape's "Failed to fillet selections" with the exact construction's reason,
    // never OCCT's raw text (row 104's "TopOpeBRepDS_DataStructure::Point")
    catch (Base::Exception& e) {
        const std::string what = e.what();
        return new App::DocumentObjectExecReturn(
            isDressUpFailure(what) ? dressUpFailure("fillet", what) : what
        );
    }
    catch (Standard_Failure& e) {
        const char* what = e.GetMessageString();
        return new App::DocumentObjectExecReturn(dressUpFailure("fillet", what ? what : ""));
    }
    catch (...) {
        return new App::DocumentObjectExecReturn(dressUpFailure("fillet", ""));
    }
}

void Fillet::Restore(Base::XMLReader& reader)
{
    DressUp::Restore(reader);
}

void Fillet::handleChangedPropertyType(Base::XMLReader& reader, const char* TypeName, App::Property* prop)
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
