// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer                                       *
 *                                      <jrheinlaender@users.sourceforge.net> *
 *                                                                            *
 *   This file is part of the FreeCAD CAx development system.                 *
 *                                                                            *
 *   This library is free software; you can redistribute it and/or            *
 *   modify it under the terms of the GNU Library General Public              *
 *   License as published by the Free Software Foundation; either             *
 *   version 2 of the License, or (at your option) any later version.         *
 *                                                                            *
 *   This library  is distributed in the hope that it will be useful,         *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of           *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            *
 *   GNU Library General Public License for more details.                     *
 *                                                                            *
 *   You should have received a copy of the GNU Library General Public        *
 *   License along with this library; see the file COPYING.LIB. If not,       *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,            *
 *   Suite 330, Boston, MA  02111-1307, USA                                   *
 *                                                                            *
 ******************************************************************************/


#include <QListIterator>
#include <QListWidgetItem>
#include <QTimer>

#include <BRepGProp.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <Precision.hxx>
#include <TopoDS.hxx>

#include <algorithm>
#include <cctype>
#include <ranges>

#include <fmt/format.h>

#include <App/Document.h>
#include <App/ElementNamingUtils.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <App/Origin.h>
#include <App/Datums.h>
#include <App/Part.h>
#include <Base/Console.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Control.h>
#include <Gui/ViewProviderCoordinateSystem.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/ShapeBinder.h>
#include <Mod/PartDesign/App/DatumLine.h>
#include <Mod/PartDesign/App/DatumPlane.h>
#include <Mod/PartDesign/App/DatumPoint.h>
#include <Mod/PartDesign/App/FeaturePrimitive.h>
#include <Mod/Sketcher/App/ExternalGeometryFacade.h>
#include <Mod/Sketcher/App/SketchObject.h>

#include "ui_TaskFeaturePick.h"
#include "TaskFeaturePick.h"
#include "Utils.h"

#include <Gui/ViewParams.h>


using namespace PartDesignGui;
using namespace Attacher;

// TODO Do ve should snap here to App:Part or GeoFeatureGroup/DocumentObjectGroup ? (2015-09-04,
// Fat-Zer)
const QString TaskFeaturePick::getFeatureStatusString(const featureStatus st)
{
    switch (st) {
        case validFeature:
            return tr("Valid");
        case invalidShape:
            return tr("Invalid shape");
        case noWire:
            return tr("No wire in sketch");
        case isUsed:
            return tr("Sketch already used by other feature");
        case otherBody:
            return tr("Belongs to another body");
        case otherPart:
            return tr("Belongs to another part");
        case notInBody:
            return tr("Doesn't belong to any body");
        case basePlane:
            return tr("Base plane");
        case afterTip:
            return tr("Feature is located after the tip of the body");
    }

    return QString();
}

