// SPDX-License-Identifier: LGPL-2.1-or-later

#include "ElementSolver.h"

#include <algorithm>
#include <cmath>
#include <iterator>
#include <limits>
#include <locale>
#include <map>
#include <numbers>
#include <numeric>
#include <optional>
#include <set>
#include <sstream>
#include <tuple>
#include <utility>

#include <Base/Console.h>
#include <Base/Exception.h>

#include "ElementNamingUtils.h"
#include "MappedName.h"

FC_LOG_LEVEL_INIT("PropertyLinks", true, true)

namespace Data
{

namespace
{

// The single section \a section decoded. The decode cache keeps its entries for the whole
// process, so the reference stays valid.
const DecodedMappedSection& decodeSection(std::string_view section)
{
    static const DecodedMappedSection empty;
    const auto& decoded = MappedName::getDecodedMappedName(std::string(section));
    return decoded.empty() ? empty : decoded.front();
}

std::vector<std::string> sortedFlags(const DecodedMappedSection& section)
{
    std::vector<std::string> flags = section.mapperFlags;
    std::sort(flags.begin(), flags.end());
    flags.erase(std::unique(flags.begin(), flags.end()), flags.end());
    return flags;
}

// An index suffix as the op code: `_2`, `_3`, ... (`Data::indexSuffix`). PartDesign's patterns
// gave it to their instances before ops#55; the solver still treats it as a counter.
bool isCounterOpCode(const std::string& opCode)
{
    return opCode.size() > 1 && opCode[0] == '_'
        && std::all_of(opCode.begin() + 1, opCode.end(), [](char c) {
               return c >= '0' && c <= '9';
           });
}

// The op code of a pattern instance's section, `_;_;<pattern>;TRF;<k>;<type>;0;MOD;_` (Part's
// OpCodes::Transformed, ops#55). It carries the MOD flag, but it's no split: it says which
// instance of which pattern the element is in.
constexpr const char* patternInstanceOpCode = "TRF";

// The op code of a boundary section, `_;_;<object>;EXT;<i>;<type>;0;_;_` (Part's
// OpCodes::External, ops#56): the element came from another document through the object (a
// Link, a binder), and the name before it is that document's. Like an instance, it is a copy.
// The index i is 0 for a Link; for a binder it is the key of the support's file, which tells
// apart the supports from copies of one file (ops#112).
constexpr const char* boundaryOpCode = "EXT";

// The op code of a second side's section, `_;_;<feature>;CPY;2;<type>;0;MOD;_` (Part's
// OpCodes::Copy). A two-sided or Symmetric Pad's or Pocket's second side is built from the
// profile's edges again, and its names are the first side's with this section (ops#255); a
// Revolution's second side has it on the profile's names inside its own (ops#240). It carries
// the MOD flag, but the element is the first side's twin, no piece of it: like an instance, the
// second side is a copy, and its names share no ancestry with the first side's (PR 243 round 2).
constexpr const char* secondSideOpCode = "CPY";

// The copy a section makes of the element it ends, as the context its prefix is in: k for a
// pattern instance, EXT;i for a boundary, CPY;2 for a second side; empty for any other section
// (and for a pattern instance without a number, still a copy section: isCopySection()).
std::string copyIndex(const DecodedMappedSection& section)
{
    if (section.opCode == patternInstanceOpCode) {
        return section.index;
    }
    if (section.opCode == boundaryOpCode || section.opCode == secondSideOpCode) {
        return section.opCode + ";" + section.index;
    }
    return {};
}

// A section that makes a copy of the element it ends: a pattern instance's, a boundary's or a
// second side's.
bool isCopySection(const DecodedMappedSection& section)
{
    return section.opCode == patternInstanceOpCode || section.opCode == boundaryOpCode
        || section.opCode == secondSideOpCode;
}

// Starts and ends a copy's context in a node of NameAncestry: `\x1e<tag>;<k>\x1e` for a pattern
// instance, `\x1e<tag>;EXT;<i>\x1e` for a boundary, `\x1e<tag>;CPY;2\x1e` for a second side,
// before a name (see NameAncestry::ancestorsOf()).
// A control character starts no mapped name.
constexpr char contextMark = '\x1e';

// The copies a name is in: (tag, copyIndex()) of each of its top-level copy sections (TRF, EXT,
// CPY), in order.
std::vector<std::pair<std::string, std::string>> patternInstances(std::string_view name)
{
    std::vector<std::pair<std::string, std::string>> instances;
    for (auto section : NameAncestry::splitSections(name)) {
        const auto& decoded = decodeSection(section);
        if (isCopySection(decoded)) {
            instances.emplace_back(decoded.iterationTag, copyIndex(decoded));
        }
    }
    return instances;
}

}  // namespace

// ---------------------------------------------------------------------------------------------
// NameAncestry

NameAncestry::Key NameAncestry::intern(std::string_view name)
{
    auto it = _keys.find(name);
    if (it != _keys.end()) {
        return it->second;
    }
    auto key = static_cast<Key>(_names.size());
    const std::string& stored = _names.emplace_back(name);
    _sets.emplace_back();
    _children.emplace_back();
    _done.push_back(0);
    _keys.emplace(std::string_view(stored), key);
    return key;
}

const std::string& NameAncestry::name(Key key) const
{
    if (key >= _names.size()) {
        throw Base::ValueError("NameAncestry: unknown key");
    }
    return _names[key];
}

std::vector<std::string_view> NameAncestry::splitSections(std::string_view name)
{
    std::vector<std::string_view> sections;
    if (name.empty()) {
        return sections;
    }
    const char delimiter = *NAME_SECTION_DELIMINATOR;
    const char escape = *SUB_SECTION_ESCAPE_CHAR;
    std::size_t start = 0;
    for (std::size_t i = 0; i < name.size(); ++i) {
        // A delimiter after a caret belongs to an embedded name, at any depth.
        if (name[i] == delimiter && (i == 0 || name[i - 1] != escape)) {
            sections.push_back(name.substr(start, i - start));
            start = i + 1;
        }
    }
    sections.push_back(name.substr(start));
    return sections;
}

namespace
{

// Walks the lineage of \a name, how its element was made, calling \a visit(section, source) on
// each section until it returns true (then true). The lineage: the name's first section and,
// recursively, every section of every name a visited section links. The sections after the
// name's first are what later features did to it (MOD, a fusion's FUS), and connected elements
// name neighbours that tell pieces apart; neither is followed.
// A source is an innermost section of the first sections' chain: following the first section's
// linked names, and their first sections' linked names, down to a section made from no name. With
// \a sourcesOnly, only that chain is walked (the later sections of a linked name aren't).
bool walkLineage(
    std::string_view name,
    bool sourcesOnly,
    const std::function<bool(const DecodedMappedSection&, bool)>& visit
)
{
    std::function<bool(std::string_view, bool, bool)> walk =
        [&](std::string_view part, bool top, bool firstChain) {
            auto sections = NameAncestry::splitSections(part);
            for (std::size_t i = 0; i < sections.size(); ++i) {
                const bool chain = firstChain && i == 0;
                if (i > 0 && (top || sourcesOnly)) {
                    break;
                }
                const auto& decoded = decodeSection(sections[i]);
                bool embeds = false;
                for (const auto& embedded : decoded.linkedNames) {
                    embeds = embeds || (!embedded.empty() && embedded != Data::EMPTY_VALUE);
                }
                if (visit(decoded, chain && !embeds)) {
                    return true;
                }
                for (const auto& embedded : decoded.linkedNames) {
                    if (!embedded.empty() && embedded != Data::EMPTY_VALUE
                        && walk(embedded, false, chain)) {
                        return true;
                    }
                }
            }
            return false;
        };
    return walk(name, true, true);
}

bool hasTag(const DecodedMappedSection& section)
{
    return !section.iterationTag.empty() && section.iterationTag != Data::EMPTY_VALUE;
}

// The copies \a name's element is made in, in its whole lineage: its own top-level copy sections
// (patternInstances()) and those of every name its lineage links, at any depth, sorted.
// A later feature's element made from a copy's (a pocket slicing a Mirrored boss) carries the
// copy only inside a linked name (ops#168 review).
std::vector<std::pair<std::string, std::string>> copyContexts(std::string_view name)
{
    auto contexts = patternInstances(name);
    walkLineage(name, false, [&](const DecodedMappedSection& section, bool) {
        if (isCopySection(section)) {
            contexts.emplace_back(section.iterationTag, copyIndex(section));
        }
        return false;
    });
    std::sort(contexts.begin(), contexts.end());
    contexts.erase(std::unique(contexts.begin(), contexts.end()), contexts.end());
    return contexts;
}

// True if \a a and \a b are two pieces of one split element: both names are the element's
// sections, each followed by its own split's (NameAncestry::isPieceOf()). Two equal pieces of an
// edge share every source, but are no twins (ops#168 review).
bool piecesOfOne(std::string_view a, std::string_view b)
{
    const auto as = NameAncestry::splitSections(a);
    const auto bs = NameAncestry::splitSections(b);
    // Pieces of a split made before a copy (`X|<split A>|<TRF>`, `X|<split B>|<TRF>`) are
    // compared without the chain of copy sections both end in, as isPieceOf() does.
    std::size_t copies = 0;
    while (copies < as.size() && copies < bs.size()
           && as[as.size() - 1 - copies] == bs[bs.size() - 1 - copies]
           && isCopySection(decodeSection(as[as.size() - 1 - copies]))) {
        ++copies;
    }
    if (copies > 0 && copies < as.size() && copies < bs.size()) {
        auto head = [](std::string_view whole, std::string_view firstStripped) {
            return whole.substr(0, firstStripped.data() - whole.data() - 1);
        };
        return piecesOfOne(head(a, as[as.size() - copies]), head(b, bs[bs.size() - copies]));
    }
    std::size_t common = 0;
    while (common < as.size() && common < bs.size() && as[common] == bs[common]) {
        ++common;
    }
    if (common == 0 || common == as.size() || common == bs.size()) {
        return false;
    }
    const auto& last = as[common - 1];
    const std::string_view whole = a.substr(0, last.data() + last.size() - a.data());
    return NameAncestry::isPieceOf(a, whole) && NameAncestry::isPieceOf(b, whole);
}

// True if \a a and \a b are two marked pieces of one projection (ops#386): the names are the same
// but in one section, where both are a far cap's or far edge's piece (PRJ and MOD) told apart by
// their marks (connected elements) or their duplicate counters. They share every source, but are
// no twins: an up-to shell rebuilt with its faces in another order trades their marks, and the
// piece left at the old place is the element the reference held.
bool markedPiecesOfOne(std::string_view a, std::string_view b)
{
    const auto as = NameAncestry::splitSections(a);
    const auto bs = NameAncestry::splitSections(b);
    if (as.empty() || as.size() != bs.size()) {
        return false;
    }
    bool marked = false;
    for (std::size_t i = 0; i < as.size(); ++i) {
        if (as[i] == bs[i]) {
            continue;
        }
        if (marked) {
            return false;
        }
        const DecodedMappedSection& x = decodeSection(as[i]);
        const DecodedMappedSection& y = decodeSection(bs[i]);
        if (!x.hasMapperFlag(MAPPER_FLAG_PROJECTION) || !x.hasMapperFlag(MAPPER_FLAG_MODIFIED)
            || !y.hasMapperFlag(MAPPER_FLAG_PROJECTION) || !y.hasMapperFlag(MAPPER_FLAG_MODIFIED)
            || x.opCode != y.opCode || x.referenceIDs != y.referenceIDs
            || x.iterationTag != y.iterationTag || x.index != y.index
            || x.elementType != y.elementType || x.linkedNames != y.linkedNames) {
            return false;
        }
        marked = true;
    }
    return marked;
}

// An innermost source section (walkLineage()): its tag, element type and reference IDs.
struct SourceSection
{
    std::string tag;
    char type;
    std::vector<std::string> ids;
};

// The known innermost source sections of \a name: those with a tag and a reference ID. A source
// without either is unknown and left out, so that one such source doesn't hide the others (PR
// 149's review).
std::vector<SourceSection> knownSourcesOf(std::string_view name)
{
    std::vector<SourceSection> sources;
    walkLineage(name, true, [&](const DecodedMappedSection& section, bool source) {
        if (!source || !hasTag(section)) {
            return false;
        }
        std::vector<std::string> ids;
        for (const auto& id : section.referenceIDs) {
            if (!id.empty() && id != Data::EMPTY_VALUE) {
                ids.push_back(id);
            }
        }
        if (!ids.empty()) {
            sources.push_back({section.iterationTag, section.elementType, std::move(ids)});
        }
        return false;
    });
    return sources;
}

// The sources T1' asks of a candidate for \a oldName's element (PR 149's review): those of the
// inputs its maker made itself (a hole circle's cylinder, extruded by the pocket from the hole's
// circle), not those of an earlier feature's element it was made from (the block's bottom face
// the pocket cut), so that a redrawn block profile keeps the hole's circles. All the old name's
// known sources when no input is the maker's own (a pad's edge, made from sketch lines).
std::vector<SourceSection> requiredSourcesOf(std::string_view oldName)
{
    const std::string maker = NameAncestry::makerTag(oldName);
    const auto sections = NameAncestry::splitSections(oldName);
    std::vector<SourceSection> own;
    if (!maker.empty() && !sections.empty()) {
        for (const auto& input : decodeSection(sections.front()).linkedNames) {
            if (!input.empty() && input != Data::EMPTY_VALUE
                && NameAncestry::makerTag(input) == maker) {
                auto sources = knownSourcesOf(input);
                own.insert(own.end(),
                           std::make_move_iterator(sources.begin()),
                           std::make_move_iterator(sources.end()));
            }
        }
    }
    return own.empty() ? knownSourcesOf(oldName) : own;
}

// True if the element named \a names lost one of \a old's sources (ops#173): for some source
// geometry of the old name (a tag and type, e.g. a sketch's edges), no name of the element has a
// source of that tag and type sharing a reference ID with the old name's. A hole's circle comes
// from the cut face's sketch and its own circle (`g0`) of the hole's sketch; another hole of that
// sketch comes from `g1` there, so it lost the hole's sketch. A top face whose profile line was
// redrawn keeps the other lines, and a sketch vertex keeps its source while one of its lines does
// (`g1v2,g2v1` and `g1v2,g7v1`). Only known sources count (knownSourcesOf()): false when the old
// name has none; a name of the element without any can't be judged and keeps them.
bool lostASource(const std::vector<std::string>& names, const std::vector<SourceSection>& old)
{
    if (old.empty()) {
        return false;
    }
    auto sharesAnId = [](const SourceSection& a, const SourceSection& b) {
        return a.tag == b.tag && a.type == b.type
            && std::any_of(a.ids.begin(), a.ids.end(), [&](const auto& id) {
                   return std::find(b.ids.begin(), b.ids.end(), id) != b.ids.end();
               });
    };
    return std::none_of(names.begin(), names.end(), [&](const auto& name) {
        const auto sources = knownSourcesOf(name);
        if (sources.empty()) {
            return true;
        }
        // every source geometry (tag and type) of the old name keeps one of its IDs
        return std::all_of(old.begin(), old.end(), [&](const SourceSection& o) {
            return std::any_of(sources.begin(), sources.end(), [&](const SourceSection& s) {
                return std::any_of(old.begin(), old.end(), [&](const SourceSection& t) {
                    return t.tag == o.tag && t.type == o.type && sharesAnId(s, t);
                });
            });
        });
    });
}

// The nodes of a name's ancestry, as NameAncestry::ancestorsOf() walks it (a node's prefix, in a
// copy section's context, and the names embedded in its last section), in two sets. `outside`:
// the element itself and its earlier states. `projected`: the nodes reached through the names a
// projection section embeds (PR 243 round 5). A section with the PRJ flag
// (MAPPER_FLAG_PROJECTION) names the element an extrusion or a revolution makes at its far end
// from a profile element: a pad's top edge is `<bottom edge>|XTR|PRJ`. That is the element's
// partner, made at the same time, and both are in the result: never the element itself, nor a
// later state of it. A missing start-cap edge whose far-cap partner holds its name is no
// evidence that the partner is that edge (a two-sided pad built as one prism, then as two
// solids: the start cap's names are gone, side 1's far cap embeds them). Two partners of one
// profile element are related, though: the far cap's edge before and after its profile is
// redrawn. The connected elements are in neither (PR 243 round 7): a modified element's
// neighbours, per end vertex the vertex and one face of another input holding it, which is never
// the element itself; a base edge collinear with a profile line's extruded face lists that face.
// `derived` (ops#335, ops#358): the nodes reached outside projections only through a node of
// another element type than the name's, "GEN of a GEN", or through a GEN section (a
// generated element, MAPPER_FLAG_GENERATED) of any type. A section edge on a face that an edge
// generated (`<<g2>;XTR;F;GEN>;CUT;E;GEN`) reaches the edge g2 through the face; a Thickness's
// or an offset's copy of a vertex (`<V>;THK;V;GEN`) reaches the vertex through the GEN section,
// at a distance. Below a GEN section a name is a source of the element, below MOD, an unchanged
// prefix or a piece an earlier state. Such a node is in the element's lineage, but the element
// needn't be where the node was: relatedness, not identity. A node reached both ways is in
// `outside` and `derived`; `outside` decides.
struct AncestryNodes
{
    std::set<std::string> outside;
    std::set<std::string> derived;
    std::set<std::string> projected;

    // True if both hold a node reached the same way; derived counts as outside, since sharing
    // an ancestor is sharing it, whatever the path's types.
    bool meets(const AncestryNodes& other) const
    {
        auto shares = [](const std::set<std::string>& a, const std::set<std::string>& b) {
            return std::any_of(a.begin(), a.end(), [&](const std::string& node) {
                return b.count(node) > 0;
            });
        };
        return shares(outside, other.outside) || shares(outside, other.derived)
            || shares(derived, other.outside) || shares(derived, other.derived)
            || shares(projected, other.projected);
    }
};

// True if \a type is an element type a name's section can carry (a section without one leaves a
// path's type as it is).
bool knownElementType(char type)
{
    return type == 'V' || type == 'E' || type == 'F';
}

// True if \a section names an element generated from the names it holds (OCCT's Generated(), a
// new element at another place or of another type), not a later state of them.
bool isGenerated(const DecodedMappedSection& section)
{
    return section.hasMapperFlag(MAPPER_FLAG_GENERATED);
}

// \a type: the element type of the name the walk started from. \a changed: the path so far
// passed a node of another type or a GEN section.
void collectAncestryNodes(std::string_view name,
                          bool projected,
                          bool changed,
                          char type,
                          AncestryNodes& nodes)
{
    auto& set = projected ? nodes.projected : changed ? nodes.derived : nodes.outside;
    if (name.empty() || !set.emplace(name).second) {
        return;
    }
    std::string context;
    std::string_view node = name;
    while (!node.empty() && node.front() == contextMark) {
        auto end = node.find(contextMark, 1);
        if (end == std::string_view::npos) {
            break;
        }
        context.append(node.substr(0, end + 1));
        node.remove_prefix(end + 1);
    }
    auto sections = NameAncestry::splitSections(node);
    if (sections.empty()) {
        return;
    }
    const auto& last = decodeSection(sections.back());
    if (!type && knownElementType(last.elementType)) {
        type = last.elementType;
    }
    changed = changed || (knownElementType(last.elementType) && last.elementType != type)
        || isGenerated(last);
    if (sections.size() > 1) {
        auto prefixSize = static_cast<std::size_t>(sections.back().data() - node.data()) - 1;
        std::string prefix(node.substr(0, prefixSize));
        if (isCopySection(last)) {
            prefix = contextMark + last.iterationTag + ";" + copyIndex(last) + contextMark + prefix;
        }
        collectAncestryNodes(context + prefix, projected, changed, type, nodes);
    }
    const bool throughProjection = projected || last.hasMapperFlag(MAPPER_FLAG_PROJECTION);
    for (const auto& embedded : last.linkedNames) {
        if (!embedded.empty()) {
            collectAncestryNodes(context + embedded, throughProjection, changed, type, nodes);
        }
    }
}

// \a type: the element type of \a name's element, or 0 to take it from the first typed section
// (NameAncestry::reaches()).
AncestryNodes ancestryNodes(std::string_view name, char type = 0)
{
    AncestryNodes nodes;
    collectAncestryNodes(name, false, false, type, nodes);
    return nodes;
}

// The element types of a path from \a name down to \a ancestor that passes a node of another
// type or a GEN section and no projection's embedded names, e.g. `E<F<E`; empty if there is
// none. A step through a GEN section that keeps the type carries the section's op code after
// the type it reaches, e.g. `V<V (THK)` for a Thickness's copy of a vertex (ops#358). For the
// evidence text only: the first such path the walk finds. Each branch carries its start type, as
// collectAncestryNodes() does. \a elementType: as ancestryNodes()' type.
std::string derivedPathOf(std::string_view name, std::string_view ancestor, char elementType = 0)
{
    std::set<std::pair<std::string, bool>> visited;
    std::string path;
    // \a from: the type of the node whose GEN section led here, and \a op that section's op
    // code; 0 and empty when no GEN section did.
    std::function<bool(std::string_view, bool, char, char, const std::string&)> walk =
        [&](std::string_view at, bool changed, char type, char from, const std::string& op) {
        if (at.empty() || !visited.emplace(std::string(at), changed).second) {
            return false;
        }
        std::string context;
        std::string_view node = at;
        while (!node.empty() && node.front() == contextMark) {
            auto end = node.find(contextMark, 1);
            if (end == std::string_view::npos) {
                break;
            }
            context.append(node.substr(0, end + 1));
            node.remove_prefix(end + 1);
        }
        auto sections = NameAncestry::splitSections(node);
        if (sections.empty()) {
            return false;
        }
        const auto& last = decodeSection(sections.back());
        const char nodeType = knownElementType(last.elementType) ? last.elementType : '?';
        if (!type && knownElementType(nodeType)) {
            type = nodeType;
        }
        const std::size_t mark = path.size();
        auto step = [&]() {
            path += path.empty() ? std::string(1, nodeType) : std::string("<") + nodeType;
            if (!op.empty() && knownElementType(nodeType) && nodeType == from) {
                path += " (" + op + ")";
            }
        };
        step();
        if (changed && at == ancestor) {
            return true;
        }
        const bool generated = isGenerated(last);
        changed = changed || (knownElementType(nodeType) && nodeType != type) || generated;
        const std::string via = generated ? last.opCode : std::string();
        if (sections.size() > 1) {
            auto prefixSize = static_cast<std::size_t>(sections.back().data() - node.data()) - 1;
            std::string prefix(node.substr(0, prefixSize));
            if (isCopySection(last)) {
                prefix =
                    contextMark + last.iterationTag + ";" + copyIndex(last) + contextMark + prefix;
            }
            // An earlier state of the same element: no step in the path. Below a GEN section,
            // a source: a step.
            if (!generated) {
                path.resize(mark);
            }
            const char prefixFrom = generated ? nodeType : from;
            if (walk(context + prefix, changed, type, prefixFrom, generated ? via : op)) {
                return true;
            }
            if (!generated) {
                step();
            }
        }
        if (!last.hasMapperFlag(MAPPER_FLAG_PROJECTION)) {
            for (const auto& embedded : last.linkedNames) {
                if (!embedded.empty() && walk(context + embedded, changed, type, nodeType, via)) {
                    return true;
                }
            }
        }
        path.resize(mark);
        return false;
    };
    return walk(name, false, elementType, 0, std::string()) ? path : std::string();
}

// How a derivedPathOf() \a path holds the old element, for the evidence: "through another type"
// (`E<F<E`), or "through a generated copy" when every node keeps the type (`V<V (THK)`).
std::string derivedVia(const std::string& path)
{
    bool sameType = !path.empty();
    for (std::size_t i = 2; i < path.size() && sameType; ++i) {
        sameType = path[i - 1] != '<' || path[i] == path[0];
    }
    return sameType ? "through a generated copy" : "through another type";
}

}  // namespace

NameAncestry::Reach NameAncestry::reaches(std::string_view name,
                                          std::string_view ancestor,
                                          char type)
{
    const AncestryNodes nodes = ancestryNodes(name, type);
    const std::string node(ancestor);
    return nodes.outside.count(node)     ? Reach::SameType
        : nodes.derived.count(node)      ? Reach::Derived
        : nodes.projected.count(node)    ? Reach::Projected
                                         : Reach::None;
}

std::string NameAncestry::derivedPath(std::string_view name,
                                      std::string_view ancestor,
                                      char type)
{
    return derivedPathOf(name, ancestor, type);
}

std::vector<std::string> NameAncestry::sourceTags(std::string_view name)
{
    std::vector<std::string> tags;
    walkLineage(name, true, [&](const DecodedMappedSection& section, bool source) {
        if (source && hasTag(section)) {
            tags.push_back(section.iterationTag);
        }
        return false;
    });
    std::sort(tags.begin(), tags.end());
    tags.erase(std::unique(tags.begin(), tags.end()), tags.end());
    return tags;
}

std::vector<std::string> NameAncestry::sourceSections(std::string_view name)
{
    std::vector<std::string> sources;
    const bool unknown = walkLineage(name, true, [&](const DecodedMappedSection& section, bool source) {
        if (!source) {
            return false;
        }
        const auto& ids = section.referenceIDs;
        const bool hasId = std::any_of(ids.begin(), ids.end(), [](const std::string& id) {
            return !id.empty() && id != Data::EMPTY_VALUE;
        });
        if (!hasTag(section) || !hasId) {
            return true;  // a source without a tag or ID: the sources are unknown
        }
        std::string key = section.iterationTag + ";" + section.elementType + ";";
        for (const auto& id : ids) {
            key += id + ",";
        }
        sources.push_back(std::move(key));
        return false;
    });
    if (unknown) {
        return {};
    }
    std::sort(sources.begin(), sources.end());
    sources.erase(std::unique(sources.begin(), sources.end()), sources.end());
    return sources;
}

std::string NameAncestry::makerTag(std::string_view name)
{
    auto sections = splitSections(name);
    if (sections.empty()) {
        return {};
    }
    const auto& tag = decodeSection(sections.front()).iterationTag;
    return tag == Data::EMPTY_VALUE ? std::string() : tag;
}

bool NameAncestry::hasLineageTag(std::string_view name, std::string_view tag)
{
    if (tag.empty() || tag == Data::EMPTY_VALUE) {
        return false;
    }
    return walkLineage(name, false, [&](const DecodedMappedSection& section, bool) {
        return section.iterationTag == tag;
    });
}

const NameAncestry::KeySet& NameAncestry::ancestorsOf(Key key)
{
    if (_done[key]) {
        return _sets[key];
    }

    // The children: the prefix, and the names embedded in the last section. Copied, since the
    // recursion below interns more nodes.
    //
    // A pattern instance's name `P|<TRF;k>` is a copy of P, made by the pattern: P's ancestry is
    // the support's history, and the copy's is that history in instance k (ops#91). So the
    // prefix of a TRF section is a node in the instance's context, `\x1e<tag>;<k>\x1e<P>`, and so
    // is every node below it. The support's elements and instance k's copies of them then share
    // no ancestor, also where a name embeds an instance's name (a fusion's face bounded by an
    // edge of each of two instances); two names of one instance share the copies' ancestors.
    // A node in a context has the children of the name it stands for, in the same context.
    // A boundary section's prefix is the same (ops#56): `X|EXT` is X brought in through one Link
    // or binder, so the copies through two links share no ancestry, nor do X and its copy. So is
    // a second side's (PR 243 round 2): `X|CPY` is the second side's twin of the first side's X.
    std::vector<std::string> children;
    std::vector<std::pair<std::string, std::string>> referenceIds;  // (ID, tag) of a leaf
    std::string context;  // the node's contexts, outermost first, for a node in a context
    {
        std::string_view node = _names[key];
        while (!node.empty() && node.front() == contextMark) {
            auto end = node.find(contextMark, 1);
            if (end == std::string_view::npos) {
                break;  // no closing mark: not a context (only a caller's string can be one)
            }
            context.append(node.substr(0, end + 1));
            node.remove_prefix(end + 1);
        }
        auto sections = splitSections(node);
        const auto& last = decodeSection(sections.empty() ? std::string_view() : sections.back());
        if (sections.size() > 1) {
            // Everything before the last top-level delimiter.
            auto prefixSize = static_cast<std::size_t>(sections.back().data() - node.data()) - 1;
            std::string prefix(node.substr(0, prefixSize));
            if (isCopySection(last)) {
                prefix = contextMark + last.iterationTag + ";" + copyIndex(last) + contextMark
                    + prefix;
            }
            children.push_back(std::move(prefix));
        }
        if (!sections.empty()) {
            for (const auto& embedded : last.linkedNames) {
                children.push_back(embedded);
            }
            for (const auto& embedded : last.connectedElements) {
                children.push_back(embedded);
            }
            if (_measure == OverlapMeasure::ReferenceIds && sections.size() == 1) {
                for (const auto& id : last.referenceIDs) {
                    if (!id.empty() && id != Data::EMPTY_VALUE) {
                        referenceIds.emplace_back(id, last.iterationTag);
                    }
                }
            }
        }
    }

    KeySet result {key};
    std::vector<Key> childKeys;
    for (const auto& child : children) {
        if (child.empty()) {
            continue;
        }
        Key childKey = intern(context + child);
        if (childKey == key) {
            continue;  // not possible for a well-formed name, which is longer than its parts
        }
        childKeys.push_back(childKey);
        const KeySet& childSet = ancestorsOf(childKey);
        result.insert(result.end(), childSet.begin(), childSet.end());
    }
    for (const auto& [id, tag] : referenceIds) {
        // In a context, the leaf is the context's copy of it: another leaf.
        Key idKey = internReferenceId(context + id, tag);
        childKeys.push_back(idKey);
        result.push_back(idKey);
    }
    std::sort(result.begin(), result.end());
    result.erase(std::unique(result.begin(), result.end()), result.end());

    _children[key] = std::move(childKeys);
    _sets[key] = std::move(result);
    _done[key] = 1;
    ++_computed;
    return _sets[key];
}

const NameAncestry::KeySet& NameAncestry::ancestors(std::string_view name)
{
    static const KeySet empty;
    if (name.empty()) {
        return empty;
    }
    return ancestorsOf(intern(name));
}

std::vector<std::string> NameAncestry::ancestorNames(std::string_view name)
{
    std::vector<std::string> names;
    for (Key key : ancestors(name)) {
        names.push_back(_names[key]);
    }
    std::sort(names.begin(), names.end());
    return names;
}

bool NameAncestry::contains(std::string_view name, std::string_view ancestor)
{
    if (name.empty() || ancestor.empty()) {
        return false;
    }
    auto it = _keys.find(ancestor);
    if (it == _keys.end()) {
        // Not seen yet: it can still be in the set, which interns every node it holds.
        const KeySet& set = ancestors(name);
        it = _keys.find(ancestor);
        return it != _keys.end() && std::binary_search(set.begin(), set.end(), it->second);
    }
    Key ancestorKey = it->second;
    const KeySet& set = ancestors(name);
    return std::binary_search(set.begin(), set.end(), ancestorKey);
}

double NameAncestry::overlap(std::string_view oldName, std::string_view candidate)
{
    if (oldName.empty()) {
        return 0.0;
    }
    // Computing the candidate's set may intern nodes; the deques keep oldSet valid.
    const KeySet& oldSet = ancestors(oldName);
    const KeySet& candidateSet = ancestors(candidate);
    if (_measure == OverlapMeasure::DepthWeighted) {
        return weightedOverlap(intern(oldName), candidateSet);
    }
    std::size_t common = 0;
    auto a = oldSet.begin();
    auto b = candidateSet.begin();
    while (a != oldSet.end() && b != candidateSet.end()) {
        if (*a < *b) {
            ++a;
        }
        else if (*b < *a) {
            ++b;
        }
        else {
            ++common;
            ++a;
            ++b;
        }
    }
    return static_cast<double>(common) / static_cast<double>(oldSet.size());
}

NameAncestry::Key NameAncestry::internReferenceId(const std::string& id, const std::string& tag)
{
    // A control character starts no mapped name, so no name interns the same string.
    Key key = intern("\x1f" + id + "@" + tag);
    if (!_done[key]) {
        _sets[key] = {key};
        _done[key] = 1;
        ++_computed;
    }
    return key;
}

double NameAncestry::weightedOverlap(Key oldKey, const KeySet& candidateSet)
{
    auto it = _weights.find(oldKey);
    if (it == _weights.end()) {
        // Shortest depths below the old name, breadth first over the children ancestorsOf()
        // recorded (the old name's set is computed, so every node in it has its children).
        std::map<Key, int> depth {{oldKey, 0}};
        std::vector<Key> level {oldKey};
        for (int d = 1; !level.empty(); ++d) {
            std::vector<Key> next;
            for (Key node : level) {
                for (Key child : _children[node]) {
                    if (depth.emplace(child, d).second) {
                        next.push_back(child);
                    }
                }
            }
            level = std::move(next);
        }
        std::vector<std::pair<Key, double>> weights;
        double total = 0.0;
        for (const auto& [node, d] : depth) {
            double weight = std::ldexp(1.0, -d);
            weights.emplace_back(node, weight);
            total += weight;
        }
        it = _weights.emplace(oldKey, std::make_pair(std::move(weights), total)).first;
    }
    const auto& [weights, total] = it->second;
    double common = 0.0;
    for (const auto& [node, weight] : weights) {
        if (std::binary_search(candidateSet.begin(), candidateSet.end(), node)) {
            common += weight;
        }
    }
    return total > 0.0 ? common / total : 0.0;
}

bool NameAncestry::topAgrees(std::string_view oldName, std::string_view candidate)
{
    auto oldSections = splitSections(oldName);
    auto candidateSections = splitSections(candidate);
    if (oldSections.empty() || candidateSections.empty()) {
        return false;
    }
    const auto& oldTop = decodeSection(oldSections.back());
    const auto& candidateTop = decodeSection(candidateSections.back());
    return oldTop.opCode == candidateTop.opCode && sortedFlags(oldTop) == sortedFlags(candidateTop);
}

bool NameAncestry::isPieceOf(std::string_view name, std::string_view oldName)
{
    // A split made before a pattern instance's section (WholeShape mode, or an edit upstream of
    // the pattern): the instance's piece is `X|<split>|<TRF>`, its element `X|<TRF>`. They are
    // compared without the chain of TRF sections both end in. The same for a split made in
    // another document, before the boundary sections both end in (ops#56).
    {
        auto nameSections = splitSections(name);
        auto oldSections = splitSections(oldName);
        std::size_t common = 0;
        while (common < nameSections.size() && common < oldSections.size()) {
            auto section = nameSections[nameSections.size() - 1 - common];
            if (section != oldSections[oldSections.size() - 1 - common]
                || !isCopySection(decodeSection(section))) {
                break;
            }
            ++common;
        }
        if (common > 0 && common < nameSections.size() && common < oldSections.size()) {
            // Each head ends before the delimiter of its first copy section.
            auto head = [](std::string_view whole, std::string_view firstStripped) {
                return whole.substr(0, firstStripped.data() - whole.data() - 1);
            };
            return isPieceOf(
                head(name, nameSections[nameSections.size() - common]),
                head(oldName, oldSections[oldSections.size() - common])
            );
        }
    }
    if (oldName.empty() || name.size() <= oldName.size() + 1
        || name.substr(0, oldName.size()) != oldName) {
        return false;
    }
    // The old name must end at a top-level delimiter of the piece.
    if (name[oldName.size()] != *NAME_SECTION_DELIMINATOR
        || oldName.back() == *SUB_SECTION_ESCAPE_CHAR) {
        return false;
    }
    auto oldSections = splitSections(oldName);
    char elementType = decodeSection(oldSections.back()).elementType;
    auto added = splitSections(name.substr(oldName.size() + 1));
    if (added.empty()) {
        return false;
    }
    for (auto section : added) {
        const auto& decoded = decodeSection(section);
        if (!decoded.hasMapperFlag(MAPPER_FLAG_MODIFIED) || decoded.elementType != elementType
            || isCopySection(decoded)) {
            return false;
        }
    }
    return true;
}

namespace
{

// The decoded section if \a name is one section carrying the IDX flag, with a real op code.
const DecodedMappedSection* indexSection(std::string_view name)
{
    if (name.empty() || NameAncestry::splitSections(name).size() != 1) {
        return nullptr;
    }
    const auto& decoded = decodeSection(name);
    if (!decoded.hasMapperFlag(MAPPER_FLAG_INDEX) || decoded.opCode.empty()
        || isCounterOpCode(decoded.opCode)) {
        return nullptr;
    }
    return &decoded;
}

}  // namespace

bool NameAncestry::sameIndexSource(std::string_view a, std::string_view b)
{
    const DecodedMappedSection* x = indexSection(a);
    const DecodedMappedSection* y = indexSection(b);  // the cache's nodes don't move
    if (!x || !y) {
        return false;
    }
    return x->referenceIDs == y->referenceIDs && x->linkedNames == y->linkedNames
        && x->iterationTag == y->iterationTag && x->index == y->index
        && x->elementType == y->elementType && x->duplicateCount == y->duplicateCount
        && sortedFlags(*x) == sortedFlags(*y) && x->connectedElements == y->connectedElements;
}

std::string_view NameAncestry::indexSource(std::string_view name)
{
    if (indexSection(name)) {
        return name;
    }
    auto sections = splitSections(name);
    if (sections.size() < 2 || !indexSection(sections.front())
        || !isPieceOf(name, sections.front())) {
        return {};
    }
    return sections.front();
}

bool NameAncestry::isIndexPieceOf(std::string_view name, std::string_view oldName)
{
    if (!indexSection(oldName)) {
        return false;
    }
    auto sections = splitSections(name);
    if (sections.size() < 2 || sections.front() == oldName
        || !sameIndexSource(sections.front(), oldName)) {
        return false;
    }
    return isPieceOf(name, sections.front());
}

std::vector<int> NameAncestry::structuralSurvivors(
    std::string_view oldName,
    const std::vector<std::string>& candidates,
    double gap,
    double bandTop,
    double* bestOut
)
{
    // Overlaps are ratios of small integers; the slack keeps best - gap from excluding a
    // candidate exactly at the boundary through rounding.
    constexpr double slack = 1e-12;

    // The top-level TRF sections say which instance an element is in: an element of another
    // instance, or of the original, is another element (ops#55), even where a later section
    // embeds names of the old name's instance (a fusion's piece of instance 3 bounded by an
    // edge of instance 2, which ancestorsOf()'s contexts alone would relate, ops#91). So do the
    // top-level EXT sections: an element brought in through another Link or binder is another
    // element (ops#56).
    const auto oldInstances = patternInstances(oldName);
    std::vector<double> overlaps;
    overlaps.reserve(candidates.size());
    double best = 0.0;
    for (const auto& candidate : candidates) {
        overlaps.push_back(
            patternInstances(candidate) == oldInstances ? overlap(oldName, candidate) : 0.0
        );
        best = std::max(best, overlaps.back());
    }
    if (bestOut) {
        *bestOut = best;
    }
    std::vector<int> survivors;
    if (best <= 0.0) {
        return survivors;
    }
    const double top = std::max(best, bandTop);
    for (std::size_t i = 0; i < candidates.size(); ++i) {
        if (overlaps[i] > 0.0 && overlaps[i] >= top - gap - slack) {
            survivors.push_back(static_cast<int>(i));
        }
    }
    std::vector<int> agreeing;
    for (int i : survivors) {
        if (topAgrees(oldName, candidates[i])) {
            agreeing.push_back(i);
        }
    }
    return agreeing.empty() ? survivors : agreeing;
}

// ---------------------------------------------------------------------------------------------
// MatchGraph and forcedMatching

int MatchGraph::addCandidate(std::vector<int> elements)
{
    candidates.push_back(Candidate {std::move(elements)});
    return static_cast<int>(candidates.size()) - 1;
}

void MatchGraph::addEdge(int entry, int candidate, bool inAncestry)
{
    edges.push_back(Edge {entry, candidate, inAncestry});
}

namespace
{

struct UnionFind
{
    explicit UnionFind(int size)
        : parent(static_cast<std::size_t>(size))
    {
        std::iota(parent.begin(), parent.end(), 0);
    }
    int find(int i)
    {
        while (parent[i] != i) {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        return i;
    }
    void unite(int a, int b)
    {
        a = find(a);
        b = find(b);
        if (a != b) {
            parent[std::max(a, b)] = std::min(a, b);
        }
    }
    std::vector<int> parent;
};

// One component of the graph, with local indices.
struct Component
{
    std::vector<int> entries;     // global entry indices
    std::vector<int> candidates;  // global candidate indices
    // Per local entry: (local candidate, inAncestry), sorted, unique.
    std::vector<std::vector<std::pair<int, bool>>> edges;
    // Per local candidate: its elements, sorted, unique.
    std::vector<std::vector<int>> elements;
    // Per local candidate: the number of inAncestry edges.
    std::vector<int> ancestral;
};

struct ComponentResult
{
    std::vector<int> partner;  // per local entry: local candidate, or -1
    std::vector<MatchStatus> status;
};

// Maximum b-matching by augmenting paths (Kuhn's algorithm with capacities).
class BMatching
{
public:
    BMatching(const Component& c, const std::vector<char>& mergeMode)
        : _c(c)
        , _mergeMode(mergeMode)
    {}

