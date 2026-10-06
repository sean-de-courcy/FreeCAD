// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2002 Jürgen Riegel <juergen.riegel@web.de>              *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include <algorithm>
#include <optional>

#include <QDir>
#include <QFileInfo>
#include <boost/algorithm/string/predicate.hpp>

#include <Base/Console.h>
#include <Base/Exception.h>
#include <Base/Reader.h>
#include <Base/Writer.h>
#include <Base/Tools.h>

#include "PropertyLinks.h"
#include "Application.h"
#include "Document.h"
#include "ElementFingerprint.h"
#include "ElementSolver.h"
#include "ElementSolverBatch.h"
#include "ReferenceReport.h"
#include "DocumentObject.h"
#include "DocumentObjectPy.h"
#include "DocumentObserver.h"
#include "ObjectIdentifier.h"
#include "ElementNamingUtils.h"
#include "GeoFeature.h"
#include "ElementReferences.h"
#include "LinkRetarget.h"
#include "NamingRevision.h"
#include "ComplexGeoData.h"
#include "NameTable.h"


FC_LOG_LEVEL_INIT("PropertyLinks", true, true)

using namespace App;
using namespace Base;
using namespace std;
namespace sp = std::placeholders;

//**************************************************************************
//**************************************************************************
// PropertyLinkBase
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE_ABSTRACT(App::PropertyLinkBase, App::Property)

// clang-format off
static std::unordered_map<std::string, std::set<PropertyLinkBase*>> _LabelMap;
static std::unordered_map<App::DocumentObject*, std::unordered_set<PropertyLinkBase*>> _ElementRefMap;
// clang-format on

// The properties to register at the next attach of a document (ops#120): those that lost a
// registration when the feature holding an element they reference was destroyed (e.g. through
// an App::Link whose target document closed), and those whose registration failed because the
// path to the element didn't resolve (the target document not open: its file missing at an
// open, or a value set while it is closed). DocInfo::registerLostReferences() takes each out and
// registers it again; a sub that still doesn't resolve puts it back. A destroyed property
// leaves the set, so it holds live properties only.
static std::unordered_set<PropertyLinkBase*> _LostElementRefs;

// A registration of \a sub failed because the path to its element doesn't resolve (ops#120)
static void registerAtNextAttach(PropertyLinkBase* prop, const char* sub)
{
    const char* element = sub ? Data::findElementName(sub) : nullptr;
    if (element && element[0]) {
        _LostElementRefs.insert(prop);
    }
}

// The properties an attach registered again while a document was restored (ops#120): an open
// resolves them at its end (updateAllElementReferences()), a restore outside one through
// resolveReregisteredReferences(). A destroyed property leaves the set.
static std::unordered_set<PropertyLinkBase*> _ResolveAfterRestore;

// The element a reference named before a link retarget made it index-only (ops#106): the sub,
// the object it is a sub of (compared by address only), and the old element's fingerprint. The
// sub's first resolution on the new target checks the element there against it
// (_updateElementReference()).
struct RetargetCheck
{
    const App::DocumentObject* obj;
    std::string sub;
    Data::ElementFingerprint before;
};
static std::unordered_map<const PropertyLinkBase*, std::vector<RetargetCheck>> _RetargetChecks;
// Checks read from a file, by sub index, until onContainerRestored() holds them (ops#109): a file
// saved before a sub's first resolution on the new target keeps its check.
static std::unordered_map<const PropertyLinkBase*,
                          std::vector<std::pair<std::size_t, Data::ElementFingerprint>>>
    _RestoredRetargetChecks;

// The reorder's re-target records in a setter (ops#127; defined with their attributes below)
static void keepRetargetRecords(std::vector<RetargetRecord>& records,
                                std::size_t count,
                                const std::vector<PropertyLinkBase::ShadowSub>& shadows);

// The consumer pass at open (ops#116): references whose names are of an older naming revision
// than their producer's, in another document, re-derived from their geometry.
// While it runs, the solver-off re-derivation has no snapshot of the shape the names were
// resolved in (a feature's element cache holds its shape before its last change in this session,
// not the one the reference was saved against): the name decides alone (ops#103's rule 1).
static bool _InConsumerPass = false;
struct ConsumerPassScope
{
    ConsumerPassScope()
    {
        _InConsumerPass = true;
    }
    ~ConsumerPassScope()
    {
        _InConsumerPass = false;
    }
};
// XLinks attached during an open whose owner documents were opened before it.
static std::unordered_set<const PropertyLinkBase*> _ConsumerPassLinks;

// The properties whose references took the consumer pass in this session (ops#120): their names
// are this build's from then on, also while their document's revision stays older (it holds
// references into a document that isn't open), so a later attach, revert or open doesn't re-derive
// them again. A destroyed property leaves the set.
static std::unordered_set<const PropertyLinkBase*> _PassedRefs;

// The fork's naming revision of \a feature's names: this build's when its element map version is
// current, else the `.F<n>` of the version it was restored with (0 without one: older than any).
// -1 when its version holds no revision (V1, no geometry): no pass for references into it.
static int producerNamingRevision(const DocumentObject* feature)
{
    auto geo = freecad_cast<const GeoFeature*>(feature);
    if (!geo) {
        return -1;
    }
    const std::string correct = geo->getCorrectElementMapVersion();
    const std::string& version = geo->_ElementMapVersion.getStrValue();
    if (version.empty() || correct.find(".F") == std::string::npos) {
        return -1;
    }
    if (version == correct) {
        return App::forkNamingRevision();
    }
    auto pos = version.find(".F");
    return pos == std::string::npos ? 0 : std::atoi(version.c_str() + pos + 2);
}

// Whether \a prop's references into \a feature take the consumer pass (ops#116): \a feature is in
// another document, its names are this build's, and \a prop's document holds names of an older
// revision. At an open (\a opening), only for the documents and links it restored.
static bool takesConsumerPass(const PropertyLinkBase* prop,
                              const DocumentObject* feature,
                              bool opening)
{
    auto owner = freecad_cast<DocumentObject*>(prop->getContainer());
    auto doc = owner ? owner->getDocument() : nullptr;
    if (!doc || !feature || feature->getDocument() == doc || _PassedRefs.count(prop) != 0) {
        return false;
    }
    if (opening && !App::openedWithOlderNaming(doc) && _ConsumerPassLinks.count(prop) == 0) {
        return false;
    }
    return App::namingRevisionOf(doc) < App::forkNamingRevision()
        && producerNamingRevision(feature) == App::forkNamingRevision();
}

// A property's subs, by index and by mapped name: compared before and after the consumer pass
static std::vector<std::string> referenceState(const PropertyLinkBase* prop)
{
    std::vector<DocumentObject*> objs;
    std::vector<std::string> subs;
    prop->getLinks(objs, true, &subs, false);
    std::vector<std::string> mapped;
    prop->getLinks(objs, true, &mapped, true);
    subs.insert(subs.end(), mapped.begin(), mapped.end());
    return subs;
}

// Whether the element an index names on a link's new target agrees with the one the reference
// named before the retarget (ops#106): the same type and kind, and the same direction (a plane's
// normal with its sense, an axis or a line either way), each in its feature's own frame. Sizes,
// centres and radii are left out: variants differ in their dimensions by design.
static bool retargetAgrees(Data::ElementFingerprint before, Data::ElementFingerprint now)
{
    before.radii.clear();
    now.radii.clear();
    return Data::intrinsicAgrees(before, now, Data::GeometryTolerances());
}

PropertyLinkBase::PropertyLinkBase() = default;

PropertyLinkBase::~PropertyLinkBase()
{
    unregisterLabelReferences();
    unregisterElementReference();
    _RetargetChecks.erase(this);
    _RestoredRetargetChecks.erase(this);
    _LostElementRefs.erase(this);
    _ResolveAfterRestore.erase(this);
    _PassedRefs.erase(this);
}

void PropertyLinkBase::setAllowExternal(bool allow)
{
    setFlag(LinkAllowExternal, allow);
}

void PropertyLinkBase::setSilentRestore(bool allow)
{
    setFlag(LinkSilentRestore, allow);
}

void PropertyLinkBase::setReturnNewElement(bool enable)
{
    setFlag(LinkNewElement, enable);
}

void PropertyLinkBase::hasSetValue()
{
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (owner) {
        owner->clearOutListCache();
    }
    Property::hasSetValue();
}

bool PropertyLinkBase::isSame(const Property& other) const
{
    if (&other == this) {
        return true;
    }
    if (other.isDerivedFrom<PropertyLinkBase>()
        || getScope() != static_cast<const PropertyLinkBase*>(&other)->getScope()) {
        return false;
    }

    static std::vector<App::DocumentObject*> ret;
    static std::vector<std::string> subs;
    static std::vector<App::DocumentObject*> ret2;
    static std::vector<std::string> subs2;

    ret.clear();
    subs.clear();
    ret2.clear();
    subs2.clear();
    getLinks(ret, true, &subs, false);
    static_cast<const PropertyLinkBase*>(&other)->getLinks(ret2, true, &subs2, true);

    return ret == ret2 && subs == subs2;
}

void PropertyLinkBase::unregisterElementReference()
{
    // The reference solver's report on this property is stale from here on (ops#7).
    ReferenceReport::clear(this);
    for (auto obj : _ElementRefs) {
        auto it = _ElementRefMap.find(obj);
        if (it != _ElementRefMap.end()) {
            it->second.erase(this);
            if (it->second.empty()) {
                _ElementRefMap.erase(it);
            }
        }
    }
    _ElementRefs.clear();
}

void PropertyLinkBase::unregisterLabelReferences()
{
    for (auto& label : _LabelRefs) {
        auto it = _LabelMap.find(label);
        if (it != _LabelMap.end()) {
            it->second.erase(this);
            if (it->second.empty()) {
                _LabelMap.erase(it);
            }
        }
    }
    _LabelRefs.clear();
}

void PropertyLinkBase::getLabelReferences(std::vector<std::string>& subs, const char* subname)
{
    const char* dot;
    for (; (subname = strchr(subname, '$')) != nullptr; subname = dot + 1) {
        ++subname;
        dot = strchr(subname, '.');
        if (!dot) {
            break;
        }
        subs.emplace_back(subname, dot - subname);
    }
}

void PropertyLinkBase::registerLabelReferences(std::vector<std::string>&& labels, bool reset)
{
    if (reset) {
        unregisterLabelReferences();
    }
    for (auto& label : labels) {
        auto res = _LabelRefs.insert(std::move(label));
        if (res.second) {
            _LabelMap[*res.first].insert(this);
        }
    }
}

void PropertyLinkBase::checkLabelReferences(const std::vector<std::string>& subs, bool reset)
{
    if (reset) {
        unregisterLabelReferences();
    }
    std::vector<std::string> labels;
    for (auto& sub : subs) {
        labels.clear();
        getLabelReferences(labels, sub.c_str());
        registerLabelReferences(std::move(labels), false);
    }
}

std::string PropertyLinkBase::updateLabelReference(const App::DocumentObject* parent,
                                                   const char* subname,
                                                   const App::DocumentObject* obj,
                                                   const std::string& ref,
                                                   const char* newLabel)
{
    if (!obj || !obj->isAttachedToDocument() || !parent || !parent->isAttachedToDocument()) {
        return {};
    }

    // Because the label is allowed to be the same across different
    // hierarchies, we have to search for all occurrences, and make sure the
    // referenced sub-object at the found hierarchy is actually the given
    // object.
    for (const char* pos = subname; ((pos = strstr(pos, ref.c_str())) != nullptr);
         pos += ref.size()) {
        auto sub = std::string(subname, pos + ref.size() - subname);
        auto sobj = parent->getSubObject(sub.c_str());
        if (sobj == obj) {
            sub = subname;
            sub.replace(pos + 1 - subname, ref.size() - 2, newLabel);
            return sub;
        }
    }
    return {};
}

std::vector<std::pair<Property*, std::unique_ptr<Property>>>
PropertyLinkBase::updateLabelReferences(App::DocumentObject* obj, const char* newLabel)
{
    std::vector<std::pair<Property*, std::unique_ptr<Property>>> ret;
    if (!obj || !obj->isAttachedToDocument()) {
        return ret;
    }
    auto it = _LabelMap.find(obj->Label.getStrValue());
    if (it == _LabelMap.end()) {
        return ret;
    }
    std::string ref("$");
    ref += obj->Label.getValue();
    ref += '.';
    std::vector<PropertyLinkBase*> props;
    props.reserve(it->second.size());
    props.insert(props.end(), it->second.begin(), it->second.end());
    for (auto prop : props) {
        if (!prop->getContainer()) {
            continue;
        }
        std::unique_ptr<Property> copy(prop->CopyOnLabelChange(obj, ref, newLabel));
        if (copy) {
            ret.emplace_back(prop, std::move(copy));
        }
    }
    return ret;
}

static std::string propertyName(const Property* prop)
{
    if (!prop) {
        return {};
    }
    if (!prop->getContainer() || !prop->hasName()) {
        auto xlink = freecad_cast<const PropertyXLink*>(prop);
        if (xlink) {
            return propertyName(xlink->parent());
        }
    }
    return prop->getFullName();
}

// The reference solver (ops#7) for the properties of solver documents among a feature's
// references, those still registered under it.
static void solveReferences(DocumentObject* feature,
                            std::vector<PropertyLinkBase*>& props,
                            bool reverse,
                            bool notify = true)
{
    auto it = _ElementRefMap.find(feature);
    if (it == _ElementRefMap.end()) {
        return;
    }
    props.erase(std::remove_if(props.begin(),
                               props.end(),
                               [&](PropertyLinkBase* prop) {
                                   return it->second.count(prop) == 0;
                               }),
                props.end());
    if (props.empty()) {
        return;
    }
    try {
        App::solveElementReferences(feature, props, reverse, notify);
    }
    catch (Base::Exception& e) {
        e.reportException();
        FC_ERR("Failed to update element references to " << feature->getFullName());
    }
    catch (std::exception& e) {
        FC_ERR("Failed to update element references to " << feature->getFullName() << ": "
                                                          << e.what());
    }
}

const std::unordered_set<PropertyLinkBase*>&
PropertyLinkBase::getElementReferences(DocumentObject* feature)
{
    static std::unordered_set<PropertyLinkBase*> none;

    auto it = _ElementRefMap.find(feature);
    if (it == _ElementRefMap.end()) {
        return none;
    }

    return it->second;
}

void PropertyLinkBase::updateElementReferences(DocumentObject* feature, bool reverse)
{
    if (!feature || !feature->getNameInDocument()) {
        return;
    }
    auto it = _ElementRefMap.find(feature);
    if (it == _ElementRefMap.end()) {
        return;
    }
    std::vector<PropertyLinkBase*> props;
    props.reserve(it->second.size());
    props.insert(props.end(), it->second.begin(), it->second.end());
    // Properties in reference solver documents (ops#7) are updated together, after the others.
    std::vector<PropertyLinkBase*> solverProps;
    for (auto prop : props) {
        if (prop->getContainer()) {
            if (prop->inSolverDocument()) {
                solverProps.push_back(prop);
                continue;
            }
            try {
                prop->updateElementReference(feature, reverse, true);
            }
            catch (Base::Exception& e) {
                e.reportException();
                FC_ERR("Failed to update element reference of " << propertyName(prop));
            }
            catch (std::exception& e) {
                FC_ERR("Failed to update element reference of " << propertyName(prop) << ": "
                                                                << e.what());
            }
        }
    }
    solveReferences(feature, solverProps, reverse);
}

void PropertyLinkBase::updateAllElementReferences(bool reverse)
{
    // The end of an open: the references registered again during it are among those updated
    // below (ops#120)
    _ResolveAfterRestore.clear();
    // Updating a reference can register or unregister references, which
    // changes _ElementRefMap. So iterate over a snapshot, and skip the
    // properties that have left the map since it was taken.
    std::vector<std::pair<DocumentObject*, std::vector<PropertyLinkBase*>>> references;
    references.reserve(_ElementRefMap.size());
    for (const auto& [feature, props] : _ElementRefMap) {
        references.emplace_back(feature,
                                std::vector<PropertyLinkBase*>(props.begin(), props.end()));
    }
    // The consumer pass (ops#116): at the end of an open, the references of the documents it
    // opened with an older naming revision into producers in other documents whose names are
    // already current are re-derived from their geometry (reverse), not followed by name. They
    // don't notify; the owners whose references changed are touched afterwards, and their
    // documents ask for a recompute. Current files pay for anyOpenedWithOlderNaming() only.
    const bool pass =
        !reverse && (App::anyOpenedWithOlderNaming() || !_ConsumerPassLinks.empty());
    std::unordered_map<PropertyLinkBase*, std::vector<std::string>> passed;  // the state before
    for (const auto& [feature, props] : references) {
        std::vector<PropertyLinkBase*> solverProps;
        std::vector<PropertyLinkBase*> solverPassProps;
        for (auto prop : props) {
            auto it = _ElementRefMap.find(feature);
            if (it == _ElementRefMap.end() || it->second.count(prop) == 0) {
                continue;
            }
            const bool inPass = pass && prop->getContainer() && feature->isAttachedToDocument()
                && takesConsumerPass(prop, feature, true);
            if (inPass) {
                passed.emplace(prop, referenceState(prop));
            }
            if (prop->getContainer() && prop->inSolverDocument()) {
                (inPass ? solverPassProps : solverProps).push_back(prop);
                continue;
            }
            if (prop->getContainer()) {
                try {
                    if (inPass) {
                        ConsumerPassScope scope;
                        prop->updateElementReference(feature, true, false);
                    }
                    else {
                        prop->updateElementReference(feature, reverse, true);
                    }
                }
                catch (Base::Exception& e) {
                    e.reportException();
                    FC_ERR("Failed to update element reference of " << propertyName(prop));
                }
                catch (std::exception& e) {
                    FC_ERR("Failed to update element reference of " << propertyName(prop) << ": "
                                                                    << e.what());
                }
            }
        }
        solveReferences(feature, solverProps, reverse);
        solveReferences(feature, solverPassProps, true, false);
    }
    if (!pass) {
        return;
    }
    for (const auto& [prop, before] : passed) {
        _PassedRefs.insert(prop);
        auto owner = freecad_cast<DocumentObject*>(prop->getContainer());
        if (owner && owner->getDocument() && referenceState(prop) != before) {
            owner->touch();
            owner->getDocument()->setStatus(Document::RecomputeOnRestore, true);
        }
    }
    if (!passed.empty()) {
        App::reportReferenceMigration();
    }
    App::endOpenedWithOlderNaming();
    _ConsumerPassLinks.clear();
}

bool PropertyLinkBase::inSolverDocument() const
{
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    auto doc = owner ? owner->getDocument() : nullptr;
    return doc && doc->isReferenceSolverOn();
}

std::string PropertyLinkBase::_getElementFingerprint(App::DocumentObject* feature,
                                                     App::DocumentObject* obj,
                                                     const std::string& sub,
                                                     const ShadowSub& shadow)
{
    // A broken reference keeps its fingerprint, even when the name it holds is found again: an
    // exact reference the solver broke (Task 2 PR 7) still holds its element's name.
    if (!obj || !obj->isAttachedToDocument() || Data::hasMissingElement(shadow.oldName.c_str())) {
        return {};
    }
    const char* subname = !shadow.newName.empty() ? shadow.newName.c_str()
        : !shadow.oldName.empty()                 ? shadow.oldName.c_str()
                                                  : sub.c_str();
    ShadowSub elementName;
    GeoFeature* geo = nullptr;
    const char* element = nullptr;
    if (!GeoFeature::resolveElement(obj,
                                    subname,
                                    elementName,
                                    false,
                                    GeoFeature::Normal,
                                    feature,
                                    &element,
                                    &geo)
        || !geo || !element || !element[0] || elementName.oldName.empty()
        || GeoFeature::hasMissingElement(elementName.oldName.c_str())) {
        return {};
    }
    Data::ElementFingerprint fingerprint;
    if (!geo->getElementFingerprint(elementName.oldName.c_str(), fingerprint)) {
        return {};
    }
    return fingerprint.toString();
}

// Whether a reference with this record snaps back to its original when the original's name gives
// an element again (ops#127): a resolution by geometry, a guess, a rejected pick. Not an index
// carry (a naming migration moved the name: it gives another element now); the pieces of an
// expansion (a split or a continuation) merge back by the collapse rule.
static bool snapsBack(const GuessRecord& guess)
{
    return !guess.empty() && !guess.origName.empty() && guess.kind != "expanded"
        && guess.kind != "continued" && guess.kind != "index";
}

bool PropertyLinkBase::_updateElementFingerprints(App::DocumentObject* feature,
                                                  App::DocumentObject* obj,
                                                  const std::vector<App::DocumentObject*>* objs,
                                                  const std::vector<std::string>& subs,
                                                  const std::vector<ShadowSub>& shadows,
                                                  std::vector<std::string>& fingerprints)
{
    bool holdsElements = false;
    for (const auto& sub : subs) {
        const char* element = Data::findElementName(sub.c_str());
        holdsElements = holdsElements || (element && element[0]);
    }
    if (!holdsElements || !inSolverDocument()) {
        return holdsElements;
    }
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (owner && owner->isRestoring()) {
        return holdsElements;
    }
    if (fingerprints.size() != subs.size()) {
        // The list was rebuilt: the old fingerprints can't be matched to the references.
        fingerprints.assign(subs.size(), std::string());
    }
    // Restored, or attached to a target restored later: the saved fingerprints are kept until a
    // check has confirmed the element each name gives now (ops#116, the updates after opening),
    // since the target may have changed while this document was closed. Taken from the name's
    // element, a fingerprint would show the check the element where it is as where it was. An
    // empty one stays empty too: the check then knows it has none (rule 3's index test), and the
    // update after it fills it.
    auto doc = owner ? owner->getDocument() : nullptr;
    const bool keepSaved = !feature
        && ((doc && doc->testStatus(Document::Restoring) && !doc->testStatus(Document::Importing))
            || testFlag(LinkRestoring));
    for (std::size_t i = 0; i < subs.size(); ++i) {
        if (keepSaved) {
            continue;
        }
        auto target = objs ? (i < objs->size() ? (*objs)[i] : nullptr) : obj;
        auto text = _getElementFingerprint(feature,
                                           target,
                                           subs[i],
                                           i < shadows.size() ? shadows[i] : ShadowSub());
        // A reference that doesn't resolve keeps its last fingerprint, for the next retry.
        if (!text.empty()) {
            fingerprints[i] = std::move(text);
        }
    }
    return holdsElements;
}

void PropertyLinkBase::_registerElementReference(App::DocumentObject* obj,
                                                 std::string& sub,
                                                 ShadowSub& shadow)
{
    if (!obj || !obj->getNameInDocument() || sub.empty()) {
        return;
    }
    if (shadow.newName.empty()) {
        _updateElementReference(nullptr, obj, sub, shadow, false);
        return;
    }
    GeoFeature* geo = nullptr;
    const char* element = nullptr;
    ShadowSub elementName;
    GeoFeature::resolveElement(obj,
                               sub.c_str(),
                               elementName,
                               true,
                               GeoFeature::ElementNameType::Export,
                               nullptr,
                               &element,
                               &geo);
    if (!geo || !element || !element[0]) {
        if (!geo) {
            registerAtNextAttach(this, sub.c_str());
        }
        return;
    }

    if (_ElementRefs.insert(geo).second) {
        _ElementRefMap[geo].insert(this);
    }
}

class StringGuard
{
public:
    explicit StringGuard(char* c)
        : c(c)
    {
        v1 = c[0];
        v2 = c[1];
        c[0] = '.';
        c[1] = 0;
    }
    ~StringGuard()
    {
        c[0] = v1;
        c[1] = v2;
    }

    char* c;
    char v1;
    char v2;
};

void PropertyLinkBase::restoreLabelReference(const DocumentObject* obj,
                                             std::string& subname,
                                             ShadowSub* shadow)
{
    std::ostringstream ss;
    char* sub = &subname[0];
    char* next = sub;
    for (char* dot = strchr(next, '.'); dot; next = dot + 1, dot = strchr(next, '.')) {
        if (dot != next && dot[-1] != '@') {
            continue;
        }
        DocumentObject* sobj;
        try {
            StringGuard guard(dot - 1);
            sobj = obj->getSubObject(subname.c_str());
            if (!sobj) {
                FC_ERR("Failed to restore label reference " << obj->getFullName() << '.'
                                                            << ss.str());
                return;
            }
        }
        catch (...) {
            throw;
        }
        ss.write(sub, next - sub);
        ss << '$' << sobj->Label.getStrValue() << '.';
        sub = dot + 1;
    }
    if (sub == subname.c_str()) {
        return;
    }

    size_t count = sub - subname.c_str();
    const auto& newSub = ss.str();
    if (shadow && shadow->oldName.size() >= count) {
        shadow->oldName = newSub + (shadow->oldName.c_str() + count);
    }
    if (shadow && shadow->newName.size() >= count) {
        shadow->newName = newSub + (shadow->newName.c_str() + count);
    }
    subname = newSub + sub;
}

bool PropertyLinkBase::_updateElementReference(DocumentObject* feature,
                                               App::DocumentObject* obj,
                                               std::string& sub,
                                               ShadowSub& shadow,
                                               bool reverse,
                                               bool notify,
                                               std::vector<Data::MappedElement> *matchedNames)
{
    if (!obj || !obj->getNameInDocument()) {
        return false;
    }
    ShadowSub elementName;
    const char* subname;
    if (shadow.newName.size()) {
        subname = shadow.newName.c_str();
    }
    else if (shadow.oldName.size()) {
        subname = shadow.oldName.c_str();
    }
    else {
        subname = sub.c_str();
    }
    GeoFeature* geo = nullptr;
    const char* element = nullptr;
    auto ret = GeoFeature::resolveElement(obj,
                                          subname,
                                          elementName,
                                          true,
                                          GeoFeature::ElementNameType::Export,
                                          feature,
                                          &element,
                                          &geo);
    if (!ret || !geo || !element || !element[0]) {
        if (elementName.oldName.size()) {
            shadow.oldName.swap(elementName.oldName);
        }
        if (!feature && !geo) {
            // A registration (no feature) whose path doesn't resolve
            registerAtNextAttach(this, subname);
        }
        return false;
    }

    if (_ElementRefs.insert(geo).second) {
        _ElementRefMap[geo].insert(this);
    }

    // The lookup gave neither an index nor a missing marker, e.g. for an index-only missing
    // reference ('?Face3': a migration's or a retarget's break, ops#103, ops#106), whose marker it
    // takes for a mapped name. Nothing can resolve such a reference: it stays exactly as it is.
    // The code below would take it for a resolved one without an index, and in reverse write the
    // empty index into the sub (ops#123).
    const char* resolvedElement = Data::findElementName(elementName.oldName.c_str());
    if (!resolvedElement || !resolvedElement[0]) {
        return false;
    }

    if (!reverse) {
        if (elementName.newName.empty()) {
            shadow.oldName.swap(elementName.oldName);
            return false;
        }
        if (shadow == elementName) {
            return false;
        }
    }

    bool missing = GeoFeature::hasMissingElement(elementName.oldName.c_str());
    std::string why;
    // A reverse update (an element map version change: a naming migration, ops#103) re-derives
    // the reference from its geometry: the element the saved name gives now (nameHit) is
    // checked against the old element's, found at the stored index (oldElement) in the shape
    // before the change.
    const bool migrating = feature == geo && reverse && !inSolverDocument()
        && !Data::hasMissingElement(shadow.oldName.c_str());
    const std::string nameHit =
        migrating && !missing ? Data::findElementName(elementName.oldName.c_str()) : "";
    bool dropName = false;
    // In a reference solver document (ops#7) this is the exact lookup only: no name match, no
    // geometric search. The solver takes the references that miss.
    if (feature == geo && (missing || reverse) && !inSolverDocument()) {
        bool resolvedMissing = false;
        std::string nameMatch;  // the name match's pick, to tell a geometric override (ops#20)

        if (elementName.newName.size() && !reverse) {
            size_t prefixOffset = strlen(subname) - strlen(element);
            std::string namePrefix {subname, prefixOffset};

            const char* mappedNameString = Data::isMappedElement(elementName.newName.c_str() + prefixOffset);
            Data::MappedName searchName;

            if (mappedNameString) {
                const char* dot = strchr(mappedNameString, '.');

                if (dot) {
                    searchName = Data::MappedName(mappedNameString, static_cast<int>(dot - mappedNameString));
                } else {
                    searchName = mappedNameString;
                }

                std::vector<Data::MappedElement> foundMappedElements = geo->findSimilarNames(searchName);
                
                if (foundMappedElements.size()) {
                    std::string frontIndexedName = foundMappedElements.front().index.toString();
                    elementName.oldName = namePrefix + frontIndexedName;

                    std::ostringstream ss;
                    ss << namePrefix << Data::ComplexGeoData::elementMapPrefix() << foundMappedElements.front().name << '.' << frontIndexedName;

                    elementName.newName = ss.str();

                    missing = false;
                    nameMatch = elementName.oldName;

                    if (foundMappedElements.size() > 1) {
                        FC_WARN(propertyName(this)
                                << " guessed element reference " << ret->getFullName() << " "
                                << (shadow.newName.size() ? shadow.newName : shadow.oldName)
                                << " -> " << elementName.newName << ": "
                                << foundMappedElements.size()
                                << " names match, the first was taken"
                                << (canUseMultipleMatchedNames() ? " and the others added" : ""));
                    }
                }

                if (matchedNames != nullptr) {
                    *matchedNames = foundMappedElements;
                }
            }
        }

        // If the referenced element is missing, or we are generating element
        // map for the first time, or we are re-generating the element map due
        // to version change, i.e. 'reverse', try search by geometry first
        const char* oldElement = Data::findElementName(shadow.oldName.c_str());
        if (!Data::hasMissingElement(oldElement) && !resolvedMissing) {
            static const std::vector<std::string> noSnapshot;
            auto names = _InConsumerPass
                ? noSnapshot
                : geo->searchElementCache(oldElement, Data::SearchOption::CheckGeometry);
            if (names.empty() && !_InConsumerPass) {
                // try floating point tolerance
                names = geo->searchElementCache(oldElement, Data::SearchOptions());
            }
            if (names.size()) {
                missing = false;
                // Among several matches (coincident elements), a migration takes the stored
                // index, else the name's element (ops#103, rule 2)
                std::string pick = names.front();
                const char* taken = "the first";
                if (migrating && names.size() > 1) {
                    for (const auto& [preferred, which] :
                         {std::pair<std::string, const char*>(oldElement, "the stored index"),
                          std::pair<std::string, const char*>(nameHit, "the name's")}) {
                        if (!preferred.empty()
                            && std::find(names.begin(), names.end(), preferred) != names.end()) {
                            pick = preferred;
                            taken = which;
                            break;
                        }
                    }
                }
                std::string newsub(subname, strlen(subname) - strlen(element));
                newsub += pick;
                GeoFeature::resolveElement(obj,
                                           newsub.c_str(),
                                           elementName,
                                           true,
                                           GeoFeature::ElementNameType::Export,
                                           feature);
                const auto& oldName = shadow.newName.size() ? shadow.newName : shadow.oldName;
                const auto& newName =
                    elementName.newName.size() ? elementName.newName : elementName.oldName;
                if (names.size() > 1) {
                    FC_WARN(propertyName(this)
                            << " guessed element reference " << ret->getFullName() << " "
                            << oldName << " -> " << newName << ": " << names.size()
                            << " elements match the old geometry, " << taken << " was taken");
                }
                if (nameMatch.size() && nameMatch != elementName.oldName) {
                    FC_WARN(propertyName(this)
                            << " guessed element reference " << ret->getFullName() << " "
                            << oldName << " -> " << newName
                            << ": the geometric search overrode the name match " << nameMatch);
                }
                else if (oldName != newName) {
                    FC_LOG(propertyName(this)
                           << " auto change element reference " << ret->getFullName() << " "
                           << oldName << " -> " << newName);
                }
            }
            else if (migrating && !missing && oldElement && oldElement[0]
                     && nameHit != oldElement) {
                // The old element's geometry is gone and the saved name now gives another
                // element: broken, not moved (ops#103, rule 1). An index-only missing reference,
                // so that no later lookup follows the name either.
                missing = true;
                dropName = true;
                why = " (re-derived from geometry: the old element is gone, and its name now gives "
                    + nameHit + ", not taken)";
                elementName.oldName = shadow.oldName;
                std::size_t at = oldElement - shadow.oldName.c_str();
                elementName.oldName.insert(at, Data::MISSING_PREFIX);
                elementName.newName = shadow.newName;  // for the warning
            }
        }
    }

    // The first resolution of a sub that a link retarget made index-only (ops#106): the index
    // must name an element that agrees with the one the reference named on the old target, or
    // the reference goes missing, never to another element. The check is used up either way.
    if (!reverse && shadow.newName.empty()) {
        auto checks = _RetargetChecks.find(this);
        if (checks != _RetargetChecks.end()) {
            auto& list = checks->second;
            auto check = std::find_if(list.begin(), list.end(), [&](const auto& entry) {
                return entry.obj == obj && entry.sub == sub;
            });
            if (check != list.end() && !missing) {
                Data::ElementFingerprint now;
                const char* newElement = Data::findElementName(elementName.oldName.c_str());
                if (!newElement || !newElement[0] || !geo->getElementFingerprint(newElement, now)
                    || !retargetAgrees(check->before, now)) {
                    missing = true;
                    why = " (the link's new target has another kind of element at that index)";
                    std::size_t at = newElement ? newElement - elementName.oldName.c_str() : 0;
                    elementName.oldName.insert(at, Data::MISSING_PREFIX);
                    elementName.newName.clear();
                }
            }
            if (check != list.end()) {
                list.erase(check);
                if (list.empty()) {
                    _RetargetChecks.erase(checks);
                }
            }
        }
    }

    if (notify) {
        aboutToSetValue();
    }

    auto updateSub = [&](const std::string& newSub) {
        if (sub != newSub) {
            // signalUpdateElementReference(sub, newSub);
            sub = newSub;
        }
    };

    if (missing) {
        FC_WARN(propertyName(this)
                << " missing element reference " << ret->getFullName() << " "
                << (elementName.newName.size() ? elementName.newName : elementName.oldName)
                << why);
        shadow.oldName.swap(elementName.oldName);
        if (dropName) {
            shadow.newName.clear();
        }
    }
    else {
        FC_TRACE(propertyName(this) << " element reference shadow update " << ret->getFullName()
                                    << " " << shadow.newName << " -> " << elementName.newName);
        shadow.swap(elementName);
        if (shadow.newName.size() && Data::hasMappedElementName(sub.c_str())) {
            updateSub(shadow.newName);
        }
    }

    if (migrating) {
        auto outcome = MigrationOutcome::Kept;
        if (missing) {
            outcome = MigrationOutcome::Broken;
        }
        else if (nameHit != Data::findElementName(shadow.oldName.c_str())) {
            outcome = MigrationOutcome::Moved;
        }
        countReferenceMigration(freecad_cast<DocumentObject*>(getContainer()), outcome);
    }

    if (reverse) {
        if (shadow.newName.size() && Data::hasMappedElementName(sub.c_str())) {
            updateSub(shadow.newName);
        }
        else {
            updateSub(shadow.oldName);
        }
        return true;
    }
    if (missing) {
        if (sub != shadow.newName) {
            updateSub(shadow.oldName);
        }
        return true;
    }
    auto pos2 = shadow.newName.rfind('.');
    if (pos2 == std::string::npos) {
        return true;
    }
    ++pos2;
    auto pos = sub.rfind('.');
    if (pos == std::string::npos) {
        pos = 0;
    }
    else {
        ++pos;
    }
    if (pos == pos2) {
        if (sub.compare(pos, sub.size() - pos, &shadow.newName[pos2]) != 0) {
            FC_LOG("element reference update " << sub << " -> " << shadow.newName);
            std::string newSub(sub);
            newSub.replace(pos, sub.size() - pos, &shadow.newName[pos2]);
            updateSub(newSub);
        }
    }
    else if (sub != shadow.oldName) {
        FC_LOG("element reference update " << sub << " -> " << shadow.oldName);
        updateSub(shadow.oldName);
    }
    return true;
}

