// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2008 Werner Mayer <wmayer[at]users.sourceforge.net>     *
 *                                                                         *
 *   This file is part of the FreeCAD CAx development system.              *
 *                                                                         *
 *   This library is free software; you can redistribute it and/or         *
 *   modify it under the terms of the GNU Library General Public           *
 *   License as published by the Free Software Foundation; either          *
 *   version 2 of the License, or (at your option) any later version.      *
 *                                                                         *
 *   This library  is distributed in the hope that it will be useful,      *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
 *   GNU Library General Public License for more details.                  *
 *                                                                         *
 *   You should have received a copy of the GNU Library General Public     *
 *   License along with this library; see the file COPYING.LIB. If not,    *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,         *
 *   Suite 330, Boston, MA  02111-1307, USA                                *
 *                                                                         *
 ***************************************************************************/

#include <algorithm>
#include <array>
#include <limits>
#include <set>
#include <string_view>

#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRep_Tool.hxx>
#include <Geom_Circle.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopExp_Explorer.hxx>
#include <ShapeFix_Shape.hxx>

#include <Base/Exception.h>
#include <App/Document.h>
#include <App/NameTable.h>
#include <Base/Reader.h>
#include <Mod/Part/App/Part2DObject.h>
#include <Mod/Part/App/FilletFallback.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/TopoShapeOpCode.h>
#include <Mod/Part/App/TopoShapeRepair.h>

#include "FeatureFillet.h"
#include "ResultCheck.h"


using namespace PartDesign;

namespace PartDesign
{
// FeatureDressUp.cpp (ops#640 F2, Onshape's failure text; declared where used)
PartDesignExport std::string dressUpFailure(const char* verb, const std::string& what);
PartDesignExport bool isDressUpFailure(const std::string& what);
// FeatureDressUp.cpp (FreeCAD-CH ops#654 T3; declared where used)
PartDesignExport bool dressUpReapplying(Part::TopoShape& base, std::vector<Part::TopoShape>& edges);
PartDesignExport void dressUpReapplied(const Part::TopoShape& result);
// ops#796 (FeatureDressUp.cpp): a studio step takes what its owner's try built
PartDesignExport void dressUpReappliedFrom(const Part::TopoShape& raw,
                                           const Part::TopoShape& result,
                                           bool plain);
PartDesignExport bool studioDressUpTake(const DressUp* step,
                                        const Part::TopoShape& base,
                                        const std::vector<Part::TopoShape>& edges,
                                        Part::TopoShape& raw);
PartDesignExport const DressUp* dressUpTriedFor(const DressUp* step);
PartDesignExport void dressUpReappliedNote(const std::string& note);
// FeatureDressUp.cpp (FreeCAD-CH ops#654 P8a; declared where used)
PartDesignExport App::DocumentObjectExecReturn* studioDressUpOwnerRun(DressUp* owner);
PartDesignExport bool studioDressUpStepPassesThrough(DressUp* step);
PartDesignExport bool runsAsStudioOwner(const Feature* feature);
// FeatureDressUp.cpp (ops#655, tangent propagation off)
PartDesignExport std::vector<Part::TopoShape> takeChainedEdges(
    const Part::TopoShape& base,
    std::vector<Part::TopoShape>& edges,
    double radius
);
PartDesignExport TopoDS_Shape runOutCut(
    const TopoDS_Shape& shape,
    const TopoDS_Shape& base,
    const TopoDS_Edge& edge,
    double radius,
    bool arc
);
PartDesignExport std::vector<std::array<TopoDS_Shape, 3>> takeArcRunOns(
    const Part::TopoShape& base,
    std::vector<Part::TopoShape>& edges,
    std::vector<Part::TopoShape>& runOut,
    double radius
);
PartDesignExport Part::TopoShape applyArcRunOns(
    Part::TopoShape shape,
    const Part::TopoShape& base,
    const std::vector<std::array<TopoDS_Shape, 3>>& runOns,
    const Part::TopoShape& blank
);
}  // namespace PartDesign


