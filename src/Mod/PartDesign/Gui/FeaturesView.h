// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// The Features list (FreeCAD-CH ops#602, notes/features-dock-design.md section 6): the studio's
// features in history order with one roll-back bar, and the Parts list, shown in PartDesign in the
// Model panel (the Combo view) in place of its tree, above its Properties panel

#include <string>
#include <vector>

#include <QListWidget>
#include <QPointer>
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

Q_SIGNALS:
    /// The bar was dropped after row (-1: the top)
    void barDropped(int row);
    /// A bar drag was cancelled (Escape): the rows go back
    void barDragCancelled();

protected:
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;

private:
    bool dragging = false;
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

    /// The shown document (null: none) and studio (null: its top level)
    App::Document* document() const;
    App::Part* studio() const;

    /// Rolls every Body of the studio after member (null: the top; toEnd: to the end) in one undo
    /// step, as the tree's bar does (ViewProviderBody::rollBar()); throws Base::Exception
    static void rollStudio(App::Document* doc, App::Part* studio, App::DocumentObject* member, bool toEnd);

protected:
    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    void showEvent(QShowEvent* event) override;

private:
    void scheduleRebuild();
    void rebuild();
    void rebuildFeatures();
    void rebuildParts();
    void syncSelectionFromApp();
    void pushSelection(const std::vector<App::DocumentObject*>& objs);
    App::DocumentObject* objectOf(const QListWidgetItem* item) const;
    App::DocumentObject* objectOf(const QTreeWidgetItem* item) const;
    void watchDocument(const Gui::Document* gdoc);
    void findStudio();

    void onBarDropped(int row);
    void onFeatureMenu(const QPoint& pos);
    void onFeatureDoubleClicked(QListWidgetItem* item);
    void onPartClicked(QTreeWidgetItem* item, int column);
    void onPartDoubleClicked(QTreeWidgetItem* item, int column);
    void rollFromMenu(App::DocumentObject* member, bool toEnd);

    void onChangedObject(const App::DocumentObject& obj, const App::Property& prop);
    void onObject(const App::DocumentObject& obj);
    void onActiveDocument(const Gui::Document& gdoc);
    void onDeleteDocument(const Gui::Document& gdoc);

    FeatureList* features = nullptr;
    QTreeWidget* parts = nullptr;
    QTimer* rebuildTimer = nullptr;
    QTimer* selectionTimer = nullptr;
    bool dirty = true;
    bool syncing = false;

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
