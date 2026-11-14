// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer <jrheinlaender@users.sourceforge.net> *
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

#include <Bnd_Box.hxx>
#include <BRep_Builder.hxx>
#include <Mod/Part/App/FCBRepAlgoAPI_Cut.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <BRepAdaptor_Curve.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <TopoDS.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <Precision.hxx>
#include <TopExp_Explorer.hxx>


#include <array>
#include <cstring>
#include <limits>
#include <optional>
#include <unordered_map>
#include <algorithm>

#include <App/Document.h>
#include <App/GeoFeature.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Base/Sequencer.h>
#include <Mod/Part/App/modelRefine.h>

#include "FeatureTransformed.h"
#include "Body.h"
#include "FeatureAddSub.h"
#include "FeatureBoolean.h"
#include "FeatureChamfer.h"
#include "FeatureExtrude.h"
#include "FeatureFillet.h"
#include "FeatureHelix.h"
#include "FeatureHole.h"
#include "FeatureLoft.h"
#include "FeatureMultiTransform.h"
#include "FeaturePipe.h"
#include "FeaturePrimitive.h"
#include "FeatureRevolved.h"
#include "FeatureMirrored.h"
#include "FeatureCurvePattern.h"
#include "FeatureLinearPattern.h"
#include "FeaturePolarPattern.h"
#include "FeatureSketchBased.h"
#include "Pieces.h"
#include "Retarget.h"
#include "StudioList.h"
#include "StudioOwner.h"
#include "StudioPattern.h"
#include "Mod/Part/App/TopoShapeOpCode.h"


using namespace PartDesign;

namespace
{

/* The number of each transformation's instance (the first, the support, is 1) in its V2 name's
 * TRF section (ops#6): one number per step, from 1, joined by ':', the trailing 1s left out. A
 * single-step pattern's instance k is "k"; instance (2, 2) of a two-step one is "2:2", and (3, 1)
 * is "3". So an instance keeps its number when another step's count changes, or when a step is
 * added after the others. A step of one occurrence is a 1 digit: left out at the end, kept in
 * the middle (a MultiTransform's unused Direction2 before a later feature's used one: "2:2:1:2"),
 * so giving it more occurrences later renames no instance. ('.' would read better, but the
 * element map rejects it in a name: it separates fields in the saved map.) Steps that don't
 * cover the list exactly are taken as one step: the whole list.
 */
std::vector<std::string> instanceNumbers(std::vector<Transformed::Step> steps, std::size_t count)
{
    std::size_t product = 1;
    for (const auto& step : steps) {
        product *= static_cast<std::size_t>(std::max(step.count, 1));
    }
    if (steps.empty() || product != count) {
        steps = {{static_cast<int>(count), 1}};
    }
    std::vector<std::string> numbers;
    numbers.reserve(count);
    for (std::size_t position = 0; position < count; ++position) {
        std::vector<std::size_t> digits;
        for (const auto& step : steps) {
            const auto stride = static_cast<std::size_t>(std::max(step.stride, 1));
            const auto stepCount = static_cast<std::size_t>(std::max(step.count, 1));
            digits.push_back(position / stride % stepCount + 1);
        }
        while (!digits.empty() && digits.back() == 1) {
            digits.pop_back();
        }
        std::string number;
        for (auto digit : digits) {
            number += (number.empty() ? "" : ":") + std::to_string(digit);
        }
        numbers.push_back(number.empty() ? "1" : number);
    }
    return numbers;
}

/* FreeCAD-CH (ops#640, B3-3b, A-2' d): the copies (indexes into shapes, from 1; shapes[0] is the
 * support) that the fuse of shapes left in solids touching nothing of the support. Onshape's
 * feature pattern and mirror (Reapply features off) drop such an instance silently; a copy that
 * reaches the part, even partly, merges. Cheap in the usual case: only a fuse that left more
 * solids than the support had is looked at. Two copies off the part that touch each other are in
 * one loose solid, and both are dropped. Touching is shapesTouch(): a copy that meets the part only
 * along an edge or at a vertex touches it and is kept (a lump on the part, as the fuse leaves it).
 * Not caught: a copy bridging two of the support's solids while another floats leaves the solid
 * count unchanged, and the floating copy is kept.
 */
std::vector<std::size_t> floatingCopies(
    const Part::TopoShape& fused,
    const Part::TopoShape& support,
    const std::vector<Part::TopoShape>& shapes
)
{
    std::vector<std::size_t> floating;
    if (fused.isNull() || support.isNull()
        || fused.countSubShapes(TopAbs_SOLID) <= support.countSubShapes(TopAbs_SOLID)) {
        return floating;
    }
    std::vector<TopoDS_Shape> loose;
    for (TopExp_Explorer xp(fused.getShape(), TopAbs_SOLID); xp.More(); xp.Next()) {
        if (!FeatureAddSub::shapesTouch(xp.Current(), support.getShape())) {
            loose.push_back(xp.Current());
        }
    }
    if (loose.empty()) {
        return floating;
    }
    for (std::size_t i = 1; i < shapes.size(); ++i) {
        for (const auto& solid : loose) {
            if (FeatureAddSub::shapesTouch(shapes[i].getShape(), solid)) {
                floating.push_back(i);
                break;
            }
        }
    }
    return floating;
}

/* Whether the original's tool (in the support's frame) touches nothing of the original's own base:
 * the original made a part of its own (Onshape's New, or an Add touching nothing). Its copies are
 * new parts too then, and none is dropped. A first feature has no base: its tool is the part.
 */
bool makesItsOwnPart(const FeatureAddSub& original, const Part::TopoShape& tool, const gp_Trsf& trsfInv)
{
    const Part::TopoShape base = original.getBaseTopoShape(/*silent=*/true);
    if (base.isNull() || base.countSubShapes(TopAbs_SOLID) == 0) {
        return true;
    }
    TopoDS_Shape moved = base.getShape().Moved(TopLoc_Location(trsfInv));
    return !FeatureAddSub::shapesTouch(tool.getShape(), moved);
}

/// Whether obj is a step of a MultiTransform: listed in one's Transformations
bool isListedStep(const Transformed& obj)
{
    for (auto const* user : obj.getInList()) {
        auto multi = freecad_cast<const MultiTransform*>(user);
        if (!multi) {
            continue;
        }
        const auto& steps = multi->Transformations.getValues();
        if (std::ranges::find(steps, &obj) != steps.end()) {
            return true;
        }
    }
    return false;
}

/// A pattern, mirror or MultiTransform with nothing to transform: red in Onshape's words
App::DocumentObjectExecReturn* nothingToTransform(const Transformed& obj)
{
    if (freecad_cast<const Mirrored*>(&obj)) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Select features to mirror.")
        );
    }
    if (freecad_cast<const MultiTransform*>(&obj)) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Select features to transform.")
        );
    }
    return new App::DocumentObjectExecReturn(
        QT_TRANSLATE_NOOP("Exception", "Select features to pattern.")
    );
}

std::string quoted(const App::DocumentObject* obj)
{
    return std::string("'") + obj->Label.getValue() + "'";
}

/// FreeCAD-CH ops#654 slice 8: the studio feature an original stands for: a studio feature (an
/// owner, outside every Body) or one of its steps; null for any other original
App::DocumentObject* studioOwnerOfOriginal(App::DocumentObject* obj)
{
    if (!obj) {
        return nullptr;
    }
    if (isStudioOwner(obj)) {
        return obj;
    }
    if (StudioList::isStep(obj)) {
        auto feature = freecad_cast<PartDesign::Feature*>(obj);
        return feature ? feature->StudioOwner.getValue() : nullptr;
    }
    return nullptr;
}

/** The step an owner picked as an original maps to in the pattern's part, or why it can't be
 * patterned there (ops#654 slice 8): a feature acting on another part or on several (Onshape cuts
 * every part at every instance, O7: a pattern across parts, a later slice), a Boolean between
 * parts, a failed step (a Remove that split its part among them: Onshape refuses it without
 * Reapply), an Intersect, a New feature (its copies are new parts, P6p), or a step after the
 * pattern */
std::string studioStepOf(
    App::DocumentObject* owner,
    const Transformed& pattern,
    Body* body,
    FeatureAddSub*& step
)
{
    const std::string name = quoted(owner);
    if (!body) {
        return name + " is a studio feature: a pattern of it belongs in a part";
    }
    if (freecad_cast<Boolean*>(owner)) {
        return name + " is a Boolean between parts: it can't be patterned";
    }
    // An Add that merges parts (ops#654 10.13, skeptic 4): its copies would merge too, which
    // patterns over parts decide (T1/T2); loud until then
    if (auto merges = freecad_cast<App::PropertyStringList*>(
            owner->getPropertyByName("StudioMergedParts")
        );
        merges && !merges->getValues().empty()) {
        return name + " merges parts into one (" + merges->getValues().front()
            + "): a pattern of an Add that merges parts comes later";
    }
    const std::vector<Body*> parts = studioScopeOf(owner);
    if (parts.size() > 1) {
        std::string names;
        for (auto part : parts) {
            names += (names.empty() ? "" : ", ") + quoted(part);
        }
        return name + " acts on " + std::to_string(parts.size()) + " parts (" + names
            + "): a pattern across parts comes later; pattern it in one part";
    }
    if (parts.empty()) {
        return name + " acts on no part";
    }
    if (parts.front() != body) {
        return name + " acts on " + quoted(parts.front()) + ", not on " + quoted(body)
            + ", the pattern's part";
    }
    step = freecad_cast<FeatureAddSub*>(StudioList::stepOf(owner, body));
    if (!step) {
        return name + " has no step in " + quoted(body);
    }
    const auto& group = body->Group.getValues();
    const auto stepAt = std::ranges::find(group, step);
    const auto patternAt = std::ranges::find(group, &pattern);
    if (patternAt != group.end() && stepAt > patternAt) {
        return name + " comes after the pattern";
    }
    if (step->Suppressed.getValue()) {
        return {};  // suppressed: it contributes nothing, as a suppressed original
    }
    if (step->isError()) {
        const std::string status = step->getStatusString();
        if (status.find("splits") != std::string::npos) {
            return name + " splits " + quoted(body)
                + ": a Remove that splits its part can't be copied (Reapply per instance comes "
                  "later)";
        }
        return name + " failed in " + quoted(body) + ": a failed feature can't be patterned";
    }
    if (step->getBooleanOperation() == FeatureAddSub::BooleanOperation::Common) {
        return name + " is an Intersect: patterning it comes later";
    }
    if (step->getBaseTopoShape(/*silent=*/true).isNull()) {
        return name + " makes a new part: a pattern of it makes new parts, which comes later";
    }
    return {};
}

