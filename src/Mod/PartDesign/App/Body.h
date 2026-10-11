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

#include <Mod/Part/App/BodyBase.h>
#include <Mod/PartDesign/PartDesignGlobal.h>

namespace App
{
class Origin;
}

namespace PartDesign
{

class Feature;

class PartDesignExport Body: public Part::BodyBase
{
    PROPERTY_HEADER_WITH_OVERRIDE(PartDesign::Body);

public:
    App::PropertyBool AllowCompound;

    /// True if this body feature is active or was active when the document was last closed
    // App::PropertyBool IsActive;

    Body();

    /** @name methods override feature */
    //@{
    /// recalculate the feature
    App::DocumentObjectExecReturn* execute() override;
    short mustExecute() const override;

    /// returns the type name of the view provider
    const char* getViewProviderName() const override
    {
        return "PartDesignGui::ViewProviderBody";
    }
    //@}

    /**
     * Add the feature into the body at the current insert point.
     * The insertion point is the before next solid after the Tip feature
     */
    std::vector<App::DocumentObject*> addObject(App::DocumentObject*) override;
    std::vector<DocumentObject*> addObjects(std::vector<DocumentObject*> obj) override;

    /**
     * Insert the feature into the body after the given feature.
     *
     * @param feature  The feature to insert into the body
     * @param target   The feature relative which one should be inserted the given.
     *                 If target is NULL than insert into the end if where is InsertBefore
     *                 and into the begin if where is InsertAfter.
     * @param after    if true insert the feature after the target. Default is false.
     *
     * @note the method doesn't modify the Tip unlike addObject()
     */
    void insertObject(App::DocumentObject* feature, App::DocumentObject* target, bool after = false);

    void setBaseProperty(App::DocumentObject* feature);

    /// Remove the feature from the body
    std::vector<DocumentObject*> removeObject(DocumentObject* obj) override;
    /// Remove the features from the body, each as removeObject() does (the chain and the Tip are
    /// kept valid, ops#127)
    std::vector<DocumentObject*> removeObjects(std::vector<DocumentObject*> objs) override;

    /** @name The roll-back bar (ops#127, notes/reorder-rollback-design.md section 1)
     *
     * The bar is the Tip. While the edit roll-back point is set (a feature's dialog is open),
     * that point is the bar instead (the effective bar). A Body whose effective bar is not its
     * last solid feature is rolled back: the solid features after the bar, the other members
     * after it that nothing above it uses, and the Body itself are held, i.e. not recomputed and
     * left touched, so rolling forward recomputes what changed above.
     */
    //@{
    /// The edit roll-back point if set, else the Tip
    App::DocumentObject* effectiveBar() const;
    /// The last solid feature in Group, or null
    App::DocumentObject* lastSolidFeature() const;
    /// The effective bar is not the last solid feature (and there is one)
    bool isRolledBack() const;
    /// Is obj held by the bar (obj is this Body or one of its members)?
    bool holds(const App::DocumentObject* obj) const;
    /// The transient edit roll-back point (not saved, not undone), or null
    App::DocumentObject* getEditRollPoint() const;
    /// Sets the edit roll-back point (null clears it); touches nothing
    void setEditRollPoint(App::DocumentObject* obj);
    /// Moves the bar after the solid feature (null: to the top)
    void rollTo(App::DocumentObject* feature);
    /// Moves the bar to the last solid feature
    void rollToEnd();
    //@}

    /** Moves objs (members of this Body) before or after target (a member, or null: the start,
     * after the base feature) in one step (ops#127, notes/reorder-rollback-design.md 2.1): the
     * BaseFeature chain is rewired, every solid whose base changed is rerouted, references from
     * a feature's own inputs into a later solid are re-targeted or parked (and restored when the
     * order allows), and the Tip keeps its place in the list. Plans first: a refusal (a check, a
     * dependency cycle) throws Base::ValueError with nothing changed. Opens no transaction and
     * doesn't recompute.
     */
    void reorderObject(const std::vector<App::DocumentObject*>& objs,
                       App::DocumentObject* target,
                       bool after);

    /**
     * Checks if the given document object lays after the current insert point
     * (place before next solid after the Tip)
     */
    bool isAfterInsertPoint(App::DocumentObject* feature);

    /**
     * Return true if the given feature is a solid feature allowed in a Body. Currently this is only
     * valid for features derived from PartDesign::Feature Return false if the given feature is a
     * Sketch or a Part::Datum feature
     */
    static bool isSolidFeature(const App::DocumentObject* obj);

    /**
     * Return true if the given feature is allowed in a Body. Currently allowed are
     * all features derived from PartDesign::Feature and Part::Datum and sketches
     */
    static bool isAllowed(const App::DocumentObject* obj);
    bool allowObject(DocumentObject* obj) override
    {
        return isAllowed(obj);
    }

    /**
     * Return the body which this feature belongs too, or NULL
     * The only difference to BodyBase::findBodyOf() is that this one casts value to Body*
     */
    static Body* findBodyOf(const App::DocumentObject* feature);

    PyObject* getPyObject() override;

    std::vector<std::string> getSubObjects(int reason = 0) const override;
    App::DocumentObject* getSubObject(
        const char* subname,
        PyObject** pyObj,
        Base::Matrix4D* pmat,
        bool transform,
        int depth
    ) const override;

    void setShowTip(bool enable)
    {
        showTip = enable;
    }

    /**
     * Return the solid feature before the given feature, or before the Tip feature
     * That is, sketches and datum features are skipped
     */
    App::DocumentObject* getPrevSolidFeature(App::DocumentObject* start = nullptr);

    /**
     * Return the next solid feature after the given feature, or after the Tip feature
     * That is, sketches and datum features are skipped
     */
    App::DocumentObject* getNextSolidFeature(App::DocumentObject* start = nullptr);

    // a body is solid if it has features that are solid according to member isSolidFeature.
    bool isSolid();

protected:
    void onSettingDocument() override;

    /// Adjusts the first solid's feature's base on BaseFeature getting set
    void onChanged(const App::Property* prop) override;

    /// Creates the corresponding Origin object
    void setupObject() override;
    /// Removes all planes and axis if they are still linked to the document
    void unsetupObject() override;

    void onDocumentRestored() override;

private:
    /// Sets feature's BaseFeature to newBase (if it differs) and reroutes the references that
    /// follow the base (onBaseFeatureRerouted()); every change of the chain goes through it
    /// (ops#127, notes/reorder-rollback-design.md 2.2)
    void rerouteBase(App::DocumentObject* feature, App::DocumentObject* newBase);

    fastsignals::scoped_connection connection;
    bool showTip = false;
    /// The edit roll-back point (ops#127): transient, not saved, not undone
    App::DocumentObject* editRollPoint = nullptr;
    /// The Tip's shape that execute() last copied, before the placement bake (ops#127, R7): a
    /// Tip whose shape is the same doesn't rewrite Shape
    Part::TopoShape lastTipShape;
};

}  // namespace PartDesign
