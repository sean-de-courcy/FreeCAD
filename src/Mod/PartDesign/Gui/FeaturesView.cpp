// SPDX-License-Identifier: LGPL-2.1-or-later

#include "FeaturesView.h"

#include <algorithm>
#include <set>

#include <QHeaderView>
#include <QKeyEvent>
#include <QLabel>
#include <QMenu>
#include <QMouseEvent>
#include <QPainter>
#include <QScrollBar>
#include <QSplitter>
#include <QVBoxLayout>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/GroupExtension.h>
#include <App/Part.h>
#include <App/PropertyLinks.h>
#include <App/SuppressibleExtension.h>
#include <Base/Exception.h>
#include <Gui/ActiveObjectList.h>
#include <Gui/Application.h>
#include <Gui/BitmapFactory.h>
#include <Gui/Command.h>
#include <Gui/Document.h>
#include <Gui/DockWindowManager.h>
#include <Gui/MainWindow.h>
#include <Gui/MDIView.h>
#include <Gui/ViewProviderDocumentObject.h>
#include <Gui/Workbench.h>
#include <Gui/WorkbenchManager.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/PartDesign/App/Body.h>
#include <Mod/PartDesign/App/Studio.h>

#include "ViewProviderBody.h"

using namespace PartDesignGui;

QPointer<FeaturesView> FeaturesView::registered;

namespace
{

constexpr const char* paramPath = "User parameter:BaseApp/Preferences/Mod/PartDesign";

/// Why the studio's bar doesn't move during an edit (as ViewProviderBody::rollBar())
constexpr const char* editLockedMessage = QT_TRANSLATE_NOOP(
    "Exception",
    "The bodies can't roll back while a dialog or an edit is open"
);

bool inPartDesign()
{
    auto wb = Gui::WorkbenchManager::instance()->active();
    return wb && wb->name() == "PartDesignWorkbench";
}

/// The Model panel's splitter (the Combo view: the tree above the Properties panel), or null when
/// the Combo view is turned off
QSplitter* modelSplitter()
{
    QWidget* combo = Gui::DockWindowManager::instance()->findRegisteredDockWindow("Std_ComboView");
    return combo ? combo->findChild<QSplitter*>(QString(), Qt::FindDirectChildrenOnly) : nullptr;
}

/// The tree in the Model panel's splitter (Gui::TreePanel, not exported: found by class name)
QWidget* treePanelOf(QSplitter* splitter)
{
    for (int i = 0; splitter && i < splitter->count(); ++i) {
        QWidget* widget = splitter->widget(i);
        if (qstrcmp(widget->metaObject()->className(), "Gui::TreePanel") == 0) {
            return widget;
        }
    }
    return nullptr;
}

/// Shows the lists or the tree in the Model panel
void showLists(bool lists)
{
    auto splitter = modelSplitter();
    auto tree = treePanelOf(splitter);
    if (auto view = FeaturesView::instance()) {
        view->setVisible(lists);
    }
    if (tree) {
        tree->setVisible(!lists || !FeaturesView::instance());
    }
}

Gui::ViewProviderDocumentObject* viewProviderOf(const App::DocumentObject* obj)
{
    return freecad_cast<Gui::ViewProviderDocumentObject*>(
        Gui::Application::Instance->getViewProvider(obj)
    );
}

/// The tree's status look (Tree.cpp, DocumentObjectItem::testStatus): the icon with the error,
/// warning, held or recompute overlay at its top right
QIcon statusIcon(const App::DocumentObject* obj, bool held)
{
    auto vp = viewProviderOf(obj);
    QIcon icon = vp ? vp->getIcon() : QIcon();
    const char* overlay = nullptr;
    if (obj->isError()) {
        overlay = "overlay_error";
    }
    else if (obj->isWarning()) {
        overlay = "overlay_warning";
    }
    else if (held) {
        overlay = "overlay_rolledback";
    }
    else if (obj->isTouched() || obj->mustExecute() == 1) {
        overlay = "overlay_recompute";
    }
    if (!overlay) {
        return icon;
    }
    QPixmap px = Gui::BitmapFactory().pixmapFromSvg(overlay, QSize(10, 10));
    return QIcon(Gui::BitmapFactory().merge(icon.pixmap(16, 16), px, Gui::BitmapFactoryInst::TopRight));
}

/// Italic for a held object, struck through for a suppressed one, as in the tree
QFont statusFont(QFont font, const App::DocumentObject* obj, bool held)
{
    font.setItalic(held);
    auto suppressible = obj->getExtensionByType<App::SuppressibleExtension>(true);
    font.setStrikeOut(suppressible && suppressible->Suppressed.getValue());
    return font;
}

bool isSuppressed(const App::DocumentObject* obj)
{
    auto suppressible = obj->getExtensionByType<App::SuppressibleExtension>(true);
    return suppressible && suppressible->Suppressed.getValue();
}

/// The studio's parts: its Bodies, and the other solids at its level (an imported shape, a Part
/// workbench feature) that no other shape reads
std::vector<App::DocumentObject*> studioParts(App::Document* doc, App::Part* studio)
{
    std::vector<App::DocumentObject*> parts;
    for (auto body : PartDesign::studioBodies(doc, studio)) {
        parts.push_back(body);
    }
    std::vector<App::DocumentObject*> candidates;
    if (studio) {
        candidates = studio->Group.getValues();
    }
    else {
        for (auto obj : doc->getObjects()) {
            if (!App::GroupExtension::getGroupOfObject(obj)
                && !App::GeoFeatureGroupExtension::getGroupOfObject(obj)) {
                candidates.push_back(obj);
            }
        }
    }
    for (auto obj : candidates) {
        if (!obj || !obj->isDerivedFrom<Part::Feature>() || obj->isDerivedFrom<Part::BodyBase>()
            || Part::BodyBase::findBodyOf(obj)) {
            continue;
        }
        auto vp = viewProviderOf(obj);
        if (!vp || !vp->showInTree()) {
            continue;
        }
        // A tool of another shape (a Cut's, a Body's base feature) is part of that shape
        bool read = std::ranges::any_of(obj->getInList(), [](App::DocumentObject* in) {
            return in && in->isDerivedFrom<App::GeoFeature>()
                && !in->hasExtension(App::GroupExtension::getExtensionClassTypeId());
        });
        if (!read) {
            parts.push_back(obj);
        }
    }
    return parts;
}

}  // namespace

