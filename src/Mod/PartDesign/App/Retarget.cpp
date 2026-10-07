// SPDX-License-Identifier: LGPL-2.1-or-later

// The reorder's plan and the re-target rule (ops#127, notes/reorder-rollback-design.md 2.1 and
// section 3)

#include <algorithm>
#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>

#include <App/Application.h>
#include <App/ComplexGeoData.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <App/ElementSolverBatch.h>
#include <App/Expression.h>
#include <App/MergeDocuments.h>
#include <App/ObjectIdentifier.h>
#include <App/PropertyExpressionEngine.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Sketcher/App/ParkedReference.h>
#include <Mod/Sketcher/App/SketchObject.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureBase.h"
#include "FeatureDressUp.h"
#include "FeatureSketchBased.h"
#include "Retarget.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

namespace PartDesign
{

namespace
{

using Objects = std::vector<App::DocumentObject*>;
using ShadowSub = App::PropertyLinkBase::ShadowSub;

/// The dynamic property that holds an owner's parked references (N1 3.4 b)
constexpr const char* ParkedProperty = "ParkedReferences";

const char* nameOf(const App::DocumentObject* obj)
{
    return obj && obj->isAttachedToDocument() ? obj->Label.getValue() : "?";
}

/// The link properties whose target follows the feature's base (N1 2.2): rerouted with it,
/// never re-targeted by the rule
bool followsBase(const App::DocumentObject* owner, const App::Property* prop)
{
    if (auto feature = freecad_cast<const PartDesign::Feature*>(owner)) {
        if (prop == &feature->BaseFeature) {
            return true;
        }
    }
    if (auto dressUp = freecad_cast<const PartDesign::DressUp*>(owner)) {
        if (prop == &dressUp->Base) {
            return true;
        }
    }
    if (auto profileBased = freecad_cast<const PartDesign::ProfileBased*>(owner)) {
        if (prop == &profileBased->Profile && Body::isSolidFeature(profileBased->Profile.getValue())) {
            return true;
        }
    }
    return false;
}

/// A link property a path of inputs follows (N1 3.1): not the expressions (S4), not a hidden
/// one, not the Body link or the base chain
bool isInputLink(const App::DocumentObject* owner, const App::Property* prop)
{
    auto link = freecad_cast<const App::PropertyLinkBase*>(prop);
    if (!link || link->getScope() == App::LinkScope::Hidden || prop == &owner->ExpressionEngine) {
        return false;
    }
    if (auto feature = freecad_cast<const PartDesign::Feature*>(owner)) {
        if (prop == &feature->BaseFeature || prop == &feature->_Body) {
            return false;
        }
    }
    return true;
}

/// A link property the rule walks (N1 3.2): an input link that doesn't follow the base
bool isWalked(const App::DocumentObject* owner, const App::Property* prop)
{
    return isInputLink(owner, prop) && !followsBase(owner, prop);
}

bool isFeatureBase(const App::DocumentObject* obj)
{
    return obj && obj->isDerivedFrom<PartDesign::FeatureBase>();
}

// -- The parking record (N1 3.4 b): one line per item, keyed by content --------------------------

std::string escapeField(const std::string& text)
{
    std::string out;
    for (char c : text) {
        if (c == '%') {
            out += "%25";
        }
        else if (c == '|') {
            out += "%7C";
        }
        else {
            out += c;
        }
    }
    return out;
}

std::string unescapeField(const std::string& text)
{
    std::string out;
    for (std::size_t i = 0; i < text.size(); ++i) {
        if (text.compare(i, 3, "%25") == 0) {
            out += '%';
            i += 2;
        }
        else if (text.compare(i, 3, "%7C") == 0) {
            out += '|';
            i += 2;
        }
        else {
            out += text[i];
        }
    }
    return out;
}

/// One parked item: a link entry (`link|<property>|<T>|<sub>|<shadow new>|<shadow old>|<fp>|
/// <position>`, then `|<guess>|<orig>|<alt>[|<orig fp>]` when it has a guess record), a sketch's
/// projection parked in place (`extgeo|`, the same fields, then `|<type>|<ids>` before the guess
/// fields, ops#131) or an expression (`expr|<path>|<T>|<text>`). `<T>` is the object's name and,
/// since ops#158, its ID: `Pad2#17` (object names have no `#`; a line without the ID still reads)
struct ParkedItem
{
    bool expression = false;
    bool extgeo = false;  // a projection: its geometries stay in the sketch without the link
    std::string property;  // the property, or the expression's path
    std::string target;    // the name of the object it refers to
    long targetId = 0;     // its ID (getID()), 0 in lines written before ops#158, -1 when it
                           // is in another document (left behind by an import, see
                           // importParkedLines)
    std::string sub;
    std::string shadowNew;
    std::string shadowOld;
    std::string fp;
    std::size_t position = 0;
    std::string text;  // the expression
    App::GuessRecord guess;  // the entry's guess record (ops#127, N1 3.2), put back with it
    int type = 0;            // extgeo: the projection's type (ExternalTypes)
    std::vector<long> ids;   // extgeo: the Ids of its geometries, in projection order

    std::string line() const
    {
        std::ostringstream ss;
        if (expression) {
            ss << "expr|" << escapeField(property) << '|' << escapeField(targetField()) << '|'
               << escapeField(text);
        }
        else {
            ss << (extgeo ? "extgeo|" : "link|") << escapeField(property) << '|'
               << escapeField(targetField()) << '|' << escapeField(sub) << '|'
               << escapeField(shadowNew)
               << '|' << escapeField(shadowOld) << '|' << escapeField(fp) << '|' << position;
            if (extgeo) {
                ss << '|' << type << '|';
                for (std::size_t i = 0; i < ids.size(); ++i) {
                    ss << (i ? "," : "") << ids[i];
                }
            }
            if (!guess.empty()) {
                ss << '|' << escapeField(guess.kind) << '|' << escapeField(guess.origText()) << '|'
                   << escapeField(guess.altText());
                if (!guess.origFingerprint.empty()) {
                    ss << '|' << escapeField(guess.origFingerprint);  // ops#133
                }
            }
        }
        return ss.str();
    }

    std::string targetField() const
    {
        return targetId != 0 ? target + "#" + std::to_string(targetId) : target;
    }

    void setTarget(const std::string& field)
    {
        target = field;
        targetId = 0;
        auto hash = field.rfind('#');
        if (hash == std::string::npos || hash + 1 == field.size()) {
            return;
        }
        try {
            std::size_t used = 0;
            long id = std::stol(field.substr(hash + 1), &used);
            if (used == field.size() - hash - 1 && id != 0) {
                target = field.substr(0, hash);
                targetId = id > 0 ? id : -1;
            }
        }
        catch (...) {
        }
    }

    void setTarget(const App::DocumentObject* obj)
    {
        target = obj->getNameInDocument();
        targetId = obj->getID();
    }