PROPERTY_SOURCE(PartDesign::Fillet, PartDesign::DressUp)

const App::PropertyQuantityConstraint::Constraints floatRadius
    = {0.0, std::numeric_limits<float>::max(), 0.1};

Fillet::Fillet()
{
    ADD_PROPERTY_TYPE(Radius, (1.0), "Fillet", App::Prop_None, "Fillet radius.");
    Radius.setUnit(Base::Unit::Length);
    Radius.setConstraints(&floatRadius);
    ADD_PROPERTY_TYPE(
        UseAllEdges,
        (false),
        "Fillet",
        App::Prop_None,
        "Fillet all edges if true, else use only those edges in Base property.\n"
        "If true, then this overrides any edge changes made to the Base property or in the "
        "dialog.\n"
    );
    ADD_PROPERTY_TYPE(
        TangentPropagation,
        (true),
        "Fillet",
        App::Prop_None,
        "Fillet the whole tangent chain of each picked edge (Onshape's 'Tangent propagation').\n"
        "Off: only the picked edges; where a picked straight edge continues tangentially, the\n"
        "fillet runs straight on until it leaves the body, as Onshape's does."
    );
}

short Fillet::mustExecute() const
{
    if (Placement.isTouched() || Radius.isTouched() || TangentPropagation.isTouched()) {
        return 1;
    }
    return DressUp::mustExecute();
}

App::DocumentObjectExecReturn* Fillet::execute()
{
    // FreeCAD-CH ops#701 (F2b): over several parts, this part failing while the first part's
    // builds is a warning, as Onshape's FILLET_PARTIAL_FAIL
    return partialFailure(build(), "fillet", "Radius");
}

namespace
{
// ops#951 (notes/fullround-name-order-900.md 3c): the dress-up's BaseFeature chain, its first
// feature first, for the names of a merged full round. Ids and places only; the objects are
// read during this execute
class ChainOrder: public Part::FilletFallback::FeatureOrder
{
public:
    explicit ChainOrder(const App::DocumentObject* base)
    {
        std::set<const App::DocumentObject*> seen;
        for (const App::DocumentObject* object = base; object && seen.insert(object).second;) {
            Entry entry;
            entry.object = object;
            entry.id = object->getID();
            const auto* feature = dynamic_cast<const PartDesign::Feature*>(object);
            entry.naming = feature ? feature->namingTag() : 0;
            for (const App::DocumentObject* read : object->getOutList()) {
                if (read && read->isDerivedFrom<Part::Part2DObject>()) {
                    entry.sketches.push_back(read->getID());
                }
            }
            chain.push_back(std::move(entry));
            object = feature ? feature->BaseFeature.getValue() : nullptr;
        }
        std::reverse(chain.begin(), chain.end());
    }

    int place(long tag) const override
    {
        for (size_t at = 0; at < chain.size(); ++at) {
            if (tag != 0 && (chain[at].id == tag || chain[at].naming == tag)) {
                return static_cast<int>(at);
            }
        }
        return -1;
    }

    int sketchMaker(long sketch, const std::string& section) const override
    {
        for (size_t at = 0; at < chain.size(); ++at) {
            const auto& sketches = chain[at].sketches;
            if (std::find(sketches.begin(), sketches.end(), sketch) == sketches.end()) {
                continue;
            }
            const auto* feature = dynamic_cast<const Part::Feature*>(chain[at].object);
            if (!feature) {
                continue;
            }
            for (const auto& element : feature->Shape.getShape().getElementMap()) {
                const std::string name = Data::NameTable::instance().toPlain(element.name.toString());
                if (name.compare(0, section.size(), section) == 0
                    && (name.size() == section.size() || name[section.size()] == '|')) {
                    return static_cast<int>(at);
                }
            }
        }
        return -1;
    }