// ------------------------------------------------------------------------------- FeatureList

FeatureList::FeatureList(QWidget* parent)
    : QListWidget(parent)
{}

QListWidgetItem* FeatureList::barItem() const
{
    for (int i = 0; i < count(); ++i) {
        if (item(i)->type() == BarType) {
            return item(i);
        }
    }
    return nullptr;
}

void FeatureList::mousePressEvent(QMouseEvent* event)
{
    auto pressed = itemAt(event->position().toPoint());
    if (event->button() == Qt::LeftButton && pressed && pressed->type() == BarType) {
        dragging = true;
        setCursor(Qt::ClosedHandCursor);
        event->accept();
        return;
    }
    QListWidget::mousePressEvent(event);
}

void FeatureList::mouseMoveEvent(QMouseEvent* event)
{
    auto bar = barItem();
    if (!dragging || !bar) {
        QListWidget::mouseMoveEvent(event);
        return;
    }
    // The bar goes before the row under the cursor, or after it in the row's lower half
    QPoint pos = event->position().toPoint();
    int from = row(bar);
    int to = 0;
    if (auto target = itemAt(pos)) {
        to = row(target) + (pos.y() > visualItemRect(target).center().y() ? 1 : 0);
    }
    else {
        to = pos.y() < 0 ? 0 : count();
    }
    if (to > from) {
        --to;  // taking the bar out moves the rows below it up
    }
    if (to != from) {
        takeItem(from);
        insertItem(to, bar);
    }
    event->accept();
}

void FeatureList::mouseReleaseEvent(QMouseEvent* event)
{
    if (!dragging) {
        QListWidget::mouseReleaseEvent(event);
        return;
    }
    dragging = false;
    unsetCursor();
    event->accept();
    if (auto bar = barItem()) {
        Q_EMIT barDropped(row(bar) - 1);
    }
}

void FeatureList::keyPressEvent(QKeyEvent* event)
{
    if (dragging && event->key() == Qt::Key_Escape) {
        dragging = false;
        unsetCursor();
        event->accept();
        Q_EMIT barDragCancelled();
        return;
    }
    QListWidget::keyPressEvent(event);
}

