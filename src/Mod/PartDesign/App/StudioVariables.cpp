// SPDX-License-Identifier: LGPL-2.1-or-later

#include <algorithm>
#include <string>
#include <unordered_map>
#include <vector>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Expression.h>
#include <App/Part.h>
#include <App/VarSet.h>
#include <App/VarSetCopy.h>
#include <App/VariableLookup.h>
#include <App/VariablePosition.h>
#include <Base/Exception.h>

#include "Studio.h"
#include "StudioVariables.h"

namespace PartDesign
{

namespace
{

using Place = App::VariablePosition::Place;

/// A part studio's set: a VarSet (not an imported copy) inside an App::Part, else null
App::Part* studioOfSet(const App::DocumentObject* holder)
{
    if (!holder || !holder->isAttachedToDocument() || !holder->isDerivedFrom<App::VarSet>()
        || holder->isDerivedFrom<App::VarSetCopy>()) {
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
    if (anchor == App::VariablePosition::atStart) {
        return index.count(user) != 0 ? Place::After : Place::Unknown;
    }
    const App::DocumentObject* row = doc->getObject(anchor.c_str());
    auto anchorAt = row ? index.find(row) : index.end();
    if (anchorAt == index.end()) {
        return Place::Lost;
    }
    auto userAt = index.find(user);
    if (userAt == index.end()) {
        return Place::Unknown;
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

/// The variables that follow a deleted row now follow the row before it
void followDeletedRow(const App::DocumentObject& deleted)
{
    App::Document* doc = deleted.getDocument();
    const char* deletedName = deleted.getNameInDocument();
    if (!doc || !deletedName || doc->isPerformingTransaction()
        || doc->testStatus(App::Document::Restoring)) {
        return;
    }
    std::unordered_map<App::Part*, std::vector<App::DocumentObject*>> sequences;
    for (App::DocumentObject* obj : doc->getObjectsOfType(App::VarSet::getClassTypeId())) {
        App::Part* studio = studioOfSet(obj);
        if (!studio || obj == &deleted) {
            continue;
        }
        auto set = static_cast<App::VarSet*>(obj);
        std::vector<std::string> names;
        for (const auto& [name, anchor] : set->VariablePositions.getValues()) {
            if (anchor == deletedName) {
                names.push_back(name);
            }
        }
        if (names.empty()) {
            continue;
        }
        auto it = sequences.find(studio);
        if (it == sequences.end()) {
            it = sequences.emplace(studio, studioSequence(doc, studio)).first;
        }
        const auto& sequence = it->second;
        auto at = std::find(sequence.begin(), sequence.end(), &deleted);
        if (at == sequence.end()) {
            // Out of the history already: the places are lost, and say so where used
            continue;
        }
        const std::string before = at == sequence.begin() ? std::string()
                                                           : (*(at - 1))->getNameInDocument();
        for (const auto& name : names) {
            App::VariablePosition::setAnchor(obj, name, before);
        }
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
