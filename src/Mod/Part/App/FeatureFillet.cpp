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
#include <limits>
#include <utility>
#include <vector>

#include <BRepFilletAPI_MakeFillet.hxx>
#include <Precision.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopTools_IndexedMapOfShape.hxx>


#include <App/Document.h>
#include <Base/Exception.h>

#include "FeatureFillet.h"
#include "FilletFallback.h"
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

        Part::FilletFallback::Recorder recorder;
        Part::FilletFallback::takeNamingOrder();
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
            // OCCT's maker raises its input's tolerances in place: it runs on a copy (ops#345)
            std::vector<TopoShape> inputEdges = edgeShapes;
            const TopoShape input = FilletFallback::makerInput(baseTopoShape, inputEdges);
            BRepFilletAPI_MakeFillet mkFillet(input.getShape());
            for (size_t k = 0; k < inputEdges.size(); ++k) {
                const auto& edge = TopoDS::Edge(inputEdges[k].getShape());
                mkFillet.Add(radii[k].first, radii[k].second, edge);
            }
            // OCCT carries a contour on over a slight corner and leaves a tooth there, in a valid
            // solid (ops#762); the exact construction takes one radius only
            std::vector<std::vector<TopoDS_Shape>> contours;
            for (int i = 1; i <= mkFillet.NbContours(); ++i) {
                contours.emplace_back();
                for (int j = 1; j <= mkFillet.NbEdges(i); ++j) {
                    contours.back().push_back(mkFillet.Edge(i, j));
                }
            }
            std::string kinkAt;
            if (FilletFallback::kinkedContour(contours, &kinkAt)) {
                return new App::DocumentObjectExecReturn(
                    "The fillet runs over a slight corner between its edges (" + kinkAt
                    + "), where OCCT's round leaves a tooth; with one radius on every edge it is "
                      "built exactly"
                );
            }
            if (mkFillet.Shape().IsNull()) {
                return new App::DocumentObjectExecReturn("Resulting shape is null");
            }
            res.makeElementShape(mkFillet, input, Part::OpCodes::Fillet);
            // makeElementFillet sends a face of zero width to the exact construction; OCCT's
            // own maker leaves it (ops#298)
            if (!FilletFallback::thinFace(res.getShape(), input.getShape()).IsNull()) {
                return new App::DocumentObjectExecReturn(
                    "The fillet would leave a face of zero width (a face it consumes whole, or a "
                    "sliver narrower than its tolerance)"
                );
            }
        }
        if (res.isNull()) {
            return new App::DocumentObjectExecReturn("Resulting shape is null");
        }
        // OCCT sometimes builds an invalid fillet without an error (ops#297)
        if (!Part::checkDressUp(res, baseTopoShape)) {
            return new App::DocumentObjectExecReturn("Resulting shape is invalid");
        }
        double largest = 0.0;
        double smallest = std::numeric_limits<double>::max();
        for (const auto& [radius1, radius2] : radii) {
            largest = std::max({largest, radius1, radius2});
            smallest = std::min({smallest, radius1, radius2});
        }
        // OCCT fills a recess its band crosses, in a valid solid (ops#393)
        const std::string filled = Part::filledPocket(res, baseTopoShape, edgeShapes, largest);
        if (!filled.empty()) {
            return new App::DocumentObjectExecReturn("The fillet " + filled);
        }
        // OCCT stopping a hair short of a step drops the step's upper part, in a valid solid
        // (ops#603)
        // Not for a round the exact construction rolled on over a tangent edge: it covers its face
        // beyond the band this check allows a direct round, and the construction measured what it
        // cut or fused against the tool's closed form (ops#640, #47 at R1 7, r 4)
        const std::string lost = recorder.rolledOn()
            ? std::string()
            : Part::lostMaterial(res, baseTopoShape, edgeShapes, largest);
        if (!lost.empty()) {
            return new App::DocumentObjectExecReturn("The fillet " + lost);
        }
        // OCCT bridges a hole or pocket the band crosses with a B-spline (ops#604 gap 3a)
        const bool constantRadius = std::all_of(radii.begin(), radii.end(), [](const auto& r) {
            return r.first == r.second;
        });
        // An arc is excused as too small for its round only below the smallest radius, so an arc
        // above its own edge's radius is never excused by a larger one elsewhere (review
        // pr968pre-r1, MixedRadiusBridge), and the round over it is bounded by its own edge's
        // radius (review pr516-r4, T1)
        std::vector<double> edgeRadii;
        for (const auto& r : radii) {
            edgeRadii.push_back(r.first);
        }
        const std::string bridged = Part::bridgedRecess(
            res,
            baseTopoShape,
            edgeShapes,
            constantRadius ? largest : 0.0,
            constantRadius ? smallest : -1.0,
            edgeRadii
        );
        if (!bridged.empty()) {
            // Onshape's round there is the plain round cut by the openings: the exact
            // construction, below the limit, where it builds a result without a bridge (ops#993)
            TopoShape exact = res;
            std::string why;
            if (!sameRadii || radii.front().first != radii.front().second
                || !Part::FilletFallback::buildAcrossRecess(
                    exact,
                    baseTopoShape,
                    edgeShapes,
                    radii.front().first,
                    Part::OpCodes::Fillet,
                    &why
                )
                || !Part::checkDressUp(exact, baseTopoShape)
                || !Part::filledPocket(exact, baseTopoShape, edgeShapes, largest).empty()
                || (!recorder.rolledOn()
                    && !Part::lostMaterial(exact, baseTopoShape, edgeShapes, largest).empty())
                || !Part::bridgedRecess(exact, baseTopoShape, edgeShapes, largest, smallest, edgeRadii)
                        .empty()) {
                return new App::DocumentObjectExecReturn("The fillet" + bridged);
            }
            res = exact;
        }
        // Where OCCT failed, the exact construction built it (ops#300, decision 54)
        recorder.report(Label.getValue());
        this->Shape.setValue(res);
        // ops#951: a merged face whose edges' history does not say which round names it
        if (const std::string note = Part::FilletFallback::takeNamingOrder(); !note.empty()) {
            if (auto doc = getDocument()) {
                const char* previous = doc->getWarningDescription(this);
                doc->setWarning(this, previous && *previous ? std::string(previous) + "\n" + note : note);
            }
        }
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
