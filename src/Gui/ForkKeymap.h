// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

#include <FCGlobal.h>
#include <Base/Parameter.h>

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

/// Re-reads the preference, and re-applies the defaults if the keymap changed.
void reload();

}  // namespace ForkKeymap

}  // namespace Gui
