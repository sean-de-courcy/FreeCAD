// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#pragma once

#include <string>

#include <QString>

#include <App/DocumentObserver.h>
#include <App/ReferenceRepair.h>

namespace PartDesignGui
{

/** The repair actions on one reference of an owner, shared by the References panel
 * (TaskReferences) and the reference fields (ReferenceField) (FreeCAD-CH, ops#150).
 *
 * The commands call the App functions (`App.acceptReference`, `App.repairReference`,
 * `App.markReferenceBroken`) on a reference named by its property and its position there, as the
 * user sees them (App::ReferenceRow::property and index). run() runs one as a command in the open
 * transaction and recomputes the document.
 */
class ReferenceActions
{
public:
    /// Keep the element the reference holds now; its warning goes.
    static std::string acceptCommand(const App::DocumentObject* owner,
                                     const std::string& property,
                                     int index);
    /// Take \a element (a candidate or an alternative) instead.
    static std::string useCommand(const App::DocumentObject* owner,
                                  const std::string& property,
                                  int index,
                                  const std::string& element);
    /// The guess is wrong: the owner fails until the reference is picked again.
    static std::string markBrokenCommand(const App::DocumentObject* owner,
                                         const std::string& property,
                                         int index);
    /// A new pick replaces the reference, whatever it holds (`force=True`).
    static std::string repickCommand(const App::DocumentObject* owner,
                                     const std::string& property,
                                     int index,
                                     const std::string& element);

    /// Runs \a command (Python) in the caller's transaction, or in one of its own when there is
    /// none (a feature's dialog opened without one): Cancel undoes it either way. Recomputes the
    /// document if it ran. False with the reason in \a error if the call failed.
    static bool run(App::DocumentObject* owner,
                    const std::string& command,
                    QString* error = nullptr);

    /// A row with a guess record the user can still accept or reject.
    static bool hasGuess(const App::ReferenceRow& row);
    /// The element a row holds now, or empty if it is missing.
    static std::string heldElement(const App::ReferenceRow& row);
    /// The element type of an element name: `Edge` for `Edge5` or `?Edge5`.
    static std::string elementType(const std::string& name);
    /// The element type of a stored sub: `Face` for `Pad.?Face3`, `Edge` for `;g3;SKT.Edge3`.
    static std::string subElementType(const std::string& sub);
};

/** Shows an object while its elements are picked or highlighted, as the body shows only one
 * solid: the body's shown feature is hidden while it is shown. restore() puts both back.
 */
class TargetDisplay
{
public:
    TargetDisplay() = default;
    TargetDisplay(const TargetDisplay&) = delete;
    TargetDisplay& operator=(const TargetDisplay&) = delete;
    ~TargetDisplay();

    void show(App::DocumentObject* target);
    void restore();
    App::DocumentObject* shown() const
    {
        return shownTarget.getObject();
    }
    /// Forgets what it changed, without restoring it (the document is gone).
    void forget();

private:
    App::DocumentObjectT shownTarget;
    App::DocumentObjectT hiddenFeature;
};

}  // namespace PartDesignGui
