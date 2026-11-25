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

#include <ChFi3d.hxx>
#include <algorithm>
#include <cmath>
#include <limits>

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
#include <BRepLProp_CLProps.hxx>
#include <BRepLProp_SLProps.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepGProp.hxx>
#include <ElCLib.hxx>
#include <GProp_GProps.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <Geom2d_Curve.hxx>
#include <IntCurvesFace_ShapeIntersector.hxx>
#include <gp_Circ.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Lin.hxx>
#include <TopTools_MapOfShape.hxx>
#include <gp_Torus.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <Bnd_Box.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <Geom_TrimmedCurve.hxx>
#include <gp_Trsf.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Vertex.hxx>
#include <Precision.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt2d.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopExp_Explorer.hxx>

#include <cstdio>
#include <cstring>
#include <array>
#include <utility>
#include <vector>
#include <map>
#include <memory>
#include <regex>
#include <string>

#include <boost/algorithm/string/predicate.hpp>

#include "FeatureDressUp.h"
#include "PartDesignParameter.h"
#include <Base/Console.h>
#include <App/Document.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <App/ElementNamingUtils.h>
#include <Base/Exception.h>
#include <Base/Writer.h>
#include "Mod/Part/App/FilletFallback.h"
#include "Mod/Part/App/TopoShapeMapper.h"
#include "Mod/Part/App/TopoShapeOpCode.h"
#include "Body.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesign;

namespace PartDesign
{

// ops#1005: the picks as getContinuousEdges lists them, and those it skips as not C0
PartDesignExport std::vector<TopoShape> pickedEdges(
    DressUp& step,
    const TopoShape& shape,
    std::vector<TopoShape>* notC0
);

PROPERTY_SOURCE(PartDesign::DressUp, PartDesign::FeatureAddSub)

DressUp::DressUp()
{
    ADD_PROPERTY(Base, (nullptr));
    // The reference solver (ops#7): a dress-up takes every piece of a split element (Task 2
    // PR 7; read as One until then).
    Base.setElementPolicy(App::PropertyLinkBase::ElementPolicy::Expand);
    // and computes on the elements that resolve when some are gone, with a warning (ops#127,
    // Onshape's rule)
    Base.setPartialAllowed(true);
    if (PartDesignParameter::instance()->getNamingMultiMatch()) {
        Base.useMultipleMatchedNames(true);
        Base.allowDuplicateLinks(false);
    }

    Placement.setStatus(App::Property::ReadOnly, true);

    ADD_PROPERTY_TYPE(
        SupportTransform,
        (false),
        "Base",
        App::Prop_None,
        "Include the base additive/subtractive shape when used in pattern features.\n"
        "If disabled, only the dressed part of the shape is used for patterning."
    );

    // FreeCAD-CH ops#654 (P8a, parts-design.md 10.14): a studio dress-up's picks. StudioPicks is
    // unused (the skeptic's point 7): removing it changes this class's header, left for a build
    // that rebuilds PartDesign anyway
    ADD_PROPERTY_TYPE(StudioPicks, (nullptr), "Studio", App::Prop_Hidden, "Unused (ops#654 P8a)");
    ADD_PROPERTY_TYPE(
        StudioPickIds,
        (),
        "Studio",
        App::Prop_Hidden,
        "A studio dress-up's picks: '<part id>|<element name>', the name interned (ops#640 C1)"
    );
    // FreeCAD-CH ops#701 (F2b): the dress-up of the first part, for one over several parts
    ADD_PROPERTY_TYPE(
        MultiPartPrimary,
        (nullptr),
        "Studio",
        App::Prop_Hidden,
        "The dress-up this one was made with in another part: when it builds and this one fails, "
        "this one passes its part through with a warning"
    );

    AddSubShape.setStatus(App::Property::Output, true);
    Operation.setStatus(App::Property::Hidden, true);
}

short DressUp::mustExecute() const
{
    if (Base.getValue() && Base.getValue()->isTouched()) {
        return 1;
    }
    return PartDesign::FeatureAddSub::mustExecute();
}

void DressUp::positionByBaseFeature()
{
    Part::Feature* base = static_cast<Part::Feature*>(BaseFeature.getValue());
    if (base && base->isDerivedFrom<Part::Feature>()) {
        this->Placement.setValue(base->Placement.getValue());
    }
}

Part::Feature* DressUp::getBaseObject(bool silent) const
{
    Part::Feature* rv = Feature::getBaseObject(/* silent = */ true);
    if (rv) {
        return rv;
    }

    const char* err = nullptr;
    App::DocumentObject* base = Base.getValue();
    if (base) {
        if (base->isDerivedFrom<Part::Feature>()) {
            rv = static_cast<Part::Feature*>(base);
        }
        else {
            err = "Linked object is not a Part object";
        }
    }
    else {
        err = "No Base object linked";
    }

    if (!silent && err) {
        throw Base::RuntimeError(err);
    }

    return rv;
}

void DressUp::getContinuousEdges(Part::TopoShape TopShape, std::vector<std::string>& SubNames)
{

    std::vector<std::string> FaceNames;

    getContinuousEdges(TopShape, SubNames, FaceNames);
}

void DressUp::getContinuousEdges(
    Part::TopoShape TopShape,
    std::vector<std::string>& SubNames,
    std::vector<std::string>& FaceNames
)
{

    TopTools_IndexedMapOfShape mapOfEdges;
    TopTools_IndexedDataMapOfShapeListOfShape mapEdgeFace;
    TopExp::MapShapesAndAncestors(TopShape.getShape(), TopAbs_EDGE, TopAbs_FACE, mapEdgeFace);
    TopExp::MapShapes(TopShape.getShape(), TopAbs_EDGE, mapOfEdges);

    unsigned int i = 0;
    while (i < SubNames.size()) {
        std::string aSubName = static_cast<std::string>(SubNames.at(i));

        if (aSubName.compare(0, 4, "Edge") == 0) {
            TopoDS_Edge edge = TopoDS::Edge(TopShape.getSubShape(aSubName.c_str()));
            const TopTools_ListOfShape& los = mapEdgeFace.FindFromKey(edge);

            if (los.Extent() != 2) {
                SubNames.erase(SubNames.begin() + i);
                continue;
            }

            const TopoDS_Shape& face1 = los.First();
            const TopoDS_Shape& face2 = los.Last();
            GeomAbs_Shape cont
                = BRep_Tool::Continuity(TopoDS::Edge(edge), TopoDS::Face(face1), TopoDS::Face(face2));
            if (cont != GeomAbs_C0) {
                SubNames.erase(SubNames.begin() + i);
                continue;
            }

            i++;
        }
        else if (aSubName.compare(0, 4, "Face") == 0) {
            TopoDS_Face face = TopoDS::Face(TopShape.getSubShape(aSubName.c_str()));

            TopTools_IndexedMapOfShape mapOfFaces;
            TopExp::MapShapes(face, TopAbs_EDGE, mapOfFaces);

            for (int j = 1; j <= mapOfFaces.Extent(); ++j) {
                TopoDS_Edge edge = TopoDS::Edge(mapOfFaces.FindKey(j));

                int id = mapOfEdges.FindIndex(edge);

                std::stringstream buf;
                buf << "Edge";
                buf << id;

                if (std::ranges::find(SubNames, buf.str()) == SubNames.end()) {
                    SubNames.push_back(buf.str());
                }
            }

            FaceNames.emplace_back(aSubName.c_str());
            SubNames.erase(SubNames.begin() + i);
        }
        // empty name or any other sub-element
        else {
            SubNames.erase(SubNames.begin() + i);
        }
    }
}

std::vector<TopoShape> DressUp::getContinuousEdges(const TopoShape& shape)
{
    return pickedEdges(*this, shape, nullptr);
}

/// The picked edges as getContinuousEdges lists them; @a notC0, when given, receives the picks it
/// skips because their faces are stored as meeting with more than C0 continuity (ops#1005).
/// Declared where used
PartDesignExport std::vector<TopoShape> pickedEdges(
    DressUp& step,
    const TopoShape& shape,
    std::vector<TopoShape>* notC0
)
{
    DressUp* self = &step;
    auto getFullName = [self]() {
        return self->getFullName();
    };
    auto& Base = step.Base;
    std::vector<TopoShape> ret;
    std::unordered_set<TopoDS_Shape, Part::ShapeHasher, Part::ShapeHasher> shapeSet;

    auto addEdge = [&](const TopoDS_Shape& subshape, const std::string& ref) {
        if (!shapeSet.insert(subshape).second) {
            return;
        }

        auto faces = shape.findAncestorsShapes(subshape, TopAbs_FACE);
        if (faces.size() != 2) {
            FC_WARN(getFullName() << ": skip edge " << ref << " with less two attaching faces");
            return;
        }
        const TopoDS_Shape& face1 = faces.front();
        const TopoDS_Shape& face2 = faces.back();
        GeomAbs_Shape cont
            = BRep_Tool::Continuity(TopoDS::Edge(subshape), TopoDS::Face(face1), TopoDS::Face(face2));
        if (cont != GeomAbs_C0) {
            // A developer's line: log level (decision 100)
            FC_LOG(getFullName() << ": skip edge " << ref << " that is not C0 continuous");
            if (notC0) {
                notC0->push_back(subshape);
            }
            return;
        }
        ret.push_back(subshape);
    };

    // In a reference solver document the edges that are gone are skipped: the feature computes
    // on the rest, and the recompute check has warned of them (ops#127).
    const bool partial = Base.isPartialAllowed() && Base.inSolverDocument();
    for (const auto& v : Base.getShadowSubs()) {
        if (partial && Data::hasMissingElement(v.oldName.c_str())) {
            continue;
        }
        TopoDS_Shape subshape;
        const auto& ref = v.newName.size() ? v.newName : v.oldName;
        subshape = shape.getSubShape(ref.c_str(), true);
        if (subshape.IsNull()) {
            FC_THROWM(Base::CADKernelError, "Invalid edge link: " << ref);
        }

        if (subshape.ShapeType() == TopAbs_EDGE) {
            addEdge(subshape, ref);
        }
        else if (subshape.ShapeType() == TopAbs_FACE || subshape.ShapeType() == TopAbs_WIRE) {
            for (TopExp_Explorer exp(subshape, TopAbs_EDGE); exp.More(); exp.Next()) {
                addEdge(exp.Current(), std::string());
            }
        }
        else {
            FC_WARN(
                getFullName() << ": skip invalid shape '" << ref << "' with type "
                              << TopoShape::shapeName(subshape.ShapeType())
            );
        }
    }
    return ret;
}

namespace
{
/// ops#1005: Onshape's limit for a smooth edge lies between 0.10 and 0.11 degrees (RB15), an
/// angle whatever the size (RB28)
constexpr double nearSmoothTurn = 0.105 * 3.14159265358979323846 / 180.0;
/// Two planes meeting closer than this to tangent are one plane: Onshape merges them at 1e-6
/// degrees and keeps a bent edge at 1e-5 degrees (1.7e-7 rad), which its chamfer never drops
/// (RB28). A plane's normal is exact, so no measuring noise comes near it
constexpr double planesTangentTurn = 1e-7;

/// A plane, cylinder, cone, sphere or torus
bool analytic(const TopoDS_Face& face)
{
    switch (BRepAdaptor_Surface(face, Standard_False).GetType()) {
        case GeomAbs_Plane:
        case GeomAbs_Cylinder:
        case GeomAbs_Cone:
        case GeomAbs_Sphere:
        case GeomAbs_Torus:
            return true;
        default:
            return false;
    }
}

/** How far an edge's two faces turn from meeting tangent along it: the largest angle, at nine
 * points ends included, between their directions into themselves and opposite ones; -1 where it
 * can't be told (not two faces, a seam, a degenerate normal or tangent) or isn't known along the
 * whole edge. Samples bound the turn only where it can't change between them: a line or circle
 * between analytic faces (their symmetry keeps the turn the same all along), or an edge stored as
 * smooth (@a storedSmooth: its modeler made its faces tangent along it). Any other edge may turn
 * between the samples (review pr1005-r1: a bend tangent at the samples and turning 20 degrees
 * between them) and is an ordinary pick, as before. An edge tangent at single points only (two
 * equal cylinders crossing) is no smooth edge either (RB28). @a planes: both faces are planes
 */
double smoothTurn(const TopoShape& shape, const TopoDS_Edge& edge, bool storedSmooth, bool& planes)
{
    planes = false;
    const auto faces = shape.findAncestorsShapes(edge, TopAbs_FACE);
    if (faces.size() != 2 || BRep_Tool::Degenerated(edge)) {
        return -1.0;
    }
    planes = BRepAdaptor_Surface(TopoDS::Face(faces[0])).GetType() == GeomAbs_Plane
        && BRepAdaptor_Surface(TopoDS::Face(faces[1])).GetType() == GeomAbs_Plane;
    BRepAdaptor_Curve curve(edge);
    const bool constant = (curve.GetType() == GeomAbs_Line || curve.GetType() == GeomAbs_Circle)
        && analytic(TopoDS::Face(faces[0])) && analytic(TopoDS::Face(faces[1]));
    if (!constant && !storedSmooth) {
        return -1.0;
    }
    double worst = 0.0;
    for (int k = 0; k < 9; ++k) {
        const double t = curve.FirstParameter()
            + (curve.LastParameter() - curve.FirstParameter()) * k / 8;
        gp_Pnt point;
        gp_Vec tangent;
        curve.D1(t, point, tangent);
        if (tangent.Magnitude() < Precision::Confusion()) {
            return -1.0;
        }
        std::array<gp_Vec, 2> inward;
        for (int i = 0; i < 2; ++i) {
            const TopoDS_Face face = TopoDS::Face(faces[i]);
            // The edge's orientation in the face, composed with the face's own (as the exact
            // construction's inwardIn): the face's material lies to the left of it
            int forward = 0;
            int reversed = 0;
            for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
                if (it.Current().IsSame(edge)) {
                    if (it.Current().Orientation() == TopAbs_REVERSED) {
                        ++reversed;
                    }
                    else {
                        ++forward;
                    }
                }
            }
            if ((forward == 0) == (reversed == 0)) {
                return -1.0;
            }
            double u = 0.0;
            double v = 0.0;
            double first = 0.0;
            double last = 0.0;
            const Handle(Geom2d_Curve) onFace = BRep_Tool::CurveOnSurface(edge, face, first, last);
            if (!onFace.IsNull()) {
                const gp_Pnt2d uv = onFace->Value(t);
                u = uv.X();
                v = uv.Y();
            }
            else {
                GeomAPI_ProjectPointOnSurf projection(point, BRep_Tool::Surface(face));
                if (projection.NbPoints() == 0) {
                    return -1.0;
                }
                projection.LowerDistanceParameters(u, v);
            }
            BRepAdaptor_Surface surface(face, Standard_False);
            BRepLProp_SLProps props(surface, u, v, 1, Precision::Confusion());
            if (!props.IsNormalDefined()) {
                return -1.0;
            }
            gp_Vec normal(props.Normal());
            if (face.Orientation() == TopAbs_REVERSED) {
                normal.Reverse();
            }
            inward[i] = normal.Crossed(reversed > 0 ? tangent.Reversed() : tangent);
            if (inward[i].Magnitude() < Precision::Confusion()) {
                return -1.0;
            }
        }
        worst = std::max(worst, 3.14159265358979323846 - inward[0].Angle(inward[1]));
    }
    return worst;
}
}  // namespace

