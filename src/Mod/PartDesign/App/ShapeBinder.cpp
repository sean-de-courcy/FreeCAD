// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 Stefan Tröger <stefantroeger@gmx.net>              *
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


#include <gp.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>
#include <BRep_Builder.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>


#include <algorithm>
#include <cmath>
#include <cstring>
#include <unordered_map>
#include <unordered_set>
#include <boost/algorithm/string/predicate.hpp>

#include <App/Application.h>
#include <App/Document.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/GroupExtension.h>
#include <App/Link.h>
#include <App/Datums.h>
#include <App/ElementNamingUtils.h>
#include <Mod/Part/App/TopoShape.h>

#include "ShapeBinder.h"
#include "Mod/Part/App/TopoShapeOpCode.h"
#include "Base/Tools.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace PartDesign;
namespace sp = std::placeholders;

namespace PartDesign
{
extern bool getPDRefineModelParameter();
}

// ============================================================================

PROPERTY_SOURCE(PartDesign::ShapeBinder, Part::Feature)

ShapeBinder::ShapeBinder()
{
    ADD_PROPERTY_TYPE(
        Support,
        (nullptr, nullptr),
        "",
        (App::PropertyType)(App::Prop_None),
        "Support of the geometry"
    );
    Placement.setStatus(App::Property::Hidden, true);
    ADD_PROPERTY_TYPE(TraceSupport, (false), "", App::Prop_None, "Trace support shape");
}

ShapeBinder::~ShapeBinder()
{
    this->connectDocumentChangedObject.disconnect();
}

void ShapeBinder::onChanged(const App::Property* prop)
{
    Feature::onChanged(prop);
}

short int ShapeBinder::mustExecute() const
{

    if (Support.isTouched()) {
        return 1;
    }
    if (TraceSupport.isTouched()) {
        return 1;
    }

    return Part::Feature::mustExecute();
}

namespace
{
// A datum element in the body's coordinates: an element of a coordinate system is placed in it
// (ops#200); an origin's too, at identity unless set from Python (ops#206)
Base::Placement datumPlacement(const App::GeoFeature* obj)
{
    Base::Placement placement = obj->Placement.getValue();
    auto element = dynamic_cast<const App::DatumElement*>(obj);
    if (auto lcs = element ? element->getLCS() : nullptr) {
        placement = lcs->Placement.getValue() * placement;
    }
    return placement;
}

// Where the coordinates of an object's shape lie in the document: its container's global
// placement (a Body's, through any App::Part), identity at the top level
Base::Placement containerPlacement(const App::DocumentObject* obj)
{
    auto* container = freecad_cast<App::GeoFeature*>(
        App::GeoFeatureGroupExtension::getGroupOfObject(obj)
    );
    return container ? container->globalPlacement() : Base::Placement();
}

// Equal but for what saving loses: a Cache_ matrix keeps 16 significant digits, so a mapping
// recomputed after reopening differs in the last ones (FreeCAD-CH ops#308 r3 F2: 7e-15)
bool sameMapping(const Base::Matrix4D& a, const Base::Matrix4D& b)
{
    for (unsigned int i = 0; i < 4; ++i) {
        for (unsigned int j = 0; j < 4; ++j) {
            const double scale = std::max({1.0, std::abs(a[i][j]), std::abs(b[i][j])});
            if (std::abs(a[i][j] - b[i][j]) > 1e-9 * scale) {
                return false;
            }
        }
    }
    return true;
}

}  // namespace

bool ShapeBinder::samePlace(const Base::Placement& a, const Base::Placement& b)
{
    if (!a.getPosition().IsEqual(b.getPosition(), Precision::Confusion())) {
        return false;
    }
    double x = 0;
    double y = 0;
    double z = 0;
    double w = 0;
    (a.getRotation().inverse() * b.getRotation()).getValue(x, y, z, w);
    return 2 * std::sqrt(x * x + y * y + z * z) <= Precision::Angular();
}

bool ShapeBinder::containerFrames(Base::Placement& sourceCS, Base::Placement& targetCS) const
{
    App::GeoFeature* obj = nullptr;
    std::vector<std::string> subs;
    ShapeBinder::getFilteredReferences(&Support, obj, subs);
    if (!obj) {
        return false;
    }
    // full placement of container of obj; a datum element's is its coordinate system's
    // container, as its global placement goes through the coordinate system (ops#210)
    sourceCS = obj->globalPlacement() * datumPlacement(obj).inverse();
    // full placement of container of this shapebinder: the container's own (PR 244
    // verification), not globalPlacement() * Placement^-1, which drifted in the last bits as
    // the binder's Placement changed
    auto* container = freecad_cast<App::GeoFeature*>(
        App::GeoFeatureGroupExtension::getGroupOfObject(this)
    );
    targetCS = container ? container->globalPlacement() : Base::Placement();
    return true;
}

Part::TopoShape ShapeBinder::updatedShape() const
{
    Part::TopoShape shape = makeTopoShape(false);
    App::GeoFeature* obj = nullptr;
    std::vector<std::string> subs;

    ShapeBinder::getFilteredReferences(&Support, obj, subs);

    // if we have a link we rebuild the shape, but we change nothing if we are a simple copy
    if (obj) {
        shape = ShapeBinder::buildShapeFromReferences(obj, subs);
        if (getSelectedHistoryAlgorithm() != App::HistoryAlgorithm::V2) {
            // V1 keeps upstream's binder, which drops the source's names (ops#29)
            shape = Part::TopoShape(shape.getShape());
        }
        // now, shape is in object's CS, and includes local Placement of obj (and of its
        // coordinate system, for a datum element: ops#200) but nothing else.

        if (TraceSupport.getValue()) {
            // compute the transform, and apply it to the shape.
            Base::Placement sourceCS;
            Base::Placement targetCS;
            containerFrames(sourceCS, targetCS);
            Base::Placement transform = targetCS.inverse() * sourceCS;
            shape.setPlacement(transform * shape.getPlacement());
        }
    }

    return shape;
}

bool ShapeBinder::hasPlacementChanged() const
{
    Part::TopoShape shape(updatedShape());
    Base::Placement placement(shape.getTransform());
    // FreeCAD-CH (ops#244, PR 244 review M2): within round-off. Compared exactly, a container's
    // Placement set again to the same value (by its expression, in the next pass of a
    // recompute) touched the binder once more, and it was left touched, a recompute behind
    return !samePlace(this->Placement.getValue(), placement);
}

App::DocumentObjectExecReturn* ShapeBinder::execute()
{
    if (!this->isRestoring()) {
        // A reference the binder would leave out fails the recompute rather than binding less
        // than Support says (ops#251)
        const std::string dropped = droppedReferences(&Support);
        if (!dropped.empty()) {
            return new App::DocumentObjectExecReturn(dropped);
        }
        Part::TopoShape shape(updatedShape());
        if (!shape.isNull()) {
            this->Placement.setValue(shape.getTransform());
            this->Shape.setValue(shape);
        }
        traced = TraceSupport.getValue() && containerFrames(tracedSourceCS, tracedTargetCS);
    }

    return Part::Feature::execute();
}

