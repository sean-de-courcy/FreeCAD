// SPDX-License-Identifier: LGPL-2.1-or-later

// The generic step of a tool-making studio feature (FreeCAD-CH ops#654, notes/parts-design.md
// 3.1 and 10.8): its owner's tool, applied to its base by Operation, then refined.

#include <algorithm>
#include <numeric>
#include <string>
#include <vector>

#include <BRepExtrema_DistShapeShape.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopAbs_ShapeEnum.hxx>

#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/PropertyStandard.h>
#include <Base/Exception.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "Body.h"
#include "FeatureApply.h"
#include "FeatureBoolean.h"
#include "Pieces.h"
#include "StudioList.h"
#include "StudioOwner.h"
#include "StudioPattern.h"
#include "StudioTransform.h"

using namespace PartDesign;

namespace PartDesign
{
// StudioOwner.cpp (FreeCAD-CH ops#654 P5; declared where used)
PartDesignExport Part::TopoShape studioBooleanTool(const App::DocumentObject* owner, std::string* why);
// StudioList.cpp (FreeCAD-CH ops#654 slice 9; declared where used)
PartDesignExport bool isStudioPartPattern(const App::DocumentObject* obj);
PartDesignExport bool studioPartMirrorConsumes(const App::DocumentObject* owner);
PartDesignExport std::vector<Body*> studioPartPatternSources(const App::DocumentObject* owner);
// StudioList.cpp and Pieces.cpp (FreeCAD-CH ops#654 10.13; declared where used)
PartDesignExport bool studioIsMergingAdd(const App::DocumentObject* owner);
PartDesignExport std::vector<std::string> studioMembersAfter(const App::DocumentObject* owner,
                                                             const Body* part);
PartDesignExport bool studioSolidsJoin(const TopoDS_Shape& a, const TopoDS_Shape& b);
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

/// tool's solids that touch or overlap base (a solid inside the other counts: distance 0); null
/// when none touches: a solid touching no part of the scope is a leftover, the owner's to check
/// and a part of its own once a command made it one (P6p, Onshape H1a and R4)
Part::TopoShape touching(const Part::TopoShape& tool, const Part::TopoShape& base)
{
    const std::vector<Part::TopoShape> solids = tool.getSubTopoShapes(TopAbs_SOLID);
    std::vector<Part::TopoShape> kept;
    for (const auto& solid : solids) {
        BRepExtrema_DistShapeShape distance(solid.getShape(), base.getShape());
        if (distance.IsDone() && distance.Value() <= Precision::Confusion()) {
            kept.push_back(solid);
        }
    }
    if (kept.empty()) {
        return {};
    }
    if (kept.size() == solids.size()) {
        return tool;
    }
    if (kept.size() == 1) {
        return kept.front();
    }
    Part::TopoShape out = tool;  // its Tag, hasher and history algorithm
    out.makeElementCompound(kept);
    return out;
}

/// What an Add owner's tool joins at its place (FreeCAD-CH ops#654 10.13, Onshape O9 and M1-M4):
/// the contact graph of its scope parts (their shapes at its place, in scope order) and its tool's
/// solids, with edges only between a tool solid and a part, contact by studioSolidsJoin (face
/// contact or overlap, never an edge or a vertex). Each component holding a part is one part: its
/// first listed part survives, the others are merged into it. A tool solid in no component is a
/// leftover (P6p)
struct Merge
{
    std::vector<Body*> parts;
    std::vector<Part::TopoShape> shapes;  ///< each part's shape at the owner's place (document)
    std::vector<int> partComponent;
    std::vector<int> toolComponent;    ///< each tool solid's component, -1: none
    std::vector<std::string> records;  ///< "<merged id> -> <survivor id>", in scope order

