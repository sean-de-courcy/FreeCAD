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

#include <cmath>
#include <cstring>
#include <limits>
#include <map>
#include <set>
#include <sstream>
#include <vector>

#include <QAction>
#include <QHeaderView>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QTimer>
#include <QToolBar>
#include <QTreeView>
#include <QVBoxLayout>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Expression.h>
#include <App/ExpressionParser.h>
#include <App/PropertyStandard.h>
#include <App/PropertyUnits.h>
#include <App/Range.h>
#include <App/VarSet.h>
#include <App/VariableLookup.h>
#include <Base/Interpreter.h>
#include <Base/Quantity.h>
#include <Base/Tools.h>
#include <CXX/Objects.hxx>

#include "Application.h"
#include "BitmapFactory.h"
#include "Command.h"
#include "Document.h"
#include "ExpressionCompleter.h"
#include "MainWindow.h"
#include "Selection/Selection.h"
#include "Dialogs/DlgAddProperty.h"
#include "VariablesView.h"

using namespace Gui;
using namespace Gui::DockWnd;
namespace sp = std::placeholders;

namespace
{

/// `u'...'` for a Python command line.
std::string pyString(const std::string& text)
{
    return "u'"
        + Base::Tools::escapeQuotesFromString(Base::Tools::escapedUnicodeFromUtf8(text.c_str()))
        + "'";
}

std::string pyObject(const App::DocumentObject* obj)
{
    std::ostringstream str;
    str << "App.getDocument('" << obj->getDocument()->getName() << "').getObject('"
        << obj->getNameInDocument() << "')";
    return str.str();
}

bool isSheet(const App::DocumentObject* obj)
{
    // Looked up each time: the Spreadsheet module may load after the panel is made.
    Base::Type type = Base::Type::fromName("Spreadsheet::Sheet");
    return !type.isBad() && obj->isDerivedFrom(type);
}

/// Calls a method of @a obj's Python object with string arguments; an empty string on any error.
std::string callString(
    const App::DocumentObject* obj,
    const char* method,
    const std::vector<std::string>& args
)
{
    Base::PyGILStateLocker lock;
    try {
        Py::Object pyObj(const_cast<App::DocumentObject*>(obj)->getPyObject(), true);
        Py::Callable function(pyObj.getAttr(method));
        Py::Tuple pyArgs(args.size());
        for (std::size_t i = 0; i < args.size(); ++i) {
            pyArgs.setItem(i, Py::String(args[i]));
        }
        Py::Object result = function.apply(pyArgs);
        if (result.isString()) {
            return Py::String(result).as_std_string("utf-8");
        }
    }
    catch (Py::Exception&) {
        PyErr_Clear();
    }
    return {};
}

/// The property type without its prefix: "Length" for App::PropertyLength.
QString typeName(const App::Property* prop)
{
    std::string name(prop->getTypeId().getName());
    for (const char* prefix : {"App::Property", "App::"}) {
        if (name.starts_with(prefix)) {
            name = name.substr(std::strlen(prefix));
            break;
        }
    }
    return QString::fromStdString(name);
}

/// The property's value as the user reads it: a quantity with its unit, like the property editor.
QString valueText(const App::Property* prop)
{
    if (!prop) {
        return {};
    }
    if (auto quantity = freecad_cast<const App::PropertyQuantity*>(prop)) {
        return QString::fromStdString(quantity->getQuantityValue().getUserString());
    }
    if (auto number = freecad_cast<const App::PropertyFloat*>(prop)) {
        return QString::number(number->getValue(), 'g', 12);
    }
    if (auto number = freecad_cast<const App::PropertyInteger*>(prop)) {
        return QString::number(number->getValue());
    }
    if (auto flag = freecad_cast<const App::PropertyBool*>(prop)) {
        return flag->getValue() ? QStringLiteral("True") : QStringLiteral("False");
    }
    if (auto text = freecad_cast<const App::PropertyString*>(prop)) {
        return QString::fromUtf8(text->getValue());
    }
    Base::PyGILStateLocker lock;
    try {
        Py::Object value(const_cast<App::Property*>(prop)->getPyObject(), true);
        return QString::fromStdString(value.str().as_std_string("utf-8"));
    }
    catch (Py::Exception&) {
        PyErr_Clear();
    }
    return {};
}

bool isNumeric(const App::Property* prop)
{
    return freecad_cast<const App::PropertyFloat*>(prop)
        || freecad_cast<const App::PropertyInteger*>(prop);
}

/// Runs @a commands as one transaction named @a name on @a doc; false and @a error on failure,
/// with the transaction aborted. A transaction already booked (a task dialog's) takes the edit.
bool runEdit(
    App::Document* doc,
    const std::string& name,
    const std::vector<std::string>& commands,
    QString& error
)
{
    bool own = doc->getBookedTransactionID() == 0;
    if (own) {
        doc->openTransaction(name);
    }
    try {
        for (const auto& command : commands) {
            Gui::Command::runCommand(Gui::Command::Doc, command.c_str());
        }
    }
    catch (const Base::Exception& e) {
        if (own) {
            doc->abortTransaction();
        }
        error = QString::fromUtf8(e.what());
        return false;
    }
    catch (...) {
        if (own) {
            doc->abortTransaction();
        }
        throw;
    }
    if (own) {
        doc->commitTransaction();
    }
    return true;
}

/// Whether @a text has a '#' that the parser resolves as a variable, as App's rewriteVariableRefs
/// finds them: one followed by an identifier start, outside a `<<...>>` string and not after a
/// word. `#Width` has one; `Part #3`, `# of`, `#1`, `Lot#A` and `<<a #b>>` don't.
bool hasVariableRef(const QString& text)
{
    auto isPart = [](QChar c) {
        return c == u'_' || c == u'@' || c.isLetterOrNumber() || c.isMark();
    };
    enum class Prev
    {
        Other,
        Word
    } prev = Prev::Other;
    for (qsizetype i = 0; i < text.size(); ++i) {
        QChar c = text[i];
        if (c == u' ' || c == u'\t' || c == u'\n' || c == u'\r') {
            continue;
        }
        if (c == u'<' && i + 1 < text.size() && text[i + 1] == u'<') {
            // A string, as the lexer takes one: up to `>>`, with backslash escapes, on one line.
            qsizetype end = -1;
            for (qsizetype j = i + 2; j < text.size(); ++j) {
                if (text[j] == u'\\') {
                    ++j;
                }
                else if (text[j] == u'\n') {
                    break;
                }
                else if (text[j] == u'>') {
                    if (j + 1 < text.size() && text[j + 1] == u'>') {
                        end = j + 2;
                    }
                    break;
                }
            }
            prev = end < 0 ? Prev::Other : Prev::Word;  // The rewriter's String acts as a Word.
            i = end < 0 ? i + 1 : end - 1;
            continue;
        }
        if (c == u'#' && prev == Prev::Other && i + 1 < text.size()
            && (text[i + 1] == u'_' || text[i + 1].isLetter())) {
            return true;
        }
        prev = isPart(c) ? Prev::Word : Prev::Other;
    }
    return false;
}

/// Whether @a text, typed for an alias or a String or Bool variable, is meant as an expression:
/// it starts with '=', or it uses `#name`, or it parses and names only things that exist, more
/// than a bare name or path. Any other text is stored as it is: `steel` edited to `bronze` stays a
/// text, not a reference to nothing, and so do `Part #3` and a single word like `Label` (ops#188).
/// A `#name` that doesn't resolve (`#Widht`, or one held by two variables) makes it an expression
/// too, so its error is shown rather than the text stored.
bool isExpressionText(const App::DocumentObject* owner, const std::string& text)
{
    if (text.starts_with('=') || hasVariableRef(QString::fromStdString(text))) {
        return true;
    }
    std::shared_ptr<App::Expression> expr;
    try {
        expr = App::Expression::parse(owner, text);
    }
    catch (const Base::Exception&) {
        return false;
    }
    if (freecad_cast<App::VariableExpression*>(expr.get())) {
        return false;  // A bare name or path: `=Label` or `#Width` makes it a reference.
    }
    std::map<App::ObjectIdentifier, bool> ids;
    expr->getIdentifiers(ids);
    if (ids.empty()) {
        return false;
    }
    for (const auto& [id, hidden] : ids) {
        if (!id.getProperty()) {
            return false;
        }
    }
    return true;
}

/// The value of @a text for a Bool variable: 1 for true, 0 for false, -1 if it is neither.
int boolValue(const QString& text)
{
    if (text.compare(QLatin1String("True"), Qt::CaseInsensitive) == 0 || text == QLatin1String("1")) {
        return 1;
    }
    if (text.compare(QLatin1String("False"), Qt::CaseInsensitive) == 0 || text == QLatin1String("0")) {
        return 0;
    }
    return -1;
}

/// The panel's tree: says whether an editor is open (state() is protected).
class VariablesTree: public QTreeView
{
public:
    using QTreeView::QTreeView;
    bool isEditing() const
    {
        return state() == EditingState;
    }
};

/// Whether @a name may name a variable: an identifier that isn't a unit, a constant or a cell.
bool isValidName(const std::string& name)
{
    return App::ExpressionParser::isTokenAnIndentifier(name)
        && !App::ExpressionParser::isTokenAUnit(name)
        && !App::ExpressionParser::isTokenAConstant(name)
        && !App::stringToAddress(name.c_str(), true).isValid();
}

}  // namespace

