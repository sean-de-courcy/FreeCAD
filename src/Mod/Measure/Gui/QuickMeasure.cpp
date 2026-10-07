// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2023 Pierre-Louis Boyer <development@Ondsel.com>        *
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


#include <cmath>
#include <vector>
#include <QLabel>
#include <QStatusBar>
#include <QTimer>

#include <BRep_Tool.hxx>
#include <Precision.hxx>
#include <TopoDS.hxx>


#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Link.h>
#include <App/Part.h>
#include <Base/UnitsApi.h>
#include <Gui/Application.h>
#include <Gui/MainWindow.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Control.h>

#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/DatumFeature.h>

#include <Mod/Measure/App/Measurement.h>

#include "QuickMeasure.h"

using namespace Measure;
using namespace MeasureGui;

FC_LOG_LEVEL_INIT("QuickMeasure", true, true)

QuickMeasure::QuickMeasure(QObject* parent)
    : QObject(parent)
    , measurement {new Measure::Measurement()}
{
    selectionTimer = new QTimer(this);
    pendingProcessing = false;
    connect(selectionTimer, &QTimer::timeout, this, &QuickMeasure::processSelection);
}

QuickMeasure::~QuickMeasure()
{
    delete selectionTimer;
    delete measurement;
}

void QuickMeasure::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (shouldMeasure(msg)) {
        if (!pendingProcessing) {
            selectionTimer->start(100);
        }
        pendingProcessing = true;
    }
}

void QuickMeasure::processSelection()
{
    if (pendingProcessing) {
        pendingProcessing = false;
        try {
            tryMeasureSelection();
        }
        catch (const Base::IndexError&) {
            // ignore this exception because it can be caused by trying to access a non-existing
            // sub-element e.g. when selecting a construction geometry in sketcher
        }
        catch (const Base::ValueError&) {
            // ignore this exception because it can be caused by trying to access a non-existing
            // sub-element e.g. when selecting a constraint in sketcher
        }
        catch (const Base::Exception& e) {
            e.reportException();
        }
        catch (const Standard_Failure& e) {
            FC_ERR(e);
        }
        catch (...) {
            FC_ERR("Unhandled unknown exception");
        }
    }
}

void QuickMeasure::tryMeasureSelection()
{
    Gui::Document* doc = Gui::Application::Instance->activeDocument();
    // FreeCAD-CH (ops#153): nothing of the last selection stays if this one throws
    showResult(QString(), {});
    measurement->clear();
    if (doc && Gui::Control().activeDialog(nullptr) == nullptr) {
        // we (still) have a doc and are not in a tool dialog where the user needs to click on stuff
        addSelectionToMeasurement();
    }
    printResult();
}

bool QuickMeasure::shouldMeasure(const Gui::SelectionChanges& msg) const
{
    if (!Gui::getMainWindow()->isRightSideMessageVisible()) {
        // don't measure if there's no where to show the result
        return false;
    }

    Gui::Document* doc = Gui::Application::Instance->activeDocument();
    if (!doc) {
        // no active document
        return false;
    }

    if (msg.Type == Gui::SelectionChanges::AddSelection
        || msg.Type == Gui::SelectionChanges::RmvSelection
        || msg.Type == Gui::SelectionChanges::SetSelection
        || msg.Type == Gui::SelectionChanges::ClrSelection) {
        // the event is about a change in selected objects
        return true;
    }
    return false;
}

bool QuickMeasure::isObjAcceptable(App::DocumentObject* obj)
{
    // only measure shapes. Exclude datums that derive from Part::Feature
    if (obj && obj->isDerivedFrom<Part::Feature>() && !obj->isDerivedFrom<Part::Datum>()) {
        return true;
    }

    return false;
}

