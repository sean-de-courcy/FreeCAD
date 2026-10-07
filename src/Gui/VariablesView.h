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

#pragma once

#include <set>
#include <string>
#include <vector>

#include <QStandardItemModel>
#include <QStyledItemDelegate>

#include <fastsignals/signal.h>

#include "DockWindow.h"

class QAction;
class QLabel;
class QTimer;
class QTreeView;

namespace App
{
class Document;
class DocumentObject;
class Property;
}  // namespace App

namespace Gui
{
class Document;

namespace DockWnd
{

/** The rows of the Variables panel: one header row per VarSet or Sheet, and under it one row per
 * variable (FreeCAD-CH, ops#152, notes/variables-design.md section 3.6).
 *
 * Columns: Name, Expression, Value, Source. Committing a Name renames the variable; committing an
 * Expression sets the value or the expression. Each edit is one transaction on the variable's
 * document, sent through Python commands with the stored text, so macros and the console stay
 * stock syntax. setData() returns false and sets lastError() when nothing was changed.
 */
class VariablesModel: public QStandardItemModel
{
    Q_OBJECT

public:
    enum Column
    {
        NameColumn,
        ExpressionColumn,
        ValueColumn,
        SourceColumn,
        ColumnCount
    };
    enum Role
    {
        KindRole = Qt::UserRole + 1,
        DocumentRole,
        HolderRole,
        VariableRole,
        AddressRole,
        EditTextRole,
    };
    enum Kind
    {
        HeaderKind,
        VarSetKind,
        AliasKind,
    };

    explicit VariablesModel(QObject* parent = nullptr);

    /// Fills the rows from @a doc's variables; no document gives no rows.
    void rebuild(const App::Document* doc);

    bool setData(const QModelIndex& index, const QVariant& value, int role = Qt::EditRole) override;
    Qt::ItemFlags flags(const QModelIndex& index) const override;

    /// Why the last setData() changed nothing, or a warning about a change it made; else empty.
    const QString& lastError() const
    {
        return error;
    }
    const QString& lastWarning() const
    {
        return warning;
    }

    /// The holder of the row's variable, or of the header row; nullptr if it is gone.
    static App::DocumentObject* holder(const QModelIndex& index);
    /// The property of a VarSet variable, or the cell property of an alias (none before the
    /// sheet's first recompute).
    static App::Property* property(const QModelIndex& index);
    static Kind kind(const QModelIndex& index);

private:
    void addHolderRows(const App::DocumentObject* holder, const std::vector<std::string>& names);
    bool rename(const QModelIndex& index, const QString& newName);
    bool setExpression(const QModelIndex& index, const QString& text);

    QString error;
    QString warning;
};

/// The Expression column's editor: an expression line edit with `#` completion.
class VariablesDelegate: public QStyledItemDelegate
{
    Q_OBJECT

public:
    explicit VariablesDelegate(QObject* parent = nullptr);

    QWidget* createEditor(
        QWidget* parent,
        const QStyleOptionViewItem& option,
        const QModelIndex& index
    ) const override;
    void setEditorData(QWidget* editor, const QModelIndex& index) const override;
    void setModelData(
        QWidget* editor,
        QAbstractItemModel* model,
        const QModelIndex& index
    ) const override;

Q_SIGNALS:
    /// A commit changed nothing: @a text is what was typed, to edit again.
    void commitFailed(const QModelIndex& index, const QString& text) const;
    void committed() const;

private:
    mutable QPersistentModelIndex retryIndex;
    mutable QString retryText;

    friend class VariablesView;
};

/** The Variables dock window (`Std_VariablesView`, hidden by default): the active document's VarSet
 * variables and sheet aliases, editable in place (FreeCAD-CH, ops#152).
 */
class VariablesView: public DockWindow
{
    Q_OBJECT

public:
    explicit VariablesView(Gui::Document* doc, QWidget* parent = nullptr);
    ~VariablesView() override;

    const char* getName() const override
    {
        return "VariablesView";
    }

protected:
    void showEvent(QShowEvent* ev) override;

private:
    void scheduleRebuild();
    void rebuild();
    void onChangedObject(const App::DocumentObject& obj, const App::Property& prop);
    void onObject(const App::DocumentObject& obj);
    void onProperty(const App::Property& prop);
    void onActiveDocument(const Gui::Document& doc);
    void onDeleteDocument(const Gui::Document& doc);
    void onCommitFailed(const QModelIndex& index, const QString& text);
    void onDoubleClicked(const QModelIndex& index);
    void updateActions();
    void showMessage(const QString& text, bool isError);

    void addVariable();
    void deleteVariable();
    void showUses();
    QString usesText(const QModelIndex& index, int* count) const;

    App::Document* currentDocument() const;
    bool isRelevant(const App::DocumentObject* obj) const;

    QTreeView* tree;
    VariablesModel* model;
    VariablesDelegate* delegate;
    QLabel* hint;
    QLabel* message;
    QTimer* timer;
    QAction* addAction;
    QAction* deleteAction;
    QAction* usesAction;
    std::string documentName;
    std::set<std::string> collapsed;

    std::vector<fastsignals::scoped_connection> connections;
};

}  // namespace DockWnd
}  // namespace Gui
