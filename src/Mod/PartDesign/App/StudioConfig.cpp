// SPDX-License-Identifier: LGPL-2.1-or-later

// A part studio's configurations, Onshape's (FreeCAD-CH ops#671): see StudioConfig.h and
// notes/configurations-design.md.

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <numbers>
#include <set>

#include <nlohmann/json.hpp>

#include <App/Application.h>
#include <App/ConfigurationHooks.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/Expression.h>
#include <App/Link.h>
#include <App/ObjectIdentifier.h>
#include <App/Part.h>
#include <App/PropertyExpressionEngine.h>
#include <App/PropertyUnits.h>
#include <Base/Exception.h>
#include <Base/Quantity.h>
#include <Base/Unit.h>

#include "Body.h"
#include "FeatureTransformed.h"
#include "Pieces.h"
#include "ShapeBinder.h"
#include "Studio.h"
#include "StudioConfig.h"
#include "StudioList.h"

using json = nlohmann::json;

namespace PartDesign
{

PROPERTY_SOURCE(PartDesign::StudioConfig, App::VarSet)

namespace
{

// Set while configReconcile() writes: the expression write hook lets those writes through
thread_local bool writingCells = false;

struct WritingCells
{
    bool old;
    WritingCells()
        : old(writingCells)
    {
        writingCells = true;
    }
    ~WritingCells()
    {
        writingCells = old;
    }
    WritingCells(const WritingCells&) = delete;
    WritingCells& operator=(const WritingCells&) = delete;
};

bool refuse(std::string* why, const std::string& text)
{
    if (why) {
        *why = text;
    }
    return false;
}

std::string refuseText(std::string* why, const std::string& text)
{
    refuse(why, text);
    return {};
}

std::string quoted(const App::DocumentObject* obj)
{
    return std::string("'") + (obj ? obj->Label.getValue() : "?") + "'";
}

/// Shortest text that reads back as v
std::string number(double v)
{
    char buf[64];
    for (int precision : {15, 16, 17}) {
        std::snprintf(buf, sizeof(buf), "%.*g", precision, v);
        if (std::strtod(buf, nullptr) == v) {
            break;
        }
    }
    return buf;
}

/// StudioConfig objects alive in the session (any document, the undo stack's too): none, and
/// StudioConfig::of() returns at once (the Link and expression hooks call it on every write)
std::atomic<int> liveConfigs {0};

/// A saved value as JSON. A value that can't be read throws (loud): read as empty, the next edit
/// would write over it (ops#671 review)
json parsed(const App::PropertyString& prop, const char* list)
{
    const std::string text = prop.getValue();
    json j;
    if (!text.empty()) {
        try {
            j = json::parse(text);
        }
        catch (const json::exception& e) {
            throw Base::RuntimeError(std::string("The configuration's saved ") + prop.getName()
                                     + " can't be read: " + e.what());
        }
        if (!j.is_object()) {
            throw Base::RuntimeError(std::string("The configuration's saved ") + prop.getName()
                                     + " is not a JSON object");
        }
    }
    if (!j.is_object()) {
        j = json::object();
    }
    j["version"] = 1;
    if (!j.contains(list) || !j[list].is_array()) {
        j[list] = json::array();
    }
    return j;
}

json inputsOf(const StudioConfig* cfg)
{
    return parsed(cfg->Inputs, "inputs");
}

json tableOf(const StudioConfig* cfg)
{
    json t = parsed(cfg->Table, "params");
    if (!t.contains("suppress") || !t["suppress"].is_array()) {
        t["suppress"] = json::array();
    }
    return t;
}

void store(App::PropertyString& prop, const json& j)
{
    const std::string text = j.dump();
    if (text != prop.getValue()) {
        prop.setValue(text);
    }
}

std::string str(const json& j, const char* key)
{
    return j.contains(key) && j[key].is_string() ? j[key].get<std::string>() : std::string();
}

json* findInput(json& inputs, const std::string& idOrName)
{
    for (auto& in : inputs["inputs"]) {
        if (str(in, "id") == idOrName) {
            return &in;
        }
    }
    for (auto& in : inputs["inputs"]) {
        if (str(in, "name") == idOrName) {
            return &in;
        }
    }
    return nullptr;
}

const json* findInput(const json& inputs, const std::string& idOrName)
{
    return findInput(const_cast<json&>(inputs), idOrName);
}

const json* findRow(const json& input, const std::string& idOrName)
{
    for (const auto& r : input["rows"]) {
        if (str(r, "id") == idOrName) {
            return &r;
        }
    }
    for (const auto& r : input["rows"]) {
        if (str(r, "name") == idOrName) {
            return &r;
        }
    }
    return nullptr;
}

/// The input's cells' keys: its row ids, or "false" and "true"
std::vector<std::string> cellKeys(const json& input)
{
    std::vector<std::string> keys;
    if (str(input, "kind") == "list") {
        for (const auto& r : input["rows"]) {
            keys.push_back(str(r, "id"));
        }
    }
    else {
        keys = {"false", "true"};
    }
    return keys;
}

std::string defaultValue(const json& input)
{
    const std::string kind = str(input, "kind");
    if (kind == "list") {
        return str(input, "default");
    }
    if (kind == "checkbox") {
        return input.value("default", true) ? "true" : "false";
    }
    if (str(input, "type") == "Text") {
        return str(input, "default");
    }
    return number(input.value("default", 0.0));
}

/// Every input's active value (Active's where it is valid, else the default)
std::map<std::string, std::string> activeValues(const StudioConfig* cfg)
{
    const json inputs = inputsOf(cfg);
    const auto& active = cfg->Active.getValues();
    std::map<std::string, std::string> values;
    for (const auto& in : inputs["inputs"]) {
        const std::string id = str(in, "id");
        std::string v = defaultValue(in);
        auto it = active.find(id);
        if (it != active.end()) {
            const std::string kind = str(in, "kind");
            if (kind == "list") {
                const json* row = findRow(in, it->second);
                if (row && str(*row, "id") == it->second) {
                    v = it->second;
                }
            }
            else if (kind == "checkbox") {
                if (it->second == "true" || it->second == "false") {
                    v = it->second;
                }
            }
            else {
                v = it->second;
            }
        }
        values[id] = v;
    }
    return values;
}

/// Onshape (CP2-7): changing a default doesn't change the active value. An input with no active
/// value of its own (it follows its default) gets its current value as one first
void pinActive(StudioConfig* cfg, const std::string& id)
{
    auto active = cfg->Active.getValues();
    if (active.contains(id)) {
        return;
    }
    const auto values = activeValues(cfg);
    auto it = values.find(id);
    if (it != values.end()) {
        active[id] = it->second;
        cfg->Active.setValues(active);
    }
}

App::Part* studioOfObject(const App::DocumentObject* obj)
{
    if (!obj) {
        return nullptr;
    }
    if (auto body = freecad_cast<Body*>(const_cast<App::DocumentObject*>(obj))) {
        App::Part* studio = nullptr;
        Part::BodyBase::studioOf(body, studio);
        return studio;
    }
    if (auto body = Body::findBodyOf(obj)) {
        App::Part* studio = nullptr;
        Part::BodyBase::studioOf(body, studio);
        return studio;
    }
    return App::Part::getPartOfObject(obj, /*recursive=*/true);
}

StudioConfig* configOfObject(const App::DocumentObject* obj)
{
    if (!obj || !obj->getDocument()) {
        return nullptr;
    }
    return StudioConfig::of(obj->getDocument(), studioOfObject(obj));
}

/// The configured studio source belongs to (a Part shown whole, or a part of one), or null
StudioConfig* sourceConfig(const App::DocumentObject* source)
{
    if (!source || !source->getDocument()) {
        return nullptr;
    }
    if (auto part = freecad_cast<App::Part*>(const_cast<App::DocumentObject*>(source))) {
        if (auto cfg = StudioConfig::of(source->getDocument(), part)) {
            return cfg->hasInputs() ? cfg : nullptr;
        }
    }
    auto cfg = configOfObject(source);
    return cfg && cfg->hasInputs() ? cfg : nullptr;
}

/// path of obj as the Table keeps it (the engine's canonical form); throws on a bad path
std::string canonical(const App::DocumentObject* obj, const std::string& path)
{
    App::ObjectIdentifier id = App::ObjectIdentifier::parse(obj, path);
    if (!id.getProperty()) {
        throw Base::ValueError("no property " + path + " in " + quoted(obj));
    }
    return obj->ExpressionEngine.canonicalPath(id).toString();
}

/// The expression a cell binds: its text parsed in obj, or, when it doesn't parse, a text
/// expression that fails to evaluate, so the feature errors while this row is active (F7)
std::shared_ptr<App::Expression> cellExpression(const App::DocumentObject* obj, const std::string& text)
{
    try {
        return std::shared_ptr<App::Expression>(App::Expression::parse(obj, text));
    }
    catch (const Base::Exception& e) {
        std::string message = std::string("configuration cell '") + text + "': " + e.what();
        std::ranges::replace(message, '>', ')');
        return std::shared_ptr<App::Expression>(
            App::Expression::parse(obj, "<<" + message + ">>"));
    }
}

/// Whether a table entry is obj's: its name and its object ID. A configured object that was deleted
/// keeps its entry (its undo brings the configuration back), and a later object given the same name
/// is not configured by it
bool isEntryOf(const json& e, const App::DocumentObject* obj)
{
    if (!obj || !obj->isAttachedToDocument() || str(e, "object") != obj->getNameInDocument()) {
        return false;
    }
    return !e.contains("id") || !e["id"].is_number_integer() || e["id"].get<long>() == obj->getID();
}

/// The object a table entry configures, or null (deleted, or its name now another object's, or
/// an object outside cfg's studio: a pasted studio's copied table names the originals, which it
/// must never write, ops#671 review P5)
App::DocumentObject* entryObject(const StudioConfig* cfg, const json& e)
{
    App::DocumentObject* obj = cfg->getDocument()->getObject(str(e, "object").c_str());
    return isEntryOf(e, obj) && studioOfObject(obj) == cfg->studio() ? obj : nullptr;
}

json* findParam(json& table, const App::DocumentObject* obj, const std::string& path)
{
    for (auto& p : table["params"]) {
        if (isEntryOf(p, obj) && str(p, "path") == path) {
            return &p;
        }
    }
    return nullptr;
}

json* findSuppress(json& table, const App::DocumentObject* obj)
{
    for (auto& s : table["suppress"]) {
        if (isEntryOf(s, obj)) {
            return &s;
        }
    }
    return nullptr;
}

App::PropertyBool* suppressedProperty(App::DocumentObject* owner, bool add)
{
    auto prop = freecad_cast<App::PropertyBool*>(owner->getPropertyByName("Suppressed"));
    if (!prop && add) {
        prop = static_cast<App::PropertyBool*>(owner->addDynamicProperty(
            "App::PropertyBool",
            "Suppressed",
            "Studio",
            "Suppressed: its steps pass their base through (ops#654)",
            App::Prop_Hidden
        ));
    }
    return prop;
}

/// The value text of obj's path now: its expression's, or its value's
std::string currentText(App::DocumentObject* obj, const std::string& path)
{
    App::ObjectIdentifier id = App::ObjectIdentifier::parse(obj, path);
    auto info = obj->getExpression(id);
    if (info.expression) {
        return info.expression->toString();
    }
    // The property's own path value: a sketch's Constraints.<name> is its dimension (the Python
    // attribute path knows no constraint names)
    const App::any value = id.getValue(true);
    if (value.type() == typeid(Base::Quantity)) {
        const auto& q = App::any_cast<Base::Quantity>(value);
        const std::string unit = q.getUnit().getString();
        return number(q.getValue()) + (unit.empty() ? "" : " " + unit);
    }
    if (value.type() == typeid(double)) {
        return number(App::any_cast<double>(value));
    }
    if (value.type() == typeid(float)) {
        return number(App::any_cast<float>(value));
    }
    if (value.type() == typeid(int)) {
        return std::to_string(App::any_cast<int>(value));
    }
    if (value.type() == typeid(long)) {
        return std::to_string(App::any_cast<long>(value));
    }
    if (value.type() == typeid(bool)) {
        return App::any_cast<bool>(value) ? "1" : "0";
    }
    throw Base::TypeError(quoted(obj) + "'s " + path + " is no number: it can't be configured");
}

/// configReconcile's work; changed collects the objects whose expression or suppression it wrote
std::string reconcileCells(StudioConfig* cfg, bool checkOnly, std::set<App::DocumentObject*>* changed)
{
    const json inputs = inputsOf(cfg);
    json table = tableOf(cfg);
    const auto values = activeValues(cfg);
    std::vector<std::string> differ;
    WritingCells writing;

    auto activeCell = [&](const json& entry) -> const json* {
        auto v = values.find(str(entry, "input"));
        if (v == values.end() || !entry.contains("cells") || !entry["cells"].contains(v->second)) {
            return nullptr;
        }
        return &entry["cells"][v->second];
    };

    for (const auto& p : table["params"]) {
        App::DocumentObject* obj = entryObject(cfg, p);
        const json* cell = activeCell(p);
        if (!obj || !cell || !cell->is_string()) {
            continue;
        }
        const std::string path = str(p, "path");
        App::ObjectIdentifier id;
        try {
            id = App::ObjectIdentifier::parse(obj, path);
        }
        catch (const Base::Exception&) {
            differ.push_back(obj->getNameInDocument() + std::string(".") + path + ": no such path");
            continue;
        }
        auto want = cellExpression(obj, cell->get<std::string>());
        auto have = obj->getExpression(id).expression;
        if (have && want && have->isSame(*want, false)) {
            continue;
        }
        if (checkOnly) {
            differ.push_back(obj->getNameInDocument() + std::string(".") + path + " is "
                             + (have ? "'" + have->toString() + "'" : "not bound")
                             + ", its active cell '" + cell->get<std::string>() + "'");
            continue;
        }
        obj->ExpressionEngine.setValue(id, want);
        if (changed) {
            changed->insert(obj);
        }
    }

    for (const auto& s : table["suppress"]) {
        App::DocumentObject* obj = entryObject(cfg, s);
        const json* cell = activeCell(s);
        if (!obj || !cell || !cell->is_boolean()) {
            continue;
        }
        const bool on = cell->get<bool>();
        auto prop = suppressedProperty(obj, false);
        const bool have = prop && prop->getValue();
        if (have == on) {
            continue;
        }
        if (checkOnly) {
            differ.push_back(obj->getNameInDocument() + std::string(" is ")
                             + (have ? "suppressed" : "not suppressed") + ", its active cell "
                             + (on ? "suppressed" : "not suppressed"));
            continue;
        }
        suppressedProperty(obj, true)->setValue(on);
        if (changed) {
            changed->insert(obj);
        }
    }

    for (const auto& in : inputs["inputs"]) {
        if (str(in, "kind") != "variable") {
            continue;
        }
        const std::string name = str(in, "name");
        App::Property* prop = cfg->getDynamicPropertyByName(name.c_str());
        auto v = values.find(str(in, "id"));
        if (!prop || v == values.end()) {
            continue;
        }
        const std::string type = str(in, "type");
        bool same = true;
        if (auto text = freecad_cast<App::PropertyString*>(prop)) {
            same = v->second == text->getValue();
            if (!same && !checkOnly) {
                text->setValue(v->second);
            }
        }
        else if (auto integer = freecad_cast<App::PropertyInteger*>(prop)) {
            const long want = std::lround(std::strtod(v->second.c_str(), nullptr));
            same = integer->getValue() == want;
            if (!same && !checkOnly) {
                integer->setValue(want);
            }
        }
        else if (auto real = freecad_cast<App::PropertyFloat*>(prop)) {
            const double want = std::strtod(v->second.c_str(), nullptr);
            same = real->getValue() == want;
            if (!same && !checkOnly) {
                real->setValue(want);
            }
        }
        if (!same && checkOnly) {
            differ.push_back("the configuration Variable " + name + " is not its active value "
                             + v->second);
        }
    }

    if (!checkOnly) {
        // Written: what the load check found is gone (the next recompute clears the error)
        cfg->clearLoadMismatch();
    }
    std::string text;
    for (const auto& d : differ) {
        text += (text.empty() ? "" : "; ") + d;
    }
    return text;
}

/// The list reconcile after a cell or active-value change
bool reconcileList(StudioConfig* cfg, std::string* why)
{
    if (auto list = StudioList::of(cfg->getDocument(), cfg->studio())) {
        return list->reconcile(why);
    }
    return true;
}

bool rebind(StudioConfig* cfg, std::string* why, std::set<App::DocumentObject*>* changed = nullptr)
{
    reconcileCells(cfg, false, changed);
    return reconcileList(cfg, why);
}

StudioConfig* configOrRefuse(App::Part* studio, App::Document* doc, std::string* why)
{
    auto cfg = StudioConfig::of(doc, studio);
    if (!cfg || !cfg->hasInputs()) {
        refuse(why, std::string("The studio ") + (studio ? quoted(studio) : "") + " has no configuration inputs");
        return nullptr;
    }
    return cfg;
}

App::Document* docOf(App::Part* studio)
{
    if (studio) {
        return studio->getDocument();
    }
    return App::GetApplication().getActiveDocument();
}

bool isIdentifier(const std::string& name)
{
    if (name.empty() || !(std::isalpha(static_cast<unsigned char>(name[0])) || name[0] == '_')) {
        return false;
    }
    return std::ranges::all_of(name, [](char c) {
        return std::isalnum(static_cast<unsigned char>(c)) || c == '_';
    });
}

bool nameTaken(const json& inputs, const std::string& name)
{
    for (const auto& in : inputs["inputs"]) {
        if (str(in, "id") == name || str(in, "name") == name) {
            return true;
        }
    }
    return false;
}

std::string rowIdFor(const json& input, const std::string& name)
{
    std::string base;
    for (char c : name) {
        base += std::isalnum(static_cast<unsigned char>(c)) ? c : '_';
    }
    if (base.empty()) {
        base = "Row";
    }
    std::string id = base;
    for (int n = 2; findRow(input, id) && str(*findRow(input, id), "id") == id; ++n) {
        id = base + "_" + std::to_string(n);
    }
    return id;
}

/// The internal value (mm, degrees) of text for a Variable of type, or why not
bool variableValue(const std::string& type, const std::string& text, double& value, std::string* why)
{
    Base::Quantity q;
    try {
        q = Base::Quantity::parse(text);
    }
    catch (const Base::Exception& e) {
        return refuse(why, "'" + text + "' is no value: " + e.what());
    }
    const Base::Unit& unit = q.getUnit();
    if (type == "Length") {
        if (unit != Base::Unit::Length && unit != Base::Unit::One) {
            return refuse(why, "'" + text + "' is no length");
        }
    }
    else if (type == "Angle") {
        if (unit != Base::Unit::Angle && unit != Base::Unit::One) {
            return refuse(why, "'" + text + "' is no angle");
        }
    }
    else if (unit != Base::Unit::One) {
        return refuse(why, "'" + text + "' is no number");
    }
    value = q.getValue();
    if (type == "Integer" && value != std::round(value)) {
        return refuse(why, "'" + text + "' is no integer");
    }
    return true;
}

/// The key text of an input's value
std::string keyValue(const json& in, const std::string& v)
{
    if (str(in, "kind") != "variable") {
        return v;
    }
    const std::string type = str(in, "type");
    const double x = std::strtod(v.c_str(), nullptr);
    char buf[64];
    if (type == "Length") {
        std::snprintf(buf, sizeof(buf), "%.17g meter", x / 1000.0);
        return buf;
    }
    if (type == "Angle") {
        std::snprintf(buf, sizeof(buf), "%.17g radian", x * std::numbers::pi / 180.0);
        return buf;
    }
    if (type == "Integer") {
        return std::to_string(std::llround(x));
    }
    if (type == "Real") {
        std::snprintf(buf, sizeof(buf), "%.17g", x);
        return buf;
    }
    return v;
}

/// Resolves the user's values (input id or name -> row id or name, a bool, a value) into Active's
bool resolveValues(const StudioConfig* cfg,
                   const std::map<std::string, std::string>& given,
                   std::map<std::string, std::string>& out,
                   std::string* why)
{
    const json inputs = inputsOf(cfg);
    for (const auto& [key, value] : given) {
        const json* in = findInput(inputs, key);
        if (!in) {
            return refuse(why, "No configuration input '" + key + "'");
        }
        const std::string id = str(*in, "id");
        const std::string kind = str(*in, "kind");
        if (kind == "list") {
            const json* row = findRow(*in, value);
            if (!row) {
                return refuse(why, "The input " + str(*in, "name") + " has no row '" + value + "'");
            }
            out[id] = str(*row, "id");
        }
        else if (kind == "checkbox") {
            std::string v = value;
            std::ranges::transform(v, v.begin(), [](unsigned char c) { return std::tolower(c); });
            if (v == "true" || v == "1" || v == "on") {
                out[id] = "true";
            }
            else if (v == "false" || v == "0" || v == "off") {
                out[id] = "false";
            }
            else {
                return refuse(why, "The checkbox " + str(*in, "name") + " takes true or false, not '" + value + "'");
            }
        }
        else {
            const std::string type = str(*in, "type");
            if (type == "Text") {
                out[id] = value;
                continue;
            }
            double x = 0;
            if (!variableValue(type, value, x, why)) {
                return false;
            }
            // Onshape's UI refuses a value out of range (its field turns invalid; CF8)
            const double lo = in->value("min", -HUGE_VAL);
            const double hi = in->value("max", HUGE_VAL);
            if (x < lo || x > hi) {
                return refuse(why, "Enter a value between " + number(lo) + " and " + number(hi)
                                       + " for " + str(*in, "name") + " (was '" + value + "')");
            }
            out[id] = number(x);
        }
    }
    return true;
}

/// The readers (Links, SubShapeBinders) outside the studio that show its parts
std::vector<App::DocumentObject*> outsideReaders(StudioConfig* cfg)
{
    std::vector<App::DocumentObject*> readers;
    for (auto obj : cfg->getDocument()->getObjects()) {
        std::vector<App::DocumentObject*> sources;
        if (auto link = obj->getExtensionByType<App::LinkBaseExtension>(true)) {
            if (link->getLinkedObjectProperty()) {
                if (auto linked = link->getTrueLinkedObject(true)) {
                    sources.push_back(linked);
                }
            }
        }
        else if (auto binder = freecad_cast<SubShapeBinder*>(obj)) {
            sources = binder->Support.getValues();
        }
        for (auto src : sources) {
            if (sourceConfig(src) == cfg && !configReaderKey(obj, src).empty()) {
                readers.push_back(obj);
                break;
            }
        }
    }
    return readers;
}

/// The expression write hook: a write to a configured path becomes its active row's cell
bool hookWrite(App::DocumentObject* owner,
               const App::ObjectIdentifier& path,
               const std::shared_ptr<App::Expression>& expr)
{
    if (writingCells || !owner || !owner->isAttachedToDocument()) {
        return false;
    }
    App::Document* doc = owner->getDocument();
    if (doc->isPerformingTransaction() || owner->isRestoring()
        || doc->testStatus(App::Document::Restoring)) {
        return false;
    }
    auto cfg = configOfObject(owner);
    if (!cfg || cfg == owner) {
        return false;
    }
    json table = tableOf(cfg);
    const std::string pathText = path.toString();
    json* p = findParam(table, owner, pathText);
    if (!p) {
        return false;
    }
    if (!expr) {
        throw Base::RuntimeError(quoted(owner) + "'s " + pathText
                                 + " is configured: remove the configuration first");
    }
    std::string why;
    if (!configSetCell(owner, pathText, std::string(), expr->toString(), &why)) {
        throw Base::RuntimeError(why);
    }
    return true;
}

}  // namespace

// ---------------------------------------------------------------------------------------------

StudioConfig::StudioConfig()
{
    ++liveConfigs;
    ADD_PROPERTY_TYPE(Inputs, (""), "Configuration", App::Prop_Hidden,
                      "The configuration inputs (JSON; FreeCAD-CH ops#671)");
    ADD_PROPERTY_TYPE(Table, (""), "Configuration", App::Prop_Hidden,
                      "The configured parameters and suppressions (JSON)");
    ADD_PROPERTY_TYPE(Active, (), "Configuration", App::Prop_Hidden,
                      "The studio's active configuration: input id -> value");
}

App::DocumentObjectExecReturn* StudioConfig::execute()
{
    // The check again, not only the load's: an undo past the write that cleared a load mismatch
    // brings the file's expressions back, and the error with them (review R3). Check only: an
    // edit, undo or redo leaves the expressions and the cells agreeing, so this finds nothing
    // but what the file brought
    try {
        mismatch = reconcileCells(this, true, nullptr);
    }
    catch (const Base::Exception& e) {  // no std::exception
        mismatch = e.what();
    }
    catch (const std::exception& e) {
        mismatch = e.what();
    }
    if (!mismatch.empty()) {
        return new App::DocumentObjectExecReturn(
            "The file's configured values are not the active configuration's: " + mismatch, this);
    }
    return App::VarSet::execute();
}

short StudioConfig::mustExecute() const
{
    return mismatch.empty() ? App::VarSet::mustExecute() : 1;
}

void StudioConfig::onDocumentRestored()
{
    App::VarSet::onDocumentRestored();
    // Check only (3.2): writing would touch every configured feature on open
    try {
        mismatch = reconcileCells(this, true, nullptr);
    }
    catch (const Base::Exception& e) {  // no std::exception
        mismatch = e.what();
    }
    catch (const std::exception& e) {
        mismatch = e.what();
    }
    if (!mismatch.empty()) {
        touch();
    }
}

StudioConfig::~StudioConfig()
{
    --liveConfigs;
}

StudioConfig* StudioConfig::of(App::Document* doc, App::Part* studio, bool create)
{
    if (!doc || (!create && liveConfigs.load() == 0)) {
        return nullptr;
    }
    for (auto obj : doc->getObjectsOfType(StudioConfig::getClassTypeId())) {
        auto cfg = static_cast<StudioConfig*>(obj);
        if (cfg->studio() == studio) {
            return cfg;
        }
    }
    if (!create) {
        return nullptr;
    }
    auto cfg = static_cast<StudioConfig*>(doc->addObject("PartDesign::StudioConfig", "Configurations"));
    if (studio) {
        studio->addObject(cfg);
    }
    return cfg;
}

App::Part* StudioConfig::studio() const
{
    return App::Part::getPartOfObject(this, /*recursive=*/true);
}

std::string StudioConfig::keyOf(const std::map<std::string, std::string>& values) const
{
    const json inputs = inputsOf(this);
    std::string key;
    for (const auto& in : inputs["inputs"]) {
        const std::string id = str(in, "id");
        auto it = values.find(id);
        const std::string v = it != values.end() ? it->second : defaultValue(in);
        key += (key.empty() ? "" : ";") + id + "=" + keyValue(in, v);
    }
    return key;
}

std::string StudioConfig::activeKey() const
{
    return keyOf(activeValues(this));
}

std::string StudioConfig::defaultKey() const
{
    return keyOf({});
}

bool StudioConfig::hasInputs() const
{
    return !inputsOf(this)["inputs"].empty();
}

std::string configReconcile(StudioConfig* config, bool checkOnly)
{
    if (!config) {
        return {};
    }
    const std::string text = reconcileCells(config, checkOnly, nullptr);
    if (!checkOnly) {
        // Written: what the load check found is gone (the next recompute clears the error)
        config->touch();
    }
    return text;
}

// ---- inputs -----------------------------------------------------------------------------------

namespace
{
/// The studio's StudioConfig, made on the first input
StudioConfig* configForInput(App::Part* studio, std::string* why)
{
    App::Document* doc = docOf(studio);
    if (!doc) {
        refuse(why, "No document");
        return nullptr;
    }
    return StudioConfig::of(doc, studio, true);
}
}  // namespace

std::string configAddList(App::Part* studio,
                          const std::string& name,
                          const std::vector<std::string>& rowNames,
                          std::string* why)
{
    auto cfg = configForInput(studio, why);
    if (!cfg) {
        return {};
    }
    json inputs = inputsOf(cfg);
    if (name.empty() || nameTaken(inputs, name)) {
        return refuseText(why, "An input needs a name of its own ('" + name + "')");
    }
    std::vector<std::string> names = rowNames.empty() ? std::vector<std::string> {"Default"} : rowNames;
    std::string id;
    for (int n = 1;; ++n) {
        id = "List_" + std::to_string(n);
        if (!nameTaken(inputs, id)) {
            break;
        }
    }
    json input = {{"id", id}, {"name", name}, {"kind", "list"}, {"rows", json::array()}};
    for (std::size_t i = 0; i < names.size(); ++i) {
        // Onshape's first row keeps the id "Default" whatever its name (CF1)
        const std::string rowId = i == 0 ? std::string("Default") : rowIdFor(input, names[i]);
        input["rows"].push_back({{"id", rowId}, {"name", names[i]}});
    }
    input["default"] = "Default";
    inputs["inputs"].push_back(input);
    store(cfg->Inputs, inputs);
    return id;
}

std::string configAddCheckbox(App::Part* studio, const std::string& name, bool defaultValue, std::string* why)
{
    auto cfg = configForInput(studio, why);
    if (!cfg) {
        return {};
    }
    json inputs = inputsOf(cfg);
    if (!isIdentifier(name) || nameTaken(inputs, name)) {
        return refuseText(why, "A checkbox needs a name of its own, letters, digits and _ ('" + name + "')");
    }
    inputs["inputs"].push_back({{"id", name}, {"name", name}, {"kind", "checkbox"}, {"default", defaultValue}});
    store(cfg->Inputs, inputs);
    return name;
}

std::string configAddVariable(App::Part* studio,
                              const std::string& name,
                              const std::string& type,
                              const std::string& defaultText,
                              const std::string& minimum,
                              const std::string& maximum,
                              std::string* why)
{
    static const std::map<std::string, const char*> propertyTypes = {
        {"Length", "App::PropertyDistance"},
        {"Angle", "App::PropertyAngle"},
        {"Integer", "App::PropertyInteger"},
        {"Real", "App::PropertyFloat"},
        {"Text", "App::PropertyString"},
    };
    auto pt = propertyTypes.find(type);
    if (pt == propertyTypes.end()) {
        return refuseText(why, "A configuration Variable is a Length, Angle, Integer, Real or Text, not '" + type + "'");
    }
    auto cfg = configForInput(studio, why);
    if (!cfg) {
        return {};
    }
    json inputs = inputsOf(cfg);
    if (!isIdentifier(name) || nameTaken(inputs, name) || cfg->getPropertyByName(name.c_str())) {
        return refuseText(why, "A configuration Variable needs a name of its own, letters, digits and _ ('" + name + "')");
    }
    json input = {{"id", name}, {"name", name}, {"kind", "variable"}, {"type", type}};
    if (type == "Text") {
        input["default"] = defaultText;
    }
    else {
        double def = 0;
        double lo = -HUGE_VAL;
        double hi = HUGE_VAL;
        if (!variableValue(type, defaultText, def, why)
            || (!minimum.empty() && !variableValue(type, minimum, lo, why))
            || (!maximum.empty() && !variableValue(type, maximum, hi, why))) {
            return {};
        }
        if (lo > hi || def < lo || def > hi) {
            return refuseText(why, "The default " + defaultText + " is not between the minimum and the maximum");
        }
        input["default"] = def;
        if (!minimum.empty()) {
            input["min"] = lo;
        }
        if (!maximum.empty()) {
            input["max"] = hi;
        }
    }
    inputs["inputs"].push_back(input);
    store(cfg->Inputs, inputs);
    cfg->addDynamicProperty(pt->second, name.c_str(), "Configuration",
                            "A configuration Variable (ops#671): its value is the active configuration's",
                            App::Prop_ReadOnly);
    std::string ignored;
    rebind(cfg, &ignored);
    return name;
}

std::string configAddRow(App::Part* studio, const std::string& input, const std::string& name, std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return {};
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in || str(*in, "kind") != "list") {
        return refuseText(why, "No List input '" + input + "'");
    }
    if (name.empty() || findRow(*in, name)) {
        return refuseText(why, "A row needs a name of its own ('" + name + "')");
    }
    const std::string id = rowIdFor(*in, name);
    (*in)["rows"].push_back({{"id", id}, {"name", name}});
    const std::string inputId = str(*in, "id");
    const std::string from = str(*in, "default");
    json table = tableOf(cfg);
    for (const char* list : {"params", "suppress"}) {
        for (auto& e : table[list]) {
            if (str(e, "input") == inputId && e["cells"].contains(from)) {
                e["cells"][id] = e["cells"][from];
            }
        }
    }
    store(cfg->Inputs, inputs);
    store(cfg->Table, table);
    return id;
}

