// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2024 Eric Price (CorvusCorax)                           *
 *                      <eric.price[at]tuebingen.mpg.de>                   *
 *                                                                         *
 *   This file is part of FreeCAD.                                         *
 *                                                                         *
 *   FreeCAD is free software: you can redistribute it and/or modify it    *
 *   under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1 of the  *
 *   License, or (at your option) any later version.                       *
 *                                                                         *
 *   FreeCAD is distributed in the hope that it will be useful, but        *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
 *   Lesser General Public License for more details.                       *
 *                                                                         *
 *   You should have received a copy of the GNU Lesser General Public      *
 *   License along with FreeCAD. If not, see                               *
 *   <https://www.gnu.org/licenses/>.                                      *
 *                                                                         *
 **************************************************************************/

/**
 * FCBRepAlgoAPI provides a wrapper for various OCCT functions.
 */

#include <FCBRepAlgoAPI_BooleanOperation.h>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepBndLib.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <Bnd_Box.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Iterator.hxx>
#include <Precision.hxx>
#include <FuzzyHelper.h>
#include <MassProperties.h>
#include <SignalException.h>
#include <Base/Console.h>
#include <Base/Exception.h>

#include <cmath>
#include <vector>

FCBRepAlgoAPI_BooleanOperation::FCBRepAlgoAPI_BooleanOperation()
{
    SetRunParallel(Standard_True);
    SetNonDestructive(Standard_True);
}


FCBRepAlgoAPI_BooleanOperation::FCBRepAlgoAPI_BooleanOperation(
    const TopoDS_Shape& theS1,
    const TopoDS_Shape& theS2,
    const BOPAlgo_Operation theOperation
)
    : BRepAlgoAPI_BooleanOperation(theS1, theS2, theOperation)
{
    if (!BRepCheck_Analyzer(theS1).IsValid()) {
        Base::Console().warning("Base shape is not valid for boolean operation");
    }

    if (!BRepCheck_Analyzer(theS2).IsValid()) {
        Base::Console().warning("Tool shape is not valid for boolean operation");
    }

    setAutoFuzzy();
    SetRunParallel(Standard_True);
    SetNonDestructive(Standard_True);
}

void FCBRepAlgoAPI_BooleanOperation::setAutoFuzzy()
{
    FCBRepAlgoAPIHelper::setAutoFuzzy(this);
}


void FCBRepAlgoAPIHelper::setAutoFuzzy(BRepAlgoAPI_BooleanOperation* op)
{
    Bnd_Box bounds;
    for (TopTools_ListOfShape::Iterator it(op->Arguments()); it.More(); it.Next()) {
        BRepBndLib::Add(it.Value(), bounds);
    }
    for (TopTools_ListOfShape::Iterator it(op->Tools()); it.More(); it.Next()) {
        BRepBndLib::Add(it.Value(), bounds);
    }
    op->SetFuzzyValue(
        Part::FuzzyHelper::getBooleanFuzzy() * sqrt(bounds.SquareExtent()) * Precision::Confusion()
    );
}

void FCBRepAlgoAPIHelper::setAutoFuzzy(BRepAlgoAPI_BuilderAlgo* op)
{
    Bnd_Box bounds;
    for (TopTools_ListOfShape::Iterator it(op->Arguments()); it.More(); it.Next()) {
        BRepBndLib::Add(it.Value(), bounds);
    }
    op->SetFuzzyValue(
        Part::FuzzyHelper::getBooleanFuzzy() * sqrt(bounds.SquareExtent()) * Precision::Confusion()
    );
}

