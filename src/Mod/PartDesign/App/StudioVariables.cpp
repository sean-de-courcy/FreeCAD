// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Expression.h>
#include <App/Part.h>
#include <App/VarSet.h>
#include <App/VariableLookup.h>
#include <App/VariablePosition.h>
#include <Base/Exception.h>

#include "Feature.h"
#include "Studio.h"
#include "StudioList.h"
#include "StudioVariables.h"

namespace PartDesign
{

namespace
{

using Place = App::VariablePosition::Place;

/// A part studio's set: a plain App::VarSet inside an App::Part, else null. Not an imported copy
/// (VarSetCopy) nor a configuration (StudioConfig): Onshape's configuration inputs are seen by the
/// whole studio (CF5b), they are no rows of its history
App::Part* studioOfSet(const App::DocumentObject* holder)
{
    if (!holder || !holder->isAttachedToDocument()
        || holder->getTypeId() != App::VarSet::getClassTypeId()) {
        return nullptr;
    }
    return App::Part::getPartOfObject(holder, true);
}

/// The list entries of studio that are no rows of studioSequence() (studio features, "owners"),
/// each with its steps: an owner acts where its steps are
std::vector<std::pair<App::DocumentObject*, std::vector<Feature*>>> ownersOf(App::Document* doc,
                                                                            App::Part* studio)
{
    std::vector<std::pair<App::DocumentObject*, std::vector<Feature*>>> owners;
    if (const StudioList* list = StudioList::of(doc, studio)) {
        for (App::DocumentObject* entry : list->Entries.getValues()) {
            if (entry && isStudioOwner(entry)) {
                owners.emplace_back(entry, StudioList::stepsOf(entry));
            }
        }
    }
    return owners;
}

/// The names of the studio's rows, in history order
std::vector<std::string> rowNames(App::Document* doc, App::Part* studio)
{
    std::vector<std::string> names;
    for (App::DocumentObject* row : studioSequence(doc, studio)) {
        if (const char* name = row->getNameInDocument()) {
            names.emplace_back(name);
        }
    }
    return names;
}

/// Each row's index in the studio's history, and each owner's (its first step's: the owner is
/// above whatever follows its place). While a document recomputes, the indexes of each studio are
/// read once and kept until it ends (every expression of every row is checked)
class RowIndex
{
public:
    using Index = std::unordered_map<const App::DocumentObject*, std::size_t>;

    static const Index& of(App::Document* doc, App::Part* studio)
    {
        static Index fresh;
        if (!doc->testStatus(App::Document::Recomputing)) {
            fresh = read(doc, studio);
            return fresh;
        }
        auto& cache = kept();
        auto it = cache.find(studio);
        if (it == cache.end()) {
            it = cache.emplace(studio, read(doc, studio)).first;
        }
        return it->second;
    }

    static void forget()
    {
        kept().clear();
    }

private:
    static std::unordered_map<const App::Part*, Index>& kept()
    {
        static std::unordered_map<const App::Part*, Index> cache;
        return cache;
    }