std::pair<DocumentObject*, std::string>
PropertyLinkBase::tryReplaceLink(const PropertyContainer* owner,
                                 DocumentObject* obj,
                                 const DocumentObject* parent,
                                 DocumentObject* oldObj,
                                 DocumentObject* newObj,
                                 const char* subname)
{
    std::pair<DocumentObject*, std::string> res;
    res.first = 0;
    if (!obj) {
        return res;
    }

    if (oldObj == obj) {
        if (owner == parent) {
            res.first = newObj;
            if (subname) {
                res.second = subname;
            }
            return res;
        }
        return res;
    }
    else if (newObj == obj) {
        // This means the new object is already sub-object of this parent
        // (consider a case of swapping the tool and base object of the Cut
        // feature). We'll swap the old and new object.
        return tryReplaceLink(owner, obj, parent, newObj, oldObj, subname);
    }
    if (!subname || !subname[0]) {
        return res;
    }

    App::DocumentObject* prev = obj;
    std::size_t prevPos = 0;
    std::string sub = subname;
    for (auto pos = sub.find('.'); pos != std::string::npos; pos = sub.find('.', pos)) {
        ++pos;
        char c = sub[pos];
        if (c == '.') {
            continue;
        }
        sub[pos] = 0;
        auto sobj = obj->getSubObject(sub.c_str());
        sub[pos] = c;
        if (!sobj) {
            break;
        }
        if (sobj == oldObj) {
            if (prev == parent) {
                if (sub[prevPos] == '$') {
                    sub.replace(prevPos + 1, pos - 1 - prevPos, newObj->Label.getValue());
                }
                else {
                    sub.replace(prevPos, pos - 1 - prevPos, newObj->getNameInDocument());
                }
                res.first = obj;
                res.second = std::move(sub);
                return res;
            }
            break;
        }
        else if (sobj == newObj) {
            return tryReplaceLink(owner, obj, parent, newObj, oldObj, subname);
        }
        else if (prev == parent) {
            break;
        }
        prev = sobj;
        prevPos = pos;
    }
    return res;
}

std::pair<DocumentObject*, std::vector<std::string>>
PropertyLinkBase::tryReplaceLinkSubs(const PropertyContainer* owner,
                                     DocumentObject* obj,
                                     const DocumentObject* parent,
                                     DocumentObject* oldObj,
                                     DocumentObject* newObj,
                                     const std::vector<std::string>& subs)
{
    std::pair<DocumentObject*, std::vector<std::string>> res;
    res.first = 0;
    if (!obj) {
        return res;
    }

    auto r = tryReplaceLink(owner, obj, parent, oldObj, newObj);
    if (r.first) {
        res.first = r.first;
        res.second = subs;
        return res;
    }
    for (auto it = subs.begin(); it != subs.end(); ++it) {
        auto r = tryReplaceLink(owner, obj, parent, oldObj, newObj, it->c_str());
        if (r.first) {
            if (!res.first) {
                res.first = r.first;
                res.second.insert(res.second.end(), subs.begin(), it);
            }
            res.second.push_back(std::move(r.second));
        }
        else if (res.first) {
            res.second.push_back(*it);
        }
    }
    return res;
}

//**************************************************************************
//**************************************************************************
// PropertyLinkListBase
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE_ABSTRACT(App::PropertyLinkListBase, App::PropertyLinkBase)

//**************************************************************************
//**************************************************************************
// PropertyLink
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyLink, App::PropertyLinkBase)
TYPESYSTEM_SOURCE(App::PropertyLinkChild, App::PropertyLink)
TYPESYSTEM_SOURCE(App::PropertyLinkGlobal, App::PropertyLink)
TYPESYSTEM_SOURCE(App::PropertyLinkHidden, App::PropertyLink)

//**************************************************************************
// Construction/Destruction


PropertyLink::PropertyLink() = default;

PropertyLink::~PropertyLink()
{
    resetLink();
}

//**************************************************************************
// Base class implementer

void PropertyLink::resetLink()
{
    // in case this property gets dynamically removed
    // maintain the back link in the DocumentObject class if it is from a document object
    if (_pcScope != LinkScope::Hidden && _pcLink && getContainer()
        && getContainer()->isDerivedFrom<App::DocumentObject>()) {
        App::DocumentObject* parent = static_cast<DocumentObject*>(getContainer());
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy)) {
            if (_pcLink) {
                _pcLink->_removeBackLink(parent);
                _pcLink->_removeBackLinkProp(getName(), parent);
            }
        }
    }
    _pcLink = nullptr;
}

void PropertyLink::setValue(App::DocumentObject* lValue)
{
    auto parent = dynamic_cast<App::DocumentObject*>(getContainer());
    if (!testFlag(LinkAllowExternal) && parent && lValue
        && parent->getDocument() != lValue->getDocument()) {
        throw Base::ValueError("PropertyLink does not support external object");
    }

    aboutToSetValue();

    // maintain the back link in the DocumentObject class if it is from a document object
    if (_pcScope != LinkScope::Hidden && parent) {
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy)) {
            if (_pcLink) {
                _pcLink->_removeBackLink(parent);
                _pcLink->_removeBackLinkProp(getName(), parent);
            }
            if (lValue) {
                lValue->_addBackLink(parent);
                lValue->_addBackLinkProp(getName(), parent);
            }
        }
    }

    _pcLink = lValue;
    hasSetValue();
}

App::DocumentObject* PropertyLink::getValue() const
{
    return _pcLink;
}

App::DocumentObject* PropertyLink::getValue(Base::Type t) const
{
    return (_pcLink && _pcLink->isDerivedFrom(t)) ? _pcLink : nullptr;
}

PyObject* PropertyLink::getPyObject()
{
    if (_pcLink) {
        return _pcLink->getPyObject();
    }
    else {
        Py_Return;
    }
}

void PropertyLink::setPyObject(PyObject* value)
{
    Base::PyTypeCheck(&value, &DocumentObjectPy::Type);
    if (value) {
        DocumentObjectPy* pcObject = static_cast<DocumentObjectPy*>(value);
        setValue(pcObject->getDocumentObjectPtr());
    }
    else {
        setValue(nullptr);
    }
}

void PropertyLink::Save(Base::Writer& writer) const
{
    writer.Stream() << writer.ind() << "<Link value=\"" << (_pcLink ? _pcLink->getExportName() : "")
                    << "\"/>" << std::endl;
}

void PropertyLink::Restore(Base::XMLReader& reader)
{
    // read my element
    reader.readElement("Link");
    // get the value of my attribute
    std::string name = reader.getName(reader.getAttribute<const char*>("value"));

    // Property not in a DocumentObject!
    assert(getContainer()->isDerivedFrom<App::DocumentObject>());

    if (!name.empty()) {
        DocumentObject* parent = static_cast<DocumentObject*>(getContainer());

        App::Document* document = parent->getDocument();
        DocumentObject* object = document ? document->getObject(name.c_str()) : nullptr;
        if (!object) {
            if (reader.isVerbose()) {
                Base::Console().warning("Lost link to '%s' while loading, maybe "
                                        "an object was not loaded correctly\n",
                                        name.c_str());
            }
        }
        else if (parent == object) {
            if (reader.isVerbose()) {
                Base::Console().warning("Object '%s' links to itself, nullify it\n", name.c_str());
            }
            object = nullptr;
        }

        setValue(object);
    }
    else {
        setValue(nullptr);
    }
}

Property* PropertyLink::Copy() const
{
    PropertyLink* p = new PropertyLink();
    p->_pcLink = _pcLink;
    return p;
}

void PropertyLink::Paste(const Property& from)
{
    if (!from.isDerivedFrom<PropertyLink>()) {
        throw Base::TypeError("Incompatible property to paste to");
    }

    setValue(static_cast<const PropertyLink&>(from)._pcLink);
}

void PropertyLink::getLinks(std::vector<App::DocumentObject*>& objs,
                            bool all,
                            std::vector<std::string>* subs,
                            bool newStyle) const
{
    (void)newStyle;
    (void)subs;
    if ((all || _pcScope != LinkScope::Hidden) && _pcLink && _pcLink->isAttachedToDocument()) {
        objs.push_back(_pcLink);
    }
}

void PropertyLink::getLinksTo(std::vector<App::ObjectIdentifier>& identifiers,
                              App::DocumentObject* obj,
                              const char* subname,
                              bool all) const
{
    (void)subname;
    if (!all && _pcScope == LinkScope::Hidden) {
        return;  // Don't get hidden links unless all is specified.
    }
    if (obj && _pcLink == obj) {
        identifiers.emplace_back(*this);
    }
}

void PropertyLink::breakLink(App::DocumentObject* obj, bool clear)
{
    if (_pcLink == obj || (clear && getContainer() == obj)) {
        setValue(nullptr);
    }
}

bool PropertyLink::adjustLink(const std::set<App::DocumentObject*>& inList)
{
    (void)inList;
    return false;
}

Property* PropertyLink::CopyOnLinkReplace(const App::DocumentObject* parent,
                                          App::DocumentObject* oldObj,
                                          App::DocumentObject* newObj) const
{
    auto res = tryReplaceLink(getContainer(), _pcLink, parent, oldObj, newObj);
    if (res.first) {
        auto p = new PropertyLink();
        p->_pcLink = res.first;
        return p;
    }
    return nullptr;
}

//**************************************************************************
// PropertyLinkList
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyLinkList, App::PropertyLinkListBase)
TYPESYSTEM_SOURCE(App::PropertyLinkListChild, App::PropertyLinkList)
TYPESYSTEM_SOURCE(App::PropertyLinkListGlobal, App::PropertyLinkList)
TYPESYSTEM_SOURCE(App::PropertyLinkListHidden, App::PropertyLinkList)

//**************************************************************************
// Construction/Destruction


PropertyLinkList::PropertyLinkList() = default;

PropertyLinkList::~PropertyLinkList()
{
    // in case this property gety dynamically removed

    // maintain the back link in the DocumentObject class
    if (_pcScope != LinkScope::Hidden && !_lValueList.empty() && getContainer()
        && getContainer()->isDerivedFrom<App::DocumentObject>()) {
        App::DocumentObject* parent = static_cast<DocumentObject*>(getContainer());
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy)) {
            for (auto* obj : _lValueList) {
                if (obj) {
                    obj->_removeBackLink(parent);
                    obj->_removeBackLinkProp(getName(), parent);
                }
            }
        }
    }
}

void PropertyLinkList::setSize(int newSize)
{
    for (int i = newSize; i < (int)_lValueList.size(); ++i) {
        auto obj = _lValueList[i];
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        _nameMap.erase(obj->getNameInDocument());

        if (_pcScope != LinkScope::Hidden) {
            obj->_removeBackLink(static_cast<DocumentObject*>(getContainer()));
            obj->_removeBackLinkProp(getName(), static_cast<DocumentObject*>(getContainer()));
        }
    }
    _lValueList.resize(newSize);
}

void PropertyLinkList::setSize(int newSize, const_reference def)
{
    auto oldSize = getSize();
    setSize(newSize);
    for (auto i = oldSize; i < newSize; ++i) {
        _lValueList[i] = def;
    }
}

void PropertyLinkList::set1Value(int idx, DocumentObject* const& value)
{
    DocumentObject* obj = nullptr;
    if (idx >= 0 && idx < (int)_lValueList.size()) {
        obj = _lValueList[idx];
        if (obj == value) {
            return;
        }
    }

    if (!value || !value->isAttachedToDocument()) {
        throw Base::ValueError("invalid document object");
    }

    _nameMap.clear();

    if (getContainer() && getContainer()->isDerivedFrom<App::DocumentObject>()) {
        App::DocumentObject* parent = static_cast<DocumentObject*>(getContainer());
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            if (obj) {
                obj->_removeBackLink(static_cast<DocumentObject*>(getContainer()));
                obj->_removeBackLinkProp(getName(), static_cast<DocumentObject*>(getContainer()));
            }
            if (value) {
                value->_addBackLink(static_cast<DocumentObject*>(getContainer()));
                value->_addBackLinkProp(getName(), static_cast<DocumentObject*>(getContainer()));
            }
        }
    }

    inherited::set1Value(idx, value);
}

void PropertyLinkList::setValues(const std::vector<DocumentObject*>& value)
{
    if (value.size() == 1 && !value[0]) {
        // one null element means clear, as backward compatibility for old code
        setValues(std::vector<DocumentObject*>());
        return;
    }

    auto parent = freecad_cast<App::DocumentObject*>(getContainer());
    for (auto obj : value) {
        if (!obj || !obj->isAttachedToDocument()) {
            throw Base::ValueError("PropertyLinkList: invalid document object");
        }
        if (!testFlag(LinkAllowExternal) && parent && parent->getDocument() != obj->getDocument()) {
            throw Base::ValueError("PropertyLinkList does not support external object");
        }
    }
    _nameMap.clear();

    // maintain the back link in the DocumentObject class
    if (parent) {
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            for (auto* obj : _lValueList) {
                if (obj) {
                    obj->_removeBackLink(parent);
                    obj->_removeBackLinkProp(getName(), parent);
                }
            }
            for (auto* obj : value) {
                if (obj) {
                    obj->_addBackLink(parent);
                    obj->_addBackLinkProp(getName(), parent);
                }
            }
        }
    }

    inherited::setValues(value);
}

PyObject* PropertyLinkList::getPyObject()
{
    int count = getSize();
#if 0  // FIXME: Should switch to tuple
    Py::Tuple sequence(count);
#else
    Py::List sequence(count);
#endif
    for (int i = 0; i < count; i++) {
        auto obj = _lValueList[i];
        if (obj && obj->isAttachedToDocument()) {
            sequence.setItem(i, Py::asObject(_lValueList[i]->getPyObject()));
        }
        else {
            sequence.setItem(i, Py::None());
        }
    }

    return Py::new_reference_to(sequence);
}

DocumentObject* PropertyLinkList::getPyValue(PyObject* item) const
{
    Base::PyTypeCheck(&item, &DocumentObjectPy::Type);

    return item ? static_cast<DocumentObjectPy*>(item)->getDocumentObjectPtr() : nullptr;
}

void PropertyLinkList::Save(Base::Writer& writer) const
{
    writer.Stream() << writer.ind() << "<LinkList count=\"" << getSize() << "\">" << endl;
    writer.incInd();
    for (int i = 0; i < getSize(); i++) {
        DocumentObject* obj = _lValueList[i];
        if (obj) {
            writer.Stream() << writer.ind() << "<Link value=\"" << obj->getExportName() << "\"/>"
                            << endl;
        }
        else {
            writer.Stream() << writer.ind() << "<Link value=\"\"/>" << endl;
        }
    }

    writer.decInd();
    writer.Stream() << writer.ind() << "</LinkList>" << endl;
}

void PropertyLinkList::Restore(Base::XMLReader& reader)
{
    // read my element
    reader.readElement("LinkList");
    // get the value of my attribute
    int count = reader.getAttribute<long>("count");
    App::PropertyContainer* container = getContainer();
    if (!container) {
        throw Base::RuntimeError("Property is not part of a container");
    }
    if (!container->isDerivedFrom<App::DocumentObject>()) {
        std::stringstream str;
        str << "Container is not a document object (" << container->getTypeId().getName() << ")";
        throw Base::TypeError(str.str());
    }

    std::vector<DocumentObject*> values;
    values.reserve(count);
    for (int i = 0; i < count; i++) {
        reader.readElement("Link");
        std::string name = reader.getName(reader.getAttribute<const char*>("value"));
        // In order to do copy/paste it must be allowed to have defined some
        // referenced objects in XML which do not exist anymore in the new
        // document. Thus, we should silently ignore this.
        // Property not in an object!
        DocumentObject* father = static_cast<DocumentObject*>(getContainer());
        App::Document* document = father->getDocument();
        DocumentObject* child = document ? document->getObject(name.c_str()) : nullptr;
        if (child) {
            values.push_back(child);
        }
        else if (reader.isVerbose()) {
            FC_WARN("Lost link to " << (document ? document->getName() : "") << " " << name
                                    << " while loading, maybe an object was not loaded correctly");
        }
    }

    reader.readEndElement("LinkList");

    // assignment
    setValues(values);
}

Property* PropertyLinkList::CopyOnLinkReplace(const App::DocumentObject* parent,
                                              App::DocumentObject* oldObj,
                                              App::DocumentObject* newObj) const
{
    std::vector<DocumentObject*> links;
    bool copied = false;
    bool found = false;
    for (auto it = _lValueList.begin(); it != _lValueList.end(); ++it) {
        auto res = tryReplaceLink(getContainer(), *it, parent, oldObj, newObj);
        if (res.first) {
            found = true;
            if (!copied) {
                copied = true;
                links.insert(links.end(), _lValueList.begin(), it);
            }
            links.push_back(res.first);
        }
        else if (*it == newObj) {
            // in case newObj already exists here, we shall remove all existing
            // entry, and insert it to take over oldObj's position.
            if (!copied) {
                copied = true;
                links.insert(links.end(), _lValueList.begin(), it);
            }
        }
        else if (copied) {
            links.push_back(*it);
        }
    }
    if (!found) {
        return nullptr;
    }
    auto p = new PropertyLinkList();
    p->_lValueList = std::move(links);
    return p;
}

Property* PropertyLinkList::Copy() const
{
    PropertyLinkList* p = new PropertyLinkList();
    p->_lValueList = _lValueList;
    return p;
}

void PropertyLinkList::Paste(const Property& from)
{
    if (!from.isDerivedFrom<PropertyLinkList>()) {
        throw Base::TypeError("Incompatible property to paste to");
    }

    setValues(static_cast<const PropertyLinkList&>(from)._lValueList);
}

unsigned int PropertyLinkList::getMemSize() const
{
    return static_cast<unsigned int>(_lValueList.size() * sizeof(App::DocumentObject*));
}


DocumentObject* PropertyLinkList::find(const char* name, int* pindex) const
{
    const int DONT_MAP_UNDER = 10;
    if (!name) {
        return nullptr;
    }
    if (_lValueList.size() <= DONT_MAP_UNDER) {
        int index = -1;
        for (auto obj : _lValueList) {
            ++index;
            if (obj && obj->getNameInDocument() && boost::equals(name, obj->getNameInDocument())) {
                if (pindex) {
                    *pindex = index;
                }
                return obj;
            }
        }
        return nullptr;
    }
    // We're using a map.  Do we need to (re)create it?
    if (_nameMap.empty() || _nameMap.size() > _lValueList.size()) {
        _nameMap.clear();
        for (int i = 0; i < (int)_lValueList.size(); ++i) {
            auto obj = _lValueList[i];
            if (obj && obj->isAttachedToDocument()) {
                _nameMap[obj->getNameInDocument()] = i;
            }
        }
    }
    // Now lookup up in that map
    auto it = _nameMap.find(name);
    if (it == _nameMap.end()) {
        return nullptr;
    }
    if (pindex) {
        *pindex = it->second;
    }
    return _lValueList[it->second];
}

DocumentObject* PropertyLinkList::findUsingMap(const std::string& name, int* pindex) const
{
    if (_nameMap.size() == _lValueList.size()) {
        auto it = _nameMap.find(name);
        if (it == _nameMap.end()) {
            return nullptr;
        }
        if (pindex) {
            *pindex = it->second;
        }
        return _lValueList[it->second];
    }
    return find(name.c_str(), pindex);
}

void PropertyLinkList::getLinks(std::vector<App::DocumentObject*>& objs,
                                bool all,
                                std::vector<std::string>* subs,
                                bool newStyle) const
{
    (void)subs;
    (void)newStyle;
    if (all || _pcScope != LinkScope::Hidden) {
        objs.reserve(objs.size() + _lValueList.size());
        for (auto obj : _lValueList) {
            if (obj && obj->isAttachedToDocument()) {
                objs.push_back(obj);
            }
        }
    }
}

void PropertyLinkList::getLinksTo(std::vector<App::ObjectIdentifier>& identifiers,
                                  App::DocumentObject* obj,
                                  const char* subname,
                                  bool all) const
{
    (void)subname;
    if (!obj || (!all && _pcScope == LinkScope::Hidden)) {
        return;
    }
    int i = -1;
    for (auto docObj : _lValueList) {
        ++i;
        if (docObj == obj) {
            identifiers.emplace_back(*this, i);
            break;
        }
    }
}

void PropertyLinkList::breakLink(App::DocumentObject* obj, bool clear)
{
    if (clear && getContainer() == obj) {
        setValues({});
        return;
    }
    std::vector<App::DocumentObject*> values;
    values.reserve(_lValueList.size());
    for (auto o : _lValueList) {
        if (o != obj) {
            values.push_back(o);
        }
    }
    if (values.size() != _lValueList.size()) {
        setValues(values);
    }
}

bool PropertyLinkList::adjustLink(const std::set<App::DocumentObject*>& inList)
{
    (void)inList;
    return false;
}


//**************************************************************************
// PropertyLinkSub
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyLinkSub, App::PropertyLinkBase)
TYPESYSTEM_SOURCE(App::PropertyLinkSubChild, App::PropertyLinkSub)
TYPESYSTEM_SOURCE(App::PropertyLinkSubGlobal, App::PropertyLinkSub)
TYPESYSTEM_SOURCE(App::PropertyLinkSubHidden, App::PropertyLinkSub)

//**************************************************************************
// Construction/Destruction


PropertyLinkSub::PropertyLinkSub() = default;

PropertyLinkSub::~PropertyLinkSub()
{
    // in case this property is dynamically removed

    if (_pcLinkSub && getContainer()
        && getContainer()->isDerivedFrom<App::DocumentObject>()) {
        App::DocumentObject* parent = static_cast<DocumentObject*>(getContainer());
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            if (_pcLinkSub) {
                _pcLinkSub->_removeBackLink(parent);
                _pcLinkSub->_removeBackLinkProp(getName(), parent);
            }
        }
    }
}

void PropertyLinkSub::setSyncSubObject(bool enable)
{
    _Flags.set((std::size_t)LinkSyncSubObject, enable);
}

void PropertyLinkSub::setValue(App::DocumentObject* lValue,
                               const std::vector<std::string>& SubList,
                               std::vector<ShadowSub>&& shadows)
{
    setValue(lValue, std::vector<std::string>(SubList), std::move(shadows));
}

void PropertyLinkSub::setValue(App::DocumentObject* lValue,
                               std::vector<std::string>&& subs,
                               std::vector<ShadowSub>&& shadows)
{
    auto parent = freecad_cast<App::DocumentObject*>(getContainer());
    if (lValue) {
        if (!lValue->isAttachedToDocument()) {
            throw Base::ValueError("PropertyLinkSub: invalid document object");
        }
        if (!testFlag(LinkAllowExternal) && parent
            && parent->getDocument() != lValue->getDocument()) {
            throw Base::ValueError("PropertyLinkSub does not support external object");
        }
    }
    aboutToSetValue();

    if (parent) {
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            if (_pcLinkSub) {
                _pcLinkSub->_removeBackLink(parent);
                _pcLinkSub->_removeBackLinkProp(getName(), parent);
            }
            if (lValue) {
                lValue->_addBackLink(parent);
                lValue->_addBackLinkProp(getName(), parent);
            }
        }
    }

    // `from` (Task 2 PR 7) stays with a reference the caller passes on with its shadow (a
    // restore, a paste, the relink); a sub chosen anew (no shadow, or no shadows at all) drops it.
    // So do a guess record and the reorder's re-target record (ops#127).
    keepRetargetRecords(_Retargets, subs.size(), shadows);
    if (shadows.size() != subs.size() || _ExpandedFrom.size() != subs.size()) {
        _ExpandedFrom.assign(subs.size(), std::string());
    }
    else {
        for (std::size_t i = 0; i < subs.size(); ++i) {
            if (shadows[i].oldName.empty() && shadows[i].newName.empty()) {
                _ExpandedFrom[i].clear();
            }
        }
    }
    if (shadows.size() != subs.size() || _Guesses.size() != subs.size()) {
        _Guesses.assign(subs.size(), GuessRecord());
    }
    else {
        for (std::size_t i = 0; i < subs.size(); ++i) {
            if (shadows[i].oldName.empty() && shadows[i].newName.empty()) {
                _Guesses[i] = GuessRecord();
            }
        }
    }
    _pcLinkSub = lValue;
    _cSubList = std::move(subs);
    if (shadows.size() == _cSubList.size()) {
        _ShadowSubList = std::move(shadows);
        onContainerRestored();  // re-register element references
    }
    else {
        updateElementReference(nullptr);
    }
    checkLabelReferences(_cSubList);
    hasSetValue();
}

App::DocumentObject* PropertyLinkSub::getValue() const
{
    return _pcLinkSub;
}

const std::vector<std::string>& PropertyLinkSub::getSubValues() const
{
    return _cSubList;
}

static inline const std::string& getSubNameWithStyle(const std::string& subName,
                                                     const PropertyLinkBase::ShadowSub& shadow,
                                                     bool newStyle,
                                                     std::string& tmp)
{
    if (!newStyle) {
        if (!shadow.oldName.empty()) {
            return shadow.oldName;
        }
    }
    else if (!shadow.newName.empty()) {
        if (Data::hasMissingElement(shadow.oldName.c_str())) {
            auto pos = shadow.newName.rfind('.');
            if (pos != std::string::npos) {
                tmp = shadow.newName.substr(0, pos + 1);
                tmp += shadow.oldName;
                return tmp;
            }
        }
        return shadow.newName;
    }
    return subName;
}

std::vector<std::string> PropertyLinkSub::getSubValues(bool newStyle) const
{
    assert(_cSubList.size() == _ShadowSubList.size());
    std::vector<std::string> ret;
    ret.reserve(_cSubList.size());
    std::string tmp;
    for (size_t i = 0; i < _ShadowSubList.size(); ++i) {
        ret.push_back(getSubNameWithStyle(_cSubList[i], _ShadowSubList[i], newStyle, tmp));
    }
    return ret;
}

std::vector<std::string> PropertyLinkSub::getSubValuesStartsWith(const char* starter,
                                                                 bool newStyle) const
{
    assert(_cSubList.size() == _ShadowSubList.size());
    std::vector<std::string> ret;
    std::string tmp;
    for (size_t i = 0; i < _ShadowSubList.size(); ++i) {
        const auto& sub = getSubNameWithStyle(_cSubList[i], _ShadowSubList[i], newStyle, tmp);
        auto element = Data::findElementName(sub.c_str());
        if (element && boost::starts_with(element, starter)) {
            ret.emplace_back(element);
        }
    }
    return ret;
}

App::DocumentObject* PropertyLinkSub::getValue(Base::Type t) const
{
    return (_pcLinkSub && _pcLinkSub->isDerivedFrom(t)) ? _pcLinkSub : nullptr;
}

PyObject* PropertyLinkSub::getPyObject()
{
    Py::Tuple tup(2);
    Py::List list(static_cast<int>(_cSubList.size()));
    if (_pcLinkSub) {
        tup[0] = Py::asObject(_pcLinkSub->getPyObject());
        int i = 0;
        for (auto& sub : getSubValues(testFlag(LinkNewElement))) {
            list[i++] = Py::String(sub);
        }
        tup[1] = list;
        return Py::new_reference_to(tup);
    }
    else {
        return Py::new_reference_to(Py::None());
    }
}

void PropertyLinkSub::setPyObject(PyObject* value)
{
    if (PyObject_TypeCheck(value, &(DocumentObjectPy::Type))) {
        DocumentObjectPy* pcObject = static_cast<DocumentObjectPy*>(value);
        setValue(pcObject->getDocumentObjectPtr());
    }
    else if (PyTuple_Check(value) || PyList_Check(value)) {
        Py::Sequence seq(value);
        if (seq.size() == 0) {
            setValue(nullptr);
        }
        else if (seq.size() != 2) {
            throw Base::ValueError("Expect input sequence of size 2");
        }
        else if (PyObject_TypeCheck(seq[0].ptr(), &(DocumentObjectPy::Type))) {
            DocumentObjectPy* pcObj = static_cast<DocumentObjectPy*>(seq[0].ptr());
            static const char* errMsg =
                "type of second element in tuple must be str or sequence of str";
            PropertyString propString;
            if (seq[1].isString()) {
                std::vector<std::string> vals;
                propString.setPyObject(seq[1].ptr());
                vals.emplace_back(propString.getValue());
                setValue(pcObj->getDocumentObjectPtr(), std::move(vals));
            }
            else if (seq[1].isSequence()) {
                Py::Sequence list(seq[1]);
                std::vector<std::string> vals(list.size());
                unsigned int i = 0;
                for (Py::Sequence::iterator it = list.begin(); it != list.end(); ++it, ++i) {
                    if (!(*it).isString()) {
                        throw Base::TypeError(errMsg);
                    }
                    propString.setPyObject((*it).ptr());
                    vals[i] = propString.getValue();
                }
                setValue(pcObj->getDocumentObjectPtr(), std::move(vals));
            }
            else {
                throw Base::TypeError(errMsg);
            }
        }
        else {
            std::string error =
                std::string("type of first element in tuple must be 'DocumentObject', not ");
            error += seq[0].ptr()->ob_type->tp_name;
            throw Base::TypeError(error);
        }
    }
    else if (Py_None == value) {
        setValue(nullptr);
    }
    else {
        std::string error = std::string(
            "type must be 'DocumentObject', 'NoneType' or ('DocumentObject',['String',]) not ");
        error += value->ob_type->tp_name;
        throw Base::TypeError(error);
    }
}

