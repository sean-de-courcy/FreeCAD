// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 Crawlspace Habitats LLC                            *
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

// FreeCAD-CH (ops#640): the view tools of Onshape's View menu: section view, named views,
// display styles, camera.

#include <algorithm>
#include <vector>

#include <Inventor/SbVec3f.h>
#include <QCoreApplication>
#include <QInputDialog>
#include <QLineEdit>
#include <QMenu>
#include <QPointer>
#include <QStringList>

#include <App/Application.h>
#include <Base/Parameter.h>

#include "Action.h"
#include "Application.h"
#include "BitmapFactory.h"
#include "Command.h"
#include "Document.h"
#include "MainWindow.h"
#include "NamedViews.h"
#include "SectionView.h"
#include "View3DInventor.h"
#include "View3DInventorViewer.h"
#include "ViewProviderDocumentObject.h"

using namespace Gui;

namespace
{
View3DInventor* activeView3D()
{
    return qobject_cast<View3DInventor*>(getMainWindow()->activeWindow());
}
}  // namespace

//===========================================================================
// Std_SectionView
//===========================================================================

DEF_STD_CMD_AC(StdCmdSectionView)

namespace
{
std::vector<QPointer<Gui::Dialog::SectionViewPanel>> sectionPanels;
}

StdCmdSectionView::StdCmdSectionView()
    : Command("Std_SectionView")
{
    sGroup = "Standard-View";
    sMenuText = QT_TR_NOOP("&Section view");
    sToolTipText = QT_TR_NOOP(
        "Hides one side of a plane and fills the cut, so the model looks solid. Only the view "
        "changes, not the document"
    );
    sWhatsThis = "Std_SectionView";
    sStatusTip = sToolTipText;
    sPixmap = "Std_ToggleClipPlane";
    eType = Alter3DView;
}

Action* StdCmdSectionView::createAction()
{
    Action* pcAction = Command::createAction();
    pcAction->setCheckable(true);
    return pcAction;
}

void StdCmdSectionView::activated(int iMsg)
{
    View3DInventor* view = activeView3D();
    if (!view) {
        return;
    }

    // forget the panels that are gone
    sectionPanels.erase(
        std::remove_if(
            sectionPanels.begin(),
            sectionPanels.end(),
            [](const QPointer<Gui::Dialog::SectionViewPanel>& panel) { return panel.isNull(); }
        ),
        sectionPanels.end()
    );
    auto panelOfView = std::find_if(
        sectionPanels.begin(),
        sectionPanels.end(),
        [view](const QPointer<Gui::Dialog::SectionViewPanel>& panel) {
            return panel->getView() == view;
        }
    );

    if (iMsg == 1) {
        if (panelOfView == sectionPanels.end()) {
            sectionPanels.emplace_back(Gui::Dialog::SectionViewPanel::makeDockWidget(view));
        }
    }
    else {
        if (panelOfView != sectionPanels.end()) {
            (*panelOfView)->closePanel();
            sectionPanels.erase(panelOfView);
        }
        // a section that was set without the panel (Python)
        SectionView::clear(view->getViewer());
    }

    SbVec3f origin;
    SbVec3f cut;
    if (_pcAction) {
        _pcAction->setBlockedChecked(SectionView::get(view->getViewer(), origin, cut));
    }
}

bool StdCmdSectionView::isActive()
{
    View3DInventor* view = activeView3D();
    if (!view) {
        return false;
    }
    SbVec3f origin;
    SbVec3f cut;
    const bool on = SectionView::get(view->getViewer(), origin, cut);
    if (_pcAction && _pcAction->isChecked() != on) {
        _pcAction->setBlockedChecked(on);
    }
    return true;
}

//===========================================================================
// Std_SaveNamedView
//===========================================================================

DEF_3DV_CMD(StdCmdSaveNamedView)

StdCmdSaveNamedView::StdCmdSaveNamedView()
    : Command("Std_SaveNamedView")
{
    sGroup = "Standard-View";
    sMenuText = QT_TR_NOOP("Save named &view...");
    sToolTipText = QT_TR_NOOP("Saves the camera of the view under a name, in the document");
    sWhatsThis = "Std_SaveNamedView";
    sStatusTip = sToolTipText;
    eType = Alter3DView;
}

