// SPDX-License-Identifier: LGPL-2.1-or-later

// The user's history operations as list edits (FreeCAD-CH ops#654, S1 and S3): each edits the
// studio's list and reconciles. No transaction (the caller's), no recompute.

#include <algorithm>

#include <App/Document.h>
#include <App/Part.h>
#include <App/PropertyStandard.h>
#include <Base/Exception.h>

#include "Body.h"
#include "Pieces.h"
#include "StudioConfig.h"
#include "StudioEdit.h"
#include "StudioList.h"

namespace PartDesign
{

// FreeCAD-CH ops#654 S3: Studio.cpp's drag of list entries (the bar kept, reads refused)
bool moveStudioEntries(StudioList* list,
                       const std::vector<App::DocumentObject*>& block,
                       App::DocumentObject* after,
                       bool hinted,
                       App::DocumentObject* bar,
                       std::string* why,
                       bool* changed);

namespace
{

bool refuse(std::string* why, const std::string& text)
{
    if (why) {
        *why = text;
    }
    return false;
}

std::string quoted(const App::DocumentObject* obj)
{
    return std::string("'") + (obj ? obj->Label.getValue() : "?") + "'";
}

/// The studio entry belongs to: its Body's, else the App::Part holding it (null: the top level)
App::Part* studioOfEntry(const App::DocumentObject* entry)
{
    if (auto body = Body::findBodyOf(entry)) {
        App::Part* studio = nullptr;
        Part::BodyBase::studioOf(body, studio);
        return studio;
    }
    return App::Part::getPartOfObject(entry, /*recursive=*/true);
}

/// The list obj names: the list itself, the one holding obj, a Body's or a studio's
StudioList* listNamedBy(App::DocumentObject* obj)
{
    if (!obj) {
        return nullptr;
    }
    if (auto list = freecad_cast<StudioList*>(obj)) {
        return list;
    }
    if (auto list = StudioList::holding(obj)) {
        return list;
    }
    if (auto body = freecad_cast<Body*>(obj)) {
        App::Part* studio = nullptr;
        if (Part::BodyBase::studioOf(body, studio)) {
            return StudioList::of(body->getDocument(), studio);
        }
        return nullptr;
    }
    if (auto studio = freecad_cast<App::Part*>(obj)) {
        return StudioList::of(studio->getDocument(), studio);
    }
    return nullptr;
}

/// The list holding entry, or a refusal
StudioList* holdingOrRefuse(const App::DocumentObject* entry, std::string* why)
{
    auto list = StudioList::holding(entry);
    if (!list) {
        refuse(why, quoted(entry) + " is not in a studio's history");
    }
    return list;
}

bool reconciled(StudioList* list, std::string* why)
{
    return list->reconcile(why);
}

template<typename Edit>
bool edited(Edit edit, std::string* why)
{
    try {
        return edit();
    }
    catch (const Base::Exception& e) {
        return refuse(why, e.what());
    }
}

}  // namespace

bool studioInsert(App::DocumentObject* entry, int index, std::string* why)
{
    if (!entry || !entry->getDocument()) {
        return refuse(why, "Nothing to insert into the history");
    }
    if (auto list = StudioList::holding(entry)) {
        const auto& entries = list->Entries.getValues();
        const auto pos = std::find(entries.begin(), entries.end(), entry) - entries.begin();
        return refuse(why, quoted(entry) + " is in the history already, at "
                               + std::to_string(pos + 1));
    }
    if (StudioList::isStep(entry) || entry->isDerivedFrom<Part::BodyBase>()
        || entry->isDerivedFrom<App::Part>() || entry->isDerivedFrom<StudioList>()) {
        return refuse(why, quoted(entry) + " can't be a row of the history");
    }
    return edited([&] {
        StudioList* list = StudioList::of(entry->getDocument(), studioOfEntry(entry), true);
        list->insertEntry(entry, index < 0 ? list->barIndex() : index);
        return reconciled(list, why);
    }, why);
}

bool studioRemove(App::DocumentObject* entry, std::string* why)
{
    StudioList* list = holdingOrRefuse(entry, why);
    if (!list) {
        return false;
    }
    return edited([&] {
        releasePiecesOf(entry);  // P6p: the parts it made go with it, or stay never live
        list->removeEntry(entry);
        if (Body* body = Body::findBodyOf(entry)) {
            body->removeObject(entry);
        }
        return reconciled(list, why);
    }, why);
}

bool studioMove(App::DocumentObject* entry, int index, std::string* why)
{
    StudioList* list = holdingOrRefuse(entry, why);
    if (!list) {
        return false;
    }
    // FreeCAD-CH ops#654 S3: a drag, Onshape's: refused above what entry reads or below what
    // reads it; the bar stays after the entry it followed. index as moveEntry() reads it: a place
    // in the list without entry
    return edited([&] {
        auto others = list->Entries.getValues();
        std::erase(others, entry);
        const int size = static_cast<int>(others.size());
        if (index < 0 || index > size) {
            index = size;
        }
        App::DocumentObject* after = index > 0 ? others[index - 1] : nullptr;
        bool changed = false;
        return moveStudioEntries(list, {entry}, after, false, nullptr, why, &changed);
    }, why);
}

bool studioSetBar(App::DocumentObject* anyEntry, int index, std::string* why)
{
    StudioList* list = listNamedBy(anyEntry);
    if (!list) {
        return refuse(why, quoted(anyEntry) + " names no studio history");
    }
    return edited([&] {
        list->setBarIndex(index);
        return reconciled(list, why);
    }, why);
}

bool studioSetScope(App::DocumentObject* owner, const std::vector<Body*>& parts, std::string* why)
{
    StudioList* list = holdingOrRefuse(owner, why);
    if (!list) {
        return false;
    }
    if (Body::findBodyOf(owner)) {
        return refuse(why, quoted(owner) + " is a member of a part: it has no scope");
    }
    return edited([&] {
        setStudioScope(owner, parts);
        return reconciled(list, why);
    }, why);
}

bool studioSetScopeIds(
    App::DocumentObject* owner,
    const std::vector<std::string>& ids,
    std::string* why
)
{
    StudioList* list = holdingOrRefuse(owner, why);
    if (!list) {
        return false;
    }
    if (Body::findBodyOf(owner)) {
        return refuse(why, quoted(owner) + " is a member of a part: it has no scope");
    }
    return edited([&] {
        setStudioScopeIds(owner, ids);
        return reconciled(list, why);
    }, why);
}

bool studioSuppress(App::DocumentObject* entry, bool on, std::string* why)
{
    // FreeCAD-CH ops#671: a configured suppression's Suppress writes the active cell (CF4)
    if (configSuppressionIsConfigured(entry)) {
        return configSetSuppressionCell(entry, std::string(), on, why);
    }
    StudioList* list = holdingOrRefuse(entry, why);
    if (!list) {
        return false;
    }
    return edited([&] {
        auto prop = freecad_cast<App::PropertyBool*>(entry->getPropertyByName("Suppressed"));
        if (!prop) {
            if (Body::findBodyOf(entry)) {
                return refuse(why, quoted(entry) + " can't be suppressed");
            }
            prop = static_cast<App::PropertyBool*>(entry->addDynamicProperty(
                "App::PropertyBool",
                "Suppressed",
                "Studio",
                "Suppressed: its steps pass their base through (ops#654)",
                App::Prop_Hidden
            ));
        }
        if (prop->getValue() != on) {
            prop->setValue(on);
        }
        return reconciled(list, why);
    }, why);
}

}  // namespace PartDesign