static bool updateLinkReference(App::PropertyLinkBase* prop,
                                App::DocumentObject* feature,
                                bool reverse,
                                bool notify,
                                App::DocumentObject* link,
                                std::vector<std::string>& subs,
                                std::vector<int>& mapped,
                                std::vector<PropertyLinkBase::ShadowSub>& shadows)
{
    if (!feature) {
        shadows.clear();
        prop->unregisterElementReference();
    }
    shadows.resize(subs.size());
    if (!link || !link->isAttachedToDocument()) {
        return false;
    }
    auto owner = freecad_cast<DocumentObject*>(prop->getContainer());
    if (owner && owner->isRestoring()) {
        return false;
    }
    if (feature && prop->inSolverDocument()) {
        // The reference solver (ops#7), for this property alone. It notifies itself, so the
        // caller is told of a change only when it doesn't notify.
        bool changed = App::solveElementReferences(feature, {prop}, reverse, notify);
        return changed && !notify;
    }
    bool touched = false;
    std::vector<Data::MappedElement> extraMatchedNames;
    std::ostringstream ss;

    std::vector<std::string> newSubs = { };
    std::vector<PropertyLinkBase::ShadowSub> newShadows = { };

    for (size_t i = 0; i < subs.size(); i++) {
        if (prop->_updateElementReference(feature,
                                          link,
                                          subs[i],
                                          shadows[i],
                                          reverse,
                                          notify && !touched,
                                          &extraMatchedNames))
        {
            // let's do the name matching here
            if (extraMatchedNames.size() > 1 && prop->canUseMultipleMatchedNames()) {
                extraMatchedNames.erase(extraMatchedNames.begin());

                for (const Data::MappedElement &mappedElement : extraMatchedNames) {
                    std::string name = mappedElement.name.toString();
                    std::string index = mappedElement.index.toString();

                    ss << Data::ComplexGeoData::elementMapPrefix() << name << '.' << index;

                    if (prop->canHaveDuplicateLinks() || std::find(newSubs.begin(), newSubs.end(), index) == newSubs.end()) {
                        newShadows.emplace_back(ss.str(), index);
                        newSubs.push_back(index);
                    }
                    
                    ss.str("");
                }
            }

            extraMatchedNames.clear();

            touched = true;
        }

        if (prop->canHaveDuplicateLinks() || std::find(newSubs.begin(), newSubs.end(), subs[i]) == newSubs.end()) {
            newShadows.push_back(shadows[i]);
            newSubs.push_back(subs[i]);
        }
    }
    if (!touched) {
        return false;
    }
    subs = newSubs;
    shadows = newShadows;
    for (int idx : mapped) {
        if (idx < (int)subs.size() && !shadows[idx].newName.empty()) {
            subs[idx] = shadows[idx].newName;
        }
    }
    mapped.clear();
    if (owner && feature) {
        owner->onUpdateElementReference(prop);
    }
    return true;
}

// Where the path of sub, up to its element, passes through link (ops#42): the offset in sub just
// after the object on the path that is link or leads to it (a link to a link counts too), or
// std::string::npos if the offset isn't known; nothing if the path doesn't pass through link.
static std::optional<std::size_t> pathThrough(App::DocumentObject* obj,
                                              const std::string& sub,
                                              const char* element,
                                              App::DocumentObject* link)
{
    std::string path(sub.c_str(), element - sub.c_str());
    std::vector<int> sizes;
    auto objects = obj->getSubObjectList(path.c_str(), &sizes);
    for (std::size_t k = 0; k < objects.size(); ++k) {
        // A link to a link: the chain of linked objects counts too.
        auto o = objects[k];
        for (int depth = 0; o && depth < 64; ++depth) {
            if (o == link) {
                return k < sizes.size() && sizes[k] >= 0 ? std::size_t(sizes[k])
                                                         : std::string::npos;
            }
            auto next = o->getLinkedObject(false);
            if (next == o) {
                break;
            }
            o = next;
        }
    }
    return std::nullopt;
}

// The fingerprint of the element that rest (the part of a sub after a link) names on oldTarget,
// the link's target before a retarget (ops#106); invalid if it can't be taken.
static Data::ElementFingerprint oldElementFingerprint(App::DocumentObject* oldTarget,
                                                      const std::string& rest)
{
    Data::ElementFingerprint fingerprint;
    if (!oldTarget || !oldTarget->isAttachedToDocument()) {
        return fingerprint;
    }
    PropertyLinkBase::ShadowSub elementName;
    GeoFeature* geo = nullptr;
    const char* element = nullptr;
    if (!GeoFeature::resolveElement(oldTarget,
                                    rest.c_str(),
                                    elementName,
                                    false,
                                    GeoFeature::Normal,
                                    nullptr,
                                    &element,
                                    &geo)
        || !geo || elementName.oldName.empty()
        || GeoFeature::hasMissingElement(elementName.oldName.c_str())) {
        return fingerprint;
    }
    const char* name = Data::findElementName(elementName.oldName.c_str());
    if (!name || !name[0] || !geo->getElementFingerprint(name, fingerprint)) {
        return {};
    }
    return fingerprint;
}

// The shadows of subs (references to objs, or all to obj) after link was pointed at another
// object (ops#42): a reference through it keeps only its index, for the new target's shape to
// resolve. Returns whether any reference passes through link; changed tells whether a shadow
// changed (one already index-only, or missing, stays as it is). checks gets, for each sub made
// index-only, the fingerprint of the element it named on oldTarget, the link's old target, when
// one can be taken (ops#106).
static bool retargetShadows(App::DocumentObject* link,
                            App::DocumentObject* oldTarget,
                            App::DocumentObject* obj,
                            const std::vector<App::DocumentObject*>* objs,
                            const std::vector<std::string>& subs,
                            std::vector<PropertyLinkBase::ShadowSub>& shadows,
                            bool& changed,
                            std::vector<RetargetCheck>& checks)
{
    bool found = false;
    changed = false;
    shadows.resize(subs.size());
    for (std::size_t i = 0; i < subs.size(); ++i) {
        auto target = objs ? (i < objs->size() ? (*objs)[i] : nullptr) : obj;
        const char* element = Data::findElementName(subs[i].c_str());
        if (!target || !target->isAttachedToDocument() || !element || !element[0]) {
            continue;
        }
        auto offset = pathThrough(target, subs[i], element, link);
        if (!offset) {
            continue;
        }
        found = true;
        auto& shadow = shadows[i];
        if (shadow.newName.empty() || Data::hasMissingElement(shadow.oldName.c_str())
            || Data::hasMissingElement(element)) {
            continue;
        }
        if (*offset != std::string::npos && *offset <= subs[i].size()) {
            auto fingerprint = oldElementFingerprint(oldTarget, subs[i].substr(*offset));
            if (fingerprint.isValid()) {
                checks.push_back({target, subs[i], std::move(fingerprint)});
            }
        }
        shadow.newName.clear();
        shadow.oldName = Data::oldElementName(subs[i].c_str());
        changed = true;
    }
    return found;
}

// Holds the checks retargetShadows() took for prop, for the first resolution of its index-only
// subs (ops#106). A sub's earlier check, from a retarget it hasn't resolved since, stays: it
// holds what the reference named before either retarget.
static void holdRetargetChecks(const PropertyLinkBase* prop, std::vector<RetargetCheck>& checks)
{
    if (checks.empty()) {
        return;
    }
    auto& held = _RetargetChecks[prop];
    for (auto& check : checks) {
        bool known = std::any_of(held.begin(), held.end(), [&](const auto& entry) {
            return entry.obj == check.obj && entry.sub == check.sub;
        });
        if (!known) {
            held.push_back(std::move(check));
        }
    }
    checks.clear();
}

#define ATTR_RETARGET "retarget"

// The saved form of a link retarget's held check (ops#106, ops#109): the old element's
// fingerprint, on an index-only sub that hasn't resolved on the link's new target yet. Written in
// every document, solver documents included: their saved fingerprint doesn't stop the index from
// landing on another kind of element.
static void writeRetargetCheck(Base::Writer& writer,
                               const PropertyLinkBase* prop,
                               const App::DocumentObject* obj,
                               const std::string& sub,
                               const PropertyLinkBase::ShadowSub& shadow)
{
    auto checks = _RetargetChecks.find(prop);
    if (!shadow.newName.empty() || checks == _RetargetChecks.end()) {
        return;
    }
    for (const auto& check : checks->second) {
        if (check.obj == obj && check.sub == sub) {
            writer.Stream() << "\" " ATTR_RETARGET "=\""
                            << Base::Persistence::encodeAttribute(check.before.toString());
            return;
        }
    }
}

// Reads the saved check of the sub at index (see writeRetargetCheck()) into restored.
static void readRetargetCheck(Base::XMLReader& reader,
                              std::size_t index,
                              std::vector<std::pair<std::size_t, Data::ElementFingerprint>>& restored)
{
    if (!reader.hasAttribute(ATTR_RETARGET)) {
        return;
    }
    auto fingerprint =
        Data::ElementFingerprint::fromString(reader.getAttribute<const char*>(ATTR_RETARGET));
    if (fingerprint.isValid()) {
        restored.emplace_back(index, std::move(fingerprint));
    }
}

// Keeps a restored property's checks for its onContainerRestored(), in place of any it held.
static void keepRestoredRetargetChecks(
    const PropertyLinkBase* prop,
    std::vector<std::pair<std::size_t, Data::ElementFingerprint>>&& restored)
{
    _RetargetChecks.erase(prop);
    if (restored.empty()) {
        _RestoredRetargetChecks.erase(prop);
    }
    else {
        _RestoredRetargetChecks[prop] = std::move(restored);
    }
}

// Holds a restored property's checks for its subs (references to objs, or all to obj) before
// they are registered, so that their first resolution runs them as in the session that saved
// them. A sub whose object wasn't restored drops its check.
static void holdRestoredRetargetChecks(const PropertyLinkBase* prop,
                                       App::DocumentObject* obj,
                                       const std::vector<App::DocumentObject*>* objs,
                                       const std::vector<std::string>& subs)
{
    auto restored = _RestoredRetargetChecks.find(prop);
    if (restored == _RestoredRetargetChecks.end()) {
        return;
    }
    std::vector<RetargetCheck> checks;
    for (auto& [index, fingerprint] : restored->second) {
        auto target = objs ? (index < objs->size() ? (*objs)[index] : nullptr) : obj;
        if (target && index < subs.size()) {
            checks.push_back({target, subs[index], std::move(fingerprint)});
        }
    }
    _RestoredRetargetChecks.erase(restored);
    holdRetargetChecks(prop, checks);
}

// The reference solver's pass 1 (ops#7) for one property's references: the exact lookup (in a
// solver document, _updateElementReference() does nothing more), then an entry for each
// reference that is missing (just now, or already) or resolved exactly. The references of
// other targets are dropped in pass 2.
static void collectLinkReferences(App::PropertyLinkBase* prop,
                                  App::DocumentObject* feature,
                                  App::SolverBatch& batch,
                                  App::DocumentObject* link,
                                  const std::vector<App::DocumentObject*>* links,
                                  std::vector<std::string>& subs,
                                  std::vector<PropertyLinkBase::ShadowSub>& shadows,
                                  const std::vector<std::string>& fingerprints,
                                  const std::vector<std::string>* froms,
                                  const std::vector<App::GuessRecord>* guesses)
{
    shadows.resize(subs.size());
    auto owner = freecad_cast<DocumentObject*>(prop->getContainer());
    if (!owner || owner->isRestoring()) {
        return;
    }
    bool touched = false;
    for (std::size_t i = 0; i < subs.size(); ++i) {
        auto obj = links ? (i < links->size() ? (*links)[i] : nullptr) : link;
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        auto& shadow = shadows[i];
        // The stored index, before the lookup rewrites the shadow to its hit (ops#103)
        const char* storedElement = Data::findElementName(shadow.oldName.c_str());
        std::string storedIndex = storedElement ? storedElement : "";
        if (prop->_updateElementReference(feature,
                                          obj,
                                          subs[i],
                                          shadow,
                                          batch.reverse,
                                          batch.notify && !touched)) {
            touched = true;
        }
        App::SolverEntry entry;
        // A provisional pick (ops#127) is solved as the element it holds, by that element's
        // name and fingerprint, and keeps its record; when the original's name gives an element
        // again, the entry is exact on that one instead, and the reference snaps back to it
        // unless the solver's checks break it.
        const App::GuessRecord* guess =
            guesses && i < guesses->size() && !(*guesses)[i].empty() ? &(*guesses)[i] : nullptr;
        if (guess) {
            entry.guess = *guess;
        }
        if (guess && snapsBack(*guess)) {
            const std::string& held = !shadow.oldName.empty() ? shadow.oldName : subs[i];
            const char* heldElement = Data::findElementName(held.c_str());
            const std::string prefix =
                heldElement ? held.substr(0, heldElement - held.c_str()) : std::string();
            App::PropertyLinkBase::ShadowSub found;
            App::GeoFeature* geo = nullptr;
            const char* element = nullptr;
            const std::string path = prefix + guess->origText();
            const char* index = nullptr;
            if (heldElement
                && App::GeoFeature::resolveElement(obj,
                                                   path.c_str(),
                                                   found,
                                                   true,
                                                   App::GeoFeature::ElementNameType::Export,
                                                   feature,
                                                   &element,
                                                   &geo)
                && geo && element && element[0]) {
                index = Data::findElementName(found.oldName.c_str());
            }
            if (index && index[0] && !Data::hasMissingElement(index)) {
                entry.kind = App::SolverEntry::Kind::Exact;
                entry.guessed = true;
                if (!Data::hasMissingElement(heldElement)) {
                    entry.guessedIndex = heldElement;
                }
                entry.prefix = prefix;
                entry.exactName = guess->origName;
                entry.oldIndex = index;
                entry.prop = prop;
                entry.index = static_cast<int>(i);
                entry.obj = obj;
                entry.owner = owner;
                entry.sub = subs[i];
                // no fingerprint: the one saved is the picked element's, not the original's
                entry.policy = prop->getElementPolicy();
                if (froms && i < froms->size()) {
                    entry.from = (*froms)[i];
                }
                batch.entries.push_back(std::move(entry));
                continue;
            }
        }
        if (Data::hasMissingElement(shadow.oldName.c_str())) {
            if (!Data::hasMappedElementName(shadow.newName.c_str())) {
                continue;  // an index-only missing reference: no name to solve from (ops#123)
            }
            entry.kind = App::SolverEntry::Kind::Missing;
        }
        else if (!shadow.newName.empty()) {
            entry.kind = App::SolverEntry::Kind::Exact;
        }
        else {
            continue;  // an index-only reference: nothing to solve
        }
        const char* element = Data::findElementName(shadow.newName.c_str());
        if (!element) {
            continue;
        }
        entry.prefix = shadow.newName.substr(0, element - shadow.newName.c_str());
        if (entry.kind == App::SolverEntry::Kind::Missing) {
            entry.oldName = App::bareMappedName(shadow.newName);
        }
        else {
            entry.exactName = App::bareMappedName(shadow.newName);
        }
        const char* oldElement = Data::findElementName(shadow.oldName.c_str());
        entry.oldIndex = oldElement ? oldElement : "";
        if (entry.kind == App::SolverEntry::Kind::Missing) {
            entry.oldIndex.erase(0, std::strlen(Data::MISSING_PREFIX));
        }
        if (entry.oldIndex.empty()) {
            continue;
        }
        entry.prop = prop;
        entry.index = static_cast<int>(i);
        entry.obj = obj;
        entry.owner = owner;
        entry.sub = subs[i];
        entry.oldFingerprint = i < fingerprints.size() ? fingerprints[i] : std::string();
        if (entry.kind == App::SolverEntry::Kind::Exact
            && !Data::hasMissingElement(storedIndex.c_str())) {
            entry.storedIndex = std::move(storedIndex);
        }
        entry.policy = prop->getElementPolicy();
        if (froms && i < froms->size()) {
            entry.from = (*froms)[i];
        }
        batch.entries.push_back(std::move(entry));
    }
    batch.properties.emplace_back(prop, touched);
}

// Writes the solver's resolutions into subs and shadows, calling aboutToSet() first if pass 1
// didn't change the property already. Returns true if the property changed in either pass.
// Resolved, Broken and Guessed (one element) only: the types that call it keep one sub per
// reference. Guessed and Broken set the reference's record (Broken's may be empty), Resolved
// clears it; a Broken one with clearFingerprint clears the fingerprint too (ops#127).
static bool writeLinkResolutions(const std::vector<App::SolverResolution>& resolutions,
                                 std::vector<std::string>& subs,
                                 std::vector<PropertyLinkBase::ShadowSub>& shadows,
                                 std::vector<std::string>& fingerprints,
                                 std::vector<App::GuessRecord>& guesses,
                                 const std::function<void()>& aboutToSet)
{
    using Status = App::SolverResolution::Status;
    const auto& context = resolutions.front();
    bool changed = context.touched;
    shadows.resize(subs.size());
    guesses.resize(subs.size());
    if (fingerprints.size() != subs.size()) {
        fingerprints.resize(subs.size());
    }
    for (const auto& resolution : resolutions) {
        if ((resolution.status != Status::Resolved && resolution.status != Status::Broken
             && (resolution.status != Status::Guessed || !resolution.pieces.empty()))
            || resolution.index < 0
            || resolution.index >= static_cast<int>(subs.size())) {
            continue;
        }
        if (!changed && context.notify) {
            aboutToSet();
        }
        changed = true;
        subs[resolution.index] = resolution.sub;
        shadows[resolution.index] = resolution.shadow;
        guesses[resolution.index] =
            resolution.status == Status::Resolved ? App::GuessRecord() : resolution.guess;
        if (resolution.status == Status::Broken && resolution.clearFingerprint) {
            fingerprints[resolution.index].clear();
        }
    }
    return changed;
}

void PropertyLinkSub::afterRestore()
{
    _ShadowSubList.resize(_cSubList.size());
    if (!testFlag(LinkRestoreLabel) || !_pcLinkSub || !_pcLinkSub->isAttachedToDocument()) {
        return;
    }
    setFlag(LinkRestoreLabel, false);
    for (std::size_t i = 0; i < _cSubList.size(); ++i) {
        restoreLabelReference(_pcLinkSub, _cSubList[i], &_ShadowSubList[i]);
    }
}

void PropertyLinkSub::onContainerRestored()
{
    unregisterElementReference();
    holdRestoredRetargetChecks(this, _pcLinkSub, nullptr, _cSubList);
    if (!_pcLinkSub || !_pcLinkSub->isAttachedToDocument()) {
        return;
    }
    for (std::size_t i = 0; i < _cSubList.size(); ++i) {
        _registerElementReference(_pcLinkSub, _cSubList[i], _ShadowSubList[i]);
    }
    _updateElementFingerprints(nullptr, _pcLinkSub, nullptr, _cSubList, _ShadowSubList, _Fingerprints);
}

void PropertyLinkSub::updateElementReference(DocumentObject* feature, bool reverse, bool notify)
{
    if (!feature) {
        _Guesses.clear();  // the shadows go too: a sub set anew (ops#127)
    }
    bool changed = updateLinkReference(this,
                                       feature,
                                       reverse,
                                       notify,
                                       _pcLinkSub,
                                       _cSubList,
                                       _mapped,
                                       _ShadowSubList);
    _updateElementFingerprints(feature, _pcLinkSub, nullptr, _cSubList, _ShadowSubList, _Fingerprints);
    if (!changed) {
        return;
    }
    if (notify) {
        hasSetValue();
    }
}

bool PropertyLinkSub::updateElementFingerprints()
{
    return _updateElementFingerprints(nullptr,
                                      _pcLinkSub,
                                      nullptr,
                                      _cSubList,
                                      _ShadowSubList,
                                      _Fingerprints);
}

// The reference solver's passes (ops#7).
void PropertyLinkSub::collectElementReferences(App::DocumentObject* feature, SolverBatch& batch)
{
    collectLinkReferences(this,
                          feature,
                          batch,
                          _pcLinkSub,
                          nullptr,
                          _cSubList,
                          _ShadowSubList,
                          _Fingerprints,
                          &_ExpandedFrom,
                          &_Guesses);
}

void PropertyLinkSub::applyResolutions(const std::vector<SolverResolution>& resolutions)
{
    if (resolutions.empty()) {
        return;
    }
    const auto& context = resolutions.front();
    // The parallel lists are rebuilt: an expansion adds subs, a collapse removes them (Task 2
    // PR 7). Their sizes always match, so the fingerprint refresh keeps every one.
    auto subs = _cSubList;
    auto shadows = _ShadowSubList;
    auto fingerprints = _Fingerprints;
    auto froms = _ExpandedFrom;
    auto guesses = _Guesses;
    auto retargets = _Retargets;
    std::vector<int> firstNew;
    std::vector<int> countNew;
    bool written = rebuildSubList(resolutions,
                                  subs,
                                  shadows,
                                  fingerprints,
                                  froms,
                                  firstNew,
                                  countNew,
                                  &guesses,
                                  &retargets);
    bool changed = context.touched;
    if (written) {
        if (!changed && context.notify) {
            aboutToSetValue();
        }
        changed = true;
        bool moved = subs.size() != _cSubList.size()
            || std::any_of(countNew.begin(), countNew.end(), [](int n) { return n != 1; });
        _cSubList.swap(subs);
        _ShadowSubList.swap(shadows);
        _Fingerprints.swap(fingerprints);
        _ExpandedFrom.swap(froms);
        _Guesses.swap(guesses);
        _Retargets.swap(retargets);
        if (moved) {
            _mapped = remapSubIndices(_mapped, firstNew, countNew);
            ReferenceReport::remap(this, firstNew, countNew);
            context.firstNew = std::move(firstNew);
            context.countNew = std::move(countNew);
        }
    }
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (changed) {
        // As updateLinkReference() does.
        for (int idx : _mapped) {
            if (idx < (int)_cSubList.size() && !_ShadowSubList[idx].newName.empty()) {
                _cSubList[idx] = _ShadowSubList[idx].newName;
            }
        }
        _mapped.clear();
        if (owner && context.feature) {
            owner->onUpdateElementReference(this);
        }
    }
    _updateElementFingerprints(context.feature,
                               _pcLinkSub,
                               nullptr,
                               _cSubList,
                               _ShadowSubList,
                               _Fingerprints);
    if (changed && context.notify) {
        hasSetValue();
    }
}

std::vector<std::string> PropertyLinkSub::getElementFingerprints() const
{
    auto fingerprints = _Fingerprints;
    fingerprints.resize(_cSubList.size());
    return fingerprints;
}

std::vector<GuessRecord> PropertyLinkSub::getElementGuesses() const
{
    auto guesses = _Guesses;
    guesses.resize(_cSubList.size());
    return guesses;
}

bool PropertyLinkSub::referenceChanged() const
{
    return !_mapped.empty();
}

namespace
{
/// importSubName() for a reader that maps object names (an import)
std::string importMappedSubName(Base::XMLReader& reader, const char* sub, bool& restoreLabel)
{
    std::ostringstream str;
    for (const char* dot = strchr(sub, '.'); dot; sub = dot + 1, dot = strchr(sub, '.')) {
        size_t count = dot - sub;
        const char* tail = ".";
        if (count && dot[-1] == '@') {
            // tail=='@' means we are exporting a label reference. So retain
            // this marker so that the label can be restored in afterRestore().
            tail = "@.";
            --count;
            restoreLabel = true;
        }
        str << reader.getName(std::string(sub, count).c_str()) << tail;
    }
    str << sub;
    return str.str();
}
}  // namespace

std::string
PropertyLinkBase::importSubName(Base::XMLReader& reader, const char* sub, bool& restoreLabel)
{
    std::string result = sub;
    if (reader.doNameMapping()) {
        result = importMappedSubName(reader, sub, restoreLabel);
    }
    // The references to interned names in a subname or shadow mean what the file's name table
    // says: a reference the table lacks is made unresolvable (ops#6, Data::NameRemap)
    if (auto* remap = Data::NameRemap::active()) {
        remap->remapSubName(result);
    }
    return result;
}

const char* PropertyLinkBase::exportSubName(std::string& output,
                                            const App::DocumentObject* obj,
                                            const char* sub,
                                            bool first_obj)
{
    std::ostringstream str;
    const char* res = sub;

    if (!sub || !sub[0]) {
        return res;
    }

    bool touched = false;
    if (first_obj) {
        auto dot = strchr(sub, '.');
        if (!dot) {
            return res;
        }
        const char* hash;
        for (hash = sub; hash < dot && *hash != '#'; ++hash) {}
        App::Document* doc = nullptr;
        if (*hash == '#') {
            doc = GetApplication().getDocument(std::string(sub, hash - sub).c_str());
        }
        else {
            hash = nullptr;
            if (obj && obj->isAttachedToDocument()) {
                doc = obj->getDocument();
            }
        }
        if (!doc) {
            FC_ERR("Failed to get document for the first object in " << sub);
            return res;
        }
        obj = doc->getObject(std::string(sub, dot - sub).c_str());
        if (!obj || !obj->isAttachedToDocument()) {
            return res;
        }
        if (hash) {
            if (!obj->isExporting()) {
                str << doc->getName() << '#';
            }
            sub = hash + 1;
        }
    }
    else if (!obj || !obj->isAttachedToDocument()) {
        return res;
    }

    for (const char* dot = strchr(sub, '.'); dot; sub = dot + 1, dot = strchr(sub, '.')) {
        // name with trailing '.'
        auto name = std::string(sub, dot - sub + 1);
        if (first_obj) {
            first_obj = false;
        }
        else {
            obj = obj->getSubObject(name.c_str());
        }
        if (!obj || !obj->isAttachedToDocument()) {
            FC_WARN("missing sub object '" << name << "' in '" << sub << "'");
            break;
        }
        if (obj->isExporting()) {
            if (name[0] == '$') {
                if (name.compare(1, name.size() - 2, obj->Label.getValue()) != 0) {
                    str << obj->getExportName(true) << "@.";
                    touched = true;
                    continue;
                }
            }
            else if (name.compare(0, name.size() - 1, obj->getNameInDocument()) == 0) {
                str << obj->getExportName(true) << '.';
                touched = true;
                continue;
            }
        }
        str << name;
    }
    if (!touched) {
        return res;
    }
    str << sub;
    output = str.str();
    return output.c_str();
}

App::DocumentObject* PropertyLinkBase::tryImport(const App::Document* doc,
                                                 const App::DocumentObject* obj,
                                                 const std::map<std::string, std::string>& nameMap)
{
    if (doc && obj && obj->isAttachedToDocument()) {
        auto it = nameMap.find(obj->getExportName(true));
        if (it != nameMap.end()) {
            obj = doc->getObject(it->second.c_str());
            if (!obj) {
                FC_THROWM(Base::RuntimeError, "Cannot find import object " << it->second);
            }
        }
    }
    return const_cast<DocumentObject*>(obj);
}

std::string PropertyLinkBase::tryImportSubName(const App::DocumentObject* obj,
                                               const char* _subname,
                                               const App::Document* doc,
                                               const std::map<std::string, std::string>& nameMap)
{
    if (!doc || !obj || !obj->isAttachedToDocument()) {
        return {};
    }

    std::ostringstream ss;
    std::string subname(_subname);
    char* sub = &subname[0];
    char* next = sub;
    for (char* dot = strchr(next, '.'); dot; next = dot + 1, dot = strchr(next, '.')) {
        StringGuard guard(dot);
        auto sobj = obj->getSubObject(subname.c_str());
        if (!sobj) {
            FC_ERR("Failed to restore label reference " << obj->getFullName() << '.' << subname);
            return {};
        }
        dot[0] = 0;
        if (next[0] == '$') {
            if (strcmp(next + 1, sobj->Label.getValue()) != 0) {
                continue;
            }
        }
        else if (strcmp(next, sobj->getNameInDocument()) != 0) {
            continue;
        }
        auto it = nameMap.find(sobj->getExportName(true));
        if (it == nameMap.end()) {
            continue;
        }
        auto imported = doc->getObject(it->second.c_str());
        if (!imported) {
            FC_THROWM(RuntimeError, "Failed to find imported object " << it->second);
        }
        ss.write(sub, next - sub);
        if (next[0] == '$') {
            ss << '$' << imported->Label.getStrValue() << '.';
        }
        else {
            ss << it->second << '.';
        }
        sub = dot + 1;
    }
    if (sub != subname.c_str()) {
        return ss.str();
    }
    return {};
}

void PropertyLinkBase::_getLinksTo(std::vector<App::ObjectIdentifier>& identifiers,
                                   App::DocumentObject* obj,
                                   const char* subname,
                                   const std::vector<std::string>& subs,
                                   const std::vector<PropertyLinkBase::ShadowSub>& shadows) const
{
    if (!subname) {
        identifiers.emplace_back(*this);
        return;
    }
    App::SubObjectT objT(obj, subname);
    auto subObject = objT.getSubObject();
    auto subElement = objT.getOldElementName();

    int i = -1;
    for (const auto& sub : subs) {
        ++i;
        if (sub == subname) {
            identifiers.emplace_back(*this);
            return;
        }
        if (!subObject) {
            continue;
        }
        // After above, there is a subobject and the subname doesn't match our current entry
        App::SubObjectT sobjT(obj, sub.c_str());
        if (sobjT.getSubObject() == subObject && sobjT.getOldElementName() == subElement) {
            identifiers.emplace_back(*this);
            return;
        }
        // And the oldElementName ( short, I.E. "Edge5" ) doesn't match.
        if (i < (int)shadows.size()) {
            const auto& [shadowNewName, shadowOldName] = shadows[i];
            if (shadowNewName == subname || shadowOldName == subname) {
                identifiers.emplace_back(*this);
                return;
            }
            if (!subObject) {
                continue;
            }
            App::SubObjectT shadowobjT(obj,
                                       shadowNewName.empty() ? shadowOldName.c_str()
                                                             : shadowNewName.c_str());
            if (shadowobjT.getSubObject() == subObject
                && shadowobjT.getOldElementName() == subElement) {
                identifiers.emplace_back(*this);
                return;
            }
        }
    }
}

#define ATTR_SHADOWED "shadowed"
#define ATTR_FINGERPRINT "fp"
#define ATTR_FROM "from"
#define ATTR_RETARGET_TARGET "rt"
#define ATTR_RETARGET_ORIGINAL "rto"
#define ATTR_RETARGET_FINGERPRINT "rtfp"

// The reorder's re-target record of reference i (ops#127, notes/reorder-rollback-design.md 3.4),
// written in every document: where the reference was and what it named there.
static void writeRetargetRecord(Base::Writer& writer,
                                const std::vector<RetargetRecord>& records,
                                std::size_t i)
{
    if (i >= records.size() || records[i].empty()) {
        return;
    }
    const auto& record = records[i];
    writer.Stream() << "\" " ATTR_RETARGET_TARGET "=\""
                    << Base::Persistence::encodeAttribute(record.target)
                    << "\" " ATTR_RETARGET_ORIGINAL "=\""
                    << Base::Persistence::encodeAttribute(record.origText());
    if (!record.origFp.empty()) {
        writer.Stream() << "\" " ATTR_RETARGET_FINGERPRINT "=\""
                        << Base::Persistence::encodeAttribute(record.origFp);
    }
}

// The record saved on the current element (see writeRetargetRecord()), empty if none. An
// imported object's name is mapped as the reader maps it.
static RetargetRecord readRetargetRecord(Base::XMLReader& reader)
{
    if (!reader.hasAttribute(ATTR_RETARGET_TARGET)) {
        return {};
    }
    auto attribute = [&](const char* name) {
        return std::string(reader.hasAttribute(name) ? reader.getAttribute<const char*>(name) : "");
    };
    std::string target = reader.getName(reader.getAttribute<const char*>(ATTR_RETARGET_TARGET));
    return RetargetRecord::fromAttributes(target,
                                          attribute(ATTR_RETARGET_ORIGINAL),
                                          attribute(ATTR_RETARGET_FINGERPRINT));
}

