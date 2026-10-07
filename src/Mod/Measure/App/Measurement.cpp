// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2013 Luke Parry <l.parry@warwick.ac.uk>                 *
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
#include <chrono>
#include <cmath>

#include <Bnd_Box.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepBndLib.hxx>
#include <BRepExtrema_ExtPC.hxx>
#include <BRepExtrema_ExtPF.hxx>
#include <BRepTools.hxx>
#include <BRepTopAdaptor_FClass2d.hxx>
#include <GCPnts_TangentialDeflection.hxx>
#include <gp_Pnt2d.hxx>
#include <Message_ProgressIndicator.hxx>
#include <Message_ProgressScope.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopoDS_Compound.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepGProp_Domain.hxx>
#include <BRepGProp_Face.hxx>
#include <BRepGProp_Vinert.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <gp_Pln.hxx>
#include <gp_Circ.hxx>
#include <gp_Torus.hxx>
#include <gp_Cylinder.hxx>
#include <gp_Sphere.hxx>
#include <gp_Lin.hxx>
#include <GProp_GProps.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shape.hxx>
#include <TopExp_Explorer.hxx>


#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Tools.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/TopoShape.h>

#include "Measurement.h"
#include "MeasurementPy.h"
#include "ShapeFinder.h"


using namespace Measure;
using namespace Base;
using namespace Part;

TYPESYSTEM_SOURCE(Measure::Measurement, Base::BaseClass)

Measurement::Measurement()
{
    measureType = MeasureType::Invalid;
    References3D.setScope(App::LinkScope::Global);
}

Measurement::~Measurement() = default;

void Measurement::clear()
{
    std::vector<App::DocumentObject*> Objects;
    std::vector<std::string> SubElements;
    References3D.setValues(Objects, SubElements);
    measureType = MeasureType::Invalid;
}

bool Measurement::has3DReferences()
{
    return (References3D.getSize() > 0);
}

// add a 3D reference (obj+sub) to end of list
int Measurement::addReference3D(App::DocumentObject* obj, const std::string& subName)
{
    return addReference3D(obj, subName.c_str());
}

/// add a 3D reference (obj+sub) to end of list
int Measurement::addReference3D(App::DocumentObject* obj, const char* subName)
{
    std::vector<App::DocumentObject*> objects = References3D.getValues();
    std::vector<std::string> subElements = References3D.getSubValues();

    objects.push_back(obj);
    subElements.emplace_back(subName);

    References3D.setValues(objects, subElements);

    measureType = findType();
    return References3D.getSize();
}

MeasureType Measurement::findType()
{
    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subElements = References3D.getSubValues();

    std::vector<App::DocumentObject*>::const_iterator obj = objects.begin();
    std::vector<std::string>::const_iterator subEl = subElements.begin();

    MeasureType mode;

    int verts = 0;
    int edges = 0;
    int lines = 0;
    int circles = 0;
    int circleArcs = 0;
    int faces = 0;
    int planes = 0;
    int cylinders = 0;
    int cylinderSections = 0;
    int cones = 0;
    int torus = 0;
    int spheres = 0;
    int discs = 0;
    int vols = 0;
    int other = 0;

    for (; obj != objects.end(); ++obj, ++subEl) {
        TopoDS_Shape refSubShape;
        try {
            refSubShape = Part::Feature::getShape(
                *obj,
                Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                    | Part::ShapeOption::Transform,
                (*subEl).c_str()
            );

            if (refSubShape.IsNull()) {
                return MeasureType::Invalid;
            }
        }
        catch (Standard_Failure& e) {
            std::stringstream errorMsg;

            errorMsg << "Measurement - getType - " << e.GetMessageString() << std::endl;
            throw Base::CADKernelError(e.GetMessageString());
        }

        switch (refSubShape.ShapeType()) {
            case TopAbs_VERTEX: {
                verts++;
            } break;
            case TopAbs_EDGE: {
                edges++;
                TopoDS_Edge edge = TopoDS::Edge(refSubShape);
                BRepAdaptor_Curve sf(edge);

                if (sf.GetType() == GeomAbs_Line) {
                    lines++;
                }
                else if (sf.GetType() == GeomAbs_Circle) {
                    if (sf.IsClosed()) {
                        circles++;
                    }
                    else {
                        circleArcs++;
                    }
                }
            } break;
            case TopAbs_FACE: {
                faces++;
                TopoDS_Face face = TopoDS::Face(refSubShape);
                BRepAdaptor_Surface sf(face);

                if (sf.GetType() == GeomAbs_Plane) {
                    TopExp_Explorer edges(face, TopAbs_EDGE);
                    if (!edges.More()) {
                        planes++;
                        break;
                    }
                    TopoDS_Edge edge = TopoDS::Edge(edges.Current());
                    edges.Next();
                    if (edges.More()) {
                        planes++;
                        break;
                    }
                    BRepAdaptor_Curve adapt(edge);
                    if (adapt.GetType() != GeomAbs_Circle) {
                        planes++;
                        break;
                    }

                    discs++;
                }
                else if (sf.GetType() == GeomAbs_Cylinder) {
                    if (sf.IsUClosed() || sf.IsVClosed()) {
                        cylinders++;
                    }
                    else {
                        cylinderSections++;
                    }
                }
                else if (sf.GetType() == GeomAbs_Sphere) {
                    spheres++;
                }
                else if (sf.GetType() == GeomAbs_Cone) {
                    cones++;
                }
                else if (sf.GetType() == GeomAbs_Torus) {
                    torus++;
                }
            } break;
            case TopAbs_SOLID: {
                vols++;
            } break;
            default:
                other++;
                break;
        }
    }

    if (other > 0) {
        mode = MeasureType::Invalid;
    }
    else if (vols > 0) {
        if (verts > 0 || edges > 0 || faces > 0) {
            mode = MeasureType::Invalid;
        }
        else {
            mode = MeasureType::Volumes;
        }
    }
    else if (faces > 0) {
        if (verts > 0 || edges > 0) {
            if (faces == 1 && (cylinders + cylinderSections) == 1 && verts == 1 && edges == 0) {
                mode = MeasureType::PointToCylinder;
            }
            else if (faces == 1 && verts == 1) {
                mode = MeasureType::PointToSurface;
            }
            else if (
                faces == 1 && (cylinders + cylinderSections) == 1 && (circles + circleArcs) == 1
                && edges == 1
            ) {
                mode = MeasureType::CircleToCylinder;
            }
            else if (faces == 1 && (circles + circleArcs) == 1 && edges == 1) {
                mode = MeasureType::CircleToSurface;
            }
            else {
                mode = MeasureType::Invalid;
            }
        }
        else {
            if (planes == 1 && faces == 1) {
                mode = MeasureType::Plane;
            }
            else if (planes == 2 && faces == 2) {
                if (planesAreParallel()) {
                    mode = MeasureType::TwoPlanes;
                }
                else {
                    mode = MeasureType::Surfaces;
                }
            }
            else if (cylinders == 1 && faces == 1) {
                mode = MeasureType::Cylinder;
            }
            else if (cylinderSections == 1 && faces == 1) {
                mode = MeasureType::CylinderSection;
            }
            else if ((cylinders + cylinderSections) == 2 && faces == 2) {
                mode = MeasureType::TwoCylinders;
            }
            else if (cones == 1 && faces == 1) {
                mode = MeasureType::Cone;
            }
            else if (spheres == 1 && faces == 1) {
                mode = MeasureType::Sphere;
            }
            else if (torus == 1 && faces == 1) {
                mode = MeasureType::Torus;
            }
            else if (discs == 1 && faces == 1) {
                mode = MeasureType::Disc;
            }
            else {
                mode = MeasureType::Surfaces;
            }
        }
    }
    else if (edges > 0) {
        if (verts > 0) {
            if (verts > 1) {
                mode = MeasureType::Invalid;
            }
            else if ((circles + circleArcs) == 1) {
                mode = MeasureType::PointToCircle;
            }
            else {
                mode = MeasureType::PointToEdge;
            }
        }
        else if (lines == 1 && edges == 1) {
            mode = MeasureType::Line;
        }
        else if (lines == 2 && edges == 2) {
            if (linesAreParallel()) {
                mode = MeasureType::TwoParallelLines;
            }
            else {
                mode = MeasureType::TwoLines;
            }
        }
        else if (circles == 1 && edges == 1) {
            mode = MeasureType::Circle;
        }
        else if (circleArcs == 1 && edges == 1) {
            mode = MeasureType::CircleArc;
        }
        else if ((circles + circleArcs) == 2 && edges == 2) {
            mode = MeasureType::TwoCircles;
        }
        else if ((circles + circleArcs == 1) && edges == 2) {
            mode = MeasureType::CircleToEdge;
        }
        else {
            mode = MeasureType::Edges;
        }
    }
    else if (verts > 0) {
        if (verts == 2) {
            mode = MeasureType::PointToPoint;
        }
        else {
            mode = MeasureType::Points;
        }
    }
    else {
        mode = MeasureType::Invalid;
    }

    return mode;
}