/// One tool the copy engine copies at every instance: an original's, or an instance of a
/// pattern among the originals
struct PatternTool
{
    Part::TopoShape fuse;
    Part::TopoShape cut;
    FeatureAddSub* seed = nullptr;  ///< the feature whose tool this is (or is an instance of)
    Part::TopoShape seedFuse;       ///< the seed's own additive tool, in the same frame
};

/** The tools of a pattern's originals, in the pattern's frame (ops#654 slice 8, Onshape P2 and
 * P3): a feature's tool; a studio feature's: its step's in the pattern's part; a pattern's or
 * mirror's: its own instances, flattened (each of its originals' tools moved by each of its
 * transforms but the first), never its seeds */
struct ToolCollector
{
    Transformed& pattern;
    Body* body;
    gp_Trsf frame;         ///< the Body's frame to the pattern's
    gp_Trsf fromDocument;  ///< the document's frame to the pattern's
    Part::TopoShape part;  ///< the part at the pattern's place, in its frame
    bool nameInstances;
    /// Reapply on with every original's tool independent of the base (ops#654 T3): a copy is the
    /// instance re-run, so the copy rule (studioCopyRefusal) has nothing to refuse
    bool reapply = false;

    /// original's tools into out; checks: the transforms they undergo (for the copy rule)
    std::string add(
        App::DocumentObject* original,
        const std::vector<gp_Trsf>& checks,
        std::vector<PatternTool>& out,
        int depth
    )
    {
        if (auto owner = studioOwnerOfOriginal(original)) {
            FeatureAddSub* step = nullptr;
            if (std::string why = studioStepOf(owner, pattern, body, step); !why.empty()) {
                return why;
            }
            if (step->Suppressed.getValue()) {
                return {};
            }
            PatternTool tool;
            if (std::string why = plain(step, tool); !why.empty()) {
                return why;
            }
            const Part::TopoShape& shape = tool.fuse.isNull() ? tool.cut : tool.fuse;
            if (std::string why = reapply
                    ? std::string()
                    : studioCopyRefusal(step, shape, part, checks, fromDocument);
                !why.empty()) {
                return why;
            }
            out.push_back(tool);
            return {};
        }
        if (auto inner = freecad_cast<Transformed*>(original)) {
            return instances(*inner, checks, out, depth);
        }
        auto feature = freecad_cast<FeatureAddSub*>(original);
        if (!feature) {
            return QT_TRANSLATE_NOOP(
                "Exception",
                "Only additive and subtractive features can be transformed"
            );
        }
        PatternTool tool;
        if (std::string why = plain(feature, tool); !why.empty()) {
            return why;
        }
        out.push_back(tool);
        return {};
    }

    std::string plain(FeatureAddSub* feature, PatternTool& tool) const
    {
        Part::TopoShape fuseShape = pattern.makeTopoShape(false);
        Part::TopoShape cutShape = pattern.makeTopoShape(false);
        feature->getAddSubShape(fuseShape, cutShape);
        if (fuseShape.isNull() && cutShape.isNull()) {
            return QT_TRANSLATE_NOOP("Exception", "Shape of additive/subtractive feature is empty");
        }
        gp_Trsf trsf = frame.Multiplied(feature->getLocation().Transformation());
        if (!fuseShape.isNull()) {
            fuseShape = fuseShape.makeElementTransform(trsf);
        }
        if (!cutShape.isNull()) {
            cutShape = cutShape.makeElementTransform(trsf);
        }
        tool.fuse = fuseShape;
        tool.cut = cutShape;
        tool.seed = feature;
        tool.seedFuse = fuseShape;
        return {};
    }

    /// inner's own instances (a pattern among the originals), flattened
    std::string instances(
        Transformed& inner,
        const std::vector<gp_Trsf>& checks,
        std::vector<PatternTool>& out,
        int depth
    )
    {
        const std::string name = quoted(&inner);
        if (depth > 8) {
            return name + ": patterns nested too deep";
        }
        if (freecad_cast<MultiTransform*>(&inner)) {
            return name + " is a MultiTransform: it can't be an original";
        }
        if (static_cast<Transformed::Mode>(inner.TransformMode.getValue())
            != Transformed::Mode::Features) {
            return name + " transforms the whole shape: it can't be an original";
        }
        if (inner.getFeatureBody() != body) {
            return name + " is in another part";
        }
        if (inner.isError()) {
            return name + " failed: a failed feature can't be patterned";
        }
        const std::vector<App::DocumentObject*> originals = inner.getOriginals();
        if (originals.empty()) {
            return {};
        }
        std::vector<gp_Trsf> list;
        try {
            std::list<gp_Trsf> got = inner.getTransformations(originals);
            list.assign(got.begin(), got.end());
        }
        catch (const Base::Exception& e) {
            return name + ": " + e.what();
        }
        catch (const Standard_Failure& e) {
            return name + ": " + e.GetMessageString();
        }
        const auto skipped = inner.getSkippedPositions();
        const auto numbers = nameInstances
            ? instanceNumbers(inner.getTransformationSteps(), list.size())
            : std::vector<std::string>();
        // inner's transforms are in its support's frame: moved into the pattern's
        gp_Trsf innerFrame = frame;
        if (const Part::Feature* support = inner.getBaseObject(/*silent=*/true)) {
            innerFrame.Multiply(support->Shape.getShape().getShape().Location().Transformation());
        }
        const gp_Trsf innerFrameInv = innerFrame.Inverted();
        std::vector<std::pair<std::size_t, gp_Trsf>> moves;
        for (std::size_t position = 1; position < list.size(); ++position) {
            if (std::ranges::find(skipped, position) != skipped.end()) {
                continue;
            }
            moves.emplace_back(
                position,
                innerFrame.Multiplied(list[position]).Multiplied(innerFrameInv)
            );
        }
        // Its seeds' copies go through its moves, then through those of the patterns outside it
        std::vector<gp_Trsf> innerChecks;
        for (const gp_Trsf& check : checks) {
            for (const auto& move : moves) {
                innerChecks.push_back(check.Multiplied(move.second));
            }
        }
        std::vector<PatternTool> seeds;
        for (auto original : originals) {
            if (std::string why = add(original, innerChecks, seeds, depth + 1); !why.empty()) {
                return why;
            }
        }
        // An additive copy inner dropped (entirely off its part, ops#640 B3-3b) is no instance
        const TopoDS_Shape result = inner.Shape.getShape().getShape().Moved(TopLoc_Location(frame));
        const long tag = inner.namingTag() ? inner.namingTag() : inner.getID();
        auto copy = [&](const Part::TopoShape& shape, const std::pair<std::size_t, gp_Trsf>& move) {
            const std::string op = nameInstances
                ? std::string()
                : Data::indexSuffix(static_cast<int>(move.first) + 1);
            // inner's result shape (Feature::makeResultShape(), protected)
            Part::TopoShape moved = nameInstances
                ? inner.makeTopoShape(false)
                : Part::TopoShape(shape.Tag, shape.Hasher, shape.getHistoryAlgorithm());
            moved.makeElementTransform(shape, move.second, op.c_str());
            if (nameInstances) {
                moved.appendElementSection(tag, Part::OpCodes::Transformed, numbers[move.first]);
            }
            return moved;
        };
        for (const PatternTool& seed : seeds) {
            std::optional<bool> ownPart;
            for (const auto& move : moves) {
                PatternTool tool;
                tool.seed = seed.seed;
                tool.seedFuse = seed.seedFuse;
                if (!seed.fuse.isNull()) {
                    Part::TopoShape moved = copy(seed.fuse, move);
                    if (!FeatureAddSub::shapesTouch(moved.getShape(), result)) {
                        if (!ownPart) {
                            ownPart = makesItsOwnPart(*seed.seed, seed.seedFuse, frame);
                        }
                        if (!*ownPart) {
                            moved = Part::TopoShape();
                        }
                    }
                    tool.fuse = moved;
                }
                if (!seed.cut.isNull()) {
                    tool.cut = copy(seed.cut, move);
                }
                if (!tool.fuse.isNull() || !tool.cut.isNull()) {
                    out.push_back(tool);
                }
            }
        }
        return {};
    }
};

/// A pattern among the originals that an instance went through (flattened, Onshape P2): its move
/// in the outer pattern's frame and the instance's number in it (ops#654 T3)
struct InnerLevel
{
    Transformed* inner = nullptr;
    gp_Trsf move;
    std::size_t position = 0;
    std::string number;
};

/// One original a pattern with Reapply on makes at each instance (ops#654 T3)
struct ReapplyItem
{
    FeatureAddSub* seed = nullptr;         ///< a native feature, or a studio feature's step
    App::DocumentObject* named = nullptr;  ///< the feature messages name (the owner of a step)
    FeatureExtrude* rerun = nullptr;       ///< re-run at each instance; null: its tool is copied
    Hole* hole = nullptr;                  ///< a hole re-run at each instance
    DressUp* dressUp = nullptr;            ///< a chamfer or fillet re-run on each instance's edges
    gp_Trsf toPattern;                     ///< rerun's own frame to the pattern's
    Part::TopoShape tool;                  ///< the seed's tool, in the pattern's frame
    bool additive = true;
    std::vector<InnerLevel> levels;  ///< the patterns among the originals it is in, innermost first
    /// The T3 fix (oracle 9, R3): how many of levels (innermost first) re-run it, each with Reapply
    /// on while this pattern's is off; the outer ones copy what they made. 0: none, or all of
    /// them and this pattern too
    std::size_t rerunBy = 0;

    /// The move of the innermost count of levels, composed (all of them by default)
    gp_Trsf innerMove(std::size_t count = std::numeric_limits<std::size_t>::max()) const
    {
        gp_Trsf move;
        for (std::size_t i = 0; i < levels.size() && i < count; ++i) {
            move = levels[i].move.Multiplied(move);
        }
        return move;
    }
};

