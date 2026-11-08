// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
 *                                                                          *
 *   This file is part of the FreeCAD CAx development system.               *
 *                                                                          *
 *   This library is free software; you can redistribute it and/or          *
 *   modify it under the terms of the GNU Library General Public            *
 *   License as published by the Free Software Foundation; either           *
 *   version 2 of the License, or (at your option) any later version.       *
 *                                                                          *
 *   This library  is distributed in the hope that it will be useful,       *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of         *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          *
 *   GNU Library General Public License for more details.                   *
 *                                                                          *
 *   You should have received a copy of the GNU Library General Public      *
 *   License along with this library; see the file COPYING.LIB. If not,     *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,          *
 *   Suite 330, Boston, MA  02111-1307, USA                                 *
 *                                                                          *
 ****************************************************************************/

#include <algorithm>
#include <cstring>
#include <map>
#include <set>
#include <vector>

#include <QAction>
#include <QApplication>
#include <QDockWidget>
#include <QInputDialog>
#include <QLineEdit>
#include <QMdiArea>
#include <QMdiSubWindow>
#include <QMenu>
#include <QMessageBox>
#include <QPointer>
#include <QTabBar>
#include <QTimer>
#include <QToolBar>
#include <QToolButton>

#include <CXX/Extensions.hxx>
#include <fastsignals/signal.h>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/DocumentObjectPy.h>
#include <App/DocumentPy.h>
#include <App/DocumentTabs.h>
#include <Base/Console.h>
#include <Base/Interpreter.h>

#include "DocumentTabBar.h"
#include "ActiveObjectList.h"
#include "Application.h"
#include "BitmapFactory.h"
#include "Command.h"
#include "Control.h"
#include "DockWindowManager.h"
#include "Document.h"
#include "ForkKeymap.h"
#include "MainWindow.h"
#include "MDIView.h"
#include "View3DInventor.h"
#include "View3DInventorViewer.h"
#include "ViewProviderDocumentObject.h"
#include "Workbench.h"
#include "WorkbenchManager.h"
#include "Selection/Selection.h"

using namespace Gui;
using Gui::DocumentTabs::accepts;
using Gui::DocumentTabs::isOn;
using Gui::DocumentTabs::tabOfView;
namespace AppTabs = App::DocumentTabs;

namespace
{

/// The Qt property holding a 3D view's tab name, on the MDI view and on its viewer
constexpr const char* tabProperty = "FreeCADCH_Tab";

bool is3DKind(AppTabs::Kind kind)
{
    return kind == AppTabs::Kind::PartStudio || kind == AppTabs::Kind::Assembly;
}

std::string tagOf(const QObject* object)
{
    if (!object) {
        return {};
    }
    const QVariant tag = object->property(tabProperty);
    return tag.isValid() ? tag.toByteArray().toStdString() : std::string();
}

/// The open dialog that blocks a switch, as Onshape asks to finish a feature first
bool dialogBlocks(std::string* refusal)
{
    if (!Control().activeDialog()) {
        return false;
    }
    if (refusal) {
        *refusal = QApplication::translate("DocumentTabs", "Finish or cancel the open dialog first")
                       .toStdString();
    }
    return true;
}

class Controller: public QObject
{
public:
    explicit Controller(MainWindow* mw);

    static Controller* instance()
    {
        return self;
    }

    void schedule(const App::Document* doc);
    void reconcile(App::Document* doc);
    void refreshBars();
    void applyKeymap();

    std::string activeTab(const App::Document* doc) const;
    bool switchTo(
        App::Document* doc,
        const std::string& name,
        bool sideEffects,
        std::string* refusal
    );
    MDIView* showTab(App::Document* doc, const AppTabs::Tab& tab);
    void setTag(MDIView* view, const std::string& tag);
    void refilter(MDIView* view);
    MDIView* viewOf(App::Document* doc, const std::string& name) const;

    std::string create(App::Document* doc, const std::string& kind);
    bool rename(App::Document* doc, const std::string& name, const std::string& text);
    bool remove(
        App::Document* doc,
        const std::string& name,
        bool force,
        std::string& message,
        std::vector<App::DocumentObject*>& users
    );

    void beforeUndo(Gui::Document* gdoc, bool undo);

    std::string pendingTab;  // the tab of the view createView() is making
    const App::Document* pendingDoc = nullptr;

private:
    void onViewActivated(QMdiSubWindow* window);
    void onCommit(const App::Document& doc);
    void onDeleteDocument(const App::Document& doc);
    void onTabClicked(int index);
    void onTabMenu(const QPoint& pos);
    void onDocumentClicked(int index);
    void onDocumentClose(int index);
    void renameInteractive(int index);
    void deleteInteractive(int index);
    void message(const std::string& text);