    static Index read(App::Document* doc, App::Part* studio)
    {
        Index index;
        const auto sequence = studioSequence(doc, studio);
        for (std::size_t i = 0; i < sequence.size(); ++i) {
            index.emplace(sequence[i], i);
        }
        for (const auto& [owner, steps] : ownersOf(doc, studio)) {
            std::size_t first = sequence.size();
            for (Feature* step : steps) {
                auto at = index.find(step);
                if (at != index.end() && at->second < first) {
                    first = at->second;
                }
            }
            if (first < sequence.size()) {
                index.emplace(owner, first);
            }
        }
        return index;
    }
};

Place placeRow(const App::DocumentObject* user, const App::DocumentObject* holder, const std::string& anchor)
{
    App::Part* studio = studioOfSet(holder);
    if (!studio || !user || !user->isAttachedToDocument()) {
        return Place::Unknown;
    }
    App::Document* doc = holder->getDocument();
    const auto& index = RowIndex::of(doc, studio);
    // Only rows (and owners) are placed: a non-row (a set's own expression, an object outside the
    // studio) is never checked, not even against a lost place
    auto userAt = index.find(user);
    if (userAt == index.end()) {
        return Place::Unknown;
    }
    if (anchor == App::VariablePosition::atStart) {
        return Place::After;
    }
    const App::DocumentObject* row = doc->getObject(anchor.c_str());
    auto anchorAt = row ? index.find(row) : index.end();
    if (anchorAt == index.end()) {
        return Place::Lost;
    }
    return userAt->second <= anchorAt->second ? Place::Before : Place::After;
}

/// Whether places may change now: not while a file is read or an undo or redo replays them
bool mayPlace(const App::DocumentObject* holder)
{
    App::Document* doc = holder ? holder->getDocument() : nullptr;
    return doc && !doc->testStatus(App::Document::Restoring)
        && !doc->testStatus(App::Document::Importing) && !doc->isPerformingTransaction();
}

/// Whether obj's expressions use a variable named name of any set
bool usesName(const App::DocumentObject* obj, const std::string& name)
{
    for (const auto& [path, expression] : obj->ExpressionEngine.getExpressions()) {
        (void)path;
        if (!expression) {
            continue;
        }
        for (const auto& [id, hidden] : expression->getIdentifiers()) {
            (void)hidden;
            const App::DocumentObject* holder = id.getDocumentObject();
            if (holder && holder->isDerivedFrom<App::VarSet>() && id.getPropertyName() == name) {
                return true;
            }
        }
    }
    return false;
}

/// Touches the studio's rows and owners whose expressions use a variable named name of any set:
/// a place that moved (or a variable now shadowing an outer one) is checked again at the next
/// recompute, also by rows that use the outer variable and so don't depend on its set
void touchUsersOf(App::Document* doc, App::Part* studio, const std::string& name)
{
    std::vector<App::DocumentObject*> users = studioSequence(doc, studio);
    for (const auto& [owner, steps] : ownersOf(doc, studio)) {
        (void)steps;
        users.push_back(owner);
    }
    for (App::DocumentObject* user : users) {
        if (!user->isTouched() && usesName(user, name)) {
            user->touch();
        }
    }
}

/// The studios of doc whose sets have saved places
std::unordered_set<App::Part*> placedStudios(App::Document* doc)
{
    std::unordered_set<App::Part*> studios;
    for (App::DocumentObject* obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
        App::Part* studio = studioOfSet(obj);
        if (studio && !static_cast<App::VarSet*>(obj)->VariablePositions.getValues().empty()) {
            studios.insert(studio);
        }
    }
    return studios;
}

using Snapshot = std::unordered_map<const App::Part*, std::vector<std::string>>;

/// Each placed studio's row names at the end of the last recompute, per document: the history a
/// delete through any path (a Body's removeObject first, the list's reconcile) left behind
std::unordered_map<const App::Document*, Snapshot>& snapshots()
{
    static std::unordered_map<const App::Document*, Snapshot> all;
    return all;
}

/** Keeps the places of studio's variables whose row leaves its place: a row of leaving (deleted
 * or moved), or a row no longer in the history. Such a variable now follows the nearest row
 * above it in before (the row names before the change) that stays in place, or the start: it
 * keeps its place, as Onshape's Variable feature stays where it is. A row unknown to before is
 * left alone (its users say the place is lost)
 */
void keepPlaces(App::Document* doc,
                App::Part* studio,
                const std::vector<std::string>& before,
                const std::unordered_set<std::string>& leaving)
{
    std::unordered_set<std::string> staying;
    for (App::DocumentObject* row : studioSequence(doc, studio)) {
        const char* name = row->getNameInDocument();
        if (name && leaving.count(name) == 0) {
            staying.insert(name);
        }
    }
    std::unordered_map<std::string, std::size_t> indexOfName;
    for (std::size_t i = 0; i < before.size(); ++i) {
        indexOfName.emplace(before[i], i);
    }
    for (App::DocumentObject* obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
        if (studioOfSet(obj) != studio) {
            continue;
        }
        const auto values = static_cast<App::VarSet*>(obj)->VariablePositions.getValues();  // a copy
        for (const auto& [name, anchor] : values) {
            if (anchor == App::VariablePosition::atStart || staying.count(anchor) != 0) {
                continue;
            }
            auto at = indexOfName.find(anchor);
            if (at == indexOfName.end()) {
                continue;
            }
            std::string above;
            for (std::size_t i = at->second; i-- > 0;) {
                if (staying.count(before[i]) != 0) {
                    above = before[i];
                    break;
                }
            }
            App::VariablePosition::setAnchor(obj, name, above);
        }
    }
}

/// The names of row's whole entry: row, its steps, and (a step) its owner and the owner's steps
void addEntryNames(App::Document* doc,
                   App::Part* studio,
                   const App::DocumentObject* row,
                   std::unordered_set<std::string>& names)
{
    if (const char* name = row->getNameInDocument()) {
        names.insert(name);
    }
    for (Feature* step : StudioList::stepsOf(row)) {
        names.insert(step->getNameInDocument());
    }
    for (const auto& [owner, steps] : ownersOf(doc, studio)) {
        if (std::find(steps.begin(), steps.end(), row) != steps.end()) {
            names.insert(owner->getNameInDocument());
            for (Feature* step : steps) {
                names.insert(step->getNameInDocument());
            }
        }
    }
}

/// The variables that follow a deleted row now follow the row above it. Runs before the studio's
/// list drops a deleted owner (module start-up's order), so an owner's steps go with it. A delete
/// that took the row out of the history first (a Body's removeObject, the list's reconcile) is
/// repaired before the next recompute instead (repairBeforeRecompute())
void followDeletedRow(const App::DocumentObject& deleted)
{
    App::Document* doc = deleted.getDocument();
    if (!doc || !deleted.getNameInDocument() || doc->isPerformingTransaction()
        || doc->testStatus(App::Document::Restoring)) {
        return;
    }
    if (deleted.isDerivedFrom<App::Part>()) {
        auto it = snapshots().find(doc);
        if (it != snapshots().end()) {
            it->second.erase(static_cast<const App::Part*>(&deleted));
        }
    }
    for (App::Part* studio : placedStudios(doc)) {
        if (studio == &deleted) {
            continue;
        }
        std::unordered_set<std::string> leaving;
        addEntryNames(doc, studio, &deleted, leaving);
        keepPlaces(doc, studio, rowNames(doc, studio), leaving);
    }
}

/// Before a recompute: a variable whose row left the history since the last one follows the
/// nearest row above it that stayed (the last recompute's snapshot)
void repairBeforeRecompute(const App::Document& constDoc)
{
    RowIndex::forget();
    auto doc = const_cast<App::Document*>(&constDoc);
    if (doc->isPerformingTransaction() || doc->testStatus(App::Document::Restoring)) {
        return;
    }
    auto it = snapshots().find(doc);
    if (it == snapshots().end()) {
        return;
    }
    for (App::Part* studio : placedStudios(doc)) {
        auto snap = it->second.find(studio);
        if (snap != it->second.end()) {
            keepPlaces(doc, studio, snap->second, {});
        }
    }
}

/// After a recompute: the placed studios' histories, for the next repair
void snapshotAfterRecompute(const App::Document& constDoc)
{
    RowIndex::forget();
    auto doc = const_cast<App::Document*>(&constDoc);
    auto& mine = snapshots()[doc];
    mine.clear();
    for (App::Part* studio : placedStudios(doc)) {
        mine.emplace(studio, rowNames(doc, studio));
    }
}

/// A variable added to a part studio's set goes where the studio's bar is
void placeAdded(const App::Property& prop)
{
    auto holder = dynamic_cast<App::DocumentObject*>(prop.getContainer());
    App::Part* studio = studioOfSet(holder);
    if (!studio || !mayPlace(holder) || !prop.getName()) {
        return;
    }
    App::Document* doc = holder->getDocument();
    App::DocumentObject* after = studioBarAfter(studioSequence(doc, studio));
    App::VariablePosition::setAnchor(holder, prop.getName(), after ? after->getNameInDocument() : "");
    touchUsersOf(doc, studio, prop.getName());
    snapshots()[doc][studio] = rowNames(doc, studio);
}

void placeRenamed(const App::Property& prop, const char* oldName)
{
    auto holder = dynamic_cast<App::DocumentObject*>(prop.getContainer());
    if (!oldName || !prop.getName() || !studioOfSet(holder) || !mayPlace(holder)) {
        return;
    }
    const std::string anchor = App::VariablePosition::anchorOf(holder, oldName);
    if (!anchor.empty()) {
        App::VariablePosition::clearAnchor(holder, oldName);
        App::VariablePosition::setAnchor(holder, prop.getName(), anchor);
    }
}

void placeRemoved(const App::Property& prop)
{
    auto holder = dynamic_cast<App::DocumentObject*>(prop.getContainer());
    if (!prop.getName() || !studioOfSet(holder) || !mayPlace(holder)) {
        return;
    }
    App::VariablePosition::clearAnchor(holder, prop.getName());
}

/// An imported set's places name rows of the file it came from
void forgetImported(const std::vector<App::DocumentObject*>& objs)
{
    for (App::DocumentObject* obj : objs) {
        if (auto set = freecad_cast<App::VarSet*>(obj)) {
            if (!set->VariablePositions.getValues().empty()) {
                set->VariablePositions.setValue();
            }
        }
    }
}

}  // namespace

void registerStudioVariables()
{
    App::VariablePosition::setOrder(placeRow);
    auto& app = App::GetApplication();
    app.signalAppendDynamicProperty.connect(placeAdded);
    app.signalRenameDynamicProperty.connect(placeRenamed);
    app.signalRemoveDynamicProperty.connect(placeRemoved);
    app.signalDeletedObject.connect(followDeletedRow);
    app.signalBeforeRecomputeDocument.connect(repairBeforeRecompute);
    app.signalRecomputed.connect(snapshotAfterRecompute);
    app.signalDeleteDocument.connect([](const App::Document& doc) { snapshots().erase(&doc); });
    auto watch = [](App::Document& doc) {
        doc.signalImportObjects.connect(
            [](const std::vector<App::DocumentObject*>& objs, Base::XMLReader&) {
                forgetImported(objs);
            }
        );
    };
    for (auto doc : app.getDocuments()) {
        watch(*doc);
    }
    app.signalNewDocument.connect([watch](const App::Document& doc, bool) {
        watch(const_cast<App::Document&>(doc));
    });
}

std::vector<std::string> studioRowNames(App::Document* doc, App::Part* studio)
{
    return rowNames(doc, studio);
}

void keepVariablePlaces(App::Document* doc,
                        App::Part* studio,
                        const std::vector<std::string>& before,
                        const std::vector<App::DocumentObject*>& rows)
{
    if (!doc || doc->isPerformingTransaction()) {
        return;
    }
    std::unordered_set<std::string> moved;
    for (App::DocumentObject* row : rows) {
        if (row && row->isAttachedToDocument()) {
            addEntryNames(doc, studio, row, moved);
        }
    }
    keepPlaces(doc, studio, before, moved);
    std::unordered_set<std::string> names;
    for (App::DocumentObject* obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
        if (studioOfSet(obj) == studio) {
            for (const auto& [name, anchor] : static_cast<App::VarSet*>(obj)->VariablePositions.getValues()) {
                (void)anchor;
                names.insert(name);
            }
        }
    }
    for (const auto& name : names) {
        touchUsersOf(doc, studio, name);
    }
    if (!names.empty()) {
        snapshots()[doc][studio] = rowNames(doc, studio);
    }
}

App::DocumentObject* variablePosition(const App::DocumentObject* holder, const std::string& name)
{
    const std::string anchor = App::VariablePosition::anchorOf(holder, name);
    if (anchor.empty() || anchor == App::VariablePosition::atStart || !holder->getDocument()) {
        return nullptr;
    }
    return holder->getDocument()->getObject(anchor.c_str());
}

void setVariablePosition(App::DocumentObject* holder, const std::string& name, App::DocumentObject* after)
{
    App::Part* studio = studioOfSet(holder);
    if (!studio) {
        throw Base::ValueError(
            "only the variables of a part studio's VarSet (inside an App::Part) have a place in "
            "its history"
        );
    }
    if (!App::VariableLookup::isVariable(holder, name)) {
        throw Base::ValueError(
            "no variable named " + name + " in " + std::string(holder->Label.getValue())
        );
    }
    const auto sequence = studioSequence(holder->getDocument(), studio);
    if (after && std::find(sequence.begin(), sequence.end(), after) == sequence.end()) {
        throw Base::ValueError(
            std::string(after->Label.getValue()) + " is no feature of the part studio's history"
        );
    }
    const std::string anchor = after ? after->getNameInDocument() : "";
    if ((anchor.empty() ? std::string(App::VariablePosition::atStart) : anchor)
        == App::VariablePosition::anchorOf(holder, name)) {
        return;
    }
    App::VariablePosition::setAnchor(holder, name, anchor);
    touchUsersOf(holder->getDocument(), studio, name);
    snapshots()[holder->getDocument()][studio] = rowNames(holder->getDocument(), studio);
}

}  // namespace PartDesign
