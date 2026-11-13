// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                            *
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

#include <algorithm>
#include <cmath>
#include <numbers>
#include <vector>

#include <BRepAdaptor_Curve.hxx>
#include <BRep_Tool.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Circ.hxx>
#include <gp_Pnt.hxx>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/GroupExtension.h>
#include <Base/Exception.h>
#include <Base/Placement.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>
#include <Mod/Part/App/BodyBase.h>
#include <Mod/Part/App/DatumFeature.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Sketcher/App/GeoEnum.h>
#include <Mod/Sketcher/App/GeometryFacade.h>
#include <Mod/Sketcher/App/SketchObject.h>

#include "ModelSnap.h"
#include "Utils.h"
#include "ViewProviderSketch.h"

using namespace SketcherGui;

namespace
{

/// how far off the sketch plane a model element still counts as lying in it
constexpr double planeTolerance = 1e-6;

struct Candidate
{
    enum class Kind
    {
        Vertex,
        Segment,
        Arc
    };
    Kind kind = Kind::Vertex;
    App::DocumentObject* object = nullptr;
    std::string subName;
    Base::Vector2d a;       // the vertex; the segment's start
    Base::Vector2d b;       // the segment's end
    Base::Vector2d centre;  // the arc's
    double radius = 0.0;
    double first = 0.0;  // the arc runs counter-clockwise from first through span (radians)
    double span = 0.0;
};

struct SourceKey
{
    App::DocumentObject* object = nullptr;
    TopoDS_Shape shape;  // held so its TShape stays the one compared
    Base::Placement placement;
    Base::Placement frame;  // its container's, in the sketch's (externalFrame): a Body that moved
};

struct Cache
{
    const Sketcher::SketchObject* sketch = nullptr;
    Base::Placement sketchPlacement;
    std::vector<SourceKey> sources;
    std::vector<Candidate> candidates;
};

Cache& cache()
{
    static Cache instance;
    return instance;
}

Base::Vector3d toBase(const gp_Pnt& point)
{
    return Base::Vector3d(point.X(), point.Y(), point.Z());
}

/// the angle of v in [0, 2 pi)
double angleOf(const Base::Vector2d& v)
{
    double angle = std::atan2(v.y, v.x);
    if (angle < 0.0) {
        angle += 2.0 * std::numbers::pi;
    }
    return angle;
}

/// angle - from, in [0, 2 pi)
double sweep(double from, double angle)
{
    double delta = std::fmod(angle - from, 2.0 * std::numbers::pi);
    if (delta < 0.0) {
        delta += 2.0 * std::numbers::pi;
    }
    return delta;
}

/** the objects whose shapes the sketch snaps to: the support (without datums and the origin),
 * in a Body the solid feature before the sketch (the part as the sketch sees it, so a sketch on a
 * plane reaches the part's edges in that plane), and the other shown Bodies' Tips it may link.
 * All come before the sketch: a link to them makes no cycle. A Body's solid features are told by
 * their BaseFeature property (Sketcher can't link PartDesign).
 */
std::vector<App::DocumentObject*> snapSources(const Sketcher::SketchObject* sketch)
{
    std::vector<App::DocumentObject*> sources;
    auto take = [&sources, sketch](App::DocumentObject* object) {
        if (!object || object == sketch || !object->isDerivedFrom<Part::Feature>()
            || object->isDerivedFrom<Part::Datum>()) {
            return;
        }
        if (std::ranges::find(sources, object) == sources.end()) {
            sources.push_back(object);
        }
    };
    for (auto* object : sketch->AttachmentSupport.getValues()) {
        take(object);
    }

    auto* group = App::GeoFeatureGroupExtension::getGroupOfObject(sketch);
    auto* groupExtension = group ? group->getExtensionByType<App::GroupExtension>(true) : nullptr;
    if (groupExtension) {
        App::DocumentObject* previousSolid = nullptr;
        for (auto* object : groupExtension->Group.getValues()) {
            if (object == sketch) {
                break;
            }
            if (object && object->getPropertyByName("BaseFeature")
                && object->isDerivedFrom<Part::Feature>()
                && !object->isDerivedFrom<Part::Part2DObject>()) {
                previousSolid = object;
            }
        }
        auto* document = sketch->getDocument();
        if (previousSolid && document && sketch->isExternalAllowed(document, previousSolid)) {
            take(previousSolid);
        }
    }

    // FreeCAD-CH (ops#640, rank 18, second slice): the other parts of the sketch's studio, each
    // by its Body's Tip (the part as it is), when shown and when the sketch may link it:
    // isExternalAllowed() takes only a Body of the same studio and refuses a cycle, so a part
    // that depends on the sketch (made after it) is left out, as Onshape's sketch sees only the
    // parts made before it
    auto* ownBody = Part::BodyBase::findBodyOf(sketch);
    auto* document = sketch->getDocument();
    if (ownBody && document) {
        for (auto* object : document->getObjectsOfType(Part::BodyBase::getClassTypeId())) {
            auto* body = static_cast<Part::BodyBase*>(object);
            if (body == ownBody || !body->Visibility.getValue()) {
                continue;
            }
            App::DocumentObject* tip = body->Tip.getValue();
            if (tip && !tip->isDerivedFrom<Part::Part2DObject>()
                && sketch->isExternalAllowed(document, tip)) {
                take(tip);
            }
        }
    }
    return sources;
}

void addCandidates(const Sketcher::SketchObject* sketch,
                   App::DocumentObject* object,
                   const Part::TopoShape& shape,
                   std::vector<Candidate>& candidates)
{
    // read in the source's container, mapped into the sketch's (externalFrame, ops#331), then
    // into the sketch's own coordinates
    const Base::Placement toSketch =
        sketch->Placement.getValue().inverse() * sketch->externalFrame(object, std::string());
    auto mapPoint = [&toSketch](const gp_Pnt& point) {
        Base::Vector3d mapped;
        toSketch.multVec(toBase(point), mapped);
        return mapped;
    };
    auto inPlane = [](const Base::Vector3d& point) {
        return std::abs(point.z) < planeTolerance;
    };

    const auto vertexCount = static_cast<int>(shape.countSubShapes(TopAbs_VERTEX));
    for (int index = 1; index <= vertexCount; ++index) {
        const TopoDS_Shape vertex = shape.getSubShape(TopAbs_VERTEX, index, /*silent*/ true);
        if (vertex.IsNull()) {
            continue;
        }
        const Base::Vector3d point = mapPoint(BRep_Tool::Pnt(TopoDS::Vertex(vertex)));
        if (!inPlane(point)) {
            continue;
        }
        Candidate candidate;
        candidate.kind = Candidate::Kind::Vertex;
        candidate.object = object;
        candidate.subName = "Vertex" + std::to_string(index);
        candidate.a = Base::Vector2d(point.x, point.y);
        candidates.push_back(std::move(candidate));
    }

    const auto edgeCount = static_cast<int>(shape.countSubShapes(TopAbs_EDGE));
    for (int index = 1; index <= edgeCount; ++index) {
        const TopoDS_Shape edgeShape = shape.getSubShape(TopAbs_EDGE, index, /*silent*/ true);
        if (edgeShape.IsNull()) {
            continue;
        }
        const TopoDS_Edge& edge = TopoDS::Edge(edgeShape);
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        BRepAdaptor_Curve curve(edge);
        const double firstParameter = curve.FirstParameter();
        const double lastParameter = curve.LastParameter();
        const Base::Vector3d start = mapPoint(curve.Value(firstParameter));
        const Base::Vector3d end = mapPoint(curve.Value(lastParameter));
        const Base::Vector3d middle = mapPoint(curve.Value((firstParameter + lastParameter) / 2.0));
        if (!inPlane(start) || !inPlane(end) || !inPlane(middle)) {
            continue;
        }

        Candidate candidate;
        candidate.object = object;
        candidate.subName = "Edge" + std::to_string(index);
        if (curve.GetType() == GeomAbs_Line) {
            candidate.kind = Candidate::Kind::Segment;
            candidate.a = Base::Vector2d(start.x, start.y);
            candidate.b = Base::Vector2d(end.x, end.y);
            if ((candidate.b - candidate.a).Length() < Precision::Confusion()) {
                continue;
            }
        }
        else if (curve.GetType() == GeomAbs_Circle) {
            const gp_Circ circle = curve.Circle();
            const Base::Vector3d centre = mapPoint(circle.Location());
            candidate.kind = Candidate::Kind::Arc;
            candidate.centre = Base::Vector2d(centre.x, centre.y);
            candidate.radius = circle.Radius();
            const Base::Vector2d startOffset = Base::Vector2d(start.x, start.y) - candidate.centre;
            const Base::Vector2d endOffset = Base::Vector2d(end.x, end.y) - candidate.centre;
            const Base::Vector2d middleOffset =
                Base::Vector2d(middle.x, middle.y) - candidate.centre;
            const bool closed = (lastParameter - firstParameter)
                >= 2.0 * std::numbers::pi - Precision::Angular();
            if (closed) {
                candidate.first = 0.0;
                candidate.span = 2.0 * std::numbers::pi;
            }
            else {
                const double startAngle = angleOf(startOffset);
                const double toEnd = sweep(startAngle, angleOf(endOffset));
                const double toMiddle = sweep(startAngle, angleOf(middleOffset));
                if (toMiddle <= toEnd) {
                    candidate.first = startAngle;
                    candidate.span = toEnd;
                }
                else {
                    // the edge runs clockwise in the sketch: the same arc counter-clockwise from
                    // its end
                    candidate.first = angleOf(endOffset);
                    candidate.span = 2.0 * std::numbers::pi - toEnd;
                }
            }
        }
        else {
            continue;  // first slice: lines and circles only
        }
        candidates.push_back(std::move(candidate));
    }
}

const std::vector<Candidate>& candidatesOf(const Sketcher::SketchObject* sketch)
{
    Cache& current = cache();

    std::vector<SourceKey> sources;
    for (auto* object : snapSources(sketch)) {
        Part::TopoShape shape;
        try {
            shape = Part::Feature::getTopoShape(
                object,
                Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform);
        }
        catch (const Base::Exception&) {
            continue;
        }
        catch (const Standard_Failure&) {
            continue;
        }
        if (shape.isNull()) {
            continue;
        }
        sources.push_back({object,
                           shape.getShape(),
                           shape.getPlacement(),
                           sketch->externalFrame(object, std::string())});
    }

    const Base::Placement sketchPlacement = sketch->Placement.getValue();
    auto sameSources = [&]() {
        if (current.sources.size() != sources.size()) {
            return false;
        }
        for (size_t index = 0; index < sources.size(); ++index) {
            const SourceKey& was = current.sources[index];
            const SourceKey& now = sources[index];
            if (was.object != now.object || was.shape.TShape() != now.shape.TShape()
                || !was.placement.isSame(now.placement, Precision::Confusion())
                || !was.frame.isSame(now.frame, Precision::Confusion())) {
                return false;
            }
        }
        return true;
    };
    if (current.sketch == sketch
        && current.sketchPlacement.isSame(sketchPlacement, Precision::Confusion())
        && sameSources()) {
        return current.candidates;
    }

    current.sketch = sketch;
    current.sketchPlacement = sketchPlacement;
    current.candidates.clear();
    for (const auto& source : sources) {
        try {
            Part::TopoShape shape(source.shape);
            addCandidates(sketch, source.object, shape, current.candidates);
        }
        catch (const Base::Exception&) {
        }
        catch (const Standard_Failure&) {
        }
    }
    current.sources = std::move(sources);
    return current.candidates;
}

/// the GeoId of the one external geometry the link to object's subName gives (as
/// CommandConstraints' findExternalReference); linked tells whether there is a link at all
int findLink(const Sketcher::SketchObject* sketch,
             const App::DocumentObject* object,
             const std::string& subName,
             bool& linked)
{
    linked = false;
    const auto objects = sketch->ExternalGeometry.getValues();
    const auto subNames = sketch->ExternalGeometry.getSubValues();
    for (size_t index = 0; index < objects.size() && index < subNames.size(); ++index) {
        if (objects[index] != object || subNames[index] != subName) {
            continue;
        }
        linked = true;
        std::vector<int> geoIds;
        const auto& geos = sketch->getExternalGeometry();
        for (long id : sketch->externalGeometryIds(static_cast<int>(index))) {
            for (size_t geo = 0; geo < geos.size(); ++geo) {
                if (Sketcher::GeometryFacade::getId(geos[geo]) == id) {
                    geoIds.push_back(-1 - static_cast<int>(geo));  // ExternalGeo[k] is -1 - k
                    break;
                }
            }
        }
        return geoIds.size() == 1 ? geoIds.front() : Sketcher::GeoEnum::GeoUndef;
    }
    return Sketcher::GeoEnum::GeoUndef;
}

}  // namespace

