// SPDX-License-Identifier: LGPL-2.1-or-later

// Split (FreeCAD-CH ops#325, B+ Stage 1 session 4, notes/bplus-stage1-design.md 2.7)

#include <cstring>

#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepPrimAPI_MakeHalfSpace.hxx>
#include <Bnd_Box.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopoDS.hxx>
#include <gp_Ax3.hxx>
#include <gp_Trsf.hxx>

#include <App/Datums.h>
#include <App/Document.h>
#include <App/GeoFeature.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/GroupExtension.h>
#include <Mod/Part/App/TopoShapeOpCode.h>

#include "Body.h"
#include "FeatureBoolean.h"
#include "FeatureSplit.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true);

using namespace PartDesign;

namespace PartDesign
{

PROPERTY_SOURCE(PartDesign::Split, PartDesign::FeatureRefine)

const char* Split::SideEnums[] = {"Front", "Back", nullptr};

namespace
{
std::string label(const App::DocumentObject* obj)
{
    return obj ? obj->Label.getValue() : "None";
}

std::string planeLabel(const App::DocumentObject* tool, const std::string& sub)
{
    return label(tool) + (sub.empty() ? "" : "." + sub);
}

std::string firstSub(const App::PropertyLinkSub& link)
{
    const std::vector<std::string>& subs = link.getSubValues();
    return subs.empty() ? std::string() : subs.front();
}

/// Whether @p plane has some of @p base on both sides: the extent of base along the normal,
/// from its exact bounding box in the plane's frame. A plane through a vertex or along a face
/// leaves one side empty (the probe, notes/studio-gates.md "Session 4")
bool cuts(const TopoDS_Shape& base, const gp_Pln& plane)
{
    gp_Trsf toPlane;
    toPlane.SetTransformation(gp_Ax3(plane.Position()));
    BRepBuilderAPI_Transform moved(base, toPlane, /*copy=*/false);
    Bnd_Box box;
    BRepBndLib::AddOptimal(
        moved.Shape(),
        box,
        /*useTriangulation=*/false,
        /*useShapeTolerance=*/false
    );
    if (box.IsVoid()) {
        return false;
    }
    double xMin, yMin, zMin, xMax, yMax, zMax;
    box.Get(xMin, yMin, zMin, xMax, yMax, zMax);
    return zMin < -Precision::Confusion() && zMax > Precision::Confusion();
}
}  // namespace

Split::Split()
{
    ADD_PROPERTY_TYPE(
        Tool,
        (nullptr),
        "Split",
        App::Prop_None,
        "The plane: an origin plane, a datum plane or a planar face"
    );
    Tool.setScope(App::LinkScope::Global);
    ADD_PROPERTY_TYPE(
        Side,
        (0L),
        "Split",
        App::Prop_None,
        "The side of the plane that stays: Front, where its normal points, or Back"
    );
    Side.setEnums(SideEnums);
    ADD_PROPERTY_TYPE(
        Partner,
        (nullptr),
        "Split",
        App::Prop_ReadOnly,
        "The original part's Split, whose base, plane and side this one reads"
    );
    Partner.setScope(App::LinkScope::Global);
    ADD_PROPERTY_TYPE(
        NewHalf,
        (false),
        "Split",
        (App::PropertyType)(App::Prop_Hidden | App::Prop_ReadOnly),
        "The new part's Split: it keeps the other side of its partner's plane"
    );
    ADD_PROPERTY_TYPE(
        PartnerFrame,
        (Base::Placement()),
        "Split",
        (App::PropertyType)(App::Prop_Hidden | App::Prop_Output),
        "Where the partner's part was, in this part's frame, when this Split last computed"
    );
    ADD_PROPERTY_TYPE(
        ToolFrame,
        (Base::Placement()),
        "Split",
        (App::PropertyType)(App::Prop_Hidden | App::Prop_Output),
        "Where the plane's object was, in this part's frame, when this Split last computed"
    );
    Partner.setStatus(App::Property::Hidden, true);
}

Split* Split::partnerSplit() const
{
    return NewHalf.getValue() ? freecad_cast<Split*>(Partner.getValue()) : nullptr;
}

Base::Placement Split::partnerFrame() const
{
    Split* partner = partnerSplit();
    Body* own = getFeatureBody();
    Body* other = partner ? partner->getFeatureBody() : nullptr;
    const Base::Placement here = own ? own->globalPlacement() : Base::Placement();
    return here.inverse() * (other ? other->globalPlacement() : Base::Placement());
}

Base::Placement Split::toolFrame() const
{
    const Split* source = NewHalf.getValue() ? partnerSplit() : this;
    App::DocumentObject* tool = source ? source->Tool.getValue() : nullptr;
    if (!tool) {
        return {};
    }
    // The Tool with its container: its Body, the coordinate system or group of an origin plane
    Body* own = getFeatureBody();
    const Base::Placement here = own ? own->globalPlacement() : Base::Placement();
    return here.inverse() * App::GeoFeature::getGlobalPlacement(tool);
}

bool Split::waits() const
{
    const Split* held = NewHalf.getValue() ? partnerSplit() : this;
    Body* body = held ? held->getFeatureBody() : nullptr;
    return body && body->holds(held);
}

void Split::onChanged(const App::Property* prop)
{
    // The new half's own plane and side are unused: shown is the partner it reads
    if (prop == &NewHalf) {
        const bool newHalf = NewHalf.getValue();
        Tool.setStatus(App::Property::Hidden, newHalf);
        Side.setStatus(App::Property::Hidden, newHalf);
        Partner.setStatus(App::Property::Hidden, !newHalf);
    }
    FeatureRefine::onChanged(prop);
}

void Split::onDocumentRestored()
{
    onChanged(&NewHalf);
    FeatureRefine::onDocumentRestored();
}

short Split::mustExecute() const
{
    if (Tool.isTouched() || Side.isTouched() || Partner.isTouched() || NewHalf.isTouched()) {
        return 1;
    }
    // A part moved, and nothing this Split links changed (as a Merge's, ops#325 M-t6): the
    // partner's part, for the new half, or the Tool's own part. Not while it waits
    if (!waits()) {
        if (partnerSplit()
            && !partnerFrame().isSame(PartnerFrame.getValue(), Precision::Confusion())) {
            return 1;
        }
        if (!toolFrame().isSame(ToolFrame.getValue(), Precision::Confusion())) {
            return 1;
        }
    }
    return FeatureRefine::mustExecute();
}

App::DocumentObjectExecReturn* Split::recompute()
{
    // The new half fails with its partner's reason: both halves red, one message (design 2.7)
    if (Split* partner = partnerSplit(); partner && partner->isError()) {
        Body* body = getFeatureBody();
        if (!Suppressed.getValue() && !(body && body->holds(this))) {
            const char* why = getDocument()->getErrorDescription(partner);
            return new App::DocumentObjectExecReturn(
                why && *why ? std::string(why) : label(partner) + " failed",
                this
            );
        }
    }
    return FeatureRefine::recompute();
}

App::DocumentObjectExecReturn* Split::execute()
{
    // Whose base, plane and side: this Split's, or the new half's partner's with the other side
    const Split* source = this;
    bool keepFront = Side.getValue() == 0;
    if (NewHalf.getValue()) {
        Split* partner = partnerSplit();
        if (!partner) {
            return new App::DocumentObjectExecReturn("Its partner Split was deleted", this);
        }
        // The original rolled back between the split point and its Split holds the partner:
        // this half waits with it, keeping its last shape, until the original rolls to its end
        if (Body* body = partner->getFeatureBody(); body && body->holds(partner)) {
            return App::DocumentObject::StdReturn;
        }
        source = partner;
        keepFront = partner->Side.getValue() != 0;
        PartnerFrame.setValue(partnerFrame());
    }
    ToolFrame.setValue(toolFrame());

    Body* part = source->getFeatureBody();
    App::DocumentObject* baseObject = source->BaseFeature.getValue();
    if (!baseObject) {
        return new App::DocumentObjectExecReturn(
            label(part) + " has nothing before its Split to split",
            this
        );
    }
    // In this Body's frame: the new half's base is in the partner's Body (design 2.7)
    TopoShape base = getTopoShapeInLocalCoordinates(baseObject);
    if (base.isNull() || countSolids(base.getShape()) == 0) {
        return new App::DocumentObjectExecReturn(
            label(baseObject) + " has no solid to split",
            this
        );
    }

    App::DocumentObject* toolObject = source->Tool.getValue();
    const std::string sub = firstSub(source->Tool);
    if (!toolObject) {
        return new App::DocumentObjectExecReturn("The Split has no plane", this);
    }
    gp_Pln plane;
    try {
        plane = toolPlane(this, toolObject, sub);
    }
    catch (const Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what(), this);
    }
    // Never one half empty, silently: both Splits fail (design 2.7)
    if (!cuts(base.getShape(), plane)) {
        return new App::DocumentObjectExecReturn(
            planeLabel(toolObject, sub) + " doesn't cut " + label(part),
            this
        );
    }

