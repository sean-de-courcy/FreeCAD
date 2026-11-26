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

#include "FeatureSketchBased.h"

namespace PartDesign
{

class PartDesignExport Loft: public ProfileBased
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::Loft);

public:
    Loft();

    App::PropertyLinkSubList Sections;
    App::PropertyBool Ruled;
    App::PropertyBool Closed;
    /// Onshape's start and end profile conditions with their magnitudes (ops#655,
    /// notes/loft-options.md): "None" or "Normal to profile"
    App::PropertyEnumeration StartCondition;
    App::PropertyFloat StartMagnitude;
    App::PropertyEnumeration EndCondition;
    App::PropertyFloat EndMagnitude;
    /// Onshape's connections (ops#640, notes/loft-connections.md): entries 2k and 2k+1 are one
    /// vertex of the Profile and one of the Section that the loft joins
    App::PropertyLinkSubList Connections;
    /// How "Normal to profile" sizes its tangents (ops#855, R3): "Onshape", the per-rail rule of
    /// fork-1.0.1 (fork PR 468), or "Legacy", fork-1.0.0's k * distance, which a loft read from a
    /// file without this property (saved by ForkRelease 12 or older) keeps. Hidden.
    App::PropertyEnumeration TangentRule;
    /// The vertex pairing each unconnected loop pair with different vertex counts took on the last
    /// recompute (ops#1071): "chain" (Onshape's, by corner position), "old-tie" (OCCT's polar
    /// method: two pairings fit equally), "tie-picked" (two fit equally and OCCT's failed: the first
    /// in a fixed order), "old-failure" (OCCT's: the chain didn't build), comma
    /// separated; empty where none applies. A recompute that changes it warns. Hidden output.
    App::PropertyString PairingRule;

    /** @name methods override feature */
    //@{
    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;
    /// returns the type name of the view provider
    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderLoft";
    }
    //@}

    static std::vector<Part::TopoShape> getSectionShape(
        const char* name,
        App::DocumentObject* obj,
        const std::vector<std::string>& subname,
        size_t expected_size = 0
    );

    void Restore(Base::XMLReader& reader) override;

protected:
    // handle changed property
    void handleChangedPropertyType(
        Base::XMLReader& reader,
        const char* TypeName,
        App::Property* prop
    ) override;

private:
    /// The loft, with Onshape's automatic start pairs for unconnected profiles or without them
    /// (ops#1071); `automaticUsed` says whether one was taken, `rules` gets each unconnected loop
    /// pair's pairing (`PairingRule`'s words); `pickTies` takes a tied pair's first chain instead of
    /// the old pairing.
    App::DocumentObjectExecReturn* executeLoft(
        bool automaticStarts,
        bool& automaticUsed,
        std::vector<std::string>& rules,
        bool pickTies = false
    );
    /// Stores the pairing of this recompute in `PairingRule`, with a warning when it changed.
    void notePairing(const std::vector<std::string>& rules);

    static const char* ConditionEnums[];
    static const char* TangentRuleEnums[];
    // static const char* TypeEnums[];
    // static const char* SideEnums[];
};

class PartDesignExport AdditiveLoft: public Loft
{

    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::AdditiveLoft);

public:
    AdditiveLoft();
};

class PartDesignExport SubtractiveLoft: public Loft
{

    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::SubtractiveLoft);

public:
    SubtractiveLoft();
};

}  // namespace PartDesign