void FeatureBarDelegate::paint(QPainter* painter, const QStyleOptionViewItem& option, const QModelIndex& index) const
{
    auto list = qobject_cast<const FeatureList*>(parent());
    auto item = list ? list->item(index.row()) : nullptr;
    if (!item || item->type() != FeatureList::BarType) {
        QStyledItemDelegate::paint(painter, option, index);
        return;
    }
    // As the tree's bar (Tree.cpp, TreeWidgetItemDelegate::paint): a line across the row with a
    // grip at its start, in the highlight colour while dragged
    QColor color = list->isDraggingBar() ? option.palette.color(QPalette::Highlight)
                                         : option.palette.color(QPalette::Mid);
    painter->save();
    painter->setRenderHint(QPainter::Antialiasing, false);
    QRect rect = option.rect;
    int thickness = std::max(2, rect.height() / 3);
    painter->fillRect(QRect(rect.left(), rect.center().y() - thickness / 2, rect.width(), thickness), color);
    int dot = thickness + 1;
    int y = rect.center().y() - dot / 2;
    for (int k = 0; k < 3; ++k) {
        painter->fillRect(QRect(rect.left() + 2 + k * (dot + 2), y - dot, dot, dot), color);
        painter->fillRect(QRect(rect.left() + 2 + k * (dot + 2), y + dot, dot, dot), color);
    }
    painter->restore();
}

// ------------------------------------------------------------------------------ FeaturesView

FeaturesView::FeaturesView(QWidget* parent)
    : QWidget(parent)
    , Gui::SelectionObserver(true, Gui::ResolveMode::OldStyleElement)
{
    auto layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    auto splitter = new QSplitter(Qt::Vertical, this);
    layout->addWidget(splitter);

    auto featuresBox = new QWidget(splitter);
    auto featuresLayout = new QVBoxLayout(featuresBox);
    featuresLayout->setContentsMargins(0, 0, 0, 0);
    featuresLayout->setSpacing(2);
    auto title = new QLabel(tr("Features"), featuresBox);
    title->setObjectName(QStringLiteral("featuresTitle"));
    title->setContentsMargins(4, 2, 4, 0);
    featuresLayout->addWidget(title);
    features = new FeatureList(featuresBox);
    features->setObjectName(QStringLiteral("featureList"));
    features->setItemDelegate(new FeatureBarDelegate(features));
    features->setSelectionMode(QAbstractItemView::ExtendedSelection);
    features->setIconSize(QSize(16, 16));
    features->setContextMenuPolicy(Qt::CustomContextMenu);
    featuresLayout->addWidget(features);

    parts = new QTreeWidget(splitter);
    parts->setObjectName(QStringLiteral("partsList"));
    parts->setColumnCount(2);
    parts->setHeaderLabels({tr("Parts"), QString()});
    parts->setRootIsDecorated(false);
    parts->setIconSize(QSize(16, 16));
    parts->setSelectionMode(QAbstractItemView::ExtendedSelection);
    parts->header()->setStretchLastSection(false);
    parts->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    parts->header()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    splitter->setStretchFactor(0, 3);
    splitter->setStretchFactor(1, 1);

    rebuildTimer = new QTimer(this);
    rebuildTimer->setSingleShot(true);
    rebuildTimer->setInterval(50);
    connect(rebuildTimer, &QTimer::timeout, this, &FeaturesView::rebuild);
    selectionTimer = new QTimer(this);
    selectionTimer->setSingleShot(true);
    selectionTimer->setInterval(0);
    connect(selectionTimer, &QTimer::timeout, this, &FeaturesView::syncSelectionFromApp);

    connect(features, &FeatureList::barDropped, this, &FeaturesView::onBarDropped);
    connect(features, &FeatureList::barDragCancelled, this, &FeaturesView::rebuild);
    connect(features, &QListWidget::customContextMenuRequested, this, &FeaturesView::onFeatureMenu);
    connect(features, &QListWidget::itemDoubleClicked, this, &FeaturesView::onFeatureDoubleClicked);
    connect(features, &QListWidget::itemSelectionChanged, this, [this]() {
        if (syncing) {
            return;
        }
        std::vector<App::DocumentObject*> objs;
        for (auto item : features->selectedItems()) {
            if (auto obj = objectOf(item)) {
                objs.push_back(obj);
            }
        }
        pushSelection(objs);
    });
    connect(parts, &QTreeWidget::itemClicked, this, &FeaturesView::onPartClicked);
    connect(parts, &QTreeWidget::itemDoubleClicked, this, &FeaturesView::onPartDoubleClicked);
    connect(parts, &QTreeWidget::itemSelectionChanged, this, [this]() {
        if (syncing) {
            return;
        }
        std::vector<App::DocumentObject*> objs;
        for (auto item : parts->selectedItems()) {
            if (auto obj = objectOf(item)) {
                objs.push_back(obj);
            }
        }
        pushSelection(objs);
    });

    auto& app = App::GetApplication();
    connections.emplace_back(app.signalNewObject.connect([this](const App::DocumentObject& obj) {
        onObject(obj);
    }));
    connections.emplace_back(app.signalDeletedObject.connect([this](const App::DocumentObject& obj) {
        onObject(obj);
    }));
    connections.emplace_back(app.signalChangedObject.connect(
        [this](const App::DocumentObject& obj, const App::Property& prop) { onChangedObject(obj, prop); }
    ));
    auto ofThisDocument = [this](const App::Document& doc) {
        if (documentName == doc.getName()) {
            scheduleRebuild();
        }
    };
    connections.emplace_back(app.signalRecomputed.connect(ofThisDocument));
    connections.emplace_back(app.signalUndoDocument.connect(ofThisDocument));
    connections.emplace_back(app.signalRedoDocument.connect(ofThisDocument));
    connections.emplace_back(Gui::Application::Instance->signalActiveDocument.connect(
        [this](const Gui::Document& gdoc) { onActiveDocument(gdoc); }
    ));
    connections.emplace_back(Gui::Application::Instance->signalDeleteDocument.connect(
        [this](const Gui::Document& gdoc) { onDeleteDocument(gdoc); }
    ));
    if (auto gdoc = Gui::Application::Instance->activeDocument()) {
        onActiveDocument(*gdoc);
    }
}

