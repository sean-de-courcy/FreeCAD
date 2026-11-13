// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2016 Victor Titov (DeepSOIC) <vv.titov@gmail.com>       *
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
#include <limits>

#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Copy.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepLib_FindSurface.hxx>
#include <ElSLib.hxx>
#include <Geom_Plane.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopExp_Explorer.hxx>
#include <QtGlobal>
#include <TopExp.hxx>

#include "FaceMakerBullseye.h"
#include "FaceMakerCheese.h"

#include "TopoShape.h"
#include "WireJoiner.h"


using namespace Part;

TYPESYSTEM_SOURCE(Part::FaceMakerBullseye, Part::FaceMakerPublic)

void FaceMakerBullseye::setPlane(const gp_Pln& plane)
{
    this->myPlane = gp_Pln(plane);
    this->planeSupplied = true;
}

std::string FaceMakerBullseye::getUserFriendlyName() const
{
    return {tr("Bull's-eye facemaker").toStdString()};
}

std::string FaceMakerBullseye::getBriefExplanation() const
{
    return {tr("Supports making planar faces with holes with islands in them").toStdString()};
}

bool FaceMakerBullseye::WireInfo::operator<(const WireInfo& other) const
{
    return extent - other.extent > Precision::Confusion();
}

void FaceMakerBullseye::Build_Essence()
{
    if (myWires.empty()) {
        return;
    }

    // validity check
    for (TopoDS_Wire& w : myWires) {
        if (!BRep_Tool::IsClosed(w)) {
            throw Base::ValueError("Wire is not closed.");
        }
    }


    // find plane (at the same time, test that all wires are on the same plane)
    gp_Pln plane;
    if (this->planeSupplied) {
        plane = this->myPlane;
    }
    else {
        TopoDS_Builder builder;
        TopoDS_Compound comp;
        builder.MakeCompound(comp);
        for (TopoDS_Wire& w : myWires) {
            builder.Add(comp, BRepBuilderAPI_Copy(w).Shape());
        }
        BRepLib_FindSurface planeFinder(comp, -1, /*OnlyPlane=*/Standard_True);
        if (!planeFinder.Found()) {
            throw Base::ValueError("Wires are not coplanar");
        }
        plane = GeomAdaptor_Surface(planeFinder.Surface()).Plane();
    }

    std::vector<WireInfo> wireInfos;
    for (const auto& w : this->myTopoWires) {
        Bnd_Box box;
        if (w.isNull()) {
            continue;
        }
        BRepBndLib::AddOptimal(w.getShape(), box, Standard_False);
        if (box.IsVoid()) {
            continue;
        }
        wireInfos.emplace_back(w, box);
    }

    // Sort wires by length of diagonal of bounding box.
    std::stable_sort(wireInfos.begin(), wireInfos.end());

    // Where on the plane a face's wires can be: the box of the projections of their boxes' corners,
    // which holds the projection of each of their edges (the curves a planar face classifies on)
    // and of their vertices. FaceDriller::hitTest() of a wire whose first vertex projects outside
    // a face's box, by more than twice that vertex's tolerance and the confusion, can only say
    // HitNone: the vertex is on none of the face's wires, and the classifier finds the point OUT.
    // So it isn't asked: asked of every face made so far, separate regions cost a classification
    // per pair (perf profile 3: a through-all Pocket of 1600 squares, 520 s and refused)
    struct Reach
    {
        double uMin = std::numeric_limits<double>::max();
        double vMin = std::numeric_limits<double>::max();
        double uMax = -std::numeric_limits<double>::max();
        double vMax = -std::numeric_limits<double>::max();
        bool whole = false;  // a box that can't be bounded: every point may be in it
    };
    auto addBox = [&plane](Reach& reach, const Bnd_Box& box) {
        if (box.IsVoid()) {
            return;
        }
        if (box.IsOpen()) {
            reach.whole = true;
            return;
        }
        double x[2], y[2], z[2];
        box.Get(x[0], y[0], z[0], x[1], y[1], z[1]);
        for (double cx : x) {
            for (double cy : y) {
                for (double cz : z) {
                    double u = 0.0;
                    double v = 0.0;
                    ElSLib::Parameters(plane, gp_Pnt(cx, cy, cz), u, v);
                    reach.uMin = std::min(reach.uMin, u);
                    reach.vMin = std::min(reach.vMin, v);
                    reach.uMax = std::max(reach.uMax, u);
                    reach.vMax = std::max(reach.vMax, v);
                }
            }
        }
    };
    auto away = [](const Reach& reach, double u, double v, double margin) {
        return !reach.whole
            && (u < reach.uMin - margin || u > reach.uMax + margin || v < reach.vMin - margin
                || v > reach.vMax + margin);
    };

    for (int i = 0; i < (reuseInnerWire ? 2 : 1); ++i) {
        // add wires one by one to current set of faces.
        std::vector<std::unique_ptr<FaceDriller>> faces;
        std::vector<Reach> reaches;  // each face's, in the same order
        for (auto it = wireInfos.begin(); it != wireInfos.end();) {

            // The point FaceDriller::hitTest() classifies: the wire's first vertex, on the plane
            const auto vertex = TopoDS::Vertex(it->wire.getSubShape(TopAbs_VERTEX, 1));
            const double margin = 2 * BRep_Tool::Tolerance(vertex) + Precision::Confusion();
            double pointU = 0.0;
            double pointV = 0.0;
            ElSLib::Parameters(plane, BRep_Tool::Pnt(vertex), pointU, pointV);

            // test if this wire is on any of existing faces (if yes, it's a hole;
            //  if no, it's a beginning of a new face).
            FaceDriller* foundFace = nullptr;
            Reach* foundReach = nullptr;
            bool hitted = false;
            for (std::size_t k = faces.size(); k-- > 0;) {
                if (away(reaches[k], pointU, pointV, margin)) {
                    continue;
                }
                switch (faces[k]->hitTest(it->wire)) {
                    case FaceDriller::HitTest::Hit:
                        foundFace = faces[k].get();
                        foundReach = &reaches[k];
                        hitted = true;
                        break;
                    case FaceDriller::HitTest::HitOuter:
                        // Shape in outer wire but not on face, which means it is
                        // within a hole. So it's a hit and we shall make a new face
                        // with the wire.
                        hitted = true;
                        break;
                    default:
                        break;
                }
            }

            TopoDS_Wire w = TopoDS::Wire(it->wire.getShape());

            if (foundFace) {
                // wire is on a face.
                if (reuseInnerWire) {
                    foundFace->addHole(*it, mySourceShapes);
                }
                else {
                    foundFace->addHole(w);
                }
                // Inside the outer wire's box when the wires are sound; added all the same, so
                // that a vertex shared with a hole wire is never skipped
                addBox(*foundReach, it->bound);
            }
            else {
                // wire is not on a face. Start a new face.
                faces.push_back(std::make_unique<FaceDriller>(plane, w));
                reaches.emplace_back();
                addBox(reaches.back(), it->bound);
            }

            if (i == 0 && reuseInnerWire && !hitted) {
                // If reuseInnerWire, then discard the outer-most wire, and
                // retry so that the previous hole (and nested hole) wires can
                // become outer wire for new faces.
                it = wireInfos.erase(it);
            }
            else {
                ++it;
            }
        }

        // and we are done!
        for (std::unique_ptr<FaceDriller>& ff : faces) {
            this->myShapesToReturn.push_back(ff->Face());
        }
    }
}