/* TRANSLATOR Gui::DockWnd::VariablesView */

// ----------------------------------------------------------------------------------------------

VariablesModel::VariablesModel(QObject* parent)
    : QStandardItemModel(parent)
{
    setColumnCount(ColumnCount);
    setHorizontalHeaderLabels({tr("Name"), tr("Expression"), tr("Value"), tr("Source")});
}

void VariablesModel::rebuild(const App::Document* doc)
{
    removeRows(0, rowCount());
    if (!doc) {
        return;
    }
    // listVariables gives the variables per object, in the document's object order.
    const App::DocumentObject* holder = nullptr;
    std::vector<std::string> names;
    for (const auto& var : App::VariableLookup::listVariables(doc)) {
        if (var.holder != holder) {
            if (holder) {
                addHolderRows(holder, names);
            }
            holder = var.holder;
            names.clear();
        }
        names.push_back(var.name);
    }
    if (holder) {
        addHolderRows(holder, names);
    }
}

void VariablesModel::addHolderRows(
    const App::DocumentObject* holder,
    const std::vector<std::string>& names
)
{
    bool sheet = isSheet(holder);
    QString docName = QString::fromLatin1(holder->getDocument()->getName());
    QString holderName = QString::fromLatin1(holder->getNameInDocument());
    QString label = QString::fromUtf8(holder->Label.getValue());

    auto header = new QStandardItem(label);
    header->setData(HeaderKind, KindRole);
    header->setData(docName, DocumentRole);
    header->setData(holderName, HolderRole);
    header->setToolTip(QString::fromLatin1(holder->getNameInDocument()));
    QList<QStandardItem*> headerRow {header};
    for (int column = 1; column < ColumnCount; ++column) {
        auto item = new QStandardItem();
        item->setData(HeaderKind, KindRole);
        headerRow << item;
    }
    appendRow(headerRow);

    for (const auto& name : names) {
        QString varName = QString::fromStdString(name);
        QString address;
        QString expression;
        App::Property* prop = holder->getPropertyByName(name.c_str());
        QString tip;

        if (sheet) {
            address = QString::fromStdString(callString(holder, "getCellFromAlias", {name}));
            std::string content = callString(holder, "getContents", {address.toStdString()});
            expression = QString::fromStdString(content);
            if (content.starts_with('=')) {
                try {
                    auto expr = App::Expression::parse(holder, content.substr(1));
                    expression = QString::fromStdString(App::toDisplayString(expr.get()));
                }
                catch (const Base::Exception&) {
                    // A cell that no longer parses shows its content as it is.
                }
            }
            tip = tr("Alias of %1 %2").arg(label, address);
        }
        else if (prop) {
            auto info = holder->getExpression(App::ObjectIdentifier(*prop));
            expression = info.expression
                ? QString::fromStdString(App::toDisplayString(info.expression.get()))
                : valueText(prop);
            tip = tr("%1 (%2)").arg(varName, typeName(prop));
        }

        auto nameItem = new QStandardItem(varName);
        auto exprItem = new QStandardItem(expression);
        exprItem->setData(expression, EditTextRole);
        auto valueItem = new QStandardItem(valueText(prop));
        auto sourceItem = new QStandardItem(
            sheet ? QStringLiteral("%1 %2").arg(label, address) : label
        );
        QList<QStandardItem*> row {nameItem, exprItem, valueItem, sourceItem};
        for (auto item : row) {
            item->setData(sheet ? AliasKind : VarSetKind, KindRole);
            item->setData(docName, DocumentRole);
            item->setData(holderName, HolderRole);
            item->setData(varName, VariableRole);
            item->setData(address, AddressRole);
            item->setToolTip(tip);
        }
        if (holder->isError() && !expression.isEmpty()) {
            valueItem->setForeground(Qt::red);
            valueItem->setToolTip(QString::fromUtf8(holder->getStatusString()));
        }
        header->appendRow(row);
    }
}