FeaturesView::~FeaturesView() = default;

FeaturesView* FeaturesView::instance()
{
    return registered.data();
}

bool FeaturesView::prefersModelTree()
{
    return App::GetApplication().GetParameterGroupByPath(paramPath)->GetBool("ShowModelTree", false);
}

void FeaturesView::enterPartDesign()
{
    // Deferred: at start-up the window's saved layout is restored after the workbench activates
    QTimer::singleShot(0, []() {
        if (!inPartDesign()) {
            return;
        }
        QSplitter* splitter = modelSplitter();
        if (!splitter) {
            return;
        }
        if (!registered) {
            QWidget* tree = treePanelOf(splitter);
            int index = tree ? splitter->indexOf(tree) : 0;
            QList<int> sizes = splitter->sizes();
            auto view = new FeaturesView();
            view->setObjectName(QStringLiteral("FeaturesView"));
            splitter->insertWidget(index, view);
            registered = view;
            // The lists take the tree's room
            if (index < sizes.size()) {
                sizes.insert(index, sizes[index]);
                splitter->setSizes(sizes);
            }
        }
        showLists(!prefersModelTree());
    });
}

void FeaturesView::leavePartDesign()
{
    showLists(false);
}

void FeaturesView::toggleModelTree()
{
    bool tree = !prefersModelTree();
    App::GetApplication().GetParameterGroupByPath(paramPath)->SetBool("ShowModelTree", tree);
    if (inPartDesign()) {
        if (!registered && !tree) {
            enterPartDesign();
            return;
        }
        showLists(!tree);
    }
}

App::Document* FeaturesView::document() const
{
    return documentName.empty() ? nullptr : App::GetApplication().getDocument(documentName.c_str());
}

App::Part* FeaturesView::studio() const
{
    auto doc = document();
    if (!doc || studioName.empty()) {
        return nullptr;
    }
    return freecad_cast<App::Part*>(doc->getObject(studioName.c_str()));
}

