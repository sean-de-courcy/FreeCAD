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

#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopExp_Explorer.hxx>

#include <cstring>

#include <boost/algorithm/string/predicate.hpp>

#include "FeatureDressUp.h"
#include "PartDesignParameter.h"
#include <Base/Console.h>
#include <App/Document.h>
#include <App/ElementNamingUtils.h>
#include <Base/Exception.h>
#include "Mod/Part/App/TopoShapeMapper.h"

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
        "A studio dress-up's picks: '<part id>|<element name>', the name expanded (ops#654 P8a)"
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
// (StudioPickIds, "<part id>|<element name>", the name expanded); a step of its own type in each
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
    std::string text;  ///< as stored, "<part id>|<element name>"
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

/// The parameters a step reads from its owner when it runs (skeptic 3: never copied at
/// reconcile, so an edit of the owner by Python or the property editor can't leave it stale)
std::vector<const char*> ownerParameters(const DressUp* step)
{
    if (step->isDerivedFrom<Chamfer>()) {
        return {"ChamferType", "Size", "Size2", "Angle", "FlipDirection", "UseAllEdges", "Refine"};
    }
    return {"Radius", "UseAllEdges", "Refine"};
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
        const std::string name = bar == std::string::npos ? std::string() : text.substr(bar + 1);
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
        else if (pick.found.size() > 1) {
            std::string where;
            for (const auto& found : pick.found) {
                where += (where.empty() ? "'" : ", '") + std::string(found.first->Label.getValue())
                    + "'";
            }
            notes.push_back(partLabel(owner, pick.id) + ": a picked edge is in two parts (" + where
                            + "), so it is left out (unverified on Onshape)");
        }
        else {
            auto& names = subs[pick.found.front().first];
            for (const auto& name : pick.found.front().second) {
                if (std::ranges::find(names, name) == names.end()) {
                    names.push_back(name);
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
        // The step's Base: written when its picks or its base changed, else FreeCAD's own
        // (skeptic 2: the reference solver's guesses and warnings are never reset silently)
        std::vector<std::string> wanted;
        for (const auto& pick : picks) {
            if (pick.found.size() == 1 && pick.found.front().first == part) {
                wanted.push_back(pick.text);
            }
        }
        wanted.push_back(std::string("@") + base->getNameInDocument());
        auto seen = stringList(step, "StudioPicksSeen", "What Base was last written from (ops#654 P8a)");
        if (seen->getValues() != wanted || step->Base.getValue() != base) {
            const auto& names = subs[part];
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

}  // namespace PartDesign
