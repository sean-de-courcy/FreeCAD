// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Jürgen Riegel <juergen.riegel@web.de>              *
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


#include <algorithm>
#include <set>
#include <string>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentPy.h>
#include <App/DocumentObjectPy.h>
#include <App/Part.h>
#include <Base/GeometryPyCXX.h>
#include <Base/Interpreter.h>
#include <Base/VectorPy.h>
#include <Base/Tools.h>
#include <Mod/Part/App/BodyBase.h>
#include <Mod/Part/App/PartFeature.h>

#include <App/ElementNamingUtils.h>
#include <App/NameTable.h>

#include "Body.h"
#include "Derived.h"
#include "FeatureDressUp.h"
#include "FeatureBase.h"
#include "FeatureBoolean.h"
#include "FeatureDeletePart.h"
#include "FeatureSketchBased.h"
#include "FeatureSplit.h"
#include "Pieces.h"
#include "Studio.h"
#include "StudioVariables.h"
#include "StudioConfig.h"
#include "StudioEdit.h"
#include "StudioList.h"


namespace PartDesign
{
// FeatureDressUp.cpp (FreeCAD-CH ops#654 P8a; declared where used)
struct StudioDressUpPick
{
    std::string text;
    std::string id;
    std::vector<std::pair<Body*, std::vector<std::string>>> found;
};
PartDesignExport std::vector<StudioDressUpPick> studioDressUpPicks(const DressUp* owner);
}  // namespace PartDesign

