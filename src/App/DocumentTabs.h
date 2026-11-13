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

#include <string>
#include <vector>

#include <FCGlobal.h>

using PyObject = struct _object;

namespace App
{
class Document;
class DocumentObject;

/** Onshape's typed tabs (FreeCAD-CH, ops#640 rank 59, notes/onshape-tabs-design.md).
 *
 * A tab is an object the document already has: a Part Studio is a top-level App::Part (not an
 * Assembly), or the document's top level (the implicit studio, "Part Studio 1" by default); an
 * Assembly a root Assembly::AssemblyObject; a Drawing a TechDraw::DrawPage; a Variable Studio an
 * App::VarSet of exactly that type marked in the registry. No new type or property: the registry is
 * one key of the document's Meta map (metaKey()), holding the tab order (internal names, "*" for
 * the implicit studio), the Variable Studio marks and the implicit studio's label. Meta isn't part of
 * the undo history, so an undone tab keeps its place for a redo. Reading it never loses a tab:
 * stale names are skipped, tabs it doesn't list come last, in creation order.
 */
namespace DocumentTabs
{

enum class Kind
{
    PartStudio,
    Assembly,
    Drawing,
    VariableStudio,
};

struct Tab
{
    Kind kind;
    /// The tab's object; nullptr for the implicit studio (the document's top level)
    DocumentObject* object;

    /// The object's internal name, "*" for the implicit studio
    std::string name() const;
};

/// The Meta key of the registry: "FreeCADCH.Tabs"
AppExport const char* metaKey();

/// The name standing for the implicit studio in the order and in tab names: "*"
AppExport const char* implicitName();

/// Whether @p obj is a tab's object, and of which kind
AppExport bool isTabObject(const DocumentObject* obj, Kind* kind = nullptr);

/** The tab @p obj belongs to: the tab object holding it (itself for a tab object), or nullptr for
 * the implicit studio (the top level and what isn't in another tab).
 */
AppExport DocumentObject* tabOf(const DocumentObject* obj);

/// The tab name of tabOf(@p obj): its internal name, or "*"
AppExport std::string tabNameOf(const DocumentObject* obj);

/// Whether the implicit studio is a tab: the top level holds a 3D object of no other tab, no
/// other Part Studio exists, or the registry holds its label (named or shown once)
AppExport bool hasImplicitStudio(const Document* doc);

/// The document's tabs, in order
AppExport std::vector<Tab> tabs(const Document* doc);

/// The tab named @p name ("*" for the implicit studio); false where there is none
AppExport bool findTab(const Document* doc, const std::string& name, Tab& tab);

/// The tab's name in the bar: the object's Label, the registry's label for the implicit studio
AppExport std::string label(const Document* doc, const Tab& tab);

/// The implicit studio's label: the registry's, else the lowest "Part Studio N" no tab object has
AppExport std::string implicitLabel(const Document* doc);
/// Stores the implicit studio's label; from then on it is a tab even when empty, until deleted
AppExport void setImplicitLabel(Document* doc, const std::string& label);
/// Whether the registry holds the implicit studio's label
AppExport bool hasImplicitLabel(const Document* doc);

/// The stored order (as written, stale names included)
AppExport std::vector<std::string> order(const Document* doc);
AppExport void setOrder(Document* doc, const std::vector<std::string>& names);

/// Writes the current order with @p name moved right after @p after (or last, where @p after isn't
/// a tab)
AppExport void placeAfter(Document* doc, const std::string& name, const std::string& after);

AppExport bool isVariableStudio(const DocumentObject* obj);
/// Marks or unmarks an App::VarSet (of exactly that type) as a Variable Studio
AppExport void setVariableStudio(DocumentObject* varSet, bool marked);
/// FreeCAD-CH ops#721: the attached copies (App::VarSetCopy) in @a studio's reference list, in
/// list order (StudioPosition, then document order); empty unless @a studio is a Variable Studio
/// (notes/variable-studio-references.md section 1)
AppExport std::vector<DocumentObject*> variableReferences(const DocumentObject* studio);
/// The Variable Studio whose reference list holds @a copy, or nullptr (unlisted, detached, or a
/// studio gone or unmarked)
AppExport DocumentObject* studioOf(const DocumentObject* copy);

/// The lowest free "<base> N" (N from 1) among the labels of the document's tabs
AppExport std::string nextLabel(const Document* doc, const std::string& base);

/// What deleting the tab removes: its object (the implicit studio: the top level's 3D objects of
/// no other tab) and everything inside, origins included
AppExport std::vector<DocumentObject*> members(const Document* doc, const Tab& tab);

/// The objects outside the tab that use one of its members (a link in an assembly, an expression)
AppExport std::vector<DocumentObject*> dependents(const Document* doc, const Tab& tab);

/// Removes the tab's members from the document (in the caller's transaction)
AppExport void removeTab(Document* doc, const Tab& tab);

/** Why the tab can't be duplicated, "" when it can (slice 2): only a Part Studio that is an
 * App::Part and an Assembly duplicate. A Part Studio that uses an object outside it other than a
 * VarSet (a Derived source, a binder of another studio) is refused, the object named; an
 * Assembly's links stay pointing at the same studios
 */
AppExport std::string duplicateRefusal(const Document* doc, const Tab& tab);

/** Onshape's "Duplicate": a copy of the tab, not linked to the original, as a new tab right of it
 * labelled "<label> (N)" (the lowest free N from 1); in the caller's transaction. Returns the new
 * tab object; throws Base::RuntimeError with duplicateRefusal() where it can't
 */
AppExport DocumentObject* duplicate(Document* doc, const Tab& tab);

/// The label duplicate() gives a copy of the tab: "<label> (N)", the lowest N no tab has
AppExport std::string duplicateLabel(const Document* doc, const Tab& tab);

/** What Export writes for the tab: a Part Studio's visible parts (Bodies, solids and links, not
 * sketches or datums; through plain groups), an Assembly's object itself; empty for the others
 */
AppExport std::vector<DocumentObject*> exportObjects(const Document* doc, const Tab& tab);

/** Onshape's "Export" to STEP: exportObjects() through @p module's export(objects, path,
 * exportHidden=False), "Import" (headless) or "ImportGui" (the colours too). Throws
 * Base::Exception when there's nothing to write or the writer fails
 */
AppExport void exportTab(
    const Document* doc,
    const Tab& tab,
    const std::string& path,
    const char* module = "Import"
);

/// The Python module FreeCAD.DocumentTabs
AppExport PyObject* initModule();

inline std::string Tab::name() const
{
    return tabNameOf(object);  // a tab object's own name, "*" for nullptr
}

}  // namespace DocumentTabs
}  // namespace App
