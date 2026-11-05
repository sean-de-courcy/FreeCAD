// SPDX-License-Identifier: LGPL-2.1-or-later
/***************************************************************************
 *   Copyright (c) 2009 Jürgen Riegel <juergen.riegel@web.de>              *
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


#include <algorithm>

#include <QDialogButtonBox>
#include <QHBoxLayout>
#include <QPushButton>

#include <Gui/BitmapFactory.h>

#include "TaskEditControl.h"


using namespace Gui::TaskView;

TaskEditControl::TaskEditControl(QWidget* parent)
    : TaskWidget(parent)
{
    hboxLayout = new QHBoxLayout(this);
    buttonBox = new QDialogButtonBox(this);
    buttonBox->setStandardButtons(QDialogButtonBox::Cancel | QDialogButtonBox::Ok);
    // At the right of the box's top, as Onshape's check and cross (ops#605 2a)
    buttonBox->setCenterButtons(false);

    hboxLayout->addWidget(buttonBox);
}

TaskEditControl::~TaskEditControl() = default;

QDialogButtonBox* TaskEditControl::standardButtons() const
{
    return buttonBox;
}

void TaskEditControl::decorateButtons(bool defaultOk)
{
    // The words become tooltips. A button the dialog renamed (Create, Run Check, Delete) keeps
    // its words, gets no icon and isn't made the default. With defaultOk the checked OK is the
    // default button, so Enter in a field of the panel accepts it (TaskView::keyPressEvent),
    // unless the dialog made a button of its own the default (FEM's Apply)
    const auto decorate = [this](QDialogButtonBox::StandardButton which, const char* icon) {
        QPushButton* button = buttonBox->button(which);
        if (!button) {
            return false;
        }
        QDialogButtonBox standard;
        standard.setStandardButtons(which);
        if (button->text() != standard.button(which)->text()) {
            return false;
        }
        button->setIcon(BitmapFactory().iconFromTheme(icon));
        button->setToolTip(button->text().remove(QLatin1Char('&')));
        button->setAccessibleName(button->toolTip());
        button->setText(QString());
        return true;
    };
    const bool checked = decorate(QDialogButtonBox::Ok, "edit_OK");
    decorate(QDialogButtonBox::Cancel, "edit_Cancel");

    const QList<QAbstractButton*> buttons = buttonBox->buttons();
    const bool ownDefault = std::ranges::any_of(buttons, [](QAbstractButton* button) {
        auto* push = qobject_cast<QPushButton*>(button);
        return push && push->isDefault();
    });
    if (checked && defaultOk && !ownDefault) {
        buttonBox->button(QDialogButtonBox::Ok)->setDefault(true);
    }
}

#include "moc_TaskEditControl.cpp"
