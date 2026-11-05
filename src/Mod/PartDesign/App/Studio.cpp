// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Studio.h"

#include <algorithm>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <App/Datums.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/GroupExtension.h>
#include <App/Part.h>
#include <App/PropertyExpressionEngine.h>
#include <App/PropertyLinks.h>
#include <Base/Exception.h>

#include "Body.h"
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

std::vector<App::DocumentObject*> studioSequence(App::Document* doc, App::Part* studio)
{
    const auto bodies = studioBodies(doc, studio);
    std::vector<std::vector<App::DocumentObject*>> lanes;
    std::unordered_map<const App::DocumentObject*, std::size_t> laneOf;
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
    std::unordered_map<const App::DocumentObject*, std::unordered_set<App::DocumentObject*>> deps;
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

    // Kahn's algorithm over the lanes' heads: the smallest id among the ready ones
    std::unordered_map<const App::DocumentObject*, std::size_t> remaining;
    std::unordered_map<const App::DocumentObject*, std::vector<App::DocumentObject*>> dependants;
    for (const auto& [member, reads] : deps) {
        remaining[member] = reads.size();
        for (auto read : reads) {
            dependants[read].push_back(const_cast<App::DocumentObject*>(member));
        }
    }
    std::vector<std::size_t> next(lanes.size(), 0);
    std::vector<App::DocumentObject*> sequence;
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
                return other == lanes.size() || head->getID() < lanes[other][next[other]]->getID();
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
    return sequence;
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
