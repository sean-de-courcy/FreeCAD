// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
 *                                                                          *
 *   Copyright (c) 2008 Jürgen Riegel <juergen.riegel@web.de>               *
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
#include <cmath>
#include <numbers>
#include <set>
#include <tuple>

#include <Geom2dAPI_InterCurveCurve.hxx>
#include <Geom2dInt_GInter.hxx>
#include <Geom2d_Line.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <GeomAPI.hxx>
#include <Geom_Curve.hxx>
#include <IntRes2d_IntersectionSegment.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <gp_Pln.hxx>

#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <Base/Console.h>
#include <Base/Tools.h>
#include <Base/Vector3D.h>

#include <memory>

#include "GeoEnum.h"
#include "SketchObject.h"


#undef DEBUG
// #define DEBUG

// clang-format off
using namespace Sketcher;
using namespace Base;

int SketchObject::moveGeometries(const std::vector<GeoElementId>& geoEltIds, const Base::Vector3d& toPoint, bool relative,
                            bool updateGeoBeforeMoving)
{

    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    // if we are moving a point at SketchObject level, we need to start from a solved sketch
    // if we have conflicts we can forget about moving. However, there is the possibility that we
    // need to do programmatically moves of new geometry that has not been solved yet and that
    // because they were programmatically generated won't generate a conflict. This is the case of
    // Fillet for example. This is why exceptionally, it may be required to update the sketch
    // geometry to that of of SketchObject upon moving. => use updateGeometry parameter = true then


    if (updateGeoBeforeMoving || solverNeedsUpdate) {
        // FreeCAD-CH (ops#640): a conflict solved around stays left out while dragging (the
        // skip set of the last solve), and its diagnosis stays the one the marks show
        const int dof = solvedSketch.setUpSketch(
            getCompleteGeometry(), Constraints.getValues(), getExternalGeometryCount());

        if (!lastSolvedAroundConflict) {
            lastDoF = dof;
            retrieveSolverDiagnostics();
        }

        solverNeedsUpdate = false;
    }

    if (solvedSketch.hasConflicts())  // conflicting constraints in what the solver holds
        return -1;
    if (!lastSolvedAroundConflict && (lastDoF < 0 || lastHasConflict))  // over-constrained
        return -1;

    // move the point and solve
    lastSolverStatus = solvedSketch.moveGeometries(geoEltIds, toPoint, relative);

    // moving the point can not result in a conflict that we did not have
    // or a redundancy that we did not have before, or a change of DoF

    if (lastSolverStatus == 0) {
        std::vector<Part::Geometry*> geomlist = solvedSketch.extractGeometry();
        Geometry.setValues(geomlist);
        for (auto* geo :  geomlist) {
            delete geo;
        }
    }

    solvedSketch.resetInitMove();// reset solver point moving mechanism

    return lastSolverStatus;
}

int SketchObject::moveGeometry(int geoId, PointPos pos, const Base::Vector3d& toPoint, bool relative,
    bool updateGeoBeforeMoving)
{
    std::vector<GeoElementId> geoEltIds = { GeoElementId(geoId, pos) };
    return moveGeometries(geoEltIds, toPoint, relative, updateGeoBeforeMoving);
}

int SketchObject::delGeometries(const std::vector<int>& GeoIds, DeleteOptions options)
{
    return delGeometries(GeoIds.begin(), GeoIds.end(), options);
}

template <class InputIt>
int SketchObject::delGeometries(InputIt first, InputIt last, DeleteOptions options)
{
    std::vector<int> sGeoIds;
    std::vector<int> negativeGeoIds;

    // Separate GeoIds into negative (external) and non-negative GeoIds
    for (auto it = first; it != last; ++it) {
        int geoId = *it;
        if (geoId < 0 && geoId <= GeoEnum::RefExt) {
            negativeGeoIds.push_back(geoId);
        }
        else if (geoId >= 0){
            sGeoIds.push_back(geoId);
        }
    }

    // Handle negative GeoIds by calling delExternal
    if (!negativeGeoIds.empty()) {
        int result = delExternal(negativeGeoIds);
        if (result != 0) {
            return result; // Return if deletion of external geometries failed
        }
    }

    // Proceed with non-negative GeoIds
    if (sGeoIds.empty()) {
        return 0; // No positive GeoIds to delete
    }

    // if a GeoId has internal geometry, it must delete internal geometries too
    for (auto c : Constraints.getValues()) {
        if (c->Type == InternalAlignment) {
            auto pos = std::ranges::find(sGeoIds, c->Second);

            if (pos != sGeoIds.end()) {
                sGeoIds.push_back(c->First);
            }
        }
    }

    std::ranges::sort(sGeoIds);
    // eliminate duplicates
    auto newend = std::unique(sGeoIds.begin(), sGeoIds.end());
    sGeoIds.resize(std::distance(sGeoIds.begin(), newend));

    return delGeometriesExclusiveList(sGeoIds, options);
}

// clang-format on
void SketchObject::replaceGeometries(std::vector<int> oldGeoIds, std::vector<Part::Geometry*>& newGeos)
{
    auto& vals = getInternalGeometry();
    auto newVals(vals);

    if (std::ranges::any_of(oldGeoIds, [](auto geoId) { return geoId < 0; })) {
        THROWM(ValueError, "Cannot replace external geometries and axes.");
    }

    auto oldGeoIdIter = oldGeoIds.begin();
    auto newGeoIter = newGeos.begin();

    for (; oldGeoIdIter != oldGeoIds.end() && newGeoIter != newGeos.end();
         ++oldGeoIdIter, ++newGeoIter) {
        GeometryFacade::copyId(getGeometry(*oldGeoIdIter), *newGeoIter);
        newVals[*oldGeoIdIter] = *newGeoIter;
    }

    for (; newGeoIter != newGeos.end(); ++newGeoIter) {
        generateId(*newGeoIter);
        newVals.push_back(*newGeoIter);
    }

    // Set geometries first, then delete the old ones. This allows to use `delGeometries`.
    Geometry.setValues(std::move(newVals));

    delGeometries(oldGeoIdIter, oldGeoIds.end());
}
// clang-format off

std::vector<int> SketchObject::chooseFilletsEdges(const std::vector<int>& GeoIdList) const
{
    if (GeoIdList.size() == 2) {
        return GeoIdList;
    }

    std::vector<int> dst;
    for (auto id : GeoIdList) {
        if (!GeometryFacade::getFacade(getGeometry(id))->getConstruction()) {
            dst.push_back(id);

            if (dst.size() > 2) {
                return {};
            }
        }
    }
    return dst;
}

int SketchObject::fillet(int GeoId, PointPos PosId, double radius, bool trim, bool createCorner, bool chamfer)
{
    if (GeoId < 0 || GeoId > getHighestCurveIndex()) {
        Base::Console().error("Invalid GeoId: %d\n", GeoId);
        return -1;
    }

    // Find the other geometry Id associated with the coincident point
    std::vector<int> GeoIdList;
    std::vector<PointPos> PosIdList;
    getDirectlyCoincidentPoints(GeoId, PosId, GeoIdList, PosIdList);

    GeoIdList = chooseFilletsEdges(GeoIdList);

    // only coincident points between two (non-external) edges can be filleted
    if (GeoIdList.size() != 2 || GeoIdList[0] < 0 || GeoIdList[1] < 0) {
        Base::Console().error("Invalid number of edges connected to GeoId: %d\n", GeoId);
        return -1;
    }

    const Part::Geometry* geo1 = getGeometry(GeoIdList[0]);
    const Part::Geometry* geo2 = getGeometry(GeoIdList[1]);

    if (geo1->is<Part::GeomLineSegment>()
        && geo2->is<Part::GeomLineSegment>()) {
        auto* lineSeg1 = static_cast<const Part::GeomLineSegment*>(geo1);
        auto* lineSeg2 = static_cast<const Part::GeomLineSegment*>(geo2);

        Base::Vector3d midPnt1 = (lineSeg1->getStartPoint() + lineSeg1->getEndPoint()) / 2;
        Base::Vector3d midPnt2 = (lineSeg2->getStartPoint() + lineSeg2->getEndPoint()) / 2;
        return fillet(GeoIdList[0], GeoIdList[1], midPnt1, midPnt2, radius, trim, createCorner, chamfer);
    }
    // TODO: Find a way to eval two correct points that can be bound by an arc created using
    // Here is an attempt for reference, works some times but it depends on the curves, their direction, etc
    // else if (geo1->isDerivedFrom<Part::GeomCurve>()
    //     && geo2->isDerivedFrom<Part::GeomCurve>()) {
    //     auto* lineSeg1 = static_cast<const Part::GeomCurve*>(geo1);
    //     auto* lineSeg2 = static_cast<const Part::GeomCurve*>(geo2);

    //     // .05 is a safe bet, if the param becomes too large, it won't be able to form the fillet's arc
    //     Base::Vector3d midPnt1 = lineSeg1->pointAtParameter(.05f);
    //     Base::Vector3d midPnt2 = lineSeg2->pointAtParameter(.05f);
    //     return fillet(GeoIdList[0], GeoIdList[1], midPnt1, midPnt2, radius, trim, createCorner, chamfer);
    // }

    return -1;
}

int SketchObject::fillet(int GeoId1, int GeoId2, const Base::Vector3d& refPnt1,
                         const Base::Vector3d& refPnt2, double radius, bool trim, bool createCorner, bool chamfer)
{
    if (GeoId1 < 0 || GeoId1 > getHighestCurveIndex() || GeoId2 < 0 || GeoId2 > getHighestCurveIndex()) {
        return -1;
    }

    // two geometries can only get filleted if they have a coincident point
    std::vector<int> GeoIdList;
    std::vector<PointPos> PosIdList;
    getDirectlyCoincidentPoints(GeoId1, GeoId2, GeoIdList, PosIdList);

    if (GeoIdList.size() < 1) {
        return -1;
    }

    // If either of the two input lines are locked, don't try to trim since it won't work anyway
    const Part::Geometry* geo1 = getGeometry(GeoId1);
    const Part::Geometry* geo2 = getGeometry(GeoId2);
    if (trim && (GeometryFacade::getBlocked(geo1) || GeometryFacade::getBlocked(geo2))) {
        trim = false;
    }

    int pos1 = 0;
    int pos2 = 0;
    bool reverse = false;
    Base::Vector3d cornerPoint;
    std::unique_ptr<Part::GeomArcOfCircle> arc(createFilletGeometry(geo1, geo2, refPnt1, refPnt2, radius, pos1, pos2, reverse, cornerPoint));
    if (!arc) {
        return -1;
    }

    int filletId = addGeometry(arc.get());
    if (filletId < 0) {
        return -1;
    }

    PointPos PosId1 = static_cast<PointPos>(pos1);
    PointPos PosId2 = static_cast<PointPos>(pos2);
    PointPos filletPosId1 = PointPos::none;
    PointPos filletPosId2 = PointPos::none;

    Base::Vector3d p1 = arc->getStartPoint(true);
    Base::Vector3d p2 = arc->getEndPoint(true);

    if(!reverse) {
        std::swap(p1, p2);
    }

    if (trim) {
        // Stays undefined/-1 if createCorner=false
        int newId1 = -1, newId2 = -1;
        bool swapped1 = false, swapped2 = false;
        // When keeping the corner, we split the original geometry into two and turn the two geometries that form the corner into construction geometry.
        // To keep the indices stable, we have to swap the ids:
        //  * GeoId1,2 are the non-construction geometries
        //  * newId1,2 are the construction geometries, relative to GeoId1,2
        //  * swapped1,2 indicates if the construction geometries and original ones had to be swapped
        // This is because SketchObject::split pushes the new geometry, which is created on the PointPos::end side of the curve, at the end of SketchObject::Geometry

        // The resulting ids from this operation:
        // [GeoId1, GeoId2, ...]
        // -> fillet between GeoId1 and GeoId2 with createCorner=true
        // Will result in these ids:
        // [GeoId1, GeoId2, ..., arc, newId1, newId2]

        if (createCorner) {
            // If the lines don't intersect, there's no original corner to work with so
            // don't try to transfer the constraints. But we should delete line length and equal
            // constraints and constraints on the affected endpoints because they're about
            // to move unpredictably.
            if (!arePointsCoincident(GeoId1, PosId1, GeoId2, PosId2)) {
                // Delete constraints on the endpoints
                delConstraintOnPoint(GeoId1, PosId1, false);
                delConstraintOnPoint(GeoId2, PosId2, false);

                // Delete line length and equal constraints
                const std::vector<Constraint*>& constraints = this->Constraints.getValues();
                std::vector<int> deleteme;
                for (int i = 0; i < int(constraints.size()); i++) {
                    const Constraint* c = constraints[i];
                    if (c->Type == Sketcher::Distance || c->Type == Sketcher::Equal) {
                        bool line1 = c->First == GeoId1 && c->FirstPos == PointPos::none;
                        bool line2 = c->First == GeoId2 && c->FirstPos == PointPos::none;
                        if (line1 || line2) {
                            deleteme.push_back(i);
                        }
                    }
                }
                delConstraints(std::move(deleteme), DeleteOption::NoSolve);
            }
            else {
                // Add construction geometry

                auto splitCornerPiece = [&](int& geoId, PointPos pos, const Base::Vector3d& point) -> std::pair<int, bool>
                {
                    int highest = getHighestCurveIndex();

                    split(geoId, point);
                    int newId = highest + 1;

                    const bool needsSwap = pos == PointPos::start;
                    if(needsSwap) {
                        std::swap(newId, geoId);
                    }

                    setConstruction(newId, true);

                    return {newId, needsSwap};
                };

                std::tie(newId1, swapped1) = splitCornerPiece(GeoId1, PosId1, p1);
                std::tie(newId2, swapped2) = splitCornerPiece(GeoId2, PosId2, p2);
            }
        }
        else {
            delConstraintOnPoint(GeoId1, PosId1, false);
            delConstraintOnPoint(GeoId2, PosId2, false);
        }

        filletPosId1 = reverse ? PointPos::start : PointPos::end;
        filletPosId2 = reverse ? PointPos::end : PointPos::start;
        moveGeometry(GeoId1, PosId1, p1, false, true);
        moveGeometry(GeoId2, PosId2, p2, false, true);

        auto makeTangent = [&](int firstGeoId, PointPos firstPosId,
                               int secondGeoId, PointPos secondPosId) {
            auto tangent = std::make_unique<Sketcher::Constraint>();
            tangent->Type = Sketcher::Tangent;

        #ifdef SKETCHER_CONSTRAINT_USE_LEGACY_ELEMENTS
            tangent->First = firstGeoId;
            tangent->FirstPos = firstPosId;
            tangent->Second = secondGeoId;
            tangent->SecondPos = secondPosId;
        #else
            tangent->addElement(GeoElementId(firstGeoId, firstPosId));
            tangent->addElement(GeoElementId(secondGeoId, secondPosId));
        #endif

            addConstraint(std::move(tangent));
        };

        makeTangent(GeoId1, PosId1, filletId, filletPosId1);
        makeTangent(GeoId2, PosId2, filletId, filletPosId2);

        if (createCorner) {
            // Swapping the geometry and construction geometry to keep the ids stable
            const auto swapGeometries = [&](int geoId, int newId, bool swapped) {
                if(swapped) {
                    return;
                }

                // the original geometry should keep its id, the new construction geometry should be added at the end
                // because split splits depending on the endpoints, we cannot control which geometry keeps the original id and which one get added at the end.
                // So at this point, we swap the geometries and associated constraints to keep the order correct

                const auto& allConstraints = this->Constraints.getValues();

                const int tempGeoId = getHighestCurveIndex() + 1;

                for (auto* constraint : allConstraints) {
                    constraint->substituteIndex(geoId, tempGeoId);
                    constraint->substituteIndex(newId, geoId);
                    constraint->substituteIndex(tempGeoId, newId);
                }

                Geometry.swapValues(geoId, newId);
            };

            swapGeometries(GeoId1, newId1, swapped1);
            swapGeometries(GeoId2, newId2, swapped2);
        }
    }

    if (chamfer) {
        auto line = std::make_unique<Part::GeomLineSegment>();
        line->setPoints(p1, p2);
        int lineGeoId = addGeometry(std::move(line));

        auto coinc1 = std::make_unique<Sketcher::Constraint>();
        auto coinc2 = std::make_unique<Sketcher::Constraint>();

        coinc1->Type = Sketcher::Coincident;
        coinc2->Type = Sketcher::Coincident;
#ifdef SKETCHER_CONSTRAINT_USE_LEGACY_ELEMENTS
        coinc1->First = lineGeoId;
        coinc1->FirstPos = filletPosId1;

        coinc2->First = lineGeoId;
        coinc2->FirstPos = filletPosId2;
#else
        coinc1->addElement(GeoElementId(lineGeoId, filletPosId1));
        coinc2->addElement(GeoElementId(lineGeoId, filletPosId2));
#endif

#ifdef SKETCHER_CONSTRAINT_USE_LEGACY_ELEMENTS
        coinc1->Second = filletId;
        coinc1->SecondPos = PointPos::start;

        coinc2->Second = filletId;
        coinc2->SecondPos = PointPos::end;
#else
        coinc1->addElement(GeoElementId(filletId, PointPos::start));
        coinc2->addElement(GeoElementId(filletId, PointPos::end));
#endif

        addConstraint(std::move(coinc1));
        addConstraint(std::move(coinc2));

        setConstruction(filletId, true);
    }

    // if we do not have a recompute after the geometry creation, the sketch must be solved to
    // update the DoF of the solver
    if (noRecomputes) {
        solve();
    }

    return 0;
}

int SketchObject::extend(int GeoId, double increment, PointPos endpoint)
{
    if (GeoId < 0 || GeoId > getHighestCurveIndex())
        return -1;

    const std::vector<Part::Geometry*>& geomList = getInternalGeometry();
    Part::Geometry* geom = geomList[GeoId];
    int retcode = -1;
    if (geom->is<Part::GeomLineSegment>()) {
        auto* seg = static_cast<Part::GeomLineSegment*>(geom);
        Base::Vector3d startVec = seg->getStartPoint();
        Base::Vector3d endVec = seg->getEndPoint();
        if (endpoint == PointPos::start) {
            Base::Vector3d newPoint = startVec - endVec;
            double scaleFactor = newPoint.Length() + increment;
            newPoint.Normalize();
            newPoint.Scale(scaleFactor, scaleFactor, scaleFactor);
            newPoint = newPoint + endVec;
            retcode = moveGeometry(GeoId, Sketcher::PointPos::start, newPoint, false, true);
        }
        else if (endpoint == PointPos::end) {
            Base::Vector3d newPoint = endVec - startVec;
            double scaleFactor = newPoint.Length() + increment;
            newPoint.Normalize();
            newPoint.Scale(scaleFactor, scaleFactor, scaleFactor);
            newPoint = newPoint + startVec;
            retcode = moveGeometry(GeoId, Sketcher::PointPos::end, newPoint, false, true);
        }
    }
    else if (geom->is<Part::GeomArcOfCircle>()) {
        auto* arc = static_cast<Part::GeomArcOfCircle*>(geom);
        double startArc, endArc;
        arc->getRange(startArc, endArc, true);
        if (endpoint == PointPos::start) {
            arc->setRange(startArc - increment, endArc, true);
            retcode = 0;
        }
        else if (endpoint == PointPos::end) {
            arc->setRange(startArc, endArc + increment, true);
            retcode = 0;
        }
    }
    if (retcode == 0 && noRecomputes) {
        solve();
    }
    return retcode;
}

