// SPDX-License-Identifier: LGPL-2.1-or-later

#include "Studio.h"

#include <algorithm>
#include <cmath>
#include <cstring>
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
#include <App/MappedElement.h>
#include <Base/Console.h>
#include <Base/Exception.h>
#include <Mod/Part/App/PartFeature.h>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRep_Tool.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <gp_Circ.hxx>
#include <gp_Dir.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>

#include "Body.h"
#include "Feature.h"
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

/// history.deps[member] and history.wholeReads[member] (readHistory()): the members of other
/// Bodies that member, a row of lane, reads, directly or through other objects (a spreadsheet, a
/// Part feature, a link, a MultiTransform's step, another studio's Body), first its reads first
/// (linkReads(member), or what a drop plans it to read). The Group order covers its own Body's (a
/// link to a later member of its own Body, from Python, is left to the Group order)
void readMember(History& history,
                std::size_t lane,
                App::DocumentObject* member,
                const std::vector<App::DocumentObject*>& first)
{
    const auto& laneOf = history.laneOf;
    auto& found = history.deps[member];
    found.clear();
    history.wholeReads.erase(member);
    std::unordered_set<const App::DocumentObject*> seen {member};
    std::vector<App::DocumentObject*> readers;
    bool top = true;
    while (top || !readers.empty()) {
        App::DocumentObject* reader = top ? member : readers.back();
        if (!top) {
            readers.pop_back();
        }
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

        std::ranges::for_each(top ? first : linkReads(reader), visit);
        top = false;
    }
}

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

    for (std::size_t lane = 0; lane < lanes.size(); ++lane) {
        for (auto member : lanes[lane]) {
            readMember(history, lane, member, linkReads(member));
        }
    }
    const auto& deps = history.deps;

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

void retraceReadsOfDeleted(const App::DocumentObject& deleted);

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
    // Module start-up's one hook (AppPartDesign.cpp): a delete's re-target too (ops#640 rank 4)
    App::GetApplication().signalDeletedObject.connect(retraceReadsOfDeleted);

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

/// A read between Bodies that a drop breaks: reader would read read, a later member
struct BrokenRead
{
    App::DocumentObject* reader = nullptr;
    App::DocumentObject* read = nullptr;
    /// The refusal's text; empty: nothing is broken
    std::string text;
};

/// The first read between Bodies that order breaks and history's sequence kept (a loop's broken
/// reads stay broken), with the refusal's text, or none. A Body read whole is read as its last solid
/// feature in the planned Groups: the lane ownLane's rows become ownPlan (review prlocal632-r1 T1:
/// a solid dropped below a binder of its Body became its last solid, and the list put it back)
BrokenRead brokenRead(const History& history,
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
                return {reader,
                        read,
                        "'" + labelOf(reader) + "' uses '" + labelOf(read) + "' of '" + bodyOf(read)
                            + "': it can't go above it"};
            }
            return {reader,
                    read,
                    "'" + labelOf(reader) + "' of '" + bodyOf(reader) + "' uses '" + labelOf(read)
                        + "': it can't go below it"};
        }
    }
    return {};
}

