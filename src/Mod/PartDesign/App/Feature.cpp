// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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


#include <BRep_Tool.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepCheck_Solid.hxx>
#include <BRepCheck_Status.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <ShapeFix_Solid.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Builder.hxx>

#include <cstring>
#include <set>
#include <vector>

#include "App/Datums.h"
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <App/ElementSolverBatch.h>
#include <App/FeaturePythonPyImp.h>
#include <App/GeoFeatureGroupExtension.h>
#include <Base/Console.h>

#include "Feature.h"
#include "FailureContinuation.h"
#include "FeaturePy.h"
#include "Body.h"
#include "ShapeBinder.h"

#include <BRep_Builder.hxx>

FC_LOG_LEVEL_INIT("PartDesign", true, true)


namespace PartDesign
{

namespace
{

Base::Placement getObjectPlacement(const App::DocumentObject* object)
{
    if (!object) {
        return {};
    }

    auto placement = object->getPropertyByName<App::PropertyPlacement>("Placement");
    return placement ? placement->getValue() : Base::Placement();
}

Base::Placement getContainingGeoFeatureGroupPlacement(const App::DocumentObject* object)
{
    Base::Placement placement;
    std::set<const App::DocumentObject*> visited;
    std::vector<const App::DocumentObject*> groups;

    for (auto group = App::GeoFeatureGroupExtension::getGroupOfObject(object);
         group && visited.insert(group).second;
         group = App::GeoFeatureGroupExtension::getGroupOfObject(group)) {
        groups.push_back(group);
    }

    for (auto it = groups.rbegin(); it != groups.rend(); ++it) {
        placement = placement * getObjectPlacement(*it);
    }

    return placement;
}

Base::Placement getDisplayedObjectPlacement(const App::DocumentObject* object)
{
    return getContainingGeoFeatureGroupPlacement(object) * getObjectPlacement(object);
}

}  // namespace

bool getPDRefineModelParameter()
{
    Base::Reference<ParameterGrp> hGrp = App::GetApplication()
                                             .GetUserParameter()
                                             .GetGroup("BaseApp")
                                             ->GetGroup("Preferences")
                                             ->GetGroup("Mod/PartDesign");
    return hGrp->GetBool("RefineModel", true);
}

// ------------------------------------------------------------------------------------------------

PROPERTY_SOURCE(PartDesign::Feature, Part::Feature)

Feature::Feature()
{
    ADD_PROPERTY(BaseFeature, (nullptr));
    ADD_PROPERTY_TYPE(
        _Body,
        (nullptr),
        "Base",
        (App::PropertyType)(App::Prop_ReadOnly | App::Prop_Hidden | App::Prop_Output
                            | App::Prop_Transient),
        0
    );
    ADD_PROPERTY(SuppressedShape, (TopoShape()));
    Placement.setStatus(App::Property::Hidden, true);
    BaseFeature.setStatus(App::Property::Hidden, true);

    App::SuppressibleExtension::initExtension(this);
    Part::PreviewExtension::initExtension(this);
}

App::DocumentObjectExecReturn* Feature::recompute()
{
    // Held by the Body's roll-back bar (ops#127): not run on any path (also obj.recompute()); it
    // stays touched and runs when the bar passes it
    if (auto body = getFeatureBody(); body && body->holds(this)) {
        return App::DocumentObject::StdReturn;
    }

    setMaterialToBodyMaterial();

    if (Suppressed.getValue()) {
        if (auto doc = getDocument()) {
            doc->clearWarning(this);  // it computes nothing of its own (ops#127)
        }
        Shape.setValue(getBaseTopoShape(true));
        updateSuppressedShape();
        return App::DocumentObject::StdReturn;
    }

    SuppressedShape.setValue(TopoShape());

    // In a Body, an input in error fails the feature before it runs; the recompute's continuation
    // rule then passes its base shape through (ops#126). getFeatureBody() is the rule's own
    // membership test for a feature (FailureContinuation.cpp, bodyOf())
    if (getFeatureBody()) {
        std::string why;
        if (inputInError(this, why)) {
            return new App::DocumentObjectExecReturn(why, this);
        }
    }
    return Part::Feature::recompute();
}

App::DocumentObjectExecReturn* Feature::recomputePreview()
{
    updatePreviewShape();

    return StdReturn;
}

void Feature::setMaterialToBodyMaterial()
{
    auto body = getFeatureBody();
    if (body) {
        // Ensure the part has the same material as the body
        auto feature = dynamic_cast<Part::Feature*>(body);
        if (feature) {
            copyMaterial(feature);
        }
    }
}

void Feature::updateSuppressedShape()
{
    TopoShape res = makeTopoShape(false);
    TopoShape shape = Shape.getShape();
    shape.setPlacement(Base::Placement());
    std::vector<TopoShape> generated;
    if (!shape.isNull()) {
        unsigned count = shape.countSubShapes(TopAbs_FACE);
        for (unsigned i = 1; i <= count; ++i) {
            Data::MappedName mapped = shape.getMappedName(Data::IndexedName::fromConst("Face", i));
            if (mapped && shape.isElementGenerated(mapped)) {
                generated.push_back(shape.getSubTopoShape(TopAbs_FACE, i));
            }
        }
    }
    if (!generated.empty()) {
        res.makeElementCompound(generated);
        res.setPlacement(Placement.getValue());
    }
    SuppressedShape.setValue(res);
}

short Feature::mustExecute() const
{
    if (BaseFeature.isTouched()) {
        return 1;
    }
    return Part::Feature::mustExecute();
}

TopoShape Feature::makeResultShape(const TopoShape& base) const
{
    if (getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V1) {
        return TopoShape(base.Tag, base.Hasher, base.getHistoryAlgorithm());
    }
    return makeTopoShape(false);
}

TopoShape Feature::getSolid(const TopoShape& shape) const
{
    if (shape.isNull()) {
        throw Part::NullShapeException("Null shape 1");
    }

    // If single solid rule is not enforced  we simply return the shape as is
    if (singleSolidRuleMode() != Feature::SingleSolidRuleMode::Enforced) {
        return shape;
    }

    int count = shape.countSubShapes(TopAbs_SOLID);
    if (count) {
        auto res = shape.getSubTopoShape(TopAbs_SOLID, 1);
        res.fixSolidOrientation();
        return res;
    }

    return shape;
}

void Feature::onBaseFeatureRerouted(App::DocumentObject* /*oldBase*/, App::DocumentObject* /*newBase*/)
{}

namespace
{

// The relink in a reference solver document (ops#7, Task 2 PR 6): the link moves to the new base
// with every reference marked missing, keeping its old mapped name (the shadow) and its saved
// fingerprint, and the solver then resolves them against the new base. An index name never
// carries over from one shape to another: a reference is found exactly by its name (a 1:1
// modified element keeps its incoming name, so an edge the old base only trimmed is the new
// base's full edge), by the solver's evidence, or it breaks with its candidates reported.
// Returns false, leaving the link as it is, if a reference has no mapped name or a sub-object
// path, as the name match does.
bool relinkThroughSolver(
    App::PropertyLinkSub& link,
    const Part::TopoShape& oldShape,
    App::DocumentObject* newBase
)
{
    const auto& oldSubs = link.getSubValues();
    const auto& oldShadows = link.getShadowSubs();
    std::vector<std::string> subs;
    std::vector<App::PropertyLinkBase::ShadowSub> shadows;
    for (std::size_t i = 0; i < oldSubs.size(); ++i) {
        const auto& sub = oldSubs[i];
        if (sub.empty()) {
            subs.emplace_back();
            shadows.emplace_back();
            continue;
        }
        if (Data::findElementName(sub.c_str()) != sub.c_str()) {
            return false;
        }
        std::string mapped;
        std::string index;
        if (i < oldShadows.size()) {
            mapped = App::bareMappedName(oldShadows[i].newName);
            const char* element = Data::findElementName(oldShadows[i].oldName.c_str());
            index = element ? element : "";
            if (Data::hasMissingElement(index.c_str())) {
                index.erase(0, std::strlen(Data::MISSING_PREFIX));
            }
        }
        if (mapped.empty() || index.empty()) {
            Data::MappedElement element = oldShape.getElementName(sub.c_str());
            mapped = element.name.toString();
            index = element.index ? element.index.toString() : std::string();
        }
        if (mapped.empty() || index.empty()) {
            return false;
        }
        std::string missing = Data::MISSING_PREFIX + index;
        subs.push_back(missing);
        shadows.emplace_back(
            Data::ComplexGeoData::elementMapPrefix() + mapped + "." + index,
            missing
        );
    }
    link.setValue(newBase, std::move(subs), std::move(shadows));
    // A new base that hasn't computed yet (insert at the roll-back bar, ops#127): its first shape
    // solves the references, since a missing reference is solved on every update of its target
    auto newFeature = freecad_cast<Part::Feature*>(newBase);
    if (newFeature && !newFeature->Shape.getShape().isNull()) {
        App::solveElementReferences(newBase, {&link}, false, true);
    }
    return true;
}

}  // namespace

bool Feature::relinkToMatchingSubelements(
    App::PropertyLinkSub& link,
    App::DocumentObject* oldBase,
    App::DocumentObject* newBase
)
{
    if (!oldBase || !newBase || link.getValue() != oldBase) {
        return false;
    }

    auto oldFeature = freecad_cast<Part::Feature*>(oldBase);
    auto newFeature = freecad_cast<Part::Feature*>(newBase);
    if (!oldFeature || !newFeature) {
        return false;
    }

    const auto& oldShape = oldFeature->Shape.getShape();
    const auto& newShape = newFeature->Shape.getShape();
    if (oldShape.isNull()) {
        return false;
    }
    if (link.inSolverDocument()) {
        // Also onto a new base without a shape yet (ops#127, N1 2.2)
        return relinkThroughSolver(link, oldShape, newBase);
    }
    if (newShape.isNull()) {
        return false;
    }

    const auto& oldSubs = link.getSubValues();
    std::vector<std::string> newSubs;
    newSubs.reserve(oldSubs.size());

    const App::HistoryAlgorithm& selectedHistoryAlgorithm = oldFeature->getSelectedHistoryAlgorithm();

    for (const auto& sub : oldSubs) {
        if (sub.empty()) {
            newSubs.emplace_back();
            continue;
        }

        Data::MappedElement subMappedElement = oldShape.getElementName(sub.c_str());

        if (!subMappedElement.index) {
            return false;
        }

        std::pair<TopAbs_ShapeEnum, int> subDecodedIndexedName = Part::TopoShape::shapeTypeAndIndex(
            subMappedElement.index
        );
        if (subDecodedIndexedName.second <= 0) {
            return false;
        }

        auto oldSubShape = oldShape.getSubTopoShape(
            subDecodedIndexedName.first,
            subDecodedIndexedName.second,
            true
        );

        if (oldSubShape.isNull()) {
            return false;
        }

        std::vector<std::string> names;

        if (selectedHistoryAlgorithm == App::HistoryAlgorithm::V1) {
            auto matches = newShape.findSubShapesWithSharedVertex(
                oldSubShape,
                &names,
                Data::SearchOption::CheckGeometry
            );

            if (matches.size() != 1) {
                return false;
            }
        }
        else if (selectedHistoryAlgorithm == App::HistoryAlgorithm::V2) {
            std::vector<Data::MappedElement> foundNames
                = findSimilarNames(subMappedElement.name, newShape);

            if (foundNames.size()) {
                names.push_back(foundNames.front().name.toString());
            }

            if (foundNames.size() > 1) {
                FC_WARN(
                    link.getFullName() << ": guessed the relinked reference "
                                  << sub << " -> " << foundNames.front().index.toString()
                                  << ", the first of " << foundNames.size()
                                  << " matching elements of " << newFeature->getFullName()
                );
            }
        }

        if (names.size() != 1) {
            return false;
        }

        newSubs.push_back(names.front());
    }

    link.setValue(newBase, std::move(newSubs));
    return true;
}

void Feature::onChanged(const App::Property* prop)
{
    if (!this->isRestoring() && this->getDocument()
        && !this->getDocument()->isPerformingTransaction()) {
        // Setting BaseFeature doesn't reorder the Body (ops#77). Upstream had a reorder here that
        // never ran: it looked the base's index up into the feature's. Turned on, it would have
        // fired for nearly every new feature (the sketch between a feature and its base counts in
        // Group), and Body::insertObject would have listed the base twice.
        if (prop == &ShapeMaterial) {
            auto body = Body::findBodyOf(this);
            if (body) {
                if (body->ShapeMaterial.getValue().getUUID() != ShapeMaterial.getValue().getUUID()) {
                    body->ShapeMaterial.setValue(ShapeMaterial.getValue());
                }
            }
        }
        else if (prop == &Suppressed) {
            if (Suppressed.getValue()) {
                SuppressedPlacement = Placement.getValue();
                updateSuppressedShape();
            }
            else {
                Placement.setValue(SuppressedPlacement);
                SuppressedPlacement = Base::Placement();
            }
        }
    }
    Part::Feature::onChanged(prop);
}

int Feature::countSolids(const TopoDS_Shape& shape, TopAbs_ShapeEnum type)
{
    int result = 0;
    if (shape.IsNull()) {
        return result;
    }
    TopExp_Explorer xp;
    xp.Init(shape, type);
    for (; xp.More(); xp.Next()) {
        result++;
    }
    return result;
}

TopoShape Feature::fixSolids(const TopoShape& solids)
{
    if (solids.isNull()) {
        return solids;
    }

    std::vector<TopoDS_Solid> fixSolids;

    TopExp_Explorer xp;
    xp.Init(solids.getShape(), TopAbs_SOLID);
    for (; xp.More(); xp.Next()) {
        TopoDS_Solid solid = TopoDS::Solid(xp.Current());
        BRepCheck_Solid bs(solid);
        if (bs.IsStatusOnShape(solid)) {
            const auto& listOfStatus = bs.StatusOnShape(solid);
            if (listOfStatus.Contains(BRepCheck_EnclosedRegion)) {
                fixSolids.emplace_back(solid);
            }
        }
    }

    if (fixSolids.empty()) {
        return solids;
    }

    TopoDS_Compound comp;
    TopoDS_Builder bb;
    bb.MakeCompound(comp);
    for (const TopoDS_Solid& it : fixSolids) {
        ShapeFix_Solid fix(it);
        fix.Perform();
        bb.Add(comp, fix.Solid());
    }

    TopoShape fixShape = makeTopoShape(comp);
    return fixShape;
}

bool Feature::isSingleSolidRuleSatisfied(const TopoDS_Shape& shape, TopAbs_ShapeEnum type)
{
    if (singleSolidRuleMode() == Feature::SingleSolidRuleMode::Disabled) {
        return true;
    }

    int solidCount = countSolids(shape, type);

    return solidCount <= 1;
}


Feature::SingleSolidRuleMode Feature::singleSolidRuleMode() const
{
    auto body = getFeatureBody();

    // When the feature is not part of an body (which should not happen) let's stay with the default
    if (!body) {
        return SingleSolidRuleMode::Enforced;
    }

    auto areCompoundSolidsAllowed = body->AllowCompound.getValue();

    return areCompoundSolidsAllowed ? SingleSolidRuleMode::Disabled : SingleSolidRuleMode::Enforced;
}

const gp_Pnt Feature::getPointFromFace(const TopoDS_Face& f)
{
    if (!f.Infinite()) {
        TopExp_Explorer exp;
        exp.Init(f, TopAbs_VERTEX);
        if (exp.More()) {
            return BRep_Tool::Pnt(TopoDS::Vertex(exp.Current()));
        }
        // Else try the other method
    }

    // TODO: Other method, e.g. intersect X,Y,Z axis with the (unlimited?) face?
    // Or get a "corner" point if the face is limited?
    throw Base::NotImplementedError("getPointFromFace(): Not implemented yet for this case");
}

Part::Feature* Feature::getBaseObject(bool silent) const
{
    App::DocumentObject* BaseLink = BaseFeature.getValue();
    Part::Feature* BaseObject = nullptr;
    const char* err = nullptr;

    if (BaseLink) {
        if (BaseLink->isDerivedFrom<Part::Feature>()) {
            BaseObject = static_cast<Part::Feature*>(BaseLink);
        }
        if (!BaseObject) {
            err = "No base feature linked";
        }
    }
    else {
        err = "Base property not set";
    }

    // If the function not in silent mode throw the exception describing the error
    if (!silent && err) {
        throw Base::RuntimeError(err);
    }

    return BaseObject;
}

const TopoDS_Shape& Feature::getBaseShape() const
{
    const Part::Feature* BaseObject = getBaseObject();

    if (!BaseObject) {
        throw Base::ValueError("Base feature's shape is not defined");
    }

    if (BaseObject->isDerivedFrom<PartDesign::ShapeBinder>()
        || BaseObject->isDerivedFrom<PartDesign::SubShapeBinder>()) {
        throw Base::ValueError("Base shape of shape binder cannot be used");
    }

    const TopoDS_Shape& result = BaseObject->Shape.getValue();
    if (result.IsNull()) {
        throw Base::ValueError("Base feature's shape is invalid");
    }
    TopExp_Explorer xp(result, TopAbs_SOLID);
    if (!xp.More()) {
        throw Base::ValueError("Base feature's shape is not a solid");
    }

    return result;
}

Part::TopoShape Feature::getBaseTopoShape(bool silent) const
{
    Part::TopoShape result = makeTopoShape(false);

    const Part::Feature* BaseObject = getBaseObject(silent);
    if (!BaseObject) {
        return result;
    }

    if (BaseObject != BaseFeature.getValue()) {
        if (BaseObject->isDerivedFrom<PartDesign::ShapeBinder>()
            || BaseObject->isDerivedFrom<PartDesign::SubShapeBinder>()) {
            if (silent) {
                return result;
            }
            throw Base::ValueError("Base shape of shape binder cannot be used");
        }
    }

    result = BaseObject->Shape.getShape();
    if (!silent) {
        if (result.isNull()) {
            throw Base::ValueError("Base feature's TopoShape is invalid");
        }
        if (!result.hasSubShape(TopAbs_SOLID)) {
            throw Base::ValueError("Base feature's shape is not a solid");
        }
    }
    else if (!result.hasSubShape(TopAbs_SOLID)) {
        result.setShape(TopoDS_Shape());
    }
    return result;
}

Part::TopoShape Feature::getTopoShapeInLocalCoordinates(const App::DocumentObject* object) const
{
    if (!object) {
        return {};
    }

    auto body = getFeatureBody();
    const bool isSameBodyFeature = body && object->isDerivedFrom<PartDesign::Feature>()
        && PartDesign::Body::findBodyOf(object) == body;

    if (isSameBodyFeature) {
        return static_cast<const Part::Feature*>(object)->Shape.getShape();
    }

    Part::ShapeOptions options = Part::ShapeOption::ResolveLink;
    if (!body) {
        return Part::Feature::getTopoShape(object, options | Part::ShapeOption::Transform);
    }

    Base::Matrix4D shapePlacement;
    auto shape = Part::Feature::getTopoShape(object, options, nullptr, &shapePlacement);
    if (!shape.isNull()) {
        Base::Matrix4D placement = getDisplayedObjectPlacement(body).inverse().toMatrix();
        placement *= getDisplayedObjectPlacement(object).toMatrix();
        placement *= shapePlacement;
        shape.transformShape(placement, false, true);
    }
    return shape;
}

void Feature::getGeneratedShapes(
    std::vector<int>& faces,
    std::vector<int>& edges,
    std::vector<int>& vertices
) const
{
    static const auto addAllSubShapesToSet = [](const Part::TopoShape& shape,
                                                const Part::TopoShape& face,
                                                TopAbs_ShapeEnum type,
                                                std::set<int>& set) {
        for (auto& subShape : face.getSubShapes(type)) {
            if (int subShapeId = shape.findShape(subShape); subShapeId > 0) {
                set.insert(subShapeId);
            }
        }
    };

    Part::TopoShape shape = Shape.getShape();

    std::set<int> edgeSet;
    std::set<int> vertexSet;

    int count = shape.countSubShapes(TopAbs_FACE);

    for (int faceId = 1; faceId <= count; ++faceId) {
        if (Data::MappedName mapped = shape.getMappedName(Data::IndexedName::fromConst("Face", faceId));
            shape.isElementGenerated(mapped)) {
            faces.push_back(faceId);

            Part::TopoShape face = shape.getSubTopoShape(TopAbs_FACE, faceId);

            addAllSubShapesToSet(shape, face, TopAbs_EDGE, edgeSet);
            addAllSubShapesToSet(shape, face, TopAbs_VERTEX, vertexSet);
        }
    }

    std::ranges::copy(edgeSet, std::back_inserter(edges));
    std::ranges::copy(vertexSet, std::back_inserter(vertices));
}

void Feature::updatePreviewShape()
{
    // no-op
}

PyObject* Feature::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new FeaturePy(this), true);
    }
    return Py::new_reference_to(PythonObject);
}