namespace
{
/// The solids of the shapes in \a list, also inside compounds and compsolids
std::vector<TopoDS_Shape> solidsOf(const TopTools_ListOfShape& list)
{
    std::vector<TopoDS_Shape> solids;
    for (TopTools_ListOfShape::Iterator it(list); it.More(); it.Next()) {
        for (TopExp_Explorer xp(it.Value(), TopAbs_SOLID); xp.More(); xp.Next()) {
            solids.push_back(xp.Current());
        }
    }
    return solids;
}

/// Whether the boolean left no trace of \a tool: every face deleted, as a cut that removed nothing
/// leaves them (a void's faces stay, reversed), or every face kept unchanged, as a fuse that
/// merged nothing leaves them
bool leftNoTrace(BRepAlgoAPI_BooleanOperation* op, const TopoDS_Shape& tool, bool deleted)
{
    TopExp_Explorer xp(tool, TopAbs_FACE);
    if (!xp.More()) {
        return false;
    }
    for (; xp.More(); xp.Next()) {
        if (!op->Modified(xp.Current()).IsEmpty() || op->IsDeleted(xp.Current()) != deleted) {
            return false;
        }
    }
    return true;
}

/// Whether \a tool, which left no trace, overlaps the material of \a solid, by two independent
/// witnesses: a vertex of the tool classifies IN the solid, and the screened volume of their
/// common part is more than a millionth of the tool's (OCCT's Common is right where the solid
/// builder fails, ops#472). One vertex decides, as such a tool lies wholly in the material or
/// wholly outside it, and each classification costs about 0.1 s on a 1000-span face
bool overlaps(const TopoDS_Shape& solid, const TopoDS_Shape& tool, double fuzzy)
{
    Bnd_Box solidBounds, toolBounds;
    BRepBndLib::Add(solid, solidBounds);
    BRepBndLib::Add(tool, toolBounds);
    TopExp_Explorer vertex(tool, TopAbs_VERTEX);
    if (solidBounds.IsOut(toolBounds) || !vertex.More()) {
        return false;
    }
    BRepClass3d_SolidClassifier classifier(
        solid,
        BRep_Tool::Pnt(TopoDS::Vertex(vertex.Current())),
        Precision::Confusion()
    );
    if (classifier.State() != TopAbs_IN) {
        return false;
    }
    BRepAlgoAPI_Common common;
    TopTools_ListOfShape arguments, tools;
    arguments.Append(solid);
    tools.Append(tool);
    common.SetArguments(arguments);
    common.SetTools(tools);
    common.SetFuzzyValue(fuzzy);
    common.Build();
    if (!common.IsDone()) {
        return false;
    }
    return Part::MassProperties::volume(common.Shape())
        > 1e-6 * std::abs(Part::MassProperties::volume(tool));
}
}  // namespace

void FCBRepAlgoAPIHelper::checkLostTools(BRepAlgoAPI_BooleanOperation* op)
{
    const bool cut = op->Operation() == BOPAlgo_CUT;
    if ((!cut && op->Operation() != BOPAlgo_FUSE) || !op->IsDone() || !op->HasHistory()) {
        return;
    }
    // FCBRepAlgoAPI_BooleanOperation::Build cuts a compound argument or tool piece by piece, and
    // the history then covers only the last piece: those cuts aren't checked yet (ops#472)
    if (cut) {
        for (const auto* list : {&op->Arguments(), &op->Tools()}) {
            for (TopTools_ListOfShape::Iterator it(*list); it.More(); it.Next()) {
                if (it.Value().ShapeType() == TopAbs_COMPOUND) {
                    return;
                }
            }
        }
    }
    const std::vector<TopoDS_Shape> bases = solidsOf(op->Arguments());
    const std::vector<TopoDS_Shape> tools = solidsOf(op->Tools());
    if (bases.empty() || tools.empty()) {
        return;
    }
    std::vector<TopoDS_Shape> results;
    for (TopExp_Explorer xp(op->Shape(), TopAbs_SOLID); xp.More(); xp.Next()) {
        results.push_back(xp.Current());
    }
    // A fuse that kept a tool whole has more solids than its base, else it merged nothing
    if (!cut && results.size() <= bases.size()) {
        return;
    }
    for (const auto& tool : tools) {
        if (!leftNoTrace(op, tool, cut)) {
            continue;
        }
        // A cut that removed nothing lost the tool if the result still has material where the
        // tool is (a tool outside the base, or inside another tool, has none). A fuse that merged
        // nothing lost it if the tool lies in the material of the base or of another tool
        std::vector<TopoDS_Shape> others = cut ? results : bases;
        if (!cut) {
            for (const auto& other : tools) {
                if (!other.IsSame(tool)) {
                    others.push_back(other);
                }
            }
        }
        for (const auto& other : others) {
            if (overlaps(other, tool, op->FuzzyValue())) {
                throw Base::CADKernelError(
                    cut ? "Cut failed: a tool solid lies inside the base, but the result lost its "
                          "cavity (OCCT solid builder fault, ops#472)"
                        : "Fuse failed: a tool solid lies inside the base, but the result kept it "
                          "as a separate overlapping solid (OCCT solid builder fault, ops#472)"
                );
            }
        }
    }
}

