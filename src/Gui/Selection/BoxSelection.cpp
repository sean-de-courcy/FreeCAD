// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileCopyrightText: 2026 FreeCAD contributors
// SPDX-FileNotice: Part of the FreeCAD project.

/******************************************************************************
 *                                                                            *
 *   FreeCAD is free software: you can redistribute it and/or modify          *
 *   it under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1            *
 *   of the License, or (at your option) any later version.                   *
 *                                                                            *
 *   FreeCAD is distributed in the hope that it will be useful,               *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty              *
 *   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                  *
 *   See the GNU Lesser General Public License for more details.              *
 *                                                                            *
 *   You should have received a copy of the GNU Lesser General Public         *
 *   License along with FreeCAD. If not, see https://www.gnu.org/licenses     *
 *                                                                            *
 ******************************************************************************/

#include "BoxSelection.h"

#include <memory>
#include <vector>

#include <CXX/Objects.hxx>
#include <Inventor/nodes/SoCamera.h>

#include <App/Application.h>
#include <App/ComplexGeoDataPy.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/GeoFeatureGroupExtension.h>
#include <Base/Interpreter.h>
#include <Base/Tools2D.h>

#include "Application.h"
#include "Selection.h"
#include "Utilities.h"
#include "View3DInventorViewer.h"
#include "ViewProviderDocumentObject.h"

using namespace Gui;