TaskFeaturePick::TaskFeaturePick(
    std::vector<App::DocumentObject*>& objects,
    const std::vector<featureStatus>& status,
    bool singleFeatureSelect,
    QWidget* parent
)
    : TaskBox(Gui::BitmapFactory().pixmap("edit-select-all"), tr("Select Attachment"), true, parent)
    , ui(new Ui_TaskFeaturePick)
    , doSelection(false)
{

    proxy = new QWidget(this);
    ui->setupUi(proxy);

    // clang-format off
    connect(ui->checkUsed, &QCheckBox::toggled, this, &TaskFeaturePick::onUpdate);
    connect(ui->checkOtherBody, &QCheckBox::toggled, this, &TaskFeaturePick::onUpdate);
    connect(ui->checkOtherPart, &QCheckBox::toggled, this, &TaskFeaturePick::onUpdate);
    connect(ui->radioIndependent, &QRadioButton::toggled, this, &TaskFeaturePick::onUpdate);
    connect(ui->radioDependent, &QRadioButton::toggled, this, &TaskFeaturePick::onUpdate);
    connect(ui->radioXRef, &QRadioButton::toggled, this, &TaskFeaturePick::onUpdate);
    connect(ui->listWidget, &QListWidget::itemSelectionChanged, this, &TaskFeaturePick::onItemSelectionChanged);
    connect(ui->listWidget, &QListWidget::itemDoubleClicked, this, &TaskFeaturePick::onDoubleClick);
    // clang-format on


    if (!singleFeatureSelect) {
        ui->listWidget->setSelectionMode(QAbstractItemView::ExtendedSelection);
    }

    // NOTE: generally there shouldn't be more then one origin
    std::map<App::Origin*, Gui::DatumElements> originVisStatus;

    auto statusIt = status.cbegin();
    auto objIt = objects.begin();
    assert(status.size() == objects.size());

    bool attached = false;
    for (; statusIt != status.end(); ++statusIt, ++objIt) {
        QListWidgetItem* item = new QListWidgetItem(QStringLiteral("%1 (%2)").arg(
            QString::fromUtf8((*objIt)->Label.getValue()),
            getFeatureStatusString(*statusIt)
        ));
        item->setData(Qt::UserRole, QString::fromLatin1((*objIt)->getNameInDocument()));
        ui->listWidget->addItem(item);

        App::Document* pDoc = (*objIt)->getDocument();
        documentName = pDoc->getName();
        if (!attached) {
            attached = true;
            attachDocument(Gui::Application::Instance->getDocument(pDoc));
        }

        // check if we need to set any origin in temporary visibility mode
        auto* datum = dynamic_cast<App::DatumElement*>(*objIt);
        if ((*statusIt == validFeature || *statusIt == basePlane) && datum) {
            auto* origin = dynamic_cast<App::Origin*>(datum->getLCS());
            if (origin) {
                if ((*objIt)->isDerivedFrom<App::Plane>()) {
                    originVisStatus[origin].setFlag(Gui::DatumElement::Planes, true);
                }
                else if ((*objIt)->isDerivedFrom<App::Line>()) {
                    originVisStatus[origin].setFlag(Gui::DatumElement::Axes, true);
                }
            }
        }
    }

    // Setup the origin's temporary visibility
    for (const auto& originPair : originVisStatus) {
        const auto& origin = originPair.first;

        auto* vpo = static_cast<Gui::ViewProviderCoordinateSystem*>(
            Gui::Application::Instance->getViewProvider(origin)
        );
        if (vpo) {
            vpo->setTemporaryVisibility(originVisStatus[origin]);
            vpo->setTemporaryScale(Gui::ViewParams::instance()->getDatumTemporaryScaleFactor());
            vpo->setPlaneLabelVisibility(true);
            origins.push_back(vpo);
        }
    }

    // TODO may be update origin API to show only some objects (2015-08-31, Fat-Zer)

    groupLayout()->addWidget(proxy);
    statuses = status;
    updateList();
}

TaskFeaturePick::~TaskFeaturePick()
{
    for (Gui::ViewProviderCoordinateSystem* vpo : origins) {
        vpo->resetTemporaryVisibility();
        vpo->resetTemporarySize();
        vpo->setPlaneLabelVisibility(false);
    }
}

void TaskFeaturePick::updateList()
{
    int index = 0;

    for (auto status : statuses) {
        QListWidgetItem* item = ui->listWidget->item(index);

        switch (status) {
            case validFeature:
                item->setHidden(false);
                break;
            case invalidShape:
                item->setHidden(true);
                break;
            case isUsed:
                item->setHidden(!ui->checkUsed->isChecked());
                break;
            case noWire:
                item->setHidden(true);
                break;
            case otherBody:
                item->setHidden(!ui->checkOtherBody->isChecked());
                break;
            case otherPart:
                item->setHidden(!ui->checkOtherPart->isChecked());
                break;
            case notInBody:
                item->setHidden(!ui->checkOtherPart->isChecked());
                break;
            case basePlane:
                item->setHidden(false);
                break;
            case afterTip:
                item->setHidden(true);
                break;
        }

        index++;
    }
}

void TaskFeaturePick::onUpdate(bool)
{
    bool enable = false;
    if (ui->checkOtherBody->isChecked() || ui->checkOtherPart->isChecked()) {
        enable = true;
    }

    ui->radioDependent->setEnabled(enable);
    ui->radioIndependent->setEnabled(enable);
    ui->radioXRef->setEnabled(enable);

    updateList();
}

std::vector<App::DocumentObject*> TaskFeaturePick::getFeatures()
{
    features.clear();
    QListIterator<QListWidgetItem*> i(ui->listWidget->selectedItems());
    while (i.hasNext()) {

        auto item = i.next();
        if (item->isHidden()) {
            continue;
        }

        QString t = item->data(Qt::UserRole).toString();
        features.push_back(t);
    }

    std::vector<App::DocumentObject*> result;

    for (const auto& feature : features) {
        result.push_back(
            App::GetApplication().getDocument(documentName.c_str())->getObject(feature.toLatin1().data())
        );
    }

    return result;
}

