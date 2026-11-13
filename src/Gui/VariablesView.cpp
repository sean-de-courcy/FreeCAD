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
#include <cmath>
#include <cstring>
#include <limits>
#include <map>
#include <set>
#include <sstream>
#include <utility>
#include <vector>

#include <QAction>
#include <QApplication>
#include <QColor>
#include <QComboBox>
#include <QCoreApplication>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFileInfo>
#include <QFormLayout>
#include <QGuiApplication>
#include <QHeaderView>
#include <QInputDialog>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPointer>
#include <QPushButton>
#include <QStyle>
#include <QTimer>
#include <QToolBar>
#include <QTreeView>
#include <QVBoxLayout>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/DocumentTabs.h>
#include <App/Expression.h>
#include <App/ExpressionParser.h>
#include <App/GeoFeatureGroupExtension.h>
#include <App/GroupExtension.h>
#include <App/PropertyPythonObject.h>
#include <App/PropertyStandard.h>
#include <App/PropertyUnits.h>
#include <App/Range.h>
#include <App/VarSet.h>
#include <App/VarSetCopy.h>
#include <App/VariableLookup.h>
#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Base/Quantity.h>
#include <Base/Tools.h>
#include <CXX/Objects.hxx>

#include "Application.h"
#include "BitmapFactory.h"
#include "Command.h"
#include "DockWindowManager.h"
#include "ForkKeymap.h"
#include "Document.h"
#include "ExpressionCompleter.h"
#include "MainWindow.h"
#include "Selection/Selection.h"
#include "Dialogs/DlgAddProperty.h"
#include "propertyeditor/PropertyEditor.h"
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

/// The variable's type as the Type column names it (ops#317, design section 1.2): Length (a
/// Length or a Distance), Angle, Number, Integer, Yes/No, Text, another quantity's dimension
/// (Area), else the property type.
QString variableType(const App::Property* prop)
{
    if (!prop) {
        return {};
    }
    if (auto quantity = freecad_cast<const App::PropertyQuantity*>(prop)) {
        const Base::Unit& unit = quantity->getUnit();
        if (unit == Base::Unit::Length) {
            return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "Length");
        }
        if (unit == Base::Unit::Angle) {
            return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "Angle");
        }
        std::string dimension = unit.getTypeString();
        return dimension.empty() ? typeName(prop) : QString::fromStdString(dimension);
    }
    if (freecad_cast<const App::PropertyFloat*>(prop)) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "Number");
    }
    if (freecad_cast<const App::PropertyInteger*>(prop)) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "Integer");
    }
    if (freecad_cast<const App::PropertyBool*>(prop)) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "Yes/No");
    }
    if (freecad_cast<const App::PropertyString*>(prop)) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "Text");
    }
    return typeName(prop);
}

/// A description as one table line: its first line, and an ellipsis when more follow.
QString descriptionLine(const QString& text)
{
    qsizetype end = text.indexOf(u'\n');
    return end < 0 ? text : text.left(end).trimmed() + QStringLiteral(" …");
}

bool isNumeric(const App::Property* prop)
{
    return freecad_cast<const App::PropertyFloat*>(prop)
        || freecad_cast<const App::PropertyInteger*>(prop);
}

// FreeCAD-CH (ops#640, measured variables 2): a measured variable's row (design note section 6).
// Not in the header's Role enum, so that only this file rebuilds.
constexpr int MeasuredRole = Qt::UserRole + 50;
// The Add dialog's Type data of a measured kind: this prefix, then the kind ("Length").
constexpr const char* measuredTypePrefix = "Measured:";

/// The measurement @a prop of @a holder reads: its expression is `<object>.Value` and that object
/// has a MeasuredVariable proxy (freecad.variables.measured); else nullptr.
App::DocumentObject* measurementOf(const App::DocumentObject* holder, const App::Property* prop)
{
    if (!holder || !prop) {
        return nullptr;
    }
    auto info = holder->getExpression(App::ObjectIdentifier(*prop));
    auto variable = dynamic_cast<const App::VariableExpression*>(info.expression.get());
    if (!variable) {
        return nullptr;
    }
    App::ObjectIdentifier path = variable->getPath();
    App::DocumentObject* obj = path.getDocumentObject();
    if (!obj || path.getPropertyName() != "Value" || !obj->getPropertyByName("ReferenceNames")) {
        return nullptr;
    }
    auto proxy = freecad_cast<App::PropertyPythonObject*>(obj->getPropertyByName("Proxy"));
    if (!proxy) {
        return nullptr;
    }
    Base::PyGILStateLocker lock;
    try {
        Py::Object value = proxy->getValue();
        if (value.isNone()) {
            return nullptr;
        }
        Py::Object name = value.type().getAttr("__name__");
        return Py::String(name).as_std_string("utf-8") == "MeasuredVariable" ? obj : nullptr;
    }
    catch (Py::Exception&) {
        PyErr_Clear();
    }
    return nullptr;
}

/// Whether @a obj is a measured variable's own holder: a VarSet whose every variable is measured
/// (freecad.variables.measured.is_measured_holder). Its rows show under its studio's own set, and
/// it is never an Add target.
bool isMeasuredHolder(const App::DocumentObject* obj)
{
    if (!obj || obj->getTypeId() != App::VarSet::getClassTypeId()) {
        return false;
    }
    std::vector<std::string> names = obj->getDynamicPropertyNames();
    if (names.empty()) {
        return false;
    }
    for (const auto& name : names) {
        if (!measurementOf(obj, obj->getPropertyByName(name.c_str()))) {
            return false;
        }
    }
    return true;
}

/// The studio's own set a measured variable's holder belongs with: the first VarSet of its
/// App::Part that is no holder, or for the implicit studio (the top level) the one named, else
/// labelled, "Variables" (freecad.variables.measured.studio_variables).
App::DocumentObject* studioSetOf(const App::DocumentObject* holder)
{
    auto isOwnSet = [](const App::DocumentObject* obj) {
        return obj && obj->getTypeId() == App::VarSet::getClassTypeId()
            && !App::DocumentTabs::isVariableStudio(obj) && !isMeasuredHolder(obj);
    };
    if (App::DocumentObject* group = App::GeoFeatureGroupExtension::getGroupOfObject(holder)) {
        if (auto ext = group->getExtensionByType<App::GroupExtension>(true)) {
            for (auto obj : ext->Group.getValues()) {
                if (isOwnSet(obj)) {
                    return obj;
                }
            }
        }
        return nullptr;
    }
    App::Document* doc = holder->getDocument();
    App::DocumentObject* named = doc->getObject("Variables");
    if (isOwnSet(named) && !App::GeoFeatureGroupExtension::getGroupOfObject(named)) {
        return named;
    }
    for (auto obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
        if (isOwnSet(obj) && !App::GeoFeatureGroupExtension::getGroupOfObject(obj)
            && std::string(obj->Label.getValue()) == "Variables") {
            return obj;
        }
    }
    return nullptr;
}

/// A measured variable's holder shows no header of its own: its row moves under its studio's
/// set, where Onshape lists every variable of the studio. A holder whose set isn't listed keeps
/// its header.
void foldMeasuredHolders(QStandardItemModel* model, const App::Document* doc)
{
    using Model = Gui::DockWnd::VariablesModel;
    auto headerOf = [model](const App::DocumentObject* holder) -> QStandardItem* {
        const QString name = QString::fromLatin1(holder->getNameInDocument());
        for (int row = 0; row < model->rowCount(); ++row) {
            QStandardItem* header = model->item(row, 0);
            if (header && header->data(Model::KindRole).toInt() == Model::HeaderKind
                && header->data(Model::HolderRole).toString() == name) {
                return header;
            }
        }
        return nullptr;
    };
    for (int row = model->rowCount() - 1; row >= 0; --row) {
        QStandardItem* header = model->item(row, 0);
        if (!header || header->data(Model::KindRole).toInt() != Model::HeaderKind) {
            continue;
        }
        App::DocumentObject* holder
            = doc->getObject(header->data(Model::HolderRole).toString().toLatin1().constData());
        if (!isMeasuredHolder(holder)) {
            continue;
        }
        App::DocumentObject* set = studioSetOf(holder);
        if (!set) {
            continue;
        }
        QStandardItem* target = headerOf(set);
        if (!target) {
            // The studio's set has no variables of its own, so no header: this one becomes it
            const QString label = QString::fromUtf8(set->Label.getValue());
            header->setText(label);
            header->setData(QString::fromLatin1(set->getNameInDocument()), Model::HolderRole);
            header->setToolTip(QString::fromLatin1(set->getNameInDocument()));
            continue;
        }
        if (target == header) {
            continue;
        }
        while (header->rowCount() > 0) {
            target->appendRow(header->takeRow(0));
        }
        model->removeRow(header->row());
    }
}

/// What a measurement reads, for the Expression column: "Length of Pad.Edge3, Pad.Edge7",
/// "Distance (minimum, use axis) of Pad.Face1, Sketch.Edge2", "Distance along X (maximum) of ...",
/// "Radius of Pad.Edge4". The references as last measured.
QString measurementText(const App::DocumentObject* measurement)
{
    auto kind = freecad_cast<const App::PropertyEnumeration*>(
        measurement->getPropertyByName("Kind")
    );
    auto type = freecad_cast<const App::PropertyEnumeration*>(
        measurement->getPropertyByName("DistanceType")
    );
    auto names = freecad_cast<const App::PropertyStringList*>(
        measurement->getPropertyByName("ReferenceNames")
    );
    QString what = kind && kind->getValueAsString()
        ? QString::fromUtf8(kind->getValueAsString())
        : QStringLiteral("?");
    QStringList refs;
    if (names) {
        for (const auto& name : names->getValues()) {
            refs << QString::fromStdString(name);
        }
    }
    auto flag = [measurement](const char* name) {
        auto prop = freecad_cast<const App::PropertyBool*>(measurement->getPropertyByName(name));
        return prop && prop->getValue();
    };
    if (what == QLatin1String("Distance")) {
        auto record = freecad_cast<const App::PropertyEnumeration*>(
            measurement->getPropertyByName("ValueToRecord")
        );
        bool maximum = type && type->getValueAsString()
            && std::string(type->getValueAsString()) == "Maximum";
        QString mode = maximum
            ? QCoreApplication::translate("Gui::DockWnd::VariablesModel", "maximum")
            : flag("UseAxis")
            ? QCoreApplication::translate("Gui::DockWnd::VariablesModel", "minimum, use axis")
            : QCoreApplication::translate("Gui::DockWnd::VariablesModel", "minimum");
        std::string axis = record && record->getValueAsString() ? record->getValueAsString() : "";
        if (axis == "X" || axis == "Y" || axis == "Z") {
            // "Distance along X (minimum) of Pad.Edge1, Pad.Edge2"
            return QCoreApplication::translate("Gui::DockWnd::VariablesModel",
                                               "Distance along %1 (%2) of %3")
                .arg(QString::fromStdString(axis), mode, refs.join(QStringLiteral(", ")));
        }
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "Distance (%1) of %2")
            .arg(mode, refs.join(QStringLiteral(", ")));
    }
    if (what == QLatin1String("Diameter") && flag("Radius")) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "Radius of %1")
            .arg(refs.join(QStringLiteral(", ")));
    }
    return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "%1 of %2")
        .arg(QCoreApplication::translate("Gui::DockWnd::VariablesModel", what.toUtf8().constData()),
             refs.join(QStringLiteral(", ")));
}