    std::vector<long> sketchesAt(int place) const override
    {
        return place >= 0 && static_cast<size_t>(place) < chain.size()
            ? chain[static_cast<size_t>(place)].sketches
            : std::vector<long>();
    }

    int lastChange(const Data::MappedName& name, int place) const override
    {
        if (place < 0 || static_cast<size_t>(place) >= chain.size()) {
            return place;
        }
        // A feature whose result first has the name, or has it again after one without it, made
        // the edge anew (a slot leaving a remnant renames the piece: review pr503-r1 T1)
        int last = place;
        TopoDS_Shape previous = edgeNamed(static_cast<size_t>(place), name);
        bool gap = previous.IsNull();
        for (size_t at = static_cast<size_t>(place) + 1; at < chain.size(); ++at) {
            const TopoDS_Shape edge = edgeNamed(at, name);
            if (edge.IsNull()) {
                gap = true;
                continue;
            }
            if (gap || !sameEnds(previous, edge)) {
                last = static_cast<int>(at);
            }
            previous = edge;
            gap = false;
        }
        return last;
    }

private:
    // The edge of that name in the result of the feature at  at, or null
    TopoDS_Shape edgeNamed(size_t at, const Data::MappedName& name) const
    {
        const auto* feature = dynamic_cast<const Part::Feature*>(chain[at].object);
        if (!feature) {
            return {};
        }
        const Part::TopoShape shape = feature->Shape.getShape();
        const Data::IndexedName index = shape.getIndexedName(name);
        if (!index || std::string(index.getType()) != "Edge") {
            return {};
        }
        return shape.getSubShape(TopAbs_EDGE, index.getIndex(), /*silent=*/true);
    }

    // Whether a later feature left the edge as it was: the same edge, or one with the same ends
    static bool sameEnds(const TopoDS_Shape& a, const TopoDS_Shape& b)
    {
        if (a.IsSame(b)) {
            return true;
        }
        TopoDS_Vertex a1, a2, b1, b2;
        TopExp::Vertices(TopoDS::Edge(a), a1, a2);
        TopExp::Vertices(TopoDS::Edge(b), b1, b2);
        if (a1.IsNull() || a2.IsNull() || b1.IsNull() || b2.IsNull()) {
            return false;
        }
        auto closeTo = [](const TopoDS_Vertex& u, const TopoDS_Vertex& v) {
            return BRep_Tool::Pnt(u).Distance(BRep_Tool::Pnt(v)) <= Precision::Confusion();
        };
        return (closeTo(a1, b1) && closeTo(a2, b2)) || (closeTo(a1, b2) && closeTo(a2, b1));
    }

    struct Entry
    {
        const App::DocumentObject* object = nullptr;
        long id = 0;
        long naming = 0;
        std::vector<long> sketches;
    };
    std::vector<Entry> chain;
};
}  // namespace

