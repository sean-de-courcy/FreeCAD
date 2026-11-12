// SPDX-License-Identifier: LGPL-2.1-or-later

// The cache of other configurations' shapes (FreeCAD-CH ops#671 C3): see ConfigCache.h and
// notes/configurations-design.md 12.

#include <atomic>
#include <chrono>
#include <memory>
#include <optional>
#include <set>
#include <string_view>

#include <App/Application.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/DocumentObjectGroup.h>
#include <App/ElementNamingUtils.h>
#include <App/Link.h>
#include <App/Part.h>
#include <App/PropertyLinks.h>
#include <Base/Console.h>
#include <Base/FileInfo.h>
#include <Base/Tools.h>
#include <Base/Sequencer.h>

#include "Body.h"
#include "ConfigCache.h"
#include "StudioConfig.h"
#include "StudioList.h"

namespace PartDesign
{

PROPERTY_SOURCE(PartDesign::ConfigShape, Part::Feature)

namespace
{

std::atomic<int> liveEntries {0};
int inPass = 0;
int inSwitch = 0;
bool passScheduled = false;
ConfigCacheStats stats;
std::function<void(std::function<void()>)> scheduler;

/// Studio documents edited since their last recompute's stable point (by name)
std::set<std::string> studioEditDocs;
/// Instances that asked for a pass: document name -> object names
std::map<std::string, std::set<std::string>> requests;

enum class Event
{
    None,
    Recompute,
    Commit,
    Other  // undo, redo, abort
};
std::map<const App::Document*, Event> lastEvent;
/// The documents whose objects a document's last recompute ran (by name): a recompute also runs the
/// objects of other documents its objects depend on, and only the document recomputed signals it (C3h)
std::map<const App::Document*, std::set<std::string>> recomputedDocs;

const char* GroupMark = "ConfigCacheGroup";

bool isTemp(const App::Document* doc)
{
    return !doc || doc->testStatus(App::Document::TempDoc);
}

std::string studioName(const StudioConfig* cfg)
{
    App::Part* studio = cfg ? cfg->studio() : nullptr;
    return studio ? studio->getNameInDocument() : std::string();
}

std::string studioLabel(const StudioConfig* cfg)
{
    App::Part* studio = cfg ? cfg->studio() : nullptr;
    return studio ? "'" + std::string(studio->Label.getValue()) + "'" : std::string("of the document");
}

App::Link* instanceLink(const App::DocumentObject* obj)
{
    return freecad_cast<App::Link*>(const_cast<App::DocumentObject*>(obj));
}

App::PropertyXLink* linkedProperty(App::Link* link)
{
    return freecad_cast<App::PropertyXLink*>(link->getLinkedObjectProperty());
}

/// What the cache writes (C3i): its entries and their group, and an instance's target and the
/// text that names its part. Written in a Document::UnrecordedWrites scope: derived data, which no
/// undo step records and which never clears Redo (coordinator c752's ruling A, 11-12)
bool inRetarget = false;  ///< an instance's LinkedObject is being set to its entry or Body

bool derivedWrite(const App::DocumentObject& obj, const App::Property& prop)
{
    // The retarget rewrites the references that follow the instance (App::followLinkRetarget:
    // a joint's, an attachment's): derived from the row too (coordinator c752, 11-12)
    if (inRetarget && prop.isDerivedFrom<App::PropertyLinkBase>()) {
        return true;
    }
    if (obj.isDerivedFrom<ConfigShape>()) {
        return true;
    }
    const char* objName = obj.getNameInDocument();
    if (objName && std::string_view(objName).starts_with("ConfigCache")) {
        return true;
    }
    // _LinkTouched: the link's recompute marker for its view provider, touched only by its own
    // execute, which in the GUI runs inside the pass's scope outside a document's Recomputing status
    const std::string_view name = prop.getName() ? prop.getName() : "";
    return obj.isDerivedFrom<App::Link>()
        && (name == "LinkedObject" || name == "ConfigDoc" || name == "ConfigStudio" || name == "ConfigPartId"
            || name == "_LinkTouched");
}

/// derivedWrite, counting what it refuses: each is a write the scope warns about (stats)
bool derivedWriteCounted(const App::DocumentObject& obj, const App::Property& prop)
{
    const bool derived = derivedWrite(obj, prop);
    if (!derived) {
        ++stats.foreignWrites;
    }
    return derived;
}

/// The instance's own property: never getPropertyByName, which an App::Link answers with its
/// linked object's property when it has none (an entry's ConfigKey, C3f)
App::PropertyString* stringProperty(App::DocumentObject* obj, const char* name, bool add)
{
    auto prop = freecad_cast<App::PropertyString*>(obj->getDynamicPropertyByName(name));
    if (!prop && add) {
        prop = static_cast<App::PropertyString*>(obj->addDynamicProperty(
            "App::PropertyString", name, "Configuration",
            "The configured studio's part this instance shows (ops#671)", App::Prop_Hidden));
    }
    return prop;
}

std::string stringValue(const App::DocumentObject* obj, const char* name)
{
    auto prop = freecad_cast<App::PropertyString*>(obj->getDynamicPropertyByName(name));
    return prop ? prop->getValue() : std::string();
}

void setString(App::DocumentObject* obj, const char* name, const std::string& value)
{
    auto prop = stringProperty(obj, name, false);
    if (!prop || prop->getValue() != value) {
        stringProperty(obj, name, true)->setValue(value);  // "" too: a document's own studio
    }
}

/// What an instance stands for: a studio (its document and name) and a part id. Its link can
/// break (a switch removes a piece's Body), so the instance keeps them as text too
struct InstancePart
{
    App::Document* doc = nullptr;
    StudioConfig* cfg = nullptr;  ///< null: the studio is gone or no longer configured
    std::string studio;
    std::string partId;
    Body* body = nullptr;  ///< the live Body with that id (null: the active configuration has none)
};

void noteInstance(App::DocumentObject* link, const InstancePart& p)
{
    setString(link, "ConfigDoc", p.doc->getName());
    setString(link, "ConfigStudio", p.studio);
    setString(link, "ConfigPartId", p.partId);
}

Body* liveBody(App::Document* doc, const StudioConfig* cfg, const std::string& partId)
{
    for (auto obj : doc->getObjectsOfType(Body::getClassTypeId())) {
        auto body = static_cast<Body*>(obj);
        if (configObjectConfig(body) == cfg && studioPartId(body) == partId) {
            return body;
        }
    }
    return nullptr;
}

std::optional<InstancePart> resolveInstance(const App::DocumentObject* obj)
{
    auto link = instanceLink(obj);
    if (!link) {
        return std::nullopt;
    }
    auto prop = linkedProperty(link);
    auto target = prop ? prop->getValue() : nullptr;
    InstancePart p;
    if (auto e = freecad_cast<ConfigShape*>(target)) {
        p.doc = e->getDocument();
        p.studio = e->ConfigStudio.getValue();
        p.partId = e->ConfigPartId.getValue();
    }
    else if (auto body = freecad_cast<Body*>(target); body && configSourceConfig(body)) {
        p.doc = body->getDocument();
        p.cfg = configSourceConfig(body);
        p.studio = studioName(p.cfg);
        p.partId = studioPartId(body);
        p.body = body;
        return p;
    }
    else if (!target && !stringValue(link, "ConfigPartId").empty()) {
        p.doc = App::GetApplication().getDocument(stringValue(link, "ConfigDoc").c_str());
        p.studio = stringValue(link, "ConfigStudio");
        p.partId = stringValue(link, "ConfigPartId");
    }
    if (!p.doc || p.partId.empty()) {
        return std::nullopt;
    }
    App::Part* studio = nullptr;
    if (!p.studio.empty()) {
        studio = freecad_cast<App::Part*>(p.doc->getObject(p.studio.c_str()));
    }
    if (p.studio.empty() || studio) {
        p.cfg = StudioConfig::of(p.doc, studio);
        if (p.cfg && !p.cfg->hasInputs()) {
            p.cfg = nullptr;
        }
    }
    if (p.cfg) {
        p.body = liveBody(p.doc, p.cfg, p.partId);
    }
    return p;
}

std::string instanceKey(const App::DocumentObject* link, const StudioConfig* cfg)
{
    const std::string key = stringValue(link, "ConfigKey");
    return key.empty() ? cfg->defaultKey() : key;
}

void request(const App::DocumentObject* reader);

void markEntries(App::Document* doc, const std::string& studio)
{
    for (auto e : configCacheEntries(doc)) {
        if (studio == e->ConfigStudio.getValue()) {
            e->setStale(true);
        }
    }
}

/// Marks what an edit of obj makes stale: its studio's entries when it is a configured studio's
/// object, else those of every configured studio that reads it (any open document)
void onEdit(const App::DocumentObject& obj)
{
    if (inPass || inSwitch || isConfigCacheObject(&obj)) {
        return;
    }
    App::Document* doc = obj.getDocument();
    if (!doc || isTemp(doc) || doc->testStatus(App::Document::Restoring)
        || doc->testStatus(App::Document::Recomputing) || doc->isPerformingTransaction()) {
        return;
    }
    if (auto cfg = configObjectConfig(&obj)) {
        if (cfg->hasInputs()) {
            markEntries(doc, studioName(cfg));
            studioEditDocs.insert(doc->getName());
            return;
        }
    }
    if (liveEntries.load() == 0) {
        return;
    }
    std::set<const StudioConfig*> done;
    for (auto dep : obj.getInListRecursive()) {
        auto cfg = configObjectConfig(dep);
        if (!cfg || !cfg->hasInputs() || !done.insert(cfg).second) {
            continue;
        }
        markEntries(cfg->getDocument(), studioName(cfg));
        studioEditDocs.insert(cfg->getDocument()->getName());
    }
}

/// A studio's Body going (a switch removing a piece, or the user): its instances keep what they
/// stand for as text (the link breaks next) and ask for a pass
void onDeleted(const App::DocumentObject& obj)
{
    if (!inPass && obj.isDerivedFrom<Body>() && !isTemp(obj.getDocument())) {
        for (auto user : obj.getInList()) {
            auto link = instanceLink(user);
            auto prop = link ? linkedProperty(link) : nullptr;
            if (prop && prop->getValue() == &obj) {
                if (auto part = resolveInstance(link)) {
                    noteInstance(link, *part);
                    request(link);
                }
            }
        }
    }
    onEdit(obj);
}

void onChanged(const App::DocumentObject& obj, const App::Property& prop)
{
    if (prop.testStatus(App::Property::Output) || prop.testStatus(App::Property::Transient)
        || (obj.getPropertyType(&prop) & (App::Prop_Output | App::Prop_Transient))) {
        return;
    }
    // An instance's own bookkeeping (its key, what it stands for) is no studio edit, even at the
    // root of a document's own studio, where every object is the studio's (C3f, review 10)
    if (instanceLink(&obj) && prop.getName() && std::string_view(prop.getName()).starts_with("Config")) {
        return;
    }
    onEdit(obj);
}

/// Mirrors the stale state into ConfigStale (for the next load, and for a recovery snapshot,
/// which fires no save signal)
void mirror(const App::Document& doc)
{
    if (isTemp(&doc) || doc.testStatus(App::Document::Restoring) || liveEntries.load() == 0) {
        return;
    }
    std::optional<App::Document::UnrecordedWrites> unrecorded;
    for (auto e : configCacheEntries(&doc)) {
        if (e->ConfigStale.getValue() != e->isStale()) {
            if (!unrecorded) {
                unrecorded.emplace(const_cast<App::Document&>(doc), derivedWriteCounted);
            }
            e->ConfigStale.setValue(e->isStale());
        }
    }
}

std::vector<App::Document*> openDocs()
{
    std::vector<App::Document*> docs;
    for (auto doc : App::GetApplication().getDocuments()) {
        if (!isTemp(doc)) {
            docs.push_back(doc);
        }
    }
    return docs;
}

/// After a studio edit's recompute: the instances on stale entries, and those on a studio's Body
/// in another configuration, become touched (they wait for the consumer's recompute)
void touchWaitingInstances()
{
    for (auto doc : openDocs()) {
        for (auto obj : doc->getObjectsOfType(App::Link::getClassTypeId())) {
            auto link = static_cast<App::Link*>(obj);
            auto prop = linkedProperty(link);
            auto target = prop ? prop->getValue() : nullptr;
            if (auto e = freecad_cast<ConfigShape*>(target)) {
                if (e->isStale() && !link->isTouched()) {
                    link->touch();
                }
            }
            else if (auto body = freecad_cast<Body*>(target)) {
                auto cfg = configSourceConfig(body);
                if (cfg && instanceKey(link, cfg) != cfg->activeKey() && !link->isTouched()) {
                    link->touch();
                }
            }
        }
    }
}

void request(const App::DocumentObject* reader)
{
    if (inPass || !reader->getDocument() || isTemp(reader->getDocument())) {
        return;
    }
    requests[reader->getDocument()->getName()].insert(reader->getNameInDocument());
}

bool busy(const App::Document* doc)
{
    // The step reopened at the end of a recompute (ops#654 10.15) is no user's transaction: the
    // pass runs then, unrecorded (C3i)
    return (doc->hasPendingTransaction() && !doc->isStepReopened()) || doc->isPerformingTransaction()
        || doc->testStatus(App::Document::Recomputing);
}

/// The values of a key ("<id>=<value>;...": lengths in metres, angles in radians)
std::map<std::string, std::string> keyValues(const std::string& key)
{
    std::map<std::string, std::string> values;
    size_t pos = 0;
    while (pos <= key.size()) {
        size_t end = key.find(';', pos);
        if (end == std::string::npos) {
            end = key.size();
        }
        const std::string item = key.substr(pos, end - pos);
        const size_t eq = item.find('=');
        if (eq != std::string::npos) {
            std::string v = item.substr(eq + 1);
            for (auto [from, to] : {std::pair {" meter", " m"}, std::pair {" radian", " rad"}}) {
                const std::string f(from);
                if (v.size() > f.size() && v.compare(v.size() - f.size(), f.size(), f) == 0) {
                    v = v.substr(0, v.size() - f.size()) + to;
                }
            }
            values[item.substr(0, eq)] = v;
        }
        pos = end + 1;
    }
    return values;
}

App::DocumentObject* cacheGroup(App::Document* doc)
{
    for (auto obj : doc->getObjectsOfType(App::DocumentObjectGroup::getClassTypeId())) {
        if (obj->getPropertyByName(GroupMark)) {
            return obj;
        }
    }
    auto group = doc->addObject("App::DocumentObjectGroup", "ConfigCache");
    group->addDynamicProperty("App::PropertyBool", GroupMark, "Configuration",
                              "Holds the shapes of a studio's other configurations (ops#671)",
                              App::Prop_Hidden);
    group->Label.setValue("Configuration cache");
    group->Visibility.setValue(false);
    return group;
}

ConfigShape* findEntry(App::Document* doc,
                       const std::string& studio,
                       const std::string& key,
                       const std::string& partId)
{
    for (auto e : configCacheEntries(doc)) {
        if (studio == e->ConfigStudio.getValue() && key == e->ConfigKey.getValue()
            && partId == e->ConfigPartId.getValue()) {
            return e;
        }
    }
    return nullptr;
}

ConfigShape* makeEntry(App::Document* doc,
                       const std::string& studio,
                       const std::string& key,
                       const std::string& partId)
{
    auto group = static_cast<App::DocumentObjectGroup*>(cacheGroup(doc));
    auto e = static_cast<ConfigShape*>(doc->addObject("PartDesign::ConfigShape", "ConfigEntry"));
    e->ConfigStudio.setValue(studio);
    e->ConfigKey.setValue(key);
    e->ConfigPartId.setValue(partId);
    e->Visibility.setValue(false);
    group->addObject(e);
    return e;
}

void fillError(ConfigShape* e, const std::string& why)
{
    e->Shape.setValue(Part::TopoShape());
    e->ConfigError.setValue(why);
    e->setStale(false);
    e->purgeTouched();
    ++stats.fills;
}

void fillShape(ConfigShape* e, const Part::TopoShape& shape)
{
    e->Shape.setValue(shape);
    e->ConfigError.setValue("");
    e->setStale(false);
    e->purgeTouched();
    ++stats.fills;
}

/// The copy's Body with partId in the studio named studio, or null
Body* copyBody(App::Document* copy, const StudioConfig* copyCfg, const std::string& partId)
{
    for (auto obj : copy->getObjectsOfType(Body::getClassTypeId())) {
        auto body = static_cast<Body*>(obj);
        if (configObjectConfig(body) == copyCfg && studioPartId(body) == partId) {
            return body;
        }
    }
    return nullptr;
}

std::string copyPath(const App::Document* doc)
{
    static int counter = 0;
    const std::string name = std::string(".") + doc->getName() + ".configs-"
        + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count() % 1000000) + "-"
        + std::to_string(++counter) + ".FCStd";
    Base::FileInfo file(doc->getFileName());
    // Beside the file, so the copy's links into other documents resolve as the original's do
    if (doc->getFileName()[0] && file.exists()) {
        Base::FileInfo dir(file.dirPath());
        if (dir.isWritable()) {
            return file.dirPath() + "/" + name;
        }
    }
    return App::Application::getTempPath() + name;
}

/// Fills entries (key -> entries) of studio doc's studio from one hidden copy
void fillFromCopy(App::Document* doc,
                  const std::string& studio,
                  const std::map<std::string, std::vector<ConfigShape*>>& keys)
{
    App::Part* liveStudio = studio.empty() ? nullptr : freecad_cast<App::Part*>(doc->getObject(studio.c_str()));
    const std::string label = studio.empty() ? std::string("of the document")
                                             : "'" + std::string(liveStudio ? liveStudio->Label.getValue() : studio.c_str()) + "'";
    auto failAll = [&keys](const std::string& why) {
        for (const auto& [key, entries] : keys) {
            for (auto e : entries) {
                fillError(e, why);
            }
        }
    };
    // A partly loaded document copies only what is loaded: a silently wrong copy (review 3)
    if (doc->testStatus(App::Document::PartialDoc)) {
        failAll("The studio " + label + " is only partly loaded: open its document to build its "
                "other configurations");
        return;
    }
    const auto start = std::chrono::steady_clock::now();
    const std::string path = copyPath(doc);
    App::Document* copy = nullptr;
    std::string failure;
    try {
        if (doc->saveCopy(path.c_str())) {
            App::DocumentInitFlags flags;
            flags.createView = false;
            flags.temporary = true;
            copy = App::GetApplication().openDocument(path.c_str(), flags);
        }
    }
    catch (const Base::Exception& e) {
        failure = std::string(": ") + e.what();
    }
    stats.copySeconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    if (!copy) {
        Base::FileInfo(path).deleteFile();
        failAll("The studio " + label + " can't be copied to build its other configurations" + failure);
        return;
    }
    ++stats.copies;
    App::Part* copyStudio = studio.empty() ? nullptr : freecad_cast<App::Part*>(copy->getObject(studio.c_str()));
    StudioConfig* copyCfg = StudioConfig::of(copy, copyStudio);
    Base::SequencerLauncher seq("Building configurations", keys.size());
    for (const auto& [key, entries] : keys) {
        std::string why;
        bool ok = copyCfg && (studio.empty() || copyStudio);
        if (!ok) {
            why = "the studio is gone";
        }
        else {
            try {
                ok = configSetActiveIn(copy, copyStudio, keyValues(key), &why);
            }
            catch (const Base::Exception& e) {
                ok = false;
                why = e.what();
            }
            ++stats.keys;
        }
        for (auto e : entries) {
            if (!ok) {
                fillError(e, "The configuration " + key + " of the studio " + label + " fails: " + why);
                continue;
            }
            auto body = copyBody(copy, copyCfg, e->ConfigPartId.getValue());
            if (!body) {
                fillError(e, "The configuration " + key + " of the studio " + label
                                 + " has no part " + e->ConfigPartId.getValue());
                continue;
            }
            auto tip = body->Tip.getValue();
            if (body->isError() || (tip && tip->isError())) {
                fillError(e, "The configuration " + key + " of the studio " + label + " fails: '"
                                 + body->Label.getValue() + "' has an error");
                continue;
            }
            if (body->Shape.getShape().isNull()) {
                fillError(e, "The configuration " + key + " of the studio " + label + " gives '"
                                 + body->Label.getValue() + "' no solid");
                continue;
            }
            fillShape(e, body->Shape.getShape());
        }
        seq.next();
    }
    App::GetApplication().closeDocument(copy->getName());
    Base::FileInfo(path).deleteFile();
}

struct PassGuard
{
    PassGuard()
    {
        ++inPass;
    }
    ~PassGuard()
    {
        --inPass;
    }
    PassGuard(const PassGuard&) = delete;
    PassGuard& operator=(const PassGuard&) = delete;
};

struct Served
{
    App::Link* link;
    App::DocumentObject* target;
};

/// The instances of docs (empty: the requested ones) that need a pass
std::vector<App::Link*> instancesToServe(const std::vector<App::Document*>& docs)
{
    std::vector<App::Link*> links;
    if (docs.empty()) {
        for (const auto& [docName, names] : requests) {
            auto doc = App::GetApplication().getDocument(docName.c_str());
            for (const auto& name : doc ? names : std::set<std::string> {}) {
                if (auto link = instanceLink(doc->getObject(name.c_str()))) {
                    links.push_back(link);
                }
            }
        }
        return links;
    }
    for (auto doc : docs) {
        for (auto obj : doc->getObjectsOfType(App::Link::getClassTypeId())) {
            auto link = static_cast<App::Link*>(obj);
            if (resolveInstance(link)) {
                links.push_back(link);
            }
        }
    }
    return links;
}

/// The pass: false (why) when put off by an open transaction
bool runPass(const std::vector<App::Document*>& docs, std::string* why)
{
    if (inPass) {
        return true;
    }
    std::vector<App::Link*> links = instancesToServe(docs);
    // Which entries each instance needs, and which documents take part
    struct Need
    {
        App::Link* link;
        InstancePart part;
        std::string key;
    };
    std::vector<Need> needs;
    std::set<App::Document*> involved;
    for (auto link : links) {
        auto part = resolveInstance(link);
        if (!part || (!part->cfg && !part->body)) {
            continue;  // its studio is gone: it stays loud
        }
        needs.push_back({link, *part, part->cfg ? instanceKey(link, part->cfg) : std::string()});
        involved.insert(link->getDocument());
        involved.insert(part->doc);
    }
    for (auto doc : involved) {
        if (busy(doc)) {
            ++stats.deferred;
            if (why) {
                *why = std::string("The document ") + doc->getName()
                    + " has a transaction open: the configurations are built after it";
            }
            return false;
        }
    }
    if (docs.empty()) {
        requests.clear();
    }
    if (needs.empty()) {
        return true;
    }
    PassGuard guard;
    // Every write of the pass, its recomputes included, is derived data (C3i)
    std::vector<std::unique_ptr<App::Document::UnrecordedWrites>> unrecorded;
    for (auto doc : involved) {
        unrecorded.push_back(std::make_unique<App::Document::UnrecordedWrites>(*doc, derivedWriteCounted));
    }
    ++stats.passes;
    std::vector<Served> served;
    std::map<std::pair<App::Document*, std::string>, std::map<std::string, std::vector<ConfigShape*>>> fills;
    for (const auto& n : needs) {
        const InstancePart& p = n.part;
        noteInstance(n.link, p);
        // The studio's active configuration (or no longer configured): the live Body
        if (p.body && (!p.cfg || n.key == p.cfg->activeKey())) {
            served.push_back({n.link, p.body});
            continue;
        }
        ConfigShape* e = findEntry(p.doc, p.studio, n.key, p.partId);
        if (!e) {
            e = makeEntry(p.doc, p.studio, n.key, p.partId);
        }
        if (n.key == p.cfg->activeKey()) {
            // The shown configuration has no such part (a piece it doesn't make)
            fillError(e, "The configuration " + n.key + " of the studio " + studioLabel(p.cfg)
                             + " has no part " + p.partId);
        }
        else if (e->isStale()) {
            auto& list = fills[{p.doc, p.studio}][n.key];
            if (std::ranges::find(list, e) == list.end()) {
                list.push_back(e);
            }
        }
        served.push_back({n.link, e});
    }
    for (const auto& [where, keys] : fills) {
        fillFromCopy(where.first, where.second, keys);
    }
    for (const auto& s : served) {
        auto prop = linkedProperty(s.link);
        if (prop && prop->getValue() != s.target) {
            inRetarget = true;
            const Base::ScopeGuard retargeted([] { inRetarget = false; });
            prop->setValue(s.target);
        }
        // An errored object can end a recompute untouched (Document.cpp's stopped and
        // continuation branches): every served instance runs again (review 1)
        s.link->touch();
    }
    for (auto doc : involved) {
        studioEditDocs.erase(doc->getName());
    }
    for (auto doc : involved) {
        doc->recompute();
    }
    return true;
}

void schedulePass()
{
    if (!scheduler) {
        runPass({}, nullptr);
        return;
    }
    if (passScheduled) {
        return;
    }
    passScheduled = true;
    scheduler([] {
        passScheduled = false;
        runPass({}, nullptr);
    });
}

void onStable(const App::Document& doc)
{
    const Event ev = lastEvent[&doc];
    lastEvent.erase(&doc);
    std::set<std::string> ran;
    if (auto it = recomputedDocs.find(&doc); it != recomputedDocs.end()) {
        ran.swap(it->second);
        recomputedDocs.erase(it);
    }
    if (isTemp(&doc) || inPass) {
        return;
    }
    mirror(doc);
    if ((ev != Event::Recompute && ev != Event::Commit) || doc.isPerformingTransaction()) {
        return;
    }
    if (ev == Event::Recompute) {
        // The studio edits this recompute ended, in its own document or in one it reached (C3h)
        ran.insert(doc.getName());
        bool ended = false;
        for (const auto& name : ran) {
            ended = studioEditDocs.erase(name) > 0 || ended;
        }
        if (ended) {
            touchWaitingInstances();  // a studio edit never runs the pass (ruling 1)
            return;
        }
    }
    if (!requests.empty()) {
        schedulePass();
    }
}

void connectDocument(const App::Document& cdoc)
{
    if (isTemp(&cdoc)) {
        return;
    }
    auto& doc = const_cast<App::Document&>(cdoc);
    doc.signalRecomputed.connect([](const App::Document& d, const std::vector<App::DocumentObject*>& objs) {
        lastEvent[&d] = Event::Recompute;
        auto& ran = recomputedDocs[&d];
        for (auto obj : objs) {
            if (obj->isAttachedToDocument() && obj->getDocument() != &d) {
                ran.insert(obj->getDocument()->getName());
            }
        }
    });
    doc.signalCommitTransaction.connect([](const App::Document& d) { lastEvent[&d] = Event::Commit; });
    doc.signalAbortTransaction.connect([](const App::Document& d) { lastEvent[&d] = Event::Other; });
    doc.signalBecameStable.connect(onStable);
}

/// An undo or redo marks every entry of its document stale: nothing then depends on the order of
/// the change signals during the rollback (review 6). Undo has already regenerated the model
/// (`Document::undo`, regenerateAfterTransaction), so the instances on those entries are touched
/// now and the next recompute refills them; an undo is no studio edit, whose recompute only
/// touches (that took two recomputes to show the undone shape)
void onUndoRedo(const App::Document& cdoc)
{
    lastEvent[&cdoc] = Event::Other;
    if (isTemp(&cdoc) || liveEntries.load() == 0) {
        return;
    }
    auto& doc = const_cast<App::Document&>(cdoc);
    auto entries = configCacheEntries(&doc);
    for (auto e : entries) {
        e->setStale(true);
    }
    if (!entries.empty()) {
        touchWaitingInstances();
    }
}

}  // namespace