MeasureType Measurement::getType()
{
    return measureType;
}

TopoDS_Shape Measurement::getShape(App::DocumentObject* obj, const char* subName, TopAbs_ShapeEnum hint) const
{
    (void)hint;
    return Part::Feature::getShape(
        obj,
        Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
            | Part::ShapeOption::Transform,
        subName
    );
}


// TODO:: add lengthX, lengthY (and lengthZ??) support
//  Methods for distances (edge length, two points, edge and a point
double Measurement::length() const
{
    double result = 0.0;
    int numRefs = References3D.getSize();
    if (numRefs == 0) {
        Base::Console().error("Measurement::length - No 3D references available\n");
    }
    else if (measureType == MeasureType::Invalid) {
        Base::Console().error("Measurement::length - measureType is Invalid\n");
    }
    else {
        const std::vector<App::DocumentObject*>& objects = References3D.getValues();
        const std::vector<std::string>& subElements = References3D.getSubValues();

        if (measureType == MeasureType::Points || measureType == MeasureType::PointToPoint
            || measureType == MeasureType::PointToEdge || measureType == MeasureType::PointToSurface
            || measureType == MeasureType::PointToCircle
            || measureType == MeasureType::PointToCylinder) {

            Base::Vector3d diff = this->delta();
            result = diff.Length();
        }
        else if (
            measureType == MeasureType::Edges || measureType == MeasureType::Line
            || measureType == MeasureType::TwoLines || measureType == MeasureType::Circle
            || measureType == MeasureType::CircleArc || measureType == MeasureType::TwoCircles
            || measureType == MeasureType::CircleToEdge
        ) {

            // Iterate through edges and calculate each length
            std::vector<App::DocumentObject*>::const_iterator obj = objects.begin();
            std::vector<std::string>::const_iterator subEl = subElements.begin();

            for (; obj != objects.end(); ++obj, ++subEl) {

                //  Get the length of one edge
                TopoDS_Shape shape = getShape(*obj, (*subEl).c_str(), TopAbs_EDGE);
                if (shape.IsNull() || shape.Infinite()) {
                    continue;
                }
                const TopoDS_Edge& edge = TopoDS::Edge(shape);
                BRepAdaptor_Curve curve(edge);

                switch (curve.GetType()) {
                    case GeomAbs_Line: {
                        gp_Pnt P1 = curve.Value(curve.FirstParameter());
                        gp_Pnt P2 = curve.Value(curve.LastParameter());
                        gp_XYZ diff = P2.XYZ() - P1.XYZ();
                        result += diff.Modulus();
                        break;
                    }
                    case GeomAbs_Circle: {
                        double u = curve.FirstParameter();
                        double v = curve.LastParameter();
                        double radius = curve.Circle().Radius();
                        if (u > v) {  // if arc is reversed
                            std::swap(u, v);
                        }

                        double range = v - u;
                        result += radius * range;
                        break;
                    }
                    case GeomAbs_Ellipse:
                    case GeomAbs_BSplineCurve:
                    case GeomAbs_Hyperbola:
                    case GeomAbs_Parabola:
                    case GeomAbs_BezierCurve: {
                        result += GCPnts_AbscissaPoint::Length(curve);
                        break;
                    }
                    default: {
                        throw Base::RuntimeError(
                            "Measurement - length - Curve type not currently handled"
                        );
                    }
                }
            }
        }
    }
    return result;
}