/// Whether computer ends Up to next (Onshape re-runs it at each instance, Reapply on or off:
/// oracle 9, R2)
bool endsUpToNext(const App::DocumentObject* computer)
{
    if (auto hole = freecad_cast<const Hole*>(computer)) {
        return std::strcmp(hole->DepthType.getValueAsString(), "UpToFirst") == 0;
    }
    if (auto ext = freecad_cast<const FeatureExtrude*>(computer)) {
        return std::strcmp(ext->Type.getValueAsString(), "UpToFirst") == 0
            || (std::strcmp(ext->SideType.getValueAsString(), "Two sides") == 0
                && std::strcmp(ext->Type2.getValueAsString(), "UpToFirst") == 0);
    }
    return false;
}

/// Whether computer, an extrusion or a hole, starts at a reference rather than at its profile's
/// plane (or an offset from it): rerunItem() can't re-run it
bool startsAtReference(const App::DocumentObject* computer)
{
    if (auto hole = freecad_cast<const Hole*>(computer)) {
        return std::strcmp(hole->StartType.getValueAsString(), "Reference") == 0;
    }
    if (auto ext = freecad_cast<const FeatureExtrude*>(computer)) {
        const std::string start = ext->StartType.getValueAsString();
        return start != "Profile plane" && start != "Offset";
    }
    return false;
}

/// Whether edges a and b coincide: their ends and their middle within tol of each other
bool sameEdge(const TopoDS_Shape& a, const TopoDS_Shape& b, double tol)
{
    if (a.IsNull() || b.IsNull() || a.ShapeType() != TopAbs_EDGE || b.ShapeType() != TopAbs_EDGE) {
        return false;
    }
    GProp_GProps pa;
    GProp_GProps pb;
    BRepGProp::LinearProperties(a, pa);
    BRepGProp::LinearProperties(b, pb);
    if (std::fabs(pa.Mass() - pb.Mass()) > tol) {
        return false;
    }
    BRepAdaptor_Curve curve(TopoDS::Edge(a));
    const gp_Pnt middle = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
    std::vector<gp_Pnt> points {middle, curve.Value(curve.FirstParameter()),
                                curve.Value(curve.LastParameter())};
    for (const gp_Pnt& point : points) {
        BRepExtrema_DistShapeShape distance(BRepBuilderAPI_MakeVertex(point).Vertex(), b);
        if (!distance.IsDone() || distance.Value() > tol) {
            return false;
        }
    }
    return true;
}

/// The type of a feature as a person reads it ("Thickness" for PartDesign::Thickness)
std::string typeName(const App::DocumentObject* obj)
{
    std::string name(obj->getTypeId().getName());
    if (const auto colons = name.rfind("::"); colons != std::string::npos) {
        name = name.substr(colons + 2);
    }
    return name;
}

/** The originals of a pattern, flattened as ToolCollector does (Onshape P2, P3), each with how an
 * instance is made (ops#654 T3, notes/patterns-design.md 3.3). Where Reapply is on: an extrusion
 * whose tool depends on the base (Up to next, last, face, vertex or shape, Through all) is re-run
 * at each instance against the part as it grows; a Blind, Two lengths or Symmetric extrusion's tool
 * is the same wherever it goes, so its copy is the re-run; anything else is refused loudly. The
 * T3 fix (Onshape oracle 9): each pattern follows its own Reapply (R3): an original is re-run at
 * this pattern's instances only when this pattern and every pattern among the originals it goes
 * through have Reapply on; when only the innermost ones have, it is re-run where they make it and
 * the others copy that; when the innermost has it off, the seed's tool is copied (refused where
 * the copy may differ from Onshape's, studioCopyRefusal()). An Up to next seed is re-run at every
 * instance, Reapply on or off (R2) */
struct ReapplyCollector
{
    Transformed& pattern;
    Body* body;
    gp_Trsf frame;         ///< the Body's frame to the pattern's
    gp_Trsf fromDocument;  ///< the document's frame to the pattern's
    bool nameInstances;
    ToolCollector& tools;
    bool reapplyOn = false;        ///< this pattern's Reapply
    std::vector<gp_Trsf> outer;    ///< this pattern's instances (the original left out)

    std::string add(
        App::DocumentObject* original,
        const std::vector<InnerLevel>& levels,
        std::vector<ReapplyItem>& out,
        int depth
    )
    {
        if (auto owner = studioOwnerOfOriginal(original)) {
            FeatureAddSub* step = nullptr;
            if (std::string why = studioStepOf(owner, pattern, body, step); !why.empty()) {
                return why;
            }
            if (step->Suppressed.getValue()) {
                return {};
            }
            return item(step, owner, levels, out);
        }
        if (auto inner = freecad_cast<Transformed*>(original)) {
            return instances(*inner, levels, out, depth);
        }
        auto feature = freecad_cast<FeatureAddSub*>(original);
        if (!feature) {
            return QT_TRANSLATE_NOOP(
                "Exception",
                "Only additive and subtractive features can be transformed"
            );
        }
        return item(feature, feature, levels, out);
    }

    std::string item(
        FeatureAddSub* seed,
        App::DocumentObject* computer,
        const std::vector<InnerLevel>& levels,
        std::vector<ReapplyItem>& out
    )
    {
        std::size_t on = 0;
        for (const InnerLevel& level : levels) {
            if (!level.inner->Reapply.getValue()) {
                break;
            }
            ++on;
        }
        // Up to next is re-run with Reapply off too (oracle 9 R2), but from a reference it can't
        // be yet: with Reapply off it is then copied, as integration does (review prline-b4-r1 T2)
        if ((endsUpToNext(computer) && !startsAtReference(computer))
            || (on == levels.size() && reapplyOn)) {
            return rerunItem(seed, computer, levels, out);
        }
        const std::size_t before = out.size();
        if (on == 0) {
            // Made with Reapply off: a copy of the seed's tool (R3), unless it may differ from
            // Onshape's instance
            if (std::string why = copied(seed, computer, levels, out); !why.empty()) {
                return why;
            }
            if (out.size() == before) {
                return {};
            }
            const ReapplyItem& it = out.back();
            std::vector<gp_Trsf> checks;
            const gp_Trsf inner = it.innerMove();
            for (const gp_Trsf& t : outer) {
                checks.push_back(t.Multiplied(inner));
            }
            return studioCopyRefusal(seed, it.tool, tools.part, checks, fromDocument);
        }
        // Re-run by the innermost patterns, whose Reapply is on; copied by the others
        if (std::string why = rerunItem(seed, computer, levels, out); !why.empty()) {
            return why;
        }
        if (out.size() == before) {
            return {};
        }
        ReapplyItem& it = out.back();
        if (it.dressUp) {
            return quoted(computer) + " is re-run at each instance of "
                + quoted(levels[on - 1].inner) + " (Reapply on), and copying a "
                + typeName(computer) + " re-run there (" + quoted(&pattern)
                + ", Reapply off) isn't available yet";
        }
        if (it.rerun || it.hole) {
            it.rerunBy = on;
        }
        return {};
    }

    /// An original as a pattern with Reapply on makes it at each instance
    std::string rerunItem(
        FeatureAddSub* seed,
        App::DocumentObject* computer,
        const std::vector<InnerLevel>& levels,
        std::vector<ReapplyItem>& out
    )
    {
        const std::string name = quoted(computer);
        if (auto hole = freecad_cast<Hole*>(computer)) {
            return holeItem(seed, hole, levels, out);
        }
        if (auto revolved = freecad_cast<Revolved*>(computer)) {
            // By an angle its tool is the same wherever it goes (patterns-design 3.3): the copy
            // is the re-run. Up to a face, a vertex, next or last: not yet
            // Both sides when it has two (review prline-b4-r1 T3: side 2 up to a face was copied)
            auto byAngle = [](const std::string& type) {
                return type == "Angle" || type == "?TwoAngles";
            };
            const std::string type = revolved->Type.getValueAsString();
            const std::string type2 = revolved->Type2.getValueAsString();
            const bool twoSides =
                std::strcmp(revolved->SideType.getValueAsString(), "Two sides") == 0;
            if (byAngle(type) && (type == "?TwoAngles" || !twoSides || byAngle(type2))) {
                return copied(seed, computer, levels, out);
            }
            if (!byAngle(type)) {
                return "Reapply isn't available for a revolve that ends " + endName(type)
                    + " yet: " + name + " can only be copied (Reapply off)";
            }
            return "Reapply isn't available for a revolve whose second side ends " + endName(type2)
                + " yet: " + name + " can only be copied (Reapply off)";
        }
        if (freecad_cast<Pipe*>(computer) || freecad_cast<Loft*>(computer)
            || freecad_cast<Helix*>(computer) || freecad_cast<FeaturePrimitive*>(computer)) {
            // A sweep, loft or helix along its own path, a primitive: its tool doesn't depend on
            // the base, so its copy is the re-run
            return copied(seed, computer, levels, out);
        }
        if (auto dressUp = freecad_cast<DressUp*>(computer);
            dressUp && (freecad_cast<Chamfer*>(dressUp) || freecad_cast<Fillet*>(dressUp))) {
            auto chamfer = freecad_cast<Chamfer*>(dressUp);
            auto fillet = freecad_cast<Fillet*>(dressUp);
            if ((chamfer && chamfer->UseAllEdges.getValue())
                || (fillet && fillet->UseAllEdges.getValue())) {
                return "Reapply isn't available for a " + typeName(computer)
                    + " of all edges yet: " + name + " can only be copied (Reapply off)";
            }
            ReapplyItem it;
            it.seed = seed;
            it.named = computer;
            it.levels = levels;
            it.dressUp = dressUp;
            out.push_back(it);
            return {};
        }
        auto ext = freecad_cast<FeatureExtrude*>(computer);
        if (!ext) {
            // A studio feature that is a shape object (a primitive): its tool is its own shape,
            // the same wherever it goes, so its copy is the re-run
            if (computer != seed && !freecad_cast<PartDesign::Feature*>(computer)) {
                return copied(seed, computer, levels, out);
            }
            return "Reapply isn't available for " + typeName(computer) + " yet: " + name
                + " can only be copied (Reapply off)";
        }
        if (seed->getBooleanOperation() == FeatureAddSub::BooleanOperation::Common) {
            return name + " is an Intersect: Reapply isn't available for it yet";
        }
        const std::string start = ext->StartType.getValueAsString();
        if (start != "Profile plane" && start != "Offset") {
            return name + " starts at a reference: Reapply isn't available for it yet";
        }
        PatternTool tool;
        if (std::string why = tools.plain(seed, tool); !why.empty()) {
            return why;
        }
        ReapplyItem it;
        it.seed = seed;
        it.named = computer;
        it.levels = levels;
        it.additive = !tool.fuse.isNull();
        it.tool = it.additive ? tool.fuse : tool.cut;
        auto blind = [](const char* type) {
            return std::strcmp(type, "Length") == 0 || std::strcmp(type, "?TwoLengths") == 0;
        };
        const bool twoSides = std::strcmp(ext->SideType.getValueAsString(), "Two sides") == 0;
        if (!blind(ext->Type.getValueAsString())
            || (twoSides && !blind(ext->Type2.getValueAsString()))) {
            it.rerun = ext;
            it.toPattern = toolFrame(seed, computer);
        }
        out.push_back(it);
        return {};
    }