Qt::ItemFlags VariablesModel::flags(const QModelIndex& index) const
{
    Qt::ItemFlags result = QStandardItemModel::flags(index) & ~Qt::ItemIsEditable;
    if (kind(index) != HeaderKind
        && (index.column() == NameColumn || index.column() == ExpressionColumn)) {
        result |= Qt::ItemIsEditable;
    }
    return result;
}

VariablesModel::Kind VariablesModel::kind(const QModelIndex& index)
{
    return static_cast<Kind>(index.data(KindRole).toInt());
}

App::DocumentObject* VariablesModel::holder(const QModelIndex& index)
{
    if (!index.isValid()) {
        return nullptr;
    }
    QModelIndex first = index.sibling(index.row(), 0);
    App::Document* doc = App::GetApplication().getDocument(
        first.data(DocumentRole).toString().toLatin1().constData()
    );
    if (!doc) {
        return nullptr;
    }
    return doc->getObject(first.data(HolderRole).toString().toLatin1().constData());
}

App::Property* VariablesModel::property(const QModelIndex& index)
{
    App::DocumentObject* obj = holder(index);
    if (!obj || kind(index) == HeaderKind) {
        return nullptr;
    }
    return obj->getPropertyByName(index.data(VariableRole).toString().toStdString().c_str());
}

bool VariablesModel::setData(const QModelIndex& index, const QVariant& value, int role)
{
    if (role != Qt::EditRole || kind(index) == HeaderKind) {
        return QStandardItemModel::setData(index, value, role);
    }
    error.clear();
    warning.clear();
    if (index.column() == NameColumn) {
        return rename(index, value.toString().trimmed());
    }
    if (index.column() == ExpressionColumn) {
        return setExpression(index, value.toString().trimmed());
    }
    return false;
}

