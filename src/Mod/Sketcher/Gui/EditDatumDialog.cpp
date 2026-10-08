// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Werner Mayer <wmayer[at]users.sourceforge.net>     *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/


/// Qt Include Files
#include <Inventor/sensors/SoSensor.h>
#include <QApplication>
#include <QDialog>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLineEdit>
#include <functional>


#include <Base/Tools.h>
#include <Gui/Application.h>
#include <App/Expression.h>
#include <App/ExpressionParser.h>
#include <Gui/CommandT.h>
#include <Gui/Document.h>
#include <Gui/MainWindow.h>
#include <Gui/Notifications.h>
#include <Gui/PrefWidgets.h>
#include <Gui/QuantitySpinBox.h>
#include <Gui/View3DInventor.h>
#include <Gui/View3DInventorViewer.h>
#include <Gui/Document.h>
#include <Mod/Sketcher/App/GeometryFacade.h>
#include <Mod/Sketcher/App/SketchObject.h>
#include <App/Datums.h>

#include "EditDatumDialog.h"
#include "CommandSketcherTools.h"
#include "Utils.h"
#include "ViewProviderSketch.h"
#include "SketcherSettings.h"
#include "ui_InsertDatum.h"

#include <Precision.hxx>
#include <cmath>
#include <numeric>


using namespace SketcherGui;

/* TRANSLATOR SketcherGui::EditDatumDialog */

bool SketcherGui::checkConstraintName(const Sketcher::SketchObject* sketch, std::string constraintName)
{
    if (!constraintName.empty() && constraintName != Base::Tools::getIdentifier(constraintName)) {
        Gui::NotifyUserError(
            sketch,
            QT_TRANSLATE_NOOP("Notifications", "Value Error"),
            QT_TRANSLATE_NOOP(
                "Notifications",
                "Invalid constraint name (must only contain alphanumericals and "
                "underscores, and must not start with digit)"
            )
        );
        return false;
    }

    return true;
}


namespace
{

/// The popup of EditDatumDialog::execInPlace. A click outside closes a popup through reject():
/// that applies valid input, or keeps the current value. Esc doesn't come here (eventFilter).
class DatumInPlacePopup: public QDialog
{
public:
    DatumInPlacePopup(QWidget* parent, std::function<bool()> apply)
        : QDialog(parent, Qt::Popup | Qt::FramelessWindowHint)
        , apply(std::move(apply))
    {}

    void reject() override
    {
        done(apply() ? EditDatumDialog::InPlaceApplied : EditDatumDialog::InPlaceKept);
    }

private:
    std::function<bool()> apply;
};

/// Whether an expression refers to a property, e.g. a spreadsheet alias, rather than being a
/// plain value like "10+5" or "2*3 in".
bool refersToProperty(const App::Expression* expr)
{
    return expr && !expr->getIdentifiers().empty();
}

/// Places a widget centred on a point, inside a rectangle.
void placeCentred(QWidget* widget, const QPoint& centre, const QRect& area)
{
    QSize size = widget->size();
    int x = centre.x() - size.width() / 2;
    int y = centre.y() - size.height() / 2;
    x = std::max(area.left(), std::min(x, area.right() - size.width()));
    y = std::max(area.top(), std::min(y, area.bottom() - size.height()));
    widget->move(x, y);
}

void finishDatumTransaction(Sketcher::SketchObject* sketch, int transactionID)
{
    Gui::Command::commitCommand(transactionID);

    // As in EditDatumDialog::accepted: see the work-around noted there.
    sketch->ExpressionEngine.execute();
    sketch->solve();
    tryAutoRecompute(sketch);
}

}  // namespace

