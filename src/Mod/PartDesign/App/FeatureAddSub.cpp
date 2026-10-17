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


#include <map>
#include <memory>
#include <set>

#include <BRepExtrema_DistShapeShape.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>


#include <App/FeaturePythonPyImp.h>
#include <Mod/Part/App/modelRefine.h>
#include <Mod/Part/App/TopoShapeOpCode.h>
#include <GProp_GProps.hxx>
#include <BRepGProp.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>
#include <App/Document.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>

#include "Body.h"
#include "FeatureAddSub.h"
#include "FeaturePy.h"
#include "FeatureSketchBased.h"

#include <Mod/Part/App/Tools.h>


using namespace PartDesign;

namespace PartDesign
{

extern bool getPDRefineModelParameter();

namespace
{
bool isOwn(const App::DocumentObject* obj, const App::Property* prop);
bool isCopied(const App::Property* prop);
}  // namespace

PROPERTY_SOURCE(PartDesign::FeatureAddSub, PartDesign::FeatureRefine)

FeatureAddSub::FeatureAddSub()
{
    ADD_PROPERTY(AddSubShape, (TopoDS_Shape()));
    ADD_PROPERTY_TYPE(Operation, (false), "Part Design", App::Prop_None, "Boolean operation to compute");
    Operation.setEnums({"Union", "Subtraction", "Common"});
    ADD_PROPERTY_TYPE(
        SiblingOf,
        (nullptr),
        "Part Design",
        App::Prop_None,
        "The cut this one follows: its parameters by expression, its links by copy (ops#325)"
    );
}


FeatureAddSub::Type FeatureAddSub::getAddSubType()
{
    return addSubType;
}

FeatureAddSub::BooleanOperation FeatureAddSub::getBooleanOperation()
{
    return booleanOperation;
}

void FeatureAddSub::defineAdditive()
{
    addSubType = FeatureAddSub::Type::Additive;
    Operation.setStatus(App::Property::Status::Hidden, true);
    Operation.setEnums({"Union"});
    Operation.setValue("Union");
}

void FeatureAddSub::defineSubtractive()
{
    addSubType = FeatureAddSub::Type::Subtractive;
    Operation.setStatus(App::Property::Status::Hidden, false);
    Operation.setEnums({"Subtraction", "Common"});
    Operation.setValue("Subtraction");
}

const char* FeatureAddSub::getBooleanMaker() const
{
    switch (booleanOperation) {
        case BooleanOperation::Subtraction:
            return Part::OpCodes::Cut;
        case BooleanOperation::Common:
            return Part::OpCodes::Common;
        default:
            return Part::OpCodes::Fuse;
    }
}

void FeatureAddSub::onChanged(const App::Property* property)
{
    if (property == &Operation) {
        const char* strOp = Operation.getValueAsString();
        if (strcmp(strOp, "Subtraction") == 0) {
            booleanOperation = BooleanOperation::Subtraction;
            addSubType = Type::Subtractive;
        }
        else if (strcmp(strOp, "Common") == 0) {
            booleanOperation = BooleanOperation::Common;
            addSubType = Type::Subtractive;
        }
        else {
            booleanOperation = BooleanOperation::Union;
            addSubType = Type::Additive;
        }
    }
    // A sibling checks its links against this one's when it recomputes, and no expression reads
    // a link, so no dependency runs it: a link changed here does (ops#325)
    if (isCopied(property) && !isRestoring() && getDocument() && !isOwn(this, property)) {
        for (FeatureAddSub* sibling : getSiblings()) {
            sibling->touch();
        }
    }

    Feature::onChanged(property);
}

short FeatureAddSub::mustExecute() const
{
    if (Refine.isTouched()) {
        return 1;
    }
    return PartDesign::Feature::mustExecute();
}

App::DocumentObjectExecReturn* FeatureAddSub::recompute()
{
    auto body = getFeatureBody();
    // A sibling whose links aren't its primary's fails until the primary is edited (ops#325)
    const bool runs = !Suppressed.getValue() && !(body && body->holds(this));
    if (runs) {
        if (std::string why = outOfStep(); !why.empty()) {
            return new App::DocumentObjectExecReturn(why, this);
        }
    }
    App::DocumentObjectExecReturn* result = FeatureRefine::recompute();
    if (result == StdReturn && runs) {
        warnIfMissing();
    }
    // A subtractive feature with nothing before it cut nothing and returned its tool as material
    // (FreeCAD-CH ops#308 F8: a Body's first Pocket, e.g. on another Body's face, which T1 no
    // longer takes as a base). Checked after the run, so an input's error is reported first; the
    // failure passes the (empty) base through. Not when suppressed or held: those pass their
    // base through already.
    if (result == StdReturn && addSubType == Type::Subtractive && !Suppressed.getValue()
        && !(body && body->holds(this)) && getBaseTopoShape(true).isNull()) {
        return new App::DocumentObjectExecReturn(
            "Nothing to cut: a subtractive feature needs a solid before it in its Body, or a "
            "BaseFeature",
            this
        );
    }
    if (result != StdReturn || booleanOperation != BooleanOperation::Common || Suppressed.getValue()
        || (body && body->holds(this))) {
        return result;
    }
    // A Common keeps only what its tool overlaps: in a base of several solids it removes the
    // ones the tool doesn't reach, whole, with no sign (FreeCAD-CH ops#308 T3). Counted here
    // for every subtractive feature: a base solid with no volume left in the result.
    try {
        const TopoShape base = getBaseTopoShape(true);
        const std::vector<TopoShape> solids = base.getSubTopoShapes(TopAbs_SOLID);
        const TopoDS_Shape& shape = Shape.getValue();
        if (solids.size() < 2) {
            return result;
        }
        Bnd_Box kept;
        if (!shape.IsNull()) {
            BRepBndLib::Add(shape, kept);
        }
        int gone = 0;
        for (const TopoShape& solid : solids) {
            Bnd_Box box;
            BRepBndLib::Add(solid.getShape(), box);
            double volume = 0;
            if (!shape.IsNull() && !kept.IsOut(box)) {
                BRepAlgoAPI_Common common(solid.getShape(), shape);
                if (!common.IsDone()) {
                    continue;  // unknown: not counted
                }
                GProp_GProps props;
                BRepGProp::VolumeProperties(common.Shape(), props);
                volume = props.Mass();
            }
            gone += volume <= Precision::Confusion() ? 1 : 0;
        }
        if (gone > 0) {
            const std::string text = "Common removed " + std::to_string(gone) + " of the "
                + std::to_string(solids.size())
                + " solids of its base entirely: those its tool doesn't overlap";
            if (auto doc = getDocument()) {
                const char* previous = doc->getWarningDescription(this);
                doc->setWarning(
                    this,
                    previous && *previous ? std::string(previous) + "\n" + text : text
                );
            }
        }
    }
    catch (const Standard_Failure&) {
    }
    catch (const Base::Exception&) {
    }
    return result;
}

void FeatureAddSub::getAddSubShape(Part::TopoShape& addShape, Part::TopoShape& subShape)
{
    if (addSubType == Type::Additive) {
        addShape = AddSubShape.getShape();
    }
    else {
        subShape = AddSubShape.getShape();
    }
}

void FeatureAddSub::updatePreviewShape()
{
    // FreeCAD-CH (ops#148, upstream issue 24326): a feature that fails has no preview. Its
    // AddSubShape is the last good one's (e.g. a Pad switched to "To last" with nothing below).
    if (isError()) {
        PreviewShape.setValue(TopoShape());
        return;
    }

    const auto notifyWarning = [](const QString& message) {
        Base::Console().translatedUserWarning(
            "Preview",
            tr("Failure while computing removed volume preview: %1").arg(message).toUtf8()
        );
    };

    // for subtractive shapes we want to also showcase removed volume, not only the tool
    if (getBooleanMaker() != Part::OpCodes::Fuse) {
        TopoShape base = getBaseTopoShape(true);
        base.move(getInverseLocation(base));
        const TopoShape& tool = AddSubShape.getShape();

        if (!tool.isEmpty()) {
            try {
                // Compute removed volume preview (for display)
                TopoShape common = makeTopoShape(false);
                common.makeElementBoolean(
                    Part::OpCodes::Common,
                    {base, tool},
                    "Preview",
                    Precision::Confusion()
                );

                // does CUT change volume?
                GProp_GProps propsBefore, propsAfter;
                BRepGProp::VolumeProperties(base.getShape(), propsBefore);

                TopoShape cut = makeTopoShape(false);
                cut.makeElementBoolean(
                    Part::OpCodes::Cut,
                    {base, tool},
                    "PreviewCheck",
                    Precision::Confusion()
                );

                BRepGProp::VolumeProperties(cut.getShape(), propsAfter);

                const double removed = propsBefore.Mass() - propsAfter.Mass();

                if (removed <= Precision::Confusion()) {
                    notifyWarning(
                        tr("Resulting shape is empty. That may indicate that no material will be "
                           "removed or a problem with the model.")
                    );
                }
                PreviewShape.setValue(common);
                return;
            }
            catch (Standard_Failure& e) {
                notifyWarning(QString::fromUtf8(e.GetMessageString()));
            }
            catch (Base::Exception& e) {
                notifyWarning(QString::fromStdString(e.what()));
            }
            PreviewShape.setValue(base);
            return;
        }
    }

    PreviewShape.setValue(AddSubShape.getShape());
}

// ------------------------------------------------------------------------------------------------
// Siblings (FreeCAD-CH ops#325, B+ Stage 1 3a)

namespace
{
// A property that is the feature's own, not shared with its siblings: its name, its place in its
// Body, its shapes and state, and whatever the user doesn't set
bool isOwn(const App::DocumentObject* obj, const App::Property* prop)
{
    static const std::set<std::string> own {
        "Label",
        "Label2",
        "ExpressionEngine",
        "Visibility",
        "Placement",
        "BaseFeature",
        "_Body",
        "SiblingOf",
        "Shape",
        "AddSubShape",
        "SuppressedShape",
        "Suppressed",
    };
    if (own.contains(prop->getName())) {
        return true;
    }
    // The type's flags only: a feature makes some read-only for a while (Pocket's UpToFace and
    // Length, by Type), and those must follow too, or switching the primary's Type later would
    // leave the sibling's unbound
    const short type = obj->getPropertyType(prop);
    return (type & (App::Prop_ReadOnly | App::Prop_Output | App::Prop_Transient | App::Prop_Hidden))
        || prop->testStatus(App::Property::Output) || prop->testStatus(App::Property::Transient);
}

// A link, copied to each sibling: expressions can't drive links
bool isCopied(const App::Property* prop)
{
    return prop->isDerivedFrom<App::PropertyLinkBase>();
}

// A value, bound to the primary's by expression (enumerations too)
bool isBound(const App::Property* prop)
{
    return prop->isDerivedFrom<App::PropertyBool>() || prop->isDerivedFrom<App::PropertyInteger>()
        || prop->isDerivedFrom<App::PropertyFloat>()
        || prop->isDerivedFrom<App::PropertyEnumeration>()
        || prop->isDerivedFrom<App::PropertyVector>();
}

// Whether two links name the same objects and elements. Not Property::isSame: for two links,
// PropertyLinkBase::isSame is always false
bool sameLinks(const App::Property* one, const App::Property* other)
{
    std::vector<App::DocumentObject*> objects;
    std::vector<App::DocumentObject*> otherObjects;
    std::vector<std::string> subs;
    std::vector<std::string> otherSubs;
    static_cast<const App::PropertyLinkBase*>(one)->getLinks(objects, true, &subs, false);
    static_cast<const App::PropertyLinkBase*>(other)
        ->getLinks(otherObjects, true, &otherSubs, false);
    return objects == otherObjects && subs == otherSubs;
}

// The properties of `obj` that its siblings share
std::vector<App::Property*> sharedProperties(const App::DocumentObject* obj)
{
    std::vector<App::Property*> props;
    obj->getPropertyList(props);
    std::erase_if(props, [obj](const App::Property* prop) {
        return isOwn(obj, prop) || !(isCopied(prop) || isBound(prop));
    });
    return props;
}

std::string label(const App::DocumentObject* obj)
{
    return obj->Label.getValue();
}

// The links of `user` besides those of its place in a Body's chain
bool linksBesidesChain(App::DocumentObject* user, const App::DocumentObject* target)
{
    auto feature = freecad_cast<Feature*>(user);
    std::vector<App::Property*> props;
    user->getPropertyList(props);
    std::vector<App::DocumentObject*> links;
    for (auto prop : props) {
        if (!isCopied(prop)
            || (feature && (prop == &feature->BaseFeature || prop == &feature->_Body))) {
            continue;
        }
        links.clear();
        static_cast<App::PropertyLinkBase*>(prop)->getLinks(links, /*all=*/true);
        if (std::ranges::find(links, target) != links.end()) {
            return true;
        }
    }
    return false;
}
}  // namespace

std::vector<FeatureAddSub*> FeatureAddSub::getSiblings() const
{
    std::vector<FeatureAddSub*> found;
    if (App::Document* doc = getDocument()) {
        for (auto obj : doc->getObjectsOfType(FeatureAddSub::getClassTypeId())) {
            auto feature = static_cast<FeatureAddSub*>(obj);
            if (feature->SiblingOf.getValue() == this) {
                found.push_back(feature);
            }
        }
    }
    return found;
}

App::DocumentObject* FeatureAddSub::siblingUser(const FeatureAddSub* sibling)
{
    Body* body = Body::findBodyOf(sibling);
    for (auto user : sibling->getInList()) {
        if (user != body && linksBesidesChain(user, sibling)) {
            return user;
        }
    }
    return nullptr;
}

std::vector<FeatureAddSub*> FeatureAddSub::makeSiblings(
    FeatureAddSub* primary,
    const std::vector<App::DocumentObject*>& bodies
)
{
    Body* body = primary ? Body::findBodyOf(primary) : nullptr;
    if (!body || primary->getAddSubType() != Type::Subtractive
        || !primary->isDerivedFrom<ProfileBased>()) {
        throw Base::ValueError(
            "Siblings: the primary must be a subtractive sketch-based feature in a body"
        );
    }
    if (primary->SiblingOf.getValue()) {
        throw Base::ValueError(
            "Siblings: " + label(primary) + " follows "
            + label(primary->SiblingOf.getValue()) + "; edit that one, or Unlink this one"
        );
    }
    std::vector<Body*> targets;
    for (auto obj : bodies) {
        auto target = freecad_cast<Body*>(obj);
        if (!target) {
            throw Base::ValueError(
                "Siblings: " + (obj ? label(obj) : std::string("None")) + " isn't a body"
            );
        }
        if (target == body) {
            throw Base::ValueError(
                "Siblings: " + label(target) + " is " + label(primary) + "'s own body"
            );
        }
        if (!Part::BodyBase::areStudioSiblings(body, target)) {
            throw Base::ValueError(
                "Siblings: " + label(target) + " isn't a part of " + label(body)
                + "'s studio (one container, placed alike)"
            );
        }
        if (std::ranges::find(targets, target) == targets.end()) {
            targets.push_back(target);
        }
    }

    // Refused before anything changes: a sibling to delete that something uses, and a new one in a
    // rolled-back part, which would land mid-history (the design's critic, point 10)
    std::map<Body*, FeatureAddSub*> existing;
    for (FeatureAddSub* sibling : primary->getSiblings()) {
        existing[Body::findBodyOf(sibling)] = sibling;
    }
    for (const auto& [part, sibling] : existing) {
        if (std::ranges::find(targets, part) != targets.end()) {
            continue;
        }
        if (App::DocumentObject* user = siblingUser(sibling)) {
            throw Base::ValueError(
                "Siblings: " + label(sibling) + " is used by " + label(user)
                + "; it stays until that changes"
            );
        }
    }
    for (Body* target : targets) {
        if (!existing.contains(target) && target->isRolledBack()) {
            throw Base::ValueError("Siblings: Roll " + label(target) + " to the end first");
        }
    }

    App::Document* doc = primary->getDocument();
    for (const auto& [part, sibling] : existing) {
        if (std::ranges::find(targets, part) != targets.end()) {
            continue;
        }
        if (part) {
            part->removeObject(sibling);  // the next solid takes its base (Body::removeObject)
        }
        doc->removeObject(sibling->getNameInDocument());
    }

    const std::vector<App::Property*> shared = sharedProperties(primary);
    std::vector<FeatureAddSub*> result;
    for (Body* target : targets) {
        FeatureAddSub* sibling = existing.contains(target) ? existing[target] : nullptr;
        if (!sibling) {
            sibling = static_cast<FeatureAddSub*>(
                doc->addObject(primary->getTypeId().getName(), primary->getNameInDocument())
            );
            target->addObject(sibling);
            sibling->Label.setValue(label(primary) + " (" + label(target) + ")");
            sibling->SiblingOf.setValue(primary);
        }
        for (App::Property* prop : shared) {
            App::Property* mine = sibling->getPropertyByName(prop->getName());
            if (!mine || mine->getTypeId() != prop->getTypeId()) {
                continue;
            }
            if (isCopied(prop) ? !sameLinks(mine, prop) : !mine->isSame(*prop)) {
                std::unique_ptr<App::Property> copy(prop->Copy());
                mine->Paste(*copy);
            }
            if (isCopied(prop)) {
                continue;
            }
            App::ObjectIdentifier path(*mine);
            const std::string text = std::string(primary->getNameInDocument()) + "."
                + prop->getName();
            auto bound = sibling->getExpression(path).expression;
            if (!bound || bound->toString() != text) {
                sibling->setExpression(path, App::Expression::parse(sibling, text));
            }
        }
        result.push_back(sibling);
    }
    return result;
}

void FeatureAddSub::unlinkSibling()
{
    std::vector<App::Property*> props;
    getPropertyList(props);
    for (App::Property* prop : props) {
        if (isOwn(this, prop) || !isBound(prop)) {
            continue;
        }
        App::ObjectIdentifier path(*prop);
        if (getExpression(path).expression) {
            setExpression(path, nullptr);
        }
    }
    SiblingOf.setValue(nullptr);
}

std::string FeatureAddSub::outOfStep() const
{
    auto primary = freecad_cast<FeatureAddSub*>(SiblingOf.getValue());
    if (!primary) {
        return {};
    }
    // A link changed from the property editor or Python, not through the primary's panel (the
    // design's critic, point 3)
    for (App::Property* prop : sharedProperties(primary)) {
        if (!isCopied(prop)) {
            continue;
        }
        App::Property* mine = getPropertyByName(prop->getName());
        if (mine && !sameLinks(mine, prop)) {
            return std::string(prop->getName()) + " is out of step with " + label(primary)
                + ": edit " + label(primary) + " to re-sync, or Unlink this one";
        }
    }
    return {};
}

void FeatureAddSub::warnIfMissing()
{
    Body* body = getFeatureBody();
    if (!SiblingOf.getValue() || !body) {
        return;
    }
    try {
        // Both in the Body's frame: the tool is built in the feature's own
        const TopoShape base = getBaseTopoShape(true);
        TopoShape tool = AddSubShape.getShape();
        tool.setPlacement(Placement.getValue());
        if (base.isNull() || tool.isNull() || shapesTouch(tool.getShape(), base.getShape())) {
            return;
        }
        const std::string text = "doesn't touch " + label(body) + ": its cut misses the part";
        if (auto doc = getDocument()) {
            const char* previous = doc->getWarningDescription(this);
            doc->setWarning(
                this,
                previous && *previous ? std::string(previous) + "\n" + text : text
            );
        }
    }
    catch (const Standard_Failure&) {
    }
    catch (const Base::Exception&) {
    }
}

bool FeatureAddSub::shapesTouch(const TopoDS_Shape& tool, const TopoDS_Shape& part)
{
    if (tool.IsNull() || part.IsNull()) {
        return false;
    }
    Bnd_Box toolBox;
    Bnd_Box partBox;
    BRepBndLib::Add(tool, toolBox, /*useTriangulation=*/false);
    BRepBndLib::Add(part, partBox, /*useTriangulation=*/false);
    toolBox.Enlarge(Precision::Confusion());
    if (toolBox.IsOut(partBox)) {
        return false;
    }
    BRepExtrema_DistShapeShape distance(tool, part);
    return distance.IsDone() && distance.Value() <= Precision::Confusion();
}

}  // namespace PartDesign

namespace App
{
/// @cond DOXERR
PROPERTY_SOURCE_TEMPLATE(PartDesign::FeatureAddSubPython, PartDesign::FeatureAddSub)
template<>
const char* PartDesign::FeatureAddSubPython::getViewProviderName() const
{
    return "PartDesignGui::ViewProviderPython";
}
template<>
PyObject* PartDesign::FeatureAddSubPython::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new FeaturePythonPyT<PartDesign::FeaturePy>(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
/// @endcond

// explicit template instantiation
template class PartDesignExport FeaturePythonT<PartDesign::FeatureAddSub>;
}  // namespace App


namespace PartDesign
{

PROPERTY_SOURCE(PartDesign::FeatureAdditivePython, PartDesign::FeatureAddSubPython)

FeatureAdditivePython::FeatureAdditivePython()
{
    defineAdditive();
}

FeatureAdditivePython::~FeatureAdditivePython() = default;


PROPERTY_SOURCE(PartDesign::FeatureSubtractivePython, PartDesign::FeatureAddSubPython)

FeatureSubtractivePython::FeatureSubtractivePython()
{
    defineSubtractive();
}

FeatureSubtractivePython::~FeatureSubtractivePython() = default;

}  // namespace PartDesign