/** Onshape's rule for smooth picks in a fillet or chamfer (ops#1005; notes/onshape-facts.md SE1,
 * SE2, RB15, RB28). An edge is smooth where its faces meet within 0.105 degrees of tangent along
 * it. A selection of smooth edges only is refused (FILLET_FAIL_SMOOTH, CHAMFER_FAIL_SMOOTH). A
 * chamfer holding a bent edge between two planes (turning by 1.7e-7 rad and more) and any other
 * edge fails (CHAMFER_FACE_RANGE_TOO_LARGE, RB15, RB28). Otherwise the smooth edges are taken out
 * of @a edges: Onshape drops a tangent line, and a near-smooth edge beside a curved face, silently
 * (SE2, RB28); its fillet rounds a near-smooth edge between planes with a sliver face of width
 * r d and next to no volume (r^2 d^3 / 24 per length), left out here. Without them neither OCCT
 * nor the exact construction sees them: OCCT skips them itself, but the construction, asked when
 * OCCT fails on another edge, refused the whole selection for one smooth edge. @a notC0 are the
 * picks pickedEdges skipped as stored smooth (a prism's edges within 0.1 degrees of tangent are).
 * Returns the error, or empty. Declared where used.
 */
PartDesignExport std::string smoothEdgeRule(
    const DressUp* step,
    const TopoShape& shape,
    std::vector<TopoShape>& edges,
    const std::vector<TopoShape>& notC0,
    bool chamfer
)
{
    if (edges.empty() && notC0.empty()) {
        return {};
    }
    std::vector<double> turns;
    turns.reserve(edges.size());
    std::size_t smooth = 0;
    std::size_t bentPlanes = 0;
    auto count = [&](double turn, bool planes) {
        if (turn >= 0.0 && turn <= nearSmoothTurn) {
            ++smooth;
            if (planes && turn > planesTangentTurn) {
                ++bentPlanes;
            }
        }
    };
    for (const auto& edge : edges) {
        bool planes = false;
        turns.push_back(smoothTurn(shape, TopoDS::Edge(edge.getShape()), false, planes));
        count(turns.back(), planes);
    }
    for (const auto& edge : notC0) {
        // Stored as smooth: tangent where it can't be measured
        // Measured before planes is read: a call's arguments are evaluated in no set order
        bool planes = false;
        const double turn = smoothTurn(shape, TopoDS::Edge(edge.getShape()), true, planes);
        count(std::max(0.0, turn), planes);
    }
    const std::size_t total = edges.size() + notC0.size();
    const std::string what = chamfer ? "Chamfer" : "Fillet";
    if (smooth == total) {
        return what
            + " not possible: every picked edge is smooth, its two faces meeting tangent along it "
              "or within 0.1 degree of it (as in Onshape). Pick an edge where the faces meet at "
              "an angle";
    }
    if (chamfer && bentPlanes > 0) {
        return "Chamfer not possible: a picked edge is nearly smooth, two planes meeting within "
               "0.1 degree of each other, and Onshape fails a chamfer holding such an edge with "
               "others. Take that edge out of the selection";
    }
    std::vector<TopoShape> kept;
    kept.reserve(edges.size());
    for (std::size_t i = 0; i < edges.size(); ++i) {
        if (turns[i] >= 0.0 && turns[i] <= nearSmoothTurn) {
            // A developer's line: log level (decision 100)
            FC_LOG(step->getFullName() << ": drop smooth edge, turn " << turns[i] << " rad");
            continue;
        }
        kept.push_back(edges[i]);
    }
    edges = std::move(kept);
    return {};
}

std::vector<TopoShape> DressUp::getFaces(const TopoShape& shape)
{
    std::vector<TopoShape> ret;
    const auto& vals = Base.getSubValues();
    const auto& subs = Base.getShadowSubs();
    // The shadows are listed in the same order as the sub-names, one each. The shadow's old name
    // is the indexed name ("Face3"), also for a sub stored as a mapped name.
    auto indexedName = [&](std::size_t i) -> const std::string& {
        return i < subs.size() && !subs[i].oldName.empty() ? subs[i].oldName : vals[i];
    };

    // A face that no longer exists is stored as "?Face3" (Data::MISSING_PREFIX), which the type
    // test below doesn't take for a face. The feature must fail then, not carry on without it
    // (ops#60). A missing element of another type is skipped, as the element itself would be.
    std::string missing;
    for (std::size_t i = 0; i < vals.size(); ++i) {
        const std::string& name = indexedName(i);
        if (!Data::hasMissingElement(name.c_str()) && !Data::hasMissingElement(vals[i].c_str())) {
            continue;
        }
        std::string element = name.substr(name.rfind('.') + 1);  // npos + 1 == 0
        if (boost::starts_with(element, Data::MISSING_PREFIX)) {
            element.erase(0, std::strlen(Data::MISSING_PREFIX));
        }
        if (boost::starts_with(element, "Face")) {
            missing += (missing.empty() ? "" : ", ") + element;
        }
    }
    // In a reference solver document the feature computes on the faces that resolve, with a
    // warning from the recompute check (ops#127, Onshape's rule); never on none.
    bool anyResolving = false;
    for (std::size_t i = 0; i < vals.size(); ++i) {
        const std::string& name = indexedName(i);
        anyResolving = anyResolving
            || (boost::starts_with(name, "Face") && !Data::hasMissingElement(name.c_str())
                && !Data::hasMissingElement(vals[i].c_str()));
    }
    if (!missing.empty()
        && !(anyResolving && Base.isPartialAllowed() && Base.inSolverDocument())) {
        FC_THROWM(Part::NullShapeException, "Missing face reference: " << missing);
    }

    for (std::size_t i = 0; i < vals.size(); ++i) {
        const std::string& name = indexedName(i);
        if (!boost::starts_with(name, "Face")) {
            continue;
        }
        // the shadow of this sub-name, not of the i-th face (ops#65)
        const std::string& ref = i < subs.size() && !subs[i].newName.empty() ? subs[i].newName
                                                                              : vals[i];
        TopoShape subshape = makeTopoShape(false);
        try {
            subshape = shape.getSubTopoShape(ref.c_str());
        }
        catch (...) {
        }

        if (subshape.isNull()) {
            FC_ERR(getFullName() << ": invalid face reference '" << ref << "'");
            FC_THROWM(Part::NullShapeException, "Invalid face reference: " << name);
        }

        if (subshape.shapeType() != TopAbs_FACE) {
            FC_WARN(
                getFullName() << ": skip invalid shape '" << ref << "' with type "
                              << subshape.shapeName()
            );
            continue;
        }
        ret.push_back(subshape);
    }
    return ret;
}

void DressUp::onBeforeChange(const App::Property* prop)
{
    if (prop == &Base) {
        baseBeforeChange = Base.getValue();
        baseChanging = true;
    }

    FeatureAddSub::onBeforeChange(prop);
}

void DressUp::onChanged(const App::Property* prop)
{
    if (prop == &Base) {
        // BaseFeature follows Base when Base is linked to another object. A change that keeps the
        // object (the naming refresh after an upstream edit, references added or removed) leaves
        // BaseFeature alone: after Body::insertObject it is the inserted feature, and Base still
        // names the feature before it (ops#82). Restoring and undo/redo set both properties.
        bool sameObject = baseChanging && Base.getValue() == baseBeforeChange;
        baseChanging = false;
        baseBeforeChange = nullptr;
        if (!sameObject && BaseFeature.getValue() && Base.getValue() != BaseFeature.getValue()
            && !getDocument()->testStatus(App::Document::Restoring)
            && !getDocument()->isPerformingTransaction()) {
            BaseFeature.setValue(Base.getValue());
        }
    }
    else if (prop == &Shape || prop == &SupportTransform) {
        if (!getDocument()->testStatus(App::Document::Restoring)
            && !getDocument()->isPerformingTransaction()) {
            // AddSubShape acts as a shape cache; invalidate so Transformed
            // can rebuild it lazily via getAddSubShape().
            AddSubShape.setValue(Part::TopoShape());
        }
    }
    else if (prop == &_PassedThrough) {
        // FreeCAD-CH ops#701 (F2c): a follower's state reads whether this one built
        // (partialFailure()). Its only dependency is its size expression, which a suppression
        // doesn't touch, and the recompute enforces only the readers of a changed property.
        // Undo too: it puts back the follower's properties, not its Error state
        if (!getDocument()->testStatus(App::Document::Restoring)) {
            for (auto in : getInList()) {
                auto follower = freecad_cast<DressUp*>(in);
                if (follower && follower != this && follower->MultiPartPrimary.getValue() == this) {
                    follower->enforceRecompute();
                }
            }
        }
    }

    Feature::onChanged(prop);
}

void DressUp::onBaseFeatureRerouted(
    App::DocumentObject* oldBase,
    App::DocumentObject* newBase,
    bool reorder
)
{
    relinkToMatchingSubelements(Base, oldBase, newBase, reorder);
}

void DressUp::getAddSubShape(Part::TopoShape& addShape, Part::TopoShape& subShape)
{
    Part::TopoShape res = AddSubShape.getShape();

    if (res.isNull()) {
        try {
            std::vector<Part::TopoShape> shapes;
            Part::TopoShape shape = Shape.getShape();
            shape.setPlacement(Base::Placement());

            FeatureAddSub* base = nullptr;
            if (SupportTransform.getValue()) {
                // SupportTransform means transform the support together with
                // the dressing. So we need to find the previous support
                // feature (which must be of type FeatureAddSub), and skipping
                // any consecutive DressUp in-between.
                for (Feature* current = this;; current = static_cast<DressUp*>(base)) {
                    base = freecad_cast<FeatureAddSub*>(current->getBaseObject(true));
                    if (!base) {
                        FC_THROWM(
                            Base::CADKernelError,
                            "Cannot find additive or subtractive support for " << getFullName()
                        );
                    }
                    if (!base->isDerivedFrom<DressUp>()) {
                        break;
                    }
                }
            }

            Part::TopoShape baseShape;
            if (base) {
                baseShape = base->getBaseTopoShape(true);
                baseShape.move(base->getInverseLocation(baseShape));
                if (base->getAddSubType() == Type::Additive) {
                    if (!baseShape.isNull() && baseShape.hasSubShape(TopAbs_SOLID)) {
                        shapes.emplace_back(shape.makeElementCut(baseShape.getShape()));
                    }
                    else {
                        shapes.push_back(shape);
                    }
                }
                else {
                    BRep_Builder builder;
                    TopoDS_Compound comp;
                    builder.MakeCompound(comp);
                    // push an empty compound to indicate null additive shape
                    shapes.emplace_back(comp);
                    if (!baseShape.isNull() && baseShape.hasSubShape(TopAbs_SOLID)) {
                        shapes.emplace_back(baseShape.makeElementCut(shape.getShape()));
                    }
                    else {
                        shapes.push_back(shape);
                    }
                }
            }
            else {
                baseShape = getBaseTopoShape();
                baseShape.move(getInverseLocation(baseShape));
                shapes.emplace_back(shape.makeElementCut(baseShape.getShape()));
                shapes.emplace_back(baseShape.makeElementCut(shape.getShape()));
            }

            // Make a compound to contain both additive and subtractive shape,
            // bceause a dressing (e.g. a fillet) can either be additive or
            // subtractive. And the dressup feature can contain mixture of both.
            AddSubShape.setValue(makeTopoShape(false).makeElementCompound(shapes));
        }
        catch (Standard_Failure& e) {
            FC_THROWM(
                Base::CADKernelError,
                "Failed to calculate AddSub shape: " << e.GetMessageString()
            );
        }
        res = AddSubShape.getShape();
    }

    if (res.isNull()) {
        throw Part::NullShapeException("Null AddSub shape");
    }

    if (res.getShape().ShapeType() != TopAbs_COMPOUND) {
        addShape = res;
    }
    else {
        int count = res.countSubShapes(TopAbs_SHAPE);
        if (!count) {
            throw Part::NullShapeException("Null AddSub shape");
        }
        if (count) {
            Part::TopoShape s = res.getSubTopoShape(TopAbs_SHAPE, 1);
            if (!s.isNull() && s.hasSubShape(TopAbs_SOLID)) {
                addShape = s;
            }
        }
        if (count > 1) {
            Part::TopoShape s = res.getSubTopoShape(TopAbs_SHAPE, 2);
            if (!s.isNull() && s.hasSubShape(TopAbs_SOLID)) {
                subShape = s;
            }
        }
    }
}

