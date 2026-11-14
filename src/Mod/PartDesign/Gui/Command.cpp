// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Jürgen Riegel <juergen.riegel@web.de>              *
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


#include <functional>

#include <BRep_Tool.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <GeomLib_IsPlanarSurface.hxx>
#include <QMessageBox>
#include <QMetaObject>
#include <QPushButton>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>


#include <App/Document.h>
#include <App/DocumentObserver.h>
#include <App/ElementNamingUtils.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <App/Origin.h>
#include <App/Part.h>
#include <Base/Tools.h>
#include <Gui/Application.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>
#include <Gui/Control.h>
#include <Gui/Document.h>
#include <Gui/ForkKeymap.h>
#include <Gui/MainWindow.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Selection/SelectionObject.h>
#include <Gui/TaskView/TaskDialog.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Mod/Part/App/Attacher.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Sketcher/App/SketchObject.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/Derived.h>
#include <Mod/PartDesign/App/FeatureBoolean.h>
#include <Mod/PartDesign/App/FeatureGroove.h>
#include <Mod/PartDesign/App/FeatureMultiTransform.h>
#include <Mod/PartDesign/App/FeatureRevolution.h>
#include <Mod/PartDesign/App/FeatureTransformed.h>
#include <Mod/PartDesign/App/DatumLine.h>
#include <Mod/PartDesign/App/DatumPlane.h>
#include <Mod/PartDesign/App/DatumPoint.h>
#include <Mod/PartDesign/App/FeatureDressUp.h>
#include <Mod/PartDesign/App/FeatureDefeaturing.h>
#include <Mod/PartDesign/App/ShapeBinder.h>
#include <Mod/PartDesign/App/PartDesignParameter.h>
#include <Mod/PartDesign/App/Studio.h>
#include <Mod/PartDesign/App/StudioList.h>

#include "DlgActiveBody.h"
#include "ReferenceField.h"
#include "ReferenceSelection.h"
#include "SketchWorkflow.h"
#include "TaskDerived.h"
#include "TaskDressUpParameters.h"
#include "TaskFeatureParameters.h"
#include "TaskFeaturePick.h"
#include "TaskShapeBinder.h"
#include "Utils.h"
#include "WorkflowManager.h"
#include "ViewProvider.h"
#include "ViewProviderBody.h"
#include <Mod/Part/Gui/EdgeMidpointMarker.h>
#include <Mod/Part/Gui/TaskAttacher.h>


// TODO Remove this header after fixing code so it won;t be needed here (2015-10-20, Fat-Zer)
#include "ui_DlgReference.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

using namespace std;
using namespace Attacher;

static void copyPlacementExpressions(App::DocumentObject* target, const App::DocumentObject* source)
{
    if (!target || !source) {
        return;
    }

    for (const auto& it : source->ExpressionEngine.getExpressions()) {
        if (!it.second || it.first.getPropertyName() != "Placement") {
            continue;
        }

        try {
            auto path = App::ObjectIdentifier::parse(target, it.first.toString().c_str());
            target->setExpression(path, App::Expression::parse(target, it.second->toString()));
        }
        catch (const Base::Exception& e) {
            FC_WARN("Failed to copy placement expression: " << e.what());
        }
    }
}

/** The Body a command adds its feature to (FreeCAD-CH ops#640, rank 14): Onshape's features
 * take any part's entities with no part to activate first. With no Body active, the Body of the
 * first selected object that is in one, with no question; with  pickOwns (a Hole drills the
 * part its sketch is on), also when the selection is in another Body of the active one's studio.
 * Otherwise the active Body, asked for as before.
 */
static PartDesign::Body* commandBody(Gui::Command* cmd, bool pickOwns = false)
{
    PartDesign::Body* active = PartDesignGui::getBody(/*messageIfNot = */ false);
    if (!active || pickOwns) {
        for (auto& sel : cmd->getSelection().getSelectionEx()) {
            App::DocumentObject* obj = sel.getObject();
            // a Body picked whole (in the tree) is its own part
            PartDesign::Body* owner = freecad_cast<PartDesign::Body*>(obj);
            if (!owner && obj) {
                owner = PartDesign::Body::findBodyOf(obj);
            }
            if (!owner || owner == active) {
                break;
            }
            if (!active || PartDesignGui::isStudioSelection(active, obj)) {
                return owner;
            }
            break;
        }
    }
    return PartDesignGui::getBody(/*messageIfNot = */ true);
}

//===========================================================================
// PartDesign_Datum
//===========================================================================

/**
 * @brief UnifiedDatumCommand is a common routine called by datum plane, line and point commands
 * @param cmd (i/o) command, to have shortcuts to doCommand, etc.
 * @param type (input)
 * @param name (input). Is used to generate new name for an object, and to fill undo messages.
 *
 */
void UnifiedDatumCommand(Gui::Command& cmd, Base::Type type, std::string name)
{
    try {
        std::string fullTypeName(type.getName());

        App::PropertyLinkSubList support;
        cmd.getSelection().getAsPropertyLinkSubList(support);
        // FreeCAD-CH (ops#673): one edge picked in 3D at its middle; the dialog makes it the
        // edge's middle (the selection is cleared before the dialog opens)
        bool midpointPick = false;
        {
            const auto sel = Gui::Selection().getSelectionEx(
                nullptr,
                App::DocumentObject::getClassTypeId(),
                Gui::ResolveMode::NoResolve
            );
            if (sel.size() == 1 && sel[0].getSubNames().size() == 1 && sel[0].hasPickedPoint(0)) {
                midpointPick = PartGui::EdgeMidpointMarker::pickedMiddle(
                                   sel[0].getDocName(),
                                   sel[0].getFeatName(),
                                   sel[0].getSubNames()[0].c_str(),
                                   sel[0].getPickedPoints()[0]
                )
                                   .has_value();
            }
        }

        bool bEditSelected = false;
        if (support.getSize() == 1 && support.getValue()) {
            if (support.getValue()->isDerivedFrom(type)) {
                bEditSelected = true;
            }
        }

        // FreeCAD-CH (ops#640, rank 14): with no Body active, the picked part's
        PartDesign::Body* pcActiveBody = commandBody(&cmd);

        if (bEditSelected) {
            pcActiveBody->getDocument()->openTransaction(
                std::string(std::string("Edit ") + name).c_str()
            );  // Will be closed in the edit dialog accept/reject
            PartDesignGui::setEdit(support.getValue(), pcActiveBody);
        }
        else if (pcActiveBody) {

            // TODO Check how this will work outside of a body (2015-10-20, Fat-Zer)
            std::string FeatName = cmd.getUniqueObjectName(name.c_str(), pcActiveBody);

            pcActiveBody->getDocument()->openTransaction(
                std::string(std::string("Create ") + name).c_str()
            );  // Will be closed in the edit dialog accept/reject
            FCMD_OBJ_CMD(pcActiveBody, "newObject('" << fullTypeName << "','" << FeatName << "')");

            // remove the body from links in case it's selected as
            // otherwise a cyclic dependency will be created
            support.removeValue(pcActiveBody);

            auto Feat = pcActiveBody->getDocument()->getObject(FeatName.c_str());
            if (!Feat) {
                return;
            }

            // test if current selection fits a mode.
            if (support.getSize() > 0) {
                Part::AttachExtension* pcDatum = Feat->getExtensionByType<Part::AttachExtension>();
                pcDatum->attacher().setReferences(support);
                SuggestResult sugr;
                pcDatum->attacher().suggestMapModes(sugr);
                if (sugr.message == Attacher::SuggestResult::srOK) {
                    // fits some mode. Populate AttachmentSupport property.
                    FCMD_OBJ_CMD(Feat, "AttachmentSupport = " << support.getPyReprString());
                    FCMD_OBJ_CMD(
                        Feat,
                        "MapMode = '" << AttachEngine::getModeName(sugr.bestFitMode) << "'"
                    );
                    if (midpointPick && support.getSize() == 1) {
                        PartGui::TaskAttacher::markMidpointPick(Feat);
                    }
                }
                else {
                    QMessageBox::information(
                        Gui::getMainWindow(),
                        QObject::tr("Invalid Selection"),
                        QObject::tr("There are no attachment modes that fit selected objects. Select something else.")
                    );
                }
            }
            cmd.doCommand(
                Gui::Command::Doc,
                "App.activeDocument().recompute()"
            );  // recompute the feature based on its references
            PartDesignGui::setEdit(Feat, pcActiveBody);
        }
        else {
            QMessageBox::warning(
                Gui::getMainWindow(),
                QObject::tr("Error"),
                QObject::tr("There is no active body. Please activate a body before inserting a datum entity.")
            );
        }
    }
    catch (Base::Exception& e) {
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Error"),
            QApplication::translate("Exception", e.what())
        );
    }
    catch (Standard_Failure& e) {
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Error"),
            QString::fromLatin1(e.GetMessageString())
        );
    }
}

/* Datum feature commands =======================================================*/

DEF_STD_CMD_A(CmdPartDesignPlane)

CmdPartDesignPlane::CmdPartDesignPlane()
    : Command("PartDesign_Plane")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Datum Plane");
    sToolTipText = QT_TR_NOOP("Creates a new datum plane");
    sWhatsThis = "PartDesign_Plane";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Plane";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignPlane::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    UnifiedDatumCommand(*this, Base::Type::fromName("PartDesign::Plane"), "DatumPlane");
}

bool CmdPartDesignPlane::isActive()
{
    if (getActiveGuiDocument()) {
        return true;
    }
    else {
        return false;
    }
}

DEF_STD_CMD_A(CmdPartDesignLine)

CmdPartDesignLine::CmdPartDesignLine()
    : Command("PartDesign_Line")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Datum Line");
    sToolTipText = QT_TR_NOOP("Creates a new datum line");
    sWhatsThis = "PartDesign_Line";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Line";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignLine::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    UnifiedDatumCommand(*this, Base::Type::fromName("PartDesign::Line"), "DatumLine");
}

bool CmdPartDesignLine::isActive()
{
    if (getActiveGuiDocument()) {
        return true;
    }
    else {
        return false;
    }
}

DEF_STD_CMD_A(CmdPartDesignPoint)

CmdPartDesignPoint::CmdPartDesignPoint()
    : Command("PartDesign_Point")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Datum Point");
    sToolTipText = QT_TR_NOOP("Creates a new datum point");
    sWhatsThis = "PartDesign_Point";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Point";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignPoint::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    UnifiedDatumCommand(*this, Base::Type::fromName("PartDesign::Point"), "DatumPoint");
}

bool CmdPartDesignPoint::isActive()
{
    if (getActiveGuiDocument()) {
        return true;
    }
    else {
        return false;
    }
}

DEF_STD_CMD_A(CmdPartDesignCS)

CmdPartDesignCS::CmdPartDesignCS()
    : Command("PartDesign_CoordinateSystem")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Local Coordinate System");
    sToolTipText = QT_TR_NOOP("Creates a new local coordinate system");
    sWhatsThis = "PartDesign_CoordinateSystem";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_CoordinateSystem";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignCS::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    UnifiedDatumCommand(*this, Base::Type::fromName("PartDesign::CoordinateSystem"), "Local_CS");
}

bool CmdPartDesignCS::isActive()
{
    if (getActiveGuiDocument()) {
        return true;
    }
    else {
        return false;
    }
}

//===========================================================================
// PartDesign_ShapeBinder
//===========================================================================

DEF_STD_CMD_A(CmdPartDesignShapeBinder)

CmdPartDesignShapeBinder::CmdPartDesignShapeBinder()
    : Command("PartDesign_ShapeBinder")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Shape Binder");
    sToolTipText = QT_TR_NOOP("Creates a new shape binder");
    sWhatsThis = "PartDesign_ShapeBinder";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_ShapeBinder";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignShapeBinder::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    App::PropertyLinkSubList support;
    getSelection().getAsPropertyLinkSubList(support);

    bool bEditSelected = false;
    if (support.getSize() == 1 && support.getValue()) {
        if (support.getValue()->isDerivedFrom<PartDesign::ShapeBinder>()) {
            bEditSelected = true;
        }
    }

    if (bEditSelected) {
        openCommand(QT_TRANSLATE_NOOP("Command", "Edit Shape Binder"));
        PartDesignGui::setEdit(support.getValue());
    }
    else {
        PartDesign::Body* pcActiveBody = PartDesignGui::getBody(/*messageIfNot = */ true);
        if (!pcActiveBody) {
            return;
        }

        // remove the body from links in case it's selected as
        // otherwise a cyclic dependency will be created
        support.removeValue(pcActiveBody);

        // A selection the binder would bind only part of (two objects, or an object both whole
        // and by its elements) makes no binder (ops#251); by labels, translated (ops#266)
        const QString dropped = PartDesignGui::TaskShapeBinder::droppedText(&support);
        if (!dropped.isEmpty()) {
            QMessageBox::warning(Gui::getMainWindow(), QObject::tr("Shape Binder"), dropped);
            return;
        }

        std::string FeatName = getUniqueObjectName("ShapeBinder", pcActiveBody);

        openCommand(QT_TRANSLATE_NOOP("Command", "Create Shape Binder"));
        FCMD_OBJ_CMD(pcActiveBody, "newObject('PartDesign::ShapeBinder','" << FeatName << "')");

        auto Feat = pcActiveBody->getObject(FeatName.c_str());
        if (!Feat) {
            return;
        }

        // test if current selection fits a mode.
        if (support.getSize() > 0) {
            FCMD_OBJ_CMD(Feat, "Support = " << support.getPyReprString());
        }
        updateActive();
        PartDesignGui::setEdit(Feat, pcActiveBody);
    }
    // TODO do a proper error processing (2015-09-11, Fat-Zer)
}

bool CmdPartDesignShapeBinder::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_SubShapeBinder
//===========================================================================

DEF_STD_CMD_A(CmdPartDesignSubShapeBinder)

// A pick in another Body comes as a path through it, (Body2, "PadB.Face5"): a binder of that
// depends on the whole Body, so two Bodies with binders of each other make a cycle that never
// settles (FreeCAD-CH ops#308 T2). The feature itself, (PadB, "Face5"), is bound instead; the
// binder follows its Body's placement. A whole Body picked stays as it is, and so does every pick
// with no active Body: the binder is then made at the top level, where no cycle through a Body forms.
// A pick through App::Parts, (P1, "Body2.PadB.Face5"), is followed down to the Body's feature the
// same way (ops#321: the binder depended on the whole Part); a whole Part or Body picked, or a path
// through anything else (an App::Link), stays as it is.
static void bindFeaturesNotBodies(
    std::map<App::DocumentObject*, std::vector<std::string>>& values,
    const PartDesign::Body* active
)
{
    // The feature and its element that sub names from obj, through App::Parts and then a Body
    // other than the active one; none when it names something else
    auto featurePick = [active](App::DocumentObject* obj, const std::string& sub)
        -> std::optional<std::pair<App::DocumentObject*, std::string>> {
        App::DocumentObject* current = obj;
        std::size_t start = 0;
        while (current) {
            const auto dot = sub.find('.', start);
            if (dot == std::string::npos) {
                return std::nullopt;
            }
            App::DocumentObject* child =
                obj->getSubObject(sub.substr(0, dot + 1).c_str(), nullptr, nullptr, false);
            if (auto body = freecad_cast<PartDesign::Body*>(current)) {
                if (body == active || !child || !body->hasObject(child) || dot + 1 >= sub.size()) {
                    return std::nullopt;
                }
                return std::make_pair(child, sub.substr(dot + 1));
            }
            auto part = freecad_cast<App::Part*>(current);
            if (!part || !child || !part->hasObject(child)) {
                return std::nullopt;
            }
            current = child;
            start = dot + 1;
        }
        return std::nullopt;
    };

    std::map<App::DocumentObject*, std::vector<std::string>> result;
    for (auto& [obj, subs] : values) {
        if (!active || subs.empty()) {
            auto& kept = result[obj];
            kept.insert(kept.end(), subs.begin(), subs.end());
            continue;
        }
        for (const auto& sub : subs) {
            if (auto pick = featurePick(obj, sub)) {
                result[pick->first].push_back(pick->second);
            }
            else {
                result[obj].push_back(sub);
            }
        }
    }
    values = std::move(result);
}

CmdPartDesignSubShapeBinder::CmdPartDesignSubShapeBinder()
    : Command("PartDesign_SubShapeBinder")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Sub-Shape Binder");
    sToolTipText = QT_TR_NOOP(
        "Creates a reference to geometry from one or more objects, allowing it to be used inside "
        "or outside a body. It tracks relative placements, supports multiple geometry types "
        "(solids, faces, edges, vertices), and can work with objects in the same or external "
        "documents."
    );
    sWhatsThis = "PartDesign_SubShapeBinder";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_SubShapeBinder";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignSubShapeBinder::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    App::DocumentObject* parent = nullptr;
    std::string parentSub;
    std::map<App::DocumentObject*, std::vector<std::string>> values;
    for (auto& sel : Gui::Selection().getCompleteSelection(Gui::ResolveMode::NoResolve)) {
        if (!sel.pObject) {
            continue;
        }
        auto& subs = values[sel.pObject];
        if (sel.SubName && sel.SubName[0]) {
            subs.emplace_back(sel.SubName);
        }
    }

    std::string FeatName;
    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(false, true, true, &parent, &parentSub);
    FeatName = getUniqueObjectName("Binder", pcActiveBody);
    if (parent) {
        decltype(values) links;
        for (auto& v : values) {
            App::DocumentObject* obj = v.first;
            if (obj != parent) {
                auto& subs = links[obj];
                subs.insert(subs.end(), v.second.begin(), v.second.end());
                continue;
            }
            for (auto& sub : v.second) {
                auto link = obj;
                auto linkSub = parentSub;
                parent->resolveRelativeLink(linkSub, link, sub);
                if (link && link != pcActiveBody) {
                    links[link].push_back(sub);
                }
            }
        }
        values = std::move(links);
    }
    bindFeaturesNotBodies(values, pcActiveBody);

    PartDesign::SubShapeBinder* binder = nullptr;
    try {
        openCommand(QT_TRANSLATE_NOOP("Command", "Create Sub-Shape Binder"));
        if (pcActiveBody) {
            FCMD_OBJ_CMD(pcActiveBody, "newObject('PartDesign::SubShapeBinder','" << FeatName << "')");
            binder = dynamic_cast<PartDesign::SubShapeBinder*>(
                pcActiveBody->getObject(FeatName.c_str())
            );
        }
        else {
            doCommand(
                Command::Doc,
                "App.ActiveDocument.addObject('PartDesign::SubShapeBinder','%s')",
                FeatName.c_str()
            );
            binder = dynamic_cast<PartDesign::SubShapeBinder*>(
                App::GetApplication().getActiveDocument()->getObject(FeatName.c_str())
            );
        }
        if (!binder) {
            return;
        }
        binder->setLinks(std::move(values));
        updateActive();
        commitCommand();
    }
    catch (Base::Exception& e) {
        e.reportException();
        QMessageBox::critical(
            Gui::getMainWindow(),
            QObject::tr("Sub-shape binder"),
            QApplication::translate("Exception", e.what())
        );
        abortCommand();
    }
}

bool CmdPartDesignSubShapeBinder::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_Clone
//===========================================================================

DEF_STD_CMD_A(CmdPartDesignClone)

CmdPartDesignClone::CmdPartDesignClone()
    : Command("PartDesign_Clone")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Clone");
    sToolTipText = QT_TR_NOOP("Copies a solid object parametrically as the base feature of a new body");
    sWhatsThis = "PartDesign_Clone";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Clone";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignClone::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    std::vector<App::DocumentObject*> objs = getSelection().getObjectsOfType(
        Part::Feature::getClassTypeId()
    );

    if (objs.size() == 1) {
        // As suggested in https://forum.freecad.org/viewtopic.php?f=3&t=25265&p=198547#p207336
        // put the clone into its own new body.
        // This also fixes bug #3447 because the clone is a PD feature and thus
        // requires a body where it is part of.
        openCommand(QT_TRANSLATE_NOOP("Command", "Create Clone"));

        auto obj = objs[0];
        auto objCmd = getObjectCmd(obj);
        std::string cloneName = getUniqueObjectName("Clone", obj);
        std::string bodyName = getUniqueObjectName("Body", obj);
        bool allowCompound = PartDesign::PartDesignParameter::instance()->getAllowCompoundDefault();

        // Create body and clone
        Gui::cmdAppDocument(
            obj,
            std::stringstream() << "addObject('PartDesign::Body','" << bodyName << "')"
        );
        Gui::cmdAppDocument(
            obj,
            std::stringstream() << "addObject('PartDesign::FeatureBase','" << cloneName << "')"
        );

        auto bodyObj = obj->getDocument()->getObject(bodyName.c_str());
        auto cloneObj = obj->getDocument()->getObject(cloneName.c_str());

        // In the first step set the group link and tip of the body
        Gui::cmdAppObject(
            bodyObj,
            std::stringstream() << "AllowCompound = " << Gui::asString(allowCompound)
        );
        Gui::cmdAppObject(bodyObj, std::stringstream() << "Group = [" << getObjectCmd(cloneObj) << "]");
        Gui::cmdAppObject(bodyObj, std::stringstream() << "Tip = " << getObjectCmd(cloneObj));

        // In the second step set the link of the base feature
        Gui::cmdAppObject(cloneObj, std::stringstream() << "BaseFeature = " << objCmd);
        Gui::cmdAppObject(cloneObj, std::stringstream() << "Placement = " << objCmd << ".Placement");
        copyPlacementExpressions(cloneObj, obj);
        Gui::cmdAppObject(cloneObj, std::stringstream() << "setEditorMode('Placement', 0)");

        updateActive();
        copyVisual(cloneObj, "ShapeAppearance", obj);
        copyVisual(cloneObj, "LineColor", obj);
        copyVisual(cloneObj, "PointColor", obj);
        copyVisual(cloneObj, "Transparency", obj);
        copyVisual(cloneObj, "DisplayMode", obj);
        commitCommand();
    }
}