/// a and b, two elements, are the same for what a reference reads of them: a face on the same
/// plane facing the same way (a face an operation trimmed or holed keeps its plane), an edge with
/// the same ends on the same line or circle (a trimmed edge is shorter: an attachment to it, by
/// its start or its length, would move; review sff13-r1 Sonnet rl1), the same point. An element an
/// operation generated from another (a fillet's edge from the sharp edge) is none of these, and
/// isn't traced back to it. Other surfaces and curves aren't compared: false
bool sameCarrier(const TopoDS_Shape& a, const TopoDS_Shape& b)
{
    constexpr double angular = 1e-9;
    if (a.IsNull() || b.IsNull() || a.ShapeType() != b.ShapeType()) {
        return false;
    }
    // The shapes' own tolerances, at least the modelling one (review sff13-r1 Opus T3: a fixed
    // 1e-7 refused at 4 m where the shapes agree within their tolerance)
    double tolerance = std::max(Precision::Confusion(), std::max(BRep_Tool::MaxTolerance(a, TopAbs_VERTEX), BRep_Tool::MaxTolerance(b, TopAbs_VERTEX)));
    switch (a.ShapeType()) {
        case TopAbs_FACE: {
            BRepAdaptor_Surface sa(TopoDS::Face(a));
            BRepAdaptor_Surface sb(TopoDS::Face(b));
            if (sa.GetType() != GeomAbs_Plane || sb.GetType() != GeomAbs_Plane) {
                return false;
            }
            gp_Pln pa = sa.Plane();
            gp_Pln pb = sb.Plane();
            // The faces' own normals: a FlatFace attachment takes its direction from them
            gp_Dir na = pa.Axis().Direction();
            gp_Dir nb = pb.Axis().Direction();
            if (a.Orientation() == TopAbs_REVERSED) {
                na.Reverse();
            }
            if (b.Orientation() == TopAbs_REVERSED) {
                nb.Reverse();
            }
            if (!na.IsEqual(nb, angular) || pa.Distance(pb.Location()) >= tolerance) {
                return false;
            }
            // a lies within b: every corner of a is on b (a face trimmed or holed by a later
            // feature is part of the earlier one; a pattern's or a mirror's copy on the same
            // plane is elsewhere: review sff13-r1 Opus T1)
            for (TopExp_Explorer it(a, TopAbs_VERTEX); it.More(); it.Next()) {
                BRepClass_FaceClassifier classifier(
                    TopoDS::Face(b),
                    BRep_Tool::Pnt(TopoDS::Vertex(it.Current())),
                    tolerance
                );
                if (classifier.State() != TopAbs_IN && classifier.State() != TopAbs_ON) {
                    return false;
                }
            }
            return true;
        }
        case TopAbs_EDGE: {
            BRepAdaptor_Curve ca(TopoDS::Edge(a));
            BRepAdaptor_Curve cb(TopoDS::Edge(b));
            // The same ends, in either direction
            gp_Pnt a0 = ca.Value(ca.FirstParameter());
            gp_Pnt a1 = ca.Value(ca.LastParameter());
            gp_Pnt b0 = cb.Value(cb.FirstParameter());
            gp_Pnt b1 = cb.Value(cb.LastParameter());
            bool ends = (a0.Distance(b0) < tolerance && a1.Distance(b1) < tolerance)
                || (a0.Distance(b1) < tolerance && a1.Distance(b0) < tolerance);
            if (!ends) {
                return false;
            }
            if (ca.GetType() == GeomAbs_Line && cb.GetType() == GeomAbs_Line) {
                return true;
            }
            if (ca.GetType() == GeomAbs_Circle && cb.GetType() == GeomAbs_Circle) {
                gp_Circ ra = ca.Circle();
                gp_Circ rb = cb.Circle();
                // With the same ends, the arcs' middles tell an arc from the rest of its circle
                gp_Pnt am = ca.Value((ca.FirstParameter() + ca.LastParameter()) / 2);
                gp_Pnt bm = cb.Value((cb.FirstParameter() + cb.LastParameter()) / 2);
                return ra.Location().Distance(rb.Location()) < tolerance
                    && std::abs(ra.Radius() - rb.Radius()) < tolerance
                    && ra.Axis().IsParallel(rb.Axis(), angular) && am.Distance(bm) < tolerance;
            }
            return false;
        }
        case TopAbs_VERTEX:
            return BRep_Tool::Pnt(TopoDS::Vertex(a)).Distance(BRep_Tool::Pnt(TopoDS::Vertex(b))) < tolerance;
        default:
            return false;
    }
}

/// The element of obj's shape, placed as the document shows it, or a null shape
TopoDS_Shape elementOf(const App::DocumentObject* obj, const std::string& element)
{
    try {
        auto shape = Part::Feature::getTopoShape(obj, Part::ShapeOption::ResolveLink | Part::ShapeOption::Transform);
        return shape.isNull() ? TopoDS_Shape() : shape.getSubShape(element.c_str(), true);
    }
    catch (const Base::Exception&) {
        return {};
    }
    catch (const Standard_Failure&) {
        return {};
    }
}

/// One element entry of a link property, read from another object (retraceRead())
struct Retrace
{
    App::PropertyLinkBase* prop = nullptr;
    std::size_t entry = 0;
    App::DocumentObject* top = nullptr;
    std::string sub;
};

/** The element entries of reader that name read, each read instead from the latest member of
 * read's Body in earlier (the rows above reader) that its element comes from (report 16, ops#647):
 * a sketch on a pad's top face that a fillet trimmed is on the pad's face, as Onshape traces a
 * reference to the feature that made it. The trace is the element's own history, faces to faces
 * (Part::Feature::getElementHistory); a member is a solid feature of that Body. Empty when an
 * entry has no such origin, when reader reads read otherwise (a whole object, a list without
 * subnames, an expression), or when the property keeps a re-target or a guess record on any
 * entry: the drop is then refused as before. Only AttachmentSupport-like properties
 * (PropertyLinkSub, PropertyLinkSubList) are rewritten
 */