bool configRenameRow(App::Part* studio,
                     const std::string& input,
                     const std::string& row,
                     const std::string& name,
                     std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return false;
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in || str(*in, "kind") != "list") {
        return refuse(why, "No List input '" + input + "'");
    }
    for (auto& r : (*in)["rows"]) {
        if (str(r, "id") == row) {
            for (const auto& other : (*in)["rows"]) {
                if (&other != &r && (str(other, "name") == name || str(other, "id") == name)) {
                    return refuse(why, "A row needs a name of its own ('" + name + "')");
                }
            }
            r["name"] = name;
            store(cfg->Inputs, inputs);
            return true;
        }
    }
    return refuse(why, "No row '" + row + "'");
}

bool configRemoveRow(App::Part* studio, const std::string& input, const std::string& row, std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return false;
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in || str(*in, "kind") != "list") {
        return refuse(why, "No List input '" + input + "'");
    }
    auto& rows = (*in)["rows"];
    if (rows.size() < 2) {
        return refuse(why, "A List keeps one row at least");
    }
    auto it = std::ranges::find_if(rows, [&](const json& r) { return str(r, "id") == row; });
    if (it == rows.end()) {
        return refuse(why, "No row '" + row + "'");
    }
    rows.erase(it);
    if (str(*in, "default") == row) {
        (*in)["default"] = str(rows[0], "id");
    }
    const std::string inputId = str(*in, "id");
    json table = tableOf(cfg);
    for (const char* list : {"params", "suppress"}) {
        for (auto& e : table[list]) {
            if (str(e, "input") == inputId) {
                e["cells"].erase(row);
            }
        }
    }
    store(cfg->Inputs, inputs);
    store(cfg->Table, table);
    auto active = cfg->Active.getValues();
    if (active.contains(inputId) && active[inputId] == row) {
        active.erase(inputId);
        cfg->Active.setValues(active);
    }
    return rebind(cfg, why);
}

