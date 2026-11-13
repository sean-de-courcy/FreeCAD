// SPDX-License-Identifier: LGPL-2.1-or-later

#pragma once

// The studio's ordered feature list, the only truth of its history (FreeCAD-CH ops#654,
// notes/parts-design.md 3.2 and 10.8). Each Body's chain is a projection of the list, rebuilt by
// reconcile() inside the edit's transaction: undo, redo and reopen need no handlers of their own.
//
// An entry is one of:
// - an owner (a studio feature): an object outside every Body, computing only its tool (a
//   PartDesign feature from S2; in S1's tests a shape object carrying a dynamic StudioScope). It
//   projects to one step in each part its StudioScope resolves to at its place, keyed by (owner,
//   part) and placed at the owner's place in the list;
// - a member of a Body (a native feature, a sketch, a datum): it projects to itself, in its Body.
// The bar: entries at and after Bar are rolled back.
//
// Parts are named by part id (Body::StudioPartId), never by a link to the Body
// (notes/one-history-design.md 5 and 9): a scope is an ordered list of ids; an id resolves to the
// live Body that has it, or to every piece descended from it (StudioParentId); an id whose part
// is gone or absorbed resolves to nothing. A Body's FeatureBase and a MultiTransform's steps are
// not entries: they keep their place in the Group.

#include <map>
#include <string>
#include <vector>

#include <App/DocumentObject.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class Part;
}

namespace PartDesign
{

class Body;
class Feature;

class PartDesignExport StudioList: public App::DocumentObject
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::StudioList);

public:
    StudioList();

    /// The history, in order: owners and Body members (Hidden scope: no dependency)
    App::PropertyLinkListHidden Entries;
    /// Entries [0, Bar) are active, the others rolled back; -1 puts the bar at the end
    App::PropertyInteger Bar;

    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderStudioList";
    }
    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;

    /// The list of studio (null: the document's top level); with create, made (and adopted from
    /// the derived order, studioSequence()) when missing. No transaction is opened here
    static StudioList* of(App::Document* doc, App::Part* studio, bool create = false);
    /// The list that holds entry, or null
    static StudioList* holding(const App::DocumentObject* entry);
    /// The studio (App::Part, or null for the top level) this list belongs to
    App::Part* studio() const;

    /** @name List edits. Each edits Entries and Bar only; call reconcile() after (the Python API
     * does both). index -1 is the end. */
    //@{
    void insertEntry(App::DocumentObject* entry, int index);
    void removeEntry(App::DocumentObject* entry);
    void moveEntry(App::DocumentObject* entry, int index);
    void setBarIndex(int index);
    /// The bar as an index into Entries (Bar, or the size when at the end)
    int barIndex() const;
    //@}

    /// One slot of a Body's projected chain
    struct Slot
    {
        App::DocumentObject* entry = nullptr;  ///< the list entry (owner or the member itself)
        bool isStep = false;                   ///< entry is an owner: the slot is its step
        bool suppressed = false;               ///< the owner is suppressed
        bool held = false;                     ///< at or after the bar
    };
    struct Projection
    {
        /// Each Body's members and steps in history order
        std::map<Body*, std::vector<Slot>> chains;
        /// Why the list can't be projected (an entry in two places, a member of a Body outside
        /// the studio), or empty
        std::vector<std::string> errors;
        /// The owners with a scope none of whose ids resolves at their place: they act on nothing
        /// ("No merge scope selected"; an owner fails so from S2)
        std::vector<App::DocumentObject*> unresolved;
    };
    /// The desired chains, from Entries, Bar and each owner's StudioScope. Pure: changes nothing.
    /// Body members the list doesn't hold yet are left out (reconcile() adopts them first)
    Projection project() const;

    /** Makes the document match project(): creates the missing steps (a deterministic name, see
     * stepName()), removes the steps whose owner or part is gone or dropped from the scope,
     * reorders each Body's Group to the projected order (Body::insertObject keeps BaseFeature
     * links right), sets each step's values from its owner, and each Body's Tip from the bar.
     * Body members the list doesn't hold are adopted first, after the entry before them in their
     * Body. No recompute; no transaction. Returns false and sets why when the projection has
     * errors (nothing is changed then) */
    bool reconcile(std::string* why = nullptr);

    /// The step of owner in body, or null
    static Feature* stepOf(const App::DocumentObject* owner, const Body* body);
    /// Every step of owner, in its parts' order
    static std::vector<Feature*> stepsOf(const App::DocumentObject* owner);
    /// The object name of owner's step in body: a function of the two names only
    static std::string stepName(const App::DocumentObject* owner, const Body* body);
    /// Whether obj is a step: a Body member made by reconcile (a FeatureApply, or a feature with
    /// a StudioOwner). Not an entry
    static bool isStep(const App::DocumentObject* obj);

protected:
    void onChanged(const App::Property* prop) override;

private:
    /// project() on entries and bar (an index, or -1 for the end) instead of Entries and Bar
    Projection projectEntries(const std::vector<App::DocumentObject*>& entries, int bar) const;
};

/// Whether obj is a studio feature: held by a list, and not a member of any Body
PartDesignExport bool isStudioOwner(const App::DocumentObject* obj);
/// The part id of body: its StudioPartId, or its object name while it has none (adoption writes
/// that name into StudioPartId at the next reconcile)
PartDesignExport std::string studioPartId(const Body* body);
/// owner's scope as stored: its StudioScope part ids, in order (empty without the property)
PartDesignExport std::vector<std::string> studioScopeIds(const App::DocumentObject* owner);
/// Sets owner's StudioScope to ids (adding it as a hidden dynamic property to an owner without
/// one); no reconcile, and no change when equal
PartDesignExport void setStudioScopeIds(
    App::DocumentObject* owner,
    const std::vector<std::string>& ids
);
/// The parts (live Bodies of the studio) owner acts on at its place in its list: each id of its
/// StudioScope resolved, in order, without repeats. An id resolves to the Body that has it and the
/// pieces descended from it; to nothing when that part is gone, absorbed (MergedInto) or made
/// later in the list (StudioMadeBy)
PartDesignExport std::vector<Body*> studioScopeOf(const App::DocumentObject* owner);
/// Sets owner's scope to the ids of parts (no reconcile)
PartDesignExport void setStudioScope(App::DocumentObject* owner, const std::vector<Body*>& parts);
/// The type of the step owner makes in each part: "PartDesign::FeatureApply" for every feature
/// that makes a tool; the owner's own type for dress-ups, Shell, Draft and Thickness (P8a)
PartDesignExport std::string studioStepType(const App::DocumentObject* owner);

}  // namespace PartDesign
