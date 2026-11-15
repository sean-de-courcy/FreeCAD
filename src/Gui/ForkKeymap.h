// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCGlobal.h>
#include <Base/Parameter.h>

#include <QtCore/qnamespace.h>

class QKeyEvent;

namespace Gui
{

class Command;

/** The fork's default keymap: Onshape's keyboard shortcuts (FreeCAD-CH, ops#194).
 *
 * One table of command (or action) names and their default keys, applied when a command registers
 * (CommandManager::addCommand()). The keys it sets become the commands' defaults: a key the user
 * set is stored as a difference and kept, and Reset gives the table's key. Upstream's `sAccel`
 * stays in the source. The preference `General/Keymap`, "Onshape" (the default) or "FreeCAD",
 * switches between the table and upstream's keys; a change applies at once.
 *
 * Sub-actions that aren't commands (the draw styles, the workbenches' W, 1..9) take their key from
 * accel() when they are made. See notes/onshape-shortcuts.md.
 */
namespace ForkKeymap
{

/// The group holding the preference `Keymap` (Preferences/General); ShortcutManager observes it.
GuiExport ParameterGrp::handle preferenceGroup();

/// Whether the fork's keymap is the active one.
GuiExport bool isOnshape();

/** The active keymap's default key for the command or action \a name: the table's key under the
 * fork's keymap, "" where it takes the key away; nullptr where upstream's applies.
 */
GuiExport const char* accel(const char* name);

/// accel(name), or \a upstream where that is nullptr.
GuiExport const char* accel(const char* name, const char* upstream);

/// Gives a C++ command in the table the active keymap's default key (its `sAccel`).
void applyTo(Command* cmd);

/** Keeps the action of a command whose key must work while its toolbars are hidden (Pad and
 * Revolution in sketch edit) in a widget of its own (Command::initAction()).
 */
void actionCreated(Command* cmd);

/// Re-reads the preferences, and re-applies the defaults if the keymap or isMac() changed.
void reload();

/** Whether the Mac's keys apply: on macOS, and elsewhere where the hidden preference
 * `KeymapMacKeys` (General) is set, so the GUI tests can check them on Windows (ops#640 polish,
 * the Mac keys). They differ in three ways: Backspace deletes too (isDeleteKey()), the Part
 * selection filters take Control+Shift (Qt's Meta) for Shift+Option, which types a character on
 * the Mac, and the sketch tools' M takes Control for Cmd, whose Cmd+M minimizes the window.
 */
GuiExport bool isMac();

/** Whether  event is the Delete key alone: Delete, and with isMac() also Backspace, the Mac
 * keyboard's Delete key (Fn+Delete gives Delete). For the places that test the key themselves.
 */
GuiExport bool isDeleteKey(const QKeyEvent* event);

/** The modifier of a sketch tool's own key  letter ('M', 'U', ...) under the fork's keymap
 * (Sketcher's DrawSketchHandler::isToolKey()): Ctrl (Cmd on macOS), but Meta for M with isMac().
 */
GuiExport Qt::KeyboardModifier toolKeyModifier(char letter);

}  // namespace ForkKeymap

}  // namespace Gui
