// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2013 Jan Rheinländer <jrheinlaender@users.sourceforge.net> *
 *                                                                            *
 *   This file is part of the FreeCAD CAx development system.                 *
 *                                                                            *
 *   This library is free software; you can redistribute it and/or            *
 *   modify it under the terms of the GNU Library General Public              *
 *   License as published by the Free Software Foundation; either             *
 *   version 2 of the License, or (at your option) any later version.         *
 *                                                                            *
 *   This library  is distributed in the hope that it will be useful,         *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of           *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            *
 *   GNU Library General Public License for more details.                     *
 *                                                                            *
 *   You should have received a copy of the GNU Library General Public        *
 *   License along with this library; see the file COPYING.LIB. If not,       *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,            *
 *   Suite 330, Boston, MA  02111-1307, USA                                   *
 *                                                                            *
 ******************************************************************************/


#include <Mod/Part/App/FCBRepAlgoAPI_Common.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Cut.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <Standard_Failure.hxx>

#include <algorithm>
#include <cmath>

#include <BRepBndLib.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <Precision.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Pnt.hxx>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/PropertyLinks.h>
#include <App/SuppressibleExtension.h>
#include <Base/Tools.h>
#include <Mod/Part/App/modelRefine.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "FeatureBoolean.h"
#include "Body.h"
#include "FeatureSketchBased.h"
#include "StudioList.h"
#include "StudioOwner.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true);

using namespace PartDesign;

namespace PartDesign
{
extern bool getPDRefineModelParameter();

PROPERTY_SOURCE_WITH_EXTENSIONS(PartDesign::Boolean, PartDesign::FeatureRefine)

const char* Boolean::TypeEnums[] = {"Fuse", "Cut", "Common", nullptr};

Boolean::Boolean()
{
    ADD_PROPERTY(Type, ((long)0));
    Type.setEnums(TypeEnums);
    ADD_PROPERTY_TYPE(
        UseLegacyBodyPlacement,
        (App::GetApplication().isRestoring()),
        "Compatibility",
        App::Prop_Hidden,
        "Use legacy PartDesign Boolean body placement handling"
    );
    // The last Keep tools the dialog accepted (FreeCAD-CH ops#640 rank 28, hands-on A-5); a
    // restored Boolean reads its own, and one saved without it reads false
    const bool keepTools = !App::GetApplication().isRestoring()
        && App::GetApplication()
               .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/PartDesign")
               ->GetBool("BooleanKeepTools", false);
    ADD_PROPERTY_TYPE(
        KeepTools,
        (keepTools),
        "Boolean",
        App::Prop_None,
        "Keep the tool parts: off, the Boolean consumes them (Onshape's Keep tools)"
    );
    ADD_PROPERTY_TYPE(
        SeparateTools,
        (nullptr),
        "Boolean",
        static_cast<App::PropertyType>(App::Prop_Output | App::Prop_Hidden),
        "The tools a Union left as they were: they touch nothing it fuses, and stay parts"
    );
    // FreeCAD-CH ops#654 (P5)
    ADD_PROPERTY_TYPE(StudioTools, (), "Studio", App::Prop_Hidden, "The tool parts, by part id");

    App::GeoFeatureGroupExtension::initExtension(this);
    // Boolean tools are references, not owned coordinate-system children.
    Group.setScope(App::LinkScope::Global);
}

namespace
{
// A Merge's saved toolFrames() from its last compute (FreeCAD-CH ops#325, PR 305 round 1)
constexpr const char* mergeFrames = "MergeFrames";

// Whether two shapes share a point: in contact, or one inside the other (FreeCAD-CH ops#640
// rank 3b: a Union fuses what touches)
bool shapesTouch(const TopoShape& one, const TopoShape& other)
{
    Bnd_Box oneBox;
    Bnd_Box otherBox;
    BRepBndLib::Add(one.getShape(), oneBox, /*useTriangulation=*/false);
    BRepBndLib::Add(other.getShape(), otherBox, /*useTriangulation=*/false);
    oneBox.Enlarge(Precision::Confusion());
    if (oneBox.IsOut(otherBox)) {
        return false;
    }
    BRepExtrema_DistShapeShape distance(one.getShape(), other.getShape());
    if (distance.IsDone() && distance.Value() <= Precision::Confusion()) {
        return true;
    }
    // Surfaces apart: one solid may still hold the other whole
    auto inside = [](const TopoShape& inner, const TopoShape& outer) {
        TopExp_Explorer vertex(inner.getShape(), TopAbs_VERTEX);
        if (!vertex.More()) {
            return false;
        }
        const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(vertex.Current()));
        for (TopExp_Explorer solid(outer.getShape(), TopAbs_SOLID); solid.More(); solid.Next()) {
            BRepClass3d_SolidClassifier classifier(solid.Current(), point, Precision::Confusion());
            if (classifier.State() == TopAbs_IN) {
                return true;
            }
        }
        return false;
    };
    return inside(one, other) || inside(other, one);
}

double volumeOf(const TopoShape& shape)
{
    GProp_GProps props;
    BRepGProp::VolumeProperties(shape.getShape(), props);
    return props.Mass();
}

// Whether the tools left the base's volume as it was: judged by volume, as an Extrude's Remove
// that misses (FeatureExtrude's cutMissed), so a tool that only shares a face with the base
// counts. The tolerance scales with the tools plus the base's own rounding
bool unchangedBy(const TopoShape& base, const std::vector<TopoShape>& tools, const TopoShape& result)
{
    double toolVolume = 0.0;
    for (const auto& tool : tools) {
        toolVolume += std::fabs(volumeOf(tool));
    }
    const double baseVolume = volumeOf(base);
    const double tolerance = 1e-6 * toolVolume + 1e-9 * std::fabs(baseVolume);
    return std::fabs(volumeOf(result) - baseVolume) <= tolerance;
}
}  // namespace