bool configSetDefaultRow(App::Part* studio, const std::string& input, const std::string& row, std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return false;
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in || str(*in, "kind") != "list") {
        return refuse(why, "No List input '" + input + "'");
    }
    const json* r = findRow(*in, row);
    if (!r) {
        return refuse(why, "No row '" + row + "'");
    }
    pinActive(cfg, str(*in, "id"));
    (*in)["default"] = str(*r, "id");
    store(cfg->Inputs, inputs);
    return rebind(cfg, why);
}

bool configMoveRow(App::Part* studio, const std::string& input, const std::string& row, int index, std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return false;
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in || str(*in, "kind") != "list") {
        return refuse(why, "No List input '" + input + "'");
    }
    json& rows = (*in)["rows"];
    const int count = static_cast<int>(rows.size());
    if (index < 0 || index >= count) {
        return refuse(why, "No position " + std::to_string(index) + " among " + std::to_string(count) + " rows");
    }
    for (int i = 0; i < count; ++i) {
        if (str(rows[i], "id") == row) {
            if (i != index) {
                json moved = rows[i];
                rows.erase(rows.begin() + i);
                rows.insert(rows.begin() + index, moved);
                store(cfg->Inputs, inputs);
            }
            return true;
        }
    }
    return refuse(why, "No row '" + row + "'");
}