bool CmdPartDesignClone::isActive()
{
    return getSelection().countObjectsOfType<Part::Feature>() == 1;
}

//===========================================================================
// PartDesign_Sketch
//===========================================================================

/* Sketch commands =======================================================*/
DEF_STD_CMD_A(CmdPartDesignNewSketch)

CmdPartDesignNewSketch::CmdPartDesignNewSketch()
    : Command("PartDesign_NewSketch")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("New Sketch");
    sToolTipText = QT_TR_NOOP("Creates a new sketch");
    sWhatsThis = "PartDesign_NewSketch";
    sStatusTip = sToolTipText;
    sPixmap = "Sketcher_NewSketch";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}


void CmdPartDesignNewSketch::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    PartDesignGui::SketchWorkflow creator(getActiveGuiDocument());
    creator.createSketch();
}

bool CmdPartDesignNewSketch::isActive()
{
    if (getActiveGuiDocument()) {
        return true;
    }
    else {
        return false;
    }
}

//===========================================================================
// Common utility functions for all features creating solids
//===========================================================================

static void finishFeature(
    const Gui::Command* cmd,
    App::DocumentObject* feature,
    App::DocumentObject* prevSolidFeature = nullptr,
    const bool hidePrevSolid = true,
    const bool updateDocument = true
)
{
    PartDesign::Body* activeBody;

    if (prevSolidFeature) {
        // insert into the same body as the given previous one
        activeBody = PartDesignGui::getBodyFor(prevSolidFeature, /*messageIfNot = */ false);
    }
    else {
        activeBody = PartDesignGui::getBody(/*messageIfNot = */ false);
    }

    if (hidePrevSolid && prevSolidFeature) {
        FCMD_OBJ_HIDE(prevSolidFeature);
    }

    if (updateDocument) {
        cmd->updateActive();
    }
    else {
        feature->recomputeFeature();
    }

    auto base = dynamic_cast<PartDesign::Feature*>(feature);
    if (base) {
        base = dynamic_cast<PartDesign::Feature*>(base->getBaseObject(true));
    }
    App::DocumentObject* obj = base;
    if (!obj) {
        obj = activeBody;
    }

    // Do this before calling setEdit to avoid to override the 'Shape preview' mode (#0003621)
    if (obj) {
        cmd->copyVisual(feature, "ShapeAppearance", obj);
        cmd->copyVisual(feature, "LineColor", obj);
        cmd->copyVisual(feature, "PointColor", obj);
        cmd->copyVisual(feature, "Transparency", obj);
        cmd->copyVisual(feature, "DisplayMode", obj);
    }

    // A tool started while its dialog is open drops it when the user gave it nothing (rank 24, F2)
    PartDesignGui::TaskDlgFeatureParameters::noteCreated(feature);
    // The feature's own Body: a new Extrude may have gone to another part (hands-on check A-1)
    PartDesign::Body* featureBody = PartDesign::Body::findBodyOf(feature);
    PartDesignGui::setEdit(
        feature,
        featureBody && featureBody != activeBody ? featureBody : activeBody
    );
    cmd->doCommand(cmd->Gui, "Gui.Selection.clearSelection()");
}

//===========================================================================
// Common utility functions for ProfileBased features
//===========================================================================

// Take a list of Part2DObjects and classify them for creating a
// ProfileBased feature. FirstFreeSketch is the first free sketch in the same body
// or sketches.end() if non available. The returned number is the amount of free sketches
unsigned validateSketches(
    std::vector<App::DocumentObject*>& sketches,
    std::vector<PartDesignGui::TaskFeaturePick::featureStatus>& status,
    std::vector<App::DocumentObject*>::iterator& firstFreeSketch
)
{
    // TODO Review the function for non-part bodies (2015-09-04, Fat-Zer)
    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(false);
    App::Part* pcActivePart = PartDesignGui::getPartFor(pcActiveBody, false);

    // TODO: If the user previously opted to allow multiple use of sketches or use of sketches from
    // other bodies, then count these as valid sketches!
    unsigned freeSketches = 0;
    firstFreeSketch = sketches.end();

    for (std::vector<App::DocumentObject*>::iterator s = sketches.begin(); s != sketches.end(); s++) {
        // FreeCAD-CH (ops#325): a sketch of another Body of the same studio is linked directly,
        // and may be used there too
        const bool studioSketch = pcActiveBody && !pcActiveBody->hasObject(*s)
            && PartDesignGui::isStudioSelection(pcActiveBody, *s);

        if (!pcActiveBody) {
            // We work in the old style outside any body
            if (PartDesign::Body::findBodyOf(*s)) {
                status.push_back(PartDesignGui::TaskFeaturePick::otherPart);
                continue;
            }
        }
        else if (!pcActiveBody->hasObject(*s) && !studioSketch) {
            // Check whether this plane belongs to a body of the same part
            PartDesign::Body* b = PartDesign::Body::findBodyOf(*s);
            if (!b) {
                status.push_back(PartDesignGui::TaskFeaturePick::notInBody);
            }
            else if (pcActivePart && pcActivePart->hasObject(b, true)) {
                status.push_back(PartDesignGui::TaskFeaturePick::otherBody);
            }
            else {
                status.push_back(PartDesignGui::TaskFeaturePick::otherPart);
            }

            continue;
        }

        // Base::Console().error("Checking sketch %s\n", (*s)->getNameInDocument());
        //  Check whether this sketch is already being used by another feature
        //  Body features don't count...
        std::vector<App::DocumentObject*> inList = (*s)->getInList();
        std::vector<App::DocumentObject*>::iterator o = inList.begin();
        while (o != inList.end()) {
            // Base::Console().error("Inlist: %s\n", (*o)->getNameInDocument());
            if ((*o)->isDerivedFrom<PartDesign::Body>()) {
                o = inList.erase(o);  // ignore bodies
            }
            else if (!((*o)->isDerivedFrom<PartDesign::Feature>())) {
                o = inList.erase(o);  // ignore non-partDesign
            }
            else {
                ++o;
            }
        }
        if (!inList.empty() && !studioSketch) {
            status.push_back(PartDesignGui::TaskFeaturePick::isUsed);
            continue;
        }

        if (pcActiveBody && !studioSketch && pcActiveBody->isAfterInsertPoint(*s)) {
            status.push_back(PartDesignGui::TaskFeaturePick::afterTip);
            continue;
        }

        // Check whether the sketch shape is valid
        Part::Part2DObject* sketch = static_cast<Part::Part2DObject*>(*s);
        const TopoDS_Shape& shape = sketch->Shape.getValue();
        if (shape.IsNull()) {
            status.push_back(PartDesignGui::TaskFeaturePick::invalidShape);
            continue;
        }

        // count free wires
        int ctWires = 0;
        TopExp_Explorer ex;
        for (ex.Init(shape, TopAbs_WIRE); ex.More(); ex.Next()) {
            ctWires++;
        }
        if (ctWires == 0) {
            status.push_back(PartDesignGui::TaskFeaturePick::noWire);
            continue;
        }

        // All checks passed - found a valid sketch. Another part's is offered in the pick dialog
        // but never taken without asking (ops#325)
        if (!studioSketch) {
            if (firstFreeSketch == sketches.end()) {
                firstFreeSketch = s;
            }
            freeSketches++;
        }
        status.push_back(PartDesignGui::TaskFeaturePick::validFeature);
    }

    return freeSketches;
}

/**
 *  Partially pulled from Linkstage3 importExternalObjects for toponaming element map
 *  compatibility with sketches that contain point objects.  By adding an empty
 *  subobject when appropriate, we allow those sketches to be used as profiles without error.
 *
 * @param prop  The property ( generally a Profile link )
 * @param _sobjs    Subobjects to use
 * @param report    True if we should raise a dialog, otherwise raise and exception
 * @return  True if elements were found
 */
bool importExternalElements(App::PropertyLinkSub& prop, std::vector<App::SubObjectT> _sobjs)
{
    if (!prop.getName() || !prop.getName()[0]) {
        FC_THROWM(Base::RuntimeError, "Invalid property");
    }
    auto editObj = freecad_cast<App::DocumentObject*>(prop.getContainer());
    if (!editObj) {
        FC_THROWM(Base::RuntimeError, "Editing object not found");
    }
    auto body = PartDesign::Body::findBodyOf(editObj);
    if (!body) {
        FC_THROWM(Base::RuntimeError, "No body for editing object: " << editObj->getNameInDocument());
    }
    std::map<App::DocumentObject*, std::vector<std::string>> links;
    std::vector<App::SubObjectT> sobjs;
    auto docName = editObj->getDocument()->getName();
    auto inList = editObj->getInListEx(true);
    auto inListProp = editObj->getInListExProp(true);
    for (auto sobjT : _sobjs) {
        auto sobj = sobjT.getSubObject();
        if (sobj == editObj) {
            continue;
        }
        if (!sobj) {
            FC_THROWM(Base::RuntimeError, "Object not found: " << sobjT.getSubObjectFullName(docName));
        }
        if (App::GetApplication().isFineGrainedRecomputeEnabled()) {
            // Fully mimics the else block except for taking into account input properties.
            for (const auto& [fromObj, fromProp, toObj, toProp] : inListProp) {
                if (fromObj == sobj && !toObj->isInputProperty(toProp)) {
                    FC_THROWM(
                        Base::RuntimeError,
                        "Cyclic dependency on object " << sobjT.getSubObjectFullName(docName)
                    );
                }
            }
        }
        else {
            if (inList.count(sobj)) {
                FC_THROWM(
                    Base::RuntimeError,
                    "Cyclic dependency on object " << sobjT.getSubObjectFullName(docName)
                );
            }
        }
        sobjT.normalized();
        // Make sure that if a subelement is chosen for some object,
        // we exclude whole object reference for that object.
        auto& subs = links[sobj];
        std::string element = sobjT.getOldElementName();
        if (element.size()) {
            if (subs.size() == 1 && subs.front().empty()) {
                // (ops#252: the loop never advanced past another object's entry)
                for (auto it = sobjs.begin(); it != sobjs.end(); ++it) {
                    if (it->getSubObject() == sobj) {
                        sobjs.erase(it);
                        break;
                    }
                }
                subs.clear();
            }
        }
        else if (subs.size() > 0) {
            continue;
        }
        subs.push_back(std::move(element));
        sobjs.push_back(sobjT);
    }

    int import = 0;
    App::DocumentObject* obj = nullptr;
    std::vector<std::string> subs;
    for (const auto& sobjT : sobjs) {
        auto sobj = sobjT.getSubObject();
        if (PartDesign::Body::findBodyOf(sobj) != body) {
            import = 1;
            break;
        }
        if (!obj) {
            obj = sobj;
        }
        else if (obj != sobj) {
            if (!import) {
                import = -1;
            }
            break;
        }
        subs.push_back(sobjT.getOldElementName());
    }
    if (!import) {
        if (subs.empty()) {
            subs.emplace_back();
        }
        if (obj == prop.getValue() && prop.getSubValues() == subs) {
            return false;
        }
        prop.setValue(obj, std::move(subs));
        return true;
    }
    return false;
}

// FreeCAD-CH (ops#640, rank 13): the features whose dialog has a Profile field start with no
// profile and wait for its pick, as Onshape's profile features do. Revolve's, Groove's and Helix's
// dialogs have one since rank 21
static bool dialogTakesProfile(const std::string& which)
{
    return which == "Pad" || which == "Pocket" || which == "Hole" || which == "AdditiveLoft"
        || which == "SubtractiveLoft" || which == "AdditivePipe" || which == "SubtractivePipe"
        || which == "Revolution" || which == "Groove" || which == "AdditiveHelix"
        || which == "SubtractiveHelix";
}

// A line a Revolve, Groove or Helix takes as its axis (ops#640, rank 21): an origin axis or a datum
// line (\a sub ''), or one straight edge of a shape, a sketch's included (\a sub its name)
static bool isAxisPick(const App::DocumentObject* obj, const std::vector<std::string>& subs, std::string& sub)
{
    if (!obj) {
        return false;
    }
    if (obj->isDerivedFrom<App::Line>() || obj->isDerivedFrom<PartDesign::Line>()) {
        sub.clear();
        return true;
    }
    auto feature = freecad_cast<const Part::Feature*>(obj);
    if (!feature || subs.size() != 1 || subs.front().rfind("Edge", 0) != 0) {
        return false;
    }
    try {
        const Part::TopoShape edge(
            feature->Shape.getShape().getSubShape(subs.front().c_str(), /*silent=*/true)
        );
        if (edge.isNull() || !edge.isLinearEdge()) {
            return false;
        }
    }
    catch (const Base::Exception&) {
        return false;
    }
    catch (const Standard_Failure&) {
        return false;
    }
    sub = subs.front();
    return true;
}

// A face of a solid that isn't planar: an extrude can't take it (ops#640, rank 5; Onshape's
// Extrude refuses a curved face at pick time, B3-4)
static bool isCurvedFace(const App::DocumentObject* obj, const std::string& sub)
{
    auto feature = freecad_cast<const Part::Feature*>(obj);
    if (!feature || obj->isDerivedFrom<Part::Part2DObject>() || sub.rfind("Face", 0) != 0) {
        return false;
    }
    try {
        const Part::TopoShape face(
            feature->Shape.getShape().getSubShape(sub.c_str(), /*silent=*/true)
        );
        return !face.isNull() && !face.isPlanar(Attacher::AttachEnginePlane::planarPrecision());
    }
    catch (const Base::Exception&) {
        return false;
    }
    catch (const Standard_Failure&) {
        return false;
    }
}

// What a new feature left out of the selection, in the status of its open dialog's field for
// \a property (ops#640, rank 13: never a modal), through ReferenceField::setNote(), else on
// the status bar
static void noteLeftOut(const char* property, const QString& note)
{
    if (note.isEmpty()) {
        return;
    }
    if (Gui::TaskView::TaskDialog* dlg = Gui::Control().activeDialog()) {
        for (QWidget* widget : dlg->getDialogContent()) {
            if (!widget) {
                continue;
            }
            for (auto field : widget->findChildren<PartDesignGui::ReferenceField*>()) {
                if (field->propertyName() == property) {
                    field->setNote(note);
                    return;
                }
            }
        }
    }
    Gui::getMainWindow()->showMessage(note, 10000);
}

// FreeCAD-CH (ops#640, the hub's decision): a sketch outside any Body, in the studio of the
// feature's Body (the same App::Part, or both outside any), is a profile: Onshape reads any sketch
// of the studio. The feature takes it through an independent copy into its Body, attached where
// the sketch is (the pick dialog's Make independent copy, which no command opens any more)
static bool isFreeStudioSketch(const PartDesign::Body* body, const App::DocumentObject* obj)
{
    App::Part* studio = nullptr;
    if (!body || !obj || !obj->isDerivedFrom<Part::Part2DObject>()
        || obj->getDocument() != body->getDocument() || Part::BodyBase::bodyOfObject(obj)
        || !Part::BodyBase::studioOf(body, studio)) {
        return false;
    }
    return App::Part::getPartOfObject(obj, /*recursive=*/true) == studio;
}