short Boolean::mustExecute() const
{
    if (Group.isTouched() || UseLegacyBodyPlacement.isTouched() || KeepTools.isTouched()
        || StudioTools.isTouched()) {
        return 1;
    }
    // A merged part moved: nothing it links changed, and the Body isn't linked (FreeCAD-CH
    // ops#325, M-t6)
    if (isMerge()) {
        const std::vector<Base::Placement> frames = toolFrames();
        if (frames.size() != lastToolFrames.size()
            || !std::ranges::equal(frames, lastToolFrames, [](const auto& one, const auto& other) {
                   return one.isSame(other, Precision::Confusion());
               })) {
            return 1;
        }
    }
    return PartDesign::Feature::mustExecute();
}

TopoShape Boolean::getBooleanTopoShape(const App::DocumentObject* object) const
{
    if (UseLegacyBodyPlacement.getValue()) {
        return getTopoShape(object, Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform);
    }
    return getTopoShapeInLocalCoordinates(object);
}

std::vector<App::DocumentObject*> Boolean::addObject(App::DocumentObject* object)
{
    return addObjects({object});
}

std::vector<App::DocumentObject*> Boolean::addObjects(std::vector<App::DocumentObject*> objects)
{
    auto tools = Group.getValues();
    std::vector<App::DocumentObject*> added;

    for (auto object : objects) {
        if (!object || std::ranges::find(tools, object) != tools.end()) {
            continue;
        }

        tools.push_back(object);
        added.push_back(object);
    }

    Base::ObjectStatusLocker<App::Property::Status, App::Property> guard(App::Property::User3, &Group);
    Group.setValues(tools);
    return added;
}

std::vector<App::DocumentObject*> Boolean::setObjects(std::vector<App::DocumentObject*> objects)
{
    std::vector<App::DocumentObject*> tools;
    std::vector<App::DocumentObject*> added;

    for (auto object : objects) {
        if (!object || std::ranges::find(tools, object) != tools.end()) {
            continue;
        }

        tools.push_back(object);
        added.push_back(object);
    }

    Base::ObjectStatusLocker<App::Property::Status, App::Property> guard(App::Property::User3, &Group);
    Group.setValues(tools);
    return added;
}

std::vector<App::DocumentObject*> Boolean::removeObject(App::DocumentObject* object)
{
    return removeObjects({object});
}

std::vector<App::DocumentObject*> Boolean::removeObjects(std::vector<App::DocumentObject*> objects)
{
    auto tools = Group.getValues();
    std::vector<App::DocumentObject*> removed;

    for (auto object : objects) {
        auto it = std::ranges::find(tools, object);
        if (it == tools.end()) {
            continue;
        }

        removed.push_back(object);
        tools.erase(it);
    }

    Base::ObjectStatusLocker<App::Property::Status, App::Property> guard(App::Property::User3, &Group);
    Group.setValues(tools);
    return removed;
}

bool Boolean::hasObject(const App::DocumentObject* /*object*/, bool /*recursive*/) const
{
    // Boolean tools are references, not owned children. Returning false keeps
    // GeoFeatureGroupExtension from using this object as their coordinate system.
    return false;
}

// StudioList.cpp and StudioOwner.cpp (FreeCAD-CH ops#654 P5; declared where used)
PartDesignExport void studioBooleanParts(const App::DocumentObject* owner,
                                         std::vector<Body*>& steps,
                                         std::vector<Body*>& tools,
                                         std::vector<Body*>& both);
PartDesignExport Part::TopoShape studioBooleanTool(const App::DocumentObject* owner, std::string* why);