// A setter's rule for the re-target records (ops#127), as for `from`: a reference passed on with
// its shadow (a restore, a paste, the re-target itself) keeps its record; a sub chosen anew (no
// shadow, or no shadows at all: a re-pick) ends it.
static void keepRetargetRecords(std::vector<RetargetRecord>& records,
                                std::size_t count,
                                const std::vector<PropertyLinkBase::ShadowSub>& shadows)
{
    if (shadows.size() != count || records.size() != count) {
        records.assign(count, RetargetRecord());
        return;
    }
    for (std::size_t i = 0; i < count; ++i) {
        if (shadows[i].oldName.empty() && shadows[i].newName.empty()) {
            records[i] = RetargetRecord();
        }
    }
}
#define ATTR_SHADOW "shadow"
#define ATTR_MAPPED "mapped"

#define IGNORE_SHADOW false

// A reference's guess record (ops#127): its kind, the original and the alternatives.
#define ATTR_GUESS "guess"
#define ATTR_ORIG "orig"
#define ATTR_ALT "alt"

static void writeGuessRecord(Base::Writer& writer,
                             const std::vector<GuessRecord>& guesses,
                             std::size_t i)
{
    if (i >= guesses.size() || guesses[i].empty()) {
        return;
    }
    const auto& guess = guesses[i];
    writer.Stream() << "\" " ATTR_GUESS "=\"" << Base::Persistence::encodeAttribute(guess.kind)
                    << "\" " ATTR_ORIG "=\""
                    << Base::Persistence::encodeAttribute(guess.origText());
    const std::string alternatives = guess.altText();
    if (!alternatives.empty()) {
        writer.Stream() << "\" " ATTR_ALT "=\"" << Base::Persistence::encodeAttribute(alternatives);
    }
}

static GuessRecord readGuessRecord(Base::XMLReader& reader)
{
    if (!reader.hasAttribute(ATTR_GUESS)) {
        return {};
    }
    std::string orig =
        reader.hasAttribute(ATTR_ORIG) ? reader.getAttribute<const char*>(ATTR_ORIG) : "";
    if (auto* remap = Data::NameRemap::active()) {
        remap->remapSubName(orig);  // as importSubName() does (ops#6)
    }
    return GuessRecord::fromAttributes(reader.getAttribute<const char*>(ATTR_GUESS),
                                       orig,
                                       reader.hasAttribute(ATTR_ALT)
                                           ? reader.getAttribute<const char*>(ATTR_ALT)
                                           : "");
}

void PropertyLinkSub::Save(Base::Writer& writer) const
{
    assert(_cSubList.size() == _ShadowSubList.size());

    std::string internal_name;
    // it can happen that the object is still alive but is not part of the document anymore and thus
    // returns 0
    if (_pcLinkSub && _pcLinkSub->isAttachedToDocument()) {
        internal_name = _pcLinkSub->getExportName();
    }
    writer.Stream() << writer.ind() << "<LinkSub value=\"" << internal_name << "\" count=\""
                    << _cSubList.size();
    writer.Stream() << "\">" << std::endl;
    writer.incInd();
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    bool exporting = owner && owner->isExporting();
    const bool saveFingerprints = inSolverDocument();
    for (unsigned int i = 0; i < _cSubList.size(); i++) {
        const auto& shadow = _ShadowSubList[i];
        // shadow.oldName stores the old style element name. For backward
        // compatibility reason, we shall store the old name into attribute
        // 'value' whenever possible.
        const auto& sub = shadow.oldName.empty() ? _cSubList[i] : shadow.oldName;
        writer.Stream() << writer.ind() << "<Sub value=\"";
        if (exporting) {
            std::string exportName;
            writer.Stream() << encodeAttribute(exportSubName(exportName, _pcLinkSub, sub.c_str()));
            if (!shadow.oldName.empty() && shadow.newName == _cSubList[i]) {
                writer.Stream() << "\" " ATTR_MAPPED "=\"1";
            }
        }
        else {
            writer.Stream() << encodeAttribute(sub);
            if (!_cSubList[i].empty()) {
                if (sub != _cSubList[i]) {
                    // Stores the actual value that is shadowed. For new version FC,
                    // we will restore this shadowed value instead.
                    writer.Stream() << "\" " ATTR_SHADOWED "=\"" << encodeAttribute(_cSubList[i]);
                }
                else if (!shadow.newName.empty()) {
                    // Here means the user set value is old style element name.
                    // We shall then store the shadow somewhere else.
                    writer.Stream() << "\" " ATTR_SHADOW "=\"" << encodeAttribute(shadow.newName);
                }
            }
        }
        if (saveFingerprints && i < _Fingerprints.size() && !_Fingerprints[i].empty()) {
            writer.Stream() << "\" " ATTR_FINGERPRINT "=\"" << encodeAttribute(_Fingerprints[i]);
        }
        if (saveFingerprints && i < _ExpandedFrom.size() && !_ExpandedFrom[i].empty()) {
            writer.Stream() << "\" " ATTR_FROM "=\"" << encodeAttribute(_ExpandedFrom[i]);
        }
        if (saveFingerprints) {
            writeGuessRecord(writer, _Guesses, i);
        }
        writeRetargetRecord(writer, _Retargets, i);
        writeRetargetCheck(writer, this, _pcLinkSub, _cSubList[i], shadow);
        writer.Stream() << "\"/>" << endl;
    }
    writer.decInd();
    writer.Stream() << writer.ind() << "</LinkSub>" << endl;
}

void PropertyLinkSub::Restore(Base::XMLReader& reader)
{
    // read my element
    reader.readElement("LinkSub");
    // get the values of my attributes
    std::string name = reader.getName(reader.getAttribute<const char*>("value"));
    int count = reader.getAttribute<long>("count");

    // Property not in a DocumentObject!
    assert(getContainer()->isDerivedFrom<App::DocumentObject>());
    App::Document* document = static_cast<DocumentObject*>(getContainer())->getDocument();

    DocumentObject* pcObject = nullptr;
    if (!name.empty()) {
        pcObject = document ? document->getObject(name.c_str()) : nullptr;
        if (!pcObject) {
            if (reader.isVerbose()) {
                FC_WARN("Lost link to "
                        << name << " while loading, maybe an object was not loaded correctly");
            }
        }
    }

    std::vector<int> mapped;
    std::vector<std::string> values(count);
    std::vector<ShadowSub> shadows(count);
    std::vector<std::string> fingerprints(count);
    std::vector<std::string> froms(count);
    std::vector<GuessRecord> guesses(count);
    std::vector<RetargetRecord> retargets(count);
    std::vector<std::pair<std::size_t, Data::ElementFingerprint>> checks;
    bool restoreLabel = false;
    // Sub may store '.' separated object names, so be aware of the possible mapping when import
    for (int i = 0; i < count; i++) {
        reader.readElement("Sub");
        if (reader.hasAttribute(ATTR_FINGERPRINT)) {
            fingerprints[i] = reader.getAttribute<const char*>(ATTR_FINGERPRINT);
        }
        retargets[i] = readRetargetRecord(reader);
        readRetargetCheck(reader, i, checks);
        if (reader.hasAttribute(ATTR_FROM)) {
            froms[i] = reader.getAttribute<const char*>(ATTR_FROM);
            if (auto* remap = Data::NameRemap::active()) {
                remap->remapSubName(froms[i]);  // as importSubName() does (ops#6)
            }
        }
        guesses[i] = readGuessRecord(reader);
        shadows[i].oldName = importSubName(reader, reader.getAttribute<const char*>("value"), restoreLabel);
        if (reader.hasAttribute(ATTR_SHADOWED) && !IGNORE_SHADOW) {
            values[i] = shadows[i].newName =
                importSubName(reader, reader.getAttribute<const char*>(ATTR_SHADOWED), restoreLabel);
        }
        else {
            values[i] = shadows[i].oldName;
            if (reader.hasAttribute(ATTR_SHADOW) && !IGNORE_SHADOW) {
                shadows[i].newName =
                    importSubName(reader, reader.getAttribute<const char*>(ATTR_SHADOW), restoreLabel);
            }
        }
        if (reader.hasAttribute(ATTR_MAPPED)) {
            mapped.push_back(i);
        }
    }
    setFlag(LinkRestoreLabel, restoreLabel);

    reader.readEndElement("LinkSub");
    keepRestoredRetargetChecks(this, std::move(checks));

    if (pcObject) {
        setValue(pcObject, std::move(values), std::move(shadows));
        _mapped = std::move(mapped);
        _Fingerprints = std::move(fingerprints);
        _ExpandedFrom = std::move(froms);
        _Guesses = std::move(guesses);
        _Retargets = std::move(retargets);
    }
    else {
        setValue(nullptr);
    }
}

template<class Func, class... Args>
std::vector<std::string> updateLinkSubs(const App::DocumentObject* obj,
                                        const std::vector<std::string>& subs,
                                        Func* f,
                                        Args&&... args)
{
    if (!obj || !obj->isAttachedToDocument()) {
        return {};
    }

    std::vector<std::string> res;
    for (auto it = subs.begin(); it != subs.end(); ++it) {
        const auto& sub = *it;
        auto new_sub = (*f)(obj, sub.c_str(), args...);
        if (new_sub.size()) {
            if (res.empty()) {
                res.reserve(subs.size());
                res.insert(res.end(), subs.begin(), it);
            }
            res.push_back(std::move(new_sub));
        }
        else if (!res.empty()) {
            res.push_back(sub);
        }
    }
    return res;
}

Property*
PropertyLinkSub::CopyOnImportExternal(const std::map<std::string, std::string>& nameMap) const
{
    auto owner = dynamic_cast<const DocumentObject*>(getContainer());
    if (!owner || !owner->getDocument()) {
        return nullptr;
    }
    if (!_pcLinkSub || !_pcLinkSub->isAttachedToDocument()) {
        return nullptr;
    }

    auto subs =
        updateLinkSubs(_pcLinkSub, _cSubList, &tryImportSubName, owner->getDocument(), nameMap);
    auto linked = tryImport(owner->getDocument(), _pcLinkSub, nameMap);
    if (subs.empty() && linked == _pcLinkSub) {
        return nullptr;
    }

    PropertyLinkSub* p = new PropertyLinkSub();
    p->_pcLinkSub = linked;
    if (subs.empty()) {
        p->_cSubList = _cSubList;
    }
    else {
        p->_cSubList = std::move(subs);
    }
    return p;
}

Property* PropertyLinkSub::CopyOnLabelChange(App::DocumentObject* obj,
                                             const std::string& ref,
                                             const char* newLabel) const
{
    auto owner = dynamic_cast<const DocumentObject*>(getContainer());
    if (!owner || !owner->getDocument()) {
        return nullptr;
    }
    if (!_pcLinkSub || !_pcLinkSub->isAttachedToDocument()) {
        return nullptr;
    }

    auto subs = updateLinkSubs(_pcLinkSub, _cSubList, &updateLabelReference, obj, ref, newLabel);
    if (subs.empty()) {
        return nullptr;
    }

    PropertyLinkSub* p = new PropertyLinkSub();
    p->_pcLinkSub = _pcLinkSub;
    p->_cSubList = std::move(subs);
    return p;
}

Property* PropertyLinkSub::CopyOnLinkReplace(const App::DocumentObject* parent,
                                             App::DocumentObject* oldObj,
                                             App::DocumentObject* newObj) const
{
    auto res = tryReplaceLinkSubs(getContainer(), _pcLinkSub, parent, oldObj, newObj, _cSubList);
    if (res.first) {
        PropertyLinkSub* p = new PropertyLinkSub();
        p->_pcLinkSub = res.first;
        p->_cSubList = std::move(res.second);
        return p;
    }
    return nullptr;
}

Property* PropertyLinkSub::Copy() const
{
    PropertyLinkSub* p = new PropertyLinkSub();
    p->_pcLinkSub = _pcLinkSub;
    p->_cSubList = _cSubList;
    p->_ShadowSubList = _ShadowSubList;
    p->_Fingerprints = _Fingerprints;
    p->_ExpandedFrom = _ExpandedFrom;
    p->_Guesses = _Guesses;
    p->_Retargets = _Retargets;
    return p;
}

void PropertyLinkSub::Paste(const Property& from)
{
    if (!from.isDerivedFrom<PropertyLinkSub>()) {
        throw Base::TypeError("Incompatible property to paste to");
    }
    auto& link = static_cast<const PropertyLinkSub&>(from);
    setValue(link._pcLinkSub, link._cSubList, std::vector<ShadowSub>(link._ShadowSubList));
    if (link._Fingerprints.size() == _cSubList.size()) {
        _Fingerprints = link._Fingerprints;
    }
    // Undo and redo restore a property through Paste: an expansion comes back with its `from`,
    // a guess with its record (ops#127).
    _ExpandedFrom = link._ExpandedFrom;
    _ExpandedFrom.resize(_cSubList.size());
    _Guesses = link._Guesses;
    _Guesses.resize(_cSubList.size());
    // So does the reorder's re-target record (ops#127)
    _Retargets = link._Retargets;
    _Retargets.resize(_cSubList.size());
}

void PropertyLinkSub::setRetargets(std::vector<RetargetRecord>&& records)
{
    aboutToSetValue();
    _Retargets = std::move(records);
    _Retargets.resize(_cSubList.size());
    hasSetValue();
}

void PropertyLinkSub::setElementFingerprint(std::size_t index, const std::string& fingerprint)
{
    if (index >= _cSubList.size()) {
        return;
    }
    aboutToSetValue();
    _Fingerprints.resize(_cSubList.size());
    _Fingerprints[index] = fingerprint;
    hasSetValue();
}

void PropertyLinkSub::getLinks(std::vector<App::DocumentObject*>& objs,
                               bool all,
                               std::vector<std::string>* subs,
                               bool newStyle) const
{
    if (all || _pcScope != LinkScope::Hidden) {
        if (_pcLinkSub && _pcLinkSub->isAttachedToDocument()) {
            // we use to run this method everytime the program needed to access the sub-elements in
            // a property link, but it caused multiple issues (#23441 and #23402) so it has been
            // commented out.
            // updateElementReferences(_pcLinkSub);
            objs.push_back(_pcLinkSub);
            if (subs) {
                *subs = getSubValues(newStyle);
            }
        }
    }
}

void PropertyLinkSub::getLinksTo(std::vector<App::ObjectIdentifier>& identifiers,
                                 App::DocumentObject* obj,
                                 const char* subname,
                                 bool all) const
{
    if (all || _pcScope != LinkScope::Hidden) {
        if (obj && obj == _pcLinkSub) {
            _getLinksTo(identifiers, obj, subname, _cSubList, _ShadowSubList);
        }
    }
}

void PropertyLinkSub::breakLink(App::DocumentObject* obj, bool clear)
{
    if (obj == _pcLinkSub || (clear && getContainer() == obj)) {
        setValue(nullptr);
    }
}

static App::DocumentObject*
adjustLinkSubs(App::PropertyLinkBase* prop,
               const std::set<App::DocumentObject*>& inList,
               App::DocumentObject* link,
               std::vector<std::string>& subs,
               std::map<App::DocumentObject*, std::vector<std::string>>* links = nullptr)
{
    App::DocumentObject* newLink = nullptr;
    for (auto& sub : subs) {
        size_t pos = sub.find('.');
        for (; pos != std::string::npos; pos = sub.find('.', pos + 1)) {
            auto sobj = link->getSubObject(sub.substr(0, pos + 1).c_str());
            if (!sobj
                || (!prop->testFlag(PropertyLinkBase::LinkAllowExternal)
                    && sobj->getDocument() != link->getDocument())) {
                pos = std::string::npos;
                break;
            }
            if (!newLink) {
                if (inList.contains(sobj)) {
                    continue;
                }
                newLink = sobj;
                if (links) {
                    (*links)[sobj].push_back(sub.substr(pos + 1));
                }
                else {
                    sub = sub.substr(pos + 1);
                }
            }
            else if (links) {
                (*links)[sobj].push_back(sub.substr(pos + 1));
            }
            else if (sobj == newLink) {
                sub = sub.substr(pos + 1);
            }
            break;
        }
        if (pos == std::string::npos) {
            return nullptr;
        }
    }
    return newLink;
}

bool PropertyLinkSub::adjustLink(const std::set<App::DocumentObject*>& inList)
{
    if (_pcScope == LinkScope::Hidden) {
        return false;
    }
    if (!_pcLinkSub || !_pcLinkSub->isAttachedToDocument() || !inList.contains(_pcLinkSub)) {
        return false;
    }
    auto subs = _cSubList;
    auto link = adjustLinkSubs(this, inList, _pcLinkSub, subs);
    if (link) {
        setValue(link, std::move(subs));
        return true;
    }
    return false;
}

//**************************************************************************
// PropertyLinkSubList
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyLinkSubList, App::PropertyLinkBase)
TYPESYSTEM_SOURCE(App::PropertyLinkSubListChild, App::PropertyLinkSubList)
TYPESYSTEM_SOURCE(App::PropertyLinkSubListGlobal, App::PropertyLinkSubList)
TYPESYSTEM_SOURCE(App::PropertyLinkSubListHidden, App::PropertyLinkSubList)

//**************************************************************************
// Construction/Destruction


PropertyLinkSubList::PropertyLinkSubList() = default;

PropertyLinkSubList::~PropertyLinkSubList()
{
    // in case this property is dynamically removed

    // maintain backlinks
    if (!_lValueList.empty() && getContainer()
        && getContainer()->isDerivedFrom<App::DocumentObject>()) {
        App::DocumentObject* parent = static_cast<DocumentObject*>(getContainer());
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            for (auto* obj : _lValueList) {
                if (obj) {
                    obj->_removeBackLink(parent);
                    obj->_removeBackLinkProp(getName(), parent);
                }
            }
        }
    }
}

void PropertyLinkSubList::setSyncSubObject(bool enable)
{
    _Flags.set((std::size_t)LinkSyncSubObject, enable);
}

void PropertyLinkSubList::verifyObject(App::DocumentObject* obj, App::DocumentObject* parent)
{
    if (obj) {
        if (!obj->isAttachedToDocument()) {
            throw Base::ValueError("PropertyLinkSubList: invalid document object");
        }
        if (!testFlag(LinkAllowExternal) && parent && parent->getDocument() != obj->getDocument()) {
            throw Base::ValueError("PropertyLinkSubList does not support external object");
        }
    }
}

void PropertyLinkSubList::setSize(int newSize)
{
    _lValueList.resize(newSize);
    _lSubList.resize(newSize);
    _ShadowSubList.resize(newSize);
    _Retargets.clear();
}

int PropertyLinkSubList::getSize() const
{
    return static_cast<int>(_lValueList.size());
}

void PropertyLinkSubList::setValue(DocumentObject* lValue, const char* SubName)
{
    auto parent = freecad_cast<App::DocumentObject*>(getContainer());
    verifyObject(lValue, parent);

    // maintain backlinks
    if (parent) {
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            for (auto* obj : _lValueList) {
                if (obj) {
                    obj->_removeBackLink(parent);
                    obj->_removeBackLinkProp(getName(), parent);
                }
            }
            if (lValue) {
                lValue->_addBackLink(parent);
                lValue->_addBackLinkProp(getName(), parent);
            }
        }
    }

    if (lValue) {
        aboutToSetValue();
        _lValueList.resize(1);
        _lValueList[0] = lValue;
        _lSubList.resize(1);
        _lSubList[0] = SubName;
    }
    else {
        aboutToSetValue();
        _lValueList.clear();
        _lSubList.clear();
    }
    updateElementReference(nullptr);
    checkLabelReferences(_lSubList);
    hasSetValue();
}

void PropertyLinkSubList::setValues(const std::vector<DocumentObject*>& lValue,
                                    const std::vector<const char*>& lSubNames)
{
    auto parent = freecad_cast<App::DocumentObject*>(getContainer());
    for (auto obj : lValue) {
        verifyObject(obj, parent);
    }

    if (lValue.size() != lSubNames.size()) {
        throw Base::ValueError(
            "PropertyLinkSubList::setValues: size of subelements list != size of objects list");
    }

    // maintain backlinks.
    if (parent) {
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            //_lValueList can contain items multiple times, but we trust the document
            // object to ensure that this works
            for (auto* obj : _lValueList) {
                if (obj) {
                    obj->_removeBackLink(parent);
                    obj->_removeBackLinkProp(getName(), parent);
                }
            }

            // maintain backlinks. lValue can contain items multiple times, but we trust the
            // document object to ensure that the backlink is only added once
            for (auto* obj : lValue) {
                if (obj) {
                    obj->_addBackLink(parent);
                    obj->_addBackLinkProp(getName(), parent);
                }
            }
        }
    }

    aboutToSetValue();
    _lValueList = lValue;
    _lSubList.resize(lSubNames.size());
    int i = 0;
    for (std::vector<const char*>::const_iterator it = lSubNames.begin(); it != lSubNames.end();
         ++it, ++i) {
        if (*it) {
            _lSubList[i] = *it;
        }
    }
    updateElementReference(nullptr);
    checkLabelReferences(_lSubList);
    hasSetValue();
}

void PropertyLinkSubList::setValues(const std::vector<DocumentObject*>& lValue,
                                    const std::vector<std::string>& lSubNames,
                                    std::vector<ShadowSub>&& ShadowSubList)
{
    setValues(std::vector<DocumentObject*>(lValue),
              std::vector<std::string>(lSubNames),
              std::move(ShadowSubList));
}

void PropertyLinkSubList::setValues(std::vector<DocumentObject*>&& lValue,
                                    std::vector<std::string>&& lSubNames,
                                    std::vector<ShadowSub>&& ShadowSubList)
{
    auto parent = freecad_cast<App::DocumentObject*>(getContainer());
    for (auto obj : lValue) {
        verifyObject(obj, parent);
    }
    if (lValue.size() != lSubNames.size()) {
        throw Base::ValueError(
            "PropertyLinkSubList::setValues: size of subelements list != size of objects list");
    }

    // maintain backlinks.
    if (parent) {
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            //_lValueList can contain items multiple times, but we trust the document
            // object to ensure that this works
            for (auto* obj : _lValueList) {
                if (obj) {
                    obj->_removeBackLink(parent);
                    obj->_removeBackLinkProp(getName(), parent);
                }
            }

            // maintain backlinks. lValue can contain items multiple times, but we trust the
            // document object to ensure that the backlink is only added once
            for (auto* obj : lValue) {
                if (obj) {
                    obj->_addBackLink(parent);
                    obj->_addBackLinkProp(getName(), parent);
                }
            }
        }
    }

    aboutToSetValue();
    // A guess record (ops#127) stays with a reference passed on with its shadow (a restore, a
    // paste); a sub chosen anew drops it.
    if (ShadowSubList.size() != lSubNames.size() || _Guesses.size() != lSubNames.size()) {
        _Guesses.assign(lSubNames.size(), GuessRecord());
    }
    else {
        for (std::size_t i = 0; i < lSubNames.size(); ++i) {
            if (ShadowSubList[i].oldName.empty() && ShadowSubList[i].newName.empty()) {
                _Guesses[i] = GuessRecord();
            }
        }
    }
    // The reorder's re-target records (ops#127) stay with references passed on with their shadows
    keepRetargetRecords(_Retargets, lSubNames.size(), ShadowSubList);
    _lValueList = std::move(lValue);
    _lSubList = std::move(lSubNames);
    if (ShadowSubList.size() == _lSubList.size()) {
        _ShadowSubList = std::move(ShadowSubList);
        onContainerRestored();  // re-register element references
    }
    else {
        updateElementReference(nullptr);
    }
    checkLabelReferences(_lSubList);
    hasSetValue();
}

void PropertyLinkSubList::setValue(DocumentObject* lValue, const std::vector<std::string>& SubList)
{
    auto parent = dynamic_cast<App::DocumentObject*>(getContainer());
    verifyObject(lValue, parent);

    // maintain backlinks.
    if (parent) {
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            //_lValueList can contain items multiple times, but we trust the document
            // object to ensure that this works
            for (auto* obj : _lValueList) {
                if (obj) {
                    obj->_removeBackLink(parent);
                    obj->_removeBackLinkProp(getName(), parent);
                }
            }

            // maintain backlinks. lValue can contain items multiple times, but we trust the
            // document object to ensure that the backlink is only added once
            if (lValue) {
                lValue->_addBackLink(parent);
                lValue->_addBackLinkProp(getName(), parent);
            }
        }
    }

    aboutToSetValue();
    std::size_t size = SubList.size();
    this->_lValueList.clear();
    this->_lSubList.clear();
    if (size == 0) {
        if (lValue) {
            this->_lValueList.push_back(lValue);
            this->_lSubList.emplace_back();
        }
    }
    else {
        this->_lSubList = SubList;
        this->_lValueList.insert(this->_lValueList.begin(), size, lValue);
    }
    updateElementReference(nullptr);
    checkLabelReferences(_lSubList);
    hasSetValue();
}

void PropertyLinkSubList::addValue(App::DocumentObject* obj,
                                   const std::vector<std::string>& subs,
                                   bool reset)
{
    auto parent = freecad_cast<App::DocumentObject*>(getContainer());
    verifyObject(obj, parent);

    // maintain backlinks.
    if (parent) {
        // before accessing internals make sure the object is not about to be destroyed
        // otherwise the backlink contains dangling pointers
        if (!parent->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
            //_lValueList can contain items multiple times, but we trust the document
            // object to ensure that this works
            if (reset) {
                for (auto* value : _lValueList) {
                    if (value && value == obj) {
                        value->_removeBackLink(parent);
                        value->_removeBackLinkProp(getName(), parent);
                    }
                }
            }

            // maintain backlinks. lValue can contain items multiple times, but we trust the
            // document object to ensure that the backlink is only added once
            if (obj) {
                obj->_addBackLink(parent);
                obj->_addBackLinkProp(getName(), parent);
            }
        }
    }

    std::vector<DocumentObject*> valueList;
    std::vector<std::string> subList;

    if (reset) {
        for (std::size_t i = 0; i < _lValueList.size(); i++) {
            if (_lValueList[i] != obj) {
                valueList.push_back(_lValueList[i]);
                subList.push_back(_lSubList[i]);
            }
        }
    }
    else {
        valueList = _lValueList;
        subList = _lSubList;
    }

    std::size_t size = subs.size();
    if (size == 0) {
        if (obj) {
            valueList.push_back(obj);
            subList.emplace_back();
        }
    }
    else if (obj) {
        subList.insert(subList.end(), subs.begin(), subs.end());
        valueList.insert(valueList.end(), size, obj);
    }

    aboutToSetValue();
    _lValueList = valueList;
    _lSubList = subList;
    updateElementReference(nullptr);
    checkLabelReferences(_lSubList);
    hasSetValue();
}

const string PropertyLinkSubList::getPyReprString() const
{
    assert(this->_lValueList.size() == this->_lSubList.size());

    if (this->_lValueList.empty()) {
        return std::string("None");
    }

    std::stringstream strm;
    strm << "[";
    for (std::size_t i = 0; i < this->_lSubList.size(); i++) {
        if (i > 0) {
            strm << ",(";
        }
        else {
            strm << "(";
        }
        App::DocumentObject* obj = this->_lValueList[i];
        if (obj) {
            strm << "App.getDocument('" << obj->getDocument()->getName() << "').getObject('"
                 << obj->getNameInDocument() << "')";
        }
        else {
            strm << "None";
        }
        strm << ",";
        strm << "'" << this->_lSubList[i] << "'";
        strm << ")";
    }
    strm << "]";
    return strm.str();
}

DocumentObject* PropertyLinkSubList::getValue() const
{
    App::DocumentObject* ret = nullptr;
    // FIXME: cache this to avoid iterating each time, to improve speed
    for (auto i : this->_lValueList) {
        if (!ret) {
            ret = i;
        }
        if (ret != i) {
            return nullptr;
        }
    }
    return ret;
}

int PropertyLinkSubList::removeValue(App::DocumentObject* lValue)
{
    assert(this->_lValueList.size() == this->_lSubList.size());

    std::size_t num = std::count(this->_lValueList.begin(), this->_lValueList.end(), lValue);
    if (num == 0) {
        return 0;
    }

    std::vector<DocumentObject*> links;
    std::vector<std::string> subs;
    links.reserve(this->_lValueList.size() - num);
    subs.reserve(this->_lSubList.size() - num);

    for (std::size_t i = 0; i < this->_lValueList.size(); ++i) {
        if (this->_lValueList[i] != lValue) {
            links.push_back(this->_lValueList[i]);
            subs.push_back(this->_lSubList[i]);
        }
    }

    setValues(links, subs);
    return static_cast<int>(num);
}

void PropertyLinkSubList::setSubListValues(const std::vector<PropertyLinkSubList::SubSet>& values)
{
    std::vector<DocumentObject*> links;
    std::vector<std::string> subs;
    for (std::vector<PropertyLinkSubList::SubSet>::const_iterator it = values.begin();
         it != values.end();
         ++it) {
        if (it->second.empty()) {
            links.push_back(it->first);
            subs.emplace_back();
            continue;
        }
        for (std::vector<std::string>::const_iterator jt = it->second.begin();
             jt != it->second.end();
             ++jt) {
            links.push_back(it->first);
            subs.push_back(*jt);
        }
    }
    setValues(links, subs);
}

std::vector<PropertyLinkSubList::SubSet> PropertyLinkSubList::getSubListValues(bool newStyle) const
{
    std::vector<PropertyLinkSubList::SubSet> values;
    if (_lValueList.size() != _lSubList.size()) {
        throw Base::ValueError("PropertyLinkSubList::getSubListValues: size of subelements list != "
                               "size of objects list");
    }

    assert(_ShadowSubList.size() == _lSubList.size());

    for (std::size_t i = 0; i < _lValueList.size(); i++) {
        App::DocumentObject* link = _lValueList[i];
        std::string sub;
        if (newStyle && !_ShadowSubList[i].newName.empty()) {
            sub = _ShadowSubList[i].newName;
        }
        else if (!newStyle && !_ShadowSubList[i].oldName.empty()) {
            sub = _ShadowSubList[i].oldName;
        }
        else {
            sub = _lSubList[i];
        }
        if (values.empty() || values.back().first != link) {
            // new object started, start a new subset.
            values.emplace_back(link, std::vector<std::string>());
        }
        values.back().second.push_back(sub);
    }
    return values;
}

PyObject* PropertyLinkSubList::getPyObject()
{
    std::vector<SubSet> subLists = getSubListValues();
    std::size_t count = subLists.size();
#if 0  // FIXME: Should switch to tuple
    Py::Tuple sequence(count);
#else
    Py::List sequence(count);
#endif
    for (std::size_t i = 0; i < count; i++) {
        Py::Tuple tup(2);
        tup[0] = Py::asObject(subLists[i].first->getPyObject());

        const std::vector<std::string>& sub = subLists[i].second;
        Py::Tuple items(sub.size());
        for (std::size_t j = 0; j < sub.size(); j++) {
            items[j] = Py::String(sub[j]);
        }

        tup[1] = items;
        sequence[i] = tup;
    }

    return Py::new_reference_to(sequence);
}

void PropertyLinkSubList::setPyObject(PyObject* value)
{
    try {  // try PropertyLinkSub syntax
        PropertyLinkSub dummy;
        dummy.setPyObject(value);
        this->setValue(dummy.getValue(), dummy.getSubValues());
        return;
    }
    catch (...) {
    }
    try {
        // try PropertyLinkList syntax
        PropertyLinkList dummy;
        dummy.setPyObject(value);
        const auto& values = dummy.getValues();
        std::vector<std::string> subs(values.size());
        this->setValues(values, subs);
        return;
    }
    catch (...) {
    }

    static const char* errMsg =
        "Expects sequence of items of type DocObj, (DocObj,SubName), or (DocObj, (SubName,...))";

    if (!PyTuple_Check(value) && !PyList_Check(value)) {
        throw Base::TypeError(errMsg);
    }

    Py::Sequence list(value);
    Py::Sequence::size_type size = list.size();

    std::vector<DocumentObject*> values;
    values.reserve(size);
    std::vector<std::string> SubNames;
    SubNames.reserve(size);
    for (Py::Sequence::size_type i = 0; i < size; i++) {
        Py::Object item = list[i];
        if ((item.isTuple() || item.isSequence()) && PySequence_Size(*item) == 2) {
            Py::Sequence seq(item);
            if (PyObject_TypeCheck(seq[0].ptr(), &(DocumentObjectPy::Type))) {
                auto obj = static_cast<DocumentObjectPy*>(seq[0].ptr())->getDocumentObjectPtr();
                PropertyString propString;
                if (seq[1].isString()) {
                    values.push_back(obj);
                    propString.setPyObject(seq[1].ptr());
                    SubNames.emplace_back(propString.getValue());
                }
                else if (seq[1].isSequence()) {
                    Py::Sequence list(seq[1]);
                    for (Py::Sequence::iterator it = list.begin(); it != list.end(); ++it) {
                        if (!(*it).isString()) {
                            throw Base::TypeError(errMsg);
                        }
                        values.push_back(obj);
                        propString.setPyObject((*it).ptr());
                        SubNames.emplace_back(propString.getValue());
                    }
                }
                else {
                    throw Base::TypeError(errMsg);
                }
            }
        }
        else if (PyObject_TypeCheck(*item, &(DocumentObjectPy::Type))) {
            DocumentObjectPy* pcObj;
            pcObj = static_cast<DocumentObjectPy*>(*item);
            values.push_back(pcObj->getDocumentObjectPtr());
            SubNames.emplace_back();
        }
        else {
            throw Base::TypeError(errMsg);
        }
    }
    setValues(values, SubNames);
}

