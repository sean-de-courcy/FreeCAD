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
#include "StudioList.h"
#include "StudioOwner.h"
#include "StudioTransform.h"

namespace PartDesign
{

namespace
{

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
    const Part::TopoShape& base,
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
            return fail(
                std::string("'") + source->Label.getValue() + "' has no solid before " + label
            );
        }
        Part::TopoShape out(tag, owner->getDocument()->getStringHasher());
        out.makeElementTransform(
            solid,
            (bodyFrame.inverse() * motion).toMatrix(),
            Part::OpCodes::Copy,
            Part::CheckScale::noScaleCheck,
            Part::CopyType::copy
        );
        return out;
    }
    if (base.isNull()) {
        return fail("Nothing comes before " + label + " in " + part + ": it has no solid to move");
    }
    if (copy) {
        return base;  // the source of a copy stays where it is
    }
    // Moved: its location composed with the motion in the Body's frame; geometry and element map
    // are the base's, so what refers to its faces follows (Onshape: a moved part keeps its ids)
    Part::TopoShape out = base;
    out.setPlacement(bodyFrame.inverse() * motion * bodyFrame * base.getPlacement());
    return out;
}

}  // namespace PartDesign
