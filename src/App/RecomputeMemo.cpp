// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   FreeCAD-CH (ops#796): the recompute result memo.                       *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU     *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

#include <algorithm>
#include <deque>
#include <iomanip>
#include <limits>
#include <locale>
#include <map>
#include <memory>
#include <set>
#include <unordered_map>

#include <QByteArray>
#include <QCryptographicHash>

#include <Base/Console.h>
#include <Base/Parameter.h>
#include <Base/Writer.h>

#include "Application.h"
#include "Document.h"
#include "DocumentObject.h"
#include "GroupExtension.h"
#include "Link.h"
#include "PropertyGeo.h"
#include "PropertyLinks.h"
#include "PropertyPythonObject.h"
#include "RecomputeMemo.h"

FC_LOG_LEVEL_INIT("RecomputeMemo", true, true)

namespace App::RecomputeMemo
{

namespace
{

// NOLINTBEGIN(cppcoreguidelines-avoid-non-const-global-variables)

struct HandleType
{
    Base::Type type;
    HandleHooks hooks;
};

std::vector<HandleType>& handleTypes()
{
    static std::vector<HandleType> types;
    return types;
}

std::vector<std::pair<Base::Type, Predicate>>& allowedTypes()
{
    static std::vector<std::pair<Base::Type, Predicate>> types;
    return types;
}

const HandleHooks* hooksOf(const Property* property)
{
    for (const auto& entry : handleTypes()) {
        if (property->isDerivedFrom(entry.type)) {
            return &entry.hooks;
        }
    }
    return nullptr;
}

std::string digestOf(const std::string& text)
{
    return QCryptographicHash::hash(
               QByteArray::fromRawData(text.data(), static_cast<qsizetype>(text.size())),
               QCryptographicHash::Sha1
    )
        .toStdString();
}

// The saved form of a property, inline and at full precision
bool savedForm(const Property& property, std::string& text)
{
    try {
        Base::StringWriter writer;
        writer.setForceXML(true);
        writer.Stream().imbue(std::locale::classic());
        writer.Stream() << std::setprecision(std::numeric_limits<double>::max_digits10);
        property.Save(writer);
        text = writer.getString();
        return true;
    }
    catch (...) {
        return false;
    }
}

// A change of any property of a container bumps its serial: the tokens made of it are void
std::unordered_map<const PropertyContainer*, std::uint64_t> serials;
// Any user or system parameter changed: every kept run is void (settings are inputs)
std::uint64_t epoch = 1;
std::uint64_t nextStamp = 1;
Stats counters;
std::deque<std::string> noteLines;

void note(const std::string& line)
{
    noteLines.push_back(line);
    while (noteLines.size() > 400) {
        noteLines.pop_front();
    }
    FC_LOG(line);
}

// A value a handle property held, kept alive so its identity can't be another value's
struct Kept
{
    std::unique_ptr<Property> copy;
    std::string identity;
    std::uint64_t stamp {0};
};
constexpr std::size_t keptValues = 8;
std::unordered_map<const Property*, std::deque<Kept>> history;

// The stamp of the value a handle property holds now; 0 when it can't be told
std::uint64_t stampOf(const Property* property, const HandleHooks& hooks)
{
    std::string identity;
    if (!hooks.identity || !hooks.identity(*property, identity)) {
        return 0;
    }
    auto& values = history[property];
    for (auto it = values.begin(); it != values.end(); ++it) {
        if (it->identity == identity) {
            const std::uint64_t stamp = it->stamp;
            if (it != values.begin()) {
                Kept kept = std::move(*it);
                values.erase(it);
                values.push_front(std::move(kept));
            }
            return stamp;
        }
    }
    Kept kept;
    kept.copy.reset(property->Copy());
    if (!kept.copy) {
        return 0;
    }
    // The copy shares the value: it must read as the same one
    std::string copied;
    if (!hooks.identity(*kept.copy, copied) || copied != identity) {
        return 0;
    }
    kept.identity = std::move(identity);
    kept.stamp = nextStamp++;
    const std::uint64_t stamp = kept.stamp;
    values.push_front(std::move(kept));
    while (values.size() > keptValues) {
        values.pop_back();
    }
    return stamp;
}

// The value a handle property holds now is, in content, the one that has this stamp
void aliasStamp(const Property* property, const HandleHooks& hooks, std::uint64_t stamp)
{
    std::string identity;
    if (!hooks.identity || !hooks.identity(*property, identity)) {
        return;
    }
    for (auto& kept : history[property]) {
        if (kept.identity == identity) {
            kept.stamp = stamp;
            return;
        }
    }
}

struct Output
{
    std::string name;
    std::shared_ptr<Property> value;
    bool handle {false};
    std::uint64_t stamp {0};  // a handle's
    std::string plain;        // the digest of the saved form (not a handle)
    std::string quick;        // a handle's quick digest
    std::string content;      // a handle's content digest, made when needed
};

struct Entry
{
    std::string key;
    // Own handle properties the run didn't write: inputs, by stamp
    std::vector<std::pair<std::string, std::uint64_t>> inputs;
    std::vector<Output> outputs;
    std::uint64_t used {0};
};
constexpr std::size_t keptRuns = 4;

struct ObjectMemo
{
    long id {0};
    const Document* document {nullptr};
    std::vector<Entry> entries;
    // It wrote another object in a run: it runs every time (its result still gets an identity)
    bool syncing {false};
    // The token of its properties, valid while its serial is the one it was made at
    bool tokenMade {false};
    bool tokenOk {false};
    std::uint64_t tokenSerial {0};
    std::string plain;                                                  // all but handles
    std::vector<std::pair<std::string, const Property*>> handles;       // by name
    std::set<const Property*> historyOf;
};
std::unordered_map<const DocumentObject*, ObjectMemo> memos;
std::uint64_t useClock = 0;

ObjectMemo& memoOf(const DocumentObject* object)
{
    auto& memo = memos[object];
    if (memo.id != object->getID() || memo.document != object->getDocument()) {
        // Another object at this address
        for (const Property* property : memo.historyOf) {
            history.erase(property);
        }
        memo = ObjectMemo();
        memo.id = object->getID();
        memo.document = object->getDocument();
    }
    return memo;
}

std::uint64_t serialOf(const PropertyContainer* container)
{
    auto it = serials.find(container);
    return it == serials.end() ? 0 : it->second;
}

// The properties of an object as a key reads them: `plain` (every property but Visibility and
// the handles, by saved form) and the handles by name. False when it can't be told (a Python
// proxy, a geometry property without hooks)
bool makeToken(const DocumentObject* object, ObjectMemo& memo, bool fresh = false)
{
    const std::uint64_t serial = serialOf(object);
    if (!fresh && memo.tokenMade && memo.tokenSerial == serial) {
        return memo.tokenOk;
    }
    memo.tokenMade = true;
    memo.tokenSerial = serial;
    memo.tokenOk = false;
    memo.plain.clear();
    memo.handles.clear();

    std::map<std::string, Property*> properties;
    object->getPropertyMap(properties);
    std::string text(object->getTypeId().getName());
    text += '\n';
    for (const auto& [name, property] : properties) {
        if (!property || property == &object->Visibility) {
            continue;
        }
        if (property->isDerivedFrom<PropertyPythonObject>()) {
            return false;
        }
        if (hooksOf(property)) {
            memo.handles.emplace_back(name, property);
            continue;
        }
        if (property->isDerivedFrom<PropertyComplexGeoData>()) {
            return false;
        }
        std::string saved;
        if (!savedForm(*property, saved)) {
            return false;
        }
        text += name;
        text += '=';
        text += digestOf(saved);
    }
    memo.plain = digestOf(text);
    memo.tokenOk = true;
    return true;
}

std::string nameOf(const DocumentObject* object)
{
    return object->isAttachedToDocument() ? object->getFullName() : std::string("?");
}

std::vector<DocumentObject*> sortedUnique(std::vector<DocumentObject*> objects)
{
    objects.erase(std::remove(objects.begin(), objects.end(), nullptr), objects.end());
    std::sort(objects.begin(), objects.end(), [](const auto* a, const auto* b) {
        const std::string an = nameOf(a);
        const std::string bn = nameOf(b);
        return an != bn ? an < bn : a < b;
    });
    objects.erase(std::unique(objects.begin(), objects.end()), objects.end());
    return objects;
}

// The whole state of an object: its plain properties and its handles' stamps
bool fullToken(const DocumentObject* object, std::string& text)
{
    ObjectMemo& memo = memoOf(object);
    if (!makeToken(object, memo)) {
        return false;
    }
    text = memo.plain;
    for (const auto& [name, property] : memo.handles) {
        const HandleHooks* hooks = hooksOf(property);
        const std::uint64_t stamp = hooks ? stampOf(property, *hooks) : 0;
        if (stamp == 0) {
            return false;
        }
        memo.historyOf.insert(property);
        text += name;
        text += '#';
        text += std::to_string(stamp);
    }
    return true;
}

// The state of an object and of everything it can read through its out-list, recursively
struct Closure
{
    std::unordered_map<const DocumentObject*, std::string> made;
    std::set<const DocumentObject*> making;