    static std::optional<ParkedItem> parse(const std::string& line)
    {
        std::vector<std::string> fields;
        std::size_t start = 0;
        while (true) {
            auto bar = line.find('|', start);
            fields.push_back(unescapeField(line.substr(start, bar - start)));
            if (bar == std::string::npos) {
                break;
            }
            start = bar + 1;
        }
        ParkedItem item;
        if (fields.size() == 4 && fields[0] == "expr") {
            item.expression = true;
            item.property = fields[1];
            item.setTarget(fields[2]);
            item.text = fields[3];
            return item;
        }
        // A projection's line has two fields more before the guess fields
        const std::size_t base = fields[0] == "extgeo" ? 10 : 8;
        if ((fields[0] == "link" || fields[0] == "extgeo")
            && (fields.size() == base || fields.size() == base + 3
                || fields.size() == base + 4)) {
            item.extgeo = fields[0] == "extgeo";
            item.property = fields[1];
            item.setTarget(fields[2]);
            item.sub = fields[3];
            item.shadowNew = fields[4];
            item.shadowOld = fields[5];
            item.fp = fields[6];
            try {
                item.position = static_cast<std::size_t>(std::stoul(fields[7]));
            }
            catch (...) {
                item.position = 0;
            }
            if (item.extgeo) {
                try {
                    item.type = std::stoi(fields[8]);
                    std::size_t start = 0;
                    while (start < fields[9].size()) {
                        auto comma = fields[9].find(',', start);
                        item.ids.push_back(std::stol(fields[9].substr(start, comma - start)));
                        start = comma == std::string::npos ? fields[9].size() : comma + 1;
                    }
                }
                catch (...) {
                    return {};
                }
            }
            if (fields.size() >= base + 3) {
                item.guess = App::GuessRecord::fromAttributes(
                    fields[base],
                    fields[base + 1],
                    fields[base + 2],
                    fields.size() == base + 4 ? fields[base + 3] : std::string()
                );
            }
            return item;
        }
        return {};
    }
};

/// The key a parked projection's geometries had: `<object>.<mapped name>`, as the Sketcher builds
/// it from the link (SketchObject::updateGeometryRefs)
std::string projectionKey(const ParkedItem& item)
{
    const std::string& sub = item.shadowNew.empty() ? item.sub : item.shadowNew;
    return item.target + "." + Data::newElementName(sub.c_str());
}

/// The element a parked item referred to, as the user knows it (`Edge3`)
std::string parkedElement(const ParkedItem& item)
{
    std::string element = Data::oldElementName(item.sub.c_str());
    if (Data::hasMissingElement(element.c_str())) {
        element.erase(0, std::strlen(Data::MISSING_PREFIX));
    }
    return element;
}

std::vector<std::string> parkedLines(const App::DocumentObject* owner)
{
    auto prop = freecad_cast<App::PropertyStringList*>(owner->getPropertyByName(ParkedProperty));
    return prop ? prop->getValues() : std::vector<std::string>();
}

void writeParkedLines(App::DocumentObject* owner, const std::vector<std::string>& lines)
{
    auto prop = freecad_cast<App::PropertyStringList*>(owner->getPropertyByName(ParkedProperty));
    if (lines.empty()) {
        if (prop) {
            owner->removeDynamicProperty(ParkedProperty);
        }
        return;
    }
    if (!prop) {
        prop = freecad_cast<App::PropertyStringList*>(owner->addDynamicProperty(
            "App::PropertyStringList",
            ParkedProperty,
            "Base",
            "References a reorder set aside because they now point below this object "
            "(FreeCAD-CH ops#127); put back when the order allows",
            App::Prop_Hidden));
    }
    if (prop) {
        prop->setValues(lines);
    }
}

/// The object a parked item refers to: the one of that name, if it is the same object
/// (ops#158: a new object can take a deleted one's name); null when it was deleted, or left in
/// another document
App::DocumentObject* parkedTarget(const App::Document* doc, const ParkedItem& item)
{
    auto obj = doc ? doc->getObject(item.target.c_str()) : nullptr;
    if (obj && item.targetId != 0 && obj->getID() != item.targetId) {
        return nullptr;
    }
    return obj;
}

// -- A link property as the rule sees it ---------------------------------------------------------

enum class Kind
{
    Link,
    LinkList,
    LinkSub,
    LinkSubList,
    External,  // a sketch's ExternalGeometry (a PropertyLinkSubList with keyed projections)
    XLink,
    XLinkSubList
};

/// One element reference
struct SubEntry
{
    std::string sub;
    ShadowSub shadow;
    std::string fp;
    App::RetargetRecord record;
    App::GuessRecord guess;  // the solver's (ops#127, P5)
};

/// One object with its references: a PropertyLink(Sub), a PropertyXLink, one link of a
/// PropertyXLinkSubList, or one entry of a list. No subs: the whole object.
struct Unit
{
    App::DocumentObject* obj = nullptr;
    std::vector<SubEntry> subs;
    int origin = -1;       // its position in the property as read; -1: put back from parking
    bool frozen = false;   // a form the rule doesn't write (sub-object paths, mixed subs)
    bool edited = false;
    bool dropped = false;  // parked, or a duplicate of a restored or re-targeted piece
    // A sketch's projection (ops#131): the Ids of its geometries in projection order, and its type
    std::vector<long> ids;
    int type = 0;

    /// Every sub carries a re-target record to the same object
    bool allRecorded() const
    {
        if (subs.empty()) {
            return false;
        }
        for (const auto& s : subs) {
            if (s.record.empty() || s.record.target != subs.front().record.target) {
                return false;
            }
        }
        return true;
    }
};

struct PropertyState
{
    App::DocumentObject* owner = nullptr;
    App::PropertyLinkBase* prop = nullptr;
    Kind kind = Kind::Link;
    std::vector<Unit> units;
    Objects removed;                  // PropertyXLinkSubList: the objects of parked links
    std::set<App::DocumentObject*> solveOn;
    bool changed = false;