namespace
{
std::string quotedLabel(const App::DocumentObject* obj)
{
    return std::string("'") + (obj ? obj->Label.getValue() : "?") + "'";
}

/** A Boolean studio feature (FreeCAD-CH ops#654 P5, Onshape O3): outside every Body, its targets
 * are its StudioScope and its tools its StudioTools (part ids). It computes nothing of its own:
 * its steps (one in each target of a Subtract, one in the first part of a Union) apply its tool,
 * the tool parts' shapes at its place (FeatureApply::toolOf). Here it checks what it would act on
 * and fails loudly, its own shape empty:
 * - Intersect between parts makes a new part in Onshape, which waits for pieces (P6p);
 * - no target or no tool part left at its place ("Need at least one solid": a pick of a part
 *   consumed or merged away resolves to nothing, O9b / F2);
 * - a part that is a target and a tool.
 */
App::DocumentObjectExecReturn* executeStudioBoolean(Boolean& boolean)
{
    boolean.Shape.setValue(Part::TopoShape());
    if (!boolean.SeparateTools.getValues().empty()) {
        boolean.SeparateTools.setValues(std::vector<App::DocumentObject*>());
    }
    const std::string type = boolean.Type.getValueAsString();
    if (type == "Common") {
        return new App::DocumentObjectExecReturn(
            "An Intersect between parts makes a new part, which is not done yet: use Subtract "
            "or Union, or an Intersect inside one part",
            &boolean
        );
    }
    // A Union's tool parts that touch none of the parts it merges stay parts (P6p, Onshape A-2'
    // b): decided here, from every tool listed, and read by the projection after the recompute
    // (StudioApartTools, as the part mirror's StudioConsumesSource)
    auto apart = freecad_cast<App::PropertyStringList*>(boolean.getPropertyByName("StudioApartTools"));
    if (!apart) {
        apart = static_cast<App::PropertyStringList*>(boolean.addDynamicProperty(
            "App::PropertyStringList",
            "StudioApartTools",
            "Studio",
            "The Union's tool parts that touch none of the parts it merges (ops#654 P6p)",
            App::Prop_Hidden | App::Prop_Output | App::Prop_NoRecompute
        ));
    }
    if (!apart->getValues().empty()) {
        apart->setValues(std::vector<std::string>());
    }
    std::vector<Body*> steps;
    std::vector<Body*> tools;
    std::vector<Body*> both;
    studioBooleanParts(&boolean, steps, tools, both);
    if (type == "Fuse" && !steps.empty() && !tools.empty()) {
        std::vector<Part::TopoShape> merged;
        if (Part::TopoShape first = studioBaseAt(&boolean, steps.front()); !first.isNull()) {
            merged.push_back(first);
        }
        std::vector<std::pair<Body*, Part::TopoShape>> rest;
        for (auto tool : tools) {
            rest.emplace_back(tool, studioBaseAt(&boolean, tool));
        }
        auto touchesMerged = [&merged](const Part::TopoShape& shape) {
            return std::ranges::any_of(merged, [&shape](const Part::TopoShape& other) {
                BRepExtrema_DistShapeShape distance(shape.getShape(), other.getShape());
                return distance.IsDone() && distance.Value() <= Precision::Confusion();
            });
        };
        for (bool grew = !merged.empty(); grew;) {
            grew = false;
            for (auto it = rest.begin(); it != rest.end();) {
                if (!it->second.isNull() && touchesMerged(it->second)) {
                    merged.push_back(it->second);
                    it = rest.erase(it);
                    grew = true;
                }
                else {
                    ++it;
                }
            }
        }
        std::vector<std::string> ids;
        for (const auto& [tool, shape] : rest) {
            if (!shape.isNull()) {
                ids.push_back(studioPartId(tool));
            }
        }
        if (!ids.empty() && ids.size() == tools.size()) {
            apart->setValues(ids);  // none consumed (unverified on Onshape: loud)
            return new App::DocumentObjectExecReturn(
                "No tool part touches " + quotedLabel(steps.front())
                    + ": a Union merges parts that touch",
                &boolean
            );
        }
        if (!ids.empty()) {
            apart->setValues(ids);
            studioBooleanParts(&boolean, steps, tools, both);
        }
    }
    if (!both.empty()) {
        return new App::DocumentObjectExecReturn(
            quotedLabel(both.front()) + " is a target and a tool of this Boolean",
            &boolean
        );
    }
    if (type == "Fuse") {
        if (steps.size() + tools.size() < 2) {
            return new App::DocumentObjectExecReturn(
                "Need at least two parts to merge: the Union's parts are gone, merged or consumed "
                "at its place",
                &boolean
            );
        }
    }
    else if (steps.empty()) {
        return new App::DocumentObjectExecReturn(
            "Need at least one target part: the Subtract's targets are gone, merged or consumed "
            "at its place",
            &boolean
        );
    }
    else if (tools.empty()) {
        return new App::DocumentObjectExecReturn(
            "Need at least one tool part: the Subtract's tools are gone, merged or consumed at "
            "its place",
            &boolean
        );
    }
    std::string why;
    if (studioBooleanTool(&boolean, &why).isNull()) {
        return new App::DocumentObjectExecReturn(why, &boolean);
    }
    return App::DocumentObject::StdReturn;
}
}  // namespace

