// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Thomas Anderson <blobfish[at]gmx.com>              *
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
#include <cstdlib>
#include <memory>
#include <string>
#include <utility>
#include <numbers>
#include <iterator>
#include <Bnd_Box.hxx>
#include <BRep_Builder.hxx>
#include <BRep_TEdge.hxx>
#include <BRep_TVertex.hxx>
#include <BRep_Tool.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepLib.hxx>
#include <BRepLib_FuseEdges.hxx>
#include <BRepLib_MakeWire.hxx>
#include <BRepTools.hxx>
#include <BSplCLib.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepGProp.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <Geom2dConvert_CompCurveToBSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Conic.hxx>
#include <Geom_ConicalSurface.hxx>
#include <Geom_Curve.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Geom_ElementarySurface.hxx>
#include <Geom_Plane.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>
#include <Geom_SphericalSurface.hxx>
#include <Geom_Surface.hxx>
#include <Geom_ToroidalSurface.hxx>
#include <GeomAdaptor_Surface.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <gp_Ax3.hxx>
#include <gp_Cone.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Pln.hxx>
#include <gp_Torus.hxx>
#include <GProp_GProps.hxx>
#include <Precision.hxx>
#include <ShapeAnalysis_Curve.hxx>
#include <ShapeAnalysis_Shell.hxx>
#include <ShapeBuild_ReShape.hxx>
#include <ShapeFix_Face.hxx>
#include <Standard_Version.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColgp_SequenceOfPnt.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopoDS_Shape.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_DataMapOfShapeShape.hxx>
#include <TopTools_DataMapOfIntegerListOfShape.hxx>
#include <TopTools_DataMapOfIntegerShape.hxx>

#include <Base/Console.h>
#include <App/ElementNamingUtils.h>

#include "MassProperties.h"
#include "modelRefine.h"


using namespace ModelRefine;


void ModelRefine::getFaceEdges(const TopoDS_Face& face, EdgeVectorType& edges)
{
    TopExp_Explorer it;
    for (it.Init(face, TopAbs_EDGE); it.More(); it.Next()) {
        edges.push_back(TopoDS::Edge(it.Current()));
    }
}

void ModelRefine::boundaryEdges(const FaceVectorType& faces, EdgeVectorType& edgesOut)
{
    // this finds all the boundary edges. Maybe more than one boundary.
    std::list<TopoDS_Edge> edges;
    FaceVectorType::const_iterator faceIt;
    for (faceIt = faces.begin(); faceIt != faces.end(); ++faceIt) {
        EdgeVectorType faceEdges;
        EdgeVectorType::iterator faceEdgesIt;
        getFaceEdges(*faceIt, faceEdges);
        for (faceEdgesIt = faceEdges.begin(); faceEdgesIt != faceEdges.end(); ++faceEdgesIt) {
            bool foundSignal(false);
            std::list<TopoDS_Edge>::iterator edgesIt;
            for (edgesIt = edges.begin(); edgesIt != edges.end(); ++edgesIt) {
                if ((*edgesIt).IsSame(*faceEdgesIt)) {
                    edgesIt = edges.erase(edgesIt);
                    foundSignal = true;
                    break;
                }
            }
            if (!foundSignal) {
                edges.push_back(*faceEdgesIt);
            }
        }
    }

    edgesOut.reserve(edges.size());
    std::copy(edges.begin(), edges.end(), back_inserter(edgesOut));
}

TopoDS_Shell ModelRefine::removeFaces(const TopoDS_Shell& shell, const FaceVectorType& faces)
{
    ShapeBuild_ReShape rebuilder;
    FaceVectorType::const_iterator it;
    for (it = faces.begin(); it != faces.end(); ++it) {
        rebuilder.Remove(*it);
    }
    return TopoDS::Shell(rebuilder.Apply(shell));
}

namespace ModelRefine
{
class WireSort
{
public:
    bool operator()(const TopoDS_Wire& wire1, const TopoDS_Wire& wire2)
    {
        Bnd_Box box1, box2;
        BRepBndLib::Add(wire1, box1);
        BRepBndLib::Add(wire2, box2);
        // Note: This works because we can be sure that the wires do not intersect
        return box2.SquareExtent() < box1.SquareExtent();
    }
};
}  // namespace ModelRefine

////////////////////////////////////////////////////////////////////////////////////////////

void FaceTypeSplitter::addShell(const TopoDS_Shell& shellIn)
{
    shell = shellIn;
}

void FaceTypeSplitter::registerType(const GeomAbs_SurfaceType& type)
{
    typeMap.insert(SplitMapType::value_type(type, FaceVectorType()));
}

bool FaceTypeSplitter::hasType(const GeomAbs_SurfaceType& type) const
{
    return typeMap.find(type) != typeMap.end();
}

void FaceTypeSplitter::split()
{
    TopExp_Explorer shellIt;
    for (shellIt.Init(shell, TopAbs_FACE); shellIt.More(); shellIt.Next()) {
        TopoDS_Face tempFace(TopoDS::Face(shellIt.Current()));
        GeomAbs_SurfaceType currentType = FaceTypedBase::getFaceType(tempFace);
        SplitMapType::iterator mapIt = typeMap.find(currentType);
        if (mapIt == typeMap.end()) {
            continue;
        }
        (*mapIt).second.push_back(tempFace);
    }
}

const FaceVectorType& FaceTypeSplitter::getTypedFaceVector(const GeomAbs_SurfaceType& type) const
{
    if (this->hasType(type)) {
        return (*(typeMap.find(type))).second;
    }
    // error here.
    static FaceVectorType error;
    return error;
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////

FaceAdjacencySplitter::FaceAdjacencySplitter(const TopoDS_Shell& shell)
{
    TopExp_Explorer shellIt;
    for (shellIt.Init(shell, TopAbs_FACE); shellIt.More(); shellIt.Next()) {
        TopTools_ListOfShape shapeList;
        TopExp_Explorer it;
        for (it.Init(shellIt.Current(), TopAbs_EDGE); it.More(); it.Next()) {
            shapeList.Append(it.Current());
        }
        faceToEdgeMap.Add(shellIt.Current(), shapeList);
    }
    TopExp::MapShapesAndAncestors(shell, TopAbs_EDGE, TopAbs_FACE, edgeToFaceMap);
}


void FaceAdjacencySplitter::split(const FaceVectorType& facesIn)
{
    facesInMap.Clear();
    processedMap.Clear();
    adjacencyArray.clear();

    FaceVectorType::const_iterator it;
    for (it = facesIn.begin(); it != facesIn.end(); ++it) {
        facesInMap.Add(*it);
    }
    // the reserve call guarantees the vector will never get "pushed back" in the
    // recursiveFind calls, thus invalidating the iterators. We can be sure of this as any one
    // matched set can't be bigger than the set passed in. if we have seg faults, we will
    // want to turn this tempFaces vector back into a std::list ensuring valid iterators
    // at the expense of std::find speed.
    FaceVectorType tempFaces;
    tempFaces.reserve(facesIn.size() + 1);

    for (it = facesIn.begin(); it != facesIn.end(); ++it) {
        // skip already processed shapes.
        if (processedMap.Contains(*it)) {
            continue;
        }

        tempFaces.clear();
        processedMap.Add(*it);
        recursiveFind(*it, tempFaces);
        if (tempFaces.size() > 1) {
            adjacencyArray.push_back(tempFaces);
        }
    }
}

void FaceAdjacencySplitter::recursiveFind(const TopoDS_Face& face, FaceVectorType& outVector)
{
    outVector.push_back(face);

    const TopTools_ListOfShape& edges = faceToEdgeMap.FindFromKey(face);
    TopTools_ListIteratorOfListOfShape edgeIt;
    for (edgeIt.Initialize(edges); edgeIt.More(); edgeIt.Next()) {
        const TopTools_ListOfShape& faces = edgeToFaceMap.FindFromKey(edgeIt.Value());
        TopTools_ListIteratorOfListOfShape faceIt;
        for (faceIt.Initialize(faces); faceIt.More(); faceIt.Next()) {
            if (!facesInMap.Contains(faceIt.Value())) {
                continue;
            }
            if (processedMap.Contains(faceIt.Value())) {
                continue;
            }
            processedMap.Add(faceIt.Value());
            recursiveFind(TopoDS::Face(faceIt.Value()), outVector);
        }
    }
}

//////////////////////////////////////////////////////////////////////////////////////////////////////

static Handle(Geom_Plane) getGeomPlane(const TopoDS_Face& faceIn);

// FaceTypedPlane::isEqual() on the planes themselves: the first group face's plane, then the face's
static bool planesEqual(const gp_Pln& planeOne, const gp_Pln& planeTwo)
{
    // The distance first: it is the cheaper test, and most planes of a body differ by it
    return planeOne.Distance(planeTwo.Position().Location()) < Precision::Confusion()
        && planeOne.Position().Direction().IsParallel(
            planeTwo.Position().Direction(),
            Precision::Confusion()
        );
}

void FaceEqualitySplitter::split(const FaceVectorType& faces, FaceTypedBase* object)
{
    std::vector<FaceVectorType> tempVector;
    tempVector.reserve(faces.size());
    FaceVectorType::const_iterator faceIt;
    // FREECAD_CH_REFINE_PLANES=off groups planes through isEqual() as before, to compare
    static const bool planesOnce = [] {
#ifdef _MSC_VER
        char* value = nullptr;
        std::size_t size = 0;
        if (_dupenv_s(&value, &size, "FREECAD_CH_REFINE_PLANES") != 0 || !value) {
            return true;
        }
        const bool on = std::string(value) != "off";
        std::free(value);
        return on;
#else
        const char* value = std::getenv("FREECAD_CH_REFINE_PLANES");
        return !value || std::string(value) != "off";
#endif
    }();
    if (planesOnce && object->getType() == GeomAbs_Plane) {
        // The same groups as below, with each face's plane read once: isEqual() reads both
        // faces' surfaces (a copy of each, for a face with a location) at every comparison,
        // a third of a 14600-face pattern's time (ops#640, perf profile 6). A face without a
        // plane equals nothing, as in isEqual()
        std::vector<std::pair<bool, gp_Pln>> firstPlanes;
        firstPlanes.reserve(faces.size());
        for (faceIt = faces.begin(); faceIt != faces.end(); ++faceIt) {
            const Handle(Geom_Plane) surface = getGeomPlane(*faceIt);
            const bool hasPlane = !surface.IsNull();
            const gp_Pln plane = hasPlane ? surface->Pln() : gp_Pln();
            bool foundMatch = false;
            for (std::size_t k = 0; hasPlane && k < tempVector.size(); ++k) {
                if (firstPlanes[k].first && planesEqual(firstPlanes[k].second, plane)) {
                    tempVector[k].push_back(*faceIt);
                    foundMatch = true;
                    break;
                }
            }
            if (!foundMatch) {
                tempVector.emplace_back(1, *faceIt);
                firstPlanes.emplace_back(hasPlane, plane);
            }
        }
    }
    else {
        for (faceIt = faces.begin(); faceIt != faces.end(); ++faceIt) {
            bool foundMatch(false);
            std::vector<FaceVectorType>::iterator tempIt;
            for (tempIt = tempVector.begin(); tempIt != tempVector.end(); ++tempIt) {
                if (object->isEqual((*tempIt).front(), *faceIt)) {
                    (*tempIt).push_back(*faceIt);
                    foundMatch = true;
                    break;
                }
            }
            if (!foundMatch) {
                // (no reserve for the whole input in every group: with most surfaces different
                // that asked for faces x faces of memory)
                tempVector.emplace_back(1, *faceIt);
            }
        }
    }
    std::vector<FaceVectorType>::iterator it;
    for (it = tempVector.begin(); it != tempVector.end(); ++it) {
        if ((*it).size() < 2) {
            continue;
        }
        equalityVector.push_back(*it);
    }
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////////////

GeomAbs_SurfaceType FaceTypedBase::getFaceType(const TopoDS_Face& faceIn)
{
    Handle(Geom_Surface) surface = BRep_Tool::Surface(faceIn);
    GeomAdaptor_Surface surfaceTest(surface);
    return surfaceTest.GetType();
}

// A merged face is built on a copy of the input faces' surface. Its boundary edges are the
// input's own, and an edge keeps its pcurves per surface handle and location. On the input
// faces' own surface (what BRep_Tool::Surface returns for a location-free input), MakeFace and
// ShapeFix_Face would add or shift pcurves that the input faces use, and so corrupt the input in
// place, even when the merged face is then discarded and the input returned unrefined (ops#316).
// A located input already gets a transformed copy from BRep_Tool::Surface.
template<class T>
static Handle(T) copyOfSurface(const Handle(T) & surface)
{
    return surface.IsNull() ? surface : Handle(T)::DownCast(surface->Copy());
}

void FaceTypedBase::boundarySplit(
    const FaceVectorType& facesIn,
    std::vector<EdgeVectorType>& boundariesOut
) const
{
    EdgeVectorType bEdges;
    boundaryEdges(facesIn, bEdges);

    std::list<TopoDS_Edge> edges;
    std::copy(bEdges.begin(), bEdges.end(), back_inserter(edges));
    while (!edges.empty()) {
        TopoDS_Vertex destination = TopExp::FirstVertex(edges.front(), Standard_True);
        TopoDS_Vertex lastVertex = TopExp::LastVertex(edges.front(), Standard_True);
        EdgeVectorType boundary;
        boundary.push_back(edges.front());
        edges.pop_front();
        // single edge closed check.
        if (destination.IsSame(lastVertex)) {
            boundariesOut.push_back(boundary);
            continue;
        }

        bool closedSignal(false);
        std::list<TopoDS_Edge>::iterator it;
        for (it = edges.begin(); it != edges.end();) {
            TopoDS_Vertex currentVertex = TopExp::FirstVertex(*it, Standard_True);
            if (lastVertex.IsSame(currentVertex)) {
                boundary.push_back(*it);
                lastVertex = TopExp::LastVertex(*it, Standard_True);
                edges.erase(it);
                it = edges.begin();
                if (lastVertex.IsSame(destination)) {
                    closedSignal = true;
                    break;
                }
                continue;
            }
            ++it;
        }
        if (closedSignal) {
            boundariesOut.push_back(boundary);
        }
    }
}


///////////////////////////////////////////////////////////////////////////////////////////////////////

FaceTypedPlane::FaceTypedPlane()
    : FaceTypedBase(GeomAbs_Plane)
{}

static Handle(Geom_Plane) getGeomPlane(const TopoDS_Face& faceIn)
{
    Handle(Geom_Plane) planeSurfaceOut;
    Handle(Geom_Surface) surface = BRep_Tool::Surface(faceIn);
    if (!surface.IsNull()) {
        planeSurfaceOut = Handle(Geom_Plane)::DownCast(surface);
        if (planeSurfaceOut.IsNull()) {
            Handle(Geom_RectangularTrimmedSurface)
                trimmedSurface = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface);
            if (!trimmedSurface.IsNull()) {
                planeSurfaceOut = Handle(Geom_Plane)::DownCast(trimmedSurface->BasisSurface());
            }
        }
    }

    return planeSurfaceOut;
}

bool FaceTypedPlane::isEqual(const TopoDS_Face& faceOne, const TopoDS_Face& faceTwo) const
{
    Handle(Geom_Plane) planeSurfaceOne = getGeomPlane(faceOne);
    Handle(Geom_Plane) planeSurfaceTwo = getGeomPlane(faceTwo);
    if (planeSurfaceOne.IsNull() || planeSurfaceTwo.IsNull()) {
        return false;  // error?
    }

    return planesEqual(planeSurfaceOne->Pln(), planeSurfaceTwo->Pln());
}

GeomAbs_SurfaceType FaceTypedPlane::getType() const
{
    return GeomAbs_Plane;
}

TopoDS_Face FaceTypedPlane::buildFace(const FaceVectorType& faces) const
{
    std::vector<TopoDS_Wire> wires;

    std::vector<EdgeVectorType> splitEdges;
    this->boundarySplit(faces, splitEdges);
    if (splitEdges.empty()) {
        return {};
    }
    std::vector<EdgeVectorType>::iterator splitIt;
    for (splitIt = splitEdges.begin(); splitIt != splitEdges.end(); ++splitIt) {
        BRepLib_MakeWire wireMaker;
        EdgeVectorType::iterator it;
        for (it = (*splitIt).begin(); it != (*splitIt).end(); ++it) {
            wireMaker.Add(*it);
        }
        TopoDS_Wire currentWire = wireMaker.Wire();
        wires.push_back(currentWire);
    }

    std::sort(wires.begin(), wires.end(), ModelRefine::WireSort());

    BRepLib_MakeFace faceMaker(wires.at(0), Standard_True);
    if (faceMaker.Error() != BRepLib_FaceDone) {
        return {};
    }
    TopoDS_Face current = faceMaker.Face();
    if (wires.size() > 1) {
        ShapeFix_Face faceFix(current);
        faceFix.SetContext(new ShapeBuild_ReShape());
        for (size_t index(1); index < wires.size(); ++index) {
            faceFix.Add(wires.at(index));
        }
        faceFix.Perform();
        if (faceFix.Status(ShapeExtend_FAIL)) {
            return {};
        }
        faceFix.FixOrientation();
        faceFix.Perform();
        if (faceFix.Status(ShapeExtend_FAIL)) {
            return {};
        }
        current = faceFix.Face();
    }

    return current;
}

FaceTypedPlane& ModelRefine::getPlaneObject()
{
    static FaceTypedPlane object;
    return object;
}
/////////////////////////////////////////////////////////////////////////////////////////////////////////

FaceTypedCylinder::FaceTypedCylinder()
    : FaceTypedBase(GeomAbs_Cylinder)
{}

static Handle(Geom_CylindricalSurface) getGeomCylinder(const TopoDS_Face& faceIn)
{
    Handle(Geom_CylindricalSurface) cylinderSurfaceOut;
    Handle(Geom_Surface) surface = BRep_Tool::Surface(faceIn);
    if (!surface.IsNull()) {
        cylinderSurfaceOut = Handle(Geom_CylindricalSurface)::DownCast(surface);
        if (cylinderSurfaceOut.IsNull()) {
            Handle(Geom_RectangularTrimmedSurface)
                trimmedSurface = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface);
            if (!trimmedSurface.IsNull()) {
                cylinderSurfaceOut = Handle(Geom_CylindricalSurface)::DownCast(
                    trimmedSurface->BasisSurface()
                );
            }
        }
    }

    return cylinderSurfaceOut;
}

