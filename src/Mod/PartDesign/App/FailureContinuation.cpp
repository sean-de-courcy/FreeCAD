// SPDX-License-Identifier: LGPL-2.1-or-later

#include "FailureContinuation.h"

#include <map>
#include <optional>
#include <set>
#include <utility>
#include <vector>

#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopLoc_Location.hxx>

#include <App/DocumentObject.h>
#include <App/GroupExtension.h>
#include <App/PropertyLinks.h>
#include <App/RecomputeContinuation.h>
#include <Base/Console.h>
#include <Base/Placement.h>
#include <Base/Tools.h>
#include <Mod/Part/App/TopoShape.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureBase.h"
#include "Retarget.h"
#include "ShapeBinder.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

namespace PartDesign
{

namespace
{

/// The Body `obj` belongs to: a PartDesign feature's own (Feature::getFeatureBody(): its _Body,
/// else the Body whose Group holds it), else the Body whose Group holds it (found in its in-list). A MultiTransform's
/// sub-transformation is a member too (it is added with body.newObject); it isn't a solid
/// feature, so it doesn't pass through. The claim (continuesAfter()) and the pass-through
/// (afterFailure()) both use this one test.
Body* bodyOf(const App::DocumentObject* obj)
{
    if (!obj || obj->isDerivedFrom<Part::BodyBase>()) {
        return nullptr;
    }
    if (auto feature = freecad_cast<const Feature*>(obj)) {
        if (auto body = feature->getFeatureBody()) {
            return body;
        }
    }
    // The Body whose Group holds it: the Group link puts the Body in its members' in-lists, so
    // this costs O(in-list), not a walk of the document as Body::findBodyOf() (the tree asks
    // holds() for every item on every status pass, review of fork PR 119)
    for (auto user : obj->getInList()) {
        if (auto body = freecad_cast<Body*>(user); body && body->hasObject(obj)) {
            return body;
        }
    }
    return nullptr;
}

/// One link of a property: the object and whether it names elements (a non-empty sub)
struct InputLink
{
    App::DocumentObject* object;
    bool byElement;
};

bool hasElement(const std::vector<std::string>& subs)
{
    for (const auto& sub : subs) {
        if (!sub.empty()) {
            return true;
        }
    }
    return false;
}

void collectLinks(const App::Property* prop, std::vector<InputLink>& links)
{
    if (auto list = freecad_cast<const App::PropertyXLinkSubList*>(prop)) {
        for (const auto& link : list->getSubListValues()) {
            if (auto object = link.getValue()) {
                links.push_back({object, hasElement(link.getSubValues())});
            }
        }
    }
    else if (auto xlink = freecad_cast<const App::PropertyXLink*>(prop)) {
        if (auto object = xlink->getValue()) {
            links.push_back({object, hasElement(xlink->getSubValues())});
        }
    }
    else if (auto subList = freecad_cast<const App::PropertyLinkSubList*>(prop)) {
        const auto& objects = subList->getValues();
        const auto& subs = subList->getSubValues();
        for (std::size_t i = 0; i < objects.size(); ++i) {
            if (objects[i]) {
                links.push_back({objects[i], i < subs.size() && !subs[i].empty()});
            }
        }
    }
    else if (auto sub = freecad_cast<const App::PropertyLinkSub*>(prop)) {
        if (auto object = sub->getValue()) {
            links.push_back({object, hasElement(sub->getSubValues())});
        }
    }
    else if (auto list = freecad_cast<const App::PropertyLinkList*>(prop)) {
        for (auto object : list->getValues()) {
            if (object) {
                links.push_back({object, false});
            }
        }
    }
    else if (auto link = freecad_cast<const App::PropertyLink*>(prop)) {
        if (auto object = link->getValue()) {
            links.push_back({object, false});
        }
    }
    else if (auto base = freecad_cast<const App::PropertyLinkBase*>(prop)) {
        std::vector<App::DocumentObject*> objects;
        base->getLinks(objects, true);
        for (auto object : objects) {
            if (object) {
                links.push_back({object, false});
            }
        }
    }
}

/** Write the failed solid feature's base shape as its output (ops#126, N1 4.5.3, F1, F8)
 *
 * The base is re-expressed relative to the feature's own Placement when the two differ (an
 * unattached primitive, a Boolean, a feature that never ran), so the world geometry is the
 * base's and the Placement is kept.
 */
/// What a failed solid feature's pass-through is made from: its base, null when the base holds no
/// solid (getBaseTopoShape(true)). FeatureBase's base is outside the Body: it passes the empty
/// shape through
Part::TopoShape passThroughSource(const Feature& feature)
{
    if (feature.isDerivedFrom<FeatureBase>()) {
        return {};
    }
    return feature.getBaseTopoShape(true);
}

/// Whether a failed solid feature's pass-through is the empty shape. passThroughBase() writes it
/// from passThroughSource(), so the claim and the stop can't disagree with what it writes
/// (decision 259: the stop tested its own idea of empty, and a lead without a solid hid a failure,
/// review pr579-r4g T-R4G-1)
bool passThroughIsEmpty(const Feature& feature)
{
    return passThroughSource(feature).isNull();
}

void passThroughBase(Feature& feature)
{
    Part::TopoShape base = passThroughSource(feature);

    Part::TopoShape pass;
    if (!base.isNull()) {
        Base::Placement placement = feature.Placement.getValue();
        Base::Placement location(base.getTransform());
        if (location.isSame(placement, Precision::Confusion())) {
            pass = base;
        }
        else {
            // Writing the shape replaces its location with the Placement (below), so the base's
            // own location goes into the geometry too: P^-1 * L, from the base unlocated. P^-1
            // alone dropped L, and the base came out displaced by minus it (ops#487)
            Part::TopoShape unlocated = base.located(TopLoc_Location());
            pass = unlocated.makeElementTransform((placement.inverse() * location).toMatrix(),
                                                  nullptr,
                                                  Part::CheckScale::noScaleCheck,
                                                  Part::CopyType::copy);
        }
    }

    // Inside the Recompute status, as an execute() writes it: the shape takes the feature's
    // placement and the Placement isn't overwritten (Part::Feature::onChanged)
    Base::ObjectStatusLocker<App::ObjectStatus, App::DocumentObject> exe(App::Recompute, &feature);
    // Before the shape: setting it solves the references to it, which rule PT judges by this state
    // (ops#549)
    feature.setFailurePassedThrough(true);
    feature.Shape.setValue(pass);
}

/// The link properties of `owner` that are its inputs, passed to `use` with their links: not a
/// hidden link (a sibling's SiblingOf, whose primary may fail alone, ops#325) or a feature's _Body;
/// with `skipGroup`, not a container's Group either (a container computes nothing from its members,
/// as failedInputText() in Document.cpp has it; but a PartDesign::Boolean's tools are its Group).
/// ExpressionEngine is passed too: each caller decides about it
template<typename Use>
void forEachInput(const App::DocumentObject* owner, bool skipGroup, Use use)
{
    auto group = skipGroup ? owner->getExtensionByType<App::GroupExtension>(true) : nullptr;
    auto feature = freecad_cast<const Feature*>(owner);
    std::vector<App::Property*> props;
    owner->getPropertyList(props);
    std::vector<InputLink> links;
    for (auto prop : props) {
        auto link = freecad_cast<const App::PropertyLinkBase*>(prop);
        if (!link || link->getScope() == App::LinkScope::Hidden
            || (feature && prop == &feature->_Body) || (group && prop == &group->Group)) {
            continue;
        }
        links.clear();
        collectLinks(prop, links);
        if (use(prop, links)) {
            return;
        }
    }
}

class BodyFailureContinuation: public App::RecomputeContinuation
{
public:
    /** A failed member is claimed, and its Body continues past it, only when what it passes on is
     * a real, current result (ops#579, decision 262; design work\s9347\base-stop-design.md)
     *
     * (S) A solid feature: its pass-through isn't the empty shape (decision 259), and its base is
     * Valid or itself a claimed failure, up the BaseFeature chain. (N) Any other member passes
     * nothing on: it is claimed when none of its inputs is an unclaimed failure.
     *
     * Only what is upstream of `failed` is read. Document::recompute runs the topological order, so
     * all of it has run, or stands untouched, before `failed` runs, and nothing upstream is written
     * again before its dependants are judged: every site that asks gets the same answer. The Body
     * stop of decisions 254 and 255 (1) follows from it: a member whose chain runs through an
     * unclaimed failure fails at S1 naming its input, and is unclaimed too. The Body-wide walk that
     * stood for it read members off the chain, whose state changes during the recompute (reviews
     * pr579-r4h T-R4H-1 and T-R4H-2)
     */
    bool continuesAfter(const App::DocumentObject* failed) const override
    {
        Claims claims;
        return claimed(failed, claims);
    }