// FreeCAD-CH (ops#640): the GeoIds of the geometry of ExternalGeometry's entries marked implicit (a
// constraint's helper link, a model pick, ops#634). Onshape's model edges in the sketch plane, not
// Use'd, bound neither Trim nor Extend (GA3-25)
static std::set<int> implicitHelperGeoIds(const SketchObject& obj, const std::map<long, int>& geoMap)
{
    std::set<int> helpers;
    for (int entry = 0; entry < obj.ExternalGeometry.getSize(); ++entry) {
        if (!obj.isImplicitExternal(entry)) {
            continue;
        }
        for (long id : obj.externalGeometryIds(entry)) {
            auto it = geoMap.find(id);
            if (it != geoMap.end()) {
                helpers.insert(-it->second - 1);  // ExternalGeo[k] has GeoId -1 - k
            }
        }
    }
    return helpers;
}

// FreeCAD-CH (Onshape's Extend, ops#640; see the header)
double SketchObject::seekExtendBoundary(
    int GeoId,
    PointPos endpoint,
    double increment,
    int& boundaryGeoId,
    PointPos& boundaryPos
) const
{
    boundaryGeoId = GeoEnum::GeoUndef;
    boundaryPos = PointPos::none;
    if (GeoId < 0 || GeoId > getHighestCurveIndex() || !(increment > 0)
        || (endpoint != PointPos::start && endpoint != PointPos::end)) {
        return increment;
    }
    const auto* seg = dynamic_cast<const Part::GeomLineSegment*>(getGeometry(GeoId));
    if (!seg) {
        return increment;
    }
    const Base::Vector3d end = endpoint == PointPos::start ? seg->getStartPoint() : seg->getEndPoint();
    Base::Vector3d dir = end - (endpoint == PointPos::start ? seg->getEndPoint() : seg->getStartPoint());
    if (dir.Length() < Precision::Confusion()) {
        return increment;
    }
    dir.Normalize();

    // as Trim's (arePointsWithinPrecision): a point within this of the path is on it
    const double tol = 500 * Precision::Confusion();
    double best = increment + tol;  // a boundary at the click (within tol) is reached
    // a candidate at distance t along the path from the old end: the nearest wins, and at the
    // same distance a point (an end point, a sketch point) wins over a curve's crossing
    auto consider = [&](const Base::Vector3d& p, int geoId, PointPos pos) {
        const Base::Vector3d v = p - end;
        const double t = v * dir;
        if (t <= tol || (v - dir * t).Length() > tol) {
            return;  // behind or at the old end (a curve through it doesn't stop it), or off the path
        }
        const bool point = pos != PointPos::none;
        const bool first = boundaryGeoId == GeoEnum::GeoUndef;
        const bool samePlace = std::abs(t - best) <= tol;
        if ((first && t <= best) || (!first && t < best - tol)
            || (!first && samePlace && point && boundaryPos == PointPos::none)) {
            best = t;
            boundaryGeoId = geoId;
            boundaryPos = pos;
        }
    };

    // a constraint's helper link (a model pick, ops#634) is not Use'd: it doesn't stop it
    const std::set<int> helpers = implicitHelperGeoIds(*this, externalGeoMap);

    gp_Pln plane(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1));
    Handle(Geom2d_Curve) path = new Geom2d_TrimmedCurve(
        new Geom2d_Line(gp_Pnt2d(end.x, end.y), gp_Dir2d(dir.x, dir.y)),
        0.0,
        increment + tol
    );
    std::vector<int> ids;
    for (int id = 0; id <= getHighestCurveIndex(); ++id) {
        ids.push_back(id);
    }
    // not the origin axes (GeoIds -1 and -2): Onshape's don't stop it
    for (int id = GeoEnum::RefExt; id >= -getExternalGeometryCount(); --id) {
        ids.push_back(id);
    }
    for (int id : ids) {
        const Part::Geometry* geo = getGeometry(id);
        if (id == GeoId || !geo || helpers.count(id) != 0
            || GeometryFacade::isInternalAligned(geo)) {
            continue;  // an ellipse's axes, a B-spline's poles and knots are the curve's own
        }
        if (geo->is<Part::GeomPoint>()) {
            consider(static_cast<const Part::GeomPoint*>(geo)->getPoint(), id, PointPos::start);
            continue;
        }
        if (geo->isDerivedFrom<Part::GeomBoundedCurve>()) {
            const auto* bounded = static_cast<const Part::GeomBoundedCurve*>(geo);
            consider(bounded->getStartPoint(), id, PointPos::start);
            consider(bounded->getEndPoint(), id, PointPos::end);
        }
        Handle(Geom_Curve) curve3d = Handle(Geom_Curve)::DownCast(geo->handle());
        if (curve3d.IsNull()) {
            continue;
        }
        try {
            Geom2dAPI_InterCurveCurve intersector(path, GeomAPI::To2d(curve3d, plane), 1.0e-12);
            for (int i = 1; i <= intersector.NbPoints(); ++i) {
                const gp_Pnt2d p = intersector.Point(i);
                consider(Base::Vector3d(p.X(), p.Y(), 0), id, PointPos::none);
            }
            // a collinear overlap: its first point (an end point, considered above, or the path's)
            const Geom2dInt_GInter& inter = intersector.Intersector();
            for (int i = 1; i <= inter.NbSegments(); ++i) {
                const IntRes2d_IntersectionSegment& overlap = inter.Segment(i);
                if (overlap.HasFirstPoint()) {
                    const gp_Pnt2d p = overlap.FirstPoint().Value();
                    consider(Base::Vector3d(p.X(), p.Y(), 0), id, PointPos::none);
                }
            }
        }
        catch (const Standard_Failure&) {
            continue;  // a curve OCCT can't intersect doesn't stop it
        }
    }
    if (boundaryGeoId == GeoEnum::GeoUndef) {
        return increment;
    }
    // a crossing at one of the boundary's end points is that point (a corner, a curve's end)
    if (boundaryPos == PointPos::none) {
        const Base::Vector3d at = end + dir * best;
        for (PointPos pos : {PointPos::start, PointPos::end}) {
            const Part::Geometry* geo = getGeometry(boundaryGeoId);
            if (geo->isDerivedFrom<Part::GeomBoundedCurve>()
                && (getPoint(boundaryGeoId, pos) - at).Length() < tol) {
                boundaryPos = pos;
                break;
            }
        }
    }
    return best;
}

int SketchObject::extendToBoundary(int GeoId, double increment, PointPos endpoint)
{
    int boundaryGeoId;
    PointPos boundaryPos;
    const double bounded = seekExtendBoundary(GeoId, endpoint, increment, boundaryGeoId, boundaryPos);
    if (boundaryGeoId == GeoEnum::GeoUndef) {
        return extend(GeoId, increment, endpoint);
    }
    // the end goes onto the boundary, and the constraint holds it there
    int retcode = extend(GeoId, bounded, endpoint);
    if (retcode != 0) {
        return retcode;
    }
    auto constraint = std::make_unique<Constraint>();
    constraint->First = GeoId;
    constraint->FirstPos = endpoint;
    constraint->Second = boundaryGeoId;
    if (boundaryPos == PointPos::none) {
        constraint->Type = Sketcher::PointOnObject;
    }
    else {
        constraint->Type = Sketcher::Coincident;
        constraint->SecondPos = boundaryPos;
    }
    addConstraint(std::move(constraint));
    if (noRecomputes) {
        solve();
    }
    return 0;
}

// clang-format on
bool SketchObject::seekTrimPoints(
    int GeoId,
    const Base::Vector3d& point,
    bool includeSketchAxes,
    int& GeoId1,
    Base::Vector3d& intersect1,
    int& GeoId2,
    Base::Vector3d& intersect2
)
{
    if (GeoId < 0 || GeoId > getHighestCurveIndex()) {
        return false;
    }

    auto geos = getCompleteGeometry();  // this includes the axes as GeomBoundedCurve

    // remove the axes since they aren't infinite lines and not all intersections will count
    geos.resize(geos.size() - 2);

    Part::GeomLine hAxis;
    Part::GeomLine vAxis;
    int hAxisIndex = -1;
    int vAxisIndex = -1;
    if (includeSketchAxes) {
        // re-add the axes as infinite lines
        hAxisIndex = static_cast<int>(geos.size());
        hAxis.setLine(Base::Vector3d(0, 0, 0), Base::Vector3d(1, 0, 0));
        geos.push_back(&hAxis);

        vAxisIndex = static_cast<int>(geos.size());
        vAxis.setLine(Base::Vector3d(0, 0, 0), Base::Vector3d(0, 1, 0));
        geos.push_back(&vAxis);
    }

    // FreeCAD-CH (Onshape GA3-25, GA3-25b, ops#640): a constraint's helper link (a model pick) bounds
    // no trim, and a point on the curve (a sketch point, a Use'd one) does. Part's search takes only
    // curves: a helper's entry is replaced by a point (which it skips), and each point on the curve
    // stands in as a short segment across the curve through it (the crossing is the point)
    const std::set<int> helpers = implicitHelperGeoIds(*this, externalGeoMap);
    Part::GeomPoint skipped;
    std::vector<std::unique_ptr<Part::GeomLineSegment>> standIns;
    std::map<int, int> standInGeoIds;  // index in geos -> the point's GeoId
    const auto* trimmed = getGeometry<Part::GeomCurve>(GeoId);
    const std::size_t ownCount = geos.size() - (includeSketchAxes ? 2 : 0);
    for (std::size_t i = 0; i < ownCount; ++i) {
        const int id = getGeoIdFromCompleteGeometryIndex(static_cast<int>(i));
        if (helpers.count(id) != 0) {
            geos[i] = &skipped;
            continue;
        }
        if (!trimmed || id == GeoId || !geos[i]->is<Part::GeomPoint>()
            || GeometryFacade::isInternalAligned(geos[i])) {
            continue;
        }
        const Base::Vector3d p = static_cast<const Part::GeomPoint*>(geos[i])->getPoint();
        double u;
        Base::Vector3d tangent;
        if (!trimmed->closestParameter(p, u) || (trimmed->pointAtParameter(u) - p).Length() > Precision::Confusion()
            || !trimmed->tangent(u, tangent)) {
            continue;
        }
        tangent.Normalize();
        const Base::Vector3d across(-tangent.y * 1e-4, tangent.x * 1e-4, 0);
        auto standIn = std::make_unique<Part::GeomLineSegment>();
        standIn->setPoints(p - across, p + across);
        standInGeoIds[static_cast<int>(geos.size())] = id;
        geos.push_back(standIn.get());
        standIns.push_back(std::move(standIn));
    }

    int localindex1, localindex2;

    // Not found in will be returned as -1, not as GeoUndef, Part WB is agnostic to the concept
    // of GeoUndef
    if (
        !Part2DObject::seekTrimPoints(geos, GeoId, point, localindex1, intersect1, localindex2, intersect2)
    ) {
        return false;
    }

    // invalid complete geometry indices are mapped to GeoUndef
    auto getGeoIdForIndex = [&](int index) {
        if (auto it = standInGeoIds.find(index); it != standInGeoIds.end()) {
            return it->second;
        }
        if (includeSketchAxes && index == hAxisIndex) {
            return Part::Part2DObject::H_Axis;
        }
        if (includeSketchAxes && index == vAxisIndex) {
            return Part::Part2DObject::V_Axis;
        }
        return getGeoIdFromCompleteGeometryIndex(index);
    };

    GeoId1 = getGeoIdForIndex(localindex1);
    GeoId2 = getGeoIdForIndex(localindex2);

    return true;
}

// given a geometry and a point, returns the corresponding parameter of the geometry point
// closest to the point. Wrapped around a try-catch so the calling operation can fail without
// throwing an exception.
bool getIntersectionParameter(const Part::Geometry* geo, const Base::Vector3d point, double& pointParam)
{
    const auto* curve = static_cast<const Part::GeomCurve*>(geo);

    try {
        curve->closestParameter(point, pointParam);
    }
    catch (Base::CADKernelError& e) {
        e.reportException();
        return false;
    }

    return true;
}

bool arePointsWithinPrecision(const Base::Vector3d& point1, const Base::Vector3d& point2)
{
    // From testing: 500x (or 0.000050) is needed in order to not falsely distinguish points
    // calculated with seekTrimPoints
    return ((point1 - point2).Length() < 500 * Precision::Confusion());
}

bool areParamsWithinApproximation(double param1, double param2)
{
    // From testing: 500x (or 0.000050) is needed in order to not falsely distinguish points
    // calculated with seekTrimPoints
    return (std::abs(param1 - param2) < Precision::PApproximation());
}

// returns true if the point defined by (GeoId1, pos1) can be considered to be coincident with
// point.
bool isPointAtPosition(const SketchObject* obj, int GeoId1, PointPos pos1, const Base::Vector3d& point)
{
    Base::Vector3d pp = obj->getPoint(GeoId1, pos1);

    return arePointsWithinPrecision(point, pp);
}

// Checks whether preexisting constraints must be converted to new constraints.
// Preexisting point on object constraints get converted to coincidents.
// Returns:
//     - The constraint that should be used to constraint GeoId and cuttingGeoId
std::unique_ptr<Constraint> transformPreexistingConstraintForTrim(
    const SketchObject* obj,
    const Constraint* constr,
    int GeoId,
    int cuttingGeoId,
    const Base::Vector3d& cutPointVec,
    int newGeoId,
    PointPos newPosId
)
{
    /* TODO: It is possible that the trimming entity has both a PointOnObject constraint to the
     * trimmed entity, and a simple Tangent constraint to the trimmed entity. In this case we
     * want to change to a single end-to-end tangency, i.e we want to ensure that constrType1
     * is set to Sketcher::Tangent, that the secondPos1 is captured from the PointOnObject,
     * and also make sure that the PointOnObject constraint is deleted.
     */
    // TODO: Symmetric and distance constraints (sometimes together) can be changed to something
    std::unique_ptr<Constraint> newConstr;
    if (cuttingGeoId == GeoEnum::GeoUndef || !constr->involvesGeoId(cuttingGeoId)
        || !constr->involvesGeoIdAndPosId(GeoId, PointPos::none)) {
        return newConstr;
    }
    switch (constr->Type) {
        case PointOnObject: {
            // we might want to transform this (and the new point-on-object constraints) into a
            // coincidence At this stage of the check the point has to be an end of
            // `cuttingGeoId` on the edge of `GeoId`.
            if (isPointAtPosition(obj, constr->First, constr->FirstPos, cutPointVec)) {
                // We already know the point-on-object is on the whole of GeoId
                newConstr.reset(constr->copy());
                newConstr->Type = Sketcher::Coincident;
                newConstr->Second = newGeoId;
                newConstr->SecondPos = newPosId;
            }
            break;
        }
        case Tangent:
        case Perpendicular: {
            // These may have to be turned into endpoint-to-endpoint or endpoint-to-edge
            // TODO: could there be tangent/perpendicular constraints not involving the trim
            // that are modified below?
            newConstr.reset(constr->copy());
            newConstr->substituteIndexAndPos(GeoId, PointPos::none, newGeoId, newPosId);
            // make sure the first position is a point
            if (newConstr->FirstPos == PointPos::none) {
                std::swap(newConstr->First, newConstr->Second);
                std::swap(newConstr->FirstPos, newConstr->SecondPos);
            }
            // there is no need for the third point if it exists
            newConstr->Third = GeoEnum::GeoUndef;
            newConstr->ThirdPos = PointPos::none;
            break;
        }
        default:
            break;
    }
    return newConstr;
}

std::unique_ptr<Constraint> getNewConstraintAtTrimCut(
    const SketchObject* obj,
    int cuttingGeoId,
    int cutGeoId,
    PointPos cutPosId,
    const Base::Vector3d& cutPointVec
)
{
    auto newConstr = std::make_unique<Sketcher::Constraint>();
    newConstr->First = cutGeoId;
    newConstr->FirstPos = cutPosId;
    newConstr->Second = cuttingGeoId;
    // FreeCAD-CH (ops#656): a closed cutting curve (a circle, an ellipse) has no ends: its point at
    // parameter 0 is not a "start" to be coincident with (that made a malformed constraint).
    const auto* cutting = obj->getGeometry(cuttingGeoId);
    const bool cuttingHasEnds = cutting && !SketchObject::isClosedCurve(cutting);
    if (cuttingHasEnds && isPointAtPosition(obj, cuttingGeoId, PointPos::start, cutPointVec)) {
        newConstr->Type = Sketcher::Coincident;
        newConstr->SecondPos = PointPos::start;
    }
    else if (cuttingHasEnds && isPointAtPosition(obj, cuttingGeoId, PointPos::end, cutPointVec)) {
        newConstr->Type = Sketcher::Coincident;
        newConstr->SecondPos = PointPos::end;
    }
    else {
        // Points are sufficiently far apart: use point-on-object
        newConstr->Type = Sketcher::PointOnObject;
        newConstr->SecondPos = PointPos::none;
    }
    return newConstr;
}