std::optional<ModelSnapHit> SketcherGui::findModelSnap(const Sketcher::SketchObject* sketch,
                                                       const Base::Vector2d& pos,
                                                       double tolerance)
{
    if (!sketch || tolerance <= 0.0) {
        return std::nullopt;
    }

    const std::vector<Candidate>& candidates = candidatesOf(sketch);

    // A vertex first, as Onshape wakes the corner over the edges meeting there
    const Candidate* nearestVertex = nullptr;
    double vertexDistance = tolerance;
    for (const auto& candidate : candidates) {
        if (candidate.kind != Candidate::Kind::Vertex) {
            continue;
        }
        const double distance = (candidate.a - pos).Length();
        if (distance <= vertexDistance) {
            vertexDistance = distance;
            nearestVertex = &candidate;
        }
    }
    if (nearestVertex) {
        return ModelSnapHit {nearestVertex->object, nearestVertex->subName, true, nearestVertex->a};
    }

    const Candidate* nearestEdge = nullptr;
    double edgeDistance = tolerance;
    Base::Vector2d edgePoint;
    for (const auto& candidate : candidates) {
        Base::Vector2d closest;
        if (candidate.kind == Candidate::Kind::Segment) {
            const Base::Vector2d direction = candidate.b - candidate.a;
            double t = ((pos - candidate.a) * direction) / direction.Sqr();
            t = std::clamp(t, 0.0, 1.0);
            closest = candidate.a + direction * t;
        }
        else if (candidate.kind == Candidate::Kind::Arc) {
            const Base::Vector2d offset = pos - candidate.centre;
            if (offset.Length() < Precision::Confusion()) {
                continue;
            }
            if (sweep(candidate.first, angleOf(offset)) > candidate.span + Precision::Angular()) {
                continue;  // off the arc's extent
            }
            closest = candidate.centre + offset * (candidate.radius / offset.Length());
        }
        else {
            continue;
        }
        const double distance = (closest - pos).Length();
        if (distance <= edgeDistance) {
            edgeDistance = distance;
            nearestEdge = &candidate;
            edgePoint = closest;
        }
    }
    if (!nearestEdge) {
        return std::nullopt;
    }
    ModelSnapHit hit {nearestEdge->object, nearestEdge->subName, false, edgePoint};
    hit.isArc = nearestEdge->kind == Candidate::Kind::Arc;
    // SQ2: the edge's middle wins along the edge within a wider radius than the edge across it
    // (Onshape: about 8 px against 5). A whole circle has no middle
    std::optional<Base::Vector2d> middle;
    if (nearestEdge->kind == Candidate::Kind::Segment) {
        middle = (nearestEdge->a + nearestEdge->b) / 2.0;
    }
    else if (nearestEdge->span < 2.0 * std::numbers::pi - Precision::Angular()) {
        const double angle = nearestEdge->first + nearestEdge->span / 2.0;
        middle = nearestEdge->centre
            + Base::Vector2d(std::cos(angle), std::sin(angle)) * nearestEdge->radius;
    }
    if (middle && (edgePoint - *middle).Length() <= tolerance * modelMidpointRadius) {
        hit.position = *middle;
        hit.isMidpoint = true;
    }
    return hit;
}

