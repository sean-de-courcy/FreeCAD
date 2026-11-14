// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2026 Crawlspace Habitats LLC                            *
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

#include <string>
#include <vector>
#include <FCGlobal.h>

namespace Base
{
class Writer;
class XMLReader;
}  // namespace Base

namespace Gui
{
class Document;

/**
 * Named views (Onshape's saved views): a camera kept under a name in the Gui document. They are
 * written into GuiDocument.xml as
 *   <NamedViews Count="n"> <View name=".." settings=".."/> ... </NamedViews>
 * after the <Camera> element, and read back when the document is restored.
 *
 * The lists live here, keyed by document, so that Document.h stays as it is (every Gui file
 * includes it): Document::Save/Restore call write/read, the destructor calls forget.
 * Changing the list marks the document modified.
 */
namespace NamedViews
{
/** The names in the order they were saved. */
GuiExport std::vector<std::string> names(const Document* doc);
GuiExport bool has(const Document* doc, const std::string& name);
/** The camera settings (the string View3DInventor::getCamera() gives), empty if there is none. */
GuiExport std::string settings(const Document* doc, const std::string& name);

/** Stores the settings under the name; a view of the same name is replaced (its place stays).
 *  False if the name is empty. */
GuiExport bool save(Document* doc, const std::string& name, const std::string& settings);
/** Saves the camera of the document's active 3D view. False without a view or a name. */
GuiExport bool saveCurrent(Document* doc, const std::string& name);
/** Sets the camera of the document's active 3D view. False without a view or the name. */
GuiExport bool restore(Document* doc, const std::string& name);
GuiExport bool remove(Document* doc, const std::string& name);
/** False if oldName is missing, newName is empty or another view has that name. */
GuiExport bool rename(Document* doc, const std::string& oldName, const std::string& newName);

/** Called when a document goes away. */
GuiExport void forget(const Document* doc);
/** Writes the element (nothing if there are no views). */
GuiExport void write(const Document* doc, Base::Writer& writer);
/** Reads the element; the reader stands on its start element. */
GuiExport void read(Document* doc, Base::XMLReader& reader);
}  // namespace NamedViews

}  // namespace Gui