void prepareProfileBased(
    PartDesign::Body* pcActiveBody,
    Gui::Command* cmd,
    const std::string& which,
    std::function<void(Part::Feature*, App::DocumentObject*)> func
)
{
    // FreeCAD-CH (ops#640, rank 21): a line selected after the profile, or alone, is a Revolve's,
    // Groove's or Helix's axis, as Onshape's Revolve keeps it. Written before the worker runs; the
    // workers keep an axis already set
    const bool takesAxis = which == "Revolution" || which == "Groove" || which == "AdditiveHelix"
        || which == "SubtractiveHelix";
    auto keptAxis = std::make_shared<std::pair<App::DocumentObjectT, std::string>>();
    auto writeKeptAxis = [keptAxis](App::DocumentObject* Feat) {
        App::DocumentObject* axis = keptAxis->first.getObject();
        if (axis && Feat && Feat->getPropertyByName("ReferenceAxis")) {
            FCMD_OBJ_CMD(
                Feat,
                "ReferenceAxis = (" << Gui::Command::getObjectCmd(axis) << ",['"
                                    << keptAxis->second << "'])"
            );
        }
    };

    auto base_worker = [=](App::DocumentObject* feature, const std::vector<std::string>& subs) {
        if (!feature || !feature->isDerivedFrom<Part::Feature>()) {
            return;
        }

        // Related to #0002760: when an operation can't be performed due to a broken
        // profile then make sure that it is recomputed when cancelling the operation
        // otherwise it might be impossible to see that it's broken.
        if (feature->isTouched()) {
            feature->recomputeFeature();
        }

        std::string FeatName = cmd->getUniqueObjectName(which.c_str(), pcActiveBody);

        cmd->openCommand(std::string("Make ") + which);

        // A sketch outside any Body: its copy in the Body, made in the feature's step, before it
        if (isFreeStudioSketch(pcActiveBody, feature)) {
            QString refusal;
            App::DocumentObject* copy = PartDesignGui::TaskFeaturePick::copySketchIntoBody(
                feature,
                pcActiveBody,
                &refusal
            );
            if (!copy) {
                cmd->abortCommand();
                Gui::getMainWindow()->showMessage(
                    refusal.isEmpty()
                        ? QObject::tr("'%1' can't be copied into the body")
                              .arg(QString::fromUtf8(feature->Label.getValue()))
                        : refusal,
                    10000
                );
                return;
            }
            feature = copy;
        }

        FCMD_OBJ_CMD(pcActiveBody, "newObject('PartDesign::" << which << "','" << FeatName << "')");
        auto Feat = pcActiveBody->getDocument()->getObject(FeatName.c_str());

        auto objCmd = Gui::Command::getObjectCmd(feature);

        // Populate the subs parameter by checking for external elements before
        // we construct our command.
        auto ProfileFeature = freecad_cast<PartDesign::ProfileBased*>(Feat);

        std::vector<std::string>& cmdSubs = const_cast<vector<std::string>&>(subs);
        if (subs.size() == 0) {
            importExternalElements(ProfileFeature->Profile, {feature});
            cmdSubs = ProfileFeature->Profile.getSubValues();
        }
        // run the command in console to set the profile (without selected subelements)
        auto runProfileCmd = [=]() {
            FCMD_OBJ_CMD(Feat, "Profile = " << objCmd);
        };

        // run the command in console to set the profile with selected subelements
        // useful to set, say, a face of a solid as the "profile"
        auto runProfileCmdWithSubs = [=]() {
            std::ostringstream ss;
            for (auto& s : cmdSubs) {
                ss << "'" << s << "',";
            }
            FCMD_OBJ_CMD(Feat, "Profile = (" << objCmd << ", [" << ss.str() << "])");
        };

        if (which.compare("AdditiveLoft") == 0 || which.compare("SubtractiveLoft") == 0) {
            // for additive and subtractive lofts set subvalues even for sketches
            // when a vertex is first selected
            auto subName = subs.empty() ? "" : subs.front();

            // `ProfileBased::getProfileShape()` and other methods will return
            // just the sub-shapes if they are set. So when whole sketches are
            // desired, do not set sub-values.
            if (feature->isDerivedFrom<Part::Part2DObject>() && subName.compare(0, 6, "Vertex") != 0) {
                runProfileCmd();
            }
            else {
                runProfileCmdWithSubs();
            }

            // for additive and subtractive lofts allow the user to preselect the sections
            std::vector<Gui::SelectionObject> selection = cmd->getSelection().getSelectionEx();
            if (selection.size() > 1) {  // treat additional selected objects as sections
                for (std::vector<Gui::SelectionObject>::size_type ii = 1; ii < selection.size();
                     ii++) {
                    // Add subvalues even for sketches in case we just want points
                    auto objCmdSection = Gui::Command::getObjectCmd(selection[ii].getObject());
                    const auto& subnames = selection[ii].getSubNames();
                    std::ostringstream ss;
                    if (!subnames.empty()) {
                        for (auto& s : subnames) {
                            ss << "'" << s << "',";
                        }
                    }
                    else {
                        // an empty string indicates the whole object
                        ss << "''";
                    }
                    FCMD_OBJ_CMD(Feat, "Sections += [(" << objCmdSection << ", [" << ss.str() << "])]");
                }
            }
        }
        else if (which.compare("AdditivePipe") == 0 || which.compare("SubtractivePipe") == 0) {
            // for additive and subtractive pipes set subvalues even for sketches
            // to support point sections
            auto subName = subs.empty() ? "" : subs.front();

            // `ProfileBased::getProfileShape()` and other methods will return
            // just the sub-shapes if they are set. So when whole sketches are
            // desired, don't set sub-values.
            if (feature->isDerivedFrom<Part::Part2DObject>() && subName.compare(0, 6, "Vertex") != 0) {
                runProfileCmd();
            }
            else {
                runProfileCmdWithSubs();
            }

            // for additive and subtractive pipes allow the user to preselect the spines
            std::vector<Gui::SelectionObject> selection = cmd->getSelection().getSelectionEx();
            if (selection.size() == 2) {  // treat additional selected object as spine
                std::vector<string> subnames = selection[1].getSubNames();
                auto objCmdSpine = Gui::Command::getObjectCmd(selection[1].getObject());
                if (selection[1].getObject()->isDerivedFrom<Part::Part2DObject>()
                    && subnames.empty()) {
                    FCMD_OBJ_CMD(Feat, "Spine = " << objCmdSpine);
                }
                else {
                    std::ostringstream ss;
                    for (auto& s : subnames) {
                        if (s.find("Edge") != std::string::npos) {
                            ss << "'" << s << "',";
                        }
                    }
                    FCMD_OBJ_CMD(Feat, "Spine = (" << objCmdSpine << ", [" << ss.str() << "])");
                }
            }
        }
        else {
            // Always use the subs
            runProfileCmdWithSubs();
        }

        writeKeptAxis(Feat);
        func(static_cast<Part::Feature*>(feature), Feat);
    };

    // FreeCAD-CH (ops#640, rank 13): no profile yet. The feature is made without one and fails
    // red until its dialog's Profile field, armed as its first empty field, takes the pick;
    // \a note says what was left out of the selection
    auto empty_worker = [=](const QString& note) {
        std::string FeatName = cmd->getUniqueObjectName(which.c_str(), pcActiveBody);
        cmd->openCommand(std::string("Make ") + which);
        FCMD_OBJ_CMD(pcActiveBody, "newObject('PartDesign::" << which << "','" << FeatName << "')");
        App::DocumentObject* Feat = pcActiveBody->getDocument()->getObject(FeatName.c_str());
        if (!Feat) {
            cmd->abortCommand();
            return;
        }
        {
            // Its missing profile isn't printed as an error while the dialog opens asking for it
            // (as a Revolve's missing axis, finishWaitingForAxis); the feature keeps its error
            Base::ObjectStatusLocker<App::Document::Status, App::Document> guard(
                App::Document::IgnoreErrorOnRecompute,
                Feat->getDocument(),
                true
            );
            writeKeptAxis(Feat);
            func(nullptr, Feat);
        }
        noteLeftOut("Profile", note);
    };


    // FreeCAD-CH (ops#640, round 3): a subtractive feature with nothing to subtract from is made
    // and fails red, 'No merge scope selected', as Onshape's Remove with an empty scope, unless
    // its tool overlaps a part it then opens in (openAsOnshape); there was a modal

    // if a profile is selected we can make our life easy and fast
    std::vector<Gui::SelectionObject> selection = cmd->getSelection().getSelectionEx();
    // FreeCAD-CH (ops#640, rank 13): a selection that can't make the profile is left out and
    // said in the Profile field's status, never in a modal (it was "Cannot use selected
    // object"); the feature then starts as with nothing selected
    bool leftOut = false;
    // The selection entry kept as the axis (rank 21): one after the first, or the only one when it
    // is no sketch (hands-on B-2: a sketch selected is the profile). Alone, it opens the dialog with
    // no profile, its Profile field armed and the axis set
    std::size_t axisEntry = selection.size();
    if (takesAxis) {
        for (std::size_t index = 0; index < selection.size(); ++index) {
            const App::DocumentObject* obj = selection[index].getObject();
            if (index == 0
                && (selection.size() != 1 || !obj || obj->isDerivedFrom<Part::Part2DObject>())) {
                continue;
            }
            std::string sub;
            if (obj
                && (PartDesign::Body::findBodyOf(obj) == pcActiveBody
                    || PartDesignGui::isStudioSelection(pcActiveBody, obj))
                && isAxisPick(obj, selection[index].getSubNames(), sub)) {
                keptAxis->first = App::DocumentObjectT(obj);
                keptAxis->second = sub;
                axisEntry = index;
                break;
            }
        }
        if (axisEntry == 0) {
            empty_worker(QString());
            return;
        }
    }
    if (!selection.empty()) {
        QString refused;
        const bool extrude = which == "Pad" || which == "Pocket";
        for (const auto& it : selection) {
            const App::DocumentObject* obj = it.getObject();
            if (!obj) {
                continue;
            }
            const QString label = QString::fromUtf8(obj->Label.getValue());
            const std::vector<std::string>& subs = it.getSubNames();
            const std::string sub = subs.empty() ? std::string() : subs.front();
            const bool first = &it == &selection.front();
            if (PartDesign::Body::findBodyOf(obj) != pcActiveBody
                && !(first && isFreeStudioSketch(pcActiveBody, obj))) {
                // the selected objects must belong to the body, or (FreeCAD-CH, ops#325) to
                // another part of its studio; the first pick is the profile (another part's face
                // may be a first feature's too, ops#325 2a), the others are sections or a spine;
                // a first pick may be a sketch outside any Body of the studio (ops#640)
                if (!PartDesignGui::isStudioSelection(pcActiveBody, obj)
                    || (first
                        && !PartDesign::ProfileBased::isStudioProfile(pcActiveBody, obj, sub.c_str()))) {
                    refused = QObject::tr("'%1' is not in the active body").arg(label);
                    break;
                }
            }
            if (!first) {
                continue;
            }
            // an origin plane or another object without a shape makes no profile (it made no
            // feature, without a word: PR 255 review L2)
            if (!obj->isDerivedFrom<Part::Feature>()) {
                refused = QObject::tr("'%1' can't be a profile").arg(label);
                break;
            }
            // of a solid an extrude takes planar faces only (rank 5; hands-on B-2: an edge
            // selected is left out, Onshape's Extrude opening with its field empty)
            for (const auto& element : subs) {
                if (!extrude || obj->isDerivedFrom<Part::Part2DObject>()) {
                    break;
                }
                if (element.rfind("Face", 0) != 0) {
                    refused = QObject::tr("'%1' %2 is not a face")
                                  .arg(label, QString::fromStdString(element));
                    break;
                }
                if (isCurvedFace(obj, element)) {
                    refused = QObject::tr("'%1' %2 is not planar")
                                  .arg(label, QString::fromStdString(element));
                    break;
                }
            }
            if (!refused.isEmpty()) {
                break;
            }
        }
        if (!refused.isEmpty()) {
            const QString note = QObject::tr("Left out of the selection: %1.").arg(refused);
            if (dialogTakesProfile(which)) {
                empty_worker(note);
                return;
            }
            // A command whose dialog has no Profile field (none since rank 21): the sketch is
            // chosen as with nothing selected
            Gui::getMainWindow()->showMessage(note, 10000);
            Gui::Selection().clearSelection();
            leftOut = true;
        }
    }
    if (!selection.empty() && !leftOut) {
        {
            // The first object's elements make the profile; a loft takes the other picks as
            // sections, a pipe a second pick's edges as its spine. Say which picks are left out
            // (ops#252: they were dropped without a word)
            const bool loft = which == "AdditiveLoft" || which == "SubtractiveLoft";
            const bool pipe = which == "AdditivePipe" || which == "SubtractivePipe";
            const std::size_t used = loft ? selection.size()
                                          : (pipe && selection.size() == 2 ? 2 : 1);
            QStringList dropped;
            QString spineNote;
            for (std::size_t index = 1; index < selection.size(); ++index) {
                App::DocumentObject* obj = selection[index].getObject();
                if (!obj) {
                    continue;
                }
                const QString label = QString::fromUtf8(obj->Label.getValue());
                if (index == axisEntry) {
                    continue;  // the axis, kept (rank 21)
                }
                if (index >= used) {
                    dropped << QStringLiteral("'%1'").arg(label);
                    continue;
                }
                if (pipe) {
                    const auto& subs = selection[index].getSubNames();
                    bool edge = false;
                    for (const auto& sub : subs) {
                        if (sub.find("Edge") == std::string::npos) {
                            dropped << QStringLiteral("'%1' %2").arg(label, QString::fromStdString(sub));
                        }
                        else {
                            edge = true;
                        }
                    }
                    if (!subs.empty() && !edge) {
                        // with no edge left, the spine is the whole object (PR 255 review L3)
                        spineNote = QObject::tr(" The whole of '%1' is the spine.").arg(label);
                    }
                }
            }
            App::DocumentObject* profile = selection.front().getObject();
            const QString profileLabel =
                profile ? QString::fromUtf8(profile->Label.getValue()) : QString();
            base_worker(profile, selection.front().getSubNames());
            // only when base_worker made a feature: it makes none on another object, such as an
            // origin plane (PR 255 review L2)
            if (!dropped.isEmpty() && profile && profile->isDerivedFrom<Part::Feature>()) {
                Gui::getMainWindow()->showMessage(
                    QObject::tr("The profile is '%1': a feature takes the elements of one object. "
                                "Left out of the selection: %2.")
                            .arg(profileLabel, dropped.join(QStringLiteral(", ")))
                        + spineNote,
                    10000
                );
            }
        }
        return;
    }

    // no face profile was selected, do the extended sketch logic

    // FreeCAD-CH (ops#640, rank 13): with nothing selected the dialog opens with its Profile
    // field armed, as Onshape's do: no sketch list (TaskFeaturePick), no "No sketch" modal, and
    // a sketch selected in another document is left out with a note (it was a modal, ops#410)
    if (dialogTakesProfile(which)) {
        QString note;
        for (App::DocumentObject* obj : cmd->getSelection().getObjectsOfType(
                 Part::Part2DObject::getClassTypeId(),
                 "*"
             )) {
            if (obj->getDocument() != cmd->getDocument()) {
                note = QObject::tr("Left out of the selection: '%1' is in the document '%2', not "
                                   "in the active document.")
                           .arg(
                               QString::fromUtf8(obj->Label.getValue()),
                               QString::fromUtf8(obj->getDocument()->Label.getValue())
                           );
                break;
            }
        }
        empty_worker(note);
        return;
    }

    bool bNoSketchWasSelected = false;
    // FreeCAD-CH (ops#410): the user chose to go on although a sketch of another document is
    // selected; the pick dialog then shows even for a single free sketch
    bool sketchOfAnotherDocumentSelected = false;
    // Get a valid sketch from the user
    // First check selections
    std::vector<App::DocumentObject*> sketches = cmd->getSelection().getObjectsOfType(
        Part::Part2DObject::getClassTypeId()
    );
    if (sketches.empty()) {  // no sketches were selected. Let user pick an object from valid ones
                             // available in document
        sketches = cmd->getDocument()->getObjectsOfType(Part::Part2DObject::getClassTypeId());
        bNoSketchWasSelected = true;

        // FreeCAD-CH (ops#410, decision 104): the selection holds only the active document's
        // objects (upstream PR 33716), so a sketch selected in another document is no profile.
        // Said, rather than left out: the command went on with a sketch of this document, or said
        // that none is available. The selection can be a leftover (switching documents doesn't
        // clear it), so the user is asked, and a sketch is never taken without the pick dialog.
        // A Link into the active document resolves to an object of it: not another document's
        App::DocumentObject* other = nullptr;
        for (App::DocumentObject* obj : cmd->getSelection().getObjectsOfType(
                 Part::Part2DObject::getClassTypeId(),
                 "*"
             )) {
            if (obj->getDocument() != cmd->getDocument()) {
                other = obj;
                break;
            }
        }
        if (other) {
            const QString otherLabel = QString::fromUtf8(other->Label.getValue());
            const QString otherDocLabel = QString::fromUtf8(other->getDocument()->Label.getValue());
            const QString activeLabel = QString::fromUtf8(cmd->getDocument()->Label.getValue());
            if (sketches.empty()) {
                QMessageBox::warning(
                    Gui::getMainWindow(),
                    QObject::tr("Sketch in another document"),
                    QObject::tr("'%1' is in the document '%2', not in the active document. Select "
                                "a sketch of the active document.")
                        .arg(otherLabel, otherDocLabel)
                );
                return;
            }
            QMessageBox msgBox(Gui::getMainWindow());
            msgBox.setIcon(QMessageBox::Warning);
            msgBox.setWindowTitle(QObject::tr("Sketch in another document"));
            msgBox.setText(
                QObject::tr("'%1' is in the document '%2', not in the active document. Continue "
                            "with a sketch of '%3'?")
                    .arg(otherLabel, otherDocLabel, activeLabel)
            );
            QPushButton* proceed
                = msgBox.addButton(QObject::tr("Continue"), QMessageBox::AcceptRole);
            QPushButton* cancel = msgBox.addButton(QMessageBox::Cancel);
            msgBox.setDefaultButton(QMessageBox::Cancel);
            msgBox.setEscapeButton(cancel);
            msgBox.exec();
            if (msgBox.clickedButton() != proceed) {
                return;
            }
            sketchOfAnotherDocumentSelected = true;
        }
    }

    if (sketches.empty()) {
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("No sketch to work on"),
            QObject::tr("No sketch is available in the document")
        );
        return;
    }

    std::vector<PartDesignGui::TaskFeaturePick::featureStatus> status;
    std::vector<App::DocumentObject*>::iterator firstFreeSketch;
    int freeSketches = validateSketches(sketches, status, firstFreeSketch);

    auto accepter = [=](const std::vector<App::DocumentObject*>& features) -> bool {
        if (features.empty()) {
            return false;
        }

        return true;
    };

    auto sketch_worker = [&, base_worker](std::vector<App::DocumentObject*> features) {
        // FreeCAD-CH (ops#245): the pick dialog's copy failed (reported in the Report view);
        // front() of the empty list was undefined behaviour
        if (features.empty()) {
            // the pick dialog copies nothing without an active body (ops#244 L6: the message said
            // the copy had failed)
            if (!PartDesignGui::getBody(false)) {
                QMessageBox::warning(
                    Gui::getMainWindow(),
                    QObject::tr("No active body"),
                    QObject::tr("There is no active body to copy the sketch into. Activate a "
                                "body and try again.")
                );
                return;
            }
            QMessageBox::warning(
                Gui::getMainWindow(),
                QObject::tr("No sketch"),
                QObject::tr("The selected sketch couldn't be copied into the body. See the Report "
                            "view.")
            );
            return;
        }
        base_worker(features.front(), {});
    };

    // if there is a sketch selected which is from another body or part we need to bring up the
    // pick task dialog to decide how those are handled
    bool extReference = std::find_if(
                            status.begin(),
                            status.end(),
                            [](const PartDesignGui::TaskFeaturePick::featureStatus& s) {
                                return s == PartDesignGui::TaskFeaturePick::otherBody
                                    || s == PartDesignGui::TaskFeaturePick::otherPart
                                    || s == PartDesignGui::TaskFeaturePick::notInBody;
                            }
                        )
        != status.end();

    // TODO Clean this up (2015-10-20, Fat-Zer)
    if (pcActiveBody && !bNoSketchWasSelected && extReference) {

        // Hint: In an older version the function expected the body to be inside
        // a Part container and if not an error was raised and the function aborted.
        // First of all, for the user this wasn't obvious because the error message
        // was quite confusing (and thus the user may have done the wrong thing since
        // they may have assumed the that the sketch was meant) and
        // Second, there is no need that the body must be inside a Part container.
        // For more details see: https://forum.freecad.org/viewtopic.php?f=19&t=32164
        // The function has been modified not to expect the body to be in the Part
        // and it now directly invokes the 'makeCopy' dialog.
        auto* pcActivePart = PartDesignGui::getPartFor(pcActiveBody, false);

        QDialog dia(Gui::getMainWindow());
        PartDesignGui::Ui_DlgReference dlg;
        dlg.setupUi(&dia);
        dia.setModal(true);
        int result = dia.exec();
        if (result == QDialog::DialogCode::Rejected) {
            return;
        }

        if (!dlg.radioXRef->isChecked()) {
            cmd->openCommand(QT_TRANSLATE_NOOP("Command", "Make Copy"));
            // the container it's added to: the active body, or else the active part
            auto oBody = PartDesignGui::getBodyFor(sketches[0], false);
            App::DocumentObject* target = oBody ? static_cast<App::DocumentObject*>(pcActiveBody)
                                                : pcActivePart;
            // FreeCAD-CH (ops#410, decision 104): the sketch is in the active document, so the
            // copy isn't refused (ops#327's guard against a dependent copy across documents is
            // gone with the selection that could reach it)
            auto copy = PartDesignGui::TaskFeaturePick::makeCopy(
                sketches[0],
                "",
                dlg.radioIndependent->isChecked(),
                target
            );
            if (!copy) {  // PR 360 review: makeCopy gives none without an object or a document
                cmd->abortCommand();
                return;
            }
            if (oBody) {
                pcActiveBody->addObject(copy);
            }
            else if (pcActivePart) {
                pcActivePart->addObject(copy);
            }

            sketches[0] = copy;
            firstFreeSketch = sketches.begin();
        }
    }

    // Show sketch choose dialog and let user pick sketch if no sketch was selected and no free one
    // available or multiple free ones are available
    if (bNoSketchWasSelected && (freeSketches != 1 || sketchOfAnotherDocumentSelected)) {

        Gui::TaskView::TaskDialog* dlg = Gui::Control().activeDialog();
        PartDesignGui::TaskDlgFeaturePick* pickDlg
            = qobject_cast<PartDesignGui::TaskDlgFeaturePick*>(dlg);
        if (dlg && !pickDlg) {
            QMessageBox msgBox(Gui::getMainWindow());
            msgBox.setText(QObject::tr("A dialog is already open in the task panel"));
            msgBox.setInformativeText(QObject::tr("Close this dialog?"));
            msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
            msgBox.setDefaultButton(QMessageBox::Yes);
            int ret = msgBox.exec();
            if (ret == QMessageBox::Yes) {
                Gui::Control().closeDialog();
            }
            else {
                return;
            }
        }

        if (dlg) {
            Gui::Control().closeDialog();
        }

        Gui::Selection().clearSelection();
        pickDlg = new PartDesignGui::TaskDlgFeaturePick(sketches, status, accepter, sketch_worker, true);
        // Logically dead code because 'bNoSketchWasSelected' must be true
        // if (!bNoSketchWasSelected && extReference)
        //    pickDlg->showExternal(true);

        Gui::Control().showDialog(pickDlg, cmd->getDocument());
    }
    else {
        std::vector<App::DocumentObject*> theSketch;
        if (!bNoSketchWasSelected) {
            theSketch.push_back(sketches[0]);
        }
        else {
            theSketch.push_back(*firstFreeSketch);
        }

        sketch_worker(theSketch);
    }
}

// FreeCAD-CH (ops#194): from a sketch in edit, Pad and Revolution close the sketch and take it as
// their profile, as Onshape's extrude and revolve keys (Shift+E, Shift+W) do. The sketch's task
// dialog would disable them, so they are ForEdit and check the dialog themselves.
static Sketcher::SketchObject* sketchInEdit()
{
    Gui::Document* guiDoc = Gui::Application::Instance->activeDocument();
    auto vp = guiDoc ? dynamic_cast<Gui::ViewProviderDocumentObject*>(guiDoc->getInEdit()) : nullptr;
    return vp ? dynamic_cast<Sketcher::SketchObject*>(vp->getObject()) : nullptr;
}

// What Command::testActive() checks for a command that isn't ForEdit, but a sketch in edit passes
// under the fork's keymap (FreeCAD's keeps upstream's: disabled in the sketch), and so does an
// open feature dialog holding its step (ops#640: the tool accepts that dialog first)
static bool allowedOrSketchInEdit(App::Document* doc)
{
    return (Gui::ForkKeymap::isOnshape() && sketchInEdit())
        || Gui::Command::stepLockedDocument() != nullptr
        || (Gui::Control().isAllowedAlterDocument(doc) && Gui::Control().isAllowedAlterView(doc)
            && Gui::Control().isAllowedAlterSelection(doc));
}