double SketcherGui::modelSnapTolerance(const ViewProviderSketch& viewProvider)
{
    if (!viewProvider.isInEditMode()) {
        return 0.0;
    }
    // getScaleFactor is the world size of a thirtieth of the view's height; the sketch picks
    // within about five pixels, a sixth of that on a view about 900 pixels high
    return viewProvider.getScaleFactor() / 6.0;
}

int SketcherGui::linkModelSnap(Sketcher::SketchObject* sketch,
                               App::DocumentObject* object,
                               const std::string& subName)
{
    if (!sketch || !object || subName.empty()) {
        return Sketcher::GeoEnum::GeoUndef;
    }
    bool linked = false;
    const int existing = findLink(sketch, object, subName, linked);
    if (linked) {
        return existing;  // GeoUndef when the link gives none or several: no constraint to it
    }

    if (!Gui::Command::hasPendingCommand()) {
        // renamed by the autoconstraints' own command, so link and constraint are one undo step
        Gui::Command::openActiveDocumentCommand(
            App::TransactionName {.name = QT_TRANSLATE_NOOP("Command", "Add external geometry"),
                                  .temporary = true});
    }

    const int links = sketch->ExternalGeometry.getSize();
    try {
        // implicit: the link goes with its last constraint, as in Onshape, where nothing is
        // projected (ops#634's addProjectedExternalReference)
        Gui::cmdAppObjectArgs(sketch,
                              "addExternal(\"%s\",\"%s\", False, False, True)",
                              object->getNameInDocument(),
                              subName.c_str());
        tryAutoRecomputeIfNotSolve(sketch);
    }
    catch (const Base::Exception&) {
        return Sketcher::GeoEnum::GeoUndef;
    }
    if (sketch->ExternalGeometry.getSize() <= links) {
        return Sketcher::GeoEnum::GeoUndef;
    }
    const int geoId = findLink(sketch, object, subName, linked);
    if (geoId == Sketcher::GeoEnum::GeoUndef && linked) {
        // a link that gives no single geometry is not kept for a constraint it can't take (as
        // CommandConstraints' materializeExternalReference)
        std::vector<int> geoIds;
        const auto& geos = sketch->getExternalGeometry();
        for (long id : sketch->externalGeometryIds(links)) {
            for (size_t geo = 0; geo < geos.size(); ++geo) {
                if (Sketcher::GeometryFacade::getId(geos[geo]) == id) {
                    geoIds.push_back(-1 - static_cast<int>(geo));
                    break;
                }
            }
        }
        if (!geoIds.empty()) {
            sketch->delExternal(geoIds);
        }
    }
    return geoId;
}
