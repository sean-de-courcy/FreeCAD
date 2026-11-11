// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2013 Jan Rheinländer                                    *
 *                                   <jrheinlaender@users.sourceforge.net> *
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


#include <QAction>
#include <QApplication>
#include <QCheckBox>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>

#include <algorithm>
#include <array>


#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/CommandT.h>
#include <Gui/Selection/Selection.h>
#include <Gui/Tools.h>
#include <Gui/ViewProvider.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/FeatureBoolean.h>
#include <Mod/PartDesign/App/StudioList.h>

#include "ui_TaskBooleanParameters.h"
#include "TaskBooleanParameters.h"


using namespace PartDesignGui;
using namespace Gui;

namespace PartDesignGui
{
// StudioGui.cpp (FreeCAD-CH ops#654 P5): a Boolean studio feature's Targets and Tools
QWidget* makeStudioBooleanBox(App::DocumentObject* owner);
void studioBooleanBoxSetType(QWidget* box, const char* type);
void studioBooleanBoxSetKeepTools(QWidget* box, bool on);
}  // namespace PartDesignGui

/* TRANSLATOR PartDesignGui::TaskBooleanParameters */

namespace
{

// The tools list's row of the Boolean's own part (FreeCAD-CH ops#640 rank 28): a tool of a Union or
// an Intersect, which getBodies() leaves out (the Boolean is in it)
constexpr int ownPartRole = Qt::UserRole + 1;

constexpr const char* keepToolsParam = "BooleanKeepTools";

// Union, Subtract, Intersect: Type's Fuse, Cut, Common (of the generated form, whatever its scope)
template<typename Form>
std::array<QPushButton*, 3> typeButtons(const Form& ui)
{
    return {ui.buttonUnion, ui.buttonSubtract, ui.buttonIntersect};
}

PartDesign::Body* getBodyOfSelection(App::DocumentObject* object)
{
    if (!object) {
        return nullptr;
    }

    if (object->isDerivedFrom<PartDesign::Body>()) {
        return static_cast<PartDesign::Body*>(object);
    }

    return PartDesign::Body::findBodyOf(object);
}

class BooleanToolSelection: public Gui::SelectionGate
{
public:
    explicit BooleanToolSelection(PartDesign::Boolean* boolean)
        : boolean(boolean)
    {}

    bool allow(App::Document* document, App::DocumentObject* object, const char*) override
    {
        if (!boolean) {
            return false;
        }

        auto* body = getBodyOfSelection(object);
        if (document == boolean->getDocument() && body == boolean->getFeatureBody()) {
            notAllowedReason = QT_TR_NOOP("The result Body cannot be used as a Boolean tool.");
            return false;
        }

        return true;
    }

private:
    PartDesign::Boolean* boolean;
};

}  // namespace

