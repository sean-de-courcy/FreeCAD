// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2022 Abdullah Tahiri <abdullah.tahiri.yo@gmail.com>     *
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

#pragma once

#include <cmath>
#include <numbers>

#include <Precision.hxx>

#include <algorithm>
#include <string>
#include <vector>

#include <Inventor/SbString.h>

#include <App/Application.h>
#include <Base/Quantity.h>
#include <Base/Tools.h>
#include <Gui/ForkKeymap.h>
#include <Gui/Notifications.h>
#include <Gui/Selection/SelectionFilter.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>

#include <Mod/Sketcher/App/SketchObject.h>

#include "DrawSketchHandler.h"
#include "SketchEnterTarget.h"
#include "Utils.h"
#include "ViewProviderSketch.h"

using namespace Sketcher;

namespace SketcherGui
{

class FilletSelection: public Gui::SelectionFilterGate
{
    App::DocumentObject* object;

public:
    explicit FilletSelection(App::DocumentObject* obj)
        : Gui::SelectionFilterGate(nullPointer())
        , object(obj)
    {}

    bool allow(App::Document* /*pDoc*/, App::DocumentObject* pObj, const char* sSubName) override
    {
        if (pObj != this->object) {
            return false;
        }
        if (Base::Tools::isNullOrEmpty(sSubName)) {
            return false;
        }
        std::string element(sSubName);
        if (element.substr(0, 4) == "Edge") {
            int GeoId = std::atoi(element.substr(4, 4000).c_str()) - 1;
            Sketcher::SketchObject* Sketch = static_cast<Sketcher::SketchObject*>(object);
            const Part::Geometry* geom = Sketch->getGeometry(GeoId);
            if (geom->isDerivedFrom<Part::GeomBoundedCurve>()) {
                return true;
            }
        }
        if (element.substr(0, 6) == "Vertex") {
            int VtId = std::atoi(element.substr(6, 4000).c_str()) - 1;
            Sketcher::SketchObject* Sketch = static_cast<Sketcher::SketchObject*>(object);
            std::vector<int> GeoIdList;
            std::vector<Sketcher::PointPos> PosIdList;
            Sketch->getDirectlyCoincidentPoints(VtId, GeoIdList, PosIdList);
            GeoIdList = Sketch->chooseFilletsEdges(GeoIdList);
            if (GeoIdList.size() == 2 && GeoIdList[0] >= 0 && GeoIdList[1] >= 0) {
                const Part::Geometry* geom1 = Sketch->getGeometry(GeoIdList[0]);
                const Part::Geometry* geom2 = Sketch->getGeometry(GeoIdList[1]);
                if (geom1->is<Part::GeomLineSegment>() && geom2->is<Part::GeomLineSegment>()) {
                    return true;
                }
                // TODO: This could return true for any curve as long as
                // int SketchObject::fillet(int GeoId, PointPos PosId, double radius, bool trim,
                // bool createCorner, bool chamfer) evaluates two correct points that can be bound
                // by an arc created using GeomArcOfCircle* createFilletGeometry(const Geometry*
                // geo1, const Geometry* geo2, const Base::Vector3d& refPnt1, const Base::Vector3d&
                // refPnt2, double radius, int& pos1, int& pos2, bool& reverse, Base::Vector3d&
                // cornerPoint) See int SketchObject::fillet(int GeoId, PointPos PosId, double
                // radius, bool trim, bool createCorner, bool chamfer)
            }
        }
        return false;
    }
};


class DrawSketchHandlerFillet;

namespace ConstructionMethods
{

enum class FilletConstructionMethod
{
    Fillet,
    Chamfer,
    End  // Must be the last one
};

}  // namespace ConstructionMethods

using DSHFilletController = DrawSketchDefaultWidgetController<
    DrawSketchHandlerFillet,
    StateMachines::TwoSeekEnd,
    /*PAutoConstraintSize =*/0,
    /*OnViewParametersT =*/OnViewParameters<0, 0>,  // NOLINT
    /*WidgetParametersT =*/WidgetParameters<1, 2>,  // NOLINT (FreeCAD-CH: the sizes)
    /*WidgetCheckboxesT =*/WidgetCheckboxes<1, 1>,  // NOLINT
    /*WidgetComboboxesT =*/WidgetComboboxes<1, 1>,  // NOLINT
    /*WidgetLineEditsT =*/WidgetLineEdits<0, 0>,
    ConstructionMethods::FilletConstructionMethod,
    /*bool PFirstComboboxIsConstructionMethod =*/true>;

using DSHFilletControllerBase = DSHFilletController::ControllerBase;

using DrawSketchHandlerFilletBase = DrawSketchControllableHandler<DSHFilletController>;

class DrawSketchHandlerFillet: public DrawSketchHandlerFilletBase, public SketchEnterTarget
{
    Q_DECLARE_TR_FUNCTIONS(SketcherGui::DrawSketchHandlerFillet)