    App::AfterInputFailure decide(const App::DocumentObject* /*failed*/,
                                  const App::DocumentObject* dependant,
                                  std::string& why) const override
    {
        if (dependant->isDerivedFrom<Body>()) {
            // F6: the Body copies its Tip, which passed through
            return App::AfterInputFailure::Run;
        }
        if (bodyOf(dependant) && dependant->isDerivedFrom<Feature>()) {
            // F3 runs in Feature::recompute, and afterFailure() passes through
            return App::AfterInputFailure::Run;
        }
        // F4: a sketch, datum, binder... in a Body; and outside every Body, as F4 (ops#579; F5
        // left it out of the recompute, Valid on the old output): an element of the failed
        // feature is judged on its pass-through, any other link fails it
        return inputInError(dependant, why) ? App::AfterInputFailure::Fail
                                            : App::AfterInputFailure::Run;
    }

    void afterFailure(App::DocumentObject* failed) const override
    {
        auto feature = freecad_cast<Feature*>(failed);
        if (!feature || !Body::isSolidFeature(feature) || !bodyOf(feature)) {
            // A non-solid member keeps its old output, which nothing reads as a solid
            return;
        }
        try {
            passThroughBase(*feature);
        }
        catch (Base::Exception& e) {
            e.reportException();
        }
        catch (Standard_Failure& e) {
            FC_ERR("Pass-through of " << failed->getFullName()
                                      << " failed: " << e.GetMessageString());
        }
        catch (std::exception& e) {
            FC_ERR("Pass-through of " << failed->getFullName() << " failed: " << e.what());
        }
    }