App::DocumentObjectExecReturn* Boolean::execute()
{
    if (runsAsStudioOwner(this)) {
        return executeStudioBoolean(*this);
    }

    // Get the operation type
    std::string type = Type.getValueAsString();

    // Check the parameters
    const Part::Feature* baseFeature = this->getBaseObject(/* silent = */ true);

    if (!baseFeature && type == "Cut") {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Cannot do boolean cut without BaseFeature")
        );
    }

    // A Merge's tools are its absorbed parts' merged features (FreeCAD-CH ops#325)
    if (isMerge()) {
        lastToolFrames = toolFrames();
        auto saved = freecad_cast<App::PropertyPlacementList*>(getPropertyByName(mergeFrames));
        if (saved && saved->getValues() != lastToolFrames) {
            saved->setValues(lastToolFrames);
        }
        if (std::string why = mergeProblem(); !why.empty()) {
            return new App::DocumentObjectExecReturn(why, this);
        }
    }

    std::vector<App::DocumentObject*> tools = Group.getValues();
    if (tools.empty()) {
        // Being set up: before its first tool (its command runs it once before the panel opens)
        // or in its panel. Otherwise its tools are gone (e.g. the tool Body was deleted), and
        // keeping the old result would show them silently (FreeCAD-CH ops#314); failing passes
        // the base shape through (ops#126)
        if (settingUp || Shape.getShape().isNull()) {
            return App::DocumentObject::StdReturn;
        }
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Boolean has no tools: add a Body to its list")
        );
    }

    // Get the base shape to operate on
    Part::TopoShape baseTopShape = makeTopoShape(false);
    if (baseFeature) {
        if (UseLegacyBodyPlacement.getValue()) {
            baseTopShape = baseFeature->Shape.getShape();
        }
        else {
            baseTopShape = getBooleanTopoShape(baseFeature);
        }
    }
    else {
        auto feature = tools.back();
        if (!feature->isDerivedFrom<Part::Feature>()) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Cannot do boolean with anything but Part::Feature and its derivatives"
            ));
        }

        if (UseLegacyBodyPlacement.getValue()) {
            baseTopShape = static_cast<Part::Feature*>(feature)->Shape.getShape();
        }
        else {
            baseTopShape = getBooleanTopoShape(feature);
        }
        tools.pop_back();
    }

    if (baseTopShape.getShape().IsNull()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Cannot do boolean operation with invalid base shape")
        );
    }

    std::vector<TopoShape> shapes;
    shapes.push_back(baseTopShape);
    for (auto it = tools.begin(); it < tools.end(); ++it) {
        auto shape = getBooleanTopoShape(*it);
        if (shape.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Tool shape is null")
            );
        }
        shapes.push_back(shape);
    }

    // Onshape's Union, Subtract and Intersect (FreeCAD-CH ops#640 rank 3b): a Merge keeps its own
    // rules (ops#325)
    const bool plain = !isMerge();
    const bool hadTools = !tools.empty();
    std::vector<App::DocumentObject*> separate;
    if (plain && type == "Fuse" && hadTools) {
        // A Union fuses what touches the base, directly or through another tool it fuses; a tool
        // apart from all of it stays a part of its own (hands-on A-2' b)
        std::vector<bool> joined(tools.size(), false);
        {
            std::vector<const TopoShape*> fused {&shapes.front()};
            for (bool grew = true; grew;) {
                grew = false;
                for (std::size_t i = 0; i < tools.size(); ++i) {
                    const TopoShape& tool = shapes[i + 1];
                    if (!joined[i] && std::ranges::any_of(fused, [&tool](const TopoShape* shape) {
                            return shapesTouch(tool, *shape);
                        })) {
                        joined[i] = true;
                        fused.push_back(&tool);
                        grew = true;
                    }
                }
            }
        }
        std::vector<TopoShape> joinedShapes {shapes.front()};
        std::vector<App::DocumentObject*> joinedTools;
        for (std::size_t i = 0; i < tools.size(); ++i) {
            if (joined[i]) {
                joinedShapes.push_back(shapes[i + 1]);
                joinedTools.push_back(tools[i]);
            }
            else {
                separate.push_back(tools[i]);
            }
        }
        shapes = std::move(joinedShapes);
        tools = std::move(joinedTools);
    }
    if (SeparateTools.getValues() != separate) {
        SeparateTools.setValues(separate);
    }
    // A Subtract or an Intersect whose tools are all apart from the base changes nothing; the
    // boolean isn't run (B3-3a, A-2' c)
    bool apart = false;
    if (plain && hadTools && (type == "Cut" || type == "Common")) {
        auto touchesBase = [&shapes](const TopoShape& tool) {
            return shapesTouch(tool, shapes.front());
        };
        apart = type == "Cut" ? std::none_of(shapes.begin() + 1, shapes.end(), touchesBase)
                              : !std::all_of(shapes.begin() + 1, shapes.end(), touchesBase);
    }

    TopoShape result(baseTopShape);

    if (!tools.empty() && !apart) {
        const char* op = nullptr;

        if (type == "Fuse") {
            op = Part::OpCodes::Fuse;
        }
        else if (type == "Cut") {
            op = Part::OpCodes::Cut;
        }
        else if (type == "Common") {
            op = Part::OpCodes::Common;
        }
        // LinkStage3 defines these other types of Boolean operations.  Removed for now pending
        // decision to bring them in or not.
        // else if(type == "Compound")
        //     op = Part::OpCodes::Compound;
        // else if(type == "Section")
        //     op = Part::OpCodes::Section;
        else {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Unsupported boolean operation")
            );
        }

        try {
            // Without a BaseFeature, the base is a tool Body's shape, and booleanInputCheck()
            // checks it
            result = makeResultShape(baseTopShape)
                         .makeElementBoolean(
                             op,
                             shapes,
                             nullptr,
                             FuzzyTolerance.getValue(),
                             Part::ElementMapPolicy::Propagate,
                             booleanInputCheck(),
                             &booleanInputsValid
                         );
        }
        catch (Standard_Failure& e) {
            FC_ERR("Boolean operation failed: " << e.GetMessageString());
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Boolean operation failed")
            );
        }
    }

    // What Onshape says, or leaves, when a Boolean changes nothing (ops#640 rank 3b)
    std::string note;
    if (plain && hadTools) {
        std::vector<TopoShape> toolShapes(shapes.begin() + 1, shapes.end());
        if (type == "Common" && (apart || result.countSubShapes(TopAbs_SOLID) == 0)) {
            // An Intersect that misses leaves nothing, with no message (hands-on A-2' c); with Keep
            // tools, the part as it was
            if (!KeepTools.getValue()) {
                TopoDS_Compound empty;
                BRep_Builder builder;
                builder.MakeCompound(empty);
                this->Shape.setValue(makeTopoShape(empty));
                return StdReturn;
            }
            result = baseTopShape;
        }
        else if (type == "Cut" && (apart || unchangedBy(baseTopShape, toolShapes, result))) {
            // The target as it was, the tools consumed: an info, the row healthy (B3-3a)
            note = "Selected tools and targets do not intersect.";
        }
        else if (type == "Fuse" && (tools.empty() || unchangedBy(baseTopShape, toolShapes, result))) {
            // Nothing touched, or every tool inside the base (A-2' b)
            note = "Boolean resulted in no geometry change. The parts either do not intersect or "
                   "are totally contained.";
        }
    }

    result = refineShapeIfActive(result);

    if (!isSingleSolidRuleSatisfied(result.getShape())) {
        return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
            "Exception",
            "Result has multiple solids: enable 'Allow Compound' in the active body."
        ));
    }

    this->Shape.setValue(getSolid(result));
    warnMerged();
    if (!note.empty()) {
        if (App::Document* doc = getDocument()) {
            const char* previous = doc->getWarningDescription(this);
            doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + note : note);
        }
    }

    return StdReturn;
}