    friend DSHFilletController;
    friend DSHFilletControllerBase;

public:
    explicit DrawSketchHandlerFillet(ConstructionMethod constrMethod = ConstructionMethod::Fillet)
        : DrawSketchHandlerFilletBase(constrMethod)
        , preserveCorner(true)
        , vtId(-1)
        , geoId1(GeoEnum::GeoUndef)
        , geoId2(GeoEnum::GeoUndef)
    {
        // FreeCAD-CH (ops#640, rank 42): the sizes last typed are the defaults
        ParameterGrp::handle hGrp = sizesGroup();
        filletRadius = std::max(0.0, hGrp->GetFloat("FilletRadius", defaultSize));
        chamferDistance = std::max(0.0, hGrp->GetFloat("ChamferDistance", defaultSize));
        chamferAngle = hGrp->GetFloat("ChamferAngle", defaultChamferAngle);
        if (chamferAngle <= 0.0 || chamferAngle >= 180.0) {  // NOLINT
            chamferAngle = defaultChamferAngle;
        }
    }
    ~DrawSketchHandlerFillet() override
    {
        Gui::Selection().rmvSelectionGate();
    }

    /// FreeCAD-CH (ops#640, hands-on C-4): a corner picked, its fillet previewed, waiting for
    /// Enter (or a click) to be made
    bool hasPendingFillet() const
    {
        return pendingVertex;
    }
    /// Enter (ViewProviderSketch::keyPressed): the previewed fillet is made. The handler may be
    /// gone after it (not in continuous mode): the caller touches it no more.
    void createPendingFillet()
    {
        if (pendingVertex && !isState(SelectMode::End)) {
            setState(SelectMode::End);
        }
    }
    bool takesEnter() const override
    {
        return hasPendingFillet();
    }
    void enterPressed() override
    {
        createPendingFillet();
    }

    /// FreeCAD-CH (ops#640, rank 42): where the fillet and chamfer sizes typed are kept
    static ParameterGrp::handle sizesGroup()
    {
        return App::GetApplication().GetParameterGroupByPath(
            "User parameter:BaseApp/Preferences/Mod/Sketcher/Tools"
        );
    }

private:
    void updateDataAndDrawToPosition(Base::Vector2d onSketchPos) override
    {
        switch (state()) {
            case SelectMode::SeekFirst: {
                vtId = getPreselectPoint();
                geoId1 = getPreselectCurve();
                firstPos = onSketchPos;
            } break;
            case SelectMode::SeekSecond: {
                // FreeCAD-CH (ops#640, C-4): the picked corner's fillet stays previewed
                if (pendingVertex) {
                    drawPendingFillet();
                    break;
                }
                geoId2 = getPreselectCurve();
                secondPos = onSketchPos;
            } break;
            default:
                break;
        }
    }

    /** FreeCAD-CH (ops#640, rank 42): the corner of two lines: the point where they meet and,
     * from it, the unit direction along each line toward the part of the line that stays.
     */
    struct LineCorner
    {
        Base::Vector3d vertex;
        Base::Vector3d dir1;
        Base::Vector3d dir2;
        /// How far each line runs from the vertex along its direction: the most a fillet or a
        /// chamfer may take of it
        double reach1 = 0;
        double reach2 = 0;
        bool valid = false;
    };

    /// How far \a line runs from \a vertex along \a dir (to its farther end)
    static double reachAlong(
        const Part::GeomLineSegment* line,
        const Base::Vector3d& vertex,
        const Base::Vector3d& dir
    )
    {
        return std::max((line->getStartPoint() - vertex) * dir, (line->getEndPoint() - vertex) * dir);
    }

    /// The corner at the two lines' coincident ends \a pos1 and \a pos2
    static LineCorner cornerAtEnds(
        const Part::GeomLineSegment* line1,
        PointPos pos1,
        const Part::GeomLineSegment* line2,
        PointPos pos2
    )
    {
        LineCorner corner;
        Base::Vector3d dir1 = line1->getEndPoint() - line1->getStartPoint();
        Base::Vector3d dir2 = line2->getEndPoint() - line2->getStartPoint();
        if (dir1.Length() < Precision::Confusion() || dir2.Length() < Precision::Confusion()) {
            return corner;
        }
        if (pos1 == PointPos::end) {
            dir1 = -dir1;
        }
        if (pos2 == PointPos::end) {
            dir2 = -dir2;
        }
        corner.vertex = pos1 == PointPos::end ? line1->getEndPoint() : line1->getStartPoint();
        corner.dir1 = dir1.Normalize();
        corner.dir2 = dir2.Normalize();
        corner.reach1 = reachAlong(line1, corner.vertex, corner.dir1);
        corner.reach2 = reachAlong(line2, corner.vertex, corner.dir2);
        corner.valid = true;
        return corner;
    }