    // A Common with the half-space, named by the boolean's history (the probe: valid and exact
    // with planes through vertices, along faces, across fillets and B-spline faces)
    const gp_Dir normal = plane.Axis().Direction();
    const gp_Pnt inside = plane.Location().Translated(gp_Vec(normal) * (keepFront ? 1.0 : -1.0));
    BRepBuilderAPI_MakeFace face(plane);
    BRepPrimAPI_MakeHalfSpace space(face.Face(), inside);
    TopoShape spaceShape = makeTopoShape(false);
    spaceShape.setShape(space.Solid());
    spaceShape.Tag = -getID();

    TopoShape result;
    try {
        result = makeResultShape(base).makeElementBoolean(
            Part::OpCodes::Common,
            {base, spaceShape},
            nullptr,
            FuzzyTolerance.getValue()
        );
    }
    catch (Standard_Failure& e) {
        FC_ERR("Split failed: " << e.GetMessageString());
        return new App::DocumentObjectExecReturn("Split: the boolean operation failed", this);
    }
    result = refineShapeIfActive(result);
    if (result.isNull() || countSolids(result.getShape()) == 0) {
        return new App::DocumentObjectExecReturn(
            planeLabel(toolObject, sub) + " doesn't cut " + label(part),
            this
        );
    }
    if (!isSingleSolidRuleSatisfied(result.getShape())) {
        return new App::DocumentObjectExecReturn(
            "Result has multiple solids: enable 'Allow Compound' in the active body.",
            this
        );
    }
    Shape.setValue(getSolid(result));
    return StdReturn;
}