static void leaveSketchForProfile()
{
    Sketcher::SketchObject* sketch = sketchInEdit();
    if (!sketch) {
        return;
    }
    Gui::Document* guiDoc = Gui::Application::Instance->activeDocument();
    App::DocumentObjectT sketchT(sketch);
    Gui::Application::Instance->commandManager().runCommandByName("Sketcher_LeaveSketch");
    if (guiDoc->getInEdit() || !sketchT.getObject()) {
        return;  // the sketch stayed open: leave its selection alone
    }
    Gui::Selection().clearSelection();
    Gui::Selection().addSelection(sketchT.getDocumentName().c_str(), sketchT.getObjectName().c_str());
}

void finishProfileBased(const Gui::Command* cmd, const Part::Feature* sketch, App::DocumentObject* Feat)
{
    if (sketch && sketch->isDerivedFrom<Part::Part2DObject>()) {
        FCMD_OBJ_HIDE(sketch);
    }
    finishFeature(cmd, Feat);
}

// The creation recompute of a Revolution or Groove still waiting for its axis: its "No axis"
// isn't printed as an error while the dialog opens asking for the pick, as Onshape's Revolve
// waits without one (FreeCAD-CH ops#643, review MISS); the feature keeps its error and message
// (the tree's mark and the dialog's banner say what it needs)
static void finishWaitingForAxis(
    const Gui::Command* cmd,
    const Part::Feature* sketch,
    App::DocumentObject* feature
)
{
    auto axis = dynamic_cast<App::PropertyLinkSub*>(feature->getPropertyByName("ReferenceAxis"));
    App::Document* doc = feature->getDocument();
    if (!axis || axis->getValue() || doc->testStatus(App::Document::IgnoreErrorOnRecompute)) {
        finishProfileBased(cmd, sketch, feature);
        return;
    }
    doc->setStatus(App::Document::IgnoreErrorOnRecompute, true);
    try {
        finishProfileBased(cmd, sketch, feature);
    }
    catch (...) {
        doc->setStatus(App::Document::IgnoreErrorOnRecompute, false);
        throw;
    }
    doc->setStatus(App::Document::IgnoreErrorOnRecompute, false);
}

// FreeCAD-CH (ops#640, round 3 of hands-on check A-1): a new Revolve, Loft, Sweep or Helix opens
// as Onshape's, as an Extrude does: an Add with the one part its tool touches, else New; a Remove
// in its own part, or in the one other part its tool overlaps instead. With no tool yet (no axis, no
// path, no section) the pick that makes it decides (TaskResultParameters::profileTaken).
//  recompute: the feature isn't computed with its last parameters yet
static void openAsOnshape(App::DocumentObject* feature, bool recompute)
{
    auto addSub = freecad_cast<PartDesign::FeatureAddSub*>(feature);
    if (!addSub) {
        return;
    }
    auto axis = dynamic_cast<App::PropertyLinkSub*>(feature->getPropertyByName("ReferenceAxis"));
    const bool waitsForAxis = addSub->isDerivedFrom<PartDesign::Revolved>() && axis
        && !axis->getValue();
    if (recompute && !waitsForAxis) {
        Gui::Command::updateActive();
    }
    if (!waitsForAxis && !addSub->AddSubShape.getShape().isNull()) {
        PartDesignGui::TaskResultParameters::applyOpeningOperation(feature);
    }
    else {
        PartDesignGui::TaskResultParameters::awaitOpeningOperation(feature);
    }
}

/* FreeCAD-CH (ops#654 S4, notes/parts-design.md 3.1, 3.5): in a studio that has a history list
 * (PartDesign::StudioList), Extrude and Extrude (remove) make a studio feature, an *owner*: the
 * Pad or Pocket in the studio, outside every Body, whose steps act on the parts of its scope. The
 * studio is the selected profile's, else the active Body's, else the active Part's (the document's
 * top level without one). Null without a list: today's path. sketchPart: the Body the selected
 * profile is in, if any
 */
namespace PartDesign
{
// App/StudioList.cpp (FreeCAD-CH ops#654 P5, P6a; declared where used)
PartDesignExport std::vector<Body*> studioLivePartsAt(const StudioList* list, int index);
}  // namespace PartDesign

namespace PartDesignGui
{
// StudioGui.cpp (FreeCAD-CH ops#654 S4 fix; declared where used)
bool studioPrefillPart(App::DocumentObject* owner, PartDesign::Body*& part);
void studioPrefillLive(App::DocumentObject* owner);
}  // namespace PartDesignGui

/* FreeCAD-CH ops#654, the list on first use (decision 337, notes/parts-design.md 10.8): the
 * studio's list is the only truth, so the first studio command (Extrude, Extrude (remove), the
 * patterns and Mirror, part mirror, Boolean) makes it, adopted from studioSequence(), in the
 * command's own transaction: undo or Cancel takes it back with the feature. Body members it
 * doesn't hold (sketches, datums, fillets made later) are adopted at reconcile. Sketch, datum,
 * Body, Fillet and Chamfer don't make it (Fillet and Chamfer make a studio feature in a listed studio,
 * P8a; unlisted, they keep the per-Body path until R0)
 */

/// An assembly is no studio: it never gets a list (an active Part or a profile's container may be one)
static bool isAssemblyStudio(const App::Part* studio)
{
    const Base::Type assembly = Base::Type::fromName("Assembly::AssemblyObject");
    return studio && !assembly.isBad() && studio->isDerivedFrom(assembly);
}

/// Why the studio, without a list, can't get one by adoption now (a loud refusal: the first
/// reconcile could change what the person sees without a word), else empty:
/// - rolled back (a Body's Tip moved back): the derived bar is one place for every Body, so a
///   Body whose rows the derived order puts below it would roll back at the first reconcile;
/// - an in-Body Boolean (not a Merge) whose tool is a part of the studio: the list knows no such
///   consumption, so the hidden tool would be a live part (a target, a pre-fill pick)
static QString studioListRefusal(App::Document* doc, App::Part* studio)
{
    if (!doc || PartDesign::StudioList::of(doc, studio, false)) {
        return {};
    }
    const auto bodies = PartDesign::studioBodies(doc, studio);
    for (auto body : bodies) {
        for (auto member : body->Group.getValues()) {
            auto boolean = freecad_cast<PartDesign::Boolean*>(member);
            if (!boolean || boolean->isMerge()) {
                continue;
            }
            for (auto tool : boolean->Group.getValues()) {
                if (std::ranges::find(bodies, tool) != bodies.end()) {
                    return QObject::tr("'%1' in '%2' uses the part '%3' as its tool, which the "
                                       "studio's history can't hold: studio features can't be "
                                       "made in this studio")
                        .arg(QString::fromUtf8(boolean->Label.getValue()),
                             QString::fromUtf8(body->Label.getValue()),
                             QString::fromUtf8(tool->Label.getValue()));
                }
            }
        }
    }
    if (PartDesign::isStudioRolledBack(doc, studio)) {
        return QObject::tr("The studio is rolled back: roll it to the end in the Features list "
                           "first, then make the studio feature");
    }
    return {};
}

/// Whether a studio command takes the studio path (an owner, a listed pattern) in studio: it has
/// a list, or one is made on first use. The hidden user parameter StudioListOnFirstUse (default
/// on, no UI) is a test hook only: off, a studio without a list keeps the sibling-era in-Body path,
/// for the GUI tests of that path until R0 removes it
static bool takesStudioPath(App::Document* doc, App::Part* studio)
{
    if (!doc) {
        return false;
    }
    if (PartDesign::StudioList::of(doc, studio, false)) {
        return true;
    }
    return App::GetApplication()
        .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/PartDesign")
        ->GetBool("StudioListOnFirstUse", true);
}

/// studioListRefusal(), said in the status bar and the report: true when refused
static bool refuseStudioList(App::Document* doc, App::Part* studio)
{
    const QString why = studioListRefusal(doc, studio);
    if (why.isEmpty()) {
        return false;
    }
    Gui::getMainWindow()->showMessage(why, 10000);
    Base::Console().error("%s\n", why.toUtf8().constData());
    return true;
}

/// The studio's list, made (adopted) if missing; inside the command's open transaction. Its callers'
/// later command lines (`PartDesign.studioInsert(...)`) need the module in the console, list or not
static PartDesign::StudioList* makeStudioList(App::Document* doc, App::Part* studio)
{
    Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
    if (PartDesign::StudioList* list = PartDesign::StudioList::of(doc, studio, false)) {
        return list;
    }
    const std::string studioCmd = studio
        ? Gui::Command::getObjectCmd(studio)
        : std::string("App.getDocument('") + doc->getName() + "')";
    Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.studioList(%s, True)", studioCmd.c_str());
    PartDesign::StudioList* list = PartDesign::StudioList::of(doc, studio, false);
    if (!list) {
        throw Base::RuntimeError("The studio's history list was not made");
    }
    return list;
}

/// The studio an owner goes in: the selected profile's, else the active Body's, else the active
/// Part's; false where it can't be (a profile of another document, an assembly's Body)
static bool ownerStudio(
    Gui::Command* cmd,
    App::Part*& studio,
    PartDesign::Body*& sketchPart,
    App::DocumentObject*& profile,
    std::vector<std::string>& subs
)
{
    studio = nullptr;
    sketchPart = nullptr;
    profile = nullptr;
    subs.clear();
    App::Document* doc = cmd->getDocument();
    if (!doc) {
        return false;
    }
    const std::vector<Gui::SelectionObject> selection = cmd->getSelection().getSelectionEx();
    if (!selection.empty() && selection.front().getObject()) {
        profile = const_cast<App::DocumentObject*>(selection.front().getObject());
        subs = selection.front().getSubNames();
        if (profile->getDocument() != doc) {
            return false;
        }
        sketchPart = PartDesign::Body::findBodyOf(profile);
        if (sketchPart) {
            if (!Part::BodyBase::studioOf(sketchPart, studio)) {
                return false;
            }
        }
        else {
            studio = App::Part::getPartOfObject(profile, /*recursive=*/true);
        }
    }
    else if (PartDesign::Body* active = PartDesignGui::getBody(/*messageIfNot = */ false)) {
        if (!Part::BodyBase::studioOf(active, studio)) {
            return false;
        }
    }
    else {
        studio = PartDesignGui::getActivePart();
    }
    return !isAssemblyStudio(studio);
}

/// FreeCAD-CH (ops#654 S4): Extrude in a studio makes an owner, in one step with the studio's
/// list (made on first use), its list entry, its scope and its first recompute (Cancel aborts all
/// of it); false: no studio (an assembly, another document's profile), today's path
static bool prepareStudioOwner(Gui::Command* cmd, const std::string& which, double length)
{
    if (which != "Pad" && which != "Pocket") {
        return false;
    }
    App::Part* studio = nullptr;
    PartDesign::Body* sketchPart = nullptr;
    App::DocumentObject* profile = nullptr;
    std::vector<std::string> subs;
    if (!ownerStudio(cmd, studio, sketchPart, profile, subs)) {
        return false;
    }
    App::Document* doc = cmd->getDocument();
    if (!takesStudioPath(doc, studio)) {
        return false;
    }
    if (refuseStudioList(doc, studio)) {
        return true;
    }
    // A profile: a sketch, its elements, or planar faces of a part's solid
    QString leftOut;
    if (profile && !profile->isDerivedFrom<Part::Feature>()) {
        leftOut = QObject::tr("Left out of the selection: '%1' can't be a profile.")
                      .arg(QString::fromUtf8(profile->Label.getValue()));
        profile = nullptr;
        subs.clear();
    }
    const std::string name = cmd->getUniqueObjectName(which.c_str());
    cmd->openCommand(std::string("Make ") + which);
    try {
        makeStudioList(doc, studio);
        Gui::cmdAppDocument(
            doc,
            std::ostringstream() << "addObject('PartDesign::" << which << "','" << name << "')"
        );
        App::DocumentObject* owner = doc->getObject(name.c_str());
        if (!owner) {
            throw Base::RuntimeError("The studio feature was not made");
        }
        const std::string ownerCmd = Gui::Command::getObjectCmd(owner);
        if (studio) {
            Gui::cmdAppObject(studio, std::ostringstream() << "addObject(" << ownerCmd << ")");
        }
        auto sketch = freecad_cast<Part::Part2DObject*>(profile);
        if (profile) {
            std::ostringstream ss;
            for (const auto& sub : subs) {
                ss << "'" << sub << "',";
            }
            FCMD_OBJ_CMD(
                owner,
                "Profile = (" << Gui::Command::getObjectCmd(profile) << ", [" << ss.str() << "])"
            );
        }
        FCMD_OBJ_CMD(owner, "Length = " << length);
        if (sketch) {
            FCMD_OBJ_CMD(
                owner,
                "ReferenceAxis = (" << Gui::Command::getObjectCmd(sketch) << ",['N_Axis'])"
            );
        }
        Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.studioInsert(%s, -1)", ownerCmd.c_str());
        // The scope Onshape's Extrude pre-fills (oracle 6, batch 6 Q1): the tool touching or
        // intersecting exactly one live part -> Add into it, else New; not the sketch's part or
        // the active Body. Extrude (remove) is the Extrude switched to Remove (Q1d, Q1e): the
        // part the tool meets going the Extrude's way (out of the material) stays its scope, else
        // none ("No merge scope selected"), and it cuts into the material, the Pocket's own way
        const bool remove = which == "Pocket";
        auto profileBased = freecad_cast<PartDesign::ProfileBased*>(owner);
        if (remove && profileBased) {
            profileBased->Reversed.setValue(true);
        }
        PartDesign::Body* target = nullptr;
        PartDesignGui::studioPrefillPart(owner, target);
        if (remove && profileBased) {
            profileBased->Reversed.setValue(false);
        }
        if (target) {
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.studioSetScopeIds(%s, ['%s'])",
                ownerCmd.c_str(),
                PartDesign::studioPartId(target).c_str()
            );
        }
        else if (!remove) {
            Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.studioNewPart(%s)", ownerCmd.c_str());
        }
        {
            // A missing profile isn't printed as an error while the dialog opens asking for it
            Base::ObjectStatusLocker<App::Document::Status, App::Document> guard(
                App::Document::IgnoreErrorOnRecompute,
                doc,
                profile == nullptr
            );
            Gui::cmdAppDocument(doc, "recompute()");
        }
        if (sketch) {
            FCMD_OBJ_HIDE(sketch);
        }
        PartDesignGui::TaskDlgFeatureParameters::noteCreated(owner);
        if (!remove) {
            // Picked again on every change of the tool until the person chooses (Q1f)
            PartDesignGui::studioPrefillLive(owner);
        }
        if (!PartDesignGui::setEdit(owner)) {
            throw Base::RuntimeError("The studio feature's dialog didn't open");
        }
        cmd->doCommand(cmd->Gui, "Gui.Selection.clearSelection()");
        if (!leftOut.isEmpty()) {
            noteLeftOut("Profile", leftOut);
        }
    }
    catch (const Base::Exception& e) {
        cmd->abortCommand();
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 10000);
        Base::Console().error("%s\n", e.what());
    }
    return true;
}

void prepareProfileBased(Gui::Command* cmd, const std::string& which, double length)
{
    if (prepareStudioOwner(cmd, which, length)) {
        return;
    }
    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    auto worker = [cmd, length, which](Part::Feature* profile, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        // specific parameters for Pad/Pocket
        FCMD_OBJ_CMD(Feat, "Length = " << length);
        Gui::Command::updateActive();

        Part::Part2DObject* sketch = dynamic_cast<Part::Part2DObject*>(profile);

        if (sketch) {
            std::ostringstream str;
            Gui::cmdAppObject(
                Feat,
                str << "ReferenceAxis = (" << Gui::Command::getObjectCmd(sketch) << ",['N_Axis'])"
            );
        }

        // FreeCAD-CH (ops#640, hands-on check A-1): a new Extrude opens as Onshape's, Add with
        // the one part its tool touches, else New. With no profile yet, its first one decides
        // A Remove (Pocket) opens with the part its tool overlaps (round 3)
        if (which == "Pad" || which == "Pocket") {
            if (profile) {
                PartDesignGui::TaskResultParameters::applyOpeningOperation(Feat);
            }
            else {
                PartDesignGui::TaskResultParameters::awaitOpeningOperation(Feat);
            }
        }

        finishProfileBased(cmd, sketch, Feat);
    };

    prepareProfileBased(pcActiveBody, cmd, which, worker);
}

//===========================================================================
// PartDesign_Pad
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignPad)

CmdPartDesignPad::CmdPartDesignPad()
    : Command("PartDesign_Pad")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Extrude");  // FreeCAD-CH (ops#605): Onshape's word
    sToolTipText = QT_TR_NOOP("Extrudes the selected sketch or profile and adds it to the body");
    sWhatsThis = "PartDesign_Pad";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Pad";
    eType |= ForEdit;  // FreeCAD-CH (ops#194): from a sketch in edit; isActive() checks the dialog
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignPad::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    leaveSketchForProfile();
    prepareProfileBased(this, "Pad", 10.0);
}

bool CmdPartDesignPad::isActive()
{
    return hasActiveDocument() && allowedOrSketchInEdit(getDocument());
}

//===========================================================================
// PartDesign_Pocket
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignPocket)

CmdPartDesignPocket::CmdPartDesignPocket()
    : Command("PartDesign_Pocket")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Extrude (remove)");  // FreeCAD-CH (ops#605): Onshape's word
    sToolTipText = QT_TR_NOOP("Extrudes the selected sketch or profile and removes it from the body");
    sWhatsThis = "PartDesign_Pocket";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Pocket";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignPocket::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    prepareProfileBased(this, "Pocket", 5.0);
}

bool CmdPartDesignPocket::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_Hole
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignHole)

CmdPartDesignHole::CmdPartDesignHole()
    : Command("PartDesign_Hole")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Hole");
    sToolTipText
        = QT_TR_NOOP("Creates holes in the active body at the center points of circles or arcs of the selected sketch or profile");
    sWhatsThis = "PartDesign_Hole";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Hole";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignHole::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    // FreeCAD-CH (ops#640, rank 14): the Hole goes in the part its sketch is on, active or not
    PartDesign::Body* pcActiveBody = commandBody(this, /*pickOwns = */ true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd](Part::Feature* sketch, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        finishProfileBased(cmd, sketch, Feat);
    };

    prepareProfileBased(pcActiveBody, this, "Hole", worker);
}

bool CmdPartDesignHole::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_Revolution
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignRevolution)

CmdPartDesignRevolution::CmdPartDesignRevolution()
    : Command("PartDesign_Revolution")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Revolve");
    sToolTipText = QT_TR_NOOP(
        "Revolves the selected sketch or profile around a line or axis and adds it to the body"
    );
    sWhatsThis = "PartDesign_Revolution";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Revolution";
    eType |= ForEdit;  // FreeCAD-CH (ops#194): as PartDesign_Pad
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignRevolution::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    leaveSketchForProfile();
    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd](Part::Feature* sketch, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        // No axis yet: the dialog waits for its pick, as Onshape's Revolve does (FreeCAD-CH
        // ops#643, the user's report 12); the pick turns it the way the axis suggests
        // (TaskRevolutionParameters::writeAxis)
        FCMD_OBJ_CMD(Feat, "Angle = 360.0");
        // where it opens: now with a kept axis, else at the axis pick (ops#640, round 3)
        openAsOnshape(Feat, /*recompute = */ true);

        finishWaitingForAxis(cmd, sketch, Feat);
    };

    prepareProfileBased(pcActiveBody, this, "Revolution", worker);
}

bool CmdPartDesignRevolution::isActive()
{
    return hasActiveDocument() && allowedOrSketchInEdit(getDocument());
}

//===========================================================================
// PartDesign_Groove
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignGroove)

CmdPartDesignGroove::CmdPartDesignGroove()
    : Command("PartDesign_Groove")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Groove");
    sToolTipText = QT_TR_NOOP(
        "Revolves the sketch or profile around a line or axis and removes it from the body"
    );
    sWhatsThis = "PartDesign_Groove";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Groove";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignGroove::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd](Part::Feature* sketch, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        // No axis yet, as for a Revolution (FreeCAD-CH ops#643)
        FCMD_OBJ_CMD(Feat, "Angle = 360.0");
        // where it opens: now with a kept axis, else at the axis pick (ops#640, round 3)
        openAsOnshape(Feat, /*recompute = */ true);

        finishWaitingForAxis(cmd, sketch, Feat);
    };

    prepareProfileBased(pcActiveBody, this, "Groove", worker);
}

bool CmdPartDesignGroove::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_AdditivePipe
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignAdditivePipe)

CmdPartDesignAdditivePipe::CmdPartDesignAdditivePipe()
    : Command("PartDesign_AdditivePipe")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Additive Pipe");
    sToolTipText = QT_TR_NOOP(
        "Sweeps the selected sketch or profile along a path and adds it to the body"
    );
    sWhatsThis = "PartDesign_AdditivePipe";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_AdditivePipe";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignAdditivePipe::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    // FreeCAD-CH (ops#640, rank 14): with no Body active, the picked part's
    PartDesign::Body* pcActiveBody = commandBody(this);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd](Part::Feature* sketch, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        // specific parameters for pipe
        Gui::Command::updateActive();
        openAsOnshape(Feat, /*recompute = */ false);  // ops#640, round 3

        finishProfileBased(cmd, sketch, Feat);
    };

    prepareProfileBased(pcActiveBody, this, "AdditivePipe", worker);
}