void QuickMeasure::addSelectionToMeasurement()
{
    int count = 0;
    int limit = 100;

    // FreeCAD-CH (ops#153): collected, then set at once (addReference3D classifies the whole
    // list again on every call)
    std::vector<App::DocumentObject*> objects;
    std::vector<std::string> subs;

    auto selObjs = Gui::Selection().getSelectionEx(
        nullptr,
        App::DocumentObject::getClassTypeId(),
        Gui::ResolveMode::NoResolve
    );

    for (auto& selObj : selObjs) {
        App::DocumentObject* rootObj = selObj.getObject();
        const std::vector<std::string> subNames = selObj.getSubNames();

        // Check that there's not too many selection
        count += subNames.empty() ? 1 : subNames.size();
        if (count > limit) {
            measurement->clear();
            return;
        }

        if (subNames.empty()) {
            if (isObjAcceptable(rootObj)) {
                objects.push_back(rootObj);
                subs.emplace_back();
            }
            continue;
        }

        for (auto& subName : subNames) {
            App::DocumentObject* obj = rootObj->getSubObject(subName.c_str());

            if (!isObjAcceptable(obj)) {
                continue;
            }
            objects.push_back(rootObj);
            subs.push_back(subName);
        }
    }
    measurement->setReferences3D(objects, subs);
}

static QString areaStr(double value)
{
    Base::Quantity area(value, Base::Unit::Area);
    return QString::fromStdString(Base::UnitsApi::toUnicodeSuperscript(area.getUserString()));
}

static QString lengthStr(double value)
{
    Base::Quantity dist(value, Base::Unit::Length);
    return QString::fromStdString(dist.getUserString());
}

static QString angleStr(double value)
{
    Base::Quantity dist(value, Base::Unit::Angle);
    return QString::fromStdString(dist.getUserString());
}

// FreeCAD-CH (ops#153): x, y and z of a point or of a difference
static QString xyzStr(const QString& prefix, const Base::Vector3d& v)
{
    return QStringLiteral("%1X: %2, %1Y: %3, %1Z: %4")
        .arg(prefix, lengthStr(v.x), lengthStr(v.y), lengthStr(v.z));
}

// FreeCAD-CH (ops#153): the label shows the selection type's values as before, then, for two
// items, Min, Max and Center; three or more items show the summed lengths and areas. The
// label's tooltip has every value, one per line, plus the X/Y/Z differences
// (notes/measure-design.md)
void QuickMeasure::printResult()
{
    const int count = measurement->References3D.getSize();
    QStringList details;
    if (count >= 3) {
        const SumResult sums = measurement->sums();
        QStringList parts;
        if (sums.edges > 0) {
            parts << tr("Total length: %1").arg(lengthStr(sums.length));
        }
        if (sums.faces > 0) {
            parts << tr("Total area: %1").arg(areaStr(sums.area));
        }
        if (parts.isEmpty() && sums.vertices == count) {
            parts << tr("Vertices: %1").arg(sums.vertices);
        }
        showResult(parts.join(QStringLiteral(", ")), details);
        return;
    }

    label.clear();
    printTypeResult();

    MeasureType mtype = measurement->getType();
    if (count == 1 && mtype == MeasureType::Points) {
        const auto& objects = measurement->References3D.getValues();
        const auto& subNames = measurement->References3D.getSubValues();
        TopoDS_Shape shape = Part::Feature::getShape(
            objects[0],
            Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
                | Part::ShapeOption::Transform,
            subNames[0].c_str()
        );
        if (!shape.IsNull() && shape.ShapeType() == TopAbs_VERTEX) {
            gp_Pnt p = BRep_Tool::Pnt(TopoDS::Vertex(shape));
            details << xyzStr(QString(), Base::Vector3d(p.X(), p.Y(), p.Z()));
        }
    }
    if (count == 2 && mtype == MeasureType::PointToPoint) {
        details << xyzStr(QString(QChar(0x0394)), measurement->delta());
    }
    else if (count == 2) {
        const DistanceResult result = measurement->distances(timeLimit());
        QStringList parts;
        if (!label.isEmpty()) {
            parts << label;
        }

        // Parallel planes or lines already show their distance: Min only where it differs
        bool showMin = true;
        if (result.hasMin && mtype == MeasureType::TwoPlanes) {
            showMin = std::abs(result.min - measurement->planePlaneDistance())
                > Precision::Confusion();
        }
        else if (result.hasMin && mtype == MeasureType::TwoParallelLines) {
            showMin = std::abs(result.min - measurement->lineLineDistance())
                > Precision::Confusion();
        }
        if (!result.hasMin && result.timedOut) {
            parts << tr("Min: %1").arg(QString(QChar(0x2013)));
        }
        else if (result.hasMin && showMin) {
            parts << tr("Min: %1").arg(lengthStr(result.min));
        }
        if (result.hasMax) {
            const QString max = lengthStr(result.max);
            parts << tr("Max: %1").arg(
                result.maxExact ? max : QString(QChar(0x2248)) + QLatin1Char(' ') + max
            );
        }
        // Circles show their center distance, cylinders their axis distance already
        const bool showCenter = mtype != MeasureType::TwoCircles
            && mtype != MeasureType::PointToCircle && mtype != MeasureType::TwoCylinders
            && mtype != MeasureType::PointToCylinder && mtype != MeasureType::CircleToCylinder;
        if (result.hasCenter && showCenter) {
            parts << tr("Center: %1").arg(lengthStr(result.center));
        }
        label = parts.join(QStringLiteral(", "));

        const QString delta(QChar(0x0394));
        if (result.hasMin) {
            details << tr("Min %1").arg(xyzStr(delta, result.minTo - result.minFrom));
            if (result.inside) {
                details << tr("One shape lies inside the other");
            }
        }
        if (result.hasMax && !result.maxExact) {
            details << tr("Max is approximate (sampled)");
        }
        if (result.hasCenter) {
            details << tr("Center %1").arg(xyzStr(delta, result.centerTo - result.centerFrom));
        }
        if (result.timedOut) {
            details << tr("Skipped: over %1 ms").arg(timeLimit());
        }
    }
    showResult(label, details);
}

