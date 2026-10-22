// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2012 Konstantinos Poulios <logari81@gmail.com>             *
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


#include <algorithm>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <QDialog>
#include <QMessageBox>


#include <App/Document.h>
#include <App/ElementNamingUtils.h>
#include <App/Origin.h>
#include <App/Datums.h>
#include <App/Part.h>
#include <App/PropertyLinks.h>
#include <Base/Tools.h>
#include <Gui/Command.h>
#include <Gui/Document.h>
#include <Gui/MainWindow.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/PartDesign/App/Feature.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/DatumLine.h>
#include <Mod/PartDesign/App/DatumPlane.h>
#include <Mod/PartDesign/App/DatumPoint.h>
#include <Mod/PartDesign/App/ShapeBinder.h>

#include "ui_DlgReference.h"
#include "ReferenceSelection.h"
#include "TaskFeaturePick.h"
#include "Utils.h"


using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::ReferenceSelection.cpp */

bool ReferenceSelection::allow(App::Document* pDoc, App::DocumentObject* pObj, const char* sSubName)
{
    if (!pObj) {
        return false;
    }
    PartDesign::Body* body = getBody();
    App::OriginGroupExtension* originGroup = getOriginGroupExtension(body);

    // Don't allow selection in other document
    if (support && pDoc != support->getDocument()) {
        return false;
    }

    // Enable selection from origin of current part/
    if (pObj->isDerivedFrom<App::DatumElement>()) {
        return allowOrigin(body, originGroup, pObj);
    }

    if (pObj->isDerivedFrom<Part::Datum>()) {
        return allowDatum(body, pObj);
    }

    // The flag was used to be set. So, this block will never be treated and really doesn't make
    // sense anyway
#if 0
    if (!type.testFlag(AllowSelection::OTHERBODY)) {
        if (support == NULL)
            return false;
        if (pObj != support)
            return false;
    }
#endif
    if (pObj->isDerivedFrom<Part::Part2DObject>() && Base::Tools::isNullOrEmpty(sSubName)) {
        return type.testFlag(AllowSelection::FACE);
    }

    // Handle selection of geometry elements
    if (Base::Tools::isNullOrEmpty(sSubName)) {
        return type.testFlag(AllowSelection::WHOLE);
    }

    // resolve links if needed
    if (!pObj->isDerivedFrom<Part::Feature>()) {
        pObj = Part::Feature::getShapeOwner(pObj, sSubName);
    }

    if (pObj && pObj->isDerivedFrom<Part::Feature>()) {
        return allowPartFeature(pObj, sSubName);
    }

    return false;
}

PartDesign::Body* ReferenceSelection::getBody() const
{
    auto* body = support ? PartDesign::Body::findBodyOf(support) : PartDesignGui::getBody(false);
    return body;
}

App::OriginGroupExtension* ReferenceSelection::getOriginGroupExtension(PartDesign::Body* body) const
{
    App::DocumentObject* originGroupObject = nullptr;

    if (body) {  // Search for Part of the body
        originGroupObject = App::OriginGroupExtension::getGroupOfObject(body);
    }
    else if (support) {  // if no body search part for support
        originGroupObject = App::OriginGroupExtension::getGroupOfObject(support);
    }
    else {  // fallback to active part
        originGroupObject = PartDesignGui::getActivePart();
    }

    App::OriginGroupExtension* originGroup = nullptr;
    if (originGroupObject) {
        originGroup = originGroupObject->getExtensionByType<App::OriginGroupExtension>();
    }

    return originGroup;
}

bool ReferenceSelection::allowOrigin(
    PartDesign::Body* body,
    App::OriginGroupExtension* originGroup,
    App::DocumentObject* pObj
) const
{
    bool fits = false;
    if (type.testFlag(AllowSelection::FACE) && pObj->isDerivedFrom<App::Plane>()) {
        fits = true;
    }
    else if (type.testFlag(AllowSelection::EDGE) && pObj->isDerivedFrom<App::Line>()) {
        fits = true;
    }

    if (fits) {  // check that it actually belongs to the chosen body or part
        try {    // here are some throwers
            if (body) {
                // FreeCAD-CH (ops#325): another Body's origin in the same studio is the same
                // plane or axis; the pick is relinked to this Body's own
                if (body->hasObject(pObj, true)
                    || Part::BodyBase::studioOriginFeature(body, pObj)) {
                    return true;
                }
            }
            else if (originGroup) {
                if (originGroup->hasObject(pObj, true)) {
                    return true;
                }
            }
        }
        catch (const Base::Exception&) {
        }
    }
    return false;  // The Plane/Axis doesn't fits our needs
}

