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

#include <QPointer>
#include <QWidget>
#include <FCGlobal.h>

class SbVec3f;
class QDoubleSpinBox;
class QDockWidget;
class QPushButton;
class SoEventCallback;

namespace Gui
{
class View3DInventor;
class View3DInventorViewer;

/**
 * The view-only section view (Onshape's "Section view"): one plane hides the part of the model
 * on its cut side, and a stencil cap fills the cut so the model looks solid. Nothing is added
 * to the document; the state lives in the scene graph of the viewer.
 *
 * The normal always points to the side that is cut away (hidden).
 */
namespace SectionView
{
/** Sets (or moves) the section of the viewer. False if the normal has no length. */
GuiExport bool set(View3DInventorViewer* viewer, const SbVec3f& origin, const SbVec3f& cutNormal);
/** Removes the section of the viewer, if any. */
GuiExport void clear(View3DInventorViewer* viewer);
/** The section of the viewer: false if there is none. */
GuiExport bool get(const View3DInventorViewer* viewer, SbVec3f& origin, SbVec3f& cutNormal);
}  // namespace SectionView

namespace Dialog
{

/**
 * The panel of the section view command: plane buttons, a pick of a face or a selected plane,
 * the offset in mm and a flip. It lives in a dock widget; closing it (button, Esc) removes the
 * section again.
 */
class GuiExport SectionViewPanel: public QWidget
{
    Q_OBJECT

public:
    /** Creates the panel in a dock widget and starts the section on the default plane */
    static SectionViewPanel* makeDockWidget(Gui::View3DInventor* view);
    explicit SectionViewPanel(Gui::View3DInventor* view, QWidget* parent = nullptr);
    ~SectionViewPanel() override;

    Gui::View3DInventor* getView() const;
    /** Closes the dock widget: the destructor removes the section */
    void closePanel();

private:
    void applyPlane();
    void setPlane(const SbVec3f& base, const SbVec3f& cutNormal);
    void setAxisPlane(int axis);
    void onOffsetChanged(double value);
    void onFlip();
    void onSelectedPlane();
    void onPickFace(bool on);
    void stopPicking();
    static void pickCallback(void* userdata, SoEventCallback* node);

    struct Data;
    Data* d;
};

}  // namespace Dialog
}  // namespace Gui