    // The size of a maximum matching without the edge (excludedEntry, excludedCandidate), and
    // the matching (per local entry: local candidate or -1).
    int solve(int excludedEntry, int excludedCandidate, std::vector<int>* matching = nullptr)
    {
        _excludedEntry = excludedEntry;
        _excludedCandidate = excludedCandidate;
        std::size_t entries = _c.entries.size();
        std::size_t candidates = _c.candidates.size();
        _assigned.assign(entries, -1);
        _users.assign(candidates, {});
        int size = 0;
        for (std::size_t e = 0; e < entries; ++e) {
            _visited.assign(candidates, 0);
            if (augment(static_cast<int>(e))) {
                ++size;
            }
        }
        if (matching) {
            *matching = _assigned;
        }
        return size;
    }

private:
    int capacity(int candidate) const
    {
        return _mergeMode[candidate] ? _c.ancestral[candidate] : 1;
    }

    bool allowed(int entry, int candidate, bool inAncestry) const
    {
        if (entry == _excludedEntry && candidate == _excludedCandidate) {
            return false;
        }
        // A candidate used as a merge takes only the entries whose old names it holds.
        return !_mergeMode[candidate] || inAncestry;
    }

    bool augment(int entry)
    {
        for (const auto& [candidate, inAncestry] : _c.edges[entry]) {
            if (!allowed(entry, candidate, inAncestry) || _visited[candidate]) {
                continue;
            }
            _visited[candidate] = 1;
            auto& users = _users[candidate];
            if (static_cast<int>(users.size()) < capacity(candidate)) {
                users.push_back(entry);
                _assigned[entry] = candidate;
                return true;
            }
            for (int& user : users) {
                int displaced = user;
                if (augment(displaced)) {
                    // augment() gave the displaced entry another candidate.
                    user = entry;
                    _assigned[entry] = candidate;
                    return true;
                }
            }
        }
        return false;
    }

    const Component& _c;
    const std::vector<char>& _mergeMode;
    int _excludedEntry = -1;
    int _excludedCandidate = -1;
    std::vector<int> _assigned;
    std::vector<std::vector<int>> _users;
    std::vector<char> _visited;
};

ComponentResult solveByAugmenting(const Component& c, int maxMerges)
{
    std::size_t entries = c.entries.size();
    ComponentResult result {std::vector<int>(entries, -1), {}};

    std::vector<int> merges;
    for (std::size_t k = 0; k < c.candidates.size(); ++k) {
        if (c.ancestral[k] >= 2) {
            merges.push_back(static_cast<int>(k));
        }
    }
    if (static_cast<int>(merges.size()) > maxMerges) {
        result.status.assign(entries, MatchStatus::TooLarge);
        return result;
    }

    // Per mode combination: its maximum and the edges forced within it.
    int best = -1;
    std::vector<std::vector<int>> forcedPerMode;
    std::vector<char> mergeMode(c.candidates.size(), 0);
    for (unsigned long mask = 0; mask < (1UL << merges.size()); ++mask) {
        for (std::size_t m = 0; m < merges.size(); ++m) {
            mergeMode[merges[m]] = (mask >> m) & 1UL ? 1 : 0;
        }
        BMatching matcher(c, mergeMode);
        std::vector<int> matching;
        int size = matcher.solve(-1, -1, &matching);
        if (size < best) {
            continue;
        }
        if (size > best) {
            best = size;
            forcedPerMode.clear();
        }
        std::vector<int> forced(entries, -1);
        for (std::size_t e = 0; e < entries; ++e) {
            if (matching[e] >= 0
                && matcher.solve(static_cast<int>(e), matching[e]) < size) {
                forced[e] = matching[e];
            }
        }
        forcedPerMode.push_back(std::move(forced));
    }

    result.status.assign(entries, MatchStatus::Ambiguous);
    for (std::size_t e = 0; e < entries; ++e) {
        int partner = forcedPerMode.front()[e];
        bool agreed = partner >= 0;
        for (const auto& forced : forcedPerMode) {
            agreed = agreed && forced[e] == partner;
        }
        if (agreed) {
            result.partner[e] = partner;
            result.status[e] = MatchStatus::Resolved;
        }
    }
    return result;
}

// Exhaustive search over every matching, for components whose candidates share elements.
class ExhaustiveSearch
{
public:
    ExhaustiveSearch(const Component& c, long maxSteps)
        : _c(c)
        , _maxSteps(maxSteps)
    {}

    ComponentResult run()
    {
        std::size_t entries = _c.entries.size();
        _assigned.assign(entries, -1);
        _users.assign(_c.candidates.size(), {});
        _elementUser.clear();
        _seen.assign(entries, -2);
        _ambiguous.assign(entries, 0);
        search(0, 0);

        ComponentResult result {std::vector<int>(entries, -1), {}};
        if (_aborted) {
            result.status.assign(entries, MatchStatus::TooLarge);
            return result;
        }
        result.status.assign(entries, MatchStatus::Ambiguous);
        for (std::size_t e = 0; e < entries; ++e) {
            if (!_ambiguous[e] && _seen[e] >= 0) {
                result.partner[e] = _seen[e];
                result.status[e] = MatchStatus::Resolved;
            }
        }
        return result;
    }

private:
    bool canUse(int candidate, bool inAncestry) const
    {
        const auto& users = _users[candidate];
        if (users.empty()) {
            for (int element : _c.elements[candidate]) {
                auto it = _elementUser.find(element);
                if (it != _elementUser.end() && it->second != candidate) {
                    return false;
                }
            }
            return true;
        }
        // Sharing a candidate is a merge: every user's old name must be in its ancestry.
        if (!inAncestry) {
            return false;
        }
        for (int user : users) {
            if (!ancestral(user, candidate)) {
                return false;
            }
        }
        return true;
    }

    bool ancestral(int entry, int candidate) const
    {
        for (const auto& [k, inAncestry] : _c.edges[entry]) {
            if (k == candidate) {
                return inAncestry;
            }
        }
        return false;
    }

    void use(int entry, int candidate)
    {
        if (_users[candidate].empty()) {
            for (int element : _c.elements[candidate]) {
                _elementUser[element] = candidate;
            }
        }
        _users[candidate].push_back(entry);
        _assigned[entry] = candidate;
    }

    void release(int entry, int candidate)
    {
        _users[candidate].pop_back();
        if (_users[candidate].empty()) {
            for (int element : _c.elements[candidate]) {
                _elementUser.erase(element);
            }
        }
        _assigned[entry] = -1;
    }

    void record(int size)
    {
        if (size > _best) {
            _best = size;
            std::fill(_seen.begin(), _seen.end(), -2);
            std::fill(_ambiguous.begin(), _ambiguous.end(), 0);
        }
        for (std::size_t e = 0; e < _assigned.size(); ++e) {
            if (_seen[e] == -2) {
                _seen[e] = _assigned[e];
            }
            else if (_seen[e] != _assigned[e]) {
                _ambiguous[e] = 1;
            }
        }
    }

    void search(std::size_t entry, int size)
    {
        if (_aborted || ++_steps > _maxSteps) {
            _aborted = true;
            return;
        }
        int remaining = static_cast<int>(_assigned.size() - entry);
        if (size + remaining < _best) {
            return;
        }
        if (entry == _assigned.size()) {
            record(size);
            return;
        }
        int e = static_cast<int>(entry);
        for (const auto& [candidate, inAncestry] : _c.edges[entry]) {
            if (canUse(candidate, inAncestry)) {
                use(e, candidate);
                search(entry + 1, size + 1);
                release(e, candidate);
            }
        }
        search(entry + 1, size);
    }