    /// The corner where the two lines' extensions meet, on the sides of \a ref1 and \a ref2
    static LineCorner cornerBetween(
        const Part::GeomLineSegment* line1,
        const Base::Vector3d& ref1,
        const Part::GeomLineSegment* line2,
        const Base::Vector3d& ref2
    )
    {
        LineCorner corner;
        const Base::Vector3d start1 = line1->getStartPoint();
        const Base::Vector3d start2 = line2->getStartPoint();
        Base::Vector3d dir1 = line1->getEndPoint() - start1;
        Base::Vector3d dir2 = line2->getEndPoint() - start2;
        const double cross = dir1.x * dir2.y - dir1.y * dir2.x;
        if (std::abs(cross) <= Precision::Confusion() * dir1.Length() * dir2.Length()) {
            return corner;  // parallel (or a line of zero length)
        }
        const Base::Vector3d offset = start2 - start1;
        const double along1 = (offset.x * dir2.y - offset.y * dir2.x) / cross;
        corner.vertex = start1 + dir1 * along1;
        dir1.Normalize();
        dir2.Normalize();
        if ((ref1 - corner.vertex) * dir1 < 0) {
            dir1 = -dir1;
        }
        if ((ref2 - corner.vertex) * dir2 < 0) {
            dir2 = -dir2;
        }
        corner.dir1 = dir1;
        corner.dir2 = dir2;
        corner.reach1 = reachAlong(line1, corner.vertex, dir1);
        corner.reach2 = reachAlong(line2, corner.vertex, dir2);
        corner.valid = true;
        return corner;
    }

    /** The fillet radius whose arc meets both lines at \a distance from the corner, and the
     * distance along the second line at which a chamfer \a angleDeg off the first line meets it
     * (in the triangle the chamfer cuts off, the corner's own angle is at the vertex and
     * \a angleDeg at the first line). False where the angle doesn't fit the corner.
     */
    static bool chamferSizes(
        const LineCorner& corner,
        double distance,
        double angleDeg,
        double& radius,
        double& secondDistance
    )
    {
        const double alpha = corner.dir1.GetAngle(corner.dir2);
        const double phi = Base::toRadians(angleDeg);
        const double pi = std::numbers::pi;
        if (alpha < Precision::Angular() || alpha > pi - Precision::Angular() || phi <= 0.0
            || alpha + phi >= pi - Precision::Angular()) {
            return false;
        }
        radius = distance * std::tan(alpha / 2);
        secondDistance = distance * std::sin(phi) / std::sin(alpha + phi);
        return true;
    }

    /** The sizes the fields give for this corner: the fillet's radius, or the chamfer's (as the
     * radius of the fillet whose ends it joins) and, for a chamfer that isn't even, the distance
     * along the second line (else -1). A field at 0 keeps the size from the click (upstream's).
     * A size too large for the corner's lines keeps the size from the click too, with a message
     * (fillet() would fail on it). False, with a message, where the chamfer's angle doesn't fit
     * the corner.
     */
    bool sizesFromFields(const LineCorner& corner, bool isChamfer, double& radius, double& secondDistance)
    {
        secondDistance = -1;
        if (!isChamfer) {
            if (filletRadius <= Precision::Confusion()) {
                return true;
            }
            const double alpha = corner.valid ? corner.dir1.GetAngle(corner.dir2) : 0.0;
            // The arc meets each line at r / tan(alpha/2) from the corner
            if (alpha > Precision::Angular()) {
                const double tangentAt = filletRadius / std::tan(alpha / 2);
                if (tangentAt > std::min(corner.reach1, corner.reach2) + Precision::Confusion()) {
                    warnTooLarge(tr("Fillet"));
                    return true;
                }
            }
            radius = filletRadius;
            return true;
        }
        if (chamferDistance <= Precision::Confusion() || !corner.valid) {
            return true;
        }
        double chamferRadius = 0;
        double distance2 = 0;
        if (!chamferSizes(corner, chamferDistance, chamferAngle, chamferRadius, distance2)) {
            Gui::TranslatedUserWarning(
                sketchgui->getSketchObject(),
                tr("Chamfer"),
                tr("The chamfer's angle does not fit this corner: the angle and the corner's own "
                   "angle must add up to less than 180 degrees.")
            );
            return false;
        }
        if (chamferDistance > corner.reach1 + Precision::Confusion()
            || distance2 > corner.reach2 + Precision::Confusion()) {
            warnTooLarge(tr("Chamfer"));
            return true;
        }
        radius = chamferRadius;
        if (std::abs(distance2 - chamferDistance) > Precision::Confusion()) {
            secondDistance = distance2;
        }
        return true;
    }

    void warnTooLarge(const QString& caption) const
    {
        Gui::TranslatedUserWarning(
            sketchgui->getSketchObject(),
            caption,
            tr("The size in the tool's fields is too large for the lines at this corner: the size "
               "from the click is used.")
        );
    }

    /// The end of \a geoId nearest \a point
    static PointPos nearestEnd(SketchObject* obj, int geoId, const Base::Vector3d& point)
    {
        const double toStart = (obj->getPoint(geoId, PointPos::start) - point).Length();
        const double toEnd = (obj->getPoint(geoId, PointPos::end) - point).Length();
        return toStart <= toEnd ? PointPos::start : PointPos::end;
    }