bool VariablesModel::rename(const QModelIndex& index, const QString& newName)
{
    App::DocumentObject* obj = holder(index);
    std::string oldName = index.data(VariableRole).toString().toStdString();
    std::string name = newName.toStdString();
    if (!obj) {
        error = tr("The variable's object is gone.");
        return false;
    }
    if (name == oldName) {
        return true;
    }
    if (!isValidName(name)) {
        error = tr("'%1' is not a valid name: use a name that isn't a unit, a constant or a cell "
                   "address.")
                    .arg(newName);
        return false;
    }
    if (App::VariableLookup::isVariable(obj, name)
        || (!isSheet(obj) && obj->getPropertyByName(name.c_str()))) {
        error = tr("%1 already has '%2'.").arg(QString::fromUtf8(obj->Label.getValue()), newName);
        return false;
    }

    std::string command;
    if (kind(index) == AliasKind) {
        command = pyObject(obj) + ".setAlias('"
            + index.data(AddressRole).toString().toStdString() + "', " + pyString(name) + ")";
    }
    else {
        command = pyObject(obj) + ".renameProperty(" + pyString(oldName) + ", " + pyString(name)
            + ")";
    }
    std::string transaction = "Rename " + oldName + " to " + name;
    if (!runEdit(obj->getDocument(), transaction, {command}, error)) {
        return false;
    }
    if (App::VariableLookup::find(obj->getDocument(), name).size() > 1) {
        warning = tr("#%1 becomes ambiguous for new expressions: another variable has that name. "
                     "Existing expressions keep what they use.")
                      .arg(newName);
    }
    return true;
}

bool VariablesModel::setExpression(const QModelIndex& index, const QString& text)
{
    App::DocumentObject* obj = holder(index);
    if (!obj) {
        error = tr("The variable's object is gone.");
        return false;
    }
    if (text == index.data(EditTextRole).toString()) {
        return true;  // Unchanged: a value shown rounded isn't rounded by committing it.
    }
    std::string name = index.data(VariableRole).toString().toStdString();
    std::string typed = text.toStdString();
    bool alias = kind(index) == AliasKind;
    App::Property* prop = alias ? nullptr : obj->getPropertyByName(name.c_str());
    if (!alias && !prop) {
        error = tr("The variable '%1' is gone.").arg(QString::fromStdString(name));
        return false;
    }
    if (typed.empty()) {
        error = tr("Enter a value or an expression.");
        return false;
    }

    // A text that is a plain quantity sets a number's value. For an alias, a String or a Bool, a
    // text that isn't meant as an expression (isExpressionText) is the value. Anything else is an
    // expression.
    enum class As
    {
        Value,
        Text,
        Expression
    };
    As as = As::Expression;
    bool isString = freecad_cast<App::PropertyString*>(prop) != nullptr;
    bool isBool = freecad_cast<App::PropertyBool*>(prop) != nullptr;
    if (alias || isNumeric(prop)) {
        try {
            Base::Quantity::parse(typed);
            as = As::Value;
        }
        catch (const Base::Exception&) {
        }
    }
    else if (isBool && boolValue(text) >= 0) {
        as = As::Value;
    }
    if (as == As::Expression && (alias || isString || isBool) && !isExpressionText(obj, typed)) {
        if (isBool) {
            error = tr("%1 is True or False, or an expression: start it with '=', or use #name.")
                        .arg(QString::fromStdString(name));
            return false;
        }
        as = As::Text;
    }

    std::vector<std::string> commands;
    std::string target = pyObject(obj);
    if (as != As::Expression) {
        if (alias) {
            commands.push_back(
                target + ".set('" + index.data(AddressRole).toString().toStdString() + "', "
                + pyString(typed) + ")"
            );
        }
        else {
            if (obj->getExpression(App::ObjectIdentifier(*prop)).expression) {
                commands.push_back(target + ".setExpression(" + pyString(name) + ", None)");
            }
            if (isString || freecad_cast<App::PropertyQuantity*>(prop)) {
                commands.push_back(target + "." + name + " = " + pyString(typed));
            }
            else if (isBool) {
                commands.push_back(
                    target + "." + name + " = " + (boolValue(text) ? "True" : "False")
                );
            }
            else {
                // A Float or an Integer: the quantity must have no unit.
                Base::Quantity quantity = Base::Quantity::parse(typed);
                if (!quantity.isDimensionless()) {
                    error = tr("%1 has no unit.").arg(QString::fromStdString(name));
                    return false;
                }
                std::ostringstream value;
                value.precision(17);
                if (freecad_cast<App::PropertyInteger*>(prop)) {
                    double number = quantity.getValue();
                    if (number != std::floor(number)) {
                        error = tr("%1 takes a whole number.").arg(QString::fromStdString(name));
                        return false;
                    }
                    // PropertyInteger holds a long; a cast from outside its range is undefined.
                    if (number < static_cast<double>(std::numeric_limits<long>::min())
                        || number >= static_cast<double>(std::numeric_limits<long>::max()) + 1.0) {
                        error = tr("%1 is out of range.").arg(QString::fromStdString(name));
                        return false;
                    }
                    value << static_cast<long>(number);
                }
                else {
                    value << quantity.getValue();
                }
                commands.push_back(target + "." + name + " = " + value.str());
            }
        }
    }
    else {
        // Parsed with the variable's owner: the command gets the stored text, never `#name`.
        // A leading '=' only says "expression", as in a sheet cell.
        std::shared_ptr<App::Expression> expr;
        try {
            expr = App::Expression::parse(obj, typed.starts_with('=') ? typed.substr(1) : typed);
        }
        catch (const Base::Exception& e) {
            error = QString::fromUtf8(e.what());
            // A text with '#' and a letter (`#FF0000`, `#todo`) came here through
            // hasVariableRef: say how to keep it as text (ops#192).
            if ((alias || isString) && !typed.starts_with('=')) {
                QString example = text.contains(u'>') || text.contains(u'\\')
                    ? QStringLiteral("=<<...>>")
                    : QStringLiteral("=<<%1>>").arg(text);
                error += QLatin1Char('\n') + tr("For text, write %1.").arg(example);
            }
            return false;
        }
        std::string stored = expr->toString();
        if (alias) {
            commands.push_back(
                target + ".set('" + index.data(AddressRole).toString().toStdString() + "', "
                + pyString("=" + stored) + ")"
            );
        }
        else {
            std::string invalid = obj->ExpressionEngine.validateExpression(
                App::ObjectIdentifier(*prop),
                expr
            );
            if (!invalid.empty()) {
                error = QString::fromStdString(invalid);
                return false;
            }
            commands.push_back(
                target + ".setExpression(" + pyString(name) + ", " + pyString(stored) + ")"
            );
        }
    }
    return runEdit(obj->getDocument(), "Set " + name, commands, error);
}