    /// An end type as the dialogs name it
    static std::string endName(const std::string& type)
    {
        if (type == "UpToFirst") {
            return "up to next";
        }
        if (type == "UpToLast") {
            return "up to last";
        }
        if (type == "UpToFace") {
            return "up to a face";
        }
        if (type == "UpToVertex") {
            return "up to a vertex";
        }
        if (type == "UpToShape") {
            return "up to a shape";
        }
        if (type == "ThroughAll") {
            return "through all";
        }
        return type;
    }

    /// The frame computer's tool is made in, to the pattern's: a Body feature's placement in its
    /// Body; a studio feature's in the document, as its steps take its tool (FeatureApply::toolOf())
    gp_Trsf toolFrame(FeatureAddSub* seed, App::DocumentObject* computer) const
    {
        return seed == computer ? frame.Multiplied(seed->getLocation().Transformation())
                                : fromDocument.Multiplied(Part::TopoShape::convert(
                                      App::GeoFeature::getGlobalPlacement(computer).toMatrix()
                                  ));
    }

    /// A hole: of a given depth from its profile, its tool is the same wherever it goes (copied);
    /// through all, up to next or a face, or from the part's surface: re-run at each instance
    std::string holeItem(
        FeatureAddSub* seed,
        Hole* hole,
        const std::vector<InnerLevel>& levels,
        std::vector<ReapplyItem>& out
    )
    {
        const std::string name = quoted(hole);
        const std::string start = hole->StartType.getValueAsString();
        if (start == "Reference") {
            return name + " starts at a reference: Reapply isn't available for it yet";
        }
        const std::string depth = hole->DepthType.getValueAsString();
        if (depth == "Dimension" && start != "Part") {
            return copied(seed, hole, levels, out);
        }
        PatternTool tool;
        if (std::string why = tools.plain(seed, tool); !why.empty()) {
            return why;
        }
        ReapplyItem it;
        it.seed = seed;
        it.named = hole;
        it.levels = levels;
        it.additive = !tool.fuse.isNull();
        it.tool = it.additive ? tool.fuse : tool.cut;
        it.hole = hole;
        it.toPattern = toolFrame(seed, hole);
        out.push_back(it);
        return {};
    }

    /// An original whose tool doesn't depend on the base: copied at each instance
    std::string copied(
        FeatureAddSub* seed,
        App::DocumentObject* computer,
        const std::vector<InnerLevel>& levels,
        std::vector<ReapplyItem>& out
    )
    {
        PatternTool tool;
        if (std::string why = tools.plain(seed, tool); !why.empty()) {
            return why;
        }
        ReapplyItem it;
        it.seed = seed;
        it.named = computer;
        it.levels = levels;
        it.additive = !tool.fuse.isNull();
        it.tool = it.additive ? tool.fuse : tool.cut;
        out.push_back(it);
        return {};
    }

    /// inner's own instances (a pattern among the originals), flattened: its originals at each
    std::string instances(
        Transformed& inner,
        const std::vector<InnerLevel>& levels,
        std::vector<ReapplyItem>& out,
        int depth
    )
    {
        const std::string name = quoted(&inner);
        if (depth > 8) {
            return name + ": patterns nested too deep";
        }
        if (freecad_cast<MultiTransform*>(&inner)) {
            return name + " is a MultiTransform: it can't be an original";
        }
        if (static_cast<Transformed::Mode>(inner.TransformMode.getValue())
            != Transformed::Mode::Features) {
            return name + " transforms the whole shape: it can't be an original";
        }
        if (inner.getFeatureBody() != body) {
            return name + " is in another part";
        }
        if (inner.isError()) {
            return name + " failed: a failed feature can't be patterned";
        }
        const std::vector<App::DocumentObject*> originals = inner.getOriginals();
        if (originals.empty()) {
            return {};
        }
        std::vector<gp_Trsf> list;
        try {
            std::list<gp_Trsf> got = inner.getTransformations(originals);
            list.assign(got.begin(), got.end());
        }
        catch (const Base::Exception& e) {
            return name + ": " + e.what();
        }
        catch (const Standard_Failure& e) {
            return name + ": " + e.GetMessageString();
        }
        const auto skipped = inner.getSkippedPositions();
        const auto numbers = nameInstances
            ? instanceNumbers(inner.getTransformationSteps(), list.size())
            : std::vector<std::string>();
        gp_Trsf innerFrame = frame;
        if (const Part::Feature* support = inner.getBaseObject(/*silent=*/true)) {
            innerFrame.Multiply(support->Shape.getShape().getShape().Location().Transformation());
        }
        const gp_Trsf innerFrameInv = innerFrame.Inverted();
        for (std::size_t position = 1; position < list.size(); ++position) {
            if (std::ranges::find(skipped, position) != skipped.end()) {
                continue;
            }
            InnerLevel level;
            level.inner = &inner;
            level.move = innerFrame.Multiplied(list[position]).Multiplied(innerFrameInv);
            level.position = position;
            level.number = nameInstances ? numbers[position] : std::string();
            std::vector<InnerLevel> deeper {level};
            deeper.insert(deeper.end(), levels.begin(), levels.end());
            for (auto original : originals) {
                if (std::string why = add(original, deeper, out, depth + 1); !why.empty()) {
                    return why;
                }
            }
        }
        return {};
    }
};

}  // namespace

