// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2015 Stefan Tröger <stefantroeger@gmx.net>              *
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
#include <string>
#include <vector>

#include "FeatureSketchBased.h"
#include <App/PropertyUnits.h>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Dir.hxx>
#include <Law_Function.hxx>

namespace PartDesign
{

class PartDesignExport Pipe: public ProfileBased
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::Pipe);

public:
    Pipe();

    App::PropertyLinkSub Spine;
    App::PropertyBool SpineTangent;
    App::PropertyLinkSub AuxiliarySpine;
    App::PropertyBool AuxiliarySpineTangent;
    App::PropertyBool AuxiliaryCurvilinear;
    App::PropertyEnumeration Mode;
    App::PropertyVector Binormal;
    App::PropertyEnumeration Transition;
    App::PropertyEnumeration Transformation;
    App::PropertyLinkSubList Sections;
    /// How the profile is carried along the path, in Onshape's terms (notes\sweep-design.md):
    /// "None" (its frame turns with the path), "Keep orientation" (Mode "Fixed"), or "Advanced"
    /// (Mode decides, as in files from before it, and when Mode is set directly)
    App::PropertyEnumeration ProfileControl;
    /// A profile in the middle of the path sweeps both ways along all of it (on), or from the
    /// profile one way (off)
    App::PropertyBool ExtendToFullPath;
    /// The other way along the path from the profile, with ExtendToFullPath off (Onshape's
    /// opposite direction, SW1)
    App::PropertyBool PathReversed;
    /// More path edges, from other objects than Spine's: joined with Spine's in any order
    App::PropertyLinkSubList SpineMore;
    /// Onshape's Sweep, slice 3 (notes\sweep-design.md 3, onshape-facts SW11-SW14)
    /// Faces the path lies on, for ProfileControl "Lock faces": the profile keeps its angle to
    /// their normal along the path
    App::PropertyLinkSubList LockFaces;
    /// A plane, planar face or straight edge, for ProfileControl "Lock direction": the profile's
    /// plane keeps containing its direction (a plane's or face's normal, an edge's direction)
    App::PropertyLinkSub LockDirection;
    /// The profile turns about the path, linearly in the path's length (SW11)
    App::PropertyBool HasTwist;
    /// How the twist is given: Turns, Angle (over the path), or Pitch (the length of one turn)
    App::PropertyEnumeration TwistType;
    App::PropertyFloat Turns;
    App::PropertyAngle TwistAngle;
    App::PropertyLength TwistPitch;
    /// Counter-clockwise about the path's direction (off: clockwise, Onshape's default)
    App::PropertyBool TwistCCW;
    /// The profile scales linearly in the path's length to ScaleFactor at the path's end (SW12)
    App::PropertyBool HasScale;
    App::PropertyFloat ScaleFactor;
    /// Solid, or Thin: a wall of Thickness1 (and Thickness2 on the other side) around the
    /// profile's curves, swept (SW14)
    App::PropertyEnumeration BodyType;
    App::PropertyLength Thickness1;
    App::PropertyLength Thickness2;
    // The wall centred on the profile's curves, Thickness1 in all: ProfileBased's Midplane. Not
    // a Midplane of Pipe's own: of two static properties of one name only the derived class's
    // is in the property list, so the inherited one was never purged, stayed touched from its
    // construction, and ProfileBased::mustExecute() ran every pipe in every recompute (ops#640)
    /// The wall on the other side of the profile's curves
    App::PropertyBool FlipWall;
    /// Onshape's Thin option; no effect, as in Onshape (SW14: on and off gave the same in every case)
    App::PropertyBool TrimEnds;
    /// Where the spine started and ended at the last successful recompute, the end that carried
    /// the profile's names first, where they lie in the body (ops#379). Read for the input they
    /// were stored for, or where they still are the spine's ends (ops#435)
    App::PropertyVectorList SpineEnds;
    /// The input SpineEnds was stored for (Spine's object, its elements' mapped names, sorted)
    App::PropertyStringList SpineEndsOf;
    /// A closed spine of one profile (not Auxiliary) at the last successful recompute of it, in
    /// the body, 2n + 1 points for n edges: its start, its first edge's middle, whether its end
    /// carried the profile's names (1 or 0 in x), its other vertices in the sweep's order and
    /// their edges' middles (ops#469); then the profile's frames (its placement, its geometry's)
    /// and the spine object's placement (ops#546; not in an odd count, a record from before),
    /// each its origin and the ends of its x and y axes. Kept while the spine is open or in another
    /// mode; read for the input it was stored for, or where its points still lie on the spine, in
    /// the body, turned with the whole model, or in one of the profile's frames
    App::PropertyVectorList SpineStart;
    /// The input SpineStart was stored for, as SpineEndsOf
    App::PropertyStringList SpineStartOf;
    /// The mapped name of the line at each of SpineStart's places (its edges, the start's first):
    /// a leg is its place, named by its line, and the two must agree (`notes\naming-class-B.md` 9)
    App::PropertyStringList SpineStartNames;
    /// The records of SpineStart for the last earlier inputs (at most 3, the latest first), so a
    /// spine set back to one of them starts where it did: each the count of its points (in x),
    /// then its points
    App::PropertyVectorList EarlierSpineStarts;
    /// Their inputs, as SpineStartOf, each followed by an empty string
    App::PropertyStringList EarlierSpineStartsOf;
    /// Their lines' names, as SpineStartNames, each record's followed by an empty string
    App::PropertyStringList EarlierSpineStartNames;

    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;
    /// A file without ProfileControl reads as "Advanced" (its Mode decides, as before), without
    /// ExtendToFullPath as on (it swept the whole path)
    void Restore(Base::XMLReader& reader) override;
    /// returns the type name of the view provider
    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderPipe";
    }
    App::DocumentObjectExecReturn* _execute(
        ProfileBased* feat,
        const TopoShape& path,
        const TopLoc_Location& invObjLoc = TopLoc_Location(),
        int transition = 0,
        const TopoShape& auxpath = TopoShape(),
        bool auxCurviLinear = true,
        int mode = 2,
        const Base::Vector3d& binormalVector = Base::Vector3d(),
        int transformation = 0,
        const std::vector<App::PropertyLinkSubList::SubSet>& multisections = {},
        bool moveProfile = false,
        bool rotateProfile = false
    );

