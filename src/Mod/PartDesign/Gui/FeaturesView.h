// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// The Features list (FreeCAD-CH ops#602, notes/features-dock-design.md section 6): the studio's
// features in history order with one roll-back bar, and the Parts list, shown in PartDesign in the
// Model panel (the Combo view) in place of its tree, above its Properties panel

#include <set>
#include <string>
#include <vector>

#include <QLabel>
#include <QListWidget>
#include <QPointer>
#include <QToolButton>
#include <QStyledItemDelegate>
#include <QTimer>
#include <QTreeWidget>

#include <fastsignals/signal.h>

#include <Gui/Selection/Selection.h>

namespace App
{
class Document;
class DocumentObject;
class Part;
class Property;
}  // namespace App

namespace Gui
{
class Document;
class ViewProviderDocumentObject;
}  // namespace Gui

namespace PartDesignGui
{

/// The feature list: rows, and one bar row the user drags between them
class FeatureList: public QListWidget
{
    Q_OBJECT

public:
    explicit FeatureList(QWidget* parent = nullptr);

    /// The bar row's item type
    static constexpr int BarType = QListWidgetItem::UserType + 1;

    QListWidgetItem* barItem() const;
    bool isDraggingBar() const
    {
        return dragging;
    }
    /// The selected rows are being dragged (ops#632)
    bool isDraggingRows() const
    {
        return rowDragging;
    }

Q_SIGNALS:
    /// The bar was dropped after row (-1: the top)
    void barDropped(int row);
    /// A bar drag was cancelled (Escape): the rows go back
    void barDragCancelled();
    /// The selected rows were dropped before row (count(): after the last)
    void rowsDropped(int row);
    /// The selected bar is to move one row up (-1) or down (1): the arrow keys
    void barStepped(int delta);

protected:
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;
    void paintEvent(QPaintEvent* event) override;

private:
    /// The row a drop at pos goes before
    int dropRowAt(const QPoint& pos) const;
    void endRowDrag();

    bool dragging = false;
    /// The bar row moved during its drag: a press and release without a move selects it
    bool barMoved = false;
    /// A plain press on a row: a drag of the selected rows starts when the mouse moves far enough
    bool rowPressed = false;
    bool rowDragging = false;
    /// The press was on a row of a selection of several, and kept it for a drag: a click without
    /// a drag selects the row alone on the release
    bool pressDeferred = false;
    QPoint pressPos;
    int dropRow = -1;
};

/// Paints the bar row as the tree's bar: a thick line with a grip at its start
class FeatureBarDelegate: public QStyledItemDelegate
{
public:
    using QStyledItemDelegate::QStyledItemDelegate;
    void paint(QPainter* painter, const QStyleOptionViewItem& option, const QModelIndex& index) const override;
};

class FeaturesView: public QWidget, public Gui::SelectionObserver
{
    Q_OBJECT

public:
    explicit FeaturesView(QWidget* parent = nullptr);
    ~FeaturesView() override;

    /// The widget, once PartDesign put it in the Model panel, or null
    static FeaturesView* instance();

    /// PartDesign's activation: the lists in place of the Model panel's tree, unless the user chose
    /// the tree (toggleModelTree()). Without the Combo view (turned off in the preferences) it
    /// does nothing
    static void enterPartDesign();
    /// Leaving PartDesign: the tree comes back
    static void leavePartDesign();
    /// The tree in place of the lists, or back (remembered for the next activation)
    static void toggleModelTree();
    /// The user chose the tree in PartDesign
    static bool prefersModelTree();

    /// A Features row's mark from Show dependencies: 1 a parent, 2 a child, 0 none
    static constexpr int DependencyRole = Qt::UserRole + 1;

    /// The shown document (null: none) and studio (null: its top level)
    App::Document* document() const;
    App::Part* studio() const;