bool CmdPartDesignAdditivePipe::isActive()
{
    return hasActiveDocument();
}


//===========================================================================
// PartDesign_SubtractivePipe
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignSubtractivePipe)

CmdPartDesignSubtractivePipe::CmdPartDesignSubtractivePipe()
    : Command("PartDesign_SubtractivePipe")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Subtractive Pipe");
    sToolTipText = QT_TR_NOOP(
        "Sweeps the selected sketch or profile along a path and removes it from the body"
    );
    sWhatsThis = "PartDesign_SubtractivePipe";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_SubtractivePipe";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignSubtractivePipe::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    // FreeCAD-CH (ops#640, rank 14): with no Body active, the picked part's
    PartDesign::Body* pcActiveBody = commandBody(this);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd](Part::Feature* sketch, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        // specific parameters for pipe
        Gui::Command::updateActive();
        openAsOnshape(Feat, /*recompute = */ false);  // ops#640, round 3

        finishProfileBased(cmd, sketch, Feat);
    };

    prepareProfileBased(pcActiveBody, this, "SubtractivePipe", worker);
}

bool CmdPartDesignSubtractivePipe::isActive()
{
    return hasActiveDocument();
}


//===========================================================================
// PartDesign_AdditiveLoft
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignAdditiveLoft)

CmdPartDesignAdditiveLoft::CmdPartDesignAdditiveLoft()
    : Command("PartDesign_AdditiveLoft")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Additive Loft");
    sToolTipText = QT_TR_NOOP(
        "Lofts the selected sketch or profile through one or more sections and adds it to the body"
    );
    sWhatsThis = "PartDesign_AdditiveLoft";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_AdditiveLoft";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignAdditiveLoft::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd](Part::Feature* sketch, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        // specific parameters for pipe
        Gui::Command::updateActive();
        openAsOnshape(Feat, /*recompute = */ false);  // ops#640, round 3

        finishProfileBased(cmd, sketch, Feat);
    };

    prepareProfileBased(pcActiveBody, this, "AdditiveLoft", worker);
}

bool CmdPartDesignAdditiveLoft::isActive()
{
    return hasActiveDocument();
}


//===========================================================================
// PartDesign_SubtractiveLoft
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignSubtractiveLoft)

CmdPartDesignSubtractiveLoft::CmdPartDesignSubtractiveLoft()
    : Command("PartDesign_SubtractiveLoft")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Subtractive Loft");
    sToolTipText
        = QT_TR_NOOP("Lofts the selected sketch or profile through one or more sections and removes it from the body");
    sWhatsThis = "PartDesign_SubtractiveLoft";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_SubtractiveLoft";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignSubtractiveLoft::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd](Part::Feature* sketch, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        // specific parameters for pipe
        Gui::Command::updateActive();
        openAsOnshape(Feat, /*recompute = */ false);  // ops#640, round 3

        finishProfileBased(cmd, sketch, Feat);
    };

    prepareProfileBased(pcActiveBody, this, "SubtractiveLoft", worker);
}

bool CmdPartDesignSubtractiveLoft::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_AdditiveHelix
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignAdditiveHelix)

CmdPartDesignAdditiveHelix::CmdPartDesignAdditiveHelix()
    : Command("PartDesign_AdditiveHelix")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Additive Helix");
    sToolTipText = QT_TR_NOOP(
        "Sweeps the selected sketch or profile along a helix and adds it to the body"
    );
    sWhatsThis = "PartDesign_AdditiveHelix";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_AdditiveHelix";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignAdditiveHelix::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd, &pcActiveBody](Part::Feature* sketch, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        // Creating a helix with default values isn't always valid but fixes
        // itself when more values are set. So, this guard is used to suppress
        // errors before the user is able to change the parameters.
        Base::ObjectStatusLocker<App::Document::Status, App::Document> guard(
            App::Document::IgnoreErrorOnRecompute,
            Feat->getDocument(),
            true
        );

        // specific parameters for helix
        Gui::Command::updateActive();

        // a preselected axis is kept (FreeCAD-CH ops#640, rank 21); with no profile yet (its
        // dialog's Profile field armed) the axis is the origin's Y
        auto setAxis = dynamic_cast<App::PropertyLinkSub*>(Feat->getPropertyByName("ReferenceAxis"));
        if (setAxis && setAxis->getValue()) {
            // kept
        }
        else if (sketch && sketch->isDerivedFrom<Part::Part2DObject>()) {
            FCMD_OBJ_CMD(Feat, "ReferenceAxis = (" << getObjectCmd(sketch) << ",['V_Axis'])");
        }
        else {
            FCMD_OBJ_CMD(
                Feat,
                "ReferenceAxis = (" << getObjectCmd(pcActiveBody->getOrigin()->getY()) << ",[''])"
            );
        }
        openAsOnshape(Feat, /*recompute = */ true);  // ops#640, round 3

        finishProfileBased(cmd, sketch, Feat);

        // If the initial helix creation fails then it leaves the base object invisible which makes
        // things more difficult for the user. To avoid this the base object will be made tmp.
        // visible again.
        if (Feat->isError()) {
            App::DocumentObject* base = static_cast<PartDesign::Feature*>(Feat)->BaseFeature.getValue();
            if (base) {
                PartDesignGui::ViewProvider* view = dynamic_cast<PartDesignGui::ViewProvider*>(
                    Gui::Application::Instance->getViewProvider(base)
                );
                if (view) {
                    view->makeTemporaryVisible(true);
                }
            }
        }
    };

    prepareProfileBased(pcActiveBody, this, "AdditiveHelix", worker);
}

bool CmdPartDesignAdditiveHelix::isActive()
{
    return hasActiveDocument();
}


//===========================================================================
// PartDesign_SubtractiveHelix
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignSubtractiveHelix)

CmdPartDesignSubtractiveHelix::CmdPartDesignSubtractiveHelix()
    : Command("PartDesign_SubtractiveHelix")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Subtractive Helix");
    sToolTipText = QT_TR_NOOP(
        "Sweeps the selected sketch or profile along a helix and removes it from the body"
    );
    sWhatsThis = "PartDesign_SubtractiveHelix";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_SubtractiveHelix";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignSubtractiveHelix::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd, &pcActiveBody](Part::Feature* sketch, App::DocumentObject* Feat) {
        if (!Feat) {
            return;
        }

        // specific parameters for helix
        Gui::Command::updateActive();

        // a preselected axis is kept (FreeCAD-CH ops#640, rank 21); with no profile yet (its
        // dialog's Profile field armed) the axis is the origin's Y
        auto setAxis = dynamic_cast<App::PropertyLinkSub*>(Feat->getPropertyByName("ReferenceAxis"));
        if (setAxis && setAxis->getValue()) {
            // kept
        }
        else if (sketch && sketch->isDerivedFrom<Part::Part2DObject>()) {
            FCMD_OBJ_CMD(Feat, "ReferenceAxis = (" << getObjectCmd(sketch) << ",['V_Axis'])");
        }
        else {
            FCMD_OBJ_CMD(
                Feat,
                "ReferenceAxis = (" << getObjectCmd(pcActiveBody->getOrigin()->getY()) << ",[''])"
            );
        }
        openAsOnshape(Feat, /*recompute = */ true);  // ops#640, round 3

        finishProfileBased(cmd, sketch, Feat);
    };

    prepareProfileBased(pcActiveBody, this, "SubtractiveHelix", worker);
}

bool CmdPartDesignSubtractiveHelix::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// Common utility functions for Dressup features
//===========================================================================

// What a dress-up command takes of one part (FreeCAD-CH ops#640, rank 14): the feature whose
// shape was picked, its picked elements, and whether they are all its edges (the whole part)
struct DressUpPick
{
    Part::Feature* base = nullptr;
    std::vector<std::string> subs;
    bool useAllEdges = false;
};

/** The dress-up's picks, one per part. FreeCAD-CH (ops#640, rank 14; ops#634 slice 4): the picks
 * may be on any part of the active part's studio, the active Body or not ("Selection is not in the
 * active body" goes), as Onshape's Fillet takes edges of any part and rounds each owner; each part
 * gets its own dress-up. A part picked whole (the Body, or its feature with no element) stands for
 * all its edges (Fillet, Chamfer). Picks of two studios are refused, as before. With nothing
 * selected \a noSelection is set and \a picks is empty, with no question for an active Body
 * (ops#640 rank 14): the dialog's first pick decides the part (toolFirstBody()).
 */
bool dressupGetSelected(
    Gui::Command* cmd,
    const std::string& which,
    std::vector<DressUpPick>& picks,
    bool& noSelection,
    Part::Feature** wholePart = nullptr
)
{
    std::vector<Gui::SelectionObject> selection = cmd->getSelection().getSelectionEx();

    if (selection.empty()) {
        noSelection = true;
        return true;
    }

    const bool allEdgesIfWhole = which == "Fillet" || which == "Chamfer";
    PartDesign::Body* firstOwner = nullptr;
    for (auto& it : selection) {
        App::DocumentObject* obj = it.getObject();
        if (!obj) {
            continue;
        }
        // a Body picked whole stands for its Tip, whose shape it shows
        PartDesign::Body* owner = freecad_cast<PartDesign::Body*>(obj);
        if (owner) {
            obj = owner->Tip.getValue();
        }
        else {
            owner = PartDesign::Body::findBodyOf(obj);
        }
        auto base = freecad_cast<Part::Feature*>(obj);
        if (!owner || !base) {
            QMessageBox::warning(
                Gui::getMainWindow(),
                QObject::tr("Wrong object type"),
                QObject::tr("%1 works only on parts.").arg(QString::fromStdString(which))
            );
            return false;
        }
        if (!firstOwner) {
            firstOwner = owner;
        }
        else if (owner != firstOwner && !PartDesignGui::isStudioSelection(firstOwner, base)) {
            QMessageBox::warning(
                Gui::getMainWindow(),
                QObject::tr("Wrong selection"),
                QObject::tr("Select edges, faces or parts of one part studio.")
            );
            return false;
        }

        const Part::TopoShape& shape = base->Shape.getShape();
        if (shape.getShape().IsNull()) {
            QMessageBox::warning(
                Gui::getMainWindow(),
                QObject::tr("Wrong selection"),
                QObject::tr("Shape of the selected part is empty")
            );
            return false;
        }

        auto group = std::ranges::find_if(picks, [owner](const DressUpPick& pick) {
            return PartDesign::Body::findBodyOf(pick.base) == owner;
        });
        if (group != picks.end() && group->base != base) {
            QMessageBox::warning(
                Gui::getMainWindow(),
                QObject::tr("Wrong selection"),
                QObject::tr("Select an edge, face, or body from a single body.")
            );
            return false;
        }
        if (group == picks.end()) {
            picks.push_back(DressUpPick {base, {}, false});
            group = picks.end() - 1;
        }

        const std::vector<std::string>& subs = it.getSubNames();
        if (subs.empty() || freecad_cast<PartDesign::Body*>(it.getObject())) {
            // the part whole: Fillet and Chamfer take no edges from it (selection parity P6,
            // oracle 8 SQ12: a part preselected leaves Onshape's Fillet field empty), they open
            // empty on it; Draft and Thickness as before
            if (allEdgesIfWhole && wholePart && !*wholePart) {
                *wholePart = base;
            }
            continue;
        }
        if (!group->useAllEdges) {
            for (const auto& sub : subs) {
                if (std::ranges::find(group->subs, sub) == group->subs.end()) {
                    group->subs.push_back(sub);
                }
            }
        }
    }
    if (allEdgesIfWhole) {
        // a part picked whole stands for nothing; the element picks stay
        std::erase_if(picks, [](const DressUpPick& pick) { return pick.subs.empty(); });
        if (picks.empty() && wholePart && *wholePart) {
            Gui::Selection().clearSelection();
            noSelection = true;
            return true;
        }
    }
    if (picks.empty()) {
        return false;
    }

    Gui::Selection().clearSelection();
    return true;
}

// The picks a dress-up doesn't take, named in the status bar: they are left out (ops#252).
// `which` is marked QT_TRANSLATE_NOOP("QObject", ...): it is translated here, in that context
static void reportDroppedPicks(const char* which, const QString& takes, const std::vector<std::string>& dropped)
{
    if (dropped.empty()) {
        return;
    }
    QStringList names;
    for (const auto& sub : dropped) {
        names << (sub.empty() ? QObject::tr("the whole object") : QString::fromStdString(sub));
    }
    Gui::getMainWindow()->showMessage(
        QObject::tr("%1 takes %2 only; left out of the selection: %3")
            .arg(QObject::tr(which), takes, names.join(QStringLiteral(", "))),
        10000
    );
}

// The parameters a dress-up made on another part follows from the first, by expression
// (FreeCAD-CH ops#640, rank 14): one dialog sets them for every part, as Onshape's one feature
// has one setting for all its parts: the sizes, and the types and toggles too (an enumeration or
// a bool follows by its index or value). Not UseAllEdges: each part's edges are its own
static std::vector<const char*> followedParameters(const std::string& which)
{
    if (which == "Fillet") {
        return {"Radius"};
    }
    if (which == "Chamfer") {
        return {"ChamferType", "Size", "Size2", "Angle", "FlipDirection"};
    }
    if (which == "Draft") {
        return {"Angle", "Reversed"};
    }
    if (which == "Thickness") {
        return {"Value", "Reversed", "Mode", "Join", "Intersection"};
    }
    return {};
}

// Makes the dress-up `which` on `base` in its Body, in the open transaction; its name
static std::string makeDressUp(
    Gui::Command* cmd,
    const std::string& which,
    Part::Feature* base,
    const std::vector<std::string>& SubNames,
    const bool useAllEdges,
    PartDesign::Body* body
)
{
    std::ostringstream str;
    str << '(' << Gui::Command::getObjectCmd(base) << ",[";
    for (const auto& SubName : SubNames) {
        str << "'" << SubName << "',";
    }
    str << "])";

    std::string FeatName = cmd->getUniqueObjectName(which.c_str(), base);
    FCMD_OBJ_CMD(body, "newObject('PartDesign::" << which << "','" << FeatName << "')");
    auto Feat = body->getDocument()->getObject(FeatName.c_str());
    if (!Feat) {
        return {};
    }
    FCMD_OBJ_CMD(Feat, "Base = " << str.str());
    if (useAllEdges && (which.compare("Fillet") == 0 || which.compare("Chamfer") == 0)) {
        FCMD_OBJ_CMD(Feat, "UseAllEdges = True");
    }
    return FeatName;
}

void finishDressupFeature(
    Gui::Command* cmd,
    const std::string& which,
    Part::Feature* base,
    const std::vector<std::string>& SubNames,
    const bool useAllEdges,
    const bool updateDocument = true,
    const std::vector<DressUpPick>& otherParts = {},
    const bool placedByFirstPick = false,
    // FreeCAD-CH (ops#655 T8): sets the new dress-up's parameters, in its transaction, before its
    // dialog opens (the face patterns' defaults)
    const std::function<void(App::DocumentObject*)>& setDefaults = {}
)
{
    auto body = PartDesignGui::getBodyFor(base, false);
    if (!body) {
        return;
    }
    cmd->openCommand(std::string("Make ") + which);
    const std::string FeatName = makeDressUp(cmd, which, base, SubNames, useAllEdges, body);
    auto Feat = body->getDocument()->getObject(FeatName.c_str());
    if (!Feat) {
        cmd->abortCommand();
        return;
    }
    if (setDefaults) {
        setDefaults(Feat);
    }
    // FreeCAD-CH (ops#640 rank 14): made with nothing selected, its dialog's first pick decides
    // its part (the dialog opens in finishFeature below)
    if (placedByFirstPick) {
        PartDesignGui::TaskDressUpParameters::notePlacedByFirstPick(Feat);
    }
    // FreeCAD-CH (ops#640, rank 14): the other parts' picks make a dress-up in each of their
    // Bodies, in this transaction (Cancel takes them too), its parameters following this one's
    for (const DressUpPick& other : otherParts) {
        auto otherBody = PartDesign::Body::findBodyOf(other.base);
        if (!otherBody || otherBody == body) {
            continue;
        }
        const std::string otherName
            = makeDressUp(cmd, which, other.base, other.subs, other.useAllEdges, otherBody);
        auto otherFeat = otherBody->getDocument()->getObject(otherName.c_str());
        if (!otherFeat) {
            continue;
        }
        for (const char* parameter : followedParameters(which)) {
            FCMD_OBJ_CMD(
                otherFeat,
                "setExpression('" << parameter << "', '" << FeatName << "." << parameter << "')"
            );
        }
        // ops#701 (F2b): its failure is a warning while the first part's builds
        FCMD_OBJ_CMD(otherFeat, "MultiPartPrimary = " << Gui::Command::getObjectCmd(Feat));
        FCMD_OBJ_HIDE(other.base);
        cmd->copyVisual(otherFeat, "ShapeAppearance", other.base);
        cmd->copyVisual(otherFeat, "LineColor", other.base);
        cmd->copyVisual(otherFeat, "PointColor", other.base);
        cmd->copyVisual(otherFeat, "Transparency", other.base);
        cmd->copyVisual(otherFeat, "DisplayMode", other.base);
    }
    Gui::Command::doCommand(cmd->Gui, "Gui.Selection.clearSelection()");
    finishFeature(cmd, Feat, base, /* hidePreviousSolid = */ true, updateDocument);

    App::DocumentObject* baseFeature = static_cast<PartDesign::DressUp*>(Feat)->Base.getValue();
    if (baseFeature) {
        PartDesignGui::ViewProvider* view = dynamic_cast<PartDesignGui::ViewProvider*>(
            Gui::Application::Instance->getViewProvider(baseFeature)
        );
        // in case there is an error, for example when a fillet is larger than the available space
        // display the base feature to avoid that the user sees nothing
        if (view && Feat->isError()) {
            view->Visibility.setValue(true);
        }
    }
}

// The Body a dress-up made with nothing selected starts in (FreeCAD-CH ops#640 rank 14): the
// active Body, else the first one with a solid, with no question for an active Body. Onshape's
// Fillet opens with no part at all; here the dress-up waits in this Body for its dialog's first
// pick, which moves it to the picked part (TaskDressUpParameters::notePlacedByFirstPick)
static PartDesign::Body* toolFirstBody()
{
    auto hasSolid = [](const PartDesign::Body* body) {
        auto tip = body ? freecad_cast<Part::Feature*>(body->Tip.getValue()) : nullptr;
        return tip && !tip->Shape.getShape().isNull();
    };
    // An active Body with no solid yet (new, or a sketch only) gives way to a part that has one
    if (PartDesign::Body* active = PartDesignGui::getBody(/*messageIfNot = */ false);
        hasSolid(active)) {
        return active;
    }
    App::Document* doc = App::GetApplication().getActiveDocument();
    if (!doc) {
        return nullptr;
    }
    for (PartDesign::Body* body : doc->getObjectsOfType<PartDesign::Body>()) {
        if (hasSolid(body)) {
            return body;
        }
    }
    return nullptr;
}