protected:
    /// get the given edges and all their tangent ones
    void getContinuousEdges(Part::TopoShape TopShape, std::vector<std::string>& SubNames);
    void buildPipePath(
        const Part::TopoShape& input,
        const std::vector<std::string>& edges,
        Part::TopoShape& result
    );
    void setupAlgorithm(BRepOffsetAPI_MakePipeShell& mkPipeShell, const TopoDS_Shape& auxshape);
    /// ProfileControl sets Mode; Mode set directly makes ProfileControl "Advanced"
    void onChanged(const App::Property* prop) override;
    /// Slice 3's checks and the guide and scale law for one profile along  path (in the pipe's
    /// frame  invObjLoc): sets frameGuide and  scale. An error's text, or nothing
    std::optional<std::string> prepareSlice3(
        const Part::TopoShape& path,
        const std::vector<TopoDS_Shape>& profileWires,
        const TopLoc_Location& invObjLoc,
        Handle(Law_Function)& scale
    );
    /// The profile's plane normal in the pipe's frame (\a invObjLoc): a sketch's placement Z, a
    /// planar face's normal; none for another profile
    std::optional<gp_Dir> profileNormal(const TopLoc_Location& invObjLoc) const;
    /// handle changed property
    void handleChangedPropertyType(
        Base::XMLReader& reader,
        const char* TypeName,
        App::Property* prop
    ) override;
    void handleChangedPropertyName(
        Base::XMLReader& reader,
        const char* TypeName,
        const char* PropName
    ) override;

private:
    static const char* TypeEnums[];
    static const char* TransitionEnums[];
    static const char* ModeEnums[];
    static const char* TransformEnums[];
    static const char* ProfileControlEnums[];
    static const char* TwistTypeEnums[];
    static const char* BodyTypeEnums[];
    /// Set while ProfileControl sets Mode, or the constructor or Restore set either
    bool settingMode = false;
    /// ProfileControl "None" along a path that isn't planar, where OCCT's Frenet frame neither
    /// turns over nor jumps: the sweep in Mode "Standard" takes Frenet's frame (a helix keeps its
    /// profile square to its axis). Set by execute for setupAlgorithm
    bool frenetForNone = false;
    /// A guide curve that orients the profile (twist, lock faces): the sweep's normal points from
    /// the path to it in each plane square to the path. Set by execute for setupAlgorithm
    TopoDS_Wire frameGuide;
    /// The binormal of Mode "Binormal" in the Body's coordinates: Binormal, or LockDirection's
    /// direction for ProfileControl "Lock direction". Set by execute
    Base::Vector3d binormalInBody;
};

class PartDesignExport AdditivePipe: public Pipe
{

    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::AdditivePipe);

public:
    AdditivePipe();
};

class PartDesignExport SubtractivePipe: public Pipe
{

    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::SubtractivePipe);

public:
    SubtractivePipe();
};

/// How many caps of a pipe's solid face out of it and how many into it (pipeCapsFacing)
struct PipeCapFacing
{
    int outward = 0;
    int inward = 0;
};

/// How the caps of \a solid, swept along \a spine, face: its faces made of the sections where the
/// spine starts (\a starts) and ends (\a ends), each judged by the way the section moves at its
/// vertices, away from the start cap and towards the end cap. An outward cap faces against that
/// motion at the start and with it at the end. The motion is the spine's tangent plus the frame's
/// turn with the spine's bend (\a turning, every mode but Fixed), so a profile that lies beyond the
/// centre of the spine's first bend, moving backwards, is judged right. A cap whose vertices don't
/// all agree, within 3 degrees of edge-on, isn't counted. Independent of OCCT's solid classifier,
/// which passed an inside-out multisection solid on macOS (ops#396).
PartDesignExport PipeCapFacing pipeCapsFacing(
    const TopoDS_Shape& solid,
    const TopoDS_Wire& spine,
    const std::vector<TopoDS_Shape>& starts,
    const std::vector<TopoDS_Shape>& ends,
    bool turning
);

}  // namespace PartDesign