void PropertyLinkSubList::afterRestore()
{
    assert(_lSubList.size() == _ShadowSubList.size());
    if (!testFlag(LinkRestoreLabel)) {
        return;
    }
    setFlag(LinkRestoreLabel, false);
    for (size_t i = 0; i < _lSubList.size(); ++i) {
        restoreLabelReference(_lValueList[i], _lSubList[i], &_ShadowSubList[i]);
    }
}

void PropertyLinkSubList::onContainerRestored()
{
    unregisterElementReference();
    holdRestoredRetargetChecks(this, nullptr, &_lValueList, _lSubList);
    for (size_t i = 0; i < _lSubList.size(); ++i) {
        _registerElementReference(_lValueList[i], _lSubList[i], _ShadowSubList[i]);
    }
    _updateElementFingerprints(nullptr, nullptr, &_lValueList, _lSubList, _ShadowSubList, _Fingerprints);
}

bool PropertyLinkSubList::updateElementFingerprints()
{
    return _updateElementFingerprints(nullptr,
                                      nullptr,
                                      &_lValueList,
                                      _lSubList,
                                      _ShadowSubList,
                                      _Fingerprints);
}

// The reference solver's passes (ops#7).
void PropertyLinkSubList::collectElementReferences(App::DocumentObject* feature, SolverBatch& batch)
{
    collectLinkReferences(this,
                          feature,
                          batch,
                          nullptr,
                          &_lValueList,
                          _lSubList,
                          _ShadowSubList,
                          _Fingerprints,
                          nullptr,
                          &_Guesses);
}

void PropertyLinkSubList::applyResolutions(const std::vector<SolverResolution>& resolutions)
{
    if (resolutions.empty()) {
        return;
    }
    const auto& context = resolutions.front();
    bool changed = writeLinkResolutions(resolutions,
                                        _lSubList,
                                        _ShadowSubList,
                                        _Fingerprints,
                                        _Guesses,
                                        [this]() { aboutToSetValue(); });
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (changed) {
        // As updateElementReference() does.
        std::vector<int> mapped;
        mapped.reserve(_mapped.size());
        for (int idx : _mapped) {
            if (idx < (int)_lSubList.size()) {
                if (!_ShadowSubList[idx].newName.empty()) {
                    _lSubList[idx] = _ShadowSubList[idx].newName;
                }
                else {
                    mapped.push_back(idx);
                }
            }
        }
        _mapped.swap(mapped);
        if (owner && context.feature) {
            owner->onUpdateElementReference(this);
        }
    }
    _updateElementFingerprints(context.feature,
                               nullptr,
                               &_lValueList,
                               _lSubList,
                               _ShadowSubList,
                               _Fingerprints);
    if (changed && context.notify) {
        hasSetValue();
    }
}

std::vector<std::string> PropertyLinkSubList::getElementFingerprints() const
{
    auto fingerprints = _Fingerprints;
    fingerprints.resize(_lSubList.size());
    return fingerprints;
}

std::vector<GuessRecord> PropertyLinkSubList::getElementGuesses() const
{
    auto guesses = _Guesses;
    guesses.resize(_lSubList.size());
    return guesses;
}

void PropertyLinkSubList::updateElementReference(DocumentObject* feature, bool reverse, bool notify)
{
    if (!feature) {
        // A value set without shadows: the subs are chosen anew, so their re-target records end
        // (ops#127)
        _ShadowSubList.clear();
        _Guesses.clear();  // a sub set anew (ops#127)
        _Retargets.clear();
        unregisterElementReference();
    }
    _ShadowSubList.resize(_lSubList.size());
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (owner && owner->isRestoring()) {
        return;
    }
    if (feature && inSolverDocument()) {
        // The reference solver (ops#7), for this property alone.
        App::solveElementReferences(feature, {this}, reverse, notify);
        return;
    }
    int i = 0;
    bool touched = false;
    for (auto& sub : _lSubList) {
        auto obj = _lValueList[i];
        if (_updateElementReference(feature,
                                    obj,
                                    sub,
                                    _ShadowSubList[i++],
                                    reverse,
                                    notify && !touched)) {
            touched = true;
        }
    }
    _updateElementFingerprints(feature, nullptr, &_lValueList, _lSubList, _ShadowSubList, _Fingerprints);
    if (!touched) {
        return;
    }

    std::vector<int> mapped;
    mapped.reserve(_mapped.size());
    for (int idx : _mapped) {
        if (idx < (int)_lSubList.size()) {
            if (!_ShadowSubList[idx].newName.empty()) {
                _lSubList[idx] = _ShadowSubList[idx].newName;
            }
            else {
                mapped.push_back(idx);
            }
        }
    }
    _mapped.swap(mapped);
    if (owner && feature) {
        owner->onUpdateElementReference(this);
    }
    if (notify) {
        hasSetValue();
    }
}

bool PropertyLinkSubList::referenceChanged() const
{
    return !_mapped.empty();
}

void PropertyLinkSubList::Save(Base::Writer& writer) const
{
    assert(_lSubList.size() == _ShadowSubList.size());

    int count = 0;
    for (auto obj : _lValueList) {
        if (obj && obj->isAttachedToDocument()) {
            ++count;
        }
    }
    writer.Stream() << writer.ind() << "<LinkSubList count=\"" << count << "\">" << endl;
    writer.incInd();
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    bool exporting = owner && owner->isExporting();
    const bool saveFingerprints = inSolverDocument();
    for (int i = 0; i < getSize(); i++) {
        auto obj = _lValueList[i];
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        const auto& shadow = _ShadowSubList[i];
        // shadow.oldName stores the old style element name. For backward
        // compatibility reason, we shall store the old name into attribute
        // 'value' whenever possible.
        const auto& sub = shadow.oldName.empty() ? _lSubList[i] : shadow.oldName;

        writer.Stream() << writer.ind() << "<Link obj=\"" << obj->getExportName() << "\" sub=\"";
        if (exporting) {
            std::string exportName;
            writer.Stream() << encodeAttribute(exportSubName(exportName, obj, sub.c_str()));
            if (!shadow.oldName.empty() && _lSubList[i] == shadow.newName) {
                writer.Stream() << "\" " ATTR_MAPPED "=\"1";
            }
        }
        else {
            writer.Stream() << encodeAttribute(sub);
            if (!_lSubList[i].empty()) {
                if (sub != _lSubList[i]) {
                    // Stores the actual value that is shadowed. For new version FC,
                    // we will restore this shadowed value instead.
                    writer.Stream() << "\" " ATTR_SHADOWED "=\"" << encodeAttribute(_lSubList[i]);
                }
                else if (!shadow.newName.empty()) {
                    // Here means the user set value is old style element name.
                    // We shall then store the shadow somewhere else.
                    writer.Stream() << "\" " ATTR_SHADOW "=\"" << encodeAttribute(shadow.newName);
                }
            }
        }
        if (saveFingerprints && i < (int)_Fingerprints.size() && !_Fingerprints[i].empty()) {
            writer.Stream() << "\" " ATTR_FINGERPRINT "=\"" << encodeAttribute(_Fingerprints[i]);
        }
        if (saveFingerprints) {
            writeGuessRecord(writer, _Guesses, i);
        }
        writeRetargetRecord(writer, _Retargets, i);
        writeRetargetCheck(writer, this, obj, _lSubList[i], shadow);
        writer.Stream() << "\"/>" << endl;
    }

    writer.decInd();
    writer.Stream() << writer.ind() << "</LinkSubList>" << endl;
}

void PropertyLinkSubList::Restore(Base::XMLReader& reader)
{
    // read my element
    reader.readElement("LinkSubList");
    // get the value of my attribute
    int count = reader.getAttribute<long>("count");

    std::vector<DocumentObject*> values;
    values.reserve(count);
    std::vector<std::string> SubNames;
    SubNames.reserve(count);
    std::vector<ShadowSub> shadows;
    shadows.reserve(count);
    std::vector<std::string> fingerprints;
    fingerprints.reserve(count);
    std::vector<GuessRecord> guesses;
    guesses.reserve(count);
    std::vector<RetargetRecord> retargets;
    retargets.reserve(count);
    DocumentObject* father = freecad_cast<DocumentObject*>(getContainer());
    App::Document* document = father ? father->getDocument() : nullptr;
    std::vector<int> mapped;
    std::vector<std::pair<std::size_t, Data::ElementFingerprint>> checks;
    bool restoreLabel = false;
    for (int i = 0; i < count; i++) {
        reader.readElement("Link");
        std::string name = reader.getName(reader.getAttribute<const char*>("obj"));
        // In order to do copy/paste it must be allowed to have defined some
        // referenced objects in XML which do not exist anymore in the new
        // document. Thus, we should silently ignore this.
        // Property not in an object!
        DocumentObject* child = document ? document->getObject(name.c_str()) : nullptr;
        if (child) {
            readRetargetCheck(reader, values.size(), checks);
            values.push_back(child);
            shadows.emplace_back();
            fingerprints.emplace_back(reader.hasAttribute(ATTR_FINGERPRINT)
                                          ? reader.getAttribute<const char*>(ATTR_FINGERPRINT)
                                          : "");
            guesses.push_back(readGuessRecord(reader));
            retargets.push_back(readRetargetRecord(reader));
            auto& shadow = shadows.back();
            shadow.oldName = importSubName(reader, reader.getAttribute<const char*>("sub"), restoreLabel);
            if (reader.hasAttribute(ATTR_SHADOWED) && !IGNORE_SHADOW) {
                shadow.newName =
                    importSubName(reader, reader.getAttribute<const char*>(ATTR_SHADOWED), restoreLabel);
                SubNames.push_back(shadow.newName);
            }
            else {
                SubNames.push_back(shadow.oldName);
                if (reader.hasAttribute(ATTR_SHADOW) && !IGNORE_SHADOW) {
                    shadow.newName =
                        importSubName(reader, reader.getAttribute<const char*>(ATTR_SHADOW), restoreLabel);
                }
            }
            if (reader.hasAttribute(ATTR_MAPPED)) {
                mapped.push_back(i);
            }
        }
        else if (reader.isVerbose()) {
            Base::Console().warning("Lost link to '%s' while loading, maybe "
                                    "an object was not loaded correctly\n",
                                    name.c_str());
        }
    }
    setFlag(LinkRestoreLabel, restoreLabel);

    reader.readEndElement("LinkSubList");
    keepRestoredRetargetChecks(this, std::move(checks));

    // assignment
    setValues(values, SubNames, std::move(shadows));
    if (fingerprints.size() == _lSubList.size()) {
        _Fingerprints = std::move(fingerprints);
    }
    if (guesses.size() == _lSubList.size()) {
        _Guesses = std::move(guesses);
    }
    if (retargets.size() == _lSubList.size()) {
        _Retargets = std::move(retargets);
    }
    _mapped.swap(mapped);
}

bool PropertyLinkSubList::upgrade(Base::XMLReader& reader, const char* typeName)
{
    Base::Type type = Base::Type::fromName(typeName);
    if (type.isDerivedFrom(PropertyLink::getClassTypeId())) {
        PropertyLink prop;
        prop.setContainer(getContainer());
        prop.Restore(reader);
        setValue(prop.getValue());
        return true;
    }
    else if (type.isDerivedFrom(PropertyLinkList::getClassTypeId())) {
        PropertyLinkList prop;
        prop.setContainer(getContainer());
        prop.Restore(reader);
        std::vector<std::string> subnames;
        subnames.resize(prop.getSize());
        setValues(prop.getValues(), subnames);
        return true;
    }
    else if (type.isDerivedFrom(PropertyLinkSub::getClassTypeId())) {
        PropertyLinkSub prop;
        prop.setContainer(getContainer());
        prop.Restore(reader);
        setValue(prop.getValue(), prop.getSubValues());
        return true;
    }

    return false;
}

Property*
PropertyLinkSubList::CopyOnImportExternal(const std::map<std::string, std::string>& nameMap) const
{
    auto owner = dynamic_cast<const DocumentObject*>(getContainer());
    if (!owner || !owner->getDocument() || _lValueList.size() != _lSubList.size()) {
        return nullptr;
    }
    std::vector<App::DocumentObject*> values;
    std::vector<std::string> subs;
    auto itSub = _lSubList.begin();
    for (auto itValue = _lValueList.begin(); itValue != _lValueList.end(); ++itValue, ++itSub) {
        auto value = *itValue;
        const auto& sub = *itSub;
        if (!value || !value->isAttachedToDocument()) {
            if (!values.empty()) {
                values.push_back(value);
                subs.push_back(sub);
            }
            continue;
        }
        auto linked = tryImport(owner->getDocument(), value, nameMap);
        auto new_sub = tryImportSubName(value, sub.c_str(), owner->getDocument(), nameMap);
        if (linked != value || !new_sub.empty()) {
            if (values.empty()) {
                values.reserve(_lValueList.size());
                values.insert(values.end(), _lValueList.begin(), itValue);
                subs.reserve(_lSubList.size());
                subs.insert(subs.end(), _lSubList.begin(), itSub);
            }
            values.push_back(linked);
            subs.push_back(std::move(new_sub));
        }
        else if (!values.empty()) {
            values.push_back(linked);
            subs.push_back(sub);
        }
    }
    if (values.empty()) {
        return nullptr;
    }
    std::unique_ptr<PropertyLinkSubList> p(new PropertyLinkSubList);
    p->_lValueList = std::move(values);
    p->_lSubList = std::move(subs);
    return p.release();
}

Property* PropertyLinkSubList::CopyOnLabelChange(App::DocumentObject* obj,
                                                 const std::string& ref,
                                                 const char* newLabel) const
{
    auto owner = dynamic_cast<const DocumentObject*>(getContainer());
    if (!owner || !owner->getDocument()) {
        return nullptr;
    }
    std::vector<App::DocumentObject*> values;
    std::vector<std::string> subs;
    auto itSub = _lSubList.begin();
    for (auto itValue = _lValueList.begin(); itValue != _lValueList.end(); ++itValue, ++itSub) {
        auto value = *itValue;
        const auto& sub = *itSub;
        if (!value || !value->isAttachedToDocument()) {
            if (!values.empty()) {
                values.push_back(value);
                subs.push_back(sub);
            }
            continue;
        }
        auto new_sub = updateLabelReference(value, sub.c_str(), obj, ref, newLabel);
        if (!new_sub.empty()) {
            if (values.empty()) {
                values.reserve(_lValueList.size());
                values.insert(values.end(), _lValueList.begin(), itValue);
                subs.reserve(_lSubList.size());
                subs.insert(subs.end(), _lSubList.begin(), itSub);
            }
            values.push_back(value);
            subs.push_back(std::move(new_sub));
        }
        else if (!values.empty()) {
            values.push_back(value);
            subs.push_back(sub);
        }
    }
    if (values.empty()) {
        return nullptr;
    }
    std::unique_ptr<PropertyLinkSubList> p(new PropertyLinkSubList);
    p->_lValueList = std::move(values);
    p->_lSubList = std::move(subs);
    return p.release();
}

Property* PropertyLinkSubList::CopyOnLinkReplace(const App::DocumentObject* parent,
                                                 App::DocumentObject* oldObj,
                                                 App::DocumentObject* newObj) const
{
    std::vector<App::DocumentObject*> values;
    std::vector<std::string> subs;
    auto itSub = _lSubList.begin();
    std::vector<size_t> positions;
    for (auto itValue = _lValueList.begin(); itValue != _lValueList.end(); ++itValue, ++itSub) {
        auto value = *itValue;
        const auto& sub = *itSub;
        if (!value || !value->isAttachedToDocument()) {
            if (!values.empty()) {
                values.push_back(value);
                subs.push_back(sub);
            }
            continue;
        }
        auto res = tryReplaceLink(getContainer(), value, parent, oldObj, newObj, sub.c_str());
        if (res.first) {
            if (values.empty()) {
                values.reserve(_lValueList.size());
                values.insert(values.end(), _lValueList.begin(), itValue);
                subs.reserve(_lSubList.size());
                subs.insert(subs.end(), _lSubList.begin(), itSub);
            }
            if (res.first == newObj) {
                // check for duplication
                auto itS = subs.begin();
                for (auto itV = values.begin(); itV != values.end();) {
                    if (*itV == res.first && *itS == res.second) {
                        itV = values.erase(itV);
                        itS = subs.erase(itS);
                    }
                    else {
                        ++itV;
                        ++itS;
                    }
                }
                positions.push_back(values.size());
            }
            values.push_back(res.first);
            subs.push_back(std::move(res.second));
        }
        else if (!values.empty()) {
            bool duplicate = false;
            if (value == newObj) {
                for (auto pos : positions) {
                    if (sub == subs[pos]) {
                        duplicate = true;
                        break;
                    }
                }
            }
            if (!duplicate) {
                values.push_back(value);
                subs.push_back(sub);
            }
        }
    }
    if (values.empty()) {
        return nullptr;
    }
    std::unique_ptr<PropertyLinkSubList> p(new PropertyLinkSubList);
    p->_lValueList = std::move(values);
    p->_lSubList = std::move(subs);
    return p.release();
}

Property* PropertyLinkSubList::Copy() const
{
    PropertyLinkSubList* p = new PropertyLinkSubList();
    p->_lValueList = _lValueList;
    p->_lSubList = _lSubList;
    p->_ShadowSubList = _ShadowSubList;
    p->_Guesses = _Guesses;
    // Undo and redo restore a property through Paste: the fingerprints and the reorder's
    // re-target records come back with their references (ops#127)
    p->_Fingerprints = _Fingerprints;
    p->_Retargets = _Retargets;
    return p;
}

void PropertyLinkSubList::Paste(const Property& from)
{
    if (!from.isDerivedFrom<PropertyLinkSubList>()) {
        throw Base::TypeError("Incompatible property to paste to");
    }
    auto& link = static_cast<const PropertyLinkSubList&>(from);
    setValues(link._lValueList, link._lSubList, std::vector<ShadowSub>(link._ShadowSubList));
    // Undo and redo restore a property through Paste: a guess comes back with its record
    // (ops#127).
    if (link._Guesses.size() == _lSubList.size()) {
        _Guesses = link._Guesses;
    }
    if (link._Fingerprints.size() == _lSubList.size()) {
        _Fingerprints = link._Fingerprints;
    }
    _Retargets = link._Retargets;
    _Retargets.resize(_lSubList.size());
}

void PropertyLinkSubList::setRetargets(std::vector<RetargetRecord>&& records)
{
    aboutToSetValue();
    _Retargets = std::move(records);
    _Retargets.resize(_lSubList.size());
    hasSetValue();
}

void PropertyLinkSubList::setElementFingerprint(std::size_t index, const std::string& fingerprint)
{
    if (index >= _lSubList.size()) {
        return;
    }
    aboutToSetValue();
    _Fingerprints.resize(_lSubList.size());
    _Fingerprints[index] = fingerprint;
    hasSetValue();
}

unsigned int PropertyLinkSubList::getMemSize() const
{
    unsigned int size =
        static_cast<unsigned int>(_lValueList.size() * sizeof(App::DocumentObject*));
    for (int i = 0; i < getSize(); i++) {
        size += _lSubList[i].size();
    }
    return size;
}

std::vector<std::string> PropertyLinkSubList::getSubValues(bool newStyle) const
{
    assert(_lSubList.size() == _ShadowSubList.size());
    std::vector<std::string> ret;
    ret.reserve(_ShadowSubList.size());
    std::string tmp;
    for (size_t i = 0; i < _ShadowSubList.size(); ++i) {
        ret.push_back(getSubNameWithStyle(_lSubList[i], _ShadowSubList[i], newStyle, tmp));
    }
    return ret;
}

void PropertyLinkSubList::getLinks(std::vector<App::DocumentObject*>& objs,
                                   bool all,
                                   std::vector<std::string>* subs,
                                   bool newStyle) const
{
    if (all || _pcScope != LinkScope::Hidden) {
        objs.reserve(objs.size() + _lValueList.size());
        for (auto obj : _lValueList) {
            if (obj && obj->isAttachedToDocument()) {
                // we use to run this method everytime the program needed to access the sub-elements in
                // a property link, but it caused multiple issues (#23441 and #23402) so it has been
                // commented out.
                // updateElementReferences(obj);
                objs.push_back(obj);
            }
        }
        if (subs) {
            auto _subs = getSubValues(newStyle);
            subs->reserve(subs->size() + _subs.size());
            std::move(_subs.begin(), _subs.end(), std::back_inserter(*subs));
        }
    }
}

void PropertyLinkSubList::getLinksTo(std::vector<App::ObjectIdentifier>& identifiers,
                                     App::DocumentObject* obj,
                                     const char* subname,
                                     bool all) const
{
    if (!obj || (!all && _pcScope == LinkScope::Hidden)) {
        return;
    }
    App::SubObjectT objT(obj, subname);
    auto subObject = objT.getSubObject();
    auto subElement = objT.getOldElementName();

    int i = -1;
    for (const auto& docObj : _lValueList) {
        ++i;
        if (docObj != obj) {
            continue;
        }
        // If we don't specify a subname we looking for all; or if the subname is in our
        // property, add this entry to our result
        if (!subname || (i < (int)_lSubList.size() && subname == _lSubList[i])) {
            identifiers.emplace_back(*this, i);
            continue;
        }
        // If we couldn't find any subobjects or this object's index is in our list, ignore it
        if (!subObject || i < (int)_lSubList.size()) {
            continue;
        }
        App::SubObjectT sobjT(obj, _lSubList[i].c_str());
        if (sobjT.getSubObject() == subObject && sobjT.getOldElementName() == subElement) {
            identifiers.emplace_back(*this);
            continue;
        }
        if (i < (int)_ShadowSubList.size()) {
            const auto& shadow = _ShadowSubList[i];
            App::SubObjectT sobjT(obj,
                                  shadow.newName.empty() ? shadow.oldName.c_str()
                                                         : shadow.newName.c_str());
            if (sobjT.getSubObject() == subObject && sobjT.getOldElementName() == subElement) {
                identifiers.emplace_back(*this);
                continue;
            }
        }
    }
}

void PropertyLinkSubList::breakLink(App::DocumentObject* obj, bool clear)
{
    std::vector<DocumentObject*> values;
    std::vector<std::string> subs;

    if (clear && getContainer() == obj) {
        setValues(values, subs);
        return;
    }
    assert(_lValueList.size() == _lSubList.size());

    values.reserve(_lValueList.size());
    subs.reserve(_lSubList.size());

    int i = -1;
    for (auto o : _lValueList) {
        ++i;
        if (o == obj) {
            continue;
        }
        values.push_back(o);
        subs.push_back(_lSubList[i]);
    }
    if (values.size() != _lValueList.size()) {
        setValues(values, subs);
    }
}

bool PropertyLinkSubList::adjustLink(const std::set<App::DocumentObject*>& inList)
{
    if (_pcScope == LinkScope::Hidden) {
        return false;
    }
    auto subs = _lSubList;
    auto links = _lValueList;
    int idx = -1;
    bool touched = false;
    for (std::string& sub : subs) {
        ++idx;
        auto& link = links[idx];
        if (!link || !link->isAttachedToDocument() || !inList.contains(link)) {
            continue;
        }
        touched = true;
        size_t pos = sub.find('.');
        for (; pos != std::string::npos; pos = sub.find('.', pos + 1)) {
            auto sobj = link->getSubObject(sub.substr(0, pos + 1).c_str());
            if (!sobj || sobj->getDocument() != link->getDocument()) {
                pos = std::string::npos;
                break;
            }
            if (!inList.contains(sobj)) {
                link = sobj;
                sub = sub.substr(pos + 1);
                break;
            }
        }
        if (pos == std::string::npos) {
            return false;
        }
    }
    if (touched) {
        setValues(links, subs);
    }
    return touched;
}

//**************************************************************************
// DocInfo
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

// Key on absolute path.
// Because of possible symbolic links, multiple entry may refer to the same
// file. We used to rely on QFileInfo::canonicalFilePath to resolve it, but
// has now been changed to simply use the absoluteFilePath(), and rely on user
// to be aware of possible duplicated file location. The reason being that
// some user (especially Linux user) use symlink to organize file tree.
using DocInfoMap = std::map<QString, DocInfoPtr>;
DocInfoMap _DocInfoMap;

class App::DocInfo: public std::enable_shared_from_this<App::DocInfo>
{
public:
    using Connection = fastsignals::scoped_connection;
    Connection connFinishRestoreDocument;
    Connection connPendingReloadDocument;
    Connection connDeleteDocument;
    Connection connSaveDocument;
    Connection connDeletedObject;

    DocInfoMap::iterator myPos;
    std::string myPath;
    App::Document* pcDoc {nullptr};
    std::set<PropertyXLink*> links;

    static std::string getDocPath(const char* filename,
                                  App::Document* pDoc,
                                  bool relative,
                                  QString* fullPath = nullptr)
    {
        bool absolute;
        // The path could be an URI, in that case
        // TODO: build a far much more resilient approach to test for an URI
        QString path = QString::fromUtf8(filename);
        if (path.startsWith(QLatin1String("https://"))) {
            // We do have an URI
            if (fullPath) {
                *fullPath = path;
            }
            return std::string(filename);
        }

        // make sure the filename is absolute path
        path = QDir::cleanPath(path);
        if ((absolute = QFileInfo(path).isAbsolute())) {
            if (fullPath) {
                *fullPath = path;
            }
            if (!relative) {
                return std::string(path.toUtf8().constData());
            }
        }

        const char* docPath = pDoc->getFileName();
        if (!docPath || *docPath == 0) {
            throw Base::RuntimeError("Owner document not saved");
        }

        QFileInfo docFileInfo{QString::fromUtf8(docPath)};
        QDir docDir(docFileInfo.canonicalPath());
        if (!absolute) {
            path = QDir::cleanPath(docDir.absoluteFilePath(path));
            if (fullPath) {
                *fullPath = path;
            }
        }

        if (relative) {
            return std::string(docDir.relativeFilePath(path).toUtf8().constData());
        }
        else {
            return std::string(path.toUtf8().constData());
        }
    }

    static DocInfoPtr
    get(const char* filename, App::Document* pDoc, PropertyXLink* l, const char* objName)
    {
        QString path;
        l->filePath = getDocPath(filename, pDoc, true, &path);

        FC_LOG("finding doc " << filename);

        auto it = _DocInfoMap.find(path);
        DocInfoPtr info;
        if (it != _DocInfoMap.end()) {
            info = it->second;
            if (!info->pcDoc) {
                QString fullpath(info->getFullPath());
                if (fullpath.size()
                    && App::GetApplication().addPendingDocument(
                           fullpath.toUtf8().constData(),
                           objName,
                           l->testFlag(PropertyLinkBase::LinkAllowPartial))
                        == 0) {
                    for (App::Document* doc : App::GetApplication().getDocuments()) {
                        if (getFullPath(doc->getFileName()) == fullpath) {
                            info->attach(doc);
                            break;
                        }
                    }
                }
            }
        }
        else {
            info = std::make_shared<DocInfo>();
            auto ret = _DocInfoMap.insert(std::make_pair(path, info));
            info->init(ret.first, objName, l);
        }

        if (info->pcDoc) {
            // make sure to attach only external object
            auto owner = freecad_cast<DocumentObject*>(l->getContainer());
            if (owner && owner->getDocument() == info->pcDoc) {
                return info;
            }
        }

        info->links.insert(l);
        return info;
    }

    static QString getFullPath(const char* p)
    {
        QString path = QString::fromUtf8(p);
        if (path.isEmpty()) {
            return path;
        }

        if (path.startsWith(QLatin1String("https://"))) {
            return path;
        }
        else {
            return QFileInfo(path).absoluteFilePath();
        }
    }

    QString getFullPath() const
    {
        QString path = myPos->first;
        if (path.startsWith(QLatin1String("https://"))) {
            return path;
        }
        else {
            return QFileInfo(myPos->first).absoluteFilePath();
        }
    }

    const char* filePath() const
    {
        return myPath.c_str();
    }

    void deinit()
    {
        FC_LOG("deinit " << (pcDoc ? pcDoc->getName() : filePath()));
        assert(links.empty());
        connFinishRestoreDocument.disconnect();
        connPendingReloadDocument.disconnect();
        connDeleteDocument.disconnect();
        connSaveDocument.disconnect();
        connDeletedObject.disconnect();

        auto me = shared_from_this();
        _DocInfoMap.erase(myPos);
        myPos = _DocInfoMap.end();
        myPath.clear();
        pcDoc = nullptr;
    }

    void init(DocInfoMap::iterator pos, const char* objName, PropertyXLink* l)
    {
        myPos = pos;
        myPath = myPos->first.toUtf8().constData();
        App::Application& app = App::GetApplication();
        // NOLINTBEGIN
        connFinishRestoreDocument = app.signalFinishRestoreDocument.connect(
            std::bind(&DocInfo::slotFinishRestoreDocument, this, sp::_1));
        connPendingReloadDocument = app.signalPendingReloadDocument.connect(
            std::bind(&DocInfo::slotFinishRestoreDocument, this, sp::_1));
        connDeleteDocument =
            app.signalDeleteDocument.connect(std::bind(&DocInfo::slotDeleteDocument, this, sp::_1));
        connSaveDocument =
            app.signalSaveDocument.connect(std::bind(&DocInfo::slotSaveDocument, this, sp::_1));
        // NOLINTEND

        QString fullpath(getFullPath());
        if (fullpath.isEmpty()) {
            FC_ERR("document not found " << filePath());
        }
        else {
            for (App::Document* doc : App::GetApplication().getDocuments()) {
                if (getFullPath(doc->getFileName()) == fullpath) {
                    if (doc->testStatus(App::Document::PartialDoc) && !doc->getObject(objName)) {
                        break;
                    }
                    attach(doc);
                    return;
                }
            }
            FC_LOG("document pending " << filePath());
            app.addPendingDocument(fullpath.toUtf8().constData(),
                                   objName,
                                   l->testFlag(PropertyLinkBase::LinkAllowPartial));
        }
    }

    void attach(Document* doc)
    {
        assert(!pcDoc);
        pcDoc = doc;
        FC_LOG("attaching " << doc->getName() << ", " << doc->getFileName());
        std::map<App::PropertyLinkBase*, std::vector<App::PropertyXLink*>> parentLinks;
        for (auto it = links.begin(), itNext = it; it != links.end(); it = itNext) {
            ++itNext;
            auto link = *it;
            if (link->_pcLink) {
                continue;
            }
            if (link->parentProp) {
                parentLinks[link->parentProp].push_back(link);
                continue;
            }
            auto obj = doc->getObject(link->objectName.c_str());
            if (obj) {
                link->restoreLink(obj);
            }
            else if (doc->testStatus(App::Document::PartialDoc)) {
                App::GetApplication().addPendingDocument(doc->FileName.getValue(),
                                                         link->objectName.c_str(),
                                                         false);
                FC_WARN("reloading partial document '" << doc->FileName.getValue()
                                                       << "' due to object " << link->objectName);
            }
            else {
                FC_WARN("object '" << link->objectName << "' not found in document '"
                                   << doc->getName() << "'");
            }
        }
        for (auto& v : parentLinks) {
            v.first->setFlag(PropertyLinkBase::LinkRestoring);
            v.first->aboutToSetValue();
            for (auto link : v.second) {
                auto obj = doc->getObject(link->objectName.c_str());
                if (obj) {
                    link->restoreLink(obj);
                }
                else if (doc->testStatus(App::Document::PartialDoc)) {
                    App::GetApplication().addPendingDocument(doc->FileName.getValue(),
                                                             link->objectName.c_str(),
                                                             false);
                    FC_WARN("reloading partial document '"
                            << doc->FileName.getValue() << "' due to object " << link->objectName);
                }
                else {
                    FC_WARN("object '" << link->objectName << "' not found in document '"
                                       << doc->getName() << "'");
                }
            }
            v.first->hasSetValue();
            v.first->setFlag(PropertyLinkBase::LinkRestoring, false);
        }
        // References through App::Links of other documents into this one (ops#120)
        registerLostReferences();
    }