namespace
{

// FreeCAD-CH (ops#245): a sketch copied into the body is attached to the body's XY plane, with its
// Placement (where the original is, decision 40) as the offset. fixSketchSupport threw for a sketch
// plane not parallel to one of the base planes ("Sketch plane cannot be migrated", in a rotated
// body), and dropped the sketch's offset and rotation in its plane.
void attachInPlace(Sketcher::SketchObject* sketch, PartDesign::Body* body)
{
    App::Origin* origin = body->getOrigin();
    App::Plane* plane = origin->getXY();
    const Base::Placement planePlacement =
        origin->Placement.getValue() * plane->Placement.getValue();
    const Base::Placement placement = sketch->Placement.getValue();
    sketch->AttachmentSupport.setValue(plane, "");
    sketch->MapReversed.setValue(false);
    sketch->AttachmentOffset.setValue(planePlacement.inverse() * placement);
    sketch->MapMode.setValue(Attacher::mmFlatFace);
}

}  // namespace

std::vector<App::DocumentObject*> TaskFeaturePick::buildFeatures()
{
    int index = 0;
    std::vector<App::DocumentObject*> result;
    try {
        auto activeBody = PartDesignGui::getBody(false);
        if (!activeBody) {
            return result;
        }

        auto activePart = PartDesignGui::getPartFor(activeBody, false);

        for (auto status : statuses) {
            QListWidgetItem* item = ui->listWidget->item(index);

            if (item->isSelected() && !item->isHidden()) {
                QString t = item->data(Qt::UserRole).toString();
                auto obj = App::GetApplication()
                               .getDocument(documentName.c_str())
                               ->getObject(t.toLatin1().data());

                // build the dependent copy or reference if wanted by the user
                if (status == otherBody || status == otherPart || status == notInBody) {
                    if (!ui->radioXRef->isChecked()) {
                        // where it's added below
                        App::DocumentObject* target = activeBody;
                        if (status == otherPart && !PartDesignGui::getBodyFor(obj, false)) {
                            target = activePart;
                        }
                        auto copy = makeCopy(obj, "", ui->radioIndependent->isChecked(), target);

                        if (status == otherBody) {
                            activeBody->addObject(copy);
                        }
                        else if (status == otherPart) {
                            auto oBody = PartDesignGui::getBodyFor(obj, false);
                            if (!oBody) {
                                activePart->addObject(copy);
                            }
                            else {
                                activeBody->addObject(copy);
                            }
                        }
                        else if (status == notInBody) {
                            activeBody->addObject(copy);
                            // doesn't supposed to get here anything but sketch but to be on the
                            // safe side better to check
                            if (auto* sketch = freecad_cast<Sketcher::SketchObject*>(copy)) {
                                attachInPlace(sketch, activeBody);
                            }
                        }
                        result.push_back(copy);
                    }
                    else {
                        result.push_back(obj);
                    }
                }
                else {
                    result.push_back(obj);
                }
            }

            index++;
        }
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
    catch (Py::Exception& e) {
        // reported by code analyzers
        e.clear();
        Base::Console().warning("Unexpected PyCXX exception\n");
    }
    catch (const boost::exception&) {
        // reported by code analyzers
        Base::Console().warning("Unexpected boost exception\n");
    }

    return result;
}

App::DocumentObject* TaskFeaturePick::makeCopy(
    App::DocumentObject* obj,
    std::string sub,
    bool independent,
    App::DocumentObject* target,
    QString* refusal
)
{

    App::DocumentObject* copy = nullptr;
    auto refuse = [&](const QString& why) -> App::DocumentObject* {
        if (refusal) {
            *refusal = why;
        }
        return nullptr;
    };
    // Check for null to avoid segfault
    if (!obj) {
        return copy;
    }
    if (independent
        && (obj->isDerivedFrom<Sketcher::SketchObject>()
            || obj->isDerivedFrom<PartDesign::FeaturePrimitive>())) {

        // we do know that the created instance is a document object, as obj is one. But we do not
        // know which exact type
        auto* doc = App::GetApplication().getActiveDocument();
        const auto name = fmt::format("Copy{}", obj->getNameInDocument());
        copy = doc->addObject(obj->getTypeId().getName(), name.c_str());

        // copy over all properties
        std::vector<App::Property*> props;
        obj->getPropertyList(props);

        for (App::Property* prop : props) {

            // independent copies don't have links and are not attached. Every link property,
            // also an XLink list or container (a dynamic one would be made and pasted below,
            // PR 224 review L2); the ExpressionEngine is one too: the expressions are made again
            // for the copy, below
            if (prop->isDerivedFrom<App::PropertyLinkBase>()
                || (prop->getGroup() && strcmp(prop->getGroup(), "Attachment") == 0)) {
                continue;
            }

            // FreeCAD-CH (ops#236): paired by name. The two lists were walked side by side, and
            // the original's dynamic properties (listed first) put every pair one place off (a
            // Paste between other types threw a bad cast). A dynamic property is made on the copy.
            const char* propName = prop->getName();
            App::Property* cprop = copy->getPropertyByName(propName);
            if (!cprop) {
                cprop = copy->addDynamicProperty(
                    prop->getTypeId().getName(),
                    propName,
                    prop->getGroup(),
                    prop->getDocumentation(),
                    prop->getType()
                );
                // with the status bits set after it was made: Hidden, ReadOnly, ... (PR 224
                // review L3)
                if (cprop) {
                    cprop->setStatusValue(prop->getStatus());
                }
            }
            if (!cprop || cprop->getTypeId() != prop->getTypeId()) {
                continue;
            }

            if (strcmp(propName, "Label") == 0) {
                static_cast<App::PropertyString*>(cprop)->setValue(name.c_str());
                continue;
            }

            cprop->Paste(*prop);
        }

        // FreeCAD-CH (ops#241, PR 224 review M2): the copy keeps the original's global place.
        // Detached (the Attachment group isn't copied), it is placed by its Placement alone, which
        // is relative to its container: the pasted one placed it in the target container's frame
        // as the original is in its own, so a copy into a body placed otherwise moved, silently.
        if (auto* geoCopy = freecad_cast<App::GeoFeature*>(copy)) {
            const Base::Placement targetPlacement =
                target ? App::GeoFeature::getGlobalPlacement(target) : Base::Placement();
            geoCopy->Placement.setValue(
                targetPlacement.inverse() * App::GeoFeature::getGlobalPlacement(obj)
            );
        }

        // FreeCAD-CH (ops#236): the expressions belong to the copy. Pasted, their paths and
        // expressions kept the original as their owner: they read the original's values, a
        // constraint deletion on the copy didn't renumber them, and the copy's recompute threw
        // "Invalid property owner". Made again from their text, for the copy.
        // An expression that names its own object (Sketch.Constraints.Len, <<Label>>...) prints
        // as .Constraints.Len, so it names the copy (PR 224 review M1, tested). One on Label isn't
        // made again: it would replace the copy's label (L4).
        // An expression on Placement gives the original's place in its own container: where the
        // copy's container is placed otherwise (its Placement converted above), its recompute
        // would move the copy back there, silently (PR 224 round 2). Not made again then, with a
        // warning.
        const Base::Placement& copyPlacement =
            static_cast<App::GeoFeature*>(copy)->Placement.getValue();
        const bool movedPlacement = !copyPlacement.isSame(
            static_cast<App::GeoFeature*>(obj)->Placement.getValue(),
            Precision::Confusion()
        );
        for (const auto& [path, expression] : obj->ExpressionEngine.getExpressions()) {
            if (path.getPropertyName() == "Label") {
                continue;
            }
            if (movedPlacement && path.getPropertyName() == "Placement") {
                Base::Console().warning(
                    "The copy '%s' of '%s' doesn't take the expression of %s: its container is "
                    "placed otherwise\n",
                    copy->Label.getValue(),
                    obj->Label.getValue(),
                    path.toString().c_str()
                );
                continue;
            }
            try {
                copy->setExpression(
                    App::ObjectIdentifier::parse(copy, path.toString()),
                    App::Expression::parse(copy, expression->toString())
                );
            }
            catch (const Base::Exception& e) {
                Base::Console().warning(
                    "The copy '%s' of '%s' doesn't take the expression of %s: %s\n",
                    copy->Label.getValue(),
                    obj->Label.getValue(),
                    path.toString().c_str(),
                    e.what()
                );
            }
        }

        // An independent copy links nothing outside (its links weren't copied). Its projections
        // stay, detached as a parked link's are (SketchObject::parkExternalGeometry): no
        // reference, not Missing. So the constraints on them, its degrees of freedom and its
        // Shape (defining external edges included) stay the original's, and its recompute keeps
        // them fixed: a reference left on a projection would be linked again by
        // rebuildExternalGeometry's re-check of missing elements. The copy only: the original is
        // never touched (ops#233: delConstraintsToExternal() ran on obj, once per property).
        if (auto* sketchCopy = freecad_cast<Sketcher::SketchObject*>(copy)) {
            std::vector<Part::Geometry*> external = sketchCopy->ExternalGeo.getValues();
            if (external.size() > 2) {
                for (auto it = external.begin() + 2; it != external.end(); ++it) {
                    *it = (*it)->clone();
                    auto facade = Sketcher::ExternalGeometryFacade::getFacade(*it);
                    facade->setRef(std::string());
                    facade->setFlag(Sketcher::ExternalGeometryExtension::Missing, false);
                }
                sketchCopy->ExternalGeo.setValues(std::move(external));
            }
            sketchCopy->ExternalTypes.setValues({});
            // Constraints were pasted before ExternalGeo (declaration order), against the axes
            // alone: a constraint on a projection was marked invalid, and an invalid list reads
            // as empty (no constraints solved, none shown, the next addConstraint drops them all)
            sketchCopy->Constraints.checkConstraintIndices(
                sketchCopy->getHighestCurveIndex(),
                -sketchCopy->getExternalGeometryCount()
            );
            sketchCopy->Constraints.acceptGeometry(sketchCopy->getCompleteGeometry());
        }

        // The pasted Shape names its elements after the original (its element map), and the
        // copy's first recompute names them after the copy: a link a caller sets before that maps
        // names the copy then loses ("?Face1"), and the reference comes back resolved by
        // geometry, with a Warning. So the copy gets its own Shape here, before any caller links
        // it (ops#230; the Pipe panel did it for its spines and sections since ops#225). A sketch
        // copy has no attachment and links nothing outside (above); a primitive gets its
        // BaseFeature only when its caller adds it to a body.
        // Only when the recompute keeps the original's shape (PR 223 review M1, M2): a primitive
        // whose original sits on a BaseFeature would become the bare primitive, and a caller's
        // Face1 would then name another face, silently; a subtractive one fails without a base.
        // Those keep the pasted shape, and the old resolution by geometry, with its Warning.
        auto keepsShape = [obj]() {
            auto* primitive = freecad_cast<PartDesign::FeaturePrimitive*>(obj);
            return !primitive
                || (!primitive->BaseFeature.getValue()
                    && primitive->getAddSubType() == PartDesign::FeatureAddSub::Type::Additive);
        };
        // A recomputed copy has its own element names, so a caller's Face1/Edge1 would no longer
        // be flagged when it names another element than the one picked (PR 223 review N1): the
        // callers link the picked element instead (copiedElement).
        if (keepsShape()) {
            if (!copy->recomputeFeature()) {
                Base::Console().warning(
                    "The copy '%s' of '%s' doesn't recompute: %s\n",
                    copy->Label.getValue(),
                    obj->Label.getValue(),
                    copy->getStatusString()
                );
            }
        }
    }
    else {

        const std::string name = (!independent ? std::string("Reference") : std::string("Copy"))
            + obj->getNameInDocument();
        const std::string entity = sub;

        Part::PropertyPartShape* shapeProp = nullptr;

        // TODO Replace it with commands (2015-09-11, Fat-Zer)
        if (obj->isDerivedFrom<Part::Datum>()) {
            const QString label = QString::fromUtf8(obj->Label.getValue());
            // we need to reference the individual datums and make again datums. This is important
            // as datum adjust their size dependent on the part size, hence simply copying the shape
            // is not enough
            long int mode = mmDeactivated;
            if (obj->is<PartDesign::Point>()) {
                mode = mm0Vertex;
            }
            else if (obj->is<PartDesign::Line>()) {
                mode = mm1TwoPoints;
            }
            else if (obj->is<PartDesign::Plane>()) {
                mode = mmFlatFace;
            }
            else {
                // a legacy coordinate system: its copy came unattached at the origin, without the
                // picked axis or plane (PR 227 review L1)
                return refuse(QObject::tr("'%1' can't be copied. Make a cross-reference instead.")
                                  .arg(label));
            }
            // A dependent copy is attached to the original, and the attacher reads the original's
            // placement in its own body: in a body placed otherwise, the copy would sit elsewhere,
            // silently (PR 227 review M1)
            if (!independent) {
                const Base::Placement container = App::GeoFeature::getGlobalPlacement(obj)
                    * static_cast<App::GeoFeature*>(obj)->Placement.getValue().inverse();
                const Base::Placement targetPlacement =
                    target ? App::GeoFeature::getGlobalPlacement(target) : Base::Placement();
                if (!container.isSame(targetPlacement, Precision::Confusion())) {
                    return refuse(
                        QObject::tr(
                            "A dependent copy of '%1' would not be where '%1' is: its body is "
                            "placed differently from this one. Make an independent copy instead."
                        )
                            .arg(label)
                    );
                }
            }

            auto* doc = App::GetApplication().getActiveDocument();
            // FreeCAD-CH (ops#244 P6): a datum of the original's type. Part::Datum is abstract:
            // addObject<Part::Datum> made nothing, and the null was dereferenced below.
            copy = doc->addObject(obj->getTypeId().getName(), name.c_str());
            if (!copy) {
                return refuse(QObject::tr("'%1' can't be copied.").arg(label));
            }
            Part::Datum* datumCopy = static_cast<Part::Datum*>(copy);

            // TODO Recheck this. This looks strange in case of independent copy (2015-10-31,
            // Fat-Zer)
            if (!independent) {
                datumCopy->AttachmentSupport.setValue(obj, entity.c_str());
                datumCopy->MapMode.setValue(mode);
            }
            else {
                // A datum's shape is made from its Placement (setting the Shape set the Placement
                // the original has in its own container): where the original is, as for the
                // copies above (decision 40), with the original's size
                for (const char* sizeName : {"ResizeMode", "Length", "Width"}) {
                    App::Property* size = obj->getPropertyByName(sizeName);
                    App::Property* copySize = copy->getPropertyByName(sizeName);
                    if (size && copySize && size->getTypeId() == copySize->getTypeId()) {
                        copySize->Paste(*size);
                    }
                }
                const Base::Placement targetPlacement =
                    target ? App::GeoFeature::getGlobalPlacement(target) : Base::Placement();
                datumCopy->Placement.setValue(
                    targetPlacement.inverse() * App::GeoFeature::getGlobalPlacement(obj)
                );
            }
        }
        else if (obj->is<PartDesign::ShapeBinder>() || obj->isDerivedFrom<Part::Feature>()) {

            auto* doc = App::GetApplication().getActiveDocument();
            auto* shapeBinderObj = doc->addObject<PartDesign::ShapeBinder>(name.c_str());
            if (!independent) {
                shapeBinderObj->Support.setValue(obj, entity.c_str());
            }
            else {
                shapeProp = &shapeBinderObj->Shape;
            }
            copy = shapeBinderObj;
        }
        else if (obj->isDerivedFrom<App::Plane>() || obj->isDerivedFrom<App::Line>()) {

            auto* doc = App::GetApplication().getActiveDocument();
            auto* shapeBinderObj = doc->addObject<PartDesign::ShapeBinder>(name.c_str());
            if (!independent) {
                shapeBinderObj->Support.setValue(obj, entity.c_str());
            }
            else {
                std::vector<std::string> subvalues;
                subvalues.push_back(entity);
                // FreeCAD-CH (ops#244 P6): from the original (the new binder is empty), where the
                // original is (decision 40): its shape is placed in the original's body
                auto* geoObj = static_cast<App::GeoFeature*>(obj);
                Part::TopoShape shape =
                    PartDesign::ShapeBinder::buildShapeFromReferences(geoObj, subvalues);
                shapeBinderObj->Shape.setValue(shape);
                const Base::Placement targetPlacement =
                    target ? App::GeoFeature::getGlobalPlacement(target) : Base::Placement();
                shapeBinderObj->Placement.setValue(
                    targetPlacement.inverse() * geoObj->globalPlacement()
                );
            }
            copy = shapeBinderObj;
        }

        if (independent && shapeProp) {
            auto* featureObj = static_cast<Part::Feature*>(obj);
            shapeProp->setValue(
                entity.empty() ? featureObj->Shape.getValue()
                               : featureObj->Shape.getShape().getSubShape(entity.c_str())
            );
            // FreeCAD-CH (PR 224 round 2, decision 40): where the original is, as for the copies
            // above. The binder took the shape's placement, relative to the original's container:
            // a copy into a container placed otherwise moved, silently. (A dependent binder still
            // does, ops#244.)
            auto* binder = static_cast<PartDesign::ShapeBinder*>(copy);
            const Base::Placement container = App::GeoFeature::getGlobalPlacement(obj)
                * featureObj->Placement.getValue().inverse();
            const Base::Placement targetPlacement =
                target ? App::GeoFeature::getGlobalPlacement(target) : Base::Placement();
            binder->Placement.setValue(
                targetPlacement.inverse() * container * binder->Placement.getValue()
            );
        }
    }

    return copy;
}

namespace
{

// The shape of an element, or null when it can't be read; placed by the object's Placement when
// `placed`
TopoDS_Shape elementShape(App::DocumentObject* obj, const std::string& sub, bool placed)
{
    const Part::ShapeOptions options = placed
        ? Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink
            | Part::ShapeOption::Transform
        : Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink;
    try {
        return Part::Feature::getTopoShape(obj, options, sub.c_str()).getShape();
    }
    catch (const Base::Exception&) {
    }
    catch (const Standard_Failure&) {
    }
    return {};
}

}  // namespace

// The properties that tell one element from another: its type, its length, area or point, and
// its centre of mass, in the frames described below. The Pipe panel's copy step uses it too
// (ops#234, ops#243).
bool TaskFeaturePick::sameElement(
    App::DocumentObject* original,
    App::DocumentObject* copy,
    const std::string& sub
)
{
    if (sub.empty() || original == copy) {
        return true;
    }
    // An independent copy keeps the original's global place, so its own Placement differs from
    // the original's when their containers are placed differently (PR 224 review M2, round 2):
    // both are compared without it, in their own frame. A dependent copy (a shape binder with a
    // support) in the frame of its container, which a copy in the body shares with an original
    // beside the body.
    auto* binder = freecad_cast<PartDesign::ShapeBinder*>(copy);
    const bool placed = binder && !binder->Support.getValues().empty();
    TopoDS_Shape before = elementShape(original, sub, placed);
    TopoDS_Shape after = elementShape(copy, sub, placed);
    // The reference is already broken on the original: on a copy that has the element it would
    // name another one, silently; and where neither has it (?Edge3 after a recompute of the
    // original lost it), the copy would carry the broken reference on (ops#243 L4)
    if (before.IsNull() || after.IsNull() || after.ShapeType() != before.ShapeType()) {
        return false;
    }
    auto measure = [](const TopoDS_Shape& shape, double& size, gp_Pnt& center) {
        GProp_GProps props;
        switch (shape.ShapeType()) {
            case TopAbs_VERTEX:
                size = 0;
                center = BRep_Tool::Pnt(TopoDS::Vertex(shape));
                return;
            case TopAbs_EDGE:
            case TopAbs_WIRE:
                BRepGProp::LinearProperties(shape, props);
                break;
            default:
                BRepGProp::SurfaceProperties(shape, props);
                break;
        }
        size = props.Mass();
        center = props.CentreOfMass();
    };
    double sizeBefore = 0;
    double sizeAfter = 0;
    gp_Pnt centerBefore;
    gp_Pnt centerAfter;
    try {
        measure(before, sizeBefore, centerBefore);
        measure(after, sizeAfter, centerAfter);
    }
    catch (const Standard_Failure&) {
        return false;  // not shown to be the same
    }
    const double tolerance = Precision::Confusion() * std::max(1.0, std::abs(sizeBefore));
    return std::abs(sizeAfter - sizeBefore) <= tolerance
        && centerAfter.Distance(centerBefore) <= Precision::Confusion() * 10;
}

std::optional<std::string> TaskFeaturePick::copiedElement(
    App::DocumentObject* original,
    App::DocumentObject* copy,
    const std::string& sub
)
{
    const std::string index = Data::oldElementName(sub.c_str());
    if (!copy || sub.empty() || original == copy || PartDesign::Feature::isDatum(copy)) {
        return std::string();
    }
    // a sub that names no element (PR 227 review L3)
    if (index.empty()) {
        return std::nullopt;
    }
    // An independent sketch or primitive copy has the original's elements under the same index
    // names, whether makeCopy recomputed it or it keeps the pasted shape
    if (copy->getTypeId() == original->getTypeId()
        && (copy->isDerivedFrom<Sketcher::SketchObject>()
            || copy->isDerivedFrom<PartDesign::FeaturePrimitive>())) {
        if (!sameElement(original, copy, index)) {
            return std::nullopt;
        }
        return index;
    }
    // a shape binder of that element alone
    std::string kind = index;
    kind.erase(std::remove_if(kind.begin(), kind.end(), &isdigit), kind.end());
    return kind + "1";
}

bool TaskFeaturePick::isSingleSelectionEnabled() const
{
    ParameterGrp::handle hGrp = App::GetApplication()
                                    .GetUserParameter()
                                    .GetGroup("BaseApp")
                                    ->GetGroup("Preferences")
                                    ->GetGroup("Selection");
    return hGrp->GetBool("singleClickFeatureSelect", true);
}

void TaskFeaturePick::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (doSelection) {
        return;
    }
    doSelection = true;
    ui->listWidget->clearSelection();
    for (Gui::SelectionSingleton::SelObj obj : Gui::Selection().getSelection()) {
        for (int row = 0; row < ui->listWidget->count(); row++) {
            QListWidgetItem* item = ui->listWidget->item(row);
            QString t = item->data(Qt::UserRole).toString();
            if (t.compare(QString::fromLatin1(obj.FeatName)) == 0) {
                item->setSelected(true);

                if (msg.Type == Gui::SelectionChanges::AddSelection) {
                    std::string docNameCopy = documentName;
                    if (isSingleSelectionEnabled()) {
                        QMetaObject::invokeMethod(
                            qobject_cast<Gui::ControlSingleton*>(&Gui::Control()),
                            [docNameCopy] {
                                Gui::Control().accept(
                                    Gui::Application::Instance->getDocument(docNameCopy.c_str())
                                        ->getDocument()
                                );
                            },
                            Qt::QueuedConnection
                        );
                    }
                }
            }
        }
    }
    doSelection = false;
}

