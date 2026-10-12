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

#include <FCConfig.h>

#include <algorithm>
#include <utility>
#include <vector>

#include <BRepFilletAPI_MakeFillet.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopTools_IndexedMapOfShape.hxx>


#include <Base/Exception.h>

#include "FeatureFillet.h"
#include "TopoShapeOpCode.h"
#include "TopoShapeRepair.h"


using namespace Part;

PROPERTY_SOURCE(Part::Fillet, Part::FilletBase)

Fillet::Fillet() = default;

App::DocumentObjectExecReturn* Fillet::execute()
{
    App::DocumentObject* link = Base.getValue();
    if (!link) {
        return new App::DocumentObjectExecReturn("No object linked");
    }


    try {
#if defined(__GNUC__) && defined(FC_OS_LINUX)
        Base::SignalException se;
#endif
        TopoShape baseTopoShape
            = Feature::getTopoShape(link, ShapeOption::ResolveLink | ShapeOption::Transform);
        auto baseShape = baseTopoShape.getShape();
        TopTools_IndexedMapOfShape mapOfShape;
        TopExp::MapShapes(baseShape, TopAbs_EDGE, mapOfShape);
        TopTools_IndexedMapOfShape mapOfEdges;
        TopExp::MapShapes(baseShape, TopAbs_EDGE, mapOfEdges);
        std::vector<Part::FilletElement> edges = Edges.getValues();
        std::string fullErrMsg;
        std::vector<TopoShape> edgeShapes;
        std::vector<std::pair<double, double>> radii;

        const auto& vals = EdgeLinks.getSubValues(true);
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
            radii.emplace_back(info.radius1, info.radius2);
        }
        const bool sameRadii = std::all_of(radii.begin(), radii.end(), [&](const auto& r) {
            return r == radii.front();
        });

        if (!fullErrMsg.empty()) {
            return new App::DocumentObjectExecReturn(fullErrMsg);
        }
        // Edges isn't written back: it holds what was read, and a write would make EdgeLinks
        // anew, without their records (ops#258).

        TopoShape res = makeTopoShape(false);
        if (sameRadii && !edgeShapes.empty()) {
            // The same maker as below, and the exact construction where OCCT fails or builds an
            // invalid result (ops#300, ops#297)
            res.makeElementFillet(
                baseTopoShape,
                edgeShapes,
                radii.front().first,
                radii.front().second,
                Part::OpCodes::Fillet
            );
        }
        else {
            BRepFilletAPI_MakeFillet mkFillet(baseShape);
            for (size_t k = 0; k < edgeShapes.size(); ++k) {
                const auto& edge = TopoDS::Edge(edgeShapes[k].getShape());
                mkFillet.Add(radii[k].first, radii[k].second, edge);
            }
            if (mkFillet.Shape().IsNull()) {
                return new App::DocumentObjectExecReturn("Resulting shape is null");
            }
            res.makeElementShape(mkFillet, baseTopoShape, Part::OpCodes::Fillet);
        }
        if (res.isNull()) {
            return new App::DocumentObjectExecReturn("Resulting shape is null");
        }
        // OCCT sometimes builds an invalid fillet without an error (ops#297)
        if (!Part::checkDressUp(res, baseTopoShape)) {
            return new App::DocumentObjectExecReturn("Resulting shape is invalid");
        }
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
        return new App::DocumentObjectExecReturn("A fatal error occurred when making fillets");
    }
}
