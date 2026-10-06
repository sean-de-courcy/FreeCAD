// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ElementSolverBatch.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>

#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Parameter.h>

#include "Application.h"
#include "ComplexGeoData.h"
#include "Document.h"
#include "DocumentObject.h"
#include "ElementFingerprint.h"
#include "ElementNamingUtils.h"
#include "ElementSolver.h"
#include "GeoFeature.h"
#include "NameTable.h"
#include "MappedElement.h"
#include "PropertyGeo.h"
#include "ReferenceReport.h"

FC_LOG_LEVEL_INIT("PropertyLinks", true, true)

namespace App
{

namespace
{
ElementHintsFunction elementHintsFunction = nullptr;

struct MigrationCounts
{
    int kept = 0;
    int moved = 0;
    int broken = 0;
};
// By the owner document's name: a document may be closed before the counts are reported.
std::map<std::string, MigrationCounts> migrationCounts;
}  // namespace

void setElementHintsFunction(ElementHintsFunction function)
{
    elementHintsFunction = function;
}

void countReferenceMigration(const DocumentObject* owner, MigrationOutcome outcome)
{
    auto doc = owner ? owner->getDocument() : nullptr;
    if (!doc) {
        return;
    }
    auto& counts = migrationCounts[doc->getName()];
    switch (outcome) {
        case MigrationOutcome::Kept:
            ++counts.kept;
            break;
        case MigrationOutcome::Moved:
            ++counts.moved;
            break;
        case MigrationOutcome::Broken:
            ++counts.broken;
            break;
    }
}

void reportReferenceMigration()
{
    // Every document's: a recompute re-derives the references other documents hold into it
    auto counts = std::move(migrationCounts);
    migrationCounts.clear();
    for (const auto& [name, count] : counts) {
        FC_WARN("Document '" << name << "': " << count.kept + count.moved + count.broken
                             << " element references re-derived from their geometry after a "
                                "naming change: "
                             << count.moved << " moved back to their element, " << count.broken
                             << " broken (listed above)");
    }
}

std::string bareMappedName(const std::string& newStyleName)
{
    const char* element = Data::findElementName(newStyleName.c_str());
    const char* mapped = element ? Data::isMappedElement(element) : nullptr;
    if (!mapped) {
        return {};
    }
    std::string name(mapped);
    // The index name after the last dot: `<name>.Face3`.
    auto dot = name.rfind('.');
    if (dot != std::string::npos) {
        name.resize(dot);
    }
    return name;
}

namespace
{

// The full name of the property for the log, as PropertyLinks.cpp names it: a
// PropertyXLinkSubList's link by its list.
std::string referenceName(const PropertyLinkBase* prop)
{
    if (!prop) {
        return {};
    }
    if (!prop->getContainer() || !prop->hasName()) {
        if (auto xlink = freecad_cast<const PropertyXLink*>(prop)) {
            return referenceName(xlink->parent());
        }
    }
    return prop->getFullName();
}

// The element type of an index name: `Face3` -> `Face`, `InternalEdge2` -> `InternalEdge`.
std::string indexType(const std::string& index)
{
    std::size_t end = index.size();
    while (end > 0 && index[end - 1] >= '0' && index[end - 1] <= '9') {
        --end;
    }
    return index.substr(0, end);
}

const char* const InternalPrefix = "Internal";

// A name expanded to its plain V2 form (ops#6). The solver compares names by their structure
// (sections, prefixes, embedded names), so every name it sees is plain, and it decides as it
// does in a document without InternNames.
std::string plainName(const std::string& name)
{
    if (name.find(Data::NameTable::Marker) == std::string::npos) {
        return name;
    }
    return Data::NameTable::instance().toPlain(name);
}

// The target's named elements of one type, each with all its names, plain. A sketch's
// `Internal*` types come from its InternalShape. `forms` gets the map's form of every name that
// isn't plain there, so that the names the solver picks are written back as the map holds them.
std::vector<Data::SolveInput::Element> poolOf(GeoFeature* geo,
                                              const std::string& type,
                                              std::map<std::string, std::string>& forms)
{
    std::vector<Data::SolveInput::Element> pool;
    const PropertyComplexGeoData* prop = geo->getPropertyOfGeometry();
    std::string elementType = type;
    std::string prefix;
    if (type.rfind(InternalPrefix, 0) == 0) {
        prop = freecad_cast<PropertyComplexGeoData*>(geo->getPropertyByName("InternalShape"));
        prefix = InternalPrefix;
        elementType = type.substr(prefix.size());
    }
    const Data::ComplexGeoData* data = prop ? prop->getComplexData() : nullptr;
    if (!data) {
        return pool;
    }
    std::map<std::string, std::vector<std::string>> names;
    for (const auto& mapped : data->getElementMap()) {
        if (!mapped.index || elementType != mapped.index.getType()) {
            continue;
        }
        std::string name = mapped.name.toString();
        std::string plain = plainName(name);
        if (plain != name) {
            forms[plain] = name;  // the map's form wins over an old name's
        }
        names[prefix + mapped.index.toString()].push_back(std::move(plain));
    }
    for (auto& [index, list] : names) {
        pool.push_back({index, std::move(list)});
    }
    return pool;
}

ParameterGrp::handle solverParameters()
{
    return App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Part/NamingSolver");
}

Data::Tier1Source tier1Source()
{
    std::string value = solverParameters()->GetASCII("Tier1Source", "union");
    if (value == "overlap") {
        return Data::Tier1Source::Overlap;
    }
    if (value == "names") {
        return Data::Tier1Source::Names;
    }
    return Data::Tier1Source::Union;
}

Data::OverlapMeasure overlapMeasure()
{
    std::string value = solverParameters()->GetASCII("Tier1Overlap", "plain");
    if (value == "depth") {
        return Data::OverlapMeasure::DepthWeighted;
    }
    if (value == "refids") {
        return Data::OverlapMeasure::ReferenceIds;
    }
    return Data::OverlapMeasure::Plain;
}

Data::Tier1Check tier1Check()
{
    std::string value = solverParameters()->GetASCII("Tier1Check", "intrinsic");
    if (value == "kind") {
        return Data::Tier1Check::Kind;
    }
    if (value == "none") {
        return Data::Tier1Check::None;
    }
    return Data::Tier1Check::Intrinsic;
}

// Tier 1's gap, the tolerances of tiers 2 and 3 and the continuation's distance (fork-only
// parameters for the tuning runs; a value that isn't positive and finite keeps the default).
void readTolerances(double& gap, Data::GeometryTolerances& tolerances, double& continuation)
{
    auto group = solverParameters();
    auto read = [&](const char* name, double& value) {
        double stored = group->GetFloat(name, value);
        if (std::isfinite(stored) && stored > 0.0) {
            value = stored;
        }
    };
    read("Tier1Gap", gap);
    read("Tier2Angle", tolerances.angle);
    read("Tier2Radius", tolerances.radius);
    read("Tier3Distance", tolerances.distance);
    read("Tier3GapFactor", tolerances.gapFactor);
    read("Tier3Size", tolerances.size);
    read("SamePlaceSize", tolerances.placeSize);
    read("ContinuationDistance", continuation);
    read("GuessDistance", tolerances.guessDistance);
    read("GuessGapFactor", tolerances.guessGapFactor);
    read("GuessSize", tolerances.guessSize);
}

Data::SolvePolicy solvePolicy(PropertyLinkBase::ElementPolicy policy)
{
    switch (policy) {
        case PropertyLinkBase::ElementPolicy::Expand:
            return Data::SolvePolicy::Expand;
        case PropertyLinkBase::ElementPolicy::Equivalent:
            return Data::SolvePolicy::Equivalent;
        case PropertyLinkBase::ElementPolicy::One:
        default:
            return Data::SolvePolicy::One;
    }
}

// The new sub and shadow of a reference resolved to element `index` with mapped name `name`
// (as _updateElementReference() writes an exact hit).
void resolutionFor(const SolverEntry& entry,
                   const std::string& index,
                   const std::string& name,
                   SolverResolution& resolution)
{
    resolution.status = SolverResolution::Status::Resolved;
    resolution.prop = entry.prop;
    resolution.index = entry.index;
    resolution.shadow.oldName = entry.prefix + index;
    if (!name.empty()) {
        resolution.shadow.newName =
            entry.prefix + Data::ComplexGeoData::elementMapPrefix() + name + "." + index;
    }
    if (!resolution.shadow.newName.empty() && Data::hasMappedElementName(entry.sub.c_str())) {
        resolution.sub = resolution.shadow.newName;
    }
    else {
        resolution.sub = resolution.shadow.oldName;
    }
}

// An exact reference that breaks (Task 2 PR 7): its missing form, as _updateElementReference()
// leaves a reference whose element is gone. The shadow keeps the name it held.
void brokenFor(const SolverEntry& entry, SolverResolution& resolution)
{
    resolution.status = SolverResolution::Status::Broken;
    resolution.prop = entry.prop;
    resolution.index = entry.index;
    resolution.shadow.newName = entry.prefix + Data::ComplexGeoData::elementMapPrefix()
        + entry.exactName + "." + entry.oldIndex;
    resolution.shadow.oldName = entry.prefix + Data::MISSING_PREFIX + entry.oldIndex;
    resolution.sub = entry.sub == resolution.shadow.newName ? resolution.shadow.newName
                                                            : resolution.shadow.oldName;
    // A provisional pick keeps its record (ops#127): the original stays known, and it can still
    // snap back
    resolution.guess = entry.guess;
}

// The record of a provisional resolution of \a entry (ops#127): the original is the entry's, or
// the record's when the reference holds one already.
GuessRecord guessRecordFor(const SolverEntry& entry, const char* kind)
{
    GuessRecord guess;
    guess.kind = kind;
    if (!entry.guess.empty()) {
        guess.origName = entry.guess.origName;
        guess.origIndex = entry.guess.origIndex;
    }
    else {
        guess.origName = entry.oldName.empty() ? entry.exactName : entry.oldName;
        guess.origIndex = entry.oldIndex;
    }
    return guess;
}

// An exact reference whose element can't be measured: no geometric check runs for it.
void logUnmeasured(const SolverEntry& entry)
{
    FC_LOG(referenceName(entry.prop) << "[" << entry.index << "]: " << entry.oldIndex
                                     << " can't be measured; kept by its name unchecked");
}

// Whether an exact reference must be solved, from \a saved, its saved fingerprint, and \a now,
// its element's current one: it may be split (Task 2 PR 7: a line edge or an arc that it now
// lies strictly within, or a plane it now lies in, smaller), or it moved and \a occupied says
// that another element sits where it was (ops#105). An element that moved alone needs nothing.
bool exactNeedsSolving(const SolverEntry& entry,
                       const Data::ElementFingerprint& saved,
                       const Data::ElementFingerprint& now,
                       double diagonal,
                       const Data::GeometryTolerances& tolerances,
                       double distance,
                       const std::function<bool()>& occupied)
{
    if (!saved.isValid()) {
        return false;
    }
    if (!now.isValid()) {
        logUnmeasured(entry);
        return false;
    }
    const std::string type = indexType(entry.oldIndex);
    if (type == "Edge" && saved.type == 'E' && (saved.kind == "Line" || saved.kind == "Circle")
        && Data::hitWithinOldEdge(saved, now, diagonal, tolerances, distance)) {
        return true;
    }
    if (type == "Face" && saved.type == 'F' && saved.kind == "Plane"
        && Data::faceWithinOldPlane(saved, now, diagonal, tolerances, distance)) {
        return true;
    }
    return !Data::atSamePlace(saved, now, diagonal, tolerances, distance) && occupied();
}

// Whether an exact hit is still the saved element in a naming migration (ops#103, rule 3): at
// its place, or within it (a split, as exactNeedsSolving() allows).
bool hitAgrees(const SolverEntry& entry,
               const Data::ElementFingerprint& saved,
               const Data::ElementFingerprint& now,
               double diagonal,
               const Data::GeometryTolerances& tolerances,
               double distance)
{
    const std::string type = indexType(entry.oldIndex);
    if (type == "Edge" && saved.type == 'E' && (saved.kind == "Line" || saved.kind == "Circle")
        && Data::hitWithinOldEdge(saved, now, diagonal, tolerances, distance)) {
        return true;
    }
    if (type == "Face" && saved.type == 'F' && saved.kind == "Plane"
        && Data::faceWithinOldPlane(saved, now, diagonal, tolerances, distance)) {
        return true;
    }
    return Data::atSamePlace(saved, now, diagonal, tolerances, distance);
}

// A naming migration's broken reference (ops#103): missing at its stored index, without the
// name, which now gives another element and would be followed by the next lookup. It keeps its
// fingerprint.
void migrationBrokenFor(const SolverEntry& entry, SolverResolution& resolution)
{
    resolution.status = SolverResolution::Status::Broken;
    resolution.prop = entry.prop;
    resolution.index = entry.index;
    const std::string& index = entry.storedIndex.empty() ? entry.oldIndex : entry.storedIndex;
    resolution.shadow.oldName = entry.prefix + Data::MISSING_PREFIX + index;
    resolution.sub = resolution.shadow.oldName;
}

// Two results of an equivalence probe are the same as the attacher compares placements
// (Attacher.cpp: the position within Precision::Confusion(), the rotation within
// Precision::Angular()).
bool samePlacement(const Base::Placement& a, const Base::Placement& b)
{
    constexpr double confusion = 1e-7;
    constexpr double angular = 1e-12;
    return a.getPosition().IsEqual(b.getPosition(), confusion)
        && a.getRotation().isSame(b.getRotation(), angular);
}

// The equivalence predicate of a reference whose owner has a probe: the probe runs once per
// element (with the reference's sub-object prefix), and two elements are equivalent when both
// give a result and the results are the same. A probe that throws gives no result.
std::function<bool(const std::string&, const std::string&)> equivalenceOf(const SolverEntry& entry)
{
    const auto& probe = entry.prop->getEquivalenceProbe();
    if (!probe) {
        return {};
    }
    auto results = std::make_shared<std::map<std::string, std::optional<Base::Placement>>>();
    return [probe, results, prefix = entry.prefix, index = entry.index](const std::string& a,
                                                                        const std::string& b) {
        auto resultOf = [&](const std::string& element) -> const std::optional<Base::Placement>& {
            auto it = results->find(element);
            if (it == results->end()) {
                std::optional<Base::Placement> result;
                try {
                    result = probe(index, prefix + element);
                }
                catch (...) {
                    result.reset();
                }
                it = results->emplace(element, result).first;
            }
            return it->second;
        };
        const auto& resultA = resultOf(a);
        const auto& resultB = resultOf(b);
        return resultA && resultB && samePlacement(*resultA, *resultB);
    };
}

std::string joinCandidates(const std::vector<std::string>& candidates)
{
    std::string text;
    for (const auto& candidate : candidates) {
        text += (text.empty() ? "" : ", ") + candidate;
    }
    return text;
}

}  // namespace

bool rebuildSubList(const std::vector<SolverResolution>& resolutions,
                    std::vector<std::string>& subs,
                    std::vector<PropertyLinkBase::ShadowSub>& shadows,
                    std::vector<std::string>& fingerprints,
                    std::vector<std::string>& froms,
                    std::vector<int>& firstNew,
                    std::vector<int>& countNew,
                    std::vector<ElementRecords>* recordsIn)
{
    using Status = SolverResolution::Status;
    const std::size_t count = subs.size();
    shadows.resize(count);
    fingerprints.resize(count);
    froms.resize(count);
    std::vector<ElementRecords> noRecords;
    std::vector<ElementRecords>& records = recordsIn ? *recordsIn : noRecords;
    records.resize(count);
    std::vector<const SolverResolution*> resolutionOf(count, nullptr);
    for (const auto& resolution : resolutions) {
        if (resolution.status != Status::None && resolution.index >= 0
            && resolution.index < static_cast<int>(count)) {
            resolutionOf[resolution.index] = &resolution;
        }
    }
    // The element a reference holds (`Edge3`, or with its sub-object prefix), if it resolves.
    auto elementOf = [](const std::string& sub, const PropertyLinkBase::ShadowSub& shadow) {
        const std::string& name = shadow.oldName.empty() ? sub : shadow.oldName;
        return Data::hasMissingElement(name.c_str()) ? std::string() : name;
    };
    std::set<std::string> untouched;
    for (std::size_t i = 0; i < count; ++i) {
        if (!resolutionOf[i]) {
            untouched.insert(elementOf(subs[i], shadows[i]));
        }
    }
    untouched.erase(std::string());
    std::set<std::string> written;
    // A collapse or a piece names an element another reference may hold already: one sub.
    auto held = [&](const std::string& sub, const PropertyLinkBase::ShadowSub& shadow) {
        std::string element = elementOf(sub, shadow);
        if (element.empty()) {
            return false;
        }
        return untouched.count(element) > 0 || !written.insert(element).second;
    };

    std::vector<std::string> newSubs, newFingerprints, newFroms;
    std::vector<PropertyLinkBase::ShadowSub> newShadows;
    // The reorder's re-target record (ops#127) stays with its reference through every
    // resolution but a repair, and with each piece of an expansion
    std::vector<ElementRecords> newRecords;
    std::size_t current = 0;
    auto add = [&](const std::string& sub,
                   const PropertyLinkBase::ShadowSub& shadow,
                   const std::string& fingerprint,
                   const std::string& from,
                   const GuessRecord& record = GuessRecord()) {
        newSubs.push_back(sub);
        newShadows.push_back(shadow);
        newFingerprints.push_back(fingerprint);
        newFroms.push_back(from);
        ElementRecords entry;
        entry.guess = record;
        if (!resolutionOf[current] || !resolutionOf[current]->clearRetarget) {
            entry.retarget = records[current].retarget;
        }
        newRecords.push_back(std::move(entry));
    };
    firstNew.assign(count, 0);
    countNew.assign(count, 0);
    bool changed = false;
    for (std::size_t i = 0; i < count; ++i) {
        current = i;
        firstNew[i] = static_cast<int>(newSubs.size());
        const SolverResolution* resolution = resolutionOf[i];
        if (!resolution) {
            add(subs[i], shadows[i], fingerprints[i], froms[i], records[i].guess);
        }
        else {
            changed = true;
            switch (resolution->status) {
                case Status::Resolved:
                    if (resolution->clearFrom) {
                        if (!held(resolution->sub, resolution->shadow)) {
                            add(resolution->sub, resolution->shadow, {}, {});
                        }
                    }
                    else {
                        written.insert(elementOf(resolution->sub, resolution->shadow));
                        add(resolution->sub, resolution->shadow, {}, froms[i]);
                    }
                    break;
                case Status::Expanded:
                    for (const auto& [sub, shadow] : resolution->pieces) {
                        if (!held(sub, shadow)) {
                            add(sub, shadow, {}, resolution->from);
                        }
                    }
                    break;
                case Status::Broken:
                    // A broken reference keeps its fingerprint for the next retry, and the record
                    // the resolution carries (ops#127)
                    add(resolution->sub,
                        resolution->shadow,
                        resolution->clearFingerprint ? std::string() : fingerprints[i],
                        froms[i],
                        resolution->guess);
                    break;
                case Status::Guessed:
                    // A provisional pick, with its record (ops#127): one element as Resolved
                    // writes it, or the pieces as Expanded.
                    if (!resolution->pieces.empty()) {
                        for (const auto& [sub, shadow] : resolution->pieces) {
                            if (!held(sub, shadow)) {
                                add(sub, shadow, {}, resolution->from, resolution->guess);
                            }
                        }
                    }
                    else {
                        written.insert(elementOf(resolution->sub, resolution->shadow));
                        add(resolution->sub, resolution->shadow, {}, froms[i], resolution->guess);
                    }
                    break;
                case Status::Removed:
                case Status::None:
                    break;
            }
        }
        countNew[i] = static_cast<int>(newSubs.size()) - firstNew[i];
    }
    subs.swap(newSubs);
    shadows.swap(newShadows);
    fingerprints.swap(newFingerprints);
    froms.swap(newFroms);
    records.swap(newRecords);
    return changed;
}

std::vector<int> remapSubIndices(const std::vector<int>& mapped,
                                 const std::vector<int>& firstNew,
                                 const std::vector<int>& countNew)
{
    std::vector<int> result;
    const int size = static_cast<int>(std::min(firstNew.size(), countNew.size()));
    for (int m : mapped) {
        if (m < 0 || m >= size) {
            continue;
        }
        for (int k = 0; k < countNew[m]; ++k) {
            result.push_back(firstNew[m] + k);
        }
    }
    return result;
}

bool fingerprintsAgree(const Data::ElementFingerprint& saved,
                       const Data::ElementFingerprint& now,
                       double diagonal)
{
    if (saved.type != now.type || saved.kind != now.kind) {
        return false;
    }
    auto relative = [](double a, double b) {
        return std::abs(a - b) <= 1e-9 * std::max({1.0, std::abs(a), std::abs(b)});
    };
    if (saved.size.has_value() != now.size.has_value()
        || (saved.size && !relative(*saved.size, *now.size))) {
        return false;
    }
    if (saved.center.has_value() != now.center.has_value()
        || (saved.center
            && Base::Distance(*saved.center, *now.center) > 1e-7 * std::max(diagonal, 1.0))) {
        return false;
    }
    if (saved.direction.has_value() != now.direction.has_value()
        || (saved.direction && Base::Distance(*saved.direction, *now.direction) > 1e-9)) {
        return false;
    }
    if (saved.radii.size() != now.radii.size()) {
        return false;
    }
    for (std::size_t i = 0; i < saved.radii.size(); ++i) {
        if (!relative(saved.radii[i], now.radii[i])) {
            return false;
        }
    }
    // A circle's centre (PR 7b), when both have one: a version-1 fingerprint has none.
    if (saved.location && now.location
        && Base::Distance(*saved.location, *now.location) > 1e-7 * std::max(diagonal, 1.0)) {
        return false;
    }
    // A plane's extent (PR 8), when both have one.
    if (saved.extentMin && saved.extentMax && now.extentMin && now.extentMax
        && (Base::Distance(*saved.extentMin, *now.extentMin) > 1e-7 * std::max(diagonal, 1.0)
            || Base::Distance(*saved.extentMax, *now.extentMax)
                > 1e-7 * std::max(diagonal, 1.0))) {
        return false;
    }
    return true;
}

bool solveElementReferences(DocumentObject* feature,
                            const std::vector<PropertyLinkBase*>& props,
                            bool reverse,
                            bool notify)
{
    auto geo = freecad_cast<GeoFeature*>(feature);
    if (!geo || !feature->isAttachedToDocument()) {
        return false;
    }

    // Pass 1: the exact lookup, per property.
    SolverBatch batch;
    batch.feature = feature;
    batch.reverse = reverse;
    batch.notify = notify;
    for (auto prop : props) {
        try {
            prop->collectElementReferences(feature, batch);
        }
        catch (Base::Exception& e) {
            e.reportException();
            FC_ERR("Failed to update element reference of " << referenceName(prop));
        }
        catch (std::exception& e) {
            FC_ERR("Failed to update element reference of " << referenceName(prop) << ": "
                                                            << e.what());
        }
    }

    // Pass 2. Keep the references to feature's elements, by owner.
    std::map<std::string, std::vector<const SolverEntry*>> owners;  // by full name
    for (const auto& entry : batch.entries) {
        if (!entry.owner || !entry.obj) {
            continue;
        }
        ElementNamePair elementName;
        GeoFeature* target = nullptr;
        if (!GeoFeature::resolveElement(entry.obj,
                                        entry.prefix.c_str(),
                                        elementName,
                                        true,
                                        GeoFeature::ElementNameType::Export,
                                        feature,
                                        nullptr,
                                        &target)
            || target != geo) {
            continue;
        }
        owners[entry.owner->getFullName()].push_back(&entry);
    }

    std::map<const PropertyLinkBase*, std::vector<SolverResolution>> resolutions;
    std::map<const PropertyLinkBase*, std::vector<ReferenceReport::Entry>> reports;
    std::map<std::string, std::vector<Data::SolveInput::Element>> pools;  // by type
    std::map<std::string, std::string> mapForms;  // plain name -> the map's form (ops#6)
    auto pool = [&](const std::string& type) -> const std::vector<Data::SolveInput::Element>& {
        auto it = pools.find(type);
        if (it == pools.end()) {
            it = pools.emplace(type, poolOf(geo, type, mapForms)).first;
        }
        return it->second;
    };
    // A name the solver took from the pool, in the target map's form
    auto mapForm = [&mapForms](const std::string& name) {
        auto it = mapForms.find(name);
        return it == mapForms.end() ? name : it->second;
    };
    const std::string targetName = feature->getFullName();
    bool sourceRead = false;
    Data::Tier1Source source = Data::Tier1Source::Union;
    Data::OverlapMeasure measure = Data::OverlapMeasure::Plain;
    Data::Tier1Check check = Data::Tier1Check::Intrinsic;
    double gap = Data::SolveInput().gap;
    Data::GeometryTolerances tolerances;
    double continuationDistance = Data::SolveInput().continuationDistance;
    // The guess rules' switches (ops#127, N2 5.1), on by default
    bool guess = true;
    bool guessNoStructure = true;
    double diagonal = 0.0;
    std::string maplessTag;
    std::map<std::string, std::vector<std::string>> nameMatches;  // by old name
    // The target's faces that share an edge, built on first use (a face split by a coplanar
    // one): each edge's faces.
    using Adjacency = std::map<std::string, std::set<std::string>>;
    auto adjacency = std::make_shared<std::optional<Adjacency>>();
    auto neighboursOf = [geo, adjacency](const std::string& face) {
        if (!*adjacency) {
            Adjacency map;
            const PropertyComplexGeoData* prop = geo->getPropertyOfGeometry();
            const Data::ComplexGeoData* data = prop ? prop->getComplexData() : nullptr;
            const unsigned long count = data ? data->countSubElements("Edge") : 0;
            for (unsigned long e = 1; e <= count; ++e) {
                std::vector<std::string> faces;
                for (const auto& higher :
                     geo->getHigherElements(("Edge" + std::to_string(e)).c_str(), true)) {
                    if (std::strcmp(higher.getType(), "Face") == 0) {
                        faces.push_back(higher.toString());
                    }
                }
                for (const auto& a : faces) {
                    for (const auto& b : faces) {
                        if (a != b) {
                            map[a].insert(b);
                        }
                    }
                }
            }
            *adjacency = std::move(map);
        }
        auto it = (*adjacency)->find(face);
        return it == (*adjacency)->end()
            ? std::vector<std::string>()
            : std::vector<std::string>(it->second.begin(), it->second.end());
    };

    // The target's elements' current fingerprints, measured once per batch: the shape is the
    // same for every owner (ops#105).
    auto measured = std::make_shared<std::map<std::string, Data::ElementFingerprint>>();
    auto fingerprintOf = [geo, measured](const std::string& index) {
        auto it = measured->find(index);
        if (it == measured->end()) {
            Data::ElementFingerprint fingerprint;
            if (!geo->getElementFingerprint(index.c_str(), fingerprint)) {
                fingerprint = Data::ElementFingerprint();
            }
            it = measured->emplace(index, std::move(fingerprint)).first;
        }
        return it->second;
    };
    // Their cheap descriptions (App::ElementHintsFunction), a type at a time, once per batch.
    auto hints = std::make_shared<std::map<std::string, std::vector<ElementHint>>>();
    std::function<bool(const std::string&, Data::ElementFingerprint&, std::optional<Base::Vector3d>&)>
        hintOf;
    if (elementHintsFunction) {
        hintOf = [geo, hints](const std::string& index,
                              Data::ElementFingerprint& intrinsic,
                              std::optional<Base::Vector3d>& anchor) {
            const std::string type = indexType(index);
            auto it = hints->find(type);
            if (it == hints->end()) {
                std::vector<ElementHint> list;
                if (!elementHintsFunction(geo, type.c_str(), list)) {
                    list.clear();
                }
                it = hints->emplace(type, std::move(list)).first;
            }
            const std::size_t k = std::strtoul(index.c_str() + type.size(), nullptr, 10);
            if (k < 1 || k > it->second.size() || !it->second[k - 1].valid) {
                return false;
            }
            const ElementHint& hint = it->second[k - 1];
            intrinsic = hint.intrinsic;
            anchor.reset();
            if (hint.hasAnchor) {
                anchor = hint.anchor;
            }
            return true;
        };
    }

    // The elements of `except`'s type, other than it, at the place \a saved records (ops#105), up
    // to the first if \a first: the hints rule most out unmeasured. None if they can't be
    // scanned (no shape, a sketch's internal elements).
    auto elementsAt = [&](const Data::ElementFingerprint& saved,
                          const std::string& except,
                          bool first) -> std::optional<std::vector<std::string>> {
        const std::string type = indexType(except);
        const PropertyComplexGeoData* prop = geo->getPropertyOfGeometry();
        const Data::ComplexGeoData* data = prop ? prop->getComplexData() : nullptr;
        if (!data || type.rfind(InternalPrefix, 0) == 0) {
            return std::nullopt;
        }
        std::vector<std::string> places;
        const unsigned long count = data->countSubElements(type.c_str());
        for (unsigned long k = 1; k <= count; ++k) {
            const std::string index = type + std::to_string(k);
            if (index == except) {
                continue;
            }
            Data::ElementFingerprint intrinsic;
            std::optional<Base::Vector3d> anchor;
            if (hintOf && hintOf(index, intrinsic, anchor)
                && !Data::mayBeAtPlace(saved,
                                       intrinsic,
                                       anchor,
                                       diagonal,
                                       tolerances,
                                       continuationDistance)) {
                continue;
            }
            if (Data::atSamePlace(saved,
                                  fingerprintOf(index),
                                  diagonal,
                                  tolerances,
                                  continuationDistance)) {
                places.push_back(index);
                if (first) {
                    break;
                }
            }
        }
        return places;
    };
    // An element's mapped name for a resolution (the least, as index carry takes it)
    auto nameAt = [&](const std::string& index) {
        std::string name;
        for (const auto& element : pool(indexType(index))) {
            if (element.index == index && !element.names.empty()) {
                name = *std::min_element(element.names.begin(), element.names.end());
            }
        }
        return mapForm(name);
    };

    for (auto& [ownerName, entries] : owners) {
        std::stable_sort(entries.begin(), entries.end(), [](const auto* a, const auto* b) {
            auto na = referenceName(a->prop);
            auto nb = referenceName(b->prop);
            return na != nb ? na < nb : a->index < b->index;
        });
        bool anyMissing = std::any_of(entries.begin(), entries.end(), [](const auto* e) {
            return e->kind == SolverEntry::Kind::Missing;
        });
        // A guessed reference whose original's name gives an element again snaps back
        // (ops#127).
        bool anyGuessed = std::any_of(entries.begin(), entries.end(), [](const auto* e) {
            return e->guessed;
        });
        // An owner with only exact references is solved only if one of them has a saved
        // fingerprint that its element no longer agrees with: moved, or maybe split. A reverse
        // update checks every one with a fingerprint (ops#103), and every one whose name now
        // gives another element than its stored index (ops#116).
        if (!anyMissing && !anyGuessed
            && std::none_of(entries.begin(), entries.end(), [reverse](const auto* e) {
                return e->kind == SolverEntry::Kind::Exact
                    && (!e->oldFingerprint.empty()
                        || (reverse && !e->storedIndex.empty() && e->storedIndex != e->oldIndex));
            })) {
            continue;
        }

        auto report = [&](const SolverEntry& entry, ReferenceReport::Entry item) {
            item.index = entry.index;
            item.oldName = entry.oldName.empty() ? entry.exactName : entry.oldName;
            item.oldIndex = entry.oldIndex;
            item.target = targetName;
            reports[entry.prop].push_back(std::move(item));
        };

        if (!sourceRead) {
            source = tier1Source();
            measure = overlapMeasure();
            check = tier1Check();
            readTolerances(gap, tolerances, continuationDistance);
            guess = solverParameters()->GetBool("Guess", true);
            guessNoStructure = solverParameters()->GetBool("GuessNoStructure", true);
            if (auto prop = geo->getPropertyOfGeometry()) {
                if (auto data = prop->getComplexData()) {
                    diagonal = data->getBoundBox().CalcDiagonalLength();
                    if (data->Tag != 0 && data->getElementMapSize() == 0) {
                        maplessTag = std::to_string(data->Tag);
                    }
                }
            }
            sourceRead = true;
        }
        if (!anyMissing && !anyGuessed && !reverse) {
            // Every entry, not up to the first: each unmeasurable one is logged.
            bool needed = false;
            for (const auto* e : entries) {
                if (e->kind != SolverEntry::Kind::Exact || e->oldFingerprint.empty()) {
                    continue;
                }
                const auto saved = Data::ElementFingerprint::fromString(e->oldFingerprint);
                // Another element of its type where it was. Solving the owner (its pools) costs
                // more than this scan.
                auto occupied = [&]() {
                    auto places = elementsAt(saved, e->oldIndex, true);
                    return !places || !places->empty();  // unscanned: solveOwner() decides
                };
                if (exactNeedsSolving(*e,
                                      saved,
                                      fingerprintOf(e->oldIndex),
                                      diagonal,
                                      tolerances,
                                      continuationDistance,
                                      occupied)) {
                    needed = true;
                }
            }
            if (!needed) {
                continue;
            }
        }

        if (reverse) {
            // An element-map version change (a naming migration, ops#103). An exact hit must
            // agree with its saved fingerprint: if its name moved, the element at its saved place
            // is taken (rule 3).
            for (const auto* entry : entries) {
                // A snap-back waits for the next update (ops#127).
                if (entry->kind != SolverEntry::Kind::Exact || entry->guessed) {
                    continue;
                }
                const auto saved = Data::ElementFingerprint::fromString(entry->oldFingerprint);
                const std::string& hit = entry->oldIndex;
                if (!saved.isValid()) {
                    if (entry->storedIndex.empty() || hit == entry->storedIndex) {
                        countReferenceMigration(entry->owner, MigrationOutcome::Kept);
                        continue;
                    }
                    // No geometry to re-derive it from, and its name now gives another element:
                    // broken, not moved (rule 1's counterpart, ops#116)
                    SolverResolution resolution;
                    migrationBrokenFor(*entry, resolution);
                    resolutions[entry->prop].push_back(resolution);
                    ReferenceReport::Entry item;
                    item.status = ReferenceReport::Status::Broken;
                    item.evidence = "migration: the name moved; no fingerprint to find its place";
                    item.candidates.emplace_back(hit, nameAt(hit));
                    item.candidateRoles.emplace_back("name");
                    item.candidateDistances.push_back(std::numeric_limits<double>::quiet_NaN());
                    FC_WARN(referenceName(entry->prop)
                            << "[" << entry->index << "]: " << entry->exactName << " broken ("
                            << item.evidence << ", candidates: " << hit << ")");
                    countReferenceMigration(entry->owner, MigrationOutcome::Broken);
                    report(*entry, std::move(item));
                    continue;
                }
                const auto& now = fingerprintOf(hit);
                if (!now.isValid()) {
                    logUnmeasured(*entry);
                    countReferenceMigration(entry->owner, MigrationOutcome::Kept);
                    continue;
                }
                if (hitAgrees(*entry, saved, now, diagonal, tolerances, continuationDistance)) {
                    countReferenceMigration(entry->owner, MigrationOutcome::Kept);
                    continue;
                }
                const std::string& stored = entry->storedIndex;
                auto places = elementsAt(saved, hit, false);
                if (hit == stored && (!places || places->empty())) {
                    // The name didn't move and nothing sits where its element was: it moved
                    // alone (an edit before the migration), kept as ops#105 and rule 1 keep it
                    countReferenceMigration(entry->owner, MigrationOutcome::Kept);
                    continue;
                }
                std::string pick;
                if (places && places->size() == 1) {
                    pick = places->front();
                }
                else if (places && places->size() > 1
                         && std::find(places->begin(), places->end(), stored) != places->end()) {
                    pick = stored;  // rule 2: among coincident elements, the stored index
                }
                ReferenceReport::Entry item;
                const std::string& oldName = entry->exactName;
                if (!pick.empty()) {
                    SolverResolution resolution;
                    resolutionFor(*entry, pick, nameAt(pick), resolution);
                    // Kept by its place, with a warning (ops#127). A plain reference's record
                    // has no name: the name gives another element now. One that holds a record
                    // keeps its original. An index record never snaps back.
                    resolution.status = SolverResolution::Status::Guessed;
                    if (!entry->guess.empty()) {
                        resolution.guess = guessRecordFor(*entry, "index");
                    }
                    else {
                        resolution.guess.kind = "index";
                        resolution.guess.origIndex = stored.empty() ? hit : stored;
                    }
                    resolutions[entry->prop].push_back(resolution);
                    item.status = ReferenceReport::Status::Index;
                    item.kind = resolution.guess.kind;
                    item.newIndex = pick;
                    item.evidence = "migration: the name moved; " + pick + " sits where it was";
                    item.candidates.emplace_back(pick, nameAt(pick));
                    item.candidateRoles.emplace_back("place");
                    item.candidateDistances.push_back(std::numeric_limits<double>::quiet_NaN());
                    FC_WARN(referenceName(entry->prop)
                            << "[" << entry->index << "]: " << oldName << " -> " << pick
                            << " (" << item.evidence << ", not " << hit << ")");
                    countReferenceMigration(entry->owner, MigrationOutcome::Moved);
                }
                else {
                    // Rules 1 and 2's counterparts: the old geometry is gone, or several
                    // elements sit there and none is the stored one. Broken, never the name's.
                    SolverResolution resolution;
                    migrationBrokenFor(*entry, resolution);
                    resolutions[entry->prop].push_back(resolution);
                    item.status = ReferenceReport::Status::Broken;
                    std::string where;
                    if (places) {
                        for (const auto& place : *places) {
                            item.candidates.emplace_back(place, nameAt(place));
                            item.candidateRoles.emplace_back("place");
                            item.candidateDistances.push_back(
                                std::numeric_limits<double>::quiet_NaN()
                            );
                            where += (where.empty() ? "" : " and ") + place;
                        }
                    }
                    item.candidates.emplace_back(hit, nameAt(hit));
                    item.candidateRoles.emplace_back("name");
                    item.candidateDistances.push_back(std::numeric_limits<double>::quiet_NaN());
                    if (!places) {
                        item.evidence = "migration: the name moved; its place can't be scanned";
                    }
                    else if (where.empty()) {
                        item.evidence = "migration: the name moved; nothing sits where it was";
                    }
                    else {
                        item.evidence = "migration: the name moved; " + where + " sit where it was";
                        std::string type = indexType(hit);
                        std::transform(type.begin(), type.end(), type.begin(), [](unsigned char c) {
                            return static_cast<char>(std::tolower(c));
                        });
                        item.headline = "Ambiguous " + type + " reference: " + hit + " moved and "
                            + where + " sit where it was";
                    }
                    std::vector<std::string> candidates;
                    for (const auto& candidate : item.candidates) {
                        candidates.push_back(candidate.first);
                    }
                    FC_WARN(referenceName(entry->prop)
                            << "[" << entry->index << "]: " << oldName << " broken ("
                            << item.evidence << ", candidates: " << joinCandidates(candidates)
                            << ")");
                    countReferenceMigration(entry->owner, MigrationOutcome::Broken);
                }
                report(*entry, std::move(item));
            }
            // Missing references: index carry, verified by the saved fingerprint.
            for (const auto* entry : entries) {
                if (entry->kind != SolverEntry::Kind::Missing || entry->guessed) {
                    continue;
                }
                const std::string& index = entry->oldIndex;
                Data::ElementFingerprint now;
                bool exists = geo->getElementFingerprint(index.c_str(), now);
                auto saved = Data::ElementFingerprint::fromString(entry->oldFingerprint);
                std::string name;
                for (const auto& element : pool(indexType(index))) {
                    if (element.index == index && !element.names.empty()) {
                        name = *std::min_element(element.names.begin(), element.names.end());
                    }
                }
                ReferenceReport::Entry item;
                if (exists && saved.isValid() && fingerprintsAgree(saved, now, diagonal)) {
                    countReferenceMigration(entry->owner, MigrationOutcome::Moved);
                    SolverResolution resolution;
                    resolutionFor(*entry, index, mapForm(name), resolution);
                    // Kept by its place, with a warning and a record without the name, which
                    // isn't found, or the original of the record it holds (ops#127).
                    resolution.status = SolverResolution::Status::Guessed;
                    if (!entry->guess.empty()) {
                        resolution.guess = guessRecordFor(*entry, "index");
                    }
                    else {
                        resolution.guess.kind = "index";
                        resolution.guess.origIndex = index;
                    }
                    resolutions[entry->prop].push_back(resolution);
                    item.status = ReferenceReport::Status::Index;
                    item.kind = resolution.guess.kind;
                    item.newIndex = index;
                    item.evidence = "index carry, fingerprint equal";
                    FC_WARN(referenceName(entry->prop)
                            << "[" << entry->index << "]: " << entry->oldName << " -> " << index
                            << " (tier index, fingerprint equal)");
                }
                else {
                    countReferenceMigration(entry->owner, MigrationOutcome::Broken);
                    item.status = ReferenceReport::Status::Broken;
                    item.evidence = !saved.isValid() ? "index carry, no fingerprint"
                        : !exists                    ? "index carry, no such element"
                                                     : "index carry, fingerprint differs";
                    if (exists) {
                        item.candidates.emplace_back(index, mapForm(name));
                        item.candidateRoles.emplace_back("index");
                        item.candidateDistances.push_back(
                            std::numeric_limits<double>::quiet_NaN()
                        );
                    }
                    FC_WARN(referenceName(entry->prop)
                            << "[" << entry->index << "]: " << entry->oldName << " broken ("
                            << item.evidence << (exists ? ", candidates: " + index : "")
                            << ")");
                }
                report(*entry, std::move(item));
            }
            continue;
        }

        Data::SolveInput input;
        input.source = source;
        input.measure = measure;
        input.check = check;
        input.gap = gap;
        input.tolerances = tolerances;
        input.diagonal = diagonal;
        input.maplessTag = maplessTag;
        input.continuationDistance = continuationDistance;
        input.guess = guess;
        input.guessNoStructure = guessNoStructure;
        // Nothing is guessed against a failed feature passing its input through (N2's N10)
        input.targetFailed = feature->isError();
        input.fingerprintOf = fingerprintOf;
        input.hintOf = hintOf;
        // The solver's only topology: the faces an edge bounds, for the continuation.
        input.facesOf = [geo](const std::string& index) {
            std::vector<std::string> faces;
            for (const auto& higher : geo->getHigherElements(index.c_str(), true)) {
                if (std::strcmp(higher.getType(), "Face") == 0) {
                    faces.push_back(higher.toString());
                }
            }
            return faces;
        };
        input.neighboursOf = neighboursOf;
        for (const auto* entry : entries) {
            Data::SolveInput::Entry item;
            item.type = indexType(entry->oldIndex);
            item.policy = solvePolicy(entry->policy);
            if (item.policy == Data::SolvePolicy::Expand
                && !freecad_cast<PropertyLinkSub*>(entry->prop)) {
                // Only a PropertyLinkSub keeps several subs for one reference, with their
                // `from`; no other property has the Expand policy today.
                FC_LOG(referenceName(entry->prop)
                       << "[" << entry->index << "]: Expand read as One (not a PropertyLinkSub)");
                item.policy = Data::SolvePolicy::One;
            }
            item.fingerprint = Data::ElementFingerprint::fromString(entry->oldFingerprint);
            if (item.policy == Data::SolvePolicy::Equivalent) {
                item.equivalent = equivalenceOf(*entry);
            }
            // The old names, plain; their own forms are what `from` is written back in
            auto plainOld = [&mapForms](const std::string& name) {
                std::string plain = plainName(name);
                if (plain != name) {
                    mapForms.emplace(plain, name);
                }
                return plain;
            };
            item.from = plainOld(entry->from);
            item.scope = std::to_string(reinterpret_cast<std::uintptr_t>(entry->prop)) + "|"
                + entry->prefix;
            item.position = entry->index;
            if (entry->guess.kind == "rejected") {
                // The elements the user rejected for it (App::markReferenceBroken(), ops#127)
                for (const auto& alternative : entry->guess.alternatives) {
                    if (alternative.role == "rejected") {
                        item.excluded.push_back(alternative.index);
                    }
                }
            }
            if (entry->kind == SolverEntry::Kind::Exact) {
                if (anyMissing && item.fingerprint.isValid()
                    && !fingerprintOf(entry->oldIndex).isValid()) {
                    logUnmeasured(*entry);  // the owner filter, which logs it, didn't run
                }
                item.exact = true;
                item.exactElement = entry->oldIndex;
                item.exactName = plainOld(entry->exactName);
            }
            else {
                item.oldName = plainOld(entry->oldName);
                if (source != Data::Tier1Source::Overlap && !entry->oldName.empty()) {
                    auto it = nameMatches.find(entry->oldName);
                    if (it == nameMatches.end()) {
                        Data::MappedName searchName(entry->oldName);
                        std::vector<std::string> names;
                        for (const auto& match : geo->findSimilarNames(searchName)) {
                            names.push_back(plainName(match.name.toString()));
                        }
                        it = nameMatches.emplace(entry->oldName, std::move(names)).first;
                    }
                    item.nameMatches = it->second;
                }
            }
            if (input.pool.find(item.type) == input.pool.end()) {
                input.pool[item.type] = pool(item.type);
            }
            input.entries.push_back(std::move(item));
        }

        auto outcomes = Data::solveOwner(input);
        for (std::size_t i = 0; i < entries.size(); ++i) {
            const auto& entry = *entries[i];
            const auto& outcome = outcomes[i];
            const std::string& oldName = entry.oldName.empty() ? entry.exactName : entry.oldName;
            if (outcome.status == Data::SolveStatus::Exact) {
                if (entry.guessed) {
                    // The original's name gives an element again: the reference snaps back to
                    // it, its record goes and its fingerprint is measured anew (ops#127).
                    SolverResolution resolution;
                    resolutionFor(entry, entry.oldIndex, entry.exactName, resolution);
                    resolutions[entry.prop].push_back(resolution);
                    FC_WARN(referenceName(entry.prop)
                            << "[" << entry.index << "]: " << entry.guessedIndex << " -> "
                            << entry.oldIndex << " (the original " << entry.guess.origIndex
                            << " is back)");
                }
                continue;
            }
            if (outcome.status == Data::SolveStatus::Removed) {
                SolverResolution resolution;
                resolution.status = SolverResolution::Status::Removed;
                resolution.prop = entry.prop;
                resolution.index = entry.index;
                resolutions[entry.prop].push_back(resolution);
                FC_WARN(referenceName(entry.prop)
                        << "[" << entry.index << "]: " << oldName << " removed ("
                        << outcome.evidence << " to " << outcome.element << ")");
                continue;
            }
            ReferenceReport::Entry item;
            item.evidence = outcome.evidence;
            if (outcome.status == Data::SolveStatus::Resolved && !outcome.elements.empty()) {
                // A continuation or a split, expanded: warned, with a record on every piece
                // (ops#127).
                SolverResolution resolution;
                resolution.status = SolverResolution::Status::Guessed;
                resolution.prop = entry.prop;
                resolution.index = entry.index;
                resolution.from = mapForm(outcome.from);
                resolution.guess =
                    guessRecordFor(entry, outcome.tier == 4 ? "continued" : "expanded");
                for (std::size_t p = 0; p < outcome.elements.size(); ++p) {
                    SolverResolution piece;
                    resolutionFor(entry, outcome.elements[p], mapForm(outcome.names[p]), piece);
                    resolution.pieces.emplace_back(piece.sub, piece.shadow);
                    item.pieces.emplace_back(outcome.elements[p], mapForm(outcome.names[p]));
                }
                resolutions[entry.prop].push_back(resolution);
                FC_WARN(referenceName(entry.prop)
                        << "[" << entry.index << "]: " << oldName << " -> "
                        << joinCandidates(outcome.elements) << " (tier " << outcome.tier << ", "
                        << outcome.evidence << ")");
                item.status = ReferenceReport::Status::Expanded;
                item.kind = resolution.guess.kind;
                item.tier = outcome.tier;
                item.newIndex = outcome.element;
            }
            else if (outcome.status == Data::SolveStatus::Resolved) {
                SolverResolution resolution;
                resolutionFor(entry, outcome.element, mapForm(outcome.name), resolution);
                resolution.clearFrom = outcome.collapsed;
                if (outcome.tier >= 2) {
                    // Resolved by geometry: warned, with a record and the other candidates
                    // (ops#127).
                    resolution.status = SolverResolution::Status::Guessed;
                    resolution.guess =
                        guessRecordFor(entry, outcome.tier == 2 ? "tier2" : "tier3");
                    for (std::size_t c = 0; c < outcome.candidates.size(); ++c) {
                        GuessRecord::Alternative alternative;
                        alternative.index = outcome.candidates[c];
                        if (c < outcome.candidateRoles.size()) {
                            alternative.role = outcome.candidateRoles[c];
                        }
                        if (c < outcome.candidateDistances.size()) {
                            alternative.distance = outcome.candidateDistances[c];
                        }
                        resolution.guess.alternatives.push_back(std::move(alternative));
                    }
                    item.kind = resolution.guess.kind;
                }
                else if (!entry.guess.empty() && !outcome.collapsed
                         && entry.guess.kind != "rejected") {
                    // A provisional pick followed to its element's next form keeps its record
                    // and its warning: structure followed the pick, not the original. (A
                    // rejected one that structure resolves to another element is resolved.)
                    resolution.status = SolverResolution::Status::Guessed;
                    resolution.guess = entry.guess;
                    item.kind = resolution.guess.kind;
                }
                resolutions[entry.prop].push_back(resolution);
                FC_WARN(referenceName(entry.prop)
                        << "[" << entry.index << "]: " << oldName << " -> " << outcome.element
                        << " (tier " << outcome.tier << ", " << outcome.evidence << ")");
                item.status = ReferenceReport::Status::Resolved;
                item.tier = outcome.tier;
                item.newIndex = outcome.element;
            }
            else if (outcome.status == Data::SolveStatus::Guessed) {
                // A guess rule's pick (ops#127, N2 section 5): warned, with a record whose
                // alternatives are the other elements the rule chose among
                SolverResolution resolution;
                resolutionFor(entry, outcome.element, mapForm(outcome.name), resolution);
                resolution.status = SolverResolution::Status::Guessed;
                resolution.guess = guessRecordFor(entry, outcome.guessKind.c_str());
                for (std::size_t c = 1; c < outcome.candidates.size(); ++c) {
                    GuessRecord::Alternative alternative;
                    alternative.index = outcome.candidates[c];
                    if (c < outcome.candidateRoles.size()) {
                        alternative.role = outcome.candidateRoles[c];
                    }
                    if (c < outcome.candidateDistances.size()) {
                        alternative.distance = outcome.candidateDistances[c];
                    }
                    resolution.guess.alternatives.push_back(std::move(alternative));
                }
                resolutions[entry.prop].push_back(resolution);
                item.status = ReferenceReport::Status::Guessed;
                item.kind = outcome.guessKind;
                item.tier = outcome.tier;
                item.newIndex = outcome.element;
                for (std::size_t c = 0; c < outcome.candidates.size(); ++c) {
                    item.candidates.emplace_back(outcome.candidates[c],
                                                 mapForm(outcome.candidateNames[c]));
                }
                item.candidateRoles = outcome.candidateRoles;
                item.candidateDistances = outcome.candidateDistances;
                FC_WARN(referenceName(entry.prop)
                        << "[" << entry.index << "]: " << oldName << " -> " << outcome.element
                        << " (guessed, " << outcome.evidence << ")");
            }
            else {
                if (entry.kind == SolverEntry::Kind::Exact) {
                    // A continuation under One or Equivalent, or a run-past: the exact
                    // reference becomes missing (the owner fails, the fingerprint stays).
                    SolverResolution resolution;
                    brokenFor(entry, resolution);
                    resolutions[entry.prop].push_back(resolution);
                }
                item.status = ReferenceReport::Status::Broken;
                std::string places;  // the elements where a moved one was (ops#105)
                for (std::size_t c = 0; c < outcome.candidates.size(); ++c) {
                    item.candidates.emplace_back(outcome.candidates[c],
                                                 mapForm(outcome.candidateNames[c]));
                    if (c < outcome.candidateRoles.size()
                        && outcome.candidateRoles[c] == "place") {
                        places += (places.empty() ? "" : " and ") + outcome.candidates[c];
                    }
                }
                item.candidateRoles = outcome.candidateRoles;
                item.candidateDistances = outcome.candidateDistances;
                if (!places.empty()) {
                    std::string type = indexType(entry.oldIndex);
                    std::transform(type.begin(), type.end(), type.begin(), [](unsigned char c) {
                        return static_cast<char>(std::tolower(c));
                    });
                    // The evidence's verb: `moved`, or `changed` in place.
                    const char* verb =
                        outcome.evidence.rfind("changed", 0) == 0 ? " changed and " : " moved and ";
                    item.headline = "Ambiguous " + type + " reference: " + entry.oldIndex + verb
                        + places
                        + (places.find(" and ") == std::string::npos ? " sits" : " sit")
                        + " where it was";
                }
                FC_WARN(referenceName(entry.prop)
                        << "[" << entry.index << "]: " << oldName << " broken ("
                        << outcome.evidence
                        << (outcome.candidates.empty()
                                ? std::string()
                                : ", candidates: " + joinCandidates(outcome.candidates))
                        << ")");
            }
            report(entry, std::move(item));
        }
    }

    // Write back, once per property visited, and rebuild its report for this target.
    bool changed = false;
    for (const auto& [prop, touched] : batch.properties) {
        auto& list = resolutions[prop];
        if (list.empty()) {
            list.emplace_back();
        }
        for (auto& resolution : list) {
            resolution.prop = prop;
            resolution.feature = feature;
            resolution.notify = notify;
            resolution.touched = touched;
            changed = changed || touched || resolution.status != SolverResolution::Status::None;
        }
        try {
            prop->applyResolutions(list);
        }
        catch (Base::Exception& e) {
            e.reportException();
            FC_ERR("Failed to update element reference of " << referenceName(prop));
        }
        catch (std::exception& e) {
            FC_ERR("Failed to update element reference of " << referenceName(prop) << ": "
                                                            << e.what());
        }
        // A rebuilt sub list moved the references: the report follows them.
        ReferenceReport::remapEntries(reports[prop], list.front().firstNew, list.front().countNew);
        ReferenceReport::replace(prop, targetName, std::move(reports[prop]));
    }
    return changed;
}

}  // namespace App
