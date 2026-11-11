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
#include <App/PropertyPythonObject.h>
#include <App/RecomputeContinuation.h>
#include <Base/Console.h>
#include <Base/Placement.h>
#include <Base/Tools.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/TopoShape.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureAddSub.h"
#include "FeatureApply.h"
#include "FeatureBase.h"
#include "FeatureDressUp.h"
#include "FeatureSketchBased.h"
#include "FeatureTransformed.h"
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

/// Whether no solid feature comes before `feature` in its Body's Group
bool isFirstSolid(const Feature* feature)
{
    auto body = bodyOf(feature);
    if (!body) {
        return false;
    }
    for (auto obj : body->Group.getValues()) {
        if (obj == feature) {
            return true;
        }
        if (Body::isSolidFeature(obj)) {
            return false;
        }
    }
    return false;
}

/// Whether the feature's result on an empty base is exactly the empty shape: a subtractive feature
/// cuts from nothing, and a dress-up or a pattern changes a base that isn't there. So when it fails
/// there, its empty pass-through is what it would have made (ops#591, ops#127's park; decision 262
/// (1), design work\s9347\base-stop-design.md 5 (c)). Not a Python kind, whose result is its own
/// execute()'s, and not a Boolean, whose tools make material on nothing
bool emptyOnEmpty(const Feature& feature)
{
    if (freecad_cast<const App::PropertyPythonObject*>(feature.getPropertyByName("Proxy"))) {
        return false;
    }
    if (feature.isDerivedFrom<DressUp>() || feature.isDerivedFrom<Transformed>()) {
        return true;
    }
    // A studio feature's step (FreeCAD-CH ops#654 slice 9): a failed feature contributes nothing
    // (parts-design 10.9), so a New part whose feature fails holds nothing, never the shape of
    // the feature's last success
    if (feature.isDerivedFrom<FeatureApply>()) {
        return true;
    }
    // getAddSubType() only reads the type
    auto addSub = freecad_cast<const FeatureAddSub*>(&feature);
    if (!addSub) {
        return false;
    }
    // An Add with an empty merge scope fails "No merge scope selected" and makes no part, as
    // Onshape's red Add adds nothing (ops#640 rank 3a, R7(a)): its part computes without it
    if (addSub->EmptyMergeScope.getValue() && !addSub->MergeWithAll.getValue()) {
        return true;
    }
    return const_cast<FeatureAddSub*>(addSub)->getAddSubType() == FeatureAddSub::Type::Subtractive;
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

/// What the feature's kind would take as its base with BaseFeature null, as its links name it, not
/// as it resolves: a base through an App::Link resolves to nothing and is still a base (review
/// pr591s-r1b). A dress-up's Base, a pattern's first original, a profile's object or its sketch's
/// support, under ProfileBased::getBaseObject()'s filter (a Body or another Body's member is
/// never an implicit base: ops#308)
const App::DocumentObject* namedFallbackBase(const Feature& feature)
{
    if (auto dressUp = freecad_cast<const DressUp*>(&feature)) {
        return dressUp->Base.getValue();
    }
    if (auto transformed = freecad_cast<const Transformed*>(&feature)) {
        const auto& originals = transformed->Originals.getValues();
        return originals.empty() ? nullptr : originals.front();
    }
    auto profiled = freecad_cast<const ProfileBased*>(&feature);
    if (!profiled) {
        return nullptr;
    }
    auto body = bodyOf(&feature);
    auto implicit = [body](const App::DocumentObject* obj) -> const App::DocumentObject* {
        if (!obj || obj->isDerivedFrom<Body>()) {
            return nullptr;
        }
        auto other = bodyOf(obj);
        return other && other != body ? nullptr : obj;
    };
    auto profile = profiled->Profile.getValue();
    if (!profile || !profile->isDerivedFrom<Part::Part2DObject>()) {
        return implicit(profile);
    }
    return implicit(static_cast<const Part::Part2DObject*>(profile)->AttachmentSupport.getValue());
}

/// The feature brings no solid of its own (design notes\park-design.md 5 (N)): BaseFeature null,
/// and nothing named, or something whose shape never holds a solid
bool baseless(const Feature& feature)
{
    if (feature.BaseFeature.getValue()) {
        return false;
    }
    auto named = namedFallbackBase(feature);
    return !named || Feature::isDatum(named) || named->isDerivedFrom<Part::Part2DObject>()
        || named->isDerivedFrom<ShapeBinder>() || named->isDerivedFrom<SubShapeBinder>();
}

/** The feature's failure is the park's (design notes\park-design.md 5 (P), decision 275 (2)): it,
 * or a member in error reached from it through its Body's non-solid members (a sketch, a datum,
 * a binder, a MultiTransform's step; never a solid feature, never out of the Body), holds a
 * parking record: a reorder set a reference of it aside (ops#127), so it fails without running
 * (blocked()), and what it feeds fails naming it. A record counts only when its reference is to a
 * member after the feature and the feature is the earliest solid that reads its holder
 * (parkedAbove()): the feature was moved above what it needs with the inputs only it uses, and
 * what follows it was built without it. A feature that reads a member another feature's park
 * left red (the stock given a parked boss sketch's normal as its direction) isn't parked: it
 * stops the Body (reviews pr596-r1 and pr596s-r1, StockReadsParkedSketch). Read from links,
 * records and the Group, which only edits, the reorder, the undo and the import write, outside
 * recomputes; and the members reached are upstream of the feature, so their error is final when
 * it is asked
 */
bool parkedFailure(const Feature& feature)
{
    auto body = bodyOf(&feature);
    std::set<const App::DocumentObject*> seen;
    std::vector<const App::DocumentObject*> queue {&feature};
    std::vector<const App::DocumentObject*> holders;
    for (std::size_t i = 0; i < queue.size(); ++i) {
        const App::DocumentObject* obj = queue[i];
        if (!seen.insert(obj).second) {
            continue;
        }
        // The feature itself is asked as it fails, before its error is written
        if ((i == 0 || obj->isError()) && hasParkedReferences(obj)) {
            holders.push_back(obj);
        }
        forEachInput(obj, true, [&](const App::Property*, const std::vector<InputLink>& links) {
            for (const auto& link : links) {
                if (!Body::isSolidFeature(link.object) && bodyOf(link.object) == body) {
                    queue.push_back(link.object);
                }
            }
            return false;
        });
    }
    return !holders.empty() && parkedAbove(&feature, holders);
}

class BodyFailureContinuation: public App::RecomputeContinuation
{
public:
    /** A failed member is claimed, and its Body continues past it, only when what it passes on is
     * a real, current result (ops#579, decision 262; design work\s9347\base-stop-design.md)
     *
     * (S) A solid feature: its pass-through isn't the empty shape (decision 259), and its base is
     * Valid or itself a claimed failure, up the BaseFeature chain. One that passes the empty
     * shape is claimed when it makes nothing on nothing (a subtractive feature, a dress-up, a
     * pattern) or its failure is the park's (a reorder set a reference of it aside: a boss moved
     * above the Pad its sketch sits on), and it is first in its Body naming no base of its own,
     * or on a current base without a solid: the Body computes below it, as Onshape skips a
     * feature dragged above what it needs (ops#596, decisions 275 (2), 276, 281; design
     * notes\park-design.md). A FeatureBase, and a Pad failing for another reason, stop the Body.
     * (N) Any other member passes nothing on: it is claimed when none of its inputs is an
     * unclaimed failure.
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

    void afterStop(App::DocumentObject* stopped) const override
    {
        // F37 (ops#640): a stopped Body shows no part, as Onshape's failed feature contributes
        // nothing. Called for a Fail verdict or blocked(), not for a Body whose own execute()
        // failed. A stopped feature keeps its old output: nothing claimed reads it, and its Body,
        // stopped through it, shows nothing (in "Through" display ViewProviderBody shows the
        // Body's empty Shape in place of its members); a sketch or datum isn't a solid
        auto body = freecad_cast<Body*>(stopped);
        if (!body) {
            return;
        }
        // Only a Body whose Tip is an unclaimed failure (design D:1, F37: its part is gone, a
        // first feature with nothing to pass through). A Body stopped through another input with
        // a claimed or valid Tip (the Bracket that reads a stopped Panel through its Merge,
        // decision 257) keeps its last shape, as before
        const App::DocumentObject* tip = body->Tip.getValue();
        if (!tip || !tip->isError() || continuesAfter(tip)) {
            return;
        }
        try {
            body->writeStoppedShape();
        }
        catch (Base::Exception& e) {
            e.reportException();
        }
        catch (Standard_Failure& e) {
            FC_ERR("Clearing the shape of " << stopped->getFullName()
                                            << " failed: " << e.GetMessageString());
        }
        catch (std::exception& e) {
            FC_ERR("Clearing the shape of " << stopped->getFullName() << " failed: " << e.what());
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
                    // stays set while the recompute that fixes it writes its own shape. One that
                    // passes the empty shape (a parked lead) is no shape input of anything, and
                    // the references below it are judged as in a Body without it (design
                    // notes\park-design.md 5 (R), decision 275 (4))
                    out.push_back({feature,
                                   claimed && feature->isError() && feature->failurePassedThrough()
                                       && !feature->Shape.getShape().isNull(),
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
    /// the way has the same answer. An empty pass-through is real only for a kind that makes
    /// nothing on nothing (emptyOnEmpty()) or a parked feature (parkedFailure()), first in its
    /// Body naming no base (baseless()) or on a current base: a pocket or a boss parked above the
    /// first Pad is claimed, and the Body computes below it (ops#591, ops#596). The Pad after it
    /// decides its own claim on its own pass-through, so a failed first Pad there still stops the
    /// Body (review pr579-r4 R4-1)
    bool solidClaimed(const Feature* feature, Claims& claims) const
    {
        std::vector<const Feature*> chain;
        bool result = false;
        while (true) {
            if (passThroughIsEmpty(*feature)) {
                // (F): a FeatureBase's base is the outside object the Body itself names, and a
                // Body on a failed one stops (ops#579 find 1). (K) or (P): it makes nothing on
                // nothing, or its failure is the park's. A Pad that fails for any other reason
                // stops the Body, as Onshape fails the "Add" extrudes merged with a part that
                // vanished (decision 281)
                if (feature->isDerivedFrom<FeatureBase>()
                    || !(emptyOnEmpty(*feature) || parkedFailure(*feature))) {
                    break;
                }
                if (!feature->BaseFeature.getValue()) {
                    // (L) no solid before it (a transform added before another solid is linked
                    // to its base in its first execute(): review pr591s-r1), and (N) no base
                    // named in its links, which resolve or not (a fillet on a failed outside
                    // solid, or on one through a Link: reviews pr591-r1 T1 and pr591s-r1b)
                    result = isFirstSolid(feature) && baseless(*feature);
                    break;
                }
                // A linked base that holds no solid: current, or not, as any other
            }
            const Part::Feature* baseObject = feature->getBaseObject(true);
            if (!baseObject) {
                // A BaseFeature that isn't a Part feature
                break;
            }
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
                && Body::isSolidFeature(feature->BaseFeature.getValue()))
            // FreeCAD-CH ops#654 S2: a studio owner's bases are its parts' solids before it; a
            // claimed failure among them passed its own base through (Onshape F1)
            || (feature && prop == &feature->StudioBases)) {
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
