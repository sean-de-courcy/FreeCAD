// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ElementSolverBatch.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iomanip>
#include <limits>
#include <locale>
#include <map>
#include <memory>
#include <optional>
#include <mutex>
#include <set>
#include <sstream>
#include <string_view>
#include <thread>
#include <tuple>
#include <unordered_map>

#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Parameter.h>
#include <Base/Writer.h>

#include "Application.h"
#include "ComplexGeoData.h"
#include "Datums.h"
#include "Document.h"
#include "DocumentObject.h"
#include "ElementFingerprint.h"
#include "ElementNamingUtils.h"
#include "ElementSolver.h"
#include "ElementSolverEdits.h"
#include "Expression.h"
#include "GeoFeature.h"
#include "NameTable.h"
#include "MappedElement.h"
#include "PropertyExpressionEngine.h"
#include "PropertyGeo.h"
#include "PropertyPythonObject.h"
#include "RecomputeContinuation.h"
#include "ReferenceReport.h"

FC_LOG_LEVEL_INIT("PropertyLinks", true, true)

namespace App
{

namespace
{
ElementHintsFunction elementHintsFunction = nullptr;
ElementHoldsPointFunction elementHoldsPointFunction = nullptr;
ElementHoldsPointAlongFunction elementHoldsPointAlongFunction = nullptr;
ElementSweepDirectionFunction elementSweepDirectionFunction = nullptr;
ElementUpToFacesFunction elementUpToFacesFunction = nullptr;
ElementUpToPathFunction elementUpToPathFunction = nullptr;

struct MigrationCounts
{
    int kept = 0;
    int moved = 0;
    int broken = 0;
};
// By the owner document's name: a document may be closed before the counts are reported.
std::map<std::string, MigrationCounts> migrationCounts;

// The objects edited since their document was opened (ElementSolverEdits.h), and the depth of
// solveElementReferences() calls, whose writes aren't edits.
std::map<const Document*, std::set<const DocumentObject*>> editsSinceOpen;
int solving = 0;

// The digests of one recompute (PlacementDigestScope, ElementSolverEdits.h). A digest depends on
// its object's own properties, the keys of the objects they link (IDs and document names, which
// don't change), whether the object's Placement is a source of the target (`source`) and the
// target's document (keys name another document's objects by it).
struct DigestCache
{
    enum Mode
    {
        Off,
        On,
        Verify,
    };
    struct Key
    {
        std::uintptr_t object = 0;
        std::uintptr_t doc = 0;
        bool source = false;
        bool operator<(const Key& other) const
        {
            return std::tie(object, doc, source) < std::tie(other.object, other.doc, other.source);
        }
    };
    std::mutex mutex;
    int depth = 0;
    std::thread::id owner;
    Mode mode = On;
    std::map<Key, std::uint64_t> digests;
    // Bumped by every forget: a digest made while one ran (another thread's edit) isn't kept
    std::uint64_t epoch = 0;
    // For the log at the end of the outermost scope
    std::uint64_t calls = 0;
    std::uint64_t made = 0;
    std::uint64_t reused = 0;
    std::uint64_t differed = 0;
    double seconds = 0.0;
};

DigestCache& digestCache()
{
    static DigestCache cache;
    return cache;
}

// The cache's depth, read without its mutex by forgetPlacementDigestOf()
std::atomic<int> digestDepth {0};

// An environment variable, or empty
std::string environmentValue(const char* name)
{
#ifdef _MSC_VER
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, name) != 0 || !value) {
        return {};
    }
    std::string text(value);
    std::free(value);
    return text;
#else
    const char* value = std::getenv(name);
    return value ? std::string(value) : std::string();
#endif
}

// FREECAD_CH_DIGEST_CACHE, or empty
std::string digestCacheMode()
{
    return environmentValue("FREECAD_CH_DIGEST_CACHE");
}

// The solver profile (SolverSiteTimer, ElementSolverEdits.h): on for the outermost scope's thread
// while FREECAD_CH_SOLVER_PROFILE was set at its open
struct SolverProfile
{
    std::atomic<bool> on {false};
    std::thread::id thread;
    double seconds[static_cast<int>(SolverSite::Count)] = {};
    std::uint64_t calls[static_cast<int>(SolverSite::Count)] = {};
};

SolverProfile& solverProfile()
{
    static SolverProfile profile;
    return profile;
}

// The running solveElementReferences()' measured fingerprints (batchElementFingerprint(),
// ElementSolverEdits.h), innermost first
struct BatchFingerprints
{
    const PropertyContainer* target = nullptr;
    std::map<std::string, Data::ElementFingerprint>* measured = nullptr;
    // A property of the target changed since they were measured
    bool stale = false;
    // FREECAD_CH_FINGERPRINT_SHORTCUTS=verify: each one used is measured again and compared
    bool verify = false;
    BatchFingerprints* previous = nullptr;
};
thread_local BatchFingerprints* runningBatch = nullptr;

struct BatchFingerprintsScope
{
    BatchFingerprints batch;
    BatchFingerprintsScope(const PropertyContainer* target,
                           std::map<std::string, Data::ElementFingerprint>* measured)
    {
        batch.target = target;
        batch.measured = measured;
        // FREECAD_CH_FINGERPRINT_SHORTCUTS=off: none kept
        const std::string mode = environmentValue("FREECAD_CH_FINGERPRINT_SHORTCUTS");
        batch.stale = mode == "off";
        batch.verify = mode == "verify";
        batch.previous = runningBatch;
        runningBatch = &batch;
    }
    ~BatchFingerprintsScope()
    {
        runningBatch = batch.previous;
    }
    BatchFingerprintsScope(const BatchFingerprintsScope&) = delete;
    BatchFingerprintsScope& operator=(const BatchFingerprintsScope&) = delete;
};

BatchFingerprints* batchOf(const PropertyContainer* target)
{
    for (auto batch = runningBatch; batch; batch = batch->previous) {
        if (batch->target == target) {
            return batch->stale ? nullptr : batch;
        }
    }
    return nullptr;
}

const char* solverSiteName(int site)
{
    static const char* names[] = {"updateRefs",
                                  "solve",
                                  "pass1",
                                  "pass2Frames",
                                  "pool",
                                  "measure",
                                  "solveOwner",
                                  "writeBack",
                                  "update",
                                  "updateCompare",
                                  "fingerprint",
                                  "fpResolve",
                                  "fpGet",
                                  "fpTwin",
                                  "fpUpTo",
                                  "fpClosure",
                                  "fpSources",
                                  "fpString",
                                  "held"};
    static_assert(sizeof(names) / sizeof(names[0]) == static_cast<int>(SolverSite::Count));
    return names[site];
}

// Whether this thread's recompute keeps digests now (the cache's mutex held)
bool digestCacheActive(const DigestCache& cache)
{
    return cache.depth > 0 && cache.mode != DigestCache::Off
        && cache.owner == std::this_thread::get_id();
}
}  // namespace

PlacementDigestScope::PlacementDigestScope()
{
    auto& cache = digestCache();
    std::lock_guard<std::mutex> lock(cache.mutex);
    if (cache.depth == 0) {
        cache.owner = std::this_thread::get_id();
        const std::string text = digestCacheMode();
        cache.mode = text == "off" ? DigestCache::Off
            : text == "verify"     ? DigestCache::Verify
                                   : DigestCache::On;
        cache.digests.clear();
        cache.calls = cache.made = cache.reused = cache.differed = 0;
        cache.seconds = 0.0;
        auto& profile = solverProfile();
        profile.on = false;
        if (!environmentValue("FREECAD_CH_SOLVER_PROFILE").empty()) {
            profile.thread = cache.owner;
            std::fill(std::begin(profile.seconds), std::end(profile.seconds), 0.0);
            std::fill(std::begin(profile.calls), std::end(profile.calls), 0);
            profile.on = true;
        }
    }
    else if (cache.owner != std::this_thread::get_id()) {
        return;
    }
    ++cache.depth;
    ++digestDepth;
    active = true;
}

PlacementDigestScope::~PlacementDigestScope()
{
    if (!active) {
        return;
    }
    auto& cache = digestCache();
    // Logged after the mutex is released: a console observer may change a property (a forget)
    std::uint64_t calls = 0;
    std::uint64_t made = 0;
    std::uint64_t reused = 0;
    std::uint64_t differed = 0;
    double seconds = 0.0;
    {
        std::lock_guard<std::mutex> lock(cache.mutex);
        --digestDepth;
        if (--cache.depth > 0) {
            return;
        }
        cache.digests.clear();
        calls = cache.calls;
        made = cache.made;
        reused = cache.reused;
        differed = cache.differed;
        seconds = cache.seconds;
    }
    if (calls > 0) {
        FC_LOG("placement sources: " << calls << " calls, " << seconds << " s; digests made " << made
                                     << ", reused " << reused);
    }
    auto& profile = solverProfile();
    if (profile.on.exchange(false)) {
        std::ostringstream text;
        for (int site = 0; site < static_cast<int>(SolverSite::Count); ++site) {
            if (profile.calls[site] > 0) {
                text << " " << solverSiteName(site) << " " << profile.calls[site] << "x "
                     << std::fixed << std::setprecision(4) << profile.seconds[site] << ";";
            }
        }
        FC_LOG("solver profile:" << text.str());
    }
    if (differed > 0) {
        FC_ERR("placement digests: " << differed << " kept digests differ from a fresh one");
    }
}

SolverSiteTimer::SolverSiteTimer(SolverSite which)
{
    auto& profile = solverProfile();
    if (profile.on.load(std::memory_order_relaxed) && profile.thread == std::this_thread::get_id()) {
        site = static_cast<int>(which);
        start = std::chrono::steady_clock::now().time_since_epoch().count();
    }
}

SolverSiteTimer::~SolverSiteTimer()
{
    auto& profile = solverProfile();
    if (site < 0 || !profile.on.load(std::memory_order_relaxed)) {
        return;
    }
    const auto ticks = std::chrono::steady_clock::now().time_since_epoch().count() - start;
    profile.seconds[site] += std::chrono::duration<double>(std::chrono::steady_clock::duration(ticks)).count();
    ++profile.calls[site];
}

bool batchElementFingerprint(const GeoFeature* geo,
                             const std::string& element,
                             bool& measured,
                             Data::ElementFingerprint& fingerprint)
{
    auto batch = batchOf(geo);
    if (!batch) {
        return false;
    }
    auto it = batch->measured->find(element);
    if (it == batch->measured->end()) {
        return false;
    }
    // An element getElementFingerprint() gave nothing for is kept as an invalid fingerprint
    measured = it->second.isValid();
    fingerprint = it->second;
    if (batch->verify) {
        Data::ElementFingerprint fresh;
        const bool freshMeasured = geo->getElementFingerprint(element.c_str(), fresh);
        if (freshMeasured != measured
            || (measured && fresh.toString() != fingerprint.toString())) {
            FC_ERR("fingerprint shortcuts: a kept measurement of " << geo->getFullName() << "."
                                                                   << element << " differs");
        }
        measured = freshMeasured;
        fingerprint = fresh;
    }
    return true;
}

void keepBatchElementFingerprint(const GeoFeature* geo,
                                 const std::string& element,
                                 bool measured,
                                 const Data::ElementFingerprint& fingerprint)
{
    if (auto batch = batchOf(geo)) {
        batch->measured->emplace(element,
                                 measured ? fingerprint : Data::ElementFingerprint());
    }
}

void forgetPlacementDigestOf(const PropertyContainer* container)
{
    // The running batches' measurements of the container's shape (batchElementFingerprint())
    for (auto batch = runningBatch; batch; batch = batch->previous) {
        if (container && batch->target == container) {
            batch->stale = true;
        }
    }
    if (container && digestDepth.load(std::memory_order_relaxed) > 0) {
        forgetPlacementDigest(dynamic_cast<const DocumentObject*>(container));
    }
}

void forgetPlacementDigest(const void* obj)
{
    auto& cache = digestCache();
    std::lock_guard<std::mutex> lock(cache.mutex);
    if (cache.depth == 0 || !obj) {
        return;
    }
    ++cache.epoch;
    if (cache.digests.empty()) {
        return;
    }
    const auto key = reinterpret_cast<std::uintptr_t>(obj);
    auto from = cache.digests.lower_bound(DigestCache::Key {key, 0, false});
    auto to = from;
    while (to != cache.digests.end() && to->first.object == key) {
        ++to;
    }
    cache.digests.erase(from, to);
}