/// The measured kind's word for the Source column: "measured length".
QString measuredWords(const App::DocumentObject* measurement)
{
    auto kind = freecad_cast<const App::PropertyEnumeration*>(
        measurement->getPropertyByName("Kind")
    );
    QString what = kind && kind->getValueAsString()
        ? QString::fromUtf8(kind->getValueAsString()).toLower()
        : QString();
    return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "measured %1").arg(what);
}

/// Runs freecad.variables.measuredgui.<function>(args...) and returns its text: "" when it
/// opened, else why not (a Python error's message included).
QString runMeasuredGui(const char* function, const Py::Tuple& args)
{
    Base::PyGILStateLocker lock;
    try {
        Py::Module module(PyImport_ImportModule("freecad.variables.measuredgui"), true);
        Py::Callable call(module.getAttr(function));
        Py::Object result = call.apply(args);
        return result.isString() ? QString::fromStdString(Py::String(result).as_std_string("utf-8"))
                                 : QString();
    }
    catch (Py::Exception&) {
        Base::PyException e;
        return QString::fromStdString(e.what());
    }
}

/// Recomputes @a doc after an edit, inside the edit's transaction (one undo step), as the property
/// editor does: FreeCAD-CH ops#599, Onshape regenerates as soon as a variable changes. Not while
/// the document is recomputing or loading; a failure is reported, and the edit stands.
/// Not while any document has an object in edit either, whichever view is active: the document
/// stays touched until the edit closes. A sketch's Cancel restores it from its backup and
/// untouches it, so what a recompute had built from the sketch being edited would stay, silently
/// (reviews pr599-r1 R1-1 and r1b: the sketch's own document or another, through a link or a
/// cross-document expression). An edit document whose edit was refused has none (r1c R1c-a).
void recomputeAfterEdit(App::Document* doc)
{
    if (!doc || !doc->isTouched() || doc->testStatus(App::Document::Recomputing)
        || doc->testStatus(App::Document::Restoring)) {
        return;
    }
    if (std::ranges::any_of(Application::Instance->editDocuments(), [](Gui::Document* editing) {
            return editing->getEditViewProvider() != nullptr;
        })) {
        return;
    }
    try {
        doc->recompute();
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
    catch (const std::exception& e) {
        Base::Console().error(
            "Unhandled std::exception caught in the Variables panel's recompute.\n"
            "The error message is: %s\n",
            e.what()
        );
    }
    catch (...) {
        Base::Console().error(
            "Unhandled unknown exception caught in the Variables panel's recompute.\n"
        );
    }
}

/// Runs @a commands as one transaction named @a name on @a doc, and recomputes it; false and
/// @a error on failure, with the transaction aborted. A transaction already booked (a task
/// dialog's) takes the edit.
bool runEdit(
    App::Document* doc,
    const std::string& name,
    const std::vector<std::string>& commands,
    QString& error
)
{
    // A booked transaction (a task dialog's) takes the edit; a property editor's "Edit" booking
    // doesn't (FreeCAD-CH ops#231: the editor's Esc would abort it).
    int tid = Gui::PropertyEditor::openPropertyTransaction(doc, name.c_str());
    try {
        for (const auto& command : commands) {
            Gui::Command::runCommand(Gui::Command::Doc, command.c_str());
        }
    }
    catch (const Base::Exception& e) {
        Gui::PropertyEditor::closePropertyTransaction(tid, false);
        error = QString::fromUtf8(e.what());
        return false;
    }
    catch (...) {
        Gui::PropertyEditor::closePropertyTransaction(tid, false);
        throw;
    }
    recomputeAfterEdit(doc);
    Gui::PropertyEditor::closePropertyTransaction(tid);
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

/// Whether @a name may name a variable: an identifier that isn't a cell address. A sheet alias
/// can't be a unit or a constant either; a VarSet variable can (FreeCAD-CH, ops#640, rank 54:
/// `#t` reads as the variable, App's checkVariableName).
bool isValidName(const std::string& name, bool sheet)
{
    if (App::ExpressionParser::isTokenAUnit(name) || App::ExpressionParser::isTokenAConstant(name)) {
        return !sheet && App::VariableLookup::checkVariableName(nullptr, name).empty();
    }
    return App::ExpressionParser::isTokenAnIndentifier(name)
        && !App::stringToAddress(name.c_str(), true).isValid();
}

/// Whether variables may be added to @a obj: a VarSet, but not a copy still attached to its
/// source (ops#317: its variables are the source's, read-only).
bool isEditableSet(const App::DocumentObject* obj)
{
    auto copy = freecad_cast<const App::VarSetCopy*>(obj);
    return obj && obj->isDerivedFrom<App::VarSet>() && !(copy && copy->isAttached());
}

/// FreeCAD-CH (ops#317 PR G2, ops#640 round 5): a copy's source state, as
/// freecad.variables.copies.panel_state() gives it (notes/variables-studio.md 3.2): the state, its
/// message, a tooltip, and the flag of each orphan (a variable removed at the source but still used).
struct CopyState
{
    QString state;
    QString message;
    QString tip;
    std::map<std::string, QString> orphans;
};

/// Roles on a copy's header item, read by the tests: its state and its message.
constexpr int CopyStateRole = Qt::UserRole + 20;
constexpr int CopyMessageRole = Qt::UserRole + 21;

CopyState copyState(const App::DocumentObject* copy)
{
    CopyState result;
    Base::PyGILStateLocker lock;
    try {
        PyObject* raw = PyImport_ImportModule("freecad.variables.copies");
        if (!raw) {
            throw Py::Exception();
        }
        Py::Module module(raw, true);
        Py::Callable function(module.getAttr("panel_state"));
        Py::Tuple args(1);
        args.setItem(0, Py::Object(const_cast<App::DocumentObject*>(copy)->getPyObject(), true));
        Py::Tuple values(function.apply(args));
        result.state = QString::fromStdString(Py::String(values[0]).as_std_string("utf-8"));
        result.message = QString::fromStdString(Py::String(values[1]).as_std_string("utf-8"));
        result.tip = QString::fromStdString(Py::String(values[2]).as_std_string("utf-8"));
        Py::Dict orphans(values[3]);
        for (const auto& key : orphans.keys()) {
            result.orphans[Py::String(key).as_std_string("utf-8")] = QString::fromStdString(
                Py::String(orphans[key]).as_std_string("utf-8")
            );
        }
    }
    catch (Py::Exception&) {
        Base::PyException e;  // the panel shows the copy without its state; the error is reported
        e.reportException();
    }
    return result;
}

/// The words a copy's header adds to its label for a state other than "up to date".
QString stateWords(const QString& state)
{
    if (state == QLatin1String("out of date")) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "out of date");
    }
    if (state == QLatin1String("not found")) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "source not found");
    }
    if (state == QLatin1String("unreadable")) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "source unreadable");
    }
    if (state == QLatin1String("other stamp")) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "can't compare");
    }
    if (state == QLatin1String("two sources")) {
        return QCoreApplication::translate("Gui::DockWnd::VariablesModel", "two sources");
    }
    return {};
}

/// Whether @a doc has copies (App::VarSetCopy): only then do focus and saves rebuild the panel.
bool hasCopies(const App::Document* doc)
{
    return doc && !doc->getObjectsOfType(App::VarSetCopy::getClassTypeId()).empty();
}

/// FreeCAD-CH (ops#640, rank 55): the application property through which a field's "New
/// variable..." hands the Add dialog the typed name and the field's value (a QStringList; set
/// around a run of Std_AddVariable by QuantitySpinBox.cpp and ExpressionCompleter.cpp).
constexpr const char* newVariableProperty = "FreeCADCH_NewVariable";

/// FreeCAD-CH (ops#640, hands-on D-1): a variable the Add dialog made inside a transaction that
/// another dialog had booked (a field's "New variable..." in a feature dialog). Onshape keeps such
/// a variable when the feature is cancelled: the abort takes it back with the feature, so it is
/// made again from this record, as its own undo step. A commit of the document drops the record.
struct PendingVariable
{
    std::string docName;
    std::string holderName;  // empty: the "Variables" set was made with it
    QString name;
    std::string type;
    QString text;
    QString description;
    std::string clashChoice;  // askNameClash's answer
};

std::vector<PendingVariable>& pendingVariables()
{
    static std::vector<PendingVariable> pending;
    return pending;
}

/// The records of @a docName, in the order they were made, taken out of the list.
std::vector<PendingVariable> takePendingVariables(const std::string& docName)
{
    std::vector<PendingVariable> taken;
    auto& pending = pendingVariables();
    for (auto it = pending.begin(); it != pending.end();) {
        if (it->docName == docName) {
            taken.push_back(std::move(*it));
            it = pending.erase(it);
        }
        else {
            ++it;
        }
    }
    return taken;
}

/// FreeCAD-CH (ops#640, decision 317): askNameClash's answer for the add that follows: "local",
/// the path of the imported variable, or empty (no clash). addFromDialog takes it once.
std::string& pendingClashChoice()
{
    static std::string choice;
    return choice;
}