namespace PartDesign
{
// FreeCAD-CH (ops#640 round 5): Body.cpp's New part rule (no header names it)
PartDesignExport std::string newPartRefusal(const App::DocumentObject* feature, bool ignoreMerge);
// FreeCAD-CH (ops#654 P5, P6a): StudioList.cpp's live parts and Boolean studio features
PartDesignExport std::vector<Body*> studioLivePartsAt(const StudioList* list, int index);
PartDesignExport void studioBooleanParts(const App::DocumentObject* owner,
                                         std::vector<Body*>& steps,
                                         std::vector<Body*>& tools,
                                         std::vector<Body*>& both);
PartDesignExport const App::DocumentObject* studioConsumerOf(const Body* body, int index);
// FreeCAD-CH (ops#654 10.13): StudioList.cpp's Merge with all
PartDesignExport bool studioSetMergeAll(App::DocumentObject* owner, bool on, std::string* why);

class Module: public Py::ExtensionModule<Module>
{
public:
    Module()
        : Py::ExtensionModule<Module>("_PartDesign")
    {
        add_varargs_method("makeFilletArc", &Module::makeFilletArc, "makeFilletArc(...) -- Fillet arc.");
        add_varargs_method(
            "studioOf",
            &Module::studioOf,
            "studioOf(obj) -- The studio of obj's Body: its App::Part, the document at the top "
            "level, or None (no Body, or a Body placed directly in an Assembly)."
        );
        add_varargs_method(
            "isStudioPick",
            &Module::isStudioPick,
            "isStudioPick(owner, obj, subname='') -- Whether owner may link the pick obj/subname "
            "directly: one Body, or two Bodies of one studio, and no App::Link on the path."
        );
        add_varargs_method(
            "isStudioProfile",
            &Module::isStudioProfile,
            "isStudioProfile(owner, obj, subname='') -- Whether the pick may be the Profile of "
            "owner (a profile feature, or the Body of a new one) across Bodies of one studio."
        );
        add_varargs_method(
            "newPartFrom",
            &Module::newPartFrom,
            "newPartFrom(feature) -- Moves feature, its Profile sketch if nothing that stays uses "
            "it, and the later features of its Body that work on its own material (in order), into "
            "a new Body placed as the old one, in the same container; its Merge goes first. The "
            "features that stay close their chain over it. Refused (newPartRefusal) when a feature "
            "can't be told apart. Returns the new Body; no recompute."
        );
        add_varargs_method(
            "newPartRefusal",
            &Module::newPartRefusal,
            "newPartRefusal(feature, ignoreMerge=False) -- Why newPartFrom(feature) would refuse, or "
            "'' when it is allowed. With ignoreMerge, the feature's Merge counts as gone."
        );
        add_varargs_method(
            "addToPart",
            &Module::addToPart,
            "addToPart(feature, body) -- newPartFrom the other way: moves feature, its Body's first "
            "solid, and every other member of that Body (its sketch, what builds on it) in order "
            "into body, another part of its studio, where the studio's history has the feature, "
            "and removes the empty Body. Returns body; no recompute."
        );
        add_varargs_method(
            "addToPartRefusal",
            &Module::addToPartRefusal,
            "addToPartRefusal(feature, body) -- Why addToPart(feature, body) would refuse, or '' "
            "when it is allowed."
        );
        add_varargs_method(
            "deletePart",
            &Module::deletePart,
            "deletePart(body) -- Deletes the part body from its bar on, as Onshape's Delete part: a "
            "DeletePart feature at the bar, its Tip, whose shape is empty. Its features stay; "
            "rolling above it, or deleting it, brings the part back. Returns it; no recompute."
        );
        add_varargs_method(
            "removeEmptyPart",
            &Module::removeEmptyPart,
            "removeEmptyPart(body) -- A Body of a studio with no solid feature left (its New part "
            "feature deleted): its sketches and datums go to another Body of the studio where the "
            "history has them, and the Body is removed. Returns the Body that took them, or None "
            "when nothing was done; no recompute."
        );
        add_varargs_method(
            "makeSiblings",
            &Module::makeSiblings,
            "makeSiblings(feature, bodies) -- Makes the siblings of the subtractive feature the "
            "ones in bodies, other parts of its studio: one feature of its type per Body, on its "
            "profile, its parameters bound to it by expression and its links copied. Adds the "
            "missing ones, deletes the others, copies the links again. Returns them; no recompute."
        );
        add_varargs_method(
            "siblingsOf",
            &Module::siblingsOf,
            "siblingsOf(feature) -- The siblings that follow feature."
        );
        add_varargs_method(
            "unlinkSibling",
            &Module::unlinkSibling,
            "unlinkSibling(sibling) -- Makes the sibling independent: its expressions on its "
            "primary and its SiblingOf are cleared, its values stay."
        );
        add_varargs_method(
            "makeMerge",
            &Module::makeMerge,
            "makeMerge(at, bodies) -- Merges the bodies, other parts of the studio, into the part "
            "of at: a solid feature (the Merge goes right after it) or a Body (at its Tip). The "
            "Merge is a Fuse of their last solid features; each merged Body gets MergedInto and is "
            "hidden. Returns the Merge; no recompute."
        );
        add_varargs_method(
            "setMergeScope",
            &Module::setMergeScope,
            "setMergeScope(feature, bodies) -- The merge scope of the solid feature (Onshape's "
            "Extrude): bodies, other parts of the studio, are merged right after it, and the parts "
            "it merged that aren't in bodies are parts again. Changes the Merge after it in place, "
            "makes one, or with no bodies deletes it; the Merge is accepted. Returns the Merge or "
            "None; no recompute."
        );
        add_varargs_method(
            "mergeAfter",
            &Module::mergeAfter,
            "mergeAfter(feature) -- The Merge right after the solid feature, based on it, or None."
        );
        add_varargs_method(
            "consumerOf",
            &Module::consumerOf,
            "consumerOf(body) -- The Boolean that consumes the part body, one of its tools (Keep "
            "tools off, in effect, not a Merge, the tool not one a Union left separate), or None."
        );
        add_varargs_method(
            "split",
            &Module::split,
            "split(body, tool, side='Front') -- Splits the part body by the plane tool: an origin "
            "plane, a datum plane, or (feature, 'FaceN') for a planar face. A Split at its end "
            "keeps side (Front: where the plane's normal points, or Back); a new part placed as "
            "body gets the other side, from a Split that follows the first. Returns the new "
            "Body; no recompute."
        );
        add_varargs_method(
            "studioOriginFeature",
            &Module::studioOriginFeature,
            "studioOriginFeature(owner, feature) -- owner's own origin feature standing for "
            "feature, an origin feature of another Body of the studio, or None."
        );
        add_varargs_method(
            "studioSequence",
            &Module::studioSequence,
            "studioSequence(studio) -- The features of every Body of the studio (a document: its "
            "top level, or an App::Part) in history order: after what they read in other Bodies "
            "and after their Body's earlier members, the oldest first where that leaves a choice."
        );
        add_varargs_method(
            "variablePosition",
            &Module::variablePosition,
            "variablePosition(varset, name) -- The feature of studioSequence the Part Studio "
            "variable name of varset follows in the history, or None at its start (ops#723)."
        );
        add_varargs_method(
            "setVariablePosition",
            &Module::setVariablePosition,
            "setVariablePosition(varset, name[, after]) -- Places the Part Studio variable name of "
            "varset (a VarSet in an App::Part) right after the feature after of studioSequence, or "
            "at the start for None. Features above it can't use it; no transaction, no recompute."
        );
        add_varargs_method(
            "rollStudioTo",
            &Module::rollStudioTo,
            "rollStudioTo(studio, feature) -- Moves the bar of every Body of the studio after its "
            "last solid feature at or above feature in studioSequence (None: to its top). No "
            "transaction, no recompute."
        );
        add_varargs_method(
            "rollStudioToEnd",
            &Module::rollStudioToEnd,
            "rollStudioToEnd(studio) -- Moves the bar of every Body of the studio to its end."
        );
        add_varargs_method(
            "isStudioRolledBack",
            &Module::isStudioRolledBack,
            "isStudioRolledBack(studio) -- Whether some Body of the studio is rolled back."
        );
        add_varargs_method(
            "studioBarAfter",
            &Module::studioBarAfter,
            "studioBarAfter(studio[, hint]) -- The feature of studioSequence the studio's bar "
            "follows (None: the top): the row before the first one that is held or waits below "
            "the bar (a sketch or datum after its Body's bar whose users are all held). hint, "
            "the feature (None: the top) the bar was last moved after, is kept when only "
            "sketches and datums lie between."
        );
        add_varargs_method(
            "moveInStudio",
            &Module::moveInStudio,
            "moveInStudio(studio, features, after[, bar]) -- Drags features (one, or several of "
            "one Body) to after the feature after (None: the top) in the studio's history and "
            "saves the order: inside their Body through reorderObject (the park), across Bodies "
            "refused where a read between Bodies would break. With the studio rolled back, the bar "
            "stays after bar (None: the top; default: the feature it follows). Returns whether "
            "anything changed. No transaction, no recompute."
        );
        // FreeCAD-CH (ops#640 round 6): Onshape's Derived inside one document (Derived.h)
        add_varargs_method(
            "derivedStudios",
            &Module::derivedStudios,
            "derivedStudios(doc) -- The studios of doc that hold a part to derive: the document "
            "(its top level, Part Studio 1) when it has one, then its App::Parts."
        );
        add_varargs_method(
            "studioLabel",
            &Module::studioLabel,
            "studioLabel(studio) -- A studio's name: an App::Part's Label, the implicit studio's "
            "label for a document (its top level; Part Studio 1 by default)."
        );
        add_varargs_method(
            "derivableParts",
            &Module::derivableParts,
            "derivableParts(studio) -- The parts of the studio a Derived feature can bring in: its "
            "Bodies with a shape that no Delete part deleted."
        );
        add_varargs_method(
            "makeDerived",
            &Module::makeDerived,
            "makeDerived(studio, bodies) -- A Derived feature in the studio (a document: its top "
            "level) of bodies, parts of one other studio: per part a Body built on a binder of it. "
            "Returns the lead, whose row stands for the feature. No transaction, no recompute."
        );
        add_varargs_method(
            "editDerived",
            &Module::editDerived,
            "editDerived(lead, bodies) -- The Derived feature brings in bodies instead. Returns the "
            "lead after the edit. No transaction, no recompute."
        );
        add_varargs_method(
            "isDerivedCopy",
            &Module::isDerivedCopy,
            "isDerivedCopy(obj) -- Whether obj is a derived copy: a Part::Feature holding a part of "
            "another document's saved studio (DerivedSourcePart), which freecad.derived makes."
        );
        add_varargs_method(
            "makeDerivedCopies",
            &Module::makeDerivedCopies,
            "makeDerivedCopies(studio, copies) -- A Derived feature in the studio (a document: its "
            "top level) on derived copies it holds, of one studio of one file: per copy a Body "
            "built on it. Returns the lead. No transaction, no recompute."
        );
        add_varargs_method(
            "editDerivedCopies",
            &Module::editDerivedCopies,
            "editDerivedCopies(lead, copies) -- The Derived feature on derived copies brings in "
            "copies instead. Returns the lead after the edit. No transaction, no recompute."
        );
        add_varargs_method(
            "deleteDerivedParts",
            &Module::deleteDerivedParts,
            "deleteDerivedParts(lead) -- Removes what the Derived feature made besides lead: its "
            "other members, the binders, the Bodies left empty (lead's too: lead is then in no "
            "Body, for the caller to remove). No transaction, no recompute."
        );
        add_varargs_method(
            "derivedLead",
            &Module::derivedLead,
            "derivedLead(obj) -- The lead of obj's Derived feature, or None."
        );
        add_varargs_method(
            "derivedMembers",
            &Module::derivedMembers,
            "derivedMembers(lead) -- The members of the Derived feature, lead last."
        );
        add_varargs_method(
            "derivedSource",
            &Module::derivedSource,
            "derivedSource(member) -- The part a Derived feature's member copies, or None when it "
            "is missing."
        );
        // FreeCAD-CH (ops#654): the studio's list, its projection and reconcile
        add_varargs_method(
            "studioList",
            &Module::studioList,
            "studioList(studio=None, create=False) -- The history list of studio (an App::Part, a "
            "document for its top level, None for the active document's), or None; with create, "
            "made (adopted from studioSequence) when missing. No transaction, no recompute."
        );
        add_varargs_method(
            "studioInsert",
            &Module::studioInsert,
            "studioInsert(entry, index=-1) -- Puts entry (a studio feature, or a member of a Body) "
            "into its studio's list at index (-1: at the bar) and reconciles. Returns the list."
        );
        add_varargs_method(
            "studioRemove",
            &Module::studioRemove,
            "studioRemove(entry) -- Takes entry out of its list (and out of its Body), deletes its "
            "steps and reconciles; entry itself is the caller's to delete."
        );
        add_varargs_method(
            "studioMove",
            &Module::studioMove,
            "studioMove(entry, index) -- Moves entry to index of its list and reconciles."
        );
        add_varargs_method(
            "studioSetBar",
            &Module::studioSetBar,
            "studioSetBar(anyEntry, index) -- Puts the bar of the list anyEntry names (an entry, "
            "the list, a Body or a studio) before index (-1: the end) and reconciles."
        );
        add_varargs_method(
            "studioSetScope",
            &Module::studioSetScope,
            "studioSetScope(owner, bodies) -- Sets the studio feature's scope to the part ids of "
            "bodies, in order, and reconciles."
        );
        add_varargs_method(
            "studioSetScopeIds",
            &Module::studioSetScopeIds,
            "studioSetScopeIds(owner, ids) -- Sets the studio feature's scope to the part ids, in "
            "order, and reconciles."
        );
        add_varargs_method(
            "studioScopeIds",
            &Module::studioScopeIds,
            "studioScopeIds(owner) -- The part ids of the studio feature's scope, in order."
        );
        add_varargs_method(
            "studioScopeOf",
            &Module::studioScopeOf,
            "studioScopeOf(owner) -- The Bodies the scope resolves to at the owner's place."
        );
        add_varargs_method(
            "studioPartId",
            &Module::studioPartId,
            "studioPartId(body) -- The part id of body (its name until adopted)."
        );
        add_varargs_method(
            "studioSuppress",
            &Module::studioSuppress,
            "studioSuppress(entry, on) -- Suppresses or unsuppresses entry and reconciles."
        );
        add_varargs_method(
            "configStudio",
            &Module::guarded<&Module::configStudio>,
            "configStudio(studio, create=False) -- The studio's StudioConfig (ops#671), or None."
        );
        add_varargs_method(
            "configAddList",
            &Module::guarded<&Module::configAddList>,
            "configAddList(studio, name, rowNames) -- Adds a List input; returns its id."
        );
        add_varargs_method(
            "configAddCheckbox",
            &Module::guarded<&Module::configAddCheckbox>,
            "configAddCheckbox(studio, name, default=True) -- Adds a Checkbox input; returns its id."
        );
        add_varargs_method(
            "configAddVariable",
            &Module::guarded<&Module::configAddVariable>,
            "configAddVariable(studio, name, type, default, min=None, max=None) -- Adds a configuration Variable (#name); returns its id."
        );
        add_varargs_method(
            "configAddRow",
            &Module::guarded<&Module::configAddRow>,
            "configAddRow(studio, input, name) -- Adds a row to a List input; returns its id."
        );
        add_varargs_method(
            "configRenameRow",
            &Module::guarded<&Module::configRenameRow>,
            "configRenameRow(studio, input, row, name) -- Renames a row (its id stays)."
        );
        add_varargs_method(
            "configRemoveRow",
            &Module::guarded<&Module::configRemoveRow>,
            "configRemoveRow(studio, input, row) -- Removes a row and its cells."
        );
        add_varargs_method(
            "configSetDefaultRow",
            &Module::guarded<&Module::configSetDefaultRow>,
            "configSetDefaultRow(studio, input, row) -- Makes row the List's default."
        );
        add_varargs_method(
            "configMoveRow",
            &Module::guarded<&Module::configMoveRow>,
            "configMoveRow(studio, input, row, index) -- Moves a List row to position index (0 first)."
        );
        add_varargs_method(
            "configRenameInput",
            &Module::guarded<&Module::configRenameInput>,
            "configRenameInput(studio, input, name) -- Renames an input (its id stays; a Variable's #name too)."
        );
        add_varargs_method(
            "configMoveInput",
            &Module::guarded<&Module::configMoveInput>,
            "configMoveInput(studio, input, index) -- Moves an input to position index (0 first)."
        );
        add_varargs_method(
            "configSetCheckboxDefault",
            &Module::guarded<&Module::configSetCheckboxDefault>,
            "configSetCheckboxDefault(studio, input, value) -- Sets a Checkbox input's default."
        );
        add_varargs_method(
            "configEditVariable",
            &Module::guarded<&Module::configEditVariable>,
            "configEditVariable(studio, name, default, min=None, max=None) -- Sets a configuration "
            "Variable's default and bounds (None: no bound); its type stays."
        );
        add_varargs_method(
            "configRemoveInput",
            &Module::guarded<&Module::configRemoveInput>,
            "configRemoveInput(studio, input) -- Removes an input; what it configured keeps its active value."
        );
        add_varargs_method(
            "configConfigure",
            &Module::guarded<&Module::configConfigure>,
            "configConfigure(obj, path, input) -- Configures obj's path with a List or Checkbox input."
        );
        add_varargs_method(
            "configUnconfigure",
            &Module::guarded<&Module::configUnconfigure>,
            "configUnconfigure(obj, path) -- Unconfigures obj's path (it keeps the active cell)."
        );
        add_varargs_method(
            "configSetCell",
            &Module::guarded<&Module::configSetCell>,
            "configSetCell(obj, path, row, text) -- Writes a configured path's cell (row empty: the active one)."
        );
        add_varargs_method(
            "configConfigureSuppression",
            &Module::guarded<&Module::configConfigureSuppression>,
            "configConfigureSuppression(owner, input) -- Configures owner's suppression."
        );
        add_varargs_method(
            "configUnconfigureSuppression",
            &Module::guarded<&Module::configUnconfigureSuppression>,
            "configUnconfigureSuppression(owner) -- Unconfigures owner's suppression."
        );
        add_varargs_method(
            "configSetSuppressionCell",
            &Module::guarded<&Module::configSetSuppressionCell>,
            "configSetSuppressionCell(owner, row, suppressed) -- Writes a suppression cell (row empty: the active one)."
        );
        add_varargs_method(
            "configIsConfigured",
            &Module::guarded<&Module::configIsConfigured>,
            "configIsConfigured(obj, path=None) -- Whether obj's path (None: its suppression) is configured."
        );
        add_varargs_method(
            "configInputOf",
            &Module::guarded<&Module::configInputOf>,
            "configInputOf(obj, path=None) -- The name of the input that configures obj's path (None: "
            "its suppression), or ''."
        );
        add_varargs_method(
            "configMenuItems",
            &Module::guarded<&Module::configMenuItems>,
            "configMenuItems(obj, path=None) -- The configuration items of the field's context menu "
            "(None: the suppression's), as (label, action, input id) tuples."
        );
        add_varargs_method(
            "configEntries",
            &Module::guarded<&Module::configEntries>,
            "configEntries(studio=None) -- The live table entries: dicts with object, path (None: a "
            "suppression), input (its id) and cells (row id or 'true'/'false' -> text); stale ones are left out."
        );
        add_varargs_method(
            "configSetActive",
            &Module::guarded<&Module::configSetActive>,
            "configSetActive(studio, values) -- The switch: values maps inputs (id or name) to rows, bools or values; rebinds, reconciles, makes pieces, recomputes."
        );
        add_varargs_method(
            "configKey",
            &Module::guarded<&Module::configKey>,
            "configKey(studio, values=None) -- The canonical key of values (None: the active configuration)."
        );
        add_varargs_method(
            "configDefaultKey",
            &Module::guarded<&Module::configDefaultKey>,
            "configDefaultKey(studio) -- The key of every input at its default."
        );
        add_varargs_method(
            "configReconcile",
            &Module::guarded<&Module::configReconcile>,
            "configReconcile(studio, checkOnly=True) -- Rebinds from the active cells (checkOnly: only reports what differs)."
        );
        add_varargs_method(
            "configSetReaderKey",
            &Module::guarded<&Module::configSetReaderKey>,
            "configSetReaderKey(reader, source, values) -- The configuration a Link or binder outside the studio shows."
        );
        add_varargs_method(
            "configReaderError",
            &Module::guarded<&Module::configReaderError>,
            "configReaderError(reader, source) -- Why reader may not show source now (empty: it may)."
        );
        add_varargs_method(
            "studioReconcile",
            &Module::studioReconcile,
            "studioReconcile(list) -- Makes every Body's chain the list's projection: adopts the "
            "members it doesn't hold, makes, removes and reorders steps, sets their values and "
            "each Body's Tip. No transaction, no recompute."
        );
        add_varargs_method(
            "studioProject",
            &Module::studioProject,
            "studioProject(list) -- The projection: {bodyName: [(entryName, isStep, suppressed, "
            "held), ...]}; raises with the reasons when the list can't be projected."
        );
        add_varargs_method(
            "studioStepOf",
            &Module::studioStepOf,
            "studioStepOf(owner, body) -- The step of the studio feature in body, or None."
        );
        // FreeCAD-CH ops#654 S2: a New result
        add_varargs_method(
            "studioNewPart",
            &Module::studioNewPart,
            "studioNewPart(owner) -- A new part made by the studio feature (a New result): a "
            "Body in its studio with the part id '<owner>:<n>' and StudioMadeBy the owner, whose "
            "first step is the owner's tool. The id joins the owner's scope, its Operation becomes "
            "Union, and the list is reconciled. No transaction, no recompute. Returns the Body."
        );
        // FreeCAD-CH ops#654 P5, P6a: Booleans between parts, live parts
        add_varargs_method(
            "studioLiveParts",
            &Module::studioLiveParts,
            "studioLiveParts(anyEntry, index=-1) -- The parts (Bodies) of the studio anyEntry "
            "names (an entry, the list, a Body or a studio) that are live just before the list "
            "entry at index (-1: at the bar): not merged away, not consumed by a Boolean before "
            "it, not made by it or later."
        );
        add_varargs_method(
            "studioSetToolIds",
            &Module::studioSetToolIds,
            "studioSetToolIds(boolean, ids) -- Sets the Boolean studio feature's tool parts "
            "(StudioTools) to the part ids, in order, and reconciles."
        );
        add_varargs_method(
            "studioBooleanParts",
            &Module::studioBooleanParts,
            "studioBooleanParts(boolean) -- (steps, tools): the parts a Boolean studio feature "
            "has steps in and its tool parts, resolved at its place."
        );
        add_varargs_method(
            "studioConsumerOf",
            &Module::studioConsumerOf,
            "studioConsumerOf(body, index=-1) -- The Boolean studio feature that consumes body "
            "before the list entry at index (-1: at the bar), or None."
        );
        // FreeCAD-CH ops#654 P6p: pieces and leftovers become parts at command time
        add_varargs_method(
            "studioMakePieces",
            &Module::studioMakePieces,
            "studioMakePieces(entry) -- The piece command: recomputes, makes every solid of the "
            "entry's results that no part holds (a piece of a part it splits, a solid of its tool "
            "touching no part of its scope) a new part, deletes the parts it made that hold "
            "nothing else, reconciles and recomputes. In the caller's transaction. Returns the "
            "new Bodies."
        );
        // FreeCAD-CH ops#654 10.13: an Add merges the parts its tool joins
        add_varargs_method(
            "studioSetMergeAll",
            &Module::studioSetMergeAll,
            "studioSetMergeAll(owner, on) -- Sets the studio feature's Merge with all (its scope "
            "is every part live at its place, ordered by each part's first feature in the "
            "history) and reconciles its list. No transaction, no recompute."
        );
        add_varargs_method(
            "studioPieceName",
            &Module::studioPieceName,
            "studioPieceName(body) -- The custom name a piece shows: its parent's, up the "
            "lineage; empty when there is none."
        );
        // FreeCAD-CH ops#654 P8a: one fillet or chamfer over several parts
        add_varargs_method(
            "studioPickId",
            &Module::studioPickId,
            "studioPickId(obj, element) -- The pick of element (e.g. 'Edge3') of obj's shape (a "
            "Body, or a feature of one) as a dress-up studio feature stores it in StudioPickIds: "
            "'<part id>|<element name>', the name interned (App.expandMappedName() expands it)."
        );
        add_varargs_method(
            "studioSetPickIds",
            &Module::studioSetPickIds,
            "studioSetPickIds(owner, picks) -- Sets the Fillet or Chamfer studio feature's picks "
            "(StudioPickIds) and reconciles its list: its scope is the parts they resolve to. No "
            "transaction, no recompute."
        );
        add_varargs_method(
            "studioDressUpPicks",
            &Module::studioDressUpPicks,
            "studioDressUpPicks(owner) -- Each pick of the Fillet or Chamfer studio feature found "
            "at its place: [(pick, [(body, [subname, ...]), ...]), ...]; a pick found nowhere has "
            "no body."
        );
        initialize("This module is the PartDesign module.");  // register with Python
    }

private:
    /// A configuration call: a C++ exception that is no Python one (a malformed saved value's
    /// json type error, ops#671 review) becomes a Python RuntimeError instead of escaping
    template<Py::Object (Module::*F)(const Py::Tuple&)>
    Py::Object guarded(const Py::Tuple& args)
    {
        try {
            return (this->*F)(args);
        }
        catch (const Py::BaseException&) {
            throw;
        }
        catch (const Base::Exception&) {
            throw;  // as before
        }
        catch (const std::exception& e) {
            throw Py::RuntimeError(std::string("The configuration data can't be read: ") + e.what());
        }
    }