    static Controller* self;
    MainWindow* mw;
    QToolBar* strip;
    QTabBar* documents;
    QToolBar* bar;
    QTabBar* typed;
    QTimer timer;
    std::set<const App::Document*> dirty;
    std::map<const App::Document*, std::string> active;
    std::map<const App::Document*, std::map<int, std::string>> steps;
    struct PageView
    {
        QPointer<MDIView> view;
        const App::Document* doc;
        std::string name;
    };
    std::map<const MDIView*, PageView> pageViews;  // a drawing tab's view, by the page's name
    std::vector<fastsignals::scoped_connection> connections;
};

Controller* Controller::self = nullptr;

Controller::Controller(MainWindow* mw)
    : QObject(mw)
    , mw(mw)
{
    self = this;
    timer.setSingleShot(true);
    timer.setInterval(0);
    connect(&timer, &QTimer::timeout, this, [this] {
        auto docs = dirty;
        dirty.clear();
        for (auto doc : App::GetApplication().getDocuments()) {
            if (docs.count(doc)) {
                reconcile(doc);
            }
        }
        refreshBars();
    });

    // The document strip on top, its own toolbar row (like browser tabs)
    strip = new QToolBar(mw);
    strip->setObjectName(QStringLiteral("FreeCADCH_DocumentStrip"));
    strip->setWindowTitle(QApplication::translate("DocumentTabs", "Documents"));
    strip->setMovable(false);
    documents = new QTabBar(strip);
    documents->setObjectName(QStringLiteral("FreeCADCH_DocumentTabBar"));
    documents->setTabsClosable(true);
    documents->setExpanding(false);
    documents->setDocumentMode(true);
    strip->addWidget(documents);
    mw->addToolBarBreak(Qt::TopToolBarArea);
    mw->addToolBar(Qt::TopToolBarArea, strip);
    connect(documents, &QTabBar::tabBarClicked, this, &Controller::onDocumentClicked);
    connect(documents, &QTabBar::tabCloseRequested, this, &Controller::onDocumentClose);

    // The typed tabs along the bottom: [Tab manager] [+] then the tabs
    bar = new QToolBar(mw);
    bar->setObjectName(QStringLiteral("FreeCADCH_TypedTabs"));
    bar->setWindowTitle(QApplication::translate("DocumentTabs", "Tabs"));
    bar->setMovable(false);
    auto manager = new QToolButton(bar);
    manager->setObjectName(QStringLiteral("FreeCADCH_TabManager"));
    manager->setText(QStringLiteral("☰"));
    manager->setEnabled(false);
    manager->setToolTip(QApplication::translate("DocumentTabs", "Tab manager (Alt+T): not yet"));
    bar->addWidget(manager);
    auto plus = new QToolButton(bar);
    plus->setObjectName(QStringLiteral("FreeCADCH_NewTab"));
    plus->setText(QStringLiteral("+"));
    plus->setToolTip(QApplication::translate("DocumentTabs", "Insert new tab"));
    plus->setPopupMode(QToolButton::InstantPopup);
    auto menu = new QMenu(plus);
    const std::pair<const char*, const char*> kinds[] = {
        {QT_TRANSLATE_NOOP("DocumentTabs", "Create Part Studio"), "PartStudio"},
        {QT_TRANSLATE_NOOP("DocumentTabs", "Create Assembly"), "Assembly"},
        {QT_TRANSLATE_NOOP("DocumentTabs", "Create Drawing"), "Drawing"},
        {QT_TRANSLATE_NOOP("DocumentTabs", "Create Variable Studio"), "VariableStudio"},
    };
    for (const auto& [text, kind] : kinds) {
        QAction* action = menu->addAction(QApplication::translate("DocumentTabs", text));
        action->setObjectName(QStringLiteral("FreeCADCH_Create%1").arg(QLatin1String(kind)));
        const std::string kindName = kind;
        connect(action, &QAction::triggered, this, [this, kindName] {
            if (auto doc = App::GetApplication().getActiveDocument()) {
                create(doc, kindName);
            }
        });
    }
    plus->setMenu(menu);
    bar->addWidget(plus);
    typed = new QTabBar(bar);
    typed->setObjectName(QStringLiteral("FreeCADCH_TypedTabBar"));
    typed->setShape(QTabBar::RoundedSouth);
    typed->setExpanding(false);
    typed->setDocumentMode(true);
    typed->setContextMenuPolicy(Qt::CustomContextMenu);
    bar->addWidget(typed);
    mw->addToolBar(Qt::BottomToolBarArea, bar);
    connect(typed, &QTabBar::tabBarClicked, this, &Controller::onTabClicked);
    connect(typed, &QTabBar::tabBarDoubleClicked, this, &Controller::renameInteractive);
    connect(typed, &QTabBar::customContextMenuRequested, this, &Controller::onTabMenu);

    if (auto mdi = mw->findChild<QMdiArea*>()) {
        connect(mdi, &QMdiArea::subWindowActivated, this, &Controller::onViewActivated);
    }
    connect(mw, &MainWindow::workbenchActivated, this, [this] { applyKeymap(); });

    auto& app = App::GetApplication();
    connections.emplace_back(app.signalNewObject.connect([this](const App::DocumentObject& obj) {
        schedule(obj.getDocument());
    }));
    connections.emplace_back(
        app.signalDeletedObject.connect([this](const App::DocumentObject& obj) {
            schedule(obj.getDocument());
        })
    );
    connections.emplace_back(app.signalChangedObject.connect(
        [this](const App::DocumentObject& obj, const App::Property& prop) {
            const char* name = prop.getName();
            if (name
                && (std::strcmp(name, "Group") == 0 || std::strcmp(name, "Label") == 0
                    || std::strcmp(name, "Origin") == 0)) {
                schedule(obj.getDocument());
            }
        }
    ));
    connections.emplace_back(app.signalChangedDocument.connect(
        [this](const App::Document& doc, const App::Property& prop) {
            if (&prop == &doc.Meta || &prop == &doc.Label) {
                schedule(&doc);
            }
        }
    ));
    connections.emplace_back(
        app.signalFinishRestoreDocument.connect([this](const App::Document& doc) {
            schedule(&doc);
        })
    );
    connections.emplace_back(app.signalNewDocument.connect([this](const App::Document& doc, bool) {
        schedule(&doc);
    }));
    connections.emplace_back(app.signalActiveDocument.connect([this](const App::Document& doc) {
        schedule(&doc);
    }));
    connections.emplace_back(app.signalRelabelDocument.connect([this](const App::Document& doc) {
        schedule(&doc);
    }));
    connections.emplace_back(
        app.signalCommitTransaction.connect([this](const App::Document& doc) { onCommit(doc); })
    );
    connections.emplace_back(app.signalDeleteDocument.connect([this](const App::Document& doc) {
        onDeleteDocument(doc);
    }));
    applyKeymap();
}

void Controller::applyKeymap()
{
    const bool on = isOn();
    strip->setVisible(on);
    bar->setVisible(on);
    if (auto mdi = mw->findChild<QMdiArea*>()) {
        if (auto tabs = mdi->findChild<QTabBar*>(QStringLiteral("mdiAreaTabBar"))) {
            // A hidden tab bar still takes its height from the area (QMdiArea sizes the viewport by
            // its size hint): no height at all under the Onshape keymap
            const QString hidden = QStringLiteral(
                "QTabBar::tab { height: 0px; min-height: 0px; max-height: 0px; padding: 0px;"
                " margin: 0px; border: none; } QTabBar::close-button { width: 0px; height: 0px;"
                " image: none; } QTabBar::scroller { width: 0px; }"
            );
            tabs->setStyleSheet(on ? hidden : QString());
            tabs->setVisible(!on);
        }
    }
    if (on) {
        refreshBars();
    }
}

void Controller::schedule(const App::Document* doc)
{
    if (!isOn() || !doc) {
        return;
    }
    dirty.insert(doc);
    timer.start();
}

void Controller::onDeleteDocument(const App::Document& doc)
{
    dirty.erase(&doc);
    active.erase(&doc);
    steps.erase(&doc);
    for (auto it = pageViews.begin(); it != pageViews.end();) {
        it = it->second.doc == &doc || !it->second.view ? pageViews.erase(it) : std::next(it);
    }
    timer.start();
}

MDIView* Controller::viewOf(App::Document* doc, const std::string& name) const
{
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc) {
        return nullptr;
    }
    for (auto view : gdoc->getMDIViewsOfType(View3DInventor::getClassTypeId())) {
        if (tagOf(view) == name) {
            return view;
        }
    }
    for (const auto& entry : pageViews) {
        const PageView& page = entry.second;
        if (page.view && page.doc == doc && page.name == name) {
            return page.view.data();
        }
    }
    return nullptr;
}