// ----------------------------------------------------------------------------------------------

VariablesDelegate::VariablesDelegate(QObject* parent)
    : QStyledItemDelegate(parent)
{}

QWidget* VariablesDelegate::createEditor(
    QWidget* parent,
    const QStyleOptionViewItem& option,
    const QModelIndex& index
) const
{
    committedByKey = false;
    if (index.column() != VariablesModel::ExpressionColumn) {
        return QStyledItemDelegate::createEditor(parent, option, index);
    }
    auto editor = new ExpressionLineEdit(parent);
    editor->setObjectName(QStringLiteral("expressionEditor"));
    // Its validator refuses a leading '=' and strips it, but '=' makes a text a reference here.
    editor->setValidator(nullptr);
    if (App::DocumentObject* obj = VariablesModel::holder(index)) {
        editor->setDocumentObject(obj);
    }
    return editor;
}

bool VariablesDelegate::eventFilter(QObject* object, QEvent* event)
{
    // Read by the view when a commit fails: only Return or Enter reopens the editor.
    if (event->type() == QEvent::KeyPress) {
        int key = static_cast<QKeyEvent*>(event)->key();
        committedByKey = key == Qt::Key_Return || key == Qt::Key_Enter;
    }
    else if (event->type() == QEvent::FocusOut) {
        committedByKey = false;
    }
    return QStyledItemDelegate::eventFilter(object, event);
}

void VariablesDelegate::setEditorData(QWidget* editor, const QModelIndex& index) const
{
    auto lineEdit = qobject_cast<QLineEdit*>(editor);
    if (!lineEdit) {
        QStyledItemDelegate::setEditorData(editor, index);
        return;
    }
    if (retryIndex.isValid() && retryIndex == index) {
        lineEdit->setText(retryText);
        retryIndex = QPersistentModelIndex();
        return;
    }
    QVariant text = index.data(VariablesModel::EditTextRole);
    lineEdit->setText(text.isValid() ? text.toString() : index.data(Qt::DisplayRole).toString());
}

void VariablesDelegate::setModelData(
    QWidget* editor,
    QAbstractItemModel* model,
    const QModelIndex& index
) const
{
    auto lineEdit = qobject_cast<QLineEdit*>(editor);
    if (!lineEdit) {
        QStyledItemDelegate::setModelData(editor, model, index);
        return;
    }
    if (model->setData(index, lineEdit->text(), Qt::EditRole)) {
        Q_EMIT committed();
    }
    else {
        Q_EMIT commitFailed(index, lineEdit->text());
    }
}

// ----------------------------------------------------------------------------------------------

