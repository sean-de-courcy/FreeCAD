// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ElementSolverBatch.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <memory>
#include <optional>
#include <sstream>

#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Parameter.h>

#include "Application.h"
#include "ComplexGeoData.h"
#include "DocumentObject.h"
#include "ElementFingerprint.h"
#include "ElementNamingUtils.h"
#include "ElementSolver.h"
#include "GeoFeature.h"
#include "MappedElement.h"
#include "PropertyGeo.h"
#include "ReferenceReport.h"

FC_LOG_LEVEL_INIT("PropertyLinks", true, true)

namespace App
{

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

// The target's named elements of one type, each with all its names. A sketch's `Internal*`
// types come from its InternalShape.
std::vector<Data::SolveInput::Element> poolOf(GeoFeature* geo, const std::string& type)
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
        names[prefix + mapped.index.toString()].push_back(mapped.name.toString());
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

// Tier 1's gap and the tolerances of tiers 2 and 3 (fork-only parameters for the tuning runs; a
// value that isn't positive and finite keeps the default).
void readTolerances(double& gap, Data::GeometryTolerances& tolerances)
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
    auto pool = [&](const std::string& type) -> const std::vector<Data::SolveInput::Element>& {
        auto it = pools.find(type);
        if (it == pools.end()) {
            it = pools.emplace(type, poolOf(geo, type)).first;
        }
        return it->second;
    };
    const std::string targetName = feature->getFullName();
    bool sourceRead = false;
    Data::Tier1Source source = Data::Tier1Source::Union;
    double gap = Data::SolveInput().gap;
    Data::GeometryTolerances tolerances;
    double diagonal = 0.0;
    std::map<std::string, std::vector<std::string>> nameMatches;  // by old name

    for (auto& [ownerName, entries] : owners) {
        std::stable_sort(entries.begin(), entries.end(), [](const auto* a, const auto* b) {
            auto na = referenceName(a->prop);
            auto nb = referenceName(b->prop);
            return na != nb ? na < nb : a->index < b->index;
        });
        bool anyMissing = std::any_of(entries.begin(), entries.end(), [](const auto* e) {
            return e->kind == SolverEntry::Kind::Missing;
        });
        if (!anyMissing) {
            continue;
        }

        auto report = [&](const SolverEntry& entry, ReferenceReport::Entry item) {
            item.index = entry.index;
            item.oldName = entry.oldName;
            item.oldIndex = entry.oldIndex;
            item.target = targetName;
            reports[entry.prop].push_back(std::move(item));
        };

        if (!sourceRead) {
            source = tier1Source();
            readTolerances(gap, tolerances);
            if (auto prop = geo->getPropertyOfGeometry()) {
                if (auto data = prop->getComplexData()) {
                    diagonal = data->getBoundBox().CalcDiagonalLength();
                }
            }
            sourceRead = true;
        }

        if (reverse) {
            // An element-map version change: index carry, verified by the saved fingerprint.
            for (const auto* entry : entries) {
                if (entry->kind != SolverEntry::Kind::Missing) {
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
                    SolverResolution resolution;
                    resolutionFor(*entry, index, name, resolution);
                    resolutions[entry->prop].push_back(resolution);
                    item.status = ReferenceReport::Status::Index;
                    item.newIndex = index;
                    item.evidence = "index carry, fingerprint equal";
                    FC_WARN(referenceName(entry->prop)
                            << "[" << entry->index << "]: " << entry->oldName << " -> " << index
                            << " (tier index, fingerprint equal)");
                }
                else {
                    item.status = ReferenceReport::Status::Broken;
                    item.evidence = !saved.isValid() ? "index carry, no fingerprint"
                        : !exists                    ? "index carry, no such element"
                                                     : "index carry, fingerprint differs";
                    if (exists) {
                        item.candidates.emplace_back(index, name);
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
        input.gap = gap;
        input.tolerances = tolerances;
        input.diagonal = diagonal;
        input.fingerprintOf = [geo](const std::string& index) {
            Data::ElementFingerprint fingerprint;
            if (!geo->getElementFingerprint(index.c_str(), fingerprint)) {
                return Data::ElementFingerprint();
            }
            return fingerprint;
        };
        for (const auto* entry : entries) {
            Data::SolveInput::Entry item;
            item.type = indexType(entry->oldIndex);
            item.policy = solvePolicy(entry->policy);
            if (entry->kind == SolverEntry::Kind::Exact) {
                item.exact = true;
                item.exactElement = entry->oldIndex;
            }
            else {
                item.oldName = entry->oldName;
                item.fingerprint = Data::ElementFingerprint::fromString(entry->oldFingerprint);
                if (item.policy == Data::SolvePolicy::Expand) {
                    FC_LOG(referenceName(entry->prop)
                           << "[" << entry->index << "]: Expand read as One until Task 2 PR 7");
                }
                else if (item.policy == Data::SolvePolicy::Equivalent) {
                    item.equivalent = equivalenceOf(*entry);
                }
                if (source != Data::Tier1Source::Overlap && !entry->oldName.empty()) {
                    auto it = nameMatches.find(entry->oldName);
                    if (it == nameMatches.end()) {
                        Data::MappedName searchName(entry->oldName);
                        std::vector<std::string> names;
                        for (const auto& match : geo->findSimilarNames(searchName)) {
                            names.push_back(match.name.toString());
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
            if (outcome.status == Data::SolveStatus::Exact) {
                continue;
            }
            ReferenceReport::Entry item;
            item.evidence = outcome.evidence;
            if (outcome.status == Data::SolveStatus::Resolved) {
                SolverResolution resolution;
                resolutionFor(entry, outcome.element, outcome.name, resolution);
                resolutions[entry.prop].push_back(resolution);
                item.status = ReferenceReport::Status::Resolved;
                item.tier = outcome.tier;
                item.newIndex = outcome.element;
                FC_WARN(referenceName(entry.prop)
                        << "[" << entry.index << "]: " << entry.oldName << " -> "
                        << outcome.element << " (tier " << outcome.tier << ", " << outcome.evidence
                        << ")");
            }
            else {
                item.status = ReferenceReport::Status::Broken;
                for (std::size_t c = 0; c < outcome.candidates.size(); ++c) {
                    item.candidates.emplace_back(outcome.candidates[c], outcome.candidateNames[c]);
                }
                FC_WARN(referenceName(entry.prop)
                        << "[" << entry.index << "]: " << entry.oldName << " broken ("
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
            changed = changed || touched
                || resolution.status == SolverResolution::Status::Resolved;
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
        ReferenceReport::replace(prop, targetName, std::move(reports[prop]));
    }
    return changed;
}

}  // namespace App
