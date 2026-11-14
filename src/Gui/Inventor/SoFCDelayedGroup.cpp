// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 Crawlspace Habitats LLC                            *
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

#include <Inventor/SoPath.h>
#include <Inventor/actions/SoGLRenderAction.h>

#include "SoFCDelayedGroup.h"


using namespace Gui;

SO_NODE_SOURCE(SoFCDelayedGroup)

void SoFCDelayedGroup::initClass()
{
    SO_NODE_INIT_CLASS(SoFCDelayedGroup, SoSeparator, "Separator");
}

SoFCDelayedGroup::SoFCDelayedGroup()
{
    SO_NODE_CONSTRUCTOR(SoFCDelayedGroup);

    // the render action's delayed paths invalidate caches anyway
    renderCaching.setValue(OFF);
}

SoFCDelayedGroup::~SoFCDelayedGroup() = default;

void SoFCDelayedGroup::GLRenderBelowPath(SoGLRenderAction* action)
{
    if (!action->isRenderingDelayedPaths()) {
        // first pass: the render action calls back for this path when the rest is drawn
        action->addDelayedPath(action->getCurPath()->copy());
        return;
    }
    inherited::GLRenderBelowPath(action);
}