namespace
{

using SelectionMode = enum
{
    CENTER,
    INTERSECT
};

static bool findObjectsOfTypeInBox(
    const std::string& type,
    const Base::ViewProjMethod& proj,
    Data::ComplexGeoData* data,
    const Base::Polygon2d& polygon,
    std::vector<std::string>& ret,
    SelectionMode mode
)
{
    size_t count = data->countSubElements(type.c_str());
    if (!count) {
        return false;
    }

    bool foundElement = false;
    for (size_t i = 1; i <= count; ++i) {
        std::string element(type);
        element += std::to_string(i);
        std::unique_ptr<Data::Segment> segment(data->getSubElementByName(element.c_str()));
        if (!segment) {
            continue;
        }

        if (type == "Vertex") {
            Base::Vector3d point;
            if (data->getFirstVertexFromSubElement(segment.get(), point)) {
                auto v = proj(point);
                if (polygon.Contains(Base::Vector2d(v.x, v.y))) {
                    foundElement = true;
                    ret.push_back(element);
                    continue;
                }
            }
        }
        else {
            std::vector<Base::Vector3d> points;
            std::vector<Data::ComplexGeoData::Line> lines;
            data->getLinesFromSubElement(segment.get(), points, lines);
            if (points.empty() || lines.empty()) {
                continue;
            }

            Base::Polygon2d loop;
            // TODO: can we assume the line returned above are in proper
            // order if the element is a face?
            auto v = proj(points[lines.front().I1]);
            loop.Add(Base::Vector2d(v.x, v.y));
            for (auto& line : lines) {
                for (auto i = line.I1; i < line.I2; ++i) {
                    auto projected = proj(points[i + 1]);
                    loop.Add(Base::Vector2d(projected.x, projected.y));
                }
            }

            if (!polygon.Intersect(loop)) {
                continue;
            }
            if (mode == CENTER && !polygon.Contains(loop.CalcBoundBox().GetCenter())) {
                continue;
            }
            ret.push_back(element);
            foundElement = true;
        }
    }

    return foundElement;
}

// FreeCAD-CH, selection parity P2 (Onshape's box rule, notes/selection-parity.md section 4) ------

/// The element's projected polyline points (a vertex gives its point), or none.
std::vector<Base::Vector2d> projectedPoints(
    const std::string& type,
    const Base::ViewProjMethod& proj,
    Data::ComplexGeoData* data,
    const Data::Segment* segment,
    std::vector<std::vector<Base::Vector2d>>* polylines = nullptr
)
{
    std::vector<Base::Vector2d> ret;
    if (type == "Vertex") {
        Base::Vector3d point;
        if (data->getFirstVertexFromSubElement(segment, point)) {
            auto v = proj(point);
            ret.emplace_back(v.x, v.y);
        }
        return ret;
    }
    std::vector<Base::Vector3d> points;
    std::vector<Data::ComplexGeoData::Line> lines;
    data->getLinesFromSubElement(segment, points, lines);
    for (const auto& line : lines) {
        std::vector<Base::Vector2d> polyline;
        for (auto i = line.I1; i <= line.I2 && i < points.size(); ++i) {
            auto v = proj(points[i]);
            polyline.emplace_back(v.x, v.y);
        }
        ret.insert(ret.end(), polyline.begin(), polyline.end());
        if (polylines) {
            polylines->push_back(std::move(polyline));
        }
    }
    return ret;
}

/// A projected polyline touches the polygon: a point inside, or a segment crossing its border.
bool polylineTouches(const Base::Polygon2d& polygon, const std::vector<Base::Vector2d>& polyline)
{
    for (const auto& v : polyline) {
        if (polygon.Contains(v)) {
            return true;
        }
    }
    const size_t n = polygon.GetCtVectors();
    for (size_t j = 1; j < polyline.size(); ++j) {
        Base::Line2d segment(polyline[j - 1], polyline[j]);
        for (size_t i = 0; i < n; ++i) {
            Base::Line2d border(polygon.At(i), polygon.At((i + 1) % n));
            Base::Vector2d at;
            if (segment.IntersectAndContain(border, at)) {
                return true;
            }
        }
    }
    return false;
}

/// A crossing box touches the shape: an edge or vertex touches it, or the box lies inside a
/// face's projection (a box drawn within one face).
bool shapeTouches(
    const Base::ViewProjMethod& proj,
    Data::ComplexGeoData* data,
    const Base::Polygon2d& polygon
)
{
    for (const char* type : {"Vertex", "Edge"}) {
        size_t count = data->countSubElements(type);
        for (size_t i = 1; i <= count; ++i) {
            std::string element = std::string(type) + std::to_string(i);
            std::unique_ptr<Data::Segment> segment(data->getSubElementByName(element.c_str()));
            if (!segment) {
                continue;
            }
            std::vector<std::vector<Base::Vector2d>> polylines;
            auto points = projectedPoints(type, proj, data, segment.get(), &polylines);
            if (polylines.empty()) {
                polylines.push_back(points);
            }
            for (const auto& polyline : polylines) {
                if (polylineTouches(polygon, polyline)) {
                    return true;
                }
            }
        }
    }
    if (polygon.GetCtVectors() == 0) {
        return false;
    }
    const Base::Vector2d corner = polygon.At(0);
    size_t count = data->countSubElements("Face");
    for (size_t i = 1; i <= count; ++i) {
        std::string element = "Face" + std::to_string(i);
        std::unique_ptr<Data::Segment> segment(data->getSubElementByName(element.c_str()));
        if (!segment) {
            continue;
        }
        std::vector<Base::Vector3d> points;
        std::vector<Base::Vector3d> normals;
        std::vector<Data::ComplexGeoData::Facet> facets;
        data->getFacesFromSubElement(segment.get(), points, normals, facets);
        for (const auto& facet : facets) {
            if (facet.I1 >= points.size() || facet.I2 >= points.size() || facet.I3 >= points.size()) {
                continue;
            }
            Base::Polygon2d triangle;
            for (auto index : {facet.I1, facet.I2, facet.I3}) {
                auto v = proj(points[index]);
                triangle.Add(Base::Vector2d(v.x, v.y));
            }
            if (triangle.Contains(corner)) {
                return true;
            }
        }
    }
    return false;
}

/// A window box: the whole part ("") when every face and edge of it lies inside, else each face
/// and edge wholly inside (a face by its boundary: the box is convex). Onshape takes no vertices
/// (SQ4: a window over half a box gave its right face and that face's 4 edges).
std::vector<std::string> windowElements(
    const Base::ViewProjMethod& proj,
    Data::ComplexGeoData* data,
    const Base::Polygon2d& polygon
)
{
    std::vector<std::string> ret;
    size_t total = 0;
    for (const char* type : {"Face", "Edge"}) {
        size_t count = data->countSubElements(type);
        for (size_t i = 1; i <= count; ++i) {
            std::string element = std::string(type) + std::to_string(i);
            std::unique_ptr<Data::Segment> segment(data->getSubElementByName(element.c_str()));
            if (!segment) {
                continue;
            }
            auto points = projectedPoints(type, proj, data, segment.get());
            if (points.empty()) {
                continue;
            }
            ++total;
            bool inside = true;
            for (const auto& v : points) {
                if (!polygon.Contains(v)) {
                    inside = false;
                    break;
                }
            }
            if (inside) {
                ret.push_back(element);
            }
        }
    }
    if (total > 0 && ret.size() == total) {
        ret.assign(1, std::string());
    }
    return ret;
}

/// Onshape's box rule for one part (a leaf: a body or a shape that holds no objects): a crossing
/// box gives the whole part when it touches the part's geometry (not its bounding box); a window
/// gives the whole part wholly inside, else the faces and edges wholly inside.
std::vector<std::string> partBoxSelection(
    App::DocumentObject* obj,
    SelectionMode mode,
    const Base::ViewProjMethod& proj,
    const Base::Polygon2d& polygon,
    const Base::Matrix4D& mat,
    bool transform,
    int depth
)
{
    std::vector<std::string> ret;
    Base::PyGILStateLocker lock;
    PyObject* pyobj = nullptr;
    Base::Matrix4D matCopy(mat);
    obj->getSubObject(nullptr, &pyobj, &matCopy, transform, depth);
    std::unique_ptr<Py::Object> owner;
    if (pyobj) {
        owner = std::make_unique<Py::Object>(pyobj, true);
    }
    if (!pyobj || !PyObject_TypeCheck(pyobj, &Data::ComplexGeoDataPy::Type)) {
        // No geometry to test (a datum, a mesh view...): the caller's bounding box test decides
        if (mode == INTERSECT) {
            ret.emplace_back("");
        }
        return ret;
    }
    auto data = static_cast<Data::ComplexGeoDataPy*>(pyobj)->getComplexGeoDataPtr();
    if (mode == INTERSECT) {
        if (shapeTouches(proj, data, polygon)) {
            ret.emplace_back("");
        }
        return ret;
    }
    return windowElements(proj, data, polygon);
}

/**
 * @brief Collect box-selection matches for one view provider.
 *
 * Projects visible geometry into the view and tests it against the current
 * box or fence polygon.
 *
 * @param[in] vp View provider to query.
 * @param[in] mode Center or intersect selection mode.
 * @param[in] selectElement When true, collect subelements instead of whole objects.
 * @param[in] proj Projection function for 3D points.
 * @param[in] polygon Selection polygon in projected coordinates.
 * @param[in] mat Accumulated transformation matrix.
 * @param[in] transform Whether to apply object transforms while resolving geometry.
 * @param[in] depth Current recursion depth when walking subobjects.
 * @return Matching subelement names, or an empty-string entry for whole-object matches.
 */
std::vector<std::string> getBoxSelection(
    ViewProviderDocumentObject* vp,
    SelectionMode mode,
    bool selectElement,
    const Base::ViewProjMethod& proj,
    const Base::Polygon2d& polygon,
    const Base::Matrix4D& mat,
    bool transform = true,
    int depth = 0
)
{
    std::vector<std::string> ret;
    auto obj = vp->getObject();
    if (!obj || !obj->isAttachedToDocument()) {
        return ret;
    }

    App::Document* doc = App::GetApplication().getActiveDocument();
    const auto selectionGate = SelectionSingleton::instance().getSelectionGate(doc);

    // FreeCAD-CH, selection parity P2: an object holding objects (the Part Studio, a group) is
    // never selected whole, only the parts in it (Onshape, SQ4).
    const auto& subs = obj->getSubObjects(App::DocumentObject::GS_SELECT);

    // DO NOT check this view object Visibility, let the caller do this. Because
    // we may be called by upper object hierarchy that manages our visibility.
    auto bbox3 = vp->getBoundingBox(nullptr, &mat, transform);
    Base::BoundBox2d bbox;
    const bool isBBox3Valid = bbox3.IsValid();
    if (isBBox3Valid && selectionGate == nullptr) {
        bbox = bbox3.ProjectBox(&proj);

        // check if both two boundary points are inside polygon, only
        // valid since we know the given polygon is a box.
        if (subs.empty() && polygon.Contains(Base::Vector2d(bbox.MinX, bbox.MinY))
            && polygon.Contains(Base::Vector2d(bbox.MaxX, bbox.MaxY))) {
            ret.emplace_back("");
            return ret;
        }

        if (!bbox.Intersect(polygon)) {
            return ret;
        }
    }

    if (subs.empty()) {
        if (!selectElement && selectionGate == nullptr) {
            // FreeCAD-CH, selection parity P2: a part, by its geometry
            return partBoxSelection(obj, mode, proj, polygon, mat, transform, depth);
        }
        if (!selectElement) {
            if (mode == INTERSECT || (isBBox3Valid && polygon.Contains(bbox.GetCenter()))) {
                ret.emplace_back("");
            }
            return ret;
        }

        Base::PyGILStateLocker lock;
        PyObject* pyobj = nullptr;
        Base::Matrix4D matCopy(mat);
        obj->getSubObject(nullptr, &pyobj, &matCopy, transform, depth);
        if (!pyobj) {
            return ret;
        }

        Py::Object pyobject(pyobj, true);
        if (!PyObject_TypeCheck(pyobj, &Data::ComplexGeoDataPy::Type)) {
            return ret;
        }

        auto data = static_cast<Data::ComplexGeoDataPy*>(pyobj)->getComplexGeoDataPtr();
        const auto& allAllowedDocumentTypes = data->getElementTypes();

        if (selectionGate) {
            auto filteredTypes = selectionGate->getGatedTypes(allAllowedDocumentTypes);
            if (!filteredTypes.empty()) {
                for (const auto& type : filteredTypes) {
                    findObjectsOfTypeInBox(type, proj, data, polygon, ret, mode);
                }
                return ret;
            }
        }

        for (auto type : allAllowedDocumentTypes) {
            if (findObjectsOfTypeInBox(type, proj, data, polygon, ret, mode)) {
                break;
            }
        }
        return ret;
    }

    for (auto& sub : subs) {
        App::DocumentObject* parent = nullptr;
        std::string childName;
        Base::Matrix4D smat(mat);
        auto sobj
            = obj->resolve(sub.c_str(), &parent, &childName, nullptr, nullptr, &smat, transform, depth + 1);
        if (!sobj) {
            continue;
        }

        int vis;
        if (!parent || (vis = parent->isElementVisible(childName.c_str())) < 0) {
            vis = sobj->Visibility.getValue() ? 1 : 0;
        }
        if (!vis) {
            continue;
        }

        auto svp = freecad_cast<ViewProviderDocumentObject*>(
            Application::Instance->getViewProvider(sobj)
        );
        if (!svp) {
            continue;
        }

        const auto& sels
            = getBoxSelection(svp, mode, selectElement, proj, polygon, smat, false, depth + 1);
        for (auto& sel : sels) {
            ret.emplace_back(sub + sel);
        }
    }

    // FreeCAD-CH, selection parity P2: no collapse to the container when every child matched
    // (a box around both parts gave the Part Studio itself).
    return ret;
}

}  // namespace