void SketcherGui::askDatumValues(
    Sketcher::SketchObject* sketch,
    const std::vector<int>& constrIds,
    int transactionID,
    DatumRequest request
)
{
    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Sketcher"
    );
    bool newConstraints = request == DatumRequest::NewConstraints;
    bool show = !newConstraints || hGrp->GetBool("ShowDialogOnDistanceConstraint", true);
    bool inPlace = hGrp->GetBool("DimensionValueInPlace", true);

    std::vector<int> ids;
    const std::vector<Sketcher::Constraint*>& constraints = sketch->Constraints.getValues();
    for (int id : constrIds) {
        if (id >= 0 && id < static_cast<int>(constraints.size())
            && constraints[id]->isDimensional() && constraints[id]->isDriving) {
            ids.push_back(id);
        }
    }

    auto closeUnchanged = [&]() {
        // New constraints stay as placed; an existing one is unchanged.
        if (newConstraints) {
            Gui::Command::commitCommand(transactionID);
        }
        else {
            Gui::Command::abortCommand(transactionID);
        }
    };

    if (!show || ids.empty()) {
        closeUnchanged();
        return;
    }

    if (sketch->hasConflicts()) {
        Gui::TranslatedUserWarning(
            sketch,
            QObject::tr("Dimensional constraint"),
            QObject::tr(
                "Not allowed to edit the datum because the "
                "sketch contains conflicting constraints"
            )
        );
        closeUnchanged();
        return;
    }

    if (!inPlace) {
        for (int id : ids) {
            EditDatumDialog dialog(transactionID, sketch, id);
            dialog.setCommitOnAccept(false);
            if (dialog.exec() != QDialog::Accepted || !dialog.isSuccess()) {
                // Cancel and a failed value have aborted already, as the dialog always did.
                Gui::Command::abortCommand(transactionID);
                return;
            }
        }
        finishDatumTransaction(sketch, transactionID);
        return;
    }

    bool kept = false;
    std::size_t current = 0;
    while (current < ids.size()) {
        EditDatumDialog field(transactionID, sketch, ids[current]);
        int result = field.execInPlace(current + 1 < ids.size(), current > 0);
        if (result == EditDatumDialog::InPlaceNext) {
            ++current;
        }
        else if (result == EditDatumDialog::InPlacePrevious) {
            --current;
        }
        else {
            kept = result == EditDatumDialog::InPlaceKept;
            break;
        }
    }

    if (kept && !newConstraints) {
        Gui::Command::abortCommand(transactionID);
        return;
    }
    finishDatumTransaction(sketch, transactionID);
}

EditDatumDialog::EditDatumDialog(int tid, ViewProviderSketch* vp, int ConstrNbr)
    : ConstrNbr(ConstrNbr)
    , success(false)
    , transactionID(tid)
{
    sketch = vp->getSketchObject();
    const std::vector<Sketcher::Constraint*>& Constraints = sketch->Constraints.getValues();
    Constr = Constraints[ConstrNbr];
}

EditDatumDialog::EditDatumDialog(int tid, Sketcher::SketchObject* pcSketch, int ConstrNbr)
    : sketch(pcSketch)
    , ConstrNbr(ConstrNbr)
    , success(false)
    , transactionID(tid)
{
    const std::vector<Sketcher::Constraint*>& Constraints = sketch->Constraints.getValues();
    Constr = Constraints[ConstrNbr];
}

EditDatumDialog::~EditDatumDialog()
{}

void EditDatumDialog::setCommitOnAccept(bool commit)
{
    commitOnAccept = commit;
}

void EditDatumDialog::setupValueEdit(QString& title, QString& label)
{
    Base::Quantity init_val;
    double datum = Constr->getValue();

    valueEdit->setEntryName(QByteArray("DatumValue"));
    if (Constr->Type == Sketcher::Angle) {
        datum = Base::toDegrees<double>(datum);
        title = tr("Insert Angle");
        init_val.setUnit(Base::Unit::Angle);
        label = tr("Angle");
        valueEdit->setParamGrpPath(QByteArray("User parameter:BaseApp/History/SketcherAngle"));
    }
    else if (Constr->Type == Sketcher::Radius) {
        title = tr("Insert Radius");
        init_val.setUnit(Base::Unit::Length);
        label = tr("Radius");
        valueEdit->setParamGrpPath(QByteArray("User parameter:BaseApp/History/SketcherLength"));
    }
    else if (Constr->Type == Sketcher::Diameter) {
        title = tr("Insert Diameter");
        init_val.setUnit(Base::Unit::Length);
        label = tr("Diameter");
        valueEdit->setParamGrpPath(QByteArray("User parameter:BaseApp/History/SketcherLength"));
    }
    else if (Constr->Type == Sketcher::Weight) {
        title = tr("Insert Weight");
        label = tr("Weight");
        valueEdit->setParamGrpPath(QByteArray("User parameter:BaseApp/History/SketcherWeight"));
    }
    else if (Constr->Type == Sketcher::SnellsLaw) {
        title = tr("Refractive Index Ratio", "Constraint_SnellsLaw");
        label = tr("Ratio n2/n1:", "Constraint_SnellsLaw");
        valueEdit->setParamGrpPath(
            QByteArray("User parameter:BaseApp/History/SketcherRefrIndexRatio")
        );
        valueEdit->setSingleStep(0.05);
    }
    else {
        title = tr("Insert Length");
        init_val.setUnit(Base::Unit::Length);
        label = tr("Length");
        valueEdit->setParamGrpPath(QByteArray("User parameter:BaseApp/History/SketcherLength"));
    }

    init_val.setValue(datum);

    valueEdit->setValue(init_val);
    valueEdit->pushToHistory();
    valueEdit->selectNumber();
    valueEdit->bind(sketch->Constraints.createPath(ConstrNbr));
}

