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
#include <QComboBox>
#include <QDialog>
#include <QDockWidget>
#include <QFile>
#include <QFileInfo>
#include <QInputDialog>
#include <QKeyEvent>
#include <QLineEdit>
#include <QListWidget>
#include <QVBoxLayout>
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
#include <App/GeoFeature.h>
#include <App/PropertyLinks.h>
#include <App/Link.h>
#include <App/VarSet.h>
#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Base/Parameter.h>
#include <Base/Tools.h>

#include "DocumentTabBar.h"
#include "VariableStudioView.h"
#include "ActiveObjectList.h"
#include "Application.h"
#include "BitmapFactory.h"
#include "Command.h"
#include "Control.h"
#include "DockWindowManager.h"
#include "Document.h"
#include "FileDialog.h"
#include "ForkKeymap.h"
#include "MainWindow.h"
#include "MDIView.h"
#include "View3DInventor.h"
#include "View3DInventorViewer.h"
#include "ViewProviderDocumentObject.h"
#include "Workbench.h"
#include "WorkbenchManager.h"
#include "Selection/Selection.h"
#include "ToolBarManager.h"

namespace Gui::DocumentTabs
{
// F6-3: also declared in Document.cpp, its caller (no header names it)
bool undoAllowed(Gui::Document* gdoc, bool undo);
}  // namespace Gui::DocumentTabs

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

/// A tab's icon: its object's, the group icon for the implicit studio
QIcon tabIcon(Gui::Document* gdoc, const AppTabs::Tab& tab)
{
    if (auto vp = gdoc && tab.object ? gdoc->getViewProvider(tab.object) : nullptr) {
        return vp->getIcon();
    }
    return BitmapFactory().iconFromTheme("Geofeaturegroup");
}

/** Onshape's Tab manager (Alt+T, the bar's leftmost button; slice 2): the active document's tabs
 * with a search box and a type filter. Double-click or Enter opens a tab and closes the manager
 * [guess]; Enter in the search box opens the first match. A drag reorders the tabs: the order is
 * the bar's, saved, no undo step. No thumbnails.
 */
class TabManager: public QDialog
{
public:
    explicit TabManager(QWidget* parent);

    /// The active document's tabs, the active one current
    void populate();

private:
    void applyFilter();
    void openTab(QListWidgetItem* item);
    void openFirst();
    void scheduleOrder();
    void saveOrder();

    QLineEdit* search;
    QComboBox* filter;
    QListWidget* list;
    std::string docName;
    bool populating = false;
    bool orderPending = false;
};

class Controller: public QObject, public ParameterGrp::ObserverType
{
public:
    explicit Controller(MainWindow* mw);
    ~Controller() override;

    static Controller* instance()
    {
        return self;
    }

    /// The keymap preference: ShortcutManager's reload() may run after this, so it is read later
    void OnChange(Base::Subject<const char*>& caller, const char* reason) override;
    void keymapChanged();

    void schedule(const App::Document* doc);
    void reconcile(App::Document* doc);
    void refreshBars();
    void applyKeymap();
    void placeStrip();
    void sizeButtons();

    /// The kind rule behind DocumentTabs::allowsWorkbench()
    bool allowsWorkbench(const std::string& name, std::string* refusal) const;

    std::string activeTab(const App::Document* doc) const;
    bool switchTo(
        App::Document* doc,
        const std::string& name,
        bool sideEffects,
        std::string* refusal
    );
    MDIView* showTab(App::Document* doc, const AppTabs::Tab& tab);
    MDIView* viewForTab(App::Document* doc, const AppTabs::Tab& tab);
    bool beforeEdit(Gui::Document* gdoc, App::DocumentObject* obj);
    void setTag(MDIView* view, const std::string& tag);
    void keepImplicit(App::Document* doc);
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

    bool beforeUndo(Gui::Document* gdoc, bool undo);
    void message(const std::string& text);

    // Slice 2: the tab menu's Duplicate and Export, the Tab manager, the bar's drag
    std::string duplicate(App::Document* doc, const std::string& name, std::string& refusal);
    void nameCopiedParts(App::Document* doc, App::DocumentObject* copy);
    bool exportTab(
        App::Document* doc,
        const std::string& name,
        const std::string& path,
        std::string& error
    );
    void exportAllInteractive(int index);
    bool exportAllDrawings(App::Document* doc, const std::string& path, std::string& error);
    bool writeDrawings(
        const std::vector<App::DocumentObject*>& pages,
        const std::string& path,
        const char* function,
        std::string& error
    );
    bool openManager();
    void saveBarOrder();

    /// Alt+T, the Tab manager's key under the Onshape keymap: before the menu bar's mnemonic
    bool eventFilter(QObject* watched, QEvent* event) override;

    std::string pendingTab;  // the tab of the view createView() is making
    const App::Document* pendingDoc = nullptr;
    QTabBar* typedBar() const
    {
        return typed;
    }

private:
    void leave(Gui::Document* gdoc);
    void arrive(App::Document* doc, const AppTabs::Tab& tab);
    void onViewActivated(QMdiSubWindow* window);
    void activatedElsewhere(App::Document* doc, const std::string& before, const std::string& tag);
    void onCommit(const App::Document& doc);
    void onDeleteDocument(const App::Document& doc);
    void onTabClicked(int index);
    void onTabMenu(const QPoint& pos);
    void onDocumentClicked(int index);
    void onDocumentClose(int index);
    void renameInteractive(int index);
    void deleteInteractive(int index);
    void duplicateInteractive(int index);
    void exportInteractive(int index);

    static Controller* self;
    QPointer<TabManager> manager;
    MainWindow* mw;
    bool wasOn = false;
    bool arriving = false;
    bool removingTab = false;  // remove()'s deletes, which take the tab away
    QToolBar* strip;
    QTabBar* documents;
    QToolBar* bar;
    QTabBar* typed;
    QToolButton* managerButton = nullptr;
    QToolButton* plusButton = nullptr;
    bool selectorHidden = false;  // applyKeymap() hid the Workbench toolbar
    bool stripPlaced = false;  // placeStrip() has put the strip first once
    QTimer timer;
    std::set<const App::Document*> dirty;
    std::set<const App::Document*> closing;  // their views go: an activation meanwhile is no switch
    std::map<const App::Document*, std::string> active;
    std::map<const App::Document*, std::map<int, std::string>> steps;
    std::map<const App::Document*, std::string> showAfter;  // a tab an undo or redo brings back
    void stepApplied(const App::Document& doc);

public:
    /// The tab a document being opened was saved on, shown when its restore finishes (ops#710)
    std::map<const App::Document*, std::string> restoredTab;
    void restoreFinished(const App::Document& doc);
    void applyRestoredTab(const std::string& docName);

private:
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
    wasOn = isOn();
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
    mw->addToolBar(Qt::TopToolBarArea, strip);
    placeStrip();
    connect(documents, &QTabBar::tabBarClicked, this, &Controller::onDocumentClicked);
    connect(documents, &QTabBar::tabCloseRequested, this, &Controller::onDocumentClose);