bool configRenameInput(App::Part* studio, const std::string& input, const std::string& name, std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return false;
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in) {
        return refuse(why, "No input '" + input + "'");
    }
    for (const auto& other : inputs["inputs"]) {
        if (&other != in && (str(other, "id") == name || str(other, "name") == name)) {
            return refuse(why, "An input needs a name of its own ('" + name + "')");
        }
    }
    if (name.empty()) {
        return refuse(why, "An input needs a name");
    }
    const std::string old = str(*in, "name");
    if (old == name) {
        return true;
    }
    if (str(*in, "kind") == "variable") {
        // Onshape (CP2-7) renames every input. A Variable's name is its property's (#name): the
        // property is renamed, and the expressions that read it follow
        if (!isIdentifier(name)) {
            return refuse(why, "A configuration Variable's name is used as #" + name
                                   + ": letters, digits and _, not starting with a digit");
        }
        App::Property* prop = cfg->getPropertyByName(old.c_str());
        if (!prop || cfg->getPropertyByName(name.c_str())) {
            return refuse(why, "The name " + name + " is taken");
        }
        if (!cfg->renameDynamicProperty(prop, name.c_str())) {
            return refuse(why, "The configuration Variable " + old + " can't be renamed to " + name);
        }
    }
    (*in)["name"] = name;
    store(cfg->Inputs, inputs);
    return true;
}