void Boolean::updatePreviewShape()
{
    // A studio feature (ops#654 P5) has no base: its steps show what it does
    if (runsAsStudioOwner(this)) {
        PreviewShape.setValue(Part::TopoShape());
        return;
    }
    if (strcmp(Type.getValueAsString(), "Cut") == 0) {
        TopoShape base;
        if (UseLegacyBodyPlacement.getValue()) {
            base = getBaseTopoShape(true);
            base.move(getInverseLocation(base));
        }
        else {
            base = getBooleanTopoShape(BaseFeature.getValue());
        }
        TopoShape result = Shape.getShape();

        try {
            PreviewShape.setValue(base.makeElementCut(result.getShape()));
        }
        catch (Standard_Failure& e) {
            FC_ERR("Boolean preview failed: " << e.GetMessageString());
            PreviewShape.setValue(base);
        }
        catch (Base::Exception& e) {
            FC_ERR("Boolean preview failed: " << e.what());
            PreviewShape.setValue(base);
        }
        return;
    }

    if (strcmp(Type.getValueAsString(), "Fuse") == 0) {
        // if there are no other shapes to fuse just return itself
        if (Group.getValues().empty()) {
            PreviewShape.setValue(Shape.getShape());
            return;
        }

        std::vector<TopoShape> shapes;

        for (auto& obj : Group.getValues()) {
            shapes.push_back(getBooleanTopoShape(obj));
        }

        TopoShape result = makeTopoShape(false);
        result.makeCompound(shapes);

        PreviewShape.setValue(result.getShape());
        return;
    }

    PreviewShape.setValue(Shape.getShape());
}

void Boolean::onChanged(const App::Property* prop)
{

    if (strcmp(prop->getName(), "Group") == 0) {
        touch();
    }
    // The merge warning goes, or comes back, with the next compute (FreeCAD-CH ops#325)
    else if (strcmp(prop->getName(), "MergeAccepted") == 0 && !isRestoring()) {
        touch();
    }

    Feature::onChanged(prop);
}

void Boolean::handleChangedPropertyName(Base::XMLReader& reader, const char* TypeName, const char* PropName)
{
    // The App::PropertyLinkList property was Bodies in the past
    Base::Type type = Base::Type::fromName(TypeName);

    if (Group.getClassTypeId() == type && strcmp(PropName, "Bodies") == 0) {
        Group.Restore(reader);
    }
}

// ------------------------------------------------------------------------------------------------
// Merge (FreeCAD-CH ops#325, B+ Stage 1 3b)