void ShapeBinder::getFilteredReferences(
    const App::PropertyLinkSubList* prop,
    App::GeoFeature*& obj,
    std::vector<std::string>& subobjects
)
{
    obj = nullptr;
    subobjects.clear();

    auto objs = prop->getValues();
    auto subs = prop->getSubValues();

    if (objs.empty()) {
        return;
    }

    // we only allow one part feature, so get the first one we find
    size_t index = 0;
    for (auto* it : objs) {
        if (auto part = dynamic_cast<Part::Feature*>(it)) {
            obj = part;
            break;
        }
        index++;
    }

    // do we have any part feature?
    if (obj) {
        // if we have no subshpape we use the whole shape
        if (subs[index].empty()) {
            return;
        }

        // collect all subshapes for the object
        for (index = 0; index < objs.size(); index++) {
            // we only allow subshapes from a single Part::Feature
            if (objs[index] != obj) {
                continue;
            }

            // in this mode the full shape is not allowed, as we already started the subshape
            // processing
            if (subs[index].empty()) {
                continue;
            }

            subobjects.push_back(subs[index]);
        }
    }
    else {
        // search for Origin features
        for (auto* it : objs) {
            if (auto line = dynamic_cast<App::Line*>(it)) {
                obj = line;
                break;
            }
            if (auto plane = dynamic_cast<App::Plane*>(it)) {
                obj = plane;
                break;
            }
            if (auto point = dynamic_cast<App::Point*>(it)) {
                obj = point;
                break;
            }
        }
    }
}

ShapeBinder::Dropped ShapeBinder::findDroppedReferences(const App::PropertyLinkSubList* prop)
{
    App::GeoFeature* obj = nullptr;
    std::vector<std::string> subs;
    getFilteredReferences(prop, obj, subs);

    const auto& objs = prop->getValues();
    const auto& allSubs = prop->getSubValues();
    // labels, as the user knows the objects (PR 232 review L3, ops#266)
    auto label = [](const App::DocumentObject* it) -> std::string {
        return it->isAttachedToDocument() ? it->Label.getStrValue() : "?";
    };

    // The objects left out, and obj's entries left out: its elements when the whole object is
    // kept, or the whole object when its elements are. A datum is always bound whole, so any
    // element of it is left out (PR 232 review L6: it was called "both as a whole and by its
    // elements")
    const bool datum = obj && !obj->isDerivedFrom<Part::Feature>();
    std::vector<std::string> others;
    std::vector<const App::DocumentObject*> othersSeen;  // by object: two can share a label
    bool mixed = false;
    std::vector<std::string> elements = subs;
    std::vector<std::string> datumElements;
    for (std::size_t i = 0; i < objs.size() && i < allSubs.size(); ++i) {
        const App::DocumentObject* it = objs[i];
        if (!it) {
            continue;
        }
        if (it != obj) {
            if (std::ranges::find(othersSeen, it) == othersSeen.end()) {
                othersSeen.push_back(it);
                others.push_back(label(it));
            }
        }
        else if (datum) {
            if (!allSubs[i].empty()) {
                datumElements.push_back(allSubs[i]);
            }
        }
        else if (subs.empty() != allSubs[i].empty()) {
            mixed = true;
            if (subs.empty()) {
                elements.push_back(allSubs[i]);
            }
        }
    }

    Dropped dropped;
    if (!obj) {
        if (!others.empty()) {
            dropped.kind = Dropped::Kind::NoPartFeature;
            dropped.names = std::move(others);
        }
        return dropped;
    }
    dropped.object = label(obj);
    if (!others.empty()) {
        dropped.kind = Dropped::Kind::OtherObjects;
        dropped.names = std::move(others);
    }
    else if (!datumElements.empty()) {
        dropped.kind = Dropped::Kind::DatumElements;
        dropped.names = std::move(datumElements);
    }
    else if (mixed) {
        dropped.kind = Dropped::Kind::Mixed;
        dropped.names = std::move(elements);
    }
    return dropped;
}

std::string ShapeBinder::Dropped::message() const
{
    std::string list;
    for (const auto& name : names) {
        list += (list.empty() ? "'" : ", '") + name + "'";
    }
    const std::string quoted = "'" + object + "'";
    switch (kind) {
        case Kind::None:
            return {};
        case Kind::NoPartFeature:
            return "A shape binder binds a Part feature or a datum; Support links none, only "
                + list + ".";
        case Kind::OtherObjects:
            return "A shape binder binds one object: Support links " + quoted + " and also " + list
                + ". Use a sub-shape binder to bind several objects.";
        case Kind::Mixed:
            return "Support links " + quoted + " both as a whole and by its elements (" + list
                + "); link either the object or its elements.";
        case Kind::DatumElements:
            return "Support links the datum " + quoted + " by its elements (" + list
                + "); a datum is bound as a whole: link it without elements.";
    }
    return {};
}

Part::TopoShape ShapeBinder::buildShapeFromReferences(App::GeoFeature* obj, std::vector<std::string> subs)
{

    if (!obj) {
        return TopoDS_Shape();
    }

    if (obj->isDerivedFrom<Part::Feature>()) {
        // The source's shapes with their element names (ops#29)
        auto part = static_cast<Part::Feature*>(obj);
        if (subs.empty()) {
            return part->Shape.getShape();
        }

        std::vector<Part::TopoShape> shapes;
        shapes.reserve(subs.size());
        for (const std::string& sub : subs) {
            shapes.push_back(part->Shape.getShape().getSubTopoShape(sub.c_str()));
        }

        if (shapes.size() == 1) {
            // single subshape. Return directly.
            return shapes[0];
        }

        // multiple subshapes. Make a compound, and name its elements by shape: the sub-shapes
        // can share elements (two edges of a sketch share a vertex), which makeElementCompound's
        // child ranges put on the wrong elements (ops#45).
        BRep_Builder builder;
        TopoDS_Compound cmp;
        builder.MakeCompound(cmp);
        for (const Part::TopoShape& sh : shapes) {
            builder.Add(cmp, sh.getShape());
        }
        Part::TopoShape compound(cmp);
        for (const Part::TopoShape& sh : shapes) {
            compound.mapSubElement(sh);
        }
        return compound;
    }
    else if (obj->isDerivedFrom<App::Line>()) {
        // Along the App::Line's base direction, X (ops#200)
        gp_Lin line(gp::Origin(), gp::DX());
        BRepBuilderAPI_MakeEdge mkEdge(line);
        Part::TopoShape shape(mkEdge.Shape());
        shape.setPlacement(datumPlacement(obj));
        return shape;
    }
    else if (obj->isDerivedFrom<App::Plane>()) {
        gp_Pln plane;
        BRepBuilderAPI_MakeFace mkFace(plane);
        Part::TopoShape shape(mkFace.Shape());
        shape.setPlacement(datumPlacement(obj));
        return shape;
    }
    else if (obj->isDerivedFrom<App::Point>()) {
        gp_Pnt point;
        BRepBuilderAPI_MakeVertex mkPoint(point);
        Part::TopoShape shape(mkPoint.Shape());
        shape.setPlacement(datumPlacement(obj));
        return shape;
    }

    return TopoDS_Shape();
}