int EditDatumDialog::exec(bool atCursor)
{
    // Return if constraint doesn't have editable value
    if (Constr->isDimensional()) {

        if (sketch->hasConflicts()) {
            Gui::TranslatedUserWarning(
                sketch,
                QObject::tr("Dimensional constraint"),
                QObject::tr(
                    "Not allowed to edit the datum because the "
                    "sketch contains conflicting constraints"
                )
            );
            // Close the caller's transaction: nothing has changed.
            Gui::Command::abortCommand(transactionID);
            return QDialog::Rejected;
        }

        QDialog dlg(Gui::getMainWindow());
        if (!ui_ins_datum) {
            ui_ins_datum.reset(new Ui_InsertDatum);
            ui_ins_datum->setupUi(&dlg);
        }
        valueEdit = ui_ins_datum->labelEdit;

        bool showRadiusDiameterBtns = Constr->Type == Sketcher::Radius
            || Constr->Type == Sketcher::Diameter;
        ui_ins_datum->rbRadius->setVisible(showRadiusDiameterBtns);
        ui_ins_datum->rbDiameter->setVisible(showRadiusDiameterBtns);
        if (Constr->Type == Sketcher::Radius) {
            ui_ins_datum->rbRadius->setChecked(true);
        }
        else if (Constr->Type == Sketcher::Diameter) {
            ui_ins_datum->rbDiameter->setChecked(true);
        }

        QString title;
        QString label;
        setupValueEdit(title, label);
        dlg.setWindowTitle(title);
        ui_ins_datum->label->setText(label);
        ui_ins_datum->name->setText(QString::fromStdString(Constr->Name));

        ui_ins_datum->cbDriving->setChecked(!Constr->isDriving);

        connect(ui_ins_datum->cbDriving, &QCheckBox::toggled, this, &EditDatumDialog::drivingToggled);
        connect(
            ui_ins_datum->labelEdit,
            qOverload<const Base::Quantity&>(&Gui::QuantitySpinBox::valueChanged),
            this,
            &EditDatumDialog::datumChanged
        );
        connect(
            ui_ins_datum->labelEdit,
            &Gui::QuantitySpinBox::showFormulaDialog,
            this,
            &EditDatumDialog::formEditorOpened
        );
        connect(ui_ins_datum->rbRadius, &QRadioButton::toggled, this, &EditDatumDialog::typeChanged);
        connect(&dlg, &QDialog::accepted, this, &EditDatumDialog::accepted);
        connect(&dlg, &QDialog::rejected, this, &EditDatumDialog::rejected);

        if (atCursor) {
            dlg.show();  // Need to show the dialog so geometry is computed
            QRect pg = dlg.parentWidget()->geometry();
            int Xmin = pg.x() + 10;
            int Ymin = pg.y() + 10;
            int Xmax = pg.x() + pg.width() - dlg.geometry().width() - 10;
            int Ymax = pg.y() + pg.height() - dlg.geometry().height() - 10;
            int x = Xmax < Xmin ? (Xmin + Xmax) / 2
                                : std::min(std::max(QCursor::pos().x(), Xmin), Xmax);
            int y = Ymax < Ymin ? (Ymin + Ymax) / 2
                                : std::min(std::max(QCursor::pos().y(), Ymin), Ymax);
            dlg.setGeometry(x, y, dlg.geometry().width(), dlg.geometry().height());
        }

        return dlg.exec();
    }

    return QDialog::Rejected;
}

