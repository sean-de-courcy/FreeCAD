// SPDX-License-Identifier: LGPL-2.1-or-later

// The generic step of a tool-making studio feature (FreeCAD-CH ops#654, notes/parts-design.md
// 3.1 and 10.8): its owner's tool, applied to its base by Operation, then refined.

#include <Precision.hxx>
#include <Standard_Failure.hxx>

#include <App/Document.h>
#include <App/GeoFeature.h>
#include <Base/Exception.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "Body.h"
#include "FeatureApply.h"
#include "StudioList.h"

using namespace PartDesign;

PROPERTY_SOURCE(PartDesign::FeatureApply, PartDesign::FeatureAddSub)

FeatureApply::FeatureApply()
{
    allowAllOperations();
}

short FeatureApply::mustExecute() const
{
    if (StudioOwner.isTouched()) {
        return 1;
    }
    return FeatureAddSub::mustExecute();
}

Part::TopoShape FeatureApply::toolOf(const App::DocumentObject* owner, std::string* why)
{
    auto fail = [why](const std::string& text) {
        if (why) {
            *why = text;
        }
        return Part::TopoShape();
    };
    if (!owner || !owner->isAttachedToDocument()) {
        return fail("This step has no studio feature");
    }
    const std::string label = std::string("'") + owner->Label.getValue() + "'";
    Part::TopoShape tool;
    if (auto addSub = freecad_cast<const FeatureAddSub*>(owner)) {
        tool = addSub->AddSubShape.getShape();
    }
    else if (auto feature = freecad_cast<const Part::Feature*>(owner)) {
        tool = feature->Shape.getShape();
    }
    else {
        return fail(label + " makes no shape to apply");
    }
    if (tool.isNull()) {
        return fail(label + " has no tool");
    }
    // In the document's frame: the owner's placement in its studio
    tool.setPlacement(App::GeoFeature::getGlobalPlacement(owner));
    return tool;
}

App::DocumentObjectExecReturn* FeatureApply::execute()
{
    if (onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }
    try {
        App::DocumentObject* owner = StudioOwner.getValue();
        std::string why;
        Part::TopoShape tool = toolOf(owner, &why);
        if (tool.isNull()) {
            return new App::DocumentObjectExecReturn(why, this);
        }
        Body* body = getFeatureBody();
        const std::string part =
            body ? std::string("'") + body->Label.getValue() + "'" : std::string("its part");

        // The tool in the Body's frame. The step is placed where its base is (as a dress-up),
        // or, with nothing before it, where the tool is, so a New result keeps the tool's own
        // shape (Part::Feature puts the Placement on the Shape it is given)
        const Base::Placement bodyFrame = body ? App::GeoFeature::getGlobalPlacement(body)
                                               : Base::Placement();
        const Base::Placement toolInBody = bodyFrame.inverse() * tool.getPlacement();
        Part::Feature* baseObject = getBaseObject(/*silent=*/true);
        const Base::Placement place = baseObject ? baseObject->Placement.getValue() : toolInBody;
        if (!Placement.getValue().isSame(place, Precision::Confusion())) {
            Placement.setValue(place);
        }
        tool.setPlacement(Placement.getValue().inverse() * toolInBody);

        // Its names are the owner's tool's (requirement 1: a step made again in the same place
        // makes the same names, work/standby-f/tags.log); a tag minted for (owner, part) takes
        // their place once the naming code is known to take it (studioTagFor())
        const long tag = studioTagFor(owner, body);
        if (tag != owner->getID()) {
            tool.reTagElementMap(tag, tool.Hasher);
        }
        AddSubShape.setValue(tool);

        Part::TopoShape base = getBaseTopoShape(/*silent=*/true);
        Part::TopoShape result;
        if (base.isNull()) {
            if (getBooleanOperation() != BooleanOperation::Union) {
                return new App::DocumentObjectExecReturn(
                    "No merge scope selected: nothing comes before this step in " + part,
                    this
                );
            }
            result = tool;  // New: the tool itself
        }
        else {
            base.move(getInverseLocation(base));
            result = makeTopoShape(tag, false);
            try {
                result.makeElementBoolean(
                    getBooleanMaker(),
                    {base, tool},
                    nullptr,
                    FuzzyTolerance.getValue(),
                    Part::ElementMapPolicy::Propagate,
                    booleanInputCheck(),
                    &booleanInputsValid
                );
            }
            catch (Standard_Failure&) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Failed to perform boolean operation"),
                    this
                );
            }
        }
        rawShape = result;
        result = refineShapeIfActive(result);

        // A Body never goes on with two solids (requirement 2, until pieces become parts, P6p)
        const int solids = result.isNull() ? 0 : countSolids(result.getShape());
        if (solids == 0) {
            return new App::DocumentObjectExecReturn(
                "Applying '" + std::string(owner->Label.getValue()) + "' leaves nothing of " + part,
                this
            );
        }
        if (solids > 1) {
            return new App::DocumentObjectExecReturn(
                "'" + std::string(owner->Label.getValue()) + "' splits " + part + " into "
                    + std::to_string(solids)
                    + " pieces: pieces becoming parts is not done yet",
                this
            );
        }
        Shape.setValue(getSolid(result));
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString(), this);
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what(), this);
    }
    return App::DocumentObject::StdReturn;
}