// FreeCAD-CH (ops#656): the constraints that keep the pieces of one cut curve behaving as that curve:
// arcs of one circle or ellipse keep one size (Equal; they already share the centre), the pieces of a
// line stay collinear (Tangent between lines). Without them a radius or a distance on the old curve
// governs only its first piece (probe P3). Split's pieces
// are `joined` end to end: for arcs of one circle that joint (with the shared centre) already makes the
// radii equal, and for lines its tangency makes them collinear.
static void addTiesBetweenPieces(
    const Part::Geometry* oldGeo,
    const std::vector<int>& newIds,
    bool joined,
    std::vector<Constraint*>& ties
)
{
    if (newIds.size() < 2) {
        return;
    }
    auto tie = [&](ConstraintType type, PointPos firstPos, PointPos secondPos) {
        auto* c = new Constraint();
        c->Type = type;
        c->First = newIds.front();
        c->FirstPos = firstPos;
        c->Second = newIds.back();
        c->SecondPos = secondPos;
        ties.push_back(c);
    };
    const bool circular = oldGeo->isDerivedFrom<Part::GeomCircle>()
        || oldGeo->isDerivedFrom<Part::GeomArcOfCircle>();
    const bool elliptic = oldGeo->isDerivedFrom<Part::GeomEllipse>()
        || oldGeo->isDerivedFrom<Part::GeomArcOfEllipse>();
    if ((circular && !joined) || elliptic) {
        tie(Equal, PointPos::none, PointPos::none);
    }
    if (elliptic && !joined) {
        // Equal radii and a shared centre leave an ellipse arc free to turn about the centre: an end
        // of the second piece on the first piece's ellipse holds its orientation (one equation).
        auto* c = new Constraint();
        c->Type = PointOnObject;
        c->First = newIds.back();
        c->FirstPos = PointPos::start;
        c->Second = newIds.front();
        c->SecondPos = PointPos::none;
        ties.push_back(c);
    }
    else if (!joined && oldGeo->is<Part::GeomLineSegment>()) {
        tie(Tangent, PointPos::none, PointPos::none);
    }
}

// FreeCAD-CH (ops#656): whether two curves lie on one carrier (the same circle, ellipse or infinite
// line), as the pieces Split joins end to end do.
static bool onSameCarrier(const Part::Geometry* a, const Part::Geometry* b)
{
    constexpr double tol = 1e-7;
    auto circle = [](const Part::Geometry* g, Base::Vector3d& c, double& r) {
        if (const auto* arc = dynamic_cast<const Part::GeomArcOfCircle*>(g)) {
            c = arc->getCenter();
            r = arc->getRadius();
            return true;
        }
        return false;
    };
    Base::Vector3d ca, cb;
    double ra {}, rb {};
    if (circle(a, ca, ra) && circle(b, cb, rb)) {
        return (ca - cb).Length() < tol && std::abs(ra - rb) < tol;
    }
    const auto* la = dynamic_cast<const Part::GeomLineSegment*>(a);
    const auto* lb = dynamic_cast<const Part::GeomLineSegment*>(b);
    if (la && lb) {
        const Base::Vector3d s = la->getStartPoint();
        const Base::Vector3d d = (la->getEndPoint() - s).Normalize();
        auto off = [&](const Base::Vector3d& p) {
            const Base::Vector3d v = p - s;
            return (v - d * v.Dot(d)).Length();
        };
        return off(lb->getStartPoint()) < tol && off(lb->getEndPoint()) < tol;
    }
    return false;
}

// FreeCAD-CH (ops#656): where the rest of the sketch already implies a tie, the sketch has become
// redundant. The solver may name the tie or one of the user's constraints (it prefers to name the one
// that removes fewer degrees of freedom), so take the ties out one at a time, last first, and keep each
// one out only if that lowers the number of redundant constraints without freeing anything (a two-equation
// tie can be only half implied). A redundancy the sketch had before the cut stays, and the ties stay with
// it: loud, never a silent loss. `tieIndices` are constraint indices (0-based).
static void dropRedundantTies(SketchObject* obj, std::vector<int> tieIndices)
{
    if (tieIndices.empty()) {
        return;
    }
    obj->solve();
    std::ranges::sort(tieIndices, std::greater<>());
    for (int i : tieIndices) {
        const size_t before = obj->getLastRedundant().size();
        const int dofBefore = obj->getLastDoF();
        if (before == 0) {
            return;
        }
        std::unique_ptr<Constraint> tie(obj->Constraints.getValues()[i]->copy());
        obj->delConstraint(i, DeleteOption::NoSolve);
        obj->solve();
        if (obj->getLastRedundant().size() >= before || obj->getLastDoF() > dofBefore) {
            // not this tie: put it back (at the end; the ties still to try have lower indices)
            obj->addConstraint(std::move(tie));
            obj->solve();
        }
    }
}

// FreeCAD-CH (ops#656): say which constraints a cut released because they have no equivalent on the
// pieces (an arc's length, an equal length of lines), so the loss is never silent. Numbers as the
// constraint list shows them (1-based).
static void warnReleased(const SketchObject* obj, const char* tool, const std::vector<int>& released)
{
    if (released.empty()) {
        return;
    }
    const auto& constraints = obj->Constraints.getValues();
    std::string list;
    for (int i : released) {
        list += (list.empty() ? "" : ", ") + std::to_string(i + 1);
        if (i >= 0 && i < int(constraints.size()) && !constraints[i]->Name.empty()) {
            list += " (" + constraints[i]->Name + ")";
        }
    }
    Base::Console().warning(
        obj->getFullLabel(),
        "%s removed constraint(s) %s (numbered as before it): they have no equivalent on the pieces.\n",
        tool,
        list.c_str()
    );
}

bool isGeoIdAllowedForTrim(const SketchObject* obj, int GeoId)
{
    const auto* geo = obj->getGeometry(GeoId);

    return GeoId >= 0 && GeoId <= obj->getHighestCurveIndex()
        && GeometryFacade::isInternalType(geo, InternalType::None);
}

bool getParamLimitsOfNewGeosForTrim(
    const SketchObject* obj,
    int GeoId,
    std::array<int, 2>& cuttingGeoIds,
    std::array<Base::Vector3d, 2>& cutPoints,
    std::vector<std::pair<double, double>>& paramsOfNewGeos
)
{
    const auto* geoAsCurve = obj->getGeometry<Part::GeomCurve>(GeoId);
    double firstParam = geoAsCurve->getFirstParameter();
    double lastParam = geoAsCurve->getLastParameter();
    double cut0Param {firstParam}, cut1Param {lastParam};

    bool allParamsFound = getIntersectionParameter(geoAsCurve, cutPoints[0], cut0Param)
        && getIntersectionParameter(geoAsCurve, cutPoints[1], cut1Param);
    if (!allParamsFound) {
        return false;
    }

    if (!obj->isClosedCurve(geoAsCurve) && areParamsWithinApproximation(firstParam, cut0Param)) {
        cuttingGeoIds[0] = GeoEnum::GeoUndef;
    }

    if (!obj->isClosedCurve(geoAsCurve) && areParamsWithinApproximation(lastParam, cut1Param)) {
        cuttingGeoIds[1] = GeoEnum::GeoUndef;
    }

    size_t numUndefs = std::count(cuttingGeoIds.begin(), cuttingGeoIds.end(), GeoEnum::GeoUndef);

    if (numUndefs == 0 && arePointsWithinPrecision(cutPoints[0], cutPoints[1])) {
        // If both points are detected and are coincident, deletion is the only option.
        paramsOfNewGeos.clear();
        return true;
    }

    paramsOfNewGeos.assign(2 - numUndefs, {firstParam, lastParam});

    if (paramsOfNewGeos.empty()) {
        return true;
    }

    if (obj->isClosedCurve(geoAsCurve)) {
        paramsOfNewGeos.pop_back();
    }

    if (cuttingGeoIds[0] != GeoEnum::GeoUndef) {
        paramsOfNewGeos.front().second = cut0Param;
    }
    if (cuttingGeoIds[1] != GeoEnum::GeoUndef) {
        paramsOfNewGeos.back().first = cut1Param;
    }

    return true;
}

void createArcsFromGeoWithLimits(
    const Part::GeomCurve* geo,
    const std::vector<std::pair<double, double>>& paramsOfNewGeos,
    std::vector<Part::Geometry*>& newGeos
)
{
    for (auto& [u1, u2] : paramsOfNewGeos) {
        auto newGeo = static_cast<const Part::GeomCurve*>(geo)->createArc(u1, u2);
        assert(newGeo);
        newGeos.emplace_back(newGeo);
    }
}

void createNewConstraintsForTrim(
    const SketchObject* obj,
    const int GeoId,
    const std::array<int, 2>& cuttingGeoIds,
    const std::array<Base::Vector3d, 2>& cutPoints,
    const std::vector<int>& newIds,
    const std::vector<const Part::Geometry*> newGeos,
    std::vector<int>& idsOfOldConstraints,
    std::vector<Constraint*>& newConstraints,
    std::set<int, std::greater<>>& geoIdsToBeDeleted,
    std::map<Constraint*, int>& newToOldConstraintMap,
    bool piecesTied,
    std::vector<Constraint*>& carrierTies,
    std::vector<int>& released
)
{
    const auto& allConstraints = obj->Constraints.getValues();

    bool isPoint1ConstrainedOnGeoId1 = false;
    bool isPoint2ConstrainedOnGeoId2 = false;

    const auto* trimmedGeo = obj->getGeometry(GeoId);
    const bool isTrimmedGeoConic = trimmedGeo
        && (trimmedGeo->isDerivedFrom<Part::GeomConic>()
            || trimmedGeo->isDerivedFrom<Part::GeomArcOfConic>());

    for (const auto& oldConstrId : idsOfOldConstraints) {
        // trim-specific changes first
        const Constraint* con = allConstraints[oldConstrId];
        if (con->Type == InternalAlignment) {
            if (isTrimmedGeoConic) {
                auto* newCon = con->copy();
                newCon->Second = newIds.front();
                newConstraints.push_back(newCon);
                newToOldConstraintMap[newConstraints.back()] = oldConstrId;
            }
            else {
                geoIdsToBeDeleted.insert(con->First);
            }
            continue;
        }
        if (auto newConstr = transformPreexistingConstraintForTrim(
                obj,
                con,
                GeoId,
                cuttingGeoIds[0],
                cutPoints[0],
                newIds.front(),
                PointPos::end
            )) {
            newConstraints.push_back(newConstr.release());
            newToOldConstraintMap[newConstraints.back()] = oldConstrId;  // Map new to old
            isPoint1ConstrainedOnGeoId1 = true;
            continue;
        }
        if (auto newConstr = transformPreexistingConstraintForTrim(
                obj,
                con,
                GeoId,
                cuttingGeoIds[1],
                cutPoints[1],
                newIds.back(),
                PointPos::start
            )) {
            newConstraints.push_back(newConstr.release());
            newToOldConstraintMap[newConstraints.back()] = oldConstrId;  // Map new to old
            isPoint2ConstrainedOnGeoId2 = true;
            continue;
        }
        // We have already transferred all constraints on endpoints to the new pieces.
        // If there is still any left, this means one of the remaining pieces was degenerate.
        if (!(con->Type == Angle || con->involvesGeoIdAndPosId(GeoId, PointPos::none))) {
            // FreeCAD-CH (ops#656): an end that is cut away may be the joint Split made to the other
            // piece of a line, the only thing that kept the two collinear. An end-to-end Tangent of two
            // lines says "collinear" whoever made it, so it is kept as an edge-to-edge (collinear)
            // Tangent. Arcs are left alone: Split's joint of two arcs looks the same as two arcs a user
            // drew meeting at a common centre, and a user's polyline vertex (a Coincident) ties nothing.
            const bool endToEnd = con->First != con->Second && con->FirstPos != PointPos::none
                && con->FirstPos != PointPos::mid && con->SecondPos != PointPos::none
                && con->SecondPos != PointPos::mid;
            const int other = con->First == GeoId ? con->Second : con->First;
            const auto* otherGeo = other >= 0 ? obj->getGeometry(other) : nullptr;
            bool splitJoint = false;
            if (endToEnd && otherGeo && trimmedGeo->is<Part::GeomLineSegment>()) {
                splitJoint = con->Type == Tangent;
            }
            if (splitJoint && onSameCarrier(trimmedGeo, otherGeo)) {
                auto* tie = new Constraint();
                tie->Type = Tangent;
                tie->First = newIds.front();
                tie->Second = other;
                carrierTies.push_back(tie);
            }
            continue;
        }
        // constraint has not yet been changed
        size_t sizeBefore = newConstraints.size();
        // FreeCAD-CH (ops#656): tied pieces (collinear lines) take a line's orientation once.
        if (!obj->deriveConstraintsForPieces(GeoId, newIds, newGeos, con, newConstraints, piecesTied)) {
            released.push_back(oldConstrId);
        }
        // Map all newly added derived constraints to the old ID
        for (size_t i = sizeBefore; i < newConstraints.size(); ++i) {
            newToOldConstraintMap[newConstraints[i]] = oldConstrId;
        }
    }

    // Add point-on-object/coincidence constraints with the newly exposed points.
    // This will need to account for the constraints that were already converted
    // to coincident or end-to-end tangency/perpendicularity.
    // TODO: Tangent/perpendicular not yet covered

    if (cuttingGeoIds[0] != GeoEnum::GeoUndef && !isPoint1ConstrainedOnGeoId1) {
        newConstraints.emplace_back(
            getNewConstraintAtTrimCut(obj, cuttingGeoIds[0], newIds.front(), PointPos::end, cutPoints[0])
                .release()
        );
    }

    if (cuttingGeoIds[1] != GeoEnum::GeoUndef && !isPoint2ConstrainedOnGeoId2) {
        newConstraints.emplace_back(
            getNewConstraintAtTrimCut(obj, cuttingGeoIds[1], newIds.back(), PointPos::start, cutPoints[1])
                .release()
        );
    }
}

int SketchObject::trim(int GeoId, const Base::Vector3d& point, bool includeSketchAxes)
{
    if (!isGeoIdAllowedForTrim(this, GeoId)) {
        return -1;
    }
    // Remove internal geometry beforehand for now
    // FIXME: we should be able to transfer these to new curves smoothly
    // auto geo = getGeometry(GeoId);
    const auto* geoAsCurve = getGeometry<Part::GeomCurve>(GeoId);

    if (geoAsCurve == nullptr) {
        return -1;
    }

    bool isOriginalCurveConstruction = GeometryFacade::getConstruction(geoAsCurve);
    bool isOriginalCurveClosed = isClosedCurve(geoAsCurve);

    //******************* Step A => Detection of intersection - Common to all Geometries
    //****************************************//
    // GeoIds intersecting the curve around `point`
    std::array<int, 2> cuttingGeoIds {GeoEnum::GeoUndef, GeoEnum::GeoUndef};
    // Points at the intersection
    std::array<Base::Vector3d, 2> cutPoints;

    // Using SketchObject wrapper, as Part2DObject version returns GeoId = -1 when intersection
    // not found, which is wrong for a GeoId (axis). seekTrimPoints returns:
    // - For a parameter associated with "point" between an intersection and the end point
    // (non-periodic case) cuttingGeoIds[0] != GeoUndef and cuttingGeoIds[1] == GeoUndef
    // - For a parameter associated with "point" between the start point and an intersection
    // (non-periodic case) cuttingGeoIds[1] != GeoUndef and cuttingGeoIds[0] == GeoUndef
    // - For a parameter associated with "point" between two intersection points,
    // cuttingGeoIds[0]
    // != GeoUndef and cuttingGeoIds[1] != GeoUndef
    //
    // FirstParam < point1param < point2param < LastParam
    if (!SketchObject::seekTrimPoints(
            GeoId,
            point,
            includeSketchAxes,
            cuttingGeoIds[0],
            cutPoints[0],
            cuttingGeoIds[1],
            cutPoints[1]
        )) {
        // If no suitable trim points are found, then trim defaults to deleting the geometry
        delGeometry(GeoId, DeleteOption::IncludeInternalGeometry);
        return 0;
    }

    // TODO: find trim parameters
    std::vector<std::pair<double, double>> paramsOfNewGeos;
    paramsOfNewGeos.reserve(2);
    if (!getParamLimitsOfNewGeosForTrim(this, GeoId, cuttingGeoIds, cutPoints, paramsOfNewGeos)) {
        return -1;
    }

    //******************* Step B => Creation of new geometries
    //****************************************//
    std::vector<int> newIds;
    std::vector<Part::Geometry*> newGeos;
    std::vector<const Part::Geometry*> newGeosAsConsts;
    std::map<Constraint*, int> newToOldConstraintMap;

    switch (paramsOfNewGeos.size()) {
        case 0: {
            delGeometry(GeoId, DeleteOption::IncludeInternalGeometry);
            return 0;
        }
        case 1: {
            newIds.push_back(GeoId);
            break;
        }
        case 2: {
            newIds.push_back(GeoId);
            newIds.push_back(getHighestCurveIndex() + 1);
            break;
        }
        default: {
            return -1;
        }
    }

    createArcsFromGeoWithLimits(geoAsCurve, paramsOfNewGeos, newGeos);
    for (const auto* geo : newGeos) {
        newGeosAsConsts.push_back(geo);
    }

    //******************* Step C => Creation of new constraints
    //****************************************//
    // Now that we have the new curves, change constraints as needed
    // Some are covered with `deriveConstraintsForPieces`, others are specific to trim
    // FIXME: We are using non-smart pointers since that's what's needed in `addConstraints`.
    const auto& allConstraints = this->Constraints.getValues();
    std::vector<Constraint*> newConstraints;
    std::vector<int> idsOfOldConstraints;
    std::set<int, std::greater<>> geoIdsToBeDeleted;
    getConstraintIndices(GeoId, idsOfOldConstraints);
    // remove the constraints that we want to manually transfer
    // We could transfer beforehand but in case of exception that transfer is permanent
    if (!isOriginalCurveClosed) {
        std::erase_if(idsOfOldConstraints, [&GeoId, &allConstraints, &cuttingGeoIds](const auto& i) {
            auto* constr = allConstraints[i];
            bool involvesStart = constr->involvesGeoIdAndPosId(GeoId, PointPos::start);
            bool involvesEnd = constr->involvesGeoIdAndPosId(GeoId, PointPos::end);
            bool keepStart = cuttingGeoIds[0] != GeoEnum::GeoUndef;
            bool keepEnd = cuttingGeoIds[1] != GeoEnum::GeoUndef;
            bool involvesBothButNotBothKept = involvesStart && involvesEnd && !(keepStart && keepEnd);
            return !involvesBothButNotBothKept
                && ((involvesStart && keepStart) || (involvesEnd && keepEnd));
        });
    }
    std::erase_if(idsOfOldConstraints, [&GeoId, &allConstraints](const auto& i) {
        return (allConstraints[i]->involvesGeoIdAndPosId(GeoId, PointPos::mid));
    });

    // FreeCAD-CH (ops#656): the two pieces of a line are tied collinear below.
    const bool piecesTied = newIds.size() > 1 && geoAsCurve->is<Part::GeomLineSegment>();
    std::vector<Constraint*> carrierTies;
    std::vector<int> released;
    createNewConstraintsForTrim(
        this,
        GeoId,
        cuttingGeoIds,
        cutPoints,
        newIds,
        newGeosAsConsts,
        idsOfOldConstraints,
        newConstraints,
        geoIdsToBeDeleted,
        newToOldConstraintMap,
        piecesTied,
        carrierTies,
        released
    );

    //******************* Step D => Replacing geometries and constraints
    //****************************************//

    // Constraints related to start/mid/end points of original
    [[maybe_unused]] auto constrainAsEqual = [this](int GeoId1, int GeoId2) {
        auto newConstr = std::make_unique<Sketcher::Constraint>();

        // Build Constraints associated with new pair of arcs
        newConstr->Type = Sketcher::Equal;
        newConstr->First = GeoId1;
        newConstr->FirstPos = Sketcher::PointPos::none;
        newConstr->Second = GeoId2;
        newConstr->SecondPos = Sketcher::PointPos::none;
        addConstraint(std::move(newConstr));
    };

    std::map<Constraint*, std::shared_ptr<App::Expression>> exprBackup;
    for (auto const& [newConstr, oldId] : newToOldConstraintMap) {
        if (oldId >= 0 && oldId < (int)allConstraints.size()) {
            auto exprInfo = getExpression(Constraints.createPath(oldId));
            if (exprInfo.expression) {
                exprBackup[newConstr] = std::shared_ptr<App::Expression>(exprInfo.expression->copy());
            }
        }
    }

    warnReleased(this, "Trim", released);  // before the deletion renumbers them
    delConstraints(std::move(idsOfOldConstraints), DeleteOption::NoFlag);

    if (!isOriginalCurveClosed) {
        transferConstraints(GeoId, PointPos::start, newIds.front(), PointPos::start, true);
        transferConstraints(GeoId, PointPos::end, newIds.back(), PointPos::end, true);
    }
    bool geomHasMid = geoAsCurve->isDerivedFrom<Part::GeomConic>()
        || geoAsCurve->isDerivedFrom<Part::GeomArcOfConic>();
    if (geomHasMid) {
        transferConstraints(GeoId, PointPos::mid, newIds.front(), PointPos::mid, true);
        // Make centers coincident
        if (newIds.size() > 1) {
            auto* joint = new Constraint();
            joint->Type = Coincident;
            joint->First = newIds.front();
            joint->FirstPos = PointPos::mid;
            joint->Second = newIds.back();
            joint->SecondPos = PointPos::mid;
            newConstraints.push_back(joint);

            // Any radius etc. equality constraints here
            // TODO: There could be some form of equality between the constraints here. However,
            // it may happen that this is imposed by an elaborate set of additional constraints.
            // When that happens, this causes redundant constraints, and in worse cases
            // (incorrect) complaints of over-constraint and solver failures.

            // if (std::ranges::none_of(newConstraints, [](const auto& constr) {
            //         return constr->Type == ConstraintType::Equal;
            //     })) {
            //     constrainAsEqual(newIds.front(), newIds.back());
            // }
            // TODO: ensure alignment as well?
        }
    }
    // FreeCAD-CH (ops#656): tie the pieces (fix 2); `ties` stay at the end of newConstraints.
    std::vector<Constraint*> ties;
    addTiesBetweenPieces(geoAsCurve, newIds, /*joined=*/false, ties);
    ties.insert(ties.end(), carrierTies.begin(), carrierTies.end());
    newConstraints.insert(newConstraints.end(), ties.begin(), ties.end());

    replaceGeometries({GeoId}, newGeos);
    for (auto newId : newIds) {
        setConstruction(newId, isOriginalCurveConstruction);
    }

    for (auto& deletedGeoId : geoIdsToBeDeleted) {
        for (auto& cons : newConstraints) {
            changeConstraintAfterDeletingGeo(cons, deletedGeoId);
        }
    }
    std::erase_if(newConstraints, [](const auto& constr) {
        return constr->Type == ConstraintType::None;
    });
    delGeometries(geoIdsToBeDeleted.begin(), geoIdsToBeDeleted.end());

    int lastAddedIndex = addConstraints(newConstraints);
    int firstAddedIndex = lastAddedIndex - (int)newConstraints.size() + 1;

    // Restore expressions
    std::vector<int> tieIndices;
    for (int i = 0; i < (int)newConstraints.size(); ++firstAddedIndex, ++i) {
        auto it = exprBackup.find(newConstraints[i]);
        if (it != exprBackup.end()) {
            setExpression(Constraints.createPath(firstAddedIndex), it->second);
        }
        if (std::ranges::find(ties, newConstraints[i]) != ties.end()) {
            tieIndices.push_back(firstAddedIndex);
        }
    }
    dropRedundantTies(this, std::move(tieIndices));

    if (noRecomputes) {
        solve();
    }

    //******************* Cleanup
    //****************************************//

    // Since we used regular "non-smart" pointers, we have to handle cleanup
    for (auto& cons : newConstraints) {
        delete cons;
    }

    return 0;
}