    const Component& _c;
    long _maxSteps;
    long _steps = 0;
    bool _aborted = false;
    int _best = -1;
    std::vector<int> _assigned;
    std::vector<std::vector<int>> _users;
    std::map<int, int> _elementUser;
    std::vector<int> _seen;  // per entry: its partner in the maximum matchings so far, -2 none yet
    std::vector<char> _ambiguous;
};

}  // namespace

MatchResult forcedMatching(const MatchGraph& graph, int maxMerges, long maxSteps)
{
    const int entryCount = graph.entryCount;
    const int candidateCount = static_cast<int>(graph.candidates.size());
    if (entryCount < 0) {
        throw Base::ValueError("forcedMatching: negative entry count");
    }

    // Edges, deduplicated; a duplicate with inAncestry set keeps it.
    std::map<std::pair<int, int>, bool> edges;
    for (const auto& edge : graph.edges) {
        if (edge.entry < 0 || edge.entry >= entryCount || edge.candidate < 0
            || edge.candidate >= candidateCount) {
            throw Base::ValueError("forcedMatching: edge index out of range");
        }
        edges[{edge.entry, edge.candidate}] |= edge.inAncestry;
    }

    // Components over entries [0, entryCount) and candidates [entryCount, ...), joined by edges
    // and by shared elements. Candidates without edges take no part.
    std::vector<char> used(static_cast<std::size_t>(candidateCount), 0);
    UnionFind sets(entryCount + candidateCount);
    for (const auto& [key, inAncestry] : edges) {
        sets.unite(key.first, entryCount + key.second);
        used[key.second] = 1;
    }
    std::vector<std::vector<int>> elements(static_cast<std::size_t>(candidateCount));
    std::map<int, int> firstWithElement;
    for (int k = 0; k < candidateCount; ++k) {
        auto& list = elements[k];
        list = graph.candidates[k].elements;
        std::sort(list.begin(), list.end());
        list.erase(std::unique(list.begin(), list.end()), list.end());
        if (!used[k]) {
            continue;
        }
        for (int element : list) {
            auto [it, inserted] = firstWithElement.emplace(element, k);
            if (!inserted) {
                sets.unite(entryCount + it->second, entryCount + k);
            }
        }
    }
    MatchResult result;
    result.partner.assign(static_cast<std::size_t>(entryCount), -1);
    result.status.assign(static_cast<std::size_t>(entryCount), MatchStatus::NoCandidate);

    // Components by their root, in increasing order of the root (the lowest node index).
    std::map<int, Component> components;
    std::vector<int> localIndex(static_cast<std::size_t>(entryCount + candidateCount), -1);
    for (int e = 0; e < entryCount; ++e) {
        auto& c = components[sets.find(e)];
        localIndex[e] = static_cast<int>(c.entries.size());
        c.entries.push_back(e);
        c.edges.emplace_back();
    }
    for (int k = 0; k < candidateCount; ++k) {
        if (!used[k]) {
            continue;
        }
        auto& c = components[sets.find(entryCount + k)];
        localIndex[entryCount + k] = static_cast<int>(c.candidates.size());
        c.candidates.push_back(k);
        c.elements.push_back(elements[k]);
        c.ancestral.push_back(0);
    }
    for (const auto& [key, inAncestry] : edges) {
        auto& c = components[sets.find(key.first)];
        int localEntry = localIndex[key.first];
        int localCandidate = localIndex[entryCount + key.second];
        c.edges[localEntry].emplace_back(localCandidate, inAncestry);
        if (inAncestry) {
            ++c.ancestral[localCandidate];
        }
    }

    for (auto& [root, c] : components) {
        if (c.candidates.empty()) {
            continue;  // lone entries without candidates
        }
        for (auto& list : c.edges) {
            std::sort(list.begin(), list.end());
        }
        bool sharesElements = false;
        std::map<int, int> count;
        for (const auto& list : c.elements) {
            for (int element : list) {
                sharesElements = sharesElements || ++count[element] > 1;
            }
        }
        ComponentResult solved = sharesElements ? ExhaustiveSearch(c, maxSteps).run()
                                                : solveByAugmenting(c, maxMerges);
        for (std::size_t e = 0; e < c.entries.size(); ++e) {
            int global = c.entries[e];
            if (c.edges[e].empty()) {
                continue;  // NoCandidate
            }
            result.status[global] = solved.status[e];
            result.partner[global] = solved.partner[e] >= 0 ? c.candidates[solved.partner[e]] : -1;
        }
    }
    return result;
}

// ---------------------------------------------------------------------------------------------
// groupEquivalent

std::vector<std::vector<int>> groupEquivalent(
    const std::vector<std::string>& names,
    const std::function<bool(int, int)>& equivalent
)
{
    const int count = static_cast<int>(names.size());
    UnionFind sets(count);
    std::vector<char> pair(static_cast<std::size_t>(count) * count, 0);
    for (int i = 0; i < count; ++i) {
        for (int j = i + 1; j < count; ++j) {
            if (equivalent(i, j)) {
                pair[static_cast<std::size_t>(i) * count + j] = 1;
                sets.unite(i, j);
            }
        }
    }

    std::map<int, std::vector<int>> components;
    for (int i = 0; i < count; ++i) {
        components[sets.find(i)].push_back(i);
    }

    auto byName = [&names](int a, int b) {
        return names[a] != names[b] ? names[a] < names[b] : a < b;
    };
    std::vector<std::vector<int>> groups;
    for (auto& [root, members] : components) {
        bool clique = true;
        for (std::size_t a = 0; clique && a < members.size(); ++a) {
            for (std::size_t b = a + 1; clique && b < members.size(); ++b) {
                // members are in increasing index order
                clique = pair[static_cast<std::size_t>(members[a]) * count + members[b]] != 0;
            }
        }
        if (clique) {
            std::sort(members.begin(), members.end(), byName);
            groups.push_back(std::move(members));
        }
        else {
            for (int member : members) {
                groups.push_back({member});
            }
        }
    }
    std::sort(groups.begin(), groups.end(), [&](const auto& a, const auto& b) {
        return byName(a.front(), b.front());
    });
    return groups;
}

// ---------------------------------------------------------------------------------------------
// solveOwner

namespace
{

// The number at the end of an index name (`Face12` -> 12), or -1.
long indexNumber(const std::string& index)
{
    std::size_t pos = index.size();
    while (pos > 0 && index[pos - 1] >= '0' && index[pos - 1] <= '9') {
        --pos;
    }
    if (pos == index.size() || index.size() - pos > 9) {
        return -1;
    }
    return std::stol(index.substr(pos));
}

bool byIndex(const SolveInput::Element& a, const SolveInput::Element& b)
{
    long na = indexNumber(a.index);
    long nb = indexNumber(b.index);
    return na != nb ? na < nb : a.index < b.index;
}

std::string formatOverlap(double value)
{
    std::ostringstream ss;
    ss.imbue(std::locale::classic());
    ss.precision(2);
    ss << std::fixed << value;
    return ss.str();
}

bool sameSectionsUpToCounter(
    const std::vector<std::string_view>& sectionsA,
    const std::vector<std::string_view>& sectionsB,
    bool copySiblings
);

/* Copies of one element by two copy makers of one kind (ops#523, decision 157): two copy or
 * second side sections `CPY` of any index (a link's `L`, a link array element's `L<n>`, a
 * Scale's or Reverse's `1`, a second side's `2`), or two boundary sections `EXT` of one index,
 * whatever their tags. Each copy's section is tagged with its own copy maker, so without this
 * two links to one object give names that differ in more than the counter, and the sibling
 * guards don't see one copy put in another's place.
 */
bool copySiblingSections(const DecodedMappedSection& x, const DecodedMappedSection& y)
{
    if (x.opCode == secondSideOpCode && y.opCode == secondSideOpCode) {
        return true;
    }
    return x.opCode == boundaryOpCode && y.opCode == boundaryOpCode && x.index == y.index;
}

// The section a copy adds to its original's names (ops#523, decision 157): a link copy's
// `CPY;L` or `CPY;L<n>`, or a Scale's or Reverse's `CPY;1`. A pattern instance's TRF isn't one:
// a pattern's original keeps its own names.
bool isOriginalsCopySection(std::string_view section)
{
    if (section.find(";CPY;") == std::string_view::npos) {
        return false;
    }
    DecodedMappedName decoded = MappedName::getDecodedMappedName(std::string(section));
    return decoded.size() == 1 && decoded.front().opCode == secondSideOpCode
        && (decoded.front().index == "1" || decoded.front().index.starts_with('L'));
}

/* True if \a a and \a b are the same name up to the duplicate counter of any section, at any
 * depth: the sections of the embedded Linked and Connected Names are compared the same way, so a
 * face built on instance 1's edges and one built on instance 2's are equal up to the counter.
 * Both forms of the counter are ignored, as harness.py's withoutCounter() does: the duplicate
 * count field, and a counter written over the op code, which then matches any op code. So is the
 * instance number of a pattern instance's TRF section: two instances of one pattern are siblings.
 * So are two copies of one element by two copy makers of one kind (copySiblingSections()), and
 * an element and its copy: a name and the same name with one more copy section
 * (isOriginalsCopySection(); ops#523, decision 157). Those two only with \a copySiblings: a
 * site that refuses a sibling takes them, but one that gathers an element's twins or pieces
 * doesn't, since another copy's twins are no twins of this one (the A3 pre-push review's T1).
 * A section that doesn't decode must be equal as text.
 */
bool sameUpToCounter(std::string_view a, std::string_view b, bool copySiblings = true)
{
    if (a == b) {
        return true;
    }
    auto sectionsA = NameAncestry::splitSections(a);
    auto sectionsB = NameAncestry::splitSections(b);
    if (sectionsA.size() == sectionsB.size()) {
        return sameSectionsUpToCounter(sectionsA, sectionsB, copySiblings);
    }
    if (!copySiblings) {
        return false;
    }
    // The original and its copy
    const auto& longer = sectionsA.size() > sectionsB.size() ? sectionsA : sectionsB;
    const auto& shorter = sectionsA.size() > sectionsB.size() ? sectionsB : sectionsA;
    if (shorter.empty() || longer.size() != shorter.size() + 1) {
        return false;
    }
    for (std::size_t i = 1; i < longer.size(); ++i) {
        if (!isOriginalsCopySection(longer[i])) {
            continue;
        }
        std::vector<std::string_view> without(longer);
        without.erase(without.begin() + static_cast<std::ptrdiff_t>(i));
        if (sameSectionsUpToCounter(without, shorter, copySiblings)) {
            return true;
        }
    }
    return false;
}

// sameUpToCounter() of two names' sections, pairwise
bool sameSectionsUpToCounter(
    const std::vector<std::string_view>& sectionsA,
    const std::vector<std::string_view>& sectionsB,
    bool copySiblings
)
{
    if (sectionsA.empty() || sectionsA.size() != sectionsB.size()) {
        return false;
    }
    for (std::size_t i = 0; i < sectionsA.size(); ++i) {
        if (sectionsA[i] == sectionsB[i]) {
            continue;
        }
        // Copies: the recursion below decodes more names.
        DecodedMappedName decodedA = MappedName::getDecodedMappedName(std::string(sectionsA[i]));
        DecodedMappedName decodedB = MappedName::getDecodedMappedName(std::string(sectionsB[i]));
        if (decodedA.size() != 1 || decodedB.size() != 1) {
            return false;
        }
        const DecodedMappedSection& x = decodedA.front();
        const DecodedMappedSection& y = decodedB.front();
        bool opCodesAgree = x.opCode == y.opCode || isCounterOpCode(x.opCode)
            || isCounterOpCode(y.opCode);
        // The copies of an element in two instances of one pattern are siblings: the instance
        // number in a TRF section's index counts as a counter here (ops#55).
        bool instanceSections
            = x.opCode == patternInstanceOpCode && y.opCode == patternInstanceOpCode;
        // So are its copies by two copy makers of one kind, whatever their tags (ops#523)
        bool copySections = copySiblings && copySiblingSections(x, y);
        if (!opCodesAgree || x.referenceIDs != y.referenceIDs
            || (x.iterationTag != y.iterationTag && !copySections)
            || (x.index != y.index && !instanceSections && !copySections)
            || x.elementType != y.elementType || x.mapperFlags != y.mapperFlags
            || x.linkedNames.size() != y.linkedNames.size()
            || x.connectedElements.size() != y.connectedElements.size()) {
            return false;
        }
        for (std::size_t j = 0; j < x.linkedNames.size(); ++j) {
            if (!sameUpToCounter(x.linkedNames[j], y.linkedNames[j], copySiblings)) {
                return false;
            }
        }
        for (std::size_t j = 0; j < x.connectedElements.size(); ++j) {
            if (!sameUpToCounter(x.connectedElements[j], y.connectedElements[j], copySiblings)) {
                return false;
            }
        }
    }
    return true;
}

/* True if \a name is \a oldName up to the duplicate counter (sameUpToCounter()), and not
 * \a oldName itself: a pattern instance's copy of the old element, or another element the
 * element map told apart only by the counter. With \a copySiblings, also another copy of it or
 * its original (ops#523): for the sites that refuse a sibling, not those that gather twins.
 */
bool isCounterSibling(std::string_view name, std::string_view oldName, bool copySiblings = true)
{
    return name != oldName && sameUpToCounter(name, oldName, copySiblings);
}

// Part's mapper flag of a far cap told apart from its twins only by its place among them
// (MAPPER_FLAG_ORDERED, TopoShapeExpansion.cpp; ops#360, PR 340 round 2)
constexpr const char* orderedFlag = "ORD";

/* True if a section of \a name carries the ORD flag: its element is told apart from its counter
 * siblings only by its place among them, which an edit that moves them all can change.
 */
bool isOrdered(std::string_view name)
{
    const auto sections = NameAncestry::splitSections(name);
    return std::any_of(sections.begin(), sections.end(), [](std::string_view section) {
        return decodeSection(section).hasMapperFlag(orderedFlag);
    });
}

// Part's mapper flag of a twin placed on a closed edge (closedTwinFlag, TopoShapeExpansion.cpp;
// PLAN decision 206)
constexpr const char* closedTwinFlag = "CLS";

/* True if a section of \a name carries the closed edge's twin flag: its element is told apart
 * from its twins by its place counted from the edge's seam, which an edit can turn past them with
 * the geometry unchanged (a sketch's circle turned 180 degrees under a symmetric cut). The stop
 * (decision 206): a reference to it stands only where its element holds the old place unchanged;
 * moved or gone, it breaks.
 */
bool isClosedTwin(std::string_view name)
{
    const auto sections = NameAncestry::splitSections(name);
    return std::any_of(sections.begin(), sections.end(), [](std::string_view section) {
        return decodeSection(section).hasMapperFlag(closedTwinFlag);
    });
}

/* True if a section of \a name is a far cap's piece marked by its marks (PRJ and MOD with
 * connected elements, a face), and none is ordered (isMarkedCapName()). With \a faceAlone, marked
 * by one face of the up-to shape alone (the only piece on it): an up-to shell without names,
 * rebuilt in another order, trades such marks between pieces.
 */
bool isMarkedCap(std::string_view name, bool faceAlone = false)
{
    if (isOrdered(name)) {
        return false;
    }
    const auto sections = NameAncestry::splitSections(name);
    return std::any_of(sections.begin(), sections.end(), [faceAlone](std::string_view section) {
        const DecodedMappedSection& decoded = decodeSection(section);
        if (decoded.elementType != 'F' || !decoded.hasMapperFlag(MAPPER_FLAG_PROJECTION)
            || !decoded.hasMapperFlag(MAPPER_FLAG_MODIFIED) || decoded.connectedElements.empty()) {
            return false;
        }
        if (!faceAlone) {
            return true;
        }
        if (decoded.connectedElements.size() != 1) {
            return false;
        }
        const auto markSections = NameAncestry::splitSections(decoded.connectedElements.front());
        return !markSections.empty() && decodeSection(markSections.back()).elementType == 'F';
    });
}

/* True if a section of \a name is a marked piece of a far edge or a far cap: PRJ and MOD with
 * connected elements, ordered or not (PR 366 round 3).
 */
bool isMarkedPiece(std::string_view name)
{
    const auto sections = NameAncestry::splitSections(name);
    return std::any_of(sections.begin(), sections.end(), [](std::string_view section) {
        const DecodedMappedSection& decoded = decodeSection(section);
        return (decoded.elementType == 'F' || decoded.elementType == 'E')
            && decoded.hasMapperFlag(MAPPER_FLAG_PROJECTION)
            && decoded.hasMapperFlag(MAPPER_FLAG_MODIFIED) && !decoded.connectedElements.empty();
    });
}

/* The marks of \a name's marked piece, the connected elements of its first section that is one
 * (PR 366 round 5); empty for none. Two pieces of one edge on one face of the up-to shape share
 * them, told apart by their counters.
 */
std::vector<std::string> pieceMarks(std::string_view name)
{
    for (const auto section : NameAncestry::splitSections(name)) {
        const DecodedMappedSection& decoded = decodeSection(section);
        if ((decoded.elementType == 'F' || decoded.elementType == 'E')
            && decoded.hasMapperFlag(MAPPER_FLAG_PROJECTION)
            && decoded.hasMapperFlag(MAPPER_FLAG_MODIFIED) && !decoded.connectedElements.empty()) {
            return decoded.connectedElements;
        }
    }
    return {};
}

// The op code of a Mirror's section (Part's OpCodes::Mirror): its Index says which copy.
constexpr const char* mirrorOpCode = "MIR";

/* True if \a section is a counter section (ops#503 class D, round 2): one whose Index is the
 * element's rank among the elements its op made alike, as a hole's two crossings of an edge
 * (`CUT;0;V` and `CUT;1;V`, numbered along the edge) or a split's pieces. GEN or MOD among its
 * flags, no connected elements (a marked piece's marks tell it apart), not a copy maker's
 * section (TRF, CPY, EXT, MIR: the Index says which copy, an identity, I-A7) and none of UPP,
 * LOW, PRJ and SRC (a fallback list's position, part A's accepted ladder, is no key either).
 */
bool isCounterSection(const DecodedMappedSection& section)
{
    if ((!section.hasMapperFlag(MAPPER_FLAG_GENERATED) && !section.hasMapperFlag(MAPPER_FLAG_MODIFIED))
        || !section.connectedElements.empty() || isCopySection(section)
        || section.opCode == mirrorOpCode) {
        return false;
    }
    for (const char* flag :
         {MAPPER_FLAG_UPPER, MAPPER_FLAG_LOWER, MAPPER_FLAG_PROJECTION, MAPPER_FLAG_SOURCE}) {
        if (section.hasMapperFlag(flag)) {
            return false;
        }
    }
    return true;
}

// A section's mapper flags without ORD and the closed edge's flag, in their order: the survivor
// of a 2 -> 1 change loses the flags its twins had (ops#503 class D, round 2; decision 206)
std::vector<std::string> flagsBesideOrder(const DecodedMappedSection& section)
{
    std::vector<std::string> flags;
    for (const auto& flag : section.mapperFlags) {
        if (flag != orderedFlag && flag != closedTwinFlag) {
            flags.push_back(flag);
        }
    }
    return flags;
}

/* True if \a a and \a b are the same name up to their order keys (ops#503 class D, isTwinName()):
 * as sameUpToCounter(), with the ORD flag and the closed edge's flag (decision 206) ignored at
 * every level, and the Index of a section
 * where both values are roles (Data::isRoleValue(): the last section at the top level, any
 * section below it) or, at the top level (\a top), the Index of a counter section
 * (isCounterSection(): today's bare ranks, until A2 names the ranks; then this bridging goes),
 * and the connected elements of the top level's last section when only one name has them (the
 * vertexes that told a generated twin apart, which its lone survivor lacks: decision 214).
 * Below the top level, the names a section links and connects, a pattern instance's number
 * counts as a counter too, as in sameUpToCounter(); at the top level it doesn't: an instance's
 * number is its identity (I-A7), and a copy of the old element is the "pattern sibling" guard's.
 */
bool sameUpToOrder(std::string_view a, std::string_view b, bool top)
{
    if (a == b) {
        return true;
    }
    auto sectionsA = NameAncestry::splitSections(a);
    auto sectionsB = NameAncestry::splitSections(b);
    if (sectionsA.empty() || sectionsA.size() != sectionsB.size()) {
        return false;
    }
    for (std::size_t i = 0; i < sectionsA.size(); ++i) {
        if (sectionsA[i] == sectionsB[i]) {
            continue;
        }
        const DecodedMappedName decodedA = MappedName::getDecodedMappedName(std::string(sectionsA[i]));
        const DecodedMappedName decodedB = MappedName::getDecodedMappedName(std::string(sectionsB[i]));
        if (decodedA.size() != 1 || decodedB.size() != 1) {
            return false;
        }
        const DecodedMappedSection& x = decodedA.front();
        const DecodedMappedSection& y = decodedB.front();
        const bool opCodesAgree = x.opCode == y.opCode || isCounterOpCode(x.opCode)
            || isCounterOpCode(y.opCode);
        const bool roles = isRoleValue(x.index) && isRoleValue(y.index)
            && (!top || i + 1 == sectionsA.size());
        const bool instances = !top && x.opCode == patternInstanceOpCode
            && y.opCode == patternInstanceOpCode;
        const bool ranks = top && isCounterSection(x) && isCounterSection(y);
        // The connected elements that told a twin apart, on one side only (PLAN decision 214):
        // a generated twin keeps the vertexes no other twin has as its key, and the lone member
        // left when its twins went has none, so the two are the same element up to that key
        const bool toldApart = top && i + 1 == sectionsA.size()
            && x.connectedElements.empty() != y.connectedElements.empty();
        if (!opCodesAgree || x.referenceIDs != y.referenceIDs || x.iterationTag != y.iterationTag
            || (x.index != y.index && !roles && !instances && !ranks)
            || x.elementType != y.elementType || flagsBesideOrder(x) != flagsBesideOrder(y)
            || x.linkedNames.size() != y.linkedNames.size()
            || (x.connectedElements.size() != y.connectedElements.size() && !toldApart)) {
            return false;
        }
        for (std::size_t j = 0; j < x.linkedNames.size(); ++j) {
            if (!sameUpToOrder(x.linkedNames[j], y.linkedNames[j], false)) {
                return false;
            }
        }
        for (std::size_t j = 0; j < x.connectedElements.size() && !toldApart; ++j) {
            if (!sameUpToOrder(x.connectedElements[j], y.connectedElements[j], false)) {
                return false;
            }
        }
    }
    return true;
}

/* True if \a name is keyed by its order among elements made alike (ops#503 class D, the
 * record's lone count): a section carries ORD, a duplicate counter (the field, or written over
 * the op code), or a role, or is a counter section (isCounterSection()) with a non-zero Index.
 */
bool isOrderKeyed(std::string_view name)
{
    const auto sections = NameAncestry::splitSections(name);
    for (std::size_t i = 0; i < sections.size(); ++i) {
        const auto& section = decodeSection(sections[i]);
        const bool counter = isCounterSection(section);
        const auto& duplicate = section.duplicateCount;
        if (section.hasMapperFlag(orderedFlag) || isCounterOpCode(section.opCode)
            || (!duplicate.empty() && duplicate != "0" && duplicate != Data::EMPTY_VALUE)
            || (isRoleValue(section.index) && (counter || i + 1 == sections.size()))
            || (counter && section.index != "0" && section.index != Data::EMPTY_VALUE)) {
            return true;
        }
    }
    return false;
}

/* True if \a name's element holds \a oldName's, a piece of a far cap that an edit merged with
 * others into one (ops#360, PR 340 round 3): the names are the same but in one section, a marked
 * piece's (PRJ and MOD), where \a name's marks, its connected elements, hold every one of
 * \a oldName's and more. The pieces either side of a hole become the ring around it. The old
 * marks must hold an edge of the up-to shape (the piece shared its face with other caps): a
 * piece marked by its face alone is no evidence, since a renumbered up-to shell (a Part feature
 * without names, its faces reordered) gives that face's name to another face, which holds
 * other pieces.
 * With \a alone (round 4), the marks are instead the one face of the up-to shape among the old
 * marks: the merged piece is the only far cap on that face, so its marks are the face alone
 * (the strip across a hole made taller than the hole, with no other cap on the plate). Name
 * evidence is then weaker (a renamed face holds it too): the caller corroborates by geometry.
 */
bool holdsMarkedPiece(std::string_view name, std::string_view oldName, bool alone = false)
{
    const auto sections = NameAncestry::splitSections(name);
    const auto oldSections = NameAncestry::splitSections(oldName);
    if (sections.empty() || sections.size() != oldSections.size()) {
        return false;
    }
    bool held = false;
    for (std::size_t i = 0; i < sections.size(); ++i) {
        if (sections[i] == oldSections[i]) {
            continue;
        }
        if (held) {
            return false;
        }
        const DecodedMappedSection& x = decodeSection(sections[i]);
        const DecodedMappedSection& y = decodeSection(oldSections[i]);
        if (!y.hasMapperFlag(MAPPER_FLAG_PROJECTION) || !y.hasMapperFlag(MAPPER_FLAG_MODIFIED)
            || y.connectedElements.empty() || x.opCode != y.opCode || x.referenceIDs != y.referenceIDs
            || x.iterationTag != y.iterationTag || x.index != y.index
            || x.elementType != y.elementType || x.duplicateCount != y.duplicateCount
            || sortedFlags(x) != sortedFlags(y) || x.linkedNames != y.linkedNames
            || (alone ? x.connectedElements.size() != 1
                      : x.connectedElements.size() <= y.connectedElements.size())) {
            return false;
        }
        auto markType = [](const std::string& mark) {
            const auto markSections = NameAncestry::splitSections(mark);
            return markSections.empty() ? char(0) : decodeSection(markSections.back()).elementType;
        };
        bool edge = false;
        for (const auto& mark : y.connectedElements) {
            if (!alone
                && std::find(x.connectedElements.begin(), x.connectedElements.end(), mark)
                    == x.connectedElements.end()) {
                return false;
            }
            edge = edge || markType(mark) == 'E';
        }
        if (!edge
            || (alone
                && (markType(x.connectedElements.front()) != 'F'
                    || std::find(
                           y.connectedElements.begin(),
                           y.connectedElements.end(),
                           x.connectedElements.front()
                       ) == y.connectedElements.end()))) {
            return false;
        }
        held = true;
    }
    return held;
}

/* True if \a name's element is \a oldName's far edge or far cap made whole again (ops#386): the
 * names are the same but in one section, a marked piece's in \a oldName (PRJ and MOD), which in
 * \a name is the same projection unmarked: PRJ alone, no marks, no duplicate counter. A far edge
 * that an edit moved off the up-to shell's seam, or out of a hole, is one projection again. The
 * old piece's place on it, and the up-to face under it, are the caller's to check (ops#522).
 */
bool isWholeProjectionOf(std::string_view name, std::string_view oldName)
{
    const auto sections = NameAncestry::splitSections(name);
    const auto oldSections = NameAncestry::splitSections(oldName);
    if (sections.empty() || sections.size() != oldSections.size()) {
        return false;
    }
    bool whole = false;
    for (std::size_t i = 0; i < sections.size(); ++i) {
        if (sections[i] == oldSections[i]) {
            continue;
        }
        if (whole) {
            return false;
        }
        const DecodedMappedSection& x = decodeSection(sections[i]);
        const DecodedMappedSection& y = decodeSection(oldSections[i]);
        if (!y.hasMapperFlag(MAPPER_FLAG_PROJECTION) || !y.hasMapperFlag(MAPPER_FLAG_MODIFIED)
            || y.connectedElements.empty() || !x.connectedElements.empty()
            || sortedFlags(x) != std::vector<std::string> {MAPPER_FLAG_PROJECTION}
            || x.duplicateCount != "0" || x.opCode != y.opCode || x.referenceIDs != y.referenceIDs
            || x.iterationTag != y.iterationTag || x.index != y.index
            || x.elementType != y.elementType || x.linkedNames != y.linkedNames) {
            return false;
        }
        whole = true;
    }
    return whole;
}

/* True if \a now, the up-to faces under a far piece's saved point now, are \a saved, those its
 * fingerprint lists (ops#522, PLAN decision 168), each matched by exactly one, and each saved one
 * by exactly one of \a all, every up-to face now: the same owner, the box's corners and the outer
 * wire's centre within \a eps (coincidence, as atSamePlace()), the normal at the point within
 * \a tolerances.angle either way (a face's orientation may flip on a rebuild), and the area within
 * \a tolerances.size relative (tier 3's: a trimmed B-spline plate's area moved by 4e-5 of itself
 * when only its hole moved). No face saved, or none now (the face under the point is gone), is
 * false; so are two faces now that one saved one matches, under the point or elsewhere (two halves
 * of a square, one where the other was).
 */
bool sameUpToFaces(
    const std::vector<ElementFingerprint::UpToFace>& saved,
    const std::vector<ElementFingerprint::UpToFace>& now,
    const std::vector<ElementFingerprint::UpToFace>& all,
    double eps,
    const GeometryTolerances& tolerances
)
{
    using Face = ElementFingerprint::UpToFace;
    // The face alone; with the normal at the point too, for the faces under it
    auto alike = [&](const Face& a, const Face& b) {
        return a.owner == b.owner && Base::Distance(a.boxMin, b.boxMin) <= eps
            && Base::Distance(a.boxMax, b.boxMax) <= eps
            && Base::Distance(a.wireCentre, b.wireCentre) <= eps
            && std::abs(a.area - b.area)
            <= tolerances.size * std::max({std::abs(a.area), std::abs(b.area), eps});
    };
    auto same = [&](const Face& a, const Face& b) {
        if (!alike(a, b)) {
            return false;
        }
        Base::Vector3d u = a.normal;
        Base::Vector3d v = b.normal;
        if (u.Length() <= 0.0 || v.Length() <= 0.0) {
            return false;
        }
        u.Normalize();
        v.Normalize();
        // The angle from the cross product, as intrinsicAgrees(): acos loses precision near 0
        return std::atan2((u % v).Length(), std::abs(u * v)) <= tolerances.angle;
    };
    if (saved.empty() || saved.size() != now.size()) {
        return false;
    }
    auto matchedOnce = [&](const std::vector<Face>& these, const std::vector<Face>& those, auto match) {
        return std::all_of(these.begin(), these.end(), [&](const Face& face) {
            return std::count_if(those.begin(), those.end(), [&](const Face& other) {
                       return match(face, other);
                   })
                == 1;
        });
    };
    return matchedOnce(saved, now, same) && matchedOnce(now, saved, same)
        && matchedOnce(saved, all, alike);
}

// Where a lone far piece that moved alone stands on the up-to face it lay on (ops#524, PLAN
// decisions 199 (4) and 202): placeOnUpToFace()
enum class OnUpToFace
{
    Kept,      // the saved face is the one under it, and the path from its foot stays inside it
    Left,      // another face, none or two under it, or the path leaves the face
    CantTell,  // the path can't be told (an end on the face's boundary, a seam, a failed section)
};

/* Where the far piece named \a name, whose saved fingerprint is \a saved and whose current one is
 * \a now, stands on the one up-to face it lay on (ops#524, PLAN decisions 182, 199 and 202): it is
 * marked by that face alone (a cap: isMarkedCap() with faceAlone; an edge piece: its one mark a
 * face) and one up-to face was saved with its foot. Kept when exactly one face lies under its
 * point now, the saved one (sameUpToFaces()), and the straight path from the saved foot to the
 * point now, seen along the sweep in that face's owner's frame, stays inside it
 * (\a input.upToPathInside); CantTell when that path can't be told; else Left. Empty when the test
 * doesn't apply (another kind of piece, no foot saved, no hooks, a copy of the piece: a copy
 * section after its projection, review prA1c-r1) or the up-to faces can't be told now (a datum
 * plane; a shape not made under its placement). The caller checks the twins.
 */
std::optional<OnUpToFace> placeOnUpToFace(
    const SolveInput& input,
    const ElementFingerprint& saved,
    const std::string& name,
    const ElementFingerprint& now,
    double eps
)
{
    if (!input.upToFacesAt || !input.upToPathInside || saved.upToFaces.size() != 1
        || !saved.upToFaces.front().foot || saved.type != now.type || projectionTag(name) <= 0) {
        return std::nullopt;
    }
    if (saved.type == 'F') {
        if (!isMarkedCap(name, true)) {
            return std::nullopt;
        }
    }
    else {
        const auto marks = pieceMarks(name);
        if (saved.type != 'E' || marks.size() != 1) {
            return std::nullopt;
        }
        const auto markSections = NameAncestry::splitSections(marks.front());
        if (markSections.empty() || decodeSection(markSections.back()).elementType != 'F') {
            return std::nullopt;
        }
    }
    const auto point = upToPointOf(now);
    std::vector<ElementFingerprint::UpToFace> under;
    std::vector<ElementFingerprint::UpToFace> every;
    if (!point || !input.upToFacesAt(name, *point, under, every)) {
        return std::nullopt;
    }
    if (under.size() != 1 || !sameUpToFaces(saved.upToFaces, under, every, eps, input.tolerances)) {
        return OnUpToFace::Left;
    }
    const auto inside = input.upToPathInside(name, saved.upToFaces.front(), *point);
    return !inside ? OnUpToFace::CantTell : *inside ? OnUpToFace::Kept : OnUpToFace::Left;
}

/* True if \a name's element is \a oldName's piece of a far edge after others of its pieces went
 * (PR 366 round 3): the names are the same but in one section, a marked piece's in both (PRJ,
 * MOD, ORD), with the same marks, where the duplicate counter (count (count - 1) / 2 + place,
 * TopoShapeMapper.cpp) counts fewer pieces in \a name. The count renames every piece, so a
 * piece left alone on its face of the up-to shape (the hole's fill piece when the piece left of
 * the hole goes) has the old name nowhere. A piece coming instead may take a face's index, the
 * marks, from another face (a face added to an up-to shell without names): never this rule's.
 * The caller corroborates by geometry.
 */
bool isFewerPiecesOf(std::string_view name, std::string_view oldName)
{
    const auto sections = NameAncestry::splitSections(name);
    const auto oldSections = NameAncestry::splitSections(oldName);
    if (sections.empty() || sections.size() != oldSections.size()) {
        return false;
    }
    // The count from a counter: the largest n with n (n - 1) / 2 <= counter
    auto countOf = [](const std::string& counter) {
        int value = 0;
        for (const char c : counter) {
            if (c < '0' || c > '9' || value > 1000000) {
                return 0;
            }
            value = value * 10 + (c - '0');
        }
        int count = 1;
        while ((count + 1) * count / 2 <= value) {
            ++count;
        }
        return value > 0 ? count : 0;
    };
    bool fewer = false;
    for (std::size_t i = 0; i < sections.size(); ++i) {
        if (sections[i] == oldSections[i]) {
            continue;
        }
        if (fewer) {
            return false;
        }
        const DecodedMappedSection& x = decodeSection(sections[i]);
        const DecodedMappedSection& y = decodeSection(oldSections[i]);
        if (!y.hasMapperFlag(MAPPER_FLAG_PROJECTION) || !y.hasMapperFlag(MAPPER_FLAG_MODIFIED)
            || !y.hasMapperFlag(orderedFlag) || y.connectedElements.empty()
            || sortedFlags(x) != sortedFlags(y) || x.opCode != y.opCode
            || x.referenceIDs != y.referenceIDs || x.iterationTag != y.iterationTag
            || x.index != y.index || x.elementType != y.elementType
            || x.linkedNames != y.linkedNames || x.connectedElements != y.connectedElements) {
            return false;
        }
        const int count = countOf(x.duplicateCount);
        const int oldCount = countOf(y.duplicateCount);
        if (count == 0 || oldCount == 0 || count >= oldCount) {
            return false;
        }
        fewer = true;
    }
    return fewer;
}

// The element of a target without an element map that the IDX section \a section names, when it
// carries the target's tag \a tag (Q5): the section's index name (`Edge11`), if it is of type
// \a type; otherwise empty.
std::string maplessElement(
    std::string_view section,
    const std::string& tag,
    const std::string& type
)
{
    if (tag.empty() || section.empty()) {
        return {};
    }
    const auto& decoded = decodeSection(section);
    if (decoded.iterationTag != tag || decoded.referenceIDs.size() != 1) {
        return {};
    }
    const std::string& index = decoded.referenceIDs.front();
    std::size_t end = index.size();
    while (end > 0 && index[end - 1] >= '0' && index[end - 1] <= '9') {
        --end;
    }
    if (end == index.size() || end != type.size() || index.compare(0, end, type) != 0) {
        return {};
    }
    return index;
}

std::string formatDistance(double value)
{
    std::ostringstream ss;
    ss.imbue(std::locale::classic());
    ss.precision(3);
    ss << std::fixed << value;
    return ss.str();
}

bool relativelyEqual(double a, double b, double tolerance)
{
    return std::abs(a - b) <= tolerance * std::max({std::abs(a), std::abs(b), 1e-12});
}

struct Nearest
{
    int index = -1;
    double nearest = 0.0;
    double second = -1.0;  // -1: no other candidate
    double dMax = 0.0;
};

Nearest findNearest(
    const ElementFingerprint& saved,
    const std::vector<ElementFingerprint>& candidates,
    double diagonal,
    const GeometryTolerances& tolerances
)
{
    Nearest result;
    result.dMax = tolerances.distance * diagonal;
    if (!saved.center || !(diagonal > 0.0)) {
        return result;
    }
    int best = -1;
    double bestDistance = 0.0;
    double secondDistance = -1.0;
    for (std::size_t i = 0; i < candidates.size(); ++i) {
        if (!candidates[i].center) {
            continue;
        }
        double distance = Base::Distance(*saved.center, *candidates[i].center);
        if (best < 0 || distance < bestDistance) {
            secondDistance = best < 0 ? secondDistance : bestDistance;
            best = static_cast<int>(i);
            bestDistance = distance;
        }
        else if (secondDistance < 0.0 || distance < secondDistance) {
            secondDistance = distance;
        }
    }
    result.nearest = bestDistance;
    result.second = secondDistance;
    if (best < 0 || bestDistance > result.dMax) {
        return result;
    }
    if (secondDistance >= 0.0
        && (secondDistance < tolerances.gapFactor * bestDistance || secondDistance < result.dMax)) {
        return result;
    }
    const auto& candidate = candidates[best];
    if (saved.size.has_value() != candidate.size.has_value()
        || (saved.size && !relativelyEqual(*saved.size, *candidate.size, tolerances.size))) {
        return result;
    }
    result.index = best;
    return result;
}

}  // namespace

// G3 (ops#127, design note N2 5.2): whether a piece of a split element holds the saved element's
// centre. A line piece: the centre lies on its line, within half its length; an arc piece: the
// centre's direction from the circle's centre lies within the arc's angular half-width (a saved
// arc's centre of mass lies on its bisector); a planar face piece: the centre lies in its box. All
// grown by ε = continuation × max(1, diagonal), the continuation's own ε. Other kinds hold none.
bool holdsCentre(const ElementFingerprint& saved,
                 const ElementFingerprint& piece,
                 double diagonal,
                 double continuation)
{
    if (!saved.center || !piece.center || !piece.isValid() || saved.type != piece.type
        || saved.kind != piece.kind) {
        return false;
    }
    const double eps = continuation * std::max(1.0, diagonal);
    const Base::Vector3d s = *saved.center;
    const Base::Vector3d c = *piece.center;
    if (piece.type == 'E' && piece.kind == "Line" && piece.direction && piece.size) {
        Base::Vector3d d = *piece.direction;
        if (d.Length() <= 0.0) {
            return false;
        }
        d.Normalize();
        const Base::Vector3d v = s - c;
        const double along = v * d;
        const Base::Vector3d across = v - d * along;
        return across.Length() <= eps && std::abs(along) <= *piece.size / 2.0 + eps;
    }
    if (piece.type == 'E' && piece.kind == "Circle" && piece.location && piece.size
        && !piece.radii.empty() && piece.radii.front() > 0.0) {
        const double r = piece.radii.front();
        const Base::Vector3d a = s - *piece.location;
        const Base::Vector3d b = c - *piece.location;
        if (a.Length() <= eps || b.Length() <= eps) {
            return false;
        }
        return a.GetAngle(b) <= *piece.size / (2.0 * r) + eps / r;
    }
    if (piece.type == 'F' && piece.kind == "Plane" && piece.extentMin && piece.extentMax) {
        const Base::Vector3d& lo = *piece.extentMin;
        const Base::Vector3d& hi = *piece.extentMax;
        return s.x >= lo.x - eps && s.x <= hi.x + eps && s.y >= lo.y - eps && s.y <= hi.y + eps
            && s.z >= lo.z - eps && s.z <= hi.z + eps;
    }
    return false;
}

bool coversExtent(const ElementFingerprint& saved,
                  const ElementFingerprint& element,
                  double diagonal,
                  double continuation)
{
    if (!saved.center || !element.center || !element.isValid() || saved.type != element.type
        || saved.kind != element.kind || !saved.size || !element.size) {
        return false;
    }
    const double eps = continuation * std::max(1.0, diagonal);
    const Base::Vector3d s = *saved.center;
    const Base::Vector3d c = *element.center;
    if (element.type == 'E' && element.kind == "Line" && element.direction && saved.direction) {
        Base::Vector3d d = *element.direction;
        Base::Vector3d sd = *saved.direction;
        if (d.Length() <= 0.0 || sd.Length() <= 0.0) {
            return false;
        }
        d.Normalize();
        sd.Normalize();
        // Both ends of the saved segment on the element's line, within its length
        for (double side : {-1.0, 1.0}) {
            const Base::Vector3d v = s + sd * (side * *saved.size / 2.0) - c;
            const double along = v * d;
            if ((v - d * along).Length() > eps || std::abs(along) > *element.size / 2.0 + eps) {
                return false;
            }
        }
        return true;
    }
    if (element.type == 'E' && element.kind == "Circle" && element.location && saved.location
        && !element.radii.empty() && !saved.radii.empty() && element.radii.front() > 0.0) {
        // On the same circle, and the saved arc's whole angular range within the element's
        const double r = element.radii.front();
        if (std::abs(saved.radii.front() - r) > eps
            || Base::Distance(*saved.location, *element.location) > eps) {
            return false;
        }
        const Base::Vector3d a = s - *element.location;
        const Base::Vector3d b = c - *element.location;
        if (a.Length() <= eps || b.Length() <= eps) {
            return false;
        }
        return a.GetAngle(b) + *saved.size / (2.0 * r) <= *element.size / (2.0 * r) + eps / r;
    }
    if (element.type == 'F' && element.kind == "Plane" && element.extentMin && element.extentMax
        && saved.extentMin && saved.extentMax) {
        // The box is necessary but not enough: a piece that lost a part inside its box (an L, a
        // U) still spans it. The area, no smaller than the saved one, rules out such a piece
        // when nothing grew elsewhere
        const Base::Vector3d& lo = *element.extentMin;
        const Base::Vector3d& hi = *element.extentMax;
        const Base::Vector3d& slo = *saved.extentMin;
        const Base::Vector3d& shi = *saved.extentMax;
        return slo.x >= lo.x - eps && slo.y >= lo.y - eps && slo.z >= lo.z - eps
            && shi.x <= hi.x + eps && shi.y <= hi.y + eps && shi.z <= hi.z + eps
            && *element.size >= *saved.size - eps * std::max(1.0, diagonal);
    }
    return false;
}

namespace
{

std::string describeNearest(const Nearest& nearest)
{
    std::string text = "nearest " + formatDistance(nearest.nearest);
    if (nearest.second >= 0.0) {
        text += ", second " + formatDistance(nearest.second);
    }
    return text + ", d_max " + formatDistance(nearest.dMax);
}

// The angle between two directions, either sense, as intrinsicAgrees() measures it.
double lineAngle(Base::Vector3d a, Base::Vector3d b)
{
    a.Normalize();
    b.Normalize();
    return std::atan2((a % b).Length(), std::abs(a * b));
}

constexpr double Pi = 3.14159265358979323846;

/* Where an edge was, from the fingerprint saved with its reference (the continuation, Task 2 PR
 * 7): an extent of arc length [0, length] along the old curve, a line or (PR 7b) a circle. A
 * piece of the target lies on the old curve when interval() gives its extent there; everything
 * after that (containment, a run-past, the overlap check) compares intervals.
 */
struct OldExtent
{
    bool circle = false;
    // A line: from origin along the unit direction axis. A circle: centre origin, unit axis,
    // radius, and arc length s = radius * (theta + alpha), theta being the angle from the old
    // arc's bisector towards axis x bisector, alpha half the old arc's angle.
    Base::Vector3d origin;
    Base::Vector3d axis;
    Base::Vector3d bisector;
    double radius = 0.0;
    double alpha = 0.0;
    double length = 0.0;
    // A full circle: intervals wrap at length, and s starts opposite the hit's middle.
    bool cyclic = false;
    double eps = 0.0;
    double angle = 0.0;

