// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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

#include <Precision.hxx>
#include <QComboBox>
#include <QListView>
#include <QStandardItemModel>


#include <Mod/PartDesign/App/FeaturePad.h>

#include "ui_TaskPadPocketParameters.h"
#include "TaskPadParameters.h"


using namespace PartDesignGui;
using namespace Gui;

/* TRANSLATOR PartDesignGui::TaskPadParameters */

TaskPadParameters::TaskPadParameters(ViewProviderPad* PadView, QWidget* parent, bool newObj)
    : TaskExtrudeParameters(PadView, parent, "PartDesign_Pad", tr("Pad Parameters"))
{
    ui->offsetEdit->setToolTip(tr("Offset the pad from the face at which the pad will end on side 1"));
    ui->offsetEdit2->setToolTip(tr("Offset the pad from the face at which the pad will end on side 2"));
    ui->checkBoxReversed->setToolTip(tr("Reverses pad direction"));

    // set the history path
    ui->lengthEdit->setEntryName(QByteArray("Length"));
    ui->lengthEdit->setParamGrpPath(QByteArray("User parameter:BaseApp/History/PadLength"));
    ui->lengthEdit2->setEntryName(QByteArray("Length2"));
    ui->lengthEdit2->setParamGrpPath(QByteArray("User parameter:BaseApp/History/PadLength2"));
    ui->offsetEdit->setEntryName(QByteArray("Offset"));
    ui->offsetEdit->setParamGrpPath(QByteArray("User parameter:BaseApp/History/PadOffset"));
    ui->offsetEdit2->setEntryName(QByteArray("Offset2"));
    ui->offsetEdit2->setParamGrpPath(QByteArray("User parameter:BaseApp/History/PadOffset2"));
    ui->taperEdit->setEntryName(QByteArray("TaperAngle"));
    ui->taperEdit->setParamGrpPath(QByteArray("User parameter:BaseApp/History/PadTaperAngle"));
    ui->taperEdit2->setEntryName(QByteArray("TaperAngle2"));
    ui->taperEdit2->setParamGrpPath(QByteArray("User parameter:BaseApp/History/PadTaperAngle2"));

    setupDialog();

    // if it is a newly created object use the last value of the history
    if (newObj) {
        readValuesFromHistory();
    }
}

TaskPadParameters::~TaskPadParameters() = default;

namespace
{
// Onshape has no Up to last (FreeCAD-CH ops#640, rank 22): its entry stays in the end type box,
// hidden and unpickable, unless the feature already ends so (an older file). \a mode and
// \a index are Modes, the rows' data
void offerOnlyIfChosen(QComboBox* box, int mode, int index)
{
    const int row = box->findData(mode);
    const bool hide = index != mode;
    if (auto view = qobject_cast<QListView*>(box->view())) {
        view->setRowHidden(row, hide);
    }
    if (auto model = qobject_cast<QStandardItemModel*>(box->model())) {
        if (QStandardItem* item = model->item(row)) {
            item->setEnabled(!hide);
        }
    }
}
}  // namespace

void TaskPadParameters::translateModeList(QComboBox* box, int index)
{
    // Onshape's words and order (FreeCAD-CH ops#640, rank 22): Blind, Up to next, Up to face,
    // Up to part, Up to vertex, Through all; each row's data is its Mode (\a index is one)
    auto add = [box](const QString& text, Mode mode) {
        box->addItem(text, static_cast<int>(mode));
    };
    box->clear();
    add(tr("Blind"), Mode::Dimension);
    add(tr("Up to last"), Mode::ToLast);
    add(tr("Up to next"), Mode::ToFirst);
    add(tr("Up to face"), Mode::ToFace);
    add(tr("Up to part"), Mode::ToShape);
    add(tr("Up to vertex"), Mode::ToVertex);
    // Mode::Appended (ops#640): the end type a Pocket offers too
    add(tr("Through all"), Mode::Appended);
    offerOnlyIfChosen(box, static_cast<int>(Mode::ToLast), index);
    box->setCurrentIndex(rowOfMode(box, static_cast<Mode>(index)));
}

void TaskPadParameters::updateUI(Side side)
{
    // update direction combobox
    fillDirectionCombo();
    // set and enable checkboxes
    updateWholeUI(Type::Pad, side);
}

void TaskPadParameters::onModeChanged(int index, Side side)
{
    auto& sideCtrl = getSideController(side);

    switch (static_cast<Mode>(index)) {
        case Mode::Dimension:
            sideCtrl.Type->setValue("Length");
            if (side == Side::First) {
                // Avoid error message
                double L = sideCtrl.lengthEdit->value().getValue();
                Side otherSide = side == Side::First ? Side::Second : Side::First;
                auto& sideCtrl2 = getSideController(otherSide);
                double L2 = static_cast<SidesMode>(getSidesMode()) == SidesMode::TwoSides
                    ? sideCtrl2.lengthEdit->value().getValue()
                    : 0;
                if (std::abs(L + L2) < Precision::Confusion()) {
                    sideCtrl.lengthEdit->setValue(5.0);
                }
            }
            break;
        case Mode::ToLast:
            sideCtrl.Type->setValue("UpToLast");
            break;
        case Mode::ToFirst:
            sideCtrl.Type->setValue("UpToFirst");
            break;
        case Mode::ToFace:
            // An empty face field arms in updateUI() (ops#150)
            sideCtrl.Type->setValue("UpToFace");
            break;
        case Mode::ToShape:
            sideCtrl.Type->setValue("UpToShape");
            break;
        case Mode::Appended:
            sideCtrl.Type->setValue("ThroughAll");
            break;
        case Mode::ToVertex:
            // Up to vertex (ops#640 rank 22): an empty vertex field arms in updateUI()
            sideCtrl.Type->setValue("UpToVertex");
            break;
    }

    updateUI(side);
    recomputeFeature();
}

void TaskPadParameters::apply()
{
    applyParameters();
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgPadParameters::TaskDlgPadParameters(ViewProviderPad* PadView, bool /*newObj*/)
    : TaskDlgExtrudeParameters(PadView)
    , parameters(new TaskPadParameters(PadView))
{
    Content.push_back(parameters);
    addResultBox();
    Content.push_back(preview);
}

//==== calls from the TaskView ===============================================================

#include "moc_TaskPadParameters.cpp"