    Objects targets() const
    {
        Objects out;
        for (const auto& u : units) {
            if (!u.dropped && u.obj) {
                out.push_back(u.obj);
            }
        }
        return out;
    }
};

/// The subs of a single-object property (PropertyLinkSub, PropertyXLink) as one unit
template<class P>
Unit unitOf(const P& prop, App::DocumentObject* obj)
{
    Unit unit;
    unit.obj = obj;
    const auto& subs = prop.getSubValues();
    const auto& shadows = prop.getShadowSubs();
    auto fps = prop.getElementFingerprints();
    auto records = prop.getElementRecords();
    bool anyEmpty = false;
    for (std::size_t i = 0; i < subs.size(); ++i) {
        if (subs[i].empty()) {
            anyEmpty = true;
            continue;
        }
        if (Data::findElementName(subs[i].c_str()) != subs[i].c_str()) {
            unit.frozen = true;  // a sub-object path: not the rule's form (as the relink, F.cpp)
        }
        SubEntry entry;
        entry.sub = subs[i];
        entry.shadow = i < shadows.size() ? shadows[i] : ShadowSub();
        entry.fp = i < fps.size() ? fps[i] : std::string();
        if (i < records.size()) {
            entry.record = records[i].retarget;
            entry.guess = records[i].guess;
        }
        unit.subs.push_back(std::move(entry));
    }
    if (anyEmpty && !unit.subs.empty()) {
        unit.frozen = true;
    }
    return unit;
}

/// The entries of a PropertyLinkSubList, one unit each
void readList(const App::PropertyLinkSubList& prop, std::vector<Unit>& units)
{
    const auto& objs = prop.getValues();
    const auto& subs = prop.getSubValues();
    const auto& shadows = prop.getShadowSubs();
    auto fps = prop.getElementFingerprints();
    auto records = prop.getElementRecords();
    for (std::size_t i = 0; i < objs.size(); ++i) {
        Unit unit;
        unit.obj = objs[i];
        unit.origin = static_cast<int>(i);
        const std::string& sub = i < subs.size() ? subs[i] : std::string();
        if (!sub.empty()) {
            if (Data::findElementName(sub.c_str()) != sub.c_str()) {
                unit.frozen = true;
            }
            SubEntry entry;
            entry.sub = sub;
            entry.shadow = i < shadows.size() ? shadows[i] : ShadowSub();
            entry.fp = i < fps.size() ? fps[i] : std::string();
            if (i < records.size()) {
                entry.record = records[i].retarget;
                entry.guess = records[i].guess;
            }
            unit.subs.push_back(std::move(entry));
        }
        units.push_back(std::move(unit));
    }
}

std::optional<PropertyState> readState(App::DocumentObject* owner, App::Property* p)
{
    PropertyState state;
    state.owner = owner;
    state.prop = freecad_cast<App::PropertyLinkBase*>(p);
    if (!state.prop) {
        return {};
    }
    auto sketch = freecad_cast<Sketcher::SketchObject*>(owner);
    if (sketch && p == &sketch->ExternalGeometry) {
        state.kind = Kind::External;
        readList(sketch->ExternalGeometry, state.units);
        for (auto& unit : state.units) {
            unit.ids = sketch->externalGeometryIds(unit.origin);
            unit.type = sketch->externalType(unit.origin);
        }
    }
    else if (auto xlist = freecad_cast<App::PropertyXLinkSubList*>(p)) {
        state.kind = Kind::XLinkSubList;
        int index = 0;
        for (const auto& link : xlist->getSubListValues()) {
            Unit unit = unitOf(link, link.getValue());
            unit.origin = index++;
            if (!unit.obj) {
                unit.frozen = true;  // a link into a document that isn't open
            }
            state.units.push_back(std::move(unit));
        }
    }
    else if (auto xlink = freecad_cast<App::PropertyXLink*>(p)) {
        state.kind = Kind::XLink;
        if (xlink->getValue()) {
            Unit unit = unitOf(*xlink, xlink->getValue());
            unit.origin = 0;
            state.units.push_back(std::move(unit));
        }
    }
    else if (auto list = freecad_cast<App::PropertyLinkSubList*>(p)) {
        state.kind = Kind::LinkSubList;
        readList(*list, state.units);
    }
    else if (auto linkSub = freecad_cast<App::PropertyLinkSub*>(p)) {
        state.kind = Kind::LinkSub;
        if (linkSub->getValue()) {
            Unit unit = unitOf(*linkSub, linkSub->getValue());
            unit.origin = 0;
            state.units.push_back(std::move(unit));
        }
    }
    else if (auto linkList = freecad_cast<App::PropertyLinkList*>(p)) {
        state.kind = Kind::LinkList;
        int index = 0;
        for (auto obj : linkList->getValues()) {
            Unit unit;
            unit.obj = obj;
            unit.origin = index++;
            state.units.push_back(std::move(unit));
        }
    }
    else if (auto link = freecad_cast<App::PropertyLink*>(p)) {
        state.kind = Kind::Link;
        if (link->getValue()) {
            Unit unit;
            unit.obj = link->getValue();
            unit.origin = 0;
            state.units.push_back(std::move(unit));
        }
    }
    else {
        return {};
    }
    return state;
}

/// The index name of an element reference, without the missing marker (`?Face6` -> `Face6`)
std::string indexOf(const SubEntry& entry)
{
    const std::string& name = entry.shadow.oldName.empty() ? entry.sub : entry.shadow.oldName;
    const char* element = Data::findElementName(name.c_str());
    std::string index = element ? element : "";
    if (Data::hasMissingElement(index.c_str())) {
        index.erase(0, std::strlen(Data::MISSING_PREFIX));
    }
    if (index.empty()) {
        index = entry.sub;
        if (Data::hasMissingElement(index.c_str())) {
            index.erase(0, std::strlen(Data::MISSING_PREFIX));
        }
    }
    return index;
}

/// The reference in the missing form a relink writes (`?Face6` with its mapped name in the
/// shadow), found again by name or by the solver on its new object. Without a mapped name: on
/// its own object (a restore) the index alone; on another one the index-only missing form, which
/// nothing resolves (an index never carries over from one shape to another)
SubEntry missingForm(const std::string& mapped,
                     const std::string& index,
                     const std::string& fp,
                     bool ownObject)
{
    SubEntry entry;
    entry.fp = fp;
    if (mapped.empty()) {
        entry.sub = ownObject ? index : Data::MISSING_PREFIX + index;
        if (!ownObject) {
            entry.shadow = ShadowSub(std::string(), entry.sub);
        }
        return entry;
    }
    entry.sub = Data::MISSING_PREFIX + index;
    entry.shadow = ShadowSub(Data::ComplexGeoData::elementMapPrefix() + mapped + "." + index,
                             entry.sub);
    return entry;
}

/// The original a re-target record keeps, as the reference to put back on its object, with the
/// guess record it had (N1 3.2: the elements the user rejected stay rejected)
SubEntry originalOf(const App::RetargetRecord& record)
{
    SubEntry entry = missingForm(record.origName, record.origIndex, record.origFp, true);
    entry.guess = record.guess;
    return entry;
}

/// The re-target record for an entry the rule moves off obj (N1 3.2: its saved original)
App::RetargetRecord recordFor(const SubEntry& entry, App::DocumentObject* obj)
{
    if (!entry.record.empty()) {
        return entry.record;  // moved again: the original stays the first object's element
    }
    App::RetargetRecord record;
    record.target = obj->getNameInDocument();
    record.guess = entry.guess;
    if (!entry.guess.empty()
        && (!entry.guess.origName.empty() || !entry.guess.origIndex.empty())) {
        // A provisional pick (P5): the original is the record's, not the picked element, since
        // the original's name is the one most likely to exist on the earlier object; it has no
        // fingerprint of its own (the reference's is the pick's)
        record.origName = entry.guess.origName;
        record.origIndex = entry.guess.origIndex;
        return record;
    }
    record.origIndex = indexOf(entry);
    record.origName = App::bareMappedName(entry.shadow.newName);
    if (record.origName.empty()) {
        if (auto feature = freecad_cast<Part::Feature*>(obj)) {
            auto element = feature->Shape.getShape().getElementName(record.origIndex.c_str());
            if (element.name) {
                record.origName = element.name.toString();
            }
        }
    }
    record.origFp = entry.fp;
    return record;
}

std::string recordKey(const App::RetargetRecord& record)
{
    return record.target + "|" + record.origText();
}

// -- The rule (N1 3.1-3.4) ------------------------------------------------------------------------

class Rule
{
public:
    Rule(Body& body,
         const Objects& group,
         const std::map<App::DocumentObject*, App::DocumentObject*>& newBase)
        : body(body)
        , group(group)
        , newBase(newBase)
    {
        for (auto obj : group) {
            members.insert(obj);
            if (Body::isSolidFeature(obj)) {
                chainPos[obj] = solids.size();
                solids.push_back(obj);
            }
        }
        computeEarliest();
    }

    /// Decides every re-target, park and restore on the planned order; writes nothing. Throws
    /// Base::ValueError for a case it can't break (a sketch's projection with nowhere to go).
    void plan()
    {
        for (auto owner : group) {
            planLinks(owner);
        }
        for (auto owner : group) {
            planExpressions(owner);
        }
        // Everything apply() writes must succeed, so a refusal stays write-free (S2): a sketch's
        // projections must be in step with its entries (as the Sketcher itself requires), and the
        // parking record goes into a ParkedReferences string list, which nothing else may hold
        for (const auto& [key, state] : states) {
            if (state.kind != Kind::External || !state.changed) {
                continue;
            }
            auto sketch = static_cast<const Sketcher::SketchObject*>(state.owner);
            if (!sketch->canRetargetExternalGeometry()) {
                std::ostringstream text;
                text << "'" << nameOf(sketch)
                     << "' has external geometry out of step with its projections: recompute it "
                        "first";
                throw Base::ValueError(text.str());
            }
        }
        for (const auto& [owner, ownerPlan] : owners) {
            if (!ownerPlan.linesChanged && ownerPlan.restoreExprs.empty()) {
                continue;  // its record isn't written
            }
            auto prop = owner->getPropertyByName(ParkedProperty);
            if (prop && !prop->isDerivedFrom<App::PropertyStringList>()) {
                std::ostringstream text;
                text << "'" << nameOf(owner) << "' has a property '" << ParkedProperty
                     << "' that can't hold the references a reorder sets aside";
                throw Base::ValueError(text.str());
            }
        }
    }

    /// The planned objects of owner's property prop; false if the rule leaves it as it is
    bool plannedTargets(const App::DocumentObject* owner, const App::Property* prop, Objects& out)
        const
    {
        auto it = states.find({owner, prop});
        if (it == states.end()) {
            return false;
        }
        out = it->second.targets();
        return true;
    }

    /// The planned objects owner's expressions read; false if the rule leaves them as they are
    bool plannedExpressionTargets(const App::DocumentObject* owner, Objects& out) const
    {
        auto it = owners.find(owner);
        if (it == owners.end()
            || (it->second.parkPaths.empty() && it->second.restoreExprs.empty())) {
            return false;
        }
        for (const auto& [path, expr] : owner->ExpressionEngine.getExpressions()) {
            if (it->second.parkPaths.count(path.toString())) {
                continue;
            }
            for (const auto& dep : expr->getDepObjects()) {
                out.push_back(dep.first);
            }
        }
        for (const auto& restored : it->second.restoreExprs) {
            out.push_back(restored.target);
        }
        return true;
    }

    /// Writes the plan: the links, the expressions, the parking records; then the moved
    /// references are found on their new objects (the solver, or the name without it)
    void apply()
    {
        std::vector<PropertyState*> written;
        for (auto owner : group) {
            for (auto& [key, state] : states) {
                if (key.first == owner) {
                    write(state);
                    written.push_back(&state);
                }
            }
        }
        for (auto owner : group) {
            auto it = owners.find(owner);
            if (it == owners.end()) {
                continue;
            }
            auto& plan = it->second;
            for (const auto& path : plan.parkPaths) {
                owner->ExpressionEngine.setValue(App::ObjectIdentifier::parse(owner, path),
                                                 nullptr);
            }
            for (const auto& restored : plan.restoreExprs) {
                try {
                    std::shared_ptr<App::Expression> expr(
                        App::Expression::parse(owner, restored.item.text));
                    owner->ExpressionEngine.setValue(
                        App::ObjectIdentifier::parse(owner, restored.item.property), expr);
                }
                catch (Base::Exception& e) {
                    // Kept parked: the owner keeps failing with the message
                    FC_ERR(owner->getFullName() << ": the expression of '"
                                                << restored.item.property
                                                << "' can't be put back: " << e.what());
                    plan.lines.push_back(restored.item.line());
                    plan.linesChanged = true;
                }
            }
            if (plan.linesChanged) {
                writeParkedLines(owner, plan.lines);
            }
            if (auto sketch = freecad_cast<Sketcher::SketchObject*>(owner)) {
                for (const auto& item : plan.missingProjections) {
                    sketch->markExternalGeometryMissing(item.ids, projectionKey(item));
                }
            }
        }
        for (auto state : written) {
            for (auto target : state->solveOn) {
                solve(*state->prop, target);
            }
        }
    }

