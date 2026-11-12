// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *                                                                          *
 *   Copyright (c) 2024 The FreeCAD Project Association AISBL               *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/

#include <QString>
#include <QTimer>

#include <cstdlib>
#include <string>


#include <App/Application.h>
#include <Base/Console.h>
#include <Base/Interpreter.h>
#include <Base/PyObjectBase.h>
#include <Gui/Language/Translator.h>
#include <Gui/Application.h>
#include <Gui/Command.h>
#include <Gui/ForkKeymap.h>
#include <Gui/MainWindow.h>
#include <Gui/Utilities.h>
#include <Gui/WidgetFactory.h>
#include "DlgStartPreferencesImp.h"


#include <gsl/pointers>

#include "Manipulator.h"
#include "StartView.h"

void loadStartResource()
{
    // add resources and reloads the translators
    Q_INIT_RESOURCE(Start);
    Q_INIT_RESOURCE(Start_translation);
    Gui::Translator::instance()->refresh();
}

namespace StartGui
{
extern PyObject* initModule();
}


namespace StartGui
{
class Module: public Py::ExtensionModule<Module>
{
public:
    Module()
        : Py::ExtensionModule<Module>("StartGui")
    {
        initialize("This module is the StartGui module.");  // register with Python
    }
};

// FreeCAD-CH, ops#640 P11: under the Onshape keymap the Start view is Onshape's Documents page,
// shown whenever no document is open: at start and when the last document closes. Not in a run of
// a script given on the command line (the GUI test runs), unless DocumentsPageInScripts is set.
bool isScriptRun()
{
    auto& config = App::Application::Config();
    int count = std::atoi(config["OpenFileCount"].c_str());
    for (int i = 0; i < count; ++i) {
        auto file = QString::fromStdString(config["OpenFile" + std::to_string(i)]).toLower();
        if (file.endsWith(QLatin1String(".py")) || file.endsWith(QLatin1String(".fcmacro"))) {
            return true;
        }
    }
    return false;
}

bool documentsPageWanted()
{
    if (!Gui::ForkKeymap::isOnshape() || !App::GetApplication().getDocuments().empty()) {
        return false;
    }
    auto hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Start"
    );
    return !isScriptRun() || hGrp->GetBool("DocumentsPageInScripts", false);
}

class StartLauncher
{
public:
    StartLauncher()
    {
        if (Gui::isInternalGuiTestRun()) {
            return;
        }

        // QTimers don't fire until the event loop starts, which is our signal that the GUI is up
        QTimer::singleShot(100, [this] { Launch(); });

        if (Gui::Application::Instance) {
            lastClosed = Gui::Application::Instance->signalDeleteDocument.connect(
                [](const Gui::Document&) {
                    // After the document is gone from the application's list
                    QTimer::singleShot(0, [] {
                        auto mw = Gui::getMainWindow();
                        // Not while the main window closes (quit closes every document)
                        if (mw && mw->isVisible() && documentsPageWanted()
                            && !mw->findChild<StartGui::StartView*>(QLatin1String("StartView"))) {
                            Gui::Application::Instance->commandManager().runCommandByName(
                                "Start_Start"
                            );
                        }
                    });
                }
            );
        }
    }

    void Launch()
    {
        if (Gui::isInternalGuiTestRun()) {
            return;
        }

        auto hGrp = App::GetApplication().GetParameterGroupByPath(
            "User parameter:BaseApp/Preferences/Mod/Start"
        );
        bool showOnStartup = Gui::ForkKeymap::isOnshape() ? documentsPageWanted()
                                                          : hGrp->GetBool("ShowOnStartup", true);
        if (showOnStartup) {
            Gui::Application::Instance->commandManager().runCommandByName("Start_Start");
            QTimer::singleShot(100, [this] { EnsureLaunched(); });
        }
    }

    void EnsureLaunched()
    {
        if (Gui::isInternalGuiTestRun()) {
            return;
        }

        // It's possible that "Start_Start" didn't result in the creation of an MDI window, if it
        // was called to early. This polls the views to make sure the view was created, and if it
        // was not, re-calls the command.
        auto mw = Gui::getMainWindow();
        auto existingView = mw->findChild<StartGui::StartView*>(QLatin1String("StartView"));
        if (!existingView) {
            Launch();
        }
    }

private:
    fastsignals::scoped_connection lastClosed;
};

PyObject* initModule()
{
    auto newModule = gsl::owner<Module*>(new Module);
    return Base::Interpreter().addModule(newModule);  // Transfer ownership
}

}  // namespace StartGui

/* Python entry */
PyMOD_INIT_FUNC(StartGui)
{
    static StartGui::StartLauncher* launcher = new StartGui::StartLauncher();
    Q_UNUSED(launcher)

    Base::Console().log("Loading GUI of Start module… ");
    PyObject* mod = StartGui::initModule();
    auto manipulator = std::make_shared<StartGui::Manipulator>();
    Gui::WorkbenchManipulator::installManipulator(manipulator);
    loadStartResource();
    StartGui::StartView::init();
    Base::Console().log("done\n");

    // register preferences pages
    new Gui::PrefPageProducer<StartGui::DlgStartPreferencesImp>(QT_TRANSLATE_NOOP("QObject", "Start"));

    PyMOD_Return(mod);
}
