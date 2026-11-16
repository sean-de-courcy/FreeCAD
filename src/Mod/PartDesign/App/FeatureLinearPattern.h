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


#pragma once

#include <App/PropertyUnits.h>
#include <Mod/Part/App/LinearPatternExtension.h>
#include "FeatureTransformed.h"

class gp_Vec;

namespace PartDesign
{

class PartDesignExport LinearPattern: public PartDesign::Transformed,
                                      public Part::LinearPatternExtension
{
    PROPERTY_HEADER_WITH_EXTENSIONS(PartDesign::LinearPattern);

public:
    LinearPattern();

    /** @name Onshape's linear pattern options (FreeCAD-CH ops#640 rank 8)
     * Off and empty by default, so a file saved before them computes as it did.
     */
    //@{
    /// Centered: the instances run both ways from the original along Direction, Occurrences on
    /// each side, the original included (Onshape's, oracle 9j: count n makes 2n - 1)
    App::PropertyBool Centered;
    /// Centered along Direction2, likewise (Onshape's own box for it, oracle 9j)
    App::PropertyBool Centered2;
    /// Skip instances: (i, j) pairs, flattened (i1, j1, i2, j2, ...): i counts the instances along
    /// Direction, j along Direction2, both from 0 at the negative end (the original is (0, 0)
    /// unless centered), as Onshape lists them. The original is never skipped; a pair out of
    /// range is ignored
    App::PropertyIntegerList SkippedInstances;
    //@}

    std::vector<std::size_t> getSkippedPositions() const override;

    // Virtual override to support PartDesign datum objects
    gp_Dir getDirectionFromProperty(const App::PropertyLinkSub& dirProp) const override;

    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderLinearPattern";
    }
    //@}

    /** Create transformations
     * Returns a list of (Occurrences - 1) transformations since the first, untransformed instance
     * is not counted.
     *
     * Depending on Mode selection list will be constructed differently:
     * 1. For "Overall Length" each transformation will move the shape it is applied to by the
     * distance (Length / (Occurrences - 1)) so that the transformations will cover the total
     * Length.
     * 2. For "Spacing" each transformation will move the shape by the distance explicitly given in
     *    the Offset parameter.
     *
     * If Direction contains a feature and a face name, then the transformation direction will be
     *   the normal of the given face, which must be planar. If it contains an edge name, then the
     *   transformation direction will be parallel to the given edge, which must be linear
     *
     * If Reversed is true, the direction of transformation will be opposite
     */
    const std::list<gp_Trsf> getTransformations(const std::vector<App::DocumentObject*>) override;

    /// Direction, then Direction2: the instances along Direction2 are next to each other in the
    /// list.
    std::vector<Step> getTransformationSteps() const override;

protected:
    void handleChangedPropertyType(
        Base::XMLReader& reader,
        const char* TypeName,
        App::Property* prop
    ) override;
};

}  // namespace PartDesign