    /// The earliest solid whose inputs include obj (N1 3.1), or null
    App::DocumentObject* earliestUser(const App::DocumentObject* obj) const
    {
        auto it = earliest.find(obj);
        return it == earliest.end() ? nullptr : it->second;
    }

private:
    struct RestoredExpression
    {
        ParkedItem item;
        App::DocumentObject* target = nullptr;
    };
    struct OwnerPlan
    {
        std::vector<std::string> lines;
        bool linesChanged = false;
        std::set<std::string> parkPaths;
        std::vector<RestoredExpression> restoreExprs;
        // Parked projections whose object was deleted (ops#131): their geometries get the old
        // reference back, so the sketch shows them as missing instead of as silent fixed geometry
        std::vector<ParkedItem> missingProjections;
    };

    // -- In(X) (N1 3.1): X and the members reachable from it along input links, through no
    // solid and without leaving the Body. Independent of the rule's writes: they only change
    // links into solids.
    void computeEarliest()
    {
        for (auto solid : solids) {
            std::vector<App::DocumentObject*> stack {solid};
            std::set<App::DocumentObject*> seen {solid};
            while (!stack.empty()) {
                auto obj = stack.back();
                stack.pop_back();
                earliest.emplace(obj, solid);
                std::vector<App::Property*> props;
                obj->getPropertyList(props);
                for (auto prop : props) {
                    if (!isInputLink(obj, prop)) {
                        continue;
                    }
                    Objects links;
                    static_cast<App::PropertyLinkBase*>(prop)->getLinks(links, false);
                    for (auto next : links) {
                        if (next && next != &body && members.count(next)
                            && !Body::isSolidFeature(next) && seen.insert(next).second) {
                            stack.push_back(next);
                        }
                    }
                }
            }
        }
    }

    App::DocumentObject* plannedBase(App::DocumentObject* solid) const
    {
        auto it = newBase.find(solid);
        if (it != newBase.end()) {
            return it->second;
        }
        auto feature = freecad_cast<PartDesign::Feature*>(solid);
        return feature ? feature->BaseFeature.getValue() : nullptr;
    }

    /// target is a solid of the Body at or after x in the planned chain
    bool atOrAfter(const App::DocumentObject* target, const App::DocumentObject* x) const
    {
        auto t = chainPos.find(target);
        return t != chainPos.end() && t->second >= chainPos.at(x);
    }

    void planLinks(App::DocumentObject* owner)
    {
        auto x = earliestUser(owner);
        auto doc = owner->getDocument();
        std::vector<ParkedItem> items;
        std::vector<std::string> lines = parkedLines(owner);
        std::vector<bool> keep(lines.size(), true);
        for (const auto& line : lines) {
            auto item = ParkedItem::parse(line);
            items.push_back(item ? *item : ParkedItem());
        }
        bool linesChanged = false;
        std::vector<std::string> newLines;
        std::vector<ParkedItem> missingProjections;

        std::vector<App::Property*> props;
        owner->getPropertyList(props);
        for (auto prop : props) {
            if (!isWalked(owner, prop)) {
                continue;
            }
            auto state = readState(owner, prop);
            if (!state) {
                continue;
            }
            decide(*state, x, newLines);
            for (std::size_t i = 0; i < items.size(); ++i) {
                if (items[i].expression || items[i].property != prop->getName()) {
                    continue;
                }
                auto target = parkedTarget(doc, items[i]);
                if (target && x && atOrAfter(target, x)) {
                    continue;  // still after the feature that uses it
                }
                if (target) {
                    putBack(*state, items[i], target);
                }
                else if (items[i].extgeo) {
                    missingProjections.push_back(items[i]);
                }
                keep[i] = false;  // put back, or dropped with its object
                linesChanged = true;
            }
            if (state->changed) {
                states.emplace(std::make_pair(owner, prop), std::move(*state));
            }
        }
        if (!newLines.empty()) {
            linesChanged = true;
        }
        auto& plan = owners[owner];
        for (std::size_t i = 0; i < lines.size(); ++i) {
            if (keep[i]) {
                plan.lines.push_back(lines[i]);
            }
        }
        plan.lines.insert(plan.lines.end(), newLines.begin(), newLines.end());
        plan.linesChanged = linesChanged;
        plan.missingProjections = std::move(missingProjections);
    }

    /// One property's entries: first the restore, then the re-target or the park (N1 3.2)
    void decide(PropertyState& state, App::DocumentObject* x, std::vector<std::string>& newLines)
    {
        auto doc = state.owner->getDocument();
        // Pieces of one expanded reference: one restore or re-target. A sketch's projections keep
        // their count (their keys go by position), so each piece keeps its entry there.
        const bool list = state.kind == Kind::LinkSubList || state.kind == Kind::XLinkSubList;
        std::set<std::string> seen;
        for (auto& unit : state.units) {
            if (!unit.obj || unit.frozen) {
                continue;
            }
            // 1. The restore: the record's object is no longer after the feature that uses it
            if (unit.allRecorded()) {
                auto target = doc->getObject(unit.subs.front().record.target.c_str());
                if (!target) {
                    // Its object is gone: nothing to restore to
                    for (auto& s : unit.subs) {
                        s.record = App::RetargetRecord();
                    }
                    unit.edited = state.changed = true;
                }
                else if (chainPos.count(target) && (!x || !atOrAfter(target, x))) {
                    std::vector<SubEntry> originals;
                    std::set<std::string> keys;
                    for (const auto& s : unit.subs) {
                        if (keys.insert(recordKey(s.record)).second) {
                            originals.push_back(originalOf(s.record));
                        }
                    }
                    std::string key = recordKey(unit.subs.front().record);
                    unit.obj = target;
                    unit.subs = std::move(originals);
                    unit.edited = state.changed = true;
                    state.solveOn.insert(target);
                    if (list && !seen.insert(key).second) {
                        unit.dropped = true;
                    }
                    continue;
                }
            }
            if (!x || !atOrAfter(unit.obj, x)) {
                continue;
            }
            // 2. A reference into a solid at or after the feature that uses it: re-targeted to
            // that feature's base, or parked without one
            auto base = plannedBase(x);
            if (!unit.subs.empty() && base) {
                std::vector<SubEntry> moved;
                std::set<std::string> keys;
                std::string first;
                for (const auto& s : unit.subs) {
                    auto record = recordFor(s, unit.obj);
                    if (!keys.insert(recordKey(record)).second) {
                        continue;
                    }
                    if (first.empty()) {
                        first = recordKey(record);
                    }
                    SubEntry entry =
                        missingForm(record.origName, record.origIndex, record.origFp, false);
                    entry.record = record;
                    moved.push_back(std::move(entry));
                }
                unit.obj = base;
                unit.subs = std::move(moved);
                unit.edited = state.changed = true;
                state.solveOn.insert(base);
                if (list && !first.empty() && !seen.insert(first).second) {
                    unit.dropped = true;
                }
                continue;
            }
            // A sketch's projection with no base to take it is parked in place (ops#131): its
            // geometries and their constraints stay, only the link is set aside
            park(state, unit, newLines);
        }
    }