// FreeCAD-CH (ops#153): the time limit of the two-item distances, in ms (hidden parameter)
int QuickMeasure::timeLimit()
{
    return static_cast<int>(
        App::GetApplication()
            .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/Measure")
            ->GetInt("QuickMeasureTimeLimit", 200)
    );
}

// The values of the selection type (before ops#153, the whole result)
void QuickMeasure::printTypeResult()
{
    MeasureType mtype = measurement->getType();
    if (mtype == MeasureType::Surfaces) {
        print(tr("Total area: %1").arg(areaStr(measurement->area())));
    }
    /* deactivated because computing the volumes/area of solids makes a significant
    slow down in selection of complex solids.
    else if (mtype == MeasureType::Volumes) {
        Base::Quantity area(measurement->area(), Base::Unit::Area);
        Base::Quantity vol(measurement->volume(), Base::Unit::Volume);
        print(tr("Volume: %1, Area:
    %2").arg(vol.getSafeUserString()).arg(area.getSafeUserString()));
    }*/
    else if (mtype == MeasureType::TwoPlanes) {
        print(tr("Nominal distance: %1").arg(lengthStr(measurement->planePlaneDistance())));
    }
    else if (mtype == MeasureType::Cone || mtype == MeasureType::Plane) {
        print(tr("Area: %1").arg(areaStr(measurement->area())));
    }
    else if (
        mtype == MeasureType::CylinderSection || mtype == MeasureType::Sphere
        || mtype == MeasureType::Torus
    ) {
        print(tr("Area: %1, Radius: %2")
                  .arg(areaStr(measurement->area()), lengthStr(measurement->radius())));
    }
    else if (mtype == MeasureType::Cylinder || mtype == MeasureType::Disc) {
        print(tr("Area: %1, Diameter: %2")
                  .arg(areaStr(measurement->area()), lengthStr(measurement->diameter())));
    }
    else if (mtype == MeasureType::TwoCylinders) {

        double angle = measurement->angle();

        if (angle <= Precision::Confusion()) {
            print(
                tr("Total area: %1, Axis distance: %2")
                    .arg(areaStr(measurement->area()), lengthStr(measurement->cylinderAxisDistance()))
            );
        }
        else {
            print(tr("Total area: %1, Axis distance: %2, Axis angle: %3")
                      .arg(
                          areaStr(measurement->area()),
                          lengthStr(measurement->cylinderAxisDistance()),
                          angleStr(angle)
                      ));
        }
    }
    else if (mtype == MeasureType::Edges) {
        print(tr("Total length: %1").arg(lengthStr(measurement->length())));
    }
    else if (mtype == MeasureType::TwoParallelLines) {
        print(tr("Nominal distance: %1").arg(lengthStr(measurement->lineLineDistance())));
    }
    else if (mtype == MeasureType::TwoLines) {
        print(tr("Angle: %1, Total length: %2")
                  .arg(angleStr(measurement->angle()), lengthStr(measurement->length())));
    }
    else if (mtype == MeasureType::Line) {
        print(tr("Length: %1").arg(lengthStr(measurement->length())));
    }
    else if (mtype == MeasureType::CircleArc) {
        print(tr("Radius: %1").arg(lengthStr(measurement->radius())));
    }
    else if (mtype == MeasureType::Circle) {
        print(tr("Diameter: %1").arg(lengthStr(measurement->diameter())));
    }
    else if (mtype == MeasureType::PointToPoint) {
        print(tr("Distance: %1").arg(lengthStr(measurement->length())));
    }
    else if (mtype == MeasureType::PointToEdge || mtype == MeasureType::PointToSurface) {
        // FreeCAD-CH (ops#153): Min comes with the distances
        print(QString());
    }
    else if (mtype == MeasureType::PointToCylinder) {
        print(tr("Axis distance: %1").arg(lengthStr(measurement->cylinderAxisDistance())));
    }
    else if (mtype == MeasureType::PointToCircle) {
        // FreeCAD-CH (ops#153): Min comes with the distances
        print(tr("Center distance: %1").arg(lengthStr(measurement->circleCenterDistance())));
    }
    else if (mtype == MeasureType::TwoCircles) {
        double angle = measurement->angle();
        if (angle <= Precision::Confusion()) {
            print(tr("Total length: %1, Center distance: %2")
                      .arg(
                          lengthStr(measurement->length()),
                          lengthStr(measurement->circleCenterDistance())
                      ));
        }
        else {
            print(tr("Total length: %1, Center distance: %2, Axis angle: %3")
                      .arg(
                          lengthStr(measurement->length()),
                          lengthStr(measurement->circleCenterDistance()),
                          angleStr(angle)
                      ));
        }
    }
    else if (mtype == MeasureType::CircleToEdge) {
        print(
            tr("Total length: %1, Center distance: %2")
                .arg(lengthStr(measurement->length()), lengthStr(measurement->circleCenterDistance()))
        );
    }
    else if (mtype == MeasureType::CircleToSurface) {
        print(tr("Center surface distance: %1").arg(lengthStr(measurement->circleCenterDistance())));
    }
    else if (mtype == MeasureType::CircleToCylinder) {
        double angle = measurement->angle();
        if (angle <= Precision::Confusion()) {
            print(tr("Center axis distance: %1").arg(lengthStr(measurement->cylinderAxisDistance())));
        }
        else {
            print(tr("Center axis distance: %1, Axis angle: %2")
                      .arg(lengthStr(measurement->cylinderAxisDistance()), angleStr(angle)));
        }
    }
    else {
        print(QStringLiteral(""));
    }
}

// FreeCAD-CH (ops#153): keeps the type's values for printResult(), which shows them
void QuickMeasure::print(const QString& message)
{
    label = message;
}

// FreeCAD-CH (ops#153): the label, and a tooltip with its values one per line plus details
void QuickMeasure::showResult(const QString& message, const QStringList& details)
{
    Gui::getMainWindow()->setRightSideMessage(message);
    auto statusLabel =
        Gui::getMainWindow()->statusBar()->findChild<QLabel*>(QStringLiteral("rightSideLabel"));
    if (statusLabel) {
        QStringList lines;
        if (!message.isEmpty()) {
            lines = message.split(QStringLiteral(", "));
        }
        lines << details;
        statusLabel->setToolTip(lines.join(QLatin1Char('\n')));
    }
}


#include "moc_QuickMeasure.cpp"