void DressUp::updatePreviewShape()
{
    auto shape = Shape.getShape();
    auto baseFeature = freecad_cast<Feature*>(BaseFeature.getValue());

    if (!baseFeature || baseFeature->Shape.getShape().isNull()) {
        PreviewShape.setValue(Shape.getShape());
        return;
    }

    std::vector<int> faces, edges, vertices;
    getGeneratedShapes(faces, edges, vertices);

    if (faces.empty()) {
        PreviewShape.setValue(TopoDS_Shape());
        return;
    }

    shape.setPlacement(Base::Placement());

    BRep_Builder builder;
    TopoDS_Compound comp;
    builder.MakeCompound(comp);

    for (int faceId : faces) {
        builder.Add(comp, shape.getSubShape(TopAbs_FACE, faceId));
    }

    Part::TopoShape preview = makeTopoShape(comp);
    preview.mapSubElement(shape);

    PreviewShape.setValue(preview);
}

}  // namespace PartDesign

// FreeCAD-CH ops#654 T3 (notes/patterns-design.md 3.3): a chamfer or fillet re-run at a pattern's
// instance, on the instance's base and edges; nothing of the feature is written
namespace
{
struct DressUpRun
{
    Part::TopoShape base;
    std::vector<Part::TopoShape> edges;
    Part::TopoShape result;
    // ops#796: the shape before the refine, when the run's caller asked for it and the run is
    // one the feature's own compute would repeat as it is
    bool keep = false;
    bool kept = false;
    Part::TopoShape raw;
    // ops#951: the run's note that a merged full round's face is named by the edge order (the
    // step's own compute takes the kept shape and runs no finish(): the owner says it)
    std::string namingNote;
    // ops#942: a pattern's instance, the move from the seed's base to it (null for a studio step)
    const gp_Trsf* move = nullptr;
};
thread_local DressUpRun* dressUpRun = nullptr;
// ops#942: the move the next reapplyDressUp() runs with (setDressUpReapplyMove)
thread_local const gp_Trsf* nextReapplyMove = nullptr;

/// ops#796: what a studio dress-up owner's try built at a step (studioDressUpOwnerRun), for the
/// step's own compute, which follows in the same recompute on the same base and edges: the
/// second build of the same fillet was an eighth of a mid-history edit. By the step's address
/// and id (an id is never used twice in a document)
struct KeptDressUp
{
    long step = 0;
    const App::DocumentObject* owner = nullptr;
    TopoDS_Shape base;
    std::vector<TopoDS_Shape> edges;
    // The step's parameters it was built with (the owner's then): a step computed alone after
    // its owner's values changed builds for itself (review r1 F2)
    std::vector<std::pair<std::string, std::string>> parameters;  ///< name, saved value
    Part::TopoShape raw;
};
// Per thread, as dressUpRun: the try and the take are one recompute's (review r2)
thread_local std::map<const App::DocumentObject*, KeptDressUp> keptDressUps;

/// A property's value as it is saved (a copy's type can differ from its original's)
std::string savedValue(const App::Property* prop)
{
    // A number in full: the writer's stream keeps six digits (review r2)
    if (auto number = freecad_cast<const App::PropertyFloat*>(prop)) {
        char text[40];
        std::snprintf(text, sizeof(text), "%.17g", number->getValue());
        return text;
    }
    Base::StringWriter writer;
    prop->Save(writer);
    return writer.getString();
}
}  // namespace

namespace PartDesign
{

PartDesignExport bool dressUpReapplying(Part::TopoShape& base, std::vector<Part::TopoShape>& edges)
{
    if (!dressUpRun) {
        return false;
    }
    base = dressUpRun->base;
    edges = dressUpRun->edges;
    return true;
}

/// ops#942: a pattern sets the move from the seed's base to its instance for the next
/// reapplyDressUp(), so that a chamfer's WidthPoints are moved with its edges
PartDesignExport void setDressUpReapplyMove(const gp_Trsf* move)
{
    nextReapplyMove = move;
}

/// ops#942: the run's move from the seed's base to the pattern's instance; false where the run
/// is not a pattern's (a studio step's, whose part has a frame of its own)
PartDesignExport bool dressUpReapplyMove(gp_Trsf& move)
{
    if (!dressUpRun || !dressUpRun->move) {
        return false;
    }
    move = *dressUpRun->move;
    return true;
}

PartDesignExport void dressUpReapplied(const Part::TopoShape& result)
{
    if (dressUpRun) {
        dressUpRun->result = result;
    }
}

/// The owner a step is tried for, when the try's result may be kept (ops#796): the try's refine
/// runs as the owner, as it did when the owner tried itself (its check note and its warning are
/// the owner's; review r1 F3, F4); null otherwise
PartDesignExport const DressUp* dressUpTriedFor(const DressUp* step)
{
    return dressUpRun && dressUpRun->keep ? freecad_cast<DressUp*>(step->StudioOwner.getValue())
                                          : nullptr;
}

/// ops#951 (review pr503-r1 T2): the try's note that a merged full round's face is named by the
/// edge order, said by the owner (the step that takes the kept shape runs no finish())
PartDesignExport void dressUpReappliedNote(const std::string& note)
{
    if (dressUpRun && dressUpRun->namingNote.empty()) {
        dressUpRun->namingNote = note;
    }
}

/// As dressUpReapplied(), with the shape before the refine. \a plain: the run built it the way
/// the feature's own compute reports nothing about (no exact construction's Report line)
PartDesignExport void dressUpReappliedFrom(const Part::TopoShape& raw,
                                           const Part::TopoShape& result,
                                           bool plain)
{
    if (dressUpRun) {
        dressUpRun->result = result;
        if (dressUpRun->keep && plain) {
            dressUpRun->raw = raw;
            dressUpRun->kept = true;
        }
    }
}

/// ops#796: a studio step's compute takes what its owner's try built on this base and these
/// edges with the step's parameters as they are, if it did: \a raw, before the refine (the step
/// refines it itself, as it does what it builds). The entry goes either way
PartDesignExport bool studioDressUpTake(const DressUp* step,
                                        const Part::TopoShape& base,
                                        const std::vector<Part::TopoShape>& edges,
                                        Part::TopoShape& raw)
{
    auto found = keptDressUps.find(step);
    if (found == keptDressUps.end()) {
        return false;
    }
    const KeptDressUp kept = std::move(found->second);
    keptDressUps.erase(found);
    if (kept.step != step->getID() || kept.owner != step->StudioOwner.getValue()
        || !kept.base.IsEqual(base.getShape()) || kept.edges.size() != edges.size()) {
        return false;
    }
    for (std::size_t i = 0; i < edges.size(); ++i) {
        if (!kept.edges[i].IsEqual(edges[i].getShape())) {
            return false;
        }
    }
    for (const auto& [name, value] : kept.parameters) {
        auto now = step->getPropertyByName(name.c_str());
        if (!now || savedValue(now) != value) {
            return false;
        }
    }
    raw = kept.raw;
    return true;
}

}  // namespace PartDesign

#include "FeatureChamfer.h"
#include "FeatureFillet.h"

namespace PartDesign
{

/// feature (a Chamfer or a Fillet) run on base's edges instead of its own: the result, or null
/// with why (ops#654 T3; declared where used, FeatureTransformed.cpp)
namespace
{
Part::TopoShape reapplyDressUpRun(
    DressUp* feature,
    const Part::TopoShape& base,
    const std::vector<Part::TopoShape>& edges,
    std::string& why,
    Part::TopoShape* raw,
    std::string* namingNote = nullptr
);
}  // namespace

PartDesignExport Part::TopoShape reapplyDressUp(
    DressUp* feature,
    const Part::TopoShape& base,
    const std::vector<Part::TopoShape>& edges,
    std::string& why
)
{
    return reapplyDressUpRun(feature, base, edges, why, nullptr);
}

namespace
{
/// \a raw: asked for, it takes the shape before the refine when the run kept one (null otherwise).
/// \a namingNote: asked for, the run's note of a merged face named by the edge order (ops#951)
Part::TopoShape reapplyDressUpRun(
    DressUp* feature,
    const Part::TopoShape& base,
    const std::vector<Part::TopoShape>& edges,
    std::string& why,
    Part::TopoShape* raw,
    std::string* namingNote
)
{
    DressUpRun run {base, edges, Part::TopoShape(), false, false, Part::TopoShape(), {}};
    run.keep = raw != nullptr;
    run.move = nextReapplyMove;
    nextReapplyMove = nullptr;
    DressUpRun* outer = dressUpRun;
    dressUpRun = &run;
    App::DocumentObjectExecReturn* ret = nullptr;
    try {
        if (auto chamfer = freecad_cast<Chamfer*>(feature)) {
            ret = chamfer->execute();
        }
        else if (auto fillet = freecad_cast<Fillet*>(feature)) {
            ret = fillet->execute();
        }
        else {
            why = "it isn't a chamfer or a fillet";
        }
    }
    catch (const Base::Exception& e) {
        why = e.what();
    }
    catch (const Standard_Failure& e) {
        why = e.GetMessageString();
    }
    dressUpRun = outer;
    if (namingNote) {
        *namingNote = run.namingNote;
    }
    if (ret) {
        why = ret->Why;
        delete ret;
        return {};
    }
    if (run.result.isNull() && why.empty()) {
        why = "it made nothing there";
    }
    if (raw && why.empty() && run.kept) {
        *raw = run.raw;
    }
    return why.empty() ? run.result : Part::TopoShape();
}
}  // namespace

}  // namespace PartDesign

// FreeCAD-CH ops#654 P8a (notes/parts-design.md 10.14): one fillet or chamfer over several parts.
// The owner, a Fillet or a Chamfer outside every Body, holds the parameters and the picks
// (StudioPickIds, "<part id>|<element name>", the name interned, ops#640 C1); a step of its own type in each
// part its picks resolve to does the work there, its parameters read from the owner when it runs.
// The owner computes no shape: it finds its picks at its place, writes them into a step's Base when
// they or its base changed (StudioPicksSeen), tries each part (as a pattern's instance re-run, T3)
// and reports: a part that fails is left unchanged and the owner warns (Onshape O2,
// FILLET_PARTIAL_FAIL); none rounded, it fails (FILLET_FAILED).

#include <App/ElementNamingUtils.h>
#include <App/ElementSolver.h>
#include <App/NameTable.h>

#include "Body.h"
#include "StudioList.h"
#include "StudioOwner.h"

