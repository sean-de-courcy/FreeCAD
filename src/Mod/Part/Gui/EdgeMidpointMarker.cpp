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

#include <QMouseEvent>

#include <BRepAdaptor_Curve.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>

#include <Inventor/SbVec2s.h>
#include <Inventor/nodes/SoBaseColor.h>
#include <Inventor/nodes/SoCoordinate3.h>
#include <Inventor/nodes/SoMarkerSet.h>
#include <Inventor/nodes/SoPickStyle.h>
#include <Inventor/nodes/SoSeparator.h>
#include <Inventor/nodes/SoSwitch.h>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <Base/Console.h>
#include <Gui/Application.h>
#include <Gui/Document.h>
#include <Gui/Inventor/MarkerBitmaps.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/Part/App/PartFeature.h>

#include "EdgeMidpointMarker.h"

using namespace PartGui;

EdgeMidpointMarker* EdgeMidpointMarker::instance = nullptr;  // NOLINT

void EdgeMidpointMarker::create()
{
    if (!instance) {
        instance = new EdgeMidpointMarker();
    }
}

void EdgeMidpointMarker::destruct()
{
    delete instance;
    instance = nullptr;
}

EdgeMidpointMarker::EdgeMidpointMarker()
    : QObject(nullptr)
    , Gui::SelectionObserver(true, Gui::ResolveMode::NoResolve)
{
    marker = new SoSwitch();
    marker->ref();
    marker->setName("EdgeMidpointMarker");
    marker->whichChild = SO_SWITCH_NONE;

    auto* root = new SoSeparator();
    auto* pickStyle = new SoPickStyle();
    pickStyle->style = SoPickStyle::UNPICKABLE;
    root->addChild(pickStyle);
    // Onshape's hover orange (PL4a: #FFC685)
    auto* color = new SoBaseColor();
    color->rgb.setValue(1.0F, 198.0F / 255.0F, 133.0F / 255.0F);
    root->addChild(color);
    coordinate = new SoCoordinate3();
    coordinate->setName("EdgeMidpointMarkerPoint");
    coordinate->point.setNum(1);
    root->addChild(coordinate);
    auto* points = new SoMarkerSet();
    points->markerIndex = Gui::Inventor::MarkerBitmaps::getMarkerIndex("SQUARE_FILLED", 9);
    root->addChild(points);
    marker->addChild(root);
}

EdgeMidpointMarker::~EdgeMidpointMarker()
{
    detach();
    marker->unref();
}

std::optional<Base::Vector3d> EdgeMidpointMarker::middleOf(const TopoDS_Edge& edge)
{
    if (edge.IsNull()) {
        return std::nullopt;
    }
    try {
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopExp::Vertices(edge, first, last);
        if (first.IsNull() || last.IsNull() || first.IsSame(last)) {
            return std::nullopt;  // a closed edge (SP10-Q11: a full circle has no midpoint)
        }
        BRepAdaptor_Curve curve(edge);
        if (curve.Value(curve.FirstParameter())
                .Distance(curve.Value(curve.LastParameter()))
            < Precision::Confusion()) {
            return std::nullopt;
        }
        const double length = GCPnts_AbscissaPoint::Length(curve);
        if (length < Precision::Confusion()) {
            return std::nullopt;
        }
        GCPnts_AbscissaPoint half(curve, length / 2.0, curve.FirstParameter());
        if (!half.IsDone()) {
            return std::nullopt;
        }
        const gp_Pnt point = curve.Value(half.Parameter());
        return Base::Vector3d(point.X(), point.Y(), point.Z());
    }
    catch (const Standard_Failure&) {
        return std::nullopt;
    }
}

