// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2017 Stefan Tröger <stefantroeger@gmx.net>              *
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

#include "Feature.h"

/// Base class of all additive features in PartDesign
namespace PartDesign
{

class PartDesignExport FeatureBase: public PartDesign::Feature
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::FeatureBase);

public:
    FeatureBase();

    /**
     * Compatibility property to preserve restored files that relied on the source
     * object's placement being applied inside FeatureBase.
     */
    App::PropertyBool UseLegacyBaseFeaturePlacement;
    /// The source's side (sourceSides()) when the copy was last computed: one entry, none until
    /// the first recompute after BaseFeature is set (FreeCAD-CH ops#322)
    App::PropertyPlacementList SourceFrame;

    /**
     * Where the shape execute() takes from BaseFeature lies in this feature's container: its
     * Body's frame for a feature of a Body, else its own placement. None for a source that isn't
     * a GeoFeature (an App::Link), which then doesn't move the copy.
     */
    std::optional<Base::Placement> sourceFrame() const;

    short int mustExecute() const override;

    Part::Feature* getBaseObject(bool silent = false) const override;

    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderBase";
    }

    void onChanged(const App::Property* prop) override;
    App::DocumentObjectExecReturn* execute() override;
    void onDocumentRestored() override;

private:
    void trySetBaseFeatureOfBody();
    /// Whether the copy follows its source's frame now (not legacy, not suppressed or held)
    bool followsSource() const;
    /**
     * The frames of both sides in the lowest container that holds the source and this copy, from
     * raw placements: `source`, the source's frame (as sourceFrame()); `owner`, this copy's
     * container. Only the source's side moves the copy (PLAN decision 82). False when
     * sourceFrame() has none.
     */
    bool sourceSides(Base::Placement& source, Base::Placement& owner) const;
};

}  // namespace PartDesign