int EditDatumDialog::execInPlace(bool hasNext, bool hasPrevious)
{
    if (!Constr->isDimensional()) {
        return InPlaceKept;
    }

    DatumInPlacePopup popup(Gui::getMainWindow(), [this]() { return applyInPlace(); });
    popup.setObjectName(QStringLiteral("SketcherDatumInPlace"));
    popup.setAttribute(Qt::WA_NoMouseReplay);  // the click that closes it does nothing else

    auto* layout = new QHBoxLayout(&popup);
    layout->setContentsMargins(0, 0, 0, 0);
    auto* box = new Gui::PrefQuantitySpinBox(&popup);
    box->setObjectName(QStringLiteral("SketcherDatumInPlaceValue"));
    box->setButtonSymbols(QAbstractSpinBox::NoButtons);
    box->setFrame(false);
    layout->addWidget(box);
    valueEdit = box;

    QString title;
    QString label;
    setupValueEdit(title, label);
    box->setToolTip(label);

    QFontMetrics metrics(box->font());
    box->setMinimumWidth(std::max(80, metrics.horizontalAdvance(box->text()) + 24));
    popup.adjustSize();

    inPlacePopup = &popup;
    inPlaceEscapePressed = false;
    inPlaceHasNext = hasNext;
    inPlaceHasPrevious = hasPrevious;
    box->installEventFilter(this);
    if (auto* edit = box->findChild<QLineEdit*>()) {
        edit->installEventFilter(this);
    }

    QPoint centre;
    QRect area;
    auto* vp = freecad_cast<ViewProviderSketch*>(
        Gui::Application::Instance->getViewProvider(sketch)
    );
    if (!vp || !vp->getConstraintLabelScreenPos(ConstrNbr, centre, area)) {
        // The label isn't drawn: at the cursor, inside the main window, as the dialog does.
        centre = QCursor::pos();
        area = Gui::getMainWindow()->geometry();
    }
    placeCentred(&popup, centre, area);

    popup.show();
    box->setFocus();
    box->selectNumber();
    int result = popup.exec();

    inPlacePopup = nullptr;
    valueEdit = nullptr;
    return result;
}

bool EditDatumDialog::eventFilter(QObject* watched, QEvent* event)
{
    if (!inPlacePopup
        || (event->type() != QEvent::KeyPress && event->type() != QEvent::KeyRelease
            && event->type() != QEvent::ShortcutOverride)) {
        return QObject::eventFilter(watched, event);
    }

    auto* keyEvent = static_cast<QKeyEvent*>(event);
    int key = keyEvent->key();
    if (event->type() == QEvent::KeyRelease) {
        // Esc closes the field on its release: closed on the press, the field would leave the
        // release to the 3D view, where the sketch's tools quit on it (the Dimension tool in
        // continuous mode too).
        if (key == Qt::Key_Escape && inPlaceEscapePressed && !keyEvent->isAutoRepeat()) {
            inPlacePopup->done(InPlaceKept);
            return true;
        }
        return QObject::eventFilter(watched, event);
    }
    bool fieldKey = key == Qt::Key_Return || key == Qt::Key_Enter || key == Qt::Key_Tab
        || key == Qt::Key_Backtab || key == Qt::Key_Escape;
    if (!fieldKey) {
        return QObject::eventFilter(watched, event);
    }
    if (event->type() == QEvent::ShortcutOverride) {
        // These keys belong to the field, not to the Sketcher's shortcuts.
        event->accept();
        return true;
    }

    QDialog* popup = inPlacePopup;
    if (key == Qt::Key_Escape) {
        inPlaceEscapePressed = true;
    }
    else if (key == Qt::Key_Backtab) {
        if (inPlaceHasPrevious && applyInPlace()) {
            popup->done(InPlacePrevious);
        }
    }
    else if (applyInPlace()) {
        popup->done(key == Qt::Key_Tab && inPlaceHasNext ? InPlaceNext : InPlaceApplied);
    }
    return true;
}

bool EditDatumDialog::applyInPlace()
{
    if (!valueEdit) {
        return false;
    }

    try {
        applyValue();
        valueEdit->setStyleSheet(QString());
        return true;
    }
    catch (const Base::Exception& e) {
        if (sketch->noRecomputes) {  // as in accepted(): the solver's information may be stale
            sketch->solve();
        }
        valueEdit->setStyleSheet(QStringLiteral("color: red;"));
        valueEdit->setToolTip(QString::fromUtf8(e.what()));
        return false;
    }
}