int SketchObject::split(int GeoId, const Base::Vector3d& point)
{
    // No need to check input data validity as this is an sketchobject managed operation

    Base::StateLocker lock(managedoperation, true);

    if (GeoId < 0 || GeoId > getHighestCurveIndex()) {
        return -1;
    }

    // FIXME: we should be able to transfer these to new curves smoothly
    // this removes internal geometry and constraints of geometries that still exists ???
    // deleteUnusedInternalGeometryAndUpdateGeoId(GeoId);
    const auto* geoAsCurve = getGeometry<Part::GeomCurve>(GeoId);

    bool isOriginalCurveClosed = isClosedCurve(geoAsCurve);
    // FreeCAD-CH (ops#656, fix 3, probe P7): a circle or an ellipse cut at one point is still one closed
    // curve. Split used to turn it into a full-turn arc whose two ends nothing held together (the
    // profile could open), and the solver has no robust single equation to hold them. Refuse, like
    // other CAD systems do: two arcs come from Trim, or from drawing arcs.
    if (isOriginalCurveClosed && !geoAsCurve->is<Part::GeomBSplineCurve>()) {
        Base::Console().error(
            getFullLabel(),
            "Split: a circle or an ellipse has no ends, so one cut leaves it whole. Split a circle at "
            "two points; trim an ellipse between two crossing curves, or draw arcs.\n"
        );
        return -1;
    }
    const bool isOriginalCurveConstruction = GeometryFacade::getConstruction(geoAsCurve);
    std::vector<int> newIds;
    std::vector<Part::Geometry*> newGeos;
    std::vector<Constraint*> newConstraints;

    double splitParam;
    geoAsCurve->closestParameter(point, splitParam);

    // TODO: find trim parameters
    std::vector<std::pair<double, double>> paramsOfNewGeos(
        isOriginalCurveClosed ? 1 : 2,
        {geoAsCurve->getFirstParameter(), geoAsCurve->getLastParameter()}
    );
    paramsOfNewGeos.front().second = isOriginalCurveClosed
        ? (splitParam + geoAsCurve->getLastParameter() - geoAsCurve->getFirstParameter())
        : splitParam;
    paramsOfNewGeos.back().first = splitParam;

    switch (paramsOfNewGeos.size()) {
        case 0: {
            delGeometry(GeoId);
            return 0;
        }
        case 1: {
            newIds.push_back(GeoId);
            break;
        }
        case 2: {
            newIds.push_back(GeoId);
            newIds.push_back(getHighestCurveIndex() + 1);
            break;
        }
        default: {
            return -1;
        }
    }

    createArcsFromGeoWithLimits(geoAsCurve, paramsOfNewGeos, newGeos);

    std::vector<int> idsOfOldConstraints;
    getConstraintIndices(GeoId, idsOfOldConstraints);
    const auto& allConstraints = this->Constraints.getValues();

    // This also seems to reset SketchObject::Geometry.
    // TODO: figure out why, and if that check must be used
    geoAsCurve = getGeometry<Part::GeomCurve>(GeoId);

    std::erase_if(idsOfOldConstraints, [&GeoId, &allConstraints](const auto& i) {
        return !allConstraints[i]->involvesGeoIdAndPosId(GeoId, PointPos::none);
    });

    std::vector<const Part::Geometry*> newGeosConst(newGeos.begin(), newGeos.end());

    if (!isOriginalCurveClosed && newIds.size() > 1) {
        transferConstraints(GeoId, PointPos::start, newIds.front(), PointPos::start, true);
        transferConstraints(GeoId, PointPos::end, newIds.back(), PointPos::end, true);
    }
    const bool isConic = geoAsCurve->isDerivedFrom<Part::GeomConic>()
        || geoAsCurve->isDerivedFrom<Part::GeomArcOfConic>();
    // FreeCAD-CH (ops#656): which old constraint each new one comes from, to carry its expression over
    // (Split used to drop them; Trim keeps them the same way).
    std::map<Constraint*, int> newToOld;
    std::vector<int> released;
    for (const auto& oldConstrId : idsOfOldConstraints) {
        Constraint* con = allConstraints[oldConstrId];
        if (con->Type == InternalAlignment && isConic) {
            // FreeCAD-CH (ops#656): an ellipse's axes and foci stay with its first piece, as Trim
            // keeps them. They used to be released, which left the pieces free to change shape.
            auto* moved = con->copy();
            moved->Second = newIds.front();
            newConstraints.push_back(moved);
            continue;
        }
        const size_t sizeBefore = newConstraints.size();
        if (!deriveConstraintsForPieces(GeoId, newIds, newGeosConst, con, newConstraints, true)) {
            released.push_back(oldConstrId);
        }
        for (size_t i = sizeBefore; i < newConstraints.size(); ++i) {
            newToOld[newConstraints[i]] = oldConstrId;
        }
    }
    std::map<Constraint*, std::shared_ptr<App::Expression>> exprBackup;
    for (auto const& [newConstr, oldId] : newToOld) {
        auto exprInfo = getExpression(Constraints.createPath(oldId));
        if (exprInfo.expression) {
            exprBackup[newConstr] = std::shared_ptr<App::Expression>(exprInfo.expression->copy());
        }
    }
    warnReleased(this, "Split", released);

    Constraint* joint = nullptr;
    // newIds.size() > 1 because a splitted circle gives an arc of circle, so we don't have a second
    // geometry piece
    if (!isOriginalCurveClosed && newIds.size() > 1) {
        joint = new Constraint();
        joint->Type = Coincident;
        joint->First = newIds.front();
        joint->FirstPos = PointPos::end;
        joint->Second = newIds.back();
        joint->SecondPos = PointPos::start;
        newConstraints.push_back(joint);
    }

    // This additional constraint is there to maintain existing behavior.
    // TODO: Decide whether to remove it altogether or also apply to other curves with centers.
    // TODO: Add this for all classes derived from GeomArcOfConic
    if ((geoAsCurve->isDerivedFrom<Part::GeomConic>()
         || geoAsCurve->isDerivedFrom<Part::GeomArcOfConic>())
        && newIds.size() > 1) {
        auto* midJoint = new Constraint();
        midJoint->Type = Coincident;
        midJoint->First = newIds.front();
        midJoint->FirstPos = PointPos::mid;
        midJoint->Second = newIds.back();
        midJoint->SecondPos = PointPos::mid;
        newConstraints.push_back(midJoint);
    }
    // for lines, we add a tangent constraint instead of coincident
    // TODO: this shouldn't be only for lines & bsplines, but for any geometry that isn't
    // constrained by a midpoint (like arcs/conics)
    else if (
        joint && (geoAsCurve->is<Part::GeomLineSegment>() || geoAsCurve->is<Part::GeomBSplineCurve>())
    ) {
        joint->Type = Tangent;
    }

    if (geoAsCurve->isDerivedFrom<Part::GeomConic>()
        || geoAsCurve->isDerivedFrom<Part::GeomArcOfConic>()) {
        transferConstraints(GeoId, PointPos::mid, newIds.front(), PointPos::mid);
    }

    // FreeCAD-CH (ops#656): tie the pieces (fix 2; split's line pieces are already collinear by their
    // joint, circle arcs equal by the joint and the shared centre), and keep a periodic B-spline cut at
    // one point closed (fix 3): it becomes an open one whose end poles are free, held by a coincidence.
    std::vector<Constraint*> ties;
    addTiesBetweenPieces(geoAsCurve, newIds, /*joined=*/true, ties);
    if (isOriginalCurveClosed && newIds.size() == 1) {
        if (geoAsCurve->is<Part::GeomBSplineCurve>()) {
            auto* close = new Constraint();
            close->Type = Coincident;
            close->First = newIds.front();
            close->FirstPos = PointPos::end;
            close->Second = newIds.front();
            close->SecondPos = PointPos::start;
            ties.push_back(close);
        }
    }
    newConstraints.insert(newConstraints.end(), ties.begin(), ties.end());

    delConstraints(std::move(idsOfOldConstraints), DeleteOption::NoSolve);
    replaceGeometries({GeoId}, newGeos);
    for (auto newId : newIds) {
        // FreeCAD-CH (ops#656): construction stays construction (it used to be lost for closed curves).
        setConstruction(newId, isOriginalCurveConstruction);
    }
    const int lastAddedIndex = addConstraints(newConstraints);
    const int firstAddedIndex = lastAddedIndex - int(newConstraints.size()) + 1;
    std::vector<int> tieIndices;
    for (size_t i = 0; i < newConstraints.size(); ++i) {
        auto it = exprBackup.find(newConstraints[i]);
        if (it != exprBackup.end()) {
            setExpression(Constraints.createPath(firstAddedIndex + int(i)), it->second);
        }
        if (std::ranges::find(ties, newConstraints[i]) != ties.end()) {
            tieIndices.push_back(firstAddedIndex + int(i));
        }
    }
    dropRedundantTies(this, std::move(tieIndices));

    if (noRecomputes) {
        solve();
    }

    for (auto& cons : newConstraints) {
        delete cons;
    }

    return 0;
}

// FreeCAD-CH (ops#656, rehearsal 3 F3; Onshape SK11): a circle has no ends, so Split takes two points on it
// and replaces it with two arcs of that circle, joined end to end at both points. The first arc keeps the
// circle's id and what was on its centre; the second is new. The two joints are one Coincident and one
// end-to-end Tangent: together 5 equations, exactly what makes the second arc the first one's circle
// (a Coincident at both joints plus a shared centre would repeat one equation, and two Coincidents plus
// an Equal lose the centre when the points are opposite). Ellipses are refused, as before.
int SketchObject::split(int GeoId, const Base::Vector3d& point1, const Base::Vector3d& point2)
{
    Base::StateLocker lock(managedoperation, true);

    if (GeoId < 0 || GeoId > getHighestCurveIndex()) {
        return -1;
    }
    const auto* circle = dynamic_cast<const Part::GeomCircle*>(getGeometry(GeoId));
    if (!circle || !GeometryFacade::isInternalType(circle, InternalType::None)) {
        Base::Console().error(
            getFullLabel(),
            "Split at two points: only a whole circle is split that way. Split other curves at one point.\n"
        );
        return -1;
    }
    double u1 {}, u2 {};
    circle->closestParameter(point1, u1);
    circle->closestParameter(point2, u2);
    if (u2 < u1) {
        std::swap(u1, u2);
    }
    const double period = 2 * std::numbers::pi;
    const double sweep = u2 - u1;
    // two points the same on the circle (within a micrometre on a 1 m circle) give no second arc
    if (sweep < 1e-9 || period - sweep < 1e-9) {
        Base::Console().error(getFullLabel(), "Split: pick two different points on the circle.\n");
        return -1;
    }
    const bool isConstruction = GeometryFacade::getConstruction(circle);

    std::vector<int> newIds {GeoId, getHighestCurveIndex() + 1};
    std::vector<Part::Geometry*> newGeos;
    createArcsFromGeoWithLimits(circle, {{u1, u2}, {u2, u1 + period}}, newGeos);
    std::vector<const Part::Geometry*> newGeosConst(newGeos.begin(), newGeos.end());

    // the circle's edge constraints go to the pieces (its centre constraints stay on GeoId, the first arc)
    std::vector<int> idsOfOldConstraints;
    getConstraintIndices(GeoId, idsOfOldConstraints);
    const auto& allConstraints = this->Constraints.getValues();
    std::erase_if(idsOfOldConstraints, [&GeoId, &allConstraints](const auto& i) {
        return !allConstraints[i]->involvesGeoIdAndPosId(GeoId, PointPos::none);
    });
    std::vector<Constraint*> newConstraints;
    std::map<Constraint*, int> newToOld;
    std::vector<int> released;
    for (const auto& oldConstrId : idsOfOldConstraints) {
        const size_t sizeBefore = newConstraints.size();
        if (!deriveConstraintsForPieces(
                GeoId, newIds, newGeosConst, allConstraints[oldConstrId], newConstraints, true
            )) {
            released.push_back(oldConstrId);
        }
        for (size_t i = sizeBefore; i < newConstraints.size(); ++i) {
            newToOld[newConstraints[i]] = oldConstrId;
        }
    }
    std::map<Constraint*, std::shared_ptr<App::Expression>> exprBackup;
    for (auto const& [newConstr, oldId] : newToOld) {
        auto exprInfo = getExpression(Constraints.createPath(oldId));
        if (exprInfo.expression) {
            exprBackup[newConstr] = std::shared_ptr<App::Expression>(exprInfo.expression->copy());
        }
    }
    warnReleased(this, "Split", released);

    auto* joint = new Constraint();
    joint->Type = Coincident;
    joint->First = newIds.front();
    joint->FirstPos = PointPos::end;
    joint->Second = newIds.back();
    joint->SecondPos = PointPos::start;
    newConstraints.push_back(joint);
    auto* closing = new Constraint();
    closing->Type = Tangent;
    closing->First = newIds.back();
    closing->FirstPos = PointPos::end;
    closing->Second = newIds.front();
    closing->SecondPos = PointPos::start;
    newConstraints.push_back(closing);

    delConstraints(std::move(idsOfOldConstraints), DeleteOption::NoSolve);
    replaceGeometries({GeoId}, newGeos);
    for (auto newId : newIds) {
        setConstruction(newId, isConstruction);
    }
    const int lastAddedIndex = addConstraints(newConstraints);
    const int firstAddedIndex = lastAddedIndex - int(newConstraints.size()) + 1;
    for (size_t i = 0; i < newConstraints.size(); ++i) {
        auto it = exprBackup.find(newConstraints[i]);
        if (it != exprBackup.end()) {
            setExpression(Constraints.createPath(firstAddedIndex + int(i)), it->second);
        }
    }
    if (noRecomputes) {
        solve();
    }
    for (auto& cons : newConstraints) {
        delete cons;
    }
    return 0;
}
// clang-format off