// ---- the entry --------------------------------------------------------------------------------

ConfigShape::ConfigShape()
{
    const auto attr = static_cast<App::PropertyType>(App::Prop_Hidden | App::Prop_Output | App::Prop_NoRecompute);
    ADD_PROPERTY_TYPE(ConfigStudio, (""), "Configuration", attr, "The studio's internal name");
    ADD_PROPERTY_TYPE(ConfigKey, (""), "Configuration", attr, "The configuration's key");
    ADD_PROPERTY_TYPE(ConfigPartId, (""), "Configuration", attr, "The part's id");
    ADD_PROPERTY_TYPE(ConfigError, (""), "Configuration", attr, "Why the configuration has no such part");
    ADD_PROPERTY_TYPE(ConfigStale, (true), "Configuration", attr, "Out of date when saved");
    ++liveEntries;
}

ConfigShape::~ConfigShape()
{
    --liveEntries;
}

App::DocumentObjectExecReturn* ConfigShape::execute()
{
    if (ConfigError.getValue()[0]) {
        return new App::DocumentObjectExecReturn(ConfigError.getValue());
    }
    return App::DocumentObject::StdReturn;
}

short ConfigShape::mustExecute() const
{
    return 0;
}

void ConfigShape::onDocumentRestored()
{
    Part::Feature::onDocumentRestored();
    stale = ConfigStale.getValue();
}