    void park(PropertyState& state, Unit& unit, std::vector<std::string>& newLines)
    {
        ParkedItem item;
        item.property = state.prop->getName();
        item.position = unit.origin < 0 ? 0 : static_cast<std::size_t>(unit.origin);
        if (state.kind == Kind::External) {
            item.extgeo = true;
            item.type = unit.type;
            item.ids = unit.ids;
        }
        if (unit.subs.empty()) {
            item.setTarget(unit.obj);
            newLines.push_back(item.line());
        }
        else {
            std::set<std::string> keys;
            for (const auto& s : unit.subs) {
                // A re-targeted entry parks its original, on the object it came from
                SubEntry entry = s.record.empty() ? s : originalOf(s.record);
                if (!s.record.empty() && !keys.insert(recordKey(s.record)).second) {
                    continue;
                }
                // A record's object exists here: decide() ends a record whose object is gone
                auto doc = unit.obj->getDocument();
                auto source = s.record.empty() ? unit.obj : doc->getObject(s.record.target.c_str());
                if (source) {
                    item.setTarget(source);
                }
                else {
                    item.target = s.record.target;
                    item.targetId = 0;
                }
                item.sub = entry.sub;
                item.shadowNew = entry.shadow.newName;
                item.shadowOld = entry.shadow.oldName;
                item.fp = entry.fp;
                item.guess = entry.guess;
                newLines.push_back(item.line());
            }
        }
        if (state.kind == Kind::XLinkSubList && unit.origin >= 0) {
            state.removed.push_back(unit.obj);
        }
        unit.dropped = true;
        state.changed = true;
    }

    /// Puts a parked link entry back (N1 3.4 b: appended, at its old position when it is still in
    /// range); one the property already holds, or a single link the user has set since, is dropped
    void putBack(PropertyState& state, const ParkedItem& item, App::DocumentObject* target)
    {
        Unit unit;
        unit.obj = target;
        if (!item.sub.empty()) {
            SubEntry entry;
            if (!item.shadowNew.empty()) {
                std::string index = item.sub;
                if (Data::hasMissingElement(index.c_str())) {
                    index.erase(0, std::strlen(Data::MISSING_PREFIX));
                }
                entry = missingForm(App::bareMappedName(item.shadowNew), index, item.fp, true);
            }
            else {
                entry.sub = item.sub;
                entry.fp = item.fp;
            }
            entry.guess = item.guess;
            unit.subs.push_back(std::move(entry));
            state.solveOn.insert(target);
        }
        unit.edited = true;
        if (state.kind == Kind::External) {
            // A parked projection goes back onto its geometries (ops#131). If every one of them
            // has a reference again (re-attached from Python), they have a new use: the item ends.
            unit.ids = item.ids;
            unit.type = item.type;
            auto sketch = static_cast<const Sketcher::SketchObject*>(state.owner);
            if (!item.ids.empty()
                && std::all_of(item.ids.begin(), item.ids.end(), [&](long id) {
                       auto ref = sketch->externalGeometryRefOf(id);
                       return ref && !ref->empty();
                   })) {
                return;
            }
        }
        auto live = [&]() {
            std::vector<Unit*> out;
            for (auto& u : state.units) {
                if (!u.dropped) {
                    out.push_back(&u);
                }
            }
            return out;
        };
        auto current = live();
        auto holds = [&](const Unit& u) {
            if (u.obj != target) {
                return false;
            }
            if (unit.subs.empty()) {
                return u.subs.empty();
            }
            return std::any_of(u.subs.begin(), u.subs.end(), [&](const SubEntry& s) {
                return s.sub == unit.subs.front().sub
                    || (!s.shadow.newName.empty()
                        && s.shadow.newName == unit.subs.front().shadow.newName);
            });
        };
        if (std::any_of(current.begin(), current.end(), [&](Unit* u) { return holds(*u); })) {
            if (state.kind == Kind::External) {
                // The user projected the same element again while it was parked: the new
                // projection stays, and the parked geometries keep no link (ops#131)
                auto sketch = static_cast<const Sketcher::SketchObject*>(state.owner);
                auto kept = static_cast<long>(
                    std::count_if(item.ids.begin(), item.ids.end(), [&](long id) {
                        auto ref = sketch->externalGeometryRefOf(id);
                        return ref && ref->empty();
                    }));
                Base::Console().warning(
                    "%s: the projection of '%s' %s set aside by the reorder is not put back, since "
                    "the sketch projects that element again; %ld set-aside geometr%s stay%s as "
                    "fixed geometry\n",
                    sketch->Label.getValue(), target->Label.getValue(), item.sub.c_str(), kept,
                    kept == 1 ? "y" : "ies", kept == 1 ? "s" : "");
            }
            return;
        }
        auto insertAt = [&](std::size_t position) {
            // position among the live units
            std::size_t live = 0;
            auto it = state.units.begin();
            for (; it != state.units.end(); ++it) {
                if (it->dropped) {
                    continue;
                }
                if (live == position) {
                    break;
                }
                ++live;
            }
            state.units.insert(it, std::move(unit));
            state.changed = true;
        };
        switch (state.kind) {
            case Kind::Link:
                if (current.empty()) {
                    insertAt(0);
                }
                break;
            case Kind::LinkSub:
            case Kind::XLink:
                if (current.empty()) {
                    insertAt(0);
                }
                else if (current.front()->obj == target && !unit.subs.empty()
                         && !current.front()->subs.empty()) {
                    current.front()->subs.push_back(std::move(unit.subs.front()));
                    current.front()->edited = state.changed = true;
                }
                break;
            case Kind::LinkList:
            case Kind::LinkSubList:
                insertAt(std::min(item.position, current.size()));
                break;
            case Kind::XLinkSubList: {
                auto same = std::find_if(current.begin(), current.end(), [&](Unit* u) {
                    return u->obj == target;
                });
                if (same != current.end() && !unit.subs.empty() && !(*same)->subs.empty()) {
                    (*same)->subs.push_back(std::move(unit.subs.front()));
                    (*same)->edited = state.changed = true;
                }
                else if (same == current.end()) {
                    insertAt(current.size());
                }
                break;
            }
            case Kind::External:
                // Appended: the order of the links is invisible, and the geometries keep their
                // places in any case
                insertAt(current.size());
                break;
        }
    }

    /// An expression text of owner reads an object that readsLater(x) (review S3: an expression
    /// can read more than the object it was parked for); a text that doesn't parse stays parked
    bool readsAnyLater(App::DocumentObject* owner, const std::string& text, App::DocumentObject* x)
        const
    {
        try {
            std::unique_ptr<App::Expression> expr(App::Expression::parse(owner, text));
            for (const auto& dep : expr->getDepObjects()) {
                if (dep.first != owner && readsLater(dep.first, x)) {
                    return true;
                }
            }
        }
        catch (Base::Exception&) {
            return true;
        }
        return false;
    }

    /// d is, or reaches along input links (as planned), a solid at or after x (N1 3.3, S4)
    bool readsLater(App::DocumentObject* d, App::DocumentObject* x) const
    {
        if (chainPos.count(d)) {
            return atOrAfter(d, x);
        }
        if (!members.count(d) || d == &body) {
            return false;
        }
        std::vector<App::DocumentObject*> stack {d};
        std::set<App::DocumentObject*> seen {d};
        while (!stack.empty()) {
            auto obj = stack.back();
            stack.pop_back();
            std::vector<App::Property*> props;
            obj->getPropertyList(props);
            for (auto prop : props) {
                if (!isInputLink(obj, prop)) {
                    continue;
                }
                Objects links;
                if (!plannedTargets(obj, prop, links)) {
                    static_cast<App::PropertyLinkBase*>(prop)->getLinks(links, false);
                }
                for (auto next : links) {
                    if (!next) {
                        continue;
                    }
                    if (chainPos.count(next)) {
                        if (atOrAfter(next, x)) {
                            return true;
                        }
                    }
                    else if (next != &body && members.count(next) && seen.insert(next).second) {
                        stack.push_back(next);
                    }
                }
            }
        }
        return false;
    }

    void planExpressions(App::DocumentObject* owner)
    {
        auto x = earliestUser(owner);
        auto doc = owner->getDocument();
        auto& plan = owners[owner];
        if (x) {
            for (const auto& [path, expr] : owner->ExpressionEngine.getExpressions()) {
                for (const auto& dep : expr->getDepObjects()) {
                    if (dep.first == owner || !readsLater(dep.first, x)) {
                        continue;
                    }
                    ParkedItem item;
                    item.expression = true;
                    item.property = path.toString();
                    item.setTarget(dep.first);
                    item.text = expr->toString(true);
                    plan.parkPaths.insert(item.property);
                    plan.lines.push_back(item.line());
                    plan.linesChanged = true;
                    break;
                }
            }
        }
        std::vector<std::string> kept;
        for (const auto& line : plan.lines) {
            auto item = ParkedItem::parse(line);
            if (!item || !item->expression || plan.parkPaths.count(item->property)) {
                kept.push_back(line);
                continue;
            }
            auto target = parkedTarget(doc, *item);
            if (target && x && readsLater(target, x)) {
                kept.push_back(line);
                continue;
            }
            if (target && x && readsAnyLater(owner, item->text, x)) {
                // Parked for one later object, but the text reads another that is still later
                kept.push_back(line);
                continue;
            }
            if (target) {
                plan.restoreExprs.push_back({*item, target});
            }
            plan.linesChanged = true;
        }
        plan.lines = std::move(kept);
    }

