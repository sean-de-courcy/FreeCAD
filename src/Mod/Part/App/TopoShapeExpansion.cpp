// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *                                                                          *
 *   Copyright (c) 2022 Zheng, Lei <realthunder.dev@gmail.com>              *
 *   Copyright (c) 2023 FreeCAD Project Association                         *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/

#include <algorithm>
#include <array>
#include <cmath>
#include <cctype>
#include <cstring>
#include <exception>
#include <limits>
#include <memory>
#include <numeric>
#include <optional>
#include <sstream>
#include <tuple>
#include <unordered_set>
#include <vector>

#ifndef _Standard_Version_HeaderFile
# include <Standard_Version.hxx>
#endif

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_CompCurve.hxx>
#if OCC_VERSION_HEX < 0x070600
# include <BRepAdaptor_HCurve.hxx>
# include <BRepAdaptor_HCompCurve.hxx>
#endif

#include <Base/Profiler.h>
#include <BRepAlgoAPI_Defeaturing.hxx>
#include <BRepAlgoAPI_Splitter.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepFill.hxx>
#include <BRepFill_Generator.hxx>
#include <BOPTools_AlgoTools3D.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepTopAdaptor_FClass2d.hxx>
#include <BRepTools.hxx>
#include <IntTools_Context.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <Mod/Part/App/FCBRepAlgoAPI_BooleanOperation.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Common.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Cut.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Fuse.h>
#include <Mod/Part/App/FCBRepAlgoAPI_Section.h>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_FindPlane.hxx>
#include <Geom_Plane.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Surface.hxx>
#include <gp.hxx>
#include <GeomAPI_ProjectPointOnCurve.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GeomLProp_SLProps.hxx>
#include <BRepBuilderAPI_GTransform.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepBuilderAPI_NurbsConvert.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepLib.hxx>
#include <BRepOffsetAPI_DraftAngle.hxx>
#include <BRepOffsetAPI_MakeFilling.hxx>
#include <BRepOffsetAPI_MakePipe.hxx>
#include <BRepOffsetAPI_MakeEvolved.hxx>
#include <BRepOffsetAPI_MakeThickSolid.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepProj_Projection.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom2dAdaptor_Curve.hxx>
#include <BndLib_Add2dCurve.hxx>
#include <Bnd_Box2d.hxx>
#include <GeomConvert.hxx>
#include <GeomFill_BezierCurves.hxx>
#include <GeomFill_BSplineCurves.hxx>
#include <Precision.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <BRepGProp.hxx>
#include <GProp_GProps.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopTools_DataMapOfShapeInteger.hxx>
#include <TopTools_DataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <ShapeAnalysis_FreeBounds.hxx>
#include <ShapeBuild_ReShape.hxx>
#include <ShapeConstruct_Curve.hxx>
#include <ShapeUpgrade_ShellSewing.hxx>
#include <StdFail_NotDone.hxx>
#include <TopTools_HSequenceOfShape.hxx>
#include <ShapeFix_Shape.hxx>
#include <ShapeFix_ShapeTolerance.hxx>
#include <gp.hxx>
#include <gp_Ax3.hxx>
#include <gp_Pln.hxx>
#include <gp_Vec2d.hxx>
#include <BRepFill_CompatibleWires.hxx>

#include <boost/algorithm/string/predicate.hpp>

#include <utility>

#include <OSD_Parallel.hxx>

#include <FCConfig.h>

#include "modelRefine.h"
#include "CrossSection.h"
#include "FilletFallback.h"
#include "MassProperties.h"
#include "TopoShape.h"
#include "TopoShapeOpCode.h"
#include "TopoShapeCache.h"
#include "TopoShapeMapper.h"
#include "NamingHash.h"
#include "NameSetOrder.h"
#include "FaceMaker.h"
#include "Geometry.h"
#include "BRepOffsetAPI_MakeOffsetFix.h"
#include "PipeShellApproximation.h"
#include "ProgressIndicator.h"
#include "ShapeAnalysis_FreeBoundsFix.h"
#include "SweepFrenet.h"

#include <App/Application.h>
#include <App/Document.h>
#include <App/ElementMap.h>
#include <App/ElementNamingUtils.h>
#include <App/NameTable.h>
#include <Base/BoundBox.h>
#include <Base/Exception.h>
#include <Base/Sequencer.h>
#include <Base/Tools.h>
#include <SignalException.h>
#include <ShapeAnalysis_FreeBoundsProperties.hxx>
#include <BRepFeat_MakeRevol.hxx>

#include "Tools.h"

FC_LOG_LEVEL_INIT("TopoShape", true, true)  // NOLINT

#if OCC_VERSION_HEX >= 0x070600
using Adaptor3d_HCurve = Adaptor3d_Curve;
using BRepAdaptor_HCurve = BRepAdaptor_Curve;
using BRepAdaptor_HCompCurve = BRepAdaptor_CompCurve;
#endif

namespace Part
{

static void expandCompound(const TopoShape& shape, std::vector<TopoShape>& res)
{
    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null input shape");
    }
    if (shape.getShape().ShapeType() != TopAbs_COMPOUND) {
        res.push_back(shape);
        return;
    }
    for (auto& s : shape.getSubTopoShapes()) {
        expandCompound(s, res);
    }
}

namespace
{
/// A name in the form of a map that interns or not (ops#6), as ElementMap::setElementName stores it
Data::MappedName toMapForm(const Data::MappedName& name, bool interned)
{
    auto& table = Data::NameTable::instance();
    if (interned) {
        std::string text = name.toString();
        std::string form = table.toInterned(text);
        return form == text ? name : Data::MappedName(form);
    }
    if (name.find(std::string(1, Data::NameTable::Marker)) < 0) {
        return name;
    }
    return Data::MappedName(table.toPlain(name.toString()));
}

/// The names of an input, in this shape's form, so that a builder's uniqueness counts see one
/// form when its inputs differ in it (a plain and an interned document's shapes)
void toMapForm(
    std::vector<std::pair<Data::MappedName, Data::ElementIDRefs>>& names,
    const TopoShape& input,
    const TopoShape& result
)
{
    if (input.getInternNames() == result.getInternNames()) {
        return;
    }
    for (auto& entry : names) {
        entry.first = toMapForm(entry.first, result.getInternNames());
    }
}

/// A shape built from an interned input interns its names too (ops#6): the document's switch
/// reaches every shape built from its features' shapes, along with the algorithm
void inheritInternNames(TopoShape& result, const TopoShape& input)
{
    if (input.getInternNames() && !result.getInternNames()) {
        result.setInternNames(true);
    }
}

void inheritInternNames(TopoShape& result, const std::vector<TopoShape>& inputs)
{
    for (const auto& input : inputs) {
        inheritInternNames(result, input);
    }
}
}  // namespace

void TopoShape::initCache(int reset) const
{
    if (reset > 0 || !_cache || _cache->isTouched(_Shape)) {
        if (_parentCache) {
            _parentCache.reset();
            _subLocation.Identity();
        }
        _cache = std::make_shared<TopoShapeCache>(_Shape);
    }
}

Data::ElementMapPtr TopoShape::resetElementMap(Data::ElementMapPtr elementMap)
{
    if (_cache && elementMap != this->elementMap(false)) {
        for (auto& info : _cache->shapeAncestryCache) {
            info.clear();
        }
    }
    else {
        initCache();
    }
    if (elementMap) {
        _cache->cachedElementMap = elementMap;
        _cache->subLocation.Identity();
        _cache->selectedHistoryAlgorithm = getHistoryAlgorithm();
        _subLocation.Identity();
        _parentCache.reset();
    }
    return Data::ComplexGeoData::resetElementMap(elementMap);
}

void TopoShape::dropElementNaming()
{
    resetElementMap();
    Tag = 0;
    Hasher = nullptr;
    initCache(1);
}

void TopoShape::flushElementMap() const
{
    initCache();
    if (!elementMap(false) && this->_cache) {
        if (this->_cache->cachedElementMap) {
            const_cast<TopoShape*>(this)->resetElementMap(this->_cache->cachedElementMap);
        }
        else if (this->_parentCache) {
            // The parent's algorithm is this shape's, copied when it was taken from the parent
            // (TopoShapeCache::Ancestry::_getTopoShape). The cache's own copy is set only with
            // an element map, so for a parent without one it says V2 even in V1 (ops#30).
            TopoShape parent(
                this->Tag,
                this->Hasher,
                this->_parentCache->shape,
                getHistoryAlgorithm()
            );
            parent._cache = _parentCache;
            parent.flushElementMap();
            TopoShape self(
                this->Tag,
                this->Hasher,
                this->_Shape.Located(this->_subLocation * this->_cache->subLocation),
                getHistoryAlgorithm()
            );
            self._cache = _cache;
            self.setHistoryAlgorithm(parent.getHistoryAlgorithm());
            self.mapSubElement(parent);
            this->_parentCache.reset();
            this->_subLocation.Identity();
            const_cast<TopoShape*>(this)->resetElementMap(self.elementMap());
        }
    }
}

void TopoShape::setShape(const TopoDS_Shape& shape, bool resetElementMap)
{
    if (resetElementMap) {
        this->resetElementMap();
    }
    else if (_cache && _cache->isTouched(shape)) {
        this->flushElementMap();
    }
    //_Shape._Shape = shape; // TODO: Replace the next line with this once ShapeProtector is
    // available.
    _Shape = shape;
    if (_cache) {
        initCache();
    }
}


TopoDS_Shape& TopoShape::move(TopoDS_Shape& tds, const TopLoc_Location& location)
{
#if OCC_VERSION_HEX < 0x070600
    tds.Move(location);
#else
    tds.Move(location, false);
#endif
    return tds;
}

TopoDS_Shape TopoShape::moved(const TopoDS_Shape& tds, const TopLoc_Location& location)
{
#if OCC_VERSION_HEX < 0x070600
    return tds.Moved(location);
#else
    return tds.Moved(location, false);
#endif
}

TopoDS_Shape& TopoShape::move(TopoDS_Shape& tds, const gp_Trsf& transfer)
{
#if OCC_VERSION_HEX < 0x070600
    static constexpr double scalePrecision {1e-14};
    if (std::abs(transfer.ScaleFactor()) > scalePrecision)
#else
    if (std::abs(transfer.ScaleFactor()) > TopLoc_Location::ScalePrec())
#endif
    {
        auto transferCopy(transfer);
        transferCopy.SetScaleFactor(1.0);
        tds.Move(transferCopy);
    }
    else {
        tds.Move(transfer);
    }
    return tds;
}

TopoDS_Shape TopoShape::moved(const TopoDS_Shape& tds, const gp_Trsf& transfer)
{
    TopoDS_Shape sCopy(tds);
    return move(sCopy, transfer);
}

TopoDS_Shape& TopoShape::locate(TopoDS_Shape& tds, const TopLoc_Location& loc)
{
    tds.Location(TopLoc_Location());
    return move(tds, loc);
}

TopoDS_Shape TopoShape::located(const TopoDS_Shape& tds, const TopLoc_Location& loc)
{
    auto sCopy(tds);
    sCopy.Location(TopLoc_Location());
    return moved(sCopy, loc);
}

TopoDS_Shape& TopoShape::locate(TopoDS_Shape& tds, const gp_Trsf& transfer)
{
    tds.Location(TopLoc_Location());
    return move(tds, transfer);
}

TopoDS_Shape TopoShape::located(const TopoDS_Shape& tds, const gp_Trsf& transfer)
{
    auto sCopy(tds);
    sCopy.Location(TopLoc_Location());
    return moved(sCopy, transfer);
}

void TopoShape::operator=(const TopoShape& sh)
{
    if (this != &sh) {
        this->setShape(sh._Shape, true);
        this->Tag = sh.Tag;
        this->Hasher = sh.Hasher;
        this->_cache = sh._cache;
        this->_parentCache = sh._parentCache;
        this->_subLocation = sh._subLocation;
        setHistoryAlgorithm(sh.getHistoryAlgorithm());
        setInternNames(sh.getInternNames());
        resetElementMap(sh.elementMap(false));
    }
}

int TopoShape::findShape(const TopoDS_Shape& subshape) const
{
    initCache();
    return _cache->findShape(_Shape, subshape);
}


TopoDS_Shape TopoShape::findShape(const char* name) const
{
    if (!name) {
        return {};
    }

    Data::MappedElement res = getElementName(name);
    if (!res.index) {
        return {};
    }

    auto idx = shapeTypeAndIndex(name);
    if (idx.second == 0) {
        return {};
    }
    initCache();
    return _cache->findShape(_Shape, idx.first, idx.second);
}

TopoDS_Shape TopoShape::findShape(TopAbs_ShapeEnum type, int idx) const
{
    initCache();
    return _cache->findShape(_Shape, type, idx);
}

std::vector<TopoShape> TopoShape::findSubShapesWithSharedVertex(
    const TopoShape& subshape,
    std::vector<std::string>* names,
    Data::SearchOptions options,
    double tol,
    double atol
) const
{
    bool checkGeometry = options.testFlag(Data::SearchOption::CheckGeometry);
    bool singleSearch = options.testFlag(Data::SearchOption::SingleResult);
    std::vector<TopoShape> res;
    if (subshape.isNull() || this->isNull()) {
        return res;
    }
    double tol2 = tol * tol;
    int index = 0;
    TopAbs_ShapeEnum shapeType = subshape.shapeType();

    // This is an intentionally recursive method, which will exit after looking through all
    // ancestors.
    auto searchCompositeShape = [&](TopAbs_ShapeEnum childType) {  // NOLINT (misc-no-recu2rsive)
        unsigned long count = subshape.countSubShapes(childType);
        if (!count) {
            return;
        }
        auto first = subshape.getSubTopoShape(childType, 1);
        for (const auto& child : findSubShapesWithSharedVertex(first, nullptr, options, tol, atol)) {
            for (int idx : findAncestors(child.getShape(), shapeType)) {
                auto shape = getSubTopoShape(shapeType, idx);
                if (shape.countSubShapes(childType) != count) {
                    continue;
                }
                bool found = true;
                for (unsigned long i = 2; i < count; ++i) {
                    if (shape
                            .findSubShapesWithSharedVertex(
                                subshape.getSubTopoShape(childType, i),
                                nullptr,
                                options,
                                tol,
                                atol
                            )
                            .empty()) {
                        found = false;
                        break;
                    }
                }
                if (found) {
                    res.push_back(shape);
                    if (names) {
                        names->push_back(shapeName(shapeType) + std::to_string(idx));
                    }
                    if (singleSearch) {
                        return;
                    }
                }
            }
        }
    };

    switch (shapeType) {
        case TopAbs_WIRE:
            searchCompositeShape(TopAbs_EDGE);
            break;
        case TopAbs_SHELL:
            searchCompositeShape(TopAbs_FACE);
            break;
        case TopAbs_SOLID:
            searchCompositeShape(TopAbs_SHELL);
            break;
        case TopAbs_COMPSOLID:
            searchCompositeShape(TopAbs_SOLID);
            break;
        case TopAbs_COMPOUND:
            // special treatment of single sub-shape compound, that is, search
            // its extracting the compound
            if (countSubShapes(TopAbs_SHAPE) == 1) {
                return findSubShapesWithSharedVertex(
                    subshape.getSubTopoShape(TopAbs_SHAPE, 1),
                    names,
                    options,
                    tol,
                    atol
                );
            }
            else if (unsigned long count = countSubShapes(TopAbs_SHAPE)) {
                // For multi-sub-shape compound, only search for compound with the same
                // structure
                int idx = 0;
                for (const auto& compound : getSubTopoShapes(shapeType)) {
                    ++idx;
                    if (compound.countSubShapes(TopAbs_SHAPE) != count) {
                        continue;
                    }
                    int i = 0;
                    bool found = true;
                    for (const auto& s : compound.getSubTopoShapes(TopAbs_SHAPE)) {
                        ++i;
                        auto ss = subshape.getSubTopoShape(TopAbs_SHAPE, i);
                        if (ss.isNull() && s.isNull()) {
                            continue;
                        }
                        auto options2 = options;
                        options2.setFlag(Data::SearchOption::SingleResult);
                        if (
                            ss.isNull() || s.isNull() || ss.shapeType() != s.shapeType()
                            || ss.findSubShapesWithSharedVertex(s, nullptr, options2, tol, atol).empty()
                        ) {
                            found = false;
                            break;
                        }
                    }
                    if (found) {
                        if (names) {
                            names->push_back(shapeName(shapeType) + std::to_string(idx));
                        }
                        res.push_back(compound);
                        if (singleSearch) {
                            return res;
                        }
                    }
                }
            }
            break;
        case TopAbs_VERTEX:
            // Vertex search will do comparison with tolerance to account for
            // rounding error inccured through transformation.
            for (auto& shape : getSubShapes(TopAbs_VERTEX)) {
                ++index;
                if (BRep_Tool::Pnt(TopoDS::Vertex(shape))
                        .SquareDistance(BRep_Tool::Pnt(TopoDS::Vertex(subshape.getShape())))
                    <= tol2) {
                    if (names) {
                        names->push_back(std::string("Vertex") + std::to_string(index));
                    }
                    res.push_back(getSubTopoShape(TopAbs_VERTEX, index));
                    if (singleSearch) {
                        return res;
                    }
                }
            }
            break;
        case TopAbs_EDGE:
        case TopAbs_FACE: {
            std::unique_ptr<Geometry> geom;
            bool isLine = false;
            bool isPlane = false;

            std::vector<TopoDS_Shape> vertices;
            TopoShape wire(getHistoryAlgorithm());
            if (shapeType == TopAbs_FACE) {
                wire = subshape.splitWires();
                vertices = wire.getSubShapes(TopAbs_VERTEX);
            }
            else {
                vertices = subshape.getSubShapes(TopAbs_VERTEX);
            }

            if (vertices.empty() || checkGeometry) {
                geom = Geometry::fromShape(subshape.getShape(), true);
                if (!geom) {
                    return res;
                }
                if (shapeType == TopAbs_EDGE) {
                    isLine
                        = (geom->isDerivedFrom<GeomLine>() || geom->isDerivedFrom<GeomLineSegment>());
                }
                else {
                    isPlane = geom->isDerivedFrom<GeomPlane>();
                }
            }

            auto compareGeometry = [&](const TopoShape& s, bool strict) {
                std::unique_ptr<Geometry> g2(Geometry::fromShape(s.getShape(), true));
                if (!g2) {
                    return false;
                }
                if (isLine && !strict) {
                    // For lines, don't compare geometry, just check the
                    // vertices below instead, because the exact same edge
                    // may have different geometrical representation.
                    if (!g2->isDerivedFrom<GeomLine>() && !g2->isDerivedFrom<GeomLineSegment>()) {
                        return false;
                    }
                }
                else if (isPlane && !strict) {
                    // For planes, don't compare geometry either, so that
                    // we don't need to worry about orientation and so on.
                    // Just check the edges.
                    if (!g2->isDerivedFrom<GeomPlane>()) {
                        return false;
                    }
                }
                else if (!g2 || !g2->isSame(*geom, tol, atol)) {
                    return false;
                }
                return true;
            };

            if (vertices.empty()) {
                // Probably an infinite shape, so we have to search by geometry
                int idx = 0;
                for (auto& shape : getSubTopoShapes(shapeType)) {
                    ++idx;
                    if (!shape.countSubShapes(TopAbs_VERTEX) && compareGeometry(shape, true)) {
                        if (names) {
                            names->push_back(shapeName(shapeType) + std::to_string(idx));
                        }
                        res.push_back(shape);
                        if (singleSearch) {
                            return res;
                        }
                    }
                }
                break;
            }

            // The basic idea of shape search is about the same for both edge and face.
            // * Search the first vertex, which is done with tolerance.
            // * Find the ancestor shape of the found vertex
            // * Compare each vertex of the ancestor shape and the input shape
            // * Perform geometry comparison of the ancestor and input shape.
            //      * For face, perform addition geometry comparison of each edge.
            std::unordered_set<TopoShape, ShapeHasher, ShapeHasher> shapeSet;
            for (auto& vert :
                 findSubShapesWithSharedVertex(vertices[0], nullptr, options, tol, atol)) {
                for (auto idx : findAncestors(vert.getShape(), shapeType)) {
                    auto shape = getSubTopoShape(shapeType, idx);
                    if (!shapeSet.insert(shape).second) {
                        continue;
                    }
                    TopoShape otherWire(getHistoryAlgorithm());
                    std::vector<TopoDS_Shape> otherVertices;
                    if (shapeType == TopAbs_FACE) {
                        otherWire = shape.splitWires();
                        if (wire.countSubShapes(TopAbs_EDGE)
                            != otherWire.countSubShapes(TopAbs_EDGE)) {
                            continue;
                        }
                        otherVertices = otherWire.getSubShapes(TopAbs_VERTEX);
                    }
                    else {
                        otherVertices = shape.getSubShapes(TopAbs_VERTEX);
                    }
                    if (otherVertices.size() != vertices.size()) {
                        continue;
                    }
                    if (checkGeometry && !compareGeometry(shape, false)) {
                        continue;
                    }
                    unsigned ind = 0;
                    bool matched = true;
                    for (auto& vertex : vertices) {
                        bool found = false;
                        for (unsigned inner = 0; inner < otherVertices.size(); ++inner) {
                            auto& vertex1 = otherVertices[ind];
                            if (++ind == otherVertices.size()) {
                                ind = 0;
                            }
                            if (BRep_Tool::Pnt(TopoDS::Vertex(vertex))
                                    .SquareDistance(BRep_Tool::Pnt(TopoDS::Vertex(vertex1)))
                                <= tol2) {
                                found = true;
                                break;
                            }
                        }
                        if (!found) {
                            matched = false;
                            break;
                        }
                    }
                    if (!matched) {
                        continue;
                    }

                    if (shapeType == TopAbs_FACE && checkGeometry) {
                        // Is it really necessary to check geometries of each edge of a face?
                        // Right now we only do outer wire check
                        auto otherEdges = otherWire.getSubShapes(TopAbs_EDGE);
                        std::vector<std::unique_ptr<Geometry>> geos;
                        geos.resize(otherEdges.size());
                        bool matched2 = true;
                        unsigned i = 0;
                        auto edges = wire.getSubShapes(TopAbs_EDGE);
                        for (auto& edge : edges) {
                            std::unique_ptr<Geometry> geom2(Geometry::fromShape(edge, true));
                            if (!geom2) {
                                matched2 = false;
                                break;
                            }
                            bool isLine2 = false;
                            gp_Pnt pt1, pt2;
                            if (geom2->isDerivedFrom<GeomLine>()
                                || geom2->isDerivedFrom<GeomLineSegment>()) {
                                pt1 = BRep_Tool::Pnt(TopExp::FirstVertex(TopoDS::Edge(edge)));
                                pt2 = BRep_Tool::Pnt(TopExp::LastVertex(TopoDS::Edge(edge)));
                                isLine2 = true;
                            }
                            // We will tolerate on edge reordering
                            bool found = false;
                            for (unsigned j = 0; j < otherEdges.size(); j++) {
                                auto& e1 = otherEdges[i];
                                auto& g1 = geos[i];
                                if (++i >= otherEdges.size()) {
                                    i = 0;
                                }
                                if (!g1) {
                                    g1 = Geometry::fromShape(e1, true);
                                    if (!g1) {
                                        break;
                                    }
                                }
                                if (isLine2) {
                                    if (g1->isDerivedFrom<GeomLine>()
                                        || g1->isDerivedFrom<GeomLineSegment>()) {
                                        auto p1 = BRep_Tool::Pnt(TopExp::FirstVertex(TopoDS::Edge(e1)));
                                        auto p2 = BRep_Tool::Pnt(TopExp::LastVertex(TopoDS::Edge(e1)));
                                        if ((p1.SquareDistance(pt1) <= tol2
                                             && p2.SquareDistance(pt2) <= tol2)
                                            || (p1.SquareDistance(pt2) <= tol2
                                                && p2.SquareDistance(pt1) <= tol2)) {
                                            found = true;
                                            break;
                                        }
                                    }
                                    continue;
                                }

                                if (g1->isSame(*geom2, tol, atol)) {
                                    found = true;
                                    break;
                                }
                            }
                            if (!found) {
                                matched2 = false;
                                break;
                            }
                        }
                        if (!matched2) {
                            continue;
                        }
                    }
                    if (names) {
                        names->push_back(shapeName(shapeType) + std::to_string(idx));
                    }
                    res.push_back(shape);
                }
            }
            break;
        }
        default:
            break;
    }
    return res;
}

int TopoShape::findAncestor(const TopoDS_Shape& subshape, TopAbs_ShapeEnum type) const
{
    initCache();
    return _cache->findShape(_Shape, _cache->findAncestor(_Shape, subshape, type));
}

TopoDS_Shape TopoShape::findAncestorShape(const TopoDS_Shape& subshape, TopAbs_ShapeEnum type) const
{
    initCache();
    return _cache->findAncestor(_Shape, subshape, type);
}

std::vector<int> TopoShape::findAncestors(const TopoDS_Shape& subshape, TopAbs_ShapeEnum type) const
{
    const auto& shapes = findAncestorsShapes(subshape, type);
    std::vector<int> ret;
    ret.reserve(shapes.size());
    for (const auto& shape : shapes) {
        ret.push_back(findShape(shape));
    }
    return ret;
}

std::vector<TopoDS_Shape> TopoShape::findAncestorsShapes(
    const TopoDS_Shape& subshape,
    TopAbs_ShapeEnum type
) const
{
    initCache();
    std::vector<TopoDS_Shape> shapes;
    _cache->findAncestor(_Shape, subshape, type, &shapes);
    return shapes;
}

// The following lines should be used for now to replace the original macros (in the future we can
// refactor to use std::source_location and eliminate the use of the macros entirely).
//     FC_THROWM(NullShapeException, "Null shape");
//     FC_THROWM(NullShapeException, "Null input shape");
//     FC_WARN("Null input shape");  // NOLINT
//
// The original macros:
// #define HANDLE_NULL_SHAPE _HANDLE_NULL_SHAPE("Null shape",true)
// #define HANDLE_NULL_INPUT _HANDLE_NULL_SHAPE("Null input shape",true)
// #define WARN_NULL_INPUT _HANDLE_NULL_SHAPE("Null input shape",false)

bool TopoShape::hasPendingElementMap() const
{
    return !elementMap(false) && this->_cache
        && (this->_parentCache || this->_cache->cachedElementMap);
}

bool TopoShape::canMapElement(const TopoShape& other) const
{
    if (isNull() || other.isNull() || this == &other || other.Tag == -1 || Tag == -1) {
        return false;
    }
    if ((other.Tag == 0) && !other.elementMap(false) && !other.hasPendingElementMap()) {
        return false;
    }
    initCache();
    other.initCache();
    _cache->relations.clear();
    return true;
}

namespace
{
size_t checkSubshapeCount(
    const TopoShape& topoShape1,
    const TopoShape& topoShape2,
    TopAbs_ShapeEnum elementType
)
{
    auto count = topoShape1.countSubShapes(elementType);
    auto other = topoShape2.countSubShapes(elementType);
    if (count != other) {
        FC_WARN("sub shape mismatch");  // NOLINT
        if (count > other) {
            count = other;
        }
    }
    return count;
}

}  // namespace

void TopoShape::setupChild(
    Data::ElementMap::MappedChildElements& child,
    TopAbs_ShapeEnum elementType,
    const TopoShape& topoShape,
    size_t shapeCount,
    const char* op
)
{
    child.indexedName = Data::IndexedName::fromConst(TopoShape::shapeName(elementType).c_str(), 1);
    child.offset = 0;
    child.count = static_cast<int>(shapeCount);
    child.elementMap = topoShape.elementMap();
    if (this->Tag != topoShape.Tag) {
        child.tag = topoShape.Tag;
    }
    else {
        child.tag = 0;
    }
    if (op) {
        child.postfix = op;
    }
}

void TopoShape::copyElementMap(const TopoShape& topoShape, const char* op)
{
    if (topoShape.isNull() || isNull()) {
        return;
    }
    std::vector<Data::ElementMap::MappedChildElements> children;
    std::array<TopAbs_ShapeEnum, 3> elementTypes = {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE};
    for (const auto elementType : elementTypes) {
        auto count = checkSubshapeCount(*this, topoShape, elementType);
        if (count == 0) {
            continue;
        }
        children.emplace_back();
        auto& child = children.back();
        setupChild(child, elementType, topoShape, count, op);
    }
    resetElementMap();
    inheritInternNames(*this, topoShape);
    if (!Hasher) {
        Hasher = topoShape.Hasher;
    }
    setMappedChildElements(children);
}

namespace
{
/// appendElementSection() with the section's mapper flags given
void appendSection(
    TopoShape& shape,
    long tag,
    const char* op,
    const std::string& index,
    const std::vector<std::string>& flags
)
{
    if (shape.getHistoryAlgorithm() != App::HistoryAlgorithm::V2 || shape.isNull()
        || !shape.hasElementMap()) {
        return;
    }
    const std::vector<Data::MappedName> noNames;
    std::vector<std::tuple<Data::IndexedName, Data::MappedName, Data::ElementIDRefs>> names;
    for (const auto type : {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE}) {
        const auto& typeName = TopoShape::shapeName(type);
        const std::string section = Data::NAME_SECTION_DELIMINATOR
            + Data::MappedName::makeEncodedSection(
                {},
                noNames,
                std::to_string(tag),
                op,
                index,
                typeName[0],
                std::string("0"),
                flags,
                noNames
            );
        const auto count = static_cast<int>(shape.countSubShapes(type));
        for (int i = 1; i <= count; ++i) {
            auto element = Data::IndexedName::fromConst(typeName.c_str(), i);
            // In the element's order, so its first name stays first
            for (auto& [name, sids] : shape.getElementMappedNames(element)) {
                Data::MappedName newName(name);
                newName.append(section.c_str());
                names.emplace_back(element, newName, sids);
            }
        }
    }
    // A new map: the old one may be shared, e.g. with the shape this one is a copy of
    shape.resetElementMap(std::make_shared<Data::ElementMap>());
    for (const auto& [element, name, sids] : names) {
        shape.setElementName(element, name, shape.Tag, &sids);
    }
}
}  // namespace

TopoShape& TopoShape::appendElementSection(long tag, const char* op, const std::string& index)
{
    appendSection(*this, tag, op, index, {Data::MAPPER_FLAG_MODIFIED});
    return *this;
}


// TODO: Refactor mapSubElementTypeForShape to reduce complexity
void TopoShape::mapSubElementTypeForShape(
    const TopoShape& other,
    TopAbs_ShapeEnum type,
    const char* op,
    int count,
    bool forward,
    bool& warned
)
{
    const App::HistoryAlgorithm& historyVersion = getHistoryAlgorithm();
    auto& shapeMap = _cache->getAncestry(type);
    auto& otherMap = other._cache->getAncestry(type);
    const char* shapeType = shapeName(type).c_str();

    // 1-indexed for readability (e.g. there is no "Edge0", we started at "Edge1", etc.)
    for (int outerCounter = 1; outerCounter <= count; ++outerCounter) {
        int innerCounter {0};
        int index {0};
        if (forward) {
            innerCounter = outerCounter;
            index = shapeMap.find(_Shape, otherMap.find(other._Shape, outerCounter));
            if (index == 0) {
                continue;
            }
        }
        else {
            index = outerCounter;
            innerCounter = otherMap.find(other._Shape, shapeMap.find(_Shape, outerCounter));
            if (innerCounter == 0) {
                continue;
            }
        }
        Data::IndexedName element = Data::IndexedName::fromConst(shapeType, index);
        std::vector<std::pair<Data::MappedName, Data::ElementIDRefs>> mappedNames
            = other.getElementMappedNames(element);  // don't get unmapped.

        if (mappedNames.empty()) {
            if (historyVersion == App::HistoryAlgorithm::V1) {
                mappedNames.push_back({Data::MappedName(element), {}});
            }
            else if (historyVersion == App::HistoryAlgorithm::V2) {
                mappedNames.push_back(
                    {Data::MappedName::makeUnmappedName(
                         {element.toString()},
                         other.Tag,
                         op,
                         (*element.getType())
                     ),
                     {}}
                );
            }
        }

        for (auto& mappedName : mappedNames) {
            auto& name = mappedName.first;
            auto& sids = mappedName.second;
            if (!sids.empty()) {
                if (!Hasher) {
                    Hasher = sids[0].getHasher();
                }
                else if (!sids[0].isFromSameHasher(Hasher)) {
                    if (!warned) {
                        warned = true;
                        FC_LOG("hasher mismatch: dropping the string IDs of names from another "
                               "string table");  // NOLINT
                    }
                    sids.clear();
                }
            }
            char elementType {shapeName(type)[0]};

            std::ostringstream ss;
            ensureElementMap()->encodeElementName(elementType, name, ss, &sids, Tag, op, other.Tag);
            elementMap()->setElementName(element, name, Tag, &sids);
        }
    }
}

void TopoShape::mapSubElementForShape(const TopoShape& other, const char* op)
{
    inheritInternNames(*this, other);
    bool warned = false;
    static const std::array<TopAbs_ShapeEnum, 3> types = {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE};

    for (auto type : types) {
        auto& shapeMap = _cache->getAncestry(type);
        auto& otherMap = other._cache->getAncestry(type);
        if ((shapeMap.empty()) || (otherMap.empty())) {
            continue;
        }

        bool forward {false};
        int count {0};
        if (otherMap.count() <= shapeMap.count()) {
            forward = true;
            count = otherMap.count();
        }
        else {
            forward = false;
            count = shapeMap.count();
        }
        mapSubElementTypeForShape(other, type, op, count, forward, warned);
    }
}

void TopoShape::mapSubElement(
    const TopoShape& other,
    const char* op,
    bool forceHasher,
    IncludedNameMap* nameMap
)
{
    if (!canMapElement(other)) {
        return;
    }
    inheritInternNames(*this, other);

    if (!getElementMapSize(false) && this->_Shape.IsPartner(other._Shape)) {
        if (!this->Hasher) {
            this->Hasher = other.Hasher;
        }
        copyElementMap(other, op);
        return;
    }

    bool warned = false;
    static const std::array<TopAbs_ShapeEnum, 3> types = {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE};
    const App::HistoryAlgorithm& historyVersion = getHistoryAlgorithm();
    size_t shapeHash = std::hash<TopoDS_Shape> {}(getShape());

    auto checkHasher = [this](const TopoShape& other) {
        if (Hasher) {
            if (other.Hasher != Hasher) {
                // The input has another string table (hasher) than this shape, e.g. another
                // document's, or none. The user can't act on it, so it goes only to the log
                // (ops#151, upstream issue 24567). Retagging the input to this hasher instead of
                // switching would keep this shape's names valid: ops#201.
                if (!getElementMapSize(false)) {
                    FC_LOG("hasher mismatch: the shape takes the string table of its input");
                }
                else {
                    // FC_THROWM(Base::RuntimeError, "hasher mismatch");
                    FC_LOG(
                        "hasher mismatch: the shape takes the string table of its input while "
                        "it already has element names"
                    );
                }
                Hasher = other.Hasher;
            }
        }
        else {
            Hasher = other.Hasher;
        }
    };

    TopoDS_Shape mappedShape;

    for (auto type : types) {
        auto& shapeMap = _cache->getAncestry(type);
        auto& otherMap = other._cache->getAncestry(type);
        if (!shapeMap.count() || !otherMap.count()) {
            continue;
        }
        if (!forceHasher && other.Hasher) {
            forceHasher = true;
            checkHasher(other);
        }
        const char* shapetype = shapeName(type).c_str();
        std::ostringstream ss;

        bool forward;
        int count;
        if (otherMap.count() <= shapeMap.count()) {
            forward = true;
            count = otherMap.count();
        }
        else {
            forward = false;
            count = shapeMap.count();
        }
        for (int k = 1; k <= count; ++k) {
            int i, idx;
            if (forward) {
                mappedShape = otherMap.find(other._Shape, k);
                i = k;
                idx = shapeMap.find(_Shape, mappedShape);
                if (!idx) {
                    continue;
                }
            }
            else {
                mappedShape = shapeMap.find(_Shape, k);
                idx = k;
                i = otherMap.find(other._Shape, mappedShape);
                if (!i) {
                    continue;
                }
            }
            Data::IndexedName element = Data::IndexedName::fromConst(shapetype, idx);
            Data::IndexedName otherElement = Data::IndexedName::fromConst(shapetype, i);
            std::vector<std::pair<Data::MappedName, Data::ElementIDRefs>> mappedNames
                = other.getElementMappedNames(otherElement);  // don't get unmapped.

            if (mappedNames.empty()) {
                if (historyVersion == App::HistoryAlgorithm::V1) {
                    mappedNames.push_back({Data::MappedName(otherElement), {}});
                }
                else if (historyVersion == App::HistoryAlgorithm::V2) {
                    mappedNames.push_back(
                        {Data::MappedName::makeUnmappedName(
                             {otherElement.toString()},
                             other.Tag,
                             op,
                             element.getType()[0]
                         ),
                         {}}
                    );
                }
            }

            if (historyVersion == App::HistoryAlgorithm::V2) {
                // Before the name map records the first one (the seed of a V2 builder)
                toMapForm(mappedNames, other, *this);
            }

            if (mappedNames.size()) {
                for (auto& v : mappedNames) {
                    auto& name = v.first;
                    auto& sids = v.second;
                    if (sids.size()) {
                        if (!Hasher) {
                            Hasher = sids[0].getHasher();
                        }
                        else if (!sids[0].isFromSameHasher(Hasher)) {
                            if (!warned) {
                                warned = true;
                                FC_LOG("hasher mismatch: dropping the string IDs of names from "
                                       "another string table");
                            }
                            sids.clear();
                        }
                    }
                    ss.str("");

                    if (historyVersion == App::HistoryAlgorithm::V1) {
                        ensureElementMap()
                            ->encodeElementName(shapetype[0], name, ss, &sids, Tag, op, other.Tag);
                    }
                    ensureElementMap()->setElementName(element, name, Tag, &sids);
                }

                if (nameMap) {
                    (*nameMap)[mappedShape] = {shapeHash, mappedNames.front().first};
                }
            }
        }
    }
}

void TopoShape::mapSubElementsTo(
    std::vector<TopoShape>& shapes,
    const char* op,
    IncludedNameMap* nameMap
) const
{
    for (auto& shape : shapes) {
        shape.mapSubElement(*this, op, false, nameMap);
    }
}

std::vector<Data::ElementMap::MappedChildElements> TopoShape::createChildMap(
    size_t count,
    const std::vector<TopoShape>& shapes,
    const char* op
)
{
    std::vector<Data::ElementMap::MappedChildElements> children;
    children.reserve(count * (size_t)3);
    std::array<TopAbs_ShapeEnum, 3> types = {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE};
    for (const auto topAbsType : types) {
        size_t offset = 0;
        for (auto& topoShape : shapes) {
            if (topoShape.isNull()) {
                continue;
            }
            auto subShapeCount = topoShape.countSubShapes(topAbsType);
            if (subShapeCount == 0) {
                continue;
            }
            children.emplace_back();
            auto& child = children.back();
            child.indexedName
                = Data::IndexedName::fromConst(TopoShape::shapeName(topAbsType).c_str(), 1);
            child.offset = static_cast<int>(offset);
            offset += subShapeCount;
            child.count = static_cast<int>(subShapeCount);
            child.elementMap = topoShape.elementMap();
            child.tag = topoShape.Tag;
            if (op) {
                child.postfix = op;
            }
        }
    }
    return children;
}

namespace
{
// ops#45: child ranges give each child of a compound the next countSubShapes(type) indexes. When a
// child shares a sub-shape with an earlier one, TopExp skips it in the compound, so the later
// indexes are off (e.g. a group of a box and a link to one of its faces). The counts add up
// exactly when nothing is shared. Otherwise the ranges still fit if every index they reach holds
// the child's own element; a range that runs past the end (a child wholly shared with earlier
// ones) only names nothing there.
bool childRangesFit(const TopoShape& compound, const std::vector<TopoShape>& children)
{
    for (auto type : {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE}) {
        const int total = compound.countSubShapes(type);
        int sum = 0;
        for (const auto& child : children) {
            if (!child.isNull()) {
                sum += child.countSubShapes(type);
            }
        }
        if (sum == total) {
            continue;
        }
        int offset = 0;
        for (const auto& child : children) {
            if (child.isNull()) {
                continue;
            }
            const int count = child.countSubShapes(type);
            for (int index = 1; index <= count && offset + index <= total; ++index) {
                if (!compound.getSubShape(type, offset + index, true)
                         .IsSame(child.getSubShape(type, index, true))) {
                    return false;
                }
            }
            offset += count;
        }
    }
    return true;
}
}  // namespace

void TopoShape::mapCompoundSubElements(const std::vector<TopoShape>& shapes, const char* op)
{
    int count = 0;
    for (auto& topoShape : shapes) {
        if (topoShape.isNull()) {
            continue;
        }
        ++count;
        auto subshape = getSubShape(TopAbs_SHAPE, count, /*silent = */ true);
        if (!subshape.IsPartner(topoShape._Shape)) {
            return;  // Not a partner shape, don't do any mapping at all
        }
    }
    if (!childRangesFit(*this, shapes)) {
        mapSubElement(shapes, op);  // maps each child by shape
        return;
    }
    auto children {createChildMap(count, shapes, op)};
    inheritInternNames(*this, shapes);
    setMappedChildElements(children);
}

void TopoShape::mapSubElement(const std::vector<TopoShape>& shapes, const char* op, IncludedNameMap* nameMap)
{
    if (shapes.empty()) {
        return;
    }
    inheritInternNames(*this, shapes);

    if (shapeType(true) == TopAbs_COMPOUND) {
        int count = 0;
        for (auto& s : shapes) {
            if (s.isNull()) {
                continue;
            }
            if (!getSubShape(TopAbs_SHAPE, ++count, true).IsPartner(s._Shape)) {
                count = 0;
                break;
            }
        }
        if (count && !childRangesFit(*this, shapes)) {
            count = 0;  // the children share sub-shapes: map each one by shape below
        }
        if (count) {
            std::vector<Data::ElementMap::MappedChildElements> children;
            children.reserve(count * 3);
            TopAbs_ShapeEnum types[] = {TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE};
            for (unsigned i = 0; i < sizeof(types) / sizeof(types[0]); ++i) {
                int offset = 0;
                for (auto& s : shapes) {
                    if (s.isNull()) {
                        continue;
                    }
                    int count = s.countSubShapes(types[i]);
                    if (!count) {
                        continue;
                    }
                    children.emplace_back();
                    auto& child = children.back();
                    child.indexedName = Data::IndexedName::fromConst(shapeName(types[i]).c_str(), 1);
                    child.offset = offset;
                    offset += count;
                    child.count = count;
                    child.elementMap = s.elementMap();
                    child.tag = s.Tag;
                    if (op) {
                        child.postfix = op;
                    }
                }
            }
            setMappedChildElements(children);
            return;
        }
    }

    for (auto& shape : shapes) {
        mapSubElement(shape, op, false, nameMap);
    }
}

std::vector<TopoDS_Shape> TopoShape::getSubShapes(TopAbs_ShapeEnum type, TopAbs_ShapeEnum avoid) const
{
    std::vector<TopoDS_Shape> ret;
    if (isNull()) {
        return ret;
    }
    if (avoid != TopAbs_SHAPE) {
        for (TopExp_Explorer exp(getShape(), type, avoid); exp.More(); exp.Next()) {
            ret.push_back(exp.Current());
        }
        return ret;
    }
    initCache();
    auto& ancestry = _cache->getAncestry(type);
    int count = ancestry.count();
    ret.reserve(count);
    for (int i = 1; i <= count; ++i) {
        ret.push_back(ancestry.find(_Shape, i));
    }
    return ret;
}

std::vector<TopoShape> TopoShape::getSubTopoShapes(TopAbs_ShapeEnum type, TopAbs_ShapeEnum avoid) const
{
    if (isNull()) {
        return std::vector<TopoShape>();
    }
    initCache();

    auto res = _cache->getAncestry(type).getTopoShapes(*this);
    if (avoid != TopAbs_SHAPE && hasSubShape(avoid)) {
        for (auto it = res.begin(); it != res.end();) {
            if (_cache->findAncestor(_Shape, it->getShape(), avoid).IsNull()) {
                ++it;
            }
            else {
                it = res.erase(it);
            }
        }
    }
    return res;
}

std::vector<TopoShape> TopoShape::getOrderedEdges(MapElement mapElement) const
{
    if (isNull()) {
        return std::vector<TopoShape>();
    }

    std::vector<TopoShape> shapes;
    if (shapeType() == TopAbs_WIRE) {
        BRepTools_WireExplorer xp(TopoDS::Wire(getShape()));
        while (xp.More()) {
            shapes.push_back(TopoShape(getHistoryAlgorithm(), xp.Current()));
            xp.Next();
        }
    }
    else {
        //        INIT_SHAPE_CACHE();
        initCache();
        for (const auto& w : getSubShapes(TopAbs_WIRE)) {
            BRepTools_WireExplorer xp(TopoDS::Wire(w));
            while (xp.More()) {
                shapes.push_back(TopoShape(getHistoryAlgorithm(), xp.Current()));
                xp.Next();
            }
        }
    }
    if (mapElement == MapElement::map) {
        mapSubElementsTo(shapes);
    }
    return shapes;
}

std::vector<TopoShape> TopoShape::getOrderedVertexes(MapElement mapElement) const
{
    if (isNull()) {
        return std::vector<TopoShape>();
    }

    std::vector<TopoShape> shapes;

    auto collect = [&](const TopoDS_Shape& s) {
        auto wire = TopoDS::Wire(s);
        BRepTools_WireExplorer xp(wire);
        while (xp.More()) {
            shapes.push_back(TopoShape(getHistoryAlgorithm(), xp.CurrentVertex()));
            xp.Next();
        }
        // special treatment for open wires
        TopoDS_Vertex Vfirst, Vlast;
        TopExp::Vertices(wire, Vfirst, Vlast);
        if (!Vfirst.IsNull() && !Vlast.IsNull()) {
            if (!Vfirst.IsSame(Vlast)) {
                shapes.push_back(TopoShape(getHistoryAlgorithm(), Vlast));
            }
        }
    };

    if (shapeType() == TopAbs_WIRE) {
        collect(getShape());
    }
    else {
        //        INIT_SHAPE_CACHE();
        initCache();
        for (const auto& s : getSubShapes(TopAbs_WIRE)) {
            collect(s);
        }
    }
    if (mapElement == MapElement::map) {
        mapSubElementsTo(shapes);
    }
    return shapes;
}

struct ShapeInfo
{
    const TopoDS_Shape& shape;
    TopoShapeCache::Ancestry& cache;
    TopAbs_ShapeEnum type;
    const char* shapetype;

    ShapeInfo(const TopoDS_Shape& shape, TopAbs_ShapeEnum type, TopoShapeCache::Ancestry& cache)
        : shape(shape)
        , cache(cache)
        , type(type)
        , shapetype(TopoShape::shapeName(type).c_str())
    {}

    [[nodiscard]] int count() const
    {
        return cache.count();
    }

    TopoDS_Shape find(int index)
    {
        return cache.find(shape, index);
    }

    int find(const TopoDS_Shape& subshape)
    {
        return cache.find(shape, subshape);
    }
};

////////////////////////////////////////
// makESHAPE -> makeShapeWithElementMap
///////////////////////////////////////

namespace
{
// The order of the members of a fallback list (UPP, LOW, PRJ) that share their names and are
// told apart only by an index (ops#378). The result's indexes follow the order in which OCCT
// stores sub-shapes, which can differ between platforms and OCCT versions (a round hole's four
// bend arcs in a Pipe: Windows and macOS store them in opposite orders). Instead, an UPP member's
// place is read in the parameterization of its reference, the first element in the list's name
// order that isn't a plane: a rigid motion of the inputs, a dimension edit or a tilt through an
// axis-aligned position moves the members and the reference together, so the order holds. The
// shape's own coordinates come last, and are all that LOW and PRJ members have (no reference).

/// One component of an element's order key: a value, and the period that wraps it (0: none).
struct OrderValue
{
    double value = 0;
    double period = 0;
};
/// The components of a key in order of precedence; every member of a list has the same number.
using OrderValues = std::vector<OrderValue>;

/// An element's point (its centre of mass; a vertex: its point; a degenerate edge: its vertex)
/// and its length or area, `mass`.
gp_Pnt elementPoint(const TopoDS_Shape& element, double& mass)
{
    mass = 0;
    if (element.ShapeType() == TopAbs_VERTEX) {
        return BRep_Tool::Pnt(TopoDS::Vertex(element));
    }
    if (element.ShapeType() == TopAbs_EDGE && BRep_Tool::Degenerated(TopoDS::Edge(element))) {
        const TopoDS_Vertex vertex = TopExp::FirstVertex(TopoDS::Edge(element));
        return vertex.IsNull() ? gp_Pnt() : BRep_Tool::Pnt(vertex);
    }
    GProp_GProps props;
    if (TopExp_Explorer(element, TopAbs_FACE).More()) {
        BRepGProp::SurfaceProperties(element, props);
    }
    else {
        BRepGProp::LinearProperties(element, props);
    }
    mass = props.Mass();
    return props.CentreOfMass();
}

/// The parameters of `element` on `face`, of which it is a sub-shape: an edge, at the midpoint of
/// its pcurve; a vertex, the smallest (`u` first) over the pcurves of the face's edges that end
/// there. An edge closed on the face (a seam) has two pcurves, and `CurveOnSurface` picks one by
/// the edge's orientation, which follows the storage order: the seam takes the smaller of the
/// two, as a vertex on it does. Not finite when no pcurve is found.
gp_Pnt2d parametersOnFace(const TopoDS_Face& face, const TopoDS_Shape& element)
{
    const double none = std::numeric_limits<double>::quiet_NaN();
    bool found = false;
    gp_Pnt2d smallest(none, none);
    auto consider = [&](const gp_Pnt2d& candidate) {
        if (!found || candidate.X() < smallest.X()
            || (candidate.X() == smallest.X() && candidate.Y() < smallest.Y())) {
            smallest = candidate;
            found = true;
        }
    };
    auto onPcurve = [&](const TopoDS_Edge& edge, auto parameterOf) {
        double first = 0;
        double last = 0;
        Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, face, first, last);
        if (!pcurve.IsNull()) {
            consider(pcurve->Value(parameterOf(first, last)));
        }
    };
    if (element.ShapeType() == TopAbs_EDGE) {
        const TopoDS_Edge edge = TopoDS::Edge(element);
        auto midpoint = [](double first, double last) {
            return (first + last) / 2;
        };
        onPcurve(edge, midpoint);
        if (BRep_Tool::IsClosed(edge, face)) {
            onPcurve(TopoDS::Edge(edge.Reversed()), midpoint);
        }
    }
    else if (element.ShapeType() == TopAbs_VERTEX) {
        // The explorer meets a seam once per orientation, so both of its pcurves count
        for (TopExp_Explorer edges(face, TopAbs_EDGE); edges.More(); edges.Next()) {
            const TopoDS_Edge edge = TopoDS::Edge(edges.Current());
            for (TopExp_Explorer vertexes(edge, TopAbs_VERTEX); vertexes.More(); vertexes.Next()) {
                if (vertexes.Current().IsSame(element)) {
                    const double parameter
                        = BRep_Tool::Parameter(TopoDS::Vertex(vertexes.Current()), edge);
                    onPcurve(edge, [parameter](double, double) { return parameter; });
                }
            }
        }
    }
    return smallest;
}

/// The parameter of `vertex` on `edge`; not finite when it doesn't bound the edge.
double parameterOnEdge(const TopoDS_Edge& edge, const TopoDS_Shape& vertex)
{
    for (TopExp_Explorer vertexes(edge, TopAbs_VERTEX); vertexes.More(); vertexes.Next()) {
        if (vertexes.Current().IsSame(vertex)) {
            return BRep_Tool::Parameter(TopoDS::Vertex(vertexes.Current()), edge);
        }
    }
    return std::numeric_limits<double>::quiet_NaN();
}

/// Where `vertex`, generated where `edge` crosses `face`, lies on the edge (ops#468): `in` where
/// the edge's curve, in the direction of its parameter, enters the face's side of the face (it
/// runs against the face's normal, the face's orientation counted), `out` where it leaves it;
/// empty where the vertex lies off the curve or the surface, or the curve runs along the face
/// there. A hole crossing an edge twice makes one of each, and an edit that moves the hole keeps
/// each crossing's side.
std::string crossingSide(
    const TopoDS_Shape& vertex,
    const TopoDS_Shape& edge,
    const TopoDS_Shape& face
)
{
    if (vertex.IsNull() || vertex.ShapeType() != TopAbs_VERTEX || edge.IsNull()
        || edge.ShapeType() != TopAbs_EDGE || face.IsNull() || face.ShapeType() != TopAbs_FACE) {
        return {};
    }
    const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(vertex));
    const double tolerance = BRep_Tool::Tolerance(TopoDS::Vertex(vertex)) + Precision::Confusion();
    double first = 0;
    double last = 0;
    const Handle(Geom_Curve) curve = BRep_Tool::Curve(TopoDS::Edge(edge), first, last);
    const Handle(Geom_Surface) surface = BRep_Tool::Surface(TopoDS::Face(face));
    if (curve.IsNull() || surface.IsNull()) {
        return {};
    }
    GeomAPI_ProjectPointOnCurve onCurve(point, curve, first, last);
    if (onCurve.NbPoints() == 0
        || onCurve.LowerDistance() > tolerance + BRep_Tool::Tolerance(TopoDS::Edge(edge))) {
        return {};
    }
    GeomAPI_ProjectPointOnSurf onSurface(point, surface);
    if (onSurface.NbPoints() == 0
        || onSurface.LowerDistance() > tolerance + BRep_Tool::Tolerance(TopoDS::Face(face))) {
        return {};
    }
    gp_Pnt curvePoint;
    gp_Vec tangent;
    curve->D1(onCurve.LowerDistanceParameter(), curvePoint, tangent);
    double u = 0;
    double v = 0;
    onSurface.LowerDistanceParameters(u, v);
    GeomLProp_SLProps props(surface, u, v, 1, Precision::Confusion());
    if (tangent.Magnitude() < gp::Resolution() || !props.IsNormalDefined()) {
        return {};
    }
    gp_Dir normal = props.Normal();
    if (face.Orientation() == TopAbs_REVERSED) {
        normal.Reverse();
    }
    // Below this the curve runs along the face: no side to tell
    constexpr double alongTheFace = 1e-4;
    const double cosine = gp_Dir(tangent).Dot(normal);
    if (std::abs(cosine) < alongTheFace) {
        return {};
    }
    return cosine < 0 ? Data::ROLE_CROSSING_IN : Data::ROLE_CROSSING_OUT;
}

/// A member's discriminating fields in its group (`naming-class-A.md` M2, I-A1 and I-A2): its
/// Index, its DuplicateCount, and whether its name carries ORD.
struct TwinPlace
{
    std::string index = "0";
    std::string duplicateCount = "0";
    bool ordered = false;
};

/// The place `k` among `n` twins as DuplicateCount carries it, `<k>of<n>` (ops#468, the size
/// rule): the count is in every twin's name, so a change in how many there are renames them all
/// and never passes a name to another twin.
std::string placeAmong(std::size_t k, std::size_t n)
{
    return std::to_string(k) + "of" + std::to_string(n);
}

/// The places of `count` members told apart by nothing but their order (twinOrder's), in that
/// order: a lone member `0`, as before; twins Index `0` and `<k>of<n>`, with ORD, so that the
/// solver takes them for twins (counter siblings) and re-checks an exact hit that moved.
std::vector<TwinPlace> twinPlaces(std::size_t count)
{
    std::vector<TwinPlace> places(count);
    if (count > 1) {
        for (std::size_t k = 0; k < count; ++k) {
            places[k].duplicateCount = placeAmong(k, count);
            places[k].ordered = true;
        }
    }
    return places;
}

/// The places of vertexes generated where `edge` crosses `face` (the group's first source, and its
/// first face source; the face may be null), `vertexes` in their canonical order (twinOrder's)
/// (ops#468). Each is named by its side of the face (crossingSide), a role, in Index, lone ones
/// included, and with `<k>of<n>` among the vertexes on the same side when there are several. Where
/// a side can't be told for one of them, none has one (I-A6), and they take twinPlaces. Every
/// name told by a role carries ORD: the role flips when an edit reverses the edge's curve with
/// the geometry unchanged (a MultiFuse's inputs reordered), and the flag is what sends a moved
/// exact hit on it to the solver's twin check (the role-sibling clause, `naming-class-A.md` 4.1).
std::vector<TwinPlace> crossingPlaces(
    const std::vector<TopoDS_Shape>& vertexes,
    const TopoDS_Shape& edge,
    const TopoDS_Shape& face
)
{
    std::vector<std::string> sides;
    for (const auto& vertex : vertexes) {
        sides.push_back(crossingSide(vertex, edge, face));
        if (sides.back().empty()) {
            return twinPlaces(vertexes.size());
        }
    }
    std::map<std::string, std::size_t> onSide;
    for (const auto& side : sides) {
        ++onSide[side];
    }
    std::map<std::string, std::size_t> before;
    std::vector<TwinPlace> places;
    for (const auto& side : sides) {
        const std::size_t k = before[side]++;
        TwinPlace place;
        place.index = side;
        place.duplicateCount = onSide[side] > 1 ? placeAmong(k, onSide[side]) : "0";
        place.ordered = true;
        places.push_back(place);
    }
    return places;
}

/// The key of a member of a fallback list: its place on the list's `reference` (a face: its `u`
/// and `v`; an edge, for a vertex named from edges: its parameter; null: none), then its length
/// or area, then its point in `frame`, the frame of the shape being named. Members that the
/// reference doesn't tell apart are told apart by the last components; coincident members tie
/// and keep the result's order, which no name tells apart anyway.
OrderValues elementOrderValues(
    const TopoDS_Shape& element,
    const TopoDS_Shape& reference,
    const TopLoc_Location& frame
)
{
    OrderValues values;
    if (!reference.IsNull() && reference.ShapeType() == TopAbs_FACE) {
        const TopoDS_Face face = TopoDS::Face(reference);
        const gp_Pnt2d parameters = parametersOnFace(face, element);
        const BRepAdaptor_Surface surface(face, Standard_False);
        values.push_back({parameters.X(), surface.IsUPeriodic() ? surface.UPeriod() : 0});
        values.push_back({parameters.Y(), surface.IsVPeriodic() ? surface.VPeriod() : 0});
    }
    else if (!reference.IsNull() && reference.ShapeType() == TopAbs_EDGE) {
        values.push_back({parameterOnEdge(TopoDS::Edge(reference), element)});
    }
    double mass = 0;
    const gp_Pnt point = elementPoint(element, mass).Transformed(frame.Transformation());
    values.push_back({mass});
    values.push_back({point.X()});
    values.push_back({point.Y()});
    values.push_back({point.Z()});
    return values;
}

/// Each member's rank per component of its key: sorted by value, members closer than
/// `10 * Precision::Confusion()` to their neighbour share a rank (no grid, so a near-tie can't
/// straddle a cell boundary); a periodic component also chains the values at the end of its
/// period to those at its start. Members compare by their ranks, lexicographically. Values that
/// aren't finite (no pcurve, an unbounded element) share the last rank, after the wrap-around.
std::vector<std::vector<long>> rankByGaps(const std::vector<OrderValues>& keys)
{
    const double tolerance = 10 * Precision::Confusion();
    std::vector<std::vector<long>> ranks(keys.size());
    if (keys.empty()) {
        return ranks;
    }
    std::size_t components = keys.front().size();
    for (const auto& key : keys) {
        components = std::min(components, key.size());
    }
    std::vector<std::size_t> order;
    std::vector<long> rankOf(keys.size());
    for (std::size_t component = 0; component < components; ++component) {
        auto valueOf = [&](std::size_t member) {
            return keys[member][component].value;
        };
        // The finite values sorted; the others after them, in no order
        order.clear();
        for (std::size_t member = 0; member < keys.size(); ++member) {
            if (std::isfinite(valueOf(member))) {
                order.push_back(member);
            }
        }
        const std::size_t finite = order.size();
        std::stable_sort(order.begin(), order.end(), [&](std::size_t left, std::size_t right) {
            return valueOf(left) < valueOf(right);
        });
        long rank = 0;
        for (std::size_t k = 0; k < finite; ++k) {
            if (k > 0 && valueOf(order[k]) - valueOf(order[k - 1]) > tolerance) {
                ++rank;
            }
            rankOf[order[k]] = rank;
        }
        const double period = finite > 0 ? keys[order.front()][component].period : 0;
        if (period > 0 && rank > 0
            && valueOf(order.front()) + period - valueOf(order[finite - 1]) <= tolerance) {
            for (std::size_t member : order) {
                if (rankOf[member] == rank) {
                    rankOf[member] = 0;
                }
            }
        }
        for (std::size_t member = 0; member < keys.size(); ++member) {
            if (!std::isfinite(valueOf(member))) {
                rankOf[member] = finite > 0 ? rank + 1 : 0;
            }
        }
        for (std::size_t member = 0; member < keys.size(); ++member) {
            ranks[member].push_back(rankOf[member]);
        }
    }
    return ranks;
}

/// The members' order by their ranks (rankByGaps), compared lexicographically; ties keep the
/// order the members are given in.
std::vector<std::size_t> orderByRanks(const std::vector<std::vector<long>>& ranks)
{
    std::vector<std::size_t> order(ranks.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&ranks](std::size_t left, std::size_t right) {
        return ranks[left] < ranks[right];
    });
    return order;
}

/// The canonical order of the members of a group told apart by their place alone (I-A3,
/// `naming-class-A.md` M2 (c)), as indexes into `members`, which come in the maker's order: by
/// each member's parameter on the first of `sources` if that is an edge (the pave order along it,
/// made explicit), else by its (u, v) on the first face among `sources`, then by its length or
/// area and its point in `frame`, the frame of the shape being named. A member is placed on a
/// source by projecting its point (a vertex's; an edge's or a face's centre of mass) onto the
/// source's curve or surface: members are the result's elements, not the source's sub-shapes.
/// Vertexes generated along a closed edge keep the order given (NamingMap::build's exception: the
/// maker lists them from the edge's seam, which an edit can move past one of them). Ties keep the
/// order given. Whatever decides the order, the twins' names carry ORD (twinPlaces), so the
/// solver re-checks a twin's exact hit that moved.
std::vector<std::size_t> twinOrder(
    const std::vector<TopoDS_Shape>& members,
    const std::vector<TopoDS_Shape>& sources,
    const TopLoc_Location& frame
)
{
    std::vector<std::size_t> given(members.size());
    std::iota(given.begin(), given.end(), 0);
    if (members.size() < 2) {
        return given;
    }
    TopoDS_Shape edge;
    TopoDS_Shape face;
    if (!sources.empty() && !sources.front().IsNull()
        && sources.front().ShapeType() == TopAbs_EDGE) {
        edge = sources.front();
    }
    else {
        for (const auto& source : sources) {
            if (!source.IsNull() && source.ShapeType() == TopAbs_FACE) {
                face = source;
                break;
            }
        }
    }
    Handle(Geom_Curve) curve;
    double first = 0;
    double last = 0;
    if (!edge.IsNull()) {
        TopoDS_Vertex start;
        TopoDS_Vertex end;
        TopExp::Vertices(TopoDS::Edge(edge), start, end);
        if (members.front().ShapeType() == TopAbs_VERTEX && !start.IsNull() && start.IsSame(end)) {
            return given;
        }
        curve = BRep_Tool::Curve(TopoDS::Edge(edge), first, last);
    }
    Handle(Geom_Surface) surface;
    if (!face.IsNull()) {
        surface = BRep_Tool::Surface(TopoDS::Face(face));
    }
    const double none = std::numeric_limits<double>::quiet_NaN();
    std::vector<OrderValues> keys;
    keys.reserve(members.size());
    for (const auto& member : members) {
        double mass = 0;
        const gp_Pnt point = elementPoint(member, mass);
        OrderValues values;
        if (!curve.IsNull()) {
            GeomAPI_ProjectPointOnCurve onCurve(point, curve, first, last);
            values.push_back(
                {onCurve.NbPoints() > 0 ? onCurve.LowerDistanceParameter() : none,
                 curve->IsPeriodic() ? curve->Period() : 0}
            );
        }
        else if (!surface.IsNull()) {
            GeomAPI_ProjectPointOnSurf onSurface(point, surface);
            double u = none;
            double v = none;
            if (onSurface.NbPoints() > 0) {
                onSurface.LowerDistanceParameters(u, v);
            }
            values.push_back({u, surface->IsUPeriodic() ? surface->UPeriod() : 0});
            values.push_back({v, surface->IsVPeriodic() ? surface->VPeriod() : 0});
        }
        const gp_Pnt inFrame = point.Transformed(frame.Transformation());
        values.push_back({mass});
        values.push_back({inFrame.X()});
        values.push_back({inFrame.Y()});
        values.push_back({inFrame.Z()});
        keys.push_back(std::move(values));
    }
    return orderByRanks(rankByGaps(keys));
}

/// True if the order of a fallback list's members is no key by I-A3, so that their names carry
/// ORD (`naming-class-A.md` M2 (b) (i) and (ii)): `keys` are the members' elementOrderValues on
/// `reference`, `ranks` their rankByGaps and `order` the members sorted by them. That is where two
/// members next to each other in the order are told apart (i) only by their points in the frame
/// (their places on the reference and their lengths or areas tie), by nothing at all, or on the
/// reference where one of them has no place on it (no pcurve), or (ii) by a periodic parameter of
/// a reference closed in that direction (a whole cylinder's or torus's face, a closed edge), where
/// a member's parameter can jump by the period with the members unmoved. An order told by a
/// parameter of an open reference, or by length or area, is rigid-motion invariant: the size in
/// the names is then the whole net.
bool fallbackOrderIsNoKey(
    const std::vector<OrderValues>& keys,
    const std::vector<std::vector<long>>& ranks,
    const std::vector<std::size_t>& order,
    const TopoDS_Shape& reference
)
{
    std::size_t onReference = 0;
    std::array<bool, 2> closed {false, false};
    if (!reference.IsNull() && reference.ShapeType() == TopAbs_FACE) {
        onReference = 2;
        double uMin = 0;
        double uMax = 0;
        double vMin = 0;
        double vMax = 0;
        BRepTools::UVBounds(TopoDS::Face(reference), uMin, uMax, vMin, vMax);
        const double tolerance = 10 * Precision::PConfusion();
        const BRepAdaptor_Surface surface(TopoDS::Face(reference), Standard_False);
        closed[0] = surface.IsUPeriodic() && uMax - uMin >= surface.UPeriod() - tolerance;
        closed[1] = surface.IsVPeriodic() && vMax - vMin >= surface.VPeriod() - tolerance;
    }
    else if (!reference.IsNull() && reference.ShapeType() == TopAbs_EDGE) {
        onReference = 1;
        TopoDS_Vertex start;
        TopoDS_Vertex end;
        TopExp::Vertices(TopoDS::Edge(reference), start, end);
        closed[0] = !start.IsNull() && start.IsSame(end);
    }
    for (std::size_t k = 1; k < order.size(); ++k) {
        const auto& left = ranks[order[k - 1]];
        const auto& right = ranks[order[k]];
        std::size_t component = 0;
        while (component < left.size() && left[component] == right[component]) {
            ++component;
        }
        if (component == left.size() || component > onReference) {
            return true;  // (i): a tie, or told apart by the frame's coordinates only
        }
        if (component < onReference) {
            const OrderValue& leftValue = keys[order[k - 1]][component];
            const OrderValue& rightValue = keys[order[k]][component];
            if (!std::isfinite(leftValue.value) || !std::isfinite(rightValue.value)) {
                return true;  // (i): a member with no place on the reference
            }
            if (leftValue.period > 0 && closed[component]) {
                return true;  // (ii)
            }
        }
    }
    return false;
}
}  // namespace

struct NameKey
{
    Data::MappedName name;
    long tag = 0;
    int shapetype = 0;

    NameKey() = default;
    explicit NameKey(Data::MappedName n)
        : name(std::move(n))
    {}
    NameKey(int type, Data::MappedName n)
        : name(std::move(n))
    {
        // Order the shape type from vertex < edge < face < other.  We'll rely
        // on this for sorting when we name the geometry element.
        switch (type) {
            case TopAbs_VERTEX:
                shapetype = 0;
                break;
            case TopAbs_EDGE:
                shapetype = 1;
                break;
            case TopAbs_FACE:
                shapetype = 2;
                break;
            default:
                shapetype = 3;
        }
    }
    bool operator<(const NameKey& other) const
    {
        if (shapetype < other.shapetype) {
            return true;
        }
        if (shapetype > other.shapetype) {
            return false;
        }
        if (tag < other.tag) {
            return true;
        }
        if (tag > other.tag) {
            return false;
        }
        return name < other.name;
    }
};

struct NameInfo
{
    int index {};
    Data::ElementIDRefs sids;
    const char* shapetype {};
};

struct DelayedModifiedEntry
{
    std::vector<std::pair<Data::MappedName, Data::ElementIDRefs>> incomingElementMappedNames;
    Data::IndexedName modifiedElementIndexedName;
    TopoDS_Shape modifiedElement;

    DelayedModifiedEntry(
        std::vector<std::pair<Data::MappedName, Data::ElementIDRefs>> newIncomingElementMappedNames,
        Data::IndexedName newModifiedElementIndexedName,
        TopoDS_Shape newModifiedElement
    )
        : incomingElementMappedNames(newIncomingElementMappedNames)
        , modifiedElementIndexedName(newModifiedElementIndexedName)
        , modifiedElement(newModifiedElement) {};
};

struct NamingMapValue
{
    NamingMapValue() = default;

    std::vector<std::pair<Data::MappedName, Data::ElementIDRefs>> incomingElementMappedNames;
    Data::IndexedName incomingElementIndexName;
    TopoDS_Shape incomingElementShape;
    TopoShape incomingParentShape;
    size_t incomingParentShapeHash;

    bool operator==(const NamingMapValue& other) const
    {
        return other.incomingElementShape.IsSame(incomingElementShape);
    }
};

struct NamingMapKey
{
    NamingMapKey(const TopoDS_Shape& theNewElementShape, const Data::IndexedName& theNewElementName)
        : newElementShape(theNewElementShape)
        , newElementName(theNewElementName) {};

    TopoDS_Shape newElementShape;
    Data::IndexedName newElementName;
};

/** The elements of a result, each with the source elements it was modified or generated from,
 * grouped by those sources.
 *
 * Names are written while iterating the groups, so their order is defined (ops#19, ops#378): the
 * members of a group by type (face, edge, vertex), then in the order they were first added, which
 * is their order in the modified or generated list of their first shared source, the maker's
 * history; the groups in the order of their first members. A member told apart from the others
 * only by its index then gets the same index whatever order OCCT stores the result's sub-shapes
 * in, and keeps it through the edits that leave the maker's lists alone (a rigid motion, a
 * dimension edit, a tilt). The groups' order decides no index (the Connected Name maps are
 * complete before any group is named, and the counters restart per group); it only orders the
 * duplicate counter ElementMap::setElementName gives when two elements get one mapped name. The
 * hash maps here only look up; their hashes are seeded under FREECAD_NAMING_HASH_SEED
 * (NamingHash.h), which must leave the names unchanged.
 */
class NamingMap
{
public:
    /// The members (result elements) of a group, and their shared sources.
    using Group = std::pair<std::vector<NamingMapKey>, std::vector<NamingMapValue>>;

    void add(
        const TopoDS_Shape& newShape,
        Data::IndexedName newShapeIndexName,
        Data::IndexedName mapShapeIndexName,
        const TopoDS_Shape& mapElementShape,
        const std::vector<std::pair<Data::MappedName, Data::ElementIDRefs>>& mapElementMappedNames,
        const TopoShape& incomingShape
    )
    {
        isBuilt = false;
        groups.clear();

        auto res = entryIndex.try_emplace(newShapeIndexName, entries.size());
        if (res.second) {
            entries.emplace_back(
                NamingMapKey {newShape, newShapeIndexName},
                std::vector<NamingMapValue> {}
            );
        }

        NamingMapValue newValue;

        newValue.incomingElementMappedNames = mapElementMappedNames;
        newValue.incomingElementIndexName = mapShapeIndexName;
        newValue.incomingParentShapeHash = shapeHasher(incomingShape.getShape());
        newValue.incomingElementShape = mapElementShape;
        newValue.incomingParentShape = incomingShape;

        entries[res.first->second].second.push_back(newValue);
    };

    void build()
    {
        groups.clear();

        // Members with the same sources (IsSame, in the same order) form a group. The map only
        // finds the groups whose sources hash alike.
        std::unordered_map<std::size_t, std::vector<std::size_t>> groupsBySourcesHash;

        for (const auto& [key, sources] : entries) {
            auto& candidates = groupsBySourcesHash[sourcesHash(sources)];
            auto match = std::find_if(candidates.begin(), candidates.end(), [&](std::size_t groupIdx) {
                return groups[groupIdx].second == sources;
            });

            if (match == candidates.end()) {
                candidates.push_back(groups.size());
                groups.emplace_back(std::vector<NamingMapKey> {key}, sources);
            }
            else {
                groups[*match].first.push_back(key);
            }
        }

        // The members of a group by type; the sort is stable, so within a type they keep the
        // order of their first shared source's list (ops#378). Except vertexes generated along a
        // closed edge: a maker lists them along the edge from its seam, so the list's order
        // turns over when one of them passes the seam (a section's chord end going round a
        // cylinder's circle), and they keep the result's order instead, as before ops#378
        // (fork PR 355 round 3)
        for (auto& group : groups) {
            const bool closedEdgeSource = isClosedEdge(group.second.front().incomingElementShape);
            std::stable_sort(
                group.first.begin(),
                group.first.end(),
                [closedEdgeSource](const NamingMapKey& left, const NamingMapKey& right) {
                    const int typeOrder = typeCompare(left.newElementName, right.newElementName);
                    if (typeOrder != 0) {
                        return typeOrder < 0;
                    }
                    return closedEdgeSource
                        && std::strcmp(left.newElementName.getType(), "Vertex") == 0
                        && left.newElementName.getIndex() < right.newElementName.getIndex();
                }
            );
        }

        isBuilt = true;
    };

    const std::vector<Group>& getGroups()
    {
        if (!isBuilt) {
            build();
        }

        return groups;
    };

private:
    /// Faces, then edges, then vertices (then any other type, by name): below 0 if `left`'s type
    /// comes first, 0 for the same type.
    static int typeCompare(const Data::IndexedName& left, const Data::IndexedName& right)
    {
        auto rank = [](const Data::IndexedName& name) {
            static constexpr std::array<const char*, 3> types {"Face", "Edge", "Vertex"};
            for (std::size_t i = 0; i < types.size(); i++) {
                if (std::strcmp(name.getType(), types[i]) == 0) {
                    return i;
                }
            }
            return types.size();
        };

        const std::size_t leftRank = rank(left);
        const std::size_t rightRank = rank(right);
        if (leftRank != rightRank) {
            return leftRank < rightRank ? -1 : 1;
        }
        return std::strcmp(left.getType(), right.getType());
    }

    /// An edge that starts and ends at the same vertex (a full circle, a closed B-spline)
    static bool isClosedEdge(const TopoDS_Shape& shape)
    {
        if (shape.IsNull() || shape.ShapeType() != TopAbs_EDGE) {
            return false;
        }
        TopoDS_Vertex first;
        TopoDS_Vertex last;
        TopExp::Vertices(TopoDS::Edge(shape), first, last);
        return !first.IsNull() && first.IsSame(last);
    }

    std::size_t sourcesHash(const std::vector<NamingMapValue>& sources) const
    {
        std::size_t hash = sources.size();
        for (const NamingMapValue& source : sources) {
            // The hash combine used by boost. std::hash<TopoDS_Shape> agrees with IsSame.
            hash ^= shapeHasher(source.incomingElementShape) + 0x9e3779b9 + (hash << 6) + (hash >> 2);
        }
        return namingHash(hash);
    }

    /// Result elements with their sources, in the order they were first added.
    std::vector<std::pair<NamingMapKey, std::vector<NamingMapValue>>> entries {};
    std::unordered_map<Data::IndexedName, std::size_t, NamingHasher<Data::IndexedNameHasher>>
        entryIndex {};
    std::vector<Group> groups {};

    std::hash<TopoDS_Shape> shapeHasher;

    bool isBuilt = false;
};


namespace
{
bool holdsInternedName(const std::string& name)
{
    return name.find(Data::NameTable::Marker) != std::string::npos;
}

/// Sorted by the bytes of the expansions, without duplicates. Equal expansions are duplicates
/// whatever their forms; the first of them in the input stays.
void sortByExpansion(std::vector<std::pair<std::string, std::size_t>>& texts)
{
    const auto& table = Data::NameTable::instance();
    std::stable_sort(texts.begin(), texts.end(), [&table](const auto& left, const auto& right) {
        return table.compareExpanded(left.first, right.first) < 0;
    });
    texts.erase(
        std::unique(
            texts.begin(),
            texts.end(),
            [&table](const auto& left, const auto& right) {
                return table.compareExpanded(left.first, right.first) == 0;
            }
        ),
        texts.end()
    );
}
}  // namespace

void sortNameSet(std::vector<Data::MappedName>& names)
{
    static const char marker[] = {Data::NameTable::Marker, 0};
    if (std::ranges::none_of(names, [](const Data::MappedName& name) {
            return name.find(marker) >= 0;
        })) {
        std::sort(names.begin(), names.end());
        names.erase(std::unique(names.begin(), names.end()), names.end());
        return;
    }
    std::vector<std::pair<std::string, std::size_t>> texts;
    texts.reserve(names.size());
    for (std::size_t i = 0; i < names.size(); ++i) {
        texts.emplace_back(names[i].toString(), i);
    }
    sortByExpansion(texts);
    std::vector<Data::MappedName> sorted;
    sorted.reserve(texts.size());
    for (const auto& text : texts) {
        sorted.push_back(names[text.second]);
    }
    names = std::move(sorted);
}

void sortNameSet(std::vector<std::string>& names)
{
    if (std::ranges::none_of(names, holdsInternedName)) {
        std::sort(names.begin(), names.end());
        names.erase(std::unique(names.begin(), names.end()), names.end());
        return;
    }
    std::vector<std::pair<std::string, std::size_t>> texts;
    texts.reserve(names.size());
    for (std::size_t i = 0; i < names.size(); ++i) {
        texts.emplace_back(names[i], i);
    }
    sortByExpansion(texts);
    std::vector<std::string> sorted;
    sorted.reserve(texts.size());
    for (auto& text : texts) {
        sorted.push_back(std::move(text.first));
    }
    names = std::move(sorted);
}

const std::string& modPostfix()
{
    static std::string postfix(Data::POSTFIX_MOD);
    return postfix;
}

const std::string& modgenPostfix()
{
    static std::string postfix(Data::POSTFIX_MODGEN);
    return postfix;
}

const std::string& genPostfix()
{
    static std::string postfix(Data::POSTFIX_GEN);
    return postfix;
}

const std::string& upperPostfix()
{
    static std::string postfix(Data::POSTFIX_UPPER);
    return postfix;
}

const std::string& lowerPostfix()
{
    static std::string postfix(Data::POSTFIX_LOWER);
    return postfix;
}

// TODO: Refactor checkForParallelOrCoplanar to reduce complexity
void checkForParallelOrCoplanar(
    const TopoDS_Shape& newShape,
    const ShapeInfo& newInfo,
    std::vector<TopoDS_Shape>& newShapes,
    const gp_Pln& pln,
    int& parallelFace,
    int& coplanarFace,
    int& checkParallel
)
{
    for (TopExp_Explorer xp(newShape, newInfo.type); xp.More(); xp.Next()) {
        newShapes.push_back(xp.Current());

        if ((parallelFace < 0 || coplanarFace < 0) && checkParallel > 0) {
            // Specialized checking for high level mapped
            // face that are either coplanar or parallel
            // with the source face, which are common in
            // operations like extrusion. Once found, the
            // first coplanar face will assign an index of
            // INT_MIN+1, and the first parallel face
            // INT_MIN. The purpose of these special
            // indexing is to make the name more stable for
            // those generated faces.
            //
            // For example, the top or bottom face of an
            // extrusion will be named using the extruding
            // face. With a fixed index, the name is no
            // longer affected by adding/removing of holes
            // inside the extruding face/sketch.
            gp_Pln plnOther;
            if (TopoShape(newShapes.back()).findPlane(plnOther)) {
                if (pln.Axis().IsParallel(plnOther.Axis(), Precision::Angular())) {
                    if (coplanarFace < 0) {
                        gp_Vec vec(pln.Axis().Location(), plnOther.Axis().Location());
                        Standard_Real D1 = gp_Vec(pln.Axis().Direction()).Dot(vec);
                        if (D1 < 0) {
                            D1 = -D1;
                        }
                        Standard_Real D2 = gp_Vec(plnOther.Axis().Direction()).Dot(vec);
                        if (D2 < 0) {
                            D2 = -D2;
                        }
                        if (D1 <= Precision::Confusion() && D2 <= Precision::Confusion()) {
                            coplanarFace = (int)newShapes.size();
                            continue;
                        }
                    }
                    if (parallelFace < 0) {
                        parallelFace = (int)newShapes.size();
                    }
                }
            }
        }
    }
}

// TODO: Refactor makeShapeWithElementMap to reduce complexity
TopoShape& TopoShape::makeShapeWithElementMap(
    const TopoDS_Shape& shape,
    const Mapper& mapper,
    const std::vector<TopoShape>& shapes,
    const char* op,
    ElementMapPolicy elementMapPolicy
)
{
    ZoneScoped;

    setShape(shape);
    if (shape.IsNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }

    if (elementMapPolicy == ElementMapPolicy::Drop) {
        dropElementNaming();
        return *this;
    }

    if (shapes.empty()) {
        return *this;
    }

    size_t canMap = 0;
    for (auto& incomingShape : shapes) {
        if (canMapElement(incomingShape)) {
            ++canMap;
        }
    }
    if (canMap == 0U) {
        return *this;
    }
    inheritInternNames(*this, shapes);
    if (canMap != shapes.size() && FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
        FC_WARN("Not all input shapes are mappable");  // NOLINT
    }

    if (!op) {
        op = Part::OpCodes::Maker;
    }
    std::string _op = op;
    _op += '_';

    initCache();
    ShapeInfo vertexInfo(_Shape, TopAbs_VERTEX, _cache->getAncestry(TopAbs_VERTEX));
    ShapeInfo edgeInfo(_Shape, TopAbs_EDGE, _cache->getAncestry(TopAbs_EDGE));
    ShapeInfo faceInfo(_Shape, TopAbs_FACE, _cache->getAncestry(TopAbs_FACE));

    std::array<ShapeInfo*, 3> infos = {&vertexInfo, &edgeInfo, &faceInfo};

    std::array<ShapeInfo*, TopAbs_SHAPE> infoMap {};
    infoMap[TopAbs_VERTEX] = &vertexInfo;
    infoMap[TopAbs_EDGE] = &edgeInfo;
    infoMap[TopAbs_WIRE] = &edgeInfo;
    infoMap[TopAbs_FACE] = &faceInfo;
    infoMap[TopAbs_SHELL] = &faceInfo;
    infoMap[TopAbs_SOLID] = &faceInfo;
    infoMap[TopAbs_COMPOUND] = &faceInfo;
    infoMap[TopAbs_COMPSOLID] = &faceInfo;

    const App::HistoryAlgorithm& selectedHistoryVersion = getHistoryAlgorithm();

    if (selectedHistoryVersion == App::HistoryAlgorithm::V1) {
        mapSubElement(shapes);  // Intentionally leave the op off here

        std::ostringstream ss;
        std::string postfix;
        Data::MappedName newName;

        std::map<Data::IndexedName, std::map<NameKey, NameInfo>> newNames;

        // First, collect names from other shapes that generates or modifies the
        // new shape
        for (auto& pinfo : infos) {  // Walk Vertexes, then Edges, then Faces
            auto& info = *pinfo;
            for (const auto& incomingShape : shapes) {
                if (!canMapElement(incomingShape)) {
                    continue;
                }
                auto& otherMap = incomingShape._cache->getAncestry(info.type);
                if (otherMap.empty()) {
                    continue;
                }
                for (int i = 1; i <= otherMap.count(); i++) {
                    const auto& otherElement = otherMap.find(incomingShape._Shape, i);
                    // Find all new objects that are a modification of the old object
                    Data::ElementIDRefs sids;
                    NameKey key(
                        info.type,
                        incomingShape
                            .getMappedName(Data::IndexedName::fromConst(info.shapetype, i), true, &sids)
                    );

                    int newShapeCounter = 0;
                    for (auto& newShape : mapper.modified(otherElement)) {
                        ++newShapeCounter;
                        if (newShape.ShapeType() >= TopAbs_SHAPE) {
                            // NOLINTNEXTLINE
                            FC_ERR(
                                "unknown modified shape type " << newShape.ShapeType() << " from "
                                                               << info.shapetype << i
                            );
                            continue;
                        }
                        auto& newInfo = *infoMap.at(newShape.ShapeType());
                        if (newInfo.type != newShape.ShapeType()) {
                            if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
                                // TODO: it seems modified shape may report higher
                                // level shape type just like generated shape below.
                                // Maybe we shall do the same for name construction.
                                // NOLINTNEXTLINE
                                FC_WARN(
                                    "modified shape type " << shapeName(newShape.ShapeType())
                                                           << " mismatch with " << info.shapetype << i
                                );
                            }
                            continue;
                        }
                        int newShapeIndex = newInfo.find(newShape);
                        if (newShapeIndex == 0) {
                            // This warning occurs in makeElementRevolve. It generates
                            // some shape from a vertex that never made into the
                            // final shape. There may be incomingShape cases there.
                            if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
                                // NOLINTNEXTLINE
                                FC_WARN(
                                    "Cannot find " << op << " modified " << newInfo.shapetype
                                                   << " from " << info.shapetype << i
                                );
                            }
                            continue;
                        }

                        Data::IndexedName element
                            = Data::IndexedName::fromConst(newInfo.shapetype, newShapeIndex);
                        if (getMappedName(element)) {
                            continue;
                        }

                        key.tag = incomingShape.Tag;
                        auto& name_info = newNames[element][key];
                        name_info.sids = sids;
                        name_info.index = newShapeCounter;
                        name_info.shapetype = info.shapetype;
                    }

                    int checkParallel = -1;
                    gp_Pln pln;

                    // Find all new objects that were generated from an old object
                    // (e.g. a face generated from an edge)
                    newShapeCounter = 0;
                    for (auto& newShape : mapper.generated(otherElement)) {
                        if (newShape.ShapeType() >= TopAbs_SHAPE) {
                            // NOLINTNEXTLINE
                            FC_ERR(
                                "unknown generated shape type " << newShape.ShapeType() << " from "
                                                                << info.shapetype << i
                            );
                            continue;
                        }

                        int parallelFace = -1;
                        int coplanarFace = -1;
                        auto& newInfo = *infoMap.at(newShape.ShapeType());
                        std::vector<TopoDS_Shape> newShapes;
                        int shapeOffset = 0;
                        if (newInfo.type == newShape.ShapeType()) {
                            newShapes.push_back(newShape);
                        }
                        else {
                            // It is possible for the maker to report generating a
                            // higher level shape, such as shell or solid. For
                            // example, when extruding, OCC will report the
                            // extruding face generating the entire solid. However,
                            // it will also report the edges of the extruding face
                            // generating the side faces. In this case, too much
                            // information is bad for us. We don't want the name of
                            // the side face (and its edges) to be coupled with
                            // incomingShape (unrelated) edges in the extruding face.
                            //
                            // shapeOffset below is used to make sure the higher
                            // level mapped names comes late after sorting. We'll
                            // ignore those names if there are more precise mapping
                            // available.
                            shapeOffset = 3;

                            if (info.type == TopAbs_FACE && checkParallel < 0) {
                                if (!TopoShape(otherElement).findPlane(pln)) {
                                    checkParallel = 0;
                                }
                                else {
                                    checkParallel = 1;
                                }
                            }
                            checkForParallelOrCoplanar(
                                newShape,
                                newInfo,
                                newShapes,
                                pln,
                                parallelFace,
                                coplanarFace,
                                checkParallel
                            );
                        }
                        key.shapetype += shapeOffset;
                        for (auto& workingShape : newShapes) {
                            ++newShapeCounter;
                            int workingShapeIndex = newInfo.find(workingShape);
                            if (workingShapeIndex == 0) {
                                if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
                                    // NOLINTNEXTLINE
                                    FC_WARN(
                                        "Cannot find " << op << " generated " << newInfo.shapetype
                                                       << " from " << info.shapetype << i
                                    );
                                }
                                continue;
                            }

                            Data::IndexedName element
                                = Data::IndexedName::fromConst(newInfo.shapetype, workingShapeIndex);
                            auto mapped = getMappedName(element);
                            if (mapped) {
                                continue;
                            }

                            key.tag = incomingShape.Tag;
                            auto& name_info = newNames[element][key];
                            name_info.sids = sids;
                            if (newShapeCounter == parallelFace) {
                                name_info.index = std::numeric_limits<int>::min();
                            }
                            else if (newShapeCounter == coplanarFace) {
                                name_info.index = std::numeric_limits<int>::min() + 1;
                            }
                            else {
                                name_info.index = -newShapeCounter;
                            }
                            name_info.shapetype = info.shapetype;
                        }
                        key.shapetype -= shapeOffset;
                    }
                }
            }
        }

        // We shall first exclude those names generated from high level mapping. If
        // there are still any unnamed elements left after we go through the process
        // below, we set delayed=true, and start using those excluded names.
        bool delayed = false;

        while (true) {
            constexpr int intMin = std::numeric_limits<int>::min();

            // Construct the names for modification/generation info collected in
            // the previous step
            for (auto itName = newNames.begin(), itNext = itName; itNext != newNames.end();
                 itName = itNext) {
                // We treat the first modified/generated source shape name specially.
                // If case there are more than one source shape. We hash the first
                // source name separately, and then obtain the second string id by
                // hashing all the source names together.  We then use the second
                // string id as the postfix for our name.
                //
                // In this way, we can associate the same source that are modified by
                // multiple other shapes.

                ++itNext;

                auto& element = itName->first;
                auto& names = itName->second;
                const auto& first_key = names.begin()->first;
                auto& first_info = names.begin()->second;

                if (!delayed && first_key.shapetype >= 3 && first_info.index > intMin + 1) {
                    // This name is mapped from high level (shell, solid, etc.)
                    // Delay till next round.
                    //
                    // index>INT_MAX+1 is for checking generated coplanar and
                    // parallel face mapping, which has special fixed index to make
                    // name stable.  These names are not delayed.
                    continue;
                }
                if (!delayed && getMappedName(element)) {
                    newNames.erase(itName);
                    continue;
                }

                int name_type = first_info.index > 0 ? 1 : 2;  // index>0 means modified, or else
                                                               // generated
                Data::MappedName first_name = first_key.name;

                Data::ElementIDRefs sids(first_info.sids);

                postfix.clear();
                if (names.size() > 1) {
                    ss.str("");
                    ss << '(';
                    bool first = true;
                    auto it = names.begin();
                    int count = 0;
                    for (++it; it != names.end(); ++it) {
                        auto& other_key = it->first;
                        if (other_key.shapetype >= 3 && first_key.shapetype < 3) {
                            // shapetype>=3 means it's a high level mapping (e.g. a face
                            // generates a solid). We don't want that if there are more
                            // precise low level mapping available. See comments above
                            // for more details.
                            break;
                        }
                        if (first) {
                            first = false;
                        }
                        else {
                            ss << '|';
                        }
                        auto& other_info = it->second;
                        std::ostringstream ss2;
                        if (other_info.index != 1) {
                            // 'K' marks the additional source shape of this
                            // generate (or modified) shape.
                            ss2 << elementMapPrefix() << 'K';
                            if (other_info.index == intMin) {
                                ss2 << '0';
                            }
                            else if (other_info.index == intMin + 1) {
                                ss2 << "00";
                            }
                            else {
                                // The same source shape may generate or modify
                                // more than one shape. The index here marks the
                                // position it is reported by OCC. Including the
                                // index here is likely to degrade name stablilty,
                                // but is unfortunately a necessity to avoid
                                // duplicate names.
                                ss2 << other_info.index;
                            }
                        }
                        Data::MappedName other_name = other_key.name;

                        ensureElementMap()->encodeElementName(
                            *other_info.shapetype,
                            other_name,
                            ss2,
                            &sids,
                            Tag,
                            nullptr,
                            other_key.tag
                        );
                        ss << other_name;
                        if ((name_type == 1 && other_info.index < 0)
                            || (name_type == 2 && other_info.index > 0)) {
                            if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
                                FC_WARN("element is both generated and modified");  // NOLINT
                            }
                            name_type = 0;
                        }
                        sids += other_info.sids;
                        // To avoid the name becoming to long, just put some limit here
                        if (++count == 4) {
                            break;
                        }
                    }
                    if (!first) {
                        ss << ')';
                        if (Hasher) {
                            sids.push_back(Hasher->getID(ss.str().c_str()));
                            ss.str("");
                            ss << sids.back().toString();
                        }
                        postfix = ss.str();
                    }
                }

                ss.str("");
                if (name_type == 2) {
                    ss << genPostfix();
                }
                else if (name_type == 1) {
                    ss << modPostfix();
                }
                else {
                    ss << modgenPostfix();
                }
                if (first_info.index == intMin) {
                    ss << '0';
                }
                else if (first_info.index == intMin + 1) {
                    ss << "00";
                }
                else if (abs(first_info.index) > 1) {
                    ss << abs(first_info.index);
                }
                ss << postfix;

                ensureElementMap()
                    ->encodeElementName(element[0], first_name, ss, &sids, Tag, op, first_key.tag);
                elementMap()->setElementName(element, first_name, Tag, &sids);
                if (!delayed && first_key.shapetype < 3) {
                    newNames.erase(itName);
                }
            }

            // The reverse pass. Starting from the highest level element, i.e.
            // Face, for any element that are named, assign names for its lower unnamed
            // elements. For example, if Edge1 is named E1, and its vertexes are not
            // named, then name them as E1;U1, E1;U2, etc.
            //
            // In order to make the name as stable as possible, we may assign multiple
            // names (which must be sorted, because we may use the first one to name
            // upper element in the final pass) to lower element if it appears in
            // multiple higher elements, e.g. same edge in multiple faces.

            for (size_t infoIndex = infos.size() - 1; infoIndex != 0; --infoIndex) {
                std::map<Data::IndexedName, std::map<Data::MappedName, NameInfo, Data::ElementNameComparator>>
                    names;
                auto& info = *infos.at(infoIndex);
                auto& next = *infos.at(infoIndex - 1);
                int elementCounter = 1;
                auto it = newNames.end();
                if (delayed) {
                    it = newNames.upper_bound(Data::IndexedName::fromConst(info.shapetype, 0));
                }
                for (;; ++elementCounter) {
                    Data::IndexedName element;
                    if (!delayed) {
                        if (elementCounter > info.count()) {
                            break;
                        }
                        element = Data::IndexedName::fromConst(info.shapetype, elementCounter);
                        if (newNames.count(element) != 0U) {
                            continue;
                        }
                    }
                    else if (
                        it == newNames.end()
                        || !boost::starts_with(it->first.getType(), info.shapetype)
                    ) {
                        break;
                    }
                    else {
                        element = it->first;
                        ++it;
                        elementCounter = element.getIndex();
                        if (elementCounter == 0 || elementCounter > info.count()) {
                            continue;
                        }
                    }
                    Data::ElementIDRefs sids;
                    Data::MappedName mapped = getMappedName(element, false, &sids);
                    if (!mapped) {
                        continue;
                    }

                    TopTools_IndexedMapOfShape submap;
                    TopExp::MapShapes(info.find(elementCounter), next.type, submap);
                    for (int submapIndex = 1, infoCounter = 1; submapIndex <= submap.Extent();
                         ++submapIndex) {
                        ss.str("");
                        int elementIndex = next.find(submap(submapIndex));
                        assert(elementIndex);
                        Data::IndexedName indexedName
                            = Data::IndexedName::fromConst(next.shapetype, elementIndex);
                        if (getMappedName(indexedName)) {
                            continue;
                        }
                        auto& infoRef = names[indexedName][mapped];
                        infoRef.index = infoCounter++;
                        infoRef.sids = sids;
                    }
                }
                // Assign the actual names
                for (auto& [indexedName, nameInfoMap] : names) {
                    // Do we really want multiple names for an element in this case?
                    // If not, we just pick the name in the first sorting order here.
                    auto& nameInfoMapEntry = *nameInfoMap.begin();
                    {
                        auto& nameInfo = nameInfoMapEntry.second;
                        auto& sids = nameInfo.sids;
                        newName = nameInfoMapEntry.first;
                        ss.str("");
                        ss << upperPostfix();
                        if (nameInfo.index > 1) {
                            ss << nameInfo.index;
                        }

                        ensureElementMap()
                            ->encodeElementName(indexedName[0], newName, ss, &sids, Tag, op);
                        elementMap()->setElementName(indexedName, newName, Tag, &sids);
                    }
                }
            }

            // The forward pass. For any elements that are not named, try construct its
            // name from the lower elements
            bool hasUnnamed = false;
            for (size_t ifo = 1; ifo < infos.size(); ++ifo) {
                auto& info = *infos.at(ifo);
                auto& prev = *infos.at(ifo - 1);
                for (int i = 1; i <= info.count(); ++i) {
                    Data::IndexedName element = Data::IndexedName::fromConst(info.shapetype, i);
                    if (getMappedName(element)) {
                        continue;
                    }

                    Data::ElementIDRefs sids;
                    std::map<Data::MappedName, Data::IndexedName, Data::ElementNameComparator> names;
                    TopExp_Explorer xp;
                    if (info.type == TopAbs_FACE) {
                        xp.Init(BRepTools::OuterWire(TopoDS::Face(info.find(i))), TopAbs_EDGE);
                    }
                    else {
                        xp.Init(info.find(i), prev.type);
                    }
                    for (; xp.More(); xp.Next()) {
                        int previousElementIndex = prev.find(xp.Current());
                        assert(previousElementIndex);
                        Data::IndexedName prevElement
                            = Data::IndexedName::fromConst(prev.shapetype, previousElementIndex);
                        if (!delayed && (newNames.count(prevElement) != 0U)) {
                            names.clear();
                            break;
                        }
                        Data::ElementIDRefs sid;
                        Data::MappedName name = getMappedName(prevElement, false, &sid);
                        if (!name) {
                            // only assign name if all lower elements are named
                            if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
                                FC_WARN("unnamed lower element " << prevElement);  // NOLINT
                            }
                            names.clear();
                            break;
                        }
                        auto res = names.emplace(name, prevElement);
                        if (res.second) {
                            sids += sid;
                        }
                        else if (prevElement != res.first->second) {
                            // The seam edge will appear twice, which is normal. We
                            // only warn if the mapped element names are different.
                            // NOLINTNEXTLINE
                            FC_WARN(
                                "lower element " << prevElement << " and " << res.first->second
                                                 << " has duplicated name " << name << " for "
                                                 << info.shapetype << i
                            );
                        }
                    }
                    if (names.empty()) {
                        hasUnnamed = true;
                        continue;
                    }
                    auto it = names.begin();
                    newName = it->first;
                    if (names.size() == 1) {
                        ss << lowerPostfix();
                    }
                    else {
                        bool first = true;
                        ss.str("");
                        if (!Hasher) {
                            ss << lowerPostfix();
                        }
                        ss << '(';
                        int count = 0;
                        for (++it; it != names.end(); ++it) {
                            if (first) {
                                first = false;
                            }
                            else {
                                ss << '|';
                            }
                            ss << it->first;

                            // To avoid the name becoming to long, just put some limit here
                            if (++count == 4) {
                                break;
                            }
                        }
                        ss << ')';
                        if (Hasher) {
                            sids.push_back(Hasher->getID(ss.str().c_str()));
                            ss.str("");
                            ss << lowerPostfix() << sids.back().toString();
                        }
                    }

                    ensureElementMap()->encodeElementName(element[0], newName, ss, &sids, Tag, op);
                    elementMap()->setElementName(element, newName, Tag, &sids);
                }
            }
            if (!hasUnnamed || delayed || newNames.empty()) {
                break;
            }
            delayed = true;
        }
    }
    else if (selectedHistoryVersion == App::HistoryAlgorithm::V2) {
        // The order rule (ops#19): a loop that writes names iterates in a defined order (the
        // inputs' order, the result's index order, or byte order of names). Hash containers only
        // look up, count or group. A list field that holds a set of names (Linked Names,
        // Connected Names) is sorted by bytes and has no duplicates.
        constexpr int MAXIMUM_REMAPPED_INCOMING_NAMES = 3;

        std::hash<TopoDS_Shape> shapeHasher;
        IncludedNameMap includedModifiedNameMap;
        mapSubElement(shapes, nullptr, &includedModifiedNameMap);  // Intentionally leave the op off here

        // This algorithm has some edgecase detection from the V1 Algorithm, which is why it looks a
        // little bit copypasted.
        // The frame of the shape being named, which its own location (e.g. a Part feature's
        // placement) doesn't move: the fallback lists' order keys end with coordinates taken
        // there (ops#378).
        const TopLoc_Location frame = _Shape.Location().Inverted();
        NamingMap generatedNamingMap;
        NamingMap modifiedNamingMap;

        const std::map<std::string, TopAbs_ShapeEnum> upperMapTypes {
            {"Edge", TopAbs_FACE},
            {"Face", TopAbs_EDGE},
            {"Vertex", TopAbs_FACE}
        };
        const std::map<std::string, TopAbs_ShapeEnum> lowerMapTypes {
            {"Edge", TopAbs_VERTEX},
            {"Face", TopAbs_EDGE}
        };
        // Used by the last fallback only, when no ancestor of the upperMapTypes type is named
        const std::map<std::string, TopAbs_ShapeEnum> secondUpperMapTypes {
            {"Vertex", TopAbs_EDGE}
        };

        long masterTag = Tag;

        if (masterTag == 0) {
            for (const auto& incomingShape : shapes) {
                if (incomingShape.Tag != 0) {
                    masterTag = incomingShape.Tag;
                    break;
                }
            }
            // A document feature should build its result with its own tag
            // (Part::Feature::makeTopoShape). If one doesn't, its own sections carry an
            // input's tag (ops#32): log it, so such a site shows up.
            if (masterTag != 0 && FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
                const auto documents = App::GetApplication().getDocuments();
                if (std::ranges::any_of(documents, [](const App::Document* document) {
                        return document->testStatus(App::Document::Recomputing);
                    })) {
                    FC_LOG("V2 result without a tag during a recompute, op " << op
                           << ": its sections take the input tag " << masterTag);
                }
            }
        }

        std::unordered_multiset<Data::MappedName, Data::MappedNameHasher> usedProjectedLinkedNames;
        // The projected elements without marks or a counter, named from their source's front name
        // alone, in the order they were named: the projections of one front name are twins, and
        // once all are known get the count into their names (I-A2, below the loop)
        struct ProjectedPiece
        {
            Data::IndexedName element;
            TopoDS_Shape shape;
            TopoDS_Shape source;
            Data::MappedName frontName;
            Data::MappedName given;  ///< the name it was given in the loop
            std::vector<std::string> flags;
        };
        std::vector<ProjectedPiece> projectedPieces;
        std::unordered_set<Data::IndexedName, Data::IndexedNameHasher> allGeneratedShapes;

        // A far cap that is one of several pieces of its profile face's cap is told apart by its
        // marks, the inputs' elements that bound it, as a modified element by its neighbours
        // (ops#360, PR 340 round 1), and pieces with the same marks by the duplicate counter
        // (round 2). Its section carries MOD with PRJ: a reference to a piece is
        // not the cap in one piece that an edit leaves, nor the other way round (the solver's
        // top agreement compares the flags), as a split face's piece isn't the face made whole.
        // The same for a piece of a far edge the up-to shape cuts (ops#386)
        const auto* upToSplit = dynamic_cast<const UpToSplitMapper*>(&mapper);
        // The front name of an input's element, as the loop below reads it
        auto inputName = [&](const TopoDS_Shape& element) {
            for (const auto& incomingShape : shapes) {
                int index = canMapElement(incomingShape) ? incomingShape.findShape(element) : 0;
                if (index == 0) {
                    continue;
                }
                const std::string& type = shapeName(element.ShapeType());
                Data::IndexedName name = Data::IndexedName::fromConst(type.c_str(), index);
                Data::MappedName mapped = incomingShape.getMappedName(name);
                if (!mapped) {
                    mapped = Data::MappedName::makeUnmappedName(
                        {name.toString()},
                        incomingShape.Tag,
                        op,
                        type[0]
                    );
                }
                if (incomingShape.getInternNames() != getInternNames()) {
                    mapped = toMapForm(mapped, getInternNames());
                }
                return mapped;
            }
            return Data::MappedName();
        };

        // These loops generate names with the Modified and Generated methods of the Maker class.
        // This will miss some shapes, so in the next stage we will find names with the IsPartner method.
        for (auto& info : infos) {
            std::string stringSubshapeType {info->shapetype};

            for (const auto& incomingShape : shapes) {
                size_t incomingShapeHash = shapeHasher(incomingShape.getShape());

                if (!canMapElement(incomingShape)) {
                    continue;
                }

                auto& otherMap = incomingShape._cache->getAncestry(info->type);
                if (otherMap.empty()) {
                    continue;
                }

                for (int i = 1; i <= otherMap.count(); i++) {
                    const auto& incomingShapeElement = otherMap.find(incomingShape._Shape, i);
                    Data::IndexedName incomingShapeElementIndexedName
                        = Data::IndexedName::fromConst(info->shapetype, i);
                    auto incomingShapeElementMappedNames = incomingShape.getElementMappedNames(
                        incomingShapeElementIndexedName
                    );

                    if (incomingShapeElementMappedNames.empty()) {
                        incomingShapeElementMappedNames.push_back(
                            {Data::MappedName::makeUnmappedName(
                                 {incomingShapeElementIndexedName.toString()},
                                 incomingShape.Tag,
                                 op,
                                 (*incomingShapeElementIndexedName.getType())
                             ),
                             {}}
                        );
                    }
                    // In the result's form, as the seed's name map records them
                    toMapForm(incomingShapeElementMappedNames, incomingShape, *this);

                    // Use copies here, because if we store a reference to `modified`, then call the
                    // `generated` method, the `modified` reference will change to the `generated`
                    // values.
                    std::vector<TopoDS_Shape> modifiedShapes = mapper.modified(incomingShapeElement);
                    std::vector<TopoDS_Shape> generatedShapes = mapper.generated(incomingShapeElement);
                    std::vector<TopoDS_Shape> projectedShapes = mapper.projected(incomingShapeElement);

                    size_t modifiedShapesSize = modifiedShapes.size();

                    for (size_t modifiedI = 0; modifiedI < modifiedShapesSize; modifiedI++) {
                        auto& modifiedShape = modifiedShapes[modifiedI];

                        if (modifiedShape.ShapeType() >= TopAbs_SHAPE) {
                            continue;
                        }

                        auto& newInfo = *infoMap.at(modifiedShape.ShapeType());
                        if (newInfo.type != modifiedShape.ShapeType()) {
                            continue;
                        }

                        int modifiedShapeIndex = newInfo.find(modifiedShape);
                        if (modifiedShapeIndex == 0) {
                            continue;
                        }

                        Data::IndexedName element
                            = Data::IndexedName::fromConst(newInfo.shapetype, modifiedShapeIndex);

                        includedModifiedNameMap[modifiedShape]
                            = {incomingShapeHash, incomingShapeElementMappedNames.front().first};

                        if (modifiedShapesSize == 1) {
                            // Since indexed names can have multiple MappedNames assigned to them,
                            // we want to make sure we include as many as three of them in the new
                            // ElementMap for reliability sake.
                            for (size_t incomingMappedNameIdx = 0;
                                 (incomingMappedNameIdx < incomingShapeElementMappedNames.size()
                                  && incomingMappedNameIdx < MAXIMUM_REMAPPED_INCOMING_NAMES);
                                 incomingMappedNameIdx++) {
                                ensureElementMap()->setElementName(
                                    element,
                                    incomingShapeElementMappedNames[incomingMappedNameIdx].first,
                                    masterTag
                                );
                            }
                        }
                        else {
                            modifiedNamingMap.add(
                                modifiedShape,
                                element,
                                incomingShapeElementIndexedName,
                                incomingShapeElement,
                                incomingShapeElementMappedNames,
                                incomingShape
                            );
                        }
                    }

                    for (size_t projectedI = 0; projectedI < projectedShapes.size(); projectedI++) {
                        auto& projectedShape = projectedShapes[projectedI];

                        if (projectedShape.ShapeType() >= TopAbs_SHAPE) {
                            continue;
                        }

                        auto& newInfo = *infoMap.at(projectedShape.ShapeType());
                        if (newInfo.type != projectedShape.ShapeType()) {
                            continue;
                        }

                        int projectedShapeIndex = newInfo.find(projectedShape);

                        if (projectedShapeIndex == 0) {
                            continue;
                        }

                        Data::IndexedName element
                            = Data::IndexedName::fromConst(newInfo.shapetype, projectedShapeIndex);

                        if (getMappedName(element)) {
                            // A face of the up-to shape that the split leaves whole is a far cap
                            // all the same: it has the face's name from mapSubElement, which
                            // stood for a piece of another cap once the piece grew to cover the
                            // face (ops#360, PR 340 round 2)
                            if (!upToSplit || !upToSplit->isFarCap(projectedShape)) {
                                continue;
                            }
                            ensureElementMap()->erase(element);
                        }

                        const Data::MappedName& frontName = incomingShapeElementMappedNames.front().first;

                        std::vector<Data::MappedName> marks;
                        if (upToSplit) {
                            for (const TopoDS_Shape& mark : upToSplit->marksOf(projectedShape)) {
                                if (Data::MappedName name = inputName(mark)) {
                                    marks.push_back(name);
                                }
                            }
                            sortNameSet(marks);
                        }
                        // A marked piece's marks tell it apart, or with them the duplicate
                        // counter the mapper gives it (round 2): its index is 0
                        const auto index = static_cast<int>(
                            marks.empty() ? usedProjectedLinkedNames.count(frontName) : 0
                        );
                        const int counter = upToSplit ? upToSplit->counterOf(projectedShape) : 0;
                        std::vector<std::string> flags {Data::MAPPER_FLAG_PROJECTION};
                        if (!marks.empty()) {
                            flags.emplace_back(Data::MAPPER_FLAG_MODIFIED);
                        }
                        // A piece told apart only by its place among its twins: a reference to
                        // it never goes, at the solver's tier 1, to a piece that isn't one (the
                        // bottom twin left alone when the top one goes), since the top sections'
                        // flags disagree (round 2)
                        if (counter != 0) {
                            flags.emplace_back(Data::MAPPER_FLAG_ORDERED);
                        }

                        const Data::MappedName given = ensureElementMap()->setElementName(
                            element,
                            Data::MappedName(
                                Data::MappedName::makeEncodedSection(
                                    {},
                                    {frontName},
                                    masterTag,
                                    op,
                                    index,
                                    newInfo.shapetype[0],
                                    counter,
                                    flags,
                                    marks
                                )
                            ),
                            masterTag
                        );

                        if (marks.empty()) {
                            usedProjectedLinkedNames.insert(frontName);
                            if (counter == 0) {
                                projectedPieces.push_back(
                                    {element, projectedShape, incomingShapeElement, frontName, given, flags}
                                );
                            }
                        }
                    }

                    for (size_t generatedI = 0; generatedI < generatedShapes.size(); generatedI++) {
                        const TopoDS_Shape& generatedShape = generatedShapes[generatedI];

                        if (generatedShape.ShapeType() >= TopAbs_SHAPE) {
                            continue;
                        }

                        auto& newInfo = *infoMap.at(generatedShape.ShapeType());
                        if (newInfo.type != generatedShape.ShapeType()) {
                            continue;
                        }

                        int generatedShapeIndex = newInfo.find(generatedShape);
                        if (generatedShapeIndex == 0) {
                            continue;
                        }

                        Data::IndexedName generatedShapeIndexedName
                            = Data::IndexedName::fromConst(newInfo.shapetype, generatedShapeIndex);

                        if (getMappedName(generatedShapeIndexedName)) {
                            continue;
                        }

                        generatedNamingMap.add(
                            generatedShape,
                            generatedShapeIndexedName,
                            incomingShapeElementIndexedName,
                            incomingShapeElement,
                            incomingShapeElementMappedNames,
                            incomingShape
                        );

                        std::string otherElementMapName
                            = incomingShape.getMappedName(incomingShapeElementIndexedName).toString();

                        allGeneratedShapes.insert(generatedShapeIndexedName);
                    }
                }
            }
        }

        // The projections of one front name without marks (a far cap split by a seam the refine
        // doesn't join, ops#386) are twins: in twinOrder's order on their source, Index `0`, with
        // the count in DuplicateCount and ORD, as the generated and modified stages' twins (the
        // size rule, I-A2). Named in the loop with their arrival count, so that the stages after
        // see them named; renamed here, the element's other names kept in their order.
        {
            std::vector<std::vector<std::size_t>> twins;
            std::unordered_map<Data::MappedName, std::size_t, Data::MappedNameHasher> twinsOf;
            for (std::size_t i = 0; i < projectedPieces.size(); ++i) {
                auto found = twinsOf.try_emplace(projectedPieces[i].frontName, twins.size());
                if (found.second) {
                    twins.emplace_back();
                }
                twins[found.first->second].push_back(i);
            }
            for (const auto& group : twins) {
                if (group.size() < 2) {
                    continue;
                }
                std::vector<TopoDS_Shape> shapes;
                for (std::size_t i : group) {
                    shapes.push_back(projectedPieces[i].shape);
                }
                const std::vector<std::size_t> order
                    = twinOrder(shapes, {projectedPieces[group.front()].source}, frame);
                const std::vector<TwinPlace> places = twinPlaces(order.size());
                for (std::size_t k = 0; k < order.size(); ++k) {
                    const ProjectedPiece& piece = projectedPieces[group[order[k]]];
                    std::vector<std::string> flags = piece.flags;
                    if (places[k].ordered) {
                        flags.emplace_back(Data::MAPPER_FLAG_ORDERED);
                    }
                    const Data::MappedName renamed(Data::MappedName::makeEncodedSection(
                        {},
                        std::vector<Data::MappedName> {piece.frontName},
                        std::to_string(static_cast<int>(masterTag)),
                        op,
                        places[k].index,
                        piece.element.getType()[0],
                        places[k].duplicateCount,
                        flags,
                        std::vector<Data::MappedName> {}
                    ));
                    auto names = getElementMappedNames(piece.element);
                    ensureElementMap()->erase(piece.element);
                    for (auto& [name, sids] : names) {
                        ensureElementMap()->setElementName(
                            piece.element,
                            name == piece.given ? renamed : name,
                            masterTag,
                            &sids
                        );
                    }
                }
            }
        }

        modifiedNamingMap.build();

        std::vector<std::pair<const Data::IndexedName*, std::vector<const Data::MappedName*>>>
            modifiedConnectedElementVector;
        // Counted by name, not by where the name is kept: two faces with one name are one name,
        // which tells no piece apart (ops#431). Only looked up, never iterated.
        std::unordered_map<Data::MappedName, unsigned int, Data::MappedNameHasher>
            allModifiedConnectedElementNames;

        // NamingMap::Group: pair<std::vector<NamingMapKey>, std::vector<NamingMapValue>>
        for (const auto& modifiedShapeEntry : modifiedNamingMap.getGroups()) {
            if (modifiedShapeEntry.second.size() != 1) {
                continue;
            }

            const NamingMapValue& mapValue = modifiedShapeEntry.second.front();
            const auto& incomingElementMappedNames = mapValue.incomingElementMappedNames;

            auto lowerMapTypeEntry = lowerMapTypes.find(
                modifiedShapeEntry.first.front().newElementName.getType()
            );

            auto upperMapTypeEntry = upperMapTypes.find(
                modifiedShapeEntry.first.front().newElementName.getType()
            );

            if (lowerMapTypeEntry != lowerMapTypes.end() && upperMapTypeEntry != upperMapTypes.end()) {
                ShapeInfo* upperMap = infoMap[upperMapTypeEntry->second];

                for (const Part::NamingMapKey& elementKey : modifiedShapeEntry.first) {
                    TopTools_IndexedMapOfShape lowerMap;
                    TopExp::MapShapes(elementKey.newElementShape, lowerMapTypeEntry->second, lowerMap);

                    std::unordered_set<Data::MappedName, Data::MappedNameHasher> connectedElementsSet;
                    std::vector<const Data::MappedName*> connectedElements;

                    for (int lowerIdx = 1; lowerIdx <= lowerMap.Extent(); lowerIdx++) {
                        std::vector<const Data::MappedName*> foundNames;
                        const TopoDS_Shape& lowerShape = lowerMap(lowerIdx);
                        auto lowerModifiedShapeMapIterator = includedModifiedNameMap.find(lowerShape);

                        // check to see if the lower element was directly included in one of the
                        // incoming shapes
                        if (lowerModifiedShapeMapIterator != includedModifiedNameMap.end()) {
                            foundNames.push_back(&lowerModifiedShapeMapIterator->second.second);
                        }

                        if (upperMap != nullptr) {
                            const std::vector<int> ancestors
                                = findAncestors(lowerShape, upperMapTypeEntry->second);

                            // One upper name per lower element, to keep names short: of the
                            // ancestors named from another input, the smallest name in
                            // sortNameSet's order, never the first in the result's order of
                            // its faces, which OCCT may store in another order (ops#431)
                            std::vector<const Data::MappedName*> qualifying;
                            for (const int& ancestorIdx : ancestors) {
                                const TopoDS_Shape& ancestor = upperMap->find(ancestorIdx);
                                auto upperModifiedShapeMapIterator = includedModifiedNameMap.find(
                                    ancestor
                                );

                                if (upperModifiedShapeMapIterator != includedModifiedNameMap.end()
                                    && upperModifiedShapeMapIterator->second.first
                                        != mapValue.incomingParentShapeHash) {
                                    qualifying.push_back(&upperModifiedShapeMapIterator->second.second);
                                }
                            }
                            if (!qualifying.empty()) {
                                std::vector<Data::MappedName> sorted;
                                for (const Data::MappedName* name : qualifying) {
                                    sorted.push_back(*name);
                                }
                                sortNameSet(sorted);
                                foundNames.push_back(*std::find_if(
                                    qualifying.begin(),
                                    qualifying.end(),
                                    [&sorted](const Data::MappedName* name) {
                                        return *name == sorted.front();
                                    }
                                ));
                            }
                        }

                        for (const Data::MappedName* foundName : foundNames) {
                            if (foundName != nullptr && connectedElementsSet.count(*foundName) == 0) {
                                connectedElementsSet.insert(*foundName);
                                connectedElements.push_back(foundName);

                                auto allConnectedElementIterator
                                    = allModifiedConnectedElementNames.try_emplace(*foundName, 0);

                                if (!allConnectedElementIterator.second) {
                                    allConnectedElementIterator.first->second += 1;
                                }
                            }
                        }
                    }

                    modifiedConnectedElementVector.emplace_back(
                        &elementKey.newElementName,
                        connectedElements
                    );
                }

                // Each piece's Connected Names that no other piece has. The pieces left without
                // any are told apart by their place among the group's pieces of their type: in
                // twinOrder's order on the source, with the count (the size rule, I-A2), and with
                // ORD; a lone one `0`, as before.
                std::vector<std::vector<Data::MappedName>> filteredConnectedElementsOf(
                    modifiedConnectedElementVector.size()
                );
                std::map<char, std::vector<std::size_t>> placedMembers;
                for (std::size_t i = 0; i < modifiedConnectedElementVector.size(); ++i) {
                    auto& filtered = filteredConnectedElementsOf[i];
                    for (const Data::MappedName* name : modifiedConnectedElementVector[i].second) {
                        auto allConnectedElementIterator = allModifiedConnectedElementNames.find(*name);

                        if (allConnectedElementIterator != allModifiedConnectedElementNames.end()
                            && allConnectedElementIterator->second == 0) {
                            filtered.push_back(*name);
                        }
                    }
                    if (filtered.empty()) {
                        placedMembers[*modifiedConnectedElementVector[i].first->getType()].push_back(i);
                    }
                    else {
                        sortNameSet(filtered);
                    }
                }
                std::vector<TwinPlace> places(modifiedConnectedElementVector.size());
                for (const auto& [type, indexes] : placedMembers) {
                    std::vector<TopoDS_Shape> shapes;
                    for (std::size_t i : indexes) {
                        shapes.push_back(modifiedShapeEntry.first[i].newElementShape);
                    }
                    const std::vector<std::size_t> order
                        = twinOrder(shapes, {mapValue.incomingElementShape}, frame);
                    const std::vector<TwinPlace> typePlaces = twinPlaces(order.size());
                    for (std::size_t k = 0; k < order.size(); ++k) {
                        places[indexes[order[k]]] = typePlaces[k];
                    }
                }

                for (std::size_t entry = 0; entry < modifiedConnectedElementVector.size(); ++entry) {
                    const auto& modifiedConnectedElementEntry = modifiedConnectedElementVector[entry];
                    const std::vector<Data::MappedName>& filteredConnectedElements
                        = filteredConnectedElementsOf[entry];
                    const TwinPlace& place = places[entry];
                    std::vector<std::string> flags {Data::MAPPER_FLAG_MODIFIED};
                    if (place.ordered) {
                        flags.emplace_back(Data::MAPPER_FLAG_ORDERED);
                    }

                    // Since indexed names can have multiple MappedNames assigned to them,
                    // we want to make sure we include as many as three of them in the new
                    // ElementMap for reliability sake.
                    for (size_t incomingMappedNameIdx = 0;
                         (incomingMappedNameIdx < incomingElementMappedNames.size()
                          && incomingMappedNameIdx < MAXIMUM_REMAPPED_INCOMING_NAMES);
                         incomingMappedNameIdx++) {
                        Data::MappedName newName {
                            incomingElementMappedNames[incomingMappedNameIdx].first
                        };

                        newName.append(Data::NAME_SECTION_DELIMINATOR);
                        newName.append(
                            Data::MappedName::makeEncodedSection(
                                {},
                                std::vector<Data::MappedName> {},
                                std::to_string(static_cast<int>(masterTag)),
                                op,
                                place.index,
                                modifiedConnectedElementEntry.first->getType()[0],
                                place.duplicateCount,
                                flags,
                                filteredConnectedElements
                            )
                                .c_str()
                        );

                        ensureElementMap()->setElementName(
                            *modifiedConnectedElementEntry.first,
                            newName,
                            masterTag
                        );
                    }
                }

                modifiedConnectedElementVector.clear();
                allModifiedConnectedElementNames.clear();
            }
        }

        // key is the new generated shape, value is a pair where the first value is the `IndexedName`
        // of the key, and the second is the `DecodedMappedSection` associated with the key.
        std::unordered_map<TopoDS_Shape, Data::DecodedMappedSection, ShapeHasher, ShapeHasher>
            namedGeneratedShapes;
        // In the order of the generated groups.
        std::vector<std::pair<std::vector<NamingMapKey>, Data::DecodedMappedSection>>
            delayedGeneratedMap;
        // Per entry of delayedGeneratedMap: the group's first shared source if it is an edge, and
        // its first face source (null if none), for its vertexes' sides (crossingPlaces), and
        // its sources, for its members' order (twinOrder)
        std::vector<std::pair<TopoDS_Shape, TopoDS_Shape>> delayedCrossingSources;
        std::vector<std::vector<TopoDS_Shape>> delayedSources;
        auto sourceShapes = [](const std::vector<NamingMapValue>& sources) {
            std::vector<TopoDS_Shape> shapes;
            for (const NamingMapValue& source : sources) {
                shapes.push_back(source.incomingElementShape);
            }
            return shapes;
        };
        auto crossingSources = [](const std::vector<NamingMapValue>& sources) {
            std::pair<TopoDS_Shape, TopoDS_Shape> result;
            const TopoDS_Shape& first = sources.front().incomingElementShape;
            if (first.IsNull() || first.ShapeType() != TopAbs_EDGE) {
                return result;
            }
            result.first = first;
            for (const NamingMapValue& source : sources) {
                const TopoDS_Shape& shape = source.incomingElementShape;
                if (!shape.IsNull() && shape.ShapeType() == TopAbs_FACE) {
                    result.second = shape;
                    break;
                }
            }
            return result;
        };

        generatedNamingMap.build();

        // NamingMap::Group: pair<std::vector<NamingMapKey>, std::vector<NamingMapValue>>
        for (const auto& generatedShapeEntry : generatedNamingMap.getGroups()) {
            std::vector<Data::MappedName> linkedNames;

            for (const NamingMapValue& generatedInfo : generatedShapeEntry.second) {
                if (generatedInfo.incomingElementMappedNames.size()) {
                    linkedNames.push_back(generatedInfo.incomingElementMappedNames.front().first);
                }
            }

            sortNameSet(linkedNames);

            if (linkedNames.size()) {
                Data::DecodedMappedSection newNameSection;
                size_t generatedShapes = generatedShapeEntry.first.size();

                for (const Data::MappedName& linkedName : linkedNames) {
                    newNameSection.linkedNames.push_back(linkedName.toString());
                }

                // Filled for the whole group before the member loop, so that no member (an
                // already named first one included) decides the others' fields (R8). The type
                // is each member's own (ops#46).
                newNameSection.iterationTag = std::to_string(masterTag);
                newNameSection.opCode = op;
                newNameSection.index = "0";
                newNameSection.duplicateCount = "0";
                newNameSection.mapperFlags = {Data::MAPPER_FLAG_GENERATED};

                // A vertex where an edge crosses a face takes its side into this provisional
                // section too (`naming-class-A.md` M2 (a')): the edges generated from the same
                // sources are then told apart by their end vertexes' names, not by a counter (a
                // hole's rim in two pieces split at its seam vertex). Where a side can't be told
                // for one vertex of the group, none takes one (I-A6).
                const auto [crossedEdge, crossingFace] = crossingSources(generatedShapeEntry.second);
                std::vector<std::string> provisionalSides(generatedShapes);
                if (!crossedEdge.IsNull()) {
                    for (size_t i = 0; i < generatedShapes; i++) {
                        const NamingMapKey& member = generatedShapeEntry.first[i];
                        if (std::strcmp(member.newElementName.getType(), "Vertex") != 0) {
                            continue;
                        }
                        provisionalSides[i]
                            = crossingSide(member.newElementShape, crossedEdge, crossingFace);
                        if (provisionalSides[i].empty()) {
                            provisionalSides.assign(generatedShapes, {});
                            break;
                        }
                    }
                }

                for (size_t i = 0; i < generatedShapes; i++) {
                    const Data::IndexedName& generatedElementName
                        = generatedShapeEntry.first[i].newElementName;
                    const TopoDS_Shape& generatedElementShape
                        = generatedShapeEntry.first[i].newElementShape;

                    if (getMappedName(generatedElementName)) {
                        continue;
                    }

                    newNameSection.elementType = (*generatedElementName.getType());

                    // we put all generated elements in here, even if it was just mapped above.
                    // we do this so we can look up those values later.
                    Data::DecodedMappedSection provisionalSection = newNameSection;
                    if (!provisionalSides[i].empty()) {
                        provisionalSection.index = provisionalSides[i];
                    }
                    namedGeneratedShapes[generatedElementShape] = provisionalSection;
                }

                // if the source shapes create more than one resultant shapes, then wait to map
                // it so we can collect the proper `ConnectedElements`.
                if (generatedShapes == 1) {
                    newNameSection.elementType
                        = (*generatedShapeEntry.first[0].newElementName.getType());
                    if (newNameSection.elementType == 'V' && !crossedEdge.IsNull()) {
                        const TwinPlace place = crossingPlaces(
                            {generatedShapeEntry.first[0].newElementShape},
                            crossedEdge,
                            crossingFace
                        ).front();
                        newNameSection.index = place.index;
                        newNameSection.duplicateCount = place.duplicateCount;
                        if (place.ordered) {
                            newNameSection.mapperFlags.emplace_back(Data::MAPPER_FLAG_ORDERED);
                        }
                    }
                    ensureElementMap()->setElementName(
                        generatedShapeEntry.first[0].newElementName,
                        Data::MappedName(Data::MappedName::makeEncodedSection(newNameSection)),
                        masterTag
                    );
                }
                else if (generatedShapes > 1) {
                    delayedGeneratedMap.emplace_back(generatedShapeEntry.first, newNameSection);
                    delayedCrossingSources.emplace_back(crossedEdge, crossingFace);
                    delayedSources.push_back(sourceShapes(generatedShapeEntry.second));
                }
            }
        }

        std::unordered_map<TopoDS_Shape, std::vector<std::string>, ShapeHasher, ShapeHasher>
            generatedConnectedElementMap;
        std::unordered_multiset<std::string> allGeneratedConnectedElementNames;

        // pair<std::vector<NamingMapKey>, Data::DecodedMappedSection>
        for (std::size_t entryIndex = 0; entryIndex < delayedGeneratedMap.size(); ++entryIndex) {
            const auto& delayedGeneratedEntry = delayedGeneratedMap[entryIndex];
            for (const Part::NamingMapKey& elementKey : delayedGeneratedEntry.first) {
                const Data::IndexedName& elementIndexName = elementKey.newElementName;
                const TopoDS_Shape& elementShape = elementKey.newElementShape;

                if (getMappedName(elementIndexName)) {
                    continue;
                }

                auto lowerMapTypeEntry = lowerMapTypes.find(elementIndexName.getType());

                if (lowerMapTypeEntry != lowerMapTypes.end()) {
                    TopExp_Explorer xp;
                    xp.Init(elementShape, lowerMapTypeEntry->second);

                    for (; xp.More(); xp.Next()) {
                        const TopoDS_Shape& foundSubshape = xp.Current();
                        auto namedGeneratedIterator = namedGeneratedShapes.find(foundSubshape);

                        if (namedGeneratedIterator != namedGeneratedShapes.end()) {
                            std::string encodedMappedSection = Data::MappedName::makeEncodedSection(
                                namedGeneratedIterator->second
                            );

                            generatedConnectedElementMap[elementShape].push_back(encodedMappedSection);
                            allGeneratedConnectedElementNames.insert(encodedMappedSection);

                            continue;
                        }

                        auto namedModifiedIterator = includedModifiedNameMap.find(foundSubshape);

                        if (namedModifiedIterator != includedModifiedNameMap.end()) {
                            std::string foundModifiedName
                                = namedModifiedIterator->second.second.toString();

                            generatedConnectedElementMap[elementShape].push_back(foundModifiedName);
                            allGeneratedConnectedElementNames.insert(foundModifiedName);
                        }
                    }
                }
            }

            // pair<const TopoDS_Shape, std::vector<Data::DecodedMappedSection>>
            for (auto& connectedElementKey : generatedConnectedElementMap) {
                std::vector<std::string> finalConnectedElementsList;

                for (const std::string& connectedElementSection : connectedElementKey.second) {
                    if (allGeneratedConnectedElementNames.count(connectedElementSection) <= 1) {
                        finalConnectedElementsList.push_back(connectedElementSection);
                    }
                }

                sortNameSet(finalConnectedElementsList);
                connectedElementKey.second = finalConnectedElementsList;
            }

            // The members without Connected Names are told apart by their place among the
            // group's members of their type (the type tells types apart, ops#46): in twinOrder's
            // order, with the count (the size rule, I-A2), and with ORD; a lone one `0`, as
            // before. Vertexes generated along an edge that a face crosses (a hole crossing it
            // twice) are named by their side of the face, `in` and `out` (ops#468), lone ones
            // included: when an edit changes how many there are (the hole's seam leaving the
            // edge or reaching it), a name never passes to the other crossing.
            const std::vector<NamingMapKey>& members = delayedGeneratedEntry.first;
            std::map<char, std::vector<std::size_t>> placedMembers;
            for (std::size_t i = 0; i < members.size(); ++i) {
                auto it = generatedConnectedElementMap.find(members[i].newElementShape);
                if (it == generatedConnectedElementMap.end() || it->second.empty()) {
                    placedMembers[*members[i].newElementName.getType()].push_back(i);
                }
            }
            std::vector<TwinPlace> places(members.size());
            const auto& [crossedEdge, crossingFace] = delayedCrossingSources[entryIndex];
            for (const auto& [type, indexes] : placedMembers) {
                std::vector<TopoDS_Shape> shapes;
                for (std::size_t i : indexes) {
                    shapes.push_back(members[i].newElementShape);
                }
                const std::vector<std::size_t> order
                    = twinOrder(shapes, delayedSources[entryIndex], frame);
                std::vector<TopoDS_Shape> ordered;
                for (std::size_t k : order) {
                    ordered.push_back(shapes[k]);
                }
                const std::vector<TwinPlace> typePlaces = type == 'V' && !crossedEdge.IsNull()
                    ? crossingPlaces(ordered, crossedEdge, crossingFace)
                    : twinPlaces(ordered.size());
                for (std::size_t k = 0; k < order.size(); ++k) {
                    places[indexes[order[k]]] = typePlaces[k];
                }
            }

            for (std::size_t i = 0; i < members.size(); ++i) {
                const Data::IndexedName& elementIndexName = members[i].newElementName;
                const TopoDS_Shape& elementShape = members[i].newElementShape;
                Data::DecodedMappedSection elementMappedSection = delayedGeneratedEntry.second;
                std::vector<std::string> connectedElements;
                auto it = generatedConnectedElementMap.find(elementShape);

                if (it != generatedConnectedElementMap.end()) {
                    connectedElements = it->second;
                }

                elementMappedSection.elementType = (*elementIndexName.getType());

                if (connectedElements.size()) {
                    elementMappedSection.connectedElements = connectedElements;
                }
                else {
                    elementMappedSection.index = places[i].index;
                    elementMappedSection.duplicateCount = places[i].duplicateCount;
                    if (places[i].ordered) {
                        elementMappedSection.mapperFlags.emplace_back(Data::MAPPER_FLAG_ORDERED);
                    }
                }

                ensureElementMap()->setElementName(
                    elementIndexName,
                    Data::MappedName(Data::MappedName::makeEncodedSection(elementMappedSection)),
                    masterTag
                );
            }

            generatedConnectedElementMap.clear();
            allGeneratedConnectedElementNames.clear();
        }

        // Per element type: the type tells the members of lists of different types apart. Only
        // looked up, never iterated.
        std::map<char, std::unordered_multiset<std::vector<Data::MappedName>, Data::MappedNameHasher>>
            usedUpperNames;
        std::map<char, std::unordered_multiset<std::vector<Data::MappedName>, Data::MappedNameHasher>>
            usedLowerNames;
        std::map<char, std::unordered_multiset<Data::MappedName, Data::MappedNameHasher>>
            usedPartnerNames;
        std::array<ShapeInfo*, 3> topologyMapElementOrder = {&faceInfo, &edgeInfo, &vertexInfo};

        // Now let's map any unmapped shapes with the IsPartner and ancestor method. A pass names
        // faces, then edges, then vertices, so a face named by nothing but its outer wire's edges
        // stays unnamed when those edges get their names only in this pass (UPP). A second pass
        // names what the first left, from the names the first gave; it changes no name (ops#25:
        // one of two coincident pieces of a split face, which has no history).
        //
        // The members of one partner or list (of one type) are twins, told apart by their place
        // among them: Index `0` and `<k>of<n>` in DuplicateCount (the size rule, I-A2), a lone
        // member `0`. An element's partner and lists come only from elements of other types, so
        // each type's lists are collected first and the places given after, per list in the
        // order of the members' places (elementOrderValues), not of their indexes in the result,
        // which follow OCCT's sub-shape order (ops#378: a round hole's bend arcs in a Pipe). An
        // UPP member's place is read on its reference, the first ancestor in the list's name
        // order that isn't a plane; an UPP list named only from planes keeps the result's order.
        // LOW and PRJ members have no reference, and are ordered by their length or area and
        // their coordinates. A list carries ORD only where its order is no key by I-A3
        // (fallbackOrderIsNoKey; `naming-class-A.md` M2 (b)). A member a second pass names from
        // a list the first pass named counts on after it.
        enum class Fallback
        {
            Partner,
            Upper,
            Lower
        };
        struct FallbackName
        {
            int index;
            Fallback kind;
            std::vector<Data::MappedName> names;
            TopoDS_Shape reference;  ///< UPP: the first named ancestor not a plane; else null
        };
        for (int pass = 0; pass < 2; ++pass) {
            bool unnamedLeft = false;
            for (const auto& info : topologyMapElementOrder) {
                std::string stringSubshapeType {info->shapetype};

                auto upperMapTypeEntry = upperMapTypes.find(stringSubshapeType);
                std::vector<FallbackName> fallbackNames;

                for (int mainI = 1; mainI <= info->count(); mainI++) {
                    bool wasMapped = false;
                    const auto& mainElement = info->find(mainI);
                    Data::IndexedName mainElementIndexedName
                        = Data::IndexedName::fromConst(info->shapetype, mainI);

                    if (getMappedName(mainElementIndexedName)) {
                        continue;
                    }

                    for (const auto& incomingShape : shapes) {
                        if (pass > 0) {
                            break;  // the second pass finds no new partner
                        }
                        if (!canMapElement(incomingShape)) {
                            continue;
                        }
                        auto& otherMap = incomingShape._cache->getAncestry(info->type);
                        if (otherMap.empty()) {
                            continue;
                        }
                        for (int otherI = 1; otherI <= otherMap.count(); otherI++) {
                            const auto& incomingElement
                                = otherMap.find(incomingShape._Shape, otherI);

                            if (incomingElement.IsPartner(mainElement)) {
                                Data::IndexedName incomingShapeIndexedName
                                    = Data::IndexedName::fromConst(info->shapetype, otherI);

                                Data::MappedName incomingShapeMapName = incomingShape.getMappedName(
                                    incomingShapeIndexedName
                                );

                                // An input without an element map (e.g. a Part::Plane) still
                                // gives its partner a name, as in the Modified/Generated stage.
                                if (!incomingShapeMapName) {
                                    incomingShapeMapName = Data::MappedName::makeUnmappedName(
                                        {incomingShapeIndexedName.toString()},
                                        incomingShape.Tag,
                                        op,
                                        (*incomingShapeIndexedName.getType())
                                    );
                                }

                                if (incomingShapeMapName
                                    && incomingShape.getInternNames() != getInternNames()) {
                                    incomingShapeMapName
                                        = toMapForm(incomingShapeMapName, getInternNames());
                                }

                                if (incomingShapeMapName) {
                                    fallbackNames.push_back(
                                        {mainI, Fallback::Partner, {incomingShapeMapName}, {}}
                                    );
                                    wasMapped = true;
                                    break;
                                }
                            }
                        }
                    }

                    if (!wasMapped && upperMapTypeEntry != upperMapTypes.end()) {
                        std::vector<Data::MappedName> linkedUpperNames;
                        std::vector<std::pair<Data::MappedName, TopoDS_Shape>> namedAncestors;
                        auto linkAncestorNames = [&](TopAbs_ShapeEnum ancestorType) {
                            for (const auto& ancestor :
                                 findAncestorsShapes(mainElement, ancestorType)) {
                                Data::IndexedName ancestorIndexName = Data::IndexedName::fromConst(
                                    shapeName(ancestorType).c_str(),
                                    findShape(ancestor)
                                );
                                Data::MappedName ancestorMappedName
                                    = getMappedName(ancestorIndexName);

                                if (ancestorMappedName
                                    && std::find(
                                           linkedUpperNames.begin(),
                                           linkedUpperNames.end(),
                                           ancestorMappedName
                                       ) == linkedUpperNames.end()) {
                                    linkedUpperNames.push_back(ancestorMappedName);
                                    namedAncestors.emplace_back(ancestorMappedName, ancestor);
                                }
                            }
                        };

                        linkAncestorNames(upperMapTypeEntry->second);

                        // A vertex without a named face (a result without faces, or a free edge's
                        // end) is named from its edges, as V1 does (ops#21).
                        auto secondUpperMapTypeEntry = secondUpperMapTypes.find(stringSubshapeType);
                        if (linkedUpperNames.empty()
                            && secondUpperMapTypeEntry != secondUpperMapTypes.end()) {
                            linkAncestorNames(secondUpperMapTypeEntry->second);
                        }

                        sortNameSet(linkedUpperNames);

                        if (linkedUpperNames.size()) {
                            // The list's reference: the ancestor of its first name that isn't
                            // a plane, chosen by name, never by the result's sub-shape order. A
                            // plane OCCT builds for a sketch's face has its axes along the
                            // world's whatever the sketch's turn, so on it the order would be
                            // the world's (fork PR 355 round 3). A list named only from planes
                            // has no reference and keeps the result's order, as before ops#378:
                            // any key on a plane or on the shape's coordinates swaps such a pair
                            // under a turn of the whole model (fork PR 355 round 4)
                            TopoDS_Shape reference;
                            for (const auto& listName : linkedUpperNames) {
                                const auto named = std::find_if(
                                    namedAncestors.begin(),
                                    namedAncestors.end(),
                                    [&listName](const auto& entry) {
                                        return entry.first == listName;
                                    }
                                );
                                if (named == namedAncestors.end()) {
                                    continue;
                                }
                                const TopoDS_Shape& ancestor = named->second;
                                if (ancestor.ShapeType() != TopAbs_FACE
                                    || BRepAdaptor_Surface(TopoDS::Face(ancestor), Standard_False)
                                            .GetType()
                                        != GeomAbs_Plane) {
                                    reference = ancestor;
                                    break;
                                }
                            }
                            fallbackNames.push_back(
                                {mainI, Fallback::Upper, std::move(linkedUpperNames), reference}
                            );
                            continue;
                        }

                        auto lowerMapTypeEntry = lowerMapTypes.find(stringSubshapeType);

                        if (lowerMapTypeEntry != lowerMapTypes.end()) {
                            std::vector<Data::MappedName> linkedLowerNames;

                            TopExp_Explorer xp;
                            if (stringSubshapeType == "Face") {
                                // just explore thru the outer wire of a face.
                                xp.Init(
                                    BRepTools::OuterWire(TopoDS::Face(mainElement)),
                                    lowerMapTypeEntry->second
                                );
                            }
                            else {
                                xp.Init(mainElement, lowerMapTypeEntry->second);
                            }

                            for (; xp.More(); xp.Next()) {
                                Data::IndexedName lowerSubshapeIndexName;
                                TopoDS_Shape foundLowerSubshape = xp.Current();
                                ShapeInfo*& lowerSubshapeInfo
                                    = infoMap.at(lowerMapTypeEntry->second);

                                if (lowerSubshapeInfo->type == lowerMapTypeEntry->second) {
                                    lowerSubshapeIndexName = Data::IndexedName::fromConst(
                                        shapeName(lowerMapTypeEntry->second).c_str(),
                                        lowerSubshapeInfo->find(foundLowerSubshape)
                                    );
                                }

                                if (lowerSubshapeIndexName) {
                                    Data::MappedName lowerSubshapeName = getMappedName(
                                        lowerSubshapeIndexName
                                    );

                                    if (lowerSubshapeName
                                        && std::find(
                                               linkedLowerNames.begin(),
                                               linkedLowerNames.end(),
                                               lowerSubshapeName
                                           ) == linkedLowerNames.end()) {
                                        linkedLowerNames.push_back(lowerSubshapeName);
                                    }
                                }
                            }

                            sortNameSet(linkedLowerNames);

                            if (linkedLowerNames.size()) {
                                fallbackNames.push_back(
                                    {mainI, Fallback::Lower, std::move(linkedLowerNames), {}}
                                );
                                continue;
                            }
                        }
                    }

                    if (!wasMapped) {
                        unnamedLeft = true;  // named neither by a partner nor by UPP or LOW
                    }
                }

                // The members of each partner or list, in the result's order of their first
                // member; the lists' order decides no index.
                std::vector<std::vector<std::size_t>> lists;
                std::array<std::unordered_map<std::vector<Data::MappedName>, std::size_t, Data::MappedNameHasher>, 3>
                    listIndex;
                for (std::size_t i = 0; i < fallbackNames.size(); ++i) {
                    auto& lookup = listIndex[static_cast<std::size_t>(fallbackNames[i].kind)];
                    auto found = lookup.try_emplace(fallbackNames[i].names, lists.size());
                    if (found.second) {
                        lists.emplace_back();
                    }
                    lists[found.first->second].push_back(i);
                }

                const char type = *info->shapetype;
                for (auto& list : lists) {
                    const FallbackName& first = fallbackNames[list.front()];
                    const bool resultOrder = first.kind == Fallback::Upper
                        && first.reference.IsNull();  // named only from planes
                    bool ordered = false;
                    if (list.size() > 1 && !resultOrder) {
                        std::vector<OrderValues> keys;
                        keys.reserve(list.size());
                        for (std::size_t i : list) {
                            keys.push_back(elementOrderValues(
                                info->find(fallbackNames[i].index),
                                fallbackNames[i].reference,
                                frame
                            ));
                        }
                        const std::vector<std::vector<long>> ranks = rankByGaps(keys);
                        std::vector<std::size_t> order(list.size());
                        std::iota(order.begin(), order.end(), 0);
                        // Stable: coincident members keep the result's order.
                        std::stable_sort(
                            order.begin(),
                            order.end(),
                            [&ranks](std::size_t left, std::size_t right) {
                                return ranks[left] < ranks[right];
                            }
                        );
                        std::vector<std::size_t> sorted;
                        sorted.reserve(list.size());
                        for (std::size_t k : order) {
                            sorted.push_back(list[k]);
                        }
                        list = std::move(sorted);
                        ordered = fallbackOrderIsNoKey(keys, ranks, order, first.reference);
                    }

                    // The members named before from the list's partner or names (an earlier
                    // pass's), and with this list's, how many there are
                    std::size_t before = 0;
                    switch (first.kind) {
                        case Fallback::Partner:
                            before = usedPartnerNames[type].count(first.names.front());
                            break;
                        case Fallback::Upper:
                            before = usedUpperNames[type].count(first.names);
                            break;
                        case Fallback::Lower:
                            before = usedLowerNames[type].count(first.names);
                            break;
                    }
                    const std::size_t count = before + list.size();

                    for (std::size_t position = 0; position < list.size(); ++position) {
                        const FallbackName& fallback = fallbackNames[list[position]];
                        const char* flag = nullptr;
                        switch (fallback.kind) {
                            case Fallback::Partner:
                                usedPartnerNames[type].insert(fallback.names.front());
                                flag = Data::MAPPER_FLAG_PROJECTION;
                                break;
                            case Fallback::Upper:
                                usedUpperNames[type].insert(fallback.names);
                                flag = Data::MAPPER_FLAG_UPPER;
                                break;
                            case Fallback::Lower:
                                usedLowerNames[type].insert(fallback.names);
                                flag = Data::MAPPER_FLAG_LOWER;
                                break;
                        }
                        std::vector<std::string> flags {flag};
                        if (count > 1 && ordered) {
                            flags.emplace_back(Data::MAPPER_FLAG_ORDERED);
                        }
                        Data::MappedName newName = Data::MappedName(
                            Data::MappedName::makeEncodedSection(
                                {},
                                fallback.names,
                                std::to_string(static_cast<int>(masterTag)),
                                op,
                                "0",
                                type,
                                count > 1 ? placeAmong(before + position, count) : "0",
                                flags
                            )
                        );
                        ensureElementMap()->setElementName(
                            Data::IndexedName::fromConst(info->shapetype, fallback.index),
                            newName,
                            masterTag
                        );
                    }
                }
            }
            if (!unnamedLeft) {
                break;
            }
        }
    }

    return *this;
}

namespace
{
void addShapesToBuilder(const std::vector<TopoShape>& shapes, BRep_Builder& builder, TopoDS_Compound& comp)
{
    int count = 0;
    for (auto& topoShape : shapes) {
        if (topoShape.isNull()) {
            FC_WARN("Null input shape");  // NOLINT
            continue;
        }
        builder.Add(comp, topoShape.getShape());
        ++count;
    }
    if (count == 0) {
        FC_THROWM(NullShapeException, "Null shape");
    }
}
}  // namespace

// TODO: Can this be consolidated with getSubShape()?  Empty Parm Logic is a little different.
TopoShape TopoShape::getSubTopoShape(const char* Type, bool silent) const
{
    if (!Type || !Type[0]) {
        switch (shapeType(true)) {
            case TopAbs_COMPOUND:
            case TopAbs_COMPSOLID:
                if (countSubShapes(TopAbs_SOLID) == 1) {
                    return getSubTopoShape(TopAbs_SOLID, 1);
                }
                if (countSubShapes(TopAbs_SHELL) == 1) {
                    return getSubTopoShape(TopAbs_SHELL, 1);
                }
                if (countSubShapes(TopAbs_FACE) == 1) {
                    return getSubTopoShape(TopAbs_FACE, 1);
                }
                if (countSubShapes(TopAbs_WIRE) == 1) {
                    return getSubTopoShape(TopAbs_WIRE, 1);
                }
                if (countSubShapes(TopAbs_EDGE) == 1) {
                    return getSubTopoShape(TopAbs_EDGE, 1);
                }
                if (countSubShapes(TopAbs_VERTEX) == 1) {
                    return getSubTopoShape(TopAbs_VERTEX, 1);
                }
                break;
            default:
                break;
        }
        return *this;
    }

    Data::MappedElement mapped = getElementName(Type);
    if (!mapped.index && boost::starts_with(Type, elementMapPrefix())) {
        if (!silent) {
            FC_THROWM(Base::CADKernelError, "Mapped element not found: " << Type);
        }
        return TopoShape(getHistoryAlgorithm());
    }
    auto res = shapeTypeAndIndex(mapped.index);
    if (res.second <= 0) {
        if (!silent) {
            FC_THROWM(Base::ValueError, "Invalid shape name " << (Type ? Type : ""));
        }
        return TopoShape(getHistoryAlgorithm());
    }
    return getSubTopoShape(res.first, res.second, silent);
}

// TODO: Can this be consolidated with getSubShape()?  We use ancestry; other uses current shape.
TopoShape TopoShape::getSubTopoShape(TopAbs_ShapeEnum type, int idx, bool silent) const
{
    if (isNull()) {
        if (!silent) {
            FC_THROWM(NullShapeException, "null shape");
        }
        return TopoShape(getHistoryAlgorithm());
    }
    if (idx <= 0) {
        if (!silent) {
            FC_THROWM(Base::ValueError, "Invalid shape index " << idx);
        }
        return TopoShape(getHistoryAlgorithm());
    }
    if (type < 0 || type > TopAbs_SHAPE) {
        if (!silent) {
            FC_THROWM(Base::ValueError, "Invalid shape type " << type);
        }
        return TopoShape(getHistoryAlgorithm());
    }
    initCache();
    auto& shapeMap = _cache->getAncestry(type);
    if (idx > shapeMap.count()) {
        if (!silent) {
            FC_THROWM(Base::IndexError, "Shape index " << idx << " out of bound " << shapeMap.count());
        }
        return TopoShape(getHistoryAlgorithm());
    }

    return shapeMap.getTopoShape(*this, idx);
}

TopoShape& TopoShape::makeElementEvolve(
    const TopoShape& spine,
    const TopoShape& profile,
    JoinType join,
    CoordinateSystem axeProf,
    MakeSolid solid,
    Spine profOnSpine,
    double tol,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::Evolve;
    }
    if (tol == 0.0) {
        tol = 1e-6;
    }

    GeomAbs_JoinType joinType;
    switch (join) {
        case JoinType::tangent:
            joinType = GeomAbs_Tangent;
            break;
        case JoinType::intersection:
            joinType = GeomAbs_Intersection;
            break;
        default:
            joinType = GeomAbs_Arc;
            break;
    }

    TopoDS_Shape spineShape;
    if (spine.countSubShapes(TopAbs_FACE) > 0) {
        spineShape = spine.getSubShape(TopAbs_FACE, 1);
    }
    else if (spine.countSubShapes(TopAbs_WIRE) > 0) {
        spineShape = spine.getSubShape(TopAbs_WIRE, 1);
    }
    else if (spine.countSubShapes(TopAbs_EDGE) > 0) {
        spineShape = BRepBuilderAPI_MakeWire(TopoDS::Edge(spine.getSubShape(TopAbs_EDGE, 1))).Wire();
    }
    if (spineShape.IsNull() || !BRepBuilderAPI_FindPlane(spineShape).Found()) {
        FC_THROWM(Base::CADKernelError, "Expect the spine to be a planar wire or face");
    }

    TopoDS_Shape profileShape;
    if (profile.countSubShapes(TopAbs_FACE) > 0 || profile.countSubShapes(TopAbs_WIRE) > 0) {
        profileShape = profile.getSubShape(TopAbs_WIRE, 1);
    }
    else if (profile.countSubShapes(TopAbs_EDGE) > 0) {
        profileShape
            = BRepBuilderAPI_MakeWire(TopoDS::Edge(profile.getSubShape(TopAbs_EDGE, 1))).Wire();
    }
    if (profileShape.IsNull() || !BRepBuilderAPI_FindPlane(profileShape).Found()) {
        if (profileShape.IsNull() || profile.countSubShapes(TopAbs_EDGE) > 1
            || !profile.getSubTopoShape(TopAbs_EDGE, 1).isLinearEdge()) {
            FC_THROWM(Base::CADKernelError, "Expect the profile to be a planar wire or a face or a line");
        }
    }
    if (spineShape.ShapeType() == TopAbs_FACE) {
        BRepOffsetAPI_MakeEvolved maker(
            TopoDS::Face(spineShape),
            TopoDS::Wire(profileShape),
            joinType,
            axeProf == CoordinateSystem::global ? Standard_True : Standard_False,
            solid == MakeSolid::makeSolid ? Standard_True : Standard_False,
            profOnSpine == Spine::on ? Standard_True : Standard_False,
            tol
        );
        return makeElementShape(maker, {spine, profile}, op);
    }
    else {
        BRepOffsetAPI_MakeEvolved maker(
            TopoDS::Wire(spineShape),
            TopoDS::Wire(profileShape),
            joinType,
            axeProf == CoordinateSystem::global ? Standard_True : Standard_False,
            solid == MakeSolid::makeSolid ? Standard_True : Standard_False,
            profOnSpine == Spine::on ? Standard_True : Standard_False,
            tol
        );
        return makeElementShape(maker, {spine, profile}, op);
    }
}

TopoShape& TopoShape::makeElementRuledSurface(
    const std::vector<TopoShape>& shapes,
    int orientation,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::RuledSurface;
    }

    if (shapes.size() != 2) {
        FC_THROWM(Base::CADKernelError, "Wrong number of input shapes");
    }

    std::vector<TopoShape> curves(2);
    int i = 0;
    for (auto& s : shapes) {
        if (s.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        auto type = s.shapeType();
        if (type == TopAbs_WIRE || type == TopAbs_EDGE) {
            curves[i++] = s;
            continue;
        }
        auto countOfWires = s.countSubShapes(TopAbs_WIRE);
        if (countOfWires > 1) {
            curves[i++] = s.getSubTopoShape(TopAbs_WIRE, 1);
            continue;
        }
        auto countOfEdges = s.countSubShapes(TopAbs_EDGE);
        if (countOfEdges == 0) {
            FC_THROWM(Base::CADKernelError, "Input shape has no edge");
        }
        if (countOfEdges == 1) {
            curves[i++] = s.getSubTopoShape(TopAbs_EDGE, 1);
            continue;
        }
        curves[i] = s.makeElementWires();
        if (curves[i].isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        if (curves[i].shapeType() != TopAbs_WIRE) {
            FC_THROWM(Base::CADKernelError, "Input shape forms more than one wire");
        }
        ++i;
    }

    if (curves[0].shapeType() != curves[1].shapeType()) {
        for (auto& curve : curves) {
            if (curve.shapeType() == TopAbs_EDGE) {
                curve = curve.makeElementWires();
            }
        }
    }

    auto& S1 = curves[0];
    auto& S2 = curves[1];
    bool isWire = S1.shapeType() == TopAbs_WIRE;

    // https://forum.freecad.org/viewtopic.php?f=8&t=24052
    //
    // if both shapes are sub-elements of one common shape then the fill
    // algorithm leads to problems if the shape has set a placement. The
    // workaround is to copy the sub-shape
    S1.setTransform(S1.getTransform());
    S2.setTransform(S2.getTransform());

    if (orientation == 0) {
        // Automatic
        Handle(Adaptor3d_HCurve) a1;
        Handle(Adaptor3d_HCurve) a2;
        if (!isWire) {
            BRepAdaptor_HCurve adapt1(TopoDS::Edge(S1.getShape()));
            BRepAdaptor_HCurve adapt2(TopoDS::Edge(S2.getShape()));
            a1 = new BRepAdaptor_HCurve(adapt1);
            a2 = new BRepAdaptor_HCurve(adapt2);
        }
        else {
            BRepAdaptor_HCompCurve adapt1(TopoDS::Wire(S1.getShape()));
            BRepAdaptor_HCompCurve adapt2(TopoDS::Wire(S2.getShape()));
            a1 = new BRepAdaptor_HCompCurve(adapt1);
            a2 = new BRepAdaptor_HCompCurve(adapt2);
        }

        if (!a1.IsNull() && !a2.IsNull()) {
            // get end points of 1st curve
            gp_Pnt p1 = a1->Value(0.9 * a1->FirstParameter() + 0.1 * a1->LastParameter());
            gp_Pnt p2 = a1->Value(0.1 * a1->FirstParameter() + 0.9 * a1->LastParameter());
            if (S1.getShape().Orientation() == TopAbs_REVERSED) {
                std::swap(p1, p2);
            }

            // get end points of 2nd curve
            gp_Pnt p3 = a2->Value(0.9 * a2->FirstParameter() + 0.1 * a2->LastParameter());
            gp_Pnt p4 = a2->Value(0.1 * a2->FirstParameter() + 0.9 * a2->LastParameter());
            if (S2.getShape().Orientation() == TopAbs_REVERSED) {
                std::swap(p3, p4);
            }

            // Form two triangles (P1,P2,P3) and (P4,P3,P2) and check their normals.
            // If the dot product is negative then it's assumed that the resulting face
            // is twisted, hence the 2nd edge is reversed.
            gp_Vec v1(p1, p2);
            gp_Vec v2(p1, p3);
            gp_Vec n1 = v1.Crossed(v2);

            gp_Vec v3(p4, p3);
            gp_Vec v4(p4, p2);
            gp_Vec n2 = v3.Crossed(v4);

            if (n1.Dot(n2) < 0) {
                S2.setShape(S2.getShape().Reversed(), false);
            }
        }
    }
    else if (orientation == 2) {
        // Reverse
        S2.setShape(S2.getShape().Reversed(), false);
    }

    TopoDS_Shape ruledShape;
    if (!isWire) {
        ruledShape = BRepFill::Face(TopoDS::Edge(S1.getShape()), TopoDS::Edge(S2.getShape()));
    }
    else {
        ruledShape = BRepFill::Shell(TopoDS::Wire(S1.getShape()), TopoDS::Wire(S2.getShape()));
    }

    // Both BRepFill::Face() and Shell() modifies the original input edges
    // without any API to provide relationship to the output edges. So we have
    // to use searchSubShape() to build the relationship by ourselves.

    TopoShape res(getHistoryAlgorithm(), ruledShape.Located(TopLoc_Location()));
    std::vector<TopoShape> edges;
    for (const auto& c : curves) {
        for (const auto& e : c.getSubTopoShapes(TopAbs_EDGE)) {
            auto found = res.findSubShapesWithSharedVertex(e);
            if (found.size() > 0) {
                found.front().resetElementMap(e.elementMap());
                edges.push_back(found.front());
            }
        }
    }
    // Use empty mapper and let makeShapeWithElementMap name the created surface with lower
    // elements.
    return makeShapeWithElementMap(res.getShape(), Mapper(), edges, op);
}

TopoShape& TopoShape::makeElementCompound(
    const std::vector<TopoShape>& shapes,
    const char* op,
    SingleShapeCompoundCreationPolicy policy,
    ElementMapPolicy elementMapPolicy
)
{
    if (policy == SingleShapeCompoundCreationPolicy::returnShape && shapes.size() == 1) {
        *this = shapes[0];
        if (elementMapPolicy == ElementMapPolicy::Drop) {
            dropElementNaming();
        }
        return *this;
    }

    BRep_Builder builder;
    TopoDS_Compound comp;
    builder.MakeCompound(comp);

    if (shapes.empty()) {
        setShape(comp, false);
        if (elementMapPolicy == ElementMapPolicy::Drop) {
            dropElementNaming();
        }
        return *this;
    }
    addShapesToBuilder(shapes, builder, comp);
    setShape(comp, false);

    if (elementMapPolicy == ElementMapPolicy::Drop) {
        dropElementNaming();
    }
    else {
        initCache();
        mapSubElement(shapes, op);
    }
    return *this;
}

static std::vector<TopoShape> prepareProfiles(const std::vector<TopoShape>& shapes, size_t offset = 0)
{
    std::vector<TopoShape> ret;
    for (size_t i = offset; i < shapes.size(); ++i) {
        auto shape = shapes[i];
        if (shape.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        if (shape.countSubShapes(TopAbs_FACE) == 1) {
            shape = shape.getSubTopoShape(TopAbs_FACE, 1).splitWires();
        }
        else if (shape.countSubShapes(TopAbs_WIRE) == 0 && shape.countSubShapes(TopAbs_EDGE) > 0) {
            shape = shape.makeElementWires();
        }

        if (shape.countSubShapes(TopAbs_WIRE) == 1) {
            ret.push_back(shape.getSubTopoShape(TopAbs_WIRE, 1));
            continue;
        }
        else if (shape.countSubShapes(TopAbs_VERTEX) == 1) {
            ret.push_back(shape.getSubTopoShape(TopAbs_VERTEX, 1));
            continue;
        }

        FC_THROWM(Base::CADKernelError, "Profile shape is not a single vertex, edge, wire nor face.");
    }
    if (ret.empty()) {
        FC_THROWM(Base::CADKernelError, "No profile");
    }
    return ret;
}

namespace
{
// A sweep's ends, corners and lateral edges (ops#375). MakePipeShell reports the edges and
// vertices of the sections it places at the spine's vertices (the start and end wires, and the
// wire at each corner) as generated from those vertices, so a square's four start edges were all
// `<spine vertex>;SWP;<n>;E;GEN`, told apart only by the counter n, in the wire's order. A
// profile edit that adds an edge before another (a chamfer at a corner) shifted the counters, and
// references on start, corner and end edges moved silently to a neighbour.
// - Ends. As in a PartDesign Pipe (ops#351, FeaturePipe.cpp's MapperPipeShellEnds): one end
//   wire's edges and vertices are the first section's modified (its own names), the other's the
//   last section's projected (`PRJ`). The end that keeps the first section's names is the one
//   behind its plane: the shell's start when the spine runs along the plane's normal where it
//   meets the section, its end when the spine runs against it (fork PR 352 round 3). The normal
//   is the plane's, turned towards the section's own Z axis (a sketch's normal), so the rule
//   holds wherever the profile sits on the spine and whichever way the spine is drawn. Turning
//   the profile over (reversing its placement's Z) swaps the ends' names: no rule can hold both
//   that and a reversed spine without a fixed direction in space, which a spine turned across
//   it would swap instead (ops repo notes\ops375-sweep-end-names.md, round 3). Earlier
//   rounds gave the profile's names to the end it lies at, which an interior profile has none
//   of: it handed them to the nearer end, and moving it across the spine's middle swapped the
//   ends (round 1); then the ends there were named after the spine's end vertices (round 2),
//   and an edit taking the profile across the pipe's 3D tolerance from an end renamed them all,
//   and references broke; reversing the spine swapped them.
//   When that rule can't tell (a point section, a profile without a plane, or one whose plane
//   holds the spine's tangent), round 2's applies: the profile's names to the end it lies at,
//   within the 3D tolerance; otherwise the end wires are generated from the spine's end
//   vertices, and from the section elements whose side faces or lateral edges they bound (an
//   end edge named after its spine vertex and profile edge, an end vertex after its spine
//   vertex and profile vertex; from the spine vertex alone a counter told them apart, and a
//   chamfer on the profile moved them silently).
// - Corners. The spine's other vertices generate no edges or vertices, so the edges at a corner
//   are named after the side faces they bound (`UPP`), whose names hold the spine's edge and the
//   profile's. Faces keep their history: a round corner's faces are the profile edges' too.
// - Lateral edges (a section vertex swept along one leg) are also generated from the spine edge
//   (or round corner's vertex) whose side faces they bound, so each is named after its section
//   vertex and that spine element, as a side face is after its profile edge and spine edge.
//   MakePipeShell reports them as generated from the section vertex alone, and they were told
//   apart by leg order, the first leg's taking the start vertex's name once there were two legs:
//   adding a leg at the far end, or deleting the last, moved references silently (fork PR 352
//   round 1).
class MapperSweepEnds: public MapperMaker
{
public:
    /// \a spine is the spine as given and as a wire, last (their vertices may differ),
    /// \a sections the sections added to \a pipe, a wire or a vertex each, \a tolerance the
    /// pipe's 3D tolerance. Built before MakeSolid(), after which a point section's ends are
    /// null.
    MapperSweepEnds(
        BRepOffsetAPI_MakePipeShell& pipe,
        const std::vector<TopoDS_Shape>& spine,
        const std::vector<TopoShape>& sections,
        double tolerance
    )
        : MapperMaker(pipe)
    {
        for (const TopoDS_Shape& shape : spine) {
            TopExp::MapShapes(shape, TopAbs_VERTEX, spineVertices);
            TopExp::MapShapes(shape, TopAbs_EDGE, spineEdges);
        }
        // A section's vertex keeps the edges it sweeps, should a section share it with the spine
        for (const TopoShape& section : sections) {
            TopExp::MapShapes(section.getShape(), TopAbs_VERTEX, sectionVertices);
            TopExp::MapShapes(section.getShape(), TopAbs_EDGE, sectionEdges);
        }
        for (int i = 1; i <= sectionVertices.Extent(); ++i) {
            for (const TopoDS_Shape& element : pipe.Generated(sectionVertices(i))) {
                if (element.ShapeType() == TopAbs_EDGE) {
                    laterals.Add(element);
                }
            }
        }
        const TopoDS_Shape& first = sections.front().getShape();
        const TopoDS_Shape& last = sections.back().getShape();
        TopTools_IndexedMapOfShape startElements;
        TopTools_IndexedMapOfShape endElements;
        if (!pipe.FirstShape().IsNull()) {
            TopExp::MapShapes(pipe.FirstShape(), startElements);
        }
        if (!pipe.LastShape().IsNull()) {
            TopExp::MapShapes(pipe.LastShape(), endElements);
        }
        // A point section is an end's apex, wherever the other sections' planes face
        const bool point = std::ranges::any_of(sections, [](const TopoShape& section) {
            return section.getShape().ShapeType() == TopAbs_VERTEX;
        });
        std::optional<bool> reversed;
        if (!point) {
            reversed = againstNormal(TopoDS::Wire(spine.back()), first);
        }
        if (!reversed) {
            double kept = distanceTo(first, pipe.FirstShape());
            double swapped = distanceTo(first, pipe.LastShape());
            const double atOwnEnd = std::min(kept, swapped);
            // One profile: its distances alone (the two sections' terms would be the same on
            // both sides, and nothing would ever swap)
            if (!last.IsSame(first)) {
                kept += distanceTo(last, pipe.LastShape());
                swapped += distanceTo(last, pipe.FirstShape());
            }
            reversed = swapped + Precision::Confusion() < kept;
            if (atOwnEnd > tolerance) {
                for (const TopTools_IndexedMapOfShape* end : {&startElements, &endElements}) {
                    for (int i = 1; i <= end->Extent(); ++i) {
                        const TopAbs_ShapeEnum type = end->FindKey(i).ShapeType();
                        if (type == TopAbs_EDGE || type == TopAbs_VERTEX) {
                            spineEndElements.Add(end->FindKey(i));
                        }
                    }
                }
                return;
            }
        }
        const TopTools_IndexedMapOfShape& own = *reversed ? endElements : startElements;
        const TopTools_IndexedMapOfShape& other = *reversed ? startElements : endElements;
        bindEnds(pipe, first, own, nullptr, starts);
        // With a closed spine the shell ends where it starts: those elements keep the first
        // section's names
        bindEnds(pipe, last, other, &own, ends);
    }

    const std::vector<TopoDS_Shape>& modified(const TopoDS_Shape& s) const override
    {
        MapperMaker::modified(s);
        if (const TopTools_ListOfShape* elements = starts.Seek(s)) {
            for (const TopoDS_Shape& element : *elements) {
                _res.push_back(element);
            }
        }
        return _res;
    }

    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& s) const override
    {
        MapperMaker::generated(s);
        if (spineVertices.Contains(s) && !sectionVertices.Contains(s)) {
            std::erase_if(_res, [this](const TopoDS_Shape& element) {
                return (element.ShapeType() == TopAbs_EDGE || element.ShapeType() == TopAbs_VERTEX)
                    && !spineEndElements.Contains(element);
            });
        }
        if (spineVertices.Contains(s) || spineEdges.Contains(s)) {
            // The lateral edges that bound the side faces this spine element generated
            addBounding(TopAbs_FACE, TopAbs_EDGE, laterals);
        }
        if (spineEndElements.IsEmpty()) {
            return _res;
        }
        // Away from the profile, the end wires' elements are generated from their spine end
        // vertex and from the section element they bound
        if (spineVertices.Contains(s)) {
            // The end wire's vertices, which MakePipeShell reports from no spine vertex
            addBounding(TopAbs_EDGE, TopAbs_VERTEX, spineEndElements);
        }
        else if (sectionEdges.Contains(s)) {
            // The end edges that bound this section edge's side faces
            addBounding(TopAbs_FACE, TopAbs_EDGE, spineEndElements);
        }
        else if (sectionVertices.Contains(s)) {
            // The end vertices that end this section vertex's lateral edges
            addBounding(TopAbs_EDGE, TopAbs_VERTEX, spineEndElements);
        }
        return _res;
    }

    const std::vector<TopoDS_Shape>& projected(const TopoDS_Shape& s) const override
    {
        _res.clear();
        if (const TopTools_ListOfShape* elements = ends.Seek(s)) {
            for (const TopoDS_Shape& element : *elements) {
                _res.push_back(element);
            }
        }
        return _res;
    }

private:
    /// Adds to the result the elements of type \a lower in \a among that bound its elements of
    /// type \a upper
    void addBounding(
        TopAbs_ShapeEnum upper,
        TopAbs_ShapeEnum lower,
        const TopTools_IndexedMapOfShape& among
    ) const
    {
        TopTools_IndexedMapOfShape bounding;
        for (const TopoDS_Shape& element : _res) {
            if (element.ShapeType() == upper) {
                TopExp::MapShapes(element, lower, bounding);
            }
        }
        for (int i = 1; i <= bounding.Extent(); ++i) {
            const TopoDS_Shape& element = bounding(i);
            if (among.Contains(element)
                && std::ranges::none_of(_res, [&](const TopoDS_Shape& found) {
                       return found.IsSame(element);
                   })) {
                _res.push_back(element);
            }
        }
    }

    /// Whether \a spine runs against the normal of \a section's plane where it passes nearest
    /// the section's centre, the normal turned towards the section's Z axis (its placement's,
    /// a sketch's normal); none when the section has no plane, its plane holds that Z axis or
    /// the spine's tangent there
    static std::optional<bool> againstNormal(const TopoDS_Wire& spine, const TopoDS_Shape& section)
    {
        TopExp_Explorer firstEdge(section, TopAbs_EDGE);
        if (!firstEdge.More()) {
            return std::nullopt;
        }
        BRepBuilderAPI_FindPlane findPlane(section);
        if (!findPlane.Found()) {
            return std::nullopt;
        }
        gp_Dir normal = findPlane.Plane()->Axis().Direction();
        const gp_Dir axis = gp::DZ().Transformed(firstEdge.Current().Location().Transformation());
        const double facing = normal.Dot(axis);
        if (std::abs(facing) < 0.5) {
            return std::nullopt;
        }
        if (facing < 0) {
            normal.Reverse();
        }
        GProp_GProps properties;
        BRepGProp::LinearProperties(section, properties);
        const TopoDS_Vertex centre = BRepBuilderAPI_MakeVertex(properties.CentreOfMass());
        // The nearest edge, the earlier one along the spine on a tie (a vertex between two)
        double nearest = std::numeric_limits<double>::infinity();
        gp_Vec tangent;
        for (BRepTools_WireExplorer it(spine); it.More(); it.Next()) {
            const TopoDS_Edge& edge = it.Current();
            BRepExtrema_DistShapeShape distance(centre, edge);
            if (!distance.IsDone() || distance.NbSolution() == 0
                || distance.Value() >= nearest - Precision::Confusion()) {
                continue;
            }
            double parameter = 0;
            if (distance.SupportTypeShape2(1) == BRepExtrema_IsOnEdge) {
                distance.ParOnEdgeS2(1, parameter);
            }
            else if (distance.SupportTypeShape2(1) == BRepExtrema_IsVertex) {
                parameter = BRep_Tool::Parameter(TopoDS::Vertex(distance.SupportOnShape2(1)), edge);
            }
            else {
                continue;
            }
            gp_Pnt point;
            gp_Vec derivative;
            BRepAdaptor_Curve(edge).D1(parameter, point, derivative);
            if (derivative.Magnitude() < Precision::Confusion()) {
                continue;
            }
            if (edge.Orientation() == TopAbs_REVERSED) {
                derivative.Reverse();
            }
            nearest = distance.Value();
            tangent = derivative.Normalized();
        }
        if (std::isinf(nearest)) {
            return std::nullopt;
        }
        const double along = tangent.Dot(gp_Vec(normal));
        if (std::abs(along) < 0.1) {
            return std::nullopt;
        }
        return along < 0;
    }

    /// How far \a section lies from the shell's end \a end: the mean over its vertices of the
    /// distance to the nearest vertex of the end, so that each section weighs the same whatever
    /// its number of vertices; infinite when either has none
    static double distanceTo(const TopoDS_Shape& section, const TopoDS_Shape& end)
    {
        constexpr double none = std::numeric_limits<double>::infinity();
        if (section.IsNull() || end.IsNull()) {
            return none;
        }
        TopTools_IndexedMapOfShape sectionVertices;
        TopTools_IndexedMapOfShape endVertices;
        TopExp::MapShapes(section, TopAbs_VERTEX, sectionVertices);
        TopExp::MapShapes(end, TopAbs_VERTEX, endVertices);
        if (sectionVertices.IsEmpty() || endVertices.IsEmpty()) {
            return none;
        }
        double sum = 0;
        for (int i = 1; i <= sectionVertices.Extent(); ++i) {
            const gp_Pnt at = BRep_Tool::Pnt(TopoDS::Vertex(sectionVertices(i)));
            double nearest = none;
            for (int j = 1; j <= endVertices.Extent(); ++j) {
                nearest = std::min(
                    nearest,
                    at.Distance(BRep_Tool::Pnt(TopoDS::Vertex(endVertices(j))))
                );
            }
            sum += nearest;
        }
        return sum / sectionVertices.Extent();
    }

    /// Binds each edge and vertex of \a section to the elements of one end of the shell,
    /// \a endElements, that the side faces or edges it generated hold; a point section to the
    /// end's vertex
    static void bindEnds(
        BRepOffsetAPI_MakePipeShell& pipe,
        const TopoDS_Shape& section,
        const TopTools_IndexedMapOfShape& endElements,
        const TopTools_IndexedMapOfShape* skip,
        TopTools_DataMapOfShapeListOfShape& bound
    )
    {
        if (section.IsNull()) {
            return;
        }
        auto take = [&](const TopoDS_Shape& element, TopTools_ListOfShape& found) {
            if (endElements.Contains(element) && !(skip && skip->Contains(element))) {
                found.Append(element);
            }
        };
        if (section.ShapeType() == TopAbs_VERTEX) {
            TopTools_ListOfShape found;
            for (int i = 1; i <= endElements.Extent(); ++i) {
                if (!endElements(i).IsNull() && endElements(i).ShapeType() == TopAbs_VERTEX) {
                    take(endElements(i), found);
                }
            }
            if (found.Extent() == 1) {
                bound.Bind(section, found);
            }
            return;
        }
        for (TopAbs_ShapeEnum type : {TopAbs_EDGE, TopAbs_VERTEX}) {
            TopTools_IndexedMapOfShape elements;
            TopExp::MapShapes(section, type, elements);
            for (int i = 1; i <= elements.Extent(); ++i) {
                TopTools_IndexedMapOfShape candidates;
                for (const TopoDS_Shape& side : pipe.Generated(elements(i))) {
                    TopExp::MapShapes(side, type, candidates);
                }
                TopTools_ListOfShape found;
                for (int j = 1; j <= candidates.Extent(); ++j) {
                    take(candidates(j), found);
                }
                if (!found.IsEmpty()) {
                    bound.Bind(elements(i), found);
                }
            }
        }
    }

    TopTools_IndexedMapOfShape spineVertices;
    TopTools_IndexedMapOfShape spineEdges;
    TopTools_IndexedMapOfShape sectionVertices;
    TopTools_IndexedMapOfShape sectionEdges;
    /// The edges the section vertices sweep
    TopTools_IndexedMapOfShape laterals;
    /// The end wires' edges and vertices when the first section doesn't lie at its end: the
    /// spine's end vertices keep generating them, and so do the section elements they bound
    TopTools_IndexedMapOfShape spineEndElements;
    TopTools_DataMapOfShapeListOfShape starts;
    TopTools_DataMapOfShapeListOfShape ends;
};
}  // namespace

TopoShape& TopoShape::makeElementPipeShell(
    const std::vector<TopoShape>& shapes,
    const MakeSolid make_solid,
    const Standard_Boolean isFrenet,
    TransitionMode transition,
    const char* op,
    double tol3d,
    double tolBound,
    double tolAngular
)
{
    if (!op) {
        op = Part::OpCodes::PipeShell;
    }

    if (shapes.size() < 2) {
        FC_THROWM(Base::CADKernelError, "Not enough input shapes");
    }

    auto spine = shapes.front().makeElementWires();
    if (spine.isNull()) {
        FC_THROWM(NullShapeException, "Null input shape");
    }
    if (spine.getShape().ShapeType() != TopAbs_WIRE) {
        FC_THROWM(Base::CADKernelError, "Spine shape cannot form a single wire");
    }

    BRepOffsetAPI_MakePipeShell mkPipeShell(TopoDS::Wire(spine.getShape()));
    BRepBuilderAPI_TransitionMode transMode;
    switch (transition) {
        case TransitionMode::RightCorner:
            transMode = BRepBuilderAPI_RightCorner;
            break;
        case TransitionMode::RoundCorner:
            transMode = BRepBuilderAPI_RoundCorner;
            break;
        default:
            transMode = BRepBuilderAPI_Transformed;
            break;
    }
    mkPipeShell.SetTransitionMode(transMode);
    if (tol3d != 0.0 || tolBound != 0.0 || tolAngular != 0.0) {
        if (tol3d == 0.0) {
            tol3d = 1e-4;
        }
        if (tolBound == 0.0) {
            tolBound = 1e-4;
        }
        if (tolAngular == 0.0) {
            tolAngular = 1e-2;
        }
        mkPipeShell.SetTolerance(tol3d, tolBound, tolAngular);
    }
    // OCCT's default caps left long planar spines off the main planes up to 0.15 mm loose (ops#448)
    PipeShellApproximation::set(mkPipeShell);

    const std::vector<TopoShape> profiles = prepareProfiles(shapes, 1);
    std::vector<TopoDS_Shape> sections;
    for (auto& sh : profiles) {
        sections.push_back(sh.getShape());
    }
    // Frenet's trihedron turns over at an inflection inside a spine edge (ops#421)
    const double pipeTolerance = tol3d != 0.0 ? tol3d : 1e-4;
    const SweepFrenet::Mode mode = SweepFrenet::setMode(
        mkPipeShell,
        TopoDS::Wire(spine.getShape()),
        sections,
        isFrenet,
        pipeTolerance
    );
    for (auto& sh : profiles) {
        mkPipeShell.Add(sh.getShape());
    }

    if (!mkPipeShell.IsReady()) {
        FC_THROWM(Base::CADKernelError, "shape is not ready to build");
    }
    else {
#if OCC_VERSION_HEX >= 0x070600
        mkPipeShell.Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
        mkPipeShell.Build();
#endif
    }

    // Shape() builds the pipe, which the mapper's FirstShape(), LastShape() and Generated() need.
    // The mapper reads the ends before MakeSolid(): after it, a point section's are null.
    mkPipeShell.Shape();
    SweepFrenet::checkBuilt(mkPipeShell.Shape(), mode, pipeTolerance);
    // MakePipeShell's default 3D tolerance (BRepOffsetAPI_MakePipeShell::SetTolerance) unless set
    const MapperSweepEnds mapper(
        mkPipeShell,
        {shapes.front().getShape(), spine.getShape()},
        profiles,
        tol3d != 0.0 ? tol3d : 1e-4
    );

    if (make_solid == MakeSolid::makeSolid) {
        mkPipeShell.MakeSolid();
    }

    const TopoDS_Shape built = mkPipeShell.Shape();
    return makeShapeWithElementMap(built, mapper, shapes, op);
}

namespace
{
// ops#49: BRepOffset_MakeOffset (Offset, Thickness) lists the result's faces in an order that
// changes from run to run when it adds arc faces (Join = Arc), while each face keeps the order of
// its own edges, vertexes and wires. Element indexes follow the face order, and so does the index
// that tells apart elements named after the same faces (partner, UPP and LOW names). So the faces
// are put in a canonical order before naming: by the first source element (faces, then edges,
// then vertexes, by index) whose history holds them, then by a geometric key. Only the containers
// are rebuilt: the faces and everything below them stay the same shapes, so the mapper still
// finds them.
struct FaceOrderKey
{
    int rank = std::numeric_limits<int>::max();
    std::array<long long, 4> geometry {};

    bool operator<(const FaceOrderKey& other) const
    {
        return std::tie(rank, geometry) < std::tie(other.rank, other.geometry);
    }
};

class CanonicalFaceOrder
{
public:
    CanonicalFaceOrder(const TopoShape::Mapper& mapper, const TopoShape& source)
    {
        int rank = 0;
        for (auto type : {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX}) {
            for (const auto& element : source.getSubShapes(type)) {
                // modified() and generated() share their result vector: read one at a time.
                for (const auto& image : mapper.modified(element)) {
                    claim(image, rank);
                }
                for (const auto& image : mapper.generated(element)) {
                    claim(image, rank);
                }
                ++rank;
            }
        }
    }

    /// The shape with the faces of each container in canonical order, or the shape itself if
    /// they already are.
    TopoDS_Shape apply(const TopoDS_Shape& shape)
    {
        return apply(shape, TopLoc_Location()).first;
    }

private:
    void claim(const TopoDS_Shape& image, int rank)
    {
        for (TopExp_Explorer xp(image, TopAbs_FACE); xp.More(); xp.Next()) {
            if (!ranks.IsBound(xp.Current())) {
                ranks.Bind(xp.Current(), rank);
            }
        }
    }

    FaceOrderKey faceKey(const TopoDS_Shape& face) const
    {
        FaceOrderKey key;
        if (const int* rank = ranks.Seek(face)) {
            key.rank = *rank;
        }
        GProp_GProps props;
        BRepGProp::SurfaceProperties(face, props);
        const gp_Pnt center = props.CentreOfMass();
        const double grid = 10 * Precision::Confusion();
        const std::array<double, 4> values {center.X(), center.Y(), center.Z(), props.Mass()};
        for (size_t i = 0; i < values.size(); ++i) {
            key.geometry[i] = std::llround(values[i] / grid);
        }
        return key;
    }

    /// `above` is the location of the shape's container. Returns the rebuilt shape and the
    /// smallest key of its faces.
    std::pair<TopoDS_Shape, FaceOrderKey> apply(const TopoDS_Shape& shape, const TopLoc_Location& above)
    {
        if (shape.ShapeType() == TopAbs_FACE) {
            return {shape, faceKey(shape.Moved(above))};
        }
        if (shape.ShapeType() > TopAbs_FACE) {
            return {shape, FaceOrderKey()};
        }
        const TopLoc_Location here = above * shape.Location();
        std::vector<TopoDS_Shape> original;
        std::vector<std::pair<TopoDS_Shape, FaceOrderKey>> children;
        bool changed = false;
        // The children as stored in the container, without its orientation and location.
        for (TopoDS_Iterator it(shape, Standard_False, Standard_False); it.More(); it.Next()) {
            original.push_back(it.Value());
            children.push_back(apply(it.Value(), here));
            changed = changed || !children.back().first.IsEqual(it.Value());
        }
        std::stable_sort(children.begin(), children.end(), [](const auto& a, const auto& b) {
            return a.second < b.second;
        });
        FaceOrderKey first = children.empty() ? FaceOrderKey() : children.front().second;
        for (size_t i = 0; !changed && i < children.size(); ++i) {
            changed = !children[i].first.IsEqual(original[i]);
        }
        if (!changed) {
            return {shape, first};
        }
        // Add the children to a copy at the identity, where the builder stores them as given,
        // then give the copy the container's orientation and location.
        TopoDS_Shape result = shape.EmptyCopied();
        result.Orientation(TopAbs_FORWARD);
        result.Location(TopLoc_Location());
        BRep_Builder builder;
        for (const auto& child : children) {
            builder.Add(result, child.first);
        }
        result.Closed(shape.Closed());
        result.Orientable(shape.Orientable());
        result.Infinite(shape.Infinite());
        result.Convex(shape.Convex());
        result.Orientation(shape.Orientation());
        result.Location(shape.Location());
        return {result, first};
    }

    TopTools_DataMapOfShapeInteger ranks;
};

TopoDS_Shape canonicalFaceOrder(
    const TopoDS_Shape& result,
    const TopoShape::Mapper& mapper,
    const TopoShape& source
)
{
    return CanonicalFaceOrder(mapper, source).apply(result);
}
}  // namespace

TopoShape& TopoShape::makeElementOffset(
    const TopoShape& shape,
    double offset,
    double tol,
    bool intersection,
    bool selfInter,
    short offsetMode,
    JoinType join,
    FillType fill,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::Offset;
    }

    BRepOffsetAPI_MakeOffsetShape mkOffset;
    mkOffset.PerformByJoin(
        shape.getShape(),
        offset,
        tol,
        BRepOffset_Mode(offsetMode),
        intersection ? Standard_True : Standard_False,
        selfInter ? Standard_True : Standard_False,
        GeomAbs_JoinType(join)
    );

    if (!mkOffset.IsDone()) {
        FC_THROWM(Base::CADKernelError, "BRepOffsetAPI_MakeOffsetShape not done");
    }

    TopoShape res(Tag, Hasher, getHistoryAlgorithm());
    MapperMaker mapper(mkOffset);
    res.makeShapeWithElementMap(canonicalFaceOrder(mkOffset.Shape(), mapper, shape), mapper, {shape}, op);
    if (shape.hasSubShape(TopAbs_SOLID) && !res.hasSubShape(TopAbs_SOLID)) {
        try {
            res = res.makeElementSolid();
        }
        catch (Standard_Failure& e) {
            FC_WARN("failed to make solid: " << e.GetMessageString());
        }
    }
    if (fill == FillType::noFill) {
        *this = res;
        return *this;
    }

    // get perimeter wire of original shape.
    // Wires returned seem to have edges in connection order.
    ShapeAnalysis_FreeBoundsProperties freeCheck(shape.getShape());
    freeCheck.Perform();
    if (freeCheck.NbClosedFreeBounds() < 1) {
        FC_THROWM(Base::CADKernelError, "no closed bounds");
    }

    BRep_Builder builder;
    std::vector<TopoShape> shapes;
    for (int index = 1; index <= freeCheck.NbClosedFreeBounds(); ++index) {
        TopoShape originalWire(
            shape.Tag,
            shape.Hasher,
            freeCheck.ClosedFreeBound(index)->FreeBound(),
            getHistoryAlgorithm()
        );
        originalWire.mapSubElement(shape);
        const BRepAlgo_Image& img = mkOffset.MakeOffset().OffsetEdgesFromShapes();

        // build offset wire.
        TopoDS_Wire offsetWire;
        builder.MakeWire(offsetWire);
        for (const auto& s : originalWire.getSubShapes(TopAbs_EDGE)) {
            if (!img.HasImage(s)) {
                FC_THROWM(Base::CADKernelError, "no image for shape");
            }
            const TopTools_ListOfShape& currentImage = img.Image(s);
            TopTools_ListIteratorOfListOfShape listIt;
            int edgeCount(0);
            TopoDS_Edge mappedEdge;
            for (listIt.Initialize(currentImage); listIt.More(); listIt.Next()) {
                if (listIt.Value().ShapeType() != TopAbs_EDGE) {
                    continue;
                }
                edgeCount++;
                mappedEdge = TopoDS::Edge(listIt.Value());
            }

            if (edgeCount != 1) {
                std::ostringstream stream;
                stream << "wrong edge count: " << edgeCount << std::endl;
                FC_THROWM(Base::CADKernelError, stream.str().c_str());
            }
            builder.Add(offsetWire, mappedEdge);
        }
        std::vector<TopoShape> wires;
        wires.push_back(originalWire);
        wires.push_back(TopoShape(Tag, Hasher, offsetWire, getHistoryAlgorithm()));
        wires.back().mapSubElement(res);

        // It would be nice if we could get thruSections to build planar faces
        // in all areas possible, so we could run through refine. I tried setting
        // ruled to standard_true, but that didn't have the desired affect.
        BRepOffsetAPI_ThruSections aGenerator;
        aGenerator.AddWire(TopoDS::Wire(originalWire.getShape()));
        aGenerator.AddWire(offsetWire);
#if OCC_VERSION_HEX >= 0x070600
        aGenerator.Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
        aGenerator.Build();
#endif
        if (!aGenerator.IsDone()) {
            FC_THROWM(Base::CADKernelError, "ThruSections failed");
        }

        shapes.push_back(
            TopoShape(Tag, Hasher, getHistoryAlgorithm()).makeElementShape(aGenerator, wires)
        );
    }

    TopoShape perimeterCompound(Tag, Hasher, getHistoryAlgorithm());
    perimeterCompound.makeElementCompound(shapes, op);

    // still had to sew. not using the passed in parameter for sew.
    // Sew has it's own default tolerance. Opinions?
    BRepBuilderAPI_Sewing sewTool;
    sewTool.Add(shape.getShape());
    sewTool.Add(perimeterCompound.getShape());
    sewTool.Add(res.getShape());
    sewTool.Perform();  // Perform Sewing

    TopoDS_Shape outputShape = sewTool.SewedShape();
    if ((outputShape.ShapeType() == TopAbs_SHELL) && (outputShape.Closed())) {
        BRepBuilderAPI_MakeSolid solidMaker(TopoDS::Shell(outputShape));
        if (solidMaker.IsDone()) {
            TopoDS_Solid temp = solidMaker.Solid();
            // contrary to the occ docs the return value OrientCloseSolid doesn't
            // indicate whether the shell was open or not. It returns true with an
            // open shell and we end up with an invalid solid.
            if (MassProperties::orientClosedSolid(temp)) {
                outputShape = temp;
            }
        }
    }

    shapes.clear();
    shapes.push_back(shape);
    shapes.push_back(res);
    shapes.push_back(perimeterCompound);
    *this = TopoShape(Tag, Hasher, getHistoryAlgorithm())
                .makeShapeWithElementMap(outputShape, MapperSewing(sewTool), shapes, op);
    return *this;
}

TopoShape& TopoShape::makeElementOffsetFace(
    const TopoShape& shape,
    double offset,
    double innerOffset,
    JoinType joinType,
    JoinType innerJoinType,
    const char* op
)
{
    if (std::abs(innerOffset) < Precision::Confusion() && std::abs(offset) < Precision::Confusion()) {
        *this = shape;
        return *this;
    }

    if (shape.isNull()) {
        FC_THROWM(Base::ValueError, "makeOffsetFace: input shape is null!");
    }
    if (!shape.hasSubShape(TopAbs_FACE)) {
        FC_THROWM(Base::ValueError, "makeOffsetFace: no face found");
    }

    std::vector<TopoShape> res;
    for (auto& face : shape.getSubTopoShapes(TopAbs_FACE)) {
        std::vector<TopoShape> wires;
        TopoShape outerWire = face.splitWires(&wires, ReorientForward);
        if (wires.empty()) {
            res.push_back(makeElementOffset2D(
                face,
                offset,
                joinType,
                FillType::noFill,
                OpenResult::noOpenResult,
                false,
                op
            ));
            continue;
        }
        if (outerWire.isNull()) {
            FC_THROWM(Base::CADKernelError, "makeOffsetFace: missing outer wire!");
        }

        if (std::abs(offset) > Precision::Confusion()) {
            outerWire = outerWire.makeElementOffset2D(
                offset,
                joinType,
                FillType::noFill,
                OpenResult::noOpenResult,
                false,
                op
            );
        }

        if (std::abs(innerOffset) > Precision::Confusion()) {
            TopoShape innerWires(0, Hasher, getHistoryAlgorithm());
            innerWires.makeElementCompound(wires, "", SingleShapeCompoundCreationPolicy::returnShape);
            innerWires = innerWires.makeElementOffset2D(
                innerOffset,
                innerJoinType,
                FillType::noFill,
                OpenResult::noOpenResult,
                true,
                op
            );
            wires = innerWires.getSubTopoShapes(TopAbs_WIRE);
        }
        wires.push_back(outerWire);
        gp_Pln pln;
        res.push_back(
            TopoShape(0, Hasher, getHistoryAlgorithm())
                .makeElementFace(wires, nullptr, nullptr, face.findPlane(pln) ? &pln : nullptr)
        );
    }
    return makeElementCompound(res, "", SingleShapeCompoundCreationPolicy::returnShape);
}

TopoShape& TopoShape::makeElementOffset2D(
    const TopoShape& shape,
    double offset,
    JoinType joinType,
    FillType fill,
    OpenResult allowOpenResult,
    bool intersection,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::Offset2D;
    }

    if (shape.isNull()) {
        FC_THROWM(Base::ValueError, "makeOffset2D: input shape is null!");
    }


    // OUTLINE OF MAKEOFFSET2D
    // * Prepare shapes to process
    // ** if _Shape is a compound, recursively call this routine for all subcompounds
    // ** if intrsection, dump all non-compound children into shapes to process; otherwise call this
    // routine recursively for all children
    // ** if _shape isn't a compound, dump it straight to shapes to process
    // * Test for shape types, and convert them all to wires
    // * find plane
    // * OCC call (BRepBuilderAPI_MakeOffset)
    // * postprocessing (facemaking):
    // ** convert offset result back to faces, if inputs were faces
    // ** OR do offset filling:
    // *** for closed wires, simply feed source wires + offset wires to smart facemaker
    // *** for open wires, try to connect source anf offset result by creating new edges (incomplete
    // implementation)
    // ** actual call to FaceMakerBullseye, unified for all facemaking.

    std::vector<TopoShape> shapesToProcess;
    std::vector<TopoShape> shapesToReturn;
    SingleShapeCompoundCreationPolicy outputPolicy = SingleShapeCompoundCreationPolicy::returnShape;
    if (shape.getShape().ShapeType() == TopAbs_COMPOUND) {
        if (!intersection) {
            // simply recursively process the children, independently
            for (TopoDS_Iterator it(shape.getShape()); it.More(); it.Next()) {
                shapesToReturn.push_back(
                    TopoShape(getHistoryAlgorithm(), it.Value())
                        .makeElementOffset2D(offset, joinType, fill, allowOpenResult, intersection, op)
                );
                outputPolicy = SingleShapeCompoundCreationPolicy::forceCompound;
            }
        }
        else {
            // collect non-compounds from this compound for collective offset. Process other shapes
            // independently.
            for (auto& s : shape.getSubTopoShapes()) {
                if (s.getShape().ShapeType() == TopAbs_COMPOUND) {
                    // recursively process subcompounds
                    shapesToReturn.push_back(
                        TopoShape(Tag, Hasher, getHistoryAlgorithm())
                            .makeElementOffset2D(s, offset, joinType, fill, allowOpenResult, intersection, op)
                    );
                    outputPolicy = SingleShapeCompoundCreationPolicy::forceCompound;
                }
                else {
                    shapesToProcess.push_back(s);
                }
            }
        }
    }
    else {
        shapesToProcess.push_back(shape);
    }

    if (shapesToProcess.size() > 0) {
        TopoShape res(Tag, Hasher, getHistoryAlgorithm());

        // although 2d offset supports offsetting a face directly, it seems there is
        // no way to do a collective offset of multiple faces. So, we are doing it
        // by getting all wires from the faces, and applying offsets to them, and
        // reassembling the faces later.
        std::vector<TopoShape> sourceWires;
        bool haveWires = false;
        bool haveFaces = false;
        for (auto& s : shapesToProcess) {
            const auto& sh = s.getShape();
            switch (sh.ShapeType()) {
                case TopAbs_EDGE:
                    sourceWires.push_back(s.makeElementWires());
                    haveWires = true;
                    break;
                case TopAbs_WIRE:
                    sourceWires.push_back(s);
                    haveWires = true;
                    break;
                case TopAbs_FACE: {
                    std::ranges::copy(s.getSubTopoShapes(TopAbs_WIRE), std::back_inserter(sourceWires));

                    haveFaces = true;
                } break;
                default:
                    FC_THROWM(
                        Base::TypeError,
                        "makeOffset2D: input shape is not an edge, wire or face or compound "
                        "of those."
                    );
                    break;
            }
        }
        if (haveWires && haveFaces) {
            FC_THROWM(
                Base::TypeError,
                "makeOffset2D: collective offset of a mix of wires and faces is not supported"
            );
        }
        if (haveFaces) {
            allowOpenResult = OpenResult::noOpenResult;
        }

        // find plane.
        gp_Pln workingPlane;
        if (!TopoShape(getHistoryAlgorithm())
                 .makeElementCompound(sourceWires, "", SingleShapeCompoundCreationPolicy::returnShape)
                 .findPlane(workingPlane)) {
            FC_THROWM(Base::CADKernelError, "makeOffset2D: wires are nonplanar or noncoplanar");
        }

        // do the offset..
        TopoShape offsetShape;
        if (fabs(offset) > Precision::Confusion()) {
            BRepOffsetAPI_MakeOffsetFix mkOffset(
                GeomAbs_JoinType(joinType),
                allowOpenResult == OpenResult::allowOpenResult
            );
            for (auto& w : sourceWires) {
                mkOffset.AddWire(TopoDS::Wire(w.getShape()));
            }
            try {
#if defined(__GNUC__) && defined(FC_OS_LINUX)
                Base::SignalException se;
#endif
                mkOffset.Perform(offset);
            }
            catch (Standard_Failure&) {
                throw;
            }
            catch (...) {
                FC_THROWM(
                    Base::CADKernelError,
                    "BRepOffsetAPI_MakeOffset has crashed! (Unknown exception caught)"
                );
            }
            if (mkOffset.Shape().IsNull()) {
                FC_THROWM(NullShapeException, "makeOffset2D: result of offsetting is null!");
            }

            // Copying shape to fix strange orientation behavior, OCC7.0.0. See bug #2699
            //  http://www.freecad.org/tracker/view.php?id=2699
            // Built on this shape's tag and algorithm, not the input's: the offset's own sections
            // carry the caller's tag (ops#32).
            offsetShape = TopoShape(Tag, Hasher, getHistoryAlgorithm())
                              .makeElementShape(mkOffset, shape, op)
                              .makeElementCopy();
        }
        else {
            offsetShape = TopoShape(Tag, Hasher, getHistoryAlgorithm())
                              .makeElementCompound(
                                  sourceWires,
                                  0,
                                  SingleShapeCompoundCreationPolicy::returnShape
                              );
        }

        std::vector<TopoShape> offsetWires;
        // interestingly, if wires are removed, empty compounds are returned by MakeOffset (as of
        // OCC 7.0.0) so, we just extract all nesting
        expandCompound(offsetShape, offsetWires);
        if (offsetWires.empty()) {
            FC_THROWM(Base::CADKernelError, "makeOffset2D: offset result has no wires.");
        }

        std::vector<TopoShape> wiresForMakingFaces;
        if (fill == FillType::noFill) {
            if (haveFaces) {
                wiresForMakingFaces
                    .insert(wiresForMakingFaces.end(), offsetWires.begin(), offsetWires.end());
            }
            else {
                shapesToReturn.insert(shapesToReturn.end(), offsetWires.begin(), offsetWires.end());
            }
        }
        else {
            // fill offset
            if (fabs(offset) < Precision::Confusion()) {
                FC_THROWM(Base::ValueError, "makeOffset2D: offset distance is zero. Can't fill offset.");
            }

            // filling offset. There are three major cases to consider:
            //  1. source wires and result wires are closed (simplest) -> make face
            //  from source wire + offset wire
            //
            //  2. source wire is open, but offset wire is closed (if not
            //  allowOpenResult). -> throw away source wire and make face right from
            //  offset result.
            //
            //  3. source and offset wire are both open (note that there may be
            //  closed islands in offset result) -> need connecting offset result to
            //  source wire with new edges

            // first, lets split apart closed and open wires.
            std::vector<TopoShape> closedWires;
            std::vector<TopoShape> openWires;
            for (auto& w : sourceWires) {
                if (BRep_Tool::IsClosed(TopoDS::Wire(w.getShape()))) {
                    closedWires.push_back(w);
                }
                else {
                    openWires.push_back(w);
                }
            }
            for (auto& w : offsetWires) {
                if (BRep_Tool::IsClosed(TopoDS::Wire(w.getShape()))) {
                    closedWires.push_back(w);
                }
                else {
                    openWires.push_back(w);
                }
            }

            wiresForMakingFaces
                .insert(wiresForMakingFaces.end(), closedWires.begin(), closedWires.end());
            if (allowOpenResult == OpenResult::noOpenResult || openWires.size() == 0) {
                // just ignore all open wires
            }
            else {
                // We need to connect open wires to form closed wires.

                // for now, only support offsetting one open wire -> there should be exactly two
                // open wires for connecting
                if (openWires.size() != 2) {
                    FC_THROWM(
                        Base::CADKernelError,
                        "makeOffset2D: collective offset with filling of multiple wires is "
                        "not supported yet."
                    );
                }

                TopoShape openWire1 = openWires.front();
                TopoShape openWire2 = openWires.back();

                // find open vertices
                BRepTools_WireExplorer xp;
                xp.Init(TopoDS::Wire(openWire1.getShape()));
                TopoDS_Vertex v1 = xp.CurrentVertex();
                for (; xp.More(); xp.Next()) {
                };
                TopoDS_Vertex v2 = xp.CurrentVertex();

                // find open vertices
                xp.Init(TopoDS::Wire(openWire2.getShape()));
                TopoDS_Vertex v3 = xp.CurrentVertex();
                for (; xp.More(); xp.Next()) {
                };
                TopoDS_Vertex v4 = xp.CurrentVertex();

                // check
                if (v1.IsNull()) {
                    FC_THROWM(NullShapeException, "v1 is null");
                }
                if (v2.IsNull()) {
                    FC_THROWM(NullShapeException, "v2 is null");
                }
                if (v3.IsNull()) {
                    FC_THROWM(NullShapeException, "v3 is null");
                }
                if (v4.IsNull()) {
                    FC_THROWM(NullShapeException, "v4 is null");
                }

                // assemble new wire

                // we want the connection order to be
                // v1 -> openWire1 -> v2 -> (new edge) -> v4 -> openWire2(rev) -> v3 -> (new edge)
                // -> v1 let's check if it's the case. If not, we reverse one wire and swap its
                // endpoints.

                if (fabs(gp_Vec(BRep_Tool::Pnt(v2), BRep_Tool::Pnt(v3)).Magnitude() - fabs(offset))
                    <= BRep_Tool::Tolerance(v2) + BRep_Tool::Tolerance(v3)) {
                    openWire2._Shape.Reverse();
                    std::swap(v3, v4);
                    v3.Reverse();
                    v4.Reverse();
                }
                else if (
                    (fabs(gp_Vec(BRep_Tool::Pnt(v2), BRep_Tool::Pnt(v4)).Magnitude() - fabs(offset))
                     <= BRep_Tool::Tolerance(v2) + BRep_Tool::Tolerance(v4))
                ) {
                    // orientation is as expected, nothing to do
                }
                else {
                    FC_THROWM(
                        Base::CADKernelError,
                        "makeOffset2D: fill offset: failed to establish open vertex relationship."
                    );
                }

                // now directions of open wires are aligned. Finally. make new wire!
                BRepBuilderAPI_MakeWire mkWire;
                // add openWire1
                BRepTools_WireExplorer it;
                for (it.Init(TopoDS::Wire(openWire1.getShape())); it.More(); it.Next()) {
                    mkWire.Add(it.Current());
                }
                // add first joining edge
                mkWire.Add(BRepBuilderAPI_MakeEdge(v2, v4).Edge());
                // add openWire2, in reverse order
                openWire2._Shape.Reverse();
                for (it.Init(TopoDS::Wire(openWire2.getShape())); it.More(); it.Next()) {
                    mkWire.Add(it.Current());
                }
                // add final joining edge
                mkWire.Add(BRepBuilderAPI_MakeEdge(v3, v1).Edge());
#if OCC_VERSION_HEX >= 0x070600
                mkWire.Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
                mkWire.Build();
#endif
                wiresForMakingFaces.push_back(
                    TopoShape(Tag, Hasher, getHistoryAlgorithm()).makeElementShape(mkWire, openWires, op)
                );
            }
        }

        // make faces
        if (wiresForMakingFaces.size() > 0) {
            TopoShape face(0, Hasher, getHistoryAlgorithm());
            face.makeElementFace(wiresForMakingFaces, nullptr, nullptr, &workingPlane);
            expandCompound(face, shapesToReturn);
        }
    }

    return makeElementCompound(shapesToReturn, op, outputPolicy);
}

TopoShape& TopoShape::makeElementThickSolid(
    const TopoShape& shape,
    const std::vector<TopoShape>& faces,
    double offset,
    double tol,
    bool intersection,
    bool selfInter,
    short offsetMode,
    JoinType join,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::Thicken;
    }

    // we do not offer tangent join type
    switch (join) {
        case JoinType::arc:
        case JoinType::intersection:
            break;
        default:
            join = JoinType::intersection;
    }

    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }

    if (faces.empty()) {
        FC_THROWM(NullShapeException, "Null input shape");
    }

    if (fabs(offset) <= 2 * tol) {
        *this = shape;
        return *this;
    }

    TopTools_ListOfShape remFace;
    for (auto& face : faces) {
        if (face.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        if (!shape.findShape(face.getShape())) {
            FC_THROWM(Base::CADKernelError, "face does not belong to the shape");
        }
        remFace.Append(face.getShape());
    }
    BRepOffsetAPI_MakeThickSolid mkThick;
    mkThick.MakeThickSolidByJoin(
        shape.getShape(),
        remFace,
        offset,
        tol,
        BRepOffset_Mode(offsetMode),
        intersection ? Standard_True : Standard_False,
        selfInter ? Standard_True : Standard_False,
        GeomAbs_JoinType(join)
    );
    MapperMaker mapper(mkThick);
    return makeShapeWithElementMap(
        canonicalFaceOrder(mkThick.Shape(), mapper, shape),
        mapper,
        {shape},
        op
    );
}


TopoShape& TopoShape::makeElementWires(
    const TopoShape& shape,
    const char* op,
    double tol,
    ConnectionPolicy policy,
    TopoShapeMap* output,
    ElementMapPolicy elementMapPolicy
)
{
    return makeElementWires(std::vector<TopoShape> {shape}, op, tol, policy, output, elementMapPolicy);
}


TopoShape& TopoShape::makeElementWires(
    const std::vector<TopoShape>& shapes,
    const char* op,
    double tol,
    ConnectionPolicy policy,
    TopoShapeMap* output,
    ElementMapPolicy elementMapPolicy
)
{
    if (!op) {
        op = Part::OpCodes::Wire;
    }
    if (tol < Precision::Confusion()) {
        tol = Precision::Confusion();
    }

    if (policy == ConnectionPolicy::requireSharedVertex) {
        // Can't use ShapeAnalysis_FreeBounds if not shared. It seems the output
        // edges are modified somehow, and it is not obvious how to map the
        // resulting edges.
        Handle(TopTools_HSequenceOfShape) hEdges = new TopTools_HSequenceOfShape();
        Handle(TopTools_HSequenceOfShape) hWires = new TopTools_HSequenceOfShape();
        for (const auto& shape : shapes) {
            for (const auto& edge : shape.getSubShapes(TopAbs_EDGE)) {
                hEdges->Append(edge);
            }
        }
        if (hEdges->Length() == 0) {
            FC_THROWM(NullShapeException, "Null shape");
        }
        Part::Fix_ShapeAnalysis_FreeBounds_ConnectEdgesToWires(hEdges, tol, Standard_True, hWires);
        if (hWires->Length() == 0) {
            FC_THROWM(NullShapeException, "Null shape");
        }

        std::vector<TopoShape> wires;
        for (int i = 1; i <= hWires->Length(); i++) {
            auto wire = hWires->Value(i);
            if (elementMapPolicy == ElementMapPolicy::Drop) {
                wires.emplace_back(wire);
            }
            else {
                wires.emplace_back(Tag, Hasher, wire);
                wires.back().mapSubElement(shapes, op);
            }
        }
        return makeElementCompound(
            wires,
            "",
            SingleShapeCompoundCreationPolicy::returnShape,
            elementMapPolicy
        );
    }

    std::vector<TopoShape> wires;
    std::list<TopoShape> edgeList;

    for (const auto& shape : shapes) {
        for (const auto& e : shape.getSubTopoShapes(TopAbs_EDGE)) {
            edgeList.emplace_back(e);
        }
    }

    std::vector<TopoShape> edges;
    edges.reserve(edgeList.size());
    wires.reserve(edgeList.size());

    // sort them together to wires
    while (!edgeList.empty()) {
        BRepBuilderAPI_MakeWire mkWire;
        // add and erase first edge
        edges.clear();
        edges.push_back(edgeList.front());
        mkWire.Add(TopoDS::Edge(edges.back().getShape()));
        edges.back().setShape(mkWire.Edge(), false);
        if (output) {
            (*output)[edges.back()] = edgeList.front();
        }
        edgeList.pop_front();

        // current new wire. V1 starts it bare, as upstream does: with this shape's hasher,
        // mapSubElement() would add an empty tag section after `op` to every name (ops#44)
        TopoShape new_wire = getHistoryAlgorithm() == App::HistoryAlgorithm::V1
            ? TopoShape {0, App::StringHasherRef(), mkWire.Wire(), App::HistoryAlgorithm::V1}
            : TopoShape {Tag, Hasher, mkWire.Wire(), getHistoryAlgorithm()};

        // try to connect each edge to the wire, the wire is complete if no more edges are
        // connectible
        bool found = true;
        while (found) {
            found = false;
            for (auto it = edgeList.begin(); it != edgeList.end(); ++it) {
                mkWire.Add(TopoDS::Edge(it->getShape()));
                if (mkWire.Error() != BRepBuilderAPI_DisconnectedWire) {
                    // edge added ==> remove it from list
                    found = true;
                    edges.push_back(*it);
                    // MakeWire will replace vertex of connected edge, which
                    // effectively creat a new edge. So we need to update the
                    // shape in order to preserve element mapping.
                    edges.back().setShape(mkWire.Edge(), false);
                    if (output) {
                        (*output)[edges.back()] = *it;
                    }
                    edgeList.erase(it);
                    new_wire.setShape(mkWire.Wire(), false);
                    break;
                }
            }
        }

        if (elementMapPolicy == ElementMapPolicy::Propagate) {
            new_wire.mapSubElement(edges, op);
        }
        new_wire.fix();

        wires.push_back(new_wire);
    }
    return makeElementCompound(
        wires,
        nullptr,
        SingleShapeCompoundCreationPolicy::returnShape,
        elementMapPolicy
    );
}

namespace
{


struct EdgePoints
{
    gp_Pnt v1, v2;
    std::list<TopoShape>::iterator it;
    const TopoShape* edge;
    bool closed {false};

    EdgePoints(std::list<TopoShape>::iterator it, double tol)
        : it(it)
        , edge(&*it)
    {
        TopExp_Explorer xp(it->getShape(), TopAbs_VERTEX);
        v1 = BRep_Tool::Pnt(TopoDS::Vertex(xp.Current()));
        xp.Next();
        if (xp.More()) {
            v2 = BRep_Tool::Pnt(TopoDS::Vertex(xp.Current()));
            closed = (v2.SquareDistance(v1) <= tol);
        }
        else {
            v2 = v1;
            closed = true;
        }
    }
};

}  // namespace

TopoShape TopoShape::reverseEdge(const TopoShape& edge)
{
    Standard_Real first = NAN;
    Standard_Real last = NAN;
    const Handle(Geom_Curve) & curve = BRep_Tool::Curve(TopoDS::Edge(edge.getShape()), first, last);
    first = curve->ReversedParameter(first);
    last = curve->ReversedParameter(last);
    TopoShape res(edge.getHistoryAlgorithm(), BRepBuilderAPI_MakeEdge(curve->Reversed(), last, first));
    auto edgeName = Data::IndexedName::fromConst("Edge", 1);
    if (auto mapped = edge.getMappedName(edgeName)) {
        res.elementMap()->setElementName(edgeName, mapped, res.Tag);
    }
    auto v1Name = Data::IndexedName::fromConst("Vertex", 1);
    auto v2Name = Data::IndexedName::fromConst("Vertex", 2);
    auto v1 = edge.getMappedName(v1Name);
    auto v2 = edge.getMappedName(v2Name);
    if (v1 && v2) {
        res.elementMap()->setElementName(v1Name, v2, res.Tag);
        res.elementMap()->setElementName(v2Name, v1, res.Tag);
    }
    else if (v1 && edge.countSubShapes(TopAbs_EDGE) == 1) {
        // It's possible an edge has only one vertex, so no need to reverse
        // the name
        res.elementMap()->setElementName(v1Name, v1, res.Tag);
    }
    else if (v1) {
        res.elementMap()->setElementName(v2Name, v1, res.Tag);
    }
    else if (v2) {
        res.elementMap()->setElementName(v1Name, v2, res.Tag);
    }
    return res;
};

std::deque<TopoShape> TopoShape::sortEdges(std::list<TopoShape>& edges, bool keepOrder, double tol)
{
    if (tol < Precision::Confusion()) {
        tol = Precision::Confusion();
    }
    double tol3d = tol * tol;

    std::list<EdgePoints> edgePoints;
    for (auto it = edges.begin(); it != edges.end(); ++it) {
        edgePoints.emplace_back(it, tol3d);
    }

    std::deque<TopoShape> sorted;
    if (edgePoints.empty()) {
        return sorted;
    }

    gp_Pnt first;
    gp_Pnt last;
    first = edgePoints.front().v1;
    last = edgePoints.front().v2;

    sorted.push_back(*edgePoints.front().edge);
    edges.erase(edgePoints.front().it);
    if (edgePoints.front().closed) {
        return sorted;
    }

    edgePoints.erase(edgePoints.begin());

    while (!edgePoints.empty()) {
        // search for adjacent edge
        std::list<EdgePoints>::iterator pEI;
        for (pEI = edgePoints.begin(); pEI != edgePoints.end(); ++pEI) {
            if (pEI->closed) {
                continue;
            }

            if (keepOrder && sorted.size() == 1) {
                if (pEI->v2.SquareDistance(first) <= tol3d || pEI->v1.SquareDistance(first) <= tol3d) {
                    sorted[0] = reverseEdge(sorted[0]);
                    std::swap(first, last);
                }
            }

            if (pEI->v1.SquareDistance(last) <= tol3d) {
                last = pEI->v2;
                sorted.push_back(*pEI->edge);
                edges.erase(pEI->it);
                edgePoints.erase(pEI);
                pEI = edgePoints.begin();
                break;
            }
            if (pEI->v2.SquareDistance(first) <= tol3d) {
                sorted.push_front(*pEI->edge);
                first = pEI->v1;
                edges.erase(pEI->it);
                edgePoints.erase(pEI);
                pEI = edgePoints.begin();
                break;
            }
            if (pEI->v2.SquareDistance(last) <= tol3d) {
                last = pEI->v1;
                sorted.push_back(reverseEdge(*pEI->edge));
                edges.erase(pEI->it);
                edgePoints.erase(pEI);
                pEI = edgePoints.begin();
                break;
            }
            if (pEI->v1.SquareDistance(first) <= tol3d) {
                first = pEI->v2;
                sorted.push_front(reverseEdge(*pEI->edge));
                edges.erase(pEI->it);
                edgePoints.erase(pEI);
                pEI = edgePoints.begin();
                break;
            }
        }

        if ((pEI == edgePoints.end()) || (last.SquareDistance(first) <= tol3d)) {
            // no adjacent edge found or polyline is closed
            return sorted;
        }
    }

    return sorted;
}

TopoShape& TopoShape::makeElementOrderedWires(
    const std::vector<TopoShape>& shapes,
    const char* op,
    double tol,
    TopoShapeMap* output
)
{
    if (!op) {
        op = Part::OpCodes::Wire;
    }
    if (tol < Precision::Confusion()) {
        tol = Precision::Confusion();
    }

    std::vector<TopoShape> wires;
    std::list<TopoShape> edgeList;

    auto shape = TopoShape(getHistoryAlgorithm())
                     .makeElementCompound(shapes, "", SingleShapeCompoundCreationPolicy::returnShape);
    for (auto& edge : shape.getSubTopoShapes(TopAbs_EDGE)) {
        edgeList.push_back(edge);
    }

    while (!edgeList.empty()) {
        BRepBuilderAPI_MakeWire mkWire;
        std::vector<TopoShape> edges;
        for (auto& edge : sortEdges(edgeList, true, tol)) {
            edges.push_back(edge);
            mkWire.Add(TopoDS::Edge(edge.getShape()));
            // MakeWire will replace vertex of connected edge, which
            // effectively creat a new edge. So we need to update the shape
            // in order to preserve element mapping.
            edges.back().setShape(mkWire.Edge(), false);
            if (output) {
                (*output)[edges.back()] = edge;
            }
        }
        wires.emplace_back(mkWire.Wire());
        wires.back().mapSubElement(edges, op);
    }
    return makeElementCompound(wires, nullptr, SingleShapeCompoundCreationPolicy::returnShape);
}

bool TopoShape::_makeElementTransform(
    const TopoShape& shape,
    const Base::Matrix4D& mat,
    const char* op,
    CheckScale checkScale,
    CopyType copy
)
{
    if (checkScale == CheckScale::checkScale) {
        auto scaleType = mat.hasScale();
        if (scaleType != Base::ScaleType::NoScaling && scaleType != Base::ScaleType::Uniform) {
            makeElementGTransform(shape, mat, op, copy);
            return true;
        }
    }
    makeElementTransform(shape, convert(mat), op, copy);
    return false;
}

TopoShape& TopoShape::makeElementTransform(
    const TopoShape& shape,
    const gp_Trsf& trsf,
    const char* op,
    CopyType copy
)
{
    if (copy == CopyType::noCopy) {
        // OCCT checks the ScaleFactor against gp::Resolution() which is DBL_MIN!!!
        copy = trsf.ScaleFactor() * trsf.HVectorialPart().Determinant() < 0.
                || Abs(Abs(trsf.ScaleFactor()) - 1) > Precision::Confusion()
            ? CopyType::copy
            : CopyType::noCopy;
    }
    TopoShape tmp(shape);
    if (copy == CopyType::copy) {
        if (shape.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }

        BRepBuilderAPI_Transform mkTrf(shape.getShape(), trsf, Standard_True);
        // TODO: calling Moved() is to make sure the shape has some Location,
        // which is necessary for STEP export to work. However, if we reach
        // here, it probably means BRepBuilderAPI_Transform has modified
        // underlying shapes (because of scaling), it will break compound child
        // parent relationship anyway. In short, STEP import/export will most
        // likely break badly if there is any scaling involved
        tmp.setShape(mkTrf.Shape().Moved(gp_Trsf()), false);
    }
    else {
        tmp.move(trsf);
    }

    if (op || (shape.Tag && shape.Tag != Tag)) {
        setShape(tmp._Shape);
        initCache();
        if (!Hasher) {
            Hasher = tmp.Hasher;
        }
        copyElementMap(tmp, op);
    }
    else {
        *this = tmp;
    }
    return *this;
}

TopoShape& TopoShape::makeElementGTransform(
    const TopoShape& shape,
    const Base::Matrix4D& mat,
    const char* op,
    CopyType copy
)
{
    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null input shape");
    }

    // if(!op) op = Part::OpCodes::Gtransform;
    gp_GTrsf matrix;
    matrix.SetValue(1, 1, mat[0][0]);
    matrix.SetValue(2, 1, mat[1][0]);
    matrix.SetValue(3, 1, mat[2][0]);
    matrix.SetValue(1, 2, mat[0][1]);
    matrix.SetValue(2, 2, mat[1][1]);
    matrix.SetValue(3, 2, mat[2][1]);
    matrix.SetValue(1, 3, mat[0][2]);
    matrix.SetValue(2, 3, mat[1][2]);
    matrix.SetValue(3, 3, mat[2][2]);
    matrix.SetValue(1, 4, mat[0][3]);
    matrix.SetValue(2, 4, mat[1][3]);
    matrix.SetValue(3, 4, mat[2][3]);

    // geometric transformation
    TopoShape tmp(shape);
    BRepBuilderAPI_GTransform mkTrf(shape.getShape(), matrix, copy == CopyType::copy);
    tmp.setShape(mkTrf.Shape(), false);
    if (op || (shape.Tag && shape.Tag != Tag)) {
        setShape(tmp._Shape);
        initCache();
        if (!Hasher) {
            Hasher = tmp.Hasher;
        }
        copyElementMap(tmp, op);
    }
    else {
        *this = tmp;
    }
    return *this;
}

TopoShape& TopoShape::makeElementCopy(
    const TopoShape& shape,
    const char* op,
    bool copyGeom,
    bool copyMesh,
    ElementMapPolicy elementMapPolicy
)
{
    if (shape.isNull()) {
        return *this;
    }

    TopoShape tmp(shape);
    tmp.setShape(BRepBuilderAPI_Copy(shape.getShape(), copyGeom, copyMesh).Shape(), false);

    if (elementMapPolicy == ElementMapPolicy::Drop) {
        setShape(tmp._Shape);
        dropElementNaming();
        return *this;
    }

    if (op || (shape.Tag && shape.Tag != Tag)) {
        setShape(tmp._Shape);
        initCache();
        if (!Hasher) {
            Hasher = tmp.Hasher;
        }
        copyElementMap(tmp, op);
    }
    else {
        *this = tmp;
    }
    return *this;
}

const std::vector<TopoDS_Shape>& MapperSewing::modified(const TopoDS_Shape& s) const
{
    _res.clear();
    try {
        const auto& shape = maker.Modified(s);
        if (!shape.IsNull() && !shape.IsSame(s)) {
            _res.push_back(shape);
        }
        else {
            const auto& sshape = maker.ModifiedSubShape(s);
            if (!sshape.IsNull() && !sshape.IsSame(s)) {
                _res.push_back(sshape);
            }
        }
    }
    catch (const Standard_Failure& e) {
        if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
            FC_WARN("Exception on shape mapper: " << e.GetMessageString());
        }
    }
    return _res;
}

struct MapperThruSections: MapperMaker
{
    TopoShape firstProfile;
    TopoShape lastProfile;

    MapperThruSections(BRepOffsetAPI_ThruSections& tmaker, const std::vector<TopoShape>& profiles)
        : MapperMaker(tmaker)
    {
        if (!tmaker.FirstShape().IsNull()) {
            firstProfile = profiles.front();
        }
        if (!tmaker.LastShape().IsNull()) {
            lastProfile = profiles.back();
        }
    }
    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& s) const override
    {
        MapperMaker::generated(s);
        if (!_res.empty()) {
            return _res;
        }
        try {
            auto& tmaker = dynamic_cast<BRepOffsetAPI_ThruSections&>(maker);
            auto shape = tmaker.GeneratedFace(s);
            if (!shape.IsNull()) {
                _res.push_back(shape);
            }
            if (firstProfile.getShape().IsSame(s) || firstProfile.findShape(s)) {
                _res.push_back(tmaker.FirstShape());
            }
            else if (lastProfile.getShape().IsSame(s) || lastProfile.findShape(s)) {
                _res.push_back(tmaker.LastShape());
            }
        }
        catch (const Standard_Failure& e) {
            if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
                FC_WARN("Exception on shape mapper: " << e.GetMessageString());
            }
        }
        return _res;
    }
};

// The mapper of the BRepFeat makers' up-to results: a Pad's up-to-face (BRepFeat_MakePrism) and,
// since ops#240, a Revolution's or Groove's (BRepFeat_MakeRevol). The V2 mapper works from shape
// identity alone: the sources' edges and vertices that are still the same shapes in the result.
struct MapperPrism: MapperMaker
{
    App::HistoryAlgorithm historyAlgorithm = App::HistoryAlgorithm::V2;

    // members for V1 algorithm mapper
    std::unordered_map<TopoDS_Shape, TopoDS_Shape, ShapeHasher, ShapeHasher> vertexMap;
    ShapeMapper::ShapeMap edgeMap;

    // members for V2 algorithm mapper. The claims are made in source order (ops#19); the maps only
    // look up, and generatedElements' hashes are seeded (NamingHash.h) to keep it that way.
    std::unordered_map<TopoDS_Shape, TopoDS_Shape, ShapeHasher, ShapeHasher> projectedElements;
    std::unordered_map<TopoDS_Shape, TopoDS_Shape, NamingHasher<ShapeHasher>, ShapeHasher>
        generatedElements;

    MapperPrism(
        BRepFeat_Form& maker,
        const TopoShape& upTo,
        const std::vector<TopoShape>& sourceTopoShapes,
        const App::HistoryAlgorithm& historyVersion
    )
        : MapperMaker(maker)
        , historyAlgorithm(historyVersion)
    {
        ZoneScoped;
        (void)upTo;

        if (historyAlgorithm == App::HistoryAlgorithm::V1) {
            std::vector<TopoShape> shapes;
            for (TopTools_ListIteratorOfListOfShape it(maker.FirstShape()); it.More(); it.Next()) {
                shapes.push_back(it.Value());
            }

            if (shapes.size()) {
                // It seems that BRepFeat_MakePrism::newEdges() does not return
                // edges generated by extruding the profile vertices. The following
                // code assumes BRepFeat_MakePrism::myFShape is the profile, and
                // FirstShape() returns the corresponding faces in the new shape,
                // i.e. the bottom profile, and add all edges that shares a
                // vertex with the profiles as new edges.

                std::unordered_set<TopoDS_Shape, ShapeHasher, ShapeHasher> edgeSet;
                TopoShape bottom;
                bottom.makeElementCompound(
                    shapes,
                    nullptr,
                    TopoShape::SingleShapeCompoundCreationPolicy::returnShape
                );
                TopoShape shape(maker.Shape());
                for (auto& vertex : bottom.getSubShapes(TopAbs_VERTEX)) {
                    for (auto& e : shape.findAncestorsShapes(vertex, TopAbs_EDGE)) {
                        // Make sure to not visit the same edge twice.
                        // And check only edge that are not found in the bottom profile
                        if (!edgeSet.insert(e).second && !bottom.findShape(e)) {
                            auto otherVertex = TopExp::FirstVertex(TopoDS::Edge(e));
                            if (otherVertex.IsSame(vertex)) {
                                otherVertex = TopExp::LastVertex(TopoDS::Edge(e));
                            }
                            vertexMap[vertex] = otherVertex;
                        }
                    }
                }

                // Now map each edge in the bottom profile to the extrueded top
                // profile. vertexMap created above gives us each pair of vertexes
                // of the bottom and top profile. We use it to find the
                // corresponding edges in the top profile, what an extra criteria
                // for disambiguation. That is, the pair of edges (bottom and top)
                // must belong to the same face.
                for (auto& edge : bottom.getSubShapes(TopAbs_EDGE)) {
                    std::vector<int> indices;
                    auto first = TopExp::FirstVertex(TopoDS::Edge(edge));
                    auto last = TopExp::LastVertex(TopoDS::Edge(edge));
                    auto itFirst = vertexMap.find(first);
                    auto itLast = vertexMap.find(last);
                    if (itFirst == vertexMap.end() || itLast == vertexMap.end()) {
                        continue;
                    }
                    std::vector<TopoShape> faces;
                    for (int idx : shape.findAncestors(edge, TopAbs_FACE)) {
                        faces.push_back(shape.getSubTopoShape(TopAbs_FACE, idx));
                    }
                    if (faces.empty()) {
                        continue;
                    }
                    for (int idx : shape.findAncestors(itFirst->second, TopAbs_EDGE)) {
                        auto e = shape.getSubTopoShape(TopAbs_EDGE, idx);
                        if (!e.findShape(itLast->second)) {
                            continue;
                        }
                        for (auto& face : faces) {
                            if (!face.findShape(e.getShape())) {
                                continue;
                            }
                            auto& entry = edgeMap[edge];
                            if (entry.shapeSet.insert(e.getShape()).second) {
                                entry.shapes.push_back(e.getShape());
                            }
                        }
                    }
                }
            }
        }
        else if (historyAlgorithm == App::HistoryAlgorithm::V2) {
            // Source edges and vertices with their shapes in the result, in source order: type
            // (face, edge, vertex), input, index in the input. Which source claims which result
            // element below depends on this order.
            std::vector<std::pair<TopoDS_Shape, TopoDS_Shape>> sourceElementRemap;
            std::unordered_map<TopoDS_Shape, std::size_t, NamingHasher<ShapeHasher>, ShapeHasher>
                sourceElementRemapIndex;
            // generatedElements' entries in the order they were claimed
            std::vector<std::pair<TopoDS_Shape, TopoDS_Shape>> generatedElementsInOrder;
            std::unordered_map<TopoDS_Shape, TopoDS_Shape, ShapeHasher, ShapeHasher> lowerSourceToFaceMap;
            std::unordered_set<TopoDS_Shape, ShapeHasher, ShapeHasher> allMappedElements;
            std::array<TopAbs_ShapeEnum, 3> mapTypes = {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX};
            const TopoDS_Shape& extrudedShape = maker.Shape();

            TopTools_IndexedDataMapOfShapeListOfShape edgeToFaceMap;
            TopTools_IndexedDataMapOfShapeListOfShape vertexToEdgeMap;

            for (const TopAbs_ShapeEnum& type : mapTypes) {
                TopTools_IndexedMapOfShape extrudedShapeMap;
                TopExp::MapShapes(extrudedShape, type, extrudedShapeMap);

                for (const TopoShape& sourceTopoShape : sourceTopoShapes) {
                    TopTools_IndexedMapOfShape sourceShapeMap;
                    TopExp::MapShapes(sourceTopoShape.getShape(), type, sourceShapeMap);

                    for (int sourceElementIdx = 1; sourceElementIdx <= sourceShapeMap.Extent();
                         sourceElementIdx++) {
                        const TopoDS_Shape& sourceShape = sourceShapeMap(sourceElementIdx);

                        allMappedElements.insert(sourceShape);

                        if (sourceShape.ShapeType() == TopAbs_FACE) {
                            TopTools_IndexedMapOfShape faceEdgeMap;
                            TopExp::MapShapes(sourceShape, TopAbs_EDGE, faceEdgeMap);

                            for (int sourceEdgeIdx = 1; sourceEdgeIdx <= faceEdgeMap.Extent();
                                 sourceEdgeIdx++) {
                                auto emplaceIterator = lowerSourceToFaceMap.try_emplace(
                                    faceEdgeMap(sourceEdgeIdx),
                                    sourceShape
                                );

                                if (!emplaceIterator.second) {
                                    // don't allow duplicates
                                    lowerSourceToFaceMap.erase(emplaceIterator.first);
                                }
                            }
                        }
                        else {
                            for (int extrudedElementIdx = 1;
                                 extrudedElementIdx <= extrudedShapeMap.Extent();
                                 extrudedElementIdx++) {
                                const TopoDS_Shape& currentExtrusionShape = extrudedShapeMap(
                                    extrudedElementIdx
                                );

                                if (currentExtrusionShape.IsSame(sourceShape)) {
                                    allMappedElements.insert(sourceShape);
                                    auto remapIterator = sourceElementRemapIndex.try_emplace(
                                        sourceShape,
                                        sourceElementRemap.size()
                                    );
                                    if (remapIterator.second) {
                                        sourceElementRemap.emplace_back(
                                            sourceShape,
                                            currentExtrusionShape
                                        );
                                    }
                                    else {
                                        sourceElementRemap[remapIterator.first->second].second
                                            = currentExtrusionShape;
                                    }
                                    break;
                                }
                            }
                        }
                    }
                }
            }

            TopExp::MapShapesAndAncestors(extrudedShape, TopAbs_EDGE, TopAbs_FACE, edgeToFaceMap);

            TopExp::MapShapesAndAncestors(extrudedShape, TopAbs_VERTEX, TopAbs_EDGE, vertexToEdgeMap);

            // map extruded shapes (edge -> face, vertex -> edge)
            for (const auto& sourceShapeEntry : sourceElementRemap) {
                const TopAbs_ShapeEnum type = sourceShapeEntry.first.ShapeType();
                const TopTools_ListOfShape* ancestors = nullptr;

                if (type == TopAbs_EDGE) {
                    ancestors = &edgeToFaceMap.FindFromKey(sourceShapeEntry.second);
                }
                else if (type == TopAbs_VERTEX) {
                    ancestors = &vertexToEdgeMap.FindFromKey(sourceShapeEntry.second);
                }

                if (ancestors != nullptr) {
                    TopTools_ListOfShape::Iterator ancestorsIterator {*ancestors};

                    for (; ancestorsIterator.More(); ancestorsIterator.Next()) {
                        const TopoDS_Shape& ancestor = ancestorsIterator.Value();

                        if (allMappedElements.count(ancestor) == 0) {
                            generatedElements[sourceShapeEntry.first] = ancestor;
                            generatedElementsInOrder.emplace_back(sourceShapeEntry.first, ancestor);
                            allMappedElements.insert(ancestor);

                            break;
                        }
                    }
                }
            }

            for (const auto& generatedElementEntry : generatedElementsInOrder) {
                TopTools_IndexedMapOfShape projectedElementMap;
                TopExp::MapShapes(
                    generatedElementEntry.second,
                    generatedElementEntry.first.ShapeType(),
                    projectedElementMap
                );

                for (int projectedShapeIdx = 1; projectedShapeIdx <= projectedElementMap.Extent();
                     projectedShapeIdx++) {
                    const TopoDS_Shape& projectedShape = projectedElementMap(projectedShapeIdx);

                    if (allMappedElements.count(projectedShape) == 0) {
                        projectedElements[generatedElementEntry.first] = projectedShape;
                        allMappedElements.insert(projectedShape);

                        if (projectedShape.ShapeType() == TopAbs_EDGE) {
                            const auto& edgeToFaceIterator = lowerSourceToFaceMap.find(
                                generatedElementEntry.first
                            );

                            if (edgeToFaceIterator != lowerSourceToFaceMap.end()) {
                                const TopTools_ListOfShape& faceAncestors
                                    = edgeToFaceMap.FindFromKey(projectedShape);
                                TopTools_ListOfShape::Iterator faceAncestorsIterator {faceAncestors};

                                for (; faceAncestorsIterator.More(); faceAncestorsIterator.Next()) {
                                    const TopoDS_Shape& projectedFace = faceAncestorsIterator.Value();

                                    if (allMappedElements.count(projectedFace) == 0) {
                                        projectedElements[edgeToFaceIterator->second] = projectedFace;
                                        allMappedElements.insert(projectedFace);
                                    }
                                }
                            }
                        }

                        break;
                    }
                }
            }
        }
    }
    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& s) const override
    {
        _res.clear();

        if (historyAlgorithm == App::HistoryAlgorithm::V1) {
            switch (s.ShapeType()) {
                case TopAbs_VERTEX: {
                    auto it = vertexMap.find(s);
                    if (it != vertexMap.end()) {
                        _res.push_back(it->second);
                        return _res;
                    }
                    break;
                }
                case TopAbs_EDGE: {
                    auto it = edgeMap.find(s);
                    if (it != edgeMap.end()) {
                        return it->second.shapes;
                    }
                    break;
                }
                default:
                    break;
            }
            MapperMaker::generated(s);
        }
        else if (historyAlgorithm == App::HistoryAlgorithm::V2) {
            auto generatedMapIterator = generatedElements.find(s);

            if (generatedMapIterator != generatedElements.end()
                && !generatedMapIterator->second.IsNull()) {
                _res.push_back(generatedMapIterator->second);
            }
        }

        return _res;
    }

    const std::vector<TopoDS_Shape>& projected(const TopoDS_Shape& s) const override
    {
        _res.clear();

        if (historyAlgorithm == App::HistoryAlgorithm::V2) {
            auto projectedMapIterator = projectedElements.find(s);

            if (projectedMapIterator != projectedElements.end()
                && !projectedMapIterator->second.IsNull()) {
                _res.push_back(projectedMapIterator->second);
            }
        }

        return _res;
    };
};

TopoShape& TopoShape::makeElementFilledFace(
    const std::vector<TopoShape>& _shapes,
    const BRepFillingParams& params,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::FilledFace;
    }
    BRepOffsetAPI_MakeFilling maker(
        params.degree,
        params.ptsoncurve,
        params.numiter,
        params.anisotropy,
        params.tol2d,
        params.tol3d,
        params.tolG1,
        params.tolG2,
        params.maxdeg,
        params.maxseg
    );

    if (!params.surface.isNull() && params.surface.getShape().ShapeType() == TopAbs_FACE) {
        maker.LoadInitSurface(TopoDS::Face(params.surface.getShape()));
    }

    std::vector<TopoShape> shapes;
    for (auto& s : _shapes) {
        expandCompound(s, shapes);
    }

    TopoShapeMap output;
    auto getOrder = [&](const TopoDS_Shape& s) {
        auto it = params.orders.find(s);
        if (it == params.orders.end()) {
            auto iter = output.find(s);
            if (iter != output.end()) {
                it = params.orders.find(iter->second.getShape());
            }
        }
        if (it != params.orders.end()) {
            return static_cast<GeomAbs_Shape>(it->second);
        }
        return GeomAbs_C0;
    };

    auto getSupport = [&](const TopoDS_Shape& s) {
        TopoDS_Face support;
        auto it = params.supports.find(s);
        if (it == params.supports.end()) {
            auto iter = output.find(s);
            if (iter != output.end()) {
                it = params.supports.find(iter->second.getShape());
            }
        }
        if (it != params.supports.end()) {
            if (!it->second.IsNull() && it->second.ShapeType() == TopAbs_FACE) {
                support = TopoDS::Face(it->second);
            }
        }
        return support;
    };

    auto findBoundary = [](std::vector<TopoShape>& shapes) -> TopoShape {
        // Find a wire (preferably a closed one) to be used as the boundary.
        int i = -1;
        int boundIdx = -1;
        for (auto& s : shapes) {
            ++i;
            if (s.isNull() || !s.hasSubShape(TopAbs_EDGE) || s.shapeType() != TopAbs_WIRE) {
                continue;
            }
            if (BRep_Tool::IsClosed(TopoDS::Wire(s.getShape()))) {
                boundIdx = i;
                break;
            }
            else if (boundIdx < 0) {
                boundIdx = i;
            }
        }
        if (boundIdx >= 0) {
            auto res = shapes[boundIdx];
            shapes.erase(shapes.begin() + boundIdx);
            return res;
        }
        return TopoShape();
    };

    TopoShape bound;
    std::vector<TopoShape> wires;
    if (params.boundary_begin >= 0 && params.boundary_end > params.boundary_begin
        && params.boundary_end <= (int)shapes.size()) {
        if (params.boundary_end - 1 != params.boundary_begin
            || shapes[params.boundary_begin].shapeType() != TopAbs_WIRE) {
            std::vector<TopoShape> edges;
            edges.insert(
                edges.end(),
                shapes.begin() + params.boundary_begin,
                shapes.begin() + params.boundary_end
            );
            wires = TopoShape(0, Hasher, getHistoryAlgorithm())
                        .makeElementWires(edges, "", 0.0, ConnectionPolicy::mergeWithTolerance, &output)
                        .getSubTopoShapes(TopAbs_WIRE);
            shapes.erase(shapes.begin() + params.boundary_begin, shapes.begin() + params.boundary_end);
        }
    }
    else {
        bound = findBoundary(shapes);
        if (bound.isNull()) {
            // If no boundary is found, then try to build one.
            std::vector<TopoShape> edges;
            for (auto it = shapes.begin(); it != shapes.end();) {
                if (it->shapeType(true) == TopAbs_EDGE) {
                    edges.push_back(*it);
                    it = shapes.erase(it);
                }
                else {
                    ++it;
                }
            }
            if (edges.size()) {
                wires = TopoShape(0, Hasher, getHistoryAlgorithm())
                            .makeElementWires(edges, "", 0.0, ConnectionPolicy::mergeWithTolerance, &output)
                            .getSubTopoShapes(TopAbs_WIRE);
            }
        }
    }

    if (bound.isNull()) {
        bound = findBoundary(wires);
    }

    if (bound.isNull()) {
        FC_THROWM(Base::CADKernelError, "No boundary wire");
    }

    // Since we've only selected one wire for boundary, return all the
    // other edges in shapes to be added as non boundary constraints
    shapes.insert(shapes.end(), wires.begin(), wires.end());

    // Must fix wire connection to avoid OCC crash in BRepFill_Filling.cxx WireFromList()
    // https://github.com/Open-Cascade-SAS/OCCT/blob/1c96596ae7ba120a678021db882857e289c73947/src/BRepFill/BRepFill_Filling.cxx#L133
    // The reason of crash is because the wire connection tolerance is too big.
    // The crash can be fixed by simply checking itl.More() before calling Remove().
    bound.fix(Precision::Confusion(), Precision::Confusion(), Precision::Confusion());

    for (const auto& e : bound.getOrderedEdges()) {
        maker.Add(
            TopoDS::Edge(e.getShape()),
            getSupport(e.getShape()),
            getOrder(e.getShape()),
            /*IsBound*/ Standard_True
        );
    }

    for (const auto& s : shapes) {
        if (s.isNull()) {
            continue;
        }
        const auto& sh = s.getShape();
        if (sh.ShapeType() == TopAbs_WIRE) {
            for (const auto& e : s.getSubShapes(TopAbs_EDGE)) {
                maker.Add(
                    TopoDS::Edge(e),
                    getSupport(e),
                    getOrder(e),
                    /*IsBound*/ Standard_False
                );
            }
        }
        else if (sh.ShapeType() == TopAbs_EDGE) {
            maker.Add(
                TopoDS::Edge(sh),
                getSupport(sh),
                getOrder(sh),
                /*IsBound*/ Standard_False
            );
        }
        else if (sh.ShapeType() == TopAbs_FACE) {
            maker.Add(TopoDS::Face(sh), getOrder(sh));
        }
        else if (sh.ShapeType() == TopAbs_VERTEX) {
            maker.Add(BRep_Tool::Pnt(TopoDS::Vertex(sh)));
        }
    }

#if OCC_VERSION_HEX >= 0x070600
    maker.Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
    maker.Build();
#endif
    if (!maker.IsDone()) {
        FC_THROWM(Base::CADKernelError, "Failed to created face by filling edges");
    }
    return makeElementShape(maker, _shapes, op);
}

// TODO:  This method does not appear to ever be called in the codebase, and it is probably
// broken, because using TopoShape() with no parameters means the result will not have an
// element Map.
// TopoShape& TopoShape::makeElementSolid(const std::vector<TopoShape>& shapes, const char* op)
//{
//    return makeElementSolid(TopoShape().makeElementCompound(shapes), op);
//}

TopoShape& TopoShape::makeElementSolid(const TopoShape& shape, const char* op)
{
    if (!op) {
        op = Part::OpCodes::Solid;
    }

    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }

    // first, if we were given a compsolid, try making a solid out of it
    TopoDS_CompSolid compsolid;
    int count = 0;
    for (const auto& s : shape.getSubShapes(TopAbs_COMPSOLID)) {
        ++count;
        compsolid = TopoDS::CompSolid(s);
        if (count > 1) {
            break;
        }
    }
    if (count == 0) {
        // no compsolids. Get shells...
        BRepBuilderAPI_MakeSolid mkSolid;
        count = 0;
        for (const auto& s : shape.getSubShapes(TopAbs_SHELL)) {
            ++count;
            mkSolid.Add(TopoDS::Shell(s));
        }

        if (count == 0) {  // no shells?
            FC_THROWM(Base::CADKernelError, "No shells or compsolids found in shape");
        }

        if (!mkSolid.IsDone()) {
            FC_THROWM(Base::CADKernelError, "Failed to create a solid in makeElementSolid!");
        }

        makeElementShape(mkSolid, shape, op);

        TopoDS_Solid solid = TopoDS::Solid(_Shape);
        MassProperties::orientClosedSolid(solid);
        setShape(solid, false);
    }
    else if (count == 1) {
        BRepBuilderAPI_MakeSolid mkSolid(compsolid);
        makeElementShape(mkSolid, shape, op);
    }
    else {  // if (count > 1)
        FC_THROWM(
            Base::CADKernelError,
            "Only one compsolid can be accepted. "
            "Provided shape has more than one compsolid."
        );
    }
    return *this;
}

TopoShape& TopoShape::makeElementMirror(const TopoShape& shape, const gp_Ax2& ax2, const char* op)
{
    if (!op) {
        op = Part::OpCodes::Mirror;
    }

    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    gp_Trsf mat;
    mat.SetMirror(ax2);
    // Note: Do NOT extract and pre-multiply the shape's Location/Placement here.
    // BRepBuilderAPI_Transform correctly handles shapes with Location already.
    // Pre-multiplying would double-apply the placement, causing incorrect results
    // for shapes with non-identity Placement. See GitHub issue #20834.
    BRepBuilderAPI_Transform mkTrf(shape.getShape(), mat);
    return makeElementShape(mkTrf, shape, op);
}

TopoShape& TopoShape::makeElementSlice(
    const TopoShape& shape,
    const Base::Vector3d& dir,
    double distance,
    const char* op
)
{
    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    TopoCrossSection cs(dir.x, dir.y, dir.z, shape, op);
    TopoShape res = cs.slice(1, distance);
    setShape(res._Shape);
    Hasher = res.Hasher;
    resetElementMap(res.elementMap());
    return *this;
}

TopoShape& TopoShape::makeElementSlices(
    const TopoShape& shape,
    const Base::Vector3d& dir,
    const std::vector<double>& distances,
    const char* op
)
{
    std::vector<TopoShape> wires;
    TopoCrossSection cs(dir.x, dir.y, dir.z, shape, op);
    int index = 0;
    for (auto& distance : distances) {
        cs.slice(++index, distance, wires);
    }
    return makeElementCompound(wires, op, SingleShapeCompoundCreationPolicy::returnShape);
}

TopoShape& TopoShape::replaceElementShape(
    const TopoShape& shape,
    const std::vector<std::pair<TopoShape, TopoShape>>& s
)
{
    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    BRepTools_ReShape reshape;
    std::vector<TopoShape> shapes;
    shapes.reserve(s.size() + 1);
    for (auto& v : s) {
        if (v.first.isNull() || v.second.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        reshape.Replace(v.first.getShape(), v.second.getShape());
        shapes.push_back(v.second);
    }
    // TODO:  This does not work when replacing a shape in a compound.  Should we replace with
    // something else?
    //  Note that remove works with a compound.
    shapes.push_back(shape);
    setShape(reshape.Apply(shape.getShape(), TopAbs_SHAPE));
    mapSubElement(shapes);
    return *this;
}

TopoShape& TopoShape::removeElementShape(const TopoShape& shape, const std::vector<TopoShape>& s)
{
    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    BRepTools_ReShape reshape;
    for (auto& sh : s) {
        if (sh.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        reshape.Remove(sh.getShape());
    }
    setShape(reshape.Apply(shape.getShape(), TopAbs_SHAPE));
    mapSubElement(shape);
    return *this;
}

namespace
{
/** Builds a fillet or chamfer maker: true when OCCT fails with StdFail_NotDone, the failure the
 * exact construction may build instead (ops#300). Other exceptions propagate as before.
 * @param error Receives what OCCT threw, if it threw
 * @param contour Receives the edges of the maker's contours, read before the build
 */
bool buildDressUpFailed(
    BRepFilletAPI_LocalOperation& maker,
    std::exception_ptr& error,
    std::vector<TopoDS_Shape>& contour
)
{
    for (int i = 1; i <= maker.NbContours(); ++i) {
        for (int j = 1; j <= maker.NbEdges(i); ++j) {
            contour.push_back(maker.Edge(i, j));
        }
    }
    try {
        maker.Build();
    }
    catch (const StdFail_NotDone&) {
        error = std::current_exception();
        return true;
    }
    return !maker.IsDone();
}

/** Whether OCCT built the dress-up invalid without an error (ops#297), which the exact construction
 * may build instead. If it doesn't, the invalid result is returned as before, and the feature's
 * check (Part::checkDressUp()) repairs it or fails.
 */
bool builtInvalid(BRepFilletAPI_LocalOperation& maker)
{
    return !BRepCheck_Analyzer(maker.Shape()).IsValid();
}

/** Raises OCCT's error for a maker that failed, as before the exact construction: what it threw,
 * or StdFail_NotDone. The maker must not be built again: ChFi3d crashes on a second build after a
 * failed one.
 */
[[noreturn]] void raiseDressUpError(
    const BRepBuilderAPI_MakeShape& maker,
    const std::exception_ptr& error
)
{
    if (error) {
        std::rethrow_exception(error);
    }
    maker.Check();
    throw StdFail_NotDone("BRep_API: command not done");
}

/** Whether OCCT built the dress-up with a face of zero width (ops#298): the face it consumes whole,
 * kept with area 0, or a sliver narrower than its tolerance. The exact construction builds the
 * dress-up at the limit instead; if it can't, the dress-up fails with a clear error.
 */
bool builtThinFace(BRepFilletAPI_LocalOperation& maker, const TopoShape& base)
{
    return !FilletFallback::thinFace(maker.Shape(), base.getShape()).IsNull();
}

[[noreturn]] void raiseThinFaceError(const char* what, const std::string& reason)
{
    FC_THROWM(
        Base::CADKernelError,
        what << " would leave a face of zero width (a face it consumes whole, or a sliver "
                "narrower than its tolerance), and its exact construction refused: "
             << reason
    );
}
}  // namespace

TopoShape& TopoShape::makeElementFillet(
    const TopoShape& shape,
    const std::vector<TopoShape>& edges,
    double radius1,
    double radius2,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::Fillet;
    }
    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }

    if (edges.empty()) {
        FC_THROWM(NullShapeException, "Null input shape");
    }
    for (auto& e : edges) {
        if (e.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        if (!shape.findShape(e.getShape())) {
            FC_THROWM(Base::CADKernelError, "edge does not belong to the shape");
        }
    }
    // The maker raises its input's tolerances in place: it runs on a copy (ops#345)
    std::vector<TopoShape> inputEdges = edges;
    const TopoShape input = FilletFallback::makerInput(shape, inputEdges);
    BRepFilletAPI_MakeFillet mkFillet(input.getShape());
    for (auto& e : inputEdges) {
        mkFillet.Add(radius1, radius2, TopoDS::Edge(e.getShape()));
    }
    std::exception_ptr occtError;
    FilletFallback::Request request;
    // Before the maker raises the copy's tolerances in place
    request.faceTolerances = FilletFallback::faceTolerances(input.getShape());
    const bool failed = buildDressUpFailed(mkFillet, occtError, request.contour);
    const bool thin = !failed && builtThinFace(mkFillet, input);
    if (failed || thin || builtInvalid(mkFillet)) {
        Part::SignalException sig;
        request.kind = FilletFallback::Kind::Fillet;
        request.size1 = radius1;
        request.size2 = radius2;
        std::string reason;
        if (FilletFallback::build(*this, input, inputEdges, request, op, &reason)) {
            return *this;
        }
        if (failed) {
            raiseDressUpError(mkFillet, occtError);
        }
        if (thin) {
            raiseThinFaceError("The fillet", reason);
        }
    }
    return makeElementShape(mkFillet, input, op);
}

TopoShape& TopoShape::makeElementChamfer(
    const TopoShape& shape,
    const std::vector<TopoShape>& edges,
    ChamferType chamferType,
    double radius1,
    double radius2,
    const char* op,
    Flip flipDirection
)
{
    if (!op) {
        op = Part::OpCodes::Chamfer;
    }
    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    if (edges.empty()) {
        FC_THROWM(NullShapeException, "Null input shape");
    }
    for (auto& e : edges) {
        if (e.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        if (!shape.findShape(e.getShape())) {
            FC_THROWM(Base::CADKernelError, "edge does not belong to the shape");
        }
    }
    // The maker raises its input's tolerances in place: it runs on a copy (ops#345)
    std::vector<TopoShape> inputEdges = edges;
    const TopoShape input = FilletFallback::makerInput(shape, inputEdges);
    BRepFilletAPI_MakeChamfer mkChamfer(input.getShape());
    for (auto& e : inputEdges) {
        const auto& edge = e.getShape();
        if (BRep_Tool::Degenerated(TopoDS::Edge(edge))) {
            FC_THROWM(Base::CADKernelError, "chamfer edge is degenerated");
        }
        // Add edge to fillet algorithm
        TopoDS_Shape face;
        if (flipDirection == Flip::flip) {
            const auto faces = input.findAncestorsShapes(edge, TopAbs_FACE);
            if (faces.empty()) {
                FC_THROWM(Base::CADKernelError, "chamfer edge has no adjacent face");
            }
            face = faces.back();
        }
        else {
            face = input.findAncestorShape(edge, TopAbs_FACE);
        }
        if (face.IsNull()) {
            FC_THROWM(Base::CADKernelError, "chamfer edge has no adjacent face");
        }
        switch (chamferType) {
            case ChamferType::equalDistance:  // Equal distance
                mkChamfer.Add(radius1, radius1, TopoDS::Edge(edge), TopoDS::Face(face));
                break;
            case ChamferType::twoDistances:  // Two distances
                mkChamfer.Add(radius1, radius2, TopoDS::Edge(edge), TopoDS::Face(face));
                break;
            case ChamferType::distanceAngle:  // Distance and angle
                mkChamfer
                    .AddDA(radius1, Base::toRadians(radius2), TopoDS::Edge(edge), TopoDS::Face(face));
                break;
        }
    }
    Part::SignalException sig;
    std::exception_ptr occtError;
    FilletFallback::Request request;
    // Before the maker raises the copy's tolerances in place
    request.faceTolerances = FilletFallback::faceTolerances(input.getShape());
    const bool failed = buildDressUpFailed(mkChamfer, occtError, request.contour);
    const bool thin = !failed && builtThinFace(mkChamfer, input);
    if (failed || thin || builtInvalid(mkChamfer)) {
        request.kind = FilletFallback::Kind::Chamfer;
        request.size1 = radius1;
        request.size2 = radius2;
        request.chamferType = chamferType;
        request.flipDirection = flipDirection;
        std::string reason;
        if (FilletFallback::build(*this, input, inputEdges, request, op, &reason)) {
            return *this;
        }
        if (failed) {
            raiseDressUpError(mkChamfer, occtError);
        }
        if (thin) {
            raiseThinFaceError("The chamfer", reason);
        }
    }
    return makeElementShape(mkChamfer, input, op);
}

TopoShape& TopoShape::makeElementDefeaturing(
    const TopoShape& shape,
    const std::vector<TopoShape>& faces,
    const char* op,
    ElementMapPolicy elementMapPolicy
)
{
    if (!op) {
        op = Part::OpCodes::Defeaturing;
    }
    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    if (faces.empty()) {
        FC_THROWM(NullShapeException, "Null input shape");
    }

    BRepAlgoAPI_Defeaturing mkDefeaturing;
    mkDefeaturing.SetRunParallel(true);
    mkDefeaturing.SetToFillHistory(true);
    mkDefeaturing.SetShape(shape.getShape());
    for (const auto& face : faces) {
        if (face.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        const auto& faceShape = face.getShape();
        if (faceShape.ShapeType() != TopAbs_FACE) {
            FC_THROWM(Base::CADKernelError, "defeaturing input shape is not a face");
        }
        if (!shape.findShape(faceShape)) {
            FC_THROWM(Base::CADKernelError, "defeaturing face does not belong to the shape");
        }
        mkDefeaturing.AddFaceToRemove(faceShape);
    }

#if OCC_VERSION_HEX >= 0x070600
    mkDefeaturing.Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
    mkDefeaturing.Build();
#endif
    if (!mkDefeaturing.IsDone()) {
        Standard_SStream ss;
        mkDefeaturing.DumpErrors(ss);
        throw Base::RuntimeError(ss.str().c_str());
    }
    if (mkDefeaturing.Shape().IsNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }

    return makeElementShape(mkDefeaturing, shape, op, elementMapPolicy);
}

TopoShape& TopoShape::makeElementGeneralFuse(
    const std::vector<TopoShape>& _shapes,
    std::vector<std::vector<TopoShape>>& modifies,
    double tol,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::GeneralFuse;
    }

    if (_shapes.empty()) {
        FC_THROWM(NullShapeException, "Null input shape");
    }

    std::vector<TopoShape> shapes(_shapes);

    BRepAlgoAPI_BuilderAlgo mkGFA;
    mkGFA.SetRunParallel(true);
    TopTools_ListOfShape GFAArguments;
    for (auto& shape : shapes) {
        if (shape.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }
        GFAArguments.Append(shape.getShape());
    }
    mkGFA.SetArguments(GFAArguments);
    if (tol > 0.0) {
        mkGFA.SetFuzzyValue(tol);
    }
    else if (tol < 0.0) {
        FCBRepAlgoAPIHelper::setAutoFuzzy(&mkGFA);
    }
    mkGFA.SetNonDestructive(Standard_True);
#if OCC_VERSION_HEX >= 0x070600
    mkGFA.Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
    mkGFA.Build();
#endif
    if (!mkGFA.IsDone()) {
        FC_THROWM(Base::CADKernelError, "GeneralFuse failed");
    }
    makeElementShape(mkGFA, shapes, op);
    modifies.resize(shapes.size());
    int index = 0;
    for (auto& shape : shapes) {
        auto& mod = modifies[index++];
        for (TopTools_ListIteratorOfListOfShape it(mkGFA.Modified(shape.getShape())); it.More();
             it.Next()) {
            TopoShape res(Tag);
            res.setHistoryAlgorithm(getHistoryAlgorithm());
            res.setShape(it.Value());
            mod.push_back(res);
        }
        mapSubElementsTo(mod);
    }
    return *this;
}

TopoShape& TopoShape::makeElementFuse(const std::vector<TopoShape>& shapes, const char* op, double tol)
{
    return makeElementBoolean(Part::OpCodes::Fuse, shapes, op, tol);
}

TopoShape& TopoShape::makeElementCut(const std::vector<TopoShape>& shapes, const char* op, double tol)
{
    return makeElementBoolean(Part::OpCodes::Cut, shapes, op, tol);
}

TopoShape& TopoShape::makeElementXor(
    const std::vector<TopoShape>& shapes,
    const char* op,
    double tol,
    ElementMapPolicy elementMapPolicy
)
{
    if (shapes.empty()) {
        FC_THROWM(NullShapeException, "Null shape");
    }

    if (Base::Sequencer().wasCanceled()) {
        FC_THROWM(Base::CADKernelError, "User aborted");
    }

    if (!op) {
        op = Part::OpCodes::Xor;
    }

    std::vector<TopoShape> expandedShapes;
    // Same compound expansion as Fuse
    for (auto it = shapes.begin(); it != shapes.end(); ++it) {
        auto& shape = *it;
        if (shape.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape for XOR operation");
        }
        if (shape.shapeType() == TopAbs_COMPOUND) {
            if (expandedShapes.empty()) {
                expandedShapes.insert(expandedShapes.end(), shapes.begin(), it);
            }
            expandCompound(shape, expandedShapes);
        }
        else if (!expandedShapes.empty()) {
            expandedShapes.push_back(shape);
        }
    }

    const auto& inputs = expandedShapes.empty() ? shapes : expandedShapes;
    // Note: The inputs.empty() check is now redundant because of the check at the top,
    // but it's harmless to leave it.
    if (inputs.empty()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    if (inputs.size() == 1) {
        *this = inputs[0];
        if (elementMapPolicy == ElementMapPolicy::Drop) {
            dropElementNaming();
        }
        if (shapes.size() == 1) {
            FC_WARN("Boolean operation with only one shape input");
        }
        return *this;
    }

    TopoShape result = inputs[0];
    for (size_t i = 1; i < inputs.size(); ++i) {
        // The final op is only applied on the very last iteration.
        const char* currentOp = (i == inputs.size() - 1) ? op : nullptr;

        // Step 1: Union(A, B) - intermediate result, no op code.
        TopoShape tempUnion(0, Hasher, getHistoryAlgorithm());
        tempUnion.makeElementBoolean(
            Part::OpCodes::Fuse,
            {result, inputs[i]},
            nullptr,
            tol,
            elementMapPolicy
        );

        // Step 2: Common(A, B) - intermediate result, no op code.
        TopoShape tempCommon(0, Hasher, getHistoryAlgorithm());
        tempCommon.makeElementBoolean(
            Part::OpCodes::Common,
            {result, inputs[i]},
            nullptr,
            tol,
            elementMapPolicy
        );

        // Step 3: Compute the final result for this iteration
        if (tempCommon.isNull() || tempCommon.getShape().IsNull()) {
            // No intersection, XOR is the same as Union.
            // We still call the boolean op to get the correct history.
            result.makeElementBoolean(
                Part::OpCodes::Fuse,
                {result, inputs[i]},
                currentOp,
                tol,
                elementMapPolicy
            );
        }
        else {
            // Final result is Cut(Union, Common).
            result.makeElementBoolean(
                Part::OpCodes::Cut,
                {tempUnion, tempCommon},
                currentOp,
                tol,
                elementMapPolicy
            );
        }
    }

    *this = result;
    if (elementMapPolicy == ElementMapPolicy::Drop) {
        dropElementNaming();
    }
    return *this;
}

TopoShape& TopoShape::makeElementShape(
    BRepBuilderAPI_MakeShape& mkShape,
    const TopoShape& source,
    const char* op,
    ElementMapPolicy elementMapPolicy
)
{
    std::vector<TopoShape> sources(1, source);
    return makeElementShape(mkShape, sources, op, elementMapPolicy);
}

TopoShape& TopoShape::makeElementShape(
    BRepBuilderAPI_MakeShape& mkShape,
    const std::vector<TopoShape>& shapes,
    const char* op,
    ElementMapPolicy elementMapPolicy
)
{
    TopoDS_Shape shape;
    // OCCT 7.3.x requires calling Solid() and not Shape() to function correctly
    if (typeid(mkShape) == typeid(BRepPrimAPI_MakeHalfSpace)) {
        shape = static_cast<BRepPrimAPI_MakeHalfSpace&>(mkShape).Solid();
    }
    else {
        shape = mkShape.Shape();
    }
    return makeShapeWithElementMap(shape, MapperMaker(mkShape), shapes, op, elementMapPolicy);
}

TopoShape& TopoShape::makeElementShape(
    BRepFeat_Form& mkShape,
    const std::vector<TopoShape>& sources,
    const TopoShape& upTo,
    const char* op
)
{
    const App::HistoryAlgorithm& historyAlgorithm = getHistoryAlgorithm();

    if (!op) {
        if (historyAlgorithm == App::HistoryAlgorithm::V1) {
            op = Part::OpCodes::Prism;
        }
        else if (historyAlgorithm == App::HistoryAlgorithm::V2) {
            op = Part::OpCodes::Extrude;
        }
    }

    MapperPrism mapper(mkShape, upTo, sources, historyAlgorithm);
    makeShapeWithElementMap(mkShape.Shape(), mapper, sources, op);
    return *this;
}


TopoShape& TopoShape::makeElementLoft(
    const std::vector<TopoShape>& shapes,
    IsSolid isSolid,
    IsRuled isRuled,
    IsClosed isClosed,
    Standard_Integer maxDegree,
    const char* op
)
{
    auto checkProfiles = [](const TopoShape& sh1, const TopoShape& sh2) {
        // The same TShape is used but the locations might be different
        // even if they result into the same transformation matrix.
        // Therefore compare the matrices.
        if (sh1.getShape().IsPartner(sh2.getShape())) {
            TopLoc_Location loc1 = sh1.getShape().Location();
            TopLoc_Location loc2 = sh2.getShape().Location();
            Base::Matrix4D mat1 = TopoShape::convert(loc1.Transformation());
            Base::Matrix4D mat2 = TopoShape::convert(loc2.Transformation());
            return (mat1 != mat2);
        }

        // For different shapes compare their bounding boxes
        try {
            Bnd_Box bounds1;
            Bnd_Box bounds2;
            BRepBndLib::Add(sh1.getShape(), bounds1);
            BRepBndLib::Add(sh2.getShape(), bounds2);

            // If bounding boxes are different the shapes must be different, too
            if (!bounds1.CornerMin().IsEqual(bounds2.CornerMin(), Precision::Confusion())) {
                return true;
            }
            if (!bounds1.CornerMax().IsEqual(bounds2.CornerMax(), Precision::Confusion())) {
                return true;
            }
        }
        catch (const Standard_Failure&) {
            return false;
        }

        Base::Vector3d center1;
        Base::Vector3d center2;
        if (!sh1.getCenterOfGravity(center1)) {
            return true;
        }
        if (!sh2.getCenterOfGravity(center2)) {
            return true;
        }

        return !center1.IsEqual(center2, Precision::Confusion());
    };

    if (!op) {
        op = Part::OpCodes::Loft;
    }

    // http://opencascade.blogspot.com/2010/01/surface-modeling-part5.html
    BRepOffsetAPI_ThruSections aGenerator(isSolid == IsSolid::solid, isRuled == IsRuled::ruled);
    aGenerator.SetMaxDegree(maxDegree);

    auto profiles = prepareProfiles(shapes);
    if (shapes.size() < 2) {
        FC_THROWM(Base::CADKernelError, "Need at least two vertices, edges or wires to create loft face");
    }

    int i = 0;
    for (auto& sh : profiles) {
        if (i > 0) {
            if (!checkProfiles(sh, profiles[i - 1])) {
                FC_THROWM(Base::CADKernelError, "Segments of a loft do not have sufficient separation");
            }
        }
        const auto& shape = sh.getShape();
        if (shape.ShapeType() == TopAbs_VERTEX) {
            aGenerator.AddVertex(TopoDS::Vertex(shape));
        }
        else {
            aGenerator.AddWire(TopoDS::Wire(shape));
        }
        i++;
    }
    // close loft by duplicating initial profile as last profile.  not perfect.
    if (isClosed == IsClosed::closed) {
        /* can only close loft in certain combinations of Vertex/Wire(Edge):
            - V1-W1-W2-W3-V2  ==> V1-W1-W2-W3-V2-V1  invalid closed
            - V1-W1-W2-W3     ==> V1-W1-W2-W3-V1     valid closed
            - W1-W2-W3-V1     ==> W1-W2-W3-V1-W1     invalid closed
            - W1-W2-W3        ==> W1-W2-W3-W1        valid closed*/
        if (profiles.back().getShape().ShapeType() == TopAbs_VERTEX) {
            Base::Console().message(
                "TopoShape::makeLoft: can't close Loft with Vertex as last "
                "profile. 'Closed' ignored.\n"
            );
        }
        else {
            // repeat Add logic above for first profile
            const TopoDS_Shape& firstProfile = profiles.front().getShape();
            if (firstProfile.ShapeType() == TopAbs_VERTEX) {
                aGenerator.AddVertex(TopoDS::Vertex(firstProfile));
            }
            else if (firstProfile.ShapeType() == TopAbs_EDGE) {
                aGenerator.AddWire(BRepBuilderAPI_MakeWire(TopoDS::Edge(firstProfile)).Wire());
            }
            else if (firstProfile.ShapeType() == TopAbs_WIRE) {
                aGenerator.AddWire(TopoDS::Wire(firstProfile));
            }
        }
    }

    Standard_Boolean anIsCheck = Standard_True;
    aGenerator.CheckCompatibility(anIsCheck);  // use BRepFill_CompatibleWires on profiles. force
                                               // #edges, orientation, "origin" to match.

#if OCC_VERSION_HEX >= 0x070600
    aGenerator.Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
    aGenerator.Build();
#endif
    return makeShapeWithElementMap(
        aGenerator.Shape(),
        MapperThruSections(aGenerator, profiles),
        shapes,
        op
    );
}

TopoShape& TopoShape::makeElementPrism(const TopoShape& base, const gp_Vec& vec, const char* op)
{
    if (!op) {
        op = Part::OpCodes::Extrude;
    }
    if (base.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    BRepPrimAPI_MakePrism mkPrism(base.getShape(), vec);
    return makeElementShape(mkPrism, base, op);
}

namespace
{
// How far prismUpToBySplit() extrudes the profile: past the whole of `upTo` from any point of it
double splitLength(const TopoDS_Shape& profile, const TopoDS_Shape& upTo)
{
    Bnd_Box box;
    BRepBndLib::Add(profile, box);
    BRepBndLib::Add(upTo, box);
    if (box.IsVoid() || box.IsOpen()) {
        return -1.0;
    }
    return std::sqrt(box.SquareExtent()) + 1.0;
}

// Whether BRepFeat_MakePrism extrudes `profile` along `direction` up to `upTo`: only when each
// face of it that the extrusion can meet lies on an elementary surface. Up to a face on a
// freeform surface (a loft's B-spline side, a surface of extrusion or revolution) it gave an
// empty compound, or a solid ten times too large, and said it was done (ops#353). For an up-to
// shape of several faces, faces whose bounding boxes miss the extrusion's both ways (an up-to
// shape's unrelated faces, e.g. a whole base's) don't count: BRepFeat keeps building what it
// built before. A single face always counts: BRepFeat chooses its own sense and gets the face
// without its limits, larger than the face (PR 324 round 1 verification).
bool brepFeatReaches(const TopoDS_Shape& profile, const TopoDS_Shape& upTo, const gp_Dir& direction)
{
    int faceCount = 0;
    for (TopExp_Explorer faces(upTo, TopAbs_FACE); faces.More() && faceCount < 2; faces.Next()) {
        ++faceCount;
    }
    const double length = faceCount > 1 ? splitLength(profile, upTo) : -1.0;
    Bnd_Box path;
    if (length > 0.0) {
        Bnd_Box start;
        BRepBndLib::Add(profile, start);
        path.Add(start);
        for (double sense : {1.0, -1.0}) {
            gp_Trsf shift;
            shift.SetTranslation(gp_Vec(direction) * (sense * length));
            path.Add(start.Transformed(shift));
        }
        path.Enlarge(Precision::Confusion());
    }
    for (TopExp_Explorer faces(upTo, TopAbs_FACE); faces.More(); faces.Next()) {
        if (!path.IsVoid()) {
            Bnd_Box box;
            BRepBndLib::Add(faces.Current(), box);
            if (!box.IsVoid() && path.IsOut(box)) {
                continue;
            }
        }
        switch (BRepAdaptor_Surface(TopoDS::Face(faces.Current()), Standard_False).GetType()) {
            case GeomAbs_Plane:
            case GeomAbs_Cylinder:
            case GeomAbs_Cone:
            case GeomAbs_Sphere:
            case GeomAbs_Torus:
                break;
            default:
                return false;
        }
    }
    return true;
}

// Whether `face` lies on a closed or periodic surface (a full revolution, a closed B-spline
// patch): without its limits, a prism up to it can stop at a part of the surface far from the
// face (ops#353 review M1)
bool onClosedSurface(const TopoShape& face)
{
    if (face.shapeType(true) != TopAbs_FACE) {
        return false;
    }
    const BRepAdaptor_Surface surface(TopoDS::Face(face.getShape()), Standard_False);
    return surface.IsUClosed() || surface.IsVClosed() || surface.IsUPeriodic()
        || surface.IsVPeriodic();
}

// How far `shape` reaches both ways along `direction` (its lowest and highest coordinates along
// it), or nothing for an infinite shape
std::optional<std::pair<double, double>> extentAlong(
    const TopoDS_Shape& shape,
    const gp_Dir& direction,
    bool tolerances
)
{
    gp_Trsf toFrame;
    toFrame.SetTransformation(gp_Ax3(gp::Origin(), direction));
    Bnd_Box box;
    BRepBndLib::AddOptimal(shape.Moved(TopLoc_Location(toFrame)), box, Standard_False, tolerances);
    if (box.IsVoid() || box.IsOpen()) {
        return std::nullopt;
    }
    double xMin, yMin, zMin, xMax, yMax, zMax;
    box.Get(xMin, yMin, zMin, xMax, yMax, zMax);
    return std::make_pair(zMin, zMax);
}

// Whether a prism of `profile` along `direction` up to the finite `upTo` reaches past both: its
// far end lies on `upTo`, so it can't. BRepFeat_MakePrism up to a shell that stops only part of
// the profile (UpToShape of a whole base with the profile overhanging it) extruded all of the
// profile far past the shell, and said it was done (ops#356). BRepFeat chooses its own sense, so
// past both backwards counts too (PR 326 review)
bool reachesPast(
    const TopoDS_Shape& prism,
    const TopoDS_Shape& profile,
    const TopoDS_Shape& upTo,
    const gp_Dir& direction
)
{
    const auto limit = extentAlong(upTo, direction, true);
    const auto start = extentAlong(profile, direction, true);
    const auto reach = extentAlong(prism, direction, false);
    if (!limit || !start || !reach) {
        return false;
    }
    return reach->second > std::max(limit->second, start->second) + Precision::Confusion()
        || reach->first < std::min(limit->first, start->first) - Precision::Confusion();
}

// Whether, somewhere on `piece` (a face of a solid, oriented as in it), the solid's outward normal
// points against `direction`, by more than a lean at modelling precision (below). Sampled: a grid
// over the piece's parameter range with a few points in each knot span of its surface each way
// (16 at least, 256 at most), those inside it; points just inside its edges, at fractions of the
// grid's step from each edge's curve on the surface, a few in each knot span of that curve (32 at
// least, more for an edge across many of the surface's spans, 1024 at most); and one point inside
// it. A fold narrower than a span's step away from the edges can be missed, and so can a band
// along a rim shorter than the gap between two of its edge's samples. Evenly spread, a band near
// a rim under 3 % of the range was (PR 324 round 2 verification); on the grid alone, a band along
// a rim narrower than half a step was (ops#357: a ball's band above its equator, under the plate
// it hangs from); with 32 samples per edge, a band along 2 % of its edge was (PR 331 round 1: a
// bump in the plate over the equator). Throws when no point inside the piece is found.
bool facesAgainst(const TopoDS_Face& piece, const gp_Dir& direction)
{
    const BRepAdaptor_Surface surface(piece);
    const gp_Vec along(direction);
    // A lean that moves the piece sideways by less than Precision::Confusion() over its extent
    // along the direction isn't a fold at modelling precision: a wall lofted from a circle to a
    // B-spline interpolation of it leans 1e-8 rad, and was refused (ops#357). A piece without
    // that extent (across the direction) keeps the strict bound. Measured at the first sample
    // that faces against the direction: most pieces have none
    std::optional<double> extent;
    auto against = [&](double u, double v) {
        gp_Pnt point;
        gp_Vec alongU;
        gp_Vec alongV;
        surface.D1(u, v, point, alongU, alongV);
        gp_Vec outward = alongU.Crossed(alongV);
        if (piece.Orientation() == TopAbs_REVERSED) {
            outward.Reverse();
        }
        const double size = outward.Magnitude();
        if (size <= gp::Resolution()) {
            return false;
        }
        const double cosine = -outward.Dot(along) / size;
        if (cosine <= 1e-9) {
            return false;
        }
        if (!extent) {
            const auto reach = extentAlong(piece, direction, false);
            extent = reach ? reach->second - reach->first : 0.0;
        }
        const double sine = std::sqrt(std::max(0.0, 1.0 - cosine * cosine));
        return *extent <= Precision::Confusion()
            || *extent * cosine > Precision::Confusion() * sine;
    };
    // One classifier for the piece, built at the first point to classify: built per point, a
    // piece facing against the direction mostly outside its trimming cost up to 65,536 of them on
    // a dense B-spline (ops#357). Near the boundary it classifies exactly
    std::unique_ptr<BRepTopAdaptor_FClass2d> classifier;
    auto inside = [&](double u, double v) {
        if (!classifier) {
            classifier = std::make_unique<BRepTopAdaptor_FClass2d>(piece, Precision::PConfusion());
        }
        return classifier->Perform(gp_Pnt2d(u, v)) == TopAbs_IN;
    };
    // The parameters to sample over the range of `bounds`, the bounds of knot spans (one span
    // for a curve or surface without knots): a few in each span, `least` at least and `most` at
    // most (evenly over the range when the spans are more than `most`)
    auto spread = [](const TColStd_Array1OfReal& bounds, int least, int most) {
        constexpr int perSpan = 4;
        int spans = bounds.Length() - 1;
        int each = std::max(perSpan, (least + spans - 1) / spans);
        double low = bounds.First();
        double high = bounds.Last();
        if (spans * each > most) {
            each = most / spans;
            if (each == 0) {
                spans = 1;
                each = most;
            }
        }
        std::vector<double> values;
        for (int s = 0; s < spans; ++s) {
            const double from = spans == 1 ? low : bounds(bounds.Lower() + s);
            const double to = spans == 1 ? high : bounds(bounds.Lower() + s + 1);
            for (int i = 0; i < each; ++i) {
                values.push_back(from + (i + 0.5) / each * (to - from));
            }
        }
        return values;
    };
    TColStd_Array1OfReal uBounds(1, surface.NbUIntervals(GeomAbs_CN) + 1);
    surface.UIntervals(uBounds, GeomAbs_CN);
    TColStd_Array1OfReal vBounds(1, surface.NbVIntervals(GeomAbs_CN) + 1);
    surface.VIntervals(vBounds, GeomAbs_CN);
    const std::vector<double> us = spread(uBounds, 16, 256);
    const std::vector<double> vs = spread(vBounds, 16, 256);
    // The normal first: classifying each point costs more
    for (double u : us) {
        for (double v : vs) {
            if (against(u, v) && inside(u, v)) {
                return true;
            }
        }
    }
    // Along the edges, on both sides of each (the classifier keeps the inside), across the edge's
    // curve measured in the grid's steps: a band along a rim lies between the rim and the grid's
    // first row there
    const double uStep = (uBounds.Last() - uBounds.First()) / static_cast<double>(us.size());
    const double vStep = (vBounds.Last() - vBounds.First()) / static_cast<double>(vs.size());
    // How many of the surface's knot spans one way lie across low..high
    auto spansAcross = [](const TColStd_Array1OfReal& bounds, double low, double high) {
        int spans = 1;
        for (int i = bounds.Lower() + 1; i < bounds.Upper(); ++i) {
            if (bounds(i) > low && bounds(i) < high) {
                ++spans;
            }
        }
        return spans;
    };
    for (TopExp_Explorer edges(piece, TopAbs_EDGE); edges.More(); edges.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(edges.Current());
        double first = 0.0;
        double last = 0.0;
        const Handle(Geom2d_Curve) curve = BRep_Tool::CurveOnSurface(edge, piece, first, last);
        if (BRep_Tool::Degenerated(edge) || curve.IsNull()) {
            continue;
        }
        // In each knot span of the edge's curve: an intersection's curve has its knots where it
        // bends, 62 to 72 of them where a bump in the plate meets the ball (PR 331 round 1). And
        // a few in each of the surface's spans that the curve's box lies across
        const Geom2dAdaptor_Curve adaptor(curve, first, last);
        TColStd_Array1OfReal tBounds(1, adaptor.NbIntervals(GeomAbs_CN) + 1);
        adaptor.Intervals(tBounds, GeomAbs_CN);
        int least = 32;
        Bnd_Box2d box;
        BndLib_Add2dCurve::Add(adaptor, 0.0, box);
        if (!box.IsVoid()) {
            double uLow = 0.0;
            double vLow = 0.0;
            double uHigh = 0.0;
            double vHigh = 0.0;
            box.Get(uLow, vLow, uHigh, vHigh);
            least = std::max(
                least,
                4 * (spansAcross(uBounds, uLow, uHigh) + spansAcross(vBounds, vLow, vHigh))
            );
        }
        for (double t : spread(tBounds, least, 1024)) {
            gp_Pnt2d at;
            gp_Vec2d tangent;
            curve->D1(t, at, tangent);
            gp_Vec2d across(-tangent.Y() / vStep, tangent.X() / uStep);
            const double size = across.Magnitude();
            if (size <= gp::Resolution()) {
                continue;
            }
            across /= size;
            for (double fraction : {1.0 / 8, 1.0 / 64, 1.0 / 512}) {
                for (double side : {1.0, -1.0}) {
                    const double u = at.X() + side * fraction * across.X() * uStep;
                    const double v = at.Y() + side * fraction * across.Y() * vStep;
                    if (against(u, v) && inside(u, v)) {
                        return true;
                    }
                }
            }
        }
    }
    gp_Pnt point;
    gp_Pnt2d uv;
    Handle(IntTools_Context) context = new IntTools_Context;
    if (BOPTools_AlgoTools3D::PointInFace(piece, point, uv, context) == 0) {
        return against(uv.X(), uv.Y());
    }
    for (double u : us) {
        for (double v : vs) {
            if (inside(u, v)) {
                return false;
            }
        }
    }
    throw Base::CADKernelError(QT_TRANSLATE_NOOP("Exception", "Could not extrude up to the face"));
}

// Whether BRepFeat_MakePrism's `prism` of `profile` along `direction` holds what lies behind the
// first contact: a face of one of its solids, other than one on the profile, whose outward normal
// points against the way the prism goes (facesAgainst()). Lines along it leave the prism and come
// back into it there. Up to a whole base of planes and a ball through the plate, BRepFeat filled
// the shadow of the ball's band above its equator, under the plate, and said it was done
// (ops#361); the split refuses the same geometry. BRepFeat chooses its own sense, so the way the
// prism goes is the way it reaches past the profile
bool fillsBehind(const TopoDS_Shape& prism, const TopoDS_Shape& profile, const gp_Dir& direction)
{
    const auto start = extentAlong(profile, direction, true);
    const auto reach = extentAlong(prism, direction, false);
    if (!start || !reach) {
        return false;
    }
    gp_Dir way(direction);
    if (reach->second <= start->second + Precision::Confusion()) {
        if (reach->first >= start->first - Precision::Confusion()) {
            return false;
        }
        way.Reverse();
    }
    // Whether a point inside `face` lies on the profile: the prism's start, which faces against
    // the way it goes
    auto onProfile = [&profile](const TopoDS_Face& face) {
        gp_Pnt point;
        gp_Pnt2d uv;
        Handle(IntTools_Context) context = new IntTools_Context;
        if (BOPTools_AlgoTools3D::PointInFace(face, point, uv, context) != 0) {
            return false;
        }
        BRepExtrema_DistShapeShape distance(BRepBuilderAPI_MakeVertex(point).Vertex(), profile);
        return distance.IsDone()
            && distance.Value() <= std::max(BRep_Tool::MaxTolerance(face, TopAbs_EDGE),
                                            Precision::Confusion());
    };
    for (TopExp_Explorer solids(prism, TopAbs_SOLID); solids.More(); solids.Next()) {
        for (TopExp_Explorer faces(solids.Current(), TopAbs_FACE); faces.More(); faces.Next()) {
            const TopoDS_Face& face = TopoDS::Face(faces.Current());
            try {
                if (facesAgainst(face, way) && !onProfile(face)) {
                    return true;
                }
            }
            catch (const Base::Exception&) {
                // No point inside the face to sample: nothing to say about it
            }
            catch (const Standard_Failure&) {
                // OCCT failed sampling the face or measuring its distance to the profile, so it
                // may be the face that fills behind. Can't tell: let the split decide, which
                // builds the first contact or refuses it, saying why (ops#450)
                return true;
            }
        }
    }
    return false;
}

// The prism of `profile` along `direction` up to `upTo` (a face or a shell), built without
// BRepFeat (ops#353), as a Revolution's sweep up to a face is (FeatureRevolved.cpp's
// sweepUpToFace(), ops#293): the profile extruded past `upTo`, split by it, and the pieces that
// start at the profile. Each point of the profile goes as far as the first crossing. Named into
// `named` from the extrusion, which is named from the profile, and from `upTo`. Throws when a
// piece that starts at the profile reaches the extrusion's far end (`upTo` doesn't stop all of
// the profile), or holds a piece of `upTo` inside it or one facing against the direction on its
// boundary (where the profile first meets `upTo` jumps within the profile).
TopoShape prismUpToBySplit(
    TopoShape named,
    const TopoShape& profile,
    const TopoShape& upTo,
    const gp_Dir& direction,
    const char* op
)
{
    auto fail = []() {
        return Base::CADKernelError(
            QT_TRANSLATE_NOOP("Exception", "Could not extrude up to the face")
        );
    };
    const TopoShape blank(named);
    const double length = splitLength(profile.getShape(), upTo.getShape());
    if (length <= 0.0) {
        throw fail();
    }
    BRepPrimAPI_MakePrism extrusion(profile.getShape(), gp_Vec(direction) * length);
    if (!extrusion.IsDone()) {
        throw fail();
    }
    TopoShape sweep(blank);
    sweep.makeElementShape(extrusion, profile, op);
    BRepAlgoAPI_Splitter splitter;
    TopTools_ListOfShape arguments;
    arguments.Append(sweep.getShape());
    TopTools_ListOfShape tools;
    tools.Append(upTo.getShape());
    splitter.SetArguments(arguments);
    splitter.SetTools(tools);
    splitter.SetNonDestructive(Standard_True);
    splitter.Build();
    if (!splitter.IsDone()) {
        throw fail();
    }
    // The pieces of the start and end caps
    auto piecesOf = [&splitter](const TopoDS_Shape& shape) {
        return UpToSplitMapper::piecesOf(splitter, shape);
    };
    const TopTools_IndexedMapOfShape start = piecesOf(extrusion.FirstShape());
    const TopTools_IndexedMapOfShape end = piecesOf(extrusion.LastShape());
    const TopTools_IndexedMapOfShape upToPieces = piecesOf(upTo.getShape());
    // The refusals are RuntimeErrors: they name what is wrong, and FeatureExtrude passes them on
    std::vector<TopoDS_Shape> kept;
    for (TopExp_Explorer solids(splitter.Shape(), TopAbs_SOLID); solids.More(); solids.Next()) {
        bool atStart = false;
        bool atEnd = false;
        bool inside = false;
        for (TopExp_Explorer faces(solids.Current(), TopAbs_FACE); faces.More(); faces.Next()) {
            atStart = atStart || start.Contains(faces.Current());
            atEnd = atEnd || end.Contains(faces.Current());
            inside = inside || faces.Current().Orientation() == TopAbs_INTERNAL
                || faces.Current().Orientation() == TopAbs_EXTERNAL;
        }
        if (atStart && atEnd) {
            throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                "Exception",
                "Could not extrude up to the face: part of the profile doesn't meet it"
            ));
        }
        // A piece of `upTo` that doesn't divide the extrusion, because an edge of it lies inside
        // (a free edge, a hole's), stays in the solid as an internal face: the profile beside
        // it goes on to whatever stops the solid further on, through its first contact (ops#353
        // review H1; the Revolution refuses the same, certifyFirstContact() check (i)). Points
        // on such an edge classify ON the solid, not IN, so the face is what is checked.
        if (atStart && inside) {
            throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                "Exception",
                "Could not extrude up to the face: the face's edge lies in the profile's way, so "
                "where the profile first meets the face jumps within the profile"
            ));
        }
        if (!atStart) {
            continue;
        }
        // A piece of `upTo` on the solid's boundary whose outward normal points against the
        // direction: lines along it leave the solid at the first contact and come back into it
        // there, through a closed obstacle's far side or an undercut, and the solid fills what
        // lies behind (PR 324 round 1 verification; the Revolution's certifyFirstContact()
        // checks (ii) and (iii)). With no such piece, a line enters the solid only through the
        // profile, so the solid is what first contact gives. A piece of the start cap is left
        // out: where the profile lies on a face of `upTo` (a sketch on the base, up to the base)
        // the splitter makes the two one face, whose outward normal is against the direction
        // (PR 324 round 2 verification)
        for (TopExp_Explorer faces(solids.Current(), TopAbs_FACE); faces.More(); faces.Next()) {
            if (upToPieces.Contains(faces.Current()) && !start.Contains(faces.Current())
                && facesAgainst(TopoDS::Face(faces.Current()), direction)) {
                throw Base::RuntimeError(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Could not extrude up to the face: the profile meets the face from behind, so "
                    "where the profile first meets the face jumps within the profile"
                ));
            }
        }
        kept.push_back(solids.Current());
    }
    if (kept.empty()) {
        throw fail();
    }
    const TopoDS_Shape result = UpToSplitMapper::keptShape(kept);
    auto firstShape = [&extrusion](const TopoDS_Shape& element) {
        return extrusion.FirstShape(element);
    };
    // Each far cap is the projection of its profile face, as BRepFeat names the top (ops#360)
    const UpToSplitMapper
        mapper(splitter, extrusion, firstShape, profile.getShape(), result, upTo.getShape(), direction);
    named.makeShapeWithElementMap(result, mapper, {sweep, upTo}, op);
    return named;
}
}  // namespace

TopoShape& TopoShape::makeElementPrismUntil(
    const TopoShape& baseShape,
    const TopoShape& profileShape,
    const TopoShape& supportShape,
    const TopoShape& upToShape,
    const gp_Dir& direction,
    PrismMode Mode,
    Standard_Boolean checkLimits,
    const char* op
)
{
    const App::HistoryAlgorithm& historyAlgorithm = getHistoryAlgorithm();

    // BRepFeat raises in place the tolerances of what the prism meets: the up-to face's edges and
    // vertices, and the base's, often the base feature's stored shape (1e-7 -> 5e-6 with the
    // profile's top 1e-6 under the face's edge). It runs on copies of its inputs (ops#347)
    const std::vector<TopoShape> inputs =
        FilletFallback::makerInputs({baseShape, profileShape, supportShape, upToShape});
    const TopoShape& _base = inputs[0];
    const TopoShape& profile = inputs[1];
    const TopoShape& supportFace = inputs[2];
    const TopoShape& __uptoface = inputs[3];

    if (!op) {
        if (historyAlgorithm == App::HistoryAlgorithm::V1) {
            op = Part::OpCodes::Prism;
        }
        else if (historyAlgorithm == App::HistoryAlgorithm::V2) {
            op = Part::OpCodes::Extrude;
        }
    }

    BRepFeat_MakePrism PrismMaker;

    // don't remove limits of concave face. The default centre of a long curved B-spline profile is
    // millimetres off, enough to take the wrong side of a curved face (ops#428)
    if (checkLimits && __uptoface.shapeType(true) == TopAbs_FACE) {
        gp_Pnt pCog;
        MassProperties::centreOfMass(profile.getShape(), pCog);
        checkLimits = !Part::Tools::isConcave(TopoDS::Face(__uptoface.getShape()), pCog, direction);
    }

    TopoShape _uptoface(__uptoface);
    if (checkLimits && _uptoface.shapeType(true) == TopAbs_FACE
        && !BRep_Tool::NaturalRestriction(TopoDS::Face(_uptoface.getShape()))) {
        // When using the face with BRepFeat_MakePrism::Perform(const TopoDS_Shape& Until)
        // then the algorithm expects that the 'NaturalRestriction' flag is set in order
        // to work as expected.
        BRep_Builder builder;
        _uptoface = _uptoface.makeElementCopy();
        builder.NaturalRestriction(TopoDS::Face(_uptoface.getShape()), Standard_True);
    }

    TopoShape uptoface(_uptoface);
    TopoShape base(_base);

    if (base.isNull()) {
        Mode = PrismMode::None;
        base = profile;
    }

    // Check whether the face has limits or not. Unlimited faces have no wire
    // Note: Datum planes are always unlimited
    if (checkLimits && uptoface.shapeType(true) == TopAbs_FACE && uptoface.hasSubShape(TopAbs_WIRE)) {
        TopoDS_Face face = TopoDS::Face(uptoface.getShape());
        bool remove_limits = false;
        // Remove the limits of the upToFace so that the extrusion works even if profile is larger
        // than the upToFace
        for (auto& sketchface : profile.getSubTopoShapes(TopAbs_FACE)) {
            // Get outermost wire of sketch face
            TopoShape outerWire = sketchface.splitWires();
            BRepProj_Projection proj(TopoDS::Wire(outerWire.getShape()), face, direction);
            if (!proj.More() || !proj.Current().Closed()) {
                remove_limits = true;
                break;
            }
        }

        // It must also be checked that all projected inner wires of the upToFace
        // lie outside the sketch shape. If this is not the case then the sketch
        // shape is not completely covered by the upToFace. See #0003141
        if (!remove_limits) {
            std::vector<TopoShape> wires;
            uptoface.splitWires(&wires);
            for (auto& w : wires) {
                BRepProj_Projection proj(TopoDS::Wire(w.getShape()), profile.getShape(), -direction);
                if (proj.More()) {
                    remove_limits = true;
                    break;
                }
            }
        }

        if (remove_limits) {
            // Note: Using an unlimited face every time gives unnecessary failures for concave
            // faces
            TopLoc_Location loc = face.Location();
            BRepAdaptor_Surface adapt(face, Standard_False);
            // use the placement of the adapter, not of the upToFace
            loc = TopLoc_Location(adapt.Trsf());
            BRepBuilderAPI_MakeFace mkFace(adapt.Surface().Surface(), Precision::Confusion());
            if (mkFace.IsDone()) {
                uptoface.setShape(located(mkFace.Shape(), loc), false);
            }
        }
    }

    TopoShape uptofaceCopy = uptoface;
    bool checkBase = false;
    auto retry = [&]() {
        if (!uptoface.isSame(_uptoface)) {
            // retry using the original up to face in case unnecessary failure
            // due to removing the limits
            uptoface = _uptoface;
            return true;
        }
        if ((!_base.isNull() && base.isSame(_base)) || (_base.isNull() && base.isSame(profile))) {
            // It is unclear under exactly what condition extrude up to face
            // can fail. Either the support face or the up to face must be part
            // of the base, or maybe some thing else.
            //
            // To deal with it, we retry again by disregard the supplied base,
            // and use up to face to extrude our own base. Later on, use the
            // supplied base (i.e. _base) to calculate the final shape if the
            // mode is FuseWithBase or CutWithBase.
            checkBase = true;
            uptoface = uptofaceCopy;
            base.makeElementPrism(_uptoface, direction);
            return true;
        }
        return false;
    };

    std::vector<TopoShape> srcShapes;
    TopoShape result;
    // Up to a freeform face, by a split instead of BRepFeat (ops#353): up to the face as it is,
    // then up to the face without its limits, when they were removed and it is still finite
    auto prismBySplit = [&]() -> TopoShape {
        const TopoShape named(Tag, Hasher, historyAlgorithm);
        // OCCT's own failures as the Revolution's sweep up to a face takes them: a failed try
        auto split = [&](const TopoShape& upTo) {
            try {
                return prismUpToBySplit(named, profile, upTo, direction, op);
            }
            catch (const Standard_Failure&) {
                throw Base::CADKernelError(
                    QT_TRANSLATE_NOOP("Exception", "Could not extrude up to the face")
                );
            }
        };
        try {
            return split(_uptoface);
        }
        catch (const Base::Exception&) {
            // Not without the limits of a closed or periodic surface, which can stop the profile
            // at a part of it far from the face: the first try's error stands (ops#353 review M1)
            Bnd_Box box;
            BRepBndLib::Add(uptofaceCopy.getShape(), box);
            if (uptofaceCopy.isSame(_uptoface) || box.IsVoid() || box.IsOpen()
                || onClosedSurface(_uptoface)) {
                throw;
            }
            // When the face without its limits fails too, the face as it is says why
            const std::exception_ptr first = std::current_exception();
            try {
                return split(uptofaceCopy);
            }
            catch (const Base::Exception&) {
                std::rethrow_exception(first);
            }
        }
    };
    const bool bySplit = !brepFeatReaches(profile.getShape(), _uptoface.getShape(), direction);
    if (bySplit) {
        result = prismBySplit();
    }
    while (!bySplit) {
        try {
            result = base;

            // We do not rely on BRepFeat_MakePrism to perform fuse or cut for
            // us because of its poor support of shape history.
            auto mode = PrismMode::None;

            for (auto& face : profile.getSubTopoShapes(
                     profile.hasSubShape(TopAbs_FACE) ? TopAbs_FACE : TopAbs_WIRE
                 )) {
                srcShapes.clear();
                if (!profile.isNull()
                    && (!result.findShape(profile.getShape())
                        || historyAlgorithm == App::HistoryAlgorithm::V2)) {
                    srcShapes.push_back(profile);
                }
                if (!supportFace.isNull() && !result.findShape(supportFace.getShape())) {
                    srcShapes.push_back(supportFace);
                }

                // DO NOT include uptoface for element mapping. Because OCCT
                // BRepFeat_MakePrism will report all top extruded face being
                // modified by the uptoface. If there are more than one face in
                // the profile, this will cause unnecessary duplicated element
                // mapped name. And will also disrupte element history tracing
                // back to the profile sketch.
                //
                // if (!uptoface.isNull() && !this->findShape(uptoface.getShape()))
                //     srcShapes.push_back(uptoface);

                // the MapperPrism used in coordination with the V2 topological naming algorithm
                // does not want `result` as an input, so omit it.
                if (historyAlgorithm == App::HistoryAlgorithm::V1) {
                    srcShapes.push_back(result);
                }

                if (result.isInfinite()) {
                    result = face;
                }

                PrismMaker.Init(
                    result.getShape(),
                    face.getShape(),
                    TopoDS::Face(supportFace.getShape()),
                    direction,
                    mode,
                    Standard_False
                );
                mode = PrismMode::FuseWithBase;

                PrismMaker.Perform(uptoface.getShape());

                // A face's prism with no solid is a failure too: BRepFeat gave an empty
                // compound, done, up to faces it doesn't reach (ops#353)
                const TopAbs_ShapeEnum made = face.shapeType() == TopAbs_FACE ? TopAbs_SOLID
                                                                              : TopAbs_FACE;
                if (!PrismMaker.IsDone() || PrismMaker.Shape().IsNull()
                    || !TopExp_Explorer(PrismMaker.Shape(), made).More()) {
                    FC_THROWM(Base::CADKernelError, "BRepFeat_MakePrism: extrusion failed");
                }

                if (historyAlgorithm == App::HistoryAlgorithm::V2) {
                    result.Tag = Tag;
                }

                result.makeElementShape(PrismMaker, srcShapes, uptoface, op);
            }
            break;
        }
        catch (Base::Exception&) {
            if (!retry()) {
                throw;
            }
        }
        catch (Standard_Failure&) {
            if (!retry()) {
                throw;
            }
        }
    }
    // As the split refuses it (ops#356). `result` is the profile's prisms alone here: the first
    // face's prism is made with mode None
    if (!bySplit
        && reachesPast(result.getShape(), profile.getShape(), uptoface.getShape(), direction)) {
        throw Base::RuntimeError(QT_TRANSLATE_NOOP(
            "Exception",
            "Could not extrude up to the face: part of the profile doesn't meet it"
        ));
    }
    // By the split, which builds the first contact or refuses it, saying why (ops#361)
    if (!bySplit && fillsBehind(result.getShape(), profile.getShape(), direction)) {
        result = prismBySplit();
    }

    if (!_base.isNull() && Mode != PrismMode::None) {
        if (Mode == PrismMode::FuseWithBase) {
            result.makeElementFuse({_base, result});
        }
        else {
            result.makeElementCut({_base, result});
        }
    }

    *this = result;
    return *this;
}

TopoShape& TopoShape::makeElementRevolve(
    const TopoShape& _base,
    const gp_Ax1& axis,
    double d,
    const char* face_maker,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::Revolve;
    }

    TopoShape base(_base);
    if (base.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    if (face_maker && !base.hasSubShape(TopAbs_FACE)) {
        if (!base.hasSubShape(TopAbs_WIRE)) {
            base = base.makeElementWires();
        }
        base = base.makeElementFace(nullptr, face_maker, nullptr);
    }
    BRepPrimAPI_MakeRevol mkRevol(base.getShape(), axis, d);
    return makeElementShape(mkRevol, base, op);
}

TopoShape& TopoShape::makeElementRevolution(
    const TopoShape& _base,
    const TopoShape& profile,
    const gp_Ax1& axis,
    const TopoShape& supportface,
    const TopoDS_Face& uptoface,
    const char* face_maker,
    RevolMode Mode,
    Standard_Boolean Modify,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::Revolve;
    }
    if (Mode == RevolMode::None) {
        Modify = Standard_False;
    }
    TopoShape base(_base);
    if (base.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    if (face_maker && !base.hasSubShape(TopAbs_FACE)) {
        if (!base.hasSubShape(TopAbs_WIRE)) {
            base = base.makeElementWires();
        }
        base = base.makeElementFace(nullptr, face_maker, nullptr);
    }

    const TopoDS_Face& support = TopoDS::Face(supportface.getShape());
    auto mode = Mode;
    BRepFeat_MakeRevol mkRevol;
    if (getHistoryAlgorithm() == App::HistoryAlgorithm::V1) {
        for (TopExp_Explorer xp(profile.getShape(), TopAbs_FACE); xp.More(); xp.Next()) {
            mkRevol.Init(
                base.getShape(),
                xp.Current(),
                support,
                axis,
                static_cast<int>(mode),
                Modify
            );
            mkRevol.Perform(uptoface);
            if (!mkRevol.IsDone()) {
                throw Base::RuntimeError("Revolution: Up to face: Could not revolve the sketch!");
            }
            base = mkRevol.Shape();
            if (Mode == RevolMode::None) {
                mode = RevolMode::FuseWithBase;
            }
        }
        return makeElementShape(mkRevol, base, op);
    }

    // V2 names the result as makeElementPrismUntil() names a Pad's up to a face (ops#240): the
    // profile and the support face are the sources, so each revolved face is named from the profile
    // edge that sweeps it. Not the up-to face, whose history BRepFeat reports for every end face,
    // nor the base or the running result: the base's faces get their names back in the boolean that
    // follows, where the base is a source.
    const TopoShape upTo(uptoface);
    TopoDS_Shape result = base.getShape();
    bool revolved = false;
    for (const auto& face : profile.getSubTopoShapes(TopAbs_FACE)) {
        std::vector<TopoShape> sources {profile};
        if (!supportface.isNull() && !TopoShape(result).findShape(supportface.getShape())) {
            sources.push_back(supportface);
        }
        mkRevol.Init(result, face.getShape(), support, axis, static_cast<int>(mode), Modify);
        mkRevol.Perform(uptoface);
        if (!mkRevol.IsDone()) {
            throw Base::RuntimeError("Revolution: Up to face: Could not revolve the sketch!");
        }
        result = mkRevol.Shape();
        makeElementShape(mkRevol, sources, upTo, op);
        revolved = true;
        if (Mode == RevolMode::None) {
            mode = RevolMode::FuseWithBase;
        }
    }
    if (!revolved) {
        throw Base::RuntimeError("Revolution: Up to face: Could not revolve the sketch!");
    }
    return *this;
}

TopoShape& TopoShape::makeElementDraft(
    const TopoShape& shape,
    const std::vector<TopoShape>& _faces,
    const gp_Dir& pullDirection,
    double angle,
    const gp_Pln& neutralPlane,
    bool retry,
    const char* op
)
{
    if (!op) {
        op = Part::OpCodes::Draft;
    }

    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }

    std::vector<TopoShape> faces(_faces);
    bool done = true;
    BRepOffsetAPI_DraftAngle mkDraft;
    do {
        if (faces.empty()) {
            FC_THROWM(Base::CADKernelError, "no faces can be used");
        }

        mkDraft.Init(shape.getShape());
        done = true;
        for (auto it = faces.begin(); it != faces.end(); ++it) {
            // TODO: What is the flag for?
            mkDraft.Add(TopoDS::Face(it->getShape()), pullDirection, angle, neutralPlane);
            if (!mkDraft.AddDone()) {
                // Note: the function ProblematicShape returns the face on which the error occurred
                // Note: mkDraft.Remove() stumbles on a bug in Draft_Modification::Remove() and is
                //       therefore unusable. See
                //       http://forum.freecad.org/viewtopic.php?f=10&t=3209&start=10#p25341 The
                //       only solution is to discard mkDraft and start over without the current face
                // mkDraft.Remove(face);
                FC_ERR("Failed to add some face for drafting, skip");
                done = false;
                faces.erase(it);
                break;
            }
        }
    } while (retry && !done);

#if OCC_VERSION_HEX >= 0x070600
    mkDraft.Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
    mkDraft.Build();
#endif
    return makeElementShape(mkDraft, shape, op);
}

TopoShape& TopoShape::makeElementFace(
    const TopoShape& shape,
    const char* op,
    const char* maker,
    const gp_Pln* plane,
    ElementMapPolicy elementMapPolicy
)
{
    std::vector<TopoShape> shapes;
    if (shape.isNull()) {
        FC_THROWM(NullShapeException, "Null shape");
    }
    if (shape.getShape().ShapeType() == TopAbs_COMPOUND) {
        shapes = shape.getSubTopoShapes();
    }
    else {
        shapes.push_back(shape);
    }
    return makeElementFace(shapes, op, maker, plane, elementMapPolicy);
}

TopoShape& TopoShape::makeElementFace(
    const std::vector<TopoShape>& shapes,
    const char* op,
    const char* maker,
    const gp_Pln* plane,
    ElementMapPolicy elementMapPolicy
)
{
    const App::HistoryAlgorithm& historyAlgorithm = getHistoryAlgorithm();

    if (!maker || !maker[0]) {
        maker = "Part::FaceMakerBullseye";
    }
    std::unique_ptr<FaceMaker> mkFace = FaceMaker::ConstructFromType(maker);
    mkFace->MyHasher = Hasher;
    mkFace->MyOp = op;
    mkFace->MyElementMapPolicy = elementMapPolicy;
    mkFace->setHistoryAlgorithm(historyAlgorithm);
    if (plane) {
        mkFace->setPlane(*plane);
    }

    if (historyAlgorithm == App::HistoryAlgorithm::V2) {
        mkFace->MyTag = Tag;
    }

    for (auto& shape : shapes) {
        if (shape.getShape().ShapeType() == TopAbs_COMPOUND) {
            mkFace->useTopoCompound(shape);
        }
        else {
            mkFace->addTopoShape(shape);
        }
    }
#if OCC_VERSION_HEX >= 0x070600
    mkFace->Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
    mkFace->Build();
#endif

    const auto& ret = mkFace->getTopoShape();
    setShape(ret._Shape);
    if (elementMapPolicy == ElementMapPolicy::Drop) {
        dropElementNaming();
    }
    else {
        Hasher = ret.Hasher;
        resetElementMap(ret.elementMap());
    }
    if (!isValid()) {
        ShapeFix_ShapeTolerance aSFT;
        aSFT.LimitTolerance(getShape(), Precision::Confusion(), Precision::Confusion(), TopAbs_SHAPE);

        // In some cases, the OCC reports the returned shape having invalid
        // tolerance. Not sure about the real cause.
        //
        // Update: one of the cause is related to OCC bug in
        // BRepBuilder_FindPlane, A possible call sequence is,
        //
        //      makeElementOffset2D() -> TopoShape::findPlane() -> BRepLib_FindSurface
        //
        // See code comments in findPlane() for the description of the bug and
        // work around.

        ShapeFix_Shape fixer(getShape());
        fixer.Perform();
        setShape(fixer.Shape(), false);

        if (!isValid()) {
            FC_WARN("makeElementFace: resulting face is invalid");
        }
    }
    return *this;
}

class MyRefineMaker: public BRepBuilderAPI_RefineModel
{
public:
    explicit MyRefineMaker(const TopoDS_Shape& s)
        : BRepBuilderAPI_RefineModel(s)
    {}

    void populate(ShapeMapper& mapper)
    {
        for (TopTools_DataMapIteratorOfDataMapOfShapeListOfShape it(this->myModified); it.More();
             it.Next()) {
            if (it.Key().IsNull()) {
                continue;
            }
            mapper.populate(MappingStatus::Modified, it.Key(), it.Value());
        }
    }
};

TopoShape& TopoShape::makeElementRefine(const TopoShape& shape, const char* op, RefineFail no_fail)
{
    if (shape.isNull()) {
        if (no_fail == RefineFail::throwException) {
            FC_THROWM(NullShapeException, "Null shape");
        }
        _Shape.Nullify();
        return *this;
    }
    if (!op) {
        op = Part::OpCodes::Refine;
    }
    bool closed = shape.isClosed();
    try {
        // Refine runs on a topology-only copy, with the shape's element map and Tag (ops#354).
        // Merging faces of a B-spline surface, ShapeFix_Face adds a curve on surface to their
        // boundary edges for the merged face's surface, a new copy at every run (ops#316), and
        // keeps it when the merge is then dropped. The input shares its TShapes with the shapes it
        // was made from (a cut's untouched edges are its base's), which kept one more curve per
        // edge at every recompute. The copy's sub-shapes come in the same order, so the result
        // is named as from the shape.
        TopoShape input(shape);
        input.setShape(BRepBuilderAPI_Copy(shape.getShape(), false).Shape(), false);
        MyRefineMaker mkRefine(input.getShape());
        GenericShapeMapper mapper;
        mkRefine.populate(mapper);
        mapper.init(input, mkRefine.Shape());
        makeShapeWithElementMap(mkRefine.Shape(), mapper, {input}, op);
        // For some reason, refine operation may reverse the solid
        fixSolidOrientation();
        if (isClosed() == closed) {
            return *this;
        }
    }
    catch (Standard_Failure&) {
        if (no_fail == RefineFail::throwException) {
            throw;
        }
    }
    *this = shape;
    return *this;
}

std::vector<Data::IndexedName> TopoShape::getHigherElements(const char* element, bool silent) const
{
    TopoShape shape = getSubTopoShape(element, silent);
    if (shape.isNull()) {
        return {};
    }

    std::vector<Data::IndexedName> res;

    for (int type = shape.shapeType() - 1; type >= 0; type--) {
        const char* shapetype = shapeName((TopAbs_ShapeEnum)type).c_str();
        for (int idx : findAncestors(shape.getShape(), (TopAbs_ShapeEnum)type)) {
            res.emplace_back(shapetype, idx);
        }
    }
    return res;
}

namespace
{
// Whether an element of a B-spline face (a vertex or an edge) lies on an input element: a vertex
// by distance, an edge by its vertices and its middle point. Degenerated edges lie on nothing.
bool bsplineFaceElementLiesOn(const TopoDS_Shape& element, const TopoDS_Shape& on)
{
    double tolerance = Precision::Confusion();
    if (on.ShapeType() == TopAbs_EDGE) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Edge(on)));
    }
    else if (on.ShapeType() == TopAbs_VERTEX) {
        tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Vertex(on)));
    }
    auto isOn = [&](const TopoDS_Shape& shape) {
        BRepExtrema_DistShapeShape distance(shape, on);
        return distance.IsDone() && distance.Value() <= tolerance;
    };
    if (element.ShapeType() == TopAbs_VERTEX) {
        return isOn(element);
    }
    if (element.ShapeType() != TopAbs_EDGE || BRep_Tool::Degenerated(TopoDS::Edge(element))) {
        return false;
    }
    for (TopExp_Explorer xp(element, TopAbs_VERTEX); xp.More(); xp.Next()) {
        if (!isOn(xp.Current())) {
            return false;
        }
    }
    BRepAdaptor_Curve curve(TopoDS::Edge(element));
    gp_Pnt middle = curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2);
    return isOn(BRepBuilderAPI_MakeVertex(middle).Vertex());
}
}  // namespace

TopoShape& TopoShape::makeElementBSplineFace(
    const TopoShape& shape,
    FillingStyle style,
    bool keepBezier,
    const char* op
)
{
    std::vector<TopoShape> input(1, shape);
    return makeElementBSplineFace(input, style, keepBezier, op);
}

TopoShape& TopoShape::makeElementBSplineFace(
    const std::vector<TopoShape>& input,
    FillingStyle style,
    bool keepBezier,
    const char* op
)
{
    std::vector<TopoShape> edges;
    for (auto& s : input) {
        auto e = s.getSubTopoShapes(TopAbs_EDGE);
        edges.insert(edges.end(), e.begin(), e.end());
    }

    if (edges.size() == 1 && edges[0].isClosed()) {
        auto edge = edges[0].getSubShape(TopAbs_EDGE, 1);
        auto e = TopoDS::Edge(edge);
        auto v = TopExp::FirstVertex(e);
        Standard_Real first, last;
        Handle(Geom_Curve) curve = BRep_Tool::Curve(e, first, last);

        BRepBuilderAPI_MakeEdge mk1, mk2, mk3, mk4;
        Handle(Geom_BSplineCurve) bspline = Handle(Geom_BSplineCurve)::DownCast(curve);
        if (bspline.IsNull()) {
            ShapeConstruct_Curve scc;
            bspline = scc.ConvertToBSpline(curve, first, last, Precision::Confusion());
            if (bspline.IsNull()) {
                FC_THROWM(Base::CADKernelError, "Failed to convert edge to bspline");
            }
            first = bspline->FirstParameter();
            last = bspline->LastParameter();
        }
        auto step = (last - first) * 0.25;
        auto m1 = first + step;
        auto m2 = m1 + step;
        auto m3 = m2 + step;
        auto c1 = GeomConvert::SplitBSplineCurve(bspline, first, m1, Precision::Confusion());
        auto c2 = GeomConvert::SplitBSplineCurve(bspline, m1, m2, Precision::Confusion());
        auto c3 = GeomConvert::SplitBSplineCurve(bspline, m2, m3, Precision::Confusion());
        auto c4 = GeomConvert::SplitBSplineCurve(bspline, m3, last, Precision::Confusion());
        mk1.Init(c1);
        mk2.Init(c2);
        mk3.Init(c3);
        mk4.Init(c4);

        if (!mk1.IsDone() || !mk2.IsDone() || !mk3.IsDone() || !mk4.IsDone()) {
            FC_THROWM(Base::CADKernelError, "Failed to split edge");
        }

        auto e1 = mk1.Edge();
        auto e2 = mk2.Edge();
        auto e3 = mk3.Edge();
        auto e4 = mk4.Edge();

        ShapeMapper mapper;
        mapper.populate(MappingStatus::Modified, e, std::vector<Part::TopoShape> {e1, e2, e3, e4});
        mapper.populate(
            MappingStatus::Generated,
            v,
            std::vector<Part::TopoShape> {TopExp::FirstVertex(e1)}
        );
        mapper.populate(
            MappingStatus::Generated,
            v,
            std::vector<Part::TopoShape> {TopExp::LastVertex(e4)}
        );

        BRep_Builder builder;
        TopoDS_Compound comp;
        builder.MakeCompound(comp);
        builder.Add(comp, e1);
        builder.Add(comp, e2);
        builder.Add(comp, e3);
        builder.Add(comp, e4);

        TopoShape s {getHistoryAlgorithm()};
        s.makeShapeWithElementMap(comp, mapper, edges, Part::OpCodes::Split);
        return makeElementBSplineFace(s, style, keepBezier, op);
    }

    if (edges.size() < 2 || edges.size() > 4) {
        FC_THROWM(Base::CADKernelError, "Require minimum two, maximum four edges");
    }

    GeomFill_FillingStyle fstyle;
    switch (style) {
        case coons:
            fstyle = GeomFill_CoonsStyle;
            break;
        case curved:
            fstyle = GeomFill_CurvedStyle;
            break;
        default:
            fstyle = GeomFill_StretchStyle;
    }

    Handle(Geom_Surface) aSurface;

    Standard_Real u1, u2;
    if (keepBezier) {
        std::vector<Handle(Geom_BezierCurve)> curves;
        curves.reserve(4);
        for (const auto& e : edges) {
            const TopoDS_Edge& edge = TopoDS::Edge(e.getShape());
            TopLoc_Location heloc;  // this will be output
            Handle(Geom_Curve) c_geom = BRep_Tool::Curve(edge, heloc, u1, u2);
            Handle(Geom_BezierCurve) curve = Handle(Geom_BezierCurve)::DownCast(c_geom);
            if (!curve) {
                break;
            }
            curve->Transform(heloc.Transformation());  // apply original transformation to control points
            curves.push_back(curve);
        }
        if (curves.size() == edges.size()) {
            GeomFill_BezierCurves aSurfBuilder;  // Create Surface Builder

            if (edges.size() == 2) {
                aSurfBuilder.Init(curves[0], curves[1], fstyle);
            }
            else if (edges.size() == 3) {
                aSurfBuilder.Init(curves[0], curves[1], curves[2], fstyle);
            }
            else if (edges.size() == 4) {
                aSurfBuilder.Init(curves[0], curves[1], curves[2], curves[3], fstyle);
            }
            aSurface = aSurfBuilder.Surface();
        }
    }

    if (aSurface.IsNull()) {
        std::vector<Handle(Geom_BSplineCurve)> curves;
        curves.reserve(4);
        for (const auto& e : edges) {
            const TopoDS_Edge& edge = TopoDS::Edge(e.getShape());
            TopLoc_Location heloc;  // this will be output
            Handle(Geom_Curve)
                c_geom = BRep_Tool::Curve(edge, heloc, u1, u2);  // The geometric curve
            Handle(Geom_BSplineCurve)
                bspline = Handle(Geom_BSplineCurve)::DownCast(c_geom);  // Try to get BSpline curve
            if (!bspline.IsNull()) {
                gp_Trsf transf = heloc.Transformation();
                bspline->Transform(transf);  // apply original transformation to control points
                // Store Underlying Geometry
                curves.push_back(bspline);
            }
            else {
                // try to convert it into a B-spline
                BRepBuilderAPI_NurbsConvert mkNurbs(edge);
                TopoDS_Edge nurbs = TopoDS::Edge(mkNurbs.Shape());
                // avoid copying
                TopLoc_Location heloc2;  // this will be output
                Handle(Geom_Curve) c_geom2 = BRep_Tool::Curve(nurbs, heloc2, u1, u2);  // The
                                                                                       // geometric
                                                                                       // curve
                Handle(Geom_BSplineCurve) bspline2 = Handle(Geom_BSplineCurve)::DownCast(
                    c_geom2
                );  // Try to get BSpline curve

                if (!bspline2.IsNull()) {
                    gp_Trsf transf = heloc2.Transformation();
                    bspline2->Transform(transf);  // apply original transformation to control points
                    // Store Underlying Geometry
                    curves.push_back(bspline2);
                }
                else {
                    // BRepBuilderAPI_NurbsConvert failed, try ShapeConstruct_Curve now
                    ShapeConstruct_Curve scc;
                    Handle(Geom_BSplineCurve)
                        spline = scc.ConvertToBSpline(c_geom, u1, u2, Precision::Confusion());
                    if (spline.IsNull()) {
                        throw Standard_Failure(
                            "A curve was not a B-spline and could not be converted into one."
                        );
                    }
                    gp_Trsf transf = heloc2.Transformation();
                    spline->Transform(transf);  // apply original transformation to control points
                    curves.push_back(spline);
                }
            }
        }

        GeomFill_BSplineCurves aSurfBuilder;  // Create Surface Builder

        if (edges.size() == 2) {
            aSurfBuilder.Init(curves[0], curves[1], fstyle);
        }
        else if (edges.size() == 3) {
            aSurfBuilder.Init(curves[0], curves[1], curves[2], fstyle);
        }
        else if (edges.size() == 4) {
            aSurfBuilder.Init(curves[0], curves[1], curves[2], curves[3], fstyle);
        }

        aSurface = aSurfBuilder.Surface();
    }

    BRepBuilderAPI_MakeFace aFaceBuilder;
    Standard_Real v1, v2;
    // transfer surface bounds to face
    aSurface->Bounds(u1, u2, v1, v2);

    aFaceBuilder.Init(aSurface, u1, u2, v1, v2, Precision::Confusion());

    TopoShape aFace(0, Hasher, aFaceBuilder.Face(), getHistoryAlgorithm());

    if (!aFaceBuilder.IsDone()) {
        FC_THROWM(Base::CADKernelError, "Face unable to be constructed");
    }
    if (aFace.isNull()) {
        FC_THROWM(Base::CADKernelError, "Resulting Face is null");
    }

    if (getHistoryAlgorithm() == App::HistoryAlgorithm::V2) {
        // V2 (ops#47): the face is generated from the input edges, and each of its edges and
        // vertices that lies on an input edge or vertex is that element, modified. The face's
        // edges are new shapes, so they are matched by geometry, in the face's index order.
        ShapeMapper mapper;
        for (const auto& faceEdge : aFace.getSubTopoShapes(TopAbs_EDGE)) {
            for (const auto& edge : edges) {
                if (bsplineFaceElementLiesOn(faceEdge.getShape(), edge.getShape())) {
                    mapper.populate(MappingStatus::Modified, edge, {faceEdge});
                }
            }
        }
        for (const auto& faceVertex : aFace.getSubTopoShapes(TopAbs_VERTEX)) {
            for (const auto& edge : edges) {
                for (const auto& vertex : edge.getSubTopoShapes(TopAbs_VERTEX)) {
                    if (bsplineFaceElementLiesOn(faceVertex.getShape(), vertex.getShape())) {
                        mapper.populate(MappingStatus::Modified, vertex, {faceVertex});
                    }
                }
            }
        }
        for (const auto& edge : edges) {
            mapper.populate(MappingStatus::Generated, edge, {aFace});
        }
        return makeShapeWithElementMap(
            aFace.getShape(),
            mapper,
            input,
            op ? op : Part::OpCodes::BSplineFace
        );
    }

    // TODO:  Is this correct?  makeElementBSplineFace is new (there is no corresponding non element
    // version of this operation).  It appears to be reasonable for the BRepBuilderAPI_MakeFace to
    // return more edges than we sent in.  The correspondence between old and  edges is assumed here
    // in resetting the element maps.
    auto newEdges = aFace.getSubTopoShapes(TopAbs_EDGE);
    if (newEdges.size() != edges.size()) {
        FC_WARN("Face edge count mismatch");
    }
    unsigned ind = 0;
    for (auto& edge : newEdges) {
        if (ind < edges.size()) {
            edge.resetElementMap(edges[ind++].elementMap());
        }
    }
    aFace.mapSubElement(newEdges);

    Data::ElementIDRefs sids;
    Data::MappedName edgeName
        = aFace.getMappedName(Data::IndexedName::fromConst("Edge", 1), true, &sids);
    aFace.setElementComboName(
        Data::IndexedName::fromConst("Face", 1),
        {edgeName},
        Part::OpCodes::BSplineFace,
        op,
        &sids
    );
    *this = aFace;
    return *this;
}

/**
 *  Encode and set an element name in the elementMap.  If a hasher is defined, apply it to the name.
 *
 * @param element   The element name(type) that provides 1 one character suffix to the name IF
 * <conditions>.
 * @param names     The subnames to build the name from.  If empty, return the TopoShape MappedName.
 * @param marker    The elementMap name or suffix to start the name with.  If null, use the
 *                  elementMapPrefix.
 * @param op        The op text passed to the element name encoder along with the TopoShape Tag
 * @param _sids     If defined, records the sub ids processed.
 *
 * @return          The encoded, possibly hashed name.
 */
Data::MappedName TopoShape::setElementComboName(
    const Data::IndexedName& element,
    const std::vector<Data::MappedName>& names,
    const char* marker,
    const char* op,
    const Data::ElementIDRefs* _sids
)
{
    if (names.empty()) {
        return Data::MappedName {};
    }
    std::string _marker;
    if (!marker) {
        marker = elementMapPrefix().c_str();
    }
    else if (!boost::starts_with(marker, elementMapPrefix())) {
        _marker = elementMapPrefix() + marker;
        marker = _marker.c_str();
    }
    auto it = names.begin();
    Data::MappedName newName = *it;
    std::ostringstream ss;
    Data::ElementIDRefs sids;
    if (_sids) {
        sids = *_sids;
    }
    if (names.size() == 1) {
        ss << marker;
    }
    else {
        bool first = true;
        ss.str("");
        if (!Hasher) {
            ss << marker;
        }
        ss << '(';
        for (++it; it != names.end(); ++it) {
            if (first) {
                first = false;
            }
            else {
                ss << '|';
            }
            ss << *it;
        }
        ss << ')';
        if (Hasher) {
            sids.push_back(Hasher->getID(ss.str().c_str()));
            ss.str("");
            ss << marker << sids.back().toString();
        }
    }

    ensureElementMap()->encodeElementName(element[0], newName, ss, &sids, Tag, op);
    return elementMap()->setElementName(element, newName, Tag, &sids);
}

std::vector<Data::MappedName> TopoShape::decodeElementComboName(
    const Data::IndexedName& element,
    const Data::MappedName& name,
    const char* marker,
    std::string* postfix
) const
{
    std::vector<Data::MappedName> names;
    if (!element || getHistoryAlgorithm() == App::HistoryAlgorithm::V2) {
        return names;
    }
    if (!marker) {
        marker = "";
    }
    int plen = (int)elementMapPrefix().size();
    int markerLen = strlen(marker);
    int len;
    int pos = name.findTagInElementName(nullptr, &len);
    if (pos < 0) {
        // It is possible to encode combo name without using a tag, e.g.
        // Sketcher object creates wire using edges that are created by itself,
        // so there will be no tag to encode.
        //
        // In this case, just search for the brackets
        len = name.find("(");
        if (len < 0) {
            // No bracket is also possible, if there is only one name in the combo
            pos = len = name.size();
        }
        else {
            pos = name.find(")");
            if (pos < 0) {
                // non closing bracket?
                return {};
            }
            ++pos;
        }
        if (len <= (int)markerLen) {
            return {};
        }
        len -= markerLen + plen;
    }

    if (name.find(elementMapPrefix(), len) != len || name.find(marker, len + plen) != len + plen) {
        return {};
    }

    names.emplace_back(name, 0, len);

    std::string text;
    len += plen + markerLen;
    name.appendToBuffer(text, len, pos - len);

    if (this->Hasher) {
        if (auto id = App::StringID::fromString(names.back().toRawBytes())) {
            if (App::StringIDRef sid = this->Hasher->getID(id)) {
                names.pop_back();
                names.emplace_back(sid);
            }
            else {
                return names;
            }
        }
        if (auto id = App::StringID::fromString(text.c_str())) {
            if (App::StringIDRef sid = this->Hasher->getID(id)) {
                text = sid.dataToText();
            }
            else {
                return names;
            }
        }
    }
    if (text.empty() || text[0] != '(') {
        return names;
    }
    auto endPos = text.rfind(')');
    if (endPos == std::string::npos) {
        return names;
    }

    if (postfix) {
        *postfix = text.substr(endPos + 1);
    }

    text.resize(endPos);
    std::istringstream iss(text.c_str() + 1);
    std::string token;
    while (std::getline(iss, token, '|')) {
        names.emplace_back(token);
    }
    return names;
}

/**
 * Reorient the outer and inner wires of the TopoShape
 *
 * @param innerWiresOutput If this is not a nullptr, then any inner wires processed will be returned
 * in this vector.
 * @param reorient One of NoReorient, Reorient (Outer forward, inner reversed),
 *                 ReorientForward (all forward), or ReorientReversed (all reversed)
 *
 * @return The outer wire, or an empty TopoShape if this isn't a Face, has no Face subShapes, or the
 *         outer wire isn't found.
 */
TopoShape TopoShape::splitWires(std::vector<TopoShape>* innerWiresOutput, SplitWireReorient reorient) const
{
    // ShapeAnalysis::OuterWire() is un-reliable for some reason. OCC source
    // code shows it works by creating face using each wire, and then test using
    // BRepTopAdaptor_FClass2d::PerformInfinitePoint() to check if it is an
    // outbound wire. And practice shows it sometimes returns the incorrect
    // result. Need more investigation. Note that this may be related to
    // unreliable solid face orientation
    // (https://forum.freecad.org/viewtopic.php?p=446006#p445674)
    //
    // Use BrepTools::OuterWire() instead. OCC source code shows it is
    // implemented using simple bound box checking. This should be a
    // reliable method, especially so for a planar face.

    TopoDS_Shape outerWire;

    if (shapeType(true) == TopAbs_FACE) {
        outerWire = BRepTools::OuterWire(TopoDS::Face(_Shape));
    }
    else if (countSubShapes(TopAbs_FACE) == 1) {
        outerWire = BRepTools::OuterWire(TopoDS::Face(getSubShape(TopAbs_FACE, 1)));
    }

    if (outerWire.IsNull()) {
        return TopoShape {getHistoryAlgorithm()};
    }

    TopAbs_Orientation orientOuter, orientInner;
    switch (reorient) {
        case ReorientReversed:
            orientOuter = orientInner = TopAbs_REVERSED;
            break;
        case ReorientForward:
            orientOuter = orientInner = TopAbs_FORWARD;
            break;
        default:
            orientOuter = TopAbs_FORWARD;
            orientInner = TopAbs_REVERSED;
            break;
    }

    auto reorientIfNecessary = [reorient](TopoShape& shape, TopAbs_Orientation orient) {
        if (reorient == NoReorient) {
            return;
        }

        // Special case of single edge wire. Make sure the edge is in the
        // required orientation. This is necessary because BRepFill_OffsetWire
        // has special handling of circular edge offset, which seem to only
        // respect the edge orientation and disregard the wire orientation. The
        // orientation is used to determine whether to shrink or expand.
        if (shape.countSubShapes(TopAbs_EDGE) == 1) {
            TopoDS_Shape edge = shape.getSubShape(TopAbs_EDGE, 1);
            if (edge.Orientation() == orient) {
                if (shape._Shape.Orientation() == orient) {
                    return;
                }
            }
            else {
                edge = edge.Oriented(orient);
            }

            BRepBuilderAPI_MakeWire mkWire(TopoDS::Edge(edge));
            shape.setShape(mkWire.Shape(), false);
        }
        else if (shape._Shape.Orientation() != orient) {
            shape.setShape(shape._Shape.Oriented(orient), false);
        }
    };

    TopoShape outerWireResult {getHistoryAlgorithm()};

    for (auto& wire : getSubTopoShapes(TopAbs_WIRE)) {
        if (wire.getShape().IsSame(outerWire)) {
            outerWireResult = wire;
            reorientIfNecessary(outerWireResult, orientOuter);
            continue;
        }

        if (innerWiresOutput) {
            innerWiresOutput->push_back(wire);
            reorientIfNecessary(innerWiresOutput->back(), orientInner);
        }
    }

    return outerWireResult;
}

bool TopoShape::isLinearEdge() const
{
    if (isNull() || getShape().ShapeType() != TopAbs_EDGE) {
        return false;
    }

    auto tdsEdge = TopoDS::Edge(getShape());
    if (tdsEdge.IsNull()) {
        return false;
    }

    // BRep_Tool::Curve() will transform the returned geometry, so no need to
    // check the shape's placement.
    auto curve = BRepAdaptor_Curve(tdsEdge).Curve().Curve();
    return curve && GeomCurve::isLinear(curve);
}

bool TopoShape::isPlanarFace(double tol) const
{
    if (isNull() || getShape().ShapeType() != TopAbs_FACE) {
        return false;
    }

    return GeomSurface::isPlanar(
        BRepAdaptor_Surface(TopoDS::Face(getShape())).Surface().Surface(),
        nullptr,
        tol
    );
}

// TODO:  Refactor this into two methods.  Totally separate concerns here.
bool TopoShape::linearize(LinearizeFace do_face, LinearizeEdge do_edge)
{
    bool touched = false;
    BRep_Builder builder;
    // Note: changing edge geometry seems to mess up with face (or shell, or solid)
    // Probably need to do some fix afterwards.
    if (do_edge == LinearizeEdge::linearizeEdges) {
        for (auto& edge : getSubTopoShapes(TopAbs_EDGE)) {
            TopoDS_Edge e = TopoDS::Edge(edge.getShape());
            BRepAdaptor_Curve curve(e);
            if (curve.GetType() == GeomAbs_Line || !edge.isLinearEdge()) {
                continue;
            }
            std::unique_ptr<Geometry> geo(
                Geometry::fromShape(e.Located(TopLoc_Location()).Oriented(TopAbs_FORWARD))
            );
            std::unique_ptr<Geometry> gline(static_cast<GeomCurve*>(geo.get())->toLine());
            if (gline) {
                touched = true;
                builder.UpdateEdge(
                    e,
                    Handle(Geom_Curve)::DownCast(gline->handle()),
                    e.Location(),
                    BRep_Tool::Tolerance(e)
                );
            }
        }
    }
    if (do_face == LinearizeFace::linearizeFaces) {
        for (auto& face : getSubTopoShapes(TopAbs_FACE)) {
            TopoDS_Face f = TopoDS::Face(face.getShape());
            BRepAdaptor_Surface surf(f);
            if (surf.GetType() == GeomAbs_Plane || !face.isPlanarFace()) {
                continue;
            }
            std::unique_ptr<Geometry> geo(
                Geometry::fromShape(f.Located(TopLoc_Location()).Oriented(TopAbs_FORWARD))
            );
            std::unique_ptr<Geometry> gplane(static_cast<GeomSurface*>(geo.get())->toPlane());
            if (gplane) {
                touched = true;
                builder.UpdateFace(
                    f,
                    Handle(Geom_Surface)::DownCast(gplane->handle()),
                    f.Location(),
                    BRep_Tool::Tolerance(f)
                );
            }
        }
    }
    return touched;
}

struct MapperFill: Part::TopoShape::Mapper
{
    BRepFill_Generator& maker;
    explicit MapperFill(BRepFill_Generator& maker)
        : maker(maker)
    {}
    const std::vector<TopoDS_Shape>& generated(const TopoDS_Shape& s) const override
    {
        _res.clear();
        try {
            TopTools_ListIteratorOfListOfShape it;
            for (it.Initialize(maker.GeneratedShapes(s)); it.More(); it.Next()) {
                _res.push_back(it.Value());
            }
        }
        catch (const Standard_Failure& e) {
            if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
                FC_WARN("Exception on shape mapper: " << e.GetMessageString());
            }
        }
        return _res;
    }
};

const std::vector<TopoDS_Shape>& MapperMaker::modified(const TopoDS_Shape& s) const
{
    _res.clear();
    try {
        TopTools_ListIteratorOfListOfShape it;
        for (it.Initialize(maker.Modified(s)); it.More(); it.Next()) {
            _res.push_back(it.Value());
        }
    }
    catch (const Standard_Failure& e) {
        if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
            FC_WARN("Exception on shape mapper: " << e.GetMessageString());
        }
    }
    return _res;
}

const std::vector<TopoDS_Shape>& MapperMaker::generated(const TopoDS_Shape& s) const
{
    _res.clear();
    try {
        TopTools_ListIteratorOfListOfShape it;
        for (it.Initialize(maker.Generated(s)); it.More(); it.Next()) {
            _res.push_back(it.Value());
        }
    }
    catch (const Standard_Failure& e) {
        if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
            FC_WARN("Exception on shape mapper: " << e.GetMessageString());
        }
    }
    return _res;
}

MapperHistory::MapperHistory(const Handle(BRepTools_History) & history)
    : history(history)
{}

MapperHistory::MapperHistory(const Handle(BRepTools_ReShape) & reshape)
{
    if (reshape) {
        history = reshape->History();
    }
}

MapperHistory::MapperHistory(ShapeFix_Root& fix)
{
    if (fix.Context()) {
        history = fix.Context()->History();
    }
}

const std::vector<TopoDS_Shape>& MapperHistory::modified(const TopoDS_Shape& s) const
{
    _res.clear();
    try {
        if (history) {
            TopTools_ListIteratorOfListOfShape it;
            for (it.Initialize(history->Modified(s)); it.More(); it.Next()) {
                _res.push_back(it.Value());
            }
        }
    }
    catch (const Standard_Failure& e) {
        if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
            FC_WARN("Exception on shape mapper: " << e.GetMessageString());
        }
    }
    return _res;
}

const std::vector<TopoDS_Shape>& MapperHistory::generated(const TopoDS_Shape& s) const
{
    _res.clear();
    try {
        if (history) {
            TopTools_ListIteratorOfListOfShape it;
            for (it.Initialize(history->Generated(s)); it.More(); it.Next()) {
                _res.push_back(it.Value());
            }
        }
    }
    catch (const Standard_Failure& e) {
        if (FC_LOG_INSTANCE.isEnabled(FC_LOGLEVEL_LOG)) {
            FC_WARN("Exception on shape mapper: " << e.GetMessageString());
        }
    }
    return _res;
}

// topo naming counterpart of TopoShape::makeShell()
TopoShape& TopoShape::makeElementShell(bool silent, const char* op, ElementMapPolicy elementMapPolicy)
{
    if (silent) {
        if (isNull()) {
            return *this;
        }

        if (shapeType(true) != TopAbs_COMPOUND) {
            return *this;
        }

        // we need a compound that consists of only faces
        TopExp_Explorer it;
        // no shells
        if (hasSubShape(TopAbs_SHELL)) {
            return *this;
        }

        // no wires outside a face
        it.Init(_Shape, TopAbs_WIRE, TopAbs_FACE);
        if (it.More()) {
            return *this;
        }

        // no edges outside a wire
        it.Init(_Shape, TopAbs_EDGE, TopAbs_WIRE);
        if (it.More()) {
            return *this;
        }

        // no vertexes outside an edge
        it.Init(_Shape, TopAbs_VERTEX, TopAbs_EDGE);
        if (it.More()) {
            return *this;
        }
    }
    else if (!hasSubShape(TopAbs_FACE)) {
        FC_THROWM(Base::CADKernelError, "Cannot make shell without face");
    }

    BRep_Builder builder;
    TopoDS_Shape shape;
    TopoDS_Shell shell;
    builder.MakeShell(shell);

    try {
        for (const auto& face : getSubShapes(TopAbs_FACE)) {
            builder.Add(shell, face);
        }

        Data::ElementMapPtr elementMap;
        if (elementMapPolicy == ElementMapPolicy::Propagate) {
            TopoShape tmp(Tag, Hasher, shell, getHistoryAlgorithm());
            tmp.resetElementMap();
            tmp.mapSubElement(*this, op);
            elementMap = tmp.elementMap();
        }

        shape = shell;
        BRepCheck_Analyzer check(shell);
        if (!check.IsValid()) {
            ShapeUpgrade_ShellSewing sewShell;
            shape = sewShell.ApplySewing(shell);
            // TODO confirm the above won't change OCCT topological naming
        }

        if (shape.IsNull()) {
            if (silent) {
                return *this;
            }
            FC_THROWM(NullShapeException, "Failed to make shell");
        }

        if (shape.ShapeType() != TopAbs_SHELL) {
            if (silent) {
                return *this;
            }
            FC_THROWM(
                Base::CADKernelError,
                "Failed to make shell: unexpected output shape type "
                    << shapeType(shape.ShapeType(), true)
            );
        }

        setShape(shape);
        if (elementMapPolicy == ElementMapPolicy::Drop) {
            dropElementNaming();
        }
        else {
            resetElementMap(elementMap);
        }
    }
    catch (Standard_Failure& e) {
        if (!silent) {
            FC_THROWM(Base::CADKernelError, "Failed to make shell: " << e.GetMessageString());
        }
    }

    return *this;
}

TopoShape& TopoShape::makeElementShellFromWires(
    const std::vector<TopoShape>& wires,
    bool silent,
    const char* op,
    ElementMapPolicy elementMapPolicy
)
{
    BRepFill_Generator maker;
    for (auto& w : wires) {
        if (w.shapeType(silent) == TopAbs_WIRE) {
            maker.AddWire(TopoDS::Wire(w.getShape()));
        }
    }
    if (wires.empty()) {
        if (silent) {
            _Shape.Nullify();
            return *this;
        }
        FC_THROWM(NullShapeException, "No input shapes");
    }
    maker.Perform();
    this->makeShapeWithElementMap(maker.Shell(), MapperFill(maker), wires, op, elementMapPolicy);
    return *this;
}

bool TopoShape::fixSolidOrientation()
{
    if (isNull()) {
        return false;
    }

    if (shapeType() == TopAbs_SOLID) {
        TopoDS_Solid solid = TopoDS::Solid(_Shape);
        MassProperties::orientClosedSolid(solid);
        if (solid.IsEqual(_Shape)) {
            return false;
        }
        setShape(solid, false);
        return true;
    }

    if (shapeType() == TopAbs_COMPOUND || shapeType() == TopAbs_COMPSOLID) {
        auto shapes = getSubTopoShapes();
        bool touched = false;
        for (auto& s : shapes) {
            if (s.fixSolidOrientation()) {
                touched = true;
            }
        }
        if (!touched) {
            return false;
        }

        BRep_Builder builder;
        if (shapeType() == TopAbs_COMPOUND) {
            TopoDS_Compound comp;
            builder.MakeCompound(comp);
            for (auto& s : shapes) {
                if (!s.isNull()) {
                    builder.Add(comp, s.getShape());
                }
            }
            setShape(comp, false);
        }
        else {
            TopoDS_CompSolid comp;
            builder.MakeCompSolid(comp);
            for (auto& s : shapes) {
                if (!s.isNull()) {
                    builder.Add(comp, s.getShape());
                }
            }
            setShape(comp, false);
        }
        return true;
    }

    return false;
}

TopoShape& TopoShape::makeElementBoolean(
    const char* maker,
    const TopoShape& shape,
    const char* op,
    double tolerance,
    ElementMapPolicy elementMapPolicy
)
{
    return makeElementBoolean(maker, std::vector<TopoShape>(1, shape), op, tolerance, elementMapPolicy);
}


// TODO: Refactor this so that each OpCode type is a separate method to reduce size
TopoShape& TopoShape::makeElementBoolean(
    const char* maker,
    const std::vector<TopoShape>& shapes,
    const char* op,
    double tolerance,
    ElementMapPolicy elementMapPolicy,
    BooleanInputCheck inputCheck,
    bool* inputsValid
)
{
    if (inputsValid) {
        *inputsValid = false;
    }
    if (!maker) {
        FC_THROWM(Base::CADKernelError, "no maker");
    }

    if (shapes.empty()) {
        FC_THROWM(NullShapeException, "Null shape");
    }

    if (Base::Sequencer().wasCanceled()) {
        FC_THROWM(Base::CADKernelError, "User aborted");
    }

    if (!op) {
        op = maker;
    }

    if (strcmp(maker, Part::OpCodes::Compound) == 0) {
        return makeElementCompound(
            shapes,
            op,
            SingleShapeCompoundCreationPolicy::returnShape,
            elementMapPolicy
        );
    }
    else if (boost::starts_with(maker, Part::OpCodes::Face)) {
        std::string prefix(Part::OpCodes::Face);
        prefix += '.';
        const char* face_maker = 0;
        if (boost::starts_with(maker, prefix)) {
            face_maker = maker + prefix.size();
        }
        return makeElementFace(shapes, op, face_maker, nullptr, elementMapPolicy);
    }
    else if (strcmp(maker, Part::OpCodes::Wire) == 0) {
        return makeElementWires(
            shapes,
            op,
            0.0,
            ConnectionPolicy::mergeWithTolerance,
            nullptr,
            elementMapPolicy
        );
    }
    else if (strcmp(maker, Part::OpCodes::Compsolid) == 0) {
        BRep_Builder builder;
        TopoDS_CompSolid Comp;
        builder.MakeCompSolid(Comp);
        for (auto& s : shapes) {
            if (!s.isNull()) {
                builder.Add(Comp, s.getShape());
            }
        }
        setShape(Comp);
        if (elementMapPolicy == ElementMapPolicy::Drop) {
            dropElementNaming();
        }
        else {
            mapSubElement(shapes, op);
        }
        return *this;
    }

    if (strcmp(maker, Part::OpCodes::Pipe) == 0) {
        if (shapes.size() != 2) {
            FC_THROWM(Base::CADKernelError, "Sweep needs a spine and a shape");
        }
        if (shapes[0].isNull() || shapes[1].isNull()) {
            FC_THROWM(Base::CADKernelError, "Cannot sweep with empty spine or empty shape");
        }
        if (shapes[0].getShape().ShapeType() != TopAbs_WIRE) {
            FC_THROWM(Base::CADKernelError, "Spine shape is not a wire");
        }
        BRepOffsetAPI_MakePipe mkPipe(TopoDS::Wire(shapes[0].getShape()), shapes[1].getShape());
        return makeElementShape(mkPipe, shapes, op, elementMapPolicy);
    }

    if (strcmp(maker, Part::OpCodes::Shell) == 0) {
        BRep_Builder builder;
        TopoDS_Shell shell;
        builder.MakeShell(shell);
        for (auto& s : shapes) {
            builder.Add(shell, s.getShape());
        }
        setShape(shell);
        if (elementMapPolicy == ElementMapPolicy::Drop) {
            dropElementNaming();
        }
        else {
            mapSubElement(shapes, op);
        }
        BRepCheck_Analyzer check(shell);
        if (!check.IsValid()) {
            ShapeUpgrade_ShellSewing sewShell;
            setShape(sewShell.ApplySewing(shell), false);
            // TODO: confirm the above won't change OCCT topological naming
            if (elementMapPolicy == ElementMapPolicy::Drop) {
                dropElementNaming();
            }
        }
        return *this;
    }

    if (strcmp(maker, Part::OpCodes::Xor) == 0) {
        return makeElementXor(shapes, op, tolerance, elementMapPolicy);
    }

    bool buildShell = true;

    std::vector<TopoShape> _shapes;
    // How many of the inputs come from the first argument: all of its parts when Fuse expands it
    int firstArgumentInputs = 1;
    if (strcmp(maker, Part::OpCodes::Fuse) == 0) {
        for (auto it = shapes.begin(); it != shapes.end(); ++it) {
            auto& s = *it;
            if (s.isNull()) {
                if (it == shapes.begin()) {
                    return *this;  // Compatible with pre-TNP allowing <null shape>.fuse() behavior
                }
                FC_THROWM(NullShapeException, "Null input shape");
            }
            if (s.shapeType() == TopAbs_COMPOUND) {
                if (_shapes.empty()) {
                    _shapes.insert(_shapes.end(), shapes.begin(), it);
                }
                expandCompound(s, _shapes);
                if (it == shapes.begin()) {
                    firstArgumentInputs = static_cast<int>(_shapes.size());
                }
            }
            else if (_shapes.size()) {
                _shapes.push_back(s);
            }
        }
    }
    else if (strcmp(maker, Part::OpCodes::Cut) == 0 || strcmp(maker, Part::OpCodes::Common) == 0) {
        for (unsigned i = 1; i < shapes.size(); ++i) {
            auto& s = shapes[i];
            if (s.isNull()) {
                FC_THROWM(NullShapeException, "Null input shape");
            }
            if (s.shapeType() == TopAbs_COMPOUND) {
                if (_shapes.empty()) {
                    _shapes.insert(_shapes.end(), shapes.begin(), shapes.begin() + i);
                }
                const auto sizeBeforeExpansion = _shapes.size();
                expandCompound(s, _shapes);
                if (strcmp(maker, Part::OpCodes::Common) == 0
                    && _shapes.size() == sizeBeforeExpansion) {
                    _shapes.push_back(s);
                }
            }
            else if (_shapes.size()) {
                _shapes.push_back(s);
            }
        }
    }

    if (tolerance != 0.0 && _shapes.empty()) {
        _shapes = shapes;
    }

    const auto& inputs = _shapes.size() ? _shapes : shapes;
    if (inputs.empty()) {
        FC_THROWM(NullShapeException, "Null input shape");
    }
    if (inputs.size() == 1) {
        *this = inputs[0];
        if (elementMapPolicy == ElementMapPolicy::Drop) {
            dropElementNaming();
        }
        if (shapes.size() == 1) {
            // _shapes has fewer items than shapes due to compound expansion.
            // Only warn if the caller passes one shape.
            FC_WARN("Boolean operation with only one shape input");
        }
        return *this;
    }

    std::unique_ptr<BRepAlgoAPI_BooleanOperation> mk;
    if (strcmp(maker, Part::OpCodes::Fuse) == 0) {
        mk.reset(new FCBRepAlgoAPI_Fuse);
    }
    else if (strcmp(maker, Part::OpCodes::Cut) == 0) {
        mk.reset(new FCBRepAlgoAPI_Cut);
    }
    else if (strcmp(maker, Part::OpCodes::Common) == 0) {
        mk.reset(new FCBRepAlgoAPI_Common);
    }
    else if (strcmp(maker, Part::OpCodes::Section) == 0) {
        mk.reset(new FCBRepAlgoAPI_Section);
        buildShell = false;
    }
    else {
        FC_THROWM(Base::CADKernelError, "Unknown maker");
    }

    TopTools_ListOfShape shapeArguments, shapeTools;

    std::vector<TopoShape> fixedInputs = inputs;

    bool allValid = true;
    int i = -1;
    for (auto& shape : fixedInputs) {
        if (shape.isNull()) {
            FC_THROWM(NullShapeException, "Null input shape");
        }

        // A first argument the caller vouches for isn't checked (ops#310): the check is a full
        // BRepCheck_Analyzer, and a PartDesign feature's base can be the output of its own boolean
        const bool vouchedFor = inputCheck == BooleanInputCheck::Tools && i + 1 < firstArgumentInputs;
        if (!vouchedFor && !shape.isValid()) {
            allValid = false;
            shape.fix();
        }

        if (++i == 0) {
            shapeArguments.Append(shape.getShape());
        }
        else {
            shapeTools.Append(shape.getShape());
        }
    }

    mk->SetRunParallel(Standard_True);
    OSD_Parallel::SetUseOcctThreads(Standard_True);

    mk->SetArguments(shapeArguments);
    mk->SetTools(shapeTools);
    if (tolerance > 0.0) {
        mk->SetFuzzyValue(tolerance);
    }
    else if (tolerance < 0.0) {
        FCBRepAlgoAPIHelper::setAutoFuzzy(mk.get());
    }
#if OCC_VERSION_HEX >= 0x070600
    mk->Build(std::make_unique<Part::ProgressIndicator>()->Start());
#else
    mk->Build();
#endif
    if (Base::Sequencer().wasCanceled()) {
        FC_THROWM(Base::CADKernelError, "User aborted");
    }
    FCBRepAlgoAPIHelper::checkLostTools(mk.get());
    makeElementShape(*mk, fixedInputs, op, elementMapPolicy);

    if (buildShell) {
        makeElementShell(true, nullptr, elementMapPolicy);
    }
    if (inputsValid) {
        *inputsValid = allValid;
    }
    return *this;
}

bool TopoShape::isSame(const Data::ComplexGeoData& _other) const
{
    if (!_other.isDerivedFrom<TopoShape>()) {
        return false;
    }

    const auto& other = static_cast<const TopoShape&>(_other);
    return Tag == other.Tag && Hasher == other.Hasher && _Shape.IsEqual(other._Shape);
}

long TopoShape::isElementGenerated(Data::MappedName& _name, int depth) const
{
    const App::HistoryAlgorithm& historyAlgo = getHistoryAlgorithm();

    if (historyAlgo == App::HistoryAlgorithm::V1) {
        long res = 0;
        long tag = 0;
        traceElement(_name, [&](const Data::MappedName& name, int offset, long tag2, long) {
            (void)offset;
            if (tag2 < 0) {
                tag2 = -tag2;
            }
            if (tag && tag2 != tag) {
                if (--depth < 1) {
                    return true;
                }
            }
            tag = tag2;
            if (depth == 1 && name.startsWith(genPostfix(), offset)) {
                res = tag;
                return true;
            }
            return false;
        });

        return res;
    }
    else if (historyAlgo == App::HistoryAlgorithm::V2) {
        const Data::DecodedMappedName& _decodedName = _name.getDecodedMappedName();

        if (_decodedName.size()) {
            const Data::DecodedMappedSection& lastSection = _decodedName.back();

            if (lastSection.iterationTag == std::to_string(Tag)
                && lastSection.hasMapperFlag(Data::MAPPER_FLAG_GENERATED)) {
                return true;
            }
        }
    }

    return false;
}

void TopoShape::reTagElementMap(long tag, App::StringHasherRef hasher, const char* postfix)
{
    ZoneScoped;
    if (!tag) {
        FC_WARN("invalid shape tag for re-tagging");
        return;
    }

    if (_Shape.IsNull()) {
        return;
    }

    const App::HistoryAlgorithm& selectedHistoryAlgorithm = getHistoryAlgorithm();

    if (selectedHistoryAlgorithm == App::HistoryAlgorithm::V1) {
        // Copy before retagging, as upstream does: copyElementMap() names the elements as
        // children of the copy's tag, so a shape without an element map got empty tags (ops#35)
        TopoShape tmp(*this);
        initCache(1);
        Hasher = hasher;
        Tag = tag;

        resetElementMap();
        copyElementMap(tmp, postfix);
        return;
    }

    // A shape that crosses into another document (an App::Link, a path hop or a SubShapeBinder
    // there passes the external postfix): every name gets a boundary section tagged with the
    // local object that brought it in, `<name>|_;_;<tag>;EXT;<index>;<type>;0;_;_`. A name keeps no
    // other trace of the other document, and its tags are that document's object IDs, so
    // without it the history walk takes them for local objects, and a local name with the same
    // tags is the same name (ops#56). A SubShapeBinder passes the key of the support's file in the
    // postfix (boundaryPostfix()), which becomes the section's index: its supports from copies of
    // one file had the same names otherwise (ops#112)
    const bool external = selectedHistoryAlgorithm == App::HistoryAlgorithm::V2 && postfix
        && std::string_view(postfix).starts_with(Data::POSTFIX_EXTERNAL_TAG);
    const std::string boundary = external ? Part::boundaryIndexOf(postfix) : std::string("0");

    if (selectedHistoryAlgorithm == App::HistoryAlgorithm::V2 && Tag && (Tag != tag || external)
        && !getElementMapSize()) {
        // Another object's shape without an element map (e.g. a primitive reached through a
        // Link in another document, or a Body's tip): a V2 retag only fills untagged sections,
        // so it would name nothing. Name the elements as mapSubElement() names a single
        // shape's, as the V1 retag above does (ops#35, ops#41). Across documents also when the
        // two objects' IDs are equal, so the names don't depend on that coincidence (ops#56)
        TopoShape res(tag, hasher, _Shape, selectedHistoryAlgorithm);
        res.mapSubElement(*this);
        *this = res;
        if (external) {
            appendSection(*this, tag, Part::OpCodes::External, boundary, {});
        }
        return;
    }

    initCache(1);
    Hasher = hasher;
    Tag = tag;

    if (selectedHistoryAlgorithm == App::HistoryAlgorithm::V2) {
        auto map = ensureElementMap();
        // Copies of a shape share its map, and the retag renames in place: retag a copy of the
        // map unless this shape is its only holder (`map` itself is the second reference)
        if (map.use_count() > 2) {
            map = map->copy();
            resetElementMap(map);
        }
        map->retagElementMap(tag);
        if (external) {
            appendSection(*this, tag, Part::OpCodes::External, boundary, {});
        }
    }
}

void TopoShape::cacheRelatedElements(
    const Data::MappedName& name,
    HistoryTraceType sameType,
    const QVector<Data::MappedElement>& names
) const
{
    initCache();
    _cache->insertRelation(ShapeRelationKey(name, sameType), names);
}

bool TopoShape::getRelatedElementsCached(
    const Data::MappedName& name,
    HistoryTraceType sameType,
    QVector<Data::MappedElement>& names
) const
{
    if (!_cache) {
        return false;
    }
    auto it = _cache->relations.find(ShapeRelationKey(name, sameType));
    if (it == _cache->relations.end()) {
        return false;
    }
    names = it->second;
    return true;
}

Data::MappedElement TopoShape::chooseMatchingSubShapeByPlaneOrLine(
    const TopoShape& shapeToFind,
    const TopoShape& shapeToLookIn
)
{
    Data::MappedElement result;
    // See if we have a Face.  If so, try to match using a plane.
    auto targetShape = shapeToFind.getSubTopoShape("Face", true);
    if (!targetShape.isNull()) {
        int index = 0;
        for (const auto& searchFace : shapeToLookIn.getSubTopoShapes(TopAbs_FACE)) {
            index++;  // We have to generate the element index.
            if (targetShape.isCoplanar(searchFace)) {
                if (!result.name.empty()) {
                    return {};  // Found more than one, invalidate our guess.  Future: return all
                                // matches to the UI?
                }
                result = shapeToLookIn.getElementName(("Face" + std::to_string(index)).c_str());
            }
        }
    }
    // Alternatively, try to locate an Edge, and try to match.  Currently by exact equivalence;
    // later can improve.
    targetShape = shapeToFind.getSubTopoShape("Edge", true);
    if (!targetShape.isNull()) {  // Try to match edges
        int index = 0;
        for (const auto& searchEdge : shapeToLookIn.getSubTopoShapes(TopAbs_EDGE)) {
            index++;
            if (targetShape.isSame(searchEdge)) {  // TODO: Test for edges that are collinear as
                                                   // really what we want
                if (!result.name.empty()) {
                    return {};  // Found more than one
                }
                result = shapeToLookIn.getElementName(("Edge" + std::to_string(index)).c_str());
            }
        }
    }
    return result;
}

}  // namespace Part
