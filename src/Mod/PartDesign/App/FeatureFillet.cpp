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

#include <algorithm>
#include <cmath>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <Geom_Circle.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Pln.hxx>
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
// FeatureDressUp.cpp (FreeCAD-CH ops#654 T3; declared where used)
PartDesignExport bool dressUpReapplying(Part::TopoShape& base, std::vector<Part::TopoShape>& edges);
PartDesignExport void dressUpReapplied(const Part::TopoShape& result);
}  // namespace PartDesign

namespace
{
// ops#655: tangent propagation off, as Onshape's (notes/loft-options.md, oracle fact GB13)

/// Takes out of `edges` the picked edges whose OCCT contour reaches an edge that isn't picked:
/// OCCT would fillet the whole tangent chain there. Returns them.
std::vector<Part::TopoShape> takeChainedEdges(
    const Part::TopoShape& base,
    std::vector<Part::TopoShape>& edges,
    double radius
)
{
    TopTools_IndexedMapOfShape picked;
    for (const auto& edge : edges) {
        picked.Add(edge.getShape());
    }
    std::vector<Part::TopoShape> chained;
    std::vector<Part::TopoShape> kept;
    for (const auto& edge : edges) {
        BRepFilletAPI_MakeFillet maker(base.getShape());
        maker.Add(radius, TopoDS::Edge(edge.getShape()));
        bool reaches = false;
        for (int contour = 1; contour <= maker.NbContours() && !reaches; ++contour) {
            for (int i = 1; i <= maker.NbEdges(contour); ++i) {
                if (!picked.Contains(maker.Edge(contour, i))) {
                    reaches = true;
                    break;
                }
            }
        }
        (reaches ? chained : kept).push_back(edge);
    }
    edges = std::move(kept);
    return chained;
}

[[noreturn]] void notStraightRunOut()
{
    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
        "Exception",
        "Tangent propagation off: a picked edge continues tangentially into an edge that isn't "
        "picked, and only a straight edge between two flat faces with a convex corner can stop "
        "there. Pick the whole tangent chain, or turn tangent propagation on."
    ));
}

