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

#include <Base/Console.h>

#include "VarSetCopy.h"

using namespace App;

PROPERTY_SOURCE(App::VarSetCopy, App::VarSet)

namespace
{
const char* SourceKinds[] = {"FreeCAD document", "Onshape JSON", "None", nullptr};
}

VarSetCopy::VarSetCopy()
{
    // FreeCAD-CH ops#317: notes/variables-studio.md section 3.1. Shown read-only: only the
    // import, Refresh and Detach change them. Output: they say where the variables came from,
    // and setting them (the import's SourceKind after the recompute, Detach) doesn't touch the
    // copy.
    const char* group = "Source";
    const auto type = static_cast<PropertyType>(Prop_ReadOnly | Prop_Output);
    ADD_PROPERTY_TYPE(
        CopyFormat,
        (Format),
        group,
        type,
        "The format of this copy's properties"
    );
    ADD_PROPERTY_TYPE(SourceKind, (0L), group, type, "What the variables were copied from");
    SourceKind.setEnums(SourceKinds);
    SourceKind.setValue("None");
    ADD_PROPERTY_TYPE(SourcePath, (""), group, type, "The absolute path of the source file");
    ADD_PROPERTY_TYPE(
        SourceRelativePath,
        (""),
        group,
        type,
        "The source file's path relative to this document's file"
    );
    ADD_PROPERTY_TYPE(
        SourceObject,
        (""),
        group,
        type,
        "The source VarSet's internal name, or the studio entry's index in the JSON file (from 0)"
    );
    ADD_PROPERTY_TYPE(
        SourceEntries,
        (0L),
        group,
        type,
        "JSON: the number of studio entries in the file when it was read"
    );
    ADD_PROPERTY_TYPE(
        SourceStamp,
        (""),
        group,
        type,
        "SHA-256 of the source's variables as last read"
    );
    ADD_PROPERTY_TYPE(
        SourceRefreshed,
        (""),
        group,
        type,
        "When the source was last read (UTC)"
    );
    ADD_PROPERTY_TYPE(
        SourceExpressions,
        (),
        group,
        type,
        "Each source variable's expression as the source writes it"
    );
    ADD_PROPERTY_TYPE(
        NameMap,
        (),
        group,
        type,
        "Source names whose variable here has another name"
    );
    ADD_PROPERTY_TYPE(
        Bindings,
        (),
        group,
        type,
        "Names the source uses but doesn't define, and the FreeCAD paths chosen for them"
    );
    ADD_PROPERTY_TYPE(
        Skipped,
        (),
        group,
        type,
        "Source names chosen to be skipped: the source's variables not copied, and the names "
        "whose users weren't copied"
    );
    ADD_PROPERTY_TYPE(
        Orphans,
        (),
        group,
        type,
        "Variables removed at the source but still used here"
    );
}

bool VarSetCopy::isAttached() const
{
    return std::string(SourceKind.getValueAsString()) != "None";
}

void VarSetCopy::onChanged(const Property* prop)
{
    // Copied variables are read-only while the copy is attached: the ReadOnly status bit, saved
    // with each property and clearable, unlike addProperty's read_only. Following SourceKind
    // here makes the undo of Detach (or of a re-attach) give the bits back as well.
    if (prop == &SourceKind && !isRestoring()) {
        bool attached = isAttached();
        for (const auto& name : getDynamicPropertyNames()) {
            if (Property* variable = getPropertyByName(name.c_str())) {
                variable->setStatus(Property::ReadOnly, attached);
            }
        }
    }
    VarSet::onChanged(prop);
}

void VarSetCopy::onDocumentRestored()
{
    VarSet::onDocumentRestored();
    if (CopyFormat.getValue() > Format) {
        Base::Console().warning(
            "%s: saved by a newer FreeCAD-CH (copy format %ld; this build reads %ld)\n",
            getFullName().c_str(),
            CopyFormat.getValue(),
            Format
        );
    }
}