gp_Pln Split::toolPlane(
    const Feature* owner,
    const App::DocumentObject* tool,
    const std::string& sub
)
{
    if (!tool) {
        throw Base::ValueError("The Split has no plane");
    }
    const Body* body = owner ? owner->getFeatureBody() : nullptr;
    // An origin or coordinate-system plane: placed by its coordinate system in its container
    if (auto element = freecad_cast<const App::Plane*>(tool)) {
        Base::Placement placement = App::GeoFeature::getGlobalPlacement(element);
        if (body) {
            placement = body->globalPlacement().inverse() * placement;
        }
        const Base::Vector3d pos = placement.getPosition();
        Base::Vector3d normal(0, 0, 1);
        placement.getRotation().multVec(normal, normal);
        return gp_Pln(gp_Pnt(pos.x, pos.y, pos.z), gp_Dir(normal.x, normal.y, normal.z));
    }
    // A datum plane, or a face of a solid
    if (!owner || !tool->isDerivedFrom<Part::Feature>()) {
        throw Base::ValueError(
            label(tool) + " isn't a plane: pick an origin plane, a datum plane or a planar face"
        );
    }
    TopoShape shape = owner->getTopoShapeInLocalCoordinates(tool);
    TopoDS_Shape picked;
    if (!sub.empty()) {
        picked = shape.getSubShape(sub.c_str(), /*silent=*/true);
    }
    else if (shape.countSubShapes(TopAbs_FACE) == 1 && shape.countSubShapes(TopAbs_SOLID) == 0) {
        picked = shape.getSubShape(TopAbs_FACE, 1);
    }
    if (picked.IsNull() || picked.ShapeType() != TopAbs_FACE) {
        throw Base::ValueError(
            planeLabel(tool, sub)
            + " isn't a plane: pick an origin plane, a datum plane or a planar face"
        );
    }
    BRepAdaptor_Surface surface(TopoDS::Face(picked));
    if (surface.GetType() != GeomAbs_Plane) {
        throw Base::ValueError(planeLabel(tool, sub) + " isn't planar");
    }
    gp_Pln plane = surface.Plane();
    // Out of the face: a reversed face's outside is against its surface's normal
    if (picked.Orientation() == TopAbs_REVERSED) {
        plane.SetAxis(plane.Axis().Reversed());
    }
    return plane;
}