/// The corner region a fillet of `radius` removes along a straight convex edge between two planar
/// faces of `base`, extended along the edge past the body both ways, as a prism: Onshape's fillet
/// runs straight on past a tangent vertex (GB13).
TopoDS_Shape runOutTool(const TopoDS_Shape& base, const TopoDS_Edge& edge, double radius)
{
    BRepAdaptor_Curve curve(edge);
    if (curve.GetType() != GeomAbs_Line) {
        notStraightRunOut();
    }
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(base, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    if (!edgeFaces.Contains(edge)) {
        notStraightRunOut();
    }
    TopTools_IndexedMapOfShape faces;
    for (const auto& face : edgeFaces.FindFromKey(edge)) {
        faces.Add(face);
    }
    if (faces.Extent() != 2) {
        notStraightRunOut();
    }
    const gp_Pnt start = BRep_Tool::Pnt(TopExp::FirstVertex(edge));
    const gp_Pnt end = BRep_Tool::Pnt(TopExp::LastVertex(edge));
    const gp_Dir along(gp_Vec(start, end));
    const gp_Pnt middle((start.XYZ() + end.XYZ()) / 2);
    gp_Dir normal[2];
    gp_Dir into[2];
    for (int k = 0; k < 2; ++k) {
        const TopoDS_Face& face = TopoDS::Face(faces(k + 1));
        BRepAdaptor_Surface surface(face);
        if (surface.GetType() != GeomAbs_Plane) {
            notStraightRunOut();
        }
        normal[k] = surface.Plane().Axis().Direction();
        if (face.Orientation() == TopAbs_REVERSED) {
            normal[k].Reverse();
        }
        // across the edge, into the face
        into[k] = along.Crossed(normal[k]);
        const double probe = std::min(1e-3 * radius, 1e-3 * start.Distance(end));
        BRepClass_FaceClassifier inside(face, middle.Translated(gp_Vec(into[k]) * probe), 1e-9);
        if (inside.State() != TopAbs_IN) {
            into[k].Reverse();
        }
    }
    // convex: each face runs away below the other's plane
    if (into[0].Dot(normal[1]) > -1e-9 || into[1].Dot(normal[0]) > -1e-9) {
        notStraightRunOut();
    }
    // the ball's centre is r inside both planes
    const double c = normal[0].Dot(normal[1]);
    const gp_Vec toCentre = (gp_Vec(normal[0]) + gp_Vec(normal[1])) * (-radius / (1.0 + c));

    Bnd_Box box;
    BRepBndLib::Add(base, box);
    const double past = std::sqrt(box.SquareExtent()) + radius;
    const gp_Pnt corner = start.Translated(gp_Vec(along) * -past);
    const gp_Pnt centre = corner.Translated(toCentre);
    const gp_Pnt tangent0 = centre.Translated(gp_Vec(normal[0]) * radius);
    const gp_Pnt tangent1 = centre.Translated(gp_Vec(normal[1]) * radius);
    const gp_Pnt arcMiddle = centre.Translated(gp_Vec(centre, corner).Normalized() * radius);
    Handle(Geom_TrimmedCurve) arc = GC_MakeArcOfCircle(tangent0, arcMiddle, tangent1).Value();
    BRepBuilderAPI_MakeWire wire(
        BRepBuilderAPI_MakeEdge(corner, tangent0).Edge(),
        BRepBuilderAPI_MakeEdge(arc).Edge(),
        BRepBuilderAPI_MakeEdge(tangent1, corner).Edge()
    );
    BRepBuilderAPI_MakeFace section(wire.Wire(), true);
    return BRepPrimAPI_MakePrism(section.Face(), gp_Vec(along) * (start.Distance(end) + 2 * past))
        .Shape();
}

/// The overlap of `shape` and the run-out tool of `edge` that touches `edge`: the fillet runs on
/// until it leaves the body, and doesn't reach a part of the body the tool's line enters again.
TopoDS_Shape runOutCut(const TopoDS_Shape& shape, const TopoDS_Shape& base, const TopoDS_Edge& edge, double radius)
{
    BRepAlgoAPI_Common common(shape, runOutTool(base, edge, radius));
    if (!common.IsDone()) {
        notStraightRunOut();
    }
    BRep_Builder builder;
    TopoDS_Compound touching;
    builder.MakeCompound(touching);
    int count = 0;
    for (TopExp_Explorer solid(common.Shape(), TopAbs_SOLID); solid.More(); solid.Next()) {
        BRepExtrema_DistShapeShape distance(solid.Current(), edge);
        if (distance.IsDone() && distance.Value() < 1e-6) {
            builder.Add(touching, solid.Current());
            ++count;
        }
    }
    return count ? TopoDS_Shape(touching) : TopoDS_Shape();
}
}  // namespace


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
    // FreeCAD-CH ops#654 T3: re-run at a pattern's instance, on its base and edges
    Part::TopoShape reapplyBase;
    std::vector<Part::TopoShape> reapplyEdges;
    const bool reapplying = dressUpReapplying(reapplyBase, reapplyEdges);
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
        const std::string filled
            = edges.empty() || ResultCheck::skippedForTheLimit(this, "The fillet's check for a filled recess")
            ? std::string()
            : Part::filledPocket(shape, baseShape, edges);
        if (!filled.empty()) {
            return new App::DocumentObjectExecReturn("The fillet " + filled);
        }
        // OCCT stopping a hair short of a step drops the step's upper part, in a valid solid
        // (ops#603)
        const std::string lost
            = edges.empty() || ResultCheck::skippedForTheLimit(this, "The fillet's check for lost material")
            ? std::string()
            : Part::lostMaterial(shape, baseShape, edges, radius);
        if (!lost.empty()) {
            return new App::DocumentObjectExecReturn("The fillet " + lost);
        }
        // OCCT bridges a hole or pocket the band crosses with a B-spline (ops#604 gap 3a)
        const std::string bridged
            = edges.empty() || ResultCheck::skippedForTheLimit(this, "The fillet's check for a bridged recess")
            ? std::string()
            : Part::bridgedRecess(shape, baseShape, edges, radius);
        if (!bridged.empty()) {
            return new App::DocumentObjectExecReturn("The fillet" + bridged);
        }
        // ops#655: each chained edge's fillet runs straight on until it leaves the body (GB13)
        for (const auto& edge : runOut) {
            const TopoDS_Shape tool = runOutCut(
                shape.getShape(),
                baseShape.getShape(),
                TopoDS::Edge(edge.getShape()),
                radius
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
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
    catch (...) {
        return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
            "Exception",
            "Fillet operation failed. The selected edges may contain geometry that cannot be "
            "filleted together. "
            "Try filleting edges individually or with a smaller radius."
        ));
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