void ShapeBinder::handleChangedPropertyType(
    Base::XMLReader& reader,
    const char* TypeName,
    App::Property* prop
)
{
    // The type of Support was App::PropertyLinkSubList in the past
    if (prop == &Support && strcmp(TypeName, "App::PropertyLinkSubList") == 0) {
        Support.Restore(reader);
    }
    else {
        Part::Feature::handleChangedPropertyType(reader, TypeName, prop);
    }
}

void ShapeBinder::onSettingDocument()
{
    App::Document* document = getDocument();
    if (document) {
        // NOLINTBEGIN
        this->connectDocumentChangedObject = document->signalChangedObject.connect(
            std::bind(&ShapeBinder::slotChangedObject, this, sp::_1, sp::_2)
        );
        // NOLINTEND
    }
}

void ShapeBinder::slotChangedObject(const App::DocumentObject& Obj, const App::Property& Prop)
{
    // FreeCAD-CH (ops#244, PR 244 verification 2, L2): nothing thrown out of a signal slot; a
    // check that fails leaves the binder to its next recompute
    try {
        followChangedObject(Obj, Prop);
    }
    catch (const Base::Exception& e) {
        FC_WARN(getFullName() << ": the container check failed: " << e.what());
        enforceRecompute();
    }
    catch (const Standard_Failure& e) {
        FC_WARN(getFullName() << ": the container check failed: " << e.GetMessageString());
        enforceRecompute();
    }
    catch (const std::exception& e) {
        FC_WARN(getFullName() << ": the container check failed: " << e.what());
        enforceRecompute();
    }
}

void ShapeBinder::followChangedObject(const App::DocumentObject& Obj, const App::Property& Prop)
{
    App::Document* doc = getDocument();
    if (!doc || doc->testStatus(App::Document::Restoring)) {
        return;
    }
    if (this == &Obj) {
        return;
    }
    if (!TraceSupport.getValue() || testStatus(App::ObjectStatus::Remove)) {
        return;
    }
    // FreeCAD-CH (ops#244, PR 244 review H1, M1, verification 2): the binder's place depends on
    // both containers' places, which change when the binder, the support or a container above
    // either enters or leaves a container (a copy added to its body after its first recompute at
    // the root, PartDesign_MoveFeature, a drag in the tree) with no Placement changed: it kept
    // its old place, silently. So on any such Group change, both frames are compared with those
    // of its last execute.
    auto* group = Obj.getExtensionByType<App::GeoFeatureGroupExtension>(true);
    if (group && &Prop == &group->Group) {
        Base::Placement sourceCS;
        Base::Placement targetCS;
        if (!traced) {
            // not computed since it was made or opened: its frames are taken now when it is
            // where it should be (PR 244 verification 2, L1: the shape was built again on every
            // Group change after a file was opened)
            if (hasPlacementChanged()) {
                enforceRecompute();
            }
            else {
                traced = containerFrames(tracedSourceCS, tracedTargetCS);
            }
        }
        else if (containerFrames(sourceCS, targetCS)
                 && (!samePlace(sourceCS, tracedSourceCS)
                     || !samePlace(targetCS, tracedTargetCS))) {
            enforceRecompute();
        }
        return;
    }
    if (!Prop.isDerivedFrom<App::PropertyPlacement>()) {
        return;
    }

    App::GeoFeature* obj = nullptr;
    std::vector<std::string> subs;
    ShapeBinder::getFilteredReferences(&Support, obj, subs);
    if (obj) {
        if (obj == &Obj) {
            // the directly referenced object has changed
            if (hasPlacementChanged()) {
                enforceRecompute();
            }
        }
        else if (Obj.hasExtension(App::GroupExtension::getExtensionClassTypeId())) {
            // check if the changed property belongs to a group-like object
            // like Body or Part
            std::vector<App::DocumentObject*> chain;
            std::vector<App::DocumentObject*> list = getInListRecursive();
            chain.insert(chain.end(), list.begin(), list.end());
            list = obj->getInListRecursive();
            chain.insert(chain.end(), list.begin(), list.end());

            if (const auto it = std::ranges::find(chain, &Obj); it != chain.end()) {
                if (hasPlacementChanged()) {
                    enforceRecompute();
                }
            }
        }
    }
}

// ============================================================================

PROPERTY_SOURCE(PartDesign::SubShapeBinder, Part::Feature)

SubShapeBinder::SubShapeBinder()
{
    ADD_PROPERTY_TYPE(Support, (nullptr), "", (App::PropertyType)(App::Prop_None), "Support of the geometry");
    Support.setStatus(App::Property::ReadOnly, true);
    // Several supports, one gone: the binder computes on the rest with a warning (ops#127)
    Support.setPartialAllowed(true);
    ADD_PROPERTY_TYPE(Fuse, (false), "Base", App::Prop_None, "Fuse solids from bound shapes");
    ADD_PROPERTY_TYPE(MakeFace, (true), "Base", App::Prop_None, "Create face using wires from bound shapes");
    ADD_PROPERTY_TYPE(
        Offset,
        (0.0),
        "Offsetting",
        App::Prop_None,
        "2D offset face or wires, 0.0 = no offset"
    );
    ADD_PROPERTY_TYPE(OffsetJoinType, ((long)0), "Offsetting", App::Prop_None, "Arcs, Tangent, Intersection");
    static const char* JoinTypeEnum[] = {"Arcs", "Tangent", "Intersection", nullptr};
    OffsetJoinType.setEnums(JoinTypeEnum);
    ADD_PROPERTY_TYPE(
        OffsetFill,
        (false),
        "Offsetting",
        App::Prop_None,
        "True = make face between original wire and offset."
    );
    ADD_PROPERTY_TYPE(
        OffsetOpenResult,
        (false),
        "Offsetting",
        App::Prop_None,
        "False = make closed offset from open wire."
    );
    ADD_PROPERTY_TYPE(
        OffsetIntersection,
        (false),
        "Offsetting",
        App::Prop_None,
        "False = offset child wires independently."
    );
    ADD_PROPERTY_TYPE(ClaimChildren, (false), "Base", App::Prop_Output, "Claim linked object as children");
    ADD_PROPERTY_TYPE(Relative, (true), "Base", App::Prop_None, "Enable relative sub-object binding");
    ADD_PROPERTY_TYPE(
        BindMode,
        ((long)0),
        "Base",
        App::Prop_None,
        "Synchronized: auto update binder shape on changed of bound object.\n"
        "Frozen: disable auto update, but can be updated manually using context menu.\n"
        "Detached: copy the shape of bound object and then remove the binding immediately."
    );
    ADD_PROPERTY_TYPE(
        PartialLoad,
        (false),
        "Base",
        App::Prop_None,
        "Enable partial loading, which disables auto loading of external document for"
        "external bound object."
    );
    PartialLoad.setStatus(App::Property::PartialTrigger, true);
    static const char* BindModeEnum[] = {"Synchronized", "Frozen", "Detached", nullptr};
    BindMode.setEnums(BindModeEnum);

    ADD_PROPERTY_TYPE(
        Context,
        (nullptr),
        "Base",
        App::Prop_Hidden,
        "Stores the context of this binder. It is used for monitoring and auto updating\n"
        "the relative placement of the bound shape"
    );

    static const char* BindCopyOnChangeEnum[] = {"Disabled", "Enabled", "Mutated", nullptr};
    BindCopyOnChange.setEnums(BindCopyOnChangeEnum);
    ADD_PROPERTY_TYPE(
        BindCopyOnChange,
        ((long)0),
        "Base",
        App::Prop_None,
        "Disabled: disable copy on change.\n"
        "Enabled: duplicate properties from binding object that are marked with 'CopyOnChange'.\n"
        "         Make internal copy of the object with any changed properties to obtain the\n"
        "         shape of an alternative configuration\n"
        "Mutated: indicate the binder has already mutated by changing any properties marked with\n"
        "         'CopyOnChange'. Those properties will not longer be kept in sync between the\n"
        "         binder and the binding object"
    );

    ADD_PROPERTY_TYPE(
        Refine,
        (true),
        "Base",
        (App::PropertyType)(App::Prop_None),
        "Refine shape (clean up redundant edges) after adding/subtracting"
    );

    Context.setScope(App::LinkScope::Hidden);

    ADD_PROPERTY_TYPE(
        _Version,
        (0),
        "Base",
        (App::PropertyType)(App::Prop_Hidden | App::Prop_ReadOnly),
        ""
    );

    _CopiedLink.setScope(App::LinkScope::Hidden);
    ADD_PROPERTY_TYPE(
        _CopiedLink,
        (nullptr),
        "Base",
        (App::PropertyType)(App::Prop_Hidden | App::Prop_ReadOnly | App::Prop_NoPersist),
        ""
    );
}