void Controller::refilter(MDIView* view)
{
    auto view3d = qobject_cast<View3DInventor*>(view);
    auto gdoc = view3d ? view3d->getGuiDocument() : nullptr;
    if (!gdoc) {
        return;
    }
    View3DInventorViewer* viewer = view3d->getViewer();
    App::Document* doc = gdoc->getDocument();
    std::set<ViewProvider*> claimed;
    for (auto obj : doc->getObjects()) {
        if (auto vp = gdoc->getViewProvider(obj)) {
            for (auto child : vp->claimChildren3D()) {
                if (auto childVp = gdoc->getViewProvider(child)) {
                    claimed.insert(childVp);
                }
            }
        }
    }
    for (auto obj : doc->getObjects()) {
        auto vp = gdoc->getViewProvider(obj);
        if (!vp) {
            continue;
        }
        const bool want = !claimed.count(vp) && accepts(viewer, vp);
        const bool has = viewer->hasViewProvider(vp);
        if (want && !has) {
            viewer->addViewProvider(vp);
        }
        else if (!want && has && !claimed.count(vp)) {
            viewer->removeViewProvider(vp);
        }
    }
}

void Controller::setTag(MDIView* view, const std::string& tag)
{
    auto view3d = qobject_cast<View3DInventor*>(view);
    if (!view3d) {
        return;
    }
    const QByteArray value = QByteArray::fromStdString(tag);
    view3d->setProperty(tabProperty, value);
    view3d->getViewer()->setProperty(tabProperty, value);
    refilter(view3d);

    // The studio's App::Part is the view's active part, so a new Body lands in it; an active Body
    // of another tab is let go
    App::Document* doc = view3d->getAppDocument();
    App::DocumentObject* tabObject = doc ? doc->getObject(tag.c_str()) : nullptr;
    AppTabs::Kind kind {};
    const bool studio = tabObject && AppTabs::isTabObject(tabObject, &kind)
        && kind == AppTabs::Kind::PartStudio;
    auto part = view3d->getActiveObject<App::DocumentObject*>(PARTKEY);
    if (studio && part != tabObject) {
        view3d->setActiveObject(tabObject, PARTKEY);
    }
    else if (!studio && part && AppTabs::tabNameOf(part) != tag) {
        view3d->setActiveObject(nullptr, PARTKEY);
    }
    auto body = view3d->getActiveObject<App::DocumentObject*>(PDBODYKEY);
    if (body && AppTabs::tabNameOf(body) != tag) {
        view3d->setActiveObject(nullptr, PDBODYKEY);
    }
    if (doc && !active.count(doc)) {
        active[doc] = tag;
    }
}

