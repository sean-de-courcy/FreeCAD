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

#include "FeatureAddSub.h"

namespace PartDesign
{

class PartDesignExport DressUp: public PartDesign::FeatureAddSub
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::DressUp);

public:
    DressUp();

    /**
     * Base feature and it's subelements to which dressup operation will be applied to.
     * Unlike Feature::BaseFeature it includes Sublinks and set not only inside a body.
     * But for consistency if BaseFeature is nonzero this links to the same body as it.
     */
    App::PropertyLinkSub Base;
    App::PropertyBool SupportTransform;
    /// A studio dress-up's picks on any parts, resolved (FreeCAD-CH ops#654, P8a)
    App::PropertyLinkSubList StudioPicks;
    /// The part id of each of StudioPicks (intent)
    App::PropertyStringList StudioPickIds;
    /** FreeCAD-CH ops#701 (F2b): the dress-up this one was made with, in another part, by one
     * command over edges of several parts (this one follows its sizes by expression). When that
     * one builds and this one fails, this one passes its part through with a warning, as
     * Onshape's FILLET_PARTIAL_FAIL; when that one fails too, this one's failure is an error.
     * Hidden scope, as FeatureAddSub::SiblingOf: no dependency of its own (the expressions order
     * the two). Not SiblingOf itself: FeatureAddSub::recompute() checks a sibling's links against
     * its primary's, and a dress-up's Base is its own part's edges.
     */
    App::PropertyLinkHidden MultiPartPrimary;

    short mustExecute() const override;

    /** FreeCAD-CH ops#701 (F2b): ret, the dress-up's result, as Onshape's partial failure: when
     * it failed and MultiPartPrimary built (itself: not suppressed or passed through), the base
     * passes through, the failure becomes the warning "Failed to <verb> selections on <part>:
     * <why>" and the result is a success, so the part's later features recompute on its base.
     * Only while the expression of sizeProperty still refers to the primary (F2c). Otherwise ret
     * unchanged.
     */
    App::DocumentObjectExecReturn* partialFailure(
        App::DocumentObjectExecReturn* ret,
        const char* verb,
        const char* sizeProperty
    );
    /// updates the Placement property from the Placement of the BaseFeature
    void positionByBaseFeature();
    /**
     * Returns the BaseFeature property's object if it's set otherwise returns Base's
     * feature property object otherwise feature property's object (if any)
     * @param silent if couldn't determine the base feature and silent == true,
     *               silently return a nullptr, otherwise throw Base::Exception.
     *               Default is false.
     */
    Part::Feature* getBaseObject(bool silent = false) const override;
    /// extracts all edges from the subshapes (including face edges) and furthermore adds
    /// all C0 continuous edges to the vector
    void getContinuousEdges(Part::TopoShape, std::vector<std::string>&);
    // add argument to return the selected face that edges were derived from
    void getContinuousEdges(Part::TopoShape, std::vector<std::string>&, std::vector<std::string>&);
    // Todo: Post-TNP the above two versions should be able to be factored out.
    std::vector<TopoShape> getContinuousEdges(const TopoShape& shape);

    std::vector<TopoShape> getFaces(const TopoShape& shape);
    void getAddSubShape(Part::TopoShape& addShape, Part::TopoShape& subShape) override;
    void updatePreviewShape() override;

protected:
    void onBeforeChange(const App::Property* prop) override;
    void onChanged(const App::Property* prop) override;
    void onBaseFeatureRerouted(
        App::DocumentObject* oldBase,
        App::DocumentObject* newBase,
        bool reorder
    ) override;

private:
    /// Base's object before its current change, recorded by onBeforeChange() and compared only
    /// by address in onChanged()
    App::DocumentObject* baseBeforeChange {nullptr};
    bool baseChanging {false};
};

}  // namespace PartDesign