void Gui::applyBoxSelection(
    View3DInventorViewer* viewer,
    const std::vector<SbVec2s>& picked,
    bool selectElement,
    bool additive
)
{
    if (!viewer || picked.size() < 2) {
        return;
    }

    App::Document* doc = App::GetApplication().getActiveDocument();
    if (!doc) {
        return;
    }

    SelectionMode selectionMode = CENTER;
    std::vector<SbVec2f> glPolygon = viewer->getGLPolygon(picked);

    Base::Polygon2d polygon;
    if (glPolygon.size() == 2) {
        const auto& pt1 = glPolygon[0];
        const auto& pt2 = glPolygon[1];
        polygon.Add(Base::Vector2d(pt1[0], pt1[1]));
        polygon.Add(Base::Vector2d(pt1[0], pt2[1]));
        polygon.Add(Base::Vector2d(pt2[0], pt2[1]));
        polygon.Add(Base::Vector2d(pt2[0], pt1[1]));

        // when selecting from right to left then select by intersection
        // otherwise if the center is inside the rectangle
        if (pt1[0] > pt2[0]) {
            selectionMode = INTERSECT;
        }
    }
    else {
        for (const auto& point : glPolygon) {
            polygon.Add(Base::Vector2d(point[0], point[1]));
        }
    }

    SoCamera* cam = viewer->getSoRenderManager()->getCamera();
    if (!cam) {
        return;
    }

    if (!additive) {
        Gui::Selection().clearSelection(doc->getName());
    }

    Gui::ViewVolumeProjection proj(cam->getViewVolume());

    const std::vector<App::DocumentObject*> objects = doc->getObjects();
    for (auto* obj : objects) {
        if (App::GeoFeatureGroupExtension::getGroupOfObject(obj)) {
            continue;
        }

        auto vp = freecad_cast<ViewProviderDocumentObject*>(
            Application::Instance->getViewProvider(obj)
        );
        if (!vp || !vp->isVisible()) {
            continue;
        }

        Base::Matrix4D mat;
        for (auto& sub : getBoxSelection(vp, selectionMode, selectElement, proj, polygon, mat)) {
            Gui::Selection().addSelection(doc->getName(), obj->getNameInDocument(), sub.c_str());
        }
    }
}