    // The typed tabs along the bottom: [Tab manager] [+] then the tabs
    bar = new QToolBar(mw);
    bar->setObjectName(QStringLiteral("FreeCADCH_TypedTabs"));
    bar->setWindowTitle(QApplication::translate("DocumentTabs", "Tabs"));
    bar->setMovable(false);
    managerButton = new QToolButton(bar);
    managerButton->setObjectName(QStringLiteral("FreeCADCH_TabManager"));
    managerButton->setText(QStringLiteral("☰"));
    managerButton->setToolTip(QApplication::translate("DocumentTabs", "Tab manager (Alt+T)"));
    connect(managerButton, &QToolButton::clicked, this, [this] { openManager(); });
    bar->addWidget(managerButton);
    auto plus = new QToolButton(bar);
    plusButton = plus;
    plus->setObjectName(QStringLiteral("FreeCADCH_NewTab"));
    plus->setText(QStringLiteral("+"));
    plus->setToolTip(QApplication::translate(
        "DocumentTabs",
        "Insert a Part Studio, Assembly, Drawing or Variable Studio"
    ));
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
    typed->setMovable(true);  // a drag reorders the tabs, saved, no undo step [guess]
    bar->addWidget(typed);
    mw->addToolBar(Qt::BottomToolBarArea, bar);
    sizeButtons();
    connect(typed, &QTabBar::tabMoved, this, [this](int, int) { saveBarOrder(); });
    connect(typed, &QTabBar::tabBarClicked, this, &Controller::onTabClicked);
    connect(typed, &QTabBar::tabBarDoubleClicked, this, &Controller::renameInteractive);
    connect(typed, &QTabBar::customContextMenuRequested, this, &Controller::onTabMenu);

    if (auto mdi = mw->findChild<QMdiArea*>()) {
        connect(mdi, &QMdiArea::subWindowActivated, this, &Controller::onViewActivated);
    }
    connect(mw, &MainWindow::workbenchActivated, this, [this] { applyKeymap(); });