namespace PartDesign
{

// StudioList.cpp (P8a; declared where used)
PartDesignExport std::vector<Body*> studioPickPartsAt(const App::DocumentObject* owner,
                                                      const std::string& id);

/// One pick of a dress-up owner, found at its place: the parts holding it, each with the subnames
/// (the map's own name and the index) of its elements there
struct StudioDressUpPick
{
    std::string text;  ///< as stored, "<part id>|<element name>" (interned, or expanded by an older build)
    std::string id;    ///< the part id
    std::vector<std::pair<Body*, std::vector<std::string>>> found;
};

/// owner's picks at its place, in order (declared where used)
PartDesignExport std::vector<StudioDressUpPick> studioDressUpPicks(const DressUp* owner);

namespace
{

/// The part's feature just before owner's step there, or null
Part::Feature* dressUpBaseOf(const DressUp* owner, const Body* part)
{
    auto step = StudioList::stepOf(owner, part);
    if (!step) {
        return nullptr;
    }
    return freecad_cast<Part::Feature*>(const_cast<Body*>(part)->getPrevSolidFeature(step));
}

/// Whether the element named candidate (expanded) is the pick's element: the same name, a piece
/// of it (a split, NameAncestry::isPieceOf), the name made again by the same feature from pieces
/// of its sources (ops#808: a face split by a feature inserted before the element's maker,
/// NameAncestry::isMadeFromPiecesOf; ops#849: a pad's cap whose profile gained or lost an edge,
/// the same call), or the name modified by a later feature (";:M", a
/// merge's fuse); never by equality of a stored, possibly shortened form (skeptic 1)
bool namesPick(const std::string& candidate, const std::string& pick)
{
    if (candidate == pick) {
        return true;
    }
    if (Data::NameAncestry::isPieceOf(candidate, pick)
        || Data::NameAncestry::isMadeFromPiecesOf(candidate, pick)) {
        return true;
    }
    return candidate.size() > pick.size() + 3 && candidate.starts_with(pick)
        && candidate.compare(pick.size(), 3, ";:M") == 0;
}

/// The subnames of shape's elements (edges, else faces) whose expanded names name the pick
std::vector<std::string> matchesOf(const Part::TopoShape& shape, const std::string& pick)
{
    std::vector<std::string> out;
    if (shape.isNull()) {
        return out;
    }
    const auto& table = Data::NameTable::instance();
    for (const char* type : {"Edge", "Face"}) {
        const int count = static_cast<int>(
            shape.countSubShapes(type[0] == 'E' ? TopAbs_EDGE : TopAbs_FACE)
        );
        for (int i = 1; i <= count; ++i) {
            const auto indexed = Data::IndexedName::fromConst(type, i);
            for (const auto& [name, sids] : shape.getElementMappedNames(indexed)) {
                if (namesPick(table.toPlain(name.toString()), pick)) {
                    out.push_back(
                        Data::ComplexGeoData::elementMapPrefix() + name.toString() + "."
                        + indexed.toString()
                    );
                    break;
                }
            }
        }
        if (!out.empty()) {
            break;
        }
    }
    if (!out.empty()) {
        return out;
    }
    // ops#852: none by the names above. An element made from a sketch vertex that keeps one of
    // the picked one's edge ends (Sketcher's split renames the vertex at the split edge's end),
    // taken only when every element found so names the same vertices: two vertices that each
    // keep an end (a corner cut off by a new line) are not told apart by names, and the pick is
    // then not found
    std::vector<std::string> vertices;
    for (const char* type : {"Edge", "Face"}) {
        const int count = static_cast<int>(
            shape.countSubShapes(type[0] == 'E' ? TopAbs_EDGE : TopAbs_FACE)
        );
        for (int i = 1; i <= count; ++i) {
            const auto indexed = Data::IndexedName::fromConst(type, i);
            for (const auto& [name, sids] : shape.getElementMappedNames(indexed)) {
                std::vector<std::string> kept;
                if (!Data::NameAncestry::isMadeFromPiecesOf(
                        table.toPlain(name.toString()),
                        pick,
                        &kept
                    )) {
                    continue;
                }
                std::ranges::sort(kept);
                if (out.empty()) {
                    vertices = kept;
                }
                else if (kept != vertices) {
                    return {};
                }
                out.push_back(
                    Data::ComplexGeoData::elementMapPrefix() + name.toString() + "."
                    + indexed.toString()
                );
                break;
            }
        }
        if (!out.empty()) {
            break;
        }
    }
    return out;
}

std::string partLabel(const DressUp* owner, const std::string& id)
{
    for (auto obj : owner->getDocument()->getObjectsOfType(Body::getClassTypeId())) {
        auto body = static_cast<Body*>(obj);
        if (studioPartId(body) == id) {
            return std::string("'") + body->Label.getValue() + "'";
        }
    }
    return "part '" + id + "'";
}

App::PropertyStringList* stringList(App::DocumentObject* obj, const char* name, const char* doc)
{
    auto prop = freecad_cast<App::PropertyStringList*>(obj->getPropertyByName(name));
    if (!prop) {
        prop = static_cast<App::PropertyStringList*>(obj->addDynamicProperty(
            "App::PropertyStringList",
            name,
            "Studio",
            doc,
            App::Prop_Hidden | App::Prop_Output | App::Prop_NoRecompute
        ));
    }
    return prop;
}

std::vector<std::string> stringsOf(const App::DocumentObject* obj, const char* name)
{
    auto prop = freecad_cast<App::PropertyStringList*>(obj->getPropertyByName(name));
    return prop ? prop->getValues() : std::vector<std::string>();
}

/// Whether a step's Base holds the elements the lookup found (names: "<mapped>.<indexed>"), each
/// resolved now, none missing (P8a-2)
bool holdsLookup(const App::PropertyLinkSub& link, const std::vector<std::string>& names)
{
    std::vector<std::string> held = link.getSubValues(false);
    if (std::ranges::any_of(held, [](const std::string& sub) {
            return sub.starts_with(Data::MISSING_PREFIX);
        })) {
        return false;
    }
    std::vector<std::string> found;
    for (const auto& name : names) {
        const auto dot = name.rfind('.');
        found.push_back(dot == std::string::npos ? name : name.substr(dot + 1));
    }
    std::ranges::sort(held);
    std::ranges::sort(found);
    return held == found;
}

/// The parameters a step reads from its owner when it runs (skeptic 3: never copied at
/// reconcile, so an edit of the owner by Python or the property editor can't leave it stale)
std::vector<const char*> ownerParameters(const DressUp* step)
{
    if (step->isDerivedFrom<Chamfer>()) {
        return {"ChamferType", "Size", "Size2", "Angle", "FlipDirection", "UseAllEdges",
                "TangentPropagation", "Refine", "WidthAt", "WidthPoints"};
    }
    return {"Radius", "UseAllEdges", "TangentPropagation", "Refine"};
}

void takeOwnerParameters(DressUp* step, const DressUp* owner)
{
    for (const char* name : ownerParameters(step)) {
        auto from = owner->getPropertyByName(name);
        auto to = step->getPropertyByName(name);
        if (from && to && from->getTypeId() == to->getTypeId() && !to->isSame(*from)) {
            to->Paste(*from);
        }
    }
}

}  // namespace

std::vector<StudioDressUpPick> studioDressUpPicks(const DressUp* owner)
{
    std::vector<StudioDressUpPick> out;
    if (!owner || !owner->getDocument()) {
        return out;
    }
    const auto scope = studioScopeOf(owner);
    std::map<const Body*, Part::TopoShape> shapes;
    for (const auto& text : owner->StudioPickIds.getValues()) {
        StudioDressUpPick pick;
        pick.text = text;
        const auto bar = text.find('|');
        pick.id = text.substr(0, bar);
        // The stored name is interned (ops#640 C1; an older build's, expanded, reads the same:
        // toPlain() keeps a name without references): matched expanded, as every candidate is
        const std::string name = bar == std::string::npos
            ? std::string()
            : Data::NameTable::instance().toPlain(std::string_view(text).substr(bar + 1));
        for (auto part : studioPickPartsAt(owner, pick.id)) {
            if (name.empty() || std::ranges::find(scope, part) == scope.end()) {
                continue;
            }
            auto it = shapes.find(part);
            if (it == shapes.end()) {
                auto base = dressUpBaseOf(owner, part);
                it = shapes.emplace(part, base ? base->Shape.getShape() : Part::TopoShape()).first;
            }
            auto subs = matchesOf(it->second, name);
            if (!subs.empty()) {
                pick.found.emplace_back(part, std::move(subs));
            }
        }
        out.push_back(std::move(pick));
    }
    return out;
}

/// The owner's compute, in place of the dress-up's (declared where used)
PartDesignExport App::DocumentObjectExecReturn* studioDressUpOwnerRun(DressUp* owner)
{
    owner->Shape.setValue(Part::TopoShape());
    const auto picks = studioDressUpPicks(owner);
    const std::string kind = owner->isDerivedFrom<Chamfer>() ? "chamfer" : "fillet";
    std::vector<std::string> notes;
    std::map<const Body*, std::vector<std::string>> subs;
    for (const auto& pick : picks) {
        if (pick.found.empty()) {
            // The fork's rule for a reference gone (ops#127, skeptic 4): computed on the rest,
            // with a warning; Onshape ignores it silently (oracle 9 P1)
            notes.push_back(partLabel(owner, pick.id) + ": a picked edge is not found");
        }
        else {
            // Every piece of the picked edge, in whatever part a split put it, is dressed: the
            // pick is the edge's whole history (Onshape, oracle for hub 11 P8a: a split before the
            // dress-up leaves its halves in two parts, both rounded, OK, one row; as P2 within one
            // part)
            for (const auto& [part, found] : pick.found) {
                auto& names = subs[part];
                for (const auto& name : found) {
                    if (std::ranges::find(names, name) == names.end()) {
                        names.push_back(name);
                    }
                }
            }
        }
    }
    auto useAll = freecad_cast<App::PropertyBool*>(owner->getPropertyByName("UseAllEdges"));
    const bool allEdges = useAll && useAll->getValue();
    std::vector<std::string> failed;
    int tried = 0;
    int done = 0;
    // ops#796: what an earlier run of this owner kept and no step took
    std::erase_if(keptDressUps, [owner](const auto& entry) { return entry.second.owner == owner; });
    if (keptDressUps.size() > 64) {
        keptDressUps.clear();
    }
    for (auto part : studioScopeOf(owner)) {
        auto step = freecad_cast<DressUp*>(StudioList::stepOf(owner, part));
        auto base = dressUpBaseOf(owner, part);
        if (!step || !base) {
            continue;
        }
        // The step's Base: written when its picks or its base changed, or when what it holds now
        // isn't what the lookup finds (P8a-2, 10.14 point 2 as amended): the list is the only
        // truth, so the result is the rebuild's from scratch. FreeCAD's tracking of the names it
        // last held can keep one piece of a split edge and lose another (a merge's edge cut
        // again, gate seed 6), where the lookup by ancestry finds them all; an element the lookup
        // misses is the owner's warning above, never a guess of the reference solver
        std::vector<std::string> wanted;
        for (const auto& pick : picks) {
            if (std::ranges::any_of(pick.found, [part](const auto& found) {
                    return found.first == part;
                })) {
                wanted.push_back(pick.text);
            }
        }
        wanted.push_back(std::string("@") + base->getNameInDocument());
        auto seen = stringList(step, "StudioPicksSeen", "What Base was last written from (ops#654 P8a)");
        const auto& names = subs[part];
        if (seen->getValues() != wanted || step->Base.getValue() != base
            || !holdsLookup(step->Base, names)) {
            if (!holdsLookup(step->Base, names) && step->Base.getValue() == base
                && step->Base.getSubValues() == names) {
                // The same names, one resolved to nothing when it was last tracked: a write of
                // the same value keeps each entry's shadow (ops#504 E2), so it is emptied first
                // and every name is resolved again on the base's shape as it is now
                step->Base.setValue(base, std::vector<std::string>());
            }
            if (step->Base.getValue() != base || step->Base.getSubValues() != names) {
                step->Base.setValue(base, names);
            }
            seen->setValues(wanted);
        }
        Part::TopoShape shape = step->getBaseTopoShape(/*silent=*/true);
        if (shape.isNull()) {
            failed.push_back(studioPartId(part));
            continue;
        }
        shape.locate(TopLoc_Location());
        const auto edges = allEdges ? shape.getSubTopoShapes(TopAbs_EDGE)
                                    : step->getContinuousEdges(shape);
        if (edges.empty()) {
            // None of its picks here: a piece whose sibling holds them, or picks not found (noted
            // above). It passes its base through
            failed.push_back(studioPartId(part));
            continue;
        }
        ++tried;
        std::string why;
        // ops#796: tried as the step itself, with the owner's parameters (which it reads when
        // it runs anyway): the same feature on the same base and edges builds the same shape
        // with the same names, so the step's compute takes this one instead of building again
        takeOwnerParameters(step, owner);
        Part::TopoShape raw;
        std::string namingNote;
        const Part::TopoShape tryResult
            = reapplyDressUpRun(step, shape, edges, why, &raw, &namingNote);
        if (!tryResult.isNull() && !raw.isNull()) {
            KeptDressUp kept;
            kept.step = step->getID();
            kept.owner = owner;
            kept.base = shape.getShape();
            for (const auto& edge : edges) {
                kept.edges.push_back(edge.getShape());
            }
            for (const char* name : ownerParameters(step)) {
                if (auto prop = step->getPropertyByName(name)) {
                    kept.parameters.emplace_back(name, savedValue(prop));
                }
            }
            kept.raw = raw;
            keptDressUps[step] = std::move(kept);
        }
        if (tryResult.isNull()) {
            // Onshape O2: this part is left unchanged, the others are rounded
            failed.push_back(studioPartId(part));
            notes.push_back(std::string("'") + part->Label.getValue() + "': " + why);
        }
        else {
            ++done;
            // ops#951 (review pr503-r1 T2): the step takes this shape and runs no finish()
            if (!namingNote.empty()) {
                notes.push_back(std::string("'") + part->Label.getValue() + "': " + namingNote);
            }
        }
    }
    auto prop = stringList(owner, "StudioFailedParts", "The parts whose step passes its base through (ops#654 P8a)");
    if (prop->getValues() != failed) {
        prop->setValues(failed);
    }
    std::string text;
    for (const auto& note : notes) {
        text += (text.empty() ? "" : "; ") + note;
    }
    if (done == 0) {
        return new App::DocumentObjectExecReturn(
            "The " + kind + " rounds no part"
                + (text.empty() ? std::string(": nothing it picked is found") : ": " + text),
            owner
        );
    }
    if (!text.empty()) {
        if (tried > done) {
            text = "Rounds " + std::to_string(done) + " of " + std::to_string(tried) + " parts: " + text;
        }
        owner->getDocument()->setWarning(owner, text);
    }
    return App::DocumentObject::StdReturn;
}

/// A step's compute starts here: its parameters from its owner; true when it passes its base
/// through (its part failed in the owner's try, or holds none of its picks). Declared where used
PartDesignExport bool studioDressUpStepPassesThrough(DressUp* step)
{
    auto owner = freecad_cast<DressUp*>(step->StudioOwner.getValue());
    if (!owner || Body::findBodyOf(owner)) {
        return false;
    }
    takeOwnerParameters(step, owner);
    const auto failed = stringsOf(owner, "StudioFailedParts");
    return std::ranges::find(failed, studioPartId(step->getFeatureBody())) != failed.end();
}

/// The owner's picks as its dialog lists them (P8a-2, 10.14 "the dialog"), one row per pick: the
/// part holding it at the owner's place and its elements there, "Part 2: Edge7" (a split edge:
/// "Part 2: Edge7, Edge9"; pieces in two parts: "Part 1: Edge3; Part 2: Edge7"); a pick found
/// nowhere says so. Declared where used
PartDesignExport std::vector<std::string> studioDressUpRows(const DressUp* owner)
{
    std::vector<std::string> rows;
    auto labelOf = [owner](const std::string& id) {
        for (auto obj : owner->getDocument()->getObjectsOfType(Body::getClassTypeId())) {
            auto body = static_cast<Body*>(obj);
            if (studioPartId(body) == id) {
                return std::string(body->Label.getValue());
            }
        }
        return id;
    };
    for (const auto& pick : studioDressUpPicks(owner)) {
        if (pick.found.empty()) {
            rows.push_back(labelOf(pick.id) + ": not found");
            continue;
        }
        // One row however many parts hold its pieces: "Part 1: Edge3; Part 2: Edge7"
        std::string row;
        for (const auto& [part, found] : pick.found) {
            std::string elements;
            for (const auto& sub : found) {
                const auto dot = sub.rfind('.');
                elements += (elements.empty() ? "" : ", ")
                    + (dot == std::string::npos ? sub : sub.substr(dot + 1));
            }
            row += (row.empty() ? "" : "; ") + std::string(part->Label.getValue()) + ": " + elements;
        }
        rows.push_back(row);
    }
    return rows;
}

/// The pick of element ("Edge3") of obj (a Body, or a feature of one) as owner stores it in
/// StudioPickIds, "<part id>|<element name>" with the name interned (P8a-2, the dialog's picks;
/// ops#640 C1: the map's own canonical form, bounded, its table entries saved with the file).
/// The part shows owner's own step once it rounds it: an element of that step is the same
/// element of the step's base, found by its geometry (a face the round made has none). Empty, with
/// why, when there is no pick. Declared where used
PartDesignExport std::string studioDressUpPickOf(const DressUp* owner,
                                                 App::DocumentObject* obj,
                                                 const std::string& element,
                                                 std::string& why)
{
    auto body = freecad_cast<Body*>(obj);
    if (!body) {
        body = Body::findBodyOf(obj);
    }
    auto feature = freecad_cast<Part::Feature*>(obj);
    if (!body || !feature) {
        why = "not an element of a part";
        return {};
    }
    Part::TopoShape shape = feature->Shape.getShape();
    std::string indexed = element;
    if (auto step = owner ? StudioList::stepOf(owner, body) : nullptr;
        step && (feature == step || (feature == body && body->Tip.getValue() == step))) {
        auto base = freecad_cast<Part::Feature*>(body->getPrevSolidFeature(step));
        Part::TopoShape baseShape = base ? base->Shape.getShape() : Part::TopoShape();
        Part::TopoShape picked;
        try {
            picked = shape.getSubTopoShape(element.c_str(), /*silent=*/true);
        }
        catch (...) {
        }
        std::vector<std::string> names;
        if (!picked.isNull() && !baseShape.isNull()) {
            baseShape.findSubShapesWithSharedVertex(picked, &names);
        }
        if (names.size() != 1) {
            why = "an element the " + std::string(owner->isDerivedFrom<Chamfer>() ? "chamfer" : "fillet")
                + " made: pick an edge the part had before it";
            return {};
        }
        shape = baseShape;
        indexed = names.front();
    }
    const auto mapped = shape.getElementMappedNames(Data::IndexedName(indexed.c_str()));
    if (mapped.empty()) {
        why = "the element has no name";
        return {};
    }
    return studioPartId(body) + "|"
        + Data::NameTable::instance().toInterned(mapped.front().first.toString());
}

}  // namespace PartDesign