    // \a hit, the exact element, places a full circle's start of s.
    static std::optional<OldExtent> of(
        const ElementFingerprint& saved,
        double eps,
        const GeometryTolerances& tolerances,
        const ElementFingerprint* hit = nullptr
    )
    {
        if (!saved.isValid() || saved.type != 'E' || !saved.size || !saved.center
            || !saved.direction || saved.direction->Length() <= 0.0 || !(*saved.size > eps)) {
            return std::nullopt;
        }
        OldExtent extent;
        extent.axis = *saved.direction;
        extent.axis.Normalize();
        extent.length = *saved.size;
        extent.eps = eps;
        extent.angle = tolerances.angle;
        if (saved.kind == "Line") {
            // A line edge's centre of mass is its midpoint.
            extent.origin = *saved.center - extent.axis * (extent.length / 2.0);
            return extent;
        }
        if (saved.kind != "Circle" || !saved.location || saved.radii.size() != 1
            || !(saved.radii.front() > eps)) {
            return std::nullopt;  // another curve, or a version-1 circle: not locatable
        }
        extent.circle = true;
        extent.origin = *saved.location;
        extent.radius = saved.radii.front();
        const double full = 2.0 * Pi * extent.radius;
        if (extent.length >= full - eps) {
            // A full circle: s starts opposite the hit's middle, so the hit is one interval.
            // Without a hit that shows one (a collapse checks containment only), any start does.
            extent.cyclic = true;
            extent.length = full;
            extent.alpha = Pi;
            Base::Vector3d toward;
            if (hit && hit->center) {
                toward = extent.inPlane(*hit->center - extent.origin);
            }
            if (toward.Length() < 1e-6 * extent.radius) {
                toward = extent.inPlane(std::abs(extent.axis.x) < 0.9 ? Base::Vector3d(1, 0, 0)
                                                                      : Base::Vector3d(0, 1, 0));
            }
            extent.bisector = toward;
            extent.bisector.Normalize();
            return extent;
        }
        // The centre of mass lies on the arc's bisector, r sin(alpha) / alpha from the centre.
        extent.alpha = extent.length / (2.0 * extent.radius);
        Base::Vector3d toward = extent.inPlane(*saved.center - extent.origin);
        if (toward.Length() < 1e-6 * extent.radius) {
            // Nearly a full circle: its bisector isn't reliable.
            return std::nullopt;
        }
        extent.bisector = toward;
        extent.bisector.Normalize();
        return extent;
    }

    Base::Vector3d inPlane(const Base::Vector3d& v) const
    {
        return v - axis * (v * axis);
    }

    // The piece's extent along the old curve, sorted; nothing if it doesn't lie on that curve. A
    // line: the same direction within the angle, both ends within eps of the line. A circle: a
    // circle of the same axis (within the angle), radius, centre and plane (within eps).
    std::optional<std::pair<double, double>> interval(const ElementFingerprint& piece) const
    {
        if (!piece.isValid() || piece.type != 'E' || !piece.size || !piece.center
            || !piece.direction || piece.direction->Length() <= 0.0
            || lineAngle(axis, *piece.direction) > angle) {
            return std::nullopt;
        }
        if (circle) {
            return arcInterval(piece);
        }
        if (piece.kind != "Line") {
            return std::nullopt;
        }
        Base::Vector3d direction = *piece.direction;
        direction.Normalize();
        std::pair<double, double> range;
        for (int end = 0; end < 2; ++end) {
            Base::Vector3d point = *piece.center
                + direction * ((end == 0 ? -0.5 : 0.5) * *piece.size);
            Base::Vector3d offset = point - origin;
            double t = offset * axis;
            if ((offset - axis * t).Length() > eps) {
                return std::nullopt;
            }
            (end == 0 ? range.first : range.second) = t;
        }
        if (range.first > range.second) {
            std::swap(range.first, range.second);
        }
        return range;
    }

    std::optional<std::pair<double, double>> arcInterval(const ElementFingerprint& piece) const
    {
        if (piece.kind != "Circle" || !piece.location || piece.radii.size() != 1
            || std::abs(piece.radii.front() - radius) > eps
            || Base::Distance(*piece.location, origin) > eps) {
            return std::nullopt;
        }
        Base::Vector3d offset = *piece.center - origin;
        if (std::abs(offset * axis) > eps) {
            return std::nullopt;
        }
        const double full = 2.0 * Pi * radius;
        Base::Vector3d toward = inPlane(offset);
        if (toward.Length() < 1e-6 * radius) {
            // A whole circle, or nearly: all of it.
            return std::make_pair(radius * (alpha - Pi), radius * (alpha + Pi));
        }
        const double half = *piece.size / (2.0 * radius);
        const double beta = std::atan2(toward * (axis % bisector), toward * bisector);
        std::pair<double, double> range {radius * (beta - half + alpha),
                                         radius * (beta + half + alpha)};
        if (cyclic) {
            // Starting within one turn; it may end past length (wrapping).
            double shift = std::floor(range.first / full) * full;
            range.first -= shift;
            range.second -= shift;
            return range;
        }
        // The turn that overlaps the old arc most.
        std::pair<double, double> best = range;
        for (double shift : {-full, full}) {
            std::pair<double, double> moved {range.first + shift, range.second + shift};
            if (overlap(moved) > overlap(best)) {
                best = moved;
            }
        }
        return best;
    }

    bool within(const std::pair<double, double>& range) const
    {
        if (cyclic) {
            return range.second - range.first <= length + eps;
        }
        return range.first >= -eps && range.second <= length + eps;
    }

    // The length the range shares with [0, length].
    double overlap(const std::pair<double, double>& range) const
    {
        if (cyclic) {
            return std::min(range.second - range.first, length);
        }
        return std::min(range.second, length) - std::max(range.first, 0.0);
    }

