// SPDX-License-Identifier: LGPL-2.1-or-later

// The generic step of a tool-making studio feature (FreeCAD-CH ops#654, notes/parts-design.md
// 3.1 and 10.8): its owner's tool, applied to its base by Operation, then refined.

#include <vector>

#include <BRepExtrema_DistShapeShape.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopAbs_ShapeEnum.hxx>

#include <App/Document.h>
#include <App/GeoFeature.h>
#include <Base/Exception.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "Body.h"
#include "FeatureApply.h"
#include "FeatureBoolean.h"
#include "StudioList.h"
#include "StudioOwner.h"
#include "StudioPattern.h"

using namespace PartDesign;

namespace PartDesign
{
// StudioOwner.cpp (FreeCAD-CH ops#654 P5; declared where used)
PartDesignExport Part::TopoShape studioBooleanTool(const App::DocumentObject* owner, std::string* why);
// StudioList.cpp (FreeCAD-CH ops#654 slice 9; declared where used)
PartDesignExport bool isStudioPartPattern(const App::DocumentObject* obj);
PartDesignExport bool studioPartMirrorConsumes(const App::DocumentObject* owner);
PartDesignExport std::vector<Body*> studioPartPatternSources(const App::DocumentObject* owner);
}  // namespace PartDesign

PROPERTY_SOURCE(PartDesign::FeatureApply, PartDesign::FeatureAddSub)

namespace
{

/// A Boolean studio feature (P5): its tool is other parts' shapes at its place
bool isBooleanOwner(const App::DocumentObject* owner)
{
    auto boolean = freecad_cast<const Boolean*>(owner);
    return boolean && runsAsStudioOwner(boolean);
}

/// tool's solids that touch or overlap base (a solid inside the other counts: distance 0); all of
/// them when it has one solid, or when none touches (the step then fails as it would)
Part::TopoShape touching(const Part::TopoShape& tool, const Part::TopoShape& base)
{
    const std::vector<Part::TopoShape> solids = tool.getSubTopoShapes(TopAbs_SOLID);
    if (solids.size() < 2) {
        return tool;
    }
    std::vector<Part::TopoShape> kept;
    for (const auto& solid : solids) {
        BRepExtrema_DistShapeShape distance(solid.getShape(), base.getShape());
        if (distance.IsDone() && distance.Value() <= Precision::Confusion()) {
            kept.push_back(solid);
        }
    }
    if (kept.empty() || kept.size() == solids.size()) {
        return tool;
    }
    if (kept.size() == 1) {
        return kept.front();
    }
    Part::TopoShape out = tool;  // its Tag, hasher and history algorithm
    out.makeElementCompound(kept);
    return out;
}

}  // namespace

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
    if (isBooleanOwner(owner)) {
        return studioBooleanTool(owner, why);  // in the document's frame already
    }
    if (isStudioPartPattern(owner)) {
        // The part mirror (slice 9): its source part mirrored, in the document's frame already;
        // with the source itself when its Add consumes it (Onshape oracle 9, R4)
        Part::TopoShape copy = studioPatternTool(owner, nullptr, why);
        const auto sources = studioPartPatternSources(owner);
        if (copy.isNull() || !studioPartMirrorConsumes(owner) || sources.size() != 1) {
            return copy;
        }
        Part::TopoShape source = studioBaseAt(owner, sources.front());
        if (source.isNull()) {
            return copy;
        }
        Part::TopoShape fused(owner->getID(), owner->getDocument()->getStringHasher());
        fused.makeElementFuse({copy, source});
        return fused;
    }
    Part::TopoShape tool;
    // The frame the tool's own location is in: an owner's AddSubShape is in the owner's frame; a
    // shape object's Shape carries the object's Placement already, so it is in its container's
    Base::Placement frame = App::GeoFeature::getGlobalPlacement(owner);
    if (auto addSub = freecad_cast<const FeatureAddSub*>(owner)) {
        tool = addSub->AddSubShape.getShape();
    }
    else if (auto feature = freecad_cast<const Part::Feature*>(owner)) {
        tool = feature->Shape.getShape();
        frame = frame * feature->Placement.getValue().inverse();
    }
    else {
        return fail(label + " makes no shape to apply");
    }
    if (tool.isNull()) {
        return fail(label + " has no tool");
    }
    // In the document's frame, the tool's own location kept (composed, not replaced)
    tool.setPlacement(frame * tool.getPlacement());
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

        // Its names are its owner's (format rule 2, notes/stored-tags.md 3 item 1): the tool
        // carries the owner's ID, and so do the Boolean and the refine, never the step's own ID
        // nor 0, so a step made again in the same place makes the same names
        const long tag = namingTag();

        Part::TopoShape base = getBaseTopoShape(/*silent=*/true);
        Part::TopoShape result;
        if (base.isNull()) {
            AddSubShape.setValue(tool);
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
            // FreeCAD-CH ops#654 S2: an Add fuses into this part only the tool's solids that
            // touch it; another region's solid belongs to the part it stops on (Onshape O8b)
            // A Union Boolean's tools are fused whole (P5): one that touches nothing is refused
            // below, never dropped
            if (getBooleanOperation() == BooleanOperation::Union && !isBooleanOwner(owner)) {
                tool = touching(tool, base);
            }
            AddSubShape.setValue(tool);
            result = Part::TopoShape(
                tag,
                getDocument()->getStringHasher(),
                getSelectedHistoryAlgorithm()
            );
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
        if (solids > 1 && isBooleanOwner(owner)
            && getBooleanOperation() == BooleanOperation::Union) {
            // Onshape leaves a tool apart from the others a part of its own (hands-on A-2' b);
            // until pieces become parts (P6p) the Union fails loudly
            return new App::DocumentObjectExecReturn(
                "'" + std::string(owner->Label.getValue()) + "' leaves " + part + " in "
                    + std::to_string(solids)
                    + " separate solids: a tool part touches none of the parts it merges with",
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
