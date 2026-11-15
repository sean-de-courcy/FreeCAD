// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   FreeCAD-CH (ops#796): the recompute result memo.                       *
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
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU     *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#ifndef APP_RECOMPUTEMEMO_H
#define APP_RECOMPUTEMEMO_H

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include <Base/Type.h>
#include <FCGlobal.h>

namespace App
{

class DocumentObject;
class DocumentObjectExecReturn;
class Property;
class PropertyContainer;

/**
 * @brief The recompute result memo (FreeCAD-CH, ops#796; notes/recompute-memo.md in the ops repo).
 *
 * A feature about to run whose inputs are all what they were before an earlier run doesn't run:
 * the properties that run wrote are pasted back. So an unsuppress, an undo, an edit back to an
 * earlier value and a recompute with nothing changed cost no geometry. In memory only.
 *
 * The inputs are the key: the object's own properties, the state of everything in its out-list
 * (recursively), and the plain properties of its in-list. Only objects of a type a module
 * vouches for are remembered (allow()), and only runs that wrote nothing but their own
 * properties.
 *
 * `User parameter:BaseApp/Preferences/Document/RecomputeMemo`: 0 off, 1 on, 2 verify (a hit
 * runs as well, and a difference is an error in the log).
 */
namespace RecomputeMemo
{

/// Whether an object of an allowed type is remembered
using Predicate = bool (*)(const DocumentObject*);

/// A module vouches for a type: its execute() reads only what the key covers
AppExport void allow(const Base::Type& type, Predicate predicate = nullptr);

/**
 * @brief How a property whose value is held by handle (a shape) is told apart.
 *
 * Such a property is never compared by its saved form in a key: its value has a stamp, the same
 * for the same value (identity), and a new one for any other.
 */
struct HandleHooks
{
    /// The bytes that are equal only for the very same value, while a copy of it is alive
    bool (*identity)(const Property&, std::string& bytes) {nullptr};
    /// A cheap digest that differs after nearly every real change
    bool (*quick)(const Property&, std::string& digest) {nullptr};
    /// The exact content
    bool (*content)(const Property&, std::string& digest) {nullptr};
};
AppExport void setHandleHooks(const Base::Type& propertyType, const HandleHooks& hooks);

/// The run in progress read something the key doesn't cover (its own last result): not kept
AppExport void noteImpureRun(const char* why);

struct Stats
{
    std::uint64_t runs {0};         ///< executes that ran (memo on or off)
    std::uint64_t hits {0};         ///< runs replaced by a paste
    std::uint64_t recorded {0};     ///< runs kept
    std::uint64_t notAllowed {0};   ///< objects of no allowed type
    std::uint64_t noKey {0};        ///< no key could be made
    std::uint64_t notRecorded {0};  ///< runs not kept (see notes())
    std::uint64_t canonical {0};    ///< results that took an earlier result's identity
    std::uint64_t verifyErrors {0}; ///< verify mode: differences found
    std::uint64_t flushes {0};      ///< a parameter changed: everything dropped
};
AppExport Stats stats(bool reset = false);
/// The reasons of the last runs not kept and of the verify errors (newest last)
AppExport std::vector<std::string> notes(bool reset = false);

/// Around a property's change (Property::hasSetValue()): what a run writes, and the serials
class AppExport ChangeScope
{
public:
    ChangeScope(const PropertyContainer* container, const Property* property);
    ~ChangeScope();
    ChangeScope(const ChangeScope&) = delete;
    ChangeScope& operator=(const ChangeScope&) = delete;

private:
    const PropertyContainer* container;
    const Property* property;
    bool own {false};
};

/// DocumentObject::touch(): a run that touches another object isn't kept
void objectTouched(const DocumentObject* object);
/// The object goes away
void forget(const DocumentObject* object);
/// execute(), or the paste of an earlier run's result (DocumentObject::recompute())
DocumentObjectExecReturn* run(
    DocumentObject* object,
    const std::function<DocumentObjectExecReturn*()>& execute
);

}  // namespace RecomputeMemo
}  // namespace App

#endif  // APP_RECOMPUTEMEMO_H