bool configMoveInput(App::Part* studio, const std::string& input, int index, std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return false;
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in) {
        return refuse(why, "No input '" + input + "'");
    }
    json& all = inputs["inputs"];
    const int count = static_cast<int>(all.size());
    if (index < 0 || index >= count) {
        return refuse(why, "No position " + std::to_string(index) + " among " + std::to_string(count) + " inputs");
    }
    const std::string id = str(*in, "id");
    for (int i = 0; i < count; ++i) {
        if (str(all[i], "id") == id) {
            if (i != index) {
                json moved = all[i];
                all.erase(all.begin() + i);
                all.insert(all.begin() + index, moved);
                store(cfg->Inputs, inputs);
            }
            return true;
        }
    }
    return refuse(why, "No input '" + input + "'");
}

bool configSetCheckboxDefault(App::Part* studio, const std::string& input, bool value, std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return false;
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in || str(*in, "kind") != "checkbox") {
        return refuse(why, "No Checkbox input '" + input + "'");
    }
    pinActive(cfg, str(*in, "id"));
    (*in)["default"] = value;
    store(cfg->Inputs, inputs);
    return rebind(cfg, why);
}

bool configEditVariable(App::Part* studio,
                        const std::string& input,
                        const std::string& defaultText,
                        const std::string& minimum,
                        const std::string& maximum,
                        std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return false;
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in || str(*in, "kind") != "variable") {
        return refuse(why, "No configuration Variable '" + input + "'");
    }
    const std::string type = str(*in, "type");
    if (type != "Text") {
        double def = 0;
        double lo = -HUGE_VAL;
        double hi = HUGE_VAL;
        if (!variableValue(type, defaultText, def, why)
            || (!minimum.empty() && !variableValue(type, minimum, lo, why))
            || (!maximum.empty() && !variableValue(type, maximum, hi, why))) {
            return false;
        }
        if (lo > hi || def < lo || def > hi) {
            return refuse(why, "The default " + defaultText + " is not between the minimum and the maximum");
        }
        pinActive(cfg, str(*in, "id"));
        (*in)["default"] = def;
        in->erase("min");
        in->erase("max");
        if (!minimum.empty()) {
            (*in)["min"] = lo;
        }
        if (!maximum.empty()) {
            (*in)["max"] = hi;
        }
        // An active value outside the new bounds goes: the input takes its new default
        auto active = cfg->Active.getValues();
        auto it = active.find(str(*in, "id"));
        if (it != active.end()) {
            char* end = nullptr;
            const double v = std::strtod(it->second.c_str(), &end);
            if (end == it->second.c_str() || v < lo || v > hi) {
                active.erase(it);
                cfg->Active.setValues(active);
            }
        }
    }
    else {
        pinActive(cfg, str(*in, "id"));
        (*in)["default"] = defaultText;
    }
    store(cfg->Inputs, inputs);
    return rebind(cfg, why);
}

