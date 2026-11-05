// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Studio.h"

#include <algorithm>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <App/Datums.h>
#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/GroupExtension.h>
#include <App/Part.h>
#include <Base/Exception.h>

#include "Body.h"
#include "FeatureMultiTransform.h"

namespace App
{
// Declared in DocumentObject.cpp (FreeCAD-CH ops#325), as Body.cpp does
AppExport std::vector<DocumentObject*> subnamePathReaders(const DocumentObject* obj,
                                                          std::vector<DocumentObject*>* links = nullptr);
}  // namespace App

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
    std::unordered_map<const App::DocumentObject*, std::size_t> bodyIndex;
    std::size_t total = 0;
    for (std::size_t i = 0; i < bodies.size(); ++i) {
        bodyIndex.emplace(bodies[i], i);
        lanes.push_back(rowsOf(bodies[i]));
        for (auto obj : lanes.back()) {
            laneOf.emplace(obj, i);
        }
        total += lanes.back().size();
    }

    // What reads a member through a subname path ((Studio, "Body1.Pad.Face1")) has the container
    // in its out-list, not the member: these readers, found from the member's side
    std::unordered_map<const App::DocumentObject*, std::vector<App::DocumentObject*>> pathReads;
    for (const auto& lane : lanes) {
        for (auto obj : lane) {
            for (auto reader : App::subnamePathReaders(obj)) {
                pathReads[reader].push_back(obj);
            }
        }
    }

    // deps[m]: the members of other Bodies that m reads. The Group order covers its own Body's
    // (a link to a later member of its own Body, from Python, is left to the Group order)
    std::unordered_map<const App::DocumentObject*, std::unordered_set<App::DocumentObject*>> deps;
    for (std::size_t lane = 0; lane < lanes.size(); ++lane) {
        for (auto member : lanes[lane]) {
            auto& found = deps[member];
            auto add = [&](App::DocumentObject* obj) {
                auto it = laneOf.find(obj);
                if (it != laneOf.end() && it->second != lane) {
                    found.insert(obj);
                }
            };
            std::unordered_set<const App::DocumentObject*> seen {member};
            std::vector<App::DocumentObject*> readers {member};
            while (!readers.empty()) {
                auto reader = readers.back();
                readers.pop_back();
                auto paths = pathReads.find(reader);
                if (paths != pathReads.end()) {
                    std::ranges::for_each(paths->second, add);
                }
                for (auto obj : reader->getOutList()) {
                    if (!obj || !seen.insert(obj).second) {
                        continue;
                    }
                    if (laneOf.count(obj)) {
                        add(obj);
                        continue;
                    }
                    if (auto body = bodyIndex.find(obj); body != bodyIndex.end()) {
                        // A whole Body (a Boolean's tool, a binder of the Body) reads its last
                        // solid feature, unless the link is a subname path into it, read above
                        bool viaPath = paths != pathReads.end()
                            && std::ranges::any_of(paths->second, [&](App::DocumentObject* read) {
                                   return laneOf.at(read) == body->second;
                               });
                        if (body->second != lane && !viaPath) {
                            if (auto last = bodies[body->second]->lastSolidFeature()) {
                                add(last);
                            }
                        }
                        continue;
                    }
                    // Containers (an App::Part, a group, an Origin) and origin features carry no
                    // geometry of a member, and another studio's Bodies are none of its rows;
                    // another object (a spreadsheet, a Part feature, a link) is read through
                    if (obj->hasExtension(App::GroupExtension::getExtensionClassTypeId())
                        || obj->isDerivedFrom<App::DatumElement>()
                        || obj->isDerivedFrom<Part::BodyBase>() || Part::BodyBase::findBodyOf(obj)) {
                        continue;
                    }
                    readers.push_back(obj);
                }
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
        auto it = hint ? std::find(sequence.begin(), sequence.begin() + first, hint) : sequence.begin();
        auto from = hint ? it + 1 : it;
        if ((!hint || it != sequence.begin() + first)
            && std::none_of(from, sequence.begin() + first, Body::isSolidFeature)) {
            return hint;
        }
    }
    return first == 0 ? nullptr : sequence[first - 1];
}

}  // namespace PartDesign