bool ReferenceSelection::allowDatum(PartDesign::Body* body, App::DocumentObject* pObj) const
{
    if (!body) {  // Allow selecting Part::Datum features from the active Body
        return false;
    }
    else if (!type.testFlag(AllowSelection::OTHERBODY) && !body->hasObject(pObj)
             && !Part::BodyBase::isInOneStudio(body, pObj)) {  // FreeCAD-CH (ops#325)
        return false;
    }

    if (type.testFlag(AllowSelection::FACE) && (pObj->isDerivedFrom<PartDesign::Plane>())) {
        return true;
    }
    if (type.testFlag(AllowSelection::EDGE) && (pObj->isDerivedFrom<PartDesign::Line>())) {
        return true;
    }
    if (type.testFlag(AllowSelection::POINT) && (pObj->isDerivedFrom<PartDesign::Point>())) {
        return true;
    }

    return false;
}

bool ReferenceSelection::allowPartFeature(App::DocumentObject* pObj, const char* sSubName) const
{
    std::string subName(sSubName);
    if (type.testFlag(AllowSelection::POINT) && subName.compare(0, 6, "Vertex") == 0) {
        return true;
    }

    if (type.testFlag(AllowSelection::EDGE) && subName.compare(0, 4, "Edge") == 0) {
        if (isEdge(pObj, sSubName)) {
            return true;
        }
    }

    if (type.testFlag(AllowSelection::CIRCLE) && subName.compare(0, 4, "Edge") == 0) {
        if (isCircle(pObj, sSubName)) {
            return true;
        }
    }

    if (type.testFlag(AllowSelection::FACE)) {
        if (isFace(pObj, sSubName)) {
            return true;
        }
    }

    return false;
}

bool ReferenceSelection::isEdge(App::DocumentObject* pObj, const char* sSubName) const
{
    const Part::TopoShape& shape = static_cast<const Part::Feature*>(pObj)->Shape.getValue();
    TopoDS_Shape sh = shape.getSubShape(sSubName);
    const TopoDS_Edge& edgeShape = TopoDS::Edge(sh);
    if (!edgeShape.IsNull()) {
        if (type.testFlag(AllowSelection::PLANAR)) {
            BRepAdaptor_Curve adapt(edgeShape);
            if (adapt.GetType() == GeomAbs_Line) {
                return true;
            }
        }
        else {
            return true;
        }
    }

    return false;
}

bool ReferenceSelection::isFace(App::DocumentObject* pObj, const char* sSubName) const
{
    const Part::TopoShape shape = Part::Feature::getTopoShape(
        pObj,
        Part::ShapeOption::NeedSubElement | Part::ShapeOption::ResolveLink,
        sSubName
    );
    if (shape.shapeType(true) == TopAbs_FACE) {
        const TopoDS_Face& face = TopoDS::Face(shape.getShape());
        if (type.testFlag(AllowSelection::PLANAR)) {
            BRepAdaptor_Surface adapt(face);
            if (adapt.GetType() == GeomAbs_Plane) {
                return true;
            }
        }
        else {
            return true;
        }
    }

    return false;
}

bool ReferenceSelection::isCircle(App::DocumentObject* pObj, const char* sSubName) const
{
    const Part::TopoShape& shape = static_cast<const Part::Feature*>(pObj)->Shape.getValue();
    TopoDS_Shape sh = shape.getSubShape(sSubName);
    const TopoDS_Edge& edgeShape = TopoDS::Edge(sh);
    BRepAdaptor_Curve adapt(edgeShape);
    if (adapt.GetType() == GeomAbs_Circle) {
        return true;
    }

    return false;
}

// ----------------------------------------------------------------------------

bool NoDependentsSelection::allow(App::Document* /*pDoc*/, App::DocumentObject* pObj, const char* /*sSubName*/)
{
    if (support && support->testIfLinkDAGCompatible(pObj)) {
        return true;
    }
    else {
        this->notAllowedReason = QT_TR_NOOP("Selecting this will cause circular dependency.");
        return false;
    }
}

