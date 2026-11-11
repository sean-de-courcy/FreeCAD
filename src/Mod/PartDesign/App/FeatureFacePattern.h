// SPDX-License-Identifier: LGPL-2.1-or-later
// SPDX-FileNotice: Part of the FreeCAD project.

/******************************************************************************
 *                                                                            *
 *   FreeCAD is free software: you can redistribute it and/or modify          *
 *   it under the terms of the GNU Lesser General Public License as           *
 *   published by the Free Software Foundation, either version 2.1            *
 *   of the License, or (at your option) any later version.                   *
 *                                                                            *
 *   FreeCAD is distributed in the hope that it will be useful,               *
 *   but WITHOUT ANY WARRANTY; without even the implied warranty              *
 *   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                  *
 *   See the GNU Lesser General Public License for more details.              *
 *                                                                            *
 *   You should have received a copy of the GNU Lesser General Public         *
 *   License along with FreeCAD. If not, see https://www.gnu.org/licenses     *
 *                                                                            *
 ******************************************************************************/

#pragma once

#include <list>
#include <vector>

#include <gp_Trsf.hxx>

#include <App/PropertyStandard.h>
#include <Mod/Part/App/LinearPatternExtension.h>
#include <Mod/Part/App/PolarPatternExtension.h>

#include "FeatureDressUp.h"

namespace PartDesign
{

/**
 * FreeCAD-CH (ops#655 T8, notes/face-pattern-design.md): Onshape's Face pattern. The picked faces
 * of the base (a boss's sides and top, a pocket's walls and floor, a hole's cylinder) bound a
 * feature volume: the base minus the base defeatured of those faces (what they add), and the
 * reverse (what they remove). Each instance fuses and cuts a copy of that volume at its place.
 * The faces are the dress-up's Base subnames; the subclasses give the instances.
 */
class PartDesignExport FacePattern: public DressUp
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::FacePattern);

public:
    FacePattern();

    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;

    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderFacePattern";
    }

    /// The transforms of the pattern's places, in the base's own frame; the first is the seed's
    /// (the identity) and is not copied
    virtual std::vector<gp_Trsf> instanceTransforms();
    /// The positions in instanceTransforms() of the instances skipped (never 0)
    virtual std::vector<std::size_t> skippedPositions() const;

protected:
    /// As Transformed::centerInstances (protected there): the instance at the middle of each
    /// centred direction becomes the seed, first in the list
    static std::vector<gp_Trsf> centered(
        const std::list<gp_Trsf>& transformations,
        int rows,
        int columns,
        bool centerRows,
        bool centerColumns
    );
    static int centeredIndex(int k, int middle)
    {
        return k == middle ? 0 : (k == 0 ? middle : k);
    }
};

/// A linear face pattern: one or two directions (Part's LinearPatternExtension), Centered, Skip
class PartDesignExport FaceLinearPattern: public FacePattern, public Part::LinearPatternExtension
{
    PROPERTY_HEADER_WITH_EXTENSIONS(PartDesign::FaceLinearPattern);

public:
    FaceLinearPattern();

    App::PropertyBool Centered;
    App::PropertyBool Centered2;
    /// (i, j) index pairs, flattened, from 0 at the negative end of each direction (as LinearPattern)
    App::PropertyIntegerList SkippedInstances;

    std::vector<gp_Trsf> instanceTransforms() override;
    std::vector<std::size_t> skippedPositions() const override;
    gp_Dir getDirectionFromProperty(const App::PropertyLinkSub& dirProp) const override;
};

/// A circular face pattern (Part's PolarPatternExtension), Centered, Skip
class PartDesignExport FacePolarPattern: public FacePattern, public Part::PolarPatternExtension
{
    PROPERTY_HEADER_WITH_EXTENSIONS(PartDesign::FacePolarPattern);

public:
    FacePolarPattern();

    App::PropertyBool Centered;
    /// Indexes from 0 at the seed (as PolarPattern)
    App::PropertyIntegerList SkippedInstances;

    std::vector<gp_Trsf> instanceTransforms() override;
    std::vector<std::size_t> skippedPositions() const override;
    gp_Ax2 getRotation() const override;
};

/// A face mirror: one copy, mirrored in a plane (a datum or origin plane, or a planar face)
class PartDesignExport FaceMirrored: public FacePattern
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::FaceMirrored);

public:
    FaceMirrored();

    App::PropertyLinkSub MirrorPlane;

    std::vector<gp_Trsf> instanceTransforms() override;
};

}  // namespace PartDesign