void forgetEditsSinceOpen(const Document* doc)
{
    editsSinceOpen.erase(doc);
}

void noteEditSinceOpen(const DocumentObject* obj)
{
    if (obj && obj->getDocument()) {
        editsSinceOpen[obj->getDocument()].insert(obj);
    }
}

void noteChangeSinceOpen(const DocumentObject* obj, const Property* prop)
{
    // Any change, the solver's own and an output's included: a digest skips outputs by the
    // property's status, which a change can set
    forgetPlacementDigest(obj);
    const Document* doc = obj ? obj->getDocument() : nullptr;
    if (!doc || !prop || solving > 0 || doc->testStatus(Document::Restoring)
        || doc->testStatus(Document::Recomputing) || obj->isRecomputing()
        || (prop->getType() & (Prop_Output | Prop_Transient)) != 0
        || prop->testStatus(Property::Output) || prop->testStatus(Property::Transient)) {
        return;
    }
    // The element map version is the migration's own stamp
    const char* name = prop->getName();
    if (name && std::strcmp(name, "_ElementMapVersion") == 0) {
        return;
    }
    editsSinceOpen[doc].insert(obj);
}

bool editedSinceOpen(const DocumentObject* feature)
{
    if (!feature || !feature->getDocument()) {
        return false;
    }
    auto edited = [](const DocumentObject* obj) {
        auto it = editsSinceOpen.find(obj->getDocument());
        return it != editsSinceOpen.end() && it->second.count(obj) != 0;
    };
    if (edited(feature)) {
        return true;
    }
    // Another document's object may have been edited and saved before this one was opened,
    // which no record here shows: an edit (decision 217 (3), review pr475b-r3)
    const auto chain = feature->getOutListRecursive();
    return std::any_of(chain.begin(), chain.end(), [&](const DocumentObject* obj) {
        return obj && (obj->getDocument() != feature->getDocument() || edited(obj));
    });
}

void setElementHintsFunction(ElementHintsFunction function)
{
    elementHintsFunction = function;
}

void setElementHoldsPointFunction(ElementHoldsPointFunction function)
{
    elementHoldsPointFunction = function;
}

void setElementHoldsPointAlongFunction(ElementHoldsPointAlongFunction function)
{
    elementHoldsPointAlongFunction = function;
}

void setElementSweepDirectionFunction(ElementSweepDirectionFunction function)
{
    elementSweepDirectionFunction = function;
}

void setElementUpToFacesFunction(ElementUpToFacesFunction function)
{
    elementUpToFacesFunction = function;
}

