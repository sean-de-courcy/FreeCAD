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

#include <Mod/Part/Gui/ViewProvider.h>
#include <Mod/PartDesign/PartDesignGlobal.h>
#include <Mod/PartDesign/App/Feature.h>
#include <Gui/ViewProviderPart.h>
#include <Gui/ViewProviderOriginGroupExtension.h>
#include <QCoreApplication>
#include <fastsignals/signal.h>

class SoGroup;
class SoSeparator;
class SbBox3f;
class SoGetBoundingBoxAction;
namespace PartDesignGui
{

/** ViewProvider of the Body feature
 *  This class manages the visual appearance of the features in the
 *  Body feature. That means while editing all visible features are shown.
 *  If the Body is not active it shows only the result shape (tip).
 * \author jriegel
 */
class PartDesignGuiExport ViewProviderBody: public PartGui::ViewProviderPart,
                                            public Gui::ViewProviderOriginGroupExtension
{
    Q_DECLARE_TR_FUNCTIONS(PartDesignGui::ViewProviderBody)
    PROPERTY_HEADER_WITH_EXTENSIONS(PartDesignGui::ViewProviderBody);

public:
    /// constructor
    ViewProviderBody();
    /// destructor
    ~ViewProviderBody() override;

    App::PropertyEnumeration DisplayModeBody;

    void attach(App::DocumentObject*) override;

    bool doubleClicked() override;
    void setupContextMenu(QMenu* menu, QObject* receiver, const char* member) override;
    bool isActiveBody();
    void toggleActiveBody();

    std::vector<std::string> getDisplayModes() const override;
    void setDisplayMode(const char* ModeName) override;
    void setOverrideMode(const std::string& mode) override;

    bool onDelete(const std::vector<std::string>&) override;

    /// Update the children's highlighting when triggered
    void updateData(const App::Property* prop) override;
    /// unify children visuals
    void onChanged(const App::Property* prop) override;

    /**
     * Return the bounding box of visible features
     * @note datums are counted as their base point only
     */
    SbBox3f getBoundBox();

    PartDesign::Feature* getShownFeature() const;
    ViewProvider* getShownViewProvider() const;

    /** Check whether objects can be added to the view provider by drag and drop */
    bool canDropObjects() const override;
    /** Check whether the object can be dropped to the view provider by drag and drop */
    bool canDropObject(App::DocumentObject*) const override;
    /** Add an object to the view provider by drag and drop */
    void dropObject(App::DocumentObject*) override;
    bool canDragObjectToTarget(App::DocumentObject* obj, App::DocumentObject* target) const override;
    /* Check whether the object accept reordering of its children during drop.*/
    bool acceptReorderingObjects() const override
    {
        return true;
    };

    /** @name The roll-back bar and reordering in the tree (ops#127) */
    //@{
    int treeBarIndex(const std::vector<App::DocumentObject*>& children) const override;
    bool moveTreeBar(TreeBarMove move, App::DocumentObject* child) override;
    /// Members dropped among the Body's rows: Body::reorderObject, in the drop's transaction
    bool reorderObjects(const std::vector<App::DocumentObject*>& objs,
                        App::DocumentObject* target,
                        bool after) override;
    /** Moves the bar after the solid feature (null: to the top) or to the end, in one command
     * that shows the feature the bar follows; throws Base::Exception (the command aborted)
     */
    void rollBar(App::DocumentObject* feature, bool toEnd = false);
    /** The solid feature that "Roll to here" on member puts the bar after (null: the top): a
     * solid feature itself; a sketch, datum or other member, the solid feature before the first
     * solid feature that uses it, else before it (decision 17, Q3)
     */
    static App::DocumentObject* barFeatureFor(const PartDesign::Body* body,
                                              App::DocumentObject* member);
    /// The features show one at a time, as in "Through" mode: the mode says so, or rolled back
    bool showsThrough() const;
    //@}

    /** @name The edit roll-back (ops#127, notes/reorder-rollback-design.md 5.4)
     *
     * While a member's dialog is open, the Body is rolled back to it through the transient edit
     * roll point (Body::setEditRollPoint): the saved bar (the Tip) is unchanged. "Final" lifts it.
     */
    //@{
    /** The edit roll point for member: a solid feature itself; for a sketch, datum or other
     * member, the solid feature before its first user (decision 17, Q3) or, at the top, the
     * member just before the first solid feature; null when nothing can be held
     */
    static App::DocumentObject* editRollPointFor(const PartDesign::Body* body,
                                                 App::DocumentObject* member);
    /// Final on: the end result while member's dialog is open; off: the model as member sees it
    static void setEditFinal(App::DocumentObject* member, bool final);
    /// After member's dialog recomputed member alone: in Final, the features after it compute
    static void recomputeEditTail(App::DocumentObject* member);
    //@}

    /// Override to return the color of the tip instead of the body, which doesn't really have color
    std::map<std::string, Base::Color> getElementColors(const char* element) const override;

    void show() override;

protected:
    /// Copy over all visual properties to the child features
    void unifyVisualProperty(const App::Property* prop);
    /// Set Feature viewprovider into visual body mode
    void setVisualBodyMode(bool bodymode);

private:
    static const char* BodyModeEnum[];

    void afterRecompute(const App::Document&, const std::vector<App::DocumentObject*>& recomputedObjs);
    fastsignals::scoped_connection m_RecomputedConn;
    void onChangedObject(const Gui::ViewProvider& vp, const App::Property& prop);
    fastsignals::scoped_connection m_ChangedConn;
    void refreshOverlays();
    /// Applies DisplayModeBody, or "Through" while rolled back (ops#127)
    void applyBodyDisplay();
    bool displayedThrough = false;

    void onInEdit(const Gui::ViewProviderDocumentObject& vp);
    void onResetEdit(const Gui::ViewProviderDocumentObject& vp);
    /// Sets the edit roll point and shows it: the Body's display, the tree's bar row and held look
    void setEditRoll(App::DocumentObject* point);
    /// The point in Final: none, or member itself when the saved bar holds it (rolled forward)
    App::DocumentObject* finalPointFor(App::DocumentObject* member) const;
    fastsignals::scoped_connection m_InEditConn;
    fastsignals::scoped_connection m_ResetEditConn;
    /// The member whose dialog holds the edit roll-back, or null
    App::DocumentObject* editedMember = nullptr;
    bool editFinal = false;
};

}  // namespace PartDesignGui