bool FaceTypedCylinder::isEqual(const TopoDS_Face& faceOne, const TopoDS_Face& faceTwo) const
{
    Handle(Geom_CylindricalSurface) surfaceOne = getGeomCylinder(faceOne);
    Handle(Geom_CylindricalSurface) surfaceTwo = getGeomCylinder(faceTwo);
    if (surfaceOne.IsNull() || surfaceTwo.IsNull()) {
        return false;  // probably need an error
    }
    gp_Cylinder cylinderOne = surfaceOne->Cylinder();
    gp_Cylinder cylinderTwo = surfaceTwo->Cylinder();

    if (fabs(cylinderOne.Radius() - cylinderTwo.Radius()) > Precision::Confusion()) {
        return false;
    }
    if (!cylinderOne.Axis().IsCoaxial(cylinderTwo.Axis(), Precision::Angular(), Precision::Confusion())
        && !cylinderOne.Axis().IsCoaxial(
            cylinderTwo.Axis().Reversed(),
            Precision::Angular(),
            Precision::Confusion()
        )) {
        return false;
    }

    return true;
}

GeomAbs_SurfaceType FaceTypedCylinder::getType() const
{
    return GeomAbs_Cylinder;
}

// Auxiliary method
const TopoDS_Face fixFace(const TopoDS_Face& f)
{
    static TopoDS_Face dummy;
    // Fix the face. Orientation doesn't seem to get fixed the first call.
    ShapeFix_Face faceFixer(f);
    faceFixer.SetContext(new ShapeBuild_ReShape());
    faceFixer.Perform();
    if (faceFixer.Status(ShapeExtend_FAIL)) {
        return dummy;
    }
    faceFixer.FixMissingSeam();
    faceFixer.SetContext(new ShapeBuild_ReShape());
    faceFixer.Perform();
    if (faceFixer.Status(ShapeExtend_FAIL)) {
        return dummy;
    }
    faceFixer.FixOrientation();
    faceFixer.SetContext(new ShapeBuild_ReShape());
    faceFixer.Perform();
    if (faceFixer.Status(ShapeExtend_FAIL)) {
        return dummy;
    }
    return faceFixer.Face();
}

// Detect whether a wire encircles the cylinder axis or not. This is done by calculating the
// wire length, oriented with respect to the cylinder axis
bool wireEncirclesAxis(const TopoDS_Wire& wire, const Handle(Geom_CylindricalSurface) & cylinder)
{
    double radius = cylinder->Radius();
    gp_Ax1 cylAxis = cylinder->Axis();
    gp_Vec cv(cylAxis.Location().X(), cylAxis.Location().Y(), cylAxis.Location().Z());  // center of
                                                                                        // cylinder
    gp_Vec av(cylAxis.Direction().X(), cylAxis.Direction().Y(), cylAxis.Direction().Z());  // axis
                                                                                           // of cylinder
    Handle(Geom_Plane) plane = new Geom_Plane(gp_Ax3(cylAxis.Location(), cylAxis.Direction()));
    double totalArc = 0.0;
    bool firstSegment = false;
    bool secondSegment = false;
    gp_Pnt first, last;

    for (TopExp_Explorer ex(wire, TopAbs_EDGE); ex.More(); ex.Next()) {
        TopoDS_Edge segment(TopoDS::Edge(ex.Current()));
        BRepAdaptor_Curve adapt(segment);

        // Get curve data
        double fp = adapt.FirstParameter();
        double lp = adapt.LastParameter();
        gp_Pnt segFirst, segLast;
        gp_Vec segTangent;
        adapt.D1(fp, segFirst, segTangent);
        segLast = adapt.Value(lp);

        double length = 0.0;

        if (adapt.GetType() == GeomAbs_Line) {
            // Any line on the cylinder must be parallel to the cylinder axis
            length = 0.0;
        }
        else if (adapt.GetType() == GeomAbs_Circle) {
            // Arc segment
            length = (lp - fp) * radius;
            // Check orientation in relation to cylinder axis
            GeomAPI_ProjectPointOnSurf proj(segFirst, plane);
            gp_Vec bv = gp_Vec(proj.Point(1).X(), proj.Point(1).Y(), proj.Point(1).Z());
            if ((bv - cv).Crossed(segTangent).IsOpposite(av, Precision::Confusion())) {
                length = -length;
            }
        }
        else {
            // Linearize the edge. Idea taken from ShapeAnalysis.cxx ShapeAnalysis::TotCross2D()
            TColgp_SequenceOfPnt SeqPnt;
            // If the edge has no 3d curve try to create it
            if (adapt.IsCurveOnSurface()) {
                if (BRepLib::BuildCurves3d(segment)) {
                    adapt.Initialize(segment);
                }
            }
            if (adapt.Is3DCurve()) {
                ShapeAnalysis_Curve::GetSamplePoints(adapt.Curve().Curve(), fp, lp, SeqPnt);
            }

            // Calculate the oriented length of the edge
            gp_Pnt begin;
            for (Standard_Integer j = 1; j <= SeqPnt.Length(); j++) {
                gp_Pnt end = SeqPnt.Value(j);

                // Project end point onto the plane
                GeomAPI_ProjectPointOnSurf proj(end, plane);
                if (!proj.IsDone()) {
                    return false;  // FIXME: What else can we do?
                }
                gp_Pnt pend = proj.Point(1);

                if (j > 1) {
                    // Get distance between the points, equal to (linearised) arc length
                    gp_Vec bv = gp_Vec(begin.X(), begin.Y(), begin.Z());
                    gp_Vec dv = gp_Vec(pend.X(), pend.Y(), pend.Z()) - bv;
                    double dist = dv.Magnitude();

                    if (dist > 0) {
                        // Check orientation of this piece in relation to cylinder axis
                        if ((bv - cv).Crossed(dv).IsOpposite(av, Precision::Confusion())) {
                            dist = -dist;
                        }

                        length += dist;
                    }
                }

                begin = pend;
            }
        }

        if (!firstSegment) {
            // First wire segment. Save the start and end point of the segment
            firstSegment = true;
            first = segFirst;
            last = segLast;
        }
        else if (!secondSegment) {
            // Second wire segment. Determine whether the second segment continues from
            // the first or from the last point of the first segment
            secondSegment = true;
            if (last.IsEqual(segFirst, Precision::Confusion())) {
                last = segLast;  // Third segment must begin here
            }
            else if (last.IsEqual(segLast, Precision::Confusion())) {
                last = segFirst;
                length = -length;
            }
            else if (first.IsEqual(segLast, Precision::Confusion())) {
                last = segFirst;
                totalArc = -totalArc;
                length = -length;
            }
            else {  // first.IsEqual(segFirst)
                last = segLast;
                totalArc = -totalArc;
            }
        }
        else {
            if (!last.IsEqual(segFirst, Precision::Confusion())) {
                // The length was calculated in the opposite direction of the wire traversal
                length = -length;
                last = segFirst;
            }
            else {
                last = segLast;
            }
        }

        totalArc += length;
    }

    // For an exact calculation, only two results would be possible:
    // totalArc = 0.0: The wire does not encircle the axis
    // totalArc = 2 * std::numbers::pi * radius: The wire encircles the axis
    return (fabs(totalArc) > std::numbers::pi * radius);
}