App::DocumentObject* ConfigShape::getSubObject(const char* subname,
                                               PyObject** pyObj,
                                               Base::Matrix4D* mat,
                                               bool transform,
                                               int depth) const
{
    if (subname && *subname) {
        if (const char* element = Data::findElementName(subname); element && element != subname) {
            subname = element;
        }
    }
    return Part::Feature::getSubObject(subname, pyObj, mat, transform, depth);
}

bool isConfigCacheObject(const App::DocumentObject* obj)
{
    if (!obj) {
        return false;
    }
    if (obj->isDerivedFrom<ConfigShape>()) {
        return true;
    }
    return obj->isDerivedFrom<App::DocumentObjectGroup>() && obj->getPropertyByName(GroupMark);
}

std::vector<ConfigShape*> configCacheEntries(const App::Document* doc)
{
    std::vector<ConfigShape*> out;
    if (!doc || liveEntries.load() == 0) {
        return out;
    }
    for (auto obj : doc->getObjectsOfType(ConfigShape::getClassTypeId())) {
        out.push_back(static_cast<ConfigShape*>(obj));
    }
    return out;
}

// ---- the reader check -------------------------------------------------------------------------

App::DocumentObject* configInstancePart(const App::DocumentObject* instance)
{
    auto part = resolveInstance(instance);
    return part ? part->body : nullptr;
}