void Controller::reconcile(App::Document* doc)
{
    auto gdoc = Application::Instance->getDocument(doc);
    if (!isOn() || !gdoc || doc->testStatus(App::Document::Restoring)) {
        return;
    }
    const auto tabs = AppTabs::tabs(doc);
    std::vector<std::string> names3d;
    std::set<std::string> names;
    for (const auto& tab : tabs) {
        names.insert(tab.name());
        if (is3DKind(tab.kind)) {
            names3d.push_back(tab.name());
        }
    }
    const auto views = gdoc->getMDIViewsOfType(View3DInventor::getClassTypeId());
    std::set<std::string> shown;
    for (auto view : views) {
        shown.insert(tagOf(view));
    }
    std::size_t kept = views.size();
    for (auto view : views) {
        const std::string tag = tagOf(view);
        if (!tag.empty() && names.count(tag)) {
            refilter(view);
            continue;
        }
        // Its tab is gone (deleted, or the implicit studio emptied): another tab with no view, or
        // the view goes when the document has others
        auto free = std::find_if(names3d.begin(), names3d.end(), [&shown](const std::string& n) {
            return !shown.count(n);
        });
        if (free != names3d.end()) {
            shown.insert(*free);
            setTag(view, *free);
        }
        else if (kept > 1) {
            --kept;
            QPointer<MDIView> doomed(view);
            QTimer::singleShot(0, this, [doomed] {
                if (doomed) {
                    doomed->deleteSelf();
                }
            });
        }
        else if (!names3d.empty()) {
            setTag(view, names3d.front());
        }
    }
    auto it = active.find(doc);
    if (it != active.end() && !names.count(it->second)) {
        auto current = gdoc->getActiveView();
        const std::string tag = tagOf(current);
        if (!tag.empty() && names.count(tag)) {
            it->second = tag;
        }
        else if (!names3d.empty()) {
            it->second = names3d.front();
        }
        else {
            active.erase(it);
        }
    }
}

void Controller::refreshBars()
{
    if (!isOn()) {
        return;
    }
    App::Document* activeDoc = App::GetApplication().getActiveDocument();

    // The documents
    QSignalBlocker blockDocuments(documents);
    std::vector<App::Document*> docs;
    for (auto doc : App::GetApplication().getDocuments()) {
        auto gdoc = Application::Instance->getDocument(doc);
        if (gdoc && !doc->testStatus(App::Document::TempDoc)
            && !doc->testStatus(App::Document::PartialDoc) && !gdoc->getMDIViews().empty()) {
            docs.push_back(doc);
        }
    }
    while (documents->count() > static_cast<int>(docs.size())) {
        documents->removeTab(documents->count() - 1);
    }
    for (std::size_t i = 0; i < docs.size(); ++i) {
        const QString text = QString::fromUtf8(docs[i]->Label.getValue());
        const QString name = QString::fromLatin1(docs[i]->getName());
        if (static_cast<int>(i) >= documents->count()) {
            documents->addTab(text);
        }
        documents->setTabText(static_cast<int>(i), text);
        documents->setTabData(static_cast<int>(i), name);
        if (docs[i] == activeDoc) {
            documents->setCurrentIndex(static_cast<int>(i));
        }
    }

    // The active document's typed tabs
    QSignalBlocker blockTyped(typed);
    std::vector<AppTabs::Tab> tabs;
    auto gdoc = activeDoc ? Application::Instance->getDocument(activeDoc) : nullptr;
    if (gdoc) {
        tabs = AppTabs::tabs(activeDoc);
    }
    while (typed->count() > static_cast<int>(tabs.size())) {
        typed->removeTab(typed->count() - 1);
    }
    const std::string current = activeTab(activeDoc);
    for (std::size_t i = 0; i < tabs.size(); ++i) {
        const int index = static_cast<int>(i);
        const QString text = QString::fromUtf8(AppTabs::label(activeDoc, tabs[i]).c_str());
        if (index >= typed->count()) {
            typed->addTab(text);
        }
        typed->setTabText(index, text);
        typed->setTabData(index, QString::fromStdString(tabs[i].name()));
        QIcon icon;
        if (auto vp = tabs[i].object ? gdoc->getViewProvider(tabs[i].object) : nullptr) {
            icon = vp->getIcon();
        }
        else {
            icon = BitmapFactory().iconFromTheme("Geofeaturegroup");
        }
        typed->setTabIcon(index, icon);
        if (tabs[i].name() == current) {
            typed->setCurrentIndex(index);
        }
    }
}

std::string Controller::activeTab(const App::Document* doc) const
{
    auto it = active.find(doc);
    return it == active.end() ? std::string() : it->second;
}

void Controller::onViewActivated(QMdiSubWindow* window)
{
    if (!isOn() || !window) {
        return;
    }
    auto view = qobject_cast<MDIView*>(window->widget());
    App::Document* doc = view ? view->getAppDocument() : nullptr;
    if (!doc) {
        return;
    }
    const std::string tag = tagOf(view);
    if (!tag.empty()) {
        active[doc] = tag;
    }
    else {
        auto page = pageViews.find(view);
        if (page != pageViews.end() && page->second.view) {
            active[doc] = page->second.name;
        }
    }
    timer.start();
}

void Controller::onCommit(const App::Document& doc)
{
    if (!isOn()) {
        return;
    }
    // The tab active at the commit, once per step (an empty commit that follows keeps the step's)
    const int id = doc.getTransactionID(true, 0);
    const std::string tab = activeTab(&doc);
    if (id != 0 && !tab.empty()) {
        steps[&doc].emplace(id, tab);
    }
}

void Controller::beforeUndo(Gui::Document* gdoc, bool undo)
{
    App::Document* doc = gdoc ? gdoc->getDocument() : nullptr;
    if (!doc) {
        return;
    }
    const int id = doc->getTransactionID(undo, 0);
    auto docSteps = steps.find(doc);
    if (id == 0 || docSteps == steps.end()) {
        return;
    }
    auto step = docSteps->second.find(id);
    if (step == docSteps->second.end() || step->second == activeTab(doc)) {
        return;
    }
    AppTabs::Tab tab {};
    if (AppTabs::findTab(doc, step->second, tab)) {
        switchTo(doc, step->second, true, nullptr);
    }
}

