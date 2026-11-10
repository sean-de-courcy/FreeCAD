// SPDX-License-Identifier: LGPL-2.1-or-later

// Onshape's imprint for a sketch's regions (FreeCAD-CH, feat/profile-regions): see SketchImprint.h

#include <cmath>
#include <set>
#include <vector>

#include <BRep_Tool.hxx>
#include <BRepBndLib.hxx>
#include <Bnd_Box.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>

#include <App/Datums.h>
#include <Base/Console.h>
#include <Base/Placement.h>
#include <Mod/Part/App/DatumFeature.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/PartFeature.h>

#include "SketchImprint.h"
#include "SketchObject.h"

FC_LOG_LEVEL_INIT("Sketch", true, true)

namespace
{

// An edge lies in the plane when it does within OCCT's confusion: the support's own planar faces
// are that exact, and an edge only near the plane would make faces off their surface
constexpr double inPlane = Precision::Confusion();

bool liesInPlane(const TopoDS_Edge& edge, const gp_Trsf& toLocal)
{
    if (BRep_Tool::Degenerated(edge)) {
        return false;
    }
    TopoDS_Vertex first;
    TopoDS_Vertex last;
    TopExp::Vertices(edge, first, last);
    for (const auto& v : {first, last}) {
        if (v.IsNull()) {
            return false;
        }
        if (std::abs(BRep_Tool::Pnt(v).Transformed(toLocal).Z()) > inPlane) {
            return false;
        }
    }
    Bnd_Box box;
    BRepBndLib::AddOptimal(edge.Moved(TopLoc_Location(toLocal)), box, false, false);
    if (box.IsVoid()) {
        return false;
    }
    double x0 {}, y0 {}, z0 {}, x1 {}, y1 {}, z1 {};
    box.Get(x0, y0, z0, x1, y1, z1);
    return std::abs(z0) <= inPlane && std::abs(z1) <= inPlane;
}

bool imprints(const App::DocumentObject* obj)
{
    // Model geometry only: a datum's or an origin's face is a construction plane, and another
    // sketch is no model (Onshape imprints parts and surfaces)
    return obj && obj->isDerivedFrom<Part::Feature>() && !obj->isDerivedFrom<Part::Datum>()
        && !obj->isDerivedFrom<Part::Part2DObject>() && !obj->isDerivedFrom<App::DatumElement>();
}

}  // namespace

Part::TopoShape Sketcher::imprintEdges(const SketchObject& sketch)
{
    if (sketch._InternalFaceVersion.getValue() < ImprintInternalFaceVersion
        || !sketch.MakeInternals.getValue()) {
        return {};
    }
    std::vector<Part::TopoShape> edges;
    std::set<const App::DocumentObject*> seen;
    const Base::Placement invPlm = sketch.Placement.getValue().inverse();
    for (const auto* obj : sketch.AttachmentSupport.getValues()) {
        if (!imprints(obj) || !seen.insert(obj).second) {
            continue;
        }
        try {
            auto shape = Part::Feature::getTopoShape(
                obj,
                Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform
            );
            if (shape.isNull()) {
                continue;
            }
            // The support's shape is in its own container; the sketch's coordinates are its
            // placement in its container (as external geometry, ops#331)
            const Base::Matrix4D toLocal = (invPlm * sketch.externalFrame(obj, "")).toMatrix();
            const gp_Trsf trsf = Part::TopoShape::convert(toLocal);
            TopTools_IndexedDataMapOfShapeListOfShape faceEdges;
            TopExp::MapShapesAndAncestors(shape.getShape(), TopAbs_EDGE, TopAbs_FACE, faceEdges);
            for (int i = 1; i <= faceEdges.Extent(); ++i) {
                if (faceEdges(i).IsEmpty()) {
                    continue;  // a free edge is no face's boundary
                }
                const TopoDS_Edge& edge = TopoDS::Edge(faceEdges.FindKey(i));
                if (!liesInPlane(edge, trsf)) {
                    continue;
                }
                const int index = shape.findShape(edge);
                if (index <= 0) {
                    continue;
                }
                // A copy: the regions' face maker adds curves to its edges, which must not
                // touch the model's (ops#316)
                edges.push_back(shape.getSubTopoShape(TopAbs_EDGE, index).makeElementTransform(
                    toLocal,
                    nullptr,
                    Part::CheckScale::noScaleCheck,
                    Part::CopyType::copy
                ));
            }
        }
        catch (const Base::Exception& e) {
            FC_WARN(sketch.getFullName() << ": no imprint from " << obj->getFullName() << ": "
                                         << e.what());
        }
        catch (const Standard_Failure& e) {
            FC_WARN(sketch.getFullName() << ": no imprint from " << obj->getFullName() << ": "
                                         << e.GetMessageString());
        }
    }
    if (edges.empty()) {
        return {};
    }
    return sketch.makeTopoShape().makeElementCompound(edges);
}