SubShapeBinder::~SubShapeBinder()
{
    try {
        clearCopiedObjects();
    }
    catch (const Base::ValueError& e) {
        e.reportException();
    }
}

void SubShapeBinder::setupObject()
{
    // Version 3 marks binders that default to FaceMakerBuildFace when turning
    // bound wires into faces. Older binders keep the previous face maker.
    _Version.setValue(3);
    checkPropertyStatus();
}

App::DocumentObject* SubShapeBinder::getSubObject(
    const char* subname,
    PyObject** pyObj,
    Base::Matrix4D* mat,
    bool transform,
    int depth
) const
{
    auto sobj = Part::Feature::getSubObject(subname, pyObj, mat, transform, depth);
    if (sobj) {
        return sobj;
    }
    if (Data::findElementName(subname) == subname) {
        return nullptr;
    }

    const char* dot = strchr(subname, '.');
    if (!dot) {
        return nullptr;
    }

    App::GetApplication().checkLinkDepth(depth);
    std::string name(subname, dot - subname);
    for (auto& l : Support.getSubListValues()) {
        auto obj = l.getValue();
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        for (auto& sub : l.getSubValues()) {
            auto sobj = obj->getSubObject(sub.c_str());
            if (!sobj || !sobj->isAttachedToDocument()) {
                continue;
            }
            if (subname[0] == '$') {
                if (sobj->Label.getStrValue() != name.c_str() + 1) {
                    continue;
                }
            }
            else if (!boost::equals(sobj->getNameInDocument(), name)) {
                continue;
            }
            name = Data::noElementName(sub.c_str());
            name += dot + 1;
            if (mat && transform) {
                *mat *= Placement.getValue().toMatrix();
            }
            return obj->getSubObject(name.c_str(), pyObj, mat, true, depth + 1);
        }
    }
    return nullptr;
}

void SubShapeBinder::setupCopyOnChange()
{
    copyOnChangeConns.clear();

    const auto& support = Support.getSubListValues();
    if (BindCopyOnChange.getValue() == 0 || support.size() != 1) {
        if (hasCopyOnChange) {
            hasCopyOnChange = false;
            std::vector<App::Property*> props;
            getPropertyList(props);
            for (auto prop : props) {
                if (App::LinkBaseExtension::isCopyOnChangeProperty(this, *prop)) {
                    try {
                        removeDynamicProperty(prop->getName());
                    }
                    catch (Base::Exception& e) {
                        e.reportException();
                    }
                    catch (...) {
                    }
                }
            }
        }
        return;
    }

    auto linked = support.front().getValue();
    hasCopyOnChange = App::LinkBaseExtension::setupCopyOnChange(
        this,
        linked,
        BindCopyOnChange.getValue() == 1 ? &copyOnChangeConns : nullptr,
        hasCopyOnChange
    );
    if (hasCopyOnChange) {
        copyOnChangeConns.emplace_back(linked->signalChanged.connect(
            [this](const App::DocumentObject&, const App::Property& prop) {
                if (!prop.testStatus(App::Property::Output)
                    && !prop.testStatus(App::Property::PropOutput)) {
                    if (!this->_CopiedObjs.empty()) {
                        FC_LOG(
                            "Clear binder " << getFullName() << " cache on change of "
                                            << prop.getFullName()
                        );
                        this->clearCopiedObjects();
                    }
                }
            }
        ));
    }
}

void SubShapeBinder::clearCopiedObjects()
{
    std::vector<App::DocumentObjectT> objs;
    objs.swap(_CopiedObjs);
    for (auto& o : objs) {
        auto obj = o.getObject();
        if (obj) {
            obj->getDocument()->removeObject(obj->getNameInDocument());
        }
    }
    _CopiedLink.setValue(nullptr);
}

// The parent that the supports' paths are resolved from, and the path to the binder in it;
// nullptr with Relative off, or with no parent. update() stores it as the Context
App::DocumentObject* SubShapeBinder::resolveParent(std::string& parentSub) const
{
    auto parent = Context.getValue();
    parentSub = Context.getSubName(false);
    if (!Relative.getValue()) {
        return nullptr;
    }
    if (parent && parent->getSubObject(parentSub.c_str()) == this) {
        auto parents = parent->getParents();
        if (!parents.empty()) {
            parent = parents.begin()->first;
            parentSub = parents.begin()->second + parentSub;
        }
    }
    else {
        parent = nullptr;
    }
    if (!parent && parentSub.empty()) {
        auto parents = getParents();
        if (!parents.empty()) {
            parent = parents.begin()->first;
            parentSub = parents.begin()->second;
        }
    }
    return parent;
}