void FeaturesView::onActiveDocument(const Gui::Document& gdoc)
{
    std::string name = gdoc.getDocument() ? gdoc.getDocument()->getName() : "";
    if (name != documentName) {
        documentName = name;
        barHinted = false;
        barHint.clear();
        watchDocument(&gdoc);
    }
    scheduleRebuild();
}

void FeaturesView::onDeleteDocument(const Gui::Document& gdoc)
{
    if (gdoc.getDocument() && documentName == gdoc.getDocument()->getName()) {
        // Now, not on the timer: no row may name an object of the closing document
        documentConnections.clear();
        documentName.clear();
        studioName.clear();
        syncing = true;
        features->clear();
        parts->clear();
        syncing = false;
    }
}

void FeaturesView::watchDocument(const Gui::Document* gdoc)
{
    documentConnections.clear();
    if (!gdoc) {
        return;
    }
    // The active Body (it picks the studio)
    documentConnections.emplace_back(gdoc->signalActivatedViewProvider.connect(
        [this](const Gui::ViewProviderDocumentObject*, const char* name) {
            if (name && strcmp(name, PDBODYKEY) == 0) {
                scheduleRebuild();
            }
        }
    ));
    // The edit roll-back point changes no property: the Body's view provider tells it as a Tip
    // change (ViewProviderBody::setEditRoll())
    documentConnections.emplace_back(gdoc->signalChangedObject.connect(
        [this](const Gui::ViewProviderDocumentObject&, const App::Property& prop) {
            const char* name = prop.getName();
            if (name && (strcmp(name, "Tip") == 0 || strcmp(name, "Visibility") == 0)) {
                scheduleRebuild();
            }
        }
    ));
    documentConnections.emplace_back(
        gdoc->signalInEdit.connect([this](const Gui::ViewProviderDocumentObject&) { scheduleRebuild(); })
    );
    documentConnections.emplace_back(
        gdoc->signalResetEdit.connect([this](const Gui::ViewProviderDocumentObject&) { scheduleRebuild(); })
    );
}

void FeaturesView::onObject(const App::DocumentObject& obj)
{
    if (obj.getDocument() && documentName == obj.getDocument()->getName()) {
        scheduleRebuild();
    }
}

void FeaturesView::onChangedObject(const App::DocumentObject& obj, const App::Property& prop)
{
    if (!obj.getDocument() || documentName != obj.getDocument()->getName()) {
        return;
    }
    // The order follows the links; the rows show Label, the held look the Tip, the status
    // Suppressed, the Parts list's eye Visibility
    const char* name = prop.getName();
    bool shown = name
        && (strcmp(name, "Group") == 0 || strcmp(name, "Tip") == 0 || strcmp(name, "Label") == 0
            || strcmp(name, "Suppressed") == 0 || strcmp(name, "Visibility") == 0);
    if (shown || prop.isDerivedFrom<App::PropertyLinkBase>()) {
        scheduleRebuild();
    }
}

void FeaturesView::scheduleRebuild()
{
    if (!isVisible()) {
        dirty = true;
        return;
    }
    rebuildTimer->start();
}

void FeaturesView::showEvent(QShowEvent* event)
{
    QWidget::showEvent(event);
    if (dirty) {
        rebuild();
    }
}

void FeaturesView::findStudio()
{
    studioName.clear();
    auto doc = document();
    if (!doc) {
        return;
    }
    PartDesign::Body* body = nullptr;
    auto gdoc = Gui::Application::Instance->getDocument(doc);
    if (auto view = gdoc ? gdoc->getActiveView() : nullptr) {
        body = view->getActiveObject<PartDesign::Body*>(PDBODYKEY);
    }
    App::Part* part = nullptr;
    if (body && Part::BodyBase::studioOf(body, part)) {
        if (part) {
            studioName = part->getNameInDocument();
        }
        return;
    }
    // No active Body: the top level, or the App::Part of the first Body when the top level has none
    if (!PartDesign::studioBodies(doc, nullptr).empty()) {
        return;
    }
    for (auto obj : doc->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
        if (Part::BodyBase::studioOf(static_cast<PartDesign::Body*>(obj), part) && part) {
            studioName = part->getNameInDocument();
            return;
        }
    }
}