double Measurement::lineLineDistance() const
{
    // We don't use delta() because BRepExtrema_DistShapeShape return minimum length between line
    // segment. Here we get the nominal distance between the infinite lines.
    double distance = 0.0;

    if (measureType != MeasureType::TwoParallelLines || References3D.getSize() != 2) {
        return distance;
    }

    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subElements = References3D.getSubValues();

    // Get the first line
    TopoDS_Shape shape1 = getShape(objects[0], subElements[0].c_str(), TopAbs_EDGE);
    const TopoDS_Edge& edge1 = TopoDS::Edge(shape1);
    BRepAdaptor_Curve curve1(edge1);

    // Get the second line
    TopoDS_Shape shape2 = getShape(objects[1], subElements[1].c_str(), TopAbs_EDGE);
    const TopoDS_Edge& edge2 = TopoDS::Edge(shape2);
    BRepAdaptor_Curve curve2(edge2);

    if (curve1.GetType() == GeomAbs_Line && curve2.GetType() == GeomAbs_Line) {
        gp_Lin line1 = curve1.Line();
        gp_Lin line2 = curve2.Line();

        gp_Pnt p1 = line1.Location();
        gp_Pnt p2 = line2.Location();

        // Create a vector from a point on line1 to a point on line2
        gp_Vec lineVec(p1, p2);

        // The direction vector of one of the lines
        gp_Dir lineDir = line1.Direction();

        // Project lineVec onto lineDir
        gp_Vec parallelComponent = lineVec.Dot(lineDir) * lineDir;

        // Compute the perpendicular component
        gp_Vec perpendicularComponent = lineVec - parallelComponent;

        // Distance is the magnitude of the perpendicular component
        distance = perpendicularComponent.Magnitude();
    }
    else {
        Base::Console().error("Measurement::length - TwoLines measureType requires two lines\n");
    }
    return distance;
}
double Measurement::circleCenterDistance() const
{
    double distance = 0.0;

    if (References3D.getSize() != 2) {
        return distance;
    }

    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subElements = References3D.getSubValues();

    // Get the first circle
    TopoDS_Shape shape1 = getShape(objects[0], subElements[0].c_str());
    TopoDS_Shape shape2 = getShape(objects[1], subElements[1].c_str());

    if (shape1.ShapeType() != TopAbs_EDGE) {
        std::swap(shape1, shape2);
    }

    if (measureType == MeasureType::TwoCircles) {
        const TopoDS_Edge& edge1 = TopoDS::Edge(shape1);
        BRepAdaptor_Curve curve1(edge1);

        const TopoDS_Edge& edge2 = TopoDS::Edge(shape2);
        BRepAdaptor_Curve curve2(edge2);

        if (curve1.GetType() == GeomAbs_Circle && curve2.GetType() == GeomAbs_Circle) {
            gp_Circ circle1 = curve1.Circle();
            gp_Circ circle2 = curve2.Circle();

            distance = circle1.Location().Distance(circle2.Location());
        }
    }
    else if (
        measureType == MeasureType::CircleToEdge || measureType == MeasureType::CircleToSurface
        || measureType == MeasureType::CircleToCylinder
    ) {
        const TopoDS_Edge& edge1 = TopoDS::Edge(shape1);
        BRepAdaptor_Curve curve1(edge1);

        TopoDS_Vertex circleCenter;
        const TopoDS_Shape* otherShape;
        if (curve1.GetType() == GeomAbs_Circle) {
            circleCenter = BRepBuilderAPI_MakeVertex(curve1.Circle().Location());
            otherShape = &shape2;
        }
        else {
            const TopoDS_Edge& edge2 = TopoDS::Edge(shape2);
            BRepAdaptor_Curve curve2(edge2);

            circleCenter = BRepBuilderAPI_MakeVertex(curve2.Circle().Location());
            otherShape = &shape1;
        }

        BRepExtrema_DistShapeShape extrema(circleCenter, *otherShape);

        if (extrema.IsDone()) {
            // Found the nearest point between point and curve
            // NOTE we will assume there is only 1 solution (cyclic topology will create
            // multiple solutions.
            gp_Pnt P1 = extrema.PointOnShape1(1);
            gp_Pnt P2 = extrema.PointOnShape2(1);
            gp_XYZ diff = P2.XYZ() - P1.XYZ();
            distance = Base::Vector3d(diff.X(), diff.Y(), diff.Z()).Length();
        }
    }
    else if (measureType == MeasureType::PointToCircle) {
        const TopoDS_Edge& edge1 = TopoDS::Edge(shape1);
        BRepAdaptor_Curve curve1(edge1);

        TopoDS_Vertex& vert1 = TopoDS::Vertex(shape2);

        gp_Circ circle1 = curve1.Circle();
        gp_Pnt pt = BRep_Tool::Pnt(vert1);

        distance = circle1.Location().Distance(pt);
    }

    return distance;
}
double Measurement::planePlaneDistance() const
{
    if (measureType != MeasureType::TwoPlanes || References3D.getSize() != 2) {
        return 0.0;
    }

    const auto& objects = References3D.getValues();
    const auto& subElements = References3D.getSubValues();

    // Get the first plane
    TopoDS_Shape shape1 = getShape(objects[0], subElements[0].c_str(), TopAbs_FACE);
    const TopoDS_Face& face1 = TopoDS::Face(shape1);
    BRepAdaptor_Surface surface1(face1);
    const gp_Pln& plane1 = surface1.Plane();

    // Get the second plane
    TopoDS_Shape shape2 = getShape(objects[1], subElements[1].c_str(), TopAbs_FACE);
    const TopoDS_Face& face2 = TopoDS::Face(shape2);
    BRepAdaptor_Surface surface2(face2);
    const gp_Pln& plane2 = surface2.Plane();

    // Distance between two parallel planes
    gp_Pnt pointOnPlane1 = plane1.Location();
    gp_Dir normalToPlane1 = plane1.Axis().Direction();

    gp_Pnt pointOnPlane2 = plane2.Location();

    // Create a vector from a point on plane1 to a point on plane2
    gp_Vec vectorBetweenPlanes(pointOnPlane1, pointOnPlane2);

    // Project this vector onto the plane normal
    double distance = Abs(vectorBetweenPlanes.Dot(normalToPlane1));

    return distance;
}
double Measurement::cylinderAxisDistance() const
{
    double distance = 0.0;

    if (References3D.getSize() != 2) {
        return distance;
    }

    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subElements = References3D.getSubValues();

    // Get the first circle
    TopoDS_Shape shape1 = getShape(objects[0], subElements[0].c_str());
    TopoDS_Shape shape2 = getShape(objects[1], subElements[1].c_str());

    if (shape1.ShapeType() != TopAbs_FACE) {
        std::swap(shape1, shape2);
    }

    if (measureType == MeasureType::PointToCylinder) {
        TopoDS_Face face = TopoDS::Face(shape1);
        BRepAdaptor_Surface cylinderFace(face);

        const TopoDS_Vertex& vert1 = TopoDS::Vertex(shape2);
        gp_Pnt pt = BRep_Tool::Pnt(vert1);

        if (cylinderFace.GetType() == GeomAbs_Cylinder) {
            distance = gp_Lin(cylinderFace.Cylinder().Axis()).Distance(pt);
        }
    }
    else if (measureType == MeasureType::TwoCylinders) {
        TopoDS_Face face1 = TopoDS::Face(shape1);
        BRepAdaptor_Surface surface1(face1);

        TopoDS_Face face2 = TopoDS::Face(shape2);
        BRepAdaptor_Surface surface2(face2);

        if (surface1.GetType() == GeomAbs_Cylinder && surface2.GetType() == GeomAbs_Cylinder) {
            distance = gp_Lin(surface1.Cylinder().Axis()).Distance(gp_Lin(surface2.Cylinder().Axis()));
        }
    }
    else if (measureType == MeasureType::CircleToCylinder) {
        TopoDS_Face face1 = TopoDS::Face(shape1);
        BRepAdaptor_Surface surface1(face1);

        TopoDS_Edge edge1 = TopoDS::Edge(shape2);
        BRepAdaptor_Curve curve1(edge1);

        if (surface1.GetType() == GeomAbs_Cylinder && curve1.GetType() == GeomAbs_Circle) {
            distance = gp_Lin(surface1.Cylinder().Axis()).Distance(curve1.Circle().Location());
        }
    }
    return distance;
}