MDIView* Controller::showTab(App::Document* doc, const AppTabs::Tab& tab)
{
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc) {
        return nullptr;
    }
    const std::string name = tab.name();
    if (is3DKind(tab.kind)) {
        MDIView* view = viewOf(doc, name);
        if (!view) {
            pendingDoc = doc;
            pendingTab = name;
            view = gdoc->createView(View3DInventor::getClassTypeId());
            pendingDoc = nullptr;
            pendingTab.clear();
        }
        if (view) {
            getMainWindow()->setActiveWindow(view);
        }
        active[doc] = name;
        return view;
    }
    if (tab.kind == AppTabs::Kind::Drawing) {
        MDIView* view = viewOf(doc, name);
        if (view) {
            getMainWindow()->setActiveWindow(view);
        }
        else if (auto vp = gdoc->getViewProvider(tab.object)) {
            vp->show();  // the page's view (TechDraw's ViewProviderPage::show)
            view = getMainWindow()->activeWindow();
            if (view && view->getAppDocument() == doc && tagOf(view).empty()) {
                pageViews[view] = {QPointer<MDIView>(view), doc, name};
            }
        }
        active[doc] = name;
        return view;
    }
    // A Variable Studio: the Variables panel, the VarSet selected (design T5-a)
    if (auto dock = DockWindowManager::instance()->getDockWindow("Std_VariablesView")) {
        if (auto dockWidget = qobject_cast<QDockWidget*>(dock->parentWidget())) {
            dockWidget->show();
            dockWidget->raise();
        }
    }
    Selection().addSelection(doc->getName(), tab.object->getNameInDocument());
    active[doc] = name;
    return nullptr;
}

bool Controller::switchTo(
    App::Document* doc,
    const std::string& name,
    bool sideEffects,
    std::string* refusal
)
{
    AppTabs::Tab tab {};
    if (!doc || !AppTabs::findTab(doc, name, tab)) {
        if (refusal) {
            *refusal = "No such tab";
        }
        return false;
    }
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc) {
        return false;
    }
    const std::string before = activeTab(doc);
    if (sideEffects && name != before) {
        if (dialogBlocks(refusal)) {
            return false;
        }
        // Leaving a tab ends its edit (an active assembly)
        if (gdoc->getInEdit()) {
            gdoc->resetEdit();
        }
        Selection().clearSelection();
    }
    if (App::GetApplication().getActiveDocument() != doc) {
        App::GetApplication().setActiveDocument(doc);
    }
    showTab(doc, tab);
    if (sideEffects) {
        Workbench* workbench = WorkbenchManager::instance()->active();
        const std::string current = workbench ? workbench->name() : std::string();
        switch (tab.kind) {
            case AppTabs::Kind::PartStudio:
                if (current != "PartDesignWorkbench" && current != "SketcherWorkbench") {
                    Application::Instance->activateWorkbench("PartDesignWorkbench");
                }
                break;
            case AppTabs::Kind::Assembly:
                Application::Instance->activateWorkbench("AssemblyWorkbench");
                if (!gdoc->getInEdit()) {
                    if (auto vp = gdoc->getViewProvider(tab.object)) {
                        gdoc->setEdit(vp);
                    }
                }
                break;
            case AppTabs::Kind::Drawing:
                Application::Instance->activateWorkbench("TechDrawWorkbench");
                break;
            case AppTabs::Kind::VariableStudio:
                break;
        }
    }
    timer.start();
    return true;
}

std::string Controller::create(App::Document* doc, const std::string& kind)
{
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc || dialogBlocks(nullptr)) {
        return {};
    }
    const std::string after = activeTab(doc);
    std::set<std::string> before;
    for (const auto& tab : AppTabs::tabs(doc)) {
        before.insert(tab.name());
    }
    auto newTab = [&]() -> std::string {
        for (const auto& tab : AppTabs::tabs(doc)) {
            if (!before.count(tab.name())) {
                return tab.name();
            }
        }
        return {};
    };
    std::string name;
    if (kind == "PartStudio" || kind == "VariableStudio") {
        const bool studio = kind == "PartStudio";
        const std::string label
            = AppTabs::nextLabel(doc, studio ? "Part Studio" : "Variable Studio");
        gdoc->openCommand(
            studio ? QT_TRANSLATE_NOOP("Command", "Create Part Studio")
                   : QT_TRANSLATE_NOOP("Command", "Create Variable Studio")
        );
        App::DocumentObject* obj
            = doc->addObject(studio ? "App::Part" : "App::VarSet", studio ? "Part" : "VarSet");
        obj->Label.setValue(label);
        if (!studio) {
            AppTabs::setVariableStudio(obj, true);
        }
        gdoc->commitCommand();
        name = obj->getNameInDocument();
    }
    else if (kind == "Assembly") {
        // One root assembly per document, as upstream's EnforceOneAssemblyRule (on by default):
        // a document with two crashes after it is closed, with or without the tabs (ops#640
        // round 6), so Onshape's several assemblies wait for that fix
        auto assemblyPrefs = App::GetApplication().GetParameterGroupByPath(
            "User parameter:BaseApp/Preferences/Mod/Assembly"
        );
        const bool oneRule = assemblyPrefs->GetBool("EnforceOneAssemblyRule", true);
        const auto existing = AppTabs::tabs(doc);
        if (oneRule
            && std::any_of(existing.begin(), existing.end(), [](const AppTabs::Tab& t) {
                   return t.kind == AppTabs::Kind::Assembly;
               })) {
            message(
                QApplication::translate("DocumentTabs", "This document has its assembly already")
                    .toStdString()
            );
            return {};
        }
        if (gdoc->getInEdit()) {
            gdoc->resetEdit();  // an open assembly would take the new one in
        }
        Application::Instance->activateWorkbench("AssemblyWorkbench");
        Application::Instance->commandManager().runCommandByName("Assembly_CreateAssembly");
        name = newTab();
    }
    else if (kind == "Drawing") {
        Application::Instance->activateWorkbench("TechDrawWorkbench");
        Application::Instance->commandManager().runCommandByName("TechDraw_PageDefault");
        name = newTab();
    }
    if (name.empty()) {
        return {};
    }
    AppTabs::placeAfter(doc, name, after);
    AppTabs::Tab tab {};
    if (AppTabs::findTab(doc, name, tab)) {
        if (tab.kind == AppTabs::Kind::Drawing) {
            // The command opened the page's view
            MDIView* view = getMainWindow()->activeWindow();
            if (view && view->getAppDocument() == doc && tagOf(view).empty()) {
                pageViews[view] = {QPointer<MDIView>(view), doc, name};
            }
            active[doc] = name;
        }
        else if (tab.kind == AppTabs::Kind::Assembly && viewOf(doc, name)) {
            active[doc] = name;  // the command's setEdit opened it in its own view
        }
        else {
            switchTo(doc, name, true, nullptr);
        }
    }
    timer.start();
    return name;
}