    auto& app = App::GetApplication();
    connections.emplace_back(app.signalNewObject.connect([this](const App::DocumentObject& obj) {
        // A Variable Studio's mark outlives its VarSet (for the delete's undo); a new VarSet that
        // reuses the name isn't one (R6T-8), nor a new copy, which starts with no source (ops#726)
        App::Document* doc = obj.getDocument();
        if (doc && obj.isDerivedFrom<App::VarSet>()
            && !doc->isPerformingTransaction() && !doc->testStatus(App::Document::Restoring)
            && !doc->testStatus(App::Document::Importing) && AppTabs::isVariableStudio(&obj)) {
            AppTabs::setVariableStudio(const_cast<App::DocumentObject*>(&obj), false);
        }
        schedule(doc);
    }));
    connections.emplace_back(
        app.signalDeletedObject.connect([this](const App::DocumentObject& obj) {
            App::Document* doc = obj.getDocument();
            // F6-2: the user deletes from the implicit studio shown: it keeps its tab when
            // emptied (R6T-12), its label stored now, while the object is still there; not
            // for an undo or redo (an undone import), a tab's own delete or a closing document
            if (isOn() && doc && !removingTab && !closing.count(doc)
                && !doc->isPerformingTransaction() && !doc->testStatus(App::Document::Restoring)
                && (obj.isDerivedFrom<App::GeoFeature>()
                    || obj.hasExtension(App::LinkBaseExtension::getExtensionClassTypeId()))
                && AppTabs::tabNameOf(&obj) == AppTabs::implicitName()
                && viewOf(doc, AppTabs::implicitName())) {
                keepImplicit(doc);
            }
            schedule(doc);
        })
    );
    connections.emplace_back(app.signalChangedObject.connect(
        [this](const App::DocumentObject& obj, const App::Property& prop) {
            const char* name = prop.getName();
            if (name
                && (std::strcmp(name, "Group") == 0 || std::strcmp(name, "Label") == 0
                    || std::strcmp(name, "Origin") == 0
                    // a copy's Detach, or its undo, makes it a tab or not (ops#726)
                    || std::strcmp(name, "SourceKind") == 0)) {
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
            restoreFinished(doc);
        })
    );
    connections.emplace_back(app.signalNewDocument.connect([this](const App::Document& doc, bool) {
        closing.erase(&doc);  // a new document where a closed one was
        schedule(&doc);
    }));
    // Before the GUI document deletes its views: the next view activated while they go (another
    // tab's) must not reset or start an edit of the closing document
    connections.emplace_back(
        Application::Instance->signalDeleteDocument.connect([this](const Gui::Document& gdoc) {
            if (App::Document* doc = gdoc.getDocument()) {
                closing.insert(doc);
                onDeleteDocument(*doc);
            }
        })
    );
    connections.emplace_back(app.signalActiveDocument.connect([this](const App::Document& doc) {
        schedule(&doc);
        restoreFinished(doc);  // a document restored in the background shows its tab when shown
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
    connections.emplace_back(
        app.signalUndoDocument.connect([this](const App::Document& doc) { stepApplied(doc); })
    );
    connections.emplace_back(
        app.signalRedoDocument.connect([this](const App::Document& doc) { stepApplied(doc); })
    );
    ForkKeymap::preferenceGroup()->Attach(this);
    qApp->installEventFilter(this);
    applyKeymap();
}

Controller::~Controller()
{
    qApp->removeEventFilter(this);
    ForkKeymap::preferenceGroup()->Detach(this);
    if (self == this) {
        self = nullptr;
    }
}

void Controller::OnChange(Base::Subject<const char*>& /*caller*/, const char* reason)
{
    if (!reason || !*reason || std::strcmp(reason, "Keymap") == 0) {
        QTimer::singleShot(0, this, [this] { keymapChanged(); });
    }
}

void Controller::keymapChanged()
{
    // A switch at runtime (Preferences > General): FreeCAD's keymap shows every object in every
    // view and no bars; Onshape's tags and filters the open views again (R6T-4)
    const bool on = isOn();
    if (on == wasOn) {
        return;
    }
    wasOn = on;
    for (auto doc : App::GetApplication().getDocuments()) {
        auto gdoc = Application::Instance->getDocument(doc);
        if (!gdoc) {
            continue;
        }
        if (on) {
            // The untagged views take the 3D tabs in order (reconcile()); the active one's is the
            // active tab
            active.erase(doc);
            reconcile(doc);
            const std::string tag = tagOf(gdoc->getActiveView());
            if (!tag.empty()) {
                active[doc] = tag;
            }
            continue;
        }
        for (auto view : gdoc->getMDIViewsOfType(View3DInventor::getClassTypeId())) {
            if (auto view3d = qobject_cast<View3DInventor*>(view)) {
                view3d->setProperty(tabProperty, QVariant());
                view3d->getViewer()->setProperty(tabProperty, QVariant());
                refilter(view3d);
            }
        }
    }
    if (!on) {
        dirty.clear();
        active.clear();
        steps.clear();
        showAfter.clear();
        pageViews.clear();
    }
    applyKeymap();
}

void Controller::applyKeymap()
{
    const bool on = isOn();
    strip->setVisible(on);
    bar->setVisible(on);
    if (on) {
        placeStrip();
        sizeButtons();
    }
    // A tab's kind fixes its tools: no workbench selector under the Onshape keymap (the toolbar is
    // made hidden and unavailable then; this covers a switch at runtime and an old settings folder)
    if (auto toolbars = ToolBarManager::getInstance()) {
        if (on) {
            selectorHidden = true;
            toolbars->setState(QStringLiteral("Workbench"), ToolBarManager::State::ForceHidden);
        }
        else if (selectorHidden) {
            selectorHidden = false;  // FreeCAD's keymap: as it was, nothing more to do
            toolbars->setState(QStringLiteral("Workbench"), ToolBarManager::State::RestoreDefault);
        }
    }
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

void Controller::placeStrip()
{
    // The strip alone on a full-width row above every toolbar (Onshape's document tabs), whatever
    // toolbars a workbench adds later or an old window layout restored: it goes before the first
    // toolbar of the top area, with a break after it. Toolbars added later land on the last row.
    QToolBar* first = nullptr;
    int bestY = 0;
    int bestX = 0;
    for (QToolBar* toolbar : mw->findChildren<QToolBar*>(QString(), Qt::FindDirectChildrenOnly)) {
        if (toolbar == strip || toolbar->isHidden()
            || mw->toolBarArea(toolbar) != Qt::TopToolBarArea) {
            continue;
        }
        const QPoint at = toolbar->geometry().topLeft();
        if (!first || at.y() < bestY || (at.y() == bestY && at.x() < bestX)) {
            first = toolbar;
            bestY = at.y();
            bestX = at.x();
        }
    }
    if (!first) {
        if (!stripPlaced) {
            stripPlaced = true;
            mw->removeToolBar(strip);
            mw->addToolBar(Qt::TopToolBarArea, strip);
            mw->addToolBarBreak(Qt::TopToolBarArea);
            strip->setVisible(isOn());
        }
        return;
    }
    // Already the first row, alone (as laid out): nothing to move
    const QRect at = strip->geometry();
    if (stripPlaced && strip->isVisible() && at.height() > 0 && first->geometry().height() > 0
        && at.bottom() < first->geometry().top()) {
        return;
    }
    stripPlaced = true;
    mw->removeToolBar(strip);
    mw->insertToolBar(first, strip);
    mw->insertToolBarBreak(first);
    strip->setVisible(isOn());
}

void Controller::sizeButtons()
{
    // "+" and the Tab manager button are at least a tab high, with a glyph that can be found (a
    // plain small text button was missed in the first hands-on check)
    int height = 30;
    if (typed) {
        height = std::max(
            height,
            typed->count() > 0 ? typed->tabRect(0).height() : typed->sizeHint().height()
        );
        height = std::max(height, typed->fontMetrics().height() + 14);
    }
    for (QToolButton* button : {managerButton, plusButton}) {
        if (!button) {
            continue;
        }
        QFont font = mw->font();
        if (font.pointSizeF() > 0) {
            font.setPointSizeF(font.pointSizeF() * 1.6);
        }
        else if (font.pixelSize() > 0) {
            font.setPixelSize(font.pixelSize() * 8 / 5);
        }
        font.setBold(true);
        button->setFont(font);
        button->setFixedSize(height, height);
        button->setStyleSheet(QStringLiteral(
            "QToolButton { border: 1px solid palette(mid); border-radius: 4px;"
            " background: palette(button); }"
            " QToolButton:hover { background: palette(midlight); }"
            " QToolButton::menu-indicator { image: none; width: 0px; }"
        ));
    }
}

// The Variable Studio tab's workbench (feat/variable-studio-tab adds it; absent until merged)
constexpr const char* VariableStudioWorkbenchName = "VariableStudioWorkbench";

bool Controller::allowsWorkbench(const std::string& name, std::string* refusal) const
{
    // Under the Onshape keymap a tab's kind fixes its tools (decision 355): a Part Studio takes
    // Part Design (and the Sketcher, which a sketch edit enters), an Assembly its own, a Drawing
    // TechDraw; a Variable Studio keeps what it has. Start and no open document are free.
    App::Document* doc = App::GetApplication().getActiveDocument();
    AppTabs::Tab tab {};
    if (!isOn() || arriving || !doc || closing.count(doc) || name == "StartWorkbench"
        || !AppTabs::findTab(doc, activeTab(doc), tab)) {
        return true;
    }
    const char* tabIs = nullptr;
    bool fits = false;
    switch (tab.kind) {
        case AppTabs::Kind::PartStudio:
            tabIs = QT_TRANSLATE_NOOP("DocumentTabs", "a Part Studio");
            fits = name == "PartDesignWorkbench" || name == "SketcherWorkbench";
            break;
        case AppTabs::Kind::Assembly:
            tabIs = QT_TRANSLATE_NOOP("DocumentTabs", "an Assembly");
            fits = name == "AssemblyWorkbench";
            break;
        case AppTabs::Kind::Drawing:
            tabIs = QT_TRANSLATE_NOOP("DocumentTabs", "a Drawing");
            fits = name == "TechDrawWorkbench";
            break;
        case AppTabs::Kind::VariableStudio: {
            tabIs = QT_TRANSLATE_NOOP("DocumentTabs", "a Variable Studio");
            // Its own workbench when there is one (the Variable Studio lane's, looked up by name);
            // else it keeps what it has
            const QString own = QString::fromLatin1(VariableStudioWorkbenchName);
            if (Application::Instance->workbenches().contains(own)) {
                fits = name == VariableStudioWorkbenchName;
            }
            else {
                Workbench* current = WorkbenchManager::instance()->active();
                fits = current && current->name() == name;
            }
            break;
        }
    }
    if (fits) {
        return true;
    }
    if (refusal) {
        const char* wanted = QT_TRANSLATE_NOOP("DocumentTabs", "a new tab");
        if (name == "AssemblyWorkbench") {
            wanted = QT_TRANSLATE_NOOP("DocumentTabs", "an Assembly");
        }
        else if (name == "TechDrawWorkbench") {
            wanted = QT_TRANSLATE_NOOP("DocumentTabs", "a Drawing");
        }
        else if (name == "PartDesignWorkbench" || name == "SketcherWorkbench") {
            wanted = QT_TRANSLATE_NOOP("DocumentTabs", "a Part Studio");
        }
        *refusal = QApplication::translate("DocumentTabs", "This tab is %1: use + for %2")
                       .arg(QApplication::translate("DocumentTabs", tabIs))
                       .arg(QApplication::translate("DocumentTabs", wanted))
                       .toStdString();
    }
    return false;
}

void Controller::schedule(const App::Document* doc)
{
    if (!isOn() || !doc || closing.count(doc)) {
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
    showAfter.erase(&doc);
    restoredTab.erase(&doc);
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

void Controller::keepImplicit(App::Document* doc)
{
    // The implicit studio shown with something in it stays a tab when emptied, as Onshape keeps
    // an empty Part Studio (R6T-12): its label goes to the registry. Called when the user deletes
    // from it (F6-2), not when it is shown: a write to Meta on showing marked an old file modified
    // on open, outside undo. Not while empty: Std_New's first view shows the empty document
    // before its App::Part studio is made
    if (!doc || AppTabs::hasImplicitLabel(doc) || !AppTabs::hasImplicitStudio(doc)) {
        return;
    }
    const AppTabs::Tab implicit {AppTabs::Kind::PartStudio, nullptr};
    if (!AppTabs::members(doc, implicit).empty()) {
        AppTabs::setImplicitLabel(doc, AppTabs::implicitLabel(doc));
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
        typed->setTabIcon(index, tabIcon(gdoc, tabs[i]));
        if (tabs[i].name() == current) {
            typed->setCurrentIndex(index);
        }
    }
    sizeButtons();
    if (manager && manager->isVisible()) {
        manager->populate();
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
    if (!doc || closing.count(doc)) {
        return;
    }
    const std::string tag = tagOf(view);
    if (!tag.empty()) {
        const std::string before = activeTab(doc);
        if (before.empty() || before == tag || arriving) {
            active[doc] = tag;
        }
        else {
            activatedElsewhere(doc, before, tag);
        }
    }
    else {
        auto page = pageViews.find(view);
        if (page != pageViews.end() && page->second.view) {
            active[doc] = page->second.name;
        }
        else if (auto gdoc = Application::Instance->getDocument(doc)) {
            // A page opened otherwise than by its tab (the tree): its Drawing tab's view; a
            // Variable Studio's window, its tab's
            auto studioView = qobject_cast<VariableStudioView*>(view);
            for (const auto& tab : AppTabs::tabs(doc)) {
                if (studioView && tab.kind == AppTabs::Kind::VariableStudio
                    && tab.object->getNameInDocument() == studioView->studioName()) {
                    pageViews[view] = {QPointer<MDIView>(view), doc, tab.name()};
                    active[doc] = tab.name();
                    break;
                }
                auto vp = tab.kind == AppTabs::Kind::Drawing ? gdoc->getViewProvider(tab.object)
                                                             : nullptr;
                if (vp && vp->getMDIView() == view) {
                    pageViews[view] = {QPointer<MDIView>(view), doc, tab.name()};
                    active[doc] = tab.name();
                    break;
                }
            }
        }
    }
    timer.start();
}

void Controller::activatedElsewhere(
    App::Document* doc,
    const std::string& before,
    const std::string& tag
)
{
    // A tab's view brought up otherwise than by the bar (the tree's selection or double-click,
    // Ctrl+Tab, a closed view): the bar's rules, the selection kept (R6T-5). With a dialog open
    // the view before comes back, once the activation is over, unless an edit took the tab since
    std::string refusal;
    if (viewOf(doc, before) && dialogBlocks(&refusal)) {
        message(refusal);
        const std::string docName = doc->getName();
        QTimer::singleShot(0, this, [this, docName, before] {
            App::Document* current = App::GetApplication().getDocument(docName.c_str());
            if (!current || activeTab(current) != before) {
                return;
            }
            MDIView* back = viewOf(current, before);
            if (back && getMainWindow()->activeWindow() != back) {
                getMainWindow()->setActiveWindow(back);
            }
        });
        return;
    }
    active[doc] = tag;
    AppTabs::Tab tab {};
    auto gdoc = Application::Instance->getDocument(doc);
    if (gdoc && AppTabs::findTab(doc, tag, tab)) {
        leave(gdoc);
        arrive(doc, tab);
    }
}

void Controller::leave(Gui::Document* gdoc)
{
    // Leaving a tab ends its edit (an active assembly)
    if (gdoc->getInEdit()) {
        gdoc->resetEdit();
    }
}

void Controller::arrive(App::Document* doc, const AppTabs::Tab& tab)
{
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc || arriving) {
        return;
    }
    Base::FlagToggler<> flag(arriving);
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
            // Its own tools: no Part Design toolbar or Features list (tabs slice 4)
            Application::Instance->activateWorkbench("VariableStudioWorkbench");
            break;
    }
}

void Controller::onCommit(const App::Document& doc)
{
    if (!isOn() || closing.count(&doc)) {
        return;
    }
    // The tab active at the commit, once per step (an empty commit that follows keeps the step's)
    const int id = doc.getTransactionID(true, 0);
    const std::string tab = activeTab(&doc);
    if (id != 0 && !tab.empty()) {
        steps[&doc].emplace(id, tab);
    }
}

bool Controller::beforeUndo(Gui::Document* gdoc, bool undo)
{
    App::Document* doc = gdoc ? gdoc->getDocument() : nullptr;
    if (!doc) {
        return true;
    }
    const int id = doc->getTransactionID(undo, 0);
    auto docSteps = steps.find(doc);
    if (id == 0 || docSteps == steps.end()) {
        return true;
    }
    auto step = docSteps->second.find(id);
    if (step == docSteps->second.end() || step->second == activeTab(doc)) {
        return true;
    }
    AppTabs::Tab tab {};
    std::string refusal;
    if (!AppTabs::findTab(doc, step->second, tab)) {
        // The step brings its tab back (the redo of "Create Part Studio", the undo of a tab's
        // delete): shown once it is there (J1T)
        showAfter[doc] = step->second;
        return true;
    }
    if (!switchTo(doc, step->second, true, &refusal)) {
        // F6-3: a dialog that doesn't lock the history (an assembly joint's, Std_Placement)
        // refuses the switch. Showing the step's tab under the dialog (R6T-10) stranded the user
        // there (every way back refused while the dialog is open): the undo is refused instead
        message(refusal);
        return false;
    }
    return true;
}

void Controller::stepApplied(const App::Document& doc)
{
    auto it = showAfter.find(&doc);
    if (it == showAfter.end()) {
        return;
    }
    const std::string name = it->second;
    const std::string docName = doc.getName();
    showAfter.erase(it);
    // Once the step's objects have their view providers
    QTimer::singleShot(0, this, [this, docName, name] {
        App::Document* current = App::GetApplication().getDocument(docName.c_str());
        AppTabs::Tab tab {};
        if (current && isOn() && AppTabs::findTab(current, name, tab)) {
            reconcile(current);
            switchTo(current, name, true, nullptr);
            refreshBars();
        }
    });
}

void Controller::restoreFinished(const App::Document& doc)
{
    if (!restoredTab.count(&doc)) {
        return;
    }
    // As stepApplied(): once the restored objects have their view providers and the first view its
    // tag
    const std::string docName = doc.getName();
    QTimer::singleShot(0, this, [this, docName] { applyRestoredTab(docName); });
}

void Controller::applyRestoredTab(const std::string& docName)
{
    App::Document* current = App::GetApplication().getDocument(docName.c_str());
    auto it = current ? restoredTab.find(current) : restoredTab.end();
    if (it == restoredTab.end() || current->testStatus(App::Document::Restoring)) {
        return;
    }
    if (!isOn() || closing.count(current)) {
        restoredTab.erase(it);
        return;
    }
    // A document opened beside the active one (a link's, the second of a recovery) keeps its tab
    // until it is shown: switchTo() would make it the active document
    if (App::GetApplication().getActiveDocument() != current) {
        return;
    }
    const std::string name = it->second;
    restoredTab.erase(it);
    AppTabs::Tab tab {};
    if (!AppTabs::findTab(current, name, tab)) {
        return;
    }
    reconcile(current);
    if (activeTab(current) != name) {
        switchTo(current, name, true, nullptr);
    }
    refreshBars();
}

MDIView* Controller::showTab(App::Document* doc, const AppTabs::Tab& tab)
{
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc) {
        return nullptr;
    }
    const std::string name = tab.name();
    if (is3DKind(tab.kind)) {
        // The tab is the active one before its view is: the activation brings no side effects
        active[doc] = name;
        MDIView* view = viewForTab(doc, tab);
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
    // A Variable Studio: its own window, the studio's table (tabs slice 4), kept with the page
    // views so that viewOf and an activation find it
    active[doc] = name;
    MDIView* view = VariableStudioView::open(gdoc, tab.object);
    if (view) {
        pageViews[view] = {QPointer<MDIView>(view), doc, name};
    }
    active[doc] = name;
    return view;
}

MDIView* Controller::viewForTab(App::Document* doc, const AppTabs::Tab& tab)
{
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc || !is3DKind(tab.kind)) {
        return nullptr;
    }
    const std::string name = tab.name();
    MDIView* view = viewOf(doc, name);
    if (!view) {
        pendingDoc = doc;
        pendingTab = name;
        view = gdoc->createView(View3DInventor::getClassTypeId());
        pendingDoc = nullptr;
        pendingTab.clear();
    }
    return view;
}

bool Controller::beforeEdit(Gui::Document* gdoc, App::DocumentObject* obj)
{
    App::Document* doc = gdoc->getDocument();
    const std::string name = AppTabs::tabNameOf(obj);
    AppTabs::Tab tab {};
    if (!AppTabs::findTab(doc, name, tab) || !is3DKind(tab.kind)) {
        return true;
    }
    if (activeTab(doc) == name && tabOfView(gdoc->getActiveView()) == name) {
        return true;
    }
    // Called once the edit will start (the held step's dialog accepted, the edit before reset):
    // a dialog still open is another command's (R6T-3)
    std::string refusal;
    if (dialogBlocks(&refusal)) {
        message(refusal);
        return false;
    }
    showTab(doc, tab);
    return true;
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
        leave(gdoc);
        Selection().clearSelection();
    }
    if (App::GetApplication().getActiveDocument() != doc) {
        App::GetApplication().setActiveDocument(doc);
    }
    showTab(doc, tab);
    if (sideEffects) {
        arrive(doc, tab);
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
        // The step is the new tab's: its redo shows it again (J1T), its undo is made there
        if (const int id = doc->getTransactionID(true, 0)) {
            steps[doc][id] = name;
        }
    }
    else if (kind == "Assembly") {
        // Any number of assemblies, as Onshape's (ops#651; Assembly_CreateAssembly lifts upstream's
        // one-assembly rule under the Onshape keymap, the only one with tabs)
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
    {
        Base::FlagToggler<> flag(removingTab);  // its deletes don't keep the tab (F6-2)
        AppTabs::removeTab(doc, tab);
    }
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
    // Onshape's order: Rename, Duplicate, Export, Delete (Properties, Copy to clipboard and Move
    // to document aren't here)
    App::Document* doc = App::GetApplication().getActiveDocument();
    AppTabs::Tab tab {};
    const bool found = doc
        && AppTabs::findTab(doc, typed->tabData(index).toString().toStdString(), tab);
    QMenu menu;
    menu.setToolTipsVisible(true);
    QAction* renameAction = menu.addAction(QApplication::translate("DocumentTabs", "Rename"));
    QAction* duplicateAction = menu.addAction(QApplication::translate("DocumentTabs", "Duplicate"));
    duplicateAction->setObjectName(QStringLiteral("FreeCADCH_DuplicateTab"));
    const std::string refusal = found ? AppTabs::duplicateRefusal(doc, tab) : std::string();
    duplicateAction->setEnabled(found && refusal.empty());
    duplicateAction->setToolTip(
        refusal.empty()
            ? QApplication::translate("DocumentTabs", "A copy of the tab, not linked to it")
            : QString::fromStdString(refusal)
    );
    QAction* exportAction = menu.addAction(QApplication::translate("DocumentTabs", "Export..."));
    exportAction->setObjectName(QStringLiteral("FreeCADCH_ExportTab"));
    const bool isDrawing = found && tab.kind == AppTabs::Kind::Drawing;
    const bool exportable = found && (is3DKind(tab.kind) || isDrawing);
    exportAction->setEnabled(exportable);
    exportAction->setToolTip(
        isDrawing ? QApplication::translate("DocumentTabs", "Export the drawing to PDF or SVG")
        : exportable
            ? QApplication::translate("DocumentTabs", "Export the tab to STEP")
            : QApplication::translate(
                "DocumentTabs",
                "Only a Part Studio, an Assembly or a Drawing exports"
            )
    );
    QAction* exportAllAction = nullptr;
    if (isDrawing) {
        exportAllAction = menu.addAction(
            QApplication::translate("DocumentTabs", "Export all drawings to PDF...")
        );
        exportAllAction->setObjectName(QStringLiteral("FreeCADCH_ExportAllDrawings"));
        exportAllAction->setToolTip(
            QApplication::translate("DocumentTabs", "Every drawing of the document, one PDF")
        );
    }
    QAction* deleteAction = menu.addAction(QApplication::translate("DocumentTabs", "Delete"));
    QAction* chosen = menu.exec(typed->mapToGlobal(pos));
    if (chosen == renameAction) {
        renameInteractive(index);
    }
    else if (chosen == duplicateAction) {
        duplicateInteractive(index);
    }
    else if (chosen == exportAction) {
        exportInteractive(index);
    }
    else if (exportAllAction && chosen == exportAllAction) {
        exportAllInteractive(index);
    }
    else if (chosen == deleteAction) {
        deleteInteractive(index);
    }
}

void Controller::duplicateInteractive(int index)
{
    App::Document* doc = App::GetApplication().getActiveDocument();
    if (!doc || index < 0) {
        return;
    }
    std::string refusal;
    if (duplicate(doc, typed->tabData(index).toString().toStdString(), refusal).empty()) {
        QMessageBox::information(
            mw,
            QApplication::translate("DocumentTabs", "Duplicate"),
            QString::fromStdString(refusal)
        );
    }
}

void Controller::exportInteractive(int index)
{
    App::Document* doc = App::GetApplication().getActiveDocument();
    if (!doc || index < 0) {
        return;
    }
    const std::string name = typed->tabData(index).toString().toStdString();
    // The tab's name as the file name, without the characters a file name can't hold
    QString base = typed->tabText(index);
    for (QChar bad : QStringLiteral("\\/:*?\"<>|")) {
        base.replace(bad, QLatin1Char('_'));
    }
    AppTabs::Tab exported {};
    const bool drawing = AppTabs::findTab(doc, name, exported)
        && exported.kind == AppTabs::Kind::Drawing;
    // A drawing: PDF first, so it is the default; the format follows the file's extension
    const QString file = drawing
        ? FileDialog::getSaveFileName(
            mw,
            QApplication::translate("DocumentTabs", "Export"),
            FileDialog::getWorkingDirectory() + QLatin1Char('/') + base + QStringLiteral(".pdf"),
            {FileDialog::Filter(QStringLiteral("PDF"), {QStringLiteral("*.pdf")}),
             FileDialog::Filter(QStringLiteral("SVG"), {QStringLiteral("*.svg")})}
        )
        : FileDialog::getSaveFileName(
            mw,
            QApplication::translate("DocumentTabs", "Export"),
            FileDialog::getWorkingDirectory() + QLatin1Char('/') + base + QStringLiteral(".step"),
            {FileDialog::Filter(
                QStringLiteral("STEP"),
                {QStringLiteral("*.step"), QStringLiteral("*.stp")}
            )}
        );
    if (file.isEmpty()) {
        return;
    }
    FileDialog::setWorkingDirectory(file);
    std::string error;
    if (!exportTab(doc, name, file.toUtf8().toStdString(), error)) {
        QMessageBox::warning(
            mw,
            QApplication::translate("DocumentTabs", "Export"),
            QString::fromStdString(error)
        );
        return;
    }
    message(QApplication::translate("DocumentTabs", "Exported %1").arg(file).toStdString());
}

void Controller::exportAllInteractive(int index)
{
    App::Document* doc = App::GetApplication().getActiveDocument();
    if (!doc || index < 0) {
        return;
    }
    const QString file = FileDialog::getSaveFileName(
        mw,
        QApplication::translate("DocumentTabs", "Export all drawings"),
        FileDialog::getWorkingDirectory() + QLatin1Char('/')
            + QString::fromUtf8(doc->getName()) + QStringLiteral(".pdf"),
        {FileDialog::Filter(QStringLiteral("PDF"), {QStringLiteral("*.pdf")})}
    );
    if (file.isEmpty()) {
        return;
    }
    FileDialog::setWorkingDirectory(file);
    std::string error;
    if (!exportAllDrawings(doc, file.toUtf8().toStdString(), error)) {
        QMessageBox::warning(
            mw,
            QApplication::translate("DocumentTabs", "Export"),
            QString::fromStdString(error)
        );
        return;
    }
    message(QApplication::translate("DocumentTabs", "Exported %1").arg(file).toStdString());
}

std::string Controller::duplicate(App::Document* doc, const std::string& name, std::string& refusal)
{
    AppTabs::Tab tab {};
    auto gdoc = Application::Instance->getDocument(doc);
    if (!gdoc || !AppTabs::findTab(doc, name, tab)) {
        refusal = "No such tab";
        return {};
    }
    refusal = AppTabs::duplicateRefusal(doc, tab);
    if (!refusal.empty() || dialogBlocks(&refusal)) {
        return {};
    }
    if (gdoc->getInEdit()) {
        gdoc->resetEdit();  // an open assembly: the copy is opened instead
    }
    // One undo step; the copy goes right of the original (Meta, outside undo) and is shown
    const std::string title = "Duplicate " + AppTabs::label(doc, tab);
    gdoc->openCommand(title.c_str());
    std::string copyName;
    try {
        App::DocumentObject* copy = AppTabs::duplicate(doc, tab);
        copyName = copy->getNameInDocument();
        nameCopiedParts(doc, copy);
        doc->recompute();
    }
    catch (const Base::Exception& e) {
        gdoc->abortCommand();
        refusal = e.what();
        return {};
    }
    gdoc->commitCommand();
    // The step is the copy's: its redo shows the copy (RT-3), as create()'s
    if (const int id = doc->getTransactionID(true, 0)) {
        steps[doc][id] = copyName;
    }
    reconcile(doc);
    switchTo(doc, copyName, true, nullptr);
    timer.start();
    return copyName;
}

void Controller::nameCopiedParts(App::Document* doc, App::DocumentObject* copy)
{
    // RT-4: a studio's copied Bodies are "Part N", the lowest N free, as PartDesign's
    // nameNewPart() names a new part (the copy's features keep their names). Labels are unique
    // in a document unless the preference allows duplicates; then N is free in the studio
    const Base::Type bodyType = Base::Type::fromName("PartDesign::Body");
    AppTabs::Kind kind {};
    if (!isOn() || bodyType.isBad() || !AppTabs::isTabObject(copy, &kind)
        || kind != AppTabs::Kind::PartStudio) {
        return;
    }
    const bool unique = !App::GetApplication()
                             .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Document")
                             ->GetBool("DuplicateLabels", false);
    const AppTabs::Tab copyTab {AppTabs::Kind::PartStudio, copy};
    for (auto body : AppTabs::members(doc, copyTab)) {
        if (!body->getTypeId().isDerivedFrom(bodyType)) {
            continue;
        }
        // Only a default "Part N" label (its copy reads "Part 001"): a Body the user named
        // ("Lid") keeps its name, as Onshape's duplicate keeps part names (fix review)
        const std::string prefix = QObject::tr("Part %1").arg(QString()).toUtf8().toStdString();
        const std::string current = body->Label.getValue();
        auto isDefault = [&current](const std::string& stem, bool needDigits) {
            return current.size() >= stem.size() + (needDigits ? 1 : 0)
                && current.compare(0, stem.size(), stem) == 0
                && current.find_first_not_of("0123456789", stem.size()) == std::string::npos;
        };
        // FreeCAD's own default "Body", "Body001" counts as unnamed too
        if (!isDefault(prefix, true) && !isDefault("Body", false)) {
            continue;
        }
        std::set<std::string> taken;
        for (auto obj : doc->getObjects()) {
            if (obj != body
                && (unique
                    || (obj->getTypeId().isDerivedFrom(bodyType)
                        && AppTabs::tabOf(obj) == copy))) {
                taken.insert(obj->Label.getValue());
            }
        }
        for (int n = 1;; ++n) {
            const std::string label = QObject::tr("Part %1").arg(n).toUtf8().toStdString();
            if (!taken.count(label)) {
                body->Label.setValue(label);
                break;
            }
        }
    }
}

bool Controller::exportTab(
    App::Document* doc,
    const std::string& name,
    const std::string& path,
    std::string& error
)
{
    AppTabs::Tab tab {};
    if (!doc || !AppTabs::findTab(doc, name, tab)) {
        error = "No such tab";
        return false;
    }
    if (tab.kind == AppTabs::Kind::Drawing) {
        // E1 (ops#640): the drawing's page, as PDF or SVG by the file's extension
        const QString suffix = QFileInfo(QString::fromUtf8(path.c_str())).suffix().toLower();
        if (suffix != QStringLiteral("pdf") && suffix != QStringLiteral("svg")) {
            error = "A Drawing exports to PDF or SVG";
            return false;
        }
        return writeDrawings(
            {tab.object},
            path,
            suffix == QStringLiteral("svg") ? "exportPageAsSvg" : "exportPageAsPdf",
            error
        );
    }
    try {
        // ImportGui's writer: the parts' colours too
        AppTabs::exportTab(doc, tab, path, "ImportGui");
    }
    catch (const Base::Exception& e) {
        error = e.what();
        return false;
    }
    return true;
}

bool Controller::exportAllDrawings(App::Document* doc, const std::string& path, std::string& error)
{
    // E1 (ops#640): every Drawing tab of the document, in the bar's order, as one PDF
    std::vector<App::DocumentObject*> pages;
    if (doc) {
        for (const auto& tab : AppTabs::tabs(doc)) {
            if (tab.kind == AppTabs::Kind::Drawing && tab.object) {
                pages.push_back(tab.object);
            }
        }
    }
    if (pages.empty()) {
        error = "The document has no Drawing to export";
        return false;
    }
    return writeDrawings(pages, path, "exportPagesAsPdf", error);
}

bool Controller::writeDrawings(
    const std::vector<App::DocumentObject*>& pages,
    const std::string& path,
    const char* function,
    std::string& error
)
{
    // TechDrawGui writes the page without its window being open (PagePrinter::ensureScene)
    const QString file = QString::fromUtf8(path.c_str());
    for (auto obj : pages) {
        // a page without its template can't render
        auto link = dynamic_cast<App::PropertyLink*>(obj->getPropertyByName("Template"));
        if (!link || !link->getValue()) {
            error = std::string(obj->Label.getValue()) + " has no template to export";
            return false;
        }
    }
    // a stale file must not pass for the export: replace it, or say it can't be (a viewer holds it)
    if (QFile::exists(file) && !QFile::remove(file)) {
        error = "Can't replace " + path + ": is it open in another program?";
        return false;
    }
    try {
        Base::PyGILStateLocker lock;
        PyObject* imported = PyImport_ImportModule("TechDrawGui");
        if (!imported) {
            throw Py::Exception();
        }
        Py::Module writer(imported, true);
        Py::Callable exporter(writer.getAttr(function));
        Py::Tuple args(2);
        if (std::strcmp(function, "exportPagesAsPdf") == 0) {
            Py::List list;
            for (auto obj : pages) {
                list.append(Py::asObject(obj->getPyObject()));
            }
            args.setItem(0, list);
        }
        else {
            args.setItem(0, Py::asObject(pages.front()->getPyObject()));
        }
        args.setItem(1, Py::String(path));
        exporter.apply(args);
    }
    catch (Py::Exception&) {
        Base::PyException exception;
        error = exception.what();
        return false;
    }
    catch (const Base::Exception& e) {
        error = e.what();
        return false;
    }
    if (!QFileInfo::exists(file) || QFileInfo(file).size() == 0) {
        error = "The file was not written: " + path;
        return false;
    }
    return true;
}

void Controller::saveBarOrder()
{
    // A tab dragged along the bar: its order is the document's, saved with it, not an undo step
    // (Onshape's tab order isn't one [guess])
    App::Document* doc = App::GetApplication().getActiveDocument();
    auto gdoc = doc ? Application::Instance->getDocument(doc) : nullptr;
    if (!gdoc) {
        return;
    }
    std::vector<std::string> names;
    for (int i = 0; i < typed->count(); ++i) {
        names.push_back(typed->tabData(i).toString().toStdString());
    }
    AppTabs::setOrder(doc, names);
    gdoc->setModified(true);
    timer.start();
}

bool Controller::openManager()
{
    App::Document* doc = App::GetApplication().getActiveDocument();
    if (!isOn() || !doc || !Application::Instance->getDocument(doc)) {
        return false;
    }
    if (!manager) {
        manager = new TabManager(mw);
    }
    manager->populate();
    manager->show();
    manager->raise();
    manager->activateWindow();
    return true;
}

bool Controller::eventFilter(QObject* watched, QEvent* event)
{
    const auto type = event->type();
    if ((type == QEvent::ShortcutOverride || type == QEvent::KeyPress) && isOn()) {
        auto key = static_cast<QKeyEvent*>(event);
        const auto modifiers = key->modifiers() & ~Qt::KeypadModifier;
        // RT-6: not while a modal or a menu is open, nor with no document shown
        App::Document* doc = key->key() == Qt::Key_T && modifiers == Qt::AltModifier
            ? App::GetApplication().getActiveDocument()
            : nullptr;
        if (doc && Application::Instance->getDocument(doc) && !QApplication::activeModalWidget()
            && !QApplication::activePopupWidget()) {
            // The override taken: no shortcut (the Tools menu's mnemonic) sees the key, which
            // then comes as a key press
            if (type == QEvent::ShortcutOverride) {
                event->accept();
            }
            else if (!key->isAutoRepeat()) {
                openManager();
            }
            return true;
        }
    }
    return QObject::eventFilter(watched, event);
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

// -- The Tab manager ----------------------------------------------------------------------------

constexpr int nameRole = Qt::UserRole;
constexpr int kindRole = Qt::UserRole + 1;

TabManager::TabManager(QWidget* parent)
    : QDialog(parent)
{
    setObjectName(QStringLiteral("FreeCADCH_TabManagerDialog"));
    setWindowTitle(QApplication::translate("DocumentTabs", "Tab manager"));
    setAttribute(Qt::WA_DeleteOnClose);
    setModal(false);
    auto layout = new QVBoxLayout(this);
    search = new QLineEdit(this);
    search->setObjectName(QStringLiteral("FreeCADCH_TabSearch"));
    search->setPlaceholderText(QApplication::translate("DocumentTabs", "Search tabs"));
    search->setClearButtonEnabled(true);
    layout->addWidget(search);
    filter = new QComboBox(this);
    filter->setObjectName(QStringLiteral("FreeCADCH_TabFilter"));
    filter->addItem(QApplication::translate("DocumentTabs", "All tabs"), -1);
    filter->addItem(
        QApplication::translate("DocumentTabs", "Part Studios"),
        static_cast<int>(AppTabs::Kind::PartStudio)
    );
    filter->addItem(
        QApplication::translate("DocumentTabs", "Assemblies"),
        static_cast<int>(AppTabs::Kind::Assembly)
    );
    filter->addItem(
        QApplication::translate("DocumentTabs", "Drawings"),
        static_cast<int>(AppTabs::Kind::Drawing)
    );
    filter->addItem(
        QApplication::translate("DocumentTabs", "Variable Studios"),
        static_cast<int>(AppTabs::Kind::VariableStudio)
    );
    layout->addWidget(filter);
    list = new QListWidget(this);
    list->setObjectName(QStringLiteral("FreeCADCH_TabList"));
    list->setDragDropMode(QAbstractItemView::InternalMove);
    list->setDefaultDropAction(Qt::MoveAction);
    list->setSelectionMode(QAbstractItemView::SingleSelection);
    layout->addWidget(list);
    resize(320, 400);

    connect(search, &QLineEdit::textChanged, this, [this] { applyFilter(); });
    connect(search, &QLineEdit::returnPressed, this, [this] { openFirst(); });
    connect(filter, qOverload<int>(&QComboBox::currentIndexChanged), this, [this] {
        applyFilter();
    });
    connect(list, &QListWidget::itemActivated, this, [this](QListWidgetItem* item) {
        openTab(item);
    });
    // A drag moves a row however the view does it (a move, or a removal and an insertion): the
    // order is read once it is over
    auto model = list->model();
    connect(model, &QAbstractItemModel::rowsMoved, this, [this] { scheduleOrder(); });
    connect(model, &QAbstractItemModel::rowsInserted, this, [this] { scheduleOrder(); });
    connect(model, &QAbstractItemModel::rowsRemoved, this, [this] { scheduleOrder(); });
}

void TabManager::populate()
{
    App::Document* doc = App::GetApplication().getActiveDocument();
    auto gdoc = doc ? Application::Instance->getDocument(doc) : nullptr;
    Base::FlagToggler<> flag(populating);
    list->clear();
    docName = doc ? doc->getName() : "";
    if (!gdoc) {
        return;
    }
    const std::string current = Gui::DocumentTabs::activeTab(doc);
    for (const auto& tab : AppTabs::tabs(doc)) {
        auto item = new QListWidgetItem(
            tabIcon(gdoc, tab),
            QString::fromUtf8(AppTabs::label(doc, tab).c_str()),
            list
        );
        item->setData(nameRole, QString::fromStdString(tab.name()));
        item->setData(kindRole, static_cast<int>(tab.kind));
        item->setFlags(
            Qt::ItemIsEnabled | Qt::ItemIsSelectable | Qt::ItemIsDragEnabled
        );  // not a drop target: a drop goes between rows
        if (tab.name() == current) {
            list->setCurrentItem(item);
        }
    }
    applyFilter();
}

void TabManager::applyFilter()
{
    const QString text = search->text().trimmed();
    const int kind = filter->currentData().toInt();
    QListWidgetItem* firstShown = nullptr;
    for (int row = 0; row < list->count(); ++row) {
        QListWidgetItem* item = list->item(row);
        const bool hidden = (kind >= 0 && item->data(kindRole).toInt() != kind)
            || (!text.isEmpty() && !item->text().contains(text, Qt::CaseInsensitive));
        list->setRowHidden(row, hidden);
        if (!hidden && !firstShown) {
            firstShown = item;
        }
    }
    QListWidgetItem* current = list->currentItem();
    if (firstShown && (!current || current->isHidden())) {
        list->setCurrentItem(firstShown);
    }
}

void TabManager::openTab(QListWidgetItem* item)
{
    App::Document* doc = App::GetApplication().getDocument(docName.c_str());
    Controller* ctl = Controller::instance();
    if (!item || !doc || !ctl) {
        return;
    }
    std::string refusal;
    if (!ctl->switchTo(doc, item->data(nameRole).toString().toStdString(), true, &refusal)) {
        ctl->message(refusal);
        return;
    }
    ctl->refreshBars();
    close();
}

void TabManager::openFirst()
{
    for (int row = 0; row < list->count(); ++row) {
        if (!list->isRowHidden(row)) {
            openTab(list->item(row));
            return;
        }
    }
}

void TabManager::scheduleOrder()
{
    if (populating || orderPending) {
        return;
    }
    orderPending = true;
    QTimer::singleShot(0, this, [this] { saveOrder(); });
}

void TabManager::saveOrder()
{
    orderPending = false;
    App::Document* doc = App::GetApplication().getDocument(docName.c_str());
    auto gdoc = doc ? Application::Instance->getDocument(doc) : nullptr;
    if (!gdoc) {
        return;
    }
    std::vector<std::string> names;
    for (int row = 0; row < list->count(); ++row) {
        names.push_back(list->item(row)->data(nameRole).toString().toStdString());
    }
    // Only a reordering of the same tabs (a drag half over, or the tabs changed meanwhile: read
    // them again)
    std::vector<std::string> current;
    for (const auto& tab : AppTabs::tabs(doc)) {
        current.push_back(tab.name());
    }
    std::vector<std::string> sortedNames = names;
    std::vector<std::string> sortedCurrent = current;
    std::sort(sortedNames.begin(), sortedNames.end());
    std::sort(sortedCurrent.begin(), sortedCurrent.end());
    if (sortedNames != sortedCurrent) {
        populate();
        return;
    }
    if (names != current) {
        AppTabs::setOrder(doc, names);  // the bar's order: saved, no undo step [guess]
        gdoc->setModified(true);
        if (auto ctl = Controller::instance()) {
            ctl->schedule(doc);
        }
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
            "allowsWorkbench",
            &Module::pyAllowsWorkbench,
            "allowsWorkbench(name) -> (allowed, refusal): whether the active tab's kind takes the workbench"
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
        add_varargs_method(
            "duplicate",
            &Module::pyDuplicate,
            "duplicate(doc, name) -> (copy's name, refusal), as the tab menu's Duplicate"
        );
        add_varargs_method(
            "exportTab",
            &Module::pyExportTab,
            "exportTab(doc, name, path) -> (written, error), as the tab menu's Export once\n"
            "the file is chosen"
        );
        add_varargs_method(
            "exportAllDrawings",
            &Module::pyExportAllDrawings,
            "exportAllDrawings(doc, path) -> (written, error), as the tab menu's Export all\n"
            "drawings once the file is chosen: every Drawing tab, in the bar's order, one PDF"
        );
        add_varargs_method(
            "openManager",
            &Module::pyOpenManager,
            "openManager() -> whether the Tab manager opened, as Alt+T"
        );
        add_varargs_method(
            "moveTab",
            &Module::pyMoveTab,
            "moveTab(fromIndex, toIndex): a tab dragged along the bar"
        );
        initialize("Onshape's typed tabs in the GUI (FreeCAD-CH)");
    }

private:
    Py::Object pyIsOn(const Py::Tuple& /*args*/)
    {
        return Py::Boolean(DocumentTabs::isOn());
    }
    Py::Object pyAllowsWorkbench(const Py::Tuple& args)
    {
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "s", &name)) {
            throw Py::Exception();
        }
        std::string refusal;
        const bool allowed = controller().allowsWorkbench(name, &refusal);
        Py::Tuple result(2);
        result.setItem(0, Py::Boolean(allowed));
        result.setItem(1, Py::String(refusal));
        return result;
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
    Py::Object pyDuplicate(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pyDoc, &name)) {
            throw Py::Exception();
        }
        std::string refusal;
        const std::string copy = controller().duplicate(documentArg(pyDoc), name, refusal);
        controller().refreshBars();
        Py::Tuple result(2);
        result.setItem(0, Py::String(copy));
        result.setItem(1, Py::String(refusal));
        return result;
    }
    Py::Object pyExportTab(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        const char* name = nullptr;
        char* path = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Oset", &pyDoc, &name, "utf-8", &path)) {
            throw Py::Exception();
        }
        const std::string file(path);
        PyMem_Free(path);
        std::string error;
        const bool done = controller().exportTab(documentArg(pyDoc), name, file, error);
        Py::Tuple result(2);
        result.setItem(0, Py::Boolean(done));
        result.setItem(1, Py::String(error));
        return result;
    }
    Py::Object pyExportAllDrawings(const Py::Tuple& args)
    {
        PyObject* pyDoc = nullptr;
        char* path = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "Oet", &pyDoc, "utf-8", &path)) {
            throw Py::Exception();
        }
        const std::string file(path);
        PyMem_Free(path);
        std::string error;
        const bool done = controller().exportAllDrawings(documentArg(pyDoc), file, error);
        Py::Tuple result(2);
        result.setItem(0, Py::Boolean(done));
        result.setItem(1, Py::String(error));
        return result;
    }
    Py::Object pyOpenManager(const Py::Tuple& /*args*/)
    {
        return Py::Boolean(controller().openManager());
    }
    Py::Object pyMoveTab(const Py::Tuple& args)
    {
        int from = 0;
        int to = 0;
        if (!PyArg_ParseTuple(args.ptr(), "ii", &from, &to)) {
            throw Py::Exception();
        }
        QTabBar* bar = controller().typedBar();
        if (from < 0 || to < 0 || from >= bar->count() || to >= bar->count()) {
            throw Py::IndexError("no such tab on the bar");
        }
        bar->moveTab(from, to);  // tabMoved: the order saved, as a drag
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
    if (!isOn()) {
        return true;  // FreeCAD's keymap: every view shows everything (R6T-4)
    }
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
    undoAllowed(gdoc, undo);
}

// F6-3: Gui::Document::undo()/redo()'s, declared there (the header stays as it is): shows the tab
// the next step was made in; false (the undo refused, the status bar says why) when that takes a
// switch an open dialog refuses
bool DocumentTabs::undoAllowed(Gui::Document* gdoc, bool undo)
{
    if (isOn() && Controller::instance()) {
        return Controller::instance()->beforeUndo(gdoc, undo);
    }
    return true;
}

bool DocumentTabs::beforeEdit(Gui::Document* gdoc, ViewProvider* vp)
{
    Controller* ctl = Controller::instance();
    auto vpd = dynamic_cast<ViewProviderDocumentObject*>(vp);
    App::DocumentObject* obj = vpd ? vpd->getObject() : nullptr;
    if (!isOn() || !ctl || !gdoc || !obj || !obj->isAttachedToDocument()) {
        return true;
    }
    return ctl->beforeEdit(gdoc, obj);
}

MDIView* DocumentTabs::viewOfObject(Gui::Document* gdoc, const App::DocumentObject* obj)
{
    Controller* ctl = Controller::instance();
    if (!isOn() || !ctl || !gdoc || !obj || !obj->isAttachedToDocument()
        || obj->getDocument() != gdoc->getDocument()) {
        return nullptr;
    }
    App::Document* doc = gdoc->getDocument();
    const bool solid = obj->isDerivedFrom<App::GeoFeature>()
        || obj->hasExtension(App::LinkBaseExtension::getExtensionClassTypeId())
        || AppTabs::isTabObject(obj);
    AppTabs::Tab tab {};
    if (solid && AppTabs::findTab(doc, AppTabs::tabNameOf(obj), tab) && is3DKind(tab.kind)) {
        return ctl->viewForTab(doc, tab);
    }
    // Not shown in a 3D tab (a variable set, a spreadsheet): the tab stays
    MDIView* current = gdoc->getActiveView();
    return qobject_cast<View3DInventor*>(current) && !tagOf(current).empty() ? current : nullptr;
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

void DocumentTabs::restoreActiveTab(const App::Document* doc, const std::string& name)
{
    if (auto ctl = Controller::instance(); ctl && doc && !name.empty()) {
        ctl->restoredTab[doc] = name;
    }
}

bool DocumentTabs::allowsWorkbench(const std::string& name, std::string* refusal)
{
    Controller* ctl = Controller::instance();
    return !ctl || ctl->allowsWorkbench(name, refusal);
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