    // -- Writing ---------------------------------------------------------------------------------

    static void flatten(const std::vector<Unit>& units,
                        Objects& objs,
                        std::vector<std::string>& subs,
                        std::vector<ShadowSub>& shadows,
                        std::vector<std::string>& fps,
                        std::vector<App::ElementRecords>& records)
    {
        for (const auto& u : units) {
            if (u.dropped) {
                continue;
            }
            if (u.subs.empty()) {
                objs.push_back(u.obj);
                subs.emplace_back();
                shadows.emplace_back();
                fps.emplace_back();
                records.emplace_back();
                continue;
            }
            for (const auto& s : u.subs) {
                objs.push_back(u.obj);
                subs.push_back(s.sub);
                shadows.push_back(s.shadow);
                fps.push_back(s.fp);
                records.push_back({s.guess, s.record});
            }
        }
    }

    /// The records and fingerprints after a setter that passed the shadows on: a moved entry has
    /// no guess record (its original is in the re-target record), a restored one gets its own back
    template<class P>
    static void finish(P& prop,
                       std::vector<App::ElementRecords>&& records,
                       const std::vector<std::string>& fps)
    {
        prop.setElementRecords(std::move(records));
        for (std::size_t i = 0; i < fps.size(); ++i) {
            if (!fps[i].empty()) {
                prop.setElementFingerprint(i, fps[i]);
            }
        }
    }

    static void writeXLink(App::PropertyXLink& link, const Unit& unit)
    {
        Objects objs;
        std::vector<std::string> subs;
        std::vector<ShadowSub> shadows;
        std::vector<std::string> fps;
        std::vector<App::ElementRecords> records;
        if (unit.subs.empty()) {
            link.setValue(unit.obj, std::vector<std::string>(), std::vector<ShadowSub>());
            return;
        }
        flatten({unit}, objs, subs, shadows, fps, records);
        link.setValue(unit.obj, std::move(subs), std::move(shadows));
        finish(link, std::move(records), fps);
    }

    /// A sketch's projections: the entries as read are re-targeted in place (their count kept,
    /// so the projections follow their keys), then the parked ones are set aside with their
    /// geometries kept, then the ones put back are appended onto their geometries (ops#131)
    static void writeExternal(PropertyState& state)
    {
        auto sketch = static_cast<Sketcher::SketchObject*>(state.owner);
        std::vector<Unit> asRead;
        std::vector<int> parked;
        bool moved = false;
        for (const auto& u : state.units) {
            if (u.origin < 0) {
                continue;
            }
            asRead.push_back(u);
            asRead.back().dropped = false;  // parked units are as read
            if (u.dropped) {
                parked.push_back(u.origin);
            }
            else if (u.edited) {
                moved = true;
            }
        }
        std::sort(asRead.begin(), asRead.end(), [](const Unit& a, const Unit& b) {
            return a.origin < b.origin;
        });
        if (moved) {
            Objects objs;
            std::vector<std::string> subs;
            std::vector<ShadowSub> shadows;
            std::vector<std::string> fps;
            std::vector<App::ElementRecords> records;
            flatten(asRead, objs, subs, shadows, fps, records);
            sketch->retargetExternalGeometry(objs, subs, std::move(shadows));
        }
        if (!parked.empty()) {
            sketch->parkExternalGeometry(parked);
        }
        std::vector<Unit> written;
        for (const auto& u : asRead) {
            if (std::find(parked.begin(), parked.end(), u.origin) == parked.end()) {
                written.push_back(u);
            }
        }
        for (const auto& u : state.units) {
            if (u.origin >= 0 || u.dropped || u.subs.empty()) {
                continue;
            }
            ShadowSub shadow = u.subs.front().shadow;
            int replaced =
                sketch->unparkExternalGeometry(u.obj, u.subs.front().sub, std::move(shadow), u.type,
                                               u.ids);
            if (replaced > 0) {
                Base::Console().warning(
                    "%s: %d geometr%s projected from '%s' had been deleted while the projection "
                    "was set aside; the projection gives new geometry there, without the deleted "
                    "constraints\n",
                    sketch->Label.getValue(), replaced, replaced == 1 ? "y" : "ies",
                    u.obj->Label.getValue());
            }
            written.push_back(u);
        }
        Objects objs;
        std::vector<std::string> subs;
        std::vector<ShadowSub> shadows;
        std::vector<std::string> fps;
        std::vector<App::ElementRecords> records;
        flatten(written, objs, subs, shadows, fps, records);
        finish(sketch->ExternalGeometry, std::move(records), fps);
    }

    void write(PropertyState& state)
    {
        Objects objs;
        std::vector<std::string> subs;
        std::vector<ShadowSub> shadows;
        std::vector<std::string> fps;
        std::vector<App::ElementRecords> records;
        std::vector<const Unit*> live;
        for (const auto& u : state.units) {
            if (!u.dropped) {
                live.push_back(&u);
            }
        }
        switch (state.kind) {
            case Kind::Link:
                static_cast<App::PropertyLink*>(state.prop)
                    ->setValue(live.empty() ? nullptr : live.front()->obj);
                break;
            case Kind::LinkList: {
                for (auto u : live) {
                    objs.push_back(u->obj);
                }
                static_cast<App::PropertyLinkList*>(state.prop)->setValues(objs);
                break;
            }
            case Kind::LinkSub: {
                auto& prop = *static_cast<App::PropertyLinkSub*>(state.prop);
                if (live.empty()) {
                    prop.setValue(nullptr);
                    break;
                }
                flatten(state.units, objs, subs, shadows, fps, records);
                prop.setValue(live.front()->obj, std::move(subs), std::move(shadows));
                finish(prop, std::move(records), fps);
                break;
            }
            case Kind::LinkSubList: {
                auto& prop = *static_cast<App::PropertyLinkSubList*>(state.prop);
                flatten(state.units, objs, subs, shadows, fps, records);
                prop.setValues(std::move(objs), std::move(subs), std::move(shadows));
                finish(prop, std::move(records), fps);
                break;
            }
            case Kind::External:
                writeExternal(state);
                break;
            case Kind::XLink: {
                auto& prop = *static_cast<App::PropertyXLink*>(state.prop);
                if (live.empty()) {
                    prop.setValue(nullptr);
                    break;
                }
                writeXLink(prop, *live.front());
                break;
            }
            case Kind::XLinkSubList: {
                auto& prop = *static_cast<App::PropertyXLinkSubList*>(state.prop);
                // In place first (positions as read), then the parked links go, then the links
                // put back are added
                for (const auto& u : state.units) {
                    if (!u.dropped && u.origin >= 0 && u.edited) {
                        prop.editLink(static_cast<std::size_t>(u.origin),
                                      [&u](App::PropertyXLinkSub& link) { writeXLink(link, u); });
                    }
                }
                for (auto obj : state.removed) {
                    prop.removeValue(obj);
                }
                for (const auto& u : state.units) {
                    if (u.dropped || u.origin >= 0) {
                        continue;
                    }
                    prop.addValue(u.obj, std::vector<std::string>());
                    const auto& links = prop.getSubListValues();
                    std::size_t index = 0;
                    std::size_t found = links.size();
                    for (const auto& link : links) {
                        if (link.getValue() == u.obj) {
                            found = index;
                        }
                        ++index;
                    }
                    if (found < links.size() && !u.subs.empty()) {
                        prop.editLink(found,
                                      [&u](App::PropertyXLinkSub& link) { writeXLink(link, u); });
                    }
                }
                break;
            }
        }
    }

    /// The moved references found on their new object: the solver in a solver document (once
    /// the object has a shape; its first shape solves them otherwise), the name without it
    static void solve(App::PropertyLinkBase& prop, App::DocumentObject* target)
    {
        try {
            if (prop.inSolverDocument()) {
                auto feature = freecad_cast<Part::Feature*>(target);
                if (feature && !feature->Shape.getShape().isNull()) {
                    App::solveElementReferences(target, {&prop}, false, true);
                }
            }
            else {
                prop.updateElementReference(target, false, true);
            }
        }
        catch (Base::Exception& e) {
            FC_ERR(prop.getFullName() << ": " << e.what());
        }
    }

