// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Studio.h"

#include <algorithm>
#include <iterator>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <App/Application.h>
#include <App/Datums.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/GroupExtension.h>
#include <App/Part.h>
#include <App/PropertyExpressionEngine.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <Base/Exception.h>

#include "Body.h"
#include "FeatureBase.h"
#include "FeatureMultiTransform.h"

namespace PartDesign
{

namespace
{

/// A MultiTransform's step: a member of the Body (added with body.newObject) shown and run as
/// part of its MultiTransform, not a feature of its own
bool isMultiTransformStep(const App::DocumentObject* obj)
{
    if (!freecad_cast<const Transformed*>(obj)) {
        return false;
    }
    return std::ranges::any_of(obj->getInList(), [obj](App::DocumentObject* in) {
        auto multi = freecad_cast<MultiTransform*>(in);
        return multi && std::ranges::find(multi->Transformations.getValues(), obj)
            != multi->Transformations.getValues().end();
    });
}

/// What reader reads, link entry by link entry (design section 3): an entry with a subname path
/// reads the path's last object (Support = (Studio, "A.BossA.Face3") reads BossA, not Studio nor all
/// of A); an entry without one (a face of the object, or none) and an expression read the object
/// itself. The links the out-list leaves out (hidden scope: a feature's _Body) are left out too
std::vector<App::DocumentObject*> linkReads(const App::DocumentObject* reader)
{
    std::vector<App::DocumentObject*> reads;
    std::vector<App::Property*> props;
    reader->getPropertyList(props);
    for (auto prop : props) {
        auto link = freecad_cast<App::PropertyLinkBase*>(prop);
        if (!link) {
            continue;
        }
        std::vector<App::DocumentObject*> objs;
        std::vector<std::string> subs;
        if (prop->isDerivedFrom<App::PropertyExpressionContainer>()) {
            link->getLinks(objs);
            reads.insert(reads.end(), objs.begin(), objs.end());
            continue;
        }
        link->getLinks(objs, false, &subs, false);
        // One object with all its subnames (PropertyLinkSub, PropertyXLink), or one per subname
        // (the lists); without subnames, or when they don't pair up, every object is read whole
        bool single = prop->isDerivedFrom<App::PropertyLinkSub>() || prop->isDerivedFrom<App::PropertyXLink>();
        bool paired = single ? objs.size() == 1 && !subs.empty() : !subs.empty() && objs.size() == subs.size();
        if (!paired) {
            reads.insert(reads.end(), objs.begin(), objs.end());
            continue;
        }
        for (std::size_t i = 0; i < subs.size(); ++i) {
            auto top = single ? objs[0] : objs[i];
            if (!top) {
                continue;
            }
            if (subs[i].find('.') == std::string::npos) {
                reads.push_back(top);
                continue;
            }
            auto path = top->getSubObjectList(subs[i].c_str());
            reads.push_back(!path.empty() && path.back() ? path.back() : top);
        }
    }
    return reads;
}

/// The rows of body: its Group without the MultiTransform steps
std::vector<App::DocumentObject*> rowsOf(const Body* body)
{
    std::vector<App::DocumentObject*> rows;
    for (auto obj : body->Group.getValues()) {
        if (obj && !isMultiTransformStep(obj)) {
            rows.push_back(obj);
        }
    }
    return rows;
}

}  // namespace

std::vector<Body*> studioBodies(App::Document* doc, App::Part* studio)
{
    std::vector<Body*> bodies;
    if (!doc) {
        return bodies;
    }
    for (auto obj : doc->getObjectsOfType(Body::getClassTypeId())) {
        auto body = static_cast<Body*>(obj);
        App::Part* part = nullptr;
        if (Part::BodyBase::studioOf(body, part) && part == studio) {
            bodies.push_back(body);
        }
    }
    return bodies;
}

namespace
{

constexpr const char* historyRankName = "HistoryRank";

/// A member's history key (design 3.3): its saved HistoryRank, else its object id
double historyKey(const App::DocumentObject* obj)
{
    if (auto rank = freecad_cast<App::PropertyFloat*>(obj->getPropertyByName(historyRankName))) {
        return rank->getValue();
    }
    return static_cast<double>(obj->getID());
}

/// Of two ready members, a goes first: the smaller key, then the older
bool historyBefore(const App::DocumentObject* a, const App::DocumentObject* b)
{
    double ka = historyKey(a);
    double kb = historyKey(b);
    if (ka != kb) {
        return ka < kb;
    }
    return a->getID() < b->getID();
}

/// The studio's rows (a lane per Body, its rows in Group order), what each reads in other Bodies,
/// and their order (studioSequence())
struct History
{
    std::vector<Body*> bodies;
    std::vector<std::vector<App::DocumentObject*>> lanes;
    std::unordered_map<const App::DocumentObject*, std::size_t> laneOf;
    std::unordered_map<const App::DocumentObject*, std::unordered_set<App::DocumentObject*>> deps;
    /// The lanes of the Bodies each member reads whole (in deps as their last solid feature)
    std::unordered_map<const App::DocumentObject*, std::unordered_set<std::size_t>> wholeReads;
    std::vector<App::DocumentObject*> sequence;
};

History readHistory(App::Document* doc, App::Part* studio)
{
    History history;
    history.bodies = studioBodies(doc, studio);
    const auto& bodies = history.bodies;
    auto& lanes = history.lanes;
    auto& laneOf = history.laneOf;
    std::size_t total = 0;
    for (std::size_t i = 0; i < bodies.size(); ++i) {
        lanes.push_back(rowsOf(bodies[i]));
        for (auto obj : lanes.back()) {
            laneOf.emplace(obj, i);
        }
        total += lanes.back().size();
    }

    // deps[m]: the members of other Bodies that m reads, directly or through other objects (a
    // spreadsheet, a Part feature, a link, a MultiTransform's step, another studio's Body). The
    // Group order covers its own Body's (a link to a later member of its own Body, from Python, is
    // left to the Group order)
    auto& deps = history.deps;
    for (std::size_t lane = 0; lane < lanes.size(); ++lane) {
        for (auto member : lanes[lane]) {
            auto& found = deps[member];
            std::unordered_set<const App::DocumentObject*> seen {member};
            std::vector<App::DocumentObject*> readers {member};
            while (!readers.empty()) {
                auto reader = readers.back();
                readers.pop_back();
                // Entry by entry: a subname path ((Studio, "Body1.Pad.Face1"), (C, "PadC1.Face3"))
                // reads its last object, never its top (a container, a Body) whole (reviews
                // props602-r1fix R1, props602-r2fix N1)
                auto visit = [&](App::DocumentObject* obj) {
                    if (!obj || !seen.insert(obj).second) {
                        return;
                    }
                    if (auto it = laneOf.find(obj); it != laneOf.end()) {
                        if (it->second != lane) {
                            found.insert(obj);
                        }
                        return;
                    }
                    if (auto body = freecad_cast<Body*>(obj)) {
                        // A whole Body (a Boolean's tool, a binder of the Body, a link to it, an
                        // expression of its shape) reads its last solid feature, in this studio or
                        // another (review props602-r1 T1)
                        auto last = body->lastSolidFeature();
                        if (!last) {
                            return;
                        }
                        if (auto it = laneOf.find(last); it != laneOf.end()) {
                            if (it->second != lane) {
                                found.insert(last);
                                history.wholeReads[member].insert(it->second);
                            }
                        }
                        else if (seen.insert(last).second) {
                            readers.push_back(last);
                        }
                        return;
                    }
                    // Containers (an App::Part, a group, an Origin) and origin features carry no
                    // geometry of their own; a MultiTransform's step (no row: what it reads, its
                    // MultiTransform reads) and any other object are read through
                    if (!isMultiTransformStep(obj)
                        && (obj->hasExtension(App::GroupExtension::getExtensionClassTypeId())
                            || obj->isDerivedFrom<App::DatumElement>()
                            || obj->isDerivedFrom<Part::BodyBase>())) {
                        return;
                    }
                    readers.push_back(obj);
                };
                std::ranges::for_each(linkReads(reader), visit);
            }
        }
    }

    // Kahn's algorithm over the lanes' heads: the smallest history key among the ready ones
    std::unordered_map<const App::DocumentObject*, std::size_t> remaining;
    std::unordered_map<const App::DocumentObject*, std::vector<App::DocumentObject*>> dependants;
    for (const auto& [member, reads] : deps) {
        remaining[member] = reads.size();
        for (auto read : reads) {
            dependants[read].push_back(const_cast<App::DocumentObject*>(member));
        }
    }
    std::vector<std::size_t> next(lanes.size(), 0);
    auto& sequence = history.sequence;
    sequence.reserve(total);
    while (sequence.size() < total) {
        std::size_t best = lanes.size();
        std::size_t forced = lanes.size();
        for (std::size_t i = 0; i < lanes.size(); ++i) {
            if (next[i] >= lanes[i].size()) {
                continue;
            }
            auto head = lanes[i][next[i]];
            auto smaller = [&](std::size_t other) {
                return other == lanes.size() || historyBefore(head, lanes[other][next[other]]);
            };
            if (remaining[head] == 0 && smaller(best)) {
                best = i;
            }
            if (smaller(forced)) {
                forced = i;
            }
        }
        // None ready: a loop of links between Bodies. Its oldest head goes first
        if (best == lanes.size()) {
            best = forced;
        }
        auto head = lanes[best][next[best]++];
        sequence.push_back(head);
        for (auto dependant : dependants[head]) {
            if (remaining[dependant] > 0) {
                --remaining[dependant];
            }
        }
    }
    return history;
}

}  // namespace

std::vector<App::DocumentObject*> studioSequence(App::Document* doc, App::Part* studio)
{
    return readHistory(doc, studio).sequence;
}

void saveHistoryOrder(const std::vector<App::DocumentObject*>& order)
{
    for (std::size_t i = 0; i < order.size(); ++i) {
        auto obj = order[i];
        auto rank = freecad_cast<App::PropertyFloat*>(obj->getPropertyByName(historyRankName));
        if (!rank) {
            rank = static_cast<App::PropertyFloat*>(obj->addDynamicProperty(
                "App::PropertyFloat",
                historyRankName,
                "Base",
                "The place in its part studio's history, saved by a drag in the Features list or "
                "an insert at the bar (ops#632)",
                App::Prop_Output | App::Prop_Hidden
            ));
        }
        if (rank->getValue() != static_cast<double>(i)) {
            rank->setValue(static_cast<double>(i));
        }
    }
}

void registerHistoryImport()
{
    // A copy, a paste or a merged file is new to its studio: listed as the newest, not at its
    // source's place (reviews prlocal632-r1 T3, prlocal632-r1s 1)
    auto forget = [](const std::vector<App::DocumentObject*>& objs, Base::XMLReader& /*reader*/) {
        for (auto obj : objs) {
            if (obj && obj->getDynamicPropertyByName(historyRankName)) {
                obj->removeDynamicProperty(historyRankName);
            }
        }
    };
    auto watch = [forget](App::Document& doc) {
        doc.signalImportObjects.connect(forget);
    };
    for (auto doc : App::GetApplication().getDocuments()) {
        watch(*doc);
    }
    App::GetApplication().signalNewDocument.connect([watch](const App::Document& doc, bool) {
        watch(const_cast<App::Document&>(doc));
    });
}

void saveInsertAtBar(App::Document* doc,
                     App::Part* studio,
                     const std::vector<App::DocumentObject*>& history,
                     App::DocumentObject* bar,
                     App::DocumentObject* feature)
{
    auto body = Body::findBodyOf(feature);
    if (!body) {
        return;
    }
    const auto rows = rowsOf(body);
    auto self = std::ranges::find(rows, feature);
    if (self == rows.end()) {
        return;  // a MultiTransform's step: no row
    }
    // Moved here from another Body of the studio: its old place goes
    std::vector<App::DocumentObject*> order;
    std::ranges::copy_if(history, std::back_inserter(order), [feature](auto obj) { return obj != feature; });
    auto place = [&order](const App::DocumentObject* obj) {
        return static_cast<std::ptrdiff_t>(std::ranges::find(order, obj) - order.begin());
    };
    const auto size = static_cast<std::ptrdiff_t>(order.size());
    std::ptrdiff_t at = bar ? std::min(place(bar) + 1, size) : 0;
    if (self + 1 != rows.end()) {
        at = std::min(at, place(*(self + 1)));
    }
    // Its Body's members before it that are listed below the bar (sketches and datums it doesn't
    // hold, after another Body's held rows) come up with it, unless one reads a row it would pass
    std::vector<App::DocumentObject*> block;
    std::ranges::copy_if(rows.begin(), self, std::back_inserter(block), [&](auto obj) {
        return place(obj) >= at && place(obj) < size;
    });
    if (!block.empty()) {
        const auto reads = readHistory(doc, studio).deps;
        bool passes = std::ranges::any_of(block, [&](auto obj) {
            auto it = reads.find(obj);
            return it != reads.end() && std::ranges::any_of(it->second, [&](auto read) {
                return place(read) >= at && std::ranges::find(block, read) == block.end();
            });
        });
        if (passes) {
            // After its Body's member before it instead
            block.clear();
            at = std::max(at, std::min(place(*(self - 1)) + 1, size));
        }
    }
    std::erase_if(order, [&block](auto obj) { return std::ranges::find(block, obj) != block.end(); });
    block.push_back(feature);
    order.insert(order.begin() + std::min(at, static_cast<std::ptrdiff_t>(order.size())), block.begin(), block.end());
    saveHistoryOrder(order);
}

namespace
{

/// The members reorderBody() carries with the solids of objs moved next to target (its step 2):
/// the non-solid members before a moved solid, up to the solid before it, that only moved members
/// use
std::unordered_set<const App::DocumentObject*> carriedBy(const Body& body,
                                                         const std::vector<App::DocumentObject*>& objs,
                                                         const App::DocumentObject* target)
{
    const auto& group = body.Group.getValues();
    std::unordered_set<const App::DocumentObject*> moved(objs.begin(), objs.end());
    for (auto obj : objs) {
        if (!Body::isSolidFeature(obj)) {
            continue;
        }
        auto pos = static_cast<std::size_t>(std::ranges::find(group, obj) - group.begin());
        for (bool grew = true; grew;) {
            grew = false;
            for (std::size_t i = std::min(pos, group.size()); i-- > 0;) {
                auto member = group[i];
                if (Body::isSolidFeature(member)) {
                    break;
                }
                if (member == target || moved.count(member)) {
                    continue;
                }
                bool onlyMoved = true;
                bool used = false;
                for (auto user : member->getInList()) {
                    if (user == &body || !body.hasObject(user)) {
                        continue;
                    }
                    used = true;
                    if (!moved.count(user)) {
                        onlyMoved = false;
                        break;
                    }
                }
                if (used && onlyMoved) {
                    moved.insert(member);
                    grew = true;
                }
            }
        }
    }
    return moved;
}

std::string labelOf(const App::DocumentObject* obj)
{
    return obj ? obj->Label.getValue() : "";
}

/// The first read between Bodies that order breaks and history's sequence kept (a loop's broken
/// reads stay broken), as the refusal's text, or empty. A Body read whole is read as its last solid
/// feature in the planned Groups: the lane ownLane's rows become ownPlan (review prlocal632-r1 T1:
/// a solid dropped below a binder of its Body became its last solid, and the list put it back)
std::string brokenRead(const History& history,
                       const std::vector<App::DocumentObject*>& order,
                       const std::unordered_set<const App::DocumentObject*>& moved,
                       std::size_t ownLane,
                       const std::vector<App::DocumentObject*>& ownPlan)
{
    std::unordered_map<const App::DocumentObject*, std::size_t> before;
    std::unordered_map<const App::DocumentObject*, std::size_t> now;
    for (std::size_t i = 0; i < history.sequence.size(); ++i) {
        before.emplace(history.sequence[i], i);
    }
    for (std::size_t i = 0; i < order.size(); ++i) {
        now.emplace(order[i], i);
    }
    auto lastSolid = [&](std::size_t lane) -> App::DocumentObject* {
        const auto& rows = lane == ownLane ? ownPlan : history.lanes[lane];
        auto it = std::find_if(rows.rbegin(), rows.rend(), Body::isSolidFeature);
        return it == rows.rend() ? nullptr : *it;
    };
    for (auto reader : order) {
        std::vector<App::DocumentObject*> reads;
        if (auto deps = history.deps.find(reader); deps != history.deps.end()) {
            reads.assign(deps->second.begin(), deps->second.end());
        }
        if (auto whole = history.wholeReads.find(reader); whole != history.wholeReads.end()) {
            for (auto lane : whole->second) {
                if (auto last = lastSolid(lane)) {
                    reads.push_back(last);
                }
            }
        }
        // The read listed first is named, whatever the order of the sets
        std::ranges::sort(reads, [&now](auto a, auto b) { return now.at(a) < now.at(b); });
        for (auto read : reads) {
            if (now.at(read) < now.at(reader) || before.at(read) > before.at(reader)) {
                continue;
            }
            auto bodyOf = [&history](const App::DocumentObject* obj) {
                return labelOf(history.bodies[history.laneOf.at(obj)]);
            };
            if (moved.count(reader)) {
                return "'" + labelOf(reader) + "' uses '" + labelOf(read) + "' of '" + bodyOf(read)
                    + "': it can't go above it";
            }
            return "'" + labelOf(reader) + "' of '" + bodyOf(reader) + "' uses '" + labelOf(read)
                + "': it can't go below it";
        }
    }
    return {};
}

/// order with the rows of moved taken out and put back, in their order, after the last other row
/// before at (an index of order)
std::vector<App::DocumentObject*> dropped(const std::vector<App::DocumentObject*>& order,
                                          const std::unordered_set<const App::DocumentObject*>& moved,
                                          const std::vector<App::DocumentObject*>& block,
                                          std::size_t at)
{
    std::vector<App::DocumentObject*> result;
    for (std::size_t i = 0; i < order.size(); ++i) {
        if (i == at) {
            result.insert(result.end(), block.begin(), block.end());
        }
        if (!moved.count(order[i])) {
            result.push_back(order[i]);
        }
    }
    if (at >= order.size()) {
        result.insert(result.end(), block.begin(), block.end());
    }
    return result;
}

}  // namespace

bool moveInStudio(App::Document* doc,
                  App::Part* studio,
                  const std::vector<App::DocumentObject*>& rows,
                  App::DocumentObject* after,
                  bool hinted,
                  App::DocumentObject* bar)
{
    const History history = readHistory(doc, studio);
    const auto& sequence = history.sequence;
    if (rows.empty()) {
        return false;
    }
    std::unordered_map<const App::DocumentObject*, std::size_t> index;
    for (std::size_t i = 0; i < sequence.size(); ++i) {
        index.emplace(sequence[i], i);
    }

    // 1. The rows: of one Body of the studio, and not its base feature
    std::size_t lane = history.lanes.size();
    std::unordered_set<const App::DocumentObject*> requested;
    for (auto row : rows) {
        if (!row || !index.count(row)) {
            throw Base::ValueError("Only the features of the part studio's bodies can be dragged");
        }
        if (row->isDerivedFrom<FeatureBase>()) {
            throw Base::ValueError("The base feature can't be moved");
        }
        std::size_t rowLane = history.laneOf.at(row);
        if (lane != history.lanes.size() && rowLane != lane) {
            throw Base::ValueError("Drag the features of one part at a time");
        }
        lane = rowLane;
        requested.insert(row);
    }
    if (after && !index.count(after)) {
        throw Base::ValueError("A drop goes after a feature of the part studio's history");
    }
    if (hinted && bar && !index.count(bar)) {
        throw Base::ValueError("The bar goes after a feature of the part studio's history");
    }
    Body* body = history.bodies[lane];
    const auto& own = history.lanes[lane];
    // The rows above the drop: those before after's place, after included
    const std::size_t at = after ? index.at(after) + 1 : 0;

    // 2. Inside the Body: after its last other row above the drop, else before its first
    auto groupPlan = [&](const std::unordered_set<const App::DocumentObject*>& moved,
                         App::DocumentObject*& target,
                         bool& targetAfter) {
        target = nullptr;
        targetAfter = true;
        for (auto obj : own) {
            if (!moved.count(obj) && index.at(obj) < at) {
                target = obj;
            }
        }
        if (!target) {
            auto first = std::ranges::find_if(own, [&moved](auto obj) { return !moved.count(obj); });
            if (first != own.end()) {
                target = *first;
                targetAfter = false;
            }
        }
        std::vector<App::DocumentObject*> block;
        std::vector<App::DocumentObject*> lanePlan;
        for (auto obj : own) {
            if (moved.count(obj)) {
                block.push_back(obj);
            }
            else {
                lanePlan.push_back(obj);
            }
        }
        auto it = target ? std::ranges::find(lanePlan, target) + (targetAfter ? 1 : 0) : lanePlan.end();
        lanePlan.insert(it, block.begin(), block.end());
        return lanePlan;
    };
    App::DocumentObject* target = nullptr;
    bool targetAfter = true;
    auto lanePlan = groupPlan(requested, target, targetAfter);
    bool groupMoves = lanePlan != own;
    std::vector<App::DocumentObject*> objs;
    std::ranges::copy_if(own, std::back_inserter(objs), [&requested](auto obj) {
        return requested.count(obj) > 0;
    });
    // What the reorder carries moves with them (rows only: a MultiTransform's step has none)
    std::unordered_set<const App::DocumentObject*> moved = requested;
    if (groupMoves) {
        for (auto obj : carriedBy(*body, objs, target)) {
            if (history.laneOf.count(obj)) {
                moved.insert(obj);
            }
        }
        lanePlan = groupPlan(moved, target, targetAfter);
        // With them the Group stays as it is (a Pad dropped next to its sketch)
        groupMoves = lanePlan != own;
    }
    std::vector<App::DocumentObject*> block;
    std::ranges::copy_if(own, std::back_inserter(block), [&moved](auto obj) { return moved.count(obj) > 0; });
    auto order = dropped(sequence, moved, block, at);

    // 3. Across Bodies: no read between them is broken
    auto broken = brokenRead(history, order, moved, lane, lanePlan);
    if (!broken.empty()) {
        throw Base::ValueError(broken);
    }

    // 4. The bar: the rows above it in the list as dropped (only requested rows move there)
    const bool rolledBack = std::ranges::any_of(history.bodies, [](const Body* b) { return b->isRolledBack(); });
    std::unordered_set<const App::DocumentObject*> aboveBar;
    if (rolledBack) {
        if (!hinted) {
            bar = studioBarAfter(sequence);
            // The row it followed moves: the bar stays after the row before it
            for (std::size_t i = bar ? index.at(bar) : 0; bar && requested.count(bar);) {
                bar = i > 0 ? sequence[--i] : nullptr;
            }
        }
        std::vector<App::DocumentObject*> dragged;
        std::ranges::copy_if(sequence, std::back_inserter(dragged), [&requested](auto obj) {
            return requested.count(obj) > 0;
        });
        for (auto obj : dropped(sequence, requested, dragged, at)) {
            if (!bar) {
                break;
            }
            aboveBar.insert(obj);
            if (obj == bar) {
                break;
            }
        }
    }

    // 5. Written: the Group, the order, the bar
    App::DocumentObject* oldTip = body->Tip.getValue();
    if (groupMoves) {
        body->reorderObject(objs, target, targetAfter);
        if (rowsOf(body) != lanePlan) {
            throw Base::RuntimeError("The reorder carried other features than planned: undo it");
        }
    }
    bool changed = groupMoves || order != sequence;
    if (changed) {
        saveHistoryOrder(order);
    }
    if (rolledBack) {
        App::DocumentObject* last = nullptr;
        for (auto obj : body->Group.getValues()) {
            if (aboveBar.count(obj) && Body::isSolidFeature(obj)) {
                last = obj;
            }
        }
        body->rollTo(last);
    }
    return changed || body->Tip.getValue() != oldTip;
}

std::vector<App::DocumentObject*> readsOfOtherBodies(const App::DocumentObject* member,
                                                     std::vector<const App::DocumentObject*>* via)
{
    std::vector<App::DocumentObject*> found;
    const Body* own = member ? Body::findBodyOf(member) : nullptr;
    if (!own) {
        return found;
    }
    auto add = [&](App::DocumentObject* obj, const App::DocumentObject* by) {
        found.push_back(obj);
        if (via) {
            via->push_back(by);
        }
    };
    std::unordered_set<const App::DocumentObject*> seen {member};
    // (reader, the member of own that reads through it)
    std::vector<std::pair<const App::DocumentObject*, const App::DocumentObject*>> readers {
        {member, member}
    };
    while (!readers.empty()) {
        auto [reader, by] = readers.back();
        readers.pop_back();
        for (auto obj : linkReads(reader)) {
            if (!obj || !seen.insert(obj).second) {
                continue;
            }
            if (auto body = freecad_cast<Body*>(obj)) {
                if (body != own) {
                    add(body, by);
                }
                continue;
            }
            if (auto body = Body::findBodyOf(obj)) {
                if (body != own) {
                    add(obj, by);
                }
                // Its own Body's sketch, datum or binder is read through; a solid feature's own
                // inputs are its own
                else if (!Body::isSolidFeature(obj)) {
                    readers.emplace_back(obj, obj);
                }
                continue;
            }
            // Containers (an App::Part, a group, an Origin) and origin features carry no geometry
            // of their own (studioSequence's rule)
            if (obj->hasExtension(App::GroupExtension::getExtensionClassTypeId())
                || obj->isDerivedFrom<App::DatumElement>() || obj->isDerivedFrom<Part::BodyBase>()) {
                continue;
            }
            readers.emplace_back(obj, by);
        }
    }
    return found;
}

void rollStudioTo(App::Document* doc, App::Part* studio, App::DocumentObject* member)
{
    const auto sequence = studioSequence(doc, studio);
    std::size_t end = 0;
    if (member) {
        auto it = std::ranges::find(sequence, member);
        if (it == sequence.end()) {
            throw Base::ValueError("The studio's bar goes after a feature of one of its bodies");
        }
        end = static_cast<std::size_t>(it - sequence.begin()) + 1;
    }
    std::unordered_set<const App::DocumentObject*> above(sequence.begin(), sequence.begin() + end);
    for (auto body : studioBodies(doc, studio)) {
        App::DocumentObject* last = nullptr;
        for (auto obj : body->Group.getValues()) {
            if (above.count(obj) && Body::isSolidFeature(obj)) {
                last = obj;
            }
        }
        body->rollTo(last);
    }
}

void rollStudioToEnd(App::Document* doc, App::Part* studio)
{
    for (auto body : studioBodies(doc, studio)) {
        body->rollToEnd();
    }
}

bool isStudioRolledBack(App::Document* doc, App::Part* studio)
{
    return std::ranges::any_of(studioBodies(doc, studio), [](const Body* body) {
        return body->isRolledBack();
    });
}

App::DocumentObject* studioBarAfter(const std::vector<App::DocumentObject*>& sequence,
                                    bool hinted,
                                    App::DocumentObject* hint)
{
    std::size_t first = sequence.size();
    for (std::size_t i = 0; i < sequence.size(); ++i) {
        auto body = Body::findBodyOf(sequence[i]);
        if (body && body->holds(sequence[i])) {
            first = i;
            break;
        }
    }
    if (hinted) {
        // The top: before the first row
        auto end = sequence.begin() + first;
        auto it = hint ? std::find(sequence.begin(), end, hint) : sequence.begin();
        if (!hint || it != end) {
            auto from = hint ? it + 1 : it;
            if (std::none_of(from, end, Body::isSolidFeature)) {
                return hint;
            }
        }
    }
    return first == 0 ? nullptr : sequence[first - 1];
}

}  // namespace PartDesign