double Measurement::angle(const Base::Vector3d& /*param*/) const
{
    // TODO: do these references arrive as obj+sub pairs or as a struct of obj + [subs]?
    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subElements = References3D.getSubValues();
    int numRefs = objects.size();
    if (numRefs == 0) {
        throw Base::RuntimeError("No references available for angle measurement");
    }
    else if (measureType == MeasureType::Invalid) {
        throw Base::RuntimeError("MeasureType is Invalid for angle measurement");
    }
    else if (measureType == MeasureType::TwoLines) {
        // Only case that is supported is edge to edge
        // The angle between two skew lines is measured by the angle between one line (A)
        // and a line (B) with the direction of the second through a point on the first line.
        // Since we don't know if the directions of the lines point in the same general direction
        // we could get the angle we want or the supplementary angle.
        if (numRefs == 2) {
            TopoDS_Shape shape1 = getShape(objects.at(0), subElements.at(0).c_str(), TopAbs_EDGE);
            TopoDS_Shape shape2 = getShape(objects.at(1), subElements.at(1).c_str(), TopAbs_EDGE);

            BRepAdaptor_Curve curve1(TopoDS::Edge(shape1));
            BRepAdaptor_Curve curve2(TopoDS::Edge(shape2));

            if (curve1.GetType() == GeomAbs_Line && curve2.GetType() == GeomAbs_Line) {

                gp_Pnt pnt1First = curve1.Value(curve1.FirstParameter());
                gp_Dir dir1 = curve1.Line().Direction();
                gp_Dir dir2 = curve2.Line().Direction();
                gp_Dir dir2r = curve2.Line().Direction().Reversed();

                gp_Lin l1 = gp_Lin(pnt1First, dir1);    // (A)
                gp_Lin l2 = gp_Lin(pnt1First, dir2);    // (B)
                gp_Lin l2r = gp_Lin(pnt1First, dir2r);  // (B')
                Standard_Real aRad = l1.Angle(l2);
                double aRadr = l1.Angle(l2r);
                return Base::toDegrees<double>(std::min(aRad, aRadr));
            }
            else {
                throw Base::RuntimeError("Measurement references must both be lines");
            }
        }
        else {
            throw Base::RuntimeError("Can not compute angle measurement - too many references");
        }
    }
    else if (measureType == MeasureType::Points) {
        // NOTE: we are calculating the 3d angle here, not the projected angle
        // ASSUMPTION: the references are in end-apex-end order
        if (numRefs == 3) {
            TopoDS_Shape shape0 = getShape(objects.at(0), subElements.at(0).c_str(), TopAbs_VERTEX);
            TopoDS_Shape shape1 = getShape(objects.at(1), subElements.at(1).c_str(), TopAbs_VERTEX);
            TopoDS_Shape shape2 = getShape(objects.at(1), subElements.at(2).c_str(), TopAbs_VERTEX);
            if (shape0.ShapeType() != TopAbs_VERTEX || shape1.ShapeType() != TopAbs_VERTEX
                || shape2.ShapeType() != TopAbs_VERTEX) {
                throw Base::RuntimeError("Measurement references for 3 point angle are not Vertex");
            }
            gp_Pnt gEnd0 = BRep_Tool::Pnt(TopoDS::Vertex(shape0));
            gp_Pnt gApex = BRep_Tool::Pnt(TopoDS::Vertex(shape1));
            gp_Pnt gEnd1 = BRep_Tool::Pnt(TopoDS::Vertex(shape2));
            gp_Dir gDir0 = gp_Dir(gEnd0.XYZ() - gApex.XYZ());
            gp_Dir gDir1 = gp_Dir(gEnd1.XYZ() - gApex.XYZ());
            gp_Lin line0 = gp_Lin(gEnd0, gDir0);
            gp_Lin line1 = gp_Lin(gEnd1, gDir1);
            double radians = line0.Angle(line1);
            return Base::toDegrees<double>(radians);
        }
    }
    else if (
        measureType == MeasureType::TwoCylinders || measureType == MeasureType::TwoCircles
        || measureType == MeasureType::CircleToCylinder
    ) {
        if (numRefs == 2) {
            TopoDS_Shape shape1 = getShape(objects.at(0), subElements.at(0).c_str(), TopAbs_EDGE);
            TopoDS_Shape shape2 = getShape(objects.at(1), subElements.at(1).c_str(), TopAbs_EDGE);

            gp_Ax1 axis1;
            gp_Ax1 axis2;

            if (measureType == MeasureType::TwoCylinders) {
                BRepAdaptor_Surface surface1(TopoDS::Face(shape1));
                BRepAdaptor_Surface surface2(TopoDS::Face(shape2));

                axis1 = surface1.Cylinder().Axis();
                axis2 = surface2.Cylinder().Axis();
            }
            else if (measureType == MeasureType::TwoCircles) {
                BRepAdaptor_Curve curve1(TopoDS::Edge(shape1));
                BRepAdaptor_Curve curve2(TopoDS::Edge(shape2));

                axis1 = curve1.Circle().Axis();
                axis2 = curve2.Circle().Axis();
            }
            else if (measureType == MeasureType::CircleToCylinder) {
                if (shape1.ShapeType() == TopAbs_FACE) {
                    std::swap(shape1, shape2);
                }
                BRepAdaptor_Curve curve1(TopoDS::Edge(shape1));
                BRepAdaptor_Surface surface2(TopoDS::Face(shape2));

                axis1 = curve1.Circle().Axis();
                axis2 = surface2.Cylinder().Axis();
            }
            double aRad = axis1.Angle(axis2);
            return Base::toDegrees<double>(
                std::min(aRad, std::fmod(aRad + std::numbers::pi, 2.0 * std::numbers::pi))
            );
        }
    }
    throw Base::RuntimeError("Unexpected error for angle measurement");
}

double Measurement::radius() const
{
    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subElements = References3D.getSubValues();

    int numRefs = References3D.getSize();
    if (numRefs == 0) {
        Base::Console().error("Measurement::radius - No 3D references available\n");
    }
    else if (measureType == MeasureType::Circle || measureType == MeasureType::CircleArc) {
        TopoDS_Shape shape = getShape(objects.at(0), subElements.at(0).c_str(), TopAbs_EDGE);
        const TopoDS_Edge& edge = TopoDS::Edge(shape);

        BRepAdaptor_Curve curve(edge);
        if (curve.GetType() == GeomAbs_Circle) {
            return (double)curve.Circle().Radius();
        }
    }
    else if (
        measureType == MeasureType::Cylinder || measureType == MeasureType::CylinderSection
        || measureType == MeasureType::Sphere || measureType == MeasureType::Torus
        || measureType == MeasureType::Disc
    ) {
        TopoDS_Shape shape = getShape(objects.at(0), subElements.at(0).c_str(), TopAbs_FACE);
        TopoDS_Face face = TopoDS::Face(shape);

        BRepAdaptor_Surface sf(face);
        if (sf.GetType() == GeomAbs_Cylinder) {
            return sf.Cylinder().Radius();
        }
        else if (sf.GetType() == GeomAbs_Sphere) {
            return sf.Sphere().Radius();
        }
        else if (sf.GetType() == GeomAbs_Torus) {
            return sf.Torus().MinorRadius();
        }
        else if (sf.GetType() == GeomAbs_Plane) {
            return BRepAdaptor_Curve(TopoDS::Edge(TopExp_Explorer(face, TopAbs_EDGE).Current()))
                .Circle()
                .Radius();
        }
    }

    Base::Console().error("Measurement::radius - Invalid References3D Provided\n");
    return 0.0;
}
double Measurement::diameter() const
{
    int numRefs = References3D.getSize();
    if (numRefs == 0) {
        Base::Console().error("Measurement::diameter - No 3D references available\n");
    }
    else if (
        measureType == MeasureType::Circle || measureType == MeasureType::Cylinder
        || measureType == MeasureType::Disc || measureType == MeasureType::Sphere
        || measureType == MeasureType::Torus
    ) {
        return radius() * 2;
    }
    Base::Console().error("Measurement::diameter - Invalid References3D Provided\n");
    return 0.0;
}