bool Controller::rename(App::Document* doc, const std::string& name, const std::string& text)
{
    AppTabs::Tab tab {};
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc || text.empty() || !AppTabs::findTab(doc, name, tab)) {
        return false;
    }
    if (tab.object) {
        gdoc->openCommand(QT_TRANSLATE_NOOP("Command", "Rename tab"));
        tab.object->Label.setValue(text);
        gdoc->commitCommand();
    }
    else {
        AppTabs::setImplicitLabel(doc, text);
    }
    timer.start();
    return true;
}

bool Controller::remove(
    App::Document* doc,
    const std::string& name,
    bool force,
    std::string& text,
    std::vector<App::DocumentObject*>& users
)
{
    AppTabs::Tab tab {};
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc || !AppTabs::findTab(doc, name, tab)) {
        text = "No such tab";
        return false;
    }
    const auto tabs = AppTabs::tabs(doc);
    const auto studios = std::count_if(tabs.begin(), tabs.end(), [](const AppTabs::Tab& t) {
        return t.kind == AppTabs::Kind::PartStudio;
    });
    if (tab.kind == AppTabs::Kind::PartStudio && studios <= 1) {
        text = QApplication::translate("DocumentTabs", "The last Part Studio can't be deleted")
                   .toStdString();
        return false;
    }
    if (dialogBlocks(&text)) {
        return false;
    }
    users = AppTabs::dependents(doc, tab);
    if (!users.empty() && !force) {
        std::string list;
        for (auto user : users) {
            list += std::string(list.empty() ? "" : ", ") + user->Label.getValue();
        }
        text = QApplication::translate("DocumentTabs", "%1 is used by: %2")
                   .arg(
                       QString::fromStdString(AppTabs::label(doc, tab)),
                       QString::fromStdString(list)
                   )
                   .toStdString();
        return false;
    }
    // The neighbour shown after the delete when the tab is the active one
    std::string next;
    for (std::size_t i = 0; i < tabs.size(); ++i) {
        if (tabs[i].name() == name) {
            const std::size_t j = i > 0 ? i - 1 : i + 1;
            if (j < tabs.size()) {
                next = tabs[j].name();
            }
        }
    }
    const bool wasActive = activeTab(doc) == name;
    if (gdoc->getInEdit()) {
        gdoc->resetEdit();
    }
    const std::string title = "Delete " + AppTabs::label(doc, tab);
    gdoc->openCommand(title.c_str());
    AppTabs::removeTab(doc, tab);
    gdoc->commitCommand();
    reconcile(doc);
    if (wasActive && !next.empty()) {
        switchTo(doc, next, true, nullptr);
    }
    timer.start();
    return true;
}

void Controller::message(const std::string& text)
{
    if (!text.empty()) {
        mw->showMessage(QString::fromStdString(text), 4000);
    }
}

void Controller::onTabClicked(int index)
{
    App::Document* doc = App::GetApplication().getActiveDocument();
    if (!doc || index < 0) {
        return;
    }
    std::string refusal;
    if (!switchTo(doc, typed->tabData(index).toString().toStdString(), true, &refusal)) {
        message(refusal);
    }
    timer.start();  // after the click: the bar back on the active tab when refused
}

void Controller::onTabMenu(const QPoint& pos)
{
    const int index = typed->tabAt(pos);
    if (index < 0) {
        return;
    }
    QMenu menu;
    QAction* renameAction = menu.addAction(QApplication::translate("DocumentTabs", "Rename"));
    QAction* deleteAction = menu.addAction(QApplication::translate("DocumentTabs", "Delete"));
    QAction* chosen = menu.exec(typed->mapToGlobal(pos));
    if (chosen == renameAction) {
        renameInteractive(index);
    }
    else if (chosen == deleteAction) {
        deleteInteractive(index);
    }
}

void Controller::renameInteractive(int index)
{
    App::Document* doc = App::GetApplication().getActiveDocument();
    if (!doc || index < 0) {
        return;
    }
    bool ok = false;
    const QString text = QInputDialog::getText(
        mw,
        QApplication::translate("DocumentTabs", "Rename"),
        QApplication::translate("DocumentTabs", "Name:"),
        QLineEdit::Normal,
        typed->tabText(index),
        &ok
    );
    if (ok && !text.trimmed().isEmpty()) {
        rename(doc, typed->tabData(index).toString().toStdString(), text.trimmed().toStdString());
    }
}