FaceMakerBullseye::FaceDriller::FaceDriller(const gp_Pln& plane, TopoDS_Wire outerWire)
{
    this->myPlane = plane;
    this->myFace = TopoDS_Face();

    // Ensure correct orientation of the wire.
    if (getWireDirection(myPlane, outerWire) < 0) {
        outerWire.Reverse();
    }

    myHPlane = new Geom_Plane(this->myPlane);
    BRep_Builder builder;
    builder.MakeFace(this->myFace, myHPlane, Precision::Confusion());
    builder.Add(this->myFace, outerWire);
    this->myTopoFace = TopoShape(this->myFace);
}

FaceMakerBullseye::FaceDriller::HitTest FaceMakerBullseye::FaceDriller::hitTest(
    const TopoShape& shape
) const
{
    auto vertex = TopoDS::Vertex(shape.getSubShape(TopAbs_VERTEX, 1));
    if (!myFaceBound.IsNull()) {
        if (myTopoFaceBound.findShape(vertex) > 0) {
            return HitTest::HitNone;
        }
        for (const auto& info : myHoles) {
            if (info.wire.findShape(vertex)) {
                return HitTest::Hit;
            }
        }
    }
    else if (myTopoFace.findShape(vertex) > 0) {
        return HitTest::HitNone;
    }

    double tol = BRep_Tool::Tolerance(vertex);
    auto point = BRep_Tool::Pnt(vertex);
    double u, v;
    GeomAPI_ProjectPointOnSurf(point, myHPlane).LowerDistanceParameters(u, v);
    const char* err = "FaceMakerBullseye::FaceDriller::hitTest: result unknown";
    auto hit = HitTest::HitNone;
    if (!myFaceBound.IsNull()) {
        BRepClass_FaceClassifier cl(myFaceBound, gp_Pnt2d(u, v), tol);
        switch (cl.State()) {
            case TopAbs_OUT:
            case TopAbs_ON:
                return HitTest::HitNone;
            case TopAbs_IN:
                hit = HitTest::HitOuter;
                break;
            default:
                throw Base::ValueError(err);
        }
    }
    // Against the outer wire and the holes whose box holds the point, not the whole face: a hole
    // the point is away from can't change its state, and classifying against every earlier hole
    // made a sketch of 3600 circles' faces quadratic (73 of a Pad's 89 s, kernel-9)
    TopoDS_Face face = myFace;
    if (!myHoleWires.empty()) {
        BRep_Builder builder;
        builder.MakeFace(face, myHPlane, Precision::Confusion());
        builder.Add(face, TopoDS_Iterator(myFace).Value());  // the outer wire, added first
        for (const auto& [wire, box] : myHoleWires) {
            Bnd_Box reach = box;
            reach.Enlarge(2 * tol + Precision::Confusion());
            if (!reach.IsOut(point)) {
                builder.Add(face, wire);
            }
        }
    }
    BRepClass_FaceClassifier cl(face, gp_Pnt2d(u, v), tol);
    TopAbs_State ret = cl.State();
    switch (ret) {
        case TopAbs_IN:
            return HitTest::Hit;
        case TopAbs_ON:
            if (hit == HitTest::HitOuter) {
                // the given point is within the outer wire, but on some other wire
                // of the face, which must be a hole wire, which means that two hole
                // wires have shared vertex (or edge). We can deal with this if
                // reuseInnerWire is on by merging these holes.
                return HitTest::Hit;
            }
            return HitTest::HitNone;
        case TopAbs_OUT:
            return hit;
        default:
            throw Base::ValueError(err);
    }
}