VariablesView::VariablesView(Gui::Document* doc, QWidget* parent)
    : DockWindow(doc, parent)
{
    auto layout = new QVBoxLayout(this);
    layout->setSpacing(2);
    layout->setContentsMargins(0, 0, 0, 0);

    auto toolBar = new QToolBar(this);
    toolBar->setIconSize(QSize(16, 16));
    addAction = toolBar->addAction(
        BitmapFactory().iconFromTheme("list-add"),
        tr("Add"),
        this,
        &VariablesView::addVariable
    );
    addAction->setObjectName(QStringLiteral("addVariable"));
    addAction->setToolTip(tr("Add a variable to the selected row's VarSet, or to \"Variables\""));
    deleteAction = toolBar->addAction(
        BitmapFactory().iconFromTheme("list-remove"),
        tr("Delete"),
        this,
        &VariablesView::deleteVariable
    );
    deleteAction->setObjectName(QStringLiteral("deleteVariable"));
    deleteAction->setToolTip(tr("Delete the selected variable, or remove the alias"));
    usesAction = toolBar->addAction(tr("Show uses"), this, &VariablesView::showUses);
    usesAction->setObjectName(QStringLiteral("showUses"));
    usesAction->setToolTip(tr("List the expressions that use the selected variable"));
    layout->addWidget(toolBar);

    model = new VariablesModel(this);
    delegate = new VariablesDelegate(this);
    tree = new VariablesTree(this);
    tree->setObjectName(QStringLiteral("variablesTree"));
    tree->setModel(model);
    tree->setItemDelegate(delegate);
    tree->setUniformRowHeights(true);
    tree->setAlternatingRowColors(true);
    tree->setEditTriggers(
        QAbstractItemView::DoubleClicked | QAbstractItemView::EditKeyPressed
        | QAbstractItemView::AnyKeyPressed
    );
    tree->header()->setSectionResizeMode(QHeaderView::Interactive);
    tree->setContextMenuPolicy(Qt::ActionsContextMenu);
    tree->addAction(addAction);
    tree->addAction(deleteAction);
    tree->addAction(usesAction);
    layout->addWidget(tree);

    hint = new QLabel(tr("Add a variable, or type #name in any expression."), this);
    hint->setObjectName(QStringLiteral("hint"));
    hint->setWordWrap(true);
    hint->setAlignment(Qt::AlignCenter);
    layout->addWidget(hint);

    message = new QLabel(this);
    message->setObjectName(QStringLiteral("message"));
    message->setWordWrap(true);
    message->setTextInteractionFlags(Qt::TextSelectableByMouse);
    message->hide();
    layout->addWidget(message);

    timer = new QTimer(this);
    timer->setSingleShot(true);
    timer->setInterval(100);
    connect(timer, &QTimer::timeout, this, &VariablesView::rebuild);

    connect(delegate, &VariablesDelegate::commitFailed, this, &VariablesView::onCommitFailed);
    connect(delegate, &VariablesDelegate::committed, this, [this] {
        const QString& warning = model->lastWarning();
        showMessage(warning, false);
    });
    connect(tree, &QTreeView::doubleClicked, this, &VariablesView::onDoubleClicked);
    connect(tree->selectionModel(), &QItemSelectionModel::currentChanged, this, [this] {
        updateActions();
    });

    // As in PropertyView: any change that can add, remove or change a variable rebuilds, debounced.
    auto& app = App::GetApplication();
    connections.emplace_back(
        app.signalChangedObject.connect(
            std::bind(&VariablesView::onChangedObject, this, sp::_1, sp::_2)
        )
    );
    connections.emplace_back(
        app.signalNewObject.connect(std::bind(&VariablesView::onObject, this, sp::_1))
    );
    connections.emplace_back(
        app.signalDeletedObject.connect(std::bind(&VariablesView::onObject, this, sp::_1))
    );
    connections.emplace_back(
        app.signalAppendDynamicProperty.connect(std::bind(&VariablesView::onProperty, this, sp::_1))
    );
    connections.emplace_back(
        app.signalRemoveDynamicProperty.connect(std::bind(&VariablesView::onProperty, this, sp::_1))
    );
    connections.emplace_back(
        app.signalRenameDynamicProperty.connect(std::bind(&VariablesView::onProperty, this, sp::_1))
    );
    connections.emplace_back(app.signalUndoDocument.connect([this](const App::Document&) {
        scheduleRebuild();
    }));
    connections.emplace_back(app.signalRedoDocument.connect([this](const App::Document&) {
        scheduleRebuild();
    }));
    connections.emplace_back(app.signalRecomputed.connect([this](const App::Document&) {
        scheduleRebuild();
    }));
    connections.emplace_back(Application::Instance->signalActiveDocument.connect(
        std::bind(&VariablesView::onActiveDocument, this, sp::_1)
    ));
    connections.emplace_back(Application::Instance->signalDeleteDocument.connect(
        std::bind(&VariablesView::onDeleteDocument, this, sp::_1)
    ));

    if (Gui::Document* active = Application::Instance->activeDocument()) {
        documentName = active->getDocument()->getName();
    }
    rebuild();
}

VariablesView::~VariablesView() = default;

App::Document* VariablesView::currentDocument() const
{
    return documentName.empty() ? nullptr : App::GetApplication().getDocument(documentName.c_str());
}

bool VariablesView::isRelevant(const App::DocumentObject* obj) const
{
    App::Document* doc = currentDocument();
    if (!doc || obj->getDocument() != doc) {
        return false;
    }
    return obj->isDerivedFrom<App::VarSet>() || isSheet(obj);
}

void VariablesView::onChangedObject(const App::DocumentObject& obj, const App::Property&)
{
    // Hidden, any change only marks the panel dirty: isRelevant is too costly for every change.
    if (!isVisible() || isRelevant(&obj)) {
        scheduleRebuild();
    }
}

void VariablesView::onObject(const App::DocumentObject& obj)
{
    if (!isVisible() || isRelevant(&obj)) {
        scheduleRebuild();
    }
}

void VariablesView::onProperty(const App::Property& prop)
{
    if (!isVisible()) {
        scheduleRebuild();
        return;
    }
    auto obj = freecad_cast<App::DocumentObject*>(prop.getContainer());
    if (obj && isRelevant(obj)) {
        scheduleRebuild();
    }
}

void VariablesView::onActiveDocument(const Gui::Document& doc)
{
    std::string name = doc.getDocument()->getName();
    if (name != documentName) {
        documentName = name;
        showMessage(QString(), false);
        scheduleRebuild();
    }
}

void VariablesView::onDeleteDocument(const Gui::Document& doc)
{
    std::string name = doc.getDocument()->getName();
    std::erase_if(collapsed, [&name](const std::string& key) {
        return key.starts_with(name + "/");
    });
    if (name == documentName) {
        documentName.clear();
        // The rows name objects of the closing document: drop them now, not on the timer.
        model->rebuild(nullptr);
        hint->setVisible(true);
        updateActions();
    }
}

void VariablesView::scheduleRebuild()
{
    if (!isVisible()) {
        dirty = true;
        return;
    }
    timer->start();
}

void VariablesView::showEvent(QShowEvent* ev)
{
    DockWindow::showEvent(ev);
    if (dirty) {
        rebuild();
    }
}