    /// Resolves the shadows of \a link's registered references, as
    /// PropertyLinkBase::updateAllElementReferences() does, without notifying. Returns whether
    /// a sub-element changed.
    static bool updateElementReferences(PropertyXLink* link)
    {
        bool changed = false;
        std::optional<std::vector<std::string>> passed;  // the state before the pass
        std::vector<DocumentObject*> features(link->_ElementRefs.begin(),
                                              link->_ElementRefs.end());
        for (auto feature : features) {
            // The consumer pass (ops#116), as at the end of an open
            const bool reverse = takesConsumerPass(link, feature, false);
            std::optional<ConsumerPassScope> scope;
            if (reverse) {
                if (!passed) {
                    passed = referenceState(link);
                }
                scope.emplace();
            }
            if (reverse && link->inSolverDocument()) {
                changed = App::solveElementReferences(feature, {link}, true, false) || changed;
            }
            else {
                changed = updateLinkReference(link,
                                              feature,
                                              reverse,
                                              false,
                                              link->_pcLink,
                                              link->_SubList,
                                              link->_mapped,
                                              link->_ShadowSubList)
                    || changed;
            }
        }
        if (passed) {
            _PassedRefs.insert(link);
            // A reverse update reports every reference as changed
            changed = referenceState(link) != *passed;
            App::reportReferenceMigration();
        }
        return changed;
    }

    /// Lets \a xlink's references through \a link follow its new target (ops#42): see
    /// App::followLinkRetarget(). Notifies only when a shadow changes.
    static void
    followRetarget(PropertyXLink* xlink, App::DocumentObject* link, App::DocumentObject* oldTarget)
    {
        auto shadows = xlink->_ShadowSubList;
        bool changed = false;
        std::vector<RetargetCheck> checks;
        if (!retargetShadows(link,
                             oldTarget,
                             xlink->_pcLink,
                             nullptr,
                             xlink->_SubList,
                             shadows,
                             changed,
                             checks)) {
            return;
        }
        holdRetargetChecks(xlink, checks);
        if (changed) {
            xlink->aboutToSetValue();
        }
        xlink->unregisterElementReference();
        xlink->_ShadowSubList = std::move(shadows);
        xlink->onContainerRestored();
        if (changed) {
            xlink->hasSetValue();
        }
    }

    void remove(PropertyXLink* l)
    {
        auto it = links.find(l);
        if (it != links.end()) {
            links.erase(it);
            if (links.empty()) {
                deinit();
            }
        }
    }

    static void restoreDocument(const App::Document& doc)
    {
        auto it = _DocInfoMap.find(getFullPath(doc.FileName.getValue()));
        if (it == _DocInfoMap.end()) {
            return;
        }
        it->second->slotFinishRestoreDocument(doc);
    }

    void slotFinishRestoreDocument(const App::Document& doc)
    {
        if (pcDoc) {
            return;
        }
        QString fullpath(getFullPath());
        if (!fullpath.isEmpty() && getFullPath(doc.getFileName()) == fullpath) {
            attach(const_cast<App::Document*>(&doc));
        }
    }

    void slotSaveDocument(const App::Document& doc)
    {
        if (!pcDoc) {
            slotFinishRestoreDocument(doc);
            return;
        }
        if (&doc != pcDoc) {
            return;
        }

        QFileInfo info(myPos->first);
        QString path(info.absoluteFilePath());
        const char* filename = doc.getFileName();
        QString docPath(getFullPath(filename));

        if (path.isEmpty() || path != docPath) {
            FC_LOG("document '" << doc.getName() << "' path changed");
            auto me = shared_from_this();
            auto ret = _DocInfoMap.insert(std::make_pair(docPath, me));
            if (!ret.second) {
                // is that even possible?
                FC_WARN("document '" << doc.getName() << "' path exists, detach");
                slotDeleteDocument(doc);
                return;
            }
            _DocInfoMap.erase(myPos);
            myPos = ret.first;

            std::set<PropertyXLink*> tmp;
            tmp.swap(links);
            for (auto link : tmp) {
                auto owner = static_cast<DocumentObject*>(link->getContainer());
                // adjust file path for each PropertyXLink
                DocInfo::get(filename, owner->getDocument(), link, link->objectName.c_str());
            }
        }

        // time stamp changed, touch the linking document.
        std::set<Document*> docs;
        for (auto link : links) {
            auto linkdoc = static_cast<DocumentObject*>(link->getContainer())->getDocument();
            auto ret = docs.insert(linkdoc);
            if (ret.second) {
                // This will signal the Gui::Document to call setModified();
                FC_LOG("touch document " << linkdoc->getName() << " on time stamp change of "
                                         << link->getFullName());
                linkdoc->Comment.touch();
            }
        }
    }

    void slotDeleteDocument(const App::Document& doc)
    {
        for (auto it = links.begin(), itNext = it; it != links.end(); it = itNext) {
            ++itNext;
            auto link = *it;
            auto obj = freecad_cast<DocumentObject*>(link->getContainer());
            if (obj && obj->getDocument() == &doc) {
                links.erase(it);
                // must call unlink here, so that PropertyLink::resetLink can
                // remove back link before the owner object is marked as being
                // destroyed
                link->unlink();
            }
        }
        if (links.empty()) {
            deinit();
            return;
        }
        if (pcDoc != &doc) {
            return;
        }
        std::map<App::PropertyLinkBase*, std::vector<App::PropertyXLink*>> parentLinks;
        for (auto link : links) {
            link->setFlag(PropertyLinkBase::LinkDetached);
            if (link->parentProp) {
                parentLinks[link->parentProp].push_back(link);
            }
            else {
                parentLinks[nullptr].push_back(link);
            }
        }
        for (auto& v : parentLinks) {
            if (v.first) {
                v.first->setFlag(PropertyLinkBase::LinkDetached);
                v.first->aboutToSetValue();
            }
            for (auto l : v.second) {
                l->detach();
            }
            if (v.first) {
                v.first->hasSetValue();
                v.first->setFlag(PropertyLinkBase::LinkDetached, false);
            }
        }
        pcDoc = nullptr;
    }

    bool hasXLink(const App::Document* doc) const
    {
        for (auto link : links) {
            auto obj = freecad_cast<DocumentObject*>(link->getContainer());
            if (obj && obj->getDocument() == doc) {
                return true;
            }
        }
        return false;
    }

    static void breakLinks(App::DocumentObject* obj, bool clear)
    {
        auto doc = obj->getDocument();
        for (auto itD = _DocInfoMap.begin(), itDNext = itD; itD != _DocInfoMap.end();
             itD = itDNext) {
            ++itDNext;
            auto docInfo = itD->second;
            if (docInfo->pcDoc != doc) {
                continue;
            }
            auto& links = docInfo->links;
            std::set<PropertyLinkBase*> parentLinks;
            for (auto it = links.begin(), itNext = it; it != links.end(); it = itNext) {
                ++itNext;
                auto link = *it;
                if (link->_pcLink != obj && !(clear && link->getContainer() == obj)) {
                    continue;
                }
                if (link->parentProp) {
                    parentLinks.insert(link->parentProp);
                }
                else {
                    link->breakLink(obj, clear);
                }
            }
            for (auto link : parentLinks) {
                link->breakLink(obj, clear);
            }
        }
    }

    /// Whether \a doc holds element references into a document that isn't open (ops#116)
    static bool holdsDetachedReferences(const Document* doc)
    {
        for (const auto& [path, info] : _DocInfoMap) {
            if (info->pcDoc) {
                continue;
            }
            for (auto link : info->links) {
                auto owner = freecad_cast<DocumentObject*>(link->getContainer());
                if (!owner || owner->getDocument() != doc) {
                    continue;
                }
                for (const auto& sub : link->_SubList) {
                    const char* element = Data::findElementName(sub.c_str());
                    if (element && element[0]) {
                        return true;
                    }
                }
            }
        }
        // References through a Link whose path doesn't resolve: their target isn't open either
        // (ops#120)
        return std::any_of(_LostElementRefs.begin(),
                           _LostElementRefs.end(),
                           [doc](const PropertyLinkBase* prop) {
                               auto owner = freecad_cast<DocumentObject*>(prop->getContainer());
                               return owner && owner->getDocument() == doc;
                           });
    }

    /// Drops \a feature from _ElementRefMap and from its properties' own lists (ops#119)
    static void forgetFeature(const DocumentObject* feature)
    {
        auto it = _ElementRefMap.find(const_cast<DocumentObject*>(feature));
        if (it == _ElementRefMap.end()) {
            return;
        }
        for (auto prop : it->second) {
            prop->_ElementRefs.erase(it->first);
            _LostElementRefs.insert(prop);
        }
        _ElementRefMap.erase(it);
    }

    /// Registers the references of the properties in _LostElementRefs again (ops#120), so that a
    /// reference through an App::Link follows its target's elements once the target's document
    /// is back. Each property leaves the set first; a sub whose path still doesn't resolve puts
    /// it back. The references registered again are then resolved as restoreLink() does for an
    /// XLink's own, and their owners touched if they moved: at once outside a restore (a
    /// document saved to the target's path), else after it (_ResolveAfterRestore: the end of an
    /// open, or Document::restore() for File > Revert).
    static void registerLostReferences()
    {
        const std::vector<PropertyLinkBase*> lost(_LostElementRefs.begin(), _LostElementRefs.end());
        _LostElementRefs.clear();
        const bool restoring = App::GetApplication().isRestoring();
        for (auto prop : lost) {
            auto owner = freecad_cast<DocumentObject*>(prop->getContainer());
            if (!owner || !owner->isAttachedToDocument()) {
                // Removed for undo, or not yet in a document: try again at the next attach
                _LostElementRefs.insert(prop);
                continue;
            }
            std::vector<DocumentObject*> objs;
            std::vector<std::string> subs;
            std::vector<PropertyLinkBase::ShadowSub> shadows;
            auto xlink = dynamic_cast<PropertyXLink*>(prop);
            if (xlink) {
                subs = xlink->getSubValues();
                shadows = xlink->getShadowSubs();
                objs.assign(subs.size(), xlink->getValue());
            }
            else if (auto link = dynamic_cast<PropertyLinkSub*>(prop)) {
                subs = link->getSubValues();
                shadows = link->getShadowSubs();
                objs.assign(subs.size(), link->getValue());
            }
            else if (auto list = dynamic_cast<PropertyLinkSubList*>(prop)) {
                objs = list->getValues();
                subs = list->getSubValues();
                shadows = list->getShadowSubs();
            }
            const auto count = std::min({objs.size(), subs.size(), shadows.size()});
            for (std::size_t i = 0; i < count; ++i) {
                prop->_registerElementReference(objs[i], subs[i], shadows[i]);
            }
            if (prop->_ElementRefs.empty()) {
                continue;
            }
            if (restoring) {
                _ResolveAfterRestore.insert(prop);
                // As restoreLink(): in an open, an older document opened before it takes the
                // consumer pass for these references at its end (ops#116)
                auto doc = owner->getDocument();
                if (!doc->testStatus(Document::Restoring)
                    && App::namingRevisionOf(doc) < App::forkNamingRevision()) {
                    _ConsumerPassLinks.insert(prop);
                }
            }
            else {
                resolveRegistered(prop);
            }
        }
        if (!restoring) {
            App::reportReferenceMigration();
        }
    }

    /// Resolves \a prop's registered references and touches its owner if one moved (ops#120)
    static void resolveRegistered(PropertyLinkBase* prop)
    {
        auto owner = freecad_cast<DocumentObject*>(prop->getContainer());
        if (!owner || !owner->isAttachedToDocument()) {
            return;
        }
        try {
            if (updateRegisteredReferences(prop)) {
                owner->touch();
            }
        }
        catch (Base::Exception& e) {
            e.reportException();
            FC_ERR("Failed to update element reference of " << propertyName(prop));
        }
    }

    /// Resolves \a prop's registered references without notifying, through the reference
    /// solver in a solver document (updateElementReferences() above leaves a missing reference
    /// there to a solve that doesn't come outside an open). Returns whether a sub changed.
    static bool updateRegisteredReferences(PropertyLinkBase* prop)
    {
        const auto before = referenceState(prop);
        std::vector<DocumentObject*> features(prop->_ElementRefs.begin(), prop->_ElementRefs.end());
        bool passed = false;
        for (auto feature : features) {
            const bool reverse = takesConsumerPass(prop, feature, false);
            passed = passed || reverse;
            std::optional<ConsumerPassScope> scope;
            if (reverse) {
                scope.emplace();
            }
            if (prop->inSolverDocument()) {
                App::solveElementReferences(feature, {prop}, reverse, false);
            }
            else {
                prop->updateElementReference(feature, reverse, false);
            }
        }
        if (passed) {
            _PassedRefs.insert(prop);
        }
        return referenceState(prop) != before;
    }
};

void App::forgetElementReferencesTo(const DocumentObject* feature)
{
    DocInfo::forgetFeature(feature);
}

void App::resolveReregisteredReferences()
{
    std::vector<PropertyLinkBase*> props(_ResolveAfterRestore.begin(), _ResolveAfterRestore.end());
    _ResolveAfterRestore.clear();
    for (auto prop : props) {
        // Resolved here, with the consumer pass if its document is older: not again at an
        // unrelated later open
        _ConsumerPassLinks.erase(prop);
        DocInfo::resolveRegistered(prop);
    }
    // A consumer pass among them (an older document's references) reports as at an open
    App::reportReferenceMigration();
}

int App::namingRevisionToSave(const Document* doc)
{
    // A producer not yet migrated (the recompute declined) holds the names of its file's
    // revision, and so do this document's references into it; a reference into a document that
    // isn't open holds this document's own.
    int revision = App::forkNamingRevision();
    // A removed feature kept for undo stays registered; destroyed ones leave the map (ops#119).
    for (const auto& [feature, props] : _ElementRefMap) {
        if (!feature->isAttachedToDocument() || feature->getDocument() == doc) {
            continue;
        }
        const bool held = std::any_of(props.begin(), props.end(), [doc](PropertyLinkBase* prop) {
            auto owner = freecad_cast<DocumentObject*>(prop->getContainer());
            return owner && owner->getDocument() == doc;
        });
        const int producer = held ? producerNamingRevision(feature) : -1;
        if (producer >= 0) {
            revision = std::min(revision, producer);
        }
    }
    if (DocInfo::holdsDetachedReferences(doc)) {
        revision = std::min(revision, App::namingRevisionOf(doc));
    }
    return revision;
}

void PropertyLinkBase::breakLinks(App::DocumentObject* link,
                                  const std::vector<App::DocumentObject*>& objs,
                                  bool clear)
{
    std::vector<Property*> props;
    for (auto obj : objs) {
        props.clear();
        obj->getPropertyList(props);
        for (auto prop : props) {
            auto linkProp = freecad_cast<PropertyLinkBase*>(prop);
            if (linkProp) {
                linkProp->breakLink(link, clear);
            }
        }
    }
    DocInfo::breakLinks(link, clear);
}

void App::followLinkRetarget(App::DocumentObject* link, App::DocumentObject* oldTarget)
{
    if (!link || !link->isAttachedToDocument() || link->isRestoring()
        || link->getDocument()->isPerformingTransaction()) {
        return;
    }
    // A reference through the link is held by an object that depends on it, directly (a joint
    // on the link) or through a container (a subname path through an assembly).
    std::vector<Property*> props;
    std::vector<RetargetCheck> checks;
    for (auto obj : link->getInListEx(true)) {
        if (!obj || !obj->isAttachedToDocument() || obj->isRestoring()) {
            continue;
        }
        props.clear();
        obj->getPropertyList(props);
        for (auto prop : props) {
            if (prop->getContainer() != obj) {
                continue;
            }
            bool changed = false;
            if (auto linkSub = freecad_cast<PropertyLinkSub*>(prop)) {
                auto shadows = linkSub->getShadowSubs();
                if (!retargetShadows(link,
                                     oldTarget,
                                     linkSub->getValue(),
                                     nullptr,
                                     linkSub->getSubValues(),
                                     shadows,
                                     changed,
                                     checks)) {
                    continue;
                }
                holdRetargetChecks(linkSub, checks);
                if (changed) {
                    linkSub->setValue(linkSub->getValue(),
                                      linkSub->getSubValues(),
                                      std::move(shadows));
                }
                else {
                    linkSub->onContainerRestored();  // registers under the new target
                }
            }
            else if (auto linkSubList = freecad_cast<PropertyLinkSubList*>(prop)) {
                auto shadows = linkSubList->getShadowSubs();
                if (!retargetShadows(link,
                                     oldTarget,
                                     nullptr,
                                     &linkSubList->getValues(),
                                     linkSubList->getSubValues(),
                                     shadows,
                                     changed,
                                     checks)) {
                    continue;
                }
                holdRetargetChecks(linkSubList, checks);
                if (changed) {
                    linkSubList->setValues(linkSubList->getValues(),
                                           linkSubList->getSubValues(),
                                           std::move(shadows));
                }
                else {
                    linkSubList->onContainerRestored();
                }
            }
            else if (auto xlink = freecad_cast<PropertyXLink*>(prop)) {
                DocInfo::followRetarget(xlink, link, oldTarget);
            }
            else if (auto xlinkSubList = freecad_cast<PropertyXLinkSubList*>(prop)) {
                // Each child notifies through the list.
                for (auto& child : xlinkSubList->getSubListValues()) {
                    DocInfo::followRetarget(const_cast<PropertyXLinkSub*>(&child), link, oldTarget);
                }
            }
        }
    }
}

//**************************************************************************
// PropertyXLink
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyXLink, App::PropertyLink)

PropertyXLink::PropertyXLink(bool _allowPartial, PropertyLinkBase* parent)
    : parentProp(parent)
{
    setAllowPartial(_allowPartial);
    setAllowExternal(true);
    setSyncSubObject(true);
    if (parent) {
        setContainer(parent->getContainer());
    }
}

PropertyXLink::~PropertyXLink()
{
    try {
        unlink();
    } catch (std::bad_weak_ptr &) {
        FC_WARN("Bad pointer exception caught when destroying PropertyXLink\n");
    }
}

void PropertyXLink::setSyncSubObject(bool enable)
{
    _Flags.set((std::size_t)LinkSyncSubObject, enable);
}

void PropertyXLink::unlink()
{
    if (docInfo) {
        docInfo->remove(this);
        docInfo.reset();
    }
    objectName.clear();
    resetLink();
}

void PropertyXLink::detach()
{
    if (docInfo && _pcLink) {
        aboutToSetValue();
        resetLink();
        // Keep the shadows: the sub-elements haven't changed, only the target document is
        // closed. Save writes them, and restoreLink() resolves them once it is open again. The
        // registrations go, as they hold the target's objects, which are about to be deleted.
        unregisterElementReference();
        hasSetValue();
    }
}

void PropertyXLink::aboutToSetValue()
{
    if (parentProp) {
        parentProp->aboutToSetChildValue(*this);
    }
    else {
        PropertyLinkBase::aboutToSetValue();
    }
}

void PropertyXLink::hasSetValue()
{
    if (parentProp) {
        parentProp->hasSetChildValue(*this);
    }
    else {
        PropertyLinkBase::hasSetValue();
    }
}

void PropertyXLink::setSubName(const char* subname)
{
    std::vector<std::string> subs;
    if (!Base::Tools::isNullOrEmpty(subname)) {
        subs.emplace_back(subname);
    }
    aboutToSetValue();
    setSubValues(std::move(subs));
    hasSetValue();
}

void PropertyXLink::setSubValues(std::vector<std::string>&& subs, std::vector<ShadowSub>&& shadows)
{
    // A guess record (ops#127) stays with a reference passed on with its shadow.
    if (shadows.size() != subs.size() || _Guesses.size() != subs.size()) {
        _Guesses.assign(subs.size(), GuessRecord());
    }
    else {
        for (std::size_t i = 0; i < subs.size(); ++i) {
            if (shadows[i].oldName.empty() && shadows[i].newName.empty()) {
                _Guesses[i] = GuessRecord();
            }
        }
    }
    // The reorder's re-target records (ops#127) stay with references passed on with their shadows
    keepRetargetRecords(_Retargets, subs.size(), shadows);
    _SubList = std::move(subs);
    _ShadowSubList.clear();
    if (shadows.size() == _SubList.size()) {
        _ShadowSubList = std::move(shadows);
        onContainerRestored();  // re-register element references
    }
    else {
        updateElementReference(nullptr);
    }
    checkLabelReferences(_SubList);
}

void PropertyXLink::setValue(App::DocumentObject* lValue)
{
    setValue(lValue, nullptr);
}

void PropertyXLink::setValue(App::DocumentObject* lValue, const char* subname)
{
    std::vector<std::string> subs;
    if (!Base::Tools::isNullOrEmpty(subname)) {
        subs.emplace_back(subname);
    }
    setValue(lValue, std::move(subs));
}

void PropertyXLink::restoreLink(App::DocumentObject* lValue)
{
    assert(!_pcLink && lValue && docInfo);

    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (!owner || !owner->isAttachedToDocument()) {
        throw Base::RuntimeError("invalid container");
    }

    bool touched = owner->isTouched();
    setFlag(LinkDetached, false);
    setFlag(LinkRestoring);
    aboutToSetValue();

    if (!owner->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
        lValue->_addBackLink(owner);
        lValue->_addBackLinkProp(getName(), owner);
    }

    _pcLink = lValue;
    // Keep the shadows restored from the file or kept by detach(): they find the elements again
    // if the target has changed since. A sub without a shadow gets one from its index.
    _ShadowSubList.resize(_SubList.size());
    unregisterElementReference();
    onContainerRestored();
    // Without a refresh after opening documents to follow (a document was saved to the target's
    // path), resolve the shadows now. Within one, an older document opened before it takes the
    // consumer pass for this link at its end (ops#116).
    bool restoring = App::GetApplication().isRestoring();
    if (restoring && !owner->getDocument()->testStatus(Document::Restoring)
        && App::namingRevisionOf(owner->getDocument()) < App::forkNamingRevision()) {
        _ConsumerPassLinks.insert(this);
    }
    bool moved = !restoring && DocInfo::updateElementReferences(this);
    if (restoring) {
        // isRestoring() holds during a restore outside an open too (File > Revert of the
        // target), where no end-of-open update follows: Document::restore() resolves it (ops#120)
        _ResolveAfterRestore.insert(this);
    }
    hasSetValue();
    setFlag(LinkRestoring, false);

    if (!moved && !touched && owner->isTouched() && docInfo && docInfo->pcDoc
        && stamp == docInfo->pcDoc->LastModifiedDate.getValue()) {
        owner->purgeTouched();
    }
}

void PropertyXLink::setValue(App::DocumentObject* lValue,
                             std::vector<std::string>&& subs,
                             std::vector<ShadowSub>&& shadows)
{
    if (_pcLink == lValue && _SubList == subs) {
        return;
    }

    if (lValue && (!lValue->isAttachedToDocument() || !lValue->getDocument())) {
        throw Base::ValueError("Invalid object");
    }

    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (!owner || !owner->isAttachedToDocument()) {
        throw Base::RuntimeError("invalid container");
    }

    if (lValue == owner) {
        throw Base::ValueError("self linking");
    }

    aboutToSetValue();

    DocInfoPtr info;
    const char* name = "";
    if (lValue) {
        name = lValue->getNameInDocument();
        if (lValue->getDocument() != owner->getDocument()) {
            if (!docInfo || lValue->getDocument() != docInfo->pcDoc) {
                const char* filename = lValue->getDocument()->getFileName();
                if (!filename || *filename == 0) {
                    throw Base::RuntimeError("Linked document not saved");
                }
                FC_LOG("xlink set to new document " << lValue->getDocument()->getName());
                info = DocInfo::get(filename, owner->getDocument(), this, name);
                assert(info && info->pcDoc == lValue->getDocument());
            }
            else {
                info = docInfo;
            }
        }
    }

    setFlag(LinkDetached, false);

    if (!owner->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
        if (_pcLink) {
            _pcLink->_removeBackLink(owner);
            _pcLink->_removeBackLinkProp(getName(), owner);
        }
        if (lValue) {
            lValue->_addBackLink(owner);
            lValue->_addBackLinkProp(getName(), owner);
        }
    }

    if (docInfo != info) {
        unlink();
        docInfo = info;
    }
    if (!docInfo) {
        filePath.clear();
    }
    _pcLink = lValue;
    if (docInfo && docInfo->pcDoc) {
        stamp = docInfo->pcDoc->LastModifiedDate.getValue();
    }
    objectName = name;
    setSubValues(std::move(subs), std::move(shadows));
    hasSetValue();
}

void PropertyXLink::setValue(std::string&& filename,
                             std::string&& name,
                             std::vector<std::string>&& subs,
                             std::vector<ShadowSub>&& shadows)
{
    if (name.empty()) {
        setValue(nullptr, std::move(subs), std::move(shadows));
        return;
    }
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (!owner || !owner->isAttachedToDocument()) {
        throw Base::RuntimeError("invalid container");
    }

    DocumentObject* pObject = nullptr;
    DocInfoPtr info;
    if (!filename.empty()) {
        owner->getDocument()->signalLinkXsetValue(filename);
        info = DocInfo::get(filename.c_str(), owner->getDocument(), this, name.c_str());
        if (info->pcDoc) {
            pObject = info->pcDoc->getObject(name.c_str());
        }
    }
    else {
        pObject = owner->getDocument()->getObject(name.c_str());
    }

    if (pObject) {
        setValue(pObject, std::move(subs), std::move(shadows));
        return;
    }
    setFlag(LinkDetached, false);
    aboutToSetValue();

    if (_pcLink && !owner->testStatus(ObjectStatus::Destroy) && _pcScope != LinkScope::Hidden) {
        _pcLink->_removeBackLink(owner);
        _pcLink->_removeBackLinkProp(getName(), owner);
    }

    _pcLink = nullptr;
    if (docInfo != info) {
        unlink();
        docInfo = info;
    }
    if (!docInfo) {
        filePath.clear();
    }
    if (docInfo && docInfo->pcDoc) {
        stamp = docInfo->pcDoc->LastModifiedDate.getValue();
    }
    objectName = std::move(name);
    setSubValues(std::move(subs), std::move(shadows));
    hasSetValue();
}

void PropertyXLink::setValue(App::DocumentObject* link,
                             const std::vector<std::string>& subs,
                             std::vector<ShadowSub>&& shadows)
{
    setValue(link, std::vector<std::string>(subs), std::move(shadows));
}

App::Document* PropertyXLink::getDocument() const
{
    return docInfo ? docInfo->pcDoc : nullptr;
}

const char* PropertyXLink::getDocumentPath() const
{
    return docInfo ? docInfo->filePath() : filePath.c_str();
}

const char* PropertyXLink::getObjectName() const
{
    return objectName.c_str();
}

bool PropertyXLink::upgrade(Base::XMLReader& reader, const char* typeName)
{
    if (typeName == App::PropertyLinkGlobal::getClassTypeId().getName()
        || typeName == App::PropertyLink::getClassTypeId().getName()
        || typeName == App::PropertyLinkChild::getClassTypeId().getName()) {
        PropertyLink::Restore(reader);
        return true;
    }
    FC_ERR("Cannot upgrade from " << typeName);
    return false;
}

int PropertyXLink::checkRestore(std::string* msg) const
{
    if (!docInfo) {
        if (!_pcLink && !objectName.empty()) {
            // this condition means linked object not found
            if (msg) {
                std::ostringstream ss;
                ss << "Link not restored" << std::endl;
                ss << "Object: " << objectName;
                if (!filePath.empty()) {
                    ss << std::endl << "File: " << filePath;
                }
                *msg = ss.str();
            }
            return 2;
        }
        return 0;
    }
    if (!_pcLink) {
        if (testFlag(LinkSilentRestore)) {
            return 0;
        }
        if (testFlag(LinkAllowPartial)
            && (!docInfo->pcDoc || docInfo->pcDoc->testStatus(App::Document::PartialDoc))) {
            return 0;
        }
        if (msg) {
            std::ostringstream ss;
            ss << "Link not restored" << std::endl;
            ss << "Linked object: " << objectName;
            if (docInfo->pcDoc) {
                ss << std::endl << "Linked document: " << docInfo->pcDoc->Label.getValue();
            }
            else if (!filePath.empty()) {
                ss << std::endl << "Linked file: " << filePath;
            }
            *msg = ss.str();
        }
        return 2;
    }
    if (!docInfo->pcDoc || stamp == docInfo->pcDoc->LastModifiedDate.getValue()) {
        return 0;
    }

    if (msg) {
        std::ostringstream ss;
        ss << "Time stamp changed on link " << _pcLink->getFullName();
        *msg = ss.str();
    }
    return 1;
}

void PropertyXLink::afterRestore()
{
    assert(_SubList.size() == _ShadowSubList.size());
    if (!testFlag(LinkRestoreLabel) || !_pcLink || !_pcLink->isAttachedToDocument()) {
        return;
    }

    setFlag(LinkRestoreLabel, false);
    for (size_t i = 0; i < _SubList.size(); ++i) {
        restoreLabelReference(_pcLink, _SubList[i], &_ShadowSubList[i]);
    }
}

void PropertyXLink::onContainerRestored()
{
    // It doesn't unregister first, so drop the solver's report here (ops#7).
    ReferenceReport::clear(this);
    holdRestoredRetargetChecks(this, _pcLink, nullptr, _SubList);
    if (!_pcLink || !_pcLink->isAttachedToDocument()) {
        return;
    }
    for (size_t i = 0; i < _SubList.size(); ++i) {
        _registerElementReference(_pcLink, _SubList[i], _ShadowSubList[i]);
    }
    _updateElementFingerprints(nullptr, _pcLink, nullptr, _SubList, _ShadowSubList, _Fingerprints);
}

void PropertyXLink::updateElementReference(DocumentObject* feature, bool reverse, bool notify)
{
    if (!feature) {
        _Guesses.clear();  // the shadows go too: a sub set anew (ops#127)
    }
    bool changed = updateLinkReference(this,
                                       feature,
                                       reverse,
                                       notify,
                                       _pcLink,
                                       _SubList,
                                       _mapped,
                                       _ShadowSubList);
    _updateElementFingerprints(feature, _pcLink, nullptr, _SubList, _ShadowSubList, _Fingerprints);
    if (!changed) {
        return;
    }
    if (notify) {
        hasSetValue();
    }
}

bool PropertyXLink::updateElementFingerprints()
{
    return _updateElementFingerprints(nullptr,
                                      _pcLink,
                                      nullptr,
                                      _SubList,
                                      _ShadowSubList,
                                      _Fingerprints);
}

// The reference solver's passes (ops#7).
void PropertyXLink::collectElementReferences(App::DocumentObject* feature, SolverBatch& batch)
{
    collectLinkReferences(this,
                          feature,
                          batch,
                          _pcLink,
                          nullptr,
                          _SubList,
                          _ShadowSubList,
                          _Fingerprints,
                          nullptr,
                          &_Guesses);
}

void PropertyXLink::applyResolutions(const std::vector<SolverResolution>& resolutions)
{
    if (resolutions.empty()) {
        return;
    }
    const auto& context = resolutions.front();
    // A PropertyXLinkSubList's link forwards these to its list.
    bool changed = writeLinkResolutions(resolutions,
                                        _SubList,
                                        _ShadowSubList,
                                        _Fingerprints,
                                        _Guesses,
                                        [this]() { aboutToSetValue(); });
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (changed) {
        // As updateLinkReference() does.
        for (int idx : _mapped) {
            if (idx < (int)_SubList.size() && !_ShadowSubList[idx].newName.empty()) {
                _SubList[idx] = _ShadowSubList[idx].newName;
            }
        }
        _mapped.clear();
        if (owner && context.feature) {
            owner->onUpdateElementReference(this);
        }
    }
    _updateElementFingerprints(context.feature,
                               _pcLink,
                               nullptr,
                               _SubList,
                               _ShadowSubList,
                               _Fingerprints);
    if (changed && context.notify) {
        hasSetValue();
    }
}

std::vector<std::string> PropertyXLink::getElementFingerprints() const
{
    auto fingerprints = _Fingerprints;
    fingerprints.resize(_SubList.size());
    return fingerprints;
}

std::vector<GuessRecord> PropertyXLink::getElementGuesses() const
{
    auto guesses = _Guesses;
    guesses.resize(_SubList.size());
    return guesses;
}

bool PropertyXLink::referenceChanged() const
{
    return !_mapped.empty();
}