std::string configCacheReaderError(const App::DocumentObject* reader,
                                   const App::DocumentObject* source,
                                   const std::string& c1Error)
{
    auto link = instanceLink(reader);
    if (!link) {
        return c1Error;  // binders and Derived stay loud until C4
    }
    auto entry = freecad_cast<const ConfigShape*>(source);
    if (!entry) {
        if (!freecad_cast<const Body*>(source)) {
            return c1Error;  // a whole studio shown: no entry stands for it
        }
        // A studio's Body in another configuration: the pass retargets it to an entry
        if (!studioEditDocs.contains(source->getDocument()->getName())) {
            request(reader);
        }
        return c1Error + " (a recompute builds it)";
    }
    auto cfg = configSourceConfig(entry);
    const std::string key = cfg ? instanceKey(reader, cfg) : std::string();
    const bool underEdit = studioEditDocs.contains(entry->getDocument()->getName());
    if (!cfg || key == cfg->activeKey() || key != entry->ConfigKey.getValue()) {
        // Its studio shows this configuration now, or the instance was given another one
        if (!underEdit) {
            request(reader);
        }
        if (cfg && key != entry->ConfigKey.getValue()) {
            return "The configuration of this instance changed: a recompute builds it";
        }
    }
    if (entry->isStale()) {
        if (!underEdit) {
            request(reader);
            return std::string("The configuration ") + entry->ConfigKey.getValue() + " of the studio "
                + studioLabel(cfg) + " is out of date: a recompute builds it";
        }
        return {};  // touched after the edit's recompute (ruling 3)
    }
    if (entry->ConfigError.getValue()[0]) {
        return entry->ConfigError.getValue();
    }
    return {};
}

