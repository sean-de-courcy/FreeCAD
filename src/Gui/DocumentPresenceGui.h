// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD-CH fork (ops#640, folder sync item 6, design A's B5).

#pragma once

#include <string>

#include <FCGlobal.h>

class QWidget;

namespace Gui
{
class MainWindow;

/// FreeCAD-CH (ops#640, folder sync item 6): the GUI half of App::DocumentPresence. A minute's
/// heartbeat refreshes this process's markers; a status-bar line ("Ward on WARD-MAC has this
/// document open") shows while another computer has the active document open too.
namespace DocumentPresenceGui
{

/// Registers the status-bar line and starts the heartbeat. Called once by the main window.
void start(MainWindow* mainWindow);

/// Before opening `fileName`: when another computer or process has it open, asks "Open anyway /
/// Cancel". True to go on (also when nobody else has it open).
GuiExport bool confirmOpen(const std::string& fileName, QWidget* parent);

/// Refreshes the markers and the status-bar line now (the heartbeat's work).
GuiExport void refreshNow();

/// The status-bar line's text (empty when nobody else has the active document open).
GuiExport std::string statusText();

}  // namespace DocumentPresenceGui
}  // namespace Gui