/// FreeCAD-CH (ops#654 P8a-2, parts-design.md 10.14): Fillet or Chamfer in a studio that has a
/// list makes one studio feature, outside every Body, whose picks are on any of its parts: the
/// owner, its list entry, a step in each picked part and its first recompute in one step, which
/// Cancel aborts whole. The dialog takes more picks of any part. False: no list (the per-Body path,
/// until R0), an assembly, or no studio
static bool makeStudioDressUp(
    Gui::Command* cmd,
    const std::string& which,
    const std::vector<DressUpPick>& picks
)
{
    App::Document* doc = cmd->getDocument();
    PartDesign::Body* body = picks.empty() ? PartDesignGui::getBody(/*messageIfNot = */ false)
                                           : PartDesign::Body::findBodyOf(picks.front().base);
    App::Part* studio = nullptr;
    if (body) {
        if (!Part::BodyBase::studioOf(body, studio)) {
            return false;
        }
    }
    else {
        studio = PartDesignGui::getActivePart();
    }
    if (!doc || isAssemblyStudio(studio) || !PartDesign::StudioList::of(doc, studio, false)) {
        return false;
    }
    const std::string name = cmd->getUniqueObjectName(which.c_str());
    cmd->openCommand(std::string("Make ") + which);
    try {
        makeStudioList(doc, studio);
        Gui::cmdAppDocument(
            doc,
            std::ostringstream() << "addObject('PartDesign::" << which << "','" << name << "')"
        );
        App::DocumentObject* owner = doc->getObject(name.c_str());
        if (!owner) {
            throw Base::RuntimeError("The studio feature was not made");
        }
        const std::string ownerCmd = Gui::Command::getObjectCmd(owner);
        if (studio) {
            Gui::cmdAppObject(studio, std::ostringstream() << "addObject(" << ownerCmd << ")");
        }
        std::ostringstream ids;
        for (const DressUpPick& pick : picks) {
            for (const auto& sub : pick.subs) {
                ids << "PartDesign.studioPickId(" << Gui::Command::getObjectCmd(pick.base) << ", '"
                    << Data::oldElementName(sub.c_str()) << "'),";
            }
        }
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "%s.StudioPickIds = [%s]",
            ownerCmd.c_str(),
            ids.str().c_str()
        );
        Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.studioInsert(%s, -1)", ownerCmd.c_str());
        {
            // No picks yet: the dialog asks for them; its error isn't printed meanwhile
            Base::ObjectStatusLocker<App::Document::Status, App::Document> guard(
                App::Document::IgnoreErrorOnRecompute,
                doc,
                picks.empty()
            );
            Gui::cmdAppDocument(doc, "recompute()");
        }
        PartDesignGui::TaskDlgFeatureParameters::noteCreated(owner);
        if (!PartDesignGui::setEdit(owner)) {
            throw Base::RuntimeError("The studio feature's dialog didn't open");
        }
        cmd->doCommand(cmd->Gui, "Gui.Selection.clearSelection()");
    }
    catch (const Base::Exception& e) {
        cmd->abortCommand();
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 10000);
        Base::Console().error("%s\n", e.what());
    }
    return true;
}

// Makes `which` on the picks: the first part's dress-up opens its dialog, the others follow it
// (FreeCAD-CH ops#640, rank 14). `filter` drops the elements the dress-up doesn't take, into
// `dropped`; a part left with nothing makes no dress-up
static void makeDressUps(
    Gui::Command* cmd,
    const std::string& which,
    const std::function<void(DressUpPick&, std::vector<std::string>&)>& filter,
    std::vector<std::string>& dropped
)
{
    std::vector<DressUpPick> picks;
    bool noSelection = false;
    Part::Feature* wholePart = nullptr;
    if (!dressupGetSelected(cmd, which, picks, noSelection, &wholePart)) {
        return;
    }
    if ((which == "Fillet" || which == "Chamfer") && makeStudioDressUp(cmd, which, picks)) {
        return;
    }
    if (noSelection) {
        // a part picked whole opens the dialog empty on that part (selection parity P6)
        PartDesign::Body* body = wholePart ? nullptr : toolFirstBody();
        auto base = wholePart ? wholePart
                              : (body ? freecad_cast<Part::Feature*>(body->Tip.getValue()) : nullptr);
        if (!base) {
            Gui::getMainWindow()->showMessage(
                QObject::tr("%1 needs a part with a solid").arg(QObject::tr(which.c_str())),
                10000
            );
            return;
        }
        // Fillet and Chamfer: nothing to recompute before the dialog (as before)
        const bool chamferOrFillet = which == "Fillet" || which == "Chamfer";
        finishDressupFeature(cmd, which, base, {}, false, !chamferOrFillet, {}, true);
        return;
    }
    if (filter) {
        for (auto& pick : picks) {
            filter(pick, dropped);
        }
        // a part whose picks all went makes no dress-up, unless it is the only one
        if (picks.size() > 1) {
            std::erase_if(picks, [](const DressUpPick& pick) { return pick.subs.empty(); });
            if (picks.empty()) {
                return;
            }
        }
    }
    const DressUpPick first = picks.front();
    const std::vector<DressUpPick> others(picks.begin() + 1, picks.end());
    finishDressupFeature(cmd, which, first.base, first.subs, first.useAllEdges, true, others);
}

void makeChamferOrFillet(Gui::Command* cmd, const std::string& which)
{
    std::vector<std::string> dropped;
    makeDressUps(cmd, which, nullptr, dropped);
}

//===========================================================================
// PartDesign_Fillet
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignFillet)

CmdPartDesignFillet::CmdPartDesignFillet()
    : Command("PartDesign_Fillet")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Fillet");
    sToolTipText = QT_TR_NOOP("Applies a fillet to the selected edges or faces");
    sWhatsThis = "PartDesign_Fillet";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Fillet";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignFillet::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    makeChamferOrFillet(this, "Fillet");
}

bool CmdPartDesignFillet::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_Chamfer
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignChamfer)

CmdPartDesignChamfer::CmdPartDesignChamfer()
    : Command("PartDesign_Chamfer")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Chamfer");
    sToolTipText = QT_TR_NOOP("Applies a chamfer to the selected edges or faces");
    sWhatsThis = "PartDesign_Chamfer";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Chamfer";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignChamfer::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    makeChamferOrFillet(this, "Chamfer");
    doCommand(Gui, "Gui.Selection.clearSelection()");
}

bool CmdPartDesignChamfer::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_Defeaturing
//===========================================================================

static void makeDefeaturing(Gui::Command* cmd)
{
    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);
    if (!pcActiveBody) {
        return;
    }

    std::vector<Gui::SelectionObject> selection = cmd->getSelection().getSelectionEx();

    if (selection.empty()) {
        auto* base = static_cast<Part::Feature*>(pcActiveBody->Tip.getValue());
        finishDressupFeature(cmd, "Defeaturing", base, {}, false);
        return;
    }

    if (selection.size() != 1) {
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Wrong Selection"),
            QObject::tr("Select faces from a single body")
        );
        return;
    }
    if (pcActiveBody != PartDesignGui::getBodyFor(selection[0].getObject(), false)) {
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Selection Outside Active Body"),
            QObject::tr("Select faces from the active body")
        );
        return;
    }

    if (!selection[0].isObjectTypeOf(Part::Feature::getClassTypeId())) {
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Wrong Object Type"),
            QObject::tr("Defeaturing works only on faces")
        );
        return;
    }

    std::vector<std::string> subNames = selection[0].getSubNames();
    for (const auto& name : subNames) {
        if (name.substr(0, 4) != "Face") {
            QMessageBox::warning(
                Gui::getMainWindow(),
                QObject::tr("Wrong Selection"),
                QObject::tr("Defeaturing works only on faces")
            );
            return;
        }
    }

    Gui::Selection().clearSelection();

    auto* base = static_cast<Part::Feature*>(selection[0].getObject());
    finishDressupFeature(cmd, "Defeaturing", base, subNames, false);
}

DEF_STD_CMD_A(CmdPartDesignDefeaturing)

CmdPartDesignDefeaturing::CmdPartDesignDefeaturing()
    : Command("PartDesign_Defeaturing")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Defeaturing");
    sToolTipText = QT_TR_NOOP("Removes selected faces from a solid");
    sWhatsThis = "PartDesign_Defeaturing";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Defeaturing";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignDefeaturing::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    makeDefeaturing(this);
}

bool CmdPartDesignDefeaturing::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_FaceLinearPattern, PartDesign_FacePolarPattern, PartDesign_FaceMirrored
//===========================================================================

// FreeCAD-CH (ops#655 T8): a face pattern of `which` on the faces selected on the active Body's
// solid, or on none (its dialog takes them). Like makeDefeaturing; the defaults are Onshape's
static void makeFacePattern(Gui::Command* cmd, const std::string& which)
{
    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);
    if (!pcActiveBody) {
        return;
    }

    auto setDefaults = [which, pcActiveBody](App::DocumentObject* Feat) {
        App::Origin* origin = pcActiveBody->getOrigin();
        if (which == "FaceLinearPattern") {
            FCMD_OBJ_CMD(
                Feat,
                "Direction = (" << Gui::Command::getObjectCmd(origin->getX()) << ",[''])"
            );
            // Distance is the spacing between neighbouring instances; count 2
            FCMD_OBJ_CMD(Feat, "Mode = 'Spacing'");
            FCMD_OBJ_CMD(Feat, "Offset = 20");
            FCMD_OBJ_CMD(Feat, "Occurrences = 2");
            // The second direction has Onshape's own, as the linear pattern's (ops#655): a spacing
            // of 25, count 1 (its box unticked), so a count of 2 puts the row 25 away
            FCMD_OBJ_CMD(Feat, "Mode2 = 'Spacing'");
            FCMD_OBJ_CMD(Feat, "Offset2 = 25");
        }
        else if (which == "FacePolarPattern") {
            FCMD_OBJ_CMD(
                Feat,
                "Axis = (" << Gui::Command::getObjectCmd(origin->getZ()) << ",[''])"
            );
            FCMD_OBJ_CMD(Feat, "Mode = 'Extent'");
            FCMD_OBJ_CMD(Feat, "Angle = 360");
            FCMD_OBJ_CMD(Feat, "Occurrences = 4");
        }
        else {
            FCMD_OBJ_CMD(
                Feat,
                "MirrorPlane = (" << Gui::Command::getObjectCmd(origin->getYZ()) << ",[''])"
            );
        }
    };

    std::vector<Gui::SelectionObject> selection = cmd->getSelection().getSelectionEx();

    if (selection.empty()) {
        auto* base = static_cast<Part::Feature*>(pcActiveBody->Tip.getValue());
        finishDressupFeature(cmd, which, base, {}, false, true, {}, false, setDefaults);
        return;
    }

    if (selection.size() != 1) {
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Wrong Selection"),
            QObject::tr("Select faces from a single body")
        );
        return;
    }
    if (pcActiveBody != PartDesignGui::getBodyFor(selection[0].getObject(), false)) {
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Selection Outside Active Body"),
            QObject::tr("Select faces from the active body")
        );
        return;
    }
    if (!selection[0].isObjectTypeOf(Part::Feature::getClassTypeId())) {
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Wrong Object Type"),
            QObject::tr("Face patterns work only on faces")
        );
        return;
    }

    std::vector<std::string> subNames = selection[0].getSubNames();
    for (const auto& name : subNames) {
        if (name.substr(0, 4) != "Face") {
            QMessageBox::warning(
                Gui::getMainWindow(),
                QObject::tr("Wrong Selection"),
                QObject::tr("Face patterns work only on faces")
            );
            return;
        }
    }

    Gui::Selection().clearSelection();

    auto* base = static_cast<Part::Feature*>(selection[0].getObject());
    finishDressupFeature(cmd, which, base, subNames, false, true, {}, false, setDefaults);
}

DEF_STD_CMD_A(CmdPartDesignFaceLinearPattern)

CmdPartDesignFaceLinearPattern::CmdPartDesignFaceLinearPattern()
    : Command("PartDesign_FaceLinearPattern")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Face Linear Pattern");
    sToolTipText = QT_TR_NOOP(
        "Patterns the selected faces (a boss, pocket or hole) of the part in a linear pattern"
    );
    sWhatsThis = "PartDesign_FaceLinearPattern";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_LinearPattern";
    eType |= AcceptsOpenDialog;
}

void CmdPartDesignFaceLinearPattern::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    makeFacePattern(this, "FaceLinearPattern");
}

bool CmdPartDesignFaceLinearPattern::isActive()
{
    return hasActiveDocument();
}

DEF_STD_CMD_A(CmdPartDesignFacePolarPattern)

CmdPartDesignFacePolarPattern::CmdPartDesignFacePolarPattern()
    : Command("PartDesign_FacePolarPattern")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Face Polar Pattern");
    sToolTipText = QT_TR_NOOP(
        "Patterns the selected faces (a boss, pocket or hole) of the part around an axis"
    );
    sWhatsThis = "PartDesign_FacePolarPattern";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_PolarPattern";
    eType |= AcceptsOpenDialog;
}

void CmdPartDesignFacePolarPattern::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    makeFacePattern(this, "FacePolarPattern");
}

bool CmdPartDesignFacePolarPattern::isActive()
{
    return hasActiveDocument();
}

DEF_STD_CMD_A(CmdPartDesignFaceMirrored)

CmdPartDesignFaceMirrored::CmdPartDesignFaceMirrored()
    : Command("PartDesign_FaceMirrored")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Face Mirror");
    sToolTipText = QT_TR_NOOP(
        "Mirrors the selected faces (a boss, pocket or hole) of the part in a plane"
    );
    sWhatsThis = "PartDesign_FaceMirrored";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Mirrored";
    eType |= AcceptsOpenDialog;
}

void CmdPartDesignFaceMirrored::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    makeFacePattern(this, "FaceMirrored");
}

bool CmdPartDesignFaceMirrored::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_Draft
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignDraft)

CmdPartDesignDraft::CmdPartDesignDraft()
    : Command("PartDesign_Draft")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Draft");
    sToolTipText = QT_TR_NOOP("Applies a draft to the selected faces");
    sWhatsThis = "PartDesign_Draft";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Draft";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignDraft::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    std::vector<std::string> dropped;
    // Draft takes the faces of one part (its neutral plane and pull direction are the part's):
    // another part's picks are left out and said (FreeCAD-CH ops#640, rank 14)
    const Part::Feature* firstBase = nullptr;
    auto filter = [&firstBase](DressUpPick& pick, std::vector<std::string>& out) {
        if (!firstBase) {
            firstBase = pick.base;
        }
        else if (pick.base != firstBase) {
            for (const auto& sub : pick.subs) {
                out.push_back(std::string(pick.base->Label.getValue()) + "." + sub);
            }
            pick.subs.clear();
            return;
        }
        const Part::TopoShape& TopShape = pick.base->Shape.getShape();

        // filter out the edges, each one (the erase in the loop skipped the pick after it,
        // ops#252)
        std::erase_if(pick.subs, [&](const std::string& aSubName) {
            bool keep = false;
            if (aSubName.compare(0, 4, "Face") == 0) {
                // Check for valid face types
                TopoDS_Face face = TopoDS::Face(TopShape.getSubShape(aSubName.c_str()));
                BRepAdaptor_Surface sf(face);
                keep = sf.GetType() == GeomAbs_Plane || sf.GetType() == GeomAbs_Cylinder
                    || sf.GetType() == GeomAbs_Cone;
            }
            if (!keep) {
                out.push_back(aSubName);
            }
            return !keep;
        });
    };
    makeDressUps(this, "Draft", filter, dropped);
    // after the panel opens, which would replace the message
    reportDroppedPicks(
        QT_TRANSLATE_NOOP("QObject", "Draft"),
        QObject::tr("planar, cylindrical and conical faces of one part"),
        dropped
    );
}

bool CmdPartDesignDraft::isActive()
{
    return hasActiveDocument();
}


//===========================================================================
// PartDesign_Thickness
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignThickness)

CmdPartDesignThickness::CmdPartDesignThickness()
    : Command("PartDesign_Thickness")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Shell");  // FreeCAD-CH (ops#605): Onshape's word
    sToolTipText = QT_TR_NOOP("Shells the body: applies thickness and removes the selected faces");
    sWhatsThis = "PartDesign_Thickness";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Thickness";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignThickness::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    std::vector<std::string> dropped;
    // filter out the edges, each one (ops#252, as Draft); each part picked gets its Shell
    // (FreeCAD-CH ops#640, rank 14)
    auto filter = [](DressUpPick& pick, std::vector<std::string>& out) {
        std::erase_if(pick.subs, [&out](const std::string& aSubName) {
            const bool keep = aSubName.compare(0, 4, "Face") == 0;
            if (!keep) {
                out.push_back(aSubName);
            }
            return !keep;
        });
    };
    makeDressUps(this, "Thickness", filter, dropped);
    reportDroppedPicks(QT_TRANSLATE_NOOP("QObject", "Thickness"), QObject::tr("faces"), dropped);
}

bool CmdPartDesignThickness::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// Common functions for all Transformed features
//===========================================================================

void prepareTransformed(
    PartDesign::Body* pcActiveBody,
    Gui::Command* cmd,
    const std::string& which,
    std::function<void(App::DocumentObject*, std::vector<App::DocumentObject*>)> func
)
{
    std::string FeatName = cmd->getUniqueObjectName(which.c_str(), pcActiveBody);
    // FreeCAD-CH (ops#640, rank 13): Mirror and the patterns with nothing selected stay in
    // Features mode, their Features field armed for the first pick, as Onshape's open; Scale and
    // Multi-Transform still transform the whole shape. The curve pattern (ops#655 T6) waits too
    const bool waitsForFeatures = which == "Mirrored" || which == "LinearPattern"
        || which == "PolarPattern" || which == "CurvePattern";

    // FreeCAD-CH ops#654: the studio's list is made on first use, before the pattern (adopted
    // with the Body's members, then the pattern inserted at its bar)
    App::Part* studio = nullptr;
    const bool inStudio = Part::BodyBase::studioOf(pcActiveBody, studio)
        && takesStudioPath(pcActiveBody->getDocument(), studio);
    if (inStudio && refuseStudioList(pcActiveBody->getDocument(), studio)) {
        return;
    }

    auto worker = [=](std::vector<App::DocumentObject*> features) {
        std::string msg("Make ");
        msg += which;
        cmd->openCommand(msg.c_str());
        if (inStudio) {
            makeStudioList(pcActiveBody->getDocument(), studio);
        }
        // The solid it follows, before it is inserted (a transform without originals isn't a
        // solid feature, so the Tip stays there until it is set below)
        auto previous = freecad_cast<Part::Feature*>(pcActiveBody->Tip.getValue());
        FCMD_OBJ_CMD(pcActiveBody, "newObject('PartDesign::" << which << "','" << FeatName << "')");
        // FIXME: There seems to be kind of a race condition here, leading to sporadic errors like
        // Exception (Thu Sep  6 11:52:01 2012): 'App.Document' object has no attribute 'Mirrored'
        Gui::Command::updateActive();  // Helps to ensure that the object already exists when the
                                       // next command comes up

        auto Feat = pcActiveBody->getDocument()->getObject(FeatName.c_str());

        // FreeCAD-CH ops#654 slice 8: in a listed studio the pattern is a member of the list, at
        // its bar, as every Body member is
        if (Feat && inStudio && PartDesign::StudioList::of(Feat->getDocument(), studio, false)) {
            Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.studioInsert(%s, -1)",
                Gui::Command::getObjectCmd(Feat).c_str()
            );
        }

        if (features.empty() && waitsForFeatures) {
            // Nothing to transform yet: it shows the solid before it (a transform without
            // originals keeps its shape, as Multi-Transform's start does) until the pick
            if (previous && previous != Feat) {
                FCMD_OBJ_CMD(Feat, "Shape = " << Gui::Command::getObjectCmd(previous) << ".Shape");
            }
        }
        else if (features.empty()) {
            FCMD_OBJ_CMD(Feat, "TransformMode = \"Whole shape\"");
        }
        else {
            std::stringstream str;
            str << "Originals = [";
            for (auto feature : features) {
                str << cmd->getObjectCmd(feature) << ",";
            }
            str << "]";
            FCMD_OBJ_CMD(Feat, str.str().c_str());
        }

        // TODO What is this function supposed to do? (2015-08-05, Fat-Zer)
        func(Feat, features);

        // Set the tip of the body
        FCMD_OBJ_CMD(pcActiveBody, "Tip = " << Gui::Command::getObjectCmd(Feat));
        Gui::Command::updateActive();
    };

    // Get a valid original from the user
    std::vector<App::DocumentObject*> features = cmd->getSelection().getObjectsOfType(
        PartDesign::Feature::getClassTypeId()
    );

    // Say which picks the transform leaves out, once its panel is open (ops#252: a sketch alone
    // made a "Whole shape" transform without a word). FreeCAD-CH (ops#640, rank 13): a feature
    // of another body is left out too, said in the Features field's status: it was a modal
    PartDesign::Body* activeBody = PartDesignGui::getBody(true);
    // FreeCAD-CH ops#654 slice 8: a studio feature (a Features-list row) with a step in the
    // active Body is taken: its step is copied
    auto takes = [activeBody](const App::DocumentObject* obj) {
        if (PartDesign::isStudioOwner(obj)) {
            return PartDesign::StudioList::stepOf(obj, activeBody) != nullptr;
        }
        return obj->isDerivedFrom<PartDesign::Feature>()
            && activeBody == PartDesignGui::getBodyFor(obj, false);
    };
    QStringList dropped;
    for (const auto& sel : cmd->getSelection().getSelectionEx()) {
        const App::DocumentObject* obj = sel.getObject();
        if (obj && !takes(obj)) {
            dropped << QStringLiteral("'%1'").arg(QString::fromUtf8(obj->Label.getValue()));
        }
    }
    std::erase_if(features, [&takes](App::DocumentObject* feature) { return !takes(feature); });

    worker(features);

    if (!dropped.isEmpty()) {
        const QString list = dropped.join(QStringLiteral(", "));
        noteLeftOut(
            "Originals",
            features.empty() && !waitsForFeatures
                ? QObject::tr("A transform takes features of the active body; left out of the "
                              "selection: %1. It transforms the whole shape instead.")
                      .arg(list)
                : QObject::tr("A transform takes features of the active body; left out of the "
                              "selection: %1.")
                      .arg(list)
        );
    }
}