// A merged face must stay within one period of the cylinder (2 pi in u). Merging the per-turn pieces
// of a wall between the turns of a thread gives one helical band whose pcurves span several periods
// and no seam edge; OCCT projects points to the principal period, finds them outside that face, and
// its booleans then drop the face's sections (FSLC #30: a revolve across such a wall overlapped nothing).
// Such a group is left as it was, the way ShapeUpgrade_UnifySameDomain leaves it.
static TopoDS_Face withinOnePeriod(const TopoDS_Face& face)
{
    if (face.IsNull()) {
        return face;
    }
    Standard_Real u0 = 0.0, u1 = 0.0, v0 = 0.0, v1 = 0.0;
    BRepTools::UVBounds(face, u0, u1, v0, v1);
    if (u1 - u0 > 2.0 * std::numbers::pi + Precision::PConfusion()) {
        return TopoDS_Face();
    }
    return face;
}

TopoDS_Face FaceTypedCylinder::buildFace(const FaceVectorType& faces) const
{
    static TopoDS_Face dummy;
    std::vector<EdgeVectorType> boundaries;
    boundarySplit(faces, boundaries);
    if (boundaries.empty()) {
        return dummy;
    }

    // make wires
    std::vector<TopoDS_Wire> allWires;
    std::vector<EdgeVectorType>::iterator boundaryIt;
    for (boundaryIt = boundaries.begin(); boundaryIt != boundaries.end(); ++boundaryIt) {
        BRepLib_MakeWire wireMaker;
        EdgeVectorType::iterator it;
        for (it = (*boundaryIt).begin(); it != (*boundaryIt).end(); ++it) {
            wireMaker.Add(*it);
        }
        if (wireMaker.Error() != BRepLib_WireDone) {
            return dummy;
        }
        allWires.push_back(wireMaker.Wire());
    }
    if (allWires.empty()) {
        return dummy;
    }

    // Sort wires by size, that is, the innermost wire comes last
    std::sort(allWires.begin(), allWires.end(), ModelRefine::WireSort());

    // Find outer boundary wires that cut the cylinder into segments. This will be the case f we
    // have removed the seam edges of a complete (360 degrees) cylindrical face
    Handle(Geom_CylindricalSurface) surface = getGeomCylinder(faces.at(0));
    if (surface.IsNull()) {
        return dummy;
    }
    surface = copyOfSurface(surface);
    std::vector<TopoDS_Wire> innerWires, encirclingWires;
    std::vector<TopoDS_Wire>::iterator wireIt;
    for (wireIt = allWires.begin(); wireIt != allWires.end(); ++wireIt) {
        if (wireEncirclesAxis(*wireIt, surface)) {
            encirclingWires.push_back(*wireIt);
        }
        else {
            innerWires.push_back(*wireIt);
        }
    }

    if (encirclingWires.empty()) {
        // We can use the result of the bounding box sort. First wire is the outer wire
        wireIt = allWires.begin();
        BRepBuilderAPI_MakeFace faceMaker(surface, *wireIt);
        if (!faceMaker.IsDone()) {
            return dummy;
        }

        // Add additional boundaries (inner wires).
        for (wireIt++; wireIt != allWires.end(); ++wireIt) {
            faceMaker.Add(*wireIt);
            if (!faceMaker.IsDone()) {
                return dummy;
            }
        }

        return withinOnePeriod(fixFace(faceMaker.Face()));
    }
    else {
        if (encirclingWires.size() != 2) {
            return dummy;
        }

        if (innerWires.empty()) {
            // We have just two outer boundaries
            BRepBuilderAPI_MakeFace faceMaker(surface, encirclingWires.front());
            if (!faceMaker.IsDone()) {
                return dummy;
            }
            faceMaker.Add(encirclingWires.back());
            if (!faceMaker.IsDone()) {
                return dummy;
            }

            return withinOnePeriod(fixFace(faceMaker.Face()));
        }
        else {
            // Add the inner wires first, because otherwise those that cut the seam edge will fail
            wireIt = innerWires.begin();
            BRepBuilderAPI_MakeFace faceMaker(surface, *wireIt, false);
            if (!faceMaker.IsDone()) {
                return dummy;
            }

            // Add additional boundaries (inner wires).
            for (wireIt++; wireIt != innerWires.end(); ++wireIt) {
                faceMaker.Add(*wireIt);
                if (!faceMaker.IsDone()) {
                    return dummy;
                }
            }

            // Add outer boundaries
            faceMaker.Add(encirclingWires.front());
            if (!faceMaker.IsDone()) {
                return dummy;
            }
            faceMaker.Add(encirclingWires.back());
            if (!faceMaker.IsDone()) {
                return dummy;
            }

            return withinOnePeriod(fixFace(faceMaker.Face()));
        }
    }
}

void FaceTypedCylinder::boundarySplit(
    const FaceVectorType& facesIn,
    std::vector<EdgeVectorType>& boundariesOut
) const
{
    // normal edges.
    EdgeVectorType normalEdges;
    ModelRefine::boundaryEdges(facesIn, normalEdges);

    std::list<TopoDS_Edge> sortedEdges;
    std::copy(normalEdges.begin(), normalEdges.end(), back_inserter(sortedEdges));

    while (!sortedEdges.empty()) {
        TopoDS_Vertex destination = TopExp::FirstVertex(sortedEdges.back(), Standard_True);
        TopoDS_Vertex lastVertex = TopExp::LastVertex(sortedEdges.back(), Standard_True);
        bool closedSignal(false);
        std::list<TopoDS_Edge> boundary;
        boundary.push_back(sortedEdges.back());
        sortedEdges.pop_back();

        if (destination.IsSame(lastVertex)) {
            // Single circular edge
            closedSignal = true;
        }
        else {
            std::list<TopoDS_Edge>::iterator sortedIt;
            for (sortedIt = sortedEdges.begin(); sortedIt != sortedEdges.end();) {
                TopoDS_Vertex currentVertex = TopExp::FirstVertex(*sortedIt, Standard_True);

                // Seam edges lie on top of each other. i.e. same. and we remove every match from
                // the list so we don't actually ever compare the same edge.
                if ((*sortedIt).IsSame(boundary.back())) {
                    ++sortedIt;
                    continue;
                }
                if (lastVertex.IsSame(currentVertex)) {
                    boundary.push_back(*sortedIt);
                    lastVertex = TopExp::LastVertex(*sortedIt, Standard_True);
                    if (lastVertex.IsSame(destination)) {
                        closedSignal = true;
                        sortedEdges.erase(sortedIt);
                        break;
                    }
                    sortedEdges.erase(sortedIt);
                    sortedIt = sortedEdges.begin();
                    continue;
                }
                ++sortedIt;
            }
        }
        if (closedSignal) {
            EdgeVectorType temp;
            std::copy(boundary.begin(), boundary.end(), std::back_inserter(temp));
            boundariesOut.push_back(temp);
        }
    }
}