void FCBRepAlgoAPI_BooleanOperation::Build()
{
    Message_ProgressRange progressRange;
    Build(progressRange);
}

void FCBRepAlgoAPI_BooleanOperation::Build(const Message_ProgressRange& progressRange)
{
    Part::SignalException sig;
    if (progressRange.UserBreak()) {
        throw Standard_ConstructionError("User aborted");
    }
    if (myOperation == BOPAlgo_CUT && myArguments.Size() == 1 && myTools.Size() == 1
        && myTools.First().ShapeType() == TopAbs_COMPOUND) {
        // cut argument and compound tool
        TopTools_ListOfShape myOriginalArguments = myArguments;
        TopTools_ListOfShape myOriginalTools = myTools;
        RecursiveCutFusedTools(myOriginalArguments, myOriginalTools.First());
        myArguments = myOriginalArguments;
        myTools = myOriginalTools;
    }
    else if (
        myOperation == BOPAlgo_CUT && myArguments.Size() == 1
        && myArguments.First().ShapeType() == TopAbs_COMPOUND
    ) {
        // cut compound argument
        TopTools_ListOfShape myOriginalArguments = myArguments;
        RecursiveCutCompound(myOriginalArguments.First());
        myArguments = myOriginalArguments;
    }
    else {
#if OCC_VERSION_HEX >= 0x070600
        BRepAlgoAPI_BooleanOperation::Build(progressRange);
#else
        BRepAlgoAPI_BooleanOperation::Build();
#endif
    }
    if (progressRange.UserBreak()) {
        throw Standard_ConstructionError("User aborted");
    }
}

void FCBRepAlgoAPI_BooleanOperation::RecursiveAddTools(const TopoDS_Shape& theTool)
{
    TopoDS_Iterator it(theTool);
    for (; it.More(); it.Next()) {
        if (it.Value().ShapeType() == TopAbs_COMPOUND) {
            RecursiveAddTools(it.Value());
        }
        else {
            myTools.Append(it.Value());
        }
    }
}

void FCBRepAlgoAPI_BooleanOperation::RecursiveCutFusedTools(
    const TopTools_ListOfShape& theOriginalArguments,
    const TopoDS_Shape& theTool
)
{
    // get a list of shapes in the tool compound
    myTools.Clear();
    RecursiveAddTools(theTool);

    // if tool consists of two or more shapes, fuse them together
    if (myTools.Size() >= 2) {
        myArguments.Clear();
        myArguments.Append(myTools.First());
        myTools.RemoveFirst();
        myOperation = BOPAlgo_FUSE;
        Build();

        // restore original state
        myOperation = BOPAlgo_CUT;
        myArguments = theOriginalArguments;

        if (!IsDone()) {
            myShape = {};
            return;
        }

        // use fused shape as new tool
        // if the original tools didn't all touch, the fused shape will be a compound
        // which we convert into a list of shapes so we don't attempt to fuse them again
        myTools.Clear();
        RecursiveAddTools(myShape);
    }

    // do the cut
    Build();
}

void FCBRepAlgoAPI_BooleanOperation::RecursiveCutCompound(const TopoDS_Shape& theArgument)
{
    BRep_Builder builder;
    TopoDS_Compound comp;
    builder.MakeCompound(comp);

    // iterate through shapes in argument compound and cut each one with the tool
    TopoDS_Iterator it(theArgument);
    for (; it.More(); it.Next()) {
        myArguments.Clear();
        myArguments.Append(it.Value());
        Build();

        if (!IsDone()) {
            myShape = {};
            return;
        }

        builder.Add(comp, myShape);
    }

    // result is a compound of individual cuts
    myShape = comp;
}
