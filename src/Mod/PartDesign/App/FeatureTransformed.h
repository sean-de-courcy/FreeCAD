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

#include <gp_Trsf.hxx>

#include <App/PropertyStandard.h>
#include "FeatureRefine.h"


namespace PartDesign
{

/**
 * Abstract superclass of all features that are created by transformation of another feature
 * Transformations are translation, rotation and mirroring
 */
class PartDesignExport Transformed: public PartDesign::FeatureRefine
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::Transformed);

public:
    enum class Mode
    {
        Features,
        WholeShape
    };

    Transformed();

    /** The features to be transformed
     */
    App::PropertyLinkList Originals;
    App::PropertyEnumeration TransformMode;
    App::PropertyBool Refine;
    /** @name Studio patterns (FreeCAD-CH ops#655, T1-T3) */
    //@{
    /// Feature: the originals' tools; Part: the entities are parts (StudioEntities)
    App::PropertyEnumeration PatternType;
    /// Recompute each original's tool at each instance (Onshape's Reapply features)
    App::PropertyBool Reapply;
    /// A Part pattern's parts, by part id
    App::PropertyStringList StudioEntities;
    //@}

    /**
     * Returns the BaseFeature property's object(if any) otherwise return first original,
     *         which serves as "Support" for old style workflows
     * @param silent if couldn't determine the base feature and silent == true,
     *               silently return a nullptr, otherwise throw Base::Exception.
     *               Default is false.
     */
    Part::Feature* getBaseObject(bool silent = false) const override;

    virtual std::vector<App::DocumentObject*> getOriginals() const;
    /** Returns the list of original features sorted in chronological order of
     *  the parent Body's history (retaining suppressed features).
     */
    std::vector<App::DocumentObject*> getSortedOriginals() const;

    /// Return the sketch of the first original
    App::DocumentObject* getSketchObject() const;

    /// Return true if this feature is a child of a MultiTransform
    bool isMultiTransformChild() const;

    /** FreeCAD-CH (ops#640, F3): not a solid feature of its Body: a MultiTransform's step, or a
     * new pattern with nothing picked yet (isMultiTransformChild() and no BaseFeature). A pattern
     * in the chain whose Originals went (the original deleted) stays in it and fails with
     * "Select features to pattern", so its base passes through
     */
    bool isOutOfChain() const;

    /// Get the list of transformations describing the members of the pattern
    // Note: Only the Scaled feature requires the originals
    virtual const std::list<gp_Trsf> getTransformations(const std::vector<App::DocumentObject*> /*originals*/)
    {
        return std::list<gp_Trsf>();  // Default method
    }

    /// One step of a pattern: its number of instances, and how far apart two instances next to
    /// each other along it are in the list of getTransformations() (ops#6).
    struct Step
    {
        int count;
        int stride;
    };

    /** The steps getTransformations() combined, in the order of the digits of an instance's
     * number: a V2 instance's name holds its number along each (ops#6). The default, an empty
     * list, is one step: the whole list. Valid after getTransformations().
     */
    virtual std::vector<Step> getTransformationSteps() const
    {
        return {};
    }

    /** The positions in the list getTransformations() returned whose instances are not made:
     * Onshape's Skip instances (FreeCAD-CH ops#640 rank 8). Never 0, the original. The others
     * keep their instance numbers. None by default. Valid after getTransformations().
     */
    virtual std::vector<std::size_t> getSkippedPositions() const
    {
        return {};
    }

    /** @name methods override feature */
    //@{
    /** Recalculate the feature
     * Gets the transformations from the virtual getTransformations() method of the sub class
     * and applies them to every member of Originals. The total number of copies including
     * the untransformed Originals will be sizeof(Originals) times sizeof(getTransformations())
     * If Originals is empty, execute() returns immediately without doing anything as
     * the actual processing will happen in the MultiTransform feature
     */
    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;
    //@}

    /// The direction, axis or mirror plane, read in this feature's Body (FreeCAD-CH ops#325)
    std::vector<const char*> placerProperties() const override
    {
        return {"Direction", "Direction2", "Axis", "MirrorPlane"};
    }

    App::DocumentObjectExecReturn* recomputePreview() override;

    void onChanged(const App::Property* prop) override;

    /** returns the compound of the shapes that were rejected during the last execute
     * because they did not overlap with the support
     */
    TopoDS_Shape rejected;

protected:
    void Restore(Base::XMLReader& reader) override;
    void handleChangedPropertyType(
        Base::XMLReader& reader,
        const char* TypeName,
        App::Property* prop
    ) override;

    virtual void positionBySupport();
    static TopoDS_Shape getRemainingSolids(const TopoDS_Shape&);

    /** Onshape's Centered (FreeCAD-CH ops#640 rank 8) on a list of rows x columns transformations
     * (position = row * columns + column; the original at 0): with centerRows, the instances run
     * both ways from the original along the rows' step, the original the middle one (with an even
     * count, one more on the positive side); centerColumns the same along the columns' step. The
     * original stays at position 0: the rows (columns) at index 0 and at the middle swap places.
     */
    static std::list<gp_Trsf> centerInstances(
        const std::list<gp_Trsf>& transformations,
        int rows,
        int columns,
        bool centerRows,
        bool centerColumns
    );
    /// The index the row (column) at geometric index k has in centerInstances()'s list, middle
    /// being the original's geometric index: 0 and middle swap
    static int centeredIndex(int k, int middle)
    {
        return k == middle ? 0 : (k == 0 ? middle : k);
    }

private:
    /// Out of its Body's chain (a step, or a new pattern of nothing): the solid after it builds on
    /// the one before it, and its BaseFeature is cleared
    void leaveChain(Body* body);
};

}  // namespace PartDesign