TaskBooleanParameters::TaskBooleanParameters(ViewProviderBoolean* BooleanView, QWidget* parent)
    : TaskBox(Gui::BitmapFactory().pixmap("PartDesign_Boolean"), tr("Boolean Parameters"), true, parent)
    , ui(new Ui_TaskBooleanParameters)
    , BooleanView(BooleanView)
{
    selectionMode = none;

    // we need a separate container widget to add all controls to
    proxy = new QWidget(this);
    ui->setupUi(proxy);
    QMetaObject::connectSlotsByName(this);

    this->groupLayout()->addWidget(proxy);

    PartDesign::Boolean* pcBoolean = BooleanView->getObject<PartDesign::Boolean>();
    // Onshape's Boolean (ops#640 rank 28, hands-on A-5): its own part is a tool of a Union or an
    // Intersect, listed first, and the Targets of a Subtract
    PartDesign::Body* own = pcBoolean->getFeatureBody();
    if (own && !pcBoolean->isMerge()) {
        const QString label = QString::fromUtf8(own->Label.getValue());
        auto item = new QListWidgetItem(ui->listWidgetBodies);
        item->setText(tr("%1 (this part)").arg(label));
        item->setData(Qt::UserRole, QString::fromLatin1(own->getNameInDocument()));
        item->setData(ownPartRole, true);
        item->setFlags(Qt::ItemIsEnabled);
        ui->targetsField->setText(label);
    }
    std::vector<App::DocumentObject*> bodies = pcBoolean->Group.getValues();
    for (auto body : bodies) {
        QListWidgetItem* item = new QListWidgetItem(ui->listWidgetBodies);
        item->setText(QString::fromUtf8(body->Label.getValue()));
        item->setData(Qt::UserRole, QString::fromLatin1(body->getNameInDocument()));
    }

    // Create context menu
    QAction* action = new QAction(tr("Remove"), this);
    action->setShortcut(Gui::QtTools::deleteKeySequence());

    // display shortcut behind the context menu entry
    action->setShortcutVisibleInContextMenu(true);

    ui->listWidgetBodies->addAction(action);
    connect(action, &QAction::triggered, this, &TaskBooleanParameters::onBodyDeleted);
    ui->listWidgetBodies->setContextMenuPolicy(Qt::ActionsContextMenu);

    // A new Boolean opens on Union, Keep tools as last accepted (the Boolean's default)
    const int index = std::clamp(static_cast<int>(pcBoolean->Type.getValue()), 0, 2);
    typeButtons(*ui)[index]->setChecked(true);
    ui->checkKeepTools->setChecked(pcBoolean->KeepTools.getValue());
    showFieldsOf(index);

    // clang-format off
    connect(ui->buttonBodyAdd, &QToolButton::toggled,
            this, &TaskBooleanParameters::onButtonBodyAdd);
    connect(ui->buttonBodyRemove, &QToolButton::toggled,
            this, &TaskBooleanParameters::onButtonBodyRemove);
    connect(ui->checkKeepTools, &QCheckBox::toggled,
            this, &TaskBooleanParameters::onKeepToolsChanged);
    // clang-format on
    const auto buttons = typeButtons(*ui);
    for (int i = 0; i < static_cast<int>(buttons.size()); ++i) {
        connect(buttons[i], &QPushButton::toggled, this, [this, i](bool on) {
            if (on) {
                onTypeChanged(i);
            }
        });
    }

    // A Boolean studio feature (FreeCAD-CH ops#654 P5): its targets and tools are parts of the
    // studio by id, ticked among the live parts at its place; the Body list and its picks aren't
    // used
    studioBox = makeStudioBooleanBox(pcBoolean);
    if (studioBox) {
        ui->labelTools->setVisible(false);
        ui->buttonBodyAdd->setVisible(false);
        ui->buttonBodyRemove->setVisible(false);
        ui->listWidgetBodies->setVisible(false);
        showFieldsOf(index);
        groupLayout()->addWidget(studioBox);
    }

    // A Merge (FreeCAD-CH ops#325, design 2.6): its tool is the merged part's feature, which a
    // pick here would replace by a Body; Accept clears its warning, in this dialog's transaction
    if (pcBoolean->isMerge()) {
        ui->buttonBodyAdd->setEnabled(false);
        ui->buttonBodyRemove->setEnabled(false);
        for (auto button : typeButtons(*ui)) {
            button->setEnabled(false);
        }
        QStringList merged;
        for (auto body : pcBoolean->mergedBodies()) {
            merged << QString::fromUtf8(body->Label.getValue());
        }
        auto note = new QLabel(
            tr("A Merge of %1: delete it to unmerge").arg(merged.join(QStringLiteral(", "))),
            this
        );
        note->setObjectName(QStringLiteral("mergeNote"));
        note->setWordWrap(true);
        groupLayout()->addWidget(note);
        auto accepted = freecad_cast<App::PropertyBool*>(pcBoolean->getPropertyByName("MergeAccepted"));
        if (accepted && !accepted->getValue()) {
            auto accept = new QPushButton(tr("Accept Merge"), this);
            accept->setObjectName(QStringLiteral("acceptMergeButton"));
            accept->setToolTip(tr("The merge is meant: its warning goes"));
            groupLayout()->addWidget(accept);
            connect(accept, &QPushButton::clicked, this, [this, accept]() {
                auto merge = this->BooleanView->getObject<PartDesign::Boolean>();
                FCMD_OBJ_CMD(merge, "MergeAccepted = True");
                Gui::cmdAppDocument(merge, "recompute()");
                accept->setEnabled(false);
            });
        }
    }
}