    bool token(const DocumentObject* object, std::string& out)
    {
        auto it = made.find(object);
        if (it != made.end()) {
            out = it->second;
            return true;
        }
        if (!making.insert(object).second) {
            return false;  // a cycle
        }
        std::string text;
        if (!fullToken(object, text)) {
            return false;
        }
        for (const DocumentObject* input : sortedUnique(object->getOutList())) {
            std::string below;
            if (!token(input, below)) {
                return false;
            }
            text += nameOf(input);
            text += ':';
            text += below;
        }
        making.erase(object);
        out = digestOf(text);
        made.emplace(object, out);
        return true;
    }
};

bool isAllowed(const DocumentObject* object)
{
    bool allowed = false;
    for (const auto& [type, predicate] : allowedTypes()) {
        if (object->isDerivedFrom(type) && (!predicate || predicate(object))) {
            allowed = true;
            break;
        }
    }
    if (!allowed) {
        return false;
    }
    // Readers reach a container's or a link's members through it
    return !object->hasExtension(GroupExtension::getExtensionClassTypeId())
        && !object->hasExtension(LinkBaseExtension::getExtensionClassTypeId());
}

// The key of an object about to run. False when one can't be made
bool makeKey(const DocumentObject* object, std::string& key)
{
    ObjectMemo& memo = memoOf(object);
    if (!makeToken(object, memo)) {
        return false;
    }
    const Document* document = object->getDocument();
    if (!document) {
        return false;
    }
    // An expression may read the Visibility of anything, which no token has
    if (auto engine = object->getPropertyByName("ExpressionEngine")) {
        std::string saved;
        if (!savedForm(*engine, saved) || saved.find("Visibility") != std::string::npos) {
            return false;
        }
    }
    std::string text = "epoch ";
    text += std::to_string(epoch);
    text += " document ";
    text += std::to_string(serialOf(document));
    text += '\n';
    text += memo.plain;
    Closure closure;
    closure.making.insert(object);
    for (const DocumentObject* input : sortedUnique(object->getOutList())) {
        std::string below;
        if (input == object || !closure.token(input, below)) {
            return false;
        }
        text += "\nin ";
        text += nameOf(input);
        text += ':';
        text += below;
    }
    for (const DocumentObject* reader : sortedUnique(object->getInList())) {
        if (reader == object) {
            return false;
        }
        ObjectMemo& readerMemo = memoOf(reader);
        text += "\nby ";
        text += nameOf(reader);
        text += ':';
        // One that can't be told (a Python reader) is named only: nothing of it is read here
        text += makeToken(reader, readerMemo) ? readerMemo.plain : std::string("-");
    }
    key = digestOf(text);
    return true;
}

// A run being watched: what it writes
struct Recorder
{
    DocumentObject* object {nullptr};
    Recorder* outer {nullptr};
    int ownDepth {0};
    // A write to another object outside any of its own property changes, a touch of another
    // object, or another object run within
    bool wroteOthers {false};
    // Not a function of the key (noteImpureRun())
    bool impure {false};
    std::string why;
    struct Written
    {
        const Property* property;
        int count;
        bool othersInside;
    };
    std::vector<Written> written;  // in the order of the last write
    std::vector<bool> open;        // per open own change: another object written inside
};
Recorder* active = nullptr;

struct RecorderScope
{
    explicit RecorderScope(Recorder& recorder)
        : recorder(recorder)
    {
        recorder.outer = active;
        if (active) {
            // An object run within another's run: the outer one did more than write itself
            active->wroteOthers = true;
            if (active->why.empty()) {
                active->why = "ran " + nameOf(recorder.object);
            }
        }
        active = &recorder;
    }
    ~RecorderScope()
    {
        active = recorder.outer;
    }
    RecorderScope(const RecorderScope&) = delete;
    RecorderScope& operator=(const RecorderScope&) = delete;
    Recorder& recorder;
};

int mode()
{
    static ParameterGrp::handle group =
        GetApplication().GetParameterGroupByPath("User parameter:BaseApp/Preferences/Document");
    static bool connected = false;
    if (!connected) {
        connected = true;
        auto flush = [](auto&&...) {
            ++epoch;
            ++counters.flushes;
            for (auto& [object, memo] : memos) {
                memo.entries.clear();
            }
        };
        // Never disconnected: the memo lives as long as the application
        static auto user = GetApplication().GetUserParameter().signalParamChanged.connect(flush);
        static auto system =
            GetApplication().GetSystemParameter().signalParamChanged.connect(flush);
    }
    return static_cast<int>(group->GetInt("RecomputeMemo", 0));
}

bool makeOutputs(const Recorder& recorder, std::vector<Output>& outputs, std::string& why)
{
    std::map<std::string, Property*> properties;
    recorder.object->getPropertyMap(properties);
    for (const auto& written : recorder.written) {
        Output output;
        Property* property = nullptr;
        for (const auto& [name, candidate] : properties) {
            if (candidate == written.property) {
                output.name = name;
                property = candidate;
                break;
            }
        }
        if (!property) {
            why = "a written property is gone";
            return false;
        }
        if (property->isDerivedFrom<PropertyLinkBase>()) {
            // A copy of a link holds objects, which may be gone by the time of a paste
            why = "wrote its link " + output.name;
            return false;
        }
        if (written.count > 1 && written.othersInside) {
            why = "wrote " + output.name + " more than once, with other objects following";
            return false;
        }
        if (const HandleHooks* hooks = hooksOf(property)) {
            if (written.count > 1) {
                why = "wrote " + output.name + " more than once";
                return false;
            }
            output.handle = true;
            output.stamp = stampOf(property, *hooks);
            if (output.stamp == 0 || !hooks->quick || !hooks->quick(*property, output.quick)) {
                why = "no identity for " + output.name;
                return false;
            }
        }
        else {
            std::string saved;
            if (!savedForm(*property, saved)) {
                why = "no saved form of " + output.name;
                return false;
            }
            output.plain = digestOf(saved);
        }
        output.value.reset(property->Copy());
        if (!output.value) {
            why = "no copy of " + output.name;
            return false;
        }
        outputs.push_back(std::move(output));
    }
    return true;
}

bool contentOf(Output& output)
{
    if (!output.content.empty()) {
        return true;
    }
    const HandleHooks* hooks = hooksOf(output.value.get());
    return hooks && hooks->content && hooks->content(*output.value, output.content)
        && !output.content.empty();
}

// Whether two runs wrote the same, in content. `difference` names the first property that isn't
bool sameOutputs(std::vector<Output>& a, std::vector<Output>& b, std::string& difference)
{
    if (a.size() != b.size()) {
        difference = "the properties written";
        return false;
    }
    std::map<std::string, Output*> byName;
    for (auto& output : b) {
        byName[output.name] = &output;
    }
    // The cheap parts first
    for (auto& output : a) {
        auto it = byName.find(output.name);
        if (it == byName.end() || it->second->handle != output.handle) {
            difference = output.name;
            return false;
        }
        if (output.handle ? output.quick != it->second->quick : output.plain != it->second->plain) {
            difference = output.name;
            return false;
        }
    }
    for (auto& output : a) {
        if (!output.handle) {
            continue;
        }
        Output& other = *byName[output.name];
        if (output.stamp == other.stamp) {
            continue;
        }
        if (!contentOf(output) || !contentOf(other) || output.content != other.content) {
            difference = output.name + " (content)";
            return false;
        }
    }
    return true;
}

std::vector<std::pair<std::string, std::uint64_t>> inputsOf(
    ObjectMemo& memo,
    const std::vector<Output>& outputs,
    bool& ok
)
{
    std::vector<std::pair<std::string, std::uint64_t>> inputs;
    ok = true;
    for (const auto& [name, property] : memo.handles) {
        const bool written = std::any_of(outputs.begin(), outputs.end(), [&](const Output& o) {
            return o.name == name;
        });
        if (written) {
            continue;
        }
        const HandleHooks* hooks = hooksOf(property);
        const std::uint64_t stamp = hooks ? stampOf(property, *hooks) : 0;
        if (stamp == 0) {
            ok = false;
            return inputs;
        }
        memo.historyOf.insert(property);
        inputs.emplace_back(name, stamp);
    }
    return inputs;
}

Entry* findEntry(ObjectMemo& memo, const std::string& key)
{
    for (auto& entry : memo.entries) {
        if (entry.key != key) {
            continue;
        }
        bool same = true;
        for (const auto& [name, stamp] : entry.inputs) {
            auto it = std::find_if(memo.handles.begin(), memo.handles.end(), [&](const auto& h) {
                return h.first == name;
            });
            const HandleHooks* hooks = it == memo.handles.end() ? nullptr : hooksOf(it->second);
            if (!hooks || stampOf(it->second, *hooks) != stamp) {
                same = false;
                break;
            }
        }
        // Every written property must still be there
        for (const auto& output : entry.outputs) {
            if (!same) {
                break;
            }
            same = memo.document && output.value;
        }
        if (same) {
            return &entry;
        }
    }
    return nullptr;
}

void paste(DocumentObject* object, const Entry& entry)
{
    for (const auto& output : entry.outputs) {
        if (Property* property = object->getPropertyByName(output.name.c_str())) {
            property->Paste(*output.value);
        }
    }
}

// NOLINTEND(cppcoreguidelines-avoid-non-const-global-variables)

}  // namespace

void allow(const Base::Type& type, Predicate predicate)
{
    allowedTypes().emplace_back(type, predicate);
}

void setHandleHooks(const Base::Type& propertyType, const HandleHooks& hooks)
{
    handleTypes().push_back({propertyType, hooks});
}

void noteImpureRun(const char* why)
{
    for (Recorder* recorder = active; recorder; recorder = recorder->outer) {
        recorder->impure = true;
        if (recorder->why.empty()) {
            recorder->why = why ? why : "impure";
        }
    }
}

Stats stats(bool reset)
{
    const Stats result = counters;
    if (reset) {
        counters = Stats();
    }
    return result;
}

std::vector<std::string> notes(bool reset)
{
    std::vector<std::string> result(noteLines.begin(), noteLines.end());
    if (reset) {
        noteLines.clear();
    }
    return result;
}

ChangeScope::ChangeScope(const PropertyContainer* container, const Property* property)
    : container(container)
    , property(property)
{
    if (!container) {
        return;
    }
    ++serials[container];
    Recorder* recorder = active;
    if (!recorder) {
        return;
    }
    if (container == recorder->object) {
        own = true;
        ++recorder->ownDepth;
        recorder->open.push_back(false);
    }
    else if (recorder->ownDepth == 0) {
        // Written by the run itself, not by one of its own changes: a paste wouldn't write it
        if (!recorder->wroteOthers) {
            recorder->wroteOthers = true;
            std::string name = "?";
            if (auto other = freecad_cast<const DocumentObject*>(container)) {
                name = nameOf(other);
                if (const char* propertyName = property->getName()) {
                    name += '.';
                    name += propertyName;
                }
            }
            recorder->why = "wrote " + name;
        }
    }
    else {
        for (std::size_t i = 0; i < recorder->open.size(); ++i) {
            recorder->open[i] = true;
        }
    }
}

ChangeScope::~ChangeScope()
{
    if (!own) {
        return;
    }
    Recorder* recorder = active;
    if (!recorder || recorder->object != container || recorder->open.empty()) {
        return;
    }
    const bool othersInside = recorder->open.back();
    recorder->open.pop_back();
    --recorder->ownDepth;
    if (recorder->ownDepth > 0) {
        // Written within another of its own changes (a Placement moves the Shape): the paste of
        // that one writes it again
        return;
    }
    int count = 1;
    bool inside = othersInside;
    for (auto it = recorder->written.begin(); it != recorder->written.end(); ++it) {
        if (it->property == property) {
            count += it->count;
            inside = inside || it->othersInside;
            recorder->written.erase(it);
            break;
        }
    }
    recorder->written.push_back({property, count, inside});
}

void objectTouched(const DocumentObject* object)
{
    Recorder* recorder = active;
    if (recorder && object != recorder->object && recorder->ownDepth == 0
        && !recorder->wroteOthers) {
        recorder->wroteOthers = true;
        recorder->why = "touched " + nameOf(object);
    }
}

void forget(const DocumentObject* object)
{
    auto it = memos.find(object);
    if (it != memos.end()) {
        for (const Property* property : it->second.historyOf) {
            history.erase(property);
        }
        memos.erase(it);
    }
    serials.erase(object);
}

DocumentObjectExecReturn* run(
    DocumentObject* object,
    const std::function<DocumentObjectExecReturn*()>& execute
)
{
    const int level = mode();
    const Document* document = object->getDocument();
    auto plain = [&]() {
        // Watched all the same when it runs within another's run
        Recorder recorder;
        recorder.object = object;
        const RecorderScope scope(recorder);
        ++counters.runs;
        return execute();
    };
    if (level <= 0 || !document || document->testStatus(Document::Restoring)
        || document->isPerformingTransaction()) {
        return plain();
    }
    if (!isAllowed(object)) {
        ++counters.notAllowed;
        return plain();
    }
    std::string key;
    if (!makeKey(object, key)) {
        ++counters.noKey;
        return plain();
    }
    const std::string name = nameOf(object);

    Entry* hit = nullptr;
    {
        ObjectMemo& memo = memoOf(object);
        if (!memo.syncing) {
            hit = findEntry(memo, key);
        }
    }
    if (hit && level == 1) {
        hit->used = ++useClock;
        // A copy: a paste may run other things, and the entries may move
        const Entry entry = *hit;
        ++counters.hits;
        paste(object, entry);
        object->setStatus(App::RecomputeExtension, false);
        return DocumentObject::StdReturn;
    }

    const std::string warningBefore = [&]() {
        const char* text = document->getWarningDescription(object);
        return std::string(text ? text : "");
    }();
    Recorder recorder;
    recorder.object = object;
    DocumentObjectExecReturn* result = nullptr;
    {
        const RecorderScope scope(recorder);
        ++counters.runs;
        result = execute();
    }
    // The entries may have moved while it ran
    ObjectMemo& memo = memoOf(object);
    if (result != DocumentObject::StdReturn) {
        return result;
    }
    hit = level == 2 && !memo.syncing ? findEntry(memo, key) : nullptr;

    std::string why;
    bool keep = true;
    if (recorder.impure) {
        keep = false;
        why = recorder.why;
    }
    else if (const char* text = document->getWarningDescription(object);
             warningBefore != (text ? text : "")) {
        keep = false;
        why = "set a warning";
    }
    std::vector<Output> outputs;
    if (keep && !makeOutputs(recorder, outputs, why)) {
        keep = false;
    }
    bool inputsOk = true;
    std::vector<std::pair<std::string, std::uint64_t>> inputs;
    if (keep) {
        // Its token as it was before the run named the handles; they are the same properties
        if (!makeToken(object, memo)) {
            keep = false;
            why = "no token after the run";
        }
        else {
            inputs = inputsOf(memo, outputs, inputsOk);
            if (!inputsOk) {
                keep = false;
                why = "no identity for an input shape";
            }
        }
    }

    if (hit) {
        // Verify mode: the run that a hit would have replaced
        std::string difference;
        if (recorder.wroteOthers) {
            ++counters.verifyErrors;
            note("VERIFY " + name + ": a hit would have skipped that it " + recorder.why);
            FC_ERR("Recompute memo: " << name << " hit, but its run " << recorder.why);
        }
        else if (!keep) {
            ++counters.verifyErrors;
            note("VERIFY " + name + ": a hit, but the run isn't kept: " + why);
            FC_ERR("Recompute memo: " << name << " hit, but its run can't be kept: " << why);
        }
        else if (!sameOutputs(outputs, hit->outputs, difference)) {
            ++counters.verifyErrors;
            note("VERIFY " + name + ": differs in " + difference);
            FC_ERR("Recompute memo: " << name << " hit, but a run differs in " << difference);
        }
        else {
            ++counters.hits;
        }
    }

    if (recorder.wroteOthers) {
        // It syncs other objects when they differ from what it wants: only a run does that
        if (!memo.syncing) {
            memo.syncing = true;
            note(name + " runs every time from now: it " + recorder.why);
        }
    }
    if (!keep) {
        ++counters.notRecorded;
        note(name + " not kept: " + why);
        return result;
    }

    // A result equal in content to an earlier one takes its identity: what reads it hits
    for (auto& entry : memo.entries) {
        std::string difference;
        if (sameOutputs(outputs, entry.outputs, difference)) {
            bool aliased = false;
            for (auto& output : outputs) {
                if (!output.handle) {
                    continue;
                }
                const auto other =
                    std::find_if(entry.outputs.begin(), entry.outputs.end(), [&](const Output& o) {
                        return o.name == output.name;
                    });
                if (other == entry.outputs.end() || other->stamp == output.stamp) {
                    continue;
                }
                Property* property = object->getPropertyByName(output.name.c_str());
                const HandleHooks* hooks = property ? hooksOf(property) : nullptr;
                if (hooks) {
                    aliasStamp(property, *hooks, other->stamp);
                    output.stamp = other->stamp;
                    aliased = true;
                }
            }
            if (aliased) {
                ++counters.canonical;
            }
            break;
        }
    }

    memo.entries.erase(
        std::remove_if(
            memo.entries.begin(),
            memo.entries.end(),
            [&](const Entry& entry) { return entry.key == key && entry.inputs == inputs; }
        ),
        memo.entries.end()
    );
    Entry entry;
    entry.key = key;
    entry.inputs = std::move(inputs);
    entry.outputs = std::move(outputs);
    entry.used = ++useClock;
    memo.entries.push_back(std::move(entry));
    while (memo.entries.size() > keptRuns) {
        auto oldest = std::min_element(
            memo.entries.begin(),
            memo.entries.end(),
            [](const Entry& a, const Entry& b) { return a.used < b.used; }
        );
        memo.entries.erase(oldest);
    }
    ++counters.recorded;
    return result;
}

}  // namespace App::RecomputeMemo