    /** An uneven chamfer (FreeCAD-CH, ops#640, rank 42): fillet() made it even, at the first
     * distance on both lines, its ends held by the construction arc. The arc goes; the chamfer
     * line is tied to the two lines' ends, and the second line's end is moved to
     * \a secondDistance from the corner by the solver (the chamfer's end goes with it).
     */
    void makeChamferUneven(
        SketchObject* obj,
        int arcId,
        int chamferLineId,
        const LineCorner& corner,
        int line1,
        int line2,
        double secondDistance
    )
    {
        const Base::Vector3d onFirst = corner.vertex + corner.dir1 * chamferDistance;
        const Base::Vector3d onSecond = corner.vertex + corner.dir2 * secondDistance;

        // The trimmed lines are the ones tangent to the arc: line1 and line2 themselves, but with
        // the corner kept fillet() splits them, the corner pieces (construction) keep their ids
        // and the trimmed parts come after the arc
        std::vector<int> tangent;
        for (const auto* constraint : obj->Constraints.getValues()) {
            if (constraint->Type != Sketcher::Tangent) {
                continue;
            }
            if (constraint->Second == arcId && constraint->First != arcId) {
                tangent.push_back(constraint->First);
            }
            else if (constraint->First == arcId && constraint->Second != arcId) {
                tangent.push_back(constraint->Second);
            }
        }

        Gui::cmdAppObjectArgs(obj, "delGeometry(%d)", arcId);
        const int chamferId = chamferLineId - 1;  // after the arc, so one down
        if (tangent.size() == 2) {
            for (int& geoId : tangent) {
                geoId = geoId > arcId ? geoId - 1 : geoId;
            }
            auto reach = [&](int geoId, const Base::Vector3d& point) {
                return std::min((obj->getPoint(geoId, PointPos::start) - point).Length(),
                                (obj->getPoint(geoId, PointPos::end) - point).Length());
            };
            const bool firstIsFirst = reach(tangent[0], onFirst) <= reach(tangent[1], onFirst);
            line1 = firstIsFirst ? tangent[0] : tangent[1];
            line2 = firstIsFirst ? tangent[1] : tangent[0];
        }

        const PointPos chamferAtFirst = nearestEnd(obj, chamferId, onFirst);
        const PointPos chamferAtSecond = chamferAtFirst == PointPos::start ? PointPos::end
                                                                           : PointPos::start;
        const PointPos firstEnd = nearestEnd(obj, line1, corner.vertex);
        const PointPos secondEnd = nearestEnd(obj, line2, corner.vertex);

        Gui::cmdAppObjectArgs(
            obj,
            "addConstraint(Sketcher.Constraint('Coincident',%d,%d,%d,%d))",
            line1,
            static_cast<int>(firstEnd),
            chamferId,
            static_cast<int>(chamferAtFirst)
        );
        Gui::cmdAppObjectArgs(
            obj,
            "addConstraint(Sketcher.Constraint('Coincident',%d,%d,%d,%d))",
            line2,
            static_cast<int>(secondEnd),
            chamferId,
            static_cast<int>(chamferAtSecond)
        );
        try {
            Gui::cmdAppObjectArgs(
                obj,
                "moveGeometry(%d,%d,App.Vector(%.12g,%.12g,0),0)",
                line2,
                static_cast<int>(secondEnd),
                onSecond.x,
                onSecond.y
            );
        }
        catch (const Base::Exception& e) {
            // a sketch the solver can't move: the chamfer stays even, still joined
            Base::Console().log("Chamfer: the second distance is left to the solver (%s)\n", e.what());
        }
    }

    /** After fillet(), inside its transaction (FreeCAD-CH, ops#640, rank 42): the fillet gets
     * its radius dimension, as in Onshape; an uneven chamfer is made; construction lines give
     * construction (the arc fillet() adds first is at \a highestBefore + 1, a chamfer's line is
     * the last geometry).
     */
    void finishCorner(
        SketchObject* obj,
        int highestBefore,
        bool isChamfer,
        bool construction,
        const LineCorner& corner,
        int line1,
        int line2,
        double secondDistance
    )
    {
        const int arcId = highestBefore + 1;
        if (isChamfer) {
            int chamferLineId = getHighestCurveIndex();
            if (secondDistance > 0 && corner.valid && line1 >= 0 && line2 >= 0
                && chamferLineId > arcId) {
                makeChamferUneven(obj, arcId, chamferLineId, corner, line1, line2, secondDistance);
                chamferLineId = getHighestCurveIndex();
            }
            if (construction) {
                Gui::cmdAppObjectArgs(obj, "toggleConstruction(%d) ", chamferLineId);
            }
            return;
        }

        if (construction) {
            Gui::cmdAppObjectArgs(obj, "toggleConstruction(%d) ", arcId);
        }
        const Part::Geometry* arc = obj->getGeometry(arcId);
        if (arc && isArcOfCircle(*arc)) {
            Gui::cmdAppObjectArgs(
                obj,
                "addConstraint(Sketcher.Constraint('Radius',%d,%.12g))",
                arcId,
                static_cast<const Part::GeomArcOfCircle*>(arc)->getRadius()
            );
        }
    }

    void onReset() override
    {
        pendingVertex = false;
        toolWidgetManager.resetControls();
    }

    /** FreeCAD-CH (ops#640, hands-on C-4): Onshape's fillet previews a picked corner, with the
     * radius label, and makes it on Enter (or a click); Onshape's keymap only. A chamfer, and any
     * corner that isn't two lines, is made at the click as before.
     */
    bool previewsCorner(int vertex) const
    {
        LineCorner corner;
        return Gui::ForkKeymap::isOnshape() && constructionMethod() == ConstructionMethod::Fillet
            && vertexCorner(vertex, corner);
    }

