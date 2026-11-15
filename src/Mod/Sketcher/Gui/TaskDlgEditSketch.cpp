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
#include <vector>

#include <App/Document.h>
#include <Base/Exception.h>
#include <Gui/Command.h>
#include <Gui/Control.h>
#include <Mod/Sketcher/App/SketchObject.h>

#include "TaskDlgEditSketch.h"
#include "ViewProviderSketch.h"


using namespace SketcherGui;

namespace sp = std::placeholders;

namespace
{
// FreeCAD-CH (ops#640): the panels other modules add (TaskDlgEditSketch::addContentFactory)
std::vector<TaskDlgEditSketch::ContentFactory>& contentFactories()
{
    static std::vector<TaskDlgEditSketch::ContentFactory> factories;
    return factories;
}
}  // namespace

void TaskDlgEditSketch::addContentFactory(ContentFactory factory)
{
    auto& factories = contentFactories();
    if (factory && std::ranges::find(factories, factory) == factories.end()) {
        factories.push_back(factory);
    }
}

bool TaskDlgEditSketch::hasContentFactories()
{
    return !contentFactories().empty();
}

TaskDlgEditSketch* TaskDlgEditSketch::ofSketchView(const ViewProviderSketch* view)
{
    auto dlg = qobject_cast<TaskDlgEditSketch*>(Gui::Control().activeDialog());
    return dlg && view && dlg->getSketchView() == view ? dlg : nullptr;
}

void TaskDlgEditSketch::removeNewSketch(const App::DocumentObjectT& sketchT)
{
    App::DocumentObject* sketch = sketchT.getObject();
    if (!sketch || !sketch->isAttachedToDocument()) {
        return;
    }
    App::Document* doc = sketch->getDocument();
    // Its own step: Ctrl+Z brings the sketch back, as Onshape's "Restore" does
    doc->openTransaction(QT_TRANSLATE_NOOP("Command", "Cancel New Sketch"));
    try {
        Gui::Command::doCommand(
            Gui::Command::Doc,
            "App.getDocument('%s').removeObject('%s')",
            doc->getName(),
            sketch->getNameInDocument()
        );
        doc->commitTransaction();
    }
    catch (const Base::Exception& e) {
        e.reportException();
        doc->abortTransaction();
    }
}

//**************************************************************************
//**************************************************************************
// TaskDialog
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TaskDlgEditSketch::TaskDlgEditSketch(ViewProviderSketch* sketchView)
    : TaskDialog()
    , sketchView(sketchView)
{
    assert(sketchView);
    roleOnEscape = QDialogButtonBox::ButtonRole::AcceptRole;

    ToolSettings = new TaskSketcherTool(sketchView);
    Constraints = new TaskSketcherConstraints(sketchView);
    Elements = new TaskSketcherElements(sketchView);
    Messages = new TaskSketcherMessages(sketchView);
    SolverAdvanced = new TaskSketcherSolverAdvanced(sketchView);

    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Sketcher"
    );
    // FreeCAD-CH (ops#640): Esc with no tool running keeps the sketch open, as in Onshape
    setEscapeButtonEnabled(hGrp->GetBool("LeaveSketchWithEscape", false));
    setAutoCloseOnResetEdit(true);

    // FreeCAD-CH (ops#640): other modules' panels first (the Sketch plane box, at the top as in
    // Onshape's sketch dialog)
    for (ContentFactory factory : contentFactories()) {
        if (QWidget* panel = factory(sketchView)) {
            Content.push_back(panel);
        }
    }

    Content.push_back(Messages);
    Content.push_back(ToolSettings);

    if (hGrp->GetBool("ShowSolverAdvancedWidget", false)) {
        Content.push_back(SolverAdvanced);
    }

    Content.push_back(Constraints);
    Content.push_back(Elements);

    if (!hGrp->GetBool("ExpandedMessagesWidget", true)) {
        Messages->hideGroupBox();
    }
    if (!hGrp->GetBool("ExpandedSolverAdvancedWidget", false)) {
        SolverAdvanced->hideGroupBox();
    }
    if (!hGrp->GetBool("ExpandedConstraintsWidget", true)) {
        Constraints->hideGroupBox();
    }
    if (!hGrp->GetBool("ExpandedElementsWidget", true)) {
        Elements->hideGroupBox();
    }

    connectionToolSettings = sketchView->registerToolChanged(
        std::bind(&SketcherGui::TaskDlgEditSketch::slotToolChanged, this, sp::_1)
    );

    ToolSettings->setHidden(true);

    associateToObject3dView(sketchView->getObject());
}