Base::Vector3d Measurement::delta() const
{
    Base::Vector3d result;
    int numRefs = References3D.getSize();
    if (numRefs == 0) {
        Base::Console().error("Measurement::delta - No 3D references available\n");
    }
    else if (measureType == MeasureType::Invalid) {
        Base::Console().error("Measurement::delta - measureType is Invalid\n");
    }
    else {
        const std::vector<App::DocumentObject*>& objects = References3D.getValues();
        const std::vector<std::string>& subElements = References3D.getSubValues();

        if (measureType == MeasureType::PointToPoint) {
            if (numRefs == 2) {
                // Keep separate case for two points to reduce need for complex algorithm
                TopoDS_Shape shape1 = getShape(objects.at(0), subElements.at(0).c_str(), TopAbs_VERTEX);
                TopoDS_Shape shape2 = getShape(objects.at(1), subElements.at(1).c_str(), TopAbs_VERTEX);

                const TopoDS_Vertex& vert1 = TopoDS::Vertex(shape1);
                const TopoDS_Vertex& vert2 = TopoDS::Vertex(shape2);

                gp_Pnt P1 = BRep_Tool::Pnt(vert1);
                gp_Pnt P2 = BRep_Tool::Pnt(vert2);
                gp_XYZ diff = P2.XYZ() - P1.XYZ();
                return Base::Vector3d(diff.X(), diff.Y(), diff.Z());
            }
        }
        else if (
            measureType == MeasureType::PointToEdge || measureType == MeasureType::PointToSurface
            || measureType == MeasureType::PointToCircle || measureType == MeasureType::PointToCylinder
        ) {
            // BrepExtema can calculate minimum distance between any set of topology sets.
            if (numRefs == 2) {
                TopoDS_Shape shape1 = getShape(objects.at(0), subElements.at(0).c_str());
                TopoDS_Shape shape2 = getShape(objects.at(1), subElements.at(1).c_str());

                BRepExtrema_DistShapeShape extrema(shape1, shape2);

                if (extrema.IsDone()) {
                    // Found the nearest point between point and curve
                    // NOTE we will assume there is only 1 solution (cyclic topology will create
                    // multiple solutions.
                    gp_Pnt P1 = extrema.PointOnShape1(1);
                    gp_Pnt P2 = extrema.PointOnShape2(1);
                    gp_XYZ diff = P2.XYZ() - P1.XYZ();
                    result = Base::Vector3d(diff.X(), diff.Y(), diff.Z());
                }
            }
        }
        else if (measureType == MeasureType::Edges) {
            // Only case that is supported is straight line edge
            if (numRefs == 1) {
                TopoDS_Shape shape = getShape(objects.at(0), subElements.at(0).c_str(), TopAbs_EDGE);
                const TopoDS_Edge& edge = TopoDS::Edge(shape);
                BRepAdaptor_Curve curve(edge);

                if (curve.GetType() == GeomAbs_Line) {
                    gp_Pnt P1 = curve.Value(curve.FirstParameter());
                    gp_Pnt P2 = curve.Value(curve.LastParameter());
                    gp_XYZ diff = P2.XYZ() - P1.XYZ();
                    result = Base::Vector3d(diff.X(), diff.Y(), diff.Z());
                }
            }
            else if (numRefs == 2) {
                TopoDS_Shape shape1 = getShape(objects.at(0), subElements.at(0).c_str(), TopAbs_EDGE);
                TopoDS_Shape shape2 = getShape(objects.at(1), subElements.at(1).c_str(), TopAbs_EDGE);

                BRepAdaptor_Curve curve1(TopoDS::Edge(shape1));
                BRepAdaptor_Curve curve2(TopoDS::Edge(shape2));

                // Only permit line to line distance
                if (curve1.GetType() == GeomAbs_Line && curve2.GetType() == GeomAbs_Line) {
                    BRepExtrema_DistShapeShape extrema(shape1, shape2);

                    if (extrema.IsDone()) {
                        // Found the nearest point between point and curve
                        // NOTE we will assume there is only 1 solution (cyclic topology will create
                        // multiple solutions.
                        gp_Pnt P1 = extrema.PointOnShape1(1);
                        gp_Pnt P2 = extrema.PointOnShape2(1);
                        gp_XYZ diff = P2.XYZ() - P1.XYZ();
                        result = Base::Vector3d(diff.X(), diff.Y(), diff.Z());
                    }
                }
            }
        }
        else {
            Base::Console().error("Measurement::delta - measureType is not recognized\n");
        }
    }
    return result;
}

double Measurement::volume() const
{
    double result = 0.0;
    if (References3D.getSize() == 0) {
        Base::Console().error("Measurement::volume - No 3D references available\n");
    }
    else if (measureType != MeasureType::Volumes) {
        Base::Console().error("Measurement::volume - measureType is not Volumes\n");
    }
    else {
        const std::vector<App::DocumentObject*>& objects = References3D.getValues();
        const std::vector<std::string>& subElements = References3D.getSubValues();

        for (size_t i = 0; i < objects.size(); ++i) {
            GProp_GProps props = GProp_GProps();
            TopoDS_Shape shape = getShape(objects[i], subElements[i].c_str());
            if (shape.IsNull() || shape.Infinite()) {
                continue;
            }
            BRepGProp::VolumeProperties(shape, props);
            result += props.Mass();
        }
    }
    return result;
}

double Measurement::area() const
{
    double result = 0.0;
    if (References3D.getSize() == 0) {
        Base::Console().error("Measurement::area - No 3D references available\n");
    }
    else if (
        measureType == MeasureType::Volumes || measureType == MeasureType::Surfaces
        || measureType == MeasureType::Cylinder || measureType == MeasureType::CylinderSection
        || measureType == MeasureType::TwoCylinders || measureType == MeasureType::Cone
        || measureType == MeasureType::Sphere || measureType == MeasureType::Torus
        || measureType == MeasureType::Plane || measureType == MeasureType::Disc
    ) {

        const std::vector<App::DocumentObject*>& objects = References3D.getValues();
        const std::vector<std::string>& subElements = References3D.getSubValues();

        for (size_t i = 0; i < objects.size(); ++i) {
            GProp_GProps props;
            TopoDS_Shape shape = getShape(objects[i], subElements[i].c_str());
            if (shape.IsNull() || shape.Infinite()) {
                continue;
            }
            BRepGProp::SurfaceProperties(shape, props);
            result += props.Mass();  // Area is obtained using Mass method for surface properties
        }
    }
    else {
        Base::Console().error("Measurement::area - measureType is not valid\n");
    }
    return result;
}

