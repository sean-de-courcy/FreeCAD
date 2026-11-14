// SPDX-License-Identifier: LGPL-2.1-or-later

/****************************************************************************
 *                                                                          *
 *   This file is part of the FreeCAD CAx development system.               *
 *                                                                          *
 *   This library is free software; you can redistribute it and/or          *
 *   modify it under the terms of the GNU Library General Public            *
 *   License as published by the Free Software Foundation; either           *
 *   version 2 of the License, or (at your option) any later version.       *
 *                                                                          *
 *   This library  is distributed in the hope that it will be useful,       *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of         *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          *
 *   GNU Library General Public License for more details.                   *
 *                                                                          *
 *   You should have received a copy of the GNU Library General Public      *
 *   License along with this library; see the file COPYING.LIB. If not,     *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,          *
 *   Suite 330, Boston, MA  02111-1307, USA                                 *
 *                                                                          *
 ****************************************************************************/

#pragma once

#include <string>

#include <FCGlobal.h>

using PyObject = struct _object;

namespace App
{
class Document;
class DocumentObject;
}

namespace Gui
{
class Document;
class MainWindow;
class MDIView;
class View3DInventorViewer;
class ViewProvider;

/** Onshape's typed tabs in the GUI (FreeCAD-CH, ops#640 rank 59, notes/onshape-tabs-design.md
 * slice 1), under the Onshape keymap only.
 *
 * Each Part Studio or Assembly tab is its own 3D view (an MDI view tagged with the tab's name, "*"
 * for the implicit studio), whose viewer shows only the tab's objects: accepts() is the filter
 * View3DInventorViewer::addViewProvider() applies. A Drawing tab is its page's view; a Variable
 * Studio tab shows the Variables panel. A bar along the bottom lists the active document's tabs,
 * with "+" (Part Studio, Assembly, Drawing, Variable Studio) and a menu per tab (Rename, Delete);
 * a strip on top lists the open documents. The MDI area's own tab bar is hidden. Undo stays one
 * history per document; a step made in another tab switches to that tab before it is undone or
 * redone. Under FreeCAD's keymap nothing here acts: one view shows everything, as upstream.
 */
namespace DocumentTabs
{

/// Whether the typed tabs are on (the Onshape keymap)
GuiExport bool isOn();

/// Whether @p viewer shows @p vp: always for an untagged viewer or a provider of no document object
GuiExport bool accepts(const View3DInventorViewer* viewer, const ViewProvider* vp);

/// The tab name of a 3D view ("" when it has none)
GuiExport std::string tabOfView(const MDIView* view);

/// Gui::Document::createView(): tags a new 3D view with its tab and filters it
GuiExport void viewCreated(Gui::Document* doc, MDIView* view);

/// Gui::Document::undo()/redo(): shows the tab the next step was made in
GuiExport void beforeUndo(Gui::Document* doc, bool undo);

/** Gui::Document::trySetEdit(), once the edit will start: an object of another tab (by its top
 * parent, @p vp) is edited in its own tab's view; false (the edit refused, the status bar says
 * why) when that takes a switch while another dialog is open
 */
GuiExport bool beforeEdit(Gui::Document* doc, ViewProvider* vp);

/** Gui::Document::setActiveView(): the view to show @p obj in, its 3D tab's (made when it has
 * none), or the active tab's view for an object no 3D tab shows; nullptr when the tabs are off
 */
GuiExport MDIView* viewOfObject(Gui::Document* doc, const App::DocumentObject* obj);

/// Std_New: a new document's first Part Studio, an App::Part "Part Studio 1" (design T2-a)
GuiExport void newDocumentStudio(App::Document* doc);

/// The active tab of @p doc ("" when there is none)
GuiExport std::string activeTab(const App::Document* doc);

/** Switches @p doc to the tab @p name, as a click on the bar does: refused while a dialog is open
 * (@p refusal says why); the selection is cleared and the toolbar follows the tab's kind.
 */
GuiExport bool switchTo(
    App::Document* doc,
    const std::string& name,
    std::string* refusal = nullptr
);

/** Whether the workbench @p name fits the active document's active tab: a Part Studio takes Part
 * Design and the Sketcher, an Assembly its own, a Drawing TechDraw, a Variable Studio none besides
 * the one it has; always when the tabs are off or no document is open. Std_Workbench (the selector,
 * View > Workbench) asks; a script's activateWorkbench doesn't. @p refusal says why ("This tab is
 * a Part Studio: use + for an Assembly").
 */
GuiExport bool allowsWorkbench(const std::string& name, std::string* refusal = nullptr);

/// MainWindow: the bars, the hidden MDI tab bar, the controller
GuiExport void setup(MainWindow* mw);

/// The Python module FreeCADGui.DocumentTabs
GuiExport PyObject* pythonModule();

}  // namespace DocumentTabs
}  // namespace Gui