bool configRemoveInput(App::Part* studio, const std::string& input, std::string* why)
{
    auto cfg = configOrRefuse(studio, docOf(studio), why);
    if (!cfg) {
        return false;
    }
    json inputs = inputsOf(cfg);
    json* in = findInput(inputs, input);
    if (!in) {
        return refuse(why, "No configuration input '" + input + "'");
    }
    const std::string id = str(*in, "id");
    if (str(*in, "kind") == "variable") {
        if (!cfg->getInList().empty()) {
            for (auto reader : cfg->getInList()) {
                if (reader != studio) {
                    return refuse(why, quoted(reader) + " uses the configuration Variable " + id);
                }
            }
        }
    }
    // What it configured keeps its active value (the expressions and suppressions stay)
    json table = tableOf(cfg);
    for (const char* list : {"params", "suppress"}) {
        auto& entries = table[list];
        entries.erase(std::remove_if(entries.begin(), entries.end(),
                                     [&](const json& e) { return str(e, "input") == id; }),
                      entries.end());
    }
    auto& all = inputs["inputs"];
    const std::string kind = str(*in, "kind");
    const std::string name = str(*in, "name");
    all.erase(std::ranges::find_if(all, [&](const json& e) { return str(e, "id") == id; }));
    store(cfg->Inputs, inputs);
    store(cfg->Table, table);
    auto active = cfg->Active.getValues();
    if (active.erase(id)) {
        cfg->Active.setValues(active);
    }
    if (kind == "variable") {
        cfg->removeDynamicProperty(name.c_str());
    }
    return rebind(cfg, why);
}

// ---- configured parameters and suppression ----------------------------------------------------

bool configIsConfigured(const App::DocumentObject* obj, const std::string& path)
{
    auto cfg = configOfObject(obj);
    if (!cfg) {
        return false;
    }
    try {
        json table = tableOf(cfg);
        return findParam(table, obj, canonical(obj, path)) != nullptr;
    }
    catch (const Base::Exception&) {
        return false;
    }
}

bool configSuppressionIsConfigured(const App::DocumentObject* owner)
{
    auto cfg = configOfObject(owner);
    if (!cfg || !owner->isAttachedToDocument()) {
        return false;
    }
    json table = tableOf(cfg);
    return findSuppress(table, owner) != nullptr;
}

std::string configInputOf(const App::DocumentObject* obj, const std::string& path)
{
    auto cfg = configOfObject(obj);
    if (!cfg || cfg == obj || !obj->isAttachedToDocument()) {
        return {};
    }
    try {
        json table = tableOf(cfg);
        const json* e = path.empty() ? findSuppress(table, obj) : findParam(table, obj, canonical(obj, path));
        if (!e) {
            return {};
        }
        const json inputs = inputsOf(cfg);
        const json* in = findInput(inputs, str(*e, "input"));
        return in ? str(*in, "name") : std::string();
    }
    catch (const Base::Exception&) {
        return {};
    }
    catch (const std::exception&) {
        return {};
    }
}

std::vector<App::ConfigMenuItem> configMenuItems(const App::DocumentObject* obj, const std::string& path)
{
    std::vector<App::ConfigMenuItem> items;
    if (!obj || !obj->isAttachedToDocument() || obj->isDerivedFrom<StudioConfig>()) {
        return items;
    }
    const bool suppression = path.empty();
    if (!suppression) {
        try {
            canonical(obj, path);
        }
        catch (const Base::Exception&) {
            return items;
        }
    }
    // Onshape (CP2-1, CP2-3): a configured field offers only its unconfigure; an unconfigured one
    // offers each List and Checkbox, and each configuration Variable ("Set to #len")
    const std::string configuredBy = configInputOf(obj, path);
    auto cfg = configOfObject(obj);
    if (!configuredBy.empty() && cfg) {
        json table = tableOf(cfg);
        const json* e = suppression ? findSuppress(table, obj) : findParam(table, obj, canonical(obj, path));
        items.push_back({suppression ? std::string("Unconfigure suppression") : "Unconfigure from " + configuredBy,
                         "unconfigure", e ? str(*e, "input") : std::string(), configuredBy});
        return items;
    }
    // With no input there is no item: the panel makes the first one ("Configure Part Studio").
    // With one, a plain "Configure"; with several, one item per List and Checkbox (CP2-1)
    if (!cfg) {
        return items;
    }
    const json inputs = inputsOf(cfg);
    const bool single = inputs.contains("inputs") && inputs["inputs"].size() == 1;
    for (const auto& in : inputs.value("inputs", json::array())) {
        const std::string kind = str(in, "kind");
        const std::string name = str(in, "name");
        if (kind == "list" || kind == "checkbox") {
            std::string label = suppression ? "Configure suppression" : "Configure";
            if (!single) {
                label += " with " + name;
            }
            items.push_back({label, "configure", str(in, "id"), name});
        }
        else if (kind == "variable" && !suppression) {
            items.push_back({"Set to #" + name, "variable", str(in, "id"), name});
        }
    }
    return items;
}

std::vector<ConfigEntry> configEntries(const StudioConfig* config)
{
    std::vector<ConfigEntry> out;
    if (!config) {
        return out;
    }
    const json table = tableOf(config);
    auto collect = [&](const char* list, bool suppression) {
        if (!table.contains(list) || !table[list].is_array()) {
            return;
        }
        for (const auto& e : table[list]) {
            // A stale entry (its object deleted, or its name now another object's) configures
            // nothing and is not shown; it stays for the undo that brings its object back
            App::DocumentObject* obj = entryObject(config, e);
            if (!obj) {
                continue;
            }
            ConfigEntry entry;
            entry.object = obj;
            entry.path = suppression ? std::string() : str(e, "path");
            entry.input = str(e, "input");
            if (e.contains("cells") && e["cells"].is_object()) {
                for (const auto& [key, cell] : e["cells"].items()) {
                    entry.cells[key] = cell.is_string() ? cell.get<std::string>()
                        : cell.is_boolean()             ? std::string(cell.get<bool>() ? "true" : "false")
                                                        : cell.dump();
                }
            }
            out.push_back(std::move(entry));
        }
    };
    collect("params", false);
    collect("suppress", true);
    // Onshape (CP2-4): the columns follow the feature order, not the order they were configured
    // in; a feature's parameters come before its suppression. Objects outside the studio's
    // sequence come last, in the table's order
    std::map<const App::DocumentObject*, std::size_t> rank;
    if (auto doc = config->getDocument()) {
        const auto sequence = studioSequence(doc, config->studio());
        for (std::size_t i = 0; i < sequence.size(); ++i) {
            rank.emplace(sequence[i], i);
        }
    }
    auto rankOf = [&](const ConfigEntry& e) {
        auto it = rank.find(e.object);
        return it != rank.end() ? it->second : rank.size();
    };
    std::ranges::stable_sort(out, {}, rankOf);
    return out;
}