// ops#655: tangent propagation off, as Onshape's (notes/loft-options.md, oracle fact GB13), for a
// fillet and a chamfer; declared where used
namespace
{

/// Takes out of `edges` the picked edges whose OCCT contour reaches an edge that isn't picked:
/// OCCT would fillet the whole tangent chain there. Returns them.
}  // namespace

namespace PartDesign
{
PartDesignExport std::vector<Part::TopoShape> takeChainedEdges(
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
}  // namespace PartDesign

namespace
{
[[noreturn]] void notStraightRunOut()
{
    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
        "Exception",
        "Tangent propagation off: a picked edge continues tangentially into an edge that isn't "
        "picked, and only a straight edge between two flat faces with a convex corner can stop "
        "there. Pick the whole tangent chain, or turn tangent propagation on."
    ));
}

[[noreturn]] void turnsIntoThePart(bool arc)
{
    if (arc) {
        throw Base::CADKernelError(QT_TRANSLATE_NOOP(
            "Exception",
            "Tangent propagation off: a picked edge runs on tangentially into an edge that turns into "
            "the part (a concave corner of the outline), where the round has no end: Onshape's fillet "
            "fails there too. Turn tangent propagation on to round the corner as well."
        ));
    }
    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
        "Exception",
        "Tangent propagation off: a picked edge runs on tangentially into an edge that turns into "
        "the part (a concave corner of the outline). The chamfer's straight run on through that "
        "corner is not built. Pick the whole tangent chain, or turn tangent propagation on."
    ));
}

[[noreturn]] void endOnTangentFaces()
{
    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
        "Exception",
        "Tangent propagation off: a picked edge ends on a face tangent to it where its tangent "
        "chain does not go on, and that face's surface does not end the dress-up there. Pick the "
        "whole tangent chain, or turn tangent propagation on."
    ));
}

/// The corner region a fillet of `radius` (`arc`) or an equal-distance chamfer of size `radius`
/// removes along a straight convex edge between two planar faces of `base`, extended along the
/// edge past the body both ways, as a prism: Onshape's fillet and chamfer run straight on past a
/// tangent vertex (GB13).
TopoDS_Shape runOutTool(const TopoDS_Shape& base, const TopoDS_Edge& edge, double radius, bool arc)
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

    // ops#1022: the tool runs on past an end only where the tangent chain goes on there (GB13):
    // an edge at the end that continues the edge tangentially, along one of its faces, with a
    // convex corner. At another end on a face tangent to the edge's direction (a blend running
    // out where a floor pinches out), Onshape ends the round as at any end on a face (RB9): the
    // tool runs on by a margin and is cut by that face's surface (trimRunOutAtFace). Ends on
    // other faces are as before
    TopTools_IndexedDataMapOfShapeListOfShape vertexFaces;
    TopExp::MapShapesAndAncestors(base, TopAbs_VERTEX, TopAbs_FACE, vertexFaces);
    TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
    TopExp::MapShapesAndAncestors(base, TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
    const TopoDS_Vertex ends[2] = {TopExp::FirstVertex(edge), TopExp::LastVertex(edge)};
    // One of the edge's faces, or a face on its plane with the same outside: the face split
    // coplanar at an end (pads side by side with Refine off, a fuse without removeSplitter) goes
    // on as one face, as on the refined body
    auto onEdgesFace = [&](const TopoDS_Shape& shape) {
        if (faces.Contains(shape)) {
            return true;
        }
        const TopoDS_Face& face = TopoDS::Face(shape);
        BRepAdaptor_Surface surface(face);
        if (surface.GetType() != GeomAbs_Plane) {
            return false;
        }
        gp_Dir outward = surface.Plane().Axis().Direction();
        if (face.Orientation() == TopAbs_REVERSED) {
            outward.Reverse();
        }
        if (surface.Plane().Distance(start) > Precision::Confusion()) {
            return false;
        }
        return outward.Dot(normal[0]) > 1 - 1e-9 || outward.Dot(normal[1]) > 1 - 1e-9;
    };
    // The index of the edge's face that a face is (onEdgesFace), or -1
    auto edgeFaceIndex = [&](const TopoDS_Shape& shape) {
        if (faces.Contains(shape)) {
            return faces.FindIndex(shape) - 1;
        }
        if (!onEdgesFace(shape)) {
            return -1;
        }
        const TopoDS_Face& face = TopoDS::Face(shape);
        gp_Dir outward = BRepAdaptor_Surface(face).Plane().Axis().Direction();
        if (face.Orientation() == TopAbs_REVERSED) {
            outward.Reverse();
        }
        return outward.Dot(normal[0]) > 1 - 1e-9 ? 0 : 1;
    };
    // ops#1028: where the chain goes on, whether the next edge curves, on the face it shares with
    // the edge, towards that face's material: a concave corner of the outline (a wall's corner
    // rounded, RB23, RB26). Onshape's fillet fails there; a slot's end turns away from it (GB13)
    bool turnsIn[2] = {false, false};
    auto chainGoesOn = [&](int e) {
        if (!vertexEdges.Contains(ends[e])) {
            return false;
        }
        const gp_Dir outOf = e == 0 ? along.Reversed() : along;
        TopTools_IndexedMapOfShape seen;
        for (const auto& shape : vertexEdges.FindFromKey(ends[e])) {
            const TopoDS_Edge& other = TopoDS::Edge(shape);
            if (other.IsSame(edge) || seen.Contains(other) || BRep_Tool::Degenerated(other)
                || !edgeFaces.Contains(other)) {
                continue;
            }
            seen.Add(other);
            TopTools_IndexedMapOfShape otherFaces;
            for (const auto& face : edgeFaces.FindFromKey(other)) {
                otherFaces.Add(face);
            }
            if (otherFaces.Extent() != 2
                || !(onEdgesFace(otherFaces(1)) || onEdgesFace(otherFaces(2)))) {
                continue;
            }
            BRepAdaptor_Curve curve(other);
            const bool atFirst = TopExp::FirstVertex(other).IsSame(ends[e]);
            gp_Pnt point;
            gp_Vec tangent;
            curve.D1(atFirst ? curve.FirstParameter() : curve.LastParameter(), point, tangent);
            if (tangent.Magnitude() < Precision::Confusion()) {
                continue;
            }
            if (!atFirst) {
                tangent.Reverse();
            }
            if (gp_Dir(tangent).Dot(outOf) < 1 - 1e-6) {
                continue;
            }
            if (ChFi3d::DefineConnectType(
                    other,
                    TopoDS::Face(otherFaces(1)),
                    TopoDS::Face(otherFaces(2)),
                    Precision::Angular(),
                    Standard_False
                )
                == ChFiDS_Convex) {
                BRepLProp_CLProps props(
                    curve,
                    atFirst ? curve.FirstParameter() : curve.LastParameter(),
                    2,
                    Precision::Confusion()
                );
                if (props.Curvature() > Precision::Confusion()) {
                    gp_Dir towardsCentre;
                    props.Normal(towardsCentre);
                    for (int i = 1; i <= 2; ++i) {
                        const int k = edgeFaceIndex(otherFaces(i));
                        if (k >= 0 && towardsCentre.Dot(into[k]) < -1e-6) {
                            turnsIn[e] = true;
                        }
                    }
                }
                return true;
            }
        }
        return false;
    };
    // The outward normal of a face at an end of the edge
    auto outwardAtEnd = [&](const TopoDS_Face& face, const TopoDS_Vertex& vertex, gp_Dir& outward) {
        BRepAdaptor_Surface surface(face);
        if (surface.GetType() == GeomAbs_Plane) {
            outward = surface.Plane().Axis().Direction();
        }
        else {
            const gp_Pnt2d uv = BRep_Tool::Parameters(vertex, face);
            BRepLProp_SLProps props(surface, uv.X(), uv.Y(), 1, Precision::Confusion());
            if (!props.IsNormalDefined()) {
                return false;
            }
            outward = props.Normal();
        }
        if (face.Orientation() == TopAbs_REVERSED) {
            outward.Reverse();
        }
        return true;
    };
    // The face that ends the round at an end where the chain does not go on: one tangent to the
    // edge's direction there, or, for a fillet, a curved one facing back along the edge (RB9 with
    // no blend: the scoop itself; its tangent plane cut too much). A chamfer has no Onshape fact
    // at a tangent face: it refuses there, and keeps the tangent plane at a curved one
    TopoDS_Face endFace[2];
    bool goesOn[2] = {false, false};
    for (int e = 0; e < 2; ++e) {
        if (!vertexFaces.Contains(ends[e])) {
            continue;
        }
        goesOn[e] = chainGoesOn(e);
        if (turnsIn[e]) {
            turnsIntoThePart(arc);
        }
        if (goesOn[e]) {
            continue;
        }
        const gp_Dir intoEdge = e == 0 ? along : along.Reversed();
        TopTools_IndexedMapOfShape seen;
        for (const auto& shape : vertexFaces.FindFromKey(ends[e])) {
            const TopoDS_Face& face = TopoDS::Face(shape);
            if (onEdgesFace(face) || seen.Contains(face)) {
                continue;
            }
            seen.Add(face);
            gp_Dir outward;
            if (!outwardAtEnd(face, ends[e], outward)) {
                continue;
            }
            const double facing = outward.Dot(intoEdge);
            const bool square = std::abs(facing) < 1e-6;
            const bool curvedBack = facing >= 1e-6
                && BRepAdaptor_Surface(face).GetType() != GeomAbs_Plane;
            if (!square && !(arc && curvedBack)) {
                continue;
            }
            if (!arc || !endFace[e].IsNull()) {
                endOnTangentFaces();
            }
            endFace[e] = face;
        }
    }

    Bnd_Box box;
    BRepBndLib::Add(base, box);
    const double past = std::sqrt(box.SquareExtent()) + radius;
    // Past such an end, a margin: the face's surface cuts the round off within it
    const double margin = 1 + 2 * radius;
    const double runOn[2] = {
        endFace[0].IsNull() ? past : margin,
        endFace[1].IsNull() ? past : margin
    };
    const gp_Pnt corner = start.Translated(gp_Vec(along) * -runOn[0]);
    const gp_Pnt centre = corner.Translated(toCentre);
    // a fillet's arc touches each face where the ball does; a chamfer's line meets each face
    // `radius` from the edge
    const gp_Pnt tangent0 = arc ? centre.Translated(gp_Vec(normal[0]) * radius)
                                : corner.Translated(gp_Vec(into[0]) * radius);
    const gp_Pnt tangent1 = arc ? centre.Translated(gp_Vec(normal[1]) * radius)
                                : corner.Translated(gp_Vec(into[1]) * radius);
    TopoDS_Edge across;
    if (arc) {
        const gp_Pnt arcMiddle = centre.Translated(gp_Vec(centre, corner).Normalized() * radius);
        across = BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(tangent0, arcMiddle, tangent1).Value())
                     .Edge();
    }
    else {
        across = BRepBuilderAPI_MakeEdge(tangent0, tangent1).Edge();
    }
    BRepBuilderAPI_MakeWire wire(
        BRepBuilderAPI_MakeEdge(corner, tangent0).Edge(),
        across,
        BRepBuilderAPI_MakeEdge(tangent1, corner).Edge()
    );
    BRepBuilderAPI_MakeFace section(wire.Wire(), true);
    TopoDS_Shape tool = BRepPrimAPI_MakePrism(
                            section.Face(),
                            gp_Vec(along) * (start.Distance(end) + runOn[0] + runOn[1])
    )
                            .Shape();

    // At an end where the edge meets a wall (a face there whose outside looks back along the edge:
    // a concave corner), the run-out stops at the wall as Onshape's does: the tool keeps only the
    // edge's side of the wall's plane (integrator 13, FilletRunOutPastWall). The face the body ends
    // at, or a face going on tangentially, looks away from or across the edge: the tool runs on.
    const double size = 2 * (start.Distance(end) + 2 * past + radius);
    // The tool keeps the side of the plane through `at` that `outward` looks to: a box larger than
    // the tool
    auto keepSide = [&](const gp_Pnt& at, const gp_Dir& outward) {
        const gp_Ax2 frame(at, outward);
        const gp_Pnt origin = at.Translated(
            (gp_Vec(frame.XDirection()) + gp_Vec(frame.YDirection())) * (-size / 2)
        );
        const TopoDS_Shape keep
            = BRepPrimAPI_MakeBox(gp_Ax2(origin, outward, frame.XDirection()), size, size, size)
                  .Shape();
        BRepAlgoAPI_Common trimmed(tool, keep);
        if (!trimmed.IsDone()) {
            notStraightRunOut();
        }
        tool = trimmed.Shape();
    };
    for (int e = 0; e < 2; ++e) {
        if (!vertexFaces.Contains(ends[e])) {
            continue;
        }
        const gp_Pnt at = BRep_Tool::Pnt(ends[e]);
        const gp_Dir intoEdge = e == 0 ? along : along.Reversed();
        TopTools_IndexedMapOfShape seen;
        for (const auto& shape : vertexFaces.FindFromKey(ends[e])) {
            const TopoDS_Face& face = TopoDS::Face(shape);
            if (faces.Contains(face) || seen.Contains(face) || face.IsSame(endFace[e])) {
                continue;
            }
            seen.Add(face);
            BRepAdaptor_Surface surface(face);
            gp_Dir outward;
            if (surface.GetType() == GeomAbs_Plane) {
                outward = surface.Plane().Axis().Direction();
            }
            else {
                const gp_Pnt2d uv = BRep_Tool::Parameters(ends[e], face);
                BRepLProp_SLProps props(surface, uv.X(), uv.Y(), 1, Precision::Confusion());
                if (!props.IsNormalDefined()) {
                    continue;
                }
                outward = props.Normal();
            }
            if (face.Orientation() == TopAbs_REVERSED) {
                outward.Reverse();
            }
            if (outward.Dot(intoEdge) < 1e-6) {
                continue;
            }
            // the edge's side of the wall's tangent plane
            keepSide(at, outward);
        }
    }
    // ops#1028 (RB26): where the chain goes on, the run on stops at the first face that the edge's
    // line, run on, pierces facing back along it: a wall standing across the run on (a slot's end
    // against a wall). A face the line only touches on its boundary is passed under (a boss
    // standing on the face over the run on: RB24 undercuts it)
    for (int e = 0; e < 2; ++e) {
        if (!goesOn[e]) {
            continue;
        }
        const gp_Dir outOf = e == 0 ? along.Reversed() : along;
        IntCurvesFace_ShapeIntersector hits;
        hits.Load(base, Precision::Confusion());
        hits.Perform(gp_Lin(BRep_Tool::Pnt(ends[e]), outOf), Precision::Confusion(), past);
        double nearest = std::numeric_limits<double>::infinity();
        gp_Pnt where;
        gp_Dir wallOutward;
        for (int i = 1; i <= hits.NbPnt(); ++i) {
            const double w = hits.WParameter(i);
            if (hits.State(i) != TopAbs_IN || w < 1e-6 || w >= nearest) {
                continue;
            }
            const TopoDS_Face& face = hits.Face(i);
            BRepAdaptor_Surface surface(face);
            BRepLProp_SLProps props(
                surface,
                hits.UParameter(i),
                hits.VParameter(i),
                1,
                Precision::Confusion()
            );
            if (!props.IsNormalDefined()) {
                continue;
            }
            gp_Dir outward = props.Normal();
            if (face.Orientation() == TopAbs_REVERSED) {
                outward.Reverse();
            }
            if (outward.Dot(outOf) > -1e-6) {
                continue;
            }
            nearest = w;
            where = hits.Pnt(i);
            wallOutward = outward;
        }
        if (std::isfinite(nearest)) {
            keepSide(where, wallOutward);
        }
    }
    // A point of the section near the edge at the edge's middle, and one in a run on
    const gp_Vec inSection = (gp_Vec(corner, tangent0) + gp_Vec(corner, tangent1)) * 0.1;
    for (int e = 0; e < 2; ++e) {
        if (endFace[e].IsNull()) {
            continue;
        }
        const gp_Pnt inside = middle.Translated(inSection);
        const gp_Pnt runOnEnd = BRep_Tool::Pnt(ends[e]).Translated(
            gp_Vec(e == 0 ? along.Reversed() : along) * (0.9 * margin) + inSection
        );
        tool = Part::FilletFallback::trimRunOutAtFace(
            Part::TopoShape(base),
            tool,
            edge,
            endFace[e],
            ends[e],
            radius,
            inside,
            runOnEnd
        );
        if (tool.IsNull()) {
            endOnTangentFaces();
        }
    }
    return tool;
}

}  // namespace