namespace
{
constexpr const char* mergedInto = "MergedInto";
constexpr const char* mergeAccepted = "MergeAccepted";

std::string label(const App::DocumentObject* obj)
{
    return obj ? obj->Label.getValue() : "None";
}

// The last solid feature of `body` up to its Tip, or null
App::DocumentObject* lastSolid(Body* body)
{
    const std::vector<App::DocumentObject*> group = body->Group.getValues();
    auto end = std::ranges::find(group, body->Tip.getValue());
    if (end == group.end()) {
        return nullptr;
    }
    for (auto it = std::make_reverse_iterator(end + 1); it != group.rend(); ++it) {
        if (Body::isSolidFeature(*it)) {
            return *it;
        }
    }
    return nullptr;
}

std::string labels(const std::vector<App::DocumentObject*>& objects)
{
    std::string text;
    for (auto obj : objects) {
        text += (text.empty() ? "" : ", ") + label(obj);
    }
    return text;
}
}  // namespace

bool Boolean::isMerge() const
{
    return getPropertyByName(mergeAccepted) != nullptr;
}

Boolean* Boolean::mergeOf(const App::DocumentObject* body)
{
    auto link = body ? freecad_cast<App::PropertyLinkHidden*>(body->getPropertyByName(mergedInto))
                     : nullptr;
    auto merge = link ? freecad_cast<Boolean*>(link->getValue()) : nullptr;
    // A Merge left in no part (its Body deleted alone) merges nothing (PR 305 round 1)
    return merge && merge->isMerge() && Body::findBodyOf(merge) ? merge : nullptr;
}

std::vector<App::DocumentObject*> Boolean::mergedBodies() const
{
    std::vector<App::DocumentObject*> bodies;
    if (App::Document* doc = getDocument()) {
        for (auto obj : doc->getObjectsOfType(Body::getClassTypeId())) {
            if (mergeOf(obj) == this) {
                bodies.push_back(obj);
            }
        }
    }
    return bodies;
}

namespace
{
// The merged features for a Merge of `bodies` in `survivor`, right after `after`: each Body's last
// solid feature, in `absorbed` the Bodies. Refused, with the reason, before anything changes; a
// Body that `self` merges already may stay (setMergeScope)
std::vector<App::DocumentObject*> mergeTools(
    Body* survivor,
    App::DocumentObject* after,
    const std::vector<App::DocumentObject*>& bodies,
    std::vector<Body*>& absorbed,
    const Boolean* self
)
{
    std::vector<App::DocumentObject*> tools;
    for (auto obj : bodies) {
        auto body = freecad_cast<Body*>(obj);
        if (!body) {
            throw Base::ValueError("Merge: " + label(obj) + " isn't a part");
        }
        if (std::ranges::find(absorbed, body) != absorbed.end()) {
            continue;
        }
        if (body == survivor) {
            throw Base::ValueError("Merge: " + label(body) + " can't merge into itself");
        }
        if (!Part::BodyBase::areStudioSiblings(survivor, body)) {
            throw Base::ValueError(
                "Merge: " + label(body) + " isn't a part of " + label(survivor)
                + "'s studio (one container, placed alike)"
            );
        }
        if (Boolean* merge = Boolean::mergeOf(body); merge && merge != self) {
            throw Base::ValueError(
                "Merge: " + label(body) + " is merged into "
                + label(Body::findBodyOf(merge)) + " already"
            );
        }
        // A part merged here already keeps its merged feature: one added to it later is locked
        // (mergeLock), not merged
        App::DocumentObject* merged = nullptr;
        if (self && Boolean::mergeOf(body) == self) {
            for (auto tool : self->Group.getValues()) {
                if (Body::findBodyOf(tool) == body) {
                    merged = tool;
                    break;
                }
            }
        }
        // A held feature would merge a frozen shape (design 2.6)
        if (!merged && body->isRolledBack()) {
            throw Base::ValueError("Merge: Roll " + label(body) + " to the end first");
        }
        if (!merged) {
            merged = lastSolid(body);
        }
        if (!merged) {
            throw Base::ValueError("Merge: " + label(body) + " has no solid to merge");
        }
        absorbed.push_back(body);
        tools.push_back(merged);
    }
    if (absorbed.empty()) {
        throw Base::ValueError("Merge: no part to merge");
    }
    // A merged feature that depends on a feature the Merge will feed would be a cycle (the
    // design's critic, point 11): refused, naming the dependency
    const std::vector<App::DocumentObject*> group = survivor->Group.getValues();
    std::vector<App::DocumentObject*> later(std::ranges::find(group, after) + 1, group.end());
    for (auto merged : tools) {
        const std::vector<App::DocumentObject*> closure = merged->getOutListRecursive();
        std::vector<App::DocumentObject*> found;
        std::ranges::copy_if(later, std::back_inserter(found), [&closure](auto obj) {
            return std::ranges::find(closure, obj) != closure.end();
        });
        if (found.empty()) {
            continue;
        }
        // The first solid it depends on names it best (its sketch comes before it)
        auto solid = std::ranges::find_if(found, [](auto obj) { return Body::isSolidFeature(obj); });
        App::DocumentObject* dependency = solid != found.end() ? *solid : found.front();
        throw Base::ValueError(
            "Merge: " + label(merged) + " depends on " + label(dependency)
            + ", which comes after the Merge in " + label(survivor) + "; merge after "
            + label(dependency) + ", or change " + label(merged)
        );
    }

    return tools;
}
}  // namespace