// The matrix that maps each support's shape into the binder's coordinates. report: log what
// can't be resolved (update() does; mustExecute() doesn't)
std::map<const App::DocumentObject*, Base::Matrix4D> SubShapeBinder::supportMatrices(
    App::DocumentObject* parent,
    const std::string& parentSub,
    bool report
) const
{
    std::map<const App::DocumentObject*, Base::Matrix4D> mats;
    for (auto& l : Support.getSubListValues()) {
        auto obj = l.getValue();
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        auto res = mats.emplace(obj, Base::Matrix4D());
        if (!res.second) {
            continue;
        }
        if (!parent) {
            // No parent to resolve the path from (Relative off, or a binder at the document's top
            // level): the support's shape is in its own container's coordinates, the binder's
            // in its own. Map between them (FreeCAD-CH ops#308 F1, F4: such a binder of a face
            // of a feature in a Body moved by (100, 50) stayed at the origin)
            res.first->second =
                (containerPlacement(this).inverse() * containerPlacement(obj)).toMatrix();
            continue;
        }
        std::string resolvedSub = parentSub;
        std::string linkSub;
        auto link = obj;
        auto resolved = parent->resolveRelativeLink(resolvedSub, link, linkSub);
        // Not found under the binder's parent (two Bodies at the document's top level, or
        // under one App::Part): the path stays as it was, and the support's shape is in its
        // own container's coordinates, not the document's (FreeCAD-CH ops#308 T4: a binder
        // of a face of a feature in a Body moved by (100, 50) stayed at the origin)
        const bool outside = resolved == parent && resolvedSub == parentSub && obj != parent;
        if (!resolved) {
            if (!link && report) {
                FC_WARN(
                    getFullName() << " cannot resolve relative link of " << parent->getFullName()
                                  << '.' << parentSub << " -> " << obj->getFullName()
                );
            }
            continue;
        }
        Base::Matrix4D mat;
        auto sobj = resolved->getSubObject(resolvedSub.c_str(), nullptr, &mat);
        if (sobj != this) {
            if (report) {
                FC_LOG(
                    getFullName()
                    << " skip invalid parent " << resolved->getFullName() << '.' << resolvedSub
                );
            }
        }
        else if (_Version.getValue() == 0) {
            // For existing legacy SubShapeBinder, the support's mapping cancels the
            // Placement. (Upstream stored the first support's adjustment in the Placement
            // instead, behind a flag that was never set.)
            mat.inverseGauss();
            res.first->second = mat;
        }
        else {
            // For newer SubShapeBinder, the Placement property is free
            // to use by the user to add additional offset to the
            // binding object
            mat.inverseGauss();
            res.first->second = Placement.getValue().toMatrix() * mat;
            if (outside) {
                res.first->second = res.first->second * containerPlacement(obj).toMatrix();
            }
        }
    }
    return mats;
}

// The name of the property that caches a support's matrix
std::string SubShapeBinder::cacheName(const App::DocumentObject* obj) const
{
    std::string name = "Cache_";
    name += obj->getNameInDocument();
    if (obj->getDocument() != getDocument()) {
        name += "_";
        name += obj->getDocument()->getName();
    }
    return name;
}

short SubShapeBinder::mustExecute() const
{
    if (short ret = inherited::mustExecute()) {
        return ret;
    }
    // A support whose mapping changed with nothing touching the binder: its Body in another
    // document moved, which the slot that follows a support's container doesn't hear, since it
    // listens to the binder's own document (FreeCAD-CH ops#308 R2-1: such a binder stayed
    // where the Body had been). Compared with the matrix the last update used, so a failed one
    // isn't rerun until the mapping changes again; before any, with the saved cache, so a
    // support document moved while this one was closed counts as well. Only a synchronized
    // binder follows its supports.
    if (BindMode.getValue() != 0 || isRestoring() || !getDocument()) {
        return 0;
    }
    try {
        std::string parentSub;
        auto parent = resolveParent(parentSub);
        for (const auto& [obj, mat] : supportMatrices(parent, parentSub, false)) {
            const std::string name = cacheName(obj);
            const Base::Matrix4D* last = nullptr;
            if (auto it = lastMats.find(name); it != lastMats.end()) {
                last = &it->second;
            }
            else if (auto prop = freecad_cast<App::PropertyMatrix*>(
                         getDynamicPropertyByName(name.c_str())
                     )) {
                last = &prop->getValue();
            }
            if (last && !sameMapping(*last, mat)) {
                return 1;
            }
        }
    }
    catch (...) {
        // whatever can't be resolved now, the recompute reports
    }
    return 0;
}