int SketchObject::join(
    int geoId1,
    Sketcher::PointPos posId1,
    int geoId2,
    Sketcher::PointPos posId2,
    int continuity
)
{
    // No need to check input data validity as this is an sketchobject managed operation

    Base::StateLocker lock(managedoperation, true);

    if (Sketcher::PointPos::start != posId1 && Sketcher::PointPos::end != posId1
        && Sketcher::PointPos::start != posId2 && Sketcher::PointPos::end != posId2) {
        THROWM(ValueError, "Invalid positions: points must be start or end points of a curve.");
        return -1;
    }

    if (geoId1 == geoId2) {
        THROWM(ValueError, "Connecting the end points of the same curve is not yet supported.");
        return -1;
    }

    if (geoId1 < 0 || geoId1 > getHighestCurveIndex() || geoId2 < 0
        || geoId2 > getHighestCurveIndex()) {
        return -1;
    }

    // get the old splines
    auto* geo1 = dynamic_cast<const Part::GeomCurve*>(getGeometry(geoId1));
    auto* geo2 = dynamic_cast<const Part::GeomCurve*>(getGeometry(geoId2));

    if (GeometryFacade::getConstruction(geo1) != GeometryFacade::getConstruction(geo2)) {
        THROWM(ValueError, "Cannot join construction and non-construction geometries.");
        return -1;
    }
    bool areOriginalCurvesConstruction = GeometryFacade::getConstruction(geo1);

    // TODO: make both curves b-splines here itself
    if (!geo1 || !geo2) {
        return -1;
    }

    // TODO: is there a cleaner way to get our mutable bsp's?
    // we need the splines to be mutable because we may reverse them
    // and/or change their degree
    std::unique_ptr<Part::GeomBSplineCurve> bsp1(
        geo1->toNurbs(geo1->getFirstParameter(), geo1->getLastParameter())
    );
    std::unique_ptr<Part::GeomBSplineCurve> bsp2(
        geo2->toNurbs(geo2->getFirstParameter(), geo2->getLastParameter())
    );

    if (bsp1->isPeriodic() || bsp2->isPeriodic()) {
        THROWM(ValueError, "It is only possible to join non-periodic curves.");
        return -1;
    }

    // reverse the splines if needed: join end of 1st to start of 2nd
    if (Sketcher::PointPos::start == posId1) {
        bsp1->reverse();
    }
    if (Sketcher::PointPos::end == posId2) {
        bsp2->reverse();
    }

    // ensure the degrees of both curves are the same
    if (bsp1->getDegree() < bsp2->getDegree()) {
        bsp1->increaseDegree(bsp2->getDegree());
    }
    else if (bsp2->getDegree() < bsp1->getDegree()) {
        bsp2->increaseDegree(bsp1->getDegree());
    }

    // TODO: Check for tangent constraint here
    bool makeC1Continuous = (continuity >= 1);

    // TODO: Rescale one or both sections to fulfill some purpose.
    // This could include making param between [0,1], and/or making
    // C1 continuity possible.
    if (makeC1Continuous) {
        // We assume here that there is already G1 continuity.
        // Just scale parameters to get C1.
        Base::Vector3d slope1 = bsp1->firstDerivativeAtParameter(bsp1->getLastParameter());
        Base::Vector3d slope2 = bsp2->firstDerivativeAtParameter(bsp2->getFirstParameter());
        // TODO: slope2 can technically be a zero vector
        // But that seems not possible unless the spline is trivial.
        // Prove or account for the possibility.
        double scale = slope2.Length() / slope1.Length();
        bsp2->scaleKnotsToBounds(0, scale * (bsp2->getLastParameter() - bsp2->getFirstParameter()));
    }

    // set up vectors for new poles, knots, mults
    std::vector<Base::Vector3d> poles1 = bsp1->getPoles();
    std::vector<double> weights1 = bsp1->getWeights();
    std::vector<double> knots1 = bsp1->getKnots();
    std::vector<int> mults1 = bsp1->getMultiplicities();
    std::vector<Base::Vector3d> poles2 = bsp2->getPoles();
    std::vector<double> weights2 = bsp2->getWeights();
    std::vector<double> knots2 = bsp2->getKnots();
    std::vector<int> mults2 = bsp2->getMultiplicities();

    std::vector<Base::Vector3d> newPoles(std::move(poles1));
    std::vector<double> newWeights(std::move(weights1));
    std::vector<double> newKnots(std::move(knots1));
    std::vector<int> newMults(std::move(mults1));

    poles2.erase(poles2.begin());
    if (makeC1Continuous) {
        newPoles.erase(newPoles.end() - 1);
    }
    newPoles.insert(
        newPoles.end(),
        std::make_move_iterator(poles2.begin()),
        std::make_move_iterator(poles2.end())
    );

    // TODO: Weights might need to be scaled
    weights2.erase(weights2.begin());
    if (makeC1Continuous) {
        newWeights.erase(newWeights.end() - 1);
    }
    newWeights.insert(
        newWeights.end(),
        std::make_move_iterator(weights2.begin()),
        std::make_move_iterator(weights2.end())
    );

    // knots of the second spline come after all of the first
    double offset = newKnots.back() - knots2.front();
    knots2.erase(knots2.begin());
    for (auto& knot : knots2) {
        knot += offset;
    }
    newKnots.insert(
        newKnots.end(),
        std::make_move_iterator(knots2.begin()),
        std::make_move_iterator(knots2.end())
    );

    // end knots can have a multiplicity of (degree + 1)
    if (bsp1->getDegree() < newMults.back()) {
        newMults.back() = bsp1->getDegree();
        if (makeC1Continuous) {
            newMults.back() -= 1;
        }
    }

    mults2.erase(mults2.begin());
    newMults.insert(
        newMults.end(),
        std::make_move_iterator(mults2.begin()),
        std::make_move_iterator(mults2.end())
    );

    auto* newSpline = new Part::GeomBSplineCurve(
        newPoles,
        newWeights,
        newKnots,
        newMults,
        bsp1->getDegree(),
        false,
        true
    );

    // int newGeoId = addGeometry(newSpline);
    std::vector<Part::Geometry*> newGeos {newSpline};
    replaceGeometries({geoId1, geoId2}, newGeos);

    exposeInternalGeometry(geoId1);
    setConstruction(geoId1, areOriginalCurvesConstruction);

    // TODO: transfer constraints on the non-connected ends
    auto otherPosId1 = (Sketcher::PointPos::start == posId1) ? Sketcher::PointPos::end
                                                             : Sketcher::PointPos::start;
    auto otherPosId2 = (Sketcher::PointPos::start == posId2) ? Sketcher::PointPos::end
                                                             : Sketcher::PointPos::start;

    transferConstraints(geoId1, otherPosId1, geoId1, PointPos::start, true);
    transferConstraints(geoId2, otherPosId2, geoId1, PointPos::end, true);

    return 0;
}

// clang-format on
int SketchObject::addSymmetric(
    const std::vector<int>& geoIdList,
    int refGeoId,
    Sketcher::PointPos refPosId,
    bool addSymmetryConstraints
)
{
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    const std::vector<Constraint*>& constrvals = this->Constraints.getValues();
    std::vector<Constraint*> newconstrVals(constrvals);

    std::map<int, int> geoIdMap;
    std::map<int, bool> isStartEndInverted;

    // Find out if reference is aligned with V or H axis,
    // if so we can keep Vertical and Horizontal constraints in the mirrored geometry.
    bool refIsLine = refPosId == Sketcher::PointPos::none;
    bool refIsAxisAligned = refGeoId == Sketcher::GeoEnum::VAxis
        || refGeoId == Sketcher::GeoEnum::HAxis || !refIsLine
        || std::ranges::any_of(constrvals, [&refGeoId](auto* constr) {
                                return constr->getElement(0).GeoId == refGeoId
                                    && (constr->Type == Sketcher::Vertical
                                        || constr->Type == Sketcher::Horizontal);
                            });

    std::vector<Part::Geometry*> symgeos
        = getSymmetric(geoIdList, geoIdMap, isStartEndInverted, refGeoId, refPosId);

    // Perturb geometry to avoid numerical singularities in the solver (Jacobian Rank).
    // If geometry is "perfect", the solver cannot distinguish between the derivative
    // of a Symmetry constraint and an Equal constraint, flagging one as redundant.
    // see https://github.com/FreeCAD/FreeCAD/issues/13551
    // This does not happen with other arcs types.
    if (addSymmetryConstraints) {
        for (auto* geo : symgeos) {
            if (auto* arc = dynamic_cast<Part::GeomArcOfCircle*>(geo)) {
                double start, end;
                arc->getRange(start, end, true);
                arc->setRange(start + Precision::Angular(), end, true);
            }
        }
    }

    {
        addGeometry(symgeos);

        for (auto* constr : constrvals) {
            // we look in the map, because we might have skipped internal alignment geometry
            auto firstIt = geoIdMap.find(constr->getElement(0).GeoId);

            if (firstIt == geoIdMap.end()) {
                continue;
            }

            // if First of constraint is in geoIdList
            if (addSymmetryConstraints && constr->Type != Sketcher::InternalAlignment) {
                // If we are making symmetric constraints, we only want to copy topological
                // constraints to maintain the structural shape (Coincident, and
                // endpoint-to-endpoint Tangent/Perpendicular).
                bool keepTopological = false;
                if (constr->Type == Sketcher::Coincident) {
                    keepTopological = true;
                }
                else if (constr->Type == Sketcher::Tangent || constr->Type == Sketcher::Perpendicular) {
                    if (constr->FirstPos != Sketcher::PointPos::none
                        && constr->SecondPos != Sketcher::PointPos::none) {
                        keepTopological = true;
                    }
                }

                if (!keepTopological) {
                    continue;
                }
            }

            if (constr->getElement(1).GeoId == GeoEnum::GeoUndef  //
                /*&& constr->getElement(2).GeoId == GeoEnum::GeoUndef*/) {
                if (refIsAxisAligned
                    && (constr->Type == Sketcher::DistanceX || constr->Type == Sketcher::DistanceY)) {
                    // In this case we want to keep the Vertical, Horizontal constraints.
                    // DistanceX and DistanceY constraints should also be possible to keep in
                    // this case, but keeping them causes segfault, not sure why.

                    continue;
                }
                if (!refIsAxisAligned
                    && (constr->Type == Sketcher::DistanceX     //
                        || constr->Type == Sketcher::DistanceY  //
                        || constr->Type == Sketcher::Vertical   //
                        || constr->Type == Sketcher::Horizontal)) {
                    // this includes all non-directional single GeoId constraints, as radius,
                    // diameter, weight,...
                    continue;
                }
                Constraint* constNew = constr->copy();
                constNew->Name = "";
                GeoElementId rep = constr->getElement(0);
                rep.GeoId = firstIt->second;
                constNew->setElement(0, rep);
                newconstrVals.push_back(constNew);

                continue;
            }

            // other geoids intervene in this constraint
            auto secondIt = geoIdMap.find(constr->getElement(1).GeoId);

            if (secondIt == geoIdMap.end()) {
                continue;
            }

            // Second is also in the list

            auto flipStartEndIfRelevant =
                [&isStartEndInverted](GeoElementId geId, Sketcher::PointPos& posIdNew) {
                    if (isStartEndInverted[geId.GeoId]) {
                        if (geId.Pos == Sketcher::PointPos::start) {
                            posIdNew = Sketcher::PointPos::end;
                        }
                        else if (geId.Pos == Sketcher::PointPos::end) {
                            posIdNew = Sketcher::PointPos::start;
                        }
                    }
                };

            if (constr->getElement(2).GeoId == GeoEnum::GeoUndef) {
                if (!(constr->Type == Sketcher::Coincident        //
                      || constr->Type == Sketcher::Perpendicular  //
                      || constr->Type == Sketcher::Parallel       //
                      || constr->Type == Sketcher::Tangent        //
                      || constr->Type == Sketcher::Distance       //
                      || constr->Type == Sketcher::Equal          //
                      || constr->Type == Sketcher::Angle          //
                      || constr->Type == Sketcher::PointOnObject  //
                      || constr->Type == Sketcher::Midpoint       // FreeCAD-CH (ops#656)
                      || constr->Type == Sketcher::InternalAlignment)) {
                    continue;
                }

                Constraint* constNew = constr->copy();

                // If making a dependent symmetry copy, Tangent/Perp would overconstrain the
                // angle (which is already locked by the symmetries of the endpoints/centers).
                // Downgrade endpoint-to-endpoint constraints to Coincident to keep topology.
                if (addSymmetryConstraints
                    && (constNew->Type == Sketcher::Tangent
                        || constNew->Type == Sketcher::Perpendicular)) {
                    constNew->Type = Sketcher::Coincident;
                }

                constNew->Name = "";
                auto rep0 = constNew->getElement(0);
                auto rep1 = constNew->getElement(1);
                rep0.GeoId = firstIt->second;
                rep1.GeoId = secondIt->second;
                flipStartEndIfRelevant(constr->getElement(0), rep0.Pos);
                flipStartEndIfRelevant(constr->getElement(1), rep1.Pos);
                constNew->setElement(0, rep0);
                constNew->setElement(1, rep1);

                if (constNew->Type == Tangent || constNew->Type == Perpendicular) {
                    AutoLockTangencyAndPerpty(constNew, true);
                }

                if ((constr->Type == Sketcher::Angle) && (refPosId == Sketcher::PointPos::none)) {
                    constNew->setValue(-constr->getValue());
                }

                // Signed constraints record which side of a line their subject sits on, and a
                // symmetry about a *line* reverses that side while a symmetry about a *point* does
                // not. For the new constraint, re-derive the sign from the updated geometry
                // instead of trying to figure it out from the old one.
                setOrientation(constNew, true);

                newconstrVals.push_back(constNew);
                continue;
            }

            // three GeoIds intervene in constraint
            auto thirdIt = geoIdMap.find(constr->getElement(2).GeoId);

            if (thirdIt == geoIdMap.end()) {
                continue;
            }

            // Third is also in the list
            Constraint* constNew = constr->copy();
            constNew->Name = "";
            auto rep0 = constNew->getElement(0);
            auto rep1 = constNew->getElement(1);
            auto rep2 = constNew->getElement(2);
            rep0.GeoId = firstIt->second;
            rep1.GeoId = secondIt->second;
            rep2.GeoId = thirdIt->second;
            flipStartEndIfRelevant(constr->getElement(0), rep0.Pos);
            flipStartEndIfRelevant(constr->getElement(1), rep1.Pos);
            flipStartEndIfRelevant(constr->getElement(2), rep2.Pos);
            constNew->setElement(0, rep0);
            constNew->setElement(1, rep1);
            constNew->setElement(2, rep2);
            newconstrVals.push_back(constNew);
        }

        if (!addSymmetryConstraints) {
            if (newconstrVals.size() > constrvals.size()) {
                Constraints.setValues(std::move(newconstrVals));
            }

            // we delayed update, so trigger it now.
            // Update geometry indices and rebuild vertexindex now via onChanged, so that
            // ViewProvider::UpdateData is triggered.
            Geometry.touch();

            return Geometry.getSize() - 1;
        }

        // Retrieve all coincident point groups in the original sketch
        auto coincidenceGroups = getCoincidenceGroups();
        std::set<std::pair<int, Sketcher::PointPos>> symmetricConstrainedOriginalPoints;

        auto markPointConstrained = [&](int geoId, Sketcher::PointPos pos) {
            std::pair<int, Sketcher::PointPos> pt {geoId, pos};
            symmetricConstrainedOriginalPoints.insert(pt);
            for (const auto& group : coincidenceGroups) {
                if (group.find(geoId) != group.end() && group.at(geoId) == pos) {
                    for (const auto& member : group) {
                        symmetricConstrainedOriginalPoints.insert(
                            std::make_pair(member.first, member.second)
                        );
                    }
                    break;
                }
            }
        };

        // Helper to check if a point lies on the symmetry reference
        auto isPointOnReference = [&](const Base::Vector3d& pt) {
            if (refPosId == Sketcher::PointPos::none) {
                // Reference is a line (Axis of Symmetry)
                const Part::Geometry* georef = getGeometry(refGeoId);
                if (georef && georef->is<Part::GeomLineSegment>()) {
                    auto* refLine = static_cast<const Part::GeomLineSegment*>(georef);
                    Base::Vector3d l1 = refLine->getStartPoint();
                    Base::Vector3d l2 = refLine->getEndPoint();
                    double dx = l2.x - l1.x;
                    double dy = l2.y - l1.y;
                    double line_len_sq = dx * dx + dy * dy;
                    if (line_len_sq > Precision::SquareConfusion()) {
                        double area = (pt.x - l1.x) * dy - (pt.y - l1.y) * dx;
                        if (std::abs(area) / sqrt(line_len_sq) < Precision::Confusion()) {
                            return true;
                        }
                    }
                }
            }
            else {
                // Reference is a point (Point Symmetry)
                Base::Vector3d refPt;
                if (refGeoId == Sketcher::GeoEnum::RtPnt) {
                    refPt = Base::Vector3d(0, 0, 0);
                }
                else {
                    refPt = getPoint(refGeoId, refPosId);
                }
                if ((pt - refPt).Length() < Precision::Confusion()) {
                    return true;
                }
            }
            return false;
        };

        auto createSymConstr =
            [&](int first, int second, Sketcher::PointPos firstPos, Sketcher::PointPos secondPos) {
                std::pair<int, Sketcher::PointPos> pt {first, firstPos};
                // If this point (or any coincident peer) already got a symmetry constraint, skip
                if (symmetricConstrainedOriginalPoints.count(pt) > 0) {
                    return;
                }

                Base::Vector3d pCoords = getPoint(first, firstPos);

                if (isPointOnReference(pCoords)) {
                    // Point is on the mirror axis: use Coincident to stitch and avoid singularity
                    auto* coincConstr = new Constraint();
                    coincConstr->Type = Sketcher::Coincident;
                    coincConstr->setElement(0, GeoElementId {first, firstPos});
                    coincConstr->setElement(1, GeoElementId {second, secondPos});
                    newconstrVals.push_back(coincConstr);
                }
                else {
                    // Standard symmetry constraint for off-axis points
                    auto* symConstr = new Constraint();
                    symConstr->Type = Sketcher::Symmetric;
                    symConstr->setElement(0, GeoElementId {first, firstPos});
                    symConstr->setElement(1, GeoElementId {second, secondPos});
                    symConstr->setElement(2, GeoElementId {refGeoId, refPosId});
                    newconstrVals.push_back(symConstr);
                }

                markPointConstrained(first, firstPos);
            };
        auto createEqualityConstr = [&](int first, int second) {
            auto* symConstr = new Constraint();
            symConstr->Type = Equal;
            symConstr->setElement(0, GeoElementId {first});
            symConstr->setElement(1, GeoElementId {second});
            newconstrVals.push_back(symConstr);
        };

        for (auto geoIdPair : geoIdMap) {
            int geoId1 = geoIdPair.first;
            int geoId2 = geoIdPair.second;
            const Part::Geometry* geo = getGeometry(geoId1);

            if (geo->is<Part::GeomLineSegment>()) {
                auto gf = GeometryFacade::getFacade(geo);
                if (!gf->isInternalAligned()) {
                    // Note internal aligned lines (ellipse, parabola, hyperbola) are causing
                    // redundant constraint.
                    createSymConstr(
                        geoId1,
                        geoId2,
                        PointPos::start,
                        isStartEndInverted[geoId1] ? PointPos::end : PointPos::start
                    );
                    createSymConstr(
                        geoId1,
                        geoId2,
                        PointPos::end,
                        isStartEndInverted[geoId1] ? PointPos::start : PointPos::end
                    );
                }
            }
            else if (geo->is<Part::GeomCircle>() || geo->is<Part::GeomEllipse>()) {
                createEqualityConstr(geoId1, geoId2);
                createSymConstr(geoId1, geoId2, PointPos::mid, PointPos::mid);
            }
            else if (
                geo->is<Part::GeomArcOfCircle>()        //
                || geo->is<Part::GeomArcOfEllipse>()    //
                || geo->is<Part::GeomArcOfHyperbola>()  //
                || geo->is<Part::GeomArcOfParabola>()
            ) {
                createEqualityConstr(geoId1, geoId2);
                createSymConstr(
                    geoId1,
                    geoId2,
                    PointPos::start,
                    isStartEndInverted[geoId1] ? PointPos::end : PointPos::start
                );
                createSymConstr(
                    geoId1,
                    geoId2,
                    PointPos::end,
                    isStartEndInverted[geoId1] ? PointPos::start : PointPos::end
                );
            }
            else if (geo->is<Part::GeomPoint>()) {
                auto gf = GeometryFacade::getFacade(geo);
                if (!gf->isInternalAligned()) {
                    createSymConstr(geoId1, geoId2, PointPos::start, PointPos::start);
                }
            }
            // Note bspline has symmetric by the internal aligned circles.
        }

        if (newconstrVals.size() > constrvals.size()) {
            Constraints.setValues(std::move(newconstrVals));
        }
    }

    // we delayed update, so trigger it now.
    // Update geometry indices and rebuild vertexindex now via onChanged, so that
    // ViewProvider::UpdateData is triggered.
    Geometry.touch();

    return Geometry.getSize() - 1;
}

