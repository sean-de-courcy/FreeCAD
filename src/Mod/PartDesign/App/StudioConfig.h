// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// A part studio's configurations, Onshape's (FreeCAD-CH ops#671, notes/configurations-design.md
// 3.1-3.4, 3.6). One StudioConfig per studio, beside its StudioList, holds the intent:
//  - Inputs: the configuration inputs (List: rows with a stable id and a visible name, a default
//    row; Checkbox: a default; Variable: a type, a default, a minimum and a maximum);
//  - Table: the configured parameters (object, path, input, one cell per row or per true/false;
//    a cell is expression text) and the configured suppressions (owner, input, one bool per cell);
//  - Active: the studio's shown configuration (input id -> row id, "true"/"false", or the value).
// A configuration Variable is a dynamic property of the StudioConfig (a VarSet), used as #name.
// A configured parameter's expression and a configured owner's Suppressed are artefacts of the
// active cells: configReconcile() writes them, a write to a configured path becomes the active
// row's cell (the expression write hook), and on load they are only checked.

#include <map>
#include <string>
#include <vector>

#include <App/ConfigurationHooks.h>
#include <App/PropertyStandard.h>
#include <App/VarSet.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class Document;
class Part;
}  // namespace App

namespace PartDesign
{

class PartDesignExport StudioConfig: public App::VarSet
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::StudioConfig);

public:
    StudioConfig();
    ~StudioConfig() override;

    App::PropertyString Inputs;  ///< JSON: {"version": 1, "inputs": [...]}
    App::PropertyString Table;   ///< JSON: {"version": 1, "params": [...], "suppress": [...]}
    App::PropertyMap Active;     ///< input id -> active value (row id, "true"/"false", value)

    App::DocumentObjectExecReturn* execute() override;
    void onDocumentRestored() override;
    short mustExecute() const override;

    /// The studio's (null: the document's top level) StudioConfig; made when create is set
    static StudioConfig* of(App::Document* doc, App::Part* studio, bool create = false);
    /// The studio this belongs to (null: the top level)
    App::Part* studio() const;

    /// The canonical key of values (input id -> value; missing inputs take their defaults):
    /// "<id>=<value>;..." in Inputs' order, lengths in metres and angles in radians (%.17g)
    std::string keyOf(const std::map<std::string, std::string>& values) const;
    /// The key of Active
    std::string activeKey() const;
    /// The key of every input at its default
    std::string defaultKey() const;
    /// Whether there are inputs
    bool hasInputs() const;

    /// What the load check found (empty: the file's expressions and suppressions are the cells')
    const std::string& loadMismatch() const
    {
        return mismatch;
    }
    /// Called when the cells are written: the file then is the active configuration
    void clearLoadMismatch()
    {
        mismatch.clear();
    }

private:
    std::string mismatch;
};

/// Writes every configured parameter's expression and configured owner's Suppressed from the
/// active cells, and the configuration Variables from Active; writes only what differs. With
/// checkOnly, writes nothing and returns what differs (empty: nothing). Not a list reconcile
PartDesignExport std::string configReconcile(StudioConfig* config, bool checkOnly);

// The edits (the panel's and the API's). Each refuses with why (false or empty), like the studio
// edits. The ones that change cells or the active values rebind (configReconcile) and reconcile
// the studio's list; configSetActive also makes pieces and recomputes. The caller's transaction,
// except configSetActive, which opens one when none is open.

/// Adds a List input with rows named rowNames (the first is the default row; its id is "Default",
/// Onshape's); returns its id
PartDesignExport std::string configAddList(App::Part* studio,
                                           const std::string& name,
                                           const std::vector<std::string>& rowNames,
                                           std::string* why);
/// Adds a Checkbox input (Onshape's default: ticked); returns its id (its name)
PartDesignExport std::string configAddCheckbox(App::Part* studio,
                                               const std::string& name,
                                               bool defaultValue,
                                               std::string* why);
/// Adds a configuration Variable (type Length, Angle, Integer, Real or Text; the bounds are
/// ignored for Text), used as #name; returns its id (its name)
PartDesignExport std::string configAddVariable(App::Part* studio,
                                               const std::string& name,
                                               const std::string& type,
                                               const std::string& defaultValue,
                                               const std::string& minimum,
                                               const std::string& maximum,
                                               std::string* why);
/// Adds a row to a List input; its cells copy the default row's; returns the row id
PartDesignExport std::string configAddRow(App::Part* studio,
                                          const std::string& input,
                                          const std::string& name,
                                          std::string* why);
/// Renames a row (its id stays)
PartDesignExport bool configRenameRow(App::Part* studio,
                                      const std::string& input,
                                      const std::string& row,
                                      const std::string& name,
                                      std::string* why);
/// Removes a row and its cells (not the last one); an active row falls back to the default
PartDesignExport bool configRemoveRow(App::Part* studio,
                                      const std::string& input,
                                      const std::string& row,
                                      std::string* why);
/// Makes row the List's default row
PartDesignExport bool configSetDefaultRow(App::Part* studio,
                                          const std::string& input,
                                          const std::string& row,
                                          std::string* why);