bool configConfigure(App::DocumentObject* obj,
                     const std::string& path,
                     const std::string& input,
                     std::string* why)
{
    if (!obj || !obj->isAttachedToDocument()) {
        return refuse(why, "Nothing to configure");
    }
    auto cfg = configOfObject(obj);
    if (!cfg || !cfg->hasInputs()) {
        return refuse(why, quoted(obj) + "'s studio has no configuration inputs");
    }
    if (obj == cfg) {
        return refuse(why, "A configuration Variable can't be configured");
    }
    try {
        const std::string canon = canonical(obj, path);
        json inputs = inputsOf(cfg);
        const json* in = findInput(inputs, input);
        if (!in || str(*in, "kind") == "variable") {
            return refuse(why, "A parameter is configured with a List or a Checkbox ('" + input + "')");
        }
        json table = tableOf(cfg);
        if (findParam(table, obj, canon)) {
            return refuse(why, quoted(obj) + "'s " + canon + " is configured already: unconfigure it first");
        }
        const std::string text = currentText(obj, canon);
        json cells = json::object();
        for (const auto& key : cellKeys(*in)) {
            cells[key] = text;  // Onshape copies the current value into every row (CF3)
        }
        table["params"].push_back({{"object", obj->getNameInDocument()},
                                   {"id", obj->getID()},
                                   {"path", canon},
                                   {"input", str(*in, "id")},
                                   {"cells", cells}});
        store(cfg->Table, table);
        return rebind(cfg, why);
    }
    catch (const Base::Exception& e) {
        return refuse(why, e.what());
    }
}

bool configUnconfigure(App::DocumentObject* obj, const std::string& path, std::string* why)
{
    auto cfg = obj ? configOfObject(obj) : nullptr;
    if (!cfg) {
        return refuse(why, quoted(obj) + " is not configured");
    }
    try {
        const std::string canon = canonical(obj, path);
        json table = tableOf(cfg);
        json* p = findParam(table, obj, canon);
        if (!p) {
            return refuse(why, quoted(obj) + "'s " + canon + " is not configured");
        }
        auto& params = table["params"];
        params.erase(params.begin() + (p - &params[0]));
        store(cfg->Table, table);
        // It keeps the active cell; a plain value stops being an expression
        App::ObjectIdentifier id = App::ObjectIdentifier::parse(obj, canon);
        auto expr = obj->getExpression(id).expression;
        if (expr && expr->getIdentifiers().empty()) {
            const App::any value = expr->getValueAsAny();
            WritingCells writing;
            obj->ExpressionEngine.setValue(id, std::shared_ptr<App::Expression>());
            id.setValue(value);
        }
        return reconcileList(cfg, why);
    }
    catch (const Base::Exception& e) {
        return refuse(why, e.what());
    }
}

bool configSetCell(App::DocumentObject* obj,
                   const std::string& path,
                   const std::string& row,
                   const std::string& text,
                   std::string* why)
{
    auto cfg = obj ? configOfObject(obj) : nullptr;
    if (!cfg) {
        return refuse(why, quoted(obj) + " is not configured");
    }
    if (text.empty()) {
        return refuse(why, "A configured value can't be empty");
    }
    try {
        const std::string canon = canonical(obj, path);
        json table = tableOf(cfg);
        json* p = findParam(table, obj, canon);
        if (!p) {
            return refuse(why, quoted(obj) + "'s " + canon + " is not configured");
        }
        const json inputs = inputsOf(cfg);
        const json* in = findInput(inputs, str(*p, "input"));
        if (!in) {
            return refuse(why, "The configuration input of " + canon + " is gone");
        }
        std::string key = row;
        if (key.empty()) {
            key = activeValues(cfg)[str(*in, "id")];
        }
        else if (str(*in, "kind") == "list") {
            const json* r = findRow(*in, row);
            if (!r) {
                return refuse(why, "No row '" + row + "'");
            }
            key = str(*r, "id");
        }
        else if (key != "true" && key != "false") {
            return refuse(why, "A checkbox's cells are true and false, not '" + row + "'");
        }
        // The user's text stays where it means the same as what was written
        auto& cell = (*p)["cells"][key];
        if (!(cell.is_string() && cellExpression(obj, cell.get<std::string>())->isSame(*cellExpression(obj, text), false))) {
            cell = text;
        }
        store(cfg->Table, table);
        return rebind(cfg, why);
    }
    catch (const Base::Exception& e) {
        return refuse(why, e.what());
    }
}

bool configConfigureSuppression(App::DocumentObject* owner, const std::string& input, std::string* why)
{
    if (!owner || !owner->isAttachedToDocument()) {
        return refuse(why, "Nothing to configure");
    }
    if (Body::findBodyOf(owner) || !StudioList::holding(owner)) {
        return refuse(why, quoted(owner) + " can't be suppressed: its suppression can't be configured");
    }
    auto cfg = configOfObject(owner);
    if (!cfg || !cfg->hasInputs()) {
        return refuse(why, quoted(owner) + "'s studio has no configuration inputs");
    }
    json inputs = inputsOf(cfg);
    const json* in = findInput(inputs, input);
    if (!in || str(*in, "kind") == "variable") {
        return refuse(why, "Suppression is configured with a List or a Checkbox ('" + input + "')");
    }
    json table = tableOf(cfg);
    if (findSuppress(table, owner)) {
        return refuse(why, quoted(owner) + "'s suppression is configured already");
    }
    auto prop = suppressedProperty(owner, false);
    const bool now = prop && prop->getValue();
    json cells = json::object();
    for (const auto& key : cellKeys(*in)) {
        cells[key] = now;
    }
    table["suppress"].push_back({{"object", owner->getNameInDocument()},
                                     {"id", owner->getID()},
                                     {"input", str(*in, "id")},
                                     {"cells", cells}});
    store(cfg->Table, table);
    return rebind(cfg, why);
}

bool configUnconfigureSuppression(App::DocumentObject* owner, std::string* why)
{
    auto cfg = owner ? configOfObject(owner) : nullptr;
    if (!cfg) {
        return refuse(why, quoted(owner) + "'s suppression is not configured");
    }
    json table = tableOf(cfg);
    json* s = findSuppress(table, owner);
    if (!s) {
        return refuse(why, quoted(owner) + "'s suppression is not configured");
    }
    auto& all = table["suppress"];
    all.erase(all.begin() + (s - &all[0]));
    store(cfg->Table, table);
    return true;  // Suppressed keeps the active cell
}

