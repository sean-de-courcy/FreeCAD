// SPDX-License-Identifier: LGPL-2.1-or-later

/***************************************************************************
 *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
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

#include <App/PropertyStandard.h>
#include <App/PropertyLinks.h>
#include <App/SuppressibleExtension.h>
#include <Mod/Part/App/PartFeature.h>
#include <Mod/Part/App/PreviewExtension.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

class gp_Pnt;
class gp_Pln;


/// Base class of all additive features in PartDesign
namespace PartDesign
{

using TopoShape = Part::TopoShape;

class Body;

/** PartDesign feature
 *   Base class of all PartDesign features.
 *   This kind of features only produce solids or fail.
 */
class PartDesignExport Feature: public Part::Feature,
                                public App::SuppressibleExtension,
                                public Part::PreviewExtension
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::Feature);

public:
    Feature();

    enum SingleSolidRuleMode
    {
        Disabled = 0,
        Enforced = 1
    };

    /// Base feature which this feature will be fused into or cut out of
    App::PropertyLink BaseFeature;
    App::PropertyLinkHidden _Body;

    /// Keep a copy of suppressed shapes so that we can restore them (and maybe display them)
    Part::PropertyPartShape SuppressedShape;
    /// Keep a copy of the placement before suppression to restore it back when unsuppressed, fix #20205
    Base::Placement SuppressedPlacement;
    /// The last recompute wrote the base as the output because the feature is suppressed
    /// (ops#549 PS): the shape's own state, which Suppressed alone isn't until the recompute
    App::PropertyBool _PassedThrough;
    /// The last recompute failed and the failure rule wrote the base as the output (ops#549 PT):
    /// the shape's own state, which the error alone isn't (it stays set while the next recompute
    /// runs, and that recompute's own shape solves the references to it). Saved with the shape,
    /// as the error is: an opened file judges by both.
    App::PropertyBool _FailurePassedThrough;

    /** @name Studio features (FreeCAD-CH ops#654, notes/parts-design.md 10.8,
     * notes/one-history-design.md 5 and 9). Hidden; read by name (StudioList.h), so that an
     * owner of another class may carry them as dynamic properties */
    //@{
    /// An owner's scope: the part ids (Body::StudioPartId) it acts on, in order (intent: an Add
    /// keeps the first). Ids, never links: a split part's id stands for all its pieces
    App::PropertyStringList StudioScope;
    /// A step's owner (a real dependency: the step applies its tool)
    App::PropertyLinkGlobal StudioOwner;
    /// An owner's bases, written by reconcile: each in-scope part's solid just before its step
    App::PropertyLinkListGlobal StudioBases;
    //@}

    /// The tag a step's names carry: its studio owner's object ID, 0 (its own) for any other
    /// feature. The owner is intent and its ID is saved and restored, so a step made again makes
    /// the same names (format rule 2, notes/stored-tags.md)
    long namingTag() const
    {
        const App::DocumentObject* owner = StudioOwner.getValue();
        return owner ? owner->getID() : 0;
    }
    /** @name Part::Feature's makeTopoShape() with namingTag() for a tag of 0, so that every step
     * (appliers, dress-ups, Shell, Draft) names its results by its owner (ops#654) */
    //@{
    using Part::Feature::makeTopoShape;
    TopoShape makeTopoShape(bool allowHasher) const
    {
        return Part::Feature::makeTopoShape(this, TopoDS_Shape(), namingTag(), allowHasher);
    }
    TopoShape makeTopoShape(long tag = 0, bool allowHasher = true) const
    {
        return Part::Feature::makeTopoShape(this, TopoDS_Shape(), tag ? tag : namingTag(), allowHasher);
    }
    TopoShape makeTopoShape(const TopoDS_Shape& newShape, long tag = 0, bool allowHasher = true) const
    {
        return Part::Feature::makeTopoShape(this, newShape, tag ? tag : namingTag(), allowHasher);
    }
    //@}

    App::DocumentObjectExecReturn* recompute() override;
    bool passesBaseThrough() const override
    {
        return _PassedThrough.getValue();
    }
    bool failurePassedThrough() const
    {
        return _FailurePassedThrough.getValue();
    }
    void setFailurePassedThrough(bool on)
    {
        if (_FailurePassedThrough.getValue() != on) {
            _FailurePassedThrough.setValue(on);
        }
    }
    App::DocumentObjectExecReturn* recomputePreview() override;

    short mustExecute() const override;

    /// The Placement is the chain's frame, copied from the first sketch's support or the base
    /// feature (ops#557)
    bool placementIsDerived() const override
    {
        return true;
    }

    /**
     * The properties whose links place this feature's result: each is read in its own Body's
     * coordinates as if they were this feature's (FreeCAD-CH ops#308 T4, ops#325). None by
     * default. What a feature is attached to isn't one: the attacher maps it (ops#318).
     */
    virtual std::vector<const char*> placerProperties() const
    {
        return {};
    }
    /**
     * Whether a placer link (placerProperties()) is in a container placed elsewhere than this
     * feature's Body: another Body or, outside every Body, an App::Part or the document. The
     * first such property goes to `property`, and where it is ("Body B") to `where`
     */
    virtual bool placerElsewhere(const char** property = nullptr, std::string* where = nullptr) const;
    /// placerElsewhere() judged against `body` instead of this feature's own Body: a
    /// MultiTransform reads its steps' links in its own Body (ops#325)
    bool placerElsewhereThan(
        const Body* body,
        const char** property = nullptr,
        std::string* where = nullptr
    ) const;
    /**
     * Copies made for this feature's Body that join it only after the edit's commit (the Pipe
     * panel's, ops#180): until cleared, placerElsewhere() reads them as in the Body
     */
    void setPendingMembers(std::vector<const App::DocumentObject*> objs)
    {
        pendingMembers = std::move(objs);
    }

    /// Check whether the given feature is a datum feature
    static bool isDatum(const App::DocumentObject* feature);

    /// Returns the body the feature is in, or none
    Body* getFeatureBody() const;

    /**
     * Returns the BaseFeature property's object (if any)
     * @param silent if couldn't determine the base feature and silent == true,
     *               silently return a nullptr, otherwise throw Base::Exception.
     *               Default is false.
     */
    virtual Part::Feature* getBaseObject(bool silent = false) const;
    /// Returns the BaseFeature property's shape (if any)
    virtual const TopoDS_Shape& getBaseShape() const;
    /// Returns the BaseFeature property's TopoShape (if any)
    Part::TopoShape getBaseTopoShape(bool silent = false) const;
    /// Returns a linked shape in this feature's Body coordinate system.
    Part::TopoShape getTopoShapeInLocalCoordinates(const App::DocumentObject* object) const;
    /**
     * The inverse of this feature's location, to move base (the base shape) and the shapes the
     * feature uses with it into the feature's own coordinates (ops#310). When base is placed where
     * the feature is, as positionByPrevious() places it, this is the inverse of base's own location:
     * moving base then cancels its location, and sub-shapes of base moved by it stay sub-shapes of
     * the moved base. The inverse of getLocation() is a new datum, which a move composes onto every
     * sub-shape instead, and a boolean keeps it on every sub-shape it leaves untouched: the chains
     * grow by two datums per feature, and every later operation gets slower.
     */
    TopLoc_Location getInverseLocation(const TopoShape& base) const;
    /**
     * Which inputs of a boolean on base makeElementBoolean() is to check, and fix if invalid
     * (ops#310). Only the tools when the base feature's Shape is still the one its last recompute
     * made with a boolean that reported every input valid (booleanInputsValid): checking base
     * again costs about half of each boolean. All of them otherwise, so an invalid base (a raw
     * Pipe, a Pipe fused from an invalid sweep, a dress-up's result, a BaseFeature, a suppressed
     * feature's pass-through, a Shape from undo or a reopened file) is still repaired.
     */
    Part::BooleanInputCheck booleanInputCheck() const;

    // Fills up information about which sub-shapes were generated by the feature
    virtual void getGeneratedShapes(
        std::vector<int>& faces,
        std::vector<int>& edges,
        std::vector<int>& vertices
    ) const;

    virtual void updatePreviewShape();

    PyObject* getPyObject() override;

    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProvider";
    }

    void onChanged(const App::Property* prop) override;
    void onDocumentRestored() override;

    /// Called by Body::removeObject() when this feature's BaseFeature is
    /// rerouted around a deleted feature. Subclasses may reroute only the
    /// subelement links that are known to follow BaseFeature.
    /// FreeCAD-CH: also by an insert and a reorder (ops#127); reorder is true for a reorder's
    /// (Body::reorderObject(), ops#291)
    virtual void onBaseFeatureRerouted(
        App::DocumentObject* oldBase,
        App::DocumentObject* newBase,
        bool reorder
    );

    App::DocumentObject* getSubObject(
        const char* subname,
        PyObject** pyObj,
        Base::Matrix4D* pmat,
        bool transform,
        int depth
    ) const override;