void StdCmdSaveNamedView::activated(int iMsg)
{
    Q_UNUSED(iMsg);
    Gui::Document* doc = getActiveGuiDocument();
    if (!doc) {
        return;
    }

    const auto existing = NamedViews::names(doc);
    bool ok = false;
    const QString name = QInputDialog::getText(
                             getMainWindow(),
                             QObject::tr("Save named view"),
                             QObject::tr("Name of the view (a view of the same name is replaced):"),
                             QLineEdit::Normal,
                             QObject::tr("View %1").arg(existing.size() + 1),
                             &ok
    ).trimmed();
    if (ok && !name.isEmpty()) {
        if (!NamedViews::saveCurrent(doc, name.toStdString())) {
            getMainWindow()->showMessage(QObject::tr("The view could not be saved"), 5000);
        }
        getMainWindow()->updateActions();
    }
}

//===========================================================================
// Std_NamedViews
//===========================================================================

class StdCmdNamedViews: public Gui::Command
{
public:
    StdCmdNamedViews();
    ~StdCmdNamedViews() override = default;
    const char* className() const override
    {
        return "StdCmdNamedViews";
    }

protected:
    void activated(int iMsg) override;
    bool isActive() override;
    Action* createAction() override;

private:
    void refresh();
    QString chooseView(const QString& title);

    static constexpr int maxViews {40};  // the entries made up front, as Std_FreezeViews does
    int offset {0};
    QAction* renameItem {nullptr};
    QAction* deleteItem {nullptr};
    QAction* separator {nullptr};
};

StdCmdNamedViews::StdCmdNamedViews()
    : Command("Std_NamedViews")
{
    sGroup = "Standard-View";
    sMenuText = QT_TR_NOOP("Named views");
    sToolTipText = QT_TR_NOOP("Restores, renames or deletes the named views of the document");
    sWhatsThis = "Std_NamedViews";
    sStatusTip = sToolTipText;
    eType = Alter3DView;
}

Action* StdCmdNamedViews::createAction()
{
    auto pcAction = new ActionGroup(this, getMainWindow());
    pcAction->setDropDownMenu(true);
    applyCommandData(this->className(), pcAction);

    renameItem = pcAction->addAction(QObject::tr("&Rename view..."));
    renameItem->setWhatsThis(QString::fromLatin1(getWhatsThis()));
    deleteItem = pcAction->addAction(QObject::tr("&Delete view..."));
    deleteItem->setWhatsThis(QString::fromLatin1(getWhatsThis()));
    separator = pcAction->addAction(QString());
    separator->setSeparator(true);
    offset = pcAction->actions().count();
    for (int i = 0; i < maxViews; ++i) {
        pcAction->addAction(QString())->setVisible(false);
    }

    // the entries are made from the active document each time the menu opens
    QObject::connect(pcAction, &ActionGroup::aboutToShow, [this](QMenu*) { refresh(); });
    return pcAction;
}

void StdCmdNamedViews::refresh()
{
    auto group = qobject_cast<ActionGroup*>(_pcAction);
    if (!group) {
        return;
    }
    Gui::Document* doc = getActiveGuiDocument();
    const auto names = doc ? NamedViews::names(doc) : std::vector<std::string>();
    const bool any = !names.empty();
    renameItem->setEnabled(any);
    deleteItem->setEnabled(any);
    separator->setVisible(any);

    const QList<QAction*> items = group->actions();
    for (int i = 0; i < maxViews && offset + i < items.size(); ++i) {
        QAction* item = items[offset + i];
        if (i < int(names.size())) {
            const QString name = QString::fromStdString(names[i]);
            item->setData(name);
            item->setToolTip(name);
            item->setText(QString(name).replace(QLatin1Char('&'), QStringLiteral("&&")));
            item->setVisible(true);
        }
        else {
            item->setData(QString());
            item->setVisible(false);
        }
    }
}

QString StdCmdNamedViews::chooseView(const QString& title)
{
    Gui::Document* doc = getActiveGuiDocument();
    QStringList items;
    if (doc) {
        for (const auto& name : NamedViews::names(doc)) {
            items << QString::fromStdString(name);
        }
    }
    if (items.isEmpty()) {
        return {};
    }
    bool ok = false;
    const QString name
        = QInputDialog::getItem(getMainWindow(), title, QObject::tr("View:"), items, 0, false, &ok);
    return ok ? name : QString();
}