Body* Split::makeSplit(
    App::DocumentObject* obj,
    App::DocumentObject* tool,
    const std::vector<std::string>& subs,
    const char* side
)
{
    Body* body = freecad_cast<Body*>(obj);
    if (!body) {
        body = Body::findBodyOf(obj);
    }
    if (!body) {
        throw Base::ValueError("Split: " + label(obj) + " isn't a part");
    }
    if (Boolean* merge = Boolean::mergeOf(body)) {
        throw Base::ValueError(
            "Split: " + label(body) + " is merged into " + label(Body::findBodyOf(merge))
            + "; split that part"
        );
    }
    // A held feature would split a frozen shape (design 2.7, 2.3)
    if (body->isRolledBack()) {
        throw Base::ValueError("Split: Roll " + label(body) + " to the end first");
    }
    auto last = freecad_cast<Feature*>(body->lastSolidFeature());
    if (!last) {
        throw Base::ValueError("Split: " + label(body) + " has no solid to split");
    }
    if (!tool) {
        throw Base::ValueError("Split: no plane");
    }
    // A Body's face is its Tip's: the Split goes after the Tip, and a link to its own Body would
    // be a cycle. Here, so that Split Part and Python share it
    if (auto toolBody = freecad_cast<Body*>(tool)) {
        tool = toolBody->Tip.getValue();
        if (!tool) {
            throw Base::ValueError("Split: " + label(toolBody) + " has no face to cut by");
        }
    }
    if (!Part::BodyBase::isInOneStudio(last, tool)) {
        throw Base::ValueError(
            "Split: " + label(tool) + " isn't in " + label(body) + " or a part of its studio"
        );
    }
    const std::string sub = subs.empty() ? std::string() : subs.front();
    gp_Pln plane;
    try {
        plane = toolPlane(last, tool, sub);
    }
    catch (const Base::Exception& e) {
        throw Base::ValueError(std::string("Split: ") + e.what());
    }
    if (!cuts(last->Shape.getShape().getShape(), plane)) {
        throw Base::ValueError(
            "Split: " + planeLabel(tool, sub) + " doesn't cut " + label(body)
        );
    }
    const char* kept = side && *side ? side : SideEnums[0];
    if (std::strcmp(kept, SideEnums[0]) != 0 && std::strcmp(kept, SideEnums[1]) != 0) {
        throw Base::ValueError(std::string("Split: the side is Front or Back, not ") + kept);
    }

    App::Document* doc = body->getDocument();
    auto split = static_cast<Split*>(doc->addObject("PartDesign::Split", "Split"));
    // After the Tip, as the new Tip
    body->addObject(split);
    split->Tool.setValue(tool, subs);
    split->Side.setValue(kept);

    auto part = static_cast<Body*>(doc->addObject("PartDesign::Body", "Body"));
    // "Shroud" again, made unique by the document: "Shroud001"
    part->Label.setValue(body->Label.getValue());
    // Where the old Body is, in its container, as New part places it (Body::newPartFrom)
    part->Placement.setValue(body->Placement.getValue());
    if (auto container = App::GeoFeatureGroupExtension::getGroupOfObject(body)) {
        if (auto group = container->getExtensionByType<App::GroupExtension>(true)) {
            group->addObject(part);
        }
    }
    auto half = static_cast<Split*>(doc->addObject("PartDesign::Split", "Split"));
    half->NewHalf.setValue(true);
    half->Partner.setValue(split);
    part->addObject(half);
    return part;
}

}  // namespace PartDesign