void TaskBooleanParameters::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (selectionMode == none) {
        return;
    }

    if (msg.Type == Gui::SelectionChanges::AddSelection) {
        if (strcmp(msg.pDocName, BooleanView->getObject()->getDocument()->getName()) != 0) {
            return;
        }

        // get the selected object
        PartDesign::Boolean* pcBoolean = BooleanView->getObject<PartDesign::Boolean>();
        std::string body(msg.pObjectName);
        if (body.empty()) {
            return;
        }
        App::DocumentObject* pcBody = pcBoolean->getDocument()->getObject(body.c_str());
        if (!pcBody) {
            return;
        }

        // if the selected object is not a body then get the body it is part of
        pcBody = getBodyOfSelection(pcBody);
        if (!pcBody || pcBody == pcBoolean->getFeatureBody()) {
            return;
        }
        body = pcBody->getNameInDocument();

        std::vector<App::DocumentObject*> bodies = pcBoolean->Group.getValues();

        if (selectionMode == bodyAdd) {
            if (std::ranges::find(bodies, pcBody) == bodies.end()) {
                bodies.push_back(pcBody);
                pcBoolean->Group.setValues(std::vector<App::DocumentObject*>());
                pcBoolean->addObjects(bodies);

                QListWidgetItem* item = new QListWidgetItem(ui->listWidgetBodies);
                item->setText(QString::fromUtf8(pcBody->Label.getValue()));
                item->setData(Qt::UserRole, QString::fromLatin1(pcBody->getNameInDocument()));

                pcBoolean->getDocument()->recomputeFeature(pcBoolean);
                ui->buttonBodyAdd->setChecked(false);
                exitSelectionMode();

                // Hide the bodies
                if (bodies.size() == 1) {
                    // Hide base body and added body
                    Gui::ViewProviderDocumentObject* vp = dynamic_cast<Gui::ViewProviderDocumentObject*>(
                        Gui::Application::Instance->getViewProvider(pcBoolean->BaseFeature.getValue())
                    );
                    if (vp) {
                        vp->hide();
                    }
                    vp = dynamic_cast<Gui::ViewProviderDocumentObject*>(
                        Gui::Application::Instance->getViewProvider(bodies.front())
                    );
                    if (vp) {
                        vp->hide();
                    }
                    BooleanView->show();
                }
                else {
                    // Hide newly added body
                    Gui::ViewProviderDocumentObject* vp
                        = dynamic_cast<Gui::ViewProviderDocumentObject*>(
                            Gui::Application::Instance->getViewProvider(bodies.back())
                        );
                    if (vp) {
                        vp->hide();
                    }
                }
            }
        }
        else if (selectionMode == bodyRemove) {
            if (const auto b = std::ranges::find(bodies, pcBody); b != bodies.end()) {
                bodies.erase(b);
                pcBoolean->setObjects(bodies);

                const QString internalName = QString::fromStdString(body);
                for (int row = 0; row < ui->listWidgetBodies->count(); row++) {
                    QListWidgetItem* item = ui->listWidgetBodies->item(row);
                    QString name = item->data(Qt::UserRole).toString();
                    if (name == internalName) {
                        ui->listWidgetBodies->takeItem(row);
                        delete item;
                        break;
                    }
                }

                pcBoolean->getDocument()->recomputeFeature(pcBoolean);
                ui->buttonBodyRemove->setChecked(false);
                exitSelectionMode();

                // Make bodies visible again
                Gui::ViewProviderDocumentObject* vp = dynamic_cast<Gui::ViewProviderDocumentObject*>(
                    Gui::Application::Instance->getViewProvider(pcBody)
                );
                if (vp) {
                    vp->show();
                }
                if (bodies.empty()) {
                    Gui::ViewProviderDocumentObject* vp = dynamic_cast<Gui::ViewProviderDocumentObject*>(
                        Gui::Application::Instance->getViewProvider(pcBoolean->BaseFeature.getValue())
                    );
                    if (vp) {
                        vp->show();
                    }
                    BooleanView->hide();
                }
            }
        }
    }
}

