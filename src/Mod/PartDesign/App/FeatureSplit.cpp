// SPDX-License-Identifier: LGPL-2.1-or-later

// Split (FreeCAD-CH ops#325, B+ Stage 1 session 4, notes/bplus-stage1-design.md 2.7)

#include <algorithm>
#include <cmath>
#include <cstring>

#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepGProp.hxx>
#include <BRepPrimAPI_MakeHalfSpace.hxx>
#include <BRepTools.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <Geom_Surface.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_DataMapOfShapeShape.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Ax3.hxx>
#include <gp_Pnt2d.hxx>
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

// FreeCAD-CH (ops#919, notes/surface-upto-split-919.md 5): a Split by a sheet

/// Whether @p shape cuts as a sheet, not as a plane: no solid, and several faces or one that
/// isn't planar. One planar face is a plane, extended (toolPlane, Onshape's SU9)
bool isSheetShape(const TopoShape& shape)
{
    if (shape.isNull() || shape.countSubShapes(TopAbs_SOLID) > 0) {
        return false;
    }
    const auto faces = shape.countSubShapes(TopAbs_FACE);
    if (faces > 1) {
        return true;
    }
    if (faces == 1) {
        BRepAdaptor_Surface surface(TopoDS::Face(shape.getSubShape(TopAbs_FACE, 1)));
        return surface.GetType() != GeomAbs_Plane;
    }
    return false;
}

/// A sheet a Split takes: one shell (or one face), every edge between two of its faces met by
/// them from opposite sides, so that its faces' normals agree on its Front
void checkSheet(const TopoDS_Shape& sheet, const std::string& name)
{
    TopTools_IndexedMapOfShape shells;
    TopExp::MapShapes(sheet, TopAbs_SHELL, shells);
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(sheet, TopAbs_FACE, faces);
    if (shells.Extent() > 1) {
        throw Base::ValueError(
            name + " is " + std::to_string(shells.Extent()) + " sheets: a Split takes one"
        );
    }
    if (shells.Extent() == 0) {
        if (faces.Extent() > 1) {
            throw Base::ValueError(name + " is separate faces: a Split takes one sheet");
        }
        return;
    }
    TopTools_IndexedMapOfShape shellFaces;
    TopExp::MapShapes(shells(1), TopAbs_FACE, shellFaces);
    if (shellFaces.Extent() != faces.Extent()) {
        throw Base::ValueError(name + " is a sheet and separate faces: a Split takes one sheet");
    }
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndUniqueAncestors(shells(1), TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    for (int i = 1; i <= edgeFaces.Extent(); ++i) {
        const TopTools_ListOfShape& owners = edgeFaces(i);
        if (owners.Extent() > 2) {
            throw Base::ValueError(name + " branches: more than two of its faces meet at an edge");
        }
        if (owners.Extent() != 2) {
            continue;
        }
        // The edge as each face runs it: opposite in a consistently oriented sheet
        auto orientationIn = [&](const TopoDS_Shape& face) {
            for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
                if (it.Current().IsSame(edgeFaces.FindKey(i))) {
                    return it.Current().Orientation();
                }
            }
            return TopAbs_EXTERNAL;
        };
        if (orientationIn(owners.First()) == orientationIn(owners.Last())) {
            throw Base::ValueError(name + " isn't oriented: its faces don't agree on a side");
        }
    }
}