namespace PartDesign
{
/// The overlap of `shape` and the run-out tool of `edge` that touches `edge`: the fillet (`arc`)
/// or chamfer runs on until it leaves the body, and doesn't reach a part of the body the tool's
/// line enters again.
PartDesignExport TopoDS_Shape runOutCut(
    const TopoDS_Shape& shape,
    const TopoDS_Shape& base,
    const TopoDS_Edge& edge,
    double radius,
    bool arc
)
{
    BRepAlgoAPI_Common common(shape, runOutTool(base, edge, radius, arc));
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
}  // namespace PartDesign

// ops#883: tangent propagation off on a fillet's arc edge, as Onshape's (notes/runout-arc-883.md);
// declared where used
namespace
{
[[noreturn]] void arcRunOnStop()
{
    throw Base::CADKernelError(QT_TRANSLATE_NOOP(
        "Exception",
        "Tangent propagation off: a picked edge continues tangentially into an edge that isn't "
        "picked, and only a straight edge between two flat faces, or a fillet's arc between a flat "
        "face and a hollow cylinder that goes on into a straight edge, with a convex corner can "
        "stop there. Pick the whole tangent chain, or turn tangent propagation on."
    ));
}

/// The outward normal of `face` at `point` on it
bool outwardAt(const TopoDS_Face& face, const gp_Pnt& point, gp_Dir& outward)
{
    GeomAPI_ProjectPointOnSurf project(point, BRep_Tool::Surface(face));
    if (project.NbPoints() == 0) {
        return false;
    }
    double u = 0;
    double v = 0;
    project.LowerDistanceParameters(u, v);
    BRepLProp_SLProps props(BRepAdaptor_Surface(face), u, v, 1, Precision::Confusion());
    if (!props.IsNormalDefined()) {
        return false;
    }
    outward = props.Normal();
    if (face.Orientation() == TopAbs_REVERSED) {
        outward.Reverse();
    }
    return true;
}

/// Across `edge` at `point`, into `face` (a plane holding the edge whose direction there is
/// `along`)
gp_Dir intoFace(const TopoDS_Face& face, const gp_Pnt& point, const gp_Dir& along, double probe)
{
    gp_Dir normal;
    if (!outwardAt(face, point, normal)) {
        arcRunOnStop();
    }
    gp_Dir into = along.Crossed(normal);
    BRepClass_FaceClassifier inside(face, point.Translated(gp_Vec(into) * probe), 1e-9);
    if (inside.State() != TopAbs_IN) {
        into.Reverse();
        BRepClass_FaceClassifier other(face, point.Translated(gp_Vec(into) * probe), 1e-9);
        if (other.State() != TopAbs_IN) {
            arcRunOnStop();
        }
    }
    return into;
}

bool contains(const std::vector<Part::TopoShape>& shapes, const TopoDS_Shape& shape)
{
    return std::any_of(shapes.begin(), shapes.end(), [&](const Part::TopoShape& s) {
        return s.getShape().IsSame(shape);
    });
}
}  // namespace

namespace PartDesign
{
/// ops#883: Onshape runs the round of an arc edge between a plane square to the arc's axis and a
/// coaxial concave cylinder of the arc's radius (the rim of a pocket's rounded end) on along its
/// own torus, about the arc's axis, past an unpicked tangent neighbour, until it leaves the body;
/// the neighbour stays sharp (FGC-NS44 #73; oracle 9k's correction of FB1/FB4). A convex
/// cylinder is Onshape's refusal (FILLET_ADJOINING_EDGE_NOT_FILLETED). The construction is the
/// measured one (s2834's probe 5): OCCT rounds the arc with the rest, and with it its tangent
/// chain; along each unpicked straight neighbour the base's material comes back in the r by r
/// column at the corner, and the torus is cut in that column. Measured, and so built, only: a
/// fillet; a neighbour that is a straight edge between two square planes, the arc's own and
/// the cylinder's tangent plane, longer than the run-on, with no other picked edge at its ends;
/// an OCCT contour of the arc that holds only picked edges and those neighbours.
/// Takes the arcs out of `runOut` into `edges` and returns, per neighbour, the column and the
/// torus within it, its axis one way and the other (applyArcRunOns).
PartDesignExport std::vector<std::array<TopoDS_Shape, 3>> takeArcRunOns(
    const Part::TopoShape& base,
    std::vector<Part::TopoShape>& edges,
    std::vector<Part::TopoShape>& runOut,
    double radius
)
{
    constexpr double pi = 3.14159265358979323846;
    std::vector<std::array<TopoDS_Shape, 3>> runOns;
    // per arc, its round over its own span (the torus one way and the other) and its columns
    struct ArcSpan
    {
        TopoDS_Shape tori[2];
        size_t firstColumn = 0;
        size_t endColumn = 0;
        std::vector<TopoDS_Vertex> sharpEnds;
        double runOn = 0.0;
    };
    std::vector<ArcSpan> spans;
    std::vector<Part::TopoShape> picked = edges;
    // the edges OCCT rounds without the arcs: none of their rounds may reach a column
    const std::vector<Part::TopoShape> kept = edges;
    Bnd_Box box;
    BRepBndLib::Add(base.getShape(), box);
    // a column runs on along its line until it leaves the body: OCCT's round of the line runs on
    // past its far end where the face there meets the line at under 45 deg (r / tan of it)
    const double past = std::sqrt(box.SquareExtent()) + radius;
    picked.insert(picked.end(), runOut.begin(), runOut.end());
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopTools_IndexedDataMapOfShapeListOfShape vertexEdges;
    TopExp::MapShapesAndAncestors(base.getShape(), TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    TopExp::MapShapesAndAncestors(base.getShape(), TopAbs_VERTEX, TopAbs_EDGE, vertexEdges);
    std::vector<Part::TopoShape> straight;
    for (const auto& pick : runOut) {
        const TopoDS_Edge& edge = TopoDS::Edge(pick.getShape());
        BRepAdaptor_Curve curve(edge);
        if (curve.GetType() != GeomAbs_Circle) {
            straight.push_back(pick);
            continue;
        }
        const gp_Circ circle = curve.Circle();
        const gp_Dir axisDir = circle.Axis().Direction();
        const gp_Pnt centre = circle.Location();
        const double circleRadius = circle.Radius();
        const double first = curve.FirstParameter();
        const double last = curve.LastParameter();
        const double span = last - first;
        const double tolerance = std::max(Precision::Confusion(), 1e-9 * circleRadius);
        if (span <= 0 || span >= 2 * pi - 0.03 || !edgeFaces.Contains(edge)) {
            arcRunOnStop();
        }
        // the plane square to the axis and the coaxial cylinder beside the edge
        TopoDS_Face planeFace;
        TopoDS_Face cylinderFace;
        int count = 0;
        for (const auto& shape : edgeFaces.FindFromKey(edge)) {
            const TopoDS_Face& face = TopoDS::Face(shape);
            ++count;
            BRepAdaptor_Surface surface(face);
            if (surface.GetType() == GeomAbs_Plane
                && std::abs(surface.Plane().Axis().Direction().Dot(axisDir)) > 1 - 1e-9) {
                planeFace = face;
            }
            else if (surface.GetType() == GeomAbs_Cylinder) {
                const gp_Cylinder cylinder = surface.Cylinder();
                if (std::abs(cylinder.Axis().Direction().Dot(axisDir)) > 1 - 1e-9
                    && gp_Lin(cylinder.Axis()).Distance(centre) < tolerance
                    && std::abs(cylinder.Radius() - circleRadius) < tolerance) {
                    cylinderFace = face;
                }
            }
        }
        if (count != 2 || planeFace.IsNull() || cylinderFace.IsNull()) {
            arcRunOnStop();
        }
        const gp_Pnt middle = ElCLib::Value((first + last) / 2, circle);
        const gp_Dir radialMiddle(gp_Vec(centre, middle));
        gp_Dir planeOut;
        gp_Dir cylinderOut;
        if (!outwardAt(planeFace, middle, planeOut) || !outwardAt(cylinderFace, middle, cylinderOut)) {
            arcRunOnStop();
        }
        // concave: the material is outside the circle, the cylinder's outside looks at the axis
        if (cylinderOut.Dot(radialMiddle) > -1 + 1e-6) {
            arcRunOnStop();
        }
        // convex corner: the plane's material lies outward of the circle, the cylinder's below
        // the plane
        const double probe = std::min(1e-3 * radius, 1e-3 * circleRadius * span);
        BRepClass_FaceClassifier onPlane(
            planeFace,
            middle.Translated(gp_Vec(radialMiddle) * probe),
            1e-9
        );
        BRepClass_FaceClassifier onCylinder(
            cylinderFace,
            middle.Translated(gp_Vec(planeOut) * -probe),
            1e-9
        );
        if (onPlane.State() != TopAbs_IN || onCylinder.State() != TopAbs_IN) {
            arcRunOnStop();
        }
        const gp_Vec up = planeOut.Dot(axisDir) > 0 ? gp_Vec(axisDir) : gp_Vec(axisDir).Reversed();
        // the run-on past a tangent vertex along the cylinder's tangent plane: the torus
        // leaves it where (R + r) cos t = R
        const double runOn
            = std::sqrt((circleRadius + radius) * (circleRadius + radius) - circleRadius * circleRadius);
        // The tool: the corner's section in the half-plane through the axis (the corner, the
        // ball's touch point on the plane, outward of the corner, and on the cylinder, below it,
        // and the r arc), revolved over the arc and a quarter turn past each end; its sides lie
        // on the body's plane and cylinder (a line revolved parallel to the axis is a true
        // cylinder). Never a full turn: a full turn's common came back empty (s2834's probe 6)
        const double ext = std::min(pi / 2, (2 * pi - span) / 2 - 0.01);
        // the tool must reach as far round past each tangent vertex as the run-on does
        // (review of PR 487, S1: an arc over half a turn with a large r)
        if (ext < std::acos(circleRadius / (circleRadius + radius)) + 0.01) {
            arcRunOnStop();
        }
        // the section's arc from the plane to the cylinder gives the torus the axis `up`, the
        // other way round the axis down; revolved from `start` by `angle`
        const auto toolOf = [&](bool upward, double start, double angle) {
            const gp_Pnt corner = ElCLib::Value(start, circle);
            const gp_Vec radial = gp_Vec(centre, corner).Normalized();
            const gp_Pnt ball = corner.Translated(radial * radius - up * radius);
            const gp_Pnt onPlanePoint = corner.Translated(radial * radius);
            const gp_Pnt onCylinderPoint = corner.Translated(up * -radius);
            const gp_Pnt arcMiddle = ball.Translated(gp_Vec(ball, corner).Normalized() * radius);
            const gp_Pnt from = upward ? onPlanePoint : onCylinderPoint;
            const gp_Pnt to = upward ? onCylinderPoint : onPlanePoint;
            BRepBuilderAPI_MakeWire wire(
                BRepBuilderAPI_MakeEdge(corner, from).Edge(),
                BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(from, arcMiddle, to).Value()).Edge(),
                BRepBuilderAPI_MakeEdge(to, corner).Edge()
            );
            if (!wire.IsDone()) {
                arcRunOnStop();
            }
            BRepBuilderAPI_MakeFace section(wire.Wire(), true);
            if (!section.IsDone()) {
                arcRunOnStop();
            }
            BRepPrimAPI_MakeRevol revolve(section.Face(), circle.Axis(), angle);
            if (!revolve.IsDone()) {
                arcRunOnStop();
            }
            return revolve.Shape();
        };
        const TopoDS_Shape tori[2] = {
            toolOf(true, first - ext, span + 2 * ext),
            toolOf(false, first - ext, span + 2 * ext)
        };
        ArcSpan arcSpan;
        arcSpan.tori[0] = toolOf(true, first, span);
        arcSpan.tori[1] = toolOf(false, first, span);
        arcSpan.firstColumn = runOns.size();
        arcSpan.runOn = runOn;

        // The tangent neighbours
        TopTools_IndexedMapOfShape neighbours;
        const TopoDS_Vertex ends[2] = {TopExp::FirstVertex(edge), TopExp::LastVertex(edge)};
        const double endParameters[2] = {first, last};
        for (int e = 0; e < 2; ++e) {
            if (ends[e].IsNull() || !vertexEdges.Contains(ends[e])) {
                arcRunOnStop();
            }
            gp_Pnt at;
            gp_Vec tangent;
            curve.D1(endParameters[e], at, tangent);
            if (tangent.Magnitude() < Precision::Confusion()) {
                arcRunOnStop();
            }
            const gp_Dir intoEdge = e == 0 ? gp_Dir(tangent) : gp_Dir(tangent.Reversed());
            TopoDS_Edge line;
            for (const auto& shape : vertexEdges.FindFromKey(ends[e])) {
                const TopoDS_Edge& other = TopoDS::Edge(shape);
                if (other.IsSame(edge) || (!line.IsNull() && other.IsSame(line))
                    || BRep_Tool::Degenerated(other)) {
                    continue;
                }
                BRepAdaptor_Curve otherCurve(other);
                gp_Pnt point;
                gp_Vec direction;
                otherCurve.D1(BRep_Tool::Parameter(ends[e], other), point, direction);
                const bool tangential = direction.Magnitude() > Precision::Confusion()
                    && std::abs(gp_Dir(direction).Dot(intoEdge)) > 1 - 1e-7;
                if (!tangential) {
                    continue;
                }
                if (!line.IsNull() || contains(picked, other) || otherCurve.GetType() != GeomAbs_Line
                    || !edgeFaces.Contains(other)) {
                    arcRunOnStop();
                }
                line = other;
            }
            if (line.IsNull()) {
                arcSpan.sharpEnds.push_back(ends[e]);
                continue;  // a sharp end: OCCT ends the round there, as Onshape does
            }
            // no other picked edge at the tangent vertex: its round would reach the column
            for (const auto& shape : vertexEdges.FindFromKey(ends[e])) {
                if (!shape.IsSame(edge) && !shape.IsSame(line) && contains(picked, shape)) {
                    arcRunOnStop();
                }
            }
            // the line: between the arc's plane and a square plane, the cylinder's tangent plane
            TopoDS_Face lineFaces[2];
            int n = 0;
            for (const auto& shape : edgeFaces.FindFromKey(line)) {
                if (n == 2) {
                    arcRunOnStop();
                }
                lineFaces[n++] = TopoDS::Face(shape);
            }
            if (n != 2) {
                arcRunOnStop();
            }
            gp_Dir normals[2];
            for (int k = 0; k < 2; ++k) {
                BRepAdaptor_Surface surface(lineFaces[k]);
                if (surface.GetType() != GeomAbs_Plane) {
                    arcRunOnStop();
                }
                normals[k] = surface.Plane().Axis().Direction();
            }
            if (std::abs(normals[0].Dot(normals[1])) > 1e-9
                || (std::abs(normals[0].Dot(axisDir)) < 1 - 1e-9
                    && std::abs(normals[1].Dot(axisDir)) < 1 - 1e-9)) {
                arcRunOnStop();
            }
            const TopoDS_Vertex farEnd = TopExp::FirstVertex(line).IsSame(ends[e])
                ? TopExp::LastVertex(line)
                : TopExp::FirstVertex(line);
            const gp_Pnt farPoint = BRep_Tool::Pnt(farEnd);
            const double length = at.Distance(farPoint);
            if (length < runOn + radius) {
                arcRunOnStop();
            }
            // no picked edge at the line's farEnd end: its round would reach the column
            if (vertexEdges.Contains(farEnd)) {
                for (const auto& shape : vertexEdges.FindFromKey(farEnd)) {
                    if (!shape.IsSame(line) && contains(picked, shape)) {
                        arcRunOnStop();
                    }
                }
            }
            neighbours.Add(line);
            // The column: the r by r square at the corner, into both planes, along the line from
            // r before the tangent vertex on past its far end until it leaves the body
            const gp_Dir along(gp_Vec(at, farPoint));
            const gp_Pnt mid((at.XYZ() + farPoint.XYZ()) / 2);
            const double lineProbe = std::min(1e-3 * radius, 1e-3 * length);
            const gp_Dir into0 = intoFace(lineFaces[0], mid, along, lineProbe);
            const gp_Dir into1 = intoFace(lineFaces[1], mid, along, lineProbe);
            const gp_Pnt start = at.Translated(gp_Vec(along) * -radius);
            BRepBuilderAPI_MakeWire square(
                BRepBuilderAPI_MakeEdge(start, start.Translated(gp_Vec(into0) * radius)).Edge(),
                BRepBuilderAPI_MakeEdge(
                    start.Translated(gp_Vec(into0) * radius),
                    start.Translated(gp_Vec(into0) * radius + gp_Vec(into1) * radius)
                )
                    .Edge(),
                BRepBuilderAPI_MakeEdge(
                    start.Translated(gp_Vec(into0) * radius + gp_Vec(into1) * radius),
                    start.Translated(gp_Vec(into1) * radius)
                )
                    .Edge(),
                BRepBuilderAPI_MakeEdge(start.Translated(gp_Vec(into1) * radius), start).Edge()
            );
            if (!square.IsDone()) {
                arcRunOnStop();
            }
            BRepBuilderAPI_MakeFace squareFace(square.Wire(), true);
            if (!squareFace.IsDone()) {
                arcRunOnStop();
            }
            const TopoDS_Shape column
                = BRepPrimAPI_MakePrism(squareFace.Face(), gp_Vec(along) * (radius + past))
                      .Shape();
            std::array<TopoDS_Shape, 3> entry {column, TopoDS_Shape(), TopoDS_Shape()};
            for (int k = 0; k < 2; ++k) {
                BRepAlgoAPI_Common within(tori[k], column);
                if (!within.IsDone()) {
                    arcRunOnStop();
                }
                GProp_GProps props;
                BRepGProp::VolumeProperties(within.Shape(), props);
                if (props.Mass() <= 0) {
                    arcRunOnStop();
                }
                entry[k + 1] = within.Shape();
            }
            runOns.push_back(entry);
        }
        if (neighbours.IsEmpty()) {
            arcRunOnStop();
        }
        arcSpan.endColumn = runOns.size();
        spans.push_back(arcSpan);
        // OCCT's contour of the arc holds picked edges and these neighbours only
        BRepFilletAPI_MakeFillet maker(base.getShape());
        maker.Add(radius, edge);
        for (int contour = 1; contour <= maker.NbContours(); ++contour) {
            for (int i = 1; i <= maker.NbEdges(contour); ++i) {
                const TopoDS_Edge& member = maker.Edge(contour, i);
                if (!neighbours.Contains(member) && !contains(picked, member)) {
                    arcRunOnStop();
                }
            }
        }
        edges.push_back(pick);
    }
    // the base's material comes back in each column: no other round may have taken any of it
    if (!runOns.empty() && !kept.empty()) {
        BRepFilletAPI_MakeFillet others(base.getShape());
        for (const auto& edge : kept) {
            others.Add(radius, TopoDS::Edge(edge.getShape()));
        }
        others.Build();
        if (!others.IsDone() || others.Shape().IsNull()) {
            arcRunOnStop();
        }
        for (const auto& runOn : runOns) {
            BRepAlgoAPI_Common before(base.getShape(), runOn[0]);
            BRepAlgoAPI_Common after(others.Shape(), runOn[0]);
            if (!before.IsDone() || !after.IsDone()) {
                arcRunOnStop();
            }
            GProp_GProps beforeProps;
            GProp_GProps afterProps;
            BRepGProp::VolumeProperties(before.Shape(), beforeProps);
            BRepGProp::VolumeProperties(after.Shape(), afterProps);
            if (std::abs(beforeProps.Mass() - afterProps.Mass())
                > 1e-6 * beforeProps.Mass() + Precision::Confusion()) {
                arcRunOnStop();
            }
        }
    }
    // Another arc's column puts the base's material back over this arc's round where it crosses
    // it (review of PR 487, M2: two rounded pocket ends in a row, both picked): Onshape rounds
    // each arc as alone, so its round over its own span is cut again within that column. No
    // column is restored for these entries (a null column), only the cut. The arc's run-on
    // beyond its ends lies in its own columns, cut there.
    // At a sharp end OCCT's round of the arc alone runs past the end's meridian plane or stops
    // short of it, by the end wall's slant, out to where that wall meets the ring's outer circle:
    // at most the run-on from the end for a wall near the tangent. Another arc's column there
    // puts material back or the span torus takes too much (review of PR 487 round 3, T1, and its
    // fix's review): any column of another arc within the run-on and 2 r of a sharp end stops,
    // whether or not it crosses the span torus
    const size_t columns = runOns.size();
    for (const auto& arcSpan : spans) {
        for (const auto& sharp : arcSpan.sharpEnds) {
            for (size_t j = 0; j < columns; ++j) {
                if (j >= arcSpan.firstColumn && j < arcSpan.endColumn) {
                    continue;
                }
                BRepExtrema_DistShapeShape distance(runOns[j][0], sharp);
                if (!distance.IsDone() || distance.Value() < arcSpan.runOn + 2 * radius) {
                    arcRunOnStop();
                }
            }
        }
    }
    for (const auto& arcSpan : spans) {
        for (size_t j = 0; j < columns; ++j) {
            if (j >= arcSpan.firstColumn && j < arcSpan.endColumn) {
                continue;
            }
            std::array<TopoDS_Shape, 3> entry;
            bool crosses = false;
            for (int k = 0; k < 2; ++k) {
                BRepAlgoAPI_Common within(arcSpan.tori[k], runOns[j][0]);
                if (!within.IsDone() || within.HasErrors()) {
                    arcRunOnStop();
                }
                GProp_GProps props;
                BRepGProp::VolumeProperties(within.Shape(), props);
                if (k == 0) {
                    crosses = props.Mass() > Precision::Confusion();
                    if (!crosses) {
                        break;
                    }
                }
                else if (props.Mass() <= Precision::Confusion()) {
                    arcRunOnStop();
                }
                entry[k + 1] = within.Shape();
            }
            if (crosses) {
                runOns.push_back(entry);
            }
        }
    }
    runOut = std::move(straight);
    return runOns;
}
}  // namespace PartDesign

// ops#883: the arcs' run-on, applied to the fillet's result; declared where used
namespace
{
/// The torus of a toroidal face of `shape`, the first one
bool torusOf(const TopoDS_Shape& shape, gp_Torus& torus)
{
    for (TopExp_Explorer xp(shape, TopAbs_FACE); xp.More(); xp.Next()) {
        BRepAdaptor_Surface surface(TopoDS::Face(xp.Current()));
        if (surface.GetType() == GeomAbs_Torus) {
            torus = surface.Torus();
            return true;
        }
    }
    return false;
}

/// Whether two tori are the same surface, either way round its axis
bool sameTorus(const gp_Torus& a, const gp_Torus& b)
{
    const double tolerance = 1e-9 * (a.MajorRadius() + a.MinorRadius()) + Precision::Confusion();
    return a.Location().Distance(b.Location()) < tolerance
        && std::abs(a.Axis().Direction().Dot(b.Axis().Direction())) > 1 - 1e-9
        && std::abs(a.MajorRadius() - b.MajorRadius()) < tolerance
        && std::abs(a.MinorRadius() - b.MinorRadius()) < tolerance;
}

double volumeOf(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape, props);
    return props.Mass();
}
}  // namespace