void TaskBooleanParameters::onButtonBodyAdd(bool checked)
{
    if (checked) {
        PartDesign::Boolean* pcBoolean = BooleanView->getObject<PartDesign::Boolean>();
        Gui::Document* doc = BooleanView->getDocument();
        BooleanView->hide();
        if (pcBoolean->Group.getValues().empty() && pcBoolean->BaseFeature.getValue()) {
            doc->setHide(pcBoolean->BaseFeature.getValue()->getNameInDocument());
        }
        selectionMode = bodyAdd;
        Gui::Selection().clearSelection();
        Gui::Selection().addSelectionGate(new BooleanToolSelection(pcBoolean));
    }
    else {
        exitSelectionMode();
    }
}

void TaskBooleanParameters::onButtonBodyRemove(bool checked)
{
    if (checked) {
        Gui::Document* doc = Gui::Application::Instance->activeDocument();
        if (doc) {
            BooleanView->show();
        }
        selectionMode = bodyRemove;
        Gui::Selection().clearSelection();
    }
    else {
        exitSelectionMode();
    }
}

void TaskBooleanParameters::onTypeChanged(int index)
{
    PartDesign::Boolean* pcBoolean = BooleanView->getObject<PartDesign::Boolean>();
    if (studioBox) {
        // A list edit in the dialog's transaction (ops#654 P5)
        const char* types[] = {"Fuse", "Cut", "Common"};
        studioBooleanBoxSetType(studioBox, types[std::clamp(index, 0, 2)]);
        showFieldsOf(index);
        return;
    }

    switch (index) {
        case 0:
            pcBoolean->Type.setValue("Fuse");
            break;
        case 1:
            pcBoolean->Type.setValue("Cut");
            break;
        case 2:
            pcBoolean->Type.setValue("Common");
            break;
        default:
            pcBoolean->Type.setValue("Fuse");
    }

    showFieldsOf(index);

    // Force UI update before starting heavy computation to show user's selection immediately
    QApplication::processEvents();

    pcBoolean->getDocument()->recomputeFeature(pcBoolean);
}

void TaskBooleanParameters::onKeepToolsChanged(bool on)
{
    if (studioBox) {
        studioBooleanBoxSetKeepTools(studioBox, on);  // ops#654 P5: it changes what is consumed
        return;
    }
    PartDesign::Boolean* pcBoolean = BooleanView->getObject<PartDesign::Boolean>();
    pcBoolean->KeepTools.setValue(on);
    // An Intersect that misses keeps its part with Keep tools
    pcBoolean->getDocument()->recomputeFeature(pcBoolean);
}

void TaskBooleanParameters::showFieldsOf(int index)
{
    // Union and Intersect: Tools, Keep tools; Subtract: Tools, Targets, Offset, Keep tools (A-5)
    const bool merge = BooleanView->getObject<PartDesign::Boolean>()->isMerge();
    const bool subtract = index == 1 && !merge;
    ui->checkKeepTools->setVisible(!merge);
    if (studioBox) {
        // A studio Boolean's targets are its box's (ops#654 P5)
        ui->labelTargets->setVisible(false);
        ui->targetsField->setVisible(false);
        ui->checkOffset->setVisible(false);
        return;
    }
    ui->labelTargets->setVisible(subtract);
    ui->targetsField->setVisible(subtract);
    ui->checkOffset->setVisible(subtract);
    if (ui->listWidgetBodies->count() > 0) {
        QListWidgetItem* first = ui->listWidgetBodies->item(0);
        if (first->data(ownPartRole).toBool()) {
            first->setHidden(subtract);
        }
    }
}

const std::vector<std::string> TaskBooleanParameters::getBodies() const
{
    std::vector<std::string> result;
    for (int i = 0; i < ui->listWidgetBodies->count(); i++) {
        QListWidgetItem* item = ui->listWidgetBodies->item(i);
        if (!item->data(ownPartRole).toBool()) {
            result.push_back(item->data(Qt::UserRole).toString().toStdString());
        }
    }
    return result;
}

int TaskBooleanParameters::getType() const
{
    const auto buttons = typeButtons(*ui);
    const auto checked = std::ranges::find_if(buttons, [](QPushButton* button) {
        return button->isChecked();
    });
    return checked == buttons.end() ? 0 : static_cast<int>(checked - buttons.begin());
}