/// FreeCAD-CH (ops#640, decision 317): before a local variable @a name is made in the set
/// @a holderName (empty: a new "Variables" set), when an imported copy defines that name too:
/// asks which variable `#name` means in new expressions, "Use <the copy's source>" (one copy),
/// "Use local", "Pick..." (between all of them) or Cancel. False when cancelled; @a choice gets
/// "local", the imported variable's path, or stays empty (no clash, or a name the add refuses
/// anyway). Existing expressions keep the variables they use (the message says so).
bool askNameClash(
    QWidget* parent,
    App::Document* doc,
    const std::string& holderName,
    const std::string& name,
    std::string& choice
)
{
    choice.clear();
    if (!doc || name.empty()) {
        return true;
    }
    App::DocumentObject* target = holderName.empty() ? nullptr : doc->getObject(holderName.c_str());
    if (!App::VariableLookup::checkVariableName(target, name).empty()) {
        return true;  // refused by the add, with its reason
    }
    std::vector<const App::VarSetCopy*> found;
    for (const auto& ref : App::VariableLookup::find(doc, name)) {
        auto copy = freecad_cast<const App::VarSetCopy*>(ref.holder);
        if (!copy || !copy->isAttached()) {
            // Another local set (or a sheet alias, or a detached copy: review R6-6) has the name:
            // `#name` is ambiguous among the document's own, and no choice of a copy's can settle
            // that.
            return true;
        }
        if (copy != target) {
            found.push_back(copy);
        }
    }
    if (found.empty()) {
        return true;
    }
    auto source = [](const App::VarSetCopy* copy) {
        QString file = QFileInfo(QString::fromUtf8(copy->SourcePath.getValue())).fileName();
        return file.isEmpty() ? QString::fromUtf8(copy->Label.getValue()) : file;
    };
    const QString qname = QString::fromStdString(name);
    QStringList where;
    for (auto copy : found) {
        where << VariablesView::tr("%1 (%2)")
                     .arg(QString::fromUtf8(copy->Label.getValue()), source(copy));
    }
    QMessageBox box(
        QMessageBox::Warning,
        VariablesView::tr("Name already imported"),
        VariablesView::tr(
            "#%1 is already imported: %2 defines it.\n\nWhich variable should #%1 mean in new "
            "expressions? Existing expressions keep the variable they use."
        )
            .arg(qname, where.join(QStringLiteral(", "))),
        QMessageBox::NoButton,
        parent
    );
    box.setObjectName(QStringLiteral("nameClash"));
    QPushButton* useImport = nullptr;
    if (found.size() == 1) {
        useImport = box.addButton(
            VariablesView::tr("Use %1").arg(source(found.front())),
            QMessageBox::AcceptRole
        );
        useImport->setObjectName(QStringLiteral("useImport"));
    }
    QPushButton* useLocal = box.addButton(VariablesView::tr("Use local"), QMessageBox::AcceptRole);
    useLocal->setObjectName(QStringLiteral("useLocal"));
    QPushButton* pick = box.addButton(VariablesView::tr("Pick..."), QMessageBox::ActionRole);
    pick->setObjectName(QStringLiteral("pick"));
    QPushButton* cancel = box.addButton(QMessageBox::Cancel);
    box.setEscapeButton(cancel);
    box.exec();
    QAbstractButton* clicked = box.clickedButton();
    auto pathOf = [&name](const App::VarSetCopy* copy) {
        return App::VariableRef {copy, name}.path();
    };
    if (useImport && clicked == useImport) {
        choice = pathOf(found.front());
        return true;
    }
    if (clicked == useLocal) {
        choice = "local";
        return true;
    }
    if (clicked != pick) {
        return false;
    }
    QStringList items;
    items << VariablesView::tr("%1 (the new local variable)").arg(qname);
    for (auto copy : found) {
        items << VariablesView::tr("%1.%2 (%3)")
                     .arg(QString::fromUtf8(copy->Label.getValue()), qname, source(copy));
    }
    bool ok = false;
    QString item = QInputDialog::getItem(
        parent,
        VariablesView::tr("Pick"),
        VariablesView::tr("#%1 means:").arg(qname),
        items,
        0,
        false,
        &ok
    );
    int index = ok ? static_cast<int>(items.indexOf(item)) : -1;
    if (index < 0) {
        return false;
    }
    choice = index == 0 ? std::string("local") : pathOf(found[index - 1]);
    return true;
}

/// FreeCAD-CH (ops#640, rank 15): Onshape's Variable tool, on Part Design's Features toolbar:
/// the Variables panel shown, and its Add dialog. A dialog's open transaction takes the add.
class StdCmdAddVariable: public Gui::Command
{
public:
    StdCmdAddVariable()
        : Command("Std_AddVariable")
    {
        sGroup = "Edit";
        sMenuText = QT_TR_NOOP("Variable");
        sToolTipText = QT_TR_NOOP("Adds a variable, to use as #name in any field");
        sWhatsThis = "Std_AddVariable";
        sStatusTip = sToolTipText;
        sPixmap = "VarSet";
    }
    StdCmdAddVariable(const StdCmdAddVariable&) = delete;
    StdCmdAddVariable(StdCmdAddVariable&&) = delete;
    StdCmdAddVariable& operator=(const StdCmdAddVariable&) = delete;
    StdCmdAddVariable& operator=(StdCmdAddVariable&&) = delete;
    ~StdCmdAddVariable() override = default;

    const char* className() const override
    {
        return "StdCmdAddVariable";
    }

protected:
    void activated(int iMsg) override
    {
        Q_UNUSED(iMsg);
        // By its registered name: getDockWindow() matches the dock's object name, which is the
        // panel's own ("Variables"), so it found none and the tool did nothing
        QWidget* view =
            DockWindowManager::instance()->findRegisteredDockWindow("Std_VariablesView");
        if (!view) {
            return;
        }
        // through the dock's view action, which also brings it out of an overlay panel
        DockWindowManager::instance()->activate(view);
        if (auto action = view->findChild<QAction*>(QStringLiteral("addVariable"))) {
            action->trigger();
        }
    }

    bool isActive() override
    {
        return hasActiveDocument();
    }
};

}  // namespace

/* TRANSLATOR Gui::DockWnd::VariablesView */

// ----------------------------------------------------------------------------------------------

VariablesModel::VariablesModel(QObject* parent)
    : QStandardItemModel(parent)
{
    setColumnCount(ColumnCount);
    setHorizontalHeaderLabels(
        {tr("Name"), tr("Type"), tr("Expression"), tr("Value"), tr("Description"), tr("Source")}
    );
}

void VariablesModel::rebuild(const App::Document* doc)
{
    removeRows(0, rowCount());
    if (!doc) {
        return;
    }
    // listVariables gives the variables per object, in the document's object order.
    std::vector<std::pair<const App::DocumentObject*, std::vector<std::string>>> groups;
    for (const auto& var : App::VariableLookup::listVariables(doc)) {
        if (!scope.empty() && var.holder->getNameInDocument() != scope) {
            // FreeCAD-CH (ops#640, tabs slice 4): a Variable Studio's table lists its own
            // variables, then the document's attached copies, read-only (the studios of other
            // files every studio can use, as Onshape's Variable Studio references)
            auto copy = freecad_cast<const App::VarSetCopy*>(var.holder);
            if (!copy || !copy->isAttached()) {
                continue;
            }
        }
        if (groups.empty() || groups.back().first != var.holder) {
            groups.emplace_back(var.holder, std::vector<std::string>());
        }
        groups.back().second.push_back(var.name);
    }
    if (scope.empty()) {
        for (const auto& [holder, names] : groups) {
            addHolderRows(holder, names);
        }
        foldMeasuredHolders(this, doc);
        return;
    }
    // FreeCAD-CH (ops#721, Onshape VR9): a Variable Studio's table is its referenced tables in
    // list order, the first at the top, then its own table last (the bottom-most definition
    // wins, ops#722); a name a later table defines again carries Onshape's info mark. The
    // document's copies in no studio's list follow, apart.
    using Group = std::pair<const App::DocumentObject*, std::vector<std::string>>;
    const Group* own = nullptr;
    std::vector<const Group*> others;
    const App::DocumentObject* studio = doc->getObject(scope.c_str());
    const auto references = App::DocumentTabs::variableReferences(studio);
    // Every reference gets its table, one with no variables too (so it can be moved or removed)
    std::vector<Group> referenced;
    for (const auto* reference : references) {
        referenced.emplace_back(reference, std::vector<std::string>());
    }
    for (const auto& group : groups) {
        auto it = std::find(references.begin(), references.end(), group.first);
        if (group.first->getNameInDocument() == scope) {
            own = &group;
        }
        else if (it != references.end()) {
            referenced[static_cast<std::size_t>(it - references.begin())].second = group.second;
        }
        else {
            others.push_back(&group);
        }
    }
    std::vector<const Group*> listed;
    for (const auto& group : referenced) {
        listed.push_back(&group);
    }
    for (std::size_t i = 0; i < listed.size(); ++i) {
        std::set<std::string> later;
        for (std::size_t j = i + 1; j < listed.size(); ++j) {
            later.insert(listed[j]->second.begin(), listed[j]->second.end());
        }
        if (own) {
            later.insert(own->second.begin(), own->second.end());
        }
        addHolderRows(listed[i]->first, listed[i]->second, &later, true);
    }
    if (own) {
        addHolderRows(own->first, own->second);
    }
    addNewRow(doc);
    if (!others.empty()) {
        addSectionRow(tr("Other copies in this document"));
        for (const Group* group : others) {
            addHolderRows(group->first, group->second);
        }
    }
}

void VariablesModel::addSectionRow(const QString& text)
{
    QList<QStandardItem*> row;
    for (int column = 0; column < ColumnCount; ++column) {
        auto item = new QStandardItem();
        item->setData(HeaderKind, KindRole);
        row << item;
    }
    row.front()->setText(text);
    row.front()->setToolTip(
        tr("Copies of other files' studios that this Variable Studio doesn't list: \"Add to this "
           "studio's references\" lists one that no other studio lists")
    );
    appendRow(row);
}

void VariablesModel::addNewRow(const App::Document* doc)
{
    // The studio's own rows end with an empty row, as Onshape's table (VS3): a name typed in it
    // adds a Length with no value
    App::DocumentObject* studio = doc->getObject(scope.c_str());
    if (!studio || freecad_cast<App::VarSetCopy*>(studio)) {
        return;
    }
    QList<QStandardItem*> row;
    for (int column = 0; column < ColumnCount; ++column) {
        auto item = new QStandardItem();
        item->setData(NewKind, KindRole);
        item->setData(QString::fromLatin1(doc->getName()), DocumentRole);
        item->setData(QString::fromLatin1(studio->getNameInDocument()), HolderRole);
        row << item;
    }
    row.front()->setText(tr("Name"));
    row.front()->setData(QString(), EditTextRole);
    row.front()->setForeground(Qt::gray);
    row.front()->setToolTip(tr("Type a name to add a Length variable"));
    insertRow(rowCount(), row);
}