void Controller::deleteInteractive(int index)
{
    App::Document* doc = App::GetApplication().getActiveDocument();
    if (!doc || index < 0) {
        return;
    }
    const std::string name = typed->tabData(index).toString().toStdString();
    std::string text;
    std::vector<App::DocumentObject*> users;
    if (remove(doc, name, false, text, users)) {
        return;
    }
    if (users.empty()) {
        QMessageBox::information(
            mw,
            QApplication::translate("DocumentTabs", "Delete"),
            QString::fromStdString(text)
        );
        return;
    }
    // Onshape's Delete dialog: what would break, and the choice
    const auto answer = QMessageBox::question(
        mw,
        QApplication::translate("DocumentTabs", "Delete"),
        QString::fromStdString(text) + QStringLiteral("\n\n")
            + QApplication::translate("DocumentTabs", "Delete the tab anyway?")
    );
    if (answer == QMessageBox::Yes) {
        remove(doc, name, true, text, users);
    }
}

void Controller::onDocumentClicked(int index)
{
    if (index < 0) {
        return;
    }
    const std::string name = documents->tabData(index).toString().toStdString();
    App::Document* doc = App::GetApplication().getDocument(name.c_str());
    auto gdoc = doc ? Application::Instance->getDocument(doc) : nullptr;
    if (!gdoc) {
        return;
    }
    MDIView* view = viewOf(doc, activeTab(doc));
    if (!view) {
        view = gdoc->getActiveView();
    }
    if (view) {
        getMainWindow()->setActiveWindow(view);
    }
}

void Controller::onDocumentClose(int index)
{
    const std::string name = documents->tabData(index).toString().toStdString();
    App::Document* doc = App::GetApplication().getDocument(name.c_str());
    auto gdoc = doc ? Application::Instance->getDocument(doc) : nullptr;
    if (gdoc && gdoc->canClose()) {
        App::GetApplication().closeDocument(name.c_str());
    }
}

// -- Python: FreeCADGui.DocumentTabs ------------------------------------------------------------

App::Document* documentArg(PyObject* arg)
{
    if (!PyObject_TypeCheck(arg, &App::DocumentPy::Type)) {
        throw Py::TypeError("expected a document");
    }
    return static_cast<App::DocumentPy*>(arg)->getDocumentPtr();
}

Controller& controller()
{
    if (!Controller::instance()) {
        throw Py::RuntimeError("no main window");
    }
    return *Controller::instance();
}

class Module: public Py::ExtensionModule<Module>  // NOLINT
{
public:
    Module()
        : Py::ExtensionModule<Module>("DocumentTabs")
    {
        add_varargs_method(
            "isOn",
            &Module::pyIsOn,
            "isOn() -> whether the typed tabs are on (the Onshape keymap)"
        );
        add_varargs_method(
            "activeTab",
            &Module::pyActiveTab,
            "activeTab(doc) -> the active tab's name"
        );
        add_varargs_method(
            "switchTo",
            &Module::pySwitchTo,
            "switchTo(doc, name) -> (switched, refusal), as a click on the tab"
        );
        add_varargs_method(
            "create",
            &Module::pyCreate,
            "create(doc, kind) -> the new tab's name; kind PartStudio, Assembly, Drawing or\n"
            "VariableStudio, as the '+' menu"
        );
        add_varargs_method(
            "rename",
            &Module::pyRename,
            "rename(doc, name, label), as the tab menu's Rename"
        );
        add_varargs_method(
            "deleteTab",
            &Module::pyDelete,
            "deleteTab(doc, name, force=False) -> (deleted, message, users), as the tab\n"
            "menu's Delete"
        );
        add_varargs_method(
            "viewOf",
            &Module::pyViewOf,
            "viewOf(doc, name) -> the tab's view, or None"
        );
        add_varargs_method(
            "tabOfView",
            &Module::pyTabOfView,
            "tabOfView(view) -> the tab a 3D view shows"
        );
        add_varargs_method(
            "reconcile",
            &Module::pyReconcile,
            "reconcile(doc): the views and bars, now"
        );
        initialize("Onshape's typed tabs in the GUI (FreeCAD-CH)");
    }

private:
    Py::Object pyIsOn(const Py::Tuple& /*args*/)
    {
        return Py::Boolean(DocumentTabs::isOn());
    }
    Py::Object pyActiveTab(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyDoc)) {
            throw Py::Exception();
        }
        return Py::String(controller().activeTab(documentArg(pyDoc)));
    }
    Py::Object pySwitchTo(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        std::string refusal;
        const bool done = controller().switchTo(documentArg(pyDoc), name, true, &refusal);
        controller().refreshBars();
        Py::Tuple result(2);
        result.setItem(0, Py::Boolean(done));
        result.setItem(1, Py::String(refusal));
        return result;
    }
    Py::Object pyCreate(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* kind = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &kind)) {
            throw Py::Exception();
        }
        const std::string name = controller().create(documentArg(pyDoc), kind);
        controller().refreshBars();
        return Py::String(name);
    }
    Py::Object pyRename(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        const char* text = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Oss", &pyDoc, &name, &text)) {
            throw Py::Exception();
        }
        const bool done = controller().rename(documentArg(pyDoc), name, text);
        controller().refreshBars();
        return Py::Boolean(done);
    }
    Py::Object pyDelete(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        PyObject* force = Py_False;
        if (!PyArg_ParseTuple(args.ptr(), "Os|O!", &pyDoc, &name, &PyBool_Type, &force)) {
            throw Py::Exception();
        }
        std::string text;
        std::vector<App::DocumentObject*> users;
        const bool done
            = controller().remove(documentArg(pyDoc), name, force == Py_True, text, users);
        controller().refreshBars();
        Py::List list;
        for (auto user : users) {
            list.append(Py::asObject(user->getPyObject()));
        }
        Py::Tuple result(3);
        result.setItem(0, Py::Boolean(done));
        result.setItem(1, Py::String(text));
        result.setItem(2, list);
        return result;
    }
    Py::Object pyViewOf(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        MDIView* view = controller().viewOf(documentArg(pyDoc), name);
        return view ? Py::asObject(view->getPyObject()) : Py::None();
    }
    Py::Object pyTabOfView(const Py::Tuple& args)
    {
        PyObject* pyView = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyView)) {
            throw Py::Exception();
        }
        // The view's Python object: find the MDI view whose object it is
        for (auto doc : App::GetApplication().getDocuments()) {
            auto gdoc = Application::Instance->getDocument(doc);
            if (!gdoc) {
                continue;
            }
            for (auto view : gdoc->getMDIViews()) {
                PyObject* object = view->getPyObject();
                const bool same = object == pyView;
                Py_DECREF(object);
                if (same) {
                    return Py::String(tabOfView(view));
                }
            }
        }
        return Py::String("");
    }
    Py::Object pyReconcile(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pyDoc)) {
            throw Py::Exception();
        }
        controller().reconcile(documentArg(pyDoc));
        controller().refreshBars();
        return Py::None();
    }
};

}  // namespace

