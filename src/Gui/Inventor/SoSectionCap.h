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

#include <Inventor/fields/SoSFBool.h>
#include <Inventor/fields/SoSFColor.h>
#include <Inventor/fields/SoSFVec3f.h>
#include <Inventor/nodes/SoSeparator.h>
#include <FCGlobal.h>

class SoAction;
class SoAudioRenderAction;
class SoCallbackAction;
class SoGLRenderAction;
class SoGetBoundingBoxAction;
class SoGetMatrixAction;
class SoGetPrimitiveCountAction;
class SoHandleEventAction;
class SoPickAction;
class SoRayPickAction;
class SoSearchAction;
class SoWriteAction;

namespace Gui
{

/**
 * Stencil-buffer cap for a view-only section view.
 *
 * Place the node after the scene content in the scene graph's root, while an SoClipPlane that
 * sits before the content (same plane) is active. During the OpenGL render the node draws the
 * given model twice without touching colour or depth (back faces increment, front faces
 * decrement the stencil buffer), so the stencil is non-zero exactly where the view ray enters
 * the clipped solid. Then it fills the plane with a flat colour where the stencil is non-zero.
 *
 * The model is a shared child: the node is invisible to every other action (bounding box,
 * search, callback), so the model is never seen twice. A ray pick that meets the cap where it is
 * seen gets a hit on the plane, which belongs to no view provider: a click on the cap picks
 * nothing, not the face behind it.
 *
 * The plane is given as the SoClipPlane's: normal points to the side that stays visible.
 */
class GuiExport SoSectionCap: public SoSeparator
{
    using inherited = SoSeparator;

    SO_NODE_HEADER(Gui::SoSectionCap);

public:
    static void initClass();
    SoSectionCap();

    SoSFBool on;        /**< False: draws nothing */
    SoSFVec3f origin;   /**< a point on the plane */
    SoSFVec3f normal;   /**< plane normal, pointing to the kept side */
    SoSFColor color;    /**< flat colour of the cap */

    /** The scene content that gets capped (the node is shared, not copied) */
    void setModel(SoNode* model);

    void doAction(SoAction* action) override;
    void GLRenderBelowPath(SoGLRenderAction* action) override;
    void GLRenderInPath(SoGLRenderAction* action) override;
    void GLRenderOffPath(SoGLRenderAction* action) override;
    void callback(SoCallbackAction* action) override;
    void getBoundingBox(SoGetBoundingBoxAction* action) override;
    void getMatrix(SoGetMatrixAction* action) override;
    void handleEvent(SoHandleEventAction* action) override;
    void pick(SoPickAction* action) override;
    void rayPick(SoRayPickAction* action) override;
    void search(SoSearchAction* action) override;
    void write(SoWriteAction* action) override;
    void getPrimitiveCount(SoGetPrimitiveCountAction* action) override;
    void audioRender(SoAudioRenderAction* action) override;

protected:
    ~SoSectionCap() override;
};

}  // namespace Gui