Base::Vector3d Measurement::massCenter() const
{
    Base::Vector3d result;
    int numRefs = References3D.getSize();
    if (numRefs == 0) {
        Base::Console().error("Measurement::massCenter - No 3D references available\n");
    }
    else if (measureType == MeasureType::Invalid) {
        Base::Console().error("Measurement::massCenter - measureType is Invalid\n");
    }
    else {
        const std::vector<App::DocumentObject*>& objects = References3D.getValues();
        const std::vector<std::string>& subElements = References3D.getSubValues();
        GProp_GProps gprops = GProp_GProps();

        if (measureType == MeasureType::Volumes) {
            // Iterate through edges and calculate each length
            std::vector<App::DocumentObject*>::const_iterator obj = objects.begin();
            std::vector<std::string>::const_iterator subEl = subElements.begin();

            for (; obj != objects.end(); ++obj, ++subEl) {

                // Compute inertia properties

                GProp_GProps props = GProp_GProps();
                TopoDS_Shape shape = ShapeFinder::getLocatedShape(*(*obj), "");
                if (shape.IsNull()) {
                    continue;
                }
                BRepGProp::VolumeProperties(shape, props);
                gprops.Add(props);
                // Get inertia properties
            }

            gp_Pnt cog = gprops.CentreOfMass();

            return Base::Vector3d(cog.X(), cog.Y(), cog.Z());
        }
        else {
            Base::Console().error("Measurement::massCenter - measureType is not recognized\n");
        }
    }
    return result;
}

bool Measurement::planesAreParallel() const
{
    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subElements = References3D.getSubValues();

    std::vector<gp_Dir> planeNormals;

    for (size_t i = 0; i < objects.size(); ++i) {
        TopoDS_Shape refSubShape;
        try {
            refSubShape = Part::Feature::getShape(
                objects[i],
                Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                    | Part::ShapeOption::Transform,
                subElements[i].c_str()
            );

            if (refSubShape.IsNull()) {
                return false;
            }
        }
        catch (Standard_Failure& e) {
            std::stringstream errorMsg;
            errorMsg << "Measurement - planesAreParallel - " << e.GetMessageString() << std::endl;
            throw Base::CADKernelError(e.GetMessageString());
        }

        if (refSubShape.ShapeType() == TopAbs_FACE) {
            TopoDS_Face face = TopoDS::Face(refSubShape);
            BRepAdaptor_Surface sf(face);

            if (sf.GetType() == GeomAbs_Plane) {
                gp_Pln plane = sf.Plane();
                gp_Dir normal = plane.Axis().Direction();
                planeNormals.push_back(normal);
            }
        }
    }

    if (planeNormals.size() != 2) {
        return false;  // Ensure exactly two planes are considered
    }

    // Check if normals are parallel (either identical or opposite)
    const gp_Dir& normal1 = planeNormals[0];
    const gp_Dir& normal2 = planeNormals[1];

    return normal1.IsParallel(normal2, Precision::Angular());
}

bool Measurement::linesAreParallel() const
{
    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subElements = References3D.getSubValues();

    if (References3D.getSize() != 2) {
        return false;
    }

    // Get the first line
    TopoDS_Shape shape1 = getShape(objects[0], subElements[0].c_str(), TopAbs_EDGE);
    if (shape1.IsNull()) {
        return false;
    }
    const TopoDS_Edge& edge1 = TopoDS::Edge(shape1);
    BRepAdaptor_Curve curve1(edge1);

    // Get the second line
    TopoDS_Shape shape2 = getShape(objects[1], subElements[1].c_str(), TopAbs_EDGE);
    if (shape2.IsNull()) {
        return false;
    }
    const TopoDS_Edge& edge2 = TopoDS::Edge(shape2);
    BRepAdaptor_Curve curve2(edge2);

    if (curve1.GetType() == GeomAbs_Line && curve2.GetType() == GeomAbs_Line) {
        gp_Lin line1 = curve1.Line();
        gp_Lin line2 = curve2.Line();

        gp_Dir dir1 = line1.Direction();
        gp_Dir dir2 = line2.Direction();

        // Check if lines are parallel
        if (dir1.IsParallel(dir2, Precision::Angular())) {
            return true;
        }
    }

    return false;
}

unsigned int Measurement::getMemSize() const
{
    return 0;
}

PyObject* Measurement::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new MeasurementPy(this), true);
    }
    return Py::new_reference_to(PythonObject);
}
// FreeCAD-CH (ops#153): Quick Measure's min, max and center distances between two references,
// and the sums over any number (notes/measure-design.md)