namespace
{

Gui::View3DInventorViewer* viewerOf(const char* docName)
{
    Gui::Document* document = docName ? Gui::Application::Instance->getDocument(docName) : nullptr;
    auto* view = document ? dynamic_cast<Gui::View3DInventor*>(document->getActiveView()) : nullptr;
    return view ? view->getViewer() : nullptr;
}

/// the object in edit (a sketch's own curves in edit get no marker: SP10-Q6)
App::DocumentObject* objectInEdit(const char* docName)
{
    Gui::Document* document = docName ? Gui::Application::Instance->getDocument(docName) : nullptr;
    auto* vp = document ? dynamic_cast<Gui::ViewProviderDocumentObject*>(document->getInEdit())
                        : nullptr;
    return vp ? vp->getObject() : nullptr;
}

/// the middle of the model edge a 3D pick names (document, object, full subname), if it has one
std::optional<Base::Vector3d> edgeMiddle(const char* docName,
                                         const char* objName,
                                         const char* subName,
                                         const Base::Vector3d* picked = nullptr)
{
    App::Document* document = docName ? App::GetApplication().getDocument(docName) : nullptr;
    App::DocumentObject* object = document && objName ? document->getObject(objName) : nullptr;
    if (!object || !subName || !*subName) {
        return std::nullopt;
    }
    try {
        App::DocumentObject* owner = nullptr;
        const TopoDS_Shape shape = Part::Feature::getShape(
            object,
            Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                | Part::ShapeOption::Transform,
            subName,
            nullptr,
            &owner);
        if (shape.IsNull() || shape.ShapeType() != TopAbs_EDGE) {
            return std::nullopt;
        }
        App::DocumentObject* inEdit = objectInEdit(docName);
        if (inEdit && owner == inEdit) {
            return std::nullopt;
        }
        const TopoDS_Edge& edge = TopoDS::Edge(shape);
        std::optional<Base::Vector3d> middle = EdgeMidpointMarker::middleOf(edge);
        // FreeCAD-CH (ops#673): a 3D pick lies on the edge (on its tessellation); a selection
        // made without one (Python, the tree) carries (0,0,0), which must not count as a pick
        if (middle && picked) {
            BRepExtrema_DistShapeShape distance(
                BRepBuilderAPI_MakeVertex(gp_Pnt(picked->x, picked->y, picked->z)).Vertex(),
                edge);
            const double length = GCPnts_AbscissaPoint::Length(BRepAdaptor_Curve(edge));
            if (!distance.IsDone()
                || distance.Value() > std::max(0.1 * length, Precision::Confusion())) {
                return std::nullopt;
            }
        }
        return middle;
    }
    catch (const Base::Exception&) {
        return std::nullopt;
    }
    catch (const Standard_Failure&) {
        return std::nullopt;
    }
}

/// a world point's position on the viewer's viewport (device pixels)
SbVec2s onViewport(Gui::View3DInventorViewer* viewer, const Base::Vector3d& point)
{
    return viewer->getPointOnViewport(SbVec3f(float(point.x), float(point.y), float(point.z)));
}

/// the distance in logical pixels between two viewport positions
double pixelDistance(Gui::View3DInventorViewer* viewer, const SbVec2s& a, const SbVec2s& b)
{
    const double dx = double(a[0]) - double(b[0]);
    const double dy = double(a[1]) - double(b[1]);
    const double ratio = viewer->devicePixelRatioF() > 0.0 ? viewer->devicePixelRatioF() : 1.0;
    return std::hypot(dx, dy) / ratio;
}

}  // namespace

std::optional<Base::Vector3d> EdgeMidpointMarker::pickedMiddle(const char* docName,
                                                               const char* objName,
                                                               const char* subName,
                                                               const Base::Vector3d& picked)
{
    Gui::View3DInventorViewer* viewer = viewerOf(docName);
    const std::optional<Base::Vector3d> middle = edgeMiddle(docName, objName, subName, &picked);
    if (!viewer || !middle
        || pixelDistance(viewer, onViewport(viewer, *middle), onViewport(viewer, picked))
            > radiusPixels) {
        return std::nullopt;
    }
    return middle;
}

void EdgeMidpointMarker::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    switch (msg.Type) {
        case Gui::SelectionChanges::SetPreselect:
            middle = edgeMiddle(msg.pDocName, msg.pObjectName, msg.pSubName);
            if (middle) {
                attach(viewerOf(msg.pDocName));
                update(Base::Vector3d(msg.x, msg.y, msg.z));
            }
            else {
                hide();
            }
            break;
        case Gui::SelectionChanges::RmvPreselect:
        case Gui::SelectionChanges::RmvPreselectSignal:
        case Gui::SelectionChanges::ClrSelection:
            middle.reset();
            hide();
            break;
        default:
            break;
    }
}

bool EdgeMidpointMarker::eventFilter(QObject* watched, QEvent* event)
{
    if (event->type() == QEvent::MouseMove && middle && viewer && watched == viewer->viewport()) {
        const QPoint position = static_cast<QMouseEvent*>(event)->position().toPoint();
        const bool inRadius =
            pixelDistance(viewer, onViewport(viewer, *middle), viewer->fromQPoint(position))
            <= radiusPixels;
        if (inRadius) {
            coordinate->point.set1Value(0, float(middle->x), float(middle->y), float(middle->z));
            marker->whichChild = 0;
        }
        else {
            hide();
        }
    }
    return QObject::eventFilter(watched, event);
}

void EdgeMidpointMarker::attach(Gui::View3DInventorViewer* target)
{
    if (viewer == target) {
        return;
    }
    detach();
    if (!target) {
        return;
    }
    viewer = target;
    static_cast<SoSeparator*>(viewer->getSceneGraph())->addChild(marker);  // NOLINT
    viewer->viewport()->installEventFilter(this);
}

void EdgeMidpointMarker::update(const Base::Vector3d& picked)
{
    if (!viewer || !middle) {
        hide();
        return;
    }
    if (pixelDistance(viewer, onViewport(viewer, *middle), onViewport(viewer, picked))
        <= radiusPixels) {
        coordinate->point.set1Value(0, float(middle->x), float(middle->y), float(middle->z));
        marker->whichChild = 0;
    }
    else {
        hide();
    }
}

void EdgeMidpointMarker::hide()
{
    if (marker->whichChild.getValue() != SO_SWITCH_NONE) {
        marker->whichChild = SO_SWITCH_NONE;
    }
}

void EdgeMidpointMarker::detach()
{
    hide();
    if (viewer) {
        viewer->viewport()->removeEventFilter(this);
        auto* root = static_cast<SoSeparator*>(viewer->getSceneGraph());  // NOLINT
        if (root && root->findChild(marker) >= 0) {
            root->removeChild(marker);
        }
    }
    viewer = nullptr;
}