bool Feature::isDatum(const App::DocumentObject* feature)
{
    return feature->isDerivedFrom<App::DatumElement>() || feature->isDerivedFrom<Part::Datum>();
}

gp_Pln Feature::makePlnFromPlane(const App::DocumentObject* obj)
{
    const App::GeoFeature* plane = static_cast<const App::GeoFeature*>(obj);
    if (!plane) {
        throw Base::ValueError("Feature: Null object");
    }

    Base::Vector3d pos = plane->Placement.getValue().getPosition();
    Base::Rotation rot = plane->Placement.getValue().getRotation();
    Base::Vector3d normal(0, 0, 1);
    rot.multVec(normal, normal);
    return gp_Pln(gp_Pnt(pos.x, pos.y, pos.z), gp_Dir(normal.x, normal.y, normal.z));
}

// TODO: Toponaming April 2024 Deprecated in favor of TopoShape method.  Remove when possible.
TopoDS_Shape Feature::makeShapeFromPlane(const App::DocumentObject* obj)
{
    BRepBuilderAPI_MakeFace builder(makePlnFromPlane(obj));
    if (!builder.IsDone()) {
        throw Base::CADKernelError("Feature: Could not create shape from base plane");
    }

    return builder.Shape();
}

TopoShape Feature::makeTopoShapeFromPlane(const App::DocumentObject* obj)
{
    BRepBuilderAPI_MakeFace builder(makePlnFromPlane(obj));
    if (!builder.IsDone()) {
        throw Base::CADKernelError("Feature: Could not create shape from base plane");
    }

    return Feature::makeTopoShape(obj, builder.Shape(), 0, false);
}