void VariablesModel::addHolderRows(
    const App::DocumentObject* holder,
    const std::vector<std::string>& names,
    const std::set<std::string>* shadowed,
    bool referenced
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
    // FreeCAD-CH (ops#317 PR G2, ops#640 round 5): an attached copy's header says whether its
    // source changed since the last Refresh (design section 3.2); its orphans are flagged.
    CopyState state;
    auto copy = freecad_cast<const App::VarSetCopy*>(holder);
    if (copy && copy->isAttached()) {
        state = copyState(holder);
        header->setData(state.state, CopyStateRole);
        header->setData(state.message, CopyMessageRole);
        QString words = stateWords(state.state);
        if (!words.isEmpty()) {
            header->setText(tr("%1 (%2)").arg(label, words));
            header->setForeground(
                state.state == QLatin1String("out of date") ? QColor(0xc0, 0x70, 0x00)
                                                            : QColor(Qt::red)
            );
        }
        QStringList tip {state.message};
        if (!state.tip.isEmpty()) {
            tip << state.tip;
        }
        tip << QString::fromLatin1(holder->getNameInDocument());
        header->setToolTip(tip.join(QLatin1Char('\n')));
    }
    QList<QStandardItem*> headerRow {header};
    for (int column = 1; column < ColumnCount; ++column) {
        auto item = new QStandardItem();
        item->setData(HeaderKind, KindRole);
        headerRow << item;
    }
    // A Variable Studio's own variables are top-level rows, with no header (tabs slice 4)
    QStandardItem* parent = header;
    if (!scope.empty() && holder->getNameInDocument() == scope) {
        qDeleteAll(headerRow);
        parent = invisibleRootItem();
    }
    else {
        appendRow(headerRow);
    }

    for (const auto& name : names) {
        QString varName = QString::fromStdString(name);
        QString address;
        QString expression;
        App::Property* prop = holder->getPropertyByName(name.c_str());
        QString tip;
        QString description;  // a VarSet variable's; an alias has none

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
            const char* doc = holder->getPropertyDocumentation(prop);
            description = QString::fromUtf8(doc ? doc : "");
        }

        auto nameItem = new QStandardItem(varName);
        auto typeItem = new QStandardItem(variableType(prop));
        auto exprItem = new QStandardItem(expression);
        exprItem->setData(expression, EditTextRole);
        auto valueItem = new QStandardItem(valueText(prop));
        auto descriptionItem = new QStandardItem(descriptionLine(description));
        descriptionItem->setData(description, EditTextRole);
        auto sourceItem = new QStandardItem(
            sheet ? QStringLiteral("%1 %2").arg(label, address) : label
        );
        QList<QStandardItem*> row {
            nameItem,
            typeItem,
            exprItem,
            valueItem,
            descriptionItem,
            sourceItem
        };
        for (auto item : row) {
            item->setData(sheet ? AliasKind : VarSetKind, KindRole);
            item->setData(docName, DocumentRole);
            item->setData(holderName, HolderRole);
            item->setData(varName, VariableRole);
            item->setData(address, AddressRole);
            item->setToolTip(tip);
        }
        if (!description.isEmpty()) {
            descriptionItem->setToolTip(description);
        }
        // FreeCAD-CH (ops#640, measured variables 2): a measured variable shows what it reads and
        // is marked in Source; its own measurement's error (a lost reference) marks it failed.
        App::DocumentObject* measurement = sheet ? nullptr : measurementOf(holder, prop);
        if (measurement) {
            QString reads = measurementText(measurement);
            exprItem->setText(reads);
            exprItem->setData(reads, EditTextRole);
            sourceItem->setText(measuredWords(measurement));
            for (auto item : row) {
                item->setData(true, MeasuredRole);
                item->setToolTip(tr("%1: %2 (double-click to change what it measures)")
                                     .arg(varName, measuredWords(measurement)));
            }
        }
        if (measurement && measurement->isError()) {
            QString why = QString::fromUtf8(measurement->getStatusString());
            // Its users fail with it (FreeCAD marks them "'<measurement>' has an error")
            QStringList users;
            for (const auto& use : App::VariableLookup::uses(prop)) {
                if (use.user && use.user != holder && use.user->isError()) {
                    QString user = QString::fromUtf8(use.user->Label.getValue());
                    if (!users.contains(user)) {
                        users << user;
                    }
                }
            }
            QString tip = tr("%1 failed: %2").arg(varName, why);
            if (!users.isEmpty()) {
                tip += QLatin1Char('\n') + tr("Failed with it: %1").arg(users.join(QStringLiteral(", ")));
            }
            nameItem->setForeground(Qt::red);
            valueItem->setForeground(Qt::red);
            valueItem->setText(tr("failed"));
            for (auto item : row) {
                item->setToolTip(tip);
            }
        }
        else if (holder->isError() && !expression.isEmpty()) {
            valueItem->setForeground(Qt::red);
            valueItem->setToolTip(QString::fromUtf8(holder->getStatusString()));
        }
        auto orphan = state.orphans.find(name);
        if (orphan != state.orphans.end()) {
            // Removed at the source but still used (design section 3.4, D2): frozen, flagged.
            sourceItem->setText(tr("%1: %2").arg(label, orphan->second));
            nameItem->setForeground(Qt::gray);
            for (auto item : row) {
                item->setToolTip(tr("%1: %2").arg(varName, orphan->second));
            }
        }
        if (referenced) {
            // Onshape's referenced tables: every row grey (read-only), shadowed or not (VR9)
            for (auto item : row) {
                if (item->foreground() == QBrush()) {
                    item->setForeground(Qt::gray);
                }
            }
        }
        if (shadowed && shadowed->count(name)) {
            // ... and a name a later table defines again marked, as Onshape's: "Overwritten in
            // another variable table." (ops#722: own variables, then the last-listed reference)
            nameItem->setIcon(
                QApplication::style()->standardIcon(QStyle::SP_MessageBoxInformation)
            );
            nameItem->setToolTip(tr("Overwritten in another variable table."));
        }
        parent->appendRow(row);
    }
}