std::vector<Retrace> retraceRead(App::DocumentObject* reader,
                                 App::DocumentObject* read,
                                 const std::unordered_set<const App::DocumentObject*>& earlier,
                                 const Body* body = nullptr)
{
    std::vector<Retrace> plan;
    // body: read's Body, given when read has just left its Group (a delete, ops#640 rank 4)
    const Body* readBody = body ? body : Body::findBodyOf(read);
    // Traced on computed shapes only: a touched reader or read could re-pin its other entries to
    // stale elements when the property is written again (review sff13-r1 Sonnet 4)
    auto stale = [](const App::DocumentObject* obj) {
        return obj->isTouched() || obj->mustExecute() == 1 || obj->isError();
    };
    if (!readBody || stale(reader) || stale(read)) {
        return {};
    }
    // The element, read from read's shape, comes from: a member made before reader, where it lies
    // on the same carrier (sameCarrier())
    auto origin = [&](const std::string& element, std::string& found) -> App::DocumentObject* {
        TopoDS_Shape now = elementOf(read, element);
        for (const auto& item : Part::Feature::getElementHistory(read, element.c_str(), true, true)) {
            if (item.obj == read || !item.obj || !earlier.count(item.obj)
                || Body::findBodyOf(item.obj) != readBody || !Body::isSolidFeature(item.obj)) {
                continue;
            }
            Data::IndexedName index = item.index;
            if (!index) {
                index = Part::Feature::getTopoShape(item.obj, Part::ShapeOption::NeedSubElement)
                            .getIndexedName(item.element);
            }
            if (index && sameCarrier(now, elementOf(item.obj, index.toString()))) {
                found = index.toString();
                return item.obj;
            }
        }
        return nullptr;
    };
    std::size_t reads = 0;
    std::vector<App::Property*> props;
    reader->getPropertyList(props);
    for (auto prop : props) {
        auto link = freecad_cast<App::PropertyLinkBase*>(prop);
        if (!link || prop->isDerivedFrom<App::PropertyExpressionContainer>()) {
            continue;
        }
        std::vector<App::DocumentObject*> objs;
        std::vector<std::string> subs;
        link->getLinks(objs, false, &subs, false);
        bool single = prop->isDerivedFrom<App::PropertyLinkSub>();
        bool list = prop->isDerivedFrom<App::PropertyLinkSubList>();
        auto anyRecord = [](const auto& records) {
            return std::ranges::any_of(records, [](const auto& record) { return !record.empty(); });
        };
        bool records = false;
        if (auto sub = freecad_cast<App::PropertyLinkSub*>(prop)) {
            records = anyRecord(sub->getRetargets()) || anyRecord(sub->getElementGuesses());
        }
        else if (auto subList = freecad_cast<App::PropertyLinkSubList*>(prop)) {
            records = anyRecord(subList->getRetargets()) || anyRecord(subList->getElementGuesses());
        }
        for (std::size_t i = 0; i < subs.size() || (subs.empty() && i < objs.size()); ++i) {
            auto top = single ? (objs.empty() ? nullptr : objs[0]) : (i < objs.size() ? objs[i] : nullptr);
            std::string sub = i < subs.size() ? subs[i] : std::string();
            if (!top) {
                continue;
            }
            // The entry's last object, as linkReads() reads it
            auto dot = sub.rfind('.');
            App::DocumentObject* last = top;
            if (dot != std::string::npos) {
                auto path = top->getSubObjectList(sub.c_str());
                last = !path.empty() && path.back() ? path.back() : top;
            }
            if (last != read) {
                continue;
            }
            ++reads;
            std::string element = dot == std::string::npos ? sub : sub.substr(dot + 1);
            // A sketch's projections are keyed by their object (Sketcher::SketchObject's
            // ExternalGeometry): a plain write would leave the keys and their constraints behind
            // (review sff13-r1 Opus T4), so a projection isn't traced
            bool projection = strcmp(prop->getName(), "ExternalGeometry") == 0
                || strcmp(prop->getName(), "ExternalGeo") == 0;
            if ((!single && !list) || records || element.empty() || projection) {
                return {};
            }
            std::string index;
            auto from = origin(element, index);
            if (!from) {
                return {};
            }
            // The same path, its last object and element replaced: (Pad, "Face3"), or
            // (Studio, "Body.Pad.Face3") for (Studio, "Body.Fillet.Face6")
            Retrace retrace {link, i, top, index};
            if (dot != std::string::npos) {
                if (dot == 0) {
                    return {};
                }
                auto objDot = sub.rfind('.', dot - 1);
                std::string prefix = objDot == std::string::npos ? std::string() : sub.substr(0, objDot + 1);
                if (top == read) {
                    return {};
                }
                retrace.sub = prefix + from->getNameInDocument() + "." + index;
            }
            else {
                retrace.top = from;
            }
            plan.push_back(std::move(retrace));
        }
    }
    // Every entry that reads read is traced, and nothing else of reader reads it directly
    auto direct = static_cast<std::size_t>(std::ranges::count(linkReads(reader), read));
    if (plan.size() != reads || direct != reads) {
        return {};
    }
    // A single-object property (PropertyLinkSub) holds one object: its entries traced to two
    // members can't be written (review sff13-r1 Sonnet rl2)
    for (const auto& a : plan) {
        for (const auto& b : plan) {
            if (a.prop == b.prop && a.prop->isDerivedFrom<App::PropertyLinkSub>() && a.top != b.top) {
                return {};
            }
        }
    }
    return plan;
}