protected:
    /**
     * Set by this feature's boolean during execute() (makeElementBoolean's inputsValid): its result
     * came from a boolean whose inputs were all valid as given (ops#310). Reset at the start of
     * every recompute; a recompute that succeeds with it set vouches for the Shape it leaves.
     * Mutable: some features' booleans run in const helpers (makeShape()).
     */
    mutable bool booleanInputsValid = false;
    /// The check for a boolean on this feature's own result of its previous boolean (a pattern's
    /// next original, a Hole's next hole), from that boolean's report
    Part::BooleanInputCheck ownResultCheck() const
    {
        return booleanInputsValid ? Part::BooleanInputCheck::Tools : Part::BooleanInputCheck::All;
    }
    /**
     * Get a solid of the given shape. If no solid is found an exception is raised.
     */
    TopoShape getSolid(const TopoShape&) const;
    /**
     * The shape to build a result on whose operation takes base as an input (ops#39). In V2 it
     * is makeTopoShape(false): the sections the operation adds carry this feature's ID. In V1
     * it has base's tag, hasher and algorithm, as upstream builds such results on a copy of
     * base, so V1 names stay upstream's.
     */
    TopoShape makeResultShape(const TopoShape& base) const;
    static int countSolids(const TopoDS_Shape&, TopAbs_ShapeEnum type = TopAbs_SOLID);
    static bool relinkToMatchingSubelements(
        App::PropertyLinkSub& link,
        App::DocumentObject* oldBase,
        App::DocumentObject* newBase,
        bool reorder
    );

    /**
     * Fix solids
     */
    TopoShape fixSolids(const TopoShape&);

    /**
     * Checks if the single-solid body rule is fulfilled.
     */
    bool isSingleSolidRuleSatisfied(const TopoDS_Shape&, TopAbs_ShapeEnum type = TopAbs_SOLID);
    SingleSolidRuleMode singleSolidRuleMode() const;

    void updateSuppressedShape();

    /**
     * Set the Material To Body Material object
     */
    void setMaterialToBodyMaterial();

    /// Grab any point from the given face
    static const gp_Pnt getPointFromFace(const TopoDS_Face& f);
    /// Make a shape from a base plane (convenience method)
    static gp_Pln makePlnFromPlane(const App::DocumentObject* obj);
    // TODO: Toponaming April 2024 Deprecated in favor of TopoShape method.  Remove when possible.
    static TopoDS_Shape makeShapeFromPlane(const App::DocumentObject* obj);
    static TopoShape makeTopoShapeFromPlane(const App::DocumentObject* obj);

private:
    // The last recompute failed because a placer is in a Body placed elsewhere (ops#308 R2-2).
    // Not read from the error text in mustExecute(): a recompute sets the texts aside while it
    // runs (ops#126)
    bool failedElsewhere = false;
    // The Shape the last recompute vouched for (booleanInputsValid); a later Shape (undo, a reopen,
    // a pass-through) isn't the same TShape, and is checked again (ops#310)
    TopoDS_Shape vouchedShape;
    std::vector<const App::DocumentObject*> pendingMembers;
};

using FeaturePython = App::FeaturePythonT<Feature>;

}  // namespace PartDesign