void PropertyXLink::Save(Base::Writer& writer) const
{
    auto owner = dynamic_cast<const DocumentObject*>(getContainer());
    if (!owner || !owner->getDocument()) {
        return;
    }

    assert(_SubList.size() == _ShadowSubList.size());

    auto exporting = owner->isExporting();
    if (_pcLink && exporting && _pcLink->isExporting()) {
        // this means, we are exporting the owner and the linked object together.
        // Lets save the export name
        writer.Stream() << writer.ind() << "<XLink name=\"" << _pcLink->getExportName();
    }
    else {
        const char* path = filePath.c_str();
        std::string _path;
        if (exporting) {
            // Here means we are exporting the owner but not exporting the
            // linked object.  Try to use absolute file path for easy transition
            // into document at different directory
            if (docInfo) {
                _path = docInfo->filePath();
            }
            else {
                auto pDoc = owner->getDocument();
                const char* docPath = pDoc->getFileName();
                if (!Base::Tools::isNullOrEmpty(docPath)) {
                    if (!filePath.empty()) {
                        _path = DocInfo::getDocPath(filePath.c_str(), pDoc, false);
                    }
                    else {
                        _path = docPath;
                    }
                }
                else {
                    FC_WARN("PropertyXLink export without saving the document");
                }
            }
            if (!_path.empty()) {
                path = _path.c_str();
            }
        }
        writer.Stream() << writer.ind() << "<XLink file=\"" << encodeAttribute(path)
                        << "\" stamp=\""
                        << (docInfo && docInfo->pcDoc ? docInfo->pcDoc->LastModifiedDate.getValue()
                                                      : "")
                        << "\" name=\"" << objectName;
    }

    if (testFlag(LinkAllowPartial)) {
        writer.Stream() << "\" partial=\"1";
    }

    const bool saveFingerprints = inSolverDocument();
    auto writeFingerprint = [&](std::size_t i) {
        if (saveFingerprints && i < _Fingerprints.size() && !_Fingerprints[i].empty()) {
            writer.Stream() << "\" " ATTR_FINGERPRINT "=\"" << encodeAttribute(_Fingerprints[i]);
        }
        if (saveFingerprints) {
            writeGuessRecord(writer, _Guesses, i);
        }
        writeRetargetRecord(writer, _Retargets, i);
        writeRetargetCheck(writer, this, _pcLink, _SubList[i], _ShadowSubList[i]);
    };
    if (_SubList.empty()) {
        writer.Stream() << "\"/>" << std::endl;
    }
    else if (_SubList.size() == 1) {
        const auto& subName = _SubList[0];
        const auto& shadowSub = _ShadowSubList[0];
        const auto& sub = shadowSub.oldName.empty() ? subName : shadowSub.oldName;
        if (exporting) {
            std::string exportName;
            writer.Stream() << "\" sub=\""
                            << encodeAttribute(exportSubName(exportName, _pcLink, sub.c_str()));
            if (!shadowSub.oldName.empty() && shadowSub.newName == subName) {
                writer.Stream() << "\" " ATTR_MAPPED "=\"1";
            }
        }
        else {
            writer.Stream() << "\" sub=\"" << encodeAttribute(sub);
            if (!sub.empty()) {
                if (sub != subName) {
                    writer.Stream() << "\" " ATTR_SHADOWED "=\"" << encodeAttribute(subName);
                }
                else if (!shadowSub.newName.empty()) {
                    writer.Stream()
                        << "\" " ATTR_SHADOW "=\"" << encodeAttribute(shadowSub.newName);
                }
            }
        }
        writeFingerprint(0);
        writer.Stream() << "\"/>" << std::endl;
    }
    else {
        writer.Stream() << "\" count=\"" << _SubList.size() << "\">" << std::endl;
        writer.incInd();
        for (unsigned int i = 0; i < _SubList.size(); i++) {
            const auto& shadow = _ShadowSubList[i];
            // shadow.oldName stores the old style element name. For backward
            // compatibility reason, we shall store the old name into attribute
            // 'value' whenever possible.
            const auto& sub = shadow.oldName.empty() ? _SubList[i] : shadow.oldName;
            writer.Stream() << writer.ind() << "<Sub value=\"";
            if (exporting) {
                std::string exportName;
                writer.Stream() << encodeAttribute(exportSubName(exportName, _pcLink, sub.c_str()));
                if (!shadow.oldName.empty() && shadow.newName == _SubList[i]) {
                    writer.Stream() << "\" " ATTR_MAPPED "=\"1";
                }
            }
            else {
                writer.Stream() << encodeAttribute(sub);
                if (!_SubList[i].empty()) {
                    if (sub != _SubList[i]) {
                        writer.Stream()
                            << "\" " ATTR_SHADOWED "=\"" << encodeAttribute(_SubList[i]);
                    }
                    else if (!shadow.newName.empty()) {
                        writer.Stream()
                            << "\" " ATTR_SHADOW "=\"" << encodeAttribute(shadow.newName);
                    }
                }
            }
            writeFingerprint(i);
            writer.Stream() << "\"/>" << endl;
        }
        writer.decInd();
        writer.Stream() << writer.ind() << "</XLink>" << endl;
    }
}

void PropertyXLink::Restore(Base::XMLReader& reader)
{
    // read my element
    reader.readElement("XLink");
    std::string stampAttr, file;
    if (reader.hasAttribute("stamp")) {
        stampAttr = reader.getAttribute<const char*>("stamp");
    }
    if (reader.hasAttribute("file")) {
        file = reader.getAttribute<const char*>("file");
    }

    setFlag(LinkAllowPartial,
            reader.hasAttribute("partial") && reader.getAttribute<bool>("partial"));
    std::string name;
    if (file.empty()) {
        name = reader.getName(reader.getAttribute<const char*>("name"));
    }
    else {
        name = reader.getAttribute<const char*>("name");
    }

    DocumentObject* object = nullptr;
    if (!name.empty() && file.empty()) {
        if (auto parent = freecad_cast<DocumentObject*>(getContainer())) {
            Document* document = parent->getDocument();
            object = document ? document->getObject(name.c_str()) : nullptr;
            if (!object && reader.isVerbose()) {
                FC_WARN("Lost link to '" << name
                                         << "' while loading, maybe "
                                            "an object was not loaded correctly");
            }
        }
    }

    std::vector<std::string> subs;
    std::vector<ShadowSub> shadows;
    std::vector<std::string> fingerprints;
    std::vector<GuessRecord> guesses;
    std::vector<RetargetRecord> retargets;
    std::vector<int> mapped;
    std::vector<std::pair<std::size_t, Data::ElementFingerprint>> checks;
    bool restoreLabel = false;
    if (reader.hasAttribute("sub")) {
        if (reader.hasAttribute(ATTR_MAPPED)) {
            mapped.push_back(0);
        }
        readRetargetCheck(reader, 0, checks);
        retargets.push_back(readRetargetRecord(reader));
        subs.emplace_back();
        auto& subname = subs.back();
        shadows.emplace_back();
        fingerprints.emplace_back(reader.hasAttribute(ATTR_FINGERPRINT)
                                      ? reader.getAttribute<const char*>(ATTR_FINGERPRINT)
                                      : "");
        guesses.push_back(readGuessRecord(reader));
        auto& shadow = shadows.back();
        shadow.oldName = importSubName(reader, reader.getAttribute<const char*>("sub"), restoreLabel);
        if (reader.hasAttribute(ATTR_SHADOWED) && !IGNORE_SHADOW) {
            subname = shadow.newName =
                importSubName(reader, reader.getAttribute<const char*>(ATTR_SHADOWED), restoreLabel);
        }
        else {
            subname = shadow.oldName;
            if (reader.hasAttribute(ATTR_SHADOW) && !IGNORE_SHADOW) {
                shadow.newName =
                    importSubName(reader, reader.getAttribute<const char*>(ATTR_SHADOW), restoreLabel);
            }
        }
    }
    else if (reader.hasAttribute("count")) {
        int count = reader.getAttribute<long>("count");
        subs.resize(count);
        shadows.resize(count);
        fingerprints.resize(count);
        guesses.resize(count);
        retargets.resize(count);
        for (int i = 0; i < count; i++) {
            reader.readElement("Sub");
            if (reader.hasAttribute(ATTR_FINGERPRINT)) {
                fingerprints[i] = reader.getAttribute<const char*>(ATTR_FINGERPRINT);
            }
            guesses[i] = readGuessRecord(reader);
            retargets[i] = readRetargetRecord(reader);
            readRetargetCheck(reader, i, checks);
            shadows[i].oldName = importSubName(reader, reader.getAttribute<const char*>("value"), restoreLabel);
            if (reader.hasAttribute(ATTR_SHADOWED) && !IGNORE_SHADOW) {
                subs[i] = shadows[i].newName =
                    importSubName(reader, reader.getAttribute<const char*>(ATTR_SHADOWED), restoreLabel);
            }
            else {
                subs[i] = shadows[i].oldName;
                if (reader.hasAttribute(ATTR_SHADOW) && !IGNORE_SHADOW) {
                    shadows[i].newName =
                        importSubName(reader, reader.getAttribute<const char*>(ATTR_SHADOW), restoreLabel);
                }
            }
            if (reader.hasAttribute(ATTR_MAPPED)) {
                mapped.push_back(i);
            }
        }
        reader.readEndElement("XLink");
    }
    setFlag(LinkRestoreLabel, restoreLabel);
    keepRestoredRetargetChecks(this, std::move(checks));

    if (name.empty()) {
        setValue(nullptr);
        return;
    }

    if (!file.empty() || (!object && !name.empty())) {
        this->stamp = stampAttr;
        setValue(std::move(file), std::move(name), std::move(subs), std::move(shadows));
    }
    else {
        setValue(object, std::move(subs), std::move(shadows));
    }
    _mapped = std::move(mapped);
    if (fingerprints.size() == _SubList.size()) {
        _Fingerprints = std::move(fingerprints);
    }
    if (guesses.size() == _SubList.size()) {
        _Guesses = std::move(guesses);
    }
    if (retargets.size() == _SubList.size()) {
        _Retargets = std::move(retargets);
    }
}

Property*
PropertyXLink::CopyOnImportExternal(const std::map<std::string, std::string>& nameMap) const
{
    auto owner = freecad_cast<const DocumentObject*>(getContainer());
    if (!owner || !owner->getDocument() || !_pcLink || !_pcLink->isAttachedToDocument()) {
        return nullptr;
    }

    auto subs = updateLinkSubs(_pcLink, _SubList, &tryImportSubName, owner->getDocument(), nameMap);
    auto linked = tryImport(owner->getDocument(), _pcLink, nameMap);
    if (subs.empty() && linked == _pcLink) {
        return nullptr;
    }

    std::unique_ptr<PropertyXLink> p(new PropertyXLink);
    copyTo(*p, linked, &subs);
    return p.release();
}

Property* PropertyXLink::CopyOnLinkReplace(const App::DocumentObject* parent,
                                           App::DocumentObject* oldObj,
                                           App::DocumentObject* newObj) const
{
    auto res = tryReplaceLinkSubs(getContainer(), _pcLink, parent, oldObj, newObj, _SubList);
    if (!res.first) {
        return nullptr;
    }
    std::unique_ptr<PropertyXLink> p(new PropertyXLink);
    copyTo(*p, res.first, &res.second);
    return p.release();
}

Property* PropertyXLink::CopyOnLabelChange(App::DocumentObject* obj,
                                           const std::string& ref,
                                           const char* newLabel) const
{
    auto owner = dynamic_cast<const DocumentObject*>(getContainer());
    if (!owner || !owner->getDocument() || !_pcLink || !_pcLink->isAttachedToDocument()) {
        return nullptr;
    }
    auto subs = updateLinkSubs(_pcLink, _SubList, &updateLabelReference, obj, ref, newLabel);
    if (subs.empty()) {
        return nullptr;
    }
    std::unique_ptr<PropertyXLink> p(new PropertyXLink);
    copyTo(*p, _pcLink, &subs);
    return p.release();
}

void PropertyXLink::copyTo(PropertyXLink& other,
                           DocumentObject* linked,
                           std::vector<std::string>* subs) const
{
    if (!linked) {
        linked = _pcLink;
    }
    if (linked && linked->isAttachedToDocument()) {
        other.docName = linked->getDocument()->getName();
        other.objectName = linked->getNameInDocument();
        other.docInfo.reset();
        other.filePath.clear();
    }
    else {
        other.objectName = objectName;
        other.docName.clear();
        other.docInfo = docInfo;
        other.filePath = filePath;
    }
    if (subs) {
        other._SubList = std::move(*subs);
    }
    else {
        other._SubList = _SubList;
        other._ShadowSubList = _ShadowSubList;
        other._Fingerprints = _Fingerprints;
        other._Guesses = _Guesses;
        other._Retargets = _Retargets;
    }
    other._Flags = _Flags;
}

Property* PropertyXLink::Copy() const
{
    std::unique_ptr<PropertyXLink> p(new PropertyXLink);
    copyTo(*p);
    return p.release();
}

void PropertyXLink::Paste(const Property& from)
{
    if (!from.isDerivedFrom<PropertyXLink>()) {
        throw Base::TypeError("Incompatible property to paste to");
    }

    const auto& other = static_cast<const PropertyXLink&>(from);
    if (!other.docName.empty()) {
        auto doc = GetApplication().getDocument(other.docName.c_str());
        if (!doc) {
            FC_WARN("Document '" << other.docName << "' not found");
            return;
        }
        auto obj = doc->getObject(other.objectName.c_str());
        if (!obj) {
            FC_WARN("Object '" << other.docName << '#' << other.objectName << "' not found");
            return;
        }
        setValue(obj,
                 std::vector<std::string>(other._SubList),
                 std::vector<ShadowSub>(other._ShadowSubList));
    }
    else {
        setValue(std::string(other.filePath),
                 std::string(other.objectName),
                 std::vector<std::string>(other._SubList),
                 std::vector<ShadowSub>(other._ShadowSubList));
    }
    if (other._Fingerprints.size() == _SubList.size()) {
        _Fingerprints = other._Fingerprints;
    }
    if (other._Guesses.size() == _SubList.size()) {
        _Guesses = other._Guesses;  // undo and redo restore a guess with its record (ops#127)
    }
    // The reorder's re-target records come back with their references (ops#127)
    _Retargets = other._Retargets;
    _Retargets.resize(_SubList.size());
    setFlag(LinkAllowPartial, other.testFlag(LinkAllowPartial));
}

void PropertyXLink::setRetargets(std::vector<RetargetRecord>&& records)
{
    aboutToSetValue();
    _Retargets = std::move(records);
    _Retargets.resize(_SubList.size());
    hasSetValue();
}

void PropertyXLink::setElementFingerprint(std::size_t index, const std::string& fingerprint)
{
    if (index >= _SubList.size()) {
        return;
    }
    aboutToSetValue();
    _Fingerprints.resize(_SubList.size());
    _Fingerprints[index] = fingerprint;
    hasSetValue();
}

bool PropertyXLink::supportXLink(const App::Property* prop)
{
    return prop->isDerivedFrom<PropertyXLink>()
        || prop->isDerivedFrom<PropertyXLinkSubList>()
        || prop->isDerivedFrom<PropertyXLinkContainer>();
}

bool PropertyXLink::hasXLink(const App::Document* doc)
{
    for (auto& v : _DocInfoMap) {
        if (v.second->hasXLink(doc)) {
            return true;
        }
    }
    return false;
}

bool PropertyXLink::hasXLink(const std::vector<App::DocumentObject*>& objs,
                             std::vector<App::Document*>* unsaved)
{
    std::set<App::Document*> docs;
    bool ret = false;
    for (auto o : objs) {
        if (o && o->isAttachedToDocument() && docs.insert(o->getDocument()).second) {
            if (!hasXLink(o->getDocument())) {
                continue;
            }
            if (!unsaved) {
                return true;
            }
            ret = true;
            if (!o->getDocument()->isSaved()) {
                unsaved->push_back(o->getDocument());
            }
        }
    }
    return ret;
}

void PropertyXLink::restoreDocument(const App::Document& doc)
{
    DocInfo::restoreDocument(doc);
}

std::map<App::Document*, std::set<App::Document*>>
PropertyXLink::getDocumentOutList(App::Document* doc)
{
    std::map<App::Document*, std::set<App::Document*>> ret;
    for (auto& v : _DocInfoMap) {
        for (auto link : v.second->links) {
            if (!v.second->pcDoc || link->getScope() == LinkScope::Hidden
                || link->testStatus(Property::PropTransient)
                || link->testStatus(Property::Transient)
                || link->testStatus(Property::PropNoPersist)) {
                continue;
            }
            auto obj = dynamic_cast<App::DocumentObject*>(link->getContainer());
            if (!obj || !obj->isAttachedToDocument() || !obj->getDocument()) {
                continue;
            }
            if (doc && obj->getDocument() != doc) {
                continue;
            }
            ret[obj->getDocument()].insert(v.second->pcDoc);
        }
    }
    return ret;
}

std::map<App::Document*, std::set<App::Document*>>
PropertyXLink::getDocumentInList(App::Document* doc)
{
    std::map<App::Document*, std::set<App::Document*>> ret;
    for (auto& v : _DocInfoMap) {
        if (!v.second->pcDoc || (doc && doc != v.second->pcDoc) || v.second->links.empty()) {
            continue;
        }
        auto& docs = ret[v.second->pcDoc];
        for (auto link : v.second->links) {
            if (link->getScope() == LinkScope::Hidden || link->testStatus(Property::PropTransient)
                || link->testStatus(Property::Transient)
                || link->testStatus(Property::PropNoPersist)) {
                continue;
            }
            auto obj = dynamic_cast<App::DocumentObject*>(link->getContainer());
            if (obj && obj->isAttachedToDocument() && obj->getDocument()) {
                docs.insert(obj->getDocument());
            }
        }
    }
    return ret;
}

PyObject* PropertyXLink::getPyObject()
{
    if (!_pcLink) {
        Py_Return;
    }
    const auto& subs = getSubValues(false);
    if (subs.empty()) {
        return _pcLink->getPyObject();
    }
    Py::Tuple ret(2);
    ret.setItem(0, Py::Object(_pcLink->getPyObject(), true));
    PropertyString propString;
    if (subs.size() == 1) {
        propString.setValue(subs.front());
        ret.setItem(1, Py::asObject(propString.getPyObject()));
    }
    else {
        Py::List list(subs.size());
        int i = 0;
        for (auto& sub : subs) {
            propString.setValue(sub);
            list[i++] = Py::asObject(propString.getPyObject());
        }
        ret.setItem(1, list);
    }
    return Py::new_reference_to(ret);
}

void PropertyXLink::setPyObject(PyObject* value)
{
    if (PySequence_Check(value)) {
        Py::Sequence seq(value);
        if (seq.size() != 2) {
            throw Base::ValueError("Expect input sequence of size 2");
        }
        std::vector<std::string> subs;
        Py::Object pyObj(seq[0].ptr());
        Py::Object pySub(seq[1].ptr());
        if (pyObj.isNone()) {
            setValue(nullptr);
            return;
        }
        else if (!PyObject_TypeCheck(pyObj.ptr(), &DocumentObjectPy::Type)) {
            throw Base::TypeError("Expect the first element to be of 'DocumentObject'");
        }
        PropertyString propString;
        if (pySub.isString()) {
            propString.setPyObject(pySub.ptr());
            subs.push_back(propString.getStrValue());
        }
        else if (pySub.isSequence()) {
            Py::Sequence seq(pySub);
            subs.reserve(seq.size());
            for (Py_ssize_t i = 0; i < seq.size(); ++i) {
                Py::Object sub(seq[i]);
                if (!sub.isString()) {
                    throw Base::TypeError("Expect only string inside second argument");
                }
                propString.setPyObject(sub.ptr());
                subs.push_back(propString.getStrValue());
            }
        }
        else {
            throw Base::TypeError("Expect the second element to be a string or sequence of string");
        }
        setValue(static_cast<DocumentObjectPy*>(pyObj.ptr())->getDocumentObjectPtr(),
                 std::move(subs));
    }
    else if (PyObject_TypeCheck(value, &(DocumentObjectPy::Type))) {
        setValue(static_cast<DocumentObjectPy*>(value)->getDocumentObjectPtr());
    }
    else if (Py_None == value) {
        setValue(nullptr);
    }
    else {
        throw Base::TypeError(
            "type must be 'DocumentObject', 'None', or '(DocumentObject, SubName)' or "
            "'DocumentObject, [SubName..])");
    }
}

const char* PropertyXLink::getSubName(bool newStyle) const
{
    if (_SubList.empty() || _ShadowSubList.empty()) {
        return "";
    }
    return getSubNameWithStyle(_SubList[0], _ShadowSubList[0], newStyle, tmpShadow).c_str();
}

void PropertyXLink::getLinks(std::vector<App::DocumentObject*>& objs,
                             bool all,
                             std::vector<std::string>* subs,
                             bool newStyle) const
{
    if ((all || _pcScope != LinkScope::Hidden) && _pcLink && _pcLink->isAttachedToDocument()) {
        // we use to run this method everytime the program needed to access the sub-elements in
        // a property link, but it caused multiple issues (#23441 and #23402) so it has been
        // commented out.
        // updateElementReferences(_pcLink, false);
        objs.push_back(_pcLink);
        if (subs && _SubList.size() == _ShadowSubList.size()) {
            *subs = getSubValues(newStyle);
        }
    }
}

void PropertyXLink::getLinksTo(std::vector<App::ObjectIdentifier>& identifiers,
                               App::DocumentObject* obj,
                               const char* subname,
                               bool all) const
{
    if (all || _pcScope != LinkScope::Hidden) {
        if (obj && obj == _pcLink) {
            _getLinksTo(identifiers, obj, subname, _SubList, _ShadowSubList);
        }
    }
}

bool PropertyXLink::adjustLink(const std::set<App::DocumentObject*>& inList)
{
    if (_pcScope == LinkScope::Hidden) {
        return false;
    }
    if (!_pcLink || !_pcLink->isAttachedToDocument() || !inList.contains(_pcLink)) {
        return false;
    }
    auto subs = _SubList;
    auto link = adjustLinkSubs(this, inList, _pcLink, subs);
    if (link) {
        setValue(link, std::move(subs));
        return true;
    }
    return false;
}

std::vector<std::string> PropertyXLink::getSubValues(bool newStyle) const
{
    assert(_SubList.size() == _ShadowSubList.size());
    std::vector<std::string> ret;
    ret.reserve(_SubList.size());
    std::string tmp;
    for (size_t i = 0; i < _ShadowSubList.size(); ++i) {
        ret.push_back(getSubNameWithStyle(_SubList[i], _ShadowSubList[i], newStyle, tmp));
    }
    return ret;
}

std::vector<std::string> PropertyXLink::getSubValuesStartsWith(const char* starter,
                                                               bool newStyle) const
{
    (void)newStyle;

    std::vector<std::string> temp;
    for (const auto& it : _SubList) {
        if (strncmp(starter, it.c_str(), strlen(starter)) == 0) {
            temp.push_back(it);
        }
    }
    return temp;
}

void PropertyXLink::setAllowPartial(bool enable)
{
    setFlag(LinkAllowPartial, enable);
    if (enable) {
        return;
    }
    auto owner = dynamic_cast<const DocumentObject*>(getContainer());
    if (!owner) {
        return;
    }
    if (!App::GetApplication().isRestoring() && !owner->getDocument()->isPerformingTransaction()
        && !_pcLink && docInfo && !filePath.empty() && !objectName.empty()
        && (!docInfo->pcDoc || docInfo->pcDoc->testStatus(Document::PartialDoc))) {
        auto path = docInfo->getDocPath(filePath.c_str(), owner->getDocument(), false);
        if (!path.empty()) {
            App::GetApplication().openDocument(path.c_str());
        }
    }
}

//**************************************************************************
// PropertyXLinkSub
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyXLinkSub, App::PropertyXLink)
TYPESYSTEM_SOURCE(App::PropertyXLinkSubHidden, App::PropertyXLinkSub)

PropertyXLinkSub::PropertyXLinkSub(bool allowPartial, PropertyLinkBase* parent)
    : PropertyXLink(allowPartial, parent)
{}

PropertyXLinkSub::~PropertyXLinkSub() = default;

bool PropertyXLinkSub::upgrade(Base::XMLReader& reader, const char* typeName)
{
    if (typeName == PropertyLinkSubGlobal::getClassTypeId().getName()
        || typeName == PropertyLinkSub::getClassTypeId().getName()
        || typeName == PropertyLinkSubChild::getClassTypeId().getName()) {
        App::PropertyLinkSub linkProp;
        linkProp.setContainer(getContainer());
        linkProp.Restore(reader);
        setValue(linkProp.getValue(), linkProp.getSubValues());
        return true;
    }
    return PropertyXLink::upgrade(reader, typeName);
}

PyObject* PropertyXLinkSub::getPyObject()
{
    if (!_pcLink) {
        Py_Return;
    }
    Py::Tuple ret(2);
    ret.setItem(0, Py::Object(_pcLink->getPyObject(), true));
    const auto& subs = getSubValues(false);
    Py::List list(subs.size());
    int i = 0;
    PropertyString propString;
    for (auto& sub : subs) {
        propString.setValue(sub);
        list[i++] = Py::asObject(propString.getPyObject());
    }
    ret.setItem(1, list);
    return Py::new_reference_to(ret);
}

//**************************************************************************
// PropertyXLinkSubList
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyXLinkSubList, App::PropertyLinkBase)

//**************************************************************************
// Construction/Destruction


PropertyXLinkSubList::PropertyXLinkSubList()
{
    _pcScope = LinkScope::Global;
    setSyncSubObject(true);
}

PropertyXLinkSubList::~PropertyXLinkSubList() = default;

void PropertyXLinkSubList::setSyncSubObject(bool enable)
{
    _Flags.set((std::size_t)LinkSyncSubObject, enable);
}

int PropertyXLinkSubList::getSize() const
{
    return static_cast<int>(_Links.size());
}

void PropertyXLinkSubList::setValue(DocumentObject* lValue, const char* SubName)
{
    std::map<DocumentObject*, std::vector<std::string>> values;
    if (lValue) {
        auto& subs = values[lValue];
        if (SubName) {
            subs.emplace_back(SubName);
        }
    }
    setValues(std::move(values));
}

void PropertyXLinkSubList::setValues(const std::vector<DocumentObject*>& lValue,
                                     const std::vector<const char*>& lSubNames)
{
#define CHECK_SUB_SIZE(_l, _r)                                                                     \
    do {                                                                                           \
        if (_l.size() != _r.size())                                                                \
            FC_THROWM(Base::ValueError, "object and subname size mismatch");                       \
    } while (0)
    CHECK_SUB_SIZE(lValue, lSubNames);
    std::map<DocumentObject*, std::vector<std::string>> values;
    int i = 0;
    for (auto& obj : lValue) {
        const char* sub = lSubNames[i++];
        if (sub) {
            values[obj].emplace_back(sub);
        }
    }
    setValues(std::move(values));
}

void PropertyXLinkSubList::setValues(const std::vector<DocumentObject*>& lValue,
                                     const std::vector<std::string>& lSubNames)
{
    CHECK_SUB_SIZE(lValue, lSubNames);
    std::map<DocumentObject*, std::vector<std::string>> values;
    int i = 0;
    for (auto& obj : lValue) {
        values[obj].push_back(lSubNames[i++]);
    }
    setValues(std::move(values));
}

void PropertyXLinkSubList::setSubListValues(const std::vector<PropertyLinkSubList::SubSet>& svalues)
{
    std::map<DocumentObject*, std::vector<std::string>> values;
    for (auto& v : svalues) {
        auto& s = values[v.first];
        s.reserve(s.size() + v.second.size());
        s.insert(s.end(), v.second.begin(), v.second.end());
    }
    setValues(std::move(values));
}

void PropertyXLinkSubList::setValues(
    const std::map<App::DocumentObject*, std::vector<std::string>>& values)
{
    setValues(std::map<App::DocumentObject*, std::vector<std::string>>(values));
}

void PropertyXLinkSubList::setValues(
    std::map<App::DocumentObject*, std::vector<std::string>>&& values)
{
    for (auto& v : values) {
        if (!v.first || !v.first->isAttachedToDocument()) {
            FC_THROWM(Base::ValueError, "invalid document object");
        }
    }

    atomic_change guard(*this);

    for (auto it = _Links.begin(), itNext = it; it != _Links.end(); it = itNext) {
        ++itNext;
        auto iter = values.find(it->getValue());
        if (iter == values.end()) {
            _Links.erase(it);
            continue;
        }
        it->setSubValues(std::move(iter->second));
        values.erase(iter);
    }

    for (auto& v : values) {
        _Links.emplace_back(testFlag(LinkAllowPartial), this);
        _Links.back().setValue(v.first, std::move(v.second));
    }
    guard.tryInvoke();
}

void PropertyXLinkSubList::addValue(App::DocumentObject* obj,
                                    const std::vector<std::string>& subs,
                                    bool reset)
{
    addValue(obj, std::vector<std::string>(subs), reset);
}

void PropertyXLinkSubList::addValue(App::DocumentObject* obj,
                                    std::vector<std::string>&& subs,
                                    bool reset)
{

    if (!obj || !obj->isAttachedToDocument()) {
        FC_THROWM(Base::ValueError, "invalid document object");
    }

    for (auto& l : _Links) {
        if (l.getValue() == obj) {
            auto s = l.getSubValues();
            if (s.empty() || reset) {
                l.setSubValues(std::move(subs));
            }
            else {
                s.reserve(s.size() + subs.size());
                std::move(subs.begin(), subs.end(), std::back_inserter(s));
                l.setSubValues(std::move(s));
            }
            return;
        }
    }
    atomic_change guard(*this);
    _Links.emplace_back(testFlag(LinkAllowPartial), this);
    _Links.back().setValue(obj, std::move(subs));
    guard.tryInvoke();
}

void PropertyXLinkSubList::setValue(DocumentObject* lValue, const std::vector<std::string>& SubList)
{
    std::map<DocumentObject*, std::vector<std::string>> values;
    if (lValue) {
        values[lValue] = SubList;
    }
    setValues(std::move(values));
}

void PropertyXLinkSubList::setValues(const std::vector<DocumentObject*>& values)
{
    atomic_change guard(*this);
    _Links.clear();
    for (auto obj : values) {
        _Links.emplace_back(testFlag(LinkAllowPartial), this);
        _Links.back().setValue(obj);
    }
    guard.tryInvoke();
}

void PropertyXLinkSubList::set1Value(int idx,
                                     DocumentObject* value,
                                     const std::vector<std::string>& SubList)
{
    if (idx < -1 || idx > getSize()) {
        throw Base::RuntimeError("index out of bound");
    }

    if (idx < 0 || idx + 1 == getSize()) {
        if (SubList.empty()) {
            addValue(value, SubList);
            return;
        }
        atomic_change guard(*this);
        _Links.emplace_back(testFlag(LinkAllowPartial), this);
        _Links.back().setValue(value);
        guard.tryInvoke();
        return;
    }

    auto it = _Links.begin();
    for (; idx; --idx) {
        ++it;
    }
    it->setValue(value, SubList);
}

const string PropertyXLinkSubList::getPyReprString() const
{
    if (_Links.empty()) {
        return std::string("None");
    }
    std::ostringstream ss;
    ss << '[';
    for (auto& link : _Links) {
        auto obj = link.getValue();
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        ss << "(App.getDocument('" << obj->getDocument()->getName() << "').getObject('"
           << obj->getNameInDocument() << "'),  (";
        const auto& subs = link.getSubValues();
        if (subs.empty()) {
            ss << "''";
        }
        else {
            for (auto& sub : subs) {
                ss << "'" << sub << "',";
            }
        }
        ss << ")), ";
    }
    ss << ']';
    return ss.str();
}

DocumentObject* PropertyXLinkSubList::getValue() const
{
    if (!_Links.empty()) {
        return _Links.begin()->getValue();
    }
    return nullptr;
}

int PropertyXLinkSubList::removeValue(App::DocumentObject* lValue)
{
    atomic_change guard(*this, false);
    int ret = 0;
    for (auto it = _Links.begin(); it != _Links.end();) {
        if (it->getValue() != lValue) {
            ++it;
        }
        else {
            guard.aboutToChange();
            it = _Links.erase(it);
            ++ret;
        }
    }
    guard.tryInvoke();
    return ret;
}