Qt::ItemFlags VariablesModel::flags(const QModelIndex& index) const
{
    Qt::ItemFlags result = QStandardItemModel::flags(index) & ~Qt::ItemIsEditable;
    if (isReadOnly(index)) {
        return result;
    }
    if (kind(index) == NewKind) {
        return index.column() == NameColumn ? result | Qt::ItemIsEditable : result;
    }
    // A measured variable's expression is its measurement: changed in its dialog (double-click)
    const bool measuredRow = index.data(MeasuredRole).toBool();
    if (kind(index) != HeaderKind
        && (index.column() == NameColumn
            || (index.column() == ExpressionColumn && !measuredRow))) {
        result |= Qt::ItemIsEditable;
    }
    if (kind(index) == VarSetKind && index.column() == DescriptionColumn) {
        result |= Qt::ItemIsEditable;  // an alias has no description
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
    if (!obj || kind(index) == HeaderKind || kind(index) == NewKind) {
        return nullptr;
    }
    return obj->getPropertyByName(index.data(VariableRole).toString().toStdString().c_str());
}

bool VariablesModel::isReadOnly(const QModelIndex& index)
{
    if (kind(index) != VarSetKind) {
        return false;
    }
    App::Property* prop = property(index);
    return prop && prop->testStatus(App::Property::ReadOnly);
}

bool VariablesModel::setData(const QModelIndex& index, const QVariant& value, int role)
{
    if (role != Qt::EditRole || kind(index) == HeaderKind) {
        return QStandardItemModel::setData(index, value, role);
    }
    error.clear();
    warning.clear();
    if (kind(index) == NewKind) {
        const QString name = value.toString().trimmed();
        if (index.column() != NameColumn || name.isEmpty()) {
            return name.isEmpty();
        }
        if (!addNamed) {
            return false;
        }
        return addNamed(name, error);
    }
    if (index.column() == NameColumn) {
        return rename(index, value.toString().trimmed());
    }
    if (index.column() == ExpressionColumn) {
        return setExpression(index, value.toString().trimmed());
    }
    if (index.column() == DescriptionColumn && kind(index) == VarSetKind) {
        if (value.toString() == index.data(EditTextRole).toString()) {
            return true;
        }
        return describe(
            holder(index),
            index.data(VariableRole).toString().toStdString(),
            value.toString(),
            error
        );
    }
    return false;
}

bool VariablesModel::describe(
    App::DocumentObject* obj,
    const std::string& name,
    const QString& text,
    QString& error
)
{
    App::Property* prop = obj ? obj->getPropertyByName(name.c_str()) : nullptr;
    if (!prop || !prop->testStatus(App::Property::PropDynamic)) {
        error = tr("The variable '%1' is gone.").arg(QString::fromStdString(name));
        return false;
    }
    std::string description = text.trimmed().toStdString();
    const char* old = obj->getPropertyDocumentation(prop);
    if (description == (old ? old : "")) {
        return true;
    }
    return runEdit(
        obj->getDocument(),
        "Describe " + name,
        {pyObject(obj) + ".setDocumentationOfProperty(" + pyString(name) + ", "
         + pyString(description) + ")"},
        error
    );
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
    if (!isValidName(name, isSheet(obj))) {
        error = isSheet(obj)
            ? tr("'%1' is not a valid name: use a name that isn't a unit, a constant or a cell "
                 "address.")
                  .arg(newName)
            : tr("'%1' is not a valid name: use letters, digits and _, and no cell address or "
                 "function name.")
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
    bool alias = kind(index) == AliasKind;
    App::Property* prop = alias ? nullptr : obj->getPropertyByName(name.c_str());
    if (!alias && !prop) {
        error = tr("The variable '%1' is gone.").arg(QString::fromStdString(name));
        return false;
    }
    std::vector<std::string> commands;
    if (!editCommands(
            obj,
            prop,
            index.data(AddressRole).toString().toStdString(),
            name,
            text,
            commands,
            error
        )) {
        return false;
    }
    return runEdit(obj->getDocument(), "Set " + name, commands, error);
}

bool VariablesModel::editCommands(
    App::DocumentObject* obj,
    App::Property* prop,
    const std::string& address,
    const std::string& name,
    const QString& text,
    std::vector<std::string>& commands,
    QString& error,
    bool* isExpression
)
{
    std::string typed = text.toStdString();
    bool alias = prop == nullptr;
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

    if (isExpression) {
        *isExpression = as == As::Expression;
    }
    std::string target = pyObject(obj);
    if (as != As::Expression) {
        if (alias) {
            commands.push_back(target + ".set('" + address + "', " + pyString(typed) + ")");
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
            commands.push_back(target + ".set('" + address + "', " + pyString("=" + stored) + ")");
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
    return true;
}

QString VariablesModel::unitMismatch(App::DocumentObject* obj, App::Property* prop)
{
    auto quantity = freecad_cast<App::PropertyQuantity*>(prop);
    bool number = !quantity && freecad_cast<App::PropertyFloat*>(prop);
    if (!obj || (!quantity && !number)) {
        return {};
    }
    auto info = obj->getExpression(App::ObjectIdentifier(*prop));
    if (!info.expression) {
        return {};
    }
    App::ExpressionPtr result;
    try {
        result = info.expression->eval();
    }
    catch (const Base::Exception& e) {
        return QString::fromUtf8(e.what());
    }
    auto value = freecad_cast<App::NumberExpression*>(result.get());
    if (!value) {
        return {};  // not a number: the property says what it takes
    }
    const Base::Unit& unit = value->getQuantity().getUnit();
    const Base::Unit& wanted = quantity ? quantity->getUnit() : Base::Unit::One;
    // A unitless result takes a quantity's default unit, as App's checkPathUnit and the
    // Expression column take it.
    if (unit == wanted || (quantity && unit == Base::Unit::One)) {
        return {};
    }
    QString name = QString::fromUtf8(prop->getName());
    QString gives = unit == Base::Unit::One
        ? tr("a number without a unit")
        : QString::fromStdString(value->getQuantity().getUserString());
    return tr("The expression gives %1, but the type of %2 is %3.")
        .arg(gives, name, variableType(prop));
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
    if (index.column() == VariablesModel::DescriptionColumn
        && index.data(VariablesModel::EditTextRole).toString().contains(u'\n')) {
        // One line in the cell would lose the others: the dialog edits them all.
        QPersistentModelIndex persistent(index);
        QTimer::singleShot(0, const_cast<VariablesDelegate*>(this), [this, persistent] {
            if (persistent.isValid()) {
                Q_EMIT multiLineEdit(persistent);
            }
        });
        return nullptr;
    }
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

VariablesView::VariablesView(Gui::Document* doc, QWidget* parent, App::DocumentObject* studio)
    : DockWindow(doc, parent)
{
    if (studio && studio->isAttachedToDocument()) {
        studioName = studio->getNameInDocument();
        documentName = studio->getDocument()->getName();
    }
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
    importAction = toolBar->addAction(
        tr("Import variables..."),
        this,
        &VariablesView::importVariables
    );
    importAction->setObjectName(QStringLiteral("importVariables"));
    importAction->setToolTip(
        tr("Import Onshape variable studio exports (.json) as read-only copies")
    );
    // FreeCAD-CH (ops#317 PRs G2 and F, ops#640 round 5): a VarSet of a saved FreeCAD file as a
    // copy, and a copy's Refresh and Locate, each through freecad.variables.importgui's preview.
    // An object's and a document's internal names are identifiers, safe in the code.
    auto runGui = [this](const std::string& call) {
        std::string code = "from freecad.variables import importgui\nimportgui." + call + "\n";
        try {
            Base::Interpreter().runString(code.c_str());
        }
        catch (const Base::Exception& e) {
            showMessage(QString::fromUtf8(e.what()), true);
        }
    };
    auto currentCopy = [this]() -> App::VarSetCopy* {
        auto copy = freecad_cast<App::VarSetCopy*>(VariablesModel::holder(tree->currentIndex()));
        return copy && copy->isAttached() ? copy : nullptr;
    };
    auto copyCall = [](const char* function, const App::VarSetCopy* copy) {
        return std::string(function) + "(FreeCAD.getDocument(\"" + copy->getDocument()->getName()
            + "\").getObject(\"" + copy->getNameInDocument() + "\"))";
    };
    QAction* copyAction = toolBar->addAction(tr("Copy from FreeCAD file..."), this, [this, runGui] {
        if (App::Document* doc = currentDocument()) {
            std::string docCall = "FreeCAD.getDocument(\"" + std::string(doc->getName()) + "\")";
            // FreeCAD-CH ops#721: a studio's Insert puts the copy into its reference list
            App::DocumentObject* obj = this->studio();
            std::string studioArg = obj
                ? ", studio=" + docCall + ".getObject(\"" + obj->getNameInDocument() + "\")"
                : std::string();
            runGui("copy_from_file(" + docCall + studioArg + ")");
        }
    });
    copyAction->setObjectName(QStringLiteral("copyFromFreeCAD"));
    copyAction->setToolTip(
        tr("Copy a VarSet of a saved FreeCAD document as a read-only copy, read from the file")
    );
    QAction* refreshAction = toolBar->addAction(
        tr("Refresh..."),
        this,
        [runGui, currentCopy, copyCall] {
            if (App::VarSetCopy* copy = currentCopy()) {
                runGui(copyCall("refresh", copy));
            }
        }
    );
    refreshAction->setObjectName(QStringLiteral("refreshCopy"));
    refreshAction->setToolTip(
        tr("Read the selected copy's source again: a preview, then the changes as one undo step")
    );
    auto locateAction = new QAction(tr("Locate source..."), this);
    locateAction->setObjectName(QStringLiteral("locateSource"));
    locateAction->setToolTip(tr("Point the selected copy at another source file, then Refresh"));
    connect(locateAction, &QAction::triggered, this, [runGui, currentCopy, copyCall] {
        if (App::VarSetCopy* copy = currentCopy()) {
            runGui(copyCall("locate", copy));
        }
    });
    // FreeCAD-CH ops#721: a Variable Studio's reference list (notes/variable-studio-references.md
    // section 2), in its table's context menu: Move up, Move down, Remove reference, and Add to
    // this studio's references for a copy in no list. Stored expressions keep their variables;
    // the message names those whose #name now means another one (ops#732 is the rebind).
    auto referenceCall = [this](const char* function, App::DocumentObject* a, App::DocumentObject* b,
                                int index) {
        Base::PyGILStateLocker lock;
        try {
            PyObject* imported = PyImport_ImportModule("freecad.variables.copies");
            if (!imported) {
                throw Py::Exception();
            }
            Py::Module module(imported, true);
            Py::Callable call(module.getAttr(function));
            Py::Tuple args(b ? 2 : (index >= 0 ? 2 : 1));
            args.setItem(0, Py::asObject(a->getPyObject()));
            if (b) {
                args.setItem(1, Py::asObject(b->getPyObject()));
            }
            else if (index >= 0) {
                args.setItem(1, Py::Long(index));
            }
            Py::Object plan = call.apply(args);
            QStringList lines;
            Py::List warnings(plan.getAttr("warnings"));
            for (const auto& line : warnings) {
                lines << QString::fromStdString(Py::String(line).as_std_string("utf-8"));
            }
            showMessage(lines.join(QLatin1Char('\n')), false);
        }
        catch (Py::Exception&) {
            Base::PyException error;
            showMessage(QString::fromUtf8(error.what()), true);
        }
    };
    auto listedCopy = [this, currentCopy]() -> std::pair<App::VarSetCopy*, int> {
        App::VarSetCopy* copy = currentCopy();
        App::DocumentObject* obj = this->studio();
        if (!copy || !obj || App::DocumentTabs::studioOf(copy) != obj) {
            return {nullptr, -1};
        }
        const auto list = App::DocumentTabs::variableReferences(obj);
        auto it = std::find(list.begin(), list.end(), copy);
        return {copy, static_cast<int>(it - list.begin())};
    };
    auto moveUpAction = new QAction(tr("Move reference up"), this);
    moveUpAction->setObjectName(QStringLiteral("moveReferenceUp"));
    moveUpAction->setToolTip(tr("Move the selected reference up: a later reference wins"));
    connect(moveUpAction, &QAction::triggered, this, [listedCopy, referenceCall] {
        auto [copy, position] = listedCopy();
        if (copy && position > 0) {
            referenceCall("move_reference", copy, nullptr, position - 1);
        }
    });
    auto moveDownAction = new QAction(tr("Move reference down"), this);
    moveDownAction->setObjectName(QStringLiteral("moveReferenceDown"));
    moveDownAction->setToolTip(tr("Move the selected reference down: a later reference wins"));
    connect(moveDownAction, &QAction::triggered, this, [listedCopy, referenceCall] {
        auto [copy, position] = listedCopy();
        if (copy) {
            referenceCall("move_reference", copy, nullptr, position + 1);
        }
    });
    auto removeReferenceAction = new QAction(tr("Remove reference"), this);
    removeReferenceAction->setObjectName(QStringLiteral("removeReference"));
    removeReferenceAction->setToolTip(
        tr("Take the selected reference out of this studio's list; the copy stays in the document")
    );
    connect(removeReferenceAction, &QAction::triggered, this, [listedCopy, referenceCall] {
        auto [copy, position] = listedCopy();
        (void)position;
        if (copy) {
            referenceCall("remove_reference", copy, nullptr, -1);
        }
    });
    auto addReferenceAction = new QAction(tr("Add to this studio's references"), this);
    addReferenceAction->setObjectName(QStringLiteral("addReference"));
    addReferenceAction->setToolTip(tr("List the selected copy last in this studio's references"));
    connect(addReferenceAction, &QAction::triggered, this, [this, currentCopy, referenceCall] {
        App::VarSetCopy* copy = currentCopy();
        App::DocumentObject* obj = this->studio();
        if (copy && obj && !App::DocumentTabs::studioOf(copy)) {
            referenceCall("add_reference", obj, copy, -1);
        }
    });
    // FreeCAD-CH (ops#640): the toolbar's text actions don't set the panel's width (a dock 441 px
    // wide took 185 px from the 3D view in round 5): what doesn't fit goes to its overflow button,
    // and every action is in the list's context menu too
    toolBar->setSizePolicy(QSizePolicy::Ignored, toolBar->sizePolicy().verticalPolicy());
    layout->addWidget(toolBar);
    // In the context menu only
    describeAction = new QAction(tr("Edit description..."), this);
    describeAction->setObjectName(QStringLiteral("editDescription"));
    describeAction->setToolTip(tr("Edit the selected variable's description, in several lines"));
    connect(describeAction, &QAction::triggered, this, &VariablesView::editDescription);

    model = new VariablesModel(this);
    delegate = new VariablesDelegate(this);
    tree = new VariablesTree(this);
    tree->setObjectName(QStringLiteral("variablesTree"));
    model->setScope(studioName);
    model->addNamed = [this](const QString& name, QString& error) {
        App::DocumentObject* obj = this->studio();
        if (!obj || !currentDocument()) {
            error = tr("The Variable Studio is gone.");
            return false;
        }
        return addFromDialog(
            currentDocument()->getName(),
            obj->getNameInDocument(),
            name,
            "App::PropertyDistance",
            QString(),
            QString(),
            error
        );
    };
    tree->setModel(model);
    tree->setItemDelegate(delegate);
    if (!studioName.empty()) {
        // The studio itself is every own row's source; the Onshape import makes copies, which
        // the dock lists
        tree->setColumnHidden(VariablesModel::SourceColumn, true);
        importAction->setVisible(false);
        tree->setRootIsDecorated(false);
        // Onshape's "Insert Variable Studio" (VS8): here another file's VarSet, as a copy that
        // Refresh reads again (a studio of this document needs no insert: every studio sees it)
        copyAction->setText(tr("Insert Variable Studio..."));
        copyAction->setToolTip(
            tr("Insert a Variable Studio of a saved FreeCAD document, as a read-only copy that "
               "Refresh reads again")
        );
    }
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
    tree->addAction(describeAction);
    tree->addAction(importAction);
    tree->addAction(copyAction);
    tree->addAction(refreshAction);
    tree->addAction(locateAction);
    if (!studioName.empty()) {
        for (QAction* action : {moveUpAction, moveDownAction, removeReferenceAction, addReferenceAction}) {
            tree->addAction(action);
        }
    }
    layout->addWidget(tree);

    hint = new QLabel(
        studioName.empty() ? tr("Add a variable, or type #name in any expression.")
                           : tr("Add a variable: every Part Studio uses it as #name."),
        this
    );
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
    connect(delegate, &VariablesDelegate::multiLineEdit, this, [this](const QModelIndex& index) {
        tree->setCurrentIndex(index);
        editDescription();
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
    // A description or group change (ops#317 PR A)
    connections.emplace_back(app.signalChangePropertyEditor.connect(
        [this](const App::Document&, const App::Property& prop) { onProperty(prop); }
    ));
    connections.emplace_back(app.signalUndoDocument.connect([this](const App::Document&) {
        scheduleRebuild();
    }));
    connections.emplace_back(app.signalRedoDocument.connect([this](const App::Document&) {
        scheduleRebuild();
    }));
    connections.emplace_back(app.signalRecomputed.connect([this](const App::Document&) {
        scheduleRebuild();
    }));
    // FreeCAD-CH (ops#317 PR G2, ops#640 round 5): a copy's source may have changed while FreeCAD
    // was in the background (an Onshape re-export) or been saved here: the states are checked
    // again (a stat first, the file read only when it changed). Before a document is saved, its
    // copies' relative source paths are rewritten for the file it is saved to (Save As too).
    connect(qGuiApp, &QGuiApplication::applicationStateChanged, this, [this](Qt::ApplicationState s) {
        if (s == Qt::ApplicationActive && hasCopies(currentDocument())) {
            scheduleRebuild();
        }
    });
    connections.emplace_back(app.signalFinishSaveDocument.connect(
        [this](const App::Document&, const std::string&) {
            if (hasCopies(currentDocument())) {
                scheduleRebuild();
            }
        }
    ));
    connections.emplace_back(app.signalStartSaveDocument.connect(
        [](const App::Document& doc, const std::string& file) {
            if (!hasCopies(&doc)) {
                return;
            }
            Base::PyGILStateLocker lock;
            try {
                PyObject* raw = PyImport_ImportModule("freecad.variables.copies");
                if (!raw) {
                    throw Py::Exception();
                }
                Py::Module module(raw, true);
                Py::Callable function(module.getAttr("before_save"));
                Py::Tuple args(2);
                args.setItem(0, Py::Object(const_cast<App::Document&>(doc).getPyObject(), true));
                args.setItem(1, Py::String(file));
                function.apply(args);
            }
            catch (Py::Exception&) {
                Base::PyException e;  // a save doesn't fail for it
                e.reportException();
            }
        }
    ));
    // FreeCAD-CH (ops#640, hands-on D-1): a variable made inside a dialog's transaction stays when
    // the dialog is cancelled, as in Onshape. The abort took it back: it is made again, in its own
    // transaction, after the abort (the signal comes while the document is rolling back).
    connections.emplace_back(app.signalAbortTransaction.connect([this](const App::Document& doc) {
        std::vector<PendingVariable> pending = takePendingVariables(doc.getName());
        if (pending.empty()) {
            return;
        }
        QTimer::singleShot(0, this, [this, pending] {
            for (const auto& var : pending) {
                App::Document* document = App::GetApplication().getDocument(var.docName.c_str());
                if (!document) {
                    continue;
                }
                std::string holderName = var.holderName;
                App::DocumentObject* holder = holderName.empty()
                    ? nullptr
                    : document->getObject(holderName.c_str());
                if (!holder) {
                    // The set went with the abort (or was made with the variable): the
                    // "Variables" set, if one is left, else a new one.
                    holder = document->getObject("Variables");
                    holderName = isEditableSet(holder) ? holder->getNameInDocument() : "";
                    if (holderName.empty()) {
                        holder = nullptr;
                    }
                }
                if (holder && holder->getPropertyByName(var.name.toStdString().c_str())) {
                    continue;  // not taken back
                }
                QString error;
                pendingClashChoice() = var.clashChoice;
                if (!addFromDialog(
                        var.docName,
                        holderName,
                        var.name,
                        var.type.c_str(),
                        var.text,
                        var.description,
                        error
                    )) {
                    showMessage(error, true);
                }
            }
        });
    }));
    connections.emplace_back(app.signalCommitTransaction.connect([](const App::Document& doc) {
        takePendingVariables(doc.getName());  // committed with the dialog's step
    }));
    connections.emplace_back(app.signalDeleteDocument.connect([](const App::Document& doc) {
        takePendingVariables(doc.getName());  // a later document of the same name isn't this one
    }));
    connections.emplace_back(Application::Instance->signalActiveDocument.connect(
        std::bind(&VariablesView::onActiveDocument, this, sp::_1)
    ));
    connections.emplace_back(Application::Instance->signalDeleteDocument.connect(
        std::bind(&VariablesView::onDeleteDocument, this, sp::_1)
    ));

    if (Gui::Document* active = Application::Instance->activeDocument();
        active && studioName.empty()) {
        documentName = active->getDocument()->getName();
    }
    rebuild();
    if (!studioName.empty()) {
        return;  // the rest is the dock's: the Variable tool and the keymap's first showing
    }

    // FreeCAD-CH (ops#640, rank 15): the Variable tool, made with the panel it opens
    CommandManager& commands = Application::Instance->commandManager();
    if (!commands.getCommandByName("Std_AddVariable")) {
        commands.addCommand(new StdCmdAddVariable());
    }
    // Under the Onshape keymap the panel is shown on the right, as Onshape's variable table is
    // (F13), once: the dock windows' saved state keeps it closed when the user closes it.
    if (ForkKeymap::isOnshape()) {
        auto marker = App::GetApplication().GetParameterGroupByPath(
            "User parameter:BaseApp/Preferences/DockWindows/VariablesView"
        );
        if (!marker->GetBool("ShownByKeymap", false)) {
            marker->SetBool("ShownByKeymap", true);
            App::GetApplication()
                .GetParameterGroupByPath("User parameter:BaseApp/MainWindow/DockWindows")
                ->SetBool("Std_VariablesView", true);
        }
    }
}

VariablesView::~VariablesView() = default;

App::Document* VariablesView::currentDocument() const
{
    return documentName.empty() ? nullptr : App::GetApplication().getDocument(documentName.c_str());
}

App::DocumentObject* VariablesView::studio() const
{
    App::Document* doc = studioName.empty() ? nullptr : currentDocument();
    return doc ? doc->getObject(studioName.c_str()) : nullptr;
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
    if (!studioName.empty()) {
        return;  // a Variable Studio's table stays on its document
    }
    std::string name = doc.getDocument()->getName();
    if (name != documentName) {
        documentName = name;
        showMessage(QString(), false);
        scheduleRebuild();
    }
    // FreeCAD-CH (ops#640, rank 15): Add follows the document now, also while the panel is hidden
    // and its rebuild waits: the Variable tool shows the panel and triggers Add at once, which a
    // hidden panel's stale state left disabled (no Add dialog)
    updateActions();
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
        if (VariablesModel::kind(header) != VariablesModel::HeaderKind) {
            continue;  // a Variable Studio's own row
        }
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
        if (VariablesModel::kind(header) != VariablesModel::HeaderKind) {
            // A Variable Studio's own row (tabs slice 4): flat, the current row kept
            if (!currentVariable.isEmpty()
                && header.data(VariablesModel::HolderRole).toString() == currentHolder
                && header.data(VariablesModel::VariableRole).toString() == currentVariable) {
                tree->setCurrentIndex(model->index(row, currentColumn));
            }
            continue;
        }
        tree->setFirstColumnSpanned(row, QModelIndex(), true);
        QString holder = header.data(VariablesModel::HolderRole).toString();
        tree->setExpanded(header, !collapsed.contains(headerKey(header)));
        if (currentVariable.isEmpty()) {
            if (holder == currentHolder) {
                tree->setCurrentIndex(header);
            }
            continue;
        }
        // Each row's own holder: a measured variable's row sits under its studio's set (ops#640)
        for (int child = 0; child < model->rowCount(header); ++child) {
            QModelIndex index = model->index(child, currentColumn, header);
            if (index.data(VariablesModel::HolderRole).toString() == currentHolder
                && index.data(VariablesModel::VariableRole).toString() == currentVariable) {
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
        && VariablesModel::kind(current) != VariablesModel::HeaderKind
        && VariablesModel::kind(current) != VariablesModel::NewKind;
    addAction->setEnabled(currentDocument() != nullptr);
    importAction->setEnabled(currentDocument() != nullptr);
    // A copy's Refresh and Locate (ops#317 PR G2): on an attached copy's header or variable.
    auto copy = freecad_cast<App::VarSetCopy*>(VariablesModel::holder(current));
    bool attached = copy && copy->isAttached();
    for (const char* name : {"refreshCopy", "locateSource"}) {
        if (auto action = findChild<QAction*>(QString::fromLatin1(name))) {
            action->setEnabled(attached);
        }
    }
    if (auto action = findChild<QAction*>(QStringLiteral("copyFromFreeCAD"))) {
        action->setEnabled(currentDocument() != nullptr);
    }
    // A studio's reference actions (ops#721): on a copy's header or variable
    App::DocumentObject* obj = studio();
    App::DocumentObject* listedIn = attached ? App::DocumentTabs::studioOf(copy) : nullptr;
    bool listed = obj && listedIn == obj;
    int position = -1;
    int count = 0;
    if (listed) {
        const auto list = App::DocumentTabs::variableReferences(obj);
        count = static_cast<int>(list.size());
        position = static_cast<int>(std::find(list.begin(), list.end(), copy) - list.begin());
    }
    const std::pair<const char*, bool> referenceStates[] = {
        {"moveReferenceUp", listed && position > 0},
        {"moveReferenceDown", listed && position + 1 < count},
        {"removeReference", listed},
        {"addReference", obj && attached && !listedIn},
    };
    for (const auto& [name, enabled] : referenceStates) {
        if (auto action = findChild<QAction*>(QString::fromLatin1(name))) {
            action->setEnabled(enabled);
        }
    }
    // A copy's variable can't be deleted or described while the copy is attached (ops#317).
    bool readOnly = VariablesModel::isReadOnly(current);
    deleteAction->setEnabled(variable && !readOnly);
    usesAction->setEnabled(variable);
    describeAction->setEnabled(
        current.isValid() && VariablesModel::kind(current) == VariablesModel::VarSetKind
        && !readOnly
    );
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
    // FreeCAD-CH (ops#640, measured variables 2): a measured variable reopens its dialog, as an
    // Onshape Variable feature opens for editing (the name stays editable in place).
    if (index.data(MeasuredRole).toBool() && index.column() != VariablesModel::NameColumn
        && index.column() != VariablesModel::DescriptionColumn) {
        App::DocumentObject* obj = VariablesModel::holder(index);
        if (!obj) {
            return;
        }
        QString error;
        {
            Base::PyGILStateLocker lock;
            Py::Tuple holderName(2);
            holderName.setItem(0, Py::String(obj->getDocument()->getName()));
            holderName.setItem(1, Py::String(obj->getNameInDocument()));
            Py::Tuple call(2);
            call.setItem(0, holderName);
            call.setItem(
                1,
                Py::String(index.data(VariablesModel::VariableRole).toString().toStdString())
            );
            error = runMeasuredGui("edit", call);
        }
        showMessage(error, !error.isEmpty());
        return;
    }
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

App::DocumentObject* VariablesView::addTarget() const
{
    App::Document* doc = currentDocument();
    if (!doc) {
        return nullptr;
    }
    if (!studioName.empty()) {
        App::DocumentObject* obj = studio();
        return isEditableSet(obj) ? obj : nullptr;  // a Variable Studio adds to itself
    }
    // The selected row's VarSet, else the document's "Variables" VarSet; never a copy that is
    // still attached to its source (ops#317: its variables are read-only).
    if (App::DocumentObject* obj = VariablesModel::holder(tree->currentIndex())) {
        if (isEditableSet(obj) && !isMeasuredHolder(obj)) {
            return obj;
        }
    }
    App::DocumentObject* obj = doc->getObject("Variables");
    if (isEditableSet(obj)) {
        return obj;
    }
    for (auto obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
        if (std::string(obj->Label.getValue()) == "Variables" && isEditableSet(obj)) {
            return obj;
        }
    }
    return nullptr;
}

void VariablesView::addVariable()
{
    // The panel's own Add dialog (ops#317, design section 1.3): Name, Type, Value or expression,
    // Description and Set, added as one undo step; "Other..." opens the stock dialog.
    App::Document* doc = currentDocument();
    if (!doc) {
        return;
    }
    App::DocumentObject* target = addTarget();
    if (!studioName.empty() && !target) {
        return;  // the studio is gone
    }
    std::string docName = doc->getName();

    auto dialog = new QDialog(getMainWindow());
    dialog->setObjectName(QStringLiteral("addVariableDialog"));
    dialog->setWindowTitle(tr("Add variable"));
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowModality(Qt::ApplicationModal);

    auto nameEdit = new QLineEdit(dialog);
    nameEdit->setObjectName(QStringLiteral("name"));
    auto typeBox = new QComboBox(dialog);
    typeBox->setObjectName(QStringLiteral("type"));
    // A Length is a Distance: a Length clamps a negative value to 0 without a word (ops#319). No
    // Integer: it rounds what an expression gives and drops its unit; "Other..." has it.
    typeBox->addItem(tr("Length"), QByteArray("App::PropertyDistance"));
    typeBox->addItem(tr("Angle"), QByteArray("App::PropertyAngle"));
    typeBox->addItem(tr("Number"), QByteArray("App::PropertyFloat"));
    typeBox->addItem(tr("Yes/No"), QByteArray("App::PropertyBool"));
    typeBox->addItem(tr("Text"), QByteArray("App::PropertyString"));
    // FreeCAD-CH (ops#640, measured variables 2): Onshape's Variable feature in the measured
    // mode. OK opens the measured variable dialog, which takes picks in the 3D view; Distance's
    // minimum or center to center is chosen there.
    if (studioName.empty()) {  // a Variable Studio has no geometry to measure
        typeBox->insertSeparator(typeBox->count());
        typeBox->addItem(tr("Measured distance"), QByteArray(measuredTypePrefix) + "Distance");
        typeBox->addItem(tr("Measured length"), QByteArray(measuredTypePrefix) + "Length");
        typeBox->addItem(tr("Measured diameter"), QByteArray(measuredTypePrefix) + "Diameter");
    }
    auto valueEdit = new ExpressionLineEdit(dialog);
    valueEdit->setObjectName(QStringLiteral("value"));
    valueEdit->setValidator(nullptr);  // as in the Expression column: '=' starts an expression
    valueEdit->setPlaceholderText(tr("A value, or an expression with #name"));
    auto descriptionEdit = new QPlainTextEdit(dialog);
    descriptionEdit->setObjectName(QStringLiteral("description"));
    descriptionEdit->setTabChangesFocus(true);
    descriptionEdit->setFixedHeight(descriptionEdit->fontMetrics().lineSpacing() * 4);
    auto setBox = new QComboBox(dialog);
    setBox->setObjectName(QStringLiteral("set"));
    for (auto obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
        if (!isEditableSet(obj)) {
            continue;  // an attached copy (ops#317)
        }
        if (isMeasuredHolder(obj)) {
            continue;  // a measured variable's own set (ops#640): it holds that variable only
        }
        if (!studioName.empty() && obj != target) {
            continue;  // a Variable Studio's Add: the studio only
        }
        setBox->addItem(
            QString::fromUtf8(obj->Label.getValue()),
            QString::fromLatin1(obj->getNameInDocument())
        );
    }
    if (!target) {
        setBox->insertItem(0, tr("Variables (new)"), QString());
    }
    setBox->setCurrentIndex(
        target ? setBox->findData(QString::fromLatin1(target->getNameInDocument())) : 0
    );
    // `#` completion: from the set's VarSet, else from any object of the document.
    if (target) {
        valueEdit->setDocumentObject(target);
    }
    else if (!doc->getObjects().empty()) {
        valueEdit->setDocumentObject(doc->getObjects().front());
    }

    // FreeCAD-CH (ops#640, rank 55): from a field's "New variable...": its name, its value as
    // the variable's, and the type that value has. Onshape fills in the name the same way.
    const QStringList fromField = qApp->property(newVariableProperty).toStringList();
    qApp->setProperty(newVariableProperty, QVariant());
    if (!fromField.isEmpty()) {
        nameEdit->setText(fromField.front());
        if (fromField.size() > 1) {
            valueEdit->setText(fromField.at(1));
            try {
                Base::Quantity quantity = Base::Quantity::parse(fromField.at(1).toStdString());
                const char* type = quantity.getUnit() == Base::Unit::Angle ? "App::PropertyAngle"
                    : quantity.isDimensionless()                           ? "App::PropertyFloat"
                                                 : "App::PropertyDistance";
                int index = typeBox->findData(QByteArray(type));
                if (index >= 0) {
                    typeBox->setCurrentIndex(index);
                }
            }
            catch (const Base::Exception&) {
                // not a plain value: the type stays Length
            }
        }
    }

    auto errorLabel = new QLabel(dialog);
    errorLabel->setObjectName(QStringLiteral("error"));
    errorLabel->setWordWrap(true);
    errorLabel->setStyleSheet(QStringLiteral("color: red;"));
    errorLabel->setTextInteractionFlags(Qt::TextSelectableByMouse);
    errorLabel->hide();

    auto buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, dialog);
    QPushButton* other = buttons->addButton(tr("Other..."), QDialogButtonBox::ActionRole);
    other->setObjectName(QStringLiteral("other"));
    other->setToolTip(tr("Add a property of any type with the Add Property dialog"));

    auto form = new QFormLayout();
    form->addRow(tr("Name:"), nameEdit);
    form->addRow(tr("Type:"), typeBox);
    form->addRow(tr("Value:"), valueEdit);
    form->addRow(tr("Description:"), descriptionEdit);
    form->addRow(tr("Set:"), setBox);
    auto layout = new QVBoxLayout(dialog);
    layout->addLayout(form);
    layout->addWidget(errorLabel);
    layout->addWidget(buttons);

    // A measured kind: the value comes from the picks, and the variable goes into the active Part
    // Studio's own set.
    auto onType = [=](int) {
        const bool measuredKind
            = typeBox->currentData().toByteArray().startsWith(measuredTypePrefix);
        valueEdit->setEnabled(!measuredKind);
        setBox->setEnabled(!measuredKind);
        valueEdit->setPlaceholderText(
            measuredKind ? tr("Picked in the 3D view after OK")
                         : tr("A value, or an expression with #name")
        );
        setBox->setToolTip(
            measuredKind ? tr("A measured variable goes into its Part Studio's variables")
                         : QString()
        );
    };
    connect(typeBox, qOverload<int>(&QComboBox::currentIndexChanged), dialog, onType);

    QPointer<VariablesView> view(this);
    connect(buttons, &QDialogButtonBox::accepted, dialog, [=] {
        if (!view) {
            dialog->reject();
            return;
        }
        QByteArray type = typeBox->currentData().toByteArray();
        QString error;
        if (type.startsWith(measuredTypePrefix)) {
            // The measured variable dialog checks the name against the studio's set and opens;
            // nothing is made before its OK.
            {
                Base::PyGILStateLocker lock;
                Py::Tuple args(4);
                args.setItem(0, Py::String(docName));
                args.setItem(1, Py::String(nameEdit->text().trimmed().toStdString()));
                args.setItem(
                    2,
                    Py::String(type.mid(int(std::strlen(measuredTypePrefix))).toStdString())
                );
                args.setItem(3, Py::String(descriptionEdit->toPlainText().toStdString()));
                error = runMeasuredGui("start", args);
            }
            if (error.isEmpty()) {
                view->showMessage(QString(), false);
                dialog->accept();
                return;
            }
            errorLabel->setText(error);
            errorLabel->show();
            return;
        }
        // FreeCAD-CH (ops#640, decision 317): a name an imported copy has: asked before anything
        // is made; Cancel keeps the dialog as it is.
        std::string clashChoice;
        App::Document* addDoc = App::GetApplication().getDocument(docName.c_str());
        if (addDoc
            && !askNameClash(
                dialog,
                addDoc,
                setBox->currentData().toString().toStdString(),
                nameEdit->text().trimmed().toStdString(),
                clashChoice
            )) {
            return;
        }
        if (!view) {
            dialog->reject();
            return;
        }
        pendingClashChoice() = clashChoice;
        if (view->addFromDialog(
                docName,
                setBox->currentData().toString().toStdString(),
                nameEdit->text().trimmed(),
                type.constData(),
                valueEdit->text().trimmed(),
                descriptionEdit->toPlainText(),
                error
            )) {
            view->showMessage(QString(), false);
            dialog->accept();
            return;
        }
        // Nothing was added: say why, and keep what was typed.
        errorLabel->setText(error);
        errorLabel->show();
    });
    connect(buttons, &QDialogButtonBox::rejected, dialog, &QDialog::reject);
    connect(other, &QPushButton::clicked, dialog, [=] {
        std::string holderName = setBox->currentData().toString().toStdString();
        dialog->reject();
        if (!view) {
            return;
        }
        // After the click: the stock flow processes events, which would delete this dialog and
        // its button under their own handler.
        QTimer::singleShot(0, view, [view, docName, holderName] {
            App::Document* doc = App::GetApplication().getDocument(docName.c_str());
            if (!view || !doc || doc != view->currentDocument()) {
                return;
            }
            App::DocumentObject* holder = holderName.empty() ? nullptr
                                                             : doc->getObject(holderName.c_str());
            // A chosen set deleted meanwhile: never a new "Variables" set in its place.
            if (!holderName.empty() && !holder) {
                view->showMessage(
                    tr("The set '%1' is gone.").arg(QString::fromStdString(holderName)),
                    true
                );
                return;
            }
            view->addOtherVariable(holder);
        });
    });

    dialog->show();
    dialog->raise();
    dialog->activateWindow();
    if (fromField.isEmpty()) {
        nameEdit->setFocus();
    }
    else {
        valueEdit->setFocus();
        valueEdit->selectAll();
    }
}

bool VariablesView::addFromDialog(
    const std::string& docName,
    const std::string& holderName,
    const QString& name,
    const char* type,
    const QString& text,
    const QString& description,
    QString& error
)
{
    App::Document* doc = App::GetApplication().getDocument(docName.c_str());
    if (!doc) {
        error = tr("The document is gone.");
        return false;
    }
    App::DocumentObject* target = holderName.empty() ? nullptr
                                                     : doc->getObject(holderName.c_str());
    if (!holderName.empty() && !target) {
        error = tr("The set '%1' is gone.").arg(QString::fromStdString(holderName));
        return false;
    }
    if (target && !isEditableSet(target)) {
        error = tr("'%1' is a copy of its source: its variables can't be changed here.")
                    .arg(QString::fromUtf8(target->Label.getValue()));
        return false;
    }
    std::string varName = name.toStdString();
    // FreeCAD-CH (ops#640, decision 317): the answer to the name clash question, taken once.
    const std::string clashChoice = std::exchange(pendingClashChoice(), std::string());

    // Checked before anything is made: the name, and a plain value's unit against the type.
    std::string reason = App::VariableLookup::checkVariableName(target, varName);
    if (!reason.empty()) {
        error = QString::fromStdString(reason);
        return false;
    }
    std::string typeName(type);
    if (!text.isEmpty()
        && (typeName == "App::PropertyDistance" || typeName == "App::PropertyAngle"
            || typeName == "App::PropertyFloat")) {
        try {
            Base::Quantity quantity = Base::Quantity::parse(text.toStdString());
            const Base::Unit& wanted = typeName == "App::PropertyDistance" ? Base::Unit::Length
                : typeName == "App::PropertyAngle"                         ? Base::Unit::Angle
                                                                           : Base::Unit::One;
            // A number without a unit takes the type's default unit, as in the Expression column.
            if (quantity.getUnit() != wanted && !quantity.isDimensionless()) {
                error = wanted == Base::Unit::One
                    ? tr("A Number has no unit, and %1 has one.").arg(text)
                    : tr("%1 has the wrong unit for this type.").arg(text);
                return false;
            }
        }
        catch (const Base::Exception&) {
            // not a plain value: an expression, checked once it is set
        }
    }

    // One transaction for the whole add, the "Variables" VarSet included. A transaction already
    // booked (a task dialog's) takes it instead, and what was made is taken back on a failure.
    // FreeCAD-CH (ops#640, D-1): a dialog's booking, which the add joins when tid is 0 (0 also
    // comes when the document's transactions are locked or busy, and there is nothing to redo).
    const bool booked = doc->getBookedTransactionID() != 0;
    int tid = Gui::PropertyEditor::openPropertyTransaction(doc, ("Add " + varName).c_str());
    bool created = false;
    bool added = false;
    auto fail = [&](const QString& message) {
        if (tid != 0) {
            Gui::PropertyEditor::closePropertyTransaction(tid, false);
        }
        else {
            try {
                if (created) {
                    Gui::Command::runCommand(
                        Gui::Command::Doc,
                        ("App.getDocument('" + docName + "').removeObject('"
                         + target->getNameInDocument() + "')")
                            .c_str()
                    );
                }
                else if (added) {
                    Gui::Command::runCommand(
                        Gui::Command::Doc,
                        (pyObject(target) + ".removeProperty(" + pyString(varName) + ")").c_str()
                    );
                }
            }
            catch (const Base::Exception& e) {
                e.reportException();
            }
        }
        error = message;
        return false;
    };
    try {
        if (!target) {
            // The name addObject gives it: "Variables001" if another object is named "Variables".
            // Not the document's last object: an observer may add one as it is made.
            std::string varSetName = doc->getUniqueObjectName("Variables");
            Gui::Command::runCommand(
                Gui::Command::Doc,
                ("App.getDocument('" + docName + "').addObject('App::VarSet', 'Variables')").c_str()
            );
            target = doc->getObject(varSetName.c_str());
            if (!target || !target->isDerivedFrom<App::VarSet>()) {
                target = nullptr;
                return fail(tr("The \"Variables\" set could not be made."));
            }
            created = true;
            // Its own properties (Label) count now.
            reason = App::VariableLookup::checkVariableName(target, varName);
            if (!reason.empty()) {
                return fail(QString::fromStdString(reason));
            }
        }
        Gui::Command::runCommand(
            Gui::Command::Doc,
            (pyObject(target) + ".addProperty('" + typeName + "', " + pyString(varName)
             + ", 'Base', " + pyString(description.trimmed().toStdString()) + ")")
                .c_str()
        );
        added = true;
        App::Property* prop = target->getPropertyByName(varName.c_str());
        if (!prop) {
            return fail(tr("The variable '%1' could not be made.").arg(name));
        }
        if (!text.isEmpty()) {
            std::vector<std::string> commands;
            bool isExpression = false;
            QString message;
            if (!VariablesModel::editCommands(
                    target,
                    prop,
                    {},
                    varName,
                    text,
                    commands,
                    message,
                    &isExpression
                )) {
                return fail(message);
            }
            for (const auto& command : commands) {
                Gui::Command::runCommand(Gui::Command::Doc, command.c_str());
            }
            if (isExpression) {
                QString mismatch = VariablesModel::unitMismatch(target, prop);
                if (!mismatch.isEmpty()) {
                    return fail(mismatch);
                }
            }
        }
        if (!clashChoice.empty()) {
            // Recorded on the copies that define the name, in this add's undo step.
            const std::string path = clashChoice == "local"
                ? App::VariableRef {target, varName}.path()
                : clashChoice;
            Gui::Command::runCommand(
                Gui::Command::Doc,
                ("__import__('freecad.variables.copies', fromlist=['choose']).choose(App.getDocument('"
                 + docName + "'), " + pyString(varName) + ", " + pyString(path) + ")")
                    .c_str()
            );
        }
    }
    catch (const Base::Exception& e) {
        return fail(QString::fromUtf8(e.what()));
    }
    catch (...) {
        // Not left open or booked: the next edit would join it, with a half-made VarSet.
        fail({});
        throw;
    }
    recomputeAfterEdit(doc);
    Gui::PropertyEditor::closePropertyTransaction(tid);
    if (tid == 0 && booked) {
        // FreeCAD-CH (ops#640, D-1): joined a dialog's booking; made again if that is cancelled.
        pendingVariables().push_back(
            {docName, holderName, name, typeName, text, description, clashChoice}
        );
    }
    return true;
}

void VariablesView::addOtherVariable(App::DocumentObject* target)
{
    App::Document* doc = currentDocument();
    if (!doc) {
        return;
    }
    if (target && !isEditableSet(target)) {
        showMessage(
            tr("'%1' is a copy of its source: its variables can't be changed here.")
                .arg(QString::fromUtf8(target->Label.getValue())),
            true
        );
        return;
    }
    bool created = false;
    int createdID = 0;  // the "Add variable" undo step, when the panel made one
    if (!target) {
        // Its own committed step: the dialog aborts and reopens its "Add property" transaction
        // as the name or the type is typed, which must not take the VarSet with it.
        int booked = doc->getBookedTransactionID();
        bool own = booked == 0 || Gui::PropertyEditor::isEditorBooking(booked);
        QString error;
        std::string command = std::string("App.getDocument('") + doc->getName()
            + "').addObject('App::VarSet', 'Variables')";
        // The name addObject gives it: "Variables001" if another object is named "Variables".
        // Not the document's last object: an observer may add one as it is made.
        std::string varSetName = doc->getUniqueObjectName("Variables");
        if (!runEdit(doc, "Add variable", {command}, error)) {
            showMessage(error, true);
            return;
        }
        if (own) {
            createdID = doc->getTransactionID(true, 0);
        }
        target = doc->getObject(varSetName.c_str());
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

void VariablesView::editDescription()
{
    QModelIndex current = tree->currentIndex();
    App::DocumentObject* obj = VariablesModel::holder(current);
    if (!obj || VariablesModel::kind(current) != VariablesModel::VarSetKind
        || VariablesModel::isReadOnly(current)) {
        return;
    }
    // Everything is read from the row before the dialog: the panel may rebuild while it is open,
    // which frees the row.
    std::string docName = obj->getDocument()->getName();
    std::string holderName = obj->getNameInDocument();
    QString qName = current.data(VariablesModel::VariableRole).toString();
    QString text = current.sibling(current.row(), VariablesModel::DescriptionColumn)
                       .data(VariablesModel::EditTextRole)
                       .toString();

    // On the heap, guarded: the panel, and its child dialog with it, may be deleted during exec().
    QPointer<VariablesView> self(this);
    QPointer<QInputDialog> dialog = new QInputDialog(this);
    dialog->setObjectName(QStringLiteral("descriptionDialog"));
    dialog->setWindowTitle(tr("Describe %1").arg(qName));
    dialog->setLabelText(tr("Description of %1:").arg(qName));
    dialog->setOption(QInputDialog::UsePlainTextEditForTextInput);
    dialog->setTextValue(text);
    int result = dialog->exec();
    if (!self || !dialog) {
        return;
    }
    QString value = dialog->textValue();
    delete dialog;
    if (result != QDialog::Accepted) {
        return;
    }
    // Looked up again: the document may have changed while the dialog was open.
    App::Document* doc = App::GetApplication().getDocument(docName.c_str());
    obj = doc ? doc->getObject(holderName.c_str()) : nullptr;
    QString error;
    if (!VariablesModel::describe(obj, qName.toStdString(), value, error)) {
        showMessage(error, true);
        return;
    }
    showMessage(QString(), false);
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
    if (!obj || VariablesModel::kind(current) == VariablesModel::HeaderKind
        || VariablesModel::kind(current) == VariablesModel::NewKind
        || VariablesModel::isReadOnly(current)) {
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
        // FreeCAD-CH (ops#640, measured variables 2): a measured variable goes with its
        // measurement, and with its own set when it was that set's only variable.
        App::DocumentObject* measurement = measurementOf(obj, VariablesModel::property(current));
        const bool lastOfHolder = measurement && isMeasuredHolder(obj)
            && obj->getDynamicPropertyNames().size() == 1;
        commands.push_back(pyObject(obj) + ".removeProperty(" + pyString(name) + ")");
        std::vector<std::string> removals;  // after the touches below
        if (measurement) {
            removals.push_back(
                "App.getDocument(" + pyString(docName) + ").removeObject("
                + pyString(measurement->getNameInDocument()) + ")"
            );
        }
        if (lastOfHolder) {
            removals.push_back(
                "App.getDocument(" + pyString(docName) + ").removeObject(" + pyString(holderName)
                + ")"
            );
        }
        // Its users, the VarSet itself included, fail at the edit's recompute (D4, ops#599): touch
        // them, as nothing else would.
        std::set<const App::DocumentObject*> users;
        if (App::Property* prop = VariablesModel::property(current)) {
            for (const auto& use : App::VariableLookup::uses(prop)) {
                if (use.user && use.user->isAttachedToDocument()
                    && !(lastOfHolder && use.user == obj) && users.insert(use.user).second) {
                    commands.push_back(pyObject(use.user) + ".touch()");
                }
            }
        }
        commands.insert(commands.end(), removals.begin(), removals.end());
    }
    if (count > 0) {
        QMessageBox box(
            QMessageBox::Warning,
            tr("Delete variable"),
            tr("%n expression(s) use #%1. They will fail.\n\n%2\n\n"
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

void VariablesView::importVariables()
{
    // ops#317 PR G1: freecad.variables.importgui asks for the files, then shows its dialog (not
    // waited for). A document's internal name is an identifier, safe in the string.
    App::Document* doc = currentDocument();
    if (!doc) {
        return;
    }
    std::string code = "from freecad.variables import importgui\n"
                       "importgui.run(FreeCAD.getDocument(\""
        + std::string(doc->getName()) + "\"))\n";
    try {
        Base::Interpreter().runString(code.c_str());
    }
    catch (const Base::Exception& e) {
        showMessage(QString::fromUtf8(e.what()), true);
    }
}

void VariablesView::showUses()
{
    QModelIndex current = tree->currentIndex();
    if (VariablesModel::kind(current) == VariablesModel::HeaderKind
        || VariablesModel::kind(current) == VariablesModel::NewKind) {
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