void FeaturesView::rebuild()
{
    if (!isVisible()) {
        dirty = true;
        return;
    }
    // Not under the user's hand: a bar drag ends with its own rebuild
    if (features->isDraggingBar()) {
        rebuildTimer->start();
        return;
    }
    dirty = false;
    findStudio();
    syncing = true;
    rebuildFeatures();
    rebuildParts();
    syncing = false;
    syncSelectionFromApp();
}

void FeaturesView::rebuildFeatures()
{
    int scroll = features->verticalScrollBar() ? features->verticalScrollBar()->value() : 0;
    features->clear();
    auto doc = document();
    if (!doc) {
        return;
    }
    const auto sequence = PartDesign::studioSequence(doc, studio());
    App::DocumentObject* hint = barHint.empty() ? nullptr : doc->getObject(barHint.c_str());
    bool hinted = barHinted && (barHint.empty() || hint);
    App::DocumentObject* after = PartDesign::studioBarAfter(sequence, hinted, hint);
    std::size_t barRow = 0;
    if (after) {
        barRow = static_cast<std::size_t>(std::ranges::find(sequence, after) - sequence.begin()) + 1;
    }
    auto addBar = [this]() {
        auto bar = new QListWidgetItem(features, FeatureList::BarType);
        bar->setFlags(Qt::ItemIsEnabled);
        bar->setSizeHint(QSize(0, 9));
        bar->setToolTip(tr("Roll-back bar: drag it to roll every body of the part studio back"));
    };
    for (std::size_t i = 0; i < sequence.size(); ++i) {
        if (i == barRow) {
            addBar();
        }
        auto obj = sequence[i];
        auto body = PartDesign::Body::findBodyOf(obj);
        bool held = body && body->holds(obj);
        auto item = new QListWidgetItem(QString::fromUtf8(obj->Label.getValue()), features);
        item->setData(Qt::UserRole, QByteArray(obj->getNameInDocument()));
        item->setIcon(statusIcon(obj, held));
        item->setFont(statusFont(item->font(), obj, held));
        if (body) {
            item->setToolTip(tr("%1 (%2)").arg(
                QString::fromUtf8(obj->Label.getValue()),
                QString::fromUtf8(body->Label.getValue())
            ));
        }
    }
    if (barRow >= sequence.size()) {
        addBar();
    }
    if (auto bar = features->verticalScrollBar()) {
        bar->setValue(scroll);
    }
}

void FeaturesView::rebuildParts()
{
    parts->clear();
    auto doc = document();
    if (!doc) {
        return;
    }
    QIcon visible(Gui::BitmapFactory().pixmap("TreeItemVisible"));
    QIcon invisible(Gui::BitmapFactory().pixmap("TreeItemInvisible"));
    for (auto obj : studioParts(doc, studio())) {
        auto body = freecad_cast<PartDesign::Body*>(obj);
        bool held = body && body->isRolledBack();
        auto item = new QTreeWidgetItem(parts);
        item->setText(0, QString::fromUtf8(obj->Label.getValue()));
        item->setData(0, Qt::UserRole, QByteArray(obj->getNameInDocument()));
        item->setIcon(0, statusIcon(obj, held));
        item->setFont(0, statusFont(item->font(0), obj, held));
        auto vp = viewProviderOf(obj);
        if (vp && vp->canToggleVisibility()) {
            item->setIcon(1, vp->isShow() ? visible : invisible);
            item->setToolTip(1, tr("Show or hide"));
        }
    }
}

App::DocumentObject* FeaturesView::objectOf(const QListWidgetItem* item) const
{
    auto doc = document();
    if (!doc || !item || item->type() == FeatureList::BarType) {
        return nullptr;
    }
    return doc->getObject(item->data(Qt::UserRole).toByteArray().constData());
}

App::DocumentObject* FeaturesView::objectOf(const QTreeWidgetItem* item) const
{
    auto doc = document();
    if (!doc || !item) {
        return nullptr;
    }
    return doc->getObject(item->data(0, Qt::UserRole).toByteArray().constData());
}