/// How many loops the free edges of @p sheet make: the edges of one face only, seams aside
int freeLoops(const TopoDS_Shape& sheet)
{
    TopTools_IndexedDataMapOfShapeListOfShape edgeFaces;
    TopExp::MapShapesAndUniqueAncestors(sheet, TopAbs_EDGE, TopAbs_FACE, edgeFaces);
    std::vector<TopoDS_Edge> free;
    for (int i = 1; i <= edgeFaces.Extent(); ++i) {
        const TopoDS_Edge& edge = TopoDS::Edge(edgeFaces.FindKey(i));
        const TopTools_ListOfShape& owners = edgeFaces(i);
        if (owners.Extent() != 1 || BRep_Tool::Degenerated(edge)
            || BRep_Tool::IsClosed(edge, TopoDS::Face(owners.First()))) {
            continue;
        }
        free.push_back(edge);
    }
    // Loops by shared end points: each edge starts its own group, joined through its vertices
    std::vector<int> group(free.size());
    for (std::size_t i = 0; i < free.size(); ++i) {
        group[i] = static_cast<int>(i);
    }
    auto root = [&group](int i) {
        while (group[i] != i) {
            i = group[i] = group[group[i]];
        }
        return i;
    };
    std::vector<std::pair<gp_Pnt, int>> ends;
    for (std::size_t i = 0; i < free.size(); ++i) {
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopExp::Vertices(free[i], first, last);
        for (const TopoDS_Vertex& vertex : {first, last}) {
            if (vertex.IsNull()) {
                continue;
            }
            const gp_Pnt point = BRep_Tool::Pnt(vertex);
            for (const auto& [other, j] : ends) {
                if (point.Distance(other) <= Precision::Confusion()) {
                    group[root(static_cast<int>(i))] = root(j);
                }
            }
            ends.emplace_back(point, static_cast<int>(i));
        }
    }
    int loops = 0;
    for (std::size_t i = 0; i < free.size(); ++i) {
        loops += root(static_cast<int>(i)) == static_cast<int>(i) ? 1 : 0;
    }
    return loops;
}

/// A point inside @p face, as surface parameters; false when none is found
bool pointInside(const TopoDS_Face& face, double& u, double& v)
{
    double u1, u2, v1, v2;
    BRepTools::UVBounds(face, u1, u2, v1, v2);
    const double tol = BRep_Tool::Tolerance(face);
    constexpr int steps = 8;
    // The middle first, then a grid
    for (int k = -1; k < (steps - 1) * (steps - 1); ++k) {
        const double fu = k < 0 ? 0.5 : (1 + k % (steps - 1)) / double(steps);
        const double fv = k < 0 ? 0.5 : (1 + k / (steps - 1)) / double(steps);
        u = u1 + fu * (u2 - u1);
        v = v1 + fv * (v2 - v1);
        BRepClass_FaceClassifier classifier(face, gp_Pnt2d(u, v), tol);
        if (classifier.State() == TopAbs_IN) {
            return true;
        }
    }
    return false;
}

/// The normal of @p face at (@p u, @p v), out of the face as oriented; @p point is set there
gp_Vec faceNormal(const TopoDS_Face& face, double u, double v, gp_Pnt& point)
{
    Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    gp_Vec du;
    gp_Vec dv;
    surface->D1(u, v, point, du, dv);
    gp_Vec normal = du.Crossed(dv);
    if (face.Orientation() == TopAbs_REVERSED) {
        normal.Reverse();
    }
    return normal;
}