    /// The corner of two lines at the sketch vertex \a vertex (as the fillet at a point takes it)
    bool vertexCorner(int vertex, LineCorner& corner) const
    {
        if (vertex < 0) {
            return false;
        }
        SketchObject* obj = sketchgui->getSketchObject();
        int geoId = GeoEnum::GeoUndef;
        PointPos posId = PointPos::none;
        obj->getGeoVertexIndex(vertex, geoId, posId);
        if (posId != PointPos::start && posId != PointPos::end) {
            return false;
        }
        std::vector<int> geoIds;
        std::vector<PointPos> posIds;
        obj->getDirectlyCoincidentPoints(geoId, posId, geoIds, posIds);
        geoIds = obj->chooseFilletsEdges(geoIds);
        if (geoIds.size() != 2 || posIds.size() < 2 || geoIds[0] < 0 || geoIds[1] < 0) {
            return false;
        }
        const Part::Geometry* geo1 = obj->getGeometry(geoIds[0]);
        const Part::Geometry* geo2 = obj->getGeometry(geoIds[1]);
        if (!geo1 || !geo2 || !isLineSegment(*geo1) || !isLineSegment(*geo2)) {
            return false;
        }
        corner = cornerAtEnds(
            static_cast<const Part::GeomLineSegment*>(geo1),
            posIds[0],
            static_cast<const Part::GeomLineSegment*>(geo2),
            posIds[1]
        );
        const double alpha = corner.valid ? corner.dir1.GetAngle(corner.dir2) : 0.0;
        return corner.valid && alpha > Precision::Angular()
            && alpha < std::numbers::pi - Precision::Angular();
    }

    /// The previewed fillet's arc and its "R..." label: the radius field's (the last typed), or
    /// the size from the click where the field is 0 or too large for the lines (as made)
    void drawPendingFillet()
    {
        LineCorner corner;
        if (!vertexCorner(vtId, corner)) {
            clearEdit();
            return;
        }
        const double pi = std::numbers::pi;
        const double alpha = corner.dir1.GetAngle(corner.dir2);
        const double reach = std::min(corner.reach1, corner.reach2);
        const double guess = reach * 0.2 * std::sin(alpha / 2);  // upstream's, at a point
        double radius = filletRadius > Precision::Confusion() ? filletRadius : guess;
        if (radius / std::tan(alpha / 2) > reach + Precision::Confusion()) {
            radius = guess;
        }
        const double tangentAt = radius / std::tan(alpha / 2);
        Base::Vector3d bisector = corner.dir1 + corner.dir2;
        bisector.Normalize();
        const Base::Vector3d centre = corner.vertex + bisector * (radius / std::sin(alpha / 2));
        const Base::Vector3d end1 = corner.vertex + corner.dir1 * tangentAt;
        const Base::Vector3d end2 = corner.vertex + corner.dir2 * tangentAt;
        const double start = std::atan2(end1.y - centre.y, end1.x - centre.x);
        double sweep = std::atan2(end2.y - centre.y, end2.x - centre.x) - start;
        while (sweep > pi) {
            sweep -= 2 * pi;
        }
        while (sweep < -pi) {
            sweep += 2 * pi;
        }
        constexpr int segments = 24;
        std::vector<Base::Vector2d> arc;
        arc.reserve(segments + 1);
        for (int i = 0; i <= segments; ++i) {
            const double angle = start + sweep * i / segments;
            arc.emplace_back(centre.x + radius * std::cos(angle), centre.y + radius * std::sin(angle));
        }
        drawEdit(arc);
        const std::string label =
            "R" + Base::Quantity(radius, Base::Unit::Length).getUserString();
        setPositionText(Base::Vector2d(centre.x, centre.y), SbString(label.c_str()));
    }