    Body& body;
    const Objects& group;
    const std::map<App::DocumentObject*, App::DocumentObject*>& newBase;
    std::set<App::DocumentObject*> members;
    Objects solids;
    std::map<const App::DocumentObject*, std::size_t> chainPos;
    std::map<const App::DocumentObject*, App::DocumentObject*> earliest;
    std::map<std::pair<const App::DocumentObject*, const App::Property*>, PropertyState> states;
    std::map<const App::DocumentObject*, OwnerPlan> owners;
};

/// The planned state of a reorder: the new Group and each solid's new base
struct Plan
{
    Body& body;
    Objects group;
    Objects moved;
    std::map<App::DocumentObject*, App::DocumentObject*> newBase;  // solid -> its planned base
    std::vector<std::pair<App::DocumentObject*, App::DocumentObject*>> changes;  // (solid, base)
    const Rule* rule = nullptr;

    explicit Plan(Body& b)
        : body(b)
    {}

    /// The planned out-edges of obj: its links, with the base-following links of a solid on its
    /// planned base and the rule's writes (the Body itself and hidden links left out)
    Objects outEdges(App::DocumentObject* obj) const
    {
        Objects out;
        std::vector<App::Property*> props;
        obj->getPropertyList(props);
        auto planned = newBase.find(obj);
        bool rebased = false;
        for (auto prop : props) {
            auto link = freecad_cast<App::PropertyLinkBase*>(prop);
            if (!link || link->getScope() == App::LinkScope::Hidden) {
                continue;
            }
            if (planned != newBase.end() && followsBase(obj, prop)) {
                rebased = true;
                continue;
            }
            Objects objs;
            if (rule
                && (prop == &obj->ExpressionEngine ? rule->plannedExpressionTargets(obj, objs)
                                                   : rule->plannedTargets(obj, prop, objs))) {
                // the rule's re-targets, parks and restores (N1 3.5)
            }
            else {
                link->getLinks(objs, false);
            }
            for (auto o : objs) {
                if (o && o != &body) {
                    out.push_back(o);
                }
            }
        }
        if (rebased && planned->second) {
            out.push_back(planned->second);
        }
        return out;
    }