void VariablesView::rebuild()
{
    if (!isVisible()) {
        dirty = true;  // Rebuilt when shown.
        return;
    }
    if (static_cast<VariablesTree*>(tree)->isEditing()) {
        // Rebuilding would close the editor: wait for it.
        scheduleRebuild();
        return;
    }
    dirty = false;

    // Keep the collapsed headers and the current row across the rebuild.
    QString currentHolder;
    QString currentVariable;
    int currentColumn = 0;
    QModelIndex current = tree->currentIndex();
    if (current.isValid()) {
        currentHolder
            = current.sibling(current.row(), 0).data(VariablesModel::HolderRole).toString();
        currentVariable = current.data(VariablesModel::VariableRole).toString();
        currentColumn = current.column();
    }
    auto headerKey = [](const QModelIndex& header) {
        return header.data(VariablesModel::DocumentRole).toString().toStdString() + "/"
            + header.data(VariablesModel::HolderRole).toString().toStdString();
    };
    for (int row = 0; row < model->rowCount(); ++row) {
        QModelIndex header = model->index(row, 0);
        if (tree->isExpanded(header)) {
            collapsed.erase(headerKey(header));
        }
        else {
            collapsed.insert(headerKey(header));
        }
    }

    model->rebuild(currentDocument());

    for (int row = 0; row < model->rowCount(); ++row) {
        QModelIndex header = model->index(row, 0);
        tree->setFirstColumnSpanned(row, QModelIndex(), true);
        QString holder = header.data(VariablesModel::HolderRole).toString();
        tree->setExpanded(header, !collapsed.contains(headerKey(header)));
        if (holder != currentHolder) {
            continue;
        }
        if (currentVariable.isEmpty()) {
            tree->setCurrentIndex(header);
            continue;
        }
        for (int child = 0; child < model->rowCount(header); ++child) {
            QModelIndex index = model->index(child, currentColumn, header);
            if (index.data(VariablesModel::VariableRole).toString() == currentVariable) {
                tree->setCurrentIndex(index);
            }
        }
    }
    hint->setVisible(model->rowCount() == 0);
    updateActions();
}

void VariablesView::updateActions()
{
    QModelIndex current = tree->currentIndex();
    bool variable = current.isValid()
        && VariablesModel::kind(current) != VariablesModel::HeaderKind;
    addAction->setEnabled(currentDocument() != nullptr);
    deleteAction->setEnabled(variable);
    usesAction->setEnabled(variable);
}

void VariablesView::showMessage(const QString& text, bool isError)
{
    message->setText(text);
    message->setStyleSheet(isError ? QStringLiteral("color: red;") : QString());
    message->setVisible(!text.isEmpty());
}

void VariablesView::onCommitFailed(const QModelIndex& index, const QString& text)
{
    showMessage(model->lastError(), true);
    if (!delegate->committedByKey) {
        // Committed by leaving the editor: reopening it would take the focus back.
        return;
    }
    // Keep editing what was typed: nothing was changed.
    QPersistentModelIndex retry(index);
    delegate->retryIndex = retry;
    delegate->retryText = text;
    QTimer::singleShot(0, this, [this, retry] {
        if (retry.isValid()) {
            tree->setCurrentIndex(retry);
            tree->edit(retry);
        }
    });
}

void VariablesView::onDoubleClicked(const QModelIndex& index)
{
    if (index.column() != VariablesModel::SourceColumn
        && VariablesModel::kind(index) != VariablesModel::HeaderKind) {
        return;
    }
    App::DocumentObject* obj = VariablesModel::holder(index);
    if (!obj) {
        return;
    }
    Gui::Selection().clearSelection();
    Gui::Selection().addSelection(obj->getDocument()->getName(), obj->getNameInDocument());
}

void VariablesView::addVariable()
{
    App::Document* doc = currentDocument();
    if (!doc) {
        return;
    }
    // The selected row's VarSet, else the document's "Variables" VarSet, created on first use.
    App::DocumentObject* target = nullptr;
    QModelIndex current = tree->currentIndex();
    if (App::DocumentObject* obj = VariablesModel::holder(current)) {
        if (obj->isDerivedFrom<App::VarSet>()) {
            target = obj;
        }
    }
    if (!target) {
        App::DocumentObject* obj = doc->getObject("Variables");
        if (obj && obj->isDerivedFrom<App::VarSet>()) {
            target = obj;
        }
    }
    if (!target) {
        for (auto obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
            if (std::string(obj->Label.getValue()) == "Variables") {
                target = obj;
                break;
            }
        }
    }

    bool created = false;
    int createdID = 0;  // the "Add variable" undo step, when the panel made one
    if (!target) {
        // Its own committed step: the dialog aborts and reopens its "Add property" transaction
        // as the name or the type is typed, which must not take the VarSet with it.
        bool own = doc->getBookedTransactionID() == 0;
        QString error;
        std::string command = std::string("App.getDocument('") + doc->getName()
            + "').addObject('App::VarSet', 'Variables')";
        if (!runEdit(doc, "Add variable", {command}, error)) {
            showMessage(error, true);
            return;
        }
        if (own) {
            createdID = doc->getTransactionID(true, 0);
        }
        // The new object is the document's last; its name may be "Variables001" if another
        // object is named "Variables".
        const auto& objects = doc->getObjects();
        target = objects.empty() ? nullptr : objects.back();
        if (!target || !target->isDerivedFrom<App::VarSet>()) {
            return;
        }
        created = true;
    }

    auto dialog = new Dialog::DlgAddProperty(getMainWindow(), target);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowModality(Qt::ApplicationModal);
    if (created) {
        std::string docName = doc->getName();
        std::string varSetName = target->getNameInDocument();
        connect(dialog, &QDialog::finished, this, [docName, varSetName, createdID](int) {
            // Closed before any variable was added: take the empty VarSet back out, by undoing
            // its step while it is the last one, else in a step of its own.
            App::Document* doc = App::GetApplication().getDocument(docName.c_str());
            App::DocumentObject* varSet = doc ? doc->getObject(varSetName.c_str()) : nullptr;
            if (!varSet || !varSet->getDynamicPropertyNames().empty()) {
                return;
            }
            Gui::Document* guiDoc = Application::Instance->getDocument(doc);
            if (guiDoc && createdID != 0 && doc->getBookedTransactionID() == 0
                && doc->getTransactionID(true, 0) == createdID) {
                guiDoc->undo(1);
                return;
            }
            QString error;
            runEdit(
                doc,
                "Delete " + varSetName,
                {std::string("App.getDocument('") + docName + "').removeObject('" + varSetName
                 + "')"},
                error
            );
        });
    }
    dialog->show();
    dialog->raise();
    dialog->activateWindow();
}