App::DocumentObjectExecReturn* Fillet::build()
{
    // FreeCAD-CH ops#654 T3: re-run at a pattern's instance, on its base and edges
    Part::TopoShape reapplyBase;
    std::vector<Part::TopoShape> reapplyEdges;
    const bool reapplying = dressUpReapplying(reapplyBase, reapplyEdges);
    // FreeCAD-CH ops#654 P8a: a studio feature over several parts computes no shape of its own;
    // its steps read its parameters, and one whose part failed passes its base through (O2)
    if (!reapplying && runsAsStudioOwner(this)) {
        return studioDressUpOwnerRun(this);
    }
    if (!reapplying && StudioOwner.getValue() && studioDressUpStepPassesThrough(this)) {
        this->positionByBaseFeature();
        Shape.setValue(getBaseTopoShape(/*silent=*/true));
        return App::DocumentObject::StdReturn;
    }
    if (!reapplying && onlyHaveRefined()) {
        return App::DocumentObject::StdReturn;
    }


    Part::TopoShape baseShape;
    try {
        baseShape = reapplying ? reapplyBase : getBaseTopoShape();
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    baseShape.locate(TopLoc_Location());

    auto edges = reapplying            ? reapplyEdges
        : UseAllEdges.getValue() ? baseShape.getSubTopoShapes(TopAbs_EDGE)
                                 : getContinuousEdges(baseShape);
    if (edges.empty()) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Fillet not possible on selected shapes")
        );
    }

    double radius = Radius.getValue();

    if (radius <= 0) {
        return new App::DocumentObjectExecReturn(
            QT_TRANSLATE_NOOP("Exception", "Fillet radius must be greater than zero")
        );
    }

    if (!reapplying) {
        this->positionByBaseFeature();
    }
    try {
        TopoShape shape = makeTopoShape();
        // Add signal handler for segfault protection
#if defined(__GNUC__) && defined(FC_OS_LINUX)
        Base::SignalException se;
#endif

        Part::FilletFallback::Recorder recorder;
        // ops#951: which round names a merged full round's face, from the feature list
        const ChainOrder order(getBaseObject(/*silent=*/true));
        Part::FilletFallback::takeNamingOrder();
        // ops#796: a studio step's owner built it already, on this base and these edges, with
        // these parameters, and checked it: the step goes on from the shape before the refine
        if (Part::TopoShape raw;
            !reapplying && StudioOwner.getValue() && studioDressUpTake(this, baseShape, edges, raw)) {
            this->rawShape = raw;
            shape = refineShapeIfActive(raw);
            if (!isSingleSolidRuleSatisfied(shape.getShape())) {
                return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                    "Exception",
                    "Result has multiple solids: enable 'Allow Compound' in the active body."
                ));
            }
            this->Shape.setValue(getSolid(shape));
            return App::DocumentObject::StdReturn;
        }
        // ops#655: with tangent propagation off, an edge whose tangent chain goes on is cut
        // Onshape's way after the others are filleted
        std::vector<Part::TopoShape> runOut = TangentPropagation.getValue()
            ? std::vector<Part::TopoShape>()
            : takeChainedEdges(baseShape, edges, radius);
        // ops#883: an arc's round runs on along its torus past an unpicked straight neighbour;
        // OCCT rounds the arc with the others, then the neighbour's corner is put back and cut
        const auto arcRunOns = runOut.empty()
            ? std::vector<std::array<TopoDS_Shape, 3>>()
            : takeArcRunOns(baseShape, edges, runOut, radius);
        if (edges.empty()) {
            shape = baseShape;
        }
        else {
            shape.makeElementFillet(baseShape, edges, Radius.getValue(), Radius.getValue());
        }
        if (shape.isNull()) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is null")
            );
        }
        if (!arcRunOns.empty()) {
            shape = applyArcRunOns(shape, baseShape, arcRunOns, makeTopoShape());
        }

        // Limiting every tolerance to Precision::Confusion() used to be the repair: it opened the
        // gaps a fillet closes with larger tolerances, turning valid fillets into invalid solids,
        // and edited sub-shapes shared with the base shape in place (ops#12). The repair works on
        // a copy and keeps the names of the elements it doesn't change (ops#168). A result that is
        // invalid and can't be repaired without changing its solids or its surface fails the
        // feature, as it did up to 0.21, instead of breaking the features after it. The check is
        // the full one: BRepAlgo::IsValid on the new faces passed OCCT's two-solid result of an
        // overlong full round (ops#297).
        // Solids and shells only, as OCCT returns them: a later feature fails on a BaseFeature's
        // loose faces (ops#303)
        if (!Part::checkDressUp(shape, baseShape, Part::LooseParts::drop)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is invalid")
            );
        }
        // OCCT fills a recess its band crosses, in a valid solid (ops#393)
        if (!edges.empty()) {
            ResultCheck::stopIfPastTheLimit("The fillet's check for a filled recess");
        }
        const std::string filled
            = edges.empty() ? std::string() : Part::filledPocket(shape, baseShape, edges, radius);
        if (!filled.empty()) {
            return new App::DocumentObjectExecReturn("The fillet " + filled);
        }
        // OCCT stopping a hair short of a step drops the step's upper part, in a valid solid
        // (ops#603). Not for a round the exact construction rolled on over a tangent edge: it
        // covers its face beyond the band this check allows a direct round, and the construction
        // measured what it cut or fused against the tool's closed form (ops#640, #47 at R1 7, r 4)
        const bool checkLost = !edges.empty() && !recorder.rolledOn();
        if (checkLost) {
            ResultCheck::stopIfPastTheLimit("The fillet's check for lost material");
        }
        const std::string lost
            = checkLost ? Part::lostMaterial(shape, baseShape, edges, radius) : std::string();
        // ops#990 (HNY-DSN #108, #111): where OCCT's valid round overflows a narrow strip onto a
        // dip no ball fits into, it rolls on and bridges the dip, and drops a part of the base;
        // Onshape builds the plain round there. The same selection once more, OCCT's result
        // refused, so the exact construction is asked; its result stands only where it passes
        // the same checks. Only where OCCT built it and nothing else changed the shape; where the
        // construction refuses or throws, the check's error stands
        bool rebuilt = false;
        if (!lost.empty() && !recorder.built() && runOut.empty() && arcRunOns.empty()) {
            ResultCheck::stopIfPastTheLimit("The fillet's exact construction after its check");
            TopoShape again = makeTopoShape();
            try {
                Part::FilletFallback::RefusedResultScope refusedScope;
                again.makeElementFillet(baseShape, edges, radius, radius);
            }
            catch (const Base::Exception&) {
                again = TopoShape();
            }
            catch (const Standard_Failure&) {
                again = TopoShape();
            }
            rebuilt = recorder.built() && !again.isNull()
                && Part::checkDressUp(again, baseShape, Part::LooseParts::drop)
                && Part::filledPocket(again, baseShape, edges, radius).empty()
                && (recorder.rolledOn()
                    || Part::lostMaterial(again, baseShape, edges, radius).empty());
            if (rebuilt) {
                shape = again;
            }
        }
        if (!lost.empty() && !rebuilt) {
            return new App::DocumentObjectExecReturn("The fillet " + lost);
        }
        // OCCT bridges a hole or pocket the band crosses with a B-spline (ops#604 gap 3a)
        if (!edges.empty()) {
            ResultCheck::stopIfPastTheLimit("The fillet's check for a bridged recess");
        }
        const std::string bridged
            = edges.empty() ? std::string() : Part::bridgedRecess(shape, baseShape, edges, radius);
        if (!bridged.empty()) {
            // Onshape's round there is the plain round cut by the openings: the exact
            // construction, below the limit, where it builds a result without a bridge (ops#993).
            // Not with an arc's run-on (ops#883), which the construction doesn't build
            TopoShape exact = shape;
            if (!arcRunOns.empty()
                || !Part::FilletFallback::buildAcrossRecess(
                    exact,
                    baseShape,
                    edges,
                    radius,
                    Part::OpCodes::Fillet
                )
                || !Part::checkDressUp(exact, baseShape, Part::LooseParts::drop)
                || !Part::filledPocket(exact, baseShape, edges, radius).empty()
                || (!recorder.rolledOn()
                    && !Part::lostMaterial(exact, baseShape, edges, radius).empty())
                || !Part::bridgedRecess(exact, baseShape, edges, radius).empty()) {
                return new App::DocumentObjectExecReturn("The fillet" + bridged);
            }
            shape = exact;
        }
        // ops#655: each chained edge's fillet runs straight on until it leaves the body (GB13)
        for (const auto& edge : runOut) {
            const TopoDS_Shape tool = runOutCut(
                shape.getShape(),
                baseShape.getShape(),
                TopoDS::Edge(edge.getShape()),
                radius,
                true
            );
            if (tool.IsNull()) {
                continue;
            }
            TopoShape cut = makeTopoShape();
            cut.makeElementCut({shape, makeTopoShape(tool)});
            shape = cut;
        }
        if (!runOut.empty() && !Part::checkDressUp(shape, baseShape, Part::LooseParts::drop)) {
            return new App::DocumentObjectExecReturn(
                QT_TRANSLATE_NOOP("Exception", "Resulting shape is invalid")
            );
        }
        // store shape before refinement
        if (reapplying) {
            // ops#951: the pattern instance's undecided merged face is said on the pattern's fillet;
            // a studio owner's try's, by the owner: the step's own compute clears its warning and
            // takes the kept shape without a finish() (review pr503-r1 T2)
            auto owner = freecad_cast<Fillet*>(const_cast<DressUp*>(dressUpTriedFor(this)));
            if (const std::string note = Part::FilletFallback::takeNamingOrder(); !note.empty()) {
                if (owner) {
                    dressUpReappliedNote(note);
                }
                else if (auto doc = getDocument()) {
                    // Once, whatever the number of instances and the pattern's recomputes (review
                    // pr503-r2 L2)
                    const std::string previous = doc->getWarningDescription(this)
                        ? doc->getWarningDescription(this)
                        : "";
                    if (previous.find(note) == std::string::npos) {
                        doc->setWarning(this, previous.empty() ? note : previous + "\n" + note);
                    }
                }
            }
            dressUpReappliedFrom(
                shape,
                owner ? owner->refineShapeIfActive(shape) : refineShapeIfActive(shape),
                !recorder.built()
            );
            return App::DocumentObject::StdReturn;
        }
        this->rawShape = shape;
        shape = refineShapeIfActive(shape);
        if (!isSingleSolidRuleSatisfied(shape.getShape())) {
            return new App::DocumentObjectExecReturn(QT_TRANSLATE_NOOP(
                "Exception",
                "Result has multiple solids: enable 'Allow Compound' in the active body."
            ));
        }

        shape = getSolid(shape);
        // Where OCCT failed, the exact construction built it (ops#300, decision 54), once
        // the feature has its result
        recorder.report(Label.getValue());
        this->Shape.setValue(shape);
        // ops#951: a merged face whose edges' history does not say which round names it
        if (const std::string note = Part::FilletFallback::takeNamingOrder(); !note.empty()) {
            if (auto doc = getDocument()) {
                const char* previous = doc->getWarningDescription(this);
                doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + note : note);
            }
        }
        return App::DocumentObject::StdReturn;
    }
    // ops#640 F2: Onshape's "Failed to fillet selections" with the exact construction's reason,
    // never OCCT's raw text (row 104's "TopOpeBRepDS_DataStructure::Point")
    catch (Base::Exception& e) {
        const std::string what = e.what();
        return new App::DocumentObjectExecReturn(
            isDressUpFailure(what) ? dressUpFailure("fillet", what) : what
        );
    }
    catch (Standard_Failure& e) {
        const char* what = e.GetMessageString();
        return new App::DocumentObjectExecReturn(dressUpFailure("fillet", what ? what : ""));
    }
    catch (...) {
        return new App::DocumentObjectExecReturn(dressUpFailure("fillet", ""));
    }
}

void Fillet::Restore(Base::XMLReader& reader)
{
    DressUp::Restore(reader);
}

void Fillet::handleChangedPropertyType(Base::XMLReader& reader, const char* TypeName, App::Property* prop)
{
    if (prop && strcmp(TypeName, "App::PropertyFloatConstraint") == 0
        && prop->getTypeId().getName() == "App::PropertyQuantityConstraint") {
        App::PropertyFloatConstraint p;
        p.Restore(reader);
        static_cast<App::PropertyQuantityConstraint*>(prop)->setValue(p.getValue());
    }
    else {
        DressUp::handleChangedPropertyType(reader, TypeName, prop);
    }
}