/// Moves a List row to position index (0 is the first); the default row stays the default
PartDesignExport bool configMoveRow(App::Part* studio,
                                    const std::string& input,
                                    const std::string& row,
                                    int index,
                                    std::string* why);
/// Renames an input (its id stays). A Variable's property is renamed too (its #name), and the
/// expressions that read it follow
PartDesignExport bool configRenameInput(App::Part* studio,
                                        const std::string& input,
                                        const std::string& name,
                                        std::string* why);
/// Moves an input to position index (0 is the first): the panel's tabs and the bar follow
PartDesignExport bool configMoveInput(App::Part* studio, const std::string& input, int index, std::string* why);
/// Sets a Checkbox input's default and rebinds
PartDesignExport bool configSetCheckboxDefault(App::Part* studio,
                                               const std::string& input,
                                               bool value,
                                               std::string* why);
/// Sets a configuration Variable's default and bounds (empty: no bound; the type stays) and rebinds
PartDesignExport bool configEditVariable(App::Part* studio,
                                         const std::string& input,
                                         const std::string& defaultValue,
                                         const std::string& minimum,
                                         const std::string& maximum,
                                         std::string* why);
/// Removes an input; what it configured keeps its active value, unconfigured
PartDesignExport bool configRemoveInput(App::Part* studio, const std::string& input, std::string* why);

/// Configures obj's path with a List or Checkbox input: every cell gets the current value (its
/// expression's text, or the value)
PartDesignExport bool configConfigure(App::DocumentObject* obj,
                                      const std::string& path,
                                      const std::string& input,
                                      std::string* why);
/// Unconfigures obj's path: it keeps the active cell (a plain value is no longer an expression)
PartDesignExport bool configUnconfigure(App::DocumentObject* obj, const std::string& path, std::string* why);
/// Writes the cell of obj's configured path for row (a row id, or "true"/"false"; empty: the
/// active one) and rebinds
PartDesignExport bool configSetCell(App::DocumentObject* obj,
                                    const std::string& path,
                                    const std::string& row,
                                    const std::string& text,
                                    std::string* why);
/// Configures owner's suppression with a List or Checkbox input: every cell gets its Suppressed
PartDesignExport bool configConfigureSuppression(App::DocumentObject* owner,
                                                 const std::string& input,
                                                 std::string* why);
/// Unconfigures owner's suppression: it keeps the active cell
PartDesignExport bool configUnconfigureSuppression(App::DocumentObject* owner, std::string* why);
/// Writes owner's suppression cell for row (empty: the active one) and rebinds
PartDesignExport bool configSetSuppressionCell(App::DocumentObject* owner,
                                               const std::string& row,
                                               bool suppressed,
                                               std::string* why);
/// Whether owner's suppression is configured
PartDesignExport bool configSuppressionIsConfigured(const App::DocumentObject* owner);
/// Whether obj's path is configured
PartDesignExport bool configIsConfigured(const App::DocumentObject* obj, const std::string& path);
/// The name of the input that configures obj's path (empty path: its suppression), or empty
PartDesignExport std::string configInputOf(const App::DocumentObject* obj, const std::string& path);

/// The configuration items of obj's path's context menu (empty path: its suppression's), Onshape's
PartDesignExport std::vector<App::ConfigMenuItem> configMenuItems(const App::DocumentObject* obj,
                                                                  const std::string& path);

/// A live table entry: a configured parameter (path) or suppression (empty path)
struct ConfigEntry
{
    App::DocumentObject* object = nullptr;
    std::string path;
    std::string input;
    /// Row id (or "true"/"false") -> the cell's text (a suppression's: "true"/"false")
    std::map<std::string, std::string> cells;
};
/// The table's live entries, parameters first, in the table's order; stale ones (an object
/// deleted, or its name now another object's) are left out (C2: the panel hides them)
PartDesignExport std::vector<ConfigEntry> configEntries(const StudioConfig* config);

/// The switch: sets the active values (input id or name -> row id or name, true/false, value),
/// rebinds, reconciles, makes pieces and recomputes, in one transaction (the caller's if open)
PartDesignExport bool configSetActive(App::Part* studio,
                                      const std::map<std::string, std::string>& values,
                                      std::string* why);

/// The key of the user's values (input id or name -> row id or name, a bool, a value; missing
/// inputs: the defaults), or empty with why
PartDesignExport std::string configKeyOf(const StudioConfig* config,
                                         const std::map<std::string, std::string>& values,
                                         std::string* why);
/// The key reader carries (its ConfigKey; without one, the default key), or empty when source is
/// no configured studio's
PartDesignExport std::string configReaderKey(const App::DocumentObject* reader,
                                             const App::DocumentObject* source);
/// Sets reader's ConfigKey to the key of values (missing inputs: the defaults)
PartDesignExport bool configSetReaderKey(App::DocumentObject* reader,
                                         const App::DocumentObject* source,
                                         const std::map<std::string, std::string>& values,
                                         std::string* why);
/// Why reader may not show source now (the studio's active configuration differs from the
/// reader's); empty when it may
PartDesignExport std::string configReaderError(const App::DocumentObject* reader,
                                               const App::DocumentObject* source);

/// Installs App's hooks (the expression write hook, the reader check); at module init
PartDesignExport void registerConfigurationHooks();

}  // namespace PartDesign
