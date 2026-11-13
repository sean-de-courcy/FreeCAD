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

#include <limits>
#include <vector>

#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Lin.hxx>
#include <gp_Circ.hxx>
#include <gp_Ax2.hxx>
#include <gp_Trsf.hxx>
#include <BRepAdaptor_Curve.hxx>

#include "DatumLine.h"
#include <Base/Axis.h>
#include <Base/Exception.h>
#include <Base/Tools.h>
#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/Part2DObject.h>
#include <App/Datums.h>

#include "FeaturePolarPattern.h"

using namespace PartDesign;

namespace PartDesign
{

PROPERTY_SOURCE_WITH_EXTENSIONS(PartDesign::PolarPattern, PartDesign::Transformed)

PolarPattern::PolarPattern()
{
    Part::PolarPatternExtension::initExtension(this);

    ADD_PROPERTY_TYPE(
        Centered,
        (false),
        "PolarPattern",
        App::Prop_None,
        "The instances run both ways from the original, Occurrences on each side, the original included"
    );
    ADD_PROPERTY_TYPE(
        SkippedInstances,
        (),
        "Skip",
        App::Prop_None,
        "Instances not made: indexes counted from 0 at the first instance"
    );
}

gp_Ax2 PolarPattern::getRotation() const
{
    App::DocumentObject* refObject = Axis.getValue();
    if (!refObject) {
        return gp_Ax2();
    }

    if (refObject->isDerivedFrom<PartDesign::Line>()) {
        PartDesign::Line* line = static_cast<PartDesign::Line*>(refObject);
        Base::Vector3d base = line->getBasePoint();
        gp_Pnt axbase(base.x, base.y, base.z);
        Base::Vector3d dir = line->getDirection();
        gp_Dir axdir(dir.x, dir.y, dir.z);

        TopLoc_Location invObjLoc = this->getLocation().Inverted();
        axbase.Transform(invObjLoc.Transformation());
        axdir.Transform(invObjLoc.Transformation());

        gp_Ax2 axis(axbase, axdir);
        if (Reversed.getValue()) {
            axis.SetDirection(axis.Direction().Reversed());
        }
        return axis;
    }

    return Part::PolarPatternExtension::getRotation();
}

const std::list<gp_Trsf> PolarPattern::getTransformations(const std::vector<App::DocumentObject*>)
{
    const int count = std::max(static_cast<int>(Occurrences.getValue()), 1);
    std::list<gp_Trsf> turns = calculateTransformations();
    if (!Centered.getValue() || count < 2 || turns.size() != static_cast<std::size_t>(count)) {
        return turns;
    }
    // FreeCAD-CH (ops#655): Onshape's Centered counts per side, the seed included (oracle 9j,
    // Q-D6): count n makes 2n - 1 instances, the turns mirrored through the seed (the angle is the
    // extent on each side)
    const std::vector<gp_Trsf> list(turns.begin(), turns.end());
    std::list<gp_Trsf> geometric;
    for (int k = 1 - count; k < count; ++k) {
        geometric.push_back(
            k < 0 ? list[static_cast<std::size_t>(-k)].Inverted() : list[static_cast<std::size_t>(k)]
        );
    }
    return centerInstances(geometric, 2 * count - 1, 1, true, false);
}

std::vector<std::size_t> PolarPattern::getSkippedPositions() const
{
    // Centered: 2n - 1 instances, the seed the middle one (oracle 9j)
    const int occurrences = std::max(static_cast<int>(Occurrences.getValue()), 1);
    const int count = Centered.getValue() ? 2 * occurrences - 1 : occurrences;
    const int middle = Centered.getValue() ? (count - 1) / 2 : 0;
    std::vector<std::size_t> positions;
    for (long index : SkippedInstances.getValues()) {
        if (index < 0 || index >= count) {
            continue;
        }
        const auto position = static_cast<std::size_t>(centeredIndex(static_cast<int>(index), middle));
        if (position != 0) {
            positions.push_back(position);
        }
    }
    return positions;
}

void PolarPattern::handleChangedPropertyType(
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