std::vector<Part::Geometry*> SketchObject::getSymmetric(
    const std::vector<int>& geoIdList,
    std::map<int, int>& geoIdMap,
    std::map<int, bool>& isStartEndInverted,
    int refGeoId,
    Sketcher::PointPos refPosId
)
{
    using std::numbers::pi;

    std::vector<Part::Geometry*> symmetricVals;
    bool refIsLine = refPosId == Sketcher::PointPos::none;
    int cgeoid = getHighestCurveIndex() + 1;

    auto shouldCopyGeometry = [&](auto* geo, int geoId) -> bool {
        auto gf = GeometryFacade::getFacade(geo);
        if (!gf->isInternalAligned()) {
            // Return true if not internal aligned, indicating it should always be copied
            return true;
        }

        // only add if the corresponding geometry it defines is also in the list.
        const auto& constraints = Constraints.getValues();
        auto constrIt = std::ranges::find_if(constraints, [&geoId](auto* c) {
            return c->Type == Sketcher::InternalAlignment && c->getElement(0).GeoId == geoId;
        });
        int definedGeo = (constrIt == constraints.end()) ? GeoEnum::GeoUndef
                                                         : (*constrIt)->getElement(1).GeoId;
        // Return true if definedGeo is in geoIdList, false otherwise
        return std::ranges::find(geoIdList, definedGeo) != geoIdList.end();
    };

    if (refIsLine) {
        const Part::Geometry* georef = getGeometry(refGeoId);
        if (!georef->is<Part::GeomLineSegment>()) {
            return {};
        }

        auto* refGeoLine = static_cast<const Part::GeomLineSegment*>(georef);
        // line
        Base::Vector3d refstart = refGeoLine->getStartPoint();
        Base::Vector3d vectline = refGeoLine->getEndPoint() - refstart;

        for (auto geoId : geoIdList) {
            const Part::Geometry* geo = getGeometry(geoId);
            Part::Geometry* geosym;

            if (!shouldCopyGeometry(geo, geoId)) {
                continue;
            }

            geosym = geo->copy();

            // Handle Geometry
            if (geosym->is<Part::GeomLineSegment>()) {
                auto* geosymline = static_cast<Part::GeomLineSegment*>(geosym);
                Base::Vector3d sp = geosymline->getStartPoint();
                Base::Vector3d ep = geosymline->getEndPoint();

                geosymline->setPoints(
                    sp + 2.0 * (sp.Perpendicular(refGeoLine->getStartPoint(), vectline) - sp),
                    ep + 2.0 * (ep.Perpendicular(refGeoLine->getStartPoint(), vectline) - ep)
                );
                isStartEndInverted.insert(std::make_pair(geoId, false));
            }
            else if (geosym->is<Part::GeomCircle>()) {
                auto* geosymcircle = static_cast<Part::GeomCircle*>(geosym);
                Base::Vector3d cp = geosymcircle->getCenter();

                geosymcircle->setCenter(
                    cp + 2.0 * (cp.Perpendicular(refGeoLine->getStartPoint(), vectline) - cp)
                );
                isStartEndInverted.insert(std::make_pair(geoId, false));
            }
            else if (geosym->is<Part::GeomArcOfCircle>()) {
                auto* geoaoc = static_cast<Part::GeomArcOfCircle*>(geosym);
                Base::Vector3d sp = geoaoc->getStartPoint(true);
                Base::Vector3d ep = geoaoc->getEndPoint(true);
                Base::Vector3d cp = geoaoc->getCenter();

                Base::Vector3d ssp = sp
                    + 2.0 * (sp.Perpendicular(refGeoLine->getStartPoint(), vectline) - sp);
                Base::Vector3d sep = ep
                    + 2.0 * (ep.Perpendicular(refGeoLine->getStartPoint(), vectline) - ep);
                Base::Vector3d scp = cp
                    + 2.0 * (cp.Perpendicular(refGeoLine->getStartPoint(), vectline) - cp);

                double theta1 = Base::fmod(atan2(sep.y - scp.y, sep.x - scp.x), 2.f * std::numbers::pi);
                double theta2 = Base::fmod(atan2(ssp.y - scp.y, ssp.x - scp.x), 2.f * std::numbers::pi);

                geoaoc->setCenter(scp);
                geoaoc->setRange(theta1, theta2, true);
                isStartEndInverted.insert(std::make_pair(geoId, true));
            }
            else if (geosym->is<Part::GeomEllipse>()) {
                auto* geosymellipse = static_cast<Part::GeomEllipse*>(geosym);
                Base::Vector3d cp = geosymellipse->getCenter();

                Base::Vector3d majdir = geosymellipse->getMajorAxisDir();
                double majord = geosymellipse->getMajorRadius();
                double minord = geosymellipse->getMinorRadius();
                double df = sqrt(majord * majord - minord * minord);
                Base::Vector3d f1 = cp + df * majdir;

                Base::Vector3d sf1 = f1
                    + 2.0 * (f1.Perpendicular(refGeoLine->getStartPoint(), vectline) - f1);
                Base::Vector3d scp = cp
                    + 2.0 * (cp.Perpendicular(refGeoLine->getStartPoint(), vectline) - cp);

                geosymellipse->setMajorAxisDir(sf1 - scp);

                geosymellipse->setCenter(scp);
                isStartEndInverted.insert(std::make_pair(geoId, false));
            }
            else if (geosym->is<Part::GeomArcOfEllipse>()) {
                auto* geosymaoe = static_cast<Part::GeomArcOfEllipse*>(geosym);
                Base::Vector3d cp = geosymaoe->getCenter();

                Base::Vector3d majdir = geosymaoe->getMajorAxisDir();
                double majord = geosymaoe->getMajorRadius();
                double minord = geosymaoe->getMinorRadius();
                double df = sqrt(majord * majord - minord * minord);
                Base::Vector3d f1 = cp + df * majdir;

                Base::Vector3d sf1 = f1
                    + 2.0 * (f1.Perpendicular(refGeoLine->getStartPoint(), vectline) - f1);
                Base::Vector3d scp = cp
                    + 2.0 * (cp.Perpendicular(refGeoLine->getStartPoint(), vectline) - cp);

                geosymaoe->setMajorAxisDir(sf1 - scp);

                geosymaoe->setCenter(scp);

                double theta1, theta2;
                geosymaoe->getRange(theta1, theta2, true);
                theta1 = 2.0 * pi - theta1;
                theta2 = 2.0 * pi - theta2;
                std::swap(theta1, theta2);
                if (theta1 < 0) {
                    theta1 += 2.0 * pi;
                    theta2 += 2.0 * pi;
                }

                geosymaoe->setRange(theta1, theta2, true);
                isStartEndInverted.insert(std::make_pair(geoId, true));
            }
            else if (geosym->is<Part::GeomArcOfHyperbola>()) {
                auto* geosymaoe = static_cast<Part::GeomArcOfHyperbola*>(geosym);
                Base::Vector3d cp = geosymaoe->getCenter();

                Base::Vector3d majdir = geosymaoe->getMajorAxisDir();
                double majord = geosymaoe->getMajorRadius();
                double minord = geosymaoe->getMinorRadius();
                double df = sqrt(majord * majord + minord * minord);
                Base::Vector3d f1 = cp + df * majdir;

                Base::Vector3d sf1 = f1
                    + 2.0 * (f1.Perpendicular(refGeoLine->getStartPoint(), vectline) - f1);
                Base::Vector3d scp = cp
                    + 2.0 * (cp.Perpendicular(refGeoLine->getStartPoint(), vectline) - cp);

                geosymaoe->setMajorAxisDir(sf1 - scp);

                geosymaoe->setCenter(scp);

                double theta1, theta2;
                geosymaoe->getRange(theta1, theta2, true);
                theta1 = -theta1;
                theta2 = -theta2;
                std::swap(theta1, theta2);

                geosymaoe->setRange(theta1, theta2, true);
                isStartEndInverted.insert(std::make_pair(geoId, true));
            }
            else if (geosym->is<Part::GeomArcOfParabola>()) {
                auto* geosymaoe = static_cast<Part::GeomArcOfParabola*>(geosym);
                Base::Vector3d cp = geosymaoe->getCenter();

                Base::Vector3d f1 = geosymaoe->getFocus();

                Base::Vector3d sf1 = f1
                    + 2.0 * (f1.Perpendicular(refGeoLine->getStartPoint(), vectline) - f1);
                Base::Vector3d scp = cp
                    + 2.0 * (cp.Perpendicular(refGeoLine->getStartPoint(), vectline) - cp);

                geosymaoe->setXAxisDir(sf1 - scp);
                geosymaoe->setCenter(scp);

                double theta1, theta2;
                geosymaoe->getRange(theta1, theta2, true);
                theta1 = -theta1;
                theta2 = -theta2;
                std::swap(theta1, theta2);

                geosymaoe->setRange(theta1, theta2, true);
                isStartEndInverted.insert(std::make_pair(geoId, true));
            }
            else if (geosym->is<Part::GeomBSplineCurve>()) {
                auto* geosymbsp = static_cast<Part::GeomBSplineCurve*>(geosym);

                std::vector<Base::Vector3d> poles = geosymbsp->getPoles();

                for (auto& pole : poles) {
                    pole = pole
                        + 2.0 * (pole.Perpendicular(refGeoLine->getStartPoint(), vectline) - pole);
                }

                geosymbsp->setPoles(poles);

                isStartEndInverted.insert(std::make_pair(geoId, false));
            }
            else if (geosym->is<Part::GeomPoint>()) {
                auto* geosympoint = static_cast<Part::GeomPoint*>(geosym);
                Base::Vector3d cp = geosympoint->getPoint();

                geosympoint->setPoint(
                    cp + 2.0 * (cp.Perpendicular(refGeoLine->getStartPoint(), vectline) - cp)
                );
                isStartEndInverted.insert(std::make_pair(geoId, false));
            }
            else {
                Base::Console().error("Unsupported Geometry!! Just copying it.\n");
                isStartEndInverted.insert(std::make_pair(geoId, false));
            }

            symmetricVals.push_back(geosym);
            geoIdMap.insert(std::make_pair(geoId, cgeoid));
            cgeoid++;
        }

        return symmetricVals;
    }

    // reference is a point
    Vector3d refpoint;
    const Part::Geometry* georef = getGeometry(refGeoId);

    if (georef->is<Part::GeomPoint>()) {
        refpoint = static_cast<const Part::GeomPoint*>(georef)->getPoint();
    }
    else if (refGeoId == -1 && refPosId == Sketcher::PointPos::start) {
        refpoint = Vector3d(0, 0, 0);
    }
    else {
        if (refPosId == Sketcher::PointPos::none) {
            Base::Console().error("Wrong PointPosId.\n");
            return {};
        }
        refpoint = getPoint(georef, refPosId);
    }

    for (auto geoId : geoIdList) {
        const Part::Geometry* geo = getGeometry(geoId);
        Part::Geometry* geosym;

        if (!shouldCopyGeometry(geo, geoId)) {
            continue;
        }

        geosym = geo->copy();

        // Handle Geometry
        if (geosym->is<Part::GeomLineSegment>()) {
            auto* geosymline = static_cast<Part::GeomLineSegment*>(geosym);
            Base::Vector3d sp = geosymline->getStartPoint();
            Base::Vector3d ep = geosymline->getEndPoint();
            Base::Vector3d ssp = sp + 2.0 * (refpoint - sp);
            Base::Vector3d sep = ep + 2.0 * (refpoint - ep);

            geosymline->setPoints(ssp, sep);
            isStartEndInverted.insert(std::make_pair(geoId, false));
        }
        else if (geosym->is<Part::GeomCircle>()) {
            auto* geosymcircle = static_cast<Part::GeomCircle*>(geosym);
            Base::Vector3d cp = geosymcircle->getCenter();

            geosymcircle->setCenter(cp + 2.0 * (refpoint - cp));
            isStartEndInverted.insert(std::make_pair(geoId, false));
        }
        else if (geosym->is<Part::GeomArcOfCircle>()) {
            auto* geoaoc = static_cast<Part::GeomArcOfCircle*>(geosym);
            Base::Vector3d sp = geoaoc->getStartPoint(true);
            Base::Vector3d ep = geoaoc->getEndPoint(true);
            Base::Vector3d cp = geoaoc->getCenter();

            Base::Vector3d ssp = sp + 2.0 * (refpoint - sp);
            Base::Vector3d sep = ep + 2.0 * (refpoint - ep);
            Base::Vector3d scp = cp + 2.0 * (refpoint - cp);

            double theta1 = Base::fmod(atan2(ssp.y - scp.y, ssp.x - scp.x), 2.f * pi);
            double theta2 = Base::fmod(atan2(sep.y - scp.y, sep.x - scp.x), 2.f * pi);

            geoaoc->setCenter(scp);
            geoaoc->setRange(theta1, theta2, true);
            isStartEndInverted.insert(std::make_pair(geoId, false));
        }
        else if (geosym->is<Part::GeomEllipse>()) {
            auto* geosymellipse = static_cast<Part::GeomEllipse*>(geosym);
            Base::Vector3d cp = geosymellipse->getCenter();

            Base::Vector3d majdir = geosymellipse->getMajorAxisDir();
            double majord = geosymellipse->getMajorRadius();
            double minord = geosymellipse->getMinorRadius();
            double df = sqrt(majord * majord - minord * minord);
            Base::Vector3d f1 = cp + df * majdir;

            Base::Vector3d sf1 = f1 + 2.0 * (refpoint - f1);
            Base::Vector3d scp = cp + 2.0 * (refpoint - cp);

            geosymellipse->setMajorAxisDir(sf1 - scp);

            geosymellipse->setCenter(scp);
            isStartEndInverted.insert(std::make_pair(geoId, false));
        }
        else if (geosym->is<Part::GeomArcOfEllipse>()) {
            auto* geosymaoe = static_cast<Part::GeomArcOfEllipse*>(geosym);
            Base::Vector3d cp = geosymaoe->getCenter();

            Base::Vector3d majdir = geosymaoe->getMajorAxisDir();
            double majord = geosymaoe->getMajorRadius();
            double minord = geosymaoe->getMinorRadius();
            double df = sqrt(majord * majord - minord * minord);
            Base::Vector3d f1 = cp + df * majdir;

            Base::Vector3d sf1 = f1 + 2.0 * (refpoint - f1);
            Base::Vector3d scp = cp + 2.0 * (refpoint - cp);

            geosymaoe->setMajorAxisDir(sf1 - scp);

            geosymaoe->setCenter(scp);
            isStartEndInverted.insert(std::make_pair(geoId, false));
        }
        else if (geosym->is<Part::GeomArcOfHyperbola>()) {
            auto* geosymaoe = static_cast<Part::GeomArcOfHyperbola*>(geosym);
            Base::Vector3d cp = geosymaoe->getCenter();

            Base::Vector3d majdir = geosymaoe->getMajorAxisDir();
            double majord = geosymaoe->getMajorRadius();
            double minord = geosymaoe->getMinorRadius();
            double df = sqrt(majord * majord + minord * minord);
            Base::Vector3d f1 = cp + df * majdir;

            Base::Vector3d sf1 = f1 + 2.0 * (refpoint - f1);
            Base::Vector3d scp = cp + 2.0 * (refpoint - cp);

            geosymaoe->setMajorAxisDir(sf1 - scp);

            geosymaoe->setCenter(scp);
            isStartEndInverted.insert(std::make_pair(geoId, false));
        }
        else if (geosym->is<Part::GeomArcOfParabola>()) {
            auto* geosymaoe = static_cast<Part::GeomArcOfParabola*>(geosym);
            Base::Vector3d cp = geosymaoe->getCenter();
            Base::Vector3d f1 = geosymaoe->getFocus();

            Base::Vector3d sf1 = f1 + 2.0 * (refpoint - f1);
            Base::Vector3d scp = cp + 2.0 * (refpoint - cp);

            geosymaoe->setXAxisDir(sf1 - scp);
            geosymaoe->setCenter(scp);

            isStartEndInverted.insert(std::make_pair(geoId, false));
        }
        else if (geosym->is<Part::GeomBSplineCurve>()) {
            auto* geosymbsp = static_cast<Part::GeomBSplineCurve*>(geosym);

            std::vector<Base::Vector3d> poles = geosymbsp->getPoles();

            for (auto& pole : poles) {
                pole = pole + 2.0 * (refpoint - pole);
            }

            geosymbsp->setPoles(poles);
        }
        else if (geosym->is<Part::GeomPoint>()) {
            auto* geosympoint = static_cast<Part::GeomPoint*>(geosym);
            Base::Vector3d cp = geosympoint->getPoint();

            geosympoint->setPoint(cp + 2.0 * (refpoint - cp));
            isStartEndInverted.insert(std::make_pair(geoId, false));
        }
        else {
            Base::Console().error("Unsupported Geometry!! Just copying it.\n");
            isStartEndInverted.insert(std::make_pair(geoId, false));
        }

        symmetricVals.push_back(geosym);
        geoIdMap.insert(std::make_pair(geoId, cgeoid));
        cgeoid++;
    }

    return symmetricVals;
}