namespace
{
using Clock = std::chrono::steady_clock;

// Stops OCCT's algorithms at a deadline (through Message_ProgressScope::More); the loops below
// check it per edge and face
class Deadline: public Message_ProgressIndicator
{
public:
    explicit Deadline(Clock::time_point end)
        : end(end)
    {}
    bool UserBreak() override
    {
        return expired();
    }
    void Show(const Message_ProgressScope& /*scope*/, const bool /*force*/) override
    {}
    bool expired() const
    {
        return Clock::now() > end;
    }

private:
    Clock::time_point end;
};

bool isDegenerated(const TopoDS_Shape& edge)
{
    return BRep_Tool::Degenerated(TopoDS::Edge(edge));
}

// Whether Extrema finds a point's extrema on the curve or surface analytically (else it samples)
bool isAnalytic(GeomAbs_CurveType type)
{
    switch (type) {
        case GeomAbs_Line:
        case GeomAbs_Circle:
        case GeomAbs_Ellipse:
        case GeomAbs_Hyperbola:
        case GeomAbs_Parabola:
            return true;
        default:
            return false;
    }
}

bool isAnalytic(GeomAbs_SurfaceType type)
{
    switch (type) {
        case GeomAbs_Plane:
        case GeomAbs_Cylinder:
        case GeomAbs_Cone:
        case GeomAbs_Sphere:
        case GeomAbs_Torus:
            return true;
        default:
            return false;
    }
}

// The center of mass of the shape's subshapes of the highest dimension, one face or edge at a
// time so the deadline is checked in between. A solid's volume integral is taken over its faces
// against one common point, as BRepGProp::VolumeProperties does
bool centerOfMass(const TopoDS_Shape& shape, const Deadline& deadline, gp_Pnt& center)
{
    Bnd_Box box;
    BRepBndLib::Add(shape, box);
    if (box.IsVoid()) {
        return false;
    }
    double x0 {}, y0 {}, z0 {}, x1 {}, y1 {}, z1 {};
    box.Get(x0, y0, z0, x1, y1, z1);
    const gp_Pnt location((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
    GProp_GProps total(location);

    TopTools_IndexedMapOfShape faces, edges;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    TopExp::MapShapes(shape, TopAbs_EDGE, edges);
    if (TopExp_Explorer(shape, TopAbs_SOLID).More()) {
        BRepGProp_Vinert vinert;
        vinert.SetLocation(location);
        for (TopExp_Explorer solids(shape, TopAbs_SOLID); solids.More(); solids.Next()) {
            for (TopExp_Explorer ex(solids.Current(), TopAbs_FACE); ex.More(); ex.Next()) {
                if (deadline.expired()) {
                    return false;
                }
                const TopoDS_Face& face = TopoDS::Face(ex.Current());
                BRepGProp_Face gface(face);
                if (BRep_Tool::NaturalRestriction(face)) {
                    vinert.Perform(gface);
                }
                else {
                    BRepGProp_Domain domain(face);
                    vinert.Perform(gface, domain);
                }
                total.Add(vinert);
            }
        }
    }
    else if (!faces.IsEmpty()) {
        for (int i = 1; i <= faces.Extent(); ++i) {
            if (deadline.expired()) {
                return false;
            }
            GProp_GProps props;
            BRepGProp::SurfaceProperties(faces(i), props);
            total.Add(props);
        }
    }
    else if (!edges.IsEmpty()) {
        for (int i = 1; i <= edges.Extent(); ++i) {
            if (deadline.expired()) {
                return false;
            }
            GProp_GProps props;
            BRepGProp::LinearProperties(edges(i), props);
            total.Add(props);
        }
    }
    else {
        TopTools_IndexedMapOfShape vertices;
        TopExp::MapShapes(shape, TopAbs_VERTEX, vertices);
        if (vertices.IsEmpty()) {
            return false;
        }
        gp_XYZ sum;
        for (int i = 1; i <= vertices.Extent(); ++i) {
            sum += BRep_Tool::Pnt(TopoDS::Vertex(vertices(i))).XYZ();
        }
        center = gp_Pnt(sum / vertices.Extent());
        return true;
    }
    if (std::abs(total.Mass()) <= Precision::Confusion()) {
        return false;
    }
    center = total.CentreOfMass();
    return true;
}

// A circle's or a sphere's center, else the center of mass
bool centerOf(const TopoDS_Shape& shape, const Deadline& deadline, gp_Pnt& center)
{
    if (shape.ShapeType() == TopAbs_EDGE && !isDegenerated(shape)) {
        BRepAdaptor_Curve curve(TopoDS::Edge(shape));
        if (curve.GetType() == GeomAbs_Circle) {
            center = curve.Circle().Location();
            return true;
        }
    }
    if (shape.ShapeType() == TopAbs_FACE) {
        BRepAdaptor_Surface surface(TopoDS::Face(shape));
        if (surface.GetType() == GeomAbs_Sphere) {
            center = surface.Sphere().Location();
            return true;
        }
    }
    return centerOfMass(shape, deadline, center);
}

// Only planes and lines: the farthest pair is a pair of vertices
bool isPolyhedral(const TopoDS_Shape& shape)
{
    for (TopExp_Explorer ex(shape, TopAbs_FACE); ex.More(); ex.Next()) {
        if (BRepAdaptor_Surface(TopoDS::Face(ex.Current())).GetType() != GeomAbs_Plane) {
            return false;
        }
    }
    for (TopExp_Explorer ex(shape, TopAbs_EDGE); ex.More(); ex.Next()) {
        if (!isDegenerated(ex.Current())
            && BRepAdaptor_Curve(TopoDS::Edge(ex.Current())).GetType() != GeomAbs_Line) {
            return false;
        }
    }
    return true;
}

// Points among which the farthest pair of two shapes lies, up to the sampling: the vertices,
// samples on curved edges, and a grid on faces whose interior can hold an extreme point of the
// convex hull (not planes, cylinders, cones or extrusions, whose rulings end on the boundary).
// Above the limit every k-th point is kept, and decimated says so. False if the deadline passed
bool maxCandidates(
    const TopoDS_Shape& shape,
    double deflection,
    const Deadline& deadline,
    std::vector<gp_Pnt>& points,
    bool& decimated
)
{
    constexpr std::size_t limit = 2000;
    constexpr int grid = 16;
    points.clear();
    decimated = false;
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, TopAbs_VERTEX, map);
    for (int i = 1; i <= map.Extent(); ++i) {
        points.push_back(BRep_Tool::Pnt(TopoDS::Vertex(map(i))));
    }
    map.Clear();
    TopExp::MapShapes(shape, TopAbs_EDGE, map);
    for (int i = 1; i <= map.Extent(); ++i) {
        if (deadline.expired()) {
            return false;
        }
        if (isDegenerated(map(i))) {
            continue;
        }
        BRepAdaptor_Curve curve(TopoDS::Edge(map(i)));
        if (curve.GetType() == GeomAbs_Line) {
            continue;
        }
        GCPnts_TangentialDeflection sampler(curve, 0.2, deflection);
        for (int j = 1; j <= sampler.NbPoints(); ++j) {
            points.push_back(sampler.Value(j));
        }
    }
    map.Clear();
    TopExp::MapShapes(shape, TopAbs_FACE, map);
    for (int i = 1; i <= map.Extent(); ++i) {
        if (deadline.expired()) {
            return false;
        }
        const TopoDS_Face& face = TopoDS::Face(map(i));
        BRepAdaptor_Surface surface(face);
        switch (surface.GetType()) {
            case GeomAbs_Plane:
            case GeomAbs_Cylinder:
            case GeomAbs_Cone:
            case GeomAbs_SurfaceOfExtrusion:
                continue;
            default:
                break;
        }
        double u0 {}, u1 {}, v0 {}, v1 {};
        BRepTools::UVBounds(face, u0, u1, v0, v1);
        BRepTopAdaptor_FClass2d classifier(face, Precision::PConfusion());
        for (int iu = 0; iu <= grid; ++iu) {
            for (int iv = 0; iv <= grid; ++iv) {
                const double u = u0 + (u1 - u0) * iu / grid;
                const double v = v0 + (v1 - v0) * iv / grid;
                if (classifier.Perform(gp_Pnt2d(u, v)) != TopAbs_OUT) {
                    points.push_back(surface.Value(u, v));
                }
            }
        }
    }
    if (points.size() > limit) {
        decimated = true;
        std::vector<gp_Pnt> fewer;
        fewer.reserve(limit);
        const double step = static_cast<double>(points.size()) / limit;
        for (std::size_t i = 0; i < limit; ++i) {
            fewer.push_back(points[static_cast<std::size_t>(i * step)]);
        }
        points.swap(fewer);
    }
    return true;
}

// The point of the shape farthest from p: at a vertex, or at a stationary point inside an edge
// or a face (all extrema of the distance from p, maxima included). exact turns false when an
// extremum search threw or sampled (a curve or surface Extrema has no analytic solution for).
// An analytic search that isn't done found no extremum inside the bounds, or infinitely many
// (p on an axis), whose farthest points then lie on the boundary too: exact stays.
// Returns -1 if the deadline passed
double farthestOn(
    const TopoDS_Shape& shape,
    const gp_Pnt& p,
    const Deadline& deadline,
    gp_Pnt& farthest,
    bool& exact
)
{
    double best = -1.0;
    auto consider = [&](const gp_Pnt& q) {
        const double d = p.SquareDistance(q);
        if (d > best) {
            best = d;
            farthest = q;
        }
    };
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(shape, TopAbs_VERTEX, map);
    for (int i = 1; i <= map.Extent(); ++i) {
        consider(BRep_Tool::Pnt(TopoDS::Vertex(map(i))));
    }
    const TopoDS_Vertex vertex = BRepBuilderAPI_MakeVertex(p);
    map.Clear();
    TopExp::MapShapes(shape, TopAbs_EDGE, map);
    for (int i = 1; i <= map.Extent(); ++i) {
        if (deadline.expired()) {
            return -1.0;
        }
        if (isDegenerated(map(i))) {
            continue;
        }
        const TopoDS_Edge& edge = TopoDS::Edge(map(i));
        try {
            BRepExtrema_ExtPC ext(vertex, edge);
            if (!isAnalytic(BRepAdaptor_Curve(edge).GetType())) {
                exact = false;
            }
            for (int n = 1; ext.IsDone() && n <= ext.NbExt(); ++n) {
                consider(ext.Point(n));
            }
        }
        catch (const Standard_Failure&) {
            exact = false;
        }
    }
    map.Clear();
    TopExp::MapShapes(shape, TopAbs_FACE, map);
    for (int i = 1; i <= map.Extent(); ++i) {
        if (deadline.expired()) {
            return -1.0;
        }
        const TopoDS_Face& face = TopoDS::Face(map(i));
        try {
            BRepExtrema_ExtPF ext(vertex, face, Extrema_ExtFlag_MAX);
            if (!isAnalytic(BRepAdaptor_Surface(face).GetType())) {
                exact = false;
            }
            for (int n = 1; ext.IsDone() && n <= ext.NbExt(); ++n) {
                consider(ext.Point(n));
            }
        }
        catch (const Standard_Failure&) {
            exact = false;
        }
    }
    return best < 0.0 ? -1.0 : std::sqrt(best);
}
}  // namespace

// FreeCAD-CH (ops#153)
void Measurement::setReferences3D(
    const std::vector<App::DocumentObject*>& objects,
    const std::vector<std::string>& subNames
)
{
    References3D.setValues(objects, subNames);
    measureType = findType();
}

// FreeCAD-CH (ops#153): min (BRepExtrema), max (candidate pairs, then a local refinement) and
// center distances between the two references, within timeLimitMs: BRepExtrema stops at the
// deadline, and every other step checks it per edge or face
DistanceResult Measurement::distances(int timeLimitMs) const
{
    DistanceResult result;
    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subNames = References3D.getSubValues();
    if (objects.size() != 2) {
        return result;
    }
    const TopoDS_Shape a = getShape(objects[0], subNames[0].c_str());
    const TopoDS_Shape b = getShape(objects[1], subNames[1].c_str());
    if (a.IsNull() || b.IsNull()) {
        return result;
    }
    const auto limit = std::chrono::milliseconds(std::max(timeLimitMs, 0));
    Handle(Deadline) deadline = new Deadline(Clock::now() + limit);
    auto timedOut = [&]() {
        result.timedOut = deadline->expired();
        return result.timedOut;
    };

    // Min
    BRepExtrema_DistShapeShape extrema(
        a,
        b,
        Extrema_ExtFlag_MIN,
        Extrema_ExtAlgo_Grad,
        deadline->Start()
    );
    if (timedOut() || !extrema.IsDone() || extrema.NbSolution() < 1) {
        return result;
    }
    result.hasMin = true;
    result.min = extrema.Value();
    result.inside = extrema.InnerSolution();
    result.minFrom = toVector3d(extrema.PointOnShape1(1));
    result.minTo = toVector3d(extrema.PointOnShape2(1));

    // Center
    gp_Pnt centerA, centerB;
    if (centerOf(a, *deadline, centerA) && centerOf(b, *deadline, centerB)) {
        result.hasCenter = true;
        result.center = centerA.Distance(centerB);
        result.centerFrom = toVector3d(centerA);
        result.centerTo = toVector3d(centerB);
    }
    if (timedOut()) {
        return result;
    }

    // Max: the farthest pair of candidates, then from it, twice, the farthest point on the other
    // shape. Exact when both are polyhedral and all their vertices are candidates (the pair is
    // two vertices), or when one is a vertex and the farthest point on the other is found
    // analytically
    Bnd_Box box;
    BRepBndLib::Add(a, box);
    BRepBndLib::Add(b, box);
    const double deflection =
        std::max(std::sqrt(box.SquareExtent()) * 1e-3, Precision::Confusion());
    std::vector<gp_Pnt> pointsA, pointsB;
    bool decimatedA = false, decimatedB = false;
    if (!maxCandidates(a, deflection, *deadline, pointsA, decimatedA)
        || !maxCandidates(b, deflection, *deadline, pointsB, decimatedB)) {
        timedOut();
        return result;
    }
    double best = -1.0;
    gp_Pnt p, q;
    for (const gp_Pnt& pa : pointsA) {
        for (const gp_Pnt& pb : pointsB) {
            const double d = pa.SquareDistance(pb);
            if (d > best) {
                best = d;
                p = pa;
                q = pb;
            }
        }
        if (timedOut()) {
            return result;
        }
    }
    if (best < 0.0) {
        return result;
    }
    best = std::sqrt(best);
    bool exactA = true, exactB = true;
    for (int i = 0; i < 2; ++i) {
        gp_Pnt farther;
        double d = farthestOn(b, p, *deadline, farther, exactB);
        if (timedOut()) {
            return result;
        }
        if (d > best) {
            best = d;
            q = farther;
        }
        d = farthestOn(a, q, *deadline, farther, exactA);
        if (timedOut()) {
            return result;
        }
        if (d > best) {
            best = d;
            p = farther;
        }
    }
    result.hasMax = true;
    result.max = best;
    result.maxFrom = toVector3d(p);
    result.maxTo = toVector3d(q);
    const bool polyhedral = !decimatedA && !decimatedB && isPolyhedral(a) && isPolyhedral(b);
    result.maxExact = polyhedral || (a.ShapeType() == TopAbs_VERTEX && exactB)
        || (b.ShapeType() == TopAbs_VERTEX && exactA);
    return result;
}

// FreeCAD-CH (ops#153): the summed lengths and areas of any selection, per kind
SumResult Measurement::sums() const
{
    SumResult result;
    const std::vector<App::DocumentObject*>& objects = References3D.getValues();
    const std::vector<std::string>& subNames = References3D.getSubValues();
    for (std::size_t i = 0; i < objects.size(); ++i) {
        const TopoDS_Shape shape = getShape(objects[i], subNames[i].c_str());
        if (shape.IsNull()) {
            ++result.other;
            continue;
        }
        switch (shape.ShapeType()) {
            case TopAbs_VERTEX:
                ++result.vertices;
                break;
            case TopAbs_EDGE:
                ++result.edges;
                if (!isDegenerated(shape)) {
                    BRepAdaptor_Curve curve(TopoDS::Edge(shape));
                    result.length += GCPnts_AbscissaPoint::Length(curve);
                }
                break;
            case TopAbs_FACE: {
                ++result.faces;
                GProp_GProps props;
                BRepGProp::SurfaceProperties(shape, props);
                result.area += props.Mass();
                break;
            }
            case TopAbs_SOLID:
                ++result.solids;
                break;
            default:
                ++result.other;
                break;
        }
    }
    return result;
}