    int indexOf(const Body* body) const
    {
        auto it = std::ranges::find(parts, body);
        return it == parts.end() ? -1 : static_cast<int>(it - parts.begin());
    }
    /// The first listed part of component
    int survivorOf(int component) const
    {
        for (std::size_t k = 0; k < parts.size(); ++k) {
            if (partComponent[k] == component) {
                return static_cast<int>(k);
            }
        }
        return -1;
    }
};

Merge mergeOf(const App::DocumentObject* owner, const Part::TopoShape& tool)
{
    Merge out;
    for (auto part : studioScopeOf(owner)) {
        // Not a part it makes itself from a leftover (P6p): it has no shape before it
        if (isPieceBody(part) && part->StudioMadeBy.getValue() == owner) {
            continue;
        }
        Part::TopoShape shape = studioBaseAt(owner, part);
        if (!shape.isNull()) {
            out.parts.push_back(part);
            out.shapes.push_back(shape);
        }
    }
    const std::vector<Part::TopoShape> solids = tool.getSubTopoShapes(TopAbs_SOLID);
    const int parts = static_cast<int>(out.parts.size());
    // Union-find over the parts (0..parts-1) and the tool's solids (parts..); a component's root
    // is its first listed part
    std::vector<int> root(parts + solids.size());
    std::iota(root.begin(), root.end(), 0);
    auto find = [&root](int k) {
        while (root[k] != k) {
            root[k] = root[root[k]];
            k = root[k];
        }
        return k;
    };
    for (std::size_t j = 0; j < solids.size(); ++j) {
        for (int k = 0; k < parts; ++k) {
            if (studioSolidsJoin(solids[j].getShape(), out.shapes[k].getShape())) {
                const int a = find(parts + static_cast<int>(j));
                const int b = find(k);
                root[std::max(a, b)] = std::min(a, b);
            }
        }
    }
    for (int k = 0; k < parts; ++k) {
        out.partComponent.push_back(find(k));
    }
    for (std::size_t j = 0; j < solids.size(); ++j) {
        const int r = find(parts + static_cast<int>(j));
        out.toolComponent.push_back(r < parts ? r : -1);
    }
    for (int k = 0; k < parts; ++k) {
        const int survivor = out.survivorOf(out.partComponent[k]);
        if (survivor != k) {
            out.records.push_back(studioPartId(out.parts[k]) + " -> "
                                  + studioPartId(out.parts[survivor]));
        }
    }
    return out;
}

/// Writes owner's merge record (StudioMergedParts) when it changed; the projection takes it after
/// the recompute (resyncPartMirrors)
void noteMerges(App::DocumentObject* owner, const std::vector<std::string>& records)
{
    auto prop =
        freecad_cast<App::PropertyStringList*>(owner->getPropertyByName("StudioMergedParts"));
    if (!prop) {
        if (records.empty() || owner->getPropertyByName("StudioMergedParts")) {
            return;
        }
        prop = static_cast<App::PropertyStringList*>(owner->addDynamicProperty(
            "App::PropertyStringList",
            "StudioMergedParts",
            "Studio",
            "The parts this Add merges into another part of its scope, each '<id> -> <survivor "
            "id>' (ops#654 10.13)",
            App::Prop_Hidden | App::Prop_Output | App::Prop_NoRecompute
        ));
    }
    if (prop->getValues() != records) {
        prop->setValues(records);
    }
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
        Body* body = getFeatureBody();
        // ops#655: a Transform studio feature's step moves its part or makes a copy
        // (StudioTransform.cpp); its location is the step's Placement
        if (owner && isStudioTransform(owner)) {
            Part::TopoShape moved =
                studioTransformStep(owner, body, getBaseTopoShape(/*silent=*/true), namingTag(), &why);
            if (moved.isNull()) {
                return new App::DocumentObjectExecReturn(why, this);
            }
            AddSubShape.setValue(Part::TopoShape());
            const Base::Placement place = moved.getPlacement();
            if (!Placement.getValue().isSame(place, Precision::Confusion())) {
                Placement.setValue(place);
            }
            rawShape = moved;
            Shape.setValue(moved);
            return App::DocumentObject::StdReturn;
        }
        // A piece step (P6p): the first step of a part its owner made from a piece or a leftover
        // takes the one solid of the source its witness selects, as is
        const bool piece = body && owner && isPieceBody(body) && body->StudioMadeBy.getValue() == owner;
        Part::TopoShape tool = piece ? pieceShape(body, &why) : toolOf(owner, &why);
        // 10.13: an Add owner merges the parts its tool joins; decided here, in the document's
        // frame, by every step alike (the record is written when it changes)
        const bool merging = !piece && owner && studioIsMergingAdd(owner)
            && getBooleanOperation() == BooleanOperation::Union;
        Merge merge;
        if (merging) {
            if (!tool.isNull()) {
                merge = mergeOf(owner, tool);
            }
            noteMerges(owner, merge.records);
        }
        if (tool.isNull()) {
            return new App::DocumentObjectExecReturn(why, this);
        }
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
        if (piece) {
            AddSubShape.setValue(Part::TopoShape());
            if (!base.isNull()) {
                return new App::DocumentObjectExecReturn(
                    "Something comes before the first step of " + part + ", a part made from a piece",
                    this
                );
            }
            rawShape = tool;
            Shape.setValue(tool);
            return App::DocumentObject::StdReturn;
        }
        if (base.isNull()) {
            AddSubShape.setValue(tool);
            if ((merging && !merge.parts.empty()) || (body && isPieceBody(body))) {
                // 10.13: nothing before it in a piece (its split held nothing for it), or in a
                // part of an Add over parts with solids: a part that fails, and so does what
                // acts on it (P6p); never the tool as a part of its own (unverified on Onshape)
                return new App::DocumentObjectExecReturn(
                    "Nothing comes before this step in " + part + ": it has no solid to add to",
                    this
                );
            }
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
            std::vector<Part::TopoShape> merged;  // the parts merged into this one (10.13)
            const int k = merging ? merge.indexOf(body) : -1;
            if (k >= 0) {
                // Only the tool's solids of this part's component, and only in its survivor; the
                // parts merged into it enter the fuse whole (skeptic 4 and 5: no per-solid filter)
                const int component = merge.partComponent[k];
                std::vector<Part::TopoShape> kept;
                if (merge.survivorOf(component) == k) {
                    const auto solids = tool.getSubTopoShapes(TopAbs_SOLID);
                    for (std::size_t j = 0; j < solids.size() && j < merge.toolComponent.size();
                         ++j) {
                        if (merge.toolComponent[j] == component) {
                            kept.push_back(solids[j]);
                        }
                    }
                }
                if (kept.empty()) {
                    // Nothing of the tool joins this part, or it is merged into another: it stays
                    // as it was here
                    AddSubShape.setValue(Part::TopoShape());
                    rawShape = base;
                    Shape.setValue(getSolid(base));
                    return App::DocumentObject::StdReturn;
                }
                if (kept.size() < tool.countSubShapes(TopAbs_SOLID)) {
                    Part::TopoShape some = tool;  // its Tag, hasher and history algorithm
                    some.makeElementCompound(kept);
                    tool = some;
                }
                const Base::Placement toStep = (bodyFrame * Placement.getValue()).inverse();
                for (std::size_t m = 0; m < merge.parts.size(); ++m) {
                    if (static_cast<int>(m) == k || merge.partComponent[m] != component) {
                        continue;
                    }
                    // A feature of the merged part after the owner has no part to act on: loud,
                    // never a silent follow (P8a's picks)
                    const auto later = studioMembersAfter(owner, merge.parts[m]);
                    if (!later.empty()) {
                        std::string names;
                        for (const auto& name : later) {
                            names += (names.empty() ? "'" : ", '") + name + "'";
                        }
                        const std::string gone =
                            std::string("'") + merge.parts[m]->Label.getValue() + "'";
                        return new App::DocumentObjectExecReturn(
                            "'" + std::string(owner->Label.getValue()) + "' merges " + gone
                                + " into " + part + ", but " + names + " after it in " + gone
                                + " would have no part: move it above, or into " + part,
                            this
                        );
                    }
                    Part::TopoShape other = merge.shapes[m];
                    other.transformShape(toStep.toMatrix(), false, true);
                    merged.push_back(other);
                }
            }
            else if (getBooleanOperation() == BooleanOperation::Union && !isBooleanOwner(owner)) {
                tool = touching(tool, base);
                if (tool.isNull()) {
                    // Nothing of the tool touches this part: it stays as it was
                    AddSubShape.setValue(Part::TopoShape());
                    rawShape = base;
                    Shape.setValue(getSolid(base));
                    return App::DocumentObject::StdReturn;
                }
            }
            AddSubShape.setValue(tool);
            result = Part::TopoShape(
                tag,
                getDocument()->getStringHasher(),
                getSelectedHistoryAlgorithm()
            );
            try {
                std::vector<Part::TopoShape> operands {base, tool};
                operands.insert(operands.end(), merged.begin(), merged.end());
                result.makeElementBoolean(
                    getBooleanMaker(),
                    operands,
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
        noteSplitHeld(owner, body, result);
        if (solids > 1) {
            // A split (P6p): every piece must be a part, made by a command; the part's chain then
            // ends here, holding them all (its pieces take theirs)
            if (std::string unclaimed = unclaimedSplit(owner, body, result); !unclaimed.empty()) {
                return new App::DocumentObjectExecReturn(unclaimed, this);
            }
            Shape.setValue(result);
            return App::DocumentObject::StdReturn;
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