namespace PartDesign
{
/// ops#883: puts the base's material back in each run-on's column and cuts the torus there,
/// then merges each torus the cut split (OCCT's round of the arc and its run-on: Onshape's one
/// face), and only those. `runOns` from takeArcRunOns: the column, the torus within it with its
/// axis one way and the other; the one OCCT's round has is cut, else the faces wouldn't merge.
/// `blank` names the results (the feature's makeTopoShape())
PartDesignExport Part::TopoShape applyArcRunOns(
    Part::TopoShape shape,
    const Part::TopoShape& base,
    const std::vector<std::array<TopoDS_Shape, 3>>& runOns,
    const Part::TopoShape& blank
)
{
    std::vector<TopoDS_Shape> cutters;
    for (const auto& runOn : runOns) {
        gp_Torus cutter;
        if (!torusOf(runOn[1], cutter)) {
            arcRunOnStop();
        }
        TopoDS_Shape chosen = runOn[1];
        for (TopExp_Explorer xp(shape.getShape(), TopAbs_FACE); xp.More(); xp.Next()) {
            BRepAdaptor_Surface surface(TopoDS::Face(xp.Current()));
            if (surface.GetType() == GeomAbs_Torus && sameTorus(surface.Torus(), cutter)) {
                if (surface.Torus().Axis().Direction().Dot(cutter.Axis().Direction()) < 0) {
                    chosen = runOn[2];
                }
                break;
            }
        }
        cutters.push_back(chosen);
    }
    for (const auto& runOn : runOns) {
        if (runOn[0].IsNull()) {
            continue;  // only a cut: another arc's round crossed by a column (takeArcRunOns)
        }
        BRepAlgoAPI_Common back(base.getShape(), runOn[0]);
        if (!back.IsDone()) {
            arcRunOnStop();
        }
        Part::TopoShape tool(blank);
        tool.setShape(back.Shape());
        Part::TopoShape fused(blank);
        fused.makeElementFuse({shape, tool});
        shape = fused;
    }
    for (const auto& cutter : cutters) {
        Part::TopoShape tool(blank);
        tool.setShape(cutter);
        Part::TopoShape cut(blank);
        cut.makeElementCut({shape, tool});
        shape = cut;
    }
    // the seams: edges between two faces of one torus
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndAncestors(shape.getShape(), TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    TopTools_MapOfShape keep;
    int seams = 0;
    for (int i = 1; i <= edgeFaces.Extent(); ++i) {
        std::vector<gp_Torus> tori;
        TopTools_IndexedMapOfShape faces;
        for (const auto& face : edgeFaces(i)) {
            faces.Add(face);
        }
        for (int k = 1; k <= faces.Extent(); ++k) {
            BRepAdaptor_Surface surface(TopoDS::Face(faces(k)));
            if (surface.GetType() == GeomAbs_Torus) {
                tori.push_back(surface.Torus());
            }
        }
        const bool seam = faces.Extent() == 2 && tori.size() == 2 && sameTorus(tori[0], tori[1])
            && std::any_of(cutters.begin(), cutters.end(), [&](const TopoDS_Shape& cutter) {
                   gp_Torus torus;
                   return torusOf(cutter, torus) && sameTorus(torus, tori[0]);
               });
        if (seam) {
            ++seams;
        }
        else {
            keep.Add(edgeFaces.FindKey(i));
        }
    }
    if (seams == 0) {
        return shape;
    }
    ShapeUpgrade_UnifySameDomain unify(shape.getShape(), true, true, false);
    unify.KeepShapes(keep);
    unify.Build();
    const TopoDS_Shape& unified = unify.Shape();
    const double before = volumeOf(shape.getShape());
    if (unified.IsNull() || !BRepCheck_Analyzer(unified).IsValid()
        || std::abs(volumeOf(unified) - before) > 1e-7 * std::abs(before) + Precision::Confusion()) {
        return shape;  // the seam stays: a face more than Onshape's, the same solid
    }
    Part::TopoShape merged(blank);
    merged.makeShapeWithElementMap(unified, Part::MapperHistory(unify.History()), {shape}, Part::OpCodes::Refine);
    return merged;
}
}  // namespace PartDesign

// FreeCAD-CH ops#640 F2: a fillet's or chamfer's failure in Onshape's words (design F, row 104)
namespace
{
/// Whether text is OCCT's or C++'s own words rather than the fork's: an OCCT class or exception
/// name ("TopOpeBRepDS_DataStructure::Point", "Standard_OutOfRange", "BRep_API: ..."), the
/// exact construction's "OCCT: ..." relay, "command not done", or nothing at all
bool isKernelText(const std::string& text)
{
    static const std::regex internal(
        R"(\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|\b(?:TopoDS|Base|Part|std)::\w+|)"
        R"(command not done|Unknown C\+\+ exception|^\s*OCCT:)"
    );
    return text.find_first_not_of(" \t\r\n") == std::string::npos
        || std::regex_search(text, internal);
}
}  // namespace

namespace PartDesign
{

/** The message of a fillet or chamfer that failed, as Onshape's: "Failed to fillet selections"
 * with the exact construction's reason after it, and never OCCT's raw text.
 *
 * TopoShape::makeElementFillet() and makeElementChamfer() raise OCCT's error with the reason
 * appended, "BRep_API: command not done (exact construction refused: <reason>)", or the fork's
 * own thin-face error, which names the reason too; OCCT's other errors come as they are.
 *
 * @param verb "fillet" or "chamfer"
 * @param what The error's text
 * @return "Failed to <verb> selections: <reason>", with a hint where no reason is readable
 */
PartDesignExport std::string dressUpFailure(const char* verb, const std::string& what)
{
    static const std::string marker = "exact construction refused: ";
    std::string reason;
    const std::size_t at = what.find(marker);
    if (at != std::string::npos && at > 0 && what[at - 1] == '(') {
        // OCCT's error with the reason in parentheses: the reason alone
        reason = what.substr(at + marker.size());
        if (!reason.empty() && reason.back() == ')') {
            reason.pop_back();
        }
        if (isKernelText(reason)) {
            reason.clear();
        }
    }
    else if (!isKernelText(what)) {
        reason = what;
    }
    else if (at != std::string::npos && !isKernelText(what.substr(at + marker.size()))) {
        reason = what.substr(at + marker.size());
    }
    const std::string verbText(verb);
    if (reason.empty()) {
        reason = "the geometry kernel could not build it; try a smaller "
            + std::string(verbText == "fillet" ? "radius" : "size") + " or fewer edges";
    }
    return "Failed to " + verbText + " selections: " + reason;
}

/// Whether a dress-up's error is reworded by dressUpFailure(): OCCT's text, or one that carries
/// the exact construction's reason. The fork's other errors (a time limit, Esc) stay as they are.
PartDesignExport bool isDressUpFailure(const std::string& what)
{
    return isKernelText(what) || what.find("exact construction refused: ") != std::string::npos;
}

}  // namespace PartDesign

namespace PartDesign
{

namespace
{

/// Whether `follower` still follows `primary`: the expression of its size refers to it. That
/// expression alone orders the two (MultiPartPrimary is hidden), so without it the primary's
/// state may be stale; and the user has given this part a size of its own (ops#701 F2c)
bool followsBySize(
    const App::DocumentObject* follower,
    App::DocumentObject* primary,
    const char* sizeProperty
)
{
    const App::Property* size = follower->getPropertyByName(sizeProperty);
    if (!size) {
        return false;
    }
    const auto info = follower->getExpression(App::ObjectIdentifier(*size));
    if (!info.expression) {
        return false;
    }
    // A hidden reference (href()) adds no dependency edge: it orders nothing
    const auto deps = info.expression->getDepObjects();
    const auto dep = deps.find(primary);
    return dep != deps.end() && !dep->second;
}

/// Whether the primary built its own result: not an error, not suppressed, not passed through
/// (a suppressed feature's or its own partial failure's), not held by its Body's roll-back bar
bool builtItself(const DressUp* primary)
{
    if (primary->isError() || primary->Shape.getShape().isNull() || primary->Suppressed.getValue()
        || primary->passesBaseThrough()) {
        return false;
    }
    const Body* body = primary->getFeatureBody();
    return !(body && body->holds(primary));
}

}  // namespace

App::DocumentObjectExecReturn* DressUp::partialFailure(
    App::DocumentObjectExecReturn* ret,
    const char* verb,
    const char* sizeProperty
)
{
    auto primary = freecad_cast<DressUp*>(MultiPartPrimary.getValue());
    // Not inside a pattern's re-run (dressUpRun), whose caller takes the failure. A link whose
    // size expression is gone (cleared, replaced) is no link: nothing orders the two (F2c)
    if (!ret || ret == App::DocumentObject::StdReturn || dressUpRun || !primary || primary == this
        || !followsBySize(this, primary, sizeProperty) || !builtItself(primary)) {
        return ret;
    }
    Part::TopoShape base;
    try {
        base = getBaseTopoShape(true);
    }
    catch (const Base::Exception&) {
    }
    if (base.isNull()) {
        return ret;
    }
    std::string why = ret->Why;
    delete ret;
    // "Failed to fillet selections: <reason>" (dressUpFailure()) names the part; another
    // failure (an invalid result, a recess filled) goes after it
    const std::string failed = "Failed to " + std::string(verb) + " selections";
    const Body* body = getFeatureBody();
    const std::string on = failed + " on " + (body ? body->Label.getValue() : Label.getValue());
    why = why.rfind(failed + ": ", 0) == 0 ? on + why.substr(failed.size()) : on + ": " + why;

    // As a suppressed feature's: the output is the base, the feature's own state is a success
    this->positionByBaseFeature();
    if (!_PassedThrough.getValue()) {
        _PassedThrough.setValue(true);
    }
    setFailurePassedThrough(false);
    Shape.setValue(base);
    // Nothing of its own for a pattern to apply, as a suppressed feature's. onChanged(Shape)
    // has cleared it already (this runs only in execute()); said here, where it matters
    AddSubShape.setValue(Part::TopoShape());
    if (auto doc = getDocument()) {
        const char* previous = doc->getWarningDescription(this);
        doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + why : why);
    }
    return App::DocumentObject::StdReturn;
}

}  // namespace PartDesign
