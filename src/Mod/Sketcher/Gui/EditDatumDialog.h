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

#pragma once

#include <QObject>
#include <memory>
#include <vector>

class QDialog;

namespace Gui
{
class PrefQuantitySpinBox;
}

namespace Sketcher
{
class Constraint;
class SketchObject;
}  // namespace Sketcher

namespace SketcherGui
{
class ViewProviderSketch;
class Ui_InsertDatum;

bool checkConstraintName(const Sketcher::SketchObject* sketch, std::string constraintName);

/// Why askDatumValues asks for values.
enum class DatumRequest
{
    /// The constraints were just placed; their transaction holds them.
    NewConstraints,
    /// The user wants to change an existing constraint (double-click on its label).
    ExistingConstraint,
};

/// Asks for the values of the dimensional, driving constraints among constrIds (in placement
/// order) and closes the transaction once, so a placement or an edit is one undo step.
/// - New constraints are asked for only if "Ask for the value" (ShowDialogOnDistanceConstraint) is
///   on; otherwise, and in a sketch with conflicts, the transaction is committed as it is.
/// - With "Type the value at the label" (DimensionValueInPlace) on, a value field opens at each
///   label (EditDatumDialog::execInPlace). Esc keeps the current values (new constraints) or
///   changes nothing (an existing one).
/// - Otherwise the dialog opens for each; its Cancel aborts the transaction, as before.
void askDatumValues(
    Sketcher::SketchObject* sketch,
    const std::vector<int>& constrIds,
    int transactionID,
    DatumRequest request
);

class EditDatumDialog: public QObject
{
    Q_OBJECT

public:
    /// How execInPlace ended.
    enum InPlaceResult
    {
        InPlaceKept = 0,      ///< Esc: the constraint keeps its current value
        InPlaceApplied = 1,   ///< Enter, or a click outside with valid input
        InPlaceNext = 2,      ///< Tab with a next field
        InPlacePrevious = 3,  ///< Shift+Tab with a previous field
    };

    EditDatumDialog(int tid, ViewProviderSketch* vp, int ConstrNbr);
    EditDatumDialog(int tid, Sketcher::SketchObject* pcSketch, int ConstrNbr);
    ~EditDatumDialog() override;

    int exec(bool atCursor = true);
    /// A frameless value field at the constraint's label (at the cursor if the label isn't
    /// drawn), run modally. A valid value is applied in the open transaction, which stays open:
    /// the caller closes it. Invalid input keeps the field open, red, with the reason in its
    /// tooltip. A typed expression that refers to a property (a spreadsheet alias) becomes the
    /// constraint's expression. Returns an InPlaceResult.
    int execInPlace(bool hasNext = false, bool hasPrevious = false);
    /// Whether the dialog's OK commits the transaction (the default) or leaves it to the caller.
    void setCommitOnAccept(bool commit);
    bool isSuccess();

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    Sketcher::SketchObject* sketch;
    Sketcher::Constraint* Constr;
    int ConstrNbr;
    bool success;
    std::unique_ptr<Ui_InsertDatum> ui_ins_datum;
    int transactionID;
    bool commitOnAccept {true};

    /// The value field: the dialog's or the popup's.
    Gui::PrefQuantitySpinBox* valueEdit {nullptr};
    QDialog* inPlacePopup {nullptr};
    bool inPlaceHasNext {false};
    bool inPlaceHasPrevious {false};
    bool inPlaceEscapePressed {false};

private Q_SLOTS:
    void accepted();
    void rejected();
    void drivingToggled(bool);
    void datumChanged();
    void formEditorOpened(bool);
    void typeChanged(bool);

private:
    /// Sets up valueEdit for the constraint: units, history, value, binding. Returns the
    /// dialog's title and the value's label.
    void setupValueEdit(QString& title, QString& label);
    /// Applies valueEdit's value to the constraint in the open transaction. Throws on failure.
    void applyValue();
    /// applyValue for the popup; on failure, shows the reason in the field and returns false.
    bool applyInPlace();
    void performAutoScale(double newDatum);
};

}  // namespace SketcherGui