Boolean* Boolean::makeMerge(App::DocumentObject* at, const std::vector<App::DocumentObject*>& bodies)
{
    auto survivor = freecad_cast<Body*>(at);
    App::DocumentObject* after = nullptr;
    if (survivor) {
        after = lastSolid(survivor);
    }
    else if ((survivor = Body::findBodyOf(at)) && Body::isSolidFeature(at)) {
        after = at;
    }
    if (!survivor || !after) {
        throw Base::ValueError(
            "Merge: " + label(at) + " is neither a solid feature in a part nor a part with a solid"
        );
    }
    if (Boolean* merge = mergeOf(survivor)) {
        throw Base::ValueError(
            "Merge: " + label(survivor) + " is merged into " + label(Body::findBodyOf(merge))
            + "; merge into that part"
        );
    }
    std::vector<Body*> absorbed;
    std::vector<App::DocumentObject*> tools = mergeTools(survivor, after, bodies, absorbed, nullptr);

    App::Document* doc = survivor->getDocument();
    const bool atTip = survivor->Tip.getValue() == after;
    auto merge = static_cast<Boolean*>(doc->addObject("PartDesign::Boolean", "Merge"));
    merge->Label.setValue("Merge");
    survivor->insertObject(merge, after, /*after=*/true);
    if (atTip) {
        survivor->Tip.setValue(merge);
    }
    merge->Type.setValue("Fuse");
    auto accepted = static_cast<App::PropertyBool*>(merge->addDynamicProperty(
        "App::PropertyBool",
        mergeAccepted,
        "Merge",
        "Whether the merge was accepted: until then it warns",
        App::Prop_Hidden
    ));
    accepted->setValue(false);
    merge->addDynamicProperty(
        "App::PropertyPlacementList",
        mergeFrames,
        "Merge",
        "Where the merged parts were, in this part's frame, when the Merge last computed",
        App::Prop_Output | App::Prop_Hidden
    );
    merge->setObjects(tools);
    for (Body* body : absorbed) {
        auto link = freecad_cast<App::PropertyLinkHidden*>(body->getPropertyByName(mergedInto));
        if (!link) {
            link = static_cast<App::PropertyLinkHidden*>(body->addDynamicProperty(
                "App::PropertyLinkHidden",
                mergedInto,
                "Merge",
                "The Merge this part is merged into",
                App::Prop_Hidden
            ));
        }
        link->setValue(merge);
        body->Visibility.setValue(false);
    }
    return merge;
}

Boolean* Boolean::mergeAfter(const App::DocumentObject* feature)
{
    Body* body = Body::findBodyOf(feature);
    if (!body || !Body::isSolidFeature(feature)) {
        return nullptr;
    }
    auto next = freecad_cast<Boolean*>(
        body->getNextSolidFeature(const_cast<App::DocumentObject*>(feature))
    );
    return next && next->isMerge() && next->BaseFeature.getValue() == feature ? next : nullptr;
}

Boolean* Boolean::scopeMerge(const App::DocumentObject* feature)
{
    auto profileBased = freecad_cast<const ProfileBased*>(feature);
    if (!profileBased
        || const_cast<ProfileBased*>(profileBased)->getAddSubType() != FeatureAddSub::Type::Additive) {
        return nullptr;
    }
    Boolean* merge = mergeAfter(feature);
    auto accepted = merge ? freecad_cast<App::PropertyBool*>(merge->getPropertyByName(mergeAccepted))
                          : nullptr;
    return accepted && accepted->getValue() ? merge : nullptr;
}

Boolean* Boolean::setMergeScope(App::DocumentObject* feature, const std::vector<App::DocumentObject*>& bodies)
{
    Body* survivor = Body::findBodyOf(feature);
    if (!survivor || !Body::isSolidFeature(feature)) {
        throw Base::ValueError("Merge scope: " + label(feature) + " isn't a solid feature in a part");
    }
    Boolean* merge = mergeAfter(feature);
    if (bodies.empty()) {
        // Every part unticked: the Merge goes, and its parts are parts again (Body::onChanged
        // shows them when their MergedInto link breaks)
        if (merge) {
            App::Document* doc = merge->getDocument();
            const std::string name = merge->getNameInDocument();
            survivor->removeObject(merge);
            doc->removeObject(name.c_str());
        }
        return nullptr;
    }
    if (!merge) {
        merge = makeMerge(feature, bodies);
    }
    else {
        // In place, so what reads the Merge (the next feature, a sketch on its faces) keeps it
        std::vector<Body*> absorbed;
        std::vector<App::DocumentObject*> tools = mergeTools(survivor, feature, bodies, absorbed, merge);
        for (auto obj : merge->mergedBodies()) {
            if (std::ranges::find(absorbed, obj) == absorbed.end()) {
                if (auto link = freecad_cast<App::PropertyLinkHidden*>(obj->getPropertyByName(mergedInto))) {
                    link->setValue(nullptr);
                }
            }
        }
        merge->setObjects(tools);
        for (Body* body : absorbed) {
            auto link = freecad_cast<App::PropertyLinkHidden*>(body->getPropertyByName(mergedInto));
            if (!link) {
                link = static_cast<App::PropertyLinkHidden*>(body->addDynamicProperty(
                    "App::PropertyLinkHidden",
                    mergedInto,
                    "Merge",
                    "The Merge this part is merged into",
                    App::Prop_Hidden
                ));
            }
            if (link->getValue() != merge) {
                link->setValue(merge);
                body->Visibility.setValue(false);
            }
        }
    }
    // A merge picked in the feature's own dialog is a plain feature: no Warning (P50)
    if (auto accepted = freecad_cast<App::PropertyBool*>(merge->getPropertyByName(mergeAccepted))) {
        if (!accepted->getValue()) {
            accepted->setValue(true);
        }
    }
    return merge;
}

