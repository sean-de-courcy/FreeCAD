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

#include <vector>

#include "FeatureSketchBased.h"
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <TopoDS_Wire.hxx>

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
    /// Where the spine started and ended at the last successful recompute, the end that carried
    /// the profile's names first, in the feature's frame; empty before (ops#379)
    App::PropertyVectorList SpineEnds;

    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;
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