    bool holds(const App::DocumentObject* obj) const override
    {
        // The roll-back bar (ops#127): a Body holds itself while rolled back, and what is after
        // its bar that nothing above uses
        if (auto body = freecad_cast<const Body*>(obj)) {
            return body->holds(obj);
        }
        auto body = bodyOf(obj);
        return body && body->holds(obj);
    }

    bool blocked(const App::DocumentObject* obj, std::string& why) const override
    {
        // A reference a reorder set aside (ops#127)
        return bodyOf(obj) && parkedReason(obj, why);
    }

    void shapeInputChain(const App::DocumentObject* target,
                         std::vector<ChainFeature>& out) const override
    {
        // Breadth first, so the nearest come first. Not getOutListRecursive(): expression links,
        // a sketch's external geometry and a Body's members after its Tip don't feed the shape
        // (ops#549 r2), and its order is by address
        out.clear();
        std::set<const App::DocumentObject*> seen;
        std::vector<const App::DocumentObject*> queue {target};
        std::vector<InputLink> links;
        auto follow = [&](const App::Property* prop) {
            links.clear();
            collectLinks(prop, links);
            for (const auto& link : links) {
                queue.push_back(link.object);
            }
        };
        for (std::size_t i = 0; i < queue.size(); ++i) {
            const App::DocumentObject* obj = queue[i];
            if (!obj || !obj->isAttachedToDocument() || !seen.insert(obj).second) {
                continue;
            }
            if (auto body = freecad_cast<const Body*>(obj)) {
                queue.push_back(body->Tip.getValue());
            }
            else if (auto feature = freecad_cast<const Feature*>(obj);
                     feature && Body::isSolidFeature(feature)) {
                // What its shape is now, not its Suppressed property: set before the recompute
                // that passes the base through, it describes no shape yet
                const bool suppressed = feature->passesBaseThrough();
                const bool claimed = bodyOf(feature) != nullptr;
                if (claimed || suppressed) {
                    // Failed while its output is the failure's pass-through: the error alone
                    // stays set while the recompute that fixes it writes its own shape
                    out.push_back({feature,
                                   claimed && feature->isError() && feature->failurePassedThrough(),
                                   suppressed});
                }
                std::vector<App::Property*> props;
                feature->getPropertyList(props);
                for (auto prop : props) {
                    if (!prop->isDerivedFrom<App::PropertyLinkBase>()
                        || prop == &feature->ExpressionEngine || prop == &feature->_Body
                        || static_cast<App::PropertyLinkBase*>(prop)->getScope()
                            == App::LinkScope::Hidden) {
                        continue;
                    }
                    follow(prop);
                }
            }
            else if (obj->isDerivedFrom<ShapeBinder>() || obj->isDerivedFrom<SubShapeBinder>()) {
                if (auto support = obj->getPropertyByName("Support")) {
                    follow(support);
                }
            }
            else if (auto linked = obj->getLinkedObject(true); linked && linked != obj) {
                queue.push_back(linked);
            }
        }
    }

private:
    /// What one continuesAfter() found: each answer, and nullopt while one is being asked further
    /// down, so a cycle, which can't reach a recompute, ends unclaimed
    using Claims = std::map<const App::DocumentObject*, std::optional<bool>>;