std::string Boolean::mergeProblem() const
{
    const std::vector<App::DocumentObject*> bodies = mergedBodies();
    const std::vector<App::DocumentObject*> tools = Group.getValues();
    const std::string fix = "; re-pick the part, or delete the Merge";
    // No tools while the part is still here (its merged feature deleted) is said below: nothing
    // of it is merged (PR 305 round 1)
    if (bodies.empty()) {
        return label(this) + ": the merged part is gone" + fix;
    }
    for (auto tool : tools) {
        if (mergeOf(Body::findBodyOf(tool)) != this) {
            return label(this) + ": the merged part changed, " + label(tool)
                + " isn't in a part merged here" + fix;
        }
    }
    for (auto body : bodies) {
        if (std::ranges::none_of(tools, [body](auto tool) {
                return Body::findBodyOf(tool) == body;
            })) {
            return label(this) + ": the merged part changed, nothing of " + label(body)
                + " is merged" + fix;
        }
    }
    return {};
}

std::vector<Base::Placement> Boolean::toolFrames() const
{
    std::vector<Base::Placement> frames;
    Body* own = Body::findBodyOf(this);
    const Base::Placement here = own ? own->globalPlacement() : Base::Placement();
    for (auto tool : Group.getValues()) {
        Body* body = Body::findBodyOf(tool);
        frames.push_back(here.inverse() * (body ? body->globalPlacement() : Base::Placement()));
    }
    return frames;
}

void Boolean::onDocumentRestored()
{
    // The frames it last computed with, as saved: a Merge saved stale (its part moved after it
    // ran) runs on the next recompute. One saved without them runs once (PR 305 round 1)
    if (auto saved = freecad_cast<App::PropertyPlacementList*>(getPropertyByName(mergeFrames))) {
        lastToolFrames = saved->getValues();
    }
    FeatureRefine::onDocumentRestored();
}

void Boolean::warnMerged()
{
    auto accepted = freecad_cast<App::PropertyBool*>(getPropertyByName(mergeAccepted));
    App::Document* doc = getDocument();
    if (!accepted || accepted->getValue() || !doc) {
        return;
    }
    const std::string text = "Merged " + labels(mergedBodies()) + " into "
        + label(Body::findBodyOf(this));
    const char* previous = doc->getWarningDescription(this);
    doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + text : text);
}

std::string Boolean::mergeLock(const App::DocumentObject* feature)
{
    Body* body = Body::findBodyOf(feature);
    Boolean* merge = body && Body::isSolidFeature(feature) ? mergeOf(body) : nullptr;
    if (!merge) {
        return {};
    }
    const std::vector<App::DocumentObject*> group = body->Group.getValues();
    const auto here = std::ranges::find(group, feature);
    for (auto merged : merge->Group.getValues()) {
        const auto there = std::ranges::find(group, merged);
        if (there != group.end() && here != group.end() && here > there) {
            return label(body) + " is merged into " + label(Body::findBodyOf(merge)) + " at "
                + label(merged) + "; this feature doesn't reach the merge. Move it before "
                + label(merged) + ", or delete the Merge";
        }
    }
    return {};
}

Boolean* Boolean::consumerOf(const App::DocumentObject* body)
{
    auto part = freecad_cast<const Body*>(body);
    App::Document* doc = part ? part->getDocument() : nullptr;
    if (!doc) {
        return nullptr;
    }
    for (auto obj : doc->getObjectsOfType(Boolean::getClassTypeId())) {
        auto boolean = static_cast<Boolean*>(obj);
        if (boolean->isMerge() || boolean->KeepTools.getValue() || boolean->isError()) {
            continue;
        }
        auto suppressible = boolean->getExtensionByType<App::SuppressibleExtension>(true);
        if (suppressible && suppressible->Suppressed.getValue()) {
            continue;
        }
        // Rolled back past it, the history doesn't reach it yet: its tools are parts
        Body* own = Body::findBodyOf(boolean);
        if (!own || own == part || own->holds(boolean)) {
            continue;
        }
        const std::vector<App::DocumentObject*> separate = boolean->SeparateTools.getValues();
        for (auto tool : boolean->Group.getValues()) {
            const Body* toolBody = freecad_cast<const Body*>(tool);
            if (!toolBody) {
                toolBody = Body::findBodyOf(tool);
            }
            if (toolBody == part && std::ranges::find(separate, tool) == separate.end()) {
                return boolean;
            }
        }
    }
    return nullptr;
}

}  // namespace PartDesign
