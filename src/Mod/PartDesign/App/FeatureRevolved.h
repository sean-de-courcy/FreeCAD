// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2010 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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

#pragma once

#include <optional>

#include <App/PropertyUnits.h>
#include "FeatureSketchBased.h"

namespace Part
{
enum class RevolMode;
}

class TopLoc_Location;

namespace PartDesign
{

class PartDesignExport Revolved: public ProfileBased
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::Revolved);

public:
    Revolved();

    static const char* SideTypesEnums[];

    App::PropertyEnumeration SideType;
    App::PropertyEnumeration Type;
    App::PropertyEnumeration Type2;
    App::PropertyVector Base;
    App::PropertyVector Axis;
    App::PropertyAngle Angle;
    App::PropertyAngle Angle2;
    App::PropertyEnumeration StartType;
    App::PropertyAngle StartOffset;
    App::PropertyLinkSub StartReference;

    /** if this property is set to a valid link, both Axis and Base properties
     *  are calculated according to the linked line
     */
    App::PropertyLinkSub ReferenceAxis;

    /** @name methods override feature */
    //@{
    short mustExecute() const override;
    void onChanged(const App::Property* prop) override;
    //@}

    /// suggests a value for Reversed flag so that material is always added to the support
    bool suggestReversed();
    /// the suggestion, or none when it can't be computed (no valid axis or profile face)
    std::optional<bool> suggestedReversed();

    /// Returns the effective angular offset from the profile plane in degrees.
    double getStartOffset() const;

    enum class RevolMethod
    {
        Angle,
        ThroughAll,
        ToLast = ThroughAll,
        ToFirst,
        ToFace,
        TwoAngles
    };

protected:
    /** Recalculate the feature
     * Revolves the Sketch around the given Axis (with basepoint Base)
     * The angle of the revolution is given by Angle.
     * If Midplane is true, then the revolution will extend for half of Angle on both sides of the
     * sketch plane. If Reversed is true then the direction of revolution will be reversed. The
     * created material will be fused with the sketch support (if there is one)
     */
    App::DocumentObjectExecReturn* executeRevolved(Part::RevolMode revolMode);
    void onDocumentRestored() override;

private:
    App::DocumentObjectExecReturn* executeRevolvedOnce(Part::RevolMode revolMode);
    App::DocumentObjectExecReturn* tryExecuteRevolved(Part::RevolMode revolMode);
    TopoShape tryGetBaseShape() const;
    // The face up to the first or last face of the base, or the chosen face (ToFace)
    TopoShape getRevolutionUpToFace(
        RevolMethod method,
        const TopoShape& chosenFace,
        const TopoShape& base,
        const TopoShape& sketchshape,
        const gp_Ax1& axis
    ) const;
    TopoShape tryToRevolveToFace(
        const TopoShape& upToFace,
        const gp_Ax1& axis,
        const TopoShape& sketchshape
    ) const;
    TopoShape generateSingleRevolutionSide(
        RevolMethod method,
        double angle,
        const TopoShape& chosenFace,
        const TopoShape& sketchshape,
        const TopoShape& base,
        const gp_Pnt& pnt,
        const gp_Dir& dir,
        Part::RevolMode revolMode,
        bool markSeam = false
    );
    // The base operation's volume must be possible for a correct fuse or cut of the two; with
    // `checkVolume` (an up-to-face tool, ops#293), its edges must also meet within tolerance
    void setResult(const TopoShape& base, const TopoShape& revolved, bool checkVolume = false);
    // A side's tool was built by constructFirstContact() in this recompute (ops#293 D2): its
    // volume checks integrate over knot spans (FirstContact::spanVolume())
    mutable bool constructedTool = false;
    // ops#1048: setResult()'s point check refused the combined result (OCCT missed where the
    // tool's cone meets the base), and this recompute's retry turns the profile's straight edges
    // that end on the axis into degree-1 B-splines (freshAxisEdges()), which OCCT intersects
    bool pointCheckRefused = false;
    bool splineConeLines = false;
    // review r1: the refused first result (its volume, the base's, valid or not) and the retry's
    // volume once it passed the point check (-1: not reached); a retry that agrees with a valid
    // first result keeps the first (the check refused a right result), computed with the check off
    // (review r2: the solids must match; review r3: the agreement scales with the change)
    double refusedVolume = -1.0;
    double refusedBaseVolume = 0.0;
    bool refusedValid = false;
    unsigned long refusedSolids = 0;
    double retriedVolume = -1.0;
    unsigned long retriedSolids = 0;
    bool skipPointCheck = false;
    // how far the retry's volume may be from the refused first result's for the first to be
    // kept: 1e-3 of the retry's change to the base (a miss differs by the change it missed;
    // the retry's revolution surfaces by about 1e-5 of it), plus 1e-9 of the base for a change
    // of nothing (a tool touching the base, review r1)
    double keptTolerance() const;

    double getStartReferenceAngle(
        const TopoShape& profileShape,
        const App::PropertyLinkSub& reference,
        const gp_Ax1& axis,
        double offset,
        const TopLoc_Location& invObjLoc
    ) const;
    static TopoShape rotateProfileToStart(const TopoShape& profileShape, const gp_Ax1& axis, double angle);

    /// updates Axis from ReferenceAxis
    void updateAxis();

    virtual TopoShape makeShape(const TopoShape& base, const TopoShape& revolve) const = 0;
    virtual bool suggestReversedAngle(double angle) const = 0;

    /**
     * Generates a revolution of the input sketchshape and stores it in the given \a revol.
     */
    void generateRevolution(
        TopoShape& revol,
        const TopoShape& sketchshape,
        const gp_Ax1& ax1,
        double angle,
        double angle2,
        bool midplane,
        bool reversed,
        RevolMethod method
    );

    /**
     * Disables settings that are not valid for the current method
     */
    void updateProperties();

    static const App::PropertyAngle::Constraints floatAngle;
};

}  // namespace PartDesign