FaceTypedCylinder& ModelRefine::getCylinderObject()
{
    static FaceTypedCylinder object;
    return object;
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////

// Cones, tori and spheres (ops#931). Two adjacent faces on one such surface stayed two faces: a
// chamfer's cone after a mirror fuse, a revolve's cone cut across its seam, a fillet's torus in two
// pieces. Onshape has one face there. Faces are grouped by the surface in space (an axis in either
// direction: two rounds of one full round sweep the same torus about opposite axes), and the merged
// face is built on a copy of the first face's surface from the group's boundary, as the cylinder's.
// A group is left as it is unless the merged face is valid and has the group's area.
static double curveOnSurfaceGap(
    const Handle(Geom_Curve) & curve,
    const TopLoc_Location& location,
    double first,
    double last,
    const Handle(Geom2d_Curve) & curve2d,
    const Handle(Geom_Surface) & surface,
    const TopLoc_Location& where,
    double first2d,
    double last2d
);

namespace
{

// The angle a point turns about an axis, in the plane through the axis' location at right angles
// to it; nothing for a point on the axis
bool angleAbout(const gp_Ax3& frame, const gp_Pnt& point, double& angle)
{
    const gp_Vec d(frame.Location(), point);
    const double x = d.Dot(gp_Vec(frame.XDirection()));
    const double y = d.Dot(gp_Vec(frame.YDirection()));
    if (std::hypot(x, y) < Precision::Confusion()) {
        return false;
    }
    angle = std::atan2(y, x);
    return true;
}

// The angle a point turns about a torus' tube, in the half plane of the torus' axis through it
bool angleAboutTube(const gp_Torus& torus, const gp_Pnt& point, double& angle)
{
    const gp_Ax3& frame = torus.Position();
    double u = 0.0;
    if (!angleAbout(frame, point, u)) {
        return false;
    }
    const gp_Vec radial = gp_Vec(frame.XDirection()) * std::cos(u)
        + gp_Vec(frame.YDirection()) * std::sin(u);
    const gp_Pnt centre = frame.Location().Translated(radial * torus.MajorRadius());
    const gp_Vec d(centre, point);
    const double x = d.Dot(radial);
    const double y = d.Dot(gp_Vec(frame.Direction()));
    if (std::hypot(x, y) < Precision::Confusion()) {
        return false;
    }
    angle = std::atan2(y, x);
    return true;
}

// The angle a wire turns in all, by `angleOf` at points along each edge in the edge's direction
// (degenerated edges left out): about 0 for a wire that does not go round, about 2 pi for one that
// goes round once. Each step is taken under pi
template<typename AngleOf>
double wireTurn(const TopoDS_Wire& wire, const AngleOf& angleOf)
{
    constexpr int steps = 64;
    double total = 0.0;
    for (TopExp_Explorer xp(wire, TopAbs_EDGE); xp.More(); xp.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(xp.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        BRepAdaptor_Curve curve(edge);
        double first = curve.FirstParameter();
        double last = curve.LastParameter();
        if (edge.Orientation() == TopAbs_REVERSED) {
            std::swap(first, last);
        }
        bool have = false;
        double previous = 0.0;
        for (int i = 0; i <= steps; ++i) {
            double angle = 0.0;
            if (!angleOf(curve.Value(first + (last - first) * i / steps), angle)) {
                continue;
            }
            if (have) {
                double step = angle - previous;
                while (step > std::numbers::pi) {
                    step -= 2.0 * std::numbers::pi;
                }
                while (step <= -std::numbers::pi) {
                    step += 2.0 * std::numbers::pi;
                }
                total += step;
            }
            previous = angle;
            have = true;
        }
    }
    return total;
}

double faceArea(const TopoDS_Shape& shape)
{
    GProp_GProps props;
    BRepGProp::SurfaceProperties(shape, props);
    return props.Mass();
}

// The slack of a face's boundary in an area comparison (ops#1044): the sum over its edges (those
// in `only`, if given) of the gap between the edge's curve on this face and its 3D curve, times the
// edge's length. A face's area is integrated inside its curves on the surface. An approximated edge
// (a fillet's, an intersection's) has its curve there a little off its 3D curve, well inside its
// tolerance, and a merged face built on a copy of the surface gets its curves projected again, so
// the areas of a right merge differ by about this much. The curve is the one on this very face,
// with its location: such edges carry older curves on other copies of the surface. Negative where
// a gap cannot be read or exceeds the edge's tolerance
double boundarySlack(const TopoDS_Face& face, const TopTools_IndexedMapOfShape* only)
{
    TopLoc_Location where;
    const Handle(Geom_Surface) surface = BRep_Tool::Surface(face, where);
    if (surface.IsNull()) {
        return -1.0;
    }
    double slack = 0.0;
    for (TopExp_Explorer it(face, TopAbs_EDGE); it.More(); it.Next()) {
        const TopoDS_Edge& edge = TopoDS::Edge(it.Current());
        if (BRep_Tool::Degenerated(edge) || (only && !only->Contains(edge))) {
            continue;
        }
        TopLoc_Location location;
        double first = 0.0, last = 0.0;
        const Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, location, first, last);
        double first2d = 0.0, last2d = 0.0;
        const Handle(Geom2d_Curve) curve2d = BRep_Tool::CurveOnSurface(edge, face, first2d, last2d);
        if (curve.IsNull() || curve2d.IsNull()) {
            return -1.0;
        }
        const double gap = curveOnSurfaceGap(
            curve, location, first, last, curve2d, surface, where, first2d, last2d
        );
        if (gap > BRep_Tool::Tolerance(edge)) {
            return -1.0;  // unreadable (1e100) or loose: no allowance for it
        }
        if (gap > 0.0) {
            slack += gap * GCPnts_AbscissaPoint::Length(BRepAdaptor_Curve(edge));
        }
    }
    return slack;
}

// The merged face covers the group: the same area, within 1e-7 of it plus the slack of the
// group's boundary edges on their own faces and on the merged face (ops#1044). Exact edges add
// nothing. The slack is capped at 1e-4 of the area, so a face built on the complement of a
// periodic surface is still caught. On the merged face the tolerance test of boundarySlack()
// cannot refuse (the face fix has already raised its edges' tolerances to cover their curves):
// there the cap is the guard
bool coversGroup(const FaceVectorType& faces, const TopoDS_Face& face)
{
    double area = 0.0;
    for (const auto& f : faces) {
        area += faceArea(f);
    }
    const double difference = std::fabs(faceArea(face) - area);
    const double allowed = 1e-7 * area + Precision::Confusion();
    if (difference <= allowed) {
        return true;
    }
    EdgeVectorType edges;
    ModelRefine::boundaryEdges(faces, edges);
    TopTools_IndexedMapOfShape boundary;
    for (const auto& edge : edges) {
        boundary.Add(edge);
    }
    double slack = boundarySlack(face, nullptr);
    if (slack < 0.0) {
        return false;
    }
    for (const auto& f : faces) {
        const double own = boundarySlack(f, &boundary);
        if (own < 0.0) {
            return false;
        }
        slack += own;
    }
    return difference <= allowed + std::min(slack, 1e-4 * area);
}

enum class Revolved
{
    Cone,
    Torus,
    Sphere
};

// The face's elementary surface (a trimmed one's basis), or null
Handle(Geom_ElementarySurface) elementarySurface(const TopoDS_Face& face)
{
    Handle(Geom_Surface) surface = BRep_Tool::Surface(face);
    Handle(Geom_RectangularTrimmedSurface)
        trimmed = Handle(Geom_RectangularTrimmedSurface)::DownCast(surface);
    if (!trimmed.IsNull()) {
        surface = trimmed->BasisSurface();
    }
    return Handle(Geom_ElementarySurface)::DownCast(surface);
}

bool sameAxisLine(const gp_Ax1& one, const gp_Ax1& two)
{
    return one.IsCoaxial(two, Precision::Angular(), Precision::Confusion())
        || one.IsCoaxial(two.Reversed(), Precision::Angular(), Precision::Confusion());
}

bool sameLength(double one, double two)
{
    return std::fabs(one - two) <= Precision::Confusion();
}

bool revolvedEqual(Revolved kind, const TopoDS_Face& faceOne, const TopoDS_Face& faceTwo)
{
    switch (kind) {
        case Revolved::Cone: {
            auto one = Handle(Geom_ConicalSurface)::DownCast(elementarySurface(faceOne));
            auto two = Handle(Geom_ConicalSurface)::DownCast(elementarySurface(faceTwo));
            if (one.IsNull() || two.IsNull()) {
                return false;
            }
            // one double cone in space: the apex, the axis line and the half angle
            const gp_Cone c1 = one->Cone();
            const gp_Cone c2 = two->Cone();
            return c1.Apex().Distance(c2.Apex()) <= Precision::Confusion()
                && std::fabs(std::fabs(c1.SemiAngle()) - std::fabs(c2.SemiAngle()))
                <= Precision::Angular()
                && sameAxisLine(c1.Axis(), c2.Axis());
        }
        case Revolved::Torus: {
            auto one = Handle(Geom_ToroidalSurface)::DownCast(elementarySurface(faceOne));
            auto two = Handle(Geom_ToroidalSurface)::DownCast(elementarySurface(faceTwo));
            if (one.IsNull() || two.IsNull()) {
                return false;
            }
            const gp_Torus t1 = one->Torus();
            const gp_Torus t2 = two->Torus();
            return sameLength(t1.MajorRadius(), t2.MajorRadius())
                && sameLength(t1.MinorRadius(), t2.MinorRadius())
                && t1.Location().Distance(t2.Location()) <= Precision::Confusion()
                && sameAxisLine(t1.Axis(), t2.Axis());
        }
        case Revolved::Sphere: {
            auto one = Handle(Geom_SphericalSurface)::DownCast(elementarySurface(faceOne));
            auto two = Handle(Geom_SphericalSurface)::DownCast(elementarySurface(faceTwo));
            if (one.IsNull() || two.IsNull()) {
                return false;
            }
            return sameLength(one->Radius(), two->Radius())
                && one->Location().Distance(two->Location()) <= Precision::Confusion();
        }
    }
    return false;
}

// The UV range of a merged face stays within one period, as withinOnePeriod() for cylinders: in u
// for all three, in v too for a torus
bool withinPeriods(const TopoDS_Face& face, Revolved kind)
{
    Standard_Real u0 = 0.0, u1 = 0.0, v0 = 0.0, v1 = 0.0;
    BRepTools::UVBounds(face, u0, u1, v0, v1);
    const double period = 2.0 * std::numbers::pi + Precision::PConfusion();
    return u1 - u0 <= period && (kind != Revolved::Torus || v1 - v0 <= period);
}

TopoDS_Face buildRevolvedFace(Revolved kind, const FaceVectorType& faces, const std::vector<EdgeVectorType>& boundaries)
{
    Handle(Geom_ElementarySurface) basis = elementarySurface(faces.at(0));
    if (basis.IsNull()) {
        return {};
    }
    basis = copyOfSurface(basis);

    // The group's boundary without its degenerated edges (a cone's apex, a sphere's poles)
    std::vector<EdgeVectorType> kept;
    bool degenerated = false;
    for (const auto& boundary : boundaries) {
        bool all = true;
        bool some = false;
        for (const auto& edge : boundary) {
            const bool d = BRep_Tool::Degenerated(edge);
            all = all && d;
            some = some || d;
        }
        if (some && !all) {
            return {};  // a boundary running into an apex or a pole: not built here
        }
        degenerated = degenerated || some;
        if (!all) {
            kept.push_back(boundary);
        }
    }

    TopoDS_Face face;
    if (kept.empty()) {
        // No boundary but degenerated edges, or none at all: the group is the whole closed
        // surface (a sphere's or a torus' pieces). The surface's own face, on the first face's side
        if (kind == Revolved::Cone) {
            return {};
        }
        BRepBuilderAPI_MakeFace maker(basis, Precision::Confusion());
        if (!maker.IsDone()) {
            return {};
        }
        face = maker.Face();
        face.Orientation(faces.at(0).Orientation());
    }
    else {
        if (degenerated) {
            return {};  // a cap to an apex or a pole beside another boundary: not built here
        }
        std::vector<TopoDS_Wire> wires;
        for (const auto& boundary : kept) {
            BRepLib_MakeWire wireMaker;
            for (const auto& edge : boundary) {
                wireMaker.Add(edge);
            }
            if (wireMaker.Error() != BRepLib_WireDone) {
                return {};
            }
            wires.push_back(wireMaker.Wire());
        }
        std::sort(wires.begin(), wires.end(), ModelRefine::WireSort());

        // Wires that go round the axis, or round a torus' tube, cut the surface into bands
        const gp_Ax3 frame = basis->Position();
        std::vector<TopoDS_Wire> inner, encircling;
        int roundAxis = 0;
        int roundTube = 0;
        for (const auto& wire : wires) {
            bool round = false;
            if (kind == Revolved::Torus) {
                const gp_Torus torus = Handle(Geom_ToroidalSurface)::DownCast(basis)->Torus();
                const double tube = wireTurn(wire, [&torus](const gp_Pnt& p, double& a) {
                    return angleAboutTube(torus, p, a);
                });
                if (std::fabs(tube) > std::numbers::pi) {
                    ++roundTube;
                    round = true;
                }
            }
            const double turn = wireTurn(wire, [&frame](const gp_Pnt& p, double& a) {
                return angleAbout(frame, p, a);
            });
            if (std::fabs(turn) > std::numbers::pi) {
                ++roundAxis;
                round = true;
            }
            (round ? encircling : inner).push_back(wire);
        }
        // the bands built: two wires round the axis (a cylinder's kind) or two round the tube (a
        // torus cut by two half planes of its axis), each going round one way only
        if (roundAxis > 0 && roundTube > 0) {
            return {};
        }

        if (encircling.empty()) {
            BRepBuilderAPI_MakeFace maker(basis, wires.front());
            if (!maker.IsDone()) {
                return {};
            }
            for (std::size_t i = 1; i < wires.size(); ++i) {
                maker.Add(wires[i]);
                if (!maker.IsDone()) {
                    return {};
                }
            }
            face = fixFace(maker.Face());
        }
        else {
            // a band between two wires round the axis, as a cylinder's; a sphere's are caps and
            // zones, not built here
            if (encircling.size() != 2 || kind == Revolved::Sphere) {
                return {};
            }
            std::vector<TopoDS_Wire> order(inner);
            order.push_back(encircling.front());
            order.push_back(encircling.back());
            // the inner wires first, as for a cylinder: those across the seam fail otherwise
            BRepBuilderAPI_MakeFace maker(basis, order.front(), false);
            if (!maker.IsDone()) {
                return {};
            }
            for (std::size_t i = 1; i < order.size(); ++i) {
                maker.Add(order[i]);
                if (!maker.IsDone()) {
                    return {};
                }
            }
            face = fixFace(maker.Face());
        }
    }
    if (face.IsNull() || !withinPeriods(face, kind) || !BRepCheck_Analyzer(face).IsValid()) {
        return {};
    }
    if (!coversGroup(faces, face)) {
        return {};
    }
    return face;
}

class FaceTypedRevolved: public FaceTypedBase
{
public:
    FaceTypedRevolved(GeomAbs_SurfaceType type, Revolved kind)
        : FaceTypedBase(type)
        , kind(kind)
    {}

    bool isEqual(const TopoDS_Face& faceOne, const TopoDS_Face& faceTwo) const override
    {
        try {
            return revolvedEqual(kind, faceOne, faceTwo);
        }
        catch (Standard_Failure&) {
            return false;
        }
    }

    GeomAbs_SurfaceType getType() const override
    {
        return surfaceType;
    }

    TopoDS_Face buildFace(const FaceVectorType& faces) const override
    {
        try {
            std::vector<EdgeVectorType> boundaries;
            boundarySplit(faces, boundaries);
            // every boundary edge in a closed boundary, else the group is left as it is
            EdgeVectorType edges;
            ModelRefine::boundaryEdges(faces, edges);
            std::size_t inBoundaries = 0;
            for (const auto& boundary : boundaries) {
                inBoundaries += boundary.size();
            }
            if (inBoundaries != edges.size()) {
                return {};
            }
            return buildRevolvedFace(kind, faces, boundaries);
        }
        catch (Standard_Failure&) {
            return {};
        }
    }

private:
    Revolved kind;
};

}  // namespace

static FaceTypedBase& getConeObject()
{
    static FaceTypedRevolved object(GeomAbs_Cone, Revolved::Cone);
    return object;
}

static FaceTypedBase& getTorusObject()
{
    static FaceTypedRevolved object(GeomAbs_Torus, Revolved::Torus);
    return object;
}

static FaceTypedBase& getSphereObject()
{
    static FaceTypedRevolved object(GeomAbs_Sphere, Revolved::Sphere);
    return object;
}

// FreeCAD-CH (ops#931, review pri931-r1 F1): makeElementRefine's UnifySameDomain fallback merges
// cone, torus and sphere faces only where the face uniter would: each shell's faces of these kinds
// are grouped as FaceUniter::process() groups them (by kind, by surface, by adjacency), and the
// edges of every face in a group the uniter's buildFace refuses (a pointed cone, a sphere cap or
// zone, a closed surface with holes) are kept. A helix earlier in the body, which sends the
// refine to the fallback, then never decides whether such faces merge. A face with no equal
// neighbour is in no group (FaceAdjacencySplitter keeps groups of two or more), so there is
// nothing to merge it with; faces in no shell keep their edges (review pri931-r2).
void ModelRefine::revolvedEdgesToKeep(const TopoDS_Shape& shape, TopTools_MapOfShape& keep)
{
    FaceTypedBase* types[] = {&getConeObject(), &getTorusObject(), &getSphereObject()};
    auto keepFace = [&keep](const TopoDS_Shape& face) {
        for (TopExp_Explorer xe(face, TopAbs_EDGE); xe.More(); xe.Next()) {
            keep.Add(xe.Current());
        }
    };
    auto revolved = [&types](const TopoDS_Face& face) {
        const GeomAbs_SurfaceType kind = BRepAdaptor_Surface(face).GetType();
        for (FaceTypedBase* type : types) {
            if (type->getType() == kind) {
                return true;
            }
        }
        return false;
    };
    TopTools_MapOfShape inShell;
    for (TopExp_Explorer xs(shape, TopAbs_SHELL); xs.More(); xs.Next()) {
        const TopoDS_Shell& shell = TopoDS::Shell(xs.Current());
        FaceTypeSplitter splitter;
        splitter.addShell(shell);
        for (FaceTypedBase* type : types) {
            splitter.registerType(type->getType());
        }
        splitter.split();
        FaceAdjacencySplitter adjacencySplitter(shell);
        for (FaceTypedBase* type : types) {
            const FaceVectorType& typedFaces = splitter.getTypedFaceVector(type->getType());
            for (const TopoDS_Face& face : typedFaces) {
                inShell.Add(face);
            }
            FaceEqualitySplitter equalitySplitter;
            equalitySplitter.split(typedFaces, type);
            for (std::size_t e = 0; e < equalitySplitter.getGroupCount(); ++e) {
                adjacencySplitter.split(equalitySplitter.getGroup(e));
                for (std::size_t a = 0; a < adjacencySplitter.getGroupCount(); ++a) {
                    const FaceVectorType& group = adjacencySplitter.getGroup(a);
                    if (!type->buildFace(group).IsNull()) {
                        continue;
                    }
                    for (const TopoDS_Face& face : group) {
                        keepFace(face);
                    }
                }
            }
        }
    }
    for (TopExp_Explorer xf(shape, TopAbs_FACE); xf.More(); xf.Next()) {
        const TopoDS_Face& face = TopoDS::Face(xf.Current());
        if (!inShell.Contains(face) && revolved(face)) {
            keepFace(face);
        }
    }
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////

// TODO: change this version after occ fix. Freecad Mantis 1450
#if OCC_VERSION_HEX <= 0x7fffff
void collectConicEdges(const TopoDS_Shell& shell, TopTools_IndexedMapOfShape& map)
{
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(shell, TopAbs_EDGE, edges);

    for (int index = 1; index <= edges.Extent(); ++index) {
        const TopoDS_Edge& currentEdge = TopoDS::Edge(edges.FindKey(index));
        if (currentEdge.IsNull()) {
            continue;
        }
        TopLoc_Location location;
        Standard_Real first, last;
        const Handle(Geom_Curve) & curve = BRep_Tool::Curve(currentEdge, location, first, last);
        if (curve.IsNull()) {
            continue;
        }
        if (curve->IsKind(STANDARD_TYPE(Geom_Conic))) {
            map.Add(currentEdge);
        }
    }
}
#endif

// A seam is walked twice by its face's wire, with a pcurve for each pass. Fusing it
// rebuilds only one of them, leaving the wire unable to close.
// This is similar to collectConicEdges but for seam edges, which are always closed in their face.
static void collectSeamEdges(const TopoDS_Shell& shell, TopTools_IndexedMapOfShape& map)
{
    for (TopExp_Explorer fx(shell, TopAbs_FACE); fx.More(); fx.Next()) {
        const TopoDS_Face& face = TopoDS::Face(fx.Current());
        for (TopExp_Explorer ex(face, TopAbs_EDGE); ex.More(); ex.Next()) {
            const TopoDS_Edge edge = TopoDS::Edge(ex.Current());
            if (!edge.IsNull() && BRep_Tool::IsClosed(edge, face)) {
                map.Add(edge);
            }
        }
    }
}

// The fuse of edges, checked (ops#640, Case Base's Finger Hole after an exact Finger Grip Overhang
// Fillet 2). BRepLib_FuseEdges joins the 2D curves of the edges it fuses (UpdatePCurve): where
// the first edge's does not span the fused edge, it adds the others' whole, not over each edge's
// own range. Two spans of one B-spline on a wall, the first with a 2D curve of its own on the
// wall's plane and the second on a part of a longer one, gave an edge whose 2D curve ran back
// along the whole of the second: 7.98 mm off its 3D curve. The shape check passes that, because
// the face fix raises the edge's and its vertices' tolerance to cover the gap, and every later
// Boolean on the wall is wrong. So: a fused edge whose curve on a face leaves its 3D curve gets
// that curve joined again from its edges' own ranges; one that still leaves it is not fused; and
// a fuse after which any tolerance grew past growthAllowed() is undone for its edges.

// What a tolerance may become through a fuse of edges
static double growthAllowed(double tolerance)
{
    return 10.0 * std::max(tolerance, 1e-6);
}

// The largest distance of an edge's curve on one surface from its 3D curve, at the same parameter
static double curveOnSurfaceGap(
    const Handle(Geom_Curve) & curve,
    const TopLoc_Location& location,
    double first,
    double last,
    const Handle(Geom2d_Curve) & curve2d,
    const Handle(Geom_Surface) & surface,
    const TopLoc_Location& where,
    double first2d,
    double last2d
)
{
    constexpr double unknown = 1e100;
    try {
        const gp_Trsf toWorld = location.Transformation();
        const gp_Trsf surfaceToWorld = where.Transformation();
        double gap = 0.0;
        constexpr int samples = 9;
        for (int index = 0; index < samples; ++index) {
            const double at = static_cast<double>(index) / (samples - 1);
            const gp_Pnt on3d = curve->Value(first + (last - first) * at).Transformed(toWorld);
            const gp_Pnt2d uv = curve2d->Value(first2d + (last2d - first2d) * at);
            const gp_Pnt onFace = surface->Value(uv.X(), uv.Y()).Transformed(surfaceToWorld);
            gap = std::max(gap, on3d.Distance(onFace));
        }
        return gap;
    }
    catch (const Standard_Failure&) {
        return unknown;
    }
}

// The curve of a fused edge on one surface, joined from its edges' own curves there: each over
// its edge's own range, in the order of the parameter. Null where they don't adjoin
static Handle(Geom2d_Curve) joinedCurveOnSurface(
    const TopTools_ListOfShape& edges,
    const Handle(Geom_Surface) & surface,
    const TopLoc_Location& where,
    double first,
    double last
)
{
    struct Piece
    {
        double first;
        double last;
        Handle(Geom2d_Curve) curve;
    };
    try {
        std::vector<Piece> pieces;
        TopTools_ListIteratorOfListOfShape member;
        for (member.Initialize(edges); member.More(); member.Next()) {
            double pieceFirst = 0.0;
            double pieceLast = 0.0;
            const Handle(Geom2d_Curve) curve = BRep_Tool::CurveOnSurface(
                TopoDS::Edge(member.Value()),
                surface,
                where,
                pieceFirst,
                pieceLast
            );
            if (curve.IsNull()) {
                return {};
            }
            pieces.push_back({pieceFirst, pieceLast, curve});
        }
        std::sort(pieces.begin(), pieces.end(), [](const Piece& a, const Piece& b) {
            return a.first < b.first;
        });
        const double slack = 1e-9 * std::max(1.0, std::abs(last - first));
        if (pieces.empty() || std::abs(pieces.front().first - first) > slack
            || std::abs(pieces.back().last - last) > slack) {
            return {};
        }
        for (std::size_t index = 1; index < pieces.size(); ++index) {
            if (std::abs(pieces[index - 1].last - pieces[index].first) > slack) {
                return {};
            }
        }
        Geom2dConvert_CompCurveToBSplineCurve join(
            new Geom2d_TrimmedCurve(pieces[0].curve, pieces[0].first, pieces[0].last)
        );
        for (std::size_t index = 1; index < pieces.size(); ++index) {
            const Handle(Geom2d_BoundedCurve) next
                = new Geom2d_TrimmedCurve(pieces[index].curve, pieces[index].first, pieces[index].last);
            if (!join.Add(next, 1e-6, Standard_True)) {
                return {};
            }
        }
        const Handle(Geom2d_BSplineCurve) joined = join.BSplineCurve();
        if (joined.IsNull()) {
            return {};
        }
        if (std::abs(joined->FirstParameter() - first) > slack
            || std::abs(joined->LastParameter() - last) > slack) {
            TColStd_Array1OfReal knots(1, joined->NbKnots());
            joined->Knots(knots);
            BSplCLib::Reparametrize(first, last, knots);
            joined->SetKnots(knots);
        }
        return joined;
    }
    catch (const Standard_Failure&) {
        return {};
    }
}

// Whether a fused edge's curves on its faces follow its 3D curve within \a allowed, after
// joining again those that don't (above)
static bool fusedEdgeFollowsItsFaces(
    const TopoDS_Edge& fused,
    const TopTools_ListOfShape& edges,
    double allowed
)
{
    TopLoc_Location location;
    double first = 0.0;
    double last = 0.0;
    const Handle(Geom_Curve) curve = BRep_Tool::Curve(fused, location, first, last);
    if (curve.IsNull()) {
        return true;
    }
    struct OnSurface
    {
        Handle(Geom_Surface) surface;
        TopLoc_Location where;
    };
    auto gapOf = [&](int rank, OnSurface& on) {
        Handle(Geom2d_Curve) curve2d;
        double first2d = 0.0;
        double last2d = 0.0;
        BRep_Tool::CurveOnSurface(fused, curve2d, on.surface, on.where, first2d, last2d, rank);
        if (curve2d.IsNull() || on.surface.IsNull()) {
            return -1.0;
        }
        return curveOnSurfaceGap(
            curve,
            location,
            first,
            last,
            curve2d,
            on.surface,
            on.where,
            first2d,
            last2d
        );
    };
    std::vector<OnSurface> off;
    for (int rank = 1;; ++rank) {
        OnSurface on;
        const double gap = gapOf(rank, on);
        if (gap < 0.0) {
            break;
        }
        if (gap > allowed) {
            off.push_back(on);
        }
    }
    if (off.empty()) {
        return true;
    }
    BRep_Builder builder;
    for (const OnSurface& on : off) {
        const Handle(Geom2d_Curve) joined
            = joinedCurveOnSurface(edges, on.surface, on.where, first, last);
        if (joined.IsNull()) {
            return false;
        }
        builder.UpdateEdge(fused, joined, on.surface, on.where, BRep_Tool::Tolerance(fused));
    }
    for (int rank = 1;; ++rank) {
        OnSurface on;
        const double gap = gapOf(rank, on);
        if (gap < 0.0) {
            break;
        }
        if (gap > allowed) {
            return false;
        }
    }
    return true;
}

// The tolerances of a shape's edges and vertices: read before a fuse of edges, compared and put
// back after one that is undone (the face fix writes into what the fused shape shares with it)
struct Tolerances
{
    TopTools_IndexedMapOfShape shapes;
    std::vector<double> values;

    explicit Tolerances(const TopoDS_Shape& shape)
    {
        TopExp::MapShapes(shape, TopAbs_EDGE, shapes);
        TopExp::MapShapes(shape, TopAbs_VERTEX, shapes);
        values.reserve(shapes.Extent());
        for (int index = 1; index <= shapes.Extent(); ++index) {
            values.push_back(now(shapes(index)));
        }
    }
    static double now(const TopoDS_Shape& shape)
    {
        return shape.ShapeType() == TopAbs_EDGE ? BRep_Tool::Tolerance(TopoDS::Edge(shape))
                                                : BRep_Tool::Tolerance(TopoDS::Vertex(shape));
    }
    bool grew() const
    {
        for (int index = 1; index <= shapes.Extent(); ++index) {
            if (now(shapes(index)) > growthAllowed(values[index - 1])) {
                return true;
            }
        }
        return false;
    }
    void putBack() const
    {
        for (int index = 1; index <= shapes.Extent(); ++index) {
            const TopoDS_Shape& shape = shapes(index);
            if (now(shape) == values[index - 1]) {
                continue;
            }
            if (shape.ShapeType() == TopAbs_EDGE) {
                Handle(BRep_TEdge)::DownCast(shape.TShape())->Tolerance(values[index - 1]);
            }
            else {
                Handle(BRep_TVertex)::DownCast(shape.TShape())->Tolerance(values[index - 1]);
            }
        }
    }
};

FaceTypedBSpline::FaceTypedBSpline()
    : FaceTypedBase(GeomAbs_BSplineSurface)
{}

// B-spline surfaces of one kind: rationality, periodicity, closure and degrees
static bool bsplinesAlike(
    const Handle(Geom_BSplineSurface) & one,
    const Handle(Geom_BSplineSurface) & two
)
{
    if (one->IsURational() != two->IsURational()) {
        return false;
    }
    if (one->IsVRational() != two->IsVRational()) {
        return false;
    }
    if (one->IsUPeriodic() != two->IsUPeriodic()) {
        return false;
    }
    if (one->IsVPeriodic() != two->IsVPeriodic()) {
        return false;
    }
    if (one->IsUClosed() != two->IsUClosed()) {
        return false;
    }
    if (one->IsVClosed() != two->IsVClosed()) {
        return false;
    }
    if (one->UDegree() != two->UDegree()) {
        return false;
    }
    if (one->VDegree() != two->VDegree()) {
        return false;
    }

    return one->NbUPoles() == two->NbUPoles() && one->NbVPoles() == two->NbVPoles()
        && one->NbUKnots() == two->NbUKnots() && one->NbVKnots() == two->NbVKnots();
}

// The same surface: pole for pole, weight for weight, knot for knot. Knots are compared exactly,
// or within PConfusion of the knot range where `tolerant`
static bool bsplinesSame(
    const Handle(Geom_BSplineSurface) & one,
    const Handle(Geom_BSplineSurface) & two,
    bool tolerant
)
{
    if (!bsplinesAlike(one, two)) {
        return false;
    }

    // pole test
    int uPoleCountOne(one->NbUPoles());
    int vPoleCountOne(one->NbVPoles());
    int uPoleCountTwo(two->NbUPoles());
    int vPoleCountTwo(two->NbVPoles());

    if (uPoleCountOne != uPoleCountTwo || vPoleCountOne != vPoleCountTwo) {
        return false;
    }

    TColgp_Array2OfPnt polesOne(1, uPoleCountOne, 1, vPoleCountOne);
    TColgp_Array2OfPnt polesTwo(1, uPoleCountTwo, 1, vPoleCountTwo);
    one->Poles(polesOne);
    two->Poles(polesTwo);

    for (int indexU = 1; indexU <= uPoleCountOne; ++indexU) {
        for (int indexV = 1; indexV <= vPoleCountOne; ++indexV) {
            if (!(polesOne.Value(indexU, indexV)
                      .IsEqual(polesTwo.Value(indexU, indexV), Precision::Confusion()))) {
                return false;
            }
        }
    }

    // weight test: two rational surfaces on the same poles and knots with other weights are
    // other surfaces (ops#1044)
    if (one->IsURational() || one->IsVRational()) {
        TColStd_Array2OfReal weightsOne(1, uPoleCountOne, 1, vPoleCountOne);
        TColStd_Array2OfReal weightsTwo(1, uPoleCountTwo, 1, vPoleCountTwo);
        one->Weights(weightsOne);
        two->Weights(weightsTwo);
        for (int indexU = 1; indexU <= uPoleCountOne; ++indexU) {
            for (int indexV = 1; indexV <= vPoleCountOne; ++indexV) {
                const double w1 = weightsOne.Value(indexU, indexV);
                const double w2 = weightsTwo.Value(indexU, indexV);
                if (std::fabs(w1 - w2) > Precision::PConfusion() * std::max(1.0, std::fabs(w1))) {
                    return false;
                }
            }
        }
    }

    // knot test
    int uKnotCountOne(one->NbUKnots());
    int vKnotCountOne(one->NbVKnots());
    int uKnotCountTwo(two->NbUKnots());
    int vKnotCountTwo(two->NbVKnots());
    if (uKnotCountOne != uKnotCountTwo || vKnotCountOne != vKnotCountTwo) {
        return false;
    }
    TColStd_Array1OfReal uKnotsOne(1, uKnotCountOne);
    TColStd_Array1OfReal vKnotsOne(1, vKnotCountOne);
    TColStd_Array1OfReal uKnotsTwo(1, uKnotCountTwo);
    TColStd_Array1OfReal vKnotsTwo(1, vKnotCountTwo);
    one->UKnots(uKnotsOne);
    one->VKnots(vKnotsOne);
    two->UKnots(uKnotsTwo);
    two->VKnots(vKnotsTwo);
    // exact, or within PConfusion of the knot range for a reversed copy, whose knots are computed
    const double uTolerance = tolerant
        ? Precision::PConfusion() * (uKnotsOne.Value(uKnotCountOne) - uKnotsOne.Value(1))
        : 0.0;
    const double vTolerance = tolerant
        ? Precision::PConfusion() * (vKnotsOne.Value(vKnotCountOne) - vKnotsOne.Value(1))
        : 0.0;
    auto differ = [](double a, double b, double tolerance) {
        return tolerance > 0.0 ? std::fabs(a - b) > tolerance : a != b;
    };
    for (int indexU = 1; indexU <= uKnotCountOne; ++indexU) {
        if (differ(uKnotsOne.Value(indexU), uKnotsTwo.Value(indexU), uTolerance)) {
            return false;
        }
    }
    for (int indexV = 1; indexV <= vKnotCountOne; ++indexV) {
        if (differ(vKnotsOne.Value(indexV), vKnotsTwo.Value(indexV), vTolerance)) {
            return false;
        }
    }

    // Formulas:
    // Periodic:     knots=poles+2*degree-mult(1)+2
    // Non-periodic: knots=poles+degree+1
    auto getUKnotSequenceSize = [](Handle(Geom_BSplineSurface) surface) {
        int uPoleCount(surface->NbUPoles());
        int uDegree(surface->UDegree());
        if (surface->IsUPeriodic()) {
            int uMult1(surface->UMultiplicity(1));
            int size = uPoleCount + 2 * uDegree - uMult1 + 2;
            return size;
        }
        else {
            int size = uPoleCount + uDegree + 1;
            return size;
        }
    };
    auto getVKnotSequenceSize = [](Handle(Geom_BSplineSurface) surface) {
        int vPoleCount(surface->NbVPoles());
        int vDegree(surface->VDegree());
        if (surface->IsVPeriodic()) {
            int vMult1(surface->VMultiplicity(1));
            int size = vPoleCount + 2 * vDegree - vMult1 + 2;
            return size;
        }
        else {
            int size = vPoleCount + vDegree + 1;
            return size;
        }
    };

    // knot sequence.
    int uKnotSequenceOneCount(getUKnotSequenceSize(one));
    int vKnotSequenceOneCount(getVKnotSequenceSize(one));
    int uKnotSequenceTwoCount(getUKnotSequenceSize(two));
    int vKnotSequenceTwoCount(getVKnotSequenceSize(two));
    if (uKnotSequenceOneCount != uKnotSequenceTwoCount
        || vKnotSequenceOneCount != vKnotSequenceTwoCount) {
        return false;
    }
    TColStd_Array1OfReal uKnotSequenceOne(1, uKnotSequenceOneCount);
    TColStd_Array1OfReal vKnotSequenceOne(1, vKnotSequenceOneCount);
    TColStd_Array1OfReal uKnotSequenceTwo(1, uKnotSequenceTwoCount);
    TColStd_Array1OfReal vKnotSequenceTwo(1, vKnotSequenceTwoCount);
    one->UKnotSequence(uKnotSequenceOne);
    one->VKnotSequence(vKnotSequenceOne);
    two->UKnotSequence(uKnotSequenceTwo);
    two->VKnotSequence(vKnotSequenceTwo);
    for (int indexU = 1; indexU <= uKnotSequenceOneCount; ++indexU) {
        if (differ(uKnotSequenceOne.Value(indexU), uKnotSequenceTwo.Value(indexU), uTolerance)) {
            return false;
        }
    }
    for (int indexV = 1; indexV <= vKnotSequenceOneCount; ++indexV) {
        if (differ(vKnotSequenceOne.Value(indexV), vKnotSequenceTwo.Value(indexV), vTolerance)) {
            return false;
        }
    }
    return true;
}

// Which reversal of `two` is `one` (ops#1044): 1 in u, 2 in v, 3 both, 0 none. A wall symmetric
// about a mirror plane (a loft of symmetric sections) is its own mirror image run backwards, so a
// mirror fuse of its halves gives two faces on one surface whose poles are each other's reversed.
// OCCT's own reversal carries weights and multiplicities and shifts a periodic surface's poles
static int bsplineReversal(
    const Handle(Geom_BSplineSurface) & one,
    const Handle(Geom_BSplineSurface) & two
)
{
    if (!bsplinesAlike(one, two)) {
        return 0;
    }
    const bool periodic = one->IsUPeriodic() || one->IsVPeriodic();
    for (int flip = 1; flip <= 3; ++flip) {
        const bool inU = (flip & 1) != 0;
        const bool inV = (flip & 2) != 0;
        // a screen without a copy: a reversal takes a non-periodic surface's first pole to a corner
        if (!periodic
            && !one->Pole(1, 1).IsEqual(
                two->Pole(inU ? two->NbUPoles() : 1, inV ? two->NbVPoles() : 1),
                Precision::Confusion()
            )) {
            continue;
        }
        Handle(Geom_BSplineSurface) reversed = Handle(Geom_BSplineSurface)::DownCast(two->Copy());
        if (inU) {
            reversed->UReverse();
        }
        if (inV) {
            reversed->VReverse();
        }
        if (bsplinesSame(one, reversed, true)) {
            return flip;
        }
    }
    return 0;
}

bool FaceTypedBSpline::isEqual(const TopoDS_Face& faceOne, const TopoDS_Face& faceTwo) const
{
    try {
        Handle(Geom_BSplineSurface)
            surfaceOne = Handle(Geom_BSplineSurface)::DownCast(BRep_Tool::Surface(faceOne));
        Handle(Geom_BSplineSurface)
            surfaceTwo = Handle(Geom_BSplineSurface)::DownCast(BRep_Tool::Surface(faceTwo));

        if (surfaceOne.IsNull() || surfaceTwo.IsNull()) {
            return false;
        }
        return bsplinesSame(surfaceOne, surfaceTwo, false)
            || bsplineReversal(surfaceOne, surfaceTwo) != 0;
    }
    catch (Standard_Failure& e) {
        std::ostringstream stream;
        if (e.GetMessageString()) {
            stream << "FaceTypedBSpline::isEqual: OCC Error: " << e.GetMessageString() << std::endl;
        }
        else {
            stream << "FaceTypedBSpline::isEqual: Unknown OCC Error" << std::endl;
        }
        Base::Console().message(stream.str().c_str());
    }
    catch (...) {
        std::ostringstream stream;
        stream << "FaceTypedBSpline::isEqual: Unknown Error" << std::endl;
        Base::Console().message(stream.str().c_str());
    }

    return false;
}

GeomAbs_SurfaceType FaceTypedBSpline::getType() const
{
    return GeomAbs_BSplineSurface;
}

TopoDS_Face FaceTypedBSpline::buildFace(const FaceVectorType& faces) const
{
    // A group with a member on the first one's surface run backwards (ops#1044) is built with the
    // guards of buildRevolvedFace(); a group of index-equal faces is built as it always was
    bool reversed = false;
    {
        Handle(Geom_BSplineSurface)
            first = Handle(Geom_BSplineSurface)::DownCast(BRep_Tool::Surface(faces.at(0)));
        for (std::size_t index = 1; !first.IsNull() && index < faces.size(); ++index) {
            Handle(Geom_BSplineSurface)
                other = Handle(Geom_BSplineSurface)::DownCast(BRep_Tool::Surface(faces[index]));
            if (!other.IsNull() && !bsplinesSame(first, other, false)) {
                reversed = true;
                break;
            }
        }
    }
    if (reversed) {
        try {
            std::vector<EdgeVectorType> boundaries;
            boundarySplit(faces, boundaries);
            // every boundary edge in a closed boundary, else the group is left as it is
            EdgeVectorType edges;
            ModelRefine::boundaryEdges(faces, edges);
            std::size_t inBoundaries = 0;
            for (const auto& boundary : boundaries) {
                inBoundaries += boundary.size();
            }
            if (boundaries.empty() || inBoundaries != edges.size()) {
                return {};
            }
            std::vector<TopoDS_Wire> wires;
            for (const auto& boundary : boundaries) {
                BRepLib_MakeWire wireMaker;
                for (const auto& edge : boundary) {
                    wireMaker.Add(edge);
                }
                if (wireMaker.Error() != BRepLib_WireDone) {
                    return {};
                }
                wires.push_back(wireMaker.Wire());
            }
            std::sort(wires.begin(), wires.end(), ModelRefine::WireSort());
            Handle(Geom_BSplineSurface) surface = copyOfSurface(
                Handle(Geom_BSplineSurface)::DownCast(BRep_Tool::Surface(faces.at(0)))
            );
            if (surface.IsNull()) {
                return {};
            }
            BRepBuilderAPI_MakeFace faceMaker(surface, wires.front());
            if (!faceMaker.IsDone()) {
                return {};
            }
            for (std::size_t index = 1; index < wires.size(); ++index) {
                faceMaker.Add(wires[index]);
                if (!faceMaker.IsDone()) {
                    return {};
                }
            }
            ShapeFix_Face faceFixer(faceMaker.Face());
            faceFixer.SetContext(new ShapeBuild_ReShape());
            faceFixer.Perform();
            if (faceFixer.Status(ShapeExtend_FAIL)) {
                return {};
            }
            faceFixer.FixOrientation();
            faceFixer.Perform();
            if (faceFixer.Status(ShapeExtend_FAIL)) {
                return {};
            }
            const TopoDS_Face face = faceFixer.Face();
            if (face.IsNull() || !BRepCheck_Analyzer(face).IsValid() || !coversGroup(faces, face)) {
                return {};
            }
            return face;
        }
        catch (Standard_Failure&) {
            return {};
        }
    }

    std::vector<TopoDS_Wire> wires;

    std::vector<EdgeVectorType> splitEdges;
    this->boundarySplit(faces, splitEdges);
    if (splitEdges.empty()) {
        return {};
    }
    std::vector<EdgeVectorType>::iterator splitIt;
    for (splitIt = splitEdges.begin(); splitIt != splitEdges.end(); ++splitIt) {
        BRepLib_MakeWire wireMaker;
        EdgeVectorType::iterator it;
        for (it = (*splitIt).begin(); it != (*splitIt).end(); ++it) {
            wireMaker.Add(*it);
        }
        TopoDS_Wire currentWire = wireMaker.Wire();
        wires.push_back(currentWire);
    }

    std::sort(wires.begin(), wires.end(), ModelRefine::WireSort());

    // make face from surface and outer wire.
    Handle(Geom_BSplineSurface) surface = copyOfSurface(
        Handle(Geom_BSplineSurface)::DownCast(BRep_Tool::Surface(faces.at(0)))
    );
    if (!surface) {
        return {};
    }
    std::vector<TopoDS_Wire>::iterator wireIt;
    wireIt = wires.begin();
    BRepBuilderAPI_MakeFace faceMaker(surface, *wireIt);
    if (!faceMaker.IsDone()) {
        return {};
    }

    // add additional boundaries.
    for (wireIt++; wireIt != wires.end(); ++wireIt) {
        faceMaker.Add(*wireIt);
        if (!faceMaker.IsDone()) {
            return {};
        }
    }

    // fix newly constructed face. Orientation doesn't seem to get fixed the first call.
    ShapeFix_Face faceFixer(faceMaker.Face());
    faceFixer.SetContext(new ShapeBuild_ReShape());
    faceFixer.Perform();
    if (faceFixer.Status(ShapeExtend_FAIL)) {
        return {};
    }
    faceFixer.FixOrientation();
    faceFixer.Perform();
    if (faceFixer.Status(ShapeExtend_FAIL)) {
        return {};
    }

    return faceFixer.Face();
}

FaceTypedBSpline& ModelRefine::getBSplineObject()
{
    static FaceTypedBSpline object;
    return object;
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////

FaceUniter::FaceUniter(const TopoDS_Shell& shellIn)
    : modifiedSignal(false)
{
    workShell = shellIn;
}

bool FaceUniter::process()
{
    if (workShell.IsNull()) {
        return false;
    }
    modifiedShapes.clear();
    deletedShapes.clear();
    typeObjects.push_back(&getPlaneObject());
    typeObjects.push_back(&getCylinderObject());
    typeObjects.push_back(&getConeObject());
    typeObjects.push_back(&getTorusObject());
    typeObjects.push_back(&getSphereObject());
    typeObjects.push_back(&getBSplineObject());
    // add more face types.

    bool checkFinalShell = false;
    ModelRefine::FaceTypeSplitter splitter;
    splitter.addShell(workShell);
    std::vector<FaceTypedBase*>::iterator typeIt;
    for (typeIt = typeObjects.begin(); typeIt != typeObjects.end(); ++typeIt) {
        splitter.registerType((*typeIt)->getType());
    }
    splitter.split();

    ModelRefine::FaceVectorType facesToRemove;
    ModelRefine::FaceVectorType facesToSew;

    ModelRefine::FaceAdjacencySplitter adjacencySplitter(workShell);

    for (typeIt = typeObjects.begin(); typeIt != typeObjects.end(); ++typeIt) {
        ModelRefine::FaceVectorType typedFaces = splitter.getTypedFaceVector((*typeIt)->getType());
        ModelRefine::FaceEqualitySplitter equalitySplitter;
        equalitySplitter.split(typedFaces, *typeIt);
        for (std::size_t indexEquality(0); indexEquality < equalitySplitter.getGroupCount();
             ++indexEquality) {
            adjacencySplitter.split(equalitySplitter.getGroup(indexEquality));
            //            std::cout << "      adjacency group count: " <<
            //            adjacencySplitter.getGroupCount() << std::endl;
            for (std::size_t adjacentIndex(0); adjacentIndex < adjacencySplitter.getGroupCount();
                 ++adjacentIndex) {
                //                    std::cout << "         face count is: " <<
                //                    adjacencySplitter.getGroup(adjacentIndex).size() << std::endl;
                TopoDS_Face newFace = (*typeIt)->buildFace(adjacencySplitter.getGroup(adjacentIndex));
                if (!newFace.IsNull()) {
                    // the created face should have the same orientation as the input faces
                    const FaceVectorType& faces = adjacencySplitter.getGroup(adjacentIndex);
                    if (!faces.empty() && newFace.Orientation() != faces[0].Orientation()) {
                        checkFinalShell = true;
                    }
                    facesToSew.push_back(newFace);

                    // This reserve is probably not actually an improvement over letting
                    // emplace_back allocate as needed. Leaving the code here for study if someone
                    // wants to measure it. Coverity issue 356645. - chennes, March 2025
                    // if (facesToRemove.capacity() <= facesToRemove.size() +
                    // adjacencySplitter.getGroup(adjacentIndex).size())
                    //    facesToRemove.reserve(facesToRemove.size() +
                    //    adjacencySplitter.getGroup(adjacentIndex).size());

                    FaceVectorType temp = adjacencySplitter.getGroup(adjacentIndex);
                    facesToRemove.insert(facesToRemove.end(), temp.begin(), temp.end());
                    // the first shape will be marked as modified, i.e. replaced by newFace, all
                    // others are marked as deleted jrheinlaender: IMHO this is not correct because
                    // references to the deleted faces will be broken, whereas they should be
                    // replaced by references to the new face. To achieve this all shapes should be
                    // marked as modified, producing one single new face. This is the inverse
                    // behaviour to faces that are split e.g. by a boolean cut, where one old shape
                    // is marked as modified, producing multiple new shapes
                    if (!temp.empty()) {
                        for (const auto& f : temp) {
                            modifiedShapes.emplace_back(f, newFace);
                        }
                    }
                }
            }
        }
    }
    if (!facesToSew.empty()) {
        modifiedSignal = true;
        workShell = ModelRefine::removeFaces(workShell, facesToRemove);
        TopExp_Explorer xp;
        bool emptyShell = true;
        for (xp.Init(workShell, TopAbs_FACE); xp.More(); xp.Next()) {
            emptyShell = false;
            break;
        }

        if (!emptyShell || facesToSew.size() > 1) {
            BRepBuilderAPI_Sewing sew;
            sew.Add(workShell);
            FaceVectorType::iterator sewIt;
            for (sewIt = facesToSew.begin(); sewIt != facesToSew.end(); ++sewIt) {
                sew.Add(*sewIt);
            }
            sew.Perform();

            // update the list of modifications
            for (auto& it : modifiedShapes) {
                if (sew.IsModified(it.second)) {
                    it.second = sew.Modified(it.second);

                    // TODO: uncomment in the V2 algorithm PR
                    // if (this->myTopoShape.getHistoryAlgorithm() == App::HistoryAlgorithm::V1) {
                    break;
                    // }
                }
            }

            TopExp_Explorer workShellExplorer;
            std::vector<TopAbs_ShapeEnum> types = {TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX};

            // track any modifications created by the reShape operation in the sewer
            for (TopAbs_ShapeEnum& type : types) {
                workShellExplorer.Init(workShell, type);

                for (; workShellExplorer.More(); workShellExplorer.Next()) {
                    const TopoDS_Shape& workShellSubShape = workShellExplorer.Value();

                    if (sew.IsModifiedSubShape(workShellSubShape)) {
                        // we add a modified shape entry even if `workShellSubShape` is already
                        // present as a key for extra info to give the topological naming method.
                        modifiedShapes.emplace_back(
                            workShellSubShape,
                            sew.ModifiedSubShape(workShellSubShape)
                        );
                    }
                }
            }

            try {
                // Sewing hands back a face's INTERNAL vertex (one on none of its edges: a
                // revolved thread cap crossing the wall, rehearsal 5 rb43 at FSLC #31) as a free
                // vertex beside the shell, in a compound. That compound is the shell, and its merge
                // stands; the loose vertex is left out. A compound with anything else (two shells,
                // a free face or edge) stays a failure
                TopoDS_Shape sewed = sew.SewedShape();
                if (!sewed.IsNull() && sewed.ShapeType() == TopAbs_COMPOUND) {
                    TopoDS_Shape shell;
                    int shells = 0;
                    bool others = false;
                    for (TopoDS_Iterator member(sewed); member.More(); member.Next()) {
                        if (member.Value().ShapeType() == TopAbs_SHELL) {
                            ++shells;
                            shell = member.Value();
                        }
                        else if (member.Value().ShapeType() != TopAbs_VERTEX) {
                            others = true;
                        }
                    }
                    if (shells == 1 && !others) {
                        sewed = shell;
                    }
                }
                workShell = TopoDS::Shell(sewed);
            }
            catch (Standard_Failure&) {
                return false;
            }
        }
        else {
            // workShell has no more faces and we add exactly one face
            BRep_Builder builder;
            builder.MakeShell(workShell);
            FaceVectorType::iterator sewIt;
            for (sewIt = facesToSew.begin(); sewIt != facesToSew.end(); ++sewIt) {
                builder.Add(workShell, *sewIt);
            }
        }

        TopTools_IndexedMapOfShape map;
// TODO: change this version after occ fix. Freecad Mantis 1450
#if OCC_VERSION_HEX <= 0x7fffff
        collectConicEdges(workShell, map);
#endif
        collectSeamEdges(workShell, map);
        // The fuse, checked (above, "The fuse of edges, checked"): run again without the edges
        // whose fused edge fails, until none does
        const Tolerances before(workShell);
        std::unique_ptr<BRepLib_FuseEdges> fuser;
        TopTools_DataMapIteratorOfDataMapOfShapeShape mapIt;
        while (true) {
            fuser = std::make_unique<BRepLib_FuseEdges>(workShell);
            fuser->AvoidEdges(map);
            TopTools_DataMapOfIntegerListOfShape fusedEdges;
            TopTools_DataMapOfIntegerShape resultEdges;
            fuser->Edges(fusedEdges);
            fuser->ResultEdges(resultEdges);
            const int avoided = map.Extent();
            auto avoid = [&map](const TopTools_ListOfShape& edges) {
                TopTools_ListIteratorOfListOfShape member;
                for (member.Initialize(edges); member.More(); member.Next()) {
                    map.Add(member.Value());
                }
            };
            auto inputTolerance = [](const TopTools_ListOfShape& edges) {
                double tolerance = 0.0;
                TopTools_ListIteratorOfListOfShape member;
                for (member.Initialize(edges); member.More(); member.Next()) {
                    tolerance = std::max(tolerance, BRep_Tool::Tolerance(TopoDS::Edge(member.Value())));
                }
                return tolerance;
            };
            // Before the substitution and the face fix: each fused edge's curves on its faces
            TopTools_DataMapIteratorOfDataMapOfIntegerListOfShape group;
            for (group.Initialize(fusedEdges); group.More(); group.Next()) {
                if (resultEdges.IsBound(group.Key())
                    && !fusedEdgeFollowsItsFaces(
                        TopoDS::Edge(resultEdges(group.Key())),
                        group.Value(),
                        growthAllowed(inputTolerance(group.Value()))
                    )) {
                    avoid(group.Value());
                }
            }
            if (map.Extent() != avoided) {
                continue;
            }
            TopTools_DataMapOfShapeShape fixedFaces;
            fuser->Faces(fixedFaces);
            for (mapIt.Initialize(fixedFaces); mapIt.More(); mapIt.Next()) {
                ShapeFix_Face faceFixer(TopoDS::Face(mapIt.Value()));
                faceFixer.Perform();
            }
            // After them: no tolerance grew, of a fused edge or of anything the shape had
            bool grew = false;
            for (group.Initialize(fusedEdges); group.More(); group.Next()) {
                if (resultEdges.IsBound(group.Key())
                    && BRep_Tool::Tolerance(TopoDS::Edge(resultEdges(group.Key())))
                        > growthAllowed(inputTolerance(group.Value()))) {
                    avoid(group.Value());
                    grew = true;
                }
            }
            if (!grew && before.grew()) {
                // not one fused edge's own: none of this fuse is kept
                for (group.Initialize(fusedEdges); group.More(); group.Next()) {
                    avoid(group.Value());
                }
                grew = true;
            }
            if (!grew || map.Extent() == avoided) {
                break;
            }
            before.putBack();
        }
        BRepLib_FuseEdges& edgeFuse = *fuser;
        TopTools_DataMapOfShapeShape affectedFaces;
        edgeFuse.Faces(affectedFaces);
        workShell = TopoDS::Shell(edgeFuse.Shape());

        // A difference of orientation between original and fused faces was previously detected
        if (checkFinalShell) {
            ShapeAnalysis_Shell check;
            check.LoadShells(workShell);
            if (!check.HasFreeEdges()) {
                // the shell is a solid, make sure that volume is positive. OCCT's default
                // integration can give a long curved B-spline face's solid the wrong sign
                // (ops#414)
                if (Part::MassProperties::volume(workShell) < 0) {
                    workShell = TopoDS::Shell(workShell.Reversed());
                }
            }
        }
        // update the list of modifications
        TopTools_DataMapOfShapeShape faceMap;
        edgeFuse.Faces(faceMap);
        for (mapIt.Initialize(faceMap); mapIt.More(); mapIt.Next()) {
            bool isModifiedShape = false;
            for (auto& it : modifiedShapes) {
                if (mapIt.Key().IsSame(it.second)) {
                    // Note: IsEqual() for some reason does not work
                    it.second = mapIt.Value();
                    isModifiedShape = true;
                }
            }
            if (!isModifiedShape) {
                // Catch faces that were not united but whose boundary was changed (probably because
                // several adjacent faces were united)
                // See https://sourceforge.net/apps/mantisbt/free-cad/view.php?id=873
                modifiedShapes.emplace_back(mapIt.Key(), mapIt.Value());
            }
        }
        // Handle edges that were fused. See
        // https://sourceforge.net/apps/mantisbt/free-cad/view.php?id=873
        TopTools_DataMapOfIntegerListOfShape oldEdges;
        TopTools_DataMapOfIntegerShape newEdges;
        edgeFuse.Edges(oldEdges);
        edgeFuse.ResultEdges(newEdges);
        TopTools_DataMapIteratorOfDataMapOfIntegerListOfShape edgeMapIt;
        for (edgeMapIt.Initialize(oldEdges); edgeMapIt.More(); edgeMapIt.Next()) {
            const TopTools_ListOfShape& edges = edgeMapIt.Value();
            int idx = edgeMapIt.Key();
            TopTools_ListIteratorOfListOfShape edgeIt;
            for (edgeIt.Initialize(edges); edgeIt.More(); edgeIt.Next()) {
                if (newEdges.IsBound(idx)) {
                    modifiedShapes.emplace_back(edgeIt.Value(), newEdges(idx));
                }
            }
            // TODO: Handle vertices that have disappeared in the fusion of the edges
        }
    }
    return true;
}

void FaceUniter::fixOrientation(const TopoDS_Shell& shell)
{
    if (shell.Orientation() != workShell.Orientation()) {
        workShell.Reverse();
    }
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////

// BRepBuilderAPI_RefineModel implement a way to log all modifications on the faces

namespace
{
// Adds the members of `shape` of the given type, recursing into its sub-compounds only
void addFreeMembers(
    const TopoDS_Shape& shape,
    TopAbs_ShapeEnum type,
    BRep_Builder& builder,
    TopoDS_Compound& comp
)
{
    for (TopoDS_Iterator it(shape); it.More(); it.Next()) {
        const TopoDS_Shape& member = it.Value();
        if (member.IsNull()) {
            continue;
        }
        if (member.ShapeType() == TopAbs_COMPOUND) {
            addFreeMembers(member, type, builder, comp);
        }
        else if (member.ShapeType() == type) {
            builder.Add(comp, member);
        }
    }
}
}  // namespace

Part::BRepBuilderAPI_RefineModel::BRepBuilderAPI_RefineModel(const TopoDS_Shape& shape)
{
    myShape = shape;
    Build();
}

#if OCC_VERSION_HEX >= 0x070600
void Part::BRepBuilderAPI_RefineModel::Build(const Message_ProgressRange&)
#else
void Part::BRepBuilderAPI_RefineModel::Build()
#endif
{
    if (myShape.IsNull()) {
        throw Standard_Failure("Cannot remove splitter from empty shape");
    }

    if (myShape.ShapeType() == TopAbs_SOLID) {
        const TopoDS_Solid& solid = TopoDS::Solid(myShape);
        BRepBuilderAPI_MakeSolid mkSolid;
        TopExp_Explorer it;
        for (it.Init(solid, TopAbs_SHELL); it.More(); it.Next()) {
            const TopoDS_Shell& currentShell = TopoDS::Shell(it.Current());
            ModelRefine::FaceUniter uniter(currentShell);
            if (uniter.process()) {
                if (uniter.isModified()) {
                    const TopoDS_Shell& newShell = uniter.getShell();
                    mkSolid.Add(newShell);
                    LogModifications(uniter);
                }
                else {
                    mkSolid.Add(currentShell);
                }
            }
            else {
                throw Standard_Failure("Removing splitter failed");
            }
        }
        myShape = mkSolid.Solid();
    }
    else if (myShape.ShapeType() == TopAbs_SHELL) {
        const TopoDS_Shell& shell = TopoDS::Shell(myShape);
        ModelRefine::FaceUniter uniter(shell);
        if (uniter.process()) {
            // TODO: Why not check for uniter.isModified()?
            myShape = uniter.getShell();
            LogModifications(uniter);
        }
        else {
            throw Standard_Failure("Removing splitter failed");
        }
    }
    else if (myShape.ShapeType() == TopAbs_COMPOUND) {
        BRep_Builder builder;
        TopoDS_Compound comp;
        builder.MakeCompound(comp);

        TopExp_Explorer xp;
        // solids
        for (xp.Init(myShape, TopAbs_SOLID); xp.More(); xp.Next()) {
            const TopoDS_Solid& solid = TopoDS::Solid(xp.Current());
            BRepTools_ReShape reshape;
            TopExp_Explorer it;
            int countShells = 0;
            for (it.Init(solid, TopAbs_SHELL); it.More(); it.Next()) {
                countShells++;
                const TopoDS_Shell& currentShell = TopoDS::Shell(it.Current());
                ModelRefine::FaceUniter uniter(currentShell);
                if (uniter.process()) {
                    if (uniter.isModified()) {
                        if (countShells > 1) {
                            uniter.fixOrientation(currentShell);
                        }
                        const TopoDS_Shell& newShell = uniter.getShell();
                        reshape.Replace(currentShell, newShell);
                        LogModifications(uniter);
                    }
                }
                else {
                    // kept as it was; the caller may try another way (makeElementRefine)
                    mySkippedShells = true;
                }
            }
            builder.Add(comp, reshape.Apply(solid));
        }
        // free shells
        for (xp.Init(myShape, TopAbs_SHELL, TopAbs_SOLID); xp.More(); xp.Next()) {
            const TopoDS_Shell& shell = TopoDS::Shell(xp.Current());
            ModelRefine::FaceUniter uniter(shell);
            if (uniter.process()) {
                builder.Add(comp, uniter.getShell());
                LogModifications(uniter);
            }
            else {
                // kept as it was (it used to be dropped from the result)
                builder.Add(comp, shell);
                mySkippedShells = true;
            }
        }
        // the rest: the compound's own faces, wires, edges and vertices, in that order. Only the
        // compound's members (its sub-compounds' too), not an explorer's "not under an X": a
        // solid's or a face's INTERNAL vertex is under no edge, and was added again as a free
        // vertex beside its solid (a thread's vertex touching the face it was fused onto,
        // FSLC #30), which made every later fuse with the body "not allowed" (ops#640)
        for (TopAbs_ShapeEnum type : {TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE, TopAbs_VERTEX}) {
            addFreeMembers(myShape, type, builder, comp);
        }

        myShape = comp;
    }

    Done();
}

void Part::BRepBuilderAPI_RefineModel::LogModifications(const ModelRefine::FaceUniter& uniter)
{
    const std::vector<ShapePairType>& modShapes = uniter.getModifiedShapes();
    for (const auto& it : modShapes) {
        TopTools_ListOfShape list;
        list.Append(it.second);
        myModified.Bind(it.first, list);
    }
    const ShapeVectorType& delShapes = uniter.getDeletedShapes();
    for (const auto& it : delShapes) {
        myDeleted.Append(it);
    }
}

const TopTools_ListOfShape& Part::BRepBuilderAPI_RefineModel::Modified(const TopoDS_Shape& S)
{
    if (myModified.IsBound(S)) {
        return myModified.Find(S);
    }
    else {
        return myEmptyList;
    }
}

Standard_Boolean Part::BRepBuilderAPI_RefineModel::IsDeleted(const TopoDS_Shape& S)
{
    TopTools_ListIteratorOfListOfShape it;
    for (it.Initialize(myDeleted); it.More(); it.Next()) {
        if (it.Value().IsSame(S)) {
            return Standard_True;
        }
    }

    return Standard_False;
}