bool TaskBooleanParameters::getKeepTools() const
{
    return ui->checkKeepTools->isChecked();
}

void TaskBooleanParameters::onBodyDeleted()
{
    PartDesign::Boolean* pcBoolean = BooleanView->getObject<PartDesign::Boolean>();
    std::vector<App::DocumentObject*> bodies = pcBoolean->Group.getValues();
    // By the row's name: the first row may be the Boolean's own part, which stays (ops#640 rank 28)
    QListWidgetItem* current = ui->listWidgetBodies->currentItem();
    if (!current || current->data(ownPartRole).toBool()) {
        return;
    }

    App::DocumentObject* body = nullptr;
    QString internalName = current->data(Qt::UserRole).toString();
    for (auto it = bodies.begin(); it != bodies.end(); ++it) {
        if (internalName == QLatin1String((*it)->getNameInDocument())) {
            body = *it;
            bodies.erase(it);
            break;
        }
    }

    delete ui->listWidgetBodies->takeItem(ui->listWidgetBodies->row(current));
    if (!body) {
        return;
    }
    pcBoolean->setObjects(bodies);
    pcBoolean->getDocument()->recomputeFeature(pcBoolean);

    // Make bodies visible again
    Gui::ViewProviderDocumentObject* vp = dynamic_cast<Gui::ViewProviderDocumentObject*>(
        Gui::Application::Instance->getViewProvider(body)
    );
    if (vp) {
        vp->show();
    }
    if (bodies.empty()) {
        Gui::ViewProviderDocumentObject* vp = dynamic_cast<Gui::ViewProviderDocumentObject*>(
            Gui::Application::Instance->getViewProvider(pcBoolean->BaseFeature.getValue())
        );
        if (vp) {
            vp->show();
        }
        BooleanView->hide();
    }
}

TaskBooleanParameters::~TaskBooleanParameters()
{
    if (selectionMode == bodyAdd) {
        Gui::Selection().rmvSelectionGate();
    }
}

void TaskBooleanParameters::changeEvent(QEvent* e)
{
    TaskBox::changeEvent(e);
    if (e->type() == QEvent::LanguageChange) {
        ui->retranslateUi(proxy);
    }
}