void FeaturesView::pushSelection(const std::vector<App::DocumentObject*>& objs)
{
    auto doc = document();
    if (!doc) {
        return;
    }
    syncing = true;
    Gui::Selection().clearSelection(doc->getName());
    for (auto obj : objs) {
        // As the tree selects: from the top-level object down (Body1.Pad.)
        auto parents = obj->getParents();
        if (!parents.empty() && parents.front().first) {
            Gui::Selection().addSelection(
                doc->getName(),
                parents.front().first->getNameInDocument(),
                parents.front().second.c_str()
            );
        }
        else {
            Gui::Selection().addSelection(doc->getName(), obj->getNameInDocument());
        }
    }
    syncing = false;
}

void FeaturesView::onSelectionChanged(const Gui::SelectionChanges& msg)
{
    if (syncing) {
        return;
    }
    if (msg.Type != Gui::SelectionChanges::AddSelection && msg.Type != Gui::SelectionChanges::RmvSelection
        && msg.Type != Gui::SelectionChanges::SetSelection
        && msg.Type != Gui::SelectionChanges::ClrSelection) {
        return;
    }
    selectionTimer->start();
}

void FeaturesView::syncSelectionFromApp()
{
    auto doc = document();
    if (!doc || !isVisible()) {
        return;
    }
    std::set<std::string> selected;
    for (const auto& sel : Gui::Selection().getSelection(doc->getName())) {
        if (sel.pObject && sel.pObject->isAttachedToDocument()) {
            selected.insert(sel.pObject->getNameInDocument());
        }
    }
    syncing = true;
    for (int i = 0; i < features->count(); ++i) {
        auto item = features->item(i);
        if (item->type() != FeatureList::BarType) {
            item->setSelected(selected.count(item->data(Qt::UserRole).toByteArray().toStdString()) > 0);
        }
    }
    for (int i = 0; i < parts->topLevelItemCount(); ++i) {
        auto item = parts->topLevelItem(i);
        item->setSelected(selected.count(item->data(0, Qt::UserRole).toByteArray().toStdString()) > 0);
    }
    syncing = false;
}

void FeaturesView::rollStudio(App::Document* doc, App::Part* studio, App::DocumentObject* member, bool toEnd)
{
    if (!doc) {
        return;
    }
    // Its transaction would commit an open edit's: Cancel couldn't take the edit back
    if (ViewProviderBody::isEditLocked(doc)) {
        throw Base::RuntimeError(editLockedMessage);
    }
    const auto bodies = PartDesign::studioBodies(doc, studio);
    std::vector<App::DocumentObject*> oldTips;
    for (auto body : bodies) {
        oldTips.push_back(body->Tip.getValue());
    }
    std::string studioCmd = studio ? Gui::Command::getObjectCmd(studio)
                                   : std::string("App.getDocument('") + doc->getName() + "')";
    int tid = doc->openTransaction(
        toEnd ? QT_TRANSLATE_NOOP("Command", "Roll to end") : QT_TRANSLATE_NOOP("Command", "Roll to here")
    );
    try {
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        if (toEnd) {
            Gui::Command::doCommand(Gui::Command::Doc, "PartDesign.rollStudioToEnd(%s)", studioCmd.c_str());
        }
        else {
            std::string memberCmd = member ? Gui::Command::getObjectCmd(member) : std::string("None");
            Gui::Command::doCommand(
                Gui::Command::Doc,
                "PartDesign.rollStudioTo(%s, %s)",
                studioCmd.c_str(),
                memberCmd.c_str()
            );
        }
        bool changed = false;
        for (std::size_t i = 0; i < bodies.size(); ++i) {
            auto body = bodies[i];
            App::DocumentObject* tip = body->Tip.getValue();
            if (tip == oldTips[i]) {
                continue;
            }
            changed = true;
            // As the tree's bar: show the feature the bar follows (which hides the Body's other
            // features), or none at the very top
            if (tip) {
                FCMD_OBJ_SHOW(tip);
            }
            else {
                for (auto obj : body->Group.getValues()) {
                    if (PartDesign::Body::isSolidFeature(obj) && obj->Visibility.getValue()) {
                        FCMD_OBJ_HIDE(obj);
                    }
                }
            }
        }
        if (!changed) {
            App::GetApplication().abortTransaction(tid);
            return;
        }
        Gui::Command::updateActive();
        App::GetApplication().commitTransaction(tid);
    }
    catch (const Base::Exception&) {
        App::GetApplication().abortTransaction(tid);
        throw;
    }
}