    // Whether two of \a ranges (the pieces of one edge) overlap by more than eps.
    bool overlapping(std::vector<std::pair<double, double>> ranges) const
    {
        std::sort(ranges.begin(), ranges.end());
        for (std::size_t r = 1; r < ranges.size(); ++r) {
            if (ranges[r - 1].second - ranges[r].first > eps) {
                return true;
            }
        }
        // Around a full circle, the last piece may wrap onto the first.
        return cyclic && !ranges.empty()
            && ranges.back().second - length - ranges.front().first > eps;
    }
};

}  // namespace

bool hitWithinOldEdge(
    const ElementFingerprint& saved,
    const ElementFingerprint& now,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    const double eps = distance * std::max(1.0, diagonal);
    auto extent = OldExtent::of(saved, eps, tolerances, &now);
    if (!extent) {
        return false;
    }
    auto range = extent->interval(now);
    return range && extent->within(*range)
        && range->second - range->first < extent->length - eps;
}

namespace
{

bool isPlane(const ElementFingerprint& fp)
{
    return fp.isValid() && fp.type == 'F' && fp.kind == "Plane" && fp.size && fp.center
        && fp.direction && fp.direction->Length() > 0.0;
}

// An outline's span seen along the unit direction (PR 366 round 5)
std::pair<double, double> spanAlong(
    const std::vector<Base::Vector3d>& outline,
    const Base::Vector3d& direction
)
{
    double low = std::numeric_limits<double>::infinity();
    double high = -low;
    for (const auto& point : outline) {
        low = std::min(low, point * direction);
        high = std::max(high, point * direction);
    }
    return {low, high};
}

// Whether two faces' outlines share no area, seen along the old one's normal (PR 366 round 5):
// on an axis across a side of either, their spans share no length (two convex outlines that
// don't overlap have such an axis). A face lifted along the normal keeps its place. Empty when
// the old outline spans no area. Round 6: seen along the unit \a sweep instead when there is one
// (the direction a Pad or Pocket swept its profile along, which made the pieces), unless the old
// face lies along it: the tilted plate's normal, beside lower plates, made two pieces side by
// side overlap. A piece lifted along the sweep keeps its place.
std::optional<bool> outlinesApart(
    const std::vector<Base::Vector3d>& old,
    const std::vector<Base::Vector3d>& now,
    double eps,
    const std::optional<Base::Vector3d>& sweep = std::nullopt
)
{
    if (old.size() < 3 || now.size() < 2) {
        return std::nullopt;
    }
    Base::Vector3d normal;
    for (std::size_t i = 1; i + 1 < old.size(); ++i) {
        normal += (old[i] - old[0]) % (old[i + 1] - old[0]);
    }
    if (normal.Length() <= eps * eps) {
        return std::nullopt;
    }
    normal.Normalize();
    if (sweep && std::abs(normal * *sweep) > 0.01) {
        normal = *sweep;
    }
    const auto oldOutline = ElementFingerprint::convexOutline(old, normal);
    const auto outline = ElementFingerprint::convexOutline(now, normal);
    auto separates = [&](const std::vector<Base::Vector3d>& sides) {
        const std::size_t count = sides.size() > 2 ? sides.size() : 1;
        for (std::size_t i = 0; i < count && sides.size() >= 2; ++i) {
            Base::Vector3d axis = normal % (sides[(i + 1) % sides.size()] - sides[i]);
            if (axis.Length() <= eps) {
                continue;
            }
            axis.Normalize();
            const auto [oldLow, oldHigh] = spanAlong(oldOutline, axis);
            const auto [low, high] = spanAlong(outline, axis);
            if (std::min(oldHigh, high) - std::max(oldLow, low) <= eps) {
                return true;
            }
        }
        return false;
    };
    return separates(oldOutline) || separates(outline);
}

// Whether an old straight piece of a far edge lies apart from a face beside the piece that took
// its name (PR 366 round 6), seen along the unit \a sweep: on an axis across a side of the face's
// outline other than the piece's own line, the old piece's span and the face's share no length.
// Along its own line, the way across the seams, a slanted piece slid onto the next plate still
// shares a length with the old one; the cap beside it ends at the seam the old piece lies
// beyond. A piece moved across its line, A grown taller or shorter, is apart from that cap, if
// at all, only beyond the piece's own line. False when the face spans no area seen so, and when
// either piece isn't straight (a B-spline plate's far edge may be a straight B-spline curve).
bool apartBesideLine(
    const std::vector<Base::Vector3d>& old,
    const std::vector<Base::Vector3d>& face,
    const std::vector<Base::Vector3d>& piece,
    const Base::Vector3d& sweep,
    double eps
)
{
    auto straight = [&](const std::vector<Base::Vector3d>& points) {
        if (points.size() < 2) {
            return false;
        }
        Base::Vector3d chord = points.back() - points.front();
        const double length = chord.Length();
        if (length <= eps) {
            return false;
        }
        chord /= length;
        const double tolerance = std::max(eps, length * 1e-6);
        return std::all_of(points.begin(), points.end(), [&](const Base::Vector3d& point) {
            const Base::Vector3d offset = point - points.front();
            return (offset - chord * (offset * chord)).Length() <= tolerance;
        });
    };
    if (face.size() < 3 || !straight(old) || !straight(piece)) {
        return false;
    }
    // The piece's line, seen along the sweep
    auto flat = [&](const Base::Vector3d& vector) {
        return vector - sweep * (vector * sweep);
    };
    Base::Vector3d along = flat(piece.back() - piece.front());
    if (along.Length() <= eps) {
        return false;
    }
    along.Normalize();
    const auto outline = ElementFingerprint::convexOutline(face, sweep);
    for (std::size_t i = 0; outline.size() >= 3 && i < outline.size(); ++i) {
        const Base::Vector3d side = flat(outline[(i + 1) % outline.size()] - outline[i]);
        // A side along the piece's line, or parallel to it (a parallelogram's other side), is seen
        // across the line, as the piece's own is
        if (side.Length() <= eps || (side % along).Length() <= eps * std::max(1.0, side.Length())) {
            continue;
        }
        Base::Vector3d axis = sweep % side;
        if (axis.Length() <= eps) {
            continue;
        }
        axis.Normalize();
        const auto [oldLow, oldHigh] = spanAlong(old, axis);
        const auto [low, high] = spanAlong(outline, axis);
        if (std::min(oldHigh, high) - std::max(oldLow, low) <= eps) {
            return true;
        }
    }
    return false;
}

}  // namespace

bool planeAgrees(
    const ElementFingerprint& saved,
    const ElementFingerprint& face,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    if (!isPlane(saved) || !isPlane(face)) {
        return false;
    }
    Base::Vector3d normal = *saved.direction;
    Base::Vector3d other = *face.direction;
    normal.Normalize();
    other.Normalize();
    // A plane's normal keeps its sense: a face of the opposite side isn't in this plane.
    if (std::atan2((normal % other).Length(), normal * other) > tolerances.angle) {
        return false;
    }
    const double eps = distance * std::max(1.0, diagonal);
    return std::abs((*face.center - *saved.center) * normal) <= eps;
}

ExtentRelation faceExtentRelation(
    const ElementFingerprint& saved,
    const ElementFingerprint& face,
    double diagonal,
    double distance
)
{
    if (!saved.extentMin || !saved.extentMax || !face.extentMin || !face.extentMax) {
        return ExtentRelation::Unknown;
    }
    const double eps = distance * std::max(1.0, diagonal);
    bool inside = true;
    for (int axis = 0; axis < 3; ++axis) {
        const double oldLow = (*saved.extentMin)[axis];
        const double oldHigh = (*saved.extentMax)[axis];
        const double low = (*face.extentMin)[axis];
        const double high = (*face.extentMax)[axis];
        const double overlap = std::min(oldHigh, high) - std::max(oldLow, low);
        if (overlap < -eps || (overlap <= eps && oldHigh - oldLow > eps && high - low > eps)) {
            return ExtentRelation::Outside;
        }
        if (low < oldLow - eps || high > oldHigh + eps) {
            inside = false;
        }
    }
    return inside ? ExtentRelation::Inside : ExtentRelation::Overlapping;
}

bool faceWithinOldPlane(
    const ElementFingerprint& saved,
    const ElementFingerprint& now,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    return planeAgrees(saved, now, diagonal, tolerances, distance)
        && *now.size < *saved.size * (1.0 - distance);
}

bool intrinsicAgrees(
    const ElementFingerprint& saved,
    const ElementFingerprint& candidate,
    const GeometryTolerances& tolerances
)
{
    if (!saved.isValid() || !candidate.isValid() || saved.type != candidate.type
        || saved.kind != candidate.kind) {
        return false;
    }
    if (saved.direction.has_value() != candidate.direction.has_value()) {
        return false;
    }
    if (saved.direction) {
        Base::Vector3d a = *saved.direction;
        Base::Vector3d b = *candidate.direction;
        if (a.Length() <= 0.0 || b.Length() <= 0.0) {
            return false;
        }
        a.Normalize();
        b.Normalize();
        double cosine = a * b;
        // A plane's normal carries the face's orientation; an axis or a line has no sense (the
        // producer normalizes its sign, which a component near 0 can flip).
        if (!(saved.type == 'F' && saved.kind == "Plane")) {
            cosine = std::abs(cosine);
        }
        // The angle from the cross product: acos loses precision near 0.
        double angle = std::atan2((a % b).Length(), cosine);
        if (angle > tolerances.angle) {
            return false;
        }
    }
    if (saved.radii.size() != candidate.radii.size()) {
        return false;
    }
    for (std::size_t i = 0; i < saved.radii.size(); ++i) {
        if (!relativelyEqual(saved.radii[i], candidate.radii[i], tolerances.radius)) {
            return false;
        }
    }
    return true;
}

bool atSamePlace(
    const ElementFingerprint& saved,
    const ElementFingerprint& now,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    // The kind, direction and radii as tier 2 compares them.
    if (!intrinsicAgrees(saved, now, tolerances)) {
        return false;
    }
    const double eps = distance * std::max(1.0, diagonal);
    if (saved.size.has_value() != now.size.has_value()
        || (saved.size
            && std::abs(*saved.size - *now.size)
                > tolerances.placeSize
                    * std::max({std::abs(*saved.size), std::abs(*now.size), eps}))) {
        return false;
    }
    if (saved.center.has_value() != now.center.has_value()
        || (saved.center && Base::Distance(*saved.center, *now.center) > eps)) {
        return false;
    }
    if (saved.location && now.location && Base::Distance(*saved.location, *now.location) > eps) {
        return false;
    }
    if (saved.extentMin && saved.extentMax && now.extentMin && now.extentMax
        && (Base::Distance(*saved.extentMin, *now.extentMin) > eps
            || Base::Distance(*saved.extentMax, *now.extentMax) > eps)) {
        return false;
    }
    return true;
}

bool isOrderedName(std::string_view name)
{
    return isOrdered(name);
}

bool isMarkedCapName(std::string_view name)
{
    return isMarkedCap(name, true);
}

bool isMarkedPieceName(std::string_view name)
{
    return isMarkedPiece(name);
}

bool isMarkedPieceOf(std::string_view name, long tag)
{
    if (tag == 0) {
        return false;
    }
    const std::string own = std::to_string(tag);
    const std::string negated = std::to_string(-tag);
    const auto sections = NameAncestry::splitSections(name);
    return std::any_of(sections.begin(), sections.end(), [&](std::string_view section) {
        const DecodedMappedSection& decoded = decodeSection(section);
        return (decoded.elementType == 'F' || decoded.elementType == 'E')
            && decoded.hasMapperFlag(MAPPER_FLAG_PROJECTION)
            && decoded.hasMapperFlag(MAPPER_FLAG_MODIFIED) && !decoded.connectedElements.empty()
            && (decoded.iterationTag == own || decoded.iterationTag == negated);
    });
}

long projectionTag(std::string_view name)
{
    const auto sections = NameAncestry::splitSections(name);
    for (auto section = sections.begin(); section != sections.end(); ++section) {
        const DecodedMappedSection& decoded = decodeSection(*section);
        if (!decoded.hasMapperFlag(MAPPER_FLAG_PROJECTION) || !hasTag(decoded)) {
            continue;
        }
        // A copy of the piece (a pattern's or a mirror's instance, a boundary, a second side):
        // its place isn't the one the extrusion made (review prA1c-r1's MirrorCopyAcrossHole)
        if (std::any_of(std::next(section), sections.end(), [](const auto later) {
                return isCopySection(decodeSection(later));
            })) {
            return 0;
        }
        long tag = 0;
        for (const char c : decoded.iterationTag) {
            if (c < '0' || c > '9' || tag > 100000000L) {
                return 0;
            }
            tag = tag * 10 + (c - '0');
        }
        return tag;
    }
    return 0;
}

std::optional<Base::Vector3d> upToPointOf(const ElementFingerprint& fingerprint)
{
    if (fingerprint.type == 'E' && !fingerprint.outline.empty()) {
        const auto& outline = fingerprint.outline;
        if (outline.size() == 2) {
            return (outline.front() + outline.back()) / 2.0;
        }
        return outline[outline.size() / 2];
    }
    if (fingerprint.inside) {
        return fingerprint.inside;
    }
    return fingerprint.center;
}

bool isCounterSiblingName(std::string_view name, std::string_view other, bool copySiblings)
{
    return isCounterSibling(name, other, copySiblings);
}

bool isTwinName(std::string_view name, std::string_view other)
{
    return name != other && sameUpToOrder(name, other, true);
}

bool isOrderKeyedName(std::string_view name)
{
    return isOrderKeyed(name);
}

const char* otherOriginOf(const std::vector<std::string>& names,
                          std::string_view oldName,
                          bool sameMaker)
{
    const auto old = NameAncestry::sourceTags(oldName);
    const bool shared = std::any_of(names.begin(), names.end(), [&](const auto& name) {
        const auto tags = NameAncestry::sourceTags(name);
        return std::any_of(tags.begin(), tags.end(), [&](const auto& tag) {
            return std::binary_search(old.begin(), old.end(), tag);
        });
    });
    if (!shared) {
        return "source";
    }
    const std::string maker = sameMaker ? NameAncestry::makerTag(oldName) : std::string();
    if (!maker.empty() && std::none_of(names.begin(), names.end(), [&](const auto& name) {
            return NameAncestry::hasLineageTag(name, maker);
        })) {
        return "maker";
    }
    return nullptr;
}

bool mayBeQuietAtPlace(const std::vector<std::string>& names,
                       std::string_view oldName,
                       bool sameMaker)
{
    if (oldName.empty()) {
        return true;
    }
    // The twin-pick rule (ops#503 D1): a twin of the old element is never quiet, a pure
    // renumbering included, though it sits at the old place by definition
    if (std::any_of(names.begin(), names.end(), [&](const auto& name) {
            return isTwinName(name, oldName);
        })) {
        return false;
    }
    // XP's source condition (I-S6): an element of another source at the old place is policy
    // D's new sketch object, which the quiet level would hide
    return otherOriginOf(names, oldName, sameMaker) == nullptr;
}

bool lostOldSources(const std::vector<std::string>& names, std::string_view oldName)
{
    if (oldName.empty()
        || std::any_of(names.begin(), names.end(), [&](const auto& name) {
               return NameAncestry::isPieceOf(name, oldName)
                   || NameAncestry::isIndexPieceOf(name, oldName);
           })) {
        return false;
    }
    return lostASource(names, requiredSourcesOf(oldName));
}

bool mayBeAtPlace(
    const ElementFingerprint& saved,
    const ElementFingerprint& intrinsic,
    const std::optional<Base::Vector3d>& anchor,
    double diagonal,
    const GeometryTolerances& tolerances,
    double distance
)
{
    // What atSamePlace() compares first, measured the same way.
    if (!intrinsicAgrees(saved, intrinsic, tolerances)) {
        return false;
    }
    const double eps = distance * std::max(1.0, diagonal);
    if (saved.location && intrinsic.location
        && Base::Distance(*saved.location, *intrinsic.location) > eps) {
        return false;
    }
    if (!anchor || !saved.center) {
        return true;
    }
    // The element's centre lies on its vertex, line or plane, and atSamePlace() wants the saved
    // centre within eps of it: 2 eps leaves room for the centre's integration.
    const Base::Vector3d offset = *saved.center - *anchor;
    if (saved.type == 'V') {
        return offset.Length() <= 2 * eps;
    }
    if (!intrinsic.direction || intrinsic.direction->Length() <= 0.0) {
        return true;
    }
    Base::Vector3d axis = *intrinsic.direction;
    axis.Normalize();
    if (saved.type == 'F' && saved.kind == "Plane") {
        return std::abs(offset * axis) <= 2 * eps;
    }
    if (saved.type == 'E' && saved.kind == "Line") {
        return (offset - axis * (offset * axis)).Length() <= 2 * eps;
    }
    return true;
}

int extrinsicNearest(
    const ElementFingerprint& saved,
    const std::vector<ElementFingerprint>& candidates,
    double diagonal,
    const GeometryTolerances& tolerances
)
{
    return findNearest(saved, candidates, diagonal, tolerances).index;
}

std::vector<SolveOutcome> solveOwner(const SolveInput& input)
{
    NameAncestry ancestry(input.measure);
    std::vector<SolveOutcome> outcomes(input.entries.size());

    // Pools in index order, names sorted by bytes, duplicates merged; a dense element ID over
    // all types for the graph.
    struct Pool
    {
        std::vector<SolveInput::Element> elements;
        std::vector<int> ids;
        std::map<std::string, int> byName;  // name -> position in elements
        std::set<std::string> exact;        // index names resolved at tier 0
    };
    std::map<std::string, Pool> pools;
    std::vector<std::pair<std::string, int>> elementOfId;  // ID -> (type, position)
    std::map<std::string, std::map<std::string, std::vector<std::string>>> mergedByType;
    for (const auto& [type, elements] : input.pool) {
        auto& merged = mergedByType[type];
        for (const auto& element : elements) {
            auto& names = merged[element.index];
            names.insert(names.end(), element.names.begin(), element.names.end());
        }
    }
    // A target without an element map: the elements its IDX names point to, without names (Q5).
    for (const auto& entry : input.entries) {
        if (entry.exact) {
            continue;
        }
        std::string index = maplessElement(NameAncestry::indexSource(entry.oldName),
                                           input.maplessTag,
                                           entry.type);
        if (!index.empty()) {
            mergedByType[entry.type][index];
        }
    }
    for (auto& [type, merged] : mergedByType) {
        Pool& pool = pools[type];
        for (auto& [index, names] : merged) {
            std::sort(names.begin(), names.end());
            names.erase(std::unique(names.begin(), names.end()), names.end());
            pool.elements.push_back({index, std::move(names)});
        }
        std::sort(pool.elements.begin(), pool.elements.end(), byIndex);
        for (std::size_t k = 0; k < pool.elements.size(); ++k) {
            pool.ids.push_back(static_cast<int>(elementOfId.size()));
            elementOfId.emplace_back(type, static_cast<int>(k));
            for (const auto& name : pool.elements[k].names) {
                // A name names one element; keep the first by index if a map is inconsistent.
                pool.byName.emplace(name, static_cast<int>(k));
            }
        }
    }

    auto firstName = [](const SolveInput::Element& element) {
        return element.names.empty() ? std::string() : element.names.front();
    };

    // The pool elements' current fingerprints, measured on first use.
    std::map<std::string, ElementFingerprint> measured;
    auto fingerprintOfIndex = [&](const std::string& index) -> const ElementFingerprint& {
        auto it = measured.find(index);
        if (it == measured.end()) {
            ElementFingerprint fingerprint;
            if (input.fingerprintOf) {
                fingerprint = input.fingerprintOf(index);
            }
            it = measured.emplace(index, std::move(fingerprint)).first;
        }
        return it->second;
    };
    auto fingerprintOf = [&](const SolveInput::Element& element) -> const ElementFingerprint& {
        return fingerprintOfIndex(element.index);
    };
    auto positionOf = [](const Pool& pool, const std::string& index) {
        for (std::size_t k = 0; k < pool.elements.size(); ++k) {
            if (pool.elements[k].index == index) {
                return static_cast<int>(k);
            }
        }
        return -1;
    };

    // Tier 0.
    for (std::size_t i = 0; i < input.entries.size(); ++i) {
        const auto& entry = input.entries[i];
        if (!entry.exact) {
            continue;
        }
        auto& outcome = outcomes[i];
        outcome.status = SolveStatus::Exact;
        outcome.tier = 0;
        outcome.element = entry.exactElement;
        pools[entry.type].exact.insert(entry.exactElement);
        auto& pool = pools[entry.type];
        for (const auto& element : pool.elements) {
            if (element.index == entry.exactElement) {
                outcome.name = firstName(element);
            }
        }
    }

    // Entries decided before the graph: moved, collapsing and continued exact entries.
    std::vector<char> decidedEntry(input.entries.size(), 0);
    const double nan = std::numeric_limits<double>::quiet_NaN();

    // Moved (ops#105): an exact element that no longer sits where its saved fingerprint was,
    // while another element of its type sits there now. The name says one, the geometry the
    // other: never a pick. Moved alone (nothing at the old place), the name stands.
    {
        std::map<std::string, std::set<std::string>> reserved;  // by type: the places taken
        struct Hint
        {
            bool valid = false;
            ElementFingerprint intrinsic;
            std::optional<Base::Vector3d> anchor;
        };
        std::map<std::string, Hint> hints;  // by index, on first use
        for (std::size_t i = 0; i < input.entries.size(); ++i) {
            const auto& entry = input.entries[i];
            const ElementFingerprint& saved = entry.fingerprint;
            if (!entry.exact || !saved.isValid()) {
                continue;
            }
            Pool& pool = pools[entry.type];
            const std::string& hit = entry.exactElement;
            const int hitPosition = positionOf(pool, hit);
            auto here = [&](const ElementFingerprint& now) {
                return atSamePlace(saved,
                                   now,
                                   input.diagonal,
                                   input.tolerances,
                                   input.continuationDistance);
            };
            const ElementFingerprint& now = fingerprintOfIndex(hit);
            if (hitPosition < 0 || !now.isValid() || here(now)) {
                continue;  // unmoved, or nothing to compare
            }
            // The elements there: a cheap hint first rules most out, so that only the rest are
            // fingerprinted.
            auto mayBeHere = [&](const std::string& index) {
                if (!input.hintOf) {
                    return true;
                }
                auto it = hints.find(index);
                if (it == hints.end()) {
                    Hint hint;
                    hint.valid = input.hintOf(index, hint.intrinsic, hint.anchor);
                    it = hints.emplace(index, std::move(hint)).first;
                }
                const Hint& hint = it->second;
                return !hint.valid
                    || mayBeAtPlace(saved,
                                    hint.intrinsic,
                                    hint.anchor,
                                    input.diagonal,
                                    input.tolerances,
                                    input.continuationDistance);
            };
            std::vector<int> place;
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& index = pool.elements[k].index;
                if (static_cast<int>(k) != hitPosition && mayBeHere(index)
                    && here(fingerprintOfIndex(index))) {
                    place.push_back(static_cast<int>(k));
                }
            }
            const std::string& hitName = entry.exactName.empty()
                ? firstName(pool.elements[hitPosition])
                : entry.exactName;
            // A twin on a closed edge (decision 206) that moved breaks, whatever sits at its old
            // place: its place among its twins counts from the edge's seam, and an edit that turns
            // the seam past them gives its name to another twin, which may sit anywhere, the old
            // place included, or nowhere near it. Its own twin there (below) is no proof either.
            const bool closedTwin = isClosedTwin(hitName);
            // Twins (ops#360, PR 340 round 3): pieces of one far cap told apart only by their
            // place among them (the ORD flag and the duplicate counter) can trade names when an
            // edit turns them, so nothing sits at the old place. Round 5: the saved fingerprint
            // holds the twins' centroid, so the saved centre's offset from it is the old piece's
            // place among them. A counter sibling whose offset from the twins' centroid now is as
            // near the old offset as the hit's or nearer (a tie within 2 %, round 4) is where the
            // old piece went: the twins turned, about any point. A move of them all keeps every
            // offset, and a twin's growth moves the centroid by a fraction of it, so the hit's
            // offset stays the nearest and the name stands. An older record (no centroid, or
            // another number of twins) compares the centres themselves (round 3), which breaks
            // a move of the pair too: loud, never a pick.
            bool nearerTwin = false;
            std::vector<int> twins;
            bool twinsKeptShape = false;
            if (place.empty() && saved.center && now.center && isOrdered(hitName)) {
                const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
                std::vector<std::pair<int, Base::Vector3d>> siblings;
                Base::Vector3d centroid = *now.center;
                for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                    const auto& element = pool.elements[k];
                    const auto& names = element.names;
                    if (static_cast<int>(k) == hitPosition
                        || std::none_of(names.begin(), names.end(), [&](const auto& name) {
                               // the hit's own twins: no other copy's (ops#523)
                               return isCounterSibling(name, hitName, false);
                           })) {
                        continue;
                    }
                    const ElementFingerprint& sibling = fingerprintOfIndex(element.index);
                    if (sibling.center) {
                        siblings.emplace_back(static_cast<int>(k), *sibling.center);
                        centroid += *sibling.center;
                    }
                }
                centroid /= static_cast<double>(siblings.size() + 1);
                const bool offsets = saved.twinCentroid
                    && saved.twinCount == static_cast<int>(siblings.size() + 1);
                // The old place and the twins' places now, from their centroids or as they are
                const Base::Vector3d old = offsets ? *saved.center - *saved.twinCentroid
                                                   : *saved.center;
                const Base::Vector3d origin = offsets ? centroid : Base::Vector3d();
                const Base::Vector3d hitOffset = *now.center - origin;
                const double hitDistance = Base::Distance(old, hitOffset);
                // Round 6 (N9): the angular tie. A turn by a symmetry's angle (45 degrees for four
                // lobes) gives the old piece's place two readings, +45 and -45: the hit's and a
                // sibling's offsets lie at the same angle from the old offset. Off the twins'
                // centre their lengths differ a little, and the offsets' distances from the old
                // one can differ by more than the 2 % tie (4 % with the disc 0.3 mm off). So the
                // sibling ties also when its offset's angle from the old offset is within
                // tieDegrees of the hit's and the two offsets are about as long (within 25 %), as
                // two places one turn could take the old piece to. Round 7 (N12): with the disc
                // 0.35-0.37 of its radius off, the two readings lie 5-9 degrees apart, so the band
                // is 12 degrees. It assumes twins at least about twice the band apart (a ring of at
                // most 15): a turn ties, loudly, within half the band of the symmetry turn; closer
                // twins tie on smaller turns, down to moveDegrees. A merged twin moves the centroid
                // off the turn's centre and can need 16 degrees (ops#422). A hit within
                // moveDegrees of the old offset (a move, hitDistance 0) has no such tie; kept apart
                // from the band, so a symmetry turn no wider than the band (15 lobes and more)
                // still ties. Neither has a sibling on the same ray at another distance from the
                // centroid (twins in a row).
                constexpr double degrees = 180.0 / std::numbers::pi;
                auto angleFromOld = [&](const Base::Vector3d& offset) {
                    return std::atan2((old % offset).Length(), old * offset) * degrees;
                };
                const double tieDegrees = 12.0;
                const double moveDegrees = 5.0;
                const bool angular = offsets && old.Length() > eps && hitOffset.Length() > eps
                    && angleFromOld(hitOffset) > moveDegrees;
                const double hitAngle = angular ? angleFromOld(hitOffset) : 0.0;
                auto angularTie = [&](const Base::Vector3d& offset) {
                    const double shorter = std::min(offset.Length(), hitOffset.Length());
                    const double longer = std::max(offset.Length(), hitOffset.Length());
                    return angular && shorter > eps && shorter >= 0.75 * longer
                        && std::abs(angleFromOld(offset) - hitAngle) <= tieDegrees;
                };
                for (const auto& [k, centre] : siblings) {
                    if (Base::Distance(old, centre - origin) <= hitDistance * 1.02 + eps
                        || angularTie(centre - origin)) {
                        place.push_back(k);
                    }
                }
                nearerTwin = !place.empty();
                for (const auto& sibling : siblings) {
                    twins.push_back(sibling.first);
                }
                // The hit's size and its offset from the twins' centroid as they were: the set
                // moved as one, with whatever cut it
                twinsKeptShape = offsets && hitDistance <= eps && saved.size && now.size
                    && relativelyEqual(*saved.size, *now.size, 0.01);
            }
            // A far cap marked by one face of the up-to shape alone (ops#386, PR 366 round 2) that
            // moved with nothing at its old place, off its old centre, while another piece of the
            // same projection marked by a face alone holds that centre, is ambiguous. The marks of
            // an up-to shape without names are its faces' indexes: rebuilt with a face more, or
            // in another order, it gives the name to another piece, and the piece the reference
            // held shrank around its old centre. A piece that moved off its old centre onto
            // another kind of piece (the hole's fill piece onto a twin, the disc and the hole
            // moved together) keeps its name. Round 3: so does one whose neighbour holding the
            // centre reaches out of the old place (box), a seam moved across the old piece, the
            // neighbour's plate grown over it; the piece that shrank around its old centre lies
            // within it
            bool offCentre = false;
            if (place.empty() && isMarkedCap(hitName, true)) {
                const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
                const double reach = (saved.size ? std::sqrt(*saved.size) / 4.0 : 0.0) + eps;
                const bool centreLeft = saved.center && input.holdsPoint
                    && !input.holdsPoint(hit, *saved.center, reach);
                // Within the old piece's box; an older fingerprint without one (a face not planar),
                // no larger than the old piece (a plate grown over the old centre is larger)
                auto withinOldPlace = [&](const ElementFingerprint& other) {
                    if (!saved.extentMin || !saved.extentMax || !other.extentMin || !other.extentMax) {
                        return !saved.size || !other.size || *other.size <= *saved.size * 1.01;
                    }
                    const Base::Vector3d& low = *saved.extentMin;
                    const Base::Vector3d& high = *saved.extentMax;
                    const Base::Vector3d& otherLow = *other.extentMin;
                    const Base::Vector3d& otherHigh = *other.extentMax;
                    return otherLow.x >= low.x - eps && otherLow.y >= low.y - eps
                        && otherLow.z >= low.z - eps && otherHigh.x <= high.x + eps
                        && otherHigh.y <= high.y + eps && otherHigh.z <= high.z + eps;
                };
                for (std::size_t k = 0; centreLeft && k < pool.elements.size(); ++k) {
                    const auto& names = pool.elements[k].names;
                    if (static_cast<int>(k) != hitPosition
                        && std::any_of(names.begin(), names.end(), [&](const auto& name) {
                               return markedPiecesOfOne(name, hitName) && isMarkedCap(name, true);
                           })
                        && input.holdsPoint(pool.elements[k].index, *saved.center, reach)
                        && withinOldPlace(fingerprintOfIndex(pool.elements[k].index))) {
                        place.push_back(static_cast<int>(k));
                    }
                }
                offCentre = !place.empty();
            }
            // A marked piece of a far edge or far cap (PR 366 round 3) that moved with nothing at
            // its old place and no longer overlaps it: an up-to shell without names, rebuilt in
            // another order while the pieces slid onto the next face, gives the old face's index
            // to that face, and the name to its piece, with the same count and place along the
            // edge. Overlapping (round 5, from the outlines every face and edge fingerprint has
            // since version 5): two pieces of one edge whose points, seen along the edge, share a
            // length (a seam moved may leave a sliver of the old piece); two faces whose outlines,
            // seen along the old one's normal, share an area (a cap lifted with its plate keeps
            // its place). Sizes alone over-count the overlap of a tall or thin piece, and of an
            // arc, whose length runs round its chord; boxes in the world's axes (round 4) that of
            // a turned piece, and an arc's box corners seen along a slanted way that of the arc.
            // An older fingerprint, without an outline, keeps round 3's tests: edges by their
            // centres' distance along the edge against half their lengths together, planes by
            // their boxes, other faces by their centres' distance against half their sides
            // together. A piece shifted within its old place keeps its name; twins went by their
            // places above. The piece on a hole's fill, the disc and the hole moved together
            // further than its size, breaks too: its old place left bare, it can't be told from a
            // cap whose pieces slid onto the next faces of a reordered shell, its other pieces
            // sharing their faces with another profile's caps (round 3, three plates). Round 5b:
            // so do twins whose set left together, none of them where the old piece was (each
            // outline apart from the old one, seen the same way), and changed shape: a half
            // circle that a B-spline plate cut in two, the pieces slid onto the next plate of a
            // reordered shell, where the plate cuts them elsewhere. Twins of one shape as before
            // (the hit's size and offset from their centroid) moved with what cut them, a hole
            // moved with its disc: their places above decide. So do twins without outlines (an
            // older record)
            const auto outlineOf = [&](int k) -> const std::vector<Base::Vector3d>& {
                return fingerprintOfIndex(pool.elements[k].index).outline;
            };
            const bool twinOutlines = !saved.outline.empty()
                && std::none_of(twins.begin(), twins.end(), [&](int k) {
                       return outlineOf(k).empty();
                   });
            // Round 6: a far edge's pieces whose set kept its shape, seen along the sweep, may
            // still have left their plate: a slanted edge slid by one plate with its corner on a
            // seam cuts into pieces of the same shape there. A set moved with the plates that cut
            // it can't be told from that by the target alone; only the cap beside the hit (below)
            // decides then, loudly when the old piece lies beyond it
            // ops#524 (PLAN decision 182, N2): the sweep of the extrusion that made the hit, which
            // a later feature (the Tip) passes on without one of its own
            std::optional<Base::Vector3d> sweep = input.sweep;
            if (input.sweepOf && isMarkedPiece(hitName)) {
                if (auto own = input.sweepOf(hitName)) {
                    sweep = own;
                }
            }
            const bool keptShapeBeside = twinOutlines && twinsKeptShape && saved.type == 'E'
                && sweep && input.facesOf;
            const bool twinsMayDepart = twins.empty() || (twinOutlines && !twinsKeptShape)
                || keptShapeBeside;
            bool departed = false;
            if (place.empty() && twinsMayDepart && saved.center && now.center && saved.size
                && now.size && isMarkedPiece(hitName)) {
                const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
                const double apart = Base::Distance(*saved.center, *now.center);
                const bool outlines = !saved.outline.empty() && !now.outline.empty();
                std::optional<bool> outlinesSay;
                // Whether an outline lies apart from the old one: an edge's span along the way
                // (set below), a face's outline seen along the old one's normal or the sweep
                std::optional<Base::Vector3d> edgeWay;
                auto apartFromOld = [&](const std::vector<Base::Vector3d>& outline) {
                    if (saved.type != 'E') {
                        return outlinesApart(saved.outline, outline, eps, sweep).value_or(false);
                    }
                    if (!edgeWay) {
                        return false;
                    }
                    const auto [oldLow, oldHigh] = spanAlong(saved.outline, *edgeWay);
                    const auto [low, high] = spanAlong(outline, *edgeWay);
                    return std::min(oldHigh, high) - std::max(oldLow, low) <= eps;
                };
                // Round 6: whether the old straight piece lies beyond the cap beside the edge piece
                // \a index (apartBesideLine()), seen along the sweep; set when it decided the hit
                bool besideDecided = false;
                auto apartBeside = [&](const std::string& index) {
                    if (saved.type != 'E' || !sweep || !input.facesOf) {
                        return false;
                    }
                    const auto& piece = fingerprintOfIndex(index).outline;
                    for (const auto& face : input.facesOf(index)) {
                        const auto& outline = fingerprintOfIndex(face).outline;
                        if (apartBesideLine(saved.outline, outline, piece, *sweep, eps)) {
                            return true;
                        }
                    }
                    return false;
                };
                if (saved.type == 'E') {
                    // Along the edge only: the far edge moved across itself (A grown taller) still
                    // holds its old span. A line's direction; a curve's (a B-spline plate's far
                    // edge, an arc), round 5, the way across the seams: to the middle of the edge's
                    // pieces on other faces (marked otherwise), or, when that is short (the hit
                    // between them), to the nearest of them. Round 3's test, for an older
                    // fingerprint, takes the way to the nearest other piece, which is slanted
                    // when a disc slid diagonally has two quarter arcs beside its half circle.
                    // Without one, the way it moved, or the distance itself
                    std::optional<Base::Vector3d> direction;
                    std::optional<Base::Vector3d> across;
                    if (saved.kind == "Line" && saved.direction && saved.direction->Length() > eps) {
                        direction = *saved.direction;
                        across = direction;
                    }
                    else {
                        const auto hitMarks = pieceMarks(hitName);
                        double nearest = std::numeric_limits<double>::infinity();
                        double nearestElsewhere = std::numeric_limits<double>::infinity();
                        std::optional<Base::Vector3d> wayElsewhere;
                        Base::Vector3d sum;
                        int elsewhere = 0;
                        for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                            const auto& names = pool.elements[k].names;
                            const auto piece = std::find_if(
                                names.begin(),
                                names.end(),
                                [&](const auto& name) { return markedPiecesOfOne(name, hitName); }
                            );
                            if (static_cast<int>(k) == hitPosition || piece == names.end()) {
                                continue;
                            }
                            const ElementFingerprint& other = fingerprintOfIndex(
                                pool.elements[k].index
                            );
                            if (other.center) {
                                const Base::Vector3d way = *other.center - *now.center;
                                if (way.Length() > eps && way.Length() < nearest) {
                                    nearest = way.Length();
                                    direction = way;
                                }
                                if (pieceMarks(*piece) != hitMarks) {
                                    sum += *other.center;
                                    ++elsewhere;
                                    if (way.Length() > eps && way.Length() < nearestElsewhere) {
                                        nearestElsewhere = way.Length();
                                        wayElsewhere = way;
                                    }
                                }
                            }
                        }
                        if (elsewhere > 0) {
                            const Base::Vector3d middle = sum / static_cast<double>(elsewhere)
                                - *now.center;
                            across = middle.Length() >= nearestElsewhere / 2.0
                                ? std::optional<Base::Vector3d>(middle)
                                : wayElsewhere;
                        }
                        if (!across) {
                            across = direction;
                        }
                    }
                    const Base::Vector3d way = across ? *across : *now.center - *saved.center;
                    if (outlines && way.Length() > eps) {
                        // Each piece's points seen along the way: their span
                        edgeWay = Base::Vector3d(way).Normalize();
                        outlinesSay = !keptShapeBeside && apartFromOld(now.outline);
                        // Round 6: a straight piece's way is its line (a line's direction, or the
                        // way to its other pieces along it), which a slanted piece slid onto the
                        // next plate still shares with the old one; seen along the sweep, the old
                        // piece lies beyond a side of the cap beside the hit, the seam it ends at
                        if (!*outlinesSay && apartBeside(hit)) {
                            outlinesSay = true;
                            besideDecided = true;
                        }
                    }
                    else if (!outlines) {
                        double along = apart;
                        if (direction) {
                            along = std::abs(
                                (*now.center - *saved.center)
                                * Base::Vector3d(*direction).Normalize()
                            );
                        }
                        departed = along >= (*saved.size + *now.size) / 2.0 - eps;
                    }
                }
                else if (outlines) {
                    outlinesSay = outlinesApart(saved.outline, now.outline, eps, sweep);
                }
                if (outlinesSay) {
                    departed = *outlinesSay;
                }
                else if (saved.type != 'E' && saved.kind == "Plane" && now.kind == "Plane"
                         && saved.extentMin && saved.extentMax && now.extentMin && now.extentMax) {
                    // The boxes' common part, on each axis; a flat face's box is flat on one
                    const Base::Vector3d low(
                        std::max(saved.extentMin->x, now.extentMin->x),
                        std::max(saved.extentMin->y, now.extentMin->y),
                        std::max(saved.extentMin->z, now.extentMin->z)
                    );
                    const Base::Vector3d high(
                        std::min(saved.extentMax->x, now.extentMax->x),
                        std::min(saved.extentMax->y, now.extentMax->y),
                        std::min(saved.extentMax->z, now.extentMax->z)
                    );
                    const Base::Vector3d common = high - low;
                    const int shared = (common.x > eps) + (common.y > eps) + (common.z > eps);
                    const bool apartOnAxis = common.x < -eps || common.y < -eps || common.z < -eps;
                    departed = apartOnAxis || shared < 2;
                }
                else if (saved.type != 'E') {
                    departed = apart >= (std::sqrt(*saved.size) + std::sqrt(*now.size)) / 2.0 - eps;
                }
                // Twins apart the way the hit was found apart: round 6, beside their caps too
                if (departed && !twins.empty()) {
                    departed = outlinesSay.has_value()
                        && std::all_of(twins.begin(), twins.end(), [&](int k) {
                               return apartFromOld(outlineOf(k))
                                   || (besideDecided && apartBeside(pool.elements[k].index));
                           });
                }
                // ops#524: no departed piece is taken back for having slid within its up-to face
                // (PLAN decision 202): a piece of another part of a reshaped or moved profile,
                // reborn alone on the same face, can't be told from it by the face and the path
                // (review prA1c-r1's UArmSwapRedraw)
            }
            // ops#524 (PLAN decisions 199 (4) and 202): a lone piece that moved alone, still
            // overlapping its old place, left the place on its up-to face all the same when the
            // face under it now isn't the saved one, or the path from its saved foot leaves the
            // face or can't be told: the profile moved by placement or by its support, or the
            // plates under it, across a hole, gave the plate's piece beyond it the name, at a place
            // that overlaps the old one in the target's frame (the attack set's ALonePiece L, silent
            // on integration). Only when the up-to faces can be told
            std::optional<OnUpToFace> onFace;
            if (place.empty() && !departed && twins.empty() && isMarkedPiece(hitName)) {
                const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
                onFace = placeOnUpToFace(input, saved, hitName, now, eps);
            }
            const bool leftItsFace = onFace && *onFace != OnUpToFace::Kept;
            if (place.empty() && !departed && !closedTwin && !leftItsFace) {
                continue;  // moved alone
            }
            departed = departed || leftItsFace;
            if (!offCentre && !departed && !(closedTwin && place.empty())
                && entry.policy == SolvePolicy::Equivalent
                && entry.equivalent && std::all_of(place.begin(), place.end(), [&](int k) {
                       return entry.equivalent(hit, pool.elements[k].index);
                   })) {
                // Every element there gives the consumer the hit's result: the entry is exact,
                // as if unmoved, and reserves nothing.
                continue;
            }
            auto distanceOf = [&](const ElementFingerprint& fp) {
                return saved.center && fp.center ? Base::Distance(*saved.center, *fp.center) : nan;
            };
            const double moved = distanceOf(now);
            const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
            auto movedBy = [&]() {
                return std::isnan(moved) || moved <= eps
                    ? std::string("changed")
                    : "moved " + formatDistance(moved) + " mm";
            };
            std::string there;
            for (int k : place) {
                there += (there.empty() ? "" : ", ") + pool.elements[k].index;
            }
            const char* sit = place.size() > 1 ? " sit" : " sits";
            // Own twins (ops#168): the elements there are copies of the hit's own source
            // geometry, e.g. a pad's bottom edge where its top edge was after a lift by the pad's
            // length. The element moved with its feature; nothing else took its place. The hit's
            // name is the one the reference holds; copies count in the whole lineage, so a
            // later feature's edges on a boss and on its mirror copy are no twins. Nor are two
            // marked pieces of one far edge or cap (ops#386: a reordered up-to shell).
            const auto hitSources = NameAncestry::sourceSections(hitName);
            const auto hitCopies = copyContexts(hitName);
            auto ownTwin = [&](int k) {
                if (hitSources.empty()) {
                    return false;
                }
                const auto& names = pool.elements[k].names;
                return std::any_of(names.begin(), names.end(), [&](const auto& name) {
                    return NameAncestry::sourceSections(name) == hitSources
                        && copyContexts(name) == hitCopies && !isCounterSibling(name, hitName)
                        && !piecesOfOne(name, hitName) && !markedPiecesOfOne(name, hitName);
                });
            };
            if (!departed && !closedTwin && std::all_of(place.begin(), place.end(), ownTwin)) {
                outcomes[i].evidence = movedBy() + "; its own twin" + (place.size() > 1 ? "s " : " ")
                    + there + sit + " where it was";
                continue;
            }
            decidedEntry[i] = 1;
            for (int k : place) {
                reserved[entry.type].insert(pool.elements[k].index);
            }
            auto& outcome = outcomes[i];
            outcome = SolveOutcome();
            auto list = [&](int k, const char* role) {
                const auto& element = pool.elements[k];
                outcome.candidates.push_back(element.index);
                outcome.candidateNames.push_back(firstName(element));
                outcome.candidateRoles.emplace_back(role);
                outcome.candidateDistances.push_back(distanceOf(fingerprintOf(element)));
            };
            for (int k : place) {
                list(k, "place");
            }
            if (closedTwin) {
                // The hit's twins, wherever they are: one of them holds the old member
                for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                    const auto& names = pool.elements[k].names;
                    if (static_cast<int>(k) != hitPosition
                        && std::find(place.begin(), place.end(), static_cast<int>(k)) == place.end()
                        && std::any_of(names.begin(), names.end(), [&](const auto& name) {
                               return name != hitName && sameUpToOrder(name, hitName, true);
                           })) {
                        list(static_cast<int>(k), "twin");
                    }
                }
            }
            list(hitPosition, "name");
            if (closedTwin) {
                outcome.evidence = movedBy() + "; a twin on a closed edge, placed from its seam"
                    + (place.empty() ? std::string()
                                     : "; " + there + sit + " where it was");
            }
            else if (departed) {
                outcome.evidence = movedBy()
                    + (!leftItsFace ? " off where it was, and nothing sits there"
                           : *onFace == OnUpToFace::Left
                           ? " off its place on its up-to face, and nothing sits there"
                           : " off its place, and its way on its up-to face can't be told");
            }
            else if (offCentre) {
                outcome.evidence = movedBy() + " off its old centre; " + there
                    + (place.size() > 1 ? " hold it" : " holds it");
            }
            else {
                outcome.evidence = movedBy() + "; "
                    + (nearerTwin ? (place.size() > 1 ? "its twins " : "its twin ") : "") + there
                    + sit + (nearerTwin ? " nearer where it was" : " where it was");
            }
        }
        // The elements at an old place are as ambiguous as the moved one: no other entry of the
        // owner takes them.
        for (const auto& [type, indexes] : reserved) {
            pools[type].exact.insert(indexes.begin(), indexes.end());
        }
    }

    // Collapse: a group of references expanded from one name (the same scope and `from`) merges
    // back when that name is found exactly and no member holds another element.
    std::map<std::pair<std::string, std::string>, std::vector<int>> fromGroups;
    for (std::size_t i = 0; i < input.entries.size(); ++i) {
        const auto& entry = input.entries[i];
        if (!entry.from.empty()) {
            fromGroups[{entry.scope, entry.from}].push_back(static_cast<int>(i));
        }
    }
    for (const auto& [key, members] : fromGroups) {
        const std::string& type = input.entries[members.front()].type;
        if (std::any_of(members.begin(), members.end(), [&](int i) {
                return input.entries[i].type != type || decidedEntry[i];
            })) {
            continue;
        }
        Pool& pool = pools[type];
        auto found = pool.byName.find(key.second);
        if (found == pool.byName.end()) {
            continue;
        }
        const auto& element = pool.elements[found->second];
        // A missing member merged back only if it is a structural piece of the `from` element,
        // or its saved geometry lies on that element as it is now (a continuation that the
        // element covers again). A member gone elsewhere (its line redrawn with a new ID) is
        // solved on its own.
        const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
        const ElementFingerprint& now = fingerprintOfIndex(element.index);
        auto extent = OldExtent::of(now, eps, input.tolerances);
        auto mergedBack = [&](const SolveInput::Entry& entry) {
            if (NameAncestry::isPieceOf(entry.oldName, key.second)
                || NameAncestry::isIndexPieceOf(entry.oldName, key.second)) {
                return true;
            }
            auto range = extent ? extent->interval(entry.fingerprint) : std::nullopt;
            return range && extent->within(*range);
        };
        bool merged = std::all_of(members.begin(), members.end(), [&](int i) {
            const auto& entry = input.entries[i];
            return entry.exact ? entry.exactElement == element.index : mergedBack(entry);
        });
        if (!merged) {
            continue;
        }
        int keep = *std::min_element(members.begin(), members.end(), [&](int a, int b) {
            return input.entries[a].position < input.entries[b].position;
        });
        for (int i : members) {
            auto& outcome = outcomes[i];
            outcome = SolveOutcome();
            outcome.element = element.index;
            outcome.name = firstName(element);
            if (i == keep) {
                outcome.status = SolveStatus::Resolved;
                outcome.tier = 0;
                outcome.collapsed = true;
                outcome.evidence = "pieces merged back: " + key.second + " found exactly";
            }
            else {
                outcome.status = SolveStatus::Removed;
                outcome.evidence = "pieces merged back";
            }
            decidedEntry[i] = 1;
        }
        pool.exact.insert(element.index);
    }

    // G3 on the exact entries' splits (ops#127, N2 5.2): of an exact entry's pieces (\a listed,
    // positions in \a pool, the hit among them), the one whose extent holds the saved centre,
    // if exactly one does and the rules may guess; -1 otherwise (N5, N10).
    auto pieceHoldingCentre = [&](const SolveInput::Entry& entry,
                                  const Pool& pool,
                                  const std::vector<int>& listed) {
        if (!input.guess || input.targetFailed || !entry.fingerprint.isValid()) {
            return -1;
        }
        int found = -1;
        for (int k : listed) {
            if (holdsCentre(entry.fingerprint,
                            fingerprintOf(pool.elements[k]),
                            input.diagonal,
                            input.continuationDistance)) {
                if (found >= 0) {
                    return -1;
                }
                found = k;
            }
        }
        return found;
    };
    // The outcome of that guess: the piece, tier 1 (structure found the pieces), the others as
    // alternatives (the hit's role `name`, the rest `piece`) nearest centre first.
    auto guessedPiece = [&](const SolveInput::Entry& entry,
                            const Pool& pool,
                            const std::vector<int>& listed,
                            int pick,
                            int hitPosition) {
        SolveOutcome outcome;
        outcome.status = SolveStatus::Guessed;
        outcome.tier = 1;
        outcome.guessKind = "piece";
        outcome.element = pool.elements[pick].index;
        outcome.name = firstName(pool.elements[pick]);
        outcome.evidence = "guess: the piece at the saved centre, of "
            + std::to_string(listed.size()) + " pieces";
        auto distanceOf = [&](int k) {
            const ElementFingerprint& now = fingerprintOf(pool.elements[k]);
            return entry.fingerprint.center && now.center
                ? Base::Distance(*entry.fingerprint.center, *now.center)
                : nan;
        };
        std::vector<int> order {pick};
        std::vector<int> others;
        for (int k : listed) {
            if (k != pick) {
                others.push_back(k);
            }
        }
        std::stable_sort(others.begin(), others.end(), [&](int a, int b) {
            const double da = distanceOf(a);
            const double db = distanceOf(b);
            return std::isnan(db) ? !std::isnan(da) : da < db;
        });
        order.insert(order.end(), others.begin(), others.end());
        for (int k : order) {
            outcome.candidates.push_back(pool.elements[k].index);
            outcome.candidateNames.push_back(firstName(pool.elements[k]));
            outcome.candidateRoles.emplace_back(k == pick ? "guess"
                                                : k == hitPosition ? "name"
                                                                   : "piece");
            outcome.candidateDistances.push_back(distanceOf(k));
        }
        return outcome;
    };

    // Continuation: an exact line edge that is now a strict part of the edge its fingerprint
    // was saved for, and the other line edges on the old edge that bound a face it bounds.
    {
        const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
        Pool& pool = pools["Edge"];
        const std::set<std::string> held = pool.exact;  // before any continuation is taken
        std::map<std::string, std::set<std::string>> facesByEdge;
        auto facesOf = [&](const std::string& index) -> const std::set<std::string>& {
            auto it = facesByEdge.find(index);
            if (it == facesByEdge.end()) {
                std::set<std::string> faces;
                if (input.facesOf) {
                    for (auto& face : input.facesOf(index)) {
                        faces.insert(std::move(face));
                    }
                }
                it = facesByEdge.emplace(index, std::move(faces)).first;
            }
            return it->second;
        };
        std::vector<int> taken;
        for (std::size_t i = 0; i < input.entries.size(); ++i) {
            const auto& entry = input.entries[i];
            if (!entry.exact || decidedEntry[i] || entry.type != "Edge"
                || !entry.fingerprint.isValid()) {
                continue;
            }
            const std::string& hit = entry.exactElement;
            const int hitPosition = positionOf(pool, hit);
            const ElementFingerprint& now = fingerprintOfIndex(hit);
            if (hitPosition < 0
                || !hitWithinOldEdge(entry.fingerprint,
                                  now,
                                  input.diagonal,
                                  input.tolerances,
                                  input.continuationDistance)) {
                continue;
            }
            auto extent = OldExtent::of(entry.fingerprint, eps, input.tolerances, &now);
            auto hitRange = extent->interval(now);
            const auto& hitFaces = facesOf(hit);
            // A piece is the old element's maker's own edge (ops#284): another feature's edge on
            // the old edge's line, such as a fillet's end on the face the edge bounds, is no piece
            // of it, though that face puts the maker in its lineage. Such an edge within the old
            // extent is traced, and named in a taken continuation's evidence: a piece another
            // feature failed to report as modified would show there.
            const std::string maker = input.sameMaker ? NameAncestry::makerTag(entry.exactName)
                                                      : std::string();
            auto otherMaker = [&](const SolveInput::Element& element) {
                return !maker.empty()
                    && std::none_of(
                        element.names.begin(),
                        element.names.end(),
                        [&](const std::string& name) {
                            return NameAncestry::makerTag(name) == maker;
                        }
                    );
            };
            std::vector<std::pair<int, std::pair<double, double>>> continued;  // position, range
            std::vector<int> pastEnd;
            std::vector<int> skipped;  // another maker's, within the old extent, on a shared face
            std::string sharedFace;
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& index = pool.elements[k].index;
                if (index == hit || held.count(index)) {
                    continue;
                }
                auto range = extent->interval(fingerprintOf(pool.elements[k]));
                if (!range) {
                    continue;
                }
                bool within = extent->within(*range);
                if (!within && extent->overlap(*range) <= eps) {
                    continue;  // beyond the old ends, at most touching one
                }
                const auto& faces = facesOf(index);
                auto shared = std::find_if(faces.begin(), faces.end(), [&](const auto& face) {
                    return hitFaces.count(face) > 0;
                });
                if (shared == faces.end()) {
                    continue;
                }
                if (otherMaker(pool.elements[k])) {
                    if (within) {
                        skipped.push_back(static_cast<int>(k));
                        FC_LOG(
                            "continuation of " << hit << " (" << entry.exactName << "): " << index
                                               << " lies within the old edge but "
                                               << "has another maker, not taken"
                        );
                    }
                    continue;
                }
                if (within) {
                    continued.emplace_back(static_cast<int>(k), *range);
                    if (sharedFace.empty()) {
                        sharedFace = *shared;
                    }
                }
                else {
                    pastEnd.push_back(static_cast<int>(k));
                }
            }
            if (continued.empty() && pastEnd.empty()) {
                continue;  // only shortened
            }
            // Pieces of one edge are disjoint; overlapping ones are something else.
            std::vector<std::pair<double, double>> ranges {*hitRange};
            for (const auto& [k, range] : continued) {
                ranges.push_back(range);
            }
            const bool overlapping = extent->overlapping(ranges);

            std::vector<int> positions {hitPosition};
            std::string continuations;
            for (const auto& [k, range] : continued) {
                positions.push_back(k);
                continuations += (continuations.empty() ? "" : ", ") + pool.elements[k].index;
            }
            auto& outcome = outcomes[i];
            auto breakWith = [&](std::vector<int> listed, std::string evidence) {
                std::sort(listed.begin(), listed.end());
                outcome = SolveOutcome();
                outcome.evidence = std::move(evidence);
                for (int k : listed) {
                    outcome.candidates.push_back(pool.elements[k].index);
                    outcome.candidateNames.push_back(firstName(pool.elements[k]));
                    outcome.candidateRoles.emplace_back(k == hitPosition ? "name" : "piece");
                    outcome.candidateDistances.push_back(nan);
                }
            };
            if (!pastEnd.empty() || overlapping) {
                std::vector<int> listed = positions;
                listed.insert(listed.end(), pastEnd.begin(), pastEnd.end());
                std::string evidence = "pieces overlap";
                if (!pastEnd.empty()) {
                    evidence = "continued past the old edge by "
                        + pool.elements[pastEnd.front()].index;
                    for (std::size_t p = 1; p < pastEnd.size(); ++p) {
                        evidence += ", " + pool.elements[pastEnd[p]].index;
                    }
                }
                breakWith(listed, evidence);
            }
            else if (entry.policy == SolvePolicy::Expand) {
                std::sort(positions.begin(), positions.end());
                outcome.status = SolveStatus::Resolved;
                outcome.tier = 4;
                for (int k : positions) {
                    outcome.elements.push_back(pool.elements[k].index);
                    outcome.names.push_back(firstName(pool.elements[k]));
                }
                outcome.element = outcome.elements.front();
                outcome.name = outcome.names.front();
                outcome.from = entry.from.empty() ? entry.exactName : entry.from;
                outcome.evidence = "continued by " + continuations
                    + (extent->circle ? " (arc" : " (line") + (continued.size() > 1 ? "s" : "")
                    + " within the old edge, shares "
                    + sharedFace + ")";
                for (int k : skipped) {
                    outcome.evidence += ", skipped " + pool.elements[k].index + " (another maker)";
                }
                for (const auto& [k, range] : continued) {
                    taken.push_back(k);
                }
            }
            else if (entry.policy == SolvePolicy::Equivalent && entry.equivalent
                     && std::all_of(continued.begin(), continued.end(), [&](const auto& c) {
                            return entry.equivalent(hit, pool.elements[c.first].index);
                        })) {
                // Every piece gives the consumer the same result: the hit stands.
            }
            else {
                // G3 under One: the piece at the saved centre (never under Equivalent, N6)
                const int pick = entry.policy == SolvePolicy::One
                    ? pieceHoldingCentre(entry, pool, positions)
                    : -1;
                if (pick >= 0) {
                    outcome = guessedPiece(entry, pool, positions, pick, hitPosition);
                    if (pick != hitPosition) {
                        taken.push_back(pick);
                    }
                }
                else {
                    breakWith(positions, "split: the old edge continues in " + continuations);
                }
            }
            decidedEntry[i] = 1;
        }
        for (int k : taken) {
            pool.exact.insert(pool.elements[k].index);
        }
    }

    // A planar face split by a coplanar one (Q3 (b)): a face's fingerprint doesn't bound its
    // region, so the rest of the old face can't be told from a coplanar neighbour. Detected and
    // broken, never taken.
    {
        Pool& pool = pools["Face"];
        auto inPlane = [&](const ElementFingerprint& saved, const ElementFingerprint& face) {
            return planeAgrees(saved,
                               face,
                               input.diagonal,
                               input.tolerances,
                               input.continuationDistance);
        };
        std::map<std::string, std::set<std::string>> neighbours;
        auto neighboursOf = [&](const std::string& index) -> const std::set<std::string>& {
            auto it = neighbours.find(index);
            if (it == neighbours.end()) {
                std::set<std::string> faces;
                if (input.neighboursOf) {
                    for (auto& face : input.neighboursOf(index)) {
                        faces.insert(std::move(face));
                    }
                }
                faces.erase(index);
                it = neighbours.emplace(index, std::move(faces)).first;
            }
            return it->second;
        };
        for (std::size_t i = 0; i < input.entries.size(); ++i) {
            const auto& entry = input.entries[i];
            const ElementFingerprint& saved = entry.fingerprint;
            if (!entry.exact || decidedEntry[i] || entry.type != "Face" || !isPlane(saved)) {
                continue;
            }
            const std::string& hit = entry.exactElement;
            const int hitPosition = positionOf(pool, hit);
            if (hitPosition < 0
                || !faceWithinOldPlane(saved,
                                       fingerprintOfIndex(hit),
                                       input.diagonal,
                                       input.tolerances,
                                       input.continuationDistance)) {
                continue;
            }
            const auto& hitNeighbours = neighboursOf(hit);
            std::vector<int> listed {hitPosition};
            std::string beside;
            std::string pastEnd;  // faces that run past the old face's extent
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& index = pool.elements[k].index;
                if (index == hit || pool.exact.count(index)
                    || !inPlane(saved, fingerprintOf(pool.elements[k]))) {
                    continue;
                }
                // Outside the old face's extent, a face holds no point of it (PR 8).
                ExtentRelation relation = faceExtentRelation(saved,
                                                             fingerprintOf(pool.elements[k]),
                                                             input.diagonal,
                                                             input.continuationDistance);
                if (relation == ExtentRelation::Outside) {
                    continue;
                }
                const auto& faces = neighboursOf(index);
                bool related = hitNeighbours.count(index) > 0
                    || std::any_of(faces.begin(), faces.end(), [&](const auto& face) {
                           return hitNeighbours.count(face) > 0;
                       });
                if (related) {
                    listed.push_back(static_cast<int>(k));
                    beside += (beside.empty() ? "" : ", ") + index;
                    if (relation == ExtentRelation::Overlapping) {
                        pastEnd += (pastEnd.empty() ? "" : ", ") + index;
                    }
                }
            }
            if (listed.size() == 1) {
                continue;  // only shrunk
            }
            // Equivalent (the coordinator's decision on the review): the hit stands if every
            // coplanar face beside it gives the consumer the same result, as for edges.
            // A face that runs past the old one breaks the entry under every policy, as an edge
            // that runs past the old end does.
            if (pastEnd.empty() && entry.policy == SolvePolicy::Equivalent && entry.equivalent
                && std::all_of(listed.begin(), listed.end(), [&](int k) {
                       return k == hitPosition
                           || entry.equivalent(hit, pool.elements[k].index);
                   })) {
                decidedEntry[i] = 1;
                continue;
            }
            std::sort(listed.begin(), listed.end());
            auto& outcome = outcomes[i];
            // G3 (One, Expand): the piece at the saved centre, unless a face runs past the old
            // one (N6) or the pieces give an Equivalent consumer different results (N6)
            const int pick = pastEnd.empty() && entry.policy != SolvePolicy::Equivalent
                ? pieceHoldingCentre(entry, pool, listed)
                : -1;
            if (pick >= 0) {
                outcome = guessedPiece(entry, pool, listed, pick, hitPosition);
                pool.exact.insert(pool.elements[pick].index);
                decidedEntry[i] = 1;
                continue;
            }
            outcome = SolveOutcome();
            outcome.evidence = pastEnd.empty()
                ? "split: a coplanar face beside it, " + beside
                : "split: a coplanar face beside it runs past the old face, " + pastEnd;
            for (int k : listed) {
                outcome.candidates.push_back(pool.elements[k].index);
                outcome.candidateNames.push_back(firstName(pool.elements[k]));
                outcome.candidateRoles.emplace_back(k == hitPosition ? "name" : "piece");
                outcome.candidateDistances.push_back(nan);
            }
            decidedEntry[i] = 1;
        }
    }

    // A twin on a closed edge whose name is gone (decision 206) breaks: no element holds its old
    // place by its name, and the twins' places count from the seam, so neither the structure nor
    // the geometry tells which one it was. The elements at its old place are its candidates.
    for (std::size_t i = 0; i < input.entries.size(); ++i) {
        const auto& entry = input.entries[i];
        if (entry.exact || decidedEntry[i] || !isClosedTwin(entry.oldName)) {
            continue;
        }
        decidedEntry[i] = 1;
        auto& outcome = outcomes[i];
        outcome = SolveOutcome();
        outcome.evidence = "a twin on a closed edge, placed from its seam; its name is gone";
        const ElementFingerprint& saved = entry.fingerprint;
        const Pool& pool = pools[entry.type];
        // After those at its old place, its twins (the same name up to their places)
        std::vector<const SolveInput::Element*> twins;
        for (const auto& element : pool.elements) {
            if (std::any_of(element.names.begin(), element.names.end(), [&](const auto& name) {
                    return sameUpToOrder(name, entry.oldName, true);
                })) {
                twins.push_back(&element);
            }
        }
        auto listTwins = [&]() {
            for (const auto* element : twins) {
                if (std::find(outcome.candidates.begin(), outcome.candidates.end(), element->index)
                    == outcome.candidates.end()) {
                    outcome.candidates.push_back(element->index);
                    outcome.candidateNames.push_back(firstName(*element));
                    outcome.candidateRoles.emplace_back("twin");
                    outcome.candidateDistances.push_back(nan);
                }
            }
        };
        if (!saved.isValid()) {
            listTwins();
            continue;
        }
        for (const auto& element : pool.elements) {
            ElementFingerprint intrinsic;
            std::optional<Base::Vector3d> anchor;
            if (input.hintOf && input.hintOf(element.index, intrinsic, anchor)
                && !mayBeAtPlace(saved,
                                 intrinsic,
                                 anchor,
                                 input.diagonal,
                                 input.tolerances,
                                 input.continuationDistance)) {
                continue;
            }
            const ElementFingerprint& now = fingerprintOfIndex(element.index);
            if (now.isValid()
                && atSamePlace(saved,
                               now,
                               input.diagonal,
                               input.tolerances,
                               input.continuationDistance)) {
                outcome.candidates.push_back(element.index);
                outcome.candidateNames.push_back(firstName(element));
                outcome.candidateRoles.emplace_back("place");
                outcome.candidateDistances.push_back(
                    saved.center && now.center ? Base::Distance(*saved.center, *now.center) : nan
                );
            }
        }
        listTwins();
    }

    // Missing entries, grouped: one solve per (old name, type, policy).
    std::map<std::tuple<std::string, std::string, int>, std::vector<int>> groups;
    for (std::size_t i = 0; i < input.entries.size(); ++i) {
        const auto& entry = input.entries[i];
        if (!entry.exact && !decidedEntry[i]) {
            groups[{entry.oldName, entry.type, static_cast<int>(entry.policy)}].push_back(
                static_cast<int>(i)
            );
        }
    }

    struct GroupState
    {
        const std::vector<int>* members = nullptr;
        Pool* pool = nullptr;
        std::string oldName;
        // The pool's element type ('V', 'E', 'F'), for the ancestry walk (ops#359)
        char type = 0;
        std::vector<int> candidates;  // positions in the pool, in index order
        std::set<int> fromOverlap;
        std::set<int> fromNames;
        std::set<std::string> matchedNames;  // the names the name match found them by
        std::set<int> inAncestry;
        // The far edge's piece left after others of its pieces went (isFewerPiecesOf(), PR 366
        // round 3), or -1: the old piece renumbered, no pattern's copy
        int fewerPieces = -1;
        // Under Tier1Derived::Place: the elements that reach the old name only through a node of
        // another type or a GEN section (ops#335, ops#358), and the survivors of tier 1 that were
        // all such elements, which the no-candidate branch then got instead (listed first on a
        // break, role `derived`).
        std::set<int> derivedOnly;
        std::vector<int> derived;
        // Tier 1's candidates that T1 dropped, made by another maker (ops#167), and that T1'
        // dropped, which lost one of the old element's sources (ops#173): for the evidence, and
        // listed last on a break (ops#174).
        std::vector<int> otherMaker;
        std::vector<int> otherSource;
        // Tier 1's candidates that the merged-neighbour test dropped (ops#446); the target's
        // faces that hold two of the old element's faces or more, in index order, with how many
        // each holds; and how many of the old element's faces no face holds.
        std::vector<int> otherFaces;
        std::vector<std::pair<std::string, std::size_t>> mergedFaces;
        std::size_t lostFaces = 0;
        // Tier 1's candidates that the missing-generator test dropped (ops#454); the generator's
        // type ("edge", "vertex") and, as above, its faces' holders that hold two or more of
        // them and how many no face holds.
        std::vector<int> otherGenerator;
        const char* generatorType = "";
        std::vector<std::pair<std::string, std::size_t>> generatorMergedFaces;
        std::size_t generatorLostFaces = 0;
        // Tier 1's candidates that the held-generator test dropped (ops#467), and the
        // generators they aren't made from, each as its type ("edge") and an element holding it.
        std::vector<int> notGenerated;
        std::vector<std::pair<std::string, std::string>> heldGenerators;
        // The old name's face generator that no face holds, when it dropped tier 1's survivors
        // (the face-generator net, ops#503 D1); they are in otherGenerator then.
        std::string faceGenerator;
        // The twin clause (ops#503 D1): tier 1's one survivor, the old element's twin, which
        // geometry judged instead (-1: none); and the twin-pick rule's pure renumbering, the pick
        // (-1: none) and its evidence clause.
        int twinSurvivor = -1;
        int renumbered = -1;
        std::string renumberedClause;
        // The IDX source's elements, and whether they replaced the other candidates (tier 2
        // agreed with one of them at least).
        std::set<int> fromIndex;
        bool indexed = false;
        SolveOutcome outcome;
        bool decided = false;
        int graphEntry = -1;
        // Tiers 2-3: the survivors of tier 1 before geometry narrowed them (what a broken entry
        // lists), the tier that narrowed them (0: none), whether geometry alone found the
        // candidate, and what it found.
        std::vector<int> listed;
        int geometryTier = 0;
        bool geometric = false;
        std::string geometryEvidence;
        // Equivalent: the pieces that resolve as one, their representative being the only
        // entry of `candidates`.
        std::vector<int> equivalent;
        // Expand: the pieces that resolve together, the first being the only entry of
        // `candidates`.
        std::vector<int> expanded;
        // The members' saved fingerprint, if they all hold the same valid one.
        const ElementFingerprint* saved = nullptr;
        // A guess rule's pick (ops#127, N2 section 5): the rule (`nearest`, `geometric`,
        // `piece`), the other elements it chose among with their role, and the evidence is
        // geometryEvidence.
        std::string guessKind;
        std::vector<int> guessAlternatives;
        const char* guessRole = "structural";
    };

    // The members' saved fingerprint, if they all hold the same valid one.
    auto savedFingerprint = [&](const std::vector<int>& members) -> const ElementFingerprint* {
        const ElementFingerprint& first = input.entries[members.front()].fingerprint;
        if (!first.isValid()) {
            return nullptr;
        }
        for (int member : members) {
            if (input.entries[member].fingerprint != first) {
                return nullptr;
            }
        }
        return &first;
    };
    std::vector<GroupState> states;
    states.reserve(groups.size());

    // \a role: the candidates' role, or empty for a structural survivor's or a piece's, as the
    // group shows it.
    auto listCandidates = [nan](GroupState& state,
                                const std::vector<int>& positions,
                                const char* role = nullptr) {
        auto isPiece = [&](int k) {
            const auto& names = state.pool->elements[k].names;
            return std::any_of(names.begin(), names.end(), [&](const auto& n) {
                return NameAncestry::isPieceOf(n, state.oldName)
                    || NameAncestry::isIndexPieceOf(n, state.oldName);
            });
        };
        for (int k : positions) {
            const auto& element = state.pool->elements[k];
            state.outcome.candidates.push_back(element.index);
            state.outcome.candidateNames.push_back(
                element.names.empty() ? std::string() : element.names.front()
            );
            state.outcome.candidateRoles.emplace_back(role                       ? role
                                                      : isPiece(k)               ? "piece"
                                                      : state.derivedOnly.count(k) ? "derived"
                                                                                 : "structural");
            state.outcome.candidateDistances.push_back(nan);
        }
    };
    // The candidates at \a positions nearest the saved centre first, with their distances, at
    // most eight (ops#127, N3 5.3: a no-structure break). Those without a distance last.
    auto listByDistance = [&fingerprintOf](GroupState& state,
                                           const std::vector<int>& positions,
                                           const char* role,
                                           std::size_t most = 8) {
            auto distanceOf = [&](int k) {
                const ElementFingerprint& now = fingerprintOf(state.pool->elements[k]);
                return state.saved && state.saved->center && now.center
                    ? Base::Distance(*state.saved->center, *now.center)
                    : std::numeric_limits<double>::quiet_NaN();
            };
            std::vector<std::pair<double, int>> ranked;
            for (int k : positions) {
                ranked.emplace_back(distanceOf(k), k);
            }
            std::stable_sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b) {
                return std::isnan(b.first) ? !std::isnan(a.first) : a.first < b.first;
            });
            if (ranked.size() > most) {
                ranked.resize(most);
            }
            for (const auto& [distance, k] : ranked) {
                const auto& element = state.pool->elements[k];
                state.outcome.candidates.push_back(element.index);
                state.outcome.candidateNames.push_back(
                    element.names.empty() ? std::string() : element.names.front()
                );
                state.outcome.candidateRoles.emplace_back(role);
                state.outcome.candidateDistances.push_back(distance);
            }
        };
    // What G2's pick \a element lacks, or nullptr: one of its names must share an innermost
    // source with \a oldName (policy D) and, under sameMaker, have its maker in its lineage
    // (G2', ops#167), since two holes' edges on the face both cut share that face's sketch as a
    // source, but not their maker.
    auto otherOrigin = [&input](const SolveInput::Element& element,
                                const std::string& oldName) -> const char* {
        return otherOriginOf(element.names, oldName, input.sameMaker);
    };
    // Which faces hold several of the old element's faces, and how many it lost (ops#446). Not
    // whether the edit merged them: a refined pipe's faces were merged when it was saved already
    // (fork PR 361's review).
    auto facesText = [](const std::vector<std::pair<std::string, std::size_t>>& merged,
                        std::size_t lost) {
        std::string why;
        for (const auto& [face, count] : merged) {
            why += (why.empty() ? "" : ", ") + face + " holds " + std::to_string(count)
                + " of them";
        }
        if (lost) {
            why += (why.empty() ? "" : ", ")
                + (lost == 1 ? std::string("1 of them is") : std::to_string(lost) + " of them are")
                + " on no face";
        }
        return why;
    };
    // Why structure didn't decide, when T1 dropped tier 1's candidates (ops#167).
    auto otherMakerText = [&facesText](const GroupState& state) {
        std::string text;
        if (const auto n = state.otherMaker.size()) {
            text = n == 1 ? std::string("; tier 1's 1 survivor has another maker")
                          : "; tier 1's " + std::to_string(n) + " survivors have another maker";
        }
        if (const auto n = state.otherSource.size()) {
            text += n == 1
                ? std::string("; tier 1's 1 survivor lost the old element's source")
                : "; tier 1's " + std::to_string(n) + " survivors lost the old element's source";
        }
        if (const auto n = state.otherFaces.size()) {
            text += (n == 1 ? std::string("; tier 1's 1 survivor lies off the old element's faces")
                            : "; tier 1's " + std::to_string(n)
                         + " survivors lie off the old element's faces")
                + " (" + facesText(state.mergedFaces, state.lostFaces) + ")";
        }
        if (const auto n = state.otherGenerator.size(); n && !state.faceGenerator.empty()) {
            text += (n == 1 ? std::string("; tier 1's 1 survivor lacks")
                            : "; tier 1's " + std::to_string(n) + " survivors lack")
                + " the old element's face generator (a face, which no face holds)";
        }
        else if (n) {
            const std::string type = state.generatorType;
            text += (n == 1 ? std::string("; tier 1's 1 survivor lacks")
                            : "; tier 1's " + std::to_string(n) + " survivors lack")
                + " the old element's generator (" + (type == "edge" ? "an " : "a ") + type
                + " named after its faces, which no "
                + type + " holds; "
                + facesText(state.generatorMergedFaces, state.generatorLostFaces) + ")";
        }
        if (const auto n = state.notGenerated.size()) {
            std::string held;
            for (const auto& [type, holder] : state.heldGenerators) {
                held += (held.empty() ? "" : "; ") + std::string(type == "edge" ? "an " : "a ")
                    + type + ", which " + holder + " holds";
            }
            text += (n == 1 ? std::string("; tier 1's 1 survivor isn't")
                            : "; tier 1's " + std::to_string(n) + " survivors aren't")
                + " made from the old element's generator"
                + (state.heldGenerators.size() == 1 ? "" : "s") + " (" + held + ")";
        }
        return text;
    };
    // The derived survivors the no-candidate branch ran instead of (ops#335), for the evidence:
    // how they hold the old name and, given \a agree (the pool's elements tier 2 kept), why none
    // was taken.
    auto derivedText = [](const GroupState& state, const std::vector<int>* agree) {
        if (state.derived.empty()) {
            return std::string();
        }
        const auto n = state.derived.size();
        std::string path;
        for (const auto& name : state.pool->elements[state.derived.front()].names) {
            path = derivedPathOf(name, state.oldName, state.type);
            if (!path.empty()) {
                break;
            }
        }
        std::string text = (n == 1 ? std::string("; tier 1's 1 survivor is in ancestry ")
                                   : "; tier 1's " + std::to_string(n)
                                    + " survivors are in ancestry ")
            + derivedVia(path);
        if (!path.empty()) {
            text += " (" + path + ")";
        }
        if (agree) {
            const bool kept = std::any_of(state.derived.begin(), state.derived.end(), [&](int k) {
                return std::find(agree->begin(), agree->end(), k) != agree->end();
            });
            text += kept ? (n == 1 ? ", not at the old place" : ", none at the old place")
                         : (n == 1 ? ", tier 2 disagrees with it" : ", tier 2 disagrees with them");
        }
        return text;
    };
    // A break's candidates: the derived survivors first (ops#335), then the rest of \a agree,
    // each nearest the saved centre first, eight at most.
    auto listDerivedFirst = [&listByDistance](GroupState& state, const std::vector<int>& agree) {
        listByDistance(state, state.derived, "derived");
        std::vector<int> rest;
        for (int k : agree) {
            if (std::find(state.derived.begin(), state.derived.end(), k) == state.derived.end()) {
                rest.push_back(k);
            }
        }
        const auto n = state.outcome.candidates.size();
        listByDistance(state, rest, "geometric", n < 8 ? 8 - n : std::size_t(0));
    };
    // The survivors T1, T1', the merged-neighbour and the missing- and held-generator tests
    // dropped, last on a break (ops#174, ops#446, ops#454, ops#467), in the room left of eight
    // candidates: never taken automatically, offered to the user's pick. Those the break listed
    // already aren't listed again (a tier-3 pick T1' dropped). The same feature's elements first:
    // they are the likelier pick (PR 149's review).
    auto listDropped = [&listByDistance](GroupState& state) {
        auto unlisted = [&](const std::vector<int>& dropped) {
            const auto& listed = state.outcome.candidates;
            std::vector<int> rest;
            for (int k : dropped) {
                const auto& index = state.pool->elements[k].index;
                if (std::find(listed.begin(), listed.end(), index) == listed.end()) {
                    rest.push_back(k);
                }
            }
            return rest;
        };
        auto room = [&]() {
            const auto n = state.outcome.candidates.size();
            return n < 8 ? 8 - n : std::size_t(0);
        };
        // The twin clause's survivor (ops#503 D1), where geometry didn't list it: tier 1's
        // structure did name it
        if (state.twinSurvivor >= 0) {
            listByDistance(state, unlisted({state.twinSurvivor}), "structural", room());
        }
        listByDistance(state, unlisted(state.otherGenerator), "other generator", room());
        listByDistance(state, unlisted(state.notGenerated), "other generator", room());
        listByDistance(state, unlisted(state.otherFaces), "other faces", room());
        listByDistance(state, unlisted(state.otherSource), "other source", room());
        listByDistance(state, unlisted(state.otherMaker), "other maker", room());
    };

    // The linked names of \a section if it carries the UPP flag (an element named after the faces
    // it lies on), sorted and distinct; otherwise none.
    auto upperLinked = [](const DecodedMappedSection& section) {
        std::vector<std::string> linked;
        if (section.hasMapperFlag(MAPPER_FLAG_UPPER)) {
            linked = section.linkedNames;
            std::sort(linked.begin(), linked.end());
            linked.erase(std::unique(linked.begin(), linked.end()), linked.end());
        }
        return linked;
    };
    // The target's faces that hold a name of \a linked, or a same-type descendant of it (a piece,
    // a fusion's modification), with the number of linked names each holds; those holding two or
    // more (merged), in index order; and the number of linked names no face holds (lost). For the
    // merged-neighbour and missing-generator tests (ops#446, ops#454).
    struct FaceHolders
    {
        std::map<std::string, std::size_t> holders;
        std::vector<std::pair<std::string, std::size_t>> merged;
        std::size_t lost = 0;
    };
    auto faceHolders = [&input, &ancestry](const std::vector<std::string>& linked) {
        FaceHolders result;
        std::map<std::string, std::set<std::size_t>> held;
        std::vector<bool> found(linked.size(), false);
        for (const auto& face : input.faces) {
            for (std::size_t i = 0; i < linked.size(); ++i) {
                if (std::any_of(face.names.begin(), face.names.end(), [&](const auto& n) {
                        return n == linked[i]
                            || (ancestry.contains(n, linked[i])
                                && NameAncestry::reaches(n, linked[i], 'F')
                                    == NameAncestry::Reach::SameType);
                    })) {
                    held[face.index].insert(i);
                    found[i] = true;
                }
            }
        }
        for (const auto& [index, which] : held) {
            result.holders.emplace(index, which.size());
            if (which.size() >= 2) {
                result.merged.emplace_back(index, which.size());
            }
        }
        std::sort(result.merged.begin(), result.merged.end(), [](const auto& a, const auto& b) {
            const long na = indexNumber(a.first);
            const long nb = indexNumber(b.first);
            return na != nb ? na < nb : a.first < b.first;
        });
        result.lost = static_cast<std::size_t>(std::count(found.begin(), found.end(), false));
        return result;
    };

    MatchGraph graph;
    std::map<int, int> nodeOfId;              // element ID -> graph candidate
    std::map<int, int> representativeOfNode;  // equivalent candidates -> representative's ID
    // Per pool and maker: whether each element has the maker in its lineage (-1: not known yet).
    // Many entries share a maker, and the lineage walk isn't cached (PR 149's review).
    std::map<std::pair<const Pool*, std::string>, std::vector<signed char>> lineageMakers;
    std::vector<signed char> noMaker;

    for (auto& [key, members] : groups) {
        GroupState& state = states.emplace_back();
        state.members = &members;
        state.oldName = std::get<0>(key);
        state.pool = &pools[std::get<1>(key)];
        // The walk takes the element's type from the pool: a name whose top section has none
        // would otherwise get the first typed node's, and a path through another type could
        // count as same-type (ops#359).
        const std::string& poolType = std::get<1>(key);
        state.type = poolType == "Vertex" ? 'V'
            : poolType == "Edge"          ? 'E'
            : poolType == "Face"          ? 'F'
                                          : 0;
        Pool& pool = *state.pool;
        const std::string& oldName = state.oldName;

        // The pool for this entry: tier-0 elements only as proven merges, and never an element
        // the user rejected for one of the members (ops#127).
        std::set<std::string> rejected;
        for (int member : members) {
            const auto& excluded = input.entries[member].excluded;
            rejected.insert(excluded.begin(), excluded.end());
        }
        // T1 (ops#167): a candidate must come from the old element's maker. The overlap counts
        // shared ancestry of any kind, so another hole's edge on the face both holes cut shares
        // that face with the old edge as fully as a piece of the old edge would. A candidate in
        // the old name's ancestry, or with the maker in its lineage (pieces, a redraw in the
        // maker's own sketch, a later feature's modification), stays. Another maker's elements
        // are left out before tier 1's band and top agreement narrow the survivors, so that none
        // of them evicts a same-maker survivor (ops#174); their own survivors are the evidence.
        const std::string maker = input.sameMaker ? NameAncestry::makerTag(oldName) : std::string();
        auto& madeBy = maker.empty() ? noMaker : lineageMakers[{&pool, maker}];
        madeBy.resize(pool.elements.size(), -1);
        auto fromMaker = [&](int k) {
            if (maker.empty() || state.inAncestry.count(k)) {
                return true;
            }
            if (madeBy[k] < 0) {
                const auto& names = pool.elements[k].names;
                madeBy[k] = std::any_of(names.begin(), names.end(), [&](const auto& n) {
                    return NameAncestry::hasLineageTag(n, maker);
                });
            }
            return madeBy[k] > 0;
        };
        std::vector<std::string> flatNames;
        std::vector<int> flatElements;
        std::vector<std::string> otherNames;
        std::vector<int> otherElements;
        std::vector<char> allowed(pool.elements.size(), 0);
        for (std::size_t k = 0; k < pool.elements.size(); ++k) {
            const auto& element = pool.elements[k];
            if (rejected.count(element.index)) {
                continue;
            }
            // A projection partner of the old element holds its name, but is another element
            // (AncestryNodes::projected): it is no evidence, and not in the old name's ancestry.
            // Under Tier1Derived::Place, nor is an element that reaches it only through a node
            // of another type or a GEN section (ops#335, ops#358: an offset copy): it is related
            // to the old element, and geometry decides.
            bool contains = false;
            bool derivedName = false;
            if (!oldName.empty()) {
                for (const auto& n : element.names) {
                    if (!ancestry.contains(n, oldName)) {
                        continue;
                    }
                    const AncestryNodes nodes = ancestryNodes(n, state.type);
                    if (nodes.outside.count(oldName)) {
                        contains = true;
                        break;
                    }
                    if (nodes.derived.count(oldName)) {
                        derivedName = true;
                    }
                }
                if (!contains && derivedName && input.derived == Tier1Derived::Ancestry) {
                    contains = true;
                }
            }
            if (pool.exact.count(element.index) && !contains) {
                continue;
            }
            allowed[k] = 1;
            if (contains) {
                state.inAncestry.insert(static_cast<int>(k));
            }
            else if (derivedName) {
                state.derivedOnly.insert(static_cast<int>(k));
            }
            const bool same = fromMaker(static_cast<int>(k));
            for (const auto& name : element.names) {
                (same ? flatNames : otherNames).push_back(name);
                (same ? flatElements : otherElements).push_back(static_cast<int>(k));
            }
        }

        std::set<int> otherMaker;
        if (!oldName.empty() && input.source != Tier1Source::Names) {
            double best = 0.0;
            for (int i : ancestry.structuralSurvivors(oldName, flatNames, input.gap, 0.0, &best)) {
                state.fromOverlap.insert(flatElements[i]);
            }
            // Another maker's survivors within the band of both sets' best, as they were before
            // T1 left them out: not every element of the other maker that shares a node (PR
            // 149's review).
            if (!otherNames.empty()) {
                for (int i : ancestry.structuralSurvivors(oldName, otherNames, input.gap, best)) {
                    otherMaker.insert(otherElements[i]);
                }
            }
        }
        if (input.source != Tier1Source::Overlap) {
            for (int member : members) {
                // A name match made in other copies than the old name's is another element,
                // whatever the matcher made of the copy sections deep in its lineage (PR 243
                // round 3).
                const auto oldCopies = copyContexts(input.entries[member].oldName);
                for (const auto& name : input.entries[member].nameMatches) {
                    auto it = pool.byName.find(name);
                    if (it != pool.byName.end() && allowed[it->second]
                        && copyContexts(name) == oldCopies) {
                        state.fromNames.insert(it->second);
                        state.matchedNames.insert(name);
                    }
                }
            }
        }
        std::set<int> all(state.fromOverlap);
        all.insert(state.fromNames.begin(), state.fromNames.end());

        // The IDX source: the elements named by the old name's IDX section under any op code,
        // or by its index on a map-less target (Q5); and the old IDX element's pieces under
        // another op code, which join the candidates as pieces.
        std::string_view indexSource = NameAncestry::indexSource(oldName);
        if (!indexSource.empty()) {
            std::string maplessIndex =
                maplessElement(indexSource, input.maplessTag, std::get<1>(key));
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                if (!allowed[k]) {
                    continue;
                }
                const auto& names = pool.elements[k].names;
                if (pool.elements[k].index == maplessIndex
                    || std::any_of(names.begin(), names.end(), [&](const auto& n) {
                           return NameAncestry::sameIndexSource(n, indexSource);
                       })) {
                    state.fromIndex.insert(static_cast<int>(k));
                }
                else if (std::any_of(names.begin(), names.end(), [&](const auto& n) {
                             return NameAncestry::isIndexPieceOf(n, oldName);
                         })) {
                    all.insert(static_cast<int>(k));
                }
            }
        }
        // The old element's pieces, wherever tier 1's filters left them: a piece's top section
        // is its cutter's, so the top agreement among the overlap survivors can drop every
        // piece in favour of an element generated from the old one (Task 2 PR 7's review).
        if (!oldName.empty()) {
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& names = pool.elements[k].names;
                if (allowed[k] && std::any_of(names.begin(), names.end(), [&](const auto& n) {
                        return NameAncestry::isPieceOf(n, oldName);
                    })) {
                    all.insert(static_cast<int>(k));
                }
            }
        }
        // T1 for the name matches (the overlap's survivors are filtered above).
        for (auto it = all.begin(); it != all.end();) {
            if (fromMaker(*it)) {
                ++it;
            }
            else {
                otherMaker.insert(*it);
                it = all.erase(it);
            }
        }
        state.otherMaker.assign(otherMaker.begin(), otherMaker.end());
        // T1' (ops#173): a candidate must keep the old element's sources. Another hole cut by
        // the same pocket from another circle of its sketch shares the maker and the cut face,
        // as fully as a redraw of the hole's own circle does; it is no structural evidence that
        // the old element is still there. Without it, geometry decides (tier 3, G2 under policy
        // D: same source tag and maker, within reach, with a warning) or the entry breaks with
        // the candidates ranked. The old name's ancestry, its pieces and the IDX source stay.
        // Only the sources of what the maker made itself count (requiredSourcesOf()).
        const auto oldSources = input.sameSource && !oldName.empty()
            ? requiredSourcesOf(oldName)
            : std::vector<SourceSection>();
        // T1''s test for the pool's element \a k, which the twin clause's geometric pick must pass
        // too (PR 379 round 2's cloud review, F1)
        auto lostOldSource = [&](int k) {
            if (oldSources.empty()) {
                return false;
            }
            const auto& names = pool.elements[k].names;
            const bool kept = state.inAncestry.count(k) || state.fromIndex.count(k)
                || std::any_of(names.begin(), names.end(), [&](const auto& n) {
                       return NameAncestry::isPieceOf(n, oldName)
                           || NameAncestry::isIndexPieceOf(n, oldName);
                   });
            return !kept && lostASource(names, oldSources);
        };
        if (!oldSources.empty()) {
            for (auto it = all.begin(); it != all.end();) {
                if (lostOldSource(*it)) {
                    state.otherSource.push_back(*it);
                    it = all.erase(it);
                }
                else {
                    ++it;
                }
            }
        }
        // Merged neighbours (ops#446): an edge or vertex named after the faces it lies on (UPP),
        // whose faces aren't one face each in the target any more, may be gone with the boundary
        // between them. Two of them are one face (a refined Pipe's joint at a bend made straight:
        // the merged face keeps both legs' names), or one of them is on no face (a round pipe's
        // merged cylinder keeps one leg's name only; a Round corner bend made straight takes its
        // round face's counter name with it). Another bend's joint shares a face with it, and its
        // sources, so the overlap, T1 and T1' keep it, 20 mm away. A survivor fits if it lies on
        // two of the target's faces at least, each holding one of the old element's faces (a
        // vertex that still sits at the corner of the merged face and the others); the old name's
        // ancestry, its pieces and the IDX source fit, as for T1'. When none fits, none counts:
        // geometry decides (tier 3 at the same place, among them first; G2 under policy D) or the
        // entry breaks. When one fits, they all stay: the test empties the survivors or leaves
        // them, it never narrows them to a pick (fork PR 361 round 2: a merge older than the edit
        // arms it, and a Round corner's counter names can make another bend's vertex fit).
        // The UPP flag is read on the making section, the name's first (ops#454): a joint trimmed
        // by a later cut (`UPP{...}|CUT;MOD`) is the joint's piece, and a hole leaving one piece
        // of the other bend's joint beside it would make that piece tier 1's pick.
        // The survivors MN and MG never drop: the old name's ancestry, its pieces and the IDX
        // source, as for T1'.
        auto exempt = [&](int k) {
            const auto& names = pool.elements[k].names;
            return state.inAncestry.count(k) || state.fromIndex.count(k)
                || std::any_of(names.begin(), names.end(), [&](const auto& n) {
                       return NameAncestry::isPieceOf(n, oldName)
                           || NameAncestry::isIndexPieceOf(n, oldName);
                   });
        };
        if (!oldName.empty() && !input.faces.empty() && input.facesOf
            && (state.type == 'E' || state.type == 'V') && !all.empty()) {
            const auto linked =
                upperLinked(decodeSection(NameAncestry::splitSections(oldName).front()));
            const FaceHolders faces = linked.size() >= 2 ? faceHolders(linked) : FaceHolders();
            auto fits = [&](int k) {
                if (exempt(k)) {
                    return true;
                }
                std::set<std::string> on;
                for (auto& face : input.facesOf(pool.elements[k].index)) {
                    on.insert(std::move(face));
                }
                return on.size() >= 2 && std::all_of(on.begin(), on.end(), [&](const auto& face) {
                           return faces.holders.count(face) > 0;
                       });
            };
            if ((!faces.merged.empty() || faces.lost > 0)
                && std::none_of(all.begin(), all.end(), fits)) {
                state.otherFaces.assign(all.begin(), all.end());
                all.clear();
                state.mergedFaces = faces.merged;
                state.lostFaces = faces.lost;
            }
        }
        // A missing generator (MG, ops#454): an edge or vertex generated (GEN on its making
        // section) from an edge or vertex named after its faces (UPP, two at least), e.g. a
        // refined Pocket's hole vertex where a refined Pipe's joint edge enters the hole. When
        // that element's faces aren't one face each any more (merged or lost, as MN arms) and no
        // element of its type holds it, or a same-type descendant of it (a trimmed piece), it is
        // gone, and so is the point or edge it generated. A vertex on the same hole and the same
        // merged face shares more than half its ancestry, the maker and the sources: tier 1 took
        // the seam vertex, 1 mm away, silently. Every survivor that isn't exempt is dropped;
        // geometry decides (tier 3 at the same place, G2 under policy D) or the entry breaks,
        // listing them (role `other generator`). Both conditions are needed: a cylinder renamed
        // upstream renames its seam inside the seam vertices' names, so no edge reaches the old
        // seam although it's there, and a refined pipe's y sides are one face when it is saved,
        // so a joint vertex's faces are merged before any edit. Not in pattern instances: an
        // instance's names aren't the plain linked name.
        // The generators the old name's making section links, if it carries GEN, sorted and
        // distinct (MG and HG)
        std::vector<std::string> generators;
        if (!oldName.empty() && (state.type == 'E' || state.type == 'V')) {
            const auto& making = decodeSection(NameAncestry::splitSections(oldName).front());
            if (making.hasMapperFlag(MAPPER_FLAG_GENERATED)) {
                for (const auto& generator : making.linkedNames) {
                    if (!generator.empty() && generator != Data::EMPTY_VALUE) {
                        generators.push_back(generator);
                    }
                }
                std::sort(generators.begin(), generators.end());
                generators.erase(std::unique(generators.begin(), generators.end()),
                                 generators.end());
            }
        }
        // The elements of the pool of \a type (SolveInput::pool) that hold \a generator, or a
        // same-type descendant of it (a trimmed piece); none without a pool of the type
        auto holdersOf = [&](const std::string& generator, char type) {
            std::vector<const SolveInput::Element*> holders;
            const auto typePool = input.pool.find(type == 'F' ? "Face"
                                                  : type == 'E' ? "Edge"
                                                  : type == 'V' ? "Vertex"
                                                                : "");
            if (typePool == input.pool.end()) {
                return holders;
            }
            for (const auto& element : typePool->second) {
                if (std::any_of(element.names.begin(), element.names.end(), [&](const auto& n) {
                        return n == generator
                            || (ancestry.contains(n, generator)
                                && NameAncestry::reaches(n, generator, type)
                                    == NameAncestry::Reach::SameType);
                    })) {
                    holders.push_back(&element);
                }
            }
            return holders;
        };
        if (!input.faces.empty() && !all.empty() && patternInstances(oldName).empty()) {
            for (const auto& generator : generators) {
                const auto sections = NameAncestry::splitSections(generator);
                const auto linked = upperLinked(decodeSection(sections.front()));
                const char type = decodeSection(sections.back()).elementType;
                if (linked.size() < 2 || (type != 'E' && type != 'V')
                    || input.pool.find(type == 'E' ? "Edge" : "Vertex") == input.pool.end()) {
                    continue;
                }
                const FaceHolders faces = faceHolders(linked);
                if (faces.merged.empty() && faces.lost == 0) {
                    continue;
                }
                if (!holdersOf(generator, type).empty()) {
                    continue;
                }
                for (auto it = all.begin(); it != all.end();) {
                    if (exempt(*it)) {
                        ++it;
                    }
                    else {
                        state.otherGenerator.push_back(*it);
                        it = all.erase(it);
                    }
                }
                state.generatorType = type == 'E' ? "edge" : "vertex";
                state.generatorMergedFaces = faces.merged;
                state.generatorLostFaces = faces.lost;
                break;
            }
        }
        // A held generator (HG, ops#467), the converse of MG: an edge or vertex generated from an
        // element L that the target still holds (an element of L's type holds L, or a same-type
        // descendant of it) is the point or edge where L meets the other generators. A survivor
        // that L didn't generate isn't it: a refined Pipe's joint moved off a hole by a longer
        // leg keeps its name, and the seam vertex on the hole shares the cylinder, the leg's
        // face and their sources with the hole vertex the joint generated (4 of 7 nodes), the
        // maker and the hole's circle, so tier 1 took it, 1 mm away and silently; with holes at
        // both bends and the first made straight, the second bend's seam vertex went to the
        // other hole's, 12.9 mm away. A survivor fits L if one of its names has a making section
        // with GEN that links L, a same-type descendant of L (a trimmed piece), or another name
        // of an element holding L (a merged face holds both legs' names, and the whole circle on
        // it links one of them: the merged arc stays). Every held generator counts, not any one:
        // a seam vertex links the seam but not the joint (PLAN decision 124). The survivors that
        // don't fit are dropped, the exempt ones never; geometry decides (the exact place, tier
        // 3, G2 under policy D) or the entry breaks, listing them (role `other generator`). It
        // narrows: unlike MN, it reads the survivor's own making section, and a name is held now
        // or it isn't. Not in pattern instances, as MG. A generator nothing holds is MG's, T1''s
        // and geometry's, but for a face:
        // The face-generator net (ops#503 D1, class B's review CC3): a face generator that no face
        // holds (none carries its name or a same-type descendant of it) drops the survivors that
        // aren't exempt, as MG does for an edge or a vertex. A Pad's taper sends its caps down the
        // draft path, whose index names share nothing with the old ones: the top rim arc's
        // generator, the top cap, was held by nothing, the cylinder was, and HG kept the bottom
        // rim arc, made from the cylinder too, 5 mm down and silently. Made from a face that is
        // gone, the old element is none that a held face made; geometry decides (role `other
        // generator`). A face renamed through MOD is still held: the net fires only where a
        // face's lineage broke (a renamed cap, a redrawn profile). Off without a face pool, as
        // HG's test of a face is.
        if (!generators.empty() && !all.empty() && patternInstances(oldName).empty()) {
            struct Held
            {
                const std::string* generator;
                char type;
                std::set<std::string> names;  // the names of the elements holding it
                std::string holder;           // the first of them by index
            };
            std::vector<Held> held;
            for (const auto& generator : generators) {
                const auto sections = NameAncestry::splitSections(generator);
                if (sections.empty()) {
                    continue;
                }
                const char type = decodeSection(sections.back()).elementType;
                const auto holders = holdersOf(generator, type);
                if (holders.empty()) {
                    if (type == 'F' && input.pool.count("Face")) {
                        bool dropped = false;
                        for (auto it = all.begin(); it != all.end();) {
                            if (exempt(*it)) {
                                ++it;
                            }
                            else {
                                state.otherGenerator.push_back(*it);
                                it = all.erase(it);
                                dropped = true;
                            }
                        }
                        if (dropped && state.faceGenerator.empty()) {
                            state.faceGenerator = generator;
                        }
                    }
                    continue;
                }
                Held h {&generator, type, {}, {}};
                for (const auto* element : holders) {
                    h.names.insert(element->names.begin(), element->names.end());
                    const long a = indexNumber(element->index);
                    const long b = indexNumber(h.holder);
                    if (h.holder.empty() || a < b || (a == b && element->index < h.holder)) {
                        h.holder = element->index;
                    }
                }
                held.push_back(std::move(h));
            }
            // Whether one of \a names has a making section with GEN linking \a h's generator
            auto madeFrom = [&](const std::vector<std::string>& names, const Held& h) {
                return std::any_of(names.begin(), names.end(), [&](const auto& n) {
                    const auto sections = NameAncestry::splitSections(n);
                    if (sections.empty()) {
                        return false;
                    }
                    const auto& making = decodeSection(sections.front());
                    if (!making.hasMapperFlag(MAPPER_FLAG_GENERATED)) {
                        return false;
                    }
                    const auto& links = making.linkedNames;
                    return std::any_of(links.begin(), links.end(), [&](const auto& link) {
                        return link == *h.generator || h.names.count(link) > 0
                            || (!link.empty() && link != Data::EMPTY_VALUE
                                && ancestry.contains(link, *h.generator)
                                && NameAncestry::reaches(link, *h.generator, h.type)
                                    == NameAncestry::Reach::SameType);
                    });
                });
            };
            std::vector<bool> missed(held.size(), false);
            for (auto it = all.begin(); it != all.end();) {
                bool fits = true;
                if (!exempt(*it)) {
                    for (std::size_t i = 0; i < held.size(); ++i) {
                        if (!madeFrom(pool.elements[*it].names, held[i])) {
                            missed[i] = true;
                            fits = false;
                        }
                    }
                }
                if (fits) {
                    ++it;
                }
                else {
                    state.notGenerated.push_back(*it);
                    it = all.erase(it);
                }
            }
            for (std::size_t i = 0; i < held.size(); ++i) {
                if (missed[i]) {
                    state.heldGenerators.emplace_back(held[i].type == 'F'   ? "face"
                                                      : held[i].type == 'E' ? "edge"
                                                                            : "vertex",
                                                      held[i].holder);
                }
            }
        }
        // The twin clause (ops#503 class D, D1; I-S5): tier 1's one survivor named as the old
        // element up to an order key (isTwinName()) is its twin, not the element: they share
        // every node but the old one's own, so the overlap takes the twin wherever the old
        // element went. A hole's centre moved onto the edge it crossed made the right crossing
        // the seam vertex, and tier 1 took the left one, 1.9 mm away, silently. Geometry decides
        // over the whole pool (the no-candidate branch: the survivor is in it), under the
        // twin-pick rule. A lone survivor that is no twin stays tier 1's; two or more go to the
        // tie-break as before, where the rule judges the pick.
        if (all.size() == 1 && !oldName.empty()) {
            const int k = *all.begin();
            const auto& names = pool.elements[k].names;
            if (std::any_of(names.begin(), names.end(), [&](const auto& n) {
                    return isTwinName(n, oldName);
                })) {
                state.twinSurvivor = k;
                all.clear();
            }
        }
        // A piece of a far cap merged with others into one (ops#360, PR 340 round 3): the one
        // candidate whose name holds the old piece's (holdsMarkedPiece()) is the evidence, as a
        // name in its ancestry is, and the other survivors don't count. Their overlap is the
        // start cap's, which every piece of the cap shares, so the piece on the hole's fill
        // stayed within the gap of the ring, and the old piece's reference broke. Several old
        // pieces may merge into it (their entries take it together).
        // Round 4: when no name holds the old piece's marks, the one candidate marked by the old
        // piece's face alone (the only far cap on it) counts too, if the saved centre lies over
        // it: a strip across a hole made taller, with no other cap on its face. A renamed face
        // of a reordered up-to shell holds the name but not the old piece's centre.
        // The single-piece rule (ops#386): when no name holds the old piece's, the one element
        // that is its far edge or far cap made whole again (the same projection unmarked,
        // isWholeProjectionOf()) is the element if the saved centre lies on it and it lies on
        // the up-to faces the piece did (ops#522, below).
        if (!oldName.empty()) {
            const ElementFingerprint* centred = nullptr;
            for (const auto member : members) {
                const ElementFingerprint& fingerprint = input.entries[member].fingerprint;
                if (fingerprint.isValid() && fingerprint.center) {
                    centred = &fingerprint;
                    break;
                }
            }
            // Within a quarter of a face's side of its inside, or a hundredth of an edge's length
            // of the edge (ops#386). Round 6: a face's saved point inside it when there is one
            // (an L's centre lies outside the L, where a whole cap on the next plate holds it)
            const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
            // Round 7 (I-S9): a face whose area falls short of its outline's with no saved point
            // inside it (none found) refuses; its centre may lie outside it, so it can't stand in
            auto lacksInsidePoint = [&] {
                if (centred->type != 'F' || centred->inside || !centred->size
                    || centred->outline.size() < 3) {
                    return false;
                }
                const auto& outline = centred->outline;
                Base::Vector3d sum;
                for (std::size_t i = 1; i + 1 < outline.size(); ++i) {
                    sum += (outline[i] - outline.front()) % (outline[i + 1] - outline.front());
                }
                return *centred->size < 0.98 * sum.Length() / 2.0;
            };
            auto holdsSavedCentre = [&](int k) {
                if (!centred || !input.holdsPoint || lacksInsidePoint()) {
                    return false;
                }
                const double size = centred->size ? *centred->size : 0.0;
                const double reach = centred->type == 'E' ? size / 100.0 : std::sqrt(size) / 4.0;
                const Base::Vector3d& point = centred->inside ? *centred->inside : *centred->center;
                // Round 8: a face's point seen along the sweep, unless the old face lies along it
                // (as outlinesApart()). A tilted cap made whole on the next plate of a ridge
                // held the old strip's centre beside it by its nearest point, inside the cap
                if (centred->type == 'F' && input.sweep && input.holdsPointAlong) {
                    Base::Vector3d normal;
                    const auto& outline = centred->outline;
                    for (std::size_t i = 1; i + 1 < outline.size(); ++i) {
                        normal += (outline[i] - outline.front()) % (outline[i + 1] - outline.front());
                    }
                    if (outline.size() < 3 || normal.Length() <= eps * eps
                        || std::abs(normal.Normalize() * *input.sweep) > 0.01) {
                        return input.holdsPointAlong(pool.elements[k].index,
                                                     point,
                                                     *input.sweep,
                                                     reach + eps);
                    }
                }
                return input.holdsPoint(pool.elements[k].index, point, reach + eps);
            };
            auto holdersOf = [&](bool alone) {
                std::vector<int> holders;
                for (int k : all) {
                    const auto& names = pool.elements[k].names;
                    if (std::any_of(names.begin(), names.end(), [&](const auto& n) {
                            return holdsMarkedPiece(n, oldName, alone);
                        })) {
                        holders.push_back(k);
                    }
                }
                return holders;
            };
            std::vector<int> holders = holdersOf(false);
            if (holders.empty() && input.holdsPoint) {
                holders = holdersOf(true);
                if (holders.size() != 1 || !holdsSavedCentre(holders.front())) {
                    holders.clear();
                }
            }
            // Round 3: a far edge's piece after others of its pieces went, its marks the same
            // (isFewerPiecesOf()), is the element if it is the only piece with those marks and the
            // saved centre lies on it: the hole's fill piece left alone on its face when the piece
            // left of the hole goes. Pieces coming never count, since a face added to an up-to
            // shell without names may take another's index
            if (holders.empty() && input.holdsPoint) {
                int marked = 0;
                for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                    const auto& names = pool.elements[k].names;
                    if (std::any_of(names.begin(), names.end(), [&](const auto& n) {
                            return isCounterSibling(n, oldName, false);  // no other copy's
                        })) {
                        ++marked;
                        if (allowed[k] && std::any_of(names.begin(), names.end(), [&](const auto& n) {
                                return isFewerPiecesOf(n, oldName);
                            })) {
                            holders.push_back(static_cast<int>(k));
                        }
                    }
                }
                if (marked != 1 || holders.size() != 1 || !holdsSavedCentre(holders.front())) {
                    holders.clear();
                }
                else {
                    state.fewerPieces = holders.front();
                }
            }
            // A far edge or far cap made whole again takes its piece quietly, twins together,
            // like the ring rule above (PLAN decision 122 (2): a disc across an elliptic hole
            // that moves away from under it, both twins onto the whole cap), only on the up-to
            // faces the piece lay on (ops#522, decision 168). In the target's own frame the
            // profile may stay while the up-to plates move under it (round 9, decision 152), and
            // the edge or cap made whole on the next plate then holds a gone piece's saved point.
            // So the faces under the saved point now, the point carried by the target's current
            // placement into each face owner's own frame, must be those the fingerprint saved:
            // the same box, area, normal and outer wire there, and no other up-to face like
            // them. A plate rebuilt elsewhere, a face gone from under the point, a datum plane
            // (no box), or two faces that match one break the reference, as on integration
            // (decision 150). Only a piece the target made itself (its marked section's tag): a
            // later Pad keeps an earlier one's pieces, while its own up-to faces may stay put
            // when the earlier one's move (review pr398-r3)
            if (holders.empty() && input.holdsPoint && input.upToFacesAt) {
                for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                    const auto& names = pool.elements[k].names;
                    if (allowed[k] && std::any_of(names.begin(), names.end(), [&](const auto& n) {
                            return isWholeProjectionOf(n, oldName);
                        })) {
                        holders.push_back(static_cast<int>(k));
                    }
                }
                auto onSameUpToFaces = [&] {
                    std::vector<ElementFingerprint::UpToFace> now;
                    std::vector<ElementFingerprint::UpToFace> every;
                    const auto point = centred ? upToPointOf(*centred) : std::nullopt;
                    return point && !centred->upToFaces.empty()
                        && isMarkedPieceOf(oldName, input.targetTag)
                        && input.upToFacesAt(oldName, *point, now, every)
                        && sameUpToFaces(centred->upToFaces, now, every, eps, input.tolerances);
                };
                // The edge or cap made whole holds the saved point itself, as the save took it on
                // the piece (elementUpToFaces()): an edge within its reach of the point may lie on
                // the next plate, past a seam, while the saved face is still under the point; a
                // cap is seen along the sweep, as the up-to faces are, never by its nearest point
                // (review pr398-r4)
                auto holdsSavedPoint = [&](int k) {
                    if (!centred) {
                        return false;
                    }
                    const auto& index = pool.elements[k].index;
                    if (centred->type == 'E') {
                        const double coincidence = 1e-6 * std::max(1.0, input.diagonal);
                        return centred->center
                            && input.holdsPoint(index, *centred->center, coincidence);
                    }
                    if (centred->type != 'F' || !input.sweep || !input.holdsPointAlong
                        || lacksInsidePoint() || !centred->size) {
                        return false;
                    }
                    const Base::Vector3d& point = centred->inside ? *centred->inside : *centred->center;
                    return input.holdsPointAlong(index,
                                                 point,
                                                 *input.sweep,
                                                 std::sqrt(*centred->size) / 4.0 + eps);
                };
                if (holders.size() != 1 || !holdsSavedPoint(holders.front())
                    || !onSameUpToFaces()) {
                    holders.clear();
                }
            }
            if (holders.size() == 1) {
                all = {holders.front()};
                state.inAncestry.insert(holders.front());
                state.derivedOnly.erase(holders.front());
            }
        }
        state.candidates.assign(all.begin(), all.end());

        // Derived survivors only (ops#335, PLAN decision 81): every survivor reaches the old name
        // only through a node of another type or a GEN section, so none shows that the old
        // element is still there; a section edge on a face generated from the old edge survives
        // wherever the cut left it, a Thickness's copy of a corner 2 mm in (ops#358, decision
        // 86). They are G2's same-source evidence, not tier 1's: the no-candidate branch runs as
        // it is, over the whole pool, and they are listed first on a break.
        if (!state.candidates.empty()
            && std::all_of(state.candidates.begin(), state.candidates.end(), [&](int k) {
                   const auto& names = pool.elements[k].names;
                   return state.derivedOnly.count(k) > 0
                       && std::none_of(names.begin(), names.end(), [&](const auto& n) {
                              return NameAncestry::isPieceOf(n, oldName)
                                  || NameAncestry::isIndexPieceOf(n, oldName);
                          });
               })) {
            state.derived = std::move(state.candidates);
            state.candidates.clear();
        }

        // Tiers 2 and 3 and the IDX source, for a reference with a saved fingerprint.
        const ElementFingerprint* saved = savedFingerprint(members);
        state.saved = saved;
        auto intrinsicSurvivors = [&](const std::vector<int>& positions) {
            std::vector<int> agree;
            for (int k : positions) {
                if (intrinsicAgrees(*saved, fingerprintOf(pool.elements[k]), input.tolerances)) {
                    agree.push_back(k);
                }
            }
            return agree;
        };
        auto nearestOf = [&](const std::vector<int>& positions) {
            std::vector<ElementFingerprint> fingerprints;
            for (int k : positions) {
                fingerprints.push_back(fingerprintOf(pool.elements[k]));
            }
            return findNearest(*saved, fingerprints, input.diagonal, input.tolerances);
        };
        // The exact place (XP, ops#394): those of \a positions, tier 2's survivors, that lie at
        // the saved place. Asked where tier 3's gap test chose none: an element where the old one
        // was and as it was is the element, not one plausible candidate among others, though a
        // long board's other edge lies within d_max (decision 97 Q4)
        auto atPlaceAmong = [&](const std::vector<int>& positions) {
            std::vector<int> found;
            if (!input.exactPlace || !saved->center) {
                return found;
            }
            for (int k : positions) {
                if (atSamePlace(*saved,
                                fingerprintOf(pool.elements[k]),
                                input.diagonal,
                                input.tolerances,
                                input.continuationDistance)) {
                    found.push_back(k);
                }
            }
            return found;
        };
        // Several elements at the saved place (coincident twins of a compound): the entry breaks,
        // listing them first (role `place`), then the others of \a rest nearest first
        auto breakAtPlace = [&](const std::vector<int>& place,
                                const std::vector<int>& rest,
                                const char* role,
                                const std::string& why) {
            state.decided = true;
            state.outcome.evidence = "ambiguous: " + std::to_string(place.size())
                + " elements at the saved place" + why;
            listByDistance(state, place, "place");
            std::vector<int> others;
            for (int k : rest) {
                if (std::find(place.begin(), place.end(), k) == place.end()) {
                    others.push_back(k);
                }
            }
            const auto n = state.outcome.candidates.size();
            listByDistance(state, others, role, n < 8 ? 8 - n : std::size_t(0));
            listDropped(state);
        };
        // The twin-pick rule (ops#503 class D, D1; I-S5, I-S9): a single pick, whatever chose it
        // (XP, tier 3, G1, G2, tier 2 among the survivors), named as the old element up to an
        // order key (isTwinName()) is the old element's twin, and never quiet. The name and the
        // geometry can't tell a twin that took the old place from the old element: CC1, the
        // circle moved so that the left crossing landed exactly where the right one was, the
        // right one gone into the seam vertex, and tier 3 took the left one there, quietly. The
        // record can: the saved fingerprint's twin count (PR 340 round 5) against the pick's
        // order group now. No count saved (a record older than D1): a trade, the field the rule
        // needs being missing. One saved and the pick alone: a lone member renumbered (Lone), as
        // the branch takes it. Two or more: a pure renumbering (Pure, warned with its clause) if
        // the group has as many now and the pick's offset from their centroid is the saved one
        // (the twin block's 2 % tie, or its 12 degree band for a turned set); else a trade. The
        // batch never gives a twin pick the quieter level (mayBeQuietAtPlace()).
        enum class TwinPick
        {
            NotTwin,
            Lone,
            Pure,
            Trade,
        };
        int twinsNow = 0;
        auto twinPick = [&](int position) {
            const auto& names = pool.elements[position].names;
            if (oldName.empty() || std::none_of(names.begin(), names.end(), [&](const auto& n) {
                    return isTwinName(n, oldName);
                })) {
                return TwinPick::NotTwin;
            }
            // Its order group now: it and the type's elements with a name that is one of its
            // names up to an order key, as the record counts them (App::elementTwinCentroid())
            const ElementFingerprint& own = fingerprintOf(pool.elements[position]);
            std::optional<Base::Vector3d> centroid = own.center;
            twinsNow = 1;
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& other = pool.elements[k].names;
                if (static_cast<int>(k) == position
                    || std::none_of(other.begin(), other.end(), [&](const auto& m) {
                           return std::any_of(names.begin(), names.end(), [&](const auto& n) {
                               return isTwinName(m, n);
                           });
                       })) {
                    continue;
                }
                ++twinsNow;
                const ElementFingerprint& twin = fingerprintOf(pool.elements[k]);
                if (centroid && twin.center) {
                    *centroid += *twin.center;
                }
                else {
                    centroid.reset();
                }
            }
            const int count = saved ? saved->twinCount : 0;
            if (count == 1 && twinsNow == 1) {
                return TwinPick::Lone;
            }
            if (count < 2 || twinsNow != count || !centroid || !own.center || !saved->center
                || !saved->twinCentroid) {
                return TwinPick::Trade;
            }
            *centroid /= static_cast<double>(twinsNow);
            const double eps = input.continuationDistance * std::max(1.0, input.diagonal);
            const Base::Vector3d old = *saved->center - *saved->twinCentroid;
            const Base::Vector3d offset = *own.center - *centroid;
            if (Base::Distance(old, offset) <= old.Length() * 0.02 + eps) {
                return TwinPick::Pure;
            }
            constexpr double degrees = 180.0 / std::numbers::pi;
            const double shorter = std::min(old.Length(), offset.Length());
            const double longer = std::max(old.Length(), offset.Length());
            const bool turned = shorter > eps && shorter >= 0.75 * longer
                && std::atan2((old % offset).Length(), old * offset) * degrees <= 12.0;
            return turned ? TwinPick::Pure : TwinPick::Trade;
        };
        // The rule applied to the pick at \a position, chosen among \a rest: true if the entry
        // broke (a trade: the pick first, role `place` where the old element was, else
        // `geometric`; the twin clause's survivor (`structural`); then \a rest by distance, as
        // \a role); a pure renumbering keeps its clause for the evidence.
        auto twinBreaks = [&](int position, const std::vector<int>& rest, const char* role) {
            const TwinPick verdict = twinPick(position);
            const auto& index = pool.elements[position].index;
            if (verdict == TwinPick::Pure) {
                state.renumbered = position;
                state.renumberedClause = "; twin renumbered: " + index + " at its place among "
                    + std::to_string(twinsNow);
                return false;
            }
            if (verdict != TwinPick::Trade) {
                return false;
            }
            state.decided = true;
            const int count = saved ? saved->twinCount : 0;
            state.outcome.evidence = "ambiguous: " + index + " is the old element's twin ("
                + (count ? std::to_string(count) + (count == 1 ? " twin" : " twins") + " saved"
                         : std::string("no twin record"))
                + ", " + std::to_string(twinsNow) + " now)" + otherMakerText(state);
            const bool there = saved
                && atSamePlace(*saved,
                               fingerprintOf(pool.elements[position]),
                               input.diagonal,
                               input.tolerances,
                               input.continuationDistance);
            listByDistance(state, {position}, there ? "place" : "geometric");
            if (state.twinSurvivor >= 0 && state.twinSurvivor != position) {
                listByDistance(state, {state.twinSurvivor}, "structural");
            }
            std::vector<int> others;
            for (int k : rest) {
                if (k != position && k != state.twinSurvivor) {
                    others.push_back(k);
                }
            }
            const auto n = state.outcome.candidates.size();
            listByDistance(state, others, role, n < 8 ? 8 - n : std::size_t(0));
            listDropped(state);
            return true;
        };
        // The order test for a pick no name relates to the old element (tier 3 without structure,
        // G2), or an empty string. The hole's circle redrawn (its crossings named anew, the
        // reference broken at their place, PLAN decision 155), then moved by more than half its
        // crossings' spacing: G2 took the other crossing, the nearer one to the saved place, where
        // `integration` had followed the name taken at the redraw (PR 379 round 4's attack set,
        // ACrossings|redrawn-then-move). Where the record saved two twins or more and the pick has
        // an order group now (its names up to an order key, as twinPick() counts them), the pick
        // must be the member whose offset from the group's centroid is nearest the saved offset,
        // and the group the saved size; else the entry breaks. An old element's twin is
        // twinBreaks()'s.
        auto orderBreaks = [&](int position) -> std::string {
            if (!saved || saved->twinCount < 2 || !saved->center || !saved->twinCentroid
                || twinPick(position) != TwinPick::NotTwin) {
                return {};
            }
            const auto& names = pool.elements[position].names;
            std::vector<int> group {position};
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                const auto& other = pool.elements[k].names;
                if (static_cast<int>(k) != position
                    && std::any_of(other.begin(), other.end(), [&](const auto& m) {
                           return std::any_of(names.begin(), names.end(), [&](const auto& n) {
                               return isTwinName(m, n);
                           });
                       })) {
                    group.push_back(static_cast<int>(k));
                }
            }
            if (group.size() < 2) {
                return {};
            }
            Base::Vector3d centroid;
            bool measured = true;
            for (int k : group) {
                const auto& centre = fingerprintOf(pool.elements[k]).center;
                if (!centre) {
                    measured = false;
                    break;
                }
                centroid += *centre;
            }
            bool trade = !measured || static_cast<int>(group.size()) != saved->twinCount;
            if (!trade) {
                centroid /= static_cast<double>(group.size());
                const Base::Vector3d old = *saved->center - *saved->twinCentroid;
                auto miss = [&](int k) {
                    return Base::Distance(*fingerprintOf(pool.elements[k]).center - centroid, old);
                };
                const double own = miss(position);
                trade = std::any_of(group.begin() + 1, group.end(), [&](int k) {
                    return miss(k) <= own;
                });
            }
            if (!trade) {
                return {};
            }
            return pool.elements[position].index + " is out of its twins' saved order ("
                + std::to_string(saved->twinCount) + " twins saved, "
                + std::to_string(group.size()) + " now)";
        };
        // XP's source condition (ops#503 D1; I-S6, I-P1): the pick at the exact place that lacks
        // the old name's origin (otherOriginOf(): a new sketch object, policy D's case) says so;
        // the batch then warns it at the normal level, never the quieter same-place one.
        auto atPlaceText = [&](int position) {
            return otherOrigin(pool.elements[position], oldName) ? std::string(", another source")
                                                                 : std::string();
        };
        // The guess rules (N2 section 5): never against a failed target (N10), never without a
        // saved fingerprint (N8).
        const bool guessing = input.guess && !input.targetFailed && saved != nullptr;
        // Tier 3 with the guess rules' wider tolerances (G1, G2)
        auto wideNearestOf = [&](const std::vector<int>& positions) {
            GeometryTolerances wide = input.tolerances;
            wide.distance = input.tolerances.guessDistance;
            wide.gapFactor = input.tolerances.guessGapFactor;
            wide.size = input.tolerances.guessSize;
            std::vector<ElementFingerprint> fingerprints;
            for (int k : positions) {
                fingerprints.push_back(fingerprintOf(pool.elements[k]));
            }
            return findNearest(*saved, fingerprints, input.diagonal, wide);
        };
        // G3: the one piece whose extent holds the saved centre, or -1 (none or several, N5)
        auto pieceAtSavedCentre = [&](const std::vector<int>& pieces) {
            int found = -1;
            for (int k : pieces) {
                if (holdsCentre(*saved,
                                fingerprintOf(pool.elements[k]),
                                input.diagonal,
                                input.continuationDistance)) {
                    if (found >= 0) {
                        return -1;
                    }
                    found = k;
                }
            }
            return found;
        };

        // Pieces. Under One they break the entry at once. Under Expand they resolve together.
        // Under Equivalent they resolve as one candidate if every piece gives the consumer the
        // same result, represented by the piece whose first name sorts first; otherwise the
        // entry breaks. The other survivors don't count: the pieces are what is left of the old
        // element. Equivalent without pieces is One (see solveOwner()'s comment).
        std::vector<int> pieces;
        std::vector<int> others;
        for (int k : state.candidates) {
            const auto& names = pool.elements[k].names;
            bool piece = std::any_of(names.begin(), names.end(), [&](const auto& n) {
                return NameAncestry::isPieceOf(n, oldName)
                    || NameAncestry::isIndexPieceOf(n, oldName);
            });
            (piece ? pieces : others).push_back(k);
        }
        const bool equivalentPolicy = std::get<2>(key) == static_cast<int>(SolvePolicy::Equivalent);
        if (!pieces.empty() && equivalentPolicy) {
            std::vector<std::string> indexes;
            for (int k : pieces) {
                indexes.push_back(pool.elements[k].index);
            }
            auto results = groupEquivalent(indexes, [&](int a, int b) {
                return std::all_of(members.begin(), members.end(), [&](int member) {
                    const auto& equivalent = input.entries[member].equivalent;
                    return equivalent && equivalent(indexes[a], indexes[b]);
                });
            });
            if (results.size() != 1) {
                state.decided = true;
                state.outcome.evidence = "split into " + std::to_string(pieces.size())
                    + " pieces, " + std::to_string(results.size())
                    + " different results for the consumer";
                listCandidates(state, pieces);
                listCandidates(state, others);
                listDropped(state);
                continue;
            }
            int representative = *std::min_element(pieces.begin(), pieces.end(), [&](int a, int b) {
                const std::string na = firstName(pool.elements[a]);
                const std::string nb = firstName(pool.elements[b]);
                return na != nb ? na < nb : a < b;
            });
            state.equivalent = pieces;
            state.candidates = {representative};
            state.listed = pieces;
        }
        else if (!pieces.empty() && std::get<2>(key) == static_cast<int>(SolvePolicy::Expand)) {
            // Structural evidence, as for Equivalent: no geometry runs.
            state.expanded = pieces;
            state.candidates = {pieces.front()};
            state.listed = pieces;
        }
        else if (!pieces.empty()) {
            // G3: under One, the piece whose extent holds the saved centre, if exactly one does
            const int piece = guessing ? pieceAtSavedCentre(pieces) : -1;
            if (piece < 0) {
                state.decided = true;
                state.outcome.evidence = "split into " + std::to_string(pieces.size()) + " pieces";
                listCandidates(state, pieces);
                listCandidates(state, others);
                listDropped(state);
                continue;
            }
            state.guessKind = "piece";
            state.guessRole = "piece";
            for (int k : pieces) {
                if (k != piece) {
                    state.guessAlternatives.push_back(k);
                }
            }
            state.geometryEvidence = "guess: the piece at the saved centre, of "
                + std::to_string(pieces.size()) + " pieces";
            state.candidates = {piece};
            state.listed = pieces;
        }
        else {
            state.listed = state.candidates;
        }

        // The IDX source decides among its elements when tier 2 agrees with one: it names the
        // old element itself (or the whole it was a piece of), under the op code of whatever
        // last touched it. The other survivors don't count then.
        if (saved && pieces.empty() && !state.fromIndex.empty()) {
            std::vector<int> agree = intrinsicSurvivors(
                std::vector<int>(state.fromIndex.begin(), state.fromIndex.end())
            );
            if (!agree.empty()) {
                state.indexed = true;
                state.candidates = agree;
                state.listed = agree;
            }
        }

        // The survivors the merged-neighbour test dropped (ops#446) first: one that sits where
        // the old element sat is taken by tier 3, with its warning, before the whole pool is
        // searched (fork PR 361 round 2: a Round corner pipe's edit and back renames the faces by
        // their counters, and the pool holds a vertex 0.7 mm away). Another bend's joint is far.
        if (saved && state.candidates.empty() && !state.otherFaces.empty()) {
            std::vector<int> agree = intrinsicSurvivors(state.otherFaces);
            if (!agree.empty()) {
                Nearest nearest = nearestOf(agree);
                int pick = nearest.index >= 0 ? agree[nearest.index] : -1;
                // XP; several at the place are left to the whole pool, which breaks on them
                const auto place = pick < 0 ? atPlaceAmong(agree) : std::vector<int>();
                if (place.size() == 1) {
                    pick = place.front();
                }
                if (pick >= 0 && twinBreaks(pick, agree, "other faces")) {
                    continue;
                }
                if (pick >= 0) {
                    state.geometric = true;
                    state.geometryEvidence = std::string("no structural candidate, tier 3 among "
                                                         "tier 1's survivors off the old "
                                                         "element's faces")
                        + (nearest.index >= 0 ? std::string(": ")
                                             : ", at the same place" + atPlaceText(pick) + ": ")
                        + describeNearest(nearest);
                    state.candidates = {pick};
                    state.listed = state.candidates;
                }
            }
        }

        if (saved && state.candidates.size() > 1) {
            // Geometry breaks ties among tier 1's survivors; it never replaces them.
            std::vector<int> agree = intrinsicSurvivors(state.candidates);
            // A derived survivor (ops#335) is evidence only where tier 3 chose it: tier 2 alone
            // narrowing to it isn't enough, so tier 3 runs on it.
            if (agree.size() == 1 && !state.derivedOnly.count(agree.front())) {
                if (twinBreaks(agree.front(), state.listed, "structural")) {
                    continue;
                }
                state.geometryTier = 2;
                state.geometryEvidence = "tier 2: 1 of " + std::to_string(state.candidates.size());
                state.candidates = agree;
            }
            else if (!agree.empty()) {
                Nearest nearest = nearestOf(agree);
                const auto place = nearest.index < 0 ? atPlaceAmong(agree) : std::vector<int>();
                Nearest wide;
                if (nearest.index < 0 && place.empty() && guessing) {
                    wide = wideNearestOf(agree);
                }
                const int single = nearest.index >= 0 ? agree[nearest.index]
                    : place.size() == 1               ? place.front()
                    : wide.index >= 0                 ? agree[wide.index]
                                                      : -1;
                if (single >= 0 && twinBreaks(single, state.listed, "structural")) {
                    continue;
                }
                if (nearest.index >= 0) {
                    state.geometryTier = 3;
                    state.geometryEvidence = "tier 3: " + describeNearest(nearest);
                    state.candidates = {agree[nearest.index]};
                }
                else if (place.size() == 1) {
                    // XP: a thin member's two edges, both tier 1's survivors, within d_max
                    state.geometryTier = 3;
                    state.geometryEvidence = "tier 3, at the same place" + atPlaceText(single)
                        + ": " + describeNearest(nearest);
                    state.candidates = place;
                }
                else if (!place.empty()) {
                    breakAtPlace(place, state.listed, "structural", "");
                    continue;
                }
                else if (wide.index >= 0) {
                    // G1: tier 3's wider rule among the structural survivors tier 2 keeps
                    const int pick = agree[wide.index];
                    state.geometryTier = 3;
                    state.guessKind = "nearest";
                    state.guessRole = "structural";
                    state.geometryEvidence = "guess: tier 3 wide: " + describeNearest(wide);
                    for (int k : agree) {
                        if (k != pick) {
                            state.guessAlternatives.push_back(k);
                        }
                    }
                    state.candidates = {pick};
                }
                else if (agree.size() < state.candidates.size()) {
                    state.geometryTier = 2;
                    state.geometryEvidence = "tier 2: " + std::to_string(agree.size()) + " of "
                        + std::to_string(state.candidates.size());
                    state.candidates = agree;
                }
            }
        }
        else if (saved && state.candidates.empty()) {
            // Nothing structural: both geometric tiers must pass, on every element of the type
            // that no other reference of the owner holds exactly.
            std::vector<int> open;
            for (std::size_t k = 0; k < pool.elements.size(); ++k) {
                if (allowed[k]) {
                    open.push_back(static_cast<int>(k));
                }
            }
            std::vector<int> agree = intrinsicSurvivors(open);
            if (!agree.empty()) {
                Nearest nearest = nearestOf(agree);
                // XP: the board's top edge drawn again where it was, its other top edge within
                // d_max (ops#394)
                const auto place = nearest.index < 0 ? atPlaceAmong(agree) : std::vector<int>();
                if (nearest.index >= 0 || place.size() == 1) {
                    const int pick = nearest.index >= 0 ? agree[nearest.index] : place.front();
                    // After the twin clause, the pool holds what tier 1's filters dropped (another
                    // generator, another maker), and the pick must share the old name's origin,
                    // as G2's does (policy D): a hole's crossing whose twin went off the edge's
                    // end was taken at another hole's crossing, 0.77 away (PR 379 round 1). It must
                    // keep the old name's sources as well (T1''s test): another circle of the
                    // hole's own sketch, cut by the same pocket, shares the origin, and was taken
                    // there, at the same-place level when it lay at the saved place (round 2's
                    // cloud review, F1).
                    // XP's pick that lost the old name's sources breaks too, twin clause or not
                    // (PLAN decisions 155 and 165): a sibling of the old element's sketch dragged
                    // into its vacated place, within d_max of another element, can't be told from
                    // the element drawn again there (round 3's reviews), so ops#394's redraw
                    // breaks until D2 (ops#526) tells them apart. Tier 3's own nearest at the
                    // place resolves as before, never quietly (App::reboundInPlace()).
                    // So does XP's pick of another origin under T1' (PLAN decision 184): another
                    // link's copy of the old element's sketch, put where a copy that left the
                    // fuse had it, keeps the sketch source but not the old element's maker; a
                    // body's pad deleted and padded again from its sketch likewise. And so does
                    // its pick made in other copies than the old name's (decision 185, tier 1's
                    // test for name matches): the other copy's pad rim where a gone copy had its
                    // sketch's edge holds both. T1' off, it resolves with XP's warning (I-S6).
                    const char* lacks = nullptr;
                    if (state.twinSurvivor >= 0) {
                        lacks = otherOrigin(pool.elements[pick], oldName);
                    }
                    const bool atPlace = nearest.index < 0 || !atPlaceAmong({pick}).empty();
                    if (!lacks && (state.twinSurvivor >= 0 || nearest.index < 0)
                        && lostOldSource(pick)) {
                        lacks = "source element";
                    }
                    if (!lacks && nearest.index < 0 && input.sameSource) {
                        // An index-only reference (no old name) has no origin to share: it breaks
                        // here, as at tier 3's gap
                        lacks = otherOrigin(pool.elements[pick], oldName);
                        const auto oldCopies = copyContexts(oldName);
                        const auto& names = pool.elements[pick].names;
                        if (!lacks && !oldName.empty() && !names.empty()
                            && std::none_of(names.begin(), names.end(), [&](const auto& n) {
                                return copyContexts(n) == oldCopies;
                            })) {
                            lacks = "copy";
                        }
                    }
                    const std::string why = lacks
                        ? pool.elements[pick].index + " has another " + lacks
                        : orderBreaks(pick);
                    if (!why.empty()) {
                        state.decided = true;
                        state.outcome.evidence = (nearest.index >= 0
                                                      ? std::string("no structural candidate, tier 3: ")
                                                      : "no structural candidate, at the same place: ")
                            + describeNearest(nearest) + "; the pick " + why
                            + derivedText(state, &agree) + otherMakerText(state);
                        // The pick, then the twin tier 1 named (the user's likelier choice
                        // when the twin went, if one did), then the rest by distance. A pick at
                        // the saved place is listed as such, so the report says it sits there.
                        listByDistance(state, {pick}, atPlace ? "place" : "geometric");
                        if (state.twinSurvivor >= 0 && state.twinSurvivor != pick) {
                            listByDistance(state, {state.twinSurvivor}, "structural");
                        }
                        std::vector<int> others;
                        for (int k : agree) {
                            if (k != pick && k != state.twinSurvivor) {
                                others.push_back(k);
                            }
                        }
                        const auto n = state.outcome.candidates.size();
                        listByDistance(state, others, "geometric", n < 8 ? 8 - n : std::size_t(0));
                        listDropped(state);
                        continue;
                    }
                    if (twinBreaks(pick, agree, "geometric")) {
                        continue;
                    }
                    state.geometric = true;
                    state.geometryEvidence = (nearest.index >= 0
                                                  ? std::string("no structural candidate, tier 3: ")
                                                  : "no structural candidate, at the same place"
                                                      + atPlaceText(pick) + ": ")
                        + describeNearest(nearest) + derivedText(state, nullptr);
                    state.candidates = {pick};
                    state.listed = state.candidates;
                }
                else if (!place.empty()) {
                    breakAtPlace(place,
                                 agree,
                                 "geometric",
                                 derivedText(state, &agree) + otherMakerText(state));
                    continue;
                }
                else {
                    // G2: tier 3's wider rule without structure, behind its own switch. Policy D
                    // (ops#127, N3 4.4): the pick must share an innermost source with the old
                    // name, as a line redrawn in its sketch does; an element of another source
                    // (a neighbour of a deleted feature, a new sketch object) is no guess, and
                    // the reference breaks with the candidates by distance. G2' (ops#167): the
                    // pick must also come from the old element's maker.
                    Nearest wide;
                    if (guessing && input.guessNoStructure) {
                        wide = wideNearestOf(agree);
                    }
                    std::string otherSource;
                    if (wide.index >= 0 && (!input.guessAnySource || state.twinSurvivor >= 0)) {
                        const auto& picked = pool.elements[agree[wide.index]];
                        const char* lacks = otherOrigin(picked, oldName);
                        // after the twin clause, T1''s test too (F1, as above)
                        if (!lacks && state.twinSurvivor >= 0 && lostOldSource(agree[wide.index])) {
                            lacks = "source element";
                        }
                        if (lacks) {
                            otherSource = "; the wide reach's " + picked.index + " has another "
                                + lacks;
                            wide = Nearest();
                        }
                    }
                    if (wide.index >= 0) {
                        const std::string order = orderBreaks(agree[wide.index]);
                        if (!order.empty()) {
                            otherSource = "; the wide reach's " + order;
                            wide = Nearest();
                        }
                    }
                    if (wide.index < 0) {
                        state.decided = true;
                        state.outcome.evidence = "no structural candidate, tier 3 found none: "
                            + describeNearest(nearest) + otherSource
                            + derivedText(state, &agree) + otherMakerText(state);
                        listDerivedFirst(state, agree);
                        listDropped(state);
                        continue;
                    }
                    const int pick = agree[wide.index];
                    if (twinBreaks(pick, agree, "geometric")) {
                        continue;
                    }
                    state.geometric = true;
                    state.guessKind = "geometric";
                    state.guessRole = "geometric";
                    state.geometryEvidence
                        = std::string(
                              input.guessAnySource
                                  ? "guess: no structural candidate"
                                  : "guess: no structural candidate, redrawn in the same source"
                          )
                        + ", tier 3 wide: " + describeNearest(wide) + derivedText(state, nullptr);
                    for (int k : agree) {
                        if (k != pick) {
                            state.guessAlternatives.push_back(k);
                        }
                    }
                    state.candidates = {pick};
                    state.listed = state.candidates;
                }
            }
        }

        if (state.candidates.empty()) {
            state.decided = true;
            static const std::vector<int> none;
            state.outcome.evidence = "no candidate"
                + derivedText(state, saved ? &none : nullptr)
                + (saved || state.derived.empty() ? "" : ", no saved fingerprint")
                + otherMakerText(state);
            listDerivedFirst(state, {});
            listDropped(state);
            continue;
        }

        state.graphEntry = graph.entryCount++;
        if (!state.equivalent.empty()) {
            // One candidate holding every equivalent element, so that no other entry takes one
            // of them; it stands for its representative.
            std::vector<int> ids;
            for (int k : state.equivalent) {
                ids.push_back(pool.ids[k]);
            }
            int representative = state.candidates.front();
            int node = graph.addCandidate(std::move(ids));
            representativeOfNode[node] = pool.ids[representative];
            graph.addEdge(state.graphEntry, node, state.inAncestry.count(representative) > 0);
            continue;
        }
        if (!state.expanded.empty()) {
            // One candidate holding every piece: the pieces are matched as a set. They hold the
            // old name in their ancestry.
            std::vector<int> ids;
            for (int k : state.expanded) {
                ids.push_back(pool.ids[k]);
            }
            int node = graph.addCandidate(std::move(ids));
            representativeOfNode[node] = pool.ids[state.expanded.front()];
            graph.addEdge(state.graphEntry, node, true);
            continue;
        }
        for (int k : state.candidates) {
            int id = pool.ids[k];
            auto [it, inserted] = nodeOfId.emplace(id, 0);
            if (inserted) {
                it->second = graph.addCandidate({id});
            }
            graph.addEdge(state.graphEntry, it->second, state.inAncestry.count(k) > 0);
        }
    }

    MatchResult matched = forcedMatching(graph);
    std::map<int, int> idOfNode(representativeOfNode);
    for (const auto& [id, node] : nodeOfId) {
        idOfNode[node] = id;
    }

    for (auto& state : states) {
        if (!state.decided) {
            int e = state.graphEntry;
            MatchStatus status = matched.status[e];
            int k = status == MatchStatus::Resolved
                ? elementOfId[idOfNode[matched.partner[e]]].second
                : -1;
            // A partner named as the old element up to the duplicate counter is a sibling (a
            // pattern instance's copy of it), never the element itself: its ancestry and its top
            // section are the old element's, so the evidence below can't tell them apart.
            auto siblingElement = [&](int position) {
                const auto& names = state.pool->elements[position].names;
                return std::any_of(names.begin(), names.end(), [&](const auto& n) {
                    return isCounterSibling(n, state.oldName);
                });
            };
            // But a piece of a far edge or cap counted by its place among the pieces (ORD) that
            // sits where the old piece was is the old piece, renumbered because another piece
            // went or came (PR 366 round 2); a pattern's copy never sits there. So is the one
            // piece with its marks after others went, the saved centre on it (round 3)
            auto renumbered = [&](int position) {
                if (position == state.fewerPieces) {
                    return true;
                }
                // Another copy's piece at the old place is no renumbering of this one: copy 0
                // gone and copy 1 moved onto its place (ops#523, the A3 pre-push review's T2)
                const auto& names = state.pool->elements[position].names;
                const bool otherCopy
                    = std::any_of(names.begin(), names.end(), [&](const auto& n) {
                          return isCounterSibling(n, state.oldName);
                      })
                    && std::none_of(names.begin(), names.end(), [&](const auto& n) {
                           return isCounterSibling(n, state.oldName, false);
                       });
                return !otherCopy && state.saved && isOrdered(state.oldName)
                    && atSamePlace(
                           *state.saved,
                           fingerprintOf(state.pool->elements[position]),
                           input.diagonal,
                           input.tolerances,
                           input.continuationDistance
                    );
            };
            bool sibling = k >= 0 && !renumbered(k)
                && (state.expanded.empty() ? siblingElement(k)
                                           : std::any_of(state.expanded.begin(),
                                                         state.expanded.end(),
                                                         siblingElement));
            // A partner from tier 1 must agree with the old name on the top section, or hold the
            // old name in its ancestry: an ancestor shared with the old name alone (e.g. a sketch
            // edge that many elements embed through a face) doesn't show it is the same element.
            // A partner that only geometry found passed both geometric tiers. The IDX source and
            // the old element's pieces (an IDX element's pieces under another op code don't hold
            // the old name) are evidence of their own. The name that agrees on the top section
            // must be one tier 1 found the partner by: one the name match returned, or one that
            // shares an ancestor with the old name. A partner found through one name (a far
            // cap's PRJ name, which embeds the old start cap's) that holds another, unrelated name
            // with the same top op code (another sketch's plain name, where the far cap meets a
            // base element) has no evidence (PR 243 round 6). Nor one that shares an ancestor
            // through a projection's embedded names on one side only, or through the connected
            // elements (AncestryNodes, PR 243 round 7): where both caps meet base elements, the
            // far cap's PRJ name and the start cap's name are both topped by FUS;MOD, and the PRJ
            // name embeds the start cap's.
            std::optional<AncestryNodes> oldNodes;
            auto related = [&](const std::string& name) {
                if (!oldNodes) {
                    oldNodes = ancestryNodes(state.oldName);
                }
                return ancestryNodes(name).meets(*oldNodes);
            };
            // A derived survivor among others (ops#335) is evidence only where tier 3 (strict or
            // G1) chose it: its lineage holds the old element's source, not the old element.
            const bool derivedPartner = k >= 0 && state.derivedOnly.count(k) > 0;
            bool evidenced = k >= 0
                && (state.geometric || (state.indexed && state.fromIndex.count(k) > 0)
                    || (derivedPartner
                            ? state.geometryTier == 3
                            : state.inAncestry.count(k) > 0 || !state.equivalent.empty()
                                || !state.expanded.empty()
                                || std::any_of(
                                    state.pool->elements[k].names.begin(),
                                    state.pool->elements[k].names.end(),
                                    [&](const auto& n) {
                                        return NameAncestry::topAgrees(state.oldName, n)
                                            && (state.matchedNames.count(n) > 0
                                                || related(n));
                                    }
                                )));
            // A partner that tier 1 alone found must not contradict the saved geometry (ops#87:
            // a thread's B-spline edge resolved to a circle with which it shares sources). The
            // geometric tiers, the IDX source and pieces checked or need no check.
            bool contradicts = false;
            if (k >= 0 && state.saved && input.check != Tier1Check::None && !state.geometric
                && state.geometryTier == 0 && !state.indexed && state.equivalent.empty()
                && state.expanded.empty()) {
                const ElementFingerprint& now = fingerprintOf(state.pool->elements[k]);
                contradicts = input.check == Tier1Check::Kind
                    ? !(now.isValid() && now.type == state.saved->type
                        && now.kind == state.saved->kind)
                    : !intrinsicAgrees(*state.saved, now, input.tolerances);
            }
            if (status == MatchStatus::Resolved && sibling) {
                state.outcome.evidence = "pattern sibling";
                listCandidates(state, state.listed, state.geometric ? "geometric" : nullptr);
            }
            else if (status == MatchStatus::Resolved && !evidenced && derivedPartner) {
                std::string path;
                for (const auto& name : state.pool->elements[k].names) {
                    path = derivedPathOf(name, state.oldName, state.type);
                    if (!path.empty()) {
                        break;
                    }
                }
                state.outcome.evidence = state.pool->elements[k].index + " is in ancestry "
                    + derivedVia(path) + (path.empty() ? "" : " (" + path + ")")
                    + ", tier 3 didn't choose it"
                    + (state.geometryEvidence.empty() ? "" : ", " + state.geometryEvidence);
                listCandidates(state, state.listed);
            }
            else if (status == MatchStatus::Resolved && !evidenced) {
                state.outcome.evidence = "no top agreement";
                listCandidates(state, state.listed, state.geometric ? "geometric" : nullptr);
            }
            else if (status == MatchStatus::Resolved && contradicts) {
                state.outcome.evidence = "tier 2 disagrees with "
                    + state.pool->elements[k].index;
                listCandidates(state, state.listed, state.geometric ? "geometric" : nullptr);
            }
            else if (status == MatchStatus::Resolved && !state.expanded.empty()) {
                state.outcome.status = SolveStatus::Resolved;
                state.outcome.tier = 1;
                for (int piece : state.expanded) {
                    state.outcome.elements.push_back(state.pool->elements[piece].index);
                    state.outcome.names.push_back(firstName(state.pool->elements[piece]));
                }
                state.outcome.element = state.outcome.elements.front();
                state.outcome.name = state.outcome.names.front();
                state.outcome.evidence = "split into " + std::to_string(state.expanded.size())
                    + " pieces, expanded";
            }
            else if (status == MatchStatus::Resolved) {
                const auto& element = state.pool->elements[k];
                double best = 0.0;
                for (const auto& name : element.names) {
                    best = std::max(best, ancestry.overlap(state.oldName, name));
                }
                std::string sources;
                if (state.fromOverlap.count(k)) {
                    sources = "overlap";
                }
                if (state.fromNames.count(k)) {
                    sources += sources.empty() ? "names" : "+names";
                }
                if (state.indexed && state.fromIndex.count(k)) {
                    sources += sources.empty() ? "index" : "+index";
                }
                state.outcome.status = SolveStatus::Resolved;
                state.outcome.tier = state.geometric ? 3 : state.geometryTier ? state.geometryTier : 1;
                state.outcome.element = element.index;
                state.outcome.name = firstName(element);
                if (!state.guessKind.empty()) {
                    // A guess rule's pick (ops#127): the pick first, then the alternatives in
                    // rank order (nearest centre first), with their distances.
                    state.outcome.status = SolveStatus::Guessed;
                    state.outcome.guessKind = state.guessKind;
                    auto distanceOf = [&](int position) {
                        const ElementFingerprint& now =
                            fingerprintOf(state.pool->elements[position]);
                        return state.saved && state.saved->center && now.center
                            ? Base::Distance(*state.saved->center, *now.center)
                            : std::numeric_limits<double>::quiet_NaN();
                    };
                    auto addCandidate = [&](int position, const char* role) {
                        const auto& candidate = state.pool->elements[position];
                        state.outcome.candidates.push_back(candidate.index);
                        state.outcome.candidateNames.push_back(
                            candidate.names.empty() ? std::string() : candidate.names.front()
                        );
                        state.outcome.candidateRoles.emplace_back(role);
                        state.outcome.candidateDistances.push_back(distanceOf(position));
                    };
                    addCandidate(k, "guess");
                    std::vector<int> alternatives = state.guessAlternatives;
                    std::stable_sort(alternatives.begin(), alternatives.end(), [&](int a, int b) {
                        const double da = distanceOf(a);
                        const double db = distanceOf(b);
                        return std::isnan(db) ? !std::isnan(da) : da < db;
                    });
                    for (int position : alternatives) {
                        addCandidate(position,
                                     state.derivedOnly.count(position) ? "derived"
                                                                       : state.guessRole);
                    }
                }
                else if (state.geometric || state.geometryTier >= 2) {
                    // Geometry chose among tier 1's survivors: the others are the alternatives
                    // the user may prefer (ops#127).
                    std::vector<int> others;
                    for (int position : state.listed) {
                        if (position != k) {
                            others.push_back(position);
                        }
                    }
                    listCandidates(state, others, state.geometric ? "geometric" : nullptr);
                    // The derived survivors geometry passed over (ops#335)
                    others.clear();
                    for (int position : state.derived) {
                        if (position != k) {
                            others.push_back(position);
                        }
                    }
                    listCandidates(state, others, "derived");
                }
                if (state.geometric || !state.guessKind.empty()) {
                    state.outcome.evidence = state.geometryEvidence;
                }
                else {
                    state.outcome.evidence = "overlap " + formatOverlap(best) + ", sources "
                        + sources + (state.inAncestry.count(k) ? ", in ancestry" : "")
                        + (state.indexed ? ", tier 2 agrees" : "")
                        + (state.geometryEvidence.empty() ? "" : ", " + state.geometryEvidence)
                        + (state.equivalent.empty()
                               ? ""
                               : ", " + std::to_string(state.equivalent.size())
                                   + " pieces equivalent for the consumer");
                }
                // The twin-pick rule's pure renumbering (ops#503 D1): its own words, which the
                // batch never warns at the quieter level
                if (k == state.renumbered) {
                    state.outcome.evidence += state.renumberedClause;
                }
            }
            else {
                state.outcome.evidence = status == MatchStatus::TooLarge ? "too large to solve"
                    : status == MatchStatus::NoCandidate                 ? "no candidate"
                                                                         : "ambiguous";
                if (!state.geometryEvidence.empty()) {
                    state.outcome.evidence += ", " + state.geometryEvidence;
                }
                listCandidates(state, state.listed, state.geometric ? "geometric" : nullptr);
            }
            if (state.outcome.status == SolveStatus::Broken) {
                listDropped(state);
            }
        }
        if (state.twinSurvivor >= 0) {
            state.outcome.evidence = "tier 1's one survivor is the old element's twin ("
                + state.pool->elements[state.twinSurvivor].index + "); geometry decides; "
                + state.outcome.evidence;
        }
        for (int member : *state.members) {
            outcomes[member] = state.outcome;
            if (!state.outcome.elements.empty()) {
                // Expanded: a member that was a piece already passes its `from` on.
                const auto& from = input.entries[member].from;
                outcomes[member].from = from.empty() ? state.oldName : from;
            }
        }
    }
    return outcomes;
}

}  // namespace Data