void finishTransformed(Gui::Command* cmd, App::DocumentObject* Feat)
{
    finishFeature(cmd, Feat);
}

//===========================================================================
// PartDesign_Mirrored
//===========================================================================

/** FreeCAD-CH (ops#654 slice 9): Mirror in a studio with a list makes a part mirror (Onshape's
 * Mirror, Part type) when no feature is picked and either no Body is active or a part is picked
 * (whole, or by a face of it: its part is the part to mirror). It is a studio feature, in one step
 * with its list entry, its New part and its first recompute (Cancel aborts all of it): the part's
 * id in StudioEntities, Operation Union (the Result row's words, New with the part it makes), the
 * plane picked in its dialog. False: today's path */
static bool prepareStudioPartMirror(Gui::Command* cmd)
{
    App::Document* doc = cmd->getDocument();
    if (!doc) {
        return false;
    }
    PartDesign::Body* source = nullptr;
    for (const auto& sel : cmd->getSelection().getSelectionEx()) {
        auto obj = const_cast<App::DocumentObject*>(sel.getObject());
        if (!obj || obj->getDocument() != doc) {
            continue;
        }
        if (auto body = freecad_cast<PartDesign::Body*>(obj)) {
            source = body;
            continue;
        }
        auto body = PartDesign::Body::findBodyOf(obj);
        const auto& subs = sel.getSubNames();
        const bool element = std::ranges::any_of(subs, [](const std::string& sub) {
            return !sub.empty();
        });
        if (!body || !element || !obj->isDerivedFrom<PartDesign::Feature>()) {
            return false;  // a feature (or anything else) picked: today's feature mirror
        }
        source = body;
    }
    App::Part* studio = nullptr;
    if (source) {
        if (!Part::BodyBase::studioOf(source, studio)) {
            return false;
        }
    }
    else if (PartDesignGui::getBody(/*messageIfNot = */ false)) {
        return false;  // a Body is active: today's mirror of its features
    }
    else {
        studio = PartDesignGui::getActivePart();
    }
    // FreeCAD-CH ops#654: the studio's list is made on first use, in this step
    if (isAssemblyStudio(studio) || !takesStudioPath(doc, studio)) {
        return false;
    }
    if (refuseStudioList(doc, studio)) {
        return true;
    }
    const std::string name = cmd->getUniqueObjectName("Mirrored");
    cmd->openCommand("Make Mirrored");
    try {
        makeStudioList(doc, studio);
        Gui::cmdAppDocument(
            doc,
            std::ostringstream() << "addObject('PartDesign::Mirrored','" << name << "')"
        );
        App::DocumentObject* owner = doc->getObject(name.c_str());
        if (!owner) {
            throw Base::RuntimeError("The part mirror was not made");
        }
        const std::string ownerCmd = Gui::Command::getObjectCmd(owner);
        if (studio) {
            Gui::cmdAppObject(studio, std::ostringstream() << "addObject(" << ownerCmd << ")");
        }
        FCMD_OBJ_CMD(owner, "PatternType = 'Part'");
        FCMD_OBJ_CMD(
            owner,
            "addProperty('App::PropertyEnumeration', 'Operation', 'Studio', 'The Result row: New "
            "or Add (Union), Remove (Subtraction), Intersect (Common)', 0, False, True)"
        );
        FCMD_OBJ_CMD(owner, "Operation = ['Union', 'Subtraction', 'Common']");
        FCMD_OBJ_CMD(owner, "Operation = 'Union'");
        if (source) {
            FCMD_OBJ_CMD(owner, "StudioEntities = ['" << PartDesign::studioPartId(source) << "']");
        }
        Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.studioInsert(%s, -1)", ownerCmd.c_str());
        // Onshape's part mirror makes a new part by default
        Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.studioNewPart(%s)", ownerCmd.c_str());
        {
            // No plane yet: its error isn't printed while the dialog opens asking for it
            Base::ObjectStatusLocker<App::Document::Status, App::Document> guard(
                App::Document::IgnoreErrorOnRecompute,
                doc,
                true
            );
            Gui::cmdAppDocument(doc, "recompute()");
        }
        PartDesignGui::TaskDlgFeatureParameters::noteCreated(owner);
        cmd->doCommand(cmd->Gui, "Gui.Selection.clearSelection()");
        if (!PartDesignGui::setEdit(owner)) {
            throw Base::RuntimeError("The part mirror's dialog didn't open");
        }
    }
    catch (const Base::Exception& e) {
        cmd->abortCommand();
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 10000);
        Base::Console().error("%s\n", e.what());
    }
    return true;
}

DEF_STD_CMD_A(CmdPartDesignMirrored)

CmdPartDesignMirrored::CmdPartDesignMirrored()
    : Command("PartDesign_Mirrored")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Mirror");
    sToolTipText = QT_TR_NOOP("Mirrors the selected features or active body");
    sWhatsThis = "PartDesign_Mirrored";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Mirrored";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignMirrored::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    if (prepareStudioPartMirror(this)) {
        return;
    }
    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd,
                   pcActiveBody](App::DocumentObject* Feat, std::vector<App::DocumentObject*> features) {
        bool direction = false;
        if (!features.empty() && features.front()->isDerivedFrom<PartDesign::ProfileBased>()
            && !PartDesign::isStudioOwner(features.front())) {
            Part::Part2DObject* sketch = (static_cast<PartDesign::ProfileBased*>(features.front()))
                                             ->getVerifiedSketch(/* silent =*/true);
            if (sketch) {
                FCMD_OBJ_CMD(Feat, "MirrorPlane = (" << getObjectCmd(sketch) << ", ['V_Axis'])");
                direction = true;
            }
        }
        if (!direction) {
            FCMD_OBJ_CMD(
                Feat,
                "MirrorPlane = (" << getObjectCmd(pcActiveBody->getOrigin()->getXY()) << ", [''])"
            );
        }

        finishTransformed(cmd, Feat);
    };

    prepareTransformed(pcActiveBody, this, "Mirrored", worker);
}

bool CmdPartDesignMirrored::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_LinearPattern
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignLinearPattern)

CmdPartDesignLinearPattern::CmdPartDesignLinearPattern()
    : Command("PartDesign_LinearPattern")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Linear pattern");  // FreeCAD-CH (ops#605): Onshape's word
    sToolTipText = QT_TR_NOOP(
        "Duplicates the selected features or the active body in a linear pattern"
    );
    sWhatsThis = "PartDesign_LinearPattern";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_LinearPattern";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignLinearPattern::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker =
        [cmd, pcActiveBody](App::DocumentObject* Feat, std::vector<App::DocumentObject*> features) {
            bool direction = false;
            if (!features.empty() && features.front()->isDerivedFrom<PartDesign::ProfileBased>()
            && !PartDesign::isStudioOwner(features.front())) {
                Part::Part2DObject* sketch = (static_cast<PartDesign::ProfileBased*>(features.front()))
                                                 ->getVerifiedSketch(/* silent =*/true);
                if (sketch) {
                    FCMD_OBJ_CMD(
                        Feat,
                        "Direction = (" << Gui::Command::getObjectCmd(sketch) << ", ['H_Axis'])"
                    );
                    direction = true;
                }
            }
            if (!direction) {
                FCMD_OBJ_CMD(
                    Feat,
                    "Direction = (" << Gui::Command::getObjectCmd(pcActiveBody->getOrigin()->getX())
                                    << ",[''])"
                );
            }
            // Onshape's defaults (ops#640 rank 8, B3-6): Distance is the spacing between
            // neighbouring instances, so a count change keeps it; count 2; Centered and Skip off
            // (the properties' defaults). The second direction has Onshape's own: an empty
            // Direction (Onshape doesn't fill it), a spacing of 25, count 1 (its box unticked),
            // so a count of 2 puts the row 25 away once a direction is picked (ops#655)
            FCMD_OBJ_CMD(Feat, "Mode = 'Spacing'");
            FCMD_OBJ_CMD(Feat, "Offset = 25");
            FCMD_OBJ_CMD(Feat, "Occurrences = 2");
            FCMD_OBJ_CMD(Feat, "Mode2 = 'Spacing'");
            FCMD_OBJ_CMD(Feat, "Offset2 = 25");

            finishTransformed(cmd, Feat);
        };

    prepareTransformed(pcActiveBody, this, "LinearPattern", worker);
}

bool CmdPartDesignLinearPattern::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_PolarPattern
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignPolarPattern)

CmdPartDesignPolarPattern::CmdPartDesignPolarPattern()
    : Command("PartDesign_PolarPattern")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Circular pattern");  // FreeCAD-CH (ops#605): Onshape's word
    sToolTipText = QT_TR_NOOP(
        "Duplicates the selected features or the active body in a circular pattern"
    );
    sWhatsThis = "PartDesign_PolarPattern";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_PolarPattern";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignPolarPattern::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd,
                   pcActiveBody](App::DocumentObject* Feat, std::vector<App::DocumentObject*> features) {
        bool direction = false;
        if (!features.empty() && features.front()->isDerivedFrom<PartDesign::ProfileBased>()
            && !PartDesign::isStudioOwner(features.front())) {
            Part::Part2DObject* sketch = (static_cast<PartDesign::ProfileBased*>(features.front()))
                                             ->getVerifiedSketch(/* silent =*/true);
            if (sketch) {
                FCMD_OBJ_CMD(Feat, "Axis = (" << Gui::Command::getObjectCmd(sketch) << ",['N_Axis'])");
                direction = true;
            }
        }
        if (!direction) {
            FCMD_OBJ_CMD(
                Feat,
                "Axis = (" << Gui::Command::getObjectCmd(pcActiveBody->getOrigin()->getZ()) << ",[''])"
            );
        }

        // Onshape's defaults (ops#640 rank 8, B3-6): 360 deg, count 4, Equal spacing on
        // (Extent), Centered and Skip off
        FCMD_OBJ_CMD(Feat, "Mode = 'Extent'");
        FCMD_OBJ_CMD(Feat, "Angle = 360");
        FCMD_OBJ_CMD(Feat, "Occurrences = 4");

        finishTransformed(cmd, Feat);
    };

    prepareTransformed(pcActiveBody, this, "PolarPattern", worker);
}

bool CmdPartDesignPolarPattern::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_CurvePattern (FreeCAD-CH ops#655, T6: Onshape's Curve pattern)
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignCurvePattern)

CmdPartDesignCurvePattern::CmdPartDesignCurvePattern()
    : Command("PartDesign_CurvePattern")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Curve pattern");
    sToolTipText = QT_TR_NOOP("Duplicates the selected features or the active body along a path");
    sWhatsThis = "PartDesign_CurvePattern";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_CurvePattern";
    eType |= AcceptsOpenDialog;
}

void CmdPartDesignCurvePattern::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);
    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd](App::DocumentObject* Feat, std::vector<App::DocumentObject*> /*features*/) {
        // The path is picked in the panel, its field armed; the count is the feature's default
        finishTransformed(cmd, Feat);
    };

    prepareTransformed(pcActiveBody, this, "CurvePattern", worker);
}

bool CmdPartDesignCurvePattern::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_Scaled
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignScaled)

CmdPartDesignScaled::CmdPartDesignScaled()
    : Command("PartDesign_Scaled")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Scale");
    sToolTipText = QT_TR_NOOP("Scales the selected features or the active body");
    sWhatsThis = "PartDesign_Scaled";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Scaled";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignScaled::activated(int iMsg)
{
    Q_UNUSED(iMsg);

    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    Gui::Command* cmd = this;
    auto worker = [cmd](App::DocumentObject* Feat, std::vector<App::DocumentObject*> /*features*/) {
        FCMD_OBJ_CMD(Feat, "Factor = 2");
        FCMD_OBJ_CMD(Feat, "Occurrences = 2");

        finishTransformed(cmd, Feat);
    };

    prepareTransformed(pcActiveBody, this, "Scale", worker);
}

bool CmdPartDesignScaled::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_MultiTransform
//===========================================================================
DEF_STD_CMD_A(CmdPartDesignMultiTransform)

CmdPartDesignMultiTransform::CmdPartDesignMultiTransform()
    : Command("PartDesign_MultiTransform")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Multi-Transform");
    sToolTipText = QT_TR_NOOP(
        "Applies multiple transformations to the selected features or active body"
    );
    sWhatsThis = "PartDesign_MultiTransform";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_MultiTransform";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignMultiTransform::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(true);

    if (!pcActiveBody) {
        return;
    }

    std::vector<App::DocumentObject*> features;

    // Check if a Transformed feature has been selected, convert it to MultiTransform
    features = getSelection().getObjectsOfType(PartDesign::Transformed::getClassTypeId());
    if (!features.empty()) {
        // Throw out MultiTransform features, we don't want to nest them
        for (std::vector<App::DocumentObject*>::iterator f = features.begin(); f != features.end();) {
            if ((*f)->isDerivedFrom<PartDesign::MultiTransform>()) {
                f = features.erase(f);
            }
            else {
                f++;
            }
        }

        if (features.empty()) {
            return;
        }
        // Note: If multiple Transformed features were selected, only the first one is used
        PartDesign::Transformed* trFeat = static_cast<PartDesign::Transformed*>(features.front());

        // Move the insert point back one feature
        App::DocumentObject* oldTip = nullptr;
        App::DocumentObject* prevFeature = nullptr;
        if (pcActiveBody) {
            oldTip = pcActiveBody->Tip.getValue();
            prevFeature = pcActiveBody->getPrevSolidFeature(trFeat);
        }
        Gui::Selection().clearSelection();
        if (prevFeature) {
            Gui::Selection().addSelection(
                prevFeature->getDocument()->getName(),
                prevFeature->getNameInDocument()
            );
        }

        openCommand(QT_TRANSLATE_NOOP("Command", "Convert to Multi-Transform feature"));

        Gui::CommandManager& rcCmdMgr = Gui::Application::Instance->commandManager();
        rcCmdMgr.runCommandByName("PartDesign_MoveTip");

        // We cannot remove the Transform feature from the body as otherwise
        // we will have a PartDesign feature without a body which is not allowed
        // and causes to pop up the migration dialog later when adding new features
        // to the body.
        // Additionally it creates the error message: "Links go out of the allowed scope"
        // #0003509
#if 0
        // Remove the Transformed feature from the Body
        if (pcActiveBody)
            FCMD_OBJ_CMD(pcActiveBody,"removeObject("<<getObjectCmd(trFeat)<<")");
#endif

        // Create a MultiTransform feature and move the Transformed feature inside it
        std::string FeatName = getUniqueObjectName("MultiTransform", pcActiveBody);
        FCMD_OBJ_CMD(pcActiveBody, "newObject('PartDesign::MultiTransform','" << FeatName << "')");
        auto Feat = pcActiveBody->getDocument()->getObject(FeatName.c_str());
        auto objCmd = getObjectCmd(trFeat);
        FCMD_OBJ_CMD(Feat, "Originals = " << objCmd << ".Originals");
        FCMD_OBJ_CMD(Feat, "TransformMode = " << objCmd << ".TransformMode");
        FCMD_OBJ_CMD(Feat, "BaseFeature = " << objCmd << ".BaseFeature");
        FCMD_OBJ_CMD(Feat, "Transformations = [" << objCmd << "]");

        FCMD_OBJ_CMD(trFeat, "Originals = []");

        // Add the MultiTransform into the Body at the current insert point
        finishFeature(this, Feat);

        // Restore the insert point
        if (pcActiveBody && oldTip != trFeat) {
            Gui::Selection().clearSelection();
            Gui::Selection().addSelection(oldTip->getDocument()->getName(), oldTip->getNameInDocument());
            rcCmdMgr.runCommandByName("PartDesign_MoveTip");
            Gui::Selection().clearSelection();
        }  // otherwise the insert point remains at the new MultiTransform, which is fine
    }
    else {

        Gui::Command* cmd = this;
        auto worker =
            [cmd,
             pcActiveBody](App::DocumentObject* Feat, std::vector<App::DocumentObject*> /*features*/) {
                // Make sure the user isn't presented with an empty screen because no
                // transformations are defined yet...
                App::DocumentObject* prevSolid = pcActiveBody->Tip.getValue();
                if (prevSolid) {
                    Part::Feature* feat = static_cast<Part::Feature*>(prevSolid);
                    FCMD_OBJ_CMD(Feat, "Shape = " << getObjectCmd(feat) << ".Shape");
                }
                finishFeature(cmd, Feat);
            };

        prepareTransformed(pcActiveBody, this, "MultiTransform", worker);
    }
}

bool CmdPartDesignMultiTransform::isActive()
{
    return hasActiveDocument();
}

//===========================================================================
// PartDesign_Boolean
//===========================================================================

/* Boolean commands =======================================================*/
DEF_STD_CMD_A(CmdPartDesignBoolean)

CmdPartDesignBoolean::CmdPartDesignBoolean()
    : Command("PartDesign_Boolean")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Boolean Operation");
    sToolTipText = QT_TR_NOOP(
        "Applies boolean operations with the selected objects and the active body"
    );
    sWhatsThis = "PartDesign_Boolean";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Boolean";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}


/* FreeCAD-CH (ops#654 P5, notes/parts-design.md 3.5, Onshape O3): in a studio that has a history
 * list, Boolean makes a studio feature: a PartDesign::Boolean in the studio, outside every Body,
 * whose targets and tools are parts by id. The studio is the active Body's, else the selected
 * part's, else the active Part's. Its first target is the active Body, its tools the other parts
 * selected, each only if live at the bar; it opens on Union (Onshape's default), Keep tools as
 * last accepted. One transaction with its list entry and its first recompute: Cancel leaves
 * nothing. False: not such a studio, today's path
 */
static bool makeStudioBoolean(Gui::Command* cmd)
{
    App::Document* doc = cmd->getDocument();
    if (!doc) {
        return false;
    }
    std::vector<PartDesign::Body*> picked;
    for (const auto& selected : cmd->getSelection().getSelectionEx()) {
        auto obj = const_cast<App::DocumentObject*>(selected.getObject());
        auto body = freecad_cast<PartDesign::Body*>(obj);
        if (!body) {
            body = PartDesign::Body::findBodyOf(obj);
        }
        if (body && std::ranges::find(picked, body) == picked.end()) {
            picked.push_back(body);
        }
    }
    PartDesign::Body* active = PartDesignGui::getBody(/*messageIfNot = */ false);
    if (active && active->getDocument() != doc) {
        active = nullptr;
    }
    App::Part* studio = nullptr;
    PartDesign::Body* anchor = active ? active : (picked.empty() ? nullptr : picked.front());
    if (anchor) {
        if (!Part::BodyBase::studioOf(anchor, studio)) {
            return false;
        }
    }
    else {
        studio = PartDesignGui::getActivePart();
    }
    // FreeCAD-CH ops#654: the studio's list is made on first use, in this step
    if (isAssemblyStudio(studio) || !takesStudioPath(doc, studio)) {
        return false;
    }
    if (refuseStudioList(doc, studio)) {
        return true;
    }
    auto pyList = [](const std::vector<std::string>& ids) {
        std::string out = "[";
        for (const auto& id : ids) {
            out += "'" + id + "',";
        }
        return out + "]";
    };
    const std::string name = cmd->getUniqueObjectName("Boolean");
    cmd->openCommand(QT_TRANSLATE_NOOP("Command", "Create Boolean"));
    try {
        PartDesign::StudioList* list = makeStudioList(doc, studio);
        const auto live = PartDesign::studioLivePartsAt(list, -1);
        auto isLive = [&live](PartDesign::Body* body) {
            return body && std::ranges::find(live, body) != live.end();
        };
        std::vector<std::string> targets;
        if (isLive(active)) {
            targets.push_back(PartDesign::studioPartId(active));
        }
        std::vector<std::string> tools;
        for (auto body : picked) {
            const std::string id = PartDesign::studioPartId(body);
            if (isLive(body) && std::ranges::find(targets, id) == targets.end()) {
                tools.push_back(id);
            }
        }
        Gui::cmdAppDocument(doc, std::ostringstream() << "addObject('PartDesign::Boolean','" << name << "')");
        App::DocumentObject* owner = doc->getObject(name.c_str());
        if (!owner) {
            throw Base::RuntimeError("The Boolean was not made");
        }
        const std::string ownerCmd = Gui::Command::getObjectCmd(owner);
        if (studio) {
            Gui::cmdAppObject(studio, std::ostringstream() << "addObject(" << ownerCmd << ")");
        }
        FCMD_OBJ_CMD(owner, "Type = 'Fuse'");
        // A Union lists its parts as tools, merged into the first (the active part)
        std::vector<std::string> parts = targets;
        parts.insert(parts.end(), tools.begin(), tools.end());
        FCMD_OBJ_CMD(owner, "StudioTools = " << pyList(parts));
        Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.studioInsert(%s, -1)", ownerCmd.c_str());
        {
            // A Boolean of fewer than two parts fails until its parts are ticked: not an error
            // printed while its dialog opens
            Base::ObjectStatusLocker<App::Document::Status, App::Document> guard(
                App::Document::IgnoreErrorOnRecompute,
                doc,
                parts.size() < 2
            );
            Gui::cmdAppDocument(doc, "recompute()");
        }
        PartDesignGui::TaskDlgFeatureParameters::noteCreated(owner);
        if (!PartDesignGui::setEdit(owner)) {
            throw Base::RuntimeError("The Boolean's dialog didn't open");
        }
        cmd->doCommand(cmd->Gui, "Gui.Selection.clearSelection()");
    }
    catch (const Base::Exception& e) {
        cmd->abortCommand();
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 10000);
        Base::Console().error("%s\n", e.what());
    }
    return true;
}