bool configSetSuppressionCell(App::DocumentObject* owner, const std::string& row, bool suppressed, std::string* why)
{
    auto cfg = owner ? configOfObject(owner) : nullptr;
    if (!cfg) {
        return refuse(why, quoted(owner) + "'s suppression is not configured");
    }
    json table = tableOf(cfg);
    json* s = findSuppress(table, owner);
    if (!s) {
        return refuse(why, quoted(owner) + "'s suppression is not configured");
    }
    const json inputs = inputsOf(cfg);
    const json* in = findInput(inputs, str(*s, "input"));
    if (!in) {
        return refuse(why, "The configuration input of " + quoted(owner) + "'s suppression is gone");
    }
    std::string key = row;
    if (key.empty()) {
        key = activeValues(cfg)[str(*in, "id")];
    }
    else if (str(*in, "kind") == "list") {
        const json* r = findRow(*in, row);
        if (!r) {
            return refuse(why, "No row '" + row + "'");
        }
        key = str(*r, "id");
    }
    else if (key != "true" && key != "false") {
        return refuse(why, "A checkbox's cells are true and false, not '" + row + "'");
    }
    (*s)["cells"][key] = suppressed;
    store(cfg->Table, table);
    return rebind(cfg, why);
}

// ---- the switch -------------------------------------------------------------------------------

bool configSetActive(App::Part* studio, const std::map<std::string, std::string>& values, std::string* why)
{
    App::Document* doc = docOf(studio);
    auto cfg = configOrRefuse(studio, doc, why);
    if (!cfg) {
        return false;
    }
    std::map<std::string, std::string> resolved;
    if (!resolveValues(cfg, values, resolved, why)) {
        return false;
    }
    auto active = activeValues(cfg);
    for (const auto& [id, v] : resolved) {
        active[id] = v;
    }
    const bool own = !doc->hasPendingTransaction();
    if (own) {
        doc->openTransaction("Configuration");
    }
    try {
        if (active != cfg->Active.getValues()) {
            cfg->Active.setValues(active);
        }
        std::set<App::DocumentObject*> changed;
        reconcileCells(cfg, false, &changed);
        cfg->touch();
        if (!reconcileList(cfg, why)) {
            if (own) {
                doc->abortTransaction();
            }
            return false;
        }
        // The readers outside the studio check the new configuration against theirs (3.6)
        for (auto reader : outsideReaders(cfg)) {
            reader->touch();
        }
        // A suppression or a value that splits a part or leaves a solid outside its scope makes
        // parts, in this step, like a list drag (10.12)
        std::vector<App::DocumentObject*> makers;
        for (auto obj : changed) {
            if (isStudioOwner(obj)
                && (!studioScopeIds(obj).empty() || obj->isDerivedFrom<PartDesign::Transformed>())) {
                makers.push_back(obj);
            }
        }
        // In the list's order (then by object ID), never the set's pointer order: the pieces'
        // Bodies and ids are made in this order (I-N1, ops#671 review P4)
        std::vector<App::DocumentObject*> order;
        if (auto list = cfg->studio() ? StudioList::of(cfg->getDocument(), cfg->studio()) : nullptr) {
            order = list->Entries.getValues();
        }
        auto place = [&order](App::DocumentObject* obj) {
            auto it = std::ranges::find(order, obj);
            return std::pair<std::ptrdiff_t, long>(it - order.begin(), obj->getID());
        };
        std::ranges::sort(makers, {}, place);
        if (makers.empty()) {
            doc->recompute();
        }
        for (auto maker : makers) {
            std::string pieceWhy;
            makePieces(maker, &pieceWhy);
            if (!pieceWhy.empty()) {
                throw Base::RuntimeError(pieceWhy);
            }
        }
        if (own) {
            doc->commitTransaction();
        }
        return true;
    }
    catch (const Base::Exception& e) {
        if (own) {
            doc->abortTransaction();
        }
        return refuse(why, e.what());
    }
    catch (const std::exception& e) {  // a saved value of the wrong JSON type (review P3)
        if (own) {
            doc->abortTransaction();
        }
        return refuse(why, std::string("The configuration data can't be read: ") + e.what());
    }
}

std::string configKeyOf(const StudioConfig* config,
                        const std::map<std::string, std::string>& values,
                        std::string* why)
{
    std::map<std::string, std::string> resolved;
    if (!config || !resolveValues(config, values, resolved, why)) {
        return {};
    }
    return config->keyOf(resolved);
}

// ---- readers outside the studio ---------------------------------------------------------------

std::string configReaderKey(const App::DocumentObject* reader, const App::DocumentObject* source)
{
    auto cfg = sourceConfig(source);
    if (!cfg || !reader) {
        return {};
    }
    if (reader->getDocument() == cfg->getDocument() && studioOfObject(reader) == cfg->studio()) {
        return {};  // inside the studio
    }
    if (auto key = freecad_cast<App::PropertyString*>(reader->getPropertyByName("ConfigKey"))) {
        if (key->getValue()[0]) {
            return key->getValue();
        }
    }
    // Onshape's Insert and Derived pick the default row, not the shown one (CF8)
    return cfg->defaultKey();
}

bool configSetReaderKey(App::DocumentObject* reader,
                        const App::DocumentObject* source,
                        const std::map<std::string, std::string>& values,
                        std::string* why)
{
    auto cfg = sourceConfig(source);
    if (!cfg || !reader) {
        return refuse(why, quoted(source) + " is no configured studio's");
    }
    std::map<std::string, std::string> resolved;
    if (!resolveValues(cfg, values, resolved, why)) {
        return false;
    }
    auto prop = freecad_cast<App::PropertyString*>(reader->getPropertyByName("ConfigKey"));
    if (!prop) {
        prop = static_cast<App::PropertyString*>(reader->addDynamicProperty(
            "App::PropertyString", "ConfigKey", "Configuration",
            "The configuration of its studio this shows (ops#671)", App::Prop_Hidden));
    }
    prop->setValue(cfg->keyOf(resolved));
    reader->touch();
    return true;
}

std::string configReaderError(const App::DocumentObject* reader, const App::DocumentObject* source)
{
    // A part made from a piece whose solid is gone (its split suppressed, or another row's) keeps
    // its Body while something outside the studio reads it: the reader is loud, never showing
    // the solid it had or nothing at all (review R2, round 2)
    if (auto body = freecad_cast<const Body*>(source)) {
        if (body->StudioMadeBy.getValue() && !body->StudioPieceWitness.getValues().empty()
            && body->Shape.getShape().isNull()) {
            return quoted(body) + " holds no solid: the piece it was made from is gone (its split "
                   "is suppressed, or this configuration doesn't make it)";
        }
    }
    const std::string key = configReaderKey(reader, source);
    if (key.empty()) {
        return {};
    }
    auto cfg = sourceConfig(source);
    const std::string active = cfg->activeKey();
    if (key == active) {
        return {};
    }
    App::Part* studio = cfg->studio();
    return "The studio " + (studio ? quoted(studio) : std::string("of the document"))
        + " shows the configuration " + active + ", not this one's (" + key
        + "): until instances and Derived get their own configuration, switch the studio to it";
}

void registerConfigurationHooks()
{
    App::setExpressionWriteHook(hookWrite);
    App::setConfigReaderCheck(configReaderError);
    App::setConfiguredQuery([](const App::DocumentObject* obj, const App::ObjectIdentifier& path) {
        return configInputOf(obj, path.toString());
    });
    App::setConfigMenuQuery([](const App::DocumentObject* obj, const App::ObjectIdentifier& path) {
        return configMenuItems(obj, path.toString());
    });
    // An undo or redo can bring back expressions a StudioConfig's cells disagree with (a file
    // that failed the load check, then a configReconcile write undone) without restoring any of
    // its properties: touched, its execute() checks again (review R3, round 2)
    auto recheck = [](const App::Document& doc) {
        if (liveConfigs.load() == 0) {
            return;
        }
        for (auto obj : doc.getObjectsOfType(StudioConfig::getClassTypeId())) {
            obj->touch();
        }
    };
    App::GetApplication().signalUndoDocument.connect(recheck);
    App::GetApplication().signalRedoDocument.connect(recheck);
}

}  // namespace PartDesign
