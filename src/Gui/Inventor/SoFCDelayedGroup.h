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

#pragma once

#include <Inventor/nodes/SoSeparator.h>
#include <FCGlobal.h>

class SoGLRenderAction;

namespace Gui
{

/**
 * A separator that is drawn after the rest of the scene: when the scene is rendered it only
 * remembers its path, and draws its children when the render action renders its delayed
 * paths (the way it draws transparent objects), so the depth buffer already holds all the
 * opaque faces. Meant for what has to be seen against the finished depth buffer, like the
 * edges behind faces. All other actions treat it as a plain separator.
 */
class GuiExport SoFCDelayedGroup: public SoSeparator
{
    using inherited = SoSeparator;

    SO_NODE_HEADER(Gui::SoFCDelayedGroup);

public:
    static void initClass();
    SoFCDelayedGroup();

    void GLRenderBelowPath(SoGLRenderAction* action) override;

protected:
    ~SoFCDelayedGroup() override;
};

}  // namespace Gui