void StdCmdNamedViews::activated(int iMsg)
{
    Gui::Document* doc = getActiveGuiDocument();
    if (!doc) {
        return;
    }
    refresh();

    if (iMsg == 0) {
        const QString oldName = chooseView(QObject::tr("Rename named view"));
        if (oldName.isEmpty()) {
            return;
        }
        bool ok = false;
        const QString newName = QInputDialog::getText(
                                    getMainWindow(),
                                    QObject::tr("Rename named view"),
                                    QObject::tr("New name:"),
                                    QLineEdit::Normal,
                                    oldName,
                                    &ok
        ).trimmed();
        if (ok && !newName.isEmpty()
            && !NamedViews::rename(doc, oldName.toStdString(), newName.toStdString())) {
            getMainWindow()->showMessage(QObject::tr("A view of this name exists already"), 5000);
        }
    }
    else if (iMsg == 1) {
        const QString name = chooseView(QObject::tr("Delete named view"));
        if (!name.isEmpty()) {
            NamedViews::remove(doc, name.toStdString());
        }
    }
    else if (iMsg >= offset) {
        auto group = qobject_cast<ActionGroup*>(_pcAction);
        const QList<QAction*> items = group ? group->actions() : QList<QAction*>();
        if (iMsg < items.size()) {
            const QString name = items[iMsg]->data().toString();
            if (!name.isEmpty()) {
                NamedViews::restore(doc, name.toStdString());
            }
        }
    }
    refresh();
}

bool StdCmdNamedViews::isActive()
{
    if (!activeView3D()) {
        return false;
    }
    refresh();
    return true;
}

//===========================================================================
// Std_DisplayStyle and Std_TangentEdges: Onshape's display menu
//===========================================================================

namespace
{
// The display settings of the Part shapes (the view provider reads them where it renders):
// the same parameters ViewProviderPartExt reads.
ParameterGrp::handle displayParameters()
{
    return App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Part/View"
    );
}

/** The shapes of every open document take a changed display setting. */
void refreshDisplay()
{
    for (App::Document* appDoc : App::GetApplication().getDocuments()) {
        Gui::Document* doc = Application::Instance->getDocument(appDoc);
        if (!doc) {
            continue;
        }
        for (ViewProvider* vp :
             doc->getViewProvidersOfType(ViewProviderDocumentObject::getClassTypeId())) {
            static_cast<ViewProviderDocumentObject*>(vp)->updateView();
        }
    }
}

// the viewer's override mode of each style of the menu
const char* const displayModes[] = {"Shaded", "Flat Lines", "Flat Lines", "Wireframe"};
constexpr int hiddenEdgesStyle = 2;
}  // namespace

class StdCmdDisplayStyle: public Gui::Command
{
public:
    StdCmdDisplayStyle();
    ~StdCmdDisplayStyle() override = default;
    const char* className() const override
    {
        return "StdCmdDisplayStyle";
    }
    void languageChange() override;

protected:
    void activated(int iMsg) override;
    bool isActive() override;
    Action* createAction() override;
};

StdCmdDisplayStyle::StdCmdDisplayStyle()
    : Command("Std_DisplayStyle")
{
    sGroup = "Standard-View";
    sMenuText = QT_TR_NOOP("&Display");
    sToolTipText = QT_TR_NOOP("Changes how the faces and edges of the model are drawn");
    sStatusTip = sToolTipText;
    sWhatsThis = "Std_DisplayStyle";
    sPixmap = "DrawStyleFlatLines";
    eType = Alter3DView;
}

Action* StdCmdDisplayStyle::createAction()
{
    auto pcAction = new ActionGroup(this, getMainWindow());
    pcAction->setDropDownMenu(true);
    pcAction->setIsMode(true);
    applyCommandData(this->className(), pcAction);

    const char* const names[] = {
        "Std_DisplayShaded",
        "Std_DisplayShadedEdges",
        "Std_DisplayHiddenEdges",
        "Std_DisplayWireframe",
    };
    const char* const icons[] = {
        "DrawStyleShaded",
        "DrawStyleFlatLines",
        "DrawStyleHiddenLine",
        "DrawStyleWireFrame",
    };
    for (int i = 0; i < 4; ++i) {
        QAction* item = pcAction->addAction(QString());
        item->setCheckable(true);
        item->setIcon(BitmapFactory().iconFromTheme(icons[i]));
        item->setObjectName(QString::fromLatin1(names[i]));
        item->setWhatsThis(QString::fromLatin1(getWhatsThis()));
    }
    pcAction->setCheckedAction(1);  // shaded with edges is the default
    pcAction->setIcon(pcAction->actions()[1]->icon());

    _pcAction = pcAction;
    languageChange();
    return pcAction;
}