void SubShapeBinder::update(SubShapeBinder::UpdateOption options)
{
    Part::TopoShape result = makeTopoShape(false);
    std::vector<Part::TopoShape> shapes;
    std::vector<std::pair<int, int>> shapeOwners;
    std::vector<const Base::Matrix4D*> shapeMats;
    // The shape's object is in another document: the key of its support's file for the boundary
    // section, Part::boundaryIndex() (ops#112); empty if not
    std::vector<std::string> shapeBoundary;

    bool forced = (Shape.getValue().IsNull() || (options & UpdateForced)) ? true : false;
    bool init = (!forced && (options & UpdateForced)) ? true : false;

    std::string errMsg;
    std::string missing;  // the subs that resolve to nothing, as "Label.Face3, ..."
    std::string parentSub;
    auto parent = resolveParent(parentSub);
    if (parent && (parent != Context.getValue() || parentSub != Context.getSubName(false))) {
        Context.setValue(parent, parentSub.c_str());
    }

    auto mats = supportMatrices(parent, parentSub, true);
    lastMats.clear();
    for (const auto& [obj, mat] : mats) {
        lastMats.emplace(cacheName(obj), mat);
    }
    int idx = -1;
    for (auto& l : Support.getSubListValues()) {
        ++idx;
        auto obj = l.getValue();
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        auto res = mats.find(obj);
        if (init) {
            continue;
        }

        App::DocumentObject* copied = nullptr;

        if (BindCopyOnChange.getValue() == 2 && Support.getSubListValues().size() == 1) {
            if (!_CopiedObjs.empty()) {
                copied = _CopiedObjs.front().getObject();
            }

            bool recomputeCopy = false;
            int copyerror = 0;
            if (!copied || !copied->isValid()) {
                recomputeCopy = true;
                clearCopiedObjects();

                App::DocumentInitFlags initFlags {.createView = false, .temporary = true};
                auto tmpDoc = App::GetApplication().newDocument("_tmp_binder", nullptr, initFlags);
                auto objs = tmpDoc->copyObject({obj}, true, true);
                if (!objs.empty()) {
                    for (auto it = objs.rbegin(); it != objs.rend(); ++it) {
                        _CopiedObjs.emplace_back(*it);
                    }
                    copied = objs.back();
                    // IMPORTANT! must make a recomputation first before any
                    // further change so that we can generate the correct
                    // geometry element map.
                    if (!copied->recomputeFeature(true)) {
                        copyerror = 1;
                    }
                }
            }

            if (copied) {
                if (!copyerror) {
                    std::vector<App::Property*> props;
                    getPropertyList(props);
                    // lambda for copying values of copy-on-change properties
                    const auto copyPropertyValues =
                        [this, &recomputeCopy, &props, copied](const bool to_support) {
                            for (auto prop : props) {
                                if (!App::LinkBaseExtension::isCopyOnChangeProperty(this, *prop)) {
                                    continue;
                                }
                                // we only copy read-only and output properties from support to binder
                                if (!to_support
                                    && !(
                                        prop->testStatus(App::Property::Output)
                                        && prop->testStatus(App::Property::ReadOnly)
                                    )) {
                                    continue;
                                }
                                auto p = copied->getPropertyByName(prop->getName());
                                if (p && p->getContainer() == copied
                                    && p->getTypeId() == prop->getTypeId() && !p->isSame(*prop)) {
                                    recomputeCopy = true;
                                    auto* const from = to_support ? prop : p;
                                    auto* const to = to_support ? p : prop;

                                    std::unique_ptr<App::Property> pcopy(from->Copy());
                                    to->Paste(*pcopy);
                                }
                            }
                        };

                    copyPropertyValues(true);
                    if (recomputeCopy && !copied->recomputeFeature(true)) {
                        copyerror = 2;
                    }
                    if (!copyerror) {
                        copyPropertyValues(false);
                    }
                }
                obj = copied;
                _CopiedLink.setValue(copied, l.getSubValues(false));
                if (copyerror) {
                    FC_THROWM(
                        Base::RuntimeError,
                        (
                            copyerror == 1 ? "Initial copy failed." : "Copy on change failed."
                        ) << " Please check report view for more details.\n"
                             "You can show temporary document to reveal the failed objects using\n"
                             "tree view context menu."
                    );
                }
            }
        }

        const auto& subvals = copied ? _CopiedLink.getSubValues() : l.getSubValues();
        std::set<std::string> subs(subvals.begin(), subvals.end());
        int sidx = copied ? -1 : idx;
        int subidx = -1;
        static std::string none;
        if (subs.empty()) {
            subs.insert(none);
        }
        else if (subs.size() > 1) {
            subs.erase(none);
        }
        for (const auto& sub : subs) {
            ++subidx;
            try {
                auto shape = Part::Feature::getTopoShape(
                    obj,
                    Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                        | Part::ShapeOption::Transform,
                    sub.c_str()
                );
                if (!shape.isNull()) {
                    shapes.push_back(shape);
                    shapeOwners.emplace_back(sidx, subidx);
                    shapeMats.push_back(&res->second);
                    // Keyed by the support's own document, not a copy-on-change copy's
                    // temporary one, whose name depends on the session: a support in this
                    // document gives 0
                    shapeBoundary.push_back(
                        obj->getDocument() != getDocument()
                            ? Part::boundaryIndex(*getDocument(), *l.getValue()->getDocument())
                            : std::string()
                    );
                }
                else if (const char* element = Data::findElementName(sub.c_str());
                         element && element[0]) {
                    // the element is gone ("?Face3"), or never existed
                    std::string name(element);
                    if (boost::starts_with(name, Data::MISSING_PREFIX)) {
                        name.erase(0, std::strlen(Data::MISSING_PREFIX));
                    }
                    missing += (missing.empty() ? "" : ", ") + std::string(obj->Label.getValue())
                        + '.' + std::string(sub.c_str(), element - sub.c_str()) + name;
                }
            }
            catch (Base::Exception& e) {
                e.reportException();
                FC_ERR(
                    getFullName() << " failed to obtain shape from " << obj->getFullName() << '.' << sub
                );
                if (errMsg.empty()) {
                    std::ostringstream ss;
                    ss << "Failed to obtain shape " << obj->getFullName() << '.'
                       << Data::oldElementName(sub.c_str());
                    errMsg = ss.str();
                }
            }
        }
    }

    if (!init) {

        if (!errMsg.empty()) {
            if (!(options & UpdateInit)) {
                FC_THROWM(Base::RuntimeError, errMsg);
            }
            if (!Shape.getValue().IsNull()) {
                return;
            }
        }

        // A sub-element that resolves to nothing must fail the binder, not leave it bound to
        // the rest, or to its old shape when nothing is left (ops#69). Only the recompute
        // reports it: update() also runs when Support changes, including while its references
        // are refreshed, where an exception would only be logged as a failed refresh. The
        // binder is recomputed after that. In a reference solver document it binds what
        // resolves, with a warning from the recompute check, while something does (ops#127).
        const bool partial =
            Support.isPartialAllowed() && Support.inSolverDocument() && !shapes.empty();
        if (!missing.empty() && !partial) {
            if (options & UpdateForced) {
                FC_THROWM(Base::RuntimeError, "Missing element in Support: " << missing);
            }
            return;
        }

        // If not forced, only rebuild when there is any change in
        // transformation matrix
        if (!forced) {
            bool hit = true;
            for (auto& v : mats) {
                auto prop = freecad_cast<App::PropertyMatrix*>(
                    getDynamicPropertyByName(cacheName(v.first).c_str())
                );
                if (!prop || prop->getValue() != v.second) {
                    hit = false;
                    break;
                }
            }
            if (hit) {
                return;
            }
        }
        std::ostringstream ss;
        int idx = -1;
        for (auto& shape : shapes) {
            ++idx;
            if (shape.getHistoryAlgorithm() == App::HistoryAlgorithm::V2) {
                // A shape from another document, with an element map or without: its names get
                // a boundary section with the binder's tag (ops#56) and the key of the
                // support's file, so supports from copies of one file get distinct names, in
                // any order (ops#112)
                if (!shapeBoundary[idx].empty()) {
                    shape.reTagElementMap(
                        getID(),
                        getDocument()->getStringHasher(),
                        Part::boundaryPostfix(shapeBoundary[idx]).c_str()
                    );
                }
            }
            else if (shape.Hasher && shape.getElementMapSize()
                     && shape.Hasher != getDocument()->getStringHasher()) {
                ss.str("");
                ss << Data::POSTFIX_EXTERNAL_TAG << Data::ComplexGeoData::elementMapPrefix()
                   << Part::OpCodes::Shapebinder << ':' << shapeOwners[idx].first << ':'
                   << shapeOwners[idx].second;
                shape.reTagElementMap(-getID(), getDocument()->getStringHasher(), ss.str().c_str());
            }
            if (!shape.hasSubShape(TopAbs_FACE) && shape.hasSubShape(TopAbs_EDGE)) {
                shape = shape.makeElementCopy();
            }
        }

        // A single support with Relative off used to drop the shape's own placement, which
        // left a face of a placed feature at the origin (ops#308 F4): it is mapped like the rest
        {
            for (size_t i = 0; i < shapes.size(); ++i) {
                auto& shape = shapes[i];
                shape = shape.makeElementTransform(*shapeMats[i]);
                // if(shape.Hasher
                //         && shape.getElementMapSize()
                //         && shape.Hasher != getDocument()->getStringHasher())
                // {
                //     shape.reTagElementMap(getID(),
                //             getDocument()->getStringHasher(),TOPOP_SHAPEBINDER);
                // }
            }
        }

        if (shapes.empty()) {
            // Shape.resetElementMapVersion();
            return;
        }
        result.makeElementCompound(shapes);
        bool fused = false;
        if (Fuse.getValue()) {
            // If the compound has solid, fuse them together, and ignore other type of
            // shapes
            std::vector<TopoDS_Shape> solids;
            Part::TopoShape solid = makeTopoShape(false);
            for (auto& s : result.getSubTopoShapes(TopAbs_SOLID)) {
                if (solid.isNull()) {
                    solid = s;
                }
                else {
                    solids.push_back(s.getShape());
                }
            }
            if (!solids.empty()) {
                result = solid.fuse(solids);
                fused = true;
            }
            else if (!solid.isNull()) {
                // wrap the single solid in compound to keep its placement
                result.makeElementCompound({solid});
                fused = true;
            }
        }

        if (!fused && (MakeFace.getValue() || Offset.getValue() != 0.0)
            && !result.hasSubShape(TopAbs_FACE) && result.hasSubShape(TopAbs_EDGE)) {
            result = result.makeElementWires();
            if (MakeFace.getValue()) {
                try {
                    // FaceMakerBuildFace became the default only for binders
                    // created with _Version >= 3. Binders from older documents
                    // predate sketches producing faces by default, so they keep
                    // the previous face maker (FaceMakerBullseye) to avoid
                    // silently changing their generated topology on reopen.
                    const char* faceMaker = _Version.getValue() >= 3 ? "Part::FaceMakerBuildFace"
                                                                     : nullptr;
                    result = result.makeElementFace(nullptr, faceMaker);
                }
                catch (...) {
                }
            }
        }

        if (!fused && result.hasSubShape(TopAbs_WIRE) && Offset.getValue() != 0.0) {
            try {
                result = result.makeElementOffset2D(
                    Offset.getValue(),
                    (Part::JoinType)OffsetJoinType.getValue(),
                    OffsetFill.getValue() ? Part::FillType::fill : Part::FillType::noFill,
                    OffsetOpenResult.getValue() ? Part::OpenResult::allowOpenResult
                                                : Part::OpenResult::noOpenResult,
                    OffsetIntersection.getValue()
                );
            }
            catch (...) {
                std::ostringstream msg;
                msg << Label.getValue() << ": failed to make 2D offset" << std::endl;
                Base::Console().error(msg.str().c_str());
            }
        }

        if (Refine.getValue()) {
            result = result.makeElementRefine();
        }
        result.setPlacement(Placement.getValue());
        Shape.setValue(result);
    }

    // collect transformation matrix cache entries
    std::unordered_set<std::string> caches;
    for (const auto& name : getDynamicPropertyNames()) {
        if (boost::starts_with(name, "Cache_")) {
            caches.emplace(name);
        }
    }

    // update transformation matrix cache
    for (auto& v : mats) {
        const std::string cache = cacheName(v.first);
        const char* name = cache.c_str();
        auto prop = getDynamicPropertyByName(name);
        if (!prop || !prop->isDerivedFrom<App::PropertyMatrix>()) {
            if (prop) {
                removeDynamicProperty(name);
            }
            prop = addDynamicProperty("App::PropertyMatrix", name, "Cache", nullptr, 0, false, true);
        }
        caches.erase(name);
        static_cast<App::PropertyMatrix*>(prop)->setValue(v.second);
    }

    // remove any non-used cache entries.
    for (const auto& name : caches) {
        try {
            removeDynamicProperty(name.c_str());
        }
        catch (...) {
        }
    }

    // With no Context, or Relative off, nothing connected the slot that follows a support's
    // container when it moves (ops#308 F1, F4)
    if (!connRecomputedObj.connected() && getDocument()) {
        contextDoc = getDocument();
        connRecomputedObj = contextDoc->signalRecomputedObject.connect(
            [this](const App::DocumentObject& obj) { slotRecomputedObject(obj); }
        );
    }
}