// ---- the API ----------------------------------------------------------------------------------

bool configRefresh(App::Document* doc, std::string* why)
{
    std::vector<App::Document*> docs;
    if (doc) {
        docs.push_back(doc);
    }
    else {
        docs = openDocs();
    }
    return runPass(docs, why);
}

bool configSetInstanceKey(App::DocumentObject* instance,
                          const std::map<std::string, std::string>& values,
                          std::string* why)
{
    auto part = resolveInstance(instance);
    if (!part || !part->cfg) {
        if (why) {
            *why = "This isn't an instance of a configured studio's part";
        }
        return false;
    }
    const std::string key = configKeyOf(part->cfg, values, why);
    if (key.empty()) {
        return false;
    }
    noteInstance(instance, *part);
    setString(instance, "ConfigKey", key);
    instance->touch();
    return true;
}

ConfigCacheStats configCacheStats()
{
    return stats;
}

void setConfigPassScheduler(std::function<void(std::function<void()>)> s)
{
    scheduler = std::move(s);
}

ConfigSwitchGuard::ConfigSwitchGuard()
{
    ++inSwitch;
}

ConfigSwitchGuard::~ConfigSwitchGuard()
{
    --inSwitch;
}

void registerConfigCacheHooks()
{
    auto& app = App::GetApplication();
    app.signalChangedObject.connect(onChanged);
    app.signalNewObject.connect([](const App::DocumentObject& obj) { onEdit(obj); });
    app.signalDeletedObject.connect(onDeleted);
    app.signalUndoDocument.connect(onUndoRedo);
    app.signalRedoDocument.connect(onUndoRedo);
    app.signalStartSaveDocument.connect([](const App::Document& doc, const std::string&) { mirror(doc); });
    app.signalNewDocument.connect([](const App::Document& doc, bool) { connectDocument(doc); });
    app.signalDeleteDocument.connect([](const App::Document& doc) {
        lastEvent.erase(&doc);
        recomputedDocs.erase(&doc);
        studioEditDocs.erase(doc.getName());
        requests.erase(doc.getName());
    });
    for (auto doc : app.getDocuments()) {
        connectDocument(*doc);
    }
}

}  // namespace PartDesign