void setElementUpToPathFunction(ElementUpToPathFunction function)
{
    elementUpToPathFunction = function;
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
        FC_WARN(
            "Document '" << name << "': " << count.kept + count.moved + count.broken
                         << " element references re-derived from their geometry after a "
                            "naming change: "
                         << count.moved << " moved back to their element, " << count.broken
                         << " broken (their features name them)"
        );
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

// P-beta 2 (decision 247): see the header
bool indexMadeOnly(const std::string& name, int depth)
{
    // (no text test for the flag first: a linked name may be interned, `~<ID>`)
    if (depth <= 0 || name.empty()) {
        return false;
    }
    const auto& sections = Data::MappedName::getDecodedMappedName(name);
    auto real = [](const std::string& value) {
        return !value.empty() && value != Data::EMPTY_VALUE;
    };
    auto allIndexMade = [&](const std::vector<std::string>& names) {
        return std::all_of(names.begin(), names.end(), [&](const std::string& linked) {
            return !real(linked) || indexMadeOnly(linked, depth - 1);
        });
    };
    return !sections.empty()
        && std::all_of(sections.begin(), sections.end(), [&](const auto& section) {
               if (section.opCode == "MLN" || !allIndexMade(section.connectedElements)) {
                   return false;
               }
               if (section.hasMapperFlag(Data::MAPPER_FLAG_INDEX)) {
                   return allIndexMade(section.linkedNames);
               }
               const auto& ids = section.referenceIDs;
               return std::none_of(ids.begin(), ids.end(), real)
                   && std::any_of(section.linkedNames.begin(), section.linkedNames.end(), real)
                   && allIndexMade(section.linkedNames);
           });
}

void placementSources(const GeoFeature* geo, std::vector<Data::ElementFingerprint::Source>& sources)
{
    // The time it takes, for the recompute's log line (PlacementDigestScope)
    struct Timer
    {
        std::chrono::steady_clock::time_point started = std::chrono::steady_clock::now();
        ~Timer()
        {
            const std::chrono::duration<double> spent = std::chrono::steady_clock::now() - started;
            auto& cache = digestCache();
            std::lock_guard<std::mutex> lock(cache.mutex);
            if (cache.depth > 0 && cache.owner == std::this_thread::get_id()) {
                ++cache.calls;
                cache.seconds += spent.count();
            }
        }
    } timer;
    sources.clear();
    if (!geo || !geo->isAttachedToDocument()) {
        return;
    }
    // PartDesign's types by name: App can't name them
    static const Base::Type bodyType = Base::Type::fromName("PartDesign::Body");
    static const Base::Type featureType = Base::Type::fromName("PartDesign::Feature");
    static const Base::Type primitiveType = Base::Type::fromName("PartDesign::FeaturePrimitive");
    auto isA = [](const DocumentObject* object, const Base::Type& type) {
        return !type.isBad() && object->getTypeId().isDerivedFrom(type);
    };
    // The chain: the target's out-list (11.9 F4), a Body's from its Tip
    std::vector<DocumentObject*> chain;
    const DocumentObject* top = geo;
    if (isA(geo, bodyType)) {
        auto tip = dynamic_cast<PropertyLink*>(geo->getPropertyByName("Tip"));
        top = tip ? tip->getValue() : nullptr;
        if (top) {
            chain.push_back(const_cast<DocumentObject*>(top));
        }
    }
    if (top) {
        // A link set into a cycle writes its record before the recompute reports the cycle:
        // no sources, so the record never reads rigid (decision 150)
        std::vector<DocumentObject*> out;
        try {
            out = top->getOutListRecursive();
        }
        catch (const Base::BadGraphError&) {
            return;
        }
        chain.insert(chain.end(), out.begin(), out.end());
    }
    const Document* doc = geo->getDocument();
    auto keyOf = [doc](const DocumentObject* object) {
        std::string key = std::to_string(object->getID());
        if (object->getDocument() != doc) {
            key += "@";
            key += object->getDocument()->getName();
        }
        return key;
    };
    // What the chain and the target name: up-to owners and a Split's tool (always sources,
    // 11.9 F6) and geometry (loci, 11.9 F1/F2). Every link but the attachment's names geometry
    // (decision 150: a name left out read rigid, ReviewDraftedBoxFlipped); a locus named only
    // as a mirror plane keeps no sense, the reflection is the same
    std::set<const DocumentObject*> upTo;
    std::map<const DocumentObject*, bool> named;
    std::vector<Data::ElementFingerprint::Source> vectors;
    std::vector<const DocumentObject*> namers(chain.begin(), chain.end());
    namers.push_back(geo);
    for (const DocumentObject* object : namers) {
        if (!object || !object->isAttachedToDocument()) {
            continue;
        }
        std::vector<Property*> properties;
        object->getPropertyList(properties);
        for (Property* property : properties) {
            const char* name = property->getName();
            // A vector input (a pad's custom direction, a pipe's binormal, kept in body
            // coordinates): it must turn with the part (decision 150: a second silent in the
            // closure, ReviewPadCustomDirectionFlipped, takes every input, not a list of names).
            // A vector read-only by its type or an output (a revolve's Base and Axis, made from its
            // reference axis) is made from what the closure holds. isReadOnly() reads the type
            // only, so a pad's own Direction (read-only in the editor alone) is kept, and turns
            // with the part as a direction
            if (auto value = dynamic_cast<PropertyVector*>(property); value && name) {
                if (object->isReadOnly(property)
                    || (object->getPropertyType(property) & Prop_Output) != 0) {
                    continue;
                }
                Data::ElementFingerprint::Source source;
                source.key = keyOf(object) + "." + name;
                source.locus = 'V';
                source.point = value->getValue();
                vectors.push_back(std::move(source));
                continue;
            }
            auto link = dynamic_cast<PropertyLinkBase*>(property);
            if (!link || !name || std::strcmp(name, "AttachmentSupport") == 0) {
                continue;
            }
            std::vector<DocumentObject*> linked;
            link->getLinks(linked, true);
            const std::string_view which(name);
            if (which == "UpToFace" || which == "UpToFace2" || which == "UpToShape"
                || which == "UpToShape2" || which == "Tool") {
                upTo.insert(linked.begin(), linked.end());
            }
            const bool mirror = which == "MirrorPlane";
            for (const DocumentObject* target : linked) {
                auto [at, added] = named.emplace(target, mirror);
                if (!added) {
                    at->second = at->second && mirror;
                }
            }
        }
    }
    std::set<const DocumentObject*> seen;
    std::set<const DocumentObject*> placed;  // the objects whose Placement is a source
    for (const DocumentObject* object : chain) {
        auto feature = dynamic_cast<const GeoFeature*>(object);
        if (!feature || !feature->isAttachedToDocument() || !seen.insert(object).second) {
            continue;
        }
        const std::string typeName(object->getTypeId().getName());
        const bool own = typeName.rfind("App::", 0) != 0 && !isA(object, bodyType)
            && (!isA(object, featureType) || isA(object, primitiveType));
        if (own || upTo.count(object) > 0) {
            Data::ElementFingerprint::Source source;
            source.key = keyOf(object);
            source.placement = feature->Placement.getValue();
            sources.push_back(std::move(source));
            placed.insert(object);
        }
    }
    // A primitive target's Placement is its own, not made from its base (Rv2dPrimTarget): a
    // source as in the chain
    if (isA(geo, primitiveType) && seen.insert(geo).second) {
        Data::ElementFingerprint::Source source;
        source.key = keyOf(geo);
        source.placement = geo->Placement.getValue();
        sources.push_back(std::move(source));
        placed.insert(geo);
    }
    // The origin lines and planes named as geometry: loci
    for (const auto& [object, mirror] : named) {
        auto datum = dynamic_cast<const DatumElement*>(object);
        const bool line = dynamic_cast<const Line*>(object) != nullptr;
        if (!datum || !datum->isAttachedToDocument()
            || (!line && !dynamic_cast<const Plane*>(object))) {
            continue;
        }
        Data::ElementFingerprint::Source source;
        source.key = keyOf(object);
        source.locus = line ? 'L' : (mirror ? 'M' : 'P');
        source.point = datum->getBasePoint();
        source.direction = datum->getDirection();
        source.direction.Normalize();
        sources.push_back(std::move(source));
    }
    sources.insert(sources.end(), vectors.begin(), vectors.end());
    // Nothing else changed (decision 231: input by input didn't converge, five silents): each
    // object of the chain and the target folds its other inputs into a digest. Not its Placement
    // and AttachmentOffset (the sources), its vectors (the inputs above, or made from the
    // closure), its geometry (what the record measures), its outputs and transient properties
    // (made by the recompute). A Placement is left out only where the record has it otherwise: a
    // source's, a PartDesign feature's (made from its sources), the Body's (the frame of every
    // record); an App::Link's is folded. A link folds the objects and the elements it names (its
    // saved form carries the records), the expression engine its expressions, any other property
    // its saved form
    // keepable: no property's saved form can change without a property change (a Python proxy's
    // state can)
    auto digestOf = [&](const DocumentObject* object, bool& keepable) {
        keepable = true;
        const bool source = placed.count(object) > 0;
        const bool derived = source || isA(object, featureType) || isA(object, bodyType);
        std::uint64_t digest = Data::ElementFingerprint::DigestSeed;
        auto fold = [&digest](std::string_view text) {
            Data::ElementFingerprint::foldDigest(digest, text);
            Data::ElementFingerprint::foldDigest(digest, std::string_view("\0", 1));
        };
        std::vector<Property*> properties;
        object->getPropertyList(properties);
        auto nameOf = [](const Property* property) {
            const char* name = property->getName();
            return std::string_view(name ? name : "");
        };
        std::sort(properties.begin(), properties.end(), [&nameOf](const auto* a, const auto* b) {
            return nameOf(a) < nameOf(b);
        });
        for (Property* property : properties) {
            const std::string_view name = nameOf(property);
            if (name.empty() || (derived && name == "Placement")
                || (source && name == "AttachmentOffset")
                || dynamic_cast<PropertyVector*>(property)
                || dynamic_cast<PropertyComplexGeoData*>(property)
                || (object->getPropertyType(property) & (Prop_Output | Prop_Transient)) != 0
                || property->testStatus(Property::Output)
                || property->testStatus(Property::Transient)) {
                continue;
            }
            fold(name);
            if (dynamic_cast<PropertyPythonObject*>(property)) {
                keepable = false;
            }
            if (auto engine = dynamic_cast<PropertyExpressionEngine*>(property)) {
                for (const auto& [path, expression] : engine->getExpressions()) {
                    fold(path.toString());
                    fold(expression ? expression->toString(true) : std::string());
                }
            }
            else if (auto link = dynamic_cast<PropertyLinkBase*>(property)) {
                std::vector<DocumentObject*> linked;
                std::vector<std::string> subs;
                link->getLinks(linked, true, &subs, false);
                for (const DocumentObject* target : linked) {
                    fold(target && target->isAttachedToDocument() ? keyOf(target) : std::string());
                }
                fold("|");
                for (const std::string& sub : subs) {
                    fold(sub);
                }
            }
            else {
                // Inline: a list saved to a file otherwise writes only the file's name (a
                // pattern's Spacings, a polygon's Nodes)
                Base::StringWriter writer;
                writer.setForceXML(true);
                writer.Stream().imbue(std::locale::classic());
                writer.Stream() << std::setprecision(std::numeric_limits<double>::max_digits10);
                try {
                    property->Save(writer);
                    fold(writer.getString());
                }
                catch (const Base::Exception&) {
                    fold("?");
                }
                catch (const std::exception&) {
                    fold("?");
                }
            }
        }
        return digest;
    };
    // Made once per recompute (PlacementDigestScope): kept until a property of the object changes
    auto keptDigestOf = [&](const DocumentObject* object) {
        auto& cache = digestCache();
        const DigestCache::Key key {reinterpret_cast<std::uintptr_t>(object),
                                    reinterpret_cast<std::uintptr_t>(doc),
                                    placed.count(object) > 0};
        bool keep = false;
        bool verify = false;
        std::optional<std::uint64_t> kept;
        std::uint64_t epoch = 0;
        {
            std::lock_guard<std::mutex> lock(cache.mutex);
            if (digestCacheActive(cache)) {
                auto it = cache.digests.find(key);
                if (it != cache.digests.end()) {
                    ++cache.reused;
                    if (cache.mode != DigestCache::Verify) {
                        return it->second;
                    }
                    kept = it->second;
                    verify = true;
                }
                keep = true;
                epoch = cache.epoch;
            }
        }
        bool keepable = true;
        const std::uint64_t digest = digestOf(object, keepable);
        bool differs = false;
        if (keep) {
            std::lock_guard<std::mutex> lock(cache.mutex);
            if (verify && kept && *kept != digest) {
                ++cache.differed;
                differs = true;
            }
            if (!kept) {
                ++cache.made;
            }
            if (keepable && cache.epoch == epoch && digestCacheActive(cache)) {
                cache.digests[key] = digest;
            }
        }
        if (differs) {
            FC_ERR("placement digest of " << object->getFullName() << " kept " << *kept
                                          << ", made " << digest);
        }
        return digest;
    };
    // Only beside sources: a record without them never reads rigid, and keeps its form
    std::set<const DocumentObject*> digested;
    for (const DocumentObject* object : namers) {
        if (sources.empty() || !object || !object->isAttachedToDocument()
            || !digested.insert(object).second) {
            continue;
        }
        Data::ElementFingerprint::Source source;
        source.key = keyOf(object);
        source.locus = 'D';
        source.digest = keptDigestOf(object);
        sources.push_back(std::move(source));
    }
    std::sort(sources.begin(), sources.end(), [](const auto& a, const auto& b) {
        return a.locus != b.locus ? a.locus < b.locus : a.key < b.key;
    });
    if (sources.size() > Data::ElementFingerprint::MaxSources) {
        sources.clear();
    }
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

// What tier 1 makes of a candidate that holds the old name only through a node of another type
// or a GEN section (ops#335, ops#358): `place` (geometry decides, the default) or `ancestry`
// (before ops#335)
Data::Tier1Derived tier1Derived()
{
    std::string value = solverParameters()->GetASCII("Tier1Derived", "place");
    if (value == "ancestry") {
        return Data::Tier1Derived::Ancestry;
    }
    return Data::Tier1Derived::Place;
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

// The name of an element a resolution writes: the least of its names, as index carry takes it,
// leaving out the IDX aliases P-beta gives beside an MLN name (decision 247): they are dropped at
// the producer's next naming, so a reference holding one would break then
std::string resolutionName(const std::vector<std::string>& names)
{
    if (names.empty()) {
        return {};
    }
    const bool matched = std::any_of(names.begin(), names.end(), [](const std::string& name) {
        return name.find(";MLN;") != std::string::npos;
    });
    std::string least;
    for (const auto& name : names) {
        if ((least.empty() || name < least) && !(matched && indexMadeOnly(name))) {
            least = name;
        }
    }
    return least;
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

// Whether \a entry is an attachment's support (the attachment extension's property, told by its
// name, so the link flags in PropertyLinks.h stay as they are): the one consumer whose pieces of
// a split face can break (SW19 (a)) or come back to the whole face (SW20 (3)).
bool isAttachmentSupport(const SolverEntry& entry)
{
    const char* name = entry.prop ? entry.prop->getName() : nullptr;
    return name && std::strcmp(name, "AttachmentSupport") == 0;
}

// Whether \a entry's old element was made by the reference's own target (SW19 (a), amended by
// SW20, naming-design.md): its old name's last section carries the target's tag and isn't a
// modified one (a sweep's cap, `...;SEW;...;LOW`, generated by the sweep), where a face the target
// only modified (a Pad's top through a Pocket, MOD) was made by an earlier feature.
bool madeByItsTarget(const SolverEntry& entry)
{
    // Its own sections (Data::ownSectionsOf()): the last section's tag and flags are the plain
    // form's, without the whole history the plain form writes out (ops#640)
    const std::string name =
        Data::ownSectionsOf(entry.oldName.empty() ? entry.exactName : entry.oldName);
    DocumentObject* target = entry.obj;
    if (target && !entry.prefix.empty()) {
        target = target->getSubObject(entry.prefix.c_str());
    }
    if (name.empty() || !target) {
        return false;
    }
    const Data::DecodedMappedName& decoded = Data::MappedName::getDecodedMappedName(name);
    if (decoded.empty()) {
        return false;
    }
    const Data::DecodedMappedSection& last = decoded.back();
    return last.iterationTag == std::to_string(target->getID())
        && !last.hasMapperFlag(Data::MAPPER_FLAG_MODIFIED);
}

// The record of a provisional resolution of \a entry (ops#127): the original is the entry's, with
// its saved fingerprint (ops#133), or the record's when the reference holds one already.
GuessRecord guessRecordFor(const SolverEntry& entry, const char* kind)
{
    GuessRecord guess;
    guess.kind = kind;
    if (!entry.guess.empty()) {
        guess.origName = entry.guess.origName;
        guess.origIndex = entry.guess.origIndex;
        guess.origFingerprint = entry.guess.origFingerprint;
    }
    else {
        guess.origName = entry.oldName.empty() ? entry.exactName : entry.oldName;
        guess.origIndex = entry.oldIndex;
        guess.origFingerprint = entry.oldFingerprint;
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
    // The target's frame moved since the record (ops#557): the local shape and its names can be
    // as they were while the elements traded places globally. solveOwner() judges the hit against
    // the old global place, and a part moved as one piece with another edit at both places
    // (decision 234).
    if (entry.frame || entry.turned) {
        return true;
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
    // A twin (ops#360, PR 340 round 3) that moved may have traded names with another twin that
    // moved too: nothing at its old place, solveOwner() compares the twins' distances. A marked
    // far cap may have taken another's name from a reordered up-to shell (ops#386, PR 366 round
    // 2): solveOwner() checks that it holds its old centre. Any marked piece may have, while the
    // pieces slid onto the next face (round 3): solveOwner() checks that it overlaps its old place.
    // Read in the name's own sections (Data::ownSectionsOf()): the three tests read top-level
    // sections' flags and lists, and a marked cap's one mark through its own sections, so they
    // answer as for the plain form. Every exact reference with a record comes here at every
    // recompute; the plain form of one face of the replica's Case Lid was 4.9e8 characters (ops#640)
    const std::string plain = Data::ownSectionsOf(entry.exactName);
    // An ordered hit saved among two twins or more that holds its old place (PR 390 round 2k,
    // decision 241): a lone crossing may have taken its gone twin's role exactly there.
    // solveOwner() counts its twins
    if (saved.twinCount >= 2 && Data::isOrderedName(plain)
        && Data::atSamePlace(saved, now, diagonal, tolerances, distance)) {
        return true;
    }
    return !Data::atSamePlace(saved, now, diagonal, tolerances, distance)
        && (occupied() || Data::isOrderedName(plain) || Data::isMarkedCapName(plain)
            || Data::isMarkedPieceName(plain));
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

// Whether \a motion moves anything (ops#557, decision 218): its position beyond ε (\a distance
// times max(1, \a diagonal)) or its rotation beyond \a angle. A frame or a chain that didn't move
// leaves the record as it is.
bool movesFrame(const Base::Placement& motion, double diagonal, double angle, double distance)
{
    double q0 = 0.0;
    double q1 = 0.0;
    double q2 = 0.0;
    double q3 = 1.0;
    motion.getRotation().getValue(q0, q1, q2, q3);
    const double turn = 2.0 * std::acos(std::min(1.0, std::abs(q3)));
    return motion.getPosition().Length() > distance * std::max(1.0, diagonal) || turn > angle;
}

// Whether \a geo's shape is its old one under a new frame (ops#557): a PartDesign feature's
// Placement set in its execute before the shape is made again (positionByPrevious()), which
// Part::Feature::onChanged() passes on to the old shape with the Shape marked NoRecompute. A frame
// move judged on it would compare the old shape with the old place, and keep and refresh what the
// new shape trades.
bool shapeAwaitsFrame(const GeoFeature* geo)
{
    const PropertyComplexGeoData* prop = geo->getPropertyOfGeometry();
    return geo->placementIsDerived() && geo->isRecomputing() && prop
        && prop->testStatus(Property::NoRecompute);
}

// A reference's record as the solve reads it: mapped to where the element is now when the
// target's chain moved as one piece (decision 218, the entry's rigid motion)
Data::ElementFingerprint recordOf(const SolverEntry& entry, const std::string& text, double angle)
{
    auto record = Data::ElementFingerprint::fromString(text);
    if (record.isValid() && entry.rigid) {
        record = record.transformed(*entry.rigid, angle);
    }
    return record;
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

// The tag obj's own names carry: a studio step's are its owner's ID (FreeCAD-CH ops#654 S2,
// notes/stored-tags.md 3), read by name so that App knows no PartDesign class
long namingTagOf(const DocumentObject* obj)
{
    auto owner = freecad_cast<PropertyLink*>(obj->getPropertyByName("StudioOwner"));
    if (owner && owner->getValue()) {
        return owner->getValue()->getID();
    }
    return obj->getID();
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

// What two names must share to be twins (Data::isTwinName()), read off the text without
// decoding it: the number of sections and each section's reference IDs, iteration tag and
// element type, which the twin test compares exactly. The fields are read as MappedName's
// decoder reads them (a character after the escape is no delimiter, one escape comes off, an
// empty or `_` last item is none), so names the test calls twins always share the key.
// Decoding every name of the map for each reference made creating references about 8.5 times
// slower on a 372-edge model (PR 379 round 1).
std::string twinKey(std::string_view name)
{
    std::string key;
    std::vector<std::string> items;
    std::string item;
    int field = 0;
    int escapeLevel = 0;
    bool pending = false;
    auto finishField = [&](bool endOfSection) {
        if (!item.empty() && item != Data::EMPTY_VALUE) {
            items.push_back(item);
        }
        switch (field) {
            case Data::SECTION_REFERENCE_ID_INDEX:
                for (const auto& id : items) {
                    key += id;
                    key += *Data::SUB_SECTION_LIST_DELIMINATOR;
                }
                break;
            case Data::SECTION_ITERATION_TAG_INDEX:
                key += items.empty() ? std::string(Data::EMPTY_VALUE) : items.front();
                break;
            case Data::SECTION_ELEMENT_TYPE_INDEX:
                key += items.empty() || items.front().empty() ? *Data::EMPTY_VALUE
                                                              : items.front().front();
                break;
            default:
                break;
        }
        key += *Data::SECTION_SUB_DELIMINATOR;
        items.clear();
        item.clear();
        if (endOfSection) {
            key += *Data::NAME_SECTION_DELIMINATOR;
            field = 0;
        }
        else {
            ++field;
        }
    };
    for (char c : name) {
        if (escapeLevel == 0) {
            if (c == *Data::SECTION_SUB_DELIMINATOR || c == *Data::NAME_SECTION_DELIMINATOR) {
                finishField(c == *Data::NAME_SECTION_DELIMINATOR);
                pending = false;
                continue;
            }
            if (c == *Data::SUB_SECTION_LIST_DELIMINATOR) {
                items.push_back(item);
                item.clear();
                pending = false;
                continue;
            }
        }
        pending = true;
        if (c == *Data::SUB_SECTION_ESCAPE_CHAR) {
            if (++escapeLevel == 1) {
                continue;
            }
        }
        else {
            escapeLevel = 0;
        }
        item += c;
    }
    if (pending) {
        finishField(true);
    }
    return key;
}

// A name with its own sections in full and the names they embed left as the map holds them
// (Data::ownSectionsOf()). twinKey() reads only fields that hold no embedded name (each top-level
// section's reference IDs, iteration tag and element type), so this form has the plain form's
// key, at the cost of the name's own text instead of its whole history's. On the replica's Case
// Lid after its circular pattern, the plain forms of every edge's names, built once per
// referenced edge, took 129 s per edge of a chamfer's link assignment, and one face's name took
// gigabytes (ops#640).
std::string ownSections(const std::string& name)
{
    return Data::ownSectionsOf(name);
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
                    else if (!held(resolution->sub, resolution->shadow)) {
                        // One sub: an element another reference holds isn't written again (the
                        // Opus verification of fork PR 249 round 1, finding 3)
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
    // The solver's own writes aren't edits (ElementSolverEdits.h)
    ++solving;
    struct SolvingGuard
    {
        ~SolvingGuard()
        {
            --solving;
        }
    } solvingGuard;
    SolverSiteTimer solveTimer(SolverSite::Solve);

    // Pass 1: the exact lookup, per property.
    SolverBatch batch;
    batch.feature = feature;
    batch.reverse = reverse;
    batch.notify = notify;
    std::optional<SolverSiteTimer> pass1Timer(std::in_place, SolverSite::Pass1);
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

    pass1Timer.reset();

    // Pass 2. Keep the references to feature's elements, by owner.
    std::optional<SolverSiteTimer> framesTimer(std::in_place, SolverSite::Pass2Frames);
    std::map<std::string, std::vector<const SolverEntry*>> owners;  // by full name
    // The target's frame now and the solver's tolerances, for the entries' frames (ops#557): read
    // at the first record that has a frame
    bool frameRead = false;
    std::optional<Base::Placement> frameNow;
    double frameDiagonal = 0.0;
    Data::GeometryTolerances frameTolerances;
    double frameDistance = Data::SolveInput().continuationDistance;
    const std::string framedVersion = std::to_string(Data::ElementFingerprint::VersionWithFrame)
        + "|";
    const bool targetIsBody = geo->getTypeId().isDerivedFrom(Base::Type::fromName("PartDesign::Body"));
    bool sourcesRead = false;
    std::vector<Data::ElementFingerprint::Source> sourcesNow;
    for (auto& entry : batch.entries) {
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
        // Whether the target's frame moved since the record, for every entry (a missing one's
        // picks are judged by it too): the reference's record, a snap-back probe's original
        const std::string& record = entry.guessed ? entry.guess.origFingerprint
                                                  : entry.oldFingerprint;
        if (record.rfind(framedVersion, 0) == 0) {
            if (!frameRead) {
                frameRead = true;
                const PropertyComplexGeoData* prop = geo->getPropertyOfGeometry();
                if (const Data::ComplexGeoData* data = prop ? prop->getComplexData() : nullptr) {
                    frameNow = data->getPlacement();
                    frameDiagonal = data->getBoundBox().CalcDiagonalLength();
                    double unusedGap = 0.0;
                    readTolerances(unusedGap, frameTolerances, frameDistance);
                }
            }
            if (frameNow) {
                // The chain moved as one piece (decision 218): the record is read mapped to where
                // the element is now, and the frame's check (211) is skipped. A feature-held
                // record maps by its frames, a Body-held one (body coordinates) by the motion
                const auto saved = Data::ElementFingerprint::fromString(record);
                std::optional<Data::ElementFingerprint::PieceMotion> piece;
                if (saved.isValid() && !saved.sources.empty() && (saved.frame || targetIsBody)) {
                    if (!sourcesRead) {
                        sourcesRead = true;
                        placementSources(geo, sourcesNow);
                    }
                    piece = Data::ElementFingerprint::pieceMotion(
                        saved.sources,
                        sourcesNow,
                        frameDistance * std::max(1.0, frameDiagonal),
                        frameTolerances.angle
                    );
                }
                auto moves = [&](const Base::Placement& placement) {
                    return movesFrame(placement, frameDiagonal, frameTolerances.angle, frameDistance);
                };
                if (piece && moves(piece->motion)) {
                    // The rigid follow is off for the beta (decision 237, after the closure's
                    // eighth silent: a record taken early, its sources from the edited model, read
                    // "nothing else changed"): no record is read mapped by the motion. Where the
                    // frame moved, the frame rule judges it (211 with 236's guard: a twin where it
                    // was breaks). Where it stayed (an AttachmentOffset, a Body-held record),
                    // anything where the element was breaks, and nothing there leaves it to today's
                    // rules
                    const Base::Placement old = saved.frame
                        ? frameNow->inverse() * *saved.frame
                        : Base::Placement();
                    if (saved.frame && moves(old)) {
                        entry.frame = old;
                    }
                    else {
                        entry.turned = old;
                        entry.turnMotion = piece->motion;
                        entry.turnFollowed = false;
                    }
                }
                else if (saved.isValid() && saved.frame) {
                    const Base::Placement turned = frameNow->inverse() * *saved.frame;
                    if (moves(turned)) {
                        if (saved.sources.empty()) {
                            // No sources (a link cycle at the write, a Body without a Tip,
                            // 10.11.7 F5): anything where it was breaks, no keep (decision 150)
                            entry.turned = turned;
                            entry.turnMotion = turned;
                            entry.turnFollowed = false;
                        }
                        else {
                            entry.frame = turned;
                        }
                    }
                }
            }
            // The old shape under the new frame: the update after the shape is made judges the
            // move, with the record as it was (its refresh is skipped too)
            if ((entry.frame || entry.rigid || entry.turned) && shapeAwaitsFrame(geo)) {
                entry.frame.reset();
                entry.rigid.reset();
                entry.turned.reset();
                continue;
            }
        }
        owners[entry.owner->getFullName()].push_back(&entry);
    }
    framesTimer.reset();

    std::map<const PropertyLinkBase*, std::vector<SolverResolution>> resolutions;
    std::map<const PropertyLinkBase*, std::vector<ReferenceReport::Entry>> reports;
    std::map<std::string, std::vector<Data::SolveInput::Element>> pools;  // by type
    std::map<std::string, std::string> mapForms;  // plain name -> the map's form (ops#6)
    auto pool = [&](const std::string& type) -> const std::vector<Data::SolveInput::Element>& {
        auto it = pools.find(type);
        if (it == pools.end()) {
            SolverSiteTimer poolTimer(SolverSite::Pool);
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
    Data::Tier1Derived derived = Data::Tier1Derived::Place;
    double gap = Data::SolveInput().gap;
    Data::GeometryTolerances tolerances;
    double continuationDistance = Data::SolveInput().continuationDistance;
    // The guess rules' switches (ops#127, N2 5.1), on by default
    bool guess = true;
    bool guessNoStructure = true;
    bool guessAnySource = false;
    // The exact place (ops#394), on by default
    bool exactPlace = true;
    // T1 and G2' (ops#167), T1' (ops#173), on by default
    bool sameMaker = true;
    bool sameSource = true;
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
    // And the write-back's records' (batchElementFingerprint())
    BatchFingerprintsScope batchFingerprints(geo, measured.get());
    auto fingerprintOf = [geo, measured](const std::string& index) {
        auto it = measured->find(index);
        if (it == measured->end()) {
            SolverSiteTimer measureTimer(SolverSite::Measure);
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
                name = resolutionName(element.names);
            }
        }
        return mapForm(name);
    };
    // A Missing reference's index carry, and the elements at its saved place when the carry
    // fails (ops#475)
    struct MissingPlace
    {
        Data::ElementFingerprint saved;
        Data::ElementFingerprint now;
        bool exists = false;
        bool carried = false;
        std::optional<std::vector<std::string>> places;
        bool indexAtPlace = false;
        // The one element at the place, the index's own not there too
        std::string one() const
        {
            return places && places->size() == 1 && !indexAtPlace ? places->front() : std::string();
        }
    };
    auto missingPlace = [&](const SolverEntry& entry) {
        MissingPlace place;
        const std::string& index = entry.oldIndex;
        place.exists = geo->getElementFingerprint(index.c_str(), place.now);
        place.saved = recordOf(entry, entry.oldFingerprint, tolerances.angle);
        if (place.saved.isValid() && entry.frame) {
            place.saved = place.saved.transformed(*entry.frame, tolerances.angle);  // ops#557
        }
        place.carried = place.exists && place.saved.isValid()
            && fingerprintsAgree(place.saved, place.now, diagonal);
        if (!place.carried && place.saved.isValid()) {
            place.places = elementsAt(place.saved, index, false);
            place.indexAtPlace = place.exists
                && Data::atSamePlace(place.saved, place.now, diagonal, tolerances, continuationDistance);
        }
        return place;
    };
    // OCCT's storage order moves no element and keeps their count: where a migration only
    // reorders, every Missing reference to the feature keeps an index that exists and, with a
    // saved fingerprint, keeps its element there or finds its one element at its place, and every
    // exact reference has an element at its saved place. When one doesn't, the migration
    // recompute had an edit, which may have moved another element onto a saved place (the attack
    // set's slides, review pr475b-s-r1's remove-slides): then no Missing reference is kept by its
    // place (ops#475). An edit the references don't show is caught by editedSinceOpen() below.
    // Read once, after the tolerances.
    std::optional<bool> placesHold;
    // editedSinceOpen(feature), read once
    std::optional<bool> edited;
    auto featureEdited = [&]() {
        if (!edited) {
            edited = editedSinceOpen(feature);
        }
        return *edited;
    };
    auto editedBy = [&](const SolverEntry& entry) {
        if (entry.guessed) {
            return false;
        }
        if (entry.kind == SolverEntry::Kind::Exact) {
            // Nothing where it was, neither its element nor another (a reorder empties no place;
            // a name that moved to another element is rule 3's, not an edit)
            auto saved = Data::ElementFingerprint::fromString(entry.oldFingerprint);
            Data::ElementFingerprint now;
            if (!saved.isValid() || !geo->getElementFingerprint(entry.oldIndex.c_str(), now)
                || Data::atSamePlace(saved, now, diagonal, tolerances, continuationDistance)) {
                return false;
            }
            auto others = elementsAt(saved, entry.oldIndex, true);
            return others && others->empty();
        }
        MissingPlace place = missingPlace(entry);
        return !place.exists || (place.saved.isValid() && !place.carried && place.one().empty());
    };
    auto missingPlacesHold = [&]() {
        if (!placesHold) {
            placesHold = true;
            for (const auto& owner : owners) {
                for (const auto* entry : owner.second) {
                    if (editedBy(*entry)) {
                        placesHold = false;
                        return false;
                    }
                }
            }
        }
        return *placesHold;
    };

    // Rule PT (ops#549): the features this target's shape is built on that can pass their base
    // through, read once. A failure among them puts every entry under the veto (PT1: kept only
    // at the saved place or covering it); a suppression only an entry whose record was taken
    // with another set suppressed (PS, a switch: PT1s, within it too). A record taken in the
    // current world is judged by the ordinary rules.
    enum class PassThrough
    {
        None,
        Failure,
        Switch
    };
    std::optional<std::vector<RecomputeContinuation::ChainFeature>> chain;
    std::vector<std::pair<long, bool>> chainWorld;
    const DocumentObject* chainFailure = nullptr;
    auto readChain = [&]() -> const std::vector<RecomputeContinuation::ChainFeature>& {
        if (!chain) {
            chain.emplace();
            if (auto rule = recomputeContinuation()) {
                rule->shapeInputChain(feature, *chain);
            }
            for (const auto& link : *chain) {
                if (link.failed && !chainFailure) {
                    chainFailure = link.object;
                }
                chainWorld.emplace_back(link.object->getID(), link.suppressed);
            }
        }
        return *chain;
    };
    // Per entry, read once: the record's marks can list thousands of objects
    std::map<const SolverEntry*, PassThrough> passThroughs;
    auto passThroughOf = [&](const SolverEntry& entry) {
        if (readChain().empty()) {
            return PassThrough::None;
        }
        if (chainFailure) {
            return PassThrough::Failure;
        }
        auto [it, added] = passThroughs.emplace(&entry, PassThrough::None);
        if (added) {
            const auto saved = Data::ElementFingerprint::fromString(entry.oldFingerprint);
            if (Data::passThroughWorldSwitched(saved.marks, chainWorld)) {
                it->second = PassThrough::Switch;
            }
        }
        return it->second;
    };
    // PT1 or PT1s for the pick `index` of `entry`, under `rule`. Any pick at the saved place.
    // Covering or within the saved element only for the saved name's own element (tier 0: the
    // same element as the feature changed it; review saa46-r1, 4); covering it, it holds the
    // saved inside point (r2); within it, no other element of its type lies on the saved surface
    // or curve inside the saved extent (a split or an island is no proof).
    auto passThroughKeeps = [&](const SolverEntry& entry, PassThrough rule, const std::string& index) {
        const auto saved = Data::ElementFingerprint::fromString(entry.oldFingerprint);
        const auto& now = fingerprintOf(index);
        if (!saved.isValid() || !now.isValid()) {
            return false;
        }
        if (Data::atSamePlace(saved, now, diagonal, tolerances, continuationDistance)) {
            return true;
        }
        if (entry.kind != SolverEntry::Kind::Exact || index != entry.oldIndex) {
            return false;
        }
        const double eps = continuationDistance * std::max(1.0, diagonal);
        if (Data::passThroughKeeps(saved, now, diagonal, tolerances, continuationDistance, false)) {
            const auto point = saved.inside ? saved.inside : saved.center;
            return point && elementHoldsPointFunction
                && elementHoldsPointFunction(geo, index.c_str(), *point, eps);
        }
        if (rule != PassThrough::Switch
            || !Data::passThroughKeeps(saved, now, diagonal, tolerances, continuationDistance, true)) {
            return false;
        }
        const PropertyComplexGeoData* prop = geo->getPropertyOfGeometry();
        const Data::ComplexGeoData* data = prop ? prop->getComplexData() : nullptr;
        if (!data) {
            return false;
        }
        const std::string type = indexType(index);
        const unsigned long count = data->countSubElements(type.c_str());
        for (unsigned long k = 1; k <= count; ++k) {
            const std::string other = type + std::to_string(k);
            if (other != index
                && Data::passThroughKeeps(saved,
                                          fingerprintOf(other),
                                          diagonal,
                                          tolerances,
                                          continuationDistance,
                                          true)) {
                return false;
            }
        }
        return true;
    };
    // The veto's evidence: the nearest feature that failed, or whose suppression changed since
    // the record
    auto passThroughEvidence = [&](const SolverEntry& entry, PassThrough rule) {
        if (rule == PassThrough::Failure) {
            return "'" + std::string(chainFailure->Label.getValue())
                + "' failed and passes its base through: kept only where it was";
        }
        const auto saved = Data::ElementFingerprint::fromString(entry.oldFingerprint);
        for (const auto& link : readChain()) {
            if (Data::passThroughWorldSwitched(saved.marks, {{link.object->getID(), link.suppressed}})) {
                return "'" + std::string(link.object->Label.getValue()) + "' was "
                    + (link.suppressed ? "suppressed" : "unsuppressed")
                    + " since the reference was taken: kept only where it was";
            }
        }
        return std::string("a suppression changed since the reference was taken: kept only where "
                           "it was");
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
        // A guessed reference whose original's name gives another element again has a probe,
        // which may snap it back (ops#127, ops#133).
        bool anyGuessed = std::any_of(entries.begin(), entries.end(), [](const auto* e) {
            return e->guessed;
        });
        // An owner with only exact references is solved only if one of them has a saved
        // fingerprint that its element no longer agrees with: moved, or maybe split. A reverse
        // update checks every one with a fingerprint (ops#103), and every one whose name now
        // gives another element than its stored index (ops#116).
        auto exactMayNeedSolving = [&entries, reverse]() {
            return std::any_of(entries.begin(), entries.end(), [reverse](const auto* e) {
                return e->kind == SolverEntry::Kind::Exact && !e->guessed
                    && (!e->oldFingerprint.empty()
                        || (reverse && !e->storedIndex.empty() && e->storedIndex != e->oldIndex));
            });
        };
        // Under rule PT an entry the batch would skip is checked too: a hit held by its name alone
        // (no fingerprint, moved alone, unmeasurable) is what the veto is for (ops#549)
        const bool ownerPassThrough = std::any_of(entries.begin(), entries.end(), [&](const auto* e) {
            return passThroughOf(*e) != PassThrough::None;
        });
        if (!anyMissing && !anyGuessed && !exactMayNeedSolving() && !ownerPassThrough) {
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
            derived = tier1Derived();
            readTolerances(gap, tolerances, continuationDistance);
            guess = solverParameters()->GetBool("Guess", true);
            guessNoStructure = solverParameters()->GetBool("GuessNoStructure", true);
            // G2 without the same-source test (N3 5.2), for comparison runs
            guessAnySource = solverParameters()->GetBool("GuessAnySource", false);
            // The one element at the saved place, whatever lies within tier 3's gap (ops#394)
            exactPlace = solverParameters()->GetBool("ExactPlace", true);
            // Tier 1 and G2 only from the old element's maker (ops#167), off for comparison runs
            sameMaker = solverParameters()->GetBool("Tier1SameMaker", true);
            // Tier 1 only from elements that kept the old element's sources (ops#173), off for
            // comparison runs
            sameSource = solverParameters()->GetBool("Tier1SameSource", true);
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
        // Per guessed reference, the element its original's name gives, whether or not it snaps
        // back (ops#138)
        std::map<std::pair<const PropertyLinkBase*, int>, std::string> originalNow;
        auto isOriginalNow = [&originalNow](const SolverEntry& entry, const std::string& element) {
            auto it = originalNow.find({entry.prop, entry.index});
            return it != originalNow.end() && it->second == element;
        };
        if (anyGuessed) {
            // The probes (ops#133): the original's name gives an element again. The reference
            // snaps back to it only if it is the original as saved, its fingerprint agreeing
            // with the record's. A piece of the original that kept the name (the pick is
            // another piece), the original moved or changed, or an unmeasurable one: the pick
            // and its record stand, and the reference is solved as the element it holds. A
            // record saved before ops#133 has no original fingerprint: a piece's never snaps
            // back by name, the others do as they did. A reverse update leaves it for the next.
            std::set<std::pair<const PropertyLinkBase*, int>> snapped;
            for (const auto* entry : entries) {
                if (!entry->guessed || reverse) {
                    continue;
                }
                if (!entry->oldIndex.empty()) {
                    originalNow[{entry->prop, entry->index}] = entry->oldIndex;
                }
                bool back = false;
                // (read mapped when the chain moved as one piece, decision 218)
                const auto original = recordOf(*entry, entry->guess.origFingerprint, tolerances.angle);
                if (!original.isValid()) {
                    // By its name alone: not on a pass-through (ops#549)
                    back = entry->guess.origFingerprint.empty() && entry->guess.kind != "piece"
                        && entry->guess.kind != "equivalent"
                        && passThroughOf(*entry) == PassThrough::None;
                }
                else if (entry->turned || entry->frame) {
                    // The target's frame moved, or the part moved as one piece with another edit
                    // (ops#557): no snap-back. Where it was, a part turned onto itself has the
                    // original's twin under its name (review pr557o-r2f); the element held is
                    // judged as an entry of its own, with 211's guard or the break
                    back = false;
                }
                else {
                    const auto& now = fingerprintOf(entry->oldIndex);
                    back = now.isValid() && fingerprintsAgree(original, now, diagonal);
                }
                if (!back) {
                    FC_LOG(
                        referenceName(entry->prop)
                        << "[" << entry->index << "]: the original " << entry->guess.origIndex
                        << "'s name gives " << entry->oldIndex << ", not the original as saved; "
                        << entry->guessedIndex << " is kept"
                    );
                    continue;
                }
                // The original is back: the reference snaps back to it, its record goes and its
                // fingerprint is measured anew.
                SolverResolution resolution;
                resolutionFor(*entry, entry->oldIndex, entry->exactName, resolution);
                resolutions[entry->prop].push_back(resolution);
                snapped.emplace(entry->prop, entry->index);
                FC_LOG(
                    referenceName(entry->prop)
                    << "[" << entry->index << "]: " << entry->guessedIndex << " -> "
                    << entry->oldIndex << " (the original " << entry->guess.origIndex << " is back)"
                );
            }
            entries.erase(
                std::remove_if(
                    entries.begin(),
                    entries.end(),
                    [&snapped](const auto* e) {
                        return e->guessed || snapped.count({e->prop, e->index}) > 0;
                    }
                ),
                entries.end()
            );
            anyGuessed = false;
            anyMissing = std::any_of(entries.begin(), entries.end(), [](const auto* e) {
                return e->kind == SolverEntry::Kind::Missing;
            });
            if (!anyMissing && !exactMayNeedSolving() && !ownerPassThrough) {
                continue;
            }
        }
        if (!anyMissing && !reverse) {
            // Every entry, not up to the first: each unmeasurable one is logged.
            bool needed = false;
            for (const auto* e : entries) {
                if (e->kind != SolverEntry::Kind::Exact) {
                    continue;
                }
                // Rule PT: solved unless its hit stands by PT1 (or PT1s); the veto after
                // solveOwner() judges the outcome (ops#549)
                if (const auto rule = passThroughOf(*e); rule != PassThrough::None) {
                    if (!passThroughKeeps(*e, rule, e->oldIndex)) {
                        needed = true;
                    }
                    continue;
                }
                if (e->oldFingerprint.empty()) {
                    continue;
                }
                const auto saved = recordOf(*e, e->oldFingerprint, tolerances.angle);
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
                if (entry->kind != SolverEntry::Kind::Exact) {
                    continue;
                }
                // The target's frame moved (ops#557): the element is looked for where it was
                // globally, the record mapped into the current frame
                auto saved = recordOf(*entry, entry->oldFingerprint, tolerances.angle);
                if (saved.isValid() && entry->frame) {
                    saved = saved.transformed(*entry->frame, tolerances.angle);
                }
                const std::string& hit = entry->oldIndex;
                // Rule PT: kept only by PT1 (or PT1s), never by its name alone (ops#549)
                if (const auto rule = passThroughOf(*entry); rule != PassThrough::None) {
                    if (passThroughKeeps(*entry, rule, hit)) {
                        countReferenceMigration(entry->owner, MigrationOutcome::Kept);
                        continue;
                    }
                    SolverResolution resolution;
                    migrationBrokenFor(*entry, resolution);
                    resolutions[entry->prop].push_back(resolution);
                    ReferenceReport::Entry item;
                    item.status = ReferenceReport::Status::Broken;
                    item.evidence = passThroughEvidence(*entry, rule);
                    item.candidates.emplace_back(hit, nameAt(hit));
                    item.candidateRoles.emplace_back("pass-through");
                    item.candidateDistances.push_back(std::numeric_limits<double>::quiet_NaN());
                    FC_LOG(referenceName(entry->prop) << "[" << entry->index << "]: "
                                                      << entry->exactName << " broken ("
                                                      << item.evidence << ")");
                    countReferenceMigration(entry->owner, MigrationOutcome::Broken);
                    report(*entry, std::move(item));
                    continue;
                }
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
                    FC_LOG(
                        referenceName(entry->prop)
                        << "[" << entry->index << "]: " << entry->exactName << " broken ("
                        << item.evidence << ", candidates: " << hit << ")"
                    );
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
                const bool agrees
                    = hitAgrees(*entry, saved, now, diagonal, tolerances, continuationDistance);
                // A part moved as one piece with another edit breaks (decisions 234 and 236),
                // with what sits where it was; without sources, only where anything sits there
                std::optional<std::vector<std::string>> oldPlaces;
                bool twoPlaces = false;
                if (entry->turned) {
                    const auto old = Data::ElementFingerprint::fromString(entry->oldFingerprint)
                                         .transformed(*entry->turned, tolerances.angle);
                    oldPlaces = elementsAt(old, hit, false);
                    const bool hitThere
                        = Data::atSamePlace(old, now, diagonal, tolerances, continuationDistance);
                    twoPlaces = entry->turnFollowed || !oldPlaces || !oldPlaces->empty() || hitThere;
                }
                if (agrees && !twoPlaces) {
                    countReferenceMigration(entry->owner, MigrationOutcome::Kept);
                    continue;
                }
                const std::string& stored = entry->storedIndex;
                auto places = twoPlaces ? oldPlaces : elementsAt(saved, hit, false);
                if (!twoPlaces && hit == stored && (!places || places->empty())) {
                    // The name didn't move and nothing sits where its element was: it moved
                    // alone (an edit before the migration), kept as ops#105 and rule 1 keep it
                    countReferenceMigration(entry->owner, MigrationOutcome::Kept);
                    continue;
                }
                std::string pick;
                if (!twoPlaces && places && places->size() == 1) {
                    pick = places->front();
                }
                else if (!twoPlaces && places && places->size() > 1
                         && std::find(places->begin(), places->end(), stored) != places->end()) {
                    pick = stored;  // rule 2: among coincident elements, the stored index
                }
                ReferenceReport::Entry item;
                const std::string& oldName = entry->exactName;
                if (!pick.empty() && entry->guess.empty() && indexMadeOnly(oldName)) {
                    // P-beta 2 (decision 247): a name made only of IDX sections is no name, so it
                    // can't have moved: kept by its place, with no record or warning
                    SolverResolution resolution;
                    resolutionFor(*entry, pick, nameAt(pick), resolution);
                    resolutions[entry->prop].push_back(resolution);
                    FC_LOG(
                        referenceName(entry->prop)
                        << "[" << entry->index << "]: " << oldName << " -> " << pick
                        << " (migration: an index-made name, kept by its place)"
                    );
                    countReferenceMigration(entry->owner, MigrationOutcome::Kept);
                    continue;
                }
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
                    FC_LOG(
                        referenceName(entry->prop)
                        << "[" << entry->index << "]: " << oldName << " -> " << pick << " ("
                        << item.evidence << ", not " << hit << ")"
                    );
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
                    FC_LOG(
                        referenceName(entry->prop)
                        << "[" << entry->index << "]: " << oldName << " broken (" << item.evidence
                        << ", candidates: " << joinCandidates(candidates) << ")"
                    );
                    countReferenceMigration(entry->owner, MigrationOutcome::Broken);
                }
                report(*entry, std::move(item));
            }
            // Missing references: index carry, verified by the saved fingerprint. When it fails,
            // the one element at the saved place (ops#475): OCCT's storage order differs between
            // platforms, so a file saved on one may have the element at another index on the
            // other. The index's own element at the place, or several there, break it, and so
            // does another Missing reference not at its place (missingPlacesHold).
            for (const auto* entry : entries) {
                if (entry->kind != SolverEntry::Kind::Missing) {
                    continue;
                }
                const std::string& index = entry->oldIndex;
                const MissingPlace place = missingPlace(*entry);
                const bool exists = place.exists;
                const auto& saved = place.saved;
                const auto& places = place.places;
                const bool indexAtPlace = place.indexAtPlace;
                std::string name;
                for (const auto& element : pool(indexType(index))) {
                    if (element.index == index && !element.names.empty()) {
                        name = resolutionName(element.names);
                    }
                }
                // A part moved as one piece with another edit breaks (decisions 234 and 236);
                // without sources, only where anything sits where it was
                bool turnedThere = false;
                if (entry->turned && saved.isValid()) {
                    const auto old = Data::ElementFingerprint::fromString(entry->oldFingerprint)
                                         .transformed(*entry->turned, tolerances.angle);
                    const auto others = elementsAt(old, index, true);
                    turnedThere = entry->turnFollowed || !others || !others->empty()
                        || (exists
                            && Data::atSamePlace(old, place.now, diagonal, tolerances, continuationDistance));
                }
                ReferenceReport::Entry item;
                const bool carried = place.carried && !turnedThere;
                const std::string carryEvidence = !saved.isValid() ? "index carry, no fingerprint"
                    : !exists      ? "index carry, no such element"
                    : turnedThere ? "index carry, the part moved as one piece with another edit"
                                  : "index carry, fingerprint differs";
                std::string pick = place.one();
                // Why the one element at the place isn't taken (decision 217), else empty
                std::string refusal;
                if (!pick.empty()) {
                    if (turnedThere) {
                        refusal = "but the part moved as one piece with another edit";
                    }
                    else if (entry->frame) {
                        // Where it was, a part turned onto itself has a twin (decision 236)
                        refusal = "but the target's frame moved";
                    }
                    else if (entry->owner && entry->owner->getDocument() != feature->getDocument()) {
                        // The consumer pass: the feature's file may have had its own edits
                        refusal = "but it is another document's";
                    }
                    else if (!missingPlacesHold()) {
                        refusal = "but the migration had an edit";
                    }
                    else if (featureEdited()) {
                        // An edit before the migration recompute may have moved another element
                        // there (decision 217, at its literal rule after review pr475b-r2)
                        refusal = "but the feature changed since the file was opened";
                    }
                }
                const bool refused = !refusal.empty();
                if (refused) {
                    pick.clear();
                }
                if ((!pick.empty() || carried) && entry->guess.empty()
                    && indexMadeOnly(entry->oldName)) {
                    // P-beta 2 (decision 247): a name made only of IDX sections is no name, so
                    // the reference isn't missing it: kept by its place, or at its index when its
                    // fingerprint agrees there, with no record or warning
                    SolverResolution resolution;
                    if (!pick.empty()) {
                        resolutionFor(*entry, pick, nameAt(pick), resolution);
                    }
                    else {
                        resolutionFor(*entry, index, mapForm(name), resolution);
                    }
                    resolutions[entry->prop].push_back(resolution);
                    FC_LOG(
                        referenceName(entry->prop)
                        << "[" << entry->index << "]: " << entry->oldName << " -> "
                        << (pick.empty() ? index : pick)
                        << " (migration: an index-made name, kept by its place)"
                    );
                    countReferenceMigration(entry->owner, MigrationOutcome::Kept);
                    continue;
                }
                if (!pick.empty()) {
                    countReferenceMigration(entry->owner, MigrationOutcome::Moved);
                    SolverResolution resolution;
                    resolutionFor(*entry, pick, nameAt(pick), resolution);
                    // Kept by its place, with a warning, as the index carry below
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
                    item.newIndex = pick;
                    item.evidence = carryEvidence + "; " + pick + " sits where it was";
                    item.candidates.emplace_back(pick, nameAt(pick));
                    item.candidateRoles.emplace_back("place");
                    item.candidateDistances.push_back(std::numeric_limits<double>::quiet_NaN());
                    FC_LOG(
                        referenceName(entry->prop)
                        << "[" << entry->index << "]: " << entry->oldName << " -> " << pick
                        << " (" << item.evidence << ")"
                    );
                }
                else if (carried) {
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
                    FC_LOG(
                        referenceName(entry->prop)
                        << "[" << entry->index << "]: " << entry->oldName << " -> " << index
                        << " (tier index, fingerprint equal)"
                    );
                }
                else {
                    countReferenceMigration(entry->owner, MigrationOutcome::Broken);
                    item.status = ReferenceReport::Status::Broken;
                    item.evidence = carryEvidence;
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
                    if (refused) {
                        // The one element at the place, refused
                        item.evidence += "; " + where + " sits where it was, " + refusal;
                    }
                    else if (!where.empty()) {
                        // Several elements at the place, or the index's own one with another
                        // (rule 2's counterpart): never one of them by its index
                        item.evidence += "; " + where + (indexAtPlace ? " and " + index : "")
                            + " sit where it was";
                    }
                    if (exists) {
                        item.candidates.emplace_back(index, mapForm(name));
                        item.candidateRoles.emplace_back("index");
                        item.candidateDistances.push_back(
                            std::numeric_limits<double>::quiet_NaN()
                        );
                    }
                    std::vector<std::string> candidates;
                    for (const auto& candidate : item.candidates) {
                        candidates.push_back(candidate.first);
                    }
                    FC_LOG(
                        referenceName(entry->prop)
                        << "[" << entry->index << "]: " << entry->oldName << " broken ("
                        << item.evidence
                        << (candidates.empty() ? "" : ", candidates: " + joinCandidates(candidates))
                        << ")"
                    );
                }
                report(*entry, std::move(item));
            }
            continue;
        }

        Data::SolveInput input;
        input.source = source;
        input.measure = measure;
        input.check = check;
        input.derived = derived;
        input.gap = gap;
        input.tolerances = tolerances;
        input.diagonal = diagonal;
        input.maplessTag = maplessTag;
        input.continuationDistance = continuationDistance;
        input.guess = guess;
        input.guessNoStructure = guessNoStructure;
        input.guessAnySource = guessAnySource;
        input.exactPlace = exactPlace;
        input.sameMaker = sameMaker;
        input.sameSource = sameSource;
        // Nothing is guessed against a failed feature passing its input through (N2's N10), nor
        // under rule PT's veto (PT3, ops#549: tier 3 and XP picks stand only by PT1)
        input.targetFailed = feature->isError() || ownerPassThrough;
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
        if (elementHoldsPointFunction) {
            input.holdsPoint =
                [geo](const std::string& index, const Base::Vector3d& point, double distance) {
                    return elementHoldsPointFunction(geo, index.c_str(), point, distance);
                };
        }
        if (elementHoldsPointAlongFunction) {
            input.holdsPointAlong = [geo](const std::string& index,
                                          const Base::Vector3d& point,
                                          const Base::Vector3d& along,
                                          double distance) {
                return elementHoldsPointAlongFunction(geo, index.c_str(), point, along, distance);
            };
        }
        Base::Vector3d sweep;
        if (elementSweepDirectionFunction && elementSweepDirectionFunction(geo, nullptr, sweep)
            && sweep.Length() > 0.0) {
            input.sweep = sweep.Normalize();
        }
        if (elementSweepDirectionFunction) {
            // A far piece's own: the extrusion that made it, maybe before the target (ops#524)
            input.sweepOf = [geo](const std::string& name) -> std::optional<Base::Vector3d> {
                Base::Vector3d direction;
                if (!elementSweepDirectionFunction(geo, name.c_str(), direction)
                    || direction.Length() <= 0.0) {
                    return std::nullopt;
                }
                return direction.Normalize();
            };
        }
        if (elementUpToFacesFunction) {
            input.upToFacesAt = [geo](const std::string& name,
                                      const Base::Vector3d& point,
                                      std::vector<Data::ElementFingerprint::UpToFace>& faces,
                                      std::vector<Data::ElementFingerprint::UpToFace>& all) {
                return elementUpToFacesFunction(geo, name.c_str(), point, faces, &all);
            };
            input.targetTag = namingTagOf(geo);  // FreeCAD-CH ops#654 S2
        }
        if (elementUpToPathFunction) {
            input.upToPathInside = [geo](const std::string& name,
                                         const Data::ElementFingerprint::UpToFace& saved,
                                         const Base::Vector3d& point) {
                return elementUpToPathFunction(geo, name.c_str(), saved, point);
            };
        }
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
                item.listHolder = true;
            }
            item.fingerprint = recordOf(*entry, entry->oldFingerprint, tolerances.angle);
            item.frame = entry->frame;
            if (entry->turned) {
                // Where it was: the stored record mapped by T, beside the followed one
                const auto stored = Data::ElementFingerprint::fromString(entry->oldFingerprint);
                Data::SolveInput::Entry::Turn turn;
                turn.oldPlace = stored.isValid()
                    ? stored.transformed(*entry->turned, tolerances.angle)
                    : Data::ElementFingerprint();
                turn.oldBoxDropped = stored.extentMin && !turn.oldPlace.extentMin;
                turn.followedBoxDropped = stored.extentMin && !item.fingerprint.extentMin;
                turn.motion = entry->turnMotion;
                turn.followed = entry->turnFollowed;
                item.turned = std::move(turn);
            }
            if (item.policy == Data::SolvePolicy::Equivalent) {
                item.equivalent = equivalenceOf(*entry);
                // An attachment's face cut into pieces inside the feature that made it breaks,
                // as in Onshape (SW19 (a), a sweep's end cap); one a later feature cuts keeps a
                // piece (SW20, a box top split by a slot); an up-to face keeps either piece.
                item.piecesBreak = isAttachmentSupport(*entry) && madeByItsTarget(*entry);
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
                // An edge or vertex named after its faces (UPP on its making section, the
                // first): the merged-neighbour test needs the target's faces (ops#446). One
                // generated from such an edge or vertex (GEN, the linked name's making section
                // UPP with two linked names at least): the missing-generator test needs them
                // and the pool of the linked name's type (ops#454). Any generated one: the
                // held-generator test needs the pools of its linked names' types (ops#467).
                if (!item.oldName.empty() && (item.type == "Edge" || item.type == "Vertex")) {
                    // The first (making) or last section of a name, decoded
                    auto sectionOf = [](std::string_view name, bool making) {
                        static const Data::DecodedMappedSection none;
                        const auto sections = Data::NameAncestry::splitSections(name);
                        if (sections.empty()) {
                            return none;
                        }
                        const auto& decoded = Data::MappedName::getDecodedMappedName(
                            std::string(making ? sections.front() : sections.back())
                        );
                        return decoded.empty() ? none : decoded.front();
                    };
                    const auto making = sectionOf(item.oldName, true);
                    if (making.hasMapperFlag(Data::MAPPER_FLAG_UPPER)) {
                        if (input.faces.empty()) {
                            input.faces = pool("Face");
                        }
                    }
                    else if (making.hasMapperFlag(Data::MAPPER_FLAG_GENERATED)) {
                        for (const auto& linked : making.linkedNames) {
                            // The held-generator test (ops#467) reads the pool of every
                            // generator's type
                            const char type = sectionOf(linked, false).elementType;
                            if (type != 'F' && type != 'E' && type != 'V') {
                                continue;
                            }
                            const std::string typeName = type == 'F' ? "Face"
                                : type == 'E'                        ? "Edge"
                                                                     : "Vertex";
                            if (input.pool.find(typeName) == input.pool.end()) {
                                input.pool[typeName] = pool(typeName);
                            }
                            const auto generator = sectionOf(linked, true);
                            const std::set<std::string> faces(generator.linkedNames.begin(),
                                                              generator.linkedNames.end());
                            if (generator.hasMapperFlag(Data::MAPPER_FLAG_UPPER)
                                && faces.size() >= 2 && type != 'F' && input.faces.empty()) {
                                input.faces = pool("Face");
                            }
                        }
                    }
                }
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

        std::optional<SolverSiteTimer> ownerTimer(std::in_place, SolverSite::SolveOwner);
        auto outcomes = Data::solveOwner(input);
        ownerTimer.reset();
        for (std::size_t i = 0; i < entries.size(); ++i) {
            const auto& entry = *entries[i];
            const auto& outcome = outcomes[i];
            const std::string& oldName = entry.oldName.empty() ? entry.exactName : entry.oldName;
            // Rule PT (ops#549): on a pass-through, whatever the solver picks (tier 0 included)
            // stands only by PT1 (or PT1s): otherwise the entry breaks, its pick listed, and the
            // reference keeps its record. A collapse and a removal are left alone; an expansion's
            // pieces are judged one by one.
            if (const auto rule = passThroughOf(entry); rule != PassThrough::None) {
                std::vector<std::string> picks;
                if (outcome.status == Data::SolveStatus::Exact) {
                    picks.push_back(outcome.element.empty() ? entry.oldIndex : outcome.element);
                }
                else if (outcome.status == Data::SolveStatus::Resolved && !outcome.elements.empty()) {
                    picks = outcome.elements;
                }
                else if ((outcome.status == Data::SolveStatus::Resolved && !outcome.collapsed)
                         || outcome.status == Data::SolveStatus::Guessed) {
                    picks.push_back(outcome.element);
                }
                std::vector<std::string> vetoed;
                for (const auto& pick : picks) {
                    if (!passThroughKeeps(entry, rule, pick)) {
                        vetoed.push_back(pick);
                    }
                }
                if (!vetoed.empty()) {
                    if (entry.kind == SolverEntry::Kind::Exact) {
                        SolverResolution resolution;
                        brokenFor(entry, resolution);
                        resolutions[entry.prop].push_back(resolution);
                    }
                    ReferenceReport::Entry item;
                    item.status = ReferenceReport::Status::Broken;
                    item.tier = outcome.tier;
                    item.evidence = passThroughEvidence(entry, rule);
                    for (const auto& pick : vetoed) {
                        item.candidates.emplace_back(pick, nameAt(pick));
                        item.candidateRoles.emplace_back("pass-through");
                        item.candidateDistances.push_back(std::numeric_limits<double>::quiet_NaN());
                    }
                    FC_LOG(referenceName(entry.prop)
                           << "[" << entry.index << "]: " << oldName << " broken (" << item.evidence
                           << ", candidates: " << joinCandidates(vetoed) << ")");
                    report(entry, std::move(item));
                    continue;
                }
            }
            if (outcome.status == Data::SolveStatus::Exact) {
                if (!outcome.evidence.empty()) {
                    // Kept by its name, with a reason the solver gives (e.g. its own twin sits
                    // at its old place, ops#168).
                    FC_LOG(referenceName(entry.prop) << "[" << entry.index << "]: "
                                                     << outcome.element << " kept ("
                                                     << outcome.evidence << ")");
                }
                continue;
            }
            if (outcome.status == Data::SolveStatus::Removed) {
                SolverResolution resolution;
                resolution.status = SolverResolution::Status::Removed;
                resolution.prop = entry.prop;
                resolution.index = entry.index;
                resolutions[entry.prop].push_back(resolution);
                FC_LOG(
                    referenceName(entry.prop) << "[" << entry.index << "]: " << oldName << " removed ("
                                              << outcome.evidence << " to " << outcome.element << ")"
                );
                continue;
            }
            // A guess whose pick the solver finds again as the element the original's name
            // gives (resolved, guessed, or broken with it as the only candidate) has returned to
            // its original: two findings agree. The probe didn't snap it back because an
            // intervening edit changed the original since its fingerprint (a snapshot) was
            // saved. It holds the original plainly, its record and warning gone (ops#138). The
            // name alone can give the piece of the original that kept it (ops#133), and the
            // search can end there when the pick is gone: the element must also hold the
            // original's saved centre (G3's test) and cover all of its saved extent, or it
            // isn't the original returned (the Opus review of fork PR 249, M1; a piece can hold
            // the centre: its verification, finding 1). So a curved face, a B-spline, a vertex
            // or a record without a saved fingerprint never returns: its guess stays. Nor if
            // another reference of the property holds it.
            if (!entry.guess.empty() && entry.guess.kind != "rejected") {
                std::string returned;
                std::string returnedName;
                if ((outcome.status == Data::SolveStatus::Resolved && outcome.elements.empty())
                    || outcome.status == Data::SolveStatus::Guessed) {
                    if (isOriginalNow(entry, outcome.element)) {
                        returned = outcome.element;
                        returnedName = outcome.name;
                    }
                }
                else if (outcome.status == Data::SolveStatus::Broken
                         && outcome.candidates.size() == 1
                         && outcome.candidateNames.size() == 1
                         && isOriginalNow(entry, outcome.candidates.front())) {
                    returned = outcome.candidates.front();
                    returnedName = outcome.candidateNames.front();
                }
                if (!returned.empty()) {
                    const auto saved =
                        Data::ElementFingerprint::fromString(entry.guess.origFingerprint);
                    const auto now = fingerprintOf(returned);
                    if (!Data::holdsCentre(saved, now, diagonal, continuationDistance)
                        || !Data::coversExtent(saved, now, diagonal, continuationDistance)) {
                        FC_LOG(referenceName(entry.prop)
                               << "[" << entry.index << "]: " << returned
                               << ", which the original " << entry.guess.origIndex
                               << "'s name gives, doesn't hold its saved centre and extent: "
                                  "not the original");
                        returned.clear();
                    }
                }
                if (!returned.empty()
                    && std::any_of(entries.begin(), entries.end(), [&](const auto* other) {
                           return other->prop == entry.prop && other->index != entry.index
                               && other->kind == SolverEntry::Kind::Exact
                               && other->obj == entry.obj && other->prefix == entry.prefix
                               && other->oldIndex == returned;
                       })) {
                    // Held already: not settled here. The outcome below names an element the
                    // other reference holds, and rebuildSubList() writes no second sub for it
                    returned.clear();
                }
                if (!returned.empty()) {
                    SolverResolution resolution;
                    resolutionFor(entry, returned, mapForm(returnedName), resolution);
                    resolution.clearFrom = outcome.status == Data::SolveStatus::Resolved
                        && outcome.collapsed;
                    resolutions[entry.prop].push_back(resolution);
                    ReferenceReport::Entry item;
                    item.status = ReferenceReport::Status::Resolved;
                    item.tier = outcome.tier;
                    item.newIndex = returned;
                    item.evidence = "the original's name gives it again";
                    report(entry, std::move(item));
                    FC_LOG(
                        referenceName(entry.prop)
                        << "[" << entry.index << "]: " << oldName << " -> " << returned
                        << " (the original " << entry.guess.origIndex
                        << " is back, changed since it was saved)"
                    );
                    continue;
                }
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
                FC_LOG(
                    referenceName(entry.prop) << "[" << entry.index << "]: " << oldName << " -> "
                                              << joinCandidates(outcome.elements) << " (tier "
                                              << outcome.tier << ", " << outcome.evidence << ")"
                );
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
                else if (outcome.equivalentPieces && entry.guess.empty()
                         && isAttachmentSupport(entry)) {
                    // A piece standing for pieces that give the consumer one result (an
                    // attachment kept on a face a later feature split, SW20): it holds the
                    // piece, and a silent record of the whole element, so that the probe
                    // returns it there once the split goes and the old name gives the whole
                    // element again, its fingerprint agreeing (Onshape's SW20 (3)). Only an
                    // attachment: an up-to face needs no way back (any piece gives the same
                    // extent, and the whole face does too).
                    resolution.status = SolverResolution::Status::Guessed;
                    resolution.guess = guessRecordFor(entry, "equivalent");
                }
                resolutions[entry.prop].push_back(resolution);
                FC_LOG(
                    referenceName(entry.prop)
                    << "[" << entry.index << "]: " << oldName << " -> " << outcome.element
                    << " (tier " << outcome.tier << ", " << outcome.evidence << ")"
                );
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
                FC_LOG(
                    referenceName(entry.prop)
                    << "[" << entry.index << "]: " << oldName << " -> " << outcome.element
                    << " (guessed, " << outcome.evidence << ")"
                );
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
                    // A twin nearer the old place than the hit (ops#360, PR 340 round 3)
                    const bool nearer = outcome.evidence.find(" nearer where it was")
                        != std::string::npos;
                    item.headline = "Ambiguous " + type + " reference: " + entry.oldIndex + verb
                        + places
                        + (places.find(" and ") == std::string::npos ? " sits" : " sit")
                        + (nearer ? " nearer where it was" : " where it was");
                }
                FC_LOG(
                    referenceName(entry.prop)
                    << "[" << entry.index << "]: " << oldName << " broken (" << outcome.evidence
                    << (outcome.candidates.empty()
                            ? std::string()
                            : ", candidates: " + joinCandidates(outcome.candidates))
                    << ")"
                );
            }
            report(entry, std::move(item));
        }
    }

    // Write back, once per property visited, and rebuild its report for this target.
    SolverSiteTimer writeTimer(SolverSite::WriteBack);
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

bool reboundInPlace(DocumentObject* obj, const std::string& sub, const GuessRecord& guess)
{
    if ((guess.kind != "tier2" && guess.kind != "tier3") || guess.origFingerprint.empty() || !obj
        || !obj->isAttachedToDocument() || Data::hasMissingElement(sub.c_str())) {
        return false;
    }
    const Data::ElementFingerprint saved = Data::ElementFingerprint::fromString(guess.origFingerprint);
    if (!saved.isValid()) {
        return false;
    }
    // The element the reference holds, in the feature that owns it (as the solver measured it)
    ElementNamePair elementName;
    GeoFeature* geo = nullptr;
    const char* element = nullptr;
    if (!GeoFeature::resolveElement(
            obj,
            sub.c_str(),
            elementName,
            false,
            GeoFeature::Normal,
            nullptr,
            &element,
            &geo
        )
        || !geo || !element || !element[0] || elementName.oldName.empty()
        || GeoFeature::hasMissingElement(elementName.oldName.c_str())) {
        return false;
    }
    double diagonal = 0.0;
    if (auto prop = geo->getPropertyOfGeometry()) {
        if (auto data = prop->getComplexData()) {
            diagonal = data->getBoundBox().CalcDiagonalLength();
        }
    }
    double gap = Data::SolveInput().gap;
    Data::GeometryTolerances tolerances;
    double continuationDistance = Data::SolveInput().continuationDistance;
    readTolerances(gap, tolerances, continuationDistance);
    auto here = [&](const std::string& index) {
        Data::ElementFingerprint now;
        return geo->getElementFingerprint(index.c_str(), now)
            && Data::atSamePlace(saved, now, diagonal, tolerances, continuationDistance);
    };
    if (!here(elementName.oldName)) {
        return false;
    }
    // An index-only reference has no origin to share: never quiet (ops#550 (1), ops#526 D2)
    if (guess.origName.empty()) {
        return false;
    }
    // Never quiet for the original's twin, nor for an element of another origin (ops#503 D1:
    // the twin-pick rule, XP's source condition), judged from the names as the solver judged
    // them
    {
        std::vector<std::string> names;
        if (const auto prop = geo->getPropertyOfGeometry()) {
            if (const auto data = prop->getComplexData()) {
                // the map's entries, as poolOf() reads them (F4)
                Data::IndexedName indexed(elementName.oldName.c_str());
                if (indexed) {
                    for (const auto& mapped : data->getElementMap()) {
                        if (mapped.index == indexed) {
                            names.push_back(plainName(mapped.name.toString()));
                        }
                    }
                }
            }
        }
        const std::string oldName = plainName(guess.origName);
        const bool sameMaker = solverParameters()->GetBool("Tier1SameMaker", true);
        if (!Data::mayBeQuietAtPlace(names, oldName, sameMaker)) {
            return false;
        }
        // T1''s test: an element that lost the old name's sources is quiet only when the record
        // says it is the element drawn again there (ops#526 D2, placeVerdict(): its sides the
        // old element's, every source it doesn't share new to a sketch the target was built
        // from); a sibling moved onto the place, a record without the marks, or one taken after
        // an index-made old element's object left the model (SourceGone), is never quiet
        // (PLAN decisions 155 and 165). Judged on the record the solver judged (the guess's
        // snapshot), never on a refreshed one. The solver's own form of the test also exempts
        // tier 1's ancestry and IDX survivors; this one doesn't, which can only warn where the
        // solver would have kept the quieter level.
        if (solverParameters()->GetBool("Tier1SameSource", true)) {
            const bool lost = Data::lostOldSources(names, oldName);
            Data::ElementFingerprint now;
            const Data::PlaceVerdict verdict = geo->getElementFingerprint(elementName.oldName.c_str(), now)
                ? Data::placeVerdict(saved, now, names, oldName, lost, tolerances)
                : Data::PlaceVerdict::Unjudged;
            if (verdict == Data::PlaceVerdict::OtherSide || verdict == Data::PlaceVerdict::SourceGone
                || (lost && verdict != Data::PlaceVerdict::Quiet)) {
                return false;
            }
        }
    }
    // The only element there: an alternative at the same place makes the pick a choice
    return std::none_of(
        guess.alternatives.begin(),
        guess.alternatives.end(),
        [&](const GuessRecord::Alternative& alternative) {
            return !alternative.index.empty() && alternative.index != elementName.oldName
                && here(alternative.index);
        }
    );
}

std::string twinKeyForTesting(const std::string& name, bool plain)
{
    return twinKey(plain ? plainName(name) : ownSections(name));
}

namespace
{
// A target shape's names of one type by twin key: each element's index and the name's own
// sections (elementTwinCentroid())
using TwinIndex = std::unordered_map<std::string, std::vector<std::pair<int, std::string>>>;
thread_local int twinIndexDepth = 0;
thread_local std::map<std::pair<const Data::ComplexGeoData*, std::string>, TwinIndex> twinIndexes;

TwinIndex makeTwinIndex(const Data::ComplexGeoData* data, const char* type)
{
    TwinIndex index;
    const auto elements = data->countSubElements(type);
    for (unsigned long i = 1; i <= elements; ++i) {
        const Data::IndexedName indexed(type, static_cast<int>(i));
        for (const auto& mapped : data->getElementMappedNames(indexed)) {
            std::string own = ownSections(mapped.first.toString());
            std::string key = twinKey(own);
            index[std::move(key)].emplace_back(static_cast<int>(i), std::move(own));
        }
    }
    return index;
}
}  // namespace

TwinIndexScope::TwinIndexScope()
{
    ++twinIndexDepth;
}

TwinIndexScope::~TwinIndexScope()
{
    if (--twinIndexDepth == 0) {
        twinIndexes.clear();
    }
}

bool elementTwinCentroid(const GeoFeature* geo, const char* element, Base::Vector3d& centroid, int& count)
{
    count = 0;
    const PropertyComplexGeoData* prop = geo ? geo->getPropertyOfGeometry() : nullptr;
    const Data::ComplexGeoData* data = prop ? prop->getComplexData() : nullptr;
    if (!data || !element || !element[0]) {
        return false;
    }
    Data::IndexedName indexed(element);
    if (!indexed) {
        return false;
    }
    // The element's names with their own sections in full and the names they embed as the map
    // holds them (ownSections()): Data::isTwinName() and Data::isOrderKeyedName() read a
    // reference as its content and answer as for the plain forms the solver sees (poolOf()),
    // without building them
    std::vector<std::string> names;
    for (const auto& mapped : data->getElementMappedNames(indexed)) {
        names.push_back(ownSections(mapped.first.toString()));
    }
    if (names.empty()) {
        return false;
    }
    // Its twins: the elements of its type with a name that is one of these up to an order key
    // (Data::isTwinName(), ops#503 D1: the bare-rank crossings of an edge too, which carry no
    // ORD flag, and the survivor of a 2 -> 1 change, which lost it)
    std::vector<std::string> keys;
    for (const auto& name : names) {
        keys.push_back(twinKey(name));
    }
    // Only the elements of its type, each name tested only when it shares the twin key: walking
    // the whole map and decoding every name made creating references about 8.5 times slower on a
    // 372-edge model (PR 379 round 1). The names are each index's own (findAll()), where the
    // solver's pool reads the map's entries (getAll(): a child element's first name): they differ
    // for child-mapped elements only. Reading the pool's way here cost 3 times more again (round
    // 3), and no model was found where the difference decides; a count that differs is a trade
    // (loud), the ORD pieces' desync D3's (round 2's cloud review, F4).
    // The names of its type by twin key (makeTwinIndex()), kept while a TwinIndexScope lives: each
    // reference of a list tests only the names that share a key with one of its own
    TwinIndex local;
    const TwinIndex* byKey = &local;
    if (twinIndexDepth > 0) {
        const auto slot = std::make_pair(data, std::string(indexed.getType()));
        auto it = twinIndexes.find(slot);
        if (it == twinIndexes.end()) {
            it = twinIndexes.emplace(slot, makeTwinIndex(data, indexed.getType())).first;
        }
        byKey = &it->second;
    }
    else {
        local = makeTwinIndex(data, indexed.getType());
    }
    std::set<int> found;
    for (std::size_t k = 0; k < names.size(); ++k) {
        const auto it = byKey->find(keys[k]);
        if (it == byKey->end()) {
            continue;
        }
        for (const auto& [i, own] : it->second) {
            if (i != indexed.getIndex() && found.count(i) == 0 && Data::isTwinName(own, names[k])) {
                found.insert(i);
            }
        }
    }
    std::set<std::string> twins;
    for (const int i : found) {
        twins.insert(Data::IndexedName(indexed.getType(), i).toString());
    }
    if (twins.empty()) {
        // Alone, with a name keyed by its order: one twin, so that the solver tells a later pick
        // of it renumbered from a trade (the twin-pick rule's lone member)
        if (std::any_of(names.begin(), names.end(), [](const std::string& name) {
                return Data::isOrderKeyedName(name);
            })) {
            count = 1;
            return true;
        }
        return false;
    }
    Data::ElementFingerprint own;
    if (!geo->getElementFingerprint(element, own) || !own.center) {
        return false;
    }
    Base::Vector3d sum = *own.center;
    int number = 1;
    for (const auto& index : twins) {
        Data::ElementFingerprint twin;
        if (geo->getElementFingerprint(index.c_str(), twin) && twin.center) {
            sum += *twin.center;
            ++number;
        }
    }
    if (number < 2) {
        return false;
    }
    centroid = sum / static_cast<double>(number);
    count = number;
    return true;
}

bool elementUpToFaces(
    const GeoFeature* geo,
    const char* element,
    const Data::ElementFingerprint& fingerprint,
    std::vector<Data::ElementFingerprint::UpToFace>& faces
)
{
    faces.clear();
    const PropertyComplexGeoData* prop = geo ? geo->getPropertyOfGeometry() : nullptr;
    const Data::ComplexGeoData* data = prop ? prop->getComplexData() : nullptr;
    const auto point = Data::upToPointOf(fingerprint);
    if (!elementUpToFacesFunction || !data || !element || !element[0]
        || (fingerprint.type != 'F' && fingerprint.type != 'E') || !point) {
        return false;
    }
    Data::IndexedName indexed(element);
    if (!indexed) {
        return false;
    }
    // A far piece: a marked projection, as the made-whole rule's old name is (solveOwner()), made
    // by this feature. A later Pad's shape keeps an earlier Pad's pieces under their names, and
    // its own up-to faces aren't theirs (review pr398-r3). The piece's name names the extrusion
    // that made it (ops#524)
    const long tag = namingTagOf(geo);  // FreeCAD-CH ops#654 S2: a step names by its owner
    // Told off the name's own sections (ownSections()): the mark is in a top-level section's
    // fields, and the plain form, the whole history, is built for a marked piece only
    std::string own;
    for (const auto& mapped : data->getElementMappedNames(indexed)) {
        const std::string name = mapped.first.toString();
        if (Data::isMarkedPieceOf(ownSections(name), tag)) {
            own = plainName(name);
            break;
        }
    }
    if (own.empty()) {
        return false;
    }
    // An edge's point must lie on the edge: an arc's centre of mass lies off it, over another
    // plate than the one the arc lies on (review pr398-r3). Can't be told otherwise.
    const double diagonal = std::max(1.0, data->getBoundBox().CalcDiagonalLength());
    if (fingerprint.type == 'E') {
        if (!elementHoldsPointFunction
            || !elementHoldsPointFunction(geo, element, *point, 1e-6 * diagonal)) {
            return false;
        }
    }
    // A face's point, seen along the sweep as the up-to faces are, must lie inside the face: a
    // centre of mass kept for a face with a small hole around it (no inside point) lies in the
    // hole, over another plate (review pr398-r4)
    Base::Vector3d sweep;
    if (fingerprint.type == 'F'
        && (!elementSweepDirectionFunction || !elementHoldsPointAlongFunction
            || !elementSweepDirectionFunction(geo, own.c_str(), sweep) || sweep.Length() <= 0.0
            || !elementHoldsPointAlongFunction(geo, element, *point, sweep.Normalize(), diagonal))) {
        return false;
    }
    return elementUpToFacesFunction(geo, own.c_str(), *point, faces, nullptr);
}

}  // namespace App