/// @p base divided by @p sheet, the piece on the kept side, named through the cut. Throws, with
/// the reason, unless the sheet divides the base into exactly two solids, one on each side of
/// it, whose volumes add up to the base's. The sheet is not extended (Onshape: SU6 to SU8)
TopoShape splitBySheet(
    TopoShape named,
    const TopoShape& base,
    const TopoShape& sheet,
    double fuzzy,
    bool keepFront,
    const std::string& sheetName,
    const std::string& partName
)
{
    checkSheet(sheet.getShape(), sheetName);
    BRepAlgoAPI_Splitter splitter;
    TopTools_ListOfShape arguments;
    arguments.Append(base.getShape());
    TopTools_ListOfShape tools;
    tools.Append(sheet.getShape());
    splitter.SetArguments(arguments);
    splitter.SetTools(tools);
    if (fuzzy > 0.0) {
        splitter.SetFuzzyValue(fuzzy);
    }
    splitter.SetNonDestructive(Standard_True);
    splitter.Build();
    if (!splitter.IsDone()) {
        throw Base::ValueError("Split: the cut by " + sheetName + " failed");
    }
    TopTools_IndexedMapOfShape solids;
    TopExp::MapShapes(splitter.Shape(), TopAbs_SOLID, solids);
    const std::string noCut = sheetName + " doesn't cut " + partName;
    if (solids.Extent() < 2) {
        throw Base::ValueError(noCut);
    }
    if (solids.Extent() > 2) {
        throw Base::ValueError(
            sheetName + " cuts " + partName + " into " + std::to_string(solids.Extent())
            + " pieces; a split into more than two parts is not supported"
        );
    }
    // A sheet whose free edges make one loop (a disc: an open chain's sheet, one face) has no
    // inside: which part keeps which piece would follow the way its edges were drawn, which a
    // move, a redraw or a copy can turn silently (ops#919, reviews r2 and r3). Refused until a
    // Split chooses its piece by something that holds through those (the coordinator's ruling)
    if (freeLoops(sheet.getShape()) == 1) {
        throw Base::ValueError(
            sheetName + " is an open sheet (its free edges make one loop): a Split by it is not "
            "supported yet; a closed tube, or a sheet of one planar face, is"
        );
    }
    // Each piece of a sheet face, to that face as the sheet runs it
    TopTools_DataMapOfShapeShape sheetFaceOf;
    for (TopExp_Explorer it(sheet.getShape(), TopAbs_FACE); it.More(); it.Next()) {
        const TopTools_ListOfShape& images = splitter.Modified(it.Current());
        if (images.IsEmpty()) {
            sheetFaceOf.Bind(it.Current(), it.Current());
        }
        for (const auto& image : images) {
            sheetFaceOf.Bind(image, it.Current());
        }
    }
    // A piece is Front where the sheet's normals point into it: on every face it has on the
    // sheet, its outward normal is against the sheet's
    const std::string noDivide = sheetName + " doesn't divide " + partName;
    int frontIndex = 0;
    int backIndex = 0;
    double volume = 0.0;
    for (int i = 1; i <= solids.Extent(); ++i) {
        int front = 0;
        int back = 0;
        for (TopExp_Explorer it(solids(i), TopAbs_FACE); it.More(); it.Next()) {
            if (!sheetFaceOf.IsBound(it.Current())) {
                continue;
            }
            const TopoDS_Face piece = TopoDS::Face(it.Current());
            const TopoDS_Face of = TopoDS::Face(sheetFaceOf.Find(it.Current()));
            double u, v;
            if (!pointInside(piece, u, v)) {
                continue;
            }
            gp_Pnt point;
            const gp_Vec out = faceNormal(piece, u, v, point);
            GeomAPI_ProjectPointOnSurf onSheet(point, BRep_Tool::Surface(of));
            if (onSheet.NbPoints() == 0) {
                continue;
            }
            double us, vs;
            onSheet.LowerDistanceParameters(us, vs);
            gp_Pnt sheetPoint;
            const double dot = out.Dot(faceNormal(of, us, vs, sheetPoint));
            if (dot < 0.0) {
                ++front;
            }
            else if (dot > 0.0) {
                ++back;
            }
        }
        // On both sides of the sheet, or touching it nowhere: the sheet does not divide
        if ((front > 0) == (back > 0)) {
            throw Base::ValueError(noDivide);
        }
        (front > 0 ? frontIndex : backIndex) = i;
        GProp_GProps props;
        BRepGProp::VolumeProperties(solids(i), props);
        volume += props.Mass();
    }
    if (frontIndex == 0 || backIndex == 0) {
        throw Base::ValueError(noDivide);
    }
    GProp_GProps whole;
    BRepGProp::VolumeProperties(base.getShape(), whole);
    if (std::fabs(volume - whole.Mass()) > 1e-6 * std::max(1.0, std::fabs(whole.Mass()))) {
        throw Base::ValueError(noDivide);
    }
    named.makeElementShape(splitter, {base, sheet}, Part::OpCodes::Split);
    return named.getSubTopoShape(TopAbs_SOLID, keepFront ? frontIndex : backIndex);
}
}  // namespace