    /// Rolls every Body of the studio after member (null: the top; toEnd: to the end) in one undo
    /// step, as the tree's bar does (ViewProviderBody::rollBar()); throws Base::Exception
    static void rollStudio(App::Document* doc, App::Part* studio, App::DocumentObject* member, bool toEnd);
    /// Drags rows to after the row after (null: the top) in one undo step "Reorder", the bar
    /// after bar (hinted), and recomputes (PartDesign.moveInStudio, ops#632); a drop that changes
    /// nothing leaves no step. Throws Base::Exception (a refusal, or a dialog open)
    static void moveRows(App::Document* doc,
                         App::Part* studio,
                         const std::vector<App::DocumentObject*>& rows,
                         App::DocumentObject* after,
                         bool hinted,
                         App::DocumentObject* bar);

protected:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void showEvent(QShowEvent* event) override;

private:
    void scheduleRebuild();
    void rebuild();
    /// Rebuilds the rows even when what they show is unchanged (after a cancelled or refused drag)
    void forceRebuild();
    void rebuildFeatures();
    void rebuildParts();
    void syncSelectionFromApp();
    void pushSelection(const std::vector<App::DocumentObject*>& objs);
    App::DocumentObject* objectOf(const QListWidgetItem* item) const;
    App::DocumentObject* objectOf(const QTreeWidgetItem* item) const;
    void watchDocument(const Gui::Document* gdoc);
    void findStudio();

    void onBarDropped(int row);
    void onRowsDropped(int row);
    /// The selected bar one row up (-1) or down (1), in one undo step
    void stepBar(int delta);
    void onFeatureMenu(const QPoint& pos);
    void onFeatureDoubleClicked(QListWidgetItem* item);
    void onPartClicked(QTreeWidgetItem* item, int column);
    void onPartDoubleClicked(QTreeWidgetItem* item, int column);
    void onPartMenu(const QPoint& pos);
    void rollFromMenu(App::DocumentObject* member, bool toEnd);
    /// Only the failed rows while the header's error icon is down (Onshape's error filter)
    void applyErrorFilter();
    /// Opens the editor on view's current row (F2, Shift+N, the menus' Rename)
    void renameCurrent(QAbstractItemView* view);
    /// The editor's text as obj's Label, in one undo step "Rename"
    void rename(App::DocumentObject* obj, const QString& text);
    void endRename();
    /// Marks obj's parents and children in the Features list (the menu's Show dependencies)
    void showDependencies(App::DocumentObject* obj);
    void markDependencies();

    void onChangedObject(const App::DocumentObject& obj, const App::Property& prop);
    void onObject(const App::DocumentObject& obj);
    void onActiveDocument(const Gui::Document& gdoc);
    void onDeleteDocument(const Gui::Document& gdoc);

    FeatureList* features = nullptr;
    QTreeWidget* parts = nullptr;
    QLabel* title = nullptr;
    QToolButton* errorsButton = nullptr;
    /// A row's name is being edited: rebuilds wait for its commit
    bool renaming = false;
    /// The bar row is selected (for the arrow keys)
    bool barSelected = false;
    /// The rows Show dependencies marked, by object name
    std::set<std::string> dependencyParents;
    std::set<std::string> dependencyChildren;
    QTimer* rebuildTimer = nullptr;
    QTimer* selectionTimer = nullptr;
    bool dirty = true;
    bool syncing = false;
    /// What the rows show (name, label, status), to leave unchanged rows alone: a rebuild drops the
    /// rows' selection anchor, so a Shift+click after it would start over
    std::vector<std::string> featureRows;
    std::vector<std::string> partRows;
    /// The rows' object names (the bar as "|"): unchanged, a changed row is updated in place
    std::vector<std::string> featureNames;
    std::vector<std::string> partNames;

    /// The shown document and studio, by name (an App::Part's, or empty for the top level)
    std::string documentName;
    std::string studioName;
    /// The row the bar was last moved after (barHinted: empty is the top), for studioBarAfter()
    bool barHinted = false;
    std::string barHint;

    std::vector<fastsignals::scoped_connection> connections;
    std::vector<fastsignals::scoped_connection> documentConnections;

    static QPointer<FeaturesView> registered;
};

}  // namespace PartDesignGui
