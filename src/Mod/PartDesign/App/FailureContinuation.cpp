// SPDX-License-Identifier: LGPL-2.1-or-later

#include "FailureContinuation.h"

#include <utility>
#include <vector>

#include <Precision.hxx>
#include <Standard_Failure.hxx>

#include <App/DocumentObject.h>
#include <App/PropertyLinks.h>
#include <App/RecomputeContinuation.h>
#include <Base/Console.h>
#include <Base/Placement.h>
#include <Base/Tools.h>
#include <Mod/Part/App/TopoShape.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureBase.h"

FC_LOG_LEVEL_INIT("PartDesign", true, true)

namespace PartDesign
{

namespace
{

/// The Body `obj` belongs to: a PartDesign feature's own (also a MultiTransform's
/// sub-transformation, which isn't in the Body's Group), else the Body whose Group holds it
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
    return Body::findBodyOf(obj);
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
 * unattached primitive), so the world geometry is the base's and the Placement is kept.
 */
void passThroughBase(Feature& feature)
{
    Part::TopoShape base;
    if (!feature.isDerivedFrom<FeatureBase>()) {
        // FeatureBase's base is outside the Body: it passes the empty shape through
        base = feature.getBaseTopoShape(true);
    }

    Part::TopoShape pass;
    if (!base.isNull()) {
        Base::Placement placement = feature.Placement.getValue();
        Base::Placement location(base.getTransform());
        if (location.isSame(placement, Precision::Confusion())) {
            pass = base;
        }
        else {
            pass = base.makeElementTransform(placement.inverse().toMatrix(),
                                             nullptr,
                                             Part::CheckScale::noScaleCheck,
                                             Part::CopyType::copy);
        }
    }

    // Inside the Recompute status, as an execute() writes it: the shape takes the feature's
    // placement and the Placement isn't overwritten (Part::Feature::onChanged)
    Base::ObjectStatusLocker<App::ObjectStatus, App::DocumentObject> exe(App::Recompute, &feature);
    feature.Shape.setValue(pass);
}

class BodyFailureContinuation: public App::RecomputeContinuation
{
public:
    bool continuesAfter(const App::DocumentObject* failed) const override
    {
        return bodyOf(failed) != nullptr;
    }

    App::AfterInputFailure decide(const App::DocumentObject* /*failed*/,
                                  const App::DocumentObject* dependant,
                                  std::string& why) const override
    {
        if (dependant->isDerivedFrom<Body>()) {
            // F6: the Body copies its Tip, which passed through
            return App::AfterInputFailure::Run;
        }
        if (!bodyOf(dependant)) {
            // F5: outside every Body, as upstream
            return App::AfterInputFailure::Skip;
        }
        if (dependant->isDerivedFrom<Feature>()) {
            // F3 runs in Feature::recompute, and afterFailure() passes through
            return App::AfterInputFailure::Run;
        }
        // F4: a sketch, datum, binder... in a Body
        return inputInError(dependant, why) ? App::AfterInputFailure::Fail
                                            : App::AfterInputFailure::Run;
    }

    void afterFailure(App::DocumentObject* failed) const override
    {
        auto feature = freecad_cast<Feature*>(failed);
        if (!feature || !Body::isSolidFeature(feature) || !feature->getFeatureBody()) {
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
};

}  // namespace

bool inputInError(const App::DocumentObject* owner, std::string& why)
{
    std::vector<App::Property*> props;
    owner->getPropertyList(props);
    bool isFeature = owner->isDerivedFrom<Feature>();
    std::vector<InputLink> links;
    for (auto prop : props) {
        if (!prop->isDerivedFrom<App::PropertyLinkBase>() || prop == &owner->ExpressionEngine) {
            continue;
        }
        if (isFeature) {
            auto feature = static_cast<const Feature*>(owner);
            if (prop == &feature->_Body) {
                continue;
            }
            if (prop == &feature->BaseFeature
                && Body::isSolidFeature(feature->BaseFeature.getValue())) {
                continue;
            }
        }
        links.clear();
        collectLinks(prop, links);
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
            return true;
        }
    }
    return false;
}

void registerFailureContinuation()
{
    App::setRecomputeContinuation(std::make_shared<BodyFailureContinuation>());
}

}  // namespace PartDesign