int SketchObject::addCopy(
    const std::vector<int>& geoIdList,
    const Base::Vector3d& displacement,
    bool moveonly,
    bool clone,
    int csize,
    int rsize,
    bool constraindisplacement,
    double perpscale
)
{
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    const std::vector<Part::Geometry*>& geovals = getInternalGeometry();
    std::vector<Part::Geometry*> newgeoVals(geovals);

    const std::vector<Constraint*>& constrvals = this->Constraints.getValues();
    std::vector<Constraint*> newconstrVals(constrvals);

    if (!moveonly) {
        newgeoVals.reserve(geovals.size() + geoIdList.size());
    }

    std::vector<int> newgeoIdList(geoIdList);

    if (newgeoIdList.empty()) {  // default option to operate on all the geometry
        for (int i = 0; i < int(geovals.size()); i++) {
            newgeoIdList.push_back(i);
        }
    }

    int cgeoid = getHighestCurveIndex() + 1;

    int iterfirstgeoid = -1;

    Base::Vector3d iterfirstpoint;

    int refgeoid = -1;

    int colrefgeoid = 0, rowrefgeoid = 0;

    int currentrowfirstgeoid = -1, prevrowstartfirstgeoid = -1, prevfirstgeoid = -1;

    Sketcher::PointPos refposId = Sketcher::PointPos::none;

    std::map<int, int> geoIdMap;

    Base::Vector3d perpendicularDisplacement
        = Base::Vector3d(perpscale * displacement.y, perpscale * -displacement.x, 0);

    int x, y;

    auto makeCopyAtRowColumn = [&](int x, int y) {
        // the reference for constraining array elements is the first valid point of the first
        // element
        if (x == 0 && y == 0) {
            const Part::Geometry* geo = getGeometry(*(newgeoIdList.begin()));

            auto gf = GeometryFacade::getFacade(geo);

            if (gf->isInternalAligned() && !moveonly) {
                // only add this geometry if the corresponding geometry it defines is also in
                // the list.

                auto constrIt = std::ranges::find_if(constrvals, [&newgeoIdList](auto c) {
                    return (
                        c->Type == Sketcher::InternalAlignment && c->First == *(newgeoIdList.begin())
                    );
                });

                int definedGeo = (constrIt != constrvals.end()) ? (*constrIt)->Second
                                                                : GeoEnum::GeoUndef;

                if (std::ranges::find(newgeoIdList, definedGeo) == newgeoIdList.end()) {
                    // the first element setting the reference is an internal alignment
                    // geometry, wherein the geometry it defines is not part of the copy
                    // operation.
                    THROWM(
                        Base::ValueError,
                        "A move/copy/array operation on an internal alignment geometry is "
                        "only possible together with the geometry it defines."
                    );
                }
            }

            refgeoid = *(newgeoIdList.begin());
            currentrowfirstgeoid = refgeoid;
            iterfirstgeoid = refgeoid;
            if (geo->is<Part::GeomCircle>() || geo->is<Part::GeomEllipse>()) {
                refposId = Sketcher::PointPos::mid;
            }
            else {
                refposId = Sketcher::PointPos::start;
            }

            return;  // the first element is already in place
        }

        prevfirstgeoid = iterfirstgeoid;

        iterfirstgeoid = cgeoid;

        if (x == 0) {  // if first element of second row
            prevrowstartfirstgeoid = currentrowfirstgeoid;
            currentrowfirstgeoid = cgeoid;
        }

        for (auto it = newgeoIdList.cbegin(); it != newgeoIdList.cend(); ++it) {
            const Part::Geometry* geo = getGeometry(*it);

            Part::Geometry* geocopy;

            auto gf = GeometryFacade::getFacade(geo);

            if (gf->isInternalAligned() && !moveonly) {
                // only add this geometry if the corresponding geometry it defines is also in
                // the list.
                int definedGeo = GeoEnum::GeoUndef;

                auto constrIt = std::ranges::find_if(constrvals, [&it](auto c) {
                    return (c->Type == Sketcher::InternalAlignment && c->First == *it);
                });
                if (constrIt != constrvals.end()) {
                    definedGeo = (*constrIt)->Second;
                }

                if (std::ranges::find(newgeoIdList, definedGeo) == newgeoIdList.end()) {
                    // we should not copy internal alignment geometry, unless the element they
                    // define is also mirrored
                    continue;
                }
            }

            // We have already cloned all geometry and constraints, we only need a copy if not
            // moving
            if (!moveonly) {
                geocopy = geo->copy();
                generateId(geocopy);
            }
            else {
                geocopy = newgeoVals[*it];
            }

            // Handle Geometry
            if (geocopy->is<Part::GeomLineSegment>()) {
                auto* geosymline = static_cast<Part::GeomLineSegment*>(geocopy);
                Base::Vector3d ep = geosymline->getEndPoint();
                Base::Vector3d ssp = geosymline->getStartPoint() + double(x) * displacement
                    + double(y) * perpendicularDisplacement;

                geosymline->setPoints(
                    ssp,
                    ep + double(x) * displacement + double(y) * perpendicularDisplacement
                );

                if (it == newgeoIdList.begin()) {
                    iterfirstpoint = ssp;
                }
            }
            else if (geocopy->is<Part::GeomCircle>()) {
                auto* geosymcircle = static_cast<Part::GeomCircle*>(geocopy);
                Base::Vector3d cp = geosymcircle->getCenter();
                Base::Vector3d scp = cp + double(x) * displacement
                    + double(y) * perpendicularDisplacement;

                geosymcircle->setCenter(scp);

                if (it == newgeoIdList.begin()) {
                    iterfirstpoint = scp;
                }
            }
            else if (geocopy->is<Part::GeomArcOfCircle>()) {
                auto* geoaoc = static_cast<Part::GeomArcOfCircle*>(geocopy);
                Base::Vector3d cp = geoaoc->getCenter();
                Base::Vector3d scp = cp + double(x) * displacement
                    + double(y) * perpendicularDisplacement;

                geoaoc->setCenter(scp);

                if (it == newgeoIdList.begin()) {
                    iterfirstpoint = geoaoc->getStartPoint(true);
                }
            }
            else if (geocopy->is<Part::GeomEllipse>()) {
                auto* geosymellipse = static_cast<Part::GeomEllipse*>(geocopy);
                Base::Vector3d cp = geosymellipse->getCenter();
                Base::Vector3d scp = cp + double(x) * displacement
                    + double(y) * perpendicularDisplacement;

                geosymellipse->setCenter(scp);

                if (it == newgeoIdList.begin()) {
                    iterfirstpoint = scp;
                }
            }
            else if (geocopy->is<Part::GeomArcOfEllipse>()) {
                auto* geoaoe = static_cast<Part::GeomArcOfEllipse*>(geocopy);
                Base::Vector3d cp = geoaoe->getCenter();
                Base::Vector3d scp = cp + double(x) * displacement
                    + double(y) * perpendicularDisplacement;

                geoaoe->setCenter(scp);

                if (it == newgeoIdList.begin()) {
                    iterfirstpoint = geoaoe->getStartPoint(true);
                }
            }
            else if (geocopy->is<Part::GeomArcOfHyperbola>()) {
                auto* geoaoe = static_cast<Part::GeomArcOfHyperbola*>(geocopy);
                Base::Vector3d cp = geoaoe->getCenter();
                Base::Vector3d scp = cp + double(x) * displacement
                    + double(y) * perpendicularDisplacement;

                geoaoe->setCenter(scp);

                if (it == newgeoIdList.begin()) {
                    iterfirstpoint = geoaoe->getStartPoint(true);
                }
            }
            else if (geocopy->is<Part::GeomArcOfParabola>()) {
                auto* geoaoe = static_cast<Part::GeomArcOfParabola*>(geocopy);
                Base::Vector3d cp = geoaoe->getCenter();
                Base::Vector3d scp = cp + double(x) * displacement
                    + double(y) * perpendicularDisplacement;

                geoaoe->setCenter(scp);

                if (it == newgeoIdList.begin()) {
                    iterfirstpoint = geoaoe->getStartPoint(true);
                }
            }
            else if (geocopy->is<Part::GeomBSplineCurve>()) {
                auto* geobsp = static_cast<Part::GeomBSplineCurve*>(geocopy);

                std::vector<Base::Vector3d> poles = geobsp->getPoles();

                for (auto& pole : poles) {
                    pole = pole + double(x) * displacement + double(y) * perpendicularDisplacement;
                }

                geobsp->setPoles(poles);

                if (it == newgeoIdList.begin()) {
                    iterfirstpoint = geobsp->getStartPoint();
                }
            }
            else if (geocopy->is<Part::GeomPoint>()) {
                auto* geopoint = static_cast<Part::GeomPoint*>(geocopy);
                Base::Vector3d cp = geopoint->getPoint();
                Base::Vector3d scp = cp + double(x) * displacement
                    + double(y) * perpendicularDisplacement;
                geopoint->setPoint(scp);

                if (it == newgeoIdList.begin()) {
                    iterfirstpoint = scp;
                }
            }
            else {
                Base::Console().error("Unsupported Geometry!! Just skipping it.\n");
                continue;
            }

            if (!moveonly) {  // we are copying
                newgeoVals.push_back(geocopy);
                geoIdMap.insert(std::make_pair(*it, cgeoid));
                cgeoid++;
            }
        }

        if (moveonly) {
            return;
        }

        // handle geometry constraints
        for (const auto& constr : constrvals) {
            auto fit = geoIdMap.find(constr->First);

            if (fit == geoIdMap.end()) {
                continue;
            }

            // First of constraint is in geoIdList
            if (constr->Second == GeoEnum::GeoUndef /*&& constr->Third == GeoEnum::GeoUndef*/) {
                if ((constr->Type == Sketcher::DistanceX || constr->Type == Sketcher::DistanceY)
                    && constr->FirstPos != Sketcher::PointPos::none) {
                    continue;
                }
                // if it is not a point locking DistanceX/Y
                if ((constr->Type == Sketcher::DistanceX || constr->Type == Sketcher::DistanceY
                     || constr->Type == Sketcher::Distance || constr->Type == Sketcher::Diameter
                     || constr->Type == Sketcher::Weight || constr->Type == Sketcher::Radius)
                    && clone) {
                    // Distances on a single Element are mapped to equality
                    // constraints in clone mode
                    Constraint* constNew = constr->copy();
                    constNew->Type = Sketcher::Equal;
                    constNew->isDriving = true;
                    // first is already (constr->First)
                    constNew->Second = fit->second;
                    newconstrVals.push_back(constNew);
                    continue;
                }
                if (!(constr->Type == Sketcher::Angle && clone)) {
                    Constraint* constNew = constr->copy();
                    constNew->First = fit->second;
                    newconstrVals.push_back(constNew);
                    continue;
                }
                if (getGeometry(constr->First)->is<Part::GeomLineSegment>()) {
                    // Angles on a single Element are mapped to parallel
                    // constraints in clone mode
                    Constraint* constNew = constr->copy();
                    constNew->Type = Sketcher::Parallel;
                    constNew->isDriving = true;
                    // first is already (constr->First)
                    constNew->Second = fit->second;
                    newconstrVals.push_back(constNew);
                }
                continue;
            }

            // other geoids intervene in this constraint
            auto sit = geoIdMap.find(constr->Second);

            if (sit == geoIdMap.end()) {
                continue;
            }

            // Second is also in the list
            if (constr->Third == GeoEnum::GeoUndef) {
                if ((constr->Type == Sketcher::DistanceX || constr->Type == Sketcher::DistanceY
                     || constr->Type == Sketcher::Distance)
                    && (constr->First == constr->Second) && clone) {
                    // Distances on a two Elements, which must be points of the
                    // same line are mapped to equality constraints in clone
                    // mode
                    Constraint* constNew = constr->copy();
                    constNew->Type = Sketcher::Equal;
                    constNew->isDriving = true;
                    constNew->FirstPos = Sketcher::PointPos::none;
                    // first is already (constr->First)
                    constNew->Second = fit->second;
                    constNew->SecondPos = Sketcher::PointPos::none;
                    newconstrVals.push_back(constNew);
                    continue;
                }
                // remaining, this includes InternalAlignment constraints
                Constraint* constNew = constr->copy();
                constNew->First = fit->second;
                constNew->Second = sit->second;
                newconstrVals.push_back(constNew);
                continue;
            }

            auto tit = geoIdMap.find(constr->Third);

            if (tit != geoIdMap.end()) {
                continue;
            }

            // Third is also in the list
            Constraint* constNew = constr->copy();
            constNew->First = fit->second;
            constNew->Second = sit->second;
            constNew->Third = tit->second;

            newconstrVals.push_back(constNew);
        }

        // handle inter-geometry constraints
        if (!constraindisplacement) {
            // after each creation reset map so that the key-value is univoque (only for
            // operations other than move)
            geoIdMap.clear();
        }

        // add a construction line
        auto* constrline = new Part::GeomLineSegment();

        // position of the reference point
        Base::Vector3d sp = getPoint(refgeoid, refposId)
            + ((x == 0) ? (double(x) * displacement + double(y - 1) * perpendicularDisplacement)
                        : (double(x - 1) * displacement + double(y) * perpendicularDisplacement));

        // position of the current instance corresponding point
        Base::Vector3d ep = iterfirstpoint;
        constrline->setPoints(sp, ep);
        GeometryFacade::setConstruction(constrline, true);

        generateId(constrline);
        newgeoVals.push_back(constrline);

        Constraint* constNew;

        if (x == 0) {
            // first element of a row

            // add coincidents for construction line
            constNew = new Constraint();
            constNew->Type = Sketcher::Coincident;
            constNew->First = prevrowstartfirstgeoid;
            constNew->FirstPos = refposId;
            constNew->Second = cgeoid;
            constNew->SecondPos = Sketcher::PointPos::start;
            newconstrVals.push_back(constNew);

            constNew = new Constraint();
            constNew->Type = Sketcher::Coincident;
            constNew->First = iterfirstgeoid;
            constNew->FirstPos = refposId;
            constNew->Second = cgeoid;
            constNew->SecondPos = Sketcher::PointPos::end;
            newconstrVals.push_back(constNew);

            // it is the first added element of this row in the perpendicular to
            // displacementvector direction
            if (y == 1) {
                rowrefgeoid = cgeoid;
                cgeoid++;

                // add length (or equal if perpscale==1) and perpendicular
                if (perpscale == 1.0) {
                    constNew = new Constraint();
                    constNew->Type = Sketcher::Equal;
                    constNew->First = rowrefgeoid;
                    constNew->FirstPos = Sketcher::PointPos::none;
                    constNew->Second = colrefgeoid;
                    constNew->SecondPos = Sketcher::PointPos::none;
                    newconstrVals.push_back(constNew);
                }
                else {
                    constNew = new Constraint();
                    constNew->Type = Sketcher::Distance;
                    constNew->First = rowrefgeoid;
                    constNew->FirstPos = Sketcher::PointPos::none;
                    constNew->setValue(perpendicularDisplacement.Length());
                    newconstrVals.push_back(constNew);
                }

                constNew = new Constraint();
                constNew->Type = Sketcher::Perpendicular;
                constNew->First = rowrefgeoid;
                constNew->FirstPos = Sketcher::PointPos::none;
                constNew->Second = colrefgeoid;
                constNew->SecondPos = Sketcher::PointPos::none;
                newconstrVals.push_back(constNew);
            }
            else {
                // it is just one more element in the col direction
                cgeoid++;

                // all other first rowers get an equality and perpendicular constraint
                constNew = new Constraint();
                constNew->Type = Sketcher::Equal;
                constNew->First = rowrefgeoid;
                constNew->FirstPos = Sketcher::PointPos::none;
                constNew->Second = cgeoid - 1;
                constNew->SecondPos = Sketcher::PointPos::none;
                newconstrVals.push_back(constNew);

                constNew = new Constraint();
                constNew->Type = Sketcher::Perpendicular;
                constNew->First = cgeoid - 1;
                constNew->FirstPos = Sketcher::PointPos::none;
                constNew->Second = colrefgeoid;
                constNew->SecondPos = Sketcher::PointPos::none;
                newconstrVals.push_back(constNew);
            }
        }
        else {
            // any element not being the first element of a row

            // add coincidents for construction line
            constNew = new Constraint();
            constNew->Type = Sketcher::Coincident;
            constNew->First = prevfirstgeoid;
            constNew->FirstPos = refposId;
            constNew->Second = cgeoid;
            constNew->SecondPos = Sketcher::PointPos::start;
            newconstrVals.push_back(constNew);

            constNew = new Constraint();
            constNew->Type = Sketcher::Coincident;
            constNew->First = iterfirstgeoid;
            constNew->FirstPos = refposId;
            constNew->Second = cgeoid;
            constNew->SecondPos = Sketcher::PointPos::end;
            newconstrVals.push_back(constNew);

            if (y == 0 && x == 1) {
                // first element of the first row
                colrefgeoid = cgeoid;
                cgeoid++;

                // add length and Angle
                constNew = new Constraint();
                constNew->Type = Sketcher::Distance;
                constNew->First = colrefgeoid;
                constNew->FirstPos = Sketcher::PointPos::none;
                constNew->setValue(displacement.Length());
                newconstrVals.push_back(constNew);

                constNew = new Constraint();
                constNew->Type = Sketcher::Angle;
                constNew->First = colrefgeoid;
                constNew->FirstPos = Sketcher::PointPos::none;
                constNew->setValue(atan2(displacement.y, displacement.x));
                newconstrVals.push_back(constNew);
            }
            else {
                // any other element
                cgeoid++;

                // all other elements get an equality and parallel constraint
                constNew = new Constraint();
                constNew->Type = Sketcher::Equal;
                constNew->First = colrefgeoid;
                constNew->FirstPos = Sketcher::PointPos::none;
                constNew->Second = cgeoid - 1;
                constNew->SecondPos = Sketcher::PointPos::none;
                newconstrVals.push_back(constNew);

                constNew = new Constraint();
                constNew->Type = Sketcher::Parallel;
                constNew->First = cgeoid - 1;
                constNew->FirstPos = Sketcher::PointPos::none;
                constNew->Second = colrefgeoid;
                constNew->SecondPos = Sketcher::PointPos::none;
                newconstrVals.push_back(constNew);
            }
        }

        // after each creation reset map so that the key-value is univoque (only for
        // operations other than move)
        geoIdMap.clear();
    };

    for (y = 0; y < rsize; y++) {
        for (x = 0; x < csize; x++) {
            makeCopyAtRowColumn(x, y);
        }
    }

    // Block acceptGeometry in OnChanged to avoid unnecessary checks and updates
    {
        Base::StateLocker preventUpdate(internaltransaction, true);
        Geometry.setValues(std::move(newgeoVals));

        if (newconstrVals.size() > constrvals.size()) {
            Constraints.setValues(std::move(newconstrVals));
        }
    }

    // we inhibited update, so we trigger it now
    // Update geometry indices and rebuild vertexindex now via onChanged, so that
    // ViewProvider::UpdateData is triggered.
    Geometry.touch();

    return Geometry.getSize() - 1;
}
// clang-format off