namespace PartDesign
{
// FeatureExtrude.cpp (FreeCAD-CH ops#654 T3; declared where used): feature's tool re-solved at a
// pattern's instance, in the feature's frame
PartDesignExport Part::TopoShape reapplyExtrusion(
    FeatureExtrude* feature,
    const gp_Trsf& toSeed,
    const Part::TopoShape& base,
    const std::string& partLabel,
    std::string& why
);

// FeatureHole.cpp and FeatureDressUp.cpp (FreeCAD-CH ops#654 T3; declared where used)
PartDesignExport Part::TopoShape reapplyHole(
    Hole* hole,
    const gp_Trsf& toSeed,
    const Part::TopoShape& base,
    std::string& why
);
PartDesignExport Part::TopoShape reapplyDressUp(
    DressUp* feature,
    const Part::TopoShape& base,
    const std::vector<Part::TopoShape>& edges,
    std::string& why
);

extern bool getPDRefineModelParameter();

PROPERTY_SOURCE(PartDesign::Transformed, PartDesign::FeatureRefine)

std::array<char const*, 3> transformModeEnums = {"Features", "Whole shape", nullptr};
std::array<char const*, 3> patternTypeEnums = {"Feature", "Part", nullptr};

Transformed::Transformed()
{
    ADD_PROPERTY(Originals, (nullptr));
    Originals.setSize(0);
    // FreeCAD-CH ops#654 slice 8: an original may be a studio feature, outside the pattern's Body
    // (its step in the Body is what is copied)
    Originals.setScope(App::LinkScope::Global);
    Placement.setStatus(App::Property::ReadOnly, true);

    ADD_PROPERTY(TransformMode, (static_cast<long>(Mode::Features)));
    TransformMode.setEnums(transformModeEnums.data());

    // FreeCAD-CH ops#655 (T1-T3)
    ADD_PROPERTY_TYPE(PatternType, (0L), "Studio", App::Prop_Hidden, "Pattern features or parts");
    PatternType.setEnums(patternTypeEnums.data());
    ADD_PROPERTY_TYPE(
        Reapply,
        (false),
        "Studio",
        App::Prop_Hidden,
        "Recompute each original's tool at each instance"
    );
    ADD_PROPERTY_TYPE(
        StudioEntities,
        (),
        "Studio",
        App::Prop_Hidden,
        "A Part pattern's parts, by part id"
    );
}

void Transformed::positionBySupport()
{
    // TODO May be here better to throw exception (silent=false) (2015-07-27, Fat-Zer)
    Part::Feature* support = getBaseObject(/* silent =*/true);
    if (support) {
        this->Placement.setValue(support->Placement.getValue());
    }
}

Part::Feature* Transformed::getBaseObject(bool silent) const
{
    Part::Feature* rv = Feature::getBaseObject(/* silent = */ true);
    if (rv) {
        return rv;
    }

    const char* err = nullptr;
    const std::vector<App::DocumentObject*>& originals = getOriginals();
    // NOTE: may be here supposed to be last origin but in order to keep the old behaviour keep here
    // first
    App::DocumentObject* firstOriginal = originals.empty() ? nullptr : originals.front();
    if (firstOriginal) {
        rv = freecad_cast<Part::Feature*>(firstOriginal);
        if (!rv) {
            err = QT_TRANSLATE_NOOP(
                "Exception",
                "Transformation feature Linked object is not a Part object"
            );
        }
    }
    else {
        if (freecad_cast<const Mirrored*>(this)) {
            err = QT_TRANSLATE_NOOP("Exception", "No features selected to be mirrored.");
        }
        // FreeCAD-CH (ops#655 T6): the curve pattern is a pattern too
        else if (freecad_cast<const LinearPattern*>(this) || freecad_cast<const PolarPattern*>(this)
                 || freecad_cast<const CurvePattern*>(this)) {
            err = QT_TRANSLATE_NOOP("Exception", "No features selected to be patterned.");
        }
        else {
            err = QT_TRANSLATE_NOOP("Exception", "No features selected to be transformed.");
        }
    }

    if (!silent && err) {
        throw Base::RuntimeError(err);
    }

    return rv;
}

std::vector<App::DocumentObject*> Transformed::getSortedOriginals() const
{
    std::vector<DocumentObject*> originals = Originals.getValues();

    // Sort originals in chronological order of the body's group history
    if (auto body = getFeatureBody()) {
        const auto& group = body->Group.getValues();
        std::unordered_map<const DocumentObject*, size_t> indexMap;
        for (size_t i = 0; i < group.size(); ++i) {
            indexMap[group[i]] = i;
        }
        // A studio feature sorts at its step in this Body (ops#654 slice 8)
        auto inBody = [body](DocumentObject* obj) -> const DocumentObject* {
            if (obj && isStudioOwner(obj)) {
                if (auto step = StudioList::stepOf(obj, body)) {
                    return step;
                }
            }
            return obj;
        };
        std::ranges::sort(originals, [&indexMap, &inBody](DocumentObject* a, DocumentObject* b) {
            auto itA = indexMap.find(inBody(a));
            auto itB = indexMap.find(inBody(b));
            size_t idxA = (itA != indexMap.end()) ? itA->second : std::numeric_limits<size_t>::max();
            size_t idxB = (itB != indexMap.end()) ? itB->second : std::numeric_limits<size_t>::max();
            return idxA < idxB;
        });
    }

    return originals;
}

std::vector<App::DocumentObject*> Transformed::getOriginals() const
{
    auto const mode = static_cast<Mode>(TransformMode.getValue());

    if (mode == Mode::WholeShape) {
        return {};
    }

    std::vector<DocumentObject*> originals = getSortedOriginals();

    const auto isSuppressed = [](const DocumentObject* obj) {
        auto feature = freecad_cast<Feature*>(obj);

        return feature != nullptr && feature->Suppressed.getValue();
    };

    // Remove suppressed features from the list so the transformations behave as if they are not
    // there
    auto [first, last] = std::ranges::remove_if(originals, isSuppressed);
    originals.erase(first, last);

    return originals;
}

App::DocumentObject* Transformed::getSketchObject() const
{
    std::vector<DocumentObject*> originals = getOriginals();
    DocumentObject const* firstOriginal = !originals.empty() ? originals.front() : nullptr;

    if (auto feature = freecad_cast<PartDesign::ProfileBased*>(firstOriginal)) {
        return feature->getVerifiedSketch(true);
    }
    if (freecad_cast<PartDesign::FeatureAddSub*>(firstOriginal)) {
        return nullptr;
    }
    if (auto pattern = freecad_cast<LinearPattern*>(this)) {
        return pattern->Direction.getValue();
    }
    if (auto pattern = freecad_cast<PolarPattern*>(this)) {
        return pattern->Axis.getValue();
    }
    if (auto pattern = freecad_cast<Mirrored*>(this)) {
        return pattern->MirrorPlane.getValue();
    }

    return nullptr;
}

void Transformed::Restore(Base::XMLReader& reader)
{
    PartDesign::Feature::Restore(reader);
}

bool Transformed::isMultiTransformChild() const
{
    // Checking for a MultiTransform in the dependency list is not reliable on initialization
    // because the dependencies are only established after creation.
    /*
    for (auto const* obj : getInList()) {
        auto mt = freecad_cast<PartDesign::MultiTransform*>(obj);
        if (!mt) {
            continue;
        }

        auto const transfmt = mt->Transformations.getValues();
        if (std::find(transfmt.begin(), transfmt.end(), this) != transfmt.end()) {
            return true;
        }
    }
    */

    // instead check for default property values because these are invalid for a standalone
    // transform feature. This will mislabel standalone features during the initialization phase.
    if (TransformMode.getValue() == 0 && Originals.getValue().empty()) {
        return true;
    }

    return false;
}

bool Transformed::isOutOfChain() const
{
    if (!isMultiTransformChild()) {
        // Originals listed, or a whole-shape transform
        return false;
    }
    if (!BaseFeature.getValue()) {
        // A pattern being filled in, or a step made in a MultiTransform (ops#579, ops#590)
        return true;
    }
    // FreeCAD-CH (ops#640, F3): one that had a place in the chain and whose Originals went (the
    // original deleted, or emptied in its dialog) stays there and fails, so its base passes
    // through, unless a MultiTransform lists it as a step: converting a pattern sets the
    // MultiTransform's Transformations before it empties the pattern's Originals (the steps loop
    // in onChanged() leaves the chain then). The in-list holds the MultiTransform as soon as its
    // Transformations are set (PropertyLinkList::setValues), and this is asked only for a
    // transform with a BaseFeature and nothing to pattern, so the walk is rare
    const App::DocumentObject* self = this;
    auto isSelf = [self](const App::DocumentObject* step) {
        return step == self;
    };
    for (auto user : getInList()) {
        auto multi = freecad_cast<MultiTransform*>(user);
        if (multi && multi != self
            && std::ranges::any_of(multi->Transformations.getValues(), isSelf)) {
            return true;
        }
    }
    return false;
}

void Transformed::leaveChain(Body* body)
{
    // The solid after it builds on the one before it, as when it is removed (this one no longer
    // counts as a solid there), and it has no base, as a step made in a MultiTransform has none
    auto next = freecad_cast<PartDesign::Feature*>(body->getNextSolidFeature(this));
    if (next && next->BaseFeature.getValue() == this) {
        body->setBaseProperty(next);
    }
    if (BaseFeature.getValue()) {
        BaseFeature.setValue(nullptr);
    }
}

void Transformed::handleChangedPropertyType(
    Base::XMLReader& reader,
    const char* TypeName,
    App::Property* prop
)
{
    // The property 'Angle' of PolarPattern has changed from PropertyFloat
    // to PropertyAngle and the property 'Length' has changed to PropertyLength.
    Base::Type inputType = Base::Type::fromName(TypeName);
    if (auto property = freecad_cast<App::PropertyFloat*>(prop);
        property != nullptr && inputType.isDerivedFrom(App::PropertyFloat::getClassTypeId())) {
        // Do not directly call the property's Restore method in case the implementation
        // has changed. So, create a temporary PropertyFloat object and assign the value.
        App::PropertyFloat floatProp;
        floatProp.Restore(reader);
        property->setValue(floatProp.getValue());
    }
    else {
        PartDesign::Feature::handleChangedPropertyType(reader, TypeName, prop);
    }
}

short Transformed::mustExecute() const
{
    if (Originals.isTouched() || TransformMode.isTouched()) {
        return 1;
    }
    return PartDesign::Feature::mustExecute();
}

App::DocumentObjectExecReturn* Transformed::recomputePreview()
{
    const auto mode = static_cast<Mode>(TransformMode.getValue());

    // A pattern of nothing is out of the chain, with no base (ops#590): nothing to preview, and
    // its edit must still open so that originals can be picked (ops#607)
    const Part::Feature* supportFeature = getBaseObject(/* silent = */ true);
    if (!supportFeature) {
        PreviewShape.setValue(TopoDS_Shape());
        return App::DocumentObject::StdReturn;
    }
    const Part::TopoShape supportShape = supportFeature->Shape.getShape();

    if (supportShape.isNull()) {
        return App::DocumentObject::StdReturn;
    }

    gp_Trsf supportTransform = supportShape.getShape().Location().Transformation();

    const auto makeCompoundOfToolShapes = [this, &supportTransform]() {
        BRep_Builder builder;
        TopoDS_Compound compound;

        builder.MakeCompound(compound);
        for (auto original : getOriginals()) {
            if (auto owner = studioOwnerOfOriginal(original)) {
                original = StudioList::stepOf(owner, getFeatureBody());  // ops#654 slice 8
            }
            if (auto* feature = freecad_cast<FeatureAddSub*>(original)) {
                auto shape = feature->AddSubShape.getShape();

                gp_Trsf trsf = supportTransform.Inverted().Multiplied(
                    feature->getLocation().Transformation()
                );

                if (shape.isNull()) {
                    continue;
                }

                shape = shape.makeElementTransform(trsf);

                builder.Add(compound, shape.getShape());
            }
        }

        return compound;
    };

    switch (mode) {
        case Mode::Features:
            PreviewShape.setValue(makeCompoundOfToolShapes());
            return StdReturn;

        case Mode::WholeShape: {
            auto shape = getBaseTopoShape();
            shape = shape.makeElementTransform(supportTransform.Inverted());

            PreviewShape.setValue(shape.getShape());

            return StdReturn;
        }

        default:
            return FeatureRefine::recomputePreview();
    }
}

void Transformed::onChanged(const App::Property* prop)
{
    if (prop == &TransformMode) {
        auto const mode = static_cast<Mode>(TransformMode.getValue());
        Originals.setStatus(App::Property::Status::Hidden, mode == Mode::WholeShape);
    }
    // FreeCAD-CH (ops#579, ops#590): a transform is a solid feature of its Body only while its
    // Originals or mode are set; a new one counts as a MultiTransform step, so its Body doesn't
    // link its base when it is added. The chain follows here when that changes, in any position:
    // linked first in execute(), a transform and its base made in one recompute ran in the wrong
    // order (ops#579), and of two transforms added before a solid before one recompute, the first
    // linked the second, which then didn't reroute the solid (ops#590)
    auto multi = freecad_cast<MultiTransform*>(this);
    const App::Property* steps = multi ? &multi->Transformations : nullptr;
    if ((prop == &Originals || prop == &TransformMode || prop == &BaseFeature || prop == steps)
        && !isRestoring() && !testStatus(App::ObjectStatus::Remove)) {
        auto doc = getDocument();
        auto body = getFeatureBody();
        if (doc && body && !doc->isPerformingTransaction() && body->hasObject(this)
            && !reorderWriting()) {
            if (prop == steps) {
                // A MultiTransform's steps are steps: it gives them their originals and mode, and
                // a transform listed here with its own (converting a pattern; a whole-shape one
                // keeps its mode) would stay a solid feature, its base this MultiTransform: a
                // cycle (ops#590). Emptied, each leaves the chain (below)
                for (auto obj : multi->Transformations.getValues()) {
                    auto step = freecad_cast<Transformed*>(obj);
                    if (!step || freecad_cast<MultiTransform*>(step)) {
                        continue;
                    }
                    if (!step->Originals.getValues().empty()) {
                        step->Originals.setValues({});
                    }
                    if (step->TransformMode.getValue() != static_cast<long>(Mode::Features)) {
                        step->TransformMode.setValue(static_cast<long>(Mode::Features));
                    }
                    // One whose Originals were gone already (a pattern of a deleted original,
                    // still in the chain: ops#640, F3) got no change above to take it out
                    if (step->BaseFeature.getValue() && step->getFeatureBody() == body
                        && !Body::isSolidFeature(step)) {
                        step->leaveChain(body);
                    }
                }
            }
            else if (prop == &BaseFeature) {
                // A base copied from a neighbour the link below rerouted onto this one:
                // converting a pattern to a MultiTransform sets the MultiTransform's Originals and
                // mode, which reroutes the pattern onto it, then copies the pattern's BaseFeature.
                // The base before it in the chain, where a solid's base always is (review pr579-r5
                // T-R5-1)
                if (BaseFeature.getValue() == this) {
                    BaseFeature.setValue(
                        Body::isSolidFeature(this) ? body->getPrevSolidFeature(this) : nullptr
                    );
                }
            }
            else if (Body::isSolidFeature(this)) {
                // Into the chain: its base is the solid before it, and the solid after it builds
                // on it
                if (!BaseFeature.getValue()) {
                    body->setBaseProperty(this);
                }
            }
            else {
                // Out of the chain (a MultiTransform's step, or a new pattern of nothing; one in
                // the chain whose Originals went stays a solid feature: isOutOfChain(), ops#640).
                // Converting a pattern makes it the MultiTransform's step after the
                // MultiTransform's link rerouted it onto it: its base would be a cycle (ops#590)
                leaveChain(body);
            }
        }
    }

    FeatureRefine::onChanged(prop);
}

// StudioList.cpp (FreeCAD-CH ops#654 slice 9; declared where used)
PartDesignExport std::vector<Body*> studioPartPatternSources(const App::DocumentObject* owner);
PartDesignExport void studioSetPartMirrorConsumes(App::DocumentObject* owner, bool consumes);

namespace
{

bool touches(const TopoDS_Shape& a, const TopoDS_Shape& b)
{
    BRepExtrema_DistShapeShape distance(a, b);
    return distance.IsDone() && distance.Value() <= Precision::Confusion();
}

/** A part pattern as a studio feature (FreeCAD-CH ops#654 slice 9, notes/patterns-design.md
 * 3.1): the part mirror. Outside every Body, its steps apply its tool (FeatureApply::toolOf):
 * New, a new part holding the copy (studioNewPart); Add, Remove, Intersect, one step per scope
 * part. Its Operation is a dynamic enumeration of FreeCAD's words (Union, Subtraction, Common),
 * as the Result row writes; New is a Union whose scope is the parts it made. Its own shape stays
 * empty; it fails loudly when its tool can't be made or its scope resolves to nothing.
 * Add (Onshape oracle 9, R4): the copy merges into the scope part it touches (the survivor); a
 * copy touching none would be a new part (P6p), and one touching two would merge parts, which is
 * not done yet: both refused loudly. The source part outside the scope is consumed, merged into
 * the survivor with the copy, exactly when it touches the copy or the survivor; it is decided here
 * (StudioConsumesSource) and the list's projection follows after the recompute. Remove,
 * Intersect and New never consume it. */
App::DocumentObjectExecReturn* executeStudioPartPattern(Transformed& pattern)
{
    pattern.Shape.setValue(Part::TopoShape());
    studioSetPartMirrorConsumes(&pattern, false);  // a failed feature contributes nothing
    std::string why;
    const Part::TopoShape tool = studioPatternTool(&pattern, nullptr, &why);
    if (tool.isNull()) {
        return new App::DocumentObjectExecReturn(why, &pattern);
    }
    const std::vector<Body*> scope = studioScopeOf(&pattern);
    if (scope.empty()) {
        return new App::DocumentObjectExecReturn("No merge scope selected", &pattern);
    }
    auto operation =
        freecad_cast<App::PropertyEnumeration*>(pattern.getPropertyByName("Operation"));
    const char* value = operation ? operation->getValueAsString() : nullptr;
    const bool isNew = std::ranges::all_of(scope, [&pattern](const Body* part) {
        return part->StudioMadeBy.getValue() == &pattern;
    });
    if ((value && std::string(value) != "Union") || isNew) {
        return App::DocumentObject::StdReturn;
    }
    std::vector<const Body*> touched;
    Part::TopoShape survivorBase;
    bool anyBase = false;
    for (auto part : scope) {
        const Part::TopoShape base = studioBaseAt(&pattern, part);
        if (base.isNull()) {
            continue;
        }
        anyBase = true;
        if (touches(tool.getShape(), base.getShape())) {
            touched.push_back(part);
            survivorBase = base;
        }
    }
    if (anyBase && touched.empty()) {
        // Onshape oracle 9 R4: a copy touching no scope part is a new part, made by the command
        // (P6p); until then the mirror fails loudly
        if (std::string left = unclaimedLeftovers(&pattern); !left.empty()) {
            return new App::DocumentObjectExecReturn(left, &pattern);
        }
        return App::DocumentObject::StdReturn;
    }
    if (touched.size() > 1) {
        std::string names;
        for (auto part : touched) {
            names += std::string(names.empty() ? "" : " and ") + "'" + part->Label.getValue() + "'";
        }
        return new App::DocumentObjectExecReturn(
            "The mirrored copy touches " + names
                + ": an Add that would merge parts is not done yet; keep one of them in the "
                  "merge scope",
            &pattern
        );
    }
    if (touched.size() == 1) {
        const std::vector<Body*> sources = studioPartPatternSources(&pattern);
        const Body* source = sources.empty() ? nullptr : sources.front();
        if (source && std::ranges::find(scope, source) == scope.end()) {
            const Part::TopoShape sourceBase = studioBaseAt(&pattern, source);
            if (!sourceBase.isNull()
                && (touches(sourceBase.getShape(), tool.getShape())
                    || touches(sourceBase.getShape(), survivorBase.getShape()))) {
                studioSetPartMirrorConsumes(&pattern, true);
            }
        }
    }
    return App::DocumentObject::StdReturn;
}

}  // namespace

App::DocumentObjectExecReturn* Transformed::execute()
{
    // FreeCAD-CH ops#654 slice 9: a part pattern in a studio's list computes only what its steps
    // apply (the part mirror's tool); here it checks it
    if (runsAsStudioOwner(this) && PatternType.getValue() == 1) {
        return executeStudioPartPattern(*this);
    }
    if (isOutOfChain()) {
        // FreeCAD-CH (ops#640): a MultiTransform's step computes nothing of its own (its
        // MultiTransform runs it), and a reorder's parked Originals have their own message, before
        // this runs. A new pattern or mirror with nothing picked is red, as Onshape's is, and stays
        // out of the chain: it contributes nothing
        if (isListedStep(*this) || hasParkedOriginals(this)) {
            return App::DocumentObject::StdReturn;
        }
        return nothingToTransform(*this);
    }

    auto const mode = static_cast<Mode>(TransformMode.getValue());

    if (mode == Mode::Features && Originals.getValues().empty()) {
        // FreeCAD-CH (ops#640, F3): in the chain with nothing to pattern (its original deleted,
        // or the list emptied in its dialog). It fails, red in Onshape's words as a new one is,
        // and the failure rule passes its base through: the Body shows the model without the
        // pattern, and edits above reach it. Returned StdReturn, it kept its last shape, the
        // deleted original's copies included
        return nothingToTransform(*this);
    }

    std::vector<DocumentObject*> originals = getOriginals();

    // FreeCAD-CH ops#654 slice 8: of studio features every one suppressed, it passes its base
    // through (below, with no tool), as their suppressed steps do: it kept its last shape
    const bool studioOriginals = std::ranges::any_of(Originals.getValues(), [](auto obj) {
        return studioOwnerOfOriginal(obj) != nullptr;
    });
    if (mode == Mode::Features && originals.empty() && !studioOriginals) {
        // Every original suppressed: as upstream
        return App::DocumentObject::StdReturn;
    }

    if (!this->BaseFeature.getValue()) {
        if (auto body = getFeatureBody()) {
            body->setBaseProperty(this);
        }
    }

    this->positionBySupport();

    // get transformations from subclass by calling virtual method
    std::vector<gp_Trsf> transformations;
    try {
        std::list<gp_Trsf> t_list = getTransformations(originals);
        transformations.insert(transformations.end(), t_list.begin(), t_list.end());
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (const Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }

    if (transformations.empty()) {
        return App::DocumentObject::StdReturn;  // No transformations defined, exit silently
    }

    // Get the support
    Part::Feature* supportFeature = nullptr;

    try {
        supportFeature = getBaseObject();
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }

    const Part::TopoShape& supportTopShape = supportFeature->Shape.getShape();
    if (supportTopShape.getShape().IsNull()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Cannot transform invalid support shape")
        );
    }

    // create an untransformed copy of the support shape
    Part::TopoShape supportShape(supportTopShape);

    gp_Trsf trsfInv = supportShape.getShape().Location().Transformation().Inverted();

    supportShape.locate(TopLoc_Location());
    // The support, then this feature's own result after each original
    auto inputCheck = booleanInputCheck();

    // V2 names each instance by content (ops#55): each copy gets a section with this feature's ID
    // and its instance number appended to every name, one number per step (instanceNumbers(),
    // ops#6). V1 keeps the instance suffix as the op.
    const bool nameInstances = getSelectedHistoryAlgorithm() == App::HistoryAlgorithm::V2;
    const auto numbers = nameInstances
        ? instanceNumbers(getTransformationSteps(), transformations.size())
        : std::vector<std::string>();
    // Onshape's Skip instances (ops#640 rank 8): by position in the list
    const auto skipped = getSkippedPositions();
    // The copies of fused originals tried, and those made: none made fails (ops#640, A-2' d)
    std::size_t copiesTried = 0;
    std::size_t copiesMade = 0;
    auto getTransformedCompShape = [&](const auto& supportShape, const auto& origShape) {
        std::vector<TopoShape> shapes = {supportShape};
        int instance = 1;
        auto transformIter = transformations.cbegin();
        transformIter++;
        for (; transformIter != transformations.end(); transformIter++) {
            if (Base::Sequencer().wasCanceled()) {
                return std::vector<TopoShape>();
            }
            auto opName = nameInstances ? std::string() : Data::indexSuffix(instance);
            ++instance;
            if (std::ranges::find(skipped, static_cast<std::size_t>(instance - 1)) != skipped.end()) {
                continue;
            }
            shapes.emplace_back(makeResultShape(origShape)
                                    .makeElementTransform(origShape, *transformIter, opName.c_str()));
            if (nameInstances) {
                // a studio step names by its owner (ops#654, notes/stored-tags.md 3 item 2)
                shapes.back().appendElementSection(
                    namingTag() ? namingTag() : getID(),
                    Part::OpCodes::Transformed,
                    numbers[instance - 1]
                );
            }
        }
        return shapes;
    };

    switch (mode) {
        case Mode::Features: {
            // NOTE: It would be possible to build a compound from all original addShapes/subShapes
            // and then transform the compounds as a whole. But we choose to apply the
            // transformations to each Original separately. This way it is easier to discover what
            // feature causes a fuse/cut to fail. The downside is that performance suffers when
            // there are many originals. But it seems safe to assume that in most cases there are
            // few originals and many transformations
            // FreeCAD-CH ops#654 slice 8: the originals' tools first, a studio feature's from its
            // step, a pattern's own instances flattened (Onshape P2), each refused loudly where a
            // copy may differ from Onshape's instance (studioCopyRefusal(), until T3)
            std::vector<gp_Trsf> instances;
            for (std::size_t position = 1; position < transformations.size(); ++position) {
                if (std::ranges::find(skipped, position) == skipped.end()) {
                    instances.push_back(transformations[position]);
                }
            }
            Body* body = getFeatureBody();
            gp_Trsf fromDocument = trsfInv;
            if (body) {
                fromDocument.Multiply(Part::TopoShape::convert(
                    App::GeoFeature::getGlobalPlacement(body).inverse().toMatrix()
                ));
            }
            ToolCollector collector {*this, body, trsfInv, fromDocument, supportShape, nameInstances};
            const bool reapply = Reapply.getValue();
            collector.reapply = reapply;
            {
                // FreeCAD-CH ops#654 T3 (Onshape's Reapply features, O6, O10): with Reapply on each
                // instance re-runs the originals there, in order, against the part as it grows.
                // The T3 fix (oracle 9): instance by instance with Reapply off too (R1); an Up to
                // next original re-run at each instance either way, an instance that fails
                // contributing nothing (R2); each pattern among the originals following its own
                // Reapply (R3)
                ReapplyCollector reapplied {
                    *this, body, trsfInv, fromDocument, nameInstances, collector, reapply, instances
                };
                std::vector<ReapplyItem> items;
                for (auto original : originals) {
                    std::string why = reapplied.add(original, {}, items, 0);
                    if (!why.empty()) {
                        return new App::DocumentObjectExecReturn(why, this);
                    }
                }
                const bool rerun = std::ranges::any_of(items, [](const ReapplyItem& item) {
                    return item.rerun || item.hole || item.dressUp || item.rerunBy;
                });
                const bool adds = std::ranges::any_of(items, [](const ReapplyItem& item) {
                    return item.additive;
                });
                const bool removes = std::ranges::any_of(items, [](const ReapplyItem& item) {
                    return !item.additive;
                });
                // Tools independent of the base, all adding or all removing: the order doesn't
                // matter, and the copies below are the instances re-run, names and all
                if (rerun || (adds && removes)) {
                    const std::string partName = body ? quoted(body) : std::string("the part");
                    const long tag = namingTag() ? namingTag() : getID();
                    // Re-run by patterns among the originals only (R3, the outer ones copying
                    // what they made): made once, where the innermost of them makes it, against
                    // the part at that pattern's place (unverified on Onshape for a tool that
                    // depends on the base: Onshape's inner pattern grows its part instance by
                    // instance), then copied as any tool is
                    for (auto it = items.begin(); it != items.end();) {
                        if (!it->rerunBy) {
                            ++it;
                            continue;
                        }
                        Transformed* by = it->levels[it->rerunBy - 1].inner;
                        Part::TopoShape innerBase;
                        if (const Part::Feature* support = by->getBaseObject(/*silent=*/true)) {
                            innerBase = support->Shape.getShape();
                        }
                        if (innerBase.isNull()) {
                            return new App::DocumentObjectExecReturn(
                                quoted(by) + " has no base", this
                            );
                        }
                        const gp_Trsf at = innerBase.getShape().Location().Transformation();
                        innerBase.locate(TopLoc_Location());
                        innerBase = innerBase.makeElementTransform(trsfInv.Multiplied(at));
                        const gp_Trsf back = it->toPattern.Inverted().Multiplied(
                            it->innerMove(it->rerunBy).Inverted()
                        );
                        const gp_Trsf toSeed = back.Multiplied(it->toPattern);
                        const Part::TopoShape base = innerBase.makeElementTransform(back);
                        std::string why;
                        Part::TopoShape made;
                        try {
                            made = it->rerun
                                ? reapplyExtrusion(it->rerun, toSeed, base, partName, why)
                                : reapplyHole(it->hole, toSeed, base, why);
                        }
                        catch (const Standard_Failure& e) {
                            why = e.GetMessageString();
                        }
                        catch (const Base::Exception& e) {
                            why = e.what();
                        }
                        if (made.isNull()) {
                            it = items.erase(it);  // it contributes nothing (R2)
                            continue;
                        }
                        it->tool = made.makeElementTransform(it->toPattern);
                        it->rerun = nullptr;
                        it->hole = nullptr;
                        ++it;
                    }
                    // Of each original re-run at this pattern's instances, the instances that
                    // failed; whether any original was made at any instance; of the copies that
                    // add, those tried and made
                    std::vector<std::size_t> failed(items.size(), 0);
                    std::vector<std::string> firstWhy(items.size());
                    bool madeSome = false;
                    std::size_t instancesRun = 0;
                    std::size_t addsTried = 0;
                    std::size_t addsMade = 0;
                    try {
                        for (std::size_t position = 1; position < transformations.size();
                             ++position) {
                            if (std::ranges::find(skipped, position) != skipped.end()) {
                                continue;
                            }
                            if (Base::Sequencer().wasCanceled()) {
                                return new App::DocumentObjectExecReturn("User aborted");
                            }
                            const gp_Trsf& outer = transformations[position];
                            const std::string instance = "instance " + std::to_string(position + 1);
                            ++instancesRun;
                            for (std::size_t index = 0; index < items.size(); ++index) {
                                const ReapplyItem& item = items[index];
                                const gp_Trsf full = outer.Multiplied(item.innerMove());
                                if (item.dressUp) {
                                    // A chamfer or fillet on the instance's edges: the seed's
                                    // edges moved there, each an edge of the part as it is now
                                    Part::TopoShape seedBase =
                                        item.dressUp->getBaseTopoShape(/*silent=*/true);
                                    if (seedBase.isNull()) {
                                        return new App::DocumentObjectExecReturn(
                                            quoted(item.named) + " has no base", this
                                        );
                                    }
                                    const gp_Trsf seedFrame = trsfInv.Multiplied(
                                        seedBase.getShape().Location().Transformation()
                                    );
                                    seedBase.locate(TopLoc_Location());
                                    const gp_Trsf move = full.Multiplied(seedFrame);
                                    Bnd_Box partBox;
                                    BRepBndLib::Add(supportShape.getShape(), partBox);
                                    const double tol =
                                        std::max(1e-6, 1e-7 * std::sqrt(partBox.SquareExtent()));
                                    const std::vector<Part::TopoShape> partEdges =
                                        supportShape.getSubTopoShapes(TopAbs_EDGE);
                                    std::vector<Part::TopoShape> edges;
                                    for (const auto& edge : item.dressUp->getContinuousEdges(seedBase)) {
                                        const TopoDS_Shape there =
                                            BRepBuilderAPI_Transform(edge.getShape(), move, true).Shape();
                                        auto found = std::ranges::find_if(
                                            partEdges,
                                            [&](const Part::TopoShape& candidate) {
                                                return sameEdge(there, candidate.getShape(), tol);
                                            }
                                        );
                                        if (found == partEdges.end()) {
                                            return new App::DocumentObjectExecReturn(
                                                quoted(item.named) + " at " + instance
                                                    + ": its edges aren't found on the instance",
                                                this
                                            );
                                        }
                                        edges.push_back(*found);
                                    }
                                    if (edges.empty()) {
                                        return new App::DocumentObjectExecReturn(
                                            quoted(item.named) + " has no edges", this
                                        );
                                    }
                                    std::string why;
                                    Part::TopoShape made =
                                        reapplyDressUp(item.dressUp, supportShape, edges, why);
                                    if (made.isNull()) {
                                        return new App::DocumentObjectExecReturn(
                                            quoted(item.named) + " at " + instance + ": " + why,
                                            this
                                        );
                                    }
                                    supportShape = made;
                                    inputCheck = ownResultCheck();
                                    madeSome = true;
                                    continue;
                                }
                                Part::TopoShape shape = item.tool;
                                if (item.rerun || item.hole) {
                                    // Re-run in the seed's place against the base and references
                                    // carried back there; then moved, as a copy is
                                    const gp_Trsf back = item.toPattern.Inverted().Multiplied(
                                        full.Inverted()
                                    );
                                    const gp_Trsf toSeed = back.Multiplied(item.toPattern);
                                    const Part::TopoShape base = supportShape.makeElementTransform(back);
                                    std::string why;
                                    Part::TopoShape made = item.rerun
                                        ? reapplyExtrusion(item.rerun, toSeed, base, partName, why)
                                        : reapplyHole(item.hole, toSeed, base, why);
                                    if (made.isNull()) {
                                        // An instance that fails contributes nothing, with no
                                        // message (oracle 9, R2)
                                        if (failed[index]++ == 0) {
                                            firstWhy[index] = instance + ": " + why;
                                        }
                                        continue;
                                    }
                                    shape = made.makeElementTransform(item.toPattern);
                                }
                                // Named as a copy is (pattern-instance-names.md, patterns-design 3.3)
                                for (const InnerLevel& level : item.levels) {
                                    Part::TopoShape moved = nameInstances
                                        ? level.inner->makeTopoShape(false)
                                        : Part::TopoShape(
                                              shape.Tag,
                                              shape.Hasher,
                                              shape.getHistoryAlgorithm()
                                          );
                                    const std::string op = nameInstances
                                        ? std::string()
                                        : Data::indexSuffix(static_cast<int>(level.position) + 1);
                                    moved.makeElementTransform(shape, level.move, op.c_str());
                                    if (nameInstances) {
                                        const long innerTag = level.inner->namingTag()
                                            ? level.inner->namingTag()
                                            : level.inner->getID();
                                        moved.appendElementSection(
                                            innerTag,
                                            Part::OpCodes::Transformed,
                                            level.number
                                        );
                                    }
                                    shape = moved;
                                }
                                const std::string op = nameInstances
                                    ? std::string()
                                    : Data::indexSuffix(static_cast<int>(position));
                                Part::TopoShape placed =
                                    makeResultShape(shape).makeElementTransform(shape, outer, op.c_str());
                                if (nameInstances) {
                                    placed.appendElementSection(
                                        tag,
                                        Part::OpCodes::Transformed,
                                        numbers[position]
                                    );
                                }
                                const int before = countSolids(supportShape.getShape());
                                Part::TopoShape result = makeResultShape(supportShape);
                                result.makeElementBoolean(
                                    item.additive ? Part::OpCodes::Fuse : Part::OpCodes::Cut,
                                    {supportShape, placed},
                                    nullptr,
                                    -1.0,
                                    Part::ElementMapPolicy::Propagate,
                                    inputCheck,
                                    &booleanInputsValid
                                );
                                // An instance that removes nothing does nothing (Onshape P1); one
                                // that adds a solid apart from the part is a new part in Onshape.
                                // With Reapply off such a copy is dropped with no message, as the
                                // copy engine drops it (ops#640 B3-3b), unless the seed made a
                                // part of its own
                                const bool copiedHere = !item.rerun && !item.hole;
                                if (item.additive && copiedHere) {
                                    ++addsTried;
                                }
                                const bool floats = item.additive
                                    && countSolids(result.getShape()) > before
                                    && !FeatureAddSub::shapesTouch(
                                        placed.getShape(),
                                        supportShape.getShape()
                                    );
                                if (floats && !reapply) {
                                    if (!makesItsOwnPart(*item.seed, item.tool, trsfInv)) {
                                        continue;
                                    }
                                }
                                else if (floats) {
                                    return new App::DocumentObjectExecReturn(
                                        quoted(item.named) + " at " + instance
                                            + " touches nothing of " + partName
                                            + ": with Reapply on it would become a new part, which "
                                              "is not done yet",
                                        this
                                    );
                                }
                                if (item.additive && copiedHere) {
                                    ++addsMade;
                                }
                                supportShape = result;
                                inputCheck = ownResultCheck();
                                madeSome = true;
                            }
                        }
                    }
                    catch (const Standard_Failure& e) {
                        return new App::DocumentObjectExecReturn(e.GetMessageString(), this);
                    }
                    catch (const Base::Exception& e) {
                        return new App::DocumentObjectExecReturn(e.what(), this);
                    }
                    // An original re-run at every instance and made at none contributes nothing,
                    // with no message, while the pattern makes another original somewhere: Onshape
                    // builds such a pattern (ops#640, a replica's circular pattern), as it drops
                    // any failing instance (R2). Loud only when the pattern makes nothing at all
                    // (unverified on Onshape)
                    for (std::size_t index = 0; index < items.size() && !madeSome; ++index) {
                        if (instancesRun > 0 && failed[index] == instancesRun) {
                            return new App::DocumentObjectExecReturn(
                                quoted(items[index].named) + " can't be made at any instance ("
                                    + firstWhy[index] + ")",
                                this
                            );
                        }
                    }
                    // No added copy reached the part, as the copy engine says below
                    if (addsTried > 0 && addsMade == 0) {
                        return new App::DocumentObjectExecReturn(
                            QT_TRANSLATE_NOOP("Exception", "Could not create all instances as entered.")
                        );
                    }
                    break;
                }
            }
            std::vector<PatternTool> tools;
            for (auto original : originals) {
                std::string why = collector.add(original, instances, tools, 0);
                if (!why.empty()) {
                    return new App::DocumentObjectExecReturn(why, this);
                }
            }
            for (const PatternTool& tool : tools) {
                Part::TopoShape fuseShape = tool.fuse;
                Part::TopoShape cutShape = tool.cut;
                auto feature = tool.seed;
                if (!fuseShape.isNull()) {
                    auto shapes = getTransformedCompShape(supportShape, fuseShape);
                    if (Base::Sequencer().wasCanceled()) {
                        return new App::DocumentObjectExecReturn("User aborted");
                    }
                    auto fused = makeResultShape(supportShape).makeElementBoolean(
                        Part::OpCodes::Fuse,
                        shapes,
                        nullptr,
                        -1.0,
                        Part::ElementMapPolicy::Propagate,
                        inputCheck,
                        &booleanInputsValid
                    );
                    copiesTried += shapes.size() - 1;
                    // FreeCAD-CH (ops#640, B3-3b): a copy entirely off the part is dropped, with
                    // no message and no lump: the fuse is made again without it. The others keep
                    // their instance numbers
                    auto floating = floatingCopies(fused, supportShape, shapes);
                    if (!floating.empty() && reapply
                        && !makesItsOwnPart(*feature, tool.seedFuse, trsfInv)) {
                        // ops#654 T3: Onshape makes such an instance a new part (H1 B3-3b)
                        return new App::DocumentObjectExecReturn(
                            "An instance of " + quoted(feature->StudioOwner.getValue()
                                                           ? feature->StudioOwner.getValue()
                                                           : feature)
                                + " touches nothing of "
                                + (body ? quoted(body) : std::string("the part"))
                                + ": with Reapply on it would become a new part, which is not "
                                  "done yet",
                            this
                        );
                    }
                    if (!floating.empty() && !makesItsOwnPart(*feature, tool.seedFuse, trsfInv)) {
                        std::vector<Part::TopoShape> kept;
                        for (std::size_t i = 0; i < shapes.size(); ++i) {
                            if (std::ranges::find(floating, i) == floating.end()) {
                                kept.push_back(shapes[i]);
                            }
                        }
                        if (kept.size() > 1) {
                            fused = makeResultShape(supportShape).makeElementBoolean(
                                Part::OpCodes::Fuse,
                                kept,
                                nullptr,
                                -1.0,
                                Part::ElementMapPolicy::Propagate,
                                inputCheck,
                                &booleanInputsValid
                            );
                        }
                        else {
                            fused = supportShape;
                        }
                        copiesMade += kept.size() - 1;
                    }
                    else {
                        copiesMade += shapes.size() - 1;
                    }
                    supportShape = fused;
                    inputCheck = ownResultCheck();
                }
                if (!cutShape.isNull()) {
                    auto shapes = getTransformedCompShape(supportShape, cutShape);
                    if (Base::Sequencer().wasCanceled()) {
                        return new App::DocumentObjectExecReturn("User aborted");
                    }
                    // A copy that cuts nothing changes nothing: never dropped, it counts as made
                    copiesTried += shapes.size() - 1;
                    copiesMade += shapes.size() - 1;
                    supportShape = makeResultShape(supportShape).makeElementBoolean(
                        Part::OpCodes::Cut,
                        shapes,
                        nullptr,
                        -1.0,
                        Part::ElementMapPolicy::Propagate,
                        inputCheck,
                        &booleanInputsValid
                    );
                    inputCheck = ownResultCheck();
                }
            }
            // FreeCAD-CH (ops#640, A-2' d): no copy reached the part. Onshape's mirror of a
            // feature whose image is entirely off the part is red with this message (its second
            // sentence, "Try selecting "Reapply features" option.", names an option this
            // feature doesn't have); the failure rule passes the base through: no lump
            if (copiesTried > 0 && copiesMade == 0) {
                return new App::DocumentObjectExecReturn(
                    QT_TRANSLATE_NOOP("Exception", "Could not create all instances as entered.")
                );
            }
            break;
        }
        case Mode::WholeShape: {
            auto shapes = getTransformedCompShape(supportShape, supportShape);
            if (Base::Sequencer().wasCanceled()) {
                return new App::DocumentObjectExecReturn("User aborted");
            }
            supportShape = makeResultShape(supportShape).makeElementBoolean(
                Part::OpCodes::Fuse,
                shapes,
                nullptr,
                -1.0,
                Part::ElementMapPolicy::Propagate,
                inputCheck,
                &booleanInputsValid
            );
            break;
        }
    }

    supportShape = refineShapeIfActive((supportShape));

    // FreeCAD-CH ops#654 slice 8, P6p: a part of a listed studio goes on in two solids only as
    // pieces a command made parts (Onshape S1): the part's chain then ends here, holding them all
    if (StudioList::holding(this)) {
        noteSplitHeld(this, getFeatureBody(), supportShape);
        if (const int solids = countSolids(supportShape.getShape()); solids > 1) {
            if (std::string why = unclaimedSplit(this, getFeatureBody(), supportShape);
                !why.empty()) {
                return new App::DocumentObjectExecReturn(why, this);
            }
            this->Shape.setValue(supportShape);
            rejected.Nullify();
            return App::DocumentObject::StdReturn;
        }
    }

    this->Shape.setValue(getSolid(supportShape));
    if (singleSolidRuleMode() == SingleSolidRuleMode::Enforced) {
        rejected = getRemainingSolids(supportShape.getShape());
    }
    else {
        rejected.Nullify();
    }

    return App::DocumentObject::StdReturn;
}

std::list<gp_Trsf> Transformed::centerInstances(
    const std::list<gp_Trsf>& transformations,
    int rows,
    int columns,
    bool centerRows,
    bool centerColumns
)
{
    const int middleRow = centerRows ? (rows - 1) / 2 : 0;
    const int middleColumn = centerColumns ? (columns - 1) / 2 : 0;
    if (rows < 1 || columns < 1 || static_cast<std::size_t>(rows) * columns != transformations.size()
        || (middleRow == 0 && middleColumn == 0)) {
        return transformations;
    }
    std::vector<gp_Trsf> list(transformations.begin(), transformations.end());
    // Relative to the instance at the middle: it becomes the original, untransformed
    const gp_Trsf toMiddle = list[static_cast<std::size_t>(middleRow) * columns + middleColumn].Inverted();
    std::vector<gp_Trsf> centered(list.size());
    for (int row = 0; row < rows; ++row) {
        for (int column = 0; column < columns; ++column) {
            const auto from = static_cast<std::size_t>(row) * columns + column;
            const auto to = static_cast<std::size_t>(centeredIndex(row, middleRow)) * columns
                + centeredIndex(column, middleColumn);
            centered[to] = toMiddle.Multiplied(list[from]);
        }
    }
    return {centered.begin(), centered.end()};
}

TopoDS_Shape Transformed::getRemainingSolids(const TopoDS_Shape& shape)
{
    BRep_Builder builder;
    TopoDS_Compound compShape;
    builder.MakeCompound(compShape);

    if (shape.IsNull()) {
        throw Standard_Failure("Shape is null");
    }
    TopExp_Explorer xp;
    xp.Init(shape, TopAbs_SOLID);
    xp.Next();  // skip the first

    for (; xp.More(); xp.Next()) {
        builder.Add(compShape, xp.Current());
    }

    return {std::move(compShape)};
}

}  // namespace PartDesign
