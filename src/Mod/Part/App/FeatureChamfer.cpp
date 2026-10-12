// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2010 Werner Mayer <wmayer[at]users.sourceforge.net>     *
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
#include <utility>
#include <vector>

#include <BRepFilletAPI_MakeChamfer.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>


#include <SignalException.h>
#include "FeatureChamfer.h"
#include "FilletFallback.h"
#include "TopoShapeOpCode.h"
#include "TopoShapeRepair.h"


using namespace Part;

PROPERTY_SOURCE(Part::Chamfer, Part::FilletBase)

Chamfer::Chamfer() = default;

App::DocumentObjectExecReturn* Chamfer::execute()
{
    App::DocumentObject* link = Base.getValue();
    if (!link) {
        return new App::DocumentObjectExecReturn("No object linked");
    }

    try {
        TopoShape baseTopoShape
            = Feature::getTopoShape(link, ShapeOption::ResolveLink | ShapeOption::Transform);
        const auto& baseShape = baseTopoShape.getShape();
        TopTools_IndexedDataMapOfShapeListOfShape mapEdgeFace;
        TopExp::MapShapesAndAncestors(baseShape, TopAbs_EDGE, TopAbs_FACE, mapEdgeFace);
        TopTools_IndexedMapOfShape mapOfEdges;
        std::vector<Part::FilletElement> edges = Edges.getValues();
        TopExp::MapShapes(baseShape, TopAbs_EDGE, mapOfEdges);
        std::string fullErrMsg;
        std::vector<TopoShape> edgeShapes;
        std::vector<std::pair<double, double>> sizes;

        const auto& vals = EdgeLinks.getSubValues();
        const auto& subs = EdgeLinks.getShadowSubs();
        if (subs.size() != (size_t)Edges.getSize()) {
            return new App::DocumentObjectExecReturn("Edge link size mismatch");
        }
        size_t i = 0;
        for (const auto& info : edges) {
            auto& sub = subs[i];
            auto& ref = sub.newName.empty() ? vals[i] : sub.newName;
            auto& oldName = sub.oldName.empty() ? "" : sub.oldName;
            ++i;

            if (Data::hasMissingElement(ref.c_str()) || Data::hasMissingElement(oldName.c_str())) {
                fullErrMsg.append("Missing edge link: ");
                fullErrMsg.append(ref);
                fullErrMsg.append("\n");
                // Report it and go on with the next edge; nothing is erased from `edges`, which
                // this loop iterates (ops#74), since a missing link returns the error unstored.
                continue;
            }
            // Toponaming project March 2024:  Replaced this code because it wouldn't work:
            //            TopoDS_Shape edge;
            //            try {
            //                edge = baseTopoShape.getSubShape(ref.c_str());
            //            }catch(...){}
            auto id = Data::MappedName(ref.c_str()).toIndexedName().getIndex();
            const TopoDS_Edge& edge = TopoDS::Edge(mapOfEdges.FindKey(id));
            if (edge.IsNull()) {
                return new App::DocumentObjectExecReturn("Invalid edge link");
            }
            edgeShapes.emplace_back(edge);
            sizes.emplace_back(info.radius1, info.radius2);
        }

        if (!fullErrMsg.empty()) {
            return new App::DocumentObjectExecReturn(fullErrMsg);
        }
        // Edges isn't written back: it holds what was read, and a write would make EdgeLinks
        // anew, without their records (ops#258).

        const bool sameSizes = std::all_of(sizes.begin(), sizes.end(), [&](const auto& s) {
            return s == sizes.front();
        });
        Part::FilletFallback::Recorder recorder;
        TopoShape res = makeTopoShape();
        if (sameSizes && !edgeShapes.empty()) {
            // The same maker as below (the reference face is the edge's first ancestor), and the
            // exact construction where OCCT fails or builds an invalid result (ops#300, ops#297)
            res.makeElementChamfer(
                baseTopoShape,
                edgeShapes,
                ChamferType::twoDistances,
                sizes.front().first,
                sizes.front().second,
                Part::OpCodes::Chamfer,
                Flip::none
            );
        }
        else {
            BRepFilletAPI_MakeChamfer mkChamfer(baseShape);
            for (size_t k = 0; k < edgeShapes.size(); ++k) {
                const auto& edge = TopoDS::Edge(edgeShapes[k].getShape());
                const TopoDS_Face& face = TopoDS::Face(mapEdgeFace.FindFromKey(edge).First());
                mkChamfer.Add(sizes[k].first, sizes[k].second, edge, face);
            }
            Part::SignalException sig;
            if (mkChamfer.Shape().IsNull()) {
                return new App::DocumentObjectExecReturn("Resulting shape is null");
            }
            res.makeElementShape(mkChamfer, baseTopoShape, Part::OpCodes::Chamfer);
            // makeElementChamfer sends a face of zero width to the exact construction; OCCT's
            // own maker leaves it (ops#298)
            if (!FilletFallback::thinFace(res.getShape(), baseShape).IsNull()) {
                return new App::DocumentObjectExecReturn(
                    "The chamfer would leave a face of zero width (a face it consumes whole, or a "
                    "sliver narrower than its tolerance)"
                );
            }
        }
        if (res.isNull()) {
            return new App::DocumentObjectExecReturn("Resulting shape is null");
        }
        // OCCT sometimes builds an invalid chamfer without an error (ops#297)
        if (!Part::checkDressUp(res, baseTopoShape)) {
            return new App::DocumentObjectExecReturn("Resulting shape is invalid");
        }
        // Where OCCT failed, the exact construction built it (ops#300, decision 54)
        recorder.report(Label.getValue());
        this->Shape.setValue(res);
        return Part::FilletBase::execute();
    }
    catch (Base::Exception& e) {
        return new App::DocumentObjectExecReturn(e.what());
    }
    catch (Standard_Failure& e) {
        return new App::DocumentObjectExecReturn(e.GetMessageString());
    }
    catch (...) {
        return new App::DocumentObjectExecReturn(
            "Chamfer failed: OCC kernel error in chamfer computation"
        );
    }
}