void TaskBooleanParameters::exitSelectionMode()
{
    if (selectionMode == bodyAdd) {
        Gui::Selection().rmvSelectionGate();
    }
    selectionMode = none;
    Gui::Document* doc = Gui::Application::Instance->activeDocument();
    if (doc) {
        doc->setShow(BooleanView->getObject()->getNameInDocument());
    }
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgBooleanParameters::TaskDlgBooleanParameters(ViewProviderBoolean* BooleanView)
    : TaskDlgFeatureParameters(BooleanView)
    , BooleanView(BooleanView)
{
    assert(BooleanView);
    parameter = new TaskBooleanParameters(BooleanView);

    Content.push_back(parameter);
    Content.push_back(preview);

    // While open, an empty tool list computes nothing instead of failing (ops#314)
    if (auto boolean = BooleanView->getObject<PartDesign::Boolean>()) {
        boolean->setSettingUp(true);
        booleanT = App::DocumentObjectT(boolean);
    }
}

TaskDlgBooleanParameters::~TaskDlgBooleanParameters()
{
    // Gone when Cancel undid its creation
    if (auto boolean = booleanT.getObjectAs<PartDesign::Boolean>()) {
        boolean->setSettingUp(false);
    }
}

//==== calls from the TaskView ===============================================================


void TaskDlgBooleanParameters::open()
{
    TaskDlgFeatureParameters::open();
}

void TaskDlgBooleanParameters::clicked(int)
{}

bool TaskDlgBooleanParameters::accept()
{
    auto obj = BooleanView->getObject();
    if (!obj || !obj->isAttachedToDocument()) {
        return false;
    }
    // A Boolean studio feature (ops#654 P5): its list edits are made; Keep tools remembered
    if (PartDesign::isStudioOwner(obj)) {
        try {
            App::GetApplication()
                .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/PartDesign")
                ->SetBool(keepToolsParam, parameter->getKeepTools());
            Gui::Command::doCommand(Gui::Command::Doc, "App.ActiveDocument.recompute()");
            Gui::Command::doCommand(Gui::Command::Gui, "Gui.activeDocument().resetEdit()");
            // FreeCAD-CH (ops#654 P6p): the OK is the command that makes a split's pieces parts
            // (once the edit has ended; a step of its own when the edit's is closed by then)
            App::Document* document = obj->getDocument();
            const bool own = !document->hasPendingTransaction();
            if (own) {
                document->openTransaction(QT_TRANSLATE_NOOP("Command", "Make pieces parts"));
            }
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "import PartDesign\nPartDesign.studioMakePieces(%s)",
                Gui::Command::getObjectCmd(obj).c_str()
            );
            document->commitTransaction();
        }
        catch (const Base::Exception& e) {
            obj->getDocument()->abortTransaction();
            QMessageBox::warning(
                parameter,
                tr("Boolean: Accept: Input error"),
                QCoreApplication::translate("Exception", e.what())
            );
            return false;
        }
        return true;
    }
    BooleanView->Visibility.setValue(true);

    try {
        std::vector<std::string> bodies = parameter->getBodies();
        if (bodies.empty()) {
            QMessageBox::warning(parameter, tr("Empty Body List"), tr("The body list cannot be empty"));
            return false;
        }
        std::stringstream str;
        str << Gui::Command::getObjectCmd(obj) << ".setObjects( [";
        for (const auto& body : bodies) {
            str << "App.getDocument('" << obj->getDocument()->getName() << "').getObject('" << body
                << "'),";
        }
        str << "])";
        Gui::Command::runCommand(Gui::Command::Doc, str.str().c_str());
        FCMD_OBJ_CMD(obj, "Type = " << parameter->getType());
        // Keep tools, remembered for the next Boolean (ops#640 rank 28, hands-on A-5)
        auto boolean = freecad_cast<PartDesign::Boolean*>(obj);
        const bool plain = boolean && !boolean->isMerge();
        if (plain) {
            const bool keep = parameter->getKeepTools();
            FCMD_OBJ_CMD(obj, "KeepTools = " << (keep ? "True" : "False"));
            App::GetApplication()
                .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/PartDesign")
                ->SetBool(keepToolsParam, keep);
        }

        Gui::Command::doCommand(Gui::Command::Doc, "App.ActiveDocument.recompute()");
        Gui::Command::doCommand(Gui::Command::Gui, "Gui.activeDocument().resetEdit()");
        // A kept tool, or one a Union left apart, is a part still: shown; a consumed part is
        // hidden, as Onshape deletes it (B3-3a, A-2' b)
        if (plain) {
            const std::vector<App::DocumentObject*> separate = boolean->SeparateTools.getValues();
            for (auto tool : boolean->Group.getValues()) {
                if (boolean->KeepTools.getValue() || std::ranges::find(separate, tool) != separate.end()) {
                    FCMD_OBJ_SHOW(tool);
                }
                else if (tool->isDerivedFrom<PartDesign::Body>()) {
                    FCMD_OBJ_HIDE(tool);
                }
            }
        }
        obj->getDocument()->commitTransaction();
    }
    catch (const Base::Exception& e) {
        obj->getDocument()->abortTransaction();
        QMessageBox::warning(
            parameter,
            tr("Boolean: Accept: Input error"),
            QCoreApplication::translate("Exception", e.what())
        );
        return false;
    }
    return true;
}

bool TaskDlgBooleanParameters::reject()
{
    // Show the bodies again
    PartDesign::Boolean* obj = BooleanView->getObject<PartDesign::Boolean>();
    Gui::Document* doc = Gui::Application::Instance->activeDocument();
    if (doc) {
        if (obj->BaseFeature.getValue()) {
            doc->setShow(obj->BaseFeature.getValue()->getNameInDocument());
            std::vector<App::DocumentObject*> bodies = obj->Group.getValues();
            for (auto body : bodies) {
                doc->setShow(body->getNameInDocument());
            }
        }
        // roll back the done things
        doc->abortCommand();
        Gui::Command::doCommand(Gui::Command::Gui, "Gui.activeDocument().resetEdit()");
    }

    return true;
}

#include "moc_TaskBooleanParameters.cpp"