void TaskFeaturePick::onItemSelectionChanged()
{
    if (doSelection) {
        return;
    }
    doSelection = true;
    ui->listWidget->blockSignals(true);
    Gui::Selection().clearSelection();
    for (int row = 0; row < ui->listWidget->count(); row++) {
        QListWidgetItem* item = ui->listWidget->item(row);
        QString t = item->data(Qt::UserRole).toString();
        if (item->isSelected()) {
            Gui::Selection().addSelection(documentName.c_str(), t.toLatin1());
        }
    }
    ui->listWidget->blockSignals(false);
    doSelection = false;
}

void TaskFeaturePick::onDoubleClick(QListWidgetItem* item)
{
    if (doSelection) {
        return;
    }
    doSelection = true;
    QString t = item->data(Qt::UserRole).toString();
    Gui::Selection().addSelection(documentName.c_str(), t.toLatin1());
    doSelection = false;

    std::string docNameCopy = documentName;
    QMetaObject::invokeMethod(
        qobject_cast<Gui::ControlSingleton*>(&Gui::Control()),
        [docNameCopy] {
            Gui::Control().accept(
                Gui::Application::Instance->getDocument(docNameCopy.c_str())->getDocument()
            );
        },
        Qt::QueuedConnection
    );
}

void TaskFeaturePick::slotDeletedObject(const Gui::ViewProviderDocumentObject& Obj)
{
    if (const auto it = std::ranges::find(origins, &Obj); it != origins.end()) {
        origins.erase(it);
    }
}