    void executeCommands() override
    {
        SketchObject* obj = sketchgui->getSketchObject();

        bool construction = false;
        bool isChamfer = constructionMethod() == ConstructionMethod::Chamfer;
        const int highestBefore = getHighestCurveIndex();

        if (vtId != -1) {
            int GeoId;
            PointPos PosId = PointPos::none;
            obj->getGeoVertexIndex(vtId, GeoId, PosId);
            if (PosId == PointPos::start || PosId == PointPos::end) {

                // guess fillet radius
                double radius = -1;
                LineCorner corner;
                int line1 = GeoEnum::GeoUndef;
                int line2 = GeoEnum::GeoUndef;
                std::vector<int> GeoIdList;
                std::vector<Sketcher::PointPos> PosIdList;
                obj->getDirectlyCoincidentPoints(GeoId, PosId, GeoIdList, PosIdList);
                GeoIdList = obj->chooseFilletsEdges(GeoIdList);
                if (GeoIdList.size() == 2 && GeoIdList[0] >= 0 && GeoIdList[1] >= 0) {
                    const Part::Geometry* geo1 = obj->getGeometry(GeoIdList[0]);
                    const Part::Geometry* geo2 = obj->getGeometry(GeoIdList[1]);

                    construction = GeometryFacade::getConstruction(geo1)
                        && GeometryFacade::getConstruction(geo2);

                    if (isLineSegment(*geo1) && isLineSegment(*geo2)) {
                        auto* lineSeg1 = static_cast<const Part::GeomLineSegment*>(geo1);
                        auto* lineSeg2 = static_cast<const Part::GeomLineSegment*>(geo2);
                        Base::Vector3d dir1 = lineSeg1->getEndPoint() - lineSeg1->getStartPoint();
                        Base::Vector3d dir2 = lineSeg2->getEndPoint() - lineSeg2->getStartPoint();
                        if (PosIdList[0] == PointPos::end) {
                            dir1 *= -1;
                        }
                        if (PosIdList[1] == PointPos::end) {
                            dir2 *= -1;
                        }
                        double l1 = dir1.Length();
                        double l2 = dir2.Length();
                        double angle = dir1.GetAngle(dir2);
                        radius = (l1 < l2 ? l1 : l2) * 0.2 * sin(angle / 2);

                        corner = cornerAtEnds(lineSeg1, PosIdList[0], lineSeg2, PosIdList[1]);
                        line1 = GeoIdList[0];
                        line2 = GeoIdList[1];
                    }
                }
                if (radius < 0) {
                    return;
                }

                double secondDistance = -1;
                if (!sizesFromFields(corner, isChamfer, radius, secondDistance)) {
                    return;
                }

                // create fillet at point
                try {
                    openCommand(QT_TRANSLATE_NOOP("Command", "Create fillet"));
                    Gui::cmdAppObjectArgs(
                        obj,
                        "fillet(%d,%d,%.12g,%s,%s,%s)",
                        GeoId,
                        static_cast<int>(PosId),
                        radius,
                        "True",
                        preserveCorner ? "True" : "False",
                        isChamfer ? "True" : "False"
                    );

                    finishCorner(
                        obj,
                        highestBefore,
                        isChamfer,
                        construction,
                        corner,
                        line1,
                        line2,
                        secondDistance
                    );

                    commitCommand();
                }
                catch (const Base::Exception& e) {
                    Gui::NotifyUserError(
                        obj,
                        QT_TRANSLATE_NOOP("Notifications", "Failed to create fillet"),
                        e.what()
                    );
                    abortCommand();
                }

                tryAutoRecomputeIfNotSolve(obj);
            }  // end if curve endpoint
        }  // end if vertex
        else {
            Base::Vector3d refPnt1(firstPos.x, firstPos.y, 0.f);
            Base::Vector3d refPnt2(secondPos.x, secondPos.y, 0.f);

            const Part::Geometry* geo1 = obj->getGeometry(geoId1);
            const Part::Geometry* geo2 = obj->getGeometry(geoId2);

            construction = GeometryFacade::getConstruction(geo1)
                && GeometryFacade::getConstruction(geo2);

            double radius = 0;
            LineCorner corner;

            if (isLineSegment(*geo1) && isLineSegment(*geo2)) {
                // guess fillet radius
                auto* line1 = static_cast<const Part::GeomLineSegment*>(geo1);
                auto* line2 = static_cast<const Part::GeomLineSegment*>(geo2);

                radius = Part::suggestFilletRadius(line1, line2, refPnt1, refPnt2);

                if (radius < 0) {
                    return;
                }

                corner = cornerBetween(line1, refPnt1, line2, refPnt2);
            }

            double secondDistance = -1;
            if (!sizesFromFields(corner, isChamfer, radius, secondDistance)) {
                Gui::Selection().clearSelection();
                return;
            }

            // create fillet between lines
            try {
                openCommand(QT_TRANSLATE_NOOP("Command", "Create fillet"));
                Gui::cmdAppObjectArgs(
                    obj,
                    "fillet(%d,%d,App.Vector(%f,%f,0),App.Vector(%f,%f,0),%.12g,%s,%s,%s)",
                    geoId1,
                    geoId2,
                    firstPos.x,
                    firstPos.y,
                    secondPos.x,
                    secondPos.y,
                    radius,
                    "True",
                    preserveCorner ? "True" : "False",
                    isChamfer ? "True" : "False"
                );
                finishCorner(
                    obj,
                    highestBefore,
                    isChamfer,
                    construction,
                    corner,
                    geoId1,
                    geoId2,
                    secondDistance
                );
                commitCommand();
            }
            catch (const Base::CADKernelError& e) {
                if (e.getTranslatable()) {
                    Gui::TranslatedUserError(
                        sketchgui,
                        tr("CAD Kernel Error"),
                        tr(e.getMessage().c_str())
                    );
                }
                Gui::Selection().clearSelection();
                abortCommand();
            }
            catch (const Base::ValueError& e) {
                Gui::TranslatedUserError(sketchgui, tr("Value Error"), tr(e.getMessage().c_str()));
                Gui::Selection().clearSelection();
                abortCommand();
            }
            catch (const Base::Exception& e) {
                // FreeCAD-CH: the Python error fillet() raises (a radius too large for the lines)
                Gui::NotifyUserError(
                    obj,
                    QT_TRANSLATE_NOOP("Notifications", "Failed to create fillet"),
                    e.what()
                );
                Gui::Selection().clearSelection();
                abortCommand();
            }

            tryAutoRecompute(obj);

            Gui::Selection().clearSelection();
        }
    }