void EditDatumDialog::applyValue()
{
    // setDatum replaces the constraint objects (PropertyConstraintList::applyValues deletes the
    // old ones), also when it fails and the field stays open for another try: read it afresh.
    Constr = sketch->Constraints.getValues()[ConstrNbr];

    if (valueEdit->hasExpression()) {
        // A formula from the formula editor ('=').
        valueEdit->apply();
        return;
    }

    QString text = valueEdit->text().trimmed();
    std::shared_ptr<App::Expression> expr;
    try {
        expr = App::ExpressionParser::parse(sketch, text.toUtf8().constData());
    }
    catch (const Base::Exception&) {
        // Not an expression as it stands, e.g. a value in the user's locale: the field reads it.
    }

    if (refersToProperty(expr.get())) {
        // A spreadsheet alias or another property: link to it. Its value goes through setDatum
        // first, which refuses values the constraint can't take.
        App::ExpressionPtr result = expr->eval();
        auto* number = freecad_cast<App::NumberExpression*>(result.get());
        if (!number) {
            throw Base::ValueError("The expression doesn't give a number");
        }
        Base::Quantity quantity = number->getQuantity();
        if (Constr->Type == Sketcher::Angle && quantity.isDimensionless()) {
            quantity.setUnit(Base::Unit::Angle);  // degrees, as the expression engine reads it
        }
        auto unitString = Base::Tools::escapeQuotesFromString(quantity.getUnit().getString());
        const double oldDatum = Constr->getValue();
        Gui::cmdAppObjectArgs(
            sketch,
            "setDatum(%i,App.Units.Quantity('%.12g %s'))",
            ConstrNbr,
            quantity.getValue(),
            unitString
        );

        std::string exprString = Base::Tools::escapedUnicodeFromUtf8(expr->toString().c_str());
        exprString = Base::Tools::escapeQuotesFromString(exprString);
        try {
            Gui::cmdAppObjectArgs(
                sketch,
                "setExpression('%s', u'%s')",
                sketch->Constraints.createPath(ConstrNbr).toEscapedString(),
                exprString
            );
        }
        catch (const Base::Exception&) {
            // No link (e.g. a cyclic one): put the value back, so that Esc keeps the old one.
            sketch->setDatum(ConstrNbr, oldDatum);
            throw;
        }
        return;
    }

    if (!valueEdit->hasValidInput()) {
        throw Base::ValueError("Invalid value");
    }

    Base::Quantity newQuant = valueEdit->value();
    if (Constr->Type != Sketcher::SnellsLaw && Constr->Type != Sketcher::Weight
        && newQuant.isDimensionless()) {
        throw Base::ValueError("Invalid value");
    }

    valueEdit->pushToHistory();
    double newDatum = newQuant.getValue();
    auto unitString = Base::Tools::escapeQuotesFromString(newQuant.getUnit().getString());

    performAutoScale(newDatum);

    Gui::cmdAppObjectArgs(
        sketch,
        "setDatum(%i,App.Units.Quantity('%.8g %s'))",
        ConstrNbr,
        newDatum,
        unitString
    );
}

void EditDatumDialog::typeChanged(bool checked)
{
    Q_UNUSED(checked);
    if (!ui_ins_datum->rbRadius->isVisible()) {
        return;
    }

    // Updates UI labels based on selection, but does NOT change value yet
    QWidget* dlg = ui_ins_datum->labelEdit->parentWidget();
    while (dlg && !dlg->isWindow()) {
        dlg = dlg->parentWidget();
    }
    if (ui_ins_datum->rbRadius->isChecked()) {
        ui_ins_datum->label->setText(tr("Radius"));
        if (dlg) {
            dlg->setWindowTitle(tr("Insert Radius"));
        }
    }
    else {
        ui_ins_datum->label->setText(tr("Diameter"));
        if (dlg) {
            dlg->setWindowTitle(tr("Insert Diameter"));
        }
    }
}

