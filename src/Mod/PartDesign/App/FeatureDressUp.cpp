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
#include <BRepLProp_SLProps.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <Bnd_Box.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <Geom_TrimmedCurve.hxx>
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

#include <cstring>
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
#include "Mod/Part/App/TopoShapeMapper.h"
#include "Body.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesign;

namespace PartDesign
{


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
};
thread_local DressUpRun* dressUpRun = nullptr;
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

PartDesignExport void dressUpReapplied(const Part::TopoShape& result)
{
    if (dressUpRun) {
        dressUpRun->result = result;
    }
}

}  // namespace PartDesign

#include "FeatureChamfer.h"
#include "FeatureFillet.h"

namespace PartDesign
{

/// feature (a Chamfer or a Fillet) run on base's edges instead of its own: the result, or null
/// with why (ops#654 T3; declared where used, FeatureTransformed.cpp)
PartDesignExport Part::TopoShape reapplyDressUp(
    DressUp* feature,
    const Part::TopoShape& base,
    const std::vector<Part::TopoShape>& edges,
    std::string& why
)
{
    DressUpRun run {base, edges, Part::TopoShape()};
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
    if (ret) {
        why = ret->Why;
        delete ret;
        return {};
    }
    if (run.result.isNull() && why.empty()) {
        why = "it made nothing there";
    }
    return why.empty() ? run.result : Part::TopoShape();
}

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
/// of it (a split, NameAncestry::isPieceOf), or the name modified by a later feature (";:M", a
/// merge's fuse); never by equality of a stored, possibly shortened form (skeptic 1)
bool namesPick(const std::string& candidate, const std::string& pick)
{
    if (candidate == pick) {
        return true;
    }
    if (Data::NameAncestry::isPieceOf(candidate, pick)) {
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
                "TangentPropagation", "Refine"};
    }
    return {"Radius", "UseAllEdges", "TangentPropagation", "Refine"};
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
        if (reapplyDressUp(owner, shape, edges, why).isNull()) {
            // Onshape O2: this part is left unchanged, the others are rounded
            failed.push_back(studioPartId(part));
            notes.push_back(std::string("'") + part->Label.getValue() + "': " + why);
        }
        else {
            ++done;
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
    for (const char* name : ownerParameters(step)) {
        auto from = owner->getPropertyByName(name);
        auto to = step->getPropertyByName(name);
        if (from && to && from->getTypeId() == to->getTypeId() && !to->isSame(*from)) {
            to->Paste(*from);
        }
    }
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

    Bnd_Box box;
    BRepBndLib::Add(base, box);
    const double past = std::sqrt(box.SquareExtent()) + radius;
    const gp_Pnt corner = start.Translated(gp_Vec(along) * -past);
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
    TopoDS_Shape tool
        = BRepPrimAPI_MakePrism(section.Face(), gp_Vec(along) * (start.Distance(end) + 2 * past))
              .Shape();

    // At an end where the edge meets a wall (a face there whose outside looks back along the edge:
    // a concave corner), the run-out stops at the wall as Onshape's does: the tool keeps only the
    // edge's side of the wall's plane (integrator 13, FilletRunOutPastWall). The face the body ends
    // at, or a face going on tangentially, looks away from or across the edge: the tool runs on.
    TopTools_IndexedDataMapOfShapeListOfShape vertexFaces;
    TopExp::MapShapesAndAncestors(base, TopAbs_VERTEX, TopAbs_FACE, vertexFaces);
    const double size = 2 * (start.Distance(end) + 2 * past + radius);
    const TopoDS_Vertex ends[2] = {TopExp::FirstVertex(edge), TopExp::LastVertex(edge)};
    for (int e = 0; e < 2; ++e) {
        if (!vertexFaces.Contains(ends[e])) {
            continue;
        }
        const gp_Pnt at = BRep_Tool::Pnt(ends[e]);
        const gp_Dir intoEdge = e == 0 ? along : along.Reversed();
        TopTools_IndexedMapOfShape seen;
        for (const auto& shape : vertexFaces.FindFromKey(ends[e])) {
            const TopoDS_Face& face = TopoDS::Face(shape);
            if (faces.Contains(face) || seen.Contains(face)) {
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
            // a box on the edge's side of the wall's tangent plane, larger than the tool
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