    std::string getToolName() const override
    {
        return "DSH_Fillet";
    }

    QString getCrosshairCursorSVGName() const override
    {
        Gui::Selection().rmvSelectionGate();
        Gui::Selection().addSelectionGate(new FilletSelection(sketchgui->getObject()));

        if (constructionMethod() == DrawSketchHandlerFillet::ConstructionMethod::Fillet) {
            if (preserveCorner) {
                return QStringLiteral("Sketcher_Pointer_Create_PointFillet");
            }
            else {
                return QStringLiteral("Sketcher_Pointer_Create_Fillet");
            }
        }
        else {
            if (preserveCorner) {
                return QStringLiteral("Sketcher_Pointer_Create_PointChamfer");
            }
            else {
                return QStringLiteral("Sketcher_Pointer_Create_Chamfer");
            }
        }
    }

    std::unique_ptr<QWidget> createWidget() const override
    {
        return std::make_unique<SketcherToolDefaultWidget>();
    }

    bool isWidgetVisible() const override
    {
        return true;
    };

    QPixmap getToolIcon() const override
    {
        return Gui::BitmapFactory().pixmap("Sketcher_CreateFillet");
    }

    QString getToolWidgetText() const override
    {
        return QString(tr("Fillet/Chamfer Parameters"));
    }

    bool canGoToNextMode() override
    {
        if (state() == SelectMode::SeekFirst) {
            if (vtId != -1) {
                return true;
            }
            if (geoId1 >= 0) {
                const Part::Geometry* geo = sketchgui->getSketchObject()->getGeometry(geoId1);
                if (geo->isDerivedFrom<Part::GeomBoundedCurve>()) {
                    return true;
                }
            }
        }

        if (state() == SelectMode::SeekSecond) {
            if (geoId2 >= 0) {
                const Part::Geometry* geo = sketchgui->getSketchObject()->getGeometry(geoId2);
                if (geo->isDerivedFrom<Part::GeomBoundedCurve>()) {
                    return true;
                }
            }
        }

        return false;
    }

    void onButtonPressed(Base::Vector2d onSketchPos) override
    {
        this->updateDataAndDrawToPosition(onSketchPos);
        if (canGoToNextMode()) {
            if (state() == SelectMode::SeekFirst) {
                if (vtId != -1 && previewsCorner(vtId)) {
                    // FreeCAD-CH (ops#640, C-4): previewed first; Enter or a click makes it
                    pendingVertex = true;
                    moveToNextMode();
                    drawPendingFillet();
                }
                else if (vtId != -1) {
                    setState(SelectMode::End);
                }
                else {
                    // add the edge to the selection
                    std::stringstream ss;
                    ss << "Edge" << geoId1 + 1;
                    Gui::Selection().addSelection(
                        sketchgui->getSketchObject()->getDocument()->getName(),
                        sketchgui->getSketchObject()->getNameInDocument(),
                        ss.str().c_str(),
                        onSketchPos.x,
                        onSketchPos.y,
                        0.f
                    );
                    moveToNextMode();
                }
            }
            else {
                moveToNextMode();
            }
        }
        else if (pendingVertex && state() == SelectMode::SeekSecond) {
            // FreeCAD-CH (ops#640, C-4): a click makes the previewed fillet, as Enter does
            setState(SelectMode::End);
            return;  // the handler may be gone (not in continuous mode)
        }
        updateHint();
    }


private:
    bool preserveCorner;
    int vtId, geoId1, geoId2;
    Base::Vector2d firstPos, secondPos;
    /// FreeCAD-CH (ops#640, C-4): vtId's fillet is previewed, waiting for Enter or a click
    bool pendingVertex = false;