TaskDlgEditSketch::~TaskDlgEditSketch()
{
    // to make sure to delete the advanced solver panel
    // it must be part to the 'Content' array
    if (const auto it = std::ranges::find(Content, SolverAdvanced); it == Content.end()) {
        Content.push_back(SolverAdvanced);
    }

    connectionToolSettings.disconnect();
}

void TaskDlgEditSketch::slotToolChanged(const std::string& toolname)
{
    bool widgetvisible = false;

    if (toolname != "DSH_None") {
        widgetvisible = sketchView->toolManager.isWidgetVisible();

        ToolSettings->toolChanged(toolname);
    }

    ToolSettings->setHidden(!widgetvisible);
}

//==== calls from the TaskView ===============================================================


void TaskDlgEditSketch::open()
{}

void TaskDlgEditSketch::closed()
{}

void TaskDlgEditSketch::clicked(int)
{}

bool TaskDlgEditSketch::reject()
{
    ViewProviderSketch* view = sketchView;
    std::string document = getDocumentName();  // needed because resetEdit() deletes this instance
    // FreeCAD-CH (ops#640, hands-on R1): Onshape's cancel of a new sketch removes it
    const bool removeSketch = newSketch;
    const App::DocumentObjectT sketchT(view->getObject());
    view->editingCancelled = true;
    Gui::Command::doCommand(Gui::Command::Gui, "Gui.getDocument('%s').resetEdit()", document.c_str());
    view->editingCancelled = false;
    if (removeSketch) {
        removeNewSketch(sketchT);
    }

    return true;
}

bool TaskDlgEditSketch::accept()
{
    std::string document = getDocumentName();  // needed because resetEdit() deletes this instance
    // FreeCAD-CH (ops#640): a new sketch closed while it still waits for its plane, with nothing
    // in it, goes as a cancelled one does: there was nothing to draw on
    auto sketch = dynamic_cast<Sketcher::SketchObject*>(sketchView->getObject());
    const bool removeSketch = newSketch && toolsBlocked && sketch
        && sketch->Geometry.getSize() == 0 && sketch->Constraints.getSize() == 0;
    const App::DocumentObjectT sketchT(sketch);
    Gui::Command::doCommand(Gui::Command::Gui, "Gui.getDocument('%s').resetEdit()", document.c_str());
    if (removeSketch) {
        removeNewSketch(sketchT);
    }
    Gui::Command::doCommand(Gui::Command::Doc, "App.getDocument('%s').recompute()", document.c_str());

    return true;
}

void TaskDlgEditSketch::saveDialogState() const
{
    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Sketcher"
    );
    hGrp->SetBool("ExpandedMessagesWidget", Messages->isGroupVisible());
    hGrp->SetBool("ExpandedSolverAdvancedWidget", SolverAdvanced->isGroupVisible());
    hGrp->SetBool("ExpandedConstraintsWidget", Constraints->isGroupVisible());
    hGrp->SetBool("ExpandedElementsWidget", Elements->isGroupVisible());
}

QDialogButtonBox::StandardButtons TaskDlgEditSketch::getStandardButtons() const
{
    return QDialogButtonBox::Ok | QDialogButtonBox::Cancel;
}

void TaskDlgEditSketch::autoClosedOnResetEdit()
{
    saveDialogState();
}

void TaskDlgEditSketch::autoClosedOnClosedView()
{
    // FreeCAD-CH (ops#640): the view (or its document) closing is no cancel: the sketch stays
    newSketch = false;
    // Make sure the edit mode is exited when the view is closed.
    reject();
}

#include "moc_TaskDlgEditSketch.cpp"