bool Split::isSheetObject(const App::DocumentObject* tool)
{
    auto feature = freecad_cast<const Part::Feature*>(tool);
    if (!feature || Body::findBodyOf(tool)) {
        return false;
    }
    const TopoDS_Shape& shape = feature->Shape.getShape().getShape();
    return !shape.IsNull() && countSolids(shape) == 0 && TopExp_Explorer(shape, TopAbs_FACE).More();
}

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
    ADD_PROPERTY_TYPE(
        KeepTool,
        (false),
        "Split",
        App::Prop_None,
        "A sheet as the tool stays shown; off, the Split hides it (shown again when the Split is "
        "deleted)"
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
        KeepTool.setStatus(App::Property::Hidden, newHalf);
    }
    // Keep tools turned on or off by hand shows or hides a sheet tool (ops#919)
    if (prop == &KeepTool && !isRestoring() && !NewHalf.getValue() && getDocument()
        && !getDocument()->isPerformingTransaction()) {
        App::DocumentObject* tool = Tool.getValue();
        if (tool && Tool.getSubValues().empty() && isSheetObject(tool)) {
            tool->Visibility.setValue(KeepTool.getValue());
        }
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
    // FreeCAD-CH (ops#919): a sheet of several faces, or of one curved face, cuts as it is
    if (sub.empty() && toolObject->isDerivedFrom<Part::Feature>()) {
        const TopoShape sheet = getTopoShapeInLocalCoordinates(toolObject);
        if (isSheetShape(sheet)) {
            TopoShape result;
            try {
                result = splitBySheet(
                    makeResultShape(base),
                    base,
                    sheet,
                    FuzzyTolerance.getValue(),
                    keepFront,
                    label(toolObject),
                    label(part)
                );
            }
            catch (const Base::Exception& e) {
                return new App::DocumentObjectExecReturn(e.what(), this);
            }
            catch (Standard_Failure& e) {
                FC_ERR("Split failed: " << e.GetMessageString());
                return new App::DocumentObjectExecReturn(
                    "Split: the cut by " + label(toolObject) + " failed",
                    this
                );
            }
            result = refineShapeIfActive(result);
            if (result.isNull() || countSolids(result.getShape()) == 0) {
                return new App::DocumentObjectExecReturn(
                    label(toolObject) + " doesn't cut " + label(part),
                    this
                );
            }
            Shape.setValue(getSolid(result));
            return StdReturn;
        }
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

void Split::unsetupObject()
{
    // A sheet this Split hid comes back into view (ops#919)
    App::DocumentObject* tool = Tool.getValue();
    if (!NewHalf.getValue() && !KeepTool.getValue() && tool && !tool->isRemoving()
        && Tool.getSubValues().empty() && isSheetObject(tool)) {
        tool->Visibility.setValue(true);
    }
    FeatureRefine::unsetupObject();
}

Body* Split::makeSplit(
    App::DocumentObject* obj,
    App::DocumentObject* tool,
    const std::vector<std::string>& subs,
    const char* side,
    bool keepTool
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
    // FreeCAD-CH (ops#919): a sheet in no Body (a surface made beside the parts) is admitted;
    // one planar face then cuts as its whole plane, any other sheet as it is
    const bool sheetObject = subs.empty() && isSheetObject(tool);
    if (sheetObject) {
        if (tool->getDocument() != body->getDocument()) {
            throw Base::ValueError(
                "Split: " + label(tool) + " isn't in " + label(body) + "'s document"
            );
        }
        // The Split goes after the Tip: a sheet that depends on the Body itself is a cycle
        const std::vector<App::DocumentObject*> needs = tool->getOutListRecursive();
        if (std::find(needs.begin(), needs.end(), body) != needs.end()) {
            throw Base::ValueError(
                "Split: " + label(tool) + " depends on " + label(body)
                + " itself; link it to a feature of " + label(body)
            );
        }
    }
    else if (!Part::BodyBase::isInOneStudio(last, tool)) {
        throw Base::ValueError(
            "Split: " + label(tool) + " isn't in " + label(body) + " or a part of its studio"
        );
    }
    const std::string sub = subs.empty() ? std::string() : subs.front();
    const TopoShape sheet = sheetObject ? last->getTopoShapeInLocalCoordinates(tool) : TopoShape();
    if (sheetObject && isSheetShape(sheet)) {
        try {
            splitBySheet(
                TopoShape(),
                last->Shape.getShape(),
                sheet,
                0.0,
                true,
                label(tool),
                label(body)
            );
        }
        catch (const Base::Exception& e) {
            throw Base::ValueError(std::string("Split: ") + e.what());
        }
        catch (Standard_Failure& e) {
            throw Base::ValueError("Split: the cut by " + label(tool) + " failed");
        }
    }
    else {
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
    split->KeepTool.setValue(keepTool);
    // Onshape consumes a sheet tool unless Keep tools: here it is hidden, and shown again when
    // the Split is deleted (unsetupObject)
    if (sheetObject && !keepTool) {
        tool->Visibility.setValue(false);
    }

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