    // FreeCAD-CH (ops#640, rank 42): the fields' sizes (0: the size from the click, upstream's).
    // Before a size is typed: Onshape's fillet opens at 0.25 in (hands-on C-4); in millimetres,
    // the pack's unit, a round 5 mm [guess]; the chamfer the same, at 45 degrees.
    static constexpr double defaultSize = 5.0;           // mm
    static constexpr double defaultChamferAngle = 45.0;  // degrees
    double filletRadius = defaultSize;
    double chamferDistance = defaultSize;
    double chamferAngle = defaultChamferAngle;  // degrees, from the first line

public:
    std::list<Gui::InputHint> getToolHints() const override
    {
        using enum Gui::InputHint::UserInput;

        const Gui::InputHint switchModeHint {
            .message = tr("%1 switch mode"),
            .sequences = {toolKey(KeyM)}
        };
        const Gui::InputHint preserveCornerHint {
            .message = tr("%1 toggle preserve corner"),
            .sequences = {toolKey(KeyU)}
        };

        // FreeCAD-CH (ops#640, C-4): the previewed corner
        if (pendingVertex) {
            return {{tr("%1 create fillet"), {KeyReturn}}, {tr("%1 create fillet"), {MouseLeft}}};
        }

        return Gui::lookupHints<SelectMode>(
            state(),
            {
                {.state = SelectMode::SeekFirst,
                 .hints
                 = {{tr("%1 pick first edge or point"), {MouseLeft}},
                    switchModeHint,
                    preserveCornerHint}},
                {.state = SelectMode::SeekSecond,
                 .hints
                 = {{tr("%1 pick second edge"), {MouseLeft}}, switchModeHint, preserveCornerHint}},
                {.state = SelectMode::End,
                 .hints = {{tr("%1 create fillet"), {MouseLeft}}, switchModeHint, preserveCornerHint}},
            }
        );
    }
};

template<>
void DSHFilletController::configureToolWidget()
{
    if (!init) {  // Code to be executed only upon initialisation
        QStringList names = {QStringLiteral("Fillet"), QStringLiteral("Chamfer")};
        toolWidget->setComboboxElements(WCombobox::FirstCombo, names);

        toolWidget->setComboboxItemIcon(
            WCombobox::FirstCombo,
            0,
            Gui::BitmapFactory().iconFromTheme("Sketcher_CreateFillet")
        );
        toolWidget->setComboboxItemIcon(
            WCombobox::FirstCombo,
            1,
            Gui::BitmapFactory().iconFromTheme("Sketcher_CreateChamfer")
        );

        toolWidget->setCheckboxLabel(
            WCheckbox::FirstBox,
            QApplication::translate("TaskSketcherTool_c1_fillet", "Preserve corner (U)")
        );
        toolWidget->setCheckboxToolTip(
            WCheckbox::FirstBox,
            QApplication::translate(
                "TaskSketcherTool_c1_fillet",
                "Preserves intersection point and most constraints"
            )
        );

        toolWidget->setCheckboxIcon(
            WCheckbox::FirstBox,
            Gui::BitmapFactory().iconFromTheme("Sketcher_CreatePointFillet")
        );
    }
    syncCheckboxToHandler(WCheckbox::FirstBox, handler->preserveCorner);

    // FreeCAD-CH (ops#640, rank 42): Onshape's fields, the last size typed as the default. The
    // fillet's radius; the chamfer's distance from the corner along the first line (the first
    // pick, or the first of a vertex's two lines) and its angle to that line, 45 degrees.
    if (handler->constructionMethod() == ConstructionMethods::FilletConstructionMethod::Fillet) {
        toolWidget->setParameterLabel(
            WParameter::First,
            QApplication::translate("TaskSketcherTool_p1_fillet", "Radius")
        );
        toolWidget->configureParameterUnit(WParameter::First, Base::Unit::Length);
        toolWidget->configureParameterMin(WParameter::First, 0.0);
        toolWidget->configureParameterInitialValue(WParameter::First, handler->filletRadius);
    }
    else {
        toolWidget->setParameterLabel(
            WParameter::First,
            QApplication::translate("TaskSketcherTool_p1_fillet", "Distance")
        );
        toolWidget->configureParameterUnit(WParameter::First, Base::Unit::Length);
        toolWidget->configureParameterMin(WParameter::First, 0.0);
        toolWidget->configureParameterInitialValue(WParameter::First, handler->chamferDistance);

        toolWidget->setParameterLabel(
            WParameter::Second,
            QApplication::translate("TaskSketcherTool_p2_fillet", "Angle")
        );
        toolWidget->configureParameterUnit(WParameter::Second, Base::Unit::Angle);
        toolWidget->configureParameterMin(WParameter::Second, 0.0);
        toolWidget->configureParameterMax(WParameter::Second, 180.0);  // NOLINT
        toolWidget->configureParameterInitialValue(WParameter::Second, handler->chamferAngle);
    }
}

template<>
void DSHFilletController::adaptDrawingToParameterChange(int parameterindex, double value)
{
    // FreeCAD-CH (ops#640, rank 42): a size typed is the default from now on
    ParameterGrp::handle hGrp = DrawSketchHandlerFillet::sizesGroup();
    const bool isChamfer = handler->constructionMethod()
        == ConstructionMethods::FilletConstructionMethod::Chamfer;
    switch (parameterindex) {
        case WParameter::First:
            if (isChamfer) {
                handler->chamferDistance = std::max(0.0, value);
                hGrp->SetFloat("ChamferDistance", handler->chamferDistance);
            }
            else {
                handler->filletRadius = std::max(0.0, value);
                hGrp->SetFloat("FilletRadius", handler->filletRadius);
            }
            break;
        case WParameter::Second:
            if (isChamfer && value > 0.0 && value < 180.0) {  // NOLINT
                handler->chamferAngle = value;
                hGrp->SetFloat("ChamferAngle", handler->chamferAngle);
            }
            break;
        default:
            break;
    }
}

template<>
void DSHFilletController::adaptDrawingToCheckboxChange(int checkboxindex, bool value)
{
    Q_UNUSED(checkboxindex);

    switch (checkboxindex) {
        case WCheckbox::FirstBox:
            handler->preserveCorner = value;
            break;
    }

    handler->updateCursor();
}

}  // namespace SketcherGui
