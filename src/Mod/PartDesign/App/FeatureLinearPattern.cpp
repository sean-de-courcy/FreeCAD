// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2012 Jan Rheinländer <jrheinlaender@users.sourceforge.net> *
 *                                                                            *
 *   This file is part of the FreeCAD CAx development system.                 *
 *                                                                            *
 *   This library is free software; you can redistribute it and/or            *
 *   modify it under the terms of the GNU Library General Public              *
 *   License as published by the Free Software Foundation; either             *
 *   version 2 of the License, or (at your option) any later version.         *
 *                                                                            *
 *   This library  is distributed in the hope that it will be useful,         *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty of           *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            *
 *   GNU Library General Public License for more details.                     *
 *                                                                            *
 *   You should have received a copy of the GNU Library General Public        *
 *   License along with this library; see the file COPYING.LIB. If not,       *
 *   write to the Free Software Foundation, Inc., 59 Temple Place,            *
 *   Suite 330, Boston, MA  02111-1307, USA                                   *
 *                                                                            *
 ******************************************************************************/

#include <algorithm>
#include <cstdlib>
#include <limits>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <gp_Dir.hxx>
#include <gp_Pln.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#include <Precision.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>

#include <App/Datums.h>
#include <Base/Axis.h>
#include <Mod/Part/App/Tools.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/Part2DObject.h>

#include "FeatureLinearPattern.h"
#include "DatumLine.h"
#include "DatumPlane.h"


using namespace PartDesign;