    // A deleted object, or one no longer in a document, raises ReferenceError
    static App::DocumentObject* objectArg(PyObject* obj)
    {
        auto pyObj = static_cast<App::DocumentObjectPy*>(obj);
        // PyObjectBase's isValid(): DocumentObjectPy hides it with the Python method
        App::DocumentObject* object =
            pyObj->Base::PyObjectBase::isValid() ? pyObj->getDocumentObjectPtr() : nullptr;
        if (!object || !object->isAttachedToDocument() || !object->getDocument()) {
            PyErr_SetString(PyExc_ReferenceError, "The object is deleted or not in a document");
            throw Py::Exception();
        }
        return object;
    }

    // FreeCAD-CH (ops#325): the studio predicates, for the tests and for scripts
    Py::Object studioOf(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        App::DocumentObject* obj = objectArg(pObj);
        App::Part* studio = nullptr;
        if (!Part::BodyBase::studioOf(Part::BodyBase::bodyOfObject(obj), studio)) {
            return Py::None();
        }
        if (studio) {
            return Py::asObject(studio->getPyObject());
        }
        return Py::asObject(obj->getDocument()->getPyObject());
    }

    Py::Object isStudioPick(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pObj;
        const char* subname = "";
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!|s",
                &(App::DocumentObjectPy::Type),
                &pOwner,
                &(App::DocumentObjectPy::Type),
                &pObj,
                &subname
            )) {
            throw Py::Exception();
        }
        return Py::Boolean(
            Part::BodyBase::isStudioPick(objectArg(pOwner), objectArg(pObj), subname)
        );
    }

    // FreeCAD-CH (ops#325 2a): New part
    Py::Object newPartFrom(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        try {
            return Py::asObject(Body::newPartFrom(objectArg(pObj))->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640 round 5): newPartFrom's rule, for the dialog's rows and the tests
    Py::Object newPartRefusal(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pIgnore = Py_False;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!|O!",
                &(App::DocumentObjectPy::Type),
                &pObj,
                &PyBool_Type,
                &pIgnore
            )) {
            throw Py::Exception();
        }
        try {
            return Py::String(PartDesign::newPartRefusal(objectArg(pObj), pIgnore == Py_True));
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640): Add to part, New part the other way
    Py::Object addToPart(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBody;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!",
                &(App::DocumentObjectPy::Type),
                &pObj,
                &(App::DocumentObjectPy::Type),
                &pBody
            )) {
            throw Py::Exception();
        }
        auto body = freecad_cast<Body*>(objectArg(pBody));
        if (!body) {
            PyErr_SetString(PyExc_TypeError, "Expected a PartDesign Body");
            throw Py::Exception();
        }
        try {
            return Py::asObject(Body::addToPart(objectArg(pObj), body)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640): addToPart's rule, for the dialog's rows and the tests
    Py::Object addToPartRefusal(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBody;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!",
                &(App::DocumentObjectPy::Type),
                &pObj,
                &(App::DocumentObjectPy::Type),
                &pBody
            )) {
            throw Py::Exception();
        }
        auto body = freecad_cast<Body*>(objectArg(pBody));
        if (!body) {
            PyErr_SetString(PyExc_TypeError, "Expected a PartDesign Body");
            throw Py::Exception();
        }
        try {
            return Py::String(Body::addToPartRefusal(objectArg(pObj), body));
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640 rank 30, blind test F50): a deleted New part's empty Body
    Py::Object removeEmptyPart(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        auto body = freecad_cast<Body*>(objectArg(pObj));
        if (!body) {
            PyErr_SetString(PyExc_TypeError, "Expected a PartDesign Body");
            throw Py::Exception();
        }
        try {
            Body* target = DeletePart::removeEmptyPart(body);
            return target ? Py::asObject(target->getPyObject()) : Py::None();
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#635): Delete part
    Py::Object deletePart(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        auto body = freecad_cast<Body*>(objectArg(pObj));
        if (!body) {
            PyErr_SetString(PyExc_TypeError, "Expected a PartDesign Body");
            throw Py::Exception();
        }
        try {
            return Py::asObject(DeletePart::deletePart(body)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#325 3a): one cut through several parts
    static FeatureAddSub* addSubArg(PyObject* obj)
    {
        auto feature = freecad_cast<FeatureAddSub*>(objectArg(obj));
        if (!feature) {
            PyErr_SetString(PyExc_TypeError, "Expected an additive or subtractive feature");
            throw Py::Exception();
        }
        return feature;
    }

    static Py::List objectList(const auto& objects)
    {
        Py::List list;
        for (auto obj : objects) {
            list.append(Py::asObject(obj->getPyObject()));
        }
        return list;
    }

    static std::vector<App::DocumentObject*> objectsArg(PyObject* objects)
    {
        std::vector<App::DocumentObject*> result;
        Py::Sequence sequence(objects);
        for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
            PyObject* item = (*it).ptr();
            if (!PyObject_TypeCheck(item, &(App::DocumentObjectPy::Type))) {
                PyErr_SetString(PyExc_TypeError, "Expected a sequence of bodies");
                throw Py::Exception();
            }
            result.push_back(objectArg(item));
        }
        return result;
    }

    Py::Object makeSiblings(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pObj, &pBodies)) {
            throw Py::Exception();
        }
        FeatureAddSub* feature = addSubArg(pObj);
        std::vector<App::DocumentObject*> bodies = objectsArg(pBodies);
        try {
            return objectList(FeatureAddSub::makeSiblings(feature, bodies));
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#325 3b): Merge
    Py::Object makeMerge(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pObj, &pBodies)) {
            throw Py::Exception();
        }
        App::DocumentObject* at = objectArg(pObj);
        std::vector<App::DocumentObject*> bodies = objectsArg(pBodies);
        try {
            return Py::asObject(Boolean::makeMerge(at, bodies)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640 rank 1): the merge scope
    Py::Object setMergeScope(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pObj, &pBodies)) {
            throw Py::Exception();
        }
        App::DocumentObject* feature = objectArg(pObj);
        std::vector<App::DocumentObject*> bodies = objectsArg(pBodies);
        try {
            Boolean* merge = Boolean::setMergeScope(feature, bodies);
            return merge ? Py::asObject(merge->getPyObject()) : Py::None();
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object mergeAfter(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        Boolean* merge = Boolean::mergeAfter(objectArg(pObj));
        return merge ? Py::asObject(merge->getPyObject()) : Py::None();
    }

    // FreeCAD-CH (ops#640 rank 28): a part a Boolean consumed
    Py::Object consumerOf(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        Boolean* boolean = Boolean::consumerOf(objectArg(pObj));
        return boolean ? Py::asObject(boolean->getPyObject()) : Py::None();
    }

    // FreeCAD-CH (ops#325 4): Split
    Py::Object split(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pTool;
        const char* side = "Front";
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O|s",
                &(App::DocumentObjectPy::Type),
                &pObj,
                &pTool,
                &side
            )) {
            throw Py::Exception();
        }
        App::DocumentObject* body = objectArg(pObj);
        App::DocumentObject* tool = nullptr;
        std::vector<std::string> subs;
        if (PyObject_TypeCheck(pTool, &(App::DocumentObjectPy::Type))) {
            tool = objectArg(pTool);
        }
        else if (PyTuple_Check(pTool) && PyTuple_Size(pTool) == 2
                 && PyObject_TypeCheck(
                     PyTuple_GetItem(pTool, 0),
                     &(App::DocumentObjectPy::Type)
                 )) {
            tool = objectArg(PyTuple_GetItem(pTool, 0));
            Py::Object sub(PyTuple_GetItem(pTool, 1));
            if (sub.isString()) {
                subs.push_back(Py::String(sub).as_std_string());
            }
            else {
                Py::Sequence sequence(sub);
                for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
                    subs.push_back(Py::String(*it).as_std_string());
                }
            }
        }
        else {
            PyErr_SetString(PyExc_TypeError, "Expected a plane, or (feature, 'FaceN')");
            throw Py::Exception();
        }
        try {
            return Py::asObject(Split::makeSplit(body, tool, subs, side)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object siblingsOf(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        return objectList(addSubArg(pObj)->getSiblings());
    }

    Py::Object unlinkSibling(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        addSubArg(pObj)->unlinkSibling();
        return Py::None();
    }

    Py::Object isStudioProfile(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pObj;
        const char* subname = "";
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!|s",
                &(App::DocumentObjectPy::Type),
                &pOwner,
                &(App::DocumentObjectPy::Type),
                &pObj,
                &subname
            )) {
            throw Py::Exception();
        }
        return Py::Boolean(
            ProfileBased::isStudioProfile(objectArg(pOwner), objectArg(pObj), subname)
        );
    }

    Py::Object studioOriginFeature(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pObj;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!",
                &(App::DocumentObjectPy::Type),
                &pOwner,
                &(App::DocumentObjectPy::Type),
                &pObj
            )) {
            throw Py::Exception();
        }
        auto feature = Part::BodyBase::studioOriginFeature(objectArg(pOwner), objectArg(pObj));
        if (!feature) {
            return Py::None();
        }
        return Py::asObject(feature->getPyObject());
    }

    // FreeCAD-CH (ops#602): the studio's feature list and bar. The studio is a document (its
    // top level) or an App::Part
    static void studioArg(PyObject* obj, App::Document*& doc, App::Part*& studio)
    {
        studio = nullptr;
        if (PyObject_TypeCheck(obj, &(App::DocumentPy::Type))) {
            doc = static_cast<App::DocumentPy*>(obj)->getDocumentPtr();
            if (!doc) {
                PyErr_SetString(PyExc_ReferenceError, "The document is closed");
                throw Py::Exception();
            }
            return;
        }
        if (PyObject_TypeCheck(obj, &(App::DocumentObjectPy::Type))) {
            studio = freecad_cast<App::Part*>(objectArg(obj));
            if (studio) {
                doc = studio->getDocument();
                return;
            }
        }
        PyErr_SetString(PyExc_TypeError, "Expected a document or an App::Part");
        throw Py::Exception();
    }

    Py::Object studioSequence(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        return objectList(PartDesign::studioSequence(doc, studio));
    }

    // FreeCAD-CH (ops#723): Part Studio variables' place in the history (StudioVariables.h)
    Py::Object variablePosition(const Py::Tuple& args)
    {
        PyObject* pHolder;
        const char* name;
        if (!PyArg_ParseTuple(args.ptr(), "O!s", &(App::DocumentObjectPy::Type), &pHolder, &name)) {
            throw Py::Exception();
        }
        auto row = PartDesign::variablePosition(objectArg(pHolder), name);
        return row ? Py::asObject(row->getPyObject()) : Py::None();
    }

    Py::Object setVariablePosition(const Py::Tuple& args)
    {
        PyObject* pHolder;
        const char* name;
        PyObject* pAfter = Py_None;
        if (!PyArg_ParseTuple(
                args.ptr(), "O!s|O", &(App::DocumentObjectPy::Type), &pHolder, &name, &pAfter
            )) {
            throw Py::Exception();
        }
        App::DocumentObject* after = nullptr;
        if (pAfter != Py_None) {
            if (!PyObject_TypeCheck(pAfter, &(App::DocumentObjectPy::Type))) {
                PyErr_SetString(PyExc_TypeError, "Expected a feature or None");
                throw Py::Exception();
            }
            after = objectArg(pAfter);
        }
        try {
            PartDesign::setVariablePosition(objectArg(pHolder), name, after);
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
        return Py::None();
    }

    Py::Object rollStudioTo(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pStudio, &pObj)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        App::DocumentObject* member = nullptr;
        if (pObj != Py_None) {
            if (!PyObject_TypeCheck(pObj, &(App::DocumentObjectPy::Type))) {
                PyErr_SetString(PyExc_TypeError, "Expected a feature or None");
                throw Py::Exception();
            }
            member = objectArg(pObj);
        }
        try {
            PartDesign::rollStudioTo(doc, studio, member);
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
        return Py::None();
    }

    Py::Object rollStudioToEnd(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        PartDesign::rollStudioToEnd(doc, studio);
        return Py::None();
    }

    Py::Object isStudioRolledBack(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        return Py::Boolean(PartDesign::isStudioRolledBack(doc, studio));
    }

    Py::Object studioBarAfter(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pHint = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "O|O", &pStudio, &pHint)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        App::DocumentObject* hint = nullptr;
        if (pHint && pHint != Py_None) {
            if (!PyObject_TypeCheck(pHint, &(App::DocumentObjectPy::Type))) {
                PyErr_SetString(PyExc_TypeError, "Expected a feature or None");
                throw Py::Exception();
            }
            hint = objectArg(pHint);
        }
        auto after =
            PartDesign::studioBarAfter(PartDesign::studioSequence(doc, studio), pHint != nullptr, hint);
        if (!after) {
            return Py::None();
        }
        return Py::asObject(after->getPyObject());
    }

    // A feature, None, or (with none) a missing argument
    static App::DocumentObject* featureOrNone(PyObject* obj)
    {
        if (!obj || obj == Py_None) {
            return nullptr;
        }
        if (!PyObject_TypeCheck(obj, &(App::DocumentObjectPy::Type))) {
            PyErr_SetString(PyExc_TypeError, "Expected a feature or None");
            throw Py::Exception();
        }
        return objectArg(obj);
    }

    Py::Object moveInStudio(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pRows;
        PyObject* pAfter;
        PyObject* pBar = nullptr;
        if (!PyArg_ParseTuple(args.ptr(), "OOO|O", &pStudio, &pRows, &pAfter, &pBar)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        std::vector<App::DocumentObject*> rows;
        if (PyObject_TypeCheck(pRows, &(App::DocumentObjectPy::Type))) {
            rows.push_back(objectArg(pRows));
        }
        else if (PySequence_Check(pRows)) {
            Py::Sequence sequence(pRows);
            for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
                if (!PyObject_TypeCheck((*it).ptr(), &(App::DocumentObjectPy::Type))) {
                    PyErr_SetString(PyExc_TypeError, "Expected a feature or a sequence of features");
                    throw Py::Exception();
                }
                rows.push_back(objectArg((*it).ptr()));
            }
        }
        else {
            PyErr_SetString(PyExc_TypeError, "Expected a feature or a sequence of features");
            throw Py::Exception();
        }
        App::DocumentObject* after = featureOrNone(pAfter);
        App::DocumentObject* bar = featureOrNone(pBar);
        try {
            return Py::Boolean(PartDesign::moveInStudio(doc, studio, rows, after, pBar != nullptr, bar));
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    // FreeCAD-CH (ops#640 round 6): Derived (Derived.h)
    static PyObject* studioObject(App::Document* doc, App::Part* studio)
    {
        return studio ? studio->getPyObject() : doc->getPyObject();
    }

    static PartDesign::FeatureBase* derivedArg(PyObject* obj)
    {
        auto lead = freecad_cast<PartDesign::FeatureBase*>(objectArg(obj));
        if (!lead || !PartDesign::isDerived(lead)) {
            PyErr_SetString(PyExc_TypeError, "Expected a Derived feature");
            throw Py::Exception();
        }
        return lead;
    }

    static std::vector<Body*> bodiesArg(PyObject* objects)
    {
        std::vector<Body*> bodies;
        for (auto obj : objectsArg(objects)) {
            auto body = freecad_cast<Body*>(obj);
            if (!body) {
                PyErr_SetString(PyExc_TypeError, "Expected a sequence of bodies");
                throw Py::Exception();
            }
            bodies.push_back(body);
        }
        return bodies;
    }

    static std::vector<Part::Feature*> copiesArg(PyObject* objects)
    {
        std::vector<Part::Feature*> copies;
        for (auto obj : objectsArg(objects)) {
            if (!PartDesign::isDerivedCopy(obj)) {
                PyErr_SetString(PyExc_TypeError, "Expected a sequence of derived copies");
                throw Py::Exception();
            }
            copies.push_back(static_cast<Part::Feature*>(obj));
        }
        return copies;
    }

    Py::Object isDerivedCopy(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        return Py::Boolean(PartDesign::isDerivedCopy(objectArg(pObj)));
    }

    Py::Object makeDerivedCopies(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pCopies;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pStudio, &pCopies)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        std::vector<Part::Feature*> copies = copiesArg(pCopies);
        try {
            return Py::asObject(PartDesign::makeDerivedCopies(doc, studio, copies)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object editDerivedCopies(const Py::Tuple& args)
    {
        PyObject* pLead;
        PyObject* pCopies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pLead, &pCopies)) {
            throw Py::Exception();
        }
        PartDesign::FeatureBase* lead = derivedArg(pLead);
        std::vector<Part::Feature*> copies = copiesArg(pCopies);
        try {
            return Py::asObject(PartDesign::editDerivedCopies(lead, copies)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object derivedStudios(const Py::Tuple& args)
    {
        PyObject* pDoc;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pDoc)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pDoc, doc, studio);
        Py::List list;
        for (auto part : PartDesign::derivedStudios(doc)) {
            list.append(Py::asObject(studioObject(doc, part)));
        }
        return list;
    }

    Py::Object studioLabel(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        return Py::String(PartDesign::studioLabel(doc, studio));
    }

    Py::Object derivableParts(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        return objectList(PartDesign::derivableParts(doc, studio));
    }

    Py::Object makeDerived(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pStudio, &pBodies)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        studioArg(pStudio, doc, studio);
        std::vector<Body*> bodies = bodiesArg(pBodies);
        try {
            return Py::asObject(PartDesign::makeDerived(doc, studio, bodies)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object editDerived(const Py::Tuple& args)
    {
        PyObject* pLead;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "O!O", &(App::DocumentObjectPy::Type), &pLead, &pBodies)) {
            throw Py::Exception();
        }
        PartDesign::FeatureBase* lead = derivedArg(pLead);
        std::vector<Body*> bodies = bodiesArg(pBodies);
        try {
            return Py::asObject(PartDesign::editDerived(lead, bodies)->getPyObject());
        }
        catch (const Base::Exception& e) {
            e.setPyException();
            throw Py::Exception();
        }
    }

    Py::Object deleteDerivedParts(const Py::Tuple& args)
    {
        PyObject* pLead;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pLead)) {
            throw Py::Exception();
        }
        PartDesign::deleteDerivedParts(derivedArg(pLead));
        return Py::None();
    }

    Py::Object derivedLead(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pObj)) {
            throw Py::Exception();
        }
        auto lead = PartDesign::derivedLead(objectArg(pObj));
        if (!lead) {
            return Py::None();
        }
        return Py::asObject(lead->getPyObject());
    }

    Py::Object derivedMembers(const Py::Tuple& args)
    {
        PyObject* pLead;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pLead)) {
            throw Py::Exception();
        }
        return objectList(PartDesign::derivedMembers(derivedArg(pLead)));
    }

    Py::Object derivedSource(const Py::Tuple& args)
    {
        PyObject* pMember;
        if (!PyArg_ParseTuple(args.ptr(), "O!", &(App::DocumentObjectPy::Type), &pMember)) {
            throw Py::Exception();
        }
        auto source = PartDesign::derivedSource(derivedArg(pMember));
        if (!source) {
            return Py::None();
        }
        return Py::asObject(source->getPyObject());
    }

    // FreeCAD-CH (ops#654): the studio's list
    static PartDesign::StudioList* studioListArg(PyObject* obj)
    {
        auto list = PyObject_TypeCheck(obj, &(App::DocumentObjectPy::Type))
            ? freecad_cast<PartDesign::StudioList*>(objectArg(obj))
            : nullptr;
        if (!list) {
            PyErr_SetString(PyExc_TypeError, "Expected a studio list");
            throw Py::Exception();
        }
        return list;
    }

    static PartDesign::Body* bodyArg(PyObject* obj)
    {
        auto body = PyObject_TypeCheck(obj, &(App::DocumentObjectPy::Type))
            ? freecad_cast<PartDesign::Body*>(objectArg(obj))
            : nullptr;
        if (!body) {
            PyErr_SetString(PyExc_TypeError, "Expected a body");
            throw Py::Exception();
        }
        return body;
    }

    static App::DocumentObject* entryArg(PyObject* obj)
    {
        if (!PyObject_TypeCheck(obj, &(App::DocumentObjectPy::Type))) {
            PyErr_SetString(PyExc_TypeError, "Expected a document object");
            throw Py::Exception();
        }
        return objectArg(obj);
    }

    // A list edit's refusal raises ValueError with its reason
    static Py::Object done(bool ok, const std::string& why)
    {
        if (!ok) {
            throw Py::ValueError(why.empty() ? std::string("Refused") : why);
        }
        return Py::None();
    }

    Py::Object studioList(const Py::Tuple& args)
    {
        PyObject* pStudio = Py_None;
        PyObject* pCreate = Py_False;
        if (!PyArg_ParseTuple(args.ptr(), "|OO", &pStudio, &pCreate)) {
            throw Py::Exception();
        }
        App::Document* doc = nullptr;
        App::Part* studio = nullptr;
        if (pStudio == Py_None) {
            doc = App::GetApplication().getActiveDocument();
            if (!doc) {
                throw Py::ValueError("No active document");
            }
        }
        else {
            studioArg(pStudio, doc, studio);
        }
        auto list = PartDesign::StudioList::of(doc, studio, PyObject_IsTrue(pCreate) == 1);
        if (!list) {
            return Py::None();
        }
        return Py::asObject(list->getPyObject());
    }

    Py::Object studioInsert(const Py::Tuple& args)
    {
        PyObject* pEntry;
        int index = -1;
        if (!PyArg_ParseTuple(args.ptr(), "O|i", &pEntry, &index)) {
            throw Py::Exception();
        }
        App::DocumentObject* entry = entryArg(pEntry);
        std::string why;
        done(PartDesign::studioInsert(entry, index, &why), why);
        return Py::asObject(PartDesign::StudioList::holding(entry)->getPyObject());
    }

    Py::Object studioRemove(const Py::Tuple& args)
    {
        PyObject* pEntry;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pEntry)) {
            throw Py::Exception();
        }
        std::string why;
        return done(PartDesign::studioRemove(entryArg(pEntry), &why), why);
    }

    Py::Object studioMove(const Py::Tuple& args)
    {
        PyObject* pEntry;
        int index;
        if (!PyArg_ParseTuple(args.ptr(), "Oi", &pEntry, &index)) {
            throw Py::Exception();
        }
        std::string why;
        return done(PartDesign::studioMove(entryArg(pEntry), index, &why), why);
    }

    Py::Object studioSetBar(const Py::Tuple& args)
    {
        PyObject* pEntry;
        int index;
        if (!PyArg_ParseTuple(args.ptr(), "Oi", &pEntry, &index)) {
            throw Py::Exception();
        }
        std::string why;
        return done(PartDesign::studioSetBar(entryArg(pEntry), index, &why), why);
    }

    Py::Object studioSetScope(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pBodies;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pOwner, &pBodies)) {
            throw Py::Exception();
        }
        App::DocumentObject* owner = entryArg(pOwner);
        std::vector<PartDesign::Body*> bodies;
        Py::Sequence sequence(pBodies);
        for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
            bodies.push_back(bodyArg((*it).ptr()));
        }
        std::string why;
        return done(PartDesign::studioSetScope(owner, bodies, &why), why);
    }

    Py::Object studioSetScopeIds(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pIds;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pOwner, &pIds)) {
            throw Py::Exception();
        }
        App::DocumentObject* owner = entryArg(pOwner);
        std::vector<std::string> ids;
        Py::Sequence sequence(pIds);
        for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
            if (!PyUnicode_Check((*it).ptr())) {
                PyErr_SetString(PyExc_TypeError, "Expected a sequence of part ids (strings)");
                throw Py::Exception();
            }
            ids.push_back(Py::String(*it).as_std_string("utf-8"));
        }
        std::string why;
        return done(PartDesign::studioSetScopeIds(owner, ids, &why), why);
    }

    Py::Object studioScopeIds(const Py::Tuple& args)
    {
        PyObject* pOwner;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pOwner)) {
            throw Py::Exception();
        }
        Py::List list;
        for (const auto& id : PartDesign::studioScopeIds(entryArg(pOwner))) {
            list.append(Py::String(id));
        }
        return list;
    }

    Py::Object studioScopeOf(const Py::Tuple& args)
    {
        PyObject* pOwner;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pOwner)) {
            throw Py::Exception();
        }
        return objectList(PartDesign::studioScopeOf(entryArg(pOwner)));
    }

    Py::Object studioPartId(const Py::Tuple& args)
    {
        PyObject* pBody;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pBody)) {
            throw Py::Exception();
        }
        return Py::String(PartDesign::studioPartId(bodyArg(pBody)));
    }

    // ---- FreeCAD-CH ops#671: configurations ----

    static void configStudioArg(PyObject* obj, App::Document*& doc, App::Part*& studio)
    {
        doc = nullptr;
        studio = nullptr;
        if (obj == Py_None) {
            doc = App::GetApplication().getActiveDocument();
            if (!doc) {
                throw Py::ValueError("No active document");
            }
            return;
        }
        studioArg(obj, doc, studio);
    }

    static std::string configValueText(PyObject* v)
    {
        if (PyBool_Check(v)) {
            return v == Py_True ? "true" : "false";
        }
        if (PyLong_Check(v)) {
            return std::to_string(PyLong_AsLongLong(v));
        }
        if (PyFloat_Check(v)) {
            char buf[64];
            std::snprintf(buf, sizeof(buf), "%.17g", PyFloat_AsDouble(v));
            return buf;
        }
        if (PyUnicode_Check(v)) {
            return Py::String(v).as_std_string("utf-8");
        }
        return Py::String(Py::Object(v).str()).as_std_string("utf-8");
    }

    static std::map<std::string, std::string> configValues(PyObject* dict)
    {
        std::map<std::string, std::string> values;
        if (!dict || dict == Py_None) {
            return values;
        }
        if (!PyDict_Check(dict)) {
            throw Py::TypeError("Expected a dict of input -> value");
        }
        PyObject* key = nullptr;
        PyObject* value = nullptr;
        Py_ssize_t pos = 0;
        while (PyDict_Next(dict, &pos, &key, &value)) {
            values[configValueText(key)] = configValueText(value);
        }
        return values;
    }

    static Py::Object configId(const std::string& id, const std::string& why)
    {
        if (id.empty()) {
            throw Py::ValueError(why.empty() ? std::string("Refused") : why);
        }
        return Py::String(id);
    }

    static PartDesign::StudioConfig* configOrThrow(PyObject* pStudio)
    {
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        auto cfg = PartDesign::StudioConfig::of(doc, studio);
        if (!cfg) {
            throw Py::ValueError("The studio has no configurations");
        }
        return cfg;
    }

    Py::Object configStudio(const Py::Tuple& args)
    {
        PyObject* pStudio = Py_None;
        PyObject* pCreate = Py_False;
        if (!PyArg_ParseTuple(args.ptr(), "|OO", &pStudio, &pCreate)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        auto cfg = PartDesign::StudioConfig::of(doc, studio, PyObject_IsTrue(pCreate) == 1);
        return cfg ? Py::asObject(cfg->getPyObject()) : Py::None();
    }

    Py::Object configAddList(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* name;
        PyObject* pRows = Py_None;
        if (!PyArg_ParseTuple(args.ptr(), "Os|O", &pStudio, &name, &pRows)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::vector<std::string> rows;
        if (pRows != Py_None) {
            Py::Sequence seq(pRows);
            for (auto it = seq.begin(); it != seq.end(); ++it) {
                rows.push_back(Py::String(*it).as_std_string("utf-8"));
            }
        }
        std::string why;
        return configId(PartDesign::configAddList(studio, name, rows, &why), why);
    }

    Py::Object configAddCheckbox(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* name;
        PyObject* pDefault = Py_True;
        if (!PyArg_ParseTuple(args.ptr(), "Os|O", &pStudio, &name, &pDefault)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return configId(
            PartDesign::configAddCheckbox(studio, name, PyObject_IsTrue(pDefault) == 1, &why),
            why
        );
    }

    Py::Object configAddVariable(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* name;
        const char* type;
        PyObject* pDefault;
        PyObject* pMin = Py_None;
        PyObject* pMax = Py_None;
        if (!PyArg_ParseTuple(args.ptr(), "OssO|OO", &pStudio, &name, &type, &pDefault, &pMin, &pMax)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        auto text = [](PyObject* v) {
            return v == Py_None ? std::string() : configValueText(v);
        };
        std::string why;
        return configId(
            PartDesign::configAddVariable(studio, name, type, text(pDefault), text(pMin), text(pMax), &why),
            why
        );
    }

    Py::Object configAddRow(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* input;
        const char* name;
        if (!PyArg_ParseTuple(args.ptr(), "Oss", &pStudio, &input, &name)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return configId(PartDesign::configAddRow(studio, input, name, &why), why);
    }

    Py::Object configRenameRow(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* input;
        const char* row;
        const char* name;
        if (!PyArg_ParseTuple(args.ptr(), "Osss", &pStudio, &input, &row, &name)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return done(PartDesign::configRenameRow(studio, input, row, name, &why), why);
    }

    Py::Object configRemoveRow(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* input;
        const char* row;
        if (!PyArg_ParseTuple(args.ptr(), "Oss", &pStudio, &input, &row)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return done(PartDesign::configRemoveRow(studio, input, row, &why), why);
    }

    Py::Object configSetDefaultRow(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* input;
        const char* row;
        if (!PyArg_ParseTuple(args.ptr(), "Oss", &pStudio, &input, &row)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return done(PartDesign::configSetDefaultRow(studio, input, row, &why), why);
    }

    Py::Object configMoveRow(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* input;
        const char* row;
        int index;
        if (!PyArg_ParseTuple(args.ptr(), "Ossi", &pStudio, &input, &row, &index)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return done(PartDesign::configMoveRow(studio, input, row, index, &why), why);
    }

    Py::Object configRenameInput(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* input;
        const char* name;
        if (!PyArg_ParseTuple(args.ptr(), "Oss", &pStudio, &input, &name)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return done(PartDesign::configRenameInput(studio, input, name, &why), why);
    }

    Py::Object configMoveInput(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* input;
        int index;
        if (!PyArg_ParseTuple(args.ptr(), "Osi", &pStudio, &input, &index)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return done(PartDesign::configMoveInput(studio, input, index, &why), why);
    }

    Py::Object configSetCheckboxDefault(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* input;
        PyObject* pValue;
        if (!PyArg_ParseTuple(args.ptr(), "OsO", &pStudio, &input, &pValue)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return done(
            PartDesign::configSetCheckboxDefault(studio, input, PyObject_IsTrue(pValue) == 1, &why),
            why
        );
    }

    Py::Object configEditVariable(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* name;
        PyObject* pDefault;
        PyObject* pMin = Py_None;
        PyObject* pMax = Py_None;
        if (!PyArg_ParseTuple(args.ptr(), "OsO|OO", &pStudio, &name, &pDefault, &pMin, &pMax)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        auto text = [](PyObject* v) {
            return v == Py_None ? std::string() : configValueText(v);
        };
        std::string why;
        return done(
            PartDesign::configEditVariable(studio, name, text(pDefault), text(pMin), text(pMax), &why),
            why
        );
    }

    Py::Object configRemoveInput(const Py::Tuple& args)
    {
        PyObject* pStudio;
        const char* input;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pStudio, &input)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return done(PartDesign::configRemoveInput(studio, input, &why), why);
    }

    Py::Object configConfigure(const Py::Tuple& args)
    {
        PyObject* pObj;
        const char* path;
        const char* input;
        if (!PyArg_ParseTuple(args.ptr(), "Oss", &pObj, &path, &input)) {
            throw Py::Exception();
        }
        std::string why;
        return done(PartDesign::configConfigure(entryArg(pObj), path, input, &why), why);
    }

    Py::Object configUnconfigure(const Py::Tuple& args)
    {
        PyObject* pObj;
        const char* path;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pObj, &path)) {
            throw Py::Exception();
        }
        std::string why;
        return done(PartDesign::configUnconfigure(entryArg(pObj), path, &why), why);
    }

    Py::Object configSetCell(const Py::Tuple& args)
    {
        PyObject* pObj;
        const char* path;
        const char* row;
        PyObject* pText;
        if (!PyArg_ParseTuple(args.ptr(), "OssO", &pObj, &path, &row, &pText)) {
            throw Py::Exception();
        }
        std::string why;
        return done(
            PartDesign::configSetCell(entryArg(pObj), path, row, configValueText(pText), &why),
            why
        );
    }

    Py::Object configConfigureSuppression(const Py::Tuple& args)
    {
        PyObject* pObj;
        const char* input;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pObj, &input)) {
            throw Py::Exception();
        }
        std::string why;
        return done(PartDesign::configConfigureSuppression(entryArg(pObj), input, &why), why);
    }

    Py::Object configUnconfigureSuppression(const Py::Tuple& args)
    {
        PyObject* pObj;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pObj)) {
            throw Py::Exception();
        }
        std::string why;
        return done(PartDesign::configUnconfigureSuppression(entryArg(pObj), &why), why);
    }

    Py::Object configSetSuppressionCell(const Py::Tuple& args)
    {
        PyObject* pObj;
        const char* row;
        PyObject* pOn;
        if (!PyArg_ParseTuple(args.ptr(), "OsO", &pObj, &row, &pOn)) {
            throw Py::Exception();
        }
        std::string why;
        return done(
            PartDesign::configSetSuppressionCell(entryArg(pObj), row, PyObject_IsTrue(pOn) == 1, &why),
            why
        );
    }

    Py::Object configIsConfigured(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pPath = Py_None;
        if (!PyArg_ParseTuple(args.ptr(), "O|O", &pObj, &pPath)) {
            throw Py::Exception();
        }
        App::DocumentObject* obj = entryArg(pObj);
        if (pPath == Py_None) {
            return Py::Boolean(PartDesign::configSuppressionIsConfigured(obj));
        }
        return Py::Boolean(PartDesign::configIsConfigured(obj, configValueText(pPath)));
    }

    Py::Object configInputOf(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pPath = Py_None;
        if (!PyArg_ParseTuple(args.ptr(), "O|O", &pObj, &pPath)) {
            throw Py::Exception();
        }
        App::DocumentObject* obj = entryArg(pObj);
        const std::string path = pPath == Py_None ? std::string() : configValueText(pPath);
        return Py::String(PartDesign::configInputOf(obj, path));
    }

    Py::Object configMenuItems(const Py::Tuple& args)
    {
        PyObject* pObj;
        PyObject* pPath = Py_None;
        if (!PyArg_ParseTuple(args.ptr(), "O|O", &pObj, &pPath)) {
            throw Py::Exception();
        }
        App::DocumentObject* obj = entryArg(pObj);
        const std::string path = pPath == Py_None ? std::string() : configValueText(pPath);
        Py::List out;
        for (const auto& item : PartDesign::configMenuItems(obj, path)) {
            out.append(Py::TupleN(Py::String(item.label), Py::String(item.action), Py::String(item.input)));
        }
        return out;
    }

    Py::Object configEntries(const Py::Tuple& args)
    {
        PyObject* pStudio = Py_None;
        if (!PyArg_ParseTuple(args.ptr(), "|O", &pStudio)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        Py::List out;
        for (const auto& e : PartDesign::configEntries(PartDesign::StudioConfig::of(doc, studio))) {
            Py::Dict d;
            d.setItem("object", Py::asObject(e.object->getPyObject()));
            d.setItem("path", e.path.empty() ? Py::None() : Py::Object(Py::String(e.path)));
            d.setItem("input", Py::String(e.input));
            Py::Dict cells;
            for (const auto& [key, text] : e.cells) {
                cells.setItem(key, Py::String(text));
            }
            d.setItem("cells", cells);
            out.append(d);
        }
        return out;
    }

    Py::Object configSetActive(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pValues;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pStudio, &pValues)) {
            throw Py::Exception();
        }
        App::Document* doc;
        App::Part* studio;
        configStudioArg(pStudio, doc, studio);
        std::string why;
        return done(PartDesign::configSetActive(studio, configValues(pValues), &why), why);
    }

    Py::Object configKey(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pValues = Py_None;
        if (!PyArg_ParseTuple(args.ptr(), "O|O", &pStudio, &pValues)) {
            throw Py::Exception();
        }
        auto cfg = configOrThrow(pStudio);
        if (pValues == Py_None) {
            return Py::String(cfg->activeKey());
        }
        std::string why;
        std::string key = PartDesign::configKeyOf(cfg, configValues(pValues), &why);
        return configId(key, why);
    }

    Py::Object configDefaultKey(const Py::Tuple& args)
    {
        PyObject* pStudio;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pStudio)) {
            throw Py::Exception();
        }
        return Py::String(configOrThrow(pStudio)->defaultKey());
    }

    Py::Object configReconcile(const Py::Tuple& args)
    {
        PyObject* pStudio;
        PyObject* pCheck = Py_True;
        if (!PyArg_ParseTuple(args.ptr(), "O|O", &pStudio, &pCheck)) {
            throw Py::Exception();
        }
        return Py::String(
            PartDesign::configReconcile(configOrThrow(pStudio), PyObject_IsTrue(pCheck) == 1)
        );
    }

    Py::Object configSetReaderKey(const Py::Tuple& args)
    {
        PyObject* pReader;
        PyObject* pSource;
        PyObject* pValues = Py_None;
        if (!PyArg_ParseTuple(args.ptr(), "OO|O", &pReader, &pSource, &pValues)) {
            throw Py::Exception();
        }
        std::string why;
        return done(
            PartDesign::configSetReaderKey(entryArg(pReader), entryArg(pSource), configValues(pValues), &why),
            why
        );
    }

    Py::Object configReaderError(const Py::Tuple& args)
    {
        PyObject* pReader;
        PyObject* pSource;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pReader, &pSource)) {
            throw Py::Exception();
        }
        return Py::String(PartDesign::configReaderError(entryArg(pReader), entryArg(pSource)));
    }

    Py::Object studioSuppress(const Py::Tuple& args)
    {
        PyObject* pEntry;
        PyObject* pOn;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pEntry, &pOn)) {
            throw Py::Exception();
        }
        std::string why;
        const bool on = PyObject_IsTrue(pOn) == 1;
        return done(PartDesign::studioSuppress(entryArg(pEntry), on, &why), why);
    }

    Py::Object studioReconcile(const Py::Tuple& args)
    {
        PyObject* pList;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pList)) {
            throw Py::Exception();
        }
        std::string why;
        return done(studioListArg(pList)->reconcile(&why), why);
    }

    Py::Object studioProject(const Py::Tuple& args)
    {
        PyObject* pList;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pList)) {
            throw Py::Exception();
        }
        const auto projection = studioListArg(pList)->project();
        if (!projection.errors.empty()) {
            std::string why;
            for (const auto& error : projection.errors) {
                why += (why.empty() ? "" : "\n") + error;
            }
            throw Py::ValueError(why);
        }
        Py::Dict out;
        for (const auto& [body, chain] : projection.chains) {
            Py::List slots;
            for (const auto& slot : chain) {
                Py::Tuple item(4);
                item.setItem(0, Py::String(slot.entry->getNameInDocument()));
                item.setItem(1, Py::Boolean(slot.isStep));
                item.setItem(2, Py::Boolean(slot.suppressed));
                item.setItem(3, Py::Boolean(slot.held));
                slots.append(item);
            }
            out.setItem(Py::String(body->getNameInDocument()), slots);
        }
        return out;
    }

    Py::Object studioStepOf(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pBody;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pOwner, &pBody)) {
            throw Py::Exception();
        }
        auto step = PartDesign::StudioList::stepOf(entryArg(pOwner), bodyArg(pBody));
        if (!step) {
            return Py::None();
        }
        return Py::asObject(step->getPyObject());
    }

    // FreeCAD-CH ops#654 P5, P6a
    Py::Object studioLiveParts(const Py::Tuple& args)
    {
        PyObject* pAny;
        int index = -1;
        if (!PyArg_ParseTuple(args.ptr(), "O|i", &pAny, &index)) {
            throw Py::Exception();
        }
        App::DocumentObject* any = entryArg(pAny);
        PartDesign::StudioList* list = freecad_cast<PartDesign::StudioList*>(any);
        if (!list) {
            list = PartDesign::StudioList::holding(any);
        }
        if (!list) {
            App::Part* studio = freecad_cast<App::Part*>(any);
            if (auto body = freecad_cast<PartDesign::Body*>(any)) {
                Part::BodyBase::studioOf(body, studio);
            }
            list = PartDesign::StudioList::of(any->getDocument(), studio);
        }
        if (!list) {
            throw Py::ValueError(std::string("'") + any->Label.getValue()
                                 + "' names no studio history");
        }
        return objectList(PartDesign::studioLivePartsAt(list, index));
    }

    Py::Object studioSetToolIds(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pIds;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pOwner, &pIds)) {
            throw Py::Exception();
        }
        auto boolean = freecad_cast<PartDesign::Boolean*>(entryArg(pOwner));
        PartDesign::StudioList* list = PartDesign::StudioList::holding(boolean);
        if (!boolean || !list || !PartDesign::isStudioOwner(boolean)) {
            throw Py::ValueError("Expected a Boolean studio feature in a studio's history");
        }
        std::vector<std::string> ids;
        Py::Sequence sequence(pIds);
        for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
            if (!PyUnicode_Check((*it).ptr())) {
                PyErr_SetString(PyExc_TypeError, "Expected a sequence of part ids (strings)");
                throw Py::Exception();
            }
            ids.push_back(Py::String(*it).as_std_string("utf-8"));
        }
        if (boolean->StudioTools.getValues() != ids) {
            boolean->StudioTools.setValues(ids);
        }
        std::string why;
        return done(list->reconcile(&why), why);
    }

    Py::Object studioBooleanParts(const Py::Tuple& args)
    {
        PyObject* pOwner;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pOwner)) {
            throw Py::Exception();
        }
        std::vector<PartDesign::Body*> steps;
        std::vector<PartDesign::Body*> tools;
        std::vector<PartDesign::Body*> both;
        PartDesign::studioBooleanParts(entryArg(pOwner), steps, tools, both);
        Py::Tuple out(2);
        out.setItem(0, objectList(steps));
        out.setItem(1, objectList(tools));
        return out;
    }

    Py::Object studioConsumerOf(const Py::Tuple& args)
    {
        PyObject* pBody;
        int index = -1;
        if (!PyArg_ParseTuple(args.ptr(), "O|i", &pBody, &index)) {
            throw Py::Exception();
        }
        auto consumer = PartDesign::studioConsumerOf(bodyArg(pBody), index);
        if (!consumer) {
            return Py::None();
        }
        return Py::asObject(const_cast<App::DocumentObject*>(consumer)->getPyObject());
    }

    // FreeCAD-CH ops#654 P6p
    Py::Object studioMakePieces(const Py::Tuple& args)
    {
        PyObject* pEntry;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pEntry)) {
            throw Py::Exception();
        }
        std::string why;
        const auto made = PartDesign::makePieces(entryArg(pEntry), &why);
        if (!why.empty()) {
            throw Py::ValueError(why);
        }
        return objectList(made);
    }

    // FreeCAD-CH ops#654 10.13
    Py::Object studioSetMergeAll(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pOn;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pOwner, &pOn)) {
            throw Py::Exception();
        }
        std::string why;
        return done(
            PartDesign::studioSetMergeAll(entryArg(pOwner), PyObject_IsTrue(pOn) == 1, &why),
            why
        );
    }

    // FreeCAD-CH ops#654 P8a
    Py::Object studioPickId(const Py::Tuple& args)
    {
        PyObject* pObj;
        const char* element;
        if (!PyArg_ParseTuple(args.ptr(), "Os", &pObj, &element)) {
            throw Py::Exception();
        }
        App::DocumentObject* obj = entryArg(pObj);
        auto body = freecad_cast<PartDesign::Body*>(obj);
        if (!body) {
            body = PartDesign::Body::findBodyOf(obj);
        }
        auto feature = freecad_cast<Part::Feature*>(obj);
        if (!body || !feature) {
            throw Py::ValueError("Expected a Body, or a feature of one");
        }
        const char* indexed = Data::findElementName(element);
        const Part::TopoShape shape = feature->Shape.getShape();
        const auto names = shape.getElementMappedNames(
            Data::IndexedName(indexed && *indexed ? indexed : element)
        );
        if (names.empty()) {
            throw Py::ValueError(std::string("No element map name for '") + element + "'");
        }
        return Py::String(
            PartDesign::studioPartId(body) + "|"
            + Data::NameTable::instance().toInterned(names.front().first.toString())
        );
    }

    Py::Object studioSetPickIds(const Py::Tuple& args)
    {
        PyObject* pOwner;
        PyObject* pPicks;
        if (!PyArg_ParseTuple(args.ptr(), "OO", &pOwner, &pPicks)) {
            throw Py::Exception();
        }
        auto owner = freecad_cast<PartDesign::DressUp*>(entryArg(pOwner));
        if (!owner || PartDesign::Body::findBodyOf(owner)) {
            throw Py::TypeError("Expected a Fillet or Chamfer studio feature");
        }
        std::vector<std::string> picks;
        Py::Sequence sequence(pPicks);
        for (Py::Sequence::iterator it = sequence.begin(); it != sequence.end(); ++it) {
            picks.push_back(Py::String(*it).as_std_string("utf-8"));
        }
        if (owner->StudioPickIds.getValues() != picks) {
            owner->StudioPickIds.setValues(picks);
        }
        std::string why;
        auto list = PartDesign::StudioList::holding(owner);
        return done(!list || list->reconcile(&why), why);
    }

    Py::Object studioDressUpPicks(const Py::Tuple& args)
    {
        PyObject* pOwner;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pOwner)) {
            throw Py::Exception();
        }
        auto owner = freecad_cast<PartDesign::DressUp*>(entryArg(pOwner));
        if (!owner) {
            throw Py::TypeError("Expected a Fillet or Chamfer");
        }
        Py::List out;
        for (const auto& pick : PartDesign::studioDressUpPicks(owner)) {
            Py::List found;
            for (const auto& [body, subs] : pick.found) {
                Py::List names;
                for (const auto& sub : subs) {
                    names.append(Py::String(sub));
                }
                found.append(Py::TupleN(Py::asObject(body->getPyObject()), names));
            }
            out.append(Py::TupleN(Py::String(pick.text), found));
        }
        return out;
    }

    Py::Object studioPieceName(const Py::Tuple& args)
    {
        PyObject* pBody;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pBody)) {
            throw Py::Exception();
        }
        return Py::String(PartDesign::pieceInheritedName(bodyArg(pBody)));
    }

    // FreeCAD-CH ops#654 S2: a New result, a part the owner makes (notes/parts-design.md 3.1)
    Py::Object studioNewPart(const Py::Tuple& args)
    {
        PyObject* pOwner;
        if (!PyArg_ParseTuple(args.ptr(), "O", &pOwner)) {
            throw Py::Exception();
        }
        App::DocumentObject* owner = entryArg(pOwner);
        PartDesign::StudioList* list = PartDesign::StudioList::holding(owner);
        if (!list || !PartDesign::isStudioOwner(owner)) {
            throw Py::ValueError(
                std::string("'") + owner->Label.getValue()
                + "' is not a studio feature in a studio's history"
            );
        }
        App::Document* doc = owner->getDocument();
        // Its id: "<owner>:<n>", the first n no part of the document has
        std::set<std::string> taken;
        for (auto obj : doc->getObjectsOfType(PartDesign::Body::getClassTypeId())) {
            taken.insert(PartDesign::studioPartId(static_cast<PartDesign::Body*>(obj)));
        }
        std::string id;
        for (int n = 1; id.empty() || taken.count(id); ++n) {
            id = std::string(owner->getNameInDocument()) + ":" + std::to_string(n);
        }
        auto body = static_cast<PartDesign::Body*>(doc->addObject("PartDesign::Body", "Body"));
        if (App::Part* studio = list->studio()) {
            studio->getExtensionByType<App::GroupExtension>()->addObject(body);
        }
        body->StudioPartId.setValue(id);
        body->StudioMadeBy.setValue(owner);
        auto ids = PartDesign::studioScopeIds(owner);
        if (std::find(ids.begin(), ids.end(), id) == ids.end()) {
            ids.push_back(id);
        }
        PartDesign::setStudioScopeIds(owner, ids);
        auto operation = freecad_cast<App::PropertyEnumeration*>(owner->getPropertyByName("Operation"));
        if (auto addSub = freecad_cast<PartDesign::FeatureAddSub*>(owner)) {
            operation = &addSub->Operation;
        }
        // An Extrude owner's, or a part mirror's dynamic one (ops#654 slice 9)
        if (operation && operation->isPartOf("Union")
            && std::string(operation->getValueAsString()) != "Union") {
            operation->setValue("Union");
        }
        std::string why;
        if (!list->reconcile(&why)) {
            throw Py::ValueError(why.empty() ? std::string("Refused") : why);
        }
        return Py::asObject(body->getPyObject());
    }

    Py::Object makeFilletArc(const Py::Tuple& args)
    {
        PyObject* pM1;
        PyObject* pP;
        PyObject* pQ;
        PyObject* pN;
        double r2;
        int ccw;
        if (!PyArg_ParseTuple(
                args.ptr(),
                "O!O!O!O!di",
                &(Base::VectorPy::Type),
                &pM1,
                &(Base::VectorPy::Type),
                &pP,
                &(Base::VectorPy::Type),
                &pQ,
                &(Base::VectorPy::Type),
                &pN,
                &r2,
                &ccw
            )) {
            throw Py::Exception();
        }

        Base::Vector3d M1 = Py::Vector(pM1, false).toVector();
        Base::Vector3d P = Py::Vector(pP, false).toVector();
        Base::Vector3d Q = Py::Vector(pQ, false).toVector();
        Base::Vector3d N = Py::Vector(pN, false).toVector();

        Base::Vector3d u = Q - P;
        Base::Vector3d v = P - M1;
        Base::Vector3d b;
        if (ccw) {
            b = u % N;
        }
        else {
            b = N % u;
        }
        b.Normalize();

        double uu = u * u;
        double uv = u * v;
        double r1 = v.Length();

        // distinguish between internal and external fillets
        r2 *= Base::sgn(uv);

        double cc = 2.0 * r2 * (b * v - r1);
        double d = uv * uv - uu * cc;
        if (d < 0) {
            throw Py::RuntimeError("Unable to calculate intersection points");
        }

        double t;
        double t1 = (-uv + sqrt(d)) / uu;
        double t2 = (-uv - sqrt(d)) / uu;

        if (fabs(t1) < fabs(t2)) {
            t = t1;
        }
        else {
            t = t2;
        }

        Base::Vector3d M2 = P + (u * t) + (b * r2);
        Base::Vector3d S1 = (r2 * M1 + r1 * M2) / (r1 + r2);
        Base::Vector3d S2 = M2 - (b * r2);

        Py::Tuple tuple(3);
        tuple.setItem(0, Py::Vector(S1));
        tuple.setItem(1, Py::Vector(S2));
        tuple.setItem(2, Py::Vector(M2));

        return tuple;
    }
};

PyObject* initModule()
{
    return Base::Interpreter().addModule(new Module);
}

}  // namespace PartDesign
