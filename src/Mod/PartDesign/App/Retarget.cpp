// SPDX-License-Identifier: LGPL-2.1-or-later

// The reorder's plan and the re-target rule (ops#127, notes/reorder-rollback-design.md 2.1 and
// section 3)

#include <algorithm>
#include <map>
#include <set>
#include <sstream>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/PropertyLinks.h>
#include <Base/Exception.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureBase.h"
#include "FeatureDressUp.h"
#include "FeatureSketchBased.h"
#include "Retarget.h"

namespace PartDesign
{

namespace
{

using Objects = std::vector<App::DocumentObject*>;

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

/// The planned state of a reorder: the new Group and each solid's new base
struct Plan
{
    Body& body;
    Objects group;
    Objects moved;
    std::map<App::DocumentObject*, App::DocumentObject*> newBase;  // solid -> its planned base
    std::vector<std::pair<App::DocumentObject*, App::DocumentObject*>> changes;  // (solid, base)

    explicit Plan(Body& b)
        : body(b)
    {}

    /// The planned out-edges of obj: its links, with the base-following links of a solid on its
    /// planned base (the Body itself and hidden links left out)
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
            link->getLinks(objs, false);
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

bool isFeatureBase(const App::DocumentObject* obj)
{
    return obj && obj->isDerivedFrom<PartDesign::FeatureBase>();
}

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

    // 5. The cycle check on the planned graph (N1 3.5): a refusal writes nothing
    auto cycle = plan.findCycle();
    if (!cycle.empty()) {
        std::ostringstream text;
        text << "This order makes a dependency cycle: ";
        for (std::size_t i = 0; i < cycle.size(); ++i) {
            text << (i ? " -> " : "") << nameOf(cycle[i]);
        }
        throw Base::ValueError(text.str());
    }

    // The Tip (step 7 of N1 2.1) is decided on the old order
    App::DocumentObject* tip = body.Tip.getValue();
    App::DocumentObject* newTip = tip;
    if (tip && movedSet.count(tip)) {
        if (!body.isRolledBack()) {
            newTip = nullptr;  // the new last solid, below
        }
        else {
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
    }
    bool tipToEnd = tip && movedSet.count(tip) && !body.isRolledBack();

    // 6. Write: Group once, then each changed base in the new chain order (the reroute of N1 2.2)
    body.Group.setValues(plan.group);
    for (const auto& [feature, base] : plan.changes) {
        reroute(feature, base);
    }

    // 7. The Tip keeps its place in the list
    if (tipToEnd) {
        body.rollToEnd();
    }
    else if (body.Tip.getValue() != newTip) {
        body.Tip.setValue(newTip);
    }
}

bool parkedReason(const App::DocumentObject* obj, std::string& why)
{
    // Parking comes with the re-target rule (N1 3.4 b)
    (void)obj;
    (void)why;
    return false;
}

}  // namespace PartDesign
