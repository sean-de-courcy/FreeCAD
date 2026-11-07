// SPDX-License-Identifier: LGPL-2.1-or-later

#include "FeaturesView.h"

#include <algorithm>
#include <set>

#include <QApplication>
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
#include <Mod/PartDesign/App/FeatureDeletePart.h>
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

/// Why the features don't move during an edit (design 3.3, the bar's rule)
constexpr const char* reorderLockedMessage = QT_TRANSLATE_NOOP(
    "Exception",
    "The features can't be reordered while a dialog or an edit is open"
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

/// For each of bodies whose Tip isn't its old one, as the tree's bar does: shows the feature the
/// bar follows (which hides the Body's other features), or none at the very top. False when no
/// Tip moved
bool showMovedTips(const std::vector<PartDesign::Body*>& bodies, const std::vector<App::DocumentObject*>& oldTips)
{
    bool changed = false;
    for (std::size_t i = 0; i < bodies.size(); ++i) {
        auto body = bodies[i];
        App::DocumentObject* tip = body->Tip.getValue();
        if (tip == oldTips[i]) {
            continue;
        }
        changed = true;
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
    return changed;
}

/// What a row shows of obj: its name, label and status (statusIcon(), statusFont())
std::string rowKey(const App::DocumentObject* obj, bool held, const std::string& extra = {})
{
    std::string key = obj->getNameInDocument();
    key += '\x1f';
    key += obj->Label.getValue();
    key += '\x1f';
    key += obj->isError() ? 'e' : obj->isWarning() ? 'w' : '-';
    key += held ? 'h' : '-';
    key += obj->isTouched() || obj->mustExecute() == 1 ? 't' : '-';
    key += isSuppressed(obj) ? 's' : '-';
    key += extra;
    return key;
}

/// The studio's parts: its Bodies with a solid feature at or above their bar, and the other solids
/// at its level (an imported shape, a Part workbench feature) that no other shape reads. A part
/// exists only while the history makes it, as in Onshape (ops#635): a Body whose new-part feature
/// was deleted, whose bar is at its top, or that a Delete part deleted, isn't one; it keeps its
/// sketches, and shows nothing
std::vector<App::DocumentObject*> studioParts(App::Document* doc, App::Part* studio)
{
    std::vector<App::DocumentObject*> parts;
    for (auto body : PartDesign::studioBodies(doc, studio)) {
        if (body->Tip.getValue() && !PartDesign::DeletePart::deleterOf(body)) {
            parts.push_back(body);
        }
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

int FeatureList::dropRowAt(const QPoint& pos) const
{
    // Before the row under the cursor, or after it in the row's lower half
    if (auto target = itemAt(pos)) {
        return row(target) + (pos.y() > visualItemRect(target).center().y() ? 1 : 0);
    }
    return pos.y() < 0 ? 0 : count();
}

void FeatureList::endRowDrag()
{
    rowPressed = false;
    rowDragging = false;
    pressDeferred = false;
    dropRow = -1;
    unsetCursor();
    viewport()->update();
}

void FeatureList::mousePressEvent(QMouseEvent* event)
{
    QPoint pos = event->position().toPoint();
    auto pressed = itemAt(pos);
    if (event->button() == Qt::LeftButton && pressed && pressed->type() == BarType) {
        dragging = true;
        setCursor(Qt::ClosedHandCursor);
        event->accept();
        return;
    }
    // A plain press on a row may start a drag of the selected rows (ops#632). On a row of a
    // selection of several it keeps the selection until the release, as Qt does with drags on
    if (event->button() == Qt::LeftButton && pressed && event->modifiers() == Qt::NoModifier) {
        rowPressed = true;
        pressPos = pos;
        if (pressed->isSelected() && selectedItems().size() > 1) {
            pressDeferred = true;
            event->accept();
            return;
        }
    }
    QListWidget::mousePressEvent(event);
}

void FeatureList::mouseMoveEvent(QMouseEvent* event)
{
    if (rowPressed) {
        QPoint pos = event->position().toPoint();
        if (!rowDragging && (event->buttons() & Qt::LeftButton)
            && (pos - pressPos).manhattanLength() >= QApplication::startDragDistance()) {
            rowDragging = true;
            setCursor(Qt::ClosedHandCursor);
        }
        if (rowDragging) {
            dropRow = dropRowAt(pos);
            viewport()->update();
        }
        // Not the list's own drag selection: the press is a drag's
        event->accept();
        return;
    }
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
    if (rowDragging) {
        int before = dropRow;
        endRowDrag();
        event->accept();
        Q_EMIT rowsDropped(before);
        return;
    }
    if (pressDeferred) {
        // A click on a row of the selection, without a drag: the press it held back
        QMouseEvent press(
            QEvent::MouseButtonPress,
            event->position(),
            event->globalPosition(),
            Qt::LeftButton,
            Qt::LeftButton,
            Qt::NoModifier
        );
        QListWidget::mousePressEvent(&press);
    }
    if (rowPressed) {
        endRowDrag();
    }
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
    if (rowDragging && event->key() == Qt::Key_Escape) {
        endRowDrag();
        event->accept();
        return;
    }
    if (dragging && event->key() == Qt::Key_Escape) {
        dragging = false;
        unsetCursor();
        event->accept();
        Q_EMIT barDragCancelled();
        return;
    }
    QListWidget::keyPressEvent(event);
}

void FeatureList::paintEvent(QPaintEvent* event)
{
    QListWidget::paintEvent(event);
    if (!rowDragging || dropRow < 0 || count() == 0) {
        return;
    }
    // Where the dragged rows go: a line in the highlight colour
    int y = dropRow < count() ? visualItemRect(item(dropRow)).top()
                              : visualItemRect(item(count() - 1)).bottom() + 1;
    QPainter painter(viewport());
    painter.setPen(QPen(palette().color(QPalette::Highlight), 2));
    painter.drawLine(0, y, viewport()->width(), y);
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
    connect(features, &FeatureList::barDragCancelled, this, &FeaturesView::forceRebuild);
    connect(features, &FeatureList::rowsDropped, this, &FeaturesView::onRowsDropped);
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
        featureRows.clear();
        partRows.clear();
        featureNames.clear();
        partNames.clear();
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
    // The order follows the links and the saved ranks; the rows show Label, the held look the
    // Tip, the status Suppressed, the Parts list's eye Visibility
    const char* name = prop.getName();
    bool shown = name
        && (strcmp(name, "Group") == 0 || strcmp(name, "Tip") == 0 || strcmp(name, "Label") == 0
            || strcmp(name, "Suppressed") == 0 || strcmp(name, "Visibility") == 0
            || strcmp(name, "HistoryRank") == 0);
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
    // Not under the user's hand: a drag ends with its own rebuild
    if (features->isDraggingBar() || features->isDraggingRows()) {
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

void FeaturesView::forceRebuild()
{
    featureRows.clear();
    partRows.clear();
    featureNames.clear();
    partNames.clear();
    rebuild();
}

void FeaturesView::rebuildFeatures()
{
    auto doc = document();
    if (!doc) {
        features->clear();
        featureRows.clear();
        featureNames.clear();
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
    // The rows in list order: a member's index in sequence, or -1 for the bar (none in an empty
    // studio)
    std::vector<int> order;
    std::vector<bool> held;
    std::vector<std::string> rows;
    std::vector<std::string> names;
    for (std::size_t i = 0; i < sequence.size(); ++i) {
        if (i == barRow) {
            order.push_back(-1);
        }
        order.push_back(static_cast<int>(i));
    }
    if (barRow >= sequence.size() && !sequence.empty()) {
        order.push_back(-1);
    }
    for (std::size_t i = 0; i < sequence.size(); ++i) {
        auto body = PartDesign::Body::findBodyOf(sequence[i]);
        held.push_back(body && body->holds(sequence[i]));
    }
    for (int index : order) {
        if (index < 0) {
            rows.emplace_back("|");
            names.emplace_back("|");
            continue;
        }
        auto obj = sequence[index];
        auto body = PartDesign::Body::findBodyOf(obj);
        rows.push_back(rowKey(obj, held[index], body ? body->Label.getValue() : ""));
        names.emplace_back(obj->getNameInDocument());
    }
    // Unchanged: the rows (and the user's selection anchor in them) stay
    if (rows == featureRows && features->count() == static_cast<int>(rows.size())) {
        return;
    }
    // The same rows in the same order (a status or a label changed): updated in place, so a
    // selection and its Shift anchor survive (review props602-r1fix R2)
    bool inPlace = names == featureNames && features->count() == static_cast<int>(names.size());
    featureRows = rows;
    featureNames = names;
    auto decorate = [this](QListWidgetItem* item, App::DocumentObject* obj, bool isHeld) {
        auto body = PartDesign::Body::findBodyOf(obj);
        item->setText(QString::fromUtf8(obj->Label.getValue()));
        item->setData(Qt::UserRole, QByteArray(obj->getNameInDocument()));
        item->setIcon(statusIcon(obj, isHeld));
        item->setFont(statusFont(features->font(), obj, isHeld));
        if (body) {
            item->setToolTip(tr("%1 (%2)").arg(
                QString::fromUtf8(obj->Label.getValue()),
                QString::fromUtf8(body->Label.getValue())
            ));
        }
    };
    if (inPlace) {
        for (std::size_t r = 0; r < order.size(); ++r) {
            if (order[r] >= 0) {
                decorate(features->item(static_cast<int>(r)), sequence[order[r]], held[order[r]]);
            }
        }
        return;
    }
    int scroll = features->verticalScrollBar() ? features->verticalScrollBar()->value() : 0;
    features->clear();
    for (int index : order) {
        if (index < 0) {
            auto bar = new QListWidgetItem(features, FeatureList::BarType);
            bar->setFlags(Qt::ItemIsEnabled);
            bar->setSizeHint(QSize(0, 9));
            bar->setToolTip(tr("Roll-back bar: drag it to roll every body of the part studio back"));
            continue;
        }
        decorate(new QListWidgetItem(features), sequence[index], held[index]);
    }
    if (auto bar = features->verticalScrollBar()) {
        bar->setValue(scroll);
    }
}

void FeaturesView::rebuildParts()
{
    auto doc = document();
    if (!doc) {
        parts->clear();
        partRows.clear();
        partNames.clear();
        return;
    }
    const auto objs = studioParts(doc, studio());
    std::vector<std::string> rows;
    std::vector<std::string> names;
    for (auto obj : objs) {
        auto body = freecad_cast<PartDesign::Body*>(obj);
        auto vp = viewProviderOf(obj);
        std::string eye = !vp || !vp->canToggleVisibility() ? "" : vp->isShow() ? "v" : "i";
        rows.push_back(rowKey(obj, body && body->isRolledBack(), eye));
        names.emplace_back(obj->getNameInDocument());
    }
    if (rows == partRows && parts->topLevelItemCount() == static_cast<int>(rows.size())) {
        return;
    }
    bool inPlace = names == partNames && parts->topLevelItemCount() == static_cast<int>(names.size());
    partRows = rows;
    partNames = names;
    QIcon visible(Gui::BitmapFactory().pixmap("TreeItemVisible"));
    QIcon invisible(Gui::BitmapFactory().pixmap("TreeItemInvisible"));
    if (!inPlace) {
        parts->clear();
    }
    for (std::size_t i = 0; i < objs.size(); ++i) {
        auto obj = objs[i];
        auto body = freecad_cast<PartDesign::Body*>(obj);
        bool held = body && body->isRolledBack();
        auto item = inPlace ? parts->topLevelItem(static_cast<int>(i)) : new QTreeWidgetItem(parts);
        item->setText(0, QString::fromUtf8(obj->Label.getValue()));
        item->setData(0, Qt::UserRole, QByteArray(obj->getNameInDocument()));
        item->setIcon(0, statusIcon(obj, held));
        item->setFont(0, statusFont(parts->font(), obj, held));
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
    // The other list follows (review props602s-r1, finding 1: a Parts row stayed selected)
    selectionTimer->start();
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
    // Only the rows that differ: setSelected() on a row commits the range a Shift+click is still
    // building, so the next Shift+click couldn't shrink it (review props602-r1fix R2)
    syncing = true;
    for (int i = 0; i < features->count(); ++i) {
        auto item = features->item(i);
        bool want = selected.count(item->data(Qt::UserRole).toByteArray().toStdString()) > 0;
        if (item->type() != FeatureList::BarType && item->isSelected() != want) {
            item->setSelected(want);
        }
    }
    for (int i = 0; i < parts->topLevelItemCount(); ++i) {
        auto item = parts->topLevelItem(i);
        bool want = selected.count(item->data(0, Qt::UserRole).toByteArray().toStdString()) > 0;
        if (item->isSelected() != want) {
            item->setSelected(want);
        }
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
    // FreeCAD-CH (ops#640): refused beside an open dialog's held step; commitTransaction(0)
    // would commit that step behind the dialog
    if (tid == 0 && doc->isStepLocked()) {
        throw Base::RuntimeError("Finish the open dialog first");
    }
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
        if (!showMovedTips(bodies, oldTips)) {
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
    // The dragged bar row moved without the signature knowing
    forceRebuild();
}

void FeaturesView::onRowsDropped(int row)
{
    auto doc = document();
    if (!doc || row < 0) {
        return;
    }
    // The dragged rows (the selected ones), and the list as dropped: the other rows and the bar,
    // with the dragged rows before row
    std::vector<App::DocumentObject*> rows;
    std::set<int> dragged;
    for (int i = 0; i < features->count(); ++i) {
        auto item = features->item(i);
        if (item->isSelected() && item->type() != FeatureList::BarType) {
            if (auto obj = objectOf(item)) {
                rows.push_back(obj);
                dragged.insert(i);
            }
        }
    }
    if (rows.empty()) {
        return;
    }
    std::vector<App::DocumentObject*> listed;  // the bar as null
    std::size_t dropAt = 0;
    int barAt = -1;
    for (int i = 0; i <= features->count(); ++i) {
        if (i == row) {
            dropAt = listed.size();
            listed.insert(listed.end(), rows.begin(), rows.end());
        }
        if (i == features->count()) {
            break;
        }
        if (dragged.count(i)) {
            continue;
        }
        auto item = features->item(i);
        if (item->type() == FeatureList::BarType) {
            barAt = static_cast<int>(listed.size());
            listed.push_back(nullptr);
            continue;
        }
        listed.push_back(objectOf(item));
    }
    // What each goes after: the last row above it (null: the top)
    auto rowBefore = [&listed](std::size_t end) -> App::DocumentObject* {
        for (std::size_t i = end; i-- > 0;) {
            if (listed[i]) {
                return listed[i];
            }
        }
        return nullptr;
    };
    App::DocumentObject* after = rowBefore(dropAt);
    App::DocumentObject* bar = barAt >= 0 ? rowBefore(static_cast<std::size_t>(barAt)) : nullptr;
    std::string barName = bar ? bar->getNameInDocument() : "";
    bool rolledBack = PartDesign::isStudioRolledBack(doc, studio());
    try {
        moveRows(doc, studio(), rows, after, barAt >= 0, bar);
        // Rolled back, the bar stays where the list showed it as dropped (at the end it stays
        // at the end)
        if (rolledBack && barAt >= 0) {
            barHinted = true;
            barHint = barName;
        }
    }
    catch (const Base::Exception& e) {
        Gui::getMainWindow()->showMessage(QString::fromUtf8(e.what()), 5000);
    }
    forceRebuild();
}

void FeaturesView::moveRows(App::Document* doc,
                            App::Part* studio,
                            const std::vector<App::DocumentObject*>& rows,
                            App::DocumentObject* after,
                            bool hinted,
                            App::DocumentObject* bar)
{
    if (!doc || rows.empty()) {
        return;
    }
    // Its transaction would commit an open edit's, as the bar's
    if (ViewProviderBody::isEditLocked(doc)) {
        throw Base::RuntimeError(reorderLockedMessage);
    }
    const auto bodies = PartDesign::studioBodies(doc, studio);
    std::vector<App::DocumentObject*> oldTips;
    for (auto body : bodies) {
        oldTips.push_back(body->Tip.getValue());
    }
    const auto oldSequence = PartDesign::studioSequence(doc, studio);
    auto objCmd = [](App::DocumentObject* obj) {
        return obj ? Gui::Command::getObjectCmd(obj) : std::string("None");
    };
    std::string studioCmd = studio ? Gui::Command::getObjectCmd(studio)
                                   : std::string("App.getDocument('") + doc->getName() + "')";
    std::string rowsCmd = "[";
    for (auto obj : rows) {
        rowsCmd += (rowsCmd.size() > 1 ? ", " : "") + objCmd(obj);
    }
    rowsCmd += "]";
    std::string barCmd = hinted ? ", " + objCmd(bar) : std::string();
    int tid = doc->openTransaction(QT_TRANSLATE_NOOP("Command", "Reorder"));
    // FreeCAD-CH (ops#640): refused beside an open dialog's held step; commitTransaction(0)
    // would commit that step behind the dialog
    if (tid == 0 && doc->isStepLocked()) {
        throw Base::RuntimeError("Finish the open dialog first");
    }
    try {
        Gui::Command::doCommand(Gui::Command::Doc, "import PartDesign");
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "PartDesign.moveInStudio(%s, %s, %s%s)",
            studioCmd.c_str(),
            rowsCmd.c_str(),
            objCmd(after).c_str(),
            barCmd.c_str()
        );
        bool tipsMoved = showMovedTips(bodies, oldTips);
        if (!tipsMoved && PartDesign::studioSequence(doc, studio) == oldSequence) {
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