void FaceMakerBullseye::FaceDriller::copyFaceBound(
    TopoDS_Face& face,
    TopoShape& topoFace,
    const TopoShape& source
)
{
    face = BRepBuilderAPI_MakeFace(myHPlane, TopoDS::Wire(source.getSubShape(TopAbs_WIRE, 1)));
    topoFace = TopoShape(face);
}

void FaceMakerBullseye::FaceDriller::addHole(TopoDS_Wire w)
{
    // Ensure correct orientation of the wire.
    if (getWireDirection(myPlane, w) > 0) {  // if wire is CCW..
        w.Reverse();                         //.. we want CW!
    }

    if (this->myFaceBound.IsNull()) {
        copyFaceBound(this->myFaceBound, this->myTopoFaceBound, this->myTopoFace);
    }

    BRep_Builder builder;
    builder.Add(this->myFace, w);
    addHoleWire(w);
}

void FaceMakerBullseye::FaceDriller::addHoleWire(const TopoDS_Wire& w)
{
    Bnd_Box box;
    BRepBndLib::Add(w, box);
    myHoleWires.emplace_back(w, box);
}

void FaceMakerBullseye::FaceDriller::addHole(const WireInfo& wireInfo, std::vector<TopoShape>& sources)
{
    if (this->myFaceBound.IsNull()) {
        copyFaceBound(this->myFaceBound, this->myTopoFaceBound, this->myTopoFace);
    }

    if (!myJoiner) {
        myJoiner.reset(new WireJoiner);
        myJoiner->setOutline(true);
    }
    myJoiner->addShape(wireInfo.wire);

    bool intersected = false;
    for (const auto& info : myHoles) {
        if (!info.bound.IsOut(wireInfo.bound) || !wireInfo.bound.IsOut(info.bound)) {
            intersected = true;
            break;
        }
    }

    myHoles.push_back(wireInfo);
    TopoShape wire = wireInfo.wire;

    if (intersected) {
        TopoShape hole;
        // Join intersected wires and get their outline
        myJoiner->getResultWires(hole);
        // Check if the hole gets merged.
        if (!hole.findShape(wireInfo.wire.getShape())) {
            for (const auto& e : wireInfo.wire.getSubTopoShapes(TopAbs_EDGE)) {
                if (hole.findShape(e.getShape()) > 0) {
                    continue;
                }
                for (const auto& e : hole.findSubShapesWithSharedVertex(e.getShape())) {
                    sources.push_back(e);
                }
            }
            copyFaceBound(this->myFace, this->myTopoFace, this->myTopoFaceBound);
            myHoleWires.clear();  // the face is the outer wire again; the joined holes follow
            wire = hole;
        }
    }

    BRep_Builder builder;
    for (const auto& w : wire.getSubShapes(TopAbs_WIRE)) {
        // Ensure correct orientation of the wire.
        TopoDS_Wire hole = TopoDS::Wire(w);
        if (getWireDirection(myPlane, hole) > 0) {  // if wire is CCW..
            hole = TopoDS::Wire(w.Reversed());      //.. we want CW!
        }
        builder.Add(this->myFace, hole);
        addHoleWire(hole);
    }
}

