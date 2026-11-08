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

#pragma once

#include <fastsignals/signal.h>

#include <App/DocumentObserver.h>
#include <Gui/TaskView/TaskDialog.h>

#include "TaskSketcherConstraints.h"
#include "TaskSketcherElements.h"
#include "TaskSketcherMessages.h"
#include "TaskSketcherSolverAdvanced.h"
#include "TaskSketcherTool.h"
#include "ViewProviderSketch.h"


using Connection = fastsignals::connection;

namespace SketcherGui
{


/// simulation dialog for the TaskView
class SketcherGuiExport TaskDlgEditSketch: public Gui::TaskView::TaskDialog
{
    Q_OBJECT

public:
    explicit TaskDlgEditSketch(ViewProviderSketch* sketchView);
    ~TaskDlgEditSketch() override;
    ViewProviderSketch* getSketchView() const
    {
        return sketchView;
    }

public:
    /// is called the TaskView when the dialog is opened
    void open() override;
    /// is called by the framework when the dialog is closed
    void closed() override;
    /// is called by the framework if an button is clicked which has no accept or reject role
    void clicked(int) override;
    /// is called by the framework if the dialog is accepted (Ok)
    bool accept() override;
    /// is called by the framework if the dialog is rejected (Cancel)
    bool reject() override;
    bool isAllowedAlterDocument() const override
    {
        return false;
    }
    void autoClosedOnResetEdit() override;
    void autoClosedOnClosedView() override;

    QDialogButtonBox::StandardButtons getStandardButtons() const override;

    /** @brief Function used to register a slot to be triggered when the tool widget is changed. */
    template<typename F>
    fastsignals::connection registerToolWidgetChanged(F&& f)
    {
        return ToolSettings->registerToolWidgetChanged(std::forward<F>(f));
    }

    /** FreeCAD-CH (ops#640): a panel another module puts at the top of the dialog (PartDesign's
     * Sketch plane box), made for the sketch edited, or null for none. The dialog owns it. A plain
     * function, so the list holds nothing of the module that registered it at exit.
     */
    using ContentFactory = QWidget* (*)(ViewProviderSketch* sketchView);
    /// Adds \a factory; every dialog made after it asks it for its panel.
    static void addContentFactory(ContentFactory factory);
    /// True once a module has added one (PartDesignGui, when it is loaded).
    static bool hasContentFactories();

    /** FreeCAD-CH (ops#640, hands-on R1): the sketch was made for this dialog (New Sketch, with
     * Onshape's keymap). Cancel removes it, as Onshape's cancel of a new sketch does, in its own
     * undo step (Ctrl+Z brings it back, as Onshape's Restore); so does OK while it still has no
     * plane and nothing in it.
     */
    void setNewSketch(bool on)
    {
        newSketch = on;
    }
    bool isNewSketch() const
    {
        return newSketch;
    }
    /** FreeCAD-CH (ops#640, hands-on C-1): the sketch tools are greyed (isCommandActive) while the
     * sketch waits for its plane (PartDesign's Sketch plane box sets it).
     */
    void setToolsBlocked(bool on)
    {
        toolsBlocked = on;
    }
    bool areToolsBlocked() const
    {
        return toolsBlocked;
    }
    /// The sketch dialog open now on \a view, or null.
    static TaskDlgEditSketch* ofSketchView(const ViewProviderSketch* view);
    /// Removes a cancelled new sketch, in its own undo step ("Cancel New Sketch").
    static void removeNewSketch(const App::DocumentObjectT& sketch);

protected:
    void slotUndoDocument(const App::Document&);
    void slotRedoDocument(const App::Document&);

private:
    void slotToolChanged(const std::string& toolname);
    void saveDialogState() const;

protected:
    ViewProviderSketch* sketchView;
    TaskSketcherConstraints* Constraints;
    TaskSketcherElements* Elements;
    TaskSketcherMessages* Messages;
    TaskSketcherSolverAdvanced* SolverAdvanced;
    TaskSketcherTool* ToolSettings;

private:
    Connection connectionToolSettings;
    bool isEscapeAction {false};
    bool newSketch {false};
    bool toolsBlocked {false};
};


}  // namespace SketcherGui
