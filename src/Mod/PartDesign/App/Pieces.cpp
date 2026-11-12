// SPDX-License-Identifier: LGPL-2.1-or-later

// Pieces and leftovers become parts at command time (FreeCAD-CH ops#654, P6p,
// notes/parts-design.md 10.12).

#include <algorithm>
#include <iterator>
#include <map>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <Precision.hxx>
#include <Standard_Failure.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <TopExp_Explorer.hxx>

#include <App/Document.h>
#include <App/DocumentObject.h>
#include <App/ElementNamingUtils.h>
#include <App/ElementSolver.h>
#include <App/GroupExtension.h>
#include <App/MappedName.h>
#include <App/NameTable.h>
#include <App/Part.h>
#include <App/PropertyStandard.h>
#include <Base/Tools.h>

#include "Body.h"
#include "Feature.h"
#include "FeatureApply.h"
#include "Pieces.h"
#include "Studio.h"
#include "StudioList.h"
#include "StudioOwner.h"

namespace PartDesign
{

// StudioList.cpp (slice 9; declared where used)
PartDesignExport bool isStudioPartPattern(const App::DocumentObject* obj);
// FeatureTransformed.cpp, StudioList.cpp (T1b): a feature pattern's instances that are no part's
PartDesignExport bool isStudioFeaturePattern(const App::DocumentObject* obj);
PartDesignExport Part::TopoShape studioPatternLeftovers(const App::DocumentObject* obj);
PartDesignExport bool isInstancePartPattern(const App::DocumentObject* obj);
// StudioList.cpp (10.13 gate round; declared where used)
PartDesignExport const char* studioOperationOf(const App::DocumentObject* owner);

/// Whether two solids join (FreeCAD-CH ops#654 10.13, skeptic 3): their fuse has fewer solids
/// than its inputs, so they share a face or overlap; an edge or a vertex in common is no join
/// (Onshape M2, R9 S1). The one contact test of an Add's merge, its leftovers and the dialog's
/// pre-fill (declared where used)
PartDesignExport bool studioSolidsJoin(const TopoDS_Shape& a, const TopoDS_Shape& b)
{
    if (a.IsNull() || b.IsNull()) {
        return false;
    }
    BRepExtrema_DistShapeShape distance(a, b);
    if (!distance.IsDone() || distance.Value() > Precision::Confusion()) {
        return false;
    }
    auto count = [](const TopoDS_Shape& shape) {
        int n = 0;
        for (TopExp_Explorer xp(shape, TopAbs_SOLID); xp.More(); xp.Next()) {
            ++n;
        }
        return n;
    };
    try {
        BRepAlgoAPI_Fuse fuse(a, b);
        if (!fuse.IsDone()) {
            return false;
        }
        return count(fuse.Shape()) < count(a) + count(b);
    }
    catch (const Standard_Failure&) {
        return false;
    }
}

namespace
{

const App::DocumentObject* commandEntry = nullptr;

/// The entries whose last compute found solids that are no part (10.12 amendment, "leftovers and
/// splits that appear without a command"): (document, entry) names, so a deleted entry is never
/// read. Due: the resync can make them (a first split, a further piece, a leftover); loud: a
/// source of the entry it must not touch (a record that finds nothing, no unique witness, the
/// nested debt), so the whole entry stays loud
using EntryKey = std::pair<std::string, std::string>;
std::set<EntryKey> duePieces;
std::set<EntryKey> loudPieces;

EntryKey entryKey(const App::DocumentObject* entry)
{
    return {entry->getDocument()->getName(), entry->getNameInDocument()};
}

void markPieces(const App::DocumentObject* entry, bool due)
{
    if (entry && entry->isAttachedToDocument() && entry->getDocument()) {
        (due ? duePieces : loudPieces).insert(entryKey(entry));
    }
}

std::string quoted(const App::DocumentObject* obj)
{
    return std::string("'") + (obj ? obj->Label.getValue() : "?") + "'";
}

/// The Body of doc whose part id is id, or null
Body* bodyWithId(App::Document* doc, const std::string& id)
{
    if (!doc || id.empty()) {
        return nullptr;
    }
    for (auto obj : doc->getObjectsOfType(Body::getClassTypeId())) {
        auto body = static_cast<Body*>(obj);
        if (studioPartId(body) == id) {
            return body;
        }
    }
    return nullptr;
}

/// shape (in body's frame) in the document's frame
Part::TopoShape inDocument(Part::TopoShape shape, const Body* body)
{
    if (!shape.isNull() && body) {
        shape.setPlacement(body->globalPlacement() * shape.getPlacement());
    }
    return shape;
}

/// Every mapped name of each face of source, expanded, per solid; then only the names on one
/// solid alone
std::vector<std::set<std::string>> uniqueNames(const Part::TopoShape& source)
{
    const std::vector<Part::TopoShape> solids = source.getSubTopoShapes(TopAbs_SOLID);
    std::vector<std::set<std::string>> out(solids.size());
    std::map<std::string, int> count;
    const auto& table = Data::NameTable::instance();
    for (std::size_t j = 0; j < solids.size(); ++j) {
        for (TopExp_Explorer it(solids[j].getShape(), TopAbs_FACE); it.More(); it.Next()) {
            const int index = source.findShape(it.Current());
            if (index <= 0) {
                continue;
            }
            for (const auto& [name, sids] :
                 source.getElementMappedNames(Data::IndexedName::fromConst("Face", index))) {
                out[j].insert(table.toPlain(name.toString()));
            }
        }
        for (const auto& name : out[j]) {
            ++count[name];
        }
    }
    for (auto& names : out) {
        for (auto it = names.begin(); it != names.end();) {
            it = count[*it] > 1 ? names.erase(it) : std::next(it);
        }
    }
    return out;
}

std::set<std::string> faceNames(const Part::TopoShape& shape)
{
    std::set<std::string> out;
    if (shape.isNull()) {
        return out;
    }
    const auto& table = Data::NameTable::instance();
    const int faces = static_cast<int>(shape.countSubShapes(TopAbs_FACE));
    for (int i = 1; i <= faces; ++i) {
        for (const auto& [name, sids] :
             shape.getElementMappedNames(Data::IndexedName::fromConst("Face", i))) {
            out.insert(table.toPlain(name.toString()));
        }
    }
    return out;
}

/// True if a top-level section of name from the from-th on carries ORD or a closed edge's CLS:
/// its place among its twins is an order, not a fact about the element
bool placedByOrder(const std::string& name, std::size_t from)
{
    const auto& sections = Data::MappedName::getDecodedMappedName(name);
    for (std::size_t i = from; i < sections.size(); ++i) {
        if (sections[i].hasMapperFlag(Data::MAPPER_FLAG_ORDERED)
            || sections[i].hasMapperFlag("CLS")) {
            return true;
        }
    }
    return false;
}

using Score = std::tuple<int, int, int>;

/// A record's witness against one solid's unique names: hits per tier. An entry a file of an
/// older build stored from an order (pieceWitness() no longer writes them: tier 1 placed by ORD
/// anywhere, tier 3 by its last section, the split's) counts for nothing
Score scoreOf(const std::vector<std::string>& witness, const std::set<std::string>& names)
{
    int hits[3] = {0, 0, 0};
    for (const auto& entry : witness) {
        if (entry.size() < 3 || entry[0] < '1' || entry[0] > '3') {
            continue;
        }
        const std::string name = entry.substr(2);
        if (entry[0] != '2') {
            const std::size_t sections = Data::MappedName::getDecodedMappedName(name).size();
            if (placedByOrder(name, entry[0] == '1' || sections == 0 ? 0 : sections - 1)) {
                continue;
            }
        }
        if (names.count(name)) {
            ++hits[entry[0] - '1'];
        }
    }
    return {hits[0], hits[1], hits[2]};
}

bool touchesAny(const Part::TopoShape& solid, const std::vector<Part::TopoShape>& bases, bool join)
{
    for (const auto& base : bases) {
        if (join ? studioSolidsJoin(solid.getShape(), base.getShape())
                 : [&]() {
                       BRepExtrema_DistShapeShape distance(solid.getShape(), base.getShape());
                       return distance.IsDone() && distance.Value() <= Precision::Confusion();
                   }()) {
            return true;
        }
    }
    return false;
}

/// Sets entry's command flag for a scope
class CommandGuard
{
public:
    explicit CommandGuard(const App::DocumentObject* entry)
        : previous(commandEntry)
    {
        commandEntry = entry;
    }
    ~CommandGuard()
    {
        commandEntry = previous;
    }
    CommandGuard(const CommandGuard&) = delete;
    CommandGuard& operator=(const CommandGuard&) = delete;

private:
    const App::DocumentObject* previous;
};

bool isDefaultName(const std::string& label)
{
    const std::string prefix = "Part ";
    if (label.size() <= prefix.size() || label.compare(0, prefix.size(), prefix) != 0) {
        return false;
    }
    return std::all_of(label.begin() + static_cast<long>(prefix.size()), label.end(), [](char c) {
        return c >= '0' && c <= '9';
    });
}

/// The steps or feature whose results are entry's split sources: each step of an owner outside
/// the piece Bodies it made; a Body member itself
std::vector<Feature*> resultsOf(App::DocumentObject* entry)
{
    std::vector<Feature*> out;
    if (Body::findBodyOf(entry)) {
        if (auto feature = freecad_cast<Feature*>(entry)) {
            out.push_back(feature);
        }
        return out;
    }
    for (auto step : StudioList::stepsOf(entry)) {
        Body* body = Body::findBodyOf(step);
        if (body && !(isPieceBody(body) && body->StudioMadeBy.getValue() == entry)) {
            out.push_back(step);
        }
    }
    return out;
}

}  // namespace

bool isPieceBody(const Body* body)
{
    return body && body->StudioMadeBy.getValue() && !body->StudioPieceWitness.getValues().empty();
}

std::vector<Body*> pieceRecords(const App::DocumentObject* maker, const std::string& parentId)
{
    std::vector<Body*> out;
    if (!maker || !maker->getDocument()) {
        return out;
    }
    for (auto obj : maker->getDocument()->getObjectsOfType(Body::getClassTypeId())) {
        auto body = static_cast<Body*>(obj);
        if (isPieceBody(body) && body->StudioMadeBy.getValue() == maker
            && parentId == body->StudioParentId.getValue()) {
            out.push_back(body);
        }
    }
    return out;
}

Part::TopoShape leftoverSolids(const App::DocumentObject* owner)
{
    if (!owner || Body::findBodyOf(owner)) {
        return {};
    }
    // A feature pattern's (T1b, 10.16 settled 3 and 2): a New original's instances, an Add over
    // parts' instances that join none of them
    if (isStudioFeaturePattern(owner)) {
        return studioPatternLeftovers(owner);
    }
    // A Linear or Polar part pattern's New (T2, no scope): every copy, each a part of its own
    if (isInstancePartPattern(owner) && studioScopeIds(owner).empty()) {
        return FeatureApply::toolOf(owner);
    }
    // Only an Add's tool has leftovers (H1a, R4): a Remove or an Intersect whose tool meets no
    // scope part takes nothing away there, and its tool is no material (10.13 gate round: seed 5
    // op 49's command made a Remove's cutter a part)
    if (std::string(studioOperationOf(owner)) != "Union") {
        return {};
    }
    std::vector<Part::TopoShape> bases;
    for (auto part : studioScopeOf(owner)) {
        Part::TopoShape shape = studioBaseAt(owner, part);
        if (!shape.isNull()) {
            bases.push_back(shape);
        }
    }
    if (bases.empty()) {
        return {};
    }
    Part::TopoShape tool = FeatureApply::toolOf(owner);
    if (tool.isNull()) {
        return {};
    }
    // An Add owner's tool solid is a leftover when it joins no scope part: face contact, never an
    // edge or a vertex (10.13, Onshape M2); a part mirror's copy when it touches none (R4)
    const bool join = !isStudioPartPattern(owner) || isInstancePartPattern(owner);
    std::vector<Part::TopoShape> kept;
    for (const auto& solid : tool.getSubTopoShapes(TopAbs_SOLID)) {
        if (!touchesAny(solid, bases, join)) {
            kept.push_back(solid);
        }
    }
    if (kept.empty()) {
        return {};
    }
    Part::TopoShape out = tool;  // its Tag, hasher and names
    out.makeElementCompound(
        kept,
        nullptr,
        Part::TopoShape::SingleShapeCompoundCreationPolicy::forceCompound
    );
    return out;
}

Part::TopoShape pieceSource(const Body* piece, std::string* why)
{
    auto fail = [why](const std::string& text) {
        if (why) {
            *why = text;
        }
        return Part::TopoShape();
    };
    if (!isPieceBody(piece)) {
        return fail(quoted(piece) + " is no piece");
    }
    App::DocumentObject* maker = piece->StudioMadeBy.getValue();
    const std::string parentId = piece->StudioParentId.getValue();
    if (parentId.empty()) {
        Part::TopoShape left = leftoverSolids(maker);
        if (left.isNull()) {
            return fail(quoted(maker) + " leaves no solid outside its merge scope: "
                        + quoted(piece) + " holds nothing");
        }
        return left;
    }
    Body* parent = bodyWithId(piece->getDocument(), parentId);
    if (!parent) {
        return fail("The part " + quoted(piece) + " was split from is gone");
    }
    const Feature* result = nullptr;
    if (Body::findBodyOf(maker)) {
        if (Body::findBodyOf(maker) == parent) {
            result = freecad_cast<const Feature*>(maker);
        }
    }
    else {
        result = StudioList::stepOf(maker, parent);
    }
    if (!result) {
        return fail(quoted(maker) + " no longer acts on " + quoted(parent) + ", which "
                    + quoted(piece) + " was split from");
    }
    if (result->isError()) {
        return fail(quoted(maker) + " failed in " + quoted(parent));
    }
    Part::TopoShape shape = result->Shape.getShape();
    if (shape.isNull() || !shape.hasSubShape(TopAbs_SOLID)) {
        return fail(quoted(maker) + " leaves nothing of " + quoted(parent));
    }
    return inDocument(shape, parent);
}

std::vector<std::string>
pieceWitness(const Part::TopoShape& source, int index, const Part::TopoShape& base)
{
    std::vector<std::string> out;
    const auto unique = uniqueNames(source);
    if (index < 0 || index >= static_cast<int>(unique.size())) {
        return out;
    }
    const std::set<std::string> baseNames = faceNames(base);
    for (const auto& name : unique[index]) {
        int tier = 1;
        std::size_t inherited = 0;  // the sections the parent's face had: E added the rest
        if (baseNames.count(name)) {
            tier = 2;
            inherited = std::string::npos;
        }
        else {
            const auto old = std::ranges::find_if(baseNames, [&name](const std::string& old) {
                return Data::NameAncestry::isPieceOf(name, old);
            });
            if (old != baseNames.end()) {
                // A piece of a closed face: its place on it isn't canonical (CLS), no witness
                if (name.find("CLS") != std::string::npos) {
                    continue;
                }
                tier = 3;
                inherited = Data::MappedName::getDecodedMappedName(*old).size();
            }
        }
        // A name E gave by an order that is no fact about the piece (ORD: the twins are told
        // apart only by their place among them, e.g. by u on a closed face, which counts from a
        // seam an edit can turn past them), no witness in any tier (review prline-b5-r1 R1)
        if (inherited != std::string::npos && placedByOrder(name, inherited)) {
            continue;
        }
        out.push_back(std::to_string(tier) + " " + name);
    }
    std::ranges::sort(out);
    return out;
}

PieceMatch matchPieces(const Part::TopoShape& source, const std::vector<Body*>& records)
{
    PieceMatch out;
    out.solids.assign(records.size(), -1);
    out.why.assign(records.size(), std::string());
    out.heldBy.assign(records.size(), -1);
    const auto unique = uniqueNames(source);
    const int count = static_cast<int>(unique.size());
    const bool split = !records.empty() && std::ranges::none_of(records, [](const Body* r) {
        return std::string(r->StudioParentId.getValue()).empty();
    });
    // A split whose source is one solid is gone (Onshape Q13, SPLIT_NO_CHANGE): no piece claims
    // the unsplit part, whatever the witness scores; picks of a piece resolve to the parent
    // (parts-design.md 10.12 amendment). Leftovers keep the rule below
    if (count == 1 && split) {
        for (std::size_t r = 0; r < records.size(); ++r) {
            out.why[r] = "The split that made " + quoted(records[r])
                + " is gone: it is the part it was cut from again";
        }
        return out;
    }
    std::vector<std::vector<Score>> scores(records.size());
    bool ambiguous = false;
    std::vector<Score> best(records.size(), Score {0, 0, 0});
    for (std::size_t r = 0; r < records.size(); ++r) {
        const auto witness = records[r]->StudioPieceWitness.getValues();
        int at = -1;
        int ties = 0;
        for (int j = 0; j < count; ++j) {
            Score score = scoreOf(witness, unique[j]);
            scores[r].push_back(score);
            if (score == Score {0, 0, 0}) {
                continue;
            }
            if (at < 0 || score > best[r]) {
                best[r] = score;
                at = j;
                ties = 0;
            }
            else if (score == best[r]) {
                ++ties;
            }
        }
        if (at < 0) {
            out.why[r] = "None of the faces that told " + quoted(records[r])
                + " apart is on a piece any more: it holds nothing";
        }
        else if (ties > 0) {
            ambiguous = true;
        }
        else {
            out.solids[r] = at;
        }
    }
    if (ambiguous) {
        for (std::size_t r = 0; r < records.size(); ++r) {
            out.solids[r] = -1;
            out.why[r] = "The faces that told " + quoted(records[r])
                + " apart lie on two pieces: which one it is can't be told";
        }
        return out;
    }
    // A partial unsplit (Onshape Q14e): a split source of two or more solids, each held by a
    // record, some by several. Quiet: the highest score holds it (a tie: the first record), the
    // others are absorbed into it, and picks of them resolve to it (10.12 amendment). With a
    // solid unheld the rule below stays (the maker is loud through unclaimedSplit anyway)
    const bool partial = split && count > 1 && [&]() {
        for (int j = 0; j < count; ++j) {
            if (std::ranges::find(out.solids, j) == out.solids.end()) {
                return false;
            }
        }
        return true;
    }();
    if (partial) {
        for (int j = 0; j < count; ++j) {
            int holder = -1;
            for (std::size_t r = 0; r < records.size(); ++r) {
                if (out.solids[r] == j
                    && (holder < 0 || best[r] > best[static_cast<std::size_t>(holder)])) {
                    holder = static_cast<int>(r);
                }
            }
            for (std::size_t r = 0; r < records.size(); ++r) {
                if (out.solids[r] == j && static_cast<int>(r) != holder) {
                    out.solids[r] = -1;
                    out.heldBy[r] = holder;
                    out.why[r] = quoted(records[r]) + "'s piece is "
                        + quoted(records[static_cast<std::size_t>(holder)])
                        + "'s now (its cut is gone): it holds nothing";
                }
            }
        }
        return out;
    }
    // One solid, several records: the strictly higher score claims it
    for (int j = 0; j < count; ++j) {
        std::vector<std::size_t> claim;
        for (std::size_t r = 0; r < records.size(); ++r) {
            if (out.solids[r] == j) {
                claim.push_back(r);
            }
        }
        if (claim.size() < 2) {
            continue;
        }
        auto top = std::ranges::max_element(claim, {}, [&best](std::size_t r) { return best[r]; });
        const Score high = best[*top];
        const auto highs = std::ranges::count_if(claim, [&](std::size_t r) {
            return best[r] == high;
        });
        for (auto r : claim) {
            if (highs == 1 && r == *top) {
                continue;
            }
            out.solids[r] = -1;
            out.why[r] = highs == 1
                ? quoted(records[r]) + "'s piece is " + quoted(records[*top])
                    + "'s now (the split is gone): it holds nothing"
                : "The split " + quoted(records[r])
                    + " came from is gone, and its piece is as much another's: it holds nothing";
        }
    }
    return out;
}

Part::TopoShape pieceShape(const Body* piece, std::string* why)
{
    Part::TopoShape source = pieceSource(piece, why);
    if (source.isNull()) {
        return {};
    }
    App::DocumentObject* maker = piece->StudioMadeBy.getValue();
    const auto records = pieceRecords(maker, piece->StudioParentId.getValue());
    const PieceMatch match = matchPieces(source, records);
    const auto at = std::ranges::find(records, piece) - records.begin();
    if (at >= static_cast<long>(records.size())) {
        return {};
    }
    if (match.solids[at] < 0) {
        if (why) {
            *why = match.why[at];
        }
        return {};
    }
    return source.getSubTopoShape(TopAbs_SOLID, match.solids[at] + 1);
}

std::string unclaimedSplit(const App::DocumentObject* maker,
                           const Body* part,
                           const Part::TopoShape& result)
{
    if (!maker || !part || result.isNull() || commandEntry == maker) {
        return {};
    }
    const int solids = static_cast<int>(result.countSubShapes(TopAbs_SOLID));
    if (solids < 2) {
        return {};
    }
    const std::string head = quoted(maker) + " splits " + quoted(part) + " into "
        + std::to_string(solids) + " pieces";
    const std::string partId = studioPartId(part);
    const auto records = pieceRecords(maker, partId);
    if (records.empty()) {
        // A first split: the resync makes both pieces (Onshape U1). Loud while the maker holds
        // records of a piece of this part whose own split is gone (the split amendment's skeptic
        // point 1, a nested split under a vanished outer one: debt)
        const App::Document* doc = maker->getDocument();
        const bool nested = std::ranges::any_of(
            doc->getObjectsOfType(Body::getClassTypeId()),
            [&](const App::DocumentObject* obj) {
                auto body = static_cast<const Body*>(obj);
                if (!isPieceBody(body) || body->StudioMadeBy.getValue() != maker) {
                    return false;
                }
                std::set<std::string> seen;
                std::string id = body->StudioParentId.getValue();
                while (!id.empty() && seen.insert(id).second) {
                    const Body* up = bodyWithId(const_cast<App::Document*>(doc), id);
                    id = up ? std::string(up->StudioParentId.getValue()) : std::string();
                    if (id == partId) {
                        return true;
                    }
                }
                return false;
            }
        );
        markPieces(maker, !nested);
        return head + ": open " + quoted(maker) + " and press OK to make them parts";
    }
    const PieceMatch match = matchPieces(result, records);
    std::set<int> claimed(match.solids.begin(), match.solids.end());
    claimed.erase(-1);
    if (static_cast<int>(claimed.size()) < solids) {
        // A further piece beside records that all hold theirs: a new ordinal (amendment point
        // 4); a record that finds nothing (no unique witness, a different cut) stays loud
        markPieces(maker, std::ranges::none_of(match.solids, [](int j) { return j < 0; }));
        return head + ", " + std::to_string(claimed.size()) + " are parts: open " + quoted(maker)
            + " and press OK";
    }
    for (std::size_t r = 0; r < records.size(); ++r) {
        if (match.solids[r] < 0 && match.heldBy[r] < 0) {
            markPieces(maker, false);  // its piece step fails: a command would delete the record
        }
    }
    return {};
}

void noteSplitHeld(App::DocumentObject* maker, const Body* part, const Part::TopoShape& result)
{
    if (!maker || !part || !maker->isAttachedToDocument()) {
        return;
    }
    const std::string id = studioPartId(part);
    const auto records = pieceRecords(maker, id);
    // What this source's entries should be: the part's id when its split is gone; for a partial
    // unsplit (Onshape Q14e), "<piece id>><holder id>" per absorbed piece, in the records' order
    std::vector<std::string> mine;
    if (!result.isNull() && !records.empty()) {
        const PieceMatch match = matchPieces(result, records);
        if (result.countSubShapes(TopAbs_SOLID) == 1) {
            if (std::ranges::all_of(match.solids, [](int j) { return j < 0; })) {
                mine.push_back(id);
            }
        }
        else {
            for (std::size_t r = 0; r < records.size(); ++r) {
                if (match.heldBy[r] >= 0) {
                    mine.push_back(studioPartId(records[r]) + ">"
                                   + studioPartId(records[static_cast<std::size_t>(match.heldBy[r])]));
                }
            }
        }
    }
    auto prop = freecad_cast<App::PropertyStringList*>(maker->getPropertyByName("StudioSplitLost"));
    std::vector<std::string> ids = prop ? prop->getValues() : std::vector<std::string>();
    // This source's entries now: its id, or an absorption of one of its records
    auto ofThis = [&](const std::string& entry) {
        if (entry == id) {
            return true;
        }
        const auto mark = entry.find('>');
        return mark != std::string::npos && std::ranges::any_of(records, [&](const Body* r) {
                   return studioPartId(r) == entry.substr(0, mark);
               });
    };
    std::vector<std::string> now;
    std::ranges::copy_if(ids, std::back_inserter(now), ofThis);
    if (now == mine) {
        return;  // unchanged: no reordering, so the resync's fixed point settles
    }
    std::erase_if(ids, ofThis);
    ids.insert(ids.end(), mine.begin(), mine.end());
    if (!prop) {
        prop = static_cast<App::PropertyStringList*>(maker->addDynamicProperty(
            "App::PropertyStringList",
            "StudioSplitLost",
            "Studio",
            "The parts whose split by this entry is gone, its pieces holding nothing (ops#654 P6p)",
            App::Prop_Hidden | App::Prop_Output | App::Prop_NoRecompute
        ));
    }
    prop->setValues(ids);
}

/// Writes the leftover records of owner whose solid is gone (StudioLeftoverLost, their ids; 10.12
/// amendment point 5, Onshape U2 and Q2c) when it changed: the tool merged back onto its part, the
/// new part is gone, its record kept for the tool's leaving again. consumedBy reads it (the Body
/// is a part nowhere), the projection takes it after the recompute (its Seen twin)
static void noteLeftoversLost(const App::DocumentObject* owner, const std::vector<std::string>& ids)
{
    auto entry = const_cast<App::DocumentObject*>(owner);
    auto prop =
        freecad_cast<App::PropertyStringList*>(entry->getPropertyByName("StudioLeftoverLost"));
    if (!prop && ids.empty()) {
        return;
    }
    if (prop && prop->getValues() == ids) {
        return;
    }
    if (!prop) {
        prop = static_cast<App::PropertyStringList*>(entry->addDynamicProperty(
            "App::PropertyStringList",
            "StudioLeftoverLost",
            "Studio",
            "The parts this entry made from a leftover whose solid is gone, merged back (ops#654 "
            "10.12)",
            App::Prop_Hidden | App::Prop_Output | App::Prop_NoRecompute
        ));
    }
    prop->setValues(ids);
}

std::string unclaimedLeftovers(const App::DocumentObject* owner)
{
    if (!owner || commandEntry == owner) {
        return {};
    }
    const Part::TopoShape left = leftoverSolids(owner);
    const auto records = pieceRecords(owner, std::string());
    if (left.isNull()) {
        // Every leftover merged back (Onshape U2: E OK, the new part gone): its record stays,
        // dormant, so leaving again gives the same id (Q2c)
        std::vector<std::string> lost;
        for (auto record : records) {
            lost.push_back(studioPartId(record));
        }
        noteLeftoversLost(owner, lost);
        return {};
    }
    const int solids = static_cast<int>(left.countSubShapes(TopAbs_SOLID));
    const PieceMatch match = matchPieces(left, records);
    // A record that finds nothing beside solids that are all claimed merged back; beside a solid
    // that is no part it is undecided (a different leftover, or no witness): none is dormant then,
    // and the entry stays loud below
    std::vector<std::string> lost;
    bool allClaimed = true;
    for (int j = 0; j < solids; ++j) {
        allClaimed = allClaimed && std::ranges::find(match.solids, j) != match.solids.end();
    }
    for (std::size_t r = 0; allClaimed && r < records.size(); ++r) {
        if (match.solids[r] < 0) {
            lost.push_back(studioPartId(records[r]));
        }
    }
    noteLeftoversLost(owner, lost);
    for (int j = 0; j < solids; ++j) {
        if (std::ranges::find(match.solids, j) == match.solids.end()) {
            markPieces(owner, true);  // the resync makes it a part (Onshape U2, H1a, R4)
            return "Solid " + std::to_string(j + 1)
                + " of the tool touches no part of the merge scope and is no part: open "
                + quoted(owner) + " and press OK to make it a new part";
        }
    }
    return {};
}

std::vector<App::DocumentObject*> takePiecesDue(App::Document* doc)
{
    std::vector<App::DocumentObject*> out;
    if (!doc) {
        return out;
    }
    const std::string name = doc->getName();
    for (auto it = duePieces.begin(); it != duePieces.end();) {
        if (it->first != name) {
            ++it;
            continue;
        }
        auto entry = doc->getObject(it->second.c_str());
        if (entry && !loudPieces.count(*it)) {
            out.push_back(entry);
        }
        it = duePieces.erase(it);
    }
    std::erase_if(loudPieces, [&name](const EntryKey& key) { return key.first == name; });
    return out;
}

const App::DocumentObject* piecesCommandEntry()
{
    return commandEntry;
}

std::vector<Body*> makePieces(App::DocumentObject* entry, std::string* why)
{
    std::vector<Body*> made;
    // A refusal leaves nothing it added and returns nothing (review prline-b5-r1 T3)
    auto fail = [why](const std::string& text) {
        if (why) {
            *why = text;
        }
        return std::vector<Body*>();
    };
    StudioList* list = entry ? StudioList::holding(entry) : nullptr;
    if (!list) {
        return fail(quoted(entry) + " is in no studio's history");
    }
    App::Document* doc = entry->getDocument();
    auto touchAll = [entry]() {
        entry->touch();
        for (auto step : StudioList::stepsOf(entry)) {
            step->touch();
        }
    };
    {
        CommandGuard guard(entry);
        touchAll();
        doc->recompute({}, /*force=*/true);
    }
    // A refusal after the recompute under the guard: computed again outside it, so that entry
    // stays loud (its checks passed meanwhile)
    auto refuse = [&](const std::string& text) {
        touchAll();
        doc->recompute({}, /*force=*/true);
        return fail(text);
    };

    struct Source
    {
        Part::TopoShape shape;
        Part::TopoShape base;
        Body* parent = nullptr;  // null: the leftovers
    };
    std::vector<Source> sources;
    for (auto result : resultsOf(entry)) {
        Body* body = Body::findBodyOf(result);
        if (!body || result->isError()) {
            continue;
        }
        Part::TopoShape shape = result->Shape.getShape();
        if (shape.isNull()
            || (shape.countSubShapes(TopAbs_SOLID) < 2
                && pieceRecords(entry, studioPartId(body)).empty())) {
            continue;
        }
        Part::TopoShape base = Body::findBodyOf(entry) ? result->getBaseTopoShape(true)
                                                       : studioBaseAt(entry, body);
        sources.push_back({inDocument(shape, body), base, body});
    }
    // An Add's leftover record that finds nothing stays (merged back, 10.12 amendment point 5,
    // Onshape Q2c): dormant until the tool leaves its part again, with the same id. A feature
    // pattern's whose instance is gone goes (fewer occurrences: its Body left empty)
    const bool keepLeftovers = !isStudioFeaturePattern(entry)
        && !(isInstancePartPattern(entry) && studioScopeIds(entry).empty());  // T2 New likewise
    std::vector<Body*> emptied;
    if (Part::TopoShape left = leftoverSolids(entry); !left.isNull()) {
        sources.push_back({left, Part::TopoShape(), nullptr});
    }
    else if (!keepLeftovers) {
        emptied = pieceRecords(entry, std::string());
    }

    // Every new piece and its witness first: a piece that can't become a part refuses the
    // command before anything changes
    struct NewPiece
    {
        std::string parentId;
        std::vector<std::string> witness;
    };
    std::vector<NewPiece> pieces;
    for (const auto& source : sources) {
        const std::string parentId = source.parent ? studioPartId(source.parent) : std::string();
        const auto records = pieceRecords(entry, parentId);
        const PieceMatch match = matchPieces(source.shape, records);
        const int solids = static_cast<int>(source.shape.countSubShapes(TopAbs_SOLID));
        for (std::size_t r = 0; r < records.size(); ++r) {
            // A gone split's records stay, and an absorbed piece's (a partial unsplit), so its
            // pieces come back with their ids when an edit cuts again (10.12 amendment, point 4)
            if (match.solids[r] < 0 && match.heldBy[r] < 0
                && (source.parent ? solids != 1 : !keepLeftovers)) {
                emptied.push_back(records[r]);
            }
        }
        for (int j = 0; j < solids && (solids > 1 || !source.parent); ++j) {
            if (std::ranges::find(match.solids, j) != match.solids.end()) {
                continue;
            }
            auto witness = pieceWitness(source.shape, j, source.base);
            if (witness.empty()) {
                return refuse("No face tells piece " + std::to_string(j + 1) + " of "
                              + (source.parent ? quoted(source.parent) : quoted(entry))
                              + " apart from the others: it can't become a part");
            }
            pieces.push_back({parentId, std::move(witness)});
        }
    }

    App::Part* studio = list->studio();
    auto counter = freecad_cast<App::PropertyInteger*>(entry->getPropertyByName("StudioPieceCount"));
    for (const auto& [parentId, witness] : pieces) {
        // Its id: "<entry>:<k>", k from the entry's counter, never reused
        if (!counter) {
            counter = static_cast<App::PropertyInteger*>(entry->addDynamicProperty(
                "App::PropertyInteger",
                "StudioPieceCount",
                "Studio",
                "The last ordinal of a part this entry made from a piece (ops#654 P6p)",
                App::Prop_Hidden
            ));
        }
        std::set<std::string> taken;
        for (auto obj : doc->getObjectsOfType(Body::getClassTypeId())) {
            taken.insert(studioPartId(static_cast<Body*>(obj)));
        }
        int k = counter->getValue();
        std::string id;
        do {
            ++k;
            id = std::string(entry->getNameInDocument()) + ":" + std::to_string(k);
        } while (taken.count(id));
        counter->setValue(k);
        auto body = static_cast<Body*>(doc->addObject("PartDesign::Body", "Body"));
        if (studio) {
            studio->getExtensionByType<App::GroupExtension>()->addObject(body);
        }
        body->StudioPartId.setValue(id);
        body->StudioParentId.setValue(parentId);
        body->StudioMadeBy.setValue(entry);
        body->StudioPieceWitness.setValues(witness);
        body->Label.setValue("Part 1");  // a default name: numbered by place (S3)
        made.push_back(body);
    }
    // A record without a solid goes when its Body holds nothing else; else it stays, failing
    for (auto body : emptied) {
        const auto group = body->Group.getValues();
        const bool alone = std::ranges::all_of(group, [](App::DocumentObject* member) {
            return StudioList::isStep(member);
        });
        if (!alone) {
            continue;
        }
        for (auto member : group) {
            const std::string name = member->getNameInDocument();
            body->removeObject(member);
            doc->removeObject(name.c_str());
        }
        doc->removeObject(body->getNameInDocument());
    }
    std::string text;
    if (!list->reconcile(&text)) {
        // What it added goes; the records it deleted come back with the caller's abort
        for (auto body : made) {
            for (auto member : body->Group.getValues()) {
                const std::string name = member->getNameInDocument();
                body->removeObject(member);
                doc->removeObject(name.c_str());
            }
            doc->removeObject(body->getNameInDocument());
        }
        return refuse(text);
    }
    touchAll();
    doc->recompute({}, /*force=*/true);
    return made;
}

void releasePiecesOf(App::DocumentObject* maker)
{
    App::Document* doc = maker ? maker->getDocument() : nullptr;
    if (!doc) {
        return;
    }
    for (auto obj : doc->getObjectsOfType(Body::getClassTypeId())) {
        auto body = static_cast<Body*>(obj);
        if (!isPieceBody(body) || body->StudioMadeBy.getValue() != maker) {
            continue;
        }
        const auto group = body->Group.getValues();
        if (std::ranges::all_of(group, [](App::DocumentObject* m) { return StudioList::isStep(m); })) {
            for (auto member : group) {
                const std::string name = member->getNameInDocument();
                body->removeObject(member);
                doc->removeObject(name.c_str());
            }
            doc->removeObject(body->getNameInDocument());
            continue;
        }
        auto gone = freecad_cast<App::PropertyBool*>(body->getPropertyByName("StudioMakerGone"));
        if (!gone) {
            gone = static_cast<App::PropertyBool*>(body->addDynamicProperty(
                "App::PropertyBool",
                "StudioMakerGone",
                "Studio",
                "The entry that made this part from a piece is gone (ops#654 P6p)",
                App::Prop_Hidden
            ));
        }
        gone->setValue(true);
    }
}

std::string pieceInheritedName(const Body* body)
{
    std::set<const Body*> seen;
    while (body && seen.insert(body).second) {
        const std::string parentId = body->StudioParentId.getValue();
        if (parentId.empty()) {
            return {};
        }
        body = bodyWithId(body->getDocument(), parentId);
        if (body && !isDefaultName(body->Label.getValue())) {
            return body->Label.getValue();
        }
    }
    return {};
}

}  // namespace PartDesign