void FeaturesView::onBarDropped(int row)
{
    auto doc = document();
    App::DocumentObject* member = row >= 0 ? objectOf(features->item(row)) : nullptr;
    // After the last row: the end
    bool toEnd = row >= 0 && row == features->count() - 2;
    barHinted = true;
    barHint = member ? member->getNameInDocument() : "";
    try {
        rollStudio(doc, studio(), member, toEnd);
    }
    catch (const Base::Exception& e) {
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
    }
    rebuild();
}

void FeaturesView::rollFromMenu(App::DocumentObject* member, bool toEnd)
{
    barHinted = !toEnd;
    barHint = member && !toEnd ? member->getNameInDocument() : "";
    try {
        rollStudio(document(), studio(), member, toEnd);
    }
    catch (const Base::Exception& e) {
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
    }
    rebuild();
}

void FeaturesView::onFeatureDoubleClicked(QListWidgetItem* item)
{
    if (auto obj = objectOf(item)) {
        if (auto vp = viewProviderOf(obj)) {
            vp->doubleClicked();
        }
    }
}

void FeaturesView::onFeatureMenu(const QPoint& pos)
{
    auto item = features->itemAt(pos);
    App::DocumentObject* obj = objectOf(item);
    if (!obj) {
        return;
    }
    QPointer<FeaturesView> self(this);
    std::string name = obj->getNameInDocument();
    auto runByName = [](const char* command) {
        Gui::Application::Instance->commandManager().runCommandByName(command);
    };
    QMenu menu(this);
    auto edit = menu.addAction(tr("Edit"), [self, name]() {
        auto doc = self ? self->document() : nullptr;
        auto target = doc ? doc->getObject(name.c_str()) : nullptr;
        if (auto vp = target ? viewProviderOf(target) : nullptr) {
            vp->doubleClicked();
        }
    });
    edit->setObjectName(QStringLiteral("featureEdit"));
    menu.addSeparator();
    bool locked = ViewProviderBody::isEditLocked(document());
    auto here = menu.addAction(tr("Roll to here"), [self, name]() {
        auto doc = self ? self->document() : nullptr;
        if (auto target = doc ? doc->getObject(name.c_str()) : nullptr) {
            self->rollFromMenu(target, false);
        }
    });
    here->setObjectName(QStringLiteral("featureRollTo"));
    here->setEnabled(!locked);
    auto end = menu.addAction(tr("Roll to end"), [self]() {
        if (self) {
            self->rollFromMenu(nullptr, true);
        }
    });
    end->setObjectName(QStringLiteral("featureRollToEnd"));
    end->setEnabled(!locked);
    menu.addSeparator();
    auto show = menu.addAction(tr("Show/Hide"), [runByName]() { runByName("Std_ToggleVisibility"); });
    show->setObjectName(QStringLiteral("featureToggleVisibility"));
    auto suppress = menu.addAction(
        isSuppressed(obj) ? tr("Unsuppress") : tr("Suppress"),
        [runByName]() { runByName("Std_ToggleSuppress"); }
    );
    suppress->setObjectName(QStringLiteral("featureToggleSuppress"));
    auto remove = menu.addAction(tr("Delete"), [runByName]() { runByName("Std_Delete"); });
    remove->setObjectName(QStringLiteral("featureDelete"));
    menu.exec(features->viewport()->mapToGlobal(pos));
}

void FeaturesView::onPartClicked(QTreeWidgetItem* item, int column)
{
    if (column != 1) {
        return;
    }
    auto obj = objectOf(item);
    auto vp = obj ? viewProviderOf(obj) : nullptr;
    if (vp && vp->canToggleVisibility()) {
        vp->Gui::ViewProvider::toggleVisibility();
        scheduleRebuild();
    }
}

void FeaturesView::onPartDoubleClicked(QTreeWidgetItem* item, int column)
{
    if (column == 1) {
        return;
    }
    // As the tree's double-click: a Body becomes the active one (ViewProviderBody::doubleClicked())
    if (auto obj = objectOf(item)) {
        if (auto vp = viewProviderOf(obj)) {
            vp->doubleClicked();
        }
    }
}

#include "moc_FeaturesView.cpp"