void CmdPartDesignBoolean::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    if (makeStudioBoolean(this)) {
        return;
    }
    PartDesign::Body* pcActiveBody = PartDesignGui::getBody(/*messageIfNot = */ true);
    if (!pcActiveBody) {
        return;
    }

    Gui::SelectionFilter BodyFilter("SELECT Part::Feature COUNT 1..");

    openCommand(QT_TRANSLATE_NOOP("Command", "Create Boolean"));
    std::string FeatName = getUniqueObjectName("Boolean", pcActiveBody);
    FCMD_OBJ_CMD(pcActiveBody, "newObject('PartDesign::Boolean','" << FeatName << "')");
    auto Feat = pcActiveBody->getDocument()->getObject(FeatName.c_str());

    // If we don't add an object to the boolean group then don't update the body
    // as otherwise this will fail and it will be marked as invalid
    bool updateDocument = false;
    if (BodyFilter.match() && !BodyFilter.Result.empty()) {
        std::vector<App::DocumentObject*> bodies;
        for (auto& results : BodyFilter.Result) {
            for (auto& result : results) {
                if (result.getObject() != pcActiveBody) {
                    bodies.push_back(result.getObject());
                }
            }
        }
        if (!bodies.empty()) {
            updateDocument = true;
            std::string bodyString = PartDesignGui::buildLinkListPythonStr(bodies);
            FCMD_OBJ_CMD(Feat, "addObjects(" << bodyString << ")");
        }
    }

    finishFeature(this, Feat, nullptr, false, updateDocument);
}

bool CmdPartDesignBoolean::isActive()
{
    if (getActiveGuiDocument()) {
        return true;
    }
    else {
        return false;
    }
}

//===========================================================================
// PartDesign_MergeParts (FreeCAD-CH ops#325, B+ Stage 1 3b, design 2.5)
//===========================================================================

DEF_STD_CMD_A(CmdPartDesignMergeParts)

CmdPartDesignMergeParts::CmdPartDesignMergeParts()
    : Command("PartDesign_MergeParts")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Merge Parts");
    sToolTipText = QT_TR_NOOP(
        "Merges parts into one: select the part to keep (or its feature to merge after), then "
        "the parts it absorbs"
    );
    sWhatsThis = "PartDesign_MergeParts";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Boolean";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignMergeParts::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    // In the order picked: the first is the part that stays
    std::vector<App::DocumentObject*> picked;
    for (auto& sel : Gui::Selection().getSelectionEx()) {
        App::DocumentObject* obj = sel.getObject();
        if (obj && std::ranges::find(picked, obj) == picked.end()) {
            picked.push_back(obj);
        }
    }
    if (picked.size() < 2) {
        QMessageBox::information(
            Gui::getMainWindow(),
            QObject::tr("Merge Parts"),
            QObject::tr("Select the part to keep (or its feature to merge after), then the parts "
                        "to merge into it.")
        );
        return;
    }
    std::string bodies;
    for (auto it = picked.begin() + 1; it != picked.end(); ++it) {
        App::DocumentObject* body = PartDesign::Body::findBodyOf(*it);
        if ((*it)->isDerivedFrom<PartDesign::Body>()) {
            body = *it;
        }
        bodies += (bodies.empty() ? "" : ", ") + (body ? getObjectCmd(body) : getObjectCmd(*it));
    }
    openCommand(QT_TRANSLATE_NOOP("Command", "Merge parts"));
    try {
        doCommand(Doc, "import PartDesign");
        doCommand(
            Doc,
            "PartDesign.makeMerge(%s, [%s])",
            getObjectCmd(picked.front()).c_str(),
            bodies.c_str()
        );
        updateActive();
        commitCommand();
    }
    catch (const Base::Exception& e) {
        abortCommand();
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Merge Parts"),
            QString::fromUtf8(e.what())
        );
    }
}

bool CmdPartDesignMergeParts::isActive()
{
    if (!getActiveGuiDocument() || Gui::Selection().size() < 2) {
        return false;
    }
    // FreeCAD-CH ops#654 R0 lite: the sibling path's Merge isn't offered in a studio with a
    // history list (its Boolean's Union merges parts there); the code stays for older studios
    for (auto& sel : Gui::Selection().getSelectionEx()) {
        App::DocumentObject* obj = sel.getObject();
        auto body = freecad_cast<PartDesign::Body*>(obj);
        if (!body) {
            body = PartDesign::Body::findBodyOf(obj);
        }
        App::Part* studio = nullptr;
        if (body && Part::BodyBase::studioOf(body, studio)
            && PartDesign::StudioList::of(body->getDocument(), studio, false)) {
            return false;
        }
    }
    return true;
}

//===========================================================================
// PartDesign_Split (FreeCAD-CH ops#325, B+ Stage 1 4, design 2.7)
//===========================================================================

DEF_STD_CMD_A(CmdPartDesignSplit)

CmdPartDesignSplit::CmdPartDesignSplit()
    : Command("PartDesign_Split")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Split Part");
    sToolTipText = QT_TR_NOOP(
        "Splits a part in two by a plane: select the part and an origin plane, a datum plane or "
        "a planar face. The part keeps one side, a new part the other"
    );
    sWhatsThis = "PartDesign_Split";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_Boolean";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignSplit::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    // The plane: an origin or datum plane, in any order, else a planar face (a Body's face is
    // its Tip's, PartDesign.split); the part: another pick, or the face's own part
    std::vector<Gui::SelectionObject> picks = Gui::Selection().getSelectionEx();
    App::DocumentObject* part = nullptr;
    App::DocumentObject* tool = nullptr;
    std::string sub;
    std::size_t toolPick = picks.size();
    for (std::size_t i = 0; i < picks.size() && !tool; ++i) {
        App::DocumentObject* obj = picks[i].getObject();
        if (obj->isDerivedFrom<App::Plane>() || obj->isDerivedFrom<PartDesign::Plane>()) {
            tool = obj;
            toolPick = i;
        }
    }
    for (std::size_t i = 0; i < picks.size() && !tool; ++i) {
        const std::vector<std::string>& subs = picks[i].getSubNames();
        if (!subs.empty() && subs.front().starts_with("Face")) {
            tool = picks[i].getObject();
            sub = subs.front();
            toolPick = i;
        }
    }
    for (std::size_t i = 0; i < picks.size() && !part; ++i) {
        if (i != toolPick) {
            part = picks[i].getObject();
        }
    }
    if (!part && tool && !sub.empty()) {
        part = tool;
    }
    PartDesign::Body* body = freecad_cast<PartDesign::Body*>(part);
    if (!body) {
        body = PartDesign::Body::findBodyOf(part);
    }
    if (!body || !tool) {
        QMessageBox::information(
            Gui::getMainWindow(),
            QObject::tr("Split Part"),
            QObject::tr("Select the part to split and a plane: an origin plane, a datum plane or "
                        "a planar face.")
        );
        return;
    }
    std::string toolArg = getObjectCmd(tool);
    if (!sub.empty()) {
        toolArg = "(" + toolArg + ", '" + sub + "')";
    }
    // The panel's OK commits it, its Cancel takes both halves away
    openCommand(QT_TRANSLATE_NOOP("Command", "Split part"));
    try {
        doCommand(Doc, "import PartDesign");
        doCommand(Doc, "PartDesign.split(%s, %s)", getObjectCmd(body).c_str(), toolArg.c_str());
        updateActive();
    }
    catch (const Base::Exception& e) {
        abortCommand();
        QMessageBox::warning(
            Gui::getMainWindow(),
            QObject::tr("Split Part"),
            QString::fromUtf8(e.what())
        );
        return;
    }
    PartDesignGui::setEdit(body->Tip.getValue(), body);
}

bool CmdPartDesignSplit::isActive()
{
    return getActiveGuiDocument() && Gui::Selection().size() >= 1;
}

//===========================================================================
// PartDesign_Derived (FreeCAD-CH ops#640 round 6, notes/onshape-tabs-design.md 2.5)
//===========================================================================

DEF_STD_CMD_A(CmdPartDesignDerived)

CmdPartDesignDerived::CmdPartDesignDerived()
    : Command("PartDesign_Derived")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Derived");
    sToolTipText = QT_TR_NOOP(
        "Brings parts of another part studio of this document into this one: each a new part "
        "that follows its source"
    );
    sWhatsThis = "PartDesign_Derived";
    sStatusTip = sToolTipText;
    sPixmap = "PartDesign_SubShapeBinder";
    eType |= AcceptsOpenDialog;  // FreeCAD-CH (ops#640): accepts an open feature dialog first
}

void CmdPartDesignDerived::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    App::Document* doc = getActiveGuiDocument() ? getActiveGuiDocument()->getDocument() : nullptr;
    App::Part* studio = nullptr;
    if (!doc || !PartDesignGui::activeStudio(doc, studio)) {
        QMessageBox::information(
            Gui::getMainWindow(),
            QObject::tr("Derived"),
            QObject::tr("The active part isn't in a part studio.")
        );
        return;
    }
    auto others = PartDesign::derivedStudios(doc);
    std::erase(others, studio);
    if (others.empty()) {
        QMessageBox::information(
            Gui::getMainWindow(),
            QObject::tr("Derived"),
            QObject::tr("No other part studio of this document has a part to derive.")
        );
        return;
    }
    // A dialog the step lock doesn't cover (none to accept first) is still open: refused visibly
    if (Gui::Control().activeDialog()) {
        Gui::getMainWindow()->showMessage(QObject::tr("Finish the open dialog first"), 5000);
        return;
    }
    Gui::Control().showDialog(new PartDesignGui::TaskDlgDerived(doc, studio));
}

bool CmdPartDesignDerived::isActive()
{
    // Another feature's dialog is accepted first (AcceptsOpenDialog, review R6-3); only a Derived
    // dialog already open greys it
    return getActiveGuiDocument()
        && !qobject_cast<PartDesignGui::TaskDlgDerived*>(Gui::Control().activeDialog());
}

// Command group for datums =============================================

class CmdPartDesignCompDatums: public Gui::GroupCommand
{
public:
    CmdPartDesignCompDatums()
        : GroupCommand("PartDesign_CompDatums")
    {
        sAppModule = "PartDesign";
        sGroup = "PartDesign";
        sMenuText = QT_TR_NOOP("Create Datum");
        sToolTipText = QT_TR_NOOP("Creates a datum object or local coordinate system");
        sWhatsThis = "PartDesign_CompDatums";
        sStatusTip = sToolTipText;
        // FreeCAD-CH (ops#640): beside a feature dialog holding its step, the tool accepts it first
        eType = ForEdit | AcceptsOpenDialog;

        setCheckable(false);

        addCommand("PartDesign_Plane");
        addCommand("PartDesign_Line");
        addCommand("PartDesign_Point");
        addCommand("PartDesign_CoordinateSystem");
    }

    const char* className() const override
    {
        return "CmdPartDesignCompDatums";
    }

    bool isActive() override
    {
        // FreeCAD-CH (ops#640): stays enabled beside a step-locked dialog (accept-first)
        return (hasActiveDocument() && (!Gui::Control().activeDialog() || stepLockedDocument()));
    }
};

// Command group for datums =============================================

class CmdPartDesignCompSketches: public Gui::GroupCommand
{
public:
    CmdPartDesignCompSketches()
        : GroupCommand("PartDesign_CompSketches")
    {
        sAppModule = "PartDesign";
        sGroup = "PartDesign";
        sMenuText = QT_TR_NOOP("Create Datum");
        sToolTipText = QT_TR_NOOP("Creates a datum object or local coordinate system");
        sWhatsThis = "PartDesign_CompDatums";
        sStatusTip = sToolTipText;
        // FreeCAD-CH (ops#640): beside a feature dialog holding its step, the tool accepts it first
        eType = ForEdit | AcceptsOpenDialog;

        setCheckable(false);
        setRememberLast(false);

        addCommand("PartDesign_NewSketch");
        addCommand("Sketcher_MapSketch");
        addCommand("Sketcher_EditSketch");
    }

    const char* className() const override
    {
        return "CmdPartDesignCompSketches";
    }

    bool isActive() override
    {
        // FreeCAD-CH (ops#640): stays enabled beside a step-locked dialog (accept-first)
        return (hasActiveDocument() && (!Gui::Control().activeDialog() || stepLockedDocument()));
    }
};

//===========================================================================
// Initialization
//===========================================================================

//===========================================================================
// PartDesign_ToggleSketches, PartDesign_TogglePlanes (FreeCAD-CH, ops#194: Onshape's Shift+H, P)
//===========================================================================

namespace
{

/// The object's view provider; none for the one in edit (hiding the sketch being edited, or the
/// datum plane in its panel, would pull it from under the user)
Gui::ViewProvider* viewProviderOf(App::DocumentObject* obj)
{
    Gui::Document* guiDoc = obj ? Gui::Application::Instance->getDocument(obj->getDocument())
                                : nullptr;
    Gui::ViewProvider* vp = guiDoc ? guiDoc->getViewProvider(obj) : nullptr;
    return vp && vp != guiDoc->getInEdit() ? vp : nullptr;
}

/// Hides them all when one is shown, else shows them all
void toggleTogether(const std::vector<Gui::ViewProvider*>& vps, bool anyShown)
{
    for (Gui::ViewProvider* vp : vps) {
        if (anyShown) {
            vp->hide();
        }
        else {
            vp->show();
        }
    }
}

}  // namespace

DEF_STD_CMD_A(CmdPartDesignToggleSketches)

CmdPartDesignToggleSketches::CmdPartDesignToggleSketches()
    : Command("PartDesign_ToggleSketches")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Show/Hide &Sketches");
    sToolTipText = QT_TR_NOOP(
        "Hides the active body's sketches if one is shown, otherwise shows them all"
    );
    sWhatsThis = "PartDesign_ToggleSketches";
    sStatusTip = sToolTipText;
    eType = Alter3DView;
}

void CmdPartDesignToggleSketches::activated(int /*iMsg*/)
{
    PartDesign::Body* body = PartDesignGui::getBody(/*messageIfNot = */ false, false);
    if (!body) {
        return;
    }
    std::vector<Gui::ViewProvider*> sketches;
    bool anyShown = false;
    for (App::DocumentObject* obj : body->Group.getValues()) {
        Gui::ViewProvider* vp = viewProviderOf(obj);
        if (vp && obj->isDerivedFrom<Part::Part2DObject>()) {
            sketches.push_back(vp);
            anyShown = anyShown || vp->isShow();
        }
    }
    toggleTogether(sketches, anyShown);
}

bool CmdPartDesignToggleSketches::isActive()
{
    return PartDesignGui::getBody(/*messageIfNot = */ false, false) != nullptr;
}

DEF_STD_CMD_A(CmdPartDesignTogglePlanes)

CmdPartDesignTogglePlanes::CmdPartDesignTogglePlanes()
    : Command("PartDesign_TogglePlanes")
{
    sAppModule = "PartDesign";
    sGroup = QT_TR_NOOP("PartDesign");
    sMenuText = QT_TR_NOOP("Show/Hide &Planes");
    sToolTipText = QT_TR_NOOP(
        "Hides the active body's origin and datum planes if one is shown, otherwise shows them all"
    );
    sWhatsThis = "PartDesign_TogglePlanes";
    sStatusTip = sToolTipText;
    eType = Alter3DView;
}

void CmdPartDesignTogglePlanes::activated(int /*iMsg*/)
{
    PartDesign::Body* body = PartDesignGui::getBody(/*messageIfNot = */ false, false);
    App::Origin* origin = body ? body->getOrigin() : nullptr;
    Gui::ViewProvider* originVp = viewProviderOf(origin);
    if (!originVp) {
        return;
    }
    // An origin's planes show only with the origin
    std::vector<Gui::ViewProvider*> planes;
    bool anyShown = false;
    for (App::Plane* plane : origin->planes()) {
        if (Gui::ViewProvider* vp = viewProviderOf(plane)) {
            planes.push_back(vp);
            anyShown = anyShown || (originVp->isShow() && vp->isShow());
        }
    }
    for (App::DocumentObject* obj : body->Group.getValues()) {
        Gui::ViewProvider* vp = viewProviderOf(obj);
        if (vp && obj->isDerivedFrom<PartDesign::Plane>()) {
            planes.push_back(vp);
            anyShown = anyShown || vp->isShow();
        }
    }
    if (!anyShown && !originVp->isShow()) {
        // show the origin for its planes only: its axes and point stay hidden
        for (App::DocumentObject* obj : origin->OriginFeatures.getValues()) {
            Gui::ViewProvider* vp = viewProviderOf(obj);
            if (vp && !obj->isDerivedFrom<App::Plane>()) {
                vp->hide();
            }
        }
        originVp->show();
    }
    toggleTogether(planes, anyShown);
}

bool CmdPartDesignTogglePlanes::isActive()
{
    return PartDesignGui::getBody(/*messageIfNot = */ false, false) != nullptr;
}

void CreatePartDesignCommands()
{
    Gui::CommandManager& rcCmdMgr = Gui::Application::Instance->commandManager();

    rcCmdMgr.addCommand(new CmdPartDesignShapeBinder());
    rcCmdMgr.addCommand(new CmdPartDesignSubShapeBinder());
    rcCmdMgr.addCommand(new CmdPartDesignClone());
    rcCmdMgr.addCommand(new CmdPartDesignPlane());
    rcCmdMgr.addCommand(new CmdPartDesignLine());
    rcCmdMgr.addCommand(new CmdPartDesignPoint());
    rcCmdMgr.addCommand(new CmdPartDesignCS());

    rcCmdMgr.addCommand(new CmdPartDesignNewSketch());

    rcCmdMgr.addCommand(new CmdPartDesignPad());
    rcCmdMgr.addCommand(new CmdPartDesignPocket());
    rcCmdMgr.addCommand(new CmdPartDesignHole());
    rcCmdMgr.addCommand(new CmdPartDesignRevolution());
    rcCmdMgr.addCommand(new CmdPartDesignGroove());
    rcCmdMgr.addCommand(new CmdPartDesignAdditivePipe);
    rcCmdMgr.addCommand(new CmdPartDesignSubtractivePipe);
    rcCmdMgr.addCommand(new CmdPartDesignAdditiveLoft);
    rcCmdMgr.addCommand(new CmdPartDesignSubtractiveLoft);
    rcCmdMgr.addCommand(new CmdPartDesignAdditiveHelix);
    rcCmdMgr.addCommand(new CmdPartDesignSubtractiveHelix);

    rcCmdMgr.addCommand(new CmdPartDesignFillet());
    rcCmdMgr.addCommand(new CmdPartDesignDraft());
    rcCmdMgr.addCommand(new CmdPartDesignChamfer());
    rcCmdMgr.addCommand(new CmdPartDesignThickness());
    rcCmdMgr.addCommand(new CmdPartDesignDefeaturing());
    // FreeCAD-CH (ops#655 T8): the face patterns
    rcCmdMgr.addCommand(new CmdPartDesignFaceLinearPattern());
    rcCmdMgr.addCommand(new CmdPartDesignFacePolarPattern());
    rcCmdMgr.addCommand(new CmdPartDesignFaceMirrored());

    rcCmdMgr.addCommand(new CmdPartDesignMirrored());
    rcCmdMgr.addCommand(new CmdPartDesignLinearPattern());
    rcCmdMgr.addCommand(new CmdPartDesignPolarPattern());
    rcCmdMgr.addCommand(new CmdPartDesignCurvePattern());
    // rcCmdMgr.addCommand(new CmdPartDesignScaled());
    rcCmdMgr.addCommand(new CmdPartDesignMultiTransform());

    rcCmdMgr.addCommand(new CmdPartDesignBoolean());
    rcCmdMgr.addCommand(new CmdPartDesignMergeParts());
    rcCmdMgr.addCommand(new CmdPartDesignSplit());
    rcCmdMgr.addCommand(new CmdPartDesignDerived());
    rcCmdMgr.addCommand(new CmdPartDesignCompDatums());
    rcCmdMgr.addCommand(new CmdPartDesignCompSketches());
    rcCmdMgr.addCommand(new CmdPartDesignToggleSketches());
    rcCmdMgr.addCommand(new CmdPartDesignTogglePlanes());
}