void SubShapeBinder::slotRecomputedObject(const App::DocumentObject& Obj)
{
    // Only a synchronized binder follows its supports: update() re-reads their shapes, so a
    // Frozen one took its source's later changes as soon as the source's Body or its own context
    // recomputed (FreeCAD-CH ops#308 r3 F1)
    if (BindMode.getValue() != 0) {
        return;
    }
    // A container of a support moves it too, as the binder's own context does (ops#308 T4): a
    // Body that was moved recomputes, its features don't
    auto contains = [this, &Obj]() {
        for (auto obj : Support.getValues()) {
            for (auto group = obj ? App::GeoFeatureGroupExtension::getGroupOfObject(obj) : nullptr;
                 group;
                 group = App::GeoFeatureGroupExtension::getGroupOfObject(group)) {
                if (group == &Obj) {
                    return true;
                }
            }
        }
        return false;
    };
    if ((Context.getValue() == &Obj || contains())
        && !this->testStatus(App::ObjectStatus::Recompute2)) {
        try {
            update();
        }
        catch (Base::Exception& e) {
            e.reportException();
        }
    }
}

App::DocumentObjectExecReturn* SubShapeBinder::recompute()
{
    // A support that depends on this binder makes a cycle, which no recompute settles: its
    // objects stay touched after every one, with no error. A path through a Body does it when
    // that Body holds a binder of this one's Body ((Body1, "PadA.Face6") in Body2, then
    // (Body2, "PadB.Face5") in Body1): a Body depends on all its features. Bound to the feature
    // itself, (PadA, "Face6"), nothing loops (FreeCAD-CH ops#308 T2). Checked before the
    // reference check of DocumentObject::recompute(): once the cycle has failed the features
    // between, the bound element is gone, and the cause would be reported as a missing face.
    for (auto obj : Support.getValues()) {
        if (!obj || obj == this) {
            continue;
        }
        bool cyclic = false;
        try {
            const std::vector<App::DocumentObject*> deps = obj->getOutListRecursive();
            cyclic = std::ranges::find(deps, this) != deps.end();
        }
        catch (const Base::BadGraphError&) {
            cyclic = true;
        }
        if (cyclic) {
            return new App::DocumentObjectExecReturn(
                std::string("Cyclic dependency: the support ") + obj->Label.getValue()
                    + " depends on this binder. Bind the feature's element itself (Feature, "
                      "Face), not through its Body",
                this
            );
        }
    }
    return inherited::recompute();
}

App::DocumentObjectExecReturn* SubShapeBinder::execute()
{
    setupCopyOnChange();

    if (BindMode.getValue() == 0) {
        update(UpdateForced);
    }

    return inherited::execute();
}

void SubShapeBinder::onDocumentRestored()
{
    if (_Version.getValue() < 2) {
        update(UpdateInit);
    }
    inherited::onDocumentRestored();
}

void SubShapeBinder::collapseGeoChildren()
{
    // Geo children, i.e. children of GeoFeatureGroup may group some tool
    // features under itself but does not function as a container. In addition,
    // its parent group can directly reference the tool feature grouped without
    // referencing the child. The purpose of this function is to remove any
    // intermediate Non group features in the object path to avoid unnecessary
    // dependencies.
    if (Support.testStatus(App::Property::User3)) {
        return;
    }

    Base::ObjectStatusLocker<App::Property::Status, App::Property> guard(App::Property::User3, &Support);
    App::PropertyXLinkSubList::atomic_change guard2(Support, false);

    std::vector<App::DocumentObject*> removes;
    std::map<App::DocumentObject*, std::vector<std::string>> newVals;
    std::ostringstream ss;
    for (auto& l : Support.getSubListValues()) {
        auto obj = l.getValue();
        if (!obj || !obj->getNameInDocument()) {
            continue;
        }
        auto subvals = l.getSubValues();
        if (subvals.empty()) {
            continue;
        }
        bool touched = false;
        for (auto itSub = subvals.begin(); itSub != subvals.end();) {
            auto& sub = *itSub;
            // A sub-element that no longer exists ("?Face3") doesn't resolve, so normalize()
            // would turn it into "", which binds the whole object and drops the other subs.
            // Keep it as it is: update() reports it (ops#69).
            if (Data::hasMissingElement(sub.c_str())) {
                ++itSub;
                continue;
            }
            App::SubObjectT sobjT(obj, sub.c_str());
            if (sobjT.normalize(App::SubObjectT::NormalizeOption::KeepSubName)) {
                touched = true;
                auto newobj = sobjT.getObject();
                sub = sobjT.getSubName();
                if (newobj != obj) {
                    newVals[newobj].push_back(std::move(sub));
                    itSub = subvals.erase(itSub);
                    continue;
                }
            }
            ++itSub;
        }
        if (touched) {
            removes.push_back(obj);
        }
        if (!subvals.empty() && touched) {
            auto& newSubs = newVals[obj];
            if (newSubs.empty()) {
                newSubs = std::move(subvals);
            }
            else {
                newSubs.insert(
                    newSubs.end(),
                    std::make_move_iterator(subvals.begin()),
                    std::make_move_iterator(subvals.end())
                );
            }
        }
    }

    if (removes.size() || newVals.size()) {
        guard2.aboutToChange();
    }
    for (auto obj : removes) {
        Support.removeValue(obj);
    }
    if (newVals.size()) {
        setLinks(std::move(newVals));
    }
}

