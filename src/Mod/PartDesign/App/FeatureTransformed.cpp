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
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <Precision.hxx>
#include <TopExp_Explorer.hxx>


#include <array>
#include <unordered_map>
#include <algorithm>

#include <App/Document.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Base/Sequencer.h>
#include <Mod/Part/App/modelRefine.h>

#include "FeatureTransformed.h"
#include "Body.h"
#include "FeatureAddSub.h"
#include "FeatureMultiTransform.h"
#include "FeatureMirrored.h"
#include "FeatureLinearPattern.h"
#include "FeaturePolarPattern.h"
#include "FeatureSketchBased.h"
#include "Retarget.h"
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

}  // namespace

namespace PartDesign
{
extern bool getPDRefineModelParameter();

PROPERTY_SOURCE(PartDesign::Transformed, PartDesign::FeatureRefine)

std::array<char const*, 3> transformModeEnums = {"Features", "Whole shape", nullptr};

Transformed::Transformed()
{
    ADD_PROPERTY(Originals, (nullptr));
    Originals.setSize(0);
    Placement.setStatus(App::Property::ReadOnly, true);

    ADD_PROPERTY(TransformMode, (static_cast<long>(Mode::Features)));
    TransformMode.setEnums(transformModeEnums.data());
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
        else if (freecad_cast<const LinearPattern*>(this) || freecad_cast<const PolarPattern*>(this)) {
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
        std::ranges::sort(originals, [&indexMap](const DocumentObject* a, const DocumentObject* b) {
            auto itA = indexMap.find(a);
            auto itB = indexMap.find(b);
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
        for (const auto& original : getOriginals()) {
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
                // Out of the chain (a MultiTransform's step, or a pattern of nothing): the solid
                // after it builds on the one before it, as when it is removed (this one no longer
                // counts as a solid there), and it has no base, as a step made in a MultiTransform
                // has none. Converting a pattern makes it the MultiTransform's step after the
                // MultiTransform's link rerouted it onto it: its base would be a cycle (ops#590)
                auto next = freecad_cast<PartDesign::Feature*>(body->getNextSolidFeature(this));
                if (next && next->BaseFeature.getValue() == this) {
                    body->setBaseProperty(next);
                }
                if (BaseFeature.getValue()) {
                    BaseFeature.setValue(nullptr);
                }
            }
        }
    }

    FeatureRefine::onChanged(prop);
}

App::DocumentObjectExecReturn* Transformed::execute()
{
    if (isMultiTransformChild()) {
        // FreeCAD-CH (ops#640): a MultiTransform's step computes nothing of its own. A pattern or
        // mirror of nothing is red, as Onshape's is, and stays out of the chain: it contributes
        // nothing (a reorder's parked Originals have their own message, before this runs)
        if (isListedStep(*this) || hasParkedOriginals(this)) {
            return App::DocumentObject::StdReturn;
        }
        if (freecad_cast<const Mirrored*>(this)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Select features to mirror.")
            );
        }
        if (freecad_cast<const LinearPattern*>(this) || freecad_cast<const PolarPattern*>(this)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Select features to pattern.")
            );
        }
        if (freecad_cast<const MultiTransform*>(this)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Select features to transform.")
            );
        }
        return App::DocumentObject::StdReturn;
    }

    auto const mode = static_cast<Mode>(TransformMode.getValue());

    std::vector<DocumentObject*> originals = getOriginals();

    if (mode == Mode::Features && originals.empty()) {
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
                shapes.back().appendElementSection(
                    getID(),
                    Part::OpCodes::Transformed,
                    numbers[instance - 1]
                );
            }
        }
        return shapes;
    };

    switch (mode) {
        case Mode::Features:
            // NOTE: It would be possible to build a compound from all original addShapes/subShapes
            // and then transform the compounds as a whole. But we choose to apply the
            // transformations to each Original separately. This way it is easier to discover what
            // feature causes a fuse/cut to fail. The downside is that performance suffers when
            // there are many originals. But it seems safe to assume that in most cases there are
            // few originals and many transformations
            for (auto original : originals) {
                // Extract the original shape and determine whether to cut or to fuse
                Part::TopoShape fuseShape = makeTopoShape(false);
                Part::TopoShape cutShape = makeTopoShape(false);

                auto feature = freecad_cast<PartDesign::FeatureAddSub*>(original);
                if (!feature) {
                    return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                        "Exception",
                        "Only additive and subtractive features can be transformed"
                    ));
                }

                feature->getAddSubShape(fuseShape, cutShape);
                if (fuseShape.isNull() && cutShape.isNull()) {
                    return new App::DocumentObjectExecReturn(
                        QT_TRANSLATE_NOOP("Exception", "Shape of additive/subtractive feature is empty")
                    );
                }
                gp_Trsf trsf = trsfInv.Multiplied(feature->getLocation().Transformation());
                if (!fuseShape.isNull()) {
                    fuseShape = fuseShape.makeElementTransform(trsf);
                }
                if (!cutShape.isNull()) {
                    cutShape = cutShape.makeElementTransform(trsf);
                }
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
                    if (!floating.empty() && !makesItsOwnPart(*feature, fuseShape, trsfInv)) {
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