void EditDatumDialog::accepted()
{
    // Toggling Reference while the dialog was open (also by typing a value: datumChanged) went
    // through setDriving, which replaces the constraint objects: read it afresh (ops#172).
    Constr = sketch->Constraints.getValues()[ConstrNbr];

    // Check if we need to swap Radius <-> Diameter
    if (Constr->Type == Sketcher::Radius && ui_ins_datum->rbDiameter->isChecked()) {
        Constr->Type = Sketcher::Diameter;
    }
    else if (Constr->Type == Sketcher::Diameter && ui_ins_datum->rbRadius->isChecked()) {
        Constr->Type = Sketcher::Radius;
    }

    Base::Quantity newQuant = ui_ins_datum->labelEdit->value();
    if (Constr->Type == Sketcher::SnellsLaw || Constr->Type == Sketcher::Weight
        || !newQuant.isDimensionless()) {

        // save the value for the history
        ui_ins_datum->labelEdit->pushToHistory();

        double newDatum = newQuant.getValue();

        try {

            /*if (ui_ins_datum->cbDriving->isChecked() == Constr->isDriving) {
                Gui::cmdAppObjectArgs(sketch, "toggleDriving(%i)", ConstrNbr);
            }*/

            if (!ui_ins_datum->cbDriving->isChecked()) {
                if (ui_ins_datum->labelEdit->hasExpression()) {
                    ui_ins_datum->labelEdit->apply();
                }
                else {
                    auto unitString = newQuant.getUnit().getString();
                    unitString = Base::Tools::escapeQuotesFromString(unitString);

                    performAutoScale(newDatum);

                    Gui::cmdAppObjectArgs(
                        sketch,
                        "setDatum(%i,App.Units.Quantity('%.8g %s'))",
                        ConstrNbr,
                        newDatum,
                        unitString
                    );
                }
            }

            std::string constraintName = ui_ins_datum->name->text().trimmed().toStdString();
            std::string currConstraintName = sketch->Constraints[ConstrNbr]->Name;

            if (constraintName != currConstraintName
                && SketcherGui::checkConstraintName(sketch, constraintName)) {
                Gui::cmdAppObjectArgs(
                    sketch,
                    "renameConstraint(%d, u'%s')",
                    ConstrNbr,
                    constraintName.c_str()
                );
            }

            if (!commitOnAccept) {
                // The caller commits once for all its constraints (askDatumValues).
                success = true;
                return;
            }

            Gui::Command::commitCommand(transactionID);

            // THIS IS A WORK-AROUND NOT TO DELAY 0.19 RELEASE
            //
            // depsAreTouched is not returning true in this case:
            //  https://forum.freecad.org/viewtopic.php?f=3&t=55633&p=481061#p478477
            //
            // It appears related to a drastic change in how dependencies are calculated, see:
            //  https://forum.freecad.org/viewtopic.php?f=3&t=55633&p=481061#p481061
            //
            // This is NOT the solution, as there is no point in systematically executing the
            // ExpressionEngine on every dimensional constraint change. Just a quick fix to avoid
            // clearly unwanted behaviour in absence of time to actually fix the root cause.

            // if (sketch->noRecomputes && sketch->ExpressionEngine.depsAreTouched()) {
            sketch->ExpressionEngine.execute();
            sketch->solve();
            //}

            tryAutoRecompute(sketch);
            success = true;
        }
        catch (const Base::Exception& e) {
            Gui::NotifyUserError(sketch, QT_TRANSLATE_NOOP("Notifications", "Value Error"), e.what());

            Gui::Command::abortCommand(transactionID);

            if (sketch->noRecomputes) {  // if setdatum failed, it is highly likely that solver
                                         // information is invalid.
                sketch->solve();
            }
        }
    }
}

void EditDatumDialog::rejected()
{
    Gui::Command::abortCommand(transactionID);
    sketch->recomputeFeature();
}

bool EditDatumDialog::isSuccess()
{
    return success;
}

void EditDatumDialog::drivingToggled(bool state)
{
    if (state) {
        ui_ins_datum->labelEdit->setToLastUsedValue();
    }
    sketch->setDriving(ConstrNbr, !state);
    if (!sketch->noRecomputes) {  // if noRecomputes, solve() is already done by setDriving()
        sketch->solve();
    }
}

void EditDatumDialog::datumChanged()
{
    if (ui_ins_datum->labelEdit->text() != std::as_const(ui_ins_datum->labelEdit)->getHistory()[0]) {
        ui_ins_datum->cbDriving->setChecked(false);
    }
}

void EditDatumDialog::formEditorOpened(bool state)
{
    if (state) {
        ui_ins_datum->cbDriving->setChecked(false);
    }
}