/// Writes the entries retraceRead() planned, each property once, the other entries as they are
void writeRetraces(const std::vector<Retrace>& plan)
{
    std::vector<App::PropertyLinkBase*> props;
    for (const auto& retrace : plan) {
        if (std::ranges::find(props, retrace.prop) == props.end()) {
            props.push_back(retrace.prop);
        }
    }
    for (auto prop : props) {
        if (auto single = freecad_cast<App::PropertyLinkSub*>(prop)) {
            auto subs = single->getSubValues();
            App::DocumentObject* top = single->getValue();
            for (const auto& retrace : plan) {
                if (retrace.prop == prop && retrace.entry < subs.size()) {
                    top = retrace.top;
                    subs[retrace.entry] = retrace.sub;
                }
            }
            single->setValue(top, subs);
            continue;
        }
        // Without shadows: every entry's is taken again from its object's shape (the other
        // entries' unchanged, the new one's from the earlier member)
        auto list = static_cast<App::PropertyLinkSubList*>(prop);
        auto objs = list->getValues();
        auto subs = list->getSubValues(false);
        for (const auto& retrace : plan) {
            if (retrace.prop == prop && retrace.entry < objs.size() && retrace.entry < subs.size()) {
                objs[retrace.entry] = retrace.top;
                subs[retrace.entry] = retrace.sub;
            }
        }
        list->setValues(std::move(objs), std::move(subs));
    }
}

/** A solid feature being deleted (a Fillet): what reads its elements by name (a sketch on the face
 * it trimmed, a datum on it) reads instead the earlier member of its Body the element comes from,
 * by a drop's trace (retraceRead()), as Onshape keeps a sketch on the extrude's top face when the
 * fillet under it goes and moves it with that face afterwards (ops#640 rank 4, hands-on B3-1).
 * Run from signalDeletedObject, which Document::_removeObject() sends before it breaks the links
 * to the object, so the links are still there; the delete path has already taken the feature out
 * of its Body's Group (Body::removeObject()), so the Body is the one of its BaseFeature, and the
 * earlier members are its BaseFeature chain. Written at the delete, in its transaction: a saved
 * file computes as before (compat-neutral). Not on an undo, a redo or a rollback, which put the
 * links back themselves; not for solid features reading it (the Body reroutes those). A reader
 * whose entries have no such origin (an element the feature made, a projection) loses them as
 * before.
 */