void TaskFeaturePick::slotUndoDocument(const Gui::Document& doc)
{
    if (origins.empty()) {
        QTimer::singleShot(100, [&doc]() { Gui::Control().closeDialog(doc.getDocument()); });
    }
}

void TaskFeaturePick::slotDeleteDocument(const Gui::Document& doc)
{
    origins.clear();
    App::Document* docPtr = doc.getDocument();
    QTimer::singleShot(100, [docPtr]() { Gui::Control().closeDialog(docPtr); });
}

void TaskFeaturePick::showExternal(bool val)
{
    ui->checkOtherBody->setChecked(val);
    ui->checkOtherPart->setChecked(val);
    updateList();
}


//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgFeaturePick::TaskDlgFeaturePick(
    std::vector<App::DocumentObject*>& objects,
    const std::vector<TaskFeaturePick::featureStatus>& status,
    std::function<bool(std::vector<App::DocumentObject*>)> afunc,
    std::function<void(std::vector<App::DocumentObject*>)> wfunc,
    bool singleFeatureSelect,
    std::function<void(void)> abortfunc /* = NULL */
)
    : TaskDialog()
    , accepted(false)
{
    pick = new TaskFeaturePick(objects, status, singleFeatureSelect);
    Content.push_back(pick);

    acceptFunction = afunc;
    workFunction = wfunc;
    abortFunction = abortfunc;
}

TaskDlgFeaturePick::~TaskDlgFeaturePick()
{
    // do the work now as before in accept() the dialog is still open, hence the work
    // function could not open another dialog
    if (accepted) {
        try {
            workFunction(pick->buildFeatures());
        }
        catch (...) {
        }
    }
    else if (abortFunction) {

        // Get rid of the TaskFeaturePick before the TaskDialog dtor does. The
        // TaskFeaturePick holds pointers to things (ie any implicitly created
        // Body objects) that might be modified/removed by abortFunction.
        for (auto it : Content) {
            delete it;
        }
        Content.clear();

        try {
            abortFunction();
        }
        catch (...) {
        }
    }
}

//==== calls from the TaskView ===============================================================


void TaskDlgFeaturePick::open()
{}

void TaskDlgFeaturePick::clicked(int)
{}

bool TaskDlgFeaturePick::accept()
{
    accepted = acceptFunction(pick->getFeatures());
    return accepted;
}

bool TaskDlgFeaturePick::reject()
{
    accepted = false;
    return true;
}

void TaskDlgFeaturePick::showExternal(bool val)
{
    pick->showExternal(val);
}


#include "moc_TaskFeaturePick.cpp"
