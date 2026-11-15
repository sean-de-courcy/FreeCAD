// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 FreeCAD-CH contributors                            *
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

#ifndef PARTGUI_EDGEMIDPOINTMARKER_H
#define PARTGUI_EDGEMIDPOINTMARKER_H

#include <optional>

#include <QObject>
#include <QPointer>

#include <Base/Vector3D.h>
#include <Gui/Selection/Selection.h>
#include <Mod/Part/PartGlobal.h>

class TopoDS_Edge;
class SoSwitch;
class SoCoordinate3;

namespace Gui
{
class View3DInventorViewer;
}

namespace PartGui
{

/** FreeCAD-CH (selection parity 10, SP10-Q8/Q9/Q11): Onshape's midpoint marker on model edges.
 * Hovering a model edge within about 8 px of its middle shows a small marker there, in the 3D view
 * and on the model picks of a sketch in edit (both go through the 3D preselection). An open edge
 * has a middle (half its length); a closed one (a full circle) has none. A sketch's own curves in
 * edit get no marker (SP10-Q6). The marker is a node named "EdgeMidpointMarker" (an SoSwitch, its
 * point "EdgeMidpointMarkerPoint") at the top of the active view's scene graph.
 */
class PartGuiExport EdgeMidpointMarker: public QObject, public Gui::SelectionObserver
{
public:
    /// Onshape's midpoint radius in screen pixels (SQ2: about 8 px along the edge)
    static constexpr double radiusPixels = 8.0;

    static void create();
    static void destruct();

    /// the middle of an open edge (the point at half its length); none for a closed edge
    static std::optional<Base::Vector3d> middleOf(const TopoDS_Edge& edge);

    /** The middle of the edge named by a 3D pick (document, object, full subname), when the
     * picked point lies within radiusPixels of it on the active view's screen.
     */
    static std::optional<Base::Vector3d> pickedMiddle(const char* docName,
                                                      const char* objName,
                                                      const char* subName,
                                                      const Base::Vector3d& picked);

private:
    EdgeMidpointMarker();
    ~EdgeMidpointMarker() override;

    void onSelectionChanged(const Gui::SelectionChanges& msg) override;
    /// the cursor moving along the preselected edge (no selection message for that) moves in or
    /// out of its middle's radius
    bool eventFilter(QObject* watched, QEvent* event) override;
    void attach(Gui::View3DInventorViewer* target);
    void update(const Base::Vector3d& picked);
    void hide();
    void detach();

    QPointer<Gui::View3DInventorViewer> viewer;
    /// the preselected edge's middle, when it is a model edge with one
    std::optional<Base::Vector3d> middle;
    SoSwitch* marker = nullptr;
    SoCoordinate3* coordinate = nullptr;

    static EdgeMidpointMarker* instance;  // NOLINT
};

}  // namespace PartGui

#endif  // PARTGUI_EDGEMIDPOINTMARKER_H
