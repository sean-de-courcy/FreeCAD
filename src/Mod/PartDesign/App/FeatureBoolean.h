// SPDX-License-Identifier: LGPL-2.1-or-later

/******************************************************************************
 *   Copyright (c) 2013 Jan Rheinländer <jrheinlaender@users.sourceforge.net> *
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

#include <App/GeoFeatureGroupExtension.h>
#include <App/PropertyStandard.h>
#include "FeatureRefine.h"


namespace PartDesign
{

/**
 * Abstract superclass of all features that are created by transformation of another feature
 * Transformations are translation, rotation and mirroring
 */
class PartDesignExport Boolean: public PartDesign::FeatureRefine, public App::GeoFeatureGroupExtension
{
    PROPERTY_HEADER_WITH_EXTENSIONS(PartDesign::Boolean);

public:
    Boolean();

    /// The type of the boolean operation
    App::PropertyEnumeration Type;
    /**
     * Compatibility property to preserve the historic transformed-body Boolean behavior
     * in restored documents. New Boolean features use Body-local linked geometry.
     */
    App::PropertyBool UseLegacyBodyPlacement;
    /** Onshape's Keep tools (FreeCAD-CH ops#640 rank 28): on, the tool parts stay parts; off, the
     * Boolean consumes them, and they leave the Parts list (consumerOf). A new Boolean takes the
     * value its dialog last accepted (the user parameter BooleanKeepTools); old files read false.
     * An Intersect that misses keeps its part as it was with Keep tools on (hands-on A-2' c)
     */
    App::PropertyBool KeepTools;
    /** The tools a Union left as they were (ops#640 rank 3b, hands-on A-2' b): they touch nothing
     * it fuses, so it doesn't fuse them, and they stay parts. Set at each compute
     */
    App::PropertyLinkListHidden SeparateTools;
    /// A studio Boolean's tool parts, by part id (FreeCAD-CH ops#654, P5)
    App::PropertyStringList StudioTools;

    /** @name methods override feature */
    //@{
    /// Recalculate the feature
    App::DocumentObjectExecReturn* execute() override;
    void updatePreviewShape() override;
    short mustExecute() const override;
    std::vector<App::DocumentObject*> addObject(App::DocumentObject* object) override;
    std::vector<App::DocumentObject*> addObjects(std::vector<App::DocumentObject*> objects) override;
    std::vector<App::DocumentObject*> setObjects(std::vector<App::DocumentObject*> objects) override;
    std::vector<App::DocumentObject*> removeObject(App::DocumentObject* object) override;
    std::vector<App::DocumentObject*> removeObjects(std::vector<App::DocumentObject*> objects) override;
    bool hasObject(const App::DocumentObject* object, bool recursive = false) const override;
    /// returns the type name of the view provider
    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderBoolean";
    }
    void onChanged(const App::Property* prop) override;
    void onDocumentRestored() override;
    //@}

    /// Set while its panel edits the tools: an empty list then computes nothing instead of failing
    void setSettingUp(bool on)
    {
        settingUp = on;
    }

    /** @name Merge (FreeCAD-CH ops#325, B+ Stage 1 3b, notes/bplus-stage1-design.md 2.6)
     * A Merge is a Fuse in the surviving part whose tools are other parts' last solid features.
     * Each absorbed Body names it in a hidden MergedInto link (Hidden scope: no dependency) and
     * is hidden; a solid added to it after its merged feature fails at recompute. Only a Merge
     * has MergeAccepted: until it is set, the Merge warns "Merged <part> into <part>".
     */
    //@{
    /// Merges @p bodies into the part of @p at: a solid feature, the Merge going right after it,
    /// or a Body, the Merge going at its Tip. Refused, with the reason, before anything changes.
    /// No recompute.
    static Boolean* makeMerge(App::DocumentObject* at, const std::vector<App::DocumentObject*>& bodies);
    /// Whether this Boolean is a Merge
    bool isMerge() const;
    /// The Merge @p body is merged into, or null
    static Boolean* mergeOf(const App::DocumentObject* body);
    /// The Bodies merged into this Merge, in document order
    std::vector<App::DocumentObject*> mergedBodies() const;
    /// Why @p feature fails: a solid after its merged Body's merged feature, or empty
    static std::string mergeLock(const App::DocumentObject* feature);
    /// The Merge right after @p feature in its Body, based on it (makeMerge's place), or null
    static Boolean* mergeAfter(const App::DocumentObject* feature);
    /** The Merge that is @p feature's merge scope (ops#640 rank 1): mergeAfter, accepted, after an
     * additive profile feature (an Extrude's Add), or null. It is part of the feature: it has no
     * row of its own in the Features list, and it goes when the feature is deleted
     * (Body::removeObject). A Merge Parts made and not accepted, or one after a cut, is its own.
     */
    static Boolean* scopeMerge(const App::DocumentObject* feature);
    /** The merge scope of @p feature, a solid feature in a part (FreeCAD-CH ops#640 rank 1): the
     * parts in @p bodies are merged right after it, the others it merged no more. Changes the Merge
     * after it in place, makes one (makeMerge) or, with no bodies, deletes it; the Merge is
     * accepted (no Warning: Onshape's merge is a plain feature). Refused, with the reason, before
     * anything changes. Returns the Merge, or null; no recompute.
     */
    static Boolean* setMergeScope(
        App::DocumentObject* feature,
        const std::vector<App::DocumentObject*>& bodies
    );
    //@}

    /** The Boolean that consumes @p body, a part one of its tools is in, or null (FreeCAD-CH
     * ops#640 rank 28, B3-3a): a Boolean in effect (not a Merge, not suppressed or failed, not
     * after its part's bar) with Keep tools off, the tool not one a Union left separate. A
     * consumed part isn't a part any more: Onshape's Boolean deletes its tools
     */
    static Boolean* consumerOf(const App::DocumentObject* body);

protected:
    void handleChangedPropertyName(
        Base::XMLReader& reader,
        const char* TypeName,
        const char* PropName
    ) override;


private:
    Part::TopoShape getBooleanTopoShape(const App::DocumentObject* object) const;
    /// Why this Merge can't compute: its tools aren't its absorbed parts' features
    std::string mergeProblem() const;
    /// Warns "Merged <part> into <part>" until accepted
    void warnMerged();
    /// Where the tools' Bodies are in this one's frame
    std::vector<Base::Placement> toolFrames() const;
    /// toolFrames() at the last compute: a Merge whose part moved runs again (polled, as the
    /// other readers of a moved Body, ops#325 1b-1)
    std::vector<Base::Placement> lastToolFrames;

    static const char* TypeEnums[];
    bool settingUp = false;
};

}  // namespace PartDesign
