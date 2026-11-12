// SPDX-License-Identifier: LGPL-2.1-or-later

// FreeCAD-CH ops#655: a Transform studio feature's steps (notes/transform-design.md)

#include <string>
#include <vector>

#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/PropertyGeo.h>
#include <App/PropertyStandard.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "Body.h"
#include "Feature.h"
#include "StudioList.h"
#include "StudioOwner.h"
#include "StudioTransform.h"

namespace PartDesign
{

namespace
{

/// shape scaled by mat (Scale, ops#677) as new geometry under owner's tag: its location is folded
/// into the matrix first, so a non-uniform scale (BRepBuilderAPI_GTransform) gets a shape without
/// one. No op: copyElementMap passes the mapped names through
Part::TopoShape scaledShape(
    const App::DocumentObject* owner,
    long tag,
    const Part::TopoShape& shape,
    const Base::Matrix4D& mat
)
{
    Part::TopoShape local = shape;
    const Base::Matrix4D place = shape.getPlacement().toMatrix();
    local.setPlacement(Base::Placement());
    Part::TopoShape out(tag, owner->getDocument()->getStringHasher());
    out.makeElementTransform(
        local,
        mat * place,
        nullptr,
        Part::CheckScale::checkScale,
        Part::CopyType::copy
    );
    return out;
}

/// The source part id of the copy made, from owner's "StudioCopies" ("<made id>=<source id>")
std::string copySourceId(const App::DocumentObject* owner, const std::string& made)
{
    auto copies = freecad_cast<App::PropertyStringList*>(owner->getPropertyByName("StudioCopies"));
    if (!copies) {
        return {};
    }
    const std::string prefix = made + "=";
    for (const auto& record : copies->getValues()) {
        if (record.compare(0, prefix.size(), prefix) == 0) {
            return record.substr(prefix.size());
        }
    }
    return {};
}

/// part's shape just before owner's step, in part's frame, of any kind: a solid, a sheet or a
/// wire body (ops#678, Onshape TR10: Transform moves surfaces and curves too). The usual bases
/// (getBaseTopoShape, studioBaseAt) keep solids only. Null when there is no step or nothing
/// with an edge before it
Part::TopoShape anyBaseOf(const App::DocumentObject* owner, const Body* part)
{
    Feature* step = StudioList::stepOf(owner, part);
    if (!step) {
        return {};
    }
    auto previous =
        freecad_cast<const Part::Feature*>(const_cast<Body*>(part)->getPrevSolidFeature(step));
    if (!previous) {
        return {};
    }
    Part::TopoShape shape = previous->Shape.getShape();
    if (shape.isNull() || !shape.hasSubShape(TopAbs_EDGE)) {
        return {};
    }
    return shape;
}

const Body* partWithId(const App::Document* doc, const std::string& id)
{
    if (id.empty()) {
        return nullptr;
    }
    for (auto obj : doc->getObjectsOfType(Body::getClassTypeId())) {
        auto body = static_cast<const Body*>(obj);
        if (studioPartId(body) == id) {
            return body;
        }
    }
    return nullptr;
}

}  // namespace

bool isStudioTransform(const App::DocumentObject* owner)
{
    return owner && freecad_cast<App::PropertyPlacement*>(owner->getPropertyByName("StudioTransform"))
        && freecad_cast<App::PropertyBool*>(owner->getPropertyByName("MakeCopy"));
}

Part::TopoShape studioTransformStep(
    const App::DocumentObject* owner,
    const Body* body,
    const Part::TopoShape& solidBase,
    long tag,
    std::string* why
)
{
    auto fail = [why](const std::string& text) {
        if (why) {
            *why = text;
        }
        return Part::TopoShape();
    };
    if (!isStudioTransform(owner) || !body) {
        return fail("This step has no Transform");
    }
    const std::string label = std::string("'") + owner->Label.getValue() + "'";
    const std::string part = std::string("'") + body->Label.getValue() + "'";
    const Base::Placement motion =
        static_cast<App::PropertyPlacement*>(owner->getPropertyByName("StudioTransform"))->getValue();
    const bool copy = static_cast<App::PropertyBool*>(owner->getPropertyByName("MakeCopy"))->getValue();
    const Base::Placement bodyFrame = App::GeoFeature::getGlobalPlacement(body);
    // Scale (ops#677): its matrix in the document's frame; identity for the other types
    const auto* scaleProp = freecad_cast<App::PropertyMatrix*>(owner->getPropertyByName("StudioScale"));
    const bool scaled = scaleProp && scaleProp->getValue().hasScale(1e-9) != Base::ScaleType::NoScaling;
    const Base::Matrix4D docToBody = bodyFrame.inverse().toMatrix();
    // A sheet or a wire body moves as a solid does (ops#678, TR10); the caller's base is solids only
    const Part::TopoShape base = solidBase.isNull() ? anyBaseOf(owner, body) : solidBase;

    if (body->StudioMadeBy.getValue() == owner) {
        // A copy (Copy part): the source's solid where the Transform is in the history, moved, as
        // a part of its own with names of its own
        if (!copy) {
            return fail(label + " no longer copies: " + part + " has nothing to hold");
        }
        if (!base.isNull()) {
            return fail("Something comes before " + label + " in " + part + ", the copy it made");
        }
        const std::string sourceId = copySourceId(owner, studioPartId(body));
        const Body* source = partWithId(owner->getDocument(), sourceId);
        if (!source) {
            return fail("The part " + part + " was copied from is gone");
        }
        Part::TopoShape solid = studioBaseAt(owner, source);  // in the document's frame
        if (solid.isNull()) {
            // A sheet or a wire body (ops#678), in the document's frame as studioBaseAt's is
            solid = anyBaseOf(owner, source);
            if (!solid.isNull()) {
                solid.transformShape(source->globalPlacement().toMatrix(), false, true);
            }
        }
        if (solid.isNull()) {
            return fail(
                std::string("'") + source->Label.getValue() + "' has no shape before " + label
            );
        }
        Part::TopoShape out(tag, owner->getDocument()->getStringHasher());
        if (scaled) {
            out = scaledShape(owner, tag, solid, docToBody * scaleProp->getValue());
        }
        else {
            out.makeElementTransform(
                solid,
                (bodyFrame.inverse() * motion).toMatrix(),
                nullptr,
                Part::CheckScale::noScaleCheck,
                Part::CopyType::copy
            );
        }
        // Names of its own (I-A7): the owner's copy section on every name. V2 keeps a child's
        // mapped names as they are, so an op given to makeElementTransform() adds nothing here
        out.appendElementSection(owner->getID(), Part::OpCodes::Copy, "1");
        return out;
    }
    if (base.isNull()) {
        return fail("Nothing comes before " + label + " in " + part + ": it has nothing to move");
    }
    if (copy) {
        return base;  // the source of a copy stays where it is
    }
    if (scaled) {
        // Scaled: new geometry (a scale can't be a location), the base's names kept as a move keeps
        // them
        return scaledShape(owner, tag, base, docToBody * scaleProp->getValue() * bodyFrame.toMatrix());
    }
    // Moved: its location composed with the motion in the Body's frame; geometry and element map
    // are the base's, so what refers to its faces follows (Onshape: a moved part keeps its ids)
    Part::TopoShape out = base;
    out.setPlacement(bodyFrame.inverse() * motion * bodyFrame * base.getPlacement());
    return out;
}

}  // namespace PartDesign