    bool claimed(const App::DocumentObject* failed, Claims& claims) const
    {
        if (auto it = claims.find(failed); it != claims.end()) {
            return it->second.value_or(false);
        }
        if (!bodyOf(failed)) {
            return false;
        }
        claims[failed] = std::nullopt;
        bool result = Body::isSolidFeature(failed)
            ? solidClaimed(static_cast<const Feature*>(failed), claims)
            : inputsCurrent(failed, claims);
        claims[failed] = result;
        return result;
    }

    /// (S), up the base chain: each base real (so non-null), and Valid or a claimed failure, whose
    /// shape is its own pass-through, made from its base by this same test. Every base in error on
    /// the way has the same answer
    bool solidClaimed(const Feature* feature, Claims& claims) const
    {
        std::vector<const Feature*> chain;
        bool result = false;
        while (true) {
            if (passThroughIsEmpty(*feature)) {
                break;
            }
            const Part::Feature* baseObject = feature->getBaseObject(true);
            if (!baseObject->isError()) {
                result = true;
                break;
            }
            // In error and not a solid feature of a Body (a Part feature set as BaseFeature from
            // Python): no rule claims it
            auto base = freecad_cast<const Feature*>(baseObject);
            if (!base || !Body::isSolidFeature(base) || !bodyOf(base)) {
                break;
            }
            if (auto it = claims.find(base); it != claims.end()) {
                result = it->second.value_or(false);
                break;
            }
            claims[base] = std::nullopt;
            chain.push_back(base);
            feature = base;
        }
        for (auto base : chain) {
            claims[base] = result;
        }
        return result;
    }

    /// (N): a sketch, datum, binder or a MultiTransform's sub-feature passes nothing on. One
    /// stopped by an unclaimed failure stays touched, and its readers elsewhere are marked at once
    /// (decision 250 (1)-(2)); one that failed for its own reason, or on a claimed input, is judged
    /// by decide(). Expressions count
    bool inputsCurrent(const App::DocumentObject* member, Claims& claims) const
    {
        bool current = true;
        forEachInput(member, true, [&](const App::Property*, const std::vector<InputLink>& links) {
            for (const auto& link : links) {
                if (link.object != member && link.object->isError()
                    && !claimed(link.object, claims)) {
                    current = false;
                    return true;
                }
            }
            return false;
        });
        return current;
    }
};

}  // namespace

bool inputInError(const App::DocumentObject* owner, std::string& why)
{
    auto feature = freecad_cast<const Feature*>(owner);
    bool inError = false;
    // A Boolean's tools are its Group: a failed one fails it (TestMerge.testFailedMergedFeature)
    forEachInput(owner, false, [&](const App::Property* prop, const std::vector<InputLink>& links) {
        if (prop == &owner->ExpressionEngine
            || (feature && prop == &feature->BaseFeature
                && Body::isSolidFeature(feature->BaseFeature.getValue()))) {
            return false;
        }
        for (const auto& link : links) {
            if (link.object == owner || !link.object->isError()) {
                continue;
            }
            if (link.byElement && Body::isSolidFeature(link.object) && bodyOf(link.object)) {
                // Its elements are judged on the pass-through shape
                continue;
            }
            why = std::string(prop->getName()) + " links to '" + link.object->Label.getValue()
                + "', which has an error";
            inError = true;
            return true;
        }
        return false;
    });
    return inError;
}

void registerFailureContinuation()
{
    App::setRecomputeContinuation(std::make_shared<BodyFailureContinuation>());
}

}  // namespace PartDesign