// This function checks an object's visible flag recursively in a Gui::Document
// assuming that lastParent (if provided) is visible
bool isVisibleUpTo(App::DocumentObject* obj, Gui::Document* doc, App::DocumentObject* lastParent)
{
    while (obj && obj != lastParent) {
        auto parentviewprovider = doc->getViewProvider(obj);

        if (!parentviewprovider || !parentviewprovider->isVisible()) {
            return false;
        }
        obj = obj->getFirstParent();
    }
    return true;
}
bool hasVisualFeature(App::DocumentObject* obj, App::DocumentObject* rootObj, Gui::Document* doc)
{
    auto docObjects = doc->getDocument()->getObjects();
    for (auto object : docObjects) {

        // Presumably, the sketch that is being edited has visual features, but
        // that's not interesting
        if (object == obj) {
            continue;
        }

        // No need to continue analysis if the object's visible flag is down
        bool visible = isVisibleUpTo(object, doc, rootObj);
        if (!visible) {
            continue;
        }

        App::DocumentObject* link = object->getLinkedObject();
        if (link->getDocument() != doc->getDocument()) {
            Gui::Document* linkDoc = Gui::Application::Instance->getDocument(link->getDocument());
            if (linkDoc && hasVisualFeature(link, link, linkDoc)) {
                return true;
            }
            continue;
        }

        // Skip objects that are not of geometric nature
        if (!object->isDerivedFrom<App::GeoFeature>()) {
            continue;
        }

        // Skip datum objects
        if (object->isDerivedFrom<App::DatumElement>()) {
            continue;
        }

        // Skip container objects because getting their bounging box might
        // return a valid bounding box around annotations or datums
        if (object->hasExtension(App::GeoFeatureGroupExtension::getExtensionClassTypeId())) {
            continue;
        }

        // Get the bounding box of the object
        auto viewProvider = doc->getViewProvider(object);
        if (viewProvider && viewProvider->getBoundingBox().IsValid()) {
            return true;
        }
    }
    return false;
}

void EditDatumDialog::performAutoScale(double newDatum)
{
    const std::vector<Sketcher::Constraint*>& constraints = sketch->Constraints.getValues();
    for (auto* constr : constraints) {
        if (constr->Type == Sketcher::Group || constr->Type == Sketcher::Text) {
            // Do not attempt to scale if there's a group
            return;
        }
    }

    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Sketcher/dimensioning"
    );
    long autoScaleMode = hGrp->GetInt(
        "AutoScaleMode",
        static_cast<int>(SketcherGui::AutoScaleMode::WhenNoScaleFeatureIsVisible)
    );

    // There is a single constraint in the sketch so it can
    // be used as a reference to scale the geometries around the origin
    // if there are external geometries, it is safe to assume that the sketch
    // was drawn with these geometries as scale references (use <= 2 because
    // the sketch axis are considered as external geometries)
    // if the sketch has blocked geometries, it is considered a scale indicator
    // and autoscale is not performed either
    if ((autoScaleMode == static_cast<int>(SketcherGui::AutoScaleMode::Always)
         || (autoScaleMode == static_cast<int>(SketcherGui::AutoScaleMode::WhenNoScaleFeatureIsVisible)
             && !hasVisualFeature(sketch, nullptr, Gui::Application::Instance->activeDocument())))
        && sketch->getExternalGeometryCount() <= 2 && !sketch->hasBlockConstraint()) {
        try {
            // Handle the case where multiple datum constraints are present but only one is scale
            // defining e.g. a bunch of angle constraints and a single length constraint
            int scaleDefiningConstraint = sketch->getSingleScaleDefiningConstraint();
            if (scaleDefiningConstraint != ConstrNbr) {
                return;
            }

            double oldDatum = sketch->getDatum(ConstrNbr);
            if (!std::isfinite(newDatum) || !std::isfinite(oldDatum)
                || std::abs(oldDatum) <= Precision::Confusion()) {
                return;
            }

            double scaleFactor = newDatum / oldDatum;
            if (!std::isfinite(scaleFactor) || scaleFactor <= Precision::Confusion()
                || std::abs(scaleFactor - 1.0) <= Precision::Confusion()) {
                return;
            }
            centerScale(scaleFactor);

            // Some constraints cannot be scaled so the actual datum constraint
            // might change index
            ConstrNbr = sketch->getSingleScaleDefiningConstraint();
        }
        catch (const Base::Exception& e) {
            Base::Console().error("Exception performing autoscale: %s\n", e.what());
        }
    }
}

#include "moc_EditDatumDialog.cpp"
