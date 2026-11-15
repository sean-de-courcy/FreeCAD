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

#include <QEvent>
#include <QGridLayout>
#include <QSplitter>

#include <App/Application.h>

#include "ComboView.h"
#include "PropertyView.h"
#include "Tree.h"


using namespace Gui;
using namespace Gui::DockWnd;


/* TRANSLATOR Gui::DockWnd::ComboView */

ComboView::ComboView(Gui::Document* pcDocument, QWidget* parent)
    : DockWindow(pcDocument, parent)
{
    auto pLayout = new QGridLayout(this);
    pLayout->setSpacing(0);
    pLayout->setContentsMargins(0, 0, 0, 0);

    // tabs to switch between Tree/Properties and TaskPanel
    auto splitter = new QSplitter();
    pLayout->addWidget(splitter, 0, 0);

    // splitter between tree and property view
    splitter->setOrientation(Qt::Vertical);

    tree = new TreePanel("ComboView", this);
    splitter->addWidget(tree);

    // property view
    prop = new PropertyView(this);
    splitter->addWidget(prop);

    // FreeCAD-CH (ops#796): Onshape has no property pane under its lists. When the separate
    // Property View panel is enabled (the "FreeCAD-CH Onshape" pack enables it, hidden, so it
    // stays in View > Panels), the Model panel shows only the lists.
    auto hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/DockWindows/PropertyView"
    );
    if (hGrp->GetBool("Enabled", false)) {
        prop->hide();
    }
}

ComboView::~ComboView() = default;

#include "moc_ComboView.cpp"