void retraceReadsOfDeleted(const App::DocumentObject& deleted)
{
    auto* feature = const_cast<App::DocumentObject*>(&deleted);
    App::Document* doc = feature->getDocument();
    if (!doc || doc->isPerformingTransaction() || doc->testStatus(App::Document::Restoring)
        || doc->testStatus(App::Document::Recomputing) || App::GetApplication().isClosingAll()
        || !Body::isSolidFeature(feature)) {
        return;
    }
    try {
        App::DocumentObject* base = static_cast<PartDesign::Feature*>(feature)->BaseFeature.getValue();
        Body* body = Body::findBodyOf(feature);
        if (!body) {
            body = Body::findBodyOf(base);
        }
        if (!body || !base) {
            return;
        }
        std::unordered_set<const App::DocumentObject*> earlier;
        for (App::DocumentObject* member = base; member && body->hasObject(member)
             && earlier.insert(member).second;) {
            auto* solid = freecad_cast<PartDesign::Feature*>(member);
            member = solid ? solid->BaseFeature.getValue() : nullptr;
        }
        std::vector<Retrace> retraces;
        std::unordered_set<const App::DocumentObject*> seen;
        for (App::DocumentObject* reader : feature->getInList()) {
            if (!reader || reader == feature || !seen.insert(reader).second
                || reader->testStatus(App::ObjectStatus::Remove) || Body::isSolidFeature(reader)) {
                continue;
            }
            auto plan = retraceRead(reader, feature, earlier, body);
            retraces.insert(retraces.end(), plan.begin(), plan.end());
        }
        writeRetraces(retraces);
    }
    catch (const Base::Exception& e) {
        e.reportException();
    }
    catch (const Standard_Failure& e) {
        Base::Console().error("Re-targeting what reads %s: %s\n",
                              feature->getFullName().c_str(),
                              e.GetMessageString());
    }
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
    // Not const: a traced read changes what its reader reads (step 3)
    History history = readHistory(doc, studio);
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

    // 3. Across Bodies: no read between them is broken. A face, edge or vertex of a later member
    // that an earlier one made (a pad's top face a later fillet trimmed) is read from that one
    // instead, as Onshape traces a reference to the feature that made it (report 16, ops#647);
    // any other broken read refuses the drop. Planned on the history, written in step 5
    std::unordered_set<const App::DocumentObject*> earlier;
    std::vector<Retrace> retraces;
    std::unordered_map<App::DocumentObject*, std::vector<App::DocumentObject*>> plannedReads;
    for (;;) {
        auto broken = brokenRead(history, order, moved, lane, lanePlan);
        if (broken.text.empty()) {
            break;
        }
        earlier.clear();
        for (auto obj : order) {
            if (obj == broken.reader) {
                break;
            }
            earlier.insert(obj);
        }
        auto plan = retraceRead(broken.reader, broken.read, earlier);
        if (plan.empty() || std::ranges::any_of(retraces, [&broken](const Retrace& done) {
                return done.prop->getContainer() == broken.reader;
            })) {
            throw Base::ValueError(broken.text);
        }
        // What it reads once traced: its reads with read replaced by the earlier members
        auto& reads = plannedReads[broken.reader];
        reads = linkReads(broken.reader);
        for (const auto& retrace : plan) {
            auto it = std::ranges::find(reads, broken.read);
            if (it != reads.end()) {
                reads.erase(it);
            }
            auto path = retrace.sub.find('.') == std::string::npos
                ? std::vector<App::DocumentObject*>()
                : retrace.top->getSubObjectList(retrace.sub.c_str());
            reads.push_back(!path.empty() && path.back() ? path.back() : retrace.top);
        }
        readMember(history, history.laneOf.at(broken.reader), broken.reader, reads);
        // Still read another way (through a datum, a spreadsheet): refused
        if (history.deps[broken.reader].count(broken.read)) {
            throw Base::ValueError(broken.text);
        }
        retraces.insert(retraces.end(), plan.begin(), plan.end());
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

    // 5. Written: the traced reads, the Group, the order, the bar
    writeRetraces(retraces);
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
    // Without a hint, above the sketches and datums that wait below the bar with the held rows
    // they are made for (Body::waitsBelowBar()): one place for one state, as Onshape's (ops#640
    // rank 34, blind test F43). Only after the last solid before the first held row: a live solid
    // stays above the bar (a sketch made early, or another Body that isn't rolled back), or a drop
    // without a bar given (moveInStudio()) would roll that Body back
    std::size_t from = 0;
    for (std::size_t i = 0; i < first; ++i) {
        if (Body::isSolidFeature(sequence[i])) {
            from = i + 1;
        }
    }
    for (std::size_t i = from; i < first; ++i) {
        auto body = Body::findBodyOf(sequence[i]);
        if (body && body->waitsBelowBar(sequence[i])) {
            first = i;
            break;
        }
    }
    return first == 0 ? nullptr : sequence[first - 1];
}

}  // namespace PartDesign