void StdCmdDisplayStyle::languageChange()
{
    Command::languageChange();

    auto pcAction = qobject_cast<ActionGroup*>(_pcAction);
    if (!pcAction) {
        return;
    }
    const QList<QAction*> items = pcAction->actions();
    if (items.size() < 4) {
        return;
    }
    items[0]->setText(QCoreApplication::translate("Std_DisplayStyle", "Shaded"));
    items[0]->setToolTip(QCoreApplication::translate("Std_DisplayStyle", "Faces without edge lines"));
    items[1]->setText(QCoreApplication::translate("Std_DisplayStyle", "Shaded with edges"));
    items[1]->setToolTip(QCoreApplication::translate("Std_DisplayStyle", "Faces and edge lines"));
    items[2]->setText(QCoreApplication::translate("Std_DisplayStyle", "Hidden edges visible"));
    items[2]->setToolTip(QCoreApplication::translate(
        "Std_DisplayStyle",
        "Faces and edge lines, and the edges behind faces drawn dashed and dim"
    ));
    items[3]->setText(QCoreApplication::translate("Std_DisplayStyle", "Wireframe"));
    items[3]->setToolTip(QCoreApplication::translate("Std_DisplayStyle", "Edge lines only"));
}

void StdCmdDisplayStyle::activated(int iMsg)
{
    if (iMsg < 0 || iMsg > 3) {
        return;
    }
    Gui::Document* doc = getActiveGuiDocument();
    if (!doc) {
        return;
    }

    displayParameters()->SetBool("ShowHiddenEdges", iMsg == hiddenEdgesStyle);

    // the first view sets the mode of the shapes, the others follow it
    bool first = true;
    for (MDIView* mdi : doc->getMDIViews()) {
        auto view = qobject_cast<View3DInventor*>(mdi);
        if (!view || !view->getViewer()) {
            continue;
        }
        if (first) {
            view->getViewer()->setOverrideMode(displayModes[iMsg]);
        }
        else {
            view->getViewer()->updateOverrideMode(displayModes[iMsg]);
        }
        first = false;
    }
    refreshDisplay();

    // isActive() ran before this with the old mode and put the check back on the old entry
    if (auto group = qobject_cast<ActionGroup*>(_pcAction)) {
        group->setCheckedAction(iMsg);
    }
}

bool StdCmdDisplayStyle::isActive()
{
    Gui::Document* doc = getActiveGuiDocument();
    if (!doc) {
        return false;
    }
    auto group = qobject_cast<ActionGroup*>(_pcAction);
    auto view = qobject_cast<View3DInventor*>(doc->getActiveView());
    if (group && view && view->getViewer()) {
        const std::string mode = view->getViewer()->getOverrideMode();
        const bool hidden = displayParameters()->GetBool("ShowHiddenEdges", false);
        int style = -1;
        if (mode == "Shaded") {
            style = 0;
        }
        else if (mode == "Wireframe") {
            style = 3;
        }
        else if (mode == "Flat Lines" || mode == "As Is") {
            style = hidden ? hiddenEdgesStyle : 1;
        }
        // another draw style (points, no shading, hidden line) leaves the menu as it was
        if (style >= 0 && group->checkedAction() != style) {
            group->setCheckedAction(style);
        }
    }
    return true;
}

DEF_STD_CMD_AC(StdCmdTangentEdges)

StdCmdTangentEdges::StdCmdTangentEdges()
    : Command("Std_TangentEdges")
{
    sGroup = "Standard-View";
    sMenuText = QT_TR_NOOP("&Tangent edges");
    sToolTipText = QT_TR_NOOP(
        "Shows the edges where two faces meet tangentially; hidden, only the creases remain"
    );
    sWhatsThis = "Std_TangentEdges";
    sStatusTip = sToolTipText;
    eType = Alter3DView;
}

Action* StdCmdTangentEdges::createAction()
{
    Action* pcAction = Command::createAction();
    pcAction->setCheckable(true);
    return pcAction;
}

void StdCmdTangentEdges::activated(int iMsg)
{
    displayParameters()->SetBool("ShowTangentEdges", iMsg == 1);
    refreshDisplay();
}

bool StdCmdTangentEdges::isActive()
{
    if (!getActiveGuiDocument()) {
        return false;
    }
    const bool shown = displayParameters()->GetBool("ShowTangentEdges", true);
    if (_pcAction && _pcAction->isChecked() != shown) {
        _pcAction->setBlockedChecked(shown);
    }
    return true;
}

//===========================================================================
// registration
//===========================================================================

namespace Gui
{
void CreateViewToolCommands()
{
    CommandManager& rcCmdMgr = Application::Instance->commandManager();
    rcCmdMgr.addCommand(new StdCmdSectionView());
    rcCmdMgr.addCommand(new StdCmdSaveNamedView());
    rcCmdMgr.addCommand(new StdCmdNamedViews());
    rcCmdMgr.addCommand(new StdCmdDisplayStyle());
    rcCmdMgr.addCommand(new StdCmdTangentEdges());
}
}  // namespace Gui