namespace PartDesign
{

PROPERTY_SOURCE_WITH_EXTENSIONS(PartDesign::LinearPattern, PartDesign::Transformed)

namespace
{
/// The instances along one direction: count, or 2 count - 1 when centered (Onshape's count is per
/// side, the seed included; oracle 9j)
int instancesAlong(long count, bool centered)
{
    const int n = std::max(static_cast<int>(count), 1);
    return centered ? 2 * n - 1 : n;
}
}  // namespace

LinearPattern::LinearPattern()
{
    Part::LinearPatternExtension::initExtension(this);

    ADD_PROPERTY_TYPE(
        Centered,
        (false),
        "Direction 1",
        App::Prop_None,
        "The instances run both ways from the original, which is the middle one"
    );
    ADD_PROPERTY_TYPE(
        Centered2,
        (false),
        "Direction 2",
        App::Prop_None,
        "The instances run both ways from the original in the second direction"
    );
    ADD_PROPERTY_TYPE(
        SkippedInstances,
        (),
        "Skip",
        App::Prop_None,
        "Instances not made: (i, j) index pairs, flattened, counted from 0 at the negative end of "
        "each direction"
    );
}

gp_Dir LinearPattern::getDirectionFromProperty(const App::PropertyLinkSub& dirProp) const
{
    App::DocumentObject* refObject = dirProp.getValue();
    if (!refObject) {
        throw Base::ValueError("No direction reference specified");
    }

    if (auto* plane = freecad_cast<PartDesign::Plane*>(refObject)) {
        Base::Vector3d d = plane->getNormal();
        gp_Dir dir(d.x, d.y, d.z);

        TopLoc_Location invObjLoc = this->getLocation().Inverted();
        dir.Transform(invObjLoc.Transformation());
        return Base::convertTo<gp_Vec>(dir);
    }
    else if (auto* line = freecad_cast<PartDesign::Line*>(refObject)) {
        Base::Vector3d d = line->getDirection();
        gp_Dir dir(d.x, d.y, d.z);

        TopLoc_Location invObjLoc = this->getLocation().Inverted();
        dir.Transform(invObjLoc.Transformation());
        return Base::convertTo<gp_Vec>(dir);
    }

    // FreeCAD-CH (ops#640 rank 27, E-2): a cylindrical face steps along its axis, as Onshape's
    // Direction field takes it; the extension takes straight edges and planar faces
    if (auto* feature = freecad_cast<Part::Feature*>(refObject)) {
        const auto& subs = dirProp.getSubValues();
        if (!subs.empty() && subs[0].compare(0, 4, "Face") == 0) {
            TopoDS_Shape ref = feature->Shape.getShape().getSubShape(subs[0].c_str(), /*silent=*/true);
            if (!ref.IsNull() && ref.ShapeType() == TopAbs_FACE) {
                BRepAdaptor_Surface adapt(TopoDS::Face(ref));
                if (adapt.GetType() == GeomAbs_Cylinder) {
                    gp_Dir dir = adapt.Cylinder().Axis().Direction();
                    dir.Transform(this->getLocation().Inverted().Transformation());
                    return dir;
                }
            }
        }
    }

    return Part::LinearPatternExtension::getDirectionFromProperty(dirProp);
}

const std::list<gp_Trsf> LinearPattern::getTransformations(const std::vector<App::DocumentObject*>)
{
    const int first = std::max(static_cast<int>(Occurrences.getValue()), 1);
    const int second = std::max(static_cast<int>(Occurrences2.getValue()), 1);
    // FreeCAD-CH (ops#655): a direction in use needs its reference, as Onshape's "Select a pattern
    // direction." (oracle 9j, Q-D3). Without one its step is 0 and every copy falls on the seed,
    // silently; count 1 is Onshape's unticked second direction and needs none
    if ((first > 1 && !Direction.getValue()) || (second > 1 && !Direction2.getValue())) {
        throw Base::ValueError("Select a pattern direction.");
    }
    std::list<gp_Trsf> grid = calculateTransformations();
    if (!Centered.getValue() && !Centered2.getValue()) {
        return grid;
    }
    const std::vector<gp_Trsf> list(grid.begin(), grid.end());
    if (list.size() != static_cast<std::size_t>(first) * second) {
        return grid;
    }
    // Onshape's Centered (oracle 9j, Q-D1): the count is per side, the seed included, so count n
    // makes 2n - 1 instances along that direction, the steps mirrored through the seed. The grid
    // from the seed has Direction2 fastest; its steps are translations
    const auto step = [&](int k, bool second2) {
        const auto index = static_cast<std::size_t>(std::abs(k));
        const gp_Trsf& t = list[second2 ? index : index * static_cast<std::size_t>(second)];
        gp_Vec v(t.TranslationPart());
        return k < 0 ? v.Reversed() : v;
    };
    const int rows = instancesAlong(first, Centered.getValue());
    const int columns = instancesAlong(second, Centered2.getValue());
    const int middle = Centered.getValue() ? first - 1 : 0;
    const int middle2 = Centered2.getValue() ? second - 1 : 0;
    std::list<gp_Trsf> geometric;
    for (int row = 0; row < rows; ++row) {
        for (int column = 0; column < columns; ++column) {
            gp_Trsf t;
            t.SetTranslation(step(row - middle, false) + step(column - middle2, true));
            geometric.push_back(t);
        }
    }
    return centerInstances(geometric, rows, columns, Centered.getValue(), Centered2.getValue());
}

std::vector<std::size_t> LinearPattern::getSkippedPositions() const
{
    // Along a centered direction there are 2n - 1 instances, the seed the middle one
    const int first = instancesAlong(Occurrences.getValue(), Centered.getValue());
    const int second = instancesAlong(Occurrences2.getValue(), Centered2.getValue());
    const int middle = Centered.getValue() ? (first - 1) / 2 : 0;
    const int middle2 = Centered2.getValue() ? (second - 1) / 2 : 0;
    const auto& pairs = SkippedInstances.getValues();
    std::vector<std::size_t> positions;
    for (std::size_t k = 0; k + 1 < pairs.size(); k += 2) {
        const long i = pairs[k];
        const long j = pairs[k + 1];
        if (i < 0 || i >= first || j < 0 || j >= second) {
            continue;
        }
        const auto position = static_cast<std::size_t>(centeredIndex(static_cast<int>(i), middle))
                * static_cast<std::size_t>(second)
            + static_cast<std::size_t>(centeredIndex(static_cast<int>(j), middle2));
        if (position != 0) {
            positions.push_back(position);
        }
    }
    return positions;
}

std::vector<Transformed::Step> LinearPattern::getTransformationSteps() const
{
    // As getTransformations() combines them: Direction2 varies fastest
    const int first = instancesAlong(Occurrences.getValue(), Centered.getValue());
    const int second = instancesAlong(Occurrences2.getValue(), Centered2.getValue());
    return {{first, second}, {second, 1}};
}

void LinearPattern::handleChangedPropertyType(
    Base::XMLReader& reader,
    const char* TypeName,
    App::Property* prop
)
// transforms properties that had been changed
{
    // property Occurrences had the App::PropertyInteger and was changed to
    // App::PropertyIntegerConstraint
    if (prop == &Occurrences && strcmp(TypeName, "App::PropertyInteger") == 0) {
        App::PropertyInteger OccurrencesProperty;
        // restore the PropertyInteger to be able to set its value
        OccurrencesProperty.Restore(reader);
        Occurrences.setValue(OccurrencesProperty.getValue());
    }
    else {
        Transformed::handleChangedPropertyType(reader, TypeName, prop);
    }
}

}  // namespace PartDesign
