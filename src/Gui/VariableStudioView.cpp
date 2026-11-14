// SPDX-License-Identifier: LGPL-2.1-or-later
/***************************************************************************
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 ***************************************************************************/

#include <cstring>

#include <QIcon>
#include <QPointer>
#include <QTimer>
#include <QVBoxLayout>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>

#include "BitmapFactory.h"
#include "Document.h"
#include "MainWindow.h"
#include "MenuManager.h"
#include "ToolBarManager.h"
#include "VariableStudioView.h"
#include "VariablesView.h"

using namespace Gui;

TYPESYSTEM_SOURCE_ABSTRACT(Gui::VariableStudioView, Gui::MDIView)

VariableStudioView::VariableStudioView(Gui::Document* doc, App::DocumentObject* obj, QWidget* parent)
    : MDIView(doc, parent)
    , studio(obj->getNameInDocument())
{
    setObjectName(QStringLiteral("VariableStudioView"));
    setAttribute(Qt::WA_DeleteOnClose);
    // The panel as a plain widget: no document of its own to attach to (the view is the one
    // attached), its rows the studio's
    auto central = new QWidget(this);
    auto layout = new QVBoxLayout(central);
    layout->setContentsMargins(0, 0, 0, 0);
    table = new DockWnd::VariablesView(nullptr, central, obj);
    table->setObjectName(QStringLiteral("VariableStudioTable"));
    layout->addWidget(table);
    setCentralWidget(central);
    setWindowIcon(QIcon(BitmapFactory().pixmap("VarSet")));
    updateTitle();

    // A relabel renames the window; the studio deleted (its tab, or the undo of its creation)
    // closes it, after the signal (the window is deleted on close)
    QPointer<VariableStudioView> self(this);
    auto& app = App::GetApplication();
    connections.emplace_back(app.signalChangedObject.connect(
        [this](const App::DocumentObject& changed, const App::Property& prop) {
            if (&prop == &changed.Label && changed.getDocument() == getAppDocument()
                && changed.isAttachedToDocument() && studio == changed.getNameInDocument()) {
                updateTitle();
            }
        }
    ));
    connections.emplace_back(app.signalDeletedObject.connect(
        [this, self](const App::DocumentObject& deleted) {
            if (deleted.getDocument() != getAppDocument()) {
                return;
            }
            const char* name = deleted.getNameInDocument();
            if (name && studio == name) {
                QTimer::singleShot(0, [self] {
                    if (self) {
                        self->deleteSelf();
                    }
                });
            }
        }
    ));
}

VariableStudioView::~VariableStudioView() = default;

void VariableStudioView::updateTitle()
{
    App::Document* doc = getAppDocument();
    App::DocumentObject* obj = doc ? doc->getObject(studio.c_str()) : nullptr;
    const QString label = obj ? QString::fromUtf8(obj->Label.getValue())
                              : QString::fromStdString(studio);
    setWindowTitle(
        doc ? QStringLiteral("%1 : %2").arg(QString::fromUtf8(doc->Label.getValue()), label)
            : label
    );
}

void VariableStudioView::onRelabel(Gui::Document*)
{
    updateTitle();
}

bool VariableStudioView::onMsg(const char* pMsg)
{
    Gui::Document* gdoc = getGuiDocument();
    if (!gdoc) {
        return false;
    }
    if (std::strcmp("Undo", pMsg) == 0) {
        gdoc->undo(1);
        return true;
    }
    if (std::strcmp("Redo", pMsg) == 0) {
        gdoc->redo(1);
        return true;
    }
    if (std::strcmp("Save", pMsg) == 0) {
        gdoc->save();
        return true;
    }
    if (std::strcmp("SaveAs", pMsg) == 0) {
        gdoc->saveAs();
        return true;
    }
    if (std::strcmp("SaveCopy", pMsg) == 0) {
        gdoc->saveCopy();
        return true;
    }
    return MDIView::onMsg(pMsg);
}

bool VariableStudioView::onHasMsg(const char* pMsg) const
{
    Gui::Document* gdoc = getGuiDocument();
    App::Document* doc = getAppDocument();
    if (!gdoc || !doc) {
        return false;
    }
    if (std::strcmp("Undo", pMsg) == 0) {
        return doc->getAvailableUndos() > 0;
    }
    if (std::strcmp("Redo", pMsg) == 0) {
        return doc->getAvailableRedos() > 0;
    }
    if (std::strcmp("Save", pMsg) == 0 || std::strcmp("SaveAs", pMsg) == 0
        || std::strcmp("SaveCopy", pMsg) == 0) {
        return true;
    }
    return MDIView::onHasMsg(pMsg);
}

VariableStudioView* VariableStudioView::find(Gui::Document* doc, const App::DocumentObject* obj)
{
    if (!doc || !obj || !obj->isAttachedToDocument()) {
        return nullptr;
    }
    for (auto view : doc->getMDIViewsOfType(VariableStudioView::getClassTypeId())) {
        auto studioView = static_cast<VariableStudioView*>(view);
        if (studioView->studio == obj->getNameInDocument()) {
            return studioView;
        }
    }
    return nullptr;
}

VariableStudioView* VariableStudioView::open(Gui::Document* doc, App::DocumentObject* obj)
{
    if (!doc || !obj || !obj->isAttachedToDocument() || obj->getDocument() != doc->getDocument()) {
        return nullptr;
    }
    VariableStudioView* view = find(doc, obj);
    if (!view) {
        view = new VariableStudioView(doc, obj, getMainWindow());
        getMainWindow()->addWindow(view);
    }
    getMainWindow()->setActiveWindow(view);
    return view;
}

// ---------------------------------------------------------------------------------------------

TYPESYSTEM_SOURCE(Gui::VariableStudioWorkbench, Gui::StdWorkbench)

VariableStudioWorkbench::VariableStudioWorkbench() = default;

VariableStudioWorkbench::~VariableStudioWorkbench() = default;

ToolBarItem* VariableStudioWorkbench::setupToolBars() const
{
    // The standard toolbars less those of a 3D view (View, Individual Views) and of the model
    // (Structure); Clipboard and Macro stay hidden as in StdWorkbench
    ToolBarItem* root = StdWorkbench::setupToolBars();
    for (const char* name : {"View", "Individual Views", "Structure"}) {
        if (ToolBarItem* item = root->findItem(name)) {
            root->removeItem(item);
            delete item;
        }
    }
    return root;
}

ToolBarItem* VariableStudioWorkbench::setupCommandBars() const
{
    return new ToolBarItem;
}

#include "moc_VariableStudioView.cpp"