QString VariablesView::usesText(const QModelIndex& index, int* count) const
{
    App::Property* prop = VariablesModel::property(index);
    App::DocumentObject* obj = VariablesModel::holder(index);
    QStringList lines;
    if (prop && obj) {
        for (const auto& use : App::VariableLookup::uses(prop)) {
            lines << QString::fromStdString(use.toString(obj->getDocument()));
        }
    }
    lines.removeDuplicates();
    lines.sort();
    if (count) {
        *count = static_cast<int>(lines.size());
    }
    return lines.join(QLatin1Char('\n'));
}

void VariablesView::deleteVariable()
{
    QModelIndex current = tree->currentIndex();
    App::DocumentObject* obj = VariablesModel::holder(current);
    if (!obj || VariablesModel::kind(current) == VariablesModel::HeaderKind) {
        return;
    }
    // Everything is read from the row before the message box: the panel may rebuild while it is
    // open, which frees the row.
    std::string docName = obj->getDocument()->getName();
    std::string holderName = obj->getNameInDocument();
    std::string name = current.data(VariablesModel::VariableRole).toString().toStdString();
    QString qName = QString::fromStdString(name);
    std::vector<std::string> commands;
    int count = 0;
    QString uses;
    if (VariablesModel::kind(current) == VariablesModel::AliasKind) {
        // Removes the alias, not the cell: its uses are rewritten to the cell address.
        commands.push_back(
            pyObject(obj) + ".setAlias('"
            + current.data(VariablesModel::AddressRole).toString().toStdString() + "', None)"
        );
    }
    else {
        uses = usesText(current, &count);
        commands.push_back(pyObject(obj) + ".removeProperty(" + pyString(name) + ")");
        // Its users, the VarSet itself included, fail at the next recompute (D4): touch them, as
        // nothing else would.
        std::set<const App::DocumentObject*> users;
        if (App::Property* prop = VariablesModel::property(current)) {
            for (const auto& use : App::VariableLookup::uses(prop)) {
                if (use.user && use.user->isAttachedToDocument()
                    && users.insert(use.user).second) {
                    commands.push_back(pyObject(use.user) + ".touch()");
                }
            }
        }
    }
    if (count > 0) {
        QMessageBox box(
            QMessageBox::Warning,
            tr("Delete variable"),
            tr("%n expression(s) use #%1. They will fail at the next recompute.\n\n%2\n\n"
               "Delete #%1?",
               nullptr,
               count)
                .arg(qName, uses),
            QMessageBox::Ok | QMessageBox::Cancel,
            this
        );
        box.setObjectName(QStringLiteral("deleteVariableUses"));
        box.setDefaultButton(QMessageBox::Cancel);
        if (box.exec() != QMessageBox::Ok) {
            return;
        }
    }
    // Looked up again: the document may have changed while the box was open.
    App::Document* doc = App::GetApplication().getDocument(docName.c_str());
    if (!doc || !doc->getObject(holderName.c_str())) {
        return;
    }
    QString error;
    if (!runEdit(doc, "Delete " + name, commands, error)) {
        showMessage(error, true);
        return;
    }
    showMessage(QString(), false);
}

void VariablesView::showUses()
{
    QModelIndex current = tree->currentIndex();
    if (VariablesModel::kind(current) == VariablesModel::HeaderKind) {
        return;
    }
    QString qName = current.data(VariablesModel::VariableRole).toString();
    int count = 0;
    QString uses = usesText(current, &count);
    QMessageBox box(
        QMessageBox::Information,
        tr("Uses of #%1").arg(qName),
        count > 0 ? tr("%n expression(s) use #%1:\n\n%2", nullptr, count).arg(qName, uses)
                  : tr("No expression uses #%1.").arg(qName),
        QMessageBox::Ok,
        this
    );
    box.setObjectName(QStringLiteral("variableUses"));
    box.exec();
}

#include "moc_VariablesView.cpp"
