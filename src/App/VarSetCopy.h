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

#include "PropertyStandard.h"
#include "VarSet.h"

namespace App
{

/** A static copy of variables from outside the document (FreeCAD-CH ops#317,
 * notes/variables-studio.md section 3.1).
 *
 * A VarSet whose variables, dynamic properties as in any VarSet, were copied from a source: an
 * Onshape variable studio export or a VarSet in a FreeCAD document. The static properties below
 * say where from and how it was read; they are part of the files saved with the beta (decision
 * 65): a change to them raises CopyFormat and comes with an upgrade. While the copy is attached
 * (SourceKind isn't "None") its variables are read-only; Detach (SourceKind "None") makes them
 * editable again. The import, Detach and Refresh are in freecad.variables.copies.
 */
class AppExport VarSetCopy: public App::VarSet
{
    PROPERTY_HEADER_WITH_OVERRIDE(App::VarSetCopy);

public:
    /// The format of this table; raised by any later change to it, with an upgrade.
    static constexpr long Format = 1;

    VarSetCopy();
    ~VarSetCopy() override = default;

    PropertyInteger CopyFormat;
    PropertyEnumeration SourceKind;
    PropertyString SourcePath;
    PropertyString SourceRelativePath;
    PropertyString SourceObject;
    PropertyInteger SourceEntries;
    PropertyString SourceStamp;
    PropertyString SourceRefreshed;
    PropertyMap SourceExpressions;
    PropertyMap NameMap;
    PropertyMap Bindings;
    PropertyStringList Skipped;
    PropertyStringList Orphans;

    /// Whether the copy still has a source (SourceKind isn't "None").
    bool isAttached() const;

protected:
    void onChanged(const Property* prop) override;
    void onDocumentRestored() override;
};

}  // namespace App