bool CombineSelectionFilterGates::allow(App::Document* pDoc, App::DocumentObject* pObj, const char* sSubName)
{
    return filter1->allow(pDoc, pObj, sSubName) && filter2->allow(pDoc, pObj, sSubName);
}


namespace PartDesignGui
{

bool getReferencedSelection(
    const App::DocumentObject* thisObj,
    const Gui::SelectionChanges& msg,
    App::DocumentObject*& selObj,
    std::vector<std::string>& selSub,
    bool* answered
)
{
    selObj = nullptr;
    if (answered) {
        *answered = false;
    }
    if (!thisObj) {
        return false;
    }

    if (strcmp(thisObj->getDocument()->getName(), msg.pDocName) != 0) {
        return false;
    }

    selObj = thisObj->getDocument()->getObject(msg.pObjectName);
    if (selObj == thisObj) {
        return false;
    }

    std::string subname = msg.pSubName;

    // check if the selection is an external reference and ask the user what to do
    // of course only if thisObj is in a body, as otherwise the old workflow would not
    // be supported
    PartDesign::Body* body = PartDesignGui::getBodyFor(thisObj, false);
    bool originfeature = selObj->isDerivedFrom<App::DatumElement>();
    if (originfeature) {
        // FreeCAD-CH (ops#325): another Body's origin in the same studio: this Body's own
        if (auto own = Part::BodyBase::studioOriginFeature(thisObj, selObj)) {
            selObj = own;
        }
    }
    if (!originfeature && body) {
        PartDesign::Body* selBody = PartDesignGui::getBodyFor(selObj, false);
        // FreeCAD-CH (ops#325): another Body of the same studio is referenced directly
        if ((!selBody || body != selBody)
            && !Part::BodyBase::isStudioPick(thisObj, selObj, subname.c_str())) {
            QDialog dia(Gui::getMainWindow());
            Ui_DlgReference dlg;
            dlg.setupUi(&dia);
            dia.setModal(true);
            int result = dia.exec();
            if (result == QDialog::DialogCode::Rejected) {
                selObj = nullptr;
                if (answered) {
                    *answered = true;
                }
                return false;
            }

            if (!dlg.radioXRef->isChecked()) {
                App::Document* document = thisObj->getDocument();
                document->openTransaction("Make copy");
                QString refusal;
                auto copy = PartDesignGui::TaskFeaturePick::makeCopy(
                    selObj,
                    subname,
                    dlg.radioIndependent->isChecked(),
                    body,
                    &refusal
                );
                // nothing to link (PR 227 review L2: the null went into the body)
                if (!copy) {
                    QMessageBox::warning(
                        Gui::getMainWindow(),
                        QObject::tr("No copy"),
                        refusal.isEmpty()
                            ? QObject::tr("'%1' can't be copied. Make a cross-reference instead.")
                                  .arg(QString::fromUtf8(selObj->Label.getValue()))
                            : refusal
                    );
                    selObj = nullptr;
                    if (answered) {
                        *answered = true;
                    }
                    return false;
                }

                // The picked element on the copy (ops#244 P1: the first one of its kind,
                // whatever was picked, on a copy that keeps the original's elements, such as a
                // primitive on a base): the same index, once it's shown to be the same one (PR
                // 223 review N1), or the first one of a shape binder of that element
                const std::optional<std::string> element =
                    PartDesignGui::TaskFeaturePick::copiedElement(selObj, copy, subname);
                if (!element) {
                    // removed before the message box, whose event loop would otherwise run
                    // with it (PR 224 review L5)
                    copy->getDocument()->removeObject(copy->getNameInDocument());
                    QMessageBox::warning(
                        Gui::getMainWindow(),
                        QObject::tr("Copy differs"),
                        PartDesignGui::TaskFeaturePick::copyDiffers(selObj, subname)
                    );
                    selObj = nullptr;
                    if (answered) {
                        *answered = true;
                    }
                    return false;
                }
                subname = *element;
                body->addObject(copy);
                // FreeCAD-CH (ops#244): a dependent copy (a traced shape binder) has no shape
                // until it computes. The feature in edit read it as linked ("null shape") and OK
                // failed, the panel staying open. Computed in the body, where it is placed; one
                // that fails isn't linked
                if (auto* binder = freecad_cast<PartDesign::ShapeBinder*>(copy);
                    binder && binder->TraceSupport.getValue() && !binder->recomputeFeature()) {
                    // FreeCAD-CH (ops#395 6): a failure with no status text read "...: ."
                    QString why = QString::fromUtf8(binder->getStatusString());
                    if (why.isEmpty()) {
                        why = QObject::tr("it has no shape");
                    }
                    copy->getDocument()->removeObject(copy->getNameInDocument());
                    QMessageBox::warning(
                        Gui::getMainWindow(),
                        QObject::tr("No copy"),
                        QObject::tr("The copy of '%1' doesn't compute: %2. Make a cross-reference "
                                    "instead.")
                            .arg(QString::fromUtf8(selObj->Label.getValue()), why)
                    );
                    selObj = nullptr;
                    if (answered) {
                        *answered = true;
                    }
                    return false;
                }

                selObj = copy;
            }
        }
    }

    // Remove subname for planes and datum features
    if (PartDesign::Feature::isDatum(selObj)) {
        subname = "";
    }

    selSub = std::vector<std::string>(1, subname);

    return true;
}

QString getRefStr(const App::DocumentObject* obj, const std::vector<std::string>& sub)
{
    if (!obj) {
        return {};
    }

    if (PartDesign::Feature::isDatum(obj)) {
        return QString::fromLatin1(obj->getNameInDocument());
    }

    if (!sub.empty() && !sub.front().empty()) {
        return QString::fromLatin1(obj->getNameInDocument()) + QStringLiteral(":")
            + QString::fromLatin1(sub.front().c_str());
    }

    if (obj->isDerivedFrom<Part::Part2DObject>()) {
        // only return bare name for sketches when no subelement is specified
        return QString::fromLatin1(obj->getNameInDocument());
    }

    return {};
}

std::string buildLinkSubPythonStr(const App::DocumentObject* obj, const std::vector<std::string>& subs)
{
    if (!obj) {
        return "None";
    }

    // (obj, ["sub", ...]): upstream left the object out, so the PropertyLinkSub it was written to
    // refused the list ("Expect input sequence of size 2"; ops#276)
    std::string result("[");

    for (const auto& sub : subs) {
        result += "\"" + Base::Tools::escapeEncodeString(sub) + "\",";
    }
    result += "]";

    const std::string postfix = ", " + result + ")";
    return Gui::Command::getObjectCmd(obj, "(", postfix.c_str());
}

std::string buildLinkSingleSubPythonStr(
    const App::DocumentObject* obj,
    const std::vector<std::string>& subs
)
{
    if (!obj) {
        return "None";
    }

    if (PartDesign::Feature::isDatum(obj)) {
        return Gui::Command::getObjectCmd(obj, "(", ", [''])");
    }
    else {
        return Gui::Command::getObjectCmd(obj, "(", ", ['")
            + Base::Tools::escapeEncodeString(subs.front()) + "'])";
    }
}

bool isSameLink(
    const App::PropertyLinkSub& prop,
    const App::DocumentObject* obj,
    const std::vector<std::string>& subs
)
{
    if (prop.getValue() != obj) {
        return false;
    }
    // A datum is linked with no sub or with one empty sub.
    auto noElement = [](const std::vector<std::string>& names) {
        return std::all_of(names.begin(), names.end(), [](const std::string& name) {
            return name.empty();
        });
    };
    if (noElement(subs)) {
        return noElement(prop.getSubValues(false));
    }
    return prop.getSubValues(false) == subs || prop.getSubValues(true) == subs;
}

std::string buildLinkListPythonStr(const std::vector<App::DocumentObject*>& objs)
{
    if (objs.empty()) {
        return "None";
    }

    std::string result("[");

    for (auto obj : objs) {
        result += Gui::Command::getObjectCmd(obj, nullptr, ",");
    }
    result += "]";

    return result;
}

std::string buildLinkSubListPythonStr(
    const std::vector<App::DocumentObject*>& objs,
    const std::vector<std::string>& subs
)
{
    if (objs.empty()) {
        return "None";
    }

    std::string result("[");

    assert(objs.size() == subs.size());

    for (size_t i = 0, objs_sz = objs.size(); i < objs_sz; i++) {
        if (objs[i]) {
            result += '(';
            result += Gui::Command::getObjectCmd(objs[i]);
            result += ",\"";
            result += Base::Tools::escapeEncodeString(subs[i]);
            result += "\"),";
        }
    }

    result += "]";

    return result;
}
}  // namespace PartDesignGui
