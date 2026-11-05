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

void TaskEditControl::decorateButtons()
{
    // The words become tooltips; a dialog that renames a button later keeps its icon too.
    // OK is the default button: Enter in the panel accepts it (TaskView::keyPressEvent)
    const auto decorate = [this](QDialogButtonBox::StandardButton which, const char* icon) {
        QPushButton* button = buttonBox->button(which);
        if (!button) {
            return button;
        }
        button->setIcon(BitmapFactory().iconFromTheme(icon));
        button->setToolTip(button->text().remove(QLatin1Char('&')));
        button->setAccessibleName(button->toolTip());
        button->setText(QString());
        return button;
    };
    if (QPushButton* ok = decorate(QDialogButtonBox::Ok, "edit_OK")) {
        ok->setDefault(true);
    }
    decorate(QDialogButtonBox::Cancel, "edit_Cancel");
}

#include "moc_TaskEditControl.cpp"