int FaceMakerBullseye::FaceDriller::getWireDirection(const gp_Pln& plane, const TopoDS_Wire& wire)
{
    // Build a face using the known plane (avoids the expensive BRepLib_FindSurface).
    // Since the plane is supplied, the surface normal is always co-directional with plane.
    BRepBuilderAPI_MakeFace mkFace(plane, wire, /*Inside=*/Standard_True);
    TopoDS_Face tmpFace = mkFace.Face();
    if (tmpFace.IsNull()) {
        throw Standard_Failure("getWireDirection: Failed to create face from wire");
    }

    // CheckInside() (called by the constructor) reverses the wires in the face if the wire
    // was CW — detect this via the wire orientation change.
    TopoDS_Iterator it(tmpFace, /*CumOri=*/Standard_False);
    bool normal_co = it.Value().Orientation() == wire.Orientation();

    return normal_co ? 1 : -1;
}

//////////////////////////////////////////////////////////////////////////////////////////////////

TYPESYSTEM_SOURCE(Part::FaceMakerRing, Part::FaceMakerBullseye)

FaceMakerRing::FaceMakerRing()
{
    reuseInnerWire = true;
}

std::string FaceMakerRing::getUserFriendlyName() const
{
    return {tr("Ring facemaker").toStdString()};
}

std::string FaceMakerRing::getBriefExplanation() const
{
    return {tr("Supports making planar faces with holes and holes as faces").toStdString()};
}
