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

/// Each row's index in the studio's history. While a document recomputes, the indexes of each
/// studio are read once and kept until it ends (every expression of every row is checked)
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
    // Only rows are placed: a non-row (a set's own expression, an object outside the studio)
    // is never checked, not even against a lost place
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

/// Touches the rows of sequence whose expressions use a variable named name of any set: a place
/// that moved (or a variable now shadowing an outer one) is checked again at the next recompute,
/// also by rows that use the outer variable and so don't depend on holder
void touchUsersOf(const std::vector<App::DocumentObject*>& sequence, const std::string& name)
{
    for (App::DocumentObject* row : sequence) {
        bool uses = false;
        for (const auto& [path, expression] : row->ExpressionEngine.getExpressions()) {
            (void)path;
            if (!expression) {
                continue;
            }
            for (const auto& [id, hidden] : expression->getIdentifiers()) {
                (void)hidden;
                const App::DocumentObject* obj = id.getDocumentObject();
                if (obj && obj->isDerivedFrom<App::VarSet>() && id.getPropertyName() == name) {
                    uses = true;
                    break;
                }
            }
            if (uses) {
                break;
            }
        }
        if (uses && !row->isTouched()) {
            row->touch();
        }
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
    const auto sequence = studioSequence(holder->getDocument(), studio);
    App::DocumentObject* after = studioBarAfter(sequence);
    App::VariablePosition::setAnchor(holder, prop.getName(), after ? after->getNameInDocument() : "");
    touchUsersOf(sequence, prop.getName());
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

/// The variables of studio's sets that follow a row of leaving (rows that go away or move) now
/// follow the nearest row above it in sequence (the history before the change) that stays: the
/// variable keeps its place, as Onshape's Variable feature stays where it is. Returns the names of
/// the variables whose place changed
std::vector<std::string> keepPlaces(App::Document* doc,
                                    App::Part* studio,
                                    const std::vector<App::DocumentObject*>& sequence,
                                    const std::unordered_set<const App::DocumentObject*>& leaving)
{
    std::vector<std::string> changed;
    std::unordered_map<std::string, std::size_t> indexOfName;
    for (std::size_t i = 0; i < sequence.size(); ++i) {
        if (const char* name = sequence[i]->getNameInDocument()) {
            indexOfName.emplace(name, i);
        }
    }
    for (App::DocumentObject* obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
        if (studioOfSet(obj) != studio || leaving.count(obj) != 0) {
            continue;
        }
        auto set = static_cast<App::VarSet*>(obj);
        const auto values = set->VariablePositions.getValues();  // a copy: setAnchor changes it
        for (const auto& [name, anchor] : values) {
            auto at = indexOfName.find(anchor);
            if (at == indexOfName.end() || leaving.count(sequence[at->second]) == 0) {
                continue;
            }
            std::string above;
            for (std::size_t i = at->second; i-- > 0;) {
                if (leaving.count(sequence[i]) == 0) {
                    above = sequence[i]->getNameInDocument();
                    break;
                }
            }
            App::VariablePosition::setAnchor(obj, name, above);
            changed.push_back(name);
        }
    }
    return changed;
}

/// The variables that follow a deleted row now follow the row above it. Runs before the studio's
/// list drops a deleted owner (module start-up's order), so an owner's steps go with it
void followDeletedRow(const App::DocumentObject& deleted)
{
    App::Document* doc = deleted.getDocument();
    if (!doc || !deleted.getNameInDocument() || doc->isPerformingTransaction()
        || doc->testStatus(App::Document::Restoring)) {
        return;
    }
    std::unordered_set<App::Part*> studios;
    for (App::DocumentObject* obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
        App::Part* studio = studioOfSet(obj);
        if (studio && obj != &deleted
            && !static_cast<App::VarSet*>(obj)->VariablePositions.getValues().empty()) {
            studios.insert(studio);
        }
    }
    if (studios.empty()) {
        return;
    }
    std::unordered_set<const App::DocumentObject*> leaving {&deleted};
    for (auto step : StudioList::stepsOf(&deleted)) {
        leaving.insert(step);
    }
    for (App::Part* studio : studios) {
        keepPlaces(doc, studio, studioSequence(doc, studio), leaving);
    }
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
    app.signalBeforeRecomputeDocument.connect([](const App::Document&) { RowIndex::forget(); });
    app.signalRecomputed.connect([](const App::Document&) { RowIndex::forget(); });
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

void keepVariablePlaces(App::Document* doc,
                        App::Part* studio,
                        const std::vector<App::DocumentObject*>& before,
                        const std::vector<App::DocumentObject*>& rows)
{
    if (!doc || doc->isPerformingTransaction()) {
        return;
    }
    std::unordered_set<const App::DocumentObject*> moved;
    for (App::DocumentObject* row : rows) {
        moved.insert(row);
        for (auto step : StudioList::stepsOf(row)) {
            moved.insert(step);
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
    if (names.empty()) {
        return;
    }
    const auto after = studioSequence(doc, studio);
    for (const auto& name : names) {
        touchUsersOf(after, name);
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
    touchUsersOf(sequence, name);
}

}  // namespace PartDesign