Body* Feature::getFeatureBody() const
{

    auto body = freecad_cast<Body*>(_Body.getValue());
    if (body) {
        return body;
    }

    auto list = getInList();
    for (auto in : list) {
        if (in->isDerivedFrom<Body>() &&                // is Body?
            static_cast<Body*>(in)->hasObject(this)) {  // is part of this Body?

            return static_cast<Body*>(in);
        }
    }

    return nullptr;
}

App::DocumentObject* Feature::getSubObject(
    const char* subname,
    PyObject** pyObj,
    Base::Matrix4D* pmat,
    bool transform,
    int depth
) const
{
    if (subname && subname != Data::findElementName(subname)) {
        const char* dot = strchr(subname, '.');
        if (dot) {
            auto body = PartDesign::Body::findBodyOf(this);
            if (body) {
                auto feat = body->Group.findUsingMap(std::string(subname, dot));
                if (feat) {
                    Base::Matrix4D _mat;
                    if (!transform) {
                        // Normally the parent object is supposed to transform
                        // the sub-object using its own placement. So, if no
                        // transform is requested, (i.e. no parent
                        // transformation), we just need to NOT apply the
                        // transformation.
                        //
                        // But PartDesign features (including sketch) are
                        // supposed to be contained inside a body. It makes
                        // little sense to transform its sub-object. So if 'no
                        // transform' is requested, we need to actively apply
                        // an inverse transform.
                        _mat = Placement.getValue().inverse().toMatrix();
                        if (pmat) {
                            *pmat *= _mat;
                        }
                        else {
                            pmat = &_mat;
                        }
                    }
                    return feat->getSubObject(dot + 1, pyObj, pmat, true, depth + 1);
                }
            }
        }
    }
    return Part::Feature::getSubObject(subname, pyObj, pmat, transform, depth);
}


}  // namespace PartDesign

namespace App
{
/// @cond DOXERR
PROPERTY_SOURCE_TEMPLATE(PartDesign::FeaturePython, PartDesign::Feature)
template<>
const char* PartDesign::FeaturePython::getViewProviderName() const
{
    return "PartDesignGui::ViewProviderPython";
}
template<>
PyObject* PartDesign::FeaturePython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new FeaturePythonPyT<PartDesign::FeaturePy>(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
/// @endcond

// explicit template instantiation
template class PartDesignExport FeaturePythonT<PartDesign::Feature>;
}  // namespace App