    /// A dependency cycle in the planned graph, as the objects along it; empty if none. The
    /// search covers the Body's members and the objects outside it that they reach.
    Objects findCycle() const
    {
        std::map<App::DocumentObject*, int> state;  // 1 on the path, 2 done
        Objects path;
        Objects cycle;
        std::function<bool(App::DocumentObject*)> visit = [&](App::DocumentObject* obj) {
            state[obj] = 1;
            path.push_back(obj);
            for (auto next : outEdges(obj)) {
                if (!next->isAttachedToDocument()) {
                    continue;
                }
                auto it = state.find(next);
                if (it != state.end() && it->second == 1) {
                    auto start = std::find(path.begin(), path.end(), next);
                    cycle.assign(start, path.end());
                    cycle.push_back(next);
                    return true;
                }
                if (it == state.end() && visit(next)) {
                    return true;
                }
            }
            path.pop_back();
            state[obj] = 2;
            return false;
        };
        for (auto obj : group) {
            if (!state.count(obj) && visit(obj)) {
                return cycle;
            }
        }
        return {};
    }
};

}  // namespace

void reorderBody(Body& body,
                 const std::vector<App::DocumentObject*>& objs,
                 App::DocumentObject* target,
                 bool after,
                 const RerouteBase& reroute)
{
    const Objects group = body.Group.getValues();
    auto position = [&](const App::DocumentObject* obj) {
        return static_cast<std::size_t>(std::find(group.begin(), group.end(), obj) - group.begin());
    };

    // 1. Checks: nothing is changed before they pass
    if (objs.empty()) {
        return;
    }
    std::set<App::DocumentObject*> requested;
    for (auto obj : objs) {
        if (!obj || !body.hasObject(obj)) {
            throw Base::ValueError("Body: only members of this body can be moved in it");
        }
        if (isFeatureBase(obj)) {
            throw Base::ValueError("The base feature can't be moved");
        }
        requested.insert(obj);
    }
    if (target && !body.hasObject(target)) {
        throw Base::ValueError("Body: the target of a move must be a member of this body");
    }
    if (target && requested.count(target)) {
        throw Base::ValueError("Body: an object can't be moved next to itself");
    }
    bool hasBase = !group.empty() && isFeatureBase(group.front());
    if (hasBase && target == group.front() && !after) {
        throw Base::ValueError("Nothing can go before the base feature");
    }

    // 2. Carried inputs: the non-solid members before a moved solid, up to the previous solid,
    // that only it (or another carried member) uses
    std::set<App::DocumentObject*> movedSet(requested);
    for (auto obj : objs) {
        if (!Body::isSolidFeature(obj)) {
            continue;
        }
        std::size_t pos = position(obj);
        // Until nothing more is carried: a member can sit after the member that uses it (a datum
        // after its sketch), so one backward pass misses it (review M3)
        for (bool grew = true; grew;) {
            grew = false;
            for (std::size_t i = pos; i-- > 0;) {
                auto member = group[i];
                if (Body::isSolidFeature(member)) {
                    break;
                }
                if (member == target || movedSet.count(member)) {
                    continue;
                }
                bool onlyMoved = true;
                bool used = false;
                for (auto user : member->getInList()) {
                    if (user == &body || !body.hasObject(user)) {
                        continue;
                    }
                    used = true;
                    if (!movedSet.count(user)) {
                        onlyMoved = false;
                        break;
                    }
                }
                if (used && onlyMoved) {
                    movedSet.insert(member);
                    grew = true;
                }
            }
        }
    }

    // 3. The new Group: the moved objects in their order, at the target
    Plan plan(body);
    for (auto obj : group) {
        if (movedSet.count(obj)) {
            plan.moved.push_back(obj);
        }
        else {
            plan.group.push_back(obj);
        }
    }
    std::size_t insertAt = 0;
    if (target) {
        auto it = std::find(plan.group.begin(), plan.group.end(), target);
        insertAt = static_cast<std::size_t>(it - plan.group.begin()) + (after ? 1 : 0);
    }
    else {
        insertAt = after ? 0 : plan.group.size();
    }
    if (hasBase && insertAt == 0) {
        insertAt = 1;  // the start is after the base feature
    }
    plan.group.insert(plan.group.begin() + static_cast<std::ptrdiff_t>(insertAt),
                      plan.moved.begin(),
                      plan.moved.end());

    // 4. The new chain: each solid's base is the solid before it (the base feature keeps its own)
    App::DocumentObject* previous = nullptr;
    for (auto obj : plan.group) {
        if (!Body::isSolidFeature(obj)) {
            continue;
        }
        if (!isFeatureBase(obj)) {
            plan.newBase[obj] = previous;
            auto feature = static_cast<PartDesign::Feature*>(obj);
            if (feature->BaseFeature.getValue() != previous) {
                plan.changes.emplace_back(obj, previous);
            }
        }
        previous = obj;
    }
    // Only the solids whose base changes are re-planned in the graph
    for (auto it = plan.newBase.begin(); it != plan.newBase.end();) {
        auto feature = static_cast<PartDesign::Feature*>(it->first);
        if (feature->BaseFeature.getValue() == it->second) {
            it = plan.newBase.erase(it);
        }
        else {
            ++it;
        }
    }

    // 5. The re-target rule on the planned order (N1 3.2-3.4), and the cycle check on the planned
    // graph with its writes (N1 3.5): a refusal writes nothing
    Rule rule(body, plan.group, plan.newBase);
    rule.plan();
    plan.rule = &rule;
    auto cycle = plan.findCycle();
    if (!cycle.empty()) {
        std::ostringstream text;
        text << "This order makes a dependency cycle: ";
        for (std::size_t i = 0; i < cycle.size(); ++i) {
            text << (i ? " -> " : "") << nameOf(cycle[i]);
        }
        throw Base::ValueError(text.str());
    }

    // The Tip (step 7 of N1 2.1) is decided on the old order. A Body that isn't rolled back stays
    // so: the bar stays at the end, also when a feature is dropped below the last solid (which
    // would otherwise be held)
    App::DocumentObject* tip = body.Tip.getValue();
    App::DocumentObject* newTip = tip;
    const bool atEnd = !body.isRolledBack();
    if (tip && movedSet.count(tip) && !atEnd) {
        // Rolled back and the Tip moved: the last unmoved solid before it
        newTip = nullptr;
        for (std::size_t i = position(tip); i-- > 0;) {
            if (Body::isSolidFeature(group[i]) && !movedSet.count(group[i])) {
                newTip = group[i];
                break;
            }
        }
        if (!newTip && hasBase) {
            newTip = group.front();
        }
    }

    // 6. Write: Group once, then each changed base in the new chain order (the reroute of N1
    // 2.2), then the rule's re-targets, parks and restores
    body.Group.setValues(plan.group);
    for (const auto& [feature, base] : plan.changes) {
        reroute(feature, base);
    }
    rule.apply();

    // 7. The Tip keeps its place in the list
    if (atEnd) {
        body.rollToEnd();
    }
    else if (body.Tip.getValue() != newTip) {
        body.Tip.setValue(newTip);
    }
}

bool parkedReason(const App::DocumentObject* obj, std::string& why)
{
    auto lines = parkedLines(obj);
    if (lines.empty()) {
        return false;
    }
    auto doc = obj->getDocument();
    auto item = ParkedItem::parse(lines.front());
    if (!item || !doc) {
        why = "A reference was set aside by a reorder";
        return true;
    }
    auto target = parkedTarget(doc, *item);
    std::string targetLabel = target ? target->Label.getValue() : item->target;
    // The feature it now comes after: the earliest solid whose inputs include obj
    std::string userLabel;
    if (auto body = Body::findBodyOf(obj)) {
        Objects group = body->Group.getValues();
        std::map<App::DocumentObject*, App::DocumentObject*> none;
        Rule rule(*body, group, none);
        if (auto user = rule.earliestUser(obj)) {
            userLabel = user->Label.getValue();
        }
    }
    std::ostringstream ss;
    if (item->extgeo) {
        // A projection parked in place (ops#131)
        std::string element = parkedElement(*item);
        ss << item->property << " projects '" << targetLabel << "'";
        if (!element.empty()) {
            ss << " (" << element << ")";
        }
        if (!target) {
            ss << ", which was deleted: the projection is kept as fixed geometry until the next "
                  "reorder of the Body marks it missing";
        }
        else if (!userLabel.empty()) {
            ss << ", which now comes after '" << userLabel
               << "': the projection is kept as fixed geometry until '" << userLabel
               << "' is moved below '" << targetLabel << "'";
        }
        else {
            ss << ", which a reorder put after it: the projection is kept as fixed geometry";
        }
        if (lines.size() > 1) {
            ss << " (and " << lines.size() - 1 << " more set aside)";
        }
        why = ss.str();
        return true;
    }
    if (item->expression) {
        ss << "the expression of '" << item->property << "' reads '" << targetLabel << "'";
    }
    else {
        ss << item->property << " refers to '" << targetLabel << "'";
    }
    if (!userLabel.empty()) {
        ss << ", which now comes after '" << userLabel << "'";
    }
    else {
        ss << ", which a reorder put after it";
    }
    if (lines.size() > 1) {
        ss << " (and " << lines.size() - 1 << " more set aside)";
    }
    why = ss.str();
    return true;
}

bool hasParkedOriginals(const App::DocumentObject* obj)
{
    for (const auto& line : parkedLines(obj)) {
        auto item = ParkedItem::parse(line);
        if (item && !item->expression && item->property == "Originals") {
            return true;
        }
    }
    return false;
}

namespace
{

/// Import, merge and paste (ops#158): readObjects gives the imported objects new IDs and, where a
/// name is taken, new names, so an imported owner's lines would name an object that is gone, or
/// another one. Each line whose object came in with it (the object saved under that name with that
/// ID) is rewritten to name the copy (and to put the reference back by its index), and so are the
/// objects an expression's text names. A line whose object didn't come in keeps naming it: in a
/// copy within the document it is still there, under its name and ID; from anywhere else it is
/// in another document, and an object of that name here is another one, whatever its ID.
void importParkedLines(const std::vector<App::DocumentObject*>& objs, Base::XMLReader& /*reader*/)
{
    // The imported objects by the name each was saved under, with the ID it had there
    std::map<std::string, std::pair<App::DocumentObject*, long>> saved;
    for (auto obj : objs) {
        if (auto source = App::importedSource(obj)) {
            saved[source->name] = {obj, source->id};
        }
    }
    for (auto owner : objs) {
        auto source = App::importedSource(owner);
        if (!source || !owner->isAttachedToDocument()) {
            continue;
        }
        auto doc = owner->getDocument();
        // A copy's names end in `@<document>`, the document it was copied from (exportObjects); a
        // saved project's (merge) don't
        auto at = source->name.find('@');
        const std::string suffix = at == std::string::npos ? "" : source->name.substr(at);
        const bool sameDocument = suffix == std::string("@") + doc->getName();
        // The copy of the owner's object of that name, if it is that object (id; 0 takes any)
        auto copyOf = [&](const std::string& name, long id) -> App::DocumentObject* {
            auto it = saved.find(name + suffix);
            if (id < 0 || it == saved.end() || (id > 0 && it->second.second != id)) {
                return nullptr;
            }
            return it->second.first;
        };
        auto lines = parkedLines(owner);
        bool changed = false;
        for (auto& line : lines) {
            auto item = ParkedItem::parse(line);
            if (!item) {
                continue;
            }
            if (auto copy = copyOf(item->target, item->targetId)) {
                item->setTarget(copy);
                // The mapped name's tags are the source objects' IDs, which the copies don't
                // have: the reference goes back by its index, as an imported link's does
                item->shadowNew.clear();
            }
            else if (!sameDocument) {
                item->targetId = -1;
            }
            if (item->expression) {
                try {
                    // The objects the text names without a document resolve here: to the copies
                    // that kept their names, or to this document's objects (or the originals,
                    // within the document) where a copy was renamed. A reference into another
                    // document stays as it is. The parse doesn't rename them
                    std::unique_ptr<App::Expression> expr(
                        App::Expression::parse(owner, item->text));
                    std::vector<std::pair<App::DocumentObject*, App::DocumentObject*>> renames;
                    for (const auto& dep : expr->getDeps(App::Expression::DepAll)) {
                        auto obj = dep.first;
                        if (!obj || !obj->isAttachedToDocument() || obj->getDocument() != doc) {
                            continue;
                        }
                        auto copy = copyOf(obj->getNameInDocument(), 0);
                        if (copy && copy != obj) {
                            renames.emplace_back(obj, copy);
                        }
                    }
                    // One at a time, each before the one whose copy it renames (X001 to X002
                    // before X to X001), so that no name is renamed twice
                    while (!renames.empty()) {
                        auto next = std::find_if(renames.begin(), renames.end(), [&](auto& r) {
                            return std::none_of(renames.begin(), renames.end(), [&](auto& o) {
                                return o.first == r.second;
                            });
                        });
                        if (next == renames.end()) {
                            next = renames.begin();
                        }
                        if (auto replaced = expr->replaceObject(owner, next->first, next->second)) {
                            expr = std::move(replaced);
                        }
                        renames.erase(next);
                    }
                    item->text = expr->toString(true);
                }
                catch (const Base::Exception& e) {
                    FC_WARN(owner->getFullName() << ": a parked expression could not be read on "
                                                    "import: " << e.what());
                }
            }
            auto rewritten = item->line();
            if (rewritten != line) {
                line = rewritten;
                changed = true;
            }
        }
        if (changed) {
            writeParkedLines(owner, lines);
        }
    }
}

}  // namespace

void registerParkedImport()
{
    auto watch = [](App::Document& doc) {
        doc.signalImportObjects.connect(&importParkedLines);
    };
    for (auto doc : App::GetApplication().getDocuments()) {
        watch(*doc);
    }
    App::GetApplication().signalNewDocument.connect([watch](const App::Document& doc, bool) {
        watch(const_cast<App::Document&>(doc));
    });
}

void registerParkedReferenceProvider()
{
    Sketcher::setParkedReferenceProvider([](const Sketcher::SketchObject& sketch, long id) {
        for (const auto& line : parkedLines(&sketch)) {
            auto item = ParkedItem::parse(line);
            if (item && item->extgeo
                && std::find(item->ids.begin(), item->ids.end(), id) != item->ids.end()) {
                std::string element = parkedElement(*item);
                return element.empty() ? item->target : item->target + "." + element;
            }
        }
        return std::string();
    });
}

}  // namespace PartDesign