void SubShapeBinder::onChanged(const App::Property* prop)
{
    if (prop == &Context || prop == &Relative) {
        if (!Context.getValue() || !Relative.getValue()) {
            connRecomputedObj.disconnect();
        }
        else if (contextDoc != Context.getValue()->getDocument() || !connRecomputedObj.connected()) {
            // NOLINTBEGIN
            contextDoc = Context.getValue()->getDocument();
            connRecomputedObj = contextDoc->signalRecomputedObject.connect(
                std::bind(&SubShapeBinder::slotRecomputedObject, this, sp::_1)
            );
            // NOLINTEND
        }
    }
    else if (!isRestoring()) {
        if (prop == &Support) {
            collapseGeoChildren();
            clearCopiedObjects();
            setupCopyOnChange();
            if (!Support.getSubListValues().empty()) {
                update();
                if (BindMode.getValue() == 2) {
                    Support.setValue(nullptr);
                }
            }
        }
        else if (prop == &BindCopyOnChange) {
            setupCopyOnChange();
        }
        else if (prop == &BindMode) {
            if (BindMode.getValue() == 2) {
                Support.setValue(nullptr);
            }
            else if (BindMode.getValue() == 0) {
                update();
            }
            checkPropertyStatus();
        }
        else if (prop == &PartialLoad) {
            checkPropertyStatus();
        }
        else if (prop && !prop->testStatus(App::Property::User3)) {
            checkCopyOnChange(*prop);
        }
    }
    inherited::onChanged(prop);
}

void SubShapeBinder::checkCopyOnChange(const App::Property& prop)
{
    if (BindCopyOnChange.getValue() != 1 || getDocument()->isPerformingTransaction()
        || !App::LinkBaseExtension::isCopyOnChangeProperty(this, prop)
        || Support.getSubListValues().size() != 1) {
        return;
    }

    auto linked = Support.getSubListValues().front().getValue();
    if (!linked) {
        return;
    }
    auto linkedProp = linked->getPropertyByName(prop.getName());
    if (linkedProp && linkedProp->getTypeId() == prop.getTypeId() && !linkedProp->isSame(prop)) {
        BindCopyOnChange.setValue(2);
    }
}

void SubShapeBinder::checkPropertyStatus()
{
    Support.setAllowPartial(PartialLoad.getValue());

    // Make Shape transient can reduce some file size, and maybe reduce file
    // loading time as well. But there maybe complication arise when doing
    // TopoShape version upgrade. So we DO NOT set transient at the moment.
    //
    // Shape.setStatus(App::Property::Transient, !PartialLoad.getValue() && BindMode.getValue()==0);
}

void SubShapeBinder::setLinks(
    std::map<App::DocumentObject*, std::vector<std::string>>&& values,
    bool reset
)
{
    if (values.empty()) {
        if (reset) {
            Support.setValue(nullptr);
            Shape.setValue(makeTopoShape(false));
        }
        return;
    }
    auto inSet = getInListEx(true);
    inSet.insert(this);

    for (auto& v : values) {
        if (!v.first || !v.first->isAttachedToDocument()) {
            FC_THROWM(Base::ValueError, "Invalid document object");
        }
        if (inSet.find(v.first) != inSet.end()) {
            FC_THROWM(Base::ValueError, "Cyclic reference to " << v.first->getFullName());
        }

        if (v.second.empty()) {
            v.second.emplace_back("");
            continue;
        }

        std::vector<std::string> wholeSubs;
        for (auto& sub : v.second) {
            if (sub.empty()) {
                wholeSubs.clear();
                v.second.resize(1);
                v.second[0].clear();
                break;
            }
            else if (sub[sub.size() - 1] == '.') {
                wholeSubs.push_back(sub);
            }
        }
        for (auto& whole : wholeSubs) {
            for (auto it = v.second.begin(); it != v.second.end();) {
                auto& sub = *it;
                if (!boost::starts_with(sub, whole) || sub.size() == whole.size()) {
                    ++it;
                }
                else {
                    FC_LOG("Remove subname " << sub << " because of whole selection " << whole);
                    it = v.second.erase(it);
                }
            }
        }
    }

    if (!reset) {
        for (auto& link : Support.getSubListValues()) {
            auto subs = link.getSubValues();
            auto& s = values[link.getValue()];
            if (s.empty()) {
                s = std::move(subs);
                continue;
            }
            else if (subs.empty() || s[0].empty()) {
                continue;
            }

            for (auto& sub : s) {
                for (auto it = subs.begin(); it != subs.end();) {
                    if (sub[sub.size() - 1] == '.') {
                        if (boost::starts_with(*it, sub)) {
                            FC_LOG("Remove subname " << *it << " because of whole selection " << sub);
                            it = subs.erase(it);
                        }
                        else {
                            ++it;
                        }
                    }
                    else if (it->empty() || (it->back() == '.' && boost::starts_with(sub, *it))) {
                        FC_LOG("Remove whole subname " << *it << " because of " << sub);
                        it = subs.erase(it);
                    }
                    else {
                        ++it;
                    }
                }
            }
            subs.insert(subs.end(), s.begin(), s.end());
            s = std::move(subs);
        }
    }
    Support.setValues(std::move(values));
}

void SubShapeBinder::handleChangedPropertyType(
    Base::XMLReader& reader,
    const char* TypeName,
    App::Property* prop
)
{
    if (prop == &Support) {
        Support.upgrade(reader, TypeName);
    }
    else {
        inherited::handleChangedPropertyType(reader, TypeName, prop);
    }
}

////////////////////////////////////////////////////////////////////////////////////////

namespace App
{
PROPERTY_SOURCE_TEMPLATE(PartDesign::SubShapeBinderPython, PartDesign::SubShapeBinder)
template<>
const char* PartDesign::SubShapeBinderPython::getViewProviderName() const
{
    return "PartDesignGui::ViewProviderSubShapeBinderPython";
}
template class PartDesignExport FeaturePythonT<PartDesign::SubShapeBinder>;
}  // namespace App