PyObject* PropertyXLinkSubList::getPyObject()
{
    Py::List list;
    for (auto& link : _Links) {
        auto obj = link.getValue();
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }

        Py::Tuple tup(2);
        tup[0] = Py::asObject(obj->getPyObject());

        const auto& subs = link.getSubValues();
        Py::Tuple items(subs.size());
        for (std::size_t j = 0; j < subs.size(); j++) {
            items[j] = Py::String(subs[j]);
        }
        tup[1] = items;
        list.append(tup);
    }
    return Py::new_reference_to(list);
}

void PropertyXLinkSubList::setPyObject(PyObject* value)
{
    try {  // try PropertyLinkSub syntax
        PropertyLinkSub dummy;
        dummy.setAllowExternal(true);
        dummy.setPyObject(value);
        this->setValue(dummy.getValue(), dummy.getSubValues());
        return;
    }
    catch (Base::Exception&) {
    }

    if (!PyTuple_Check(value) && !PyList_Check(value)) {
        throw Base::TypeError(
            "Invalid type. Accepts (DocumentObject, (subname...)) or sequence of such type.");
    }
    Py::Sequence seq(value);
    std::map<DocumentObject*, std::vector<std::string>> values;
    try {
        for (Py_ssize_t i = 0; i < seq.size(); ++i) {
            PropertyLinkSub link;
            link.setAllowExternal(true);
            link.setPyObject(seq[i].ptr());
            const auto& subs = link.getSubValues();
            auto& s = values[link.getValue()];
            s.reserve(s.size() + subs.size());
            s.insert(s.end(), subs.begin(), subs.end());
        }
    }
    catch (Base::Exception&) {
        throw Base::TypeError(
            "Invalid type inside sequence. Must be type of (DocumentObject, (subname...))");
    }
    setValues(std::move(values));
}

void PropertyXLinkSubList::afterRestore()
{
    for (auto& l : _Links) {
        l.afterRestore();
    }
}

void PropertyXLinkSubList::onContainerRestored()
{
    for (auto& l : _Links) {
        l.onContainerRestored();
    }
}

void PropertyXLinkSubList::updateElementReference(DocumentObject* feature,
                                                  bool reverse,
                                                  bool notify)
{
    for (auto& l : _Links) {
        l.updateElementReference(feature, reverse, notify);
    }
}

bool PropertyXLinkSubList::updateElementFingerprints()
{
    bool holdsElements = false;
    for (auto& l : _Links) {
        holdsElements = l.updateElementFingerprints() || holdsElements;
    }
    return holdsElements;
}

// The reference solver's passes (ops#7): per link, which holds the references (and is what
// registers under the targets).
void PropertyXLinkSubList::collectElementReferences(App::DocumentObject* feature, SolverBatch& batch)
{
    for (auto& l : _Links) {
        l.collectElementReferences(feature, batch);
    }
}

void PropertyXLinkSubList::applyResolutions(const std::vector<SolverResolution>& resolutions)
{
    for (auto& l : _Links) {
        std::vector<SolverResolution> own;
        for (const auto& resolution : resolutions) {
            if (resolution.prop == &l) {
                own.push_back(resolution);
            }
        }
        if (!own.empty()) {
            l.applyResolutions(own);
        }
    }
}

std::vector<std::string> PropertyXLinkSubList::getElementFingerprints() const
{
    std::vector<std::string> fingerprints;
    for (auto& l : _Links) {
        auto child = l.getElementFingerprints();
        fingerprints.insert(fingerprints.end(), child.begin(), child.end());
    }
    return fingerprints;
}

std::vector<GuessRecord> PropertyXLinkSubList::getElementGuesses() const
{
    std::vector<GuessRecord> guesses;
    for (auto& l : _Links) {
        auto child = l.getElementGuesses();
        guesses.insert(guesses.end(), child.begin(), child.end());
    }
    return guesses;
}

bool PropertyXLinkSubList::referenceChanged() const
{
    for (auto& l : _Links) {
        if (l.referenceChanged()) {
            return true;
        }
    }
    return false;
}

void PropertyXLinkSubList::Save(Base::Writer& writer) const
{
    writer.Stream() << writer.ind() << "<XLinkSubList count=\"" << _Links.size();
    if (testFlag(LinkAllowPartial)) {
        writer.Stream() << "\" partial=\"1";
    }
    writer.Stream() << "\">" << endl;
    writer.incInd();
    for (auto& l : _Links) {
        l.Save(writer);
    }
    writer.decInd();
    writer.Stream() << writer.ind() << "</XLinkSubList>" << endl;
}

void PropertyXLinkSubList::Restore(Base::XMLReader& reader)
{
    reader.readElement("XLinkSubList");
    setFlag(LinkAllowPartial,
            reader.hasAttribute("partial") && reader.getAttribute<bool>("partial"));
    int count = reader.getAttribute<long>("count");
    atomic_change guard(*this, false);
    _Links.clear();
    for (int i = 0; i < count; ++i) {
        _Links.emplace_back(false, this);
        _Links.back().Restore(reader);
    }
    reader.readEndElement("XLinkSubList");
    guard.tryInvoke();
}

Property*
PropertyXLinkSubList::CopyOnImportExternal(const std::map<std::string, std::string>& nameMap) const
{
    std::unique_ptr<Property> copy;
    auto it = _Links.begin();
    for (; it != _Links.end(); ++it) {
        copy.reset(it->CopyOnImportExternal(nameMap));
        if (copy) {
            break;
        }
    }
    if (!copy) {
        return nullptr;
    }
    std::unique_ptr<PropertyXLinkSubList> p(new PropertyXLinkSubList);
    for (auto iter = _Links.begin(); iter != it; ++iter) {
        p->_Links.emplace_back();
        iter->copyTo(p->_Links.back());
    }
    p->_Links.emplace_back();
    static_cast<PropertyXLinkSub&>(*copy).copyTo(p->_Links.back());
    for (++it; it != _Links.end(); ++it) {
        p->_Links.emplace_back();
        copy.reset(it->CopyOnImportExternal(nameMap));
        if (copy) {
            static_cast<PropertyXLinkSub&>(*copy).copyTo(p->_Links.back());
        }
        else {
            it->copyTo(p->_Links.back());
        }
    }
    return p.release();
}

Property* PropertyXLinkSubList::CopyOnLabelChange(App::DocumentObject* obj,
                                                  const std::string& ref,
                                                  const char* newLabel) const
{
    std::unique_ptr<Property> copy;
    auto it = _Links.begin();
    for (; it != _Links.end(); ++it) {
        copy.reset(it->CopyOnLabelChange(obj, ref, newLabel));
        if (copy) {
            break;
        }
    }
    if (!copy) {
        return nullptr;
    }
    std::unique_ptr<PropertyXLinkSubList> p(new PropertyXLinkSubList);
    for (auto iter = _Links.begin(); iter != it; ++iter) {
        p->_Links.emplace_back();
        iter->copyTo(p->_Links.back());
    }
    p->_Links.emplace_back();
    static_cast<PropertyXLinkSub&>(*copy).copyTo(p->_Links.back());
    for (++it; it != _Links.end(); ++it) {
        p->_Links.emplace_back();
        copy.reset(it->CopyOnLabelChange(obj, ref, newLabel));
        if (copy) {
            static_cast<PropertyXLinkSub&>(*copy).copyTo(p->_Links.back());
        }
        else {
            it->copyTo(p->_Links.back());
        }
    }
    return p.release();
}

Property* PropertyXLinkSubList::CopyOnLinkReplace(const App::DocumentObject* parent,
                                                  App::DocumentObject* oldObj,
                                                  App::DocumentObject* newObj) const
{
    std::unique_ptr<Property> copy;
    PropertyXLinkSub* copied = nullptr;
    std::set<std::string> subs;
    auto it = _Links.begin();
    for (; it != _Links.end(); ++it) {
        copy.reset(it->CopyOnLinkReplace(parent, oldObj, newObj));
        if (copy) {
            copied = static_cast<PropertyXLinkSub*>(copy.get());
            if (copied->getValue() == newObj) {
                for (auto& sub : copied->getSubValues()) {
                    subs.insert(sub);
                }
            }
            break;
        }
    }
    if (!copy) {
        return nullptr;
    }
    std::unique_ptr<PropertyXLinkSubList> p(new PropertyXLinkSubList);
    for (auto iter = _Links.begin(); iter != it; ++iter) {
        if (iter->getValue() == newObj && copied->getValue() == newObj) {
            // merge subnames in case new object already exists
            for (auto& sub : iter->getSubValues()) {
                if (subs.insert(sub).second) {
                    copied->_SubList.push_back(sub);
                }
            }
        }
        else {
            p->_Links.emplace_back();
            iter->copyTo(p->_Links.back());
        }
    }
    p->_Links.emplace_back();
    copied->copyTo(p->_Links.back());
    copied = &p->_Links.back();
    for (++it; it != _Links.end(); ++it) {
        if ((it->getValue() == newObj || it->getValue() == oldObj)
            && copied->getValue() == newObj) {
            // merge subnames in case new object already exists
            for (auto& sub : it->getSubValues()) {
                if (subs.insert(sub).second) {
                    copied->_SubList.push_back(sub);
                }
            }
            continue;
        }
        p->_Links.emplace_back();
        copy.reset(it->CopyOnLinkReplace(parent, oldObj, newObj));
        if (copy) {
            static_cast<PropertyXLinkSub&>(*copy).copyTo(p->_Links.back());
        }
        else {
            it->copyTo(p->_Links.back());
        }
    }
    return p.release();
}

Property* PropertyXLinkSubList::Copy() const
{
    PropertyXLinkSubList* p = new PropertyXLinkSubList();
    for (auto& l : _Links) {
        p->_Links.emplace_back(testFlag(LinkAllowPartial), p);
        l.copyTo(p->_Links.back());
    }
    return p;
}

void PropertyXLinkSubList::editLink(std::size_t link,
                                    const std::function<void(PropertyXLinkSub&)>& edit)
{
    if (link >= _Links.size()) {
        return;
    }
    aboutToSetValue();
    auto it = _Links.begin();
    std::advance(it, link);
    edit(*it);
    hasSetValue();
}

void PropertyXLinkSubList::Paste(const Property& from)
{
    if (!from.isDerivedFrom<PropertyXLinkSubList>()) {
        throw Base::TypeError("Incompatible property to paste to");
    }

    aboutToSetValue();
    _Links.clear();
    for (auto& l : static_cast<const PropertyXLinkSubList&>(from)._Links) {
        _Links.emplace_back(testFlag(LinkAllowPartial), this);
        _Links.back().Paste(l);
    }
    hasSetValue();
}

unsigned int PropertyXLinkSubList::getMemSize() const
{
    unsigned int size = 0;
    for (auto& l : _Links) {
        size += l.getMemSize();
    }
    return size;
}

const std::vector<std::string>& PropertyXLinkSubList::getSubValues(App::DocumentObject* obj) const
{
    for (auto& l : _Links) {
        if (l.getValue() == obj) {
            return l.getSubValues();
        }
    }
    FC_THROWM(Base::RuntimeError, "object not found");
}

std::vector<std::string> PropertyXLinkSubList::getSubValues(App::DocumentObject* obj,
                                                            bool newStyle) const
{
    for (auto& l : _Links) {
        if (l.getValue() == obj) {
            return l.getSubValues(newStyle);
        }
    }
    return {};
}

void PropertyXLinkSubList::getLinks(std::vector<App::DocumentObject*>& objs,
                                    bool all,
                                    std::vector<std::string>* subs,
                                    bool newStyle) const
{
    if (all || _pcScope != LinkScope::Hidden) {
        if (!subs) {
            objs.reserve(objs.size() + _Links.size());
            for (auto& l : _Links) {
                auto obj = l.getValue();
                if (obj && obj->isAttachedToDocument()) {
                    objs.push_back(obj);
                }
            }
            return;
        }
        size_t count = 0;
        for (auto& l : _Links) {
            auto obj = l.getValue();
            if (obj && obj->isAttachedToDocument()) {
                count += std::max((int)l.getSubValues().size(), 1);
            }
        }
        if (!count) {
            objs.reserve(objs.size() + _Links.size());
            for (auto& l : _Links) {
                auto obj = l.getValue();
                if (obj && obj->isAttachedToDocument()) {
                    objs.push_back(obj);
                }
            }
            return;
        }

        objs.reserve(objs.size() + count);
        subs->reserve(subs->size() + count);
        for (auto& l : _Links) {
            auto obj = l.getValue();
            if (obj && obj->isAttachedToDocument()) {
                // we use to run this method everytime the program needed to access the sub-elements in
                // a property link, but it caused multiple issues (#23441 and #23402) so it has been
                // commented out.
                // updateElementReferences(obj);

                auto subnames = l.getSubValues(newStyle);
                if (subnames.empty()) {
                    subnames.emplace_back("");
                }
                for (auto& sub : subnames) {
                    objs.push_back(obj);
                    subs->push_back(std::move(sub));
                }
            }
        }
    }
}

// Same algorithm as _getLinksTo above, but returns all matches
void PropertyXLinkSubList::_getLinksToList(
    std::vector<App::ObjectIdentifier>& identifiers,
    App::DocumentObject* obj,
    const char* subname,
    const std::vector<std::string>& subs,
    const std::vector<PropertyLinkBase::ShadowSub>& shadows) const
{
    if (!subname) {
        identifiers.emplace_back(*this);
        return;
    }
    App::SubObjectT objT(obj, subname);
    auto subObject = objT.getSubObject();
    auto subElement = objT.getOldElementName();

    int i = -1;
    for (const auto& sub : subs) {
        ++i;
        if (sub == subname) {
            identifiers.emplace_back(*this, i);
            continue;
        }
        if (!subObject) {
            continue;
        }
        // There is a subobject and the subname doesn't match our current entry
        App::SubObjectT sobjT(obj, sub.c_str());
        if (sobjT.getSubObject() == subObject && sobjT.getOldElementName() == subElement) {
            identifiers.emplace_back(*this, i);
            continue;
        }
        // The oldElementName ( short, I.E. "Edge5" ) doesn't match.
        if (i < (int)shadows.size()) {
            const auto& [shadowNewName, shadowOldName] = shadows[i];
            if (shadowNewName == subname || shadowOldName == subname) {
                identifiers.emplace_back(*this, i);
                continue;
            }
            if (!subObject) {
                continue;
            }
            App::SubObjectT shadowobjT(obj,
                                       shadowNewName.empty() ? shadowOldName.c_str()
                                                             : shadowNewName.c_str());
            if (shadowobjT.getSubObject() == subObject
                && shadowobjT.getOldElementName() == subElement) {
                identifiers.emplace_back(*this, i);
                continue;
            }
        }
    }
}

void PropertyXLinkSubList::getLinksTo(std::vector<App::ObjectIdentifier>& identifiers,
                                      App::DocumentObject* obj,
                                      const char* subname,
                                      bool all) const
{
    if (!all && _pcScope != LinkScope::Hidden) {
        return;
    }
    for (auto& l : _Links) {
        if (obj && obj == l._pcLink) {
            _getLinksToList(identifiers, obj, subname, l._SubList, l._ShadowSubList);
        }
    }
}

void PropertyXLinkSubList::breakLink(App::DocumentObject* obj, bool clear)
{
    if (clear && getContainer() == obj) {
        setValue(nullptr);
        return;
    }
    atomic_change guard(*this, false);
    for (auto& l : _Links) {
        if (l.getValue() == obj) {
            guard.aboutToChange();
            l.setValue(nullptr);
        }
    }
    guard.tryInvoke();
}

bool PropertyXLinkSubList::adjustLink(const std::set<App::DocumentObject*>& inList)
{
    if (_pcScope == LinkScope::Hidden) {
        return false;
    }
    std::map<App::DocumentObject*, std::vector<std::string>> values;
    bool touched = false;
    int count = 0;
    for (auto& l : _Links) {
        auto obj = l.getValue();
        if (!obj || !obj->isAttachedToDocument()) {
            ++count;
            continue;
        }
        if (inList.contains(obj) && adjustLinkSubs(this, inList, obj, l._SubList, &values)) {
            touched = true;
        }
    }
    if (touched) {
        decltype(_Links) tmp;
        if (count) {
            // XLink allows detached state, i.e. with closed external document. So
            // we need to preserve empty link
            for (auto it = _Links.begin(), itNext = it; it != _Links.end(); it = itNext) {
                ++itNext;
                if (!it->getValue()) {
                    tmp.splice(tmp.end(), _Links, it);
                }
            }
        }
        setValues(std::move(values));
        _Links.splice(_Links.end(), tmp);
    }
    return touched;
}

int PropertyXLinkSubList::checkRestore(std::string* msg) const
{
    for (auto& l : _Links) {
        int res;
        if ((res = l.checkRestore(msg))) {
            return res;
        }
    }
    return 0;
}

bool PropertyXLinkSubList::upgrade(Base::XMLReader& reader, const char* typeName)
{
    if (typeName == PropertyLinkListGlobal::getClassTypeId().getName()
        || typeName == PropertyLinkList::getClassTypeId().getName()
        || typeName == PropertyLinkListChild::getClassTypeId().getName()) {
        PropertyLinkList linkProp;
        linkProp.setContainer(getContainer());
        linkProp.Restore(reader);
        setValues(linkProp.getValues());
        return true;
    }
    else if (
        typeName == PropertyLinkSubListGlobal::getClassTypeId().getName()
        || typeName == PropertyLinkSubList::getClassTypeId().getName()
        || typeName == PropertyLinkSubListChild::getClassTypeId().getName()
    ) {
        PropertyLinkSubList linkProp;
        linkProp.setContainer(getContainer());
        linkProp.Restore(reader);
        std::map<DocumentObject*, std::vector<std::string>> values;
        const auto& objs = linkProp.getValues();
        const auto& subs = linkProp.getSubValues();
        assert(objs.size() == subs.size());
        for (size_t i = 0; i < objs.size(); ++i) {
            values[objs[i]].push_back(subs[i]);
        }
        setValues(std::move(values));
        return true;
    }
    _Links.clear();
    _Links.emplace_back(testFlag(LinkAllowPartial), this);
    if (!_Links.back().upgrade(reader, typeName)) {
        _Links.clear();
        return false;
    }
    return true;
}

void PropertyXLinkSubList::setAllowPartial(bool enable)
{
    setFlag(LinkAllowPartial, enable);
    for (auto& l : _Links) {
        l.setAllowPartial(enable);
    }
}

void PropertyXLinkSubList::hasSetChildValue(Property&)
{
    if (!signalCounter) {
        hasSetValue();
    }
}

void PropertyXLinkSubList::aboutToSetChildValue(Property&)
{
    if (!signalCounter || !hasChanged) {
        aboutToSetValue();
        if (signalCounter) {
            hasChanged = true;
        }
    }
}

std::vector<App::DocumentObject*> PropertyXLinkSubList::getValues() const
{
    std::vector<DocumentObject*> xLinks;
    getLinks(xLinks);
    return (xLinks);
}

//**************************************************************************
// PropertyXLinkList
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TYPESYSTEM_SOURCE(App::PropertyXLinkList, App::PropertyXLinkSubList)

//**************************************************************************
// Construction/Destruction

PropertyXLinkList::PropertyXLinkList() = default;

PropertyXLinkList::~PropertyXLinkList() = default;

PyObject* PropertyXLinkList::getPyObject()
{
    for (auto& link : _Links) {
        auto obj = link.getValue();
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        if (link.hasSubName()) {
            return PropertyXLinkSubList::getPyObject();
        }
    }

    Py::List list;
    for (auto& link : _Links) {
        auto obj = link.getValue();
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        list.append(Py::asObject(obj->getPyObject()));
    }
    return Py::new_reference_to(list);
}

void PropertyXLinkList::setPyObject(PyObject* value)
{
    try {  // try PropertyLinkList syntax
        PropertyLinkList dummy;
        dummy.setAllowExternal(true);
        dummy.setPyObject(value);
        this->setValues(dummy.getValues());
        return;
    }
    catch (Base::Exception&) {
    }

    PropertyXLinkSubList::setPyObject(value);
}

//**************************************************************************
// PropertyXLinkContainer
//++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
TYPESYSTEM_SOURCE_ABSTRACT(App::PropertyXLinkContainer, App::PropertyLinkBase)

PropertyXLinkContainer::PropertyXLinkContainer()
{
    _pcScope = LinkScope::Global;
    _LinkRestored = false;
}

PropertyXLinkContainer::~PropertyXLinkContainer() = default;

void PropertyXLinkContainer::afterRestore()
{
    _DocMap.clear();
    if (!_XLinkRestores) {
        return;
    }
    _Deps.clear();
    for (auto& info : *_XLinkRestores) {
        auto obj = info.xlink->getValue();
        if (!obj) {
            continue;
        }
        if (!info.docName.empty()) {
            if (info.docName != obj->getDocument()->getName()) {
                _DocMap[info.docName] = obj->getDocument()->getName();
            }
            if (info.docLabel != obj->getDocument()->Label.getValue()) {
                _DocMap[App::quote(info.docLabel)] = obj->getDocument()->Label.getValue();
            }
        }
        if (_Deps.insert(std::make_pair(obj, info.xlink->getScope() == LinkScope::Hidden)).second) {
            _XLinks[obj->getFullName()] = std::move(info.xlink);
            onAddDep(obj);
        }
    }
    _XLinkRestores.reset();
}

void PropertyXLinkContainer::breakLink(App::DocumentObject* obj, bool clear)
{
    if (!obj || !obj->isAttachedToDocument()) {
        return;
    }
    auto owner = dynamic_cast<App::DocumentObject*>(getContainer());
    if (!owner || !owner->isAttachedToDocument()) {
        return;
    }
    if (!clear || obj != owner) {
        auto it = _Deps.find(obj);
        if (it == _Deps.end()) {
            return;
        }
        aboutToSetValue();
        onBreakLink(obj);
        if (obj->getDocument() != owner->getDocument()) {
            _XLinks.erase(obj->getFullName());
        }
        else if (!it->second) {
            obj->_removeBackLink(owner);
            obj->_removeBackLinkProp(getName(), owner);
        }
        _Deps.erase(it);
        onRemoveDep(obj);
        hasSetValue();
        return;
    }
    if (obj != owner) {
        return;
    }
    for (auto& v : _Deps) {
        auto key = v.first;
        if (!key || !key->isAttachedToDocument()) {
            continue;
        }
        onBreakLink(key);
        if (!v.second && key->getDocument() == owner->getDocument()) {
            key->_removeBackLink(owner);
        }
    }
    _XLinks.clear();
    _Deps.clear();
}

int PropertyXLinkContainer::checkRestore(std::string* msg) const
{
    if (_LinkRestored) {
        for (auto& v : _XLinks) {
            int res = v.second->checkRestore(msg);
            if (res) {
                return res;
            }
        }
    }
    return 0;
}

void PropertyXLinkContainer::Save(Base::Writer& writer) const
{

    writer.Stream() << writer.ind() << "<XLinks count=\"" << _XLinks.size();

    std::map<App::Document*, int> docSet;
    auto owner = freecad_cast<App::DocumentObject*>(getContainer());
    if (owner && !owner->isExporting()) {
        // Document name and label can change on restore, we shall record the
        // current document name and label and pair it with the associated
        // xlink, so that we can restore them correctly.
        int i = -1;
        for (auto& v : _XLinks) {
            ++i;
            auto obj = v.second->getValue();
            if (obj && obj->getDocument()) {
                docSet.insert(std::make_pair(obj->getDocument(), i));
            }
        }

        if (!docSet.empty()) {
            writer.Stream() << "\" docs=\"" << docSet.size();
        }
    }

    std::ostringstream ss;
    int hidden = 0;
    int i = -1;
    for (auto& v : _XLinks) {
        ++i;
        if (v.second->getScope() == LinkScope::Hidden) {
            ss << i << ' ';
            ++hidden;
        }
    }
    if (hidden) {
        writer.Stream() << "\" hidden=\"" << ss.str();
    }

    writer.Stream() << "\">" << std::endl;
    writer.incInd();

    for (auto& v : docSet) {
        writer.Stream() << writer.ind() << "<DocMap "
                        << "name=\"" << v.first->getName() << "\" label=\""
                        << encodeAttribute(v.first->Label.getValue()) << "\" index=\"" << v.second
                        << "\"/>" << std::endl;
    }

    for (auto& v : _XLinks) {
        v.second->Save(writer);
    }
    writer.decInd();

    writer.Stream() << writer.ind() << "</XLinks>" << std::endl;
}

void PropertyXLinkContainer::Restore(Base::XMLReader& reader)
{
    reader.readElement("XLinks");
    auto count = reader.getAttribute<unsigned long>("count");
    _XLinkRestores = std::make_unique<std::vector<RestoreInfo>>(count);

    if (reader.hasAttribute("hidden")) {
        std::istringstream iss(reader.getAttribute<const char*>("hidden"));
        int index;
        while (iss >> index) {
            if (index >= 0 && index < static_cast<int>(count)) {
                _XLinkRestores->at(index).hidden = true;
            }
        }
    }

    if (reader.hasAttribute("docs")) {
        auto docCount = reader.getAttribute<unsigned long>("docs");
        _DocMap.clear();
        for (unsigned i = 0; i < docCount; ++i) {
            reader.readElement("DocMap");
            auto index = reader.getAttribute<unsigned long>("index");
            if (index >= count) {
                FC_ERR(propertyName(this) << " invalid document map entry");
                continue;
            }
            auto& info = _XLinkRestores->at(index);
            info.docName = reader.getAttribute<const char*>("name");
            info.docLabel = reader.getAttribute<const char*>("label");
        }
    }

    for (auto& info : *_XLinkRestores) {
        info.xlink.reset(createXLink());
        if (info.hidden) {
            info.xlink->setScope(LinkScope::Hidden);
        }
        info.xlink->Restore(reader);
    }
    reader.readEndElement("XLinks");
}

void PropertyXLinkContainer::aboutToSetChildValue(App::Property& prop)
{
    auto xlink = dynamic_cast<App::PropertyXLink*>(&prop);
    if (xlink && xlink->testFlag(LinkDetached)) {
        auto obj = const_cast<App::DocumentObject*>(xlink->getValue());
        if (_Deps.erase(obj)) {
            _onBreakLink(xlink->getValue());
            onRemoveDep(obj);
        }
    }
}

void PropertyXLinkContainer::onBreakLink(DocumentObject*)
{}

void PropertyXLinkContainer::_onBreakLink(DocumentObject* obj)
{
    try {
        onBreakLink(obj);
    }
    catch (Base::Exception& e) {
        e.reportException();
        FC_ERR("Exception on breaking link property " << getFullName());
    }
    catch (std::exception& e) {
        FC_ERR("Exception on breaking link property " << getFullName() << ": " << e.what());
    }
    catch (...) {
        FC_ERR("Exception on breaking link property " << getFullName());
    }
}

PropertyXLink* PropertyXLinkContainer::createXLink()
{
    return new PropertyXLink(false, this);
}

bool PropertyXLinkContainer::isLinkedToDocument(const App::Document& doc) const
{
    auto iter = _XLinks.lower_bound(doc.getName());
    if (iter != _XLinks.end()) {
        size_t len = strlen(doc.getName());
        return iter->first.size() > len && iter->first[len] == '#'
            && boost::starts_with(iter->first, doc.getName());
    }
    return false;
}

// Mimics updateDeps() but for fine-grained property dependencies.  It does not
// handle the XLink logic that is left to updateDeps().
void PropertyXLinkContainer::updateDepsProp(
    std::map<std::pair<std::string, DocumentObject*>, bool>& propDeps)
{
    auto owner = freecad_cast<DocumentObject*>(getContainer());
    if (!owner || !owner->isAttachedToDocument()) {
        return;
    }

    // delete all entries in propDeps of owner:
    std::erase_if(propDeps, [owner](auto const& kv) {
        return kv.first.second == owner;
    });

    for (auto& [pair, hidden] : propDeps) {
        std::string const& propName = pair.first;
        DocumentObject* obj = pair.second;
        if (obj && obj->isAttachedToDocument()) {
            auto it = _PropDeps.find(pair);
            if (it != _PropDeps.end()) {
                if (hidden != it->second) {
                    if (hidden) {
                        obj->_removeBackLinkProp(getName(), owner, propName.c_str());
                    }
                    else {
                        obj->_addBackLinkProp(getName(), owner, propName.c_str());
                    }
                }
                _PropDeps.erase(it);
                continue;
            }
            if (!hidden) {
                obj->_addBackLinkProp(getName(), owner, propName.c_str());
            }
        }
    }

    for (auto& [pair, hidden] : _PropDeps) {
        std::string const& propName = pair.first;
        DocumentObject* obj = pair.second;
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        if (!hidden) {
            obj->_removeBackLinkProp(getName(), owner, propName.c_str());
        }
    }

    _PropDeps = std::move(propDeps);
}

void PropertyXLinkContainer::updateDeps(std::map<DocumentObject*, bool>&& newDeps,
                                        std::map<std::pair<std::string, DocumentObject*>, bool>* propDeps)
{
    // We want dependencies in terms of the to- and fromProperty if true.
    // Otherwise we only want the dependencies in terms of HEAD.
    bool fineGrainedProps = propDeps != nullptr;
    if (fineGrainedProps) {
        updateDepsProp(*propDeps);
    }
    auto owner = freecad_cast<App::DocumentObject*>(getContainer());
    if (!owner || !owner->isAttachedToDocument()) {
        return;
    }
    newDeps.erase(owner);

    for (auto& v : newDeps) {
        auto obj = v.first;
        if (obj && obj->isAttachedToDocument()) {
            auto it = _Deps.find(obj);
            if (it != _Deps.end()) {
                if (v.second != it->second) {
                    if (v.second) {
                        obj->_removeBackLink(owner);
                        if (!fineGrainedProps) {
                            obj->_removeBackLinkProp(getName(), owner);
                        }
                    }
                    else {
                        obj->_addBackLink(owner);
                        if (!fineGrainedProps) {
                            obj->_addBackLinkProp(getName(), owner);
                        }
                    }
                }
                _Deps.erase(it);
                continue;
            }
            if (owner->getDocument() != obj->getDocument()) {
                auto& xlink = _XLinks[obj->getFullName()];
                if (!xlink) {
                    xlink.reset(createXLink());
                    xlink->setValue(obj);
                }
                xlink->setScope(v.second ? LinkScope::Hidden : LinkScope::Global);
            }
            else if (!v.second) {
                obj->_addBackLink(owner);
                if (!fineGrainedProps) {
                    obj->_addBackLinkProp(getName(), owner);
                }
            }

            onAddDep(obj);
        }
    }
    for (auto& v : _Deps) {
        auto obj = v.first;
        if (!obj || !obj->isAttachedToDocument()) {
            continue;
        }
        if (obj->getDocument() == owner->getDocument()) {
            if (!v.second) {
                obj->_removeBackLink(owner);
                if (!fineGrainedProps) {
                    obj->_removeBackLinkProp(getName(), owner);
                }
            }
        }
        else {
            _XLinks.erase(obj->getFullName());
        }
        onRemoveDep(obj);
    }
    _Deps = std::move(newDeps);

    _LinkRestored = testFlag(LinkRestoring);

    if (!_LinkRestored && !testFlag(LinkDetached)) {
        for (auto it = _XLinks.begin(), itNext = it; it != _XLinks.end(); it = itNext) {
            ++itNext;
            if (!it->second->getValue()) {
                _XLinks.erase(it);
            }
        }
    }
}

void PropertyXLinkContainer::clearDeps()
{
    auto owner = dynamic_cast<App::DocumentObject*>(getContainer());
    if (!owner || !owner->isAttachedToDocument()) {
        return;
    }

    if (!owner->testStatus(ObjectStatus::Destroy)) {
        for (auto& v : _Deps) {
            auto obj = v.first;
            if (!v.second && obj && obj->isAttachedToDocument()
                && obj->getDocument() == owner->getDocument()) {
                obj->_removeBackLink(owner);
                obj->_removeBackLinkProp(getName(), owner);
            }
        }
    }

    _Deps.clear();
    _XLinks.clear();
    _LinkRestored = false;
}

void PropertyXLinkContainer::getLinks(std::vector<App::DocumentObject*>& objs,
                                      bool all,
                                      std::vector<std::string>* /*subs*/,
                                      bool /*newStyle*/) const
{
    for (auto& v : _Deps) {
        if (all || !v.second) {
            objs.push_back(v.first);
        }
    }
}

void PropertyXLinkContainer::getLinksProp(std::vector<std::pair<std::string, App::DocumentObject*>>& links,
                                          bool all) const
{
    for (auto& [pair, hidden] : _PropDeps) {
        if (all || !hidden) {
            links.push_back(pair);
        }
    }
}