bool SketchObject::convertToNURBS(int GeoId)
{
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    if (GeoId > getHighestCurveIndex()
        || (GeoId < 0 && -GeoId > static_cast<int>(ExternalGeo.getSize())) || GeoId == -1
        || GeoId == -2)
        return false;

    const Part::Geometry* geo = getGeometry(GeoId);

    if (geo->is<Part::GeomPoint>())
        return false;

    const auto* geo1 = static_cast<const Part::GeomCurve*>(geo);

    Part::GeomBSplineCurve* bspline;

    try {
        bspline = geo1->toNurbs(geo1->getFirstParameter(), geo1->getLastParameter());

        if (geo1->isDerivedFrom<Part::GeomArcOfConic>()) {
            const auto* geoaoc = static_cast<const Part::GeomArcOfConic*>(geo1);

            if (geoaoc->isReversed())
                bspline->reverse();
        }
    }
    catch (const Base::Exception& e) {
        Base::Console().error("%s\n", e.what());
        // revert to original values
        return false;
    }

    const std::vector<Part::Geometry*>& vals = getInternalGeometry();

    std::vector<Part::Geometry*> newVals(vals);

    // Block checks and updates in OnChanged to avoid unnecessary checks and updates
    {
        Base::StateLocker preventUpdate(internaltransaction, true);

        if (GeoId < 0) {// external geometry
            newVals.push_back(bspline);
            generateId(bspline);
        }
        else {// normal geometry

            newVals[GeoId] = bspline;
            GeometryFacade::copyId(geo, bspline);

            const std::vector<Sketcher::Constraint*>& cvals = Constraints.getValues();

            std::vector<Constraint*> newcVals(cvals);

            int index = cvals.size() - 1;
            // delete constraints on this elements other than coincident constraints (bspline does
            // not support them currently), except for coincidents on mid point of the
            // to-be-converted curve.
            for (; index >= 0; index--) {
                auto otherthancoincident = cvals[index]->Type != Sketcher::Coincident
                    && cvals[index]->involvesGeoId(GeoId);

                auto coincidentonmidpoint = cvals[index]->Type == Sketcher::Coincident
                    && cvals[index]->involvesGeoIdAndPosId(GeoId, Sketcher::PointPos::mid);

                if (otherthancoincident || coincidentonmidpoint)
                    newcVals.erase(newcVals.begin() + index);
            }

            this->Constraints.setValues(std::move(newcVals));
        }

        Geometry.setValues(std::move(newVals));
    }

    // trigger update now
    // Update geometry indices and rebuild vertexindex now via onChanged, so that
    // ViewProvider::UpdateData is triggered.
    Geometry.touch();

    return true;
}

bool SketchObject::increaseBSplineDegree(int GeoId, int degreeincrement /*= 1*/)
{
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    if (GeoId < 0 || GeoId > getHighestCurveIndex()) {
        return false;
    }

    const Part::Geometry* geo = getGeometry(GeoId);

    if (!geo->is<Part::GeomBSplineCurve>()) {
        return false;
    }

    const auto* bsp = static_cast<const Part::GeomBSplineCurve*>(geo);

    const Handle(Geom_BSplineCurve) curve = Handle(Geom_BSplineCurve)::DownCast(bsp->handle());

    std::unique_ptr<Part::GeomBSplineCurve> bspline(new Part::GeomBSplineCurve(curve));

    try {
        int cdegree = bspline->getDegree();

        bspline->increaseDegree(cdegree + degreeincrement);
    }
    catch (const Base::Exception& e) {
        Base::Console().error("%s\n", e.what());
        return false;
    }

    const std::vector<Part::Geometry*>& vals = getInternalGeometry();

    std::vector<Part::Geometry*> newVals(vals);

    GeometryFacade::copyId(geo, bspline.get());
    newVals[GeoId] = bspline.release();

    // AcceptGeometry called from onChanged
    Geometry.setValues(std::move(newVals));

    return true;
}

bool SketchObject::decreaseBSplineDegree(int GeoId, int degreedecrement /*= 1*/)
{
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    if (GeoId < 0 || GeoId > getHighestCurveIndex())
        return false;

    const Part::Geometry* geo = getGeometry(GeoId);

    if (!geo->is<Part::GeomBSplineCurve>())
        return false;

    const auto* bsp = static_cast<const Part::GeomBSplineCurve*>(geo);

    const Handle(Geom_BSplineCurve) curve = Handle(Geom_BSplineCurve)::DownCast(bsp->handle());

    std::unique_ptr<Part::GeomBSplineCurve> bspline(new Part::GeomBSplineCurve(curve));

    try {
        int cdegree = bspline->getDegree();

        // degree must be >= 1
        int maxdegree = cdegree - degreedecrement;
        if (maxdegree == 0)
            return false;
        bspline->approximate(Precision::Confusion(), 20, maxdegree, GeomAbs_C0);
    }
    catch (const Base::Exception& e) {
        Base::Console().error("%s\n", e.what());
        return false;
    }

    // FIXME: Avoid to delete the whole geometry but only delete invalid constraints
    // and unused construction geometries
#if 0
    const std::vector< Part::Geometry * > &vals = getInternalGeometry();

    std::vector< Part::Geometry * > newVals(vals);

    newVals[GeoId] = bspline.release();

    // AcceptGeometry called from onChanged
    Geometry.setValues(newVals);
#else
    delGeometry(GeoId);
    int newId = addGeometry(bspline.release());
    exposeInternalGeometry(newId);
#endif

    return true;
}

// clang-format on
bool SketchObject::modifyBSplineKnotMultiplicity(int GeoId, int knotIndex, int multiplicityincr)
{
    // no need to check input data validity as this is an sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    if (GeoId < 0 || GeoId > getHighestCurveIndex()) {
        THROWMT(
            Base::ValueError,
            QT_TRANSLATE_NOOP("Exceptions", "B-spline Geometry Index (GeoID) is out of bounds.")
        );
    }

    if (multiplicityincr == 0) {
        // no change in multiplicity
        THROWMT(
            Base::ValueError,
            QT_TRANSLATE_NOOP("Exceptions", "You are requesting no change in knot multiplicity.")
        );
    }

    const Part::Geometry* geo = getGeometry(GeoId);

    if (!geo->is<Part::GeomBSplineCurve>()) {
        THROWMT(
            Base::TypeError,
            QT_TRANSLATE_NOOP("Exceptions", "The Geometry Index (GeoId) provided is not a B-spline.")
        );
    }

    const auto* bsp = static_cast<const Part::GeomBSplineCurve*>(geo);

    int degree = bsp->getDegree();

    if (knotIndex > bsp->countKnots() || knotIndex < 1) {
        // knotindex in OCC 1 -> countKnots
        THROWMT(
            Base::ValueError,
            QT_TRANSLATE_NOOP(
                "Exceptions",
                "The knot index is out of bounds. Note that in accordance with "
                "OCC notation, the first knot has index 1 and not zero."
            )
        );
    }

    std::unique_ptr<Part::GeomBSplineCurve> bspline;

    int curmult = bsp->getMultiplicity(knotIndex);

    // zero is removing the knot, degree is just positional continuity
    if ((curmult + multiplicityincr) > degree) {
        THROWMT(
            Base::ValueError,
            QT_TRANSLATE_NOOP(
                "Exceptions",
                "The multiplicity cannot be increased beyond the degree of the B-spline."
            )
        );
    }

    // zero is removing the knot, degree is just positional continuity
    if ((curmult + multiplicityincr) < 0) {
        THROWMT(
            Base::ValueError,
            QT_TRANSLATE_NOOP("Exceptions", "The multiplicity cannot be decreased beyond zero.")
        );
    }

    try {
        bspline.reset(static_cast<Part::GeomBSplineCurve*>(bsp->clone()));

        if (multiplicityincr > 0) {  // increase multiplicity
            bspline->increaseMultiplicity(knotIndex, curmult + multiplicityincr);
        }
        else {  // decrease multiplicity
            bool result = bspline->removeKnot(knotIndex, curmult + multiplicityincr, 1E6);

            if (!result) {
                THROWMT(
                    Base::CADKernelError,
                    QT_TRANSLATE_NOOP(
                        "Exceptions",
                        "OCC is unable to decrease the multiplicity within the "
                        "maximum tolerance."
                    )
                );
            }
        }
    }
    catch (const Base::Exception& e) {
        Base::Console().error("%s\n", e.what());
        return false;
    }

    // we succeeded with the multiplicity modification, so alignment geometry may be
    // invalid/inconsistent for the new bspline
    std::vector<int> delGeoId;

    std::vector<Base::Vector3d> poles = bsp->getPoles();
    std::vector<Base::Vector3d> newPoles = bspline->getPoles();

    // on fully removing a knot the knot geometry changes
    std::vector<double> knots = bsp->getKnots();
    std::vector<double> newKnots = bspline->getKnots();

    std::map<Sketcher::InternalAlignmentType, std::vector<int>> indexInNew {
        {Sketcher::BSplineControlPoint, {}},
        {Sketcher::BSplineKnotPoint, {}}
    };
    indexInNew[Sketcher::BSplineControlPoint].reserve(poles.size());
    indexInNew[Sketcher::BSplineKnotPoint].reserve(knots.size());

    for (const auto& pole : poles) {
        const auto it = std::ranges::find(newPoles, pole);
        indexInNew[Sketcher::BSplineControlPoint].emplace_back(it - newPoles.begin());
    }
    std::ranges::replace(indexInNew[Sketcher::BSplineControlPoint], int(newPoles.size()), -1);

    for (const auto& knot : knots) {
        const auto it = std::ranges::find(newKnots, knot);
        indexInNew[Sketcher::BSplineKnotPoint].emplace_back(it - newKnots.begin());
    }
    std::ranges::replace(indexInNew[Sketcher::BSplineKnotPoint], int(newKnots.size()), -1);

    const std::vector<Sketcher::Constraint*>& cvals = Constraints.getValues();

    std::vector<Constraint*> newcVals(0);

    // modify pole and knot constraints
    for (const auto& constr : cvals) {
        if (!(constr->Type == Sketcher::InternalAlignment && constr->Second == GeoId)) {
            newcVals.push_back(constr);
            continue;
        }

        int index = indexInNew.at(constr->AlignmentType).at(constr->InternalAlignmentIndex);

        if (index == -1) {
            // it is an internal alignment geometry that is no longer valid
            // => delete it and the geometry
            delGeoId.push_back(constr->First);
            continue;
        }

        Constraint* newConstr = constr->clone();
        newConstr->InternalAlignmentIndex = index;
        newcVals.push_back(newConstr);
    }

    const std::vector<Part::Geometry*>& vals = getInternalGeometry();

    std::vector<Part::Geometry*> newVals(vals);

    GeometryFacade::copyId(geo, bspline.get());
    newVals[GeoId] = bspline.release();

    // Block acceptGeometry in OnChanged to avoid unnecessary checks and updates
    {
        Base::StateLocker preventUpdate(internaltransaction, true);
        Geometry.setValues(std::move(newVals));

        this->Constraints.setValues(std::move(newcVals));
    }

    // Trigger update now
    // Update geometry indices and rebuild vertexindex now via onChanged, so that
    // ViewProvider::UpdateData is triggered.
    if (!delGeoId.empty()) {
        delGeometriesExclusiveList(delGeoId);
    }
    else {
        Geometry.touch();
    }
    return true;
}

bool SketchObject::insertBSplineKnot(int GeoId, double param, int multiplicity)
{
    // TODO: Check if this is still valid: no need to check input data validity as this is an
    // sketchobject managed operation.
    Base::StateLocker lock(managedoperation, true);

    // handling unacceptable cases
    if (GeoId < 0 || GeoId > getHighestCurveIndex()) {
        THROWMT(
            Base::ValueError,
            QT_TRANSLATE_NOOP("Exceptions", "B-spline Geometry Index (GeoID) is out of bounds.")
        );
    }

    if (multiplicity == 0) {
        THROWMT(
            Base::ValueError,
            QT_TRANSLATE_NOOP("Exceptions", "Knot cannot have zero multiplicity.")
        );
    }

    const Part::Geometry* geo = getGeometry(GeoId);

    if (!geo->is<Part::GeomBSplineCurve>()) {
        THROWMT(
            Base::TypeError,
            QT_TRANSLATE_NOOP("Exceptions", "The Geometry Index (GeoId) provided is not a B-spline.")
        );
    }

    const auto* bsp = static_cast<const Part::GeomBSplineCurve*>(geo);

    int degree = bsp->getDegree();
    double firstParam = bsp->getFirstParameter();
    double lastParam = bsp->getLastParameter();

    if (multiplicity > degree) {
        THROWMT(
            Base::ValueError,
            QT_TRANSLATE_NOOP(
                "Exceptions",
                "Knot multiplicity cannot be higher than the degree of the B-spline."
            )
        );
    }

    if (param > lastParam || param < firstParam) {
        THROWMT(
            Base::ValueError,
            QT_TRANSLATE_NOOP("Exceptions", "Knot cannot be inserted outside the B-spline parameter range.")
        );
    }

    std::unique_ptr<Part::GeomBSplineCurve> bspline;

    // run the command
    try {
        bspline.reset(static_cast<Part::GeomBSplineCurve*>(bsp->clone()));

        bspline->insertKnot(param, multiplicity);
    }
    catch (const Base::Exception& e) {
        Base::Console().error("%s\n", e.what());
        return false;
    }

    // once command is run update the internal geometries
    std::vector<int> delGeoId;

    std::vector<Base::Vector3d> poles = bsp->getPoles();
    std::vector<Base::Vector3d> newPoles = bspline->getPoles();
    std::vector<int> poleIndexInNew(poles.size(), -1);

    for (size_t j = 0; j < poles.size(); j++) {
        const auto it = std::ranges::find(newPoles, poles[j]);
        poleIndexInNew[j] = it - newPoles.begin();
    }
    std::ranges::replace(poleIndexInNew, int(newPoles.size()), -1);

    std::vector<double> knots = bsp->getKnots();
    std::vector<double> newKnots = bspline->getKnots();
    std::vector<int> knotIndexInNew(knots.size(), -1);

    for (size_t j = 0; j < knots.size(); j++) {
        const auto it = std::ranges::find(newKnots, knots[j]);
        knotIndexInNew[j] = it - newKnots.begin();
    }
    std::ranges::replace(knotIndexInNew, int(newKnots.size()), -1);

    const std::vector<Sketcher::Constraint*>& cvals = Constraints.getValues();

    std::vector<Constraint*> newcVals(0);

    // modify pole and knot constraints
    for (const auto& constr : cvals) {
        if (!(constr->Type == Sketcher::InternalAlignment && constr->Second == GeoId)) {
            newcVals.push_back(constr);
            continue;
        }

        std::vector<int>* indexInNew = nullptr;

        if (constr->AlignmentType == Sketcher::BSplineControlPoint) {
            indexInNew = &poleIndexInNew;
        }
        else if (constr->AlignmentType == Sketcher::BSplineKnotPoint) {
            indexInNew = &knotIndexInNew;
        }
        else {
            // it is a bspline geometry, but not a controlpoint or knot
            newcVals.push_back(constr);
            continue;
        }

        if (indexInNew && indexInNew->at(constr->InternalAlignmentIndex) == -1) {
            // it is an internal alignment geometry that is no longer valid
            // => delete it and the pole circle
            delGeoId.push_back(constr->First);
            continue;
        }

        Constraint* newConstr = constr->clone();
        newConstr->InternalAlignmentIndex = indexInNew->at(constr->InternalAlignmentIndex);
        newcVals.push_back(newConstr);
    }

    const std::vector<Part::Geometry*>& vals = getInternalGeometry();

    std::vector<Part::Geometry*> newVals(vals);

    GeometryFacade::copyId(geo, bspline.get());
    newVals[GeoId] = bspline.release();

    // Block acceptGeometry in OnChanged to avoid unnecessary checks and updates
    {
        Base::StateLocker preventUpdate(internaltransaction, true);
        Geometry.setValues(std::move(newVals));

        this->Constraints.setValues(std::move(newcVals));
    }

    // Trigger update now
    // Update geometry indices and rebuild vertexindex now via onChanged, so that
    // ViewProvider::UpdateData is triggered.
    if (!delGeoId.empty()) {
        // NOTE: There have been a couple of instances when knot insertion has
        // led to a segmentation fault: see
        // https://forum.freecad.org/viewtopic.php?f=19&t=64962&sid=10272db50a635c633260517b14ecad37.
        // If a segfault happens again and a `Geometry.touch()` here fixes it,
        // it is possible that `delGeometriesExclusiveList` is causing an update
        // in constraint GUI features during an intermediate step.
        // See 247a9f0876a00e08c25b07d1f8802479d8623e87 for suggestions.
        // Geometry.touch();
        delGeometriesExclusiveList(delGeoId);
        return true;
    }

    Geometry.touch();

    return true;
}
// clang-format on