bool DocumentTabs::isOn()
{
    return ForkKeymap::isOnshape();
}

bool DocumentTabs::accepts(const View3DInventorViewer* viewer, const ViewProvider* vp)
{
    const std::string tag = viewer ? tagOf(viewer) : std::string();
    if (tag.empty()) {
        return true;
    }
    auto vpd = dynamic_cast<const ViewProviderDocumentObject*>(vp);
    App::DocumentObject* obj = vpd ? vpd->getObject() : nullptr;
    if (!obj || !obj->isAttachedToDocument()) {
        return true;
    }
    return AppTabs::tabNameOf(obj) == tag;
}

std::string DocumentTabs::tabOfView(const MDIView* view)
{
    return tagOf(view);
}

void DocumentTabs::viewCreated(Gui::Document* gdoc, MDIView* view)
{
    Controller* ctl = Controller::instance();
    if (!isOn() || !ctl || !gdoc || !qobject_cast<View3DInventor*>(view)) {
        return;
    }
    App::Document* doc = gdoc->getDocument();
    std::string tag;
    if (ctl->pendingDoc == doc && !ctl->pendingTab.empty()) {
        tag = ctl->pendingTab;
    }
    else {
        // A further view of the active tab (a clone for undocking, Std_ViewCreate), else the first
        tag = tabOfView(gdoc->getActiveView());
        if (tag.empty()) {
            tag = ctl->activeTab(doc);
        }
        AppTabs::Tab tab {};
        if (tag.empty() || !AppTabs::findTab(doc, tag, tab) || !is3DKind(tab.kind)) {
            tag.clear();
            for (const auto& candidate : AppTabs::tabs(doc)) {
                if (is3DKind(candidate.kind)) {
                    tag = candidate.name();
                    break;
                }
            }
        }
    }
    if (!tag.empty()) {
        ctl->setTag(view, tag);
    }
}

void DocumentTabs::beforeUndo(Gui::Document* gdoc, bool undo)
{
    if (isOn() && Controller::instance()) {
        Controller::instance()->beforeUndo(gdoc, undo);
    }
}

void DocumentTabs::beforeEdit(Gui::Document* gdoc, ViewProvider* vp)
{
    Controller* ctl = Controller::instance();
    auto vpd = dynamic_cast<ViewProviderDocumentObject*>(vp);
    App::DocumentObject* obj = vpd ? vpd->getObject() : nullptr;
    if (!isOn() || !ctl || !gdoc || !obj || !obj->isAttachedToDocument()) {
        return;
    }
    App::Document* doc = gdoc->getDocument();
    const std::string name = AppTabs::tabNameOf(obj);
    AppTabs::Tab tab {};
    if (!AppTabs::findTab(doc, name, tab) || !is3DKind(tab.kind)) {
        return;
    }
    const std::string current = tabOfView(gdoc->getActiveView());
    if (current != name) {
        ctl->showTab(doc, tab);
    }
}

void DocumentTabs::newDocumentStudio(App::Document* doc)
{
    if (!isOn() || !doc || !doc->getObjects().empty()) {
        return;
    }
    // No undo step: a new document starts with its studio, as in Onshape
    App::DocumentObject* part = doc->addObject("App::Part", "Part");
    part->Label.setValue(AppTabs::nextLabel(doc, "Part Studio"));
    if (auto ctl = Controller::instance()) {
        ctl->reconcile(doc);
        ctl->refreshBars();
    }
    if (auto gdoc = Application::Instance->getDocument(doc)) {
        gdoc->setModified(false);
    }
}

std::string DocumentTabs::activeTab(const App::Document* doc)
{
    return Controller::instance() ? Controller::instance()->activeTab(doc) : std::string();
}

bool DocumentTabs::switchTo(App::Document* doc, const std::string& name, std::string* refusal)
{
    return Controller::instance() && Controller::instance()->switchTo(doc, name, true, refusal);
}

void DocumentTabs::setup(MainWindow* mw)
{
    if (!Controller::instance()) {
        new Controller(mw);
    }
}

PyObject* DocumentTabs::pythonModule()
{
    return Base::Interpreter().addModule(new Module);
}
